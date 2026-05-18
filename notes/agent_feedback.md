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

## 2026-05-15 — shell-script unit-test mechanics: pipe-eats-exit-code + awk-extract-fragility

**Project context**: Phase 2d live test #1, post-test postmortem.
Two test-plan defects surfaced (Tests 2b + 4b). Both share the
same family as the Phase 2c+3 entry above ("test stimulus must
actually exercise the assertion site"), but at a lower-level
mechanical layer: the test harness mechanics themselves were
wrong, not the choice of subcommand.

**Trigger**: external-failure (user ran the tests; one reported
the wrong exit code because of a pipe artifact; one outright
failed to source the function-under-test because awk extraction
captured a partial body).

**Skill(s) involved**: `human-facing-doc-authoring` (test plans
are human-facing docs); secondarily `research-software-engineering`
(shell-script testing discipline).

**Observation**: across two consecutive live tests (Phase 2c+3 +
Phase 2d), four total test-plan defects emerged, all sharing the
common root cause "the test harness mechanism didn't read /
extract / route what the assertion expected." The Phase 2c+3
defects were at the SUBCOMMAND-CHOICE layer (using `status`
where SSH-attempt activity was expected); the Phase 2d defects
are at the SHELL-MECHANICS layer (`| tail` eats exit code; awk
extraction of function bodies with embedded `}` lines breaks).
Both layers benefit from explicit testing-discipline rules.

**Proposed actions** (two complementary rules):

1. **Exit-code capture through pipes**: when a test pipeline ends
   in a transformer (`| tail`, `| head`, `| grep`, etc.), `$?`
   reads the transformer's exit code, NOT the upstream command
   under test. For tests where the exit code is the assertion,
   either:
   - drop the pipe and redirect output to a file or `/dev/null`,
     then read `$?` directly:
     ```sh
     command_under_test arg >/dev/null 2>&1
     echo "exit code: $?"
     ```
   - OR use bash's `${PIPESTATUS[0]}` to capture the leftmost
     pipe element's exit code:
     ```sh
     command_under_test arg 2>&1 | tail -15
     echo "exit code: ${PIPESTATUS[0]}"
     ```
   The latter is bash-only (POSIX sh doesn't have PIPESTATUS);
   for portable harnesses prefer the former.

2. **awk function-body extraction is fragile when bodies contain
   heredocs with `}` lines**: the common pattern
   `awk '/^funcname\(\) \{/,/^}$/'` relies on the closing `}`
   being unique-on-a-line, but bash functions whose bodies embed
   JSON / YAML heredocs break that assumption (the heredoc's
   closing `}` matches first and truncates the extraction).
   Three alternative approaches:
   - For one-line guards (asserts, single-statement bodies),
     exercise the predicate directly inline without extracting
     the surrounding function body. The L6 test rewrote
     `[ -n "${PROXY_PORT:-}" ] || die "..."` as a direct
     `bash -c` invocation with the same predicate.
   - For multi-line writers with heredocs, use brace-counting
     extraction (parse the bash body counting `{` / `}` depth
     and find the matching closing `}` at the function's level).
     More complex but correct.
   - For functions designed for testability, factor the assertions
     out into separate `_check_invariants_<name>` helpers that
     don't embed heredocs. Best long-term but requires the source
     to be designed this way.

Both rules belong in either `human-facing-doc-authoring`'s
test-plan-authoring guidance OR a new shell-script-testing
reference under `research-software-engineering`. The latter is
probably the better home: these are shell-mechanics rules, not
narrative-prose rules.

**Pattern-detection observation**: this is the **second
postmortem in a row** that surfaced test-design defects of this
family (Phase 2c+3's two + Phase 2d's two = four total). The
consistency suggests this is a class of bug, not isolated
mistakes -- worth a dedicated discipline rule rather than
case-by-case fixes.

**Evidence / minimal repro**:
- Test 2b (Phase 2d live test #1): user pasted
  `[err ] ... Refusing to overwrite a broken Claude Code config.`
  followed by `exit code: 0`. The exit code 0 was the trailing
  `| tail -15`'s; the actual `die` exited 2.
- Test 4b (Phase 2d live test #1): user got
  `/tmp/_writer.sh: line 53: syntax error: unexpected end of
  file` + `command not found: write_opencode_config` + `exit
  code: 127`. The awk extraction captured up to a `}` line
  inside the function's JSON heredoc, producing an unterminated
  bash body when sourced.

**Status**: open (queued for upstream roll-up); pairs naturally
with the "test stimulus must actually exercise the assertion
site" entry (same family, different layer).

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

**Status**: open (queued for upstream roll-up). Discipline rule
candidate: when an upstream-stack finding surfaces, document it
in BOTH the per-project LIMITATIONS doc (full diagnosis) AND the
top-of-README quick-orient callout (workaround only). Auto-default
fix queued separately for v2.3.

---

*Created 2026-05-14 by Ahmed Attia (with substantial AI assistance from
Claude per `CONTRIBUTORS.md`) from
[`scicomp-research-skills/templates/software-skeleton/notes/agent_feedback.md`](https://github.com/a-attia/scicomp-research-skills/tree/main/templates/software-skeleton/notes/agent_feedback.md).*
