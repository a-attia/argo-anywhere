"""Tests for the ROUTING-HONESTY PROBE (``_probe_proxy_routing``).

Companion to ``test_engine_routing_refresh.py``. That module pins the
*repair* (mutating verbs POST ``/refresh``); this one pins the *detection*
that read-only verbs (``status``, ``list-models``) use instead.

``argo-proxy`` advertises models from one table (``/v1/models``) and routes
from another that only ``/refresh`` rebuilds. The routing table is exposed
nowhere except the 404 for an unknown model::

    Unknown model: 'x'. Configured models: argo:a, argo:b, ...

So the probe requests a model that cannot exist and diffs the disclosed list
against ``/v1/models``. Contract under test:

1. **Probe via /v1/messages, never /v1/chat/completions.** Measured
   2026-10-26: the OpenAI path fuzzy-matched a bogus id to ``gpt-5.4-nano``
   and ran a billed completion. ``max_tokens`` is bounded as a backstop.
2. **Fail toward "unverified", never toward "routable".** Reworded message,
   empty list, no jq, no response -> ``unverified``.
3. **A model is unroutable only if NONE of its aliases routes.**
4. **Read-only**: the probe never calls ``/refresh`` (D-034).
5. **Downstream honesty**: ``status`` downgrades to ``CHECK`` and stops
   counting unroutable models as reachable; ``list-models`` warns on stderr
   without changing tsv/json output.
"""

from __future__ import annotations

import json
import re
import subprocess
import tempfile
import textwrap
from pathlib import Path

from argo_anywhere._engine import engine_path


def _engine_source() -> str:
    with engine_path() as script:
        return script.read_text()


def _function_body(src: str, name: str) -> str:
    match = re.search(rf"^{re.escape(name)}\(\) \{{\n.*?^\}}$", src, re.M | re.S)
    assert match, f"{name} not found in engine"
    return match.group(0)


def _code_only(body: str) -> str:
    return "\n".join(
        line for line in body.splitlines() if not line.lstrip().startswith("#")
    )


MODELS = {
    "data": [
        {"id": "argo:gpt-4o", "internal_name": "gpt4o"},
        {"id": "argo:claude-4.6-opus", "internal_name": "claudeopus46"},
        # Two aliases, neither routed -> ONE unroutable model.
        {"id": "argo:claude-opus-5.5", "internal_name": "claudeopus55"},
        {"id": "argo:claude-5.5-opus", "internal_name": "claudeopus55"},
        # Two aliases, ONE routed -> routable.
        {"id": "argo:sonnet-x", "internal_name": "sonnetx"},
        {"id": "argo:sonnet-x-alias", "internal_name": "sonnetx"},
        {"id": "argo:text-embedding-9", "internal_name": "embed9"},
    ]
}
ROUTED_ALL = [
    "argo:gpt-4o",
    "argo:claude-4.6-opus",
    "argo:claude-opus-5.5",
    "argo:claude-5.5-opus",
    "argo:sonnet-x",
    "argo:sonnet-x-alias",
    "argo:text-embedding-9",
]
ROUTED_STALE = ["argo:gpt-4o", "argo:claude-4.6-opus", "argo:sonnet-x-alias"]


def _error(routed: list[str]) -> str:
    return json.dumps(
        {
            "type": "error",
            "error": {
                "type": "invalid_request_error",
                "message": "Unknown model: 'argo-anywhere-routing-probe-nonexistent'. "
                "Configured models: " + ", ".join(routed),
            },
        }
    )


def _run_probe(
    resp: str, *, body: str | None = None, no_jq: bool = False
) -> tuple[dict[str, str], str]:
    """Run the real ``_probe_proxy_routing`` with a logging ``curl`` stub."""
    src = _engine_source()
    jq_shim = (
        'command() { if [ "${1:-}" = -v ] && [ "${2:-}" = jq ]; then return 1; fi; '
        'builtin command "$@"; }'
        if no_jq
        else ""
    )
    harness = textwrap.dedent(
        """
        set -euo pipefail
        PROXY_PORT=64999
        {jq_shim}
        curl() {{ printf '%s\\n' "$*" >> "$PWD/curl.log"; cat "$PWD/resp.txt"; }}
        _ROUTING_PROBE_MODEL="argo-anywhere-routing-probe-nonexistent"
        {fn}
        _probe_proxy_routing "$(cat "$PWD/models.json")"
        for v in SUM_ROUTING_STATE SUM_ROUTING_REASON SUM_UNROUTABLE_COUNT \\
                 SUM_UNROUTABLE_CHAT_COUNT SUM_UNROUTABLE_LIST; do
          printf '%s=%s\\n' "$v" "${{!v}}"
        done
        printf 'INTERNAL=%s\\n' "$(printf '%s' "$SUM_UNROUTABLE_INTERNAL" | tr '\\n' ' ')"
        """
    ).format(jq_shim=jq_shim, fn=_function_body(src, "_probe_proxy_routing"))
    with tempfile.TemporaryDirectory() as td:
        Path(td, "resp.txt").write_text(resp)
        Path(td, "models.json").write_text(json.dumps(MODELS) if body is None else body)
        Path(td, "curl.log").write_text("")
        Path(td, "h.sh").write_text(harness)
        out = subprocess.run(
            ["bash", "h.sh"], cwd=td, capture_output=True, text=True, timeout=30
        )
        log = Path(td, "curl.log").read_text()
    assert out.returncode == 0, out.stderr
    vals = dict(line.split("=", 1) for line in out.stdout.splitlines() if "=" in line)
    return vals, log


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------


