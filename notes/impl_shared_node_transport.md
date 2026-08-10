# Implementation plan — transport on a shared compute node

**Status**: **DRAFT — for discussion; not executed.** No code, no locked
decisions. **Owner**: Ahmed Attia. **Last updated**: 2026-08-10.
**Linked PLAN.md sections**: D-003 (mux master owns the forward), D-020
(port as transport-layer state), D-024 (connect/configure/run).
**Would earn**: the next free decision number — **D-034** as of
2026-08-10. Two other `designing`-status notes
([`impl_command_echo.md`](impl_command_echo.md),
[`impl_channel_persistence.md`](impl_channel_persistence.md)) still name
D-033/D-034 in their headers; D-033 was taken by the 2026-07-22
ControlPersist decision, so all three are contended. Assign at execution
time, not now.

This note works out how `argo-anywhere` should establish its transport to
a compute node that it shares with other users — including users who are
not running `argo-anywhere`. It was written after a 2026-08-10 field
incident in which the tool reported `ALL GREEN` while routing the
maintainer's traffic through a stranger's `argo-proxy`. The incident is
not a single bug: it is five independent defects that happen to compose,
sitting on top of one structural assumption that stopped holding when the
tool got popular.

Nothing here is scheduled. The purpose is to establish a shared factual
baseline, force the design choice (Unix socket vs. hardened TCP), and fix
an execution order — before any code moves.

