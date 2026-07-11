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
    """The argv prefix that invokes this package's CLI in a fresh shell.

    Prefer the ``argo-anywhere`` console script next to the running interpreter
    (nicer window title, no PATH assumption); fall back to
    ``<python> -m argo_anywhere`` which always works.
    """
    script = Path(sys.executable).with_name("argo-anywhere")
    if script.exists():
        return [str(script)]
    return [sys.executable, "-m", "argo_anywhere"]


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
    """AppleScript that opens a new window of ``term_id`` running ``command``."""
    q = _apple_quote(command)
    if term_id == "iterm":
        return (
            'tell application "iTerm"\n'
            "  activate\n"
            "  set newWindow to (create window with default profile)\n"
            f'  tell current session of newWindow to write text "{q}"\n'
            "end tell"
        )
    # Terminal.app: `do script` opens a NEW window running the command.
    return (
        'tell application "Terminal"\n'
        "  activate\n"
        f'  do script "{q}"\n'
        "end tell"
    )


def cli_terminal_argv(term_id: str, command: str) -> list[str]:
    """argv to launch CLI terminal ``term_id`` running ``command`` (via a login
    shell so PATH/rc are set)."""
    _, binary, prefix = _CLI_TERMS[term_id]
    return [binary, *prefix, "bash", "-lc", command]


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
    try:
        if term_id in _MAC_OSA_TERMS:
            _run(
                ["osascript", "-e", macos_osa_script(term_id, command)],
                check=True, capture_output=True, text=True, timeout=15,
            )
        else:
            # GUI terminals may stay in the foreground -- launch detached and
            # do not wait on them.
            _popen(
                cli_terminal_argv(term_id, command),
                start_new_session=True,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
    except Exception as exc:  # noqa: BLE001 -- report, never raise
        return {"ok": False, "terminal": label, "terminal_id": term_id, "command": command, "error": str(exc)}

    return {"ok": True, "terminal": label, "terminal_id": term_id, "command": command, "error": None}
