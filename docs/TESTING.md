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

---

## On-node paths (Phase 2 additions)

The above guide tests the **laptop → tunnel → compute node** flow. If
you want to verify the script's on-node paths (running `client`, `tunnel`,
or `server` directly from a shell on a compute node), use this section.

### Setup: get a shell on a compute node

```sh
ssh -J <user>@logins.cels.anl.gov <user>@compute-01.cels.anl.gov
```

Once on the node, fetch the script (or use the existing
`~/.argo_opencode.sh` if it's recent enough — `md5sum` it against the
fresh download to be sure):

```sh
curl -fsSL https://raw.githubusercontent.com/a-attia/argo-opencode/main/argo_opencode.sh -o argo_opencode.sh
md5sum argo_opencode.sh
```

### On-node test 1: `client` with same-host short-circuit

Goal: verify the script detects "I'm on the picked node" and skips the
SSH tunnel, running argo-proxy locally instead.

```sh
# Capture pre-state
stat -c '%Y %n' ~/.argo_opencode.sh ~/.argo_opencode.server.log 2>/dev/null
date +%s

bash argo_opencode.sh client
# When the picker shows up, pick compute-01 (or whichever alias is the
# default-marked entry). The fix in commit ee8b13c makes the script
# default to the alias that resolves to your physical host.
```

**Pass criteria:**

- `[argo_opencode] Detected ANL compute node (compute-XXX-Y...); defaulting to --no-jump.` — auto-detection fired.
- `[argo_opencode] Selected node is this host (compute-XXX-Y...); skipping SSH tunnel.` — short-circuit fired.
- `~/.argo_opencode.sh` mtime: **unchanged** (no scp happened).
- argo-proxy: same pid as before (existing instance reused, not restarted).
- The shell returns to the prompt (no foreground tunnel).

### On-node test 2: `tunnel` standalone

Goal: verify `tunnel` brings up the tunnel without touching the OpenCode
config.

```sh
# Snapshot OpenCode config mtime
stat -c '%Y %n' ~/.config/opencode/config.json 2>/dev/null

bash argo_opencode.sh tunnel
```

**Pass criteria:**

- Same on-node short-circuit lines as test 1.
- No `[ ok ] OpenCode already installed` or `OpenCode config already
  up to date` lines (because tunnel doesn't run setup_opencode_client).
- `~/.config/opencode/config.json` mtime: **unchanged**.

### On-node test 3: `server` standalone

Goal: verify the standalone-server identity-resolution prompt.

```sh
bash argo_opencode.sh server
```

**Pass criteria:**

- `[argo_opencode] Standalone 'server' invocation. Resolved identity from local config + cache ...`
- `Proceed? [Y/n]:` — type `Y` or hit Enter.
- The prompt fires **exactly once** (the tee re-exec subprocess inherits
  the resolved values via env, so its standalone-detection sees them as
  already-set; the second-pass prompt is suppressed).

Now test the non-interactive path:

```sh
bash argo_opencode.sh -y server
# Should NOT prompt. -y skips the confirmation.
```

And the env-supplied path (verifies the prompt is also suppressed when
env is supplied explicitly):

```sh
ARGO_OPENCODE_USER=<user> ARGO_OPENCODE_PORT=64742 bash argo_opencode.sh server
# Should NOT prompt. The env-was-supplied check bypasses the standalone branch.
```

### On-node test 4: `stop` confirmation prompt

Goal: verify the on-node `mode_stop` shows the destructive-action
confirmation prompt and refuses by default.

```sh
bash argo_opencode.sh stop
# When the prompt asks 'Kill the listener anyway? [y/N]:' type 'n'.
```

**Pass criteria:**

- Warning lists the blast radius ("any client ... pointed at this host:port",
  "any laptop whose SSH tunnel forwards to this host:port", etc.).
- Default `[N]` aborts cleanly with `[err ] Aborted.`
- argo-proxy is still running afterward (verify with `lsof -nPi :64742 -sTCP:LISTEN`).

Then test the actual kill path:

```sh
bash argo_opencode.sh stop
# Type 'y' this time.
```

**Pass criteria:**

- `[ ok ] Killed: <pid>`
- Either a "session is still around" hint with screen/tmux cleanup
  command (if the wrapper survived), OR a calm "session manager exited
  along with its child; no cleanup needed" line (the typical case where
  argo-proxy was the only process inside its screen wrapper).
