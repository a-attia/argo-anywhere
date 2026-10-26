"""Tests for the ROUTING-TABLE FRESHNESS invariant (``_refresh_proxy_model_routing``).

``argo-proxy`` keeps **two** model tables and its periodic refresh updates
only one of them (measured 2026-10-26 against ``argo-proxy 3.3.3`` /
``llm-rosetta 0.13.0``)::

    ModelRegistry        -> serves GET /v1/models      -> refreshed every 24h
    GatewayConfig.models -> decides REQUEST ROUTING    -> never auto-refreshed

``rebuild_gateway_models()`` (``argoproxy/bridge.py``) has exactly one caller:
the manual ``/refresh`` endpoint. The background task
(``ModelRegistry._periodic_refresh``) calls ``refresh_availability()`` alone.
So a long-running proxy **advertises models it then 404s on** -- its routing
table is frozen at process-start.

Observed live: four Claude 5.5 ids were listed by ``/v1/models`` while every
request against them returned::

    HTTP 404  Unknown model: 'argo:claude-opus-5.5'. Configured models: ...

with all six 5.5 aliases absent from that ``Configured models:`` list and
everything else present.

This matters to the engine because **every model surface reads /v1/models** --
the lying table. ``gather_summary`` reported ``ALL GREEN ... 37 configured
(37 reachable)`` over those 404s, which is the overclaim D-034 ("evidence,
not reachability") exists to prevent, and ``_opencode_models_block`` would
write the unroutable ids into a user's config.

We cannot *detect* the split-brain from ``/v1/models``, so we repair it
opportunistically: POST ``/refresh`` on the paths that either report model
state or write it.

The contract under test:

1. **Never dies** -- no channel / no curl / no ``/refresh`` endpoint /
   timeout must all degrade to a silent no-op. It runs mid-connect; model
   housekeeping is never a reason to fail a channel.
2. **Silent on success** -- it fires on every connect and configure.
3. **Wired into the paths that matter** -- ``mode_tunnel`` (connect),
   ``_configure_ensure_channel_or_die`` (configure/run, both branches), and
   ``mode_update_models``.
4. **Ordered before the read** -- repairing after ``gather_summary`` or after
   ``fetch_proxy_models`` would describe/persist the stale table.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

from argo_anywhere._engine import engine_path


def _engine_source() -> str:
    with engine_path() as script:
        return script.read_text()


def _function_body(src: str, name: str) -> str:
    lines = src.splitlines()
    start = next(
        (i for i, line in enumerate(lines) if line.startswith(f"{name}() {{")),
        None,
    )
    assert start is not None, f"{name} definition not found in engine"
    for idx in range(start + 1, len(lines)):
        if lines[idx] == "}":
            return "\n".join(lines[start : idx + 1])
    raise AssertionError(f"unterminated function body for {name}")


def _run_refresh(tmp_path: Path, *, curl_script: str | None) -> subprocess.CompletedProcess:
    """Run the real ``_refresh_proxy_model_routing`` under bash.

    ``curl_script`` is the body of a stub ``curl`` on PATH; ``None`` means
    curl is absent entirely. Runs under ``set -euo pipefail`` to match the
    engine, so any non-zero leak surfaces as a failure.
    """
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    if curl_script is not None:
        curl = bindir / "curl"
        curl.write_text("#!/bin/sh\n" + curl_script + "\n")
        curl.chmod(0o755)

    script = tmp_path / "drive.sh"
    script.write_text(
        "set -euo pipefail\n"
        'PATH="%s"\n' % bindir
        + "PROXY_PORT=64743\n"
        + _function_body(_engine_source(), "_refresh_proxy_model_routing")
        + "\n_refresh_proxy_model_routing\n"
         "echo \"RC=$?\"\n"
    )
    return subprocess.run(
        ["bash", str(script)], capture_output=True, text=True, timeout=30
    )


# --------------------------------------------------------------------------
# Rule 1: never dies, whatever the channel does.
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("label", "curl_script"),
    [
        ("healthy /refresh", "exit 0"),
        # Pre-/refresh argo-proxy: endpoint absent. curl -fsS exits 22 on 404.
        ("endpoint absent (404)", "exit 22"),
        ("no channel (conn refused)", "exit 7"),
        ("timeout", "exit 28"),
        ("curl killed by signal", "kill -TERM $$"),
        ("garbage on stdout", "echo '<html>not json</html>'; exit 0"),
        ("noise on stderr", "echo boom >&2; exit 1"),
    ],
)
def test_refresh_never_fails_the_caller(
    tmp_path: Path, label: str, curl_script: str
) -> None:
    """Every channel outcome degrades to a clean return 0.

    This function runs inside ``connect`` and ``configure`` under
    ``set -euo pipefail``. A non-zero return would abort a channel the user
    actually asked for, to fix a model list they did not mention.
    """
    proc = _run_refresh(tmp_path, curl_script=curl_script)
    assert proc.returncode == 0, f"{label}: engine aborted\n{proc.stderr}"
    assert "RC=0" in proc.stdout, f"{label}: non-zero return\n{proc.stdout}"


def test_refresh_survives_curl_being_absent(tmp_path: Path) -> None:
    """No curl on PATH -> no-op, not an unbound-command abort."""
    proc = _run_refresh(tmp_path, curl_script=None)
    assert proc.returncode == 0, proc.stderr
    assert "RC=0" in proc.stdout


# --------------------------------------------------------------------------
# Rule 2: silent on success.
# --------------------------------------------------------------------------


def test_refresh_is_silent(tmp_path: Path) -> None:
    """It fires on every connect/configure; a line per run is noise.

    It also has nothing honest to say: ``/refresh`` reports before/after
    counts for the *registry*, the table that was already correct. The
    2026-10-26 repair that fixed four 404ing models returned an unchanged
    ``57 -> 57`` because the real change landed in the unreported gateway
    table.
    """
    body = '{"status":"refreshed","before":{"total_aliases":57},"after":{"total_aliases":57}}'
    proc = _run_refresh(tmp_path, curl_script=f"echo '{body}'; exit 0")
    assert proc.stdout.strip() == "RC=0", f"unexpected chatter: {proc.stdout!r}"
    assert proc.stderr.strip() == "", f"unexpected stderr: {proc.stderr!r}"


def test_refresh_posts_to_the_refresh_endpoint(tmp_path: Path) -> None:
    """Sanity: it really POSTs /refresh on the configured port."""
    argv_log = tmp_path / "argv.log"
    proc = _run_refresh(
        tmp_path,
        curl_script=f'printf "%s\\n" "$*" >> {argv_log}; exit 0',
    )
    assert proc.returncode == 0, proc.stderr
    recorded = argv_log.read_text()
    assert "-X POST" in recorded, recorded
    assert "http://localhost:64743/refresh" in recorded, recorded
    # Bounded: this runs in the middle of an interactive flow.
    assert "--max-time" in recorded, recorded


# --------------------------------------------------------------------------
# Rule 3 + 4: wired in, and ordered before the read.
# --------------------------------------------------------------------------


def _code_only(body: str) -> str:
    """Strip comment lines so ordering/containment assertions see real calls.

    Without this the prose in the ROUTING-TABLE FRESHNESS comments (which
    names ``gather_summary`` and the other call sites) satisfies the
    assertions on its own -- the tests would pass with the calls deleted.
    """
    return "\n".join(
        line for line in body.splitlines() if not line.lstrip().startswith("#")
    )


def _callers(src: str) -> dict[str, str]:
    return {
        name: _function_body(src, name)
        for name in (
            "mode_tunnel",
            "_configure_ensure_channel_or_die",
            "mode_update_models",
        )
    }


@pytest.mark.parametrize(
    "caller",
    ["mode_tunnel", "_configure_ensure_channel_or_die", "mode_update_models"],
)
def test_refresh_is_wired_into_model_surfaces(caller: str) -> None:
    """connect, configure/run and update-models all repair before reporting."""
    body = _code_only(_callers(_engine_source())[caller])
    assert "_refresh_proxy_model_routing" in body, (
        f"{caller} no longer refreshes the routing table; a stale proxy will "
        "advertise models it 404s on, and this surface will restate that as fact"
    )


def test_configure_refreshes_on_the_reuse_branch() -> None:
    """The reuse branch is the one that matters most.

    ``configure`` against an already-up channel is the common case, and that
    proxy may have been running for days -- the most likely to be stale,
    and the writers are about to bake ``/v1/models`` into a user's config.
    """
    body = _code_only(
        _function_body(_engine_source(), "_configure_ensure_channel_or_die")
    )
    # Split on the dedented closing `fi` of the channel_is_up block, not a
    # bare "fi" (which also matches inside words like "config").
    reuse = body.split("if channel_is_up; then", 1)[1].split("\n  fi", 1)[0]
    assert "_refresh_proxy_model_routing" in reuse, (
        "the channel-reuse branch must refresh; it is the staleness-prone path"
    )


def test_tunnel_refreshes_before_gather_summary() -> None:
    """Order matters: refreshing after the read would describe the stale table."""
    body = _code_only(_function_body(_engine_source(), "mode_tunnel"))
    assert body.index("_refresh_proxy_model_routing") < body.index("gather_summary"), (
        "refresh must precede gather_summary, else the status box reports "
        "reachability counts taken from the pre-repair model list"
    )


def test_update_models_refreshes_before_fetching() -> None:
    """``update-models`` persists the list, so it must repair before reading."""
    body = _code_only(_function_body(_engine_source(), "mode_update_models"))
    assert body.index("_refresh_proxy_model_routing") < body.index(
        "fetch_proxy_models"
    ), (
        "refresh must precede fetch_proxy_models, else unroutable model ids "
        "get written into the user's config"
    )


def test_quiet_and_loud_refreshers_stay_distinct() -> None:
    """``_update_argoproxy_post_refresh`` is the loud sibling; keep it loud.

    It runs only after an ``update argoproxy`` upgrade, where the user asked
    for a change and wants to know what happened. Collapsing the two would
    either make connect chatty or make upgrades silent.
    """
    src = _engine_source()
    loud = _function_body(src, "_update_argoproxy_post_refresh")
    quiet = _function_body(src, "_refresh_proxy_model_routing")
    assert "/refresh" in loud and "/refresh" in quiet
    assert re.search(r"\b(ok|log|warn)\b", loud), "the upgrade path should report"
    assert not re.search(r"^\s*(ok|log|warn|err) ", quiet, re.M), (
        "the opportunistic path must stay silent"
    )
