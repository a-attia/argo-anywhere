"""Tests for live-channel model population in ``write_opencode_config``.

``write_opencode_config`` used to emit a **hardcoded five-model block**, and
``handle_config_file``'s ``[b]ackup+overwrite`` replaces the target file
wholesale. So a user whose config had been populated by ``update-models``
lost every model beyond those five -- silently, while running ``configure``,
a command with no obvious connection to their model picker.

Measured on the maintainer's laptop (2026-08-12), against a live channel
serving 51 ids / 34 unique chat models::

    before: 34 models    after: 5 models    gained: 0

Among the 29 deleted was ``claudeopus5`` -- the model driving the session
that ran the command.

The writer now populates from the live ``/v1/models`` and unions the result
with whatever the config already had. Three rules, each pinned below:

1. **Degrade, never die** -- no channel / no ``jq`` / malformed body must
   still produce a valid config.
2. **Never drop an existing key** -- the writer cannot prompt (it runs twice
   inside ``handle_config_file``, once for the diff), so it cannot obtain
   consent, so deletion is not its business. Removing orphans stays
   ``update-models``, which asks per model.
3. **Fetch once per run** -- otherwise the proposal shown in the diff can
   differ from what actually gets written.

The behavioural tests extract the real engine functions and run them under
bash against a stub ``fetch_proxy_models``, so they exercise the shipped code
rather than a re-implementation.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

from argo_anywhere._engine import engine_path


def _engine_source() -> str:
    with engine_path() as script:
        return script.read_text()


def _function_body(src: str, name: str) -> str:
    """Extract a shell function, honouring heredocs.

    The naive ``^name\\(\\).*?^\\}`` regex used by the other engine test
    modules truncates here: both functions below emit JSON via a heredoc, and
    that JSON closes with a ``}`` at column 0. The regex stops at the first
    one, yielding a fragment that ends mid-heredoc -- which parses as
    "unexpected end of file" when handed to bash. Track heredoc state instead.
    """
    lines = src.splitlines()
    start = next(
        (i for i, line in enumerate(lines) if line.startswith(f"{name}() {{")),
        None,
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


# A minimal /v1/models payload in the shape argo-proxy returns: two chat
# models, one embedding (must be filtered), one alias duplicating an
# internal_name (must be deduped).
STUB_MODELS_JSON = json.dumps(
    {
        "data": [
            {"id": "argo:gpt-5.4", "internal_name": "gpt54"},
            {"id": "argo:claude-5-opus", "internal_name": "claudeopus5"},
            {"id": "argo:text-embedding-3", "internal_name": "embed3"},
            {"id": "argo:gpt-5.4-alias", "internal_name": "gpt54"},
        ]
    }
)


def _run_writer(
    tmp_path: Path,
    *,
    existing: dict | None,
    models_body: str,
    with_jq: bool = True,
    with_python: bool = True,
) -> tuple[dict, dict[str, str]]:
    """Run the real ``write_opencode_config`` under bash; return (config, globals).

    ``models_body`` is what the stubbed ``fetch_proxy_models`` prints -- empty
    string simulates an unreachable channel.
    """
    src = _engine_source()
    helpers = "\n".join(
        (
            _function_body(src, "_opencode_models_hardcoded"),
            _function_body(src, "_opencode_models_block"),
            _function_body(src, "write_opencode_config"),
        )
    )

    existing_path = tmp_path / "existing.json"
    if existing is not None:
        existing_path.write_text(json.dumps(existing, indent=2))

    dest = tmp_path / "out.json"
    body_file = tmp_path / "models_body.json"
    body_file.write_text(models_body)

    # A PATH containing only what the writer legitimately needs, so masking
    # jq / python3 is a real absence rather than a shadowed name.
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    needed = ["sed", "cat", "printf", "grep", "mktemp", "curl", "sh"]
    if with_jq:
        needed.append("jq")
    if with_python:
        needed.append("python3")
    for tool in needed:
        found = shutil.which(tool)
        if found:
            (fake_bin / tool).symlink_to(found)

    # Write to a file rather than passing via `bash -c`: the extracted engine
    # functions contain heredocs whose terminators must sit at column 0, so any
    # re-indentation (or dedent) of the embedded source breaks parsing.
    script = "\n".join(
        (
            "set -euo pipefail",
            f"PATH={fake_bin}",
            "PROXY_PORT=64751",
            "ARGO_ANYWHERE_USER=testuser",
            f"OPENCODE_GLOBAL_CONFIG={existing_path}",
            f"_OPENCODE_SCOPE_PATH={existing_path}",
            'die() { echo "DIE: $*" >&2; exit 1; }',
            f"fetch_proxy_models() {{ cat {body_file}; }}",
            helpers,
            f"write_opencode_config {dest}",
            'echo "SOURCE=${_OPENCODE_MODELS_SOURCE:-<unset>}" >&2',
            'echo "ADDED=${_OPENCODE_MODELS_ADDED:-<unset>}" >&2',
            'echo "KEPT=${_OPENCODE_MODELS_KEPT:-<unset>}" >&2',
        )
    )
    script_path = tmp_path / "harness.sh"
    script_path.write_text(script)

    proc = subprocess.run(
        ["bash", str(script_path)], capture_output=True, text=True, timeout=60
    )
    assert proc.returncode == 0, f"writer failed: {proc.stderr}"

    reported = dict(
        line.split("=", 1)
        for line in proc.stderr.splitlines()
        if "=" in line and line.split("=", 1)[0] in {"SOURCE", "ADDED", "KEPT"}
    )
    return json.loads(dest.read_text()), reported


def _models(cfg: dict) -> dict:
    return cfg["provider"]["argo"]["models"]


# ---------------------------------------------------------------------------
# Rule 2 -- the regression itself
# ---------------------------------------------------------------------------


def test_existing_models_are_never_dropped(tmp_path: Path) -> None:
    """The 2026-08-12 regression: 34 models -> 5, none gained.

    The config carries a model the proxy does not serve. It must survive.
    """
    existing = {
        "provider": {
            "argo": {
                "models": {
                    "legacymodel99": {"name": "legacy-99"},
                    "gpt54": {"name": "stale-name"},
                }
            }
        }
    }
    cfg, reported = _run_writer(
        tmp_path, existing=existing, models_body=STUB_MODELS_JSON
    )
    models = _models(cfg)

    assert "legacymodel99" in models, (
        "a model the proxy no longer serves must be PRESERVED; the writer "
        "cannot prompt, so it cannot obtain consent to delete"
    )
    assert "claudeopus5" in models, "live models must be added"
    assert reported["SOURCE"] == "live"
    assert reported["KEPT"] == "1", "the preserved orphan should be reported"


def test_live_list_wins_on_collision(tmp_path: Path) -> None:
    """A key in both places takes the live display name (fresher)."""
    existing = {"provider": {"argo": {"models": {"gpt54": {"name": "stale-name"}}}}}
    cfg, _ = _run_writer(tmp_path, existing=existing, models_body=STUB_MODELS_JSON)
    assert _models(cfg)["gpt54"]["name"] == "gpt-5.4"


def test_embeddings_filtered_and_aliases_deduped(tmp_path: Path) -> None:
    """Selection rules must match ``update-models``' jq filter."""
    cfg, _ = _run_writer(tmp_path, existing=None, models_body=STUB_MODELS_JSON)
    models = _models(cfg)
    assert "embed3" not in models, "embedding models are not chat-usable"
    assert sorted(models) == ["claudeopus5", "gpt54"], (
        "the duplicate internal_name must collapse to one entry"
    )


