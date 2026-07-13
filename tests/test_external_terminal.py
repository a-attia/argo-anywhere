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


# --- focus-follow-window (cross-platform, best effort) --------------------

def test_open_macos_cli_terminal_triggers_focus_raise(monkeypatch) -> None:
    """Regression 2026-07-13 (cross-platform focus): the AppleScript path
    activates inline; the CLI-Popen path must also trigger a follow-up
    focus push via System Events (macOS) so a launched alacritty / kitty /
    wezterm / ghostty window doesn't sit behind the browser."""
    calls: list[dict] = []

    def fake_popen(argv, **kw):
        class _P:
            pid = 4242
        return _P()

    def fake_run(argv, **kw):
        calls.append({"argv": list(argv), "kw": kw})
        class _R:
            returncode = 0
            stdout = ""
            stderr = ""
        return _R()

    # Use a real available CLI id; fake availability + fake osascript.
    monkeypatch.setattr(
        et, "available_terminals",
        lambda system=None: [{"id": "alacritty", "label": "Alacritty"}],
    )
    monkeypatch.setattr(et.shutil, "which", lambda name: "/usr/bin/" + name)
    # Skip the 120ms sleep in tests.
    monkeypatch.setattr(et, "_raise_focus_macos_cli",
                        lambda tid, **kw: calls.append({"focus": "macos-cli", "term_id": tid}))

    r = et.open_external_terminal(
        ["argo-anywhere", "run"],
        terminal="alacritty", system="Darwin",
        _run=fake_run, _popen=fake_popen,
    )
    assert r["ok"] is True
    # Focus raise must have been invoked with the term id.
    focus_calls = [c for c in calls if c.get("focus") == "macos-cli"]
    assert focus_calls == [{"focus": "macos-cli", "term_id": "alacritty"}]


def test_open_linux_cli_terminal_triggers_focus_raise(monkeypatch) -> None:
    """Same regression, Linux side: wmctrl invocation (best effort)."""
    called: dict = {}

    def fake_popen(argv, **kw):
        class _P:
            pid = 1234
        return _P()

    monkeypatch.setattr(
        et, "available_terminals",
        lambda system=None: [{"id": "gnome-terminal", "label": "GNOME Terminal"}],
    )
    monkeypatch.setattr(
        et, "_raise_focus_linux",
        lambda label, pid, **kw: called.update({"label": label, "pid": pid}),
    )

    r = et.open_external_terminal(
        ["argo-anywhere", "run"],
        terminal="gnome-terminal", system="Linux",
        _run=lambda *a, **k: None, _popen=fake_popen,
    )
    assert r["ok"] is True
    assert called == {"label": "GNOME Terminal", "pid": 1234}


def test_focus_raise_never_fails_the_launch(monkeypatch) -> None:
    """The focus push is best-effort; if the helper itself raises, the
    launch must still report success (users can Cmd-Tab manually)."""

    def fake_popen(argv, **kw):
        class _P:
            pid = 4242
        return _P()

    monkeypatch.setattr(
        et, "available_terminals",
        lambda system=None: [{"id": "kitty", "label": "kitty"}],
    )

    def boom(*a, **kw):
        raise RuntimeError("focus helper crashed unexpectedly")

    monkeypatch.setattr(et, "_raise_focus_macos_cli", boom)

    r = et.open_external_terminal(
        ["argo-anywhere", "run"],
        terminal="kitty", system="Darwin",
        _run=lambda *a, **k: None, _popen=fake_popen,
    )
    assert r["ok"] is True


def test_focus_raise_macos_cli_no_ops_for_unknown_term(monkeypatch) -> None:
    """Terminal ids without a mapped bundle name (shouldn't happen in
    practice but the CLI catalog + bundle-name catalog are separate maps)
    must silently no-op rather than firing a bogus AppleScript."""
    called = {"count": 0}

    def fake_run(argv, **kw):
        called["count"] += 1
        class _R:
            returncode = 0; stdout = ""; stderr = ""
        return _R()

    monkeypatch.setattr(et.shutil, "which", lambda name: "/usr/bin/" + name)
    et._raise_focus_macos_cli(
        "unknown-terminal-id", _run=fake_run, _sleep=lambda s: None,
    )
    assert called["count"] == 0


