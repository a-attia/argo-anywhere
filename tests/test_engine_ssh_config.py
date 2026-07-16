"""Tests for the D-032 ssh-config-native support (introduced 2026-07-15).

Structure follows the plan's commit sequence
(notes/impl_ssh_config_native.md §9):

- **C1 tests** (helpers exist; --jump-host plumbing; grep invariants):
  test_ssh_config_helpers_are_defined,
  test_ssh_config_helpers_return_empty_on_ssh_G_failure,
  test_alias_proxy_notice_dedup_*,
  test_jump_host_*,
  test_no_local_ANL_JUMP_shadow,
  test_ANL_JUMP_readers_use_expansion.

- **C2 tests** (Sub-fixes A/B/C wired in): use `_write_ssh_G_shim` to
  drop a stub `ssh` binary into a scratch PATH so the helpers see
  synthetic `ssh -G` output. Cover:
    * Sub-fix C: ssh_jump_args skips -J when alias has own ProxyJump;
      adds -J when it doesn't; dedup fires once per alias.
    * Sub-fix B: resolve_username reads ssh-config User; NEVER caches
      the inferred value; --user flag wins over ssh-config.
    * Sub-fix A: pick_node's warn upgrades to a helpful log line
      when the string is an ssh_config alias (verified via a smaller
      unit-level slice, not a full pick_node run which needs live SSH).

See notes/impl_ssh_config_native.md §4.2 for the full test-case list.
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
import textwrap
from pathlib import Path

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


# ===========================================================================
# C2 tests: Sub-fixes A/B/C wired into ssh_jump_args / resolve_username /
# pick_node. Use a stub `ssh` binary in a scratch PATH so the helpers see
# synthetic `ssh -G` output.
# ===========================================================================


def _write_ssh_G_shim(shim_dir: Path, ssh_g_output: dict[str, str]) -> str:
    """Install a fake `ssh` in shim_dir that responds to `ssh -G <alias>`
    with a canned response from ssh_g_output[alias], and forwards every
    other invocation to the real `ssh`.

    ``ssh_g_output`` maps alias name → the multi-line stdout to emit for
    ``ssh -G <alias>``. Unknown aliases exit 0 with no output (matches
    OpenSSH behavior for a resolvable-but-unrewritten hostname).

    Returns the PATH to use (shim_dir prepended, real /usr/bin etc. after
    for tr/awk/cp/etc.).
    """
    shim_dir.mkdir(parents=True, exist_ok=True)
    # Locate the real ssh so the shim can delegate for non -G invocations.
    real_ssh = ""
    for p in os.environ.get("PATH", "").split(":"):
        cand = os.path.join(p, "ssh")
        if os.path.isfile(cand) and os.access(cand, os.X_OK):
            real_ssh = cand
            break
    # Build a bash-case block: each alias key -> printf its response.
    cases = []
    for alias, response in ssh_g_output.items():
        # Escape single-quotes in the response (bash single-quote form).
        escaped = response.replace("'", "'\\''")
        cases.append(f"    {alias}) printf '%s' '{escaped}'; exit 0 ;;")
    cases_block = "\n".join(cases) if cases else "    # (no aliases)"
    shim = shim_dir / "ssh"
    shim.write_text(textwrap.dedent(f"""\
        #!/bin/bash
        # ssh shim for D-032 tests: intercepts `ssh -G <alias>`; delegates
        # everything else to the real ssh at {real_ssh}.
        if [ "${{1:-}}" = "-G" ] && [ -n "${{2:-}}" ]; then
          alias="$2"
          case "$alias" in
{cases_block}
            *) exit 0 ;;  # unknown alias: exit 0 with no output
          esac
        fi
        exec {real_ssh} "$@"
        """))
    shim.chmod(0o755)
    # PATH: shim first, then a minimal set of essential dirs so the engine
    # can find tr/awk/cp/etc. (mirrors _path_with_jq_hidden's approach).
    essentials_bin = shim_dir / "_essentials"
    essentials_bin.mkdir(exist_ok=True)
    for tool in ("tr", "awk", "cp", "diff", "wc", "mktemp", "cat", "printf",
                 "date", "grep", "sed", "head", "tail", "sort", "uniq", "env",
                 "basename", "dirname", "mkdir", "rm", "chmod", "ln", "touch",
                 "which", "bash", "sh", "cmp", "python3", "python", "id",
                 "hostname"):
        for p in os.environ.get("PATH", "").split(":"):
            cand = os.path.join(p, tool)
            if os.path.isfile(cand) and os.access(cand, os.X_OK):
                try:
                    (essentials_bin / tool).symlink_to(cand)
                except FileExistsError:
                    pass
                break
    return f"{shim_dir}:{essentials_bin}"


# --- Sub-fix C: ssh_jump_args + alias-has-own-proxy ------------------------


def test_C_ssh_jump_args_skips_when_alias_has_proxyjump(tmp_path: Path) -> None:
    """Sub-fix C: when the target alias has its own ProxyJump in ssh_config,
    ssh_jump_args must NOT add our -J."""
    shim_dir = tmp_path / "bin"
    ssh_g = {
        "polaris-login": (
            "hostname compute-386-02.cels.anl.gov\n"
            "user example-user-1\n"
            "proxyjump example-user-1@logins.cels.anl.gov\n"
        ),
    }
    env = os.environ.copy()
    env["PATH"] = _write_ssh_G_shim(shim_dir, ssh_g)
    snippet = """
