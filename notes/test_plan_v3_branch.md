# Live-test plan — v3 branch (D-030 lifecycle + D-028 rename + install-launcher)

**Scope**: the three feature sets landed on `feat/python-package-webui` after P4,
verified so far only by unit tests + sandbox smoke (no real ANL). This plan is
the at-the-keyboard gate. **Owner**: Ahmed Attia (with Claude).
**Created**: 2026-07-11.

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
argo-anywhere --version            # 3.0.0.dev0
```

**Post-push / post-publish:** the git-URL / PyPI forms work once the branch is on
GitHub (or v3 ships):

```sh
pipx install --force 'argo-anywhere[app] @ git+https://github.com/a-attia/argo-anywhere@feat/python-package-webui'
# or, after release:  pipx install 'argo-anywhere[app]'
```

## Pre-flight status (2026-07-11)

Part A pre-flighted from a dev install: **T1-T4, T6 PASS**; **T5 surfaced
Finding 1** (uninstall skipped a leftover `~/.argo_anywhere` in package mode,
disagreeing with the footprint) — **fixed** in `b00ea6e`, re-verified. Part A is
ready to re-run in your pipx environment; **Part B (`connect`) is the remaining
gate.**

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
