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

## 2026-05-14 — bash/PyYAML interop trap: `awk -F'"'` silently degrades on plain scalars

**RESOLVED upstream 2026-05-17** in `scicomp-research-skills` commit
`686b3a1` as rule 12.1 (primary observation) + rule 12.3 (secondary
observation about recovery hints needing to be tested themselves) in
`skills/research-software-engineering/references/12-shell-and-cross-language-interop.md`.

Full original entry archived at
[`_resolved/2026-05-14_yaml-quoting-and-recovery-hints.md`](_resolved/2026-05-14_yaml-quoting-and-recovery-hints.md);
see [`_resolved/INDEX.md`](_resolved/INDEX.md) for the full
resolved-entry index.

## 2026-05-14 — `setdefault` for security-defaulted keys preserves the wrong default on upgraders

**RESOLVED upstream 2026-05-17** in `scicomp-research-skills` commit
`686b3a1` as rule 12.2 in
`skills/research-software-engineering/references/12-shell-and-cross-language-interop.md`.

Full original entry archived at
[`_resolved/2026-05-14_setdefault-security-defaults.md`](_resolved/2026-05-14_setdefault-security-defaults.md);
see [`_resolved/INDEX.md`](_resolved/INDEX.md) for the full
resolved-entry index.

## 2026-05-15 — exit-summary "what to do next" hints must be scope-keyed, not action-keyed

**RESOLVED upstream 2026-05-17** in `scicomp-research-skills` commit
`686b3a1` as rule 12.6 in
`skills/research-software-engineering/references/12-shell-and-cross-language-interop.md`
(landed under `research-software-engineering` rather than
`human-facing-doc-authoring` as originally proposed -- the rule's
audience is shell-script + CLI authors more than narrative-prose
authors).

Full original entry archived at
[`_resolved/2026-05-15_exit-summary-scope-keyed.md`](_resolved/2026-05-15_exit-summary-scope-keyed.md);
see [`_resolved/INDEX.md`](_resolved/INDEX.md) for the full
resolved-entry index.

## 2026-05-15 — test-plan stimulus must actually exercise the assertion site

**RESOLVED upstream 2026-05-17** in `scicomp-research-skills` commit
`686b3a1` as rule 12.4 in
`skills/research-software-engineering/references/12-shell-and-cross-language-interop.md`.

Full original entry archived at
[`_resolved/2026-05-15_test-stimulus-exercises-assertion.md`](_resolved/2026-05-15_test-stimulus-exercises-assertion.md);
see [`_resolved/INDEX.md`](_resolved/INDEX.md) for the full
resolved-entry index.

## 2026-05-15 — shell-script unit-test mechanics: pipe-eats-exit-code + awk-extract-fragility

**RESOLVED upstream 2026-05-17** in `scicomp-research-skills` commit
`686b3a1` as rule 12.5 in
`skills/research-software-engineering/references/12-shell-and-cross-language-interop.md`
(landed under `research-software-engineering` -- the proposal's
preferred home).

Full original entry archived at
[`_resolved/2026-05-15_shell-test-mechanics.md`](_resolved/2026-05-15_shell-test-mechanics.md);
see [`_resolved/INDEX.md`](_resolved/INDEX.md) for the full
resolved-entry index.

---

## 2026-05-18 — release-gate live test as a real correctness gate (Phase 4 v2.2.0)

**Project context**: Phase 4 v2.2.0 release-gate live test. Ran
the 12-test live-verification plan (`notes/test_plan_phase4.md`)
against the real ANL infrastructure (one Duo prompt; real
`argo-proxy` on a real compute node) before tagging. Three of the
twelve tests surfaced real defects in code that had passed all of
the inline smoke tests + had been reviewed before commit; the
amendments were landed mid-test as separate commits per the
project's amendment-mid-test convention (matches Phase 2b/2c+3
cadence).

**Trigger**: every release; the gate is documented in
`AGENTS.md` "Smoke tests" + `docs/TESTING.md` + per-phase test
plans in `notes/test_plan_phase*.md`.