def test_in_sync_proxy_is_verified_with_nothing_unroutable() -> None:
    vals, _ = _run_probe(_error(ROUTED_ALL))
    assert vals["SUM_ROUTING_STATE"] == "verified"
    assert vals["SUM_UNROUTABLE_COUNT"] == "0"


def test_stale_routing_table_is_detected() -> None:
    vals, _ = _run_probe(_error(ROUTED_STALE))
    assert vals["SUM_ROUTING_STATE"] == "verified"
    # claudeopus55 (both aliases missing) + embed9.
    assert vals["SUM_UNROUTABLE_COUNT"] == "2"
    assert set(vals["INTERNAL"].split()) == {"claudeopus55", "embed9"}


def test_unroutable_list_names_the_models() -> None:
    vals, _ = _run_probe(_error(ROUTED_STALE))
    assert set(vals["INTERNAL"].split()) == {"claudeopus55", "embed9"}
    assert "claude" in vals["SUM_UNROUTABLE_LIST"]


def test_a_model_is_routable_if_any_alias_routes() -> None:
    """sonnetx has one routed alias of two; it must not be reported."""
    vals, _ = _run_probe(_error(ROUTED_STALE))
    assert "sonnetx" not in vals["INTERNAL"].split()


def test_chat_count_excludes_embeddings() -> None:
    """gather_summary subtracts this from SUM_MODEL_UNIQ_COUNT, which already
    drops embeddings -- the two must be like for like."""
    vals, _ = _run_probe(_error(ROUTED_STALE))
    assert vals["SUM_UNROUTABLE_CHAT_COUNT"] == "1"


# ---------------------------------------------------------------------------
# Fail toward "unverified"
# ---------------------------------------------------------------------------


def test_reworded_upstream_message_is_unverified_not_routable() -> None:
    reworded = json.dumps({"error": {"message": "No such model. Available: argo:gpt-4o"}})
    vals, _ = _run_probe(reworded)
    assert vals["SUM_ROUTING_STATE"] == "unverified"
    assert vals["SUM_UNROUTABLE_COUNT"] == "0"


def test_no_response_is_unverified() -> None:
    vals, _ = _run_probe("")
    assert vals["SUM_ROUTING_STATE"] == "unverified"


def test_a_successful_completion_is_unverified() -> None:
    """If a future proxy stops 404ing and answers instead, we must not read
    the absence of an error as 'everything routes'."""
    vals, _ = _run_probe(json.dumps({"type": "message", "content": []}))
    assert vals["SUM_ROUTING_STATE"] == "unverified"


def test_empty_configured_list_is_unverified() -> None:
    vals, _ = _run_probe(_error([]))
    assert vals["SUM_ROUTING_STATE"] == "unverified"


def test_missing_models_body_is_unverified_and_skips_the_probe() -> None:
    vals, log = _run_probe(_error(ROUTED_ALL), body="")
    assert vals["SUM_ROUTING_STATE"] == "unverified"
    assert log == ""


def test_missing_jq_is_unverified_and_skips_the_probe() -> None:
    vals, log = _run_probe(_error(ROUTED_STALE), no_jq=True)
    assert vals["SUM_ROUTING_STATE"] == "unverified"
    assert "jq" in vals["SUM_ROUTING_REASON"]
    assert log == ""


# ---------------------------------------------------------------------------
# Safety: which endpoint, and nothing mutating
# ---------------------------------------------------------------------------


def test_probe_goes_through_the_anthropic_path() -> None:
    _, log = _run_probe(_error(ROUTED_ALL))
    assert "/v1/messages" in log


def test_probe_never_uses_the_fuzzy_matching_openai_path() -> None:
    """The OpenAI path turns a bogus id into a billed real completion."""
    _, log = _run_probe(_error(ROUTED_ALL))
    assert "/v1/chat/completions" not in log
    fn = _code_only(_function_body(_engine_source(), "_probe_proxy_routing"))
    assert "chat/completions" not in fn


