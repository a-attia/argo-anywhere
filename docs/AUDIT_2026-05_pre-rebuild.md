# Audit 2026-05 — pre-Phase-3 (multi-client) baseline

> **HISTORICAL ARCHIVE (filed 2026-05-15 per audit finding I3)**.
> This audit was conducted in early May 2026 against the v1.x line
> (`argo_opencode.sh`, pre-rename) and is preserved here for
> provenance. The current audit-of-record is
> [`AUDIT_2026-05-12.md`](AUDIT_2026-05-12.md), which started after
> the v1.2.0 rename + revert sequence and the multi-client refactor
> introduced new findings that this earlier audit could not have
> seen (the script changed substantially between the two audits).
> The findings table below is documented for completeness; do not
> use it as a current to-do list. References to symbols / line
> numbers in this doc reflect the v1.x codebase before the v2.0
> rebuild and will not match the current `argo_anywhere.sh`.
>
> All findings from this earlier audit that remained relevant after
> the v2.0 rebuild were either (a) re-found and tracked in the
> 2026-05-12 audit, or (b) explicitly cross-referenced from
> 2026-05-12's "Cross-check against prior audit" section.

Structured audit of `argo_opencode.sh` after Phase 2 of the multi-client
work landed (collision-detection UX, `tunnel` subcommand, on-node
short-circuit, etc.) and before Phase 3 (Claude Code support + repo
symlinks) begins.

Goal: catch drift, dead code, doc/code mismatches, and latent bugs that
built up across the burst of fixes in Phase 0–2 + their follow-ups,
before piling new code on.

Three audit phases, plus one user-requested enhancement that landed
together.

## Phase 1 — code correctness (commit `578f246`)

Read the script end-to-end with three passes: section TOC vs reality,
function-by-function correctness, orphan/dead-code grep. Seven findings.

