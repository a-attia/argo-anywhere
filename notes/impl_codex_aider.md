# Implementation plan -- codex + aider CLI-tool support

**Status**: aider (Phase 5a) **LIVE-TEST PASSED 2026-07-09**
(`notes/test_plan_lifecycle.md` Test 1: default gpt-4o + opus-4.8 both
answer through the tunnel). codex (Phase 5b) still designing (gated on
the `/v1/responses` probe + a TOML-writer decision).
**Owner**: Ahmed Attia (with AI assistance per `CONTRIBUTORS.md`).
**Last updated**: 2026-07-08.
**Target repo**: <https://github.com/a-attia/argo-anywhere> (single-file
`argo_anywhere.sh`).
**Linked PLAN.md sections**: Section 2 (public API surface -- `--cli-tool`
values), Section 4 (Phase 5 "aider integration"; codex is NOT yet a
roadmap item and should be added), Section 7 (design-decisions log -- a
new D-NNN will codify the codex Responses-API decision).

## Purpose

Add two new AI coding CLI tools -- **OpenAI Codex CLI** (`codex`) and
**aider** (`aider`) -- as first-class `--cli-tool` targets, each
implemented against the existing five-function per-tool API contract, so
ANL users can drive them through the same SSH-tunnel + argo-proxy
transport that already serves OpenCode and Claude Code.

## Background: the per-tool API contract (what every new tool must supply)

Both tools slot into the established contract (see `AGENTS.md`
"Multi-CLI-tool architecture" and PLAN.md Section 3). For a tool named
`<name>`, that means:

1. `setup_<name>_cli_tool()` -- dispatcher entry point; idempotent; calls
   `<name>_pick_scope` (if multi-scope), then `ensure_<name>_installed`,
   then `handle_config_file <path> <desc> write_<name>_config`.
2. `ensure_<name>_installed()` -- install-or-detect the binary; prepend
   the install location to `PATH` for the rest of the run.
3. `write_<name>_config(dest)` -- one-arg writer; everything else via
   globals (`PROXY_PORT`, `ARGO_ANYWHERE_USER`); Python heredoc for
   non-trivial merges.
4. `<name>_scope_values()` -- D-018 scope vocabulary (space-separated).
5. A `<name>|<label>` row in `CLI_TOOLS_AVAILABLE`
   (`argo_anywhere.sh:4474`).
6. A `<name>)` arm in `do_post_tunnel_for_cli_tool`
   (`argo_anywhere.sh:4556`).

Optional: `<name>_pick_scope()` (multi-scope tools) and
`update_<name>_cli_tool()` (D-022 in-place upgrade).

The **reference implementations** to copy from:

- OpenAI-compatible-via-JSON tool -> `write_opencode_config`
  (`argo_anywhere.sh:2262`): writes a provider block with `baseURL`,
  `apiKey`, and a `Bearer <user>` header. **aider is the close cousin.**
- Env-var-driven / OAuth-aware tool -> `setup_claudecode_cli_tool` +
  `write_claudecode_config` (`argo_anywhere.sh:2846`, `:2940`) + the
  `claudecode_pick_scope` conflict-detection reference. **codex's
  provider + auth story is the closer cousin (custom provider block,
  bearer token, project-vs-user scope).**

## Public API surface (new)

New `CLI_TOOLS_AVAILABLE` rows (append after the existing two):

```text
"codex|OpenAI Codex CLI (uses ~/.codex/config.toml custom provider)"
"aider|aider (OpenAI-compatible; ~/.aider.conf.yml + OPENAI_API_BASE)"
```

New `--cli-tool` accepted values: `codex`, `aider`. No new flags
required; both consume the existing `--scope` framework and the shared
`--user` / `--node` / `--port` transport flags.

## Dependencies (upstream, verified 2026-07-08)

