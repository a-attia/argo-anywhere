# Implementation plan — Python package + web UI (Model A)

**Status**: building — P1 gate PASSED; **P0 code complete** (2026-07-10);
P2–P5 pending. **Owner**: Ahmed Attia. **Last updated**: 2026-07-10.
**Branch**: `feat/python-package-webui` (forked from `main` at the D-024 verb
split; not yet merged). **Linked PLAN.md**: design decisions
[D-026..D-029](../PLAN.md#7-design-decisions-log); open questions
[§11 items 9–12](../PLAN.md#11-open-questions).

This is the single source of truth for the Python-package + web-UI rebuild. It
consolidates the two exploration docs that preceded it (`spike/HANDOFF.md` +
`spike/RESULTS.md`, now reduced to stubs pointing here) with everything decided
and built since.

## Contents

- [Purpose](#purpose)
- [Status at a glance](#status-at-a-glance)
- [Architecture](#architecture)
- [What is proven](#what-is-proven)
- [What is built (P0)](#what-is-built-p0)
- [The two-lane driver contract](#the-two-lane-driver-contract)
- [Remaining work (P2–P5)](#remaining-work-p2p5)
- [Residuals and open questions](#residuals-and-open-questions)
- [Operational lessons](#operational-lessons)
- [Develop and run](#develop-and-run)
- [Provenance](#provenance)

## Purpose

Turn argo-anywhere from a single bash script into a `pip`-installable Python
package that **owns the runtime**, wraps the **unchanged** bash engine (vendored
verbatim as package-data), and adds a loopback-only web UI that can connect
(including Duo), monitor, configure, and run clients from a browser terminal.
The engine stays the single source of truth for all orchestration; the package
adds only the runtime and web layer around it. Rationale and the supersession of
the single-file rule (D-001) are recorded as
[D-026](../PLAN.md#7-design-decisions-log) in PLAN.md.

## Status at a glance

| Phase | Scope | Status (as of 2026-07-10) |
|:--|:--|:--|
| **P1** | Gate: can the whole `connect` flow (incl. Duo) be driven from a browser terminal over a WebSocket-bridged PTY? | **PASS** — incl. a live cold-Duo observation |
| **P0** | Package skeleton + verbatim engine + two-lane driver + web layer + CLI dispatch | **CODE COMPLETE** — 42 tests pass (see `tests/`) |
| **P2** | Dashboard + monitor: process registry, `/health` polling, a "show all tunnels" view (new capability; D-006 has none today) | pending |
| **P3** | Configure/run in the UI: conflict-escalation to the PTY lane; run-client-in-terminal; info views (list-models/list-tools/status) | pending |
| **P4** | Packaging polish: `pywebview` native window, `docs/UPGRADING.md` hard-cutover section, the D-028 clean-break content rename, PyPI publish | pending |
| **P5** | Optional/upstream-able: add engine flags for the 3 un-pre-answerable prompts so they run headless in Lane 1 | pending |

Commit trail for P0 lives on the branch (`git log --oneline`); the key SHAs as
of 2026-07-10 are `b41008c` (skeleton), `3e6062b` (driver), `f803c82` (web),
`b7b4484` (CLI dispatch), on top of the decision commits `afc322d` + `4e7d1a4`
and the cold-Duo record `da09572`.

## Architecture

Model A: the package is the runtime; the engine is a vendored asset it drives
through two lanes.

```text
                    ┌───────────────────────────── argo_anywhere (pip package) ──┐
  terminal user ───▶│ cli.py ── passthrough (real tty) ─────────────┐            │
                    │                                                ▼            │
  browser ─ WS ────▶│ web/app.py ─ pty_bridge ─▶ driver.PtySession ─┤            │
  (xterm.js)        │ driver.run_engine (captured) ─────────────────┤            │
                    │                                                ▼            │
                    │                       engine/argo-anywhere.sh (VERBATIM) ───┘
                    └────────────────────────────────────────────────────────────┘
                                             │ scp + ssh
                                             ▼
                              compute node: argo-proxy (unchanged)
```

The engine's interactive surface splits into two lanes (the heart of the
design):

- **Lane 1 — captured subprocess** for verbs that return and are pre-answerable
  via flags/env (`status`, `list-models`, `stop`, `update`, ...). Run with
  stdin closed so no prompt can hang. `driver.run_engine` → `EngineResult`.
- **Lane 2 — PTY** for Duo, the long-lived monitor loop, and the three prompts
  with no non-interactive flag. Streamed to the browser terminal via
  `web/pty_bridge.py`. `driver.PtySession`.

The plain terminal CLI does **not** use the lanes: it passes engine verbs
straight through on the user's real tty (full fidelity). The lanes exist for the
web and programmatic callers, which have no inherited controlling terminal.

## What is proven

The P1 gate — *can the entire interactive `connect` flow run from a browser
terminal, with no native terminal?* — is cleared.

| Check | Method | Result |
|:--|:--|:--|
| Prompt out / keystroke in / output back | headless + browser smoke | PASS |
| Resize control frame → PTY dims | 40×120 via `TIOCSWINSZ` | PASS |
| Silent no-echo password read (the Duo/ssh mechanism) | `read -s` | PASS |
| Host-header (DNS-rebinding) guard | curl good/bad host | 200 / 403 |
| Real engine `connect`, browser-driven | node picker + ssh master + ALL-GREEN box render | PASS (2026-07-09) |
| **Live cold Duo** in the browser terminal | fresh master; Duo Push completed in-browser; reached ALL GREEN | **PASS (2026-07-10)** |

The cold-Duo observation is the one that mattered: it confirmed a *fresh* Duo
challenge renders legibly and completes entirely in the browser, and it left the
SSH-fail-lock absent throughout (one clean attempt; CSPO discipline held).

## What is built (P0)

The package installs, the engine round-trips byte-for-byte via `--print-script`,
and `python -m argo_anywhere.web` serves a working browser terminal wired to the
engine. Layout as built:

```text
pyproject.toml                     setuptools/PEP 621; console-script `argo-anywhere`;
                                   requires-python >=3.10; extras [web]/[all]/[test]
src/argo_anywhere/
├── __init__.py                    __version__ = "3.0.0.dev0" (authoritative; D-029)
├── __main__.py                    `python -m argo_anywhere`
├── cli.py                         dispatch: --version/--print-script/web + engine passthrough
├── _engine.py                     engine_bytes() + engine_path() context manager
├── driver.py                      two-lane driver: classify / run_engine / PtySession
├── engine/
│   └── argo-anywhere.sh           the engine, vendored VERBATIM (D-026/D-028)
└── web/
    ├── app.py                     FastAPI factory + serve(); loopback + host-guard
    ├── pty_bridge.py              WebSocket ↔ PtySession (lifted from the spike)
    ├── __main__.py                `python -m argo_anywhere.web`
    └── static/                    xterm.js/css/fit (vendored) + index.html
tests/                             test_smoke.py + test_driver.py + test_web.py
```

Verification captured at commit time: 42/42 tests pass (no ANL/SSH/network);
wheel and sdist both bundle the engine + static assets; the live server passes
healthz/index/static/bad-host checks; `--print-script` reproduces the engine
byte-identically (`bash -n` clean).

One simplification landed during P0: because the bridge reuses the stdlib
`driver.PtySession`, the `[web]` extra needs **no `ptyprocess`** — one PTY
implementation, core stays dependency-free.

## The two-lane driver contract

The three engine prompts with **no** non-interactive flag MUST route through
Lane 2 (a real PTY). They are the reason the browser terminal exists:

| Prompt | Options | Engine location |
|:--|:--|:--|
| Port migrate | `[m/u/k/a]` | `prompt_port_choice` (`argo_anywhere.sh:1680`) |
| Config-file conflict | `[k/b/d/m/a]` | `handle_config_file` (`argo_anywhere.sh:2355`) |
| Scope conflict | `[k/s/a]` | `prompt_scope_switch` (`argo_anywhere.sh:2490`) |

Everything else has a flag/env pre-answer and can run in Lane 1. Two
foreground-blocking flows also belong to Lane 2: `monitor_tunnel_loop` (the
infinite reconnect/health loop; health = `/health`, not the foreground pid, per
D-003) and `mode_run` (ends with `exec "$bin"`). Self-invocation still works:
`remote_bootstrap` scp's the engine to the node and re-execs it as `server`;
under packaging the node still receives a plain `.sh`.

## Remaining work (P2–P5)

P2–P5 are conventional engineering on top of a proven base; see the phase table
above for scope. The immediate next step after P0 is **P2 (dashboard + monitor)**
— the first genuinely new capability, since D-006's single-instance model has no
"show all tunnels" view today.

Before P4's clean-break content rename, note the D-028 scope carve-outs recorded
in PLAN.md: hyphenate user-facing surfaces (filename, `REMOTE_SELF`, log prefix,
self-update sentinel, live docs, dirs-via-migration) but **not** the 17
`ARGO_ANYWHERE_*` env vars or internal bash identifiers (POSIX forbids hyphens).

## Residuals and open questions

**Residual to exercise before promotion (live, needs a keyboard):** the web
bridge drives the **stdlib** `PtySession`, whereas the spike proved the browser
path with `ptyprocess`. The stdlib PTY has not yet been observed over real
ssh/Duo. This is the same class as the (now-closed) spike cold-Duo residual;
stdlib PTYs are the standard approach, but one at-the-keyboard observation is
warranted (CSPO: one attempt). Run it with
`ARGO_ANYWHERE_WEB_ENGINE='connect' argo-anywhere web`, then complete Duo in the
browser.

**Open questions** (full text in [PLAN.md §11 items 9–12](../PLAN.md#11-open-questions)):
Python floor is settled at `>=3.10`; still open are the two-version-number
surfacing (Q10), the web-server security posture to ratify in `docs/SECURITY.md`
(Q11), and the Lane-2 PTY concurrency model plus `manifest.json`'s new home
(Q12).

## Operational lessons

**Killing the process that hosts a `connect` tears down the SSH master.**
D-003 says the mux master outlives the *foreground `ssh -N -L`* — but it does
**not** survive killing the entire `connect` monitor process that created it.
On 2026-07-10, stopping a leftover web/spike server that was hosting a
`connect` brought the whole channel down with it. When a `connect` runs under a
managed process (web server, spike server, PtySession), that process owns the
channel's lifecycle; treat teardown accordingly. This directly shapes P2's
process registry: the dashboard must track which managed process owns which
channel, and warn before killing one that owns a live tunnel.

## Develop and run

Dependencies are managed with `uv` in a git-ignored `.venv`.

```bash
# from the repo root
uv venv .venv --python 3.13
uv pip install --python .venv/bin/python -e ".[test]"   # editable + web + pytest
.venv/bin/pytest tests/ -q                              # 42 tests; no ANL/SSH/network
```

```bash
# run the console script (engine passthrough on the real terminal)
.venv/bin/argo-anywhere --version
.venv/bin/argo-anywhere --print-script > argo-anywhere.sh   # inspect-and-fork
.venv/bin/argo-anywhere status                              # passthrough to the engine

# run the web UI (loopback-only); use engine=help for a no-ANL dry run
ARGO_ANYWHERE_WEB_ENGINE=help .venv/bin/argo-anywhere web   # then open http://127.0.0.1:8799
```

## Provenance

Consolidated 2026-07-10 from `spike/HANDOFF.md` (the session-handoff, now a
stub) and `spike/RESULTS.md` (the P1 results, now a stub), plus the design
decisions and P0 implementation landed since. The `spike/` directory retains the
original proof-of-concept code (`server.py`, `smoke_test*.py`, `static/`) as the
historical reference the P0 web layer was lifted from.

*Created 2026-07-10 by Ahmed Attia (with substantial AI assistance from Claude
per [`CONTRIBUTORS.md`](../CONTRIBUTORS.md)).*
