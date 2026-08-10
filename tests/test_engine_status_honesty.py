"""Tests for ``status`` honesty (Defect 3, Tier 1 item 3).

``gather_summary`` sets its verdict from three probes that all run on the
LAPTOP -- a listener on our port, ``/health``, ``/v1/models`` -- and
``render_summary`` ANDs them into ``ALL GREEN``. None of them identifies the
process on the far end of the tunnel, yet the card printed ``Cached node:
<name>`` straight from ``$NODE_CACHE`` (a string written at the last
successful connect and never re-checked), which made the whole thing read as
a claim about that specific node.

In the 2026-08-10 incident the card was individually truthful about every
probe it ran and still misled, because the reader's actual question -- "am I
talking to my proxy on my node?" -- was not among them.

The fix surfaces ``local_tunnel_destination`` (ground truth, read from the
listener's own ControlPath socket; it already backed the P3 misroute refusal
but was never shown), relabels the cached row as last-connected, downgrades a
destination mismatch to ``CHECK``, and states the limit of the verdict.

Full analysis: ``notes/impl_shared_node_transport.md`` S2.3.
"""

from __future__ import annotations

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
    match = re.search(
        rf"^{re.escape(name)}\(\)\s*\{{.*?^\}}", src, re.MULTILINE | re.DOTALL
    )
    assert match, f"{name} definition not found in engine"
    return match.group(0)


# ---------------------------------------------------------------------------
# gather_summary: the destination must actually be collected
# ---------------------------------------------------------------------------


def test_gather_summary_records_the_tunnel_destination() -> None:
    """``gather_summary`` must call ``local_tunnel_destination``.

    The helper existed since the P3 audit fix but had exactly one caller
    (``ensure_or_reuse_tunnel``), so ``status`` had ground truth available and
    never used it.
    """
    body = _function_body(_engine_source(), "gather_summary")
    assert "local_tunnel_destination" in body, (
        "gather_summary must read the real tunnel destination, not leave the "
        "cached node to imply it"
    )
    assert "SUM_TUNNEL_DEST=" in body


def test_summary_globals_are_reset_each_call() -> None:
    """Both new globals must be reset at the top of ``gather_summary``.

    ``mode_status`` and ``mode_update_models`` both call it, and a stale
    ``SUM_DEST_MATCHES_CACHE=no`` leaking into a later render would downgrade
    a perfectly healthy card.
    """
    body = _function_body(_engine_source(), "gather_summary")
    head = body[: body.index("# Listener")]
    assert 'SUM_TUNNEL_DEST=""' in head, "SUM_TUNNEL_DEST must be reset"
    assert 'SUM_DEST_MATCHES_CACHE=""' in head, (
        "SUM_DEST_MATCHES_CACHE must be reset"
    )


def test_destination_is_only_probed_when_a_listener_exists() -> None:
    """No listener means no ControlPath to read; don't pretend otherwise."""
    body = _function_body(_engine_source(), "gather_summary")
    # The assignment (not the mention in the comment block) must be preceded
    # by a listener-present guard with nothing but the guard between them.
    assign = body.index('SUM_TUNNEL_DEST="$(local_tunnel_destination')
    guard = body[:assign].rindex('if [ "$SUM_LISTENER_OK" -eq 1 ]; then')
    between = body[guard:assign]
    assert between.count("\n") <= 2, (
        "the destination probe must sit directly inside the listener guard; "
        f"found {between.count(chr(10))} lines between them"
    )


def test_mismatch_is_three_valued_not_boolean() -> None:
    """``SUM_DEST_MATCHES_CACHE`` must distinguish unknown from mismatch.

    Empty (unknown) is the common, benign case: on-node local mode, a
    foreground tunnel with no ControlPath, or a first run with no cache. Only
    an explicit ``no`` is a real disagreement. Collapsing unknown into "no"
    would fire a scary CHECK verdict at users with nothing wrong.
    """
    body = _function_body(_engine_source(), "gather_summary")
    assert "SUM_DEST_MATCHES_CACHE=yes" in body
    assert "SUM_DEST_MATCHES_CACHE=no" in body
    # The 'no' assignment must be reachable only when we HAVE a destination
    # and a cached value to compare it against.
    seg = body[body.index("local_tunnel_destination") :]
    assert '[ -n "$SUM_TUNNEL_DEST" ]' in seg
    assert "$NODE_CACHE" in seg


