# argo-opencode

Self-contained orchestrator that lets Argonne users run AI coding assistants
([OpenCode](https://opencode.ai/), [Claude Code](https://docs.anthropic.com/en/docs/claude-code),
and others) against [argo-proxy](https://github.com/Oaklight/argo-proxy) on an
ANL compute node, from anywhere (inside or outside the ANL network).

One bash script, two roles:

- **Client mode (laptop)**: install the chosen AI client if needed, write
  its config, push this script to a chosen ANL compute node, start
  argo-proxy there inside `screen`, then open the SSH tunnel and monitor
  its health.
- **Server mode (ANL compute node)**: create a Python venv, install
  argo-proxy, write `~/.config/argoproxy/config.yaml`, start
  `argo-proxy serve` in `screen` (preferred), `tmux`, or `nohup`.

Server mode is auto-invoked over SSH by client mode. **You normally only ever
run `client`.**

## Quick start

The script ships as ONE physical file (`argo_anywhere.sh`) plus per-client
symlinks. The file inspects its invocation name (`$0`) at startup and selects
the matching client automatically — no flags needed.

| Filename | Default client |
|---|---|
| `argo_anywhere.sh` (canonical) | Interactive picker — choose at startup |
| `argo_opencode.sh` (symlink) | [OpenCode](https://opencode.ai/) |
| `argo_claudecode.sh` (symlink) | [Claude Code](https://docs.anthropic.com/en/docs/claude-code) |

### Installing all clients (recommended)

Download the canonical file once, then create local symlinks. A single
`curl` command upgrades every name simultaneously.

```sh
# Pin to a release (recommended for stability):
curl -fsSL https://raw.githubusercontent.com/a-attia/argo-opencode/v1.2.0/argo_anywhere.sh \
     -o argo_anywhere.sh && chmod +x argo_anywhere.sh

# Create per-client names (same file, no duplication):
ln -s argo_anywhere.sh argo_opencode.sh
ln -s argo_anywhere.sh argo_claudecode.sh

# Run:
bash argo_opencode.sh    # → OpenCode (no picker)
bash argo_claudecode.sh  # → Claude Code (no picker)
bash argo_anywhere.sh    # → interactive picker

# Upgrade all three at once:
curl -fsSL https://raw.githubusercontent.com/a-attia/argo-opencode/v1.2.0/argo_anywhere.sh \
     -o argo_anywhere.sh
```

### Installing a single client

If you only need one client, download it by name directly. GitHub follows the
symlink transparently, so you receive the full `argo_anywhere.sh` content saved
under the name you chose — `$0` does the rest.

```sh
# OpenCode only:
curl -fsSL https://raw.githubusercontent.com/a-attia/argo-opencode/v1.2.0/argo_opencode.sh \
     -o argo_opencode.sh && chmod +x argo_opencode.sh
bash argo_opencode.sh
# ...in another terminal once it says "Tunnel is live":
opencode
```

```sh
# Claude Code only:
curl -fsSL https://raw.githubusercontent.com/a-attia/argo-opencode/v1.2.0/argo_claudecode.sh \
     -o argo_claudecode.sh && chmod +x argo_claudecode.sh
bash argo_claudecode.sh
# ...in another terminal once it says "Tunnel is live":
claude
```

To track `main` instead of a pinned release (gets the latest fixes, but may
move under your feet):

```sh
curl -fsSL https://raw.githubusercontent.com/a-attia/argo-opencode/main/argo_anywhere.sh \
     -o argo_anywhere.sh
```

The first run prompts for your ANL (Argonne) username and asks you to pick
a compute node. Subsequent runs reuse the cached values.

### Picking a different client without renaming

```sh
# The 'setup' subcommand always shows the client picker:
bash argo_anywhere.sh setup

# argo_anywhere.sh with no subcommand defaults to the picker:
bash argo_anywhere.sh

# Each per-client name (argo_opencode.sh, argo_claudecode.sh, ...)
# defaults to that client — no picker shown.
```

### Upgrading from before v1.2.0

Pre-v1.2.0 the canonical filename was `argo_opencode.sh`. The rename to
`argo_anywhere.sh` is a pure file move + back-compat shims; **no manual
migration is required**:

- Existing curl URLs (e.g. `…/v1.1.0/argo_opencode.sh`) keep working forever
  -- tags are immutable.
- Existing per-client URLs (e.g. `…/main/argo_opencode.sh`) keep working --
  GitHub serves the symlink content transparently (the file is now a symlink
  to `argo_anywhere.sh`).
- The state directory (`~/.config/argo_opencode/`) is auto-migrated to
  `~/.config/argo_anywhere/` on the next run; cached username/node survive.
- Old env-var names (`ARGO_OPENCODE_USER`, etc.) keep working with a
  one-time deprecation warning per variable. Update your `.bashrc` exports
  to `ARGO_ANYWHERE_*` at your leisure.
- Stale SSH multiplex sockets (`~/.ssh/sockets/argo-opencode-*`) are
  closed by `clean`.
- Stale remote-side files (`~/.argo_opencode.sh`, `~/.argo_opencode.server.log`
  on the compute node) are removed by the next `clean`.

## Subcommands

| Subcommand | What it does |
|---|---|
| `client` (default) | Full laptop-side flow: install chosen client + write its config + tunnel + monitor. Chosen client is determined by invocation name (e.g. `argo_opencode.sh` -> OpenCode, `argo_claudecode.sh` -> Claude Code, `argo_anywhere.sh` -> interactive picker). |
| `setup` | Same as `client` but ALWAYS shows the client picker, regardless of invocation name |
| `tunnel` | Same as `client` but does NOT install or configure any client; just brings up the tunnel |
| `server` | Auto-invoked on the ANL compute node by `client` |
| `status` | Show local tunnel state + probe the proxy (ALL GREEN / DEGRADED / FAIL) |
| `update-models` | Refresh the OpenCode model list from the live `/v1/models` (OpenCode-specific) |
| `stop` | Kill the local SSH tunnel (does NOT touch the remote argo-proxy) |
| `clean` | Remove every artifact this script created (local + remote, with prompts) |
| `help` | Long-form guide (paths, troubleshooting, customization) |

The `help` subcommand prints the full guide. Keep it open while you work
through unfamiliar prompts:

```sh
bash argo_anywhere.sh help | less
```

## Prerequisites

**Laptop:**
- bash 3.2+ (macOS default works), `ssh`, `scp`, `curl`, `lsof`
  - macOS ships all of these. Minimal Linux installs (Alpine, slim Docker
    images) sometimes lack `lsof` — install it before running the script.
- SSH key-based auth to `logins.cels.anl.gov` (the script will refuse to
  proceed and show exact instructions if password auth is required)
- `jq`: **required** for `update-models`; **strongly recommended** for
  `status` (without it the model-count math is approximate and the
  `[m]erge` config-handling option is unavailable for JSON files)
- Optional: ANL VPN if you're off-site and your local network policy needs it

**ANL compute node** (auto-handled by `server` mode):
- Python 3.10+
- `screen` or `tmux` (falls back to `nohup`)

## What it writes where

**Laptop:**

| Path | Purpose |
|---|---|
| `~/.config/opencode/config.json` | OpenCode config (only when running the OpenCode flow) |
| `~/.claude/settings.json` *or* `./.claude/settings.local.json` | Claude Code config (only when running the Claude Code flow); see "Claude Code scope" below |
| `~/.config/argo_anywhere/user` | Cached ANL username |
| `~/.config/argo_anywhere/node` | Last-used compute node |
| `~/.ssh/sockets/argo-anywhere-<user>-<host>-<port>` | SSH multiplex master socket (Duo prompts only fire once per session) |

**ANL compute node** (after first run):

| Path | Purpose |
|---|---|
| `~/.argo_anywhere.sh` | Pushed copy of this script |
| `~/.argo_anywhere.server.log` | Server-mode bootstrap log |
| `~/agovenv/` | Python venv with argo-proxy installed |
| `~/.config/argoproxy/config.yaml` | argo-proxy config (port + user) |

See [`examples/`](./examples/) for sanitized templates of both configs.

## MFA / Duo

ANL CELS hosts use Duo. The script defaults to MFA-aware mode using SSH
`ControlMaster` connection multiplexing — **one Duo prompt per session**,
not per SSH call. The mux master is opened against the chosen compute node
(not the jump host, which on CELS is shell-restricted).

To turn this off for non-Duo hosts: `--no-mfa` or `ARGO_ANYWHERE_NO_MFA=1`.

## Running on a compute node

The default `client` flow assumes you are running the script from a laptop
*outside* the ANL network. If the script detects it is itself running on
an ANL compute node (the FQDN matches a name in `ANL_NODES` or ends in
`.cels.anl.gov`), it adjusts:

- `--no-jump` and `--no-mfa` are auto-defaulted on (intra-site SSH needs
  neither).
- If the picked node is the local host, the SSH tunnel is **skipped
  entirely**: `client` invokes the server-mode bootstrap inline and the
  local OpenCode config is pointed at `http://localhost:<port>/v1`
  directly. argo-proxy keeps running under `screen`/`tmux`/`nohup`
  after `client` returns; use `clean` to stop it.

Override either default with `ARGO_ANYWHERE_NO_JUMP=0` or
`ARGO_ANYWHERE_NO_MFA=0` if your setup needs the slow path.

If you only want to leave argo-proxy running on a node (no client
install, no tunnel), use `server` directly:

```sh
ssh <user>@compute-XX.cels.anl.gov
bash argo_anywhere.sh server   # starts argo-proxy under screen, returns
```

Other clients on other machines can then point at this proxy via their
own SSH `-L` forward, or via `argo_anywhere.sh client --node compute-XX`
from those machines.

## Sharing a compute node with other users

Each user runs their own argo-proxy instance on the compute node — the
proxy is per-user, listening on `127.0.0.1:<port>`, and your config + auth
travel with it. Two users **can** share a compute node, but they cannot
share the same port: whoever binds first wins, and the other gets refused.

To handle this gracefully, the script:

- **Detects port collisions before bootstrap.** Before `client` ssh's into
  the node to start argo-proxy, it probes `127.0.0.1:<port>` on the node
  and identifies the owner. If it's you, the script reuses; if it's someone
  else, you're prompted:

  ```
  [warn] Port 64742 on compute-01 is in use by another user
         (pid 12345, owned by 'alice'; you are 'aattia').

         Two users can't share an argo-proxy on the same port; each needs
         their own. Options:
           [n] next free port  -- probe a range and use the first free one
           [p] pick a port    -- I'll type a number (1024-65535)
           [r] retry          -- maybe 'alice' just stopped; check again
           [a] abort
    Your choice [n/p/r/a, default=n]:
  ```

- **`--auto-port`** (or `ARGO_ANYWHERE_AUTO_PORT=1`) skips the prompt and
  auto-picks the next free port. After picking, the existing OpenCode
  config-migration prompt fires so you can choose to make the new port
  sticky (recommended) or use it for one run only.

- **`--port-range LO-HI`** overrides the default search range (defaults to
  `64742`-`64842`). Use it if your environment reserves a different range
  for ad-hoc services.

- **Local self-collision** (you re-run `client` while a tunnel is already
  up from a previous invocation): the script detects the existing healthy
  tunnel and reuses it instead of erroring, then proceeds to client setup.
  This makes "I want to add another client to my running tunnel" a natural
  workflow once Phase 3+ adds non-OpenCode clients.

### Caveat: load-balanced node aliases and orphan argo-proxies

The user-facing names in `ANL_NODES` (`compute-01.cels.anl.gov`, etc.)
are **DNS aliases** that CELS resolves internally to one of several
physical hosts (`compute-XXX-Y`). Two consequences worth knowing:

- **Successive `client` runs may land on different physical hosts.**
  If today's run picks `compute-01` and lands on `compute-386-01`, and
  tomorrow's run on the same `compute-01` lands on `compute-742-03`,
  yesterday's argo-proxy keeps running on `compute-386-01` — orphaned
  but harmless. Over time these accumulate. The script can't reliably
  clean them up because it doesn't know the alias-to-physical mapping.

- **Periodic manual cleanup is the recommended mitigation.** From a
  shell on whichever physical host you happen to be on:
  ```sh
  ssh <user>@<physical-host> 'pkill -u <user> -f "argo-proxy serve"'
  ```
  Or simply `bash argo_anywhere.sh clean` whenever you've definitively
  finished with a node — that handles the current physical host's
  argo-proxy via the screen session. Orphans on other physical hosts
  remain.

- **The on-node short-circuit** (running `client` directly on a compute
  node) recognizes load-balanced aliases by resolving the picked
  hostname to its IPs and intersecting with the local interface IPs
  — so picking `compute-01` while logged into `compute-386-01` (where
  the alias includes you) correctly skips the SSH tunnel.

## Claude Code scope (project vs. global)

Claude Code reads its config from up to three files (more-specific wins,
but the `env` block is **replaced** wholesale across scopes — Anthropic
chose not to deep-merge it):

| File | Scope |
|---|---|
| `~/.claude/settings.json` | global (all projects, all directories) |
| `./.claude/settings.json` | per-project, **committed** (visible to collaborators) |
| `./.claude/settings.local.json` | per-project, **gitignored** by default |

`argo_claudecode.sh` writes EITHER the global file OR the project-local
file (never the committed file — that would force your collaborators to
also use this proxy). The choice is automatic by default, checked in order:

1. **`~/.claude.json` exists** — Claude Code's auth state file, created by
   `claude auth login`. Its presence means you have a personal Anthropic
   subscription. Writing `ANTHROPIC_AUTH_TOKEN` to the global
   `~/.claude/settings.json` would shadow your OAuth token and break all
   non-proxy Claude Code usage → **project scope** automatically.
2. **`~/.claude/settings.json` already has an `env` block** — you (or
   another tool) put env vars in the global file; clobbering it would
   silently remove them → **project scope** automatically.
3. **Neither condition** → **global scope** (smoothest UX for first-time
   users with no prior Claude Code setup).

To force one or the other:

```sh
bash argo_claudecode.sh --scope global    # always touch ~/.claude/settings.json
bash argo_claudecode.sh --scope project   # always touch ./.claude/settings.local.json
```

When the script writes the project scope, **you must run `claude` from
that same directory** to pick up the settings. The script prints which
directory at the end of the setup step.

The script always preserves any non-Anthropic-Argo keys in the target
file's `env` block (and the file's other top-level keys: `model`,
`permissions`, `hooks`, etc.). It only owns `ANTHROPIC_BASE_URL` and
`ANTHROPIC_AUTH_TOKEN`.

## Tunnel monitoring and reconnect

While `client` is in the foreground, a background loop polls
`http://localhost:<port>/health` every 15 s and notifies you on sustained
failure. If the foreground SSH process exits but `/health` still responds
(common on macOS, where the multiplex master takes over the forward and the
foreground client exits immediately), the script recognizes this as the
no-op it is and stays quiet — the master keeps the tunnel alive on its own.

If a real reconnect IS needed and the mux master is still alive, the script
attempts a silent reconnect (no Duo prompt). If reconnects fire too rapidly
(≥3 within 60 s — typically a sign of a flapping network or an OpenSSH quirk
the script can't paper over), it pauses for ~30 s before retrying so it
doesn't spam the master, your terminal, or system notifications.

## SSH failure protection

ANL/CELS networks are monitored for repeated failed SSH authentications;
too many failures from one IP trigger a CSPO (Cyber Security) block on
that IP. On a shared compute node where many users share the same outbound
IP, one user's broken SSH agent can lock out everyone.

The script tracks consecutive SSH authentication failures. After **3
consecutive failures**, it refuses all further SSH attempts and writes a
**lock file** (`~/.config/argo_anywhere/ssh-fail-lock`) that persists
across script restarts — so re-running the script immediately after a
failure doesn't silently accumulate more failures against CSPO's rate
limiter. You'll see:

```
[err ] SSH has failed 3 consecutive times.
[err ] Disabling further SSH attempts to prevent CSPO from blocking your IP
[err ]   (and locking out everyone else sharing this compute node).
[err ]   Lock will auto-expire in 300s, or delete it manually:
[err ]     rm ~/.config/argo_anywhere/ssh-fail-lock
[err ]
[err ] Common causes:
[err ]   * Closed laptop while SSH agent forwarding was active
[err ]   * Expired Kerberos tickets
[err ]   * SSH key removed from the agent ('ssh-add -D' earlier)
[err ]   * Wrong username (--user / ARGO_ANYWHERE_USER mismatch)
```

**Recovery:**
1. Verify SSH works manually: `ssh <user>@logins.cels.anl.gov true`
2. Fix whatever is broken (re-add key, renew tickets, correct username).
3. Either wait 5 minutes for the lock to auto-expire, or delete it immediately:
   ```sh
   rm ~/.config/argo_anywhere/ssh-fail-lock
   ```
4. Re-run the script.

The counter resets on any successful SSH attempt, so transient single
failures followed by a working retry do not accumulate toward the lock.

## Port policy

The OpenCode config's `baseURL` is the source of truth. The default port is
**64742**. To override for one run:

```sh
bash argo_anywhere.sh --port 64999 client
# Prompts whether to migrate config (m), use override for this run only (u),
# keep the config's port (k), or abort (a).
```

## Common operations

```sh
# Check what's happening
bash argo_anywhere.sh status

# See the full /v1/models list
ARGO_ANYWHERE_SHOW_MODELS=1 bash argo_anywhere.sh status

# Refresh the OpenCode model list from the live proxy
bash argo_anywhere.sh update-models                  # interactive: prompts per-orphan
bash argo_anywhere.sh update-models --keep-orphans   # add new; keep all stale entries
bash argo_anywhere.sh update-models --drop-orphans   # add new; drop all stale entries

# Tear down only the local tunnel
bash argo_anywhere.sh stop

# Remove everything this script created (preview first)
bash argo_anywhere.sh clean --dry-run                # safe enumeration; no changes
bash argo_anywhere.sh clean                          # interactive (per-file prompts for risky items)
bash argo_anywhere.sh clean -y                       # non-interactive; deletes safe items, KEEPS risky configs
bash argo_anywhere.sh clean -y --purge-backups       # also drop accumulated .bak.* files
bash argo_anywhere.sh clean -y --purge               # delete EVERYTHING, including configs
```

`clean` separates artifacts into three risk tiers:

- **safe** (state dir, mux sockets, our SSH tunnel, the remote venv) —
  removed on confirmation
- **risky** (`~/.config/opencode/config.json`,
  `~/.config/argoproxy/config.yaml`, and their `.bak.*` files) —
  per-file `[k]eep / [r]estore-from-backup / [d]elete / [b]ackups-only`
  prompt, or `--purge` / `--purge-backups` for the non-interactive paths
- **never touched** — the OpenCode binary, the script itself, system tools

For the full guide (troubleshooting, customization, env vars, security
notes), run `bash argo_anywhere.sh help`.

## Testing

[`docs/TESTING.md`](./docs/TESTING.md) is a step-by-step live-verification
guide for the `client` end-to-end path. Use it after non-trivial edits or
before tagging a release. It's structured so you can follow it without
external help (~5–10 min, one Duo prompt).

For lighter smoke tests after edits:

```sh
bash -n argo_anywhere.sh                              # syntax
bash argo_anywhere.sh -h                              # short usage
bash argo_anywhere.sh status                          # exit 1 if no tunnel
bash argo_anywhere.sh clean --dry-run -y --local-only # safe enumeration
```

## Related projects

- [argo-proxy](https://github.com/Oaklight/argo-proxy) — the local proxy this
  script orchestrates
- [OpenCode](https://opencode.ai/) — the AI coding assistant
- [ANL AI4Dev notes](https://web.cels.anl.gov/~jacob/ai4dev.html) — the
  internal reference this script is built around

## Author

Ahmed Attia (attia@anl.gov)
