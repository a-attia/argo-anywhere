"""P3 info-view + launcher tests -- all local.

Captured verbs are exercised with ``list-tools`` (static local list); the PTY
launcher is exercised with ``help``. The ANL-reaching verbs (status,
list-models) are never run here -- only their allowlisting is checked.
"""

from __future__ import annotations

import json

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from argo_anywhere.web.app import INFO_VERBS, build_launch_argv, create_app  # noqa: E402

CTRL = "\x00CTRL"
EXIT = "\x00EXIT"


# -- build_launch_argv (pure) ------------------------------------------------

def test_build_argv_minimal() -> None:
    assert build_launch_argv("connect") == ["connect"]


def test_build_argv_with_flags_order() -> None:
    argv = build_launch_argv("run", cli_tool="opencode", scope="project", port=8123)
    assert argv == ["--cli-tool", "opencode", "--scope", "project", "--port", "8123", "run"]


@pytest.mark.parametrize("verb", ["bogus", "rm", "", "connect;ls"])
def test_build_argv_rejects_unknown_verb(verb: str) -> None:
    with pytest.raises(ValueError):
        build_launch_argv(verb)


@pytest.mark.parametrize("bad", ["a b", "opencode;rm", "--flag", "UPPER", "x" * 40])
def test_build_argv_rejects_bad_cli_tool(bad: str) -> None:
    with pytest.raises(ValueError):
        build_launch_argv("run", cli_tool=bad)


@pytest.mark.parametrize("port", [0, 70000, -1])
def test_build_argv_rejects_bad_port(port: int) -> None:
    with pytest.raises(ValueError):
        build_launch_argv("connect", port=port)


# -- /api/run (captured Lane 1) ---------------------------------------------

@pytest.fixture()
def client() -> TestClient:
    app = create_app(engine_argv=["connect"])
    with TestClient(app, base_url="http://127.0.0.1") as c:
        yield c


def test_run_list_tools_local(client: TestClient) -> None:
    r = client.post("/api/run/list-tools")
    assert r.status_code == 200
    body = r.json()
    assert body["returncode"] == 0
    assert body["reaches_anl"] is False
    assert "opencode" in body["stdout"]


def test_run_unknown_verb_rejected(client: TestClient) -> None:
    r = client.post("/api/run/clean")  # a real verb, but not an info verb
    assert r.status_code == 400
    assert "list-tools" in r.json()["allowed"]


def test_info_verbs_anl_flags() -> None:
    # Guardrail: only list-tools is local; the others must be flagged ANL so the
    # UI never auto-runs them.
    assert INFO_VERBS["list-tools"]["anl"] is False
    assert INFO_VERBS["status"]["anl"] is True
    assert INFO_VERBS["list-models"]["anl"] is True


def test_run_bad_cli_tool_rejected(client: TestClient) -> None:
    r = client.post("/api/run/list-models?cli_tool=bad;rm")
    assert r.status_code == 400


# -- /ws launch parameterization --------------------------------------------

def test_ws_launch_verb_overrides_default(client: TestClient) -> None:
    # Server default is connect; ?verb=help must run help instead (no ANL).
    out = b""
    exit_status: object = "missing"
    with client.websocket_connect("/ws?verb=help", headers={"host": "127.0.0.1"}) as ws:
        ws.send_text(CTRL + json.dumps({"op": "resize", "rows": 40, "cols": 120}))
        for _ in range(5000):
            msg = ws.receive()
            if msg["type"] == "websocket.close":
                break
            if msg.get("bytes") is not None:
                out += msg["bytes"]
            elif msg.get("text") is not None and msg["text"].startswith(EXIT):
                exit_status = json.loads(msg["text"][len(EXIT):])["exitstatus"]
                break
    assert b"connect" in out       # help text lists the connect verb
    assert exit_status == 0        # help returns cleanly (proves it ran help, not connect)


def test_ws_rejects_bad_launch_verb(client: TestClient) -> None:
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect("/ws?verb=bogus", headers={"host": "127.0.0.1"}):
            pass
    assert exc.value.code == 1008
