# Handoff — shared-node transport work (session of 2026-08-10)

**Status**: work in progress, **nothing released, nothing pushed**.
**Audience**: the next agent (or the maintainer) picking this up cold.
**Read after**: `AGENTS.md`, then
[`impl_shared_node_transport.md`](impl_shared_node_transport.md) —
that note is the single source of truth for the analysis; this file is
only a map of where things stand and what to watch out for.

> ### Update — session of 2026-08-12
>
> Three things changed; the rest of this document still holds.
>
> 1. **`configure` live pass: PASSED** — but only on the second
>    attempt. The first run exposed an unrelated, pre-existing bug:
>    `write_opencode_config` emitted a hardcoded five-model block, so
>    `configure` + `[b]` cut a live **34-model config down to 5**,
>    including the model driving the session. Fixed in `606af68` (the
>    writer now populates from the live `/v1/models` and never drops an
>    existing key); re-ran clean, config byte-identical, no backup
>    written. This bug is in **v3.2.1 as well** — it is not a
>    regression from this work.
> 2. **Web-UI Defect 3: FIXED** (`14fc693`). See §5.1 item 3.
> 3. **The D-number contention is resolved.** D-034 belongs to this
>    work, now recorded in `PLAN.md`.
>    [`impl_channel_persistence.md`](impl_channel_persistence.md) moved
>    to D-035 and [`impl_command_echo.md`](impl_command_echo.md) to
>    D-036; neither has shipped, and a note that has not shipped does
>    not hold a number.
>
> 4. **`run` live pass: PASSED** (aider — launched, connected, clean
>    exit). It surfaced a second pre-existing bug: aider's
>    `.aider.model.settings.yml` had a hardcoded model list missing the
>    five newest models, so `--model openai/argo:claude-5-opus` returned
>    an empty stream. Fixed in `22d0b7a`.
> 5. **The cross-user collision was verified live, not simulated.** The
>    incident's collision is STILL ACTIVE on `compute-386-01`
>    (`:64742` bind=TAKEN / lsof=empty, answering `/health` identically
>    to ours). Both engine versions were run against it: v3.2.1 calls
>    that port `free` and `--auto-port` walks straight into it; the
>    fixed engine reports `other:?:?` and picks `64743`. See PLAN.md
>    D-034 "Live cross-user verification".
>
> Still open: the version decision. Suite is at **546 tests**
> *(2026-08-12)*. The operational cautions in §6 remain
> in force — the maintainer's live channel is still what this session's
> own traffic runs through.

---

## 1. What this was about

The maintainer hit a port collision that produced an auth error. The
investigation found that the tool had reported `ALL GREEN` while routing
his traffic through **a stranger's `argo-proxy`** on a shared compute
node — so his requests were authenticated with someone else's Argo
identity.

That turned out to be **five composing defects** on top of one
structural assumption (a single compile-time `PROXY_PORT_DEFAULT` on a
node with ≥10 argo-anywhere tenants). Full analysis, with the evidence,
is in [`impl_shared_node_transport.md`](impl_shared_node_transport.md).

---

## 2. State at handoff

| | |
|:---|:---|
| Branch | `main`, **18 commits ahead of `origin/main`**, unpushed |
| Working tree | clean |
| Tests | **499 passed, 1 skipped** at handoff; **524** after the 2026-08-12 session (`pytest -q` for current) |
| Engine copies | in sync (pinned by a test in every new module) |
| Released | **no** — maintainer's gate: nothing ships until the whole upgrade is tested end-to-end |
| Maintainer's live channel | `:64751` → `compute-01` (`compute-386-01`), mux pid `53382` |

**The maintainer's channel is load-bearing for the agent session
itself** — his OpenCode traffic runs through `localhost:64751`. Tearing
it down ends the session mid-task. See §6.

---

## 3. What shipped this session

All engine-side. Commits are in reverse-chronological order; each
message carries its own full rationale.

