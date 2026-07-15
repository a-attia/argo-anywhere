"""Tests for the D-032 resolved-launch preview (2026-07-15).

Covers:

* :mod:`argo_anywhere.web.preview` unit tests (SshGResult parser +
  ``reflect_jump_args`` mirror + ``run_ssh_G`` timeout/failure paths).
* Byte-equivalent-mirror test: ``reflect_jump_args`` produces the same
  argv fragment the engine's ``ssh_jump_args`` would emit, verified via
  the same stub-ssh fixture used in tests/test_engine_ssh_config.py.
* Endpoint tests for ``/api/preview-launch`` (state=cached/empty/
  partial/unresolved/resolved; divergence detection; server-side field
  validation rejects shell-hostile chars).

The mirror test is the load-bearing coupling check per plan §7 W9 +
AGENTS.md D-032 coupling subsection: any change to the engine's
``ssh_jump_args`` must land with a matching change to
``reflect_jump_args`` in the same commit.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import textwrap
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from argo_anywhere._engine import engine_path  # noqa: E402
from argo_anywhere.web.app import create_app  # noqa: E402
from argo_anywhere.web.preview import (  # noqa: E402
    DEFAULT_ANL_JUMP,
    SshGResult,
    _parse_ssh_G,
    reflect_jump_args,
    run_ssh_G,
)


# ===========================================================================
# Unit tests: SshGResult + _parse_ssh_G + reflect_jump_args.
# ===========================================================================


def test_sshgresult_has_own_proxy_via_proxyjump() -> None:
    r = SshGResult(proxyjump="user@host")
    assert r.has_own_proxy


def test_sshgresult_has_own_proxy_via_proxycommand() -> None:
    r = SshGResult(proxycommand="/usr/bin/nc %h %p")
    assert r.has_own_proxy


def test_sshgresult_no_proxy_when_none_sentinel() -> None:
    """`ProxyJump none` and `ProxyCommand none` are OpenSSH sentinels for
    "no proxy" -- must NOT be treated as a real proxy."""
    r = SshGResult(proxyjump="none", proxycommand="none")
    assert not r.has_own_proxy


def test_sshgresult_no_proxy_when_absent() -> None:
    r = SshGResult()  # all empty
    assert not r.has_own_proxy


def test_parse_ssh_G_basic() -> None:
    raw = textwrap.dedent("""\
        hostname compute-01.cels.anl.gov
        user example-user
        port 22
        proxyjump example-user@logins.cels.anl.gov
    """)
    r = _parse_ssh_G(raw)
    assert r.hostname == "compute-01.cels.anl.gov"
    assert r.user == "example-user"
    assert r.proxyjump == "example-user@logins.cels.anl.gov"
    assert r.proxycommand == ""


def test_parse_ssh_G_ignores_unknown_keys() -> None:
    """Real ssh -G output has ~50 keys; parser picks only the four we care
    about and silently ignores the rest."""
    raw = textwrap.dedent("""\
        hostname foo
        user bar
        connecttimeout 10
        serveraliveinterval 60
        stricthostkeychecking accept-new
    """)
    r = _parse_ssh_G(raw)
    assert r.hostname == "foo"
    assert r.user == "bar"
    assert r.proxyjump == ""


def test_parse_ssh_G_handles_empty_input() -> None:
    r = _parse_ssh_G("")
    assert r == SshGResult()


def test_parse_ssh_G_first_value_wins() -> None:
    """If the same key appears twice (rare; e.g. from Include), the FIRST
    value wins -- matches ssh -G's own precedence rule."""
    raw = "user first\nuser second\n"
    assert _parse_ssh_G(raw).user == "first"


# ---------------------------------------------------------------------------
# reflect_jump_args: the mirror function.
# ---------------------------------------------------------------------------


def test_reflect_no_jump_returns_empty() -> None:
    """--no-jump wins over everything else."""
    r = SshGResult(proxyjump="example@logins.cels.anl.gov")
    assert reflect_jump_args(
        "example", "polaris-login",
        anl_jump=DEFAULT_ANL_JUMP, no_jump=True, ssh_g_result=r,
    ) == []


