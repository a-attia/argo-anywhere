# argo-anywhere / AGENTS.md

This project loads shared workflow conventions from the
[scicomp-research-skills](https://github.com/a-attia/scicomp-research-skills)
repository. Before doing anything else, the consuming agent should:

1. Verify `~/.scicomp-research-skills/AGENTS.md` exists and is no more
   than 30 days stale (per its modification time). If stale, print a
   reminder suggesting `~/.scicomp-research-skills/bin/refresh.sh` and
   proceed anyway.
2. Read `~/.scicomp-research-skills/AGENTS.md`.
3. Read any skill files referenced below from
   `~/.scicomp-research-skills/skills/<name>/SKILL.md`.
4. Then read the rest of THIS file.
5. Then read `PLAN.md` for the active plan-of-record.

## Skills to load for this project

This project is a `software-script-collection` (one large bash script
plus supporting docs) — not a `software-library`. Load lightly:

- `~/.scicomp-research-skills/skills/agent-resource-discipline/SKILL.md`
  — **always load**. First-action / last-action protocols give the
  agent persistent memory across sessions via this project's indices
  (`PLAN.md` status, `notes/README.md`, `notes/agent_feedback.md`,
  `docs/AUDIT_2026-05-12.md`).
- `~/.scicomp-research-skills/skills/human-facing-doc-authoring/SKILL.md`
  — **load whenever authoring or revising a human-facing doc**:
  `README.md`, `PLAN.md`, `notes/agent_feedback.md`,
  `docs/TESTING.md`, `notes/test_plan_phase*.md`.

### Available but not loaded by default

The following skills are available and load on demand for specific
non-routine tasks; do NOT load them at session start unless the user
asks for the matching task.

- `~/.scicomp-research-skills/skills/research-software-engineering/SKILL.md`
  — **on-demand only** for this project. The skill is oriented toward
  numerical-software libraries (MMS / convergence-rate tests / "paper
  tests" guard / `experiments/<run-id>/` discipline). This project is a
  bash orchestrator with no numerical computation, no library API, and
  no experiments directory. Load if the user explicitly asks about
  testing strategy or numerical-correctness review of any future
  Python heredoc that grows non-trivial.
- `~/.scicomp-research-skills/skills/literature-survey/SKILL.md`
  — only load if the user is adding algorithmic references this project
  cites (none today; the project's "references" are upstream tool
  documentation, not academic literature).
- `~/.scicomp-research-skills/skills/research-paper-writing/SKILL.md`
  — N/A; project doesn't support a paper.
- `~/.scicomp-research-skills/skills/project-onboarding/SKILL.md`
  — only relevant for adopting the framework or migrating to a
  different framework structure; was used during the initial onboarding
  on 2026-05-14 and won't recur in routine work.

The two always-load skills (`agent-resource-discipline` +
`human-facing-doc-authoring`) compose freely; this is the steady-state
loading set for normal sessions.

---

## Project facts

- **Name**: argo-anywhere
- **Nature**: research-software (CLI orchestrator); single-file bash
  script with inline Python heredocs for structured-data work
- **Status**: v2.1.0 tagged + released (2026-05-15) + Phase 2e
  cosmetic I2 closure landed (2026-05-15; `_LOGGING` ->
  `_ARGO_ANYWHERE_REEXEC` rename for clarity). Phase 2d
  defensive-hardening landed earlier same day (3 batches; 7
  audit closures M6-M10 + L6 + L10) + live-tested PASS on first
  try with zero mid-test code amendments. Project state: 41 of
  43 audit findings closed. Only Phase 4 (multi-tool: aider /
  cursor / generic; closes M4) remains as deferred-by-trigger
  work; L8 (curl|bash claude.ai) is documented no-fix.
- **Plan-of-record**: [`PLAN.md`](PLAN.md) (read after AGENTS.md)
- **Public API surface**: CLI subcommands (`client`, `setup`, `tunnel`,
  `server`, `status`, `stop`, `update-models`, `clean`, `list-tools`,
  `help`) + flags (`--cli-tool`, `--user`, `--node`, `--port`, ...);
  see PLAN.md Section 2 for the table
- **Primary downstream consumers**: ANL users running AI coding CLI
  tools (OpenCode, Claude Code today; aider/cursor/generic planned)
  against the ANL Argo gateway from any laptop on any network
- **Current release**: v2.1.0 (tagged 2026-05-15)
- **Repo**: <https://github.com/a-attia/argo-anywhere>

### Human-facing doc map

For human-facing project docs (audience split per universal conventions
Section 6.4):

| Doc | Audience | When to read |
|:----|:---------|:-------------|
| [`README.md`](README.md) | New + returning humans | Project overview; quick start |
| [`PLAN.md`](PLAN.md) | Maintainer + co-authors | Plan-of-record; design decisions D-001..D-016 |
| [`docs/UPGRADING.md`](docs/UPGRADING.md) | v1.x users upgrading | What changes for them at v2.0 |
| [`docs/SECURITY.md`](docs/SECURITY.md) | Security-conscious users + ANL admins | Threat model, CSPO defenses, privacy posture |
| [`docs/LIMITATIONS.md`](docs/LIMITATIONS.md) | Prospective users + contributors | Known limitations + rationale |
| [`docs/TESTING.md`](docs/TESTING.md) | Maintainers + contributors | Live-verification guide (real SSH + Duo + node) |
| [`docs/AUDIT_2026-05-12.md`](docs/AUDIT_2026-05-12.md) | Maintainers | 43-finding audit + STATUS resolutions |
| [`docs/AUDIT_2026-05_pre-rebuild.md`](docs/AUDIT_2026-05_pre-rebuild.md) | Maintainers | Archived pre-rebuild audit (provenance only) |
| [`CONTRIBUTORS.md`](CONTRIBUTORS.md) | Contributors | Authorship + AI co-author trailer convention |
| [`notes/agent_feedback.md`](notes/agent_feedback.md) | Maintainer + upstream skills repo | Per-project feedback queued for upstream roll-up |
| [`notes/test_plan_phase*.md`](notes/) | Maintainer | Per-phase live-test plans (historical artifact once phase complete) |

## Project-specific overrides

(Anything that differs from the universal conventions in
`~/.scicomp-research-skills/AGENTS.md` Section 6.)

### Override: single-file architecture; no `src/`/`tests/`/`experiments/` (decided 2025 inception; reaffirmed 2026-05-14)

**Framework rule** (`~/.scicomp-research-skills/templates/software-skeleton/`
expected layout): software projects ship with `src/<library_name>/`,
`tests/`, `experiments/<run-id>/`, `figures/<topic>/`.

**Project rule**: single self-contained bash script `argo_anywhere.sh`
at the repo root. No package layout, no test suite directory, no
experiments directory.

**Rationale**: single-file distribution is a load-bearing UX property.
Users `curl one .sh -o argo_anywhere.sh && bash it`. The same file is
`scp`'d to the compute node and re-exec'd as `server`. Splitting
breaks both flows. Documented as design decision D-001 in PLAN.md.

**Scope**: project-wide. No file in this project belongs in `src/` or
`tests/`. The "tests" are smoke checks documented inline in this
AGENTS.md and a live-verification guide in `docs/TESTING.md`.

### Override: no automated test suite; no CI (decided 2025 inception)

**Framework rule** (research-software-engineering skill): substantial
projects have CI + automated tests covering numerical claims +
behavioral correctness.

**Project rule**: smoke tests run manually after non-trivial edits;
end-to-end live verification on real ANL infrastructure
(`docs/TESTING.md`); no GitHub Actions workflow.

**Rationale**: the script is testable only end-to-end against real
SSH + real Duo MFA + real argo-proxy on a real compute node.
Mocking that stack is more complex than the value it provides; a
mocked CI would test the mocks, not the script.

**Scope**: project-wide.

### Override: bash + inline Python heredoc language policy (decided 2025 inception)

**Framework rule** (research-software-engineering skill, MULTI-LANGUAGE.md):
software projects pick ONE primary language (Python / Julia / C++ /
Rust / Fortran / ...) and follow that language's conventions.

**Project rule**: bash primary; Python heredocs (`python3 - <<'PYEOF' ...
PYEOF`) as escape hatch for structured-data work (JSON/YAML/TOML
merging that preserves user-owned keys).

**Rationale**: bash is the right tool for the orchestration work
(SSH multiplexing, screen/tmux/nohup launchers, port collision
prompts). Python is the right tool for JSON/YAML merging. Inline
heredocs preserve the single-file distribution while letting Python
do what Python does well. Documented as design decision D-002 in
PLAN.md.

**Scope**: project-wide. Targets bash 3.2+ (macOS default) so no
bash-4 features (no `${var,,}`, no `mapfile`, no `declare -A`, no
`printf -v` with format reuse).

### Override: AI co-authorship trailer = adopted (matches framework default; documented for explicitness)

**Framework rule** (root `~/.scicomp-research-skills/AGENTS.md`
Section 6.3): AI co-authorship attribution default = ON; substantive
AI-assisted commits include
`Co-Authored-By: Claude <noreply@anthropic.com>` trailer.

**Project state**: ✅ adopted. Documented in [`CONTRIBUTORS.md`](CONTRIBUTORS.md).
First commit using the trailer: `f312232` (the rename + co-author
adoption commit, 2026-05-13). All subsequent commits include the
trailer. A `.gitmessage` template (added 2026-05-14) pre-populates
the trailer for `git commit` invocations.

**Scope**: every commit with substantive AI assistance. Pure
mechanical commits (e.g. dependency bumps, lockfile refreshes) MAY
omit; the user's discretion.

## Project-specific facts the agent should not have to derive

These are load-bearing facts the agent benefits from knowing without
reading PLAN.md cover-to-cover or grepping the script.

### Distribution + architecture overview

The script is published at <https://github.com/a-attia/argo-anywhere>.
Users `curl` either `main` or a pinned release tag (e.g. `v1.2.0`);
both URL forms documented in `README.md` and the script's own header.

The script is one file (~5800 lines as of v2.0) divided into 25
numbered sections (search for `# SECTION:` to navigate). Three
conceptual layers — **transport** (SSH multiplex + tunnel + monitor),
**per-tool** (`setup_<tool>_cli_tool` functions), **server-side
bootstrap** (Python venv + argo-proxy launch). See PLAN.md Section 3
for the architecture diagram.

### Subcommand reference

`client` (default), `setup`, `tunnel`, `server`, `status`, `stop`,
`update-models`, `clean`, `list-tools`, `help`.

- **`client`** — all-in-one workflow: SSH tunnel + chosen-CLI-tool
  install + config write + monitor. `scp`s the file to a chosen
  compute node and re-execs it as `server` over SSH. The "chosen
  CLI tool" is selected via `--cli-tool <name>` (or interactive
  picker if omitted).
- **`setup`** — thin alias for `client` that ALWAYS shows the picker,
  even if `--cli-tool` is set. Useful for one-off installations of a
  different tool from the user's usual.
- **`tunnel`** — `client` minus the per-tool install/config: open the
  SSH forward (or local proxy on a compute node) and block in the
  foreground monitor loop. Useful for power users managing their own
  tool configs or keeping a tunnel alive while configuring multiple
  tools in other terminals.
- **`server`** — runs argo-proxy locally. Auto-invoked by `client`
  over SSH on the picked compute node, but also a documented
  standalone workflow ("leave a proxy on this node for any tool to
  reach"). Resolves identity from env, then
  `~/.config/argoproxy/config.yaml`, then cache; prompts for
  confirmation when no env was supplied (skip with `-y`).

### MFA-aware by default

ANL CELS hosts use Duo. The script uses SSH `ControlMaster` connection
multiplexing so Duo prompts only fire once per session. Sockets land
in `~/.ssh/sockets/argo-anywhere-<user>-<host>-<port>` (literal
`%r-%h-%p` tokens, not the `%C` hash — `%C` proved fragile when
`~/.ssh/config` rewrites jump-host names, producing two different
socket paths for what was logically the same connection). Disable MFA
mode for non-Duo hosts with `--no-mfa`.

The script also detects + cleans up legacy v1.x-prefixed sockets
(`argo-opencode-*`) for users upgrading from the pre-v2.0 era.

### Jump-host shell restriction

`logins.cels.anl.gov` is jump-only — its login shell rejects all
command execution ("This account is currently not available"). The
script therefore opens the multiplex master against the picked compute
NODE, not the jump host. `mode_client` reorders pick-node before
preflight under MFA. **Do not** try to
`ssh -O ... <user>@logins.cels.anl.gov true` — it always fails.

### Mux master holds tunnels alive

Under `ControlMaster=auto`, a foreground `ssh -N -L` may exit
immediately after the forward request is acknowledged by the master;
the master then owns the forward. Health checks must verify
`/health`, not just the foreground pid. `open_tunnel_and_monitor`
handles this: if the foreground ssh dies but `/health` still answers,
declare success and let the master own the forward. The monitor and
parent wait-loop both handle empty `SSH_TUNNEL_PID`. (Design decision
D-003 in PLAN.md.)

### Port policy

The OpenCode config's `baseURL` is the source of truth. `--port N` and
`ARGO_ANYWHERE_PORT` are one-shot overrides; if they disagree with the
config, `mode_client` asks `[m]igrate / [u]se-once / [k]eep / [a]bort`.
Non-client subcommands warn on mismatch but don't prompt.

### Server-side port + config validation

After `handle_config_file` for `~/.config/argoproxy/config.yaml`,
`mode_server` reads back the `port:` line and refuses to launch
argo-proxy if it disagrees with `$PROXY_PORT` (else argo-proxy binds
the wrong port and the client polls in vain). The same writer also
preserves unknown YAML keys via a Python+PyYAML merge: only
`config_version`, `user`, `host`, `port` are owned by the script;
everything else (`argo_url`, `argo_embedding_url`,
`concurrent_downloads`, etc.) survives a `[b]ackup+overwrite` choice.

### Server-mode logging trick

The early `bash "$0" server | tee -a $LOG; exit ${PIPESTATUS[0]}`
pattern must **not** be prefixed with `exec` — `exec CMD | tee` only
`exec`s the left side, the rest of `mode_server` then runs a second
time, double-bootstrapping. (Design decision D-004 in PLAN.md.)

### Env vars are namespaced

Canonical names:

- `ARGO_ANYWHERE_USER`
- `ARGO_ANYWHERE_NODE`
- `ARGO_ANYWHERE_PORT`
- `ARGO_ANYWHERE_NO_JUMP`
- `ARGO_ANYWHERE_NO_MFA`
- `ARGO_ANYWHERE_FORCE_REINSTALL`
- `ARGO_ANYWHERE_SHOW_MODELS`
- `ARGO_ANYWHERE_CONTROL_PERSIST`
- `ARGO_ANYWHERE_AUTO_PORT`
- `ARGO_ANYWHERE_PORT_RANGE`
- `ARGO_ANYWHERE_VERBOSE_SERVER`
- `ARGO_ANYWHERE_KEEP_ORPHANS`
- `ARGO_ANYWHERE_DROP_ORPHANS`
- `ARGO_BOX_STYLE`

Two generations of legacy names still work with a one-time deprecation
warning each (snapshotted **before** the script's own config block
reassigns them, so promotion sees the inherited values):

- **Pre-namespace** (oldest): `ANL_USERNAME`, `PROXY_PORT`,
  `SHOW_MODELS`.
- **Pre-rename** (v1.x era; argo_opencode.sh): every
  `ARGO_OPENCODE_<X>` is honored as a legacy alias of
  `ARGO_ANYWHERE_<X>`. Users with `export ARGO_OPENCODE_USER=...`
  in their shell rc files see one WARN per stale var on the first run
  after upgrade; the script otherwise behaves identically.

The Argonne username is distinct from the laptop's `$USER` — never
substitute one for the other. The writers always read
`ARGO_ANYWHERE_USER` (with `ANL_USERNAME` as legacy fallback).
`mode_server`'s pid-owner check uses `id -un` (OS-level, correct) but
the config-user check uses `ARGO_ANYWHERE_USER` (Argonne-level,
correct).

### `set -euo pipefail` is on; SIGPIPE-resilient cmd substitution required

Avoid `[ test ] && cmd` at function/branch top level. When the test
fails, `set -e` doesn't kill (the man page exempts `&&`/`||` chains),
but bash 3.2 (macOS default) has parser quirks with quoted heredocs
inside `$()` under `set -u` that have bitten this script before.

Use `if/then/fi` and write multi-line remote scripts via temp files
(`mktemp` + `ssh ... < file`), **never**
`var="$(cat <<'EOS' ... EOS)"`.

**SIGPIPE in cmd substitution** (audit finding P1; design decision
D-011 in PLAN.md): the pattern `local x; x="$(cmd | head -n1)"` under
`set -euo pipefail` triggers `set -e` when `head -n1` closes stdin and
the upstream command (lsof, awk) gets SIGPIPE. **Always wrap such
patterns**:

```bash
x="$( { ... | head -n1; } || true )"
```

The `{ ...; } || true` swallows SIGPIPE so the assignment can't trip
set -e. New code review must check every `$(... | ...)` cmd
substitution for this class.

### Audit "main-mode" functions before calling them in-process

A recurring class of bug: a function originally written as the
script's **main mode** (the script's job IS to run this then exit)
gets refactored to ALSO be callable as one step of a longer in-process
flow. Main-mode-only assumptions silently break the in-process
caller. (Design decision D-005 in PLAN.md.)

Three concrete instances hit historically (commits `df10abe`,
`ed71864`, `32601c3`):

- **`$()` capture of a function that mutates globals.** Command
  substitution runs the function in a subshell; mutations to
  script-level globals (`ANL_USERNAME`, `ARGO_ANYWHERE_USER`,
  `PROXY_PORT`, env-var auto-defaults, etc.) evaporate when the
  subshell exits. Parent then sees the global as unbound and trips
  `set -u`. Fix: don't capture; use a designated `_RETURN_*` global to
  convey the "return value."
- **`exit` inside a function that may now be called in-process.**
  `mode_server`'s tee-then-exit pattern was correct when `mode_server`
  was the only thing the script did. It became wrong when
  `_client_common_setup`'s on-node short-circuit started invoking
  `mode_server` as one step of a longer flow. Fix: gate the `exit` on
  a "called in-process" flag and `return` the same status code in the
  in-process branch.
- **Assumptions about shell state outside the script.** Each AI
  tool's installer drops the binary at a known location and updates
  `~/.bashrc` PATH. The post-install `command -v <tool>` correctly
  returns non-zero because the running script's PATH doesn't include
  the new directory; the user's *next* shell would have it but ours
  doesn't. Fix: prepend the well-known install location to PATH for
  the rest of the script invocation.

The meta-rule: **when a function that was originally a "main mode"
gets called in-process from somewhere else, audit it for `exit`,
`exec`, `$()` capture by callers, and any implicit assumption that
"the user's next shell" or "the next process" will pick up state
changes we made.** None survive an in-process call. The fix usually
involves either (a) adding a flag like `_FOO_INPROC=1` that the
function checks before exiting, or (b) factoring the function into
"do the work" + "wrap with the main-mode-only behavior."

### Multi-CLI-tool architecture: per-tool API contract

The script supports several AI CLI tools (OpenCode + Claude Code
today; aider, cursor, generic planned). Each tool defines:

- **`setup_<name>_cli_tool()`** — top-level entry point invoked by the
  dispatcher (`do_post_tunnel_for_cli_tool`). MUST be idempotent.
  Calls `ensure_<name>_installed`, then
  `handle_config_file <path> <desc> write_<name>_config`. Reads
  `PROXY_PORT`, `ANL_USERNAME`, `ARGO_ANYWHERE_USER` from script-level
  globals.
- **`ensure_<name>_installed()`** — install-or-detect the tool binary.
  After install, prepend any well-known install location to `PATH` so
  the rest of the running script sees the binary (the upstream
  installer's rc-file PATH update doesn't reach the running shell).
- **`write_<name>_config(dest)`** — produce a fresh config at `dest`.
  Invoked by `handle_config_file`, so the signature is fixed at
  one-arg destination path; everything else flows in via globals. Use
  a Python heredoc for non-trivial JSON/YAML/TOML merging (preserves
  user-owned keys; we only own the few keys we need).
- **`<name>` row in the `CLI_TOOLS_AVAILABLE` array** (display order
  + picker label).
- **A `<name>` arm in `do_post_tunnel_for_cli_tool`** that calls
  `setup_<name>_cli_tool`, then `gather_summary; render_summary`,
  then prints any tool-specific tail messages ("Run: claude" etc.).

Optional but conventional:

- A **`<name>_pick_scope()`** function if the tool has multiple config
  locations (project vs global, etc.). Sets globals
  `_<NAME>_SCOPE_PATH` and `_<NAME>_SCOPE_NAME` for the writer to
  consume — DO NOT capture via `$()` (the function may need to prompt
  the user; subshell capture would eat the prompt). See
  `claudecode_pick_scope` for the reference implementation.

### Single-instance constraint (one argo-proxy + one tunnel per user per node)

The script assumes each user runs **one** argo-proxy per compute node
and **one** SSH tunnel per local port. Concrete pinch points:

- `SCREEN_SESSION="argovproxy"` is a single global constant.
  argo-proxy is always started inside the screen/tmux session named
  `argovproxy` — no per-port suffix.
- `~/.config/argoproxy/config.yaml` is the single argo-proxy config
  file on the node. Its `port:` line is mutated on each invocation.
- `local_tunnel_status` checks "is something on this port?" — can't
  tell which destination the tunnel targets.

Implications:

- A user who runs `client` twice with **different ports on the same
  node** would silently destroy the first run's argo-proxy (the second
  run's bootstrap kills the existing screen session that happens to
  share the name). The detect-and-warn check in `mode_server`
  (introduced in audit fix G1) catches this and asks before killing.
