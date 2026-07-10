"""Web-layer tests: host-guard, static serving, health, and the full
WebSocket <-> PTY bridge round-trip -- driving the engine's ``help`` verb so no
ANL/SSH/network is touched.

Skipped entirely unless the ``[web]``/``[test]`` extras are installed.
"""

from __future__ import annotations

import json

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from argo_anywhere.web.app import _host_is_loopback, create_app  # noqa: E402

CTRL = "\x00CTRL"
EXIT = "\x00EXIT"


@pytest.fixture()
def client() -> TestClient:
    # base_url makes the Host header "127.0.0.1" so it passes the loopback guard;
    # engine_argv=help keeps every /ws connection local + fast.
    app = create_app(engine_argv=["help"])
    with TestClient(app, base_url="http://127.0.0.1") as c:
        yield c


# -- host guard (pure) ------------------------------------------------------

@pytest.mark.parametrize(
    "host, ok",
    [
        ("127.0.0.1", True),
        ("127.0.0.1:8799", True),
        ("localhost:8799", True),
        ("[::1]:8799", True),
        ("", True),                 # omitted host allowed (loopback bind)
        ("evil.example.com", False),
        ("attacker:8799", False),
    ],
)
def test_host_is_loopback(host: str, ok: bool) -> None:
    assert _host_is_loopback(host) is ok


# -- HTTP surface -----------------------------------------------------------

def test_index_served(client: TestClient) -> None:
    r = client.get("/")
    assert r.status_code == 200
    assert "argo-anywhere" in r.text
    assert "/static/xterm.js" in r.text


def test_healthz(client: TestClient) -> None:
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_static_assets_served(client: TestClient) -> None:
    assert client.get("/static/xterm.css").status_code == 200
    assert client.get("/static/xterm.js").status_code == 200


def test_favicon_no_content(client: TestClient) -> None:
    assert client.get("/favicon.ico").status_code == 204


def test_bad_host_rejected() -> None:
    app = create_app(engine_argv=["help"])
    with TestClient(app, base_url="http://127.0.0.1") as c:
        r = c.get("/", headers={"host": "evil.example.com"})
        assert r.status_code == 403


# -- WebSocket <-> PTY bridge ----------------------------------------------

def test_ws_bridge_streams_engine_output_and_exit(client: TestClient) -> None:
    out = b""
    exit_status: object = "missing"
    # TestClient sends Host "testserver" on the WS upgrade regardless of
    # base_url; send a loopback Host so the DNS-rebinding guard admits it
    # (a real browser on 127.0.0.1 does this naturally).
    with client.websocket_connect("/ws", headers={"host": "127.0.0.1"}) as ws:
        ws.send_text(CTRL + json.dumps({"op": "resize", "rows": 40, "cols": 120}))
        for _ in range(5000):
            msg = ws.receive()
            if msg["type"] == "websocket.close":
                break
            if msg.get("bytes") is not None:
                out += msg["bytes"]
            elif msg.get("text") is not None:
                text = msg["text"]
                if text.startswith(EXIT):
                    exit_status = json.loads(text[len(EXIT):])["exitstatus"]
                    break
    # The engine's help rendered through the PTY to the socket...
    assert b"connect" in out
    # ...and the child exited cleanly, reported via the EXIT control frame.
    assert exit_status == 0


def test_ws_rejects_non_loopback_host(client: TestClient) -> None:
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect("/ws", headers={"host": "evil.example.com"}):
            pass
    assert exc.value.code == 1008  # policy violation (DNS-rebinding guard)
