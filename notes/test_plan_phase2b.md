# Phase 2b live-test plan (HIGH-severity audit fixes)

**What's being tested**: the five Phase 2b commits closing all
remaining HIGH-severity items from `docs/AUDIT_2026-05-12.md`:

  - `19414cc` — Batch 1: P2 (argo-proxy verbose=false default; `--verbose-server` opt-in)
  - `564cb26` — Batch 2: N1 (Ctrl+C exit summary in `cleanup_local`)
  - `5437556` — Batch 3: H1+H2+H3 (CSPO trio: preflight + pick_node + probe-nodes)
  - `30915ac` — Batch 4: H5+H6+H7 (identity trio: proxy reuse + claudecode default + privacy warning)
  - `33434c9` — Batch 5: H4+H8 (SSH housekeeping: port-range clamp + mux exit syntax)

**Audit findings addressed**: H1-H8, P2, N1 — every HIGH-severity
item except H9 (closed pre-Phase-2b by the rename). After this
verification, **Phase 2b is complete** and the remaining audit work
is Phase 2c (~23 medium/low/info items).

**Lessons applied from Phase 2a test plan**:
- No inline `# comment` after a command (zsh treats `#` literally
  and produces a syntax error). All comments either precede the
  command on their own line or follow `;` on the same line.
- Where a test would force a real SSH failure (and thus burn a CSPO
  attempt), prefer a code-review-only verification or a synthetic
  harness instead.

---

## Pre-test setup (laptop)

```sh
cd ~/AHMED_HOME/Software/argo-anywhere
git pull
git log --oneline -7
```

Expect `33434c9` at top (or newer if more commits land before live
testing).

```sh
# Confirm fixes are present (each commit leaves a "<id> fix" marker comment):
grep -cE 'P2 fix|N1|H1 fix|H2 fix|H3 fix|H4 fix|H5 fix|H6 fix|H7 fix|H8 fix' argo_anywhere.sh
```

Expect: at least 11 (multiple comment markers across the fixes).

---

## Test 1: regression — basic functionality unchanged

Confirm Phase 2a + Phase 2b combined did not break the smoke baseline.

```sh
bash -n argo_anywhere.sh && echo "syntax OK"
bash argo_anywhere.sh -h | head -10
bash argo_anywhere.sh list-tools
bash argo_anywhere.sh status 2>&1 | head -10
bash argo_anywhere.sh clean --dry-run -y --local-only 2>&1 | tail -15
```

**Pass**:
- syntax OK
- `-h` shows the new `--verbose-server` flag in the synopsis lines
- list-tools prints the registry (`opencode`, `claudecode`, ...)
- status either succeeds (if a tunnel is up) or reports FAIL cleanly
- `clean --dry-run` enumerates safe items + lists per-config "keeping"
  decisions; the mux-socket dry-run lines show the new H8 syntax
  (`ssh -O exit -S <socket> placeholder`)

---

## Test 2: P2 — argo-proxy verbose default off (Batch 1, `19414cc`)

The previous default wrote `verbose: true` into
`~/.config/argoproxy/config.yaml` on the compute node, leaking
prompts to `~/.argo_anywhere.server.log` (mode 644). The fix:
default to `verbose: false`; opt in with `--verbose-server` (or
`ARGO_ANYWHERE_VERBOSE_SERVER=1`).

### Test 2a: flag is documented in usage + long help

```sh
bash argo_anywhere.sh -h | grep -A 1 -- '--verbose-server'
bash argo_anywhere.sh help | grep -A 4 'ARGO_ANYWHERE_VERBOSE_SERVER'
```

**Pass**: both commands print the flag/env-var description.

### Test 2b: flag is parsed

```sh
bash argo_anywhere.sh --verbose-server status 2>&1 | head -3
```

**Pass**: status runs normally (no "unknown flag" error). The flag
sets `ARGO_ANYWHERE_VERBOSE_SERVER=1` for any subcommand; status
itself doesn't react to it, so this just confirms the parser
accepts it.

### Test 2c: argo-proxy config on the compute node has verbose=false

This is best verified after the next live `client` run (most
recent invocation rewrites the config on the node). After your
next `bash argo_anywhere.sh --cli-tool <name> client`:

