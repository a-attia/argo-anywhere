# Phase 2c+3 live-test plan (audit cleanup + new docs)

**What's being tested**: the seven Phase 2c+3 commits closing all
in-scope MED + LOW + INFO audit items + landing the v2.0 docs
package:

  - `f1a3d6f` — Batch 1: M2 + L1 + L4 + L5 (env-var typo + mkdir
    error surface + lock-message dedup)
  - `bdc939d` — Batch 2: M3 + L2 + L9 + L7 (port-read cache + awk
    clarity + DNS-lookup cache + macOS brew PATH check)
  - `def0370` — Batch 3: M1 + L3 + I1 + M5 (dead-code removal + TTY
    bell gate + I1+M5 closure tracking)
  - `ff26e85` — Batch 4: I3 (archive prior audit doc with
    provenance note)
  - `59494df` — Batch 5: new docs (`UPGRADING.md`, `SECURITY.md`,
    `LIMITATIONS.md`)
  - `9779089` — Batch 6a: doc rewrites (`docs/TESTING.md` +
    `AGENTS.md` final pass + `PLAN.md` D-015)
  - `874129c` — Batch 6c: full pre-tag README rewrite per
    content-check table

**Audit findings addressed**: M1, M2, M3, M5, L1, L2, L3, L4, L5,
L7, L9, I1, I3 (= 13 in-scope items). Combined with Phase 2a + 2b,
this brings v2.0 to **33 of 43 audit findings closed** (all CRIT,
all HIGH, in-scope MED/LOW/INFO). The remaining 10 findings
(M4, M6-M10, L6, L8, L10, I2) are explicitly scoped to follow-up
phases (Phase 2d defensive-hardening, Phase 4 multi-client port
resolution, Phase 2e cosmetic).

**Scope discipline**: per the user's directive, EVERY commit in
this phase is "no observable behavior change". Every test below is
designed to verify either (a) the cleanup didn't break anything,
or (b) the new docs render correctly + cross-link properly.

**Lessons applied from Phase 2a/2b test plans**:
- No inline `# comment` after a command (zsh syntax error).
- `grep -n -A N <marker>` instead of `sed -n X,Yp` line ranges.
- Code-review-only fallback for any test that would burn CSPO
  budget or require disrupting the live tunnel.

---

## Pre-test setup (laptop)

```sh
cd ~/AHMED_HOME/Software/argo-anywhere
git pull
git log --oneline -10
```

Expect at the top (in this order, most recent first):

```
874129c docs(readme): full pre-tag rewrite for v2.0 (Batch 6c per content-check table)
9779089 docs(phase-3): cross-doc rewrites + add D-015 (scope-keyed exit summaries)
59494df docs(phase-3): add UPGRADING.md + SECURITY.md + LIMITATIONS.md
ff26e85 docs(audit): archive pre-rebuild audit with provenance note (closes I3)
def0370 chore(2c-cleanup): remove dead code in on_anl_compute_node; gate notification bell on TTY; close I1+M5 in audit
bdc939d refactor(2c-cleanup): cache port + DNS lookups; clean up fragile awk; check brew PATH on macOS
f1a3d6f fix(2c-cleanup): correct env-var name in lock recovery + dedup error lines + surface real mkdir error
087dfe2 fix(n1-amend): rewrite Ctrl+C exit summary as scope-keyed (was action-keyed and misleading)
7cad796 fix(p2-amend): always overwrite verbose in argo-proxy config (was setdefault; preserved upgraders' old true)
5ced284 fix(h5-amend): yaml_scalar helper handles unquoted scalars; improve recovery hint
```

Confirm fixes are present:

```sh
grep -cE 'M1 fix|M2 fix|M3 fix|L1 fix|L2 fix|L3 fix|L4|L5|L7 fix|L9 fix|H6 fix|H7 fix|H8 fix|H5 fix|H4 fix|H3 fix|H2 fix|H1 fix|N1|P2 fix|P3 fix' argo_anywhere.sh
```

Expect: 25+ marker comments across all the fixes.

---

## Test 1: regression — basic functionality unchanged

Confirm Phase 2a + Phase 2b + Phase 2c+3 combined did not break the
smoke baseline.

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
  "keeping" decisions; the mux-socket dry-run lines show the
  H8 syntax (`ssh -O exit -S <socket> placeholder`)

---

## Test 2: M2 — env-var name in lock recovery message

