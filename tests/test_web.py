"""Web-layer tests: host-guard, static serving, health, and the full
WebSocket <-> PTY bridge round-trip -- driving the engine's ``help`` verb so no
ANL/SSH/network is touched.

Skipped entirely unless the ``[web]``/``[test]`` extras are installed.
"""

from __future__ import annotations

import json
import os

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

import argo_anywhere  # noqa: E402
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
    body = r.json()
    # D-031: /healthz carries a package marker + pid so a second argo-anywhere
    # trying to bind the same port can identify the incumbent as a sibling.
    assert body["status"] == "ok"
    assert body["app"] == "argo-anywhere"
    assert body["pid"] > 0
    assert body["package_version"]
    assert "app_cwd_short" in body


def test_api_status(client: TestClient) -> None:
    r = client.get("/api/status")
    assert r.status_code == 200
    body = r.json()
    assert "package" in body and "listeners" in body
    # The API reports the actual package version (don't pin a frozen patch).
    assert body["package"]["package_version"] == argo_anywhere.__version__
    assert isinstance(body["listeners"], list)


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


# -- D-031: /ws hard-blocks + panel routing ---------------------------------

@pytest.mark.parametrize("blocked_verb", ["run", "client"])
def test_ws_hard_blocks_run_and_client_from_embedded(
    client: TestClient, blocked_verb: str
) -> None:
    """D-031 D7a: run/client can't spawn in an embedded panel (would die on
    browser tab close)."""
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(
            f"/ws?verb={blocked_verb}", headers={"host": "127.0.0.1"}
        ):
            pass
    assert exc.value.code == 1008


# -- D-031 Task 3: cwd validation + /api/mkdir ------------------------------

def test_ws_rejects_bad_cwd(client: TestClient) -> None:
    """A relative cwd must be refused by /ws (defense in depth)."""
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(
            "/ws?verb=connect&cwd=./relative", headers={"host": "127.0.0.1"}
        ):
            pass
    assert exc.value.code == 1008


def test_ws_accepts_valid_cwd(client: TestClient, tmp_path) -> None:
    """A valid absolute cwd is accepted (spawn cwd threading lands in Task 4)."""
    # Use a returning verb (`help`) so the pty exits quickly.
    with client.websocket_connect(
        f"/ws?verb=help&cwd={tmp_path}", headers={"host": "127.0.0.1"}
    ) as ws:
        for _ in range(5000):
            msg = ws.receive()
            if msg["type"] == "websocket.close":
                break
            text = msg.get("text")
            if text and text.startswith(EXIT):
                break


def test_launch_external_rejects_bad_cwd(client: TestClient) -> None:
    r = client.post("/api/launch-external?verb=run&cwd=not-absolute")
    assert r.status_code == 400
    body = r.json()
    assert body["verdict"] == "bad_input"


def test_launch_external_missing_dir_is_409(client: TestClient, tmp_path) -> None:
    ghost = tmp_path / "does-not-exist"
    r = client.post(f"/api/launch-external?verb=run&cwd={ghost}")
    assert r.status_code == 409
    assert r.json()["verdict"] == "missing"


def test_mkdir_creates_missing_dir(client: TestClient, tmp_path) -> None:
    target = tmp_path / "new-project"
    assert not target.exists()
    r = client.post(f"/api/mkdir?path={target}")
    assert r.status_code == 201
    assert target.is_dir()
    body = r.json()
    assert body["created"] == str(target)


def test_mkdir_rejects_existing_dir(client: TestClient, tmp_path) -> None:
    r = client.post(f"/api/mkdir?path={tmp_path}")
    assert r.status_code == 409  # already exists
    body = r.json()
    assert "already" in body["error"]
    # The JS relies on the exact `error: "already exists"` string to
    # classify "409 already exists" as a recoverable outcome (dir is
    # present now, proceed with retry). If the wording changes here,
    # update the regex in _confirmAndMkdir in index.html.
    assert "already exists" in body["error"].lower()


