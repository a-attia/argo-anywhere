# Implementation plan: PyYAML-in-venv self-heal + `[m]` menu accuracy

**Status**: DRAFT — not executed. Follow-up commit staged for user approval.
**Trigger**: 2026-07-15 field report from ANL compute node
`compute-386-02` (`<ANL-username>`) — see the interleaved log analyzed in
this session's chat log.
**Target release**: v3.1.1 patch (or roll into v3.1.0's still-untagged
tree).
**Files touched (engine only; D-028 requires the same edits in the
repo-root `argo-anywhere.sh` AND the vendored
`src/argo_anywhere/engine/argo-anywhere.sh`)**:

- `src/argo_anywhere/engine/argo-anywhere.sh`
- `argo-anywhere.sh` (repo-root historical copy; keep byte-identical)
- `tests/test_engine_config.py` (new smoke assertions for both fixes)
- `docs/LIMITATIONS.md` (short "Upstream stack" note if the argo-proxy
  transitive-dep story is confirmed changed)
- `AGENTS.md` + `PLAN.md` status lines (post-3.1.1 note)
- `CHANGELOG.md` if present

---

## 1. Field report summary

Interleaved log (a vim/screen scrollback capture) from
`mode_server` shows two consecutive `bash argo-anywhere.sh server`
invocations against a compute node with:

- `argo-proxy 3.2.2` already installed in `~/argovenv`
- **PyYAML importable from neither `python3` NOR
  `~/argovenv/bin/python`** — the recovery block fires for both the
  venv path and the system fallback
- `write_argoproxy_config` dies with `Refusing to write argo-proxy
  config without PyYAML for safe merge`
- Before dying, `handle_config_file` still prints `[m] merge` as a
  menu option, accepts `m` from the user, then rejects it with `[warn]
  YAML merge not supported here` — up to four prompt cycles visible in
  the log
- User eventually types `[k]` → the existing config is kept and
  `argo-proxy` starts on `:64742`

The user is unblocked (chose `[k]`), but two defects surfaced:

1. **Load-bearing dependency (PyYAML) is not self-healing** despite
   `ensure_argoproxy_installed` already running immediately before the
   YAML writer and already `pip install`-ing into the same venv. One
   `pip install pyyaml` line would have prevented the whole cascade.
2. **`[m] merge` is offered when it cannot work.** The prompt at
   `handle_config_file:2467` unconditionally lists `[m]`, then the
   `m|M` case at `handle_config_file:2491-2504` rejects it for YAML
   with a `[warn]` and re-prompts. That's a menu the code knows to be
   invalid at prompt-render time.

Both are fixable; each is small and mostly independent.

---

## 2. Root-cause reading of the engine

### 2.1 Why `write_argoproxy_config` couldn't find PyYAML

- `write_argoproxy_config` at
  `src/argo_anywhere/engine/argo-anywhere.sh:6415-6421` picks
  `${venv_dir}/bin/python` if it exists, else `python3`. Both paths
  are exercised in the log's error output.
- `mode_server` calls `ensure_argoproxy_installed` at line 6802
  BEFORE it calls `handle_config_file … write_argoproxy_config` at
  line 6823. So by the time the writer runs, the venv exists AND
  `argo-proxy` is guaranteed installed into it.
- Historical comment at line 6371 asserts: "PyYAML, which argo-proxy
  depends on, so it's always present in the venv." **The field log
  falsifies that assumption on this node.** Two plausible
  explanations, both worth confirming but neither changes the fix:
    - `argo-proxy 3.2.2` (or the specific `llm-rosetta` release that
      ships with it) may no longer transitively require PyYAML. The
      2026-07-08 upstream audit's WATCH-17 flagged the 0.7.x
      pipeline migration; a dep pruning is plausible.
    - Someone (site admin, previous run of `--force-reinstall`, or an
      unrelated `pip uninstall`) may have removed PyYAML from
      `~/argovenv` after argo-proxy install. Argo-proxy still runs
      because most of its runtime doesn't need PyYAML.
- Either way, the fix is symmetrical: **the engine, not upstream,
  owns the guarantee** that PyYAML is available in the venv it
  writes YAML through. This flips the "argo-proxy pulls it for
  free" assumption into an explicit, tested contract.

### 2.2 Why `[m]` shows up when it can't help

