# Upstream audit: `Oaklight/argo-proxy` ↔ `argo-anywhere` v2.2.0

> **STATUS (2026-06-17)**: superseded for the latest upstream
> deltas by [`AUDIT_2026-06-17_argo-proxy-upstream.md`](AUDIT_2026-06-17_argo-proxy-upstream.md)
> (re-walk against `argo-proxy` v3.1.0 + v3.1.1). The 15-row
> watch-list + UP-01..UP-06 findings below remain the v3.0.4
> baseline; consult the re-walk for the v3.1.x disposition
> (UP-01 folds into new UP-08; UP-02 floor bumps to `>=3.1.0`;
> UP-03 dropped; UP-04 unchanged but more material; UP-05/UP-06
> merge into new UP-09; **new findings UP-07 + UP-08 + UP-09**).

*Created 2026-06-04 by Ahmed Attia (with substantial AI assistance
from Claude per [`CONTRIBUTORS.md`](../CONTRIBUTORS.md)). Scope:
`argo-proxy` releases through **v3.0.4** (PyPI upload
2026-05-23; commit `3ee2642` on `master`) audited against
`argo-anywhere` at `9769e70` (post-v2.2.0 docs cleanup; same
runtime contract as the v2.2.0 tag at `737563d`). The goal is
twofold: (1) catch any upstream change that breaks or improves
our current consumption of `argo-proxy`, and (2) produce a
**watch-list** of upstream hot-spots we should re-check on
each future `argo-proxy` release. This audit sits alongside
[`AUDIT_2026-05-12.md`](AUDIT_2026-05-12.md) (the 43-finding
fresh-eyes audit; 42-of-43 closed at v2.2.0) and
[`AUDIT_2026-05-18_argo-shim-comparison.md`](AUDIT_2026-05-18_argo-shim-comparison.md)
(the comparative audit that documented the Phase C local-shim
REJECTED decision).*

---

## Table of contents

