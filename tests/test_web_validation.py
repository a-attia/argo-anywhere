"""Unit tests for launcher-cwd server-side validation (D-031 Task 3)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from argo_anywhere.web.validation import (
    STATUS_FOR_VERDICT,
    CwdVerdict,
    validate_cwd,
)


# -- happy path -----------------------------------------------------------

def test_validate_ok_for_existing_absolute_dir(tmp_path: Path) -> None:
    v = validate_cwd(str(tmp_path))
    assert v.verdict is CwdVerdict.OK
    assert v.resolved == tmp_path.resolve()
    assert v.ok is True


def test_expanduser_accepts_tilde(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    v = validate_cwd("~")
    assert v.verdict is CwdVerdict.OK
    assert v.resolved == fake_home.resolve()


def test_resolves_symlinks(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "link"
    link.symlink_to(target)
    v = validate_cwd(str(link))
    # Resolved path names the target, not the link.
    assert v.verdict is CwdVerdict.OK
    assert v.resolved == target.resolve()


# -- BAD_INPUT --------------------------------------------------------------

@pytest.mark.parametrize("blank", [None, "", "   ", "\t"])
def test_blank_is_bad_input(blank) -> None:
    v = validate_cwd(blank)
    assert v.verdict is CwdVerdict.BAD_INPUT
    assert "required" in v.detail
    assert v.resolved is None


def test_relative_path_rejected() -> None:
    v = validate_cwd("./relative")
    assert v.verdict is CwdVerdict.BAD_INPUT
    assert "absolute" in v.detail


def test_plain_name_rejected() -> None:
    v = validate_cwd("just-a-name")
    assert v.verdict is CwdVerdict.BAD_INPUT


# -- MISSING ---------------------------------------------------------------

def test_missing_path_returns_missing_verdict(tmp_path: Path) -> None:
    ghost = tmp_path / "does-not-exist"
    v = validate_cwd(str(ghost))
    assert v.verdict is CwdVerdict.MISSING
    assert v.resolved == ghost.resolve()


# -- NOT_DIRECTORY ---------------------------------------------------------

def test_file_rejected_as_not_directory(tmp_path: Path) -> None:
    f = tmp_path / "regular_file"
    f.write_text("hi")
    v = validate_cwd(str(f))
    assert v.verdict is CwdVerdict.NOT_DIRECTORY


# -- NOT_READABLE ----------------------------------------------------------

@pytest.mark.skipif(os.geteuid() == 0, reason="root bypasses permission bits")
def test_unreadable_directory_rejected(tmp_path: Path) -> None:
    locked = tmp_path / "locked"
    locked.mkdir()
    locked.chmod(0o000)
    try:
        v = validate_cwd(str(locked))
        # Depending on platform + test-user privilege, we get NOT_READABLE.
        assert v.verdict is CwdVerdict.NOT_READABLE
    finally:
        locked.chmod(0o700)  # restore so tmp_path cleanup can rm


# -- status-code mapping ---------------------------------------------------

def test_status_for_verdict_covers_all_verdicts() -> None:
    for v in CwdVerdict:
        assert v in STATUS_FOR_VERDICT
    assert STATUS_FOR_VERDICT[CwdVerdict.OK] == 200
    assert STATUS_FOR_VERDICT[CwdVerdict.BAD_INPUT] == 400
    assert STATUS_FOR_VERDICT[CwdVerdict.MISSING] == 409
    assert STATUS_FOR_VERDICT[CwdVerdict.NOT_DIRECTORY] == 400
    assert STATUS_FOR_VERDICT[CwdVerdict.NOT_READABLE] == 400
