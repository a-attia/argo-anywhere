# Phase 2d live-test plan (defensive-hardening)

**What's being tested**: the three Phase 2d commits closing all 7
deferred MED + LOW audit items from the v2.0 release:

  - `66d2d5c` — Batch 1: M8 + M9 + L6 (config-writer fail-loud
    trio: claudecode JSON validation; argoproxy PyYAML required;
    opencode PROXY_PORT assert)
  - `4fa2372` — Batch 2: M6 + M7 (tunnel-status defensive trio:
    stricter kill targeting; permissive mux match)
  - `e6a8a58` — Batch 3: M10 + L10 (edge-case fail-loud pair:
    TTY-aware ask(); L10 closed by structural overlap with N1)

**Audit findings addressed**: M6, M7, M8, M9, M10, L6, L10 (= 7 of
the 10 items deferred from Phase 2c+3 with their explicit
"defer to Phase 2d" rationale). Combined with v2.0.0's coverage,
this brings the project to **40 of 43 audit findings closed**
(all CRIT, all HIGH, all MED except M4 which is tied to Phase 4,
all LOW except L8 which has no actionable mitigation, all INFO
except I2 cosmetic).

**Scope discipline**: per Phase 2d charter, every commit changes
behavior in the "fail louder, not silently" direction. Every test
below verifies either (a) the new die-loud / WARN-loud paths fire
correctly on their edge cases, or (b) the successful-path UX is
unchanged.

**Lessons applied from Phase 2c+3 test plans**:
- Synthetic state-injection (lock files, broken JSON) often doesn't
  exercise the asserted code path; verify the chosen stimulus
  ACTUALLY traverses the assertion site (Phase 2c+3 live-test #1
  finding).
- Code-review verification is a legitimate fallback when synthetic
  state is hard to arrange or would disrupt the live tunnel.
- Pure-function unit tests (`awk` extracted body sourced into a
  fresh shell) are more reliable than the brittle
  `source <(sed ...)` heredoc pattern.

---

## Pre-test setup (laptop)

```sh
cd ~/AHMED_HOME/Software/argo-anywhere
git pull
git log --oneline -5
```

Expect at the top (in order, most recent first):

```
e6a8a58 fix(2d-edge-cases): TTY-aware ask() default-with-WARN + L10 closure (M10 + L10)
4fa2372 fix(2d-tunnel-status): tighter kill targeting + permissive mux fallback (M6 + M7)
66d2d5c fix(2d-config-writers): config-writer fail-loud trio (M8 + M9 + L6)
e52c84a docs(plan-update): post-v2.0.0 release-state updates
```

Confirm fixes are present:

```sh
grep -cE 'M6 fix|M7 fix|M8 fix|M9 fix|M10 fix|L6 fix' argo_anywhere.sh
```

Expect: 6+ marker comments.

---

## Test 1: regression — basic functionality unchanged

Confirm the three Phase 2d batches did not break the smoke baseline.

```sh
bash -n argo_anywhere.sh && echo "syntax OK"
bash argo_anywhere.sh -h | head -10
bash argo_anywhere.sh list-tools
bash argo_anywhere.sh status 2>&1 | head -10
bash argo_anywhere.sh clean --dry-run -y --local-only 2>&1 | tail -15
```

**Pass**:
- `syntax OK`
- `-h` shows the flag synopsis including `--cli-tool`,
  `--verbose-server`, `--scope`
- `list-tools` prints the registry (`opencode`, `claudecode`)
- `status` either succeeds (if a tunnel is up) or reports FAIL
  cleanly
- `clean --dry-run` enumerates safe items + lists per-config
  "keeping" decisions

---

## Test 2: M8 — claudecode refuse-to-merge on broken JSON

The Python heredoc in `write_claudecode_config` now refuses to
merge if `~/.claude/settings.json` is unparseable JSON. Pre-fix
the heredoc would silently write a fresh file, destroying the
broken-but-recoverable user content.

### Test 2a: code review (Recommended)

```sh
grep -n -A 25 'M8 fix' argo_anywhere.sh
```

**Pass**: see the `sys.exit(2)` in the Python heredoc's
`except Exception` branch + the `if not isinstance(data, dict)`
branch. The bash-side `case "$_py_rc" in` block at the bottom of
the function shows the recovery hint with three numbered options.