# ---------------------------------------------------------------------------
# render_summary: the verdict must not overclaim
# ---------------------------------------------------------------------------


def test_all_green_no_longer_claims_a_tunnel_it_did_not_verify() -> None:
    """The green verdict must describe the endpoint, not assert "tunnel up".

    Old wording: "ALL GREEN - tunnel up, proxy healthy, N model(s)". "tunnel
    up" is precisely the part the probes cannot establish.
    """
    body = _function_body(_engine_source(), "render_summary")
    assert 'verdict="ALL GREEN  -  endpoint healthy' in body, (
        "green verdict should claim only what was probed"
    )
    assert "ALL GREEN  -  tunnel up" not in body, (
        "the old overclaiming wording must not come back"
    )


def test_destination_mismatch_downgrades_the_verdict() -> None:
    """A mismatch must render as CHECK, not green.

    It is not necessarily an error -- the user may have deliberately pointed
    elsewhere -- but it must never be unqualified green while the
    Configuration section prints a different (cached) node, or the card
    contradicts itself.
    """
    body = _function_body(_engine_source(), "render_summary")
    verdict_block = body[body.index("# Verdict") : body.index("# Body lines")]
    assert 'SUM_DEST_MATCHES_CACHE" = "no"' in verdict_block, (
        "mismatch must be considered when computing the verdict"
    )
    assert 'verdict="CHECK' in verdict_block
    # And it must be tested BEFORE the ALL GREEN branch, or it can never win.
    # Compare the actual assignments, not prose in the comment block above.
    assert verdict_block.index('verdict="CHECK') < verdict_block.index(
        'verdict="ALL GREEN'
    ), "the mismatch branch must precede the green branch"


def test_cached_node_row_is_labelled_as_not_verified() -> None:
    """The cached row must not read as a live claim.

    "Cached node: X" was read as "you are talking to X". It never meant that.
    """
    body = _function_body(_engine_source(), "render_summary")
    assert "Last connected to" in body
    assert "not re-verified" in body
    assert 'lines+=("Cached node      : ' not in body, (
        "the bare 'Cached node' row implied a live fact; it should be relabelled"
    )


def test_connection_section_shows_the_real_destination() -> None:
    """A 'Tunnel goes to' row must appear alongside the local probes."""
    body = _function_body(_engine_source(), "render_summary")
    assert "Tunnel goes to" in body
    # All three cases must be represented: known, on-node (no tunnel), unknown.
    seg = body[body.index("Tunnel goes to") - 800 : body.index("Tunnel goes to") + 400]
    assert "on_anl_compute_node" in seg, "on-node local mode needs its own wording"
    assert "unknown" in seg, "an unreadable ControlPath must say unknown"


def test_verdict_scope_is_stated_to_the_user() -> None:
    """The card must name what it did NOT verify.

    Without this the reader has no way to know the green verdict is
    laptop-local. The engine answers the identity question at bootstrap
    (_listener_is_ours); status cannot, without an SSH round trip per call.
    """
    body = _function_body(_engine_source(), "render_summary")
    assert "Checks above are local" in body
    assert "whose argo-proxy is behind it" in body


def test_scope_note_is_suppressed_on_node() -> None:
    """On a compute node there is no tunnel, so the caveat would be nonsense."""
    body = _function_body(_engine_source(), "render_summary")
    idx = body.index("Checks above are local")
    guard = body[:idx].rindex("if [")
    assert "on_anl_compute_node" in body[guard:idx], (
        "the local-checks caveat must be skipped in on-node mode"
    )


def test_scope_rationale_is_documented() -> None:
    """Keep the reasoning next to the verdict logic."""
    body = _function_body(_engine_source(), "render_summary")
    assert "SCOPE NOTE" in body


# ---------------------------------------------------------------------------
# Behaviour: render the real box
# ---------------------------------------------------------------------------


