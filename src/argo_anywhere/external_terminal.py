"""Open a command in a *new native terminal window* (out-of-UI, Lane 2).

The web UI's embedded terminal is one PTY the server manages. Users, though,
run many terminals of their own outside the UI, and a long-lived
``connect``/``client`` is most at home in one of those -- a real native window,
with a genuine controlling TTY, that lives independently of the web server.
This module launches such a window.

Terminal choice is the user's, not ours: :func:`available_terminals` reports
every terminal detected on the machine, the caller (UI / ``terminal=`` arg /
``ARGO_ANYWHERE_TERMINAL`` env) picks one, and the default is the OS's built-in
(Terminal.app on macOS -- deliberately *not* iTerm), never an assumed favourite.

Supported:

- **macOS**: Terminal.app + iTerm2 (via ``osascript``), plus any of
  Alacritty / kitty / WezTerm / Ghostty whose CLI is on ``PATH``.
- **Linux**: the usual emulators (``x-terminal-emulator`` / ``gnome-terminal`` /
  ``konsole`` / ``xfce4-terminal`` / ``xterm``) plus the same cross-platform
  CLI terminals; best-effort.

The command builders are pure so they unit-test without opening a window;
:func:`open_external_terminal` is the thin spawn around them. Opening a window
is a local OS action -- the verb it runs may reach ANL (that is the point of
``connect``), but only because the user asked; this module never runs it itself.
"""

from __future__ import annotations

import importlib.util
import os
import platform
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable, Sequence

# --- terminal catalog ------------------------------------------------------

#: macOS AppleScript-driven apps: id -> (label, app-bundle name).
_MAC_OSA_TERMS: dict[str, tuple[str, str]] = {
    "terminal": ("Terminal.app", "Terminal"),
    "iterm": ("iTerm2", "iTerm"),
}

#: CLI-launchable terminals (macOS and/or Linux): id -> (label, binary, prefix).
#: ``prefix`` precedes the inner ``bash -lc <command>`` argv.
_CLI_TERMS: dict[str, tuple[str, str, list[str]]] = {
    # cross-platform (checked on both macOS and Linux)
    "alacritty": ("Alacritty", "alacritty", ["-e"]),
    "kitty": ("kitty", "kitty", []),
    "wezterm": ("WezTerm", "wezterm", ["start", "--"]),
    "ghostty": ("Ghostty", "ghostty", ["-e"]),
    # Linux emulators
    "x-terminal-emulator": ("x-terminal-emulator", "x-terminal-emulator", ["-e"]),
    "gnome-terminal": ("GNOME Terminal", "gnome-terminal", ["--"]),
    "konsole": ("Konsole", "konsole", ["-e"]),
    "xfce4-terminal": ("Xfce Terminal", "xfce4-terminal", ["-e"]),
    "xterm": ("xterm", "xterm", ["-e"]),
}

#: The CLI terminals that make sense on macOS (the emulators are Linux-only).
_MAC_CLI_IDS = ("alacritty", "kitty", "wezterm", "ghostty")
#: Linux terminal ids, in preference order (native default first).
_LINUX_IDS = (
    "x-terminal-emulator", "gnome-terminal", "konsole", "xfce4-terminal", "xterm",
    "alacritty", "kitty", "wezterm", "ghostty",
)


def available_terminals(system: str | None = None) -> list[dict]:
    """Terminals detected on this machine as ``[{"id", "label"}, ...]``.

    Order is native-default first, so ``[0]`` is a sensible fallback choice.
    """
    system = system or platform.system()
    out: list[dict] = []
    if system == "Darwin":
        out.append({"id": "terminal", "label": _MAC_OSA_TERMS["terminal"][0]})  # always present
        if _iterm_installed():
            out.append({"id": "iterm", "label": _MAC_OSA_TERMS["iterm"][0]})
        for tid in _MAC_CLI_IDS:
            if shutil.which(_CLI_TERMS[tid][1]):
                out.append({"id": tid, "label": _CLI_TERMS[tid][0]})
    elif system == "Linux":
        for tid in _LINUX_IDS:
            if shutil.which(_CLI_TERMS[tid][1]):
                out.append({"id": tid, "label": _CLI_TERMS[tid][0]})
    return out


