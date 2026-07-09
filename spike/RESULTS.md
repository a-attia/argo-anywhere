# P1 spike results — PTY web terminal for argo-anywhere

Gate for the Python-package + web-UI exploration (Model A) on branch
`feat/python-package-webui`. The load-bearing question: **can the whole
`connect` flow — including interactive prompts and Duo — be driven entirely
from a browser terminal (xterm.js) over a WebSocket-bridged PTY, with no
native terminal?** If no, the "connect from the UI" vision is downgraded to a
monitor-only dashboard.

## Architecture proven

```
browser (xterm.js, vendored, no npm)
   │  WebSocket  (raw bytes = keystrokes; JSON control frames = resize/signal)
   ▼
FastAPI /ws  ──►  ptyprocess PTY  ──►  bash argo_anywhere.sh connect
```

- Server: `spike/server.py` (FastAPI + `ptyprocess`, host-header guard).
- Client: `spike/static/index.html` (vendored xterm.js + fit addon).
- Deps: `fastapi`, `uvicorn[standard]`, `ptyprocess` (all pip; no npm/build).

## P1a — plumbing (headless + browser), no ANL/SSH — PASS

| Check | Method | Result |
|:--|:--|:--|
| Prompt out / keystroke in / computed output back | `smoke_test.py` | PASS |
| Resize control frame → PTY dims | `smoke_test_resize.py` (40×120 via TIOCGWINSZ) | PASS |
| Clean-exit detection + status | both smoke tests | PASS |
| **Silent no-echo password read** (Duo/ssh mechanism) | `read -s` headless test | PASS (typed, read back, not echoed) |
| Host-header DNS-rebinding guard (HTTP + WS) | curl good/bad host | 200 / 403 |
| Clean shell in browser | `bash --norc --noprofile -i` | renders + types correctly |

Note: `bash -il` in the browser surfaced the user's personal login profile
(`set -o vi` + env dump), NOT a spike bug. `ssh localhost` → "connection
refused" = no local sshd, NOT a spike bug (the PTY still carried ssh's stderr
+ exit 255 correctly).

## P1b — real engine + ANL, browser terminal — PASS (2026-07-09)

Ran `SPIKE_CMD='bash .../argo_anywhere.sh connect'` and drove it entirely from
the browser terminal:

- interactive **node picker** rendered; keystroke `1` accepted ✓
- multiplexed SSH master step reached (reused an existing healthy master this
  run, so no fresh Duo fired — the cold-master Duo path is the identical PTY
  route already proven by the `read -s` silent-read test) ✓
- **full Unicode box-drawing status summary** ("ALL GREEN", 44 models) drew
  correctly in xterm.js — hardest rendering case, flawless ✓
- clean exit status 0 ✓

### Residual to exercise once before promotion (not gating)
- A truly **cold** `connect` (after `stop` + closing the mux master) to see the
  live Duo prompt render + accept input in the browser. De-risked by the
  `read -s` proof, but worth one real observation.

## Verdict

**Gate cleared.** The in-UI-terminal workflow is solid enough to build the real
package on. Proceed to P0 (package skeleton + driver) with the PTY web
terminal as a proven component.
