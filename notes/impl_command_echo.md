# Implementation plan -- command echo (`--show-commands`)

**Status**: designing (no code committed).
**Owner**: Ahmed Attia. **Last updated**: 2026-07-16.
**Target repo**: <https://github.com/a-attia/argo-anywhere>.
**Linked PLAN.md sections**: none yet — this note precedes the design
decision. If it ships, it earns a **D-036** entry in PLAN.md.
*(Renumbered 2026-08-12: this note claimed D-033, which was already
taken by the shipped ControlPersist decision of 2026-07-22. D-034 went
to the shared-node transport work and D-035 is reserved for
[`impl_channel_persistence.md`](impl_channel_persistence.md); D-036 is
the next free number.)*

## Purpose

Print the fully-composed `ssh` / `scp` command before argo-anywhere
executes it, so a user can see what the tool will actually run against
their infrastructure instead of inferring it from log prose.

## Motivation

The A7 bug (fixed in `ff89d8e`, 2026-07-16) is the existence proof.
D-032's `_ssh_config_user` resolved the maintainer's laptop username
instead of their Argonne username, so `connect` SSHed to the wrong
account, publickey auth failed, and sshd fell back to a password
prompt. The user's report was "the login procedure now requires my
password after Duo is accepted" — a symptom two full inference steps
away from the cause.

The engine was not silent about it. `_client_common_setup` already
logs:

```text
[argo-anywhere] Using ANL username: attia (source: ssh-config:logins.cels.anl.gov)
```

That line names the culprit *and* its provenance, and it still did not
land — a bare username is easy to skim past, and `source:` attribution
only means something to a reader who already suspects the username.
Compare what a command echo would have shown:

```text
[argo-anywhere] + ssh -J attia@logins.cels.anl.gov attia@compute-01 ...
```

A user who knows they are `aattia` cannot misread that. The value here
is not "more logging" — it is **putting the resolved identity next to
the thing it affects**, in the exact syntax the user already knows how
to debug and paste into their own terminal.

This is a debuggability feature, not a fix. It would not have prevented
A7; it would have collapsed the diagnosis from a bug report into a
glance.

## Public API surface

One flag plus its env twin, matching the D-019 namespace convention:

| Surface | Meaning |
|:--|:--|
| `--show-commands` | Echo each composed `ssh`/`scp` argv before running it. |
| `ARGO_ANYWHERE_SHOW_COMMANDS=1` | Env equivalent (flag wins, per the D-032 precedence pattern). |

Deliberately **not** proposed:

- **A `connect --dry-run`.** `clean` and `uninstall` own `--dry-run`
  today (`CLEAN_DRY_RUN`), where it means "enumerate what I would
  delete." Reusing the spelling for "print the ssh command and exit"
  overloads it with a second, unrelated meaning. If a preview-and-exit
  mode is ever wanted, it needs its own name.
- **Echo-on-by-default.** See Trade-offs.

## Dependencies

None new. The feature is internal to the engine; no upstream tool,
no new binary, no Python-layer change.

## Design

### The chokepoint that isn't

The obvious implementation — echo from inside `ssh_args` — is **wrong,
and wrong in a way that silently corrupts every SSH invocation**.

`ssh_args` (engine `argo-anywhere.sh:2341`) does not *run* ssh. It
composes and prints an argv fragment, and all 12 call sites consume it
via command substitution:

```bash
ssh $(ssh_args "$user" "$host") "${user}@${host}" true
```

Its **stdout is the argv**. A `log` call inside it does not produce a
log line; it produces extra words in the ssh command line. This is the
same subshell trap that the A5 amendment (`e720d71`) hit from the other
direction: the `_alias_proxy_notice_dedup` sentinel could never
propagate out of the `$()` subshell, and the fix was to move the notice
to `_announce_alias_routing_once` in the parent shell. Section 8's
comment block records the lesson; an implementer who skips it will
rediscover it as mangled ssh argv.

So there is no single chokepoint. The composition is centralized; the
**invocation is not**. Current sites (`main` @ `8f0bb2f`):

- 12 `$(ssh_args ...)` sites: `2367`, `2372`, `2409`, `4451`, `4782`,
  `4958`, `5195`, `5200`, `5523`, `5572`, `8795`, `10267`.
- 1 `scp` site: `4757` (uses a `scp_opts` array, not `ssh_args`).

They are not uniform: some capture stdout via `$()`
(`5523`, `5572`), some are tested for exit status inside `if`
(`2409`, `4451`, `5195`), some pipe a heredoc on stdin
(`4782` remote bootstrap), and `5195` is an `ssh -O check` control
command rather than a real connection.

### Option A — `_run_ssh` wrapper (rejected for a first cut)

Introduce `_run_ssh <user> <host> [--] <cmd...>` that composes, echoes,
and invokes; migrate all 13 sites.

Clean end state, but it is a 13-site refactor across exactly the code
paths that have historically broken in subtle ways, and the sites'
shapes differ enough (captured stdout, tested exit status, heredoc
stdin, `-O check`) that one wrapper signature will not fit all of them
without options that reintroduce the complexity. AGENTS.md's D-005
"audit main-mode functions" rule applies with force here: these call
sites' contracts with `set -euo pipefail` are load-bearing and
under-tested (the engine is live-verify-only). High blast radius for a
debuggability feature.

Revisit if a second reason to wrap SSH ever appears (per-call timing,
retry, structured logging). One reason is not enough.

### Option B — targeted echo at the sites that matter (recommended)

Add a helper next to `ssh_args`:

```bash
# _echo_ssh_cmd <label> <argv...>: emit the composed command when
# --show-commands is on. Called from the PARENT shell at a call site --
# never from inside ssh_args (whose stdout IS the argv).
_echo_ssh_cmd() {
  [ "${ARGO_ANYWHERE_SHOW_COMMANDS:-0}" = 1 ] || return 0
  local label="$1"; shift
  log "+ ${label}: $*"
}
```

Call it at the four sites a user actually debugs, not all 13:

| Site | Why it earns an echo |
|:--|:--|
| `ssh_preflight` (`2409`) | First real contact; where a wrong identity surfaces. |
| `ssh_mux_open` (`4451`) | Opens the master; owns the Duo prompt. |
| scp bootstrap (`4757`) | Copies the engine; distinct argv shape (`scp_opts`). |
| `remote_bootstrap` (`4782`) | Runs the server; carries env on the command line. |

The remaining sites are health checks and control commands that reuse
the master and tell a debugging user nothing new.

Cost is four call-site edits plus one helper. No refactor, no change to
any existing contract, and each edit is independently revertible.

### Redaction

**Open question, and the reason this is not a 20-minute change.**

For Claude Code, argo-proxy accepts the ANL username *as* the bearer
token (`ANTHROPIC_API_KEY` is set to the username — see
`write_claudecode_config` and `docs/SECURITY.md`). So the "secret" and
the identity are the same string, and that string is already printed
verbatim by the existing `Using ANL username:` line and by the README
screenshots' `Authorization: Bearer <ANL-username>`. An echo of
`ssh aattia@compute-01` therefore leaks nothing the engine does not
already print.

That reasoning holds *today*, for the argv shapes above. It is exactly
the kind of premise that stops holding quietly: `remote_bootstrap`
(`4782`) already passes env on the command line, and any future site
that carries a real credential would be echoed by a feature whose
author reasoned "the token is just the username." Before this ships,
the helper needs either a redaction pass over known-sensitive tokens or
an explicit, tested invariant that no echoed site ever carries one.
Prefer the invariant — it is greppable, and a grep-based test can
enforce it the way `test_module_source_never_calls_ssh` enforces the
IP-block contract.

## Trade-offs considered

**Why not on by default?** The composed argv is long
(`ControlMaster`/`ControlPath`/`ControlPersist`/`-J`/`-o` options), and
printing it on every run buys noise for the 99% of runs that work. The
A7 case is a *diagnosis* tool. Opt-in also sidesteps the redaction
question for default users. Counter-argument worth weighing: a feature
users must know to enable is a feature they will not have enabled at
the moment they need it, which is the moment the bug bites. A middle
path — echo automatically on the *retry* after an SSH failure, where
the failure tracker (D-012) already fires — would put the command in
front of the user exactly when it matters, with no flag and no noise.
That is arguably the better design and should be decided before code.

**Why `+ ` as the prefix?** Matches `set -x` convention, which readers
already parse as "this is the command being run."

**Why not `set -x` itself?** It dumps every internal command, including
the awk/`ssh -G` helpers, and would bury the four lines that matter.

## Testing plan

The engine is live-verify-only (AGENTS.md override), but this feature
is unusually testable without ANL infra, because the assertion is about
*string composition*, not connection behavior:

1. **Unit (pytest, no infra)**: with `ARGO_ANYWHERE_SHOW_COMMANDS=1`
   and the existing `_write_ssh_G_shim` stub on PATH, source the engine
   and assert `_echo_ssh_cmd` emits the expected argv and is silent when
   the flag is off. Extends `tests/test_engine_ssh_config.py`'s pattern.
2. **Grep invariant**: assert no `log`/`printf` to stdout is ever added
   inside `ssh_args` — the A5 trap, protected the way
   `test_no_local_ANL_JUMP_shadow` protects the `ANL_JUMP` contract.
   This is the highest-value test in the plan: it pins the one mistake
   an implementer is most likely to make.
3. **Redaction invariant** (gates "shipped"): assert every echoed site's
   argv is free of known-sensitive tokens, per the Redaction section.
4. **Live**: one `connect --show-commands` run; confirm the echoed
   command is copy-pasteable and reproduces the same result by hand.

## Risks

| Risk | Mitigation |
|:--|:--|
| Echo added inside `ssh_args`, corrupting argv | Grep invariant (test 2) + the Section 8 comment block. |
| A future echoed site carries a real credential | Redaction invariant (test 3) before shipping. |
| Scope creep into Option A's refactor | Four sites, one helper. If a fifth site is wanted, re-read the Option A rejection. |
| Echo drifts from what is actually run | Only echo argv already composed at that site; never recompose for display. Recomposition is how the web UI's `reflect_jump_args` mirror earns its byte-equivalence test — do not repeat that coupling here. |

## Action items

1. Decide the on-by-default question (opt-in flag vs. auto-echo on SSH
   retry) — **pending** — Ahmed. Blocks everything below.
2. Resolve redaction (invariant vs. redaction pass) — **pending** — Ahmed.
3. Add `_echo_ssh_cmd` + the four call sites — **pending**.
4. Add tests 1-3 — **pending**.
5. Record as D-036 in PLAN.md; add `--show-commands` to engine help +
   `ARGO_ANYWHERE_SHOW_COMMANDS` to the AGENTS.md env-var list —
   **pending**.
6. Live-verify (test 4) — **pending** — Ahmed (requires ANL infra).

---

*Created 2026-07-16 by Ahmed Attia (with AI assistance from Claude per
[`CONTRIBUTORS.md`](../CONTRIBUTORS.md)). Motivated by the A7
wrong-username bug (`ff89d8e`); see the commit body for the full
root-cause analysis.*