def test_focus_raise_linux_skips_on_wayland(monkeypatch) -> None:
    """Wayland's compositor enforces focus-stealing-prevention; wmctrl
    doesn't work there. The helper must skip cleanly rather than trying
    (and failing loudly)."""
    called = {"count": 0}

    monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")

    def fake_run(argv, **kw):
        called["count"] += 1
        class _R:
            returncode = 0
        return _R()

    monkeypatch.setattr(et.shutil, "which", lambda name: "/usr/bin/wmctrl")
    et._raise_focus_linux(
        "GNOME Terminal", 1234, _run=fake_run, _sleep=lambda s: None,
    )
    assert called["count"] == 0


def test_focus_raise_linux_skips_without_wmctrl(monkeypatch) -> None:
    called = {"count": 0}
    monkeypatch.setenv("XDG_SESSION_TYPE", "x11")

    def fake_run(argv, **kw):
        called["count"] += 1
        class _R:
            returncode = 0
        return _R()

    monkeypatch.setattr(et.shutil, "which", lambda name: None)
    et._raise_focus_linux(
        "GNOME Terminal", 1234, _run=fake_run, _sleep=lambda s: None,
    )
    assert called["count"] == 0


def test_focus_raise_linux_calls_wmctrl_when_available(monkeypatch) -> None:
    calls: list[list[str]] = []
    monkeypatch.setenv("XDG_SESSION_TYPE", "x11")
    monkeypatch.setattr(et.shutil, "which", lambda name: "/usr/bin/wmctrl")

    def fake_run(argv, **kw):
        calls.append(list(argv))
        class _R:
            returncode = 0
        return _R()

    et._raise_focus_linux(
        "GNOME Terminal", 1234, _run=fake_run, _sleep=lambda s: None,
    )
    assert len(calls) >= 1
    assert calls[0][:2] == ["wmctrl", "-a"]
    assert "GNOME Terminal" in calls[0]


def test_macos_scripts_activate_last_for_focus(regression_note: None = None) -> None:
    """Regression 2026-07-13: ``activate`` must be the LAST statement, else
    the browser (caller) re-takes focus by the time the script returns and
    the new terminal sits behind it. This test pins the order so a well-
    meaning refactor can't silently reintroduce the "opens behind" bug."""
    for term_id in ("terminal", "iterm"):
        s = macos_osa_script(term_id, "argo-anywhere client")
        # activate must appear; must be the LAST non-empty statement in the
        # tell-block (i.e. immediately before ``end tell``).
        assert "activate" in s
        lines = [ln.strip() for ln in s.splitlines() if ln.strip()]
        # Find the ``end tell`` line and check the one just before it.
        end_idx = next(i for i, ln in enumerate(lines) if ln == "end tell")
        assert lines[end_idx - 1] == "activate", (
            f"{term_id}: activate must be the LAST statement in the tell "
            f"block for focus to actually stick; got last-statement = "
            f"{lines[end_idx - 1]!r}"
        )


def test_cli_terminal_argv_shapes() -> None:
    assert cli_terminal_argv("xterm", "cmd") == ["xterm", "-e", "bash", "-lc", "cmd"]
    assert cli_terminal_argv("gnome-terminal", "cmd") == ["gnome-terminal", "--", "bash", "-lc", "cmd"]
    assert cli_terminal_argv("kitty", "cmd") == ["kitty", "bash", "-lc", "cmd"]


def test_console_command_is_invokable() -> None:
    cc = console_command()
    assert cc and (cc[0].endswith("argo-anywhere") or cc[-1] == "argo_anywhere")


