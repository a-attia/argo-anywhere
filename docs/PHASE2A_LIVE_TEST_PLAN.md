# Phase 2a live-test plan (CSPO hardening + symlink self-defense)

**What's being tested**: the four Phase 2a commits + the supporting
agov*->argov* + legacy-detection commit:

  - `502174b` — agov*→argov* + legacy detection
  - `eb40a6c` — C1 self-integrity check
  - `6834e32` — C4 SSH lock fails-open hardening
  - `e2a2403` — C5 lock TTL + threshold-1 reset + exponential backoff
  - `15f4bca` — C7 reconnect through SSH attempt tracker + burst-cap escalation

**Audit findings addressed**: C1, C4, C5, C7 (plus the related D4-revised
codification). Audit C2/C3/C6 were addressed in Phase 1. Remaining:
9 high-severity items (Phase 2b), 23 medium/low items (Phase 2c).

---

## Pre-test setup (laptop)

```sh
cd ~/AHMED_HOME/Software/argo-opencode
git pull
git log --oneline -7
# Expect 15f4bca at top (or newer if I've pushed more since)

# Confirm fixes are present:
grep -c 'C1 fix\|C4 fix\|C5 fix\|C7 fix\|P1 fix' argo_anywhere.sh
# Expect: at least 8 (multiple comment markers across the fixes)
```

---

## Test 1: regression — basic functionality unchanged

Verify all the Phase 1 functionality still works after Phase 2a changes.

```sh
bash -n argo_anywhere.sh && echo "syntax OK"
bash argo_anywhere.sh -h | head -5
bash argo_anywhere.sh list-tools
bash argo_anywhere.sh status 2>&1 | head -5
```

**Pass**: syntax OK; help shows --cli-tool; list-tools prints registry;
status either succeeds (if tunnel is up) or reports FAIL cleanly.

---

## Test 2: C1 integrity check

### Test 2a: real script passes

```sh
bash argo_anywhere.sh -h | head -1
```

**Pass**: shows `Usage: argo_anywhere.sh ...` (no integrity-check error).

### Test 2b: truncated file caught

```sh
head -c 8000 argo_anywhere.sh > /tmp/test_truncated.sh
bash /tmp/test_truncated.sh 2>&1 | head -8
rm /tmp/test_truncated.sh
```

**Pass**: prints
```
[err ] argo_anywhere.sh: file is suspiciously small (8000 bytes).
[err ]
[err ] The file at "/tmp/test_truncated.sh" is only 8000 bytes; the real
[err ] argo_anywhere.sh is >100KB. Likely causes:
...
```
followed by 3 numbered recovery suggestions; exit code 2.

### Test 2c: fake symlink-as-text NOT caught (documented limitation)

```sh
echo "argo_anywhere.sh" > /tmp/test_broken.sh
bash /tmp/test_broken.sh 2>&1
rm /tmp/test_broken.sh
```

**Expected (DOCUMENTED LIMITATION)**: bash prints `command not found: argo_anywhere.sh`
and exits 127. The integrity check can't fire because bash dies on line
1 before reaching it. This is documented in the comment block + audit doc.
Only Phase 3 documentation can help users in this case.

---

## Test 3: C4 lock persistence

### Test 3a: lock state files exist

```sh
ls -la ~/.config/argo_anywhere/
# Should show: user, node (if cached). May or may not show:
#   ssh-fail-lock         (only when locked)
#   ssh-fail-lock-count   (only after at least one lock event)
```

**Pass**: directory exists, is writable.

### Test 3b: simulated read-only state dir → die hard

```sh
# Make the state dir read-only
chmod 555 ~/.config/argo_anywhere

# Force the lock to fire by feeding 3 bad SSH attempts:
# Use a deliberately wrong username to force auth failures.
ARGO_ANYWHERE_USER=nonexistentuserxyz123 bash argo_anywhere.sh --cli-tool opencode client --node compute-01.cels.anl.gov 2>&1 | tail -20
# This will:
# 1. Attempt SSH to compute-01 as nonexistentuserxyz123 (fails)
# 2. Re-attempt as part of the bootstrap (fails)
# 3. Re-attempt as part of monitor (fails)
# 4. ssh_attempt_fail tries to write the lock file, can't (read-only),
#    prints C4 error message and dies with exit 3.

# Restore state dir
chmod 755 ~/.config/argo_anywhere
```

**Pass**: see error message including "we cannot write the failure lock
file" and "Refusing to continue." Exit code 3.

**NOTE**: this test may take 2-3 SSH attempts before triggering. On a
well-behaved CSPO, even these failed attempts add to your CSPO score.
Do this test ONCE at most. If you don't want to risk it, skip this
test and trust the code review.

### Test 3c: lock file content is parseable

If you triggered the lock in 3b (or any other way):
```sh
cat ~/.config/argo_anywhere/ssh-fail-lock 2>&1
# Should show a single integer (epoch seconds).
cat ~/.config/argo_anywhere/ssh-fail-lock-count 2>&1
# Should show a single integer (lock event count, >= 1).
```

**Pass**: both files contain valid integers.

After testing, manually clear the lock:
```sh
rm ~/.config/argo_anywhere/ssh-fail-lock ~/.config/argo_anywhere/ssh-fail-lock-count
```

---

## Test 4: C5 TTL + exponential backoff (READ-ONLY VERIFICATION)