def test_reflect_target_is_jump_host_returns_empty() -> None:
    """Loop guard: never add -J when the target IS the jump host."""
    assert reflect_jump_args(
        "example", DEFAULT_ANL_JUMP,
        anl_jump=DEFAULT_ANL_JUMP, no_jump=False, ssh_g_result=None,
    ) == []


def test_reflect_alias_has_own_proxy_returns_empty() -> None:
    """Sub-fix C: alias has its own ProxyJump -> skip ours."""
    r = SshGResult(proxyjump="example@logins.cels.anl.gov")
    assert reflect_jump_args(
        "example", "polaris-login",
        anl_jump=DEFAULT_ANL_JUMP, no_jump=False, ssh_g_result=r,
    ) == []


def test_reflect_bare_hostname_adds_j() -> None:
    """No ssh_config alias, no proxy -> normal -J behavior."""
    argv = reflect_jump_args(
        "example", "compute-02.cels.anl.gov",
        anl_jump=DEFAULT_ANL_JUMP, no_jump=False, ssh_g_result=None,
    )
    assert argv == ["-J", "example@logins.cels.anl.gov"]


def test_reflect_none_sentinel_still_adds_j() -> None:
    """Alias with `ProxyJump none` sentinel -> we ADD our -J (the alias
    said "no proxy," so we own the routing)."""
    r = SshGResult(proxyjump="none")
    argv = reflect_jump_args(
        "example", "some-alias",
        anl_jump=DEFAULT_ANL_JUMP, no_jump=False, ssh_g_result=r,
    )
    assert argv == ["-J", "example@logins.cels.anl.gov"]


def test_reflect_custom_anl_jump() -> None:
    """--jump-host override propagates: our -J uses the custom host."""
    argv = reflect_jump_args(
        "example", "compute-02.cels.anl.gov",
        anl_jump="bastion.example.com", no_jump=False, ssh_g_result=None,
    )
    assert argv == ["-J", "example@bastion.example.com"]


# ---------------------------------------------------------------------------
# run_ssh_G: real subprocess integration + timeout / failure paths.
# ---------------------------------------------------------------------------


def test_run_ssh_G_returns_none_on_empty_input() -> None:
    assert run_ssh_G("") is None


def test_run_ssh_G_returns_none_on_bad_input() -> None:
    """Anything the SAFE_HOSTLIKE regex rejects returns None (no
    subprocess spawn)."""
    for bad in ("user@host", "path/to", "with space", "$USER", "x" * 300):
        assert run_ssh_G(bad) is None


def test_run_ssh_G_returns_none_on_timeout(monkeypatch) -> None:
    def raise_timeout(*a, **kw):
        raise subprocess.TimeoutExpired(cmd="ssh", timeout=2.0)

    monkeypatch.setattr(subprocess, "run", raise_timeout)
    assert run_ssh_G("polaris-login") is None


def test_run_ssh_G_returns_none_on_nonzero_exit(monkeypatch) -> None:
    class FakeProc:
        returncode = 1
        stdout = ""
        stderr = "some error"

    def fake_run(*a, **kw):
        return FakeProc()

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert run_ssh_G("polaris-login") is None


def test_run_ssh_G_parses_stdout_on_success(monkeypatch) -> None:
    class FakeProc:
        returncode = 0
        stdout = "hostname foo\nuser example\n"
        stderr = ""

    def fake_run(*a, **kw):
        return FakeProc()

    monkeypatch.setattr(subprocess, "run", fake_run)
    r = run_ssh_G("polaris-login")
    assert r is not None
    assert r.hostname == "foo"
    assert r.user == "example"


# ===========================================================================
# Byte-equivalent-mirror test (the coupling contract per §7 W9).
#
# Uses the same ssh-shim pattern from tests/test_engine_ssh_config.py:
# install a fake `ssh` in a scratch PATH; call the engine's ssh_jump_args
# and Python's reflect_jump_args on the same inputs; assert equal output.
# ===========================================================================