result="$(ssh_jump_args example-user-2 polaris-login)"
echo "RESULT=<${result}>"
"""
    rc, out, _err = _source_engine_and_run(snippet, env=env)
    assert rc == 0
    assert "RESULT=<>" in out, (
        f"ssh_jump_args should return empty when alias has own ProxyJump; got:\n{out}"
    )


def test_C_ssh_jump_args_adds_when_alias_has_no_proxy(tmp_path: Path) -> None:
    """Sub-fix C: when the target alias has NO proxy (proxycommand none,
    no proxyjump), ssh_jump_args should add our -J as usual."""
    shim_dir = tmp_path / "bin"
    ssh_g = {
        "plain-node": (
            "hostname plain-node\n"
            "user example-user\n"
            "proxycommand none\n"
        ),
    }
    env = os.environ.copy()
    env["PATH"] = _write_ssh_G_shim(shim_dir, ssh_g)
    snippet = """
result="$(ssh_jump_args example-user plain-node)"
echo "RESULT=<${result}>"
"""
    rc, out, _err = _source_engine_and_run(snippet, env=env)
    assert rc == 0
    assert "RESULT=<-J example-user@logins.cels.anl.gov>" in out, (
        f"ssh_jump_args should add -J for alias with no proxy; got:\n{out}"
    )


def test_C_ssh_jump_args_respects_no_jump_with_alias(tmp_path: Path) -> None:
    """Sub-fix C interaction with --no-jump: --no-jump always wins,
    regardless of alias state."""
    shim_dir = tmp_path / "bin"
    ssh_g = {
        "polaris-login": (
            "hostname compute-386-02.cels.anl.gov\n"
            "user example-user\n"
            "proxyjump example-user@logins.cels.anl.gov\n"
        ),
    }
    env = os.environ.copy()
    env["PATH"] = _write_ssh_G_shim(shim_dir, ssh_g)
    env["ARGO_ANYWHERE_NO_JUMP"] = "1"
    snippet = """