| # | Severity | Location | Finding | Fix |
|---|---|---|---|---|
| F1 | high | `ensure_or_reuse_tunnel` `ours-healthy` branch | captured the multiplex master's pid into `SSH_TUNNEL_PID` and armed `cleanup_local`'s trap to kill it on Ctrl-C, which would destroy other SSH sessions sharing the master | split into `ours-healthy-fg` (capture pid; safe to kill) vs `ours-healthy-mux` (clear pid; don't take ownership; return 2 so caller skips the destructive trap) |
| F2 | high | TOC at top of file | five sections had grown new functions that the TOC didn't mention (Section 5, 9, 12, 16, 17) | updated TOC entries |
| F3 | medium | comment refs to internal bug IDs (B12, B13, B14, B16, B17) | no glossary in the script after testing-guide rewrite | replaced each with descriptive phrase ("the duplicate-bootstrap-via-tee bug" instead of "B14") |
| F4 | medium | `_my_interface_ips` awk | redundant `sub()` after `gsub()` had already stripped the prefix | dropped |
| F5 | medium (root cause of F1) | `local_tunnel_status` | conflated three distinct cases ("ours-healthy" covered fg-tunnels AND mux masters AND argo-proxy) | split into 5 return values: `ours-healthy-fg`, `ours-unhealthy-fg`, `ours-healthy-mux`, `ours-unhealthy-mux`, `external-healthy` |
| F6 | low | standalone-server prompt text | confusing parenthetical ("no env vars from client") | rephrased |
| F7 | low | `mode_server` | actual bootstrap body starts ~130 lines into the function; no marker | added "BODY" comment marker |

## Phase 2 — docs sync (commit `1fbdbb0`)

Cross-checked usage(), long_help(), README, AGENTS.md, docs/TESTING.md,
examples/. Three findings.

| # | Severity | Location | Finding | Fix |
|---|---|---|---|---|
| D1 | medium | `AGENTS.md` Subcommands section | `tunnel` subcommand missing from the listing | added; expanded to per-command bullets |
| D2 | medium | `docs/TESTING.md` | only covered laptop-side `client` flow; on-node paths, multi-user collision, standalone server, on-node `stop` confirmation, SSH attempt tracker were undocumented | appended "On-node paths (Phase 2 additions)" with 6 targeted live-tests + pass criteria |
| D3 | low | `long_help` "RUNNING ON A COMPUTE NODE" | mentioned standalone `server` workflow but didn't explain the identity-resolution prompt | added paragraph on resolution order + `-y` bypass |

What was already correct (no changes needed):
- Subcommands consistent across main() dispatch / usage() / README table.
- All flags appear in main() parser, usage() per-flag descriptions.
- Env vars consistent across canonical-env block and per-flag mentions.
- examples/opencode_config.example.json matches what `write_opencode_config` produces.
- examples/argoproxy_config.example.yaml matches the writer's output and notes the preserved-keys behavior.

## Phase 3 — behavior verification (cheap local)

Eleven test groups, all run from this Mac (laptop side). Findings: **no
new bugs**.

What was verified:

1. **Subcommand exit codes**: `-h`, `help`, `status` (live tunnel) all return 0.
2. **Invalid argument**: `--bogus-flag` returns 2 with usage printed.
3. **`--port` validation**: `abc` → exit 1 with clear error; `999999` → exit 1 (out of TCP range); `64999` against missing tunnel → exit 1 (FAIL verdict in summary).
4. **`--port-range` validation**: `bogus` → exit 1 with `LO-HI` format guidance.
5. **`--keep-orphans` + `--drop-orphans` mutex**: rejected at startup with exit 1.
6. **`clean --dry-run` flag combinations**: `keep` (default under -y), `DELETE files + backups (--purge)`, `keep files, delete backups (--purge-backups)` all surface the right "Risky policy" line.
7. **Subcommand conflict**: `status client` → exit 1 with `[err ] Conflicting subcommands`.
8. **`--` terminator**: `status --` parses cleanly; subsequent args ignored as designed.
9. **Port resolution precedence**: `--port` flag overrides `ARGO_OPENCODE_PORT` env, which overrides `~/.config/opencode/config.json` baseURL, which overrides `PROXY_PORT_DEFAULT`. Verified by inspecting the "Port" row in the status box across three invocations.
10. **TOC accuracy after Phase 1 fixes**: 25/25 sections present in the body; TOC entry per-section count matches.
11. **Function ref-counts**: no orphaned functions (every function defined in the script is called from at least one other site).

## What was NOT verified

These need real ANL access; documented in `docs/TESTING.md`'s on-node
section for ad-hoc verification when convenient:

- On-node `client` same-host short-circuit (`docs/TESTING.md` test 1).
- On-node `tunnel` no-OpenCode-touch (test 2).
- Standalone `server` resolution + single-prompt + `-y` bypass + env-supplied bypass (test 3).
- On-node `mode_stop` confirmation prompt + `-y` bypass + post-kill messaging (test 4).
- Multi-user collision UX `[n/p/r/a]` (test 5; requires two users on same physical host).
- SSH attempt tracker firing at threshold (test 6; awkward to verify in normal use).

## Enhancement landed in same commit window

User requested while audit was in flight: extend the node picker so the
user can type a hostname directly (equivalent to `--node <host>` but
interactive). Implemented in `pick_node`:

- Picker prompt now reads "Pick a node [1-N, hostname, or Enter for default]:" with a hint line "(or type a hostname not in this list to use it directly)".
- Numeric input behavior unchanged.
- Hostname input (matching `^[a-zA-Z0-9][a-zA-Z0-9._-]*$`) follows the same path as the `--node` flag: warn if not in `ANL_NODES`, verify reachability via `ssh_reachable`, use it.
- Invalid input (number out of range, garbage string) re-prompts with a clear hint.

Behavior parity with `--node` flag: a user can now interactively select
a hostname not in the static list without having to abort and re-invoke
with `--node <host>`.

## State of the script post-audit

- `main` HEAD: pushed; all audit commits + enhancement on origin.
- 25/25 sections present, TOC accurate.
- No dead functions, no orphan globals.
- All Bxx bug references replaced with descriptive prose.
- 5/5 cheap smoke tests pass.
- 11/11 cheap behavior tests pass.
- 6 on-node tests documented but unrun (live verification deferred to
  the next time someone is on a compute node with intent to test).

## What's queued after the audit

- **Phase 3 (multi-client)**: setup-claudecode subcommand + invocation-name
  dispatcher in `main()` + first symlink (`argo_claudecode.sh -> argo_opencode.sh`).
- **Phase 4**: setup-aider, setup-cursor (instructions only), setup-generic
  (env-var snippets), argo_anywhere.sh symlink (interactive picker).
- **Phase 1 (deferred)**: rename repo + script + env-var prefix to drop
  the OpenCode-specific naming once multi-client surface is settled.

## How to use this document

If you (future maintainer or future-me) are about to do a similar
"refactor burst then audit" cycle, the structure here is reusable:

1. Identify the audit dimensions worth checking (we used: code
   correctness, docs sync, behavior verification; we explicitly
   declined style audit, perf audit, full unit-test setup).
2. Pass through each dimension separately so findings don't bleed into
   each other.
3. Surface findings as a structured table (severity / location /
   finding / fix) rather than narrative — easier to authorize.
4. Bundle related fixes into a single commit when they're tightly
   coupled (e.g. F1 + F5 here); split when they aren't (Phase 1, 2, 3
   each got their own commit).