def test_probe_bounds_max_tokens() -> None:
    _, log = _run_probe(_error(ROUTED_ALL))
    assert '"max_tokens":1' in log


def test_probe_makes_exactly_one_request_and_never_refreshes() -> None:
    _, log = _run_probe(_error(ROUTED_STALE))
    assert len(log.strip().splitlines()) == 1
    assert "/refresh" not in log


def test_probe_model_id_cannot_collide_with_a_real_model() -> None:
    src = _engine_source()
    m = re.search(r'^_ROUTING_PROBE_MODEL="([^"]+)"', src, re.M)
    assert m and "nonexistent" in m.group(1) and not m.group(1).startswith("argo:")


# ---------------------------------------------------------------------------
# Wiring
# ---------------------------------------------------------------------------


def test_gather_summary_probes_before_the_cross_reference() -> None:
    body = _code_only(_function_body(_engine_source(), "gather_summary"))
    probe = body.find("_probe_proxy_routing")
    xref = body.find("SUM_CFG_AVAIL_COUNT=\"$(comm")
    assert probe != -1 and xref != -1 and probe < xref


def test_list_models_probes() -> None:
    body = _code_only(_function_body(_engine_source(), "mode_list_models"))
    assert "_probe_proxy_routing" in body


def test_read_only_verbs_do_not_repair() -> None:
    """status/list-models report; only mutating verbs /refresh (D-034)."""
    src = _engine_source()
    for fn in ("gather_summary", "render_summary", "mode_status", "mode_list_models",
               "_probe_proxy_routing"):
        assert "_refresh_proxy_model_routing" not in _code_only(_function_body(src, fn)), fn


def test_list_models_warning_goes_to_stderr_not_the_table() -> None:
    """tsv/json consumers must see an unchanged schema."""
    body = _code_only(_function_body(_engine_source(), "mode_list_models"))
    block = body[body.find("_probe_proxy_routing") : body.find("annotated_json=")]
    assert "warn " in block and "printf" not in block


# ---------------------------------------------------------------------------
# gather_summary: "reachable" means routable
# ---------------------------------------------------------------------------


def _gather(routed: list[str]) -> dict[str, str]:
    src = _engine_source()
    pieces = "\n".join(
        _function_body(src, n)
        for n in (
            "fetch_proxy_models",
            "extract_available_internal_names",
            "extract_configured_internal_names",
            "_probe_proxy_routing",
            "gather_summary",
        )
    )
    harness = textwrap.dedent(
        """
        set -euo pipefail
        PROXY_PORT=64999
        NODE_CACHE="$PWD/node"
        OPENCODE_CONFIG="$PWD/opencode.json"
        _ROUTING_PROBE_MODEL="argo-anywhere-routing-probe-nonexistent"
        lsof() {{ :; }}
        local_tunnel_destination() {{ :; }}
        curl() {{
          case "$*" in
            */health*) echo ok ;;
            */v1/models*) cat "$PWD/models.json" ;;
            */v1/messages*) cat "$PWD/resp.txt" ;;
          esac
        }}
        {pieces}
        gather_summary
        for v in SUM_ROUTING_STATE SUM_UNROUTABLE_COUNT SUM_MODEL_UNIQ_COUNT \\
                 SUM_MODEL_ROUTABLE_UNIQ_COUNT SUM_CFG_COUNT SUM_CFG_AVAIL_COUNT \\
                 SUM_CFG_UNROUTABLE_COUNT SUM_CFG_ORPHAN_COUNT; do
          printf '%s=%s\\n' "$v" "${{!v}}"
        done
        """
    ).format(pieces=pieces)
    cfg = {"provider": {"argo": {"models": {"gpt4o": {}, "claudeopus55": {}, "sonnetx": {}}}}}
    with tempfile.TemporaryDirectory() as td:
        Path(td, "models.json").write_text(json.dumps(MODELS))
        Path(td, "resp.txt").write_text(_error(routed))
        Path(td, "opencode.json").write_text(json.dumps(cfg))
        Path(td, "h.sh").write_text(harness)
        out = subprocess.run(
            ["bash", "h.sh"], cwd=td, capture_output=True, text=True, timeout=30
        )
    assert out.returncode == 0, out.stderr
    return dict(line.split("=", 1) for line in out.stdout.splitlines() if "=" in line)


def test_gather_in_sync_counts_every_configured_model() -> None:
    v = _gather(ROUTED_ALL)
    assert v["SUM_CFG_AVAIL_COUNT"] == "3"
    assert v["SUM_CFG_UNROUTABLE_COUNT"] == "0"
    assert v["SUM_MODEL_ROUTABLE_UNIQ_COUNT"] == v["SUM_MODEL_UNIQ_COUNT"]