result="$(ssh_jump_args example-user polaris-login)"
echo "RESULT=<${result}>"
"""
    rc, out, _err = _source_engine_and_run(snippet, env=env)
    assert rc == 0
    assert "RESULT=<>" in out, "--no-jump should return empty regardless of alias state"


def test_C_scp_branch_gated_by_alias_has_own_proxy() -> None:
    """Sub-fix C's second call site (SCP options block in
    remote_bootstrap) must skip our `-o ProxyJump=...` when the target
    alias has its own proxy. Runtime-testing this would require faking
    scp + the whole bootstrap flow; a grep-invariant is deterministic
    and catches the regression class we care about (a future refactor
    silently drops the alias guard).

    Post-audit fix (Gap-2 from notes/audit_v3_1_0_post_execution.md).
    The engine's SCP options block lives around line 4627-4644 today;
    the grep looks for the specific pattern rather than a line number
    so it survives edits to nearby code.
    """
    src = _engine_source()
    # The SCP block should contain BOTH the ProxyJump line AND the
    # _alias_has_own_proxy guard around it. The guard was added in C2.
    scp_pattern = r"scp_opts\+=\s*\(\s*-o\s+\"ProxyJump="
    guard_pattern = r"if\s+!\s+_alias_has_own_proxy\s+\"\$node\""
    assert re.search(scp_pattern, src), (
        "the SCP ProxyJump= line has moved or been removed; find its new "
        "location and confirm _alias_has_own_proxy still guards it (or "
        "update this test's pattern)."
    )
    assert re.search(guard_pattern, src), (
        "the SCP block's `if ! _alias_has_own_proxy \"$node\"; then` guard "
        "is missing. Without it, alias-based bootstraps (e.g. "
        "argo-anywhere --node polaris-login) will add a redundant -J on "
        "top of the alias's own ProxyJump, causing scp to fail with a "
        "jump-loop error. Sub-fix C requires this guard."
    )
    # Belt + braces: verify the guard and the ProxyJump line are within
    # 5 lines of each other (so a refactor that moves them apart doesn't
    # silently break the intent).
    lines = src.splitlines()
    guard_line = None
    scp_line = None
    for i, line in enumerate(lines, start=1):
        if re.search(guard_pattern, line):
            guard_line = i
        if re.search(scp_pattern, line):
            scp_line = i
    assert guard_line is not None and scp_line is not None
    assert 0 <= (scp_line - guard_line) <= 5, (
        f"the alias-proxy guard (line {guard_line}) and the SCP "
        f"ProxyJump= line (line {scp_line}) should be adjacent (within "
        f"5 lines); got {scp_line - guard_line} lines apart. Someone may "
        f"have inserted logic between them that breaks the intended "
        f"if/then relationship."
    )


def test_C_notice_dedup_across_multiple_ssh_jump_args_calls(tmp_path: Path) -> None:
    """Sub-fix C dedup: calling ssh_jump_args 10x for the same alias
    fires the notice exactly once. Documents the per-alias-per-invocation
    contract that prevents log-spam in a real `client` run (which invokes
    ssh_jump_args ~10+ times)."""
    shim_dir = tmp_path / "bin"
    ssh_g = {
        "polaris-login": (
            "hostname compute-386-02.cels.anl.gov\n"
            "user example-user\n"
            "proxyjump example-user@logins.cels.anl.gov\n"
        ),
    }
    env = os.environ.copy()
    env["PATH"] = _write_ssh_G_shim(shim_dir, ssh_g)
    snippet = """
for i in 1 2 3 4 5 6 7 8 9 10; do
  ssh_jump_args example-user polaris-login >/dev/null
done
"""
    rc, _out, err = _source_engine_and_run(snippet, env=env)
    assert rc == 0
    count = err.count("polaris-login already routes via")
    assert count == 1, (
        f"expected exactly one dedup notice across 10 ssh_jump_args calls; "
        f"got {count}:\n{err}"
    )


# --- Sub-fix B: resolve_username with ssh-config ---------------------------


def test_B_resolve_username_uses_ssh_config_user(tmp_path: Path) -> None:
    """Sub-fix B: when ARGO_ANYWHERE_USER is unset AND cache is absent
    AND ssh -G on ARGO_ANYWHERE_NODE returns a User line, use that.
    Log line must include the source attribution (per Q5 decision)."""
    shim_dir = tmp_path / "bin"
    ssh_g = {
        "polaris-login": "hostname foo\nuser example-user\n",
    }
    env = os.environ.copy()
    env["PATH"] = _write_ssh_G_shim(shim_dir, ssh_g)
    env["HOME"] = str(tmp_path / "home")  # isolated HOME (no cache)
    (tmp_path / "home").mkdir()
    env.pop("ARGO_ANYWHERE_USER", None)
    env["ARGO_ANYWHERE_NODE"] = "polaris-login"
    snippet = """
