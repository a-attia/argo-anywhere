# Implementation plan -- top-level Connect CTA vs. launcher-form coherence

**Status**: designing (no code committed).
**Owner**: Ahmed Attia. **Last updated**: 2026-07-16.
**Target repo**: <https://github.com/a-attia/argo-anywhere>.
**Linked PLAN.md sections**: D-031 (web-UI Channel + Utility panels;
top-level CTA lives in the Channel card). No new D-decision required
if only the "visible signal" fix ships; would earn a D-decision if the
label-based approach ships as a UX contract.

## Contents

- [1. Purpose](#1-purpose)
- [2. What the gap is](#2-what-the-gap-is)
- [3. Why the current split is defensible](#3-why-the-current-split-is-defensible)
- [4. Options](#4-options)
- [5. Open questions](#5-open-questions)
- [6. What we should NOT do](#6-what-we-should-not-do)
- [7. Impacts + blast radius](#7-impacts--blast-radius)
- [8. Action items](#8-action-items)

## 1. Purpose

Decide whether — and how — to close the UX gap between the top-level
**Connect** CTA (in the Channel card) and the launcher popover's SSH
target overrides (in the Actions popover). Today the two are
architecturally independent by design; users have expressed no problem
yet, but a foreseeable footgun exists and D-032's preview panel makes
it slightly worse than before.

Not a bug fix. Not scheduled. Written to give the CTA-vs-form
conversation a shared factual baseline before code.

## 2. What the gap is

Two UI entry points open a channel:

- **Top-level Connect CTA** (`#connectBtn`,
  `src/argo_anywhere/web/static/index.html:310`) → handler at
  index.html:884 → `openTerminal('verb=connect', 'connect')` → WS URL
  `ws://.../ws?verb=connect`. **The query string is the whole
  payload.** No `node`, no `user`, no `jump_host`, no `no_jump`, no
  `cwd`.

- **Actions popover → Launch (verb=connect)** (`#doLaunch`,
  index.html:1394) → builds a full `URLSearchParams` (index.html:1398-
  1406) from every field the user set → WS URL
  `ws://.../ws?verb=connect&cli_tool=X&scope=Y&cwd=Z&node=A&user=B&
  jump_host=C&no_jump=1`.

**Both** hit the same `/ws` handler, both spawn `panel.open` on the
Channel slot, both spawn the same engine verb. The difference is entirely
in the argv the engine receives:

```text
CTA        → argv = ["connect"]
Actions    → argv = ["--cli-tool", X, "--scope", Y, "--node", A, "--user", B,
                     "--jump-host", C, "--no-jump", "connect"]
```

The CTA has NO way to send overrides. The Actions form has NO way to
influence the CTA's argv. **Values typed in the Actions form's SSH
target overrides are silently ignored if the user closes the popover
and hits the top-level CTA.**

The pre-D-032 world had the same asymmetry but with fewer visible
fields (the popover only had `cli_tool` / `scope` / `cwd`), and no
preview panel. D-032 added `node` / `user` / `jump_host` / `no_jump`
AND a "Show resolved launch" preview panel that displays what the
form-driven Launch WOULD produce. That preview reinforces the mental
model "these values are now committed" — but only for a Launch, not
for the CTA. The gap didn't get wider; it got sharper.

## 3. Why the current split is defensible

Three principles the current design gets right, and any fix must
preserve:

1. **CLI parity for the fast path.** The CTA is optimised for the
   returning user: cached identity + node + port; one click; tunnel
   up. Its argv (`["connect"]`) is exactly what a terminal user gets
   from typing `argo-anywhere connect` alone. Deterministic from disk
   state. No hidden form-state coupling.

2. **Ephemerality of the form.** The launcher popover's fields are a
   form, not persistent settings. Their state dies with the popover;
   only the explicit **Launch** click commits them. Making the CTA
   read the form's live values would turn ephemeral form-state into
   sticky config, in the ONE place a user is least expecting it.

3. **No hidden state.** A user reasoning about the CTA today can
   answer "what will this run?" from `~/.config/argo_anywhere/{node,
   user,port}` and their env alone. If the CTA started consulting
   `lNode`/`lUser`/`lJump`, the answer would depend on invisible
   in-tab form state that could be minutes stale, browser-cache-
   corrupted, or set by an accidental focus-and-type in a background
   tab.

The gap exists because these three principles are architecturally
correct. The fix cannot violate them.

## 4. Options

Four possible fixes, ordered from smallest to largest.

### (a) Do nothing — cheap, defensible

The gap is real but no user has reported confusion. `connect`'s
cache-driven behavior is well-established (v3.0 pre-dates any of
these fields). Preview + Launch sit next to each other in the popover;
a user who typed overrides and saw the preview is one click away from
the correct action.

**Cost**: zero.
**Trade-off**: known footgun stays open. First user hits it, files an
issue, we revisit. Cheap to defer; may become non-cheap to explain.

### (b) Rename the CTA to signal cache-driven behavior

Change the button label from `Connect` to `Quick connect` or `Connect
(cached)`. Sets user expectations universally, not only for the
overrides-set case. Costs one word; addresses more confusion classes
than (c) at less UI risk.

**Cost**: label change + adjacent hint text in the CTA's `.sub` span
("Establish the channel — Duo runs in the terminal below." →
"Quick-connect using your cached identity + node; Duo runs in the
terminal below.").
**Trade-off**: risks a returning user thinking "quick connect" means
something less-safe than plain Connect (it doesn't; it's just faster
because there's nothing to override). Recovers via the hint text.
**Preserves all three §3 principles.**

### (c) Visible signal on the CTA when overrides are set

Detect any non-empty value in `lNode`/`lUser`/`lJump`/`lNoJump` and
render a hint on the CTA: "using defaults; Actions has overrides
set." The other agent's original proposal.

**Cost**: one JS handler on each of the four form fields + one
render pass on the CTA. Modest.
**Trade-off**:
  - **Defining "overrides set" is fraught.** Any non-empty field?
    Only fields that would produce a divergent launch (e.g. typing
    `--node polaris-login` when `polaris-login` == cached node
    produces no divergence)? The cheap definition is "any non-empty";
    the correct definition requires evaluating divergence, which
    re-couples the CTA to the form state — the exact coupling §3
    Principle 2 says we cannot pay.
  - **Signal lifetime is ambiguous.** Fires on every keystroke? Only
    after a Launch is clicked and cancelled? Persists after the
    popover is dismissed? Each answer prescribes a different user
    mental model for what "in effect" means.
  - **Reads live form state**, which is the exact hidden state
    Principle 3 was set up to avoid.

Preserves Principle 1 (CTA still cache-driven) and Principle 2
(form still ephemeral — the CTA reads it but doesn't commit it) but
violates Principle 3 (the CTA's presentation now depends on
invisible form state).

### (d) Merge the CTA into the launcher popover (delete the top-level CTA)

Remove the Channel-card CTA entirely. The only way to connect is
Actions → connect. Eliminates the gap by removing the gap-having
surface.

**Cost**: removes the fast-path most users rely on. Deep UI
restructure. Would require a corresponding "quick launch defaults"
mode in the popover to preserve one-click behavior. Very high blast
radius across D-031.
**Trade-off**: over-engineered for the observed problem. Not
recommended.

## 5. Open questions

Blocking; each is the maintainer's call.

1. **Have any users reported this?** The gap is theoretical; the fix
   cost depends on whether it's observed. If no user has hit it in
   v3.2.x's real-world use, option (a) is the correct answer for now.
2. **If a fix ships, is it label-only (b), or behavior-adjacent (c)?**
   The choice hinges on whether we treat the "overrides typed then
   ignored" scenario as a user-education problem (b) or a UI-signal
   problem (c). Not both.
3. **Does the Channel-card `.sub` hint counts as chrome we own?** The
   current "Establish the channel — Duo runs in the terminal below."
   line is already prescriptive. Extending it (option b) is a small
   edit; introducing an amber alert-style visible signal to it
   (option c) changes its role.
4. **Cross-cutting with `impl_channel_persistence.md`**: that note's
   §5.(c) "detached channel mode" would introduce a THIRD channel-
   opening entry point (`connect --detach`). If (c) ships, does the
   detached mode ALSO get the visible-signal treatment? Answer likely
   depends on which of (b)/(c) is chosen here.

## 6. What we should NOT do

For the record, so a future refactor doesn't quietly reintroduce
these:

- **Do NOT make the CTA read form values without an explicit design
  decision.** Doing so silently couples the CTA to the form,
  violating §3 Principle 2 and 3. Cost of getting this wrong: an
  unpredictable CTA that depends on invisible state. Option (c) does
  this deliberately + with UX signaling; a silent implementation
  would just be a bug.

- **Do NOT tighten the `/ws` handler's blank-cwd branch into a hard
  reject.** The top-level Connect CTA (this note's whole subject)
  legitimately sends no cwd; hard-rejecting blank cwd there would
  break the primary CTA the moment someone rewrote the "backward
  compat" comment as "no living UI caller does this." The comment at
  `src/argo_anywhere/web/app.py:831` was corrected in the same commit
  that landed this note to explicitly name the CTA as the live
  no-cwd caller, so this trap should not spring twice. Do not
  re-tighten.

## 7. Impacts + blast radius

**Option (a)**: zero.

**Option (b)** (label change): touches
`src/argo_anywhere/web/static/index.html:310-311` only. No JS, no
server, no tests. Screenshot regeneration (`scripts/screenshots.py`)
would eventually want to pick up the new label; not a blocker.

**Option (c)** (visible signal): touches `index.html` for the four
new field listeners + CTA render pass. Adds one JS function of the
same shape as `updateOverridesHint` (`index.html:1082`). Would want a
test asserting the signal appears/disappears with field content. Zero
server change.

**Option (d)** (merge): touches large sections of `index.html`
including the Channel card + launcher popover + several handlers.
Would require a UX design pass first. Not recommended.

## 8. Action items

None scheduled. This note exists so the CTA-vs-form question has a
shared baseline for the next launcher-review session. Also:

- ~~**Done**: `/ws` handler comment at `web/app.py:831` corrected in
  the same commit that landed this note.~~ Prevents the tightening
  regression called out in §6.
- **If any user reports the footgun**, revisit §4 with the specific
  scenario in hand — the choice between (b) and (c) is easier when
  there's a concrete misuse to learn from.

## Related

- `notes/impl_channel_persistence.md` — the persistence-discussion
  pile this note joins. Shares the same underlying tension (top-
  level CTA behavior vs. launcher-form state).
- `notes/impl_command_echo.md` — a different debuggability lever for
  the same class of "wrong argv silently sent" concerns.
- `PLAN.md` D-031 (web-UI launcher + Channel card) and D-032 (SSH
  target overrides in the launcher popover).

---

*Created 2026-07-16 by Ahmed Attia (with substantial AI assistance from
Claude per `CONTRIBUTORS.md`). Design record, not a plan-of-record.*
