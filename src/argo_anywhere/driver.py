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
import struct
import subprocess
import termios
from dataclasses import dataclass
from typing import Sequence

from ._engine import engine_path, packaged_env

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

#: Verbs whose managed process *owns* the SSH channel: it created the mux master
#: (or hosts the foreground monitor that did) and holds the tunnel alive, so
#: killing that process tears the whole channel down. Observed live 2026-07-10:
#: stopping a web/spike server that hosted a ``connect`` brought the channel
#: down with it (notes/impl_python_webui.md "Operational lessons"). D-003's
#: "the master outlives the foreground ``ssh -N -L``" does NOT extend to killing
#: the monitor process itself. The dashboard's kill-guard uses this set to warn
#: before stopping a session that owns a live tunnel.
#:
#: ``configure``/``run`` reuse an existing channel without opening one (D-024)
#: and ``server`` runs on the compute node, so none of those own the laptop-side
#: master; they are deliberately excluded.
CHANNEL_VERBS: frozenset[str] = frozenset({
    "connect", "tunnel", "client", "setup",
})


def owns_channel(argv: Sequence[str]) -> bool:
    """True if this engine invocation holds the SSH channel open (see
    :data:`CHANNEL_VERBS`)."""
    return verb_of(argv) in CHANNEL_VERBS


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
    environment. Intended for verbs that return (see :data:`SUBPROCESS_VERBS`);
    running an interactive verb here will hit a silent default (that is why
    :func:`classify` routes those to Lane 2). The D-030a package marker is always
    set (this is a package-spawned invocation).
    """
    argv = list(argv)
    full_env = packaged_env(env)
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
        cwd: str | os.PathLike[str] | None = None,
    ) -> None:
        """Spawn the engine on a PTY.

        ``cwd`` (D-031 Task 4): if given, chdir the child to this directory
        before ``exec``. Blank / ``None`` inherits the parent's cwd (preserves
        today's behavior for direct programmatic callers; the web UI enforces
        its own "cwd required" policy above the driver). The web layer's
        :mod:`argo_anywhere.web.validation` runs before this constructor is
        reached, so the value here is trusted to be absolute + existing.
        """
        self.argv = list(argv)
        self.cwd = str(cwd) if cwd is not None else None
        self._stack = contextlib.ExitStack()
        # Keep the vendored-engine temp path alive for the child's whole life.
        script = self._stack.enter_context(engine_path())

        master, slave = pty.openpty()
        rows, cols = dimensions
        _set_winsize(master, rows, cols)

        # D-030a package marker on every package-spawned engine invocation.
        full_env = packaged_env(env)
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
                cwd=self.cwd,
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
        """Deliver a Ctrl-C, exactly like typing it in the terminal.

        The child runs in its own session with the PTY as controlling terminal
        (``start_new_session=True``), and it spawns its own foreground children
        (ssh, the monitor loop). Sending ``SIGINT`` to the session *leader* alone
        does not reach that foreground child, which is why the button felt dead.
        Writing the terminal's INTR byte (``\\x03``) to the PTY master instead
        makes the line discipline raise ``SIGINT`` on the whole foreground
        process group -- identical to a real keystroke.
        """
        if self._proc.poll() is None:
            with contextlib.suppress(OSError):
                os.write(self._master, b"\x03")

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
