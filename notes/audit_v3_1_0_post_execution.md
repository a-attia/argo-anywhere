# Post-execution audit — v3.1.0 D-032 + PyYAML sequence

**Status**: DRAFT — audit in progress. Each pass surfaces findings inline;
the "Findings" table at the end consolidates them for the fix commit(s).
**Scope**: the 9 commits from `5565048` (extras consolidation) through
`643de22` (D-032 web C6), landed 2026-07-15.
**Baseline for comparison**: `704e11e` (v3.1.1 point release; the last commit
before this sequence).
**Trigger**: user direction after the execution sprint —
"multipass audit on the update for final refinements, testing, and make sure
all needed new tests are added and no regression is introduced."

## What we're auditing

- **Regressions** — anything a today-supported invocation would notice.
- **Test coverage gaps** — behavior paths without tests.
- **Doc drift** — plans/AGENTS/README claims that no longer match code.
- **Refactor opportunities** — patterns that landed under time pressure and
  could be tightened without changing behavior.
- **Security posture** — new attack surface introduced by C4-C6.
- **CSPO-safety** — anything that could accidentally trigger the SSH failure
  tracker or Duo prompts.

Structure mirrors the pre-execution audit in
`notes/impl_ssh_config_native.md §7`: numbered passes; each finding tagged
`RESOLVED`, `NEEDS FIX`, `NEEDS TEST`, or `NO CHANGE`.

---

## Pass 1: regression hunt (existing behavior must be identical)

The most load-bearing question: **does the every-today-user path behave
identically after the sequence?**

Baseline invariants to check:
1. `argo-anywhere client` with `--user X --node compute-01.cels.anl.gov`
   (explicit-everything path; the most-common CLI invocation).
2. `argo-anywhere status` with no changes to env or cache.
3. `argo-anywhere web` and `argo-anywhere app` boot.
4. Every existing pytest passes.
5. The engine's smoke tests (`bash -n`, `-h`, `help`, `status`,
   `clean --dry-run`) all clean.

*(Filled in during audit execution below.)*

---

## Pass 2: test coverage gaps

For each C1-C6 code change, is there a test that would fail if the change
regressed?

Coverage matrix to build:
- Every new `--jump-host` code path.
- Every new `resolve_username` source branch.
- Every new `ssh_jump_args` decision branch.
- `_alias_proxy_notice_dedup` across all callers.
- The mirror-test enforcement (already there; verify comprehensive).
- `/api/ssh-hosts` cache lifecycle.
- `/api/preview-launch` state machine (5 states).
- The launcher popover: reading + rendering + validation of the 4 new fields.

---

## Pass 3: doc drift

Every claim in the human-facing docs must still be true after execution.
Sources to check:
- `README.md` — install section, D-032 subsection, Common ops.
- `docs/UPGRADING.md` — post-3.1.0 bullet + feedback-channel note.
- `docs/LIMITATIONS.md` — mux-socket duplication note + custom-jump-host
  note.
- `AGENTS.md` — Jump-host resolution subsection + Engine ↔ web-UI coupling
  rules subsection + env-var list + status line.
- `PLAN.md` — D-032 record + status line.
- `notes/impl_ssh_config_native.md` — plan text vs. what shipped.
- `notes/test_plan_v3_1_0.md` — commit-shas placeholders (were `<C3-sha>`
  etc. at draft time; must now cite real SHAs).
- Engine help text (`usage()` + `long_help()`).

---

## Pass 4: security & CSPO safety

- `/api/ssh-hosts` never calls `ssh` (grep-verified in a test; re-verify
  the grep is tight enough to catch a future indirect call).
- `/api/preview-launch` uses subprocess-list form + timeout ≤ 2s (unit
  test asserts this; re-verify).
- The engine's SSH failure tracker (`ssh_attempt_pre/ok/fail`) is untouched
  by ssh-config work (no `ssh -G` should ever go through it).
- `--jump-host` accepting arbitrary hosts is not a boundary crossing (already
  documented in the pre-execution §7 C4; re-verify no accidental use in
  a `curl` URL or similar).
- Log injection via `~/.ssh/config` `ProxyCommand` values that echo ANSI
  escape sequences (pre-execution §7 C2 called this out; we discussed a
  `sanitize_for_log` helper — did it land?).

---

## Pass 5: refactor opportunities surfaced during execution

Things that landed working but could be cleaner:
- The `_alias_has_own_proxy` awk-idiom bug I introduced in C1 and fixed in
  C2. Now correct but the comment scar remains — worth polishing?
- `resolve_username`'s API change (echo → globals) required updating 4
  callers. The 4th (`update_argoproxy_component`) wasn't in the plan's
  original enumeration; I found it by grep during execution. Any other
  callers I missed?