- No `xargs: warning: --max-args and --replace are mutually exclusive`
  message.

### On-node test 5: multi-user collision UX

Hard to test without a second user actually running argo-proxy on the
same physical host on the same port. If you happen to have two
collaborators willing to test simultaneously:

- User A: `bash argo_opencode.sh client` → claims port 64742.
- User B: `bash argo_opencode.sh client` → should see the
  `[warn] Port 64742 on <node> is in use by another user (pid X, owned
  by '<a>'; you are '<b>')` prompt with `[n/p/r/a]` choices.
- User B picks `[n]` → script auto-finds next free port (e.g. 64743),
  prompts the OpenCode-config migration `[m/u/k/a]`.

If you can't arrange this, the cheaper substitute is to manually start
something on the port to mimic a collision:

```sh
# Bind 64742 with a sleep process owned by your account
nohup sh -c 'python3 -m http.server 64742 >/dev/null 2>&1' >/dev/null 2>&1 &
PORT_HOG_PID=$!

# Then run client; the local_tunnel_status check should see "external-healthy"
# and skip the tunnel. NOT the same as the multi-user case (different OS user)
# but exercises the local-collision branch.

# Cleanup:
kill $PORT_HOG_PID
```

### On-node test 6: SSH attempt tracker

To verify the CSPO-IP-block defense without actually breaking your SSH
auth, simulate failures by running `client` with a deliberately wrong
username:

```sh
bash argo_opencode.sh --user no-such-user client
# Should fail at ssh_preflight with "Cannot reach no-such-user@<host> without a password."
# This counts ONE SSH attempt failure.

# Repeat 3 times total:
bash argo_opencode.sh --user no-such-user client
bash argo_opencode.sh --user no-such-user client

# By the third attempt within the same session, the tracker should fire
# and refuse further SSH attempts. But each script invocation is a fresh
# process, so the counter resets each time. To exercise the in-session
# threshold, you'd need a single invocation that does multiple SSH calls
# and fails each (e.g. --probe-nodes with no ANL_NODES reachable).
```

The tracker is mostly a defense against the script's reconnect loops
hammering on a flapping network — verifying it in normal use is
inherently awkward.

---

## What each on-node step verifies

| Test | What it verifies |
|------|------------------|
| 1    | Same-host short-circuit; no scp; argo-proxy reuse |
| 2    | `tunnel` subcommand doesn't touch OpenCode config |
| 3    | Standalone `server` resolution + single confirmation prompt; -y skips; env-supplied skips |
| 4    | `mode_stop` confirmation prompt; default-N aborts; -y bypass; calm post-kill messaging |
| 5    | Multi-user collision UX (`[n/p/r/a]` prompt, `--auto-port`, OpenCode migration follow-up) |
| 6    | SSH attempt tracker fires at threshold (~3 consecutive failures within a single invocation) |

---

## Multi-client tests (Phase 3+)

These verify that the per-client invocation/dispatch + Claude Code support
work end to end. Run after any change to the dispatcher
(`do_post_tunnel_for_client`, `default_client_for_invocation`,
`interactive_setup_picker`) or to per-client setup functions.

### Setup: ensure all symlinks are present

```sh
ls -la argo_*.sh
# Expect: argo_opencode.sh (regular file), argo_anywhere.sh and
# argo_claudecode.sh as symlinks (mode lrwxr-xr-x) pointing to argo_opencode.sh.
```

### Multi-client test 1: invocation-name dispatch

```sh
bash argo_opencode.sh -h | head -1     # "Usage: argo_opencode.sh ..."
bash argo_claudecode.sh -h | head -1   # "Usage: argo_claudecode.sh ..."
bash argo_anywhere.sh -h | head -1     # "Usage: argo_anywhere.sh ..."
```

All three must show their own basename. Any showing
`argo_opencode.sh` from a non-opencode invocation means the symlink
isn't being resolved or `$0` is being mangled.

### Multi-client test 2: interactive picker (anywhere)

```sh
printf '\n' | bash argo_anywhere.sh 2>&1 | head -10
# Expect:
#   Supported AI clients:
#     1) OpenCode ...
#     2) Claude Code ...
#   Pick a client [1-2, ...]:
#   [err ] No client picked; aborting.
```

Then with input `1`:

```sh
printf '1\n' | bash argo_anywhere.sh --user nobody --node bogus.example 2>&1 | head -20
# Expect: proceeds into the OpenCode flow and fails fast at the
# preflight step (since 'nobody'/'bogus.example' are not real). The
# important bit: the picker gates correctly.
```

