"""Web-layer tests: host-guard, static serving, health, and the full
WebSocket <-> PTY bridge round-trip -- driving the engine's ``help`` verb so no
ANL/SSH/network is touched.

Uses ``pytest.importorskip("fastapi")`` at module load so the file no-ops in the
unlikely case fastapi isn't importable (e.g. a broken install); a normal
``pipx install argo-anywhere`` + ``pip install -e '.[dev]'`` has it.
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
    # Web-UI Defect 3: the dashboard needs a destination it can defend, kept
    # separate from the cached name so the UI cannot conflate them.
    assert "verified_node" in body


def test_api_status_never_falls_back_to_the_cached_node(
    client: TestClient, monkeypatch
) -> None:
    """``verified_node`` must be None when the destination is unknown.

    The bug this guards: a listener on the cached port (ownership and far end
    both unknown) plus a cached node NAME were rendered together as a verified
    link. On a shared node that listener can be a co-tenant's argo-proxy. If
    ``verified_node`` ever silently inherits the cache, the UI goes back to
    asserting a topology it cannot see.
    """
    from argo_anywhere import status as status_mod

    monkeypatch.setattr(
        status_mod, "cached_state", lambda *_a, **_k: {
            "user": "jdoe", "node": "compute-99.cels.anl.gov", "port": 64751
        }
    )
    monkeypatch.setattr(
        status_mod, "local_listeners",
        lambda *_a, **_k: [status_mod.Listener(port=64751, pid=1, command="python3")],
    )
    monkeypatch.setattr(status_mod, "tunnel_destination", lambda *_a, **_k: None)

    body = client.get("/api/status").json()
    assert body["cached"]["node"] == "compute-99.cels.anl.gov"
    assert body["verified_node"] is None, (
        "an unattributable listener must not inherit the cached node name"
    )


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


class _FakeAlivePty:
    argv = ["connect"]
    pid = 4242

    def isalive(self):
        return True

    @property
    def exitstatus(self):
        return None

    def close(self):
        self.closed = True


def _plant_channel_session(app, sid: str = "s99") -> "object":
    """Plant a fake live Channel session directly into the named slot."""
    from argo_anywhere.web.registry import ManagedSession, SessionRegistry

    reg: SessionRegistry = app.state.registry
    fake = _FakeAlivePty()
    reg._sessions[sid] = ManagedSession(sid, fake, panel="channel")  # type: ignore[arg-type]
    reg._panels["channel"] = reg._sessions[sid]
    return fake


def test_ws_refuses_second_channel_when_tunnel_is_live(monkeypatch) -> None:
    """D-031 A1: if a live Channel session AND a live tunnel exist, refuse the
    second connect attempt (the UI's launcher offers 'stop + replace')."""
    from starlette.websockets import WebSocketDisconnect

    app = create_app(engine_argv=["help"])
    _plant_channel_session(app)

    # Registry follow-up (2026-07-22): the guard now confirms the tunnel is
    # actually serving before refusing. Force "tunnel live" so the classic
    # refuse-the-second-connect behavior holds.
    monkeypatch.setattr(
        "argo_anywhere.web.app._channel_tunnel_is_live", lambda: True
    )

    with TestClient(app, base_url="http://127.0.0.1") as c:
        with pytest.raises(WebSocketDisconnect) as exc:
            with c.websocket_connect("/ws?verb=connect", headers={"host": "127.0.0.1"}):
                pass
        assert exc.value.code == 1008


def test_ws_reaps_stale_channel_and_allows_reconnect(monkeypatch) -> None:
    """Registry follow-up (2026-07-22): a channel-owning engine process that
    outlived its tunnel (mux master idle-expired) must NOT wedge reconnect.

    When the slot is occupied but the tunnel is not serving (no loopback
    listener on the cached port), the guard reaps the stale session and lets
    the fresh ``connect`` proceed instead of refusing with 1008.
    """
    app = create_app(engine_argv=["help"])
    stale = _plant_channel_session(app, sid="s-stale")

    # Tunnel is DOWN (no listener) -> the guard should reap + allow.
    monkeypatch.setattr(
        "argo_anywhere.web.app._channel_tunnel_is_live", lambda: False
    )

    reg = app.state.registry
    with TestClient(app, base_url="http://127.0.0.1") as c:
        # The fresh connect is accepted (engine_argv=["help"] exits quickly);
        # it does NOT raise a 1008 WebSocketDisconnect on accept.
        with c.websocket_connect("/ws?verb=connect", headers={"host": "127.0.0.1"}):
            pass

    # The stale session was reaped: closed + removed from the id map + slot.
    assert getattr(stale, "closed", False) is True
    assert reg.get("s-stale") is None


# --- _channel_tunnel_is_live unit tests (the guard's live-check helper) ------
# The two ws tests above monkeypatch this helper out; these cover its own
# logic: cached-port -> listener match, and the no-cached-port fallback.


def test_channel_tunnel_is_live_true_when_listener_present(monkeypatch) -> None:
    """Cached port has a matching loopback listener -> live."""
    from argo_anywhere.status import Listener
    import argo_anywhere.web.app as appmod

    monkeypatch.setattr("argo_anywhere.status.cached_state", lambda *a, **k: {"port": 64742})
    monkeypatch.setattr(
        "argo_anywhere.status.local_listeners",
        lambda ports=None: [Listener(port=64742, pid=111, command="ssh")],
    )
    assert appmod._channel_tunnel_is_live() is True


def test_channel_tunnel_is_live_false_when_no_listener(monkeypatch) -> None:
    """Cached port but nothing listening -> dead (stale channel)."""
    import argo_anywhere.web.app as appmod

    monkeypatch.setattr("argo_anywhere.status.cached_state", lambda *a, **k: {"port": 64742})
    monkeypatch.setattr("argo_anywhere.status.local_listeners", lambda ports=None: [])
    assert appmod._channel_tunnel_is_live() is False


def test_channel_tunnel_is_live_false_when_no_cached_port(monkeypatch) -> None:
    """No cached port -> treat as not-live so a stale session never wedges
    reconnect (the guard must fall through to reap + allow)."""
    import argo_anywhere.web.app as appmod

    called = {"listeners": False}

    def _boom(ports=None):
        called["listeners"] = True
        return []

    monkeypatch.setattr("argo_anywhere.status.cached_state", lambda *a, **k: {"port": None})
    monkeypatch.setattr("argo_anywhere.status.local_listeners", _boom)
    assert appmod._channel_tunnel_is_live() is False
    # short-circuits before touching lsof (no port to identify a listener)
    assert called["listeners"] is False


# ===========================================================================
# D-032 (2026-07-15): /api/ssh-hosts endpoint tests.
# The parser itself is exercised in detail in tests/test_ssh_hosts.py; these
# tests cover the endpoint's caching + refresh contract only.
# ===========================================================================


def test_api_ssh_hosts_returns_list(client: TestClient) -> None:
    """Endpoint responds with {"hosts": [...]} shape."""
    r = client.get("/api/ssh-hosts")
    assert r.status_code == 200
    body = r.json()
    assert "hosts" in body
    assert isinstance(body["hosts"], list)


def test_api_ssh_hosts_cached_across_calls(monkeypatch, client: TestClient) -> None:
    """Second call without ?refresh=1 reuses the cache -- parser called once."""
    from argo_anywhere.web import ssh_hosts as m

    calls = {"n": 0}
    real = m.parse_ssh_config_hosts

    def counting(*a, **kw):
        calls["n"] += 1
        return real(*a, **kw)

    monkeypatch.setattr(m, "parse_ssh_config_hosts", counting)
    # Cache may already be populated from an earlier test in this session;
    # clear it via ?refresh=1 first, then measure.
    client.get("/api/ssh-hosts?refresh=1")
    calls["n"] = 0

    client.get("/api/ssh-hosts")
    client.get("/api/ssh-hosts")
    client.get("/api/ssh-hosts")

    assert calls["n"] == 0, (
        "expected the second+ calls to hit the cache; "
        f"parser was called {calls['n']} time(s) after the initial refresh"
    )


def test_api_ssh_hosts_refresh_bypasses_cache(
    monkeypatch, client: TestClient,
) -> None:
    """?refresh=1 forces the parser to re-read the file."""
    from argo_anywhere.web import ssh_hosts as m

    calls = {"n": 0}
    real = m.parse_ssh_config_hosts

    def counting(*a, **kw):
        calls["n"] += 1
        return real(*a, **kw)

    monkeypatch.setattr(m, "parse_ssh_config_hosts", counting)
    # Warm the cache first.
    client.get("/api/ssh-hosts?refresh=1")
    calls["n"] = 0

    client.get("/api/ssh-hosts?refresh=1")
    client.get("/api/ssh-hosts?refresh=1")

    assert calls["n"] == 2, (
        "expected each ?refresh=1 to re-invoke the parser; "
        f"got {calls['n']} calls (expected 2)"
    )


def test_api_ssh_hosts_host_guard(client: TestClient) -> None:
    """Endpoint honors the app-wide loopback host guard."""
    r = client.get(
        "/api/ssh-hosts",
        headers={"host": "evil.example.com"},
    )
    assert r.status_code == 403


# ===========================================================================
# D-032 (2026-07-15) end-to-end threading tests: /api/launch-external and
# /ws intake must pass node/user/jump_host/no_jump through to the engine
# argv.
#
# Post-audit fix (Gap-3, Gap-4 from
# notes/audit_v3_1_0_post_execution.md). Before this, only
# build_launch_argv itself was unit-tested; the endpoint threading was
# unverified.
# ===========================================================================


def test_launch_external_passes_d032_flags_through(
    monkeypatch, client: TestClient, tmp_path,
) -> None:
    """POST /api/launch-external?verb=connect&node=X&user=Y&jump_host=Z
    &no_jump=true results in the spawned engine argv containing the four
    corresponding flags. Uses monkeypatch on open_external_terminal to
    capture the argv without actually spawning."""
    from argo_anywhere import external_terminal as ext

    captured = {}

    def fake_open(argv, terminal=None, cwd=None):
        captured["argv"] = argv
        captured["cwd"] = cwd
        return {
            "ok": True, "terminal": "iterm", "terminal_id": "iterm",
            "command": " ".join(argv), "error": None,
        }

    monkeypatch.setattr(ext, "open_external_terminal", fake_open)
    monkeypatch.setattr(
        ext, "available_terminals",
        lambda system=None: [{"id": "iterm", "label": "iTerm"}],
    )

    r = client.post(
        f"/api/launch-external?verb=connect&node=polaris-login"
        f"&user=example-user&jump_host=bastion.example.com&no_jump=true"
        f"&terminal=iterm&cwd={tmp_path}"
    )
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True

    # The spawned argv has a console-script prefix; the tail is what
    # build_launch_argv produced. Assert each D-032 flag is present.
    argv = captured["argv"]
    assert "--node" in argv, f"missing --node in: {argv}"
    idx = argv.index("--node")
    assert argv[idx + 1] == "polaris-login"

    assert "--user" in argv
    idx = argv.index("--user")
    assert argv[idx + 1] == "example-user"

    assert "--jump-host" in argv
    idx = argv.index("--jump-host")
    assert argv[idx + 1] == "bastion.example.com"

    assert "--no-jump" in argv, f"--no-jump=true should emit --no-jump flag: {argv}"


def test_launch_external_omits_empty_d032_fields(
    monkeypatch, client: TestClient, tmp_path,
) -> None:
    """Empty strings for node/user/jump_host are OMITTED (not passed as
    `--node ""`). The engine's argv parser would reject the empty value
    if we passed it; the launcher's contract is "blank == let the engine
    resolve it."""
    from argo_anywhere import external_terminal as ext

    captured = {}

    def fake_open(argv, terminal=None, cwd=None):
        captured["argv"] = argv
        return {
            "ok": True, "terminal": "iterm", "terminal_id": "iterm",
            "command": " ".join(argv), "error": None,
        }

    monkeypatch.setattr(ext, "open_external_terminal", fake_open)
    monkeypatch.setattr(
        ext, "available_terminals",
        lambda system=None: [{"id": "iterm", "label": "iTerm"}],
    )

    r = client.post(
        f"/api/launch-external?verb=connect&node=&user=&jump_host=&no_jump=false"
        f"&terminal=iterm&cwd={tmp_path}"
    )
    assert r.status_code == 200
    argv = captured["argv"]
    assert "--node" not in argv, f"empty --node should be omitted: {argv}"
    assert "--user" not in argv
    assert "--jump-host" not in argv
    assert "--no-jump" not in argv


def test_launch_external_rejects_bad_node(
    monkeypatch, client: TestClient, tmp_path,
) -> None:
    """Shell-hostile input in `node` reaches build_launch_argv, which
    raises ValueError; endpoint translates to 400."""
    from argo_anywhere import external_terminal as ext

    monkeypatch.setattr(
        ext, "available_terminals",
        lambda system=None: [{"id": "iterm", "label": "iTerm"}],
    )

    from urllib.parse import quote
    bad_node = quote("user@host;rm -rf /")
    r = client.post(
        f"/api/launch-external?verb=connect&node={bad_node}"
        f"&terminal=iterm&cwd={tmp_path}"
    )
    assert r.status_code == 400
    assert "bad node" in r.json()["error"]


def test_ws_passes_d032_query_params_through(client: TestClient) -> None:
    """WebSocket intake threads node/user/jump_host/no_jump query params
    through to the engine argv. Uses `verb=help` so no ANL/SSH is
    touched; asserts the help text (proving help ran) AND doesn't crash
    (proving the D-032 params were accepted, not rejected)."""
    with client.websocket_connect(
        "/ws?verb=help&node=polaris-login&user=example-user"
        "&jump_host=bastion.example.com&no_jump=1",
        headers={"host": "127.0.0.1"},
    ) as ws:
        # Drain the WS stream. Should exit cleanly with the help text.
        out = b""
        exit_status: object = "missing"
        for _ in range(5000):
            msg = ws.receive()
            if msg["type"] == "websocket.close":
                break
            if msg.get("bytes") is not None:
                out += msg["bytes"]
            elif msg.get("text") is not None and msg["text"].startswith("\x00EXIT"):
                import json as _json
                exit_status = _json.loads(msg["text"][len("\x00EXIT"):])["exitstatus"]
                break

    # Help ran (proves the D-032 params didn't crash the intake).
    assert b"connect" in out, "help text should mention 'connect' subcommand"
    # The engine exited cleanly (rc=0 for help).
    assert exit_status == 0, f"engine should exit 0 for help; got {exit_status!r}"


def test_ws_rejects_bad_d032_query_params(client: TestClient) -> None:
    """Shell-hostile input in a D-032 query param → ws close code 1008
    (rejected launch spec; mirrors the existing bad-verb behavior)."""
    from starlette.websockets import WebSocketDisconnect
    from urllib.parse import quote

    bad = quote("user@host;evil")
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(
            f"/ws?verb=help&node={bad}",
            headers={"host": "127.0.0.1"},
        ):
            pass
    assert exc.value.code == 1008
