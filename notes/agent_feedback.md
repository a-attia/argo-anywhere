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

**Project context**: Phase 2b live test #1 of the H5 audit fix. The
fix used `awk -F'"' '/^[[:space:]]*user:/{print $2; exit}'` to
extract the `user:` value from `~/.config/argoproxy/config.yaml`.

**Trigger**: external-failure (the user ran the live test, the new
H5 branch wrongly fired against a perfectly valid config that the
script itself had verified one log line earlier; user pasted the
log and asked).

**Skill(s) involved**: `research-software-engineering` (the rule
this would belong under is API design / cross-language interop in
shell projects with Python heredoc helpers).

**Observation**: PyYAML's `safe_dump(default_flow_style=False)` --
the default for the project's `write_argoproxy_config` writer --
emits plain ASCII strings UNQUOTED:
```yaml
user: aattia
```
The `awk -F'"' '{print $2}'` parser splits on `"`, so for the
unquoted form there's only one field; `$2` is empty. The parser
silently returns "" for the common case and only works on the
fallback writer's quoted output (`user: "aattia"`). Same class of
bug existed at TWO sites in this script (the H5 reuse check, and
a previously-latent identity-resolver path that silently degraded
to `id -un`). Both fixed by switching to a `yaml_scalar` helper
that handles plain / double-quoted / single-quoted scalars +
comments + leading whitespace; verified via 11-case synthetic
harness.

**Proposed action**: Add a "Cross-language interop" subsection (or
a one-rule entry) to `research-software-engineering/references/
03-api-design-for-researchers.md` (or wherever the skill's bash
+ Python interop lives) capturing this pattern:

> **Bash parsing of YAML/JSON written by Python**: if your bash
> script reads a YAML/JSON file that was written by a Python
> heredoc using PyYAML's `safe_dump` or `json.dump`, do NOT use
> `awk -F'"'` or `grep '"key":'` style parsers. PyYAML's default
> output is unquoted for plain ASCII scalars (`key: value`), and
> JSON's stable form is quoted -- a single parser cannot handle
> both reliably. Either (a) parse with a YAML-aware tool
> (`yq`, `python3 -c "import yaml; ..."`), or (b) write a
> form-tolerant parser that handles all three scalar styles
> (plain / double-quoted / single-quoted) explicitly.

This is a research-software-engineering rule because it's
exactly the kind of "the test I have doesn't cover the form
my writer actually emits" mismatch that production-grade
scientific scripts trip on routinely.

**Evidence / minimal repro**: live-test transcript pasted by user
on 2026-05-14; the failure shows `cfg_user` evaluating empty even
though the config file has a valid `user: aattia` line. Synthetic
harness with 11 cases (plain / double-quoted / single-quoted /
comment / whitespace / missing key / missing file / numeric scalar
/ etc.) demonstrates the new `yaml_scalar` helper handles all
forms correctly; ran during the fix commit. The fix + harness are
described in audit doc `docs/AUDIT_2026-05-12.md` H5
"REGRESSION + AMENDED" block.

**Secondary observation**: the live test ALSO surfaced that
`screen -S argovproxy -X quit` (the recovery hint baked into all
three H5 refusal branches) is INSUFFICIENT when argo-proxy
detached itself from the screen wrapper. The wrapper exits, the
listener pid keeps holding the port. The recovery hint now
suggests `kill <pid> && screen -S argovproxy -X quit`. This is a
"the recovery hint must be tested too" pattern -- error messages
that can't actually recover from the error are worse than no
hint, because the user trusts them.

**Status**: open (queued for upstream roll-up; concrete proposal
above is a 1-paragraph addition to the relevant skill reference).

## 2026-05-14 — `setdefault` for security-defaulted keys preserves the wrong default on upgraders

**Project context**: Phase 2b live test #1, second finding (after
the H5 yaml_scalar regression). The P2 fix changed
`write_argoproxy_config` to default `verbose: false` (privacy-
relevant; controls whether argo-proxy logs prompts to disk on the
compute node). The implementation used `data.setdefault('verbose',
verbose_default)` in the PyYAML merge path so that a user who had
explicitly chosen `verbose: true` would have their choice preserved.

**Trigger**: external-failure (user dumped the config file after a
successful H5 amendment verification and pasted contents; the file
showed `verbose: true` despite the script having been re-run
multiple times since the P2 fix landed).

