# Handoff — extended-thinking probe + documentation cleanup (session of 2026-08-25)

**Status**: complete and **pushed** (`origin/main` at `1c7ef5b`). Nothing
released, no tag created, no engine change.
**Audience**: the next agent (or the maintainer) picking this up cold.
**Read after**: `AGENTS.md`, then
[`impl_thinking_support.md`](impl_thinking_support.md) — that note is the
single source of truth for the measurements; this file is a map of where
things stand and what to be careful of.

Unlike [`handoff_2026-08-10_shared_node.md`](handoff_2026-08-10_shared_node.md),
this session left **nothing half-finished**. There is no work in flight to
resume. Read this if you are about to touch thinking/reasoning parameters, the
docs that were rewritten, or the probe script.

---

## Contents

- [1. What this session was](#1-what-this-session-was)
- [2. What shipped](#2-what-shipped)
- [3. The findings that constrain future work](#3-the-findings-that-constrain-future-work)
- [4. Decisions taken (do not relitigate without new evidence)](#4-decisions-taken-do-not-relitigate-without-new-evidence)
- [5. Corrections to claims made during this session](#5-corrections-to-claims-made-during-this-session)
- [6. Operational notes](#6-operational-notes)
- [7. What is open](#7-what-is-open)

---

## 1. What this session was

It started as a question — "does Opus 5 support thinking?" — and widened to
"are our per-tool configurations comprehensive?". Answering the second
honestly required measuring the stack rather than reading it, because the
project's documented account of thinking support was both stale and silent on
every model released since Opus 4.7.

The measurement work then exposed enough documentation drift that the session
turned into a four-document review pass. Both halves are pushed.

## 2. What shipped

Seven commits, `ff4defa..1c7ef5b`, all on `main`:

| Commit | What |
|:---|:---|
| `ff4defa` | Track `impl_model_metadata.md` (written 2026-08-14, left untracked) |
| `c95b0e9` | `scripts/probe_capabilities.py` + `impl_thinking_support.md` |
| `4632c99` | Replace the opus-4-7 warning with a measured matrix (README / AGENTS / LIMITATIONS) |
| `485eb66` | Split `UPGRADING.md` (~1000 → 169 lines) → `UPGRADING_HISTORY.md` |
| `7b98489` | `SECURITY.md`: four corrections a reader could have acted on |
| `1a38396` | `TESTING.md`: fix recipes that silently did nothing |
| `1c7ef5b` | CHANGELOG |

**Zero engine changes.** Both engine copies are byte-identical; `bash -n`
clean. The only new executable code is `scripts/probe_capabilities.py`, which
is a maintainer tool that nothing imports.

Gates at push: 633 passed / 1 skipped, `ruff check src tests scripts` clean.

> **CI note.** No CI run had appeared for `1c7ef5b` ~2 minutes after the push
> (newest run on `main` was still v3.4.0's). The push landed —
> `git ls-remote` confirmed the sha — so this is GitHub-side queueing. Worth a
> glance at the Actions tab; nothing is at risk, since the push is docs plus a
> standalone script and the same gates were run locally.

## 3. The findings that constrain future work

Full detail in [`impl_thinking_support.md`](impl_thinking_support.md). The
four that change what you may build:

1. **We write zero thinking configuration**, deliberately.
   `grep -cEi 'thinking|reasoning_effort|budget_tokens'` on the engine is `0`.
2. **Two vocabularies.** `/v1/messages` takes `thinking.type ∈ {enabled,
   adaptive}`. `/v1/chat/completions` takes `reasoning.mode ∈ {auto, enabled,
   disabled}` and **rejects `adaptive` outright**. A parameter that works on
   one path may not exist on the other.
3. **No shape works on every model, and the split does not follow version
   order.** `enabled` fails on `claudeopus5` + `claudesonnet5`; `adaptive`
   fails on `claudeopus41`, `claudeopus45` + `claudesonnet45`; the middle
   generation takes either. The rejection is always HTTP 200 with **zero
   bytes** — never a clean error.
4. **Thinking is unreachable via `/v1/chat/completions`.** Every
   `reasoning.mode` value returns empty `reasoning_content`. aider and
   OpenCode therefore cannot get thinking at all, and no config we write
   changes that. Claude Code uses the native path, ships its own correct
   per-model table, and works unaided including on v5.

**The trap this sets**: "our configs are minimal, let's write full per-model
defaults" is a reasonable-sounding move that is wrong here. For aider and
OpenCode it writes keys that provably do nothing; for Claude Code our table
would go stale faster than the client's — v5 is the existence proof, since the
client already routes it correctly and the upstream shim does not.

## 4. Decisions taken (do not relitigate without new evidence)

- **Not filing the three upstream reports** (maintainer, 2026-08-25). The Argo
  API has a long limitation backlog and these are low-yield. Recorded in
  `impl_thinking_support.md` §10. Consequence: treat the v5 shim gap and the
  OpenAI-path ceiling as **fixed properties of the stack** when planning, not
  as bugs awaiting a fix. The probe detects a fix if one ever lands, which is
  cheaper than tracking an issue.
- **`env.ANTHROPIC_MODEL` auto-default is dead.** It was queued for v2.3 to
  dodge the opus-4-7 bug. That bug was fixed upstream in 2026-06, so the
  workaround would now pin users to a model two generations old. Removed from
  `LIMITATIONS.md`; will not ship as specified.
- **Option 2 (a thinking floor for older Claude Code against v5) stays
  deferred** — but note §4 above makes it the *only* remaining lever for a
  non-Claude-Code client on v5, since the shim will not be fixed on our
  account. If a user reports it, it escalates rather than staying deferred.

## 5. Corrections to claims made during this session

Recorded because each was stated confidently before being falsified, and the
pattern is the useful part.

1. **"`claude --model claude-opus-5` will fail."** Wrong. Inferred from the
   opus-4-7 history without checking the client. Claude Code 2.1.241 sends
   `adaptive` for exactly the v5 models; it works today. Client version is
   load-bearing — 2.1.143 (the version in the v2.2.0 notes) predates v5.
2. **"`adaptive` is the only universally-accepted value."** Wrong, and this
   one is the reason the probe script exists. It came from a hand sweep over
   seven models; the full ten-model sweep found `adaptive` fails silently on
   three models the hand pass never tried, confirmed afterwards by curl.
   `impl_thinking_support.md` §3.1 keeps the wrong table under a superseded
   banner deliberately.
3. **The probe's own first version was broken** in the same way. It probed
   with `"say ok"`, which does not induce thinking even where thinking works,
   so it would have reported "no thinking" for every model. Fixed before the
   full sweep. A tool built to prevent confident wrong tables was briefly
   capable of producing one.
4. **My `notes/README.md` index row for the thinking note was self-stale**
   within the hour — written before the probe ran, it stated the falsified
   universal-`adaptive` claim in the index that exists to summarise the note.
   Caught during the pre-commit review.

The generalisable lesson, and it is the same one as the 2026-08-10 session's:
**a partial sweep produces a confident universal rule.** Measure the whole
space or state the sample.

## 6. Operational notes

- **The maintainer's live channel is what this session's traffic ran through**
  (`:64743` → `compute-01.cels.anl.gov`, argo-proxy 3.2.3 / llm-rosetta
  0.7.1). The `stop` / `clean` cautions from
  [`handoff_2026-08-10_shared_node.md`](handoff_2026-08-10_shared_node.md) §6
  remain in force.
- **`scripts/probe_capabilities.py` spends gateway quota** — two to four
  completions per model, ~20 requests for a full Anthropic sweep. Use
  `--model` while iterating. It is opt-in, never on the `connect` path, and
  deliberately not wired into the engine.
- **Temp artifacts from this session were cleaned up.** The logging
  pass-through proxy used for the wire captures (`tapproxy.py`), its logs, and
  the aider/OpenCode scratch configs were deleted from the OS temp dir. No
  repo files were left behind. If you need the technique again, the script was
  ~70 lines: a `ThreadingHTTPServer` that logs the parsed request body and
  forwards verbatim to the real proxy — point `ANTHROPIC_BASE_URL` /
  `--openai-api-base` at it.
- **The pytest suite number moves.** It was 633/1-skipped at this push; do not
  cite a count from a doc, run `pytest -q`.

## 7. What is open

Nothing from this session is half-done. Adjacent work that remains open,
in the order I would pick it up:

1. **`impl_upstream_hardening.md` is still DRAFT.** This session discharged
   its *doc* half (UP-13, the stale opus-4-7 claims). The engine half is
   untouched: **UP-12** (the `import argoproxy.app` probe — our two install
   probes both PASS on an argo-proxy that cannot start) and **UP-02** (the
   soft version floor, whose `_version_ge` helper exists and is unused). UP-12
   is the one with real user impact.
2. **`TESTING.md` coverage gaps**, now documented rather than fixed. Nothing
   in it exercises aider, D-032, D-034 or D-035; its newest section is v3.1.0.
   Writing those live tests is real work, not a doc pass.
3. **v3.3.0 is still not yanked on PyPI.** Flagged in the v3.4.0 commit as
   outstanding; still outstanding.
4. **`impl_model_metadata.md`** (now tracked) recommends option 1 —
   classifying `list-models`' provider column on `owned_by` rather than our
   regex — as opportunistic hygiene, ~5 lines.

---

*Created 2026-08-25 by Ahmed Attia (with AI assistance from Claude per
[`CONTRIBUTORS.md`](../CONTRIBUTORS.md)). All measurements in the linked impl
note were taken live against `compute-01.cels.anl.gov` on 2026-08-25 with
argo-proxy 3.2.3 / llm-rosetta 0.7.1, Claude Code 2.1.241, aider 0.86.2,
OpenCode 1.18.23.*
