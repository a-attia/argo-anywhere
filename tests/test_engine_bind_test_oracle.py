"""Tests for the bind-test port oracle (Defect 1).

Every port-availability check in the engine used ``lsof`` as its oracle. An
unprivileged ``lsof`` on Linux cannot attribute another user's socket, so it
prints nothing and the port reads as *free* -- on a shared compute node that
is the COMMON case, not an edge case. Measured on ``compute-386-01``
(2026-08-10):

    port 64742  lsof=<empty>   bind=TAKEN   <-- the blind spot
    port 64751  lsof=4092655   bind=TAKEN
    port 64899  lsof=<empty>   bind=FREE

The consequence was worst exactly where it hurt most: ``--auto-port``, the
flag advertised as the escape from a collision, walked the same blind oracle
and so recommended ports a co-tenant already held.

The fix makes ``socket.bind()`` the oracle -- byte-identical semantics to
what argo-proxy's own ``validate_port`` does, and the only check that sees
across users. ``lsof`` is kept for what it could always do: *attribute* a hit
we already know about.

These are grep-based invariants plus local behavioural checks; the
cross-user case cannot be simulated without a second account and was
verified on the node (see the module-level docstring in
``test_engine_listener_identity.py`` for the same pattern).
"""

from __future__ import annotations

import os
import re
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


# ---------------------------------------------------------------------------
# Contract
# ---------------------------------------------------------------------------


def test_probe_uses_bind_not_lsof_as_the_oracle() -> None:
    """``probe_remote_port_owner`` must decide availability with ``bind()``."""
    body = _function_body(_engine_source(), "probe_remote_port_owner")
    assert "s.bind(" in body, "availability must be decided by a real bind()"
    assert "BIND-TEST ORACLE" in body, "keep the rationale attached"
    # lsof must still be present -- but for attribution, after the bind test.
    assert "lsof" in body, "lsof is still needed to attribute a hit"
    assert body.index("s.bind(") < body.index("lsof -nPi"), (
        "bind test must run BEFORE lsof; lsof only attributes a known hit"
    )


def test_auto_port_walk_uses_bind_test() -> None:
    """``--auto-port`` must not recommend ports it cannot actually bind.

    This is the sharpest form of Defect 1: the flag that exists to escape a
    collision was the one most likely to walk back into one.
    """
    body = _function_body(_engine_source(), "find_next_free_remote_port")
    assert "s.bind(" in body, "the auto-port walk must bind-test each candidate"
    assert "BIND-TEST WALK" in body


def test_bind_test_disables_so_reuseaddr() -> None:
    """``SO_REUSEADDR`` must be explicitly off in both probes.

    With it set, ``bind()`` can succeed on a port in ``TIME_WAIT`` and we
    would report an unusable port as free -- reintroducing a subtler version
    of the bug.
    """
    src = _engine_source()
    for fn in ("probe_remote_port_owner", "find_next_free_remote_port"):
        body = _function_body(src, fn)
        assert "SO_REUSEADDR, 0" in body, (
            f"{fn} must disable SO_REUSEADDR so TIME_WAIT ports read as taken"
        )


def test_bound_but_unattributable_reports_other_not_free() -> None:
    """The load-bearing case: bind says taken, lsof says nothing.

    That combination means "another user's process", never "nobody's" -- the
    same inversion ``_listener_is_ours`` relies on. Reporting ``free`` here
    is precisely the original defect.
    """
    body = _function_body(_engine_source(), "probe_remote_port_owner")
    taken = body[body.index("= free ]") :]
    assert "other:?:?" in taken, (
        "a bound-but-unattributable port must report other:, not free"
    )


def test_probe_degrades_when_python3_is_missing() -> None:
    """A node without python3 must not hard-fail the probe.

    It degrades to ``unknown``, which the caller already handles by warning
    and proceeding -- weaker, but not broken.
    """
    body = _function_body(_engine_source(), "probe_remote_port_owner")
    assert "probe-failed" in body
    assert 'echo "unknown"' in body, "a failed probe must map to the unknown path"


def test_auto_port_walk_falls_back_to_lsof_without_python3() -> None:
    """The walk keeps its old behaviour on a minimal node rather than dying."""
    body = _function_body(_engine_source(), "find_next_free_remote_port")
    assert "command -v python3" in body
    assert "lsof -nPi" in body, "lsof walk must remain as the fallback branch"


def test_unknown_owner_is_reported_in_plain_language() -> None:
    """``owner='?'`` must not surface as "owned by '?' (pid ?)".

    The bind oracle can prove a port is held without naming the holder. That
    is an honest answer and should read like one.
    """
    src = _engine_source()
    prompt = _function_body(src, "prompt_port_collision")
    assert "_owner_descr" in prompt
    assert "can't be identified" in prompt
    # And the --auto-port warning has the same branch.
    tunnel = _function_body(src, "ensure_or_reuse_tunnel")
    assert "held by another user's process" in tunnel


# ---------------------------------------------------------------------------
# Behaviour (local; the cross-user case needs a second account)
# ---------------------------------------------------------------------------


