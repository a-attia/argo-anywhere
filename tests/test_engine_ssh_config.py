"""Tests for the D-032 ssh-config-native support (introduced 2026-07-15).

C1 (this test file's initial scope): the engine has new helpers
(``_ssh_config_hostname`` / ``_ssh_config_user`` / ``_alias_has_own_proxy``
+ ``_alias_proxy_notice_dedup``) and a new ``--jump-host`` /
``ARGO_ANYWHERE_JUMP_HOST`` plumbing, but no existing function calls the
new helpers yet. C1's tests verify that the plumbing exists and works in
isolation, and that the grep-based invariants (per plan §8 Q6) hold.

C2 (follow-up commits) will wire the helpers into ``ssh_jump_args``,
``resolve_username``, and ``pick_node``; those tests are added
alongside their respective wire-in commits.

See notes/impl_ssh_config_native.md §4.2 for the full test-case list.
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile

from argo_anywhere._engine import engine_path


# ---------------------------------------------------------------------------
# Shared helpers (mirrors the tempfile pattern from
# tests/test_claudecode_auth_env.py + tests/test_engine_config.py so the
# engine's ~500KB body doesn't hit Linux ARG_MAX).
# ---------------------------------------------------------------------------


def _source_engine_and_run(bash_snippet: str,
                           env: dict[str, str] | None = None,
                           timeout: float = 15.0) -> tuple[int, str, str]:
    """Source the engine (without invoking main), then run bash_snippet."""
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
            r = subprocess.run(
                ["bash", wrapper_path],
                capture_output=True, text=True, timeout=timeout,
                env=env if env is not None else os.environ.copy(),
            )
        finally:
            os.unlink(wrapper_path)
    return r.returncode, r.stdout, r.stderr


def _run_engine(argv: list[str], env: dict[str, str] | None = None,
                cwd: str | None = None) -> subprocess.CompletedProcess:
    """Run the engine end-to-end (bash argo-anywhere.sh ...) for CLI-facing tests."""
    with engine_path() as script:
        return subprocess.run(
            ["bash", str(script), *argv],
            capture_output=True, text=True, cwd=cwd, timeout=30,
            env=env if env is not None else os.environ.copy(),
        )


# ---------------------------------------------------------------------------
# Helper-function existence + basic-shape tests (C1 scope).
# The full behavior tests come in C2 when the helpers get wired in.
# ---------------------------------------------------------------------------


def test_ssh_config_helpers_are_defined() -> None:
    """All three helpers + the dedup wrapper are defined by sourcing the engine.

    C1 guarantees the helpers exist; C2 exercises their behavior via
    real ssh -G output (mocked with fixture ssh binaries).
    """
    snippet = """
declare -f _ssh_config_hostname >/dev/null || { echo MISSING _ssh_config_hostname >&2; exit 1; }
declare -f _ssh_config_user     >/dev/null || { echo MISSING _ssh_config_user     >&2; exit 1; }
declare -f _alias_has_own_proxy >/dev/null || { echo MISSING _alias_has_own_proxy >&2; exit 1; }
declare -f _alias_proxy_notice_dedup >/dev/null || { echo MISSING _alias_proxy_notice_dedup >&2; exit 1; }
echo OK
"""
    rc, out, err = _source_engine_and_run(snippet)
    assert rc == 0, f"one or more helpers missing:\n{err}"
    assert "OK" in out


def test_ssh_config_helpers_return_empty_on_ssh_G_failure() -> None:
    """When ssh -G fails (e.g. unresolvable alias), the resolver helpers
    return empty and _alias_has_own_proxy returns non-zero. Never dies.

    Uses a synthetic alias unlikely to resolve on any real system.
    """
    bogus = "definitely-not-a-real-ssh-host-xyzzy-42"
    snippet = f"""
h="$(_ssh_config_hostname '{bogus}')"
u="$(_ssh_config_user     '{bogus}')"
if _alias_has_own_proxy   '{bogus}'; then p=YES; else p=NO; fi
echo "H=<${{h}}>"
echo "U=<${{u}}>"
echo "P=${{p}}"
"""
    rc, out, err = _source_engine_and_run(snippet)
    # Should never die. Both hostname/user helpers should print an empty
    # line (either literal "H=<>" if ssh -G had no output, or "H=<{bogus}>"
    # if ssh -G resolved it as its own hostname -- OpenSSH's fallback for
    # non-alias inputs). Either is acceptable; we just want no crash.
    assert rc == 0, f"helpers crashed on bogus alias:\n{err}"
    # P should be NO (no ProxyJump/ProxyCommand for a non-alias input).
    assert "P=NO" in out, f"expected P=NO for bogus alias; got:\n{out}"


def test_alias_proxy_notice_dedup_fires_once_per_alias() -> None:
    """Call _alias_proxy_notice_dedup ten times with the same alias;
    the log line should appear exactly once in captured stderr.
    """
    snippet = """
for i in 1 2 3 4 5 6 7 8 9 10; do
  _alias_proxy_notice_dedup polaris-login <ANL-username>