def _write_ssh_G_shim(shim_dir: Path, ssh_g_output: dict[str, str]) -> str:
    """Copy of the fixture from tests/test_engine_ssh_config.py; kept local
    here so this file is independently readable + rerunnable."""
    shim_dir.mkdir(parents=True, exist_ok=True)
    real_ssh = shutil.which("ssh") or ""
    cases = []
    for alias, response in ssh_g_output.items():
        escaped = response.replace("'", "'\\''")
        cases.append(f"    {alias}) printf '%s' '{escaped}'; exit 0 ;;")
    cases_block = "\n".join(cases) if cases else "    # (no aliases)"
    shim = shim_dir / "ssh"
    shim.write_text(textwrap.dedent(f"""\
        #!/bin/bash
        if [ "${{1:-}}" = "-G" ] && [ -n "${{2:-}}" ]; then
          alias="$2"
          case "$alias" in
{cases_block}
            *) exit 0 ;;
          esac
        fi
        exec {real_ssh} "$@"
        """))
    shim.chmod(0o755)
    essentials_bin = shim_dir / "_essentials"
    essentials_bin.mkdir(exist_ok=True)
    for tool in ("tr", "awk", "cp", "diff", "wc", "mktemp", "cat", "printf",
                 "date", "grep", "sed", "head", "tail", "sort", "uniq", "env",
                 "basename", "dirname", "mkdir", "rm", "chmod", "ln", "touch",
                 "which", "bash", "sh", "cmp", "python3", "python", "id",
                 "hostname"):
        for p in os.environ.get("PATH", "").split(":"):
            cand = os.path.join(p, tool)
            if os.path.isfile(cand) and os.access(cand, os.X_OK):
                try:
                    (essentials_bin / tool).symlink_to(cand)
                except FileExistsError:
                    pass
                break
    return f"{shim_dir}:{essentials_bin}"


def _source_engine_and_run(bash_snippet: str, env: dict) -> tuple[int, str, str]:
    """Source the engine (without main), then run bash_snippet."""
    with engine_path() as script:
        body = script.read_text()
        body_no_main = body.rstrip()[: -len('main "$@"')]
        wrapper = body_no_main + "\n" + bash_snippet + "\n"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".sh", delete=False) as tf:
            tf.write(wrapper)
            path = tf.name
        try:
            r = subprocess.run(
                ["bash", path],
                capture_output=True, text=True, timeout=15, env=env,
            )
        finally:
            os.unlink(path)
    return r.returncode, r.stdout, r.stderr


@pytest.mark.parametrize("scenario", [
    # (alias, ssh_g_output_for_alias, user, no_jump_env)
    (
        "polaris-login",
        "hostname compute-01.cels.anl.gov\nuser example\nproxyjump example@logins.cels.anl.gov\n",
        "another-user",
        False,
    ),
    (
        "plain-node",
        "hostname plain-node\nuser example\nproxycommand none\n",
        "example",
        False,
    ),
    (
        "polaris-login",
        "hostname compute-01.cels.anl.gov\nuser example\nproxyjump example@logins.cels.anl.gov\n",
        "another-user",
        True,   # --no-jump
    ),
])
def test_reflect_jump_args_matches_engine(tmp_path: Path, scenario) -> None:
    """Byte-equivalent-mirror test per §7 W9 coupling contract.

    Sets up the same ssh-shim + engine environment, then computes the
    jump-args two ways: (a) via the engine's real ssh_jump_args, and
    (b) via Python's reflect_jump_args on the parsed ssh -G output.
    Assert the two produce the same argv string.
    """
    alias, ssh_g_output, user, no_jump = scenario
    shim_dir = tmp_path / "bin"
    env = os.environ.copy()
    env["PATH"] = _write_ssh_G_shim(shim_dir, {alias: ssh_g_output})
    if no_jump:
        env["ARGO_ANYWHERE_NO_JUMP"] = "1"

    # (a) engine's ssh_jump_args.
    snippet = f"""
result="$(ssh_jump_args {user} {alias})"
printf '%s' "$result"
"""
    rc, engine_out, _err = _source_engine_and_run(snippet, env)
    assert rc == 0
    engine_argv = engine_out.split()  # split on whitespace; joins -J and user@host

    # (b) Python's reflect_jump_args on the same ssh -G output.
    parsed = _parse_ssh_G(ssh_g_output)
    py_argv = reflect_jump_args(
        user, alias,
        anl_jump=DEFAULT_ANL_JUMP,
        no_jump=no_jump,
        ssh_g_result=parsed,
    )

    assert py_argv == engine_argv, (
        f"engine and Python-mirror disagree for scenario {scenario}:\n"
        f"  engine says: {engine_argv!r}\n"
        f"  Python says: {py_argv!r}\n"
        "This is a violation of the D-032 coupling contract (§7 W9). "
        "Either the engine's ssh_jump_args or the Python reflect_jump_args "
        "changed without the other."
    )


