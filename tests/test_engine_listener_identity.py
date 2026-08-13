"""Tests for the identity-before-success invariant (Defect 4).

``mode_server``'s post-launch wait used to accept any ``/health`` 200 on the
node's loopback as proof that the argo-proxy *it had just launched* came up.
On a shared compute node that is not proof of anything: another user's
argo-proxy holding the same port answers ``/health`` identically -- it is the
same software. In the 2026-08-10 field incident our proxy hung at a port
prompt, a co-tenant's proxy satisfied the wait, ``mode_server`` reported
success, and the client tunnelled into a stranger's process while the summary
box printed ALL GREEN.

The fix is ``_listener_is_ours``, which exploits an asymmetry of unprivileged
``lsof`` on Linux: a process we own is attributable (pid + owner), another
user's socket is not (empty output). Confirmed on the live node 2026-08-10 --
our ``:64751`` returned our pid and username while a co-tenant's ``:64742``
answered ``/health`` with an empty ``lsof -t``.

The helper is **fail-closed**: every uncertain outcome (no lsof, pid gone,
unknown owner) returns "not ours". Returning "ours" on uncertainty would
reopen the exact misattachment it exists to prevent, so that property is
pinned hard below.

Full analysis: ``notes/impl_shared_node_transport.md`` S2.4 (Defect 4) and its
S6 sequencing, Tier 1 item 2.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import textwrap
from pathlib import Path

import pytest

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


def _function_block(src: str, name: str) -> str:
    """Function body plus the contiguous comment block documenting it.

    The rationale for these helpers lives in comments *above* the definition
    (engine house style), so tests asserting on documentation must look at the
    block, not just the body.
    """
    body = _function_body(src, name)
    before = src[: src.index(body)]
    lines = before.splitlines()
    comment: list[str] = []
    for line in reversed(lines):
        if line.startswith("#"):
            comment.append(line)
        else:
            break
    return "\n".join(reversed(comment)) + "\n" + body


def _run_helper_harness(body: str) -> subprocess.CompletedProcess[str]:
    """Run a bash harness with ``_listener_is_ours`` sourced from the engine.

    The function is extracted from the real engine rather than reimplemented,
    so these tests cannot drift from the shipped code.
    """
    helper = _function_body(_engine_source(), "_listener_is_ours")
    harness = "set -uo pipefail\n" + helper + "\n" + textwrap.dedent(body)
    with tempfile.TemporaryDirectory() as td:
        script = Path(td) / "h.sh"
        script.write_text(harness)
        return subprocess.run(
            ["bash", str(script)],
            cwd=td,
            capture_output=True,
            text=True,
            timeout=60,
            env={
                "HOME": td,
                "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                "TMPDIR": td,
            },
        )


# ---------------------------------------------------------------------------
# Contract shape
# ---------------------------------------------------------------------------


def _wait_loop(src: str) -> str:
    """Extract ``mode_server``'s post-launch wait loop verbatim.

    The engine has three ``/health`` waits and the two tunnel-side ones look
    almost identical, so ``local waited=0`` alone is ambiguous -- it silently
    matched the wrong loop while writing this.

    The anchor is deliberately NOT ``_listener_is_ours``, even though that
    would disambiguate: the first version used it, and deleting the identity
    check (the mutation these tests exist to catch) then made the *extractor*
    raise instead of the assertions failing. Every test "failed", but for the
    wrong reason -- which would equally have "passed" the revert-check for a
    mutation that broke something else entirely. ``Server bootstrap failed.``
    is unique to this loop and independent of the property under test.
    """
    lines = src.splitlines()
    anchor = next(
        i for i, line in enumerate(lines) if 'die "Server bootstrap failed."' in line
    )
    start = next(
        i
        for i in range(anchor, -1, -1)
        if lines[i].strip() == "local waited=0"
    )
    depth = 0
    for idx in range(start, len(lines)):
        stripped = lines[idx].strip()
        if stripped.startswith("until "):
            depth += 1
        elif stripped == "done":
            depth -= 1
            if depth == 0:
                return "\n".join(lines[start : idx + 1])
    raise AssertionError("unterminated wait loop in mode_server")


def _run_wait_loop(
    tmp_path: Path,
    *,
    health: bool,
    ours: bool,
    log: str = "",
    launcher: str = "screen",
) -> subprocess.CompletedProcess[str]:
    """Drive the real wait loop against a stubbed listener.

    ``curl`` and ``_listener_is_ours`` are stubbed rather than a real socket
    bound, because the case that matters -- a listener owned by *another user*
    -- cannot be created in a test at all. Stubbing the two oracles is what
    lets the foreign path be exercised on the real loop body.

    ``sleep`` is a no-op so the 20-iteration timeout path runs instantly; the
    loop's own ``waited`` counter still advances, so the timeout arithmetic is
    the shipped arithmetic.
    """
    loop = _wait_loop(_engine_source())
    proxy_log = tmp_path / "argoproxy.out"
    proxy_log.write_text(log)
    script = "\n".join(
        (
            "set -uo pipefail",
            'err(){ echo "[err] $*" >&2; }',
            'ok(){ echo "[ok] $*"; }',
            'die(){ err "$*"; exit 1; }',
            "sleep(){ :; }",  # keep the timeout path fast
            f'curl(){{ return {0 if health else 1}; }}',
            f'_listener_is_ours(){{ return {0 if ours else 1}; }}',
            '_log_tail_meaningful(){ tail -n "${2:-20}" "$1"; }',
            "_dump_session_output_screen(){ echo DUMP-SCREEN; }",
            "_dump_session_output_tmux(){ echo DUMP-TMUX; }",
            'hostname(){ echo test-node; }',
            "PROXY_PORT=64742",
            f'_PROXY_LOG={proxy_log}',
            f'launcher={launcher}',
            "SCREEN_SESSION=argovproxy",
            'run(){',
            loop,
            '  ok "argo-proxy is listening on 127.0.0.1:${PROXY_PORT}."',
            '}',
            "run",
        )
    )
    path = tmp_path / "wait.sh"
    path.write_text(script)
    return subprocess.run(
        ["bash", str(path)], capture_output=True, text=True, timeout=60
    )


def test_wait_loop_succeeds_only_when_the_listener_is_ours(tmp_path: Path) -> None:
    """Health plus identity is the success condition -- both, not either."""
    out = _run_wait_loop(tmp_path, health=True, ours=True)
    assert out.returncode == 0, f"should succeed; stderr={out.stderr}"
    assert "argo-proxy is listening" in out.stdout


def test_wait_loop_refuses_a_healthy_listener_that_is_not_ours(
    tmp_path: Path,
) -> None:
    """The 2026-08-10 incident, reproduced against the shipped loop.

    A stranger's argo-proxy answers ``/health`` exactly as ours would. Before
    the fix this run *succeeded* and the client tunnelled into their process
    under ALL GREEN. Now it must refuse.
    """
    out = _run_wait_loop(tmp_path, health=True, ours=False)
    assert out.returncode == 1, "a foreign listener must fail the bootstrap"
    assert "is served by a process that is NOT ours" in out.stderr
    assert "Refusing to attach to another user's argo-proxy" in out.stderr
    assert "did not start listening" not in out.stderr, (
        "must name the real cause, not fall through to the generic timeout"
    )


def test_foreign_refusal_is_immediate_not_after_the_timeout(
    tmp_path: Path,
) -> None:
    """Waiting cannot free a held port, so the refusal must not burn 20s.

    Asserted through the loop's own counter rather than wall-clock (``sleep``
    is stubbed): if the refusal came from the timeout branch, the generic
    message would appear too. The distinction matters because a 20s wait
    followed by the wrong diagnosis is precisely what the field report showed.

    The positive assertion is load-bearing. Written with only the two
    ``not in`` checks, this test passed under the very mutation it was
    paired with -- deleting the identity check makes the loop *succeed*, so
    no timeout message appears and an absence-only test is satisfied by the
    bug. Assert the refusal happened, then assert how it happened.
    """
    out = _run_wait_loop(tmp_path, health=True, ours=False)
    assert "is served by a process that is NOT ours" in out.stderr, (
        "expected the refusal path, not success"
    )
    assert "did not start listening within" not in out.stderr
    assert "Server bootstrap failed" not in out.stderr


def test_foreign_refusal_names_a_way_out(tmp_path: Path) -> None:
    """A refusal the user cannot act on just relocates the dead end."""
    out = _run_wait_loop(tmp_path, health=True, ours=False)
    assert "--port" in out.stderr
    assert "--auto-port" in out.stderr


def test_foreign_refusal_shows_our_own_proxys_output(tmp_path: Path) -> None:
    """Our proxy died for a reason; the log is the only place it survives.

    The port collision is the symptom the user sees, but the cause is usually
    in our own process's output -- and by this point the session is long gone.
    """
    out = _run_wait_loop(
        tmp_path, health=True, ours=False, log="ERROR: address already in use\n"
    )
    assert "address already in use" in out.stderr
    assert str(tmp_path / "argoproxy.out") in out.stderr


def test_nothing_listening_times_out_with_the_generic_message(
    tmp_path: Path,
) -> None:
    """The other branch: no listener at all is a wait, then an honest timeout."""
    out = _run_wait_loop(tmp_path, health=False, ours=False)
    assert out.returncode == 1
    assert "did not start listening within 20s" in out.stderr
    assert "NOT ours" not in out.stderr, (
        "nothing answered -- claiming a foreign listener would be a fabrication"
    )


def test_timeout_prefers_the_log_over_the_live_session(tmp_path: Path) -> None:
    """LOG-DURABILITY COROLLARY: the log outlives the session, so read it first.

    With the stdin redirect a prompting argo-proxy dies in ~1s and the session
    is reaped ~18s before the timeout fires -- a session-only capture would
    have nothing left to show.
    """
    out = _run_wait_loop(
        tmp_path, health=False, ours=False, log="Traceback: boom\n"
    )
    assert "Traceback: boom" in out.stderr
    assert "DUMP-SCREEN" not in out.stdout, (
        "session capture is the fallback; it must not run when the log has content"
    )


def test_timeout_falls_back_to_session_capture_when_the_log_is_empty(
    tmp_path: Path,
) -> None:
    """The disjoint case: a genuine hang, still alive at 20s, log empty."""
    out = _run_wait_loop(tmp_path, health=False, ours=False, log="")
    assert "DUMP-SCREEN" in out.stdout, (
        "an empty log must trigger the live-session capture"
    )


def test_timeout_session_hint_matches_the_launcher(tmp_path: Path) -> None:
    """A screen hint on a tmux node sends the user to a command that fails."""
    out = _run_wait_loop(tmp_path, health=False, ours=False, launcher="tmux")
    assert "tmux attach -t argovproxy" in out.stderr
    assert "screen -r" not in out.stderr


def test_identity_rationale_is_documented_in_source() -> None:
    """The invariant carries its rationale, including the lsof inversion."""
    src = _engine_source()
    assert "IDENTITY-BEFORE-SUCCESS INVARIANT" in src
    helper = _function_block(src, "_listener_is_ours")
    assert "FAIL-CLOSED CONTRACT" in helper


def test_helper_is_fail_closed_by_construction() -> None:
    """Every guard in the helper must return 1 (not ours), never 0.

    Reviewed structurally as well as behaviourally: a `return 0` in a guard
    position would be an ownership claim on missing evidence.
    """
    helper = _function_body(_engine_source(), "_listener_is_ours")
    guards = re.findall(r"^\s*(?:\[.*?\]|command -v .*?)\s*\|\|\s*return (\d)",
                        helper, re.MULTILINE)
    assert guards, "expected guard clauses in _listener_is_ours"
    assert all(g == "1" for g in guards), (
        f"all guards must fail closed (return 1); found returns: {guards}"
    )
    assert "return 0" not in helper, (
        "no unconditional success path -- the final test is the only way to "
        "return 0"
    )


def test_helper_uses_sigpipe_resilient_capture() -> None:
    """The ``lsof | head`` capture must be wrapped per D-011.

    Unwrapped, ``head`` closing the pipe sends SIGPIPE to ``lsof``; under
    ``set -o pipefail`` the assignment then trips ``set -e`` and kills
    mode_server mid-bootstrap with no diagnostic (audit finding P1).
    """
    helper = _function_body(_engine_source(), "_listener_is_ours")
    assert re.search(r'"\$\(\s*\{.*lsof.*head -n1;\s*\}\s*\|\|\s*true\s*\)"', helper), (
        "lsof|head capture must use the { ...; } || true SIGPIPE guard"
    )


# ---------------------------------------------------------------------------
# Behaviour
# ---------------------------------------------------------------------------


def test_identifies_a_listener_we_own() -> None:
    """Positive case: a listener started by this very process is ours."""
    out = _run_helper_harness(
        """
        python3 -m http.server 45771 --bind 127.0.0.1 >/dev/null 2>&1 &
        SRV=$!
        sleep 1
        if _listener_is_ours 45771; then echo "verdict=ours"; else echo "verdict=foreign"; fi
        kill $SRV 2>/dev/null; wait $SRV 2>/dev/null
        """
    )
    assert "verdict=ours" in out.stdout, f"stdout={out.stdout} stderr={out.stderr}"


def test_unbound_port_is_not_ours() -> None:
    """Nothing listening must read as 'not ours', so the caller keeps waiting."""
    out = _run_helper_harness(
        """
        if _listener_is_ours 45779; then echo "verdict=ours"; else echo "verdict=foreign"; fi
        """
    )
    assert "verdict=foreign" in out.stdout


def test_dead_listener_is_not_ours() -> None:
    """A port whose owner has exited must not still read as ours."""
    out = _run_helper_harness(
        """
        python3 -m http.server 45772 --bind 127.0.0.1 >/dev/null 2>&1 &
        SRV=$!
        sleep 1
        kill $SRV 2>/dev/null; wait $SRV 2>/dev/null
        sleep 1
        if _listener_is_ours 45772; then echo "verdict=ours"; else echo "verdict=foreign"; fi
        """
    )
    assert "verdict=foreign" in out.stdout


def test_missing_lsof_fails_closed() -> None:
    """With lsof unavailable we must claim nothing, even for our own listener.

    A node without lsof is plausible (minimal images), and the safe answer
    there is "cannot confirm" -- which the caller treats as not-ours.
    """
    out = _run_helper_harness(
        """
        python3 -m http.server 45773 --bind 127.0.0.1 >/dev/null 2>&1 &
        SRV=$!
        sleep 1
        PATH=/nonexistent-dir
        if _listener_is_ours 45773; then echo "verdict=ours"; else echo "verdict=foreign"; fi
        """
    )
    assert "verdict=foreign" in out.stdout, (
        "missing lsof must fail closed, not claim ownership"
    )


def test_helper_survives_set_e() -> None:
    """The helper must be callable under ``set -e`` without killing the shell.

    mode_server runs under ``set -euo pipefail``; a helper that trips it on
    the not-ours path would abort the bootstrap instead of waiting.
    """
    out = _run_helper_harness(
        """
        set -e
        if _listener_is_ours 45778; then echo "verdict=ours"; else echo "verdict=foreign"; fi
        echo "survived=yes"
        """
    )
    assert "survived=yes" in out.stdout, (
        f"helper tripped set -e; stderr={out.stderr}"
    )


@pytest.mark.skipif(shutil.which("sudo") is None, reason="cannot test cross-user")
def test_cross_user_case_is_documented_as_verified_on_a_node() -> None:
    """The cross-user case cannot be simulated in CI without a second account.

    It WAS verified directly on compute-386-01 (2026-08-10): our own
    ``:64751`` returned our pid + username while a co-tenant's ``:64742``
    answered ``/health`` with an empty ``lsof -t`` and correctly read as
    not-ours. This test documents that provenance rather than re-running it;
    the local tests above cover every branch that does not need a second user.
    """
    helper = _function_block(_engine_source(), "_listener_is_ours")
    assert "compute-386-01" in helper, (
        "keep the live-verification provenance attached to the helper"
    )


# ---------------------------------------------------------------------------
# external-healthy identity gate (Defect 5, the one unguarded warm path)
# ---------------------------------------------------------------------------


def test_external_healthy_requires_identity() -> None:
    """``external-healthy`` must not adopt a listener it cannot attribute.

    This branch is reached when something answers ``/health`` on our port and
    it is NOT our tunnel -- typically an argo-proxy running locally on a
    compute node. The other reuse branches are anchored by evidence we own
    (our ``0700`` mux socket, whose name pins the destination host, with the
    far-end port fixed by ``-L`` at creation). This one has none of that, so
    adopting on reachability alone is ownership-by-inference.
    """
    body = _function_body(_engine_source(), "ensure_or_reuse_tunnel")
    branch = body[body.index("    external-healthy)") :]
    branch = branch[: branch.index(";;") + 2]
    assert "_listener_is_ours" in branch, (
        "external-healthy must verify ownership before adopting a listener"
    )
    assert "die " in branch, "an unattributable listener must be refused, not warned"


def test_external_healthy_check_is_local_and_free() -> None:
    """The gate must not add an SSH round trip.

    We are on the same host as the listener in this branch, so the check costs
    nothing -- unlike the ``ours-healthy-*`` branches, where the far end is a
    different machine (~0.75s over a warm mux, measured 2026-08-10).
    """
    body = _function_body(_engine_source(), "ensure_or_reuse_tunnel")
    branch = body[body.index("    external-healthy)") :]
    branch = branch[: branch.index(";;") + 2]
    # Strip comments first: the rationale legitimately discusses ssh/tunnels.
    code = "\n".join(
        ln for ln in branch.splitlines() if not ln.lstrip().startswith("#")
    )
    for forbidden in ("ssh ", "ssh_args", "probe_remote_port_owner", "scp "):
        assert forbidden not in code, (
            f"external-healthy gate must stay local; found {forbidden!r}"
        )


def test_external_healthy_has_a_documented_escape_hatch() -> None:
    """A deliberate shared-proxy setup must remain possible.

    Refusing outright would break anyone intentionally sharing a proxy. The
    override is opt-in, env-gated, and warns loudly about attribution.
    """
    src = _engine_source()
    body = _function_body(src, "ensure_or_reuse_tunnel")
    branch = body[body.index("    external-healthy)") :]
    branch = branch[: branch.index(";;") + 2]
    assert "ARGO_ANYWHERE_ALLOW_FOREIGN_PROXY" in branch
    # The refusal message must tell the user the escape hatch exists.
    assert branch.count("ARGO_ANYWHERE_ALLOW_FOREIGN_PROXY") >= 2, (
        "the refusal should name the override, not just implement it"
    )


def test_listener_is_ours_defined_before_both_call_sites() -> None:
    """Definition must precede use in the file.

    Bash resolves at call time, so late definition happens to work -- but
    relying on that across ~1400 lines is fragile. ``_listener_is_ours`` lives
    with its ``local_tunnel_*`` siblings, ahead of both callers.
    """
    src = _engine_source()
    defn = src.index("\n_listener_is_ours() {")
    assert defn < src.index("\nensure_or_reuse_tunnel() {"), (
        "_listener_is_ours must be defined before ensure_or_reuse_tunnel"
    )
    assert defn < src.index("\nmode_server() {"), (
        "_listener_is_ours must be defined before mode_server"
    )


def test_external_healthy_gate_behaviour() -> None:
    """Drive the real branch: adopt when ours, refuse when not, honour override.

    Simulating "not ours" is the delicate part. A test cannot bind a port as
    another user, so it has to make ``_listener_is_ours`` fail some other way.

    The first version masked ``PATH`` to ``/usr/bin:/bin`` to hide ``lsof`` and
    hit the helper's missing-binary guard. That is platform-dependent and it
    shipped broken: macOS keeps ``lsof`` in ``/usr/sbin``, so the mask worked
    locally, while ubuntu-latest keeps it in ``/usr/bin``, so on CI the helper
    found it, attributed the listener to the runner's own account, and reported
    "ours" -- the assertion failed with ``foreign_rc=2``. The test had never
    actually run on Linux before (CI was red for unrelated reasons from
    2026-07-23), so it looked green for a month.

    Overriding ``ps`` is the portable substitute: the helper resolves the pid's
    owner through it, so a stub that prints a name which is not ``id -un``
    exercises the real "someone else holds this port" path -- and it does so
    without depending on where any binary lives.
    """
    src = _engine_source()
    body = _function_body(src, "ensure_or_reuse_tunnel")
    branch = body[body.index("    external-healthy)") :]
    branch = branch[: branch.index(";;") + 2]
    helper = _function_body(src, "_listener_is_ours")

    harness = textwrap.dedent(
        """
        set -uo pipefail
        ok() {{ printf 'OK %s\\n' "$*"; }}
        warn() {{ printf 'WARN %s\\n' "$*"; }}
        err() {{ printf 'ERR %s\\n' "$*" >&2; }}
        die() {{ printf 'DIE %s\\n' "$*" >&2; exit 7; }}
        basename() {{ echo argo-anywhere; }}
        {helper}
        run() {{ PROXY_PORT="$1"; case external-healthy in
        {branch}
        esac; }}
        python3 -m http.server 46711 --bind 127.0.0.1 >/dev/null 2>&1 &
        SRV=$!
        sleep 1
        run 46711 >/dev/null 2>&1; echo "ours_rc=$?"
        # Shadow `ps` so the listener resolves to an account that is not ours.
        # A shell function is enough: _listener_is_ours calls `ps` unqualified.
        ( ps() {{ echo "definitely-not-$(id -un)"; }}
          run 46711 >/dev/null 2>&1 ); echo "foreign_rc=$?"
        ( ps() {{ echo "definitely-not-$(id -un)"; }}
          ARGO_ANYWHERE_ALLOW_FOREIGN_PROXY=1 run 46711 >/dev/null 2>&1
        ); echo "override_rc=$?"
        kill $SRV 2>/dev/null; wait $SRV 2>/dev/null
        """
    ).format(helper=helper, branch=branch)

    with tempfile.TemporaryDirectory() as td:
        script = Path(td) / "h.sh"
        script.write_text(harness)
        out = subprocess.run(
            ["bash", str(script)],
            cwd=td,
            capture_output=True,
            text=True,
            timeout=60,
            env={
                "HOME": td,
                "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                "TMPDIR": td,
            },
        )
    results = dict(
        line.split("=", 1) for line in out.stdout.splitlines() if "=" in line
    )
    assert results.get("ours_rc") == "2", (
        f"a listener we own must be adopted (rc=2); got {results}"
    )
    assert results.get("foreign_rc") == "7", (
        f"an unattributable listener must be refused (die); got {results}"
    )
    assert results.get("override_rc") == "2", (
        f"the override must allow adoption; got {results}"
    )


def test_engine_copies_stay_byte_identical() -> None:
    """Root and vendored engine copies must not diverge (D-001/D-028)."""
    repo_root = Path(__file__).resolve().parent.parent
    root_copy = repo_root / "argo-anywhere.sh"
    if not root_copy.exists():  # pragma: no cover - sdist/wheel layout
        pytest.skip("root engine copy not present in this layout")
    with engine_path() as vendored:
        assert root_copy.read_bytes() == vendored.read_bytes()
