"""Unit tests for the persisted web-UI state (D-031 Task 5 + 5.5).

The state file at ``~/.argo_anywhere/web_state.json`` holds the launcher's MRU
cwd list, the panel divider position, and the theme choice. These tests use a
tmp-path override so they never touch the real file.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from argo_anywhere.web import state


@pytest.fixture()
def state_file(tmp_path: Path) -> Path:
    return tmp_path / "web_state.json"


# -- defaults + shape ------------------------------------------------------

def test_default_state_has_expected_shape() -> None:
    d = state.default_state()
    assert d["version"] == state.SCHEMA_VERSION
    assert d["mru"] == []
    assert d["divider_pct"] == 50
    assert d["theme"] == "auto"


def test_load_missing_file_returns_defaults(state_file: Path) -> None:
    assert not state_file.exists()
    assert state.load_state(state_file) == state.default_state()


def test_load_corrupt_json_returns_defaults(state_file: Path) -> None:
    state_file.write_text("{not-json")
    assert state.load_state(state_file) == state.default_state()


def test_load_wrong_version_returns_defaults(state_file: Path) -> None:
    state_file.write_text(json.dumps({"version": 999, "mru": []}))
    assert state.load_state(state_file) == state.default_state()


def test_load_non_dict_returns_defaults(state_file: Path) -> None:
    state_file.write_text(json.dumps(["a", "b"]))
    assert state.load_state(state_file) == state.default_state()


# -- round-trip + atomicity ------------------------------------------------

def test_save_and_reload_roundtrips(state_file: Path, tmp_path: Path) -> None:
    d = tmp_path / "existing-proj"
    d.mkdir()
    s = state.default_state()
    s["mru"] = [str(d)]
    s["divider_pct"] = 60
    s["theme"] = "light"
    state.save_state(s, state_file)
    reloaded = state.load_state(state_file)
    assert reloaded == s


def test_save_uses_atomic_replace_no_tempfile_left_behind(
    state_file: Path, tmp_path: Path
) -> None:
    state.save_state(state.default_state(), state_file)
    # Only the target file should exist -- no *.tmp sibling.
    others = [p for p in state_file.parent.iterdir() if p != state_file]
    assert others == []


def test_save_creates_parent_dir(tmp_path: Path) -> None:
    nested = tmp_path / "sub" / "web_state.json"
    state.save_state(state.default_state(), nested)
    assert nested.is_file()


# -- MRU -------------------------------------------------------------------

def test_touch_mru_prepends_new_entry(state_file: Path, tmp_path: Path) -> None:
    a = tmp_path / "a"
    a.mkdir()
    b = tmp_path / "b"
    b.mkdir()
    state.touch_mru(str(a), state_file)
    state.touch_mru(str(b), state_file)
    assert state.load_state(state_file)["mru"] == [str(b), str(a)]


def test_touch_mru_dedupes_existing_entry(state_file: Path, tmp_path: Path) -> None:
    a = tmp_path / "a"
    a.mkdir()
    b = tmp_path / "b"
    b.mkdir()
    state.touch_mru(str(a), state_file)
    state.touch_mru(str(b), state_file)
    state.touch_mru(str(a), state_file)
    # a moves back to the front; no duplicate.
    assert state.load_state(state_file)["mru"] == [str(a), str(b)]


def test_touch_mru_caps_at_ten(state_file: Path, tmp_path: Path) -> None:
    for i in range(12):
        p = tmp_path / f"proj{i}"
        p.mkdir()
        state.touch_mru(str(p), state_file)
    mru = state.load_state(state_file)["mru"]
    assert len(mru) == state.MRU_CAP
    # Most-recent entries survived; oldest were dropped.
    assert mru[0] == str(tmp_path / "proj11")
    assert str(tmp_path / "proj0") not in mru


def test_touch_mru_ignores_relative_path(state_file: Path) -> None:
    state.touch_mru("./nope", state_file)
    assert state.load_state(state_file)["mru"] == []


def test_load_prunes_vanished_paths(state_file: Path, tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    ghost = tmp_path / "ghost"  # never created
    state.save_state(
        {"version": state.SCHEMA_VERSION, "mru": [str(real), str(ghost)],
         "divider_pct": 50, "theme": "auto"},
        state_file,
    )
    mru = state.load_state(state_file)["mru"]
    assert mru == [str(real)]  # ghost pruned


# -- divider_pct clamp -----------------------------------------------------

def test_load_clamps_divider_below_min(state_file: Path) -> None:
    state_file.write_text(json.dumps({
        "version": state.SCHEMA_VERSION, "mru": [],
        "divider_pct": 5, "theme": "auto",
    }))
    assert state.load_state(state_file)["divider_pct"] == state.DIVIDER_MIN


def test_load_clamps_divider_above_max(state_file: Path) -> None:
    state_file.write_text(json.dumps({
        "version": state.SCHEMA_VERSION, "mru": [],
        "divider_pct": 99, "theme": "auto",
    }))
    assert state.load_state(state_file)["divider_pct"] == state.DIVIDER_MAX


def test_load_defaults_non_int_divider(state_file: Path) -> None:
    state_file.write_text(json.dumps({
        "version": state.SCHEMA_VERSION, "mru": [],
        "divider_pct": "half", "theme": "auto",
    }))
    assert state.load_state(state_file)["divider_pct"] == 50


# -- theme ----------------------------------------------------------------

@pytest.mark.parametrize("v", ["auto", "dark", "light"])
def test_load_accepts_known_themes(state_file: Path, v: str) -> None:
    state_file.write_text(json.dumps({
        "version": state.SCHEMA_VERSION, "mru": [],
        "divider_pct": 50, "theme": v,
    }))
    assert state.load_state(state_file)["theme"] == v


def test_load_defaults_unknown_theme(state_file: Path) -> None:
    state_file.write_text(json.dumps({
        "version": state.SCHEMA_VERSION, "mru": [],
        "divider_pct": 50, "theme": "bogus",
    }))
    assert state.load_state(state_file)["theme"] == "auto"


# -- update_state ---------------------------------------------------------

def test_update_state_merges_known_keys(state_file: Path) -> None:
    state.update_state({"divider_pct": 65}, state_file)
    assert state.load_state(state_file)["divider_pct"] == 65
    state.update_state({"theme": "light"}, state_file)
    d = state.load_state(state_file)
    assert d["theme"] == "light" and d["divider_pct"] == 65


def test_update_state_drops_unknown_keys(state_file: Path) -> None:
    state.update_state({"malicious": {"a": 1}}, state_file)
    reloaded = state.load_state(state_file)
    assert "malicious" not in reloaded