The recovery hint printed by `ssh_attempt_pre` (when the lock is
already active) and by `ssh_attempt_fail` (when the lock just
fired) now uses `ARGO_ANYWHERE_USER` (was `ARGO_OPENCODE_USER`
pre-D4 namespace renames).

### Test 2a: code review (Recommended)

```sh
grep -nE '\${ARGO_ANYWHERE_USER:-' argo_anywhere.sh | head -5
```

**Pass**: at least 2 sites print the recovery hint with
`${ARGO_ANYWHERE_USER:-<user>}` (lines around 1077 and 1190).

### Test 2b: synthetic exercise (no live SSH; manipulate lock file)

```sh
mkdir -p ~/.config/argo_anywhere
date +%s > ~/.config/argo_anywhere/ssh-fail-lock
echo 0 > ~/.config/argo_anywhere/ssh-fail-lock-count

bash argo_anywhere.sh status 2>&1 | grep -E "ssh -o ConnectTimeout"

rm -f ~/.config/argo_anywhere/ssh-fail-lock ~/.config/argo_anywhere/ssh-fail-lock-count
```

**Pass**: the ssh-recovery line shows
`ssh -o ConnectTimeout=5 <YOUR-USER>@logins.cels.anl.gov true` with
your actual ANL username (or `<user>` if `ARGO_ANYWHERE_USER` is
unset). NOT `ARGO_OPENCODE_USER`. NOT a literal `<user>` if your
env had `ARGO_OPENCODE_USER` set.

---

## Test 3: M3 — port-read caching in resolve_port

The `read_port_from_opencode_config` call is now hoisted to the top
of `resolve_port` so it's executed at most once per invocation.

### Test 3a: code review (Recommended)

```sh
grep -n -A 18 'M3 fix' argo_anywhere.sh
```

**Pass**: see `PORT_FROM_CONFIG="$(read_port_from_opencode_config || true)"`
hoisted to the TOP of `resolve_port` (line 877+), with the M3 fix
comment explaining why.

### Test 3b: synthetic count (verify single jq invocation)

```sh
bash -x argo_anywhere.sh status 2>&1 | grep -cE "jq -r '.provider.argo.options.baseURL'"
```

**Pass**: ≤ 2 (one for `resolve_port`, possibly one for status's
own model-count math; pre-fix would have been ≥ 3 because
`resolve_port` itself called it twice).

---

## Test 4: L1 — surface real mkdir error in resolve_username

The `mkdir -p ... 2>/dev/null || die "..."` pattern in
`resolve_username` now captures stderr and surfaces it.

### Test 4a: code review (Recommended)

```sh
grep -n -A 8 'L1 fix' argo_anywhere.sh
```

**Pass**: see `_mk_err="$(mkdir -p "$STATE_DIR" 2>&1)"` capture
followed by `|| die "Cannot create state dir '$STATE_DIR':
${_mk_err}. ..."` interpolation.

### Test 4b: synthetic exercise (force mkdir failure)

```sh
mkdir -p /tmp/argo_l1_test && chmod 555 /tmp/argo_l1_test

ARGO_ANYWHERE_STATE_DIR=/tmp/argo_l1_test/inner bash -c '
  source /dev/stdin <<EOF
  $(sed -n "/^resolve_username() {/,/^}/p" argo_anywhere.sh)
EOF
  STATE_DIR=/tmp/argo_l1_test/inner USER_CACHE=/tmp/argo_l1_test/inner/user
  err()  { printf "[err ] %s\n" "$*" >&2; }
  die()  { err "$*"; exit 2; }
  log()  { :; }
  ask()  { printf "%s" "testuser"; }
  resolve_username 2>&1 | tail -3
'

rm -rf /tmp/argo_l1_test
```

**Pass**: the die message shows the actual `mkdir: cannot create
directory '...': Permission denied` text (or your platform's
equivalent), NOT the generic "permission denied? \$HOME read-only?"
guess.

This test sources the function out of the script for isolation;
it's brittle but exercises the L1 fix correctness directly.

---

## Test 5: L4 + L5 — single block of recovery instructions on lock

Pre-fix the recovery instructions printed twice when the lock was
already active (once by `ssh_attempt_pre`, once by the caller's
"See above for recovery instructions" `die`). Now the recovery
block prints once + a one-liner mode descriptor.

### Test 5a: code review (Recommended)

