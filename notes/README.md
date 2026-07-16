# notes/

This directory holds working notes for the project:

- **`agent_feedback.md`** — per-project feedback channel into the
  upstream
  [`scicomp-research-skills`](https://github.com/a-attia/scicomp-research-skills)
  repository. The agent appends entries when a skill rule was
  insufficient, a workaround was needed, or a useful pattern was
  discovered. Roll-up procedure (sanitise + file an upstream issue
  or PR) is in `~/.scicomp-research-skills/CONTRIBUTING.md`. Entries
  that have been actioned upstream are collapsed to a stub linking
  to their full text in [`_resolved/`](_resolved/INDEX.md); see the
  "Archive + resolution log" section below.
- **`test_plan_phase<N>.md`** — per-phase live-verification test plans
  (Phase 1, Phase 2a, future Phase 2b/2c/3 etc.). Created at the
  start of each phase; archived as historical artifact when phase
  completes. Migrated from `docs/PHASE*_LIVE_TEST_PLAN.md` on
  2026-05-14 per the framework's `notes/` convention for
  working-document scratch space.
- **`impl_<component>.md`** — per-component implementation plans, used
  once the project grew standalone-ish components. Each records the
  design, the trade-offs considered, and the decision it earns in
  [`PLAN.md`](../PLAN.md). See the [index below](#index-of-impl--section-notes)
  for the current set and their status; that table is the single source
  of truth, so this bullet does not enumerate them.
- **`section_<topic>.md`** (none today) — working notes for
  cross-cutting concerns. Not used today; reserved for future use.

Conventions follow
`~/.scicomp-research-skills/skills/human-facing-doc-authoring/references/notes-structures.md`.

## Index of test plans

| Phase | File | Status | Audit findings covered |
|:---|:---|:---|:---|
| Phase 1 | [`test_plan_phase1.md`](test_plan_phase1.md) | passed (2026-05-12) | C2, C3, H9 |
| Phase 2a | [`test_plan_phase2a.md`](test_plan_phase2a.md) | passed (2026-05-14; P3 added + verified) | C1, C4, C5, C7, P1, P3 |
| Phase 2b | [`test_plan_phase2b.md`](test_plan_phase2b.md) | passed (2026-05-15; 3 amendments H5+P2+N1 added + verified) | H1-H8, P2, N1 |
| Phase 2c+3 | [`test_plan_phase2c3.md`](test_plan_phase2c3.md) | passed (2026-05-15; 1 amendment L4+L5 landed mid-test) | M1-M3, M5, L1-L5, L7, L9, I1, I3 + new docs (UPGRADING/SECURITY/LIMITATIONS) + doc rewrites |
| Phase 2d | [`test_plan_phase2d.md`](test_plan_phase2d.md) | passed (2026-05-15; 0 amendments + 2 test-plan defects identified) | M6, M7, M8, M9, M10, L6, L10 (defensive-hardening: fail louder, not silently) |
| Phase 4 | [`test_plan_phase4.md`](test_plan_phase4.md) | **passed (2026-05-18; 3 code amendments + 2 doc-only commits + 2 SHA backfills + 2 test-plan-only edits)** | M4 (port-as-state); design decisions D-017 + D-018 + D-019 + D-020 + D-021; B0 latent `mode_stop` regression fix; B1b OpenCode project-scope. Mid-test amendments: `e221847` (D-016 violation: eager `--scope` validation, Test 5), `1249924` (stale `--scope` help text, Test 6), `acf0722` ([m]igrate confirmation overpromise, Test 8). Test 12 additionally surfaced two follow-up findings deferred to v2.2.1: SCOPE-NOOP (spurious scope-conflict prompt when writer would no-op) + upstream-stack opus-4-7 limitation documented in `docs/LIMITATIONS.md`. |
| Lifecycle + aider | [`test_plan_lifecycle.md`](test_plan_lifecycle.md) | **PASSED (2026-07-09; 7 mid-test amendments)** | aider Phase 5a + D-024 connect/configure/run + D-025 install/uninstall. 10 tests: aider default+opus-4.8; connect/configure channel reuse; configure-no-channel hint; --ensure; run; opencode/claudecode regression; install (sandboxed); uninstall config-restore (sandboxed); ownership guard; real bin/ migration. Test 4 full `--ensure` channel-down bring-up deferred to a from-scratch run. |
| v3 (D-028+D-030+launcher) | [`test_plan_v3_branch.md`](test_plan_v3_branch.md) | **PASSED / GATE CLOSED (2026-07-12)** | Model-A live gate: D-028 rename + D-030 lifecycle + install-launcher. Part A (T1-T6) + Part B (T7 package-mode connect) PASS from a `pipx` install; hyphenated node files, dormant bootstrap, ALL GREEN. stdlib-PTY drove the connect end-to-end; cold-Duo-in-browser recorded observed-partial (warm master reused this run; P1 spike covers the cold-Duo legibility point). |

## Index of impl + section notes

| Note | Kind | Status | Summary |
|:---|:---|:---|:---|
| [`impl_codex_aider.md`](impl_codex_aider.md) | impl | aider (Phase 5a) LIVE-TEST PASSED 2026-07-09; codex (Phase 5b) designing | Plan for adding OpenAI Codex CLI + aider as `--cli-tool` targets against the 5-function per-tool API contract. aider landed + live-tested — OpenAI-Chat path, global/project scope, key-preserving YAML merge, temperature-off model-settings; codex (Phase 5b) gated on argo-proxy's `/v1/responses` maturity + a TOML-writer decision. |
| [`impl_lifecycle_commands.md`](impl_lifecycle_commands.md) | impl | designing (decisions locked 2026-07-08) | Plan for the three-level UX reshape: connect/configure/run verb split (D-024) + symmetric install/uninstall anchored at `~/.argo_anywhere/bin/` with an install manifest for honest config-restore (D-025). Phased A (manifest) -> B (verbs) -> C (install/uninstall). |
| [`impl_python_webui.md`](impl_python_webui.md) | impl | **MERGED to `main` (2026-07-12)**; P0–P4 code-complete + `pytest` green; pre-publish live-test gate + PyPI publish pending | Model-A Python-package + web-UI rebuild: package owns the runtime, wraps the unchanged bash engine (vendored verbatim), two-lane driver (Lane-1 captured subprocess / Lane-2 PTY→browser terminal), FastAPI web UI + native app. Single source of truth; consolidates the former `spike/HANDOFF.md` + `spike/RESULTS.md` (now stubs). Records decisions D-026..D-030, the cold-Duo PASS, the P0–P4 layout, and the stdlib-PTY parity residual. `spike/` retains the proof-of-concept code the P0 web layer was lifted from. |
| [`impl_launcher_cwd.md`](impl_launcher_cwd.md) | impl | **EXECUTED + USER-VERIFIED (2026-07-13)**; targets v3.1.0 | Web-UI launcher gets an explicit cwd field (absolute; MRU-pre-filled); scope free-text → dropdown; embedded terminal splits horizontally into persistent Channel (owns `connect`) + ephemeral Utility (`configure`/`setup`/`tunnel`); `run`/`client` hard-blocked from embedded (external terminals only); `project` scope forbid-list (`$HOME` + system dirs); engine `--cwd <path>` flag for CLI parity; light/dark theme toggle; multi-instance guard; cross-platform focus-follow-window. Records decision **D-031**. 133 baseline tests → **266 passing** (+133 new). Archive after first v3.1.0 release cycle. |
| [`impl_ssh_config_native.md`](impl_ssh_config_native.md) | impl | **SHIPPED in v3.2.0** (`cd8bbdd`, 2026-07-15); live-verified with amendments A4/A5/A6, plus A7 (`ff89d8e`, 2026-07-16) post-release | Native `~/.ssh/config` respect: engine helpers (`_ssh_config_hostname` / `_ssh_config_user` / `_alias_has_own_proxy` / `_is_ssh_config_alias`), `resolve_username` refactored to a globals-based API, `--jump-host HOST` / `ARGO_ANYWHERE_JUMP_HOST`, mutable `ANL_JUMP`, plus the web-UI surface (`/api/ssh-hosts` alias picker + `/api/preview-launch` panel). Records decision **D-032** and its tri-lockstep coupling contract. **The doc's own header still reads "READY TO EXECUTE" — stale; the work shipped.** |
| [`impl_pyyaml_and_menu_fix.md`](impl_pyyaml_and_menu_fix.md) | impl | **SHIPPED in v3.2.0** (`b80970c`, 2026-07-15) | PyYAML self-heal in `ensure_argoproxy_installed` (probes + installs rather than assuming argo-proxy pulls it transitively — falsified by a 2026-07-15 field report on `compute-386-02`), plus `handle_config_file`'s `[k/b/d/m/a]` prompt only offering `[m]` when merge can actually work (never for YAML; JSON only with `jq` on PATH). **The doc's own header still reads "DRAFT — not executed" — stale; the work shipped.** |
| [`impl_channel_persistence.md`](impl_channel_persistence.md) | impl | **designing — for discussion, not scheduled** (2026-07-16); no code, no locked decisions | Shared factual baseline for the channel-persistence question raised by users 2026-07-16 ("persist when I close my screen?" + "…if the network changes?"). Establishes the three lifetimes (argo-proxy in `screen` survives everything; mux master survives terminal-close for `ControlPersist`, default 1h; tunnel dies with its terminal), and the ceiling: a network change kills TCP outright, so reconnect + **one Duo** is the floor — `mosh` can't port-forward, `autossh` means Duo spam. Documents the CLI ↔ web-UI channel-lifetime asymmetry the maintainer flagged (browser-tab close persists; web-server exit likely does not — §7.1 has the untested experiment that decides it). Options (a) document → (d) auto-reconnect, six open questions, blast radius across D-003/D-012/D-024/D-031. Would earn **D-034** if anything beyond docs ships. |
| [`impl_command_echo.md`](impl_command_echo.md) | impl | **designing** (2026-07-16); no code committed | Proposal to echo the composed `ssh`/`scp` argv before execution (`--show-commands` / `ARGO_ANYWHERE_SHOW_COMMANDS`), so a wrong resolved identity is visible at a glance instead of inferred. Motivated by the A7 wrong-username bug (`ff89d8e`), where the existing `Using ANL username:` log named the culprit and still did not land. Recommends targeted echoes at 4 call sites over a 13-site `_run_ssh` refactor; the echo must never live inside `ssh_args` (its stdout IS the argv — the A5 subshell trap). Two decisions gate code: opt-in flag vs. auto-echo on SSH retry, and the redaction story. Would earn **D-033** if it ships. |
| [`impl_cta_launcher_coherence.md`](impl_cta_launcher_coherence.md) | impl | **designing** (2026-07-16); no code committed, no user report yet | UX gap between the top-level "Connect" CTA (Channel card, cache-driven, `argv=["connect"]`) and the Actions popover's Launch (form-driven, full argv). SSH target overrides typed in the popover are silently ignored if the user closes the popover and hits the top-level CTA — a footgun D-032's preview panel makes slightly sharper. Four options, ordered by cost: (a) do nothing, (b) rename CTA to "Quick connect", (c) visible signal when overrides are set, (d) merge the CTAs. Records the three architectural principles a fix must preserve (CLI-parity fast path; form ephemerality; no hidden state). Companion §6 pins the ANTI-fix: do NOT tighten the `/ws` handler's blank-cwd branch (the CTA legitimately sends none); comment at `web/app.py:831` was corrected alongside this note. |

## Archive + resolution log

Two parallel sub-directories hold entries / artefacts that have
moved out of the project's active working set but are preserved
for traceability:

- **[`_resolved/INDEX.md`](_resolved/INDEX.md)** — agent_feedback
  entries that have been actioned upstream (codified into a
  `scicomp-research-skills` skill / reference / template). Each
  resolved entry's original text is preserved in
  `_resolved/<date>_<slug>.md`; the entry's date+title stub
  remains in `agent_feedback.md` pointing here.
- **[`_archive/INDEX.md`](_archive/INDEX.md)** — superseded /
  filed-elsewhere artefacts (upstream-proposal drafts that
  became GitHub issues, working-document versions that were
  fully replaced, etc.). Currently empty.

The two are kept separate because "resolved upstream" and
"superseded / filed elsewhere" are different kinds of "done" and
conflating them loses information.

When adding a new entry to either: append a row to the
corresponding INDEX.md AND (for `_resolved/`) create the
date-slugged file with the full original content; update the
stub in `agent_feedback.md` to point at the new file.

## Maintenance

- When a new note is added, append a row to the relevant index.
- When a note's status changes (e.g. test plan goes from queued →
  awaiting → passed), update the Status column.
- When a phase's test plan is archived (phase complete), keep the
  file — historical artifacts of "what we verified at this point".
- The `agent_feedback.md` file is self-indexing (chronological at
  the bottom); does NOT appear in the index tables above.

---

*Created 2026-05-14 by Ahmed Attia (with substantial AI assistance from
Claude per `CONTRIBUTORS.md`) from
[`scicomp-research-skills/templates/software-skeleton/notes/README.md`](https://github.com/a-attia/scicomp-research-skills/tree/main/templates/software-skeleton/notes/README.md).
Adapted for the script-collection project type: removed the
impl-notes index placeholder rows that don't apply.*
