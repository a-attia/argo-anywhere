# Resolved feedback entry: test stimulus must actually exercise the assertion site

| Field | Value |
|:------|:------|
| Date logged | 2026-05-15 |
| Date resolved | 2026-05-17 |
| F-ID(s) | F-06 |
| Resolution | Codified upstream as rule 12.4 in `skills/research-software-engineering/references/12-shell-and-cross-language-interop.md` |
| Upstream commit | `686b3a1` (Session A, scicomp-research-skills repo) |
| Original location | `notes/agent_feedback.md` lines 425-505 (pre-cleanup) |

---

## 2026-05-15 -- test-plan stimulus must actually exercise the assertion site

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

**Status**: resolved upstream 2026-05-17 (commit `686b3a1`) as
rule 12.4.