> **Revision note (second pass, 2026-08-10).** The first draft named
> three defects and presented the field evidence as a single timeline.
> A review pass found that timeline to be physically inconsistent
> (§[1.2](#12-two-runs-not-one)), which in turn surfaced two further
> defects — an identity-blind *post-launch* liveness check
> (§[2.4](#24-defect-4--the-post-launch-liveness-check-is-identity-blind))
> and the fact that H5, the one check that gets identity right, is
> structurally unreachable on a warm reconnect
> (§[2.5](#25-defect-5--h5-never-runs-on-a-warm-reconnect)). The
> recommended sequencing in §[6](#6-recommended-sequencing) is new, and
> it demotes the bind test relative to the first draft's ordering for
> a TOCTOU reason spelled out there.
>
> **Revision note (third pass, 2026-08-10).** Q2 was answered by a live
> read-only probe of `compute-386-01` over the maintainer's warm
> channel. The result inverted §[4.3](#43-where-the-socket-lives--measured-not-assumed)'s
> assumed ranking of socket locations — `/tmp` is the primary,
> `/run/user` is gated on lingering, and `~/.argo_anywhere/` is
> **disqualified** because `$HOME` is NFS shared across every compute
> node. That probe also surfaced a scoping error unrelated to
> transport (Q10: the argo-proxy config is shared across nodes too) and
> made explicit that CELS is only one target class
> (§[4.4](#44-the-target-population-is-heterogeneous-cels-is-not-the-only-target);
> Aurora has a different storage stack and invocation path), so the
> socket location must be resolved at runtime rather than hard-coded.

---

## Table of contents

- [1. The incident](#1-the-incident)
- [2. Root cause: one structural assumption, five defects](#2-root-cause-one-structural-assumption-five-defects)
- [3. Why the obvious fix is not a fix](#3-why-the-obvious-fix-is-not-a-fix)
- [4. Option A — Unix-socket transport](#4-option-a--unix-socket-transport)
- [5. Option B — hardened TCP; and the fallback ladder](#5-option-b--hardened-tcp-and-the-fallback-ladder)
- [6. Recommended sequencing](#6-recommended-sequencing)
- [7. Blast radius](#7-blast-radius)
- [8. What was verified by execution](#8-what-was-verified-by-execution)
- [9. Open questions](#9-open-questions)

---

## 1. The incident

### 1.1 The three symptoms

On 2026-08-10 a routine `argo-anywhere connect` produced three symptoms
that at first looked unrelated.

**Symptom 1 — argo-proxy stopped at a prompt.** Inspecting the `screen`
session on the node showed `argo-proxy` halted at:

```text
WARNING | [config] Warning: Port 64742 is already in use.
Enter port [56617] [Y/n/number]:
```

**Symptom 2 — the laptop reported success anyway.** `status` printed
`ALL GREEN — tunnel up, proxy healthy, N model(s)`.

**Symptom 3 — there was no `screen` session on the node.** `screen -ls`
returned `No Sockets found`.

The evidence (collected on the maintainer's laptop and on the node,
2026-08-10):

| Probe | Result | What it establishes |
|:---|:---|:---|
| `ls ~/.ssh/sockets/` | one socket, for `compute-01.cels.anl.gov` | single mux master; no ambiguity about which node |
| `ps -o command= -p <listener>` | `ssh: /…/sockets/argo-anywhere-…` | the listener is the **ControlMaster**, holding the forward (D-003) |
| `lsof -nPi :64742 -sTCP:LISTEN` (laptop) | `ssh`, owned by the user | the local listener is genuinely our tunnel, not a stray local proxy |
| `command -v lsof` (node) | `/usr/bin/lsof` | **falsifies** the "lsof is missing on the node" hypothesis |
| `ss -ltnp 'sport = :64742'` (node) | `LISTEN … 127.0.0.1:64742`, **Process column empty** | the port is held, by a process the user cannot attribute |
| `pgrep -af argo-proxy` (node) | **nine** `argo-proxy` processes, all argo-anywhere-launched, **none** owned by the user | the node is a busy shared host; we are one tenant of many |
| `screen -ls` (node) | none | our own proxy never started |

`compute-01.cels.anl.gov` is the DNS alias; `compute-386-01` is the
physical host. The engine documents exactly this split at
`src/argo_anywhere/engine/argo-anywhere.sh:727`, so the node names are
consistent and "wrong node" is **not** part of this story. (The same
comment block at `:804` records that the alias round-robins across
several physical hosts — an independent hazard, out of scope here.)

**Conclusion.** The tunnel forwarded into a listener on
`127.0.0.1:64742` on the node that was not ours. It answered `/health`
and `/v1/models`, so the summary box went green. Our own `argo-proxy`
was not running, so there was no `screen` session.

### 1.2 Two runs, not one

The three symptoms **cannot all hold at one instant**. Symptom 1
requires a live `screen` session to attach to; Symptom 3 says there is
none. They come from different invocations, and the first draft of this
note presented them as one timeline.

The distinction is not pedantry: **the run boundary determines which
defect is live.** Trace both branches against `ensure_or_reuse_tunnel`
(`:5744`):

**Branch A — bootstrap ran (the run that produced Symptom 1).**
`remote_bootstrap` (`:4830`) dies if the remote `server` exits non-zero,
so for anything to go green `mode_server` must have *succeeded*. It
does: the post-launch wait at `:7557` polls
`curl 127.0.0.1:$PORT/health`, and the **stranger's** proxy answers it
immediately while ours sits at the port prompt. `mode_server` prints
`argo-proxy is listening on 127.0.0.1:64742`, returns 0, and
`open_tunnel` forwards into a process we do not own. Note what this
means: the 20s timeout described in
§[2.2](#22-defect-2--argo-proxy-prompts-inside-screen-forever) is
precisely the branch that **did not** fire. The hang was invisible
because something else answered for it.

**Branch B — bootstrap was skipped (the run that produced Symptom 3).**
With a warm mux master holding the forward, `local_tunnel_status`
classifies the local listener as `ours-healthy-mux`, and
`ensure_or_reuse_tunnel` returns 2 at `:5823` — before
`remote_bootstrap` at `:5963` is ever reached. No SSH to the node, no
`mode_server`, no `screen` session, and `status` still green off the
laptop-side probes alone.

Both branches end in the same place for the same underlying reason, so
the conclusion above stands. But the first draft's attribution — "H5
never ran because bootstrap never completed" — is only correct for
Branch B, and it misses that Branch A has its own identity gap
(§[2.4](#24-defect-4--the-post-launch-liveness-check-is-identity-blind))
while Branch B reveals a structural one
(§[2.5](#25-defect-5--h5-never-runs-on-a-warm-reconnect)).

### 1.3 Limits on the conclusion

- **The holder is unattributable.** `ss` yields no pid for another
  user's socket without root. It is *probably* one of the nine
  argo-anywhere-launched proxies, but a plain `ssh -L`, an `sshuttle`
  session, or an `argo-shim` forward chaining onward to another host
  would present identically from our side.
- **The nine visible pids do not resolve it either.** `pgrep -af
  argo-proxy` gives us pids and argv, but argo-proxy takes its port
  from `~/.config/argoproxy/config.yaml` — a file in *another user's*
  `$HOME`, which we cannot read — and the argv carries no `--port`. So
  there is no pid→port correlation available to an unprivileged
  observer, and knowing that nine proxies exist does not tell us which
  one holds `64742`.
- **Therefore the attribution consequence is bounded but real.**
  `argo-proxy` authenticates upstream using the `user:` field in *its
  own* config (default; `--username-passthrough` is off), so requests
  sent through that tunnel reached the Argo gateway under an identity
  that was not the maintainer's. Which identity cannot be determined
  from the collected evidence.
- **The exposure is symmetric, and it is live right now.** Whoever won
  the race for `64742` on that node is, by the same mechanism,
  receiving *other tenants'* traffic under their own Argo identity —
  ours included, for the duration of the incident. This is not a
  hypothetical: it is the same bug viewed from the other end, it
  affects every co-tenant still on the default port, and it is what
  makes §[9](#9-open-questions) Q7 (do we notify them?) a live
  question rather than a courtesy.

The nine co-tenant usernames are deliberately **not recorded in this
note** — this repository is public, and the usernames add nothing to the
analysis beyond "nine, none of them ours."

---

## 2. Root cause: one structural assumption, five defects

### 2.0 The structural assumption

`PROXY_PORT_DEFAULT=64742` (`argo-anywhere.sh:341`) is a single
compile-time constant shared by **every** user of the tool. TCP loopback
ports on a shared node are node-global: `127.0.0.1:64742` is one
resource for all users on that host, and the first binder owns it for
everyone.

That assumption was harmless when the tool had a handful of users spread
across nodes. On `compute-386-01` as of 2026-08-10 there are at least ten
argo-anywhere tenants. Collision on the default port is now the **normal
case**, not an edge case. The tool's own popularity broke it.

### 2.1 Defect 1 — collision detection is blind across users

Every port check in the engine uses `lsof` as its oracle:

| Check | Site | Mechanism |
|:---|:---|:---|
| client-side pre-flight | `:5574` `probe_remote_port_owner` | `ssh node 'lsof -nPi ":$PORT" -sTCP:LISTEN -t'` |
| server-side pre-launch | `:7343` `mode_server` step 5 | same, locally on the node |
| multi-port guard | `:7465` | `lsof … | awk '$3 == me'` — own processes **by construction** |
| auto-port walk | `:5619` `find_next_free_remote_port` | same, per candidate port |

An unprivileged `lsof` on Linux cannot map another user's socket to a
pid, so `-t` prints nothing and the port reads as `free`. The engine's
own comment at `:5359` anticipates "already bound by another OS user's
argo-proxy" — the *intent* was right; the *detector* cannot see the
case. There is no `ss` / `netstat` / `/proc/net/tcp` fallback anywhere
in the engine (verified: zero occurrences, 2026-08-10).

The `ss` output in §1 is a direct demonstration: run by the socket's
non-owner, it shows the socket and an **empty** Process column.

A related scoping error, surfaced by the 2026-08-10 storage probe and
recorded here because it shares the same root: **on CELS the
"one argo-proxy per user per node" constraint is really "one per user,
full stop."** `~/.config/argoproxy/config.yaml` lives on the NFS `$HOME`
that every compute node mounts identically, so it is a single shared
file, not a per-node one. Two nodes running `mode_server` concurrently
write the same config and mutate each other's `port:` line — and
`mode_server`'s port readback (`:7319`) validates against whatever the
*other* node wrote last. The same applies to `VENV_PATH='$HOME/argovenv'`
and `REMOTE_SELF`. This is independent of the transport question and is
tracked as §[9](#9-open-questions) Q10; it is noted here because
AGENTS.md's single-instance section states the per-node framing as
though it were enforced, and on a shared `$HOME` it is not.

One further consequence of the blind detector, not obvious from the
table: **`--auto-port` inherits the blindness.**
`find_next_free_remote_port` (`:5619`) walks candidate ports with the
same unprivileged `lsof -t`, so on a busy node every port a co-tenant
holds reads as free and the "next free port" it returns can be occupied
on arrival. The flag advertised as the escape hatch from a collision
(`:5907`) is the one that most confidently walks back into one.

### 2.2 Defect 2 — argo-proxy prompts, inside `screen`, forever

`argoproxy/config/validation.py::validate_port` tests availability with a
real `socket.bind(("127.0.0.1", port))` — so it sees what our `lsof`
cannot — and on failure calls `_get_user_port_choice`, which reaches a
bare `while True: input(...)` loop in `config/interactive.py` with **no
EOF handling and no timeout**. Launched as `screen -dmS argovproxy …`
(`:7531`) the process holds a pty, so it blocks indefinitely.

Meanwhile the server-side post-launch wait (`:7557`) gives up after 20s
with `argo-proxy did not start listening within 20s` and no visibility
into the actual cause. The user must attach to the session by hand to
learn anything — which is exactly how this incident was found.

Note the interaction with §[1.2](#12-two-runs-not-one) Branch A: on a
node where the port is *already* held by a working proxy, this timeout
never fires at all. The wait is satisfied by the squatter, `mode_server`
reports success, and the hung process is left behind in `screen` as
silent litter. The 20s timeout is the *benign* outcome of this defect;
the dangerous one is the timeout being satisfied by the wrong process.

Upstream already ships `_get_yes_no_input_with_timeout` in the same
module and `validate_port` does not use it. Worth an upstream issue
alongside UP-11.

### 2.3 Defect 3 — a `/health` 200 is treated as proof of ownership

`gather_summary` (`:7663`) sets its three verdict flags from three
laptop-side probes and nothing else:

| Flag | Probe |
|:---|:---|
| `SUM_LISTENER_OK` | `lsof -nPi :$PORT -sTCP:LISTEN` on the **laptop** |
| `SUM_HEALTH_OK` | `curl localhost:$PORT/health` |
| `SUM_MODELS_OK` | `curl localhost:$PORT/v1/models` |

`render_summary:7765` ANDs them into `ALL GREEN`. No SSH, no remote pid,
no `screen` check, no identity check. The verdict means *"something on
this laptop's port answers argo-proxy's HTTP API"* — nothing more.

The box then prints `Cached node : <name>` (`:7884`) straight from
`$NODE_CACHE`, a string written at last successful connect and never
re-verified, which is what makes the output *read* as a claim about a
specific node.

`channel_is_up()` (`:6465`) is the same assumption in its purest form —
three lines, one unauthenticated curl — and it gates `connect`,
`configure`, and `run`.

The engine *does* contain the correct rule, but only on the node:
`mode_server`'s H5 check (`:7395`–`:7405`) refuses to reuse a proxy
unless it **positively confirms** `cfg_user == want_user`. Sections
[2.4](#24-defect-4--the-post-launch-liveness-check-is-identity-blind)
and [2.5](#25-defect-5--h5-never-runs-on-a-warm-reconnect) are about the
two ways that rule fails to protect us anyway.

### 2.4 Defect 4 — the post-launch liveness check is identity-blind

H5 guards the **pre-launch reuse** decision: "something is already on
this port — may I adopt it?" Nothing guards the **post-launch
confirmation**: "I just started a proxy — did *mine* come up?"

That check is `:7557`:

```bash
until curl -fsS --max-time 2 "http://127.0.0.1:${PROXY_PORT}/health" >/dev/null 2>&1; do
```

It accepts any `/health` 200 on the node's loopback as proof that the
process we launched three lines earlier is serving. It never asks
whether the screen session is alive, never checks a pid, never re-runs
the `cfg_user` comparison H5 does 200 lines above it. This is Defect 3
replicated on the node side, in the one place the note's first draft
credited the engine with getting right.

It is also the direct mechanism of §[1.2](#12-two-runs-not-one) Branch
A: it is what converts "our proxy is hung at a prompt" into
`[ ok ] argo-proxy is listening on 127.0.0.1:64742` and a green summary
box on the laptop.

Cheapest correct fix: we know the launcher and the session name, so
before trusting the curl, confirm *our* process is alive — `screen -ls`
for `$SCREEN_SESSION` (or the tmux/nohup equivalent), and ideally that
the listening pid is ours. Both are local to the node and cost
nothing. This is a strictly smaller change than anything in
§[4](#4-option-a--unix-socket-transport) or
§[5](#5-option-b--hardened-tcp-and-the-fallback-ladder) and is
independent of the transport decision.

### 2.5 Defect 5 — H5 never runs on a warm reconnect

H5 lives inside `mode_server`, which runs **only** when
`remote_bootstrap` is reached. Walk `ensure_or_reuse_tunnel` (`:5744`)
and note how many paths return before that happens:

| `local_tunnel_status` verdict | Site | Outcome |
|:---|:---|:---|
| `ours-healthy-fg` | `:5810` | `return 0` — reuse; no SSH, no bootstrap |
| `ours-healthy-mux` | `:5823` | `return 2` — reuse; no SSH, no bootstrap |
| `external-healthy` | `:5827` | `return 2` — use whatever answers; no SSH, no bootstrap |
| (falls through) | `:5963` | `remote_bootstrap` → `mode_server` → H5 runs |

So H5 is not a check that "happened not to run" during this incident.
**It is reachable only on a cold bootstrap**, and every warm
reconnect — the overwhelmingly common case, and the whole point of
D-024's `connect`/`configure`/`run` split and D-033's indefinite
`ControlPersist` — skips it by construction.

The `external-healthy` row is the sharpest of the three: its comment at
`:5555`–`:5559` reasons that "from the perspective of clients we're
about to configure, the endpoint they need is reachable, so this is
fine." That is exactly the inference §[3](#3-why-the-obvious-fix-is-not-a-fix)
argues is unsound in a commons — reachability is being read as
ownership. On a laptop it is a fair assumption; on a compute node
(where `mode_client` short-circuits to on-node local mode) it is the
misattachment case in miniature.

The corollary for design: **identity has to be verified where the
tunnel is used, not only where the proxy is launched.** Any fix that
lives solely inside `mode_server` — including H5 itself, and including
the socket-mode variant of it — protects only the cold path.

---

## 3. Why the obvious fix is not a fix

The tempting change is a **per-user default port** — derive the default
deterministically from the ANL username so ten tenants stop targeting one
number. It is worth doing eventually, but it must not be sold as the fix,
for one reason:

**The node is a mixed commons.** Co-tenants use plain `ssh -L`,
`sshuttle`, `argo-shim`, and hand-rolled setups. A hash-derived port
deconflicts argo-anywhere against *itself* and collides with everyone
else exactly as blindly as `64742` did. It converts a guaranteed
collision into an incidental one.

Two further consequences of the commons framing:

- **"Read the node's `~/.config/argoproxy/config.yaml`" is not a general
  identity check.** It assumes our own layout. A co-tenant may have no
  such file, or a different one. Introspecting a *foreign* proxy to ask
  "are you mine?" cannot be made reliable.
- **The rule that does generalise is the H5 inversion**, and
  heterogeneity strengthens it: *positively confirm the listener is ours,
  or refuse — never attach on absence of evidence.* Since most listeners
  in a commons are opaque to us by design, the corollary is that an
  occupied port means **move**, never **attach**. Per
  §[2.5](#25-defect-5--h5-never-runs-on-a-warm-reconnect), applying that
  rule means applying it on the warm path too, not just at bootstrap.

Identifying ourselves therefore requires a marker **we** control, not an
inference about someone else's process.

---

## 4. Option A — Unix-socket transport

Upstream `argo-proxy` already supports listening on a Unix domain socket,
and the help text names our exact situation:

```text
--socket, -S SOCKET   Unix socket path to listen on (overrides --host/--port).
                      Permissions are set to 0700 (owner-only) for security on
                      shared hosts. Example: /run/user/$(id -u)/argo-proxy.sock
```

There is a matching config key (`socket: str = ""`, "overrides host:port
when set"), so it fits our existing YAML-writer model rather than
requiring a new argv path.

### 4.1 What it buys

| Property | Effect |
|:---|:---|
| No TCP port on the node | The contended commons stops being our problem entirely |
| `0700` in the owner's runtime dir | Cross-user attachment becomes **impossible**, not merely detected |
| Path *is* identity | Defects 3, 4 and 5 dissolve together — no marker file, no H5 comparison, no foreign introspection, and nothing for the warm path to re-verify |
| Laptop side unchanged | `ssh -L 64742:/run/user/<uid>/argo-proxy.sock user@node` — tools still talk to `localhost:64742` |

The last row matters for scope: every client config we write, every
`curl` health probe on the laptop, and the whole web UI keep working
unmodified. Only the far end of the forward changes.

The third row is the strongest argument for Option A and deserves to be
stated plainly: an OS-enforced `0700` socket in the owner's runtime
directory does not *detect* misattachment, it makes it
**unrepresentable**. Every alternative in
§[5](#5-option-b--hardened-tcp-and-the-fallback-ladder) is a detector,
and every detector can be wrong.

### 4.1a It closes a documented, currently-untreated threat-model gap

Option A is not only a collision fix. [`docs/SECURITY.md`](../docs/SECURITY.md)
(§"Things this script does NOT defend against") already names this
exact scenario as an explicit non-defense:

> **Adversarial co-tenancy of the compute node.** [...] other users on
> the same compute node who can somehow reach `127.0.0.1:<your-port>`
> [...] could send queries that argo-proxy attributes to your Argo
> account. The on-node identity check (H5 fix) defends against the
> inverse case (you accidentally attaching to their argo-proxy) but
> doesn't defend against them attaching to yours. Mitigations: pick a
> non-default port via `--port`, or just don't run on shared compute
> nodes you don't trust.

Three observations that bear on the design choice:

1. The documented mitigation ("pick a non-default port") is exactly the
   per-user-port idea §[3](#3-why-the-obvious-fix-is-not-a-fix) demotes
   — obscurity on a node where `lsof` enumerates listeners for anyone
   who asks.
2. The incident is the *inverse* direction of the same gap, and H5 was
   supposed to cover it. Per §[2.5](#25-defect-5--h5-never-runs-on-a-warm-reconnect),
   on the warm path it does not.
3. **A `0700` socket closes both directions at once** — the one the
   engine tried to cover and the one it explicitly declined to. That
   reframes Option A from an ergonomics improvement to a security
   remediation, and it should weigh directly on
   §[9](#9-open-questions) Q1.

If Option A ships, this SECURITY.md passage must be rewritten in the
same commit rather than left as a stale non-defense.

### 4.2 The catch, verified by execution

**Socket mode does not suppress the port prompt.** `validate_port` is
called unconditionally from `validate_config_fields:35` and never
consults `config.socket`. Reproduced on 2026-08-10 against argo-proxy
3.2.3: with `socket` set to a path and `port` set to a busy 64742, the
collision prompt still fires (see [§8](#8-what-was-verified-by-execution)
for the exact reproduction).

Consequences for the design:

1. **Defect 2 must be fixed independently of Option A.** Socket mode
   removes the collision; it does not remove the hang.
2. A socket-mode config must still carry a `port:` value that is
   *actually free*, or we are back to the prompt — which means the
   bind-test probe from Option B is required **even under Option A**,
   just for a value that is never bound. (Upstream default is
   `port: int = 44497`, and `port` is in `REQUIRED_KEYS`, so it is
   always present and always validated.)
3. The clean upstream fix is a one-line early return in `validate_port`
   when `config.socket` is set. Worth filing.

### 4.3 Where the socket lives — measured, not assumed

The first draft treated `/run/user/$(id -u)` as the natural home with
`/tmp` as a grudging fallback, and flagged the whole question as the
main open unknown. **A live probe on 2026-08-10 (§[8](#8-what-was-verified-by-execution))
inverted that ranking.** The measurements below are from
`compute-386-01` — one CELS host, which is emphatically *not* the whole
target population (see §[4.4](#44-the-target-population-is-heterogeneous-cels-is-not-the-only-target)).

| Property | `/run/user/6841` | `/tmp/argo-anywhere-$UID/` | `~/.argo_anywhere/` |
|:---|:---|:---|:---|
| Filesystem | tmpfs | tmpfs (94G) | **NFS4** |
| Node-local | yes | yes | **no — one dir for every node** |
| Survives last logout | **no** (`Linger=no`) | yes | yes |
| Survives reboot | no | no | yes (proxy does not) |
| `0700` dir + bind + connect | OK | OK | OK (same-host) |
| Stale file can wedge rebind | n/a (wiped) | n/a (wiped at boot) | **yes — `EADDRINUSE`** |

**`~/.argo_anywhere/` is the worst of the three, and the reason is
structural.** `$HOME` on CELS is `netapp-386-02a:/gce/homes/<user>` over
NFS4 — *the same directory on every compute node*. A fixed socket path
under `$HOME` is therefore one global name shared by all nodes, which
reintroduces §[2.0](#20-the-structural-assumption)'s single-global-name
assumption in a new coordinate system. The contenders change from "other
users" to "your own nodes"; the shape does not.

The failure mode is also stickier than a port collision. A socket
*file* is not reclaimed by the kernel when its process dies, so a proxy
killed on node A leaves a file that makes node B's `bind()` fail
permanently:

```text
node B rebind over orphan: BLOCKED -> OSError 98 Address already in use
orphan connect: refused -> Connection refused   (so liveness IS testable)
```

The second line is the saving grace — an orphan is *detectable*, so an
unlink-if-dead protocol is implementable. But that is a stale-lock
protocol we would have to write and get right, and it is self-inflicted:
a tmpfs path makes the entire class impossible because the file cannot
outlive the node.

**`/run/user/$(id -u)` is second, gated on lingering.** It exists, is
`drwx------`, tmpfs, writable, and `XDG_RUNTIME_DIR` is set — but
`Linger=no`, and the detached argo-proxy runs inside a *session* scope
(`/user.slice/user-6841.slice/session-186508.scope`), not the user
slice. With `KillUserProcesses=no` (confirmed) the proxy **survives**
logout while `/run/user/<uid>` is **destroyed** at last logout. That
combination yields a live proxy with a deleted socket: an *invisible*
failure, strictly worse than today's loud one. Use this path only when
`loginctl show-user <u> --property=Linger` reports `yes`.

**`/tmp/argo-anywhere-$(id -u)/` at `0700` is the recommended primary**
for CELS-shaped targets: node-local, no logind coupling, survives
logout exactly as the detached `screen` session does, and not swept
between boots (`/usr/lib/tmpfiles.d/tmp.conf` carries only
`D /tmp 1777 root root -`, i.e. boot-time clear).

Two details that bite whichever path wins:

- **The `0700` guarantee must come from the containing directory.** The
  socket file itself binds `0755` under the node's `umask 0022`, despite
  argo-proxy's `--socket` help text claiming "Permissions are set to
  0700". Verify that claim rather than trusting it; the directory is
  what we control.
- **Storage class matters, not just the path.** `~/.argo_anywhere/`
  remains exactly right for *state* — the manifest, caches, the D-023
  canonical install — precisely *because* it is durable and shared. It
  is wrong for a *rendezvous point*, which must be node-local and
  self-cleaning. Keep the two categories distinct so this does not get
  re-litigated.

### 4.4 The target population is heterogeneous: CELS is not the only target

Everything in §4.3 was measured on one CELS compute node, and CELS is
only one kind of target. The tool is also pointed at machines with a
completely different storage and access shape — **Aurora** being the
worked example: a different filesystem stack (no `/gce/homes` NFS), and
a direct invocation rather than the CELS jump-host-plus-compute-node
dance.

This matters more than a footnote, because §4.3's ranking is derived
*entirely* from properties that vary by site:

| Assumption behind the §4.3 ranking | Varies by site? |
|:---|:---|
| `$HOME` is NFS shared across execution hosts | **Yes** — the whole case against `~/.argo_anywhere/` |
| A writable node-local `/tmp` on tmpfs | **Yes** — size, sweep policy, per-job namespacing |
| logind present, `Linger` queryable | **Yes** — not every scheduler-managed node runs logind |
| One long-lived interactive node per user | **Yes** — batch/scheduler sites differ fundamentally |

So the design must **not** hard-code a path. The right shape is a small
ordered resolver that picks at runtime and reports which rung it landed
on:

1. explicit override (`--socket-dir` / `ARGO_ANYWHERE_SOCKET_DIR`) — the
   escape hatch for a site we have not met;
2. `$XDG_RUNTIME_DIR` **iff** lingering is on (or the site guarantees
   the dir outlives the session);
3. `/tmp/argo-anywhere-$(id -u)/` at `0700`, **iff** `/tmp` is node-local
   and writable;
4. refuse socket mode and fall back to hardened TCP
   (§[5](#5-option-b--hardened-tcp-and-the-fallback-ladder)) — never
   silently pick a shared-filesystem path.

Rung 4 is why Option B is not wasted work under Option A: a site where
no node-local `0700` directory can be found still needs a correct TCP
path. The engine already assumes `$HOME`-relative server-side paths
throughout (`VENV_PATH='$HOME/argovenv'`, `REMOTE_SELF`, `REMOTE_LOG`),
which is fine for *state* and wrong for a rendezvous point — the same
distinction §4.3 draws.

**Posture for non-CELS targets (decided 2026-08-10): best-effort, no
per-site matrix.** We do not enumerate or pre-probe sites. Reachability
continues to work the way the engine already handles it — defer to the
alias's own `ProxyJump`/`ProxyCommand` from `~/.ssh/config` when there
is one (D-032), otherwise use the configuration the user passes — and
the resolver above discovers the storage situation at runtime, wherever
it lands. This is the whole point of resolving rather than hard-coding:
the ladder needs no advance knowledge of a site. The single obligation
it does carry is that **rung 4 must be audible** — when socket mode is
unavailable, say so in one line with the reason, so "socket mode
declined here" is distinguishable from "socket mode never tried."

Note also that `_on_anl_node`'s host detection is a `.cels.anl.gov`
suffix match, documented at `:727`–`:732` as silently returning "no" for
any other domain. A genuinely multi-site transport story eventually has
to revisit that too; out of scope here, but it is the same
CELS-is-the-world assumption showing up in a second place.

### 4.5 Remaining costs and unknowns

- **Version floor.** `--socket` and the `socket:` config key are present
  in argo-proxy 3.1.2, 3.2.1, and 3.2.3 (verified 2026-08-10). The floor
  is therefore ≤ 3.1.2 — comfortable — but adopting it finally forces
  **UP-02**, the soft version floor deferred across four audits.
- **`curl --unix-socket`** is needed for on-node health probes
  (`curl --unix-socket <path> http://localhost/health`). **Confirmed
  present on `compute-386-01`** (curl 7.81.0); unverified on other
  sites.
- **On-node local mode.** A user running directly on a compute node with
  no tunnel still needs a reachable endpoint; socket mode works there
  too, but every local `curl localhost:$PORT` in the engine needs a
  socket-aware branch.
- **`stop` / `clean` / the D-025 install manifest** must learn about
  socket files and stale-socket cleanup.
- **Per-site verification is now a prerequisite, not a nicety.** §4.3's
  probe needs re-running on each target class we claim to support
  (Aurora first). The probe is read-only and takes seconds over an
  already-warm channel; there is no reason to guess.

---

## 5. Option B — hardened TCP; and the fallback ladder

Option A cannot be the only path, because socket mode may be
unavailable (old argo-proxy on a node we do not control, no usable
runtime dir). Option B is what TCP must become regardless:

1. **Replace `lsof`-as-oracle with a bind test.** Ship the remote probe
   as a `python3 -c` `socket.bind(("127.0.0.1", port))` — byte-identical
   semantics to what argo-proxy itself will do, and the only check that
   sees across users. Keep `lsof` solely for *attributing* a hit to
   `mine:` / `other:`, which is all it was ever able to do. **This is a
   detector, not a guarantee**: we bind, release, and hand the port to
   argo-proxy moments later, so a co-tenant can take it in the gap. The
   TOCTOU window is small but structural, which is why item 5 below —
   not this one — is the load-bearing safety property (see
   §[6](#6-recommended-sequencing)). Apply it to
   `find_next_free_remote_port` too, or `--auto-port` keeps recommending
   occupied ports (§[2.1](#21-defect-1--collision-detection-is-blind-across-users)).
2. **Occupied means move.** Never attach to a listener we cannot
   positively confirm is ours.
3. **Positive-identity marker.** `mode_server` writes a node-side state
   file at launch (port/socket, pid, start time, ANL user); the client
   reads it back over the warm mux to answer "is this mine?" without
   introspecting anyone else's process. Per
   §[2.5](#25-defect-5--h5-never-runs-on-a-warm-reconnect) this is the
   only item on the ladder that also covers the **warm** path, since it
   is the client — not `mode_server` — that does the reading. Cost: an
   SSH round trip on paths that currently make none, which is the same
   trade-off as §[9](#9-open-questions) Q5 and should be decided once
   for both.
4. **Per-user default port** as a mitigation — deterministic from the
   ANL username so it is stable across runs and distinct across tenants.
   Demoted from "fix" to "reduces the incidental collision rate."
5. **Never let argo-proxy reach an interactive prompt.** Launch as
   `sh -c 'exec argo-proxy serve < /dev/null'` so a prompt raises
   `EOFError` in ~1s instead of hanging for 20s with no diagnostic. The
   engine writes every required config key, so no legitimate prompt
   should exist. Pair with `screen -X hardcopy` in the timeout branch so
   the session's output is surfaced automatically.
6. **Confirm our own process came up** before believing `/health`
   (Defect 4, §[2.4](#24-defect-4--the-post-launch-liveness-check-is-identity-blind)).
   Node-local, no round trip, no upstream dependency.

Proposed ladder: **socket mode when supported → hardened TCP with bind
test → refuse with a clear message.** Never the silent-optimistic
fallthrough the code takes today (`:5954`, "Proceeding optimistically";
the `die` at `:5959` is the give-up-after-N-rounds branch).

Independent of both options, and worth landing early because it is
self-contained: **`status` honesty** — wire in `local_tunnel_destination`
(`:5405`, which already exists and is already trusted by the P3 misroute
fix, but is called from exactly one place, `:5768`) and scope the verdict
so `ALL GREEN` cannot be read as a claim about a node it never probed.

---

## 6. Recommended sequencing

The first draft offered two options and seven open questions but no
order, which left the impression that nothing can move until the
transport question is settled. The analysis above implies otherwise:
the most valuable change is also the smallest, and it is independent of
both options.

**Tier 1 — no design decision required; land first.** Each of these is
self-contained, has no upstream dependency, changes no user-facing
flag, and is strictly correct under either Option A or Option B.

| # | Change | Defect | Status | Why first |
|:--|:---|:---|:---|:---|
| 1 | `< /dev/null` on launch + session-output capture in the timeout branch | 2 | **SHIPPED 2026-08-10** | Turns an indefinite silent hang into a ~1s diagnosable `EOFError` |
| 2 | Confirm our own session/pid before trusting `/health` at `:7557` | 4 | **SHIPPED 2026-08-10** | Stops a stranger's proxy from satisfying our liveness check |
| 3 | `status` honesty via `local_tunnel_destination` | 3 | **SHIPPED 2026-08-10** | Stops `ALL GREEN` overclaiming; pure reporting change |

**Item 1 shipped 2026-08-10 (in two commits — see the durability
correction below).** All three launchers (`screen`, `tmux`,
`nohup`) now run argo-proxy with stdin redirected from `/dev/null`
under a `NO-INTERACTIVE-PROMPT INVARIANT` comment block in
`mode_server`; the `screen` branch passes the binary as `$0` to `sh -c`
so a `$venv` containing spaces cannot word-split (the hazard the tmux
branch already solved with `printf %q`). The start-timeout branch gained
`_dump_session_output_screen` / `_dump_session_output_tmux`, which
capture the detached session's visible output (`screen -X hardcopy` /
`tmux capture-pane -p`) and print it under a header before the existing
manual-inspection hints. Both helpers are no-fail by contract: missing
binary, dead session, or unwritable `TMPDIR` degrades to a silent no-op,
because they run inside a path that is already dying. Trailing blank
padding is stripped (`hardcopy` pads to full terminal height).

Pinned by `tests/test_engine_no_interactive_prompt.py` (9 tests):
grep invariants for all three launchers plus behavioural harnesses that
reproduce the hang with the un-redirected launch shape and prove the
redirect prevents it, and that the captured text contains the actual
`Port 64742 is already in use` prompt. The behavioural tests drive the
engine's **own** launch line (extracted by regex, fake binary
substituted) rather than a copy, so they track the real code. Verified
to fail when the fix is reverted.

One testing gotcha worth recording: `screen` derives its socket
directory from `$HOME`, and the autouse `_isolate_home` fixture
repoints `HOME` per test — so a harness inheriting the ambient
environment starts sessions it cannot then see. `_run_screen_harness`
pins a private `HOME` inside its own tmpdir.

#### Durability correction — the two halves of item 1 initially cancelled out

The first implementation shipped (a) and (b) as written above and was
**subtly wrong**, caught the same day while checking the interaction
rather than the parts. The defect:

> (a) makes a prompting argo-proxy die in about **one** second. The
> start-timeout fires at **twenty**. `screen` and `tmux` reap a session
> as soon as its child exits — so by the time (b) ran, there was no
> session left to capture from, and `screen -X hardcopy` failed with
> `No screen session found`. **In the common case the fix produced no
> diagnostic at all**, which is precisely the outcome it existed to
> prevent. Verified directly: the session is gone within 2s of the
> EOF death.

The two halves only compose if the output outlives the session. All
three launchers therefore also `tee` stdout+stderr to `$_PROXY_LOG`
(`~/argoproxy.out` — the path the `nohup` branch already used, so
`clean`'s existing removal entry stays correct), truncated per launch
so the current failure is not buried under old ones. The timeout branch
reads that file **first** and only falls back to a live-session capture
when the log came back empty — the disjoint case where the process is
genuinely hung at 20s rather than long dead.

`tee` rather than `screen -L -Logfile`: `-Logfile` requires screen
≥ 4.06 and we do not control the version on an arbitrary node; `tee`
also keeps output visible to anyone attaching with `screen -r`.

The lesson generalises past this change: **a fix that makes something
fail *faster* can invalidate the mechanism that was supposed to report
the failure.** Both halves passed their own tests; only the end-to-end
sequence exposed it. `test_log_survives_the_session_that_dies_from_the_redirect`
now pins exactly that interaction — it asserts the session *is* reaped
(so the hazard stays real, not hypothetical) and that the prompt text
is still recoverable afterwards.

Item 1 is the keystone, and the reason is worth spelling out because it
inverts the first draft's ordering. **Once a collision fails fast and
loudly, the bind test stops being a correctness requirement and becomes
a UX optimization.** A bind test is inherently TOCTOU — we bind,
release, then argo-proxy binds some milliseconds later, and on a node
with ten tenants racing for the same default port that gap is real. It
cannot be the safety property. What *can* be the safety property is
argo-proxy failing immediately and visibly when it loses the race,
which is precisely what `< /dev/null` buys. The bind test then earns
its place by moving the failure earlier and making the message better —
which is worth having, but is not what keeps us correct.

**Item 2 shipped 2026-08-10.** The post-launch wait now ANDs the
`/health` curl with a new `_listener_is_ours "$PROXY_PORT"` under an
`IDENTITY-BEFORE-SUCCESS INVARIANT` comment block. A foreign listener is
a **hard, immediate failure** rather than a 20s timeout — waiting cannot
help when the port is already held — and the refusal names the way out
(`--port` / `--auto-port`) and prints our own proxy's log tail.

The discriminator is a pleasing inversion of
§[2.1](#21-defect-1--collision-detection-is-blind-across-users): the
unprivileged-`lsof` blindness that makes it useless *before* launch
becomes a reliable positive signal *after* launch, because a proxy **we**
started is always attributable to us. Empty output on a port that is
demonstrably serving therefore means "someone else's", never "nobody's".

Verified on the live node (2026-08-10), which happened to present the
exact incident configuration — both ports answering `/health`
identically:

```text
port 64751: health=answers  verdict=OURS        <- our proxy
port 64742: health=answers  verdict=not-ours    <- the co-tenant's
```

`_listener_is_ours` is **fail-closed by contract**: missing `lsof`, a
vanished pid, or an unnameable owner all return "not ours". Claiming
ownership on missing evidence would reopen precisely the misattachment
the helper exists to prevent — the same reasoning as H5's
"positively confirm or refuse" rule
(§[3](#3-why-the-obvious-fix-is-not-a-fix)), applied to the post-launch
question instead of the pre-launch one. It compares the **OS account**
(`id -un`), which is the right oracle here: the question is "did the
process we just spawned come up?", not "whose Argo identity will it
bill?" — the latter remains H5's job via the config's `user:` field.

Pinned by `tests/test_engine_listener_identity.py` (12 tests): the
wait-loop AND, the hard-failure ordering, fail-closed structure (every
guard returns 1; no unconditional `return 0`), the D-011 SIGPIPE guard
on the `lsof | head` capture, `set -e` survival, plus behavioural cases
for own / unbound / dead / no-lsof listeners. Verified to fail when the
identity check is removed.

**Item 3 shipped 2026-08-10.** `gather_summary` now calls
`local_tunnel_destination` — which existed since the P3 audit fix and
had exactly one caller, so `status` had ground truth available and never
used it — and `render_summary` surfaces it as a `Tunnel goes to` row
next to the local probes. Four changes, all reporting-only:

- **The green verdict stops overclaiming.** `ALL GREEN - tunnel up,
  proxy healthy, N model(s)` becomes `ALL GREEN - endpoint healthy,
  N model(s)`. "Tunnel up" was exactly the part three laptop-side probes
  cannot establish.
- **A destination mismatch downgrades to `CHECK`** rather than rendering
  green beside a contradicting cached node. Not an error — it may be
  deliberate — but never unqualified green.
- **`Cached node:` becomes `Last connected to: … (cached; not
  re-verified)`.** The old label was read as "the node you are talking
  to now", which it never meant.
- **The card states its own limit** in the Next-step section: the checks
  confirm the endpoint answers, not whose argo-proxy is behind it
  (suppressed in on-node mode, where there is no tunnel).

`SUM_DEST_MATCHES_CACHE` is deliberately **three-valued** — empty /
`yes` / `no`. Empty means *unknown* and stays green: on-node local mode,
a foreground tunnel with no `ControlPath`, and first runs with no cache
all legitimately produce it. Collapsing unknown into "mismatch" would
fire a scary verdict at users with nothing wrong.

Verified against the live tunnel, both paths:

```text
ALL GREEN  -  endpoint healthy, 51 model(s)
Tunnel goes to   : compute-01.cels.anl.gov  (matches cached node)
Last connected to: compute-01.cels.anl.gov  (cached; not re-verified)
```

```text
CHECK      -  endpoint healthy, but tunnel goes to compute-01.cels.anl.gov
Tunnel goes to   : compute-01.cels.anl.gov  (DIFFERS from cached node …)
Last connected to: some-other-node.cels.anl.gov  (cached; not re-verified)
                   ^ the live tunnel goes to compute-01.cels.anl.gov instead.
```

Pinned by `tests/test_engine_status_honesty.py` (14 tests): 11 contract
assertions plus 3 that render the **real** `render_summary` with stubbed
`SUM_*` globals and assert on the emitted card (matching / mismatched /
unknown destination). Verified to fail when the overclaiming wording or
the mismatch branch is reverted.

With items 1, 2 and 3 shipped, the incident as it actually occurred can
no longer reach `ALL GREEN`. Item 1 makes the collision fail in about a
second with the upstream warning quoted back to the user, instead of
hanging for 20s behind a message that named only the symptom; item 2
stops the co-tenant's proxy from standing in for ours at the moment of
success; item 3 stops the summary card from asserting more than it
checked, so a green box no longer implies a node it never probed.

**Tier 1 is complete.** Everything in it was reporting or launch
hygiene — no design decision, no user-facing flag, correct under either
transport option.

#### Tier 1 live verification (2026-08-10, `compute-386-01`)

Unit tests cannot exercise a real cross-user collision, so Tier 1 was
verified on the node itself. **The maintainer's live channel was
running throughout and had to survive**, which shaped the method: a
normal `connect` could not be used, because `SCREEN_SESSION` is a single
global name (`argovproxy`) and `mode_server`'s multi-port guard would
have offered to replace the running proxy. Instead each test drove the
engine's **own** code — launch line and wait loop extracted verbatim by
regex — inside a sandbox: `SCREENDIR=/tmp/argotest_screens`, a distinct
session name, and a copied config. `SCREENDIR` isolation was verified
first (a sandbox `screen -S argovproxy -X quit` returned
`No screen session found` while the real session stayed up).

The node presented the incident configuration for free: our proxy on
`:64751` and a co-tenant's on `:64742`, both answering `/health`
identically.

| Test | Result |
|:---|:---|
| Item 1 — real collision, engine launch line | Session reaped in **3s** (was: hang until the 20s timeout) |
| Item 1 — durable log | **2158 bytes survived** the reaped session |
| Item 2 — `_listener_is_ours` | `:64751` → OURS; `:64742` → not-ours; both answer `/health` |
| Item 2 — fail-closed | no `lsof` on `PATH` → not-ours; unbound port → not-ours |
| Wait loop (verbatim) case A | our port → succeeds immediately |
| Wait loop (verbatim) case B | co-tenant's port → **hard refusal, not a timeout** |

The log ends exactly where the analysis predicted:

```text
WARNING | [config] Warning: Port 64742 is already in use.
Enter port [64185] [Y/n/number]: ERROR | [cli] An error occurred while
  starting the server: EOF when reading a line
```

Post-test the node was byte-for-byte as snapshotted: same pids
(`4092653`/`4092655`), same `argovproxy` session, `port: 64751`
unchanged, no leftover files.

**One defect found and fixed by this exercise.** A failed start writes
~17 lines of which 8 are argo-proxy's ASCII banner, so the `tail -n 20`
in the refusal path showed the banner and buried the collision line.
Added `_log_tail_meaningful`, which filters banner glyphs and blank
padding at **display** time — deliberately not `--no-banner` at launch,
so the on-disk log and anyone attaching via `screen -r` still see
argo-proxy's normal output.

Two notes for the eventual full end-to-end run (still outstanding):
nothing here exercised `remote_bootstrap`, `scp`, or a genuine cold
`connect`; and the `tee` pipeline means the pipeline's exit status is
now `tee`'s, which is inert under `screen -dm` but unverified against a
real `mode_server` return path.

What remains is narrower but not smaller. The **cold** bootstrap path is
now guarded at both ends (H5 before launch, `_listener_is_ours` after);
the **warm** path is not guarded at all
(§[2.5](#25-defect-5--h5-never-runs-on-a-warm-reconnect), Defect 5) —
every reconnect that reuses an existing tunnel still trusts a bare
`/health`. That is Tier 2 item 5 plus the transport decision, and it is
where the remaining misattachment risk lives. Item 3 (`status` honesty)
is also still open: the summary box continues to report a verdict it
cannot actually justify.

**Tier 2 — small design decisions, no transport commitment.**

| # | Change | Defect | Note |
|:--|:---|:---|:---|
| 4 | Bind test replacing `lsof`-as-oracle, incl. the `--auto-port` walk | 1 | Detector; see TOCTOU caveat above |
| 5 | Identity check on the **warm** path (`ours-healthy-mux` / `external-healthy`) | 5 | Needs the Q5 round-trip decision |

**Tier 3 — the transport decision itself.** Option A vs Option B,
gated on §[9](#9-open-questions) Q1–Q3, which in turn are gated on the
one live test that has never been run: does `/run/user/$(id -u)` exist
and work on an ANL compute node?

Note that Tier 1 does **not** prejudge Tier 3. If Option A ships later,
items 1 and 2 remain necessary (socket mode does not suppress the
prompt — §[4.2](#42-the-catch-verified-by-execution) — and a socket can
be stale just as a port can be squatted). Nothing in Tier 1 is throwaway
work under any outcome, which is the main argument for landing it before
the design question is resolved rather than after.

---

## 7. Blast radius

Sites that change under each option. `A` = Unix socket, `B` = hardened
TCP.

| Site | Today | A | B |
|:---|:---|:---:|:---:|
| `write_argoproxy_config` (`:6831`) | owns 4 keys | + `socket` (5th owned key) | — |
| `mode_server` port readback (`:7319`) | refuses on `port` mismatch | needs socket-mode branch; `port` moot | — |
| `mode_server` step 5 (`:7343`) | `lsof` | socket-existence + liveness | bind test |
| `mode_server` launch (`:7531`) | `screen -dmS … serve` | `< /dev/null`, socket path | `< /dev/null` |
| `mode_server` wait (`:7557`) | `curl 127.0.0.1:$PORT`, identity-blind | `curl --unix-socket` + own-session check | + own-session check |
| `probe_remote_port_owner` (`:5574`) | `lsof` | n/a (no port) | bind test |
| `find_next_free_remote_port` (`:5619`) | `lsof` walk | n/a | bind-test walk |
| `local_tunnel_status` (`:5368`) | `ps`-glob on `-L <port>:` | **unchanged — verified** | unchanged |
| `ensure_or_reuse_tunnel` warm paths (`:5810`/`:5823`/`:5827`) | reuse without identity | + identity | + identity |
| `open_tunnel` (`:5016`) | `-L p:localhost:p` | `-L p:<socket>` | unchanged |
| `gather_summary` / `render_summary` | local-only verdict | + destination + identity | same |
| `channel_is_up` (`:6465`) | bare `/health` | + identity | + identity |
| `stop` / `clean` / manifest (D-025) | port-oriented | + socket files | unchanged |

Two rows deserve a note.

**`local_tunnel_status` survives socket mode — but by luck.** Its
classification globs (`:5504`–`:5506`) match on `-L <port>:` and never
inspect what follows the colon, so a socket-mode forward
(`-L 64742:/run/user/1234/argo-proxy.sock`) still classifies as
`fg-tunnel`. Confirmed by running the case block against representative
`ps` strings (§[8](#8-what-was-verified-by-execution)). This is a
happy accident of a pattern written for a different purpose, not a
designed property; record it as verified so a future tightening of
those globs does not silently break socket mode.

**The warm-path row is new** and is the one place where the two options
do *not* diverge: whichever transport wins, `ensure_or_reuse_tunnel`
must stop treating reachability as ownership
(§[2.5](#25-defect-5--h5-never-runs-on-a-warm-reconnect)).

The engine↔web-UI coupling rules in [`AGENTS.md`](../AGENTS.md)
("Engine ↔ web-UI coupling rules") apply if any user-facing flag
changes; a `--socket` / `--transport` flag would need the tri-lockstep
treatment described there for D-032.

---

## 8. What was verified by execution

Two distinct evidence sets, kept separate because the first draft
conflated them:

- **Node-side incident evidence** — the probes in
  §[1.1](#11-the-three-symptoms) *were* run on `compute-386-01`
  (`command -v lsof`, `ss -ltnp`, `pgrep -af argo-proxy`, `screen -ls`).
  That is how the incident was characterised at all.
- **Design-validation evidence** — everything below, run **on the
  maintainer's laptop only**. **Nothing in support of Option A or
  Option B has been run on an ANL node.**

All checks below run 2026-08-10 on macOS 26 against the live venvs from
the [2026-08-10 upstream audit](../docs/AUDIT_2026-08-10_argo-proxy-upstream.md),
plus one engine-source check re-run against the working tree during the
second reasoning pass.

**Socket mode does not skip the port prompt** — the load-bearing result:

```python
cfg = ArgoConfig(user="testuser", host="127.0.0.1", port=64742)  # 64742 held
cfg.socket = "/tmp/argo-anywhere-test/argo-proxy.sock"
validate_port(cfg)
# WARNING | [config] Warning: Port 64742 is already in use.
# Enter port [59636] [Y/n/number]:  -> EOFError
```

Also verified:

- `--socket` + `socket:` config key present in argo-proxy **3.1.2,
  3.2.1, 3.2.3**.
- `/health` returns `{"status": "healthy"}` and nothing else
  (`argoproxy/app.py:210`) — so laptop-side identity verification
  **cannot** come from a curl through the tunnel.
- `is_port_available` (`argoproxy/utils/misc.py:82`) is a real
  `bind()` on `127.0.0.1`, which is why it sees what our `lsof` cannot.
- Local OpenSSH is 10.2p1, far above the 6.7 needed for
  `-L port:remote_socket`.
- Zero occurrences of `ss` / `netstat` / `/proc/net/tcp` in the engine.

Added in the third pass (2026-08-10) — **run on a live ANL node**
(`compute-386-01`, via an already-warm mux master; all probes read-only,
`BatchMode=yes`, pinned to the existing `ControlPath` so no new
authentication and therefore no CSPO exposure):

- **`/run/user/6841` exists**, `drwx------`, tmpfs, writable,
  `XDG_RUNTIME_DIR` set. Unix-socket bind + connect succeed.
- **`Linger=no`**, `KillUserProcesses=no`, `RemoveIPC=yes` (defaults),
  systemd 249. The detached argo-proxy sits in
  `/user.slice/user-6841.slice/session-186508.scope` — a *session*
  scope. Hence the live-proxy-with-deleted-socket hazard in §4.3.
- **`$HOME` is NFS4** (`netapp-386-02a-user.cels.anl.gov:/gce/homes/…`),
  i.e. one directory shared by every compute node.
- **An orphaned socket file on NFS blocks a later `bind()`**
  (`OSError 98 EADDRINUSE`) while `connect()` to it is refused — so the
  wedge is real and the liveness test is available. Demonstrated
  directly.
- **`/tmp` is node-local tmpfs**, 94G, `1777`; a `0700` subdir + socket
  works; `tmpfs.d` config is `D /tmp` (boot-time clear only).
- **`curl 7.81.0` supports `--unix-socket`.**
- **Sockets bind `0755`** under the node's `umask 0022` — the `0700`
  guarantee must come from the directory.
- All probe artifacts removed; the maintainer's live channel, screen
  session, and argo-proxy were left untouched (verified after).

Scope limit on the above: **one host, one site.** Per
§[4.4](#44-the-target-population-is-heterogeneous-cels-is-not-the-only-target)
these properties vary by target, and Aurora in particular has a
different storage stack and invocation path. Nothing here should be
read as characterising "ANL nodes" in general.

Added in the second pass (2026-08-10):

- **`local_tunnel_status`'s globs survive socket mode.** The `case`
  block at `:5504`–`:5506` was extracted verbatim and run against three
  representative `ps` strings; `-L 64742:/run/user/1234/argo-proxy.sock`
  classifies as `fg-tunnel`, same as the TCP form. See
  §[7](#7-blast-radius) for why this is luck rather than design.
- **H5's unreachability on warm paths** was established by reading the
  three early-return sites in `ensure_or_reuse_tunnel`
  (`:5810`/`:5823`/`:5827`) against the single `remote_bootstrap` call
  site (`:5963`) — static, but unambiguous.

**Not verified — stated explicitly:**

- **Nothing was run on an ANL node to validate either option.**
  `/run/user/$(id -u)` availability, `curl --unix-socket` availability,
  and socket-forwarding end-to-end are all **unconfirmed on the real
  target** and are the first things a live test must establish. (This is
  the claim the first draft over-stated as "nothing was run on an ANL
  node for this note", which contradicted §1's evidence table.)
- The identity of the process holding `127.0.0.1:64742` was not
  determined and cannot be without root on the node
  (§[1.3](#13-limits-on-the-conclusion)).
- The Branch A / Branch B reconstruction in
  §[1.2](#12-two-runs-not-one) is inferred from the code paths and the
  surviving evidence, not from a captured transcript of either run. It
  is falsifiable: a `screen -X hardcopy` from item 1 of
  §[6](#6-recommended-sequencing) would have settled it directly, which
  is itself an argument for landing that item.

---

## 9. Open questions

Q1–Q7 are as first drafted (with Q1 and Q5 amended by the second pass);
Q8–Q9 are new. Note that per §[6](#6-recommended-sequencing), **none of
these gate Tier 1** — they gate Tiers 2 and 3.

1. **Socket or TCP as the primary path?** Option A is structurally
   better but adds a config key, a version floor, and a fallback ladder.
   Option B is smaller but can only ever *detect* the commons problem,
   never remove it. *Second-pass amendment*: Option A also closes a
   documented SECURITY.md non-defense in both directions
   (§[4.1a](#41a-it-closes-a-documented-currently-untreated-threat-model-gap)),
   which is a stronger argument than the collision-avoidance framing
   this question was originally written around.
2. ~~**Does `/run/user/$(id -u)` exist on ANL compute nodes**, and is it
   writable and persistent for the session's lifetime?~~ **ANSWERED
   2026-08-10 on `compute-386-01`** (§[4.3](#43-where-the-socket-lives--measured-not-assumed),
   §[8](#8-what-was-verified-by-execution)): it exists and is usable,
   **but `Linger=no` destroys it at last logout while the proxy
   survives**, so it is not the primary. `/tmp/argo-anywhere-$(id -u)/`
   at `0700` is, and `~/.argo_anywhere/` is disqualified because `$HOME`
   is NFS shared across nodes. Socket mode is viable on this host.
   Residual: the same probe has **not** been run on any other target
   class (Q11).
3. **Version floor value.** UP-02 has been deferred four times. Socket
   mode needs ≥ 3.1.2; the 2026-08-10 audit recommends ≥ 3.2.3 on other
   grounds. Pick one number for both.
4. **Does the port prompt get fixed upstream or worked around locally?**
   The `< /dev/null` launch is ours to make and works today; the
   `validate_port` early-return is a one-line upstream patch. Both?
5. **Does `status` gain a remote tier**, or does it stay local-only and
   simply stop overclaiming? A remote tier costs an SSH round trip on
   every `status` invocation. *Second-pass amendment*: this is the same
   trade-off as the warm-path identity check
   (§[2.5](#25-defect-5--h5-never-runs-on-a-warm-reconnect), Option B
   item 3) — both want a cheap authenticated round trip over the warm
   mux, and both should be answered together. Sub-question: is one
   round trip per `connect`/`configure` (not per `status`) enough, given
   the mux master is already warm and the marginal cost is a few tens of
   milliseconds?
6. **Is the per-user default port worth doing at all** if Option A
   lands, given it only helps the fallback path?
7. **Do we notify the co-tenants?** Ten argo-anywhere users on one node
   are all exposed to the same misattachment; several are presumably
   running the same stale default port. Per
   §[1.3](#13-limits-on-the-conclusion) the exposure is symmetric and
   live, so this is not purely courtesy — it is a release-notes and
   possibly a direct-outreach question, not a code question.
8. **Should Tier 1 ship as a patch release before the transport
   decision?** §[6](#6-recommended-sequencing) argues Tier 1 is correct
   under every outcome and is where most of the safety lives. Holding it
   for the design decision leaves a known misattachment path open for
   however long Q1–Q3 take.
9. **What is the smallest honest warm-path identity check?** A node-side
   state file read over the warm mux (Option B item 3) is the obvious
   candidate, but the `external-healthy` case
   (§[2.5](#25-defect-5--h5-never-runs-on-a-warm-reconnect)) has no node
   to consult when the user is running *on* the node. Does that case get
   its own rule, or does on-node local mode simply inherit the
   socket-mode guarantee under Option A?
10. **Does the shared-`$HOME` scoping error get its own fix?** On CELS,
    `~/.config/argoproxy/config.yaml`, `$HOME/argovenv`, and
    `REMOTE_SELF` are all on one NFS mount shared by every compute node,
    so "one argo-proxy per user per node" is really "one per user"
    (§[2.1](#21-defect-1--collision-detection-is-blind-across-users)).
    Two nodes running `mode_server` concurrently corrupt each other's
    `port:` line. Options: per-node config path, a node-stamped config,
    or documenting the constraint honestly. Note this interacts with the
    socket decision — a per-node socket path plus a shared config is an
    incoherent pairing.
11. **What is the per-site storage matrix?** §4.3 measured exactly one
    CELS host. Aurora (different filesystem stack, direct invocation,
    no `/gce/homes` NFS) is the nearest counter-example, and
    scheduler-managed sites may have neither logind nor a persistent
    node-local `/tmp`. Which target classes do we claim to support, and
    what does the resolver in §4.4 do when it can find no node-local
    `0700` directory — refuse socket mode silently, or say so? (Related:
    `_on_anl_node`'s `.cels.anl.gov` suffix match at `:727` already
    encodes the CELS-is-the-world assumption elsewhere in the engine.)

    **Partially resolved 2026-08-10 (maintainer):** do **not** build a
    per-site matrix, and do not probe other sites speculatively. The
    posture for non-CELS targets is **best-effort**: reach them the way
    the engine already does — honor `~/.ssh/config`'s
    `ProxyJump`/`ProxyCommand` when the alias defines one (D-032
    `_alias_has_own_proxy`), otherwise use the user-supplied
    configuration — and let the §4.4 resolver discover the storage
    situation at runtime on whatever host it lands on. That is exactly
    what the resolver is for: it needs no advance knowledge of a site,
    only an honest answer at rung 4 when no node-local `0700` directory
    exists. **The open part is narrow**: rung 4 must fall back to
    hardened TCP *audibly* (one line naming the reason), never
    silently — a site where socket mode is unavailable should look
    different from a site where it was never attempted.

---

*Created 2026-08-10 by Ahmed Attia (with substantial AI assistance from
Claude per [`CONTRIBUTORS.md`](../CONTRIBUTORS.md)). Motivated by a
field incident on `compute-386-01` the same day. Revised 2026-08-10
(second reasoning pass): corrected the §1 timeline into two explicit run
branches; added Defect 4 (identity-blind post-launch wait) and Defect 5
(H5 unreachable on warm reconnects); added §6 recommended sequencing and
demoted the bind test on TOCTOU grounds; added the SECURITY.md linkage
and the symmetric co-tenant exposure; reconciled §8's "nothing was run
on a node" against §1's node-side evidence; fixed line-number citations
(`:5954`, `:7319`, `:7395`, `:7465`, `:6831`) and the `CLAUDE.md` →
`AGENTS.md` reference. All engine line citations were re-audited
against the working tree at the end of the second pass. Revised again
2026-08-10 (third pass): a live read-only probe of `compute-386-01`
over the maintainer's warm channel answered Q2 and inverted §4.3's
socket-location ranking (`/tmp` primary; `/run/user` gated on
lingering; `~/.argo_anywhere/` disqualified by the NFS-shared `$HOME`);
added §4.4 on target heterogeneity (CELS is not the only target —
Aurora has its own storage stack and direct invocation) plus the
runtime path resolver; added Q10 (shared-`$HOME` scoping error) and Q11
(per-site storage matrix).
Engine line numbers cite the working tree as of 2026-08-10
(`src/argo_anywhere/engine/argo-anywhere.sh`, 11425 lines) and will
drift; re-grep the named function before relying on one.*
