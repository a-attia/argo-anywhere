# v2.2.1 live-test plan (lossless `update` subcommand + self-update + canonical install)

**What's being tested**: the two design decisions landing on `main`
ahead of the v2.2.1 tag, both authored 2026-06-24:

  - **D-022** (`update` subcommand): registry-driven lossless
    in-place upgrade of `argoproxy`, `opencode`, `claudecode`
    (originally 3 components); per-component helper contract;
    auto-`/refresh` after argoproxy upgrade; extracts
    `ensure_argoproxy_installed` from inline `mode_server`.
  - **D-023** (self-update + canonical install): extends the
    registry with `argo-anywhere` as the 4th component (self-update
    of the script itself); introduces `SCRIPT_VERSION` constant;
    introduces canonical install at `~/.argo_anywhere/` with
    sourceable `env` PATH helper; introduces first-run bootstrap
    fired from `mode_client`.

**Audit findings addressed**: UP-02 partially (the script now
exposes a user-facing upgrade path that doesn't require
`--force-reinstall`; the formal soft version floor still needs a
`_version_ge` check added to `ensure_argoproxy_installed`, queued
as a follow-up amendment if surfaced during live test).

**Scope discipline**: every test below verifies either (a) one of
the new affordances (`update`, bootstrap, self-update) works on
its trigger, (b) the existing v2.2.0 paths (`client`, `setup`,
`status`, `stop`, `update-models`, `clean`, `--force-reinstall`)
are unchanged, or (c) per-tool API contract extensions
(`update_<name>_cli_tool`, `ensure_argoproxy_installed` extraction)
are behavior-preserving.