```sh
grep -n 'See above for recovery' argo_anywhere.sh
```

**Pass**: exactly ONE match (line 2670, in the
`monitor_tunnel_loop` warn — and that one was deduped to a single
warn line referencing "recovery above"). The five `die` sites that
used to print "See above for recovery instructions" now print
shorter "Aborted: <mode> (SSH failure lock active; recovery
above)." messages.

### Test 5b: synthetic lock-fired output (verify single recovery block)

Use the same lock-file manipulation as Test 2b:

```sh
mkdir -p ~/.config/argo_anywhere
date +%s > ~/.config/argo_anywhere/ssh-fail-lock
echo 0 > ~/.config/argo_anywhere/ssh-fail-lock-count

bash argo_anywhere.sh tunnel 2>&1 | head -25

rm -f ~/.config/argo_anywhere/ssh-fail-lock ~/.config/argo_anywhere/ssh-fail-lock-count
```

**Pass**: see ONE block of recovery instructions (printed by
`ssh_attempt_pre`), then ONE line of `die "Aborted: ... (SSH
failure lock active; recovery above)."` from one of the callers
(`ssh_mux_open` or `ssh_preflight`). NOT two separate recovery
blocks.

The exact die message depends on which call site fires first;
both `Aborted: open SSH master ...` and `Aborted: SSH preflight
...` are valid.

---

## Test 6: L7 — macOS brew PATH check (code-review only)

Pre-fix the `ensure_opencode_installed` PATH fallback only checked
`~/.opencode/bin/opencode`. Now it checks the two brew prefixes
first, then the upstream curl|bash location.

### Test 6a: code review (Recommended)

```sh
grep -n -A 14 'L7 fix' argo_anywhere.sh
```

**Pass**: see the for-loop iterating
`/opt/homebrew/bin/opencode`, `/usr/local/bin/opencode`,
`${HOME}/.opencode/bin/opencode` in order. The post-failure error
message also enumerates all three.

### Test 6b: live exercise (skip; would require uninstalling opencode)

To live-exercise this, you would need to:
1. Uninstall opencode from your laptop.
2. Run `bash argo_anywhere.sh --cli-tool opencode client`.
3. Watch the install path; verify the post-install PATH-fallback
   check finds the binary at whichever location it landed.

This is too disruptive for routine live verification. The code
review is sufficient.

---

## Test 7: L9 — host_is_target memoization (code-review only)

Pre-fix `host_is_target` did 2 DNS lookups per call (one for `me`,
one for `target`). With 10 ANL_NODES and the on-node-detected
branch, that's 20 lookups in `pick_node`. Now `me` and `my_ips`
are cached at file-global scope.

### Test 7a: code review (Recommended)

```sh
grep -n -A 12 'L9 fix' argo_anywhere.sh
```

**Pass**: see `_HOST_IS_TARGET_ME`, `_HOST_IS_TARGET_ME_IP`,
`_HOST_IS_TARGET_MY_IPS`, `_HOST_IS_TARGET_CACHE_INIT`, and
`_host_is_target_init_cache()` declared. The body of
`host_is_target` now calls `_host_is_target_init_cache` first and
uses the cached values.

### Test 7b: synthetic count (verify cache prevents repeat lookups)

```sh
bash -c '
source <(sed -n "/^_my_interface_ips()/,/^}/p; /^this_host_fqdn()/,/^}/p; /^_host_is_target_init_cache()/,/^}/p; /^host_is_target()/,/^}/p" argo_anywhere.sh)
_HOST_IS_TARGET_CACHE_INIT=0
_HOST_IS_TARGET_ME=""
_HOST_IS_TARGET_ME_IP=""
_HOST_IS_TARGET_MY_IPS=""
# First call should populate the cache
host_is_target compute-01.cels.anl.gov 2>&1 >/dev/null
echo "After first call: ME=$_HOST_IS_TARGET_ME (cache_init=$_HOST_IS_TARGET_CACHE_INIT)"
# Subsequent calls reuse it
host_is_target compute-02.cels.anl.gov 2>&1 >/dev/null
echo "After second call: ME=$_HOST_IS_TARGET_ME (cache still init=$_HOST_IS_TARGET_CACHE_INIT)"
'
```

**Pass**: `cache_init=1` after the first call AND remains 1 after
the second — confirms the memoization is sticky.

---

## Test 8: M1 — on_anl_compute_node simplified (code-review only)