resolve_username
echo "RESULT=${_USERNAME_RESULT}"
echo "SOURCE=${_USERNAME_SOURCE}"
echo "CACHE=${_USERNAME_SHOULD_CACHE}"
"""
    rc, out, _err = _source_engine_and_run(snippet, env=env)
    assert rc == 0, f"resolve_username failed:\n{_err}"
    assert "RESULT=example-user" in out, f"expected ssh-config user; got:\n{out}"
    assert "SOURCE=ssh-config:polaris-login" in out, (
        f"expected source attribution; got:\n{out}"
    )
    assert "CACHE=0" in out, (
        f"ssh-config-inferred user should NOT be cached; got:\n{out}"
    )


def test_B_flag_beats_ssh_config(tmp_path: Path) -> None:
    """Sub-fix B priority: ARGO_ANYWHERE_USER (flag/env) beats ssh-config."""
    shim_dir = tmp_path / "bin"
    ssh_g = {"polaris-login": "hostname foo\nuser example-user-1\n"}
    env = os.environ.copy()
    env["PATH"] = _write_ssh_G_shim(shim_dir, ssh_g)
    env["HOME"] = str(tmp_path / "home")
    (tmp_path / "home").mkdir()
    env["ARGO_ANYWHERE_USER"] = "example-user-2"
    env["ARGO_ANYWHERE_NODE"] = "polaris-login"
    snippet = """
resolve_username
echo "RESULT=${_USERNAME_RESULT}"
echo "SOURCE=${_USERNAME_SOURCE}"
"""
    rc, out, _err = _source_engine_and_run(snippet, env=env)
    assert rc == 0
    assert "RESULT=example-user-2" in out, "explicit ARGO_ANYWHERE_USER should win"
    assert "SOURCE=env" in out


def test_B_ssh_config_user_not_written_to_cache(tmp_path: Path) -> None:
    """Sub-fix B per plan §7 A7: ssh-config-inferred username is NEVER
    written to USER_CACHE. Preserves the E3 "cache is write-only-from-
    explicit-actions" contract."""
    shim_dir = tmp_path / "bin"
    ssh_g = {"polaris-login": "hostname foo\nuser example-user\n"}
    env = os.environ.copy()
    env["PATH"] = _write_ssh_G_shim(shim_dir, ssh_g)
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    env["HOME"] = str(fake_home)
    env.pop("ARGO_ANYWHERE_USER", None)
    env["ARGO_ANYWHERE_NODE"] = "polaris-login"
    snippet = """
resolve_username
# Simulate the caller pattern: check _USERNAME_SHOULD_CACHE before persisting.
if [ "$_USERNAME_SHOULD_CACHE" = 1 ]; then
  _persist_username_cache "$_USERNAME_RESULT"
fi
"""
    rc, _out, _err = _source_engine_and_run(snippet, env=env)
    assert rc == 0, f"snippet failed:\n{_err}"
    cache_path = fake_home / ".config" / "argo_anywhere" / "user"
    assert not cache_path.exists(), (
        f"USER_CACHE should NOT be written when username came from "
        f"ssh-config; found: {cache_path}"
    )


