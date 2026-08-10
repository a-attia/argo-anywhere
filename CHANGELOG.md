# Changelog

Notable changes to [argo-anywhere](https://github.com/a-attia/argo-anywhere).
This project follows [Semantic Versioning](https://semver.org/): the
Python package's version (`3.x.y`) tracks the user-facing feature +
compatibility story; the vendored bash engine's `SCRIPT_VERSION` is
a separate internal component tag (see PLAN.md D-029).

Prior to `3.1.0` no changelog file was maintained; release history for
`v3.0.x` and the `v2.x` bash-script era is captured in `PLAN.md` (design
decisions D-001 through D-030) and the tag messages on the repo.

---

## Unreleased

### Fixed

- **`connect` tunnel no longer dies after ~1 hour of idle** (PLAN.md
  D-033). The quick-connect **Connect** button (and the `connect` /
  `tunnel` / `client` / `setup` CLI verbs) held the SSH tunnel only as
  long as the multiplex master's `ControlPersist` window — a finite
  ~1h. After the foreground `ssh -N -L` exits, the master owns the
  port-forward (D-003), but an idle `-L` listener does **not** count as
  an open channel for the ControlPersist idle timer (verified against
  OpenSSH `channels.c`), so the master was reaped after ~1h of no
  traffic and the forward died with it. Idle channels silently dropped
  and forced a reconnect, even though a separately hand-opened `ssh`
  session to the same host stayed up.

  Fix: channel-owning modes now request an **indefinite**
  `ControlPersist` (the master is torn down only by `stop` / `clean` /
  Ctrl-C, never by an idle timeout). One-shot commands (`status`,
  `update-models`, `clean`, ...) keep the finite 1h default. An
  explicit `ARGO_ANYWHERE_CONTROL_PERSIST` still overrides both. No new
  SSH connections or authentications are introduced, so this has no
  effect on the CSPO SSH-authentication budget.

- **Web UI: a stale channel no longer blocks reconnect.** The
  single-Channel guard previously refused a new **Connect** whenever a
  channel-owning engine process was still registered — even if that
  process had outlived its tunnel (the ~1h expiry above). Clicking
  Connect then failed with an opaque "ws error (rejected by server)."
  The guard now confirms the tunnel is actually serving (a purely local
  loopback-listener check — it never traverses the tunnel or contacts
  ANL); if the channel is stale, it reaps the dead session and lets the
  fresh Connect proceed.

### Changed

- **Web UI: the Connect action is now two clearly-labeled paths.** The
  channel card shows **Connect** (quick — reuses your saved node /
  username / port) and **Connect with options…** (opens the Actions
  sheet locked to `connect`, with the SSH-target overrides expanded and
  node/username pre-filled from cache, for picking a different compute
  node, ANL username, or jump host). Sublabel text spells out the
  difference. The old single Connect button had no visible way to
  reach the override fields short of the general Actions menu.

## v3.2.1 — 2026-07-16

Hotfix. **Upgrade if you are on v3.2.0** and your laptop username
differs from your Argonne username — the common case, and the one
v3.2.0 got wrong.

**Symptom**: `connect` asks for a password after Duo is accepted.
Reported from the field 2026-07-16.

**Cause**: `ssh -G <host>` always prints a `user` line — absent an
explicit `User` in `~/.ssh/config`, it fills in your **local OS
username** as the default, the same way it echoes the input back as
`hostname` for an unconfigured host. v3.2.0's D-032 username
inference read that line without checking whether ssh_config had
actually configured anything, so it treated the laptop username as a
resolved Argonne username. Since the inference sits *above* the
username cache in the priority order, it outranked the correct cached
value. argo-anywhere then SSHed to an account whose key isn't
authorized, publickey auth failed, and sshd fell back to asking for a
password. Duo passing first is consistent with this — the account was
wrong, not the second factor.

**Blast radius** was wider than a stale cache. On a machine with no
cache yet, the same bad inference **suppressed the interactive
"Enter your ANL username" prompt entirely**: a brand-new v3.2.0 user
was never asked, and silently got their laptop username. Anyone whose
`~/.ssh/config` sets `User` on the compute nodes but not on the jump
host was affected even with a correct cache on disk.

### Fixed

- **`_ssh_config_user` no longer mistakes ssh's default for
  configuration.** It now compares the resolved user against the
  local OS user (`id -un`) and treats a match as "nothing configured",
  returning empty so the caller falls through to the cache or the
  prompt. This mirrors the Python side's identical check in
  `SshGResult.is_alias`, which got it right in v3.2.0's A6 amendment
  but was never back-ported to the engine; the two are now in lockstep
  per the D-032 coupling contract. Pre-D-032 behavior is restored for
  every case where ssh_config has nothing to say.

  *Trade-off*: if your Argonne username genuinely equals your laptop
  username, the helper no longer infers it and you fall through to the
  cache or prompt. The resolved value is identical either way.

- **`_is_ssh_config_alias` no longer reports every bare hostname as an
  ssh_config alias.** Its third detection signal consumes
  `_ssh_config_user` and inherits the fix.

- **A latent `set -e` trap in the same helper.** A bare `return`
  inherits the status of the preceding `[` test, so "no user
  configured" surfaced as exit 1 and tripped `set -euo pipefail`
  inside the caller's `$(...)` assignment. Early returns are now
  explicit `return 0`; empty stdout is the "nothing configured"
  signal, per the Section 8 helper contract.

### Added

- **Two regression tests** (`tests/test_engine_ssh_config.py`), one
  verified to fail against the unfixed engine and reproduce the
  reported symptom exactly, the other guarding the opposite direction
  so the local-user comparison can't over-correct and start ignoring
  a genuinely-configured `User`.

- **A corrected test-harness docstring.** The `ssh -G` stub emitted
  *nothing* for unconfigured hosts and claimed that matched OpenSSH.
  It doesn't — real `ssh -G` always dumps a full effective config.
  The stub being more forgiving than reality is why 419 passing tests
  never saw this bug; the docstring now says so and points at the
  guard.

Workaround if you are staying on v3.2.0 for now:

```bash
export ARGO_ANYWHERE_USER=<your-anl-username>   # highest priority; beats the bad inference
```

Verified against real ANL infrastructure 2026-07-16: `connect`
resolves the correct username from cache and completes with a single
Duo prompt and no password prompt.

---

## v3.2.0 — 2026-07-15

*(Changelog entry backfilled 2026-07-16; the release shipped without
one. Content reconstructed from the release commit `cd8bbdd`.)*

Feature-adding release. **Superseded by v3.2.1** — see above; this
release has a username-resolution bug affecting most users. Install
v3.2.1 instead.

**One-line summary**: argo-anywhere learns to respect your
`~/.ssh/config` — `argo-anywhere --node <ssh-config-alias>` now "just
works", with alias detection, username inference, and automatic
suppression of our `-J` when the alias already carries its own
routing.

Full design record:
[`notes/impl_ssh_config_native.md`](notes/impl_ssh_config_native.md);
locked design decision: **D-032** in [`PLAN.md`](PLAN.md).

### Added

- **Native `~/.ssh/config` support (D-032)** in the engine: new
  helpers (`_ssh_config_hostname`, `_ssh_config_user`,
  `_alias_has_own_proxy`, `_is_ssh_config_alias`), alias-aware
  `pick_node`, and automatic skip of our `-J` when the target alias
  has its own `ProxyJump` / `ProxyCommand` (which would otherwise be
  redundant at best and a jump-loop error at worst).
- **`--jump-host HOST`** / **`ARGO_ANYWHERE_JUMP_HOST=HOST`** for
  pointing argo-anywhere at a non-default jump host. An explicitly
  empty `ARGO_ANYWHERE_JUMP_HOST=""` is treated as `--no-jump`,
  matching shell convention for opt-out env vars.
- **Web-UI launcher SSH-target overrides** — compute node, ANL
  username, jump host, and no-jump fields, with an ssh_config alias
  picker (`/api/ssh-hosts`) and a resolved-launch preview panel
  (`/api/preview-launch`) that shows what argo-anywhere will actually
  run, including divergence between what you typed and what
  ssh_config resolves. Both endpoints are IP-block-safe by contract:
  neither authenticates against any SSH server.

### Fixed

- **PyYAML self-heal** in `ensure_argoproxy_installed`, which now
  probes for PyYAML and installs it rather than assuming `argo-proxy`
  pulls it transitively — an assumption falsified by a field report
  from a fresh compute node, where the user hit "Refusing to write
  argo-proxy config without PyYAML for safe merge".
- **`handle_config_file`'s `[k/b/d/m/a]` prompt** only offers `[m]`
  when merge can actually work (never for YAML; for JSON only when
  `jq` is on `PATH`). Previously the option was offered and then
  silently rejected after the user picked it.

### Changed

- **Install extras consolidated to a single-mode default.** `fastapi`,
  `uvicorn`, and `pywebview` are now plain dependencies; the
  `[web]` / `[app]` / `[all]` / `[test]` / `[screenshots]` extras are
  gone. `pipx install argo-anywhere` delivers the web UI, native app,
  and `install-launcher` out of the box — no more
  `argo-anywhere[app]` to remember. Only `[dev]` remains.

---

## v3.1.1 — 2026-07-13

Hotfix. iTerm2 was smoke-tested during the v3.1.0 release cycle;
Terminal.app was not, and it turned out the AppleScript we ship for
Terminal.app never worked at all — a `run` verb targeting Terminal.app
would surface as `could not open (HTTP 502)` with the raw
osascript error text in the launcher popover.

### Fixed

- **Terminal.app AppleScript**: replaced the invalid
  ``set index of window 1 of newTab to 1`` (osascript exit 1,
  ``-10006 Can't set window ... to 1``) with the working idiom
  ``set frontmost of (first window whose tabs contains newTab) to
  true``. Terminal.app's `window` class exposes `frontmost`
  (boolean), not `index`; the earlier attempt also used
  ``window 1 of newTab`` which isn't a valid reference at all.
  iTerm2's path was unaffected (uses `create window` +
  `select newWindow` + `activate`).
- **Regression test added**
  (`test_macos_terminal_script_uses_valid_frontmost_idiom`) that
  pins the broken patterns OUT and the working idiom IN, so a
  well-meaning refactor can't silently reintroduce the bug.

Everything else in v3.1.0 unchanged. `pipx upgrade argo-anywhere`
picks this up.

---

## v3.1.0 — 2026-07-13

Feature-adding release. Engine `SCRIPT_VERSION` bumped `2.2.1-dev` →
`2.3.0`. All changes below apply to installs upgraded via
`pipx upgrade argo-anywhere`.

**One-line summary**: web-UI launcher gains an explicit working-
directory field + dual embedded terminals (Channel + Utility) +
scope-aware forbid-list + light/dark theme; the bash engine grows a
`--cwd` flag for CLI parity; the `claudecode` config writer adopts
Anthropic's canonical `ANTHROPIC_API_KEY` env-var name and gains an
in-place migrator for older configs; the release includes a
multi-instance guard, a cross-platform focus-follow-window discipline
for spawned native terminals, and a Models panel rewrite.

Full design record: [`notes/impl_launcher_cwd.md`](notes/impl_launcher_cwd.md);
locked design decision: **D-031** in
[`PLAN.md`](PLAN.md).

### Added

- **Web-UI launcher `working directory` field** — required, absolute
  path, pre-fills with the most-recently-used entry from
  `~/.argo_anywhere/web_state.json` (else `$HOME` on first run). A
  **Browse…** button next to the field opens a native folder picker
  in the pywebview app (hidden in browser mode where the sandbox
  blocks that API). Missing directories trigger an explicit
  "Create + Launch" confirmation dialog — never a silent `mkdir`.
- **Dual embedded terminals** in the web UI, split horizontally with
  a draggable divider:
  - **Channel** (left) — persistent, owns `connect`, survives a
    browser tab close so the SSH master + tunnel keep running (no
    repeat Duo).
  - **Utility** (right) — ephemeral, runs `configure` / `setup` /
    `tunnel`, free to relaunch without disturbing the Channel.
  Both panels share the container-level Terminal/Hide toggle. Divider
  position persists across reloads.
- **Light/dark theme toggle** in the top bar. Cycles `auto → dark →
  light → auto`. `auto` follows the OS preference via
  `prefers-color-scheme`; explicit choices persist to
  `~/.argo_anywhere/web_state.json`. Both embedded terminals re-color
  on toggle.
- **Engine `--cwd PATH` flag** (CLI parity with the web launcher).
  Changes to PATH before dispatching the verb; absolute path required;
  `~` and `~user` are expanded. Under `--scope project` the same
  forbid-list runs as in the web layer.
- **Scope-aware forbid-list** for `project` scope. Hard-blocks `$HOME`
  exact + system dirs (`/`, `/bin`, `/sbin`, `/usr`, `/etc`, `/var`,
  `/opt`, `/tmp`, `/var/tmp`, and on macOS `/System`, `/Library`,
  `/private` plus the `/private/etc` etc. symlink targets). Soft-warns
  when the cwd has neither `.git` nor a common project marker
  (`pyproject.toml`, `package.json`, `Cargo.toml`, `Makefile`,
  `go.mod`, …) — protects beginners from accidentally writing tool
  configs where they didn't mean to. `--scope global` is unrestricted
  (beginner happy path from `$HOME`).
- **Multi-instance guard**. `/healthz` on the web server now returns
  a package marker + pid + version, and `argo-anywhere web` /
  `argo-anywhere app` probe the target port before binding. If
  another argo-anywhere is already there, they refuse cleanly with a
  helpful "there's already one on :N (pid X, version Y); try --port
  N+1" message instead of a raw `bind()` traceback. `--force`
  bypasses (advanced use; the two instances then share
  `web_state.json` with last-write-wins semantics).
- **Cross-platform focus-follow-window** for spawned native
  terminals. On macOS AppleScript-driven terminals (Terminal.app +
  iTerm2), `activate` is now the last statement in the tell-block so
  the new window actually ends up frontmost. For Popen-launched
  terminals (alacritty / kitty / wezterm / ghostty on macOS; the
  whole Linux catalog), a best-effort raise call fires after spawn:
  `System Events` + `set frontmost` on macOS; `wmctrl -a` on Linux
  X11 (silent no-op on Wayland, where the compositor enforces
  focus-stealing-prevention by design). Never fails the launch.
- **Per-tool `<name>_shadowing_env_vars()`** contract. Each CLI tool
  declares the shell env vars whose values would shadow the config we
  wrote. A new `_check_env_shadow_and_warn` helper is called from the
  dispatcher right after `configure` finishes / before `run` execs
  the tool; if any of those env vars are set in the shell, a loud
  warning fires with the exact `unset <VAR>` commands to run. Applies
  to `opencode`, `claudecode`, `aider`, and every future tool that
  declares the function. Guards against the class of bug where a
  stale export in `~/.bashrc` (a personal API key from another
  project, say) silently routes requests away from argo.
- **`GET /api/models` endpoint** + web-UI Models panel rewrite. The
  panel now renders each model as a card with per-provider color-coded
  badges (openai green, claude orange, gemini blue), modality tags,
  and an explicit `in opencode config` badge (only when an OpenCode
  config is present — the flag is *opencode-only* and the panel now
  says so). Replaces the raw fixed-width text dump that was hard to
  scan and left users wondering whether "not configured" meant
  something was broken.
- **`argo-anywhere web --reload`** flag for source-checkout iteration.
  Requires `watchfiles`; not for use with a `pipx`-installed release
  (would invalidate the install by editing package files).

### Changed

- **Web-UI launcher no longer accepts a blank working directory**.
  Previously the field didn't exist and the spawned engine inherited
  whatever cwd the web server was launched from — which for a
  double-clicked native app was usually `$HOME`, producing surprising
  behaviour when `--scope project` wrote a config there. Blank input
  is now rejected client-side and server-side; the pre-filled default
  makes the friction one keystroke.
- **`client` verb removed from the web-UI launcher dropdown** (still
  available in the CLI). The web UI teaches the split-verb story
  (`connect` + `configure` + `run`) end-to-end; `client` is the
  legacy all-in-one path that predates that split.
- **`run` and `client` hard-blocked from embedded terminals**. Both
  in the UI (dropdown option disabled) and on the server side (`/ws`
  refuses these verbs at spawn time). Rationale: closing the browser
  tab would kill the tool session mid-work.
- **pywebview app starts in `~/.argo_anywhere/`** instead of `$HOME`.
  The app's own cwd is shown in the top-bar status strip + the About
  popover so users always know where the app itself is running (as
  distinct from where spawned tools will start — that's the per-launch
  cwd field).
- **`claudecode` config writer emits `env.ANTHROPIC_API_KEY`** instead
  of the equivalent-but-legacy `env.ANTHROPIC_AUTH_TOKEN`. Both are
  honored by Claude Code and both route requests correctly (verified
  by a dead-port live test); `ANTHROPIC_API_KEY` is Anthropic's
  canonical name in their public docs, so adopting it is
  future-proofing.
- **Scope input in the launcher** switched from free-text to a
  dropdown (`— auto —` / `global` / `project`). No more silent
  `--scope projct` typos. Includes a one-directional nudge:
  `cwd == $HOME` pre-selects `global` (steers beginners away from a
  common mis-configuration); project markers do NOT auto-nudge toward
  `project` (the safe direction is one-way).
- **Actions popover widened** to 620 px (was 440 px) so the working-
  directory row + Browse button don't cramp.

### Fixed

- **`console_command()`** (which builds the argv used to invoke
  argo-anywhere in a new terminal window) preferred a
  `<sys.executable> -m argo_anywhere` fallback that only worked in
  the *server's* env, not in the fresh login shell macOS + iTerm2
  spawn. Result: users running the dev server under a Python where
  `argo_anywhere` was only importable via `PYTHONPATH=src` saw
  `No module named argo_anywhere` in the new terminal window (which
  immediately closed). The ladder now prefers a `PATH`-lookup of the
  `argo-anywhere` console script over the `-m` form (the PATH-based
  invocation survives to a fresh shell). A new
  `console_command_verified()` runs a `<prefix> --version` probe
  with a scrubbed env before shipping the command, so a prefix that
  would only succeed with our env leaks now surfaces as an HTTP 500
  with a diagnostic instead of failing invisibly in a terminal.
- **Confirm-modal `lede` field now honors HTML markup**. Previously
  `<code>` tags in the modal text rendered as literal characters
  (e.g. `<code>/path</code>` shown verbatim). All caller-provided
  dynamic substrings (paths, verb names, error text) are now escaped
  via a `_escHtml()` helper before interpolation.
- **`_confirmAndMkdir` retry loop** treats HTTP 409 "already exists"
  as success (was previously classified as failure, silently
  cancelling the retry launch when a doubled UI action or a race
  had already created the dir).
- **`_migrate_claudecode_config_in_place`** runs before
  `handle_config_file` for `claudecode` configs. This silently
  upgrades pre-2026-07-13 configs to the canonical env-var name
  even in non-TTY callers (the web UI's `configure` verb and
  `run --ensure` are non-TTY and would previously auto-answer `k`
  at the `[k/b/d/m/a]` config-differs prompt, skipping the writer
  entirely and leaving the file stale).

### Documentation

- **`docs/LIMITATIONS.md`** — new section
  ["Claude Code TUI is misleading"](docs/LIMITATIONS.md#claude-code-tui-is-misleading-shows-subscription-tier-text-even-when-routing-goes-through-argo).
  Documents that Claude Code's welcome banner + Select-model picker
  are rendered from `~/.claude.json` OAuth account state regardless
  of the actual routing — so users may see "Opus 4.8 · API Usage
  Billing" and reasonably conclude they're on their personal
  subscription even when requests are correctly reaching argo.
  Includes concrete verification recipes (e.g.
  `claude --print --model claude-4.5-haiku 'reply ok'` — that model
  exists only in argo's catalog).
- **`docs/UPGRADING.md`** — new section for v3.0.x → v3.1.0 walkthrough
  covering: the launcher cwd contract change, the removal of `client`
  from the web dropdown, the two-panel embedded terminal split, the
  `--cwd` engine flag, the light/dark theme toggle, the multi-instance
  guard, the `web_state.json` state file, and the `ANTHROPIC_API_KEY`
  canonical-name adoption + auto-migration.
- **`README.md`** — new "Launching from the web UI (v3.1.0+)" section
  describing the five launcher fields, the dual-panel embedded
  terminal, and the theme toggle. New "Same guarantees from the CLI:
  `--cwd`" section for CLI users on remote nodes.
- **`AGENTS.md`** — new sections codifying the engine ↔ web-UI scope
  coupling rule (D-031), the launcher-cwd handling contract, the
  dual embedded terminals contract, the multi-instance guard policy,
  the light/dark theme toggle discipline (any new UI color goes into
  CSS custom properties for both palettes), the focus-follow-window
  discipline, and the per-tool `<name>_shadowing_env_vars()` contract.

### Development

- **CI**: the pinned pytest suite grew from 133 → 290 tests
  (mostly for D-031 and the auth-var work). All 290 pass on
  CPython 3.10 / 3.11 / 3.12 / 3.13.
- **Multi-instance guard usable for dev iteration**: run
  `PYTHONPATH=src python -m argo_anywhere web --port 8800 --reload`
  alongside a `pipx`-installed instance on `:8799` for painless
  iteration on the fixed code without disturbing the channel-owning
  release install.

### Contributors

Ahmed Attia (with substantial AI assistance from Claude per
[`CONTRIBUTORS.md`](CONTRIBUTORS.md)).

---

*This changelog was started 2026-07-13 for the v3.1.0 release.
Pre-3.1.0 history lives in the git log (`git log --oneline v3.0.1`)
and in `PLAN.md`'s design decisions D-001 through D-030.*
