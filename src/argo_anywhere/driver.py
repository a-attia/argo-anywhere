"""Two-lane driver over the bash engine (Model A; PLAN.md D-026, spike/HANDOFF.md).

The engine's interactive surface splits into two lanes:

- **Lane 1 (SUBPROCESS)** -- verbs that *return* and are fully pre-answerable via
  flags/env (``status``, ``list-models``, ``stop``, ``update``, ...). Run as a
  captured subprocess with **stdin closed**, so any unexpected prompt takes its
  non-TTY default instead of hanging. Safe to run and await; yields an
  :class:`EngineResult`.

- **Lane 2 (PTY)** -- verbs that hit Duo, the long-lived monitor loop, or the
  three prompts with no non-interactive flag (port-migrate / config-conflict /
  scope-conflict): ``connect``, ``tunnel``, ``client``, ``setup``,
  ``configure``, ``run``, ``server``. These run on a pseudo-terminal so a
  frontend (the browser terminal, later ``web/pty_bridge.py``) can stream bytes
  both ways. This module provides :class:`PtySession`; the WebSocket bridge
  attaches to it.

Lane assignment is conservative: only the known-returning verbs go to Lane 1;
everything else (including the default ``client`` and any unknown token) goes to
Lane 2, because giving an interactive-capable flow a real terminal is always
safe, whereas running an unclassified flow headless with a closed stdin is not.

The whole module is core (stdlib only) -- no third-party dependency. The engine
is located via :mod:`argo_anywhere._engine`.
"""

from __future__ import annotations

import contextlib
import enum
import fcntl
import os
import pty
import signal
import struct
import subprocess
import termios
from dataclasses import dataclass
from typing import Sequence

from ._engine import engine_path

# ---------------------------------------------------------------------------
# Verb classification (mirrors the engine's main() dispatcher, argo-anywhere.sh)
# ---------------------------------------------------------------------------

#: Every subcommand the engine's arg-parser recognizes (argo-anywhere.sh main()).
KNOWN_VERBS: frozenset[str] = frozenset({
    "client", "tunnel", "connect", "configure", "run", "setup", "server",
    "status", "stop", "update", "update-models", "list-models", "clean",
    "install", "uninstall", "help", "list-tools",
})

#: The engine defaults to ``client`` when no subcommand token is present.
DEFAULT_VERB = "client"

#: Lane-1 verbs: they return and are pre-answerable headlessly (with the right
#: flags). Everything else -- notably the interactive/long-lived verbs and any
#: unknown token -- is Lane 2.
SUBPROCESS_VERBS: frozenset[str] = frozenset({
    "status", "stop", "list-models", "list-tools", "update-models",
    "update", "clean", "install", "uninstall", "help",
})


class Lane(enum.Enum):
    """Which lane an engine invocation runs in."""

    SUBPROCESS = "subprocess"  # Lane 1: captured, returns an EngineResult
    PTY = "pty"                # Lane 2: pseudo-terminal, streamed to a frontend


def verb_of(argv: Sequence[str]) -> str:
    """Return the engine subcommand implied by ``argv``.

    The engine accepts flags and the subcommand in any order, so we scan for the
    first token that names a known verb; absent one, the engine defaults to
    ``client``.
    """
    for tok in argv:
        if tok in KNOWN_VERBS:
            return tok
    return DEFAULT_VERB


def classify(argv: Sequence[str]) -> Lane:
    """Return the :class:`Lane` for an engine invocation."""
    return Lane.SUBPROCESS if verb_of(argv) in SUBPROCESS_VERBS else Lane.PTY


# ---------------------------------------------------------------------------
# Lane 1 -- captured subprocess
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class EngineResult:
    """Outcome of a Lane-1 (captured-subprocess) engine invocation."""

    argv: list[str]
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0


def run_engine(
    argv: Sequence[str],
    *,
    env: dict[str, str] | None = None,
    timeout: float | None = None,
) -> EngineResult:
    """Run the engine as a captured subprocess (Lane 1) and return its result.

    ``stdin`` is closed (``DEVNULL``) so any prompt the engine would raise takes
    its non-TTY default rather than blocking. ``env`` is merged over the current
    environment; ``None`` inherits it unchanged. Intended for verbs that return
    (see :data:`SUBPROCESS_VERBS`); running an interactive verb here will hit a
    silent default (that is why :func:`classify` routes those to Lane 2).
    """
    argv = list(argv)
    full_env = None if env is None else {**os.environ, **env}
    with engine_path() as script:
        proc = subprocess.run(
            ["bash", str(script), *argv],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            env=full_env,
            timeout=timeout,
        )
    return EngineResult(
        argv=argv,
        returncode=proc.returncode,
        stdout=proc.stdout,
        stderr=proc.stderr,
    )