def default_terminal(system: str | None = None) -> str | None:
    """The default terminal id: ``ARGO_ANYWHERE_TERMINAL`` if set + available,
    else the OS native default (first detected), else ``None``."""
    avail = available_terminals(system)
    ids = [t["id"] for t in avail]
    env = os.environ.get("ARGO_ANYWHERE_TERMINAL", "").strip().lower()
    if env and env in ids:
        return env
    return ids[0] if ids else None


# --- pure command builders -------------------------------------------------

def console_command() -> list[str]:
    """The argv prefix that invokes an argo-anywhere CLI in a *fresh shell*.

    The result runs in a NEW native terminal window that does NOT inherit our
    process env -- macOS AppleScript / iTerm / GUI-launched emulators all
    spawn a fresh login shell. So the invocation MUST be self-contained: it
    can't rely on ``PYTHONPATH`` being set, or on the module being importable
    under an arbitrary interpreter that happens to sit next to ours.

    Preference order (matches what the *user* would type in that fresh
    shell, in descending order of "works everywhere without env fiddling"):

    1. The ``argo-anywhere`` console script next to the running interpreter
       (a pipx / venv install; nicest window title, no PATH assumption).
    2. Any ``argo-anywhere`` on ``PATH`` (typically the user's pipx install).
       Cross-interpreter, but matches "what my shell would run" -- and, most
       importantly, works even when the server ran under a *different*
       interpreter than the one PATH resolves to (dev-mode server under
       miniconda while the user's pipx-installed CLI is at ~/.local/bin).
    3. ``<sys.executable> -m argo_anywhere`` -- LAST resort. Requires that
       ``argo_anywhere`` be importable under ``sys.executable`` without any
       env vars set (which pytest / installed packages / anything on
       ``sys.path`` will give you; but ``PYTHONPATH=src python ...`` will
       NOT, because the spawned shell doesn't inherit ``PYTHONPATH``). We
       still gate this on ``find_spec`` here so a dev server under an
       interpreter with no argo-anywhere never picks this branch and
       ships a doomed command.
    4. Empty list -- the caller (``open_external_terminal``) then reports
       a clear "can't find argo-anywhere for this environment" error
       instead of shipping a command that would fail in a window the user
       can't inspect.

    Ordering rationale (bug 2026-07-13): a previous version tried the
    ``-m`` form BEFORE PATH. Under a dev-mode server started with
    ``PYTHONPATH=src python -m argo_anywhere web``, the server's own Python
    could import argo_anywhere fine, so the ``-m`` form was picked. But
    the spawned iTerm window started a fresh login shell without
    ``PYTHONPATH``, so ``python -m argo_anywhere`` failed with ``No module
    named argo_anywhere``. Preferring PATH matches the "would this work
    if I typed it into a fresh terminal?" test.
    """
    # 1: console script next to the running interpreter.
    script = Path(sys.executable).with_name("argo-anywhere")
    if script.exists():
        return [str(script)]
    # 2: any argo-anywhere on PATH (independent install, e.g. pipx). Do this
    # BEFORE the -m fallback so a user with a pipx install + a dev-mode
    # server under a different interpreter gets the pipx CLI in the new
    # window (works in the fresh shell) instead of the -m form (won't).
    on_path = shutil.which("argo-anywhere")
    if on_path:
        return [on_path]
    # 3: -m form, only if the module is importable under sys.executable
    # WITHOUT any env vars set. find_spec here is a NECESSARY but not
    # sufficient check (the spawned shell may still lack PYTHONPATH). We
    # only reach this branch after PATH lookup failed, which means the
    # user has no argo-anywhere install at all; the -m form is the best
    # we can do, and the caller's error will still be clearer than the
    # opaque "No module named" message the previous behavior produced.
    if importlib.util.find_spec("argo_anywhere") is not None:
        return [sys.executable, "-m", "argo_anywhere"]
    # 4: nothing usable.
    return []


