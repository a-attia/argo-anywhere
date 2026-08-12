"""Tests for live-channel coverage in aider's model-settings file.

aider (via LiteLLM) sends a ``temperature`` param by default. Reasoning /
opus-4.7+ / gpt-5 / o-series / gemini models on the ANL gateway REJECT it and
argo-proxy returns an **empty stream** rather than an error, so the request
appears to succeed and produces nothing. ``.aider.model.settings.yml`` exists
to set ``use_temperature: false`` for those models.

Its model list was hardcoded, and drifted. Measured 2026-08-12 against a live
channel serving 34 chat models, five had no entry::

    claude-5-opus  claude-5-sonnet  gpt-5.6-luna  gpt-5.6-sol  gpt-5.6-terra

Those are exactly the models whose temperature must be suppressed, so
``aider --model openai/argo:claude-5-opus`` hit the failure the file exists to
prevent -- on the newest and most-wanted models.

The list is now the **union** of the hardcoded floor and the live
``/v1/models``. Unlike the OpenCode writer this file is entirely ours, so
there is no user data to preserve -- but coverage must never SHRINK, which is
why the floor stays rather than being replaced: a momentary curl failure must
not silently drop temperature suppression for a model the user is mid-session
with. Extra entries for unserved models are inert.

Both writers are covered. The python/PyYAML path and the scratch fallback had
*separate copies* of the same stale list; fixing only the first would have
left a laptop without PyYAML emitting a file with no entry for the new models.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from argo_anywhere._engine import engine_path

# Two chat models and one embedding (must be filtered). ``newmodel-9`` is
# deliberately absent from the hardcoded floor: it stands for "a model the
# proxy started serving after this list was written", which is the whole bug.
STUB_MODELS_JSON = json.dumps(
    {
        "data": [
            {"id": "argo:gpt-4o", "internal_name": "gpt4o"},
            {"id": "argo:newmodel-9", "internal_name": "newmodel9"},
            {"id": "argo:text-embedding-3", "internal_name": "embed3"},
            # Two spellings of ONE model -- same internal_name, both served.
            # aider matches on the literal id the user types, so BOTH need an
            # entry. See test_alias_spellings_each_get_an_entry.
            {"id": "argo:brandnew-5-opus", "internal_name": "brandnew5opus"},
            {"id": "argo:brandnew-opus-5", "internal_name": "brandnew5opus"},
        ]
    }
)


def _engine_source() -> str:
    with engine_path() as script:
        return script.read_text()


def _function_body(src: str, name: str) -> str:
    """Extract a shell function, honouring heredocs (see the OpenCode module)."""
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


def _run(
    tmp_path: Path,
    *,
    writer: str,
    models_body: str,
    with_jq: bool = True,
) -> list[str]:
    """Run one of the two writers; return the model names in the settings file."""
    src = _engine_source()
    fns = "\n".join(
        (
            _function_body(src, "_aider_live_model_ids"),
            _function_body(src, "write_aider_config"),
            _function_body(src, "_aider_write_config_scratch"),
        )
    )

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    tools = ["sed", "cat", "printf", "grep", "mktemp", "curl", "sh", "date", "cp",
             "dirname", "python3", "tr"]
    if with_jq:
        tools.append("jq")
    for tool in tools:
        found = shutil.which(tool)
        if found:
            (fake_bin / tool).symlink_to(found)

    body_file = tmp_path / "models.json"
    body_file.write_text(models_body)
    orig = tmp_path / ".aider.conf.yml"
    orig.write_text("openai-api-base: http://localhost:64742/v1\n")
    settings = tmp_path / ".aider.model.settings.yml"
    dest = tmp_path / "out.yml"

    if writer == "python":
        invoke = f"write_aider_config {dest}"
    else:
        invoke = (
            f"_aider_write_config_scratch {dest} aattia 64751 "
            f"openai/argo:gpt-4o {orig} {settings}"
        )

    script = "\n".join(
        (
            "set -euo pipefail",
            f"PATH={fake_bin}",
            "PROXY_PORT=64751",
            "ARGO_ANYWHERE_USER=aattia",
            f"_AIDER_SCOPE_PATH={orig}",
            'die() { echo "DIE: $*" >&2; exit 1; }',
            'log() { :; }',
            'warn() { :; }',
            'ok() { :; }',
            f"fetch_proxy_models() {{ cat {body_file}; }}",
            fns,
            invoke,
        )
    )
    script_path = tmp_path / "harness.sh"
    script_path.write_text(script)

    proc = subprocess.run(
        ["bash", str(script_path)], capture_output=True, text=True, timeout=60
    )
    assert proc.returncode == 0, f"writer failed: {proc.stderr}"
    assert settings.exists(), "no settings file written"
    return re.findall(r"^- name: (.+)$", settings.read_text(), re.MULTILINE)


# ---------------------------------------------------------------------------
# The regression
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("writer", ["python", "scratch"])
def test_newly_served_model_gets_temperature_disabled(
    tmp_path: Path, writer: str
) -> None:
    """A model the proxy serves but the floor never heard of must be covered.

    This is the 2026-08-12 finding in miniature: without it, that model
    silently returns an empty stream.
    """
    names = _run(tmp_path, writer=writer, models_body=STUB_MODELS_JSON)
    assert "openai/argo:newmodel-9" in names, (
        f"a served model is missing from the settings file ({writer} path); "
        "aider will send temperature and get an empty stream back"
    )


@pytest.mark.parametrize("writer", ["python", "scratch"])
def test_alias_spellings_each_get_an_entry(tmp_path: Path, writer: str) -> None:
    """Every served *id* needs an entry -- aliases are not interchangeable here.

    This is where the first version of the fix was still wrong. It reused the
    OpenCode writer's ``unique_by(.internal_name)``, which is correct there
    (that config is KEYED by internal_name, so aliases collapse to one entry)
    and wrong here: aider matches the settings file against the literal id the
    user types. The proxy serves both ``argo:claude-5-opus`` and
    ``argo:claude-opus-5`` for one internal_name, jq kept the first, and
    ``--model openai/argo:claude-opus-5`` still returned an empty stream --
    the original bug surviving in half its cases.

    Found by checking coverage against the live list *after* the fix looked
    like it passed: 46 entries for 48 served ids.
    """
    names = _run(tmp_path, writer=writer, models_body=STUB_MODELS_JSON)
    for alias in ("brandnew-5-opus", "brandnew-opus-5"):
        assert f"openai/argo:{alias}" in names, (
            f"alias {alias!r} has no entry; aider matches on the literal id, "
            "so collapsing aliases leaves half the spellings broken"
        )


@pytest.mark.parametrize("writer", ["python", "scratch"])
def test_hardcoded_floor_is_never_lost(tmp_path: Path, writer: str) -> None:
    """The live list AUGMENTS the floor; it must not replace it.

    The stub serves two models. If the writer replaced rather than unioned,
    coverage would collapse from ~41 entries to 2 -- dropping suppression for
    models a user may be mid-session with.
    """
    names = _run(tmp_path, writer=writer, models_body=STUB_MODELS_JSON)
    assert "openai/argo:claude-opus-4.8" in names, (
        "a floor entry vanished; the live list must union, not replace"
    )
    assert len(names) > 30, f"coverage collapsed to {len(names)} entries"


@pytest.mark.parametrize("writer", ["python", "scratch"])
def test_no_duplicate_entries(tmp_path: Path, writer: str) -> None:
    """``gpt-4o`` is in both the floor and the stub's live list."""
    names = _run(tmp_path, writer=writer, models_body=STUB_MODELS_JSON)
    assert len(names) == len(set(names)), (
        f"duplicate entries: {[n for n in names if names.count(n) > 1]}"
    )


