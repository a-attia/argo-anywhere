# Upstream audit re-walk: `Oaklight/argo-proxy` v3.2.1-v3.2.3 (+ v3.3.0a\*) and `Oaklight/llm-rosetta` v0.7.x-v0.8.2 vs `argo-anywhere` v3.2.1

*Created 2026-08-10 by Ahmed Attia (with substantial AI assistance from
Claude per [`CONTRIBUTORS.md`](../CONTRIBUTORS.md)). Scope: delta against
[`AUDIT_2026-07-08_argo-proxy-upstream.md`](AUDIT_2026-07-08_argo-proxy-upstream.md)
(the v3.1.2 + v3.2.0a0 baseline). Covers `argo-proxy` **v3.2.1** (2026-07-10),
**v3.2.2** (2026-07-12), **v3.2.3** (2026-07-17, current stable) plus the
**v3.3.0a0/a1** pre-releases (2026-07-18), and `llm-rosetta` **v0.7.0**
through **v0.8.2** (2026-07-10 .. 2026-08-09). `argo-anywhere` baseline:
**v3.2.1** (PyPI 2026-07-16), engine `SCRIPT_VERSION=2.3.0`. This re-walk
fires per the parent audit's stated trigger for **WATCH-17** ("the first
stable `argo-proxy v3.2.0` release, OR any `llm-rosetta 0.7.x` stable
release") — both conditions fired, and the parent audit was 33 days stale
at the time of this walk.*