```sh
ssh aattia@compute-01.cels.anl.gov 'grep -E "^verbose:" ~/.config/argoproxy/config.yaml'
```

**Pass**: prints `verbose: false`.

> **Live-test #1 finding (2026-05-14)**: the original P2 fix used
> `data.setdefault('verbose', verbose_default)` in the PyYAML merge
> path, intending to "preserve user's explicit choice." That was
> wrong: the pre-P2 script wrote `verbose: true` automatically (no
> user input), so on first upgrade `setdefault` preserved the old
> `true` and the new `false` default silently did NOT take effect.
> Fixed in a follow-up commit by switching to direct assignment
> (`data['verbose'] = verbose_default`). The user's explicit-opt-in
> channel is the `--verbose-server` CLI flag, NOT the file content.
> Test 2c above passes after the amendment lands AND the user has
> re-run `client` once with the new script (the run that scp's the
> fixed script to the node + rewrites the config).
>
> If you find `verbose: true` after running `client` from the new
> script, check that:
> 1. The script on the compute node has the amendment:
>    `ssh aattia@compute-01.cels.anl.gov 'grep "data\[.verbose.\] = " ~/.argo_anywhere.sh'`
>    expected output: a line of Python code with the assignment.
> 2. The `client` invocation actually reached `mode_server` and
>    rewrote the config (look for `[ ok ] argo-proxy config already
>    up to date` OR `argo-proxy config written` in the log; if you
>    see neither, the local-reuse path short-circuited and the
>    config was not touched this run).

### Test 2d: opt-in via flag flips it back to true

```sh
bash argo_anywhere.sh --cli-tool opencode --verbose-server client
```

In a separate terminal once the tunnel is up:

```sh
ssh aattia@compute-01.cels.anl.gov 'grep -E "^verbose:" ~/.config/argoproxy/config.yaml'
```

**Pass**: prints `verbose: true`.

After verifying, kill the foreground client + re-run WITHOUT
`--verbose-server` to restore the safe default before doing any
real prompt work.

### Test 2e: opt-in via env var works the same

```sh
ARGO_ANYWHERE_VERBOSE_SERVER=1 bash argo_anywhere.sh --cli-tool opencode client
```

Same verification as 2d (config on node should show
`verbose: true`). Equivalent to the flag.

---

## Test 3: N1 — Ctrl+C exit summary (Batch 2, `564cb26`)

Foregrounded `client`, `setup`, and `tunnel` modes now print a short
summary when the user Ctrl+C's, explaining that the local tunnel +
monitor stopped, the remote argo-proxy is still alive, and how to
reuse / fully stop / fully clean.

### Test 3a: client mode prints the summary

```sh
bash argo_anywhere.sh --cli-tool opencode client
```

Wait for the status box + "Foregrounding ..." message. Press
**Ctrl+C**.

**Pass**: see (in this order, after the cleanup log lines):

```
[ ok ] Local tunnel and health monitor stopped.
[ ok ] The remote argo-proxy on compute-01.cels.anl.gov is still running (intentional).
[argo_anywhere]   - To use it again: bash argo_anywhere.sh --cli-tool opencode client
[argo_anywhere]       (will detect and reuse the existing proxy)
[argo_anywhere]   - To fully stop:   bash argo_anywhere.sh stop
[argo_anywhere]   - To remove all artifacts (local + remote): bash argo_anywhere.sh clean
```

The reuse-command line should mention the actual `--cli-tool`
value you used.

### Test 3b: tunnel mode prints the summary (tool-agnostic hint)

```sh
bash argo_anywhere.sh tunnel
```

Wait for the foregrounded monitor; **Ctrl+C**.

**Pass**: same summary, but the reuse hint is `bash
argo_anywhere.sh tunnel` (no `--cli-tool` mentioned).

### Test 3c: status mode does NOT print the summary

```sh
bash argo_anywhere.sh status 2>&1 | tail -5
```

**Pass**: the last few lines are the gather/render summary box;
NOT the new N1 ok/log lines. status never owns a foregrounded
tunnel, so the N1 summary block correctly does not fire.

### Test 3d: synthetic 4-scenario harness (already verified during
implementation; here for re-verification if needed)

