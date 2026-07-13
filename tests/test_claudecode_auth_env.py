"""Tests for the claudecode config writer's canonical-env-var adoption
+ the cross-tool env-shadow detector (2026-07-13).

Background (documented in docs/LIMITATIONS.md "Claude Code TUI is
misleading"):

* Pre-2026-07-13 the engine wrote ``env.ANTHROPIC_AUTH_TOKEN = <ANL_USER>``
  into Claude Code's settings.json. Both ``ANTHROPIC_AUTH_TOKEN`` and
  ``ANTHROPIC_API_KEY`` are honored by Claude Code and both route
  requests correctly (verified 2026-07-13 by pointing the base URL at a
  dead port -- Claude Code hung waiting on that port under either env
  var). ``ANTHROPIC_API_KEY`` is Anthropic's canonical name in their
  public docs, so we adopted it as future-proofing.

* The same investigation surfaced a real UX issue: Claude Code's TUI
  renders its welcome banner + "Select model" picker from
  ``~/.claude.json`` OAuth account state regardless of the actual
  routing. Users see "Opus 4.8 · API Usage Billing" and reasonably
  conclude they're on their personal subscription even when requests
  are correctly reaching argo. The post-configure output block +
  documentation now name that gotcha explicitly.

Tests:

* Writer output shape (new key present; old key stripped when it was ours).
* Migration preserves user-owned ``ANTHROPIC_AUTH_TOKEN`` (different value).
* Env-shadow detector fires on set + suppresses when unset (universal
  cross-tool contract).
* Every registered CLI tool declares its shadowing vars.
* In-place migrator upgrades pre-2026-07-13 configs silently (fixes the
  non-TTY-caller silent-skip bug where handle_config_file's k/b/d/m/a
  prompt would auto-answer keep-existing).
"""

from __future__ import annotations

import json
import os
import subprocess
import textwrap
from pathlib import Path


from argo_anywhere._engine import engine_path


# --- writer output (via extracted Python heredoc) --------------------------

# The bash writer wraps a python3 heredoc. We test the heredoc directly with
# the same 4 positional args the bash side passes it -- keeps the test fast
# and self-contained.
_WRITER_PY = textwrap.dedent("""
    import json, os, sys
    orig_path, dest_path, user, port = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
    data = {}
    if os.path.isfile(orig_path):
        try:
            with open(orig_path) as f:
                data = json.load(f) or {}
        except Exception:
            sys.exit(2)
        if not isinstance(data, dict):
            sys.exit(2)
    env = data.get("env") or {}
    if not isinstance(env, dict):
        env = {}
    env["ANTHROPIC_BASE_URL"] = f"http://localhost:{port}"
    env["ANTHROPIC_API_KEY"]  = user
    if env.get("ANTHROPIC_AUTH_TOKEN") == user:
        del env["ANTHROPIC_AUTH_TOKEN"]
    data["env"] = env
    with open(dest_path, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\\n")
""")


def _run_writer(orig: Path, dest: Path, user: str = "testuser", port: str = "64742") -> None:
    subprocess.run(
        ["python3", "-c", _WRITER_PY, str(orig), str(dest), user, port],
        check=True, capture_output=True, text=True,
    )


def test_writer_emits_api_key_not_auth_token(tmp_path: Path) -> None:
    """Root fix: fresh writes use ANTHROPIC_API_KEY -- the var that
    Claude Code actually honors when a personal OAuth session exists."""
    orig = tmp_path / "settings.json"
    dest = tmp_path / "out.json"
    _run_writer(orig, dest)
    out = json.loads(dest.read_text())
    env = out["env"]
    assert env["ANTHROPIC_API_KEY"] == "testuser"
    assert env["ANTHROPIC_BASE_URL"] == "http://localhost:64742"
    # AUTH_TOKEN must NOT be written on a fresh file.
    assert "ANTHROPIC_AUTH_TOKEN" not in env


