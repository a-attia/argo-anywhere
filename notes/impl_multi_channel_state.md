# Two channels at once: the saved port and node are single-slot

**Status**: **recorded for a larger next release** (2026-11-19). Not
scheduled, no code, no decisions locked. Takes the next free D-number
if it ships. It may instead be folded into D-035 (the local/remote port
split), which already lists the port and node caches as open questions.
**Linked PLAN.md sections**: D-006 (one channel at a time, accepted),
D-020 (port is transport state), D-035 (local/remote port split,
planned), §11 Open questions item 4.

## TL;DR

The v3.6.1 live test ran two channels concurrently (compute-386-01 and
compute-386-02, on two local ports). That is exactly what the per-node
data-dir fix (D-037) is meant to make safe. The engine itself handled it,
but argo-anywhere's own saved state did not. That state is one port and
one node, `~/.config/argo_anywhere/{port,node}`, so every `connect`
overwrites what the previous one saved. This produced two surprises in
one session:

1. **A one-off `--port` becomes the default for every later connect.**
   `connect --node compute-02 --port 64753` saved 64753. A later
   `connect --node compute-01` with no `--port` then used 64753 for
   compute-01, and the next compute-02 connect hit the wrong-node guard
   ("existing tunnel ... targeting 'compute-01'"). The guard was correct.
   The user had not asked for 64753 on compute-01.
2. **The last connect wins the saved node and port.** After the second
   channel came up, the cache said `compute-02` / `64743`. Client configs
   were *not* rewritten (verified: their timestamps predate the run), but
   they point at a port, not a node. opencode and aider at
   `localhost:64743` silently moved from compute-01's proxy to
   compute-02's, and a bare `status` described compute-02 only.

Neither case loses data or misroutes billing, since both proxies belong
to the user. Both, though, are the shape of problem this project keeps
paying for: saved state that disagrees with what the user believes is
running (compare the 2026-08-12 stale-cache incident in D-034/D-035).

## What "fixed" could mean

These options are not mutually exclusive. They are listed so the next
cycle starts from a menu, not a blank page.

| Option | Change | Cost / risk |
|:-------|:-------|:------------|
| **A. Don't persist one-off ports** | `--port` affects this run only; only an explicit choice (`[m]igrate` at the port prompt, `configure`) saves it | Small. Changes D-020 semantics: users who rely on "last port sticks" lose it. Needs a CHANGELOG callout. |
| **B. Make the overwrite visible** | When `connect` is about to replace a saved port/node that still has a **live** channel, say so ("saved default moves from compute-01:64743 to compute-02:64753; the compute-01 channel stays up") | Small, no semantic change. Treats the symptom. |
| **C. Per-channel state** | Key the cache by local port: `{port → node, user, opened_at}`. `status` with no flags lists all live channels; `stop`/`status --port N` pick one | Large. It is the D-006 decision reversed, and it touches `status`, `stop`, `clean`, the web UI's channel discovery and diagram, and the D-021 coherence checks. Overlaps heavily with D-035, which already has to change the port cache's shape. |
| **D. Per-node local port** | Derive the local port from the node, so two nodes never contend for one local port | Reintroduces client-config churn whenever the user switches nodes. That is the very thing D-035 is trying to remove. Probably rejected; recorded for completeness. |

**Recommendation for discussion.** Ship B early, since it is cheap and
honest. Decide A together with D-035, because both redefine what the
port cache means. Design C only if concurrent channels become a routine
workflow rather than a test setup. Today the evidence is one maintainer
test session.

## Open questions

1. Is running two channels at once a real workflow for anyone besides
   testing? The answer decides between B and C.
2. If A ships, where does "my usual port" live? Today the port cache *is*
   that preference, so removing the implicit save needs an explicit home
   for it.
3. Should `status` warn when client configs point at a port whose tunnel
   goes to a different node than last time? This is the silent move in
   gap 2. It needs a per-port node record, i.e. a small slice of C.
