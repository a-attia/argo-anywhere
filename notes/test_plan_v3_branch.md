# Live-test plan — v3 (D-030 lifecycle + D-028 rename + install-launcher)

**Status**: **PASSED / GATE CLOSED (2026-07-12)** — see [Live-test result](#live-test-result-2026-07-12--gate-closed).
**Scope**: the three feature sets merged to `main` after P4, previously verified
only by unit tests + sandbox smoke (no real ANL). This plan is the
at-the-keyboard gate. **Owner**: Ahmed Attia (with Claude).
**Created**: 2026-07-11. **Closed**: 2026-07-12.

**Commits under test**: `1b3d465` (D-030), `1c11208` (D-028), `319fd29`
(install-launcher), `b332964` (icon + docs).

## CSPO discipline (read first)

- **One clean SSH/Duo attempt.** 3 failures within 15 min risks a weekend
  lockout. The only real-infra test here (T7) is a single `connect`.
- **Never** run a non-dry `uninstall` / `stop` / `clean` against the port with
  your live channel. Where a test needs uninstall, use `--dry-run` **and** a dead
  `--port` (e.g. 59999) **and** a sandbox `HOME`.
- `argo-anywhere info` and the footprint scan reach nothing; `/health` is not
  polled by `info`.

## Preconditions

Install the branch so the console script has all the commits.

**Pre-merge (branch not yet pushed): install from the local working tree** — no
GitHub round-trip, tests the exact local state:

```sh
cd <repo>                          # the argo-anywhere checkout
pipx install --force '.[app]'
argo-anywhere --version            # 3.0.0
```

**Post-push / post-publish:** the git-URL / PyPI forms work once the branch is on
GitHub (or v3 ships):

```sh
pipx install --force 'argo-anywhere[app] @ git+https://github.com/a-attia/argo-anywhere@main'
# or, after release:  pipx install 'argo-anywhere[app]'
```

## Pre-flight status (2026-07-11)

Part A pre-flighted from a dev install: **T1-T4, T6 PASS**; **T5 surfaced
Finding 1** (uninstall skipped a leftover `~/.argo_anywhere` in package mode,
disagreeing with the footprint) — **fixed** in `b00ea6e`, re-verified.
*(Superseded by the [2026-07-12 result](#live-test-result-2026-07-12--gate-closed):
Part A re-run + Part B `connect` both PASS; gate closed.)*

## Live-test result (2026-07-12) — GATE CLOSED

Run from a `pipx`-installed package (post-merge on `main`; package version
`3.0.0`, engine `2.2.1-dev` — the D-029 split, as designed).

**Part A — PASS** (re-run in the pipx env):

- **T1 PASS** — `--print-script | head -2` → `# argo-anywhere.sh --` (hyphenated).
- **T2 PASS** — `[argo-anywhere]` runtime prefix present (seen on T4's output).
- **T3 PASS** — `info` footprint renders; manifest home `~/.config/argo_anywhere`;
  agent data excluded; a leftover engine-mode `~/.argo_anywhere` (1.3 MB) present
  (upgrader case — good, it lets T5 exercise Finding 1). *(Banner showed the
  then-installed `3.0.0.dev0` build; reinstalled to `3.0.0` before T7.)*
- **T4 PASS** — `update --check argo-anywhere` → "release version managed by
  pipx/pip"; points at `pipx upgrade`; **no** GitHub-tag probe (D-030a dormant
  self-update confirmed).
- **T5 PASS** — `uninstall --dry-run --port 59999` lists the canonical install,
  state dir, sockets; **Finding-1 fix confirmed live**: `[dry-run] would remove:
  …/.argo_anywhere` (not skipped in package mode); lists the launcher `.app` +
  log as package-only residue; ends with `pipx uninstall argo-anywhere`. Dead
  port + dry-run left the live channel on 64742 untouched.
- **T6** — launcher already present from an earlier run (idempotent).

**Part B — T7 PASS** (`ARGO_ANYWHERE_WEB_ENGINE='connect' argo-anywhere web`,
driven from the browser terminal):

- **(a) PASS** — no "First-run setup … `~/.argo_anywhere/bin`" line (bootstrap
  dormant under the package, D-030a).
- **(b) PASS** — the run created/touched **nothing** in `~/.argo_anywhere`
  (`find ~/.argo_anywhere -newermt "today 00:00"` empty). A `~/.argo_anywhere/bin/`
  *does* exist, but it is a **pre-merge engine-mode leftover** (dated Jul 9–10;
  underscore filename `argo_anywhere.sh`, predating the D-028 hyphen rename) — the
  upgrader case, already slated for removal by T5's `uninstall` dry-run. The
  contract (package-mode connect does not bootstrap a new canonical install) holds.
- **(c) PASS** — state dir / manifest home `~/.config/argo_anywhere`. `connect`
  alone did not create `manifest.json` (created on first config-touch, i.e.
  `configure`/`run`), as designed.
- **(d) PASS** — node-side files hyphenated: `Copying script to …:~/.argo-anywhere.sh`;
  `Remote bootstrap: …:~/.argo-anywhere.server.log` (D-028).
- **(e) OBSERVED-PARTIAL** — the run went through the **stdlib `PtySession`**
  (via `argo-anywhere web`) and drove the full engine `connect` to ALL GREEN, so
  the stdlib PTY is proven to drive the engine end-to-end. A **cold Duo was NOT
  reproduced this run**: the ControlPersist mux master was still warm and was
  reused (`master ready … reuse this connection`), so no fresh Duo fired. The
  cold-Duo-legibility-in-browser point is covered by the P1 spike observation
  (cold Duo in the browser, 2026-07-10); the only un-reproduced sliver is
  stdlib-PTY **+** cold Duo simultaneously. Not a publish blocker (see
  `impl_python_webui.md` residuals).
- **(f) PASS** — ALL GREEN (tunnel up, proxy healthy, 44 models).

Bonus: the softened mux-handoff `[warn]` (foreground ssh exits, master keeps the
forward) rendered as intended (D-003).

**Disposition:** the D-028 rename + D-030 lifecycle live-test gate is **CLOSED
(PASS)**. The stdlib-PTY-over-*cold*-Duo observation is recorded as
observed-partial and left as an opportunistic catch on a future natural cold
connect; it does not block the v3.0.0 publish.

## Part A — no infrastructure (safe; run anytime)

| # | Test | Command | Expect |
|:-:|:-----|:--------|:-------|
| T1 | D-028 filename rename | `argo-anywhere --print-script \| head -2` | header line `# argo-anywhere.sh --` |
| T2 | D-028 log prefix | `argo-anywhere list-tools` (or any verb) | runtime lines prefixed `[argo-anywhere]` |
| T3 | D-030 footprint view | `argo-anywhere info` | "on-disk footprint" section renders; **manifest path is `~/.config/argo_anywhere/manifest.json`** if present; agent data never listed |
| T4 | D-030 self-update dormant | `argo-anywhere update --check argo-anywhere` | "managed by pipx/pip"; **no** GitHub-tag probe |
| T5 | D-030 uninstall preview | `argo-anywhere uninstall --dry-run --port 59999` | plan box lists "canonical install … (if present), state dir, tunnels/sockets"; if you have a leftover `~/.argo_anywhere` it shows "[dry-run] would remove: …/.argo_anywhere" (Finding 1 fix — it no longer skips it in package mode); ends with the `pip`/`pipx` removal command |
| T6 | Launcher + icon | `argo-anywhere install-launcher` then open the `.app` | on macOS `~/Desktop/argo-anywhere.command` + `~/Applications/argo-anywhere.app`; the **.app shows the constellation-A icon** in Finder/Dock; double-click opens the web UI (native window if `[app]`, else browser). `argo-anywhere info` lists them; `argo-anywhere uninstall` removes them. |

## Part B — real infrastructure (ONE connect; Duo)

| # | Test | Steps | Expect |
|:-:|:-----|:------|:-------|
| T7 | D-030 package-mode connect + D-028 node files | `argo-anywhere connect` (complete Duo once) | **(a)** NO "First-run setup … `~/.argo_anywhere/bin`" line — bootstrap is dormant; **(b)** `~/.argo_anywhere/` is NOT created; **(c)** the manifest lands at `~/.config/argo_anywhere/manifest.json`; **(d)** the node-side copy is `~/.argo-anywhere.sh` and the server log `~/.argo-anywhere.server.log` (hyphenated); reaches ALL GREEN |

## Part C — migration (only if applicable)

| # | Test | Precondition | Expect |
|:-:|:-----|:-------------|:-------|
| T8 | Manifest home migration | you have a pre-D-030 `~/.argo_anywhere/manifest.json` from earlier engine-mode use | first config-touch (e.g. `configure <tool>`) moves it to `~/.config/argo_anywhere/manifest.json`, content preserved (first-touch-wins) |
| T9 | Node legacy sweep | a compute node carries an old `.argo_anywhere.sh` / `.argo_anywhere.server.log` | `argo-anywhere clean` sweeps them (v2.x legacy names) |

## Notes / rollback

- If T7 shows a bootstrap line or creates `~/.argo_anywhere/`, the CLI passthrough
  marker isn't reaching the engine — check `ARGO_ANYWHERE_PACKAGED` (D-030a).
- All Part-A tests are reversible; Part-B leaves a real channel up (tear down with
  `argo-anywhere stop` when done, which only kills a tunnel it owns).
