"""Tests for the no-interactive-prompt invariant + session-output capture.

Motivated by the 2026-08-10 field incident on ``compute-386-01`` (full
analysis: ``notes/impl_shared_node_transport.md``). Two independent defects
composed into a silent failure:

* ``screen -dm`` / ``tmux new-session -d`` give argo-proxy a pty, so upstream's
  ``validate_port`` port-collision prompt (a bare ``while True: input(...)``
  with no EOF handling and no timeout) blocks FOREVER instead of failing.
* the client-side wait then reports only "did not start listening within 20s",
  which names a symptom and not a cause -- diagnosing the real problem cost a
  manual ``screen -r`` on the node.

The fix (Tier 1 item 1 of the note's S6 sequencing) is two-part and this
module pins both:

1. every launcher runs argo-proxy with stdin redirected from ``/dev/null``, so
   the prompt raises ``EOFError`` in ~1s;
2. the start-timeout branch captures the session's visible output and prints
   it, so the traceback reaches the user automatically.

Test strategy follows ``test_engine_control_persist.py``: grep-based
invariants protect the contract's shape from a future refactor, and the
behaviour that CAN be exercised without a live SSH stack (the capture helpers,
and the EOF semantics of the launch line itself) is driven through a real
``bash`` + ``screen`` harness.
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
    """Extract a top-level shell function body by name."""
    match = re.search(
        rf"^{re.escape(name)}\(\)\s*\{{.*?^\}}", src, re.MULTILINE | re.DOTALL
    )
    assert match, f"{name} definition not found in engine"
    return match.group(0)


def _run_screen_harness(harness: str) -> subprocess.CompletedProcess[str]:
    """Run a ``screen``-using bash harness with a private, self-consistent HOME.

    ``screen`` derives its socket directory from ``$HOME``
    (``$HOME/.screen`` or ``$SCREENDIR``), so a session started under one HOME
    is invisible to a ``screen -ls`` run under another. The autouse
    ``_isolate_home`` fixture in ``conftest.py`` repoints HOME at a per-test
    sandbox, which is exactly right for the package's own state -- but it means
    a harness inheriting the ambient environment can silently start a session
    it cannot then see, and the test fails for a reason unrelated to what it is
    testing (observed 2026-08-10 while writing these tests).

    Pinning HOME *inside* the harness's own tmpdir makes each run
    self-contained and independent of the ambient value, and guarantees the
    sessions land somewhere that disappears with the tmpdir.
    """
    with tempfile.TemporaryDirectory() as td:
        home = Path(td) / "home"
        home.mkdir()
        script = Path(td) / "h.sh"
        script.write_text(harness)
        return subprocess.run(
            ["bash", str(script)],
            cwd=td,
            capture_output=True,
            text=True,
            timeout=60,
            env={
                "HOME": str(home),
                "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                "TMPDIR": td,
                "TERM": "xterm",
            },
        )


# ---------------------------------------------------------------------------
# Part 1: the no-interactive-prompt invariant
# ---------------------------------------------------------------------------


def test_all_three_launchers_redirect_stdin_from_devnull() -> None:
    """screen, tmux AND nohup must all start argo-proxy with stdin at
    /dev/null.

    This is THE invariant. If any launcher regains an inherited pty, a port
    collision hangs that launcher's path forever with no diagnostic -- the
    exact 2026-08-10 failure. ``nohup`` has always been correct; screen + tmux
    were fixed on 2026-08-10.
    """
    src = _engine_source()
    body = _function_body(src, "mode_server")

    screen_launch = re.search(r"^\s*screen -dmS .*argo-proxy.*$", body, re.MULTILINE)
    assert screen_launch, "screen launch line not found"
    assert "/dev/null" in screen_launch.group(0), (
        "screen launcher lost its stdin redirect -- a port-collision prompt "
        "will hang forever inside the detached session"
    )

    tmux_cmd = re.search(r"^\s*local _tmux_cmd;.*$", body, re.MULTILINE)
    assert tmux_cmd, "tmux command construction not found"
    assert "/dev/null" in tmux_cmd.group(0), (
        "tmux launcher lost its stdin redirect -- see the screen case"
    )

    nohup_launch = re.search(r"^\s*nohup .*argo-proxy.*$", body, re.MULTILINE)
    assert nohup_launch, "nohup launch line not found"
    assert "/dev/null" in nohup_launch.group(0), (
        "nohup launcher lost its stdin redirect (it has always had one)"
    )


def test_screen_launcher_passes_binary_out_of_band() -> None:
    """The screen launcher must pass the argo-proxy path as ``$0`` to ``sh -c``
    rather than interpolating it into the script string.

    Interpolating would word-split a ``$venv`` containing spaces (e.g.
    ``HOME=/home/Alice Smith``) -- the same hazard the tmux branch solves with
    ``printf %q``. Keeping the path out of the script text sidesteps quoting
    entirely.
    """
    src = _engine_source()
    body = _function_body(src, "mode_server")
    launch = re.search(r"^\s*screen -dmS .*argo-proxy.*$", body, re.MULTILINE)
    assert launch
    line = launch.group(0)
    assert 'sh -c \'exec "$0" serve < /dev/null\'' in line, (
        "screen launcher must pass the binary as $0, not interpolate it"
    )
    # The binary path must appear AFTER the quoted script (i.e. as the $0 arg).
    script_end = line.index("'", line.index("sh -c '") + len("sh -c '"))
    assert "argo-proxy" in line[script_end:], (
        "argo-proxy path must be the $0 argument, outside the script string"
    )


def test_no_interactive_prompt_rationale_is_documented() -> None:
    """The invariant carries its rationale in-source.

    Without it, the redirects look like noise and a future reader may 'clean
    them up'. Pinning the marker keeps the explanation attached to the code.
    """
    src = _engine_source()
    assert "NO-INTERACTIVE-PROMPT INVARIANT" in src
    body = _function_body(src, "mode_server")
    assert "validate_port" in body, "rationale should name the upstream culprit"


@pytest.mark.skipif(shutil.which("screen") is None, reason="screen not installed")
def test_devnull_redirect_actually_prevents_the_hang() -> None:
    """Behavioural proof, not a grep: run a fake argo-proxy that prompts, under
    ``screen -dm``, both ways.

    Without the redirect the session is still alive after the grace period
    (the bug). With it, the process takes EOF and exits promptly (the fix).
    """
    engine_src = _engine_source()
    body = _function_body(engine_src, "mode_server")
    launch = re.search(r"^\s*screen -dmS .*argo-proxy.*$", body, re.MULTILINE)
    assert launch
    # Reuse the ENGINE'S OWN launch shape, with our fake binary substituted,
    # so this test tracks the real code rather than a copy of it.
    real_launch = launch.group(0).strip()
    fake_launch = real_launch.replace(
        '"${SCREEN_SESSION}"', '"$SESSION"'
    ).replace('"${venv}/bin/argo-proxy"', '"$FAKE"')
    assert fake_launch != real_launch, "substitution failed; launch line changed shape"

    harness = textwrap.dedent(
        """
        set -uo pipefail
        FAKE="$PWD/fakeproxy"
        cat > "$FAKE" <<'EOS'
        #!/bin/bash
        echo "WARNING | [config] Warning: Port 64742 is already in use."
        echo -n "Enter port [56617] [Y/n/number]: "
        read -r answer
        EOS
        chmod +x "$FAKE"

        # (1) CURRENT-BUG shape: no redirect -> hangs holding the pty.
        SESSION="argo_prompt_bug_$$"
        screen -dmS "$SESSION" "$FAKE" serve
        sleep 2
        if screen -ls 2>/dev/null | grep -q "\\.${SESSION}[[:space:]]"; then
          echo "unredirected=alive"
        else
          echo "unredirected=exited"
        fi
        screen -S "$SESSION" -X quit >/dev/null 2>&1 || true

        # (2) FIXED shape: the engine's own launch line, fake binary.
        SESSION="argo_prompt_fix_$$"
        %(fake_launch)s
        sleep 2
        if screen -ls 2>/dev/null | grep -q "\\.${SESSION}[[:space:]]"; then
          echo "redirected=alive"
        else
          echo "redirected=exited"
        fi
        screen -S "$SESSION" -X quit >/dev/null 2>&1 || true
        """
    ) % {"fake_launch": fake_launch}

    out = _run_screen_harness(harness)
    results = dict(
        line.split("=", 1) for line in out.stdout.splitlines() if "=" in line
    )
    assert results.get("unredirected") == "alive", (
        "expected the un-redirected launcher to hang at the prompt "
        f"(got {results}); if this fails the test no longer reproduces the bug"
    )
    assert results.get("redirected") == "exited", (
        f"stdin redirect failed to prevent the hang (got {results})"
    )


# ---------------------------------------------------------------------------
# Part 2: automatic session-output capture in the timeout branch
# ---------------------------------------------------------------------------


def test_timeout_branch_calls_the_capture_helpers() -> None:
    """The start-timeout branch must attempt an automatic dump for screen and
    tmux before falling back to manual-inspection instructions."""
    src = _engine_source()
    body = _function_body(src, "mode_server")
    timeout_idx = body.index("did not start listening")
    tail = body[timeout_idx:]
    assert "_dump_session_output_screen" in tail
    assert "_dump_session_output_tmux" in tail


def test_capture_helpers_never_fail_the_caller() -> None:
    """Both helpers must be guarded at every step.

    They run inside a failure path that is already dying; a helper that itself
    errored (missing binary, dead session, unwritable TMPDIR) would replace a
    useful diagnostic with a confusing one. Contract: degrade to a silent
    no-op, never die.
    """
    src = _engine_source()
    for name in ("_dump_session_output_screen", "_dump_session_output_tmux"):
        body = _function_body(src, name)
        assert "command -v" in body, f"{name} must check its binary exists"
        assert "return 0" in body, f"{name} must have guarded early returns"
        assert " die " not in body, f"{name} must never die"
        assert "mktemp" in body, f"{name} should use mktemp for scratch"


@pytest.mark.skipif(shutil.which("screen") is None, reason="screen not installed")
def test_screen_capture_surfaces_the_prompt_text() -> None:
    """End-to-end: a hung session's prompt reaches stderr via the helper.

    This is the payoff of the whole change -- the 2026-08-10 incident required
    a manual ``screen -r`` to see this text.
    """
    src = _engine_source()
    helpers = "\n".join(
        _function_body(src, name)
        for name in (
            "_dump_session_output_capture",
            "_dump_session_output_screen",
        )
    )

    harness = textwrap.dedent(
        """
        set -uo pipefail
        err() {{ printf '[err] %s\\n' "$*" >&2; }}
        {helpers}

        FAKE="$PWD/fakeproxy"
        cat > "$FAKE" <<'EOS'
        #!/bin/bash
        echo "WARNING | [config] Warning: Port 64742 is already in use."
        echo -n "Enter port [56617] [Y/n/number]: "
        read -r answer
        EOS
        chmod +x "$FAKE"

        SESSION="argo_capture_$$"
        screen -dmS "$SESSION" "$FAKE" serve
        sleep 1
        _dump_session_output_screen "$SESSION"
        screen -S "$SESSION" -X quit >/dev/null 2>&1 || true

        # A session that does not exist must produce NOTHING.
        _dump_session_output_screen "no_such_session_$$"
        """
    ).format(helpers=helpers)

    out = _run_screen_harness(harness)
    stderr = out.stderr
    assert "Port 64742 is already in use" in stderr, (
        f"captured output missing the actual error; stderr was:\n{stderr}"
    )
    assert "Enter port" in stderr, "captured output missing the prompt line"
    assert "captured screen session" in stderr, "capture header missing"
    # Exactly one capture block: the nonexistent session must be a no-op.
    assert stderr.count("--- end captured output ---") == 1, (
        "a nonexistent session should produce no capture block"
    )


@pytest.mark.skipif(shutil.which("screen") is None, reason="screen not installed")
def test_capture_strips_trailing_blank_padding() -> None:
    """``screen -X hardcopy`` pads to the full terminal height.

    Unstripped, a 3-line error arrives as ~20 blank lines with the content at
    the top, which reads as a broken dump. The helper strips trailing blanks.
    """
    src = _engine_source()
    helpers = "\n".join(
        _function_body(src, name)
        for name in (
            "_dump_session_output_capture",
            "_dump_session_output_screen",
        )
    )
    harness = textwrap.dedent(
        """
        set -uo pipefail
        err() {{ printf '[err] %s\\n' "$*" >&2; }}
        {helpers}
        FAKE="$PWD/fakeproxy"
        printf '#!/bin/bash\\necho SOLE_LINE\\nread -r x\\n' > "$FAKE"
        chmod +x "$FAKE"
        SESSION="argo_pad_$$"
        screen -dmS "$SESSION" "$FAKE" serve
        sleep 1
        _dump_session_output_screen "$SESSION"
        screen -S "$SESSION" -X quit >/dev/null 2>&1 || true
        """
    ).format(helpers=helpers)

    out = _run_screen_harness(harness)
    lines = out.stderr.splitlines()
    start = next(i for i, ln in enumerate(lines) if "captured screen session" in ln)
    end = next(i for i, ln in enumerate(lines) if "end captured output" in ln)
    payload = lines[start + 1 : end]
    assert any("SOLE_LINE" in ln for ln in payload), f"content missing: {payload}"
    assert payload[-1].strip() != "", (
        f"trailing blank padding was not stripped: {payload!r}"
    )


def test_engine_copies_stay_byte_identical() -> None:
    """The root ``argo-anywhere.sh`` and the vendored package copy must match.

    D-001/D-028: the engine is vendored VERBATIM as package data. Editing one
    copy and not the other ships a package whose engine differs from the repo's
    -- and the divergence is invisible until a user hits the changed path.
    """
    repo_root = Path(__file__).resolve().parent.parent
    root_copy = repo_root / "argo-anywhere.sh"
    if not root_copy.exists():  # pragma: no cover - sdist/wheel layout
        pytest.skip("root engine copy not present in this layout")
    with engine_path() as vendored:
        assert root_copy.read_bytes() == vendored.read_bytes(), (
            "argo-anywhere.sh and src/argo_anywhere/engine/argo-anywhere.sh "
            "have diverged -- copy the edited one over the other"
        )