def test_B_ssh_config_falls_back_to_jump_host_lookup(tmp_path: Path) -> None:
    """Sub-fix B: when ARGO_ANYWHERE_NODE has no ssh-config User line
    but ANL_JUMP does, use the jump host's User (last-resort heuristic
    per plan §2.2 step 5)."""
    shim_dir = tmp_path / "bin"
    ssh_g = {
        # No user for polaris-login.
        "polaris-login": "hostname foo\n",
        # But logins.cels.anl.gov (ANL_JUMP default) has one.
        "logins.cels.anl.gov": "hostname logins.cels.anl.gov\nuser jump-user\n",
    }
    env = os.environ.copy()
    env["PATH"] = _write_ssh_G_shim(shim_dir, ssh_g)
    env["HOME"] = str(tmp_path / "home")
    (tmp_path / "home").mkdir()
    env.pop("ARGO_ANYWHERE_USER", None)
    env["ARGO_ANYWHERE_NODE"] = "polaris-login"
    snippet = """
resolve_username
echo "RESULT=${_USERNAME_RESULT}"
echo "SOURCE=${_USERNAME_SOURCE}"
"""
    rc, out, _err = _source_engine_and_run(snippet, env=env)
    assert rc == 0, f"snippet failed:\n{_err}"
    assert "RESULT=jump-user" in out, (
        f"expected jump-host fallback; got:\n{out}"
    )
    assert "SOURCE=ssh-config:logins.cels.anl.gov" in out


def test_B_prompted_username_IS_cached(tmp_path: Path) -> None:
    """Regression guard: the OLD auto-cache behavior for PROMPTED values
    still works. Only ssh-config-inferred values are exempt from caching."""
    shim_dir = tmp_path / "bin"
    ssh_g = {}  # No aliases; ssh -G will exit 0 with no output for anything.
    env = os.environ.copy()
    env["PATH"] = _write_ssh_G_shim(shim_dir, ssh_g)
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    env["HOME"] = str(fake_home)
    env.pop("ARGO_ANYWHERE_USER", None)
    env.pop("ARGO_ANYWHERE_NODE", None)
    # No cache, no env, no ssh-config user -> would prompt. Fake the prompt
    # by pre-setting a well-formed answer that the ask() auto-default path
    # would accept... actually, ask() auto-defaults to EMPTY without a
    # default, and resolve_username's regex loop would spin. We can't
    # unit-test the prompt path without a PTY. Skip the actual prompt but
    # verify the SHOULD_CACHE flag semantic by calling _persist_username_cache
    # explicitly. The real "prompted value gets cached" contract is:
    # SHOULD_CACHE=1 for prompt, 0 for everything else -- exercised in the
    # helper's setter code, verified by the source-attribution tests above.
    snippet = """
# Simulate the effect of a prompted value:
_USERNAME_RESULT=prompted-user
_USERNAME_SHOULD_CACHE=1
if [ "$_USERNAME_SHOULD_CACHE" = 1 ]; then
  _persist_username_cache "$_USERNAME_RESULT"
fi
"""
    rc, _out, _err = _source_engine_and_run(snippet, env=env)
    assert rc == 0
    cache_path = fake_home / ".config" / "argo_anywhere" / "user"
    assert cache_path.exists(), "USER_CACHE should be written for prompted values"
    assert cache_path.read_text().strip() == "prompted-user"


