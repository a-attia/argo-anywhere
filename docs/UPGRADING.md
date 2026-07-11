# Start here: install and migrate

Pick the **one** row that matches you. Each path is 2–3 steps; everything after
this section is reference detail you only need if something surprises you.

> **Pre-release note.** v3 isn't on PyPI yet, so `pipx install argo-anywhere` will
> work once v3.0.0 ships. **Until then**, wherever a step below says
> `pipx install argo-anywhere`, use the branch command:
> `pipx install 'argo-anywhere[app] @ git+https://github.com/a-attia/argo-anywhere@feat/python-package-webui'`

### New to argo-anywhere

1. **Install:** `pipx install argo-anywhere`
2. **Connect** (one Duo prompt): `argo-anywhere connect`
3. In another terminal, **run a tool** against that channel:
   `argo-anywhere run aider` (or `opencode` / `claudecode`). Prefer no terminal?
   `argo-anywhere install-launcher` gives you a double-click app.

### Coming from v2.x (you ran `bash argo-anywhere.sh …` or `curl … .sh`)

1. **Install the package:** `pipx install argo-anywhere`. It bundles the engine
   and owns everything now — you can delete your old `argo-anywhere.sh` file.
2. **Nothing to migrate by hand.** Your cached username / node / port and the
   install manifest move themselves on the first run.
3. **Tidy the old version's leftovers** — superseded copies on your laptop *and*
   on the compute node — without reconnecting: after `connect`, run
   `argo-anywhere prune`. *(prune lands right after v3 merges; until then,
   `argo-anywhere clean` after `connect` does the node cleanup with no extra Duo.)*

> If you added `. ~/.argo_anywhere/env` to your `~/.zshrc` / `~/.bashrc` for the
> old version, remove that line — the package doesn't use it.

### Coming from v1.x (you ran `argo_opencode.sh`)

1. **Install the package:** `pipx install argo-anywhere`.
2. The **first run refuses to start** while v1.x state is present and prints the
   exact 2–3 cleanup commands — run them, then re-run.
3. Continue as **New to argo-anywhere** above.

---

No hidden state: everything argo-anywhere puts on your machine is visible with
`argo-anywhere info` and removable with `argo-anywhere uninstall` (which also
restores your AI-tool configs to their pre-argo state).

---

# Upgrading from v1.x to v2.x

This document is for users who already have a working `argo_opencode.sh`
v1.x install and are upgrading to `argo-anywhere.sh` v2.x (v2.0.0,
v2.1.0, or v2.2.0). It describes what changes you will see, what the
script does automatically on first v2.x run, and what you may need to
do manually. New users (no prior install) should follow
[`README.md`](../README.md) directly.

