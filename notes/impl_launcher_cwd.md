# impl_launcher_cwd.md — Web-UI launcher: cwd control + scope UX + dual embedded terminals

**Kind**: implementation plan (per `notes/README.md` convention).
**Status**: **EXECUTED + USER-VERIFIED (2026-07-13)**. All 11 tasks +
Task 5.5 + mid-execution safety fixes (2.4a multi-instance guard, 2.4b
dev-mode + spawn-safe console command, 2.4c cross-platform focus)
landed on `main`; 266 pytest tests green (from a 133 baseline); the
user manually smoke-tested the two-panel UI, cwd + Browse + missing-dir
confirm flow, scope dropdown, theme toggle, `run` in a new iTerm2
window under a dev-mode server (miniconda + pipx cross-config), and
the focus-follow-window behaviour. Archive to `_archive/` after the
first v3.1.0 release cycle passes (leave in place until then as the
"single source of truth" for the shape of the change).
**Targets**: v3.1.0 (feature-adding; minor bump per semver).
**Design decision**: **D-031** (see `PLAN.md`).

---

## 1. Problem statement

The web UI has two related sharp edges that surfaced in a
conversation on 2026-07-13:

1. **Blind cwd inheritance.** The FastAPI server + `pywebview` app
   inherit whatever cwd was in effect when they were launched (often
   `$HOME` via Finder / launchd / a desktop entry).
   `PtySession.__init__` (`src/argo_anywhere/driver.py:188`) spawns
   the engine via `subprocess.Popen(...)` with **no `cwd=`
   argument**, so the engine runs in that inherited cwd, and any AI
   CLI tool it launches does too.

   This has a load-bearing failure mode: `--scope project` uses
   `$(_git_root_or_cwd)` inside the engine
   (`argo-anywhere.sh:2782,3346`) to pick the config location. So
   clicking "Launch → run → opencode → scope: project" from the web
   UI while the server sits in `$HOME` writes `opencode.json` **into
   the user's home directory**, not into the project the user meant.
   The user has no way to tell the launcher "I want this tool to
   start in `/path/to/my-project/` instead".

2. **Free-text scope field invites typos.** The scope input at
   `src/argo_anywhere/web/static/index.html:284` is a bare `<input
   type="text">`. The engine rejects unknown values via
   `_validate_scope_for_tool` (a hard `die` from the engine), but
   the round-trip is opaque — the user sees "scope: projct" get
   silently rejected somewhere in the engine output.

Both problems are user-facing footguns in a tool whose primary
selling point is "makes AI CLI tools easy". This design record
locks the fix.

## 2. Approach — one PR, ordered tasks

The fix is a single PR bundling eleven tasks in dependency order.
The first task (splitting the embedded terminal into two panels) is
foundational — all subsequent UI changes assume the dual-panel
layout exists. The tasks map 1-to-1 to the execution checklist in
Section 8.

### 2.1 High-level UX contract (post-PR)

- The launcher popover carries three configurable rows:
  **command** + **cli tool** (unchanged); **scope** (now a
  dropdown); **working directory** (new, always required and
  visible with a pre-filled default). Below them: **where to run**
  (existing, now tool-aware).
- The embedded-terminal container at the bottom of the dashboard is
  split horizontally into two side-by-side panels: **Channel**
  (persistent; owns `connect`) and **Utility** (ephemeral; runs
  `configure` / `setup` / `tunnel`).
- The three info verbs (`status` / `list-models` / `list-tools`)
  continue to use `/api/run` (Lane-1 captured output). They are
  NOT streamed to Utility. Rationale: they're short one-shot
  fetches; a captured JSON round-trip is simpler than a per-verb
  panel takeover.
- `run` and `client` are HARD-BLOCKED from both embedded panels;
  they can only launch into an external terminal.
- `client` is REMOVED from the web UI's verb dropdown (it's the
  legacy all-in-one flow; the split-verb story
  connect+configure+run is what the web UI teaches). `client` stays
  in the CLI unchanged.

### 2.2 Locked decisions (from the 5-round planning conversation)