def _render(dest: str, cached: str, *, listener: int = 1, health: int = 1) -> str:
    """Drive the ENGINE'S OWN render_summary with stubbed inputs.

    Sources the real function (plus the box printer it calls) and supplies the
    SUM_* globals directly, so this exercises the shipped rendering logic
    without a tunnel, a node, or any network.
    """
    src = _engine_source()
    # The box glyph constants are a top-level block, not a function; extract
    # them from the engine too rather than duplicating the glyphs here.
    glyphs = re.search(
        r'^if \[ "\$BOX_STYLE" = "unicode" \]; then\n.*?^fi$',
        src,
        re.MULTILINE | re.DOTALL,
    )
    assert glyphs, "box glyph block not found"
    pieces = [
        glyphs.group(0),
        _function_body(src, "repeat_str"),
        _function_body(src, "visible_width"),
        _function_body(src, "print_summary_box"),
        _function_body(src, "render_summary"),
    ]
    harness = textwrap.dedent(
        """
        set -uo pipefail
        C_GRN=""; C_YLW=""; C_RED=""; C_DIM=""; C_BLU=""; C_OFF=""
        ARGO_BOX_STYLE=ascii
        BOX_STYLE=ascii
        PROXY_PORT=64751
        ANL_JUMP=logins.cels.anl.gov
        OPENCODE_CONFIG="$PWD/opencode.json"
        CLAUDECODE_CONFIG="$PWD/claude.json"
        CLAUDECODE_GLOBAL_CONFIG="$PWD/claude-global.json"
        AIDER_CONFIG="$PWD/aider.yml"
        AIDER_GLOBAL_CONFIG="$PWD/aider-global.yml"
        STATE_DIR="$PWD/state"; mkdir -p "$STATE_DIR"
        USER_CACHE="$STATE_DIR/user"; NODE_CACHE="$STATE_DIR/node"
        REMOTE_LOG=".argo-anywhere.server.log"
        echo "testuser" > "$USER_CACHE"
        printf '%s\\n' "{cached}" > "$NODE_CACHE"
        on_anl_compute_node() {{ echo no; }}
        log() {{ :; }}; warn() {{ :; }}; err() {{ :; }}; ok() {{ :; }}
        SUM_LISTENER_OK={listener}; SUM_LISTENER_PID=$$; SUM_LISTENER_BIND="127.0.0.1:64751"
        SUM_HEALTH_OK={health}
        SUM_MODELS_OK=1; SUM_MODEL_COUNT=51; SUM_MODEL_UNIQ_COUNT=40
        SUM_MODEL_SAMPLE="argo:gpt-4o"
        SUM_CFG_COUNT=0; SUM_CFG_AVAIL_COUNT=0
        SUM_CFG_ORPHAN_COUNT=0; SUM_CFG_ORPHAN_LIST=""
        SUM_TUNNEL_DEST="{dest}"
        SUM_DEST_MATCHES_CACHE="{matches}"
        {pieces}
        render_summary
        """
    ).format(
        cached=cached,
        dest=dest,
        listener=listener,
        health=health,
        matches=("" if not dest else ("yes" if dest == cached else "no")),
        pieces="\n".join(pieces),
    )
    with tempfile.TemporaryDirectory() as td:
        script = Path(td) / "r.sh"
        script.write_text(harness)
        out = subprocess.run(
            ["bash", str(script)], cwd=td, capture_output=True, text=True, timeout=30
        )
    assert out.returncode == 0, f"render failed: {out.stderr}"
    # print_summary_box writes the card to STDERR (it is a status display, not
    # pipeline data), so the assertions below read stderr.
    return out.stderr


def test_render_matching_destination_is_green_and_shows_the_node() -> None:
    """The happy path still reads green, and now names the verified far end."""
    box = _render("compute-01.cels.anl.gov", "compute-01.cels.anl.gov")
    assert "ALL GREEN" in box
    assert "Tunnel goes to" in box
    assert "matches cached node" in box
    assert "Last connected to" in box
    # The green card must still carry the scope caveat.
    assert "Checks above are local" in box


def test_render_mismatched_destination_is_not_green() -> None:
    """The misroute case: healthy endpoint, wrong node -> CHECK, not green."""
    box = _render("compute-09.cels.anl.gov", "compute-01.cels.anl.gov")
    assert "ALL GREEN" not in box, (
        "a tunnel pointing somewhere other than the cached node must not "
        "render as unqualified green"
    )
    assert "CHECK" in box
    assert "compute-09.cels.anl.gov" in box
    assert "DIFFERS from cached node" in box
    # And the Configuration section must explain the disagreement in place.
    assert "the live tunnel goes to compute-09.cels.anl.gov instead" in box


def test_render_unknown_destination_stays_green() -> None:
    """Unknown is benign: a healthy endpoint we simply can't attribute.

    Firing CHECK here would cry wolf at every user whose listener has no
    readable ControlPath.
    """
    box = _render("", "compute-01.cels.anl.gov")
    assert "ALL GREEN" in box
    assert "unknown" in box
    assert "CHECK" not in box
