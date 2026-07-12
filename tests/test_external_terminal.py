"""Native new-terminal launcher tests -- no window is ever opened.

The spawn is replaced with fakes; only pure command/AppleScript builders and
the OS dispatch are exercised. Nothing here reaches ANL.
"""

from __future__ import annotations

import pytest

import argo_anywhere.external_terminal as et
from argo_anywhere.external_terminal import (
    build_command,
    cli_terminal_argv,
    console_command,
    macos_osa_script,
    open_external_terminal,
)


# -- pure builders ----------------------------------------------------------

def test_build_command_plain() -> None:
    assert build_command(["argo-anywhere", "client"]) == "argo-anywhere client"


def test_build_command_quotes_and_cwd() -> None:
    cmd = build_command(["argo-anywhere", "run", "--scope", "a b"], cwd="/tmp/x y")
    assert cmd == "cd '/tmp/x y' && argo-anywhere run --scope 'a b'"


def test_apple_quote_escapes() -> None:
    assert et._apple_quote('a"b\\c') == 'a\\"b\\\\c'


def test_macos_script_terminal_vs_iterm() -> None:
    t = macos_osa_script("terminal", "argo-anywhere client")
    assert 'application "Terminal"' in t and "do script" in t and "client" in t
    i = macos_osa_script("iterm", "argo-anywhere client")
    assert 'application "iTerm"' in i and "create window" in i and "client" in i


def test_cli_terminal_argv_shapes() -> None:
    assert cli_terminal_argv("xterm", "cmd") == ["xterm", "-e", "bash", "-lc", "cmd"]
    assert cli_terminal_argv("gnome-terminal", "cmd") == ["gnome-terminal", "--", "bash", "-lc", "cmd"]
    assert cli_terminal_argv("kitty", "cmd") == ["kitty", "bash", "-lc", "cmd"]


def test_console_command_is_invokable() -> None:
    cc = console_command()
    assert cc and (cc[0].endswith("argo-anywhere") or cc[-1] == "argo_anywhere")


# -- availability + default -------------------------------------------------

def test_available_macos_always_has_terminal() -> None:
    ids = [t["id"] for t in et.available_terminals("Darwin")]
    assert "terminal" in ids  # Terminal.app is always present on macOS


def test_available_linux_filters_by_which(monkeypatch) -> None:
    monkeypatch.setattr(et.shutil, "which", lambda b: "/usr/bin/xterm" if b == "xterm" else None)
    assert [t["id"] for t in et.available_terminals("Linux")] == ["xterm"]


def test_default_terminal_env_override(monkeypatch) -> None:
    monkeypatch.setenv("ARGO_ANYWHERE_TERMINAL", "iterm")
    monkeypatch.setattr(et, "_iterm_installed", lambda: True)
    assert et.default_terminal("Darwin") == "iterm"


def test_default_terminal_ignores_unavailable_env(monkeypatch) -> None:
    monkeypatch.setenv("ARGO_ANYWHERE_TERMINAL", "nope")
    assert et.default_terminal("Darwin") == "terminal"  # falls back to native default


# -- open_external_terminal (fake spawns) -----------------------------------

def test_open_macos_terminal_runs_osascript() -> None:
    calls = []

    def fake_run(args, **kw):
        calls.append(args)
        return object()

    res = open_external_terminal(
        ["argo-anywhere", "client"], terminal="terminal", system="Darwin", _run=fake_run
    )
    assert res["ok"] is True
    assert res["terminal_id"] == "terminal"
    assert calls[0][0] == "osascript"
    assert "client" in calls[0][2]


def test_open_linux_launches_emulator_detached(monkeypatch) -> None:
    monkeypatch.setattr(et.shutil, "which", lambda b: "/usr/bin/xterm" if b == "xterm" else None)
    calls = []
    res = open_external_terminal(
        ["argo-anywhere", "connect"], system="Linux", _popen=lambda args, **kw: calls.append(args)
    )
    assert res["ok"] is True and res["terminal_id"] == "xterm"
    assert calls[0][0] == "xterm" and "bash" in calls[0]


def test_open_unknown_terminal_rejected() -> None:
    res = open_external_terminal(["argo-anywhere", "client"], terminal="bogus", system="Darwin")
    assert res["ok"] is False and "not available" in res["error"]


def test_open_unsupported_os() -> None:
    res = open_external_terminal(["x"], system="Plan9")
    assert res["ok"] is False and "no supported terminal" in res["error"]


def test_open_reports_spawn_failure() -> None:
    def boom(*a, **k):
        raise OSError("nope")

    res = open_external_terminal(["x"], terminal="terminal", system="Darwin", _run=boom)
    assert res["ok"] is False and "nope" in res["error"]


# -- endpoints --------------------------------------------------------------

@pytest.fixture()
def client():
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    from argo_anywhere.web.app import create_app

    with TestClient(create_app(engine_argv=["connect"]), base_url="http://127.0.0.1") as c:
        yield c


def test_api_terminals_lists(client) -> None:
    body = client.get("/api/terminals").json()
    assert isinstance(body["terminals"], list)
    assert "default" in body


def test_api_launch_external_builds_console_command(client, monkeypatch) -> None:
    captured = {}

    def fake_open(argv, *, terminal=None, **kw):
        captured["argv"] = list(argv)
        captured["terminal"] = terminal
        return {"ok": True, "terminal": "Terminal.app", "terminal_id": "terminal",
                "command": " ".join(argv), "error": None}

    monkeypatch.setattr(et, "open_external_terminal", fake_open)
    r = client.post("/api/launch-external?verb=client&cli_tool=opencode&terminal=terminal")
    assert r.status_code == 200
    assert r.json()["ok"] is True
    # console prefix + validated engine argv, in order.
    assert captured["argv"][-3:] == ["client", "--cli-tool", "opencode"] or \
           captured["argv"][-3:] == ["--cli-tool", "opencode", "client"]
    assert "client" in captured["argv"] and "opencode" in captured["argv"]
    assert captured["terminal"] == "terminal"


def test_api_launch_external_bad_verb(client) -> None:
    assert client.post("/api/launch-external?verb=bogus").status_code == 400
