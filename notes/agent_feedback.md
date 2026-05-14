# Agent feedback journal

This file is the per-project feedback channel into the
[`scicomp-research-skills`](https://github.com/a-attia/scicomp-research-skills)
repository. Entries here capture observations about how the shared
skills + conventions worked (or didn't) on this specific project, so
they can be rolled up periodically into upstream improvements.

> The agent (per `agent-resource-discipline/references/persistent-memory.md`)
> appends entries automatically when triggers below fire. Humans
> can also add entries any time. The roll-up procedure (sanitise +
> file an issue at scicomp-research-skills) is in
> `~/.scicomp-research-skills/CONTRIBUTING.md`.

## Entry triggers

The agent should add an entry when:

- it caught itself in a rationalization not covered by the
  `agent-resource-discipline` rebuttals table;
- a skill rule didn't apply cleanly to the situation;
- it discovered a useful pattern not yet codified in any skill;
- the user said "remember this feedback" or "this is worth noting";
- a step in a documented workflow failed or felt awkward;
- it had to invent a workaround that other projects would also need.

### Software-specific triggers

In addition to the universal triggers above, software projects bring
their own situations worth recording:

- a `research-software-engineering` rule did not apply cleanly to a
  domain-specific situation (PDE / inverse / OED / UQ / SciML
  variant);
- a numerical-correctness check (MMS / convergence-rate / invariant)
  was insufficient or produced ambiguous evidence;
- the "paper tests" guard (Bridgeford R6) caught a real instance —
  worth recording so the rule's defensive value is documented;
- the upstream template (`scientific-python/cookie` /
  `NLeSC/python-template` / `CU-DBMI/...`) had a gotcha during
  bootstrap that other projects would hit;
- a domain-library idiom (dolfinx / petsc4py / JAX-research-style)
  came up that isn't yet in
  `references/03-api-design-for-researchers.md` (planned);
- a reproducibility step (lockfile / Zenodo handshake / CITATION.cff)
  hit friction.

## Entry skeleton

Each entry is short (5–15 lines):

```markdown
## YYYY-MM-DD -- <one-line title>

**Project context**: <which sub-task, which session phase>.
**Trigger**: <agent-self-caught / user-flagged / external-failure / pattern-discovered>.
**Skill(s) involved**: <e.g. agent-resource-discipline, literature-survey>.
**Observation**: <what happened, in 1-3 sentences>.
**Proposed action**: <add rule X to skill Y / clarify Z / no change needed but worth noting>.
**Evidence / minimal repro**: <a code snippet, a quoted agent message, or "happened twice this session in <context>">.

Status: open
```

`Status:` transitions: `open` → `rolled-up to issue #N` (after filing
upstream) → `rolled-up to PR #N` → closed (when the upstream change
has merged + been pulled into this project's canonical checkout).

## Privacy

This file lives in the project repo (not upstream). Sensitive content
(unpublished results, reviewer identities, internal data) can appear
here freely; it's only the **roll-up step** that copies sanitised
versions to the public upstream issue tracker.

## Roll-up cadence

Suggested: review at the end of each major project milestone, OR at
least monthly for active projects. Prioritise patterns that recurred
3+ times or affected multiple sub-tasks.

---

## Entries

(Add entries chronologically below, newest at the BOTTOM.)

## 2026-05-14 — Onboarding to scicomp-research-skills (initial migration)

**Project context**: bootstrapping the framework on this project for
the first time. Migration session followed the project-onboarding
skill's universal workflow (audit → plan → user-review → execute →
verify → document).

**Trigger**: user-flagged ("I want to adopt the scicomp-research-skills
framework while preserving all of the content I've already captured").

**Skill(s) involved**: `project-onboarding` (the migration itself);
`human-facing-doc-authoring` (the AGENTS.md + PLAN.md + README.md
authoring); `agent-resource-discipline` (first-action protocol of
reading existing project state before acting).

**Scenario classification**: Sub-cases 2.A + 2.C + 2.D simultaneously.
- 2.A — one agent-file format (existing AGENTS.md only; no CLAUDE.md /
  .cursorrules).
- 2.C — substantive project content (existing AGENTS.md was 457 dense
  lines of maintainer-facing technical detail accumulated over the
  v1.x development cycle; not generic boilerplate).
- 2.D — convention conflicts (single-file architecture; no automated
  test suite / CI; bash + Python heredoc language policy).

**What went smoothly**:
- The audit-before-acting discipline worked well. Reading the existing
  AGENTS.md in full + classifying each section by destination produced
  a clean migration plan that the user reviewed + approved before any
  writes.
- The content-check table (section 7 of the migration plan) gave the
  user line-level confidence that the 457 lines of existing content
  weren't being silently lost.
- The "Project-specific overrides" mechanism handled the four
  legitimate convention conflicts (single-file architecture, no
  CI, bash language, bash + Python heredocs) cleanly. None required a
  silent "the framework rule wins" decision.

**Observation 1 — software-skeleton template assumes software-library**:
The `templates/software-skeleton/` is heavily oriented toward
`software-library` projects (Python package layout with `src/<name>/`,
`tests/`, `experiments/<run-id>/`, `figures/<topic>/`, MMS tests,
convergence-rate tests, etc.). A `software-script-collection`
project type (one-or-few-files; no package layout; no numerical
computation) isn't a hostile case but requires deliberate
template-pruning by the migrating agent. For this project, the right
result was AGENTS.md + PLAN.md + notes/ + CONTRIBUTORS.md + .gitmessage
+ CLAUDE.md symlink — explicitly NOT bootstrapping `src/`/`tests/`/
`experiments/`/`figures/`. The migrating agent had to make these
"don't create" decisions explicitly.

**Proposed action 1**: Either (a) add a `software-script-skeleton/`
template variant to the framework, or (b) add an explicit
`script-collection-deviations.md` reference file inside
project-onboarding documenting the standard set of deviations a
script-collection project takes from the software-library defaults.
Option (b) is lighter weight; option (a) reduces per-project
override-block authoring.

**Observation 2 — human-facing-doc-authoring needs a "rewriting an
existing substantial doc" sub-procedure**: The full README.md rewrite
in this migration (agreed scope: full rewrite, not targeted) ran into
the same content-preservation question as the AGENTS.md migration:
how do we ensure no information from the existing 445-line README is
lost when writing a fresh ~similar-length version? The
project-onboarding skill provides a content-check table discipline
for AGENTS.md migrations; the human-facing-doc-authoring skill should
adopt the same discipline for "rewriting an existing substantial
human-facing doc" — produce a content-check table mapping each
section of the original to its destination in the rewritten version.
Without this discipline, the rewrite is effectively an "audit
before acting" step done in the agent's head, with no user-visible
verification.

**Proposed action 2**: Add a section to
`~/.claude/skills/human-facing-doc-authoring/SKILL.md` (or to
`references/self-review-checklist.md`) titled "Rewriting an existing
substantial human-facing doc" that prescribes:
1. Read the existing doc in full.
2. Produce a content-check table (section → destination in rewrite).
3. Present the table to the user for review (analogous to the
   project-onboarding migration plan).
4. Only then write the rewritten doc.
5. Final pass: verify table → rewrite alignment.

This is a useful pattern that emerged from this migration that
doesn't currently live in any skill.

**Evidence / minimal repro**: this onboarding session itself.
Migration plan (presented to user, approved before execution) lives
at the start of this commit's PR-style discussion in the chat
history; it includes the section-7 content-check table. The
human-facing-doc-authoring skill's `references/self-review-checklist.md`
covers post-write checking but not pre-write content-preservation
planning.

**Status**: open

**Observation 3 — onboarding skill's universal workflow Step 5 is
exactly this entry**: The project-onboarding skill specifies that
after migration, the agent should "append an entry to
`notes/agent_feedback.md` recording what was migrated, what conflicts
arose, and how they were resolved." This entry IS that record. The
skill's Step 5 worked correctly; recording for completeness.

**Status**: not really feedback; just confirming the universal
workflow's last step happened.

---

*Created 2026-05-14 by Ahmed Attia (with substantial AI assistance from
Claude per `CONTRIBUTORS.md`) from
[`scicomp-research-skills/templates/software-skeleton/notes/agent_feedback.md`](https://github.com/a-attia/scicomp-research-skills/tree/main/templates/software-skeleton/notes/agent_feedback.md).*