A standalone harness exercised:
- A: client mode + `--cli-tool opencode` -> full summary, opencode hint
- B: tunnel mode -> full summary, tunnel hint
- C: status mode -> SILENT
- D: client mode + early-die path (no monitor started) -> SILENT

Re-running this harness is documented in commit `564cb26`'s body
(see `git show 564cb26 -- argo_anywhere.sh | head -80`). Skip
unless the live tests above show unexpected behavior.

---

## Test 4: H1 — ssh_preflight uses ssh_args (Batch 3, `5437556`)

Off-network `--no-mfa --node compute-X` previously did a direct
SSH connect (no `-J jumphost`), which always times out off-network
and contributed to CSPO. Fix: include `$(ssh_args ...)` so
ProxyJump is applied.

### Test 4a: code review (Recommended; no risk)

```sh
grep -n -A 16 'H1 fix' argo_anywhere.sh
```

**Pass**: the BatchMode test ssh call now includes
`$(ssh_args "$user" "$target")` between the option flags and the
`"${user}@${target}" true` argument. The `# H1 fix` comment
explains the off-network rationale.

### Test 4b: run preflight via a normal `status` invocation

```sh
bash argo_anywhere.sh status 2>&1 | head -10
```

`status` doesn't itself run `ssh_preflight`, but if you have a
live tunnel from the existing mux master (you do), the status
report should still be ALL GREEN — confirming the existing
session was not disrupted by the preflight code change.

**Pass**: status box renders with no SSH attempts triggered
(check `~/.config/argo_anywhere/ssh-fail-lock-count` if curious;
should not have changed).

### Test 4c: live preflight against the picked node (OPTIONAL; uses the existing master)

```sh
bash argo_anywhere.sh --cli-tool opencode client --node compute-01.cels.anl.gov
```

**Pass**: client establishes (reusing the existing healthy mux +
tunnel + remote proxy). The preflight log line
`Testing SSH access to aattia@compute-01.cels.anl.gov` should
either succeed silently (BatchMode preflight is skipped under
MFA mode anyway, since `mfa_enabled` is true on Duo hosts and
the function early-returns after `ssh_mux_open`) — verify this
by re-reading `ssh_preflight` if needed.

The H1 path only fires under `--no-mfa`. Off-network testing
of `--no-mfa --node compute-X` is deferred to the user's next
travel scenario; flag here that it should be re-tested then.

---

## Test 5: H2 — pick_node interactive retry cap (Batch 3, `5437556`)

`pick_node` now caps hostname-typing attempts at 5 per call, so a
confused user can't burn unlimited CSPO attempts.

### Test 5a: code review (Recommended)

```sh
grep -n -A 60 'H2 fix' argo_anywhere.sh | head -80
```

**Pass**: see `_PICK_NODE_MAX=5` and `attempts=$((attempts+1))`
inside the hostname branch only (numeric in-range and parse-error
branches do not increment). On miss, prints the remaining count;
on cap, dies with a clear "re-run with --node ... or
--probe-nodes" hint.

### Test 5b: live cap (RISKY; uses CSPO budget)

To exercise the live cap, you'd type 5 unreachable hostnames at
the picker. Each ssh_reachable miss costs ONE SSH attempt. The
global SSH lock fires at threshold 3, so this would trigger the
lock partway through. **Skip this live test**; the code review
is sufficient.

If you really want to exercise it without CSPO risk: edit
`SSH_FAIL_LOCK_THRESHOLD` to 100 in a copy of the script,
disconnect from the network, run the picker, type 6 unreachable
hostnames. The 6th attempt should die with the H2 message.
Restore the threshold afterward.

---

## Test 6: H3 — --probe-nodes pre-iteration gate (Batch 3, `5437556`)

Adds an explicit `ssh_attempt_pre` at the top of each iteration
of the `--probe-nodes` for-loop, so once the SSH lock fires, the
loop dies with the proper recovery message instead of silently
marking every remaining node as "unreachable".

### Test 6a: code review (Recommended)

```sh
grep -n -A 25 'H3 fix' argo_anywhere.sh
```

**Pass**: see the `if ! ssh_attempt_pre; then die ...` block at
the top of the for-loop body, BEFORE `ssh_reachable`. The
defensive `_SSH_LOCKED` post-check is retained immediately after.