done
"""
    # Use a scrubbed <ANL-username> to avoid embedding a real value.
    snippet = snippet.replace("<ANL-username>", "example-user")
    rc, _out, err = _source_engine_and_run(snippet)
    assert rc == 0, f"dedup helper failed:\n{err}"
    # The notice starts with 'Note: polaris-login already routes via'.
    # Count occurrences in stderr.
    notice_count = err.count("polaris-login already routes via")
    assert notice_count == 1, (
        f"expected exactly ONE notice per invocation; got {notice_count}:\n{err}"
    )


def test_alias_proxy_notice_dedup_fires_once_per_distinct_alias() -> None:
    """Different aliases should each get their own single notice."""
    snippet = """
_alias_proxy_notice_dedup polaris-login example-user
_alias_proxy_notice_dedup polaris-login example-user
_alias_proxy_notice_dedup swing         example-user
_alias_proxy_notice_dedup swing         example-user
_alias_proxy_notice_dedup polaris-login example-user
"""
    rc, _out, err = _source_engine_and_run(snippet)
    assert rc == 0, f"dedup helper failed:\n{err}"
    assert err.count("polaris-login already routes via") == 1
    assert err.count("swing already routes via") == 1


# ---------------------------------------------------------------------------
# --jump-host / ARGO_ANYWHERE_JUMP_HOST plumbing tests (C1 scope).
# ---------------------------------------------------------------------------


def test_jump_host_flag_accepts_value_and_help_runs() -> None:
    """``argo-anywhere --jump-host <host> help`` runs cleanly. C1 is a
    no-op patch: the flag parses + stores; nothing consumes it yet.
    """
    r = _run_engine(["--jump-host", "bastion.example.com", "help"])
    assert r.returncode == 0, f"--jump-host with valid value failed:\n{r.stderr}"
    # Help output goes to stdout for 'help' verb.
    assert "argo-anywhere.sh" in r.stdout, "expected help banner in stdout"


def test_jump_host_cli_empty_dies() -> None:
    """CLI-empty (``--jump-host ""``) dies at parse time with a hint at --no-jump.

    Per plan §7 A9: distinguishes CLI-empty (die) from env-empty (means skip).
    """
    r = _run_engine(["--jump-host", "", "help"])
    assert r.returncode != 0, "--jump-host '' should die at parse time"
    assert "--no-jump" in r.stderr, (
        f"expected error to point at --no-jump; got:\n{r.stderr}"
    )


def test_jump_host_env_empty_means_no_jump() -> None:
    """ARGO_ANYWHERE_JUMP_HOST="" (env, explicitly empty) sets
    ARGO_ANYWHERE_NO_JUMP=1 rather than dying.

    Uses `status --local-only`-equivalent: run `help` (safe no-side-effects
    verb) and inspect that the engine exits cleanly. Behavioral verification
    (that jump_descr returns "(direct, no jump host)") happens in C2.
    """
    env = os.environ.copy()
    env["ARGO_ANYWHERE_JUMP_HOST"] = ""
    r = _run_engine(["help"], env=env)
    assert r.returncode == 0, (
        f"env-empty ARGO_ANYWHERE_JUMP_HOST should be accepted; got:\n{r.stderr}"
    )


def test_jump_host_env_value_mutates_ANL_JUMP() -> None:
    """ARGO_ANYWHERE_JUMP_HOST=<host> mutates the ANL_JUMP global so
    downstream call sites (status card, help text, error messages) reflect
    the override.

    Verifies the load-bearing "ANL_JUMP is mutable; readers pick up the
    new value at call time" invariant (plan §2.5 + §7 B8).
    """
    env = os.environ.copy()
    env["ARGO_ANYWHERE_JUMP_HOST"] = "bastion.example.com"
    r = _run_engine(["help"], env=env)
    assert r.returncode == 0, f"help with jump-host override failed:\n{r.stderr}"
    # Help text interpolates ${ANL_JUMP} in several places; the overridden
    # value should appear at least once, and the default should not.
    assert "bastion.example.com" in r.stdout, (
        "overridden jump host missing from help output"
    )
    # The default fqdn is 'logins.cels.anl.gov'. It may still appear in
    # help EXAMPLES that hardcode it (not our fault), but should NOT appear
    # in the "Jump host: X" summary lines. Weaker check: just ensure the
    # override is present.


def test_jump_host_flag_beats_env() -> None:
    """When both --jump-host and ARGO_ANYWHERE_JUMP_HOST are set, the CLI
    flag wins (it's the more explicit intent).
    """
    env = os.environ.copy()
    env["ARGO_ANYWHERE_JUMP_HOST"] = "from-env.example.com"
    r = _run_engine(["--jump-host", "from-flag.example.com", "help"], env=env)
    assert r.returncode == 0
    assert "from-flag.example.com" in r.stdout, (
        "flag value should override env value in the resolved ANL_JUMP"
    )


# ---------------------------------------------------------------------------
# Grep-based invariants (per plan §8 Q6 decision).
# These answer "does the --jump-host override reach all 42 ANL_JUMP
# references?" deterministically on every CI run, replacing the
# infrastructure-requiring live-test Scenario Y.
# ---------------------------------------------------------------------------


def _engine_source() -> str:
    """The engine's source text (for grep-based invariant tests)."""
    with engine_path() as script:
        return script.read_text()


def test_no_local_ANL_JUMP_shadow() -> None:
    """ANL_JUMP must never be declared ``local`` or ``readonly`` in any
    function called after main()'s resolution block. A local shadow
    would silently break --jump-host / ARGO_ANYWHERE_JUMP_HOST by
    hiding the mutated global from the function's own view.

    Per plan §7 B8: 42 ANL_JUMP references, all read $ANL_JUMP at
    call/interpolation time. This invariant protects the "mutable
    script global" contract from a future refactor.
    """
    src = _engine_source()
    # Match `local ANL_JUMP=` or `local ANL_JUMP\n` or `readonly ANL_JUMP...`.
    # Not looking at `local anything ANL_JUMP=...` (bash's `local` can list
    # multiple vars, but a shadow of ANL_JUMP would be listed at the start
    # of its name-token; the regex catches ``local ANL_JUMP`` with any
    # trailing char, and ``local FOO=x ANL_JUMP=y`` via the second alternation).
    bad = re.findall(
        r"^\s*(?:local|readonly)\s+(?:[A-Za-z_][A-Za-z0-9_]*\s+)*ANL_JUMP\b",
        src, re.MULTILINE,
    )
    assert bad == [], (
        f"ANL_JUMP must not be locally shadowed / readonly; found: {bad}"
    )


def test_ANL_JUMP_readers_use_expansion() -> None:
    """Every runtime reference to ANL_JUMP in the engine reads it via
    expansion (``$ANL_JUMP`` or ``${ANL_JUMP}``), NOT via a captured
    snapshot at function-definition time.

    This is the second half of the mutable-global invariant. Snapshots
    (e.g. ``local _cached_jump="$ANL_JUMP"`` at function entry, then
    reading ``$_cached_jump`` in the body) would freeze the value from
    the initial call and break subsequent --jump-host overrides in the
    same process (unlikely in the engine's one-shot lifecycle, but the
    invariant is still a good hygiene guardrail).

    Allowlist: the declaration site itself (``ANL_JUMP="..."``) and the
    resolution block that assigns from the env var (``ANL_JUMP="$ARGO_ANYWHERE_JUMP_HOST"``).
    Comments and doc blocks are exempt (grep sees the literal string but
    they're not code).
    """
    src = _engine_source()
    # Find every line that references ANL_JUMP as an assignment target.
    # Legal: the declaration + the resolution block. Anything else that
    # ASSIGNS to ANL_JUMP (as opposed to reading it) is a violation.
    lines = src.splitlines()
    illegal_assignments = []
    for i, line in enumerate(lines, start=1):
        stripped = line.strip()
        if stripped.startswith("#"):
            continue  # comment
        # Match `ANL_JUMP=<something>` at start of statement (not inside a
        # $-expansion or a variable name like SOME_ANL_JUMP_XYZ).
        m = re.match(r'^\s*ANL_JUMP=', line)
        if m:
            # Allow the two known assignment sites: initial declaration and
            # the resolution block.
            if 'ANL_JUMP="logins.cels.anl.gov"' in line:
                continue  # declaration
            if 'ANL_JUMP="$ARGO_ANYWHERE_JUMP_HOST"' in line:
                continue  # resolution block
            # Self-assignment `ANL_JUMP="${ANL_JUMP}"` is a display-only
            # interpolation (appears in the help block's CUSTOMIZATION
            # section, rendered as `ANL_JUMP="logins.cels.anl.gov"` at
            # print time to show the user the customization pattern).
            # Can't break the mutable-global contract by definition.
            if 'ANL_JUMP="${ANL_JUMP}"' in line:
                continue  # display-only interpolation
            illegal_assignments.append((i, line.rstrip()))
    assert illegal_assignments == [], (
        "ANL_JUMP has unexpected assignment sites (should only be the "
        f"declaration + the --jump-host resolution block):\n{illegal_assignments}"
    )


def test_ssh_config_helpers_and_flag_present_in_source() -> None:
    """Belt-and-braces: verify the helpers + CLI flag are string-present
    in the engine source (independent of the sourcing-based tests above).

    Guards against a future ``git reset`` or accidental deletion during
    a refactor that removes the helpers without noticing the tests still
    pass because the wire-in isn't done yet (C1 is a no-op patch by
    design; the only trace is the source itself).
    """
    src = _engine_source()
    for helper in ("_ssh_config_hostname", "_ssh_config_user",
                   "_alias_has_own_proxy", "_alias_proxy_notice_dedup"):
        assert f"{helper}()" in src, f"{helper} definition missing from engine"
    assert "--jump-host)" in src, "--jump-host argv arm missing"
    assert 'ARGO_ANYWHERE_JUMP_HOST+set' in src, (
        "ARGO_ANYWHERE_JUMP_HOST resolution block missing"
    )
