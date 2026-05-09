# argo_opencode.sh — live verification guide

Goal of this session: replace the legacy tunnel (currently pid `19818` on
port `64742`, established by `start_argo_tunnel.sh` against `compute-01`)
with a fresh tunnel built by the patched `argo_opencode.sh`. Use the same
port and node so OpenCode keeps working without any local config changes.

This exercises the four code paths we patched but couldn't verify live in
the previous session:

- **B2** — silent reconnect uses local `$user`, not the global
- **B14** — `mode_server` no longer runs the bootstrap twice
- **B15** — mux socket path uses `%r-%h-%p` (literal) instead of `%C` (hash)
- **B13** — argo-proxy YAML config writer preserves unknown keys

Reading time: ~5 min. Run time: ~5–10 min including one Duo prompt.

---

## Conventions in this guide

- All commands are meant for your **laptop terminal** unless prefixed with
  `# (on compute-01):`. Lines starting with `#` are comments.
- "**Pass**" and "**Fail**" describe what to look for. If a step fails,
  read the **If it fails** section right under it before doing anything else.
- The `argo_opencode.sh` you're running is the one in the current working
  directory (`/Users/attia/AHMED_HOME/Software/Custom_Scripts/argo_opencode.sh`).
  It is *not* uploaded to web.cels.anl.gov yet, so don't `curl` the hosted copy.

---

## Step 0 — pre-flight sanity (30s)

```sh
cd /Users/attia/AHMED_HOME/Software/Custom_Scripts

# Script syntax + basic invocation still work?
bash -n argo_opencode.sh && echo "syntax OK"
bash argo_opencode.sh -h >/dev/null 2>&1 && echo "usage OK"

# Confirm the legacy tunnel is still up on 64742
lsof -nPi :64742 -sTCP:LISTEN
```

**Pass:** `syntax OK`, `usage OK`, and lsof shows one ssh process on `127.0.0.1:64742`.

**Fail:** if syntax breaks, stop and resume the conversation with me — something happened to the file. If 64742 is empty, your OpenCode session has already lost its tunnel; you can still proceed (this guide rebuilds it), but flag it when we resume.

---

## Step 1 — capture the current state for diffing later (1 min)

We want to verify **B13** by comparing the remote argo-proxy config
before and after the test. Take a snapshot now.

```sh
# Snapshot the laptop OpenCode config (we'll see if [b]ackup gets invoked)
cp -p ~/.config/opencode/config.json /tmp/opencode_config_BEFORE.json

# Snapshot the remote argo-proxy config on compute-01 (B13 target)
ssh -J aattia@logins.cels.anl.gov aattia@compute-01.cels.anl.gov \
  'cat ~/.config/argoproxy/config.yaml' > /tmp/argoproxy_config_BEFORE.yaml

ls -la /tmp/opencode_config_BEFORE.json /tmp/argoproxy_config_BEFORE.yaml
echo "--- remote argoproxy config (BEFORE) ---"
cat /tmp/argoproxy_config_BEFORE.yaml
```