@pytest.mark.parametrize("writer", ["python", "scratch"])
def test_embeddings_are_filtered(tmp_path: Path, writer: str) -> None:
    names = _run(tmp_path, writer=writer, models_body=STUB_MODELS_JSON)
    assert not any("embedding" in n for n in names)


# ---------------------------------------------------------------------------
# Degradation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("writer", ["python", "scratch"])
def test_unreachable_channel_degrades_to_the_floor(
    tmp_path: Path, writer: str
) -> None:
    """No channel must still produce the old, working file -- never an empty one."""
    names = _run(tmp_path, writer=writer, models_body="")
    assert len(names) > 30, f"fallback produced only {len(names)} entries"
    assert "openai/argo:gpt-4o" in names


@pytest.mark.parametrize("writer", ["python", "scratch"])
def test_no_jq_degrades_to_the_floor(tmp_path: Path, writer: str) -> None:
    names = _run(
        tmp_path, writer=writer, models_body=STUB_MODELS_JSON, with_jq=False
    )
    assert len(names) > 30
    assert "openai/argo:gpt-4o" in names


def test_malformed_body_degrades_without_dying(tmp_path: Path) -> None:
    names = _run(tmp_path, writer="python", models_body="{not json")
    assert len(names) > 30


# ---------------------------------------------------------------------------
# Contract
# ---------------------------------------------------------------------------


def test_resolver_conveys_result_through_a_global() -> None:
    """D-005: a ``$(...)`` capture would lose the memo across the two calls."""
    src = _engine_source()
    body = _function_body(src, "write_aider_config")
    assert "_aider_live_model_ids" in body
    assert "$(_aider_live_model_ids" not in body, (
        "call directly; the resolver sets globals (D-005)"
    )


def test_resolver_is_memoised() -> None:
    """``handle_config_file`` calls the writer twice; both must agree."""
    body = _function_body(_engine_source(), "_aider_live_model_ids")
    assert "_AIDER_LIVE_IDS_RESOLVED" in body


def test_both_writers_consult_the_live_list() -> None:
    """The scratch fallback had its own copy of the stale list.

    Fixing only the python path would leave a laptop without PyYAML emitting
    a settings file with no entry for the newest models.
    """
    src = _engine_source()
    for name in ("write_aider_config", "_aider_write_config_scratch"):
        assert "_aider_live_model_ids" in _function_body(src, name), (
            f"{name} does not consult the live model list"
        )


def test_invariant_rationale_is_attached() -> None:
    assert "STALE-COVERAGE INVARIANT" in _engine_source()


def test_engine_copies_stay_byte_identical() -> None:
    """Root and vendored engine copies must not diverge (D-001/D-028)."""
    repo_root = Path(__file__).resolve().parent.parent
    root_copy = repo_root / "argo-anywhere.sh"
    if not root_copy.exists():  # pragma: no cover
        pytest.skip("root engine copy not present in this layout")
    with engine_path() as vendored:
        assert root_copy.read_bytes() == vendored.read_bytes()