def test_mkdir_rejects_relative_path(client: TestClient) -> None:
    r = client.post("/api/mkdir?path=./relative")
    assert r.status_code == 400
    assert r.json()["verdict"] == "bad_input"


def test_mkdir_rejects_when_path_is_a_file(client: TestClient, tmp_path) -> None:
    f = tmp_path / "not-a-dir"
    f.write_text("hi")
    r = client.post(f"/api/mkdir?path={f}")
    assert r.status_code == 400
    assert r.json()["verdict"] == "not_directory"


def test_validate_cwd_endpoint_ok(client: TestClient, tmp_path) -> None:
    r = client.get(f"/api/validate-cwd?path={tmp_path}")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["verdict"] == "ok"
    assert body["resolved"] == str(tmp_path.resolve())


def test_validate_cwd_endpoint_missing_is_409(client: TestClient, tmp_path) -> None:
    ghost = tmp_path / "no-such-dir"
    r = client.get(f"/api/validate-cwd?path={ghost}")
    assert r.status_code == 409
    assert r.json()["verdict"] == "missing"
    # Does NOT create the dir.
    assert not ghost.exists()


def test_validate_cwd_endpoint_bad_input(client: TestClient) -> None:
    r = client.get("/api/validate-cwd?path=./relative")
    assert r.status_code == 400
    assert r.json()["verdict"] == "bad_input"


# -- D-031 Task 5: /api/state (persisted UI state) --------------------------

@pytest.fixture()
def state_file(tmp_path, monkeypatch):
    """Redirect the state file to a tmp path so tests don't touch ~/."""
    from argo_anywhere import status as _status
    from argo_anywhere.web import state as _state

    p = tmp_path / "web_state.json"
    monkeypatch.setattr(_status, "WEB_STATE_FILE", p)
    monkeypatch.setattr(_state, "WEB_STATE_FILE", p)
    # ensure_app_home is called by save_state on default paths; keep it
    # from trying to touch the real ~/.argo_anywhere by pointing at tmp.
    monkeypatch.setattr(_status, "APP_HOME", tmp_path)
    return p


def test_api_state_defaults_on_fresh_install(client: TestClient, state_file) -> None:
    r = client.get("/api/state")
    assert r.status_code == 200
    body = r.json()
    assert body["mru"] == []
    assert body["divider_pct"] == 50
    assert body["theme"] == "auto"


def test_api_state_post_persists_divider_pct(client: TestClient, state_file) -> None:
    r = client.post("/api/state", json={"divider_pct": 65})
    assert r.status_code == 200
    assert r.json()["divider_pct"] == 65
    assert client.get("/api/state").json()["divider_pct"] == 65


def test_api_state_post_persists_theme(client: TestClient, state_file) -> None:
    r = client.post("/api/state", json={"theme": "light"})
    assert r.status_code == 200
    assert r.json()["theme"] == "light"


def test_api_state_post_rejects_non_json(client: TestClient, state_file) -> None:
    r = client.post("/api/state", content="not-json", headers={"content-type": "text/plain"})
    assert r.status_code == 400


# -- D-031 Task 5.5: theme toggle -----------------------------------------

# -- D-031 Task 7: /api/check-forbid + enforcement -----------------------

def test_check_forbid_allow_for_global_scope(client: TestClient, tmp_path) -> None:
    r = client.get(f"/api/check-forbid?path={tmp_path}&scope=global")
    assert r.status_code == 200
    assert r.json()["verdict"] == "allow"


def test_check_forbid_soft_warn_for_bare_project(client: TestClient, tmp_path) -> None:
    r = client.get(f"/api/check-forbid?path={tmp_path}&scope=project")
    assert r.status_code == 200
    assert r.json()["verdict"] == "soft_warn"


def test_check_forbid_allow_with_git_dir(client: TestClient, tmp_path) -> None:
    (tmp_path / ".git").mkdir()
    r = client.get(f"/api/check-forbid?path={tmp_path}&scope=project")
    assert r.status_code == 200
    assert r.json()["verdict"] == "allow"


