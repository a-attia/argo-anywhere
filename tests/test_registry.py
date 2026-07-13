"""Session-registry + dashboard-endpoint tests -- all local.

The channel-health endpoint is exercised against a throwaway localhost HTTP
server, never a real tunnel. The registry is driven with a fake PTY session so
the tests neither spawn processes nor touch the network.
"""

from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from argo_anywhere.web.app import create_app  # noqa: E402
from argo_anywhere.web.registry import SessionRegistry  # noqa: E402


# -- a fake PtySession (duck-typed: argv/pid/isalive/exitstatus/close) --------

class FakePty:
    def __init__(self, argv, *, pid: int = 4242, alive: bool = True) -> None:
        self.argv = list(argv)
        self.pid = pid
        self._alive = alive
        self.closed = False

    def isalive(self) -> bool:
        return self._alive

    @property
    def exitstatus(self):
        return None if self._alive else 0

    def close(self) -> None:
        self.closed = True
        self._alive = False


# -- registry unit ----------------------------------------------------------

def test_register_assigns_unique_ids_and_lists() -> None:
    reg = SessionRegistry()
    a = reg.register(FakePty(["connect"]))
    b = reg.register(FakePty(["help"]))
    assert a.id != b.id
    assert {m.id for m in reg.list()} == {a.id, b.id}
    assert reg.get(a.id) is a


def test_owns_channel_classification() -> None:
    reg = SessionRegistry()
    conn = reg.register(FakePty(["connect"]))
    help_ = reg.register(FakePty(["help"]))
    run = reg.register(FakePty(["run", "--cli-tool", "opencode"]))
    assert conn.owns_channel is True          # connect holds the master
    assert help_.owns_channel is False        # returns immediately
    assert run.owns_channel is False          # reuses an existing channel (D-024)


def test_snapshot_shape_and_verb() -> None:
    reg = SessionRegistry()
    m = reg.register(FakePty(["--port", "8100", "connect"]))
    snap = m.snapshot().as_dict()
    assert snap["id"] == m.id
    assert snap["verb"] == "connect"
    assert snap["pid"] == 4242
    assert snap["alive"] is True
    assert snap["exitstatus"] is None
    assert snap["owns_channel"] is True
    assert snap["uptime_s"] >= 0
    assert snap["detached"] is False


def test_detached_flag_flows_into_snapshot() -> None:
    # A channel owner whose ws closed is kept running + marked detached (the app
    # layer sets this instead of force-killing it, so the SSH master survives).
    reg = SessionRegistry()
    m = reg.register(FakePty(["connect"]))
    assert m.detached is False
    m.detached = True
    assert reg.snapshots()[0]["detached"] is True


def test_unregister_removes() -> None:
    reg = SessionRegistry()
    m = reg.register(FakePty(["help"]))
    reg.unregister(m.id)
    assert reg.get(m.id) is None
    assert reg.snapshots() == []


# -- D-031: named panel slots (Channel + Utility) ----------------------------

def test_register_panel_places_in_named_slot() -> None:
    reg = SessionRegistry()
    m, evicted = reg.register_panel(FakePty(["connect"]), "channel")
    assert evicted is None
    assert reg.get_panel("channel") is m
    assert reg.get_panel("utility") is None
    assert m.panel == "channel"


def test_register_panel_evicts_previous_slot_occupant() -> None:
    # Utility panel is ephemeral: relaunching evicts the prior session from
    # the slot mapping and returns it so the caller can stop + reap it.
    reg = SessionRegistry()
    first, _ = reg.register_panel(FakePty(["configure"]), "utility")
    second, evicted = reg.register_panel(FakePty(["setup"]), "utility")
    assert evicted is first
    # Evicted session lost its panel affinity (so subsequent snapshots don't
    # mis-report it as still occupying utility).
    assert first.panel is None
    # New session holds the slot.
    assert reg.get_panel("utility") is second
    assert second.panel == "utility"
    # Both are still in the id-keyed map (caller decides eviction cleanup).
    assert reg.get(first.id) is first
    assert reg.get(second.id) is second


def test_panel_alive_reflects_liveness() -> None:
    reg = SessionRegistry()
    fake = FakePty(["connect"])
    m, _ = reg.register_panel(fake, "channel")
    assert reg.panel_alive("channel") is True
    fake._alive = False
    assert reg.panel_alive("channel") is False


def test_unregister_clears_panel_slot() -> None:
    reg = SessionRegistry()
    m, _ = reg.register_panel(FakePty(["connect"]), "channel")
    reg.unregister(m.id)
    assert reg.get(m.id) is None
    assert reg.get_panel("channel") is None


