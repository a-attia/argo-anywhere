"""Two v3.3.0 field bugs: abort that did not abort, and a cache that lied.

Both were reported by the maintainer within an hour of the v3.3.0 release,
from one command (``connect --port <a port a co-tenant holds>``). They are
independent, and each is a distinct instance of a pattern this codebase
already had a name for.

**Bug 1 -- ``[a] abort`` continued.** Every caller captures the prompt as
``x="$(prompt_port_choice ...)"``. ``die`` inside a command substitution exits
the *subshell*; the parent reads an empty string and keeps going. The user saw
``[err] Aborted at port-reconciliation step.`` and then watched the run scp the
engine to the node and bootstrap argo-proxy. That is D-005 -- the ``$()``
capture trap AGENTS.md documents -- reappearing in a new place.

**Bug 2 -- the port cache recorded an intention, not a fact.**
``resolve_port`` wrote the cache as soon as it picked a port, before anything
had been established. Aborting (or dying, or failing to bootstrap) left the
cache naming a port with nothing on it. The web UI decides "are we connected?"
by looking for a listener on the cached port, so the dashboard read
"not connected" while a working channel ran in the embedded terminal on the
*previous* port. This is the same bug the P3 audit fixed for the NODE cache;
the port cache was left behind.
"""

from __future__ import annotations

import json
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