This Duo prompt may or may not fire depending on whether you have a warm
master to compute-01 (after our cleanup yesterday, you almost certainly
don't, so expect Duo).

**Pass:** both snapshot files exist and are non-empty. The remote argoproxy
config has `port: 64742` and probably the legacy keys (`argo_url`,
`argo_embedding_url`, etc.). Note whether the file uses **prod** URLs
(`apps.inside.anl.gov`) or **dev** URLs (`apps-dev.inside.anl.gov`). We'll
check this is preserved later.

**If it fails:** if the remote `cat` returns nothing, the legacy
config was already wiped at some point. Not catastrophic — B13 has nothing
to preserve, so the test still works, but you can't verify B13's
preserve-unknown-keys behavior. Press on.

---

## Step 2 — kill the legacy tunnel (5s)

This will sever your active OpenCode session. **Close any running OpenCode
windows first**, otherwise OpenCode may print errors as the tunnel dies.

```sh
# Confirm what's there
lsof -nPi :64742 -sTCP:LISTEN

# Kill it
bash argo_opencode.sh stop
sleep 1
lsof -nPi :64742 -sTCP:LISTEN || echo "64742 free"
```

**Pass:** `[ ok ] Killed: <pid>` followed by `64742 free`.

**Fail:** if `mode_stop` reports "Nothing to stop locally" but lsof still
shows a listener, manually kill: `lsof -nPi :64742 -sTCP:LISTEN -t | xargs kill -9`.

---

## Step 3 — run the patched client (3–5 min, 1 Duo prompt)

This is the main test. Run interactively and answer prompts as below.

```sh
bash argo_opencode.sh client
```

You should see, in order:

### 3a — Username + port resolution

```
[argo_opencode] Using ANL username: aattia
[argo_opencode] Using port: 64742  (source: opencode config baseURL)
```

**Pass:** username is `aattia` (cached), port is `64742`, source is
`opencode config baseURL` (because no `--port` override).

**No port-mismatch prompt fires** (port resolved from the config matches the
config — by definition no mismatch).

### 3b — node selection

The cached node from yesterday's tests is `compute-02`. We want
`compute-01` for this test (matches the legacy state).

You'll see the picker:

```
  Compute nodes:
    1) compute-01.cels.anl.gov
    2) compute-02.cels.anl.gov   (default)   <-- WRONG default for this test
    3) compute-03.cels.anl.gov
    (reachability NOT probed; pass --probe-nodes to test each first)

  Pick a node [1-3, Enter = default]: 1
```

**Type `1` and Enter.** Do NOT take the default — we want compute-01.

**Pass:** `[argo_opencode] Selected node: compute-01.cels.anl.gov`.

### 3c — first SSH to the node + Duo (B10 verification)

```
[argo_opencode] Opening multiplexed SSH master to aattia@compute-01.cels.anl.gov (Duo prompt expected once)...
(aattia@logins.cels.anl.gov) Duo two-factor login for aattia
...
Passcode or option (1-1): 1
[ ok ]   master ready (subsequent SSH calls will reuse this connection)
```

**Tap Duo.** This is the only Duo prompt for the whole run.

**Pass:** `master ready` line appears. **No "jumphost loop"** error
(B9 verification, already done last session). **No "This account is currently
not available"** error (B10 verification, already done last session, re-confirmed).

**B15 sub-check:** in another terminal, while this is running:
```sh
ls ~/.ssh/sockets/
```
The new socket should be named like `argo-opencode-aattia-compute-01.cels.anl.gov-22`,
**NOT** a hash like `argo-opencode-59517c4bb1bc...`. **Pass criterion: the
socket name contains the literal user/host/port, not a hex hash.** This is
the B15 fix in action.

### 3d — local OpenCode config "differs" prompt (B1 verification)

```
[warn] OpenCode config already exists at /Users/attia/.config/opencode/config.json and differs from the proposed version.

  Choose how to handle ...
    [k] keep existing (no changes)
    [b] backup existing to .bak.<timestamp>, then overwrite
    [d] show diff (existing -> proposed), then ask again
    [m] merge: only update keys this script manages (requires jq for JSON)
    [a] abort
  Your choice [k/b/d/m/a]: d
```

**Type `d` first** — see the diff. Expected: existing has `0.0.0.0:64742`
in the baseURL, proposed has `localhost:64742`. The model list should be
substantially identical (5 models on both sides). The diff will be small.

After the diff, the prompt re-fires:

```
  Your choice [k/b/d/m/a]: k
```

**Type `k`** — keep your existing config. Reasons: `0.0.0.0:64742` works
fine as a client URL, you've been running on it for months, and we don't
want to disturb anything that's been stable. Picking `[b]` would also work
but we'd lose the side-by-side comparison opportunity.

**Pass:** `[ ok ] Keeping existing OpenCode config.`

**B1 verification:** the fact that the diff shown above contains a sane
`apiKey: "aattia"` and `Authorization: "Bearer aattia"` (not empty strings)
proves B1's username-fix is producing correct output. If you see empty
strings in the proposed side of the diff, that's a B1 regression — paste
the diff and we'll fix it when we resume.

### 3e — bootstrap on compute-01 (B14 verification — KEY CHECK)

```
[argo_opencode] Copying script to aattia@compute-01.cels.anl.gov:~/.argo_opencode.sh...
[argo_opencode] Running server bootstrap on compute-01.cels.anl.gov...
[argo_opencode] [server] starting bootstrap on compute-01... for user=aattia port=64742
[ ok ] system python3 3.x OK
[ ok ] venv python 3.x OK (/home/aattia/agovenv)
[ ok ] argo-proxy: argo-proxy 3.0.0
```

Then either:

**(A)** if there's an existing argo-proxy on compute-01 already serving 64742:

```
[ ok ] Existing argo-proxy already serving on 127.0.0.1:64742 (pid X); reusing.
[ ok ] Server is up on compute-01.cels.anl.gov:64742.
```

**(B)** if no existing process — argo-proxy needs to start fresh:

```
[warn] argo-proxy config already exists at ... and differs from the proposed version.
  Your choice [k/b/d/m/a]: d
```

**If (B), type `d`** to see the diff. **Critical B13 verification:** the
diff should show our writer keeping ALL existing keys
(`argo_url`, `argo_embedding_url`, `argo_stream_url`,
`concurrent_downloads`, etc.) and only changing the 4 owned keys
(`config_version`, `host`, `port`, `user`). If you see our writer
emitting only the 6 default keys (dropping the legacy ones), B13 didn't
work — paste the diff and we'll fix it when we resume.

After the diff, when prompt re-fires:

**Type `b`** to backup + overwrite. The merge writer produces a file that
preserves your legacy keys while updating the 4 owned ones. Safe.

```
[ ok ] Backed up to ...config.yaml.bak.<ts> and overwrote argo-proxy config.
[argo_opencode] Starting argo-proxy in screen session 'agovproxy'...
[ ok ] argo-proxy is listening on 127.0.0.1:64742.
[ ok ] Server is up on compute-01.cels.anl.gov:64742.
```

**B14 verification — CRITICAL:** count the number of times you see
`[server] starting bootstrap on compute-01...`. **It should appear EXACTLY
ONCE.** Last session it appeared twice (the duplicate-bootstrap bug). If it
appears twice here, B14 didn't work — capture the full output.

### 3f — tunnel up + summary

```
[argo_opencode] Opening tunnel: localhost:64742 -> compute-01.cels.anl.gov:64742 via logins.cels.anl.gov
[ ok ] Tunnel is live. argo-proxy responding at http://localhost:64742
```

Then the big summary box, ALL GREEN. 38 models. 5 configured. Etc.

```
[argo_opencode] Foregrounding tunnel. Ctrl-C to disconnect.
```

The script is now blocking. **Leave this terminal alone** — Ctrl-C will tear
down the tunnel.

---

## Step 4 — verify the new tunnel is healthy (in a SECOND terminal)

```sh
# Identify the new tunnel
ps -ax -o pid,ppid,user,etime,command | grep -E '[s]sh.*-N -L 64742'
# Expected: ssh -N -L 64742:localhost:64742 ... aattia@compute-01.cels.anl.gov
# PPID should be the bash argo_opencode.sh pid, NOT 1.
# (Compare to the OLD tunnel which had PPID=1 because of -f.)

# Direct hit on /health
curl -s http://localhost:64742/health
echo

# Status from the script
bash argo_opencode.sh status 2>&1 | tail -25
```

**Pass:**
- ssh process exists, NO `-f` flag, PPID is the bash argo_opencode.sh pid
- `curl /health` returns `{"status": "healthy"}`
- `status` summary box shows ALL GREEN

**B13 follow-up verification (in the second terminal):**

```sh
# Pull the AFTER snapshot of the remote argoproxy config
ssh -J aattia@logins.cels.anl.gov aattia@compute-01.cels.anl.gov \
  'cat ~/.config/argoproxy/config.yaml' > /tmp/argoproxy_config_AFTER.yaml
# This should NOT fire Duo because the mux master is warm.

echo "--- BEFORE ---"; cat /tmp/argoproxy_config_BEFORE.yaml
echo "--- AFTER ---";  cat /tmp/argoproxy_config_AFTER.yaml
echo "--- DIFF ---";   diff -u /tmp/argoproxy_config_BEFORE.yaml /tmp/argoproxy_config_AFTER.yaml
```

**Pass criterion (B13):** the diff should ONLY show changes to the 4 owned
keys: `config_version` (probably `''` → `'3'`), `host` (`0.0.0.0` → `127.0.0.1`),
`port` (probably unchanged at 64742), `user` (unchanged). It may also ADD
`argo_base_url` and `verbose` if they were missing. **All other keys must
appear in both BEFORE and AFTER, identical.** If `argo_url`,
`argo_embedding_url`, `argo_stream_url`, `concurrent_downloads`, etc. are
missing from AFTER, B13 didn't work — save the diff.

**If you took path (A) at step 3e** (existing process reused), the file
wasn't rewritten this run, so the BEFORE and AFTER will be identical. That's
fine — B13 isn't exercised but isn't violated either.

---

## Step 5 — let it sit for ~30s, then test OpenCode connectivity

```sh
# Open a new terminal, try OpenCode
opencode
```

Type a quick "hello" prompt. **Pass:** OpenCode connects, returns a response.
This proves the new tunnel + remote argo-proxy + your existing OpenCode config
all interoperate correctly.

If OpenCode fails to connect: check that your config still has
`baseURL: "http://0.0.0.0:64742/v1"` (or `localhost:64742`). Should match
either since both work.

---

## Step 6 — resume conversation with me

Once Step 5 succeeds, you have a working tunnel through the patched script.
The OpenCode agent (me) reads from `localhost:64742`, which is now the new
tunnel built by the patched `argo_opencode.sh`. Open OpenCode again (or just
a new chat window) and resume the previous conversation.

Paste back, when we resume:

1. The number of times you saw `[server] starting bootstrap` (target: 1) — **B14 result**
2. The mux socket name from `ls ~/.ssh/sockets/` — **B15 result**
3. The OpenCode config diff from step 3d (just the apiKey/baseURL lines) — **B1 result**
4. The argoproxy config diff from step 4 (the `BEFORE → AFTER` diff) — **B13 result**
5. Anything that surprised you, or any prompts whose wording was unclear

We won't have explicit B2 verification (silent reconnect) unless your tunnel
actually drops mid-session. Skip it for now — code review was sufficient.

---

## Recovery — if anything goes sideways

### Test failed mid-bootstrap, no tunnel up

```sh
# Kill stale local listener if any
lsof -nPi :64742 -sTCP:LISTEN -t | xargs -r kill 2>/dev/null

# Kill stale remote screen + argo-proxy
ssh -J aattia@logins.cels.anl.gov aattia@compute-01.cels.anl.gov '
  screen -S agovproxy -X quit 2>/dev/null
  pkill -f "argo-proxy serve" 2>/dev/null
  sleep 1
  echo "--- final state ---"
  screen -ls 2>/dev/null
'

# Restore the OLD tunnel using the legacy script (so OpenCode works again
# while we figure out what broke)
bash start_argo_tunnel.sh
# Verify it's up:
lsof -nPi :64742 -sTCP:LISTEN
```

Then resume the conversation with the failure transcript.

### Test succeeded but OpenCode (Step 5) can't connect

Most likely cause: OpenCode is using a different port than the tunnel. Check:

```sh
grep -E '"baseURL"' ~/.config/opencode/config.json
lsof -nPi :64742 -sTCP:LISTEN
```

If they disagree, either edit config back to `64742` or kill the tunnel and
re-run with the right port. Resume the conversation either way.

### You accidentally Ctrl-C'd the foregrounded client

That's fine — the cleanup_local trap runs, tunnel comes down cleanly.
Re-run `bash argo_opencode.sh client` to bring it back. Cached username
and node will be reused so you skip those prompts.

---

## Summary of what each step verifies

| Step | Verifies | Bug |
|------|----------|-----|
| 0    | Script still parses                          | (regression check) |
| 1    | Remote state captured for diffing            | setup |
| 2    | mode_stop kills the legacy tunnel cleanly    | (sanity) |
| 3a   | Port resolves from config without override   | (sanity) |
| 3b   | Node picker shows configured nodes           | (sanity) |
| 3c   | Master opens against NODE not jump host      | B10 |
| 3c   | Mux socket name uses literal user-host-port  | **B15** |
| 3c   | No "jumphost loop" error                     | B9 |
| 3d   | Writer produces sane `apiKey` (Argonne user) | **B1** |
| 3e   | Bootstrap runs ONCE not twice                | **B14** |
| 3e   | Server-side argoproxy writer preserves keys  | **B13** |
| 4    | Tunnel is fresh (no `-f`, has bash parent)   | (sanity) |
| 4    | Status box shows ALL GREEN                   | (sanity) |
| 4    | argoproxy diff shows only owned-key changes  | **B13** |
| 5    | OpenCode end-to-end connectivity             | (sanity) |