**Skill(s) involved**: `research-software-engineering`
(testing-strategy discipline); `human-facing-doc-authoring`
(test-plan-authoring conventions); `agent-resource-discipline`
(amendment-mid-test cadence as a discoverable pattern across
sessions via the test-plan + commit-log indices).

**Observation**: across four consecutive release-gate live tests
(Phase 2a + 2b + 2c+3 + 2d + 4 = five tests total), the
amendment-mid-test cadence has produced:

| Phase | Tests | Mid-test code amendments | Mid-test test-plan amendments |
|:--|:--|:--|:--|
| Phase 2a | several | 0 | 1 (P3 added) |
| Phase 2b | several | 3 (H5 yaml_scalar + P2 setdefault + N1 scope-keyed) | 0 |
| Phase 2c+3 | several | 1 (L4+L5 incomplete dedup) | 2 defects identified |
| Phase 2d | several | 0 | 2 defects identified |
| Phase 4 (v2.2.0) | 12 | 3 (D-016 eager scope validation + stale --scope help + [m]igrate overpromise) | 2 (paren-in-comment defect + ambiguous-file-references) |

Pattern: a release-gate live test that produces ZERO amendments
is the exception, not the rule. The defects are always real
(D-016 violations, doc regressions, UX overpromises) and always
caught BEFORE tagging. The amendment-mid-test cadence works as
designed: the test is doing its job.

The discipline rule worth surfacing: **a release tag should NOT
be a fixed pre-test SHA**. The amendment-mid-test cadence means
the final HEAD is determined by what the live test surfaces; the
tag points at the final-amended HEAD, not at a hypothetical
"release candidate" that may not match what was actually verified.
This is the Phase 4 v2.2.0 release: tag `v2.2.0` points at
`737563d` (the SHA-backfill of the last mid-test amendment) rather
than at the pre-test HEAD `9a0834c`.