# --- console_command() fallback ladder (regression 2026-07-13) ------------
# The dev-mode-under-a-foreign-interpreter case (server run via
# ``PYTHONPATH=src <different-python> -m argo_anywhere web`` where
# ``<different-python>`` has NO ``argo-anywhere`` script next to it and NO
# installed ``argo_anywhere`` module) previously fell through to
# ``<python> -m argo_anywhere`` and produced ``No module named
# argo_anywhere`` in the spawned terminal window. Each level of the
# fallback ladder now has its own test.

def _clear_all_argo_paths(monkeypatch, tmp_path):
    """Force every branch of console_command() to see nothing until we
    re-enable one of them from the test itself."""
    # Point sys.executable at a fresh Python-lookalike that has NO sibling
    # ``argo-anywhere`` script.
    fake_python = tmp_path / "bin" / "python"
    fake_python.parent.mkdir(parents=True)
    fake_python.write_text("#!/bin/sh\nexec /usr/bin/env python \"$@\"\n")
    fake_python.chmod(0o755)
    monkeypatch.setattr(et.sys, "executable", str(fake_python))
    # Empty PATH so shutil.which("argo-anywhere") returns None.
    monkeypatch.setenv("PATH", "")
    # Pretend the module isn't importable either.
    monkeypatch.setattr(et.importlib.util, "find_spec", lambda name: None)


def test_console_command_prefers_sibling_script(monkeypatch, tmp_path) -> None:
    _clear_all_argo_paths(monkeypatch, tmp_path)
    # Now DROP an ``argo-anywhere`` next to the fake python.
    script = tmp_path / "bin" / "argo-anywhere"
    script.write_text("#!/bin/sh\necho hi\n"); script.chmod(0o755)
    assert console_command() == [str(script)]


def test_console_command_prefers_path_over_dash_m(
    monkeypatch, tmp_path
) -> None:
    """After no sibling script, PATH wins over ``-m``: the spawned shell
    doesn't inherit PYTHONPATH, so a PATH-based invocation is what actually
    survives to the new terminal (regression 2026-07-13). Both branches
    need to be available for this test to be meaningful."""
    _clear_all_argo_paths(monkeypatch, tmp_path)
    # Make BOTH the -m form and a PATH argo-anywhere available.
    monkeypatch.setattr(
        et.importlib.util, "find_spec",
        lambda name: object() if name == "argo_anywhere" else None,
    )
    other = tmp_path / "elsewhere" / "argo-anywhere"
    other.parent.mkdir()
    other.write_text("#!/bin/sh\necho hi\n"); other.chmod(0o755)
    monkeypatch.setenv("PATH", str(other.parent))
    # PATH wins.
    assert console_command() == [str(other)]


def test_console_command_falls_back_to_dash_m_last(
    monkeypatch, tmp_path
) -> None:
    """The ``-m`` form is the last resort, only when there's no sibling
    script AND no argo-anywhere on PATH."""
    _clear_all_argo_paths(monkeypatch, tmp_path)
    # Make the -m form the only available option.
    monkeypatch.setattr(
        et.importlib.util, "find_spec",
        lambda name: object() if name == "argo_anywhere" else None,
    )
    cc = console_command()
    assert cc[-2:] == ["-m", "argo_anywhere"]
    assert cc[0].endswith("python")


def test_console_command_returns_empty_when_nothing_usable(
    monkeypatch, tmp_path
) -> None:
    """The bug: server under miniconda's python with no ``argo-anywhere``
    installed there. Previously returned ``[<miniconda-python>, '-m',
    'argo_anywhere']`` which failed in the spawned terminal. Now returns
    [] so callers can refuse cleanly."""
    _clear_all_argo_paths(monkeypatch, tmp_path)
    assert console_command() == []


# --- console_command_verified() (defense-in-depth probe) -----------------

def test_console_command_verified_returns_prefix_on_success(
    monkeypatch, tmp_path
) -> None:
    """Happy path: the chosen prefix runs successfully under a scrubbed env."""
    _clear_all_argo_paths(monkeypatch, tmp_path)
    # Provide a fake argo-anywhere script that prints its version + exits 0.
    fake = tmp_path / "bin" / "argo-anywhere"
    fake.write_text("#!/bin/sh\necho 'argo-anywhere fake 0.0.0'\n"); fake.chmod(0o755)
    prefix, err = et.console_command_verified()
    assert err is None
    assert prefix == [str(fake)]


