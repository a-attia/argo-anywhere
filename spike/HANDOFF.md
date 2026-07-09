# Handoff — Python package + web-UI exploration for argo-anywhere

**For the next execution session.** Read this first, then `spike/RESULTS.md`,
then `PLAN.md`. This documents where the exploration stands, what is proven,
what is queued, and how to continue.

---

## TL;DR

- **Goal:** turn argo-anywhere into a `pip`-installable Python package that
  **owns the runtime** (Model A), wraps the *unchanged* bash engine
  (`argo_anywhere.sh`), and adds a scrollback-style local web UI that can
  connect (incl. Duo), monitor, configure, and run clients.
- **Status:** the make-or-break gate (**P1 — Duo/connect driven from a browser
  terminal**) is **PASSED**. Everything downstream is lower-risk, conventional
  engineering.
- **Branch:** `feat/python-package-webui` (local only, not pushed), forked from
  clean `main` at `2348810` (which includes the D-024 verb split — our
  precondition).
- **Next phase:** P0 — build the real package skeleton, absorbing the proven
  spike.

---

## What is proven (P1 — cleared)

Spike lives in `spike/` (isolated; venv git-ignored). Architecture:

```
browser (xterm.js, vendored, NO npm)
   │  WebSocket (raw bytes = keystrokes; JSON control frames = resize/signal)
   ▼
FastAPI /ws  ──►  ptyprocess PTY  ──►  bash argo_anywhere.sh connect
```

- **P1a (plumbing, headless + browser, no ANL):** PASS. Prompt-out /
  keystroke-in / computed-output-back / resize→PTY (40×120 via TIOCGWINSZ) /
  clean-exit / **silent no-echo password read** (the Duo/ssh mechanism, via a
  `read -s` test) / host-header DNS-rebinding guard. See `spike/RESULTS.md`.
- **P1b (real engine + ANL, browser terminal):** PASS (2026-07-09). Drove real
  `argo_anywhere.sh connect` from the browser: interactive node picker accepted
  keystrokes; SSH master step reached; **full Unicode box-drawing status
  summary rendered flawlessly**; clean exit 0.

**Commits on the branch:**
- `0febee2` — P1a spike (server + static + smoke tests + hardening)
- `6fd5810` — P1b results (RESULTS.md)
- (this handoff will be the next commit)

---

## QUEUED TASK 1 (do this first next session): cold-Duo observation in the browser

P1b **reused an existing healthy SSH mux master**, so no *fresh* Duo prompt
fired. The cold-master Duo path is byte-for-byte the same PTY route already
proven by the P1a `read -s` silent-read test, so this is **de-risked, not
gating** — but worth one real observation before promotion.

**Requires you at the keyboard** (complete Duo yourself). **CSPO SAFETY: exactly
ONE cold attempt. If Duo fails or anything errors, STOP and diagnose — do NOT
retry** (the engine's SSH-fail lock / exponential backoff, D-012, tracks
failures and can lead to an IP block).

### Exact steps

1. **Verify clean state** (no active SSH-fail lock):
   ```sh
   for f in ssh-fail-lock ssh-fail-lock-count; do
     [ -f ~/.config/argo_anywhere/$f ] && echo "$f: $(cat ~/.config/argo_anywhere/$f)" || echo "$f: absent (good)"
   done
   ```