### Test 6b: live probe (LOW RISK if SSH is healthy)

```sh
bash argo_anywhere.sh --probe-nodes status 2>&1 | head -20
```

**Pass**: probes each node in `ANL_NODES`; reports reachable /
unreachable per node. No SSH lock triggered if your auth is
healthy. (This test exercises the success path; the
lock-during-probe path is hard to exercise without already
being in a CSPO situation.)

---

## Test 7: H5 — proxy reuse identity check (Batch 4, `30915ac`; amended in a later commit, see below)

The on-node `mode_server` reuse path now refuses to attach to a
running argo-proxy unless `cfg_user == want_user` (positive match).
Three explicit refusal branches replace the old single guard.

> **Live-test #1 finding (2026-05-14)**: the initial Batch 4 fix
> used `awk -F'"' '{print $2}'` to extract `cfg_user`, which only
> matches the QUOTED YAML scalar form. PyYAML's `safe_dump` (the
> writer this script uses in the common path) emits PLAIN ASCII
> scalars unquoted, so the parser silently returned empty and the
> "config.yaml is missing or unreadable" branch wrongly fired
> against a perfectly valid config the script itself had verified
> one log line earlier. Amended via a new `yaml_scalar` helper
> (handles plain / double-quoted / single-quoted forms; tested via
> 11-case synthetic harness; same helper now also fixes a
> previously-latent bug in `_client_common_setup`'s
> identity-resolution path that silently degraded to `id -un`). The
> recovery hint was also improved to suggest `kill <pid> && screen
> -X quit` because the live test also demonstrated that argo-proxy
> can survive `screen -X quit` in a detached state. Tests 7a/7b
> below should be re-run against the amended fix.

### Test 7a: code review (Recommended)

```sh
grep -n -A 35 'H5 fix' argo_anywhere.sh
```

**Pass**: see the three refusal branches:
1. `if [ -z "$want_user" ]` — refuse with "ARGO_ANYWHERE_USER
   unset" message.
2. `if [ -z "$cfg_user" ]` — refuse with "config.yaml is missing
   or unreadable" message.
3. `if [ "$cfg_user" != "$want_user" ]` — refuse with the existing
   "configured for user X, not Y" message.
4. (success) `ok "... identity verified (user='${cfg_user}'); reusing."`

The success log now includes the verified user name for the
audit trail.

### Test 7b: synthetic test of branch 2 (config missing) — OPTIONAL

```sh
ssh aattia@compute-01.cels.anl.gov '
  set -e
  mv ~/.config/argoproxy/config.yaml ~/.config/argoproxy/config.yaml.bak
  bash ~/.argo_anywhere.sh server -y 2>&1 | head -20 || true
  mv ~/.config/argoproxy/config.yaml.bak ~/.config/argoproxy/config.yaml
'
```

**Pass**: server mode dies with "config.yaml is missing or
unreadable" message (assuming a healthy argo-proxy is currently
running on the standard port; if not, this test exits earlier).

This test temporarily moves the config file aside; restore is
in the same one-liner. Skip if it makes you nervous about the
remote state.

---

## Test 8: H6 — claudecode default-to-project scope (Batch 4, `30915ac`)

Default scope was changed from global to project on fresh
installs. Old default was a silent correctness bug: OAuth token in
`~/.claude.json` (created later by `claude auth login`) takes
precedence over `ANTHROPIC_AUTH_TOKEN` in settings.json,
neutralizing the proxy config silently.

### Test 8a: usage doc reflects the new default

```sh
bash argo_anywhere.sh -h | grep -A 16 -- '--scope'
```

**Pass**: the `--scope` description now says "If unset, the
script defaults to PROJECT scope (changed in v2.0; was global
on fresh installs)" and explains the OAuth precedence rationale.

### Test 8b: live install in a temp project directory (RISKY: writes config)

This writes a real Claude Code settings file. Do this in a
throwaway directory so you can simply `rm -rf` it after.

```sh
mkdir -p /tmp/argo_anywhere_h6_test
cd /tmp/argo_anywhere_h6_test
bash ~/AHMED_HOME/Software/argo-anywhere/argo_anywhere.sh --cli-tool claudecode client 2>&1 | grep -A 4 "Claude Code scope"
```

