"""Tests for handle_config_file's k/b/d/m/a prompt (2026-07-15).

Background (documented in notes/impl_pyyaml_and_menu_fix.md):

* Field report 2026-07-15 (compute-386-02): a user's ANL compute node
  had argo-proxy 3.2.2 installed but PyYAML missing from the venv.
  ``write_argoproxy_config`` fell into its die-hard path
  ("Refusing to write argo-proxy config without PyYAML for safe merge"),
  but BEFORE that, ``handle_config_file`` offered the ``[m]`` option
  which the same function then rejected with
  ``[warn] YAML merge not supported here.`` The user cycled through
  the prompt four times before picking ``[k]``.

Fix (this commit):

* ``handle_config_file`` computes ``allow_merge`` from ``(file suffix,
  tool availability)`` BEFORE rendering the prompt. Only offers ``[m]``
  when it can actually do work (JSON + jq present today; YAML never,
  because the YAML writer already merges before returning). Fallback
  ``m|M`` arm teaches the user why the option is missing for the file
  they're looking at (muscle-memory users still get help, not a bare
  "Unrecognized choice").

* Silently also fixes JSON-without-jq (previously offered [m], rejected
  with a warn; now the option is suppressed correctly).

Tests source the engine as a wrapped tempfile (per the existing
tests/test_claudecode_auth_env.py pattern; avoids Linux ARG_MAX limits).
Each test constructs a scratch config file + a scratch "proposed" file
via a stub writer, then feeds a canned answer to the prompt via stdin.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

from argo_anywhere._engine import engine_path


def _source_engine_and_run(bash_snippet: str,
                           stdin_text: str = "",
                           env: dict[str, str] | None = None,
                           timeout: float = 15.0,
                           use_pty: bool = False) -> tuple[int, str, str]:
    """Source the engine (without invoking main), then run bash_snippet.

    Mirrors the pattern in tests/test_claudecode_auth_env.py. Writes the
    wrapper to a tempfile and invokes ``bash <tempfile>`` (not
    ``bash -c <wrapper>``) so the ~500KB engine body doesn't exceed
    Linux's ARG_MAX limit.

    ``use_pty=True`` runs the bash under a pseudo-TTY on stdin so the
    engine's ``ask`` helper (which does ``[ -t 0 ]`` and auto-answers
    the default when stdin is a pipe) actually consumes ``stdin_text``.
    Required for any test that needs to feed a specific answer to a
    k/b/d/m/a-style prompt.
    """
    with engine_path() as script:
        body = script.read_text()
        assert body.rstrip().endswith('main "$@"'), (
            "engine's last statement changed; update the test's stripping "
            "logic to match"
        )
        body_no_main = body.rstrip()[: -len('main "$@"')]
        wrapper = body_no_main + "\n" + bash_snippet + "\n"
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".sh", delete=False,
        ) as tf:
            tf.write(wrapper)
            wrapper_path = tf.name
        try:
            if use_pty:
                # Give bash a real TTY on stdin so ``ask`` reads from
                # our input instead of auto-defaulting. stdout/stderr
                # stay captured via pipes so we can assert on them.
                #
                # PTY discipline: keep the master (parent_fd) open until
                # after communicate() returns. Closing it too early
                # signals EOF on the slave side, which turns bash's
                # stdin into a closed fd -- ``[ -t 0 ]`` then returns
                # false and ``ask`` falls into its auto-default branch.
                # Since the wrapper snippet runs finite work and exits,
                # communicate() will return naturally when bash is done.
                import pty
                parent_fd, child_fd = pty.openpty()
                proc = None
                try:
                    proc = subprocess.Popen(
                        ["bash", wrapper_path],
                        stdin=child_fd,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                        env=env if env is not None else os.environ.copy(),
                    )
                    os.close(child_fd)  # parent owns the master end now
                    if stdin_text:
                        os.write(parent_fd, stdin_text.encode())
                    # DO NOT close parent_fd here.
                    out, err = proc.communicate(timeout=timeout)
                    return proc.returncode, out, err
                except Exception:
                    if proc is not None:
                        proc.kill()
                        proc.wait()
                    raise
                finally:
                    try:
                        os.close(parent_fd)
                    except OSError:
                        pass
            else:
                r = subprocess.run(
                    ["bash", wrapper_path],
                    input=stdin_text,
                    capture_output=True, text=True, timeout=timeout,
                    env=env if env is not None else os.environ.copy(),
                )
                return r.returncode, r.stdout, r.stderr
        finally:
            os.unlink(wrapper_path)


# ---------------------------------------------------------------------------
# Fix B: [m] option is suppressed when it can't work.
# ---------------------------------------------------------------------------


def _fixture_pair(tmp_path: Path, suffix: str, existing: str, proposed: str
                  ) -> tuple[Path, Path]:
    """Write two files (existing + proposed) with different content so
    handle_config_file reaches the prompt (not the ``cmp -s`` early-return)."""
    target = tmp_path / f"config{suffix}"
    prop = tmp_path / f"proposed{suffix}"
    target.write_text(existing)
    prop.write_text(proposed)
    return target, prop


def _handle_config_file_snippet(target: Path, answer: str) -> str:
    """Bash snippet that defines a stub writer (cp proposed -> dest)
    and calls handle_config_file directly.

    The stub writer is what handle_config_file invokes to produce the
    "proposed" tempfile; we simply copy our pre-made file into place so
    the differ has something concrete to compare against.

    ``answer`` is a legacy parameter kept for readability at call sites;
    it's NOT piped into stdin. The caller provides stdin via
    ``_source_engine_and_run(snippet, stdin_text=..., use_pty=True)``.
    (Piping ``printf | handle_config_file`` would make handle_config_file's
    stdin a pipe, defeating the PTY-based ``ask`` -- ``ask`` would then
    auto-default and the answer would never be consumed.)
    """
    _ = answer  # documentation-only; see docstring
    return f"""