| Tool | Config file(s) | Wire protocol needed | argo-proxy surface | Verified against |
|:-----|:---------------|:---------------------|:-------------------|:-----------------|
| codex | `~/.codex/config.toml` (user; `$CODEX_HOME` overridable); `.codex/config.toml` (project, trust-gated) | **OpenAI Responses API** (`wire_api = "responses"` is the ONLY supported value) | **`/v1/responses`** (present `app.py:351` at argo-proxy v3.1.2; Responses handling matured in v3.2.x) | developers.openai.com/codex/config-reference; argo-proxy v3.1.2 source |
| aider | `~/.aider.conf.yml` (YAML) OR `.env` (home / git-root / cwd search order); `.aider.model.settings.yml` for unknown-model metadata | **OpenAI Chat Completions** (via `OPENAI_API_BASE` + `--model openai/<name>`) | `/v1/chat/completions` (long-stable; `app.py:350`) | aider.chat/docs/config; argo-proxy v3.1.2 source |

**The critical asymmetry:** aider rides the already-proven
OpenAI-Chat-compatible path (same surface OpenCode uses today). Codex
requires the **Responses API** (`/v1/responses`), which argo-proxy only
began serving recently and is still hardening (the v3.2.0a0 pre-release's
E2E matrix explicitly adds "codex CLI" + OpenAI Responses input). This
makes **aider the low-risk first tool** and **codex the one gated on an
argo-proxy Responses-API maturity check**.

## Design

### aider (low-risk; OpenAI-Chat path)

aider reads OpenAI-compatible settings from `~/.aider.conf.yml` and/or a
`.env`. The cleanest single-source approach is the YAML config file plus
setting the OpenAI base URL and key. The relevant keys:

- `openai-api-base: http://localhost:<PORT>/v1`
- `openai-api-key: <ANL_USERNAME>` (argo-proxy uses the username as the
  bearer token, exactly as OpenCode/Claude Code do)
- `model: openai/<model-id>` (e.g. `openai/gpt54`, `openai/claudeopus48`)

`write_aider_config(dest)` mirrors `write_opencode_config`: assert
`PROXY_PORT` and `ARGO_ANYWHERE_USER` are set (the L6 fail-loud
discipline), then emit YAML. Because aider's config search order is
home -> git-root -> cwd (last wins), scope handling maps to:

- `<name>_scope_values()` -> `global project` (global = `~/.aider.conf.yml`;
  project = `<git-root>/.aider.conf.yml` else `<cwd>/.aider.conf.yml`) --
  identical shape to `opencode_scope_values` / `opencode_pick_scope`.

`ensure_aider_installed()`: aider ships as a Python package; the upstream
recommended install is the standalone installer (`aider-install`) or
`python -m pip install aider-install && aider-install`, or `pipx install
aider-chat` / `uv tool install aider-chat`. Detect `command -v aider`
first; on macOS prefer `brew`? (aider is not in a first-party tap, so
prefer the upstream installer). Prepend the install location to `PATH`
for the run, matching the `ensure_opencode_installed` pattern.

**Privacy note:** aider writes `openai-api-key: <ANL_USERNAME>` in clear
text (same H7 class as Claude Code). Reuse the existing H7 privacy
warning in the `aider)` dispatcher arm.

### codex (higher-risk; Responses-API path)

codex reads `~/.codex/config.toml` (TOML). A custom provider is declared
under `[model_providers.<id>]`. The relevant keys (verified against the
config reference):

```toml
model = "gpt-5.5"                 # or an argo model id
model_provider = "argo"

[model_providers.argo]
name = "Argo Gateway (via argo-anywhere)"
base_url = "http://localhost:<PORT>/v1"
wire_api = "responses"           # ONLY supported value
env_key = "ARGO_ANYWHERE_TOKEN"  # env var supplying the bearer token
```

Auth options (choose one; do NOT combine):

- `env_key = "..."` -> codex reads the bearer token from an env var. This
  keeps the ANL username OUT of the config file (privacy win vs the
  aider/claudecode clear-text approach) but requires the user's shell to
  export it. `argo-anywhere` can print the exact `export` line in the
  dispatcher tail message.
