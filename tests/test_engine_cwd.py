"""Engine ``--cwd`` flag smoke tests (D-031 Task 8).

Executes the vendored bash engine as a subprocess -- no ANL infra needed
because ``help`` is a no-side-effect verb. Verifies the flag parses, applies
the shared forbid-list under ``--scope project``, and cds before mode dispatch.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from argo_anywhere._engine import engine_path


def _run(argv: list[str], cwd: str | None = None) -> subprocess.CompletedProcess:
    with engine_path() as script:
        return subprocess.run(
            ["bash", str(script), *argv],
            capture_output=True, text=True, cwd=cwd, timeout=30,
        )


def test_cwd_flag_accepts_valid_absolute(tmp_path: Path) -> None:
    r = _run(["--cwd", str(tmp_path), "help"])
    assert r.returncode == 0
    assert "connect" in r.stdout


def test_cwd_flag_rejects_relative() -> None:
    r = _run(["--cwd", "relative/foo", "help"])
    assert r.returncode != 0
    assert "absolute" in r.stderr.lower()


def test_cwd_flag_rejects_missing(tmp_path: Path) -> None:
    ghost = tmp_path / "does-not-exist"
    r = _run(["--cwd", str(ghost), "help"])
    assert r.returncode != 0
    assert "does not exist" in r.stderr


def test_cwd_flag_hard_blocks_home_under_project_scope() -> None:
    home = os.path.expanduser("~")
    r = _run(["--cwd", home, "--scope", "project", "help"])
    assert r.returncode != 0
    assert "forbidden" in r.stderr


def test_cwd_flag_allows_home_under_global_scope() -> None:
    home = os.path.expanduser("~")
    r = _run(["--cwd", home, "--scope", "global", "help"])
    # help runs; --scope emits a warn for verbs that don't consume it but
    # doesn't fail the run.
    assert r.returncode == 0


@pytest.mark.parametrize("system_dir", ["/etc", "/tmp", "/var"])
def test_cwd_flag_hard_blocks_system_dirs_under_project_scope(system_dir: str) -> None:
    if not Path(system_dir).is_dir():
        pytest.skip(f"{system_dir} not present")
    r = _run(["--cwd", system_dir, "--scope", "project", "help"])
    assert r.returncode != 0
    assert "forbidden" in r.stderr


def test_cwd_flag_allows_project_dir_with_git(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    # `help` doesn't run any project logic but the --cwd + --scope project
    # combo should still succeed since the dir passes the forbid-list.
    r = _run(["--cwd", str(tmp_path), "--scope", "project", "help"])
    assert r.returncode == 0
