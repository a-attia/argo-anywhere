# argo_opencode.sh — live verification guide

Audience: maintainers / contributors who have made a non-trivial change to
`argo_opencode.sh` and want to confirm the end-to-end `client` flow still works
before tagging a release or asking someone else to update.

This is the **live** smoke test (real SSH, real Duo prompt, real argo-proxy
on a compute node). For the cheaper local-only checks see
[Smoke tests](#smoke-tests-no-ssh-required) at the bottom of this file.

Reading time: ~5 min. Run time: ~5–10 min including one Duo prompt.

---

## Conventions in this guide

- All commands run on your **laptop** unless prefixed with `# (on <node>):`.
- "**Pass**" / "**Fail**" describe what to look for. If a step fails, read the
  **If it fails** block before moving on.
- Replace `<user>` with your ANL (Argonne) username and `<node>` with the
  compute node you actually use (e.g. `compute-01.cels.anl.gov`).
- This guide assumes you are running the version of `argo_opencode.sh` in
  *your current working directory* — typically your local clone of
  https://github.com/a-attia/argo-opencode. It does **not** re-download from
  GitHub or any hosted copy. If you want to test the published release
  instead, `curl` it down to a temp dir first and `cd` there.

---

## Step 0 — pre-flight sanity (30 s)

```sh
# Script syntax + basic invocation still work?
bash -n argo_opencode.sh && echo "syntax OK"
bash argo_opencode.sh -h >/dev/null 2>&1 && echo "usage OK"

# What's the resolved port for this checkout? (so you know what to look for
# in lsof / curl output below)
bash argo_opencode.sh status 2>&1 | grep -E 'Configured port' || true
```

**Pass:** `syntax OK` and `usage OK` both print. If you have an existing
tunnel running, the `status` output also tells you the port.

**Fail:** if `bash -n` reports an error, stop here and fix it before
proceeding — the later steps will all blow up.

---

## Step 1 — capture the current state for diffing later (1 min)

If you want to confirm that the script's argo-proxy YAML writer preserves
unknown keys (the merge path), snapshot the remote config now so you can diff
later. Skip this section if you already know the writer works or the node has
no existing config.

```sh
# Snapshot the laptop OpenCode config
cp -p ~/.config/opencode/config.json /tmp/opencode_config_BEFORE.json

# Snapshot the remote argo-proxy config on the node you'll target
ssh -J <user>@logins.cels.anl.gov <user>@<node> \
  'cat ~/.config/argoproxy/config.yaml' > /tmp/argoproxy_config_BEFORE.yaml

ls -la /tmp/opencode_config_BEFORE.json /tmp/argoproxy_config_BEFORE.yaml
echo "--- remote argoproxy config (BEFORE) ---"
cat /tmp/argoproxy_config_BEFORE.yaml
```

This SSH may trigger Duo if you have no warm multiplex master to `<node>`.

**Pass:** both snapshot files exist and are non-empty. The remote argo-proxy
config has a `port:` line and possibly extra keys (`argo_url`,
`argo_embedding_url`, `concurrent_downloads`, `max_payload_size`, etc.) — the
ones you want preserved across a `[b]ackup+overwrite` later.

**If it fails:** if the remote `cat` returns nothing, the node has no existing
argo-proxy config. Not a problem — the merge path just isn't exercised on
this node. Skip the BEFORE/AFTER diff at Step 4.

---

## Step 2 — kill any existing tunnel on the same port (5 s)

This will sever any active OpenCode session pointed at this port. **Close any
running OpenCode windows first**, otherwise OpenCode may print errors as the
tunnel dies.

```sh
# What port will the script use? (read from your OpenCode config; falls back
# to the built-in default 64742)
PORT="$(bash argo_opencode.sh status 2>&1 \
        | awk -F': *' '/Configured port/{print $2; exit}')"
echo "PORT=$PORT"

# Confirm what (if anything) is bound there
lsof -nPi ":${PORT}" -sTCP:LISTEN || echo "(nothing listening on $PORT)"

# Kill it via the script (also exits if nothing to do)
bash argo_opencode.sh stop
sleep 1
lsof -nPi ":${PORT}" -sTCP:LISTEN || echo "${PORT} free"
```

**Pass:** either `Nothing to stop locally.` (no prior listener) or
`[ ok ] Killed: <pid>` followed by `${PORT} free`.

**Fail:** if `stop` reports "Nothing to stop locally" but lsof still shows a
listener, the listener is bound to a different IP family than lsof default;
manually kill: `lsof -nPi ":${PORT}" -sTCP:LISTEN -t | xargs kill -9`.

---

## Step 3 — run the patched client (3–5 min, 1 Duo prompt)

This is the main test. Run interactively and answer the prompts as you would
for a normal session.

```sh
bash argo_opencode.sh client
```

You should see, in order:

### 3a — username + port resolution

```
[argo_opencode] Using ANL username: <user>
[argo_opencode] Using port: <port>  (source: opencode config baseURL)
```

**Pass:** username matches what you cached, port matches your config, source
is `opencode config baseURL` (or `built-in default` on a brand-new install).

If you passed `--port N` and it disagrees with the config, you'll instead be
asked `[m]igrate / [u]se-once / [k]eep / [a]bort`. That's expected — pick
whichever fits your test.

### 3b — node selection

The cached node from your last run is the default. To exercise the picker:

```
  Compute nodes:
    1) compute-01.cels.anl.gov
    2) compute-02.cels.anl.gov   (default)
    ...
    (reachability NOT probed; pass --probe-nodes to test each first)

  Pick a node [1-N, Enter = default]:
```

**Pick whatever node you intend to test against.**

**Pass:** `[argo_opencode] Selected node: <node>`.

### 3c — first SSH to the node + Duo

```
[argo_opencode] Opening multiplexed SSH master to <user>@<node> (Duo prompt expected once)...
(<user>@logins.cels.anl.gov) Duo two-factor login for <user>
...
Passcode or option (1-1): 1
[ ok ]   master ready (subsequent SSH calls will reuse this connection)
```

**Tap Duo.** This is the only Duo prompt for the whole run.

**Pass:** `master ready` line appears. **No "jumphost loop"** error and
**no "This account is currently not available"** — both indicate the
multiplex master was opened against the node, not the jump host.

**Sub-check (multiplex socket name):** in another terminal, while the run is
in progress:
```sh
ls ~/.ssh/sockets/
```
You should see a socket named `argo-opencode-<user>-<node>-22` — i.e. the
literal user/host/port tokens, **not** an opaque hex hash. The literal name
is required for socket reuse to survive `~/.ssh/config` rewrites.

### 3d — local OpenCode config handling

If your existing config differs from what the script would write, you'll see:

```
[warn] OpenCode config already exists at /Users/<you>/.config/opencode/config.json and differs from the proposed version.

  Choose how to handle ...
    [k] keep existing (no changes)
    [b] backup existing to .bak.<timestamp>, then overwrite
    [d] show diff (existing -> proposed), then ask again
    [m] merge: only update keys this script manages (requires jq for JSON)
    [a] abort
  Your choice [k/b/d/m/a]:
```

**Type `d` first** to inspect the diff. Sanity-check that the proposed file's
`apiKey` and `Authorization: Bearer …` lines contain your **Argonne**
username (not your laptop `$USER`). Then re-pick `k`, `b`, or `m` per your
intent.

**Pass:** the proposed `apiKey` is your Argonne username, not empty and not
your local OS account name.

### 3e — bootstrap on the compute node

```
[argo_opencode] Copying script to <user>@<node>:~/.argo_opencode.sh...
[argo_opencode] Running server bootstrap on <node>...
[argo_opencode] [server] starting bootstrap on <node>... for user=<user> port=<port>
[ ok ] system python3 3.x OK
[ ok ] venv python 3.x OK (/home/<user>/agovenv)
[ ok ] argo-proxy: argo-proxy <version>
```

Then either:

**(A) reuse path** — an existing argo-proxy is already serving:

```
[ ok ] Existing argo-proxy already serving on 127.0.0.1:<port> (pid X); reusing.
[ ok ] Server is up on <node>:<port>.
```

**(B) fresh path** — argo-proxy needs to start. You may then see a config-
differs prompt similar to Step 3d but for `~/.config/argoproxy/config.yaml`:

```
[warn] argo-proxy config already exists at ... and differs from the proposed version.
  Your choice [k/b/d/m/a]:
```

If you took the BEFORE snapshot at Step 1, **type `d`** here. Sanity-check
that the proposed file keeps your existing keys (`argo_url`,
`argo_embedding_url`, `concurrent_downloads`, etc.) and only changes the four
the script owns: `config_version`, `host`, `port`, `user`.

After the diff, re-prompt fires. **Type `b`** to back up + overwrite.

```
[ ok ] Backed up to ...config.yaml.bak.<ts> and overwrote argo-proxy config.
[argo_opencode] Starting argo-proxy in screen session 'agovproxy'...
[ ok ] argo-proxy is listening on 127.0.0.1:<port>.
[ ok ] Server is up on <node>:<port>.
```

**Pass criteria:**
- The `[server] starting bootstrap on <node>` line appears **exactly once**
  (not twice — that would indicate the `mode_server` re-exec is double-
  bootstrapping, a regression of an old bug).
- If you went through path (B), the proposed YAML preserved your unknown
  keys.

### 3f — tunnel up + summary

```
[argo_opencode] Opening tunnel: localhost:<port> -> <node>:<port> via logins.cels.anl.gov
[ ok ] Tunnel is live. argo-proxy responding at http://localhost:<port>
```

Then the ALL GREEN summary box, with non-zero model counts.

```
[argo_opencode] Foregrounding tunnel. Ctrl-C to disconnect.
```

The script is now blocking. **Leave this terminal alone** — Ctrl-C will tear
down the tunnel.

---

## Step 4 — verify the tunnel from a SECOND terminal

```sh
PORT="$(bash argo_opencode.sh status 2>&1 \
        | awk -F': *' '/Configured port/{print $2; exit}')"

# Identify the tunnel process
ps -ax -o pid,ppid,user,etime,command | grep -E "[s]sh.*-N -L ${PORT}"
# Expected: ssh -N -L <port>:localhost:<port> ... <user>@<node>
# PPID should be the bash argo_opencode.sh pid, NOT 1.

# Direct hit on /health
curl -s "http://localhost:${PORT}/health"
echo

# Status from the script
bash argo_opencode.sh status 2>&1 | tail -25
```

**Pass:**
- ssh process exists, no `-f` flag, PPID is the foregrounded
  `argo_opencode.sh client` invocation.
- `curl /health` returns `{"status": "healthy"}`.
- `status` summary box shows ALL GREEN.

### Optional: argo-proxy YAML preservation check

If you took the BEFORE snapshot at Step 1:

```sh
ssh -J <user>@logins.cels.anl.gov <user>@<node> \
  'cat ~/.config/argoproxy/config.yaml' > /tmp/argoproxy_config_AFTER.yaml
# Should NOT trigger Duo if the multiplex master is still warm.

diff -u /tmp/argoproxy_config_BEFORE.yaml /tmp/argoproxy_config_AFTER.yaml
```

**Pass:** the diff shows ONLY changes to the four owned keys
(`config_version`, `host`, `port`, `user`) and possibly additions of
`verbose` / `argo_base_url` if those were missing. Every other previously-
present key must appear in both BEFORE and AFTER, identical.

If you took the (A) reuse path at Step 3e the file wasn't rewritten and the
diff will be empty — that's fine, the merge path just wasn't exercised on
this run.

---

## Step 5 — end-to-end OpenCode connectivity

```sh
# In a new terminal
opencode
```

Type a quick "hello" prompt. **Pass:** OpenCode connects, returns a response.

If OpenCode fails to connect: confirm config and tunnel agree on the port.
```sh
grep -E '"baseURL"' ~/.config/opencode/config.json
lsof -nPi ":${PORT}" -sTCP:LISTEN
```

---

## Recovery — if anything goes sideways

### Test failed mid-bootstrap, no tunnel up

```sh
# Kill stale local listener, if any
PORT="$(bash argo_opencode.sh status 2>&1 | awk -F': *' '/Configured port/{print $2; exit}')"
lsof -nPi ":${PORT}" -sTCP:LISTEN -t | xargs -r kill 2>/dev/null

# Kill stale remote session + argo-proxy on the node
ssh -J <user>@logins.cels.anl.gov <user>@<node> '
  screen -S agovproxy -X quit 2>/dev/null
  pkill -f "argo-proxy serve" 2>/dev/null
  sleep 1
  echo "--- final state ---"
  screen -ls 2>/dev/null
'
```

Then re-run `bash argo_opencode.sh client` (or, in a pinch, the legacy
`start_argo_tunnel.sh` if you kept it around).

### You accidentally Ctrl-C'd the foregrounded client

That's fine — `cleanup_local` runs, the tunnel comes down cleanly. Re-run
`bash argo_opencode.sh client` to bring it back. Cached username and node
will be reused so you skip those prompts.

---

## Smoke tests (no SSH required)

These are the cheap checks to run after any non-trivial edit, even if you're
not ready for the full live test above:

```sh
bash -n argo_opencode.sh                              # syntax
bash argo_opencode.sh -h                              # short usage
bash argo_opencode.sh help | head -50                 # long help renders
bash argo_opencode.sh status                          # exit 1 if no tunnel
bash argo_opencode.sh clean --dry-run -y --local-only # safe enumeration
```

If any of these fail or print unexpected output, fix before moving to a live
test.

---

## What each live step verifies

| Step | What it verifies |
|------|------------------|
| 0    | Script still parses; basic dispatch works |
| 1    | Remote state captured (only needed for the merge-path verification at Step 4) |
| 2    | `mode_stop` cleanly tears down a previous tunnel |
| 3a   | Port resolves correctly (config baseURL > env > default) |
| 3b   | Node picker shows configured nodes and accepts a non-default choice |
| 3c   | Multiplex master opens against the NODE (not the jump host); socket name uses literal user/host/port |
| 3d   | OpenCode config writer produces a file whose `apiKey`/`Authorization` use the Argonne username |
| 3e   | Server bootstrap runs ONCE (not twice); argo-proxy YAML writer preserves unknown keys |
| 3f   | Tunnel comes up; `/health` answers; summary box renders ALL GREEN |
| 4    | Tunnel process has correct parent; argo-proxy YAML diff shows only owned-key changes |
| 5    | OpenCode end-to-end against the new tunnel works |
