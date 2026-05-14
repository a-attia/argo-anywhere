# Plan-of-Record: argo-anywhere

**Project name**: `argo-anywhere`. **Scope**: an end-to-end orchestrator
that lets Argonne (ANL) users run AI coding CLI tools (OpenCode, Claude
Code, future aider/cursor/generic) on their laptop against
[argo-proxy](https://github.com/Oaklight/argo-proxy) on an ANL compute
node, regardless of whether the laptop is on the ANL network or not.
**Audience**: ANL users with valid Argonne domain accounts who want AI
coding assistance without copy-pasting between a browser and an editor.
**Status**: pre-v2.0 (active development); v1.x line on
`a-attia/argo-anywhere`.
**Repo**: <https://github.com/a-attia/argo-anywhere>.
**License**: MIT (matches the repo's existing convention).

> **Doc status**: Living plan-of-record. Date-stamp every revision.
> Items marked `[VERIFY]` need user confirmation or independent
> lookup before use.

---

## Headline goal

**Claim.** A single self-contained bash script (`argo_anywhere.sh`)
delivers a one-command experience for Argonne users to use an AI coding
CLI tool against the lab's [Argo gateway](https://www.anl.gov/article/how-generative-artificial-intelligence-is-changing-work-at-a-national-laboratory),
end-to-end, from any laptop on any network. Where the prior art is a
two-page setup guide that the user follows manually with multiple SSH
sessions, the AI tool's own config file edits, and a fragile manual
SSH tunnel (per the published [AI4Dev guide](https://web.cels.anl.gov/~jacob/ai4dev.html)),
this script reduces it to: `curl ...; bash ... --cli-tool opencode client`.

**Positioning relative to alternatives.**

- **Manual setup** (the AI4Dev guide's path): works but requires
  ~5 SSH sessions + manual edits to the AI tool's config + manual
  tunnel + manual recovery from any failure mode. Fine for one-time
  setup; tedious for daily use; brittle.
- **`argo-shim`** (a Python alternative for similar use case): different
  design lane (per-user-port, deterministic naming, single-purpose).
  This script chose bash + single-port-default + multi-tool-per-tunnel
  for different trade-offs (single-file `curl` distribution being the
  most load-bearing).

**Why this should help.** The pain this addresses is repeated SSH
plumbing every time a user wants to use a different AI tool, on a
different node, after a network blip, after a proxy crash. Mechanism
of action: orchestrate the SSH multiplexing + tunnel + bootstrap +
client config + health monitoring + reconnect once, in one place,
hardened against the failure modes the user will actually hit.

**Demonstration.** From a clean laptop, off the ANL network:

```sh
curl -fsSL https://raw.githubusercontent.com/a-attia/argo-anywhere/main/argo_anywhere.sh \
     -o argo_anywhere.sh
bash argo_anywhere.sh --cli-tool opencode client
# ... one Duo prompt, ~30s of bootstrap output ...
# In another terminal:
opencode    # talks to Argo via the local tunnel; ALL GREEN status box visible
```

---

## 1. Scope and non-scope

### In scope

- **Single-file distribution**: one bash script users `curl` and run.
  No tarballs, no multi-file installs.
- **AI-CLI-tool-agnostic transport**: the SSH + tunnel + bootstrap
  layer is shared; per-tool concerns are contained in pluggable
  `setup_<tool>_cli_tool` functions.
- **Cross-network**: works whether the laptop is on the ANL network,
  off it, or on the compute node itself. SSH multiplexing handles the
  Duo MFA prompt (one prompt per session, not per call).
- **Defensive against CSPO IP block**: every SSH attempt goes through
  an attempt tracker with persistent on-disk lock + exponential
  backoff. The script's job is to never trigger an IP block under any
  user behavior.
- **Lightweight testing**: smoke tests + a documented live-verification
  guide (`docs/TESTING.md`). No mocked SSH/Duo/argo-proxy harness.

### Out of scope

- **Package layout** (`pyproject.toml`, `setup.py`, etc.): single-file
  distribution is load-bearing UX; splitting breaks both the curl
  and the `scp`-to-compute-node flows.
- **Test scaffolding / CI**: the script is testable only end-to-end
  against real ANL infrastructure; mocking SSH+Duo+argo-proxy is more
  complex than the value provides.
- **New runtime dependencies**: stock `bash` + `ssh` + `scp` + `curl` +
  `lsof` on the laptop, and stock Python 3.10+ on the compute node.
  `jq` is optional. PyYAML is required only on the compute-node side
  (already a transitive argo-proxy dep).
- **Multi-instance support**: one argo-proxy per user per node; one
  tunnel per local port. Users wanting parallel proxies on the same
  user/node use a different port via `--port`.
- **Replacing the AI tool**: this script orchestrates argo-proxy +
  the AI tool's own config; it does not extend or replace the AI tool
  itself.

The boundary matters. A script that tries to also be a credential
manager / a CSPO compliance auditor / a multi-tunnel dashboard ends up
doing none of them well.

---

## 2. Public API surface (target)

The "API" of this project is its CLI subcommand vocabulary, not a
library API. Stable since v2.0:

| Subcommand | Purpose | Status |
|:---|:---|:---|
| `client` | Full laptop-side flow: install AI tool + config + tunnel + monitor | stable |
| `setup` | Like `client` but always shows the picker, even with `--cli-tool` | stable |
| `tunnel` | Tunnel only (no AI-tool install/config); useful for managing multiple tools manually | stable |
| `server` | Run argo-proxy on a compute node (auto-invoked by `client` over SSH; standalone path also documented) | stable |
| `status` | Probe the tunnel + proxy health; ALL GREEN / DEGRADED / FAIL | stable |
| `update-models` | Refresh OpenCode's model list from `/v1/models` (OpenCode-specific today) | stable |
| `stop` | Kill the local SSH tunnel (does NOT touch the remote proxy) | stable |
| `clean` | Remove every artifact this script created (local + remote, with confirmation tiers) | stable |
| `list-tools` | Print supported `--cli-tool` values | stable |
| `help` | Long-form guide (paths, troubleshooting, customization) | stable |

Flag surface (all optional):

| Flag | Purpose |
|:---|:---|
| `--cli-tool NAME` | Pick the AI CLI tool (required for `client`/`setup` to skip the picker) |
| `--user NAME` | ANL username override |
| `--node HOST` | Compute-node override |
| `--port N` | Port override (one-shot; offers config migration prompt) |
| `--no-jump` | Skip the jump host (direct SSH to compute node) |
| `--no-mfa` | Disable Duo-aware mode (BatchMode SSH testing) |
| `--probe-nodes` | Probe each ANL_NODE for reachability before showing picker |
| `--auto-port` | Auto-pick the next free port instead of prompting on collision |
| `--port-range LO-HI` | Override the auto-port range |
| `--scope project\|global` | Per-tool config scope (currently consumed by Claude Code) |
| `--force-reinstall` | Wipe the server-side venv + rebuild from scratch |
| `--keep-orphans` / `--drop-orphans` | `update-models` orphan handling |
| `--dry-run` / `--local-only` / `-y` / `--purge` / `--purge-backups` | `clean` modifiers |

Design principles in use:

- **Subcommand-first; flags second.** Subcommands name what to do;
  flags refine.
- **Required flag where ambiguity exists.** `--cli-tool` is required
  for `client`/`setup` (no auto-detection from filename in v2.0+); the
  picker covers users who haven't decided.
- **Warn-but-proceed on irrelevant flags.** Passing `--cli-tool` to
  `status` warns and continues; doesn't error out (avoids breaking
  shell aliases like `alias argo='bash ... --cli-tool opencode'`).
- **Same flag, same meaning across subcommands** where possible.
  `--port` means the same thing whether passed to `client` or `clean`.

---

## 3. Architecture

The script is one file (~5800 lines as of v2.0) divided into 25
numbered sections (search for `# SECTION:` to navigate). Conceptually
three layers:

```text
argo_anywhere.sh
├── Transport layer (~2500 lines; shared across all CLI tools)
│   ├── SSH multiplex setup (Duo-aware; ControlMaster=auto)
│   ├── Jump-host / direct-connect routing
│   ├── SSH attempt tracker (CSPO defense; persistent on-disk lock)
│   ├── Tunnel open + foreground monitor + reconnect loop
│   └── Local + remote port-collision detection
├── Per-CLI-tool layer (~600 lines; one block per supported tool)
│   ├── setup_opencode_cli_tool()    -- OpenCode (sst/opencode-style)
│   ├── setup_claudecode_cli_tool()  -- Claude Code (Anthropic CLI)
│   └── setup_<future>_cli_tool()    -- aider, cursor, generic OpenAI-compatible
└── Server-side bootstrap (~500 lines; runs on the ANL compute node)
    ├── Python venv + argo-proxy install/upgrade
    ├── Config writing (preserves user's argo-proxy custom keys via PyYAML merge)
    ├── Listener detection + reuse-vs-start decision
    └── screen / tmux / nohup launcher selection
```

Per-tool API contract — every supported CLI tool defines four
functions + one registry row + one dispatcher arm. See the
`AGENTS.md` "Project-specific facts" section ("Multi-client
distribution: the per-tool API contract") for the full spec.

---

## 4. Milestones

The active development cycle is v2.0 (audit-driven hardening + adoption
of the scicomp-research-skills framework). Phase status as of
2026-05-14:

| Phase | Goal | Status |
|:---|:---|:---|
| **v1.0–v1.2** | First audited release through the per-client-symlink era | done (tagged) |
| **Phase 0 (v2.0 baseline)** | Pre-rewrite snapshot; audit doc | done |
| **Phase 1 (v2.0)** | D1+D2+D4: remove symlinks, add `--cli-tool`, rename internals to `*anywhere*` | done |
| **Phase 2a (v2.0 critical)** | Audit fixes C1, C4, C5, C7 + the P1 SIGPIPE hotfix | done; **awaiting live-test** |
| **Phase 2b (v2.0 high)** | Audit fixes H1–H9 + P2 (verbose-default privacy) + N1 (Ctrl+C exit hint) | queued (gates on Phase 2a green light) |
| **Phase 2c (v2.0 medium/low)** | M1–M10 + L1–L10 + I1–I3 (~23 items) | queued |
| **Phase 3 (v2.0 docs)** | UPGRADING.md + SECURITY.md + LIMITATIONS.md + final doc rewrites | queued |
| **v2.0.0 tag** | After all above + final live-test | queued |
| **Phase 4 (post-v2.0)** | Add aider, cursor, generic OpenAI-compatible CLI tools | future |

Milestones are **shippable**, not commit-sized. Each phase ends with a
live-test gate before the next starts, per the post-CSPO discipline
adopted in the audit.

---

## 5. Numerical correctness plan

**N/A.** This is a bash orchestrator with inline Python heredocs for
structured-data work. There are no numerical claims to verify.

The closest analog is **CSPO defense correctness**: the SSH attempt
tracker, lock TTL, and exponential backoff together guarantee an upper
bound on SSH attempts per unit time. The audit doc
(`docs/AUDIT_2026-05-12.md`) verifies this with rate calculations
showing post-Phase-2a rates stay below typical CSPO thresholds.

---

## 6. Reproducibility infrastructure

| Asset | Status / Location |
|:---|:---|
| **Lockfile** | N/A — script targets stock bash + Python 3.10+ on compute node; no application-level dependencies to pin |
| **CITATION.cff** | Not yet (queued for first DOI release; see Open Questions) |
| **Zenodo integration** | Not yet (queued) |
| **Smoke tests** | Inline in `AGENTS.md` "Project-specific facts" + `docs/TESTING.md` |
| **End-to-end live-verification** | `docs/TESTING.md` (768 lines; covers `client` flow with real SSH, real Duo, real argo-proxy) |
| **Phase-specific test plans** | `notes/test_plan_phase1.md`, `notes/test_plan_phase2a.md` (preserved historical artifacts) |
| **Audit trail** | `docs/AUDIT_2026-05.md` (5-round audit) + `docs/AUDIT_2026-05-12.md` (42-finding fresh-eyes audit) |

The principle: **lightest tool that does the job.** A bash orchestrator
running against real infrastructure doesn't benefit from a CI matrix
that mocks the infrastructure. Live testing on `compute-386-01` is the
verification path; the audit docs are the design-correctness trail.

---

## 7. Design decisions log

Significant architectural / design decisions, append-only. Each entry
gets a number + date + status.

### D-001 — Single-file distribution (curl-and-run UX) (2025 inception)

**Status**: accepted; load-bearing.

**Context.** The AI4Dev manual setup guide is 5 SSH sessions + multiple
config edits + a hand-managed tunnel. Each step is a place users get
stuck.

**Decision.** Ship one bash script users `curl` to a file and run.
Same file is `scp`'d to the compute node and re-exec'd as `server`
over SSH. No package layout, no dependencies beyond stock tooling.

**Alternatives considered.**
1. **Python package + `pipx install`**. Rejected: requires Python
   install + path management on the user's laptop; introduces a
   dependency layer that breaks the curl-and-run guarantee.
2. **Tarball with multi-file layout**. Rejected: same problem +
   harder for users to inspect (`cat the_one_file.sh` vs unpack-and-grep).

**Consequences.** ~5800 lines of bash in one file. Some Python escape-
hatch heredocs for JSON/YAML merging. Users can `cat` the script
before running. Forks happen by editing one file. No partial-install
failure modes.

### D-002 — bash + inline Python heredocs language policy (2025 inception)

**Status**: accepted.

**Context.** D-001 commits to bash. But bash is genuinely awkward for
JSON/YAML/TOML merging where preserving user-owned keys is required.

**Decision.** Inline Python heredocs (`python3 - <<'PYEOF' ... PYEOF`)
for structured-data work. Args cross via `sys.argv`; errors surface
as small integer exit codes the bash side translates.

**Alternatives considered.**
1. **Pure bash with `sed`/`awk`**. Rejected: deeply painful for
   nested JSON/YAML; correctness loss not worth the no-Python guarantee.
2. **Sibling `.py` files**. Rejected: breaks single-file distribution.

**Consequences.** Trade off syntax highlighting and unit testing of the
Python parts for the curl-and-run guarantee. Heredocs cap the
complexity at "small Python program". If a heredoc grows past ~50 lines
or needs non-stdlib deps beyond PyYAML, that's a signal to re-evaluate;
extraction to a `.py` is mechanical, not a redesign.

### D-003 — Mux master holds tunnels alive (2026-Q1)

**Status**: accepted.

**Context.** Under `ControlMaster=auto`, the foreground `ssh -N -L`
may exit immediately after the master accepts the forward request.
The master then owns the forward.

**Decision.** Health checks must verify `/health`, not just the
foreground pid. `open_tunnel_and_monitor` declares success if the
foreground ssh dies but `/health` still answers; the master keeps the
forward.

**Consequences.** Tunnel survives across foreground-ssh respawns
without user-visible churn. Code complexity in
`monitor_tunnel_loop`'s parent loop (must handle empty
`SSH_TUNNEL_PID`).

### D-004 — Server-mode tee logging without `exec` (2026-Q1)

**Status**: accepted (bug-fix design choice).

**Context.** Old code prefixed the tee re-exec with `exec`, but `exec
CMD | tee` only `exec`s the left side; the rest of `mode_server` then
runs a second time. Double-bootstrap bug.

**Decision.** Drop the `exec`. After the tee pipeline completes, gate
on `_MODE_SERVER_INPROC` flag: `return` (in-process call from
`_client_common_setup` short-circuit) or `exit` (main-mode invocation
over SSH).

**Consequences.** No double-bootstrap. Adds the `_MODE_SERVER_INPROC`
contract that callers MUST set before calling mode_server in-process.

### D-005 — "Main-mode" function refactor discipline (2026-Q1)

**Status**: meta-rule.

**Context.** A recurring class of bug: a function originally written
as the script's "main mode" (script's job IS to run this then exit)
gets refactored to ALSO be callable as one step of a longer in-process
flow. Main-mode-only assumptions silently break the in-process caller.
Three concrete instances hit (commits `df10abe`, `ed71864`,
`32601c3`).

**Decision.** When a "main mode" function gets called in-process,
audit it for:
- `exit` calls (replace with `return` gated on an `_INPROC` flag),
- `exec` (same fix),
- `$()` capture by callers (mutations to script-level globals
  evaporate in subshells; use `_RETURN_*` globals instead),
- Implicit assumptions about shell state outside the script
  (next-shell PATH updates etc.; prepend at script-level for the
  current invocation).

**Consequences.** Discipline applied throughout. Documented in
`AGENTS.md` "Project-specific facts" so future refactors carry it
forward.

### D-006 — Multi-instance constraint accepted (one argo-proxy + one tunnel per user per node) (2026-Q1)

**Status**: accepted; documented constraint.

**Context.** `SCREEN_SESSION="argovproxy"` is a single global constant.
`~/.config/argoproxy/config.yaml` is a single config file on the node.
`local_tunnel_status` checks "is something on this port?" — not "to
where?".

**Decision.** Accept the single-instance constraint. Detect-and-warn
checks (audit fix G1) catch the multi-port-same-node and
same-port-different-node collisions without architecturally lifting
the constraint.

**Alternatives considered.**
1. **Per-port screen names + per-instance configs**. Rejected: would
   cascade through `status`/`stop`/`clean` which would all need
   redesign for "show all" instead of "show one". Argo-shim chose this
   lane; we explicitly chose the other.

**Consequences.** Multi-port per user per node requires manual
intervention (the warn prompts the user). Acceptable trade-off for the
single-port-default UX simplicity.

### D-007 — Remove per-client symlinks; require `--cli-tool` (v2.0 Phase 1)

**Status**: accepted; landed.

**Context.** v1.x shipped `argo_opencode.sh` and `argo_claudecode.sh`
as git symlinks to `argo_anywhere.sh`. This broke under
`git clone` with `core.symlinks=false` (Windows default; some hardened
Linux configs) and on filesystems that don't preserve symlinks. Root
cause of "Bug 1" reported on compute-386-01.

**Decision.** Single canonical filename `argo_anywhere.sh`. Per-tool
selection via explicit `--cli-tool <name>` flag (or interactive picker
when omitted). Removed symlinks.

**Alternatives considered.**
1. **Keep symlinks; add self-defense for the broken-text-file case.**
   Rejected: the broken text file is 16 bytes; bash dies on line 1
   before any self-defense check can fire. Only docs can help that
   case.
2. **Truly separate per-client scripts.** Rejected: would duplicate
   the ~2500-line transport layer N ways; one bug fix = N file edits.

**Consequences.** Cleaner codebase. Old curl URLs to symlink names
auto-redirect via GitHub's transparent symlink serving. v1.x users
still using `argo_opencode.sh` URLs work via redirect.

### D-008 — Rename canonical script `argo_opencode.sh` → `argo_anywhere.sh` (v1.2.0 → v2.0)

**Status**: accepted; landed.

**Context.** The script supports multiple AI tools; `argo_opencode.sh`
implies OpenCode-only. Misleading.

**Decision.** Rename to `argo_anywhere.sh` (matches the `*anywhere*`
naming for shared infrastructure per D-009). Repo also renamed to
`a-attia/argo-anywhere`. GitHub auto-redirects all old URLs forever.

**Consequences.** Zero user disruption (redirects). All internal
references updated to `*anywhere*`. Pre-v2.0 state-detection in the
script catches users with v1.x state (`~/.config/argo_opencode/`,
`~/.ssh/sockets/argo-opencode-*`, `ARGO_OPENCODE_*` env vars) and
prints exact cleanup commands.

### D-009 — Naming convention: `*anywhere*` for shared infrastructure; tool-name for per-tool (v2.0 Phase 1)

**Status**: accepted.

**Context.** Per-tool functions, registries, env vars, and paths need
a consistent naming convention to scale beyond OpenCode + Claude Code.

**Decision.**
- **Shared infrastructure** (env vars, log prefix, state dir, mux
  socket prefix, screen session, venv): `*anywhere*` /
  `ARGO_ANYWHERE_*` / `argov*`.
- **Per-tool functions, constants, registries**: tool name in the name
  (`setup_<tool>_cli_tool`, `OPENCODE_CONFIG`, `CLAUDECODE_*`).

**Consequences.** Predictable naming. New tool added in Phase 4 will
follow `setup_aider_cli_tool` / `AIDER_CONFIG` etc. without ambiguity.

### D-010 — Rename `agovenv` → `argovenv`, `agovproxy` → `argovproxy` (v2.0 Phase 2a)

**Status**: accepted; landed; legacy detection added.

**Context.** Pre-v2.0 the venv was `~/agovenv` and the screen session
was `agovproxy`. Naming inconsistent with D-009. The audit recommended
keeping them to avoid orphaning v1.x users' running argo-proxies, but
the user confirmed the install base is n=1 today.

**Decision.** Rename both. Add legacy detection in `mode_server`
(warns if `~/agovenv` or `agovproxy` session detected; suggests
cleanup commands; doesn't auto-act because the legacy session might
still be holding a live argo-proxy other clients depend on). `clean`
mode enumerates both names.

**Consequences.** Naming consistent with D-009. Future users (n>1)
get a clean migration path via the warn.

### D-011 — SIGPIPE-resilient command-substitution patterns (v2.0 P1 hotfix)

**Status**: accepted; class of fix.

**Context.** The pattern `local x; x="$(cmd | head -n1)"` under
`set -euo pipefail` triggers `set -e` when `head -n1` closes stdin and
the upstream command (lsof, awk) gets SIGPIPE. The script silently
exits with no error message. Root cause of "Bug 2" /
silent-bootstrap-fail on compute-386-01.

**Decision.** Wrap every `cmd | head -n1` in cmd substitution as
`x="$( { ... | head -n1; } || true )"`. Three sites fixed in P1.

**Consequences.** Bootstrap silent-fail eliminated. Drop-in fix; no
semantic change. Class of vulnerability flagged for code review of any
new `$(... | ...)` cmd substitution.

### D-012 — Persistent on-disk SSH-failure lock with TTL + exponential backoff (v2.0 Phase 2a, audit C4+C5)

**Status**: accepted; landed.

**Context.** The original SSH attempt tracker was in-memory only.
Users hitting the lock could Ctrl-C + re-run to reset the counter and
keep generating CSPO failures.

**Decision.**
- Lock state persists to `${STATE_DIR}/ssh-fail-lock` so it survives
  script restarts.
- TTL is 30 min for first lock event; doubles per subsequent lock
  event up to a 24h cap (exponential backoff per audit C5).
- Lock-event count persists to `${STATE_DIR}/ssh-fail-lock-count`;
  resets only on a successful SSH attempt.
- Post-expiry counter resets to `THRESHOLD-1` (user gets one more
  attempt before re-locking; not three fresh attempts).
- If state-dir creation fails, die hard rather than fail-open (audit
  C4).

**Consequences.** Sustained-broken-auth users face fast-growing waits
without permanent block. Successful auth restores them to fresh state.
Tracker now wraps `scp` + bootstrap ssh + `find_next_free_remote_port`
+ clean-mode ssh + monitor reconnect, not just `ssh_reachable` +
`ssh_mux_open`.

### D-013 — Adopt `Co-Authored-By: Claude` trailer convention (v2.0 Phase 2a)

**Status**: accepted; landed.

**Context.** This project's v2.0 work has substantial AI assistance.
The audit + most fixes were drafted with Claude. Per the framework's
universal convention (root AGENTS.md Section 6.3): default = ON for
the trailer.

**Decision.** Use `Co-Authored-By: Claude <noreply@anthropic.com>`
trailer on commits with substantive AI assistance. Documented in
`CONTRIBUTORS.md`. `.gitmessage` template (planned in upcoming commit)
pre-populates the trailer.

**Consequences.** Per-commit attribution visible in `git log` and on
GitHub commit pages. Doesn't change accountability (the human
committer is responsible regardless); does record participation.

### D-014 — Adopt scicomp-research-skills framework (2026-05-14)

**Status**: accepted; landed alongside this PLAN.md.

**Context.** Need consistent agent-facing conventions across the
user's projects (this one + future paper/library projects). Framework
provides them.

**Decision.** Adopt with project-specific overrides for the
single-file architecture (no `src/`, no `tests/`, no `experiments/`)
and the lightweight testing strategy. Migrate existing AGENTS.md
content into framework's Project-facts + Project-specific-overrides +
Project-specific-facts sections. Add PLAN.md (this file). Add
`notes/agent_feedback.md`. Add `CLAUDE.md` symlink for Claude Code
discovery.

**Alternatives considered.**
1. **Don't adopt; keep ad-hoc AGENTS.md.** Rejected: framework
   provides discipline (skill-loading, cross-project consistency,
   upstream feedback loop) that ad-hoc lacks.
2. **Adopt fully including bootstrapping `src/`/`tests/`.** Rejected:
   the script's deliberate single-file architecture is incompatible.

**Consequences.** Per-project AGENTS.md follows framework structure.
Conflicts (single-file architecture; no CI; bash language; bash + Python
heredoc policy) recorded in "Project-specific overrides" with rationale.
`notes/agent_feedback.md` provides upstream-feedback channel.

(See
`~/.scicomp-research-skills/skills/human-facing-doc-authoring/references/audit-log-structures.md`
section B for the full decision-log convention. Append-only: never
delete D-NNN; if reversed, add D-MMM marked "supersedes D-NNN" and
edit D-NNN's status to "superseded by D-MMM".)

---

## 8. Code-paper coupling

**None.** This is a standalone tool, not a paper-supporting library.
If the project ever generates a publication (e.g. a HOWTO for the
ANL-AI4Dev community), that publication's repo would couple via this
project's commit/tag pin; the script itself is downstream-of-nobody.

---

## 9. Lifecycle stage

- **Now**: pre-v2.0 release (active development). v1.x line is tagged
  and stable; v2.0 is in Phase 2a verification.
- **Next 6 months**: Complete v2.0 (Phase 2b/2c/3 + tag); start
  Phase 4 (additional CLI tools — aider, cursor, generic
  OpenAI-compatible).
- **Long term**: Maintenance posture — single-author project; releases
  follow ANL-AI4Dev or Argo upstream changes that affect the
  protocols this script speaks. Abandonment criteria: when the upstream
  AI4Dev guide stops being a manual setup or Argo provides a
  per-laptop authentication primitive that obsoletes the SSH tunnel.

The lifecycle stage drives investment level. Pre-v2.0 we accept rapid
churn (history rewrites, breaking renames) because the user base is
n=1. Post-v2.0 release this changes: any breaking change requires a
deprecation window + clear UPGRADING.md guidance.

---

## 10. Tracking and cadence

- **This doc** (`PLAN.md`) is the contract; revise via PR-style edits
  and date-stamp changes.
- **AGENTS.md** is the agent-facing complement; revise in lockstep
  with significant PLAN changes that affect agent-facing conventions.
- **Audit docs** (`docs/AUDIT_2026-05.md`, `docs/AUDIT_2026-05-12.md`):
  historical artifacts, not actively maintained (each is a fresh-eyes
  audit at a point in time). Future audits get new dated files.
- **Per-phase test plans** (`notes/test_plan_phase*.md`): created per
  phase, archived as historical artifact when phase completes.
- **Live verification** (`docs/TESTING.md`): living guide; revised
  alongside any change to prompt flow, env-var handling, or SSH
  option logic.
- **Agent-feedback journal** (`notes/agent_feedback.md`): per-project
  feedback channel into the upstream
  [`scicomp-research-skills`](https://github.com/a-attia/scicomp-research-skills).

Release process:

1. Make changes on `main`. Smoke-test after each edit.
2. Live-test (`docs/TESTING.md`) before tagging.
3. Update the script header's example `curl` URLs if bumping the
   recommended pinned tag.
4. `git tag vX.Y.Z` and `git push origin main vX.Y.Z`.
5. The `curl …/raw.githubusercontent.com/a-attia/argo-anywhere/vX.Y.Z/…`
   URL becomes live as soon as the push completes.

---

## 11. Open questions

1. **CITATION.cff + Zenodo handshake**: defer until first DOI release
   (v2.0.0 tag is the natural moment). Need to decide concept-DOI
   strategy (per-version vs single concept).
2. **Phase 4 scope**: which AI CLI tools to add next, in which order?
   Candidates: aider, cursor, generic OpenAI-compatible (would let
   any tool that takes `OPENAI_BASE_URL` work without per-tool code).
   Generic-first might obviate aider/cursor specific support; needs
   investigation.
3. **`update-models` per-tool generalization**: currently OpenCode-only
   because it's the only tool with a model registry the script
   manages. Claude Code uses Anthropic's resolution; aider auto-detects.
   Decide: keep `update-models --cli-tool opencode` as the only valid
   form, or generalize when a second tool needs it?
4. **Multi-instance support** (per D-006): out of scope for v2.0, but
   if the user base ever exceeds the current n=1 and colleagues want
   parallel proxies on different ports per user-node, the touchpoints
   are documented in AGENTS.md "Single-instance constraint" section.
5. **CSPO threshold characterization**: the SSH attempt tracker assumes
   a CSPO threshold of ~10 attempts/hour as the floor. The actual
   threshold isn't published. If the assumption proves wrong (either
   way), TTL constants need adjustment.

---

*Created 2026-05-14 by Ahmed Attia. Maintained by Ahmed Attia (with
substantial AI assistance from Claude per `CONTRIBUTORS.md`).*