### Multi-client test 3: `setup` subcommand forces picker

```sh
printf '\n' | bash argo_opencode.sh setup 2>&1 | head -8
# Expect the picker to appear EVEN THOUGH the invocation is argo_opencode.sh.
# (Without `setup`, argo_opencode.sh would proceed straight to the
# OpenCode flow without showing the picker.)
```

### Multi-client test 4: Claude Code scope auto-detection

Pre-conditions: a successful tunnel up to a compute node.

Test the global-scope branch (no existing `~/.claude/settings.json`):

```sh
# Make sure no global file exists, or back it up first.
[ -f ~/.claude/settings.json ] && mv ~/.claude/settings.json ~/.claude/settings.json.testbak
bash argo_claudecode.sh
# In the script's log lines, look for:
#   [argo_opencode] Claude Code scope: global (auto; no existing env block to preserve).
# Then verify the file:
cat ~/.claude/settings.json
# Should contain:
#   "env": {
#     "ANTHROPIC_BASE_URL": "http://localhost:64742",
#     "ANTHROPIC_AUTH_TOKEN": "<your-anl-username>"
#   }
```

Test the project-scope branch (existing `env` block in global):

```sh
# Pre-seed a global env block (e.g. simulating personal Anthropic key).
mkdir -p ~/.claude
cat > ~/.claude/settings.json <<'EOF'
{
  "env": {
    "ANTHROPIC_API_KEY": "sk-ant-personal-..."
  }
}
EOF

cd /tmp && mkdir -p test-claude-scope && cd test-claude-scope
bash ~/path/to/argo_claudecode.sh
# Look for:
#   [argo_opencode] Claude Code scope: project (auto; ~/.claude/settings.json
#     already has an env block).
# Then verify project file was written, global was untouched:
cat ./.claude/settings.local.json    # should have ANTHROPIC_BASE_URL etc.
cat ~/.claude/settings.json          # should still have the personal key
```

### Multi-client test 5: `--scope` override

```sh
bash argo_claudecode.sh --scope global
# Look for:  [argo_opencode] Claude Code scope: global (--scope global).
bash argo_claudecode.sh --scope project
# Look for:  [argo_opencode] Claude Code scope: project (--scope project).
bash argo_claudecode.sh --scope bogus
# Should die with: --scope must be 'project' or 'global' (got 'bogus').
```

### Multi-client test 6: Claude Code env-block merge preservation

Pre-condition: a `~/.claude/settings.json` with extra top-level keys
AND extra env keys we don't own.

```sh
cat > ~/.claude/settings.json <<'EOF'
{
  "model": "sonnet",
  "permissions": {"allow": ["Read"]},
  "env": {
    "ANTHROPIC_API_KEY": "sk-ant-personal-...",
    "MY_OTHER_VAR": "keep-me"
  }
}
EOF

bash argo_claudecode.sh --scope global
# Pick [b] backup+overwrite at the prompt (or [m] merge if offered).
# Then:
cat ~/.claude/settings.json
# Should still contain:
#   - "model": "sonnet"
#   - "permissions": {...}
#   - env.ANTHROPIC_API_KEY (preserved)
#   - env.MY_OTHER_VAR (preserved)
#   - env.ANTHROPIC_BASE_URL (NEW, from us)
#   - env.ANTHROPIC_AUTH_TOKEN (NEW, from us)
```

### Multi-client test 7: idempotency

```sh
bash argo_claudecode.sh        # writes the config
bash argo_claudecode.sh        # second run should report:
#   [ ok ] Claude Code config (...) already up to date: ...
# i.e. cmp -s in handle_config_file finds no diff, no prompt.
```

---

## What each multi-client step verifies

| Test | What it verifies |
|------|------------------|
| 1    | `$0` invocation-name detection survives symlink resolution |
| 2    | `argo_anywhere.sh` triggers picker; picker shows registered clients; abort-on-empty works |
| 3    | `setup` subcommand always shows picker regardless of `$0` |
| 4    | Auto-scope detection (global when no env block; project when there is one) |
| 5    | `--scope` override; invalid value rejected |
| 6    | `write_claudecode_config` Python heredoc preserves user-owned env keys + non-env top-level keys |
| 7    | Per-client setup is idempotent (handle_config_file's cmp branch) |