def test_check_forbid_hard_block_returns_403(client: TestClient) -> None:
    # /etc is hard-blocked for project scope (assuming it exists).
    if not os.path.isdir("/etc"):
        import pytest as _pytest
        _pytest.skip("/etc not present")
    r = client.get("/api/check-forbid?path=/etc&scope=project")
    assert r.status_code == 403
    assert r.json()["verdict"] == "hard_block"


def test_launch_external_forbid_hard_block(client: TestClient) -> None:
    if not os.path.isdir("/etc"):
        import pytest as _pytest
        _pytest.skip("/etc not present")
    r = client.post("/api/launch-external?verb=run&cwd=/etc&scope=project&terminal=fake")
    assert r.status_code == 403
    assert r.json()["verdict"] == "hard_block"


def test_ws_forbid_hard_block(client: TestClient) -> None:
    if not os.path.isdir("/etc"):
        import pytest as _pytest
        _pytest.skip("/etc not present")
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(
            "/ws?verb=connect&cwd=/etc&scope=project",
            headers={"host": "127.0.0.1"},
        ):
            pass
    assert exc.value.code == 1008


# -- D-031 clarification: GET /api/models (structured model catalog) -------

def _fake_engine_result(stdout: str, returncode: int = 0, stderr: str = ""):
    """Build a driver.EngineResult stand-in for monkeypatching run_engine."""
    from argo_anywhere.driver import EngineResult
    return EngineResult(
        argv=["list-models", "--format", "json"],
        returncode=returncode, stdout=stdout, stderr=stderr,
    )


def test_api_models_returns_structured_payload(
    client: TestClient, monkeypatch
) -> None:
    """The endpoint parses list-models --format json and reshapes the
    per-row 'configured' string into an explicit ``in_opencode_config``
    boolean, plus counts + a note explaining what the flag means (bug
    2026-07-13: raw output looked like Claude 4.8 was "misconfigured for
    Claude Code" when it was really just absent from OpenCode's picker)."""
    from argo_anywhere.web import app as _app

    payload = """[
      {"internal_name": "gpt4o",       "id": "gpt-4o",        "provider": "openai", "modalities": "text+image->text", "configured": "yes"},
      {"internal_name": "claudeopus48","id": "claude-4.8-opus","provider": "claude", "modalities": "text+image->text", "configured": "no"},
      {"internal_name": "gemini25pro", "id": "gemini-2.5-pro","provider": "gemini", "modalities": "text->text",       "configured": "orphan"}
    ]"""
    monkeypatch.setattr(_app, "run_engine",
                        lambda argv, timeout=30: _fake_engine_result(payload))

    r = client.get("/api/models")
    assert r.status_code == 200
    body = r.json()
    assert body["opencode_config_present"] is True
    assert body["counts"] == {"total": 3, "in_config": 1, "orphan": 1}
    # Per-row: the "configured" string becomes an explicit boolean +
    # ``is_orphan`` flag; the header note names what the flag means.
    by_id = {m["id"]: m for m in body["models"]}
    assert by_id["gpt-4o"]["in_opencode_config"] is True
    assert by_id["gpt-4o"]["is_orphan"] is False
    assert by_id["claude-4.8-opus"]["in_opencode_config"] is False
    assert by_id["claude-4.8-opus"]["is_orphan"] is False
    assert by_id["gemini-2.5-pro"]["in_opencode_config"] is False
    assert by_id["gemini-2.5-pro"]["is_orphan"] is True
    # The disambiguating note must be present + name the tool
    # explicitly.
    assert "opencode" in body["note"].lower()
    assert "claude code" in body["note"].lower() or "aider" in body["note"].lower()