- `handle_config_file` at `src/argo_anywhere/engine/argo-anywhere.sh:2460-2508`
  prints the same 5-option menu regardless of file suffix or
  toolchain state.
- The `m|M` arm at line 2492 branches on filename + `jq` availability
  for JSON, and on filename alone for YAML. For YAML it always
  falls through to `warn "YAML merge not supported here. Pick [b] to
  overwrite or [k] to keep."`
- Result: the user is offered a choice that the same function will
  reject a fraction of a second later. Nothing about the menu tells
  them why. The `[warn]` is displayed BUT the prompt then re-prints
  the same 5-option menu; the user rationally tries `[m]` again on
  the next cycle (visible in the log).
- The menu should be **generated**, not hardcoded, from the
  currently-available merge capabilities:
    - JSON + `jq` → `[m]` in
    - JSON + no `jq` → `[m]` out (Merge helper text mentions "requires
      jq" today but the option is still offered)
    - YAML + PyYAML present → `[m]` COULD be in (see §5.1 Rejected
      alternatives — we do not need YAML merge in `handle_config_file`
      because `write_argoproxy_config` already merges YAML before the
      diff; `[m]` for YAML has no work to do)
    - YAML + PyYAML absent → same as above; `[m]` out
- Concretely: today the `[m]` letter for YAML is dead code. Removing
  it from the YAML menu is not a feature regression, it's a
  hallucinated affordance that we stop offering.

### 2.3 Non-issues surfaced but not fixable here

- **The interleaved log ordering** (`Recovery:` appearing before its
  own preamble; `-- VISUAL LINE --` band) is a vim/screen scrollback
  artifact; not an engine defect. No action.
- **Two consecutive `bootstrap on compute-386-02` lines** turned out
  to be the same scrollback splice, NOT the driver retrying the
  bootstrap after the first PyYAML failure. The `mode_server` process
  exited via `die` and the driver invoked it fresh a second time
  because the user re-ran the client. No retry-loop bug to fix.

---

## 3. Fix design

### 3.1 Fix A — Guarantee PyYAML in `~/argovenv`

**Where**: `ensure_argoproxy_installed()`
(`src/argo_anywhere/engine/argo-anywhere.sh:6572-6641`).

**What**: After the `argo-proxy` install/upgrade branch completes,
add an explicit PyYAML probe + install. Attach it to
`ensure_argoproxy_installed` (rather than `write_argoproxy_config`)
because:

- It's called on every `server` bootstrap AND every `update
  argoproxy` (D-022) — natural place to enforce the invariant.
- The venv is already known-good at that point (step 2 of the
  function passed).
- `write_argoproxy_config` is on the hot path and shouldn't do
  network I/O to `pip install`; the invariant belongs upstream of it.

**Sketch (bash 3.2 compatible, matches surrounding style)**:

```bash
  # 4) PyYAML in the venv (owned by us, not by argo-proxy).
  # ------------------------------------------------------------------
  # write_argoproxy_config uses PyYAML to preserve user-owned keys in
  # ~/.config/argoproxy/config.yaml (argo_embedding_url,
  # concurrent_downloads, etc.) when a config already exists. Historically
  # PyYAML rode in transitively via argo-proxy's own deps; that assumption
  # broke on a real ANL compute node in the 2026-07-15 field report
  # (argo-proxy 3.2.2 installed, PyYAML absent from the venv). Make the
  # dependency ours: probe and pip-install if missing. Small (~200 KB
  # universal wheel; no compile) and idempotent (pip is a no-op when the
  # dep is already satisfied).
  if ! "${venv}/bin/python" -c 'import yaml' >/dev/null 2>&1; then
    log "PyYAML missing from ${venv}; installing (needed for safe YAML config merge)..."
    "${venv}/bin/pip" install --quiet pyyaml \
      || warn "PyYAML install failed; write_argoproxy_config will fall back to the die-hard path if a merge is needed."
  fi
  ok "PyYAML in ${venv}: $("${venv}/bin/python" -c 'import yaml;print(yaml.__version__)' 2>/dev/null || echo "unavailable")"
```

**Notes**:

- `--quiet` matches the surrounding pip calls (`>/dev/null` on the
  pip upgrade line at 6621; `install --upgrade argo-proxy` at 6636
  is deliberately noisy so the user sees the argo-proxy version).
  Same style as line 6635 (`pip install --upgrade pip >/dev/null`).
- Failure path is a `warn`, not a `die`. If the compute node is
  offline (rare on `.cels.anl.gov` but possible), we still let the
  bootstrap continue; the existing `write_argoproxy_config` die-hard
  at line 6509 will fire IF the user has an existing config that
  needs merging. Users without an existing config are unaffected
  (Case 1 at 6398 doesn't touch Python).
- Deliberately does NOT install into the system python. The system
  python is a fallback the writer uses when the venv is missing,
  which is a "shouldn't happen after `ensure_argoproxy_installed`"
  case anyway. Keeping the concern in the venv also means we don't
  need `sudo` or `--user` decisions.
- One-line `ok` prints the resolved PyYAML version so the maintainer
  can spot upgrade-related regressions in future logs.

**Blast radius**: touches one function; adds ~10 lines of code +
comment; adds ~1s wall time to `mode_server` bootstraps that need
the install (single-digit-millisecond `import yaml` probe when it
doesn't). No behavior change on the happy path.

### 3.2 Fix B — Don't offer `[m]` when it can't merge

**Where**: `handle_config_file()`
(`src/argo_anywhere/engine/argo-anywhere.sh:2425-2511`).

**What**: Compute an `allow_merge` boolean from `(target suffix,
tool availability)` BEFORE printing the menu. Adjust the printed
menu, the accept-set in `ask`, and the `m|M` arm to be consistent
with each other.

**Sketch**:

```bash
  # Compute merge-capability once. YAML merge is deliberately excluded:
  # the YAML writers (currently only write_argoproxy_config) already merge
  # against the existing file before returning the proposed candidate to
  # handle_config_file, so [m] here would be a no-op on top of that. JSON
  # merge is via jq and only meaningful if jq is on PATH.
  local allow_merge=0 merge_hint=""
  if [[ "$target" == *.json ]] && command -v jq >/dev/null 2>&1; then
    allow_merge=1
    merge_hint="[m] merge: only update keys this script manages"
  fi

  warn "${desc} already exists at ${target} and differs from the proposed version."
  while :; do
    if [ "$allow_merge" -eq 1 ]; then
      cat >&2 <<EOF

  Choose how to handle ${target}:
    [k] keep existing (no changes)
    [b] backup existing to .bak.<timestamp>, then overwrite
    [d] show diff (existing -> proposed), then ask again
    ${merge_hint}
    [a] abort
EOF
      local choice; choice="$(ask "Your choice [k/b/d/m/a]:" "k")"
    else
      cat >&2 <<EOF

  Choose how to handle ${target}:
    [k] keep existing (no changes)
    [b] backup existing to .bak.<timestamp>, then overwrite
    [d] show diff (existing -> proposed), then ask again
    [a] abort
EOF
      local choice; choice="$(ask "Your choice [k/b/d/a]:" "k")"
    fi
    case "$choice" in
      k|K) ok "Keeping existing ${desc}."; break ;;
      b|B) …unchanged… ;;
      d|D) …unchanged… ;;
      m|M)
        if [ "$allow_merge" -eq 1 ]; then
          # existing JSON+jq merge body, unchanged
          local merged; merged="$(mktemp -t argo_anywhere.XXXXXX)"
          jq -s '.[0] * .[1]' "$target" "$proposed" > "$merged"
          cp "$merged" "$target"; rm -f "$merged"
          ok "Merged proposed keys into existing ${desc}."
          break
        else
          # Muscle-memory user typed `m` even though the menu didn't
          # advertise it. Explain why and re-prompt.
          if [[ "$target" == *.json ]]; then
            warn "Merge for JSON needs jq (not on PATH). Install jq or pick [k]/[b]/[d]."
          elif [[ "$target" == *.yaml ]] || [[ "$target" == *.yml ]]; then
            warn "Merge is not offered for YAML here (the writer already merges before this prompt). Pick [k]/[b]/[d]."
          else
            warn "Merge is not offered for this file type. Pick [k]/[b]/[d]."
          fi
        fi
        ;;
      a|A) rm -f "$proposed"; trap - RETURN; die "Aborted at ${desc} step." ;;
      *)   warn "Unrecognized choice: ${choice}" ;;
    esac
  done
