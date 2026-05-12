# Phase 1 live-test plan (v2.0 rename + --cli-tool + legacy detection)

**What's being tested**: the four Phase 1 commits (`d794a97`, `72e2851`,
`bd897a7`, `efdf9ac`) on `origin/main`.

**Scope**: D1 (no symlinks), D2 (--cli-tool flag + list-tools subcommand),
D4 (Group 1 internal rename + back-compat shims + legacy state detection).

**Audit fixes from this phase**: C2, C3, H9 (per docs/AUDIT_2026-05-12.md).

**NOT yet implemented** (later phases):
- D3 UPGRADING.md / SECURITY.md / LIMITATIONS.md (Phase 3)
- Audit critical fixes C1 (symlink self-defense), C4-C7 (CSPO
  hardening), C6 (mode_server reuse race), etc. (Phase 2)
- README/AGENTS/TESTING text rewrites (Phase 3)

So during this test you may see references in docs that don't match
what the script actually does yet -- that's expected.

---

## Setup (laptop)

```sh
cd ~/AHMED_HOME/Software/argo-opencode  # or wherever you have it
git pull
git log --oneline -6   # should show efdf9ac at top
```

Or fresh clone for cold-test:
```sh
cd /tmp
git clone https://github.com/a-attia/argo-opencode argo-anywhere-test
cd argo-anywhere-test
ls -la argo_*.sh   # should show ONLY argo_anywhere.sh (no symlinks)
```

---

## Test 1: file structure

**Expectation**: only `argo_anywhere.sh` in the repo; no symlinks.

```sh
ls -la argo_*.sh
```

**Pass**: exactly one file, `argo_anywhere.sh`, mode `-rwxr-xr-x` (regular
executable).

**Fail**: any other `argo_*.sh` files present, or `argo_anywhere.sh` is
mode `lrwxr-xr-x` (symlink).

---

## Test 2: syntax + help

```sh
bash -n argo_anywhere.sh && echo "syntax OK"
bash argo_anywhere.sh -h | head -10
```

**Pass**:
- `syntax OK`
- usage line mentions `--cli-tool NAME`
- subcommand list includes `client`, `setup`, `list-tools`, `tunnel`, etc.

---

## Test 3: list-tools

```sh
bash argo_anywhere.sh list-tools
```

**Pass**: prints exactly:
```
Supported AI CLI tools (pass to --cli-tool):
  opencode      OpenCode (sst/opencode-style)
  claudecode    Claude Code (Anthropic CLI; uses ANTHROPIC_BASE_URL env)
```

---

## Test 4: legacy state detection (laptop)

This test verifies that the script REFUSES to run if v1.x state is
detected and prints exact cleanup commands.

### Test 4a: detection trips on legacy state-dir

```sh
# Setup: simulate a v1.x install
mkdir -p ~/.config/argo_opencode
echo "$USER" > ~/.config/argo_opencode/user
echo "compute-01.cels.anl.gov" > ~/.config/argo_opencode/node

# Trigger detection
bash argo_anywhere.sh status 2>&1 | head -30
```

**Pass**: see a yellow-highlighted "LEGACY v1.x STATE DETECTED" banner
listing `~/.config/argo_opencode  (cached username/node from v1.x)`,
followed by exact `mv` and `rm` commands. Script exits non-zero.

### Test 4b: cleanup works as instructed

Run the printed commands literally:
```sh
mv ~/.config/argo_opencode ~/.config/argo_anywhere
rm -f ~/.ssh/sockets/argo-opencode-*   # may be no-op if no legacy sockets

# Now retry:
bash argo_anywhere.sh status 2>&1 | head -10
```

**Pass**: no legacy banner; status proceeds (will probably FAIL the
proxy check unless your tunnel is up — that's fine, we're testing the
detection, not the proxy).

### Test 4c: legacy env-var triggers detection

```sh
# Reset legacy state again to test env-var detection alone
ls ~/.config/argo_opencode 2>&1   # should not exist now

# Set a legacy env var:
ARGO_OPENCODE_USER=$USER bash argo_anywhere.sh status 2>&1 | head -20
```

**Pass**: detection trips with `env vars: ARGO_OPENCODE_USER  (still
honored, but rename to ARGO_ANYWHERE_*)` in the legacy items list.

### Test 4d: help and list-tools bypass detection

Even with legacy state present:
```sh
mkdir -p ~/.config/argo_opencode  # restore legacy
bash argo_anywhere.sh -h | head -3
bash argo_anywhere.sh help | head -3
bash argo_anywhere.sh list-tools

# Cleanup
rmdir ~/.config/argo_opencode
```

**Pass**: `-h` shows usage; `help` shows long guide; `list-tools` shows
the registry. None of them trip the legacy detection.

---

## Test 5: env-var promotion

