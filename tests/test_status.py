"""Status-module tests -- all local (no ANL). The health poll is exercised
against a throwaway localhost HTTP server, never a real tunnel.
"""

from __future__ import annotations

import json
import re
import socket
import textwrap
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

import argo_anywhere
from argo_anywhere import cli, status


# -- versions ---------------------------------------------------------------

def test_engine_version_matches_script_version() -> None:
    v = status.engine_version()
    # e.g. "2.3.0"
    assert re.match(r"^\d+\.\d+\.\d+", v)


def test_package_info_shape() -> None:
    info = status.package_info()
    assert info["package_version"] == argo_anywhere.__version__
    assert info["engine_version"] == status.engine_version()
    assert len(info["engine_sha256_short"]) == 12
    assert info["python_version"]
    # D-031 D3a: package_info exposes the app's own cwd (both absolute + short).
    assert "app_cwd" in info and info["app_cwd"]
    assert "app_cwd_short" in info and info["app_cwd_short"]


# -- D-031: app-cwd helpers (STATE_DIR / APP_HOME + display) ----------------

def test_app_home_constant_matches_engine_convention() -> None:
    # D-023: canonical install lives at ~/.argo_anywhere (matches the engine's
    # CANONICAL_HOME). The Python constant must agree so both sides target the
    # same dir.
    import os
    assert str(status.APP_HOME) == os.path.expanduser("~/.argo_anywhere")


def test_ensure_app_home_creates_and_is_idempotent(tmp_path, monkeypatch) -> None:
    # Redirect APP_HOME to a tmp dir so we don't touch the real one.
    target = tmp_path / ".argo_anywhere"
    monkeypatch.setattr(status, "APP_HOME", target)
    assert not target.exists()
    assert status.ensure_app_home() == target
    assert target.is_dir()
    # Second call is a no-op.
    status.ensure_app_home()
    assert target.is_dir()


def test_app_cwd_display_collapses_home(tmp_path, monkeypatch) -> None:
    # ~/foo -> ~/foo; the exact ~ collapse is what we assert.
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    inner = fake_home / "projects" / "x"
    inner.mkdir(parents=True)

    import os
    monkeypatch.setattr(os, "getcwd", lambda: str(inner))
    monkeypatch.setenv("HOME", str(fake_home))
    # Path.home() reads HOME on POSIX; force refresh for the assertion below.
    from pathlib import Path
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))
    assert status.app_cwd_display() == "~/projects/x"


def test_app_cwd_display_falls_back_when_outside_home(tmp_path, monkeypatch) -> None:
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    outside = tmp_path / "elsewhere"
    outside.mkdir()

    import os
    monkeypatch.setattr(os, "getcwd", lambda: str(outside))
    from pathlib import Path
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))
    # Not under $HOME -> report the absolute path unchanged.
    assert status.app_cwd_display() == str(outside)


# -- channel_health (localhost stub, never ANL) -----------------------------

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

    def log_message(self, *args):  # silence
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


def test_channel_health_up(health_server: int) -> None:
    h = status.channel_health(health_server, timeout=3)
    assert h.up is True
    assert "healthy" in (h.status or "")
    assert h.latency_ms is not None


def test_channel_health_down_never_raises() -> None:
    # An almost-certainly-closed port: bind+close to obtain a free one.
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    h = status.channel_health(port, timeout=1)
    assert h.up is False
    assert h.status is None
    assert h.error is not None


# -- local_listeners --------------------------------------------------------

def test_local_listeners_finds_a_bound_port() -> None:
    lsock = socket.socket()
    lsock.bind(("127.0.0.1", 0))
    lsock.listen(1)
    port = lsock.getsockname()[1]
    try:
        found = status.local_listeners([port])
        assert any(ln.port == port for ln in found), f"{port} not found in {found}"
    finally:
        lsock.close()


# -- cached_state -----------------------------------------------------------

def test_cached_state_reads_files(tmp_path) -> None:
    (tmp_path / "user").write_text("someuser\n")
    (tmp_path / "node").write_text("compute-01.example\n")
    (tmp_path / "port").write_text("64742\n")
    st = status.cached_state(tmp_path)
    assert st == {"user": "someuser", "node": "compute-01.example", "port": 64742}