- `experimental_bearer_token = "<user>"` -> writes the token into the
  TOML directly (discouraged upstream; same H7 clear-text exposure).
- command-backed `auth.command` -> codex runs a command that prints the
  token (analogous to Claude Code's `apiKeyHelper`; ties into the queued
  SH-01 random-token work). Best long-term option; more moving parts.

**Scope constraint (important):** codex project-scoped `.codex/config.toml`
**cannot override provider keys** (`model_provider`, `model_providers`,
`base_url` are user-level-only and ignored in project configs). So codex
scope handling is effectively **user-level-only for the provider block**:

- `codex_scope_values()` -> `global` only (single-value vocabulary; still
  declared so `--cli-tool codex --scope projct` is caught per D-018).
- No `codex_pick_scope()` needed (single scope); validate `--scope`
  directly in `setup_codex_cli_tool` per the D-018 single-scope path.

`write_codex_config(dest)` merges into an existing `~/.codex/config.toml`
preserving user-owned keys. TOML merging in bash is awkward -> use a
Python heredoc. **Dependency check:** Python stdlib has read-only
`tomllib` (3.11+) but NO stdlib TOML *writer*. Options: (a) require a
third-party writer (`tomli-w` / `tomlkit`) -- violates the "no new
runtime deps" scope; (b) hand-roll a minimal, section-scoped writer that
only rewrites the `[model_providers.argo]` table and leaves the rest
byte-for-byte -- more code but keeps the zero-dep guarantee; (c) since
Python 3.10 is the compute-node floor but this writer runs on the
**laptop**, the laptop's Python may be < 3.11 (no `tomllib` at all). This
is a genuine design fork and the biggest single risk item -- see Risks.

`ensure_codex_installed()`: codex ships via `npm install -g @openai/codex`
or `brew install codex` or the standalone installer. Detect `command -v
codex`; prefer `brew` on macOS, else npm/installer. Prepend install
location to `PATH`.

### Dispatcher arms (`do_post_tunnel_for_cli_tool`)

Each new tool gets an arm mirroring the existing two: call
`setup_<name>_cli_tool`, then `gather_summary; render_summary`, then
tool-specific tail messages:

- aider: "Run: aider" + the OpenAI-compatible endpoint line (like the
  opencode arm) + H7 privacy warning.
- codex: "Run: codex" + (if `env_key` chosen) the exact
  `export ARGO_ANYWHERE_TOKEN=<user>` line the user must add to their
  shell + a note that the provider is user-scope-only.

## Trade-offs considered

1. **aider config format: YAML config file vs `.env` vs pure env vars.**
   Chose `~/.aider.conf.yml` (YAML) as primary because it is the durable,
   inspectable, single-source form that matches our "write a config file"
   contract (`handle_config_file` + a `write_*_config` writer). `.env`
   would work but splits state across files and is more surprising to
   users who later inspect their config. Pure env-vars-only would leave
   nothing for `clean` to enumerate and no file for `handle_config_file`
   to manage.

2. **codex Responses API vs waiting.** codex has no Chat-Completions
   fallback (`wire_api` accepts only `responses`), so we cannot route it
   through the proven `/v1/chat/completions` path. We chose to **gate
   codex on an argo-proxy Responses-API maturity check** rather than
   ship it against a still-hardening surface. Concretely: implement aider
   first (Phase 5a); implement codex (Phase 5b) only after a live probe
   confirms `/v1/responses` works end-to-end against ANL for a
   representative model. The v3.2.0a0 codex E2E tests suggest the mature
   surface lands in the argo-proxy 3.2.x stable line.

3. **codex auth: `env_key` vs `experimental_bearer_token` vs command.**
   Chose `env_key` as the default (keeps the username out of the config
   file -> better than the aider/claudecode clear-text approach), with
   the command-backed `auth.command` flagged as the future SH-01-aligned
   upgrade. Rejected `experimental_bearer_token` as the default because
   it reintroduces the H7 clear-text exposure that `env_key` avoids.