def test_api_models_omits_opencode_fields_when_no_config(
    client: TestClient, monkeypatch
) -> None:
    """When the engine's JSON rows don't include the ``configured`` key
    (no OpenCode config on disk), the endpoint's per-row payload
    likewise omits ``in_opencode_config`` and reports the counts
    accordingly. This is the "beginner without OpenCode installed"
    happy path -- no misleading badges."""
    from argo_anywhere.web import app as _app

    payload = """[
      {"internal_name": "gpt4o", "id": "gpt-4o", "provider": "openai", "modalities": "text->text"}
    ]"""
    monkeypatch.setattr(_app, "run_engine",
                        lambda argv, timeout=30: _fake_engine_result(payload))
    r = client.get("/api/models")
    assert r.status_code == 200
    body = r.json()
    assert body["opencode_config_present"] is False
    assert body["counts"] == {"total": 1, "in_config": 0, "orphan": 0}
    assert "in_opencode_config" not in body["models"][0]


def test_api_models_reports_engine_failure(
    client: TestClient, monkeypatch
) -> None:
    from argo_anywhere.web import app as _app
    monkeypatch.setattr(
        _app, "run_engine",
        lambda argv, timeout=30: _fake_engine_result("", returncode=2, stderr="channel down"),
    )
    r = client.get("/api/models")
    assert r.status_code == 502
    assert "channel down" in r.json()["error"]


def test_api_models_reports_malformed_json(
    client: TestClient, monkeypatch
) -> None:
    from argo_anywhere.web import app as _app
    monkeypatch.setattr(_app, "run_engine",
                        lambda argv, timeout=30: _fake_engine_result("not-json{"))
    r = client.get("/api/models")
    assert r.status_code == 502
    assert "malformed JSON" in r.json()["error"]


def test_api_models_timeout_returns_504(
    client: TestClient, monkeypatch
) -> None:
    import subprocess as _sp
    from argo_anywhere.web import app as _app

    def _boom(argv, timeout=30):
        raise _sp.TimeoutExpired(cmd=argv, timeout=timeout)
    monkeypatch.setattr(_app, "run_engine", _boom)
    r = client.get("/api/models")
    assert r.status_code == 504


def test_index_ships_light_and_dark_palettes(client: TestClient) -> None:
    r = client.get("/", headers={"host": "127.0.0.1"})
    assert r.status_code == 200
    body = r.text
    # Both palette blocks + the toggle button must be present.
    assert '[data-theme="dark"]' in body
    assert '[data-theme="light"]' in body
    assert 'id="themeToggle"' in body
    # Term-bg is now a CSS variable, no more hardcoded #0f131b in .termbody.
    assert 'background: var(--term-bg)' in body


def test_full_missing_dir_flow_launch_then_mkdir_then_retry(
    client: TestClient, state_file, tmp_path, monkeypatch
) -> None:
    """Regression for the retry-after-mkdir flow the user reported: a first
    ``launch-external`` on a missing dir returns 409; a subsequent ``mkdir``
    returns 201; the retry launch returns 200 with ``ok: True``. If any
    server-side behaviour drifts (mkdir status codes, launch validator
    ordering), the JS's silent-retry contract breaks and users see the
    user's originally-reported "directory was created but the client was
    not instantiated" bug."""
    from argo_anywhere import external_terminal as ext

    monkeypatch.setattr(
        ext, "open_external_terminal",
        lambda argv, terminal=None, cwd=None: {
            "ok": True, "terminal": "iterm", "terminal_id": "iterm",
            "command": " ".join(argv), "error": None,
        },
    )
    monkeypatch.setattr(
        ext, "available_terminals",
        lambda system=None: [{"id": "iterm", "label": "iTerm"}],
    )

    missing = tmp_path / "does-not-exist-yet"

    # Step 1: initial launch attempt -> 409 missing.
    r1 = client.post(
        f"/api/launch-external?verb=run&cli_tool=opencode&scope=global"
        f"&terminal=iterm&cwd={missing}"
    )
    assert r1.status_code == 409
    assert r1.json()["verdict"] == "missing"

    # Step 2: user confirms; JS POSTs /api/mkdir.
    r2 = client.post(f"/api/mkdir?path={missing}")
    assert r2.status_code == 201
    assert missing.is_dir()

    # Step 3: JS retries the launch with the SAME params -> must succeed now.
    r3 = client.post(
        f"/api/launch-external?verb=run&cli_tool=opencode&scope=global"
        f"&terminal=iterm&cwd={missing}"
    )
    assert r3.status_code == 200, r3.text
    assert r3.json()["ok"] is True