**Lessons applied from prior test plans**:
- Synthetic state-injection must ACTUALLY traverse the asserted code
  path (Phase 2c+3 #1 + Phase 2d #3 + Phase 4 #5 finding); verify
  via WARN/log output or by reading the on-disk artifact directly.
- Pipes can mask exit codes (`| tail` resets `$?`); when an exit
  code matters, capture stderr separately or test in a clean shell.
- Self-update tests are dangerous (the script overwrites itself).
  Always take an external backup of `~/.argo_anywhere/argo_anywhere.sh`
  BEFORE running the self-update test; restore after if anything
  unexpected happens.
- Network-dependent paths (`update argo-anywhere` fetches from
  raw.githubusercontent.com; `update argoproxy --check` hits PyPI)
  may fail in air-gapped environments; flag the test as
  network-required and skip if no upstream connectivity.

---

## Pre-test setup

### Required state on the test laptop

- A working `client` invocation completed at least once (so the
  cached username, node, and port are populated; tunnel is up;
  argo-proxy is running on the chosen compute node).
- The working git checkout at
  `~/AHMED_HOME/Research/Projects/Software/argo-anywhere/` is on a
  branch with the D-022 + D-023 commits landed.
- `~/.argo_anywhere/argo_anywhere.sh` may or may not already exist
  (Test 1 covers both cases by manipulating its presence).

### Required state on the compute node

- `~/argovenv/` exists with argo-proxy installed (any version >=3.0
  is fine; Test 4 will upgrade it).
- `~/.config/argoproxy/config.yaml` exists with the user's
  username + port.

### Safety backups (run BEFORE Tests 1, 5, 8)

```sh
cp ~/.argo_anywhere/argo_anywhere.sh /tmp/argo_anywhere.sh.preupdate_backup
ssh -J <user>@logins.cels.anl.gov <user>@<node> \
  '~/argovenv/bin/argo-proxy --version > /tmp/argoproxy_version_pre_test'
```

Restoration (only if needed):

```sh
cp /tmp/argo_anywhere.sh.preupdate_backup ~/.argo_anywhere/argo_anywhere.sh
chmod 0755 ~/.argo_anywhere/argo_anywhere.sh
```

---

## Test 1: first-run canonical-install bootstrap (D-023)

**What's tested**: `maybe_bootstrap_canonical_install` fires
exactly once on the first `client` / `setup` invocation when
`~/.argo_anywhere/` is absent.

### Setup

```sh
# Move existing canonical install aside (don't delete; we restore it).
mv ~/.argo_anywhere ~/.argo_anywhere.preupdate_backup
ls -la ~/.argo_anywhere 2>&1   # expect: 'No such file or directory'
```

### Action

```sh
# Run a `setup` invocation. The 'setup' subcommand always shows the
# picker, which we'll Ctrl+C out of -- we only want to exercise
# the bootstrap path that fires BEFORE the picker.
bash argo_anywhere.sh setup
# At the CLI-tool picker prompt: hit Ctrl+C.
```

### Expected output

A pre-picker log block (cite output verbatim in the post-test record):

```
[argo_anywhere] First-run setup: installing argo_anywhere.sh into /Users/<you>/.argo_anywhere/...
[ ok ] Installed argo_anywhere.sh v2.2.1[-dev] at /Users/<you>/.argo_anywhere/argo_anywhere.sh
[ ok ]   PATH helper written to /Users/<you>/.argo_anywhere/env

  To make 'argo_anywhere.sh' discoverable as a bare command in new shells,
  add this ONE line to /Users/<you>/.zshrc:

      . "$HOME/.argo_anywhere/env"

  Then either open a new shell, or run:

      . "$HOME/.argo_anywhere/env"

  in this shell to pick up the change immediately.
```

### Verification

```sh
ls -la ~/.argo_anywhere/                    # expect: argo_anywhere.sh + env, both 0755
diff ~/.argo_anywhere/argo_anywhere.sh argo_anywhere.sh   # expect: empty (byte-identical copy)
grep -m1 '^SCRIPT_VERSION=' ~/.argo_anywhere/argo_anywhere.sh   # expect: SCRIPT_VERSION="2.2.1[-dev]"
. ~/.argo_anywhere/env && which argo_anywhere.sh   # expect: /Users/<you>/.argo_anywhere/argo_anywhere.sh
```

### Idempotence

```sh
bash argo_anywhere.sh setup
# Ctrl+C at picker.
# Verify NO bootstrap message printed; the prior install is reused.
```

### Restore

```sh
rm -rf ~/.argo_anywhere
mv ~/.argo_anywhere.preupdate_backup ~/.argo_anywhere
```

### Pass criteria

- Bootstrap fires exactly once when `~/.argo_anywhere/` is absent.
- Bootstrap is a no-op on the second invocation (no log message; no
  file change as confirmed by `stat -f '%Sm'` mtime preservation).
- `~/.argo_anywhere/env` is sourceable + idempotent (re-sourcing
  doesn't duplicate the PATH entry).
- Existing pre-test canonical install is restored cleanly.

---

## Test 2: `update --check` against all 4 components (D-022 + D-023)

**What's tested**: report-only mode reports installed-vs-upstream
without touching anything.

### Action

```sh
bash argo_anywhere.sh update --check --all 2>&1 | tee /tmp/update_check_all.log
```

### Expected output (one block per component)

```
[argo_anywhere] update --check: report-only; no upgrades will be performed.
[argo_anywhere] 
[argo_anywhere] ==> update argo-anywhere
[argo_anywhere] Current script: argo_anywhere.sh v2.2.1[-dev]
[argo_anywhere] Upstream latest tag: v2.2.0 (version: 2.2.0)
[ ok ] argo_anywhere.sh is up-to-date (2.2.1[-dev] >= 2.2.0).
[argo_anywhere] Canonical install at /Users/<you>/.argo_anywhere/argo_anywhere.sh: v<...>
[argo_anywhere] 
[argo_anywhere] ==> update argoproxy
[argo_anywhere] argo-proxy upstream latest (PyPI): <X.Y.Z>
[argo_anywhere] Updating argo-proxy on <node> (user=<you>)...
[remote] argo-proxy installed (venv): <X.Y.Z>
[remote] --check mode: not upgrading.
[argo_anywhere] 
[argo_anywhere] ==> update opencode
[argo_anywhere] OpenCode installed: <path> (version <X.Y.Z>)
[argo_anywhere]   (run 'update opencode' to attempt an in-place upgrade)
[argo_anywhere] 
[argo_anywhere] ==> update claudecode
[argo_anywhere] Claude Code installed: <path> (version <X.Y.Z>)
[argo_anywhere]   (run 'update claudecode' to attempt an in-place upgrade)
[argo_anywhere] 
[argo_anywhere] Update summary:
[ ok ]   OK:      argo-anywhere argoproxy opencode claudecode
```

### Verification

```sh
# Confirm the venv argo-proxy version didn't change.
ssh -J <user>@logins.cels.anl.gov <user>@<node> \
  '~/argovenv/bin/argo-proxy --version' \
  | diff - /tmp/argoproxy_version_pre_test   # expect: empty
# Confirm the canonical install mtime didn't change.
stat -f '%Sm' ~/.argo_anywhere/argo_anywhere.sh   # expect: pre-test mtime
```

### Pass criteria

- All 4 components report installed + upstream versions.
- No file mtime on the laptop or compute node changes.
- Exit code is 0.

---

## Test 3: `update bogus` dies loud (D-016 fail-louder discipline)

### Action + expected

```sh
bash argo_anywhere.sh update bogus 2>&1 | head -2
# Expected: [err ] update: unknown component 'bogus'. Known components: argo-anywhere, argoproxy, opencode, claudecode.
echo $?   # expect: non-zero
```

### Pass criteria

- Error message names all 4 known components.
- Exit code is non-zero (typo did NOT silently succeed).

---

## Test 4: `update argoproxy` end-to-end (D-022)

**What's tested**: lossless in-place argo-proxy upgrade + auto-POST
`/refresh` + new models appear in `/v1/models`.

### Setup

If the compute-node venv is already at the latest version, downgrade
first (otherwise the upgrade has nothing to do):

```sh
ssh -J <user>@logins.cels.anl.gov <user>@<node> \
  '~/argovenv/bin/pip install --force-reinstall argo-proxy==3.0.0'
# Confirm:
ssh -J <user>@logins.cels.anl.gov <user>@<node> \
  '~/argovenv/bin/argo-proxy --version'    # expect: argo-proxy 3.0.0
```

Then capture the BEFORE model list:

```sh
curl -fsS http://localhost:$PORT/v1/models | jq -r '.data[] | .internal_name' \
  | sort -u > /tmp/models_before.txt
wc -l /tmp/models_before.txt
```

### Action

```sh
bash argo_anywhere.sh update argoproxy 2>&1 | tee /tmp/update_argoproxy.log
```

### Expected output (key markers)

- `[argo_anywhere] argo-proxy upstream latest (PyPI): <latest>`
- `[remote] argo-proxy installed (venv): 3.0.0`
- `[remote] Running '/home/<you>/argovenv/bin/pip install --upgrade argo-proxy' (venv-targeted)...`
- `[remote] OK: venv argo-proxy now at <latest>`
- `[argo_anywhere] POST http://localhost:<port>/refresh ...`
- `[ ok ] argo-proxy model registry refreshed.`
- `[ ok ]   OK:      argoproxy`

### Verification

```sh
# Venv was upgraded.
ssh -J <user>@logins.cels.anl.gov <user>@<node> \
  '~/argovenv/bin/argo-proxy --version'    # expect: argo-proxy <latest>
ssh -J <user>@logins.cels.anl.gov <user>@<node> \
  '~/argovenv/bin/pip show argo-proxy | head -2'    # expect: Version: <latest>
# /v1/models now includes any newly-introduced models.
curl -fsS http://localhost:$PORT/v1/models | jq -r '.data[] | .internal_name' \
  | sort -u > /tmp/models_after.txt
diff /tmp/models_before.txt /tmp/models_after.txt   # expect: additions (no deletions)
# Argo-proxy config preserved (lossless).
ssh -J <user>@logins.cels.anl.gov <user>@<node> 'cat ~/.config/argoproxy/config.yaml | head -10'
# expect: same as before (user, port, argo_base_url, etc.)
```

### Pass criteria

- Venv pip path was preferred (not the upstream self-updater).
- Venv argo-proxy version moved to latest stable PyPI release.
- `~/.config/argoproxy/config.yaml` is byte-identical to pre-test.
- `~/argovenv/` directory mtime moved (pip wrote new packages) but
  the directory wasn't recreated (would mtime the parent +
  recreate ownership; here we only expect package-internal mtimes
  to move).
- `/v1/models` now lists at least one new model entry (e.g.
  `claudeopus48` if it appeared between argo-proxy 3.0.0 and the
  current latest).
- Exit code is 0.

---

## Test 5: `update argo-anywhere` end-to-end (D-023)

**What's tested**: self-update from a v2.2.0 install to the
v2.2.1 tag, lossless replacement of `~/.argo_anywhere/argo_anywhere.sh`.

### Setup

Use `update argo-anywhere` from THIS working session to install a
v2.2.0 copy at the canonical install:

```sh
# Take a safety backup (independent of the script's own backup).
cp ~/.argo_anywhere/argo_anywhere.sh /tmp/argo_anywhere.sh.test5_backup
# Now downgrade to v2.2.0 by deleting the canonical install
# and re-bootstrapping from a v2.2.0 curl:
rm -f ~/.argo_anywhere/argo_anywhere.sh
curl -fsSL https://raw.githubusercontent.com/a-attia/argo-anywhere/v2.2.0/argo_anywhere.sh \
  -o ~/.argo_anywhere/argo_anywhere.sh
chmod 0755 ~/.argo_anywhere/argo_anywhere.sh
grep -m1 '^SCRIPT_VERSION=' ~/.argo_anywhere/argo_anywhere.sh
# expect: nothing (v2.2.0 has no SCRIPT_VERSION constant)
```

### Action

```sh
# Run from the working checkout (NOT from the canonical install --
# we want the upgrade machinery to update the canonical install).
bash argo_anywhere.sh update argo-anywhere 2>&1 | tee /tmp/update_self.log
```

### Expected output (key markers)

- `[argo_anywhere] Current script: argo_anywhere.sh v2.2.1`
- `[argo_anywhere] Upstream latest tag: v2.2.1 (version: 2.2.1)`
- `[argo_anywhere] Fetching https://raw.githubusercontent.com/a-attia/argo-anywhere/v2.2.1/argo_anywhere.sh ...`
- `[argo_anywhere] Fetched argo_anywhere.sh version: 2.2.1`
- `[argo_anywhere] Backup written: /Users/<you>/.argo_anywhere/argo_anywhere.sh.bak.<timestamp>.<pid>`
- `[ ok ] argo_anywhere.sh upgraded to v2.2.1 at /Users/<you>/.argo_anywhere/argo_anywhere.sh`

### Verification

```sh
# New canonical install matches upstream v2.2.1 byte-for-byte.
diff ~/.argo_anywhere/argo_anywhere.sh \
  <(curl -fsSL https://raw.githubusercontent.com/a-attia/argo-anywhere/v2.2.1/argo_anywhere.sh)
# expect: empty
# Backup exists and is the pre-upgrade v2.2.0.
ls -la ~/.argo_anywhere/argo_anywhere.sh.bak.*    # expect: one file, mode 0755 or 0644
grep -m1 '^SCRIPT_VERSION=' ~/.argo_anywhere/argo_anywhere.sh.bak.*
# expect: nothing (the v2.2.0 backup, as expected)
# Canonical install permissions are 0755 (executable for all).
stat -f '%Lp' ~/.argo_anywhere/argo_anywhere.sh   # expect: 755
# The new copy parses cleanly.
bash -n ~/.argo_anywhere/argo_anywhere.sh && echo OK
# Bare-command invocation works (PATH integration).
. ~/.argo_anywhere/env
argo_anywhere.sh -h | head -1   # expect: Usage line
```

### Cleanup

```sh
# Restore the test 5 backup.
cp /tmp/argo_anywhere.sh.test5_backup ~/.argo_anywhere/argo_anywhere.sh
chmod 0755 ~/.argo_anywhere/argo_anywhere.sh
# Remove any backup files left by the test.
rm -f ~/.argo_anywhere/argo_anywhere.sh.bak.*
```

### Pass criteria

- Upgrade resolves the v2.2.1 tag (not falling back to `main`).
- Fetched script is byte-identical to upstream v2.2.1.
- Existing v2.2.0 install is backed up (not lost).
- New install has mode 0755 (not the mktemp default of 0600).
- `bash -n` on the new install parses cleanly.
- Bare-command invocation works after `. ~/.argo_anywhere/env`.

---

## Test 6: `update argo-anywhere` refuses dirty git tree (D-023 safety)

**What's tested**: self-update aborts when the target lives inside
a git working tree with uncommitted changes.

### Setup

Point the canonical-install path at the working git checkout
(only for this test):

```sh
# Backup the real canonical install.
mv ~/.argo_anywhere ~/.argo_anywhere.test6_backup
mkdir -p ~/.argo_anywhere
# Make a symlink so the script's target path points into the git tree.
ln -s ~/AHMED_HOME/Research/Projects/Software/argo-anywhere/argo_anywhere.sh \
  ~/.argo_anywhere/argo_anywhere.sh
# Confirm the git tree has uncommitted changes (it should, since
# we're mid-session).
cd ~/AHMED_HOME/Research/Projects/Software/argo-anywhere && git status --porcelain | head -3
# expect: non-empty (modified files).
```

### Action

```sh
bash argo_anywhere.sh update argo-anywhere 2>&1 | head -5
echo "EXIT=$?"
```

### Expected output

```
...
[err ] Refusing to overwrite /Users/<you>/.argo_anywhere/argo_anywhere.sh: the directory is inside a git working tree (...)
[err ]   with uncommitted changes. This is almost certainly your development checkout.
[err ]   If you really want to overwrite, commit/stash first, or run 'git pull' instead.
...
EXIT=1
```

### Cleanup

```sh
rm -rf ~/.argo_anywhere
mv ~/.argo_anywhere.test6_backup ~/.argo_anywhere
```

### Pass criteria

- The script aborted BEFORE fetching or replacing anything.
- The error message names the dirty git tree path.
- Exit code is non-zero.
- The working checkout's modified files are untouched.

---

## Test 7: `update opencode` + `update claudecode` (D-022 laptop-tool path)

**What's tested**: laptop-side in-place upgrade re-runs the
upstream installer correctly.

### Setup

Capture pre-test versions:

```sh
opencode --version > /tmp/opencode_pre.txt
claude --version > /tmp/claude_pre.txt
```

### Action

```sh
bash argo_anywhere.sh update opencode claudecode 2>&1 | tee /tmp/update_laptop.log
```

### Expected output (per tool)

For `opencode`:

```
[argo_anywhere] ==> update opencode
[argo_anywhere] OpenCode installed: <path> (version <pre>)
# IF brew-managed:
[argo_anywhere] Brew-managed install detected; running 'brew upgrade sst/tap/opencode'...
# ELSE (curl|bash):
[argo_anywhere] Re-running upstream installer: curl -fsSL https://opencode.ai/install | bash ...
[ ok ] OpenCode upgraded: <new>.
```

For `claudecode`:

```
[argo_anywhere] ==> update claudecode
[argo_anywhere] Claude Code installed: <path> (version <pre>)
[argo_anywhere] Re-running upstream installer: curl -fsSL https://claude.ai/install.sh | bash ...
[ ok ] Claude Code upgraded: <new>.
```

### Verification

```sh
opencode --version
claude --version
# If pre-test version was already latest: same version reported, no error.
# If pre-test version was older: new version reported, matches upstream.
# In either case: OpenCode user configs at ~/.config/opencode/config.json
# are untouched.
md5 ~/.config/opencode/config.json   # expect: same as pre-test
# Claude Code OAuth state at ~/.claude.json untouched.
md5 ~/.claude.json 2>/dev/null   # expect: same as pre-test (if it existed)
```

### Pass criteria

- Both tools' binaries are re-installed (or no-op if already at
  latest, depending on the upstream installer's behavior).
- Neither tool's config / OAuth state is touched.
- Exit code is 0.

---

## Test 8: `update --all -y` from a fresh canonical install (full integration)

**What's tested**: the all-in-one upgrade flow with non-interactive
flag.

### Setup

```sh
# Confirm canonical install exists (from prior tests' restore).
ls -la ~/.argo_anywhere/argo_anywhere.sh
```

### Action

```sh
bash argo_anywhere.sh update --all -y 2>&1 | tee /tmp/update_all.log
```

### Expected output (high-level)

- 4 component blocks (argo-anywhere, argoproxy, opencode,
  claudecode), in registry order.
- Summary line: `[ ok ]   OK:      argo-anywhere argoproxy opencode claudecode`.
- If anything is already at latest: that component reports "up-to-
  date" or "no upgrade needed" and is still counted in OK.
- Exit code is 0.

### Pass criteria

- All 4 components processed; none in Failed list.
- No interactive prompts fired (--yes auto-confirmed any missing-
  component install prompts; in practice none of the 4 should be
  missing for an installed test rig).
- Exit code is 0.

---

## Test 9: `ensure_argoproxy_installed` extraction is behavior-preserving (D-022 refactor regression)

**What's tested**: `mode_server`'s install logic, now factored into
the new `ensure_argoproxy_installed` function, still behaves
identically to the inline v2.2.0 version.

### Approach

Code-review verification (no live test possible without a
controlled compute-node environment). Confirm:

1. The new `ensure_argoproxy_installed` function body at
   `argo_anywhere.sh:5176+` contains:
   - Python 3.10+ check.
   - Venv create-or-validate (honors `ARGO_ANYWHERE_FORCE_REINSTALL`).
   - `pip install --upgrade pip` + `pip install --upgrade argo-proxy`
     IFF `argo-proxy --version` or `serve --help` fails.
   - Final `ok "argo-proxy: $(... --version)"` line.
2. The new `mode_server` body at `argo_anywhere.sh:5103+` calls
   `ensure_argoproxy_installed || die ...` exactly where the inline
   block used to live.
3. No inline references to `${venv}/bin/argo-proxy` remain inside
   `mode_server` outside the `ensure_argoproxy_installed` call.

### Pass criteria

- Code review confirms the 3 points above.
- The next live `client` invocation (Test 10) succeeds without
  changes to the existing `mode_server` flow.

---

## Test 10: existing `client` flow still works (regression)

**What's tested**: every v2.2.0 path that did NOT change in D-022 +
D-023 (mode_client tunnel + ensure_or_reuse_tunnel + the per-tool
setup_*_cli_tool dispatcher) still works correctly.

### Action

```sh
# Tear down the existing tunnel.
bash argo_anywhere.sh stop
# Bring it back up via the full client flow.
bash argo_anywhere.sh client --cli-tool opencode 2>&1 | tail -20
```

### Verification

```sh
bash argo_anywhere.sh status 2>&1 | grep -E "ALL GREEN|FAIL|DEGRADED"
# expect: ALL GREEN
```

### Pass criteria

- Tunnel up; argo-proxy reachable; status reports ALL GREEN.
- The bootstrap helper fired exactly zero new bootstrap log lines
  (because `~/.argo_anywhere/` already exists from earlier tests).
- No regressions in any per-tool setup behavior.

---

## Post-test cleanup

```sh
# Remove any test backups left behind.
rm -f /tmp/argo_anywhere.sh.preupdate_backup
rm -f /tmp/argo_anywhere.sh.test5_backup
rm -f /tmp/argoproxy_version_pre_test
rm -f /tmp/models_before.txt /tmp/models_after.txt
rm -f /tmp/update_check_all.log /tmp/update_argoproxy.log
rm -f /tmp/update_self.log /tmp/update_laptop.log /tmp/update_all.log
rm -f /tmp/opencode_pre.txt /tmp/claude_pre.txt
rm -f ~/.argo_anywhere/argo_anywhere.sh.bak.*    # any leftover .bak files
```

---

## Acceptance + tag readiness

The v2.2.1 release is tag-ready when:

- All 10 tests pass without amendment (the live verification
  performed during the 2026-06-24 implementation session already
  exercised Tests 2, 4, and 5 mid-coding; this plan formalizes the
  full battery for release-gate verification).
- The `SCRIPT_VERSION` constant in `argo_anywhere.sh` is bumped
  from `"2.2.1-dev"` to `"2.2.1"`.
- The `PLAN.md` "Lifecycle stage" section's "Now" line is updated
  to reflect the v2.2.1 tag.

If any test surfaces an amendment, document it in a post-test
record (`notes/post_test_v2_2_1.md`) per the project's
post-test-record convention (matches `notes/test_plan_phase4.md`
mid-test amendment discipline).

---

*Created 2026-06-24 by Ahmed Attia (with substantial AI assistance
from Claude per `CONTRIBUTORS.md`). Drafted in lockstep with the
D-022 + D-023 implementation session.*