To avoid risking actual CSPO blocks, verify the math without triggering
real auth failures:

```sh
# Verify the helper function via direct call
bash -c '
SSH_FAIL_LOCK_TTL_BASE=1800
SSH_FAIL_LOCK_TTL_MAX=86400
_ssh_lock_ttl_for_count() {
  local count="${1:-0}" ttl="$SSH_FAIL_LOCK_TTL_BASE"
  local i=0
  while [ "$i" -lt "$count" ] && [ "$ttl" -lt "$SSH_FAIL_LOCK_TTL_MAX" ]; do
    ttl=$((ttl * 2))
    i=$((i + 1))
  done
  [ "$ttl" -gt "$SSH_FAIL_LOCK_TTL_MAX" ] && ttl="$SSH_FAIL_LOCK_TTL_MAX"
  printf "%s\n" "$ttl"
}
echo "Backoff schedule:"
for n in 0 1 2 3 4 5 6 7; do
  ttl=$(_ssh_lock_ttl_for_count $n)
  printf "  Lock event %d: TTL = %d s (%d min)\n" "$n" "$ttl" "$((ttl/60))"
done'
```

**Pass**: prints
```
Backoff schedule:
  Lock event 0: TTL = 1800 s (30 min)
  Lock event 1: TTL = 3600 s (60 min)
  Lock event 2: TTL = 7200 s (120 min)
  Lock event 3: TTL = 14400 s (240 min)
  Lock event 4: TTL = 28800 s (480 min)
  Lock event 5: TTL = 57600 s (960 min)
  Lock event 6: TTL = 86400 s (1440 min)
  Lock event 7: TTL = 86400 s (1440 min)   ← cap kicks in
```

---

## Test 5: C7 reconnect through tracker (LIVE TEST OPTIONAL)

This is hard to exercise without deliberately disrupting your live
tunnel. Two paths:

### Test 5a: Code review only (Recommended; no risk)

```sh
grep -nA 3 'C7 fix' argo_anywhere.sh | head -40
```

**Pass**: see the three C7 fix comments + their accompanying code:
1. `ssh_attempt_pre` gate before reconnect
2. Burst-cap escalation logic
3. ssh_attempt_ok / ssh_attempt_fail accounting

### Test 5b: Live disruption test (skip if the live tunnel is in use)

This deliberately disrupts your live tunnel to exercise the reconnect path.
Only do this if you're not actively using the proxy.

```sh
# Make sure tunnel is up
bash argo_anywhere.sh status | head -3   # should show ALL GREEN

# In a SECOND terminal, start the client and let it sit in the monitor loop:
bash argo_anywhere.sh --cli-tool opencode client
# Wait until it shows the status box and "Foregrounding ..." message.

# In the FIRST terminal, kill the remote argo-proxy:
ssh aattia@compute-01.cels.anl.gov 'screen -S argovproxy -X quit; pkill -u $USER -f argo-proxy'

# Watch the second terminal. Within ~30s, you should see:
#   [warn] Health check failed (1/3).
#   [warn] Health check failed (2/3).
#   [warn] Health check failed (3/3).
#   notify_user message
#   Then the reconnect logic kicks in. Watch for:
#   - "SSH multiplex master is still alive; attempting silent reconnect..."
#   - Either "Reconnected silently..." or
#     "Reconnect installed the SSH forward but /health is silent."
#
# After 3 reconnect-burst events (~30 min in the worst case), see:
#   [warn] Reconnect loop has fired N burst events
#   [warn] ... Giving up automatic reconnect to prevent CSPO IP block.

# Once you're done observing, Ctrl-C the foregrounded client.
# Restart the proxy via the normal flow:
bash argo_anywhere.sh --cli-tool opencode client
```

**Pass**: the reconnect loop runs through `ssh_attempt_pre` (no CSPO
trigger), the burst-cap eventually escalates and the loop gives up
gracefully instead of looping forever.

---

## Test 6: legacy detection (D4-revised)

If you happen to have legacy v1.x state on the compute node:

```sh
ssh aattia@compute-01.cels.anl.gov 'ls -la ~/agovenv ~/.argo_opencode.* 2>&1 | head -5'
```

If anything shows up (legacy venv or files), the next time you run client,
you should see WARN messages about them. After cleanup via `clean`, they'll
be removed.

For our case (clean compute-01), this is N/A.

---

## Reporting back

For each test, paste either "pass" or the relevant output. Especially:

- **Test 3b** if you choose to run it: paste the exit-code output.
- **Test 5b** if you run it: paste the reconnect-loop transcript.
- For any unexpected output, paste verbatim.

If everything passes, Phase 2a is green. We then proceed to Phase 2b
(9 high-severity audit fixes) or Phase 3 (docs), per your preference.

---

## What's NOT yet implemented (for reference)

Tracked in docs/AUDIT_2026-05-12.md:

- **Phase 2b (HIGH severity, 9 items)**: H1-H9. Most are additional
  CSPO trigger paths + correctness in the multi-client setup.
- **Phase 2c (MED + LOW + INFO, ~23 items)**: smaller polish items.
- **Phase 3 (docs)**: UPGRADING.md, SECURITY.md, LIMITATIONS.md, and
  README/AGENTS/TESTING rewrites for v2.0.
- **v2.0.0 tag**: after all phases land + final live-test.
