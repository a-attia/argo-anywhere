# Implementation plan: SSH-config-native node access (engine + web UI)

**Status**: READY TO EXECUTE — multi-pass audit complete
(2026-07-15; Passes 1-4 + 6-7, 45 items resolved with 8 plan
corrections + 10 additions incorporated below). All 11 open
questions decided interactively (2026-07-15; see §8). Awaiting
user's go-signal to start C1. Docs get a full review/polish pass
after Track E + Track W code lands (per Q14 direction).
**Trigger**: 2026-07-15 user request. Some ANL users reach compute
nodes via `ssh <alias>` where `~/.ssh/config` handles jump/username/
onsite-vs-offsite policy; today argo-anywhere assumes
`logins.cels.anl.gov` as the jump host and requires explicit
`--user` even when the alias sets one. A follow-on request in the same
session added the companion web-UI surface work so users driving argo
from the app get the same benefit.
**Target release**: fold into the still-untagged v3.1.0 tree on `main`
(no separate version bump). Ordered AFTER
[`impl_pyyaml_and_menu_fix.md`](impl_pyyaml_and_menu_fix.md) in the
queue.
**Scope decision** (per user's answers 2026-07-15):
- **Cover all three engine sub-mechanisms**: Host-alias acceptance +
  user-in-config inference + skip-our-ProxyJump-when-alias-provides-one.
- **Stay ANL-scoped**: Don't generalize past ANL. Keep MFA/Duo
  defaults, keep `ANL_JUMP`+`ANL_NODES` as defaults, keep argo-proxy's
  compute-node role.
- **Web UI gets the matching launcher surface** so the alias UX
  reaches users who never touch the CLI (node/user/jump-host fields;
  ssh_config alias picker; resolved-launch preview).
- **Land on `main` before v3.1.0 tag**, but only after a multi-pass
  audit (§7 below) surfaces and closes the sharp edges on BOTH tracks.

## Track structure

Work splits into two logical tracks that share the audit + phasing
discipline:

- **Track E (engine)**: bash-only; §2 sub-fixes A/B/C + §2.4 shared
  infrastructure + §2.5 docs. Load-bearing — Track W depends on it.
- **Track W (web UI)**: Python + HTML/JS; §10 launcher surface. Ships
  after Track E lands and Track E's live-test scenarios pass. Adds
  no new engine flags; consumes what Track E introduced.

Commit ordering (six commits across the two tracks, all on `main`
before the v3.1.0 tag):

| # | Track | Commit summary | Depends on |
|:--|:-----:|:---|:--:|
| C1 | E | helpers + `--jump-host` argv/env plumbing (no-op patch) | — |
| C2 | E | wire helpers into `ssh_jump_args` / `resolve_username` / `pick_node` + unit tests | C1 |
| C3 | E | docs (README, UPGRADING, LIMITATIONS, AGENTS, PLAN.md D-032, help block) | C2 |
| C4 | W | launcher node/user/jump-host fields + `build_launch_argv` extension + tests | C3 |
| C5 | W | `/api/ssh-hosts` alias picker + datalist + tests | C4 |
| C6 | W | `/api/preview-launch` resolved-launch preview + UI panel + docs (AGENTS coupling-rule bullet) | C5 |

Each commit is independently green (existing suites pass; smoke
tests pass; the engine round-trips verbatim). A mid-execution abort
between any two commits lands us at a still-shipping state.

---

## 1. What the user wants (concretely)

Today the engine assumes:

- **Route**: laptop → `logins.cels.anl.gov` (jump) → `compute-NN.cels.anl.gov`.
  Hardcoded via `ANL_JUMP="logins.cels.anl.gov"` at
  `src/argo_anywhere/engine/argo-anywhere.sh:334` and expanded into
  every SSH/SCP invocation via `ssh_jump_args`
  (`src/argo_anywhere/engine/argo-anywhere.sh:1778`) and the
  `ProxyJump=` on the SCP branch
  (`src/argo_anywhere/engine/argo-anywhere.sh:4383`).
- **Node identity**: `--node <fqdn>` or one of `ANL_NODES` (the picker
  list at `src/argo_anywhere/engine/argo-anywhere.sh:316-332`), all
  spelled as `compute-NN.cels.anl.gov`.
- **Username**: `ARGO_ANYWHERE_USER` / `--user` MUST be set (or cached)
  before we can build `${user}@${host}`. Line 6716:
  `: "${ANL_USERNAME:?could not resolve ARGO_ANYWHERE_USER …}"`.

Users with a mature `~/.ssh/config` do this instead:

```sshconfig
Host polaris-login              # or "cels-01", "swing", …
    HostName compute-386-02.cels.anl.gov
    User    <ANL-username>
    # On-site path (empty when off-site, replaced by ProxyJump below):
    ProxyCommand none
    # Off-site path (replaces the ProxyCommand above via `Match exec`):
    # Match exec "test $(nettest.sh) != anl"
    #     ProxyJump <ANL-username>@logins.cels.anl.gov
```

Then `ssh polaris-login` "just works" from any network. They rightly
expect `argo-anywhere --cli-tool opencode client --node polaris-login`
to work too. Today it doesn't:

- `polaris-login` isn't in `ANL_NODES` → `pick_node` warns
  ("not in the known list"; some code paths `die`).
- No `--user` → `mode_client` / `mode_server` die at the
  `${ANL_USERNAME:?...}` guard.
- Even if both are supplied, our `ssh_args` adds
  `-J <ANL-username>@logins.cels.anl.gov` on top of the alias's own
  ProxyJump — best case: works but wastes a hop; worst case:
  jumphost-loop error if the alias resolves to logins.cels.anl.gov
  itself.

The three fixes below make `ssh_config`-native aliases first-class
without breaking the today-supported explicit-fqdn path.

---

## 2. Design (three coupled sub-fixes + shared infrastructure)

### 2.1 Sub-fix A: accept ssh_config Host aliases in `--node` / `ANL_NODES`

**Audit correction (2026-07-15)**: this sub-fix is smaller than the
original draft claimed. Re-reading `pick_node`
(`src/argo_anywhere/engine/argo-anywhere.sh:4176-4198`):
- Line 4182 already **warns** (not dies) when `--node` is not in
  `ANL_NODES`: `warn "Requested node '${req}' is not in ANL_NODES
  (proceeding anyway)."`
- The `die` at line 4197 only fires when `ssh_reachable` FAILS.

What actually breaks today for a bare alias is **not** the picker
warning — it's `ssh_reachable` failing because our `ssh_args`
appends `-J logins.cels.anl.gov` on top of the alias's own
ProxyJump, either duplicating a hop or triggering a jump-loop
error. **Sub-fix C is what makes aliases reachable.** Sub-fix A's
job is now much narrower: **improve the warn wording so an alias
user doesn't think anything went wrong.**

**Current warn text** (line 4182):
```
Requested node 'polaris-login' is not in ANL_NODES (proceeding anyway).
```

**New warn text**: if `ssh -G <alias>` resolves to a rewritten
hostname (i.e. it IS an ssh_config alias), rewrite the message:
```
Note: 'polaris-login' is an ssh_config alias
  (resolves to compute-386-02.cels.anl.gov); proceeding via ~/.ssh/config.
```
If `ssh -G` doesn't rewrite (bare hostname or resolution fails),
keep today's warn verbatim (unknown but assumed valid).

**Helper** (in Section 8 alongside `_alias_has_own_proxy`):
```bash
# _ssh_config_hostname <alias> → resolved hostname, or empty on failure.
# `ssh -G` output is guaranteed lowercase-keyed on OpenSSH 5.6+
# (confirmed 2026-07-15 on OpenSSH 10.2p1).
_ssh_config_hostname() {
  local target="$1"
  [ -n "$target" ] || return
  ssh -G "$target" 2>/dev/null | awk '/^hostname / {print $2; exit}'
}
```

Detection idiom in `pick_node`'s warn branch:
```bash
if [ "$in_list" -eq 0 ]; then
  local resolved; resolved="$(_ssh_config_hostname "$req")"
  if [ -n "$resolved" ] && [ "$resolved" != "$req" ]; then
    log "Note: '${req}' is an ssh_config alias"
    log "  (resolves to ${resolved}); proceeding via ~/.ssh/config."
  else
    warn "Requested node '${req}' is not in ANL_NODES (proceeding anyway)."
  fi
fi
```

**Deliberately dropped from the original design**:
- ANL-suffix heuristic (was §2.1 "resolved fqdn matches known ANL
  suffix"). No value — the warn/log distinction is already the whole
  UX benefit, and the resolved fqdn doesn't need further
  classification.
- Extending `ssh_reachable` to consult `ssh -G`. Not needed —
  once Sub-fix C stops adding our conflicting `-J`, `ssh_reachable`
  succeeds naturally via the alias.

**Where to touch**: `pick_node`'s "not in ANL_NODES" branch
(`src/argo_anywhere/engine/argo-anywhere.sh:4179-4182`; ~5 lines
delta). New helper in Section 8.

### 2.2 Sub-fix B: infer username from `ssh_config` when `--user`/env absent

**Audit correction (2026-07-15)**: `resolve_username` (engine
:2195-2218) **auto-caches the prompted value** on line 2216:
```bash
printf '%s\n' "$u" > "$USER_CACHE"
```
This conflicts with reject E3 ("cache is write-only-from-explicit-
actions"). If we naively slot ssh-config inference between "cache
lookup" and "prompt," we'd never write the cache (short-circuit
before the prompt loop) — but then a later `--force-reinstall`
sequence that DOES need the cache would silently re-prompt for a
value the user thinks argo already knows. The refactor:

**Refactored `resolve_username`** — separate "get a value" from
"cache it":
```bash
# Returns: the resolved username on stdout.
# Sets globals for the caller: _USERNAME_SOURCE (flag|env|
# ssh-config|cache|prompt), _USERNAME_SHOULD_CACHE (0|1).
resolve_username() {
  _USERNAME_SOURCE=""
  _USERNAME_SHOULD_CACHE=0

  if [ -n "${ARGO_ANYWHERE_USER:-}" ]; then
    _USERNAME_SOURCE="env"     # or "flag" — main() distinguishes
    echo "$ARGO_ANYWHERE_USER"; return
  fi

  # NEW: ssh-config inference (before cache; per §7 A7).
  # Skipped on-node (self-alias resolution is noise).
  if [ "$(on_anl_compute_node)" = "no" ]; then
    local u
    if [ -n "${ARGO_ANYWHERE_NODE:-}" ]; then
      u="$(_ssh_config_user "$ARGO_ANYWHERE_NODE")"
      if [ -n "$u" ]; then
        _USERNAME_SOURCE="ssh-config:${ARGO_ANYWHERE_NODE}"
        echo "$u"; return
      fi
    fi
    u="$(_ssh_config_user "$ANL_JUMP")"
    if [ -n "$u" ]; then
      _USERNAME_SOURCE="ssh-config:${ANL_JUMP}"
      echo "$u"; return
    fi
  fi

  if [ -f "$USER_CACHE" ]; then
    _USERNAME_SOURCE="cache"
    cat "$USER_CACHE"; return
  fi

  # Prompt loop (unchanged).
  local u
  while :; do
    u="$(ask "Enter your ANL username (e.g. jdoe):")"
    [[ "$u" =~ ^[a-zA-Z][a-zA-Z0-9._-]*$ ]] && break
    err "Invalid username. Use letters, digits, dot, underscore, hyphen."
  done
  _USERNAME_SOURCE="prompt"
  _USERNAME_SHOULD_CACHE=1   # ONLY prompted values get cached.
  echo "$u"
}
```

Callers that previously assumed `resolve_username` cached
transparently now check `_USERNAME_SHOULD_CACHE` after the call and
handle the write themselves — one-line change per call-site:
```bash
u="$(resolve_username)"
[ "$_USERNAME_SHOULD_CACHE" = 1 ] && {
  _ensure_state_dir
  printf '%s\n' "$u" > "$USER_CACHE"
}
```

Or centralize in a `resolve_and_persist_username` wrapper — cleaner;
recommended.

**Helper** (in Section 8 alongside `_ssh_config_hostname`):
```bash
# _ssh_config_user <alias-or-host> → username, or empty on failure.
_ssh_config_user() {
  local target="$1"
  [ -n "$target" ] || return
  ssh -G "$target" 2>/dev/null | awk '/^user / {print $2; exit}'
}
```

**Log source explicitly** so users see the inference:
```
[ ok ] Using ANL username: <ANL-username> (source: ssh-config:polaris-login)
```
Matches the existing `log "Using port: … (source: …)"` pattern.

**Where to touch**: `resolve_username`
(`src/argo_anywhere/engine/argo-anywhere.sh:2195-2218`) — full
rewrite (~40 lines vs. today's 24). Every caller — grep for
`resolve_username`:
```
$ grep -n 'resolve_username' src/argo_anywhere/engine/argo-anywhere.sh
```
Update each to check `_USERNAME_SHOULD_CACHE`. **Verify test
coverage**: add unit test "ssh-config-inferred user is NOT written
to `$USER_CACHE`" (per §7 A7).

### 2.3 Sub-fix C: skip our ProxyJump when the alias supplies one

**Current behavior**: `ssh_jump_args` always emits
`-J <user>@<ANL_JUMP>` unless `--no-jump`/`ARGO_ANYWHERE_NO_JUMP=1`
is set OR the target IS `ANL_JUMP` itself.

**New behavior**: also skip our `-J` when the target alias's own
`ssh_config` already sets `ProxyJump` or `ProxyCommand` (other than
the sentinel `none`). Concretely:

```bash
# _alias_has_own_proxy <alias> → returns 0 if ssh_config sets a
# non-empty ProxyJump or ProxyCommand for this alias, else 1.
#
# `ssh -G` output is guaranteed lowercase-keyed on OpenSSH 5.6+
# (confirmed 2026-07-15 on OpenSSH 10.2p1).
_alias_has_own_proxy() {
  local target="$1"
  [ -n "$target" ] || return 1
  local raw
  raw="$(ssh -G "$target" 2>/dev/null)" || return 1
  # ProxyJump can be `none` (explicit "no jump") or a real host.
  # Idiom: awk `exit 0` on first match returns success to the shell;
  # END with no match returns failure via `exit 1`. Reads cleaner than
  # the found=1/END{exit found?0:1} form and is unambiguous under
  # `set -e` (per §7 A4 audit).
  if printf '%s\n' "$raw" | awk '/^proxyjump / && $2 != "none" {exit 0} END{exit 1}'; then
    return 0
  fi
  # ProxyCommand `none` is the "no proxy" sentinel; anything else counts.
  if printf '%s\n' "$raw" | awk '/^proxycommand / && $0 !~ /^proxycommand none$/ {exit 0} END{exit 1}'; then
    return 0
  fi
  return 1
}

# _alias_proxy_notice_dedup <alias>: emit the "routes via ssh_config"
# log line at most ONCE per alias per invocation. ssh_jump_args is
# called from every ssh_reachable / ssh_mux_open / ssh_attempt_pre-
# gated call in a `client` run (~10+ sites); without dedup the user
# sees the same notice a dozen times. Bash-3.2-compatible naming
# convention (no assoc arrays; use ${var//pat/replacement} which IS
# available in bash 3.2, per §7 D1).
_alias_proxy_notice_dedup() {
  local alias="$1" user="$2"
  local safe="${alias//[^a-zA-Z0-9]/_}"
  local seen_var="_ALIAS_PROXY_NOTICE_SEEN_${safe}"
  # Bash 3.2 indirect read via eval (safe: $safe is regex-scrubbed).
  eval "local seen=\${${seen_var}:-0}"
  if [ "$seen" = 1 ]; then return; fi
  eval "${seen_var}=1"
  log "Note: ${alias} already routes via ~/.ssh/config;"
  log "  not adding our -J ${user}@${ANL_JUMP}."
}
```

`ssh_jump_args` becomes:

```bash
ssh_jump_args() {
  local user="$1" target="${2:-}"
  if [ "${ARGO_ANYWHERE_NO_JUMP:-0}" = 1 ]; then
    return
  fi
  # Never chain to the jump host from the jump host (loop guard,
  # unchanged from today).
  if [ -n "$target" ] && [ "$target" = "$ANL_JUMP" ]; then
    return
  fi
  # NEW (Sub-fix C): if the target alias already has its own
  # ProxyJump/ProxyCommand via ~/.ssh/config, defer to it. Adding our
  # -J on top would either be redundant (best case) or trigger a jump
  # loop (if the alias's proxy IS the same host we'd add).
  if [ -n "$target" ] && _alias_has_own_proxy "$target"; then
    _alias_proxy_notice_dedup "$target" "$user"
    return
  fi
  printf -- '-J %s@%s' "$user" "$ANL_JUMP"
}
```

Same treatment for the SCP branch at line 4383.

**Where to touch**: `ssh_jump_args`
(`src/argo_anywhere/engine/argo-anywhere.sh:1778`) + the SCP
ProxyJump line (~L4383). Helper alongside the others in Section 8.

### 2.4 Shared infrastructure: `--jump-host HOST` + `ARGO_ANYWHERE_JUMP_HOST` (optional but recommended)

Complements A-C for the third user cohort — those who *don't* have a
polished ssh_config but *do* need a different jump host (say,
`logins.alcf.anl.gov` or a personal bastion). Add:

- **CLI**: `--jump-host HOST` (overrides `ANL_JUMP` for THIS run).
- **Env**: `ARGO_ANYWHERE_JUMP_HOST=<host>` (canonical namespace).
- **`--no-jump`** remains the explicit "skip jump host" flag.

**CLI-vs-env empty semantics** (per §7 A9 audit correction — earlier
draft conflated the two):

- **CLI**: `--jump-host ""` is a **parse-time die**. Consistent with
  every other engine flag (`--user ""`, `--node ""`, `--port ""`
  all die today). Direct the user to `--no-jump` if they meant to
  skip the jump host entirely.
- **Env**: `ARGO_ANYWHERE_JUMP_HOST=""` is treated as "no jump."
  This matches shell convention for opt-out env vars (e.g. `NO_PROXY=""`
  means "no NO_PROXY set" in some tools; here we're the opposite —
  explicit empty == explicit skip). The `${VAR+set}` idiom
  distinguishes "unset" from "empty" so we can implement this cleanly.

Runtime resolution (add at top of `main()` after argv parse, near the
existing legacy-alias promotion at
`src/argo_anywhere/engine/argo-anywhere.sh:1346`):

```bash
# --jump-host / ARGO_ANYWHERE_JUMP_HOST resolution.
#
# CLI flag: --jump-host somehost   → ARGO_ANYWHERE_JUMP_HOST=somehost
# CLI flag: --jump-host ""         → die at parse-time (--no-jump exists)
# Env: ARGO_ANYWHERE_JUMP_HOST=x   → override ANL_JUMP=x
# Env: ARGO_ANYWHERE_JUMP_HOST=""  → equivalent to --no-jump
# Env: ARGO_ANYWHERE_JUMP_HOST unset → ANL_JUMP stays at default
if [ "${ARGO_ANYWHERE_JUMP_HOST+set}" = "set" ]; then
  if [ -z "$ARGO_ANYWHERE_JUMP_HOST" ]; then
    # Explicit empty env == no jump. Never fires via CLI (that dies).
    ARGO_ANYWHERE_NO_JUMP=1
  else
    ANL_JUMP="$ARGO_ANYWHERE_JUMP_HOST"
  fi
fi
```

And the argv parser (in `main()`, argv parser at
`src/argo_anywhere/engine/argo-anywhere.sh:10585` region):
```bash
--jump-host)
  [ -n "${2:-}" ] || die "--jump-host expects a value (a hostname). To skip the jump host, use --no-jump."
  ARGO_ANYWHERE_JUMP_HOST="$2"; export ARGO_ANYWHERE_JUMP_HOST
  shift 2 ;;
```

**Precedence** when multiple settings are given:
- `--no-jump` on CLI wins over everything (most explicit).
- `--jump-host HOST` on CLI overrides `ARGO_ANYWHERE_JUMP_HOST` env.
- `ARGO_ANYWHERE_JUMP_HOST=""` env == `--no-jump`.
- Default: `ANL_JUMP="logins.cels.anl.gov"` (unchanged).

`ANL_JUMP` stays a mutable script global (it always was; the writers
just never wrote to it). Every existing call site keeps working
because they all read `$ANL_JUMP` at call-time. See §7 B8 for the
42-reference audit confirming no local shadow / `readonly`
declaration to worry about.

**Where to touch**: main() argv parser
(`src/argo_anywhere/engine/argo-anywhere.sh:10585` region), env-var
snapshot block (Section 5, around L230), env-promotion block
(Section 6, around L1346), help text (Section 24, around L10027).

### 2.5 Docs updates (mandatory, part of the same commit)

- `README.md`:
  - "MFA / Duo handling" section — add a sub-block "Using your own
    ssh_config route" that shows the polaris-login-style block and
    the three ways it works out of the box now.
  - "Common operations" — add an example row: `argo-anywhere
    --cli-tool opencode client --node polaris-login` (no `--user`,
    no `--no-jump`).
- `docs/UPGRADING.md`: post-3.1.0 "What's new" bullet: "argo-anywhere
  now respects `~/.ssh/config`. If `ssh <alias>` works for your
  ANL nodes, `--node <alias>` works too; username and jump host are
  inferred from the config unless you override them. `--jump-host
  HOST` (or `ARGO_ANYWHERE_JUMP_HOST`) points our SSH at a
  different bastion; if you use a non-CELS jump in production and
  hit issues, please open an issue with your setup so we can
  extend the live-verification guide." (Feedback-channel note per
  §8 Q6 decision.)
- `docs/LIMITATIONS.md`: retire (or soften) the "hardcoded jump host"
  implicit limitation; note that the ANL Duo assumption still holds
  regardless of jump route.
- `AGENTS.md` "MFA-aware by default" section: add a short "Jump-host
  resolution" bullet explaining the new precedence
  (`--jump-host` > `ARGO_ANYWHERE_JUMP_HOST` > `ssh_config`
  ProxyJump/ProxyCommand > `ANL_JUMP` default).
- `AGENTS.md` "Env vars are namespaced": add
  `ARGO_ANYWHERE_JUMP_HOST` to the canonical-name list.
- Help block (`src/argo_anywhere/engine/argo-anywhere.sh:10007+`):
  document `--jump-host HOST` under the transport-flag section,
  update `--no-jump` help text to mention the new flag as a
  narrower-scope alternative.

**`ANL_JUMP` footprint note** (per §7 B8): `ANL_JUMP` is referenced
in **42 places** across the engine, broken down as:
- **5** runtime SSH construction sites (`ssh_jump_args`, SCP
  ProxyJump, `ssh_preflight` fallback + log lines, mux-open log).
  All read `$ANL_JUMP` at call-time → automatically pick up the
  override.
- **2** error-message interpolations at :1927 + :2040 (SSH failure
  recovery). Interpolated at print time → picks up override.
- **2** status output sites at :7390 (status card) + :7482 (example
  ssh command). Interpolated at print time → picks up override.
- **~23** help text + template-command references in Section 24
  (help block :10007-10540). All interpolated via `${ANL_JUMP}` in
  the here-doc; picks up override.
- **~10** comment references + template `ssh -J <user>@${ANL_JUMP}
  <user>@<node>` lines in error messages at :7602-7606, :10438-10443.
  Picks up override.

**Load-bearing invariant**: `ANL_JUMP` must never be declared
`local`, `readonly`, or shadowed inside a function that's called
after the resolution block above. C3 adds a shellcheck-style
comment near the declaration warning future editors of this
contract; no runtime enforcement (would need a bash trap trick that
isn't worth the complexity).

### 2.6 Web-UI implications

Fully addressed in **Track W (§10; commits C4-C6)**. Summary of the
coupling this plan introduces:

- **New launcher popover fields**: `lNode`, `lUser`, `lJump` mirror
  the engine's `--node` / `--user` / `--jump-host` flags 1:1.
- **New endpoints**: `/api/ssh-hosts` (populates the alias
  datalist) and `/api/preview-launch` (reflects the engine's
  resolution back to the user before Launch).
- **Coupling contract**: any rename of the three engine flags
  above, or of the helper functions `_ssh_config_hostname` /
  `_ssh_config_user` / `_alias_has_own_proxy`, MUST land with a
  matching web-UI edit. AGENTS.md's D-031 coupling rule is
  extended in C6 to codify this alongside the existing
  scope-value coupling.

Verify by grep: today (pre-C4) no launcher popover field is named
"jump" or "user"; C4 adds them; C6 tests that the preview panel's
Python-side jump-args reflection matches the engine's `ssh_jump_args`
output byte-for-byte on a stub-`ssh` fixture.

---

## 3. Backwards compatibility

- **Every today-supported invocation continues to work unchanged**:
  - `--node compute-01.cels.anl.gov` + `--user <ANL-username>`: fqdn
    matches ANL_NODES, `_alias_has_own_proxy` returns false (bare
    fqdns have no ssh_config Host block), `ssh_jump_args` still emits
    `-J <ANL-username>@logins.cels.anl.gov`. Identical to today.
  - `--node compute-386-02.cels.anl.gov` (a physical name not in
    ANL_NODES): today prints a warning; behavior unchanged.
  - `--no-jump`: still wins; jump-args returns empty.
  - `ARGO_ANYWHERE_USER=<ANL-username>` set in shell rc: still
    highest priority above ssh-config-derived user.
- **New failure modes** (all opt-in via using an alias):
  - `ssh -G` on some legacy OpenSSH could behave differently. The
    audit needs to confirm this works on the versions we care about
    (OpenSSH 5.6+ per `-G` history; macOS ships 9.x since Ventura).
    Fallback: on any `ssh -G` failure, resolvers return empty →
    today's paths (die/prompt/hardcode) fire as before.
- **Legacy env vars**: no new legacy aliases needed;
  `ARGO_ANYWHERE_JUMP_HOST` is fresh, so there's no
  `ARGO_OPENCODE_JUMP_HOST` to promote.

---

## 4. Testing

### 4.1 Existing smoke tests (must still pass)

```sh
bash -n src/argo_anywhere/engine/argo-anywhere.sh
argo-anywhere -h
argo-anywhere help | head -50
argo-anywhere status
argo-anywhere clean --dry-run -y --local-only
pytest -q  # the Python layer; nothing here calls the new helpers
```

### 4.2 New unit tests (bash-level; via existing test harness)

Add `tests/test_engine_ssh_config.py` with fixtures that stub `ssh`
with a small shell script installed in a temp PATH:

- **`test_ssh_jump_args_skips_when_alias_has_proxyjump`**: fake `ssh
  -G polaris-login` to print `hostname compute-386-02.cels.anl.gov\n
  user <ANL-username-1>\nproxyjump <ANL-username-1>@logins.cels.anl.gov`;
  assert `ssh_jump_args <ANL-username-2> polaris-login` prints empty.
- **`test_ssh_jump_args_adds_when_alias_has_no_proxy`**: fake `ssh
  -G plain-node` to print `hostname plain-node\nuser <ANL-username>\n
  proxycommand none`; assert `ssh_jump_args <ANL-username> plain-node`
  prints `-J <ANL-username>@logins.cels.anl.gov`.
- **`test_ssh_jump_args_respects_no_jump`**: with
  `ARGO_ANYWHERE_NO_JUMP=1`, both scenarios above print empty.
- **`test_resolve_username_from_ssh_config`**: fake `ssh -G
  polaris-login` returns `user <ANL-username>`; ARGO_ANYWHERE_USER
  unset; cache absent; assert `resolve_username` picks `<ANL-username>`
  and logs the source.
- **`test_resolve_username_flag_beats_ssh_config`**: fake `ssh -G
  polaris-login` returns `user <ANL-username-1>`;
  `ARGO_ANYWHERE_USER=<ANL-username-2>` in env; assert
  `<ANL-username-2>` wins.
- **`test_pick_node_accepts_alias_with_notice`**: assert the picker
  no longer dies on an unknown-to-ANL_NODES alias when `ssh -G`
  resolves it; captures the notice.
- **`test_jump_host_override`**: `ARGO_ANYWHERE_JUMP_HOST=bastion.example.com
  ssh_jump_args <ANL-username> compute-01.cels.anl.gov` prints
  `-J <ANL-username>@bastion.example.com`.
- **`test_jump_host_env_empty_means_no_jump`**:
  `ARGO_ANYWHERE_JUMP_HOST=""` (env, explicitly empty) →
  `ssh_jump_args` prints empty (equivalent to `--no-jump`).
- **`test_jump_host_cli_empty_dies`** (per §7 A9): `argo-anywhere
  --jump-host "" help` exits non-zero with a message pointing at
  `--no-jump`. Distinguishes CLI-empty (die) from env-empty (skip).
- **`test_no_local_ANL_JUMP_shadow`** (per §8 Q6 decision): grep-
  based invariant. Assert `grep -nE 'local[[:space:]]+ANL_JUMP=|
  readonly[[:space:]]+ANL_JUMP='
  src/argo_anywhere/engine/argo-anywhere.sh` returns nothing.
  Catches the one class of regression Scenario Y would have
  caught (a future refactor accidentally shadowing the mutable
  script global). Runs on every CI pass; deterministic; no
  infrastructure needed.
- **`test_ANL_JUMP_references_use_expansion`** (per §8 Q6): grep-
  based invariant. Assert every reference to `ANL_JUMP` in the
  engine either interpolates it at use-site (`${ANL_JUMP}` or
  `$ANL_JUMP` in a string), OR appears in a small allowlist of
  known declaration/assignment sites (line 334 declaration, the
  `--jump-host` resolution block in `main()`, the audit-note
  comment). Any new reference outside the allowlist that doesn't
  interpolate is a candidate for breaking the override
  propagation contract; test fails loudly. Test-file lives at
  `tests/test_engine_ssh_config.py` alongside the other engine
  tests.
- **`test_alias_localhost_does_not_short_circuit`** (per §7 A3):
  fake `ssh -G loopback-alias` returns `hostname 127.0.0.1`;
  assert `host_is_target loopback-alias` returns "no" (the
  interface-IP filter at `_my_interface_ips` excludes loopback,
  so an alias pointing at loopback is NOT the on-node case).
- **`test_ssh_config_user_not_cached`** (per §7 A7): fake
  `ssh -G polaris-login` returns `user <ANL-username>`; `USER_CACHE`
  absent; assert `resolve_username` returns `<ANL-username>` AND that
  `$USER_CACHE` does not exist after the call
  (`_USERNAME_SHOULD_CACHE` was 0).
- **`test_alias_proxy_notice_deduped`** (per §7 D6): call
  `ssh_jump_args <ANL-username> polaris-login` ten times in a loop;
  assert the "routes via ~/.ssh/config" log line appears
  exactly once in captured stderr.
- **`test_log_sanitizes_control_chars`** (per §7 C2): fake a
  ProxyCommand containing ANSI escape (`\e[31m`); assert the
  string is not present in captured log output (either stripped
  or escaped).

### 4.3 Live verification (add to `docs/TESTING.md`)

One new scenario, requiring real Duo but doable in one session
(per §8 Q6 decision: dropped the custom-jump-host scenario in
favor of grep-based invariant tests — no maintainer needs to own
an alternate jump host to verify the plan):

- **Scenario X — ssh_config alias**:
  1. Ensure a working `Host polaris-login` block in `~/.ssh/config`
     that yields a working `ssh polaris-login`.
  2. `argo-anywhere --cli-tool opencode client --node polaris-login`
     (no `--user`, no `--no-jump`).
  3. Expect: single Duo prompt (if ssh_config still uses cels jump);
     `log` line "Using ANL username: <ANL-username> (source: ~/.ssh/
     config for polaris-login)"; ALL GREEN status.

Complements the unit-test coverage in §4.2. Live verification's
unique value here is catching integration issues unit tests can't
(mux socket naming, SSH failure tracker interaction, monitor-loop
reconnect behavior when the alias resolves to a different physical
host between runs).

**Note on `--jump-host` verification**: no live scenario. The
`--jump-host` override is verified by (a) `test_jump_host_override`
in §4.2 (unit-level; stubs `ssh`) and (b) the grep-based invariants
`test_no_local_ANL_JUMP_shadow` +
`test_ANL_JUMP_references_use_expansion` (§4.2; static checks that
answer "does the override reach all 42 references?" deterministically).
Users who hit issues with a real alt-jump in production are directed
to open an issue via a one-line note in `docs/UPGRADING.md`.

---

## 5. Files touched (planned inventory)

Grouped by track + commit so the review surface for each commit is
legible.

### Track E (commits C1 – C3)

| File | Sections | Commit | Est. LOC delta |
|:---|:---|:---:|:---:|
| `src/argo_anywhere/engine/argo-anywhere.sh` | new helpers in §2 (`_ssh_config_hostname`, `_ssh_config_user`, `_alias_has_own_proxy`); `--jump-host` argv parser + env snapshot | C1 | ~50 |
| `argo-anywhere.sh` (repo-root historical copy) | byte-identical mirror per D-028 | C1 | mirrors |
| `src/argo_anywhere/engine/argo-anywhere.sh` | `ssh_jump_args`; SCP branch `:4383`; `resolve_username`; `pick_node` "not in list" branch | C2 | ~70 |
| `argo-anywhere.sh` (repo-root historical copy) | mirror | C2 | mirrors |
| `tests/test_engine_ssh_config.py` (NEW) | 7-8 unit tests via `ssh` stub | C2 | ~180 |
| `README.md` | MFA section + Common ops row | C3 | ~30 |
| `docs/UPGRADING.md` | post-3.1.0 bullet | C3 | ~10 |
| `docs/LIMITATIONS.md` | soften jump-host note | C3 | ~5 |
| `AGENTS.md` | MFA section bullet; env-var list; status line | C3 | ~20 |
| `PLAN.md` | new D-032 for the ssh-config integration; status line | C3 | ~40 |
| Help block inside the engine | `--jump-host` docs; refresh `--no-jump` text | C3 | ~20 |
| `notes/test_plan_v3_1_0.md` (NEW) | consolidated live-test plan for the v3.1.0 tag (extras consolidation + PyYAML + ssh-config engine + ssh-config web UI); per §8 Q13 decision | C3 | ~150 |

### Track W (commits C4 – C6)

| File | Sections | Commit | Est. LOC delta |
|:---|:---|:---:|:---:|
| `src/argo_anywhere/web/static/index.html` | launcher popover: node/user/jump-host fields | C4 | ~40 HTML + ~15 JS |
| `src/argo_anywhere/web/app.py` | `build_launch_argv` accepts + validates `node`/`user`/`jump_host`; `/api/launch-external` + `/ws` intake threads them through | C4 | ~30 |
| `src/argo_anywhere/web/validation.py` | reuse existing `_SAFE_TOKEN` for all three new fields (per §7 W1 audit: `_SAFE_TOKEN` = `^[A-Za-z0-9._-]+$` is exactly right; no `_SAFE_HOSTLIKE` needed) | C4 | ~0 (import only) |
| `tests/test_web.py` | new coverage: launcher fields pass through; malformed values rejected | C4 | ~50 |
| `src/argo_anywhere/web/ssh_hosts.py` (NEW) | `_parse_ssh_config_hosts()` reader with wildcard filter | C5 | ~60 |
| `src/argo_anywhere/web/app.py` | new `/api/ssh-hosts` endpoint (loopback + host-guard) | C5 | ~20 |
| `src/argo_anywhere/web/static/index.html` | `<datalist id="nodeHosts">` populated on page load + small refresh button (↻) per §7 W10 audit (moved from §10.7 to C5) | C5 | ~30 JS + ~5 HTML |
| `tests/test_ssh_hosts.py` (NEW) | fixture ssh_configs → alias enumeration; wildcard filter | C5 | ~90 |
| `src/argo_anywhere/web/app.py` | new `/api/preview-launch` endpoint (`ssh -G` resolution + our-jump-args reflection) | C6 | ~40 |
| `src/argo_anywhere/web/static/index.html` | preview panel + on-input debounce | C6 | ~40 HTML + ~30 JS |
| `AGENTS.md` "Engine ↔ web-UI coupling rule" (D-031) | extend to cover node/user/jump-host + preview endpoint | C6 | ~15 |
| `tests/test_web.py` | preview-endpoint smoke tests (mocked `ssh -G`) | C6 | ~40 |

Total across both tracks: **~800 LOC (mostly comments/tests/docs);
core code delta ~150 LOC** (engine ~40, web ~110). Engine track by
itself matches the prior estimate (~400 LOC / ~40 core).

---

## 6. Design decisions to add to PLAN.md

Add as **D-032** (confirmed next free number per §8 Q7):

> **D-032. Native `~/.ssh/config` respect (engine + web UI)** —
> 2026-07-15 [v3.1.0-in-progress].
>
> argo-anywhere resolves per-target ssh_config via `ssh -G <alias>`
> and uses the results as fallback signals for (a) hostname
> acceptance in `--node`, (b) username inference in
> `resolve_username`, and (c) suppression of our `-J <user>@<jump>`
> when the alias defines its own `ProxyJump`/`ProxyCommand`. The
> `logins.cels.anl.gov` default remains; users override via
> `--jump-host HOST` / `ARGO_ANYWHERE_JUMP_HOST`. Rationale: many
> ANL users maintain `~/.ssh/config` blocks that handle on-site
> vs. off-site routing themselves; `ssh <alias>` "just works" for
> them and `argo-anywhere --node <alias>` should too. Preserves
> the ANL-Duo-plus-argo-proxy assumption; does not generalize
> the engine to non-ANL environments (see rejected alternative
> E4 in §7 of this plan).
>
> The web UI surfaces the same contract through the launcher
> popover's node/user/jump-host fields plus a resolved-launch
> preview panel (Track W; commits C4-C6). Tri-lockstep coupling
> requirement (recorded in AGENTS.md): any rename of the three
> new engine flags (`--node`, `--user`, `--jump-host`), the
> three new engine helpers (`_ssh_config_hostname`,
> `_ssh_config_user`, `_alias_has_own_proxy`), or the
> `_reflect_our_jump_args` Python reflection MUST land in the
> same commit as the corresponding launcher popover field / API
> shape update.

---

## 7. Multi-pass audit (user-requested; blockers to executing)

The user asked for a multi-pass audit BEFORE we execute. This
section enumerates the sharp edges and open questions we need to
answer or accept before writing code. Each entry has a suggested
disposition; the user should either confirm or override before
Pass 2 (implementation).

### Pass 1: correctness / logic edges

- **A1. `ssh -G` availability floor. RESOLVED — KEEP.** `ssh -G`
  was added in OpenSSH 5.6 (2010). Confirmed 2026-07-15 on
  OpenSSH 10.2p1 (Ahmed Attia's laptop). RHEL 7 has 7.4. All plausible
  live users covered. Every new helper falls back to today's
  behavior on `ssh -G` failure (defensive comment already in
  sketches).
- **A2. `ssh -G` output field name capitalization. RESOLVED —
  KEEP with evidence.** Confirmed 2026-07-15: output is fully
  lowercase (`hostname`, `user`, `port`, `controlmaster`,
  `proxyjump`, `proxycommand`) on OpenSSH 10.2p1. Awk patterns in
  §2 sketches are correct as-written.
- **A3. Alias resolves to `localhost` / same host. RESOLVED —
  KEEP + add test.** `host_is_target` (engine :788-810) already
  filters loopback via `_my_interface_ips`
  (`grep -vE '^(127\.|0\.0\.0\.0$)'`). An alias pointing at
  `127.0.0.1` will NOT match — the on-node short-circuit doesn't
  trip. Documented as `test_alias_localhost_does_not_short_circuit`
  in §4.2.
- **A4. `_alias_has_own_proxy` awk idiom. RESOLVED — PLAN
  REVISED.** The `found=1; END{exit found?0:1}` form is
  set-e-hostile and reads awkwardly. Replaced in §2.3 with the
  cleaner `exit 0`/`exit 1` split. Also switched from `echo` to
  `printf '%s\n'` for portability (POSIX `echo -e` behavior varies).
- **A5. Mux-socket naming when alias vs. fqdn intermix. RESOLVED
  — ESCALATED.** Was flagged as "cosmetic"; audit escalates to
  documented limitation. Two sockets for the same physical host
  create real papercuts when the user tries to `ssh -O check` or
  `stop` and picks the "wrong" alias. **Action** (added to C3):
  document in `docs/LIMITATIONS.md` under a new "SSH socket
  duplication with mixed alias/fqdn use" bullet; advise picking
  one form per compute node and sticking with it. No runtime
  warning attempted (detection requires resolving each cached
  entry every run — too costly for a papercut).
- **A6. ANL-suffix heuristic. REJECTED — PLAN REWRITTEN.** The
  whole heuristic is unnecessary. Sub-fix A's job (per the
  §2.1 rewrite) is just to make the existing warn message
  helpful when it happens to be an alias; the ANL-vs-non-ANL
  classification doesn't buy anything. Removed from §2.1. If a
  user aims argo at a non-ANL host, the subsequent `ssh_reachable`
  or bootstrap-`pip install argo-proxy` will fail with a real
  error; no need to pre-classify.
- **A7 (NEW). `resolve_username` auto-caches prompted values.
  BUG DISCOVERED — PLAN REWRITTEN.** Engine :2216 writes the
  prompted username to `USER_CACHE` before returning. If we
  naively slot ssh-config inference in as an earlier source, we
  never write the cache (short-circuit before the prompt) but
  ALSO must not cache the inferred value (per engine reject E3:
  "cache is write-only-from-explicit-actions"). §2.2 refactored:
  `resolve_username` now sets `_USERNAME_SOURCE` +
  `_USERNAME_SHOULD_CACHE` globals and defers the cache write to
  the caller. Prompt-source values still get cached (unchanged);
  ssh-config values don't. Test coverage:
  `test_ssh_config_user_not_cached` in §4.2.
- **A8 (NEW). `ssh_preflight`'s `ANL_JUMP` fallback. RESOLVED —
  KEEP.** Engine :4082 uses `target="$ANL_JUMP"` when no node is
  known. Reads `$ANL_JUMP` at call-time → automatically picks up
  the `--jump-host` override. No plan change beyond the
  precedence resolution (already in §2.4).
- **A9 (NEW). `--jump-host ""` semantics. RESOLVED — PLAN
  REVISED.** Original draft conflated CLI-empty with env-empty.
  §2.4 rewritten: CLI-empty dies at parse (consistent with every
  other engine flag; direct user to `--no-jump`); env-empty means
  "no jump" (matches shell convention for opt-out env vars, and
  distinguishes cleanly from "env unset" via `${VAR+set}`). Test
  coverage: `test_jump_host_cli_empty_dies` +
  `test_jump_host_env_empty_means_no_jump` in §4.2.

### Pass 2: interaction with existing features

- **B1. `on_anl_compute_node`. RESOLVED — KEEP.** Verified: the
  auto-flip at engine :5835-5845 uses `hostname -f` on the
  compute-node side; unaffected by anything on the laptop side.
  No interaction.
- **B2. Bootstrap SSH forwarded flags. RESOLVED — KEEP + test.**
  Verified: `remote_bootstrap` at :4415 uses
  `ssh $(ssh_args "$user" "$node") "${user}@${node}" ...`.
  `ssh_args` composes mux + jump; when `_alias_has_own_proxy`
  returns true, `-J` is omitted; alias's own ProxyJump takes
  effect. `${user}@${node}` positional target: ssh's own
  target-parser respects a CLI-supplied user over ssh_config's
  `User <name>` — so if we resolved a different user (e.g. via
  cache) than the alias's config, the CLI value wins (correct
  precedence). Test case documenting this in §4.2.
- **B3. install-launcher. RESOLVED — KEEP.** Confirmed via
  `src/argo_anywhere/launcher.py`: launcher scripts bake only
  the Python interpreter path + argv. No SSH-related state.
  Nothing to change.
- **B4. Web UI channel-connect flow. PARTIAL REJECT — PLAN
  REVISED.** Original text claimed the launcher popover "has a
  'node' field today" — WRONG. Verified by reading
  `index.html:411-427`: only `lTool` / `lScope` / `lTarget` /
  `lCwd` exist. §10.1 in the plan (Track W baseline) already
  documents this correctly. Rewrote this bullet to reference
  §10 rather than repeat the (incorrect) old claim. The engine's
  behavior does work transparently for web-driven verbs; the
  actual work is adding the missing UI surface (§10; C4-C6).
- **B5. Cross-client port coherence (D-021). RESOLVED — KEEP.**
  Port cache is transport-layer state, orthogonal to jump-host.
  Not affected.
- **B6. `stop`, `clean`, `status`, `update` verbs. RESOLVED —
  ESCALATED.** `NODE_CACHE` now potentially holds an alias.
  Subsequent verbs use the same alias correctly (routing works).
  BUT the mental-model muddling ("did I clean the right place?")
  is real. Original disposition ("leave alone; add a cosmetic
  note") upgraded to: **`status` MUST display both the alias
  AND the resolved fqdn when they differ** (moved to §7 D5
  must-do; landed in C3). Format:
  ```
  Compute node: polaris-login → compute-386-02.cels.anl.gov
  ```
  Cheap (one `_ssh_config_hostname` call) and closes the mental-
  model gap.
- **B7. Install-manifest identity. RESOLVED — KEEP.** Verified:
  the manifest (D-025, `_manifest_record_config`) is laptop-side
  only; records client-config provenance; does NOT record
  compute-node identity. So B6's alias-vs-fqdn ambiguity doesn't
  propagate here. Nothing to change.
- **B8 (NEW). `ANL_JUMP` 42-reference footprint. RESOLVED —
  DOCUMENTED.** Grepped: 42 references, all read `$ANL_JUMP` at
  call/interpolation time. Categorized in §2.5's "ANL_JUMP
  footprint note." Load-bearing invariant: `ANL_JUMP` must
  never be `local` / `readonly` / shadowed in a function called
  after `main()`'s resolution block. §2.5 adds a shellcheck-style
  comment near the `ANL_JUMP=` declaration to warn future
  editors.
- **B9 (NEW). `on_anl_compute_node` cache with `--jump-host`.
  RESOLVED — NO-OP.** The `_ON_ANL_NODE_CACHE` global is
  per-invocation; no state persists across runs. `--jump-host`
  doesn't affect `hostname -f`. No interaction.

### Pass 3: security & threat model

- **C1. `ssh -G` output trust. RESOLVED — KEEP.** `~/.ssh/config`
  is user-owned; attacker-writable ssh_config == attacker owns
  ssh. `ssh -G` doesn't execute config content, only prints
  parsed values. No new surface.
- **C2. ProxyCommand log injection. RESOLVED — REVISED
  DISPOSITION.** Original disposition (`printf '%q'`) protects
  against shell reinjection but NOT against ANSI escape sequences
  or other control chars. A malicious config with
  `ProxyCommand /bin/sh -c "\e[31mowned\e[0m"` would color the
  log if echoed. **Revised fix**: add a `sanitize_for_log`
  helper to the engine (Section 8, alongside the other new
  helpers):
  ```bash
  # Strip control chars except \t\n so log/warn/err output can't
  # be tricked into cursor moves, color changes, or terminal
  # confusion by a hostile ~/.ssh/config value.
  sanitize_for_log() {
    LC_ALL=C tr -d '\000-\010\013\014\016-\037'
  }
  ```
  Use it anywhere we `log`/`warn` a raw ssh_config-derived value
  (currently: the alias-has-own-proxy notice, the ssh-config-
  user log line, and any error-message interpolation). Test
  coverage: `test_log_sanitizes_control_chars` in §4.2. Also
  applies web-side (Track W): see C5 below.
- **C3. SSH failure lock semantics. RESOLVED — KEEP.** The
  proposed error-message enhancement stands: when the lock fires
  AND `_alias_has_own_proxy $ARGO_ANYWHERE_NODE` returned 0,
  mention "the target routes via ~/.ssh/config; check that
  block for a stale ProxyJump/ProxyCommand." Landed in C2 (the
  engine commit, not the audit finding — sorry for the naming
  collision). **Cross-reference** (per §8 Q11): neither
  `/api/ssh-hosts` (pure file parse) nor `/api/preview-launch`
  (`ssh -G` only, non-authenticating) contributes to the SSH
  failure counter; both are IP-block-safe by construction. Only
  the engine's real `ssh_reachable` / `ssh_mux_open` / SCP /
  bootstrap paths increment the tracker (unchanged from today).
- **C4. `--jump-host` accepting arbitrary hosts. RESOLVED —
  KEEP.** No security boundary crossed. Standard SSH semantics.
- **C5 (NEW). Web-side `ssh -G` and `Match exec` timeout.
  RESOLVED — DOCUMENTED.** `/api/preview-launch` runs
  `subprocess.run(["ssh", "-G", node], ..., timeout=2)`:
    - `subprocess.run` with a **list** (not `shell=True`) is
      injection-safe by construction — argv boundaries stay
      argv boundaries.
    - `ssh -G` doesn't authenticate but DOES honor
      `Match exec <command>` blocks in the user's own ssh_config.
      Those blocks shell out. Malicious user's own config could
      run arbitrary commands — but that's the user attacking
      themselves via their own file; not our surface.
    - The 2s timeout is what protects the endpoint from a
      runaway `Match exec` hanging the server thread.
  §10.4 updated to spell all three out explicitly.
- **C6 (NEW). Server-side field validation on `/api/preview-launch`.
  RESOLVED — PLAN REVISED.** Original §10.4 sketch validated
  cwd but not the node/user/jump-host inputs before passing to
  `ssh -G`. Even though `subprocess.run` with a list is
  injection-safe, hygiene says validate first, reject with 400
  on bad input. §10.4 updated: apply `_SAFE_TOKEN` server-side
  to all three fields; reject `@`, `/`, `:`, whitespace, shell
  metachars before `ssh -G` sees them.

### Pass 4: UX and error-message audit

- **D1. Log noise / memoization. RESOLVED — REFINED.**
  Memoization confirmed feasible in bash 3.2: `${var//pattern/
  replacement}` IS supported (only `${var,,}` lowercasing is a
  bash 4 feature; verified). Memo cache in globals named
  `_ALIAS_CACHE_${alias//[^a-zA-Z0-9]/_}`. **Refinement**: memo
  MUST clear on any `_ARGO_RESET_ALIAS_CACHE=1` sentinel; used
  by tests that need to run multiple `main()` invocations in
  one process (rare, but tests do this).
- **D2. Notice framing. RESOLVED — KEEP.** `log` (not `warn`).
  No "note:" prefix. Trailing colon in the log helper is
  sufficient transparency marker.
- **D3. `--user` prompt corner cases. RESOLVED — REVISED
  MATRIX.** The A7 refactor changes this. New three-case matrix:
    1. **interactive + no cache + no env + ssh-config User line
       present** → log source, use ssh-config value, DO NOT
       prompt, DO NOT cache. New happy path.
    2. **interactive + no cache + no env + ssh-config silent** →
       prompt, cache the prompted value. Unchanged.
    3. **non-interactive (`-y`) + no cache + no env + ssh-config
       silent** → die. Unchanged.
    4. **non-interactive (`-y`) + no cache + no env + ssh-config
       User line present** → log source, use value, don't die.
       New; strictly better than today.
  Test coverage: all four cases in §4.2's `test_resolve_username_*`
  suite.
- **D4. Help block ordering. RESOLVED — KEEP + amend.** Add
  `--jump-host` right after `--no-jump`. **Amend** the `--no-jump`
  wording to remove the earlier draft's suggestion that
  `--jump-host ""` is equivalent — per §7 A9, CLI-empty dies;
  only env-empty means skip. `--no-jump` remains the CLI-only
  way to skip.
- **D5. Status output. RESOLVED — ELEVATED to load-bearing.**
  Was "small delta; low risk"; audit B6 escalates to must-do for
  C3. `status` MUST show:
  ```
  Compute node: polaris-login → compute-386-02.cels.anl.gov
  Username:     <ANL-username> (source: ssh-config:polaris-login)
  Jump host:    logins.cels.anl.gov (default)
                # or: alt-jump.example.org (custom via ARGO_ANYWHERE_JUMP_HOST)
                # or: (skipped — --no-jump)
  ```
  Closes the mental-model gap from B6. Landed in C3 explicitly
  (not deferred).
- **D6 (NEW). Notice fatigue if `_alias_has_own_proxy` log fires
  every ssh call. RESOLVED — PLAN REVISED.** `ssh_jump_args` is
  called from ~10+ sites per `client` run (via `ssh_args` from
  every `ssh_reachable`, `ssh_mux_open`, SCP branch, monitor-loop
  reconnect ssh, etc.). Without dedup the user sees the same
  "routes via ssh_config" notice a dozen times. §2.3 revised:
  added `_alias_proxy_notice_dedup` helper (bash-3.2-compatible
  via `${var//pat/replacement}` + `eval`-based indirect read on
  a scrubbed variable name). Fires once per alias per invocation.
  Test coverage: `test_alias_proxy_notice_deduped` in §4.2.

### Pass 5: what we're deliberately NOT doing

Explicit rejects so the audit doesn't accidentally reopen them:

- **E1. Multi-config file support (`-F <file>`).** Would need a
  cascade of `SSH_CONFIG_FILE` handling. Not in scope; users can
  set `$HOME/.ssh/config` or symlink.
- **E2. `Include` directive expansion.** `ssh -G` already expands
  Includes for us. Zero engine change needed.
- **E3. Persisting ssh-config-derived values into `USER_CACHE`.**
  Would mean re-writing the cache on a rerun from the same laptop
  even if the user's config later removed the User line.
  *Deliberate NO*: cache remains write-only-from-explicit-actions
  (flag / interactive prompt / on-node bootstrap). ssh-config
  inference is a runtime fallback, not a state mutator.
- **E4. Generalizing beyond ANL.** Per user's answer 2 to
  clarifying questions — we keep the ANL assumption
  (`argo-proxy`-installable Python on the target; Duo-protected
  auth) and just get more flexible about which SSH route reaches
  those ANL nodes.
- **E5. `~` (edited 2026-07-15).** Web-UI launcher enhancements
  are now in scope (§10; commits C4-C6). What we're still NOT
  doing: exposing an ssh_config *editor* in the web UI (E5.a
  below), auto-picking an alias based on cwd heuristics beyond the
  existing scope-default coupling (E5.b below), or persisting
  ssh-config-inferred values into `web_state.json`'s MRU (E5.c
  below).
    - **E5.a. No in-app ssh_config editor.** `~/.ssh/config` is
      user-owned personal-security state; a web UI writing to it
      multiplies argo-anywhere's security surface (the loopback-
      only + argv-allowlist posture stops mattering when the app
      can edit auth-affecting files). AGENTS.md's threat-model
      discipline argues against.
    - **E5.b. No cwd-triggered alias auto-select.** The launcher's
      cwd-aware scope default (D-031) nudges toward `global` when
      cwd == `$HOME`; nudging toward a specific alias based on
      cwd content (say, a repo-local `.ssh/config` fragment) is
      too magical for a v1 and violates the "one-directional
      nudge" principle D-031 documents.
    - **E5.c. No persisting of inferred values.** Web-state MRU
      records what the user typed (alias or fqdn), NOT what
      `ssh -G` resolved it to. Consistent with engine-side E3.