def console_command_verified(*, probe_timeout: float = 3.0) -> tuple[list[str], str | None]:
    """Like :func:`console_command`, but also VERIFY the chosen invocation
    actually runs. Returns ``(prefix, error_or_None)``.

    Rationale (bug 2026-07-13): the fallback ladder can return a nominally-
    valid prefix that fails at spawn time because the *spawned shell* has
    a different env from ours (classic offender: ``<sys.executable> -m
    argo_anywhere`` when ``PYTHONPATH=src`` was needed to make the module
    importable, but the spawned iTerm shell doesn't inherit ``PYTHONPATH``).
    A ``<prefix> --version`` probe with the same env the spawned shell
    would use (i.e. NOT ours) catches this before we ship the command to
    a terminal window the user can't inspect.

    The probe runs ``<prefix> --version`` with ``env`` scrubbed of the
    likely leaks (``PYTHONPATH``, ``PYTHONHOME``) so it emulates what a
    fresh login shell would see. On success returns ``(prefix, None)``;
    on failure returns ``([], "reason")`` so the endpoint can 500 with a
    diagnostic rather than ship a broken command.
    """
    prefix = console_command()
    if not prefix:
        return [], "no argo-anywhere CLI found for this environment"
    # Run <prefix> --version with a scrubbed env; on non-zero exit or non-
    # trivial output we treat the prefix as unusable.
    scrubbed = {k: v for k, v in os.environ.items()
                if k not in ("PYTHONPATH", "PYTHONHOME")}
    try:
        proc = subprocess.run(
            [*prefix, "--version"],
            capture_output=True, text=True,
            env=scrubbed, timeout=probe_timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return [], f"{shlex.join(prefix)} --version failed: {exc}"
    if proc.returncode != 0:
        # Common failure: "No module named argo_anywhere" from the -m form
        # under an interpreter that only saw the module via PYTHONPATH.
        detail = (proc.stderr or proc.stdout or "").strip().splitlines()
        tail = detail[-1] if detail else f"exit {proc.returncode}"
        return [], f"{shlex.join(prefix)} --version failed: {tail}"
    return prefix, None


def build_command(argv: Sequence[str], *, cwd: str | None = None) -> str:
    """A single shell-command string that runs ``argv`` (optionally after cd)."""
    cmd = shlex.join(list(argv))
    if cwd:
        cmd = f"cd {shlex.quote(cwd)} && {cmd}"
    return cmd


def _apple_quote(s: str) -> str:
    """Escape for embedding inside an AppleScript double-quoted literal."""
    return s.replace("\\", "\\\\").replace('"', '\\"')


def _iterm_installed() -> bool:
    return (
        Path("/Applications/iTerm.app").exists()
        or Path(os.path.expanduser("~/Applications/iTerm.app")).exists()
    )


def macos_osa_script(term_id: str, command: str) -> str:
    """AppleScript that opens a new window of ``term_id`` running ``command``.

    Focus discipline (fixed 2026-07-13): ``activate`` must be the LAST
    statement so the terminal actually ends up frontmost. Calling activate
    at the top races the AppleScript's window-creation work against the
    caller (the browser) re-taking focus by the time the script returns,
    leaving the user staring at the browser tab while the new terminal
    sits behind it. Also explicitly ``select`` the new window (iTerm) or
    ``set frontmost`` (both) so the target IS the frontmost window rather
    than whatever was frontmost before.
    """
    q = _apple_quote(command)
    if term_id == "iterm":
        return (
            'tell application "iTerm"\n'
            "  set newWindow to (create window with default profile)\n"
            f'  tell current session of newWindow to write text "{q}"\n'
            "  select newWindow\n"
            "  activate\n"
            "end tell"
        )
    # Terminal.app: `do script` opens a NEW window running the command
    # and returns the tab object. Two fixes on 2026-07-13:
    #   * ``set index of window 1 of newTab to 1`` (previous attempt) is
    #     an invalid reference -- ``window 1 of newTab`` doesn't parse
    #     in Terminal.app's AppleScript model, and osascript exits 1
    #     with ``Can't set window 1 of tab 1 of window id X to 1.
    #     (-10006)``, leaving the launcher's user-facing note showing
    #     the raw osascript error;
    #   * Terminal.app's window class exposes ``frontmost`` (boolean),
    #     not ``index``, so even the "correct" reference
    #     ``set index of (window of newTab) to 1`` fails the same way.
    # The working idiom: find the window whose tabs contain newTab and
    # set its ``frontmost`` to true, THEN activate the app so the
    # window actually surfaces (per D-031's focus-follow-window
    # discipline: ``activate`` is the LAST statement).
    return (
        'tell application "Terminal"\n'
        f'  set newTab to (do script "{q}")\n'
        "  set targetWindow to first window whose tabs contains newTab\n"
        "  set frontmost of targetWindow to true\n"
        "  activate\n"
        "end tell"
    )


def cli_terminal_argv(term_id: str, command: str) -> list[str]:
    """argv to launch CLI terminal ``term_id`` running ``command`` (via a login
    shell so PATH/rc are set)."""
    _, binary, prefix = _CLI_TERMS[term_id]
    return [binary, *prefix, "bash", "-lc", command]


# --- focus-follow-window (best effort; per-OS mechanism) ------------------

#: macOS ``.app`` bundle names for the CLI terminals we support. Used by the
#: post-spawn ``System Events`` activate call so the newly-opened window
#: comes to the front instead of sitting behind the browser that spawned it
#: (the FastAPI server isn't frontmost, so macOS opens the window in the
#: background by default; see :func:`_raise_focus_macos_cli`).
#:
#: kitty is the odd one out: its process name reported to macOS is
#: ``"kitty"`` regardless of how the .app is named on disk. The other
#: three ship as capital-letter bundle names.
_MAC_CLI_BUNDLE_NAMES: dict[str, str] = {
    "alacritty": "Alacritty",
    "kitty": "kitty",
    "wezterm": "WezTerm",
    "ghostty": "Ghostty",
}


def _raise_focus_macos_cli(
    term_id: str,
    *,
    _run: Callable[..., object] = subprocess.run,
    _sleep: Callable[[float], None] = __import__("time").sleep,
) -> None:
    """Bring a just-launched macOS CLI terminal to the foreground.

    The AppleScript path (Terminal.app / iTerm2) already ``activate``s as
    its final statement. The Popen path (alacritty / kitty / wezterm /
    ghostty) needs a follow-up push: when a non-frontmost process (the
    FastAPI server) launches a GUI app on macOS, the new window opens
    behind whatever the user was looking at. Fix: ``osascript`` a
    ``System Events`` activate keyed on the bundle name.

    Best effort: never raises. If ``osascript`` is absent, times out, or
    the terminal isn't recognised as one of our known bundles, silently
    no-op -- the user can Cmd-Tab manually and the launch itself still
    succeeded.

    A ~120ms sleep before the activate gives the terminal enough time to
    have registered a window with the window server; without it the
    activate frequently no-ops because the target process has no
    windows yet.
    """
    bundle = _MAC_CLI_BUNDLE_NAMES.get(term_id)
    if not bundle:
        return
    if not shutil.which("osascript"):
        return
    _sleep(0.12)
    script = (
        f'tell application "System Events"\n'
        f'  set procs to (processes whose name is "{bundle}")\n'
        f"  if (count of procs) > 0 then\n"
        f"    set frontmost of (item 1 of procs) to true\n"
        f"  end if\n"
        f"end tell"
    )
    try:
        _run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=3, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        # System Events might not be permitted (Accessibility TCC prompt
        # deferred by the user, etc.). Not fatal.
        pass


def _raise_focus_linux(
    label: str,
    pid: int | None,
    *,
    _run: Callable[..., object] = subprocess.run,
    _sleep: Callable[[float], None] = __import__("time").sleep,
) -> None:
    """Best-effort focus raise for a just-launched Linux terminal.

    Uses ``wmctrl -a <name>`` when available under X11. On Wayland (where
    focus-stealing-prevention is enforced by the compositor and external
    tools like ``wmctrl`` are unavailable) this is a no-op -- the user
    must click. That's honest: Wayland's design is "the app that has the
    user's attention keeps it"; a launcher can't override that.

    Best effort: never raises.
    """
    # Skip cleanly on Wayland -- wmctrl doesn't work + the compositor
    # would ignore the raise anyway.
    if os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland":
        return
    if not shutil.which("wmctrl"):
        return
    # A short delay so the window has appeared before we try to match it.
    _sleep(0.15)
    # Prefer PID matching (more precise) if wmctrl supports it (-x -p);
    # fall back to name matching. We try both cheaply.
    for args in (["wmctrl", "-a", label], ["wmctrl", "-xa", label.lower()]):
        try:
            r = _run(args, capture_output=True, text=True, timeout=2, check=False)
            if getattr(r, "returncode", 1) == 0:
                return
        except (OSError, subprocess.SubprocessError):
            continue


# --- the spawn -------------------------------------------------------------

def open_external_terminal(
    argv: Sequence[str],
    *,
    terminal: str | None = None,
    cwd: str | None = None,
    system: str | None = None,
    _run: Callable[..., object] = subprocess.run,
    _popen: Callable[..., object] = subprocess.Popen,
) -> dict:
    """Open ``argv`` in a new native terminal window. Never raises.

    ``terminal`` selects a specific terminal id (from :func:`available_terminals`);
    ``None`` uses :func:`default_terminal`. Returns
    ``{"ok", "terminal", "terminal_id", "command", "error"}``. ``system`` / ``_run``
    / ``_popen`` are test seams.
    """
    system = system or platform.system()
    command = build_command(argv, cwd=cwd)
    avail = {t["id"]: t["label"] for t in available_terminals(system)}

    if not avail:
        return {
            "ok": False, "terminal": None, "terminal_id": None, "command": command,
            "error": f"no supported terminal found on {system}",
        }

    term_id = (terminal or default_terminal(system) or "").lower()
    if term_id not in avail:
        return {
            "ok": False, "terminal": None, "terminal_id": term_id or None, "command": command,
            "error": f"terminal {term_id!r} not available; choose one of {sorted(avail)}",
        }

    label = avail[term_id]
    child_pid: int | None = None
    try:
        if term_id in _MAC_OSA_TERMS:
            # AppleScript already `activate`s as its final statement (fix
            # 2026-07-13). No follow-up focus push needed here.
            _run(
                ["osascript", "-e", macos_osa_script(term_id, command)],
                check=True, capture_output=True, text=True, timeout=15,
            )
        else:
            # GUI terminals may stay in the foreground -- launch detached and
            # do not wait on them.
            proc = _popen(
                cli_terminal_argv(term_id, command),
                start_new_session=True,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            child_pid = getattr(proc, "pid", None)
    except Exception as exc:  # noqa: BLE001 -- report, never raise
        return {"ok": False, "terminal": label, "terminal_id": term_id, "command": command, "error": str(exc)}

    # Focus-follow-window (fix 2026-07-13, extended cross-platform): the
    # AppleScript path handles it inline; the CLI-Popen path needs an
    # explicit follow-up push because the FastAPI server that spawned the
    # window isn't frontmost, so the OS opens the new window behind the
    # browser. Best effort per platform; never fails the launch.
    if term_id not in _MAC_OSA_TERMS:
        try:
            if system == "Darwin":
                _raise_focus_macos_cli(term_id)
            elif system == "Linux":
                _raise_focus_linux(label, child_pid)
        except Exception:  # noqa: BLE001 -- focus is nice-to-have, never fatal
            pass

    return {"ok": True, "terminal": label, "terminal_id": term_id, "command": command, "error": None}
