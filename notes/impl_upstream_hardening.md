# Implementation plan: upstream hardening (install probe, version floor, limitation docs) + argo-proxy version in the UI

**Status**: DRAFT — not executed. Awaiting the user's go-signal.
**Trigger**: 2026-08-10 deep audit of the engine against current upstream
(`docs/AUDIT_2026-08-10_argo-proxy-upstream.md`). The parent upstream audit
was 33 days stale; re-walking it surfaced one critical upstream defect
(UP-11), one real gap in our own install validation (UP-12), and one
actively-wrong user-facing doc (UP-13).
**Target release**: **v3.2.2** (patch). Nothing here is a feature; it is
correctness + honesty work. No engine `SCRIPT_VERSION` bump is required for
Phase 1/2 (see §5 Q3 — open question).
**Baseline**: `argo-anywhere` v3.2.1, engine `SCRIPT_VERSION=2.3.0`,
`main` carrying uncommitted D-033 + web-UI work from the 2026-08-09/10
sessions.
**Scope decision**: engine + docs first (Phases 1-2), UI last (Phase 3).
The UI item depends on nothing in Phases 1-2 but is lower value and
touches a surface we have just stabilised, so it goes last.

---

## Table of contents

- [1. Why this work, in one paragraph](#1-why-this-work-in-one-paragraph)
- [2. Findings this plan discharges](#2-findings-this-plan-discharges)
- [3. Phase 1 — engine correctness](#3-phase-1--engine-correctness)
- [4. Phase 2 — docs + watch hygiene](#4-phase-2--docs--watch-hygiene)
- [5. Phase 3 — UI: surface the argo-proxy version](#5-phase-3--ui-surface-the-argo-proxy-version)
- [6. Testing strategy](#6-testing-strategy)
- [7. Risk register](#7-risk-register)
- [8. Open questions](#8-open-questions)
- [9. Execution order + commit plan](#9-execution-order--commit-plan)

---

## 1. Why this work, in one paragraph

`argo-anywhere` installs argo-proxy on a compute node and then decides
"is it working?" using two probes that only exercise `argparse`. A real
upstream release (`argo-proxy 3.3.0a1`) exists **right now** that passes
both probes and cannot start, because it imports a symbol
`llm-rosetta 0.8.2` removed. We are not exposed today — we never pass
`--pre` and our PyPI query is stable-only — but the blind spot is real and
will recur, because upstream pins `llm-rosetta` with no upper bound.
Separately, our own `LIMITATIONS.md` still tells users that
`claude-opus-4-7` is broken, months after upstream fixed it, which means
we are actively steering people away from a working model. This plan
closes the probe gap, implements the long-deferred version floor, corrects
the docs, and (optionally) surfaces the node's argo-proxy version in the
web UI so the next stack break is diagnosable at a glance.

---

## 2. Findings this plan discharges

| ID | Severity | Phase | One-line |
|:---|:---|:---|:---|
| **UP-12** | HIGH | 1 | Install probe passes on a non-functional argo-proxy |
| **UP-02** | MEDIUM | 1 | Soft version floor still unimplemented (helper exists, unused) |
| **UP-13** | MEDIUM | 1 | `LIMITATIONS.md` documents a fixed limitation as live |
| **UP-14** | LOW | 2 | Docs cite a nonexistent argo-proxy v3.2.0 stable |
| **UP-04** | LOW | 2 | Stale user-preserved-keys comment (now missing 3 more keys) |
| **WATCH-17** | — | 2 | Close green (opus fix survived the pipeline migration) |
| **WATCH-18/19** | — | 2 | New rows (unbounded transitive pin; v3.3.x adoption) |
| **UP-11** | CRITICAL (upstream) | 2 | Record; optionally file upstream. **No code change** — see §7 R3 |
| **U1** | LOW | 3 | UI never shows the argo-proxy version |
| **U2** | COSMETIC | 3 | Health text renders raw JSON |

Full evidence for each: `docs/AUDIT_2026-08-10_argo-proxy-upstream.md`.

---

## 3. Phase 1 — engine correctness

### 3.1 UP-12: add an import-level probe to `ensure_argoproxy_installed`

**Site**: `argo-anywhere.sh:7079-7095`.

**Current** (both probes argparse-only):

```bash
local need_install=0
if ! "${venv}/bin/argo-proxy" --version >/dev/null 2>&1; then
  need_install=1
elif ! "${venv}/bin/argo-proxy" serve --help >/dev/null 2>&1; then
  warn "argo-proxy installed but 'serve --help' fails (likely too old); upgrading."
  need_install=1
fi
```

**Proposed** — add a third probe that actually imports the server module:

```bash
local need_install=0
if ! "${venv}/bin/argo-proxy" --version >/dev/null 2>&1; then
  need_install=1
elif ! "${venv}/bin/argo-proxy" serve --help >/dev/null 2>&1; then
  warn "argo-proxy installed but 'serve --help' fails (likely too old); upgrading."
  need_install=1
elif ! "${venv}/bin/python" -c 'import argoproxy.app' >/dev/null 2>&1; then
  # UP-12 (2026-08-10). BOTH probes above are argparse-only paths that
  # never import the server module, so a dependency-resolution break
  # passes them and only fails when mode_server actually launches --
  # inside `screen`, where the traceback is easy to miss and the user
  # just sees a tunnel that never goes healthy. Proof case: argo-proxy
  # 3.3.0a1 imports `api_key_label_var`, which llm-rosetta 0.8.2
  # removed; `--version` and `serve --help` both PASS on that install.
  # Costs ~0.31s steady-state. `argoproxy.app` verified importable
  # on 3.1.2 / 3.2.1 / 3.2.3 and failing on 3.3.0a1.
  warn "argo-proxy is installed but its server module fails to import."
  warn "  Usually a broken dependency resolution (upstream pins llm-rosetta"
  warn "  without an upper bound). Reinstalling to try to repair it."
  need_install=1
fi
```

**And the post-install assertion** (`:7091`) must gain the same check —
today it re-runs `serve --help`, which would pass on a still-broken
install and let us report success:

```bash
"${venv}/bin/argo-proxy" serve --help >/dev/null 2>&1 \
  || die "argo-proxy 'serve' subcommand still missing after install. Inspect ${venv}/bin/argo-proxy."
if ! "${venv}/bin/python" -c 'import argoproxy.app' >/dev/null 2>&1; then
  err "argo-proxy installed but its server module still fails to import:"
  "${venv}/bin/python" -c 'import argoproxy.app' 2>&1 | tail -5 | while IFS= read -r _l; do err "    ${_l}"; done
  err ""
  err "  This is an upstream dependency break, not a problem with your setup."
  err "  Workaround: pin a known-good pair inside the venv, e.g."
  err "    ${venv}/bin/pip install 'argo-proxy==3.2.3' 'llm-rosetta<0.9'"
  die "argo-proxy cannot start; refusing to launch a proxy that will fail."
fi
```

**Design notes.**

- **Fail closed, deliberately.** If upstream relocates `argoproxy.app` in
  a future major, this probe reports a problem rather than silently
  accepting an unvetted layout. For a component whose failure mode is "the
  tunnel silently never works," that is the right bias. Recorded here so a
  future reader does not "fix" it into a soft warn.
- **Echo the real traceback.** The whole point is that the error is
  currently invisible; printing the last 5 lines turns a mystery into a
  diagnosis.
- **Suggest a pin, do not apply one.** See §7 R3.

### 3.2 UP-02: soft version floor

**Site**: same function, immediately after the probe block.

```bash
# UP-02 (audit 2026-06-04, strengthened 2026-08-10): soft floor.
# SOFT by design -- warn + offer, never die. A user on a working older
# argo-proxy must not be locked out of their own tunnel by our opinion
# about versions.
#
# VALUE PENDING -- see §8 Q2. `3.1.0` is the first release whose pinned
# llm-rosetta (>=0.6.10) carries the opus-4-7/4-8 thinking-type fix, so
# it is the lowest version at which nothing is actually broken. `3.2.3`
# is merely current-stable. Warning users whose setup works fine trains
# them to ignore warnings, so this plan RECOMMENDS 3.1.0; the snippet
# below is written with that value pending the user's decision.
_ARGOPROXY_MIN_VERSION="3.1.0"

local _apv
# NOTE the outer `{ ...; } || true`. Without it this line is a set -e
# landmine of the D-011 class: when the binary is absent (or prints no
# version), `_extract_version`'s internal `grep -oE` exits 1, and under
# `set -euo pipefail` the assignment kills the script SILENTLY -- before
# any diagnostic reaches the user. Caught while dry-running this exact
# snippet during the plan audit (2026-08-10); the naive form
# `_apv="$(_extract_version "...")"` exits 1 with zero output.
_apv="$( { _extract_version "$( { "${venv}/bin/argo-proxy" --version 2>&1; } || true )"; } || true )"
if [ -n "$_apv" ] && ! _version_ge "$_apv" "$_ARGOPROXY_MIN_VERSION"; then
  warn "argo-proxy ${_apv} is older than the recommended ${_ARGOPROXY_MIN_VERSION}."
  warn "  Older versions predate upstream fixes for Claude Opus thinking-type"
  warn "  handling; some models may return empty responses."
  warn "  Upgrade with:  argo-anywhere update argoproxy"
fi
```

**Why warn-only rather than auto-upgrade:** an auto-upgrade inside
`ensure_argoproxy_installed` would fire during `connect`, i.e. while the
user is waiting on a Duo prompt, and could replace a working proxy
mid-session. `update argoproxy` already exists as the deliberate path.

**Note on `_version_ge` and pre-releases:** `_version_ge 3.3.0a1 3.2.3`
returns TRUE (sort -V ranks the alpha above its base). That is correct for
a *floor* check — someone who deliberately installed the alpha is above the
floor — and the import probe (§3.1) is what catches the alpha being broken.
The two checks are complementary; neither substitutes for the other.

### 3.3 UP-13: correct `docs/LIMITATIONS.md`

**Site**: `docs/LIMITATIONS.md:346-443` (the opus-4-7 section, ending just
before the "Claude Code TUI is misleading" heading) and the related
mention at `:638`.

**Change**: re-head the section as **RESOLVED**, move it below the live
limitations, and remove the actionable workaround so nobody follows it.

Keep the diagnosis narrative — it is a genuinely good worked example of
how an SSE-over-HTTP-200 error surfaces as a client-side "malformed
response," and it documents the ANL thinking-support matrix. Only the
*status* and the *instructions* change.

Proposed replacement heading + lede:

```markdown
### RESOLVED (2026-06 upstream): Claude Opus 4.7 / 4.8 "empty or malformed response (HTTP 200)"

> **Status: fixed upstream; no user action needed.** Kept for provenance
> and because the failure mode is instructive. `llm-rosetta >= 0.6.10`
> sets `thinking_type: adaptive` for `claudeopus47` and `claudeopus48`
> in the `argo--anthropic` shim's `reasoning.model_overrides`, which is
> exactly the conversion the ANL gateway requires. Verified still present
> in `llm-rosetta 0.8.2` (2026-08-09) after the 0.7.x/0.8.x
> `ConversionPipeline` migration -- see
> `docs/AUDIT_2026-08-10_argo-proxy-upstream.md` WATCH-17.
>
> If you are on `argo-proxy < 3.1.0`, upgrade
> (`argo-anywhere update argoproxy`); the engine also warns about this
> from v3.2.2 (UP-02 soft floor).
```

**The blast radius is wider than `LIMITATIONS.md`, and worse.** Audited
2026-08-10:

| File | Line(s) | What it says | Severity |
|:---|:---|:---|:---|
| `README.md` | **82-88** | **"Claude Code with `claude-opus-4-7` is currently broken"** — in the **"Heads up before you start"** block, near the top of the README | **worst**: it is one of the first things a new user reads |
| `README.md` | 149 | "remember the opus-4-7 workaround from …" | high |
| `README.md` | 375 | "⚠️ Subject to the opus-4-7 issue in [Heads up]" | high |
| `docs/LIMITATIONS.md` | 346-443, 638 | Full section + cross-ref | high |
| `AGENTS.md` | 237-245 | "Known upstream-stack limitation surfaced during v2.2.0 release-gate" bullet | medium (agent-facing) |

All five must move in the same commit; a partial fix leaves the README
contradicting `LIMITATIONS.md`. The README items are the priority — a
prospective user who reads "Claude Code is currently broken" at the top of
the page may simply not adopt the tool.

---

## 4. Phase 2 — docs + watch hygiene

1. **Land the audit doc** — `docs/AUDIT_2026-08-10_argo-proxy-upstream.md`
   (written; this plan's evidence base).
2. **Add it to the doc map** in `AGENTS.md`'s "Human-facing doc map" table
   and to `notes/README.md`'s impl-note index (this plan).
3. **UP-14** — correct "argo-proxy v3.2.0" references (never released;
   stable line starts at v3.2.1).
4. **UP-04** — replace the enumerated preserved-keys text with "we own
   five keys; everything else is preserved verbatim" + a pointer to
   upstream's `config.sample.yaml`, so it stops aging. **Five sites**
   carry the stale enumeration: `argo-anywhere.sh:6819` (comment),
   `:6880` (comment), `:6889` (err text), `:6957` (err text), `:7100`
   (comment). All list `argo_embedding_url, concurrent_downloads[,
   max_payload_size]` and omit `socket`, `default_chat_model`,
   `default_embed_model`.
5. **Watch-list** — close WATCH-17; add WATCH-18 (unbounded transitive
   pin) + WATCH-19 (v3.3.x adoption).
6. **PLAN.md** — record the outcome. **Does this earn a D-number?** See
   §8 Q1.
7. **Optional**: file the one-line upstream fix for UP-11. Appears
   unreported; costs us little and unblocks v3.3.x adoption sooner.

---

## 5. Phase 3 — UI: surface the argo-proxy version

### U1 — show the node's argo-proxy version

**Motivation.** The web UI reports `package_version`, `engine_version`,
`python_version`, `platform`, and `app_cwd` — but not the version of the
component most likely to break the stack. Under a UP-11-class failure the
user sees "tunnel up, health failing" with no hint of the culprit.

**Mechanism.** argo-proxy exposes **`/version`** on the same loopback port
we already poll for `/health` (confirmed allowlisted alongside `/health`
in 3.3.0a1's `auth.py:27`). So this is:

- one extra HTTP GET **through the tunnel we already have open**;
- **no new SSH connection** → no Duo prompt, no CSPO authentication-budget
  cost;
- only on explicit user action (piggyback the existing "Check now"
  health action), never on the 10 s live poll.

**Sketch** (`src/argo_anywhere/status.py`): extend `channel_health` or add
a sibling `channel_version(port)` returning the parsed version; surface it
in the channel card next to the latency readout, and in the About sheet.

**Constraint to honour**: `/api/health` is already documented as the one
endpoint that traverses the tunnel and is therefore user-triggered only.
Any `/version` call must inherit that discipline — do **not** add it to
`/api/status`, which is contractually local-only.

### U2 — health text renders raw JSON

The channel card shows `{"status": "healthy"}` verbatim. Parse and render
`healthy`. Cosmetic; bundle with U1 or drop.

---

## 6. Testing strategy

Per the project's split (`AGENTS.md`): automated tests for the Python
layer, grep-based invariants for the engine, live tests for anything
touching real SSH.

**Engine (Phase 1)** — new `tests/test_engine_argoproxy_probe.py`,
grep-based, in the style of `tests/test_engine_ssh_config.py`:

- `ensure_argoproxy_installed` contains an `import argoproxy.app` probe.
- The post-install assertion also imports (not just `serve --help`).
- `_ARGOPROXY_MIN_VERSION` is declared and equals the documented floor.
- The floor path calls `_version_ge` and does **not** call `die`
  (soft-floor invariant — this is the one most likely to be broken by a
  future well-meaning edit).
- `bash -n` still clean; `--print-script` round-trip unchanged.

**A shell-unit test** for the floor logic, following the existing pattern
of sourcing a single function (as `test_engine_control_persist.py` does):
feed `3.1.2` / `3.2.3` / `3.3.0a1` and assert warn-vs-silent.

**Docs (Phase 2)** — no automated test. Reviewer checks the doc map is
updated.

**UI (Phase 3)** — extend `tests/test_web_ui_smoke.py`; stub `/api/health`
+ the new version endpoint and assert the card renders the version and
that **no** version call happens on the passive poll.

**Explicitly NOT automated**: the UP-11 reproduction. It requires
installing a known-broken package from PyPI, which would make CI depend on
upstream continuing to host a broken artifact. The reproduction is recorded
in the audit doc; the *defence* is what gets tested.

---

## 7. Risk register

| # | Risk | Likelihood | Mitigation |
|:---|:---|:---|:---|
| **R1** | `argoproxy.app` relocates in a future major → probe false-positives and forces a reinstall loop | low | Probe failure triggers **one** reinstall attempt, then a `die` with the real traceback — it cannot loop. Fail-closed is intentional (§3.1). |
| **R2** | Import probe adds latency to every server bootstrap | certain, tiny | Measured **0.31 s** steady-state (three runs: 0.30/0.31/0.31), against an operation already dominated by SSH + venv work. **Caveat**: the *first* import after a fresh install costs **~2.9 s** while CPython writes `.pyc` files — which is precisely the run where we have just done a `pip install`, so it is invisible. |
| **R2b** | Import probe has side effects on the node (writes config, binds the port) | — | **Ruled out by test**: with a clean `HOME`, `import argoproxy.app` writes no `~/.config`, and port 44497 remains bindable afterwards. It is a pure import. |
| **R3** | Temptation to "fix" UP-11 by pinning `llm-rosetta` in our install command | medium | **Do not.** A ceiling we own must be revised on every upstream release and would silently hold users back. We *suggest* a pin in the error text; we never apply one. Upstream's pin is upstream's to fix. |
| **R4** | Soft floor gets "upgraded" to a hard `die` by a later edit | medium | Invariant test asserts no `die` in the floor path (§6). |
| **R5** | Rewriting `LIMITATIONS.md` loses the diagnosis history | low | Section is re-headed + relocated, **not** deleted. |
| **R6** | Phase 3 `/version` call creeps into the passive poll → tunnel traffic every 10 s | medium | Smoke test asserts no version request on passive refresh (§6). |
| **R7** | Floor is wrong for users on older ANL-provided argo-proxy builds | low | Soft warn only; no functional change. |
| **R8** | `set -e` kills the floor check silently when `--version` yields no parseable version | **hit during the plan audit** | Wrap the assignment `{ ...; } || true` (D-011 pattern). Both branches dry-run verified: missing binary → probe reports `ModuleNotFoundError` and dies loudly; good install → passes. |

---

## 8. Open questions

Answers needed before execution.

- **Q1 — Does this earn a design-decision number?** My read: **no**. UP-12
  and UP-02 are hardening of an existing contract
  (`ensure_argoproxy_installed`), not a new one; D-numbers in this project
  mark architectural commitments. A `CHANGELOG.md` entry plus the audit
  doc seems sufficient. **But** the "fail closed on import failure" bias
  (§3.1) is arguably a new contract worth pinning. Prefer: record as a
  short subsection under the existing D-022 (per-component update
  registry) rather than a new D-number. **Your call.**

- **Q2 — Floor value: `3.2.3` or `3.1.0`?** `3.2.3` is current stable and
  the audit's recommendation. But the *functional* justification (opus
  thinking-type) is satisfied by `llm-rosetta >= 0.6.10`, which
  `argo-proxy >= 3.1.0` carries. A `3.2.3` floor will warn users who are
  fine. Options: (a) `3.2.3` — "stay current"; (b) `3.1.0` — "warn only
  when something is actually broken." I lean **(b) `3.1.0`**, because a
  warning users can safely ignore trains them to ignore warnings.

- **Q3 — Bump engine `SCRIPT_VERSION` (2.3.0 → 2.3.1)?** Phase 1 changes
  engine behaviour (new probe, new warning). D-029 says the engine version
  is an internal component tag. Consistent with past practice would be a
  bump; it is cheap. **Recommend yes.**

- **Q4 — Phase 3 at all?** U1 is genuinely useful for diagnosing stack
  breaks but it is the only item here that adds surface rather than
  removing risk, and we have just spent two sessions stabilising the UI.
  Defer to v3.3.0?

- **Q5 — File the UP-11 fix upstream?** One line
  (`api_key_label_var` → `api_key_context_var`). Unreported. Filing costs
  little and accelerates v3.3.x, which is a real HPC improvement.

- **Q6 — Live re-test needed?** Phase 1 touches the server bootstrap path,
  which `docs/TESTING.md` covers with a live test (real SSH + Duo + node).
  A full live run is expensive. Minimum viable: one `connect --ensure` to
  a node with an existing venv (exercises the probe + floor on a healthy
  install). **Recommend** that narrow test before tagging.

---

## 9. Execution order + commit plan

Ordered so that the highest-value, lowest-risk work lands first and each
commit is independently revertible.

| # | Commit | Contents | Gate |
|:---|:---|:---|:---|
| 1 | `docs(audit): upstream re-walk 2026-08-10` | The audit doc + doc-map entry + this plan | Reviewed (this step) |
| 2 | `fix(engine): detect argo-proxy installs that cannot import` | §3.1 probe + post-install assertion + tests | `bash -n`, pytest, grep invariants |
| 3 | `feat(engine): soft version floor for argo-proxy` | §3.2 + tests | pytest |
| 4 | `docs: mark opus-4-7/4-8 limitation RESOLVED` | §3.3 across LIMITATIONS.md + AGENTS.md + README | manual read |
| 5 | `docs: watch-list + stale-reference hygiene` | Phase 2 items 3-6 | manual read |
| 6 | *(optional)* `feat(web): show argo-proxy version` | Phase 3 | pytest + smoke |

Commits 2-3 both touch `ensure_argoproxy_installed`; keeping them separate
means the floor can be reverted without losing the probe, which matters
because the floor is the one with a live open question (Q2).

**Engine dual-copy discipline**: every engine edit must be applied to both
`argo-anywhere.sh` and `src/argo_anywhere/engine/argo-anywhere.sh` in the
same commit. This is enforced by
`tests/test_smoke.py::test_vendored_engine_is_verbatim`, which asserts the
two are byte-identical (skipped in a wheel, where the repo-root copy is
absent — so it protects dev checkouts and CI, which runs from a checkout).
CI additionally asserts the wheel *ships* the engine, but does not compare
the copies. Practical consequence: **forget the second copy and pytest
fails**, which is the desired failure mode.

---

*Companion document: `docs/AUDIT_2026-08-10_argo-proxy-upstream.md`
(evidence). This note is the plan of record; if anything here ships, the
outcome is recorded in `CHANGELOG.md` and the relevant status blocks are
re-grounded per `AGENTS.md`.*
