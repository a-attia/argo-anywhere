# Implementation plan: extended-thinking support across the three CLI tools

**Status**: **investigated; designing** (2026-08-25). No code committed,
nothing scheduled. Holds no D-number — per the `notes/README.md`
convention, a note that has not shipped does not hold one.
**Trigger**: user question 2026-08-25 — "does Opus 5 in the argo-api
support thinking?", widening to "are our configurations comprehensive?"
**Baseline**: `argo-anywhere` v3.4.0, engine `SCRIPT_VERSION=2.4.0`;
on-node `argo-proxy 3.2.3` + `llm-rosetta 0.7.1` on
`compute-01.cels.anl.gov`.
**Method**: live probes against a warm channel, plus a logging
pass-through proxy interposed between each CLI tool and argo-proxy to
capture the exact request bodies the tools emit. Nothing in this note is
read from upstream source or inferred from prior notes unless labelled
so.

---

## Table of contents

- [1. Why this note exists](#1-why-this-note-exists)
- [2. What we write today](#2-what-we-write-today)
- [3. Findings](#3-findings)
  - [3.1 F1 — the gateway's per-model thinking matrix](#31-f1--the-gateways-per-model-thinking-matrix)
  - [3.2 F2 — the shim has no v5 rows](#32-f2--the-shim-has-no-v5-rows)
  - [3.3 F3 — Claude Code ships its own correct table](#33-f3--claude-code-ships-its-own-correct-table)
  - [3.4 F4 — aider and OpenCode cannot reach thinking](#34-f4--aider-and-opencode-cannot-reach-thinking)
  - [3.5 F5 — the v5 failure signature changed](#35-f5--the-v5-failure-signature-changed)
  - [3.6 F6 — incidental: gpt-5 502 on the OpenAI path](#36-f6--incidental-gpt-5-502-on-the-openai-path)
- [4. Answering the maintainer's question](#4-answering-the-maintainers-question)
- [5. Options](#5-options)
- [6. Recommendation](#6-recommendation)
- [7. What would falsify this note](#7-what-would-falsify-this-note)
- [8. Open questions](#8-open-questions)
- [9. Action items](#9-action-items)
- [10. Why the upstream reports are not being filed](#10-why-the-upstream-reports-are-not-being-filed)

---

## 1. Why this note exists

The question started narrow — does Opus 5 support thinking? — and the
answer turned out to be yes, but only through one of the two request
shapes the gateway accepts, and only on one of the two API paths our
three CLI tools use. Establishing that required measuring the stack
rather than reading it, because the repo's existing account of thinking
support is both stale (it describes Opus 4.7 as broken, fixed upstream in
2026-06) and silent on every model released since.

The wider question the maintainer then asked — are our configurations
comprehensive? — has a short answer with a long justification. The short
answer is no: we write no thinking-related key anywhere. The long
justification is that for two of our three tools, writing one would not
help, and this note exists mainly to record *why*, so the next session
does not re-derive it.

---

## 2. What we write today

Measured, not recalled:

```text
grep -cEi 'thinking|reasoning_effort|budget_tokens' \
  src/argo_anywhere/engine/argo-anywhere.sh   ->   0
```

Per writer:

| Writer | Emits | Thinking control |
|:---|:---|:---|
| `write_claudecode_config` | `env.ANTHROPIC_BASE_URL`, `env.ANTHROPIC_API_KEY` | none |
| `write_opencode_config` | per model: `name`, `modalities` | none |
| `write_aider_config` | `use_temperature: false`, `streaming: true` | none |

We configure transport, plus one workaround (`use_temperature: false`,
because reasoning models return an empty stream when `temperature` is
present). Thinking behaviour is whatever each tool defaults to.

---

## 3. Findings

### 3.1 F1 — the gateway's per-model thinking matrix

Direct `curl` against `/v1/messages` on the warm channel, streaming a
one-word prompt, recording response size:

> **Superseded 2026-08-25 (same day) by the probe script.** The table
> below was hand-measured over seven models and concluded "`adaptive` is
> the only universally-accepted value". Running
> `scripts/probe_capabilities.py` over all ten Anthropic models
> falsified that: **`adaptive` fails silently on `claudeopus41`,
> `claudeopus45` and `claudesonnet45`** — the three models the hand pass
> never tried. Confirmed by hand afterwards
> (`claude-opus-4.1` + `adaptive` → HTTP 200, 0 bytes;
> + `enabled` → 2331 bytes). Corrected matrix immediately below; the
> original is kept because the error is the point — a partial sweep
> produced a confident universal rule, which is exactly the failure mode
> the script exists to prevent.

**Corrected (full sweep, 2026-08-25):**

| Model | `enabled` | `adaptive` |
|:---|:---|:---|
| `claudeopus41`, `claudeopus45`, `claudesonnet45` | works | **200, 0 bytes** |
| `claudehaiku45`, `claudesonnet46`, `claudeopus46`, `claudeopus48` | works | works |
| `claudeopus47` | answers, no thinking seen | answers, no thinking seen |
| `claudesonnet5`, `claudeopus5` | **200, 0 bytes** | works |

There is **no shape that works on every model**, and the split does not
follow version order. `claudeopus47` is its own case: it answers on both
shapes but emitted no thinking block on a prompt that produced one on
its neighbours — unexplained, worth a look.

**Original hand-measured table (partial; kept for provenance):**

| Model | `thinking.type: enabled` | `thinking.type: adaptive` |
|:---|:---|:---|
| `claude-haiku-4.5` | works | works |
| `claude-sonnet-4.6` | works | works |
| `claude-opus-4.6` | works | works |
| `claude-opus-4.7` | works | works |
| `claude-opus-4.8` | works | works |
| **`claude-sonnet-5`** | **HTTP 200, 0 bytes** | works |
| **`claude-opus-5`** | **HTTP 200, 0 bytes** | works |

Both aliases of opus-5 (`claude-opus-5`, `claude-5-opus`) behave
identically, as expected — they resolve to one `internal_name`.

Thinking is genuinely active under `adaptive`, not merely accepted: a
reasoning prompt with `output_config.effort: high` returned a `thinking`
content block with `thinking_delta` and `signature_delta` events, not
just text.

### 3.2 F2 — the shim has no v5 rows

Read from the installed shim on the node
(`llm_rosetta/shims/providers/argo/anthropic/provider.yaml`):

```yaml
reasoning:
  thinking_type: enabled          # provider default
  model_overrides:
    claudehaiku45: {thinking_type: enabled, budget_tokens_default_ratio: 0.8}
    claudesonnet4: {thinking_type: enabled, budget_tokens_default_ratio: 0.8}
    claudeopus47:  {thinking_type: adaptive}
    claudeopus48:  {thinking_type: adaptive}
    # no claudeopus5, no claudesonnet5
```

The file's own comment states the rule it then fails to apply:

```text
# Argo Anthropic thinking support matrix (tested 2026-06-18):
#   claudeopus47+:  adaptive only (enabled → 400)
```

Opus 5 and Sonnet 5 are "4.7+", so they need `adaptive`; with no override
row they inherit the provider default `enabled` and are rejected. This is
the same defect class as UP-08 → UP-10, now in its third instance
(4.7, 4.8, 5).

**Upgrading does not fix it.** `llm-rosetta 0.9.0` (2026-08-21, the
latest on PyPI at the time of writing) carries a byte-identical
`reasoning:` block — verified by downloading the wheel and reading it.

Behaviourally consistent with all probes: the shim **rewrites** the
client's value when an override exists, and **passes it through** when
none does. Sending `adaptive` to haiku-4.5 (override `enabled`) still
produced 93 `thinking_delta` events, i.e. it was rewritten rather than
rejected. This is inference from black-box behaviour, not from reading
the shim's dispatch code.

### 3.3 F3 — Claude Code ships its own correct table

Captured on the wire from Claude Code **2.1.241** by pointing
`ANTHROPIC_BASE_URL` at a logging pass-through proxy:

| Model | Sent by default | `max_tokens` |
|:---|:---|:---|
| `claude-haiku-4.5` | `{"type": "adaptive"}` | 32000 |
| `claude-sonnet-4.6` | `{"type": "enabled", "budget_tokens": 31999}` | 32000 |
| `claude-opus-4.7` | `{"type": "enabled", "budget_tokens": 31999}` | 32000 |
| `claude-opus-4.8` | `{"type": "enabled", "budget_tokens": 31999}` | 32000 |
| **`claude-sonnet-5`** | **`{"type": "adaptive"}`** | 64000 |
| **`claude-opus-5`** | **`{"type": "adaptive"}`** | 64000 |

Three things follow. Thinking is **on by default in every case** — Claude
Code never sends a request without a `thinking` block. It maintains its
own per-model table and **sends `adaptive` for exactly the models that
require it**. And it does so with no help from us.

Also visible: `display: "omitted"` (thinking happens but is not
rendered), and betas including `interleaved-thinking-2025-05-14` and
`thinking-token-count-2026-05-13`.

`claude -p "say ok" --model claude-opus-5` returns cleanly. **Claude Code
2.1.241 + Opus 5 works today.**

> **Correction to an earlier claim in this session.** Before running this
> capture, the agent asserted that `claude --model claude-opus-5` would
> fail, reasoning from the historical opus-4-7 pattern in
> `docs/LIMITATIONS.md`. That was wrong: it generalised "the gateway
> rejects `enabled`" into "the client sends `enabled`" without checking
> the client. The client version is load-bearing — 2.1.143 (the version
> in the v2.2.0 notes) predates the v5 models; 2.1.241 knows them.

### 3.4 F4 — aider and OpenCode cannot reach thinking

Same pass-through capture, default invocations against `claude-opus-5`:

| Tool | Version | Request keys sent |
|:---|:---|:---|
| aider | 0.86.2 | `messages`, `model`, `stream` |
| OpenCode | 1.18.23 | `max_tokens`, `messages`, `model`, `stream`, `stream_options`[, `tools`] |

Neither sends any thinking parameter. Two further probes:

1. **`aider --reasoning-effort high` is silently dropped.** The captured
   body is byte-identical to the default — no `reasoning_effort`, no
   error, no warning. The flag does nothing through this stack.
2. **Forcing it via `extra_body` produces the most informative error of
   the investigation**:

   ```text
   litellm.BadRequestError: OpenAIException - Failed to parse request:
   1 validation error(s): Expected one of ('auto', 'enabled', 'disabled')
   at 'reasoning.mode', got 'adaptive'
   ```

   The OpenAI-compat path has a **different vocabulary**:
   `reasoning.mode ∈ {auto, enabled, disabled}`, not `thinking.type`.
   `adaptive` is not a legal value there at all.

Testing all three legal values on `/v1/chat/completions`:

| Model | `reasoning.mode` | `reasoning_content` |
|:---|:---|:---|
| `argo:claude-opus-5` | `auto` | `""` (empty) |
| `argo:claude-opus-5` | `enabled` | `""` (empty) |
| `argo:claude-opus-5` | `disabled` | `""` (empty) |
| `argo:claude-opus-4.6` | `enabled` | field absent |
| `argo:claude-sonnet-4.6` | `enabled` | field absent |

Streaming confirms it: 17 KB of deltas on a reasoning prompt, every
`reasoning_content` chunk empty, zero non-empty. The bare
`reasoning_effort: high` key (LiteLLM's spelling) behaves the same.

**Conclusion: thinking is not reachable through `/v1/chat/completions` on
this gateway.** The parameter is accepted and validated, then yields
nothing. This is a gateway/shim limitation, not a config gap — no key we
could write to `~/.aider.conf.yml` or the OpenCode config would change
it.

### 3.5 F5 — the v5 failure signature changed

The opus-4-7 era failure surfaced as an SSE `event: error` naming
`thinking.type.enabled` — the diagnostic path recorded at
`notes/agent_feedback.md:557`. The v5 failure does not.

- **Streaming**: HTTP 200, **zero bytes**. No error event, no body.
- **Non-streaming**: HTTP **502** with a misleading message:

  ```text
  Failed to parse upstream response: 1 validation error(s):
  Value at 'choices[0].message' does not match any variant of
  SystemMessage | UserMessage | AssistantMessage | ToolMessage
  ```

That reads like a response-parsing defect, not a rejected request
parameter. Anyone debugging Opus 5 from this 502 will investigate the
wrong layer. Worth recording precisely because it defeats the diagnosis
path the earlier incident established.

### 3.6 F6 — incidental: gpt-5 502 on the OpenAI path

Found while testing whether any model surfaces reasoning content.
`argo:gpt-5` on `/v1/chat/completions` with a `reasoning` block returns a
hard 502:

```text
Failed to parse upstream response: 1 validation error(s):
Expected int at 'usage.prompt_tokens_details.cache_write_tokens',
got NoneType
```

Unrelated to thinking; an upstream response-validation bug. Not
investigated further — recorded so it is not lost.

---

## 4. Answering the maintainer's question

> *"Worth queuing: write all default configurations locally to each model
> rather than just writing minimal configurations, right?"*

Partly right, and worth narrowing.

**Where it would not help.** For aider and OpenCode, F4 says thinking is
unreachable regardless of configuration. Writing per-model thinking
defaults for them means writing keys that provably do nothing, or that
error outright (`adaptive` is rejected by `reasoning.mode`). A writer
asserting capability it has not verified against the proxy is precisely
the failure the **NO-SILENT-MODEL-DELETION INVARIANT** was added to
prevent — same family, different key.

**Where the instinct is right, for a different reason.** The genuine
problem this proposal is reaching for is not thin configs; it is that
**every hardcoded list we own drifts**. `_opencode_models_hardcoded`
still names Opus 4.7 as current. The aider temperature floor missed five
live models until 2026-08-12. The shim's own `model_overrides` is three
generations behind. Opus 4.7 → 4.8 → 5 is one finding, learned three
times.

More per-model config makes drift *worse*: more surface, staler faster.
And F3 shows our table would be **behind** Claude Code's, which already
routes v5 correctly — so a comprehensive default risks overriding correct
client behaviour with our stale copy.

The reframing: we want comprehensive **knowledge** per model, generated
on demand, not comprehensive **written config** per model.

---

## 5. Options

**Option 1 — capability probe (generated, not hardcoded).** A script that
walks `/v1/models` and, per model, probes both API paths and both
thinking shapes, emitting the matrix in §3.1. Answers drift structurally
rather than by hand-editing a list. Cost: one script plus the runtime of
a live probe sweep (the §3.1 sweep took a few minutes). Risk: burns
gateway quota; needs to be opt-in, never on the `connect` path.

**Option 2 — a floor, not a default, for Claude Code.** Intervene only
where the client is known-wrong: an older Claude Code sending `enabled`
to a v5 model. Would mean writing `env.ANTHROPIC_MODEL` or a thinking
override *conditional on client version*. Cost: version detection plus a
per-model table — i.e. the drift surface again, which argues for keeping
it as narrow as possible. Note this is a re-scoping of the "auto-default
fix queued for v2.3" that `docs/LIMITATIONS.md` still carries for
opus-4-7; that item as written is now obsolete.

**Option 3 — document the aider/OpenCode ceiling.** Users should know
thinking is unavailable there rather than assume misconfiguration and
hunt for a setting. Cost: a `LIMITATIONS.md` subsection. No code.

**Option 4 — upstream reports.** ~~Two: the missing `claudeopus5` /
`claudesonnet5` rows in the shim's `model_overrides` (F2), and the gpt-5
usage-parsing 502 (F6).~~ **Rejected 2026-08-25** — see
[§10](#10-why-the-upstream-reports-are-not-being-filed). The Argo API's
limitation backlog makes this a low-yield channel; the probe script
detects a fix if one lands, which is cheaper than tracking an issue.

## 6. Recommendation

Ordered:

1. **Option 3 now** (docs; zero risk, immediate user value) — folded into
   the same pass that corrects the stale opus-4-7 claims (UP-13, still
   open in `impl_upstream_hardening.md`).
2. **Option 1 next** (probe script; the structural answer to drift) —
   done, see §9.
3. **Option 4 rejected** — not filing upstream; see
   [§10](#10-why-the-upstream-reports-are-not-being-filed).
4. **Option 2 only if a user reports it.** Claude Code 2.1.241 is correct
   today; intervening pre-emptively risks overriding a client that
   already knows more than we do. Note §10 makes this the *only*
   remaining lever for a non-Claude-Code client on v5, since the shim
   will not be fixed on our account — so if such a report arrives, it
   escalates in priority rather than staying deferred.

Explicitly **not** recommended: writing per-model thinking defaults into
all three tool configs.

## 7. What would falsify this note

Stated plainly so the next session can re-test cheaply rather than trust:

- **F4 is the load-bearing claim** and rests on the gateway returning
  empty `reasoning_content` for every `reasoning.mode` value on every
  model tried. A newer `llm-rosetta` or an ANL-side change could make it
  work; the probe is a two-minute `curl`. If F4 falls, Option 3 becomes
  wrong and per-model config for aider/OpenCode becomes worth revisiting.
- **F3 is version-pinned** to Claude Code 2.1.241. A future release could
  regress the table, or a user on an older release hits the v5 gap today.
- **F2 is version-pinned** to `llm-rosetta` 0.7.1 installed / 0.9.0
  latest. A v5 override row upstream closes it.
- **F1 is a point-in-time gateway measurement.** ANL changes models
  without announcement.

## 8. Open questions

1. **Is the empty `reasoning_content` on `/v1/chat/completions` intended
   or a defect?** Determines whether F4 is a permanent ceiling or a
   fixable bug, and therefore whether Option 4 grows a third report. Not
   resolvable from black-box probing — needs upstream's answer.
2. **Does the shim rewrite, or pass through?** §3.2 infers rewriting from
   the haiku `adaptive` probe. Reading `llm-rosetta`'s dispatch would
   settle it, and matters for predicting what a v5 override row would
   actually do.
3. **Should the probe script (Option 1) live in the engine or as a dev
   script?** Engine means every user can run it and it can inform
   writers; dev-script means it never risks the `connect` path. Leaning
   dev-script under `scripts/`.
4. **Does `use_temperature: false` interact with thinking?** All probes
   here omitted `temperature`. A tool sending both is untested.
5. **What is the oldest Claude Code that still routes v5 correctly?**
   Sets the real exposure for Option 2. Requires installing old releases.

## 9. Action items

1. Correct the stale opus-4-7 claims in `README.md` + `docs/LIMITATIONS.md`
   and add the v5 + OpenAI-path findings — **done 2026-08-25**, this
   session (see §6 item 1; discharges the doc half of UP-13).
1a. Build the capability probe (Option 1) — **done 2026-08-25**:
   `scripts/probe_capabilities.py`. It immediately earned itself by
   falsifying F1's universal-`adaptive` claim (see the banner in §3.1).
2. ~~File the shim `model_overrides` gap upstream~~ — **not doing**
   (maintainer decision, 2026-08-25). See §10.
3. ~~File the gpt-5 usage-parsing 502 upstream~~ — **not doing**. See §10.
4. ~~Build the capability-probe script (Option 1)~~ — **done**; see 1a.
5. ~~Resolve Q1 with upstream~~ — **not doing**; treat the OpenAI-path
   ceiling as permanent for planning purposes. See §10.

## 10. Why the upstream reports are not being filed

**Maintainer decision, 2026-08-25**: the Argo API has a substantial
backlog of limitations, and there is no reason to expect these three to
be addressed on a timescale that would change our design. Filing them
would be effort spent on a channel that has not historically moved.

This is a deliberate position, not an oversight, and it has consequences
worth stating so a future session does not relitigate them:

- **The v5 shim gap is permanent from our side.** No `claudeopus5` /
  `claudesonnet5` row will appear in `reasoning.model_overrides` because
  we asked for it. Any client sending `thinking.type: enabled` to a v5
  model keeps getting a silent empty response. Claude Code routes around
  this itself; anything else does not.
- **The OpenAI-path ceiling is permanent.** Treat "thinking is
  unreachable for aider and OpenCode" as a fixed property of the stack
  when planning, not as a bug awaiting a fix. Q1 (whether the empty
  `reasoning_content` is intended) stays formally open but is not worth
  chasing — the answer would not change what we build.
- **The gpt-5 usage-parsing 502 stays a known rough edge.** Recorded in
  §3.6 so the next person to hit it recognises it rather than debugging
  our layer.

What replaces the reports: `scripts/probe_capabilities.py`. If upstream
does fix any of this, the probe will show it on the next run without
anyone having to track an issue. That is the right shape of dependency
on a stack we do not control — measure it, don't petition it.

---

*Created 2026-08-25 by Ahmed Attia (with AI assistance from Claude per
[`CONTRIBUTORS.md`](../CONTRIBUTORS.md)). All measurements taken live
against `compute-01.cels.anl.gov` on 2026-08-25 with argo-proxy 3.2.3 /
llm-rosetta 0.7.1, Claude Code 2.1.241, aider 0.86.2, OpenCode 1.18.23.*
