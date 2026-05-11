# AGENTS.md

Maintainer / contributor notes for `argo_opencode.sh`. The user-facing
documentation is `README.md` and the script's own `help` subcommand. This
file is the *behind-the-scenes* guide: invariants, gotchas, design rationale,
and the historical bugs we'd rather not repeat.

## What this repo is

A single-purpose repo around one substantial bash script and its supporting
docs and config examples:

- `argo_opencode.sh` — end-to-end orchestrator that lets Argonne users run
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

## `argo_opencode.sh` — what to know before editing

The script is ~3000 lines of **bash** (not POSIX `sh`). Its first executable
lines re-exec under `bash` if invoked through any other shell, which catches
the macOS-specific gotcha where `/bin/sh` is bash with `POSIXLY_CORRECT=y`.
The `help` subcommand prints the full user guide; this section is the
maintainer-side complement.

Distribution: published at <https://github.com/a-attia/argo-opencode>.
Users `curl` either `main` or a pinned release tag (e.g. `v1.0.0`); both
URLs are documented in `README.md` and the script's own header.

### Subcommands

`client` (default), `server`, `status`, `stop`, `update-models`, `clean`,
`help`. The `client` mode `scp`s the file to a chosen compute node and
re-execs it as `server` over SSH.

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
`ARGO_OPENCODE_PORT` are one-shot overrides; if they disagree with the
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
- `ARGO_OPENCODE_USER`
- `ARGO_OPENCODE_NODE`
- `ARGO_OPENCODE_PORT`
- `ARGO_OPENCODE_NO_JUMP`
- `ARGO_OPENCODE_NO_MFA`
- `ARGO_OPENCODE_FORCE_REINSTALL`
- `ARGO_OPENCODE_SHOW_MODELS`
- `ARGO_OPENCODE_CONTROL_PERSIST`
- `ARGO_BOX_STYLE`

Legacy names `ANL_USERNAME`, `PROXY_PORT`, `SHOW_MODELS` still work with a
one-time deprecation warning. They are snapshotted **before** the script's
own config block reassigns them, so promotion sees the inherited values.

The Argonne username is distinct from the laptop's `$USER` — never
substitute one for the other. The writers always read `ARGO_OPENCODE_USER`
(with `ANL_USERNAME` as legacy fallback). `mode_server`'s pid-owner check
uses `id -un` (OS-level, correct) but the config-user check uses
`ARGO_OPENCODE_USER` (Argonne-level, correct).

### `set -euo pipefail` is on

Avoid `[ test ] && cmd` at function/branch top level. When the test fails,
`set -e` doesn't kill (the man page exempts `&&`/`||` chains), but bash 3.2
(macOS default) has parser quirks with quoted heredocs inside `$()` under
`set -u` that have bitten this script before.

Use `if/then/fi` and write multi-line remote scripts via temp files
(`mktemp` + `ssh ... < file`), **never** `var="$(cat <<'EOS' ... EOS)"`.

### Targets bash 3.2+

macOS default. No bash-4 features (no `${var,,}`, no `mapfile`, no
`declare -A`, no `printf -v` with format reuse, etc.).

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
bash -n argo_opencode.sh                              # syntax
bash argo_opencode.sh -h                              # short usage
bash argo_opencode.sh help | head -50                 # long help renders
bash argo_opencode.sh status                          # exit 1 if no tunnel
bash argo_opencode.sh clean --dry-run -y --local-only # safe enumeration
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