def test_gather_stale_stops_counting_unroutable_as_reachable() -> None:
    """The 2026-10-26 overclaim: '37 configured (37 reachable)' over 404s."""
    v = _gather(ROUTED_STALE)
    assert v["SUM_ROUTING_STATE"] == "verified"
    assert v["SUM_CFG_COUNT"] == "3"
    assert v["SUM_CFG_AVAIL_COUNT"] == "2"
    assert v["SUM_CFG_UNROUTABLE_COUNT"] == "1"
    # Unroutable is not "orphaned": it IS in /v1/models.
    assert v["SUM_CFG_ORPHAN_COUNT"] == "0"
    assert int(v["SUM_MODEL_ROUTABLE_UNIQ_COUNT"]) == int(v["SUM_MODEL_UNIQ_COUNT"]) - 1


# ---------------------------------------------------------------------------
# render_summary
# ---------------------------------------------------------------------------


def _render(state: str, unroutable: int, reason: str = "") -> str:
    src = _engine_source()
    glyphs = re.search(
        r'^if \[ "\$BOX_STYLE" = "unicode" \]; then\n.*?^fi$', src, re.M | re.S
    )
    assert glyphs
    pieces = "\n".join(
        [glyphs.group(0)]
        + [
            _function_body(src, n)
            for n in ("repeat_str", "visible_width", "print_summary_box", "render_summary")
        ]
    )
    harness = textwrap.dedent(
        """
        set -uo pipefail
        C_GRN=""; C_YLW=""; C_RED=""; C_DIM=""; C_BLU=""; C_OFF=""
        BOX_STYLE=ascii; PROXY_PORT=64751; ANL_JUMP=logins.cels.anl.gov
        OPENCODE_CONFIG="$PWD/opencode.json"; echo '{{}}' > "$OPENCODE_CONFIG"
        CLAUDECODE_GLOBAL_CONFIG="$PWD/x"; AIDER_GLOBAL_CONFIG="$PWD/y"
        STATE_DIR="$PWD/state"; USER_CACHE="$STATE_DIR/u"; NODE_CACHE="$STATE_DIR/n"
        REMOTE_LOG=log
        on_anl_compute_node() {{ echo no; }}
        _opencode_legacy_name_only() {{ return 1; }}
        _user_cmd_name() {{ echo argo-anywhere; }}
        SUM_LISTENER_OK=1; SUM_LISTENER_PID=""; SUM_LISTENER_BIND="127.0.0.1:64751"
        SUM_HEALTH_OK=1; SUM_MODELS_OK=1; SUM_MODEL_COUNT=57; SUM_MODEL_UNIQ_COUNT=37
        SUM_MODEL_ROUTABLE_UNIQ_COUNT=$((37 - {unr})); SUM_MODEL_SAMPLE="argo:gpt-4o"
        SUM_CFG_COUNT=37; SUM_CFG_AVAIL_COUNT=$((37 - {unr})); SUM_CFG_UNROUTABLE_COUNT={unr}
        SUM_CFG_ORPHAN_COUNT=0; SUM_CFG_ORPHAN_LIST=""
        SUM_TUNNEL_DEST=""; SUM_DEST_MATCHES_CACHE=""
        SUM_ROUTING_STATE={state}; SUM_ROUTING_REASON="{reason}"
        SUM_UNROUTABLE_COUNT={unr}; SUM_UNROUTABLE_LIST="argo:claude-opus-5.5"
        {pieces}
        render_summary
        """
    ).format(state=state, unr=unroutable, reason=reason, pieces=pieces)
    with tempfile.TemporaryDirectory() as td:
        Path(td, "r.sh").write_text(harness)
        out = subprocess.run(
            ["bash", "r.sh"], cwd=td, capture_output=True, text=True, timeout=30
        )
    assert out.returncode == 0, out.stderr
    return out.stderr


def test_render_stale_routing_is_not_green() -> None:
    box = _render("verified", 4)
    assert "ALL GREEN" not in box
    assert "CHECK" in box and "NOT routable" in box


def test_render_stale_routing_names_models_and_the_repair() -> None:
    box = _render("verified", 4)
    assert "argo:claude-opus-5.5" in box
    assert "/refresh" in box
    assert "33 routable" in box
    assert "Run  'opencode'" not in box


def test_render_verified_in_sync_says_routable() -> None:
    box = _render("verified", 0)
    assert "ALL GREEN" in box
    assert "37 configured (37 routable)" in box
    assert "reachable)" not in box


def test_render_unverified_does_not_claim_routable() -> None:
    box = _render("unverified", 0, reason="proxy did not disclose its routing table")
    assert "routing unverified" in box
    assert "Routable         : unverified" in box
    assert "37 routable" not in box
