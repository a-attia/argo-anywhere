# argo-anywhere

> **For AI coding tools**: read [`AGENTS.md`](AGENTS.md) first (project conventions + skill loading); [`PLAN.md`](PLAN.md) is the plan-of-record. This README is for humans.

argo-anywhere lets Argonne (ANL) users run AI coding CLI tools —
[OpenCode](https://opencode.ai/),
[Claude Code](https://docs.anthropic.com/en/docs/claude-code), and
[aider](https://aider.chat/) — against
[argo-proxy](https://github.com/Oaklight/argo-proxy) on an ANL compute node,
**from any laptop on any network**, with **one Duo prompt per session**.

It is a `pip`-installable Python package that owns the runtime and drives a
single self-contained bash **engine** (vendored verbatim) which does the
orchestration: the SSH tunnel, the on-node `argo-proxy` bootstrap, and each
tool's config. On top of the command-line workflow it adds an optional
loopback-only **web UI** and a native **desktop app**, so you can connect,
monitor, and run tools from a browser window without touching a terminal.

> **New here, or upgrading?** Start with the
> **[install & migrate guide](docs/UPGRADING.md#start-here-install-and-migrate)** —
> one short path each for new users, v2.x upgraders, and v1.x upgraders.

## TL;DR

Two commands, using [`pipx`](https://pipx.pypa.io/) (a standard
installer for Python CLIs — isolated environment, still on your
`PATH`), get you the full experience — CLI, web UI, and a
double-clickable desktop app:

```sh
pipx install argo-anywhere         # everything: CLI, web UI, native app
argo-anywhere install-launcher     # + a double-clickable launcher (Desktop + Applications)
```

Plain `pip install argo-anywhere` works identically if you'd rather
share your Python environment. Use `--desktop` or `--app-bundle` on
`install-launcher` if you want just one artifact instead of both. No
extras to pick, no separate `[web]` step — everything a user needs is
installed by default.

Then double-click **argo-anywhere** in your Applications folder (macOS)
or app menu (Linux), or run `argo-anywhere client` from a terminal for
the CLI flow. See [Install](#install) and
[Web UI and desktop app](#web-ui-and-desktop-app) for what each command
does + the underlying pieces; see [Quick start](#quick-start) for the
CLI-only path.

## Contents

- [TL;DR](#tldr)
- [Heads up before you start](#heads-up-before-you-start)
- [Install](#install)
- [Quick start](#quick-start)
- [What this is](#what-this-is)
- [Status](#status)
- [Web UI and desktop app](#web-ui-and-desktop-app)
- [Supported AI CLI tools](#supported-ai-cli-tools)
- [Prerequisites](#prerequisites)
- [Known limitations (please read)](#known-limitations-please-read)
- [Subcommands](#subcommands)
- [What it writes where](#what-it-writes-where)
- [Running the raw engine (fork mode)](#running-the-raw-engine-fork-mode)
- [MFA / Duo handling](#mfa--duo-handling)
- [Running on a compute node](#running-on-a-compute-node)
- [Sharing a compute node with other users](#sharing-a-compute-node-with-other-users)
- [Claude Code config scope (project vs. global)](#claude-code-config-scope-project-vs-global)
- [Port policy](#port-policy)
- [Tunnel monitoring and reconnect](#tunnel-monitoring-and-reconnect)
- [SSH failure protection (CSPO defense)](#ssh-failure-protection-cspo-defense)
- [Common operations](#common-operations)
- [Where to read more](#where-to-read-more)
- [Upgrading](#upgrading)
- [Testing](#testing)
- [Contributing](#contributing)
- [Related projects](#related-projects)
- [Authors](#authors)

## Heads up before you start

Two things worth knowing in the first thirty seconds:

1. **Claude Code with `claude-opus-4-7` is currently broken** through the ANL
   Argo gateway: every request fails with `API returned an empty or malformed
   response (HTTP 200)`. The bug is upstream — Anthropic's Vertex deployment
   rejects `thinking.type.enabled` for opus-4-7, and Claude Code 2.1.x
   mis-parses the resulting SSE error event — not in argo-anywhere or
   argo-proxy. **Workaround**: run `claude --model claude-sonnet-4-6` (or any
   non-opus-4-7 model), or set `ANTHROPIC_MODEL=claude-sonnet-4-6` in the `env`
   block of your `~/.claude/settings.json`. Full diagnosis in
   [`docs/LIMITATIONS.md`](docs/LIMITATIONS.md) "Upstream stack".

2. **Install with `pipx` / `pip`.** As of v3.0.0, argo-anywhere is a Python
   package; `pipx install argo-anywhere` is the supported install path. The
   old "`curl` one `.sh` and `bash` it" route is retired as the primary route
   — though you can still inspect or fork the raw engine (see
   [Running the raw engine](#running-the-raw-engine-fork-mode)).

## Install

The [TL;DR](#tldr) above has the two commands for the full experience.
This section covers install alternatives, prerequisites, and pointers.

The recommended install is [`pipx`](https://pipx.pypa.io/) — it puts the
`argo-anywhere` command on your `PATH` in its own isolated environment:

```sh
pipx install argo-anywhere            # everything included -- CLI, web UI, native app
```

The FastAPI web server (`argo-anywhere web`), the native desktop window
(`argo-anywhere app`), and the `install-launcher` command are all bundled
in the default install — no extras to remember, no follow-up commands to
enable the UI.

Plain `pip install argo-anywhere` (ideally into a virtual environment) works
too. Requires Python 3.10+. See [Prerequisites](#prerequisites) for the SSH /
`jq` / laptop tooling the engine needs at run time.

> **Installing from `main` (unreleased)**:
> `pipx install 'argo-anywhere @ git+https://github.com/a-attia/argo-anywhere@main'`.
> See [Status](#status).

Coming from a v1.x / v2.x `.sh` install? See [Upgrading](#upgrading) for the
clean-cutover steps.

## Quick start

The all-in-one flow — open the channel, install and configure your tool, and
hold the health monitor — is a single command:

```sh
# Pick a tool; the first run prompts for your ANL username + a compute node:
argo-anywhere --cli-tool opencode client       # OpenCode
argo-anywhere --cli-tool claudecode client     # Claude Code
argo-anywhere --cli-tool aider client          # aider

# Then, in another terminal once it reports ALL GREEN:
opencode    # or `claude`, or `aider` — whichever you configured
```

When the channel is up, the client prints an **ALL GREEN** status box — tunnel
up, proxy healthy, models available:

![The argo-anywhere client status box reading ALL GREEN: tunnel up, proxy
healthy, models available, with connection / models / paths sections.](https://raw.githubusercontent.com/a-attia/argo-anywhere/main/assets/screenshots/client.png)

*(Scrubbed demo data — no real username or node.)*

If you configured Claude Code, remember the opus-4-7 workaround from
[Heads up](#heads-up-before-you-start): `claude --model claude-sonnet-4-6`.

Prefer the **split workflow**? The SSH channel is a *shared* local endpoint
that any number of tools can hit at once, so you can hold it in one window and
configure or run tools in others:

```sh
# Window 1 — bring up the shared channel and keep it alive:
argo-anywhere connect

# Window 2+ — point tools at the existing channel (no new tunnel, no new Duo):
argo-anywhere configure opencode aider   # configure several at once
argo-anywhere run aider                  # configure one, then launch it
```

Not sure which tool? Let the picker choose:

```sh
argo-anywhere client          # picker fires when --cli-tool is omitted
argo-anywhere setup           # always shows the picker
argo-anywhere list-tools      # list the accepted --cli-tool values
```

Subsequent runs reuse the cached username, node, and port from
`~/.config/argo_anywhere/`, so you rarely re-answer the prompts.

## What this is

argo-anywhere has two layers:

- The **Python package** is the runtime you install and the command you run
  (`argo-anywhere`). It also provides the web UI, the native app, and the
  install/uninstall lifecycle.
- The **bash engine** (`argo-anywhere.sh`) does all the orchestration. It is
  vendored inside the package **verbatim** and is the single source of truth
  for how the tunnel, bootstrap, and per-tool configs work. The package drives
  it; it never reimplements it.

The engine plays two roles:

- **Client mode (laptop)** — install the chosen AI CLI tool if needed, write
  its config, push the engine to a chosen ANL compute node, start `argo-proxy`
  there (inside `screen`, falling back to `tmux` then `nohup`), open the SSH
  tunnel, and monitor its health.
- **Server mode (ANL compute node)** — create a Python venv, install
  `argo-proxy`, write `~/.config/argoproxy/config.yaml`, and start
  `argo-proxy serve`.

You normally only run the client flow; server mode is auto-invoked over SSH.
Server mode is also a documented standalone workflow — see
[Running on a compute node](#running-on-a-compute-node).

**The engine stays a single self-contained `.sh` file** (design decision D-001,
which now governs the engine rather than the whole project). The package
vendors that one file, `scp`s it to the compute node, and re-exec's it there as
`server`. What changed at v3.0.0 (D-026) is the *distribution*: the installable
unit is now the package, not a `curl`ed script. A local HTTP-shim transport
layer was evaluated against the single-engine-file rule and rejected — see
[`docs/AUDIT_2026-05-18_argo-shim-comparison.md`](docs/AUDIT_2026-05-18_argo-shim-comparison.md)
Section 4 for the rationale.

## Status

**v3.2.1 is the current release** — `pipx install argo-anywhere` installs it.
The installable unit is the Python package (Model A; design decisions
D-026..D-030): the package owns the runtime, vendors the bash engine verbatim,
and ships the web UI and native app alongside the CLI. Releases are published
from CI via PyPI Trusted Publishing on their version tag.

Per-release detail lives in [`CHANGELOG.md`](CHANGELOG.md); the design decision
behind each change (D-001..D-034) lives in [`PLAN.md`](PLAN.md). This section
names the current release and points at those two documents rather than
restating them — it drifted four releases behind by trying to be a changelog
before one existed.

> **Heads up if you use a busy shared compute node** *(as of 2026-08-12)*.
> On a node where several people run argo-anywhere, v3.2.1 and earlier can
> attach to **another user's** argo-proxy: it answers the health check
> identically, so the tool reported success and your requests went out under
> their Argo identity. You would see either an Argo authentication error or,
> worse, nothing at all. The fixes are on `main` and not yet released — see
> the `Unreleased` section of [`CHANGELOG.md`](CHANGELOG.md). If you hit this
> before the next tag, choose `[n] next free port` when argo-anywhere reports
> a collision, and treat a green `status` on a shared node as unconfirmed.

Older tags — `v1.0.0`–`v1.2.0` and the v2.x line (`v2.0.0`, `v2.1.0`, `v2.2.0`,
the last `.sh`-era release) — still resolve, and legacy pinned `.sh` URLs keep
working.

The correctness story in one sentence: a 43-finding fresh-eyes audit
([`docs/AUDIT_2026-05-12.md`](docs/AUDIT_2026-05-12.md)) covering CSPO defenses,
identity-handling, privacy posture, and multi-tool support drove the v2 cycle,
and **42 of 43 findings are closed** (only L8, the unchecksummed `curl | bash`
from `claude.ai`, remains as a documented no-fix). For the phase-by-phase
history and the roadmap ahead, see [`PLAN.md`](PLAN.md) Section 4 (Milestones);
for user-facing behavior changes across releases, see
[`docs/UPGRADING.md`](docs/UPGRADING.md).

## Web UI and desktop app

<img src="https://raw.githubusercontent.com/a-attia/argo-anywhere/main/src/argo_anywhere/assets/icon.svg" alt="argo-anywhere app icon" width="104" align="right" />

Alongside the CLI, argo-anywhere ships a **loopback-only web UI** you can drive
from a browser or a native desktop window — Duo, the live monitor, and the
interactive prompts all work without a terminal. It binds `127.0.0.1` only and
runs only allowlisted engine verbs; see
[`docs/SECURITY.md`](docs/SECURITY.md) "Local web UI" for the threat model.

![The argo-anywhere web UI: the channel signal-path (laptop → node → argo-proxy)
showing ALL GREEN, the tunnels/sessions cards, and an embedded terminal.](https://raw.githubusercontent.com/a-attia/argo-anywhere/main/assets/screenshots/web.png)

*(The screenshot uses scrubbed demo data — no real username or credentials.)*

```sh
argo-anywhere app                 # open the web UI in a native desktop window
argo-anywhere web                 # ...or serve it to your browser
```

Both verbs work out of the box after `pipx install argo-anywhere` — no extras.
They are handled by the **package**; everything else passes straight through to
the engine (see [Subcommands](#subcommands)):

| Command | What it does |
|:--|:--|
| `argo-anywhere app` | Open the web UI in a native desktop window (browser fallback if the platform webview is unavailable). |
| `argo-anywhere web` | Serve the web UI to your browser (loopback-only). |
| `argo-anywhere install-launcher` | Install a double-clickable launcher (see below). |
| `argo-anywhere info [--json]` | Local status: package + engine versions, loopback listeners, and argo-anywhere's on-disk footprint (no ANL contact). |
| `argo-anywhere uninstall [...]` | Remove argo-anywhere's footprint (manifest-driven config restore + the launchers), then print the `pipx`/`pip` command to remove the package itself. |
| `argo-anywhere --print-script` | Emit the raw bash engine to stdout (inspect-and-fork). |
| `argo-anywhere --version` | Print the package version. |

Everything the package puts on disk is listed by `argo-anywhere info` and
removed by `argo-anywhere uninstall`. Your AI-tool configs are only ever read
and restored — never argo-anywhere's to delete.

### A double-clickable launcher (no terminal needed)

You don't have to type a command every time. After `pipx install
argo-anywhere`, one command installs a **persistent, double-clickable
launcher** that opens the web UI:

```sh
argo-anywhere install-launcher               # everything for your OS (default)
argo-anywhere install-launcher --desktop     # only the Desktop launcher
argo-anywhere install-launcher --app-bundle  # only the macOS ~/Applications/.app
```

With no flags it installs everything for your platform; the two flags let you
pick just one, and `--dest <dir>` places the artifacts elsewhere. What gets
created:

| Platform | Artifacts |
|:--|:--|
| **macOS** | `~/Desktop/argo-anywhere.command` and a real `~/Applications/argo-anywhere.app` bundle (with the constellation icon and a populated "About argo-anywhere" panel). |
| **Linux** | An application-menu entry (`~/.local/share/applications/argo-anywhere.desktop`) plus `~/Desktop/argo-anywhere.sh`. |

(argo-anywhere targets macOS + Linux — its transport is SSH + Duo to ANL — so
there is no Windows launcher.)

Each launcher **bakes the absolute path of the Python interpreter that installed
argo-anywhere**, because GUI/Finder launches run with a minimal `PATH` that
would not find the console script. Double-clicking runs `argo-anywhere app` — a
native window via pywebview when it's available, falling back to your browser
otherwise. The launchers are part of argo-anywhere's footprint: they show up in
`argo-anywhere info` and are removed by `argo-anywhere uninstall`.

### Launching from the web UI (v3.1.0+)

The launcher popover in the web UI has five fields; the last two are new in
v3.1.0 (design decision **D-031** in [`PLAN.md`](PLAN.md)):

- **command** — the engine verb (`run`, `configure`, `setup`, `connect`,
  `tunnel`). `client` is CLI-only (the web UI teaches the split-verb story).
- **cli tool** — which AI tool the verb targets (`opencode` / `claudecode` /
  `aider`), or `— default —` to fire the picker.
- **scope** — a dropdown (`— auto —` / `global` / `project`). Per-tool default
  when auto; `global` writes a config that applies anywhere, `project` writes
  it under the current working directory (target file differs per tool — see
  the [scope table](#supported-ai-cli-tools)).
- **working directory** *(new)* — an absolute path where the launched process
  starts (i.e. where `project` scope resolves against, and where the AI tool
  runs from). Pre-filled with the most-recently-used entry from
  `~/.argo_anywhere/web_state.json` (or `~` on first run); type or paste any
  absolute path, or click **Browse…** in the desktop app for a native folder
  picker. Missing directories trigger an explicit "Create + Launch"
  confirmation — never silent `mkdir`.
- **where to run** — `In-browser terminal` (routes to the Channel or Utility
  panel automatically per verb) OR a native terminal window. `run` always
  goes to a native terminal so closing the browser tab can't kill the tool.

The embedded-terminal area now shows **two panels side-by-side**:

- **Channel** (left) — persistent; owns `connect`; survives a browser tab
  close so the SSH master + tunnel keep running (no repeat Duo).
- **Utility** (right) — ephemeral; runs `configure` / `setup` / `tunnel`; free
  to relaunch without disturbing the Channel.

Both panels share the container-level `Terminal` / `Hide` toggle. Drag the
divider to resize; the position is persisted.

**Light/dark theme.** A top-bar toggle cycles `auto → dark → light → auto`.
`auto` follows the OS preference; explicit choices persist across sessions.
The two embedded terminals re-color on toggle.

**Forbid-list.** When scope is `project`, argo-anywhere refuses working
directories that would litter dotfiles in `$HOME` or touch system dirs
(`$HOME` exact; `/`, `/etc`, `/usr`, `/tmp`, `/var`, `/opt`, `/System`,
`/Library`, `/private`, ...). `--scope global` is unrestricted — beginners who
launch a client from `$HOME` just to chat with the agent take the happy path.

### Same guarantees from the CLI: `--cwd`

The engine gained a **`--cwd PATH`** flag in v3.1.0 so CLI users on remote
nodes (via `screen` / `tmux`) get identical behavior to web-UI users. It
changes to `PATH` before dispatching the verb, and — under `--scope project`
— applies the same forbid-list. Absolute path required; `~` is expanded.

```sh
argo-anywhere --cwd /path/to/my-project --scope project run --cli-tool opencode
```

## Supported AI CLI tools

Pass one to `--cli-tool` (or pick it interactively):

- **`opencode`** — [OpenCode](https://opencode.ai/), an OpenAI-compatible
  client. Supports `--scope project|global` (default `global`). Project scope
  writes `<git-root>/opencode.json` (or `<cwd>/opencode.json` outside a git
  repo); global writes `~/.config/opencode/config.json`.
- **`claudecode`** — [Claude Code](https://docs.anthropic.com/en/docs/claude-code)
  (uses `ANTHROPIC_BASE_URL`). Supports `--scope project|global`; default is
  **hybrid** per [PLAN.md D-017](PLAN.md) (project when `~/.claude.json` is
  present, for OAuth safety; global otherwise). See
  [Claude Code config scope](#claude-code-config-scope-project-vs-global).
  ⚠️ Subject to the opus-4-7 issue in [Heads up](#heads-up-before-you-start).
- **`aider`** — [aider](https://aider.chat/) via its OpenAI-compatible endpoint.
  Writes `~/.aider.conf.yml` plus a sibling `.aider.model.settings.yml` that
  disables `temperature` for reasoning / opus / gpt-5 models (which otherwise
  return an empty stream). Global vs. project per `--scope`.

**Roadmap.** Cursor is **not** planned as an integrated tool (upstream guidance
discourages routing it through an LLM gateway); the workaround is
`argo-anywhere tunnel` and pointing cursor's OpenAI-compatible endpoint at
`http://localhost:<port>/v1` manually. A `generic` OpenAI-compatible
`--cli-tool` is under consideration for a later release.

## Prerequisites

**Laptop:**

- **Python 3.10+** to install and run the package.
- **bash 3.2+**, `ssh`, `scp`, `curl`, `lsof` for the engine. macOS ships all
  of these; minimal Linux images (Alpine, slim Docker) sometimes lack `lsof` —
  install it first.
- **SSH key-based auth** to `logins.cels.anl.gov`. The engine refuses to
  proceed (with exact instructions) if password auth is required.
- **`jq`** — required for `update-models`; strongly recommended for `status`
  (without it the model-count math is approximate and the `[m]erge`
  config-handling option is unavailable for JSON files).
- Optional: ANL VPN if your local network policy needs it off-site.

**ANL compute node** (auto-handled by server mode): Python 3.10+, and `screen`
or `tmux` (falls back to `nohup`).

## Known limitations (please read)

The most common foot-guns are surfaced here; [`docs/LIMITATIONS.md`](docs/LIMITATIONS.md)
is the canonical reference with full rationale and roadmap for each.

### Upstream stack

- **Claude Code + `claude-opus-4-7`** ⚠️ — fails with "API returned an empty or
  malformed response (HTTP 200)". Root cause is Anthropic Vertex's per-model
  `thinking.type` validation plus Claude Code 2.1.x's SSE error-event parsing;
  not actionable at our layer. **Workaround**: `claude --model
  claude-sonnet-4-6`, or persist via `env.ANTHROPIC_MODEL=claude-sonnet-4-6` in
  `settings.json`. Auto-default fix queued for a later release.
- **Vertex HTTP 500 on large non-streaming requests** — already mitigated
  upstream by `argo-proxy` v3.x's `anthropic_stream_mode: force` default. Just
  keep the on-node proxy current: `argo-anywhere update argoproxy`. No action
  needed in normal use.

### Architectural

- **Single-instance constraint** — one `argo-proxy` per user per compute node;
  one SSH tunnel per local port. The engine refuses to overwrite someone else's
  argo-proxy and prompts on local re-runs. See
  [Sharing a compute node](#sharing-a-compute-node-with-other-users).
- **Load-balanced compute-node aliases can leak orphan argo-proxy processes**
  across physical hosts. See
  [the caveat](#caveat-load-balanced-node-aliases-and-orphan-argo-proxies).
- **The bash engine stays a single self-contained file** (D-001, engine-only
  now). We reject engine features that require splitting it — most notably a
  local HTTP-shim transport layer (see
  [`docs/AUDIT_2026-05-18_argo-shim-comparison.md`](docs/AUDIT_2026-05-18_argo-shim-comparison.md)
  Section 4).

### Operational

- **Two-layer testing.** The Python package (driver / CLI / web) has an
  automated `pytest` suite that runs with no ANL infra. The bash engine keeps
  live-only verification — mocking real SSH + Duo + argo-proxy on a real
  compute node costs more than it delivers — so its "tests" are smoke checks
  plus [`docs/TESTING.md`](docs/TESTING.md) for end-to-end live verification.
- **`bash 3.2+` target** (macOS default) limits the engine: no `mapfile`, no
  `declare -A`, no `${var,,}`. Inline Python heredocs absorb the gap for
  structured-data work.

## Subcommands

Everything below is an **engine verb**: run it as `argo-anywhere <verb>` and the
package passes it through to the engine on your real terminal (full-fidelity Duo
and prompts). The package-only verbs (`app`, `web`, `install-launcher`, `info`,
`uninstall`, `--print-script`, `--version`) are in
[Web UI and desktop app](#web-ui-and-desktop-app).

| Subcommand | What it does |
|:---|:---|
| `client` (default) | Full laptop-side flow: install the chosen CLI tool + write its config + tunnel + monitor. Tool via `--cli-tool <name>`; without it, the picker fires. |
| `setup` | Like `client` but ALWAYS shows the picker, even with `--cli-tool` set. Handy for a one-off install of a different tool. |
| `tunnel` | Like `client` but installs/configures nothing — just brings up the tunnel + monitor. For power users managing their own configs. |
| `connect` | Bring up the **shared channel** (SSH tunnel + remote argo-proxy) and hold it in the foreground monitor. The friendlier name for `tunnel`: run it in one window, then use `configure` / `run` in others. |
| `configure TOOL...` | Install + write config for **one or more** tools against an **existing** channel (e.g. `configure opencode aider`). Detects the channel via `/health`; fails with a hint if none is up (or pass `--ensure`). Does not block. |
| `run TOOL` | Configure **one** tool, then launch it (e.g. `run aider`). Brings the channel up if missing (prompts; `--ensure` / `-y` auto-confirm). |
| `server` | Auto-invoked on the compute node by `client`. Also a standalone workflow ("leave a proxy on this node for any client to reach"). |
| `status` | Show local tunnel state + probe the proxy (ALL GREEN / DEGRADED / FAIL). Reports cross-client port disagreements (D-021) as warnings without changing the exit code. |
| `update` | Lossless in-place upgrade of installed components (`argoproxy`, `opencode`, `claudecode`). `--all` updates everything; a positional list restricts it; bare `update` lists the registry. `--check` is report-only; `--yes` auto-confirms install prompts. After `update argoproxy` it auto-POSTs `/refresh` so the proxy pulls fresh models without a restart. *(The package itself is upgraded with `pipx upgrade argo-anywhere`, not this verb — see the note below.)* |
| `update-models` | Refresh a client's in-config model list from the live `/v1/models`. Tool-aware via `--cli-tool` (default `opencode`); only OpenCode enumerates models in config, so the others print a "not applicable" note and point at `list-models`. |
| `list-models` | Tabulate the models the proxy serves on `/v1/models` (read-only). Columns: `internal_name`, `id`, `provider`, `modalities`, `configured`. `--format tsv|json` and `--output FILE` for scripting. |
| `stop` | Kill the local SSH tunnel. Does NOT touch the remote argo-proxy (see [`docs/LIMITATIONS.md`](docs/LIMITATIONS.md) "Single-instance constraint"). |
| `clean` | Remove every artifact the engine created (local + remote, with risk-tiered prompts). |
| `list-tools` | Print the registry of supported `--cli-tool` values. |
| `help` | Long-form guide (paths, troubleshooting, customization). The package appends a note on its own extra verbs. |

> **`update` and the package.** Under the package, `argo-anywhere` upgrades
> itself through `pipx upgrade argo-anywhere` (or `pip`); the engine's own
> `update argo-anywhere` self-update is dormant and simply points you at pipx
> (design decision D-030a). The other components (`argoproxy`, `opencode`,
> `claudecode`) are upgraded by the `update` verb as usual.

The engine also has `install` / `uninstall` verbs for the canonical `.sh`
install, but under the package those are handled differently — see
[Running the raw engine](#running-the-raw-engine-fork-mode). To remove the
package itself, use `argo-anywhere uninstall` (which restores your configs) then
`pipx uninstall argo-anywhere`.

For the long help text:

```sh
argo-anywhere help | less
```

## What it writes where

The paths below assume the **package** install (the common case). Files under
`~/.argo_anywhere/` are written only in engine (fork) mode — see the note after
the tables and [Running the raw engine](#running-the-raw-engine-fork-mode).

**Laptop (package mode):**

| Path | Purpose |
|:---|:---|
| `~/.config/argo_anywhere/user` | Cached ANL username |
| `~/.config/argo_anywhere/node` | Last-used compute node |
| `~/.config/argo_anywhere/port` | Cached proxy port (transport-layer state per D-020) |
| `~/.config/argo_anywhere/manifest.json` | **Install manifest** (D-025): records, at first touch, whether each client config pre-existed (so `uninstall` can restore originals) and which tool binaries argo-anywhere installed (so it only removes its own) |
| `~/.config/argo_anywhere/ssh-fail-lock`, `…-count` | SSH-failure-tracker state (created only after a lock fires); see [SSH failure protection](#ssh-failure-protection-cspo-defense) |
| `~/.config/opencode/config.json` | OpenCode global config (global scope) |
| `<git-root>/opencode.json` or `<cwd>/opencode.json` | OpenCode project-scope config |
| `~/.claude/settings.json` *or* `./.claude/settings.local.json` | Claude Code config; see [Claude Code config scope](#claude-code-config-scope-project-vs-global) |
| `~/.aider.conf.yml` (+ `.aider.model.settings.yml`) *or* `<git-root>/.aider.conf.yml` | aider config; the sibling settings file disables `temperature` for reasoning/opus/gpt-5 models |
| `~/.ssh/sockets/argo-anywhere-<user>-<host>-<port>` | SSH multiplex master socket (Duo fires once per session) |
| `~/Desktop/argo-anywhere.command`, `~/Applications/argo-anywhere.app` (macOS) | Launchers, only if you ran `install-launcher` |

**ANL compute node (after first run):**

| Path | Purpose |
|:---|:---|
| `~/.argo-anywhere.sh` | Pushed copy of the engine |
| `~/.argo-anywhere.server.log` | Server-mode bootstrap log |
| `~/argovenv/` | Python venv with argo-proxy installed |
| `~/.config/argoproxy/config.yaml` | argo-proxy config (port + user; preserves any other keys you've added, e.g. `argo_base_url`, `anthropic_stream_mode`) |

> **Package vs. engine mode.** Under the package, argo-anywhere does **not**
> create a `~/.argo_anywhere/` canonical install — the package (pipx/pip) *is*
> the install (D-030a). If you instead run a forked engine `.sh` directly, it
> bootstraps a rustup-style canonical install at `~/.argo_anywhere/bin/` on
> first use; that path is covered in
> [Running the raw engine](#running-the-raw-engine-fork-mode).

See [`examples/`](./examples/) for sanitized config templates. The full
inventory of where prompt + identity data may persist (with sensitivity
classifications) is in [`docs/SECURITY.md`](docs/SECURITY.md) "What gets logged
where".

## Running the raw engine (fork mode)

The package is the supported way to install and run argo-anywhere. But because
the engine is a single self-contained `.sh`, you can also inspect it, audit it,
or run it without the package — the D-026/D-027 escape hatch:

```sh
argo-anywhere --print-script > argo-anywhere.sh   # emit the engine verbatim
bash argo-anywhere.sh --cli-tool opencode client  # run it directly
```

When you run a forked engine `.sh` directly (rather than through the package),
its **self-management machinery is active** — the parts the package deliberately
keeps dormant:

- On first `client` / `setup`, the engine **bootstraps a canonical install** at
  `~/.argo_anywhere/bin/` (a rustup/cargo-style PATH directory holding the
  script, `install` / `uninstall` wrappers, and a sourceable `env` helper), then
  prints one-shot instructions for adding `env` to your shell rc. Opt out with
  `ARGO_ANYWHERE_SKIP_BOOTSTRAP=1`.
- `argo-anywhere.sh install` materializes that canonical install explicitly;
  `argo-anywhere.sh uninstall` tears it down (tiered, manifest-driven config
  restore).
- `argo-anywhere.sh update argo-anywhere` self-updates the canonical copy from
  the latest GitHub release tag.

Under the package these three become no-ops that point you at `pipx` instead
(D-030a), because pipx already owns the runtime and a second self-updating copy
would drift from it (D-029). Forks predate the marker, so they behave exactly as
the pre-v3 `.sh` did. See [PLAN.md](PLAN.md) decisions D-023, D-025, D-029,
D-030 for the full design.

## MFA / Duo handling

ANL CELS hosts use Duo. The engine defaults to MFA-aware mode using SSH
`ControlMaster` connection multiplexing — **one Duo prompt per session**, not
per SSH call. The mux master is opened against the chosen compute node, not the
jump host (`logins.cels.anl.gov` is shell-restricted and rejects command
execution, so the master can't live there).

Socket paths use literal `%r-%h-%p` tokens (user-host-port) rather than `%C`
(the OpenSSH hash); `%C` proved fragile when `~/.ssh/config` rewrites jump-host
names, producing two different socket paths for one logical connection. See
[`AGENTS.md`](AGENTS.md) "MFA-aware by default" for the full rationale.

Turn this off for non-Duo hosts with `--no-mfa` or `ARGO_ANYWHERE_NO_MFA=1`.

### Using your own `~/.ssh/config` route (D-032, v3.2.0+)

If your `~/.ssh/config` already routes ANL compute nodes for you (an
alias with `HostName`, `User`, and its own on/off-site
`ProxyJump`/`ProxyCommand`), pass the alias to `--node` and argo-anywhere
"just works" — no `--user`, no `--no-jump`:

```sh
# ~/.ssh/config (already works for `ssh polaris-login`):
#   Host polaris-login
#       HostName compute-XX.cels.anl.gov
#       User <ANL-username>
#       Match exec "on-anl-network"   # your own on/off-site logic
#           ProxyCommand none
#       Match !exec "on-anl-network"
#           ProxyJump <ANL-username>@logins.cels.anl.gov

argo-anywhere --cli-tool opencode client --node polaris-login
```

Three things happen automatically:

1. **Alias acceptance** — `pick_node` recognises that the string
   resolves via `ssh -G` and emits a helpful `Note: 'polaris-login'
   is an ssh_config alias (resolves to compute-XX.cels.anl.gov);
   proceeding via ~/.ssh/config` instead of the generic "not in
   ANL_NODES" warn.
2. **Username inference** — `resolve_username` reads the alias's
   `User <name>` line and uses it, logging the source
   (`Using ANL username: <ANL-username> (source: ssh-config:polaris-login)`).
   Explicit `--user` / `ARGO_ANYWHERE_USER` still wins if you set it.
3. **ProxyJump deference** — `ssh_jump_args` detects the alias's own
   ProxyJump and **skips** its own `-J`, preventing both a redundant
   hop and the jump-loop error that would otherwise fail
   `ssh_reachable`.

Values inferred from ssh_config are **never persisted** to
`~/.config/argo_anywhere/user` — the cache remains write-only from
explicit actions (flag / prompt). Change your ssh_config later and the
inference tracks it.

### Custom jump host (`--jump-host`)

If you don't have a mature `~/.ssh/config` but need a jump host other
than the default `logins.cels.anl.gov`, use `--jump-host HOST` or set
`ARGO_ANYWHERE_JUMP_HOST=HOST`:

```sh
argo-anywhere --jump-host alt-jump.example.org --cli-tool opencode client
# ... or persistently in your shell rc:
export ARGO_ANYWHERE_JUMP_HOST=alt-jump.example.org
```

An empty `ARGO_ANYWHERE_JUMP_HOST=""` env is equivalent to `--no-jump`.
The CLI form `--jump-host ""` is a parse-error — use `--no-jump` for
the "skip jump host entirely" intent.

## Running on a compute node

The default `client` flow assumes you run from a laptop *outside* the ANL
network. If the engine detects it is itself running on an ANL compute node (the
FQDN ends in `.cels.anl.gov`), it adjusts:

- `--no-jump` and `--no-mfa` are auto-enabled (intra-site SSH needs neither).
- If the picked node is the local host, the SSH tunnel is **skipped entirely**:
  `client` invokes the server-mode bootstrap inline and points the local tool
  config at `http://localhost:<port>/v1` directly. argo-proxy keeps running
  under `screen`/`tmux`/`nohup` after `client` returns; use `clean` to stop it.

Override either default with `ARGO_ANYWHERE_NO_JUMP=0` or
`ARGO_ANYWHERE_NO_MFA=0` if your setup needs the slow path.

To leave argo-proxy running on a node with no client install or tunnel, use
`server` directly. Note the node won't have the package installed — run the
pushed engine copy there:

```sh
ssh <user>@compute-XX.cels.anl.gov
bash ~/.argo-anywhere.sh server   # starts argo-proxy under screen, then returns
```

Other machines can then reach that proxy via their own SSH `-L` forward, or via
`argo-anywhere --cli-tool <name> client --node compute-XX` from those machines.

## Sharing a compute node with other users

Each user runs their own argo-proxy on the node — it is per-user, listening on
`127.0.0.1:<port>`, with your config and auth traveling with it. Two users can
share a node but not a port: whoever binds first wins, and the other is refused.
The single-instance constraint is documented in
[`docs/LIMITATIONS.md`](docs/LIMITATIONS.md).

To handle this gracefully, the engine:

- **Detects port collisions before bootstrap.** Before SSHing in to start
  argo-proxy, it probes `127.0.0.1:<port>` on the node and identifies the owner.
  If it's you, it reuses the proxy *after positively verifying identity*
  (`cfg_user` must equal `want_user`); if it's someone else, argo-anywhere
  **moves to the first free port automatically** and tells you it did:

  ```text
  [warn] Port 64742 on compute-01 is held by another user's process
         (bind() refused it; unprivileged lsof can't name the owner).
  [argo-anywhere] Probing compute-01 for a free port in 64742-64842...
  [ ok ] Moved to free port 64743 (was 64742, held by another user).
  ```

  With `--no-auto-port` you get the interactive prompt instead:

  ```text
  [warn] Port 64742 on compute-01 is in use by another user
         (pid 12345, owned by 'alice'; you are 'jdoe').

         Two users can't share an argo-proxy on the same port; each needs
         their own. Options:
           [n] next free port  -- probe a range and use the first free one
           [p] pick a port    -- I'll type a number (1024-65535)
           [r] retry          -- maybe 'alice' just stopped; check again
           [a] abort
    Your choice [n/p/r/a, default=n]:
  ```

- **`--no-auto-port`** (or `ARGO_ANYWHERE_AUTO_PORT=0`) restores the prompt
  above. Auto-pick is the default as of v3.3.0 — it was opt-in while the probe
  could not see other users' ports, which is exactly when it was least
  trustworthy. Note the prompt needs a terminal, so `--no-auto-port` does
  nothing useful under `-y` or from the web UI.
- **Free ports are decided by binding them**, not by `lsof` — an unprivileged
  `lsof` cannot see another user's socket, so on a shared node it reports held
  ports as free. Either way the port-cache-migration prompt then lets you make
  the new port sticky or one-shot.
- **`--port-range LO-HI`** overrides the default search range (`64742`–`64842`).
  The remote scan is clamped to ≤200 ports per call regardless of the requested
  width.
- **Local self-collision** — re-running `client` while your own tunnel is
  already up: the engine detects the healthy tunnel and reuses it, then proceeds
  to client setup. This makes "add another tool to my running tunnel" a natural
  workflow.

### Caveat: load-balanced node aliases and orphan argo-proxies

The user-facing node names (`compute-01.cels.anl.gov`, etc.) are **DNS aliases**
that CELS resolves to one of several physical hosts (`compute-XXX-Y`). Two
consequences:

- **Successive runs may land on different physical hosts.** If today's
  `compute-01` resolves to `compute-386-01` and tomorrow's to `compute-742-03`,
  yesterday's argo-proxy keeps running on `compute-386-01` — orphaned but
  harmless. These accumulate; the engine can't reliably clean them up because it
  doesn't know the alias-to-physical mapping.
- **Periodic manual cleanup is the mitigation.** From a shell on the physical
  host you're on:

  ```sh
  ssh <user>@<physical-host> 'pkill -u <user> -f "argo-proxy serve"'
  ```

  Or `argo-anywhere clean` when you're done with a node — that handles the
  current physical host's argo-proxy via its screen session. Orphans on other
  physical hosts remain.
- **The on-node short-circuit** recognizes load-balanced aliases by resolving
  the picked hostname to its IPs and intersecting with the local interface IPs —
  so picking `compute-01` while logged into `compute-386-01` (which the alias
  includes) correctly skips the SSH tunnel.

## Claude Code config scope (project vs. global)

Claude Code reads its config from up to three files (more-specific wins, but the
`env` block is *replaced* wholesale across scopes — Anthropic chose not to
deep-merge it):

| File | Scope |
|:---|:---|
| `~/.claude/settings.json` | global (all projects, all directories) |
| `./.claude/settings.json` | per-project, **committed** (visible to collaborators) |
| `./.claude/settings.local.json` | per-project, **gitignored** by default |

argo-anywhere writes EITHER the global file OR the project-local file — never the
committed file (which would force collaborators onto your proxy). Since v2.2 the
default is **hybrid** (design decision D-017), chosen in this order:

1. **`--scope project|global`** (or `ARGO_ANYWHERE_SCOPE`; the old
   `CLAUDECODE_SCOPE` is deprecated but honored with a one-time WARN) — explicit
   override wins. Conflict detection still fires: you're prompted
   `[k]eep / [s]witch / [a]bort` if the chosen scope would shadow an existing
   config or OAuth state.
2. **`~/.claude.json` exists** — Claude Code's auth-state file, meaning you have
   a personal Anthropic subscription. Writing `ANTHROPIC_AUTH_TOKEN` to the
   global file would shadow your OAuth token and break non-proxy usage →
   **project scope automatically** (safety wins).
3. **`~/.claude/settings.json` already has an `env` block** — clobbering it would
   silently drop those vars → **project scope automatically**.
4. **None of the above** → **global scope** (convenient for fresh installs; no
   OAuth-precedence risk without a `~/.claude.json`). If you later run
   `claude auth login`, the next run hits branch 2 and switches to project scope,
   informing you via the `[k/s/a]` prompt.

This revises the pre-v2.2 "always project" default (audit recommendation H6,
closed by D-017): strictly safer, but it penalized the common fresh-install
case; the hybrid restores convenience while preserving the safety guarantees for
users with OAuth state.

To force one or the other:

```sh
argo-anywhere --cli-tool claudecode client --scope global
argo-anywhere --cli-tool claudecode client --scope project
```

When the project scope is written, **run `claude` from that same directory** to
pick it up; the engine prints which directory at the end of setup. If you opt
into `--scope global` *after* `~/.claude.json` exists, do NOT run
`claude auth login` from that machine — the OAuth precedence rule will silently
neutralize the proxy config. The conflict-detection prompt warns you about this.

argo-anywhere always preserves non-Argo keys in the target `env` block (and the
file's other top-level keys: `model`, `permissions`, `hooks`, …). It owns only
`ANTHROPIC_BASE_URL` and `ANTHROPIC_AUTH_TOKEN`. After writing, it prints a
privacy reminder that the config now contains your ANL username (used as the
bearer token) and should be gitignored if `~/.claude/` is in a dotfiles repo.
See [`docs/SECURITY.md`](docs/SECURITY.md) for the full privacy posture.

## Port policy

Pre-v2.2 the port was derived from the OpenCode config's `baseURL`. v2.2
promotes the port to **transport-layer state** owned by the engine (design
decision D-020): the source of truth is `~/.config/argo_anywhere/port`, and each
tool's config (`baseURL`, `ANTHROPIC_BASE_URL`) is a downstream rendering. This
closed audit finding M4 ("port resolution is OpenCode-specific in a multi-client
world").

Resolution precedence:

1. `--port N` flag (one-shot override)
2. `ARGO_ANYWHERE_PORT` env var (one-shot override)
3. `~/.config/argo_anywhere/port` cache (the source of truth)
4. First-run migration from an existing client config's baseURL
5. Built-in default `64742`

The cache is **write-through**: resolving a port via anything other than the
cache writes the new value back, so subsequent runs use it.

**Cross-client coherence (D-021)** sits on top: `status` passively reports when
an installed client config disagrees with the resolved port, and `client`
proactively prompts to reconcile at startup:

```sh
argo-anywhere --port 64999 --cli-tool opencode client
# Prompts whether to:
#   [m] migrate config to port 64999 (writes config file),
#   [u] use 64999 for THIS run only (config keeps its port),
#   [k] keep config's port (use it instead),
#   [a] abort.
```

Non-`client` subcommands warn on a mismatch but don't prompt (e.g.
`argo-anywhere --port 1234 status` warns and runs against `:1234`). `status`
reports multi-config disagreement non-fatally (the exit code is unchanged — it's
a pure health check).

## Tunnel monitoring and reconnect

While `client` is in the foreground, a background loop polls
`http://localhost:<port>/health` every 15s and notifies you on sustained
failure. If the foreground SSH process exits but `/health` still responds
(common on macOS, where the multiplex master takes over the forward and the
foreground client exits immediately), the engine recognizes the no-op and stays
quiet — the master keeps the tunnel alive.

If a real reconnect is needed and the mux master is still alive, the engine
attempts a silent reconnect (no Duo). If reconnects fire too rapidly (≥3 within
60s — typically a flapping network), it escalates: pauses 5 minutes after each
burst, and **gives up after 3 bursts** (~9 attempts over ~30 minutes). It then
notifies you and exits the loop; the mux master stays alive holding its forward,
and you decide when to re-run `client`.

This burst-cap escalation (audit finding C7) prevents CSPO IP blocks from
sustained reconnect loops; see [SSH failure protection](#ssh-failure-protection-cspo-defense)
and [`docs/SECURITY.md`](docs/SECURITY.md) for the threat-model context.

## SSH failure protection (CSPO defense)

ANL/CELS networks are monitored for repeated failed SSH authentications; too
many failures from one IP trigger a CSPO (Cyber Security Program Office) block on
that IP. On a shared compute node where many users share one outbound IP, one
user's broken SSH agent can lock out everyone.

The engine defends against this with three layered mechanisms (design decision
D-012):

1. **Persistent on-disk failure lock.** After 3 consecutive SSH auth failures,
   the engine writes `~/.config/argo_anywhere/ssh-fail-lock` and refuses further
   SSH attempts. The lock survives restarts, so re-running immediately doesn't
   silently accumulate more failures. First lock TTL: 30 minutes.
2. **Exponential backoff on repeat locks.** Each successive lock doubles the TTL
   (30m → 60m → 120m → … capped at 24h), tracked in `ssh-fail-lock-count`. A
   successful SSH clears both files, so well-behaved users are never permanently
   penalized.
3. **Wide tracker scope.** Every authenticating SSH call goes through the
   tracker — reachability check, mux open, the `scp` + bootstrap ssh, port
   probing, the clean-mode ssh, and the reconnect path in the monitor loop.

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
[err ]   3. Re-run -- the lock will have expired by then, or delete it immediately.
```

**Recovery** is what the message says: verify SSH manually, fix what's broken,
then wait for the lock to expire or `rm ~/.config/argo_anywhere/ssh-fail-lock`
to clear it immediately.

## Common operations

```sh
# Check what's happening (includes the D-021 cross-client coherence report)
argo-anywhere status

# See the full /v1/models list (raw JSON dump)
ARGO_ANYWHERE_SHOW_MODELS=1 argo-anywhere status

# Tabulate served models (read-only; cross-references the OpenCode config)
argo-anywhere list-models                              # pretty text table
argo-anywhere list-models --include-embeddings         # include embedding rows
argo-anywhere list-models --format tsv > models.tsv    # script-friendly
argo-anywhere list-models --format json | jq '.[] | select(.provider=="claude")'

# Refresh the OpenCode model list from the live proxy
argo-anywhere update-models                  # interactive: prompts per orphan
argo-anywhere update-models --keep-orphans   # add new; keep stale entries
argo-anywhere update-models --drop-orphans   # add new; drop stale entries

# Upgrade installed components in place (lossless; preserves configs + venv)
argo-anywhere update --all                   # argoproxy + opencode + claudecode
argo-anywhere update argoproxy               # just the on-node proxy (+ auto /refresh)
argo-anywhere update --check --all           # report-only: installed vs latest
# (the package itself: pipx upgrade argo-anywhere)

# Tear down only the local tunnel (remote argo-proxy survives)
argo-anywhere stop

# Remove everything the engine created (preview first)
argo-anywhere clean --dry-run                # safe enumeration; no changes
argo-anywhere clean                          # interactive (per-file prompts for risky items)
argo-anywhere clean -y                       # non-interactive; deletes safe items, KEEPS configs
argo-anywhere clean -y --purge-backups       # also drop accumulated .bak.* files
argo-anywhere clean -y --purge               # delete EVERYTHING, including configs
```

`clean` separates artifacts into three risk tiers:

- **safe** (state dir incl. port cache, mux sockets, our SSH tunnel, the remote
  venv) — removed on confirmation.
- **risky** (`~/.config/opencode/config.json`, `~/.config/argoproxy/config.yaml`,
  and their `.bak.*` files) — per-file `[k]eep / [r]estore-from-backup /
  [d]elete / [b]ackups-only` prompt, or `--purge` / `--purge-backups` for the
  non-interactive paths.
- **never touched** — tool binaries, the engine itself, system tools.

To remove **argo-anywhere the package** (as opposed to a channel's artifacts),
use `argo-anywhere uninstall` (restores your client configs via the manifest,
sweeps the launchers) then `pipx uninstall argo-anywhere`.

For the full troubleshooting guide (env vars, security notes, escape hatches),
run `argo-anywhere help`.

## Where to read more

| Doc | When to read |
|:----|:-------------|
| [`docs/UPGRADING.md`](docs/UPGRADING.md) | Upgrading from a v1.x/v2.x `.sh` install, or between releases; covers v1 → v2 → the v2 → v3 hard cutover. |
| [`docs/SECURITY.md`](docs/SECURITY.md) | Threat model + privacy posture (incl. the local web UI); for security-conscious users and ANL admins. |
| [`docs/LIMITATIONS.md`](docs/LIMITATIONS.md) | Known limitations + rationale before you adopt; includes the "Upstream stack" section (opus-4-7 etc.). |
| [`docs/TESTING.md`](docs/TESTING.md) | Maintainers/contributors: live-verify the `client` path before tagging. |
| [`docs/AUDIT_2026-05-12.md`](docs/AUDIT_2026-05-12.md) | The fix trail across v2.0 → v2.2 (43 findings; 42 closed). |
| [`docs/AUDIT_2026-05-18_argo-shim-comparison.md`](docs/AUDIT_2026-05-18_argo-shim-comparison.md) | Comparative audit vs. `argo-shim`, the Phase-C-rejection rationale, slide-ready summary. |
| [`PLAN.md`](PLAN.md) | Maintainers/co-authors: plan-of-record + design decisions D-001..D-034 + roadmap. |
| [`AGENTS.md`](AGENTS.md) | AI coding tools working on this codebase: conventions + skill loading. |

## Upgrading

The canonical filename was `argo_opencode.sh` before v2.0; v2.0 renamed it to
`argo-anywhere` and replaced the per-client symlinks with `--cli-tool <name>`
(or the picker).

**v3.0.0 is a clean break** (design decision D-027): the supported install is
now `pipx install argo-anywhere`, and the single-`.sh` `curl` route is retired as
primary (the raw engine is still reachable via `argo-anywhere --print-script`).
The v2 → v3 hard-cutover steps — uninstall the old `.sh` install, then
`pipx install` — are in
[`docs/UPGRADING.md`](docs/UPGRADING.md#v2x--v300-the-python-package-rebuild).

Cumulative behavior changes through v2.2 are documented in
[`docs/UPGRADING.md`](docs/UPGRADING.md): env-var renames (`ARGO_OPENCODE_*` →
`ARGO_ANYWHERE_*`), the `CLAUDECODE_SCOPE` → `ARGO_ANYWHERE_SCOPE` deprecation
(still honored with a WARN), the port cache + cross-client coherence prompts, and
the D-017 claudecode hybrid default. The engine also auto-detects v1.x state on
first run and prints exact cleanup commands.

Old `curl` URLs against the previous repo name (`a-attia/argo-opencode`) keep
working forever — GitHub auto-redirects them — and pinning old release tags still
works.

## Testing

[`docs/TESTING.md`](./docs/TESTING.md) is a step-by-step live-verification guide
for the `client` end-to-end path (~5–10 min, one Duo prompt); use it after
non-trivial changes or before tagging a release.

The Python package has an automated `pytest` suite (no ANL infra needed) — see
[Contributing](#contributing). For the engine, lighter smoke checks after edits
(these operate on the raw `.sh`, so they're contributor-facing):

```sh
bash -n argo-anywhere.sh                              # syntax
argo-anywhere -h                                      # short usage
argo-anywhere status                                  # exit 1 if no tunnel
argo-anywhere clean --dry-run -y --local-only         # safe enumeration
```

Per-phase and live-test plans (used across the development cycle) are indexed in
[`notes/README.md`](notes/README.md).

## Contributing

This project follows the
[scicomp-research-skills](https://github.com/a-attia/scicomp-research-skills)
framework's conventions.

Set up a development environment and run the checks:

```sh
pip install -e '.[dev]'    # package + pytest + httpx + ruff + rich + playwright (or: uv pip install -e '.[dev]')
pytest -q                  # the package test suite (no ANL infra)
ruff check src tests       # lint
```

Key project files:

- [`AGENTS.md`](AGENTS.md) — canonical project conventions for AI coding tools.
  [`CLAUDE.md`](CLAUDE.md) is a symlink to it for Claude Code's discovery.
- [`PLAN.md`](PLAN.md) — plan-of-record (scope, architecture, milestones,
  design decisions D-001..D-034).
- [`docs/AUDIT_2026-05-12.md`](docs/AUDIT_2026-05-12.md) — active fresh-eyes
  audit (43 findings; 42 closed). New closures append a STATUS block in place.
- [`docs/AUDIT_2026-05-18_argo-shim-comparison.md`](docs/AUDIT_2026-05-18_argo-shim-comparison.md)
  — comparative audit; SH-* items and their per-release dispositions.
- [`docs/LIMITATIONS.md`](docs/LIMITATIONS.md) — known limitations (read before
  adding features that bump the single-instance constraint or the bash 3.2
  target).
- [`notes/agent_feedback.md`](notes/agent_feedback.md) — per-project feedback
  channel into the upstream framework.
- [`CONTRIBUTORS.md`](CONTRIBUTORS.md) — authorship + AI-collaborator
  acknowledgment + commit-trailer convention.

For the commit convention (Conventional Commits + the `Co-Authored-By: Claude`
trailer for AI-assisted commits), activate the project's template after cloning:

```sh
git config --local commit.template .gitmessage
```

## Related projects

- [argo-proxy](https://github.com/Oaklight/argo-proxy) — the on-node proxy this
  project orchestrates. Authored + maintained by Peng Ding (Argonne CELS).
- **`argo-shim`** — an alternative project solving the same problem from the
  opposite layer of the stack (a Python local HTTP proxy on the laptop). See
  [`docs/AUDIT_2026-05-18_argo-shim-comparison.md`](docs/AUDIT_2026-05-18_argo-shim-comparison.md)
  for the full comparison.
- [OpenCode](https://opencode.ai/), [Claude Code](https://docs.anthropic.com/en/docs/claude-code),
  [aider](https://aider.chat/) — the supported AI coding CLI tools.
- [ANL AI4Dev notes](https://web.cels.anl.gov/~jacob/ai4dev.html) — the internal
  reference this project is built around.
- [scicomp-research-skills](https://github.com/a-attia/scicomp-research-skills)
  — the framework providing this project's agent conventions.

## Authors

- **Primary**: Ahmed Attia ([aattia@anl.gov](mailto:aattia@anl.gov))
- **AI collaborator**: Claude (Anthropic), used substantially across the v2.0 →
  v3.0 development cycle. Per-commit attribution via the `Co-Authored-By:`
  trailer; see [`CONTRIBUTORS.md`](CONTRIBUTORS.md).

---

*Created 2025 (project inception); rewritten 2026-05-14 to follow the
[scicomp-research-skills](https://github.com/a-attia/scicomp-research-skills)
human-facing-doc-authoring conventions; revised through v2.2.0 (Phase 4).
Rewritten 2026-07-12 for v3.0.0: re-grounded in the Python package as it exists
in code (package-first, engine as a vendored/forkable component), added the
Install and "Running the raw engine" sections, and corrected the `.sh`-era
descriptions of bootstrap, self-update, and on-disk paths. Maintained by Ahmed
Attia.*