def test_writer_strips_our_old_auth_token_on_migration(tmp_path: Path) -> None:
    """Pre-2026-07-13 configs have ``ANTHROPIC_AUTH_TOKEN = <user>``.
    The migration strips it when the value matches the current user
    (i.e. it's ours), leaving ANTHROPIC_API_KEY as the sole auth var."""
    orig = tmp_path / "settings.json"
    dest = tmp_path / "out.json"
    orig.write_text(json.dumps({
        "model": "sonnet",  # user-owned; must be preserved
        "env": {
            "ANTHROPIC_BASE_URL": "http://localhost:64742",
            "ANTHROPIC_AUTH_TOKEN": "testuser",
            "SOME_OTHER_ENV": "keep-me",
        },
    }))
    _run_writer(orig, dest)
    out = json.loads(dest.read_text())
    assert out["model"] == "sonnet"                 # top-level user keys preserved
    assert out["env"]["SOME_OTHER_ENV"] == "keep-me"  # unknown env keys preserved
    assert "ANTHROPIC_AUTH_TOKEN" not in out["env"] # our old one stripped
    assert out["env"]["ANTHROPIC_API_KEY"] == "testuser"
    assert out["env"]["ANTHROPIC_BASE_URL"] == "http://localhost:64742"


def test_writer_preserves_user_owned_auth_token(tmp_path: Path) -> None:
    """A user who has legitimately set ``ANTHROPIC_AUTH_TOKEN`` to a value
    that isn't their ANL username (e.g. a personal OAuth token) keeps
    that value across our rewrites. We only strip when the value matches
    OUR username -- that's the fingerprint that it came from us."""
    orig = tmp_path / "settings.json"
    dest = tmp_path / "out.json"
    orig.write_text(json.dumps({
        "env": {
            "ANTHROPIC_AUTH_TOKEN": "my-personal-oauth-token-not-ours",
        },
    }))
    _run_writer(orig, dest)
    out = json.loads(dest.read_text())
    # User's own token survives.
    assert out["env"]["ANTHROPIC_AUTH_TOKEN"] == "my-personal-oauth-token-not-ours"
    # Ours is written too (Claude Code precedence between AUTH_TOKEN and
    # API_KEY isn't documented reliably; the safe move is to write both
    # when the user has their own AUTH_TOKEN, so API_KEY still routes us).
    assert out["env"]["ANTHROPIC_API_KEY"] == "testuser"


def test_writer_refuses_to_overwrite_malformed_json(tmp_path: Path) -> None:
    """M8 invariant: malformed target file -> exit code 2, no overwrite."""
    orig = tmp_path / "settings.json"
    dest = tmp_path / "out.json"
    orig.write_text("{not-json")
    r = subprocess.run(
        ["python3", "-c", _WRITER_PY, str(orig), str(dest), "testuser", "64742"],
        capture_output=True, text=True,
    )
    assert r.returncode == 2
    # dest must not have been written.
    assert not dest.exists()


# --- per-tool shadowing_env_vars declarations ------------------------------

def _source_engine_and_run(bash_snippet: str, env: dict[str, str] | None = None,
                           timeout: float = 15.0) -> tuple[int, str, str]:
    """Source the engine without running ``main()``, then execute
    ``bash_snippet`` against the loaded function definitions.

    ``main "$@"`` is the last line of the engine; we strip it before
    sourcing so the function definitions load without side effects.
    Returns ``(returncode, stdout, stderr)`` of the executed snippet."""
    with engine_path() as script:
        body = script.read_text()
        # Drop the final ``main "$@"`` invocation.
        assert body.rstrip().endswith('main "$@"'), (
            "engine's last statement changed; update the test's stripping "
            "logic to match"
        )
        body_no_main = body.rstrip()[: -len('main "$@"')]
        wrapper = body_no_main + "\n" + bash_snippet + "\n"
        r = subprocess.run(
            ["bash", "-c", wrapper],
            capture_output=True, text=True, timeout=timeout,
            env=env if env is not None else os.environ.copy(),
        )
    return r.returncode, r.stdout, r.stderr


