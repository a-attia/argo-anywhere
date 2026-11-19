"""Tests for the per-node data-dir invariant (argo-proxy's SQLite database).

Field report 2026-11-19: ``Failed to flush metrics: database is locked`` on one
compute node and ``... database disk image is malformed`` on another. argo-proxy
>= 3.3.0 keeps a WAL-mode SQLite database next to its config, and on CELS
``$HOME`` is one NFS mount shared by every node, so two nodes shared one SQLite
file. Design record: ``notes/impl_proxy_data_dir.md``.

The fix gives each launch a fresh per-node directory, keeps exactly one previous
generation, and passes it (plus lowered request-log caps) as env vars on every
launch line. This module pins:

* the rotation behaviour, driven through real ``bash`` against a sandbox HOME;
* that the helper never fails the launch, even when nothing on disk cooperates;
* that all three launchers actually deliver the env to the child process.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

from argo_anywhere._engine import engine_path


def _engine_source() -> str:
    with engine_path() as script:
        return script.read_text()


def _function_body(src: str, name: str) -> str:
    match = re.search(rf"^{re.escape(name)}\(\)\s*\{{.*?^\}}", src, re.MULTILINE | re.DOTALL)
    assert match, f"{name} definition not found in engine"
    return match.group(0)


def _run_prepare(
    tmp_path: Path, *, hostname: str = "compute-01.cels.anl.gov", pre: str = ""
) -> subprocess.CompletedProcess[str]:
    """Run the real ``_argoproxy_prepare_data_dir`` under ``set -euo pipefail``."""
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    stub = bindir / "hostname"
    stub.write_text(f"#!/bin/sh\nprintf '%s\\n' '{hostname}'\n")
    stub.chmod(0o755)

    script = tmp_path / "drive.sh"
    script.write_text(
        "set -euo pipefail\n"
        f'export HOME="{home}"\n'
        f'PATH="{bindir}:$PATH"\n'
        "log()  { printf 'LOG %s\\n' \"$*\"; }\n"
        "warn() { printf 'WARN %s\\n' \"$*\"; }\n"
        + _function_body(_engine_source(), "_argoproxy_prepare_data_dir")
        + "\n"
        + pre
        + "\n"
        "_argoproxy_prepare_data_dir\n"
        'echo "RC=$?"\n'
        'echo "DIR=${_ARGOPROXY_DATA_DIR}"\n'
    )
    return subprocess.run(["bash", str(script)], capture_output=True, text=True, timeout=30)


def _result(out: subprocess.CompletedProcess[str], key: str) -> str:
    for line in out.stdout.splitlines():
        if line.startswith(key + "="):
            return line.split("=", 1)[1]
    raise AssertionError(f"{key} not reported; stdout:\n{out.stdout}\nstderr:\n{out.stderr}")


# --------------------------------------------------------------------------
# Rotation behaviour
# --------------------------------------------------------------------------


def test_dir_is_per_node_and_uses_the_short_hostname(tmp_path: Path) -> None:
    out = _run_prepare(tmp_path)
    assert _result(out, "RC") == "0"
    d = Path(_result(out, "DIR"))
    assert d == tmp_path / "home/.config/argoproxy/data-compute-01"
    assert d.is_dir(), "current dir must exist before argo-proxy starts"


def test_rotation_keeps_exactly_one_previous_generation(tmp_path: Path) -> None:
    base = tmp_path / "home/.config/argoproxy"
    cur, prev = base / "data-compute-01", base / "data-compute-01.prev"

    _run_prepare(tmp_path)
    (cur / "gateway.db").write_text("session-1")

    _run_prepare(tmp_path)
    assert (prev / "gateway.db").read_text() == "session-1", "previous kept"
    assert list(cur.iterdir()) == [], "current is fresh"
    (cur / "gateway.db").write_text("session-2")

    _run_prepare(tmp_path)
    assert (prev / "gateway.db").read_text() == "session-2"
    assert list(cur.iterdir()) == []
    # session-1 is gone; nothing else accumulates.
    assert sorted(p.name for p in base.iterdir()) == [
        "data-compute-01",
        "data-compute-01.prev",
    ]


def test_two_nodes_never_share_a_directory(tmp_path: Path) -> None:
    a = Path(_result(_run_prepare(tmp_path, hostname="compute-01"), "DIR"))
    b = Path(_result(_run_prepare(tmp_path, hostname="compute-02"), "DIR"))
    assert a != b
    assert a.is_dir() and b.is_dir(), "one node's launch must not rotate the other's"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("node/../../etc", "data-node_"),  # no path escape
        ("", "data-unknown-host"),
        ("bad name$x.domain", "data-bad_name_x"),
    ],
)
def test_hostname_is_sanitized(tmp_path: Path, raw: str, expected: str) -> None:
    d = Path(_result(_run_prepare(tmp_path, hostname=raw), "DIR"))
    assert d.name == expected
    assert d.parent == tmp_path / "home/.config/argoproxy"


def test_legacy_shared_dir_is_reported_not_deleted(tmp_path: Path) -> None:
    legacy = tmp_path / "home/.config/argoproxy/data"
    legacy.mkdir(parents=True)
    (legacy / "gateway.db").write_text("maybe in use by another node")
    out = _run_prepare(tmp_path)
    assert (legacy / "gateway.db").exists(), (
        "launch must not delete the shared dir: another node's older proxy may "
        "have it open, and deleting under NFS gives that process ESTALE"
    )
    assert "old shared location" in out.stdout


# --------------------------------------------------------------------------
# Never fails the launch
# --------------------------------------------------------------------------


def test_never_fails_when_the_parent_is_read_only(tmp_path: Path) -> None:
    base = tmp_path / "home/.config/argoproxy"
    (base / "data-compute-01").mkdir(parents=True)
    (base / "data-compute-01.prev").mkdir()
    (base / "data-compute-01.prev" / "x").write_text("x")
    base.chmod(0o555)  # rename, delete and mkdir all fail
    try:
        out = _run_prepare(tmp_path)
    finally:
        base.chmod(0o755)
    assert out.returncode == 0, out.stderr
    assert _result(out, "RC") == "0"
    assert "WARN" in out.stdout, "failures must be reported, not swallowed"


def test_never_fails_when_hostname_is_missing(tmp_path: Path) -> None:
    out = _run_prepare(tmp_path, pre="hostname() { return 127; }")
    assert _result(out, "RC") == "0"
    assert Path(_result(out, "DIR")).name == "data-unknown-host"


# --------------------------------------------------------------------------
# Wiring into mode_server
# --------------------------------------------------------------------------


def test_mode_server_prepares_before_launching() -> None:
    body = _function_body(_engine_source(), "mode_server")
    prep = body.index("_argoproxy_prepare_data_dir")
    launch = body.index("screen -dmS")
    assert prep < launch
    assert not re.search(r"\$\(\s*_argoproxy_prepare_data_dir", body), (
        "must not be $()-captured: the subshell drops _ARGOPROXY_DATA_DIR (D-005)"
    )
    for var in ("DATA_DIR=", "REQUEST_LOG_SUCCESS_MAX=", "REQUEST_LOG_ERROR_MAX="):
        assert var in body, f"_ap_env must carry {var}"


def test_all_three_launchers_pass_the_env() -> None:
    body = _function_body(_engine_source(), "mode_server")
    screen = re.search(r"^\s*screen -dmS .*$", body, re.MULTILINE)
    tmux = re.search(r"^\s*_tmux_cmd=.*$", body, re.MULTILINE)
    nohup = re.search(r"^\s*nohup .*argo-proxy.*$", body, re.MULTILINE)
    assert screen and 'env "${_ap_env[@]}"' in screen.group(0)
    assert tmux and tmux.group(0).lstrip().startswith(
        '_tmux_cmd="env $(printf \'%q \' "${_ap_env[@]}")'
    )
    assert nohup and 'nohup env "${_ap_env[@]}"' in nohup.group(0)


def test_tmux_launch_delivers_env_to_the_child(tmp_path: Path) -> None:
    """Behavioural: the engine's own tmux command string, evaluated by a shell,
    hands DATA_DIR (with spaces) to the child. This is the launcher where the
    env would otherwise come from a pre-existing tmux server, not from us."""
    body = _function_body(_engine_source(), "mode_server")
    line = re.search(r"^\s*_tmux_cmd=.*$", body, re.MULTILINE).group(0).strip()
    fake = tmp_path / "fake proxy"
    fake.write_text('#!/bin/sh\necho "DATA_DIR=$DATA_DIR SUCC=$REQUEST_LOG_SUCCESS_MAX"\n')
    fake.chmod(0o755)
    log = tmp_path / "out.log"
    script = tmp_path / "drive.sh"
    script.write_text(
        "set -euo pipefail\n"
        f'venv_bin="{fake}"\n'
        f'_PROXY_LOG="{log}"\n'
        "PROXY_PORT=64742\n"
        f'_ap_env=("DATA_DIR={tmp_path}/a dir" "REQUEST_LOG_SUCCESS_MAX=1000")\n'
        + line.replace('"${venv}/bin/argo-proxy"', '"$venv_bin"')
        + "\n"
        'sh -c "$_tmux_cmd"\n'
    )
    subprocess.run(["bash", str(script)], check=True, timeout=30)
    assert log.read_text().strip() == f"DATA_DIR={tmp_path}/a dir SUCC=1000"


def test_clean_removes_the_data_dirs() -> None:
    src = _engine_source()
    assert 'for d in "$HOME/.config/argoproxy/data" "$HOME"/.config/argoproxy/data-*; do' in src
