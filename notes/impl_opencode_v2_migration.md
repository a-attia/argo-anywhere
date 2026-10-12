# Implementation plan — OpenCode 2 config-name migration (+ client upgrade audit)

**Status**: shipped in v3.5.0 (2026-10-12); live-verified by the maintainer
on OpenCode 2.0.27 the same day (`configure` migrated the real config; all
argo models visible after the service restart). Open questions resolved per
the recommendations ([§8](#8-open-questions)). Q6 resolved 2026-10-12
without a live test (see §8); on `main` after v3.5.0.
**Owner**: Ahmed Attia. **Last updated**: 2026-10-12.
**Target release**: v3.5.0 (engine `SCRIPT_VERSION` 2.5.0 → 2.6.0).
**Earns**: D-036 (recorded in `PLAN.md`).

This note plans the fix for a field breakage. After an OpenCode upgrade to
2.x, no `argo/` models appear, because argo-anywhere writes the global
OpenCode config under a filename OpenCode 2 no longer reads. It also
records the matching check of the other two supported clients (Claude Code,
aider), so that the next release covers every client-upgrade breakage we
know of, not only the one that was reported.

## Contents

1. [Headline](#1-headline)
2. [What broke, measured](#2-what-broke-measured)
3. [Other clients](#3-other-clients)
4. [Design](#4-design)
5. [Touchpoints](#5-touchpoints)
6. [Tests](#6-tests)
7. [Release + docs](#7-release--docs)
8. [Open questions](#8-open-questions)

## 1. Headline

- **Cause.** OpenCode 2 reads `~/.config/opencode/opencode.json(c)` only.
  We write `~/.config/opencode/config.json`, which OpenCode 1 accepted and
  OpenCode 2 silently ignores. The engine comment at
  `src/argo_anywhere/engine/argo-anywhere.sh:416-421` anticipated exactly
  this ("a real-world report of the rename biting can flip the global path
  with a one-shot migration").
- **The format is fine.** Our v1-shaped provider block loads under OpenCode
  2.0.27 with all 34 models and no warnings once the file has the right
  name. A rename plus migration fixes it; no rewrite to the v2-native format
  is needed for this release.
- **Second trap.** OpenCode 2 runs a background service that caches config
  per directory. Renaming the file does nothing visible until that service
  restarts, so the migration has to handle the restart.
- **Migrate eagerly, regardless of OpenCode version.** OpenCode 1 also
  accepts `opencode.json`, so renaming on *every* install, including users
  still on 1.x, turns their later OpenCode upgrade into a non-event. That
  is the "migrate automatically when they install new versions of
  OpenCode" property: the fix lands before the upgrade does.
- **Claude Code and aider: no breakage found** (details in [§3](#3-other-clients)).

## 2. What broke, measured

All measurements were taken on the maintainer's laptop on 2026-10-12 with
OpenCode `v2.0.27`. None of them contacted ANL.

| Probe | Result | What it shows |
|:---|:---|:---|
| `opencode debug config` with only `config.json` present | lists two *directories*, no file source | v2 does not load `config.json` |
| `opencode models` (real setup) | 0 `argo/` models | the user-visible symptom |
| scratch project with our file copied to `opencode.json`, `opencode models --standalone` | 34 `argo/` models, no warnings | v1 provider shape is normalized in memory |
| scratch dir queried via service *before* adding `opencode.json`, then again after | 0, then 0 | the service caches per-directory config |
| fresh scratch dir with `opencode.json` present before first query | 34 | the service *can* read it; only the cache is stale |

The v2 migration guide ([opencode.ai/v2/docs/migrate-v1](https://opencode.ai/v2/docs/migrate-v1/),
the official V1→V2 guide) lists the global locations as
`~/.config/opencode/opencode.json(c)`, `<project>/opencode.json(c)` and
`<project>/.opencode/opencode.json(c)`, and never mentions `config.json`.
It also documents the native v2 provider shape (`provider` → `providers`,
`npm` → `package` with an `aisdk:` prefix, `options` split into
`settings`/`headers`/`body`, model `id` → `modelID`). It states that v1
syntax "remains quiet by itself", which matches the measurement above.

Other v2 changes that do not affect us: the plugin API, server/client API
contracts, and TUI settings moving from `tui.json` to a global `cli.json`
(that is the new `cli.json` + `service.json` that appeared in
`~/.config/opencode/` on upgrade).

Project scope is unaffected. It already writes `<git-root>/opencode.json`
(`OPENCODE_PROJECT_CONFIG_BASENAME`, engine line 424).

## 3. Other clients

Each supported client was checked against its current upstream state.

| Client | Installed (2026-10-12) | Upstream state | Verdict |
|:---|:---|:---|:---|
| OpenCode | 2.0.27 | 2.x; config-name break above | **broken → this plan** |
| Claude Code | 2.1.296 | `env.ANTHROPIC_BASE_URL` + `env.ANTHROPIC_API_KEY` in `settings.json` still the documented mechanism | no break found |
| aider | 0.86.2 | 0.86.2 is the latest release (PyPI, 2026-02-12); no release since | no break possible from upgrading |

**Claude Code** caveats. Third-party changelog aggregators
([claudelog.com](https://claudelog.com/claude-code-changelog/),
[gradually.ai](https://www.gradually.ai/en/changelogs/claude-code/)) report
that versions **2.1.265–2.1.267** failed every turn against third-party
`ANTHROPIC_BASE_URL` endpoints, fixed in 2.1.268/2.1.269. That window is
closed, but a user pinned inside it would see argo "break". It is worth one
line in `docs/LIMITATIONS.md` and is not worth engine code. Two newer
names appear in the same changelogs: `CLAUDE_CODE_USE_GATEWAY`, and the
"gateway" framing of `ANTHROPIC_AUTH_TOKEN`. Neither changes what we write.
`CLAUDE_CODE_USE_GATEWAY` is a candidate for
`claudecode_shadowing_env_vars` only if live testing shows it reroutes
requests (see [Q6](#8-open-questions)). Not verified end-to-end, because
that needs a live channel.

**aider** is effectively dormant upstream (no release in eight months). The
risk is not breakage; it is a dormant upstream drifting from new Argo
models. Our `.aider.model.settings.yml` union with `/v1/models` already
covers new models. No action.

## 4. Design

The migration is one idempotent helper, run from every verb that writes
OpenCode config. Every verb that only reads the config falls back to the
old name instead.

### 4.1 Target name

`OPENCODE_GLOBAL_CONFIG` becomes `~/.config/opencode/opencode.json`,
unconditionally. There is no version gate at write time: both OpenCode
majors read it, and a version-dependent path would itself be a drift
source.

### 4.2 `_migrate_opencode_global_config_name` (new, engine)

The helper is idempotent and best-effort. It never `die`s, because it runs
ahead of the user's real work. Case table:

| `config.json` | `opencode.json` | Action |
|:---|:---|:---|
| absent | any | no-op |
| present, regular file | absent | atomic `mv` to `opencode.json`; leave a `config.json` → `opencode.json` symlink (see Q2); rename manifest key ([§4.4](#44-manifest--backups)); notice |
| symlink to `opencode.json` | present | no-op (already migrated, or the user's own workaround) |
| present, no `provider.argo` | present | leave both; `config.json` is not ours. Info line only |
| present, has `provider.argo` | present | key-wise union into `opencode.json` (existing `opencode.json` values win; `provider.argo.models` unioned per the NO-SILENT-MODEL-DELETION invariant); move `config.json` to `config.json.migrated.<ts>`; notice lists any keys not carried over |
| any | `opencode.jsonc` present | **do not touch**: we cannot rewrite JSONC without destroying comments. Warn with the exact manual step; writer refuses global scope until resolved (Q3) |

The notice is printed once per run, and it states plainly that OpenCode 2
ignores the old name. The message must not suggest the user did something
wrong.

### 4.3 When it runs

| Verb | Behaviour |
|:---|:---|
| `client`, `setup`, `configure`, `run` (opencode) | migrate before `opencode_pick_scope` |
| `update-models` | migrate first (it rewrites the file anyway) |
| `update opencode` | migrate after a successful upgrade; also verify the updater still works against a v2 install (the v2 curl installer lands in `~/.opencode/bin`; v2 ships its own `opencode upgrade`, and the `sst/tap/opencode` brew tap's v2 status is unverified) |
| `status`, `list-models`, `enumerate_client_ports`, `clean --dry-run`, web UI `/api/status` | **read-only**: resolve `opencode.json` then fall back to `config.json`; when only the legacy name exists *and* OpenCode is ≥ 2, show a red row: "OpenCode 2 cannot see this file — run `argo-anywhere configure --cli-tool opencode`" |
| `uninstall --restore-configs` | migrate-aware restore ([§4.4](#44-manifest--backups)) |

Read-only verbs do not mutate files. That keeps `status` honest (same
principle as D-034: report what is, do not fix silently). It also keeps the
web UI's `status.py` free of writes.

How the "automatic" requirement is met:

- **Upgrading argo-anywhere then OpenCode**: the first mutating verb after
  the argo-anywhere upgrade migrates the file. The later OpenCode upgrade
  finds `opencode.json` already in place.
- **Upgrading OpenCode first (the reported case)**: the user's next
  `configure` or `run` migrates. Until then, `status` and the web UI name
  the problem and the one command that fixes it.
- **Not covered**: a user who upgrades OpenCode and never runs
  argo-anywhere again. Nothing can fix that from our side. The
  `CHANGELOG`/`UPGRADING` entry and the symlink workaround are the
  mitigation.

### 4.4 Manifest + backups

`_manifest_configs_to_restore` (engine ~11098) finds backups by
`<path>.bak.*`. A renamed path orphans every pre-migration backup. The
migration therefore:

1. Renames the manifest key `…/config.json` → `…/opencode.json`, keeping
   `created_by_us` and the original timestamp. First-touch-wins still
   holds, because this is the same file.
2. Records `legacy_path: …/config.json` on the entry, so that restore
   searches `config.json.bak.*` as well as `opencode.json.bak.*`.
3. Leaves existing `config.json.bak.*` files where they are and does not
   rename them. `clean` enumerates both glob families.

Restore writes to `opencode.json`, the name OpenCode reads, and removes our
compatibility symlink. If the original was `created_by_us`, delete both.

### 4.5 Background service restart

After a migration that changed the file, if `opencode service status`
succeeds:

- **TTY**: offer `[r]estart now / [l]ater`. Restarting interrupts open
  OpenCode sessions, so this is not done silently.
- **Non-TTY** (web UI `configure`, `-y`): do not restart. Print
  "restart OpenCode (`opencode service restart`) to load the argo models".

The same restart hint should follow *every* opencode `configure` on v2, not
only migrations. Any config change has the same cache problem (model list
updates from `update-models` included).

### 4.6 What we deliberately do not do

- **Write the v2-native format.** v1 syntax works on both majors today, and
  a v2-only writer would break users still on 1.x. Revisit when OpenCode
  deprecates v1 syntax. Add a watch item: `WATCH-OC-1: v1 provider syntax
  warning or removal`.
- **Gate on OpenCode version at write time.** See [§4.1](#41-target-name).
  The version probe (`opencode --version` → `v2.0.27`) is used only to
  word messages.

## 5. Touchpoints

The path is hard-coded at about 24 engine sites (grep `OPENCODE_CONFIG\b`
or `OPENCODE_GLOBAL_CONFIG` plus literal `opencode/config.json` in help
text; count as of 2026-10-12). They fall into these groups:

| Group | Sites (engine lines, 2026-10-12) | Change |
|:---|:---|:---|
| Constant | 422-423 + comment 412-421 | new name; comment records this incident |
| Writer + scope picker | 3798, 3967-4047 | via resolver; conflict text updated |
| Port readers / coherence | 1452, 1535, 7258 | read-only resolver (new then legacy) |
| `update-models` + model listing | 8839, 9157-9249, 9533 | migrate, then new path |
| `status` card / summaries | 9788, 9853 | legacy-name warning row |
| `clean` | 11356, 11407-11408, 11499 | both names + both `.bak.*` families |
| Help text | 11791-11904, 12052-12187 | new name |
| **Python mirror** | `src/argo_anywhere/status.py:343` `_TOOL_CONFIGS` | candidate list `[opencode.json, config.json]`, plus a `legacy_name` flag surfaced in `/api/status` |

The `status.py` change is a **coupled surface** (CLAUDE.md "Engine ↔ web-UI
coupling rules", client-port enumeration). It lands in the same commit as
the engine resolver.

## 6. Tests

Python (pytest, no ANL infra). Engine behaviour is driven through
subprocess with a sandboxed `$HOME`, the same pattern as the existing
engine-invariant tests:

- One test per row of the [§4.2](#42-_migrate_opencode_global_config_name-new-engine)
  case table, including JSONC refusal and idempotence on a second run.
- No model is ever dropped across a both-present merge (extends
  `tests/test_engine_opencode_models.py`).
- Manifest key rename, plus restore that finds a pre-migration
  `config.json.bak.*`.
- `status`/`enumerate_client_ports` read the legacy name without mutating it.
- `status.py` resolver parity with the engine (extend
  `test_client_tool_configs_covers_every_supported_tool`).
- `clean --dry-run` lists both backup families.

Live (maintainer, `docs/TESTING.md`): fresh v2 install from 1.x-era config,
then `configure --cli-tool opencode`, then models visible after service
restart; same on a 1.x install (still works after rename); web UI shows the
legacy-name row before `configure` and clears after. Claude Code smoke on
2.1.296 for [Q6](#8-open-questions).

## 7. Release + docs

- `CHANGELOG.md` v3.5.0: lead with the user-visible line "OpenCode 2 shows
  no argo models — fixed; run `argo-anywhere configure --cli-tool opencode`
  once". Include the one-line manual workaround for users who cannot
  upgrade yet:
  `ln -s config.json ~/.config/opencode/opencode.json && opencode service restart`.
- `docs/UPGRADING.md`: a routed entry for "upgraded OpenCode to 2.x".
- `docs/LIMITATIONS.md`: the OpenCode 2 service-cache behaviour, and the
  Claude Code 2.1.265–2.1.267 regression window.
- `README.md`, `CLAUDE.md` project facts, `PLAN.md`: path references plus
  a D-036 record.
- `notes/README.md` index row (added with this note).

## 8. Open questions

**Resolved 2026-10-12**: the maintainer accepted every recommendation below.
Q1–Q5 are implemented as recommended.

**Q6 resolved 2026-10-12, reframed.** The official environment-variable
reference ([code.claude.com/docs/en/env-vars](https://code.claude.com/docs/en/env-vars))
does not document `CLAUDE_CODE_USE_GATEWAY` at all; only a community gist
mentions it, and marks itself unverified. It stays off the list. The real gap
was elsewhere: the documented provider switches had grown from
`CLAUDE_CODE_USE_BEDROCK` + `_VERTEX` (both already listed) to five.
`_FOUNDRY`, `_ANTHROPIC_AWS` and `_MANTLE` were added to
`claudecode_shadowing_env_vars`, by the same reasoning that listed Bedrock
and Vertex. No live channel was needed.

Implementation notes that differ from the plan text above:

- The web UI's Fix… button pre-fills the launcher (`configure`, tool
  `opencode`, scope `global`) rather than launching directly, so that the
  user still presses Launch and the cwd check still applies.
- The `status` card also changes its "next step" line to the `configure`
  command when only the old name exists. Otherwise it said "Run 'opencode'"
  directly under the warning that OpenCode cannot see the file.
- The restart prompt honours `-y` (`UPDATE_ASSUME_YES`) as "do not restart",
  the safe choice.

1. **D-number.** Does this earn D-036, or is it an amendment to D-017/D-018
   (scope paths)? Recommendation: D-036, because it changes a persisted
   path and the manifest contract.
2. **Compatibility symlink.** Leave `config.json → opencode.json` after
   migrating? It keeps third-party scripts and older argo-anywhere installs
   working. The cost is that 1.x might load the same file twice (harmless,
   identical content). Recommendation: yes, and remove it on uninstall.
3. **JSONC.** Refuse global scope when `opencode.jsonc` exists, or write
   our provider into a separate `opencode.json` and let OpenCode merge?
   Recommendation: refuse with instructions in this release, because OpenCode's
   merge precedence between the two is undocumented.
4. **Service restart default** in TTY mode: default `[l]ater` (safe) or
   `[r]estart` (does what the user wants)? Recommendation: `[r]` when no
   OpenCode session is active, `[l]` otherwise, if the service exposes that;
   otherwise `[l]`.
5. **Web UI.** Should the legacy-name red row carry a "Fix" button that runs
   `configure` in the Utility panel? Recommendation: yes. It reuses an
   existing verb, so no new write path enters `status.py`.
6. **`CLAUDE_CODE_USE_GATEWAY`.** Add it to `claudecode_shadowing_env_vars`?
   It needs a live check of whether it changes routing when
   `ANTHROPIC_BASE_URL` is set. Recommendation: test in the v3.5.0 live
   pass and add it only if it reroutes.

---

*Created 2026-10-12 by Ahmed Attia (with substantial AI assistance from
Claude per [`CONTRIBUTORS.md`](../CONTRIBUTORS.md)).*