- `_SAFE_HOSTLIKE` regex introduced late. Did I pick the right bounds?
  RFC 1035 says 253 chars total; sub-label limit is 63. My regex enforces
  253 total but not the sub-label. Worth tightening?
- The engine's `resolve_username` refactor split cache-write from
  resolution — but did I remember to test the `mode_server` code path (the
  in-process short-circuit)?
- CSS classes `.summary-warn` + `.div-warn` are new; do they collide with
  any existing selector or theme break?

---

## Pass 6: build + install sanity

- `python -m build` produces a clean wheel.
- The wheel's metadata reflects the extras-consolidation commit (no
  vestigial `[web]`/`[app]`/`[all]`/`[test]`/`[screenshots]` references).
- The wheel bundles the new `preview.py` + `ssh_hosts.py` in the web
  package.
- `pipx install --force .` from the working tree yields a working CLI
  with all the new endpoints reachable.

---

## Pass 7: byte-identical mirror check

Every engine change must have landed in both:
- `src/argo_anywhere/engine/argo-anywhere.sh` (vendored)
- `argo-anywhere.sh` (repo-root historical mirror)

Per D-028. Verified by `diff -q` on each engine-touching commit.

---

## Pass 1 result — regression hunt

- **R1.** `bash -n` clean on both engine copies. ✅
- **R2.** `argo-anywhere -h`, `help`, `clean --dry-run -y --local-only` all
  rc=0. ✅
- **R3.** Explicit-fqdn `ssh_jump_args attia compute-01.cels.anl.gov` (no
  ssh_config alias) still emits `-J attia@logins.cels.anl.gov`. Identical
  to pre-D-032. ✅
- **R4.** `--no-jump` still returns empty. ✅
- **R5.** `ARGO_ANYWHERE_USER=x resolve_username` → `_USERNAME_RESULT=x
  _USERNAME_SOURCE=env _USERNAME_SHOULD_CACHE=0`. Env-set never touches
  cache. ✅
- **R6.** Full pytest: 402 passing (baseline was 290 pre-sequence; delta
  +112 all new tests). ✅
- **R7.** Live `argo-anywhere status` against the running tunnel still
  renders ALL GREEN + `Jump host: logins.cels.anl.gov` + `Cached
  username: aattia`. ✅

**Verdict: NO REGRESSIONS DETECTED across the today-supported paths.**

## Pass 2 result — test coverage gaps

- **Gap-1 (NEEDS TEST): `resolve_username` on-node guard**. The
  `on_anl_compute_node` check that skips ssh-config lookup on the compute
  node is not tested. A future refactor could silently remove the guard
  and the mode_server code path would start doing `ssh -G` self-lookups
  (returning `id -un`, then caching it — quietly wrong). Add:
  `test_B_ssh_config_skipped_on_compute_node` that monkeypatches
  `on_anl_compute_node` to return "yes" and asserts the ssh-config
  branch is NOT entered.

- **Gap-2 (NEEDS TEST): SCP branch's `_alias_has_own_proxy` check**. Sub-fix
  C's second call site (engine :4639 SCP options) is untested. A future
  refactor could remove the check and re-introduce the "duplicate hop"
  bug for alias-based bootstraps. Add:
  `test_C_scp_branch_skips_proxyjump_when_alias_has_own_proxy` that
  greps the engine source AND that runs `_source_engine_and_run` with
  a scripted call to whatever helper `remote_bootstrap` uses to build
  `scp_opts` (currently inline; may need to be extracted to a helper
  for testability — see Refactor-1 below).

- **Gap-3 (NEEDS TEST): `/api/launch-external` D-032 fields end-to-end**.
  The endpoint accepts `node`/`user`/`jump_host`/`no_jump` (C4 added
  them) but no test exercises them. Only `build_launch_argv` is tested.
  Add: `test_launch_external_passes_d032_flags_through` — assert
  spawned argv includes `--node polaris-login --user X --jump-host Y
  --no-jump`. Can use the existing `test_run_launch.py`
  `test_run_bad_cli_tool_rejected` pattern with a fake open-terminal
  hook.

- **Gap-4 (NEEDS TEST): `/ws` D-032 query params end-to-end**. Same class
  as Gap-3 but for the WebSocket intake. Would exercise
  `ws?verb=help&node=polaris-login&user=X&jump_host=Y&no_jump=1` and
  assert the launched argv contains the four flags.

- **Gap-5 (NEEDS TEST): renderPreview() client-side JS**. The preview
  panel's render logic (5 state branches) is client-only JS with no
  browser test. Testing this cleanly would need Playwright; deferred to
  a follow-up (would also unblock other UI-only regressions).

