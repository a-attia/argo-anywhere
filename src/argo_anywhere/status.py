"""Local status + health surface (no ANL contact of its own).

This is the ANL-free data layer the P2 dashboard renders and the
``argo-anywhere info`` command prints: package + engine versions, local tunnel
listeners, and an on-demand localhost health poll.

Note on :func:`channel_health`: it issues a plain HTTP GET to
``http://127.0.0.1:<port>/health``. That endpoint is answered by argo-proxy on
the compute node *through* an already-established SSH tunnel, so a caller should
treat invoking it as reaching ANL and gate it on user intent accordingly (the
web UI polls it on a user action, not automatically). It never opens a tunnel
or runs ssh itself; against a down port it simply reports ``up=False``.
"""

from __future__ import annotations

import hashlib
import os
import platform
import re
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path

from . import __version__
from ._engine import engine_bytes

_SCRIPT_VERSION_RE = re.compile(rb'^SCRIPT_VERSION="?([^"\n]+)"?', re.MULTILINE)

#: The engine's state dir (matches argo-anywhere.sh STATE_DIR); local only.
STATE_DIR = Path(os.path.expanduser("~/.config/argo_anywhere"))

#: The canonical install dir (D-023; matches argo-anywhere.sh CANONICAL_HOME).
#: Also the cwd the ``app`` / ``web`` subcommands chdir to on startup (D-031
#: §2.2 D3a): the pywebview window (or the browser-hosted server) starts here
#: instead of ``$HOME``, so any code path that forgets to pass a per-launch cwd
#: lands somewhere the user can identify as argo-anywhere's, not their home.
APP_HOME = Path(os.path.expanduser("~/.argo_anywhere"))

#: The web UI's persisted state (MRU cwd list, divider position, theme).
#: Written atomically; schema-versioned. Populated by Tasks 5 + 5.5.
WEB_STATE_FILE = APP_HOME / "web_state.json"


def ensure_app_home() -> Path:
    """Create :data:`APP_HOME` if it doesn't exist yet.

    D-031 §2.3 A5: ``~/.argo_anywhere/`` may not have been bootstrapped yet
    (D-023 first-run bootstrap fires from ``mode_client``; the web UI doesn't
    go through that). Call this before ``os.chdir(APP_HOME)`` to ensure the
    dir is present. Safe to call repeatedly.
    """
    APP_HOME.mkdir(parents=True, exist_ok=True)
    return APP_HOME


def app_cwd_display() -> str:
    """A human-readable rendering of the app's cwd for the UI status strip.

    Collapses ``$HOME`` to ``~`` for compactness (``/Users/attia/.argo_anywhere``
    -> ``~/.argo_anywhere``). Called by ``/api/status`` (via ``package_info``)
    and surfaced in the web UI's launcher header + About popover (D-031 D3a).
    """
    cwd = Path(os.getcwd()).resolve()
    try:
        home = Path.home().resolve()
        rel = cwd.relative_to(home)
        return f"~/{rel}" if str(rel) != "." else "~"
    except (ValueError, RuntimeError):
        return str(cwd)


def cached_state(state_dir: Path | None = None) -> dict:
    """Read the engine's cached identity (user / node / port) -- local files.

    Returns a dict with those keys; a value is ``None`` if its cache file is
    absent. ``port`` is coerced to ``int`` when present and numeric.
    """
    base = state_dir if state_dir is not None else STATE_DIR
    out: dict = {"user": None, "node": None, "port": None}
    for key in out:
        f = base / key
        try:
            val = f.read_text().strip()
        except OSError:
            continue
        if key == "port":
            out[key] = int(val) if val.isdigit() else None
        else:
            out[key] = val or None
    return out


def engine_version() -> str:
    """The vendored engine's internal ``SCRIPT_VERSION`` (a component tag)."""
    m = _SCRIPT_VERSION_RE.search(engine_bytes())
    return m.group(1).decode() if m else "unknown"


def engine_sha256() -> str:
    """SHA-256 of the vendored engine (full hex)."""
    return hashlib.sha256(engine_bytes()).hexdigest()


def package_info() -> dict:
    """Versions + runtime facts. Package version is authoritative (D-029); the
    engine version is an internal component tag.

    D-031 D3a: ``app_cwd`` + ``app_cwd_short`` report where the web-UI process
    itself is running (distinct from where a spawned tool will start; that's
    controlled per-launch via the launcher's cwd field, Task 3).
    """
    return {
        "package_version": __version__,
        "engine_version": engine_version(),
        "engine_sha256_short": engine_sha256()[:12],
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "app_cwd": str(Path(os.getcwd()).resolve()),
        "app_cwd_short": app_cwd_display(),
    }


@dataclass(frozen=True)
class ChannelHealth:
    port: int
    up: bool
    status: str | None
    latency_ms: int | None
    error: str | None = None

    def as_dict(self) -> dict:
        return asdict(self)


def channel_health(port: int, *, timeout: float = 3.0) -> ChannelHealth:
    """Poll ``http://127.0.0.1:<port>/health`` once. Never raises."""
    url = f"http://127.0.0.1:{port}/health"
    start = time.monotonic()
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310 (loopback only)
            body = resp.read(4096).decode("utf-8", "replace").strip()
            latency = int((time.monotonic() - start) * 1000)
            return ChannelHealth(port=port, up=True, status=body or "ok", latency_ms=latency)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return ChannelHealth(port=port, up=False, status=None, latency_ms=None, error=str(exc))


@dataclass(frozen=True)
class Listener:
    port: int
    pid: int
    command: str

    def as_dict(self) -> dict:
        return asdict(self)


def local_listeners(ports: list[int] | None = None) -> list[Listener]:
    """Loopback TCP listeners, via ``lsof`` (best-effort; empty if lsof absent).

    Optionally filtered to ``ports``. Only ``127.0.0.1`` / ``[::1]`` listeners
    are reported (the tunnels this tool creates are loopback-bound).
    """
    lsof = shutil.which("lsof")
    if not lsof:
        return []
    try:
        out = subprocess.run(
            [lsof, "-nP", "-iTCP", "-sTCP:LISTEN"],
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return []

    wanted = set(ports) if ports else None
    seen: set[tuple[int, int]] = set()
    listeners: list[Listener] = []
    for line in out.splitlines():
        fields = line.split()
        if len(fields) < 9:
            continue
        command, pid_s, name = fields[0], fields[1], fields[-2] if fields[-1] == "(LISTEN)" else fields[-1]
        # NAME looks like 127.0.0.1:64742 or [::1]:8799
        m = re.search(r"(?:127\.0\.0\.1|\[::1\]):(\d+)$", name)
        if not m:
            continue
        try:
            port, pid = int(m.group(1)), int(pid_s)
        except ValueError:
            continue
        if wanted is not None and port not in wanted:
            continue
        if (port, pid) in seen:  # lsof prints IPv4 + IPv6 rows for one process
            continue
        seen.add((port, pid))
        listeners.append(Listener(port=port, pid=pid, command=command))
    return listeners