| ID  | Decision                                                                                                          |
|:----|:-------------------------------------------------------------------------------------------------------------------|
| D1  | Scope field = `<select>` with `— auto —`, `global`, `project` (per-tool vocabulary is stable enough).             |
| D2a | Absolute-path enforcement for cwd: client AND server (defense in depth).                                          |
| D2b | Browse button visible in pywebview build only; browser mode hides it (browser sandbox).                           |
| D2c | Missing directory → HTTP 409 from launch endpoint → confirm modal → OK triggers explicit `POST /api/mkdir`.       |
| D3a | pywebview app itself starts in `~/.argo_anywhere/`, not `$HOME`. Cwd shown in launcher header + About popover.    |
| D3b | Cwd field pre-fills with MRU top entry, else `$HOME` on first run. Value is visible, not placeholder text.        |
| D3c | MRU persisted on disk at `~/.argo_anywhere/web_state.json` (versioned schema, atomic writes).                    |
| D4  | No silent `mkdir`. Every creation is behind an explicit user confirmation.                                        |
| D5  | `~` is expanded via `.expanduser()` and counts as absolute. Symlinks resolved via `.resolve()`.                   |
| D6a | Forbid-list applies to `project` scope only; `global` scope is unrestricted (beginner happy path).                |
| D6b | Forbid-list enforced in BOTH Python (`web/app.py`) AND bash (engine `--cwd`). Bash is authoritative source.       |
| D6c | Cwd-aware scope default (one-directional): cwd == `$HOME` → dropdown pre-selects `global`. Project markers do NOT auto-nudge toward `project`. |
| D7a | Hard block on `run` / `client` → embedded (UI disables + server refuses).                                         |
| D7c | "Where to run" option renamed to reflect the constraint. Wording locked in Section 6.                             |
| D7d | Dual embedded terminals (Channel + Utility) is bundled into this PR; it's the foundation.                         |
| D7g | Split orientation: horizontal (side-by-side).                                                                     |
| D7h | Resizable divider with min/max width limits; position persisted in `web_state.json`.                              |
| D8  | Engine `--cwd <path>` flag bundled for CLI parity. Web UI and CLI stay in lockstep.                               |

### 2.3 Audit-pass refinements (2026-07-13, integrated before execution)

The audit pass on plan v5 surfaced eight refinements. All are
absorbed here as amendments to the locked decisions above; none
reopens a locked decision.

| ID  | Refinement                                                                                                                                                                                                                              |
|:----|:-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| A1  | Channel re-launch: check `channel_is_up` first. If channel is already healthy, refuse gracefully with "channel is already up — run `configure` in Utility instead"; offer a "stop + replace" secondary path that runs `stop` then `connect`. |
| A2  | Remove `client` from the web-UI verb dropdown. CLI-only.                                                                                                                                                                                 |
| A3  | Keep `list-tools` / `status` / `list-models` on `/api/run` (Lane-1 captured). Only `connect` / `configure` / `setup` / `tunnel` stream to a panel.                                                                                       |
| A4  | `configure` (Utility) refuses to launch if no Channel active. Clear error directs user to start Channel first via `connect`. No auto-launch (explicit > magic).                                                                          |
| A5  | `mkdir -p ~/.argo_anywhere/` in `cli._cmd_app` / `launcher.py` before cwd'ing there (canonical install may not have been bootstrapped yet).                                                                                              |
| A6  | `web_state.json`: versioned schema `{"version": 1, "mru": [...], "divider_pct": 50}`; atomic writes via `tempfile + os.replace`.                                                                                                        |
| A7  | Forbid-list check order = hard-block list FIRST, soft-warn scan SECOND. (Avoids stat storms on `/` if hard-block is bypassed.)                                                                                                          |
| A8  | Add per-panel reattach test: full browser refresh with Channel active must re-discover the session via `SessionRegistry` and reattach the ws.                                                                                            |

### 2.4 Deferred (recorded, not built in this PR)

- Folder picker in browser mode (blocked by browser sandbox; won't
  fix).
- Smarter MRU eviction (project-marker-aware, mtime-weighted). LIFO
  cap of 10 for v1.
- Per-panel show/hide toggle (container-level for v1 per D7d).
- `status` output reporting the cwd a channel was opened from.
- Streaming the info verbs (`status` / `list-models` / `list-tools`)
  to Utility instead of `/api/run` — cosmetic; keep captured for
  v1.

### 2.4b Dev-mode iteration + spawn-safe console command

Added mid-execution 2026-07-13 after two rounds of "the fix didn't apply".

**Problem 1: dev server holds old code.** Running the dev server via
``PYTHONPATH=src python -m argo_anywhere web --port 8800`` starts a normal
uvicorn process that does NOT autoreload. After a code edit the fix is
on disk but the server process still runs the pre-edit bytecode. Manual
Ctrl-C + restart is the workaround; ``--reload`` (dev only; requires
``watchfiles``) makes iteration painless.

**Problem 2: ``console_command()`` picked an invocation that works in
the server's env but not in the spawned shell's.** A dev server started
under a foreign interpreter (miniconda) with ``PYTHONPATH=src`` made the
package importable *there*, so ``console_command()`` picked
``<sys.executable> -m argo_anywhere``. But macOS AppleScript /
iTerm2 / GUI-launched emulators spawn a **fresh login shell** that does
NOT inherit ``PYTHONPATH`` -- so the same command failed with ``No
module named argo_anywhere`` in a window that immediately closed.

**Fix**:

- Reordered the fallback ladder in ``console_command()`` so PATH lookup
  wins over ``-m`` (matches "would this work if I typed it into a fresh
  terminal?").
- Added ``console_command_verified()`` that runs a ``<prefix> --version``
  probe with a **scrubbed env** (``PYTHONPATH`` / ``PYTHONHOME``
  removed) so an invocation that would only succeed under our env leaks
  gets caught HERE rather than in a terminal window.
- ``/api/launch-external`` uses the verified variant + returns 500 with
  a clear diagnostic on probe failure instead of shipping a broken
  command.

**Dev-mode discipline**: use ``--reload`` for source-checkout iteration
(``PYTHONPATH=src python -m argo_anywhere web --port 8800 --reload``).
Do NOT use ``--reload`` for a normal pipx install -- editing package
files under pipx would invalidate the install.

### 2.4c Focus-follow-window discipline for spawned terminals

Added mid-execution 2026-07-13 after the user reported "the new terminal
opens but the browser keeps focus, so I have to Cmd-Tab to see it".

**Two failure modes**, one per platform family:

- **macOS AppleScript path** (``Terminal.app`` / ``iTerm2``): calling
  ``activate`` at the START of the script races window creation against
  the caller (the browser) re-taking focus by the time the script
  returns. Fix: reorder so ``activate`` is the LAST statement in the
  tell-block. Also add ``select newWindow`` (iTerm) /
  ``set index of window 1 of newTab to 1`` (Terminal.app) so the
  RIGHT window becomes frontmost, not just the app.
- **CLI-Popen path** (``alacritty`` / ``kitty`` / ``wezterm`` /
  ``ghostty`` on macOS; the whole Linux catalog): a non-frontmost
  process launching a GUI app on macOS opens the window in the
  background; on X11 Linux the WM's focus-stealing-prevention may
  do the same. Fix: after Popen, call platform-specific best-effort
  raise helpers:
  - **macOS**: ``System Events`` ``set frontmost of (process
    <bundle>) to true``, with a ~120ms sleep first so the window
    exists to raise. Bundle names live in ``_MAC_CLI_BUNDLE_NAMES``.
  - **Linux (X11)**: ``wmctrl -a <label>``. Skipped cleanly on
    Wayland (``XDG_SESSION_TYPE=wayland``): the compositor enforces
    focus-stealing-prevention by design + ``wmctrl`` doesn't work
    there.

**Best-effort contract**: neither helper can fail the launch. If
``osascript`` / ``wmctrl`` isn't installed, if TCC denies Accessibility
permission, if we're on Wayland, if the AppleScript times out -- all
result in a silent no-op. The launch itself still succeeds; the user
just has to Cmd-Tab (or click) to reach the new window.

**Test coverage** (``tests/test_external_terminal.py``, 8 tests):
``activate``-must-be-last invariant pinned for both AppleScript
variants; macOS CLI path triggers the raise helper with the right
term id; Linux CLI path triggers the raise helper with label+pid;
unknown-term-id cleanly no-ops; Wayland cleanly no-ops; missing
``wmctrl`` cleanly no-ops; wmctrl IS called when available; a helper
that raises never breaks the launch.

### 2.4a In-scope safety fix: multi-instance guard

Added mid-execution 2026-07-13 after the user's smoke-test-time question
"what happens if I start a dev web UI while the pipx-managed one is running?".

**Failure modes without the guard**:

1. **Port collision on default 8799** -- hard-fail at uvicorn's ``bind()``.
   Safe (immediate, obvious), but the error text is stack-tracey.
2. **Two instances on different ports** -- both write to the SAME
   ``~/.argo_anywhere/web_state.json``. Not corrupt (atomic writes; last
   write wins), but the user sees MRU / theme flapping.
3. **Two instances each keeping their own** :class:`SessionRegistry` --
   each has NO visibility into the other's Channel. A second instance's
   ``connect`` would collide with the first's SSH mux master on the same
   socket path (per AGENTS.md "MFA-aware by default"). Non-fatal but
   confusing.
4. **Engine-side single-instance** on the compute node (per AGENTS.md's
   ``SCREEN_SESSION="argovproxy"``) would then kick in with its own
   prompts, twice. Potentially destructive.

**Design**: extend ``/healthz`` to identify as argo-anywhere (``app`` +
``pid`` + ``package_version`` + ``app_cwd_short``); add a pre-bind probe in
``_cmd_web`` / ``_cmd_app`` (:func:`argo_anywhere.cli._probe_peer_web`);
refuse to start with a helpful message unless ``--force`` is passed. The
``app`` command additionally opens the incumbent's URL in the browser
(most natural response to "someone else is already running") while still
exiting 1 so scripts see the refusal.

**Downgrade behavior**: pre-D-031 argo-anywhere web servers return
``{"status": "ok"}`` from ``/healthz`` without the marker. The probe
classifies them as ``foreign``, which is the safe outcome ("refuse to
bind, offer the next port"). Users upgrading incrementally get the
right behavior without any coordination.

**Escape hatch**: ``--force`` bypasses the probe. Documented as
"advanced; two instances will share ``web_state.json`` with last-write-
wins semantics; the port bind will still fail if the port is really
busy".

### 2.5 In-scope UX polish: light/dark theme toggle

Added 2026-07-13 as an in-PR enhancement (was not in the original
plan v5; added after design was written down). Rationale: the web
UI is currently hardcoded to dark (`color-scheme: dark` +
hex-literal `--bg` etc. at `index.html:9-27`). Users on daylight
setups or high-brightness screens have no relief. The sibling
`scrollback` project (which we borrowed the launcher-install
pattern from — see `impl_python_webui.md` §"The model borrowed
from scrollback") solved this the same way we will.

**Design.**

- All colors already come from CSS custom properties in the
  `:root` block. Add a second `:root[data-theme="light"]` block
  with a light-mode palette; keep the current values as
  `:root[data-theme="dark"]` (default). Update `color-scheme`
  accordingly so the browser scrollbars + form controls match.
- Add a theme toggle button in the top-bar action row (near the
  existing icon buttons). Icon shows a sun in dark mode and a
  moon in light mode; the click swaps the `data-theme` attribute
  on the `<html>` element and persists the choice to
  `web_state.json` (schema key `theme: "dark" | "light" | "auto"`).
- Default is `auto`: read `prefers-color-scheme` on load and
  apply. Explicit user choice (clicking the button) locks it to
  `dark` or `light` and disables the auto follow-through until
  the user selects `auto` again (third click cycles back to
  `auto`; a small dropdown next to the icon exposes all three
  choices for discoverability).
- xterm.js instances (Channel + Utility) must re-read the theme
  on toggle: `xterm.setOption('theme', ...)` with a background
  matching `--panel` and foreground matching `--ink`. The
  existing `theme: { background: '#0f131b' }` literal at
  `index.html:347` becomes a computed value derived from the
  current CSS variables.

**Schema addition to `web_state.json`.** Extending §4.1:

```json
{
  "version": 1,
  "mru": [...],
  "divider_pct": 50,
  "theme": "auto"
}
```

Value in `{"auto", "dark", "light"}`. Unknown → treated as
`auto`. Written atomically same as the other keys.

**Test additions** (extending §7.1 + §7.4):

- Unit: `web_state.json` round-trips `theme` correctly; invalid
  values default to `auto`.
- Live: toggle button cycles auto → dark → light → auto;
  persists across a full-browser refresh; xterm.js panels
  re-color to match.

**Task order impact.** Slotted as **Task 5.5** (right after MRU
list, since both use `web_state.json`, and both are pure
Python-endpoint + JS work with no engine coupling). Renumbering
downstream tasks is not needed — Task 5.5 is atomic and can be
reviewed independently.

---

## 3. Contract diffs

### 3.1 `PtySession.__init__` (`src/argo_anywhere/driver.py:188`)

New optional kwarg `cwd`:

```python
def __init__(
    self,
    argv: Sequence[str],
    *,
    env: dict[str, str] | None = None,
    dimensions: tuple[int, int] = (24, 80),
    cwd: str | Path | None = None,   # NEW
) -> None:
```

Threaded verbatim into `subprocess.Popen(..., cwd=cwd)`. Blank/None
= inherit process cwd (preserves today's behavior for direct
programmatic callers; the web UI enforces its own "cwd required"
policy above the driver).

### 3.2 `build_launch_argv` (`src/argo_anywhere/web/app.py:51`)

Gains a `cwd` parameter that becomes an engine `--cwd <path>` argv
pair (per D8 bundling). Same validation shape as `--scope`:
resolves absolute path via `_validate_cwd` before the argv is
built.

```python
def build_launch_argv(
    verb: str,
    *,
    cli_tool: str | None = None,
    scope: str | None = None,
    port: int | None = None,
    cwd: str | None = None,           # NEW
) -> list[str]:
```

### 3.3 New endpoints

- `GET /api/mru` → `{"mru": ["/path/a", "/path/b", ...]}`. Reads
  `~/.argo_anywhere/web_state.json`; returns empty on ENOENT.
- `POST /api/mkdir` → body `{"path": "/absolute/path"}`. Runs
  `Path(path).mkdir(parents=True, exist_ok=False)`; returns 201 on
  create, 409 if already exists (defensive; the UI shouldn't call
  it in that case). Validates against forbid-list before creating.
- `GET /api/state` → `{"app_cwd": "/Users/.../argo_anywhere",
  "divider_pct": 50, ...}`. Reads app-cwd + persisted UI state.
- `POST /api/state` → merges the given key/value into
  `web_state.json` atomically. Used for divider position updates.

### 3.4 Modified endpoints

- `POST /ws?verb=X&cwd=/path&scope=...` — `cwd` param honored,
  routes to the panel implied by the verb (Channel for `connect`,
  Utility for `configure`/`setup`/`tunnel`). Returns 1008 close on
  hard-forbid; 409 on missing directory; 403 on `run`/`client` →
  embedded attempt (hard-block per D7a). MRU touched on success.
- `POST /api/launch-external?cwd=/path&...` — `cwd` threaded into
  `open_external_terminal(..., cwd=cwd)`. Same validation.
- `POST /api/run?verb=X` — unchanged shape; `list-tools` / `status`
  / `list-models` continue here per A3.

### 3.5 `SessionRegistry` (`src/argo_anywhere/web/registry.py`)

Instead of a flat registry of `id → ManagedSession`, gains two
named slots + the ephemeral map:

- `channel: ManagedSession | None` — the sole channel-owner
  (`connect`).
- `utility: ManagedSession | None` — the current Utility-panel
  session (ephemeral; replaced freely).
- `_by_id: dict[str, ManagedSession]` — the existing id-keyed map
  (used by `POST /api/sessions/<id>/stop`); the two named slots
  are also present here.

New methods: `register_channel(session)`, `register_utility(session,
replace_existing=True)`, `get_channel()`, `get_utility()`,
`channel_alive() -> bool` (calls `.isalive()`).

### 3.6 Engine `--cwd <path>` flag (`src/argo_anywhere/engine/argo-anywhere.sh`)

Parsed early (with the other global flags), stored in
`ARGO_ANYWHERE_CWD`. Applied via:

```bash
if [ -n "${ARGO_ANYWHERE_CWD:-}" ]; then
  _validate_cwd_or_die "$ARGO_ANYWHERE_CWD" "${_SCOPE_OVERRIDE:-}"
  cd -- "$ARGO_ANYWHERE_CWD" || die "cd to --cwd failed: $ARGO_ANYWHERE_CWD"
fi
```

Where `_validate_cwd_or_die` is the new authoritative forbid-list
function (Section 5). Called before mode dispatch so all verbs run
in the requested directory.

### 3.7 Forbid-list function contract

Shared logical contract; two implementations (bash authoritative,
Python parallel for speed).

- Input: absolute path + intended scope (`project` / `global` /
  empty).
- Output:
  - `ALLOW` — path is fine.
  - `HARD_BLOCK <reason>` — refuse with reason; no override.
  - `SOFT_WARN <reason>` — allowed with explicit user confirmation.
- Scope-conditional: `global` scope always returns `ALLOW` (no dir
  restrictions per D6a). `project` scope runs the full check.

Forbid-list source of truth (see Section 5 for the enumerated
list).

---

## 4. Data schemas

### 4.1 `~/.argo_anywhere/web_state.json`

Atomic writes (`tempfile.NamedTemporaryFile(dir=...)` + `os.replace`).
Versioned schema so we can migrate later:

```json
{
  "version": 1,
  "mru": [
    "/Users/attia/projects/foo",
    "/Users/attia/projects/bar"
  ],
  "divider_pct": 50
}
```

- `version`: integer, currently `1`. Bumped on any breaking schema
  change. Reader upgrades in-place; unknown versions log a warning
  and reset to defaults.
- `mru`: LIFO list of absolute paths; capped at 10. Duplicates
  removed on insert. Non-existent paths are pruned lazily on read
  (a path that used to exist but was rm'd doesn't get offered but
  isn't loudly complained about).
- `divider_pct`: integer 25–75 (matches the min/max limit).
  Defaults to 50.

### 4.2 MRU touch policy

An entry is prepended to `mru` on the first successful **launch**
(engine spawned, no validation error) with that cwd. Not on load,
not on validation. Rationale: MRU should reflect where the user
actually ran things, not typos.

---

## 5. Forbid-list source of truth

Applied only when scope is `project`. Order: hard-block first
(A7), soft-warn second.

### 5.1 Hard-block (400, no override)

- `$HOME` exact match (would litter dotfiles in home).
- `/`, `/bin`, `/sbin`, `/usr`, `/etc`, `/var`, `/opt`, `/tmp`,
  `/var/tmp`.
- macOS additions: `/System`, `/Library`, `/private`.
- Any ancestor-of-`$HOME` above `/Users` on macOS is a system dir
  by construction (already covered by the list above).
- `.expanduser().resolve()` is applied to the user input before the
  match so `~` and symlinks don't sneak past.

### 5.2 Soft-warn + confirm

Applied when the dir has NEITHER a `.git` subdirectory NOR any of
these project markers:

- `pyproject.toml`
- `setup.py`
- `package.json`
- `Cargo.toml`
- `Makefile`
- `go.mod`
- `CMakeLists.txt`
- `pom.xml`
- `build.gradle`
- Any existing tool config already present:
  `opencode.json` / `.claude/settings.local.json` / `.aider.conf.yml`
  (if these exist, the user has clearly chosen this dir before).

Wording of the confirm modal:

> This directory has no `.git` and no obvious project marker.
> `project` scope will write `<config-basename>` here. If you want
> the tool to just chat without writing to the current directory,
> use `global` scope instead. Continue with `project`?

### 5.3 Where the list lives

- Authoritative: `argo-anywhere.sh` function
  `_scope_project_forbid_dirs()` returns the list; the engine's
  `_validate_cwd_or_die` applies it. Called from the `--cwd`
  handler AND from `_opencode_check_conflicts` /
  `_aider_check_conflicts` / `_claudecode_check_conflicts` so
  CLI-only users get identical protection.
- Python parallel: `src/argo_anywhere/web/forbid.py` (new file) with
  a `PROJECT_SCOPE_FORBID` frozenset + `check(path, scope) -> Verdict`
  function. Tested against the bash list via a shared fixture (a
  test spawns the bash function via `subprocess.run` and compares
  its output against the Python one on the same input set).

---

## 6. UI wording + layout

### 6.1 Launcher popover — full row-by-row shape

```
┌ Launch                                                             ┐
│ [ command ▼]                    [ cli tool ▼ ]                     │
│ [ scope   ▼]                    [ where to run ▼ ]                 │
│ [ working directory _____________________________ ] [Browse]       │
│    (hint: the tool will start in this directory)                   │
│                                                                    │
│                        [Launch]   [Cancel]                         │
└────────────────────────────────────────────────────────────────────┘
```

- **command** dropdown values (post-A2 removal of `client`):
  `run`, `connect`, `configure`, `setup`, `tunnel`.
- **scope** dropdown values: `— auto —`, `global`, `project`.
  Default per D6c: `— auto —` unless cwd == `$HOME`, in which case
  pre-select `global`.
- **where to run** dropdown values (per D7c):
  - For `connect` / `configure` / `setup` / `tunnel`: only
    `In-browser terminal (routed to Channel or Utility automatically)`.
  - For `run`: only the detected external terminals, labeled e.g.
    `Terminal.app (recommended for run)` / `iTerm2 (recommended
    for run)`.
- **Browse**: visible only when the client is pywebview
  (detected via a `window.pywebview` sniff on page load). Hidden
  otherwise.

### 6.2 App-cwd status strip (per D3a)

New strip immediately below the top nav bar:

```
argo-anywhere · running from ~/.argo_anywhere
```

The `~/.argo_anywhere` collapses `$HOME` to `~` for readability.
Also duplicated in About popover (`aboutBackdrop`) as a `<dt>/<dd>`
row.

### 6.3 Dual-panel layout (per D7d + D7g + D7h)

The existing embedded-terminal container (a single xterm.js
instance) becomes:

```
┌ Terminals                                        [Terminal] [Hide] ┐
│ ┌ Channel · connect ────────┬ Utility · configure/setup/tunnel ──┐ │
│ │                           │                                    │ │
│ │  (persistent panel)       │  (ephemeral panel)                 │ │
│ │                           │                                    │ │
│ │                           │                                    │ │
│ └───────────────────────────┴────────────────────────────────────┘ │
│                       ← draggable divider →                        │
└────────────────────────────────────────────────────────────────────┘
```

- Divider: draggable, min 25% / max 75% per panel width, persisted
  as `divider_pct` in `web_state.json`.
- `[Terminal]` and `[Hide]` buttons act on the container (both
  panels show or hide together) — no per-panel toggle in v1.
- Panel headers show the current session state:
  `Channel · connect (running)` / `Channel · idle` /
  `Utility · configure (opencode, project) (running)` / `Utility · idle`.

### 6.4 Confirmation modals

Two new confirm-modal flows, both reusing `confirmBackdrop`
(`index.html:328`):

- **Missing directory** (per D2c / D4):
  Title: "Directory does not exist".
  Body: "Create `<path>` and start the tool there? This will
  `mkdir -p` the path."
  Buttons: `Create + Launch` (primary) / `Cancel`.
- **Soft-warn project scope** (per D6a):
  Title: "No project marker detected".
  Body: (per Section 5.2 wording).
  Buttons: `Continue with project` / `Switch to global` /
  `Cancel`.

---

## 7. Test plan

### 7.1 Unit tests (new)

- `tests/test_driver_cwd.py`:
  - `PtySession(argv=["-c", "pwd"], cwd="/tmp")` writes `/tmp` to
    the PTY.
  - `PtySession(argv=..., cwd=None)` inherits process cwd (proves
    backward compat).
- `tests/test_web_validate_cwd.py`:
  - Absolute path OK.
  - Relative path rejected.
  - `~/foo` expands + accepted if exists.
  - Non-existent dir → returns "missing" verdict (server sends 409).
  - File (not dir) → rejected.
  - Symlink to dir → accepted, resolved to target.
- `tests/test_web_forbid.py`:
  - `$HOME` + `project` → HARD_BLOCK.
  - `$HOME` + `global` → ALLOW.
  - `/etc` + `project` → HARD_BLOCK.
  - `/tmp/foo` + `project` → HARD_BLOCK (`/tmp` prefix; even
    `/tmp/something-nested` is under a forbidden root; TBD in
    implementation — clarify: forbid-list matches EXACT path only,
    not prefix, so `/tmp/foo` is allowed but `/tmp` itself is not.
    Confirmed here to match user's intent; adjust in unit-tests
    if design shifts.) Actually: **re-reading D6a intent**: the
    hard-block list is EXACT match. `/tmp` (the dir itself) is
    forbidden; `/tmp/foo` is allowed but likely fires soft-warn.
    Documented here for the executor.
  - `~/projects/foo` (has `.git`) + `project` → ALLOW.
  - `~/projects/bar` (no marker) + `project` → SOFT_WARN.
- `tests/test_web_state.py`:
  - Read/write round-trip preserves schema.
  - Atomic write survives concurrent access simulation.
  - MRU cap at 10; duplicate prepend deduplicates.
  - Unknown version → defaults + warning.
- `tests/test_web_launch_argv.py` (extends existing):
  - `build_launch_argv(cwd="/path")` includes `--cwd /path`.
  - Rejects blank / relative / non-existent cwd.

### 7.2 Endpoint tests (new)

- `tests/test_web_app.py` (extends existing):
  - `/ws?verb=run&cwd=...` with `run` → 403 (hard-block per D7a).
  - `/ws?verb=connect&cwd=/nonexistent` → 409 (missing dir).
  - `POST /api/mkdir {"path": "/nonexistent"}` → 201 + dir exists
    after.
  - `POST /api/mkdir {"path": "/etc"}` → 400 (forbid-list).
  - `GET /api/mru` → empty on fresh state; populated after a
    successful launch.
  - `GET /api/state` → contains `app_cwd`.
  - `POST /api/state {"divider_pct": 60}` → persisted.
  - Reattach test (per A8): with Channel session alive, second ws
    connection re-uses the existing Channel session; second
    Utility connection replaces the previous Utility session.

### 7.3 Engine tests (new)

- `bash -n argo-anywhere.sh` (existing).
- `bash argo-anywhere.sh --cwd /tmp/foo connect 2>&1 | head` (with a
  fake /tmp/foo) — cd's before mode dispatch; smoke check.
- `bash argo-anywhere.sh --cwd $HOME --scope project client
  --cli-tool opencode` — refuses with forbid-list error.
- `bash argo-anywhere.sh --cwd /some/project --scope project run
  --cli-tool opencode` — writes `opencode.json` at
  `/some/project/opencode.json` (verified by inspecting output +
  file after).

### 7.4 Live-verification (append to `docs/TESTING.md`)

To be exercised in a real session before merge (per project's live-
test-gate discipline):

- [ ] Both panels render on dashboard load.
- [ ] Verb → panel routing works (`connect` → Channel; `configure`
      → Utility).
- [ ] Container hide/show button hides/shows both panels together.
- [ ] Channel survives ws-close (simulate: reload browser); on
      reload, Utility can run `status` without a repeat Duo.
- [ ] cwd input pre-fills with `$HOME` on first-ever run.
- [ ] cwd input pre-fills with MRU top entry on second run.
- [ ] Browse button visible in pywebview build, hidden in browser.
- [ ] Missing path → 409 → confirm modal → Create + Launch →
      succeeds; Cancel → no-op.
- [ ] Hard-block `run` → embedded (UI disabled + curl to `/ws`
      rejected).
- [ ] Hard-block `project` scope + `$HOME` (web returns 400 with
      clear message).
- [ ] Hard-block `project` scope + `$HOME` (CLI: `argo-anywhere
      --cwd $HOME --scope project run` refuses).
- [ ] Soft-warn `project` scope + no-marker dir (confirm modal,
      respected).
- [ ] cwd == `$HOME` → scope dropdown pre-selects `global`.
- [ ] cwd change to `.git` dir → scope dropdown does NOT auto-switch
      to `project` (one-directional nudge).
- [ ] Engine `--cwd /path --scope project client --cli-tool
      opencode` writes `opencode.json` at resolved project root.
- [ ] MRU list caps at 10 after 11 distinct launches.
- [ ] Divider drag persists across full-browser refresh.
- [ ] pywebview app cwd shown in launcher header AND About popover;
      strings match.
- [ ] Configure-in-Utility with no Channel active → clear error
      message directing user to `connect` first (per A4).
- [ ] Full existing pytest suite (133 tests) + new tests all green.

---

## 8. Execution task order

Same as PR structure. Each task lands in a coherent state (i.e.
after each task `pytest` is green + `bash -n` clean).

1. **Two-panel split**: UI (dual xterm.js instances + resizable
   divider) + `SessionRegistry` gains Channel/Utility named slots
   + `/ws` routing per verb. Baseline behavior: no cwd field yet.
2. **pywebview app cwd → `~/.argo_anywhere/`**: `mkdir -p` before
   `os.chdir`; strip in launcher header + About popover row.
3. **cwd input + Browse + validation**: text field + browse
   handler (pywebview only) + client + server validation +
   409-then-confirm modal.
4. **cwd threading**: `PtySession(cwd=)` + `open_external_terminal
   (cwd=)` + `build_launch_argv(cwd=)` → engine `--cwd`.
5. **MRU list**: `GET`/`POST /api/mru` (or `/api/state`) + JS
   datalist + touch on successful launch + pre-fill logic.
5.5 **Light/dark theme toggle** (§2.5): light-mode CSS palette
   + top-bar toggle button + `theme` key in `web_state.json` +
   xterm.js re-color on toggle. Independent of scope/cwd work;
   slotted here because it shares `web_state.json` with Task 5.
6. **Scope `<select>`**: replace `<input>` at `index.html:285` +
   cwd-aware default (cwd == `$HOME` → pre-select `global`).
7. **Forbid-list**: `web/forbid.py` + bash
   `_scope_project_forbid_dirs` + `_validate_cwd_or_die` +
   soft-warn confirm modal wiring.
8. **Engine `--cwd` flag**: CLI parser arm + `cd` + forbid-list
   call + help-text update + updated flag table in PLAN.md.
9. **AGENTS.md scope-coupling rule**: add per-project rule
   coupling engine scope-value changes to UI updates (paired with
   Task 6 in the same commit ideally, but doc-only so can slot
   anywhere).
10. **Tests**: all unit + endpoint + engine tests from Section 7.
11. **Docs**: `README.md` web-UI section refresh; `docs/UPGRADING.md`
    one-liner "web UI: launching a tool now requires picking a
    working directory; blank is no longer accepted"; refresh
    screenshots via `scripts/screenshots.py` (may defer to v3.1.0
    release cycle).

---

## 9. Blast-radius map

**Substantive changes:**

- `src/argo_anywhere/web/static/index.html` (dual-panel layout, new
  fields, confirm modals, app-cwd strip).
- `src/argo_anywhere/web/static/` (may extract JS to a file if the
  inline block grows unwieldy).
- `src/argo_anywhere/web/app.py` (new endpoints; `_validate_cwd`;
  ws routing; hard-blocks; cwd threading).
- `src/argo_anywhere/web/registry.py` (named slots).
- `src/argo_anywhere/web/forbid.py` (**new file**; Python
  forbid-list).
- `src/argo_anywhere/web/state.py` (**new file**; `web_state.json`
  reader/writer with atomic write + schema versioning).
- `src/argo_anywhere/driver.py` (`PtySession(cwd=)`).
- `src/argo_anywhere/cli.py` (`_cmd_app` cwd change +
  `mkdir -p ~/.argo_anywhere/`).
- `src/argo_anywhere/launcher.py` (desktop entry + .app runner cd
  before spawn).
- `src/argo_anywhere/engine/argo-anywhere.sh` (`--cwd` flag +
  `_validate_cwd_or_die` + `_scope_project_forbid_dirs`).
- `AGENTS.md` (project overrides section: engine-UI scope coupling
  rule).
- `PLAN.md` (D-031 entry + flag-table update).
- `README.md` (web-UI section refresh).
- `docs/UPGRADING.md` (one-liner).
- `docs/TESTING.md` (live-verification scenarios per Section 7.4).
- `notes/impl_launcher_cwd.md` (this file).
- `notes/README.md` (index row for this note).

**Audited unchanged:**

- `src/argo_anywhere/web/pty_bridge.py` (per-session; already
  correct).
- `src/argo_anywhere/external_terminal.py` (already accepts `cwd=`;
  just plumbing).
- `src/argo_anywhere/status.py`, `footprint.py`, `_engine.py`.

**Test suite**: existing 133 tests must stay green; new tests
per Section 7.

---

## 10. Migration notes

- **Behavior change**: the web UI's launcher now REQUIRES a cwd
  value. Blank is no longer accepted (previous behavior:
  silently inherited server cwd). Documented in
  `docs/UPGRADING.md`.
- **Behavior change**: `client` is removed from the web-UI verb
  dropdown. CLI users see no change (`client` still works).
  Documented in `docs/UPGRADING.md`.
- **New dependency**: none. Uses stdlib
  (`pathlib`, `tempfile`, `os.replace`).
- **New state**: `~/.argo_anywhere/web_state.json` (small; auto-
  created; safely deleted at any time — regenerates on next launch
  with defaults).
- **Backward compat**: engine `--cwd` is optional; existing scripts
  and CLI invocations that don't pass it are unaffected.
  `PtySession(cwd=None)` matches today's behavior for programmatic
  callers.

---

## 11. Provenance

- **Design conversation**: 2026-07-13, 5 planning rounds + 1 audit
  pass, all captured in the session log. Locked decisions in
  Section 2.2; audit refinements in Section 2.3.
- **Decision ID**: D-031 (see `PLAN.md`).
- **Related decisions**: D-017/D-018/D-019 (scope framework), D-020
  (port-as-transport-state), D-021 (cross-client coherence), D-024
  (connect/configure/run split), D-026..D-030 (Python-package + web
  UI). This PR is the natural next step of D-026's web-UI story.
- **Related audit findings**: none new; this closes no
  outstanding audit item (all currently-open items are documented
  no-fix or upstream-blocked).

---

*Created 2026-07-13 by Ahmed Attia (with substantial AI assistance
from Claude per `CONTRIBUTORS.md`). Archive to
`_archive/impl_launcher_cwd.md` after execution completes + the
PR merges + one release cycle passes; update
`notes/_archive/INDEX.md` and leave a stub here pointing at the
archive.*