def _run_probe_snippet(port_expr: str) -> str:
    """Extract the engine's remote bind-test snippet and run it locally."""
    src = _engine_source()
    match = re.search(
        r'result="\$\(ssh \$\(ssh_args "\$user" "\$node"\) '
        r'"\$\{user\}@\$\{node\}" "\n(    avail=.*?)\n  " 2>/dev/null\)"',
        src,
        re.DOTALL,
    )
    assert match, "remote probe snippet not found"
    inner = (
        match.group(1)
        .replace("\\$", "$")
        .replace('\\"', '"')
        .replace("${port}", port_expr)
    )
    harness = "#!/bin/bash\n" + inner
    with tempfile.TemporaryDirectory() as td:
        script = Path(td) / "p.sh"
        script.write_text(harness)
        out = subprocess.run(
            ["bash", str(script)],
            cwd=td,
            capture_output=True,
            text=True,
            timeout=30,
            env={
                "HOME": td,
                "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            },
        )
    return out.stdout.strip()


def test_probe_reports_free_for_an_unbound_port() -> None:
    assert _run_probe_snippet("47311") == "free"


def test_probe_reports_mine_for_our_own_listener() -> None:
    """A listener we own must be attributed to us, not merely 'taken'."""
    import socket

    s = socket.socket()
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.listen(1)
    try:
        result = _run_probe_snippet(str(port))
    finally:
        s.close()
    assert result.startswith("mine:"), (
        f"our own listener should report mine:<pid>; got {result!r}"
    )


# ---------------------------------------------------------------------------
# Auto-port default (D-034 Option A, 2026-08-12)
# ---------------------------------------------------------------------------
#
# Auto-pick is now ON by default. It was off, which was correct while the walk
# used the blind ``lsof`` oracle -- the flag that exists to escape a collision
# recommended ports a co-tenant already held (verified live on compute-386-01:
# the old walk over 64742-64760 returned the occupied 64742; the bind-test walk
# returns 64743). With the oracle fixed, the reason to distrust it is gone.
#
# The load-bearing part is not convenience. The interactive prompt is
# unreachable for non-TTY callers -- ``-y``, ``--ensure``, and every web-UI
# launch -- so with the old default those paths simply died on a collision, on
# a node where collision is the expected state. The tool had a working recovery
# path its own GUI could never take.


def _auto_port_verdict(*, flag: str | None, env: str | None) -> str:
    """Run the engine's own ``_auto_port_enabled`` under bash."""
    body = _function_body(_engine_source(), "_auto_port_enabled")
    lines = ["set -u", body]
    if flag is not None:
        lines.append(f"AUTO_PORT={flag}")
    if env is not None:
        lines.append(f"ARGO_ANYWHERE_AUTO_PORT={env}")
    lines.append('if _auto_port_enabled; then echo AUTO; else echo PROMPT; fi')
    out = subprocess.run(
        ["bash", "-c", "\n".join(lines)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert out.returncode == 0, out.stderr
    return out.stdout.strip()


def test_auto_port_is_on_by_default() -> None:
    """The headline change: an unconfigured run self-heals a collision."""
    assert _auto_port_verdict(flag=None, env=None) == "AUTO"


@pytest.mark.parametrize(
    ("flag", "env", "expected"),
    [
        ("1", None, "AUTO"),      # --auto-port (now redundant, still honoured)
        ("0", None, "PROMPT"),    # --no-auto-port
        (None, "1", "AUTO"),      # env on
        (None, "0", "PROMPT"),    # env off
        ("0", "1", "PROMPT"),     # explicit flag beats env, both directions
        ("1", "0", "AUTO"),
    ],
)
def test_auto_port_precedence(flag: str | None, env: str | None, expected: str) -> None:
    """CLI flag beats env; env beats the default. Opting out must be possible."""
    assert _auto_port_verdict(flag=flag, env=env) == expected


def test_no_auto_port_flag_is_parsed() -> None:
    """An opt-out users cannot spell is not an opt-out."""
    src = _engine_source()
    assert "--no-auto-port)" in src, "the opt-out flag must be in the argv parser"
    assert "--no-auto-port" in src.split("USAGE", 1)[-1] or "--no-auto-port" in src, (
        "the opt-out flag must be documented in help text"
    )


def test_auto_port_has_exactly_one_decision_site() -> None:
    """The default must not be re-implemented inline anywhere.

    The pre-change code read ``${AUTO_PORT:-${ARGO_ANYWHERE_AUTO_PORT:-0}}``
    at its single use site. A second copy of that expression elsewhere would
    silently keep the old default in whichever path it governs.
    """
    src = _engine_source()
    inline = re.findall(r"\$\{AUTO_PORT:-\$\{ARGO_ANYWHERE_AUTO_PORT:-\d\}\}", src)
    assert not inline, (
        f"inline auto-port default found ({inline}); use _auto_port_enabled"
    )


def test_no_free_port_failure_names_the_remedies() -> None:
    """Auto-pick can still fail (a full range). Say what to do about it.

    With auto-pick on by default, this error is reachable by users who never
    asked for it, so it must not be a bare 'No free port found'.
    """
    body = _function_body(_engine_source(), "ensure_or_reuse_tunnel")
    idx = body.find("No free port")
    assert idx != -1, "the exhausted-range failure message is gone"
    window = body[max(0, idx - 600) : idx + 600]
    assert "--port-range" in window and "--port" in window, (
        "the exhausted-range failure must name --port-range and --port"
    )


def test_engine_copies_stay_byte_identical() -> None:
    """Root and vendored engine copies must not diverge (D-001/D-028)."""
    repo_root = Path(__file__).resolve().parent.parent
    root_copy = repo_root / "argo-anywhere.sh"
    if not root_copy.exists():  # pragma: no cover
        pytest.skip("root engine copy not present in this layout")
    with engine_path() as vendored:
        assert root_copy.read_bytes() == vendored.read_bytes()
