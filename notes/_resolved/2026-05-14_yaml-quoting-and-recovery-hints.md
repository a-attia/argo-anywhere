# Resolved feedback entry: bash/PyYAML interop + recovery-hints-tested

| Field | Value |
|:------|:------|
| Date logged | 2026-05-14 |
| Date resolved | 2026-05-17 |
| F-ID(s) | F-03 (primary observation), F-05 (secondary observation) |
| Resolution | Codified upstream as rules 12.1 + 12.3 in `skills/research-software-engineering/references/12-shell-and-cross-language-interop.md` |
| Upstream commit | `686b3a1` (Session A, scicomp-research-skills repo) |
| Original location | `notes/agent_feedback.md` lines 195-269 (pre-cleanup) |

This entry was extracted from `agent_feedback.md` during the 2026-05-20
post-Session-A cleanup. The original chronological breadcrumb (date +
title) remains in `agent_feedback.md` as a stub linking back here.

---

## 2026-05-14 -- bash/PyYAML interop trap: `awk -F'"'` silently degrades on plain scalars

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

**Status**: resolved upstream 2026-05-17 (commit `686b3a1`).
Primary observation became rule 12.1 (YAML / JSON quoting on the
bash / Python interop boundary); secondary observation became
rule 12.3 (Error-message recovery hints must themselves be
tested).