def test_mkdir_of_already_existing_dir_is_recoverable_signal(
    client: TestClient, tmp_path
) -> None:
    """A doubled UI action (or a concurrent instance) can leave the dir
    present by the time /api/mkdir fires. The JS treats 409 + 'already
    exists' as a recoverable outcome so the launch still retries; this
    test guards that the server surface actually returns that exact shape."""
    r = client.post(f"/api/mkdir?path={tmp_path}")
    assert r.status_code == 409
    body = r.json()
    assert body["error"] == "already exists"
    assert body["path"] == str(tmp_path)


def test_ws_touches_mru_on_successful_launch(client: TestClient, state_file, tmp_path) -> None:
    """A successful ws launch with a valid cwd bumps the MRU list (D-031 Task 5)."""
    with client.websocket_connect(
        f"/ws?verb=help&cwd={tmp_path}", headers={"host": "127.0.0.1"}
    ) as ws:
        for _ in range(5000):
            msg = ws.receive()
            if msg["type"] == "websocket.close":
                break
            text = msg.get("text")
            if text and text.startswith(EXIT):
                break
    mru = client.get("/api/state").json()["mru"]
    assert str(tmp_path) in mru


def test_launch_external_touches_mru_on_success(
    client: TestClient, state_file, tmp_path, monkeypatch
) -> None:
    # Stub out open_external_terminal so we don't actually spawn a window.
    from argo_anywhere import external_terminal as ext
    monkeypatch.setattr(
        ext, "open_external_terminal",
        lambda argv, terminal=None, cwd=None: {
            "ok": True, "terminal": "fake", "terminal_id": "fake",
            "command": " ".join(argv), "error": None,
        },
    )
    # Also stub available_terminals so the launcher doesn't reject "fake".
    monkeypatch.setattr(ext, "available_terminals", lambda system=None: [{"id": "fake", "label": "Fake"}])

    r = client.post(f"/api/launch-external?verb=run&cwd={tmp_path}&terminal=fake")
    assert r.status_code == 200
    # MRU now contains the tmp_path.
    mru = client.get("/api/state").json()["mru"]
    assert str(tmp_path) in mru


def test_ws_refuses_second_channel_when_one_alive() -> None:
    """D-031 A1: if a live Channel session exists, refuse the second connect
    attempt (the UI's launcher offers 'stop + replace' as the alternative)."""
    from starlette.websockets import WebSocketDisconnect

    from argo_anywhere.web.registry import ManagedSession, SessionRegistry

    app = create_app(engine_argv=["help"])

    # Pre-populate a fake live Channel session so the ws handler's
    # panel_alive("channel") check trips.
    class _FakeAlivePty:
        argv = ["connect"]
        pid = 4242

        def isalive(self):
            return True

        @property
        def exitstatus(self):
            return None

        def close(self):
            pass

    # Directly plant the session into the named slot (bypasses ws spawn).
    reg: SessionRegistry = app.state.registry
    fake = _FakeAlivePty()
    reg._sessions["s99"] = ManagedSession("s99", fake, panel="channel")  # type: ignore[arg-type]
    reg._panels["channel"] = reg._sessions["s99"]

    with TestClient(app, base_url="http://127.0.0.1") as c:
        with pytest.raises(WebSocketDisconnect) as exc:
            with c.websocket_connect("/ws?verb=connect", headers={"host": "127.0.0.1"}):
                pass
        assert exc.value.code == 1008