| Commit | Change | Verified |
|:---|:---|:---|
| `e725e6d` | **Defect 1** — port availability decided by `bind()`, not `lsof` | live |
| `83efd5d` | Web-UI Defect 3 recorded (fixed later, 2026-08-12 `14fc693`) | n/a |
| `d0b0806` | **Q10** — `--port` passed explicitly; shared `$HOME` can serve many nodes | live |
| `ecbf71d` | Cold-connect end-to-end PASS write-up | live |
| `0d6a12d` | **Defect 5a** — `external-healthy` gated on listener ownership | local |
| `7c35c37` | Banner filter in log tails; Tier 1 live-verified | live |
| `9c905a8` | **Defect 3** — `status` stops overclaiming | rendered both paths |
| `cf1129c` | **Defect 4** — `_listener_is_ours` before declaring success | live |
| `586bdb8` | Durable log (`tee`) — the fast-death fix had eaten its own diagnostic | live |
| `4839e50` | **Defect 2** — argo-proxy can never reach an interactive prompt | live |
| `c794ed9` | D-033 ControlPersist + stale-channel reconnect + theme retint | pre-existing work, committed here |
| `5c1695a`, `17b5ef9`, `d22fdbb` | The design note itself (3 reasoning passes) | n/a |

New test modules (all pin their behaviour and were **verified to fail
when the fix is reverted**):

```text
tests/test_engine_no_interactive_prompt.py   17 tests
tests/test_engine_listener_identity.py       17
tests/test_engine_status_honesty.py          14
tests/test_engine_bind_test_oracle.py        10
tests/test_engine_control_persist.py           5
```

(Counts as of 2026-08-10; run `pytest --collect-only -q` for current.)

---

## 4. The most important thing to internalise

**Three times this session, a fix passed its own tests while failing at
its actual job.** Only end-to-end exercise caught them:

1. **`< /dev/null` + `hardcopy`** — the redirect made argo-proxy die in
   ~1s, so `screen` reaped the session ~18s *before* the capture ran.
   Both halves worked; together they produced **no diagnostic at all**.
   Fixed by `tee`-ing to a file that outlives the session (`586bdb8`).
2. **The durable log** — then buried the one useful line under
   argo-proxy's 8-line ASCII banner, because a failed start is ~17 lines
   and `tail -20` showed all of it. Found only by reading real output
   (`7c35c37`).
3. **Q10's guidance** — told users that choosing `[k]eep` would get the
   run refused, steering them into rewriting a config file shared by
   *every* node. Following the tool's advice broke the next node
   (`d0b0806`).

The generalisable rule, and the reason the maintainer's release gate is
right: **a fix that makes something fail faster can invalidate the
mechanism meant to report the failure.** Test the composition, not the
parts.

A fourth, methodological: **two of my revert-checks silently did
nothing** — the regex didn't match because `$` is backslash-escaped
inside the engine's remote heredocs, so the "revert" was a no-op and the
tests "passed" meaninglessly. Always assert the mutation landed (e.g.
count occurrences) before trusting a revert-check.

---

## 5. What is open, in my suggested order

### 5.1 No design decision needed

1. ~~**`configure` / `run` live pass.**~~ **BOTH PASSED 2026-08-12.**
   Each surfaced a separate pre-existing bug (OpenCode model deletion;
   aider model-settings staleness) — see the update box at the top.
2. **`-y` for `handle_config_file`.** The `[k/b/d/a]` prompt has no
   assume-yes bypass, so non-TTY callers always take `k`. That is now
   the *right* default (post-Q10) rather than a trap, so it is no longer
   urgent — but a scripted run still cannot choose `[b]`.
3. ~~**Web-UI Defect 3.**~~ **DONE 2026-08-12** (`14fc693`), along the
   line this item recommended: report honestly rather than verify
   remotely. `status.py` gained `tunnel_destination()` (a local mirror
   of the engine's `local_tunnel_destination` — `lsof` + `ps`, no
   network), `/api/status` exposes `verified_node` which is `null` when
   unknown and never falls back to the cache, and the UI renders
   `unverified` instead of naming an unconfirmed host. Two corrections
   to this item as originally written: the file is
   `src/argo_anywhere/status.py`, not `web/status.py`; and the lit node
   hop was driven by `local_listeners()` (an `lsof` scan), not by
   `channel_health()` — so the rendered claim rested on even less
   evidence than this item assumed.

### 5.2 Needs the maintainer

4. **Q1 / Q3 — the transport decision.** Option A (Unix socket) vs
   Option B (hardened TCP). See §9 of the note. My reading: Option A is
   structurally better *and* closes a documented `SECURITY.md`
   non-defense in both directions, but the socket path must be
   `/tmp/argo-anywhere-$(id -u)/`, **not** `/run/user` (`Linger=no`
   destroys it at last logout while `KillUserProcesses=no` keeps the
   proxy alive → live proxy, dead socket) and **not** `~/.argo_anywhere/`
   (NFS-shared; an orphaned socket file wedges later `bind()`s with
   `EADDRINUSE`).