> **Methodology note.** Unlike the previous re-walks, which read source and
> release notes, this audit **built live virtualenvs and executed the
> software** (`pip install` into clean venvs; ran the engine's own probe
> commands; loaded configs through argo-proxy's real loader; read the
> installed shim YAML). Every claim below marked "verified" was reproduced
> on this machine. Claims that could NOT be executed (anything requiring
> the ANL gateway) are marked explicitly in [§6](#6-methodology--reproducibility).

---

## Table of contents

- [Executive summary](#executive-summary)
- [1. What changed upstream since v3.1.2 / v0.6.12](#1-what-changed-upstream-since-v312--v0612)
- [2. UP-11: argo-proxy v3.3.0a1 is broken on PyPI](#2-up-11-argo-proxy-v330a1-is-broken-on-pypi-critical)
- [3. UP-12: our install probe cannot detect a broken install](#3-up-12-our-install-probe-cannot-detect-a-broken-install-high)
- [4. Re-walk of the watch-list](#4-re-walk-of-the-watch-list)
- [5. Finding dispositions](#5-finding-dispositions)
- [6. Methodology + reproducibility](#6-methodology--reproducibility)

---

## Executive summary

**The stable path is safe; the alpha path is landmined; our probe cannot
tell the difference.**

Three headline results:

1. **Everything `argo-anywhere` depends on is intact on argo-proxy
   v3.2.3.** All five config keys we own, the `/health` contract, the
   unknown-key preservation our PyYAML merge relies on, the Python floor,
   and the CLI surface are unchanged. Verified by execution, not
   inspection.

2. **`argo-proxy 3.3.0a1` cannot start at all** (new finding **UP-11**).
   It imports a symbol that `llm-rosetta 0.8.2` removed, and its
   dependency pin has no upper bound, so a plain `pip install --pre`
   resolves a combination that dies at import time. Unreported upstream.

3. **Our install validation would not catch it** (new finding **UP-12**).
   Both probes in `ensure_argoproxy_installed` — `argo-proxy --version`
   and `argo-proxy serve --help` — **pass** against the broken install,
   because both are argparse-only paths that never import the server
   module. The failure would first appear when `mode_server` launches
   inside `screen`, where the traceback is easy to miss and the user sees
   only "tunnel up, never goes healthy."

We are **not exposed today**: the engine never passes `--pre` (verified:
zero occurrences of the flag), and `_pypi_latest_version` reads PyPI's
`.info.version`, which returns the latest *stable* (`3.2.3`), never a
pre-release. UP-11 is therefore a **latent** hazard rather than a live
outage. But UP-12 is a genuine weakness independent of UP-11: the same
blind spot will recur on any import-time breakage, and upstream's
unbounded transitive pin makes that a recurring class of event, not a
one-off (see **WATCH-18**).

**Also resolved this walk:** **WATCH-17 closes green** — the opus
thinking-type fix survived the 0.7.x/0.8.x `ConversionPipeline` migration
intact, verified by reading the installed shim. That makes
[`docs/LIMITATIONS.md`](LIMITATIONS.md)'s opus-4-7 section **actively
wrong**: it still tells users to avoid a model that now works
(finding **UP-13**).

**Correction to the historical record:** `argo-proxy 3.2.0` **stable was
never released**. PyPI goes `3.2.0a0` (alpha, 2026-06-27) directly to
`3.2.1` (2026-07-10). Several of our docs refer to a v3.2.0 that does not
exist; the parent audit's WATCH-17 trigger phrase ("the first stable
`argo-proxy v3.2.0` release") should be read as "the first stable v3.2.x
release," which was v3.2.1.

### New findings at a glance

| ID | Severity | Finding | Action |
|:---|:---|:---|:---|
| **UP-11** | **CRITICAL (upstream)** | `argo-proxy 3.3.0a1` + `llm-rosetta 0.8.2` = `ImportError` at startup; unbounded pin; unreported upstream | Do not adopt; consider filing the one-line fix |
| **UP-12** | **HIGH (ours)** | `ensure_argoproxy_installed` probes pass on a non-functional install | Add an import-level probe |
| **UP-13** | **MEDIUM (ours, user-visible)** | `LIMITATIONS.md` documents opus-4-7 as broken; it was fixed at the shim layer | Rewrite section as RESOLVED |
| **UP-02** | MEDIUM (carried) | Version floor still unimplemented | Implement at `>=3.2.3` |
| **UP-14** | LOW (ours) | Docs cite a nonexistent "v3.2.0 stable" | Correct references |
| **UP-04** | LOW (carried) | Stale user-preserved-keys comment | Refresh (now also missing 3 keys) |

---

## 1. What changed upstream since v3.1.2 / v0.6.12

### 1.1 Release timeline (new entries)

| Package | Version | Date | Substance | Relevant to us? |
|:---|:---|:---|:---|:---|
| argo-proxy | **v3.2.1** | 2026-07-10 | First **stable** `ConversionPipeline` adoption. `default_chat_model` / `default_embed_model` become configurable. Floor `llm-rosetta>=0.7.0`. | Two new config keys (we don't own them; merge preserves) |
| argo-proxy | **v3.2.2** | 2026-07-12 | argo-proxy identified in User-Agent (#145); request-level security middleware blocking command-injection patterns (#139). | Middleware inspects path/query; our plain `GET /health` is unaffected |
| argo-proxy | **v3.2.3** | 2026-07-17 | `models.py` split into `models/{constants,upstream,registry}.py`. Anthropic detection broadened to `sonnet*/opus*/haiku*/fable*`. Adds Opus 4.8, Sonnet 5, GPT-5.4-mini to defaults. Floor `llm-rosetta>=0.7.1`. | **Current stable; recommended floor** |
| argo-proxy | **v3.3.0a0** | 2026-07-18 | **BREAKING (self-declared): `aiohttp` dropped.** HTTP server + transport move into llm-rosetta's gateway. ~2400 lines removed; new `bridge.py` / `auth.py` / `transport.py`. | Look-ahead; **see UP-11** |
| argo-proxy | **v3.3.0a1** | 2026-07-18 | Adds `--dev` passthrough mode; `dev_proxy.py`. | **BROKEN — see UP-11** |
| llm-rosetta | v0.7.0 .. v0.7.3 | 2026-07-10 .. 07-24 | `ConversionPipeline` stable line. | Carried transitively |
| llm-rosetta | **v0.8.0/0.8.1/0.8.2** | 2026-08-06 .. **08-09** | Gateway auth refactor: `api_key_label_var` → `api_key_context_var` + new `KeyContext`. | **Trigger for UP-11** |

`llm-rosetta 0.8.2` shipped **one day before this audit** — a good
illustration of why WATCH-18 (below) matters.

### 1.2 Config schema delta (v3.1.2 → v3.2.3)

**Only two keys added**, neither owned by us:

```
default_chat_model    # new in v3.2.1
default_embed_model   # new in v3.2.1
```

The five keys `argo-anywhere` owns are unchanged in name, type, and
semantics. Verified by introspecting the installed dataclass:

```
config_version   present=True  default=''
user             present=True  default=''
host             present=True  default='0.0.0.0'
port             present=True  default=44497
verbose          present=True  default=True
```

`config_version` is still written as `"3"`; no schema-version bump, so
our hardcoded `data['config_version'] = "3"` remains correct.

**Unknown-key preservation verified end-to-end.** A config containing
`some_unknown_downstream_key: preserve-me` was loaded by argo-proxy
v3.2.3 and the key **survived on disk untouched** — the contract
`write_argoproxy_config`'s PyYAML merge depends on.

**Our writer's exact output round-trips.** The literal 6-key document our
writer emits was loaded by argo-proxy v3.2.3's real `load_config`:

```
config_version   '3'
user             'jdoe'
host             '127.0.0.1'
port             44497
verbose          False
argo_base_url    'https://apps.inside.anl.gov/argoapi'
```

`argo_base_url` is still accepted (property-backed by `_argo_base_url`),
and our default value matches upstream's own `_argo_prod_base`.

### 1.3 Runtime-dependency delta

| Version | Runtime deps |
|:---|:---|
| v3.1.2 | `aiohttp`, `llm-rosetta<0.7.0,>=0.6.8`, `pydantic`, `tiktoken`, `tqdm`, `Pillow` |
| **v3.2.3** | `aiohttp`, **`llm-rosetta>=0.7.1`** (no upper bound), `pydantic`, `tiktoken`, `tqdm`, `Pillow` |
| v3.3.0a1 | **`llm-rosetta[gateway]>=0.7.1`**, `pydantic`, `tiktoken`, `tqdm` — `aiohttp` + `Pillow` **gone** |

The v3.3.x direction is genuinely *better* for HPC (fewer compiled
extensions to build on a compute node: `pydantic_core`, `regex`,
`tiktoken` only, vs. also `aiohttp`, `PIL`, `yarl`, `multidict`,
`frozenlist`, `propcache` on v3.2.3). The `[gateway]` extra is empty —
the HTTP server is vendored inside llm-rosetta. This is worth adopting
**once UP-11 is fixed upstream**.

**A latent risk on stable, not just alpha:** v3.2.3 *also* pins
`llm-rosetta>=0.7.1` unbounded, so today it resolves 0.8.2. I verified
v3.2.3 **works** with 0.8.2 — but that is luck, not contract. See
WATCH-18.

### 1.4 HTTP routes

`/health` unchanged in v3.2.3 (`argoproxy/app.py:210-212`):

```python
async def health_check(request: web.Request):
    log_info("/health", context="app")
    return web.json_response({"status": "healthy"}, status=200)
```

Registered at `app.py:338` and `app.py:367`. In v3.3.0a1 the handler moves
to `app.py:457-458` (registered `:600`) and is explicitly allowlisted from
the new auth hook (`auth.py:27`: `_PUBLIC_PATHS = frozenset({"/health",
"/health/live", "/health/ready", "/version"})`).

**`/version` exists on the same port** — relevant to a UI improvement (see
`notes/impl_upstream_hardening.md` §U1): it lets us report the node's
argo-proxy version through the tunnel we already have open, with **no new
SSH connection** and therefore no Duo/CSPO cost.

---

## 2. UP-11: argo-proxy v3.3.0a1 is broken on PyPI (CRITICAL)

**Severity**: CRITICAL upstream / **latent** for us
**Status**: unfixed upstream as of 2026-08-10; no matching upstream issue found

### The defect

`argo-proxy 3.3.0a1` declares `llm-rosetta[gateway]>=0.7.1` with **no upper
bound**. `llm-rosetta 0.8.2` (2026-08-09) removed `api_key_label_var`,
renaming it to `api_key_context_var` alongside a new `KeyContext`. But
`argoproxy/auth.py:16` still imports the old name at **module scope**.

Reproduced from a clean venv on this machine:

```console
$ python3 -m venv apv2 && ./apv2/bin/pip install --pre argo-proxy
argo-proxy         3.3.0a1
llm-rosetta        0.8.2

$ ./apv2/bin/argo-proxy serve
  File ".../argoproxy/auth.py", line 16, in <module>
    from llm_rosetta.gateway.auth import api_key_label_var
ImportError: cannot import name 'api_key_label_var' from 'llm_rosetta.gateway.auth'
```

Boundary: works with `llm-rosetta <= 0.8.0`, breaks at `0.8.2`.

### Why we are not exposed *today*

Two independent guards, both verified:

1. **We never pass `--pre`.** `grep -n '\-\-pre\b' argo-anywhere.sh`
   returns nothing. Our install is `pip install --upgrade argo-proxy`
   (`argo-anywhere.sh:7090`, `:8937`, `:8993`), which pip resolves to the
   latest **stable**.
2. **`_pypi_latest_version` is stable-only.** It reads
   `.info.version` from the PyPI JSON API, which is by definition the
   latest non-pre-release. Confirmed live: returns `3.2.3`, not
   `3.3.0a1`.

So the `update` path and the bootstrap path both stay on stable. UP-11 is
recorded because (a) a user *can* reach it manually via
`argo-proxy update install --pre` or a hand-rolled pip command, and (b) it
is the concrete proof case for UP-12.

### Recommended posture

- **Do not adopt v3.3.x** until upstream repins or fixes the import.
- Consider filing the one-line upstream fix (`api_key_label_var` →
  `api_key_context_var`). It appears unreported.
- Do **not** add a version *ceiling* to our install command. A ceiling
  would have to be revised on every upstream release and would silently
  hold users back; the floor (UP-02) plus the import probe (UP-12) covers
  the actual risk without that maintenance burden.

---

## 3. UP-12: our install probe cannot detect a broken install (HIGH)

**Severity**: HIGH (ours)
**Location**: `ensure_argoproxy_installed`, `argo-anywhere.sh:7079-7095`

### The gap

The engine validates an argo-proxy install with two probes:

```bash
if ! "${venv}/bin/argo-proxy" --version >/dev/null 2>&1; then
  need_install=1
elif ! "${venv}/bin/argo-proxy" serve --help >/dev/null 2>&1; then
  warn "argo-proxy installed but 'serve --help' fails (likely too old); upgrading."
  need_install=1
fi
```

Both are **argparse-only** paths. Neither imports the server module. Run
against the UP-11 install:

| Probe | Broken install (3.3.0a1) |
|:---|:---|
| `argo-proxy --version` | ✅ **passes** |
| `argo-proxy serve --help` | ✅ **passes** |
| `argo-proxy serve` (real) | ❌ `ImportError` |

The post-install assertion at `:7091` uses `serve --help` too, so it also
passes. The engine then reports `ok "argo-proxy: ..."` and proceeds to
`mode_server`, which launches inside `screen` — the traceback lands in a
detached session's scrollback. The user's visible symptom is a tunnel that
comes up and never goes healthy, with the health monitor's generic "most
likely argo-proxy on <node> is down" message.

### Verified fix

An import-level probe cleanly separates the two, and is stable across the
versions we care about:

| argo-proxy | `python -c "import argoproxy.app"` |
|:---|:---|
| 3.1.2 | OK |
| 3.2.1 | OK |
| 3.2.3 | OK |
| **3.3.0a1** | **fails (detected)** |

Cost: **0.31 s** steady-state (measured 0.30/0.31/0.31), once per server
bootstrap. The first import after a fresh install costs ~2.9 s while
CPython writes `.pyc` files, but that run has just done a `pip install`, so
it is invisible. Verified side-effect free: with a clean `HOME` the import
writes no `~/.config` and does not bind the proxy port.

`argoproxy.app` is the right module to probe: it is where the aiohttp app
and `/health` live in 3.x, and it is the module `serve` ultimately imports.
Should upstream relocate it in v3.3.x, the probe fails closed (reports a
problem) rather than open — the safe direction, and exactly what we want
for an unvetted new major.

---

## 4. Re-walk of the watch-list

Rows unchanged from the 2026-07-08 walk are omitted; see that document for
the full 17-row list.

| Row | Claim | Verdict | Evidence |
|:---|:---|:---|:---|
| WATCH-03 | `/health` returns HTTP 200 | **green** | `app.py:210-212` (3.2.3); allowlisted in 3.3.0a1 `auth.py:27` |
| WATCH-04 | clean `pip install` works | **green (stable)** / **RED (alpha)** | Clean-venv install of 3.2.3 succeeded; `--pre` install is UP-11 |
| WATCH-06 | five owned keys accepted | **green** | Dataclass introspection + live `load_config` round-trip |
| WATCH-08 | `anthropic_stream_mode` default `force` | **green** | `_anthropic_stream_mode: str = "force"` in the installed model |
| WATCH-10 | Python 3.10+ minimum | **green** | `requires-python = ">=3.10"` through 3.3.0a1 |
| WATCH-11 | no new system-level dependency | **green (improving)** | Both 3.2.3 and 3.3.0a1 install with zero system packages; 3.3.x *reduces* native surface |
| WATCH-14 | PyPI package still ships | **green** | `.info.version` → 3.2.3 |
| WATCH-15 | screen-friendly (no daemonisation) | **green** | `run()` still blocks in foreground |
| **WATCH-16** | `socket:` stays opt-in + empty by default | **green — KEEP WATCHING** | `socket = ''` in the installed 3.2.3 dataclass; not promoted in 3.3.0a1 README |
| **WATCH-17** | 0.7.x/0.8.x migration preserves `model_overrides` | **green — CLOSE** | See below |

### WATCH-17 → CLOSED (mechanism survived)

Read directly from the installed `llm-rosetta 0.8.2` shim
(`shims/providers/argo/anthropic/provider.yaml`):

```yaml
reasoning:
  thinking_type: enabled
  model_overrides:
    claudehaiku45: {thinking_type: enabled, budget_tokens_default_ratio: 0.8}
    claudesonnet4: {thinking_type: enabled, budget_tokens_default_ratio: 0.8}
    claudeopus47:  {thinking_type: adaptive}
    claudeopus48:  {thinking_type: adaptive}
```

Both opus generations map to `adaptive` — the exact fix for the HTTP-200
empty-response failure we documented at v2.2.0. The key is nested under
`reasoning:`, **not** at document top level; a top-level lookup returns
empty and is a red herring (this tripped up the first pass of this audit).

### New watch rows

| Row | Claim to re-check | Why it matters | Trigger |
|:---|:---|:---|:---|
| **WATCH-18** | argo-proxy's `llm-rosetta` pin acquires an upper bound, or stable argo-proxy breaks against the newest llm-rosetta | Unbounded transitive pins are how UP-11 happened. Stable v3.2.3 currently works with 0.8.2 **by luck**; the same rename could have hit stable. | **Every** `llm-rosetta` minor release |
| **WATCH-19** | v3.3.x becomes stable and fixes the `api_key_label_var` import | v3.3.x is a real HPC improvement (drops `aiohttp` + `Pillow`); worth adopting once it starts | First stable `argo-proxy 3.3.0` |

---

## 5. Finding dispositions

### UP-02 (version floor) — STRENGTHEN to `>=3.2.3`, still unimplemented

Carried since the 2026-06-04 audit; recommended floor has moved
`>=3.0.3` → `>=3.1.0` → `>=3.1.2` → now **`>=3.2.3`**.

The helper already exists and is correct. `_version_ge`
(`argo-anywhere.sh:8737`) is used in four places
(`:8913`, `:8923`, `:9124`, `:9251`) but **never** in
`ensure_argoproxy_installed`. Verified behaviour, including the cases a
naive string compare gets wrong:

```
_version_ge 3.2.3 3.2.3    -> TRUE
_version_ge 3.2.3 3.1.2    -> TRUE
_version_ge 3.1.2 3.2.3    -> false
_version_ge 3.2.3 3.2.10   -> false   (numeric, not lexical)
_version_ge 3.3.0a1 3.2.3  -> TRUE    (alpha sorts above its base)
```

Should be a **soft** floor (warn + offer upgrade), not a hard `die` — a
user on a working older version should not be locked out of their own
tunnel by our opinion about versions.

**Caveat on the value, raised while planning the fix.** `>=3.2.3` is
"current stable," but the *functional* justification for a floor at all is
the opus thinking-type fix, which is satisfied by `llm-rosetta >= 0.6.10`
— carried by **`argo-proxy >= 3.1.0`**. A `3.2.3` floor therefore warns a
population of users for whom nothing is broken, and a warning that can be
safely ignored teaches users to ignore warnings. The implementation plan
(`notes/impl_upstream_hardening.md` §8 Q2) recommends **`3.1.0`** on those
grounds and leaves the final value to the maintainer. This audit's
`>=3.2.3` should be read as "the version we recommend people run," not
necessarily "the version below which we should nag."

### UP-13 (NEW) — `LIMITATIONS.md` opus-4-7 section is actively wrong

`docs/LIMITATIONS.md:346-441` documents the opus-4-7 HTTP-200
empty-response failure as a live limitation, including:

```
**Verified workaround**: run Claude Code with any non-opus-4-7 [model]
claude --model claude-opus-4-7        # fails reliably
```

Per WATCH-17 above, this is fixed at the shim layer for **both** opus-4-7
and opus-4-8, and has been since `llm-rosetta 0.6.10`. We are telling users
to avoid a model that works. This is the most user-visible defect in this
audit and should be corrected before any code work.

Rewrite as a RESOLVED/historical section (keep the provenance — the
diagnosis is good documentation of how the stack fails — but re-head it
so nobody acts on the workaround).

### UP-14 (NEW) — docs cite a nonexistent "argo-proxy v3.2.0 stable"

PyPI has `3.2.0a0` then `3.2.1`; there is no 3.2.0 stable. Affected: the
WATCH-17 trigger phrasing in the 2026-07-08 audit, and any AGENTS.md /
PLAN.md text implying a v3.2.0 release. Low severity, but it makes the
watch-list trigger ambiguous ("has it fired?").

### UP-04 (stale user-preserved-keys comment) — MORE material again

The comment enumerating preserved keys (`write_argoproxy_config`, and the
error text at `argo-anywhere.sh:6958`) lists `argo_embedding_url`,
`concurrent_downloads`, `max_payload_size`. Now also missing: `socket`
(v3.1.2), `default_chat_model`, `default_embed_model` (v3.2.1). The
standing recommendation holds: replace the enumeration with "we own five
keys; everything else is preserved" + a link to upstream's
`config.sample.yaml`, so the comment stops aging.

### UP-07 (legacy key silent-ignore) — UNCHANGED

`use_legacy_argo` / `force_conversion` still absent from our engine (zero
occurrences) and still silently dropped in-memory by upstream's
`from_dict`. Unchanged disposition; low priority.

### Unchanged / no action

- **PyYAML self-heal**: independently re-confirmed this walk. A clean
  argo-proxy 3.2.3 venv has **no `yaml` module** — I hit
  `ModuleNotFoundError: No module named 'yaml'` while inspecting the shim.
  The 2026-07-15 field report was right and
  `ensure_argoproxy_installed`'s probe-and-install is correctly placed.
- **`--version` parsing**: outputs `argo-proxy 3.2.3` on line 1; our
  `_extract_version` + `| head -n1` handles it. Upstream appends
  dependency-update lines when llm-rosetta is outdated, which is exactly
  why `head -n1` is load-bearing — do not remove it.
- **CLI surface**: `serve` / `config` / `logs` / `update` / `models`
  unchanged. Note `serve`'s config argument is **positional**
  (`argo-proxy serve <config.yaml>`), not `--config`.

---

## 6. Methodology + reproducibility

**What was executed** (macOS 26, Python 3.13, clean venvs under `/tmp`):

```console
# stable
python3 -m venv apv && ./apv/bin/pip install argo-proxy      # -> 3.2.3 + llm-rosetta 0.8.2
./apv/bin/argo-proxy --version
./apv/bin/argo-proxy serve --help
./apv/bin/python -c "import argoproxy.app"
./apv/bin/python -c "from argoproxy.config.io import load_config; ..."   # round-trip + unknown-key

# alpha (UP-11)
python3 -m venv apv2 && ./apv2/bin/pip install --pre argo-proxy   # -> 3.3.0a1 + llm-rosetta 0.8.2
./apv2/bin/argo-proxy serve                                       # ImportError

# probe stability across versions
for V in 3.1.2 3.2.1 3.2.3; do pip install "argo-proxy==$V"; python -c "import argoproxy.app"; done

# shim inspection
./apv/bin/python -c "...yaml.safe_load(.../argo/anthropic/provider.yaml)['reasoning']['model_overrides']"
```

All temporary venvs were removed after the audit.

**NOT verified — stated explicitly:**

- **No live ANL gateway traffic.** `argo-proxy serve` cannot complete
  startup off-network (it probes `apps-dev.inside.anl.gov/argoapi/v1/models`
  and prompts interactively on failure). `/health` returning 200 is
  therefore **source-verified, not end-to-end verified** this walk. The
  route and handler are unchanged from versions we have live-tested
  before, so confidence is high — but it is not a live observation.
- **Not tested on Linux/HPC or Python 3.10.** All venvs were
  macOS/Python 3.13. The claim that v3.3.x's smaller native-extension
  footprint helps on a compute node is inferred from dependency metadata,
  not measured on a node.
- **`socket:` mode not exercised end-to-end**; WATCH-16 rests on the
  default value, not on behaviour.
- **v3.2.2's security middleware not fuzzed.** Our `/health` GET is plain
  and unaffected, but the middleware's full pattern set was not surveyed.

**Next re-walk trigger**: any `llm-rosetta` minor release (WATCH-18), OR
the first stable `argo-proxy 3.3.0` (WATCH-19), OR any argo-proxy release
that changes the `socket` default (WATCH-16).
