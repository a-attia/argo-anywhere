"""Unit tests for the scope-conditional forbid-list (D-031 Task 7).

The forbid-list is checked only when scope == "project" (D6a). Global scope is
unrestricted so beginners running from ``$HOME`` take the happy path.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from argo_anywhere.web.forbid import (
    HARD_BLOCK_ROOTS,
    ForbidResult,
    Verdict,
    check,
)


# -- global scope is unrestricted ----------------------------------------

@pytest.mark.parametrize("scope", ["global", "", None, "auto"])
def test_non_project_scope_always_allows(scope, tmp_path: Path) -> None:
    r = check(str(tmp_path), scope)
    assert r.verdict is Verdict.ALLOW
    assert r.ok is True


# -- hard-block roots -----------------------------------------------------

def test_root_is_hard_blocked() -> None:
    r = check("/", "project")
    assert r.verdict is Verdict.HARD_BLOCK
    assert r.ok is False
    assert r.blocking is True


@pytest.mark.parametrize("root", ["/etc", "/usr", "/tmp", "/opt", "/var"])
def test_system_dirs_hard_blocked(root: str) -> None:
    if not Path(root).is_dir():
        pytest.skip(f"{root} does not exist on this system")
    r = check(root, "project")
    assert r.verdict is Verdict.HARD_BLOCK


def test_subdir_of_hard_block_is_not_hard_blocked(tmp_path: Path) -> None:
    # /tmp/foo is allowed (subject to soft-warn if it has no markers); only
    # /tmp itself is hard-blocked. Use tmp_path (a subdir of /tmp on Linux
    # or /var/folders on macOS) as a stand-in.
    r = check(str(tmp_path), "project")
    assert r.verdict is not Verdict.HARD_BLOCK


def test_home_exact_is_hard_blocked(monkeypatch, tmp_path: Path) -> None:
    fake_home = tmp_path / "home"; fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    r = check(str(fake_home), "project")
    assert r.verdict is Verdict.HARD_BLOCK
    assert "$HOME" in r.reason or "home" in r.reason.lower()


def test_home_subdir_is_not_hard_blocked(monkeypatch, tmp_path: Path) -> None:
    fake_home = tmp_path / "home"; fake_home.mkdir()
    proj = fake_home / "projects" / "x"; proj.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(fake_home))
    r = check(str(proj), "project")
    assert r.verdict is not Verdict.HARD_BLOCK


# -- soft-warn: no markers -------------------------------------------------

def test_bare_dir_gets_soft_warn(tmp_path: Path) -> None:
    r = check(str(tmp_path), "project")
    assert r.verdict is Verdict.SOFT_WARN
    assert "marker" in r.reason or "project" in r.reason


def test_dot_git_suppresses_soft_warn(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    r = check(str(tmp_path), "project")
    assert r.verdict is Verdict.ALLOW


@pytest.mark.parametrize("marker", [
    "pyproject.toml", "package.json", "Cargo.toml", "Makefile", "go.mod",
])
def test_project_marker_files_suppress_soft_warn(tmp_path: Path, marker: str) -> None:
    (tmp_path / marker).write_text("")
    r = check(str(tmp_path), "project")
    assert r.verdict is Verdict.ALLOW


def test_existing_tool_config_suppresses_soft_warn(tmp_path: Path) -> None:
    (tmp_path / "opencode.json").write_text("{}")
    r = check(str(tmp_path), "project")
    assert r.verdict is Verdict.ALLOW


def test_dot_claude_dir_suppresses_soft_warn(tmp_path: Path) -> None:
    (tmp_path / ".claude").mkdir()
    r = check(str(tmp_path), "project")
    assert r.verdict is Verdict.ALLOW


# -- symlink resolution ---------------------------------------------------

def test_symlink_to_home_is_still_hard_blocked(monkeypatch, tmp_path: Path) -> None:
    fake_home = tmp_path / "home"; fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    link = tmp_path / "link-to-home"
    link.symlink_to(fake_home)
    r = check(str(link), "project")
    assert r.verdict is Verdict.HARD_BLOCK