**Proposed actions** (companion rules for
`research-software-engineering`'s testing-strategy reference):

1. **Pre-tag inspection includes the amendment count**. The
   release-gate checklist should explicitly enumerate "how many
   amendments landed mid-test"; that count goes into the tag's
   annotated message as evidence of what the test caught vs let
   through.
2. **The tag points at the FINAL HEAD, not the pre-test HEAD**.
   Even if no amendments fire, this is the safe default; with
   amendments, it's the only correct one.
3. **The test plan records each amendment's commit SHA** via a
   backfill commit (small, doc-only, no behavior change). This
   keeps the test plan a self-contained artifact of what
   happened, not a snapshot of what was hoped for.

**Pattern-detection observation**: the amendment cadence isn't a
sign that the smoke tests are inadequate or the reviewers were
sloppy. It's a sign that **smoke tests + code review have a
different reachability profile than end-to-end live tests**: the
former exercise individual functions; the latter exercise the
flag-parser → mode-dispatcher → main-mode-function → per-tool
setup → handle_config_file → write_*_config chain in its actual
ordering. Defects that hide behind "fires under client but never
under status" or "stale help text that no inline test exercises"
only surface when something walks through the actual user flow.

**Evidence / minimal repro**:

- Phase 4 Test 5: `bash argo_anywhere.sh --cli-tool opencode
  --scope projct status` silently accepted the typo (the
  parser deferred validation to per-tool pick_scope, which only
  ran under client/setup). Fixed by amendment `e221847`: eager
  `_validate_scope_for_tool` call in `main()` after argument
  parsing.
- Phase 4 Test 6: `bash argo_anywhere.sh -h | sed -n '/--scope/,+20p'`
  printed `Currently consumed only by Claude Code setup` (false
  since B1b added opencode project-scope), `defaults to PROJECT
  scope` (false since D-017 changed the default), and `Canonical
  env: CLAUDECODE_SCOPE` (backwards since D-019 made
  `ARGO_ANYWHERE_SCOPE` canonical). Fixed by `1249924`: help-text
  rewrite per D-017+D-018+D-019.
- Phase 4 Test 8: D-021 proactive prompt's `[m]igrate` confirmation
  said `Will canonicalize all client configs on port N this run`,
  but the code only rewrites the per-tool config the current
  invocation's setup function touches; OTHER disagreeing configs
  remained stale. Fixed by `acf0722`: corrected the confirmation
  to accurately describe the narrower semantic.

**Status**: open (queued for upstream roll-up). Composes with the
"test stimulus must exercise the assertion site" + "shell-script
unit-test mechanics" entries above into a coherent
release-gate-testing reference.

---

## 2026-05-18 — test-plan defect family: zsh tokenization of inline `# (parens)` comments

**Project context**: Phase 4 v2.2.0 release-gate live test
(`notes/test_plan_phase4.md`). User pasted code blocks from the
test plan into a zsh terminal; several commands errored or
behaved unexpectedly because of how zsh tokenizes parenthesized
comments inline with commands.

**Trigger**: external-failure (user ran the tests; multiple
commands didn't behave as the test plan described).

**Skill(s) involved**: `human-facing-doc-authoring` (test-plan
authoring); secondarily `research-software-engineering` (test-
plan mechanics).

**Observation**: across five pre-test snapshot commands + Test 2
+ Test 4 + Test 11, the test plan contained inline `# comment`
text inside ```sh code blocks. In zsh, the pattern:

```
cat ~/.config/argo_anywhere/port    # should also be 65501 now (write-through)
```

triggers a `zsh: unknown file attribute: i` error because zsh's
parser treats `(write-through)` as a filename-attribute modifier
expression even though it appears inside what bash would consider
a comment. The result: zsh aborts the line silently, the next
line runs (often a cleanup `echo ... > file`), and the user sees
the "after-cleanup" state rather than the "during-test" state —
producing apparent test failures that are really test-plan
defects.

A second, related defect: the pre-test snapshot block conflated
`~/.claude.json` (the Anthropic OAuth state cache file) with
`~/.claude/settings.json` (the Claude Code SETTINGS file inside
the `.claude/` directory). These are SEPARATE files for
SEPARATE concerns. The snapshot block checked one but Test 7
operated on the other; users couldn't tell from the snapshot
whether Test 7's preconditions were met.

**Proposed actions**:

1. **Move comments OUT of code blocks** in test plans. Narrative
   prose ABOVE the block explains what each line does; the code
   block itself stays comment-free. Doubles as the rule for
   `human-facing-doc-authoring`'s test-plan-authoring guidance.
2. **When two files have similar names**, disambiguate them
   explicitly in the test plan's pre-test snapshot AND in every
   test that operates on either. Categorize the snapshot block
   (script state / per-tool files / OAuth state) so users can
   tell at a glance which file each command is touching.
3. **For Test 7-style scenario-dependent setups**, document
   explicit scenarios (a/b/c) with matching cleanup paths.
   The original "if MISSING, SKIP" framing is too coarse; users
   may have a backup file at `<path>.anl` that turns Test 7's
   SKIP branch into a "use scenario (b)" branch. Phase 4 Test 7
   was rewritten this way during the live test (commit
   `6c0c2e4`).

**Pattern-detection observation**: this defect class is shell-
specific (zsh parses comments differently from bash inside
certain contexts; bash itself wouldn't trip on the same
construct). Since the test plan's audience runs commands in their
own shell (which on macOS defaults to zsh since Catalina), the
test plan must be **shell-agnostic-safe**: no constructs that
parse differently in bash vs zsh vs fish.

**Evidence / minimal repro**:

```zsh
% cat /tmp/x  # try parens (in a comment)
zsh: unknown file attribute: i
```

vs:

```bash
$ cat /tmp/x  # try parens (in a comment)
(file contents)
```

The bash output is what the test-plan author assumed; the zsh
output is what the user actually sees on macOS.

**Status**: open (queued for upstream roll-up); fits cleanly into
the `human-facing-doc-authoring` skill's notes on test-plan
authoring.

---

## 2026-05-18 — upstream-stack findings need a "not our bug, here's the workaround" framing

**Project context**: Phase 4 v2.2.0 release-gate live test Test 10.
User invoked `claude` after the script wrote the proxy config and
got `API Error: API returned an empty or malformed response (HTTP
200) — check for a proxy or gateway intercepting the request`.
The error looked like an `argo-anywhere` defect; the test plan's
"Pass" criteria assumed the downstream `claude` invocation would
work without further intervention.

The bug turned out to be an upstream-stack issue: Claude Code
2.1.143 sends `thinking: {type: "enabled"}` for `claude-opus-4-7`;
ANL's Argo / Vertex deployment rejects with HTTP 400 + message
`"thinking.type.enabled" is not supported for this model. Use
"thinking.type.adaptive" and "output_config.effort" to control
thinking behavior.`; `argo-proxy` v3.x correctly surfaces the
upstream error as a SSE `event: error` payload with HTTP 200;
Claude Code 2.1.143 fails to parse the `event: error` SSE shape
and reports "API returned empty/malformed."

**Trigger**: external-failure surfaced during live test;
diagnosis required enabling verbose argo-proxy logging on the
node, capturing the request/response cycle, and probing the
hypothesis space (bare curl probe → +27 tools → +max_tokens
64000 → +anthropic-beta headers → **+ thinking.type.enabled**).

**Skill(s) involved**: `research-software-engineering`
(numerical-launch + debug protocols, even though there's no
numerical work here — the discipline of bisecting a hypothesis
space cleanly is the same); secondarily `agent-resource-
discipline` (the diagnosis required pulling the verbose log
once + analyzing locally, not repeated remote round-trips).

**Observation**: this is the FIRST time the v2.2.0 release-gate
live test surfaced a finding that's NOT actionable at the
`argo-anywhere` layer. The natural reaction was to treat it as a
v2.2.0 release blocker; the right reaction (after diagnosis) was
to:

1. Document the finding + workaround in
   `docs/LIMITATIONS.md` "Upstream stack" section.
2. Cross-reference from `README.md` "Heads up before you start" so
   users see it BEFORE hitting it.
3. Queue an auto-default fix (pre-populate
   `env.ANTHROPIC_MODEL=claude-sonnet-4-6` in
   `write_claudecode_config`) for v2.3 — eliminates the foot-gun
   for every user without requiring them to know about the
   underlying bug.
4. Identify the root cause's actual layer (Anthropic Vertex
   validation + Claude Code SSE parsing) so we don't try to fix
   it at the wrong layer.

**Proposed actions** (companion rule for
`human-facing-doc-authoring`'s LIMITATIONS-style docs):

1. **Layer-the-blame discipline**: when a user-visible bug is
   surfaced at our layer but rooted upstream, document it with
   an explicit "this is what each layer is doing right"
   paragraph. The Phase 4 LIMITATIONS entry includes "argo-proxy
   is doing the right thing by surfacing the upstream error as
   an SSE error event (RFC-compliant; the SSE spec explicitly
   defines `event: error` as a valid payload type)" — that's the
   shape of the right framing.

2. **Provide BOTH a runtime workaround and a persistent
   workaround**. Users in a hurry want
   `claude --model claude-sonnet-4-6`; users who want to never
   see the bug again want the `env.ANTHROPIC_MODEL` injection in
   `settings.json`. Document both side-by-side.

3. **Queue an auto-default fix even when the bug is upstream**, if
   the at-our-layer mitigation is low-cost (a single config-writer
   key). Eliminating the foot-gun for every user is worth more
   than holding the line on "this is upstream's fault." The user
   doesn't care which layer; they care whether it works.

4. **Add a prominent README-level callout** ("Heads up before you
   start") so users see the workaround BEFORE hitting the bug.
   The natural placement is the second TOC item, immediately
   after Contents — high enough to be unmissable, low enough to
   not bury the project's main value-prop.

**Pattern-detection observation**: this is the THIRD upstream-stack
finding documented in this project (the others: H5 yaml_scalar
on plain scalars, P2 setdefault-for-security-defaults). The
consistent shape — "our integration looks broken; turns out the
upstream behavior is what we have to work around" — suggests a
class of finding worth its own discipline rule rather than ad-hoc
documentation each time.

**Evidence / minimal repro**:

```sh
# Reproduces the bug (any non-opus-4-7 model works):
claude --model claude-opus-4-7
# After typing any prompt: "API Error: API returned an empty or
# malformed response (HTTP 200) — check for a proxy or gateway..."

# Workaround:
claude --model claude-sonnet-4-6
# Works cleanly.
```

```sh
# Direct argo-proxy curl probe confirms the upstream rejection:
curl -sS -H "Authorization: Bearer aattia" -H "Content-Type: application/json" \
     -H "anthropic-version: 2023-06-01" \
     -X POST "http://localhost:64742/v1/messages" \
     -d '{"model":"claude-opus-4-7","max_tokens":50,"stream":true,
          "thinking":{"type":"enabled","budget_tokens":10000},
          "messages":[{"role":"user","content":"hi"}]}'
# Returns:
# event: error
# data: {"type": "error", "error": {"type": "api_error",
#        "message": "Error code: 400 - {'type': 'error', 'error': {
#        'type': 'invalid_request_error', 'message':
#        '\"thinking.type.enabled\" is not supported for this model.
#        Use \"thinking.type.adaptive\" and \"output_config.effort\"
#        to control thinking behavior.'}, ...}}"}}
```

**Status**: open (queued for upstream roll-up).

**Resolution note (2026-06-17, morning)**: the underlying upstream-stack
bug **for `opus-4-7`** is **fixed in `argo-proxy v3.1.0`** (PyPI
2026-06-11). The fix is at the right layer (llm-rosetta
`argo--anthropic` shim `model_overrides`: per-model
`thinking_type: adaptive` for `claudeopus47`, `enabled` for all other
models). v3.0.3 had a partial workaround in the conversion paths;
v3.1.0 fixes the root cause declaratively. Full re-walk in
[`../docs/AUDIT_2026-06-17_argo-proxy-upstream.md`](../docs/AUDIT_2026-06-17_argo-proxy-upstream.md)
§3 UP-08. The v2.3 auto-default fix
(`env.ANTHROPIC_MODEL=claude-sonnet-4-6` in `write_claudecode_config`)
was initially flagged as removable; v2.2.1 bumps the install floor to
`argo-proxy >= 3.1.0` (UP-02) to ensure users land on a fix-bearing
install.

**Reissue note (2026-06-17, evening)**: the same upstream-stack bug
**re-emerges for `opus-4-8`** (Anthropic GA 2026-06-09; also
adaptive-thinking-only). Verified by source inspection at both
`argo-proxy v3.1.1` (`src/argoproxy/models.py:60-64`
`_DEFAULT_CHAT_MODELS` stops at `claudeopus47`;
`endpoints/dispatch.py:386` `_NO_TEMPERATURE_MODELS = {"claudeopus47"}`)
and `llm-rosetta v0.6.9`
(`src/llm_rosetta/shims/providers/argo/anthropic/provider.yaml:18-20`
`model_overrides` table contains only `claudeopus47`;
`transforms.py:41-48` `_ADAPTIVE_THINKING_MODELS = frozenset({"claudeopus47"})`).
Full diagnosis in
[`../docs/AUDIT_2026-06-17_argo-proxy-upstream.md`](../docs/AUDIT_2026-06-17_argo-proxy-upstream.md)
§3-bis UP-10 (three gap citations + three live-probe commands).
**The v2.3 auto-default fix is therefore re-instated** but
**re-scoped** to a dynamic detection rule: at config-write time,
introspect `${VENV_PATH}/lib/python*/site-packages/llm_rosetta/shims/providers/argo/anthropic/provider.yaml`
`model_overrides` and pre-populate `env.ANTHROPIC_MODEL` if any of
Anthropic's two most-recent flagship Opus releases (per the
Anthropic docs at <https://docs.anthropic.com/en/docs/about-claude/models/overview>)
is absent.

The find-it-here trail (LIMITATIONS + agent_feedback + the audit
docs) made the re-walk's UP-08 → UP-10 reissue trivial to detect —
the agent went straight to "is the same shim mechanism still in
place?" rather than re-deriving the original diagnosis. **This is
the discipline-rule the entry below proposes, now demonstrated
twice**: (a) fix surfaced upstream at v3.1.0, (b) reissue for new
model surfaced same day. Worth rolling up for
`human-facing-doc-authoring` as "limitations docs should be
re-walkable on every upstream release AND on every upstream-of-the-
upstream release of the model provider whose limitation we
documented."

The discipline-rule candidate above (document upstream-stack
findings in BOTH per-project LIMITATIONS and top-of-README callout)
**stands and is reinforced** by this resolution: the find-it-here
trail (LIMITATIONS + agent_feedback) made the v3.1.0 re-walk
straightforward — the agent could check "is the limitation we
documented still applicable?" against a known answer rather than
re-deriving the diagnosis. Worth rolling up as a feedback entry for
`human-facing-doc-authoring` ("findings docs should be re-walkable
on upstream release").

Resolution status above is the project-side disposition; the
upstream-skill-side disposition (whether the discipline rule lands
in `human-facing-doc-authoring`) remains open until the agent rolls
the rule up to scicomp-research-skills.

---

## 2026-07-08 — re-walkable upstream audits paid off again; new-tool config-research belongs in the same trail

**Project context**: dependency re-walk (argo-proxy v3.1.2 + v3.2.0a0;
llm-rosetta v0.6.10-v0.6.12 + v0.7.0a*) + codex/aider design scoping.
The re-walk fired on the 2026-06-17 audit's stated trigger ("next
release of either package"). Authored `docs/AUDIT_2026-07-08_argo-proxy-upstream.md`
(delta re-walk) + `notes/impl_codex_aider.md` (design note).

**Trigger**: pattern-discovered + external-state-changed (new upstream
releases).

**Skill(s) involved**: `agent-resource-discipline` (first-action
protocol: survey the latest audit doc BEFORE re-deriving; the
persistent-memory trail made the delta walk ~20 min instead of a
full re-audit); `human-facing-doc-authoring` (both new docs).

**Observation 1 — the re-walkable-audit discipline compounds.** For the
THIRD consecutive upstream re-walk, reading the prior audit's watch-list
+ finding dispositions first let me check "is the thing we documented
still true?" against a known baseline rather than re-deriving. Bisecting
`claudeopus48` into llm-rosetta v0.6.10 took one targeted command
because the 2026-06-17 audit had already pinpointed the exact file
(`provider.yaml` `model_overrides`) and the exact gap (G2). This is the
"findings docs should be re-walkable on every upstream release"
discipline (proposed in the 2026-06-17 entry) demonstrated a third time.

**Observation 2 — new-tool config-research is the same kind of durable
finding and belongs in the same trail.** Scoping codex surfaced a
load-bearing, drift-prone fact: codex's `wire_api` accepts ONLY
`responses`, so codex support depends on argo-proxy's `/v1/responses`
surface (present since v3.1.2, maturing in v3.2.x). That is exactly the
class of "our integration depends on an upstream surface at version X"
fact the upstream-audit watch-list exists for. I cross-linked it (audit
WATCH-17 + the impl note), so the next re-walk will re-check whether the
Responses surface still supports codex. **Proposed action**: when
scoping a new downstream tool whose viability depends on an upstream
protocol/endpoint, record the dependency as a watch-list row in the
upstream audit, not only in the tool's impl note — so it gets re-walked
on the upstream cadence rather than being rediscovered when someone
finally implements the tool.

**Evidence / minimal repro**: `docs/AUDIT_2026-07-08_argo-proxy-upstream.md`
§4 (WATCH-16 socket, WATCH-17 pipeline-migration) + `notes/impl_codex_aider.md`
trade-off #2 (codex Responses-API gating).

**Status**: open (queued for upstream roll-up; composes with the
2026-06-17 "re-walkable findings docs" entry into a coherent
"upstream-dependency-audit as living document" reference for
`human-facing-doc-authoring` or `research-software-engineering`).

---

## 2026-07-09 — live-test gate keeps catching real defects; sandbox tests must guard the isolation variable

**Project context**: the aider (Phase 5a) + lifecycle-commands (D-024
connect/configure/run + D-025 install/uninstall + manifest) live-test
gate (`notes/test_plan_lifecycle.md`, 10 tests). All passed, with SEVEN
amendments landed mid-test.

**Trigger**: pattern-discovered (release-gate cadence) + external-failure
(a test-plan defect nearly wrote to `/`).

**Skill(s) involved**: `research-software-engineering` (testing-strategy /
release-gate discipline); `agent-resource-discipline` (sandbox +
never-touch-the-live-channel discipline); `human-facing-doc-authoring`
(test-plan authoring).

**Observation 1 — the live-test-gate cadence is now proven across many
phases** (Phase 2a/2b/2c+3/2d/4 + this lifecycle gate). This gate
produced 7 amendments, ALL real, none caught by smoke tests or code
review: install-method ordering (pipx-first failed to build numpy on
Python 3.13/3.14), model-id needing the `argo:` prefix, `temperature`
sent to reasoning models yielding an EMPTY stream (aider-facing surfacing
of the audit's UP-10 G3), misleading scope-conflict prompt text,
full-status-box noise during configure/run, an OpenCode-centric summary
box, and update-models silently OpenCode-only. The recurring shape: these
live only on the actual flag-parser -> dispatcher -> per-tool setup ->
config-writer -> real-client chain, which smoke tests don't walk. Rule
worth rolling up: **a new downstream tool + a new command surface always
earns a full end-to-end live gate, and "zero amendments" is the
exception, not the rule.**

**Observation 2 — sandbox tests must guard the isolation VARIABLE, not
just sandbox files.** Test 8 ran in a shell where `$SB` (the throwaway
HOME) was empty, so `"$SB/created.yml"` expanded to `/created.yml` and
targeted the filesystem ROOT. It failed safely (root read-only), but
this is the SAME class as an earlier finding this cycle where a
sandboxed `uninstall` killed the live shared channel because the port
probe (`lsof`) is machine-global even when HOME is sandboxed. **Two
generalizable rules for agent-authored sandbox/test procedures: (a)
sandboxing files is not enough when the code reaches the network/process
layer (ports, pids) — isolate the port too; (b) every block that uses an
isolation variable must GUARD it (`: "${SB:?}"` + a path-prefix check)
so an unset/typo'd value fails loudly before any destructive op, never
silently hitting `/` or a real resource.** Both were fixed in
`notes/test_plan_lifecycle.md`; the code fix (ownership-aware Tier-1
listener-kill in `mode_uninstall`) is the durable half.

**Proposed action**: roll both into `research-software-engineering` (or
`agent-resource-discipline`): a "release-gate live test for new
tool/command surfaces" rule + a "sandbox the isolation variable, guard
it, and isolate machine-global resources (ports/pids), not just files"
rule.

**Evidence / minimal repro**: `notes/impl_lifecycle_commands.md`
"Live-test amendments" (7 items) + "Test-plan defect ... unset `$SB`
targets `/`"; `notes/test_plan_lifecycle.md` SAFETY RULES + the guarded
sandbox blocks.

**Status**: open (queued for upstream roll-up).

---

*Created 2026-05-14 by Ahmed Attia (with substantial AI assistance from
Claude per `CONTRIBUTORS.md`) from
[`scicomp-research-skills/templates/software-skeleton/notes/agent_feedback.md`](https://github.com/a-attia/scicomp-research-skills/tree/main/templates/software-skeleton/notes/agent_feedback.md).*
