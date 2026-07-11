"""D-030b: the on-disk footprint ledger + its `argo-anywhere info` surface.

All local: the footprint scan is scoped to a ``home`` param, so these tests use
a tmp dir as home and never touch the real machine (no ANL/SSH/network).
"""

from __future__ import annotations

import json
from pathlib import Path

from argo_anywhere import cli
from argo_anywhere.footprint import FootprintEntry, footprint, format_size


def test_empty_home_yields_nothing(tmp_path: Path) -> None:
    assert footprint(home=tmp_path) == []


def _tiers(entries: list[FootprintEntry]) -> dict[str, str]:
    """Map basename -> tier for convenient assertions."""
    return {e.path.name: e.tier for e in entries}


def test_state_dir_is_disposable(tmp_path: Path) -> None:
    (tmp_path / ".config" / "argo_anywhere").mkdir(parents=True)
    (tmp_path / ".config" / "argo_anywhere" / "user").write_text("someone\n")
    entries = footprint(home=tmp_path)
    assert _tiers(entries)["argo_anywhere"] == "disposable"


def test_canonical_dir_is_artifact(tmp_path: Path) -> None:
    (tmp_path / ".argo_anywhere" / "bin").mkdir(parents=True)
    entries = footprint(home=tmp_path)
    assert any(e.path.name == ".argo_anywhere" and e.tier == "artifact" for e in entries)


def test_sockets_listed_disposable(tmp_path: Path) -> None:
    sock_dir = tmp_path / ".ssh" / "sockets"
    sock_dir.mkdir(parents=True)
    (sock_dir / "argo-anywhere-me-node-64742").write_text("")   # stand-in file
    (sock_dir / "argo-opencode-legacy").write_text("")          # v1.x prefix
    (sock_dir / "unrelated-socket").write_text("")              # not ours
    names = {e.path.name for e in footprint(home=tmp_path) if e.tier == "disposable"}
    assert "argo-anywhere-me-node-64742" in names
    assert "argo-opencode-legacy" in names
    assert "unrelated-socket" not in names


def test_config_backups_from_manifest(tmp_path: Path) -> None:
    state = tmp_path / ".config" / "argo_anywhere"
    state.mkdir(parents=True)
    # A pre-existing config we modified (has a backup) + a config we created.
    preexist = tmp_path / ".aider.conf.yml"
    created = tmp_path / ".aider.model.settings.yml"
    bak = Path(str(preexist) + ".bak.20260101-000000.123")
    bak.write_text("original contents\n")
    manifest = {
        "schema": 1,
        "configs": {
            str(preexist): {"preexisted": True, "created_by_us": False},
            str(created): {"preexisted": False, "created_by_us": True},
        },
        "binaries": {},
    }
    (state / "manifest.json").write_text(json.dumps(manifest))

    entries = footprint(home=tmp_path)
    baks = [e for e in entries if e.path == bak]
    assert len(baks) == 1 and baks[0].tier == "artifact"
    # The we-created config is NOT listed as a backup (no .bak; not our residue
    # to enumerate here -- uninstall deletes it via the manifest).
    assert not any(e.path == created for e in entries)


def test_format_size() -> None:
    assert format_size(0) == "0 B"
    assert format_size(512) == "512 B"
    assert format_size(1536) == "1.5 KB"
    assert format_size(5 * 1024 * 1024) == "5.0 MB"


def test_info_json_includes_footprint(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / ".argo_anywhere").mkdir()
    rc = cli.main(["info", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert "footprint" in payload
    assert any(Path(e["path"]).name == ".argo_anywhere" for e in payload["footprint"])