**Pass**: see (assuming no `~/.claude.json` exists; if you have a
personal Claude Code account, signal 1 already routed to project
before the H6 fix and you'll see the same path):

```
[argo_anywhere] Claude Code scope: project (auto; default since v2.0).
[argo_anywhere]   Config will land at ./.claude/settings.local.json and only apply when
[argo_anywhere]   'claude' is run from this directory (/tmp/argo_anywhere_h6_test).
[argo_anywhere]   Run with '--scope global' (or set CLAUDECODE_SCOPE=global) to write
...
```

After verifying, Ctrl+C the foregrounded client and clean up:

```sh
cd ~
rm -rf /tmp/argo_anywhere_h6_test
```

### Test 8c: --scope global override still works

```sh
mkdir -p /tmp/argo_anywhere_h6_test_global
cd /tmp/argo_anywhere_h6_test_global
bash ~/AHMED_HOME/Software/argo-anywhere/argo_anywhere.sh --cli-tool claudecode --scope global client 2>&1 | grep "Claude Code scope"
```

**Pass**: prints `Claude Code scope: global (--scope global).`
(Existing global-scope behavior preserved when explicitly
opted into.)

After verifying, Ctrl+C and clean up:

```sh
cd ~
rm -rf /tmp/argo_anywhere_h6_test_global
```

If `~/.claude/settings.json` was modified, restore from the most
recent `.bak.*` backup.

---

## Test 9: H7 — privacy warning (Batch 4, `30915ac`)

After writing the claudecode config, a per-scope privacy warning
explains that the config contains the user's ANL username and
reminds the user to gitignore the file.

### Test 9a: warning prints alongside Test 8b/8c output

In the Test 8b output, scroll down past the "Run: claude" lines
and look for:

```
[warn] Privacy note: ./.claude/settings.local.json now contains your ANL username
[warn]   ('aattia') in env.ANTHROPIC_AUTH_TOKEN. Don't commit it to a
[warn]   public dotfile repo or share it widely.
[argo_anywhere]   (Project scope -- Claude Code's defaults gitignore
[argo_anywhere]    .claude/settings.local.json automatically; verify your repo's
[argo_anywhere]    .gitignore covers it.)
```

In the Test 8c output (global scope), the trailing `(Project
scope ...)` lines are replaced with the global-scope variant
mentioning `~/.claude/settings.json`.

**Pass**: the warning prints with the right path + username; the
trailing per-scope hint matches the chosen scope.

---

## Test 10: H4 — port-range clamp (Batch 5, `33434c9`)

`find_next_free_remote_port` now clamps the effective end to
`start + 199` (max 200 ports per call), so a wide
`ARGO_ANYWHERE_PORT_RANGE` no longer makes the remote loop walk
thousands of ports in one ssh session.

### Test 10a: code review (Recommended)

```sh
grep -n -A 22 'H4 fix' argo_anywhere.sh
```

**Pass**: see `_FREE_PORT_MAX_SCAN=200` and the
`if [ "$end" -gt "$_max_end" ]` clamp + warn.

### Test 10b: synthetic test of the clamp (function-level; no SSH)

```sh
bash -c '
warn() { printf "[warn] %s\n" "$*" >&2; }
_FREE_PORT_MAX_SCAN=200
start=64742
end=70000
_max_end=$((start + _FREE_PORT_MAX_SCAN - 1))
if [ "$end" -gt "$_max_end" ]; then
  warn "find_next_free_remote_port: clamping end ${end} to ${_max_end} (scanning more than ${_FREE_PORT_MAX_SCAN} ports per call is refused)."
  end="$_max_end"
fi
echo "Effective end: ${end}"
'
```

**Pass**:

```
[warn] find_next_free_remote_port: clamping end 70000 to 64941 (scanning more than 200 ports per call is refused).
Effective end: 64941
```

### Test 10c: live wide-range invocation (OPTIONAL; safe — single SSH call)

```sh
ARGO_ANYWHERE_PORT_RANGE=64742-70000 ARGO_ANYWHERE_AUTO_PORT=1 \
  bash argo_anywhere.sh --cli-tool opencode client
```

This is mostly a no-op (the existing tunnel will be reused), but
if any code path triggers `find_next_free_remote_port`, the
clamp warn should appear. Skip if not interesting.

---

## Test 11: H8 — `ssh -O exit -S <sock> placeholder` (Batch 5, `33434c9`)

`ssh_mux_close_all` now uses `-S "$sock" placeholder` instead of
`-o ControlPath="$sock" x`. Avoids the edge case where a stale
socket file caused `ssh -O exit` to fall back to a real
connection attempt against the literal hostname `x`.

### Test 11a: dry-run shows the new syntax

```sh
bash argo_anywhere.sh clean --dry-run -y --local-only 2>&1 | grep -E 'mux socket|ssh -O exit'
```

**Pass**: each mux-socket line is followed by:

```
[argo_anywhere]     [dry-run] would: ssh -O exit -S /Users/.../argo-anywhere-... placeholder
```

The hostname is the literal word `placeholder` (NOT `x`, NOT
`dummy`). The `-S` flag (NOT `-o ControlPath=...`) precedes the
socket path.

### Test 11b: long_help recovery hint matches the new syntax

```sh
bash argo_anywhere.sh help | grep -A 1 'inspect/close sockets manually'
```

**Pass**: the manual recovery hint now reads
`ssh -O exit -S ~/.ssh/sockets/argo-anywhere-<user>-<host>-<port> placeholder`.

### Test 11c: real exit on an idle socket (LOW RISK)

The current laptop has at least one mux socket that's idle (the
`compute-02` socket from prior testing). Closing it should work
cleanly:

```sh
ls -l ~/.ssh/sockets/argo-anywhere-* 2>&1
# Pick one of the IDLE sockets (NOT the one targeting the live
# tunnel's compute node, which is currently compute-01).
sock=~/.ssh/sockets/argo-anywhere-aattia-compute-02.cels.anl.gov-22
ssh -O exit -S "$sock" placeholder 2>&1
ls -l "$sock" 2>&1
```

**Pass**: `ssh -O exit` prints `Exit request sent.` (or similar
benign message) and the socket file is gone (or `ls` reports "No
such file or directory"). Importantly, no actual SSH connection
attempt to a host called `placeholder` was made.

If you don't have an idle socket to test on, skip this test.

---

## Reporting back

For each test, paste either "pass" or the relevant verbatim output.
Especially:

- **Test 2c / 2d**: confirm `verbose:` line on the compute node
  with and without `--verbose-server`.
- **Test 3a / 3b / 3c**: confirm the N1 summary appears for client
  + tunnel and is absent for status.
- **Test 8b / 9a**: paste the "Claude Code scope:" log block + the
  privacy warning. (Skip if you'd rather not write a real
  claudecode config.)
- **Test 11a**: confirm the `placeholder` hostname + `-S` flag
  appear in the dry-run output.

If everything passes, **Phase 2b is COMPLETE** and we proceed to:

1. Phase 2c (~23 medium/low/info audit items), OR
2. Phase 3 (docs: UPGRADING.md, SECURITY.md, LIMITATIONS.md, final
   README/AGENTS/TESTING rewrites for v2.0), OR
3. Tag v2.0.0 (if you're satisfied with the audit coverage and want
   to ship), then move to Phase 4 (aider, cursor, generic CLI tools).

Per PLAN.md the canonical sequence is 2c -> 3 -> tag -> 4. Open
to user override.

---

## What's NOT yet implemented (for reference)

Tracked in `docs/AUDIT_2026-05-12.md`:

- **Phase 2c (MED + LOW + INFO, ~23 items)**: smaller polish items
  (M1-M10, L1-L10, INFO1-3).
- **Phase 3 (docs)**: UPGRADING.md, SECURITY.md, LIMITATIONS.md,
  README "Claude Code scope" section update (queued by H7), final
  AGENTS/TESTING rewrites for v2.0.
- **v2.0.0 tag**: after Phase 2c + Phase 3 land + final live-test.
- **Phase 4**: aider, cursor, generic OpenAI-compatible CLI tools
  (per PLAN.md Section 9).

---

*Created 2026-05-14 by Ahmed Attia (with substantial AI assistance
from Claude per [`CONTRIBUTORS.md`](../CONTRIBUTORS.md)).*