5. **Defect 5b — warm-path identity.** Narrow race (our proxy dies
   mid-session, a co-tenant takes the freed port). Costs an SSH round
   trip, **measured at ~0.75s** over a warm mux. Fine for
   `connect`/`configure`; **not** for `status`, which people run
   casually.
6. **Q7 — notify the co-tenants.** Whoever holds `:64742` on
   `compute-386-01` is *currently* receiving other people's traffic
   under their own Argo identity. People problem, not a code problem.

### 5.3 Housekeeping the maintainer should decide

- **`PLAN.md` has no record of this work.** Zero matches for
  `shared_node_transport`, `_listener_is_ours`, or the bind test. Five
  defects were fixed with no design-decision number. **The D-number is
  contended**: `impl_channel_persistence.md` and
  `impl_shared_node_transport.md` both claim D-034, and D-033 is already
  taken by the 2026-07-22 ControlPersist decision. Resolve before
  assigning. **— RESOLVED 2026-08-12: D-034 recorded in `PLAN.md` for
  the shared-node work; the other two notes moved to D-035 / D-036.**
- **`CHANGELOG.md` has 9 entries under `## Unreleased`.** Needs a
  version decision at release time.

---

## 6. Operational cautions (read before touching the node)

- **Do not run `stop` or `clean`.** Both target `$PROXY_PORT` and the
  mux master — i.e. the maintainer's live channel.
- **Do not run a plain `connect`/`client` against `compute-01`.**
  `SCREEN_SESSION="argovproxy"` is a single global name, so a second run
  offers to replace the running proxy.
- **To test safely**: use a *different node* and a *different port*
  (`--node compute-02.cels.anl.gov --port 64801` worked). Distinct
  machines: `compute-01` → `140.221.27.4`, `compute-02` → `.10`.
- **To test launch/wait logic without any node change**: extract the
  engine's own functions by regex and run them under a sandbox
  (`SCREENDIR=/tmp/...`, distinct session name, copied config). Proven
  isolation — a sandboxed `screen -S argovproxy -X quit` returns
  `No screen session found` while the real session survives.
- **SSH hygiene**: probes must reuse the existing master
  (`-o ControlMaster=no -o ControlPath=<sock> -o BatchMode=yes`) so no
  new authentication is attempted. A streak of failed auths risks a CSPO
  IP block.
- **`$HOME` is NFS shared across all CELS compute nodes.** Anything
  under it (`~/.config/argoproxy/config.yaml`, `~/argovenv`,
  `REMOTE_SELF`, `REMOTE_LOG`) is one copy for every node.
- **Backups from the live test are still on disk**:
  `/tmp/argo_livetest/backup/` plus a standalone `RESTORE.sh`. Safe to
  delete once the maintainer is happy; `/tmp` clears at reboot anyway.

---

## 7. Corrections to claims made earlier in the session

Recorded because they are in the git history and would otherwise
mislead:

- **"A warm-mux round trip costs tens of milliseconds"** — wrong by
  ~25×. **Measured 0.75s.** This is what rules out per-`status` checks.
- **"The warm path is unguarded"** — too strong. For
  `ours-healthy-fg`/`mux`, the tunnel is ours (our `0700` mux socket),
  its destination host is pinned by the P3 check, and its far-end port
  is fixed by the `-L` spec at creation. Only `external-healthy` was
  genuinely open, and that shipped as 5a.
- **"`/run/user` is the natural socket home"** — falsified by the live
  probe (`Linger=no`). See §5.2 item 4.

---

## 8. Where to look

| Question | File |
|:---|:---|
| Why any of this exists; all five defects; the open questions | [`impl_shared_node_transport.md`](impl_shared_node_transport.md) |
| Engine invariants an editor must not break | `AGENTS.md` — "No-interactive-prompt", "Identity-before-success", "Bind-test oracle" |
| Threat model + what is now defended | `docs/SECURITY.md` (co-tenancy section, rewritten) |
| How to live-test | `docs/TESTING.md` (on-node test 5, corrected) |
| Upstream argo-proxy findings | `docs/AUDIT_2026-08-10_argo-proxy-upstream.md` + [`impl_upstream_hardening.md`](impl_upstream_hardening.md) |

---

*Created 2026-08-10 by Ahmed Attia (with substantial AI assistance from
Claude per [`CONTRIBUTORS.md`](../CONTRIBUTORS.md)). Written at the end
of the session it describes, for a fresh-eyes continuation.*
