# Phase 4 live-test plan (v2.2.0 multi-tool framework)

**What's being tested**: the five Phase 4 commits landing the
per-tool scope framework, port-as-state, OpenCode project-scope,
and cross-client port-coherence on top of v2.1.0:

  - `ea94042` — B0: pre-Phase-4 hotfix; `prompt_port_choice` helper
    factoring + `mode_stop` case-label fix (latent v2.1.x bug)
  - `46c19a7` — B1a: scope framework refactor (D-017 + D-018 +
    D-019; per-tool default scope policy; per-tool scope vocabulary
    contract; `ARGO_ANYWHERE_SCOPE` user-facing + `_SCOPE_OVERRIDE`
    internal; `CLAUDECODE_SCOPE` deprecation)
  - `ecc6c64` — B1b: OpenCode project-scope support
    (`opencode_pick_scope`; `_git_root_or_cwd` helper;
    `OPENCODE_GLOBAL_CONFIG` + `OPENCODE_PROJECT_CONFIG_BASENAME`)
  - `108e5d6` — B2: port-as-transport-state (D-020); new
    `~/.config/argo_anywhere/port` cache + write-through;
    three-case first-run migration; closes audit M4
  - `549cb93` — B3: cross-client port-coherence (D-021); passive
    reporting in `mode_status`; proactive prompt in
    `_client_common_setup`; `enumerate_client_ports` +
    `detect_port_disagreement` helpers

**Audit findings addressed**: M4 (closed by B2). Combined with
v2.0.0 + v2.1.0 + Phase 2e cosmetic closure, this brings the project
to **42 of 43 audit findings closed** (only L8 remains as documented
no-fix).

**Scope discipline**: per Phase 4 charter, every commit either adds
a new framework primitive (B0, B1a, B2, B3) or applies it to a
specific tool (B1b for OpenCode project-scope). Every test below
verifies either (a) the new behavior fires correctly on its trigger,
(b) the conflict-detection prompts fire when expected and behave
correctly under `[m/u/k/a]`, or (c) the existing all-green path is
unchanged.

