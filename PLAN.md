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
| `connect` | Level-1 verb (D-024): bring up the shared channel + hold the monitor. Friendlier name for `tunnel`. | new (Lifecycle Phase B; 2026-07-09) |
| `configure TOOL...` | Level-2 verb (D-024): install + write config for one or more clients against an EXISTING channel; detects it via `/health`, `--ensure` to bring it up. Does not block. | new (Lifecycle Phase B; 2026-07-09) |
| `run TOOL` | Level-2+3 verb (D-024): configure one client then launch it; brings the channel up if missing (prompt / `--ensure` / `-y`). | new (Lifecycle Phase B; 2026-07-09) |
| `server` | Run argo-proxy on a compute node (auto-invoked by `client` over SSH; standalone path also documented) | stable |
| `status` | Probe the tunnel + proxy health; ALL GREEN / DEGRADED / FAIL | stable |
| `update-models` | Refresh OpenCode's model list from `/v1/models` (OpenCode-specific today) | stable |
| `list-models` | Tabulate the models the proxy serves on `/v1/models` (read-only sibling of `update-models`); cross-references the OpenCode config when present | stable (added 2026-06-04) |
| `stop` | Kill the local SSH tunnel (does NOT touch the remote proxy) | stable |
| `clean` | Remove every artifact this script created (local + remote, with confirmation tiers) | stable |
| `install` | Materialize the canonical `~/.argo_anywhere/bin/` install (script + install/uninstall wrappers + env helper) + stamp the manifest (D-025). Auto-runs on first `client`; explicit form supports `--dry-run`. | new (Lifecycle Phase C; 2026-07-09) |
| `uninstall` | Symmetric tiered teardown (D-025): Tier 1 canonical install + state + owned tunnel; Tier 2 `--restore-configs` (manifest-driven); Tier 3 `--remove-binaries` (manifest-gated); Tier 4 `--remote`; `--dry-run`. | new (Lifecycle Phase C; 2026-07-09) |
| `list-tools` | Print supported `--cli-tool` values | stable |
| `help` | Long-form guide (paths, troubleshooting, customization) | stable |

Flag surface (all optional):