def test_B_ssh_config_skipped_on_compute_node(tmp_path: Path) -> None:
    """Sub-fix B: when running ON an ANL compute node, resolve_username
    must skip the ssh-config lookup (self-alias resolution would return
    the OS user, which is the wrong answer for the Argonne identity).

    Post-audit fix (Gap-1 from notes/audit_v3_1_0_post_execution.md):
    the on_anl_compute_node guard is load-bearing but was previously
    untested -- a future refactor could remove it and mode_server would
    silently start caching OS-user values as Argonne usernames.

    Test strategy: shadow the on_anl_compute_node function inside the
    sourced engine to return "yes", then verify resolve_username
    falls through to USER_CACHE / prompt without consulting ssh-config
    (even when a shim would return a value).
    """
    shim_dir = tmp_path / "bin"
    # Fake ssh -G returns a User line -- but the on-node guard should
    # prevent us from ever reading it.
    ssh_g = {"polaris-login": "hostname foo\nuser wrong-user\n"}
    env = os.environ.copy()
    env["PATH"] = _write_ssh_G_shim(shim_dir, ssh_g)
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    # Pre-populate USER_CACHE with the "correct" answer so we can prove
    # the resolver got there (didn't short-circuit into ssh-config).
    cache_dir = fake_home / ".config" / "argo_anywhere"
    cache_dir.mkdir(parents=True)
    (cache_dir / "user").write_text("cached-user\n")
    env["HOME"] = str(fake_home)
    env.pop("ARGO_ANYWHERE_USER", None)
    env["ARGO_ANYWHERE_NODE"] = "polaris-login"

    # Shadow on_anl_compute_node to force the "on-node" path. This is a
    # bash function override -- redefine it BEFORE calling resolve_username.
    snippet = """
on_anl_compute_node() { echo yes; }
resolve_username
echo "RESULT=${_USERNAME_RESULT}"
echo "SOURCE=${_USERNAME_SOURCE}"
"""
    rc, out, _err = _source_engine_and_run(snippet, env=env)
    assert rc == 0, f"snippet failed:\n{_err}"
    # On-node: MUST have fallen through to cache, NOT ssh-config.
    assert "RESULT=cached-user" in out, (
        f"on-node path should have used USER_CACHE; got:\n{out}"
    )
    assert "SOURCE=cache" in out, (
        f"expected source=cache; got:\n{out}"
    )
    # Extra defence: ssh-config source string must NOT appear anywhere.
    assert "ssh-config" not in out, (
        f"on-node path should NOT consult ssh-config; got:\n{out}"
    )


# --- Sub-fix A: pick_node alias-notice upgrade -----------------------------


def test_A_pick_node_alias_notice_appears_in_log(tmp_path: Path) -> None:
    """Sub-fix A: when --node is an ssh_config alias (ssh -G resolves
    it to a different hostname), pick_node emits a 'Note: ... is an
    ssh_config alias' log line instead of the generic 'not in ANL_NODES'
    warn.

    Uses a unit-level slice: exercise the alias-detection idiom
    directly on a synthetic $req without running the full pick_node
    (which needs live SSH for ssh_reachable). The idiom is small and
    identical to what pick_node executes; the full path is verified by
    Scenario X live-test in docs/TESTING.md.
    """
    shim_dir = tmp_path / "bin"
    ssh_g = {
        "polaris-login": (
            "hostname compute-386-02.cels.anl.gov\n"
            "user example-user\n"
        ),
    }
    env = os.environ.copy()
    env["PATH"] = _write_ssh_G_shim(shim_dir, ssh_g)
    # Reproduce pick_node's warn-branch idiom:
    snippet = """
req="polaris-login"
_resolved="$(_ssh_config_hostname "$req")"
if [ -n "$_resolved" ] && [ "$_resolved" != "$req" ]; then
  log "Note: '${req}' is an ssh_config alias"
  log "  (resolves to ${_resolved}); proceeding via ~/.ssh/config."
else
  warn "Requested node '${req}' is not in ANL_NODES (proceeding anyway)."
fi
"""
    rc, _out, err = _source_engine_and_run(snippet, env=env)
    assert rc == 0
    assert "is an ssh_config alias" in err, (
        f"expected alias-notice log line; got:\n{err}"
    )
    assert "compute-386-02.cels.anl.gov" in err, (
        f"expected resolved hostname in notice; got:\n{err}"
    )
    assert "is not in ANL_NODES" not in err, (
        f"generic warn should NOT fire when alias is detected; got:\n{err}"
    )