4. **codex TOML writing: third-party writer vs hand-rolled vs `tomllib`.**
   Leaning toward a **hand-rolled section-scoped writer** (option b) to
   preserve the zero-runtime-dep guarantee (D-002 scope), accepting more
   heredoc code. This must be decided before codex implementation begins
   because it affects the writer's whole shape. The laptop-Python-<3.11
   case (no `tomllib`) means we cannot even *read* existing TOML with the
   stdlib on older laptops -> the hand-rolled writer must also do a
   tolerant hand-parse, OR we require `tomllib` and document a Python
   3.11+ laptop floor for codex specifically. This is D-NNN-worthy.

5. **codex scope: global-only vs faking project scope.** Chose
   global-only because codex itself ignores provider keys in project
   configs. Faking project scope would write a `.codex/config.toml` that
   codex silently ignores for the provider block -- a silent-failure
   landmine exactly of the class D-016 forbids. Declaring
   `codex_scope_values() -> global` and validating eagerly is the
   honest, fail-loud choice.

## Testing plan

Both tools gate "shipped" on the project's live-verification discipline
(no mocked SSH/Duo/argo-proxy). Per-tool smoke + live tests:

**aider (Phase 5a):**

1. Smoke: `bash -n argo_anywhere.sh`; `list-tools` shows `aider`;
   `--cli-tool aider --scope projct status` dies with the D-018 vocab
   error; `write_aider_config /tmp/x.yml` produces valid YAML with the
   right `openai-api-base` + key (assert PROXY_PORT non-empty first).
2. Live: `--cli-tool aider client` end-to-end -> `aider --model
   openai/<model>` answers through the tunnel; ALL GREEN status.
3. Regression: existing opencode + claudecode flows unchanged.

**codex (Phase 5b, gated):**

1. Pre-req live probe: with a healthy tunnel, `curl .../v1/responses`
   with a representative model returns a valid Responses stream (NOT an
   SSE error). If this fails, codex work stops until argo-proxy's
   Responses surface matures.
