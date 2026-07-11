# Implementation plan -- lifecycle commands (connect / configure / run) + symmetric install / uninstall + install manifest

**Status**: Phase A (manifest) + Phase B (verbs) + Phase C
(install/uninstall) IMPLEMENTED + **LIVE-TEST GATE PASSED 2026-07-09**
(all 10 tests in `notes/test_plan_lifecycle.md`; 7 amendments landed
mid-test; real `~/.argo_anywhere` migrated to bin/ layout with the
channel up throughout). Decisions locked 2026-07-08. Two deferred items:
Test 4's full `--ensure` channel-down bring-up (needs from-scratch run)
+ the per-tool `update_models` refresh follow-up (filed in PLAN).
**Owner**: Ahmed Attia (with AI assistance per `CONTRIBUTORS.md`).
**Last updated**: 2026-07-09.
**Target repo**: <https://github.com/a-attia/argo-anywhere> (single-file
`argo_anywhere.sh`).
**Linked PLAN.md sections**: Section 2 (subcommand surface), Section 7
(design decisions -- adds D-024 + D-025), Section 4 (roadmap phases).

## Purpose

Reshape argo-anywhere's UX around the three levels it actually manages,
and make install/uninstall symmetric and honest. Two coupled changes:

1. **Split the workflow into explicit verbs** (`connect` / `configure` /
   `run`) mirroring the three levels, so users can hold the shared
   channel in one window and configure/run clients freely in others.
   `client` / `setup` stay as fused one-shot fallbacks (backward compat).
2. **Symmetric install/uninstall** anchored at a canonical
   `~/.argo_anywhere/bin/` layout, with an **install manifest** so
   `uninstall` can correctly restore client configs to their
   pre-argo-anywhere state.

## The three-level model (verified 2026-07-08)

argo-anywhere manages three levels; the current `client` command fuses
levels 1 + 2 and names the fused thing after the level-2 choice
(`--cli-tool`), which is the source of the "why do I pick one tool when
the channel serves all of them?" confusion.