5. Capture what was NOT verified so future maintainers know where the
   coverage gaps are.

The audit-findings discussion in chat is the primary record; this file
is the abbreviated commit-able summary for `git log`-driven discovery.

---

## Final audit (after this doc was first written; pre-Phase-3 hardening)

A second deeper audit pass surfaced 5 more findings (G1-G5). User
authorized fixing G2-G5 + detect-and-warn for G1's architectural
limitation.

| # | Severity | Site | Type | Resolution |
|---|---|---|---|---|
| G1 | high (architectural) | multi-tunnel destruction (different ports same node, or same port different nodes) | unsupported scenario | detect-and-warn added in `mode_server` (multi-port collision) and `ensure_or_reuse_tunnel` (cached-node-mismatch); architectural limitation documented in AGENTS.md |
| G2 | high | `pick_node` typed-hostname loop + `--probe-nodes` loop could loop forever after SSH attempt tracker locked | bug | both check `_SSH_LOCKED=1` and `die` cleanly |
| G3 | medium | `mode_server` tee-re-exec used `export` for ARGO_OPENCODE_USER/PORT; leaked into parent shell when called in-process | drift from invariant | switched to per-command env (`VAR=val bash $0 server`); no shell-level export |
| G4 | medium | `mode_clean` remote step lacked on-node short-circuit | inefficiency | `host_is_target "$cached_node"` check; runs script locally if so |
| G5 | medium | `status` next-step suggested `update-models` even when no OpenCode config existed | misleading hint | branch on config existence; suggest `client` if no config |

What was NOT addressed:
- The underlying multi-tunnel architectural constraint (G1) remains.
  argo-shim's deterministic-port naming approach is the canonical
  upstream solution; we accepted single-instance-per-user as our
  trade-off.

Final state: all known bugs fixed or documented; ready for Phase 3
(multi-client) without baggage.

---

## Audit round 3 (post-G1-G5; user wanted one more pass before Phase 3)

User asked for another audit round before moving to multi-client work,
on the principle that each previous audit found things the previous
one didn't. This round used four passes: critical re-read of G1-G5
fixes, subcommand × flag matrix, shellcheck, behavioral verification
of documented behaviors.

3 findings (H1-H3), all fixed.

| # | Severity | Site | Finding | Resolution |
|---|---|---|---|---|
| H1 | medium | `--port-range` parser | accepted `65000-64900`, `0-100`, `70000-80000` silently | validate LO<HI and both ends in 1024-65535 |
| H2 | medium | `~/.config/opencode/config.json` hardcoded at 8 sites | drift-prone | new `OPENCODE_CONFIG` constant; refactored sites |
| H3 | low | shellcheck SC2295 (`${var#${pat}}` should inner-quote) | future-proofing | added inner quotes at 2 sites |

What round 3 explicitly verified as correct (no fix needed):
- G1 server-side detection (`pgrep + lsof + awk` cross-platform)
- G3 env-prefix scoping on a pipeline (verified empirically)
- G4 `eval` usage (no injection risk; values are hardcoded constants)
- G5 existence-check branch (correct logic, simple condition)
- All 3 ssh_reachable callers (lock-state handling; covered by G2)
- All exit codes (status 0/1, args 0/1/2)
- All trap handlers (proper scope)
- Legacy env var promotion + deprecation warnings
- ARGO_BOX_STYLE override
- mode_status exit code semantics

shellcheck output: 4 info-level findings before round 3, 2 after. The
remaining 2 are SC2029 ("expands on the client side" in SSH heredocs)
which is the intentional design.

