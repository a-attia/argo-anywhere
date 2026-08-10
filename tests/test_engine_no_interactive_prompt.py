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


def _screen_launch_line(body: str) -> str:
    """Return mode_server's ``screen -dmS`` launch command, joined to one line.

    The command spans three physical lines (backslash continuations) since the
    tee was added, so tests must not assume a single-line match.
    """
    match = re.search(
        r"^\s*screen -dmS (?:.*\\\n)*.*$", body, re.MULTILINE
    )
    assert match, "screen launch command not found in mode_server"
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


def test_all_three_launchers_tee_to_a_durable_log() -> None:
    """Every launcher must write argo-proxy's output to ``$_PROXY_LOG``.

    This is the LOG-DURABILITY COROLLARY and it is not optional: the stdin
    redirect makes a prompting argo-proxy die in ~1s, so the screen/tmux
    session is reaped ~18s before the start-timeout fires. A session-only
    capture therefore has nothing to read in the *common* failure -- the two
    halves of the fix would cancel out. The log file outlives the session.
    """
    src = _engine_source()
    body = _function_body(src, "mode_server")
    assert re.search(r'^\s*local _PROXY_LOG=', body, re.MULTILINE), (
        "_PROXY_LOG must be defined in mode_server"
    )
    for pattern, label in (
        (r"^\s*screen -dmS .*\n?.*tee -a", "screen"),
        (r"^\s*_tmux_cmd=.*tee -a", "tmux"),
        (r"^\s*nohup .*argo-proxy.*_PROXY_LOG", "nohup"),
    ):
        assert re.search(pattern, body, re.MULTILINE), (
            f"{label} launcher must persist output to _PROXY_LOG; without it "
            "a fast-exiting argo-proxy leaves no diagnostic at all"
        )