2. Smoke: `list-tools` shows `codex`; single-scope vocab validation;
   `write_codex_config` round-trips an existing `~/.codex/config.toml`
   preserving unrelated user keys (the TOML-merge correctness test --
   this is the highest-value unit test given trade-off #4).
3. Live: `--cli-tool codex client` -> `codex` answers through the tunnel.
4. Regression: all three prior tools unchanged.

## Risks

- **codex Responses-API immaturity (HIGH).** argo-proxy's `/v1/responses`
  is recent and still hardening; codex has no fallback protocol. Mitigation:
  gate codex behind the live probe above; ship aider independently first.
- **codex TOML-writer / laptop-Python version (MEDIUM).** No stdlib TOML
  writer; `tomllib` reader needs Python 3.11+. Mitigation: decide
  hand-rolled-writer vs Python-floor as a D-NNN before coding; the
  writer's shape depends on it.
- **codex per-model temperature (G3 from the 2026-07-08 upstream audit)
  (LOW/MEDIUM).** If codex sends `temperature` for opus-4-8, argo-proxy
  v3.1.2 does not strip it (`_NO_TEMPERATURE_MODELS = {"claudeopus47"}`)
  -> upstream 400. Mitigation: file the `+claudeopus48` upstream one-liner
  (see `docs/AUDIT_2026-07-08_argo-proxy-upstream.md` UP-10 disposition);
  document as a known limitation until fixed.
- **aider privacy (LOW).** Clear-text username in config (H7 class).
  Mitigation: reuse the existing H7 dispatcher-arm warning.

## Action items

1. Add codex + aider to PLAN.md Section 4 roadmap (codex is currently
   absent; aider is Phase 5) and Section 2 API surface -- **done**
   (2026-07-08; Phase 5 line rewritten to cover both; API-surface
   `--cli-tool` values `codex`/`aider` documented).
2. Draft the codex Responses-API + TOML-writer design decision (D-NNN)
   in PLAN.md before any codex code -- pending (Phase 5b prerequisite).
3. Implement aider (Phase 5a): `write_aider_config` (+ scratch fallback),
   `ensure_aider_installed`, `aider_scope_values`, `aider_pick_scope`,
   `_aider_check_conflicts`, `setup_aider_cli_tool`, config-path
   constants, `CLI_TOOLS_AVAILABLE` row, `do_post_tunnel_for_cli_tool`
   arm (with H7 privacy warning), `update_aider_cli_tool` +
   `UPDATE_COMPONENTS_AVAILABLE` row + `mode_update` case -- **done**
   (2026-07-08; `argo_anywhere.sh`). Smoke + correctness tests pass:
   `bash -n`; `list-tools` shows aider; `--scope projct` dies with the
   D-018 vocab error; writer produces valid YAML, preserves user keys on
   merge, refuses-to-merge on broken YAML (leaving the file untouched),
   and backs-up + scratch-writes on the no-PyYAML fallback.
 4. Live-test aider (real SSH + Duo + argo-proxy): `--cli-tool aider
    client` end-to-end, then `aider --model openai/<model>` answers
    through the tunnel; ALL GREEN status; opencode + claudecode
    regression -- **PASSED 2026-07-09** (`notes/test_plan_lifecycle.md`
    Test 1: default gpt-4o + opus-4.8 both answer; Test 6 opencode
    regression clean). The earlier live run caught an
    `ensure_aider_installed` defect (install-method ordering, see the
    finding below) and the model-id/temperature defects (also below);
    all fixed + re-verified on the passing run.

### Live-test finding (2026-07-08): install-method ordering + verify-and-fallthrough

The first `--cli-tool aider client` live run failed at the install step:
on a machine with `pipx` present and a very new default Python
(3.13/3.14 via `PIPX_DEFAULT_PYTHON`), the original `ensure_aider_installed`
tried `pipx install aider-chat` FIRST, which failed to *build* the
pinned `numpy==1.24.3` (no wheel for that CPython), then warn-and-gave-up
without trying the robust method. Two defects:

1. **Wrong method order.** aider's pinned deps often lack wheels for the
   newest CPython, so methods that use the user's Python (`pipx`, bare
   `uv tool install`) are the fragile ones. Upstream's #1 recommendation
   is the standalone installer / uv one-liner, both of which
   bundle/fetch **Python 3.12**. Fix: try the self-contained standalone
   installer FIRST, then uv pinned `--python python3.12 --with pip`, then
   pipx last.
2. **No fallthrough on failure.** A failed method must try the next, not
   warn-and-die. Fix: added `_aider_on_path` (detect + PATH-prepend) and
   VERIFY a working binary after each method, falling through on failure.

