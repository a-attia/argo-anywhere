"""Grep-based invariant tests for the D-033 ControlPersist fix (2026-07-22).

The bug: channel-owning modes (connect / tunnel / client / setup) opened the
SSH mux master with the finite ``SSH_MUX_PERSIST_DEFAULT`` (3600s / 1h). After
the foreground ``ssh -N -L`` exits, the master owns the ``-L`` forward, but an
idle ``-L`` listener does NOT count as an open channel for ControlPersist's
idle timer (verified against OpenSSH ``channels.c:channel_still_open``), so the
master was reaped after ~1h and the tunnel died with it.

The fix (D-033): a script global ``_CHANNEL_PERSIST`` set to 1 at the top of
``mode_tunnel`` and ``mode_client`` (before the master is opened by
``ssh_preflight``) makes ``ssh_mux_args`` emit ``ControlPersist=yes``
(indefinite) for those modes, while one-shot commands keep the finite default.
An explicit ``ARGO_ANYWHERE_CONTROL_PERSIST`` always wins.

These are grep-based invariants (the engine is otherwise live-only-verifiable
per AGENTS.md): they protect the contract's shape from a future refactor. The
runtime precedence itself is exercised as a shell unit in
``test_ssh_mux_args_persist_precedence`` below by sourcing just the function.
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


def test_channel_persist_global_declared_default_zero() -> None:
    """``_CHANNEL_PERSIST`` is declared at module scope defaulting to 0 so the
    one-shot commands (which never set it) get the finite default."""
    src = _engine_source()
    assert re.search(r"^_CHANNEL_PERSIST=0\b", src, re.MULTILINE), (
        "_CHANNEL_PERSIST=0 default declaration missing"
    )


def test_channel_owning_modes_set_channel_persist() -> None:
    """Both channel-owning entry points (mode_tunnel + mode_client) must set
    ``_CHANNEL_PERSIST=1``. If a future refactor drops it from either, the
    ~1h idle-expiry bug returns for that mode."""
    src = _engine_source()

    def _body(fn: str) -> str:
        # Grab from `fn() {` to the next top-level `}` heuristically: slice
        # from the function header to the next line that is exactly `}`.
        start = re.search(rf"^{fn}\(\)\s*\{{", src, re.MULTILINE)
        assert start, f"{fn} definition not found"
        rest = src[start.end():]
        end = re.search(r"^\}", rest, re.MULTILINE)
        return rest[: end.start()] if end else rest

    for fn in ("mode_tunnel", "mode_client"):
        body = _body(fn)
        assert "_CHANNEL_PERSIST=1" in body, (
            f"{fn} must set _CHANNEL_PERSIST=1 (D-033) so its mux master uses "
            f"an indefinite ControlPersist"
        )


def test_control_persist_resolver_honors_channel_persist_and_env() -> None:
    """``_resolve_control_persist`` (the single source of truth used by BOTH
    ssh_mux_args and the scp branch) must read both
    ``ARGO_ANYWHERE_CONTROL_PERSIST`` (user override) and ``_CHANNEL_PERSIST``
    (channel-mode flag)."""
    src = _engine_source()
    fn = re.search(
        r"_resolve_control_persist\(\)\s*\{.*?^\}", src, re.MULTILINE | re.DOTALL
    )
    assert fn, "_resolve_control_persist definition not found"
    body = fn.group(0)
    assert "ARGO_ANYWHERE_CONTROL_PERSIST" in body
    assert "_CHANNEL_PERSIST" in body


def test_scp_branch_uses_shared_persist_resolver() -> None:
    """The scp branch in remote_bootstrap must resolve persist via the shared
    ``_resolve_control_persist`` helper (not a private
    ``${ARGO_ANYWHERE_CONTROL_PERSIST:-$SSH_MUX_PERSIST_DEFAULT}`` that would
    ignore ``_CHANNEL_PERSIST`` and could pin a finite value if scp ever opens
    the master first). Guards against the two drifting apart."""
    src = _engine_source()
    start = re.search(r"^remote_bootstrap\(\)\s*\{", src, re.MULTILINE)
    assert start, "remote_bootstrap definition not found"
    rest = src[start.end():]
    end = re.search(r"^\}", rest, re.MULTILINE)
    body = rest[: end.start()] if end else rest
    assert "_resolve_control_persist" in body, (
        "scp branch must use the shared _resolve_control_persist helper"
    )
    # The old private-precedence pattern must be gone from this function.
    assert "ARGO_ANYWHERE_CONTROL_PERSIST:-$SSH_MUX_PERSIST_DEFAULT" not in body


def test_ssh_mux_args_persist_precedence() -> None:
    """Runtime check: source ``ssh_mux_args`` in isolation and assert the
    three-way precedence (explicit env > channel-mode 'yes' > finite default)
    plus the no-mfa empty case.

    We can't source the whole 11k-line engine cheaply, so we reconstruct the
    exact function under test from the engine source and drive it. This keeps
    the test honest against the real code (it greps the real body) without a
    live SSH stack.
    """
    src = _engine_source()
    resolver = re.search(
        r"_resolve_control_persist\(\)\s*\{.*?^\}", src, re.MULTILINE | re.DOTALL
    )
    assert resolver, "_resolve_control_persist definition not found"
    fn = re.search(r"ssh_mux_args\(\)\s*\{.*?^\}", src, re.MULTILINE | re.DOTALL)
    assert fn, "ssh_mux_args definition not found"
    fn_src = resolver.group(0) + "\n" + fn.group(0)

    harness = textwrap.dedent(
        """
        set -euo pipefail
        SSH_MUX_DIR="$PWD/sock"
        SSH_MUX_PERSIST_DEFAULT=3600
        _CHANNEL_PERSIST=0
        mfa_enabled() {{ [ "${{ARGO_ANYWHERE_NO_MFA:-0}}" = 1 ] && return 1; return 0; }}
        {fn}
        emit() {{ ssh_mux_args | grep -o 'ControlPersist=[^ ]*' || true; }}
        echo "oneshot=$(emit)"
        _CHANNEL_PERSIST=1; echo "channel=$(emit)"
        echo "explicit=$(ARGO_ANYWHERE_CONTROL_PERSIST=120 emit)"
        printf 'nomfa=[%s]\\n' "$(ARGO_ANYWHERE_NO_MFA=1 ssh_mux_args)"
        """
    ).format(fn=fn_src)

    with tempfile.TemporaryDirectory() as td:
        script = Path(td) / "h.sh"
        script.write_text(harness)
        out = subprocess.run(
            ["bash", str(script)],
            cwd=td,
            capture_output=True,
            text=True,
            timeout=15,
        )
    assert out.returncode == 0, f"harness failed: {out.stderr}"
    lines = dict(
        line.split("=", 1) for line in out.stdout.splitlines() if "=" in line
    )
    assert lines["oneshot"] == "ControlPersist=3600"
    assert lines["channel"] == "ControlPersist=yes"
    assert lines["explicit"] == "ControlPersist=120"
    assert lines["nomfa"] == "[]"  # no-mfa -> ssh_mux_args returns empty