- A user who runs `client` twice with **same port to different nodes**
  would silently reuse the first tunnel (which targets the first
  node). The detect-and-warn check in `ensure_or_reuse_tunnel` (also
  G1) catches this and refuses.
- `status` / `stop` / `clean` operate on a single `PROXY_PORT` value.
  No "show me ALL my tunnels" view exists.

Lifting the constraint is documented as out-of-scope for v2.0 but the
touchpoints are listed in PLAN.md Open Questions.

### `clean` subcommand risk tiers

Three risk tiers:

- **safe items** (state dir, mux sockets, tunnel, remote venv) deleted
  on global confirmation;
- **risky items** (OpenCode/argo-proxy configs and their `.bak.*`
  backups) get a per-file prompt;
- **non-interactive flags** for risky items: `--purge` opts into
  deletion of files + backups; `--purge-backups` only kills backups.
  Both flags skip the per-file prompt even without `-y` (the user
  explicitly opted into a destructive action).

`--dry-run` previews; `--local-only` skips remote.

### Smoke tests

After non-trivial edits:

```sh
bash -n argo_anywhere.sh                              # syntax
bash argo_anywhere.sh -h                              # short usage
bash argo_anywhere.sh help | head -50                 # long help renders
bash argo_anywhere.sh status                          # exit 1 if no tunnel
bash argo_anywhere.sh clean --dry-run -y --local-only # safe enumeration
```

The `status` summary's "ALL GREEN" branch only fires when the
script's tunnel is actually up — keep one running while you work if
you want full coverage.

For end-to-end verification (real SSH, real Duo prompt, real
argo-proxy on a compute node), follow [`docs/TESTING.md`](docs/TESTING.md).
Run before tagging a release and after any change to the prompt flow,
env-var handling, or SSH option logic.

## Citation + archival policy

- **CITATION.cff**: not yet (queued for first DOI release at v2.0.0
  tag; see PLAN.md Open Questions).
- **Zenodo handshake**: not yet (queued).
- **DOI**: none yet.
- **Software Heritage SWHID**: N/A.

---

*Created 2026-05-14 by Ahmed Attia (with substantial AI assistance
from Claude per [`CONTRIBUTORS.md`](CONTRIBUTORS.md)). Bootstrapped
from
[`scicomp-research-skills/templates/software-skeleton/`](https://github.com/a-attia/scicomp-research-skills/tree/main/templates/software-skeleton)
on 2026-05-14, replacing the project's prior 457-line ad-hoc AGENTS.md
(content migrated per the project-onboarding skill's content-check
discipline; full migration plan recorded in
`notes/agent_feedback.md` entry 1).*