The dead loop iterating `ANL_NODES` doing string comparison against
`hostname -f` was removed. Only the `*.cels.anl.gov` suffix match
remains.

### Test 8a: code review (Recommended)

```sh
grep -n -B 2 -A 15 '^on_anl_compute_node()' argo_anywhere.sh
```

**Pass**: function body has only the suffix match (case-statement
on `*.cels.anl.gov`); no `for n in "${ANL_NODES[@]:-}"` loop. The
M1 fix comment block above the function explains the
known-and-accepted limitation (if CELS moves nodes to a different
domain, the function returns "no" until updated).

---

## Test 9: L3 — TTY-gated notification bell (code-review only)

`notify_user`'s `printf '\a'` is now wrapped in a `[ -t 2 ]` guard
so the BEL character isn't embedded in log files captured via
redirection.

### Test 9a: code review (Recommended)

```sh
grep -n -A 12 '^notify_user' argo_anywhere.sh
```

**Pass**: see `if [ -t 2 ]; then printf '\a' >&2; fi` near the top
of the function body (with the L3 fix comment explaining the
gate).

---

## Test 10: I3 — prior audit doc archived

The pre-rebuild audit doc was renamed `docs/AUDIT_2026-05.md` ->
`docs/AUDIT_2026-05_pre-rebuild.md` and got a top-of-file
provenance note.

### Test 10a: rename verifiable in git

```sh
git log --diff-filter=R --name-status -- docs/AUDIT_2026-05.md docs/AUDIT_2026-05_pre-rebuild.md | head -10
```

**Pass**: shows a rename (R nnn) entry with the old + new names.

### Test 10b: provenance note present

```sh
head -25 docs/AUDIT_2026-05_pre-rebuild.md
```

**Pass**: see the `> **HISTORICAL ARCHIVE (filed 2026-05-15 per
audit finding I3)**.` callout block at the top, followed by the
explanation of (a) it's an archive, (b) the current
audit-of-record, (c) line/symbol references reflect pre-v2.0
codebase, (d) cross-check section in the new audit.

### Test 10c: cross-references updated

```sh
grep -nE 'AUDIT_2026-05(\.md|_pre-rebuild)' README.md PLAN.md AGENTS.md docs/AUDIT_2026-05-12.md | head -10
```

**Pass**:
- `README.md` does NOT reference `AUDIT_2026-05.md` (only
  references `AUDIT_2026-05-12.md`; the archived doc is
  maintainer-only and not in README's scope).
- `PLAN.md` references `AUDIT_2026-05_pre-rebuild.md` (the
  Engineering practice + Maintenance sections).
- `AGENTS.md` references `AUDIT_2026-05_pre-rebuild.md` (the
  human-facing doc map).
- `docs/AUDIT_2026-05-12.md` references `AUDIT_2026-05_pre-rebuild.md`
  in the "Cross-check" section header.

The two remaining `AUDIT_2026-05.md` mentions in
`docs/AUDIT_2026-05-12.md` are inside the I3 finding entry itself
(the heading + the closure block describing the rename) -- both
intentional historical references, not pointers.

---

## Test 11: new docs render + cross-link correctly

The three new docs (`UPGRADING.md`, `SECURITY.md`, `LIMITATIONS.md`)
exist + are cross-linked from README + each other.

### Test 11a: files exist + non-empty

```sh
wc -l docs/UPGRADING.md docs/SECURITY.md docs/LIMITATIONS.md
```

**Pass**: each file is at least 250 lines (substantial content).
Expected: ~302 / 266 / 314.

### Test 11b: no stale placeholders

```sh
grep -nE 'TODO|INSERT|<your-fork>|PLACEHOLDER' docs/UPGRADING.md docs/SECURITY.md docs/LIMITATIONS.md README.md docs/TESTING.md AGENTS.md PLAN.md
```

**Pass**: no matches (all documents are publishable as-is; no
left-over `<TODO>` / `<INSERT>` markers from drafting).

### Test 11c: no personal paths leaked

```sh
grep -nE '/Users/attia|<projects-parent-dir>' docs/UPGRADING.md docs/SECURITY.md docs/LIMITATIONS.md README.md docs/TESTING.md
```

**Pass**: no matches.

### Test 11d: cross-references resolve

```sh
for f in README.md docs/UPGRADING.md docs/SECURITY.md docs/LIMITATIONS.md docs/TESTING.md AGENTS.md PLAN.md; do
  echo "--- $f ---"
  grep -oE '\([^)]+\.md[^)]*\)' "$f" | sort -u
done
```

**Pass**: every referenced `.md` file exists in the repo. (You can
visually scan the output; or pipe through a Python one-liner if
you want it automated.)

---

## Test 12: AGENTS.md updated for v2.0 ready-to-tag

### Test 12a: status field

```sh
grep -A 1 '^- \*\*Status\*\*' AGENTS.md
```

**Pass**: shows `v2.0 ready-to-tag (Phase 2c+3 complete; awaiting
final live-test gate then v2.0.0 tag)`.

### Test 12b: doc-map subsection present

```sh
grep -A 12 '^### Human-facing doc map' AGENTS.md | head -15
```

**Pass**: shows a Markdown table with at least 8 rows
(README, PLAN, UPGRADING, SECURITY, LIMITATIONS, TESTING, AUDIT
2026-05-12, AUDIT pre-rebuild, CONTRIBUTORS, agent_feedback,
test_plans).

---

## Test 13: PLAN.md D-015 added

```sh
grep -A 5 '^### D-015' PLAN.md | head -8
```

**Pass**: shows the D-015 entry titled "Scope-keyed (not
action-keyed) exit summaries and error messages" with status
"accepted; codified in code by the N1 amendment commit (`087dfe2`)".