def _extract_shadowing_vars_for(tool: str) -> list[str]:
    """Extract the value returned by ``<tool>_shadowing_env_vars``."""
    rc, out, err = _source_engine_and_run(f"{tool}_shadowing_env_vars")
    assert rc == 0, f"{tool}_shadowing_env_vars failed: {err}"
    return out.strip().split()


def test_all_registered_tools_declare_shadowing_env_vars() -> None:
    """Every tool the launcher lets the user run against argo declares
    its shadowing env vars. If a tool grows an env-override at upstream,
    add its var here + reviewer catches the omission."""
    for tool in ("opencode", "claudecode", "aider"):
        vars_ = _extract_shadowing_vars_for(tool)
        assert vars_, f"{tool}_shadowing_env_vars returned empty"
        # Sanity: only uppercase-with-underscores env-var names.
        for v in vars_:
            assert v.replace("_", "").isalnum() and v.isupper(), f"{tool}: bad var name {v!r}"


def test_claudecode_shadowing_vars_include_the_ones_that_bit_us() -> None:
    """The regression that motivated this fix: ANTHROPIC_AUTH_TOKEN /
    ANTHROPIC_API_KEY / ANTHROPIC_BASE_URL in the shell env silently
    override our written config. All three MUST be in the shadowing
    list so the detector warns the user."""
    vars_ = set(_extract_shadowing_vars_for("claudecode"))
    for required in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN",
                     "ANTHROPIC_BASE_URL"):
        assert required in vars_, f"missing {required} from claudecode shadow list"


def test_aider_and_opencode_include_openai_key() -> None:
    """aider + opencode ride the OpenAI-Chat surface; OPENAI_API_KEY is
    the shell-env footgun for both."""
    for tool in ("opencode", "aider"):
        vars_ = set(_extract_shadowing_vars_for(tool))
        assert "OPENAI_API_KEY" in vars_, f"{tool}: missing OPENAI_API_KEY"


# --- env-shadow detector behavior (invokes the bash function directly) ----

def _run_shadow_check(tool: str, env: dict[str, str]) -> tuple[int, str]:
    """Invoke ``_check_env_shadow_and_warn`` with a specific env; return
    (exit_code, combined_stderr_stdout). Uses a MINIMAL env so tests are
    hermetic (the caller's ANTHROPIC_* / OPENAI_* must NOT leak in)."""
    clean_env = {
        "HOME": os.environ.get("HOME", ""),
        "PATH": os.environ.get("PATH", ""),
        "TERM": "dumb",
        **env,
    }
    rc, out, err = _source_engine_and_run(
        f"_check_env_shadow_and_warn {tool}",
        env=clean_env,
    )
    return rc, err + out


def test_shadow_check_silent_when_no_vars_set() -> None:
    """No shadowing vars set -> no warning output. The detector is a
    warn-only helper; it must NOT spam users with the routine happy
    path."""
    rc, out = _run_shadow_check("claudecode", {})
    assert rc == 0
    # No "Environment-shadowing check" header printed.
    assert "Environment-shadowing check" not in out


def test_shadow_check_warns_when_api_key_set() -> None:
    """The exact bug: ANTHROPIC_API_KEY set in shell -> loud warning
    with unset-instructions."""
    rc, out = _run_shadow_check("claudecode", {"ANTHROPIC_API_KEY": "sk-ant-leaked"})
    assert rc == 0  # warn-only, never fails the run
    assert "Environment-shadowing check (claudecode)" in out
    assert "ANTHROPIC_API_KEY" in out
    # Value must be MASKED (contains _KEY).
    assert "sk-ant-leaked" not in out
    # Unset instructions present.
    assert "unset ANTHROPIC_API_KEY" in out


def test_shadow_check_shows_base_url_value_unmasked() -> None:
    """Non-credential vars (BASE_URL) show their actual value -- helps
    users see if their shell is pointing to the WRONG endpoint (e.g.
    api.anthropic.com when we meant localhost:64742)."""
    rc, out = _run_shadow_check(
        "claudecode", {"ANTHROPIC_BASE_URL": "https://api.anthropic.com"},
    )
    assert rc == 0
    assert "https://api.anthropic.com" in out  # value visible