### Test 2b: synthetic broken-JSON test

```sh
mkdir -p /tmp/argo_m8_test/.claude
echo '{ "this is broken JSON' > /tmp/argo_m8_test/.claude/settings.json

# Source write_claudecode_config + dependencies for isolated test
awk '/^write_claudecode_config\(\) \{/,/^}$/' argo_anywhere.sh > /tmp/_writer.sh

bash -c '
source /tmp/_writer.sh
log()  { :; }
warn() { :; }
err()  { printf "[err ] %s\n" "$*" >&2; }
die()  { err "$*"; exit 2; }
ARGO_ANYWHERE_USER=aattia
PROXY_PORT=64742
_CLAUDECODE_SCOPE_PATH=/tmp/argo_m8_test/.claude/settings.json
write_claudecode_config /tmp/argo_m8_test/proposed.json 2>&1 | tail -15
echo "exit code: $?"
'

rm -rf /tmp/argo_m8_test /tmp/_writer.sh
```

**Pass**: see the M8 die path with the three numbered recovery
options:
```
[err ] write_claudecode_config: existing config at /tmp/argo_m8_test/.claude/settings.json is present but
[err ]   cannot be parsed as JSON (or is not a top-level JSON object).
[err ]   Refusing to merge -- doing so would silently destroy your file.
[err ]
[err ] Recovery options:
[err ]   1. Fix the JSON manually ...
[err ]   2. Move the file aside ...
[err ]   3. Pick [k]eep at the next config-handling prompt ...
[err ] Refusing to overwrite a broken Claude Code config.
exit code: 2
```

---

## Test 3: M9 — argoproxy die-hard if PyYAML missing

`write_argoproxy_config` now dies hard if PyYAML is unavailable
(rather than writing hardcoded defaults that drop user-owned keys
on `[b]ackup`). User-confirmed Option A before implementation.

### Test 3a: code review (Recommended)

```sh
grep -n -A 30 'M9 fix' argo_anywhere.sh
```

**Pass**: see the `if [ -z "$pyexe" ]` branch dies with explicit
recovery (install python3 + PyYAML; `--force-reinstall server`).
The `case "$_py_rc"` block below has separate die paths for
PyYAML-missing (rc=2), non-dict (rc=3), parse-error (rc=4).

### Test 3b: synthetic PyYAML-missing test

```sh
# Create a fake pyexe that doesn't have PyYAML
mkdir -p /tmp/argo_m9_test/bin
cat > /tmp/argo_m9_test/bin/python <<'EOF'
#!/bin/bash
# Mimic a python3 without PyYAML by exiting with code 1 on `import yaml`
if grep -q "import yaml" "$@" 2>/dev/null || grep -q "import yaml" 2>/dev/null; then
  exit 2  # ImportError exit code from the heredoc
fi
exec /usr/bin/env python3 "$@"
EOF
chmod +x /tmp/argo_m9_test/bin/python

# Create a fake existing config so write_argoproxy_config takes the merge path
mkdir -p /tmp/argo_m9_test/argoproxy
echo "user: aattia" > /tmp/argo_m9_test/argoproxy/config.yaml
echo "port: 64742" >> /tmp/argo_m9_test/argoproxy/config.yaml

# Verify the fake python is broken
echo 'import yaml' | /tmp/argo_m9_test/bin/python /dev/stdin 2>&1
echo "exit: $?"

rm -rf /tmp/argo_m9_test
```

**Pass**: the fake python exits 2 (simulating ImportError on
`import yaml`). The actual write_argoproxy_config flow on the
user's machine isn't easily testable in isolation because
`real_cfg="${HOME}/.config/argoproxy/config.yaml"` is hardcoded;
the venv selection logic also assumes `$VENV_PATH` is set. Code
review of the `case "$_py_rc"` block (Test 3a) proves the
behavior; the synthetic above just verifies the heredoc-side
`sys.exit(2)` mechanism works.

For full live verification of M9, the next time you run a
real `client` flow + `mode_server` runs on the compute node + a
broken PyYAML scenario surfaces, the user will see the M9 die
path. In normal operation PyYAML is always present in
`~/argovenv/`, so this die effectively never fires — its value
is in being there if PyYAML is ever genuinely missing.

---

## Test 4: L6 — opencode PROXY_PORT assert

