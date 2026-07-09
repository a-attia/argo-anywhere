# Upstream audit re-walk: `Oaklight/argo-proxy` v3.1.0 + v3.1.1 ↔ `argo-anywhere` v2.2.0

*Created 2026-06-17 by Ahmed Attia (with substantial AI assistance
from Claude per [`CONTRIBUTORS.md`](../CONTRIBUTORS.md)). Scope:
delta against [`AUDIT_2026-06-04_argo-proxy-upstream.md`](AUDIT_2026-06-04_argo-proxy-upstream.md)
for `argo-proxy` releases **v3.1.0** (PyPI 2026-06-11, commit
`3931a7a`) and **v3.1.1** (PyPI 2026-06-12, commit `db2a3b0`).
`argo-anywhere` baseline unchanged: v2.2.0 tag `737563d`. This is a
re-walk per the parent audit's self-instruction (§6 "Re-run after
every `argo-proxy` minor or patch release"); v2.2.0 still has
**zero broken consumption points**, but v3.1.0's `_legacy` removal
and v3.1.1's model-list churn justify two new MEDIUM-severity UP
findings and three watch-list updates.*

---

## Table of contents

- [Executive summary](#executive-summary)
- [1. What changed upstream between v3.0.4 and v3.1.1](#1-what-changed-upstream-between-v304-and-v311)
- [2. Re-walk of the 15-row watch-list](#2-re-walk-of-the-15-row-watch-list)
- [3. New findings (UP-07 .. UP-09)](#3-new-findings-up-07--up-09)
- [3-bis. UP-10 — Opus 4.8 reissues the opus-4-7 limitation (added 2026-06-17 evening)](#3-bis-up-10--opus-48-reissues-the-opus-4-7-limitation-added-2026-06-17-evening)
- [4. Disposition of prior findings (UP-01 .. UP-06) under v3.1.x](#4-disposition-of-prior-findings-up-01--up-06-under-v31x)
- [5. Recommended follow-ups + revised priority for v2.2.1](#5-recommended-follow-ups--revised-priority-for-v221)
- [6. Methodology + reproducibility](#6-methodology--reproducibility)

---

## Executive summary

**Runtime contract intact again.** Every `argo-proxy` interface that
`argo-anywhere` v2.2.0 consumes — `pip install argo-proxy`,
`argo-proxy --version`, `argo-proxy serve --help`, `argo-proxy serve`
under screen/tmux/nohup, the `/health` endpoint, the YAML config at
`~/.config/argoproxy/config.yaml` with `config_version`, `user`,
`host`, `port`, `verbose`, `argo_base_url` — **still exists with
identical semantics** in v3.1.1 (verified against the v3.1.1 tarball
at <https://codeload.github.com/Oaklight/argo-proxy/tar.gz/refs/tags/v3.1.1>).
Our PyYAML merge correctly preserves every key in the v3.1.1 config
sample.

**Three changes upstream warrant attention.** Two improve our
posture, one introduces a small migration risk:

- **Opus 4.7 limitation fixed at source** (v3.1.0; see UP-08). The
  upstream-stack limitation we documented in [`docs/LIMITATIONS.md`](LIMITATIONS.md)
  and [`notes/agent_feedback.md`](../notes/agent_feedback.md) entry
  6 — Claude Code 2.1.x + opus-4-7 + `argo-proxy ≤ 3.0.2` rejecting
  `thinking.type=enabled` — is now resolved properly at the
  shim-`model_overrides` layer (per-model `thinking_type` mapping
  via `argo--anthropic` llm-rosetta shim). v3.0.3 was a partial
  workaround in the conversion paths; v3.1.0 fixes the root cause
  declaratively. **The auto-default `env.ANTHROPIC_MODEL=claude-sonnet-4-6`
  fix queued for v2.3 in AGENTS.md is therefore no longer needed
  for opus-4-7**. **BUT** — see UP-10 below: Opus 4.8 (Anthropic
  GA 2026-06-09) is also adaptive-thinking-only AND is not in the
  v3.1.1 `_DEFAULT_CHAT_MODELS` registry, the llm-rosetta v0.6.9
  shim's `_ADAPTIVE_THINKING_MODELS` frozenset, OR the
  `_NO_TEMPERATURE_MODELS` set. The opus-4-7 limitation therefore
  **re-emerges verbatim for opus-4-8** until both upstream packages
  add the model. The v2.3 auto-default fix may need to be
  re-instated, scoped to `opus-4-8` rather than removed entirely.
- **Legacy ARGO gateway mode removed entirely** (v3.1.0). The
  `--legacy-argo` CLI flag, `USE_LEGACY_ARGO` env var, and
  `use_legacy_argo` config key are all deleted (~8,500 lines of
  `_legacy` module gone). We never wrote `use_legacy_argo`
  ourselves, but the v3.1.1 `config.sample.yaml` STILL DOCUMENTS
  it in a comment — a hand-edited user config from v2.x/v3.0.x era
  that contains `use_legacy_argo: true` will be **silently
  ignored** by v3.1.0+ rather than rejected, which is a subtle
  surprise. See UP-07.
- **Model registry churn + auto-refresh** (v3.1.1). The default
  model list was overhauled (added GPT-5 / Gemini 3.x / Claude
  4.5/4.6/4.7; removed GPT-3.5 / GPT-4 / o1-mini); the registry now
  auto-refreshes every 24 hours by default. This reduces but does
  not eliminate the relevance of our `update-models` subcommand.
  See UP-09.

**WATCH-04 (clean-install `httpx` failure) is likely resolved.**
v3.1.1's `pyproject.toml` lists `httpx` only as a `dev`-extra
dependency, no longer as a runtime dependency. Issue #117 has not
been closed but the regression vector appears gone.

**Stale upstream sample.yaml.** The v3.1.1 `config.sample.yaml`
comment block still lists `use_legacy_argo: true` as a configurable
field even though the v3.1.0 release notes (and the v3.1.1
`src/argoproxy/config/model.py` source) confirm the field has been
removed. This is an upstream doc-debt issue not actionable from our
side; recorded in §3 as part of UP-07's context.

**Schema additions in v3.1.1** (`config.sample.yaml` +
`config/model.py` confirm): `log_to_file: bool = False`,
`model_refresh_interval_hours: float = 24`, `dump_requests: bool`
(from 3.0.1, missed in the prior audit's catalog), `dump_dir: str`.
All four are correctly preserved by our PyYAML merge.

**Disposition shift for prior findings:** UP-01 partially closes
(the limitation IS fixed, doc still needs revising); UP-02 strengthens
(version floor should bump from `>=3.0.3` to `>=3.1.0` to pick up the
model-overrides fix); UP-03 needs reconsideration (upstream now only
persists `anthropic_stream_mode` when ≠ `force`, so writing it
explicitly would conflict with their "default = omit" convention);
UP-04 unchanged in priority but the stale-keys list grows. See §4.

---

## 1. What changed upstream between v3.0.4 and v3.1.1

### 1.1 Release timeline (new entries since the parent audit)

| Version | Upload date | Headline | Hits our surface? |
|:--------|:------------|:---------|:------------------|
| **v3.1.1** | 2026-06-12 | Periodic model-list auto-refresh (24h default; `model_refresh_interval_hours`); default fallback model `argo:gpt-4o → argo:gpt-5-nano`; default model list overhauled (added GPT-5 family + Gemini 3.x + Claude 4.5/4.6/4.7; removed GPT-3.5 / GPT-4 / o1-*). | **Yes**, indirectly — see UP-09 (interaction with our `update-models` subcommand). |
| **v3.1.0** | 2026-06-11 | **BREAKING**: removed `_legacy` module (~8500 lines), `--legacy-argo` flag, `USE_LEGACY_ARGO` env, `use_legacy_argo` config field; removed same-format passthrough (everything now goes through llm-rosetta converter+shim pipeline); removed CLI flags `--force-conversion`, `--enable-leaked-tool-fix`, `--real-stream`, `--pseudo-stream`, `--tool-prompting`. **Added**: llm-rosetta shim integration (`argo--anthropic` + `argo--openai_chat` shims); model-level `thinking_type` via `model_overrides` — Opus 4.7 correctly gets `adaptive`, other models keep `enabled` (**fixes the upstream-stack opus-4-7 limitation we documented at v2.2.0**); `unsigned_reasoning_blocks: preserve` policy; bumped llm-rosetta to `>=0.6.8`. | **Yes** — UP-07 (legacy-config silent-ignore on upgrade); UP-08 (opus-4-7 limitation now obsolete at source). |

### 1.2 Config schema delta (v3.0.4 → v3.1.1)

Verified against `argo-proxy-3.1.1/src/argoproxy/config/model.py`
(the `@dataclass ArgoConfig` definition + `from_dict` mapping +
`to_dict` serialiser at lines 19–270) and
`argo-proxy-3.1.1/config.sample.yaml`.

**Removed** (no longer valid keys; silently ignored by `from_dict`
since they're no longer in `cls.__annotations__`):

- `use_legacy_argo` — gone with the `_legacy` module.
- `force_conversion` — gone (everything is force-converted now).

**Added** since v3.0.4:

- `log_to_file: bool = False` — file logging alongside stdout. This
  was already promised in v3.0.0 release notes but is now an
  explicit dataclass field in v3.1.x. Privacy-relevant; see UP-05
  re-disposition in §4.
- `model_refresh_interval_hours: float = 24` (v3.1.1 only) —
  controls the new auto-refresh; `0` disables.
- `dump_requests: bool = False` + `dump_dir: str = ""` (introduced
  v3.0.1; missed in parent audit's `config.sample.yaml` table at
  §2.3). Off by default; user-preserved.

**Unchanged semantics + names**: `config_version`, `user`, `host`,
`port`, `verbose`, `max_log_history`, `argo_base_url`,
`connection_test_timeout`, `skip_url_validation`, `resolve_overrides`,
`enable_payload_control`, `max_payload_size`, `image_timeout`,
`concurrent_downloads`, `anthropic_stream_mode`,
`native_openai_base_url`, `native_anthropic_base_url`.

The five keys we own (`config_version`, `user`, `host`, `port`,
`verbose`) are all still present + accepted with identical
semantics.

### 1.3 Runtime-dependency delta

`pyproject.toml` at v3.1.1:

```toml
dependencies = [
    "aiohttp>=3.12.2",
    "llm-rosetta>=0.6.8,<0.7.0",
    "pydantic>=2.11.7",
    "tiktoken>=0.9.0",
    "tqdm>=4.67.1",
    "Pillow>=12.0.0",
]
```

Delta vs the v3.0.4 set documented in the parent audit's WATCH-11:

- **`httpx` removed from runtime deps** (moved to `dev`-extra only).
  This is the dependency that triggered the open issue #117 we
  flagged as WATCH-04. The regression vector is gone in v3.1.1.
- `llm-rosetta` floor bumped from `>=0.6.0,<0.7.0` to
  `>=0.6.8,<0.7.0` — minor-version bump within our compatible range.
- Other deps unchanged.
- Still all pure-pip-installable; no new system-level requirement.

### 1.4 CLI surface delta

`argo-proxy` top-level subcommands at v3.1.1 (unchanged from v3.0.4):
`serve`, `config`, `logs`, `update`, `models`. **Removed at v3.1.0**:
the `--legacy-argo` global flag.

Our consumption (`argo-proxy --version`, `argo-proxy serve --help`,
`argo-proxy serve`) is unaffected.

### 1.5 HTTP routes

`/health` confirmed at v3.1.1 (`src/argoproxy/app.py:210` +
`:335` + `:363`). Returns `{"status": "healthy"}` HTTP 200. No
change from v3.0.4.

`/v1` prefix unchanged.

### 1.6 Open upstream issues (delta since parent audit)

Issue #117 (`Can't find httpx ?`) appears resolved-in-practice by
the `httpx` runtime-dep removal at v3.1.1, but the issue thread has
not been closed. Recommend keeping WATCH-04 in the watch-list with
an updated verification step (see §2).

No new open issues touch our consumption surface as of 2026-06-17.

---

## 2. Re-walk of the 15-row watch-list

Each row is re-verified against v3.1.1. ✅ = still safe; ⚠ = needs
attention; ❌ = broken (none in this re-walk).

| # | Row | Status at v3.1.1 | Verification trace |
|:--|:----|:-----------------|:-------------------|
| WATCH-01 | `argo-proxy serve` works as bare command | ✅ | `serve --help` synopsis unchanged; config positional still optional (default search order). |
| WATCH-02 | `~/.config/argoproxy/config.yaml` in search order | ✅ | Unchanged; verified in `src/argoproxy/config/io.py`. |
| WATCH-03 | `/health` returns HTTP 200 | ✅ | `src/argoproxy/app.py:210`. |
| WATCH-04 | clean `pip install` works without manual intervention | ✅ (likely) | `httpx` removed from runtime deps at v3.1.1; issue #117 regression vector gone, but **issue not closed upstream** and we did not run the clean-venv probe ourselves this round. Suggest opportunistic verification on next live test. |
| WATCH-05 | `config_version: "3"` still accepted | ✅ | `from_dict` accepts `"3"`; tests in `tests/fixtures/configs/v3_already_migrated.yaml` confirm round-trip. |
| WATCH-06 | The five keys we own still accepted with same names + semantics | ✅ | `config_version`, `user`, `host`, `port`, `verbose` all in `ArgoConfig` dataclass at v3.1.1 with identical types + semantics. |
| WATCH-07 | `argo_base_url` "user-customizable; overrides upstream env" | ✅ | `_argo_base_url` field unchanged; still user-settable. |
| WATCH-08 | `anthropic_stream_mode` default stays `force` | ✅ | `_anthropic_stream_mode: str = "force"` (`config/model.py:59`). **Newly observed**: `to_dict` only serialises this key when `≠ "force"` (line 258–259), i.e. upstream treats `force` as "default; omit on write". This refines UP-03's recommendation — see §4. |
| WATCH-09 | bearer-token-is-ANL-username auth model | ✅ | README "AI Coding Tools Integration" table unchanged. |
| WATCH-10 | Python 3.10+ minimum | ✅ | `requires-python = ">=3.10"` in `pyproject.toml` v3.1.1. |
| WATCH-11 | No new system-level dependency | ✅ | All deps remain pure-pip; **`httpx` removed from runtime**. |
| WATCH-12 | `serve` startup user-validation not a hard fail | ✅ | v3.0.4 fix in place; v3.1.x retains the soft-warning behaviour. |
| WATCH-13 | `verbose: true` keeps logging prompts to stdout | ⚠ | Semantics unchanged but **new `log_to_file: bool` key** (v3.1.x explicit dataclass field) adds a separate log destination. Our `verbose: false` default still suppresses prompt logging at the source, but if a user enables `log_to_file: true` AND `verbose: true`, prompts now also land in a file regardless of stdout capture. Privacy posture in [`docs/SECURITY.md`](SECURITY.md) should add a one-liner. See UP-09 sub-point. |
| WATCH-14 | PyPI package still ships | ✅ | <https://pypi.org/pypi/argo-proxy/json> returns v3.1.1 as latest. |
| WATCH-15 | `screen`-friendly behaviour (no daemonisation, respects SIGTERM, stdout/stderr) | ✅ | Source unchanged in this area; no v3.1.x release-note mentions daemonisation or self-logging. |

**Net**: 13 of 15 rows ✅, 2 of 15 rows ⚠ (WATCH-04 needs an
opportunistic re-verification on a fresh node; WATCH-13 grows a
sub-bullet for `log_to_file`). Zero rows ❌.

---

## 3. New findings (UP-07 .. UP-09)

### UP-07 — silent-ignore of legacy `use_legacy_argo` / `force_conversion` config keys on upgrade (MEDIUM)

**Claim audited**: `argo_anywhere.sh`'s `write_argoproxy_config`
uses a `yaml.safe_load → mutate-our-keys → yaml.safe_dump` Python
heredoc that preserves **every** non-owned key verbatim. If a user
hand-edited their `~/.config/argoproxy/config.yaml` to add
`use_legacy_argo: true` or `force_conversion: true` under
`argo-proxy ≤ 3.0.x`, our writer preserves those keys across config
re-writes. Upstream v3.1.0 removed both fields; `from_dict` silently
ignores unrecognised keys (line 230–231:
`valid_fields = {k: v for k, v in config_dict.items() if k in
cls.__annotations__}`).

**Impact**: a user upgrading from `argo-proxy 3.0.x` to `3.1.0+`
while keeping their config file unchanged loses any custom legacy
or `force_conversion` behaviour **silently**. They will not see a
warning, log line, or error. The integration appears to keep
working (and for nearly all users it will), but if they were
depending on `force_conversion: true` to route everything through
the converter (now the only behaviour) or on `use_legacy_argo: true`
to hit the deprecated per-endpoint paths, the behaviour shift is
undocumented and uncommunicated.

The upstream `config.sample.yaml` at v3.1.1 still references
`use_legacy_argo: true` in a comment block (lines 41–43 of the
sample), which is doc-debt on the upstream side — but it makes the
silent-removal worse because a user reading the upstream sample
today would still think the key is valid.

**Why this is OUR concern**: we are the layer the user installs +
re-runs. The first `client` run after a `pip install --upgrade
argo-proxy` jump from 3.0.x to 3.1.x is where our `handle_config_file`
flow takes effect. We can detect the obsolete keys at that point
and warn.

**Recommendation**: add a one-shot post-parse check in
`write_argoproxy_config` (Case 2: existing-file merge) that warns
when `use_legacy_argo` or `force_conversion` is present in the
existing file:

```python
# (inside the existing PyYAML heredoc, after yaml.safe_load and
#  before our own setdefault calls)
_obsolete_v31_keys = {
    "use_legacy_argo": "removed in argo-proxy 3.1.0 (_legacy module deleted)",
    "force_conversion": "removed in argo-proxy 3.1.0 (everything is force-converted now)",
}
for _key, _reason in _obsolete_v31_keys.items():
    if _key in data:
        import sys
        print(
            f"WARN: existing argo-proxy config has '{_key}: {data[_key]}' "
            f"but this key was {_reason}. Removing.",
            file=sys.stderr,
        )
        del data[_key]
```

Removing the obsolete keys is safe (we control what we write) and
preserves the principle that the script's writers eventually
converge users on a clean config.

**Severity**: MEDIUM — the behaviour change is silent and
non-trivial, but only affects users who hand-edited their config.

### UP-08 — upstream-stack opus-4-7 limitation is RESOLVED at v3.1.0; documentation + auto-default fix need re-evaluation (MEDIUM)

**Claim audited**: [`docs/LIMITATIONS.md`](LIMITATIONS.md) "Upstream
stack" section documents the Claude Code 2.1.x + opus-4-7 +
`argo-proxy` failure as a current limitation; AGENTS.md "v2.3
roadmap" queues an auto-default fix (pre-populate
`env.ANTHROPIC_MODEL=claude-sonnet-4-6` in `write_claudecode_config`)
to work around it. [`notes/agent_feedback.md`](../notes/agent_feedback.md)
entry 6 (2026-05-18, "upstream-stack findings need a 'not our bug,
here's the workaround' framing") includes a detailed diagnosis and
queues both runtime + persistent workarounds.

**Upstream reality at v3.1.0+**: the v3.0.3 fix
(`_normalize_thinking_for_upstream` in all conversion paths) was a
workaround at the converter layer. **v3.1.0 fixes the root cause
declaratively** via llm-rosetta shim `model_overrides`: the
`argo--anthropic` shim now sets `thinking_type: adaptive` for
`opus-4-7` and `thinking_type: enabled` for all other models, so
Claude Code can send either `thinking.type=enabled` or
`thinking.type=adaptive` and the shim emits the correct form to
upstream. The v3.1.0 release notes explicitly state "Tested with
Claude Code (claude-haiku-4.5, claude-opus-4.7)" and "Fixes the old
bug where all models were incorrectly converted to adaptive."

**Impact on our docs/code**:

1. **[`docs/LIMITATIONS.md`](LIMITATIONS.md) "Upstream stack"**
   needs updating to mark the limitation as resolved at
   `argo-proxy >= 3.1.0`. The historical context can stay
   (auditable trail of what we hit during v2.2.0 release-test)
   but a clear "RESOLVED" callout is needed.
2. **AGENTS.md v2.3 roadmap entry** ("auto-default
   `env.ANTHROPIC_MODEL=claude-sonnet-4-6` to work around the
   upstream-stack opus-4-7 limitation surfaced during v2.2.0
   release-gate") should be **removed** from the v2.3 plan. The
   workaround is unnecessary when the version floor is `>=3.1.0`.
3. **[`notes/agent_feedback.md`](../notes/agent_feedback.md) entry
   6** ("Status: open") can move to "rolled-up upstream: fixed in
   `argo-proxy v3.1.0` via llm-rosetta `argo--anthropic` shim
   `model_overrides`" per the file's existing `Status:` transition
   convention.
4. **README.md "Heads up before you start"** section's opus-4-7
   callout (if any) needs the same RESOLVED-at-v3.1.0 update.

**Coupling with UP-02**: UP-08 only takes effect when the user is
on `argo-proxy >= 3.1.0`. Combining UP-02 (version-floor warning)
with UP-08 (docs revision) is the right pair: tell the user "you
need ≥ 3.1.0 to avoid this; we'll warn you if you don't."

**Severity**: MEDIUM — the doc is now wrong in a different
direction (claims a limitation that no longer exists), and we have
queued speculative work for v2.3 that is no longer needed. Net
v2.3 scope shrinks slightly.

### UP-09 — model-list churn + new `log_to_file` key (LOW)

Three sub-findings clustered as one entry (each individually below
the threshold for its own UP-NN):

**9a. Model-registry overhaul at v3.1.1.** Default model list now
includes GPT-5 family, Gemini 3.x, Claude 4.5/4.6/4.7; removes
GPT-3.5, GPT-4, o1-mini, o1-preview. Our `update-models` /
`list-models` subcommands read the live `/v1/models` endpoint, so
they automatically pick up the new list — no code change needed.
**Documentation update**: if any of our docs reference specific
GPT-4 or o1-* model names as defaults, those references are now
stale. (Spot-check needed; not exhaustive at this round.)

**9b. Periodic model-list auto-refresh at v3.1.1.** Default
24-hour refresh interval. Our `update-models` subcommand becomes
somewhat redundant for users on v3.1.1+ — the server now refreshes
itself. Worth a one-line note in `README.md`'s `update-models`
mention saying "for `argo-proxy >= 3.1.1`, this happens automatically
every 24h; the subcommand forces an immediate refresh."

**9c. New `log_to_file` config key.** v3.1.x adds
`log_to_file: bool = False` as an explicit dataclass field
(file-based logging alongside stdout; was already promised in
v3.0.0 release notes but is now formalised). This is privacy-
relevant because our P2 fix (default `verbose: false`) was scoped
to prompts in `~/.argo_anywhere.server.log` via stdout capture.
If a user explicitly sets `log_to_file: true` (we never write it;
PyYAML merge preserves their choice), prompts would land in
argo-proxy's separate log file regardless of our stdout capture.
**Recommendation**: add a sentence to [`docs/SECURITY.md`](SECURITY.md)
"Privacy: argo-proxy verbose log" section noting that
`log_to_file: true` is a separate user-controlled destination
we do not manage.

**Severity**: LOW — additive features that don't break anything;
all three sub-bullets are doc updates.

---

## 3-bis. UP-10 — Opus 4.8 reissues the opus-4-7 limitation (added 2026-06-17 evening)

*Added later the same day as the rest of this re-walk, prompted by
the user-question "Is opus 4.8 available now?". The investigation
is self-contained and folds back into UP-08's framing.*

### Background

Anthropic shipped **Claude Opus 4.8 (`claude-opus-4-8`)** to general
availability on **2026-06-09** — three days before `argo-proxy v3.1.1`
was released (2026-06-12). The model is the new Opus-tier flagship;
4.7 has moved to "Legacy models" status on Anthropic's docs. Key
spec: adaptive-thinking-only (`Extended thinking: No`,
`Adaptive thinking: Yes`), `effort` parameter defaults to `high`,
context 1M, max output 128k — i.e. **the same thinking-config and
sampling-config constraints as Opus 4.7**.

### Claim audited

UP-08 declared the opus-4-7 limitation RESOLVED at `argo-proxy >= 3.1.0`
via the llm-rosetta `argo--anthropic` shim's `model_overrides`
(per-model `thinking_type: adaptive` for `claudeopus47`). UP-08's
recommendation was to remove the v2.3 auto-default fix
(`env.ANTHROPIC_MODEL=claude-sonnet-4-6`) from AGENTS.md.

This addendum checks **whether the same fix applies for Opus 4.8.**

### Three independent gaps found

Verified against `argo-proxy v3.1.1` (PyPI 2026-06-12, tarball at
`/tmp/argo-proxy-3.1.1`) and `llm-rosetta v0.6.9` (PyPI / GitHub
release 2026-06-13, tarball at `/tmp/llm-rosetta-0.6.9`):

| Gap | Source location | Evidence | Effect on opus-4-8 |
|:----|:----------------|:---------|:-------------------|
| **G1** — model registry | `argo-proxy/src/argoproxy/models.py:60-64` `_DEFAULT_CHAT_MODELS` | Hardcoded fallback maps stop at `claudeopus47`. No `claudeopus48` / `claude-opus-4.8` entry. | If ANL's `/v1/models` exposes opus-4-8, the 24h auto-refresh (v3.1.1 feature) picks it up; otherwise `resolve_model_name` falls through to the registry default `argo:gpt-5-nano` (`models.py:783`) with a WARN log Claude Code never surfaces to the user. |
| **G2** — adaptive-thinking override | `llm-rosetta/src/llm_rosetta/shims/providers/argo/anthropic/provider.yaml:18-20` `model_overrides` | Only one entry: `claudeopus47: thinking_type: adaptive`. Documented in `transforms.py:41-48` `_ADAPTIVE_THINKING_MODELS = frozenset({"claudeopus47"})` (legacy explicit transform; "retired — handled by shim reasoning config" per line 197). | If a request to opus-4-8 carries `thinking.type=enabled` (Claude Code 2.1.x default), `_inject_shim_reasoning` (argo-proxy `dispatch.py:118-129`) falls back to the provider-level `thinking_type: enabled` from `provider.yaml:9`. Upstream Vertex rejects with HTTP 400; argo-proxy correctly surfaces as SSE `event: error`; Claude Code mis-parses as "API returned empty/malformed response (HTTP 200)" — **verbatim reproduction of the Phase 4 v2.2.0 release-gate bug**. |
| **G3** — temperature stripping | `argo-proxy/src/argoproxy/endpoints/dispatch.py:386` `_NO_TEMPERATURE_MODELS = {"claudeopus47"}` | Hardcoded set of one. The llm-rosetta issue #220 (Comprehensive per-model probe, opened 2026-05-23, still open) confirms "Claude Opus 4.7: rejects all sampling params"; same expected for Opus 4.8 (also a reasoning model with adaptive-only thinking). | If a tool sends `temperature` for opus-4-8 (Claude Code typically doesn't, but Cursor / aider / custom integrations might), argo-proxy doesn't strip it → upstream 400 → same SSE-mis-parse path as G2. |

The model-name normalisation in `_strip_temperature_for_reasoning_models`
(`dispatch.py:384`: `normalised = re.sub(r"[^a-z0-9]", "",
resolved_model.lower())`) means the lookup keys are e.g.
`claudeopus47` (without dashes). For opus-4-8 to be covered, both
sets would need to add `claudeopus48`.

### What this means for users

| Scenario | Outcome at `argo-proxy v3.1.1` |
|:---------|:-------------------------------|
| User runs `claude --model claude-opus-4-7` | **Works** (UP-08 fix in place). |
| User runs `claude --model claude-sonnet-4-6` | **Works** (no thinking-type issue). |
| User runs `claude --model claude-opus-4-8` AND ANL has refreshed registry | **Likely fails** (G2: `enabled` thinking-type rejection) unless Claude Code sends `thinking.type=adaptive` for opus-4-8, OR `thinking` field is absent. |
| User runs `claude --model claude-opus-4-8` AND ANL has NOT refreshed registry | **Fails silently** (G1: falls back to `gpt-5-nano`; user sees a model labelled "opus-4-8" but reasoning quality of `gpt-5-nano`). |
| User sets `env.ANTHROPIC_MODEL=claude-opus-4-8` in `~/.claude/settings.json` | Same as above — Claude Code reads this on startup; same failure mode. |

The third row (G2 failure) is the verbatim Phase 4 release-gate
bug we already debugged once. Two-thirds of the diagnostic work is
already in [`notes/agent_feedback.md`](../notes/agent_feedback.md)
entry 6's "Evidence / minimal repro" block, just with `opus-4-7`
substituted for `opus-4-8`.

### Verification commands (for the user to run on a working client)

These probes do NOT require code changes. Run them with a healthy
`argo-anywhere` tunnel up (`bash argo_anywhere.sh status` reports
ALL GREEN).

**1. Does ANL's gateway expose opus-4-8 at all?**

```sh
# Returns the live model registry as JSON.
curl -fsS "http://localhost:${ARGO_ANYWHERE_PORT:-44497}/v1/models" \
  -H "Authorization: Bearer ${ARGO_ANYWHERE_USER}" \
  | python3 -c 'import json, sys; d = json.load(sys.stdin); print("\n".join(sorted(m["id"] for m in d.get("data", []) if "opus" in m["id"])))'
```

Expected output today (2026-06-17): a list of opus model IDs. If
`claudeopus48` / `claude-opus-4.8` / `opus-4-8` appears, ANL has
refreshed; G1 is dormant. If it does NOT appear, G1 is live and
opus-4-8 silently falls back to `gpt-5-nano`.

**2. Direct probe: does opus-4-8 work with `thinking.type=enabled`?**

```sh
# Sends the same payload shape Claude Code 2.1.x sends.
curl -sS -H "Authorization: Bearer ${ARGO_ANYWHERE_USER}" \
     -H "Content-Type: application/json" \
     -H "anthropic-version: 2023-06-01" \
     -X POST "http://localhost:${ARGO_ANYWHERE_PORT:-44497}/v1/messages" \
     -d '{"model":"claude-opus-4-8","max_tokens":2048,"stream":true,
          "thinking":{"type":"enabled","budget_tokens":1024},
          "messages":[{"role":"user","content":"hi"}]}'
```

Possible outcomes:

- `event: message_start ...` (200 OK SSE) → G2 dormant; opus-4-8
  works with `enabled` thinking. (Unlikely unless ANL did
  something special; the shim's per-model table only covers 4.7.)
- `event: error\ndata: {"type": "error", "error": {...}}` →
  **G2 confirmed**; same failure mode as the Phase 4 release-gate
  bug. The auto-default fix should be re-instated, scoped to
  opus-4-8.
- HTTP 4xx with a "model not found" body → **G1 confirmed**; ANL
  doesn't serve opus-4-8 yet.

**3. Cross-check with `thinking.type=adaptive`:**

```sh
# Repeat (2) but with adaptive thinking-type.
curl -sS -H "Authorization: Bearer ${ARGO_ANYWHERE_USER}" \
     -H "Content-Type: application/json" \
     -H "anthropic-version: 2023-06-01" \
     -X POST "http://localhost:${ARGO_ANYWHERE_PORT:-44497}/v1/messages" \
     -d '{"model":"claude-opus-4-8","max_tokens":2048,"stream":true,
          "thinking":{"type":"adaptive"},
          "messages":[{"role":"user","content":"hi"}]}'
```

A 200 here while (2) errored is the canonical signature of the
G2 limitation.

### Disposition

UP-10 is **a re-emergence of UP-01/UP-08 scoped to opus-4-8**. The
work-arounds documented in
[`docs/LIMITATIONS.md`](LIMITATIONS.md) "Upstream stack" still
apply verbatim, just with `claude-opus-4-7` substituted by
`claude-opus-4-8`. Until upstream packages add opus-4-8, the
LIMITATIONS doc should:

- **Keep** the opus-4-7 historical entry (now marked RESOLVED at
  `argo-proxy >= 3.1.0` per UP-08).
- **Add** a new opus-4-8 entry pointing at the same workaround
  (`claude --model claude-sonnet-4-6` or
  `env.ANTHROPIC_MODEL=claude-sonnet-4-6`).
- **Note the dependency-chain fix**: opus-4-8 will work once
  `llm-rosetta` adds `claudeopus48` to the shim `model_overrides`
  AND `argo-proxy` adds it to `_NO_TEMPERATURE_MODELS` AND
  `_DEFAULT_CHAT_MODELS` (or ANL gateway refreshes argo-proxy's
  registry from `/v1/models`).

AGENTS.md v2.3 roadmap should **re-instate** the auto-default fix
(or scope it to "auto-default to a working model when the requested
opus-X model is not in the shim's `model_overrides` table") rather
than removing it entirely as UP-08 originally recommended. The
mechanism for detecting "is this model in the shim's overrides?" is
non-trivial from our layer (we'd have to crack open the shim YAML),
so the pragmatic approach is:

- **Short term (v2.2.1)**: document opus-4-8 limitation in
  [`docs/LIMITATIONS.md`](LIMITATIONS.md) using the same shape as
  the opus-4-7 entry; cite this UP-10. **Do not** auto-pin
  `env.ANTHROPIC_MODEL`.
- **Medium term (v2.3)**: re-instate auto-default
  `env.ANTHROPIC_MODEL=claude-sonnet-4-6` IF a user tries to use
  Claude Code without explicitly choosing a model AND we know the
  Anthropic-default-flagship is currently a shim-uncovered Opus
  generation. Detection rule: if the installed `llm-rosetta`'s
  `argo--anthropic/provider.yaml` lacks `model_overrides` for any
  of the most-recent two Anthropic Opus releases (per Anthropic's
  GA doc), pre-populate the env var.

The medium-term proposal couples our v2.3 release to the agent's
ability to introspect llm-rosetta's bundled shim YAML. That is
feasible (the file is a known path inside the venv:
`${VENV_PATH}/lib/python*/site-packages/llm_rosetta/shims/providers/argo/anthropic/provider.yaml`)
but adds a small runtime dependency on llm-rosetta's package
layout. Document as a v2.3 design decision before implementing.

### Filing upstream

The cleanest fix is at the source. **Filing recommendation**:

- **`llm-rosetta` issue**: "Add `claudeopus48` to
  `argo--anthropic/provider.yaml` `model_overrides`". Reference
  issue #220 (the comprehensive per-model probe that's already
  open) as the structural fix; this would be the tactical one-line
  fix while #220 is being implemented.
- **`argo-proxy` issue**: "Bump `_DEFAULT_CHAT_MODELS` and
  `_NO_TEMPERATURE_MODELS` to include `claudeopus48`". Both sets
  in `src/argoproxy/{models.py:60-64, endpoints/dispatch.py:386}`.

If those fixes land before v2.2.1 ships, UP-10 collapses to a
doc-only note (alongside the UP-08 doc revision). If they don't,
UP-10 is the new highest-priority MEDIUM finding in the v2.2.1
release because users WILL try opus-4-8 (it's Anthropic's
recommended default in their model-overview doc) and will hit the
exact bug the Phase 4 release-gate hit.

**Severity**: MEDIUM — verbatim reproduction of a previously
documented release-gate bug, plus a silent fallback to `gpt-5-nano`
if the gateway-side registry hasn't refreshed. Upgrade to HIGH if
ANL has refreshed `/v1/models` to include opus-4-8 AND the live
probe (verification step 2 above) returns the SSE-error shape,
because then the bug is reachable by any current Claude Code user
who tries the Anthropic-recommended default model.

---

## 4. Disposition of prior findings (UP-01 .. UP-06) under v3.1.x

| # | v2.2.0-era severity | Disposition at v3.1.x | New action |
|:--|:--------------------|:----------------------|:-----------|
| UP-01 (LIMITATIONS.md opus-4-7 stale) | MEDIUM | **Re-scope**: limitation IS now fully fixed (UP-08), doc still needs revising with the stronger framing "fixed via shim `model_overrides` at v3.1.0" rather than "fixed via conversion-path normalisation at v3.0.3". | Roll into UP-08 with the v3.1.0 framing. |
| UP-02 (version-floor `>=3.0.3`) | MEDIUM | **Strengthen**: bump recommended floor to `>=3.1.0`. The v3.1.0 shim-`model_overrides` fix is more robust than v3.0.3's path-by-path normalisation. | Land in v2.2.1; bump `_required_min="3.1.0"` in the suggested code snippet. |
| UP-03 (`anthropic_stream_mode: force` explicit) | LOW | **Reconsider — possibly skip**. Upstream's `to_dict` at v3.1.x only persists `anthropic_stream_mode` when ≠ `force` (the default). Writing it explicitly to our fresh-install config would contradict the upstream "omit when default" convention and would show up as a noisy diff against `argo-proxy config init` output. Probably **drop this finding** and rely on watching WATCH-08 instead. | Re-evaluate before v2.2.1 lands; lean toward dropping. |
| UP-04 (refresh user-preserved-keys comment) | LOW | **Same priority + more material**. The comment is now more stale than at v2.2.0 (missing `dump_requests`, `dump_dir`, `log_to_file`, `model_refresh_interval_hours` from v3.0.1/v3.1.x; plus `use_legacy_argo` / `force_conversion` are now actually deprecated, not just user-preserved). | Land in v2.2.1; replace enumerated list with link to upstream `config.sample.yaml` + a one-liner "we own 5 keys; everything else is preserved." |
| UP-05 (verbose privacy still valid) | LOW (verification) | **Re-confirmed with caveat**: `verbose: false` default still correct; **but new `log_to_file: bool` is a separate destination**. Subsumed by UP-09c. | Add the one-liner to SECURITY.md per UP-09c. |
| UP-06 (`claudeopus47` alias mention) | LOW | **Still applicable**; v3.1.1's auto-refreshed model list will surface both `claude-opus-4-7` (canonical) and `claudeopus47` (alias). | Mention both names when next editing limitation docs (low priority). |

**Net at v2.2.1 release**: UP-02 + UP-04 + UP-07 + UP-08 + UP-09
land; UP-01 folds into UP-08; UP-03 is dropped; UP-05/UP-06 fold
into UP-08/UP-09's doc revisions.

---

## 5. Recommended follow-ups + revised priority for v2.2.1

Updated priority order (replaces parent audit §5 for the v2.2.1
release; reflects UP-10 added later 2026-06-17):

1. **UP-08 + UP-10 paired revision** (MEDIUM × 2) — revise
   [`docs/LIMITATIONS.md`](LIMITATIONS.md) "Upstream stack" section
   to mark opus-4-7 limitation RESOLVED at `argo-proxy >= 3.1.0`
   (UP-08) AND add a fresh opus-4-8 entry pointing at the same
   workaround (UP-10) until `llm-rosetta` + `argo-proxy` add
   opus-4-8 to their per-model tables; update README.md "Heads up
   before you start" callout to cover both 4.7-historical +
   4.8-current; mark
   [`notes/agent_feedback.md`](../notes/agent_feedback.md) entry 6
   as `rolled-up upstream for opus-4-7: fixed in argo-proxy v3.1.0;
   re-emerged for opus-4-8 — see UP-10`; **DO NOT remove** the v2.3
   auto-default-fix roadmap entry from AGENTS.md (revising UP-08's
   earlier recommendation): re-scope it to "auto-default
   `env.ANTHROPIC_MODEL` when Anthropic's current flagship Opus is
   not in the shim `model_overrides` table" — see UP-10
   "Disposition" for the detection-rule design.
2. **UP-02** (MEDIUM) — add soft version-floor check to
   `ensure_argoproxy_installed` at `argo_anywhere.sh:5165–5180`;
   bump `_required_min` to `"3.1.0"`.
3. **UP-07** (MEDIUM) — add legacy-key warn-and-strip in
   `write_argoproxy_config`'s PyYAML heredoc (Case 2). Covers
   `use_legacy_argo` + `force_conversion`.
4. **UP-04** (LOW) — replace stale enumerated comment at
   [`argo_anywhere.sh:4786–4791`](../argo_anywhere.sh#L4786) with a
   link + one-liner.
5. **UP-09a/b/c** (LOW) — small doc updates: spot-check model-name
   references in our docs (9a); README note on auto-refresh (9b);
   SECURITY.md note on `log_to_file` (9c).
6. **UP-06** (LOW) — `claudeopus47` alias mention; merges naturally
   into the UP-08 LIMITATIONS.md edit.

**Dropped**: UP-03 (writing `anthropic_stream_mode: force`
explicitly would contradict upstream's "omit default" convention).

The v2.2.1 release scope therefore grows by one MEDIUM finding
(UP-07) and one MEDIUM-disposition-change (UP-08 supersedes UP-01)
but loses one LOW finding (UP-03). Net: a slightly larger v2.2.1
release with a clearer narrative ("track upstream v3.1.0 + close
the opus-4-7 limitation in our docs").

---

## 6. Methodology + reproducibility

**Sources consulted** (all 2026-06-17):

- GitHub Releases page <https://github.com/Oaklight/argo-proxy/releases>
  — v3.1.0 + v3.1.1 release notes.
- PyPI JSON <https://pypi.org/pypi/argo-proxy/json> — version list,
  upload dates, `requires_python`.
- v3.1.1 source tarball
  <https://codeload.github.com/Oaklight/argo-proxy/tar.gz/refs/tags/v3.1.1>
  — `src/argoproxy/config/model.py` (dataclass definition, `from_dict`
  mapping, `to_dict` serialisation), `src/argoproxy/app.py`
  (`/health` route handler), `pyproject.toml` (runtime deps),
  `config.sample.yaml` (documented schema).
- Our script: [`argo_anywhere.sh`](../argo_anywhere.sh) at v2.2.0
  tag `737563d` (no change since the parent audit).
- Parent audit: [`AUDIT_2026-06-04_argo-proxy-upstream.md`](AUDIT_2026-06-04_argo-proxy-upstream.md)
  (the v3.0.4 baseline this re-walk diffs against).
- [`docs/LIMITATIONS.md`](LIMITATIONS.md) "Upstream stack" section
  (the doc that needs revising per UP-08).
- [`notes/agent_feedback.md`](../notes/agent_feedback.md) entry 6
  (the rolled-up-upstream candidate per UP-08).
- AGENTS.md "v2.3 (queued)" milestone (the auto-default-fix that
  becomes obsolete per UP-08).

**Sources consulted for the UP-10 addendum** (later 2026-06-17):

- Anthropic models overview <https://docs.anthropic.com/en/docs/about-claude/models/overview>
  — confirmed Opus 4.8 GA 2026-06-09; adaptive-thinking-only;
  Opus 4.7 moved to legacy.
- llm-rosetta v0.6.9 tarball
  <https://codeload.github.com/Oaklight/llm-rosetta/tar.gz/refs/tags/v0.6.9>
  — `src/llm_rosetta/shims/providers/argo/anthropic/provider.yaml`
  + `transforms.py`. Confirmed `model_overrides` and
  `_ADAPTIVE_THINKING_MODELS` both contain only `claudeopus47`.
- argo-proxy v3.1.1 tarball, `src/argoproxy/models.py:60-64`
  (`_DEFAULT_CHAT_MODELS`) + `endpoints/dispatch.py:386`
  (`_NO_TEMPERATURE_MODELS`) — confirmed both stop at
  `claudeopus47`.
- llm-rosetta issue #220 <https://github.com/Oaklight/llm-rosetta/issues/220>
  — open since 2026-05-23; comprehensive per-model probe planned
  but does not yet include Opus 4.8 (which post-dates its
  filing).
- argo-proxy issue search <https://github.com/Oaklight/argo-proxy/issues?q=is%3Aissue+opus-4-8>
  + llm-rosetta issue search — no open issues mentioning opus-4-8
  as of 2026-06-17.

**Not consulted** (deliberate scope limit):

- Live opus-4-8 test against ANL — deferred to the user (probe
  commands listed in UP-10 §"Verification commands"). I cannot
  execute curl against the user's compute node from this
  environment. Once the user runs the three probes and reports
  back, UP-10's severity firms up to either MEDIUM (G2 not yet
  reachable because ANL hasn't refreshed) or HIGH (G2 reachable,
  bug live).
- Claude Code 2.1.x source — out of scope; tracked separately in
  per-tool integration docs.
- Live opus-4-7 + Claude Code + argo-proxy v3.1.0 test on real
  compute node — deferred. The v2.2.1 release-gate test plan
  should include "run opus-4-7 through Claude Code with the
  argo-proxy floor bumped to 3.1.0 and confirm no
  `thinking.type=enabled` error" as a regression-prevention test
  (i.e. UP-08 closure verification). **Plus**: re-run the same
  probe against `claude --model claude-opus-4-8` to verify UP-10's
  disposition.

**Reproduction**: an agent should be able to regenerate this
re-walk in ~30 minutes by:

1. `curl https://pypi.org/pypi/argo-proxy/json | jq` to confirm
   the latest version.
2. WebFetch the GitHub Releases page for the release notes diff.
3. `curl -fsSL https://codeload.github.com/Oaklight/argo-proxy/tar.gz/refs/tags/vX.Y.Z | tar xz`
   into `/tmp` and grep the config + app source for the watch-list
   verification points.
4. Walk the 15 watch-list rows from the parent audit, marking
   each ✅ / ⚠ / ❌.
5. Diff our findings against parent audit §3; write
   UP-NN entries for any new break/improvement.

---

*Re-walk closed 2026-06-17 (initial pass against v3.1.0 + v3.1.1);
re-opened and closed again later the same day to append UP-10 after
the user asked about Opus 4.8. Next re-walk trigger: either the
next `argo-proxy` release after v3.1.1, OR the next `llm-rosetta`
release after v0.6.9 (since UP-10 depends on the bundled shim),
OR ANL gateway adding `claudeopus48` to `/v1/models`. Whichever
fires first. Successor file name:
`AUDIT_<date>_argo-proxy-upstream.md`; cross-link to this file and
the v3.0.4 baseline.*