```sh
# Confirm the legacy state is gone
[ -d ~/.config/argo_opencode ] && echo "FAIL: still has legacy" || echo "OK: legacy gone"

# Set a v1.x env var:
ARGO_OPENCODE_USER=$USER bash argo_anywhere.sh status 2>&1 | head -3
```

**Pass**: see `[warn] env var 'ARGO_OPENCODE_USER' is deprecated; use
'ARGO_ANYWHERE_USER' instead (still honored for now)`. Then status
proceeds normally. (Note: this is the SECOND legacy detection trip —
because env-var-only triggers the gate. To fully bypass the gate while
testing the WARN, use `unset ARGO_OPENCODE_USER` then re-run.)

Actually — here's the subtle UX issue: legacy-detection BLOCKS, but
ALSO surfaces the env var. If you want to see the env-var promotion
WITHOUT the block, you have to run a subcommand that bypasses (like
list-tools). But list-tools doesn't read env vars meaningfully. So
the cleanest test:

```sh
# Promote the env var; verify the WARN fires; the block is also expected:
ARGO_OPENCODE_PORT=64999 bash argo_anywhere.sh status 2>&1 | head -3
```

**Pass**: WARN line appears: `env var 'ARGO_OPENCODE_PORT' is deprecated;
use 'ARGO_ANYWHERE_PORT' instead (still honored for now)`. Then the
legacy-detection block fires (also expected).

---

## Test 6: --cli-tool flag

### Test 6a: unknown value rejected

```sh
bash argo_anywhere.sh --cli-tool bogus client 2>&1 | head -3
```

**Pass**: dies with `--cli-tool: unknown tool 'bogus'. Known tools:
opencode, claudecode.`

### Test 6b: valid value accepted; preflight runs

```sh
bash argo_anywhere.sh --cli-tool opencode client --user nobody --node bogus.example 2>&1 | head -10
```

**Pass**: proceeds to preflight (you'll see "Using ANL username: nobody",
"Using port: ...", etc.) and then fails at `Verifying reachability of
'bogus.example'` (because bogus.example is unreachable). The point is
that --cli-tool was accepted and the picker was skipped.

### Test 6c: warn-but-proceed on irrelevant subcommands

```sh
bash argo_anywhere.sh --cli-tool opencode status 2>&1 | head -5
```

**Pass**: see `[warn] --cli-tool ignored for subcommand 'status' (only
used by client/setup/update-models).` Then status runs normally.

### Test 6d: picker fires when --cli-tool is omitted

```sh
printf '\n' | bash argo_anywhere.sh client 2>&1 | head -10
```

**Pass**: see "Supported AI CLI tools:" menu, "Pick a tool [1-2, ...]:"
prompt. Empty input aborts with "No CLI tool picked; aborting. Pass
--cli-tool <name> or pick from the menu."

### Test 6e: setup forces picker even with --cli-tool

```sh
printf '\n' | bash argo_anywhere.sh --cli-tool opencode setup 2>&1 | head -10
```

**Pass**: picker fires (same as 6d) even though --cli-tool was set.

---

## Test 7: end-to-end client run (laptop, with live tunnel)

This requires a live tunnel to a compute node.

### Test 7a: clean slate prep

If a tunnel is up from a previous run:
```sh
# Tear down any existing tunnel + its mux socket
bash argo_anywhere.sh stop 2>&1 || true
ls ~/.ssh/sockets/argo-anywhere-* 2>&1
ls ~/.ssh/sockets/argo-opencode-* 2>&1
# Close any sockets that remain:
ls ~/.ssh/sockets/argo-anywhere-* 2>/dev/null | xargs -I{} ssh -O exit -S {} dummy 2>/dev/null
rm -f ~/.ssh/sockets/argo-opencode-* 2>/dev/null
```

### Test 7b: real client run

```sh
bash argo_anywhere.sh --cli-tool opencode client
```

This will:
1. Trigger the Duo prompt (one time)
2. Pick the cached node OR show the picker if no cache
3. Bootstrap argo-proxy on the node
4. Open the tunnel
5. Configure OpenCode
6. Show the status box (ALL GREEN)
7. Block in the foreground monitor loop

**Pass**:
- Log prefix throughout is `[argo_anywhere]`
- Status box title says `argo_anywhere -- status summary`
- `Script state dir : /Users/USER/.config/argo_anywhere`
- `Remote bootstrap : USER@compute-XX.cels.anl.gov:~/.argo_anywhere.server.log`
- `OpenCode config : /Users/USER/.config/opencode/config.json` (unchanged)
- ALL GREEN verdict
- Suggests `Run: opencode` (or similar)

Ctrl-C to exit when done.

---

## Test 8: on-node tests (compute-386-01)

These test the script when run directly on a compute node (the on-node
short-circuit path that hit Bug 2 in the previous round).

### Setup on compute node