**Skill(s) involved**: `research-software-engineering` (the rule
this would belong under is "API design / defaults that change
meaning between versions").

**Observation**: `setdefault` is the right primitive for keys
where the file's existing value reflects a real user choice
(e.g. `argo_base_url`: a user pointing at a dev Argo endpoint
should not have that overwritten on every config rewrite). It is
the WRONG primitive for keys where the prior value was set
automatically by an older version of the same script -- in that
case, "preserving" the old value silently keeps the upgrader on
the OLD default, defeating the entire purpose of changing the
default. From the file alone you cannot tell "user explicitly
chose X" from "old script defaulted to X". For security-relevant
defaults this means `setdefault` is unsafe; the explicit-opt-in
channel must live elsewhere (CLI flag / env var) so the file
content can be authoritatively overwritten on every write.

**Proposed action**: Add a rule (or extend the existing one) to
`research-software-engineering` covering "changing security-
relevant defaults across versions." Concrete shape:

> **Defaults that change meaning between versions**: when a new
> version of a script flips a security-relevant default (e.g.
> verbose-logging off, debug mode off, telemetry off), do NOT
> use `setdefault` / "preserve existing value" merge logic in
> the config writer for that key. From the file alone you cannot
> distinguish "user explicitly opted in" from "previous version
> defaulted in." For security defaults the answer is to:
> (a) overwrite the key with the script's chosen default on every
>     write,
> (b) provide an explicit opt-in channel (CLI flag / env var) for
>     users who really want the non-default behavior, and
> (c) document the upgrade-path implication: pre-existing files
>     will have the new default applied on the first write after
>     upgrade, regardless of their prior contents.
>
> `setdefault` IS appropriate for keys that genuinely vary by
> deployment (e.g. alternate API endpoints, custom timeouts) --
> values the user picked deliberately and that have nothing to
> do with the script's security posture.

This rule pairs naturally with the bash/PyYAML interop rule above:
both are "writer's view of the file" disciplines that come up when
a shell script + Python heredoc cooperate to manage a YAML config.

**Evidence / minimal repro**: Phase 2b live test #1 transcript;
user pasted `~/.config/argoproxy/config.yaml` contents showing
`verbose: true` (last line of file) after the P2 fix had been
shipped + the script re-run multiple times. The config also showed
`argo_base_url` appended at the bottom in non-alphabetical
position, evidence that the `setdefault('argo_base_url', ...)` in
the same merge block had run on a config that already had every
other key -- the appendix-positioning is PyYAML's `safe_dump
sort_keys=False` insertion-order signature for a key that was
absent originally and got added during the merge.

**Status**: open (queued for upstream roll-up).

## 2026-05-15 — exit-summary "what to do next" hints must be scope-keyed, not action-keyed

**Project context**: Phase 2b live test #1, third finding. The N1
fix (Ctrl+C exit summary in `cleanup_local`) listed three reuse
hints: "To use it again", "To fully stop: bash <self> stop", "To
remove all artifacts: bash <self> clean". The user successfully
Ctrl+C'd a foregrounded `client` and asked whether Ctrl+C should
become equivalent to `stop`.

**Trigger**: external-failure (more precisely, external-confusion;
the user wasn't sure what each named action would actually do
because the action names didn't communicate scope).

**Skill(s) involved**: `human-facing-doc-authoring` (this is an
error-message authoring discipline, but those messages are
themselves a form of human-facing doc); secondarily
`research-software-engineering` (CLI design / shell-tool UX).

**Observation**: the original three hints were action-keyed
("stop", "clean") and assumed the user knew which action mapped
to which scope. They didn't. After Ctrl+C, the user's actual
mental model is "I just stopped this; what other state from this
session is still around, and what do I do about each piece?" --
a SCOPE question, not an action question. Worse: the "To fully
stop: bash <self> stop" hint was misleading on inspection because
`mode_stop` would print "Nothing to stop locally" (the local
listener was already gone, killed by `cleanup_local` itself one
log line above).

The right fix is to invert the mental model: list each
INDEPENDENTLY-RESIDENT piece of state, then for each piece show
the exact command (with parameters filled in) that touches it.
The user makes a scope decision, not an action decision. For
this script there are three pieces (SSH multiplex master, remote
argo-proxy, local config/cache) and the new summary lists them
explicitly with each scope's exact command.

The deepest fix observation: action names like "stop" / "clean"
already imply specific scopes, but those scopes are NOT
documented at the scope's point of relevance (the Ctrl+C
moment). The user has to reverse-engineer the scope mapping from
the action names. Inverting -- making the scope explicit and
deriving the action from it -- removes the reverse-engineering
step.

**Proposed action**: Add a guideline to
`human-facing-doc-authoring` (probably as a new bullet under
"Universal conventions" or as a short reference file
`references/error-message-authoring.md`) covering exit-summary /
error-message authoring discipline:

> **Scope-keyed, not action-keyed, "what to do next" hints**:
> when an error message or exit summary lists "what you can do
> next" actions, list them by SCOPE (what state each touches),
> not by action name. The user is in a "what do I want to keep
> alive vs tear down" mental model at that moment, not a "what
> are this tool's verbs called" mental model. Show the exact
> command (with all parameters filled in from runtime context)
> for each scope, NOT the action name + reverse-engineerable
> scope. Verify the command would actually do something useful
> at the moment it prints (e.g. don't suggest `stop` after
> already stopping the local listener -- the user would run it
> and see "nothing to stop", which corrodes trust in the
> message).

This composes well with the existing `human-facing-doc-authoring`
"Tone and prose" guidelines and with the universal conventions
about cross-references being links rather than action names.

**Evidence / minimal repro**: original Phase 2b N1 summary
(commit `564cb26`) had three action-keyed hints; user's
question-after-success on 2026-05-15 explicitly named the
scope-vs-action confusion ("It is OK if we make Ctrl+C
equivalent to argon_anywhere.sh stop, but we need to be super
clear about it"). The user's "we need to be super clear"
identifies the missing axis. The fix in the next commit
demonstrates the scope-keyed alternative.

**Status**: open (queued for upstream roll-up).

## 2026-05-15 — test-plan stimulus must actually exercise the assertion site

**Project context**: Phase 2c+3 live test #1, post-test
postmortem. Two of fourteen tests (Test 2b + Test 5b) failed not
because the underlying code was wrong but because the chosen test
stimulus didn't exercise the code path the assertion was written
against. Both defects shared the same root cause.

**Trigger**: external-failure (the user ran the tests as
documented; both produced empty output where output was expected;
diagnosis revealed the test stimulus didn't traverse the
assertion's code path).

**Skill(s) involved**: `human-facing-doc-authoring` (test plans
are human-facing docs); secondarily `research-software-engineering`
(test design discipline).

**Observation**: I designed both Test 2b and Test 5b with the
naive "set up state X + run command Y + look for output Z"
template. The state was a synthetic on-disk SSH-failure lock file.
The output was the recovery message printed by `ssh_attempt_pre`.
The chosen command Y was `bash argo_anywhere.sh status`. But
`status` mode is purely local checks (`lsof :64742`, `curl /health`
to localhost, `jq` on the OpenCode config) -- it doesn't make any
SSH calls, so `ssh_attempt_pre` never fires, so the lock file is
unread, so the recovery message never prints. The test produced
empty output not because the code was broken but because the
stimulus didn't traverse the asserted path. (Same defect appeared
in Test 5b under `--probe-nodes status` -- the flag is parsed but
unused because `status` doesn't call `pick_node`.)

The deeper observation: when authoring a test that exercises an
internal code path, **verify the chosen stimulus actually traverses
that path before declaring the test designed**. I should have
caught this by tracing through the script: "what subcommands call
`ssh_attempt_pre`? `status` is not one of them. Pick a different
stimulus." Instead I assumed the in-memory mental model
("`--probe-nodes` triggers SSH attempts") was correct and the user
ran into the empty-output failure before the assumption was caught.

**Proposed action**: Add a discipline to
`human-facing-doc-authoring` (or to the research-software-engineering
testing-strategies reference) covering test-plan stimulus
verification. Concrete shape:

> **Test stimulus must exercise the assertion site**: when
> authoring a test that exercises an internal code path
> (an SSH-failure lock recovery message, a config-file merge
> branch, a fail-loud guard, etc.), verify the chosen STIMULUS
> command actually traverses the ASSERTION site's code path
> before declaring the test designed. The naive
> "set up state X + run command Y + look for output Z" template
> silently fails when Y doesn't exercise the code reading X.
>
> Concrete check: trace the call graph from Y to the assertion
> site, OR add a print statement at the assertion site and
> confirm Y's invocation prints it, OR write a pure-function
> unit test that bypasses subcommand selection entirely (sourcing
> the helper out of the script directly).
>
> When in doubt, prefer pure-function unit tests + code-review
> (structural proof) over end-to-end synthetic stimuli. Code
> review of "every callsite uses pattern X" is a legitimate
> stand-in when behavior tests can't be cleanly arranged.

This composes with the "scope-keyed messages" discipline (the
prior agent-feedback entry) -- both are about making the test /
message itself accurately reflect runtime behavior, not the
author's mental model of runtime behavior.

**Evidence / minimal repro**: `notes/test_plan_phase2c3.md` Tests
2b and 5b as originally written; user-pasted output showing empty
results from the documented commands. Workarounds applied during
the test session (Test 2 used a pure-function unit test; Test 5
used code-review verification of the dedup pattern). Both tests
PASSED via the workarounds; the underlying code was correct all
along. The test plan got an explicit "Live-test #1 results"
section documenting the defects + the workarounds; the audit-doc
STATUS blocks for M2 and L4+L5 stand unchanged.

**Status**: open (queued for upstream roll-up).

---

*Created 2026-05-14 by Ahmed Attia (with substantial AI assistance from
Claude per `CONTRIBUTORS.md`) from
[`scicomp-research-skills/templates/software-skeleton/notes/agent_feedback.md`](https://github.com/a-attia/scicomp-research-skills/tree/main/templates/software-skeleton/notes/agent_feedback.md).*