# ---------------------------------------------------------------------------
# Lane 2 -- pseudo-terminal session (stub the web bridge attaches to)
# ---------------------------------------------------------------------------

def _set_winsize(fd: int, rows: int, cols: int) -> None:
    """Push a window size onto a PTY so full-screen prompts render correctly."""
    winsize = struct.pack("HHHH", rows, cols, 0, 0)
    fcntl.ioctl(fd, termios.TIOCSWINSZ, winsize)


class PtySession:
    """A bash-engine invocation running on a pseudo-terminal (Lane 2).

    Spawns ``bash <engine> <argv>`` on a fresh PTY in its own session, exposing
    the master fd for a frontend to read/write. This is the piece the browser
    terminal bridge (``web/pty_bridge.py``, later) drives; here it is a
    stdlib-only stub sufficient to prove the plumbing and unit-test it. The
    P1 spike already proved the browser <-> WebSocket <-> PTY route end to end
    (incl. a cold Duo challenge); wiring that bridge is a subsequent P0 step.

    Use as a context manager, or call :meth:`close` when done.
    """

    def __init__(
        self,
        argv: Sequence[str],
        *,
        env: dict[str, str] | None = None,
        dimensions: tuple[int, int] = (24, 80),
    ) -> None:
        self.argv = list(argv)
        self._stack = contextlib.ExitStack()
        # Keep the vendored-engine temp path alive for the child's whole life.
        script = self._stack.enter_context(engine_path())

        master, slave = pty.openpty()
        rows, cols = dimensions
        _set_winsize(master, rows, cols)

        full_env = {**os.environ, **(env or {})}
        full_env.setdefault("TERM", "xterm-256color")

        try:
            self._proc = subprocess.Popen(
                ["bash", str(script), *self.argv],
                stdin=slave,
                stdout=slave,
                stderr=slave,
                start_new_session=True,  # own session -> the PTY is controlling
                env=full_env,
                close_fds=True,
            )
        finally:
            os.close(slave)  # the child holds it now; parent only needs master
        self._master = master
        self.pid = self._proc.pid

    # -- fd + I/O ----------------------------------------------------------
    def fileno(self) -> int:
        """The PTY master fd (for ``select``/event-loop registration)."""
        return self._master

    def read(self, size: int = 65536) -> bytes:
        """Read up to ``size`` bytes. Returns ``b""`` at EOF (child exited)."""
        try:
            return os.read(self._master, size)
        except OSError:
            # macOS/Linux raise EIO on the master once the slave is fully gone.
            return b""

    def write(self, data: bytes) -> int:
        """Write raw bytes (keystrokes) to the PTY."""
        return os.write(self._master, data)

    def set_winsize(self, rows: int, cols: int) -> None:
        _set_winsize(self._master, rows, cols)

    # -- lifecycle ---------------------------------------------------------
    def interrupt(self) -> None:
        """Send SIGINT to the child (Ctrl-C)."""
        if self._proc.poll() is None:
            self._proc.send_signal(signal.SIGINT)

    def isalive(self) -> bool:
        return self._proc.poll() is None

    @property
    def exitstatus(self) -> int | None:
        """The child's exit code, or ``None`` if still running.

        Negative values denote termination by signal ``-N`` (subprocess
        convention).
        """
        return self._proc.poll()

    def terminate(self, *, force: bool = False) -> None:
        if self._proc.poll() is None:
            self._proc.terminate()
            if force:
                try:
                    self._proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self._proc.kill()

    def wait(self, timeout: float | None = None) -> int:
        return self._proc.wait(timeout=timeout)

    def close(self) -> None:
        """Terminate the child (if alive) and release the master fd + engine tmp."""
        try:
            self.terminate(force=True)
        finally:
            with contextlib.suppress(OSError):
                os.close(self._master)
            self._stack.close()

    def __enter__(self) -> "PtySession":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