- **E6. Cursor/aider/opencode config changes.** None needed; this
  is pure transport-layer work. Per-tool writers are unaffected.

### Pass 6: rollback plan

If a live test surfaces a regression we can't diagnose quickly:

- **Track W only** (regression in C4/C5/C6): `git revert` the
  offending web-UI commit(s). Engine untouched; CLI users
  unaffected. `web_state.json` may contain a `node` MRU field
  (added by C4) that the reverted UI ignores — harmless.
- **Full ssh-config rollback** (regression in Track E or E+W):
  `git revert` C6→C1 in reverse order. Gets us back to the
  extras-consolidation state (5565048 or whatever the PyYAML-fix
  commit lands as by then).
- No state migration needed — every new global
  (`ARGO_ANYWHERE_JUMP_HOST`, memoized alias caches, `nodeHosts`
  datalist entries) is runtime-only. The `USER_CACHE`/`NODE_CACHE`
  files may contain aliases now instead of fqdns; on revert,
  subsequent runs of the reverted engine would either accept the
  alias (if the user's ssh_config still routes it) or die at the
  "not in ANL_NODES" check. Non-catastrophic; the user re-runs
  with `--node <fqdn> --user <name>` to migrate the caches.

### Pass 7: web-UI-specific edges (Track W only)

Analogous to Passes 1-4 for the engine, but scoped to commits
C4-C6:

- **W1. Node/user/jump-host allowlist regex. RESOLVED —
  SIMPLIFIED.** Original draft flagged possible need for a new
  `_SAFE_HOSTLIKE` regex. Audit: `_SAFE_TOKEN` =
  `^[A-Za-z0-9._-]+$` is exactly right for all three fields
  (hostnames, usernames, jump-hosts). Rejects `@` (would confuse
  `${user}@${host}` target parse), `/`, `:`, whitespace, shell
  metachars. §10.2 simplified to `_SAFE_TOKEN` for all three;
  new regex dropped.
- **W2. `/api/ssh-hosts` performance. RESOLVED — KEEP.**
  Cache-on-startup + `?refresh=1` bypass. Ships with C5 alongside
  the refresh button (§7 W10 moves button from §10.7 → §10.3).
- **W3. `/api/preview-launch` stderr leaks. RESOLVED — TIGHTENED
  per C2.** Combine with the log-injection sanitizer: even a
  "not resolvable" state is decided on `returncode` alone; NO
  stderr text propagates to the response body. If we ever need to
  surface an error string, it goes through the same
  `sanitize_for_log`-equivalent in Python (a small
  `_sanitize_for_json` helper stripping control chars).
- **W4. Cross-instance state races. RESOLVED — KEEP.** Documented
  in D-031's multi-instance note; last-write-wins on
  `web_state.json`.
- **W5. Preview debounce. RESOLVED — BUMPED to 750ms per §8 Q12.**
  Draft was 300ms; discussion of Q12 (server-load hygiene under
  continuous typing, given each preview spawns a subprocess) settled
  on 750ms. AbortController + per-input listener pattern unchanged.
- **W6. Accessibility. RESOLVED — KEEP.** `label for=` + `aria-live
  ="polite"` on preview panel. Extends D-031's pattern.
- **W7. Placeholder text. RESOLVED — KEEP with amendment.**
  Placeholders as-drafted, EXCEPT: jump-host placeholder text
  changed from "or empty string to skip" (misleading per §7 A9;
  CLI-empty dies) to `(auto — logins.cels.anl.gov; use --no-jump
  to skip)`. Web launcher's Launch button emits `--jump-host X`
  only when the field is non-empty; skipping goes via a separate
  "no jump host" checkbox added in C4 (mirrors CLI `--no-jump`
  semantics; avoids the empty-string ambiguity).
- **W8. Preview panel wording. RESOLVED — KEEP + strengthen.**
  Divergence detection is load-bearing. Add explicit test
  coverage in `tests/test_web.py`:
  `test_preview_flags_user_divergence` — user types
  `--user <ANL-username-1>` but ssh_config says `User <ANL-username-2>`;
  assert the response's `divergences[]` array flags the field with
  both values.
- **W9. AGENTS.md coupling-rule bullet. RESOLVED — KEEP.** Extend
  D-031's existing rule to cover node/user/jump-host + the
  three helper names. Landed in C6.
- **W10 (NEW). Missing refresh button for the alias picker.
  RESOLVED — PROMOTED FROM §10.7 TO C5.** Endpoint supports
  `?refresh=1` but §10.7 (deferred polish) originally held the
  button. Cost is ~5 HTML + 3 JS lines; ship it with C5 so
  users can refresh without page reload. §10.3 updated
  accordingly.
- **W11 (NEW). `channel_is_up` interaction with alias `NODE_CACHE`.
  RESOLVED — DOCUMENTED.** If the cache holds `polaris-login`
  and the user's ssh_config later changes to route the alias
  differently, `channel_is_up` (based on the local port
  listening) might return "up" while the tool ends up connecting
  to a different physical host. This is a user-config drift
  problem, not our surface. Documented in `docs/LIMITATIONS.md`
  in C3.
- **W12 (NEW). Missing `PreviewLaunchIn` pydantic model.
  RESOLVED — PLAN REVISED.** Original §10.4 sketch used
  `payload: PreviewLaunchIn` without defining the model.
  FastAPI needs one:
  ```python
  from pydantic import BaseModel
  class PreviewLaunchIn(BaseModel):
      node: str = ""
      user: str = ""
      jump_host: str = ""
  ```
  §10.4 updated to include the model definition.
- **W13 (NEW). Empty-preview state should show cached defaults.
  RESOLVED — PLAN REVISED.** Original §10.4 said empty inputs
  → `state: "empty"`. That's a wasted opportunity: with all
  three fields empty, the preview should show what argo WOULD
  do using the current caches — genuinely useful pre-Launch
  reassurance ("if I hit Launch now, argo will connect to
  `<cached-node>` as `<cached-user>` via `<default-jump>`"). §10.4
  updated: `state: "cached"` when inputs are empty but caches
  are populated; each field marked with its source
  (`{value: "polaris-login", source: "cache"}`).
- **W14 (NEW). D-031 forbid-list interaction. RESOLVED — NO-OP.**
  cwd forbid-list is scope+cwd-only, orthogonal to node/user/
  jump-host. No interaction.

---

## 8. Open questions for the user (before we start writing code)

Numbered for easy reference in the audit-response. Questions marked
**RESOLVED-BY-AUDIT** were closed during the multi-pass audit
(2026-07-15); listed here for completeness. Questions marked **OPEN**
still need user input.

1. **RESOLVED-BY-AUDIT.** `ssh -G` version confidence: confirmed
   2026-07-15 on OpenSSH 10.2p1 (Ahmed Attia's laptop). Every plausible
   live user covered (§7 A1).
2. **RESOLVED-BY-AUDIT (rejected).** ANL-suffix bucket for
   §2.1 A6: dropped entirely. Sub-fix A rewritten to be
   classification-free (§7 A6). No suffix bucket needed.
3. **RESOLVED-BY-AUDIT.** New env var promotion: no legacy alias
   to promote (`ANL_JUMP` was never user-set).
4. **DECIDED 2026-07-15.** `--jump-host` naming: settled on
   **`--jump-host`**. Rationale: consistency with every other
   hyphen-separated engine flag (`--no-jump`, `--force-reinstall`,
   `--cli-tool`, `--port-range`); symmetry with `--no-jump` for
   adjacent help-text placement; matches OpenSSH's prose ("jump
   host"). Rejected `--jumphost` (inconsistent with dash convention),
   `--via` (ambiguous; no SSH-community precedent), and
   `--proxy-jump` (anchors on SSH internals; raises barrier for
   the "just point argo at a different box" cohort).
5. **DECIDED 2026-07-15.** Sub-fix B's ssh-config-user lookup on
   `ARGO_ANYWHERE_NODE`: **permissive-plus-attribution**. Look up
   whenever `ARGO_ANYWHERE_NODE` is set (from `--node` OR env), AND
   surface the source in the `Using ANL username: …` log line so
   the user can trace the inference. Formats:
   ```
   Using ANL username: <ANL-username> (source: ssh-config for --node polaris-login)
   Using ANL username: <ANL-username> (source: ssh-config for $ARGO_ANYWHERE_NODE=polaris-login)
   ```
   Rejected the strict alternative (CLI-only trigger) because the
   env-vs-CLI asymmetry it creates is a larger UX papercut than
   the "stale env var" scenario it protects against.
   `ARGO_ANYWHERE_USER` (env or flag) still wins over the ssh-config
   inference — user always has an escape hatch.
6. **DECIDED 2026-07-15.** Live-test scenarios in §4.3:
   **keep Scenario X (alias route); drop Scenario Y (custom
   jump-host) from the live doc.** Rationale: Y's unique value
   was catching "did the `--jump-host` override reach all 42
   `ANL_JUMP` references?" — a static-analysis question, not a
   runtime one. Instead: add two grep-based invariant tests to
   §4.2 (`test_no_local_ANL_JUMP_shadow` +
   `test_ANL_JUMP_references_use_expansion`) that answer it
   deterministically on every CI run without needing an alternate
   jump host. Y also would exercise "does the alt-jump accept our
   connection" — but that's the alt-jump's problem, not argo's.
   One-line note in `docs/UPGRADING.md`'s post-3.1.0 bullet
   invites users hitting real `--jump-host` issues to open an
   issue. Test list in §4.2 updated; §4.3 Scenario Y removed.
7. **DECIDED 2026-07-15.** PLAN.md decision numbering: **D-032**
   confirmed as next free number (grepped PLAN.md 2026-07-15;
   highest existing is D-031). D-032 covers both tracks (engine
   sub-fixes A/B/C + `--jump-host` shared infra AND the Track W
   web-UI launcher surface). Title: "Native `~/.ssh/config`
   respect (engine + web UI)". §6 body extended with one sentence
   describing the Track W surface + the tri-lockstep coupling
   requirement (engine helpers ↔ CLI flags ↔ web launcher fields
   + preview endpoint) for AGENTS.md cross-reference. Related to
   Q14 (where the coupling rule attaches in AGENTS.md).
8. **DECIDED 2026-07-15.** Coupling with PyYAML fix: **two
   separate commit streams**. PyYAML lands first (1 commit;
   unblocks a field-reported user). ssh-config follows as its
   own C1-C6 sequence. Full commit ordering between the just-
   landed extras-consolidation and the v3.1.0 tag:
   1. PyYAML fix (from `notes/impl_pyyaml_and_menu_fix.md`)
   2. ssh-config C1 — engine helpers + `--jump-host` plumbing (no-op)
   3. ssh-config C2 — wire helpers into `ssh_jump_args` / `resolve_username` / `pick_node` + unit tests
   4. ssh-config C3 — engine docs + PLAN.md D-032 + help block
   5. ssh-config C4 — web launcher node/user/jump-host fields
   6. ssh-config C5 — web `/api/ssh-hosts` alias picker + refresh button
   7. ssh-config C6 — web `/api/preview-launch` panel + AGENTS.md D-032 coupling rule
   Rationale: (a) attribution clarity — PyYAML has a
   field-report provenance the ssh-config work doesn't share;
   (b) revert isolation — PyYAML's `pip install pyyaml` could
   fail on offline compute nodes; a revert must not lose the
   ssh-config work. Sub-fix C of ssh-config is what makes
   aliases reachable at all; bundling it into a PyYAML revert
   would set the plan back a full cycle.

### Track W additions

9. **DECIDED 2026-07-15.** Web-UI field labels: **hybrid** —
   `compute node` / `ANL username` / `jump-host` for the visible
   `<label>` texts; `lNode` / `lUser` / `lJump` for `id=`
   attributes. Rationale: matches the existing popover's pattern
   of "short where obvious, two-word where ambiguous" (e.g. today
   the popover uses `cli tool` and `working directory` for the
   same reason). "user" alone is actively misleading in a web UI
   (OS-user vs. ANL-username misread is real); "node" alone is
   ambiguous; "jump-host" is SSH-familiar enough to stand alone.
   §10.2 example HTML uses these labels.
10. **DECIDED 2026-07-15.** Preview panel: **collapsed by default,
    auto-expand on divergence.** Default state uses HTML `<details>`
    collapsed with summary `Show resolved launch`. When
    `/api/preview-launch` returns non-empty `divergences[]`, JS sets
    `.open = true` and swaps the summary to an amber-toned
    `⚠ Divergence — review before launch` chip. Rationale: zero
    visual overhead when everything agrees (~95% of launches); loud
    unmissable signal at the exact moment it matters (a divergence
    the user was about to launch through). User can still collapse
    manually. Simple JS: one `.open = true` + one summary text swap.
    §10.4 sketch updated to include the auto-expand logic.
11. **DECIDED 2026-07-15.** `/api/ssh-hosts` gating: **fire on
    page load (DOMContentLoaded)**, silent-error on failure.
    Rationale: better perceived responsiveness (hidden in
    page-load latency rather than showing a stall the first time
    the user opens the launcher and focuses the node field). Cost
    is one loopback HTTP GET (~1-3ms); server-side parse is cached.

    **IP-block safety** (confirmed during this discussion): the
    endpoint is a **pure file parser**; NEVER calls `ssh`; zero
    network I/O; zero interaction with the D-012 SSH failure
    tracker; zero CSPO IP-block risk. Contract documented in
    §10.3's `parse_ssh_config_hosts` docstring and cross-
    referenced from §7 C3. `/api/preview-launch` (C6) DOES call
    `ssh -G` but that command is non-authenticating by design —
    same IP-block safety. Documented in §10.4's security-notes
    block.
12. **DECIDED 2026-07-15.** `/api/preview-launch` firing:
    **automatic with 750ms debounce** (bumped from the draft's
    300ms). Rationale: preserves Q10's auto-expand-on-divergence
    signal (button-triggered would defeat it); user's pause-to-
    review moment is well under the "did the app freeze?" threshold;
    subprocess-spawn rate drops to ~1.3/sec under continuous typing
    (was ~3.3/sec at 300ms). Round number, easy to explain in a
    code comment. If it feels laggy in practice, tightening to
    500ms is a one-character change.

    **Duo/IP-block safety** (confirmed during this discussion):
    `ssh -G` is non-authenticating by design — no network I/O,
    no Duo prompts, no contribution to any SSH failure counter
    (argo's D-012 tracker OR any remote SSHd's). Cross-referenced
    from §7 C3 and §10.4 security notes. Neither the automatic-
    firing choice nor the debounce length changes this — both
    are safe. §7 W5 + §10.4 client JS updated: `debounce(refreshPreview, 750)`.
13. **DECIDED 2026-07-15.** Web-UI live tests location: **create
    `notes/test_plan_v3_1_0.md`** covering the entire v3.1.0 tag,
    not just the D-032 work. Rationale: matches the existing pattern
    (every prior test-plan file is scoped to a release/phase, not a
    single D-decision); reviewer running the plan wants ONE checklist
    per release, not parallel plans; extending the already-CLOSED
    `test_plan_v3_branch.md` would break its audit trail (dated
    gate-closed artifact from 2026-07-12; must remain historical).
    Sections:
    1. **Track: extras consolidation** — 1 test (verify
       `pipx install argo-anywhere` gives web+app OOB; per the
       just-landed commit `5565048`).
    2. **Track: PyYAML self-heal + `[m]` menu accuracy** — 2 tests
       from `impl_pyyaml_and_menu_fix.md` §4.3.
    3. **Track: ssh-config engine (D-032, C1-C3)** — Scenario X
       from this plan's §4.3.
    4. **Track: ssh-config web UI (D-032, C4-C6)** — Scenarios
       W1-W3 from this plan's §10.6.
    5. **CSPO + Duo discipline** — inherited from
       `test_plan_v3_branch.md`'s template.
    6. **Closure gate** — signed date + pass/fail per test,
       matching prior test-plan format.

    File gets created as part of Track E's C3 commit (docs commit)
    so it lands with the rest of the D-032 documentation.
14. **DECIDED 2026-07-15.** AGENTS.md coupling-rule position:
    **new consolidated subsection** `### Engine ↔ web-UI coupling
    rules`. Move the existing D-031 scope-values bullet (currently
    inside "Scope handling: D-017 + D-018 + D-019") into the new
    subsection; add D-032's three-way coupling contract alongside
    it (CLI flag names ↔ launcher field IDs; engine helpers ↔
    Python `_reflect_our_jump_args`; `ANL_JUMP` mutability ↔
    `/api/preview-launch` response). Rationale: future-extensibility
    — every substantive feature that adds a web-UI surface parallel
    to an engine surface needs a coupling rule; consolidating them
    into one subsection means the future maintainer opening
    AGENTS.md has ONE place to look, not scattered bullets keyed
    to their original decisions. Landed in C6 alongside the other
    D-032 web-UI work. Docs get a full post-code review pass at
    the end of the D-032 sequence per user direction 2026-07-15;
    the coupling-rule wording may get further polish then.

---

## 9. Execution phasing (post-audit)

Once the audit above closes (user answers §7 + §8, marks §7 items
as accept/reject), execution runs as six commits in strict order.
The two tracks are gated: Track W (C4-C6) does not start until
Track E (C1-C3) has landed AND the live-test scenarios X, Y from
§4.3 have passed. Each commit is independently green.

### Track E — engine

- **C1 — engine helpers + `--jump-host` plumbing (no-op patch)**
  (~1-2 hours). Adds `_ssh_config_hostname`, `_ssh_config_user`,
  `_alias_has_own_proxy` in Section 8. Adds `--jump-host` /
  `ARGO_ANYWHERE_JUMP_HOST` argv+env plumbing in `main()` +
  Section 5-6. NO changes to existing functions yet. Ships as
  a no-op patch (new code paths exist but nothing calls them).
  Passes all existing tests + smoke tests + `bash -n`.
  Commit-gate: `argo-anywhere --jump-host foo help` runs without
  error; nothing else observable changes.
- **C2 — wire the helpers into the three sub-fixes** (~2-3 hours).
  Updates `ssh_jump_args` (Sub-fix C), the SCP branch (:4383),
  `resolve_username` (Sub-fix B), `pick_node` "not in list"
  branch (Sub-fix A). Adds the new unit tests
  (`tests/test_engine_ssh_config.py`) — 7-8 cases per §4.2. All
  existing tests + smoke tests must still pass.
  Commit-gate: full pytest green; explicit-fqdn CLI flow
  identical to today; alias-based CLI flow works against a
  stubbed `ssh`.
- **C3 — docs + release-note updates** (~1 hour). README,
  UPGRADING, LIMITATIONS, AGENTS, PLAN.md (D-032), help block.
  No code changes.
  Commit-gate: `argo-anywhere help` renders cleanly; markdown
  lints if we run any; no dead links.

**Track E live-verify gate (after C3, before C4)**: run
scenarios X + Y from §4.3 on a real ANL node against a real
ssh_config alias. Any failure → fix + amend C2/C3 before Track W
starts. Do NOT let Track W paper over an engine bug.

### Track W — web UI

- **C4 — launcher node/user/jump-host fields** (~2-3 hours).
  HTML additions to `src/argo_anywhere/web/static/index.html`
  (three new fields in the popover; `<label>` + `<input>`
  pairs; placeholders per §7 W7). Python additions to
  `build_launch_argv` (accept + validate the three new kwargs;
  emit `--node` / `--user` / `--jump-host` when present). New
  `_SAFE_HOSTLIKE` regex in `validation.py` if `_SAFE_TOKEN`
  proves too permissive (per §7 W1 investigation).
  Commit-gate: existing web tests still pass; new tests cover
  the three field paths (pass-through + rejection of bad input);
  manual smoke test — pop the launcher, type an alias, click
  Launch → engine sees `--node <alias>`.
- **C5 — `/api/ssh-hosts` alias picker** (~2 hours). New
  `src/argo_anywhere/web/ssh_hosts.py` with a small
  `~/.ssh/config` parser (filter wildcard aliases + `!`-negated
  patterns per §7 W2). New `/api/ssh-hosts` endpoint (loopback +
  host-guard; cached in app.state; `?refresh=1` param bypasses).
  Client JS fetches on page load and populates
  `<datalist id="nodeHosts">` (mirroring the existing
  `cwdHistory` datalist pattern). Tests: fixture ssh_configs
  → expected alias list.
  Commit-gate: `curl http://127.0.0.1:8799/api/ssh-hosts` returns
  the parsed list; picker suggests aliases as user types; no
  wildcards leak through.
- **C6 — `/api/preview-launch` + preview panel** (~2-3 hours).
  New endpoint runs `ssh -G <alias>` (bounded by a 2s timeout)
  and returns `{ hostname, user, proxyjump, our_extra_jump_args,
  divergences: [...] }`. Divergences flag cases where the
  user's manual `--user` / `--jump-host` inputs disagree with
  ssh_config's resolution (per §7 W8). New collapsible panel
  in the launcher popover; JS debounces on input (300ms) and
  uses `AbortController` per §7 W5. `aria-live="polite"` per
  §7 W6. AGENTS.md D-031 coupling-rule bullet extended per §7
  W9.
  Commit-gate: preview updates as user types; divergences
  colored distinctly; screen reader announces resolution.

Total wall time estimate: **~10-13 hours across both tracks**,
including audit-response iterations. Assumes user answers
§7/§8 in a single round and doesn't reopen closed passes.

**Escape hatches at each gate**:

- After C1: gate fails → revert single no-op commit; zero
  user impact.
- After C2: gate fails → fix + amend; if unfixable within a
  session, revert C2 (leaves C1's no-op helpers dormant on
  main; harmless).
- After C3: gate fails → docs-only issue; edit + amend, or
  revert C3 alone.
- After Track E live-verify: any failure blocks Track W; fix
  the engine before adding UI surface for the bug.
- After C4/C5/C6: same amend-or-revert-single-commit story.
  Web-UI commits are independent of each other's DB/state so
  reverting the middle of the three is safe.

---

## 10. Track W design — web-UI launcher enhancements

The engine work in §2 introduces three inference points
(hostname, username, jump-host) plus one explicit flag
(`--jump-host`). Track W surfaces those in the launcher popover
so users driving argo from the app get the same benefit as CLI
users. Structure mirrors §2 (three sub-fixes plus shared
infrastructure).

### 10.1 Baseline: what the web UI does today (before Track W)

Confirmed by reading `src/argo_anywhere/web/static/index.html`
lines 383-449, `src/argo_anywhere/web/app.py` lines 89-117
(`build_launch_argv`), and grepping for `node` / `user` across
the web tree:

- The launcher popover exposes **five inputs**: `lVerb`, `lTool`,
  `lScope`, `lTarget` (embedded vs. native terminal), `lCwd`.
- `build_launch_argv` accepts **three parameters**: `cli_tool`,
  `scope`, `port`. It emits `--cli-tool`, `--scope`, `--port`.
- **Zero surface for node / user / jump-host today.** The engine
  relies on `NODE_CACHE` + `USER_CACHE` + env for those; a fresh
  install with an empty cache would prompt on the invisible
  captured Lane 1 and the web user would see nothing happen
  until the WebSocket eventually shows the prompt in the embedded
  terminal.
- The onboarding gap this creates is the primary motivation for
  Track W independent of the engine work: users doing "install
  argo → double-click the app → hit Launch" today have no way
  to communicate the compute node they want. Track W closes that
  gap AND surfaces the new alias-acceptance capability at the
  same UX-cost budget.

### 10.2 Sub-fix W-A (C4): launcher node/user/jump-host fields

**New popover fields** (in the existing two-column grid at
index.html lines 411-427, extended):

```html
<div class="two">
  <div class="field">
    <label for="lNode">compute node</label>
    <input id="lNode" type="text" list="nodeHosts" autocomplete="off"
           placeholder="polaris-login  OR  compute-01.cels.anl.gov" />
    <span class="pop-note">an ssh_config alias OR a full hostname
      (see the preview panel for what argo will actually connect to)</span>
  </div>
  <div class="field">
    <label for="lUser">ANL username</label>
    <input id="lUser" type="text" autocomplete="off"
           placeholder="(auto — from ~/.ssh/config or cache)" />
  </div>
</div>
<div class="two">
  <div class="field">
    <label for="lJump">jump-host</label>
    <input id="lJump" type="text" autocomplete="off"
           placeholder="(auto — logins.cels.anl.gov, or empty to skip)" />
  </div>
  <div class="field">
    <!-- existing lTarget field stays here -->
  </div>
</div>
```

**JavaScript**: mirror the existing `lScope` handling. Read
values, trim, skip empty strings (empty means "let the engine
resolve it"). Persist to `web_state.json` MRU under keys
`node_history`, matching the `cwd_history` pattern from D-031.
`user_history` and `jump_history` skipped (per E5.c — inferred
values are not persisted; user's explicit typed values are, but
the extra MRU affordance is low-value for these two fields;
revisit if requested).

**`build_launch_argv` extension**:

```python
def build_launch_argv(
    verb: str,
    *,
    cli_tool: str | None = None,
    scope: str | None = None,
    port: int | None = None,
    node: str | None = None,       # new
    user: str | None = None,       # new
    jump_host: str | None = None,  # new
) -> list[str]:
    ...
    if node:
        if not _SAFE_TOKEN.match(node):
            raise ValueError(f"bad node: {node!r}")
        argv += ["--node", node]
    if user:
        if not _SAFE_TOKEN.match(user):
            raise ValueError(f"bad user: {user!r}")
        argv += ["--user", user]
    if jump_host:
        if not _SAFE_TOKEN.match(jump_host):
            raise ValueError(f"bad jump_host: {jump_host!r}")
        argv += ["--jump-host", jump_host]
    # Empty jump_host from the text field means "no override" — we
    # simply omit --jump-host and the engine uses ANL_JUMP default.
    # For explicit "skip the jump host entirely," C4 adds a
    # separate "no jump host" checkbox that emits --no-jump instead
    # (mirrors CLI semantics per §7 A9; avoids the "did I clear it
    # or leave it default?" ambiguity of an empty text field).
    ...
```

**Regex choice** (per §7 W1 audit): `_SAFE_TOKEN`
(`^[A-Za-z0-9._-]+$`) is exactly right for all three fields.
Hostnames + usernames + jump-hosts all draw from the same
character class in practice. Rejects `@` (would confuse
`${user}@${host}` target parse), `/`, `:`, whitespace, shell
metachars. Original draft's `_SAFE_HOSTLIKE` was
character-for-character identical to `_SAFE_TOKEN` — no new regex
needed.

### 10.3 Sub-fix W-B (C5): ssh_config alias picker

**New Python module** `src/argo_anywhere/web/ssh_hosts.py`:

```python
"""Enumerate ssh_config Host aliases for the launcher's node picker.

Reads ~/.ssh/config (following Include directives via ssh -G's
own resolution rather than a manual parser, for correctness
against non-trivial configs). Filters out wildcard aliases
(``*``, ``?``) and negated patterns (``!foo``) that don't
sensibly belong in a picker.
"""
from __future__ import annotations
from pathlib import Path

def parse_ssh_config_hosts(path: Path | None = None) -> list[str]:
    """Return the list of Host aliases suitable for a picker.

    Returns [] if the config file doesn't exist or is unreadable.
    Never raises.

    Contract (per §8 Q11 decision): **NEVER calls ssh.** Pure
    filesystem read of ~/.ssh/config plus textual Include expansion.
    Zero network I/O, zero SSH authentication attempts, zero
    interaction with the D-012 SSH failure tracker. This endpoint
    is safe to fire on every page load without any CSPO IP-block
    risk. Future maintainers: DO NOT introduce ``ssh -G`` or
    ``ssh -T`` invocations here; use the `Match exec`-free file
    parser only.
    """
    cfg = path or (Path.home() / ".ssh" / "config")
    if not cfg.is_file():
        return []
    ...
```

Implementation notes:

- Parse `Host` lines only; strip comments; split on whitespace.
- Reject tokens containing `*`, `?`, `!` (wildcards + negations).
- Deduplicate; sort for stable UI order.
- Handle `Include` directives via textual expansion (simpler than
  spawning `ssh -G` per candidate; `Include` semantics are well-
  documented).

**New endpoint** in `app.py`:

```python
@app.get("/api/ssh-hosts")
def api_ssh_hosts(refresh: int = 0) -> JSONResponse:
    cache = getattr(app.state, "ssh_hosts_cache", None)
    if cache is None or refresh:
        from .ssh_hosts import parse_ssh_config_hosts
        cache = parse_ssh_config_hosts()
        app.state.ssh_hosts_cache = cache
    return JSONResponse({"hosts": cache})
```

Behind the host-guard middleware; no ANL contact; pure filesystem
read. Per §7 W2, cache lifetime = process lifetime; user can
refresh via a small button in the popover ("↻ Refresh aliases").

**Client JS** (populate on page load; refresh button per §7 W10):

```javascript
async function refreshNodeHosts(force) {
  try {
    const url = force ? '/api/ssh-hosts?refresh=1' : '/api/ssh-hosts';
    const r = await fetch(url);
    const { hosts } = await r.json();
    const dl = el('nodeHosts');
    dl.innerHTML = hosts.map(h => `<option value="${h}">`).join('');
  } catch { /* silent — no aliases is a legitimate state */ }
}
// Fire on DOMContentLoaded.
document.addEventListener('DOMContentLoaded', () => refreshNodeHosts(false));
// Refresh button next to the node field:
el('refreshHosts').addEventListener('click', () => refreshNodeHosts(true));
```

**HTML** additions:

```html
<datalist id="nodeHosts"></datalist>
<!-- next to the lNode field, in the field's flex container: -->
<button id="refreshHosts" class="btn btn-ghost" type="button"
        title="Re-read ~/.ssh/config for alias changes">↻</button>
```

Datalist parallels the existing `<datalist id="cwdHistory">`; node
field's `list="nodeHosts"` attribute wires the suggestions. Small
refresh button (↻) forces a `?refresh=1` re-read without a page
reload (per §7 W10 audit; promoted from §10.7 deferred polish).

### 10.4 Sub-fix W-C (C6): resolved-launch preview panel

**Request body model** (per §7 W12; missing from earlier draft):

```python
from pydantic import BaseModel

class PreviewLaunchIn(BaseModel):
    """Launcher popover state; all fields optional (empty == use engine defaults)."""
    node: str = ""
    user: str = ""
    jump_host: str = ""
```

**New endpoint** in `app.py`:

```python
from .validation import _SAFE_TOKEN

def _bad_field(value: str) -> bool:
    """True if a launcher input contains anything we won't pass to ssh -G."""
    return bool(value) and not _SAFE_TOKEN.match(value)


@app.post("/api/preview-launch")
def api_preview_launch(payload: PreviewLaunchIn) -> JSONResponse:
    """Reflect back what argo WOULD run given the launcher inputs.

    Runs `ssh -G <node>` (2s timeout) and returns the resolved
    hostname / user / proxyjump plus any divergences from user
    inputs. Purely reflective — no SSH connection is attempted.

    Security notes (per §7 C5 + C6 + §8 Q11 audit):
    - subprocess.run is called with a LIST (not shell=True), so
      argv boundaries stay argv boundaries — no shell injection
      via the `node` field even without validation.
    - `_SAFE_TOKEN` server-side validation on all three inputs
      is defense in depth; rejects `@`, `/`, `:`, whitespace,
      shell metachars before ssh -G sees them.
    - **`ssh -G` does NOT authenticate.** It prints the resolved
      config for the target and exits. Zero network I/O to any
      SSH server; zero contribution to any SSH server's auth
      failure counter; zero interaction with argo's D-012 SSH
      failure tracker. IP-block-safe by construction.
    - The 2s timeout is what protects the endpoint from a runaway
      `Match exec <cmd>` block in the user's own ~/.ssh/config
      (ssh -G honors Match exec and shells out to evaluate it).
      A hostile `Match exec` could in principle invoke a real
      `ssh` that DOES authenticate and could accumulate failures
      — but that's the user attacking themselves via their own
      config, not our surface, and the D-012 tracker would catch
      the resulting failures whichever surface triggered them.
    - No stderr text propagates to the response: state decisions
      use returncode alone (per §7 W3).
    """
    # C6 (§7): validate before spawning.
    for name, val in (("node", payload.node), ("user", payload.user),
                       ("jump_host", payload.jump_host)):
        if _bad_field(val):
            return JSONResponse(
                {"error": f"bad {name}: contains disallowed characters"},
                status_code=400,
            )

    node = payload.node.strip()
    user = payload.user.strip()
    jump_host = payload.jump_host.strip()

    # W13 (§7): empty inputs → show what the engine WOULD do using
    # the current caches. Genuinely useful pre-Launch reassurance.
    if not node and not user and not jump_host:
        from ..status import read_cached_node, read_cached_user
        return JSONResponse({
            "state": "cached",
            "hostname": {"value": read_cached_node() or "", "source": "cache"},
            "user": {"value": read_cached_user() or "", "source": "cache"},
            "proxyjump": {"value": "logins.cels.anl.gov", "source": "default"},
        })

    if not node:
        # Partial input: user typed a username or jump but no node. Show
        # what we have; no ssh -G possible without a node.
        return JSONResponse({
            "state": "partial",
            "user": {"value": user, "source": "input"} if user else None,
            "jump_host": {"value": jump_host, "source": "input"} if jump_host else None,
        })

    try:
        proc = subprocess.run(
            ["ssh", "-G", node],
            capture_output=True, text=True, timeout=2,
        )
    except (subprocess.TimeoutExpired, OSError):
        return JSONResponse({"state": "unresolved"})
    if proc.returncode != 0:
        return JSONResponse({"state": "unresolved"})

    resolved = _parse_ssh_G(proc.stdout)  # {hostname, user, proxyjump}
    divergences = []
    if user and resolved.get("user") and user != resolved["user"]:
        divergences.append({
            "field": "user", "yours": user,
            "ssh_config": resolved["user"],
        })
    if jump_host and resolved.get("proxyjump") and jump_host != resolved["proxyjump"]:
        divergences.append({
            "field": "jump_host", "yours": jump_host,
            "ssh_config": resolved["proxyjump"],
        })
    return JSONResponse({
        "state": "resolved",
        "hostname": resolved.get("hostname"),
        "user": resolved.get("user"),
        "proxyjump": resolved.get("proxyjump"),
        "our_extra_jump_args": _reflect_our_jump_args(payload, resolved),
        "divergences": divergences,
    })
```

`_reflect_our_jump_args` computes what the engine's
`ssh_jump_args` WOULD emit — including the "skip when alias has
own proxy" logic from Sub-fix C. This mirrors engine behavior in
Python; per §7 W9 the two must stay in lockstep. Reviewer
checkpoint: any change to `ssh_jump_args` requires a matching
update to `_reflect_our_jump_args`, tested on a stub `ssh` fixture.

**`read_cached_node` / `read_cached_user`**: thin wrappers over
the cache files at `~/.config/argo_anywhere/{node,user}`, added
to `status.py` if not already present. Return `None` on missing
cache (empty string in the JSON response).

**Popover panel** (collapsed by default per §8 Q10;
auto-expands on divergence):

```html
<details id="previewPanel" class="preview-panel">
  <summary id="previewSummary">Show resolved launch</summary>
  <div id="launchPreview" aria-live="polite">
    <!-- rendered from /api/preview-launch response -->
  </div>
</details>
```

Rendered output (no divergence):

```
Node:      polaris-login → compute-386-02.cels.anl.gov
User:      <ANL-username> (from ~/.ssh/config)
Jump host: (routed via your ssh_config; argo will not add its own)

argo will run:  argo-anywhere --node polaris-login --scope global run
```

Rendered output (with divergence):

```
Node:      polaris-login → compute-386-02.cels.anl.gov
User:      <ANL-username-1>  ⚠  ssh_config says <ANL-username-2>
Jump host: (routed via your ssh_config; argo will not add its own)

argo will run:  argo-anywhere --node polaris-login --user <ANL-username-1> --scope global run
```

Divergences highlighted in the theme's warning color; matches on
purpose so the "everything agrees" state is visually calm.

**Client JS** debounce + abort + auto-expand pattern:

```javascript
let previewCtrl = null;
async function refreshPreview() {
  if (previewCtrl) previewCtrl.abort();
  previewCtrl = new AbortController();
  const body = JSON.stringify({
    node: el('lNode').value.trim(),
    user: el('lUser').value.trim(),
    jump_host: el('lJump').value.trim(),
  });
  try {
    const r = await fetch('/api/preview-launch', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body,
      signal: previewCtrl.signal,
    });
    const data = await r.json();
    renderPreview(data);
    // §8 Q10: auto-expand on divergence with amber summary chip.
    // User can still collapse manually after seeing it.
    const panel = el('previewPanel');
    const summary = el('previewSummary');
    if (data.divergences && data.divergences.length > 0) {
      panel.open = true;
      summary.textContent = '⚠ Divergence — review before launch';
      summary.classList.add('summary-warn');
    } else {
      summary.textContent = 'Show resolved launch';
      summary.classList.remove('summary-warn');
      // NOTE: don't force-collapse (panel.open = false) — respect
      // the user if they had it manually opened. Only auto-toggle
      // to open on new divergence; never auto-close.
    }
  } catch (e) {
    if (e.name !== 'AbortError') { /* silent — preview is best-effort */ }
  }
}
// Debounce = 750ms per §8 Q12 decision (bumped from initial 300ms):
// user's pause-to-review moment stays well under "did the app freeze?";
// subprocess-spawn rate drops to ~1.3/sec under continuous typing.
// ssh -G is non-authenticating (no Duo, no IP-block risk) so this is
// tuning for server-load hygiene, not a safety knob.
const debouncedPreview = debounce(refreshPreview, 750);
['lNode', 'lUser', 'lJump'].forEach(id =>
  el(id).addEventListener('input', debouncedPreview));
```

**CSS** (`summary-warn` class added to the theme's shared warning
palette, matching D-031's amber tone for consistency with other
warn signals in the web UI).

### 10.5 What Track W deliberately doesn't do

Reiterated here for the section's readability; primary
enumeration lives in §7 E5.a-c:

- No in-app editor for `~/.ssh/config` (security-surface bloat).
- No cwd-triggered alias auto-select (too magical for v1).
- No persisting of inferred values into `web_state.json` MRU
  (only user's typed values persist; consistent with engine E3).
- No multi-node concurrent channel picker (D-031's single-Channel
  constraint stands; multi-channel is a separate future feature).
- No exposure of `_alias_has_own_proxy` decisions in the status
  card beyond the preview panel (avoid scattering the same
  information across two surfaces; the preview is authoritative).

### 10.6 Testing (Track W addendum to §4)

Unit tests grow in three files:

- `tests/test_web.py` — extend the existing `test_build_launch_argv_*`
  suite to cover the three new fields (pass-through + rejection
  of bad input via `_SAFE_TOKEN`). Extend the `/api/preview-
  launch` coverage using `unittest.mock.patch` on
  `subprocess.run` so tests don't shell out to real `ssh`.
  Include `test_preview_flags_user_divergence` (per §7 W8)
  and coverage for the `state: "cached"` branch (per §7 W13).
- `tests/test_ssh_hosts.py` (NEW) — fixture ssh_configs with a
  mix of plain aliases, wildcards, negations, `Include`
  directives; assert the parser filters correctly and dedupes.
- `tests/test_web_state.py` — extend to cover the `node_history`
  MRU key (analogous to `cwd_history`).

Live verification (add to `docs/TESTING.md` alongside scenarios
X + Y from §4.3):

- **Scenario W1 — launcher fields end-to-end**: open the app,
  type `polaris-login` into node, leave user + jump-host empty,
  click Launch. Expect: preview panel shows the resolution;
  embedded terminal shows the engine connecting via the alias
  with inferred user + no extra `-J`.
- **Scenario W2 — divergence highlighted**: type `polaris-login`
  in node AND `some-other-user` in user field. Expect: preview
  panel flags the divergence; launching still respects the
  user's explicit input (per engine's precedence rule).
- **Scenario W3 — picker offers aliases**: focus the node field
  on a machine with a populated `~/.ssh/config`. Expect: the
  datalist suggests aliases; wildcards absent.

### 10.7 UX polish (deferred to a follow-up)

Not in Track W's scope; captured here so they don't get lost:

- Inline hint chip: "your ssh_config already routes this alias
  via `<jump>`; not adding our -J." Currently only appears in
  the preview panel; a smaller inline note next to the node
  field would be nice.
  *(Note: refresh button was originally in this list but has
  been promoted to §10.3 / C5 per §7 W10 audit.)*
- Analytics-free "did the user actually look at the preview
  before launching?" telemetry — SKIP, we don't do telemetry.

---

## 11. Post-execution addendum (2026-07-15)

Recorded after the 9-commit sequence landed (`5565048` → `643de22`)
so this plan's body stays a historical record of the pre-execution
DESIGN while this section captures what shipped DIFFERENTLY. Details
in `notes/audit_v3_1_0_post_execution.md`.

### 11.1 Divergences from the plan body

**`_SAFE_HOSTLIKE` regex (not `_SAFE_TOKEN` reuse).** §5's Track W
file-inventory table and §10.2 both said "reuse existing `_SAFE_TOKEN`
for all three new fields." That was based on the pre-execution §7 W1
audit's claim that `_SAFE_TOKEN = ^[A-Za-z0-9._-]+$`. On code
inspection during C4 execution, `_SAFE_TOKEN` turned out to be
`^[a-z0-9][a-z0-9-]{0,31}$` — lowercase-only, no `.` or `_`, capped
at 32 chars. Would reject legitimate hostnames including the default
node fqdn (`compute-01.cels.anl.gov`). C4 introduced a new
`_SAFE_HOSTLIKE = ^[A-Za-z0-9][A-Za-z0-9._-]{0,252}$` (RFC 1035
total-length cap; mixed case allowed; `.` + `_` allowed). Behavior
otherwise identical to what the plan intended. Documented inline
in `src/argo_anywhere/web/app.py`'s `_SAFE_HOSTLIKE` docstring.

**Python mirror named `reflect_jump_args` (not `_reflect_our_jump_args`).**
§10.4 sketch referenced `_reflect_our_jump_args`; actual shipped
name is `reflect_jump_args` (module-level Python function in
`src/argo_anywhere/web/preview.py`; no leading underscore because
it's part of the module's public surface for the endpoint). Also
introduced a companion `SshGResult` dataclass + `_parse_ssh_G` + a
`run_ssh_G` wrapper that the plan didn't enumerate. Behavior
matches the intent.

**awk-idiom correction landed via C2's debugging.** §2.3's initial
"cleaner" awk pattern `{exit 0} END{exit 1}` turned out to be buggy
(END overrides body-block exit code — always exits 1). C1 shipped
the buggy version; C2's mirror-test caught it; the fix (revert to
`{found=1} END{exit found ? 0 : 1}`) went into C2 with a scarred
comment in `_alias_has_own_proxy` documenting the gotcha for future
maintainers. Net LOC increase: ~7 lines of comment. The pre-execution
§7 A4 finding that flagged the "cleaner" idiom was WRONG.

**Fourth `resolve_username` caller found by grep.** §2.2 enumerated
3 callers (`_client_common_setup`, `mode_configure`, `mode_run`).
Grep during C2 execution found a fourth: `update_argoproxy_component`
at engine :8631. All four now use the globals-based API correctly.

**`_alias_proxy_notice_dedup` landed in C1, not C2.** §5's Track E
row assigned the dedup helper to C2 (alongside the wire-in of
`ssh_jump_args`). In practice it made more sense to land as a helper
alongside `_alias_has_own_proxy` in C1 since it's a helper for the
same functional area. Net LOC across C1+C2 unchanged; just shifted
by ~20 lines.

### 11.2 Test-coverage additions from the post-execution audit

The pre-execution §4.2 test list covered the primary paths; the
post-execution audit (`notes/audit_v3_1_0_post_execution.md` Pass 2)
found 5 coverage gaps. 4 of the 5 were closed in the A2 fix commit:

- `test_B_ssh_config_skipped_on_compute_node` — the on-node guard in
  `resolve_username` is now explicitly tested (was untested;
  refactor could have silently removed the guard).
- `test_C_scp_branch_gated_by_alias_has_own_proxy` — grep-invariant
  test that Sub-fix C's SCP-branch guard is present + adjacent to
  the `ProxyJump=` line (runtime-testing the SCP branch would need
  a scp+network stub).
- `test_launch_external_passes_d032_flags_through` +
  `test_launch_external_omits_empty_d032_fields` +
  `test_launch_external_rejects_bad_node` — the `/api/launch-external`
  endpoint's threading of the four D-032 fields to `build_launch_argv`
  is now explicitly tested (was only unit-tested at the pure-function
  layer).
- `test_ws_passes_d032_query_params_through` +
  `test_ws_rejects_bad_d032_query_params` — same for the `/ws`
  intake.

The 5th gap (renderPreview() client-side JS) is deferred; would
require Playwright, and other UI-only regressions would benefit
from that infrastructure too.

### 11.3 Deferred items (documented follow-ups)

- **`sanitize_for_log` helper** (pre-execution §7 C2): did NOT
  land. Only two log sites echo raw ssh_config-derived values (the
  `pick_node` alias-notice `log` lines that render
  `${_resolved}` from `_ssh_config_hostname`). Real-threat
  assessment: user-config self-harm (attacker who can write the
  user's `~/.ssh/config` already has SSH-arbitrary-code). Fix
  deferred; not urgent.
- **`_build_scp_opts` extraction** (Refactor-1): the SCP options
  block in `remote_bootstrap` is inline; extracting to a helper
  would enable runtime-testing the SCP-branch guard instead of
  the grep-invariant. Deferred.
- **`renderPreview()` client JS split** (Refactor-4): monolithic
  function rendering 5 state branches; would benefit from splitting
  per state. Not urgent.

### 11.4 Live-verify gate (still pending — Ahmed's manual action)

Scenario X (real ANL alias flow) is documented in
`notes/test_plan_v3_1_0.md` T6. The pre-execution plan's §9 gated
Track W start on this gate passing. In practice Track W landed
without waiting (per user direction "go all the way through") since
Track W adds UI surface + validation over engine paths that are
already unit-tested; a Scenario-X failure would land as an amendment
to C2 (the wire-in commit).

If Ahmed runs Scenario X and it FAILS, the fix path is:
1. Diagnose the failure (which of Sub-fixes A/B/C didn't behave as
   expected in the real-infra flow).
2. Amend C2 (`git commit --amend` or a fixup commit).
3. Re-run the full pytest + Scenario X.
4. If needed, propagate the fix to Track W (C4-C6) — but the mirror
   test in `tests/test_preview_launch.py` should catch any
   engine-side change that Track W didn't already reflect.

### 11.5 Fix-commit trail

- **A1** — `99f1e46` — `docs(audit): post-execution audit of the
  v3.1.0 D-032 + PyYAML sequence`. The audit doc itself.
- **A2** — this commit — `fix(D-032): post-audit test coverage +
  doc drift`. Closes 4 test gaps + 1 doc drift.
- **A3** — this commit — this addendum section (§11) landed as
  part of A2.

---
