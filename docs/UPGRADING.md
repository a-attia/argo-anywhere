# Upgrading from v1.x to v2.x

This document is for users who already have a working `argo_opencode.sh`
v1.x install and are upgrading to `argo_anywhere.sh` v2.x (v2.0.0 or
v2.1.0; both tagged 2026-05-15). It describes what changes you will
see, what the script does automatically on first v2.x run, and what
you may need to do manually. New users (no prior install) should
follow [`README.md`](../README.md) directly.

The v2.0.0 → v2.1.0 jump is small (7 defensive-hardening fixes; no
state migration). The bulk of this document covers the v1.x → v2.0
migration; the
[Behavior changes in v2.1.0](#behavior-changes-in-v210-phase-2d-defensive-hardening)
section near the bottom adds the v2.0 → v2.1 deltas. If you're going
directly v1.x → v2.1.0, read both.

## TL;DR

The most important changes:

- **Filename**: `argo_opencode.sh` → `argo_anywhere.sh`. The old name
  no longer exists. Re-curl the script (or `git pull`) to get the new
  one.
- **CLI tool selection is now explicit**: `--cli-tool <name>` (or the
  interactive picker) replaces the v1.x convention where the script's
  invocation name picked the tool (`argo_opencode.sh` → opencode,
  `argo_claudecode.sh` → claudecode, etc.). Aliases recommended.
- **Env vars renamed**: `ARGO_OPENCODE_*` → `ARGO_ANYWHERE_*`. Old
  names still honored with a one-time deprecation warning per
  variable; you can update at your leisure.
- **State directory moved**: `~/.config/argo_opencode/` →
  `~/.config/argo_anywhere/`. Migrated automatically on first v2.0
  run; no manual steps needed.
- **`verbose: false` is now the default in the on-node argo-proxy
  config**, closing a privacy regression where prompts were logged to
  disk on the compute node. Existing configs with `verbose: true` are
  rewritten to `verbose: false` on the next `client` run that triggers
  the config writer. Use `--verbose-server` (or
  `ARGO_ANYWHERE_VERBOSE_SERVER=1`) for opt-in debug logging.
- **Claude Code scope default changed** from global to project. Avoids
  a silent correctness regression where `claude auth login`'s OAuth
  token would override our config. Use `--scope global` to opt back
  in (and accept that you can't run `claude auth login` from that
  machine).
- **Many CSPO defenses + identity-handling fixes** (see
  [`docs/AUDIT_2026-05-12.md`](AUDIT_2026-05-12.md) for the full audit
  trail). No action needed; defaults are stricter and safer.
- **v2.1.0 fail-louder defensive-hardening (Phase 2d)**: 7 additional
  fixes (M6, M7, M8, M9, M10, L6, L10) that change behavior in the
  "die-loud with recovery hint instead of silent corruption" direction.
  Successful-path UX unchanged; you'll see new die paths only on
  edge cases (broken JSON in your claudecode config; missing PyYAML;
  unset `PROXY_PORT`; a foreign process racing into the script's
  port; non-TTY stdin without the LOGGING sentinel). See
  [Behavior changes in v2.1.0](#behavior-changes-in-v210-phase-2d-defensive-hardening)
  for the per-fix descriptions.

## Step-by-step migration

### 1. Get the new script

Either re-curl from the renamed repo:

```sh
curl -fsSL https://raw.githubusercontent.com/a-attia/argo-anywhere/main/argo_anywhere.sh \
  -o argo_anywhere.sh
chmod +x argo_anywhere.sh
```

Or, if you cloned the repo:

```sh
cd argo-anywhere   # was: cd argo-opencode
git pull
```

The GitHub repo redirects forever from `argo-opencode` to
`argo-anywhere`, so URLs you have bookmarked still work. The local
working directory may be named either; renaming yours is optional but
recommended for clarity.

If you previously had a per-tool symlink convention
(`argo_claudecode.sh` → `argo_opencode.sh`, etc.), delete those
symlinks. v2.0 picks the tool by `--cli-tool` flag, not by invocation
name.

### 2. Update your shell aliases (optional, but recommended)

If your shell rc files have aliases pointing at the old filename,
update them. Recommended pattern:

```sh
# in ~/.bashrc / ~/.zshrc:
alias argo='bash /path/to/argo_anywhere.sh'
alias argo-opencode='bash /path/to/argo_anywhere.sh --cli-tool opencode'
alias argo-claudecode='bash /path/to/argo_anywhere.sh --cli-tool claudecode'
```

Old aliases pointing at `argo_opencode.sh` keep working until you
delete that file; the rename doesn't break them automatically.

### 3. Update environment variables (optional)

If you `export`'d any of the old `ARGO_OPENCODE_*` variables in your
shell rc, update them:

| Old name (still honored) | New name |
|:-------------------------|:---------|
| `ARGO_OPENCODE_USER` | `ARGO_ANYWHERE_USER` |
| `ARGO_OPENCODE_NODE` | `ARGO_ANYWHERE_NODE` |
| `ARGO_OPENCODE_PORT` | `ARGO_ANYWHERE_PORT` |
| `ARGO_OPENCODE_NO_JUMP` | `ARGO_ANYWHERE_NO_JUMP` |
| `ARGO_OPENCODE_NO_MFA` | `ARGO_ANYWHERE_NO_MFA` |
| `ARGO_OPENCODE_FORCE_REINSTALL` | `ARGO_ANYWHERE_FORCE_REINSTALL` |
| `ARGO_OPENCODE_SHOW_MODELS` | `ARGO_ANYWHERE_SHOW_MODELS` |
| `ARGO_OPENCODE_CONTROL_PERSIST` | `ARGO_ANYWHERE_CONTROL_PERSIST` |
| `ARGO_OPENCODE_AUTO_PORT` | `ARGO_ANYWHERE_AUTO_PORT` |
| `ARGO_OPENCODE_PORT_RANGE` | `ARGO_ANYWHERE_PORT_RANGE` |
| `ARGO_OPENCODE_KEEP_ORPHANS` | `ARGO_ANYWHERE_KEEP_ORPHANS` |
| `ARGO_OPENCODE_DROP_ORPHANS` | `ARGO_ANYWHERE_DROP_ORPHANS` |
| `ARGO_OPENCODE_LOGGING` | `ARGO_ANYWHERE_LOGGING` |

The legacy names print one deprecation warning per variable on first
use, then promote to the new name silently for the rest of the
session. Update at your convenience.

The two oldest pre-namespace names also still work with deprecation
warnings: `ANL_USERNAME` → `ARGO_ANYWHERE_USER`, `PROXY_PORT` →
`ARGO_ANYWHERE_PORT`, `SHOW_MODELS` → `ARGO_ANYWHERE_SHOW_MODELS`.

### 4. Run `client` once; everything else happens automatically

```sh
bash argo_anywhere.sh --cli-tool opencode client
```

On first v2.0 run from the laptop, the script:

1. **Migrates the state directory** from `~/.config/argo_opencode/` to
   `~/.config/argo_anywhere/` (preserves cached username, cached node,
   cached SSH-failure state). Backs up the old directory rather than
   deleting it; remove it manually after you confirm v2.0 works.
2. **Cleans up legacy SSH multiplex sockets** (`argo-opencode-*`)
   alongside the new ones (`argo-anywhere-*`) when you run `clean`.
   No action needed for normal use.
3. **scp's the new script** to the compute node as
   `~/.argo_anywhere.sh` (replacing the old `~/.argo_opencode.sh`).
4. **Detects the running v1.x argo-proxy** if any and warns. The
   v1.x argo-proxy will continue serving until you stop it; the
   running process keeps the old in-memory config (notably
   `verbose: true`) until restarted.

If you have an active v1.x argo-proxy process and want the new
defaults (`verbose: false`) to take effect immediately, restart it:

```sh
ssh <user>@<node> 'screen -S argovproxy -X quit; pkill -f argo-proxy'
bash argo_anywhere.sh --cli-tool opencode client   # spawns fresh argo-proxy
```

Otherwise the next natural restart of argo-proxy (e.g. node reboot,
manual stop, etc.) will pick up the new config.

### 5. Verify

```sh
bash argo_anywhere.sh status
```

Expected: `ALL GREEN` summary box with `Cached username`,
`Cached node`, `Tunnel uptime`, etc. If you see "Cached node:
(none yet)", the migration didn't carry over your old cache —
re-run `client` once to repopulate.

```sh
ssh <user>@<node> 'grep -E "^verbose:" ~/.config/argoproxy/config.yaml'
```

Expected: `verbose: false` (after at least one `client` run that
exercised the config writer). If it still says `verbose: true` and
you didn't pass `--verbose-server`, the config writer wasn't invoked
on the most recent run (the local-tunnel-reuse short-circuit
sometimes prevents `mode_server` from running). Force a re-run:

```sh
bash argo_anywhere.sh stop
bash argo_anywhere.sh --cli-tool opencode client
```

### 6. Optionally: clean up the old install

After v2.0 has been running fine for a while:

```sh
# delete the old script (laptop)
rm /path/to/argo_opencode.sh

# remove the legacy state directory (auto-migrated; backup retained)
rm -rf ~/.config/argo_opencode/

# (compute node) remove the legacy script
ssh <user>@<node> 'rm -f ~/.argo_opencode.sh ~/.argo_opencode.server.log'

# (compute node) remove the legacy venv if you have one
ssh <user>@<node> 'rm -rf ~/agovenv'
```

These are all safe to skip. The legacy artifacts don't conflict with
v2.0; they just waste a few MB of disk.

## Behavior changes you may notice

### Default `verbose: false` in argo-proxy config

Pre-v2.0, the script wrote `verbose: true` into the on-node
`~/.config/argoproxy/config.yaml`, causing argo-proxy to log full
prompt + response bodies to `~/.argo_anywhere.server.log` (mode
0644 by default). On shared compute nodes this exposed prompt
content to anyone with SSH access to your account. v2.0 defaults
to `verbose: false`; opt back in with `--verbose-server` (or
`ARGO_ANYWHERE_VERBOSE_SERVER=1`) when actively debugging
argo-proxy.

The change applies on the next `client` run that triggers the
config writer. The running argo-proxy process keeps the old
in-memory config until restarted (see [Step 4](#4-run-client-once-everything-else-happens-automatically)).

### Default Claude Code scope changed from global to project

Pre-v2.0, on a fresh Claude Code install (no `~/.claude.json`,
no existing global env block), the script wrote to
`~/.claude/settings.json` (global scope). After the user ran
`claude auth login`, the OAuth token in `~/.claude.json` would
silently take precedence over `env.ANTHROPIC_AUTH_TOKEN` in
`settings.json` — neutralizing the proxy config without warning.

v2.0 defaults to project scope (`./.claude/settings.local.json`
in the current directory), which is not affected by the OAuth
precedence rule. Use `--scope global` (or `CLAUDECODE_SCOPE=global`)
to opt back in to the old behavior, AND accept that you can't run
`claude auth login` from that machine without breaking the proxy
config.

If your existing setup uses global scope and you want to keep it,
nothing breaks — `--scope global` is still supported. The change
only affects fresh installs and users who hadn't explicitly chosen
scope.

### Stricter on-node argo-proxy reuse identity check

Pre-v2.0, on the compute node when the script found an existing
healthy argo-proxy on the configured port, it would reuse it as
long as `cfg_user != want_user` was false. If the config.yaml was
missing or unreadable (so `cfg_user` came back empty), the check
would short-circuit to false and the script would silently attach
to a stranger's argo-proxy.

v2.0 requires a POSITIVE identity match (cfg_user == want_user)
before reusing. Three explicit refusal branches: want_user empty,
cfg_user empty, cfg_user != want_user. Only the confirmed-match
branch reuses, with the verified user name in the success log
line.

### Ctrl+C exit summary now prints what's still alive

Pre-v2.0, Ctrl+C on a foregrounded `client` returned silently to
the prompt. v2.0 prints a scope-keyed summary explaining: (a) the
local SSH tunnel + health monitor are stopped, (b) the SSH
multiplex master is still alive (keeps Duo state warm), (c) the
remote argo-proxy is still alive (keeps the node's port held),
and (d) the exact commands for each scope you might want to also
tear down. The destruction scope of Ctrl+C itself is unchanged.

### Better error messages on SSH failure lock

Pre-v2.0, when the SSH-attempt-failure tracker locked further
attempts, you would see the recovery instructions printed twice
(once by `ssh_attempt_pre`, once by the caller's `die "Refusing
to ... See above for recovery instructions"`). v2.0 prints the
recovery block once + a one-liner identifying which call path
was aborted.

## Behavior changes in v2.1.0 (Phase 2d defensive-hardening)

v2.1.0 (released 2026-05-15, same day as v2.0.0) introduces a
"fail louder, not silently" discipline (codified as design
decision D-016 in `PLAN.md`). The successful-path UX is
unchanged; the changes are visible only on edge cases that
silently corrupted user data or used unsafe defaults pre-v2.1.

If you're upgrading directly from v1.x to v2.1.0 (skipping v2.0.0
in between), you get all the v2.0.0 changes above PLUS these:

### Claude Code config writer refuses to merge broken JSON

Pre-v2.1, if `~/.claude/settings.json` (or
`./.claude/settings.local.json`) was malformed JSON (e.g. you
edited it manually and broke a brace), the writer would silently
treat it as `{}` and overwrite it with a fresh file containing
only the proxy env keys -- destroying your broken-but-recoverable
content. v2.1 detects the parse failure and refuses to merge,
with a recovery message offering three options: (1) fix the JSON
manually with `python3 -m json.tool`, (2) move the file aside
with a timestamp backup, or (3) pick `[k]eep` at the next
config-handling prompt to preserve the file in place while you
recover content from it.

### argo-proxy config writer requires PyYAML for safe merge

Pre-v2.1, if PyYAML wasn't available in the Python the script
picked (the argo-proxy venv first, then system `python3`), the
writer would fall back to writing a hardcoded 6-key defaults
file -- silently dropping any user-owned keys
(`argo_embedding_url`, `argo_stream_url`, `concurrent_downloads`,
`max_payload_size`, etc.) when you picked `[b]ackup` at the
config prompt. v2.1 dies hard with explicit recovery hints
(`pip install pyyaml`, `apt install python3-yaml`, or
`--force-reinstall server` for the venv path).

In practice PyYAML is always present in the script's argo-proxy
venv (it's a transitive dep of argo-proxy itself), so this die
fires only on truly minimal compute nodes where the venv is
missing or corrupted. If you've never seen the warn message
about "no python available for YAML merge" or "YAML merge
failed (PyYAML missing)" pre-v2.1, this die won't fire for you
in v2.1 either.

### opencode config writer asserts PROXY_PORT is set

Pre-v2.1, an empty `PROXY_PORT` would silently interpolate into
the OpenCode `baseURL` as `http://localhost:/v1` -- a syntactically
valid URL that points nowhere, and OpenCode would silently fail
to connect. v2.1 dies at writer entry with a clear message.
`resolve_port` always runs before this writer in the normal
client flow, so this die effectively never fires; it's a
defense against script-internal refactor / direct-call paths
that would otherwise produce a broken config.

### `ensure_or_reuse_tunnel` refuses to overlay our tunnel on a foreign listener

Pre-v2.1, when the script detected an unhealthy SSH tunnel on
the configured port AND classified it as ours, an unconditional
`xargs -n1 kill` would destroy any process bound to that port,
even if the classification was wrong (e.g. a different script's
`ssh -L` raced into the port between classification and kill).
v2.1 re-checks each PID's command line against the same
`ssh -L <port>:` pattern before killing; if a PID doesn't match,
the script logs the unmatched command line for inspection and
dies with "Refusing to overlay our tunnel on a foreign
listener." rather than silently destroying the foreign process.

### Mux master classification more robust to ps format drift

Pre-v2.1, the `local_tunnel_status` mux detection relied on
matching `ps -o command=` output against the exact regex
`*ssh:*argo-anywhere-*[mux]*`. The `ps` format varies across OS
versions (macOS Big Sur+ shows `ssh: <socket-path> [mux]`; older
versions may omit the `[mux]` tag). v2.1 adds a defense-in-depth
fallback: if the primary regex doesn't match but the command
line mentions `argo-{anywhere,opencode}-` AND a corresponding
socket file exists in `~/.ssh/sockets/`, classify as mux. This
prevents false-negative refusal-to-reuse on systems where the
primary regex stops matching due to format drift.

### `ask()` warns when stdin isn't a TTY

Pre-v2.1, when stdin wasn't a TTY (e.g. you piped the script's
input from a file or ran it under CI / automation), `ask()`
silently returned the default value. v2.1 prints a one-line WARN
naming the prompt + the auto-answered default, so you can see
what got auto-answered. Suppressed when `ARGO_ANYWHERE_LOGGING=1`
is set (the legitimate `mode_server` tee'd-re-exec scenario).

If you've been piping input into the script, you'll see new WARN
lines like:

```
[warn] non-interactive (stdin is not a TTY); auto-answering prompt
[warn]   'Pick a node:' with default 'compute-01.cels.anl.gov'.
```

This is informational only; the script's behavior is unchanged,
just made visible.

### Action required for v1.x → v2.1 upgraders

Same as v1.x → v2.0 (see [Step-by-step migration](#step-by-step-migration)
above). v2.1 doesn't add any migration steps beyond what v2.0
already required. The Phase 2d changes are all behavior
visibility / defensive correctness, not state migration.

## Things that did NOT change

- **The CLI surface** for `client` / `setup` / `tunnel` / `server`
  / `status` / `stop` / `update-models` / `clean` / `list-tools`
  / `help` is the same. Existing scripts that wrap the script keep
  working.
- **Single-file distribution** is unchanged. One `argo_anywhere.sh`
  on the laptop; the same file is `scp`'d to the compute node and
  re-exec'd as `server`.
- **bash 3.2+ target** (macOS default) is unchanged. No bash-4
  features.
- **MFA / Duo handling** is unchanged. SSH multiplex master
  still opens once per session; subsequent SSH calls don't re-prompt.
- **The opencode config + argo-proxy config formats** (modulo
  the `verbose:` default) are unchanged.

## Where to read more

- [`README.md`](../README.md) — top-level user-facing entry point.
- [`docs/SECURITY.md`](SECURITY.md) — threat model, CSPO defenses,
  privacy posture.
- [`docs/LIMITATIONS.md`](LIMITATIONS.md) — known limitations
  (single-instance constraint, no automated tests, etc.).
- [`docs/TESTING.md`](TESTING.md) — live-verification guide.
- [`docs/AUDIT_2026-05-12.md`](AUDIT_2026-05-12.md) — full audit
  trail with all 43 findings + their resolutions.

If something broke during your upgrade that isn't covered here, file
an issue at <https://github.com/a-attia/argo-anywhere/issues> with
the `client` invocation that failed and the relevant log lines.

---

*Created 2026-05-15 by Ahmed Attia (with substantial AI assistance
from Claude per [`CONTRIBUTORS.md`](../CONTRIBUTORS.md)) as part of
Phase 2c+3 of the v2.0 release. Revised 2026-05-15 (post-Phase 2d)
to add the "Behavior changes in v2.1.0" section covering the seven
defensive-hardening fixes shipped in v2.1.0 (M6, M7, M8, M9, M10,
L6, L10).*
