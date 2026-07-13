"""Tests for the multi-instance guard on ``argo-anywhere web`` / ``app`` (D-031).

The probe function is exercised against a throwaway localhost HTTP server so we
never need to spawn a real uvicorn. The ``_cmd_web`` refusal path is exercised
by monkeypatching the probe -- keeps the tests fast + hermetic.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from argo_anywhere import cli


class _SiblingHandler(BaseHTTPRequestHandler):
    """/healthz that identifies as an argo-anywhere sibling."""

    def do_GET(self):  # noqa: N802
        if self.path == "/healthz":
            body = json.dumps({
                "status": "ok",
                "app": "argo-anywhere",
                "package_version": "9.9.9-test",
                "pid": 12345,
                "app_cwd_short": "~/tmp",
            }).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *a):  # silence
        pass


class _ForeignHandler(BaseHTTPRequestHandler):
    """/healthz that returns 200 but isn't argo-anywhere (foreign service)."""

    def do_GET(self):  # noqa: N802
        body = json.dumps({"status": "ok", "app": "something-else"}).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


def _run_server(handler_cls) -> tuple[HTTPServer, int]:
    srv = HTTPServer(("127.0.0.1", 0), handler_cls)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv, srv.server_address[1]


# -- probe function --------------------------------------------------------

def test_probe_returns_none_when_port_is_free() -> None:
    # Pick a very unlikely free port.
    assert cli._probe_peer_web("127.0.0.1", 1, timeout=0.3) is None


def test_probe_identifies_sibling() -> None:
    srv, port = _run_server(_SiblingHandler)
    try:
        peer = cli._probe_peer_web("127.0.0.1", port)
        assert peer is not None
        assert peer["kind"] == "sibling"
        assert peer["pid"] == 12345
        assert peer["package_version"] == "9.9.9-test"
        assert peer["app_cwd_short"] == "~/tmp"
    finally:
        srv.shutdown()


def test_probe_identifies_foreign_service() -> None:
    srv, port = _run_server(_ForeignHandler)
    try:
        peer = cli._probe_peer_web("127.0.0.1", port)
        assert peer is not None
        assert peer["kind"] == "foreign"
    finally:
        srv.shutdown()


# -- _cmd_web refusal path (probe is monkeypatched, no real bind) -----------

def test_cmd_web_refuses_when_sibling_present(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        cli, "_probe_peer_web",
        lambda host, port, timeout=1.0: {
            "kind": "sibling", "pid": 4321,
            "package_version": "3.1.0", "app_cwd_short": "~/.argo_anywhere",
        },
    )
    rc = cli._cmd_web(["--port", "8799"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "another argo-anywhere is already" in err
    assert "pid 4321" in err
    assert "--port 8800" in err  # helpful next-port hint


def test_cmd_web_refuses_when_foreign_service_present(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        cli, "_probe_peer_web",
        lambda host, port, timeout=1.0: {"kind": "foreign", "status": 200},
    )
    rc = cli._cmd_web(["--port", "8799"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "not argo-anywhere" in err
    assert "Refusing to bind" in err


def test_cmd_web_force_bypasses_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # With --force we skip the probe entirely; make it explode to prove it.
    def _boom(*a, **kw):
        raise AssertionError("probe should not be called with --force")

    monkeypatch.setattr(cli, "_probe_peer_web", _boom)
    # Prevent the real serve() from running -- stub it out.
    from argo_anywhere.web import app as _app

    called = {}

    def _fake_serve(**kwargs):
        called.update(kwargs)

    monkeypatch.setattr(_app, "serve", _fake_serve)
    # Also stub ensure_app_home to avoid touching ~/.argo_anywhere.
    from argo_anywhere import status as _status

    monkeypatch.setattr(_status, "ensure_app_home", lambda: __import__("pathlib").Path("/tmp"))

    rc = cli._cmd_web(["--port", "8799", "--force"])
    assert rc == 0
    assert called["port"] == 8799
