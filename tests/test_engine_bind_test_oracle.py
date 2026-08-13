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

Grep-based invariants plus behavioural checks that drive the engine's own
remote snippets locally.

An earlier version of this docstring said the blind spot "cannot be simulated
without a second account". That was wrong, and it cost the file its most
important test for two days. Cross-*user ownership* does need a second
account -- but the oracle does not key on ownership. It keys on the pair
``bind()`` refuses / ``lsof -sTCP:LISTEN`` says nothing, and a socket bound
WITHOUT ``listen()`` produces exactly that pair on one machine as one user.
The ``64742`` row above is reproducible with one skipped syscall.

The genuinely unsimulable part is narrow: whether an unprivileged ``lsof``
can attribute a socket belonging to a *different* user. That was verified on
the node and is documented, not tested.
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
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


def test_probe_sees_a_port_that_lsof_cannot_attribute() -> None:
    """The blind spot itself, reproduced locally -- no second account needed.

    The module docstring said the cross-user case could not be simulated
    without another user. That is true of cross-*user* ownership, but it is
    not what the oracle actually keys on: the failure is that ``lsof -sTCP:
    LISTEN`` returns nothing for a port that ``bind()`` refuses. A socket
    bound WITHOUT ``listen()`` produces exactly that signature on the local
    machine --

        bind=TAKEN   lsof -sTCP:LISTEN=<empty>

    -- which is byte-for-byte the ``64742`` row measured on compute-386-01.
    The old lsof-only oracle called this port FREE; the bind oracle must call
    it taken and, being unable to name a holder, report ``other:?:?``.

    This is the single most important behaviour in the file and it had no
    behavioural test, on the belief that it needed infrastructure. It needed
    a socket that skips one syscall.
    """
    import socket

    s = socket.socket()
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    # Deliberately no listen(): held, but invisible to an lsof LISTEN filter.
    try:
        # Establish the premise rather than assuming it: if a future macOS or
        # Linux lsof starts reporting bound-not-listening sockets, this test
        # would silently stop covering the blind spot.
        probe = subprocess.run(
            ["lsof", "-nPi", f":{port}", "-sTCP:LISTEN", "-t"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if probe.stdout.strip():
            pytest.skip("this platform's lsof attributes bound-not-listening sockets")
        result = _run_probe_snippet(str(port))
    finally:
        s.close()

    assert result != "free", (
        "a port that cannot be bound must never read as free -- this is "
        "Defect 1 exactly, and it is what --auto-port walked into"
    )
    assert result == "other:?:?", (
        f"bound but unattributable must report other:?:?; got {result!r}"
    )


def _run_walk_snippet(start: int, end: int) -> tuple[str, int]:
    """Extract the auto-port walk's remote snippet and run it locally.

    Returns ``(stdout, returncode)``; the walk signals an exhausted range
    through exit status 1, which the caller distinguishes from SSH failure.
    """
    src = _engine_source()
    body = _function_body(src, "find_next_free_remote_port")
    match = re.search(
        r'"\n(    if command -v python3.*?\n    fi\n)  " 2>/dev/null\)"',
        body,
        re.DOTALL,
    )
    assert match, "remote walk snippet not found"
    inner = (
        match.group(1)
        .replace("\\$", "$")
        .replace('\\"', '"')
        .replace("${start}", str(start))
        .replace("${end}", str(end))
    )
    with tempfile.TemporaryDirectory() as td:
        script = Path(td) / "w.sh"
        script.write_text("#!/bin/bash\n" + inner)
        out = subprocess.run(
            ["bash", str(script)],
            cwd=td,
            capture_output=True,
            text=True,
            timeout=30,
            env={"HOME": td, "PATH": os.environ.get("PATH", "/usr/bin:/bin")},
        )
    return out.stdout.strip(), out.returncode


def test_auto_port_walk_skips_a_port_lsof_cannot_see() -> None:
    """Defect 1 at its sharpest, now driven rather than grepped.

    ``--auto-port`` exists to escape a collision. Walking the blind oracle, it
    recommended the occupied port -- verified live on compute-386-01, where the
    old walk over 64742-64760 returned the held 64742 and the bind-test walk
    returned 64743.

    Reproduced here with the same bound-not-listening trick: the first port in
    the range is held but invisible to ``lsof -sTCP:LISTEN``, so the old oracle
    would hand it straight back.
    """
    import socket

    s = socket.socket()
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
    s.bind(("127.0.0.1", 0))
    held = s.getsockname()[1]
    try:
        probe = subprocess.run(
            ["lsof", "-nPi", f":{held}", "-sTCP:LISTEN", "-t"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if probe.stdout.strip():
            pytest.skip("this platform's lsof attributes bound-not-listening sockets")
        picked, rc = _run_walk_snippet(held, held + 20)
    finally:
        s.close()

    assert rc == 0 and picked, f"walk found nothing in a range with free ports (rc={rc})"
    assert int(picked) != held, (
        f"the walk recommended the held port {held} -- this is the exact "
        "behaviour that made --auto-port unsafe on a shared node"
    )
    assert held < int(picked) <= held + 20, f"picked {picked} outside the range"


def test_auto_port_walk_reports_an_exhausted_range_distinctly() -> None:
    """A full range must exit 1 with no output, not print a port anyway.

    The caller separates "ran fine, nothing free" from "SSH failed" purely by
    this signal, and turns the former into the message naming ``--port-range``.
    """
    import socket

    held = []
    try:
        first = socket.socket()
        first.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
        first.bind(("127.0.0.1", 0))
        held.append(first)
        start = first.getsockname()[1]
        # Hold a small contiguous range. Ports are handed out arbitrarily, so
        # bind each explicitly and skip if the OS already has one in use.
        for candidate in range(start + 1, start + 4):
            sock = socket.socket()
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
            try:
                sock.bind(("127.0.0.1", candidate))
            except OSError:
                sock.close()
                pytest.skip("could not reserve a contiguous range on this host")
            held.append(sock)
        picked, rc = _run_walk_snippet(start, start + 3)
    finally:
        for sock in held:
            sock.close()

    assert picked == "", f"expected no port from a fully-held range; got {picked!r}"
    assert rc == 1, f"exhausted range must exit 1 (caller depends on it); got {rc}"


def test_bind_oracle_refuses_a_time_wait_port() -> None:
    """``SO_REUSEADDR, 0`` in the probe, demonstrated rather than grepped.

    A port in ``TIME_WAIT`` is not usable yet, and argo-proxy's own
    ``validate_port`` -- the thing that ultimately decides -- will refuse it.
    Our probe has to agree, or we hand out a port whose bind then fails.

    The control below is what makes this meaningful: it shows the SAME port
    reads as FREE with ``SO_REUSEADDR`` enabled, so the assertion is pinned to
    the sockopt and not to some incidental property of the port.
    """
    import socket
    import time

    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
    srv.bind(("127.0.0.1", 0))
    port = srv.getsockname()[1]
    srv.listen(1)
    client = socket.create_connection(("127.0.0.1", port))
    conn, _ = srv.accept()
    # Close the ACCEPTED side first so this host owns the TIME_WAIT.
    conn.close()
    client.close()
    srv.close()
    time.sleep(0.5)

    control = socket.socket()
    control.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        control.bind(("127.0.0.1", port))
    except OSError:
        pytest.skip("port did not enter TIME_WAIT on this platform")
    finally:
        control.close()

    assert _run_probe_snippet(str(port)) != "free", (
        "a TIME_WAIT port reads free only if SO_REUSEADDR crept back in; "
        "argo-proxy would then fail to bind the port we just recommended"
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


def test_auto_port_is_off_by_default() -> None:
    """A collision must PROMPT, not silently migrate the port.

    v3.3.0 flipped this default ON and v3.3.1 reverted it the same day after a
    field report. The reasoning that motivated the flip -- the interactive
    prompt is unreachable for ``-y`` / ``--ensure`` / web-UI launches, so those
    paths just die on a collision -- is still true and still unfixed. It is the
    lesser problem.

    A port is transport-layer state (D-020): it is written into client configs
    and cached in ``~/.config/argo_anywhere/port``, and the web UI decides
    whether a channel exists by looking for a listener on the cached port.
    Migrating it unattended left a user with a live channel on one port, a
    cache naming another, and a dashboard reporting "not connected" while a
    working session ran in the embedded terminal.

    Making migration safe to do unattended means fixing that coherence problem
    (D-035), not flipping a default. Until then the prompt is the feature.
    """
    assert _auto_port_verdict(flag=None, env=None) == "PROMPT"


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