# ===========================================================================
# Endpoint tests: /api/preview-launch.
# ===========================================================================


@pytest.fixture()
def client() -> TestClient:
    app = create_app(engine_argv=["connect"])
    with TestClient(app, base_url="http://127.0.0.1") as c:
        yield c


def test_api_preview_state_empty(client: TestClient, tmp_path: Path, monkeypatch) -> None:
    """All inputs blank AND no caches -> state=empty."""
    # Isolate cache dir so we don't accidentally pick up the tester's cache.
    monkeypatch.setattr(
        "argo_anywhere.status.STATE_DIR",
        tmp_path / "empty-state",
    )
    r = client.post("/api/preview-launch", json={})
    assert r.status_code == 200
    assert r.json()["state"] == "empty"


def test_api_preview_state_cached(client: TestClient, tmp_path: Path, monkeypatch) -> None:
    """Blank inputs + populated cache -> state=cached with the cached values."""
    fake_state = tmp_path / "argo_state"
    fake_state.mkdir()
    (fake_state / "node").write_text("polaris-login\n")
    (fake_state / "user").write_text("example-user\n")
    monkeypatch.setattr("argo_anywhere.status.STATE_DIR", fake_state)

    r = client.post("/api/preview-launch", json={})
    assert r.status_code == 200
    body = r.json()
    assert body["state"] == "cached"
    assert body["hostname"]["value"] == "polaris-login"
    assert body["hostname"]["source"] == "cache"
    assert body["user"]["value"] == "example-user"
    assert body["proxyjump"]["value"] == DEFAULT_ANL_JUMP


def test_api_preview_state_partial(client: TestClient) -> None:
    """User typed but no node -> state=partial."""
    r = client.post("/api/preview-launch", json={"user": "example"})
    assert r.status_code == 200
    body = r.json()
    assert body["state"] == "partial"
    assert body["user"]["value"] == "example"


def test_api_preview_state_unresolved(client: TestClient, monkeypatch) -> None:
    """Node given but ssh -G fails -> state=unresolved. NO stderr leaks
    into the response (per §7 W3)."""
    # Force ssh -G to return non-zero.
    def fake_run_ssh_G(alias, timeout=2.0):
        return None

    monkeypatch.setattr("argo_anywhere.web.preview.run_ssh_G", fake_run_ssh_G)
    monkeypatch.setattr("argo_anywhere.web.app.run_ssh_G", fake_run_ssh_G, raising=False)
    # Patch inside the endpoint's local import scope too:
    import argo_anywhere.web.preview as prev
    monkeypatch.setattr(prev, "run_ssh_G", fake_run_ssh_G)

    r = client.post("/api/preview-launch", json={"node": "no-such-alias"})
    assert r.status_code == 200
    body = r.json()
    assert body["state"] == "unresolved"
    # Response should not contain stderr text.
    assert "error" not in body or not body.get("error")