- **Covered items (no action needed)**: awk-idiom mirror test (byte-
  equivalent-mirror), dedup fires-once-per-alias, dedup across distinct
  aliases, cache-lifecycle for `/api/ssh-hosts` (miss + hit + refresh),
  timeout / non-zero-exit / bad-input on `run_ssh_G`, divergence
  detection, IP-block-safety invariant (subprocess-list + timeout ≤ 2s),
  loopback host guard on both new endpoints, garbage-body handling on
  `/api/preview-launch` (FastAPI returns 422 automatically).

## Pass 3 result — doc drift

- **Doc-drift-1 (NEEDS FIX): `notes/test_plan_v3_1_0.md` has 4 placeholder
  SHAs**: `<C3-sha>`, `<C4-sha>`, `<C5-sha>`, `<C6-sha>`. All landed
  (9d45344, 68e4a00, 0626659, 643de22 respectively). Also the file
  status is "OPEN" — should stay OPEN until the tester (Ahmed) runs it,
  but the commit list should be complete now.

- **Doc-drift-2 (KNOWN LIMITATION): plan `impl_ssh_config_native.md`
  claims `_SAFE_TOKEN` reuse**. Actual code introduced `_SAFE_HOSTLIKE`
  because `_SAFE_TOKEN` is stricter than the plan believed (lowercase-
  only, no `.`/`_`). Plan is a historical record; the correction is
  documented in `app.py`'s `_SAFE_HOSTLIKE` docstring. Add a "post-
  execution addendum" section to the plan noting the two divergences
  from what shipped rather than rewriting the plan body.

- **Doc-drift-3 (KNOWN LIMITATION): plan references `_reflect_our_jump_args`;
  actual is `reflect_jump_args`**. Same class as Doc-drift-2 — historical
  record. Handle in the addendum.

- **Doc-drift-4 (NO ACTION): README anchor `#using-your-own-sshconfig-
  route-d-032-v310`** — verified to resolve correctly against GitHub's
  anchor-generation rules. No fix needed.

- **Doc-drift-5 (NO ACTION): AGENTS.md D-032 status line + PLAN.md D-032
  record + coupling subsection** — all match shipped code accurately.

- **Doc-drift-6 (NO ACTION): engine help block (`usage()` + `long_help()`)**
  — `--jump-host` documented in both; `ARGO_ANYWHERE_JUMP_HOST=HOST` in
  env-vars section; short-help synopsis line includes `--jump-host HOST`.

## Pass 4 result — security & CSPO safety

- **S-1 (VERIFIED): `ssh_hosts.py` never calls `ssh`.** Grep-verified.
  Test `test_module_source_never_calls_ssh` enforces the invariant.
- **S-2 (VERIFIED): `preview.py` uses subprocess-list + timeout ≤ 2s.**
  Grep-verified. Test `test_api_preview_ssh_never_authenticates`
  enforces the invariant.
- **S-3 (VERIFIED): D-032 helpers don't touch `ssh_attempt_pre/ok/fail`.**
  Grep-verified — the three new helpers (`_ssh_config_hostname`,
  `_ssh_config_user`, `_alias_has_own_proxy`) all call raw `ssh -G`
  (non-authenticating); none go through the failure tracker.
- **S-4 (KNOWN LIMITATION): `sanitize_for_log` helper did NOT land**.
  Pre-execution §7 C2 called for a helper that strips ANSI escapes
  from ssh_config values before logging. Only two sites log ssh_config
  content: the alias-notice `log` lines in `pick_node` that echo
  `${_resolved}` (from `_ssh_config_hostname`, parsed from `ssh -G`
  stdout). A malicious `HostName ...\e[31mowned\e[0m` value in the
  user's OWN `~/.ssh/config` would color the log. Real-threat
  assessment: user-config self-harm; if attacker can write your
  `~/.ssh/config`, they can also `alias ls='rm -rf ~'` in your shell rc.
  **Verdict**: acknowledge as a documented follow-up; not urgent.
- **S-5 (VERIFIED): `--jump-host` is passed only as `-J` argument**.
  Reviewed every reference to `ANL_JUMP` post-mutation; all interpolate
  it into ssh/scp argv or into log/error messages. No URL construction,
  no shell substitution.
- **S-6 (VERIFIED): garbage POST body to `/api/preview-launch`**.
  Random-key dict → treated as all-empty → cached state. Non-dict body
  → 422 (FastAPI automatic validation). Empty body → 422. No crash.

## Pass 5 result — refactor opportunities

- **Refactor-1 (NICE TO HAVE): `remote_bootstrap`'s inline SCP options
  block**. The `scp_opts` array-building at engine :4615-4644 mixes MFA
  options, StrictHostKeyChecking, and the D-032 alias-check into one
  ~30-line block. Extracting to a `_build_scp_opts <user> <node>`
  helper would make Gap-2 (SCP branch alias check) unit-testable
  without invoking `remote_bootstrap`. Not urgent; can wait for a
  future refactor cycle.
