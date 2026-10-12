"""OpenCode 2 config-name migration (D-036).

argo-anywhere wrote the global OpenCode config to
``~/.config/opencode/config.json`` until v3.4.0. OpenCode 1.x reads that name;
OpenCode 2.x reads only ``opencode.json(c)`` and ignores ``config.json``
silently. Field report 2026-10-12: after upgrading to OpenCode 2.0.27, no
``argo/`` models appeared, with no error anywhere.

The engine now writes ``opencode.json`` and migrates the old name from every
mutating verb. These tests pin the case table in
``notes/impl_opencode_v2_migration.md`` §4.2, the manifest re-keying that
keeps uninstall able to find pre-rename backups, and the rule that read-only
paths fall back to the old name without touching it.

Like the other engine tests, they extract the real shell functions and run
them under bash in a sandboxed ``$HOME``; nothing here contacts ANL.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

from argo_anywhere import status
from argo_anywhere._engine import engine_path


def _engine_source() -> str:
    with engine_path() as script:
        return script.read_text()


def _function_body(src: str, name: str) -> str:
    """Extract a shell function, honouring heredocs (see test_engine_opencode_models)."""
    lines = src.splitlines()
    start = next(
        (i for i, line in enumerate(lines) if line.startswith(f"{name}() {{")), None
    )
    assert start is not None, f"{name} definition not found in engine"
    pending: str | None = None
    for idx in range(start, len(lines)):
        line = lines[idx]
        if pending is not None:
            if line.strip() == pending:
                pending = None
            continue
        opener = re.search(r"<<-?\s*'?([A-Za-z_][A-Za-z0-9_]*)'?", line)
        if opener:
            pending = opener.group(1)
            continue
        if idx > start and line == "}":
            return "\n".join(lines[start : idx + 1])
    raise AssertionError(f"unterminated function body for {name}")


def _constants_block(src: str) -> str:
    """The OPENCODE_* path constants, including the read-path fallback."""
    m = re.search(
        r'^OPENCODE_GLOBAL_CONFIG=.*?^OPENCODE_PROJECT_CONFIG_BASENAME=.*?$',
        src,
        re.S | re.M,
    )
    assert m, "OPENCODE_* constants block not found"
    return m.group(0)


ARGO = {
    "$schema": "https://opencode.ai/config.json",
    "provider": {
        "argo": {
            "npm": "@ai-sdk/openai-compatible",
            "options": {"baseURL": "http://localhost:64743/v1"},
            "models": {"gpt4o": {"name": "GPT-4o"}, "claudeopus5": {"name": "Opus 5"}},
        }
    },
}


def _run(home: Path, body: str, *, manifest: dict | None = None) -> subprocess.CompletedProcess:
    src = _engine_source()
    state = home / ".argo_anywhere"
    state.mkdir(parents=True, exist_ok=True)
    if manifest is not None:
        (state / "manifest.json").write_text(json.dumps(manifest))
    script = "\n".join(
        (
            "set -uo pipefail",
            f'HOME="{home}"',
            f'ARGO_MANIFEST="{state}/manifest.json"',
            "log()  { printf 'LOG %s\\n' \"$*\" >&2; }",
            "ok()   { printf 'OK %s\\n' \"$*\" >&2; }",
            "warn() { printf 'WARN %s\\n' \"$*\" >&2; }",
            "die()  { printf 'DIE %s\\n' \"$*\" >&2; exit 3; }",
            "_manifest_available() { return 0; }",
            _constants_block(src),
            _function_body(src, "_manifest_rename_config"),
            _function_body(src, "_manifest_configs_to_restore"),
            "_OPENCODE_MIGRATED=0",
            _function_body(src, "_migrate_opencode_global_config_name"),
            _function_body(src, "_opencode_legacy_name_only"),
            body,
        )
    )
    path = home / "t.sh"
    path.write_text(script)
    return subprocess.run(["bash", str(path)], capture_output=True, text=True, timeout=30)


@pytest.fixture
def home(tmp_path: Path) -> Path:
    (tmp_path / ".config" / "opencode").mkdir(parents=True)
    return tmp_path


def _oc(home: Path, name: str) -> Path:
    return home / ".config" / "opencode" / name


# ---------------------------------------------------------------------------
# Case table (§4.2)
# ---------------------------------------------------------------------------


def test_legacy_only_is_renamed_and_symlinked(home: Path) -> None:
    _oc(home, "config.json").write_text(json.dumps(ARGO))
    out = _run(home, '_migrate_opencode_global_config_name; echo "M=$_OPENCODE_MIGRATED C=$OPENCODE_CONFIG"')
    assert out.returncode == 0, out.stderr
    new, old = _oc(home, "opencode.json"), _oc(home, "config.json")
    assert json.loads(new.read_text()) == ARGO
    assert old.is_symlink() and old.resolve() == new.resolve()
    assert f"M=1 C={new}" in out.stdout


def test_migration_is_idempotent(home: Path) -> None:
    _oc(home, "config.json").write_text(json.dumps(ARGO))
    out = _run(home, "_migrate_opencode_global_config_name; _OPENCODE_MIGRATED=0; "
                     '_migrate_opencode_global_config_name; echo "M=$_OPENCODE_MIGRATED"')
    assert out.returncode == 0, out.stderr
    assert "M=0" in out.stdout
    assert json.loads(_oc(home, "opencode.json").read_text()) == ARGO


def test_nothing_to_migrate_is_a_noop(home: Path) -> None:
    out = _run(home, '_migrate_opencode_global_config_name; echo "M=$_OPENCODE_MIGRATED"')
    assert out.returncode == 0 and "M=0" in out.stdout
    assert not _oc(home, "opencode.json").exists()


def test_both_present_without_argo_leaves_both(home: Path) -> None:
    """A config.json that is not ours is not ours to move."""
    _oc(home, "config.json").write_text(json.dumps({"theme": "x"}))
    _oc(home, "opencode.json").write_text(json.dumps({"theme": "y"}))
    out = _run(home, '_migrate_opencode_global_config_name; echo "M=$_OPENCODE_MIGRATED"')
    assert out.returncode == 0 and "M=0" in out.stdout
    assert json.loads(_oc(home, "config.json").read_text()) == {"theme": "x"}
    assert json.loads(_oc(home, "opencode.json").read_text()) == {"theme": "y"}


def test_both_present_merge_never_drops_a_model(home: Path) -> None:
    """NO-SILENT-MODEL-DELETION applies to the merge too."""
    _oc(home, "config.json").write_text(json.dumps(ARGO))
    cur = {
        "theme": "dark",
        "provider": {"argo": {"options": {"baseURL": "http://localhost:65000/v1"},
                              "models": {"gpt5": {"name": "GPT-5"}}}},
    }
    _oc(home, "opencode.json").write_text(json.dumps(cur))
    out = _run(home, '_migrate_opencode_global_config_name; echo "M=$_OPENCODE_MIGRATED"')
    assert out.returncode == 0, out.stderr
    assert "M=1" in out.stdout
    merged = json.loads(_oc(home, "opencode.json").read_text())
    assert set(merged["provider"]["argo"]["models"]) == {"gpt5", "gpt4o", "claudeopus5"}
    # opencode.json wins on a conflicting scalar, and the user is told.
    assert merged["provider"]["argo"]["options"]["baseURL"].endswith(":65000/v1")
    assert merged["theme"] == "dark"
    assert "provider.argo.options.baseURL" in out.stderr
    # Nothing destroyed: old file parked, new file backed up, compat symlink.
    d = _oc(home, "x").parent
    assert len(list(d.glob("config.json.migrated.*"))) == 1
    assert len(list(d.glob("opencode.json.bak.*"))) == 1
    assert _oc(home, "config.json").is_symlink()


def test_unparseable_legacy_is_left_alone(home: Path) -> None:
    _oc(home, "config.json").write_text("{ not json")
    _oc(home, "opencode.json").write_text(json.dumps({"theme": "y"}))
    out = _run(home, '_migrate_opencode_global_config_name; echo "rc=$?"')
    assert "rc=0" in out.stdout, "the migration must never fail its caller"
    assert _oc(home, "config.json").read_text() == "{ not json"


def test_jsonc_present_touches_nothing(home: Path) -> None:
    """We cannot rewrite JSONC without destroying its comments."""
    _oc(home, "config.json").write_text(json.dumps(ARGO))
    _oc(home, "opencode.jsonc").write_text("// mine\n{}")
    out = _run(home, '_migrate_opencode_global_config_name; echo "M=$_OPENCODE_MIGRATED"')
    assert out.returncode == 0 and "M=0" in out.stdout
    assert not _oc(home, "config.json").is_symlink()
    assert not _oc(home, "opencode.json").exists()
    assert "WARN" in out.stderr


def test_pick_scope_refuses_global_over_jsonc() -> None:
    src = _function_body(_engine_source(), "opencode_pick_scope")
    assert "OPENCODE_JSONC_GLOBAL_CONFIG" in src and "die " in src


# ---------------------------------------------------------------------------
# Read path: fall back, never mutate (§4.3)
# ---------------------------------------------------------------------------


def test_read_path_falls_back_to_legacy_without_touching_it(home: Path) -> None:
    _oc(home, "config.json").write_text(json.dumps(ARGO))
    out = _run(home, 'echo "C=$OPENCODE_CONFIG"; _opencode_legacy_name_only && echo LEGACY')
    assert f"C={_oc(home, 'config.json')}" in out.stdout
    assert "LEGACY" in out.stdout
    assert not _oc(home, "opencode.json").exists()


def test_read_path_prefers_new_name(home: Path) -> None:
    _oc(home, "config.json").write_text(json.dumps(ARGO))
    _oc(home, "opencode.json").write_text(json.dumps(ARGO))
    out = _run(home, 'echo "C=$OPENCODE_CONFIG"; _opencode_legacy_name_only || echo NOT-LEGACY')
    assert f"C={_oc(home, 'opencode.json')}" in out.stdout
    assert "NOT-LEGACY" in out.stdout


def test_status_card_and_port_enumeration_do_not_migrate() -> None:
    """Read-only verbs report; only mutating verbs call the migration."""
    src = _engine_source()
    for fn in ("mode_status", "enumerate_client_ports", "read_port_from_opencode_config"):
        assert "_migrate_opencode_global_config_name" not in _function_body(src, fn), fn
    for fn in ("setup_opencode_cli_tool", "mode_update_models", "_opencode_after_upgrade"):
        assert "_migrate_opencode_global_config_name" in _function_body(src, fn), fn


# ---------------------------------------------------------------------------
# Manifest + uninstall restore (§4.4)
# ---------------------------------------------------------------------------


def test_manifest_is_rekeyed_and_restore_finds_old_backups(home: Path) -> None:
    old, new = _oc(home, "config.json"), _oc(home, "opencode.json")
    old.write_text(json.dumps(ARGO))
    bak = old.with_name("config.json.bak.20260101-000000")
    bak.write_text("{}")
    manifest = {"schema": 1, "configs": {str(old): {
        "first_touched": "2026-01-01T00:00:00", "preexisted": True, "created_by_us": False}}}
    out = _run(home, "_migrate_opencode_global_config_name; _manifest_configs_to_restore",
               manifest=manifest)
    assert out.returncode == 0, out.stderr
    data = json.loads((home / ".argo_anywhere" / "manifest.json").read_text())
    assert list(data["configs"]) == [str(new)]
    assert data["configs"][str(new)]["legacy_path"] == str(old)
    assert data["configs"][str(new)]["first_touched"] == "2026-01-01T00:00:00"
    rows = [r.split("\t") for r in out.stdout.splitlines() if r]
    assert ["restore", str(new), str(bak)] in rows
    assert ["delete", str(old), ""] in rows, "the compat symlink goes on restore"


# ---------------------------------------------------------------------------
# Python mirror (status.py) -- coupled surface, same commit as the engine
# ---------------------------------------------------------------------------


def test_status_py_targets_the_new_name() -> None:
    assert dict(status._TOOL_CONFIGS)["opencode"].endswith("/opencode.json")


def test_status_py_flags_legacy_only(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "config.json").write_text(json.dumps(ARGO))
    monkeypatch.setattr(status, "_TOOL_CONFIGS",
                        (("opencode", str(tmp_path / "opencode.json")),))
    (t,) = status.client_tool_configs()
    assert t.legacy_name is True and t.port == 64743
    assert t.path == str(tmp_path / "config.json")
    assert not (tmp_path / "opencode.json").exists(), "status.py must never write"


def test_status_py_not_legacy_after_migration(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "opencode.json").write_text(json.dumps(ARGO))
    (tmp_path / "config.json").symlink_to("opencode.json")
    monkeypatch.setattr(status, "_TOOL_CONFIGS",
                        (("opencode", str(tmp_path / "opencode.json")),))
    (t,) = status.client_tool_configs()
    assert t.legacy_name is False and t.port == 64743


def test_status_py_jsonc_is_not_flagged(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "config.json").write_text(json.dumps(ARGO))
    (tmp_path / "opencode.jsonc").write_text("{}")
    monkeypatch.setattr(status, "_TOOL_CONFIGS",
                        (("opencode", str(tmp_path / "opencode.json")),))
    (t,) = status.client_tool_configs()
    assert t.legacy_name is False


# ---------------------------------------------------------------------------
# Service-restart offer fires only on a real change
# ---------------------------------------------------------------------------
# `run opencode` passes through setup_opencode_cli_tool on every launch, and
# handle_config_file runs even when its output is byte-identical or the user
# picks [k]eep. Offering a restart (which interrupts open OpenCode sessions)
# on every launch would be noise the user learns to ignore.


@pytest.mark.parametrize("writes, expect", [("same", "0"), ("different", "1"), ("keep", "0")])
def test_restart_offer_only_when_config_changed(tmp_path: Path, writes: str, expect: str) -> None:
    src = _engine_source()
    cfg = tmp_path / "opencode.json"
    cfg.write_text('{"a": 1}')
    new = '{"a": 1}' if writes == "same" else '{"a": 2}'
    handler = (
        "handle_config_file() { :; }" if writes == "keep"
        else f"handle_config_file() {{ printf '%s' '{new}' > \"$1\"; }}"
    )
    script = "\n".join((
        "set -uo pipefail",
        "log() { :; }",
        "_migrate_opencode_global_config_name() { :; }",
        f'opencode_pick_scope() {{ _OPENCODE_SCOPE_PATH="{cfg}"; _OPENCODE_SCOPE_NAME=g; }}',
        "ensure_opencode_installed() { :; }",
        handler,
        "_OPENCODE_CONFIG_CHANGED=0",
        _function_body(src, "_file_fingerprint"),
        _function_body(src, "setup_opencode_cli_tool"),
        'setup_opencode_cli_tool; echo "CHANGED=$_OPENCODE_CONFIG_CHANGED"',
    ))
    path = tmp_path / "s.sh"
    path.write_text(script)
    out = subprocess.run(["bash", str(path)], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    assert f"CHANGED={expect}" in out.stdout


def test_dispatcher_gates_restart_offer_on_change() -> None:
    body = _function_body(_engine_source(), "do_post_tunnel_for_cli_tool")
    i = body.index("_opencode_offer_service_restart")
    assert "_OPENCODE_CONFIG_CHANGED" in body[max(0, i - 400):i]