| Level | What | Cardinality | Today | New verb |
|:------|:-----|:------------|:------|:---------|
| 1 | Channel: SSH tunnel + remote argo-proxy (venv + `serve`) | **shared / singular** per (user, node, port) | `tunnel`, or front half of `client` | `connect` |
| 2 | Install + write config for ONE client | **one tool per invocation** (our convention, not a proxy constraint) | `--cli-tool X client` / `setup` | `configure <tool>` |
| 3 | User runs clients; many tools + sessions, concurrent, reusing the one channel | **many** | (not the script's job) | `run <tool>` = configure + exec |

Key facts that make the split cheap:

- Level 1 is **ensure/reuse**, not always establish (the code already
  reuses an existing tunnel/master -- "Found existing tunnel ... reusing
  without taking ownership").
- Level 2's one-tool-at-a-time is purely our orchestrator's UX
  convention. The transport + argo-proxy serve all clients
  simultaneously, so multi-tool configuration is a free change at the
  transport level.
- The internals are already separated: `tunnel` = level 1;
  `do_post_tunnel_for_cli_tool` = level 2. The verb split is largely a
  re-mapping, not new transport code.

## Locked design decisions (2026-07-08)

- **D-a -- install/uninstall are SUBCOMMANDS, not standalone scripts.**
  Preserves D-001 (single-file distribution). The `bin/install` and
  `bin/uninstall` files are thin wrappers that call
  `argo_anywhere.sh install` / `uninstall` for discoverability.
- **D-b -- uninstall is TIERED** (Tier 3 binaries opt-in):
  - Tier 1 (always, on confirm): canonical `~/.argo_anywhere/`, `env`,
    state dir, local tunnels/sockets.
  - Tier 2 (per-item prompt / `--restore-configs`): restore client
    configs to pre-argo-anywhere state via the manifest (D-c).
  - Tier 3 (opt-in `--remove-binaries`): uninstall tool binaries
    (opencode/claudecode/aider) ONLY if we installed them. Off by
    default (users may use these tools independently).
  - Tier 4 (opt-in `--remote`): the compute-node venv (what `clean`
    already does remotely).
- **D-c -- adopt an INSTALL MANIFEST** so "restore original config" is
  correct, not best-effort. Written by the shared config-touch path;
  read by uninstall.
- **D-d -- uninstall REUSES clean's logic** for overlapping scopes
  rather than duplicating the risky-file decision tree.
- **D-e -- configure/run DETECT an existing channel and fail loud with a
  hint** if absent; opt-in `--ensure` brings the channel up (bridges to
  one-shot).

## Public API surface (new)

New subcommands (additive; existing verbs unchanged):

| Subcommand | Level | Behavior |
|:-----------|:------|:---------|
| `connect` | 1 | Ensure the channel (tunnel + remote proxy), then hold the foreground monitor. Effectively the current `tunnel` behavior; `connect` is the friendlier name (`tunnel` retained as alias). |
| `configure <tool> [<tool>...]` | 2 | Install + write config for the named tool(s) against an EXISTING channel. Detects the channel via port cache + `/health`; fail-loud-with-hint if absent (D-e). `--ensure` brings it up if missing. Multi-tool per call (level-1 is shared). |
| `run <tool>` | 2+3 | `configure <tool>` then `exec` the tool binary. `--ensure`-by-default-with-prompt (a fresh-terminal `run aider` should "just work"). |
| `install` | -- | Materialize `~/.argo_anywhere/bin/`, write `env`, print PATH hint. Explicit form of today's implicit bootstrap. `--dry-run`. |
| `uninstall` | -- | Tiered teardown (D-b) + config restore via manifest (D-c) + reuse clean (D-d). `--dry-run`, `--restore-configs`, `--remove-binaries`, `--remote`, `-y`. |

Retained unchanged (backward compat / one-shot fallback):

- `client` (fused level 1+2), `setup` (client + always-picker),
  `tunnel` (level 1; `connect` alias), `server`, `status`, `stop`,
  `update`, `update-models`, `list-models`, `clean`, `list-tools`,
  `help`.

## Canonical install layout (new; extends D-023)

Today D-023 puts `argo_anywhere.sh` + `env` directly in
`~/.argo_anywhere/`. The new layout adds a `bin/` dir + a manifest:

```text
~/.argo_anywhere/
├── bin/
│   ├── argo_anywhere.sh      the script (canonical install)
│   ├── install               thin wrapper -> argo_anywhere.sh install
│   └── uninstall             thin wrapper -> argo_anywhere.sh uninstall
├── env                       sourceable PATH helper (now points at bin/)
├── manifest.json             install manifest (D-c)
└── (state stays at ~/.config/argo_anywhere/ for now; see Open questions)
```

Migration: an existing `~/.argo_anywhere/argo_anywhere.sh` (D-023 flat
layout) is moved into `bin/` on the next `install` / bootstrap; `env` is
rewritten to point at `bin/`. The `update argo-anywhere` self-update path
must target `bin/argo_anywhere.sh`.

## Install manifest (D-c) -- the foundation

**Problem.** "uninstall restores original client configs" requires
knowing, per config file, whether argo-anywhere CREATED it (restore =
delete) or MODIFIED a pre-existing file (restore = the earliest,
pre-argo-anywhere backup). The current `.bak.<ts>.<pid>` backups don't
record which one was the pre-argo-anywhere original vs a later re-run's.

**Solution.** A manifest at `~/.argo_anywhere/manifest.json` recording,
at FIRST touch of each config, the provenance:

```json
{
  "schema": 1,
  "installed_at": "2026-07-08T...",
  "configs": {
    "/Users/x/.aider.conf.yml": {
      "first_touched": "2026-07-08T...",
      "preexisted": true,
      "original_backup": "/Users/x/.aider.conf.yml.bak.20260708-....",
      "created_by_us": false
    },
    "/Users/x/.aider.model.settings.yml": {
      "first_touched": "2026-07-08T...",
      "preexisted": false,
      "original_backup": null,
      "created_by_us": true
    }
  },
  "binaries": {
    "aider": {"installed_by_us": true, "path": "/Users/x/.local/bin/aider", "method": "standalone"}
  }
}
```

Written by the shared config-touch path (in / around `handle_config_file`
and the writers) -- record an entry the FIRST time we touch a given path,
never overwrite an existing manifest entry (first-touch wins = the true
original). `install` seeds `installed_at`. `uninstall` reads it:

- `created_by_us: true` -> delete the file on restore.
- `preexisted: true` with `original_backup` -> restore that backup.
- Binary entries with `installed_by_us: true` -> eligible for Tier 3.

This is new machinery but it is the only way to make uninstall's
config-restore HONEST rather than a guess. It also cleanly records which
binaries we installed (Tier 3) vs which the user already had.

## Design

### Verb split (Phase B) -- mostly re-mapping

- `connect` -> call the existing level-1 path (what `tunnel` runs):
  resolve node/port, ensure tunnel + remote proxy, enter monitor loop.
- `configure <tool>...` -> for each tool: detect channel (port cache +
  `GET /health`); if absent and no `--ensure`, die with a hint
  (`run 'argo_anywhere.sh connect' first, or pass --ensure`). If present
  (or `--ensure` brought it up), call `setup_<tool>_cli_tool` +
  summary. Does NOT enter the monitor loop (the channel is someone
  else's -- typically the `connect` window's).
- `run <tool>` -> `configure <tool>` (with ensure-by-default-prompt),
  then `exec <tool-binary>` so the user drops straight into the client.

The "detect existing channel" check is the one genuinely new bit: a
small helper `channel_is_up <port>` = port-cache resolve + `/health`
probe (the status path already has the pieces).

### install / uninstall (Phase C)

- `install`: promote `maybe_bootstrap_canonical_install` into an explicit
  subcommand with the `bin/` layout + `--dry-run` + beautified output
  (scicomp-research-skills style: show each action, dry-run previews the
  plan). Bootstrap-on-first-`client` stays (calls the same core) for the
  curl-and-run flow.
- `uninstall`: tiered (D-b), manifest-driven config restore (D-c),
  reuses clean's scopes (D-d). Self-removal of `~/.argo_anywhere/bin/`
  (the script deleting its own dir) handled by ordering dir-removal last
  and/or copying the teardown to a temp location -- decide at
  implementation time (Risks).

## Trade-offs considered

1. **Subcommands vs standalone install/uninstall scripts (D-a).** Chose
   subcommands to preserve D-001. Thin `bin/` wrappers give the
   discoverability of real `install`/`uninstall` files without
   fragmenting the source. The wrappers are 2-3 lines each.
2. **Manifest vs best-effort backup-restore (D-c).** Chose the manifest.
   Best-effort ("restore the oldest `.bak`") is wrong when a user
   re-runs the script multiple times (later backups aren't the
   original) or when we created the file (there's no backup to restore;
   the right action is delete). The manifest makes provenance explicit.
   Cost: new write path in the config-touch flow; must be first-touch-
   wins and robust to partial writes.
3. **configure detects vs establishes the channel (D-e).** Chose
   detect-with-hint. The entire point of the split is that `connect`
   owns the channel + monitor in one window; if `configure` silently
   established its own channel it would fragment ownership and confuse
   the single-instance model (D-006). `--ensure` covers the one-shot
   case explicitly.
4. **New verbs vs renaming existing ones.** Chose additive verbs +
   keep `client`/`setup`/`tunnel`. Renaming would break shell aliases +
   docs + muscle memory; the audit/UX cost isn't worth it. `tunnel`
   stays as a `connect` alias.
5. **Binaries removed by default vs opt-in (D-b Tier 3).** Opt-in.
   Removing a binary the user relies on outside argo-anywhere is a
   worse failure than leaving an unused binary behind. The manifest's
   `installed_by_us` gate makes even the opt-in safe (we never remove a
   binary the user already had).

## Testing plan

Each phase gates on the project's live-verification discipline
(real SSH + Duo + argo-proxy). Per-phase:

**Phase A (manifest):** unit-test the manifest writer (first-touch-wins;
records preexisted vs created; robust to re-runs); confirm existing
config writers still produce identical output; no behavior change
visible to users yet.

**Phase B (verbs):** `connect` holds the channel + monitor;
`configure aider` in a second terminal detects the channel and writes
config WITHOUT a second tunnel; `configure` with no channel dies with
the hint; `--ensure` brings it up; `run aider` drops into aider;
multi-tool `configure opencode aider`; `client`/`setup`/`tunnel`
regression (unchanged).

**Phase C (install/uninstall):** `install --dry-run` previews;
`install` builds `bin/` + env + manifest; migration from D-023 flat
layout; `uninstall --dry-run` previews the full teardown; `uninstall`
Tier 1; `--restore-configs` restores a pre-existing config to its
original + deletes a we-created config; `--remove-binaries` removes only
we-installed binaries; `--remote` handles the venv; self-removal of the
canonical dir works; re-install after uninstall is clean.

## Risks

- **Manifest correctness (HIGH).** If the manifest is wrong, uninstall
  restores the wrong thing (or deletes a user file). Mitigations:
  first-touch-wins (never overwrite an entry); atomic manifest writes;
  uninstall always `--dry-run`-previewable; never delete without the
  manifest saying `created_by_us: true` or a confirmed backup exists.
- **Self-removal during uninstall (MEDIUM).** The script deleting its
  own `~/.argo_anywhere/bin/argo_anywhere.sh` mid-run. Mitigation: order
  the canonical-dir removal last, or copy the teardown to a tempfile and
  re-exec it for the final self-delete. Decide at implementation.
- **D-023 layout migration (MEDIUM).** Users with the flat
  `~/.argo_anywhere/argo_anywhere.sh` must migrate to `bin/` cleanly;
  `update argo-anywhere` + `env` must both follow. Mitigation: detect
  the flat layout and migrate on `install`/bootstrap; keep `env`
  idempotent.
- **configure-without-channel edge cases (LOW).** Port-cache says a
  channel exists but `/health` fails (stale). Mitigation: the
  `channel_is_up` helper probes `/health`, not just the cache.

## Sequencing (agreed)

Do them in dependency order, since the verbs and uninstall SHARE the
config-touch path that the manifest instruments:

1. **Phase A -- manifest foundation** first. Instrument the shared
   config-touch path. No user-visible behavior change; pure foundation.
2. **Phase B -- verb split** (connect/configure/run). Re-maps existing
   internals; adds the channel-detect helper.
3. **Phase C -- bin/ layout + install/uninstall**. Consumes the manifest
   (config restore) and the clean logic (D-d) and the verb
   infrastructure.

Each phase is independently shippable and independently live-tested.

## Action items

1. Record D-024 (verb split) + D-025 (manifest + symmetric uninstall) in
   PLAN.md Section 7; add roadmap phases -- **done** (2026-07-08).
2. Phase A: manifest schema + writer in the shared config-touch path --
   **done** (2026-07-09; `argo_anywhere.sh`). Added `ARGO_MANIFEST` +
   `ARGO_MANIFEST_SCHEMA` constants; new Section 10b with
   `_manifest_available` (python3 + not-on-node guard),
   `manifest_record_config` (first-touch-wins, atomic, best-effort), and
   `manifest_record_binary`; wired `manifest_record_config` into
   `handle_config_file`'s top (captures `preexisted` before any write)
   and `manifest_record_binary` into all three `ensure_<tool>_installed`
   success paths (opencode / claudecode / aider x3 methods). Smoke-
   tested: fresh -> created_by_us:true; pre-existing -> preexisted:true;
   first-touch-wins on re-run (entry + first_touched unchanged); binary
   first-touch-wins; compute-node guard suppresses the write; existing
   config writers byte-identical (0 manifest calls in any writer body).
   No user-visible behavior change (record-only). Live-test gate still
   pending (the manifest becomes load-bearing only when Phase C's
   `uninstall` reads it -- Phase A alone has no user-facing surface to
   live-test beyond "configs still write correctly", covered by smoke).
3. Phase B: connect/configure/run + `channel_is_up` helper + `--ensure`
   -- **done** (2026-07-09; `argo_anywhere.sh`). Added `channel_is_up`
   (/health probe on `$PROXY_PORT`); Section 17b with `mode_connect`
   (delegates to `mode_tunnel`), `mode_configure` (multi-tool; resolves
   username without a tunnel; `_configure_ensure_channel_or_die` detects
   the channel or dies with a `connect`-first hint, `--ensure` brings it
   up), `mode_run` (single tool; ensure-with-prompt default;
   `exec`s the client, `claudecode`->`claude`). Parser: `connect` /
   `configure` / `run` subcommands; `--ensure` flag; positional tool
   args for configure/run; consumes-`--cli-tool`/`--scope` lists +
   port-mismatch skip updated; usage text extended. `client` / `setup`
   / `tunnel` retained unchanged.

   **Live-verified against the real channel (port 64742, ALL GREEN):**
   `configure aider` DETECTED the up channel ("Channel is up ...
   reusing it") and configured WITHOUT opening a tunnel or a Duo prompt,
   returning instead of blocking in the monitor -- the core Issue-2 fix.
   `configure opencode aider` configured both against the one shared
   channel. `configure <tool> --port <dead>` (and thus no channel) died
   with the connect-first hint. Unknown tool names die cleanly.
   `client`/`tunnel` still reach their mode functions (regression).
   NOTE: `run`'s final `exec <client>` was not live-exec'd here (it would
   replace the test process); the configure-then-launch path is verified
   up to the exec, and the exec target resolution (claudecode->claude)
   is covered by inspection. Confirm in the Phase B live-test gate.
4. Phase C: `bin/` layout + install/uninstall subcommands + thin
   wrappers + D-023 migration -- **done** (2026-07-09; `argo_anywhere.sh`).
   Added `ARGO_INSTALL_BIN_DIR` (+ `ARGO_INSTALL_SCRIPT` now under `bin/`,
   `ARGO_INSTALL_SCRIPT_FLAT` for migration detection, wrapper-path
   constants); `_write_install_wrappers` (thin `bin/install` +
   `bin/uninstall` shims -> the subcommands, preserving D-001);
   `_install_core` (creates `bin/`, copies the script, writes wrappers +
   env, migrates the flat layout, stamps `manifest.installed_at`);
   refactored `maybe_bootstrap_canonical_install` to reuse it; env helper
   now prepends `~/.argo_anywhere/bin` (keeps the flat dir for back-compat);
   `canonical_install_present` accepts either layout; `mode_install`
   (plan box + `--dry-run` + beautified); `mode_uninstall` (tiered per
   D-b; manifest-driven restore per D-c via `_manifest_configs_to_restore`
   + `_manifest_binaries_we_installed`; reuses `_clean_rm` per D-d; flags
   `--restore-configs` / `--remove-binaries` / `--remote` / `--dry-run` /
   `-y`); parser + dispatch + usage wired; self-update auto-retargets to
   `bin/` (uses `ARGO_INSTALL_SCRIPT`).

   **Sandbox-verified (isolated HOME; no real infra touched):** install
   builds `bin/{argo_anywhere.sh,install,uninstall}` + env-at-bin + manifest
   stamp; `install --dry-run` previews + detects the flat-layout migration;
   `uninstall --restore-configs` DELETES a config we created and RESTORES a
   config we modified to its pre-argo original (from the `.bak`) --
   manifest-driven restore correct end-to-end; `--remove-binaries` removes
   only manifest-recorded (`installed_by_us`) binaries and leaves a
   user-installed one alone; self-removal (uninstall run from inside the
   canonical install) removes the dir cleanly.

   **Ownership-guard finding (2026-07-09, live-test methodology defect ->
   real code defect).** A sandboxed `uninstall` test killed the live
   shared channel on the real port, because the port probe (`lsof`) is
   machine-global even when HOME is sandboxed AND `mode_uninstall`'s
   Tier-1 listener-kill was UNCONDITIONAL. Fixed: Tier-1 now classifies
   the listener via `local_tunnel_status` (same guard `mode_stop` uses)
   and kills ONLY `ours-*` tunnels; an `external-healthy` /
   `other-or-broken` listener is left running with a warn. Verified: the
   live channel classifies as `ours-healthy-mux` (uninstall would
   correctly reclaim it); a foreign/shared listener now takes the
   refuse-and-warn branch. Testing discipline updated: never run non-dry
   `uninstall`/`stop`/`clean` against a port with a live channel;
   sandbox HOME **and** point `--port` at a dead port.
 5. Live-test each phase; update docs (README subcommand table,
    UPGRADING, AGENTS.md contract, this note) per phase -- **done**
    (2026-07-09): live-test gate PASSED (all 10 tests in
    `notes/test_plan_lifecycle.md`); docs updated (README, UPGRADING,
    AGENTS.md, PLAN.md, this note). Two deferred: Test 4 full `--ensure`
    channel-down bring-up + the per-tool `update_models` refresh
    follow-up (PLAN roadmap).

## Live-test amendments (2026-07-09, during the Test 1-2 run)

The live run surfaced four UX/correctness issues (Tests 1-2 both PASS on
their core criteria; these are quality fixes landed mid-test per the
project's amendment-mid-test cadence):

1. **Misleading scope-conflict text (all 3 tools).** The scope-switch
   prompt's description cited `handle_config_file`'s content-prompt
   letters (`[k/b/d/m/a]` / `[k/b/d/a]`) right above the scope prompt's
   own `[k/s/a]` -- conflating the two prompts' vocabularies (the exact
   D-015 confusion). Fixed: reworded `_opencode/_claudecode/_aider_check_conflicts`
   descriptions to say "a later prompt will ask how to handle the
   existing file" without leaking the other prompt's letters.
2. **Full status box re-rendered per tool during `configure`.** `configure`
   loops over tools and each `do_post_tunnel_for_cli_tool` arm printed
   the whole ALL-GREEN box -- noise when configuring against an
   already-up channel (and printed N times for N tools). Fixed: added
   `_post_tunnel_summary` (gated on `_SUPPRESS_PER_TOOL_SUMMARY`);
   `mode_configure` sets the flag and prints ONE concise closing line
   (`Configured: ...` + `Channel: http://localhost:PORT (healthy; ...)`).
   `client`/`connect`/`status` still show the full box.
3. **OpenCode-centric status box (Fix C).** The box said "Configured: N
   in opencode config" and listed only the OpenCode config path, ignoring
   Claude Code + aider. Fixed: the model-count row is now explicitly
   labelled "OpenCode models" (honest -- only OpenCode enumerates models
   in config) and only nudges when OpenCode is actually present; the
   Paths section now lists whichever client configs exist (OpenCode +
   Claude Code + aider). Root cause = these were written when OpenCode
   was the only tool (PLAN.md D-020 flagged it).
4. **`update-models` was silently OpenCode-only.** Made it tool-aware:
   `--cli-tool` (default `opencode` for back-compat); `claudecode`/`aider`
   get an honest "not applicable" message (they pick the model at runtime,
   no in-config list to refresh) instead of silently editing the OpenCode
   config. Follow-up filed in PLAN roadmap for a real per-tool
   `<name>_update_models` (regenerate aider's model-settings from live
   `/v1/models`).

Also a minor cosmetic fix: `connect` printed "(this is 'tunnel' mode)"
because `mode_connect` delegates to `mode_tunnel`; the message is now
verb-aware (`(this is '<invoked-mode>' mode)`).

5. **`run` still printed the full status box (Test 5 finding).** Fix B
   suppressed the box for `configure` but not `run` (which is configure +
   launch). `run` now sets `_SUPPRESS_PER_TOOL_SUMMARY=1` too -- it should
   be at least as quiet as `configure`, and it's about to hand off to the
   client's own UI, so a big box right before that is noise. Verified by
   inspection (same flag/gate as the live-verified `configure` path).

All four verified live against the running channel (port 64742). None
changed the core Test 1/2 pass status; they improve the output.

**Test-plan defect (2026-07-09, Test 8): unset `$SB` targets `/`.** When
Test 8's seed block ran in a shell where `$SB` was empty (the `export`
didn't carry across a new terminal), `"$SB/created.yml"` expanded to
`/created.yml` -- targeting the filesystem ROOT. It failed SAFELY (root
is read-only; nothing was written, the Test 7 sandbox stayed intact),
but it is the same unset-variable + machine-global-reach class as the
earlier connection-kill finding. Fix (test plan, not code): every
sandbox block now begins with a guard
(`SB=/tmp/...; : "${SB:?SB must be set}"; case "$SB" in /tmp/*) ;; *) refuse;; esac`)
so an empty/unexpected `SB` fails loudly before any write, and the
Test 9 cleanup `rm -rf "$SB"` is guarded the same way. Discipline
reinforced: sandbox tests must be robust to an unset isolation variable,
not just assume it carried across shells.

## Open questions

- Should the script's state (`~/.config/argo_anywhere/`) move under
  `~/.argo_anywhere/state/` for a single teardown root? Leaning no for
  now (avoids a migration + `clean` already sweeps it), but the manifest
  makes either location tractable. Revisit in Phase C.
- Should `configure` support `--cli-tool all` / a comma-list in addition
  to positional tool args? (Positional multi-tool is the plan; `all` is
  a nice-to-have.)
- `run <tool>` exec semantics under the mux master: `exec` replaces the
  script process, which is fine (the channel is owned by the `connect`
  window / mux master, not by `run`). Confirm no orphan-cleanup trap
  fires on `exec`.

---

*Created 2026-07-08 by Ahmed Attia (with substantial AI assistance from
Claude per `CONTRIBUTORS.md`). Design decisions D-a..D-e locked with the
user 2026-07-08; grounds on the existing D-023 canonical install and the
three-level model verified the same day.*
