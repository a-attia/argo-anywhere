"""In-process registry of managed PTY sessions (P2 dashboard + monitor).

The web server spawns one :class:`~argo_anywhere.driver.PtySession` per ``/ws``
connection (Lane 2). This registry tracks those live sessions so the dashboard
can list them and -- critically -- warn before stopping one that owns a live SSH
channel.

Why the warning matters: a session running a channel-owning verb (``connect`` /
``tunnel`` / ``client`` / ``setup``; see :data:`argo_anywhere.driver.CHANNEL_VERBS`)
hosts the SSH mux master. Killing that process tears the whole tunnel down --
observed live on 2026-07-10, when stopping a server that hosted a ``connect``
brought the channel down with it. The registry marks such sessions
(``owns_channel``); the app layer combines that flag with a loopback-listener
check to decide whether a stop needs confirmation.

Local only: the registry never contacts ANL. Liveness comes from
``PtySession.isalive()`` (a ``waitpid``), not the network.
"""

from __future__ import annotations

import itertools
import threading
import time
from dataclasses import asdict, dataclass

from ..driver import PtySession, owns_channel, verb_of


@dataclass(frozen=True)
class SessionInfo:
    """A JSON-serializable point-in-time snapshot of a managed session."""

    id: str
    argv: list[str]
    verb: str
    pid: int
    started_at: float
    uptime_s: float
    alive: bool
    exitstatus: int | None
    owns_channel: bool

    def as_dict(self) -> dict:
        return asdict(self)


class ManagedSession:
    """A :class:`PtySession` plus registry bookkeeping (id, start time)."""

    def __init__(self, id: str, session: PtySession) -> None:
        self.id = id
        self.session = session
        self.argv = list(session.argv)
        self.verb = verb_of(self.argv)
        self.owns_channel = owns_channel(self.argv)
        self.pid = session.pid
        self.started_at = time.time()

    def snapshot(self, *, now: float | None = None) -> SessionInfo:
        now = time.time() if now is None else now
        return SessionInfo(
            id=self.id,
            argv=list(self.argv),
            verb=self.verb,
            pid=self.pid,
            started_at=self.started_at,
            uptime_s=round(now - self.started_at, 1),
            alive=self.session.isalive(),
            exitstatus=self.session.exitstatus,
            owns_channel=self.owns_channel,
        )


class SessionRegistry:
    """Thread-safe registry of live managed sessions.

    Sessions are added on ``/ws`` connect and removed when the bridge ends. IDs
    are small monotonic strings (``s1``, ``s2``, ...) unique within a process.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sessions: dict[str, ManagedSession] = {}
        self._ids = itertools.count(1)

    def register(self, session: PtySession) -> ManagedSession:
        with self._lock:
            sid = f"s{next(self._ids)}"
            managed = ManagedSession(sid, session)
            self._sessions[sid] = managed
            return managed

    def unregister(self, id: str) -> None:
        with self._lock:
            self._sessions.pop(id, None)

    def get(self, id: str) -> ManagedSession | None:
        with self._lock:
            return self._sessions.get(id)

    def list(self) -> list[ManagedSession]:
        with self._lock:
            return list(self._sessions.values())

    def snapshots(self) -> list[dict]:
        """All sessions as JSON-ready dicts, sharing one timestamp."""
        now = time.time()
        return [m.snapshot(now=now).as_dict() for m in self.list()]