_stub_writer() {{
  local dest="$1"
  cp -- "{target.parent}/proposed{target.suffix}" "$dest"
}}
handle_config_file \\
  "{target}" "test config ({target.name})" _stub_writer
"""


def _path_with_jq_hidden(shim_dir: Path) -> str:
    """Return a PATH that hides jq WITHOUT removing dirs the engine needs.

    Naive approach (remove any dir containing jq) fails on macOS where
    /usr/bin ships jq alongside tr, awk, cp, diff, wc, mktemp -- removing
    /usr/bin leaves the engine unable to run its own preflight (line 111
    dies: "tr: command not found").

    Trick: prepend a scratch dir containing a `jq` stub that exits
    non-zero, so ``command -v jq`` reports success but any actual jq
    invocation would fail. Since ``command -v`` is what our menu-check
    uses, this correctly simulates "jq not usable".

    Wait -- ``command -v jq`` would still return 0 (the stub exists,
    it's just broken). We need ``command -v jq`` to return NON-zero,
    which means: no jq on PATH at all.

    Actual trick: create a stub `jq` that isn't executable
    (``chmod -x``), so it exists but ``command -v`` skips it. Then
    prepend the stub dir so real jqs later on PATH are still found
    via any later dir -- so we must ALSO shadow those. Easier: use a
    PATH that is JUST our stub dir + /usr/bin (for tr/awk/etc.), and
    place a broken jq stub in the stub dir that ``command -v`` won't
    accept.

    Simpler still: bash's ``command -v jq`` uses PATH search and honors
    executable bit. A non-executable file at ``$shim_dir/jq`` blocks jq
    lookup IN THAT DIR but doesn't prevent lookup in later dirs. So:
    prepend ``$shim_dir``, then include only /usr/bin (essentials) and
    skip any dir containing jq.

    Cleanest: create $shim_dir/jq as a non-executable file, put
    $shim_dir first, then include the current PATH MINUS any dir with
    a real jq. Any dir with a real jq gets dropped, but the essentials
    typically live in /usr/bin which on macOS also has jq -- so we
    substitute: include /usr/bin's PARENT-selected essentials as
    symlinks in $shim_dir/.

    OK actual plan:
    1. Symlink the essentials (tr awk cp diff wc mktemp cat printf date
       lsof grep sed head tail sort uniq env python3 python bash sh
       basename dirname mkdir rm chmod ln touch which command) into
       $shim_dir from wherever they live in the real PATH.
    2. Do NOT symlink jq (and provide no jq at all in $shim_dir).
    3. Return PATH = "$shim_dir" (nothing else).

    This guarantees the engine's essentials work AND jq is absent.
    """
    essentials = [
        "tr", "awk", "cp", "diff", "wc", "mktemp", "cat", "printf",
        "date", "grep", "sed", "head", "tail", "sort", "uniq", "env",
        "basename", "dirname", "mkdir", "rm", "chmod", "ln", "touch",
        "which", "bash", "sh", "cmp",
        # Python for any inline heredoc that might run:
        "python3", "python",
    ]
    shim_dir.mkdir(parents=True, exist_ok=True)
    real_path_dirs = os.environ.get("PATH", "").split(":")
    for essential in essentials:
        for d in real_path_dirs:
            candidate = os.path.join(d, essential)
            if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                try:
                    (shim_dir / essential).symlink_to(candidate)
                except FileExistsError:
                    pass
                break
        # If not found, no symlink -- the engine will hit a hard error
        # if it needs it, which surfaces the test-fixture gap loudly.
    # Explicitly do NOT symlink jq. Return only $shim_dir on PATH.
    return str(shim_dir)


def test_yaml_menu_omits_m_option(tmp_path: Path) -> None:
    """For a YAML target, the k/b/d/m/a prompt must NOT show [m].

    The YAML writers merge in-writer, so handle_config_file's [m] would
    be a no-op or fight the writer's ownership decisions. Historical
    behavior was to offer [m] and then reject it via ``[warn] YAML
    merge not supported here``. Fix: don't offer it.
    """
    target, _prop = _fixture_pair(
        tmp_path, ".yaml", "old: value\n", "new: value\n"
    )
    # No PTY needed: we're just inspecting what the menu LOOKS like;
    # ask() will auto-default to 'k' which breaks the loop cleanly.
    snippet = _handle_config_file_snippet(target, "k")
    rc, _out, err = _source_engine_and_run(snippet)
    assert rc == 0, f"snippet failed: {err}"
    # The menu prompt goes to stderr; [m] must not appear in the option
    # list AND the choice-prompt must be [k/b/d/a] not [k/b/d/m/a].
    assert "[m] merge" not in err, (
        f"[m] option was offered for YAML but shouldn't be:\n{err}"
    )
    assert "[k/b/d/a]" in err, (
        f"expected reduced prompt '[k/b/d/a]'; got:\n{err}"
    )
    assert "[k/b/d/m/a]" not in err, (
        f"full [k/b/d/m/a] prompt appeared for YAML; expected reduced:\n{err}"
    )


def test_json_menu_omits_m_when_jq_missing(tmp_path: Path) -> None:
    """For a JSON target without jq on PATH, [m] must NOT be offered.

    Historical behavior was to offer [m] unconditionally for JSON, then
    reject with "Merge requires jq for JSON files. Install jq or pick
    another option." Fix: suppress the option when the tool isn't
    available.
    """
    target, _prop = _fixture_pair(
        tmp_path, ".json",
        '{"old": "value"}\n',
        '{"new": "value"}\n',
    )
    snippet = _handle_config_file_snippet(target, "k")
    env = os.environ.copy()
    env["PATH"] = _path_with_jq_hidden(tmp_path / "shim_bin")
    rc, _out, err = _source_engine_and_run(snippet, env=env)
    assert rc == 0, f"snippet failed: {err}"
    assert "[m] merge" not in err, (
        f"[m] option offered for JSON despite jq absent:\n{err}"
    )
    assert "[k/b/d/a]" in err, (
        f"expected reduced prompt '[k/b/d/a]'; got:\n{err}"
    )


def test_json_menu_includes_m_when_jq_present(tmp_path: Path) -> None:
    """Regression guard for the happy path: JSON + jq on PATH means [m]
    IS offered and works.
    """
    import shutil
    if shutil.which("jq") is None:
        import pytest
        pytest.skip("jq not on PATH; can't exercise the happy path")

    target, _prop = _fixture_pair(
        tmp_path, ".json",
        '{"config_version": "old"}\n',
        '{"config_version": "new"}\n',
    )
    # Feed 'm' through a PTY so ask() actually reads the answer.
    snippet = _handle_config_file_snippet(target, "m")
    rc, _out, err = _source_engine_and_run(snippet, stdin_text="m\n",
                                           use_pty=True)
    assert rc == 0, f"snippet failed: {err}"
    # Full prompt must include [m] this time.
    assert "[m] merge" in err, (
        f"[m] should be offered for JSON when jq is present:\n{err}"
    )
    assert "[k/b/d/m/a]" in err, (
        f"expected full prompt '[k/b/d/m/a]'; got:\n{err}"
    )
    # The merge succeeded (proposed keys landed).
    merged = target.read_text()
    assert '"config_version": "new"' in merged, (
        f"merge should have overwritten config_version; got:\n{merged}"
    )


def test_yaml_m_typed_gives_teaching_warn(tmp_path: Path) -> None:
    """Muscle-memory user types 'm' even though the YAML menu didn't
    advertise it. Expect: a warn that names the specific reason
    (writer already merges before this prompt), then re-prompt.

    Uses a PTY so ask() reads our 'm' and 'k' answers instead of
    auto-defaulting on the first prompt (which would skip the m-branch
    entirely).
    """
    target, _prop = _fixture_pair(
        tmp_path, ".yml", "old: value\n", "new: value\n"
    )
    snippet = _handle_config_file_snippet(target, "m\nk")
    rc, _out, err = _source_engine_and_run(
        snippet, stdin_text="m\nk\n", use_pty=True,
    )
    assert rc == 0, f"snippet failed: {err}"
    # The teaching message must fire and name YAML specifically (not just
    # a generic "unrecognized choice" or the old "YAML merge not supported").
    assert "writer already merges" in err, (
        f"expected YAML-specific teaching warn; got:\n{err}"
    )


def test_json_m_typed_without_jq_gives_teaching_warn(tmp_path: Path) -> None:
    """Muscle-memory user types 'm' for JSON when jq is absent. Expect
    the JSON-specific teaching message (mentions jq)."""
    target, _prop = _fixture_pair(
        tmp_path, ".json",
        '{"old": "value"}\n',
        '{"new": "value"}\n',
    )
    env = os.environ.copy()
    env["PATH"] = _path_with_jq_hidden(tmp_path / "shim_bin")
    snippet = _handle_config_file_snippet(target, "m\nk")
    rc, _out, err = _source_engine_and_run(
        snippet, stdin_text="m\nk\n", env=env, use_pty=True,
    )
    assert rc == 0, f"snippet failed: {err}"
    assert "jq" in err.lower(), (
        f"expected JSON-specific teaching warn mentioning jq; got:\n{err}"
    )


# ---------------------------------------------------------------------------
# Fix A (PyYAML self-heal): not unit-tested here.
#
# ensure_argoproxy_installed requires a real venv with pip to exercise the
# new PyYAML probe + install branch. That's live-only per docs/TESTING.md.
# See notes/impl_pyyaml_and_menu_fix.md §4.3 for the manual verification
# recipe (three-step: fresh install verifies PyYAML present; then pip
# uninstall pyyaml; then re-run verifies the self-heal fires).
# ---------------------------------------------------------------------------