```

**Notes**:

- The printed prompt string `Your choice [k/b/d/m/a]:` becomes
  `Your choice [k/b/d/a]:` when `[m]` is not offered. `ask "…" "k"`
  keeps `[k]` as the default so pressing Enter still works.
- The `m|M` arm is preserved as a fallback that gently teaches
  users why the option is unavailable (log shows the user typed
  `m` from muscle memory). Nicer than "Unrecognized choice: m".
- YAML explanation reads "the writer already merges before this
  prompt" — that's the accurate story. `write_argoproxy_config`
  builds the proposed file by merging into the existing one; if the
  proposed still differs from the existing after that merge, the
  delta is the 4 keys we own (`config_version`, `user`, `host`,
  `port`) plus the `verbose` overwrite plus the
  `argo_base_url` setdefault. `[m]` would either be a no-op or would
  fight the writer's decisions.
- Bash 3.2 lint: `[[ … && … ]]` is fine (bash 3.2 has `[[`; forbidden
  bash-4 features are `mapfile`/`declare -A`/`${var,,}` per AGENTS.md).
  Retained current style.
- **Coupled change**: the "requires jq for JSON" trailing hint text
  on the current line 2467 disappears (the option itself now
  disappears when jq is absent). One place to update.

**Blast radius**: touches one function; changes ~30 lines. No new
runtime dependencies. Risk: a downstream caller who relied on `[m]`
always being present sees it disappear for YAML — but there is no
such downstream caller (the option was silently rejected today). No
migration story needed.

### 3.3 Fix B addendum — same treatment for JSON without jq

Same audit-my-menu discipline: if `jq` is absent AND the file is
JSON, `[m]` is dead code just as it is for YAML. The current
`m|M` arm at line 2502 warns "Merge requires jq for JSON files"
but the option is still printed. The `allow_merge` computation
above already handles this correctly (`allow_merge=1` requires
both JSON suffix AND `jq` present).

This is a bug fixed "for free" by the same edit. Worth calling out
in the commit message.

---

## 4. Testing

### 4.1 Existing smoke tests (already green)

```sh
bash -n src/argo_anywhere/engine/argo-anywhere.sh
argo-anywhere -h
argo-anywhere status
argo-anywhere clean --dry-run -y --local-only
```

Run after each fix. No regressions expected.

### 4.2 New unit tests (Python layer; no ANL infra)

Add `tests/test_engine_config.py` with three cases exercising the
engine via `bash -c` invocations against synthesized fixture files:

- **`test_handle_config_file_yaml_menu_omits_m`**: point
  `handle_config_file` at an existing YAML fixture that differs from
  the writer's output; send `k\n` on stdin; assert the captured
  stderr contains `[k/b/d/a]` and NOT `[k/b/d/m/a]`.
- **`test_handle_config_file_json_no_jq_menu_omits_m`**: same idea
  for JSON with `jq` masked out of `PATH` (via a scratch `PATH=…`
  that excludes it). Assert `[k/b/d/a]`.
- **`test_handle_config_file_json_with_jq_menu_includes_m`**:
  regression guard for the happy path — with `jq` on PATH and a
  `.json` target, assert `[k/b/d/m/a]` and that piping `m\n` produces
  the merged file (not an error).

Fix A is harder to unit-test without a live venv; the smoke-test
approach is to add a docstring block in `tests/test_smoke.py`
documenting the manual verification recipe, then rely on the live-test
plan for real coverage.

### 4.3 Live verification (docs/TESTING.md pattern)

Add a short "PyYAML self-heal" section to `docs/TESTING.md`:

1. SSH to a fresh compute node (no prior `~/argovenv`).
2. From the laptop, run `argo-anywhere --cli-tool opencode client --node <fresh-node>`.
3. On the node, verify `~/argovenv/bin/python -c 'import yaml;
   print(yaml.__version__)'` succeeds AND that the `ok PyYAML in …:
   <version>` line appears in `~/.argo-anywhere.server.log`.
4. Modify `~/.config/argoproxy/config.yaml` to add a bogus key like
   `argo_test_key: preserved`. Re-run `client`. Verify the key
   survives.
5. `~/argovenv/bin/pip uninstall -y pyyaml`. Re-run `client`. Verify
   the `log "PyYAML missing … installing"` line fires and PyYAML
   reappears.

### 4.4 Field-report closure

Verify against the specific `<ANL-username> / compute-386-02` scenario
if the user can reproduce it: after the patch, the second `server`
invocation should produce `ok PyYAML in …` on the first `ok
argo-proxy: argo-proxy 3.2.2` block and NOT emit the `err We need
PyYAML …` cascade.

---

## 5. Alternatives considered + rejected

### 5.1 "Add YAML merge support to `[m]` instead of removing it"

Tempting because YAML merge via PyYAML is not hard. Rejected because:

- `write_argoproxy_config` ALREADY merges into the existing file
  before returning to `handle_config_file`. A second merge would
  either be a no-op or would fight the writer's ownership decisions
  (which keys we own vs. preserve).
- The `[k/b/d/m/a]` prompt's contract is "how to reconcile the
  proposed file with the existing file"; when the writer's proposal
  is already a merge, `[m]` is semantically empty.
- Adds ~40 lines of Python heredoc for a UI option nobody needs.

### 5.2 "Auto-pick `[b]` when `[m]` is unavailable and we detect the user typed `m`"

Rejected as user-hostile: `[b]` overwrites (with backup); the user
who typed `m` was signaling "don't overwrite my keys" — auto-`[b]`
does exactly the opposite of what they asked.

### 5.3 "Install PyYAML into the system python too"

Rejected: needs `sudo` or `--user` decision-tree. The system python
is only used as a fallback when the venv is missing, which the
preceding `ensure_argoproxy_installed` prevents. Keep the concern
inside the venv we own.

### 5.4 "Pin PyYAML as an explicit `pip install` dep of argo-proxy upstream"

Not our patch to write. Would also not help retroactively for
existing installs on compute nodes. Include as a nice-to-have entry
in the next `argo-proxy` upstream audit (add to `docs/AUDIT_2026-07-08_argo-proxy-upstream.md`
watch-list) but do NOT block on it.

---

## 6. Commit + release

Two commits (or one, since they touch adjacent functions and share a
single field-report cause):

**Preferred**: one commit, `fix(engine)` type per repo convention.
Subject line ≤ 72 chars, e.g.

> `fix(engine): guarantee PyYAML in venv + drop dead [m] menu option`

Body: field report summary; Fix A + Fix B design; live-test recipe
addition; note the `Co-Authored-By: Claude` trailer per `.gitmessage`.

**Engine version tag**: bump `SCRIPT_VERSION` in the engine from
`2.2.1-dev` (current) to `2.2.2-dev` OR leave it alone (the internal
tag is not user-visible per D-029). Decision: **leave it alone** for a
single bugfix; bump when the next feature lands.

**Package version**: no bump — this rolls into the still-untagged
v3.1.0 tree along with the extras consolidation from the prior
commit `5565048`.

**Docs**:

- `AGENTS.md` status line: add "post-v3.1.0 on `main`: PyYAML in
  venv is now a hard invariant (fix A); `[m]` menu option is
  suppressed when unusable (fix B)."
- `PLAN.md` status line: same one-line summary.
- `docs/LIMITATIONS.md` "Upstream stack" section: note that
  argo-proxy is no longer relied upon for PyYAML transitively (if
  the field investigation confirms this).
- `docs/TESTING.md`: add the "PyYAML self-heal" section from §4.3.

---

## 7. Open questions for the user before executing

1. **Which release channel**: fold into the still-unpushed v3.1.0
   (my recommendation, since v3.1.0 is not tagged yet), or hold for a
   v3.1.1 patch tag AFTER v3.1.0 ships? The user has expressed a
   preference for landing on `main` without version bumps during the
   extras consolidation — I'd apply the same here unless they say
   otherwise.
2. **Fix B menu wording**: should the muscle-memory `warn` for YAML
   mention `write_argoproxy_config`'s pre-merge behavior explicitly
   ("the writer already merges before this prompt") or use a more
   generic message ("YAML files use a different merge path")? The
   specific wording exposes an implementation detail; the generic one
   is less honest. Default draft uses the specific one.
3. **Fix A idempotency logging**: currently the draft prints `ok
   PyYAML in <venv>: <version>` on every bootstrap. Alternative:
   only log it when PyYAML was JUST installed by this run. The
   always-log form gives us a single-grep field for `PyYAML` in
   support-request logs; the conditional form is quieter. Default
   draft uses always-log.
4. **New tests**: add now (three unit tests + docs/TESTING.md
   section), or defer the test suite growth to a follow-up? The three
   tests are small and self-contained.