**Lessons applied from prior test plans**:
- Synthetic state-injection must ACTUALLY traverse the asserted code
  path; verify via instrumentation or by reading the WARN/log output
  (Phase 2c+3 #1 finding; Phase 2d #3 reaffirmation).
- Pipes can mask exit codes (`| tail` resets `$?`); when an exit code
  matters, capture in a temp file and inspect.
- Code-review verification is a legitimate fallback for paths whose
  stimulus would disrupt the live tunnel (e.g. inducing a stale
  legacy env warning requires a fresh shell with the var set).
- For multi-config disagreement tests, deliberately edit per-tool
  configs to disagree BEFORE invoking the test; confirm via `status`
  before running `client`.

---

## Pre-test setup (laptop)

```sh
cd ~/AHMED_HOME/Research/Projects/Software/argo-anywhere
git log --oneline -8
```

Expect at the top (in order, most recent first):

```
549cb93 feat(b3): cross-client port-coherence enforcement (D-021)
108e5d6 feat(b2): port-as-transport-state (D-020); closes audit M4
ecc6c64 feat(b1b): opencode project-scope support
46c19a7 feat(b1a): scope framework refactor (D-017 + D-018 + D-019)
ea94042 fix(b0): factor prompt_port_choice + mode_stop case-label fix
431c8e4 cleanup(2e): rename _LOGGING -> _ARGO_ANYWHERE_REEXEC (I2 closure)
96ed8a2 docs(plan-update): backfill audit STATUS blocks; phase2d defects
<...v2.1.0 release commit and earlier...>
```

Confirm the five Phase 4 batches are present:

```sh
grep -cE 'B0 fix|B1a|B1b|B2 (fix|refactor)|B3 (Phase 4)|D-017|D-018|D-019|D-020|D-021' argo_anywhere.sh
```

Expect: 15+ marker comments.

Snapshot pre-test state so any cleanup is easy:

```sh
ls -la ~/.config/argo_anywhere/
cat ~/.config/argo_anywhere/port  # may not exist if never run v2.2
cat ~/.config/argo_anywhere/user  # exists from prior v2.x runs
cat ~/.config/argo_anywhere/node  # exists from prior v2.x runs
ls ~/.claude.json 2>/dev/null && echo "claudecode OAuth state present" \
                              || echo "no claudecode OAuth state"
ls ~/.claude/settings.json 2>/dev/null \
   && python3 -c 'import json; print(json.load(open("/Users/'$USER'/.claude/settings.json")).get("env", {}))'
ls ~/.config/opencode/config.json 2>/dev/null \
   && grep baseURL ~/.config/opencode/config.json
```

Record results for cross-reference in Tests 5, 6, 9, 10.

---

## Test 1: regression — basic functionality unchanged

Confirm the five Phase 4 batches did not break the smoke baseline.

```sh
bash -n argo_anywhere.sh && echo "syntax OK"
bash argo_anywhere.sh -h | head -10
bash argo_anywhere.sh list-tools
bash argo_anywhere.sh status 2>&1 | head -15
bash argo_anywhere.sh clean --dry-run -y --local-only 2>&1 | tail -15
```

**Pass**:
- `syntax OK` printed.
- `-h` shows the usage line including `--scope project|global`.
- `list-tools` shows `opencode` and `claudecode` (no surprise
  additions; aider not yet integrated).
- `status` either reports ALL GREEN (tunnel up) or fails on the
  `/health` line; no syntax errors; no `[warn]` from D-021 if no
  configs disagree.
- `clean --dry-run` prints risk-tiered enumeration without errors.

**Fail trigger**: any `bash: ...syntax error...`; any unhandled
`set -u` "unbound variable"; missing `--scope` in `-h` output.

---

## Test 2: port cache — first-run migration Case 2 (single config; agree)

Verify the D-020 one-shot port migration when one tool's config
exists and the cache is empty. **This test recreates the cache from
scratch.**

Setup:

```sh
mv ~/.config/argo_anywhere/port ~/.config/argo_anywhere/port.bak 2>/dev/null \
   || true
grep baseURL ~/.config/opencode/config.json   # note current port
```

Trigger (no live tunnel needed; resolve_port runs in any subcommand
that hits `main`):

```sh
bash argo_anywhere.sh status 2>&1 | head -20
cat ~/.config/argo_anywhere/port
```

**Pass**:
- Output contains a log line like:
  ```
  [log] Port cache (~/.config/argo_anywhere/port) empty on first run;
        migrating port <N> from existing client config(s) [opencode:global].
  ```
- The new cache file contains the same port that's in the OpenCode
  config baseURL.

**Cleanup** (restore prior state):

```sh
mv ~/.config/argo_anywhere/port.bak ~/.config/argo_anywhere/port 2>/dev/null \
   || true
```

---

## Test 3: port cache — write-through precedence

Verify that passing `--port N` updates the cache.

```sh
ORIG_CACHE="$(cat ~/.config/argo_anywhere/port)"
bash argo_anywhere.sh --port 65500 status 2>&1 | head -5
cat ~/.config/argo_anywhere/port
```

**Pass**: cache file now contains `65500` (write-through fired even
though `--port` was the explicit source).

**Cleanup**:

```sh
echo "$ORIG_CACHE" > ~/.config/argo_anywhere/port
```

---

## Test 4: port cache — env var precedence over cache

```sh
ORIG_CACHE="$(cat ~/.config/argo_anywhere/port)"
ARGO_ANYWHERE_PORT=65501 bash argo_anywhere.sh status 2>&1 \
  | grep -E 'Using port|source:'
```

**Pass**: log line shows `Using port: 65501` with source mentioning
`ARGO_ANYWHERE_PORT env`.

```sh
cat ~/.config/argo_anywhere/port    # should also be 65501 now (write-through)
echo "$ORIG_CACHE" > ~/.config/argo_anywhere/port
```

---

## Test 5: scope framework — per-tool validation rejects bogus `--scope`

Verify D-018: per-tool vocabulary validation catches typos.

```sh
bash argo_anywhere.sh --cli-tool opencode --scope projct status 2>&1 \
  | grep -iE 'scope|invalid|valid values' || echo "NO MATCH"
```

(Even though `status` doesn't write configs, the parser still
validates `--scope` against the picked tool's vocabulary.)

Note: validation may or may not fire at parse time depending on
where in the picker chain status calls land; if it doesn't fire,
re-run the same against `setup` or `client`:

```sh
bash argo_anywhere.sh --cli-tool opencode --scope projct setup 2>&1 \
  | head -20
```

Use `^C` immediately after the picker fires.

**Pass**: dies with a message naming the unknown scope and listing
the valid values (`global project` for opencode; `global project`
for claudecode).

---

## Test 6: scope framework — `CLAUDECODE_SCOPE` deprecation warning

Verify D-019: the legacy env var is honored once per session with a
WARN. Requires a fresh shell to avoid double-warning suppression
from prior runs.

```sh
( CLAUDECODE_SCOPE=global bash argo_anywhere.sh --cli-tool claudecode \
       status 2>&1 | grep -iE 'CLAUDECODE_SCOPE|ARGO_ANYWHERE_SCOPE|deprecated' )
```

**Pass**: output contains exactly one line like
```
[warn] CLAUDECODE_SCOPE is deprecated; use ARGO_ANYWHERE_SCOPE instead.
```

**Code-review fallback**: if the WARN doesn't trigger via `status`,
inspect Section 6 promotion block:

```sh
grep -n "CLAUDECODE_SCOPE" argo_anywhere.sh
```

Confirm the `_warn_legacy_env CLAUDECODE_SCOPE ARGO_ANYWHERE_SCOPE`
call is present in the env-promotion block.

---

## Test 7: cross-client coherence — status reports disagreement

Verify D-021 passive reporting. Requires deliberate misconfiguration.

Setup (only if claudecode global config exists; otherwise SKIP):

```sh
ORIG_CC_PORT="$(python3 -c 'import json; \
  print(json.load(open("/Users/'$USER'/.claude/settings.json"))["env"].get("ANTHROPIC_BASE_URL", "MISSING"))')"
# Capture current; if MISSING skip this test.

# Edit claudecode global to a wrong port:
python3 -c '
import json, pathlib
p = pathlib.Path("/Users/'$USER'/.claude/settings.json")
d = json.loads(p.read_text())
d.setdefault("env", {})["ANTHROPIC_BASE_URL"] = "http://localhost:65999/v1"
p.write_text(json.dumps(d, indent=2))
'
```

Trigger:

```sh
bash argo_anywhere.sh status 2>&1 | tail -20
```

**Pass**: output contains the D-021 warn block:

```
[warn] Cross-client port disagreement detected (D-021):
[warn]   Resolved port (cache / CLI / env / default): <N>
[warn]   Disagreeing client config(s):
[warn]     claudecode global 65999 /Users/.../claude/settings.json
[warn]   Run 'argo_anywhere.sh client' to canonicalize via the [m/u/k/a] prompt.
```

`status` exit code is NOT affected by the disagreement (unchanged
from v2.1 semantics).

**Cleanup**:

```sh
python3 -c '
import json, pathlib
p = pathlib.Path("/Users/'$USER'/.claude/settings.json")
d = json.loads(p.read_text())
d.setdefault("env", {})["ANTHROPIC_BASE_URL"] = "'$ORIG_CC_PORT'"
p.write_text(json.dumps(d, indent=2))
'
```

---

## Test 8: cross-client coherence — `client` proactively prompts

Verify D-021 proactive prompt. Requires deliberate misconfiguration
(reuse Test 7's setup) **and** a willingness to either accept the
canonical-rewrite outcome or abort the prompt.

Setup: re-introduce the disagreement per Test 7.

Trigger:

```sh
bash argo_anywhere.sh --cli-tool claudecode client
```

Watch for the proactive prompt around the "Cross-client port
disagreement" warn block, then:

```
[?] Resolved=<N>, claudecode global=65999. Pick one:
    [m]igrate (rewrite to <N>), [u]se-once, [k]eep (switch to 65999), [a]bort
```

Answer `[a]bort` to leave configs untouched, OR `[m]igrate` to let
the script canonicalize (recommended for the test to also exercise
the rewrite path).

**Pass**:
- The prompt fires AFTER node selection / MFA acceptance but
  BEFORE per-tool config write.
- `[m]igrate` choice results in claudecode config now showing the
  canonical port; `status` afterwards shows no disagreement.
- `[a]bort` cleanly exits with no state changes.

**Cleanup**: if `[a]bort`'d, restore per Test 7. If `[m]igrate`'d,
nothing to clean up.

---

## Test 9: OpenCode project-scope — write to `<git-root>/opencode.json`

Verify B1b: `--cli-tool opencode --scope project` writes to the
project, not the global config.

Setup (use a throwaway git repo; do NOT contaminate this repo):

```sh
mkdir -p /tmp/argo-anywhere-test-proj && cd /tmp/argo-anywhere-test-proj
git init -q
```

Trigger (with the live tunnel up, OR `[a]bort` at the SSH prompt
to validate just the scope-resolution path):

```sh
bash ~/AHMED_HOME/Research/Projects/Software/argo-anywhere/argo_anywhere.sh \
     --cli-tool opencode --scope project setup
```

Walk through prompts until either the OpenCode picker resolves and
writes the config, OR an earlier prompt where you can `^C` once
you've seen the `[log] OpenCode scope: project (/tmp/argo-anywhere-test-proj/opencode.json)`
line.

**Pass**:
- `/tmp/argo-anywhere-test-proj/opencode.json` exists after the run.
- `~/.config/opencode/config.json` is UNTOUCHED (mtime unchanged).
- The path printed at the end of setup matches the project file.

**Cleanup**:

```sh
cd ~
rm -rf /tmp/argo-anywhere-test-proj
```

---

## Test 10: scope-switch prompt fires on global vs project conflict

Verify D-017 conflict detection: explicit `--scope global` while
`~/.claude.json` is present (OAuth state) triggers the
`[k]eep / [s]witch / [a]bort` prompt.

Pre-condition: `~/.claude.json` exists (Test 0 confirms).

Trigger:

```sh
bash argo_anywhere.sh --cli-tool claudecode --scope global setup
```

**Pass**:
- Before the OpenCode-side / tunnel-side work begins, the script
  warns about OAuth precedence and prompts:
  ```
  [?] --scope global would shadow your ~/.claude.json OAuth state.
      [k]eep going (accept the risk), [s]witch to project, [a]bort:
  ```
- `[s]witch` lands the config in project scope; `[k]eep` proceeds
  with global; `[a]bort` exits with no state changes.

**Cleanup**: if `[s]witch` or `[k]eep` chose to actually run the
setup, inspect the written file and restore the prior config if
desired (use the `*.bak.*` backup the script writes automatically).

---

## Test 11: `mode_stop` case-label fix (B0)

Verify B0's `mode_stop` regression fix. Requires our own tunnel up.

Setup:

```sh
bash argo_anywhere.sh status 2>&1 | grep -E 'ALL GREEN|listener'
# Confirm tunnel is up and listener is OURS (pid is an ssh process).
```

Trigger:

```sh
bash argo_anywhere.sh stop 2>&1 | head -20
```

**Pass**:
- Output contains:
  ```
  [log] Killing local SSH tunnel listening on :<N>...
  [ ok ] Killed: <pid>
  [warn] Note: this does NOT stop argo-proxy on the ANL node. ...
  ```
- Output does NOT contain the multi-paragraph "blast radius"
  warning intended for the external-listener case (no mention of
  "killing it will break any laptop whose SSH tunnel...").

**Cleanup**: restart the tunnel for subsequent tests if desired:

```sh
bash argo_anywhere.sh --cli-tool opencode client &
# wait for ALL GREEN, then ^Z + bg if needed
```

---

## Test 12: end-to-end — fresh `client` invocation with live tunnel

Full integration test. Tears down any prior tunnel, runs `client`
cold, verifies ALL GREEN and that scope/port/config writes all
behaved per Phase 4 expectations.

```sh
bash argo_anywhere.sh stop 2>/dev/null || true
bash argo_anywhere.sh clean -y --local-only 2>&1 | tail -5
# Selectively keep the user/node cache to avoid re-prompting:
echo "$ANL_USER" > ~/.config/argo_anywhere/user
echo "compute-01.cels.anl.gov" > ~/.config/argo_anywhere/node

bash argo_anywhere.sh --cli-tool opencode client
```

Accept any prompts; complete the Duo MFA when prompted. Wait for
the green summary box.

**Pass**:
- `status` afterwards reports ALL GREEN.
- `~/.config/argo_anywhere/port` exists and matches the listener
  port.
- No D-021 disagreement warning in status output.
- `gather_summary` + `render_summary` boxes display correctly.

**Cleanup**: leave the tunnel up (used by ongoing work).

---

## Result template

For each test, record one of:

- **PASS** — observed behavior matches "Pass" criteria; no code
  amendments.
- **PASS-with-amendment** — observed a defect that required a code
  edit; record commit SHA + amendment summary.
- **FAIL** — observed behavior does not match Pass criteria and
  required deferral; document blocker.
- **SKIP** — preconditions not met (e.g. no `~/.claude.json` for
  Test 10; user opts not to mutate live configs).
- **REVIEW-ONLY** — verified by code inspection rather than live
  execution; document the inspection.

Goal: **zero PASS-with-amendment** (Phase 2d's standard;
demonstrates the smoke discipline caught everything pre-tag).
Any FAIL blocks the v2.2.0 tag.

---

*Created 2026-05-18 by Ahmed Attia (with substantial AI assistance
from Claude per [`CONTRIBUTORS.md`](../CONTRIBUTORS.md)) as the
Phase 4 v2.2.0 release-gate live-test plan. Phase 4 batches:
B0 (`ea94042`), B1a (`46c19a7`), B1b (`ecc6c64`), B2 (`108e5d6`),
B3 (`549cb93`). B4 (cursor out-of-integration docs) deferred to
v2.3 because docs.cursor.com is webfetch-unreachable; needs
manually-collected citations.*
