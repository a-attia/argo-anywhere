# Implementation plan — Python package + web UI (Model A)

**Status**: building — P1 gate PASSED; **P0 + P2 + P3 code complete** (2026-07-10,
P3 single-terminal model; concurrency deferred to Q12); P4–P5 pending.
**Owner**: Ahmed Attia. **Last updated**: 2026-07-10.
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
- [What is built (P2)](#what-is-built-p2)
- [What is built (P3)](#what-is-built-p3)
- [Lifecycle unification (D-030, proposed)](#lifecycle-unification-d-030-proposed)
- [Remaining work (P4–P5)](#remaining-work-p4p5)
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
| **P2** | Dashboard + monitor: process registry, `/health` polling, a "show all tunnels" view (new capability; D-006 has none today) | **CODE COMPLETE (2026-07-10)** — status/health core (`status.py`, `argo-anywhere info`, `GET /api/status`) + session registry (`web/registry.py`) + dashboard endpoints (`/api/sessions`, on-demand `/api/health`, guarded `POST /api/sessions/{id}/stop`) + the dashboard UI (channel signal-path + sessions + listeners). 65 tests pass. Residual: one at-the-keyboard `/api/health` observation against a live tunnel (never auto-polled; user-action only) |
| **P3** | Configure/run in the UI: conflict-escalation to the PTY lane; run-client-in-terminal; info views (list-models/list-tools/status) | **CODE COMPLETE (2026-07-10, single-terminal model)** — info views (`POST /api/run/{verb}`), parameterized embedded launcher (`/ws?verb=…&cli_tool=…&scope=…`) with channel-owner replace-guard, **plus native new-window launch** (`external_terminal.py` + `/api/launch-external` + `/api/terminals`; user-picked terminal, OS default). Conflict-escalation is inherent: `configure`/`run` are Lane-2 so their prompts run in the PTY. Concurrent multi-session now served by new native windows; in-UI PtySession concurrency remains Q12. 103 tests pass |
| **P4** | Packaging polish: `pywebview` native window, `docs/UPGRADING.md` hard-cutover section, the D-028 clean-break content rename, PyPI publish | **in progress (2026-07-11)** — `argo-anywhere app` native window (`[app]` extra; pywebview, browser fallback) + `docs/UPGRADING.md` v2→v3 hard-cutover section + build/install verified (`python -m build` -> wheel bundles engine + static; fresh-venv console-script smoke) + `--print-script` BrokenPipe fix. **D-030 lifecycle unification (code-complete 2026-07-11) + D-028 content rename (done 2026-07-11)** both landed. **Still pending**: actual PyPI publish (needs a token; the user's action) + the joint D-030/D-028 live-test gate. 123 tests pass |
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

## What is built (P2)

P2 landed on 2026-07-10 (the genuinely new capability D-006's single-instance
model lacks):

- **Session registry** (`web/registry.py`): a thread-safe `SessionRegistry` of
  the live `PtySession`s the web server spawns (one per `/ws`). Each
  `ManagedSession` records id / argv / verb / pid / start-time and a static
  `owns_channel` flag from the new `driver.CHANNEL_VERBS`
  (`connect`/`tunnel`/`client`/`setup` — the verbs whose process hosts the SSH
  master; see [Operational lessons](#operational-lessons)).
- **Dashboard endpoints** (`web/app.py`): `GET /api/sessions`, `GET /api/status`
  now also carries `sessions`, on-demand `GET /api/health?port=N` (the only
  ANL-reaching call — a loopback GET that traverses the tunnel, so it is
  **user-action only, never auto-polled**), and `POST /api/sessions/{id}/stop`
  with a **kill-guard**: stopping a channel-owning session while a loopback
  listener is live on the cached port returns `409` + a warning; the UI confirms
  and retries with `force=true`.
- **Dashboard UI** (`web/static/index.html`): a channel *signal-path*
  (`this laptop ──:port──▶ node ──▶ argo-proxy`) with per-hop live status, a
  managed-sessions list, and loopback listeners. Local status auto-refreshes
  every 5 s (paused when the tab is hidden); channel health is a button. The
  terminal + WebSocket bridge is unchanged from P0.
- **Tests**: `tests/test_registry.py` (registry lifecycle, kill-guard,
  endpoints, `/api/health` against a localhost stub — never ANL). Suite: 65
  pass, no ANL/SSH/network.

## What is built (P3)

P3 landed on 2026-07-10 (single-terminal model):

- **Info views** (`web/app.py`): `POST /api/run/{verb}` runs a whitelisted
  returning verb captured (Lane 1, stdin closed) and returns
  `{argv, returncode, stdout, stderr, reaches_anl}`. `INFO_VERBS` gates the
  allowlist: `list-tools` (local), `status` + `list-models` (ANL — flagged so
  the UI confirms before running and **never** auto-runs them). 30 s timeout ->
  `504`.
- **Terminal launcher** (`web/app.py`): `/ws` now accepts validated query params
  (`verb` in `KNOWN_VERBS`, plus `cli_tool` / `scope` / `port` through
  `build_launch_argv`, a strict allowlist builder — no free-form passthrough).
  No params -> the server's configured default (unchanged P0/P1 behavior).
- **Native new-window launch** (`external_terminal.py` + `POST /api/launch-external`,
  `GET /api/terminals`): open a chosen verb in an **independent native terminal
  window the user owns** (not a server PtySession, not in the registry) running
  the console script on a real TTY -- full-fidelity Duo / monitor / prompts.
  Terminal choice is the user's: `available_terminals()` detects Terminal.app +
  iTerm2 (macOS, via `osascript`) plus Alacritty / kitty / WezTerm / Ghostty and
  the Linux emulators (by `PATH`); the default is the OS built-in (Terminal.app,
  **not** iTerm), overridable per-launch or via `ARGO_ANYWHERE_TERMINAL`.
- **Dashboard, redesigned monitor-first** (`web/static/index.html`, 2026-07-10
  pm): the page is the monitor; the terminal is a hidden drawer that reveals on
  a `Connect`/embedded launch or the header `Terminal` toggle, and **the page no
  longer auto-runs `connect` on boot** (opening the UI shows the monitor;
  connecting is explicit). Model locked with the user: the embedded terminal's
  job is **establishing the connection** (Duo-in-browser), while **CLI tools run
  in a new native window by default**. Concretely:
  - **Channel card** is the hero + the live status (no raw `status` dump): a
    `Connect` CTA when the tunnel is down (-> embedded terminal), and
    signal-path + meta + **live health** when up, naming who holds the channel
    (this UI vs an external terminal). Health is polled every 10s while the
    tunnel is up (a `Live` toggle, default on; `Check now` for a manual probe).
    **Safety**: the probe is an HTTP GET to `/health` through the *existing*
    tunnel -- it never opens an SSH connection, so it cannot trigger the
    3-failures/15-min Duo lockout (the engine's own monitor already polls
    `/health` in a loop). It self-gates on tunnel-up + tab-visible and never
    initiates tunnel/SSH setup.
  - **`+ Launch tool`** header button opens a focused popover (command / cli-tool
    / scope / **target**). Target defaults per command -- new native window for
    `run`/`client`/`configure`/`setup`, embedded for `connect`/`tunnel` -- and
    is overridable; the embedded path keeps the channel-owner replace-guard.
  - Cards: **Tunnels** (loopback listeners), **Held by this UI** (registry
    sessions; usually empty by design), **Tools & models** (tools as chips from
    `list-tools`; models as a scrollable list loaded on demand via
    `list-models`, ANL-gated). The reconnectable `openTerminal()` drives the
    drawer.
- **Conflict-escalation to the PTY lane** is inherent, not a separate feature:
  `configure`/`run`/`connect`/`tunnel` are Lane 2, so their three un-flaggable
  prompts (port-migrate / config-conflict / scope-conflict) run in the browser
  PTY where the user can answer them. Making them run *headless* in Lane 1 is
  the separate P5 work (engine flags for those prompts).
- **Tests**: `tests/test_run_launch.py` (argv-builder allowlist, `/api/run`
  validation, `list-tools` captured, `/ws?verb=help` launch, bad-spec rejection)
  + `tests/test_external_terminal.py` (command/AppleScript builders, OS dispatch
  with fake spawns, terminal detection + default, endpoints with the spawn
  monkeypatched -- no window ever opens). Suite: 103 pass, no ANL/SSH/network.

**On concurrency (Q12).** The *embedded* terminal is still single-session
(launching replaces it). But the practical need -- run `configure`/`run` (or a
second `connect`) *alongside* a held session -- is now served by **Open in new
window**: each native window is an independent process the user owns, exactly
matching how they already juggle many terminals. The narrower open question
(multiple concurrent *PtySessions inside the web UI*, and where `manifest.json`
lives) remains PLAN.md Q12; it is no longer blocking real multi-session use.

## Lifecycle unification (D-030, proposed)

**Status**: **CODE COMPLETE on the branch (2026-07-11)**; unit-tested (13 new
tests), sandbox-verified (no ANL); **live-test gate pending** (the engine edit
wants one real re-test alongside the D-028 rename). Was written design-first and
reviewed before coding, at the user's request. Models on the sibling
`scrollback` project's lifecycle design (`../scrollback`:
`src/scrollback/launcher_install.py` `footprint()` + `src/scrollback/cli.py`
`cmd_uninstall` / `_detect_install_tool`). Recorded in PLAN.md as the `D-030`
entry (§7) with the Q12 manifest-home resolution (§11).

**What landed (all four steps + the Q12 prerequisite):**

- **Manifest → state dir** (Q12): `ARGO_MANIFEST` re-pointed to
  `${STATE_DIR}/manifest.json`; `ARGO_MANIFEST_LEGACY` + `_manifest_migrate_home`
  do a one-shot, first-touch-wins-preserving migration (run from
  `_manifest_available`, so both record + restore paths see it). Sandbox-verified
  end-to-end.
- **D-030a marker**: `packaged_env()` in `_engine.py` sets
  `ARGO_ANYWHERE_PACKAGED=1` on all three package→engine spawn sites (CLI
  passthrough + driver Lane 1 `run_engine` + Lane 2 `PtySession`). Engine honors
  it: bootstrap dormant, `install` → pipx hint, `update argo-anywhere` → pipx
  hint, `update --check` self-row → "managed by pipx" (no GitHub probe),
  `uninstall` Tier-1 canonical-dir removal skipped. Engine-mode (`--print-script`
  fork) untouched. Sandbox-verified for all five behaviors + a marker unit test.
- **D-030b footprint** (`footprint.py`): `footprint(home=…)` ledger
  (disposable/artifact tiers; canonical dir, state dir, SSH sockets, config
  backups; never lists live agent data), extends `argo-anywhere info` (text +
  `--json`). Visibility-first; removal delegated to the engine `uninstall`.
- **D-030c package `uninstall` verb**: `cli.main` intercepts `uninstall` before
  passthrough; delegates the D-025 tiers inward (marker set → canonical-dir
  skip), then prints the `pipx`/`pip` removal command (`_package_removal_command`,
  `sys.executable`-based) only on rc == 0 (no nudge on an aborted teardown).
  Never self-deletes.

New tests: `tests/test_packaged_marker.py` (5), `tests/test_footprint.py` (7),
`tests/test_uninstall_verb.py` (6). Suite: **123 pass**, no ANL/SSH/network;
engine copies byte-identical.

The original design write-up follows (kept as the record of what was decided and
why).

### The problem: two lifecycle systems that don't know about each other

On `main`, argo-anywhere owns its whole lifecycle through the engine:

- **Install** — `argo_anywhere.sh install` + the first-run bootstrap
  (`maybe_bootstrap_canonical_install`, fired from `mode_client`/`mode_setup`)
  materialize a canonical rustup-style install at `~/.argo_anywhere/bin/`
  (D-023), with a sourceable `env` and an install `manifest.json` (D-025).
- **Update** — `update argo-anywhere` self-updates that copy from GitHub tags
  (D-023).
- **Uninstall** — `argo_anywhere.sh uninstall`: tiered teardown + manifest-driven
  config restore (D-025).

On this branch the package (D-029) adds a *second* install system —
`pipx install argo-anywhere` — that is unaware of the first. Because the CLI
passes `client`/`setup` straight through to the vendored engine
(`cli._run_engine_passthrough`, which sets **no** environment), the engine's
first-run bootstrap still fires. A pipx user therefore silently ends up with
**both**:

- the pipx venv + the `~/.local/bin/argo-anywhere` console-script shim, and
- a `~/.argo_anywhere/bin/argo_anywhere.sh` — a *second, independently
  self-updating* copy of the engine.

Two concrete failures follow:

1. `pipx uninstall argo-anywhere` removes the venv but **orphans**
   `~/.argo_anywhere/` (+ manifest + config backups + the second engine copy).
2. `update argo-anywhere` self-updates the `~/.argo_anywhere/bin/` copy from
   GitHub tags, which **drifts** from the pip-installed version — defeating
   D-029's "the package version is the single source of release identity."

### The model borrowed from scrollback

scrollback solved the same shape cleanly. Its spine:

1. **The package manager owns the package.** `scrollback uninstall` removes only
   files scrollback dropped on disk, then *prints* the removal command
   (`pipx uninstall` vs `pip uninstall`, chosen from `sys.executable`); it never
   tries to self-delete ("a process cannot reliably uninstall the package it is
   executing from").
2. **One footprint ledger.** A single `footprint()` enumerates every path
   scrollback created, each tagged by tier; **both** `doctor` (visibility) and
   `uninstall` (removal) consume it — what you see listed is exactly what gets
   removed.
3. **Tiers as data, not branches**: `disposable` (cache/index — rebuilt on
   demand), `artifact` (things install created), `durable` (user data — kept
   unless `--purge-archive`).
4. **Never touch data it only reads** (the agent transcripts) — structurally
   excluded from the footprint, not merely handled carefully.
5. **Escalating confirmation** for irreversible loss (typing a literal phrase
   even with `-y`).

The one place argo is *ahead* of scrollback and must keep: scrollback only ever
*creates* files, so "restore" = "delete"; argo *modifies* the user's client
configs, so it needs the **manifest-driven restore** (D-025) to put back the true
pre-argo original. That machinery has no scrollback analogue and stays.

### Decisions (D-030)

- **D-030a — the package owns the runtime; the engine's self-install goes
  dormant in package mode.** The CLI marks every engine passthrough with a new
  env signal `ARGO_ANYWHERE_PACKAGED=1` (set in `cli._run_engine_passthrough`).
  The engine honors it:
  - the first-run bootstrap is skipped — no `~/.argo_anywhere/bin/` is ever
    created under the package (a superset of today's
    `ARGO_ANYWHERE_SKIP_BOOTSTRAP=1`);
  - `argo_anywhere.sh install` and the `argo-anywhere` **self-update component**
    of `update` become "use pipx" hints. The *other* update components
    (`argoproxy` / `opencode` / `claudecode`) are unaffected — they are not the
    package;
  - `update --check`'s `argo-anywhere` row reports **"managed by pipx"** instead
    of installed-vs-GitHub-tag (the tag comparison is meaningless when pipx owns
    the version);
  - the engine's own `argo_anywhere.sh uninstall` still runs (reachable via
    passthrough and delegated to by D-030c), but its **Tier-1 canonical-dir/`env`
    removal becomes a no-op** (there is no canonical dir under the package); the
    tunnel/socket teardown, config-restore (Tier 2), binary (Tier 3) and remote
    (Tier 4) tiers are unaffected.
  - **Bonus UX win**: suppressing the bootstrap also stops PATH gaining a
    *second, differently-named* command — the package installs `argo-anywhere`
    (hyphen) while the engine bootstrap would drop `argo_anywhere.sh`
    (underscore) alongside it. One command under the package, not two.
  - **Engine mode is unchanged.** A user who forks the raw `.sh` via
    `--print-script` (the D-026/D-027 escape hatch) runs `bash` directly with no
    marker, so D-023/D-025 behave exactly as on `main`. The two modes are
    distinguished by one env var and nothing else. (A forked engine predates the
    marker and never receives it — forks are engine-mode by definition; the
    vendored engine is always version-locked to its package, so CLI↔engine skew
    cannot arise within one install.)

- **D-030b — a single footprint ledger for argo's own on-disk files
  (ledger-first; removal delegated).** A new enumerator (Python, in the package —
  the natural home now, mirroring scrollback's `footprint()`) tags every path
  argo created. Its **primary role is visibility**: it extends the existing
  `argo-anywhere info` command (not a new `doctor` verb — argo already chose
  `info`) so a user can answer "what has argo put on my machine?" in one place,
  scrollback-style. Its **removal role is thin and mostly delegated**: the engine
  `uninstall` Tier-1 already sweeps the state dir + sockets (with the ownership
  guard), so D-030c hands those to the engine and the ledger only *removes*
  package-only residue the engine doesn't know about (e.g. a pywebview cache).
  Tiers for argo:
  - `disposable` — state dir (`~/.config/argo_anywhere/`, cached
    user/node/port + the relocated `manifest.json`, see below), SSH mux sockets
    (`~/.ssh/sockets/argo-anywhere-*`), any pywebview cache.
  - `artifact` — the canonical `~/.argo_anywhere/` + `env` (**engine mode only**;
    absent under the package), and the client-config `.bak.*` backups the
    manifest points at, tagged **"restore source; consumed on uninstall"** (they
    are the restore *source*, so they are not removed independently — an
    uninstall consumes them via the config-restore, never strands one).
  - argo has **no `durable` / user-owned tier**: unlike scrollback's vault, argo
    owns no user data. The client configs are the *user's*, only
    modified-and-restored, never argo's to delete.
  - **Live-channel guard reused**: any socket/listener in the footprint is
    classified through `local_tunnel_status` before removal (the same guard
    `stop`/`uninstall` use), so teardown never kills a live or foreign channel.

- **D-030c — a package-level `argo-anywhere uninstall` verb.** In package mode
  this is THE front door. The CLI **intercepts** `uninstall` before the engine
  passthrough (exactly as it already intercepts `web`/`app`/`info` in
  `cli.main`) so the package verb — not the engine's own — is what a pipx user
  hits. It then **delegates** the config-restore + binary + remote tiers inward
  to the engine's existing `uninstall` (D-025, invoked with
  `ARGO_ANYWHERE_PACKAGED=1`) rather than reimplementing them, removes any
  package-only footprint residue (D-030b), and finally **prints** the exact
  `pipx uninstall argo-anywhere` / `pip uninstall argo-anywhere` command (chosen
  from `sys.executable`, scrollback-style). It never self-deletes the package.
  `--dry-run` previews; the irreversible pieces keep D-025's confirmation
  discipline. (`install` is *not* intercepted — under the package the engine's
  own `install` simply prints a "use pipx" hint per D-030a; only `uninstall`
  needs to do real cross-layer work.)

- **D-030d — keep the manifest.** Config-provenance restore (D-025) is retained
  verbatim; it is the piece scrollback doesn't need and argo can't do without.

### Resolved dependency: manifest's home (Q12 → state dir)

In package mode the bootstrap never creates `~/.argo_anywhere/`, so the manifest's
current path `~/.argo_anywhere/manifest.json` may not exist. **Decided
2026-07-11: the manifest moves to the state dir,
`~/.config/argo_anywhere/manifest.json`** — always present under the package, and
a single teardown root alongside the cached user/node/port state. This settles
the open half of PLAN.md Q12. Implementation notes:

- The engine's `ARGO_MANIFEST` constant (currently `${ARGO_INSTALL_DIR}/manifest.json`)
  re-points at the state dir; the manifest read/write helpers
  (`_manifest_stamp_installed_at`, `manifest_record_config`,
  `manifest_record_binary`, and uninstall's `_manifest_configs_to_restore` /
  `_manifest_binaries_we_installed`) follow the constant, so this is a one-line
  path change plus a one-time migration.
- **Migration**: an existing `~/.argo_anywhere/manifest.json` (D-025 flat layout)
  is moved to the state dir on first touch, first-touch-wins preserved. Engine
  mode still creates `~/.argo_anywhere/bin/`, but the manifest lives in the state
  dir under **both** modes now (one code path, no mode-branch on the manifest).
- Feeds PLAN.md Q12's "manifest.json's new home" directly; record the resolution
  there when the PLAN.md D-030 stub lands.

### Risks / review notes

- **Marker propagation to remote `server`.** `ARGO_ANYWHERE_PACKAGED=1` is set on
  the *local* passthrough; the engine's `remote_bootstrap` scp's a plain `.sh`
  and re-execs it as `server` over SSH, which does not forward this env. Benign
  either way (server mode never bootstraps/self-installs), but assert it in the
  live re-test.
- **Overlap resolved by delegation, not duplication.** D-030c wrapping the
  engine `uninstall` (à la scrollback's `uninstall` reusing `footprint()`) is
  what keeps the two uninstall paths from diverging.
- **Shippable without it.** A first PyPI v3.0.0 can honestly document "remove
  with `pipx uninstall`; full config-restore + `~/.argo_anywhere` teardown lands
  in 3.0.x." D-030 tightens the story in a point release; it is **not** a
  publish blocker.

### Scope / phasing

Proposed as **P4 lifecycle work** — landed with, or just after, the D-028
content rename, since both edit the vendored engine and both want a single live
re-test. Sequence:

1. **Manifest → state dir** (Q12, decided): re-point `ARGO_MANIFEST` +
   one-time migration. Prereq for D-030a's package-mode manifest access.
2. **D-030a** — engine guard (`ARGO_ANYWHERE_PACKAGED`, set in
   `cli._run_engine_passthrough`) + dormant self-install / self-update /
   `update --check` row. Engine edit → live re-test alongside the rename.
3. **D-030b** — footprint enumerator (package) extending `argo-anywhere info`.
4. **D-030c** — CLI intercepts `uninstall`; delegates the D-025 tiers inward,
   removes package-only residue, prints the pip/pipx command.

Each step is independently testable without ANL infra, except the final live
re-test of the engine edit.

## Remaining work (P4–P5)

P4–P5 are conventional engineering on top of a proven base; see the phase table
above for scope. **Lifecycle unification (D-030, above)** is folded into P4. The
immediate next step is **P4 (packaging polish)** —
`pywebview` native window, the `docs/UPGRADING.md` hard-cutover section, the
D-028 clean-break content rename, and PyPI publish. P5 (headless engine flags
for the three prompts) is optional/upstream-able.

**D-028 content rename — DONE (2026-07-11).** Hyphenated the user-facing
surfaces: the engine filename (`git mv argo_anywhere.sh argo-anywhere.sh`; the
vendored copy was already hyphenated, so both are now `argo-anywhere.sh` and
`test_vendored_engine_is_verbatim` still passes), `REMOTE_SELF`/`REMOTE_LOG`
node-side files (+ v2.x `.argo_anywhere.*` legacy sweep in `clean`), the log
prefix `[argo-anywhere]`, the self-update header sentinel (accepts both the new
and the legacy header for robustness), the summary-box titles, help/error text,
and the user-facing docs (README/AGENTS/UPGRADING/TESTING/SECURITY/LIMITATIONS/
examples). **Kept underscored** (platform + deliberate carve-outs): the 17
`ARGO_ANYWHERE_*` env vars + internal bash identifiers (POSIX), and — per the
2026-07-11 scope call — the on-disk **directory** names
(`~/.config/argo_anywhere`, `~/.argo_anywhere`), deferred so as not to stack a
migration on D-030's manifest move. `notes/` + PLAN.md keep their historical
`argo_anywhere.sh` design references by design.

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