def test_shadow_check_lists_multiple_vars() -> None:
    """When several shadowing vars are set, ALL are listed + unset lines
    printed for each -- not just the first hit."""
    rc, out = _run_shadow_check("claudecode", {
        "ANTHROPIC_API_KEY": "sk-ant-x",
        "ANTHROPIC_BASE_URL": "https://api.anthropic.com",
    })
    assert rc == 0
    assert "ANTHROPIC_API_KEY" in out
    assert "ANTHROPIC_BASE_URL" in out
    assert out.count("unset ") >= 2


def test_shadow_check_no_op_for_unknown_tool() -> None:
    """A tool with no ``<name>_shadowing_env_vars`` function returns
    cleanly (no error, no warning) -- keeps the helper safe to call
    unconditionally from dispatchers as we add tools."""
    rc, out = _run_shadow_check("bogus-tool-that-does-not-exist", {})
    assert rc == 0
    assert "Environment-shadowing check" not in out


# --- in-place migration (fixes the "TMP3 bug", 2026-07-13) -----------------
# The writer-level migration only fires when handle_config_file actually
# invokes the writer. A pre-fix config on disk goes through cmp -s first,
# which reports "differs" -> prompts [k/b/d/m/a]. Non-TTY callers (the web
# UI's `configure` verb + `run --ensure` + `-y` runs) auto-answer `k` and
# skip the migration silently. The fix: run
# ``_migrate_claudecode_config_in_place`` BEFORE handle_config_file so the
# file already matches the proposed shape and cmp -s returns "up to date".


def _run_migrator(target: Path, user: str = "aattia") -> tuple[int, str, str]:
    """Invoke the migrator against ``target`` with the given ANL user."""
    snippet = (
        f'ARGO_ANYWHERE_USER={user!s} '
        f'ANL_USERNAME={user!s} '
        f'_migrate_claudecode_config_in_place {str(target)!r}'
    )
    return _source_engine_and_run(snippet)


def test_migrator_upgrades_our_pre_fix_auth_token(tmp_path: Path) -> None:
    """The exact TMP3 bug: file has env.ANTHROPIC_AUTH_TOKEN = our user."""
    target = tmp_path / "settings.local.json"
    target.write_text(json.dumps({
        "env": {
            "ANTHROPIC_BASE_URL": "http://localhost:64742",
            "ANTHROPIC_AUTH_TOKEN": "aattia",
        },
    }))
    rc, out, err = _run_migrator(target, user="aattia")
    assert rc == 0
    # Migrator prints a confirmation on stdout so the user sees it.
    assert "migrated" in out
    result = json.loads(target.read_text())
    assert result["env"]["ANTHROPIC_API_KEY"] == "aattia"
    assert "ANTHROPIC_AUTH_TOKEN" not in result["env"]
    assert result["env"]["ANTHROPIC_BASE_URL"] == "http://localhost:64742"


def test_migrator_noop_when_already_migrated(tmp_path: Path) -> None:
    """Idempotent: running against a post-fix config leaves it unchanged
    and prints nothing (no ``[migrated]`` line -- users only see migration
    output when a migration actually happened)."""
    target = tmp_path / "settings.local.json"
    original = {
        "env": {
            "ANTHROPIC_BASE_URL": "http://localhost:64742",
            "ANTHROPIC_API_KEY": "aattia",
        },
    }
    target.write_text(json.dumps(original))
    rc, out, err = _run_migrator(target, user="aattia")
    assert rc == 0
    assert "migrated" not in out
    assert json.loads(target.read_text()) == original