def test_cached_state_missing_files(tmp_path) -> None:
    st = status.cached_state(tmp_path)
    assert st == {"user": None, "node": None, "port": None}


def test_cached_state_nonnumeric_port(tmp_path) -> None:
    (tmp_path / "port").write_text("not-a-port\n")
    assert status.cached_state(tmp_path)["port"] is None


# -- CLI `info` -------------------------------------------------------------

def test_cli_info_human(capsys: pytest.CaptureFixture[str]) -> None:
    rc = cli.main(["info"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "argo-anywhere" in out
    assert argo_anywhere.__version__ in out


def test_cli_info_json(capsys: pytest.CaptureFixture[str]) -> None:
    rc = cli.main(["info", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["package"]["package_version"] == argo_anywhere.__version__
    assert isinstance(payload["listeners"], list)


# -- tunnel destination (web-UI Defect 3) ------------------------------------
#
# The dashboard used to derive "connected to <node>" from two things that
# support no such claim: an lsof hit on the cached port (ownership unknown,
# destination unknown) and the node NAME out of the cache (a memory of a past
# run). Rendered together as a lit node hop plus "localhost:PORT -> compute-01",
# that is reachability presented as topology -- the same inference that let the
# 2026-08-10 incident show ALL GREEN while traffic went through a stranger's
# argo-proxy, and a diagram asserts it more forcefully than a text row.
#
# tunnel_destination mirrors the engine's local_tunnel_destination: parse the
# ControlPath socket basename out of the listener's command line, which openssh
# names after the host it is really talking to. Verified byte-equal against the
# engine on a live channel (both returned compute-01.cels.anl.gov for :64751).


def test_tunnel_destination_unknown_port_is_none() -> None:
    """No listener => None. Never a guess, never the cache."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        free_port = probe.getsockname()[1]
    assert status.tunnel_destination(free_port) is None


def test_tunnel_destination_plain_listener_is_none() -> None:
    """A listener that is not one of our tunnels is unattributable.

    This is the case that matters: something IS serving the port, so the old
    code lit the node hop. It may be a co-tenant's argo-proxy.
    """
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    try:
        assert status.tunnel_destination(srv.getsockname()[1]) is None
    finally:
        srv.close()


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        # mux master, as macOS renders it
        ("ssh: /Users/jdoe/.ssh/sockets/argo-anywhere-jdoe-compute-01.cels.anl.gov-22 [mux]",
         "compute-01.cels.anl.gov"),
        # foreground tunnel carrying an explicit ControlPath
        ("ssh -N -L 64751:localhost:64751 -o ControlPath=/Users/jdoe/.ssh/sockets/"
         "argo-anywhere-jdoe-compute-02.cels.anl.gov-22 jdoe@compute-02.cels.anl.gov",
         "compute-02.cels.anl.gov"),
        # legacy v1.x socket prefix, still alive mid-upgrade
        ("ssh: /Users/jdoe/.ssh/sockets/argo-opencode-jdoe-compute-03.cels.anl.gov-22 [mux]",
         "compute-03.cels.anl.gov"),
        # a foreign ssh tunnel on the same port -- not ours, so unknown
        ("ssh -N -L 64751:localhost:64751 someone@elsewhere.example.com", None),
        # some unrelated server
        ("/usr/bin/python3 -m http.server 64751", None),
    ],
)
def test_tunnel_destination_parses_control_path(
    monkeypatch: pytest.MonkeyPatch, command: str, expected: str | None
) -> None:
    """Parsing mirrors the engine's basename walk: strip prefix, port, user."""
    import subprocess as _sp

    def fake_run(argv, **kwargs):  # noqa: ANN001, ANN003
        if argv[0].endswith("lsof"):
            return _sp.CompletedProcess(argv, 0, stdout="4242\n", stderr="")
        if argv[0] == "ps":
            return _sp.CompletedProcess(argv, 0, stdout=command + "\n", stderr="")
        raise AssertionError(f"unexpected call: {argv}")

    monkeypatch.setattr(status.shutil, "which", lambda _tool: "/usr/bin/lsof")
    monkeypatch.setattr(status.subprocess, "run", fake_run)
    assert status.tunnel_destination(64751) == expected


def test_tunnel_destination_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """Degrade to None on any tooling failure; the dashboard must not 500."""
    def boom(*_args, **_kwargs):  # noqa: ANN002, ANN003
        raise OSError("lsof exploded")

    monkeypatch.setattr(status.shutil, "which", lambda _tool: "/usr/bin/lsof")
    monkeypatch.setattr(status.subprocess, "run", boom)
    assert status.tunnel_destination(64751) is None


def test_tunnel_destination_makes_no_network_call() -> None:
    """The 'no ANL contact of its own' contract still holds.

    Local inspection only: lsof + ps. If this ever grows an ssh round trip it
    belongs behind an explicit user action, not the status poll.
    """
    import ast
    import inspect

    src = inspect.getsource(status.tunnel_destination)
    # Strip comments + docstrings: the prose legitimately says "openssh" and
    # "no SSH", and a substring match on the raw source would fail on those.
    # Only executable code is in scope here.
    tree = ast.parse(textwrap.dedent(src))
    code_strings = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]
    # The only string literals this function should carry are argv fragments
    # for lsof / ps and the regex bits -- nothing naming ssh or a URL scheme.
    for literal in code_strings:
        low = literal.lower()
        assert not low.startswith(("http://", "https://")), (
            f"tunnel_destination must not contact anything; found {literal!r}"
        )
    argv_commands = {
        node.value
        for call in ast.walk(tree)
        if isinstance(call, ast.Call)
        for arg in call.args
        if isinstance(arg, ast.List)
        for node in arg.elts[:1]
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    assert argv_commands <= {"ps"}, (
        f"tunnel_destination may only shell out to lsof/ps; got {argv_commands}"
    )
    for banned in ("urlopen", "create_connection", "urllib"):
        assert banned not in src, (
            f"tunnel_destination must stay local; found {banned!r}"
        )


# -- channel discovery (2026-08-12 field incident) ---------------------------
#
# The dashboard answered "are we connected?" with "is something listening on
# the CACHED port?", which makes the cache load-bearing for a question it
# cannot answer. A run that aborted, died, or moved ports left the cache naming
# a dead port, and the UI reported "not connected" while a healthy channel ran
# in the embedded terminal beside it. discover_channels() answers from what
# exists: an ssh listener whose ControlPath names an argo-anywhere socket.


def test_discover_channels_ignores_the_cache(monkeypatch) -> None:
    """Discovery must not consult cached state at all."""
    import inspect

    src = inspect.getsource(status.discover_channels)
    assert "cached_state" not in src, (
        "discover_channels must answer from live inspection; consulting the "
        "cache reintroduces the bug it exists to fix"
    )


def test_discover_channels_finds_a_tunnel_on_an_uncached_port(monkeypatch) -> None:
    """The field case: a live channel on a port the cache does not name."""
    monkeypatch.setattr(
        status, "local_listeners",
        lambda *_a, **_k: [
            status.Listener(port=64743, pid=53133, command="ssh"),
            status.Listener(port=8799, pid=1, command="python3.1"),
        ],
    )
    monkeypatch.setattr(
        status, "tunnel_destination",
        lambda port: "compute-01.cels.anl.gov" if port == 64743 else None,
    )
    found = status.discover_channels()
    assert [c.port for c in found] == [64743], (
        "a live tunnel must be found regardless of what the cache says"
    )
    assert found[0].node == "compute-01.cels.anl.gov"


def test_discover_channels_ignores_non_ssh_listeners(monkeypatch) -> None:
    """A random loopback server is not a channel.

    Real laptops have plenty (Box, Adobe, adb, the web UI itself); calling one
    of those a channel would be the same overclaim in a new place.
    """
    monkeypatch.setattr(
        status, "local_listeners",
        lambda *_a, **_k: [status.Listener(port=17223, pid=2097, command="Box")],
    )
    monkeypatch.setattr(status, "tunnel_destination", lambda _p: "somewhere")
    assert status.discover_channels() == []


def test_discover_channels_ignores_unattributable_ssh(monkeypatch) -> None:
    """An ssh tunnel that is not ours has no ControlPath we can parse."""
    monkeypatch.setattr(
        status, "local_listeners",
        lambda *_a, **_k: [status.Listener(port=2222, pid=99, command="ssh")],
    )
    monkeypatch.setattr(status, "tunnel_destination", lambda _p: None)
    assert status.discover_channels() == []


def test_discover_channels_empty_means_no_channel(monkeypatch) -> None:
    """Empty is a real answer, never 'unknown'."""
    monkeypatch.setattr(status, "local_listeners", lambda *_a, **_k: [])
    assert status.discover_channels() == []


# -- per-tool config state (2026-08-12) --------------------------------------
#
# The dashboard showed only WHICH tools argo-anywhere supports, so a user whose
# channel had moved saw three cheerful chips and no hint that two of their
# tools pointed at a dead port. client_tool_configs is the Python mirror of the
# engine's enumerate_client_ports; keep the two in step.


def test_client_tool_configs_covers_every_supported_tool() -> None:
    """A tool absent from the table is invisible to the dashboard.

    That is exactly how aider went unnoticed on the engine side until
    2026-08-12: it wrote a port into its config and no coherence check knew.
    """
    tools = {t.tool for t in status.client_tool_configs()}
    assert {"opencode", "claudecode", "aider"} <= tools, (
        f"a supported tool is missing from _TOOL_CONFIGS: {tools}"
    )


def test_client_tool_configs_reads_each_format(tmp_path, monkeypatch) -> None:
    """Three tools, three different config formats, one answer shape."""
    oc = tmp_path / "opencode.json"
    oc.write_text(json.dumps({"provider": {"argo": {"options": {
        "baseURL": "http://localhost:64743/v1"}}}}))
    cc = tmp_path / "claude.json"
    cc.write_text(json.dumps({"env": {
        "ANTHROPIC_BASE_URL": "http://localhost:64744"}}))
    ai = tmp_path / "aider.yml"
    ai.write_text("model: openai/argo:gpt-4o\nopenai-api-base: http://localhost:64745/v1\n")

    monkeypatch.setattr(status, "_TOOL_CONFIGS", (
        ("opencode", str(oc)), ("claudecode", str(cc)), ("aider", str(ai)),
    ))
    got = {t.tool: t.port for t in status.client_tool_configs()}
    assert got == {"opencode": 64743, "claudecode": 64744, "aider": 64745}


def test_missing_config_reports_unconfigured_not_an_error(tmp_path, monkeypatch) -> None:
    """"Never set up" is a distinct state from "set up wrong".

    They need different advice -- `run <tool>` versus `configure <tool>` -- so
    collapsing them into one would give half the users the wrong instruction.
    """
    monkeypatch.setattr(status, "_TOOL_CONFIGS", (
        ("opencode", str(tmp_path / "nope.json")),
    ))
    (t,) = status.client_tool_configs()
    assert t.configured is False and t.port is None


def test_malformed_config_does_not_raise(tmp_path, monkeypatch) -> None:
    """A hand-edited config must not take the whole dashboard down."""
    bad = tmp_path / "bad.json"
    bad.write_text("{ this is not json")
    empty = tmp_path / "empty.yml"
    empty.write_text("")
    monkeypatch.setattr(status, "_TOOL_CONFIGS", (
        ("opencode", str(bad)), ("aider", str(empty)),
    ))
    got = status.client_tool_configs()
    assert all(t.port is None and t.configured is False for t in got)


def test_client_tool_configs_makes_no_network_call() -> None:
    """Local file reads only -- it runs inside the status poll."""
    import ast
    import inspect
    import textwrap

    # Strip docstrings + comments: the prose legitimately says "no subprocess",
    # and a raw substring match fails on the very sentence promising the
    # property. Same trap as tunnel_destination's guard, which matched "ssh"
    # inside "openssh". Check the CALLS instead.
    called = set()
    for fn in (
        status.client_tool_configs,
        status._port_from_opencode,
        status._port_from_claudecode,
        status._port_from_aider,
    ):
        tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                f = node.func
                if isinstance(f, ast.Name):
                    called.add(f.id)
                elif isinstance(f, ast.Attribute):
                    called.add(f.attr)
                    if isinstance(f.value, ast.Name):
                        called.add(f"{f.value.id}.{f.attr}")
    for banned in ("run", "Popen", "check_output", "urlopen", "system",
                   "subprocess.run", "socket.create_connection"):
        assert banned not in called, (
            f"tool-config reading must stay local; it calls {banned!r}"
        )