> **Upgrading a v2.x install to v3.0.0?** v3 is a **clean break in how
> argo-anywhere is installed** (a `pipx`-installable Python package) but **not
> in how it works** (the same bash engine, vendored verbatim). Jump to
> [v2.x → v3.0.0: the Python-package rebuild](#v2x--v300-the-python-package-rebuild).
> Everything below concerns the v1.x → v2.x bash-script era.

The v2.0.0 → v2.1.0 jump is small (7 defensive-hardening fixes; no
state migration). The v2.1.0 → v2.2.0 jump adds the per-tool scope
framework, port-as-state caching, OpenCode project-scope, and
cross-client port-coherence; one new on-disk artifact
(`~/.config/argo_anywhere/port`) is created on first v2.2.0 run via
a one-shot migration that surfaces any pre-existing disagreement.

The bulk of this document covers the v1.x → v2.0 migration;
[Behavior changes in v2.1.0](#behavior-changes-in-v210-phase-2d-defensive-hardening)
adds the v2.0 → v2.1 deltas, and
[Behavior changes in v2.2.0](#behavior-changes-in-v220-phase-4-multi-tool-framework)
adds the v2.1 → v2.2 deltas. If you're going directly v1.x → v2.2.0,
read all three.

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
curl -fsSL https://raw.githubusercontent.com/a-attia/argo-anywhere/main/argo-anywhere.sh \
  -o argo-anywhere.sh
chmod +x argo-anywhere.sh
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
alias argo='bash /path/to/argo-anywhere.sh'
alias argo-opencode='bash /path/to/argo-anywhere.sh --cli-tool opencode'
alias argo-claudecode='bash /path/to/argo-anywhere.sh --cli-tool claudecode'
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

The legacy names print one deprecation warning per variable on first
use, then promote to the new name silently for the rest of the
session. Update at your convenience.

The two oldest pre-namespace names also still work with deprecation
warnings: `ANL_USERNAME` → `ARGO_ANYWHERE_USER`, `PROXY_PORT` →
`ARGO_ANYWHERE_PORT`, `SHOW_MODELS` → `ARGO_ANYWHERE_SHOW_MODELS`.

### 4. Run `client` once; everything else happens automatically

```sh
bash argo-anywhere.sh --cli-tool opencode client
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
bash argo-anywhere.sh --cli-tool opencode client   # spawns fresh argo-proxy
```

Otherwise the next natural restart of argo-proxy (e.g. node reboot,
manual stop, etc.) will pick up the new config.

### 5. Verify

```sh
bash argo-anywhere.sh status
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
bash argo-anywhere.sh stop
bash argo-anywhere.sh --cli-tool opencode client
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
what got auto-answered. Suppressed when `_ARGO_ANYWHERE_REEXEC=1`
is set (the legitimate `mode_server` tee'd-re-exec scenario; this
is an internal sentinel, not a user-facing variable).

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

## Behavior changes in v2.2.0 (Phase 4 multi-tool framework)

v2.2.0 lands the **per-tool scope framework**, promotes the
proxy port to **transport-layer state**, adds **OpenCode
project-scope** support, and adds **cross-client port-coherence**
enforcement. Five design decisions in PLAN.md cover the wire:
D-017 (per-tool default scope policy), D-018 (per-tool scope
vocabulary contract), D-019 (`ARGO_ANYWHERE_SCOPE` user-facing +
`_SCOPE_OVERRIDE` internal), D-020 (port-as-state), D-021
(cross-client coherence).

### `--scope <value>` is now per-tool (not claudecode-specific)

v2.0 introduced `--scope project|global` for Claude Code only.
v2.2 generalizes the flag: each tool declares its accepted
`--scope` values via a `<name>_scope_values()` function, and the
CLI parser validates per-tool at the picker stage.

* **claudecode** accepts `project` or `global` (unchanged from v2.0).
* **opencode** now accepts `project` or `global` (new in v2.2; see
  next subsection). Default is `global`.

If you pass `--cli-tool X --scope Y` where `Y` is not in `X`'s
vocabulary, the script dies with a clear "unknown scope Y for
tool X; valid values: ..." message instead of silently writing
the wrong file.

### `CLAUDECODE_SCOPE` env var deprecated; use `ARGO_ANYWHERE_SCOPE`

The v2.0 `CLAUDECODE_SCOPE` env var still works but prints a
one-time WARN per shell session:

```
[warn] CLAUDECODE_SCOPE is deprecated; use ARGO_ANYWHERE_SCOPE instead.
[warn]   (Honored for now; planned removal in v3.0.0.)
```

To silence the warning, update your shell rc:

```sh
# old
export CLAUDECODE_SCOPE=global

# new
export ARGO_ANYWHERE_SCOPE=global
```

`ARGO_ANYWHERE_SCOPE` is per-invocation; you can still pass
`--scope ...` to override it on individual commands.

### OpenCode project-scope is now supported

Pre-v2.2, `--cli-tool opencode` always wrote
`~/.config/opencode/config.json` (global). v2.2 adds
`--cli-tool opencode --scope project` which writes
`<git-root>/opencode.json` (walked from cwd; falls back to cwd
when not in a git repo).

Default remains `global` to avoid surprising existing users.
Conflict detection (existing files; project-shadow-of-global)
runs in all branches; you'll get a `[k]eep / [s]witch / [a]bort`
prompt if the project-scope write would shadow your global config.

### New on-disk artifact: `~/.config/argo_anywhere/port`

v2.2 promotes the proxy port to transport-layer state. Pre-v2.2,
`PROXY_PORT` was derived from `--port` > env > **OpenCode config
baseURL** > default. v2.2 inserts a **port cache** between env
and OpenCode config:

  1. `--port` flag
  2. `ARGO_ANYWHERE_PORT` env
  3. cached port (`~/.config/argo_anywhere/port`)
  4. one-shot first-run migration (no cache; existing client
     configs)
  5. `PROXY_PORT_DEFAULT` (64742; true cold start)

**First v2.2 run** finds the cache empty and runs the migration:

* **Case 1** — no existing client configs with a baseURL: seed
  cache with `PROXY_PORT_DEFAULT` (64742); log "no existing
  client configs; cached default port".
* **Case 2** — exactly one configured tool (or all agree): seed
  cache from that config; log "migrated port N from `<tool>`
  config to `~/.config/argo_anywhere/port`".
* **Case 3** — multiple installed configs disagree on port: get
  prompted with `[m]igrate / [u]se-once / [k]eep / [a]bort` to
  pick the canonical port. `[m]igrate` seeds the cache with the
  first-listed port; `[k]eep` seeds it with the alternative;
  `[u]se-once` uses the first port for this run only without
  writing the cache.

**Subsequent runs** read the cache and skip the migration. The
cache is write-through: any time `resolve_port` chooses a port
via something other than the cache, the new value is written
back.

`clean` already sweeps the state directory as a unit; no new
entry is needed. To delete the cache manually:

```sh
rm ~/.config/argo_anywhere/port
```

The next `client` invocation will re-run the one-shot migration.

### Cross-client port-coherence is now actively enforced

When you have multiple AI CLI tools installed (e.g. opencode +
claudecode), their config files all need to point at the same
proxy port. Pre-v2.2, only the OpenCode-vs-resolved-port case
was detected; claudecode disagreements were silent.

v2.2 adds two layers of detection (per D-021):

* **`status` is now noisier** when configs disagree. After the
  health/models box, you may see:

  ```
  [warn] Cross-client port disagreement detected (D-021):
  [warn]   Resolved port (cache / CLI / env / default): 64742
  [warn]   Disagreeing client config(s):
  [warn]     claudecode global 64750 /Users/.../claude/settings.json
  [warn]   Run 'argo-anywhere.sh client' to canonicalize via the [m/u/k/a] prompt.
  ```

  status's exit code is unchanged (disagreement is informational;
  the proxy/tunnel can still be healthy).

* **`client` startup proactively prompts** when other installed
  configs disagree. You'll see a `[m]igrate / [u]se-once /
  [k]eep / [a]bort` prompt with the same semantics as the
  pre-existing OpenCode-specific prompt. `[m]igrate` rewrites
  disagreeing configs to match the resolved port on this run;
  `[u]se-once` skips downstream writes (configs untouched);
  `[k]eep` switches `PROXY_PORT` to the alternative and updates
  the cache.

**Known gap**: `opencode --scope project` configs are not yet
enumerated by the disagreement detector (only opencode-global +
claudecode-global + claudecode-project-in-cwd). If you use
opencode project-scope across multiple projects with different
ports, you'll need to canonicalize manually for now. Deferred
until a user reports being bitten.

### `mode_stop` correctly identifies our own tunnels

A latent v2.1.x bug: `mode_stop`'s case labels (`ours-healthy`,
`ours-unhealthy`) never matched `local_tunnel_status`'s actual
return values (the F1/F5 refactor in v2.1 added `-fg`/`-mux`
suffixes:  `ours-healthy-fg`, `ours-unhealthy-fg`,
`ours-healthy-mux`, `ours-unhealthy-mux`). Result: every "stop
my tunnel" run fell through to the external-listener branch's
blast-radius warning (which is the wrong message for the
laptop-tunnel case). v2.2 fixes the labels. The user-visible
effect: stopping your own tunnel now prints the correct concise
"killed your tunnel; argo-proxy survives on the remote node"
message instead of the multi-paragraph blast-radius warning.

### Action required for v1.x → v2.2 upgraders

The state-cache migration is automatic but you may be prompted
on first v2.2 run if Case 3 applies (multiple installed configs
disagree). Pick `[m]igrate` if you want the script-resolved port
to be canonical; pick `[k]eep` if you want the alternative
config's port to win.

If you have `export CLAUDECODE_SCOPE=...` in your shell rc,
rename it to `ARGO_ANYWHERE_SCOPE` at your leisure (the script
will keep working with the old name until v3.0.0).

If you don't use OpenCode and want to keep your existing port
without seeding the cache to the default, run the migration
explicitly:

```sh
mkdir -p ~/.config/argo_anywhere
echo 64742 > ~/.config/argo_anywhere/port   # whichever port you want
```

This is equivalent to picking Case 2 with the port of your
choice on first run.

## Behavior changes since v2.2.0 (landed on `main` for v2.2.1)

### New `update` subcommand for lossless in-place upgrades

Before v2.2.1 the only way to upgrade `argo-proxy` on the node was
either `--force-reinstall server` (full venv wipe + rebuild) or
hand-running `argo-proxy update install` over SSH yourself. Same
for the laptop-side CLI tools (OpenCode / Claude Code) and for the
script itself: there was no scripted upgrade path; you had to
re-run the upstream installer (or re-`curl` the script) manually.

The new `update` subcommand (PLAN.md D-022 + D-023) closes all
those gaps:

```sh
bash argo-anywhere.sh update --all                  # update everything
bash argo-anywhere.sh update argo-anywhere          # self-update the script
bash argo-anywhere.sh update argoproxy              # just argo-proxy on the node
bash argo-anywhere.sh update opencode claudecode    # explicit list
bash argo-anywhere.sh update --check --all          # report-only
bash argo-anywhere.sh update --all -y               # non-interactive
```

Properties:

- **Lossless**: never wipes the venv, configs, or OAuth state.
  `--force-reinstall` remains the destructive escape hatch.
- **Prompts before installing** a component that isn't there
  (`--yes` auto-confirms; matches `clean`'s convention).
- **After a successful `update argoproxy`**, auto-POSTs `/refresh`
  to the local tunnel so the running proxy pulls fresh upstream
  models without restart. Silently skipped if no tunnel is up.
- **Self-update** (`update argo-anywhere`) resolves the latest
  upstream tag, validates the fetched script (`bash -n` + size +
  sentinel marker), backs up the existing canonical install at
  `~/.argo_anywhere/argo-anywhere.sh`, and atomically replaces
  it. Refuses to clobber a dirty git working tree. Prompts to
  bootstrap the canonical install if it doesn't exist yet.
- **Extensible**: new CLI tools (Phase 5 aider / future cursor)
  register an `update_<name>_cli_tool` helper and get included
  automatically.

**Action required**: none. The existing `--force-reinstall` path
keeps working unchanged. If you've been running
`--force-reinstall` periodically just to pick up new argo-proxy
versions, you can switch to `update argoproxy` for a much faster
and less disruptive upgrade.

The legacy `ssh -J <user>@logins.cels.anl.gov <user>@<node>
'~/argovenv/bin/argo-proxy update install'` recipe still works
and is documented in `help` as a manual fallback for the case
where `update argoproxy` can't reach the node from the laptop.

### Canonical install at `~/.argo_anywhere/`

The first time you run `client` or `setup` in v2.2.1 (or later),
the script auto-creates `~/.argo_anywhere/` and copies itself
there as the canonical install (rustup/cargo style PATH
directory). It then prints one-shot instructions for adding the
sourceable `env` file to your shell rc:

```sh
# Add this ONE line to your ~/.zshrc (zsh) or ~/.bashrc (bash):
. "$HOME/.argo_anywhere/env"
```

After that, `argo-anywhere.sh` is callable as a bare command from
any directory. The `update argo-anywhere` subcommand keeps the
canonical install fresh.

**Action required**: nothing forced. Skip the bootstrap with
`ARGO_ANYWHERE_SKIP_BOOTSTRAP=1` in the env if you prefer to
manage the script copy yourself. If you already had a manual
`~/.argo_anywhere/` setup from a previous version (e.g. with a
hand-written `env` file or a direct `export PATH=...` rc line),
the bootstrap is a no-op (it only fires when the directory
doesn't exist); `update argo-anywhere` will manage that existing
copy from here on.

**Transitional note for v2.2.0 → v2.2.1**: the very first run of
`update argo-anywhere` from a v2.2.0 install will fetch the
latest tag (v2.2.0 itself until v2.2.1 is tagged). After v2.2.1
ships, the next `update argo-anywhere` picks up the v2.2.1 code
+ the `SCRIPT_VERSION` constant; subsequent upgrades are
version-aware.

### aider support (new CLI tool)

`aider` joins OpenCode + Claude Code as a `--cli-tool` value. It uses
the same OpenAI-compatible endpoint OpenCode does, so nothing changes
about the channel. Two aider-specific notes:

- The writer creates `~/.aider.conf.yml` (or a project-scoped
  `.aider.conf.yml`) **plus** a sibling `.aider.model.settings.yml`
  that sets `use_temperature: false` for reasoning / opus-4.7+ / gpt-5 /
  o-series / gemini models. Without it, those models return an empty
  response through argo-proxy (they reject the `temperature` param aider
  sends by default). The default model is `openai/argo:gpt-4o`; to use
  another, pass the EXACT `/v1/models` id, e.g.
  `aider --model openai/argo:claude-opus-4.8`.
- aider is installed via its self-contained standalone installer (which
  bundles Python 3.12), falling back to `uv` then `pipx`. A bare
  `pipx install aider-chat` under a very new system Python can fail to
  build pinned deps; the ordering avoids that.

### New lifecycle verbs: `connect` / `configure` / `run`

The workflow is now split into the three levels the script manages,
while `client` / `setup` / `tunnel` stay as one-shot fallbacks:

- `connect` — bring up the shared channel + hold the monitor (friendlier
  `tunnel`).
- `configure TOOL...` — install + configure one-or-more tools against an
  **existing** channel (fails with a hint if none is up; `--ensure`
  brings it up). Multi-tool in one call.
- `run TOOL` — configure one tool then launch it.

Nothing forces you to adopt these — `--cli-tool X client` works exactly
as before. The split just lets you keep the channel in one window and
configure/run tools freely in others (the channel serves them all
simultaneously).

### `install` / `uninstall` subcommands + `bin/` layout

- The canonical install moved from `~/.argo_anywhere/argo-anywhere.sh`
  (a flat file) to `~/.argo_anywhere/bin/argo-anywhere.sh`, alongside
  thin `bin/install` and `bin/uninstall` wrappers. **This migration is
  automatic** on the next `install` / `client` / bootstrap run; your
  existing flat-layout script is moved into `bin/` and the `env` helper
  is rewritten to point at `bin/` (it keeps the old dir on PATH too, so
  nothing breaks mid-migration).
- `install` is the explicit form of the first-run bootstrap
  (`--dry-run` to preview).
- `uninstall` is the new **symmetric** teardown: Tier 1 removes the
  canonical install + state + the tunnel we own; `--restore-configs`
  restores client configs to their pre-argo-anywhere state (using a new
  install manifest at `~/.argo_anywhere/manifest.json`);
  `--remove-binaries` removes only tool binaries the script installed;
  `--remote` points you at `clean --purge` for the compute-node venv.
  `uninstall` **never kills a channel it does not own** (an external or
  shared listener is left running with a warning).
- **Action required: none.** The manifest starts recording provenance
  from the next config write; configs written by earlier versions have
  no manifest entry, so `uninstall --restore-configs` can only precisely
  restore configs touched after this upgrade (older ones are left in
  place with a warning rather than guessed at).

## Things that did NOT change

- **The existing CLI surface** for `client` / `setup` / `tunnel` /
  `server` / `status` / `stop` / `update-models` / `clean` /
  `list-tools` / `help` is unchanged; the new `update`, `connect`,
  `configure`, `run`, `install`, and `uninstall` subcommands are purely
  additive. Existing scripts that wrap the script keep working.
- **Single-file distribution** is unchanged. One `argo-anywhere.sh`
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

## v2.x → v3.0.0: the Python-package rebuild

**This is a clean break in how argo-anywhere is _installed_ — not in how it
_works_.** v3.0.0 turns argo-anywhere from a single bash script you `curl` into
a `pipx`-installable **Python package** that owns the runtime and adds a local
**web UI** and an optional **native desktop app**. The orchestration engine is
the *same* bash script, vendored inside the package **verbatim** — so every
subcommand you already use behaves identically.

### TL;DR

|              | v2.x                              | v3.0.0                                            |
|:-------------|:----------------------------------|:--------------------------------------------------|
| Install      | `curl … argo-anywhere.sh -o …`    | `pipx install argo-anywhere`                      |
| Upgrade      | re-`curl` / `git pull` / `update` | `pipx upgrade argo-anywhere`                      |
| Run          | `bash argo-anywhere.sh <cmd>`     | `argo-anywhere <cmd>`                             |
| The engine   | the file you curled               | vendored verbatim; `argo-anywhere --print-script` re-emits it |
| New          | —                                 | `argo-anywhere web` (browser UI), `argo-anywhere app` (native window) |

Your configs, cached state (`~/.config/argo_anywhere/`), SSH sockets, and the
whole connect/Duo flow are **unchanged**. v3 wraps the engine; it does not
reimplement it.

### Install

Requires Python 3.10+ (plus the engine's usual `bash` / `ssh` / `scp` / `curl` /
`lsof`).

```bash
pipx install argo-anywhere            # CLI only
pipx install 'argo-anywhere[web]'     # + local web UI   (argo-anywhere web)
pipx install 'argo-anywhere[app]'     # + native window  (argo-anywhere app)
```

Prefer `pipx` so the CLI lands on your `PATH` in its own isolated environment;
`pip install --user` works too. Until v3.0.0 is published to PyPI, install the
pre-release straight from the branch:

```bash
pipx install 'argo-anywhere[app] @ git+https://github.com/a-attia/argo-anywhere@feat/python-package-webui'
```

### What you do

1. Install via `pipx` (above).
2. Use `argo-anywhere <command>` wherever you ran `bash argo-anywhere.sh
   <command>`. Every engine subcommand — `client`, `connect`, `configure`,
   `run`, `status`, `update`, `clean`, … — is passed straight through to the
   vendored engine on your real terminal, so Duo, the monitor, and every prompt
   work exactly as before.
3. *(Optional)* delete the old curled script. You can always recover the exact
   engine for inspection or forking:
   ```bash
   argo-anywhere --print-script > argo-anywhere.sh
   ```

### New: web UI and native app

- **`argo-anywhere web`** serves a loopback-only web UI — a live channel
  monitor, a browser terminal for connecting (Duo runs in the browser), and a
  launcher that opens your CLI tools in new native terminal windows. Needs the
  `[web]` extra.
- **`argo-anywhere app`** opens that same UI in a native desktop window
  (pywebview); it falls back to your default browser if the `[app]` extra isn't
  installed. Needs the `[app]` extra for the native window.
- **`argo-anywhere install-launcher`** drops a persistent, double-clickable
  launcher so you can start the UI without a terminal: on macOS a Desktop
  `.command` + a real `argo-anywhere.app` bundle (with an app icon); on Linux a
  `.desktop` menu entry + a Desktop `.sh`. It's registered in the footprint, so
  `argo-anywhere uninstall` removes it.

All three are optional — the CLI is fully usable without them.

### Why the clean break

The single-file `curl`-and-run distribution was the load-bearing UX of v1/v2.
The web UI and native app need a runtime that owns process lifecycle, an HTTP/WS
server, and a PTY bridge — which a lone bash script can't provide. v3 keeps the
engine a single self-contained file (vendored verbatim; still `scp`-able to a
compute node and re-exec'd as `server`) and wraps a thin Python runtime around
it. The `curl one .sh && bash it` route is retired as the *primary* install
path; `--print-script` preserves the inspect-and-fork workflow.

---

*Created 2026-05-15 by Ahmed Attia (with substantial AI assistance
from Claude per [`CONTRIBUTORS.md`](../CONTRIBUTORS.md)) as part of
Phase 2c+3 of the v2.0 release. Revised 2026-05-15 (post-Phase 2d)
to add the "Behavior changes in v2.1.0" section covering the seven
defensive-hardening fixes shipped in v2.1.0 (M6, M7, M8, M9, M10,
L6, L10). Revised 2026-05-18 (Phase 4 / v2.2.0) to add the
"Behavior changes in v2.2.0" section covering the per-tool scope
framework (D-017+D-018+D-019), port-as-state (D-020), OpenCode
project-scope, cross-client port-coherence (D-021), and the
`mode_stop` case-label fix. Revised 2026-07-10 (v3.0.0, Model A) to
add the "v2.x → v3.0.0: the Python-package rebuild" section (D-026..
D-029: pipx/PyPI install, vendored-verbatim engine, web UI + native
app).*
