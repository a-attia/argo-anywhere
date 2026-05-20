# Resolved feedback entry: exit-summary "what to do next" hints scope-keyed

| Field | Value |
|:------|:------|
| Date logged | 2026-05-15 |
| Date resolved | 2026-05-17 |
| F-ID(s) | F-08 |
| Resolution | Codified upstream as rule 12.6 in `skills/research-software-engineering/references/12-shell-and-cross-language-interop.md` |
| Upstream commit | `686b3a1` (Session A, scicomp-research-skills repo) |
| Original location | `notes/agent_feedback.md` lines 345-423 (pre-cleanup) |

---

## 2026-05-15 -- exit-summary "what to do next" hints must be scope-keyed, not action-keyed

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

**Status**: resolved upstream 2026-05-17 (commit `686b3a1`) as
rule 12.6. Upstream landed under
`research-software-engineering` (not `human-facing-doc-authoring`
as originally proposed) because the rule's audience is
shell-script + CLI authors more than narrative-prose authors.
