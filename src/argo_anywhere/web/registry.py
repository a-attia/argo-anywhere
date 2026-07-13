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

Named slots (D-031, v3.1.0): the two-embedded-terminal split introduces two
well-known panels -- ``channel`` (persistent, owns ``connect``) and ``utility``
(ephemeral, runs ``configure`` / ``setup`` / ``tunnel``). The registry tracks
which live session (if any) belongs to each panel so the UI can offer per-panel
routing + so the app layer can enforce "only one Channel at a time" without
racing on the id-keyed map. A session may sit in ONE named slot (or none); the
id-keyed map (``_by_id``) is the source of truth for identity.

Local only: the registry never contacts ANL. Liveness comes from
``PtySession.isalive()`` (a ``waitpid``), not the network.
"""

from __future__ import annotations

import itertools
import threading
import time
from dataclasses import asdict, dataclass
from typing import Literal

from ..driver import PtySession, owns_channel, verb_of

#: Named panel slots (D-031). ``channel`` is persistent (owns ``connect``);
#: ``utility`` is ephemeral (``configure`` / ``setup`` / ``tunnel``). The
#: web UI's dual-panel layout maps 1-to-1 to these slots.
PanelSlot = Literal["channel", "utility"]

#: Verbs that route to the Channel panel (D-031). Only ``connect`` today; the
#: broader :data:`argo_anywhere.driver.CHANNEL_VERBS` set (which includes
#: ``tunnel`` / ``client`` / ``setup``) is about *ownership* of the SSH master,
#: not about UI routing.
CHANNEL_PANEL_VERBS: frozenset[str] = frozenset({"connect"})

#: Verbs that route to the Utility panel (D-031). ``configure`` / ``setup`` /
#: ``tunnel`` are all short-to-medium-lived operations that ride the existing
#: channel; killing them (or a ws close) does not tear the tunnel down.
UTILITY_PANEL_VERBS: frozenset[str] = frozenset({"configure", "setup", "tunnel"})


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
    detached: bool
    panel: str | None  # D-031: "channel" / "utility" / None (external / legacy)

    def as_dict(self) -> dict:
        return asdict(self)


class ManagedSession:
    """A :class:`PtySession` plus registry bookkeeping (id, start time)."""

    def __init__(
        self,
        id: str,
        session: PtySession,
        *,
        panel: PanelSlot | None = None,
    ) -> None:
        self.id = id
        self.session = session
        self.argv = list(session.argv)
        self.verb = verb_of(self.argv)
        self.owns_channel = owns_channel(self.argv)
        self.pid = session.pid
        self.started_at = time.time()
        # Set True when the session's ws closed but we KEPT it running because it
        # owns the SSH channel (so the master/tunnel survives). Drained + reaped
        # by the app layer; still explicitly stoppable via /api/sessions/<id>/stop.
        self.detached = False
        #: D-031 panel slot ("channel" / "utility" / None). None means legacy /
        #: external / no-panel-assignment (backward compat with pre-D-031 code
        #: that spawned sessions via bare ``registry.register(session)``).
        self.panel: PanelSlot | None = panel

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
            detached=self.detached,
            panel=self.panel,
        )


class SessionRegistry:
    """Thread-safe registry of live managed sessions.

    Sessions are added on ``/ws`` connect and removed when the bridge ends. IDs
    are small monotonic strings (``s1``, ``s2``, ...) unique within a process.

    D-031 adds two named slots (``channel``, ``utility``) that mirror the
    dual-panel web UI. A session lives in AT MOST one named slot; the id-keyed
    map is the source of truth for identity. ``register()`` remains slot-less
    (backward compat); ``register_panel(session, panel)`` places into a named
    slot and evicts any previous occupant of that slot from the slot mapping
    (the previous session is NOT unregistered from the id map -- the caller
    decides whether to stop it).
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sessions: dict[str, ManagedSession] = {}
        self._ids = itertools.count(1)
        #: D-031 named panel slots. None means "no session currently in this
        #: panel". A slot's ManagedSession also appears in ``_sessions``.
        self._panels: dict[PanelSlot, ManagedSession | None] = {
            "channel": None,
            "utility": None,
        }

    def register(self, session: PtySession) -> ManagedSession:
        """Register a session with no panel affinity (legacy / external)."""
        with self._lock:
            sid = f"s{next(self._ids)}"
            managed = ManagedSession(sid, session)
            self._sessions[sid] = managed
            return managed

    def register_panel(
        self, session: PtySession, panel: PanelSlot
    ) -> tuple[ManagedSession, ManagedSession | None]:
        """Register a session into a named panel slot (D-031).

        Returns ``(new_managed, evicted_managed_or_None)``. The evicted session
        (if any) was the previous occupant of that slot; the caller decides
        whether to stop it (Channel: reject the new launch; Utility: stop the
        old one + spawn the new). The evicted session is left in the id-keyed
        map for the caller to reap explicitly via ``unregister(id)``.
        """
        if panel not in ("channel", "utility"):
            raise ValueError(f"unknown panel: {panel!r}")
        with self._lock:
            sid = f"s{next(self._ids)}"
            managed = ManagedSession(sid, session, panel=panel)
            self._sessions[sid] = managed
            evicted = self._panels[panel]
            self._panels[panel] = managed
            # Clear the evicted session's panel affinity so subsequent
            # snapshots don't mis-report it as still holding the slot.
            if evicted is not None:
                evicted.panel = None
            return managed, evicted

    def unregister(self, id: str) -> None:
        with self._lock:
            managed = self._sessions.pop(id, None)
            # Clear the slot mapping too if this session was in a slot.
            if managed is not None and managed.panel is not None:
                if self._panels.get(managed.panel) is managed:
                    self._panels[managed.panel] = None

    def get(self, id: str) -> ManagedSession | None:
        with self._lock:
            return self._sessions.get(id)

    def get_panel(self, panel: PanelSlot) -> ManagedSession | None:
        """Return the current occupant of a named slot, or None."""
        with self._lock:
            return self._panels.get(panel)

    def panel_alive(self, panel: PanelSlot) -> bool:
        """True if a named slot has a live session in it."""
        m = self.get_panel(panel)
        return m is not None and m.session.isalive()

    def list(self) -> list[ManagedSession]:
        with self._lock:
            return list(self._sessions.values())

    def snapshots(self) -> list[dict]:
        """All sessions as JSON-ready dicts, sharing one timestamp."""
        now = time.time()
        return [m.snapshot(now=now).as_dict() for m in self.list()]