```sh
ssh aattia@compute-386-01

# Clean up any v1.x state on the node:
rm -f ~/.argo_opencode.sh
rm -f ~/.argo_opencode.server.log
# Don't touch the venv (~/agovenv) -- that's by design (D4 keeps it)
# Don't touch the screen session (agovproxy) -- same

# Get the new script:
curl -fsSL https://raw.githubusercontent.com/a-attia/argo-opencode/main/argo_anywhere.sh \
     -o argo_anywhere.sh
ls -la argo_anywhere.sh   # should be a regular file, ~250KB
head -3 argo_anywhere.sh   # should start with "#!/usr/bin/env bash" and "# argo_anywhere.sh"
```

### Test 8a: on-node syntax + help

```sh
bash -n argo_anywhere.sh && echo "syntax OK"
bash argo_anywhere.sh list-tools
```

**Pass**: syntax OK; list-tools prints registry.

### Test 8b: on-node legacy detection

If you have a v1.x state dir on the node:
```sh
ls ~/.config/argo_opencode/ 2>&1
```

If it exists:
```sh
bash argo_anywhere.sh status 2>&1 | head -20
```

**Pass**: legacy banner fires with on-node paths.

After cleanup:
```sh
mv ~/.config/argo_opencode ~/.config/argo_anywhere   # if it existed
bash argo_anywhere.sh status 2>&1 | head -10
```

**Pass**: no banner. Status proceeds (may FAIL if no proxy running on
node, that's expected).

### Test 8c: on-node `client` (the path that hit Bug 2 last time)

```sh
bash argo_anywhere.sh --cli-tool opencode client
```

When the node picker shows, type `1` (or whichever is your physical
node's alias). The script should:
1. Detect on-node + same-host
2. Run mode_server in-process (the body should now run to completion)
3. Print `[ ok ] argo-proxy is listening on 127.0.0.1:64742.`
4. Print `[ ok ] argo-proxy is live at http://localhost:64742/v1`
5. Configure OpenCode
6. Print the status box (ALL GREEN)

**Pass**: see EVERY line above. Script finishes (does NOT silently exit
back to shell with proxy not running, like Bug 2).

**Fail**: if the script silently returns to shell after `[ ok ]
argo-proxy config already up to date` without showing the listener line
or status box, that's Bug 2 still alive. Capture the exact transcript
and report.

Note: Bug 2 (audit C6) was NOT explicitly fixed in Phase 1 — it's
slated for Phase 2a (critical fixes). It MIGHT be fixed incidentally by
the rename + state-detection changes, or it might still be there. Test
8c is important to know which.

### Test 8d: on-node status + stop

```sh
bash argo_anywhere.sh status 2>&1 | head -10
# Should show ALL GREEN if 8c worked

bash argo_anywhere.sh stop 2>&1 | head -10
# Should ask for confirmation (it kills argo-proxy on the local node)
# Pick yes; verify proxy is down
bash argo_anywhere.sh status 2>&1 | head -10
# Should show FAIL now
```

---

## Test 9: clean (laptop)

```sh
# Make sure the live tunnel is up (re-run client if needed)
bash argo_anywhere.sh status 2>&1 | grep -i "ALL GREEN"

# Dry-run clean:
bash argo_anywhere.sh clean --dry-run
```

**Pass**: prints a plan that includes:
- Local items (state dir, tunnel pid, mux sockets)
- Remote items (`~/.argo_anywhere.sh`, `~/.argo_anywhere.server.log`,
  `~/.argo_opencode.sh` and `~/.argo_opencode.server.log` — both old
  and new are listed for cleanup)
- Risky files (OpenCode config, argo-proxy YAML — kept by default)

Don't run the actual clean unless you're done with the live-test.

---

## Reporting

For each test, paste the relevant output (or just say "pass") in your
reply. Specifically:

- **Test 8c** is the most important; please paste the FULL transcript
  of the on-node `client` run including any error messages.
- **Test 4** (legacy detection) is the second most important; confirm
  the printed `mv` and `rm` commands match what you actually need to
  run on your specific machine.
- For tests that pass with no surprises, just say "pass".
- For ANY unexpected behavior (warnings you didn't expect, missing
  log lines, silent exits, hangs), capture and paste verbatim.

If something fails, we fix it before Phase 2 starts.

---

## Known issues NOT addressed in Phase 1

These are tracked in `docs/AUDIT_2026-05-12.md` and slated for Phase 2:
- C1: scp-of-symlink failure on compute nodes (audit symlink self-defense)
- C4: SSH lock fails-open if state dir creation fails
- C5: 5-min lock TTL too generous for CSPO defense
- C6: mode_server's silent reuse-existing-proxy return (likely Bug 2 root cause)
- C7: reconnect loop bypasses SSH attempt tracker
- H1-H9: additional CSPO triggers + correctness
- M1-M10, L1-L10: medium and low severity items

If you see any of these surfacing in test, that's expected — they're
on the Phase 2 list.