# ---------------------------------------------------------------------------
# Rule 1 -- degrade, never die
# ---------------------------------------------------------------------------


def test_unreachable_channel_falls_back_without_dying(tmp_path: Path) -> None:
    cfg, reported = _run_writer(tmp_path, existing=None, models_body="")
    assert reported["SOURCE"] == "fallback"
    assert len(_models(cfg)) == 5, "the hardcoded floor still produces a usable config"
    assert cfg["provider"]["argo"]["options"]["baseURL"] == "http://localhost:64751/v1"


def test_malformed_body_falls_back_without_dying(tmp_path: Path) -> None:
    cfg, reported = _run_writer(
        tmp_path, existing=None, models_body="{not valid json at all"
    )
    assert reported["SOURCE"] == "fallback"
    assert len(_models(cfg)) == 5


def test_fallback_still_preserves_existing_models(tmp_path: Path) -> None:
    """Degrading must not become a licence to delete."""
    existing = {"provider": {"argo": {"models": {"legacymodel99": {"name": "L"}}}}}
    cfg, reported = _run_writer(tmp_path, existing=existing, models_body="")
    assert reported["SOURCE"] == "fallback"
    assert "legacymodel99" in _models(cfg)


def test_no_jq_preserves_existing_models_via_python(tmp_path: Path) -> None:
    """The corner that shipped broken in the first draft.

    The original comment rationalised emitting the bare hardcoded block here
    ("a jq-less laptop can't have a populated config anyway"). That is false:
    configs are portable -- copied from a colleague, synced via dotfiles, or
    left behind when jq is uninstalled. Verified by execution: with jq masked,
    the draft took a 4-model config down to the hardcoded 5.
    """
    existing = {"provider": {"argo": {"models": {"legacymodel99": {"name": "L"}}}}}
    cfg, _ = _run_writer(
        tmp_path, existing=existing, models_body=STUB_MODELS_JSON, with_jq=False
    )
    assert "legacymodel99" in _models(cfg), (
        "python3 must perform the union jq would have done"
    )