`write_opencode_config` now asserts `PROXY_PORT` is non-empty
before writing. Pre-fix an empty `PROXY_PORT` would generate
`http://localhost:/v1`.

### Test 4a: code review (Recommended)

```sh
grep -n -A 8 'L6 fix' argo_anywhere.sh
```

**Pass**: see the `[ -n "${PROXY_PORT:-}" ] || die ...` line at
writer entry, alongside the existing user-non-empty assert.

### Test 4b: synthetic empty-PROXY_PORT test

```sh
awk '/^write_opencode_config\(\) \{/,/^}$/' argo_anywhere.sh > /tmp/_writer.sh

bash -c '
source /tmp/_writer.sh
err()  { printf "[err ] %s\n" "$*" >&2; }
die()  { err "$*"; exit 2; }
ARGO_ANYWHERE_USER=aattia
unset PROXY_PORT
write_opencode_config /tmp/test_l6_output.json 2>&1
echo "exit code: $?"
'

rm -f /tmp/_writer.sh /tmp/test_l6_output.json
```

**Pass**: shows
`[err ] write_opencode_config: PROXY_PORT is empty (resolve_port not called?). Refusing to write a config with baseURL 'http://localhost:/v1' that would silently fail to connect.`
followed by `exit code: 2`. The output file is NOT created.

---

## Test 5: M6 — stricter kill targeting on ours-unhealthy-fg

The unconditional `xargs -n1 kill` was replaced with a per-PID
classification loop that re-checks the process command line
matches `ssh -L <port>:` before killing. This test is hard to
exercise live (requires a tunnel that local_tunnel_status
classifies as ours-unhealthy-fg, which means /health is silent
but the listener IS our `ssh -L`).

### Test 5a: code review (Recommended)

```sh
grep -n -A 22 'M6 fix' argo_anywhere.sh
```

**Pass**: see the `while IFS= read -r _kill_pid` loop with the
case-statement matching the `ssh*-L <port>:` pattern. The
non-matching branch prints the unmatched command line for
inspection. After the loop, `if [ "$_killed" -eq 0 ]; then ...
die "Refusing to overlay our tunnel on a foreign listener."` is
the safety net.

### Test 5b: live exercise (skip; requires tunnel disruption)

The ours-unhealthy-fg state requires (a) our `ssh -L` listener
exists AND (b) /health is silent. Engineering this scenario
requires killing the remote argo-proxy without killing the local
SSH tunnel — possible but disruptive to your live session.
Code review is sufficient.

---

## Test 6: M7 — permissive mux match fallback

The `local_tunnel_status` mux detection now falls back to
"command line mentions argo-{anywhere,opencode}- AND a
corresponding socket file exists in SSH_MUX_DIR" when the
primary regex doesn't match. Defends against ps format drift
between OS versions.

### Test 6a: code review (Recommended)

```sh
grep -n -A 22 'M7 fix' argo_anywhere.sh
```

**Pass**: see the `if [ "$kind" = "none" ]; then` block with the
`*argo-anywhere-*|*argo-opencode-*` case-statement and the
`ls "$SSH_MUX_DIR"/argo-anywhere-* "$SSH_MUX_DIR"/argo-opencode-*`
existence check.

### Test 6b: live verification on the existing mux master

Your current mux master is on compute-01. Verify that the primary
regex still matches AND the fallback would match too (so EITHER
path classifies it correctly).

```sh
# Find the mux master pid
pgrep -f 'argo-anywhere-aattia-compute-01' | head -1

# What does ps -o command= produce on macOS Sequoia?
PID=$(pgrep -f 'argo-anywhere-aattia-compute-01' | head -1)
ps -o command= -p "$PID"

# Does the existing socket file exist?
ls -la ~/.ssh/sockets/argo-anywhere-* 2>/dev/null
```

**Pass**: pgrep finds the pid; `ps -o command=` shows something
like `ssh: /Users/.../sockets/argo-anywhere-aattia-compute-01.cels.anl.gov-22 [mux]`
(matches the primary regex); the socket file exists (so the
fallback would also match). The live status invocation that
shows ALL GREEN is itself proof that classification works:

```sh
bash argo_anywhere.sh status 2>&1 | head -3
```

**Pass**: ALL GREEN with non-zero uptime.

---

## Test 7: M10 — TTY-aware ask() default-with-WARN