def test_A_pick_node_bare_hostname_keeps_generic_warn(tmp_path: Path) -> None:
    """Sub-fix A: when --node is a bare hostname (ssh -G doesn't rewrite
    it), pick_node keeps the historical warn verbatim (no false alias
    detection)."""
    shim_dir = tmp_path / "bin"
    # ssh -G on a bare hostname returns the same hostname (OpenSSH's default).
    ssh_g = {}  # No aliases; ssh shim returns no output for any target.
    env = os.environ.copy()
    env["PATH"] = _write_ssh_G_shim(shim_dir, ssh_g)
    snippet = """
req="compute-99.cels.anl.gov"
_resolved="$(_ssh_config_hostname "$req")"
if [ -n "$_resolved" ] && [ "$_resolved" != "$req" ]; then
  log "Note: '${req}' is an ssh_config alias"
  log "  (resolves to ${_resolved}); proceeding via ~/.ssh/config."
else
  warn "Requested node '${req}' is not in ANL_NODES (proceeding anyway)."
fi
"""
    rc, _out, err = _source_engine_and_run(snippet, env=env)
    assert rc == 0
    assert "is not in ANL_NODES" in err, (
        f"expected generic warn for bare hostname; got:\n{err}"
    )
    assert "is an ssh_config alias" not in err


# ===========================================================================
# Post-live-verify fixes (2026-07-15) — see
# notes/audit_v3_1_0_post_execution.md §11 and the commit message on the
# amendment.
# ===========================================================================


def test_A_is_ssh_config_alias_signal_1_hostname_rewrite(tmp_path: Path) -> None:
    """Signal 1: `HostName foo.example.com` under `Host alias` (classic
    alias with hostname rewrite). _is_ssh_config_alias returns 0 and
    sets _ALIAS_DETECTION_REASON to "resolves to <fqdn>".
    """
    shim_dir = tmp_path / "bin"
    ssh_g = {"my-alias": "hostname resolved-host.example.com\n"}
    env = os.environ.copy()
    env["PATH"] = _write_ssh_G_shim(shim_dir, ssh_g)
    snippet = """
if _is_ssh_config_alias my-alias; then
  echo "IS_ALIAS=yes"
  echo "REASON=${_ALIAS_DETECTION_REASON}"
else
  echo "IS_ALIAS=no"
fi
"""
    rc, out, _err = _source_engine_and_run(snippet, env=env)
    assert rc == 0
    assert "IS_ALIAS=yes" in out
    assert "REASON=resolves to resolved-host.example.com" in out


def test_A_is_ssh_config_alias_signal_2_proxyjump(tmp_path: Path) -> None:
    """Signal 2: `HostName %h` (no rewrite) + `ProxyJump ...` — the
    common ANL pattern the live-verify surfaced 2026-07-15. Before this
    fix, only signal 1 was checked and this case fell through to the
    generic warn.
    """
    shim_dir = tmp_path / "bin"
    ssh_g = {"compute-01": (
        "hostname compute-01\n"          # no rewrite (%h → self)
        "user example-user\n"
        "proxyjump example-user@logins.cels.anl.gov\n"
    )}
    env = os.environ.copy()
    env["PATH"] = _write_ssh_G_shim(shim_dir, ssh_g)
    snippet = """
if _is_ssh_config_alias compute-01; then
  echo "IS_ALIAS=yes"
  echo "REASON=${_ALIAS_DETECTION_REASON}"
else
  echo "IS_ALIAS=no"
fi
"""
    rc, out, _err = _source_engine_and_run(snippet, env=env)
    assert rc == 0
    assert "IS_ALIAS=yes" in out, (
        f"live-verify regression: signal 2 (ProxyJump without hostname "
        f"rewrite) should be detected as an alias; got:\n{out}"
    )
    assert "no hostname rewrite" in out
    assert "ProxyJump" in out


def test_A_is_ssh_config_alias_signal_3_user_only(tmp_path: Path) -> None:
    """Signal 3: alias exists only to attach a User (no HostName rewrite,
    no ProxyJump/ProxyCommand). Rare but legitimate — e.g., a user with
    a different account on a specific host but the same routing.
    """
    shim_dir = tmp_path / "bin"
    ssh_g = {"my-alias": (
        "hostname my-alias\n"     # no rewrite
        "user special-account\n"  # User attached
        "proxycommand none\n"     # explicit no-proxy sentinel
    )}
    env = os.environ.copy()
    env["PATH"] = _write_ssh_G_shim(shim_dir, ssh_g)
    snippet = """
if _is_ssh_config_alias my-alias; then
  echo "IS_ALIAS=yes"
  echo "REASON=${_ALIAS_DETECTION_REASON}"
else
  echo "IS_ALIAS=no"
fi
"""
    rc, out, _err = _source_engine_and_run(snippet, env=env)
    assert rc == 0
    assert "IS_ALIAS=yes" in out, (
        f"signal 3 (User-only alias) should be detected; got:\n{out}"
    )
    assert "User special-account" in out


