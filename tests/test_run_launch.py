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


# -- D-032 (2026-07-15) build_launch_argv SSH-target overrides -------------
# The new node/user/jump-host/no-jump kwargs are C4's addition; they map 1:1
# to the engine's --node / --user / --jump-host / --no-jump flags.


def test_build_argv_with_node_alias() -> None:
    """Passing node=polaris-login threads through as --node polaris-login."""
    argv = build_launch_argv("connect", node="polaris-login")
    assert argv == ["--node", "polaris-login", "connect"]


def test_build_argv_with_all_d032_flags() -> None:
    """All four D-032 kwargs threaded in the documented order (node, user,
    jump-host, no-jump). Order matters because the engine's argv parser is
    positional-agnostic BUT reviewers scan visually and out-of-order flags
    are noisy in commit diffs."""
    argv = build_launch_argv(
        "connect",
        node="polaris-login",
        user="example-user",
        jump_host="bastion.example.com",
    )
    assert argv == [
        "--node", "polaris-login",
        "--user", "example-user",
        "--jump-host", "bastion.example.com",
        "connect",
    ]


def test_build_argv_no_jump_flag() -> None:
    """no_jump=True emits --no-jump (no value)."""
    argv = build_launch_argv("connect", no_jump=True)
    assert argv == ["--no-jump", "connect"]


def test_build_argv_no_jump_and_jump_host_can_coexist() -> None:
    """Both --jump-host and --no-jump can be present in argv. The engine's
    resolution block treats --no-jump as more explicit (wins), so the caller
    who sets both gets no-jump semantics -- which is the CLI's behavior too."""
    argv = build_launch_argv(
        "connect",
        jump_host="bastion.example.com",
        no_jump=True,
    )
    assert "--no-jump" in argv
    assert "--jump-host" in argv
    assert "bastion.example.com" in argv


def test_build_argv_empty_d032_fields_omitted() -> None:
    """Empty strings for the D-032 flag values are omitted from argv (they
    don't become `--node ""` etc.). This matches the launcher's semantics:
    blank field == "let the engine resolve it," NOT "pass an empty value.\""""
    argv = build_launch_argv(
        "connect",
        node="",
        user="",
        jump_host="",
        no_jump=False,
    )
    assert argv == ["connect"]


@pytest.mark.parametrize("bad_node", [
    "user@host",         # @ would confuse ${user}@${host} target parse
    "path/to/host",      # / is a path separator
    "host:22",           # : is a URI separator
    "space in name",     # whitespace
    "",                  # empty (would fail if we treated blank as valid)
    "-flag-like",        # leading dash would look like a flag
    "$injection",        # shell metachar
    "x" * 300,           # exceeds RFC 1035 253-char cap
])
def test_build_argv_rejects_bad_node(bad_node: str) -> None:
    """_SAFE_HOSTLIKE rejects the shape of things that would confuse the
    engine's argv parse or shell semantics. Empty strings are silently
    omitted (per test_build_argv_empty_d032_fields_omitted), so pass a
    non-empty guardrail explicitly here."""
    if bad_node == "":
        # Empty is handled by the "omit-from-argv" path, not the reject path.
        argv = build_launch_argv("connect", node=bad_node)
        assert "--node" not in argv
        return
    with pytest.raises(ValueError, match="bad node"):
        build_launch_argv("connect", node=bad_node)


@pytest.mark.parametrize("bad_user", [
    "user@host", "path/to/user", "user:pass", "with space",
    "$USER", "x" * 300,
])
def test_build_argv_rejects_bad_user(bad_user: str) -> None:
    with pytest.raises(ValueError, match="bad user"):
        build_launch_argv("connect", user=bad_user)


@pytest.mark.parametrize("bad_jump", [
    "user@host", "host:22", "with space", "$var",
])
def test_build_argv_rejects_bad_jump_host(bad_jump: str) -> None:
    with pytest.raises(ValueError, match="bad jump_host"):
        build_launch_argv("connect", jump_host=bad_jump)


def test_build_argv_accepts_legitimate_hostnames() -> None:
    """_SAFE_HOSTLIKE must accept real-world hostnames: dotted fqdns,
    hyphenated aliases, underscored usernames, mixed case (unusual but
    legal)."""
    argv = build_launch_argv(
        "connect",
        node="compute-01.cels.anl.gov",
        user="j_smith",
        jump_host="Alt-Jump.Example.ORG",
    )
    assert "compute-01.cels.anl.gov" in argv
    assert "j_smith" in argv
    assert "Alt-Jump.Example.ORG" in argv


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
