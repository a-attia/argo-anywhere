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
- SSH key-based auth to `logins.cels.anl.gov` (the script will refuse to
  proceed and show exact instructions if password auth is required)
- Optional: `jq` for `update-models` and the `[m]erge` config-handling option
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
bash argo_opencode.sh update-models

# Tear down only the local tunnel
bash argo_opencode.sh stop

# Remove everything this script created (preview first)
bash argo_opencode.sh clean --dry-run
bash argo_opencode.sh clean
```

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
