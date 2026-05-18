# Plan-of-Record: argo-anywhere

**Project name**: `argo-anywhere`. **Scope**: an end-to-end orchestrator
that lets Argonne (ANL) users run AI coding CLI tools (OpenCode, Claude
Code, future aider/cursor/generic) on their laptop against
[argo-proxy](https://github.com/Oaklight/argo-proxy) on an ANL compute
node, regardless of whether the laptop is on the ANL network or not.
**Audience**: ANL users with valid Argonne domain accounts who want AI
coding assistance without copy-pasting between a browser and an editor.
**Status**: v2.1.0 tagged + released 2026-05-15 (Phase 2d
defensive-hardening). v2.0.0 tagged + released earlier same day.
v1.x line tagged at v1.0.0 / v1.1.0 / v1.2.0; legacy URLs
redirect forever.
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

Phase status as of **2026-05-18** (post-v2.2.0 release):

| Phase | Goal | Status |
|:---|:---|:---|
| **v1.0–v1.2** | First audited release through the per-client-symlink era | **done** (tagged `v1.0.0`, `v1.1.0`, `v1.2.0`) |
| **Phase 0 (v2.0 baseline)** | Pre-rewrite snapshot; audit doc | done |
| **Phase 1 (v2.0)** | D1+D2+D4: remove symlinks, add `--cli-tool`, rename internals to `*anywhere*` | done |
| **Phase 2a (v2.0 critical)** | Audit fixes C1, C4, C5, C7 + the P1 SIGPIPE hotfix | done (live-test passed 2026-05-14) |
| **Phase 2b (v2.0 high)** | Audit fixes H1–H9 + P2 (verbose-default privacy) + N1 (Ctrl+C exit hint) | done (live-test passed 2026-05-15; 3 mid-test amendments H5+P2+N1) |
| **Phase 2c+3 (v2.0 medium/low + docs)** | M1–M5, L1–L9, I1+I3 (~17 items) + UPGRADING.md + SECURITY.md + LIMITATIONS.md | done (live-test passed 2026-05-15; 1 mid-test amendment L4+L5) |
| **v2.0.0 tag** | First v2 release | **done** (tagged `v2.0.0` 2026-05-15 at HEAD post-Phase-2c+3) |
| **Phase 2d (v2.1)** | Defensive-hardening: M6+M7+M8+M9+M10+L6+L10 (fail louder, not silently) | done (live-test passed 2026-05-15; 0 mid-test code amendments; 2 test-plan defects) |
| **Phase 2e (v2.1 cosmetic)** | I2 closure (`_LOGGING` → `_ARGO_ANYWHERE_REEXEC` rename) | done (commit `431c8e4`) |
| **v2.1.0 tag** | Defensive-hardening release | **done** (tagged `v2.1.0` 2026-05-15) |
| **Phase 4 (v2.2)** | Per-tool scope framework (D-017+D-018+D-019); port-as-state (D-020; closes audit M4); OpenCode project-scope (B1b); cross-client port-coherence (D-021); B0 latent `mode_stop` fix | done (live-test passed 2026-05-18; 3 code amendments + 2 doc-only commits + 2 SHA backfills) |
| **v2.2.0 tag** | Multi-tool framework + scope generalization release | **done** (tagged `v2.2.0` 2026-05-18 at HEAD `737563d`) |
| **v2.2.1 (queued)** | SH-04 inline `lsof`+`ps` in port-collision; SCOPE-NOOP suppression for `_<tool>_check_conflicts` A.1 prompts when writer would no-op (Test 12 finding) | queued; no scheduled trigger |
| **v2.3 (queued)** | SH-01 random `apiKeyHelper` token (eliminates H7 warning); SH-02 `CLAUDE_CODE_SKIP_ANTHROPIC_AUTH` default; SH-03 `no_proxy` injection + `HTTP_PROXY` detection; B4 cursor out-of-integration docs (needs manually-collected citations); auto-default `env.ANTHROPIC_MODEL=claude-sonnet-4-6` to work around the upstream-stack opus-4-7 limitation surfaced during v2.2.0 release-gate | queued |
| **Phase 5 (deferred)** | aider integration as application of established 5-function per-tool API contract | deferred (no scheduled trigger; fires when user requests) |
| **Phase 6+ (under consideration)** | Generic OpenAI-compatible `--cli-tool` (e.g. `--cli-tool generic --config-path <PATH>`) | under consideration |
| **Phase C local-shim mode** | Local HTTP shim layer (stream forcing + thinking-block stripping + transparent retry) per 2026-05-18 argo-shim comparative audit | **REJECTED** — would break D-001 single-file UX and address problems already handled upstream by argo-proxy's `anthropic_stream_mode: force` default (v3.x). Documented in `docs/AUDIT_2026-05-18_argo-shim-comparison.md` (Step 4 of v2.2.0 release sequence). |

Milestones are **shippable**, not commit-sized. Each phase ends with a
live-test gate before the next starts, per the post-CSPO discipline
adopted in the audit.

**Audit closure trajectory**: 0/43 at audit (Phase 0) → 22/43 at v2.0.0
(Phase 2c+3) → 33/43 at v2.0.0 release (corrected count) → 40/43 at
v2.1.0 (Phase 2d) → 41/43 at v2.1.0 + Phase 2e (I2 closure) →
**42/43 at v2.2.0** (M4 closed by Phase 4 B2's port-as-state). Only
L8 (`curl|bash claude.ai` with no checksum) remains as documented
no-fix (upstream installer choice; not actionable at our layer).

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
| **Audit trail** | `docs/AUDIT_2026-05_pre-rebuild.md` (5-round audit; archived) + `docs/AUDIT_2026-05-12.md` (43-finding fresh-eyes audit; current) |

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

### D-015 — Scope-keyed (not action-keyed) exit summaries and error messages (2026-05-15)

**Status**: accepted; codified in code by the N1 amendment commit
(`087dfe2`) and proven in the H5 amendment kill-hint (commit
`5ced284`).

**Context.** When an exit summary or error message lists "what you
can do next" actions, the user is in a "what state from this session
do I want to keep alive vs tear down" mental model at that moment,
NOT a "what are this tool's verbs called" mental model. Action-keyed
hints (`stop`, `clean`, `restart`) force the user to reverse-engineer
the scope mapping from the action names. This was concretely
exercised in Phase 2b live test #1: the original N1 summary's
`To fully stop: bash <self> stop` hint was misleading because by the
time the summary printed, `cleanup_local` had already killed the
local listener -- `stop` would print "Nothing to stop locally" and
the user could reasonably interpret that as "did anything actually
stop?"

**Decision.** Exit summaries and error messages list options by SCOPE
(what state each touches), not by action name. For each scope, show
the EXACT command (with all parameters filled in from runtime
context), not the action name + reverse-engineerable scope. Verify
the command would actually do something useful at the moment it
prints (e.g. don't suggest `stop` after already stopping the local
listener -- the user would run it and see "nothing to stop", which
corrodes trust in the message).

**Alternatives considered.**

1. **Action-keyed hints with a separate "what each action does"
   table.** Rejected: requires the user to look up the table at the
   moment of decision, increases cognitive load, doesn't surface the
   live state.
2. **Always offer all known actions in a fixed menu.** Rejected:
   includes options that wouldn't do anything useful at this moment;
   corrodes trust in the menu.
3. **Interactive prompt at exit ("scope? t/s/c/^C")**. Rejected:
   adds friction; the whole point of Ctrl+C is to be fast and
   unambiguous; the script is a CLI tool, not a TUI.

**Consequences.**
- The N1 Ctrl+C exit summary lists each independently-resident piece
  of state (SSH multiplex master, remote argo-proxy, local config /
  cache) with the exact command for each scope. When a piece of
  state is absent (e.g. no mux socket on disk under `--no-mfa`),
  the corresponding option is OMITTED entirely so the user never
  sees a "do this" hint they can't actually act on.
- The H5 reuse-refusal recovery hint includes both `kill <listener_pid>`
  AND `screen -S argovproxy -X quit` because Phase 2b live test #1
  demonstrated that argo-proxy can survive `screen -X quit` in a
  detached state. The hint surfaces both commands so the
  detached-process case isn't discovered the hard way.
- The L1 (mkdir error) fix surfaces the actual mkdir stderr verbatim
  in the die message rather than a generic "permission denied?"
  guess.
- The L4+L5 (lock recovery dedup) fix collapses 5 sites that
  re-stated "See above for recovery instructions" into one-liner
  mode descriptors, because the recovery block was already printed
  by `ssh_attempt_pre` / `ssh_attempt_fail` -- the additional line
  added a context tag, not a recapitulation.

**Generalisation queued for upstream.** Filed as agent-feedback entry
on 2026-05-15 (the "scope-keyed exit summaries" entry); concrete
proposal is a 1-paragraph addition to
`human-facing-doc-authoring`'s "Universal conventions" or to a new
`references/error-message-authoring.md` reference file. The pattern
generalises beyond this script: any CLI tool with multiple
independently-resident pieces of state benefits from this discipline.

### D-016 — Fail louder, not silently: defensive-hardening discipline (2026-05-15)

**Status**: accepted; codified by Phase 2d (commits `66d2d5c`,
`4fa2372`, `e6a8a58`).

**Context.** Across the v2.0 audit, multiple findings shared a
common shape: a code path silently corrupts user data, returns
empty / zero on edge cases, or executes a destructive action
without verifying preconditions. Each was individually fixable,
but the pattern wanted naming as a project-wide convention so
future code (and future audits) could check against it
consistently. Phase 2d deferred 7 such findings (M6-M10, L6, L10)
from Phase 2c+3 specifically because they all changed observable
behavior in the "fail louder" direction; the user's strict "no
behavior change" answer for Phase 2c+3 forced the split.

**Decision.** When a code path can encounter an edge case where
silent default / silent destruction would be wrong, prefer:

1. **Fail-loud die with explicit recovery hint** for cases where
   the script genuinely can't proceed safely (broken JSON in a
   user config the script is about to overwrite; missing PyYAML
   when the writer needs it for safe merge; PROXY_PORT empty
   when the writer is about to interpolate it into a URL).
2. **Default-with-WARN** for cases where a default IS safe but
   the silent-default behavior is invisible to the user (ask()
   under non-TTY without the legitimate sentinel).
3. **Per-PID re-classification** for destructive actions
   (kill, overwrite) where the upstream classification might be
   wrong (M6 ours-unhealthy-fg kill targeting).
4. **Defense-in-depth fallback** for fragile parse paths where
   format drift between OS versions could silently break
   classification (M7 mux detection).

**Anti-patterns to avoid:**

* `... 2>/dev/null || true` swallows that hide the actual error
  (audit L1).
* `data = {}` silent fallbacks in JSON / YAML merge (audit M8 +
  M9).
* `xargs -n1 kill` or other unconditional destructive actions
  on pre-classified PIDs (audit M6).
* Format-fragile classification regexes without a defense-in-depth
  fallback (audit M7).

**Alternatives considered.**

1. **Continue silent fallbacks; document in SECURITY.md** —
   rejected: the silent failures were the audit's largest class
   of findings precisely BECAUSE they're invisible without
   reading the code.
2. **Die hard on every edge case (no defaults at all)** —
   rejected: would break legitimate non-TTY scenarios
   (mode_server's tee'd re-exec) and force every user to
   pre-supply every prompt.
3. **Refuse-with-prompt instead of die-loud** — rejected:
   prompts only work in interactive contexts; the scenarios
   that need fail-loud are often non-interactive
   (tee'd re-exec, automation).

**Consequences.**

* **Behavior changes in the "fail louder" direction** are an
  accepted cost of v2.x and beyond. Users upgrading from
  pre-v2.1 may see new die paths fire on edge cases that
  silently corrupted before — these surface as a die with a
  recovery hint, NOT as a regression.
* **Per-finding test plans** in `notes/test_plan_phase*.md`
  must verify both (a) the new die-loud / WARN-loud path fires
  correctly on its edge case, AND (b) the successful-path UX
  is unchanged.
* **Audit STATUS blocks** must explicitly call out the
  behavior-change scope so future readers don't mistake a
  fail-loud regression report for a Phase 2d-introduced bug.

**Generalisation queued for upstream.** Filed as agent-feedback
entry on 2026-05-15 (a future entry; not yet drafted at
PLAN.md edit time); concrete proposal is a paragraph for the
`research-software-engineering` skill's testing-strategies or
api-design-for-researchers reference, since the discipline
applies broadly to any scientific-computing script that
interacts with user-owned config files or shared state.

### D-017 — Per-tool default scope policy; conflict-detection before write (2026-05-... [Phase 4 v2.2.0])

**Status**: accepted; codified by Phase 4 B1a (`claudecode_pick_scope`
rewrite + new `_claudecode_check_conflicts` + new
`prompt_scope_switch` helper in Section 11).

**Context.** The v2.0.0 H6 audit fix made claudecode's auto-default
"always project" to avoid a documented silent-correctness landmine:
writing `env.ANTHROPIC_AUTH_TOKEN` to global `~/.claude/settings.json`
could be silently shadowed by Claude Code's `~/.claude.json` OAuth
token (per docs the env-var should win; in real-world Phase 2b
live test #1 we observed shadowing). The v2.0.0 fix is correct
for users WITH a personal subscription, but inconvenient for
fresh-install users who came to argo-anywhere first (forces them
to be in a specific directory to invoke `claude`; surprises them
with an OAuth-flow prompt when they cd elsewhere).

Phase 4 generalises scope handling across multiple tools (opencode,
claudecode, future aider/cursor) and revisits the default policy
with the wider lens.

**Decision.** Default scope is **per-tool-declared with documented
rationale**, NOT script-wide-uniform. Conflict-detection runs in
ALL branches (explicit `--scope` AND auto-default): if a conflict
is detected, the user gets a scope-switch prompt
(`prompt_scope_switch`) to keep / switch / abort.

* **claudecode** uses HYBRID auto-default:
  * `--scope` / `ARGO_ANYWHERE_SCOPE` / `CLAUDECODE_SCOPE` (legacy)
    set explicitly → use that value.
  * Else if `~/.claude.json` exists (OAuth state present) →
    default to **project** (preserve subscription; H6 rationale).
  * Else (fresh install, no OAuth state) → default to **global**
    (convenience: `claude` works from any directory).
* **opencode** default is **global** (no OAuth-state concern;
  opencode is global-only in B1a; B1b will add project support but
  global remains the default).
* **Future tools** declare their default with an inline rationale
  comment block in their `<name>_pick_scope()`.

Conflict-detection checks (per claudecode):
* **A.2** (global): `~/.claude.json` exists (OAuth state) → warn
  about OAuth precedence; offer switch to project.
* **A.1** (global): `~/.claude/settings.json` has content → warn
  about content collision; offer switch to project (or proceed
  through `handle_config_file`'s `[k/b/d/m/a]` content prompt).
* **B.2** (project): cwd doesn't look like a project (no `.git`
  ancestor; no common project manifests; cwd != HOME) → warn;
  offer switch to global.

**Two-prompt model (D-015 alignment).** The scope-switch prompt
fires FIRST when `<name>_pick_scope` detects a conflict; it uses
stable letters `[k]eep-current-scope / [s]witch-to-other / [a]bort`.
Once scope is resolved, `handle_config_file` runs with its existing
unchanged `[k/b/d/m/a]` content prompt. Worst case: two simple
prompts; each unambiguous. D-015's "scope-keyed not action-keyed"
discipline is preserved (letter meanings never change with
context).

**Alternatives considered.**

1. **Default global for all tools (proposed but rejected on review)**:
   would re-expose claudecode users with personal subscriptions to
   the H6 silent-shadowing landmine on the auto-default path. The
   conflict-detection prompt is the safety net, not the primary
   defense; a user who hits the prompt and chooses `[k]eep` walks
   into the landmine. Per-tool defaults preserve the safe-by-default
   property.

2. **Combined-prompt extending `[k/b/d/m/a]` with scope letters**
   (proposed but rejected on review): reintroduces the
   action-vs-scope-letter confusion D-015 specifically removed; the
   `[u]se-once` semantic for cross-tool is genuinely ambiguous (three
   possible interpretations, none cleanly right).

3. **Keep H6 unchanged**: works for claudecode but doesn't generalise
   to other tools, and doesn't address the legitimate "fresh install
   convenience" case.

**Consequences.**

* Claudecode users who relied on auto-default project may now see
  global default on fresh installs (no OAuth state) — `docs/UPGRADING.md`
  v2.2.0 section documents this. The conflict-detection runs in all
  branches; users who later run `claude auth login` while having
  used `--scope global` get the scope-switch prompt on the next
  `client` invocation.
* Per-tool API contract gains a new `<name>_scope_values()` function
  (D-018) and the recommended `<name>_pick_scope()` is augmented
  with conflict-detection (using `prompt_scope_switch`).
* H6 audit STATUS gets a "REVISED in Phase 4 v2.2.0" addendum
  preserving the v2.0.0 history while documenting the design
  evolution.

### D-018 — Per-tool scope vocabulary contract (2026-05-... [Phase 4 v2.2.0])

**Status**: accepted; codified by Phase 4 B1a (new
`<name>_scope_values()` per-tool functions; new
`_validate_scope_for_tool` helper; CLI parser refactored to
accept any string and defer validation to per-tool stage).

**Context.** Pre-Phase-4, `--scope project|global` was validated
in the CLI parser against a hardcoded literal set. This worked
when only Claude Code consumed scope, but doesn't generalise to
future tools whose scope vocabularies differ (aider has
`home|project|cwd`; OpenCode has 8 tiers per upstream docs).

**Decision.** Each tool declares its accepted `--scope` values via
a `<name>_scope_values()` function (returns a space-separated
list). The CLI parser accepts any non-empty string at parse time
and stores into `_SCOPE_OVERRIDE`. Per-tool validation happens at
the picker stage (or at setup-time for tools without a picker)
via `_validate_scope_for_tool <tool> <scope>`, which calls
`<tool>_scope_values()` and dies with a clear "accepted values: X
Y Z" message on rejection. Validation deferred to per-tool stage
because `--scope` and `--cli-tool` can arrive in either order on
the command line; both must be known before validation can run.

**Consequences.**

* New per-tool `<name>_scope_values()` function MUST be declared
  for every tool, even tools with a single-value vocabulary (e.g.
  opencode in B1a returns just `global`). Single-value vocabulary
  is still validated to catch typos like `--cli-tool opencode --scope projct`.
* Test plan for B1a includes per-tool vocabulary validation
  (acceptance of valid values; clear die on invalid values; clear
  die on unknown tool name).
* AGENTS.md per-tool API contract gains a new bullet for
  `<name>_scope_values()` as the fifth required function.

### D-019 — Deprecate `CLAUDECODE_SCOPE`; replace with `ARGO_ANYWHERE_SCOPE` + internal `_SCOPE_OVERRIDE` (2026-05-... [Phase 4 v2.2.0])

**Status**: accepted; codified by Phase 4 B1a (legacy snapshot in
Section 1 + promotion in Section 6; new `_SCOPE_OVERRIDE` global;
`claudecode_pick_scope` reads new names; legacy alias honored with
one-time WARN per session).

**Context.** Pre-Phase-4, the env var was `CLAUDECODE_SCOPE`
(per-tool-named per D-009's convention; per-tool naming made sense
when only Claude Code consumed scope). Phase 4 generalises scope
across tools, so the env var should migrate to the shared
`*_ANYWHERE_*` namespace.

**Decision.** Two-layer naming:

* **User-facing env var: `ARGO_ANYWHERE_SCOPE`**. Matches D-009's
  namespace convention. Settable in shell rc files; settable
  inline.
* **Internal script global: `_SCOPE_OVERRIDE`**. Set by the
  `--scope` CLI flag (per-tool-agnostic storage). Per-tool
  `<name>_pick_scope` reads `_SCOPE_OVERRIDE` first, then
  `ARGO_ANYWHERE_SCOPE`, then per-tool auto-default.
* **Legacy alias: `CLAUDECODE_SCOPE`**. Honored via two-stage
  promotion (Section 1 snapshot + Section 6 promotion with
  `_warn_legacy_env CLAUDECODE_SCOPE ARGO_ANYWHERE_SCOPE`).
  Promotion only fires when the new name is empty AND the legacy
  is set. One-time WARN per session.
* **Removal target**: "whenever v3.0.0 ships" (no fixed schedule).
  Matches D-013's two-generation legacy-alias discipline.

**Consequences.**

* Users with `export CLAUDECODE_SCOPE=global` in their shell rc
  files see one WARN per session; functionality is preserved until
  v3.0.0.
* `docs/UPGRADING.md` v2.2.0 section documents the rename.
* The internal `_SCOPE_OVERRIDE` follows the underscore-prefix
  convention already established for `_INVOKED_MODE`,
  `_INVOKED_CLI_TOOL`, `_PICKED_NODE`, etc.

### D-020 — Port as transport-layer state; closes audit M4 (2026-05-... [Phase 4 v2.2.0])

**Status**: accepted; codified by Phase 4 B2 (new
`~/.config/argo_anywhere/port` cache file + read_cached_port /
write_port_cache helpers + resolve_port refactor + one-shot
first-run migration).

**Context.** Pre-Phase-4, the script derived `PROXY_PORT` from the
OpenCode config baseURL: precedence was `--port flag` >
`ARGO_ANYWHERE_PORT env` > `OpenCode config baseURL` >
`PROXY_PORT_DEFAULT`. Audit finding M4 critiqued this as
"OpenCode-specific in a multi-client world": a user running
claudecode-only (no OpenCode installed) silently got
`PROXY_PORT_DEFAULT`; if they later installed OpenCode at a
different port the configs would drift silently. The OpenCode
config was the de-facto source of truth for the port -- but only
because OpenCode was the first/only tool whose config the script
read.

**Decision.** Promote the port to **transport-layer state** owned
by the script itself, alongside the existing user / node / SSH-lock
cache files in `~/.config/argo_anywhere/`. Per-tool client configs
become **downstream renderings** that receive the port from the
cache via their writers. New precedence:

  1. `PORT_OVERRIDE_CLI` (set by `--port` flag)
  2. `ARGO_ANYWHERE_PORT` env
  3. cached port (`~/.config/argo_anywhere/port`)
  4. one-shot first-run migration (no cache; existing client configs)
  5. `PROXY_PORT_DEFAULT` (true cold start; no cache, no configs)

The cache is write-through: whenever `resolve_port` chooses a port
via something OTHER than the cache, the new value is written to
the cache so subsequent invocations see it.

**Three-case first-run migration** (when cache is empty):

* **Case 1**: no existing client configs have a baseURL anywhere.
  Seed cache with `PROXY_PORT_DEFAULT` (64742); log "no existing
  client configs; cached default port N".
* **Case 2**: exactly one client config has a baseURL (typically
  OpenCode at this point in the project's evolution; B3 will add
  inspectors for other tools). Seed cache from that config; log
  "migrated port N from <tool> config to ~/.config/argo_anywhere/port".
* **Case 3**: multiple client configs with DISAGREEING baseURLs.
  B2 inherits the OpenCode-only inspector from pre-Phase-4; B3
  adds per-tool inspectors and the disagreement-prompt machinery
  (extends the existing `prompt_port_choice` from B0 to cover
  cross-client cases). For B2, Case 3 doesn't fire because only
  one inspector exists.

**Alternatives considered.**

1. **Read from all known client configs at every invocation; pick
   first/canonical**: the original "M4 closure ambition" proposal
   from the planning phase. Rejected because it doesn't solve the
   underlying issue (configs ARE downstream renderings of the
   port; the port deserves a primary home). Caching elevates the
   port architecturally; reading-from-configs entrenches the
   "configs are the source of truth" model.

2. **Keep status quo for Phase 4; defer M4 to a later phase**:
   considered. Rejected because Phase 4's per-tool scope framework
   makes the cross-client port-coherence question more visible
   (now there's a clear path to add tool N), and addressing M4
   alongside the framework is cheaper than splitting.

3. **Per-tool port cache (separate file per tool)**: never seriously
   considered -- conflicts with the project's single-instance
   constraint (one argo-proxy per user per node; one port per
   tunnel; one port to rule them all). Per-tool port cache would
   imply per-tool tunnels, which the architecture doesn't support.

**Consequences.**

* New cache file `~/.config/argo_anywhere/port` joins user / node /
  ssh-fail-lock files in the same state directory. `clean` already
  sweeps STATE_DIR as a unit; no new entry needed in the clean
  enumeration.
* `_ensure_state_dir` helper added in Section 5 (centralizes the L1
  mkdir-with-stderr-capture pattern from `resolve_username` so
  write_port_cache + future state-dir writers share the discipline).
* `resolve_username` refactored to call `_ensure_state_dir` instead
  of repeating the inline mkdir + die boilerplate.
* `mode_server`'s separate port resolver (uses `yaml_scalar` against
  argo-proxy config on the compute node) is NOT affected by D-020.
  Documented precedence: argo-proxy config wins on-node (it's the
  actual listener); laptop cache wins elsewhere. The two resolvers
  can disagree if a user manually edits one of them; this is rare
  and documented in LIMITATIONS.md (mid-session config edits are a
  known foot-gun; not actively detected).
* `update-models` and `status`'s "OpenCode config" line still
  reference `OPENCODE_CONFIG` (= the global path); project-scope
  opencode users (per B1b) will see status point at the wrong file.
  Generalization of these consumers is out of scope for B2; would
  need a per-tool scope-discovery pass + a --scope flag on
  update-models (separate concern from M4's port-source question).

**Closes audit finding M4** ("port resolution is OpenCode-specific
in a multi-client world"). STATUS block added to audit doc with
cross-reference to D-020.

---

### D-021 — Cross-client port-coherence enforcement (2026-05-... [Phase 4 v2.2.0])

**Status**: accepted; codified by Phase 4 B3 (new
`enumerate_client_ports` + `detect_port_disagreement` helpers in
Section 7; passive reporting block in `mode_status`; proactive
prompt block in `_client_common_setup`).

**Context.** D-020 elevated the port to transport-layer state with
the cache as the source of truth, but said nothing about what
happens when multiple **installed** client configs disagree with
the cache (or with each other) at script invocation time. Scenarios
that produce this:

* User installs opencode at port A, later runs `client --port B`
  for claudecode → claudecode config gets B, opencode config keeps
  A; subsequent runs see disagreement.
* User runs `client` from inside a project directory; a
  `.claude/settings.local.json` overrides the laptop-global
  claudecode setting with a stale port.
* User hand-edits one config file but not others.

Without active detection, the user would silently end up with one
tool talking to the right tunnel and another tool talking to
nothing.

**Decision.** Add two-tier cross-client coherence enforcement:

1. **Passive reporting** in `mode_status`. After `render_summary`,
   call `detect_port_disagreement "$PROXY_PORT"` and emit a
   warn-level block listing each disagreeing config (tool, scope,
   port, path). status does NOT prompt (it's a read-only command)
   and the disagreement does NOT flip the exit code (status remains
   a pure health check; disagreement is informational).
2. **Proactive prompt** in `_client_common_setup`. After the
   existing OpenCode-specific port-mismatch block (which handles
   the legacy case where `--port` was just changed), check for
   disagreement across OTHER installed configs and invoke
   `prompt_port_choice` for `[m]igrate / [u]se-once / [k]eep /
   [a]bort` with `migrate` canonicalizing on the resolved port
   (downstream writers run later this invocation), `use-once`
   skipping downstream writes via `SKIP_CROSS_CLIENT_CONFIG_WRITES`,
   and `keep` switching `PROXY_PORT` to the alternative + updating
   the cache.

**Why split the two existing per-tool prompts.** The legacy
OpenCode block (lines 4502-4513) handles the cache-vs-config case
(user passed `--port` or the env was set; OpenCode config still
has the old value). The new block handles the multi-tool case
(other installed tools disagree with the now-resolved port). They
COULD be unified, but the legacy block has slightly different
semantics (no `SKIP_CROSS_CLIENT_CONFIG_WRITES` flag; `use-once`
sets `SKIP_OPENCODE_CONFIG_WRITE` specifically). Phase 4 keeps
them separate to minimize blast radius; a future refactor can
collapse them once all per-tool `setup_<name>_cli_tool` functions
honor `SKIP_CROSS_CLIENT_CONFIG_WRITES`.

**enumerate_client_ports inventory.** Prints one line per
installed client config that has a baseURL/env-set port:

```
<tool> <scope> <port> <path>
```

Tools currently enumerated:

* `opencode global` (reads `~/.config/opencode/config.json`
  baseURL).
* `claudecode global` (reads `~/.claude/settings.json`'s
  `env.ANTHROPIC_BASE_URL`).
* `claudecode project` (reads `<cwd>/.claude/settings.local.json`
  when present).

**Known gap (deferred).** `opencode project` (B1b's new scope) is
NOT enumerated. The opencode project path is `<git-root>/opencode.json`
where git-root is walked from cwd; cross-client coherence runs at
script startup where cwd may not be a project root (a status call
from an arbitrary directory should still work). Adding it requires
a git-root walk + `<git-root>/opencode.json` inspector; deferred
until a user reports being bitten.

**Alternatives considered.**

1. **Make status flip exit code on disagreement**: rejected.
   status's contract since v1.x is "health of the resolved tunnel
   + proxy"; folding config-coherence into it would break callers
   that branch on `argo_anywhere.sh status && ...`. Disagreement
   is a config-management concern, not a health-of-the-running-
   stack concern.
2. **Auto-canonicalize without prompting** (silently rewrite
   disagreeing configs to match resolved port): rejected per
   D-016 ("fail louder, not silently"). The user might be running
   `--port` deliberately for a one-off probe; silent rewrite would
   surprise them on the next invocation.
3. **Detect mid-session config edits** (file-mtime polling or
   inotify): out of scope. Configs are read once per invocation;
   if the user edits a config while the script is running, the
   disagreement surfaces on the NEXT invocation. Documented in
   LIMITATIONS.md as a known foot-gun (matches D-020's "rare,
   documented" framing for the on-node argo-proxy resolver
   diverging from laptop cache).

**Consequences.**

* `mode_status` gains a warn-block at the end of its body (after
  `render_summary`, before the exit-code computation). The block
  is silent when all installed configs agree with the cache, so
  the all-green case is unchanged.
* `_client_common_setup` gains a second prompt block after the
  OpenCode-specific block. Order matters: the OpenCode block
  resolves the cache-vs-config case first (which may switch
  PROXY_PORT or set SKIP_OPENCODE_CONFIG_WRITE); the cross-client
  block then sees the FINAL `PROXY_PORT` and reports any remaining
  disagreement.
* `SKIP_CROSS_CLIENT_CONFIG_WRITES` is a new opt-in flag. For B3,
  only OpenCode honors it (via the existing SKIP_OPENCODE_CONFIG_WRITE
  pattern); future per-tool setup functions should check it and
  skip their config write when set.
* No new tests in the smoke-test suite; live-test in
  `notes/test_plan_phase4.md` will cover the prompt path.

---

## 8. Code-paper coupling

**None.** This is a standalone tool, not a paper-supporting library.
If the project ever generates a publication (e.g. a HOWTO for the
ANL-AI4Dev community), that publication's repo would couple via this
project's commit/tag pin; the script itself is downstream-of-nobody.

---

## 9. Lifecycle stage

- **Now**: v2.1.0 released 2026-05-15 (Phase 2d
  defensive-hardening landed + live-tested PASS on first try
  with zero mid-test code amendments). v2.0.0 released earlier
  the same day. Audit-coverage state: 40 of 43 findings closed
  (10 CRIT + 11 HIGH + all MED except M4 + all LOW except L8 +
  all INFO except I2). All five phases (1, 2a, 2b, 2c+3, 2d)
  live-tested PASS; mid-test amendments where surfaced (P3
  added in Phase 2a; H5/P2/N1 in Phase 2b; L4+L5 in Phase 2c+3).
  Phase 2d's clean live-test (zero amendments) suggests the
  fail-louder-not-silently discipline (D-016) is well-internalized
  by this point in the project's evolution. Maintenance posture
  active.
- **Next 6 months**: optional Phase 2e cosmetic (I2 `_LOGGING`
  env var rename) when convenient. Phase 4 (additional CLI
  tools — aider, cursor, generic OpenAI-compatible; closes
  remaining M4) when there's
  user demand or a personal need.
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
- **Audit docs** (`docs/AUDIT_2026-05_pre-rebuild.md`,
  `docs/AUDIT_2026-05-12.md`): historical artifacts, not actively
  maintained (each is a fresh-eyes audit at a point in time). Future
  audits get new dated files. Archived audits get a `_pre-<event>`
  suffix when the script changes substantially enough that line/symbol
  references no longer apply (audit doc renamed to
  `_pre-rebuild` per audit finding I3 closure).
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
2. **Post-Phase-4 tool expansion**: Phase 4 (v2.2.0) landed the
   per-tool scope framework (D-017+D-018+D-019), port-as-state
   (D-020), and cross-client coherence (D-021), establishing the
   contract for adding new tools as ~5-function applications. Remaining
   candidates split into three tiers by integration cost:
   * **Phase 5 (deferred, no trigger)**: aider as a clean application
     of the established 5-function contract (`setup_aider_cli_tool`,
     `ensure_aider_installed`, `write_aider_config`, `aider_pick_scope`
     if multi-scope, `aider_scope_values`). Fires when a user requests it.
   * **v2.3 documentation work**: cursor out-of-integration docs
     (LIMITATIONS.md section + README "Not supported" subsection +
     PLAN entry). B4 of Phase 4 was deferred to v2.3 because
     docs.cursor.com is JS-only and webfetch-unreachable; needs
     manually-collected citations for upstream guidance against
     LLM-gateway routing.
   * **Even later**: generic OpenAI-compatible (`--cli-tool generic`
     with a `--config-path` flag). Considered orthogonal to per-tool
     work; would let any `OPENAI_BASE_URL`-aware tool work without
     per-tool code, but the per-tool path remains the higher-quality
     option for tools we explicitly support.
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
6. **argo-shim comparative-audit follow-up (SH-* items)**:
   `docs/AUDIT_2026-05-18_argo-shim-comparison.md` files the
   comparative audit + scrutiny + per-item disposition. v2.2.1 picks
   up SH-04 (inline `lsof`+`ps` in port-collision) + SCOPE-NOOP
   (spurious scope-conflict prompt when writer would no-op; surfaced
   during Phase 4 Test 12 live test). v2.3 picks up SH-01 (random
   `apiKeyHelper` token; supersedes H7 privacy warning), SH-02
   (`CLAUDE_CODE_SKIP_ANTHROPIC_AUTH` default), SH-03 (`no_proxy`
   injection + `HTTP_PROXY` detection), and the opus-4-7
   auto-default fix (pre-populate
   `env.ANTHROPIC_MODEL=claude-sonnet-4-6` per the upstream-stack
   limitation documented in `docs/LIMITATIONS.md`). Phase C
   local-shim mode is REJECTED with the four-point rationale in
   the audit Section 4. As each SH-* item closes, a STATUS block
   appended to the audit Section 7 records the closure commit
   (mirrors `AUDIT_2026-05-12.md` STATUS convention).
7. **Upstream-stack opus-4-7 + `thinking.type.enabled`**: surfaced
   during the v2.2.0 release-gate live test. Anthropic Vertex
   rejects `thinking.type.enabled` for `claude-opus-4-7` (requires
   `thinking.type.adaptive`); argo-proxy correctly surfaces as
   SSE `event: error` with HTTP 200; Claude Code 2.1.x fails to
   parse the SSE error event and reports "API returned empty or
   malformed response (HTTP 200)." Documented in
   `docs/LIMITATIONS.md` "Upstream stack" section with verified
   workarounds (`claude --model claude-sonnet-4-6` or
   `env.ANTHROPIC_MODEL=claude-sonnet-4-6`). Auto-default fix
   queued for v2.3. Not actionable at the argo-anywhere layer
   beyond the auto-default; the root cause sits at Anthropic
   Vertex (model-specific `thinking.type` validation) and at
   Claude Code 2.1.x (SSE `event: error` parsing). Potential
   `Oaklight/argo-proxy` upstream fix would be a translation-layer
   workaround (rewrite `thinking.type.enabled` →
   `thinking.type.adaptive` for opus-4-7 on the fly).

---

*Created 2026-05-14 by Ahmed Attia. Maintained by Ahmed Attia (with
substantial AI assistance from Claude per `CONTRIBUTORS.md`).*