def test_register_panel_rejects_unknown_slot() -> None:
    import pytest as _pytest
    reg = SessionRegistry()
    with _pytest.raises(ValueError):
        reg.register_panel(FakePty(["connect"]), "external")  # type: ignore[arg-type]


def test_snapshot_includes_panel_field() -> None:
    reg = SessionRegistry()
    m, _ = reg.register_panel(FakePty(["connect"]), "channel")
    snap = m.snapshot().as_dict()
    assert snap["panel"] == "channel"
    # Legacy slot-less register: panel is None.
    m2 = reg.register(FakePty(["help"]))
    assert m2.snapshot().as_dict()["panel"] is None


# -- endpoints --------------------------------------------------------------

@pytest.fixture()
def app_and_client():
    app = create_app(engine_argv=["help"])
    with TestClient(app, base_url="http://127.0.0.1") as c:
        yield app, c


def test_api_sessions_reflects_registry(app_and_client) -> None:
    app, c = app_and_client
    app.state.registry.register(FakePty(["connect"]))
    body = c.get("/api/sessions").json()
    assert len(body["sessions"]) == 1
    assert body["sessions"][0]["verb"] == "connect"


def test_api_status_includes_sessions(app_and_client) -> None:
    app, c = app_and_client
    app.state.registry.register(FakePty(["tunnel"]))
    body = c.get("/api/status").json()
    assert "sessions" in body
    assert body["sessions"][0]["verb"] == "tunnel"


def test_stop_unknown_session_404(app_and_client) -> None:
    _, c = app_and_client
    assert c.post("/api/sessions/nope/stop").status_code == 404


def test_stop_non_channel_session_closes(app_and_client) -> None:
    app, c = app_and_client
    m = app.state.registry.register(FakePty(["help"]))
    r = c.post(f"/api/sessions/{m.id}/stop")
    assert r.status_code == 200
    assert r.json() == {"stopped": m.id}
    assert m.session.closed is True


def test_stop_channel_owner_guarded_then_forced(app_and_client, monkeypatch) -> None:
    app, c = app_and_client
    m = app.state.registry.register(FakePty(["connect"]))

    # Simulate a live channel: cached port + a listener on it.
    import argo_anywhere.status as status

    class _Ln:
        def __init__(self, port):
            self.port = port

    monkeypatch.setattr(status, "cached_state", lambda *a, **k: {"user": "u", "node": "n", "port": 8123})
    monkeypatch.setattr(status, "local_listeners", lambda ports=None: [_Ln(8123)])

    # Unforced stop is refused with a 409 warning; the session stays alive.
    r = c.post(f"/api/sessions/{m.id}/stop")
    assert r.status_code == 409
    body = r.json()
    assert body["warning"] == "owns_live_channel"
    assert body["port"] == 8123
    assert m.session.closed is False

    # Forced stop proceeds.
    r = c.post(f"/api/sessions/{m.id}/stop?force=true")
    assert r.status_code == 200
    assert m.session.closed is True


def test_stop_channel_owner_no_listener_not_guarded(app_and_client, monkeypatch) -> None:
    app, c = app_and_client
    m = app.state.registry.register(FakePty(["connect"]))
    import argo_anywhere.status as status

    # Channel verb but no live listener -> no tunnel to protect -> stop proceeds.
    monkeypatch.setattr(status, "cached_state", lambda *a, **k: {"user": None, "node": None, "port": None})
    monkeypatch.setattr(status, "local_listeners", lambda ports=None: [])
    r = c.post(f"/api/sessions/{m.id}/stop")
    assert r.status_code == 200
    assert m.session.closed is True


# -- /api/health against a localhost stub (never ANL) -----------------------

class _HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        if self.path == "/health":
            body = b'{"status": "healthy"}'
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *args):
        pass


@pytest.fixture()
def health_server():
    srv = HTTPServer(("127.0.0.1", 0), _HealthHandler)
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        yield port
    finally:
        srv.shutdown()


def test_api_health_up(app_and_client, health_server) -> None:
    _, c = app_and_client
    body = c.get(f"/api/health?port={health_server}").json()
    assert body["up"] is True
    assert "healthy" in (body["status"] or "")
    assert body["latency_ms"] is not None


def test_api_health_bad_port(app_and_client) -> None:
    _, c = app_and_client
    assert c.get("/api/health?port=99999").status_code == 400