def test_console_command_verified_reports_failure_when_prefix_broken(
    monkeypatch, tmp_path
) -> None:
    """Regression 2026-07-13: if the prefix would fail in the spawned
    shell (e.g. ``-m argo_anywhere`` under an interpreter that only sees
    the module via PYTHONPATH), the probe catches it here so we refuse
    cleanly instead of shipping a broken command."""
    _clear_all_argo_paths(monkeypatch, tmp_path)
    # Provide a fake argo-anywhere script that always errors out.
    fake = tmp_path / "bin" / "argo-anywhere"
    fake.write_text(
        "#!/bin/sh\necho 'No module named argo_anywhere' >&2\nexit 1\n"
    )
    fake.chmod(0o755)
    prefix, err = et.console_command_verified()
    assert prefix == []
    assert err is not None
    assert "No module named argo_anywhere" in err


def test_console_command_verified_reports_when_no_prefix_at_all(
    monkeypatch, tmp_path
) -> None:
    _clear_all_argo_paths(monkeypatch, tmp_path)
    prefix, err = et.console_command_verified()
    assert prefix == []
    assert err == "no argo-anywhere CLI found for this environment"


def test_console_command_verified_scrubs_pythonpath(
    monkeypatch, tmp_path
) -> None:
    """The probe must run WITHOUT our PYTHONPATH so it emulates what a
    fresh login shell would see. Otherwise a ``python -m argo_anywhere``
    prefix that only works with our env leaks would probe green + still
    fail in the spawned terminal."""
    _clear_all_argo_paths(monkeypatch, tmp_path)
    monkeypatch.setenv("PYTHONPATH", "/some/dev/src")
    # A fake that FAILS iff PYTHONPATH is set (leaks would let it through).
    fake = tmp_path / "bin" / "argo-anywhere"
    fake.write_text(
        '#!/bin/sh\n'
        'if [ -n "$PYTHONPATH" ]; then echo "PYTHONPATH leaked" >&2; exit 1; fi\n'
        'echo ok\n'
    )
    fake.chmod(0o755)
    prefix, err = et.console_command_verified()
    assert err is None, f"probe env not scrubbed: {err}"
    assert prefix == [str(fake)]


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


def test_api_launch_external_refuses_when_console_command_unavailable(
    client, monkeypatch
) -> None:
    """Regression 2026-07-13: if the console-command probe fails (either no
    prefix found OR the found prefix doesn't actually run under a scrubbed
    env), the endpoint must refuse cleanly (500 with a diagnostic) rather
    than shipping a broken command to a fresh terminal window the user
    can't inspect."""
    monkeypatch.setattr(
        et, "console_command_verified",
        lambda **kw: ([], "no argo-anywhere CLI found for this environment"),
    )
    r = client.post("/api/launch-external?verb=connect&terminal=terminal")
    assert r.status_code == 500
    body = r.json()
    assert body["ok"] is False
    assert "argo-anywhere" in body["error"]
    # Diagnostic must name at least one recovery path.
    assert "pipx install argo-anywhere" in body["error"] or "PATH" in body["error"]


def test_api_launch_external_refuses_when_probe_fails(
    client, monkeypatch
) -> None:
    """Second regression 2026-07-13: even when console_command() returns a
    non-empty prefix, verification runs it with a scrubbed env; if the
    ``<prefix> --version`` probe fails (e.g. because the prefix would only
    have worked with our PYTHONPATH), we refuse HERE rather than in a
    terminal window."""
    monkeypatch.setattr(
        et, "console_command_verified",
        lambda **kw: (
            [],
            "python -m argo_anywhere --version failed: No module named argo_anywhere",
        ),
    )
    r = client.post("/api/launch-external?verb=connect&terminal=terminal")
    assert r.status_code == 500
    body = r.json()
    assert "No module named argo_anywhere" in body["error"]
