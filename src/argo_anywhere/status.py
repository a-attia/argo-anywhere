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
import json
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


#: Mux-socket basename prefixes the engine writes (``argo-anywhere-%r-%h-%p``);
#: the legacy ``argo-opencode-`` form still exists on v1.x masters mid-upgrade.
_MUX_PREFIXES = ("argo-anywhere-", "argo-opencode-")

_MUX_SOCKET_RE = re.compile(
    r"[/=\s](argo-(?:anywhere|opencode)-\S+)"
)


def tunnel_destination(port: int) -> str | None:
    """Host the tunnel on ``port`` actually forwards to, or ``None``.

    Python mirror of the engine's ``local_tunnel_destination`` (D-032-style
    coupling: if one changes, change both). Pure local inspection -- ``lsof``
    to find the listener pid, ``ps`` to read its command line, then parse the
    ControlPath socket basename, which openssh names after the destination it
    is really talking to. No SSH, no network, no ANL contact, consistent with
    this module's "no ANL contact of its own" contract.

    Why this exists (web-UI Defect 3): the dashboard used to light the node hop
    and render ``localhost:PORT -> <node>`` whenever *anything* held the cached
    port, taking the node name from the cache. That is reachability presented
    as topology -- exactly the inference that let the 2026-08-10 incident show
    ALL GREEN while traffic went through a stranger's argo-proxy. A cached name
    is a memory of a past connection, not evidence about the current one.

    Returns ``None`` whenever the destination cannot be established -- no
    listener, no ``lsof``/``ps``, an unparseable command line, or a listener
    that is not one of our tunnels. Callers must treat ``None`` as "unknown",
    never as "fine".
    """
    lsof = shutil.which("lsof")
    if not lsof:
        return None
    try:
        out = subprocess.run(
            [lsof, "-nP", f"-i:{port}", "-sTCP:LISTEN", "-t"],
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return None

    pid = next((ln.strip() for ln in out.splitlines() if ln.strip()), None)
    if not pid:
        return None

    try:
        cmd = subprocess.run(
            ["ps", "-o", "command=", "-p", pid],
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    if not cmd:
        return None

    match = _MUX_SOCKET_RE.search(cmd)
    if not match:
        return None
    basename = match.group(1)

    for prefix in _MUX_PREFIXES:
        if basename.startswith(prefix):
            basename = basename[len(prefix) :]
            break
    else:  # pragma: no cover - the regex guarantees one of the prefixes
        return None

    # Strip the trailing -PORT (numeric), then the leading USER- field. ANL
    # usernames are alphanumeric, so the first hyphen-separated field is the
    # user and the remainder is the host.
    without_port = re.sub(r"-\d+$", "", basename)
    _, _, host = without_port.partition("-")
    if not host:
        return None
    # Sanity: a hostname has a dot or is a bare alphanumeric label.
    if "." in host or host.isalnum():
        return host
    return None


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


@dataclass(frozen=True)
class DiscoveredChannel:
    """A live argo-anywhere tunnel found by inspection, not by the cache."""

    port: int
    pid: int
    node: str

    def as_dict(self) -> dict:
        return asdict(self)


def discover_channels() -> list[DiscoveredChannel]:
    """Every loopback listener that is one of our SSH tunnels, cache-ignored.

    The dashboard used to answer "are we connected?" with "is something
    listening on the *cached* port?". That makes the cache load-bearing for a
    question it cannot answer: the cache records what a run intended, and a run
    that aborted, failed, or moved ports leaves it naming a port with nothing
    on it. Observed 2026-08-12 — the cache said one port, a healthy channel was
    on another, and the dashboard reported "not connected" while a working
    session ran in the embedded terminal beside it.

    Discovery inverts that. A tunnel is identified by what it *is* — an ssh
    process whose ControlPath names an argo-anywhere socket
    (:func:`tunnel_destination`) — so the cache becomes a hint about which
    channel is the interesting one, never the evidence that one exists.

    Local only: ``lsof`` + ``ps``, no network, no ANL contact. Empty list means
    no tunnel found, which is a real answer; it never means "unknown".
    """
    found: list[DiscoveredChannel] = []
    for listener in local_listeners():
        if listener.command not in ("ssh", "sshd"):
            continue
        node = tunnel_destination(listener.port)
        if node:
            found.append(
                DiscoveredChannel(port=listener.port, pid=listener.pid, node=node)
            )
    return sorted(found, key=lambda c: c.port)


#: Where each CLI tool records the endpoint it talks to. Mirrors the engine's
#: OPENCODE_GLOBAL_CONFIG / CLAUDECODE_GLOBAL_CONFIG / AIDER_GLOBAL_CONFIG and
#: the readers in ``enumerate_client_ports``. **If a tool is added to the
#: engine's registry, add it here too** -- a tool absent from this table is
#: invisible to the dashboard's coherence view, which is exactly how aider went
#: unnoticed on the engine side until 2026-08-12.
_TOOL_CONFIGS: tuple[tuple[str, str], ...] = (
    ("opencode", "~/.config/opencode/config.json"),
    ("claudecode", "~/.claude/settings.json"),
    ("aider", "~/.aider.conf.yml"),
)

_URL_PORT_RE = re.compile(r"https?://[^:/]+:(\d+)")


@dataclass(frozen=True)
class ToolConfig:
    """What one CLI tool's config currently points at."""

    tool: str
    path: str
    #: Port parsed from the config, or ``None`` when the tool has no config
    #: (never configured) or the endpoint could not be parsed.
    port: int | None
    configured: bool

    def as_dict(self) -> dict:
        return asdict(self)


def _port_from_opencode(path: Path) -> int | None:
    try:
        data = json.loads(path.read_text())
        url = data["provider"]["argo"]["options"]["baseURL"]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    m = _URL_PORT_RE.search(str(url))
    return int(m.group(1)) if m else None


def _port_from_claudecode(path: Path) -> int | None:
    try:
        data = json.loads(path.read_text())
        url = data.get("env", {}).get("ANTHROPIC_BASE_URL", "")
    except (OSError, ValueError, AttributeError, TypeError):
        return None
    m = _URL_PORT_RE.search(str(url))
    return int(m.group(1)) if m else None


def _port_from_aider(path: Path) -> int | None:
    # Text scrape rather than a YAML parse, matching the engine: PyYAML is a
    # compute-node dependency, not a laptop one, and the line we own is one we
    # wrote ourselves in a fixed shape.
    try:
        for line in path.read_text().splitlines():
            if line.strip().startswith("openai-api-base:"):
                m = _URL_PORT_RE.search(line)
                return int(m.group(1)) if m else None
    except OSError:
        return None
    return None


_TOOL_READERS = {
    "opencode": _port_from_opencode,
    "claudecode": _port_from_claudecode,
    "aider": _port_from_aider,
}


def client_tool_configs() -> list[ToolConfig]:
    """What each CLI tool's config points at right now.

    Python mirror of the engine's ``enumerate_client_ports``; keep the two in
    step (same lockstep discipline as ``tunnel_destination`` ↔
    ``local_tunnel_destination``).

    Exists so the dashboard can answer the question the CLI answers after every
    ``connect``: which tools are ready, which point somewhere stale, and which
    were never set up. Before this, the web UI showed only *which tools exist*
    -- so a user whose channel had moved saw three cheerful chips and no hint
    that two of their tools would fail to connect.

    Local only: reads three files. No network, no subprocess.
    """
    out: list[ToolConfig] = []
    for tool, raw in _TOOL_CONFIGS:
        path = Path(os.path.expanduser(raw))
        if not path.is_file():
            out.append(ToolConfig(tool=tool, path=str(path), port=None,
                                  configured=False))
            continue
        port = _TOOL_READERS[tool](path)
        out.append(ToolConfig(tool=tool, path=str(path), port=port,
                              configured=port is not None))
    return out
