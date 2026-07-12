"""Status-module tests -- all local (no ANL). The health poll is exercised
against a throwaway localhost HTTP server, never a real tunnel.
"""

from __future__ import annotations

import json
import re
import socket
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

import argo_anywhere
from argo_anywhere import cli, status


# -- versions ---------------------------------------------------------------

def test_engine_version_matches_script_version() -> None:
    v = status.engine_version()
    # e.g. "2.2.1-dev"
    assert re.match(r"^\d+\.\d+\.\d+", v)


def test_package_info_shape() -> None:
    info = status.package_info()
    assert info["package_version"] == argo_anywhere.__version__
    assert info["engine_version"] == status.engine_version()
    assert len(info["engine_sha256_short"]) == 12
    assert info["python_version"]


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