| Flag | Purpose |
|:---|:---|
| `--cli-tool NAME` | Pick the AI CLI tool (required for `client`/`setup` to skip the picker). Known values: `opencode`, `claudecode`, `aider` (Phase 5a; live-test PASSED 2026-07-09); `codex` planned (Phase 5b, gated on argo-proxy `/v1/responses`) |
| `--user NAME` | ANL username override |
| `--node HOST` | Compute-node override |
| `--port N` | Port override (one-shot; offers config migration prompt) |
| `--no-jump` | Skip the jump host (direct SSH to compute node) |
| `--no-mfa` | Disable Duo-aware mode (BatchMode SSH testing) |
| `--probe-nodes` | Probe each ANL_NODE for reachability before showing picker |
| `--auto-port` | Auto-pick the next free port instead of prompting on collision |
| `--port-range LO-HI` | Override the auto-port range |
| `--scope project\|global` | Per-tool config scope (consumed by client/setup/configure/run) |
| `--ensure` | For `configure`/`run`: bring the shared channel up if it isn't already, instead of failing with the "run connect first" hint |
| `--force-reinstall` | Wipe the server-side venv + rebuild from scratch |
| `--keep-orphans` / `--drop-orphans` | `update-models` orphan handling |
| `--output FILE` / `--format text\|tsv\|json` / `--include-embeddings` | `list-models` output destination + format + embedding-filter override |
| `--dry-run` / `--local-only` / `-y` / `--purge` / `--purge-backups` | `clean` modifiers (`--dry-run` + `-y` also used by `install`/`uninstall`) |
| `--restore-configs` / `--remove-binaries` / `--remote` | `uninstall` tier opt-ins (restore client configs / remove binaries we installed / tear down remote venv) |

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
| **v2.2.1 (queued)** | SH-04 inline `lsof`+`ps` in port-collision; SCOPE-NOOP suppression for `_<tool>_check_conflicts` A.1 prompts when writer would no-op (Test 12 finding); **UP-02 + UP-04 + UP-07 + UP-08 + UP-09 + UP-10 from the upstream re-walk audits** (version-floor bump to **`>=3.1.2`** per the 2026-07-08 re-walk — supersedes the `>=3.1.0` recommendation; refresh stale user-preserved-keys comment, now also stale for the v3.1.2 `socket:` key; warn-and-strip legacy `use_legacy_argo` / `force_conversion`; mark **BOTH opus-4-7 AND opus-4-8 limitations RESOLVED** in `docs/LIMITATIONS.md` — opus-4-8 fixed via `llm-rosetta >= 0.6.10` shim `model_overrides`, carried in by argo-proxy's `<0.7.0` pin — with residual G1/G3 caveats per the 2026-07-08 re-walk; small SECURITY.md + README doc updates for `log_to_file` + model-list auto-refresh); **UP-03 dropped** (would contradict upstream "omit when default" convention); **UP-01/05/06 superseded** by UP-08/UP-09. See `docs/AUDIT_2026-07-08_argo-proxy-upstream.md` (delta re-walk vs the 2026-06-17 baseline). | queued; no scheduled trigger |
| **v2.3 (queued)** | SH-01 random `apiKeyHelper` token (eliminates H7 warning); SH-02 `CLAUDE_CODE_SKIP_ANTHROPIC_AUTH` default; SH-03 `no_proxy` injection + `HTTP_PROXY` detection; B4 cursor out-of-integration docs (needs manually-collected citations). **Auto-default `env.ANTHROPIC_MODEL` when Anthropic's current flagship Opus is not in the installed llm-rosetta shim's `model_overrides`** — **MOOT for the opus-4.7/4.8 generation as of the 2026-07-08 re-walk**: `llm-rosetta >= 0.6.10` now covers `claudeopus48` at the shim layer (bisected; carried in by argo-proxy's `<0.7.0` pin), so the common Claude Code path works without our intervention. The dynamic-detection design (introspect `${VENV_PATH}/lib/python*/site-packages/llm_rosetta/shims/providers/argo/anthropic/provider.yaml` `model_overrides`) is **retained only as a template** for a future Opus generation that outpaces the shim, not as scheduled v2.3 work. See `docs/AUDIT_2026-07-08_argo-proxy-upstream.md` UP-08/UP-10 disposition. | queued |
| **Phase 5a (aider)** | aider integration as application of the established 5-function per-tool API contract; rides the proven OpenAI-Chat-compatible path (`/v1/chat/completions`; close cousin of `write_opencode_config`). Global/project scope (mirrors opencode; no OAuth state); PyYAML key-preserving merge with a refuse-to-merge-on-broken + no-PyYAML backup+scratch fallback; H7 privacy warning; `update_aider_cli_tool` registered. Full scoping in [`notes/impl_codex_aider.md`](notes/impl_codex_aider.md). | **LIVE-TEST PASSED (2026-07-09)**; `notes/test_plan_lifecycle.md` Test 1: aider installs, config + model-settings written, default (gpt-4o) AND opus-4.8 both answer through the tunnel (the temperature/reasoning fix confirmed live). |
| **Phase 5b (codex)** | codex integration. Requires the OpenAI Responses API (`wire_api = "responses"` is codex's ONLY supported protocol) served at argo-proxy's `/v1/responses` (present since v3.1.2; matured in the v3.2.x line per the v3.2.0a0 codex E2E tests). GATED on (a) a live `/v1/responses` probe against ANL, and (b) a design decision on TOML writing (no stdlib TOML writer; `tomllib` reader needs Python 3.11+ on the laptop). codex provider config is user-scope-only (project configs can't override provider keys). Full scoping in [`notes/impl_codex_aider.md`](notes/impl_codex_aider.md). | deferred (gated; fires when the probe + TOML decision clear) |
| **Lifecycle Phase A (manifest)** | Install manifest foundation (D-025 D-c): record config provenance at first-touch in the shared config-touch path; no user-visible behavior change. Prerequisite for honest uninstall + the verb split (both share the config-touch path). | **implemented + smoke-tested (2026-07-09)**; `notes/impl_lifecycle_commands.md`. `manifest_record_config` in `handle_config_file`; `manifest_record_binary` in all 3 `ensure_<tool>_installed`; first-touch-wins + compute-node-guarded + writers byte-identical. |
| **Lifecycle Phase B (verbs)** | connect / configure / run split (D-024): re-map existing internals; add `channel_is_up` detect helper + `--ensure`; multi-tool `configure`. `client`/`setup`/`tunnel` retained as fused fallbacks. | **LIVE-TEST PASSED (2026-07-09)**; `notes/test_plan_lifecycle.md` Tests 2-6. `configure` detects the live channel + configures without opening a tunnel (Issue-2 fix confirmed on port 64742); multi-tool works; no-channel dies with connect hint; `run` configures + execs the client. Amendments: configure/run box suppression, verb-aware connect message, reworded scope-conflict text. Test 4 full `--ensure` channel-down bring-up deferred. |
| **Lifecycle Phase C (install/uninstall)** | `~/.argo_anywhere/bin/` layout + explicit `install` + tiered `uninstall` (D-025): symmetric, dry-run-able, beautified; manifest-driven config restore; reuses `clean`; D-023 flat-layout migration. | **LIVE-TEST PASSED (2026-07-09)**; `notes/test_plan_lifecycle.md` Tests 7-10. install builds bin/ + wrappers + env + manifest stamp; uninstall tiers verified live (config delete/restore correct; binary removal manifest-gated; self-removal clean); ownership guard confirmed (dead-port uninstall left the real channel untouched); real `~/.argo_anywhere` migrated flat->bin/ with the channel up. Tier-1 listener-kill is ownership-aware (`local_tunnel_status` guard). |
| **Per-tool `update-models` refresh (follow-up)** | Generalize `update-models` from a hard-coded OpenCode refresh into a per-tool contract: an optional `<name>_update_models` function each tool may implement. `opencode` refreshes its picker list (today's behavior); `aider` would regenerate `.aider.model.settings.yml`'s per-model `use_temperature:false` entries from the LIVE `/v1/models` (replacing the current static 41-entry list, so newly-served models are covered automatically); `claudecode` stays N/A. Tool-awareness scaffolding (the `--cli-tool` gate + not-applicable messaging) already landed 2026-07-09; this is the remaining "make it actually do per-tool work" step. | planned (as of 2026-07-09); filed while making `update-models` tool-aware |
| **Phase 6+ (under consideration)** | Generic OpenAI-compatible `--cli-tool` (e.g. `--cli-tool generic --config-path <PATH>`) | under consideration |
| **Phase C local-shim mode** | Local HTTP shim layer (stream forcing + thinking-block stripping + transparent retry) per 2026-05-18 argo-shim comparative audit | **REJECTED** — would break D-001 single-file UX and address problems already handled upstream by argo-proxy's `anthropic_stream_mode: force` default (v3.x). Documented in `docs/AUDIT_2026-05-18_argo-shim-comparison.md` (Step 4 of v2.2.0 release sequence). |
| **Model A — Python package + web UI** (branch `feat/python-package-webui`) | Rebuild as a `pip` package that owns the runtime and wraps the unchanged bash engine (D-026..D-029): two-lane driver, FastAPI web terminal, `argo-anywhere` console script; clean-break v3.0.0. Full plan + phasing (P0–P5) in [`notes/impl_python_webui.md`](notes/impl_python_webui.md). | **P1 gate PASS**; **P0 code-complete (2026-07-10)**; P2–P5 pending. Not on `main`. |

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

**Status**: accepted; load-bearing — **superseded for the package era by
[D-026](#d-026--python-package-as-runtime-model-a-supersedes-d-001-2026-07-10)**
(2026-07-10). The single-file rationale below is preserved for provenance; the
curl-and-run path survives only as the `--print-script` escape hatch.

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

### D-022 — `update` subcommand: lossless in-place upgrades of installed components (2026-06-24 [v2.2.1])

**Status**: accepted; landed on `main` 2026-06-24 ahead of the v2.2.1
tag. Closes the long-standing user-affordance gap surfaced during the
2026-06-24 "opus 4.8 not appearing in /v1/models" session: there was no
short, low-blast-radius way to upgrade `argo-proxy` (or any of the
laptop-side AI CLI tools) other than `--force-reinstall` (full venv
wipe + rebuild) or hand-rolling an SSH-into-node + `argo-proxy update
install` recipe documented deep in the script's `help` output.

**Context.** Before D-022 the script had three asymmetric upgrade
affordances:

1. **`--force-reinstall`** — wipes `$HOME/argovenv` on the node and
   rebuilds. Heavy-handed; the only "I want a newer argo-proxy"
   path the script exposed.
2. **Implicit upgrade in `mode_server`** — `pip install --upgrade
   argo-proxy` runs ONLY when `argo-proxy --version` or `serve --help`
   fails. Once a working `serve` exists, the venv's argo-proxy never
   upgrades again (no version-floor check; audit finding UP-02
   queued for resolution).
3. **`update-models`** — refreshes the OpenCode config's model list
   from `/v1/models`. Does not install or upgrade anything, and
   does not refresh the proxy's own model registry — so when upstream
   Argo adds (e.g.) `claudeopus48` to its `/api/v1/models/` endpoint,
   a stale argo-proxy continues to advertise the old list.

Laptop-side tools (OpenCode, Claude Code) had no upgrade affordance at
all: `ensure_<name>_installed` early-returned on `command -v <tool>`
success and never re-invoked the upstream installer.

**Decision.** Add a top-level `update` subcommand whose contract is:

1. **Lossless by default.** In-place upgrades preserve all installed
   state — venv, config files, OAuth tokens, model registries. Never
   wipes anything. `--force-reinstall` remains the explicit escape
   hatch for "venv is broken, start over."
2. **Per-component registry** (`UPDATE_COMPONENTS_AVAILABLE`) listing
   the three upgradable components today: `argoproxy`, `opencode`,
   `claudecode`. Extensible: a future per-tool addition (aider,
   cursor) registers an `update_<name>_cli_tool` helper and appends
   itself to the registry.
3. **Argument shape**: `update [--all | <components...>] [--check]
   [--yes]`. `--all` updates every registered component. A positional
   component list (e.g. `update argoproxy opencode`) restricts the
   run. Bare `update` (no args) prints the registry and exits 0
   without changing anything — refuses to do destructive work without
   explicit intent. `--check` is report-only (no installs, no
   upgrades, no `/refresh` POST). `--yes` auto-confirms install
   prompts for missing components (otherwise asks
   `Install it now? [y/N]`).
4. **Per-component upgrade idiom** chosen for safety + provenance:
   * **argo-proxy**: prefer `${venv}/bin/pip install --upgrade
     argo-proxy` (targets the venv whose binary is actually
     running). Fall back to upstream `argo-proxy update install` only
     if the venv pip path fails entirely. Discovered during the
     2026-06-24 live test: upstream `argo-proxy update install`
     resolves the wrong `pip` on compute nodes (system / conda pip,
     not the venv pip), so it "succeeds" but the running venv's
     argo-proxy stays at its old version. Codified in
     `_update_argoproxy_inproc` + `_update_argoproxy_remote_payload`
     with a multi-line comment recording the diagnosis.
   * **OpenCode**: detect brew-managed install (binary under
     `/opt/homebrew/bin`, `/usr/local/bin`, or `/home/linuxbrew/`)
     and run `brew upgrade sst/tap/opencode`; else re-run the
     upstream `curl -fsSL https://opencode.ai/install | bash`
     (idempotent and the documented upgrade path).
   * **Claude Code**: re-run upstream
     `curl -fsSL https://claude.ai/install.sh | bash` (Anthropic
     ships no brew formula today; the curl installer is idempotent).
5. **Auto-refresh after argoproxy upgrade.** When `update argoproxy`
   succeeds AND a local tunnel is reachable on `$PROXY_PORT`, POST
   to `/refresh` so the running proxy's `ModelRegistry` re-pulls
   the upstream Argo `/api/v1/models/` list without a restart.
   Silently skipped (with a log line) when no tunnel is up — the
   upgrade still succeeds; the user picks up new models on the next
   `client` / `tunnel` run. The `/refresh` endpoint exists in
   argo-proxy ≥3.0; older versions surface a 404 which the helper
   converts to a soft warn.
6. **Prompt-to-install missing components.** When a component isn't
   installed yet, `update` asks `Install it now? [y/N]` (defaults
   N; `--yes` auto-confirms). Skip rather than die: the user may
   have called `update --all` from a fresh laptop where only one of
   the three components matters to them.

**Per-tool API contract extension** (extends the contract in
[`AGENTS.md`](AGENTS.md) §"Multi-CLI-tool architecture"):

* New optional function `update_<name>_cli_tool()` per CLI tool.
  Signature: takes no args; honors `$UPDATE_CHECK_ONLY` and
  `$UPDATE_ASSUME_YES` globals; returns 0 on success/up-to-date,
  1 on user-declined-install or recoverable skip, 2+ on hard failure.
  When absent, the dispatcher `mode_update()` skips the tool with a
  warn.
* New required helper `ensure_argoproxy_installed()`: factored
  out of inline `mode_server` lines 5113-5180 into a real function
  (closes the conceptual-vs-real naming gap noted in the audit docs;
  `ensure_argoproxy_installed` was referenced in
  `docs/AUDIT_2026-06-04_argo-proxy-upstream.md:316` and AGENTS.md
  but did not exist as a function until D-022). Behavior is preserved
  verbatim — `mode_server` continues to invoke it from the same
  call-site with the same semantics.

**Shared helpers added.**

* `_version_ge <a> <b>` — semver-ish comparison via `sort -V`. Used
  by `update --check` for argo-proxy (compares installed vs
  PyPI-latest). Also unblocks the UP-02 soft-floor work (the audit
  recommended a `_version_ge` primitive but the script had none).
* `_pypi_latest_version <pkg>` — best-effort `https://pypi.org/pypi/<pkg>/json`
  GET via curl + jq (or python3 fallback). Empty string on failure;
  callers degrade to "unknown" rather than die.
* `_extract_version <text>` — normalizes `--version` output across
  tools that decorate the version with vendor names or parenthesized
  labels (`argo-proxy 3.1.2`, `2.1.187 (Claude Code)`, `1.17.9`).
  Returns the first dotted-numeric token.
* `_update_prompt_install <label>` — the
  `Install it now? [y/N]` prompt; honors `$UPDATE_ASSUME_YES`.

**Composition with `--force-reinstall`.** `update` is the lossless
sibling; `--force-reinstall` remains the destructive escape hatch.
When in-place upgrade fails, `update_argoproxy_component`'s error
message points at `--force-reinstall server` as the fallback. The
two flags do not interact: `update --force-reinstall argoproxy`
would be a contradiction, so the parser does not advertise it; the
user picks one or the other.

**Alternatives considered.**

1. **`--update-all` as a top-level flag** (matched user's initial
   phrasing): rejected. Doesn't compose with the existing subcommand
   grammar; a bare flag can't carry a positional component list
   (`--update opencode` is awkward); harder to extend.
2. **Auto-escalate to `--force-reinstall` on in-place failure**:
   rejected per D-016 ("fail louder, not silently"). The user
   may have a reason the in-place upgrade failed (intentionally
   pinned dependency, partial network failure, etc.); silently
   destroying their venv is the wrong default. Helper instead
   prints the explicit recovery command.
3. **`update` auto-restart of the running proxy**: rejected. Kills
   in-flight requests from any concurrent user on the same node.
   `/refresh` is sufficient for the model-registry use case
   (verified live 2026-06-24: opus 4.8 appeared in `/v1/models`
   immediately after `update argoproxy` without restart).
4. **Always use `argo-proxy update install` (upstream's own
   updater)**: rejected after live test. The upstream updater
   resolves `pip` from PATH at runtime, which on compute nodes
   defaults to the system / conda pip, leaving the venv's argo-proxy
   stale. The venv-pip-first idiom is the only one that
   reliably upgrades the binary that's actually running. Kept as
   the fallback path.

**Consequences.**

* `mode_server`'s install block shrinks from ~70 lines of inline
  logic to a single `ensure_argoproxy_installed || die ...` call.
  Server-mode behavior is unchanged (same install policy, same
  recreate-on-broken-venv discipline, same FORCE_REINSTALL semantics).
* New SECTION 22b in `argo_anywhere.sh` (between SECTION 22
  update-models/list-models and SECTION 23 clean helpers) houses
  the registry, the per-component update helpers, and `mode_update`.
* Help text grows: new subcommand block + new `Flags below apply to
  'update':` group + revised `Update installed components in place`
  recipe in `long_help` (replaces the stale `ssh -J ... 'argo-proxy
  update install'` one-liner with the new subcommand examples;
  keeps the manual fallback under "Manual fallback if 'update
  argoproxy' can't reach the node").
* `--all` and `--check` flags added at the top-level parser; warned-
  but-ignored when passed to subcommands that don't consume them
  (matches the existing `--cli-tool` / `--scope` / `--output` /
  `--format` ignored-warn discipline).
* The legacy single-`--yes` parse arm now sets BOTH `CLEAN_ASSUME_YES`
  and `UPDATE_ASSUME_YES` so the same flag controls both subcommands'
  non-interactive behavior.
* `clean`'s risk-tier discipline is unaffected — `update` operates
  strictly on **installed binaries / packages**, never on **config
  files**; the two subcommands have non-overlapping concerns.

**Live test (2026-06-24, on `compute-01.cels.anl.gov` via mux master).**
End-to-end: starting from venv argo-proxy `3.0.0` (system pip cached
at `3.0.1`), `bash argo_anywhere.sh update argoproxy` upgraded the
venv to `3.1.2`, POSTed `/refresh`, and `claudeopus48` appeared in
`/v1/models` (previously only `claudeopus47` and older). Total
elapsed: ~12 seconds. No prompts (SSH mux already warm).

**Follow-on (D-023, same session)**: the registry was extended with
a fourth component, `argo-anywhere`, that self-updates the script
itself. See D-023 for the full design.

### D-023 — Self-update + canonical install for `argo_anywhere.sh` itself (2026-06-24 [v2.2.1])

**Status**: accepted; landed on `main` 2026-06-24 immediately after
D-022. Extends the per-component registry from three components to
four; adds the first-run bootstrap helper that materializes the
canonical install at `~/.argo_anywhere/`.

**Context.** D-022 added `update argoproxy / opencode / claudecode`
for the three downstream components but said nothing about the
script itself. The user reported (2026-06-24 session) that they had
a stale copy of `argo_anywhere.sh` at `~/.argo_anywhere/argo_anywhere.sh`
(set up manually months earlier with a shell-rc PATH line) and asked
whether `update` could keep that copy fresh too.

Two facts surfaced during the discussion:

1. There IS no in-script self-update path today. The script doesn't
   even have a version constant; version lives only in git tags.
2. There ARE three "copies" of the script on disk for a typical
   user (1) the source-of-truth working copy (git checkout or
   wherever they `curl`d it); (2) a PATH-discoverable cached copy at
   `~/.argo_anywhere/argo_anywhere.sh` if they've set one up; (3) a
   `scp`'d copy at `~/.argo_anywhere.sh` on each compute node, kept
   in sync automatically by `remote_bootstrap` on every `client` run.

(3) already self-manages. (1) is the user's responsibility (they
chose where to put it). (2) was the gap.

**Decision.** Promote `~/.argo_anywhere/` to a first-class canonical
install location (a rustup/cargo-style PATH directory) and manage it
via two complementary helpers:

1. **Bootstrap helper** (`maybe_bootstrap_canonical_install`): fires
   ONCE on the user's first `client` / `setup` invocation IFF
   `~/.argo_anywhere/` does not yet exist. Creates the directory,
   copies `$0` into it, writes a sourceable `env` PATH-helper, and
   prints one-shot rc-line instructions. Idempotent: no-op on every
   subsequent invocation. Honors `ARGO_ANYWHERE_SKIP_BOOTSTRAP=1`.
   Does NOT fire when running on a compute node (the on-node
   short-circuit doesn't benefit), or when the user is already
   running from the canonical install path.

2. **Self-update component** (`update_argo_anywhere_component`):
   the fourth entry in `UPDATE_COMPONENTS_AVAILABLE`. Resolves the
   latest upstream version (two-step probe: GitHub `/releases/latest`
   API, falling back to `/tags` matching `v[0-9]+.[0-9]+.[0-9]+`,
   falling back to `main` branch tip); fetches the raw script;
   validates it (`bash -n` parses + size > 50 KB + sentinel marker:
   either `SCRIPT_VERSION=` line or the canonical
   `# argo_anywhere.sh --` header); backs up the existing target
   with a `.bak.<timestamp>.<pid>` suffix (matches
   `handle_config_file`'s backup convention); atomically replaces
   the canonical install via `mv` within the same filesystem.

**Two-step tag probe rationale.** The project's release process
(PLAN.md §10) tags via `git tag vX.Y.Z` ONLY — the GitHub Releases
UI is not used. The `/releases/latest` API endpoint therefore 404s
for this repo today. Verified live 2026-06-24: `/releases/latest`
returned 404; `/tags` returned the full tag history with `v2.2.0`
at the top; self-update fetched the v2.2.0 raw script successfully.
We still try `/releases/latest` first in case the convention
changes; the fallback is essentially the production path today.

**Sentinel-marker lenience (`SCRIPT_VERSION=` OR header).** The
`SCRIPT_VERSION=` constant is new in v2.2.1; v2.2.0 and earlier
releases don't have it. Validating against the constant alone would
prevent v2.2.0 users from self-upgrading to v2.2.1 — they'd see
"file does not contain a SCRIPT_VERSION= line" and have to `curl`
manually. Accepting EITHER the constant OR the long-stable header
`# argo_anywhere.sh --` (in place since the v2.0 rename) keeps the
v2.2.0 → v2.2.1 transition smooth. From v2.2.1 onward both markers
are present; the header check is dead code we keep around for
defense-in-depth.

**Atomicity discipline.** Fetch lands in a `mktemp` file in the
SAME directory as the target so the final `mv` is `rename(2)`
atomic (POSIX guarantees rename atomicity within a single
filesystem). Forces `chmod 0755` on the new file (because `mktemp`
creates with 0600 by default, and the new copy needs to be
executable + readable for the user's interactive shells).

**Refuse on dirty git tree.** When the resolved target lives inside
a git working tree with uncommitted changes, `update argo-anywhere`
aborts with a clear message: this almost always means the user is
running from a development checkout and would clobber unsaved work.
The user is told to commit/stash + use `git pull`, or to install
into the canonical location first.

**Shell-rc management = NO.** The bootstrap helper writes the `env`
file and PRINTS the rc-line instruction; it never edits the user's
rc files directly. Matches rustup/cargo convention. Rationale:
detecting the right rc file is brittle (zsh/bash, login-vs-interactive,
ZDOTDIR); rewriting user rc files invites clobbering custom edits;
the user benefits from seeing exactly what's changing. The user's
existing manual `export PATH=...` line continues to work; they can
migrate to `. ~/.argo_anywhere/env` at their leisure (the env file
is idempotent so coexistence is fine).

**Alternatives considered.**

1. **Separate `self-update` subcommand**: rejected. Keeping
   self-update inside the `update` registry (a) gets it into
   `update --all` automatically, (b) reuses the same `--check` /
   `--yes` semantics, (c) gives users one mental model for
   "upgrading anything I have installed".
2. **Auto-append rc line on bootstrap**: rejected per the
   shell-rc-management discussion above.
3. **Always use `main` branch instead of release tags**: rejected.
   Pinning to release tags is the right default for "I want a
   working version, not the latest unreleased changes". Falling
   back to `main` ONLY when no tag resolves keeps the "works
   even on day-zero of a new repo" property.
4. **Strict validation requiring `SCRIPT_VERSION=`**: rejected as
   it would block the v2.2.0 → v2.2.1 self-upgrade path (the very
   first one users will exercise).

**Consequences.**

* `argo_anywhere.sh` gains a `SCRIPT_VERSION="2.2.1-dev"` constant
  near the top of SECTION 2 (bumped to `"2.2.1"` on tag day per the
  release process).
* SECTION 5 (PLATFORM HELPERS) gains
  `maybe_bootstrap_canonical_install` + four small helpers
  (`canonical_install_present`, `_resolve_self_path`,
  `_write_argo_env_file`, `_print_path_setup_hint`).
* `mode_client` calls `maybe_bootstrap_canonical_install` as its
  very first action (before `_client_common_setup` even fires).
  `mode_setup` inherits the call automatically (it reuses
  `mode_client`).
* SECTION 22b (UPDATE) gains `update_argo_anywhere_component`
  (the largest of the four `update_*` helpers; the validation +
  atomic-replace machinery is bespoke per-component).
* The `UPDATE_COMPONENTS_AVAILABLE` registry grows from 3 to 4
  entries, with `argo-anywhere` listed first (alphabetical AND
  most-impactful position).
* Help text, AGENTS.md, README.md, and docs/UPGRADING.md all gain
  notes on the new component + the canonical install convention.

**Live test (2026-06-24, on the test laptop).** Starting from a
pre-existing `~/.argo_anywhere/` populated months earlier with the
v1.x-era manual setup: `bash argo_anywhere.sh update argo-anywhere`
resolved upstream tag `v2.2.0`, fetched
`https://raw.githubusercontent.com/a-attia/argo-anywhere/v2.2.0/argo_anywhere.sh`,
validated (size 354 KB > 50 KB threshold; bash -n clean; canonical
header present), backed up the existing copy to
`argo_anywhere.sh.bak.20260624-111941.60789`, atomically replaced
the canonical install, refreshed the env helper. Total elapsed: ~3
seconds. Verified byte-for-byte identity with upstream v2.2.0 tag
via `diff`. Backup was then manually restored to leave the user's
pre-test install in place pending the v2.2.1 tag.

---

### D-024 — Lifecycle-command split: connect / configure / run (2026-07-08)

**Status**: accepted; designing. Full plan in
[`notes/impl_lifecycle_commands.md`](../notes/impl_lifecycle_commands.md).

**Context.** argo-anywhere manages three levels: (1) the shared channel
(SSH tunnel + remote argo-proxy), (2) install + configure ONE client,
(3) the user running clients. The current `client` command fuses levels
1 + 2 and names the fused thing after the level-2 choice (`--cli-tool`).
Because the channel is a shared, client-agnostic local HTTP endpoint
that any number of tools can hit simultaneously (level 3), naming a
shared-channel operation after a single client is confusing: "why do I
pick one tool when the channel serves all of them?" The exclusivity is
purely our orchestrator's convention, not a constraint of the transport
or argo-proxy.

**Decision.** Add explicit verbs mirroring the three levels, keeping the
fused commands as backward-compatible one-shot fallbacks:

- `connect` (level 1): ensure the channel, then hold the foreground
  monitor. Effectively the current `tunnel` behavior; `tunnel` is
  retained as an alias.
- `configure <tool>...` (level 2): install + write config for the named
  tool(s) against an EXISTING channel. Multi-tool per call (the channel
  is shared). Per D-e it DETECTS the channel (port cache + `/health`)
  and fails loud with a hint if absent; `--ensure` brings it up.
- `run <tool>` (level 2+3): `configure <tool>` then `exec` the client.
- `client` / `setup` / `tunnel` retained unchanged (fused fallback).

**Consequences.** Users can hold the channel + monitor in one window and
freely configure / run clients in other windows. Largely a re-mapping of
existing internals (`tunnel` = level 1; `do_post_tunnel_for_cli_tool` =
level 2); the one new piece is a `channel_is_up <port>` helper.
Backward compat preserved (additive verbs). Per-tool API contract gains
no new required function (the verbs dispatch through the existing
`setup_<tool>_cli_tool`).

### D-025 — Install manifest + symmetric install / uninstall (2026-07-08)

**Status**: accepted; designing. Full plan in
[`notes/impl_lifecycle_commands.md`](../notes/impl_lifecycle_commands.md).

**Context.** D-023 gave the script a canonical install at
`~/.argo_anywhere/` with a self-update path but NO uninstall, and
install itself is implicit (bootstrap on first `client`). "Install"
today spans tool binaries (via `ensure_<tool>_installed`), the remote
venv, the canonical script install, and configs across several
locations; there is no symmetric teardown. `clean` removes session
artifacts (tunnels, state, configs, remote venv) but leaves
argo-anywhere installed and does not restore client configs to their
pre-argo-anywhere state.

**Decision.**

1. **`bin/` canonical layout** (D-a): `~/.argo_anywhere/bin/` holds
   `argo_anywhere.sh` + thin `install` / `uninstall` wrappers (which
   call the subcommands, preserving D-001 single-file). `env` points at
   `bin/`. Migrate the D-023 flat layout on next install/bootstrap.
2. **`install` subcommand** (D-a): explicit form of the bootstrap
   (`--dry-run`, beautified output in the scicomp-research-skills
   style). Bootstrap-on-first-`client` retained (calls the same core).
3. **Install manifest** (D-c): `~/.argo_anywhere/manifest.json` records,
   at FIRST touch of each config, whether the file pre-existed and where
   its original backup lives, plus which tool binaries we installed.
   Written by the shared config-touch path (first-touch-wins); read by
   uninstall. This makes "restore original config" correct rather than
   best-effort (delete files we created; restore the true pre-argo
   backup for files we modified).
4. **`uninstall` subcommand** — TIERED (D-b): Tier 1 canonical install +
   state + tunnels (always, on confirm); Tier 2 config restore via
   manifest (`--restore-configs`); Tier 3 tool binaries, opt-in
   `--remove-binaries`, gated on `installed_by_us`; Tier 4 remote venv
   `--remote`. REUSES clean's risky-file logic (D-d) rather than
   duplicating it. `--dry-run` previewable.

**Consequences.** Install/uninstall become symmetric and honest. New
machinery: the manifest (written in the config-touch path shared with
D-024's verbs — hence sequenced first). Self-removal of the canonical
dir during uninstall needs care (order dir-removal last or re-exec a
tempfile copy). D-023's flat layout requires a one-shot migration.

**Sequencing** (both decisions share the config-touch path): Phase A
manifest foundation -> Phase B D-024 verb split -> Phase C D-025 bin/ +
install/uninstall. Each independently shippable + live-tested.

### D-026 — Python-package-as-runtime (Model A); supersedes D-001 (2026-07-10)

**Status**: accepted; designing. Supersedes [D-001](#d-001--single-file-distribution-curl-and-run-ux-2025-inception).
Make-or-break gate (P1 — Duo/connect driven from a browser terminal) PASSED
(2026-07-09; cold-Duo residual closed 2026-07-10). Exploration record on branch
`feat/python-package-webui` (`spike/RESULTS.md`, `spike/HANDOFF.md`); to be
promoted to `notes/impl_python_webui.md`.

**Context.** D-001 chose single-file bash specifically to avoid a Python
dependency layer on the user's laptop. Two facts have since inverted that
calculus:

1. The target community (ANL scientific users) universally has Python + pip —
   the very prerequisite D-001 feared missing is mandatory here, so its stated
   objection no longer applies.
2. The new headline capability — a local web UI that can connect (incl. Duo),
   monitor, configure, and run clients entirely from a browser terminal —
   requires a persistent Python server process to drive the engine. A pure
   `.sh` cannot host that server. The P1 spike proved the load-bearing piece:
   the whole interactive `connect` flow (interactive prompts + a cold Duo
   challenge) drives cleanly over a PTY <-> WebSocket <-> xterm.js bridge.

**Decision.** Turn argo-anywhere into a `pip`-installable Python package
(Model A) that OWNS the runtime and wraps the **unchanged** bash engine
(vendored verbatim as package-data). A two-lane driver splits the engine's
interactive surface:

- **Lane 1** — managed subprocess for everything pre-answerable via flags/env
  (`-y`, `--auto-port`, `--user/--node/--port`, `--scope`, `ARGO_ANYWHERE_*`);
  these verbs return, so they are safe to run and await.
- **Lane 2** — PTY streamed to the browser terminal for Duo, the long-lived
  monitor loop, and the 3 prompts with no non-interactive flag (port-migrate,
  config-conflict, scope-conflict).

The bash engine stays the single source of truth for all orchestration
(SSH mux, Duo, CSPO defenses, port policy); the package adds only the runtime
+ web layer around it.

**Alternatives considered.**
1. **Keep pure bash + a separate optional UI script.** Rejected: bash cannot
   host the persistent server, and a second script home reintroduces the
   "two-paths problem" (already visible as three competing script copies on a
   dev machine — repo tree, `~/.argo_anywhere/bin/`, self-update backups).
2. **Rewrite the engine in Python.** Rejected: discards ~5800 lines of
   live-verified orchestration for zero user benefit. The engine is vendored
   verbatim instead; correctness is inherited, not re-litigated.

**Consequences.** D-001's curl-and-run path is retired as the *primary* install
route (see [D-027]); its inspect-and-fork spirit is preserved via a
`--print-script` escape hatch that re-emits the raw vendored `.sh`.
The pip package supplants the **install role** of `~/.argo_anywhere/` (the
D-025 `bin/` wrappers, `env`, and self-update backups become redundant). The
**state** dir (`~/.config/argo_anywhere/`: port/node/user cache + ssh-fail-lock)
and the **SSH sockets** (`~/.ssh/sockets/`) are unchanged. Where `manifest.json`
(config provenance for honest uninstall, D-025) lives once the install dir is
gone is an open question — see §11. The project's "single-file; no `src/`" override
(CLAUDE.md) is itself superseded for the package era: code lands under
`src/argo_anywhere/` with the engine as package-data. Self-invocation still
works — `remote_bootstrap` scp's the vendored `.sh` to the node and re-execs it
as `server` (compute nodes keep receiving a plain `.sh`).

### D-027 — Clean-break web-UI major release; no in-place migration (2026-07-10)

**Status**: accepted; designing.

**Context.** The move to a Python package (D-026) plus the script rename (D-028)
is a hard discontinuity in install shape and entry-point name. The user base is
small (~dozens) and coordinated, so a permanent back-compat forwarder to
straddle a one-time cutover would buy little and cost lasting complexity.

**Decision.** Ship the web-UI package as a **clean-break major release**: no
in-place migration, no back-compat forwarder or alias. Users uninstall the old
version and install the new one. The old version's mature `uninstall` / `clean`
(D-025) is the sanctioned off-ramp. A `--print-script` escape hatch (D-026)
preserves inspect-and-fork.

**Alternatives considered.**
1. **Forwarder from the old script to the package.** Rejected: permanent
   complexity for a one-time, coordinated cutover.
2. **Dual-ship both indefinitely.** Rejected: reinstates the two-paths problem
   D-026 exists to resolve.

**Consequences.** `docs/UPGRADING.md` gains a hard-cutover section
(uninstall-old -> install-new). No straddling / dual-home code. The cutover is
communicated out-of-band to the small user set.

### D-028 — Rename `argo_anywhere` -> `argo-anywhere` everywhere user-facing (2026-07-10)

**Status**: accepted; designing.

**Context.** The repo and package are hyphenated (`argo-anywhere`); only the
script file still uses an underscore (`argo_anywhere.sh`), a historical artifact
of the D-008 rename from `argo_opencode.sh`. The clean-break release (D-027) is
the natural moment to unify without a compatibility burden.

**Decision.** Rename `argo_anywhere` -> `argo-anywhere` **everywhere it is
user-facing** (uniform hyphenation matching repo + package name). Rides the
D-027 discontinuity; no forwarder/alias by design. "Everywhere" is scoped, not
literal — two hard carve-outs stay underscored because the platform forbids the
hyphen:

**Hyphenate (`argo-anywhere`)** — user-facing surface:
- the script filename `argo_anywhere.sh` -> `argo-anywhere.sh`;
- the node-side copy `REMOTE_SELF` `.argo_anywhere.sh` -> `.argo-anywhere.sh`
  (add the underscore name to `clean`'s legacy-enumeration so old nodes are
  swept — cf. `LEGACY_REMOTE_SELF`);
- package / console-script / PyPI name `argo-anywhere` (D-029);
- the log/display prefix `[argo_anywhere]` -> `[argo-anywhere]`;
- the script header, `SCRIPT_VERSION` self-update sentinel string
  (`# argo_anywhere.sh --` -> `# argo-anywhere.sh --`, argo_anywhere.sh:8305),
  and all live-doc references (README, AGENTS.md, UPGRADING, TESTING, SECURITY,
  LIMITATIONS, examples/) — **not** the dated `docs/AUDIT_*` or
  `notes/test_plan_*` provenance files;
- the config/state/install directories `~/.config/argo_anywhere` ->
  `~/.config/argo-anywhere` and `~/.argo_anywhere` -> gone-or-hyphenated (its
  install role is retired by D-026), handled as a **first-run state migration**
  under the D-027 clean break (mirror the existing `LEGACY_STATE_DIR` migration
  idiom).

**Stay underscored (hard platform constraint — do NOT sed these):**
- **Shell env-var names** (`ARGO_ANYWHERE_*`, 17 of them, + `ARGO_BOX_STYLE`,
  legacy `ARGO_OPENCODE_*`): POSIX env-var identifiers are
  `[A-Za-z_][A-Za-z0-9_]*` — hyphens are illegal.
- **Internal bash identifiers**: function names, globals (`STATE_DIR`,
  `REMOTE_SELF`, `SCRIPT_VERSION`, `ARGO_INSTALL_DIR`, ...).

**Consequences.** A naive global `s/argo_anywhere/argo-anywhere/` would break
every env var and every bash identifier — the rename MUST honor the carve-outs
above. One-time doc/reference sweep (live docs only). No user-facing alias
(consistent with D-027).

### D-029 — PyPI as the single source of truth for install + upgrade (2026-07-10)

**Status**: accepted; designing. Depends on [D-026], [D-027]. Retires the
`argo-anywhere` self-update path from [D-022]/[D-023] for the package era (the
other `update`-registry components are unaffected — see below).

**Context.** D-026 makes the package own the runtime with the engine vendored
as package-data. D-022/D-023 had previously given the *standalone script* an
in-place self-update (`update argo-anywhere` rewriting
`~/.argo_anywhere/argo_anywhere.sh`) plus a canonical install. Under Model A
the engine lives inside the installed package (site-packages / a `pipx` venv);
self-updating that copy in place is dead-or-harmful because the package manager
owns it. The name is confirmed free: **`argo-anywhere` is AVAILABLE on PyPI**
(checked 2026-07-10 — JSON API and the authoritative `/simple/` index both
return 404, incl. the `argo_anywhere` / `argoanywhere` normalized variants).

**Decision.**

1. **PyPI is the single source of truth** for the packaged tool. Install =
   `pipx install argo-anywhere` (or `pip install`); upgrade = `pipx upgrade` /
   `pip install -U`. The **package version** carries release identity; the
   vendored engine's `SCRIPT_VERSION` becomes an internal *component* version,
   not a user-facing upgrade channel.
2. **The engine self-update retires for the package era.** Running as
   package-data, `argo-anywhere update argo-anywhere` becomes a no-op that
   points the user at `pipx`/`pip`. The other `update`-registry rows —
   `argoproxy` (server-side venv-pip), `opencode`, `claudecode` (laptop tools)
   — are **UNAFFECTED**: they remain independently-installed binaries the tool
   upgrades in place.
3. **Not yet hosted.** PyPI publication happens once a working Python version
   exists (the first `v3.0.0` candidate; see §11). Until then, install is
   from-git on the `feat/python-package-webui` branch.

**Consequences.** Removes the two-homes upgrade ambiguity D-026 flags.
`docs/UPGRADING.md`'s hard-cutover section (D-027) documents the `pipx`
install/upgrade flow. `--print-script` (D-026) still re-emits the raw engine
for inspect/fork but is explicitly **not** an install/upgrade channel. The
still-queued CITATION.cff / Zenodo DOI aligns to the PyPI release + git tag.

---

## 8. Code-paper coupling

**None.** This is a standalone tool, not a paper-supporting library.
If the project ever generates a publication (e.g. a HOWTO for the
ANL-AI4Dev community), that publication's repo would couple via this
project's commit/tag pin; the script itself is downstream-of-nobody.

---

## 9. Lifecycle stage

- **Now**: v2.2.0 released 2026-05-18 (Phase 4 multi-tool
  framework landed + live-tested PASS per
  `notes/test_plan_phase4.md`). v2.2.1 in progress on `main`
  (2026-06-24): D-022 `update` subcommand + D-023 self-update +
  canonical install both landed; per-phase test plan at
  `notes/test_plan_phase_v2_2_1.md` awaits release-gate live
  verification before tagging. Audit-coverage state: **42 of 43
  findings closed** (only L8 `curl|bash claude.ai` remains as
  documented no-fix); v2.2.1 will partially address UP-02
  (`update argoproxy` exposes a user-facing upgrade path) but the
  formal `_version_ge` soft-floor inside
  `ensure_argoproxy_installed` is still queued. Maintenance posture
  active.
- **Next 6 months**: tag v2.2.1 after `notes/test_plan_phase_v2_2_1.md`
  live verification passes. Pick up the remaining v2.2.x backlog
  (UP-01/03/04/05/06 + SH-04 + SCOPE-NOOP) as patch releases.
  Phase 5 (aider integration) deferred (no scheduled trigger;
  becomes scheduled when a user asks). Phase 4 cursor docs
  deferred to v2.3.
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
   (`CLAUDE_CODE_SKIP_ANTHROPIC_AUTH` default), and SH-03 (`no_proxy`
   injection + `HTTP_PROXY` detection). Phase C local-shim mode is
   REJECTED with the four-point rationale in the audit Section 4.
   As each SH-* item closes, a STATUS block appended to the audit
   Section 7 records the closure commit (mirrors `AUDIT_2026-05-12.md`
   STATUS convention).
7. **Upstream `argo-proxy` audit roll-up (UP-* items)**: two upstream
   audits track our consumption of `Oaklight/argo-proxy`:
   `docs/AUDIT_2026-06-04_argo-proxy-upstream.md` (v3.0.4 baseline;
   UP-01..UP-06 + 15-row watch-list) and
   `docs/AUDIT_2026-06-17_argo-proxy-upstream.md` (v3.1.0+v3.1.1
   re-walk; UP-07+UP-08+UP-09 + watch-list re-disposition).
   **v2.2.1 picks up UP-02 (version-floor `>=3.1.0`) + UP-04
   (refresh stale comment) + UP-07 (warn-strip removed
   `use_legacy_argo` / `force_conversion`) + UP-08 (mark opus-4-7
   limitation RESOLVED in `docs/LIMITATIONS.md`; merges with UP-01)
   + UP-09 (small SECURITY/README updates for `log_to_file` +
   model-auto-refresh; absorbs UP-05/UP-06)**. **UP-03 dropped**
   (would contradict upstream "omit when default" convention for
   `anthropic_stream_mode`). The re-walk audit revises the priority
   ordering in §5 of the v3.0.4 baseline; the v3.0.4 file remains
   the canonical 15-row watch-list, with each row's v3.1.x status
   recorded in re-walk §2. Re-run the watch-list after each future
   `argo-proxy` release; rename successor file to
   `AUDIT_<date>_argo-proxy-upstream.md` and cross-link.
8. **Upstream-stack opus-4-X + `thinking.type.enabled`**:
   **Partially RESOLVED 2026-06-17**. For **opus-4-7**: fixed in
   upstream `argo-proxy v3.1.0` (via llm-rosetta `argo--anthropic`
   shim `model_overrides`: per-model `thinking_type: adaptive` for
   opus-4-7, `enabled` for others). For **opus-4-8** (Anthropic GA
   2026-06-09): **NOT yet fixed**; the shim's `model_overrides`
   table only contains `claudeopus47`, and argo-proxy's
   `_DEFAULT_CHAT_MODELS` + `_NO_TEMPERATURE_MODELS` both stop at
   `claudeopus47`. UP-10 in
   `docs/AUDIT_2026-06-17_argo-proxy-upstream.md` §3-bis documents
   the gap with three specific source-location citations and a
   three-step live-probe protocol the user can run against ANL.
   The v2.3 auto-default fix is **re-scoped** (not removed) per
   UP-10: pre-populate `env.ANTHROPIC_MODEL=claude-sonnet-4-6`
   when the installed llm-rosetta shim doesn't cover Anthropic's
   current flagship Opus. v2.2.1 ships the LIMITATIONS doc update
   pairing opus-4-7 (historical-RESOLVED) + opus-4-8 (current-OPEN);
   v2.3 ships the dynamic auto-default. Historical diagnosis
   preserved in `docs/AUDIT_2026-06-17_argo-proxy-upstream.md` §3
   UP-08 + §3-bis UP-10; `notes/agent_feedback.md` entry 6's
   Resolution-note is updated to reflect the 4.7-resolved /
   4.8-reissued split.

### Model-A (Python package + web UI) open questions

Raised 2026-07-10 during the pre-P0 multipass review of D-026..D-029.
Tracked here so they don't block; each must resolve before the P0 file it
gates.

9. **Package identity + Python floor (gates `pyproject.toml`)**. Name is
   settled: **`argo-anywhere`** (confirmed available on PyPI, D-029); console
   script `argo-anywhere`; target release **v3.0.0** (matches the existing
   "whenever v3.0.0 ships" removal targets). **Minimum Python: 3.10+**
   (settled 2026-07-10 — broad scientific baseline; the P1 spike used 3.13 and
   the ANL compute node ran system Python 3.12, both comfortably above). Set
   `requires-python = ">=3.10"` in `pyproject.toml`.
10. **Two version numbers (gates the release + `update` UX)**. Package version
    vs the vendored engine's `SCRIPT_VERSION`. D-029 makes the package version
    authoritative and the engine version an internal component tag. Confirm
    they may diverge (engine patched without a package bump, and vice versa)
    and how `argo-anywhere --version` / `status` surface both.
11. **Web-server security posture (gates `web/app.py`; needs a `SECURITY.md`
    row)**. The spike server is **unauthenticated** — loopback-only bind +
    host-header (DNS-rebinding) guard — and can spawn PTYs running arbitrary
    engine flows (incl. SSH). Proposed posture to ratify: acceptable because
    it shares the user's shell trust boundary (a local attacker who can reach
    `127.0.0.1:<port>` already has the user's shell). Decide whether a
    loopback token / same-origin check is warranted, and add the threat-model
    row to `docs/SECURITY.md`.
12. **Lane-2 PTY concurrency model (gates `driver.py`)**. Lane 2 streams a PTY
    to "the browser terminal", but a `configure`/`run` action can hit a
    Lane-2 prompt (config-conflict / scope-conflict, D-026) while `connect`'s
    monitor PTY is already streaming in another tab. Decide the arbitration:
    one PTY per browser session, a single shared session, or a queued
    prompt-broker. Related: **manifest.json's home** once `~/.argo_anywhere/`
    loses its install role (D-026 F1 note) — likely `~/.config/argo_anywhere/`
    with the rest of the state.

---

*Created 2026-05-14 by Ahmed Attia. Maintained by Ahmed Attia (with
substantial AI assistance from Claude per `CONTRIBUTORS.md`).*