- **Refactor-2 (NO CHANGE): awk-idiom comment in `_alias_has_own_proxy`**.
  The comment scar from my C1 mistake is honest maintainer-facing
  content. Keep as-is — it's exactly the kind of thing that saves a
  future refactor from re-breaking the invariant.
- **Refactor-3 (NO CHANGE): `_SAFE_HOSTLIKE` RFC 1035 bounds**. Total
  253 char enforced; sub-label 63 not enforced. Engine treats
  hostnames as opaque strings passed to ssh; ssh does DNS-layer
  validation itself. Sub-label enforcement is defense-in-depth we
  don't need.
- **Refactor-4 (NICE TO HAVE): `renderPreview()` client JS is monolithic**.
  ~50 lines rendering 5 state branches. Would benefit from splitting
  into `renderPreviewCached()`, `renderPreviewResolved()`, etc. for
  readability. Not urgent; the logic is straightforward.

## Pass 6 result — build + install sanity

- **B-1 (VERIFIED): `python -m build --wheel` clean**. Produces
  `argo_anywhere-3.1.1-py3-none-any.whl`.
- **B-2 (VERIFIED): wheel metadata reflects extras-consolidation**.
  Requires-Dist = fastapi, uvicorn[standard], pywebview.
  Provides-Extra = dev (only). No vestigial `[web]`/`[app]`/`[all]`/
  `[test]`/`[screenshots]`.
- **B-3 (VERIFIED): wheel bundles new files**. `preview.py` +
  `ssh_hosts.py` both present. Engine + assets + static all bundled.

## Pass 7 result — byte-identical mirror

- **M-1 (VERIFIED): mirror byte-identical.** `diff -q` on the two
  engine files returns empty.
- **M-2 (VERIFIED): all 4 engine-touching commits landed both copies**.
  Grep against each SHA's file list: `b80970c` `4b8c445` `86d2845`
  `9d45344` all touch both `src/argo_anywhere/engine/argo-anywhere.sh`
  and `argo-anywhere.sh` (D-028 mirror contract intact).

---

## Findings — fix-commit summary

Ordered from most-urgent to least:

| # | Class | Description | Fix |
|:--|:---|:---|:---|
| 1 | NEEDS FIX | Doc-drift-1: 4 placeholder SHAs in `notes/test_plan_v3_1_0.md` | Replace with real SHAs |
| 2 | NEEDS TEST | Gap-1: `resolve_username` on-node guard | Add `test_B_ssh_config_skipped_on_compute_node` |
| 3 | NEEDS TEST | Gap-2: SCP branch's `_alias_has_own_proxy` check | Add grep-invariant test (structural check; simpler than the runtime extraction Refactor-1 would enable) |
| 4 | NEEDS TEST | Gap-3: `/api/launch-external` D-032 fields | Add `test_launch_external_passes_d032_flags_through` |
| 5 | NEEDS TEST | Gap-4: `/ws` D-032 query params | Add `test_ws_passes_d032_query_params_through` |
| 6 | DOC | Doc-drift-2/3: plan's `_SAFE_TOKEN` and `_reflect_our_jump_args` references | Post-execution addendum in `impl_ssh_config_native.md` |
| 7 | KNOWN LIMITATION | S-4: `sanitize_for_log` not landed | Note as follow-up in `docs/LIMITATIONS.md` (or defer entirely — user-self-harm threat) |
| 8 | NICE TO HAVE | Refactor-1: extract `_build_scp_opts` helper | Defer to future refactor cycle |
| 9 | NICE TO HAVE | Refactor-4: split `renderPreview()` | Defer |

**Fix commits landed** (2026-07-15):
- **A1** — `99f1e46` — `docs(audit)`: this audit doc.
- **A2** — (next commit) — `fix(D-032): post-audit test coverage + doc
  drift`. Closes items 1-5 (real SHAs in test plan + 4 new tests) AND
  item 6 (post-execution addendum §11 in `impl_ssh_config_native.md`).
  409 pytest tests passing after A2 (was 402; +7 new tests, 0
  regressions).
- Items 7-9 remain as documented follow-ups (S-4 sanitize_for_log
  deferred; Refactor-1 SCP extraction deferred; Refactor-4 renderPreview
  split deferred).

---

*Created 2026-07-15 by Ahmed Attia (with substantial AI assistance from Claude
per `CONTRIBUTORS.md`). Continues the audit discipline from
`notes/impl_ssh_config_native.md §7` (pre-execution audit) — this doc is the
post-execution complement.*
