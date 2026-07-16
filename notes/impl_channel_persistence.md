# Implementation plan -- channel persistence (CLI + web UI)

**Status**: **designing — for discussion, not scheduled.** No code, no
locked decisions. Written to give the persistence conversation a shared
factual baseline; the open questions in §6 are the point of the doc.
**Owner**: Ahmed Attia. **Last updated**: 2026-07-16.
**Target repo**: <https://github.com/a-attia/argo-anywhere>.
**Linked PLAN.md sections**: D-003 (mux master owns the forward), D-012
(SSH failure tracker), D-024 (connect/configure/run split), D-031
(web-UI Channel + Utility panels). Earns a new **D-034** if any of §5
ships.

## Contents

- [1. Purpose](#1-purpose)
- [2. What users are actually asking](#2-what-users-are-actually-asking)
- [3. Current behavior: the three cases](#3-current-behavior-the-three-cases)
- [4. The ceiling, and why it is where it is](#4-the-ceiling-and-why-it-is-where-it-is)
- [5. Options](#5-options)
- [6. Open questions](#6-open-questions)
- [7. Impacts + blast radius](#7-impacts--blast-radius)
- [8. Risks](#8-risks)
- [9. Action items](#9-action-items)

## 1. Purpose

Decide what "the connection persists" should mean for argo-anywhere, and
how much of it is worth building — across **both** the CLI channel and
the web UI's Channel panel, which today have different lifetimes and
must not diverge further.

This is explicitly not a hasty fix. Two of the four options in §5 change
the shape of what `connect` *is*, which touches D-024's three-level
model, the web UI's single-Channel discipline, and the D-012 failure
tracker. The doc exists so that discussion happens before code.

## 2. What users are actually asking

Field reports (relayed 2026-07-16) are two questions that sound like one:

1. "Can the connection persist over the same network when I close my
   screen?"
2. "…and what about when the network itself changes?"

**"Close my screen" is ambiguous and the ambiguity is load-bearing** —
it could mean the laptop lid (sleep), the terminal window, or a literal
GNU `screen` session. Those have different answers, and two of them have
*opposite* answers. Pin this down before building anything (§6 Q1).

Underneath both questions is very likely a third, unasked one: **"do I
lose my argo-proxy?"** The answer is no, never — see §3. It costs
nothing to say so, and it may be most of what they want to hear.

## 3. Current behavior: the three cases

The three layers have three different lifetimes. Conflating them is what
makes this topic confusing.

| Layer | Lives where | Survives terminal close? | Survives sleep? | Survives network change? |
|:--|:--|:--|:--|:--|
| `argo-proxy` | compute node, inside `screen -dmS argovproxy` | **yes** | **yes** | **yes** |
| SSH mux master | laptop, `~/.ssh/sockets/` | **yes** (1h default) | no (~60s after wake) | no |
| `-L` tunnel | laptop, fg ssh or owned by master | no (EXIT trap) | no | no |

### 3.1 The server never dies

`argo-proxy` is launched into a detached `screen` session
(`SCREEN_SESSION="argovproxy"`, `argo-anywhere.sh:346`; launch at
`:7459`, with tmux and `nohup` fallbacks). It is not a child of anything
on the laptop. It survives terminal close, sleep, network change, and
laptop reboot. Losing the tunnel never means losing the proxy — it means
losing a few seconds of `ssh -L`.

This also means **reconnect is cheap**: a post-sleep `connect` reuses the
running proxy rather than re-bootstrapping the venv.

### 3.2 Closing the terminal: already better than users think

`cleanup_local` (the `EXIT INT TERM` trap, `argo-anywhere.sh`) kills the
monitor and the foreground tunnel — but **deliberately leaves the mux
master alive**, and says so in its exit summary:

```text
What's still alive (intentional; left for fast restart):
  * SSH multiplex master to <user>@<node>
      (keeps Duo state warm; next 'client' run skips the Duo prompt)
  * Remote argo-proxy on <node>:<port>
      (still serving; any laptop with a tunnel here keeps working)
```

So on the same network, closing the terminal costs a re-run of `connect`
and **no Duo prompt**. `ARGO_ANYWHERE_CONTROL_PERSIST` (default `3600`,
`SSH_MUX_PERSIST_DEFAULT` at `argo-anywhere.sh:2044`) tunes the window;
`=yes` makes the master persist indefinitely.

`monitor_tunnel_loop` already reconnects the forward transparently when
the foreground ssh dies while the master lives (per D-003: the master
owns the forward, so `/health` — not the pid — is the truth).

**Reading**: this case is ~solved and under-communicated. If users are
complaining here, the gap is documentation and defaults, not capability.

### 3.3 Sleep and network change: the channel is gone

The mux master carries `ServerAliveInterval=15 -o ServerAliveCountMax=4`
(~60s to death, `argo-anywhere.sh:2408`); the tunnel carries
`ServerAliveInterval=30 -o ServerAliveCountMax=3 -o
ExitOnForwardFailure=yes` (`:4959`). The comment at `:2401` states the
intent plainly:

> if the network stalls after auth (laptop resumes, flaky VPN, etc.) the
> master must die on its own so the script fails cleanly rather than
> hanging forever and forcing a manual Ctrl-C + restart (which resets the
> in-memory failure counter and risks more auth attempts against CSPO's
> rate limiter).

So the death is **designed**, and it is entangled with D-012. Loosening
the keepalives trades one Duo prompt for a class of hangs the project
already decided against, and weakens a CSPO-facing defense. Any proposal
that touches these numbers must argue against that comment, not around it.

## 4. The ceiling, and why it is where it is

**A network change cannot be survived.** An SSH tunnel is TCP; TCP is
bound to a 4-tuple containing the client IP. Change networks and the
sockets are dead — this is not a missing `ssh -o`, and no amount of
keepalive tuning reaches it. The usual suggestions fail for specific
reasons worth recording so they don't get re-proposed:

| Idea | Why it doesn't work here |
|:--|:--|
| `mosh` | Roams over UDP, but has **no port forwarding** — it is an interactive shell, not a tunnel. Cannot carry `-L`. |
| `autossh` | Reconnects, but each reconnect is a fresh SSH auth → **a fresh Duo prompt**. Trades one prompt for many, and feeds D-012's failure tracker. |
| Longer `ServerAlive*` | Doesn't help: the sockets are already dead, not stalled. Only delays discovery. |
| VPN / WireGuard | Would genuinely fix roaming, but it's ANL infrastructure, not ours to ship. |

**Therefore: reconnect + exactly one Duo prompt is the floor for sleep
and network change.** The honest framing for users is not "we'll make it
persist" but "you'll lose the tunnel, not the proxy, and getting back
costs one Duo."

The corollary is that the achievable work is about **making recovery
cheap and obvious**, not about persistence. §5 is scoped accordingly.

## 5. Options

Ordered by cost. Not mutually exclusive; (a) is worth doing regardless.

### (a) Document the three cases — cheap, do first

Write §3's table into `README.md` (near
[Tunnel monitoring and reconnect](../README.md#tunnel-monitoring-and-reconnect))
and/or `docs/LIMITATIONS.md`. Says plainly: the proxy always survives;
same-network restart is Duo-free; sleep/network-change costs one Duo and
that is a property of TCP + Duo, not a bug.

Likely resolves most of the complaint at ~zero risk. **Recommended
independent of everything below.**

### (b) Surface `ARGO_ANYWHERE_CONTROL_PERSIST`, reconsider the default

The knob exists and is nearly invisible (documented in a code comment at
`argo-anywhere.sh:2039`, not in `README.md`). `=yes` gives indefinite
Duo-free restarts on the same network.

Open: is `3600` the right default? Raising it widens the window where a
stale socket lingers after a network change; the socket path is keyed on
`%r-%h-%p`, so a stale master for the same user@node:22 is exactly what a
returning laptop would try to reuse. Needs thought about failure modes,
not just a bigger number (§6 Q3).

### (c) A detached channel mode (`connect --detach`)

Closes the terminal-close gap properly for CLI users: the channel would
survive its launching terminal without the user knowing about `tmux`.
Today the equivalent is "run `connect` inside your own tmux/screen",
which works and is undocumented.

This is where it stops being small. `connect` currently *is* a
foreground process holding a monitor; detaching it means deciding who
owns the monitor, where its output goes, how `status` finds it, how
`stop` addresses it, and what happens when two detached channels exist.
It touches D-024's three-level model directly.

### (d) Auto-reconnect on wake

Detect a dead channel and offer (or perform) re-open. Costs one Duo — the
floor from §4. The interesting question is prompt vs. automatic:
automatic re-auth on wake means Duo pushes the user didn't ask for, which
is both an annoyance and a D-012 / CSPO-rate-limiter concern. Prompted is
almost certainly right, which makes this "a better error message with a
keypress" rather than true persistence.

## 6. Open questions

These are the discussion agenda. None are decided.

**Q1. What does "close my screen" mean?** Lid, terminal window, or GNU
`screen`? Terminal-close is ~solved (§3.2); lid-close is capped at one
Duo (§4). Answering this may collapse the whole request into option (a).
*Ask the users before building.*

**Q2. Is the real complaint the Duo prompt, or the lost session?** If
Duo: the ceiling is one prompt and we should say so. If session state:
that's an argo-proxy / tool-session question, not a transport one, and
this doc is aimed at the wrong layer.

**Q3. Should `ARGO_ANYWHERE_CONTROL_PERSIST` default change?** Requires
reasoning about stale-master reuse after a network change, not just
comfort.

**Q4. Does a detached CLI channel belong in the D-024 model at all?**
`connect` is defined as the foreground channel-holder. A detached channel
is arguably a *fourth* level, or an argument that the web UI is already
the answer for users who want one.

**Q5. How do the CLI and web UI channels converge?** ← the one the
maintainer flagged. See §7.1. This is the question most likely to make
the work expensive, and it should be answered *before* (c) or (d), not
after.

**Q6. Does any of this weaken the D-012 / CSPO posture?** Every option
that re-authenticates automatically increases auth attempts against a
rate limiter the project has deliberately defended. D-012's author (this
project) should be satisfied before (d).

## 7. Impacts + blast radius

### 7.1 The CLI ↔ web UI asymmetry (the sync problem)

**The two channels do not have the same lifetime today, and any
persistence work must move both or explicitly justify not doing so.**

What's established (`src/argo_anywhere/`):

- The web UI's Channel panel is already persistence-aware: closing the
  browser tab does **not** kill the channel
  (`terminate_on_close=not managed.owns_channel`, `web/app.py:923`;
  ownership from `driver.owns_channel`, `web/registry.py:89`).
- Engine processes are spawned with `start_new_session=True`
  (`driver.py:225`), so the PTY child is its own session leader and does
  **not** receive the server's process-group signals.

What needs verifying before it is stated as fact (§9 item 2):

- **Does the web-UI channel survive the web server exiting?**
  `start_new_session=True` detaches it from the server's process group,
  but the PTY *master* fd closes when the server process dies, which
  should HUP the slave and take the engine down — running its
  `cleanup_local` trap and tearing down the tunnel. If that's what
  happens, then "close the tab" persists but "quit the app" does not,
  which is a subtle distinction users will absolutely hit and which we
  have never tested. **This is the highest-value experiment in the doc**
  and it needs no ANL infra to run (a fake long-lived child suffices).

The asymmetry to resolve: the browser tab is *not* the channel's owner,
but the web server *is*. For the CLI, the terminal *is* the owner. A
coherent story would make "the thing that owns the channel" the same
concept in both, which is essentially what option (c) proposes — hence
Q5 gating (c).

### 7.2 Coupling surfaces this would touch

Per AGENTS.md's "Engine ↔ web-UI coupling rules", a channel-lifetime
change is not local:

- **Engine**: `cleanup_local`, `monitor_tunnel_loop`, `ssh_mux_args`,
  `mode_connect` / `mode_stop` / `mode_status`.
- **Web**: `SessionRegistry` named slots (`channel` / `utility`),
  `pty_bridge.run_pty_bridge`, the multi-instance `/healthz` guard
  (D-031) — a detached channel that outlives *every* instance breaks the
  assumption that a channel belongs to an in-process registry.
- **Both**: `channel_is_up` is a localhost `/health` probe with no notion
  of *who* owns the channel. A detached-channel world needs that concept,
  and D-031's single-Channel discipline is currently enforced per-instance
  (`SessionRegistry.panel_alive("channel")`) and explicitly cannot span
  instances.

### 7.3 What would *not* be affected

`argo-proxy` and the on-node bootstrap. Every option here is laptop-side.
The server story is already correct and should not be touched.

## 8. Risks

| Risk | Note |
|:--|:--|
| Promising "persistence" and delivering "one Duo prompt" | The word means TCP survival to users. §4 is the honest ceiling; lead with it in any reply to them. |
| Weakening the CSPO defense to chase convenience | D-012 + the `:2401` comment exist for a reason. Any keepalive/auto-reauth change argues against them explicitly or not at all. |
| Duo-push spam from auto-reconnect | The `autossh` failure mode (§4) re-entering through the back door of option (d). |
| Detached channels becoming un-addressable | `status` / `stop` / `clean` assume a single foreground owner. Orphaned detached channels are a support burden, and `clean`'s tiering (AGENTS.md) would need a story. |
| CLI and web UI diverging further | Q5. Shipping (c) for the CLI without a web answer bakes the asymmetry in permanently. |

## 9. Action items

None are "build". This doc is input to a conversation.

1. **Ask the users what "close my screen" means** (Q1) — *pending* —
   Ahmed. Cheapest possible resolution; may collapse this to option (a).
2. **Run the web-server-exit experiment** (§7.1) — *pending*. No ANL
   infra needed; answers whether "quit the app" kills the channel. Do
   this before any design discussion, since it determines whether the
   asymmetry is real.
3. **Decide option (a)** — *pending* — Ahmed. Recommended regardless of
   the rest; cheap and probably sufficient.
4. **Hold the Q5 (CLI ↔ web UI convergence) discussion** — *pending* —
   Ahmed. Gates (c) and (d).
5. **Record as D-034 in PLAN.md** if anything beyond (a) ships —
   *pending*.

---

*Created 2026-07-16 by Ahmed Attia (with AI assistance from Claude per
[`CONTRIBUTORS.md`](../CONTRIBUTORS.md)). Prompted by 2026-07-16 field
questions about connection persistence across screen-close and network
change. Facts in §3 were read from the engine + web layer on that date
and cite `file:line`; re-verify before relying on them if the transport
code has moved since.*