2. **Tear down the current tunnel + mux master** (clean teardowns — NOT failed
   attempts; they don't trip the lock):
   ```sh
   cd /Users/attia/AHMED_HOME/Research/Projects/Software/argo-anywhere
   bash argo_anywhere.sh stop
   ssh -O exit -S ~/.ssh/sockets/argo-anywhere-aattia-compute-01.cels.anl.gov-22 placeholder 2>/dev/null || true
   ```
   Confirm the listener on :64742 is gone and the socket file is gone:
   ```sh
   lsof -nP -iTCP:64742 -sTCP:LISTEN 2>/dev/null || echo "listener gone"
   ls ~/.ssh/sockets/ | grep -i argo || echo "socket gone"
   ```

3. **Start the spike server against the real engine:**
   ```sh
   SPIKE_CMD='bash /Users/attia/AHMED_HOME/Research/Projects/Software/argo-anywhere/argo_anywhere.sh connect' \
     spike/.venv/bin/python spike/server.py
   ```

4. **In the browser** (`http://127.0.0.1:8799`, hard-refresh): pick node `1`,
   watch for the **cold Duo prompt**, and complete it *in the browser terminal*
   (passcode / push). Record:
   - Did Duo render legibly in the browser terminal?
   - Could you complete it entirely in-browser (no native terminal needed)?
   - Did it reach ALL GREEN?
   - Any misdraw / input lag / lost keystrokes?

5. **Afterward**, re-check the ssh-fail lock (step 1) regardless of outcome.

6. Record the result in `spike/RESULTS.md` (there's a "Residual to exercise"
   note to update) and mark this task done.

---

## IMPORTANT: environment-state clarification (avoid confusion)

There are **three** copies of the script on this machine. This is expected and
was NOT caused by the spike work:

| Location | Origin |
|:--|:--|
| `./argo_anywhere.sh` (repo working tree) | dev copy — **run this while developing** (`bash argo_anywhere.sh ...`) |
| `~/.argo_anywhere/bin/argo_anywhere.sh` | created by the **user's own D-025 `install` lifecycle test** at 2026-07-09 13:33 (identical bytes to the source at that time) |
| `~/.argo_anywhere/argo_anywhere.sh.bak.20260624-*` | old June D-022/D-023 self-update backup (pre-existing) |

`~/.argo_anywhere/` also has `bin/{install,uninstall}`, `env`, and
`manifest.json` — all from that D-025 install test. **The spike never touched
`~/.argo_anywhere/`**; it only wrote under `spike/` and ran read-only `status`.
Running from repo source is correct for development.

This three-copy situation is the concrete form of the "two-paths problem" the
Model A design resolves by elimination: once packaged, the package owns the
runtime and `~/.argo_anywhere/` demotes to state-only (port cache, sockets,
locks) — no competing script homes.

---

## How to re-run the spike (reference)

Deps are `uv`-managed in `spike/.venv` (git-ignored). If the venv is missing:
```sh
cd /Users/attia/AHMED_HOME/Research/Projects/Software/argo-anywhere
uv venv spike/.venv --python 3.13
uv pip install --python spike/.venv/bin/python fastapi "uvicorn[standard]" ptyprocess websockets
```

Smoke tests (no ANL, no SSH — safe to run anytime):
```sh
spike/.venv/bin/python spike/smoke_test.py          # plumbing round-trip
spike/.venv/bin/python spike/smoke_test_resize.py   # resize -> PTY dims
```

Browser eyeball (safe stand-ins — use a profile-free shell so you test the
terminal, not personal dotfiles):
```sh
SPIKE_CMD='bash --norc --noprofile -i' spike/.venv/bin/python spike/server.py
# silent no-echo read (Duo/ssh mechanism), fully local:
SPIKE_CMD='bash --norc --noprofile -c '\''echo -n "Enter secret: "; read -s x; echo; echo GOT=[$x]'\''' \
  spike/.venv/bin/python spike/server.py
```
Note: `bash -il` surfaces the user's login profile (`set -o vi` + env dump) and
misleads — not a spike bug. `ssh localhost` → "connection refused" = no local
sshd — also not a spike bug.

---

## NEXT PHASE: P0 — package skeleton + driver

Target layout (scrollback-parallel; scrollback is the reference for the web
layer, launchers, safety patterns — https://github.com/a-attia/scrollback):

```
src/argo_anywhere/
  engine/argo_anywhere.sh        # vendored VERBATIM as package-data
  driver.py                      # two-lane subprocess/PTY driver
  cli.py                         # `argo-anywhere` console-script (thin)
  web/app.py                     # FastAPI, 127.0.0.1, host-guard
  web/pty_bridge.py              # WebSocket <-> ptyprocess (lift from spike/server.py)
  web/static/                    # vendored xterm.js + css + fit (lift from spike/static/)
  launchers.py                   # pywebview / native window (from scrollback)
pyproject.toml                   # extras: [web], [all]; console_scripts
```

### The two-lane driver (the heart of P0)

The engine's interactive prompts split into two classes (full inventory below):

- **Lane 1 — captured/managed subprocess** for everything pre-answerable via
  flags/env (`-y`, `--auto-port`, `--user/--node/--port`, `--scope`,
  `ARGO_ANYWHERE_*`). These verbs *return* — safe to run and await.
- **Lane 2 — PTY streamed to the browser terminal** for Duo + the long-lived
  monitor loop + any flow hitting the 3 un-pre-answerable prompts below.

### The 3 prompts with NO non-interactive flag (MUST route through Lane 2)

From the earlier code inventory:

| Prompt | Options | Function / line | Notes |
|:--|:--|:--|:--|
| Port migrate | `[m/u/k/a]` | `prompt_port_choice` (~`argo_anywhere.sh:1680/1696`) | non-TTY silently defaults to `keep` |
| Config file conflict | `[k/b/d/m/a]` | `handle_config_file` (~`:2355/2400`) | non-TTY silently defaults to `keep` |
| Scope conflict | `[k/s/a]` | `prompt_scope_switch` (~`:2490/2502`) | `--scope` picks scope up front but a *detected conflict* still prompts |

Everything else (username, node, cli-tool picker, run/server/stop/clean/
update/list-models confirmations) HAS a flag/env pre-answer — see the full
table via the inventory (regenerate with an explore agent over
`argo_anywhere.sh` if needed).

### Foreground-blocking flows (Lane 2, managed background processes)

- `monitor_tunnel_loop` (~`argo_anywhere.sh:4295`): infinite reconnect/health
  loop; owned by `mode_tunnel`/`mode_client`/`mode_connect`. Health = `/health`,
  NOT the fg pid (design decision D-003).
- `mode_run` ends with `exec "$bin"` (~`:5913`) — foreground client session.

### Self-invocation (keep working under packaging)

- `remote_bootstrap` scp's `$self` to the node (~`:4026`) then ssh-re-execs it
  as `server` (~`:4050`). When packaged, `$self` = the vendored engine copy; the
  node still receives a plain `.sh`. Compute nodes have Python too but keep
  shipping the plain `.sh` (simpler).

---

## Model-A decisions to RECORD in PLAN.md before P0 code grows

Per D-014 append-only convention, draft three `D-0NN` entries (numbering: next
free after the highest existing D-0NN in PLAN.md):

1. **Supersede D-001** — adopt Python-package-as-runtime (Model A). Rationale:
   Python/pip are mandatory + universal in the target ANL scientific community
   (nullifies D-001's stated "requires Python install" objection); the web UI
   requires a persistent Python server that drives the engine.
2. **Clean-break web-UI major release** — no in-place migration, no back-compat
   forwarder. Users uninstall the old version, install the new one (n≈dozens,
   coordinated). The old version's mature `uninstall`/`clean` is the sanctioned
   off-ramp. Keep a `--print-script` escape hatch to re-emit the raw `.sh`
   (preserves D-001's inspect-and-fork spirit).
3. **Rename `argo_anywhere.sh` → `argo-anywhere.sh`** (uniform hyphenation,
   matches repo + package name). Rides the discontinuity; no forwarder/alias by
   design.

**Open question for the user:** draft these 3 decision entries FIRST (recorded
rationale before code), or alongside P0? (User leaned toward "first" in the
planning discussion.)

---

## Phasing recap (P1 done; P0 next)

- **P1** — Duo/connect in browser terminal — **DONE (PASS)**.
- **P0** — package skeleton + Lane-1 driver + `argo-anywhere` console script.
- **P2** — dashboard + monitor (process registry, `/health` polling, "show all
  tunnels" view — new capability; D-006 single-instance has no such view today).
- **P3** — configure/run in UI (conflict-escalation to PTY lane; run-client-in-
  terminal; list-models/list-tools/status info views).
- **P4** — packaging polish ([web]/[all] extras, pywebview native window from
  scrollback, `--print-script`, install-launcher/uninstall parity,
  `docs/UPGRADING.md` hard-cutover section).
- **P5 (optional, upstream-able, not prerequisite)** — add explicit bash flags
  for the 3 prompts (`--on-port-mismatch` / `--on-config-conflict` /
  `--on-scope-conflict`) so those flows can run headless in Lane 1 instead of
  escalating to the terminal.

---

## Key risks to keep validating

1. `ptyprocess` ↔ SSH `ControlMaster` interaction (D-003: master can outlive the
   fg ssh; server must adopt/monitor via `/health`).
2. PTY lifecycle across server restart (managed `connect` PTY vs. mux socket
   surviving independently — reconciliation needed).
3. CSPO discipline in ALL automated testing: never hammer the real SSH path;
   use local stand-ins for plumbing; one clean attempt for real connects.

---

*Created 2026-07-09 by Claude (OpenCode session) as the handoff for a separate
execution session. Branch `feat/python-package-webui` @ `6fd5810` + this file.*