def test_migrator_preserves_user_owned_auth_token(tmp_path: Path) -> None:
    """A user-owned AUTH_TOKEN with a value that ISN'T our ANL username
    is left alone (it's not ours to touch). This mirrors the writer's
    same policy: we only strip when the fingerprint matches."""
    target = tmp_path / "settings.local.json"
    target.write_text(json.dumps({
        "env": {
            "ANTHROPIC_BASE_URL": "http://localhost:64742",
            "ANTHROPIC_AUTH_TOKEN": "my-personal-oauth-token",
        },
    }))
    rc, out, err = _run_migrator(target, user="aattia")
    assert rc == 0
    result = json.loads(target.read_text())
    # User's own token survives untouched.
    assert result["env"]["ANTHROPIC_AUTH_TOKEN"] == "my-personal-oauth-token"
    # And we did NOT insert our API_KEY here either -- that's the writer's
    # job (which runs after the migrator if handle_config_file decides
    # a write is needed). The migrator is scoped to "our old key -> our
    # new key"; anything else is out of scope.
    assert result["env"].get("ANTHROPIC_API_KEY") is None


def test_migrator_preserves_top_level_user_keys(tmp_path: Path) -> None:
    """The user's own top-level settings (model, permissions, hooks, etc.)
    survive the migration -- we only touch env.ANTHROPIC_AUTH_TOKEN /
    env.ANTHROPIC_API_KEY."""
    target = tmp_path / "settings.local.json"
    target.write_text(json.dumps({
        "model": "sonnet",
        "permissions": {"allow": ["Read", "Bash(npm test)"]},
        "hooks": {"PreToolUse": []},
        "env": {
            "ANTHROPIC_AUTH_TOKEN": "aattia",
            "MY_CUSTOM_VAR": "keep-me",
        },
    }))
    rc, out, err = _run_migrator(target, user="aattia")
    assert rc == 0
    result = json.loads(target.read_text())
    assert result["model"] == "sonnet"
    assert result["permissions"] == {"allow": ["Read", "Bash(npm test)"]}
    assert result["hooks"] == {"PreToolUse": []}
    assert result["env"]["MY_CUSTOM_VAR"] == "keep-me"
    # Migration happened.
    assert "ANTHROPIC_AUTH_TOKEN" not in result["env"]
    assert result["env"]["ANTHROPIC_API_KEY"] == "aattia"


def test_migrator_noop_when_target_absent(tmp_path: Path) -> None:
    """No file -> nothing to migrate -> return 0 silently. Callers
    (setup_claudecode_cli_tool) always call this before handle_config_file,
    which is where the "no existing file -> write fresh" branch lives."""
    target = tmp_path / "does-not-exist.json"
    rc, out, err = _run_migrator(target, user="aattia")
    assert rc == 0
    assert not target.exists()


def test_migrator_noop_on_malformed_json(tmp_path: Path) -> None:
    """Broken JSON -> defer to handle_config_file's k/b/d/m/a flow
    (which knows how to prompt the user to fix / backup / overwrite).
    The migrator refusing to touch broken files is important: we
    don't want the migrator to make a bad situation worse by writing
    a fresh config that discards the user's recoverable content."""
    target = tmp_path / "broken.json"
    target.write_text("{not-json{")
    rc, out, err = _run_migrator(target, user="aattia")
    assert rc == 0
    # File contents unchanged.
    assert target.read_text() == "{not-json{"


def test_migrator_atomic_write_leaves_no_tempfile(tmp_path: Path) -> None:
    """The migrator uses tempfile + os.replace so a reader mid-open
    never sees a half-written file. On success only the target exists;
    no sibling tempfile is left behind (a scan for stale
    ``.argo-migrate.*`` files would fire diagnostics elsewhere)."""
    target = tmp_path / "settings.local.json"
    target.write_text(json.dumps({
        "env": {"ANTHROPIC_AUTH_TOKEN": "aattia"},
    }))
    rc, out, err = _run_migrator(target, user="aattia")
    assert rc == 0
    # Only the target exists; no sibling tempfile left behind.
    residue = [p.name for p in tmp_path.iterdir() if p != target]
    assert residue == [], f"stale tempfiles left: {residue}"
