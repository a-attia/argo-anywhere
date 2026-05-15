# argo-anywhere

> **Audience pointer for AI coding tools**: project conventions are in
> [`AGENTS.md`](AGENTS.md) (canonical) and [`CLAUDE.md`](CLAUDE.md) (symlink).
> The [`PLAN.md`](PLAN.md) is the active plan-of-record.

A self-contained bash script that lets Argonne (ANL) users run AI coding
CLI tools — [OpenCode](https://opencode.ai/),
[Claude Code](https://docs.anthropic.com/en/docs/claude-code), and
others — against [argo-proxy](https://github.com/Oaklight/argo-proxy)
on an ANL compute node, **from any laptop on any network**, with
**one Duo prompt per session**.

> Upgrading from `argo_opencode.sh` (pre-v2.0)? See
> [`docs/UPGRADING.md`](docs/UPGRADING.md) for the full migration
> guide. The script also auto-detects v1.x state on first run and
> prints exact cleanup commands.

## Contents

- [What this is](#what-this-is)
- [Status](#status)
- [Quick start](#quick-start)
- [Prerequisites](#prerequisites)
- [How `argo_anywhere.sh` is organised (subcommands)](#how-argo_anywheresh-is-organised-subcommands)
- [What it writes where](#what-it-writes-where)
- [MFA / Duo handling](#mfa--duo-handling)
- [Running on a compute node](#running-on-a-compute-node)
- [Sharing a compute node with other users](#sharing-a-compute-node-with-other-users)
- [Claude Code config scope (project vs. global)](#claude-code-config-scope-project-vs-global)
- [Tunnel monitoring and reconnect](#tunnel-monitoring-and-reconnect)
- [SSH failure protection (CSPO defense)](#ssh-failure-protection-cspo-defense)
- [Port policy](#port-policy)
- [Common operations](#common-operations)
- [Where to read more](#where-to-read-more)
- [Upgrading from `argo_opencode.sh` (pre-v2.0)](#upgrading-from-argo_opencodesh-pre-v20)
- [Testing](#testing)
- [Contributing](#contributing)
- [Related projects](#related-projects)
- [Authors](#authors)

## What this is

One bash script (`argo_anywhere.sh`) that orchestrates two roles:

- **Client mode (laptop)**: install the chosen AI CLI tool if needed,
  write its config, push this script to a chosen ANL compute node,
  start argo-proxy there inside `screen` (preferred; falls back to
  `tmux`, then `nohup`), then open the SSH tunnel and monitor its
  health.
- **Server mode (ANL compute node)**: create a Python venv, install
  argo-proxy, write `~/.config/argoproxy/config.yaml`, start
  `argo-proxy serve` inside `screen`/`tmux`/`nohup`.

Server mode is auto-invoked over SSH by client mode. **You normally
only ever run `client`**.

Single-file distribution is a load-bearing design choice: users `curl`
one URL to one file and run it. The same file is `scp`'d to the
compute node and re-exec'd as `server`. No tarballs, no Python
package, no multi-file install.

## Status

**v2.0.0 released 2026-05-15.** The v1.x line is tagged at
`v1.0.0`, `v1.1.0`, and `v1.2.0`; legacy users with pinned URLs to
those tags keep working forever. v2.0 closes a 43-finding fresh-eyes
audit (10 critical, 11 high, 10 medium, 10 low, 3 info) covering
CSPO defenses, identity-handling correctness, privacy posture, and
multi-tool support — 33 of 43 findings closed (all CRIT + all HIGH
+ in-scope MED/LOW/INFO; 10 deferred to optional follow-up phases).
See [`PLAN.md`](PLAN.md) Section 4 (Milestones) for the full
phase-by-phase status and roadmap;
[`docs/AUDIT_2026-05-12.md`](docs/AUDIT_2026-05-12.md) is the audit
trail with each finding's resolution.

## Quick start

```sh
# 1. Download (pin to a release; tags are immutable):
curl -fsSL https://raw.githubusercontent.com/a-attia/argo-anywhere/v2.0.0/argo_anywhere.sh \
     -o argo_anywhere.sh && chmod +x argo_anywhere.sh

# 2. Run with explicit tool selection:
bash argo_anywhere.sh --cli-tool opencode client       # OpenCode
bash argo_anywhere.sh --cli-tool claudecode client     # Claude Code

# 3. In another terminal once the script reports ALL GREEN:
opencode    # (or `claude`, depending on which tool you picked)
```

Or invoke without `--cli-tool` to be prompted interactively:

```sh
bash argo_anywhere.sh client          # picker fires
bash argo_anywhere.sh setup           # always shows picker
bash argo_anywhere.sh list-tools      # see what `--cli-tool` accepts
```

To track `main` instead of a pinned release (gets the latest fixes,
but may move under your feet):

```sh
curl -fsSL https://raw.githubusercontent.com/a-attia/argo-anywhere/main/argo_anywhere.sh \
     -o argo_anywhere.sh
```

The first run prompts for your ANL (Argonne) username and asks you to
pick a compute node. Subsequent runs reuse the cached values.

### Currently supported `--cli-tool` values

- `opencode` — [OpenCode](https://opencode.ai/) (sst/opencode-style
  OpenAI-compatible client)
- `claudecode` — [Claude Code](https://docs.anthropic.com/en/docs/claude-code)
  (Anthropic CLI; uses `ANTHROPIC_BASE_URL` env)

More tools (aider, Cursor, generic OpenAI-compatible) planned for
post-v2.0 work.

## Prerequisites

**Laptop:**

- bash 3.2+ (macOS default works), `ssh`, `scp`, `curl`, `lsof`.
  macOS ships all of these. Minimal Linux installs (Alpine, slim Docker
  images) sometimes lack `lsof` — install it before running the script.
- SSH key-based auth to `logins.cels.anl.gov`. The script refuses to
  proceed and shows exact instructions if password auth is required.
- `jq`: **required** for `update-models`; **strongly recommended** for
  `status` (without it the model-count math is approximate and the
  `[m]erge` config-handling option is unavailable for JSON files).
- Optional: ANL VPN if you're off-site and your local network policy
  needs it.

**ANL compute node** (auto-handled by `server` mode):

- Python 3.10+
- `screen` or `tmux` (falls back to `nohup`)

## How `argo_anywhere.sh` is organised (subcommands)

| Subcommand | What it does |
|:---|:---|
| `client` (default) | Full laptop-side flow: install chosen CLI tool + write its config + tunnel + monitor. CLI tool selected via `--cli-tool <name>`; without it, the picker fires. |
| `setup` | Same as `client` but ALWAYS shows the picker, even if `--cli-tool` is set. Useful for one-off installations of a different tool from your usual. |
| `tunnel` | Same as `client` but does NOT install or configure any CLI tool; just brings up the tunnel + monitor. Useful for power users managing their own configs or keeping a tunnel alive while configuring multiple tools. |
| `server` | Auto-invoked on the ANL compute node by `client`. Also a documented standalone workflow ("leave a proxy on this node for any client to reach"). |
| `status` | Show local tunnel state + probe the proxy (ALL GREEN / DEGRADED / FAIL). |
| `update-models` | Refresh the OpenCode model list from the live `/v1/models` (OpenCode-specific today). |
| `stop` | Kill the local SSH tunnel. Does NOT touch the remote argo-proxy (see [`docs/LIMITATIONS.md`](docs/LIMITATIONS.md) "Single-instance constraint" for why). |
| `clean` | Remove every artifact this script created (local + remote, with risk-tiered prompts). |
| `list-tools` | Print the registry of supported `--cli-tool` values. |
| `help` | Long-form guide (paths, troubleshooting, customization). Keep open while learning prompts. |

Long help:

```sh
bash argo_anywhere.sh help | less
```

## What it writes where

**Laptop:**

| Path | Purpose |
|:---|:---|
| `~/.config/opencode/config.json` | OpenCode config (only when running the OpenCode flow) |
| `~/.claude/settings.json` *or* `./.claude/settings.local.json` | Claude Code config (only when running the Claude Code flow); see [Claude Code config scope](#claude-code-config-scope-project-vs-global) |
| `~/.config/argo_anywhere/user` | Cached ANL username |
| `~/.config/argo_anywhere/node` | Last-used compute node |
| `~/.config/argo_anywhere/ssh-fail-lock`, `~/.config/argo_anywhere/ssh-fail-lock-count` | SSH-failure-tracker state files (created only after lock fires); see [SSH failure protection](#ssh-failure-protection-cspo-defense) |
| `~/.ssh/sockets/argo-anywhere-<user>-<host>-<port>` | SSH multiplex master socket (Duo prompts only fire once per session) |

**ANL compute node** (after first run):

| Path | Purpose |
|:---|:---|
| `~/.argo_anywhere.sh` | Pushed copy of this script |
| `~/.argo_anywhere.server.log` | Server-mode bootstrap log |
| `~/argovenv/` | Python venv with argo-proxy installed |
| `~/.config/argoproxy/config.yaml` | argo-proxy config (port + user) |

See [`examples/`](./examples/) for sanitized templates of both
configs (laptop OpenCode + compute-node argo-proxy). The full
inventory of where prompt + identity data may persist (with
sensitivity classifications) lives in
[`docs/SECURITY.md`](docs/SECURITY.md) "What gets logged where".

## MFA / Duo handling

ANL CELS hosts use Duo. The script defaults to MFA-aware mode using
SSH `ControlMaster` connection multiplexing — **one Duo prompt per
session**, not per SSH call. The mux master is opened against the
chosen compute node (not the jump host, which on CELS is
shell-restricted).

To turn this off for non-Duo hosts: `--no-mfa` or
`ARGO_ANYWHERE_NO_MFA=1`.

## Running on a compute node

The default `client` flow assumes you are running the script from a
laptop *outside* the ANL network. If the script detects it is itself
running on an ANL compute node (the FQDN ends in `.cels.anl.gov`),
it adjusts:

- `--no-jump` and `--no-mfa` are auto-defaulted on (intra-site SSH
  needs neither).
- If the picked node is the local host, the SSH tunnel is **skipped
  entirely**: `client` invokes the server-mode bootstrap inline and
  the local OpenCode config is pointed at `http://localhost:<port>/v1`
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

Other clients on other machines can then point at this proxy via
their own SSH `-L` forward, or via
`bash argo_anywhere.sh --cli-tool <name> client --node compute-XX`
from those machines.

## Sharing a compute node with other users

Each user runs their own argo-proxy instance on the compute node —
the proxy is per-user, listening on `127.0.0.1:<port>`, and your
config + auth travel with it. Two users **can** share a compute
node, but they cannot share the same port: whoever binds first wins,
and the other gets refused. The single-instance constraint (one
argo-proxy per user per node) is documented in
[`docs/LIMITATIONS.md`](docs/LIMITATIONS.md).

To handle this gracefully, the script:

- **Detects port collisions before bootstrap.** Before `client` ssh's
  into the node to start argo-proxy, it probes `127.0.0.1:<port>` on
  the node and identifies the owner. If it's you, the script reuses
  AFTER positively verifying identity (v2.0 H5 fix; cfg_user must
  equal want_user, not just "not different"); if it's someone else,
  you're prompted:

  ```text
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

- **`--auto-port`** (or `ARGO_ANYWHERE_AUTO_PORT=1`) skips the prompt
  and auto-picks the next free port. After picking, the existing
  OpenCode config-migration prompt fires so you can choose to make the
  new port sticky (recommended) or use it for one run only.

- **`--port-range LO-HI`** overrides the default search range
  (defaults to `64742`-`64842`). Use it if your environment reserves
  a different range for ad-hoc services. The remote port-scan range
  is clamped to ≤200 ports per call (v2.0 H4 fix) regardless of how
  wide the requested range is.

- **Local self-collision** (you re-run `client` while a tunnel is
  already up from a previous invocation): the script detects the
  existing healthy tunnel and reuses it instead of erroring, then
  proceeds to client setup. This makes "I want to add another tool to
  my running tunnel" a natural workflow.

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

- **The on-node short-circuit** (running `client` directly on a
  compute node) recognizes load-balanced aliases by resolving the
  picked hostname to its IPs and intersecting with the local
  interface IPs — so picking `compute-01` while logged into
  `compute-386-01` (where the alias includes you) correctly skips
  the SSH tunnel.

## Claude Code config scope (project vs. global)

Claude Code reads its config from up to three files (more-specific
wins, but the `env` block is **replaced** wholesale across scopes —
Anthropic chose not to deep-merge it):

| File | Scope |
|:---|:---|
| `~/.claude/settings.json` | global (all projects, all directories) |
| `./.claude/settings.json` | per-project, **committed** (visible to collaborators) |
| `./.claude/settings.local.json` | per-project, **gitignored** by default |

The script writes EITHER the global file OR the project-local file
(never the committed file — that would force your collaborators to
also use this proxy). Since v2.0 the default is **project scope**,
checked in this order:

1. **`--scope project|global` flag (or `CLAUDECODE_SCOPE` env)** —
   explicit override wins.
2. **`~/.claude.json` exists** — Claude Code's auth state file,
   created by `claude auth login`. Its presence means you have a
   personal Anthropic subscription. Writing `ANTHROPIC_AUTH_TOKEN`
   to the global `~/.claude/settings.json` would shadow your OAuth
   token and break all non-proxy Claude Code usage → **project scope
   automatically**.
3. **`~/.claude/settings.json` already has an `env` block** — you (or
   another tool) put env vars in the global file; clobbering it would
   silently remove them → **project scope automatically**.
4. **None of the above** → **project scope** (changed in v2.0; was
   global pre-v2.0). The new default closes a silent-correctness
   regression: pre-v2.0 the script wrote to `~/.claude/settings.json`
   on fresh installs; if the user later ran `claude auth login`, the
   resulting OAuth token in `~/.claude.json` would silently take
   precedence over `ANTHROPIC_AUTH_TOKEN` in `settings.json`,
   neutralizing the proxy config without warning. Project scope is
   not affected by that precedence rule.

To force one or the other:

```sh
bash argo_anywhere.sh --cli-tool claudecode client --scope global
bash argo_anywhere.sh --cli-tool claudecode client --scope project
```

When the script writes the project scope, **you must run `claude`
from that same directory** to pick up the settings. The script prints
which directory at the end of the setup step.

If you opt back into `--scope global`, accept that you must NOT run
`claude auth login` from that machine — the OAuth precedence rule
will silently neutralize the proxy config the moment you do.

The script always preserves any non-Anthropic-Argo keys in the target
file's `env` block (and the file's other top-level keys: `model`,
`permissions`, `hooks`, etc.). It only owns `ANTHROPIC_BASE_URL` and
`ANTHROPIC_AUTH_TOKEN`. After writing, the script also prints a
**privacy warning** (v2.0 H7 fix) reminding you that the config now
contains your ANL username (used as the bearer token) and that the
file should be gitignored if your `~/.claude/` is tracked in a
dotfiles repo. See [`docs/SECURITY.md`](docs/SECURITY.md) for the
full privacy posture.

## Tunnel monitoring and reconnect

While `client` is in the foreground, a background loop polls
`http://localhost:<port>/health` every 15s and notifies you on
sustained failure. If the foreground SSH process exits but `/health`
still responds (common on macOS, where the multiplex master takes
over the forward and the foreground client exits immediately), the
script recognizes this as the no-op it is and stays quiet — the
master keeps the tunnel alive on its own.

If a real reconnect IS needed and the mux master is still alive, the
script attempts a silent reconnect (no Duo prompt). If reconnects
fire too rapidly (≥3 within 60s — typically a sign of a flapping
network or an OpenSSH quirk the script can't paper over), the script
escalates: pauses 5 minutes after each burst event, and **gives up
after 3 burst events** (~9 attempts spread over ~30 minutes of
degraded operation). At that point the script notifies you and the
loop exits; the SSH multiplex master remains alive, holding whatever
forward it had. You decide when to re-run `client`.

This burst-cap escalation was added in v2.0 (audit finding C7) to
prevent CSPO IP blocks from sustained reconnect loops; see
[SSH failure protection](#ssh-failure-protection-cspo-defense) for
the full CSPO defense and [`docs/SECURITY.md`](docs/SECURITY.md) for
the broader threat-model context.

## SSH failure protection (CSPO defense)

ANL/CELS networks are monitored for repeated failed SSH
authentications; too many failures from one IP trigger a CSPO (Cyber
Security Program Office) block on that IP. On a shared compute node
where many users share the same outbound IP, one user's broken SSH
agent can lock out everyone.

The script defends against this with three layered mechanisms:

1. **Persistent on-disk failure lock**. After 3 consecutive SSH
   authentication failures, the script writes
   `~/.config/argo_anywhere/ssh-fail-lock` and refuses all further
   SSH attempts. The lock persists across script restarts so
   re-running immediately doesn't silently accumulate more failures.
   First lock TTL: 30 minutes.

2. **Exponential backoff on repeat lock events**. Each successive
   lock doubles the TTL (30min → 60min → 120min → ... capped at 24h).
   The lock-event count persists to
   `~/.config/argo_anywhere/ssh-fail-lock-count`. A successful SSH
   attempt clears both files, returning you to fresh state — so
   well-behaved users are never permanently penalized.

3. **Wide tracker scope**. Every authenticating SSH call goes through
   the tracker: `ssh_reachable`, `ssh_mux_open`, the `scp` + bootstrap
   `ssh` in `remote_bootstrap`, `find_next_free_remote_port`,
   `probe_remote_port_owner`, the clean-mode `ssh`, AND (as of v2.0
   audit C7) the reconnect path in `monitor_tunnel_loop`.

Sample lock message:

```text
[err ] SSH has failed 3 consecutive times.
[err ] Disabling further SSH attempts to prevent CSPO from blocking your IP
[err ]   (and locking out everyone else sharing this compute node).
[err ]   Lock event #1; TTL 1800s (~30min).
[err ]   Lock will auto-expire after that, or delete it manually:
[err ]     rm ~/.config/argo_anywhere/ssh-fail-lock
[err ]
[err ] Common causes:
[err ]   * Closed laptop while SSH agent forwarding was active (kills the forwarded key)
[err ]   * Expired Kerberos tickets
[err ]   * SSH key removed from the agent ('ssh-add -D' earlier)
[err ]   * Wrong username (--user / ARGO_ANYWHERE_USER mismatch)
[err ]
[err ] Recovery:
[err ]   1. Verify your SSH works manually first:
[err ]        ssh -o ConnectTimeout=5 <user>@logins.cels.anl.gov true
[err ]      (one Duo prompt is fine; what we want is a clean exit.)
[err ]   2. If that fails, fix your auth (ssh-add, reconnect agent forwarding,
[err ]      renew tickets, correct the username, etc.).
[err ]   3. Re-run the script -- the lock will have expired by then, or
[err ]      delete it immediately.
```

**Recovery** is what the message says: verify SSH manually, fix
whatever's broken, then either wait for the lock to expire or
`rm ~/.config/argo_anywhere/ssh-fail-lock` to clear it immediately.

## Port policy

The OpenCode config's `baseURL` is the source of truth for the port.
The default port is **64742**. To override for one run:

```sh
bash argo_anywhere.sh --port 64999 --cli-tool opencode client
# Prompts whether to:
#   [m] migrate config to port 64999 (writes config.json),
#   [u] use 64999 for THIS run only (config keeps 64742),
#   [k] keep config's port (use 64742 instead),
#   [a] abort.
```

For non-`client` subcommands, a port mismatch prints a warning but
doesn't prompt (e.g. `bash argo_anywhere.sh --port 1234 status` warns
and runs against `:1234` instead of the config's port).

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

# Tear down only the local tunnel (remote argo-proxy survives)
bash argo_anywhere.sh stop

# Remove everything this script created (preview first)
bash argo_anywhere.sh clean --dry-run                # safe enumeration; no changes
bash argo_anywhere.sh clean                          # interactive (per-file prompts for risky items)
bash argo_anywhere.sh clean -y                       # non-interactive; deletes safe items, KEEPS risky configs
bash argo_anywhere.sh clean -y --purge-backups       # also drop accumulated .bak.* files
bash argo_anywhere.sh clean -y --purge               # delete EVERYTHING, including configs
```

`clean` separates artifacts into three risk tiers:

- **safe** (state dir, mux sockets, our SSH tunnel, the remote venv)
  — removed on confirmation.
- **risky** (`~/.config/opencode/config.json`,
  `~/.config/argoproxy/config.yaml`, and their `.bak.*` files) —
  per-file `[k]eep / [r]estore-from-backup / [d]elete /
  [b]ackups-only` prompt, or `--purge` / `--purge-backups` for the
  non-interactive paths.
- **never touched** — the OpenCode binary, the script itself, system
  tools.

For the full troubleshooting guide (env vars, security notes,
escape hatches), run `bash argo_anywhere.sh help`.

## Where to read more

| Doc | When to read |
|:----|:-------------|
| [`docs/UPGRADING.md`](docs/UPGRADING.md) | You're on `argo_opencode.sh` v1.x and want to upgrade to `argo_anywhere.sh` v2.0 |
| [`docs/SECURITY.md`](docs/SECURITY.md) | You're security-conscious or admin-recommending the script; want the threat model + privacy posture in one place |
| [`docs/LIMITATIONS.md`](docs/LIMITATIONS.md) | You're evaluating whether the script fits your use case; want to know the known limitations + their rationale upfront |
| [`docs/TESTING.md`](docs/TESTING.md) | You're a maintainer / contributor who made a non-trivial change and want to live-verify before tagging |
| [`docs/AUDIT_2026-05-12.md`](docs/AUDIT_2026-05-12.md) | You want the audit trail of every fix that landed in v2.0 (43 findings + STATUS resolutions) |
| [`PLAN.md`](PLAN.md) | You're a maintainer / co-author; plan-of-record + design decisions D-001..D-015 |
| [`AGENTS.md`](AGENTS.md) | You're an AI coding tool working on this codebase; project conventions + skill loading |

## Upgrading from `argo_opencode.sh` (pre-v2.0)

The canonical filename was `argo_opencode.sh` before v2.0. v2.0
renames to `argo_anywhere.sh` and removes the per-client symlinks
(`argo_opencode.sh`, `argo_claudecode.sh`) that v1.x distributed.
Per-tool selection is now via `--cli-tool <name>` (or the
interactive picker).

For the step-by-step migration (re-curl, update aliases, update env
vars, run client once, verify, optionally clean up old install) plus
the full list of behavior changes you may notice (verbose: false
default, claudecode default-to-project scope, stricter on-node
identity check, Ctrl+C exit summary, better error messages on SSH
failure lock), see [`docs/UPGRADING.md`](docs/UPGRADING.md).

Old curl URLs against the previous repo name (`a-attia/argo-opencode`)
**keep working forever** — GitHub auto-redirects them to the new name
(`a-attia/argo-anywhere`).

Pinning to old release tags also works:

```sh
# Still works (uses the v1.1.0 immutable tag):
curl -fsSL https://raw.githubusercontent.com/a-attia/argo-opencode/v1.1.0/argo_opencode.sh -o argo_opencode.sh
```

## Testing

[`docs/TESTING.md`](./docs/TESTING.md) is a step-by-step
live-verification guide for the `client` end-to-end path. Use it
after non-trivial edits or before tagging a release. It's structured
so you can follow it without external help (~5–10 min, one Duo
prompt).

For lighter smoke tests after edits:

```sh
bash -n argo_anywhere.sh                              # syntax
bash argo_anywhere.sh -h                              # short usage
bash argo_anywhere.sh status                          # exit 1 if no tunnel
bash argo_anywhere.sh clean --dry-run -y --local-only # safe enumeration
```

Per-phase test plans (used during the v2.0 development cycle) live in
`notes/`:

- [`notes/test_plan_phase1.md`](notes/test_plan_phase1.md) — passed
  2026-05-12 (D1+D2+D4 + legacy detection)
- [`notes/test_plan_phase2a.md`](notes/test_plan_phase2a.md) — passed
  2026-05-14 (P3 added + verified during the live test)
- [`notes/test_plan_phase2b.md`](notes/test_plan_phase2b.md) — passed
  2026-05-15 with three follow-up amendments (H5 yaml_scalar, P2
  setdefault, N1 scope-keyed; all amendments live-verified)
- [`notes/test_plan_phase2c3.md`](notes/test_plan_phase2c3.md) —
  passed 2026-05-15 with one follow-up amendment (L4+L5 incomplete
  dedup at 3 additional sites; landed mid-test) and two test-plan
  defects identified (Test 2b + Test 5b: synthetic SSH-failure-lock
  exercise via `status` doesn't trigger the lock-fired branch
  because `status` makes no SSH calls; workarounds applied)

## Contributing

This project follows the
[scicomp-research-skills](https://github.com/a-attia/scicomp-research-skills)
framework's conventions for agent-facing project files:

- [`AGENTS.md`](AGENTS.md) — canonical project conventions for AI
  coding tools. [`CLAUDE.md`](CLAUDE.md) is a symlink to it for
  Claude Code's discovery.
- [`PLAN.md`](PLAN.md) — plan-of-record (scope, architecture,
  milestones, design decisions log).
- [`docs/AUDIT_2026-05-12.md`](docs/AUDIT_2026-05-12.md) — active
  fresh-eyes audit (43 findings; the v2.0 release closes all of HIGH
  + CRIT + most of MED/LOW; see the audit doc for the per-finding
  STATUS resolutions).
- [`docs/LIMITATIONS.md`](docs/LIMITATIONS.md) — known limitations
  (read before adding features that bump up against the
  single-instance constraint or the bash 3.2 target).
- [`notes/agent_feedback.md`](notes/agent_feedback.md) — per-project
  feedback channel into the upstream `scicomp-research-skills`.
- [`CONTRIBUTORS.md`](CONTRIBUTORS.md) — primary author + AI
  collaborator acknowledgment + commit-trailer convention.

For the commit-message convention (Conventional Commits + the
`Co-Authored-By: Claude` trailer for AI-assisted commits), activate
the project's `.gitmessage` template after cloning:

```sh
git config --local commit.template .gitmessage
```

## Related projects

- [argo-proxy](https://github.com/Oaklight/argo-proxy) — the local
  proxy this script orchestrates. Authored + maintained by
  Peng Ding (Argonne CELS).
- [OpenCode](https://opencode.ai/) — one of the supported AI coding
  CLI tools.
- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) —
  the other supported AI coding CLI tool.
- [ANL AI4Dev notes](https://web.cels.anl.gov/~jacob/ai4dev.html) —
  the internal reference this script is built around.
- [scicomp-research-skills](https://github.com/a-attia/scicomp-research-skills)
  — the framework providing this project's agent conventions.

## Authors

- **Primary**: Ahmed Attia ([aattia@anl.gov](mailto:aattia@anl.gov))
- **AI collaborator**: Claude (Anthropic), used substantially during
  the v2.0 development cycle. Per-commit attribution via the
  `Co-Authored-By:` trailer; see [`CONTRIBUTORS.md`](CONTRIBUTORS.md)
  for the full acknowledgment + rationale.

---

*Created 2025 (project inception); rewritten 2026-05-14 to follow
the [scicomp-research-skills](https://github.com/a-attia/scicomp-research-skills)
human-facing-doc-authoring conventions; revised 2026-05-15 (Phase
2c+3) to reflect v2.0-ready-to-tag state, the H6 claudecode default
flip, the new `docs/UPGRADING.md` / `docs/SECURITY.md` /
`docs/LIMITATIONS.md` cross-links, and the closure of all 11
HIGH-severity audit items + 23 of 23 in-scope MED/LOW/INFO items.
Maintained by Ahmed Attia.*
