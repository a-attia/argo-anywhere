# notes/

This directory holds working notes for the project:

- **`agent_feedback.md`** — per-project feedback channel into the
  upstream
  [`scicomp-research-skills`](https://github.com/a-attia/scicomp-research-skills)
  repository. The agent appends entries when a skill rule was
  insufficient, a workaround was needed, or a useful pattern was
  discovered. Roll-up procedure (sanitise + file an upstream issue
  or PR) is in `~/.scicomp-research-skills/CONTRIBUTING.md`.
- **`test_plan_phase<N>.md`** — per-phase live-verification test plans
  (Phase 1, Phase 2a, future Phase 2b/2c/3 etc.). Created at the
  start of each phase; archived as historical artifact when phase
  completes. Migrated from `docs/PHASE*_LIVE_TEST_PLAN.md` on
  2026-05-14 per the framework's `notes/` convention for
  working-document scratch space.
- **`impl_<component>.md`** (none today) — per-component implementation
  plans. Not used yet because this project's "components" are sections
  of one bash script, not standalone modules. If a future Python
  heredoc grows substantial enough to warrant pre-design (per the
  language-policy override in AGENTS.md), it gets an `impl_*.md` here.
- **`section_<topic>.md`** (none today) — working notes for
  cross-cutting concerns. Not used today; reserved for future use.

Conventions follow
`~/.scicomp-research-skills/skills/human-facing-doc-authoring/references/notes-structures.md`.

## Index of test plans

| Phase | File | Status | Audit findings covered |
|:---|:---|:---|:---|
| Phase 1 | [`test_plan_phase1.md`](test_plan_phase1.md) | passed (2026-05-12) | C2, C3, H9 |
| Phase 2a | [`test_plan_phase2a.md`](test_plan_phase2a.md) | awaiting live-test | C1, C4, C5, C7, P1 |

## Index of impl + section notes

(None today. Index tables here when impl_*.md or section_*.md notes
are added.)

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