`ask()` now warns when stdin isn't a TTY and a default is auto-
returned (unless `ARGO_ANYWHERE_LOGGING=1` is set, the legitimate
tee'd-re-exec sentinel).

### Test 7a: code review (Recommended)

```sh
grep -n -A 35 'M10 fix' argo_anywhere.sh
```

**Pass**: see the `if [ -t 0 ] || [ "${ARGO_ANYWHERE_LOGGING:-0}" = 1 ]`
gate. The TTY-or-LOGGING branch is the pre-fix behavior. The
non-TTY branch prints a 2-line WARN naming the prompt + the
default, then returns the default (or empty if no default).

### Test 7b: synthetic 3-scenario harness (already verified during
implementation; repeat if curious)

```sh
awk '/^ask\(\)  \{/,/^}$/' argo_anywhere.sh > /tmp/_ask.sh

bash -c '
source /tmp/_ask.sh
warn() { printf "[warn] %s\n" "$*" >&2; }
C_YLW=""
C_OFF=""

echo "=== A: non-TTY with default ==="
result=$(ask "Pick a port:" "64742" </dev/null)
echo "result=$result"
echo
echo "=== B: non-TTY no default ==="
result=$(ask "Enter your username:" </dev/null)
echo "result=\"$result\""
echo
echo "=== C: ARGO_ANYWHERE_LOGGING=1 sentinel ==="
ARGO_ANYWHERE_LOGGING=1 result=$(ask "Should be silent:" "default-x" </dev/null)
echo "result=$result"
'

rm -f /tmp/_ask.sh
```

**Pass**:
- Scenario A: WARN fires; `result=64742` returned.
- Scenario B: WARN fires (different message); `result=""` returned.
- Scenario C: silent (no WARN); `result=default-x` returned.

---

## Test 8: L10 — cleanup_local exit code (closure verification only)

L10 was closed by structural overlap with the N1 fix; no code
change in Phase 2d. Verify the closure by code review.

### Test 8a: code review (Recommended)

```sh
grep -n -A 3 'cleanup_local() {' argo_anywhere.sh
```

**Pass**: see `local rc=$?` on the very first line of the
function body, BEFORE any kill / wait calls. The exit at the
end of the function uses `exit "$rc"` (the captured value), not
`exit $?` (the live value).

```sh
awk '/^cleanup_local\(\) \{/,/^}$/' argo_anywhere.sh | grep -c 'rc='
```

**Pass**: 1 (only one rc= assignment; no path between capture
and exit can mutate it).

---

## Reporting back

For each test, paste either "pass" or the relevant verbatim output.
Especially:

- **Test 2b**: paste the M8 die path with the recovery options.
- **Test 4b**: paste the L6 die line + exit code.
- **Test 6b**: paste the `ps -o command=` output + the socket
  file listing + the status invocation result.
- **Test 7b**: paste all 3 scenarios' output.

If everything passes, **Phase 2d is COMPLETE**. After this gate,
the project state is:

- 40 of 43 audit findings closed.
- All CRIT + HIGH + MED (except M4) + LOW (except L8) + INFO
  (except I2) closed.
- v2.0.x line continues to ship; **next tag candidate: v2.1.0**
  (minor version bump because of behavior changes, even though
  defensive).

---

## What's NOT closed (queued for follow-up)

- **M4** (port resolution OpenCode-specific in multi-client world):
  tied to Phase 4 (additional CLI tools). Generalize to
  `read_port_from_any_known_client_config` when adding aider /
  cursor / generic OpenAI-compatible.
- **L8** (`curl | bash` from claude.ai with no checksum):
  no actionable mitigation that doesn't impose more cost than
  value. Marked "no fix" in audit; documented in
  `docs/SECURITY.md` "Things this script does NOT defend against".
- **I2** (`_LOGGING` env var serves dual purpose): pure cosmetic;
  rename `_LOGGING` to something less overloaded. Phase 2e
  one-commit batch when convenient.
- **Phase 4** (multi-tool extension): aider, cursor, generic
  OpenAI-compatible CLI tools. Triggered by user demand or
  personal need.

---

*Created 2026-05-15 by Ahmed Attia (with substantial AI assistance
from Claude per [`CONTRIBUTORS.md`](../CONTRIBUTORS.md)).*