Trend across audits: round 1 found 7, round 2 found 5, round 3 found 3,
all decreasing in severity. Each round's findings were of a different
character (round 1: structural/refactor drift; round 2: regressions
from refactor; round 3: pre-existing edges + cosmetic). No single audit
catches everything; cumulatively they catch most.

Final state: ready for Phase 3 (multi-client) without baggage.

---

## Audit round 4 (post-audit-3; user wanted yet another pass)

User's instinct was right: each audit found new things. Round 4 used
four passes — areas not yet probed (handle_config_file, fetch/gather/
render summaries, mode_update_models internals); race conditions and
signal handling; integer/string boundaries; portability + external-tool
dependencies.

3 findings (J1-J3), all fixed.

| # | Severity | Site | Finding | Resolution |
|---|---|---|---|---|
| J1 | medium | resolve_port | accepted privileged ports 1-1023; inconsistent with --port-range and the interactive prompt | added explicit < 1024 check |
| J2 | medium | G1 multi-port collision check | pgrep upfront gate failed silently on minimal Linux without procps | removed gate; lsof|awk filter handles the no-match case correctly on its own |
| J3 | low | handle_config_file backup name | 1-second resolution; concurrent invocations could clobber | append $$ (PID) for uniqueness |

What round 4 explicitly verified as correct:
- handle_config_file's [m]erge correctly preserves user customizations
- mode_update_models's orphan splice logic
- gather_summary / extract_* helpers
- cleanup_local signal handling (proper trap clearing, empty/live pid)
- Concurrent same-user invocations (no corruption risks)
- Cross-platform fallbacks for getent (host/dscacheutil) and ip (ifconfig)

Trend: 7 → 5 → 3 → 3. Round 4 found the same count as round 3 but the
findings were narrower (no architectural issues; one consistency, one
edge-case dependency, one rare race). Severity stayed at medium-or-below.

The convergence is genuine but not yet at zero. Worth one more pass.

---

## Audit round 5 (final)

User wanted one more pass focused on areas the previous four explicitly
hadn't probed: argo-proxy launch + crash recovery, box-rendering width
edges, input/prompt edges, file/path edges, clean subcommand sequencing.

5 findings (K1-K5), all fixed.

| # | Severity | Site | Finding | Resolution |
|---|---|---|---|---|
| K1 | medium | mode_server failure diagnostic | claimed log file existed for screen/tmux launchers but only nohup writes one | branch by $launcher; tell user how to attach to session for screen/tmux |
| K2 | medium | tmux launcher | quoting bug: $HOME with spaces breaks the shell-command arg | use printf %q to shell-escape the binary path |
| K3 | low | print_summary_box | overflow at maxc<=3 (terminals <=4 cols) | comment explaining the pathological case; no code change |
| K4 | low | mkdir -p $STATE_DIR (3 sites) | bare mkdir error on read-only $HOME | add `|| die` with helpful message |
| K5 | medium | mode_clean local-listener kill | mislabeled "Stopping local SSH tunnel" when killing argo-proxy on a node | branch label by local_tunnel_status |

What round 5 explicitly verified as correct:
- handle_config_file's [m]erge with jq * deep-merge semantics
- mode_update_models orphan splice (jq with_entries)
- ask() handles EOF/empty/whitespace/multibyte input
- Concurrent same-user writes to cache files (atomic, won't corrupt)
- HOME with spaces handled by all callers EXCEPT the tmux line (K2)
- screen launcher's exec model (separate args, not shell-command)
- nohup launcher's redirection
- print_summary_box rendering at narrow widths (40 cols works fine)
- print_summary_box rendering with very long single-line content (truncates)

Trend across all 5 audits:
- Round 1: 7 findings (structural drift)
- Round 2: 5 findings (regressions from refactor)
- Round 3: 3 findings (pre-existing edges + cosmetic)
- Round 4: 3 findings (consistency + dependency edge)
- Round 5: 5 findings (3 medium, 2 low; corner cases the previous rounds missed)

Round 5's count went UP because we deliberately probed areas the
previous 4 hadn't touched. Of the 5, K1 and K5 were real misleading-
text bugs (real users would have hit), K2 is a latent rare bug
(uncommon $HOME setups). Severity stayed medium-or-below. No
architectural issues.

Final final state: ready for Phase 3. The script has had 5 rounds of
audit; 23 findings total across all rounds; all fixed or documented.
We are at diminishing returns for further audits.