def test_api_preview_state_resolved(client: TestClient, monkeypatch) -> None:
    """Node resolves cleanly -> state=resolved with parsed values."""
    def fake_run_ssh_G(alias, timeout=2.0):
        return SshGResult(
            hostname="compute-01.cels.anl.gov",
            user="example",
            proxyjump="example@logins.cels.anl.gov",
        )

    import argo_anywhere.web.preview as prev
    monkeypatch.setattr(prev, "run_ssh_G", fake_run_ssh_G)

    r = client.post("/api/preview-launch", json={"node": "polaris-login"})
    assert r.status_code == 200
    body = r.json()
    assert body["state"] == "resolved"
    assert body["hostname"] == "compute-01.cels.anl.gov"
    assert body["user"] == "example"
    assert body["proxyjump"] == "example@logins.cels.anl.gov"
    # Alias has its own ProxyJump -> our extras should be empty.
    assert body["our_extra_jump_args"] == []
    assert body["divergences"] == []


def test_api_preview_divergence_detected(client: TestClient, monkeypatch) -> None:
    """User's explicit --user differs from ssh_config -> divergences array."""
    def fake_run_ssh_G(alias, timeout=2.0):
        return SshGResult(
            hostname="compute-01.cels.anl.gov",
            user="example-1",
            proxyjump="example-1@logins.cels.anl.gov",
        )

    import argo_anywhere.web.preview as prev
    monkeypatch.setattr(prev, "run_ssh_G", fake_run_ssh_G)

    r = client.post("/api/preview-launch", json={
        "node": "polaris-login",
        "user": "example-2",   # explicit; different from ssh_config
    })
    assert r.status_code == 200
    body = r.json()
    assert body["state"] == "resolved"
    divs = body["divergences"]
    assert len(divs) == 1
    assert divs[0]["field"] == "user"
    assert divs[0]["yours"] == "example-2"
    assert divs[0]["ssh_config"] == "example-1"


@pytest.mark.parametrize("bad_field,bad_value", [
    ("node", "user@host"),
    ("node", "with space"),
    ("node", "$injection"),
    ("user", "user@host"),
    ("jump_host", "host:22"),
])
def test_api_preview_rejects_bad_input(
    client: TestClient, bad_field: str, bad_value: str,
) -> None:
    """Server-side validation rejects shell-hostile chars with 400
    (per §7 C6 audit: defense in depth even though subprocess.run with
    a list is injection-safe)."""
    body = {"node": "polaris-login"}  # start with a valid baseline
    body[bad_field] = bad_value
    r = client.post("/api/preview-launch", json=body)
    assert r.status_code == 400
    assert bad_field in r.json()["error"]


def test_api_preview_host_guard(client: TestClient) -> None:
    """Endpoint honors the app-wide loopback host guard."""
    r = client.post(
        "/api/preview-launch",
        json={},
        headers={"host": "evil.example.com"},
    )
    assert r.status_code == 403


def test_api_preview_ssh_never_authenticates(client: TestClient, monkeypatch) -> None:
    """Contract test per §7 C5: the endpoint's subprocess call MUST use
    argv-list form (never shell=True). Otherwise a malicious 'node'
    input could inject shell metachars.

    Verified via monkeypatching subprocess.run and asserting the call
    signature at invocation time.
    """
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs

        class FakeResult:
            returncode = 0
            stdout = "hostname foo\nuser example\n"
            stderr = ""
        return FakeResult()

    monkeypatch.setattr(subprocess, "run", fake_run)

    client.post("/api/preview-launch", json={"node": "polaris-login"})
    # subprocess.run was called with a LIST (not a string) -- shell=False
    # by default and no shell=True override.
    assert isinstance(captured["cmd"], list), (
        f"expected subprocess.run to receive a list argv; got: {captured['cmd']!r}"
    )
    assert captured["cmd"][0] == "ssh"
    assert captured["cmd"][1] == "-G"
    assert captured["kwargs"].get("shell", False) is False, (
        "subprocess.run MUST NOT use shell=True -- would enable injection"
    )
    # Also verify the 2s timeout is set (per §10.4 security note about
    # user-config Match exec blocks).
    assert captured["kwargs"].get("timeout", 0) <= 2.0, (
        f"expected timeout <= 2.0s; got {captured['kwargs'].get('timeout')!r}"
    )
