# Upstream audit re-walk: `Oaklight/argo-proxy` v3.1.2 (+ v3.2.0a0) and `Oaklight/llm-rosetta` v0.6.10-v0.6.12 (+ v0.7.0a*) vs `argo-anywhere` v2.2.0

*Created 2026-07-08 by Ahmed Attia (with substantial AI assistance from
Claude per [`CONTRIBUTORS.md`](../CONTRIBUTORS.md)). Scope: delta against
[`AUDIT_2026-06-17_argo-proxy-upstream.md`](AUDIT_2026-06-17_argo-proxy-upstream.md)
(the v3.1.0 + v3.1.1 baseline). Covers `argo-proxy` **v3.1.2** (PyPI
2026-06-21, commit `6cfc918`) plus the **v3.2.0a0** pre-release (2026-06-27,
commit `b0aafaf`), and `llm-rosetta` **v0.6.10** / **v0.6.11** / **v0.6.12**
(2026-06-19 .. 2026-06-23) plus the ongoing **v0.7.0a\*** alpha series
(latest `0.7.0a3`, 2026-07-08). `argo-anywhere` baseline unchanged:
v2.2.0 tag `737563d`. This re-walk fires per the parent audit's stated
trigger ("next `argo-proxy` release after v3.1.1, OR next `llm-rosetta`
release after v0.6.9, OR ANL gateway adding `claudeopus48` to
`/v1/models`"); the first two conditions both fired.*

---

## Table of contents

- [Executive summary](#executive-summary)
- [1. What changed upstream since v3.1.1 / v0.6.9](#1-what-changed-upstream-since-v311--v069)
- [2. Re-walk of the watch-list (delta rows only)](#2-re-walk-of-the-watch-list-delta-rows-only)
- [3. Finding dispositions](#3-finding-dispositions)
- [4. New watch-list rows](#4-new-watch-list-rows)
- [5. Recommended follow-ups + revised priority for v2.2.1](#5-recommended-follow-ups--revised-priority-for-v221)
- [6. Methodology + reproducibility](#6-methodology--reproducibility)

---

## Executive summary

**Field confirmation (2026-07-08).** The maintainer's live ANL compute
node reports `argo-proxy --version` = **argo-proxy 3.1.2 + llm-rosetta
0.6.12** (already latest; no upgrade offered), and a direct
`/v1/chat/completions` probe with `model: "argo:claude-opus-4.8"`
returned a clean response through the tunnel (bearer = ANL username).
This live-confirms UP-10 on the actual chat path:

- **G1 dormant** -- ANL `/v1/models` advertises `argo:claude-opus-4.8`
  (the full 43-model list includes opus 4.1/4.5/4.6/4.7/4.8, sonnet
  4.5/4.6, haiku 4.5, gpt-5.x, gemini 2.5/3.x, o-series), so the
  hardcoded `_DEFAULT_CHAT_MODELS` fallback is never reached.
- **G2 fixed** -- opus-4-8 responds cleanly (no empty/malformed
  response), consistent with `llm-rosetta 0.6.12 >= 0.6.10` carrying the
  `claudeopus48` shim `model_overrides` fix.

Operational note surfaced during the same session: clients must send the
EXACT `/v1/models` id (`argo:claude-opus-4.8`), not a friendly name; a
bare / mistyped name yields an empty response rather than an error.
(Recorded in [`notes/impl_codex_aider.md`](../notes/impl_codex_aider.md)
as the aider default-model fix.)

**Runtime contract still fully intact.** Every `argo-proxy` interface
`argo-anywhere` v2.2.0 consumes (`pip install argo-proxy`,
`argo-proxy --version`, `argo-proxy serve --help`, `argo-proxy serve`
under screen/tmux/nohup, `/health`, the YAML config with the five keys
we own) exists with identical semantics in v3.1.2. **Zero broken
consumption points.** Our PyYAML merge preserves every key in the
v3.1.2 config sample.

Four upstream changes warrant attention; three are net positives, one is
a look-ahead:

- **UP-10 (opus-4-8) is now fixed at the shim layer.** `llm-rosetta
  v0.6.10` added `claudeopus48: thinking_type: adaptive` to the
  `argo--anthropic` shim `model_overrides` (bisected: absent in v0.6.9,
  present v0.6.10 -> v0.6.12 and the v0.7.0a series). Because `argo-proxy
  v3.1.2` still pins `llm-rosetta>=0.6.8,<0.7.0`, a fresh `pip install
  argo-proxy` today resolves llm-rosetta to `0.6.12` and therefore
  **ships the opus-4-8 thinking-type fix by default**. This closes the
  primary gap (G2) UP-10 was blocked on. Two smaller gaps remain inside
  `argo-proxy` itself (G1 registry default, G3 temperature stripping);
  see [Finding dispositions](#3-finding-dispositions).
- **New `socket:` config key** (`argo-proxy v3.1.2`). Unix-domain-socket
  listening (`--socket` / `socket:`), perms `0600`, targeted at HPC
  shared hosts. It is compatible with our writer (we own only five keys;
  upstream only serialises `socket` when non-empty) but it is a genuinely
  interesting transport option for ANL compute nodes and earns a
  watch-list row. v3.1.2 also fixed the `--host` CLI flag (previously a
  no-op).
- **`/v1/responses` endpoint is live in v3.1.2** (`app.py:351`). The
  OpenAI Responses API surface is what the OpenAI Codex CLI requires
  (`wire_api = "responses"`), so this materially unblocks future codex
  support. See the companion design note
  [`notes/impl_codex_aider.md`](../notes/impl_codex_aider.md).
- **v3.2.0a0 pre-release** migrates to the `llm-rosetta 0.7.x`
  `ConversionPipeline` and bumps the floor to `>=0.7.0a0` (a breaking
  change vs 0.6.x). Not adoptable now (alpha), but two facts matter for
  our roadmap: (a) it will eventually force a version-floor decision when
  it stabilises, and (b) its E2E test matrix explicitly exercises the
  **codex CLI** and the OpenAI Responses input format -- upstream is
  actively validating the exact path our future codex tool would use.

**Disposition shifts vs the 2026-06-17 audit:** UP-10 downgrades from
"MEDIUM, needs live probe" to "mostly resolved at source, residual
G1/G3 caveats"; UP-02's recommended version floor should move from
`>=3.1.0` to **`>=3.1.2`**; UP-08's earlier recommendation to *drop* the
v2.3 auto-default fix is reinstated as safe for the common Claude Code
path (the shim now covers both 4.7 and 4.8). No new UP-NN findings that
break consumption; the actionable items remain the v2.2.1 doc + floor
work already queued.

---

## 1. What changed upstream since v3.1.1 / v0.6.9

### 1.1 Release timeline (new entries)

| Package | Version | Upload date | Headline | Hits our surface? |
|:--------|:--------|:------------|:---------|:------------------|
| argo-proxy | **v3.1.2** | 2026-06-21 | Unix-socket listener (`--socket` / `socket:`, `0600`); startup banner shows listening address; `--host` flag fixed (was a no-op); `/refresh` registered in `--dev`. | **Yes** -- new `socket` config key (preserved by our merge); `--host` fix is cosmetic for us. |
| argo-proxy | **v3.2.0a0** (pre-release) | 2026-06-27 | Migrate to `llm-rosetta 0.7.x` `ConversionPipeline`; bump floor to `>=0.7.0a0` (BREAKING vs 0.6.x); E2E tests add codex CLI + OpenAI Responses input. | **Look-ahead** -- not adoptable (alpha); relevant to codex roadmap + future floor decision. |
| llm-rosetta | **v0.6.10** | 2026-06-19 | **Added `claudeopus48` to `argo--anthropic` shim `model_overrides`** (`thinking_type: adaptive`). | **Yes** -- closes UP-10 G2 at the shim layer. |
| llm-rosetta | **v0.6.11** | 2026-06-21 | Patch release within the 0.6.x line; `claudeopus48` override retained. | Indirect (carried by argo-proxy's `<0.7.0` pin). |
| llm-rosetta | **v0.6.12** | 2026-06-23 | Patch release; `claudeopus48` override retained; latest stable resolved by `argo-proxy`'s pin. | Indirect. |
| llm-rosetta | **v0.7.0a0 .. v0.7.0a3** | 2026-06-25 .. 2026-07-08 | New `ConversionPipeline` API (target of argo-proxy v3.2.0a0). Outside argo-proxy v3.1.2's `<0.7.0` pin. | **Look-ahead** only. |

### 1.2 Config schema delta (v3.1.1 -> v3.1.2)

Verified against `argo-proxy-3.1.2/src/argoproxy/config/model.py`.

**Added:** `socket: str = ""` (`model.py:33`) -- Unix-domain-socket path;
overrides `host:port` when set. `to_dict` only serialises it when
non-empty (`model.py:252-254`), matching the upstream "omit default"
convention already noted for `anthropic_stream_mode`.

**Unchanged:** the five keys we own (`config_version`, `user`, `host`,
`port`, `verbose`) all remain in the dataclass with identical types and
semantics (`model.py:35`, `:54`, and the `from_dict` mapping at
`:216-238`). `from_dict` still silently drops unknown keys (`model.py:232`:
`{k: v for k, v in config_dict.items() if k in cls.__annotations__}`),
which is why UP-07 (legacy `use_legacy_argo` / `force_conversion`
silent-ignore) still applies.

### 1.3 Runtime-dependency delta

`argo-proxy-3.1.2/pyproject.toml`:

```toml
requires-python = ">=3.10"
dependencies = [
    "aiohttp>=3.12.2",
    "llm-rosetta>=0.6.8,<0.7.0",
    ...
]
[project.optional-dependencies]
# httpx is dev-only:
#   "httpx>=0.28.1",
```

No change vs v3.1.1: `httpx` remains dev-only (WATCH-04 regression vector
still gone), `llm-rosetta` still pinned `>=0.6.8,<0.7.0`. The pin is what
guarantees a fresh install picks up the opus-4-8 shim fix (0.6.10+) while
staying off the breaking 0.7.x line.

### 1.4 HTTP routes

`argo-proxy-3.1.2/src/argoproxy/app.py` registers (unchanged plus one
newly relevant to us):

- `/health` (`:335`, `:364`) -- HTTP 200 `{"status": "healthy"}`. No change.
- `/v1/chat/completions` (`:350`) -- OpenAI Chat. No change.
- **`/v1/responses` (`:351`)** -- OpenAI Responses API. Present since at
  least v3.1.2; this is the codex-required surface (see the impl note).
- `/v1/messages` (`:352`) -- Anthropic Messages. No change.
- `/v1/models` (`:359`), `/refresh` (`:337`, `:362`), `/version` (`:336`).

The Responses route is not new *behaviour* we rely on today, but it is
the load-bearing fact for the codex-support prep, so it is captured here
rather than only in the impl note.

---

## 2. Re-walk of the watch-list (delta rows only)

The 2026-06-17 audit re-verified all 15 rows (13 green, 2 amber, 0 red).
This re-walk re-checks only the rows a v3.1.2 / v0.6.1x change could move;
all others remain as the parent audit left them.

| # | Row | Status at v3.1.2 | Verification trace |
|:--|:----|:-----------------|:-------------------|
| WATCH-03 | `/health` returns HTTP 200 | green | `app.py:335`, `:364` unchanged. |
| WATCH-04 | clean `pip install` works | green (likely) | `httpx` still dev-only; issue #117 vector still gone. Opportunistic fresh-venv probe still deferred to a live test. |
| WATCH-06 | five owned keys still accepted | green | `config/model.py:35,54` + `from_dict:216-238`. |
| WATCH-08 | `anthropic_stream_mode` default stays `force` | green | Unchanged; still `to_dict`-omitted when equal to default. |
| WATCH-10 | Python 3.10+ minimum | green | `requires-python = ">=3.10"` in v3.1.2. |
| WATCH-11 | no new system-level dependency | green | Deps unchanged from v3.1.1; all pure-pip. |
| WATCH-13 | `verbose: true` still logs prompts to stdout; `log_to_file` separate | green (unchanged) | No log-destination changes in v3.1.2. |
| WATCH-14 | PyPI package still ships | green | `pypi.org/pypi/argo-proxy/json` returns v3.1.2 as latest stable. |
| WATCH-15 | screen-friendly (no daemonisation) | green (caveat) | No daemonisation change; but the new `socket:` mode changes the listener surface -- see new row WATCH-16. |

**Net:** no row regresses. Two new rows are added below (WATCH-16 socket
mode; WATCH-17 the 0.7.x / v3.2.x pipeline migration).

---

## 3. Finding dispositions

### UP-10 (opus-4-8 thinking-type) -- now MOSTLY RESOLVED at source

The 2026-06-17 audit identified three gaps for opus-4-8. Status at
`argo-proxy v3.1.2` + `llm-rosetta v0.6.12`:

| Gap | 2026-06-17 status | 2026-07-08 status | Evidence |
|:----|:------------------|:------------------|:---------|
| **G2** -- adaptive-thinking override (the gap that reproduced the Phase-4 release-gate bug) | live (shim `model_overrides` had only `claudeopus47`) | **FIXED (live-confirmed)** | `llm-rosetta 0.6.10+` `argo--anthropic/provider.yaml:30-33` now maps both `claudeopus47` and `claudeopus48` to `thinking_type: adaptive`. Bisected: absent v0.6.9, present v0.6.10 -> v0.6.12 + v0.7.0a3. **Live install runs `llm-rosetta 0.6.12`** (maintainer's `argo-proxy --version`, 2026-07-08), so the fix is present on the node -- not just in source. |
| **G1** -- model-registry default | live (`_DEFAULT_CHAT_MODELS` stopped at `claudeopus47`) | **dormant on the live gateway** | `argo-proxy-3.1.2/src/argoproxy/models.py:60-64` still lists only `claudeopus41/45/46/47`, so the hardcoded fallback lacks opus-4-8. But the maintainer runs `claude-opus-4-8` on OpenCode against ANL, confirming ANL's `/v1/models` DOES serve opus-4-8 -> the hardcoded default is never reached. Would re-activate only if ANL's registry stopped advertising opus-4-8. |
| **G3** -- temperature stripping | live (`_NO_TEMPERATURE_MODELS = {"claudeopus47"}`) | **still live upstream; LIVE-CONFIRMED reachable via aider; mitigated at our layer** | `argo-proxy-3.1.2/src/argoproxy/endpoints/dispatch.py:386` still `{"claudeopus47"}`. Confirmed reachable 2026-07-08: aider (via LiteLLM) sends `temperature` by default, and every reasoning / opus-4.7+ / gpt-5 / o-series / gemini-2.5+ model returns an EMPTY stream (not an error) when `temperature` is present. Not opus-only -- the whole reasoning-model class. Mitigated in `write_aider_config` by emitting `.aider.model.settings.yml` with `use_temperature: false` for all argo: models (see [`notes/impl_codex_aider.md`](../notes/impl_codex_aider.md)); codex Phase 5b will need the same. Upstream one-liner (add `claudeopus48` + the reasoning set to `_NO_TEMPERATURE_MODELS`) still worth filing but no longer blocks our tools. |

**Disposition.** The bug that actually hurt users (G2) is fixed by
default on any fresh install. G1 is a soft fallback-to-`gpt-5-nano`
concern gated on the ANL registry state; G3 is a narrow sampling-param
concern. Both G1 and G3 remain worth an upstream one-line PR
(`+claudeopus48` to both sets), but neither blocks v2.2.1. The three
live-probe commands from the 2026-06-17 audit UP-10 section remain the
way to confirm ANL's current `/v1/models` state.

### UP-02 (version floor) -- STRENGTHEN to `>=3.1.2`

The 2026-06-17 audit recommended bumping the (still-unimplemented) soft
floor in `ensure_argoproxy_installed` from `>=3.0.3` to `>=3.1.0`. Given
v3.1.2 additionally fixes `--host` and adds socket support, and given the
opus-4-8 shim fix rides in on any install that resolves llm-rosetta
`>=0.6.10` (guaranteed by argo-proxy's own pin at v3.1.0+), the
recommended floor should be **`>=3.1.2`**. The floor is still trivially
satisfied by a fresh install; its purpose is to nudge stale venvs past
the opus-4-7/4-8 fixes and the `--host` fix.

### UP-08 (opus-4-7 doc + v2.3 auto-default fix) -- auto-default fix droppable again for the common path

The 2026-06-17 audit *reinstated* the v2.3 `env.ANTHROPIC_MODEL`
auto-default fix specifically because opus-4-8 had reissued the
limitation (UP-10). Now that `llm-rosetta 0.6.10+` covers opus-4-8 at the
shim layer, the common Claude Code path (`claude --model
claude-opus-4-8` with `thinking.type=enabled`) works without our
intervention on any install with `argo-proxy >= 3.1.0` (which pins
llm-rosetta `>= 0.6.8`, and a fresh resolve gets 0.6.12). The v2.3
auto-default fix can therefore be treated as **optional / droppable**
again for Claude Code, contingent on a live probe confirming ANL serves
opus-4-8 with the fix active. The dynamic-detection design
(introspect the bundled shim YAML) is now moot for the 4.7/4.8
generation; keep it filed only as a template for the *next* Opus
generation that outpaces the shim.

### UP-07 (legacy key silent-ignore) -- UNCHANGED

`from_dict` still silently drops `use_legacy_argo` / `force_conversion`
(`argo-proxy-3.1.2/src/argoproxy/config/model.py:232`). The v2.2.1
warn-and-strip recommendation stands verbatim.

### UP-04 (stale user-preserved-keys comment) -- MORE material

The comment is now additionally stale for `socket:` (new in v3.1.2). The
2026-06-17 recommendation (replace the enumerated list with a link to
upstream `config.sample.yaml` + "we own 5 keys; everything else is
preserved") is the right fix and neatly sidesteps having to re-enumerate
on every upstream schema addition.

---

## 4. New watch-list rows

Append these to the running watch-list (parent audit maintained 15 rows;
the 2026-06-17 re-walk left them at 15; this adds two, total 17).

| # | Row | Why it matters | Re-check trigger |
|:--|:----|:---------------|:-----------------|
| WATCH-16 | Unix-socket listener mode (`socket:` config key / `--socket`) does not become a default that bypasses our `host:port` + `/health` polling. | We poll `http://localhost:PORT/health`; a socket-only listener would answer on a Unix path our tunnel + health check don't target. Today `socket` is opt-in and empty by default, so we are safe -- but a future default flip would break our health model. | Any argo-proxy release that changes the `socket` default or makes socket-mode the recommended HPC path. |
| WATCH-17 | The `llm-rosetta 0.7.x` `ConversionPipeline` migration (argo-proxy v3.2.x) preserves the `argo--anthropic` shim `model_overrides` mechanism and the five config keys we own. | The whole opus-4-7/4-8 fix chain rides on the shim `model_overrides`; a pipeline rewrite could relocate or rename that mechanism. Our config-key ownership must survive the rewrite too. | The first stable `argo-proxy v3.2.0` release (currently alpha), OR any `llm-rosetta 0.7.x` stable release. |

---

## 5. Recommended follow-ups + revised priority for v2.2.1

Updated priority order (supersedes the 2026-06-17 audit's §5 for the
v2.2.1 release):

1. **UP-02** (MEDIUM) -- implement the soft version-floor check in
   `ensure_argoproxy_installed` (still unimplemented as of v2.2.0 tag
   `737563d`), with `_required_min="3.1.2"`. This is the single
   highest-value item: it lands the opus-4-7/4-8 fix, the `--host` fix,
   and socket support on any stale venv. (The maintainer's reference node
   already satisfies this floor at 3.1.2 + llm-rosetta 0.6.12; the check
   is for OTHER users on stale venvs.)
2. **UP-10 doc update** (MEDIUM) -- in [`docs/LIMITATIONS.md`](LIMITATIONS.md)
   "Upstream stack", mark BOTH opus-4-7 (fixed at `argo-proxy >= 3.1.0` +
   `llm-rosetta >= 0.6.8`) and opus-4-8 (fixed via `llm-rosetta >= 0.6.10`
   shim `model_overrides`) as RESOLVED, with the residual G1/G3 caveats
   noted. Update the README "Heads up before you start" callout to match.
   Mark [`notes/agent_feedback.md`](../notes/agent_feedback.md) entry 6
   as fully rolled-up for both model generations.
3. **UP-07** (MEDIUM) -- warn-and-strip `use_legacy_argo` /
   `force_conversion` in `write_argoproxy_config`'s PyYAML heredoc.
   Unchanged from 2026-06-17.
4. **UP-04** (LOW) -- replace the stale user-preserved-keys comment with a
   link + "we own 5 keys" one-liner (now also stale for `socket:`).
5. **UP-09a/b/c** (LOW) -- doc-only: model-name spot-check; README note on
   the 24h auto-refresh; SECURITY.md note on `log_to_file`.

**Newly recommended (this re-walk):**

6. **Optional upstream one-liners** (courtesy, not blocking): file
   `+claudeopus48` PRs against `argo-proxy`'s `_DEFAULT_CHAT_MODELS`
   (`models.py:60-64`, closes G1) and `_NO_TEMPERATURE_MODELS`
   (`dispatch.py:386`, closes G3). Cross-reference `llm-rosetta` issue
   #220 (comprehensive per-model probe).

**Dropped / moot:** the v2.3 dynamic-shim-introspection auto-default fix
for opus-4-8 -- superseded by the `llm-rosetta 0.6.10` shim fix (kept
only as a design template for a future outpacing Opus generation).

---

## 6. Methodology + reproducibility

**Sources consulted** (all 2026-07-08):

- PyPI JSON for both packages
  (<https://pypi.org/pypi/argo-proxy/json>,
  <https://pypi.org/pypi/llm-rosetta/json>) -- version list, upload
  dates, `requires_python`.
- GitHub Releases page <https://github.com/Oaklight/argo-proxy/releases>
  -- v3.1.2 + v3.2.0a0 release notes.
- `argo-proxy v3.1.2` source tarball
  (<https://codeload.github.com/Oaklight/argo-proxy/tar.gz/refs/tags/v3.1.2>)
  -- `src/argoproxy/config/model.py` (schema + `from_dict` + `to_dict`),
  `src/argoproxy/app.py` (routes, incl. `/v1/responses:351`),
  `src/argoproxy/models.py` (`_DEFAULT_CHAT_MODELS:60-64`),
  `src/argoproxy/endpoints/dispatch.py` (`_NO_TEMPERATURE_MODELS:386`),
  `pyproject.toml` (deps).
- `argo-proxy v3.2.0a0` source tarball -- confirmed `/v1/responses` route
  and the `llm-rosetta>=0.7.0a0` pipeline migration.
- `llm-rosetta` v0.6.9 / v0.6.10 / v0.6.11 / v0.6.12 / v0.7.0a3 source
  tarballs -- bisected `claudeopus48` into the
  `src/llm_rosetta/shims/providers/argo/anthropic/provider.yaml`
  `model_overrides` table (first appears v0.6.10).
- Our script: [`argo_anywhere.sh`](../argo_anywhere.sh) at v2.2.0 tag
  `737563d` (`write_opencode_config`, `write_argoproxy_config`,
  `ensure_argoproxy_installed`, `CLI_TOOLS_AVAILABLE`).
- Parent audit
  [`AUDIT_2026-06-17_argo-proxy-upstream.md`](AUDIT_2026-06-17_argo-proxy-upstream.md)
  (the v3.1.0 + v3.1.1 baseline this re-walk diffs against).

**Field-confirmed** (maintainer, 2026-07-08):

- `argo-proxy --version` on the live ANL node reports **argo-proxy 3.1.2
  + llm-rosetta 0.6.12** (both latest; no upgrade offered). Confirms the
  G2 shim fix is present on the install (llm-rosetta >= 0.6.10).
- Maintainer runs `claude-opus-4-8` on OpenCode against this proxy ->
  ANL `/v1/models` serves opus-4-8 -> G1 dormant on the live gateway.

**Not consulted** (deliberate scope limit):

- Direct `/v1/messages` + `thinking.type=enabled` probe for opus-4-8 --
  not run; the version pin (llm-rosetta 0.6.12) is sufficient evidence
  that G2 is fixed. The three probe commands in the 2026-06-17 audit
  UP-10 section remain available if a byte-level confirmation is wanted.
- Codex / aider live integration against argo-proxy -- deferred; the
  companion design note [`notes/impl_codex_aider.md`](../notes/impl_codex_aider.md)
  scopes the work but does not implement or live-test it.

**Reproduction** (~20 minutes):

1. `curl https://pypi.org/pypi/argo-proxy/json` and the llm-rosetta
   equivalent; confirm latest stable + upload dates.
2. WebFetch the GitHub Releases page for the release-note diff.
3. `curl -fsSL .../argo-proxy/tar.gz/refs/tags/v3.1.2 | tar xz` into
   `/tmp`; grep `config/model.py`, `app.py`, `models.py`,
   `endpoints/dispatch.py`.
4. Bisect `claudeopus48` across the llm-rosetta tags by extracting each
   tarball and grepping `provider.yaml`.
5. Diff findings against the parent audit; write UP dispositions +
   any new watch-list rows.

---

*Re-walk closed 2026-07-08. Next re-walk trigger: the first stable
`argo-proxy v3.2.0` release (currently `v3.2.0a0` alpha; watch WATCH-17),
OR any `argo-proxy` release after v3.1.2, OR ANL gateway adding
`claudeopus48` to `/v1/models` (re-run the UP-10 live probes). Successor
file name: `AUDIT_<date>_argo-proxy-upstream.md`; cross-link to this file
and the v3.1.x baseline.*