Verified on the reporting machine: the standalone installer fetched
Python 3.12 + a modern numpy and installed `aider 0.86.2` at
`~/.local/bin/aider` (first entry in `_aider_on_path`'s location list);
`ensure_aider_installed` now detects it even when `~/.local/bin` is off
PATH. **Reusable for codex Phase 5b**: apply the same
self-contained-first + verify-and-fallthrough discipline to
`ensure_codex_installed` (codex ships via npm/brew/installer with the
same "user's toolchain may be wrong" risk).

### Live-test finding (2026-07-08): model id must carry the `argo:` prefix

After the install fix, the first `aider` chat returned "Empty response
received from LLM." Root cause: the model string. aider routes an
OpenAI-compatible provider via `openai/<id>`, and `<id>` must be EXACTLY
what argo-proxy's `/v1/models` advertises -- which at ANL is the
`argo:`-prefixed id (e.g. `argo:claude-opus-4.8`, `argo:gpt-5-nano`). A
bare `gpt-5-nano` (or a typo like `claudopus48`) does not resolve and
argo-proxy returns an empty response rather than an error. Two fixes:

1. `write_aider_config` default changed from `openai/gpt-5-nano` to
   `openai/argo:gpt-5-nano`.
2. The dispatcher run-hint now shows the correct format
   (`aider --model openai/argo:claude-opus-4.8`) and points at
   `list-models` for the exact served ids.

Live-confirmed via a direct `/v1/chat/completions` probe: `model:
"argo:claude-opus-4.8"` returns a clean response through the tunnel
(bearer = ANL username). This also confirms **UP-10 G1 + G2 on the live
chat path**: ANL serves `argo:claude-opus-4.8` (G1 dormant) and it
responds cleanly (G2 fixed). The 43-model `/v1/models` list at ANL
includes opus 4.1/4.5/4.6/4.7/4.8, sonnet 4.5/4.6, haiku 4.5, the
gpt-5.x family, gemini 2.5/3.x, and the o-series.

**Reusable for codex Phase 5b**: the same "send the exact `argo:` id
from `/v1/models`, not a friendly name" rule applies; codex's
`model_providers.argo` block + `model` key must use the advertised id.

### Live-test finding (2026-07-08): aider sends `temperature`; reasoning/opus models reject it (empty stream)

Even with the correct model id, aider returned "Empty response received
from LLM" for `argo:claude-opus-4.8` -- while a direct curl with the
same id + bearer worked. Bisected the difference by reproducing aider's
request shape against the proxy:

| Model | temperature | Result |
|:------|:------------|:-------|
| opus-4.8 | none | streams cleanly |
| opus-4.8 | `0` | empty `data: [DONE]` |
| gpt-4o | `0` | streams cleanly |
| gpt-5-nano | none | empty `data: [DONE]` |

Root cause: aider (via LiteLLM) sends `temperature` by default
(`use_temperature: true` for models it doesn't recognize -- and it
doesn't recognize the `argo:`-prefixed ids). Reasoning / opus-4.7+ /
gpt-5 / o-series / gemini-2.5+ models **reject** `temperature`, and
argo-proxy's upstream returns an EMPTY stream rather than an error --
the aider-facing surfacing of the audit's **UP-10 G3** (broader than
opus-only: the whole reasoning-model class is affected).

Fix (both landed in `write_aider_config`):

1. **Emit a sibling `.aider.model.settings.yml`** (same scope dir as the
   config) with `use_temperature: false` + `streaming: true` for all
   argo: models, and point the config at it via `model-settings-file`.
   Disabling temperature is harmless for models that accept it (aider
   just omits the param), so we apply it to the whole served set
   (future-proof; no drift-prone classification).
2. **Change the default model from `gpt-5-nano` to `gpt-4o`.** gpt-5-nano
   returns empty EVEN WITH temperature disabled (a `-nano` reasoning
   quirk on the ANL gateway; the full `gpt-5` works). gpt-4o is a
   non-reasoning model that works out of the box.

Live-confirmed with the real aider binary: default (gpt-4o) responds;
`aider --model openai/argo:claude-opus-4.8` responds ("I am Claude, made
by Anthropic") -- the previously-empty scenario now works. `clean` also
extended to sweep both aider files (global scope).

**Reusable for codex Phase 5b**: codex/aider both send sampling params
that reasoning models reject; codex's provider config will need the
equivalent temperature/sampling suppression, and its default model
should likewise avoid the `-nano` reasoning variants.
5. Run the codex `/v1/responses` live probe against ANL to decide the
   codex go/no-go and target argo-proxy version -- pending (needs a live
   tunnel; user-run).
6. Implement + live-test codex (Phase 5b) contingent on items 2 + 5 --
   pending.

---

*Created 2026-07-08 by Ahmed Attia (with substantial AI assistance from
Claude per `CONTRIBUTORS.md`). Config-format facts verified against
developers.openai.com/codex/config-reference and aider.chat/docs/config
on 2026-07-08; argo-proxy `/v1/responses` route verified against the
v3.1.2 source (`app.py:351`).*
