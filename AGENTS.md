# AGENTS.md

Maintainer / contributor notes for `argo_anywhere.sh`. The user-facing
documentation is `README.md` and the script's own `help` subcommand. This
file is the *behind-the-scenes* guide: invariants, gotchas, design rationale,
and the historical bugs we'd rather not repeat.

## What this repo is

A single-purpose repo around one substantial bash script and its supporting
docs and config examples:

- `argo_anywhere.sh` — end-to-end orchestrator that lets Argonne users run
  [OpenCode](https://opencode.ai/) on their laptop against
  [argo-proxy](https://github.com/Oaklight/argo-proxy) on an ANL compute
  node, regardless of whether the laptop is on the ANL network or not.
- `README.md` — user-facing entry point. Quick start, subcommands table,
  prerequisites, common operations.
- `docs/TESTING.md` — live-verification guide for the `client` end-to-end
  path. Use after non-trivial edits or before tagging a release.
- `examples/` — sanitized templates for the two configs the script writes
  (laptop OpenCode config + compute-node argo-proxy config).
- `AGENTS.md` (this file) — maintainer notes.

There is **no** package layout, `requirements.txt`, `pyproject.toml`, test
scaffolding, or CI. The script is deliberately a single self-contained file
that users `curl` and run.

## `argo_anywhere.sh` — what to know before editing

The script is ~3000 lines of **bash** (not POSIX `sh`). Its first executable
lines re-exec under `bash` if invoked through any other shell, which catches
the macOS-specific gotcha where `/bin/sh` is bash with `POSIXLY_CORRECT=y`.
The `help` subcommand prints the full user guide; this section is the
maintainer-side complement.

Distribution: published at <https://github.com/a-attia/argo-opencode>.
Users `curl` either `main` or a pinned release tag (e.g. `v1.0.0`); both
URLs are documented in `README.md` and the script's own header.

### Subcommands

`client` (default), `setup`, `tunnel`, `server`, `status`, `stop`,
`update-models`, `clean`, `help`.

- `client` is the all-in-one workflow: SSH tunnel + chosen-client install +
  config write + monitor. `scp`s the file to a chosen compute node and
  re-execs it as `server` over SSH. The "chosen client" is determined by
  the script's invocation name (`argo_opencode.sh` → OpenCode,
  `argo_claudecode.sh` → Claude Code, `argo_anywhere.sh` → interactive
  picker), with `CLIENT_OVERRIDE` env / the `setup` subcommand as
  overrides.
- `setup` is a thin alias for `client` that ALWAYS shows the interactive
  client picker, regardless of invocation name. Useful when the user
  wants a non-default client without renaming the file.
- `tunnel` is `client` minus the per-client install/config: open the SSH
  forward (or local proxy on a compute node) and block in the foreground
  monitor loop. Useful for power users managing their own client
  configurations or for keeping a tunnel alive while configuring multiple
  clients in other terminals.
- `server` runs argo-proxy locally. Auto-invoked by `client` over SSH on
  the picked compute node, but also a documented standalone workflow
  ("leave a proxy on this node for any client to reach"). Resolves
  identity from env, then `~/.config/argoproxy/config.yaml`, then cache;
  prompts for confirmation when no env was supplied (skip with `-y`).

### MFA-aware by default

ANL CELS hosts use Duo. The script uses SSH `ControlMaster` connection
multiplexing so Duo prompts only fire once per session. Sockets land in
`~/.ssh/sockets/argo-opencode-<user>-<host>-<port>` (literal `%r-%h-%p`
tokens, not the `%C` hash — `%C` proved fragile when `~/.ssh/config` rewrites
jump-host names, producing two different socket paths for what was logically
the same connection). Disable MFA mode for non-Duo hosts with `--no-mfa`.

### Jump-host shell restriction

`logins.cels.anl.gov` is jump-only — its login shell rejects all command
execution ("This account is currently not available"). The script therefore
opens the multiplex master against the picked compute NODE, not the jump
host. `mode_client` reorders pick-node before preflight under MFA.
**Do not** try to `ssh -O ... <user>@logins.cels.anl.gov true` — it always
fails.

### Mux master holds tunnels alive

Under `ControlMaster=auto`, a foreground `ssh -N -L` may exit immediately
after the forward request is acknowledged by the master; the master then
owns the forward. Health checks must verify `/health`, not just the
foreground pid. `open_tunnel_and_monitor` handles this: if the foreground
ssh dies but `/health` still answers, declare success and let the master own
the forward. The monitor and parent wait-loop both handle empty
`SSH_TUNNEL_PID`.

### Port policy

The OpenCode config's `baseURL` is the source of truth. `--port N` and
`ARGO_ANYWHERE_PORT` are one-shot overrides; if they disagree with the
config, `mode_client` asks `[m]igrate / [u]se-once / [k]eep / [a]bort`.
Non-client subcommands warn on mismatch but don't prompt.

### Server-side port + config validation

After `handle_config_file` for `~/.config/argoproxy/config.yaml`,
`mode_server` reads back the `port:` line and refuses to launch argo-proxy
if it disagrees with `$PROXY_PORT` (else argo-proxy binds the wrong port and
the client polls in vain). The same writer also preserves unknown YAML keys
via a Python+PyYAML merge: only `config_version`, `user`, `host`, `port` are
owned by the script; everything else (`argo_url`, `argo_embedding_url`,
`concurrent_downloads`, etc.) survives a `[b]ackup+overwrite` choice.

### Server-mode logging trick

The early `bash "$0" server | tee -a $LOG; exit ${PIPESTATUS[0]}` pattern
must **not** be prefixed with `exec` — `exec CMD | tee` only `exec`s the
left side, the rest of `mode_server` then runs a second time, double-
bootstrapping. Old code had `exec` and the duplicate-bootstrap bug bit
users until it was fixed.

### Env vars are namespaced

Canonical names:
- `ARGO_ANYWHERE_USER`
- `ARGO_ANYWHERE_NODE`
- `ARGO_ANYWHERE_PORT`
- `ARGO_ANYWHERE_NO_JUMP`
- `ARGO_ANYWHERE_NO_MFA`
- `ARGO_ANYWHERE_FORCE_REINSTALL`
- `ARGO_ANYWHERE_SHOW_MODELS`
- `ARGO_ANYWHERE_CONTROL_PERSIST`
- `ARGO_BOX_STYLE`

Two generations of legacy names still work with a one-time deprecation
warning each (snapshotted **before** the script's own config block
reassigns them, so promotion sees the inherited values):

- Pre-namespace (oldest): `ANL_USERNAME`, `PROXY_PORT`, `SHOW_MODELS`.
- Pre-rename (v1.1.0 era; argo_opencode.sh): every `ARGO_OPENCODE_<X>`
  is still honored as a legacy alias of `ARGO_ANYWHERE_<X>`. Users with
  `export ARGO_OPENCODE_USER=...` in their shell rc files see one WARN
  per stale var on the first run after upgrade; the script otherwise
  behaves identically.

The Argonne username is distinct from the laptop's `$USER` — never
substitute one for the other. The writers always read `ARGO_ANYWHERE_USER`
(with `ANL_USERNAME` as legacy fallback). `mode_server`'s pid-owner check
uses `id -un` (OS-level, correct) but the config-user check uses
`ARGO_ANYWHERE_USER` (Argonne-level, correct).

### `set -euo pipefail` is on

Avoid `[ test ] && cmd` at function/branch top level. When the test fails,
`set -e` doesn't kill (the man page exempts `&&`/`||` chains), but bash 3.2
(macOS default) has parser quirks with quoted heredocs inside `$()` under
`set -u` that have bitten this script before.

Use `if/then/fi` and write multi-line remote scripts via temp files
(`mktemp` + `ssh ... < file`), **never** `var="$(cat <<'EOS' ... EOS)"`.

### Audit "main-mode" functions before calling them in-process

A recurring class of bug surfaced three times in one session. Each had
the same shape: a function that was originally written as the script's
**main mode** (i.e. "the script's job IS to run this function and
exit") was later refactored to ALSO be callable as one step of a
longer in-process flow. The function's main-mode-only assumptions
silently broke the in-process caller.

Concrete instances we hit (commits `df10abe`, `ed71864`, `32601c3`):

- **`$()` capture of a function that mutates globals.** Command
  substitution runs the function in a subshell where mutations to
  script-level globals (`ANL_USERNAME`, `ARGO_ANYWHERE_USER`,
  `PROXY_PORT`, env-var auto-defaults, etc.) evaporate when the
  subshell exits. The parent then sees the global as unbound and
  trips `set -u`. Fix: don't capture; use a designated `_RETURN_*`
  global to convey the "return value."

- **`exit` inside a function that may now be called in-process.**
  `mode_server`'s tee-then-exit pattern was correct when `mode_server`
  was the only thing the script did (invoked over SSH from the
  laptop). It became wrong when `_client_common_setup`'s on-node
  short-circuit started invoking `mode_server` as one step of a
  longer flow. Fix: gate the `exit` on a "called in-process" flag
  and `return` the same status code in the in-process branch.

- **Assumptions about shell state outside the script.** OpenCode's
  Linux installer drops the binary at `~/.opencode/bin/` and adds
  `PATH=~/.opencode/bin:$PATH` to `~/.bashrc`. The post-install
  `command -v opencode` correctly returned non-zero because the
  running script's PATH didn't include the new directory; the
  user's *next* shell would have it but ours doesn't. Fix:
  prepend the well-known install location to PATH for the rest of
  the script invocation if the binary is there, so subsequent steps
  in the SAME script can use it.

The meta-rule for future refactors: **when a function that was
originally a "main mode" gets called in-process from somewhere else,
audit it for `exit`, `exec`, `$()` capture by callers, and any
implicit assumption that "the user's next shell" or "the next process"
will pick up state changes we made.** None of these survive an
in-process call. The fix usually involves either (a) adding a flag
like `_FOO_INPROC=1` that the function checks before exiting, or
(b) factoring the function into "do the work" + "wrap with the
main-mode-only behavior."

### Targets bash 3.2+

macOS default. No bash-4 features (no `${var,,}`, no `mapfile`, no
`declare -A`, no `printf -v` with format reuse, etc.).

### Language policy: bash + inline Python heredocs

The script is bash. When bash is genuinely awkward for a piece of work
(JSON/YAML/TOML config writing, deep-merging across scopes, anything
non-trivial with structured data), the standard tool is a Python heredoc
invoked from bash, *not* a separate `.py` file.

The reference example is `write_argoproxy_config` (around line 1390): bash
builds the surrounding flow, a `python3 - <<'PYEOF' ... PYEOF` invocation
handles the YAML merge, args cross the boundary via `sys.argv`, errors
surface as exit codes the bash side translates to user-facing warnings.

Why this rule and not "rewrite to Python" or "split into multiple files":

- **Single-file distribution is a load-bearing UX property.** Users
  `curl one .sh -o argo_anywhere.sh && bash it`. The same single file is
  `scp`'d to the compute node and re-exec'd as `server`. Splitting into
  multiple files (a `lib/*.py` directory, even a single sibling `.py`)
  breaks both flows.
- **A full Python rewrite would lose that UX win**, and the work isn't
  free: the SSH multiplexing, the screen/tmux/nohup launcher, the box
  drawing, the bash 3.2 quirk handling — all of it would need a
  faithful re-port with subtle behavior change risk.
- **Heredocs cap the complexity at "small Python program."** If a
  heredoc grows past ~50 lines or needs non-stdlib dependencies beyond
  PyYAML (which is already in the server-side venv), that's a signal to
  re-evaluate this policy, not to keep growing the heredoc.

Trade-offs we're accepting:
- No syntax highlighting / linting / unit testing of the Python parts.
  Mitigate by keeping each heredoc short and self-contained.
- Variable interpolation across the boundary is by command-line args
  (with `<<'PYEOF'` to suppress bash interpolation inside the heredoc).
  This is verbose for many args but explicit, which we want.
- Python errors surface as exit codes the bash side has to interpret.
  Use small integer codes (2, 3, 4) consistently within each heredoc;
  document them in a comment immediately above the heredoc.

If we ever feel the heredoc pain enough to reconsider, the heredocs
themselves are pre-factored extraction points — moving them to a real
`.py` file is a mechanical refactor, not a redesign.

### Multi-client distribution: one file, multiple names

The script supports several AI clients (OpenCode, Claude Code, aider,
Cursor, generic OpenAI-compatible), but there is only **one** real
`.sh` file in the repo: `argo_anywhere.sh`. Per-client filenames
(`argo_opencode.sh`, `argo_claudecode.sh`, `argo_aider.sh`,
`argo_cursor.sh`) are **symlinks** to `argo_anywhere.sh`. GitHub
serves symlinks correctly via raw URLs (returns the linked content,
not a redirect), so users can:

```sh
curl -fsSL https://raw.githubusercontent.com/a-attia/argo-opencode/main/argo_claudecode.sh -o argo_claudecode.sh
bash argo_claudecode.sh    # picks Claude Code defaults
```

without ever knowing the file behind the name is shared.

The script inspects `$0` (its invocation name, basename only) at
startup and picks a sensible default client per name. The `setup`
subcommand always shows the interactive client picker regardless of
invocation name, for power users who want a non-default client without
renaming the file.

Per-client API contract — every supported client must define:

- `setup_<name>_client()` — top-level entry point invoked by the
  dispatcher (`do_post_tunnel_for_client`). MUST be idempotent. Calls
  `ensure_<name>_installed`, then `handle_config_file <path> <desc>
  write_<name>_config`. Reads `PROXY_PORT`, `ANL_USERNAME`,
  `ARGO_ANYWHERE_USER` from script-level globals.
- `ensure_<name>_installed()` — install-or-detect the client binary.
  After install, prepend any well-known install location to `PATH` so
  the rest of the running script sees the binary (the upstream
  installer's rc-file PATH update doesn't reach the running shell —
  see `ensure_opencode_installed`'s comment for the full rationale).
- `write_<name>_config(dest)` — produce a fresh config at `dest`.
  Invoked by `handle_config_file`, so the signature is fixed at "one
  arg, the destination path"; everything else flows in via globals.
  Use a Python heredoc for non-trivial JSON/YAML/TOML merging
  (preserves user-owned keys; we only own the few keys we need).
- `<name>` row in the `CLIENTS_AVAILABLE` array (display-order +
  picker label).
- A `<name>` arm in `do_post_tunnel_for_client` that calls
  `setup_<name>_client`, then `gather_summary; render_summary`,
  then prints any client-specific tail messages ("Run: claude" etc.).
- An arm in `default_client_for_invocation` that maps
  `argo_<name>.sh` → `<name>`.
- A repo-root symlink `argo_<name>.sh -> argo_anywhere.sh`.

Optional but conventional:

- A `<name>_pick_scope()` function if the client has multiple
  config locations (project vs global, etc.). Sets globals
  `_<NAME>_SCOPE_PATH` and `_<NAME>_SCOPE_NAME` for the writer to
  consume — DO NOT capture via `$()` (the function may need to
  prompt the user; subshell capture would eat the prompt). See
  `claudecode_pick_scope` for the reference implementation.

Why this shape (and why NOT truly separate per-client scripts):

- **Per-client UX preserved.** Discoverability via filename, sensible
  defaults per name, per-client filenames in `ps`/log output.
- **Zero code duplication.** The transport layer (~2500 lines: SSH
  multiplexing, tunnel monitoring, server bootstrap, state, status,
  clean) is the same across clients. Truly-separate scripts would
  require N copies of all of it; one bug fix = N file edits.
- **Single-file distribution preserved.** Each per-client name is
  still a single curl. No tarballs, no shared `argo_lib.sh`, no
  multi-file `scp` to compute nodes.
- **One source of truth.** Edit `argo_anywhere.sh`; every name
  updates automatically. No drift between copies.

Costs accepted (the "20%" we lose vs truly separate scripts):

- A user who only uses one client still receives a file containing
  every client's setup code. Harmless dead code from their POV; if
  they `cat` the script before running, they see ~4500 lines instead
  of ~1500.
- Versioning is repo-wide. We can't say "Claude Code support is v2.3
  stable, OpenCode is v2.0 still in beta" — they're the same file at
  the same tag.

Maintenance rules:

- The real file is `argo_anywhere.sh` (canonical name as of v1.2.0).
  Pre-v1.2.0 the canonical name was `argo_opencode.sh`; that name now
  lives as a symlink to `argo_anywhere.sh`. Existing curl URLs (pinned
  to v1.1.0 or earlier) keep working forever; existing main-tracking
  URLs (`…/main/argo_opencode.sh`) keep working because GitHub serves
  symlinks transparently. See "Single-instance constraint" + "Multi-
  client distribution" sections + the rename history in `git log`.
- Symlinks are normal `ln -s` in the repo; commit them as such.
  `git ls-files --stage` shows symlinks with mode `120000`.
- New per-client name = new symlink + add an arm to the
  invocation-name detection block at the top of `main()`.
- README's "Quick start" gets a per-client row pointing at the right
  raw URL. Each row's `curl -fsSL …/<name>.sh -o <name>.sh` works
  independently.

### Single-instance constraint (one tunnel + one argo-proxy per user per node)

The script is built around the assumption that each user runs **one**
argo-proxy per compute node and **one** SSH tunnel per local port.
Concrete pinch points:

- `SCREEN_SESSION="agovproxy"` is a single global constant. argo-proxy
  is always started inside the screen/tmux session named `agovproxy` —
  no per-port suffix.
- `~/.config/argoproxy/config.yaml` is the single argo-proxy config
  file on the node. Its `port:` line is mutated on each invocation.
- `local_tunnel_status` checks only "is something on this port?";
  it can't tell which destination the tunnel targets.

Implications:

- A user who runs `client` twice with **different ports on the same
  node** would silently destroy the first run's argo-proxy (the second
  run's bootstrap kills the existing screen session that happens to
  share the name). The detect-and-warn check in `mode_server`
  (introduced in audit fix G1) catches this and asks before killing.
- A user who runs `client` twice with **same port to different nodes**
  would silently reuse the first tunnel (which targets the first
  node) for traffic intended for the second. The detect-and-warn check
  in `ensure_or_reuse_tunnel` (also G1) catches this and refuses.
- `status` / `stop` / `clean` operate on a single `PROXY_PORT` value.
  No "show me ALL my tunnels" view exists.

If we ever lift this constraint (multi-instance support), the touchpoints
to consider:
- per-port screen session names (`agovproxy-${PROXY_PORT}`)
- per-instance argo-proxy config files (e.g. `~/.config/argoproxy/<port>.yaml`)
  OR a single multi-instance argo-proxy that the user runs once with
  multiple `serve` invocations on different ports (not currently
  supported by argo-proxy upstream).
- `local_tunnel_status` to also verify the destination matches.
- `status` / `stop` / `clean` redesigned around "show all" instead of
  "show one".

Don't take this on lightly — argo-shim chose a different lane (Python,
deterministic per-user-port naming, single-purpose) and we explicitly
chose ours (bash, single-port-default, multi-client-per-tunnel). The
detect-and-warn checks let users discover the limitation gracefully
without us having to expand the surface area.

### `clean` subcommand risk tiers

Three risk tiers:
- **safe items** (state dir, mux sockets, tunnel, remote venv) deleted on
  global confirmation;
- **risky items** (OpenCode/argo-proxy configs and their `.bak.*` backups)
  get a per-file prompt;
- **non-interactive flags** for risky items: `--purge` opts into deletion of
  files + backups; `--purge-backups` only kills backups. Both flags skip the
  per-file prompt even without `-y` (the user explicitly opted into a
  destructive action).

`--dry-run` previews; `--local-only` skips remote.

## Conventions to respect

- Don't introduce a package layout, requirements file, or test scaffolding.
  The script is intentionally a single self-contained file.
- Don't introduce new runtime dependencies. The script targets stock
  bash + ssh + scp + curl + lsof on the laptop, and stock Python 3.10+ on
  the compute node. `jq` is optional (used for some JSON paths;
  `update-models` requires it).
- `examples/` files must remain sanitized (no real usernames, hostnames, or
  ports beyond defaults). They are documentation, not config.
- Don't extend `start_argo_tunnel.sh` if you find a copy of it locally —
  it's the historical predecessor of this script and should not be touched.

## Testing

No unit tests, no CI. After non-trivial edits run at least the smoke tests:

```sh
bash -n argo_anywhere.sh                              # syntax
bash argo_anywhere.sh -h                              # short usage
bash argo_anywhere.sh help | head -50                 # long help renders
bash argo_anywhere.sh status                          # exit 1 if no tunnel
bash argo_anywhere.sh clean --dry-run -y --local-only # safe enumeration
```

The `status` summary's "ALL GREEN" branch only fires when the script's
tunnel is actually up — keep one running while you work if you want full
coverage.

For end-to-end verification (real SSH, real Duo prompt, real argo-proxy on
a compute node), follow [`docs/TESTING.md`](docs/TESTING.md). Run it before
tagging a release and after any change to the prompt flow, env-var handling,
or SSH option logic.

## Release process

1. Make changes on `main`. Smoke-test after each edit; live-test
   (`docs/TESTING.md`) before tagging.
2. Update the script header's example `curl` URLs if you're bumping the
   recommended pinned tag.
3. `git tag vX.Y.Z` and `git push origin main vX.Y.Z`.
4. The `curl …/raw.githubusercontent.com/a-attia/argo-opencode/vX.Y.Z/…`
   URL becomes live as soon as the push completes.

There is no separate release-notes file (yet). If we ever start one, this
section should mention it.
