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

### Residual to exercise once before promotion — DONE (PASS, 2026-07-10)
The truly **cold** `connect` was exercised at the keyboard: after `stop` tore
down the listener *and* the mux master (socket gone, no lingering ssh procs,
fail-lock clean), a fresh `connect` was driven entirely from the browser
terminal. The **live cold Duo prompt fired and rendered legibly** (transcript
redacted — username/host/device masked):

```
(<user>@<jump-host>) Duo two-factor login for <user>
Enter a passcode or select one of the following options:
1. Duo Push to XXX-XXX-XXXX
Passcode or option (1-1): 1
```

- Duo option `1` (Push) typed **in-browser**; accepted; master came ready ✓
- No native terminal needed at any point ✓
- Bootstrap ran; reached **ALL GREEN** (44 models); box-drawing summary drew
  correctly ✓
- No misdraw / input lag / lost keystrokes reported ✓
- **Fail-lock stayed absent** before and after (clean single attempt; CSPO
  one-attempt discipline held — no retries) ✓

Scope note: the SSH **master** was cold (this is what the observation targeted —
a *fresh* Duo challenge), but the node's argo-proxy **server** process was
reused (existing pid, identity-verified). That is expected and orthogonal; the
cold-*master* Duo path is what P1b's reuse-run had left unobserved.

## Verdict

**Gate cleared.** The in-UI-terminal workflow is solid enough to build the real
package on. Proceed to P0 (package skeleton + driver) with the PTY web
terminal as a proven component.
