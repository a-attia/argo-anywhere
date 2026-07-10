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
- **`impl_<component>.md`** — per-component implementation plans. Used
  once the project grew standalone-ish components: `impl_codex_aider.md`
  (aider/codex as `--cli-tool` targets), `impl_lifecycle_commands.md`
  (the connect/configure/run + install/uninstall reshape), and
  `impl_python_webui.md` (the Model-A Python-package + web-UI rebuild;
  promoted 2026-07-10 from the out-of-tree `spike/` exploration docs,
  now stubs) on the `feat/python-package-webui` branch.
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

## Index of impl + section notes

| Note | Kind | Status | Summary |
|:---|:---|:---|:---|
| [`impl_codex_aider.md`](impl_codex_aider.md) | impl | aider (Phase 5a) LIVE-TEST PASSED 2026-07-09; codex (Phase 5b) designing | Plan for adding OpenAI Codex CLI + aider as `--cli-tool` targets against the 5-function per-tool API contract. aider landed + live-tested — OpenAI-Chat path, global/project scope, key-preserving YAML merge, temperature-off model-settings; codex (Phase 5b) gated on argo-proxy's `/v1/responses` maturity + a TOML-writer decision. |
| [`impl_lifecycle_commands.md`](impl_lifecycle_commands.md) | impl | designing (decisions locked 2026-07-08) | Plan for the three-level UX reshape: connect/configure/run verb split (D-024) + symmetric install/uninstall anchored at `~/.argo_anywhere/bin/` with an install manifest for honest config-restore (D-025). Phased A (manifest) -> B (verbs) -> C (install/uninstall). |
| [`impl_python_webui.md`](impl_python_webui.md) | impl | P1 PASS; **P0 code-complete (2026-07-10)**; P2–P5 pending (branch `feat/python-package-webui`, not `main`) | Model-A Python-package + web-UI rebuild: package owns the runtime, wraps the unchanged bash engine (vendored verbatim), two-lane driver (Lane-1 captured subprocess / Lane-2 PTY→browser terminal), FastAPI web UI. Single source of truth; consolidates the former `spike/HANDOFF.md` + `spike/RESULTS.md` (now stubs). Records decisions D-026..D-029, the cold-Duo PASS, the P0 layout, and the stdlib-PTY parity residual. `spike/` retains the proof-of-concept code the P0 web layer was lifted from. |

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