def test_neither_jq_nor_python_still_writes_valid_config(tmp_path: Path) -> None:
    """The documented floor: a valid config, even if it cannot union."""
    cfg, reported = _run_writer(
        tmp_path,
        existing=None,
        models_body=STUB_MODELS_JSON,
        with_jq=False,
        with_python=False,
    )
    assert reported["SOURCE"] == "fallback"
    assert len(_models(cfg)) == 5


# ---------------------------------------------------------------------------
# Rule 3 + D-005 -- fetch once, and convey provenance through globals
# ---------------------------------------------------------------------------


def test_models_block_is_not_captured_in_a_subshell() -> None:
    """D-005: ``$(...)`` around the resolver would drop its reporting globals.

    The first draft printed the block to stdout and captured it. The value
    survived; ``_OPENCODE_MODELS_SOURCE`` / ``_ADDED`` / ``_KEPT`` did not,
    and ``set -u`` fired on the first read. Pin the call shape.
    """
    body = _function_body(_engine_source(), "write_opencode_config")
    assert "_opencode_models_block" in body
    assert "$(_opencode_models_block" not in body, (
        "call directly; a subshell capture loses the provenance globals (D-005)"
    )


def test_resolver_memoises_so_both_writer_calls_agree() -> None:
    """``handle_config_file`` invokes the writer twice (diff, then write).

    Without the memo the two calls can disagree, so the diff the user approves
    is not the file they get.
    """
    body = _function_body(_engine_source(), "_opencode_models_block")
    assert "_OPENCODE_MODELS_CACHE" in body
    first_line = body.index("_OPENCODE_MODELS_CACHE")
    assert first_line < body.index("have_jq=0"), (
        "the cache check must short-circuit BEFORE any fetch work"
    )


def test_union_reads_the_real_config_not_the_destination() -> None:
    """``$dest`` is an empty temp file on the diff call.

    Unioning against it would read ``{}`` and drop every existing model right
    where the diff is computed -- the same bug, one layer down.
    """
    body = _function_body(_engine_source(), "write_opencode_config")
    assert "_OPENCODE_SCOPE_PATH" in body, (
        "union must read the resolved scope path, never the destination"
    )
    assert '_opencode_models_block "$dest"' not in body


def test_invariant_rationale_is_attached() -> None:
    src = _engine_source()
    assert "NO-SILENT-MODEL-DELETION INVARIANT" in src, (
        "keep the rationale next to the code it constrains"
    )


def test_engine_copies_stay_byte_identical() -> None:
    """Root and vendored engine copies must not diverge (D-001/D-028)."""
    repo_root = Path(__file__).resolve().parent.parent
    root_copy = repo_root / "argo-anywhere.sh"
    if not root_copy.exists():  # pragma: no cover
        pytest.skip("root engine copy not present in this layout")
    with engine_path() as vendored:
        assert root_copy.read_bytes() == vendored.read_bytes()