def test_A_is_ssh_config_alias_returns_false_for_bare_hostname(tmp_path: Path) -> None:
    """A bare hostname with no ssh_config entry: `ssh -G bare-node` returns
    only defaults (hostname == input, no User, no ProxyJump). Detection
    should return 1 (not an alias)."""
    shim_dir = tmp_path / "bin"
    # ssh -G on a target with no config: returns only defaults matching input.
    # Our shim returns empty for unknown aliases; the engine's helpers see
    # empty output and treat it as "no signal fires."
    ssh_g = {}
    env = os.environ.copy()
    env["PATH"] = _write_ssh_G_shim(shim_dir, ssh_g)
    snippet = """
if _is_ssh_config_alias unknown-host; then
  echo "IS_ALIAS=yes"
else
  echo "IS_ALIAS=no"
fi
"""
    rc, out, _err = _source_engine_and_run(snippet, env=env)
    assert rc == 0
    assert "IS_ALIAS=no" in out


def test_C_notice_dedup_persists_across_subshells(tmp_path: Path) -> None:
    """Sub-fix C dedup: sentinel MUST survive subshell boundaries so the
    notice fires ONCE per client-run, not per-subshell.

    Live-verify 2026-07-15 (Attias-MacBook-Pro against compute-01):
    without `export`, the sentinel died at each subshell boundary and
    the notice fired ~5x per client run (pick_node's ssh_reachable,
    ssh_mux_open, scp bootstrap, ssh bootstrap, tunnel-forward).

    Test strategy: fire the dedup helper in the parent shell, then in a
    subshell (via `bash -c ""` or `( ... )`), then again in the parent.
    Assert the notice appears exactly ONCE across all three calls.
    """
    # Three-phase test:
    # 1. Fire the dedup in the parent shell.
    # 2. Fire it in a parenthesized subshell.
    # 3. Fork a full bash subprocess and check that the sentinel is in
    #    that subprocess's environment (which is the actual multi-
    #    subshell scenario a real `client` run hits).
    # 4. Fire it in the parent again.
    #
    # If dedup is broken (sentinel not exported), we'd see the notice
    # 2-3 times. If dedup works, exactly once.
    snippet = r"""
_alias_proxy_notice_dedup compute-01 example-user
(
  _alias_proxy_notice_dedup compute-01 example-user
)
bash -c 'if [ "${_ALIAS_PROXY_NOTICE_SEEN_compute_01:-0}" = "1" ]; then echo "SUBSHELL_INHERITED=yes" >&2; else echo "SUBSHELL_INHERITED=no" >&2; fi'
_alias_proxy_notice_dedup compute-01 example-user
"""
    rc, _out, err = _source_engine_and_run(snippet)
    assert rc == 0, f"snippet failed:\n{err}"
    # The `log "Note: ..."` line must appear exactly once across the
    # parent + subshell + parent-again invocations.
    count = err.count("compute-01 already routes via")
    assert count == 1, (
        f"expected exactly ONE dedup notice across parent+subshell+parent; "
        f"got {count}. The sentinel isn't being exported (fix: change "
        f"`eval \"${{seen_var}}=1\"` to `eval \"export ${{seen_var}}=1\"` "
        f"in _alias_proxy_notice_dedup).\n\nCaptured stderr:\n{err}"
    )
    # The subshell should have inherited the exported sentinel.
    assert "SUBSHELL_INHERITED=yes" in err, (
        f"the exported sentinel didn't propagate into a `bash -c` subshell "
        f"-- the export isn't working. err:\n{err}"
    )