def test_timeout_branch_prefers_the_durable_log() -> None:
    """The log must be consulted BEFORE the live-session capture.

    Ordering is the whole point: the log covers the fast-death case (common),
    the session capture covers the still-hung case (rare). If the session
    capture ran first it would usually print nothing and the real error would
    follow confusingly, or be skipped.
    """
    src = _engine_source()
    body = _function_body(src, "mode_server")
    tail = body[body.index("did not start listening") :]
    log_at = tail.index("_PROXY_LOG")
    dump_at = tail.index("_dump_session_output_screen")
    assert log_at < dump_at, "durable log must be surfaced before session capture"
    # And the session capture must be conditional on the log having been empty.
    assert re.search(r'\[ "\$_dumped" -eq 1 \] \|\| _dump_session_output', tail), (
        "session capture should only run when the log produced nothing"
    )


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

    screen_launch = _screen_launch_line(body)
    assert "/dev/null" in screen_launch, (
        "screen launcher lost its stdin redirect -- a port-collision prompt "
        "will hang forever inside the detached session"
    )

    tmux_cmd = re.search(r"^\s*_tmux_cmd=.*$", body, re.MULTILINE)
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
    line = _screen_launch_line(body)
    assert '\'"$0" serve --port "$2" < /dev/null 2>&1 | tee -a "$1"\'' in line, (
        "screen launcher must pass binary/log/port as $0/$1/$2, not interpolate"
    )
    # Both paths must appear AFTER the quoted script (i.e. as the $0/$1 args).
    script_end = line.index("'", line.index("sh -c '") + len("sh -c '"))
    tail = line[script_end:]
    assert "argo-proxy" in tail, (
        "argo-proxy path must be the $0 argument, outside the script string"
    )
    assert "_PROXY_LOG" in tail, (
        "log path must be the $1 argument, outside the script string"
    )
    assert "PROXY_PORT" in tail, (
        "port must be the $2 argument (Q10: overrides the shared config file)"
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
    # Reuse the ENGINE'S OWN launch shape, with our fake binary substituted,
    # so this test tracks the real code rather than a copy of it.
    real_launch = _screen_launch_line(body)
    fake_launch = (
        real_launch.replace('"${SCREEN_SESSION}"', '"$SESSION"')
        .replace('"${venv}/bin/argo-proxy"', '"$FAKE"')
        .replace('"${_PROXY_LOG}"', '"$LOGFILE"')
        .replace('"${PROXY_PORT}"', '"$TESTPORT"')
    )
    assert fake_launch != real_launch, "substitution failed; launch line changed shape"

    harness = textwrap.dedent(
        """
        set -uo pipefail
        FAKE="$PWD/fakeproxy"
        LOGFILE="$PWD/argoproxy.out"
        TESTPORT=64742
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


def test_all_launchers_pass_port_explicitly() -> None:
    """Every launcher must pass ``--port``; the config file is not authoritative.

    Q10: on CELS ``$HOME`` is one NFS mount shared by every compute node, so
    ``~/.config/argoproxy/config.yaml`` is a SINGLE file for all of them.
    Relying on its ``port:`` made a second node on a second port impossible
    without hand-editing the shared file (reproduced in the field
    2026-08-10). ``--port`` becomes an env override at config load, so the
    requested port wins AND the shared file is left untouched.
    """
    body = _function_body(_engine_source(), "mode_server")
    screen = _screen_launch_line(body)
    assert "--port" in screen, "screen launcher must pass --port"

    tmux = re.search(r"^\s*_tmux_cmd=.*$", body, re.MULTILINE)
    assert tmux and "--port" in tmux.group(0), "tmux launcher must pass --port"

    nohup = re.search(r"^\s*nohup .*argo-proxy.*$", body, re.MULTILINE)
    assert nohup and "--port" in nohup.group(0), "nohup launcher must pass --port"


def test_config_port_mismatch_is_a_note_not_a_refusal() -> None:
    """A disagreeing config must no longer abort the run.

    With ``--port`` passed explicitly the file's value is harmless, so
    refusing would block the multi-node case for no reason. It stays
    *reported*, because it usually means the user kept an out-of-date file.
    """
    body = _function_body(_engine_source(), "mode_server")
    seg = body[body.index("cfg_port=") : body.index("# 5) Already listening")]
    assert "die " not in seg, (
        "a config/port disagreement must not abort now that --port overrides it"
    )
    assert "Refusing to launch argo-proxy" not in seg
    assert "--port" in seg, "the note should explain that --port overrides"


def test_prompt_guidance_does_not_push_users_to_rewrite_shared_config() -> None:
    """The pre-prompt hint must not claim ``[k]eep`` gets the run refused.

    That was true before ``--port``; repeating it now would push users into
    rewriting a file shared by every node -- the exact thing that breaks
    multi-node use.
    """
    body = _function_body(_engine_source(), "mode_server")
    # The hint block is keyed off _pc_existing, just before the config prompt.
    start = body.index("_pc_existing=")
    seg = body[start : body.index("handle_config_file", start)]
    assert "this run will be refused" not in seg, (
        "stale guidance: [k]eep no longer causes a refusal"
    )
    assert "shared" in seg.lower(), (
        "the hint should mention the shared-$HOME consequence"
    )


def test_log_display_filters_the_startup_banner() -> None:
    """Log tails must drop argo-proxy's ASCII banner.

    Live-test finding (2026-08-10): a failed start writes ~17 lines, 8 of
    which are the banner, so a plain ``tail -n 20`` shows the banner and
    buries the one line that matters. Both display sites must use the filter.
    """
    src = _engine_source()
    body = _function_body(src, "mode_server")
    tail = body[body.index("did not start listening") - 3000 :]
    assert "tail -n 20 \"$_PROXY_LOG\"" not in tail, (
        "raw tail buries the error under the banner; use _log_tail_meaningful"
    )
    assert "tail -n 30 \"$_PROXY_LOG\"" not in tail
    assert tail.count("_log_tail_meaningful") >= 2, (
        "both the refusal path and the timeout path must filter"
    )


def test_banner_filter_keeps_the_error_and_drops_the_art() -> None:
    """Behavioural: feed a real captured failure log through the filter."""
    src = _engine_source()
    helper = _function_body(src, "_log_tail_meaningful")
    # Verbatim shape of a real failed start (captured on compute-386-01).
    sample = (
        "\n"
        " █████╗ ██████╗ ██████╗  ██████╗\n"
        "██╔══██╗██╔══██╗██╔════╝ ██╔═══██╗\n"
        "╚═╝  ╚═╝╚═╝  ╚═╝ ╚═════╝  ╚═════╝\n"
        "\n"
        "2026-08-10 13:08:27 | INFO     | [cli] ARGO PROXY v3.2.3\n"
        "2026-08-10 13:08:29 | WARNING  | [config] Warning: Port 64742 is already in use.\n"
        "Enter port [64185] [Y/n/number]: 2026-08-10 13:08:29 | ERROR | [cli] "
        "An error occurred while starting the server: EOF when reading a line\n"
    )
    harness = "set -uo pipefail\n" + helper + '\n_log_tail_meaningful "$1" 30\n'
    with tempfile.TemporaryDirectory() as td:
        log = Path(td) / "argoproxy.out"
        log.write_text(sample)
        script = Path(td) / "h.sh"
        script.write_text(harness)
        out = subprocess.run(
            ["bash", str(script), str(log)],
            capture_output=True,
            text=True,
            timeout=30,
        )
    assert out.returncode == 0, out.stderr
    assert "Port 64742 is already in use" in out.stdout
    assert "EOF when reading a line" in out.stdout
    assert "█" not in out.stdout and "╔" not in out.stdout, (
        f"banner glyphs survived the filter:\n{out.stdout}"
    )
    assert "" == "".join(ln for ln in out.stdout.splitlines() if not ln.strip()), (
        "blank padding should be dropped too"
    )


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
def test_log_survives_the_session_that_dies_from_the_redirect() -> None:
    """The regression that nearly shipped: (a) defeats (b) without the log.

    Drives the engine's real screen launch line with a fake argo-proxy that
    prompts. Because stdin is closed the fake dies at once and screen reaps
    the session -- so this asserts BOTH that the session is gone (proving the
    hazard is real, not hypothetical) AND that the prompt text is still
    recoverable from the teed log afterwards.
    """
    src = _engine_source()
    body = _function_body(src, "mode_server")
    launch = re.search(
        r"^\s*screen -dmS .*?\n(?:.*?\n)*?.*?\"\$\{_PROXY_LOG\}\"", body, re.MULTILINE
    )
    assert launch, "multi-line screen launch not found"
    fake_launch = (
        launch.group(0)
        .replace('"${SCREEN_SESSION}"', '"$SESSION"')
        .replace('"${venv}/bin/argo-proxy"', '"$FAKE"')
        .replace('"${_PROXY_LOG}"', '"$LOGFILE"')
        .replace('"${PROXY_PORT}"', '"$TESTPORT"')
    )
    assert "$FAKE" in fake_launch and "$LOGFILE" in fake_launch

    harness = textwrap.dedent(
        """
        set -uo pipefail
        FAKE="$PWD/fakeproxy"
        LOGFILE="$PWD/argoproxy.out"
        TESTPORT=64742
        cat > "$FAKE" <<'EOS'
        #!/bin/bash
        echo "WARNING | [config] Warning: Port 64742 is already in use."
        echo -n "Enter port [56617] [Y/n/number]: "
        read -r answer || { echo; echo "EOFError: EOF when reading a line"; exit 1; }
        EOS
        chmod +x "$FAKE"
        : > "$LOGFILE"
        SESSION="argo_durable_$$"
        %(fake_launch)s
        sleep 3
        if screen -ls 2>/dev/null | grep -q "\\.${SESSION}[[:space:]]"; then
          echo "session=alive"
          screen -S "$SESSION" -X quit >/dev/null 2>&1 || true
        else
          echo "session=reaped"
        fi
        echo "logbytes=$(wc -c < "$LOGFILE" | tr -d ' ')"
        echo "--- LOG ---"
        cat "$LOGFILE"
        """
    ) % {"fake_launch": fake_launch}

    out = _run_screen_harness(harness)
    results = dict(
        line.split("=", 1) for line in out.stdout.splitlines() if "=" in line
    )
    assert results.get("session") == "reaped", (
        "expected the session to be reaped after the fast EOF death -- if it "
        "survives, the premise of the durable-log fix has changed"
    )
    assert int(results.get("logbytes", "0")) > 0, "log file is empty"
    assert "Port 64742 is already in use" in out.stdout, (
        f"prompt text did not survive in the log; stdout:\n{out.stdout}"
    )
    assert "EOFError" in out.stdout, "the EOF death itself should be logged"


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
