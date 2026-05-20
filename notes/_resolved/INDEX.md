# Resolved feedback index

This directory holds `notes/agent_feedback.md` entries that have been
actioned upstream in `scicomp-research-skills` (or in another upstream
target). Each entry is one file. The original entry in
`agent_feedback.md` has been replaced by a stub linking back to its
file here.

**Convention**: an entry lives here when the proposal it contained has
been codified upstream + the upstream artefact is in production. If
the proposal was filed-but-not-yet-actioned (e.g. as a GitHub issue),
the entry stays in `agent_feedback.md` with a "filed as #N" marker
until the issue closes.

For superseded / filed-as-issue artefacts that aren't agent_feedback
entries, see [`../_archive/INDEX.md`](../_archive/INDEX.md).

---

## Entries (newest first)

| Date logged | Date resolved | F-ID(s) | Title | Resolution | Upstream commit | File |
|:------------|:--------------|:--------|:------|:-----------|:----------------|:-----|
| 2026-05-15 | 2026-05-17 | F-07 | shell-script unit-test mechanics (pipe-eats-exit-code + awk-extract-fragility) | rule 12.5 in `research-software-engineering/references/12-shell-and-cross-language-interop.md` | `686b3a1` | [`2026-05-15_shell-test-mechanics.md`](2026-05-15_shell-test-mechanics.md) |
| 2026-05-15 | 2026-05-17 | F-06 | test-plan stimulus must exercise the assertion site | rule 12.4 in `12-shell-and-cross-language-interop.md` | `686b3a1` | [`2026-05-15_test-stimulus-exercises-assertion.md`](2026-05-15_test-stimulus-exercises-assertion.md) |
| 2026-05-15 | 2026-05-17 | F-08 | exit-summary hints must be scope-keyed, not action-keyed | rule 12.6 in `12-shell-and-cross-language-interop.md` | `686b3a1` | [`2026-05-15_exit-summary-scope-keyed.md`](2026-05-15_exit-summary-scope-keyed.md) |
| 2026-05-14 | 2026-05-17 | F-04 | `setdefault` for security-defaulted keys preserves wrong default on upgraders | rule 12.2 in `12-shell-and-cross-language-interop.md` | `686b3a1` | [`2026-05-14_setdefault-security-defaults.md`](2026-05-14_setdefault-security-defaults.md) |
| 2026-05-14 | 2026-05-17 | F-03, F-05 | bash/PyYAML interop trap + recovery-hints-must-be-tested | rules 12.1 + 12.3 in `12-shell-and-cross-language-interop.md` | `686b3a1` | [`2026-05-14_yaml-quoting-and-recovery-hints.md`](2026-05-14_yaml-quoting-and-recovery-hints.md) |

---

## Summary

- **Total resolved entries**: 5 (covering 6 F-IDs).
- **Most recent resolution**: 2026-05-17 (scicomp-research-skills
  commit `686b3a1`, Session A roll-up).
- **All 5 entries** were rolled up in the same Session A commit
  (`686b3a1`) which introduced the new reference 12
  (`12-shell-and-cross-language-interop.md`) to the
  `research-software-engineering` skill.

---

## When to add a new entry here

Append a row to the table + create the corresponding file when:

1. An entry in `../agent_feedback.md` has been actioned upstream
   AND the upstream artefact is shipped + visible in production.
2. The action is more than cosmetic (a fix, a new rule, a new
   reference). Trivial typo fixes don't warrant archival.

The stub left in `agent_feedback.md` should preserve the original
date + title so chronological scanning still finds it, with a
"RESOLVED upstream in commit X" body pointing here.

---

*Created 2026-05-20 by A. Attia during post-Session-A cleanup of the
argo-anywhere project. The directory + index convention was
co-designed with the framework's archive+resolved convention being
back-propagated to `scicomp-research-skills` templates.*