---

## Test 14: README.md full pre-tag rewrite

### Test 14a: Status section is concise

```sh
grep -A 10 '^## Status' README.md
```

**Pass**: 5-line condensed Status statement (NOT the per-phase
recap from pre-rewrite). Includes "v2.0 is ready-to-tag" + cross-link
to `PLAN.md` Section 4 + cross-link to `docs/AUDIT_2026-05-12.md`.

### Test 14b: Claude Code scope reflects H6 default

```sh
grep -A 30 '^## Claude Code config scope' README.md | head -40
```

**Pass**: numbered decision tree shows project as the default
("None of the above → project scope (changed in v2.0; was global
pre-v2.0)") with the OAuth-precedence rationale + the must-NOT
warning for `--scope global` + cross-link to SECURITY.md.

### Test 14c: Where to read more section

```sh
grep -A 12 '^## Where to read more' README.md
```

**Pass**: shows a 7-row table cross-linking
UPGRADING / SECURITY / LIMITATIONS / TESTING / AUDIT / PLAN / AGENTS.

### Test 14d: Upgrading section shrunk to a pointer

```sh
sed -n '/^## Upgrading from/,/^## Testing/p' README.md | wc -l
```

**Pass**: ≤ 25 lines (was ~36 lines pre-rewrite). Body now
cross-links to `docs/UPGRADING.md` for the full migration.

---

## Reporting back

For each test, paste either "pass" or the relevant verbatim output.
Especially:

- **Test 4b**: paste the actual error message captured by L1's
  stderr surface.
- **Test 5b**: confirm exactly ONE recovery block + ONE die line
  (NOT two recovery blocks).
- **Test 11d**: confirm all `.md` cross-references resolve.

If everything passes, **Phase 2c+3 is COMPLETE** and the next step
is to **tag v2.0.0**:

```sh
git tag -a v2.0.0 -m "v2.0.0 -- multi-tool refactor + 33-of-43 audit findings closed.

See docs/AUDIT_2026-05-12.md for the full audit trail with per-finding
STATUS resolutions. See docs/UPGRADING.md for v1.x -> v2.0 migration."
git push origin v2.0.0
```

(The exact tag message can be refined; this is a reasonable starting
template.)

---

## What's NOT yet implemented (queued for follow-up phases)

Tracked in `docs/AUDIT_2026-05-12.md`:

- **Phase 2d defensive-hardening** (M6, M7, M8, M9, M10, L6, L10):
  7 items that change observable behavior in the "fail louder, not
  silently" direction. Will get its own live-test gate.
- **Phase 2e cosmetic** (I2): rename `_LOGGING` env var to
  something less overloaded. Pure cosmetic; one commit.
- **Phase 4** (M4 + new tools): multi-client port resolution
  generalization + aider/cursor/generic OpenAI-compatible CLI
  tools.

---

*Created 2026-05-15 by Ahmed Attia (with substantial AI assistance
from Claude per [`CONTRIBUTORS.md`](../CONTRIBUTORS.md)).*
