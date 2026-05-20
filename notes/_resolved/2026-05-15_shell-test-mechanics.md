# Resolved feedback entry: shell-script unit-test mechanics

| Field | Value |
|:------|:------|
| Date logged | 2026-05-15 |
| Date resolved | 2026-05-17 |
| F-ID(s) | F-07 |
| Resolution | Codified upstream as rule 12.5 in `skills/research-software-engineering/references/12-shell-and-cross-language-interop.md` |
| Upstream commit | `686b3a1` (Session A, scicomp-research-skills repo) |
| Original location | `notes/agent_feedback.md` lines 507-606 (pre-cleanup) |

---

## 2026-05-15 -- shell-script unit-test mechanics: pipe-eats-exit-code + awk-extract-fragility

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

**Status**: resolved upstream 2026-05-17 (commit `686b3a1`) as
rule 12.5. Landed under `research-software-engineering` (the
proposal's preferred home) rather than `human-facing-doc-authoring`.