- [Executive summary](#executive-summary)
- [1. How `argo-anywhere` consumes `argo-proxy`](#1-how-argo-anywhere-consumes-argo-proxy)
- [2. Upstream state as of 2026-06-04](#2-upstream-state-as-of-2026-06-04)
- [3. Findings (UP-NN) — diff our assumptions vs upstream reality](#3-findings-up-nn--diff-our-assumptions-vs-upstream-reality)
- [4. Watch-list — hot spots to re-check on every new `argo-proxy` release](#4-watch-list--hot-spots-to-re-check-on-every-new-argo-proxy-release)
- [5. Recommended follow-ups](#5-recommended-follow-ups)
- [6. Methodology + reproducibility](#6-methodology--reproducibility)

---

## Executive summary

**The runtime contract is intact.** Every `argo-proxy` interface that
`argo-anywhere` v2.2.0 consumes — `pip install argo-proxy`,
`argo-proxy --version`, `argo-proxy serve --help`, `argo-proxy serve`
under screen/tmux/nohup, the `/health` HTTP endpoint, the `/v1` route
prefix, the YAML config at `~/.config/argoproxy/config.yaml` with
`config_version`, `user`, `host`, `port`, `verbose`, `argo_base_url` —
**still exists in v3.0.4 with identical semantics** and is documented
as such in the upstream README at master (verified 2026-06-04). Our
PyYAML merge correctly preserves all v3.x optional keys (12 of them
enumerated in §3 below), including the ones introduced after v3.0.0
(`anthropic_stream_mode`, `force_conversion`, `resolve_overrides`,
`max_log_history`, `enable_payload_control`).

**Three small adjustments are warranted.** None are urgent; none break
existing installs. They are:

- **UP-01** — surface the v3.0.2 `claudeopus47` model alias + the
  v3.0.3 `thinking.type=adaptive` fix in `docs/LIMITATIONS.md`
  "Upstream stack" and in `notes/agent_feedback.md` entry 6 (the
  opus-4-7 limitation entry currently reads as if unfixed; upstream
  shipped both fixes in v3.0.2 + v3.0.3 between our v2.2.0 release
  test and now).
- **UP-02** — pin a soft floor on the installed `argo-proxy` version
  in `ensure_argoproxy_installed` (currently we pin to "has `serve`
  subcommand"; recommend bumping to `>= 3.0.3` so users automatically
  pick up the opus-4-7 fixes via the existing `--force-reinstall`
  path).
- **UP-03** — adopt the upstream-published `anthropic_stream_mode:
  force` default into our `write_argoproxy_config` writer's
  fresh-install path (it's already the upstream default at v3.0.0+,
  so this is purely a "make the config explicit so a future upstream
  default change doesn't silently shift our users").

**One known-bad behaviour upstream is not yet fixed and we should keep
watching it**: issue #117 (`Can't find httpx ?`, opened 2026-04-23
against v3.0.x betas) describes a clean-install failure that affects
exactly the kind of bootstrap path `mode_server` exercises. Verified
on 2026-06-04: open, no PR linked, no workaround in the issue thread.
See **WATCH-04** in §4.

**Zero deprecated calls.** We do not call any `argo-proxy` CLI
subcommand that has been removed, renamed, or moved between v3.0.0
and v3.0.4. We do not read any config key that has been deprecated.
We do not depend on any HTTP route prefix that has changed.

---

## 1. How `argo-anywhere` consumes `argo-proxy`

`argo-anywhere` calls `argo-proxy` through six surfaces. Each is a
potential break point on an upstream release.

### 1.1 Install + version probe

Performed by `ensure_argoproxy_installed` ([`argo_anywhere.sh:5117`](../argo_anywhere.sh#L5117)).
The script targets Python 3.10+ (matches upstream `requires_python`)
and runs:

```bash
"${venv}/bin/pip" install --upgrade argo-proxy
"${venv}/bin/argo-proxy" --version
"${venv}/bin/argo-proxy" serve --help
```

The version probe is "string non-empty + exit 0"; we do **not** parse
the version number. The `serve --help` probe is the gate: if it
fails, we re-install with `pip install --upgrade argo-proxy`. The
`--force-reinstall` user flag forces a `rm -rf "$VENV_PATH"` first.

### 1.2 Config file

Written by `write_argoproxy_config` at
[`argo_anywhere.sh:4799`](../argo_anywhere.sh#L4799). Target file:
`~/.config/argoproxy/config.yaml` (the second of the three upstream
search locations, per the upstream README). Schema we own:

```yaml
config_version: "3"
user: "<ARGO_ANYWHERE_USER>"
host: 127.0.0.1
port: <PROXY_PORT>
verbose: false      # or true if --verbose-server
argo_base_url: "https://apps.inside.anl.gov/argoapi"
```

**Key preservation contract** (D-002 + M9 from
[`AUDIT_2026-05-12.md`](AUDIT_2026-05-12.md)): we own exactly
**five** keys (`config_version`, `user`, `host`, `port`, `verbose`).
We `setdefault` on `argo_base_url` (preserve user's value if
present; default to prod URL). Every other key in the file is
**preserved verbatim** via the `yaml.safe_load → mutate-our-keys
→ yaml.safe_dump` Python heredoc.

### 1.3 Process management

`mode_server` starts the proxy under one of three session managers in
preference order: **screen** (preferred), **tmux**, **nohup**. The
session name is the global constant `SCREEN_SESSION="argovproxy"`
(no per-port suffix; this is the single-instance constraint D-006).

The invocation is the bare `argo-proxy serve` — no positional config
path, no flags. We rely on the default config search order finding
`~/.config/argoproxy/config.yaml`.

### 1.4 Health check

`local_tunnel_status` and the monitor loop probe
`http://localhost:<PROXY_PORT>/health` over the SSH tunnel (or
directly on the node in single-host mode). We treat HTTP 200 as
"argo-proxy is up." The probe is a `curl -fsS --max-time 5`.

### 1.5 Route prefix used by clients

The OpenCode + Claude Code + (future) aider configs all point at
`http://localhost:<PROXY_PORT>/v1` (OpenAI Chat format) or
`http://localhost:<PROXY_PORT>` (Anthropic Messages format). These
prefixes are baked into `write_opencode_config` (line ~1898) and
`write_claudecode_config`. We do not implement format conversion
ourselves; we delegate entirely to `argo-proxy`.

### 1.6 Auth model

The ANL username is passed as the bearer token. `argo-proxy`
attributes calls by it. We never see a separate API key.

---

## 2. Upstream state as of 2026-06-04

### 2.1 Release timeline

| Version | Upload date | Headline |
|:--------|:------------|:---------|
| **v3.0.4** | 2026-05-23 | Fix: startup user-validation model selection (skip `gpt4olatest` which ARGO rejects). |
| v3.0.3 | 2026-05-23 | Fix: normalize `thinking.type=enabled → adaptive` in **all** conversion paths (passthrough + non-streaming + buffered-streaming + streaming). Closes #123, #124. **Resolves the opus-4-7 limitation** we documented in [`docs/LIMITATIONS.md`](LIMITATIONS.md) "Upstream stack". |
| v3.0.2 | 2026-05-20 | Strip `temperature` for Opus 4.7 (reasoning model rejects it with 400). Add `claudeopus47` model alias to the registry. |
| v3.0.1 | 2026-05-17 | `--dump-requests` CLI flag; `llm-rosetta` bumped to `>=0.6.0,<0.7.0`; vendored `zerodep/yaml` replaces PyYAML runtime dep; README rewritten for v3.x universal-gateway architecture. |
| v3.0.0 | 2026-04-18 | Universal 4-format gateway (OpenAI Chat + OpenAI Responses + Anthropic Messages + Google GenAI). New subcommand-based CLI (`serve`, `config init/migrate/list/env`, `update check/install`, `models`, `logs collect`). `--anthropic-stream-mode {force,retry,passthrough}` — default `force` (this is the upstream feature that obsoleted the Phase C local-shim idea). `--force-conversion` mode. Error dumps at `~/.config/argoproxy/error_dumps/`. |

### 2.2 Open upstream issues that touch our surface

Filtered to "could affect a user running `argo-anywhere`":

| # | Title | Status | Hits us? |
|:--|:------|:-------|:---------|
| 117 | `Can't find httpx ?` | open since 2026-04-23 | **Yes** — clean install on a fresh venv may fail to import `httpx`; exactly the `argovenv` first-run path we exercise. See WATCH-04. |
| 120 | `Opus 4.7 not working with claude-code` | open since 2026-04-24 | **Partially fixed** by v3.0.2 + v3.0.3, but issue stays open as a tracking ticket; opus-4-7 may still hit Claude Code 2.1.x parsing bugs even with the upstream fix. |
| 125 | "Migrate preprocessing transforms to `llm-rosetta` shims" | open since 2026-05-23 (enhancement) | **No** — internal refactor; user-visible behaviour stable. Watch for regression risk in a v3.1 cut. |
| 122 | "Track support for Google Antigravity CLI (`agy`)" | open since 2026-05-22 | **Future** — would land a new client integration upstream; we'd add a `setup_agy_cli_tool` in our own multi-tool framework if/when we want to support it. |
| 91 | Azure content-filter blocks requests with `ResponsibleAIPolicyViolation` | open since 2026-03-29 | **Upstream-gateway behaviour**; not actionable from our side. |

The other open issues (#89, #111, #114, #116, #118) are around
`--force-conversion` edge cases or `error_dumps` logging hygiene —
none of those features are enabled in our default config, so they do
not affect us today.

### 2.3 Config schema as of v3.0.x (master `config.sample.yaml`)

Verified 2026-06-04 against
[`Oaklight/argo-proxy@master/config.sample.yaml`](https://github.com/Oaklight/argo-proxy/blob/master/config.sample.yaml).
The full v3 schema is:

| Key | Default | Owned by us? |
|:----|:--------|:-------------|
| `config_version` | `"3"` | Ours (we always write `"3"`). |
| `user` | (required) | Ours. |
| `host` | `0.0.0.0` | Ours (we write `127.0.0.1` for tighter binding under SSH-tunnel topology). |
| `port` | random | Ours (we write `PROXY_PORT`). |
| `verbose` | `true` | Ours (we override to `false` for privacy; see [`docs/SECURITY.md`](SECURITY.md)). |
| `max_log_history` | `3` | User-preserved. |
| `argo_base_url` | dev URL | We `setdefault` to the prod URL; user-preserved if explicit. |
| `connection_test_timeout` | `5` | User-preserved. |
| `skip_url_validation` | conditional / `false` | User-preserved. |
| `resolve_overrides` | `{}` | User-preserved. |
| `enable_payload_control` | `false` | User-preserved. |
| `max_payload_size` | `20` MB | User-preserved. |
| `image_timeout` | `30` s | User-preserved. |
| `concurrent_downloads` | `10` | User-preserved. |
| `use_legacy_argo` | unset / `false` | User-preserved. |
| `anthropic_stream_mode` | `force` (CLI default; conditional in config) | User-preserved (currently never written by us; see UP-03). |
| `force_conversion` | `false` | User-preserved. |
| `native_openai_base_url` | derived | User-preserved. |
| `native_anthropic_base_url` | derived | User-preserved. |

**Diff vs the comment block at [`argo_anywhere.sh:4786-4790`](../argo_anywhere.sh#L4786-L4790)**:
the comment lists `verbose, argo_base_url, argo_url, argo_stream_url,
argo_embedding_url, concurrent_downloads, connection_test_timeout,
image_timeout, max_payload_size`. Three of these (`argo_url`,
`argo_stream_url`, `argo_embedding_url`) are **v2-era keys**; they
disappeared at v3.0.0 in favour of the single `argo_base_url` from
which v3 derives the other URLs internally. The comment is harmless
(the merge logic doesn't care about the names) but stale. The five
**new** v3.x keys not in the comment (`anthropic_stream_mode`,
`force_conversion`, `resolve_overrides`, `max_log_history`,
`enable_payload_control`, `skip_url_validation`,
`use_legacy_argo`, `native_openai_base_url`,
`native_anthropic_base_url`) are all correctly preserved by the
merge but the comment doesn't mention them. See UP-04.

### 2.4 CLI surface as of v3.0.4

Verified against the upstream README at master:

```
argo-proxy [-h] [--version] {serve,config,logs,update,models}
```

We call only `argo-proxy --version` and `argo-proxy serve --help` and
`argo-proxy serve` (bare). All three exist in v3.0.4. The `config
init` / `config migrate` / `update install` subcommands exist but we
do not invoke them — we manage the config file ourselves and we
manage upgrades via `pip install --upgrade argo-proxy`. This is
**deliberate**: upstream's `update install` subcommand requires a
working `argo-proxy` install already in place to bootstrap from,
whereas our `pip install --upgrade` works from a fresh venv with no
chicken-and-egg.

### 2.5 Health endpoint

The upstream README's "Utility Endpoints" table confirms `/health`
exists and is documented as the health check. Unchanged from v2.x.

### 2.6 Auth model

The upstream README's "AI Coding Tools Integration" table confirms
"All tools use your ANL username as the API key." Unchanged.

---

## 3. Findings (UP-NN) — diff our assumptions vs upstream reality

Each finding is tagged **UP-NN** for tracking. Severity is one of
**HIGH** (we are broken or imminently break), **MEDIUM** (we work but
ship a stale assertion or miss a free improvement), **LOW**
(cosmetic / doc-debt only). All v2.2.0-era findings are LOW or
MEDIUM today; the runtime contract is healthy.

### UP-01 — `docs/LIMITATIONS.md` opus-4-7 entry is now stale (MEDIUM)

**Claim audited**: [`docs/LIMITATIONS.md`](LIMITATIONS.md) "Upstream
stack: argo-proxy + AI CLI tools" describes the opus-4-7 +
Claude-Code-2.1.x failure as a *current limitation*, citing
`thinking.type.enabled` vs `thinking.type.adaptive` and the SSE-error-
as-200 mis-parse. The doc was written 2026-05-18 at v2.2.0 release.

**Upstream reality on 2026-06-04**: `argo-proxy` shipped two fixes:

- **v3.0.2** (2026-05-20): added `claudeopus47` to the model
  registry and strips `temperature` for Opus 4.7 (which rejects it
  as a reasoning model).
- **v3.0.3** (2026-05-23): added `_normalize_thinking_for_upstream`
  to **all** conversion paths (`_convert_non_streaming`,
  `_convert_buffered_streaming`, `_convert_streaming`). Closes #123,
  #124. This is the actual upstream fix for the `thinking.type`
  rejection.

**Impact**: a user reading [`docs/LIMITATIONS.md`](LIMITATIONS.md)
today would conclude opus-4-7 doesn't work, when in fact it does as
of `argo-proxy >= 3.0.3` (combined with a recent Claude Code).

**Recommendation**: revise the "Upstream stack" section to note that
v3.0.3 ships the fix; add a "Required to take effect: upgrade
`argo-proxy` to >= 3.0.3 on the compute node" callout; cross-
reference UP-02. Also update [`notes/agent_feedback.md`](../notes/agent_feedback.md)
entry 6 with a resolution note pointing at v3.0.3.

**Severity**: MEDIUM — the doc is wrong but not actively dangerous
(users who try Claude Code today will succeed; users who read the
doc first might unnecessarily switch to Sonnet).

### UP-02 — bump `argo-proxy` install floor to `>=3.0.3` (MEDIUM)

**Claim audited**: `ensure_argoproxy_installed`
([`argo_anywhere.sh:5160-5180`](../argo_anywhere.sh#L5160)) checks
only "binary exists" and "`serve --help` works." It does **not**
check the version number; any v3.x that has `serve` passes. Existing
installs of v3.0.0 / v3.0.1 / v3.0.2 are not auto-upgraded.

**Why this matters**: a user who installed `argo-anywhere` between
the v3.0.0 release (2026-04-18) and the v3.0.3 release (2026-05-23)
has an `argovenv` pinned to the version that was current at install
time. Without an explicit force-reinstall, the per-`client`-run
`pip install --upgrade` (line `5175`) **does** upgrade — but only if
a fresh install happens. The existing-venv path skips the upgrade
when the version probe passes.

Reading the code at lines 5160-5180 more carefully: the install path
runs `pip install --upgrade argo-proxy` (line 5175) on **every**
client run that lands in the "install or upgrade" branch
(`needs_install=1`), and that branch is triggered when `serve --help`
fails. The branch is NOT triggered when the existing binary's
`serve --help` succeeds — which is the case for all v3.0.x. So a
user pinned at v3.0.0 stays at v3.0.0 indefinitely.

**Recommendation**: add a soft version-floor check after the
"`serve --help` succeeds" branch:

```bash
# Soft floor: warn (don't fail) if installed version is older than
# the floor that fixes known upstream bugs we have documented as
# "fixed upstream as of vX.Y.Z". Bump this when documenting a new
# fix in docs/LIMITATIONS.md's "Upstream stack" section.
local _required_min="3.0.3"
local _installed; _installed="$("${venv}/bin/argo-proxy" --version 2>&1 | awk '{print $NF}')"
if [ -n "$_installed" ] && ! _version_ge "$_installed" "$_required_min"; then
  warn "argo-proxy ${_installed} is older than the recommended floor ${_required_min}."
  warn "  v3.0.3+ fixes the opus-4-7 thinking.type=adaptive issue."
  warn "  Upgrade with: ${venv}/bin/pip install --upgrade argo-proxy"
  warn "  Or re-run with: --force-reinstall"
fi
```

`_version_ge` would be a tiny bash helper using `sort -V` (already
used elsewhere in the script for similar comparisons; grep
`sort -V`). Implementation note: the warn is intentionally non-fatal
so we never break a working install over a version comparison.

**Severity**: MEDIUM — this is a "give the user a clue" improvement.
Strictly speaking, a user who explicitly ran `--force-reinstall` once
between 2026-05-23 and now is fully fixed.

### UP-03 — make our `write_argoproxy_config` writer set `anthropic_stream_mode: force` explicitly on fresh installs (LOW)

**Claim audited**: `write_argoproxy_config`'s **Case 1** (no existing
file → emit defaults) writes a 6-key file
([`argo_anywhere.sh:4822-4829`](../argo_anywhere.sh#L4822)). It does
not write `anthropic_stream_mode`. The upstream README documents the
CLI flag default as `force` and the YAML default as "conditional —
only persisted when set."

**Why this matters today**: nothing. v3.x defaults `anthropic_stream_mode`
to `force` internally; not writing it means we inherit the upstream
default, and the upstream default is what we want (it's the upstream
solution to Claude Code's 10-minute-timeout-on-non-streaming bug,
which is one of the reasons we rejected the Phase C local-shim per
[`AUDIT_2026-05-18_argo-shim-comparison.md`](AUDIT_2026-05-18_argo-shim-comparison.md)).

**Why it might matter tomorrow**: if upstream ever changes the
default (say, to `retry` for some perceived performance reason), our
users would silently shift. Writing the key explicitly pins behaviour
to what we tested at v2.2.0 release.

**Recommendation**: extend Case 1 to write the line:

```yaml
anthropic_stream_mode: force
```

…with a comment in the bash heredoc explaining why ("inherits the
upstream v3.x default; pinned explicitly to insulate against a
future upstream default change"). Case 2 (existing-file merge)
should add `data.setdefault('anthropic_stream_mode', 'force')`
mirroring the `argo_base_url` handling, so existing user-customised
configs are untouched.

**Severity**: LOW — speculative defence; current behaviour is correct.

### UP-04 — refresh the user-preserved-keys comment block (LOW)

**Claim audited**: the comment at
[`argo_anywhere.sh:4786-4790`](../argo_anywhere.sh#L4786) enumerates
"user-owned keys we preserve" as `verbose, argo_base_url, argo_url,
argo_stream_url, argo_embedding_url, concurrent_downloads,
connection_test_timeout, image_timeout, max_payload_size`. Three of
these (`argo_url`, `argo_stream_url`, `argo_embedding_url`) are
**v2-era**; they no longer exist in v3.x. Nine new v3.x keys are
absent from the comment (`anthropic_stream_mode`, `force_conversion`,
`resolve_overrides`, `max_log_history`, `enable_payload_control`,
`skip_url_validation`, `use_legacy_argo`, `native_openai_base_url`,
`native_anthropic_base_url`).

**Impact**: comment-only; the actual merge logic uses
`yaml.safe_load → yaml.safe_dump` and is schema-agnostic. The
comment misleads a future maintainer about the upstream schema.

**Recommendation**: replace the enumerated list with a reference to
the upstream `config.sample.yaml` link + the full v3.x table at §2.3
of this audit. A maintained list will go stale at every upstream
release; a link will not.

**Severity**: LOW — pure doc-debt.

### UP-05 — verify the `verbose: true` privacy concern is still valid at v3.0.x (LOW; verification task)

**Claim audited**: [`docs/SECURITY.md`](SECURITY.md) (and the P2 fix
in our v2.0 line) sets `verbose: false` by default because
"`argo-proxy verbose: true` logs every request body (prompts) and
response body to its stdout, captured in `~/.argo_anywhere.server.log`
on the compute node."

**Upstream reality**: at v3.0.1 the upstream README adds a new key
`max_log_history: 3` (description: "keep last N messages in verbose
request logs"). At v3.0.x the upstream README's default for
`verbose` is **still `true`** (see §2.3). The `verbose` semantics
appear unchanged.

**Recommendation**: keep our `verbose: false` default. This finding
is recorded for completeness — we are not changing anything, but the
audit confirms the assumption underlying the P2 fix is still
load-bearing.

**Severity**: LOW — confirmation, no action.

### UP-06 — `claudeopus47` model alias may interact with our default-model documentation (LOW)

**Claim audited**: [`AGENTS.md`](../AGENTS.md) and
[`docs/LIMITATIONS.md`](LIMITATIONS.md) reference `claude-opus-4-7`
(with the dash). v3.0.2 added `claudeopus47` (no dashes) as a
model alias.

**Impact**: Claude Code accepts both names; our docs are fine.

**Recommendation**: when next editing the limitation docs, mention
both names so users searching for either find the relevant section.

**Severity**: LOW — discoverability nit.

---

## 4. Watch-list — hot spots to re-check on every new `argo-proxy` release

The single most useful artifact this audit produces. On every
`argo-proxy` minor or patch release, an agent (or maintainer) should
re-verify the items in this table. The first time any row breaks,
file an entry in this audit's successor (rename to
`AUDIT_<date>_argo-proxy-upstream.md` and reuse this structure).

| # | Watch-target | Why we depend on it | How to verify |
|:--|:-------------|:--------------------|:--------------|
| **WATCH-01** | `argo-proxy serve` works as a bare command (no positional config arg required) under the upstream default config-search order | `mode_server` invokes `argo-proxy serve` with no args. If upstream made the config path required, we'd silently fail at startup. | Read the upstream `pyproject.toml` entry-points + scan `serve` CLI handler for `required=True` on a positional. Or run `argo-proxy serve --help` and confirm the synopsis still says `[config]` not `<config>`. |
| **WATCH-02** | `~/.config/argoproxy/config.yaml` remains in the config-search order | We write the file at exactly this path. If upstream demotes this location below the others (or removes it), we'd write a file argo-proxy ignores. | Read the upstream README "Configuration" section + grep upstream `src/` for `config_paths` / `CONFIG_SEARCH_PATHS`. |
| **WATCH-03** | `/health` endpoint returns HTTP 200 on a healthy proxy | Our monitor loop polls it. If upstream renames to `/healthz` (more idiomatic) or moves it to `/api/health`, our health checks would all flip to red. | Read the upstream README "Utility Endpoints" table + grep upstream `src/` for `@app.get("/health")`. |
| **WATCH-04** | `pip install argo-proxy` on a clean venv installs runtime deps without manual intervention | Issue [#117](https://github.com/Oaklight/argo-proxy/issues/117) (open since 2026-04-23) reports `httpx` import failure on a clean install. Our `mode_server` `pip install` is the EXACT path that triggers this. | After each upstream release, attempt a clean install in a throwaway venv: `python3.10 -m venv /tmp/v && /tmp/v/bin/pip install argo-proxy==<latest> && /tmp/v/bin/argo-proxy serve --help`. If it fails, hold the floor at the last-working version. |
| **WATCH-05** | `config_version: "3"` is still the accepted schema version | Bumped to `"3"` at v3.0.0. If upstream cuts a v4 schema, our writer would emit a stale version and either be ignored or migrated noisily. | Read `config.sample.yaml` at upstream master; if `config_version:` is no longer `'3'`, write a UP finding. |
| **WATCH-06** | The five keys we own (`config_version`, `user`, `host`, `port`, `verbose`) all stay accepted, with the same names + semantics | Our writer hardcodes all five. Renaming any one ("`username`" → "`user`" was an early-v3-beta migration) would break new configs. | Verify each key still appears with the same name in `config.sample.yaml` and in the README's "Configuration Options Reference" table. |
| **WATCH-07** | `argo_base_url` keeps "user-customizable; can override the upstream env" semantics | We `setdefault` it to the prod URL but preserve user customisation. If upstream makes it overridable only via `argo-proxy config env`, our writer's setdefault would clash with the new state machine. | Verify the README "Configuration" + "config env" sections still describe `argo_base_url` as a YAML override, not a derived value. |
| **WATCH-08** | `anthropic_stream_mode` default stays `force` (upstream-side fix for Claude Code 10-minute timeout) | If the default flips to `retry` or `passthrough`, Claude Code on long requests would hit the 10-minute Anthropic timeout we counted on `force` to bypass. Documented as the reason Phase C local-shim is REJECTED. | Verify the README's "Configuration Options Reference" still lists default as `force`. |
| **WATCH-09** | The bearer-token-is-the-ANL-username auth model stays unchanged | Every per-tool config writer hard-codes the ANL username as the API key. If upstream switched to "first call must POST `/auth/login`" or similar, all per-tool configs would 401. | Verify the README's "AI Coding Tools Integration" section still says "All tools use your ANL username as the API key." |
| **WATCH-10** | Python 3.10 stays the minimum supported | `mode_server`'s Python version check at [`argo_anywhere.sh:5117`](../argo_anywhere.sh#L5117) hardcodes "≥ 3.10". If upstream bumps to 3.11 or 3.12, our check still passes 3.10 binaries that will then fail to install argo-proxy. | Read `pyproject.toml`'s `requires_python` at upstream master and the PyPI JSON `requires_python` field. |
| **WATCH-11** | Dependencies don't introduce a new system-level requirement (libgomp, OpenSSL ≥ X.Y, ...) | Our venv path is `pip install` only. A C-extension dep that needs `apt install`'d system libraries would fail silently in the venv on a typical compute node. | Watch `pyproject.toml` `dependencies` for new entries on each release. Current set (2026-06-04): `aiohttp`, `llm-rosetta`, `pydantic`, `tiktoken`, `tqdm`, `Pillow` — all pure-pip-installable. |
| **WATCH-12** | The `serve` subcommand's startup user-validation does not become a hard fail | v3.0.4 fixed the "always shows 'network may be unavailable' warning" bug. If a future release escalates that warning to a hard exit, our monitor would see `argo-proxy serve` die at startup on every run. | Boot a healthy proxy after a new release and verify `serve` reaches "listening on port N" without a non-zero exit. |
| **WATCH-13** | `verbose: true` keeps logging prompts to stdout (the privacy concern we default-disable) | If upstream changes `verbose: true` to only log metadata, the privacy rationale for our default-`false` would weaken and we could re-evaluate. Conversely, if a new `log_to_file` config moves prompts to disk regardless of `verbose`, we'd need to disable that too. | Read the upstream "Configuration Options Reference" table; confirm `verbose` semantics. Search for any new `log_*` keys. |
| **WATCH-14** | `argo-proxy` continues to ship a stable PyPI package (not switched to git-only / VCS install) | Our `pip install argo-proxy` assumes PyPI. A switch to "install from git" would break `--force-reinstall` and any offline-bootstrap scenarios. | Confirm <https://pypi.org/pypi/argo-proxy/json> still returns the latest version. |
| **WATCH-15** | The `screen`-friendly behaviour of `argo-proxy serve` (no daemonisation; respects SIGTERM; writes to stdout/stderr) holds | If upstream daemonises itself or starts writing to a fixed log file, our screen-wrapper assumption (we capture stdout via `screen`'s logging) breaks. | Boot it under `screen -dmS test argo-proxy serve` after each release; confirm output reaches the screen log. |

### How to use this watch-list

After any new `argo-proxy` release (PyPI upload or GitHub release),
run through the 15 rows. The verification commands are explicit
enough that an agent can execute them with no prior context. Total
time on a clean machine: ~15 minutes. Findings (if any) get a new
**UP-NN** entry appended to §3 of this audit (or its dated
successor) with **severity** + **recommendation**.

---

## 5. Recommended follow-ups

In rough priority order:

1. **UP-01** (MEDIUM) — revise [`docs/LIMITATIONS.md`](LIMITATIONS.md)
   "Upstream stack" section to reflect v3.0.3 + v3.0.2 fixes; update
   [`notes/agent_feedback.md`](../notes/agent_feedback.md) entry 6
   with the upstream-fix resolution.
2. **UP-02** (MEDIUM) — add the soft version-floor check to
   `ensure_argoproxy_installed`. Bumps the recommended floor to
   `>=3.0.3` so users with stale venvs see a clue.
3. **UP-04** (LOW) — replace the stale enumerated comment block at
   [`argo_anywhere.sh:4786-4790`](../argo_anywhere.sh#L4786) with a
   link to the upstream `config.sample.yaml`.
4. **UP-03** (LOW) — make the `anthropic_stream_mode: force` default
   explicit in our config writer.
5. **UP-06** (LOW) — mention both `claude-opus-4-7` and `claudeopus47`
   names in the limitations docs.

These should land as part of a v2.2.1 or v2.3 doc-and-defensive
cycle. None requires Phase-5-style multi-tool changes. They are
straightforward edits plus one small script addition.

The **watch-list (§4) itself is the more valuable artifact** — it
ensures the next time `Oaklight/argo-proxy` cuts a release, the
verification work is reduced from "audit the whole repo" to "walk
15 rows."

---

## 6. Methodology + reproducibility

**Sources consulted** (all 2026-06-04):

- GitHub Releases page <https://github.com/Oaklight/argo-proxy/releases>
  — v3.0.0 through v3.0.4 release notes.
- PyPI JSON <https://pypi.org/pypi/argo-proxy/json> — version list,
  upload dates, `requires_python`, `requires_dist`.
- `master` branch README, `config.sample.yaml`, recent commits via
  GitHub API + raw-content URLs.
- Open issues filtered for the surface we depend on.
- Our script: [`argo_anywhere.sh`](../argo_anywhere.sh) at commit
  `9769e70` (same runtime contract as v2.2.0 tag `737563d`).
- [`AUDIT_2026-05-12.md`](AUDIT_2026-05-12.md) (43 findings; this
  audit relies on its M9 finding-resolution for the YAML-merge
  preservation contract).
- [`AUDIT_2026-05-18_argo-shim-comparison.md`](AUDIT_2026-05-18_argo-shim-comparison.md)
  (the comparative audit that established `anthropic_stream_mode:
  force` is the upstream solution to the streaming-timeout problem
  we'd otherwise solve with a local shim).
- [`docs/LIMITATIONS.md`](LIMITATIONS.md) "Upstream stack" section.
- [`notes/agent_feedback.md`](../notes/agent_feedback.md) entries 4
  + 6 (opus-4-7 diagnosis).

**Not consulted** (deliberate scope limit):

- `argo-proxy` source code inside `src/` — schemas / endpoints /
  defaults were verified against documentation rather than source.
  If a doc-vs-code drift exists upstream, this audit would not
  catch it. Worth a follow-up if a watch-list row fails despite
  documentation appearing unchanged.
- `llm-rosetta` (the transitive dependency that v3.x uses for
  cross-format translation). We do not call into it directly; any
  breakage would surface as an `argo-proxy` test failure first.
- Claude Code / OpenCode / aider / cursor release notes — out of
  scope; those are tracked separately in the per-tool integration
  docs.

**Reproduction**: an agent should be able to regenerate this audit in
~30 minutes by re-running the same `WebFetch` queries against the
same URLs and following the **§1 (how we consume) → §2 (upstream
state) → §3 (findings) → §4 (watch-list)** structure. The watch-list
is the only section a new release strictly requires re-running; §1 +
§3 are deltas against this baseline.

---

*Audit closed 2026-06-04. Re-run after every `argo-proxy` minor or
patch release; rename the successor file to
`AUDIT_<date>_argo-proxy-upstream.md` and cross-link both.*