# ---------------------------------------------------------------------------
# Bug 1 -- abort must abort
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("fn", "answer"),
    [
        ("prompt_port_choice", "a"),
        ("prompt_port_choice", "zzz"),   # unrecognised -> also abort
        ("prompt_scope_switch", "a"),
        ("prompt_scope_switch", "zzz"),
    ],
)
def test_prompt_returns_abort_sentinel_instead_of_dying(
    tmp_path: Path, fn: str, answer: str
) -> None:
    """The helper must not ``die``: it runs inside ``$()``.

    Asserting the sentinel rather than the exit status is the point -- a helper
    that dies here *looks* correct in isolation and silently fails to stop the
    caller.
    """
    body = _function_body(_engine_source(), fn)
    args = "64743 64751 'OpenCode config'" if fn == "prompt_port_choice" else "'desc' global project"
    script = "\n".join(
        (
            "set -uo pipefail",
            "C_YLW=''; C_OFF=''",
            'warn(){ echo "[warn] $*" >&2; }',
            'err(){ echo "[err] $*" >&2; }',
            'die(){ err "$*"; exit 1; }',
            f'ask(){{ echo "{answer}"; }}',
            body,
            f'verdict="$({fn} {args} 2>/dev/null)"',
            'echo "VERDICT=${verdict}"',
        )
    )
    path = tmp_path / "h.sh"
    path.write_text(script)
    out = subprocess.run(["bash", str(path)], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, f"helper should return, not exit: {out.stderr}"
    assert "VERDICT=abort" in out.stdout, (
        f"{fn} must emit an 'abort' sentinel the caller can act on; got {out.stdout!r}"
    )


def test_abort_actually_stops_the_run(tmp_path: Path) -> None:
    """End-to-end: a real call-site shape must not reach the code after it.

    This is the field bug in miniature. Before the fix this script printed the
    'REACHED' line -- i.e. the tool said it aborted and then carried on to
    bootstrap.
    """
    body = _function_body(_engine_source(), "prompt_port_choice")
    script = "\n".join(
        (
            "set -uo pipefail",
            "C_YLW=''; C_OFF=''",
            'warn(){ echo "[warn] $*" >&2; }',
            'err(){ echo "[err] $*" >&2; }',
            'die(){ err "$*"; exit 1; }',
            'ask(){ echo "a"; }',
            body,
            '_ppc_choice="$(prompt_port_choice 64743 64751 \'OpenCode config\' 2>/dev/null)"',
            'case "$_ppc_choice" in',
            '  abort) die "Aborted at port-reconciliation step." ;;',
            '  migrate|use-once|keep) : ;;',
            'esac',
            'echo "REACHED-CODE-AFTER-ABORT"',
        )
    )
    path = tmp_path / "e2e.sh"
    path.write_text(script)
    out = subprocess.run(["bash", str(path)], capture_output=True, text=True, timeout=30)
    assert "REACHED-CODE-AFTER-ABORT" not in out.stdout, (
        "execution continued past an abort -- the die ran in the $() subshell"
    )
    assert out.returncode == 1, f"abort must exit non-zero; got {out.returncode}"


def test_every_call_site_handles_the_abort_sentinel() -> None:
    """A ``case`` without an ``abort)`` arm silently ignores the user's choice.

    Emitting a sentinel only helps if every caller acts on it; a missing arm
    falls through and recreates the bug in a new shape.
    """
    src = _engine_source()
    lines = src.splitlines()
    sites = [
        i for i, line in enumerate(lines)
        if line.strip() in ('case "$_ppc_choice" in', 'case "$_ppc_choice2" in',
                            'case "$_ssc_choice" in')
    ]
    assert sites, "no prompt-verdict case blocks found -- did they get renamed?"
    for i in sites:
        window = "\n".join(lines[i : i + 6])
        assert "abort)" in window, (
            f"case block at line {i + 1} does not handle the abort sentinel:\n{window}"
        )


def test_prompt_helpers_do_not_die() -> None:
    """Grep invariant: a future edit must not reintroduce ``die`` here."""
    src = _engine_source()
    for fn in ("prompt_port_choice", "prompt_scope_switch"):
        body = _function_body(src, fn)
        code = [
            ln for ln in body.splitlines()
            if ln.strip() and not ln.strip().startswith("#")
        ]
        assert not any(re.search(r"\bdie\b", ln) for ln in code), (
            f"{fn} calls die; it runs inside $() so that exits only the subshell "
            "(ABORT-MUST-ABORT INVARIANT)"
        )


# ---------------------------------------------------------------------------
# Bug 2 -- the cache must describe a channel that worked
# ---------------------------------------------------------------------------


def test_resolve_port_stages_the_cache_write_instead_of_doing_it() -> None:
    """``resolve_port`` must not write the cache; it only stages a value."""
    body = _function_body(_engine_source(), "resolve_port")
    assert "_PORT_CACHE_PENDING=" in body, "resolve_port should stage, not write"
    code = [
        ln for ln in body.splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    ]
    assert not any("write_port_cache" in ln for ln in code), (
        "resolve_port writes the port cache directly; an aborted or failed run "
        "then leaves the cache naming a port with nothing on it, and the web UI "
        "reads that cache to decide whether a channel exists"
    )
    assert "CACHE-AFTER-SUCCESS INVARIANT" in body, "keep the rationale attached"


def test_commit_helper_is_called_on_the_success_paths() -> None:
    """Every place that caches the NODE after success must cache the port too.

    The two are the same fact -- "this channel worked" -- and drifting them
    apart is what produced a cache that disagreed with reality.
    """
    src = _engine_source()
    lines = src.splitlines()
    node_writes = [i for i, ln in enumerate(lines) if 'write_node_cache "$node"' in ln]
    assert node_writes, "no write_node_cache call sites found"
    for i in node_writes:
        window = "\n".join(lines[i : i + 8])
        assert "_persist_port_cache" in window, (
            f"write_node_cache at line {i + 1} has no matching _persist_port_cache:\n"
            f"{window}"
        )


def test_commit_helper_is_a_noop_without_a_pending_value(tmp_path: Path) -> None:
    """Safe to call unconditionally -- callers should not have to check."""
    src = _engine_source()
    script = "\n".join(
        (
            "set -uo pipefail",
            f'PORT_CACHE={tmp_path}/port',
            "PORT_PERSIST_OK=1",
            "_PORT_CACHE_PENDING=''",
            'die(){ echo "DIE $*" >&2; exit 1; }',
            "_ensure_state_dir(){ :; }",
            _function_body(src, "write_port_cache"),
            _function_body(src, "_persist_port_cache"),
            "_persist_port_cache",
            'echo "SURVIVED"',
            '[ -e "$PORT_CACHE" ] && echo "WROTE-ANYWAY" || echo "no-write"',
        )
    )
    path = tmp_path / "n.sh"
    path.write_text(script)
    out = subprocess.run(["bash", str(path)], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    assert "SURVIVED" in out.stdout
    assert "no-write" in out.stdout, "no pending value must mean no cache write"


def test_commit_helper_writes_when_given_a_port(tmp_path: Path) -> None:
    src = _engine_source()
    cache = tmp_path / "port"
    script = "\n".join(
        (
            "set -uo pipefail",
            f'PORT_CACHE={cache}',
            "PORT_PERSIST_OK=1",
            "_PORT_CACHE_PENDING=''",
            'die(){ echo "DIE $*" >&2; exit 1; }',
            "_ensure_state_dir(){ :; }",
            _function_body(src, "write_port_cache"),
            _function_body(src, "_persist_port_cache"),
            "_persist_port_cache 64743",
        )
    )
    path = tmp_path / "w.sh"
    path.write_text(script)
    out = subprocess.run(["bash", str(path)], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    assert cache.read_text().strip() == "64743"


def test_engine_copies_stay_byte_identical() -> None:
    """Root and vendored engine copies must not diverge (D-001/D-028)."""
    repo_root = Path(__file__).resolve().parent.parent
    root_copy = repo_root / "argo-anywhere.sh"
    if not root_copy.exists():  # pragma: no cover
        pytest.skip("root engine copy not present in this layout")
    with engine_path() as vendored:
        assert root_copy.read_bytes() == vendored.read_bytes()


# ---------------------------------------------------------------------------
# Cross-client port coherence (2026-08-12)
# ---------------------------------------------------------------------------
#
# enumerate_client_ports is what makes "do my clients agree on the port?"
# answerable -- detect_port_disagreement walks it, and both `status` and client
# startup act on the result. aider was missing from it since Phase 5a shipped,
# so aider's config was invisible to every coherence check.
#
# Observed after a collision moved the port: cache and opencode both said
# 64743, aider still said 64751, nothing warned, and `aider` failed with
# connection-refused against a port that no longer existed -- which reads to a
# user as "argo-anywhere broke aider".


def _enumerate(tmp_path: Path, *, opencode_port=None, aider_port=None) -> str:
    """Run the real enumerate_client_ports against synthetic configs."""
    src = _engine_source()
    oc = tmp_path / "opencode.json"
    if opencode_port:
        oc.write_text(
            json.dumps({"provider": {"argo": {"options": {
                "baseURL": f"http://localhost:{opencode_port}/v1"}}}})
        )
    ai = tmp_path / ".aider.conf.yml"
    if aider_port:
        ai.write_text(f"openai-api-base: http://localhost:{aider_port}/v1\n")

    script = "\n".join(
        (
            "set -uo pipefail",
            f'OPENCODE_GLOBAL_CONFIG={oc}',
            # read_port_from_opencode_config reads OPENCODE_CONFIG (the legacy
            # alias), not OPENCODE_GLOBAL_CONFIG. Set both, as the engine does.
            f'OPENCODE_CONFIG={oc}',
            'CLAUDECODE_GLOBAL_CONFIG=/nonexistent',
            'CLAUDECODE_PROJECT_CONFIG=/nonexistent',
            f'AIDER_GLOBAL_CONFIG={ai}',
            _function_body(src, "read_port_from_opencode_config"),
            _function_body(src, "_get_port_from_claudecode_config"),
            _function_body(src, "_get_port_from_aider_config"),
            _function_body(src, "enumerate_client_ports"),
            "enumerate_client_ports",
        )
    )
    path = tmp_path / "enum.sh"
    path.write_text(script)
    out = subprocess.run(["bash", str(path)], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    return out.stdout


def test_aider_is_visible_to_the_coherence_check(tmp_path: Path) -> None:
    """aider's port must be enumerated, or nothing can notice it drifting."""
    out = _enumerate(tmp_path, opencode_port=64743, aider_port=64751)
    assert "aider global 64751" in out, (
        f"aider is invisible to enumerate_client_ports; got:\n{out}"
    )
    assert "opencode global 64743" in out


def test_disagreement_is_detected_across_tools(tmp_path: Path) -> None:
    """The field case: one tool moved, another did not."""
    src = _engine_source()
    oc = tmp_path / "opencode.json"
    oc.write_text('{"provider":{"argo":{"options":{"baseURL":"http://localhost:64743/v1"}}}}')
    ai = tmp_path / ".aider.conf.yml"
    ai.write_text("openai-api-base: http://localhost:64751/v1\n")
    script = "\n".join(
        (
            "set -uo pipefail",
            f'OPENCODE_GLOBAL_CONFIG={oc}',
            # read_port_from_opencode_config reads OPENCODE_CONFIG (the legacy
            # alias), not OPENCODE_GLOBAL_CONFIG. Set both, as the engine does.
            f'OPENCODE_CONFIG={oc}',
            'CLAUDECODE_GLOBAL_CONFIG=/nonexistent',
            'CLAUDECODE_PROJECT_CONFIG=/nonexistent',
            f'AIDER_GLOBAL_CONFIG={ai}',
            _function_body(src, "read_port_from_opencode_config"),
            _function_body(src, "_get_port_from_claudecode_config"),
            _function_body(src, "_get_port_from_aider_config"),
            _function_body(src, "enumerate_client_ports"),
            _function_body(src, "detect_port_disagreement"),
            'detect_port_disagreement 64743 || true',
        )
    )
    path = tmp_path / "d.sh"
    path.write_text(script)
    out = subprocess.run(["bash", str(path)], capture_output=True, text=True, timeout=30)
    assert "aider" in out.stdout and "64751" in out.stdout, (
        f"the drifted client must be reported; got:\n{out.stdout}"
    )
    assert "opencode" not in out.stdout, "an agreeing client must not be reported"


def test_agreeing_clients_produce_no_disagreement(tmp_path: Path) -> None:
    src = _engine_source()
    oc = tmp_path / "opencode.json"
    oc.write_text('{"provider":{"argo":{"options":{"baseURL":"http://localhost:64743/v1"}}}}')
    ai = tmp_path / ".aider.conf.yml"
    ai.write_text("openai-api-base: http://localhost:64743/v1\n")
    script = "\n".join(
        (
            "set -uo pipefail",
            f'OPENCODE_GLOBAL_CONFIG={oc}',
            # read_port_from_opencode_config reads OPENCODE_CONFIG (the legacy
            # alias), not OPENCODE_GLOBAL_CONFIG. Set both, as the engine does.
            f'OPENCODE_CONFIG={oc}',
            'CLAUDECODE_GLOBAL_CONFIG=/nonexistent',
            'CLAUDECODE_PROJECT_CONFIG=/nonexistent',
            f'AIDER_GLOBAL_CONFIG={ai}',
            _function_body(src, "read_port_from_opencode_config"),
            _function_body(src, "_get_port_from_claudecode_config"),
            _function_body(src, "_get_port_from_aider_config"),
            _function_body(src, "enumerate_client_ports"),
            _function_body(src, "detect_port_disagreement"),
            'detect_port_disagreement 64743 || true',
        )
    )
    path = tmp_path / "a.sh"
    path.write_text(script)
    out = subprocess.run(["bash", str(path)], capture_output=True, text=True, timeout=30)
    assert out.stdout.strip() == "", f"expected no disagreement; got:\n{out.stdout}"


def test_every_config_writing_tool_is_enumerated() -> None:
    """A tool that writes a port but is not enumerated is invisible to coherence.

    Grep-level, deliberately: the point is to fail when someone adds a fourth
    tool and forgets this function, which is exactly how aider was missed.
    """
    src = _engine_source()
    body = _function_body(src, "enumerate_client_ports")
    for tool in ("opencode", "claudecode", "aider"):
        assert tool in body, (
            f"{tool} writes a port into its config but is absent from "
            "enumerate_client_ports, so no coherence check can see it"
        )


def _coherence(tmp_path: Path, *, port: int, opencode=None, aider=None,
               packaged=False) -> str:
    """Run the real report_client_coherence against synthetic configs."""
    src = _engine_source()
    oc = tmp_path / "opencode.json"
    if opencode:
        oc.write_text(json.dumps({"provider": {"argo": {"options": {
            "baseURL": f"http://localhost:{opencode}/v1"}}}}))
    ai = tmp_path / ".aider.conf.yml"
    if aider:
        ai.write_text(f"openai-api-base: http://localhost:{aider}/v1\n")
    fns = "\n".join(
        _function_body(src, f) for f in (
            "read_port_from_opencode_config",
            "_get_port_from_claudecode_config",
            "_get_port_from_aider_config",
            "enumerate_client_ports",
            "detect_port_disagreement",
            "report_client_coherence",
        )
    )
    script = "\n".join(
        (
            "set -uo pipefail",
            'warn(){ echo "[warn] $*"; }',
            f'OPENCODE_GLOBAL_CONFIG={oc}',
            f'OPENCODE_CONFIG={oc}',
            'CLAUDECODE_GLOBAL_CONFIG=/nonexistent',
            'CLAUDECODE_PROJECT_CONFIG=/nonexistent',
            f'AIDER_GLOBAL_CONFIG={ai}',
            f'ARGO_ANYWHERE_PACKAGED={1 if packaged else 0}',
            f'PROXY_PORT={port}',
            fns,
            f"report_client_coherence {port}",
        )
    )
    path = tmp_path / "c.sh"
    path.write_text(script)
    out = subprocess.run(["bash", str(path)], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    return out.stdout


def test_coherence_names_the_drifted_client_and_the_fix(tmp_path: Path) -> None:
    """The field case: a collision moved the channel, one client stayed behind.

    Reporting the disagreement is not enough on its own -- the user needs the
    command. "aider still says :64751" without "run `configure aider`" is a
    diagnosis with no treatment.
    """
    out = _coherence(tmp_path, port=64743, opencode=64743, aider=64751,
                     packaged=True)
    assert "aider" in out and "64751" in out, f"drifted client not named:\n{out}"
    assert "argo-anywhere configure aider" in out, (
        f"the fix command must be spelled out; got:\n{out}"
    )
    assert "configure opencode" not in out, (
        "a client that already agrees must not be listed"
    )


def test_coherence_is_silent_when_everything_agrees(tmp_path: Path) -> None:
    """No news is good news -- this runs on every successful connect."""
    out = _coherence(tmp_path, port=64743, opencode=64743, aider=64743)
    assert out.strip() == "", f"expected silence; got:\n{out}"


def test_coherence_uses_the_command_the_user_can_actually_type(tmp_path: Path) -> None:
    """Under the package the command is `argo-anywhere`, not the script name."""
    out = _coherence(tmp_path, port=64743, aider=64751, packaged=True)
    assert "argo-anywhere configure aider" in out
    assert ".sh configure" not in out, (
        "packaged mode must not print the vendored script's filename"
    )


def test_coherence_runs_after_every_channel_is_established() -> None:
    """It must fire for channel-only verbs too, and after the port is final.

    The pre-existing startup check missed this twice over: it is gated on
    `with_opencode_setup=1` (so `connect` / `tunnel` / `--ensure` skip it), and
    it runs BEFORE ensure_or_reuse_tunnel (so a collision-moved port is never
    re-checked). Pinning it to the cache-commit sites keeps both properties:
    those are exactly the points where a channel is known to be up on a known
    port.
    """
    src = _engine_source()
    lines = src.splitlines()
    commits = [i for i, ln in enumerate(lines)
               if ln.strip() == '_persist_port_cache "$PROXY_PORT"']
    assert commits, "no cache-commit sites found -- did they get renamed?"
    for i in commits:
        window = "\n".join(lines[i : i + 4])
        assert "report_client_coherence" in window, (
            f"channel established at line {i + 1} without a coherence report:\n"
            f"{window}"
        )


def test_coherence_only_reports_never_rewrites() -> None:
    """It must not silently fix configs this run was not asked to touch.

    Unattended state changes are what produced the v3.3.0 incident; the whole
    point of reporting is that the user stays in control.
    """
    body = _function_body(_engine_source(), "report_client_coherence")
    for forbidden in ("write_opencode_config", "write_aider_config",
                      "handle_config_file", "_persist_port_cache",
                      "write_port_cache"):
        assert forbidden not in body, (
            f"report_client_coherence calls {forbidden}; it must only report"
        )
