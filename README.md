# argo-opencode

Self-contained orchestrator that lets Argonne users run [OpenCode](https://opencode.ai/)
against [argo-proxy](https://github.com/Oaklight/argo-proxy) on an ANL compute
node, from anywhere (inside or outside the ANL network).

One bash script, two roles:

- **Client mode (laptop)**: install OpenCode if needed, write the OpenCode
  config, push this script to a chosen ANL compute node, start argo-proxy
  there inside `screen`, then open the SSH tunnel and monitor its health.
- **Server mode (ANL compute node)**: create a Python venv, install
  argo-proxy, write `~/.config/argoproxy/config.yaml`, start
  `argo-proxy serve` in `screen` (preferred), `tmux`, or `nohup`.

Server mode is auto-invoked over SSH by client mode. **You normally only ever
run `client`.**

## Quick start

Pinned to a release (recommended for stability):

```sh
curl -fsSL https://raw.githubusercontent.com/a-attia/argo-opencode/v1.0.0/argo_opencode.sh \
     -o argo_opencode.sh
bash argo_opencode.sh                # runs 'client' by default
# ...in another terminal once it says "Tunnel is live":
opencode
```

Or live from `main` (gets you the latest fixes, may move under your feet):

```sh
curl -fsSL https://raw.githubusercontent.com/a-attia/argo-opencode/main/argo_opencode.sh \
     -o argo_opencode.sh
```

The first run prompts for your ANL (Argonne) username and asks you to pick
a compute node. Subsequent runs reuse the cached values.

## Subcommands

| Subcommand | What it does |
|---|---|
| `client` (default) | Full laptop-side flow: install + config + tunnel + monitor |
| `tunnel` | Same as `client` but does NOT install or configure any client; just brings up the tunnel |
| `server` | Auto-invoked on the ANL compute node by `client` |
| `status` | Show local tunnel state + probe the proxy (ALL GREEN / DEGRADED / FAIL) |
| `update-models` | Refresh the OpenCode model list from the live `/v1/models` |
| `stop` | Kill the local SSH tunnel (does NOT touch the remote argo-proxy) |
| `clean` | Remove every artifact this script created (local + remote, with prompts) |
| `help` | Long-form guide (paths, troubleshooting, customization) |

The `help` subcommand prints the full guide. Keep it open while you work
through unfamiliar prompts:

```sh
bash argo_opencode.sh help | less
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
| `~/.config/opencode/config.json` | OpenCode config the script writes |
| `~/.config/argo_opencode/user` | Cached ANL username |
| `~/.config/argo_opencode/node` | Last-used compute node |
| `~/.ssh/sockets/argo-opencode-<user>-<host>-<port>` | SSH multiplex master socket (Duo prompts only fire once per session) |

**ANL compute node** (after first run):

| Path | Purpose |
|---|---|
| `~/.argo_opencode.sh` | Pushed copy of this script |
| `~/.argo_opencode.server.log` | Server-mode bootstrap log |
| `~/agovenv/` | Python venv with argo-proxy installed |
| `~/.config/argoproxy/config.yaml` | argo-proxy config (port + user) |

See [`examples/`](./examples/) for sanitized templates of both configs.

## MFA / Duo

ANL CELS hosts use Duo. The script defaults to MFA-aware mode using SSH
`ControlMaster` connection multiplexing — **one Duo prompt per session**,
not per SSH call. The mux master is opened against the chosen compute node
(not the jump host, which on CELS is shell-restricted).

To turn this off for non-Duo hosts: `--no-mfa` or `ARGO_OPENCODE_NO_MFA=1`.

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

Override either default with `ARGO_OPENCODE_NO_JUMP=0` or
`ARGO_OPENCODE_NO_MFA=0` if your setup needs the slow path.

If you only want to leave argo-proxy running on a node (no client
install, no tunnel), use `server` directly:

```sh
ssh <user>@compute-XX.cels.anl.gov
bash argo_opencode.sh server   # starts argo-proxy under screen, returns
```

Other clients on other machines can then point at this proxy via their
own SSH `-L` forward, or via `argo_opencode.sh client --node compute-XX`
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

- **`--auto-port`** (or `ARGO_OPENCODE_AUTO_PORT=1`) skips the prompt and
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
  Or simply `bash argo_opencode.sh clean` whenever you've definitively
  finished with a node — that handles the current physical host's
  argo-proxy via the screen session. Orphans on other physical hosts
  remain.

- **The on-node short-circuit** (running `client` directly on a compute
  node) recognizes load-balanced aliases by resolving the picked
  hostname to its IPs and intersecting with the local interface IPs
  — so picking `compute-01` while logged into `compute-386-01` (where
  the alias includes you) correctly skips the SSH tunnel.

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

The script defends against this with a simple consecutive-failure counter:
after **3 consecutive SSH authentication failures**, all further SSH
attempts in this run are refused, and you'll see a recovery message:

```
[err ] SSH has failed 3 consecutive times.
[err ] Disabling further SSH attempts to prevent CSPO from blocking your IP
[err ]   (and locking out everyone else sharing this compute node).
[err ]
[err ] Common causes:
[err ]   * Closed laptop while SSH agent forwarding was active
[err ]   * Expired Kerberos tickets
[err ]   * SSH key removed from the agent ('ssh-add -D' earlier)
[err ]   * Wrong username (--user / ARGO_OPENCODE_USER mismatch)
```

Recovery: verify SSH works manually (`ssh <user>@logins.cels.anl.gov true`),
fix whatever's broken, then re-run the script. The lock resets on restart
by design — you have to take an action before re-trying so we don't
silently re-trigger the same failure pattern.

The counter resets on any successful SSH attempt; transient single failures
followed by a recovery don't accumulate.

## Port policy

The OpenCode config's `baseURL` is the source of truth. The default port is
**64742**. To override for one run:

```sh
bash argo_opencode.sh --port 64999 client
# Prompts whether to migrate config (m), use override for this run only (u),
# keep the config's port (k), or abort (a).
```

## Common operations

```sh
# Check what's happening
bash argo_opencode.sh status

# See the full /v1/models list
ARGO_OPENCODE_SHOW_MODELS=1 bash argo_opencode.sh status

# Refresh the OpenCode model list from the live proxy
bash argo_opencode.sh update-models                  # interactive: prompts per-orphan
bash argo_opencode.sh update-models --keep-orphans   # add new; keep all stale entries
bash argo_opencode.sh update-models --drop-orphans   # add new; drop all stale entries

# Tear down only the local tunnel
bash argo_opencode.sh stop

# Remove everything this script created (preview first)
bash argo_opencode.sh clean --dry-run                # safe enumeration; no changes
bash argo_opencode.sh clean                          # interactive (per-file prompts for risky items)
bash argo_opencode.sh clean -y                       # non-interactive; deletes safe items, KEEPS risky configs
bash argo_opencode.sh clean -y --purge-backups       # also drop accumulated .bak.* files
bash argo_opencode.sh clean -y --purge               # delete EVERYTHING, including configs
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
notes), run `bash argo_opencode.sh help`.

## Testing

[`docs/TESTING.md`](./docs/TESTING.md) is a step-by-step live-verification
guide for the `client` end-to-end path. Use it after non-trivial edits or
before tagging a release. It's structured so you can follow it without
external help (~5–10 min, one Duo prompt).

For lighter smoke tests after edits:

```sh
bash -n argo_opencode.sh                              # syntax
bash argo_opencode.sh -h                              # short usage
bash argo_opencode.sh status                          # exit 1 if no tunnel
bash argo_opencode.sh clean --dry-run -y --local-only # safe enumeration
```

## Related projects

- [argo-proxy](https://github.com/Oaklight/argo-proxy) — the local proxy this
  script orchestrates
- [OpenCode](https://opencode.ai/) — the AI coding assistant
- [ANL AI4Dev notes](https://web.cels.anl.gov/~jacob/ai4dev.html) — the
  internal reference this script is built around

## Author

Ahmed Attia (attia@anl.gov)
