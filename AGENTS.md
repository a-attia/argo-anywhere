# argo-anywhere / AGENTS.md

This project loads shared workflow conventions from the
[scicomp-research-skills](https://github.com/a-attia/scicomp-research-skills)
repository. Before doing anything else, the consuming agent should:

1. Verify `~/.scicomp-research-skills/AGENTS.md` exists and is no more
   than 30 days stale (per its modification time). If stale, print a
   reminder suggesting `~/.scicomp-research-skills/bin/refresh.sh` and
   proceed anyway.
2. Read `~/.scicomp-research-skills/AGENTS.md`.
3. Read any skill files referenced below from
   `~/.scicomp-research-skills/skills/<name>/SKILL.md`.
4. Then read the rest of THIS file.
5. Then read `PLAN.md` for the active plan-of-record.

## Skills to load for this project

This project is a `software-script-collection` (one large bash script
plus supporting docs) — not a `software-library`. Load lightly:

- `~/.scicomp-research-skills/skills/agent-resource-discipline/SKILL.md`
  — **always load**. First-action / last-action protocols give the
  agent persistent memory across sessions via this project's indices
  (`PLAN.md` status, `notes/README.md`, `notes/agent_feedback.md`,
  `docs/AUDIT_2026-05-12.md`).
- `~/.scicomp-research-skills/skills/human-facing-doc-authoring/SKILL.md`
  — **load whenever authoring or revising a human-facing doc**:
  `README.md`, `PLAN.md`, `notes/agent_feedback.md`,
  `docs/TESTING.md`, `notes/test_plan_phase*.md`.

### Available but not loaded by default

The following skills are available and load on demand for specific
non-routine tasks; do NOT load them at session start unless the user
asks for the matching task.

- `~/.scicomp-research-skills/skills/research-software-engineering/SKILL.md`
  — **on-demand only** for this project. The skill is oriented toward
  numerical-software libraries (MMS / convergence-rate tests / "paper
  tests" guard / `experiments/<run-id>/` discipline). This project is a
  bash orchestrator with no numerical computation, no library API, and
  no experiments directory. Load if the user explicitly asks about
  testing strategy or numerical-correctness review of any future
  Python heredoc that grows non-trivial.
- `~/.scicomp-research-skills/skills/literature-survey/SKILL.md`
  — only load if the user is adding algorithmic references this project
  cites (none today; the project's "references" are upstream tool
  documentation, not academic literature).
- `~/.scicomp-research-skills/skills/research-paper-writing/SKILL.md`
  — N/A; project doesn't support a paper.
- `~/.scicomp-research-skills/skills/project-onboarding/SKILL.md`
  — only relevant for adopting the framework or migrating to a
  different framework structure; was used during the initial onboarding
  on 2026-05-14 and won't recur in routine work.

The two always-load skills (`agent-resource-discipline` +
`human-facing-doc-authoring`) compose freely; this is the steady-state
loading set for normal sessions.

---

## Project facts

- **Name**: argo-anywhere
- **Nature**: research-software (CLI orchestrator). **As of v3.0.0 a
  Python package** (`src/argo_anywhere/`) that owns the runtime and
  vendors the bash **engine** (`argo-anywhere.sh`, ~5800 lines, inline
  Python heredocs for structured-data work) VERBATIM as package data,
  plus a loopback-only FastAPI web UI + pywebview native app. The
  engine stays a single self-contained `.sh` (D-001, engine-only);
  the *project* is no longer single-file (D-026).
- **Status**: **v3.2.1 RELEASED on PyPI (2026-07-16)** — the current
  release. It hotfixes a username-resolution bug in v3.2.0 where
  `ssh -G`'s *default* `User` (the local OS username, which it emits
  for every host whether ssh_config configures one or not) outranked
  the username cache and suppressed the interactive username prompt;
  recorded as amendment **A7** under D-032 in `PLAN.md`.
  **Per-release history belongs in [`CHANGELOG.md`](CHANGELOG.md), not
  here.** The remainder of this bullet is accumulated *project facts*
  (what exists and how it works) — useful, but it drifted into
  changelog-shaped "on `main`, awaiting the tag" prose across
  v3.0–v3.2 and ended up four releases stale. Do not extend it that
  way: when a release ships, re-ground the status claim above and put
  the narrative in `CHANGELOG.md`.
  D-031 shipped: web-UI launcher cwd + dual embedded terminals
  (Channel + Utility) + scope-aware forbid-list + scope dropdown +
  MRU history + light/dark theme toggle + engine `--cwd` parity +
  multi-instance guard + cross-platform focus-follow-window (macOS
  AppleScript activate-last + Popen-path System Events raise; Linux
  wmctrl best-effort with Wayland no-op). Design record
  [`notes/impl_launcher_cwd.md`](notes/impl_launcher_cwd.md). Test
  count: 133 baseline → **290 passing** *(as of the D-031 work,
  2026-07-13; the suite has grown since — run `pytest -q` for the
  current number rather than trusting this one)* (includes the 2026-07-13
  claudecode-config cleanup: `write_claudecode_config` now emits
  Anthropic's canonical `ANTHROPIC_API_KEY` instead of the legacy
  alias `ANTHROPIC_AUTH_TOKEN` (both are honored by Claude Code;
  the swap is future-proofing, not a bug fix — earlier notes
  claiming AUTH_TOKEN was silently ignored were mistaken, later
  falsified by dead-port tests showing both env vars route the
  request through `ANTHROPIC_BASE_URL` correctly);
  `_migrate_claudecode_config_in_place` runs BEFORE
  `handle_config_file` so pre-2026-07-13 configs converge on the
  canonical shape silently in non-TTY callers (web UI's
  `configure` verb + `run --ensure` + `-y` runs auto-answer `k`
  at the k/b/d/m/a prompt and would otherwise skip the migration);
  per-tool `<name>_shadowing_env_vars()` contract +
  `_check_env_shadow_and_warn` fires at configure / before `run`
  execs the tool and warns loudly if a shell-env value would
  shadow the config we wrote (universal detector, applies to
  every tool). Same investigation also surfaced the real
  UX issue: the Claude Code TUI welcome banner + Select-model
  picker are rendered from `~/.claude.json` OAuth account state
  regardless of the actual routing — users see "Opus 4.8 · API
  Usage Billing" and reasonably conclude they're off argo. The
  post-configure output block now prints a "how to verify
  routing" hint. See docs/LIMITATIONS.md "Claude Code TUI is
  misleading"). Prior release:
  (`pipx install argo-anywhere`;
  Model-A merge `01ac516`). The Python-package + web-UI rebuild
  (D-026..D-030) shipped: package builds (wheel+sdist bundle the
  engine + assets + static), engine round-trips verbatim via
  `--print-script`, `pytest` suite green (no ANL infra), `LICENSE`
  (MIT) in metadata, CI + tag-gated OIDC publish under
  `.github/workflows/`, Q11 web-server security posture ratified in
  `docs/SECURITY.md` (loopback bind + Host guard + argv allowlist;
  loopback-token/Origin check queued as post-3.0 hardening), and the
  **D-028/D-030 live-test gate PASSED (2026-07-12)**
  (`notes/test_plan_v3_branch.md`: package-mode `connect` reached ALL
  GREEN with hyphenated node files + dormant bootstrap). **v3.0.1**
  (version set to `3.0.1`) is on `main` — docs re-ground + README
  screenshots (`assets/screenshots/`, via `scripts/screenshots.py`,
  regeneration tools now in the `[dev]` extra) + install-launcher docs
  — published from CI on its `v3.0.1` tag. **Post-v3.1.0 on `main`
  (pending tag)**: extras consolidated to a single-mode default install
  — `fastapi` + `uvicorn` + `pywebview` are folded into `dependencies`,
  and the old `[web]`/`[app]`/`[all]`/`[test]`/`[screenshots]` extras
  are dropped. Only `[dev]` remains, now absorbing `rich` + `playwright`
  so the maintainer-only screenshot regeneration path still works. Net
  effect for users: `pipx install argo-anywhere` now delivers the web
  UI + native app + `install-launcher` out of the box; no more
  `argo-anywhere[app]` incantation to remember. **Also on `main`
  post-v3.1.0**: PyYAML self-heal in the argo-proxy venv (`ensure_
  argoproxy_installed` now probes + installs, replacing the "argo-proxy
  pulls it transitively" assumption that got falsified in a 2026-07-15
  field report on `compute-386-02`) + `handle_config_file`'s `[k/b/d/m/a]`
  prompt only offers `[m]` when merge can actually work (YAML never;
  JSON only when `jq` is on PATH); AND D-032 native `~/.ssh/config`
  respect (new engine helpers `_ssh_config_hostname` /
  `_ssh_config_user` / `_alias_has_own_proxy`; refactored
  `resolve_username` to a globals-based API that separates value-
  resolution from cache-persistence per plan §7 A7 / E3; new
  `--jump-host HOST` / `ARGO_ANYWHERE_JUMP_HOST` for custom jump hosts;
  every existing invocation continues to behave identically —
  ssh-config path activates only when there is one to consult). The stdlib-PTY-over-*cold*-Duo point is an
  observed-partial (non-blocking; a warm master was reused during the
  gate). The engine's internal `SCRIPT_VERSION`
  is `2.2.1-dev` — intentionally distinct from the package version per
  D-029 (package version = release identity; engine version = internal
  component tag). Historical v2.x record below (preserved for
  provenance). **Last `.sh`-era tag: v2.2.0, released 2026-05-18**
  (tag at commit `737563d`) — this is the end of the v2.x line, NOT
  the project's latest release (see the Status bullet above and
  [`CHANGELOG.md`](CHANGELOG.md)). Phase 4 lands the per-tool scope framework +
  port-
  as-transport-state + OpenCode project-scope + cross-client
  port-coherence on top of v2.1.0's defensive-hardening base; five
  new design decisions D-017..D-021 in PLAN.md codify the new
  contracts. Phase 4 batches: B0 (`ea94042`; port-prompt helper +
  `mode_stop` case-label fix), B1a (`46c19a7`; scope framework
  D-017+D-018+D-019) + amendments `e221847` (D-016 violation: eager
  `--scope` validation; Test 5) + `1249924` (stale `--scope` help
  text; Test 6), B1b (`ecc6c64`; opencode project-scope), B2
  (`108e5d6`; port-as-state D-020; closes audit M4), B3 (`549cb93`;
  cross-client coherence D-021) + amendment `acf0722` (`[m]igrate`
  confirmation message overpromise correction; Test 8), B5 docs +
  test plan + tag (`9a0834c` + `4fe613a` + `f9cbb18` + `6c0c2e4` +
  `737563d`). Live verification per `notes/test_plan_phase4.md`:
  ALL 12 TESTS PASS with 3 code amendments + 2 doc-only commits +
  2 SHA backfills landed mid-test. Project state: **42 of 43 audit
  findings closed** (M4 closed by B2; only L8 `curl|bash claude.ai`
  remains as documented no-fix).
- **v2.2.x roadmap**: B4 cursor out-of-integration docs deferred
  to v2.3 (docs.cursor.com webfetch-unreachable; needs manually-
  collected citations); SH-04 (port-collision inline `lsof`+`ps`
  per 2026-05-18 argo-shim comparative audit) + **SCOPE-NOOP**
  (suppress `_<tool>_check_conflicts` A.1 prompts when the
  writer would produce a no-op against the existing target;
  surfaced during Test 12 live test where opencode-global prompted
  even though the existing file was already up to date) +
  **UP-01..UP-06** (six findings from 2026-06-04 upstream
  `argo-proxy` audit: stale opus-4-7 limitation doc; soft version
  floor `>=3.0.3` in `ensure_argoproxy_installed`; explicit
  `anthropic_stream_mode: force` on fresh installs; stale
  user-preserved-keys comment; opus-4-7 alias mention; verbose
  privacy reconfirmation) queued for v2.2.1; SH-01/02/03 (auth-token
  rotation; `no_proxy` injection; `CLAUDE_CODE_SKIP_ANTHROPIC_AUTH`
  default) queued for v2.3. **2026-06-24 landed on `main` ahead of
  v2.2.1 tag**: D-022 `update` subcommand (lossless in-place
  upgrades; per-component registry; auto `/refresh` after argoproxy
  upgrade) — extracts `ensure_argoproxy_installed` from inline
  `mode_server`, adds `update_<name>_cli_tool` per-tool helper
  contract, and partially addresses UP-02 (the script now exposes
  a user-facing upgrade path that doesn't require `--force-reinstall`;
  the formal soft version floor still needs a `_version_ge` check
  added to `ensure_argoproxy_installed`, queued for the v2.2.1 tag).
  **D-023 self-update + canonical install** (added same session):
  adds `argo-anywhere` as a fourth registered `update` component;
  introduces `SCRIPT_VERSION` constant; introduces canonical install
  at `~/.argo_anywhere/` (rustup/cargo style PATH directory with a
  sourceable `env` helper); introduces first-run bootstrap fired
  from `mode_client` that materializes the canonical install on
  initial use (no-op thereafter; opt-out via
  `ARGO_ANYWHERE_SKIP_BOOTSTRAP=1`).
  **Phase 5a aider integration + the lifecycle-command work
  (D-024 connect/configure/run + D-025 install/uninstall + install
  manifest) all LIVE-TEST PASSED 2026-07-09** (`notes/test_plan_lifecycle.md`,
  10 tests). aider: full 5-function contract
  (`setup_aider_cli_tool`, `ensure_aider_installed`, `write_aider_config`
  + `_aider_write_config_scratch` fallback, `aider_scope_values`,
  `aider_pick_scope`, `_aider_check_conflicts`) + registry rows +
  dispatcher arm + `update_aider_cli_tool`; OpenAI-Chat path
  (`/v1/chat/completions`); writes `~/.aider.conf.yml` + a sibling
  `.aider.model.settings.yml` that disables `temperature` for
  reasoning/opus/gpt-5 models (they return an empty stream otherwise);
  default model `openai/argo:gpt-4o`. Lifecycle: `connect`/`configure`/`run`
  verbs (channel-detect via `channel_is_up` + `--ensure`; `configure`
  reuses an existing channel without a new tunnel); canonical install
  moved to `~/.argo_anywhere/bin/` with thin `install`/`uninstall`
  wrappers; tiered `uninstall` restores client configs via the
  `manifest.json` provenance (delete files we created; restore originals
  we modified) and never kills a channel it doesn't own; `update-models`
  is now `--cli-tool`-aware. **Phase 5b codex still gated** on argo-proxy
  `/v1/responses` maturity + a TOML-writer decision (see
  `notes/impl_codex_aider.md`). Phase C local-shim mode REJECTED (would
  break D-001 single-file UX and address problems already handled
  upstream by argo-proxy's `anthropic_stream_mode: force` default).
- **Known upstream-stack limitation surfaced during v2.2.0
  release-gate live test**: Claude Code 2.1.x + ANL Argo gateway
  rejects `thinking.type.enabled` on `claude-opus-4-7` (requires
  `thinking.type.adaptive`); argo-proxy surfaces the error as a
  SSE `event: error` with HTTP 200 (correct per SSE spec); Claude
  Code mis-parses and reports "API returned empty or malformed
  response (HTTP 200)". Workaround: `claude --model claude-sonnet-4-6`
  or set `env.ANTHROPIC_MODEL=claude-sonnet-4-6` in `~/.claude/settings.json`.
  Auto-default fix queued for v2.3 (pre-populate `env.ANTHROPIC_MODEL`
  in `write_claudecode_config`).
- **Plan-of-record**: [`PLAN.md`](PLAN.md) (read after AGENTS.md)
- **Public API surface**: CLI subcommands (`client`, `setup`, `tunnel`,
  `connect`, `configure`, `run`, `server`, `status`, `stop`, `update`,
  `update-models`, `list-models`, `clean`, `install`, `uninstall`,
  `list-tools`, `help`) + flags (`--cli-tool`, `--user`, `--node`,
  `--port`, `--ensure`, `--restore-configs`, `--remove-binaries`,
  `--remote`, ...); see PLAN.md Section 2 for the table. The
  `connect`/`configure`/`run` verbs (D-024) are the three-level split of
  `client` (channel / configure-tool / run-tool); `install`/`uninstall`
  (D-025) are the symmetric lifecycle pair anchored at
  `~/.argo_anywhere/bin/` with an install manifest
  (`~/.argo_anywhere/manifest.json`) driving honest config-restore.
- **Primary downstream consumers**: ANL users running AI coding CLI
  tools (OpenCode, Claude Code, aider today; codex/cursor planned)
  against the ANL Argo gateway from any laptop on any network
- **Current release**: **v3.2.1** (2026-07-16, on PyPI). Release
  history: [`CHANGELOG.md`](CHANGELOG.md) — the single source of
  truth for "what shipped when"; do not restate it here.
- **Repo**: <https://github.com/a-attia/argo-anywhere>

### Human-facing doc map

For human-facing project docs (audience split per universal conventions
Section 6.4):

| Doc | Audience | When to read |
|:----|:---------|:-------------|
| [`README.md`](README.md) | New + returning humans | Project overview; quick start |
| [`CHANGELOG.md`](CHANGELOG.md) | Users upgrading; maintainer | **Single source of truth for "what shipped when"** (per-release, since v3.1.0). Re-ground the status claims in `README.md` / `PLAN.md` / this file at tag time; put the narrative here. |
| [`PLAN.md`](PLAN.md) | Maintainer + co-authors | Plan-of-record; design decisions D-001..D-032 |
| [`docs/UPGRADING.md`](docs/UPGRADING.md) | v1.x users upgrading | What changes for them across v2.0 / v2.1 / v2.2 |
| [`docs/SECURITY.md`](docs/SECURITY.md) | Security-conscious users + ANL admins | Threat model, CSPO defenses, privacy posture |
| [`docs/LIMITATIONS.md`](docs/LIMITATIONS.md) | Prospective users + contributors | Known limitations + rationale (includes "Upstream stack" section for argo-proxy / Claude Code limitations as of v2.2.0) |
| [`docs/TESTING.md`](docs/TESTING.md) | Maintainers + contributors | Live-verification guide (real SSH + Duo + node) |
| [`docs/AUDIT_2026-05-12.md`](docs/AUDIT_2026-05-12.md) | Maintainers | 43-finding fresh-eyes audit + STATUS resolutions (42-of-43 closed at v2.2.0) |
| [`docs/AUDIT_2026-05-18_argo-shim-comparison.md`](docs/AUDIT_2026-05-18_argo-shim-comparison.md) | Maintainers + presenters | Comparative audit `argo-anywhere` ↔ `argo-shim` (5 SH-* findings; Phase C local-shim REJECTED; slide-ready "Executive comparison" section at top) |
| [`docs/AUDIT_2026-06-04_argo-proxy-upstream.md`](docs/AUDIT_2026-06-04_argo-proxy-upstream.md) | Maintainers | Upstream `argo-proxy` audit through v3.0.4: 6 UP-* findings (1 MEDIUM stale-doc, 1 MEDIUM version-floor, 4 LOW); 15-row watch-list of upstream hot-spots to re-check on every new `argo-proxy` release |
| [`docs/AUDIT_2026-06-17_argo-proxy-upstream.md`](docs/AUDIT_2026-06-17_argo-proxy-upstream.md) | Maintainers | Re-walk vs v3.1.0 + v3.1.1: `_legacy` removal (UP-07), opus-4-7 fixed at source (UP-08), opus-4-8 reissues the limitation (UP-10); disposition of UP-01..UP-06 |
| [`docs/AUDIT_2026-07-08_argo-proxy-upstream.md`](docs/AUDIT_2026-07-08_argo-proxy-upstream.md) | Maintainers | Delta re-walk vs v3.1.2 (+ v3.2.0a0) and `llm-rosetta` v0.6.10-v0.6.12: opus-4-8 fixed at the shim layer (`llm-rosetta >= 0.6.10`), new `socket:` config key, `/v1/responses` live (codex-relevant), floor recommendation -> `>=3.1.2`; adds WATCH-16 (socket) + WATCH-17 (0.7.x pipeline migration) |
| [`docs/AUDIT_2026-08-10_argo-proxy-upstream.md`](docs/AUDIT_2026-08-10_argo-proxy-upstream.md) | Maintainers | **Execution-based** re-walk vs v3.2.1-v3.2.3 (+ v3.3.0a\*) and `llm-rosetta` v0.7.x-v0.8.2 (live venvs, not source reading). **UP-11**: `argo-proxy 3.3.0a1` cannot start (imports a symbol `llm-rosetta 0.8.2` removed; unbounded pin; unreported upstream). **UP-12**: our install probes (`--version`, `serve --help`) both PASS on that broken install. **UP-13**: `LIMITATIONS.md` + README document opus-4-7 as broken though it was fixed upstream. Closes WATCH-17 green; adds WATCH-18 (unbounded transitive pin) + WATCH-19 (v3.3.x adoption). Plan: [`notes/impl_upstream_hardening.md`](notes/impl_upstream_hardening.md) |
| [`docs/AUDIT_2026-05_pre-rebuild.md`](docs/AUDIT_2026-05_pre-rebuild.md) | Maintainers | Archived pre-rebuild audit (provenance only) |
| [`CONTRIBUTORS.md`](CONTRIBUTORS.md) | Contributors | Authorship + AI co-author trailer convention |
| [`notes/agent_feedback.md`](notes/agent_feedback.md) | Maintainer + upstream skills repo | Per-project feedback queued for upstream roll-up |
| [`notes/impl_codex_aider.md`](notes/impl_codex_aider.md) | Maintainer | Design + implementation record for aider (Phase 5a; LIVE-TEST PASSED 2026-07-09) + codex (Phase 5b; gated). Config-format facts, per-tool contract application, live-test findings. |
| [`notes/impl_lifecycle_commands.md`](notes/impl_lifecycle_commands.md) | Maintainer | Design + implementation record for D-024 (connect/configure/run) + D-025 (install/uninstall + install manifest). Three-level model, locked decisions, live-test amendments. LIVE-TEST PASSED 2026-07-09. |
| [`notes/impl_python_webui.md`](notes/impl_python_webui.md) | Maintainer | **Single source of truth** for the Model-A Python-package + web-UI rebuild (merged to `main` 2026-07-12; D-026..D-030). Plan/phasing (P0–P5), P1+cold-Duo PASS, P0–P4 code-complete layout, two-lane driver contract, residuals. Consolidates the former `spike/HANDOFF.md` + `spike/RESULTS.md` (now stubs). |
| [`notes/test_plan_phase*.md`](notes/), [`notes/test_plan_lifecycle.md`](notes/test_plan_lifecycle.md) | Maintainer | Per-phase live-test plans (historical artifact once phase complete). `test_plan_lifecycle.md` covers aider + the lifecycle commands (PASSED 2026-07-09). |

## Project-specific overrides

(Anything that differs from the universal conventions in
`~/.scicomp-research-skills/AGENTS.md` Section 6.)

### Override: single-file architecture; no `src/`/`tests/`/`experiments/` (decided 2025 inception; reaffirmed 2026-05-14) — SUPERSEDED on `main` (v3.0.0)

> **Status (`main`, v3.0.0, merged 2026-07-12): SUPERSEDED by
> D-026..D-030 (Model A — Python package + web UI).** On `main` the
> project IS a Python package. New code lands under `src/argo_anywhere/`, and a
> real `tests/` tree is expected for the Python layer (driver / cli / web).
> **The bash engine stays a single file** — vendored VERBATIM as package-data
> at `src/argo_anywhere/engine/argo-anywhere.sh` (D-028 rename) — so "one `.sh`
> file" remains true for the *engine* even though the *project* is no longer
> single-file. The `curl one .sh && bash it` install path is retired as the
> primary route (D-027 clean break); `--print-script` re-emits the raw engine
> for inspect/fork (D-026); install + upgrade go through PyPI/`pipx` (D-029).
> The original rule below is preserved for provenance and still governs the
> engine file itself (keep it self-contained; do not split the `.sh`).

**Framework rule** (`~/.scicomp-research-skills/templates/software-skeleton/`
expected layout): software projects ship with `src/<library_name>/`,
`tests/`, `experiments/<run-id>/`, `figures/<topic>/`.

**Project rule**: single self-contained bash script `argo-anywhere.sh`
at the repo root. No package layout, no test suite directory, no
experiments directory.

**Rationale**: single-file distribution is a load-bearing UX property.
Users `curl one .sh -o argo-anywhere.sh && bash it`. The same file is
`scp`'d to the compute node and re-exec'd as `server`. Splitting
breaks both flows. Documented as design decision D-001 in PLAN.md.

**Scope**: project-wide. No file in this project belongs in `src/` or
`tests/`. The "tests" are smoke checks documented inline in this
AGENTS.md and a live-verification guide in `docs/TESTING.md`.

### Override: no automated test suite; no CI (decided 2025 inception) — REVISED on `main` (v3.0.0)

> **Status (`main`, v3.0.0, merged 2026-07-12): REVISED by
> D-026.** The Python layer (driver / cli / web / PTY bridge) is unit-testable
> WITHOUT real ANL infra and HAS a `tests/` suite (pytest; 133 tests green as
> of the merge); CI for that layer is in scope. The **bash engine keeps its
> live-only verification** (`docs/TESTING.md`: real SSH + Duo + argo-proxy) —
> mocking that stack tests the mocks, not the engine. Net rule: automated
> unit tests for the package code; manual live tests for the engine.
> Original rule below preserved for provenance.

**Framework rule** (research-software-engineering skill): substantial
projects have CI + automated tests covering numerical claims +
behavioral correctness.

**Project rule**: smoke tests run manually after non-trivial edits;
end-to-end live verification on real ANL infrastructure
(`docs/TESTING.md`); no GitHub Actions workflow.

**Rationale**: the script is testable only end-to-end against real
SSH + real Duo MFA + real argo-proxy on a real compute node.
Mocking that stack is more complex than the value it provides; a
mocked CI would test the mocks, not the script.

**Scope**: project-wide.

### Override: bash + inline Python heredoc language policy (decided 2025 inception) — REVISED on `main` (v3.0.0)

> **Status (`main`, v3.0.0, merged 2026-07-12): REVISED by
> D-026.** Two-language project now. The vendored **bash engine** keeps the
> bash-3.2+ policy below (it is carried VERBATIM, unchanged). A **Python 3.10+**
> package layer wraps it (driver / cli / web); new non-engine code is Python and
> follows Python conventions (type hints, `ruff` for lint + format, pytest). The
> engine's inline Python-heredoc escape hatch is unchanged. Original rule below
> preserved for provenance.

**Framework rule** (research-software-engineering skill, MULTI-LANGUAGE.md):
software projects pick ONE primary language (Python / Julia / C++ /
Rust / Fortran / ...) and follow that language's conventions.

**Project rule**: bash primary; Python heredocs (`python3 - <<'PYEOF' ...
PYEOF`) as escape hatch for structured-data work (JSON/YAML/TOML
merging that preserves user-owned keys).

**Rationale**: bash is the right tool for the orchestration work
(SSH multiplexing, screen/tmux/nohup launchers, port collision
prompts). Python is the right tool for JSON/YAML merging. Inline
heredocs preserve the single-file distribution while letting Python
do what Python does well. Documented as design decision D-002 in
PLAN.md.

**Scope**: project-wide. Targets bash 3.2+ (macOS default) so no
bash-4 features (no `${var,,}`, no `mapfile`, no `declare -A`, no
`printf -v` with format reuse).

### Override: AI co-authorship trailer = adopted (matches framework default; documented for explicitness)

**Framework rule** (root `~/.scicomp-research-skills/AGENTS.md`
Section 6.3): AI co-authorship attribution default = ON; substantive
AI-assisted commits include
`Co-Authored-By: Claude <noreply@anthropic.com>` trailer.

**Project state**: ✅ adopted. Documented in [`CONTRIBUTORS.md`](CONTRIBUTORS.md).
First commit using the trailer: `f312232` (the rename + co-author
adoption commit, 2026-05-13). All subsequent commits include the
trailer. A `.gitmessage` template (added 2026-05-14) pre-populates
the trailer for `git commit` invocations.

**Scope**: every commit with substantive AI assistance. Pure
mechanical commits (e.g. dependency bumps, lockfile refreshes) MAY
omit; the user's discretion.

## Project-specific facts the agent should not have to derive

These are load-bearing facts the agent benefits from knowing without
reading PLAN.md cover-to-cover or grepping the script.

### Distribution + architecture overview

The project is published at <https://github.com/a-attia/argo-anywhere>.
**As of v3.0.0 the supported install is the PyPI package**
(`pipx install argo-anywhere`; from `main` until the first publish) —
see `README.md` "Install". The pre-v3 `curl` one-`.sh` route is
retired as primary; the raw engine is still obtainable for
inspect/fork via `argo-anywhere --print-script` (D-026), and a forked
`.sh` self-manages exactly as the pre-v3 script did (see `README.md`
"Running the raw engine (fork mode)").

The engine is one file (~5800 lines as of v2.0) divided into 25
numbered sections (search for `# SECTION:` to navigate). Three
conceptual layers — **transport** (SSH multiplex + tunnel + monitor),
**per-tool** (`setup_<tool>_cli_tool` functions), **server-side
bootstrap** (Python venv + argo-proxy launch). See PLAN.md Section 3
for the architecture diagram.

### Subcommand reference

`client` (default), `setup`, `tunnel`, `server`, `status`, `stop`,
`update`, `update-models`, `list-models`, `clean`, `list-tools`, `help`.

- **`client`** — all-in-one workflow: SSH tunnel + chosen-CLI-tool
  install + config write + monitor. `scp`s the file to a chosen
  compute node and re-execs it as `server` over SSH. The "chosen
  CLI tool" is selected via `--cli-tool <name>` (or interactive
  picker if omitted).
- **`setup`** — thin alias for `client` that ALWAYS shows the picker,
  even if `--cli-tool` is set. Useful for one-off installations of a
  different tool from the user's usual.
- **`tunnel`** — `client` minus the per-tool install/config: open the
  SSH forward (or local proxy on a compute node) and block in the
  foreground monitor loop. Useful for power users managing their own
  tool configs or keeping a tunnel alive while configuring multiple
  tools in other terminals.
- **`server`** — runs argo-proxy locally. Auto-invoked by `client`
  over SSH on the picked compute node, but also a documented
  standalone workflow ("leave a proxy on this node for any tool to
  reach"). Resolves identity from env, then
  `~/.config/argoproxy/config.yaml`, then cache; prompts for
  confirmation when no env was supplied (skip with `-y`).
- **`update`** — lossless in-place upgrade of installed components
  (per PLAN.md D-022 + D-023; added 2026-06-24 for v2.2.1). Registry
  today (four components):
  - `argo-anywhere` (the script itself; D-023): resolves the latest
    upstream tag via the GitHub API (two-step probe:
    `/releases/latest` falling back to `/tags`; final fallback to
    `main`); validates the fetched script (`bash -n` + size >50 KB +
    sentinel marker: `SCRIPT_VERSION=` line OR canonical
    `# argo-anywhere.sh --` header); atomically replaces the
    canonical install at `~/.argo_anywhere/argo-anywhere.sh` with a
    `.bak.<timestamp>.<pid>` backup. Refuses to clobber a dirty git
    working tree. Prompts to bootstrap the canonical install if it
    doesn't exist yet.
  - `argoproxy` (server-side, via SSH to the compute node +
    venv-pip; D-022).
  - `opencode` (laptop, via brew or curl-installer re-run; D-022).
  - `claudecode` (laptop, via curl-installer re-run; D-022).

  `--all` updates everything; positional component args restrict the
  run; bare `update` lists the registry and exits without changing
  anything. `--check` is report-only (installed vs latest tag for
  argo-anywhere; installed vs PyPI-latest for argoproxy; installed-
  version for the laptop tools). `--yes` auto-confirms install
  prompts for missing components. After a successful `update
  argoproxy`, automatically POSTs `/refresh` to the local tunnel if
  it's up, so the running proxy's ModelRegistry pulls fresh upstream
  models without a restart. Sibling of `update-models` (which only
  refreshes the OpenCode config's model list; never installs
  anything) and the lossless complement to `--force-reinstall`
  (which always wipes + rebuilds the venv).

### MFA-aware by default

ANL CELS hosts use Duo. The script uses SSH `ControlMaster` connection
multiplexing so Duo prompts only fire once per session. Sockets land
in `~/.ssh/sockets/argo-anywhere-<user>-<host>-<port>` (literal
`%r-%h-%p` tokens, not the `%C` hash — `%C` proved fragile when
`~/.ssh/config` rewrites jump-host names, producing two different
socket paths for what was logically the same connection). Disable MFA
mode for non-Duo hosts with `--no-mfa`.

The script also detects + cleans up legacy v1.x-prefixed sockets
(`argo-opencode-*`) for users upgrading from the pre-v2.0 era.

### Jump-host shell restriction

`logins.cels.anl.gov` is jump-only — its login shell rejects all
command execution ("This account is currently not available"). The
script therefore opens the multiplex master against the picked compute
NODE, not the jump host. `mode_client` reorders pick-node before
preflight under MFA. **Do not** try to
`ssh -O ... <user>@logins.cels.anl.gov true` — it always fails.

### Jump-host resolution (D-032, v3.2.0; amended A7 in v3.2.1)

`ANL_JUMP` is a **mutable script global**, not a `readonly` constant.
Resolution precedence at `main()` (post-argv, pre-mode-dispatch):

1. `--no-jump` on CLI (or `ARGO_ANYWHERE_NO_JUMP=1` env) → skip the
   jump host entirely; `ssh_jump_args` returns empty.
2. `--jump-host HOST` on CLI → `ANL_JUMP=HOST` for THIS run.
3. `ARGO_ANYWHERE_JUMP_HOST=HOST` env → `ANL_JUMP=HOST` (flag beats
   env; both were parsed by the argv arm which exports the env var).
4. `ARGO_ANYWHERE_JUMP_HOST=""` env (explicitly empty) → treated as
   `--no-jump` (matches shell convention for opt-out env vars;
   distinguishable from unset via `${VAR+set}`).
5. Per-target `~/.ssh/config` `ProxyJump`/`ProxyCommand` on the alias
   → `ssh_jump_args` detects via `_alias_has_own_proxy` and skips
   our `-J` even when steps 1-4 didn't fire, deferring to the
   alias's own routing. The user-facing "routes via ssh_config"
   notice fires ONCE per client-setup from
   `_announce_alias_routing_once` in `_client_common_setup` (parent
   shell); `ssh_jump_args` itself is silent. Design history: A5
   amendment 2026-07-15 replaced an earlier `_alias_proxy_notice_dedup`
   that tried to dedup from within a `$()` subshell (broken by design;
   the sentinel never propagated to the parent).
6. Default: `ANL_JUMP="logins.cels.anl.gov"` (declared in Section 5).

**Load-bearing invariant**: `ANL_JUMP` must NEVER be declared
`local` or `readonly` inside a function called after step 2/3
mutates it. All 42 existing `ANL_JUMP` references read `$ANL_JUMP`
at call/interpolation time, so mutating the global here propagates
to `ssh_jump_args`, the SCP branch, `ssh_preflight`, the status
card, help text, error messages, and every template `ssh -J
<user>@${ANL_JUMP} ...` command in the docs — without any per-site
change. Two grep-based invariant tests in
`tests/test_engine_ssh_config.py` (`test_no_local_ANL_JUMP_shadow`
+ `test_ANL_JUMP_readers_use_expansion`) protect this contract from
a future refactor.

Username inference (D-032 Sub-fix B): `resolve_username` consults
`ssh -G` for `ARGO_ANYWHERE_NODE` then `ANL_JUMP` between the
env-check and the cache-check. Values inferred this way are NEVER
persisted to `USER_CACHE` (the cache remains write-only-from-
explicit-actions per plan §7 E3); prompted values still get cached
as before. The refactor split `resolve_username` (which now sets
globals `_USERNAME_RESULT`, `_USERNAME_SOURCE`,
`_USERNAME_SHOULD_CACHE`) from a new `_persist_username_cache`
helper the caller invokes conditionally. **Callers MUST NOT** use
`$(resolve_username)` command substitution — the subshell drops
the globals (D-005 pattern).

### Mux master holds tunnels alive

Under `ControlMaster=auto`, a foreground `ssh -N -L` may exit
immediately after the forward request is acknowledged by the master;
the master then owns the forward. Health checks must verify
`/health`, not just the foreground pid. `open_tunnel_and_monitor`
handles this: if the foreground ssh dies but `/health` still answers,
declare success and let the master own the forward. The monitor and
parent wait-loop both handle empty `SSH_TUNNEL_PID`. (Design decision
D-003 in PLAN.md.)

### Port policy

The OpenCode config's `baseURL` is the source of truth. `--port N` and
`ARGO_ANYWHERE_PORT` are one-shot overrides; if they disagree with the
config, `mode_client` asks `[m]igrate / [u]se-once / [k]eep / [a]bort`.
Non-client subcommands warn on mismatch but don't prompt.

### Server-side port + config validation

After `handle_config_file` for `~/.config/argoproxy/config.yaml`,
`mode_server` reads back the `port:` line and refuses to launch
argo-proxy if it disagrees with `$PROXY_PORT` (else argo-proxy binds
the wrong port and the client polls in vain). The same writer also
preserves unknown YAML keys via a Python+PyYAML merge: only
`config_version`, `user`, `host`, `port` are owned by the script;
everything else (`argo_url`, `argo_embedding_url`,
`concurrent_downloads`, etc.) survives a `[b]ackup+overwrite` choice.

### No-interactive-prompt invariant (argo-proxy launch)

**Every launcher in `mode_server` MUST run argo-proxy with stdin
redirected from `/dev/null`** (`screen`, `tmux`, and `nohup` — the
last has always had it; the first two were fixed 2026-08-10). Search
the engine for `NO-INTERACTIVE-PROMPT INVARIANT`.

Why: `screen -dm` / `tmux new-session -d` hand the child a pty, so an
interactive prompt has something to read from and blocks forever inside
a session nobody is watching. Upstream's `validate_port` tests the port
with a real `socket.bind()` — so it sees cross-user collisions our
unprivileged `lsof` probe cannot — and on failure drops into a bare
`while True: input(...)` with no EOF handling and no timeout. The
client-side wait then reports only `did not start listening within 20s`,
naming a symptom rather than a cause. With stdin at `/dev/null` the same
prompt raises `EOFError` in ~1s.

Two rules for anyone touching that launch block:

- The `screen` branch passes the binary as `$0` to
  `sh -c 'exec "$0" serve < /dev/null'` rather than interpolating the
  path into the script string — a `$venv` containing spaces would
  otherwise word-split (the hazard the `tmux` branch solves with
  `printf %q`).
- **All three launchers also `tee` to `$_PROXY_LOG` (`~/argoproxy.out`),
  and the timeout branch reads that FIRST.** This is the
  `LOG-DURABILITY COROLLARY` and it is load-bearing: the stdin redirect
  makes a prompting argo-proxy die in ~1s, so `screen`/`tmux` reap the
  session ~18s before the 20s timeout fires. A session-only capture has
  nothing left to read in the common case — the two halves of the fix
  would cancel out. The log outlives the session; historically only the
  `nohup` branch wrote it. Use `tee`, not `screen -L -Logfile`
  (`-Logfile` needs screen ≥4.06, which we cannot assume on an
  arbitrary node, and `tee` keeps output visible to `screen -r`).
- The start-timeout branch calls `_dump_session_output_screen` /
  `_dump_session_output_tmux` as a **fallback only** (when the log came
  back empty), covering the disjoint case where the process is still
  alive at 20s — a genuine hang rather than a fast death. They capture
  the live session's visible buffer (`screen -X hardcopy` /
  `tmux capture-pane -p`). Both are **no-fail by contract** — missing
  binary, dead session, or unwritable `TMPDIR` degrades to a silent
  no-op, because they run inside a path that is already dying. Never
  let them `die`.

Pinned by `tests/test_engine_no_interactive_prompt.py`, which also
asserts the two engine copies stay byte-identical. Background:
[`notes/impl_shared_node_transport.md`](notes/impl_shared_node_transport.md)
(Tier 1 item 1).

### Bind-test oracle for port availability (not `lsof`)

**Port availability is decided by `socket.bind()`, never by `lsof`.**
`probe_remote_port_owner` and `find_next_free_remote_port` both bind-test;
`lsof` is only used to *attribute* a hit we already know about.

Why: an unprivileged `lsof` on Linux cannot see another user's socket, so
a co-tenant-held port reads as **free**. On a shared node that is the
common case. Measured on `compute-386-01`: `:64742` → `lsof=<empty>` but
`bind=TAKEN`. `--auto-port` was the worst affected — the flag that exists
to escape a collision recommended occupied ports.

Rules for anyone touching those probes:

- **`SO_REUSEADDR` must stay explicitly disabled** (`, 0`). With it set,
  `bind()` succeeds on a `TIME_WAIT` port and an unusable port reads free.
- **Bound-but-unattributable is `other:?:?`, never `free`.** Empty `lsof`
  on a port that refuses `bind()` means "someone else's", not "nobody's".
- **Both probes degrade rather than fail** when `python3` is absent
  (probe → `unknown`; walk → old `lsof` loop).
- The walk uses **one** python process for the whole range, not one per
  candidate.

Still a detector, not a guarantee: there is a TOCTOU window between our
bind and argo-proxy's. The load-bearing safety property is the
no-interactive-prompt fast-fail above. Pinned by
`tests/test_engine_bind_test_oracle.py`.

### Identity-before-success invariant (argo-proxy post-launch wait)

**`mode_server`'s post-launch wait MUST confirm the `/health` responder
is ours** — `until curl … /health && _listener_is_ours "$PROXY_PORT"`.
Search the engine for `IDENTITY-BEFORE-SUCCESS INVARIANT`.

Why: on a shared node another user's argo-proxy holding our port answers
`/health` identically (same software), so a bare curl proves only that
*something* serves. In the 2026-08-10 incident our proxy hung at a port
prompt, a co-tenant's satisfied the wait, `mode_server` reported success,
and the client tunnelled into a stranger's process under ALL GREEN.

`_listener_is_ours <port>` exploits an inversion: the unprivileged-`lsof`
blindness that makes it useless *before* launch (can't see other users'
sockets — Defect 1) is a reliable positive signal *after* launch, since
a proxy we started is always attributable to us. Empty `lsof -t` on a
port that demonstrably serves means "someone else's", not "nobody's".

- **Fail-closed by contract.** Missing `lsof`, vanished pid, unnameable
  owner → "not ours". Never claim ownership on missing evidence; that
  is the same rule as H5's "positively confirm or refuse", applied
  post-launch. Do not add a `return 0` to a guard clause.
- It compares the **OS account** (`id -un`), deliberately. The question
  is "did the process we just spawned come up?" — *not* "whose Argo
  identity will it bill?", which stays H5's job via the config `user:`.
- A foreign listener is a **hard failure, not a timeout**: waiting
  cannot free a held port, so we refuse immediately and name the fix
  (`--port` / `--auto-port`).

Pinned by `tests/test_engine_listener_identity.py`. Background:
[`notes/impl_shared_node_transport.md`](notes/impl_shared_node_transport.md)
§2.4 (Defect 4), Tier 1 item 2.

### Server-mode logging trick

The early `bash "$0" server | tee -a $LOG; exit ${PIPESTATUS[0]}`
pattern must **not** be prefixed with `exec` — `exec CMD | tee` only
`exec`s the left side, the rest of `mode_server` then runs a second
time, double-bootstrapping. (Design decision D-004 in PLAN.md.)

### Env vars are namespaced

Canonical names:

- `ARGO_ANYWHERE_USER`
- `ARGO_ANYWHERE_NODE`
- `ARGO_ANYWHERE_PORT`
- `ARGO_ANYWHERE_NO_JUMP`
- `ARGO_ANYWHERE_JUMP_HOST` (D-032; empty string == `--no-jump`)
- `ARGO_ANYWHERE_NO_MFA`
- `ARGO_ANYWHERE_FORCE_REINSTALL`
- `ARGO_ANYWHERE_SHOW_MODELS`
- `ARGO_ANYWHERE_CONTROL_PERSIST`
- `ARGO_ANYWHERE_AUTO_PORT`
- `ARGO_ANYWHERE_PORT_RANGE`
- `ARGO_ANYWHERE_VERBOSE_SERVER`
- `ARGO_ANYWHERE_KEEP_ORPHANS`
- `ARGO_ANYWHERE_DROP_ORPHANS`
- `ARGO_ANYWHERE_ALLOW_FOREIGN_PROXY` (opt out of the `external-healthy`
  identity gate; see "Identity-before-success invariant")
- `ARGO_BOX_STYLE`

Two generations of legacy names still work with a one-time deprecation
warning each (snapshotted **before** the script's own config block
reassigns them, so promotion sees the inherited values):

- **Pre-namespace** (oldest): `ANL_USERNAME`, `PROXY_PORT`,
  `SHOW_MODELS`.
- **Pre-rename** (v1.x era; argo_opencode.sh): every
  `ARGO_OPENCODE_<X>` is honored as a legacy alias of
  `ARGO_ANYWHERE_<X>`. Users with `export ARGO_OPENCODE_USER=...`
  in their shell rc files see one WARN per stale var on the first run
  after upgrade; the script otherwise behaves identically.

The Argonne username is distinct from the laptop's `$USER` — never
substitute one for the other. The writers always read
`ARGO_ANYWHERE_USER` (with `ANL_USERNAME` as legacy fallback).
`mode_server`'s pid-owner check uses `id -un` (OS-level, correct) but
the config-user check uses `ARGO_ANYWHERE_USER` (Argonne-level,
correct).

### `set -euo pipefail` is on; SIGPIPE-resilient cmd substitution required

Avoid `[ test ] && cmd` at function/branch top level. When the test
fails, `set -e` doesn't kill (the man page exempts `&&`/`||` chains),
but bash 3.2 (macOS default) has parser quirks with quoted heredocs
inside `$()` under `set -u` that have bitten this script before.

Use `if/then/fi` and write multi-line remote scripts via temp files
(`mktemp` + `ssh ... < file`), **never**
`var="$(cat <<'EOS' ... EOS)"`.

**SIGPIPE in cmd substitution** (audit finding P1; design decision
D-011 in PLAN.md): the pattern `local x; x="$(cmd | head -n1)"` under
`set -euo pipefail` triggers `set -e` when `head -n1` closes stdin and
the upstream command (lsof, awk) gets SIGPIPE. **Always wrap such
patterns**:

```bash
x="$( { ... | head -n1; } || true )"
```

The `{ ...; } || true` swallows SIGPIPE so the assignment can't trip
set -e. New code review must check every `$(... | ...)` cmd
substitution for this class.

### Audit "main-mode" functions before calling them in-process

A recurring class of bug: a function originally written as the
script's **main mode** (the script's job IS to run this then exit)
gets refactored to ALSO be callable as one step of a longer in-process
flow. Main-mode-only assumptions silently break the in-process
caller. (Design decision D-005 in PLAN.md.)

Three concrete instances hit historically (commits `df10abe`,
`ed71864`, `32601c3`):

- **`$()` capture of a function that mutates globals.** Command
  substitution runs the function in a subshell; mutations to
  script-level globals (`ANL_USERNAME`, `ARGO_ANYWHERE_USER`,
  `PROXY_PORT`, env-var auto-defaults, etc.) evaporate when the
  subshell exits. Parent then sees the global as unbound and trips
  `set -u`. Fix: don't capture; use a designated `_RETURN_*` global to
  convey the "return value."
- **`exit` inside a function that may now be called in-process.**
  `mode_server`'s tee-then-exit pattern was correct when `mode_server`
  was the only thing the script did. It became wrong when
  `_client_common_setup`'s on-node short-circuit started invoking
  `mode_server` as one step of a longer flow. Fix: gate the `exit` on
  a "called in-process" flag and `return` the same status code in the
  in-process branch.
- **Assumptions about shell state outside the script.** Each AI
  tool's installer drops the binary at a known location and updates
  `~/.bashrc` PATH. The post-install `command -v <tool>` correctly
  returns non-zero because the running script's PATH doesn't include
  the new directory; the user's *next* shell would have it but ours
  doesn't. Fix: prepend the well-known install location to PATH for
  the rest of the script invocation.

The meta-rule: **when a function that was originally a "main mode"
gets called in-process from somewhere else, audit it for `exit`,
`exec`, `$()` capture by callers, and any implicit assumption that
"the user's next shell" or "the next process" will pick up state
changes we made.** None survive an in-process call. The fix usually
involves either (a) adding a flag like `_FOO_INPROC=1` that the
function checks before exiting, or (b) factoring the function into
"do the work" + "wrap with the main-mode-only behavior."

### Multi-CLI-tool architecture: per-tool API contract

The script supports several AI CLI tools (OpenCode + Claude Code
today; aider, cursor, generic planned). Each tool defines:

- **`setup_<name>_cli_tool()`** — top-level entry point invoked by the
  dispatcher (`do_post_tunnel_for_cli_tool`). MUST be idempotent.
  Calls `<name>_pick_scope()` (if applicable; B1a Phase 4 moved this
  BEFORE `ensure_<name>_installed`), then `ensure_<name>_installed`,
  then `handle_config_file <path> <desc> write_<name>_config`. Reads
  `PROXY_PORT`, `ANL_USERNAME`, `ARGO_ANYWHERE_USER` from script-level
  globals.
- **`ensure_<name>_installed()`** — install-or-detect the tool binary.
  After install, prepend any well-known install location to `PATH` so
  the rest of the running script sees the binary (the upstream
  installer's rc-file PATH update doesn't reach the running shell).
- **`write_<name>_config(dest)`** — produce a fresh config at `dest`.
  Invoked by `handle_config_file`, so the signature is fixed at
  one-arg destination path; everything else flows in via globals. Use
  a Python heredoc for non-trivial JSON/YAML/TOML merging (preserves
  user-owned keys; we only own the few keys we need).
- **`<name>_scope_values()`** — D-018 (Phase 4 B1a): declares the
  space-separated list of legal `--scope` values for this tool. Used
  by `_validate_scope_for_tool` (called from `<name>_pick_scope` for
  tools with multiple scopes, OR from `setup_<name>_cli_tool` directly
  for tools with a single scope). Even tools with a single scope MUST
  declare this so the per-tool vocabulary validation catches typos
  like `--cli-tool opencode --scope projct`.
- **`<name>` row in the `CLI_TOOLS_AVAILABLE` array** (display order
  + picker label).
- **A `<name>` arm in `do_post_tunnel_for_cli_tool`** that calls
  `setup_<name>_cli_tool`, then `gather_summary; render_summary`,
  then prints any tool-specific tail messages ("Run: claude" etc.).

Optional but conventional:

- A **`<name>_pick_scope()`** function if the tool has multiple config
  locations (project vs global, etc.). Sets globals
  `_<NAME>_SCOPE_PATH` and `_<NAME>_SCOPE_NAME` for the writer to
  consume — DO NOT capture via `$()` (the function may need to prompt
  the user; subshell capture would eat the prompt). See
  `claudecode_pick_scope` for the reference implementation. Per D-017,
  the function should (a) resolve the intended scope from
  `_SCOPE_OVERRIDE` / `ARGO_ANYWHERE_SCOPE` / per-tool auto-default,
  (b) validate against `<name>_scope_values()`, (c) detect conflicts
  (existing files; OAuth state; project-shadow), (d) invoke
  `prompt_scope_switch` on conflict to let the user keep/switch/abort.
- An **`update_<name>_cli_tool()`** function (per D-022; v2.2.1) that
  performs an in-place upgrade of the tool's binary without nuking
  state. Contract: takes no args; honors `$UPDATE_CHECK_ONLY` (report-
  only mode) and `$UPDATE_ASSUME_YES` (auto-confirm install prompts)
  globals; returns 0 on success / up-to-date, 1 on user-declined-install
  or recoverable skip, 2+ on hard failure. When absent, `mode_update`
  skips the tool with a warn. Per-tool implementation idiom: detect
  install path (brew prefix vs curl|bash) and run the matching upstream
  upgrade command; for compiled / venv-based components, prefer the
  local pip's `--upgrade` path over upstream self-updaters (see D-022
  for the live-test rationale that `argo-proxy update install` resolves
  the wrong `pip` on compute nodes).
- A **`<name>_shadowing_env_vars()`** function (added 2026-07-13)
  declaring space-separated env-var names whose SHELL values, if set,
  would override the config we write. Consumed by
  `_check_env_shadow_and_warn <name>` which the dispatcher
  (`do_post_tunnel_for_cli_tool`) calls right after configure
  finishes / before `mode_run` execs the tool. Warns loudly with the
  exact `unset <VAR>` commands to run. Tools with no runtime env
  exposure may omit the function (the helper cleanly no-ops).
  **When adding a new tool**: declare the function even if you think
  the tool has no env footgun today. Upstream tools grow env
  overrides across releases; a user with `ANTHROPIC_API_KEY=sk-ant-…`
  (or `OPENAI_API_KEY=…`, etc.) exported in their shell rc would
  have that value override the argo credential we wrote to the
  config file, silently routing requests to their personal account
  instead of argo. The detector surfaces that class of leak
  universally. Keep the list in sync with `write_<name>_config`:
  any env key we write should be in the shadow list too, so a
  user with a stale export finds out immediately instead of
  silently getting the wrong endpoint.

The server-side `argo-proxy` component has the analogous shape but
is NOT a CLI tool registered in `CLI_TOOLS_AVAILABLE`; it lives in
the parallel `UPDATE_COMPONENTS_AVAILABLE` registry and is handled by
`update_argoproxy_component` (whose remote-execution path is what
distinguishes it from the laptop-side `update_<name>_cli_tool`
helpers). `ensure_argoproxy_installed` is the shared install primitive
(factored out of `mode_server` in D-022 so both `mode_server` and
`update_argoproxy_component`'s on-node short-circuit can call it).

### Scope handling: D-017 + D-018 + D-019 (Phase 4 v2.2.0)

- **`--scope <value>`** CLI flag (and `ARGO_ANYWHERE_SCOPE` env var; D-019
  user-facing namespace). Value semantics are per-tool: each tool
  declares its accepted values via `<name>_scope_values()`. The CLI
  parser accepts any non-empty string at parse time; per-tool
  validation happens at the picker/setup stage so it can run after
  both `--scope` AND `--cli-tool` have been observed (flag order is
  not constrained).
- **`_SCOPE_OVERRIDE`** is the internal global where the CLI parser
  stores `--scope <value>`. Per-tool pick_scope reads it (preferred)
  or `ARGO_ANYWHERE_SCOPE` (fallback to env-set value).
- **`CLAUDECODE_SCOPE`** is deprecated (was the pre-Phase-4 per-tool
  env var). Honored with one-time WARN per session via the Section 6
  promotion block (`_warn_legacy_env CLAUDECODE_SCOPE ARGO_ANYWHERE_SCOPE`).
  Removal target: "whenever v3.0.0 ships" (no fixed schedule).
- **Per-tool default scope (D-017)** is HYBRID for claudecode: explicit
  > `~/.claude.json`-present → project (safety; preserves personal
  subscription) > else global (convenience for fresh installs). For
  opencode, default is global (no OAuth state to preserve; opencode is
  global-only until B1b adds project support).
- **Engine ↔ web-UI coupling**: see the dedicated `### Engine ↔
  web-UI coupling rules` subsection below (moved out of this bullet
  post-D-032 so all coupling rules live in one place).

### Engine ↔ web-UI coupling rules

Any change on one side of these coupled surfaces requires a matching
change on the other in the SAME commit. No automated enforcement
except where noted (a couple of grep-based invariant tests exist);
reviewers verify by grep or the mirror-test suite.

- **D-031 scope-values (2026-07-13)**: any change to a tool's
  `<name>_scope_values()` function in the engine (adding /
  removing / renaming a legal scope value) MUST update the web UI's
  `lScope` `<select>` options in `src/argo_anywhere/web/static/index.html`
  in the same commit. The web UI dropdown is a closed-vocabulary
  UI whose values must match the per-tool engine vocabulary exactly.
  A mismatch would either hide a legal value from web users
  (dropdown missing) or ship a value the engine rejects (dropdown
  extra → engine `die`). Reviewers verify by grepping
  `<name>_scope_values` in both files. Also update `PLAN.md`'s
  D-031 (if the change is substantive) and `notes/impl_launcher_cwd.md`
  §6.1 wording (if the field's default logic changes).

- **D-032 ssh-config surface (2026-07-15)**: **tri-lockstep**
  contract across three coupled surfaces:

    1. **Engine CLI flags** (`--node` / `--user` / `--jump-host` /
       `--no-jump`) ↔ **launcher popover field names + IDs**
       (`lNode` / `lUser` / `lJump` / `lNoJump`) in
       `src/argo_anywhere/web/static/index.html` ↔
       **`build_launch_argv` kwargs** (`node` / `user` /
       `jump_host` / `no_jump`) in `src/argo_anywhere/web/app.py`.
       Renaming any one of the four flags requires all three
       surfaces to move in the same commit.

    2. **Engine helpers** (`_ssh_config_hostname` /
       `_ssh_config_user` / `_alias_has_own_proxy` /
       `_is_ssh_config_alias` / `_announce_alias_routing_once` in
       Section 8 of the engine) ↔
       **Python mirror** (`argo_anywhere.web.preview.reflect_jump_args`
       + `SshGResult.has_own_proxy`) in
       `src/argo_anywhere/web/preview.py`. The mirror reflects
       the engine's ssh_jump_args decision back to the launcher's
       preview panel; if the two disagree, the panel lies about
       what argo-anywhere will do at Launch. Enforced by
       `tests/test_preview_launch.py::test_reflect_jump_args_matches_engine`
       — a byte-equivalent-mirror test using the same stub-ssh
       fixture on both sides.

    3. **`ANL_JUMP` mutability contract** (engine's `main()`
       resolution block) ↔ **`/api/preview-launch` response
       shape** — both must reflect the resolved jump host, not
       the compile-time default. Protected by
       `tests/test_engine_ssh_config.py::test_no_local_ANL_JUMP_shadow`
       + `test_ANL_JUMP_readers_use_expansion` (grep-based
       invariants that fail if a future refactor `local`-shadows
       `ANL_JUMP` or introduces an assignment outside the two
       known sites).

  Additional reviewer checks:

  * `grep -n '_SAFE_HOSTLIKE\|_SAFE_TOKEN' src/argo_anywhere/web/`
    — the two regexes have distinct purposes (`_SAFE_TOKEN` for
    cli-tool + scope tokens; `_SAFE_HOSTLIKE` for hostnames +
    usernames + jump-hosts). Any tightening of either must
    preserve the coverage of legitimate real-world inputs.
  * `grep -n 'ssh_jump_args\|reflect_jump_args' src/argo_anywhere/`
    — the two implementations must produce byte-equivalent argv
    fragments; adding a new decision branch to one requires the
    other to gain the same branch in the same commit.

- **IP-block safety contract** (D-032, cross-cutting): the web
  endpoints `/api/ssh-hosts` and `/api/preview-launch` MUST NOT
  authenticate against any SSH server. `/api/ssh-hosts` is a pure
  file parse (never calls `ssh`); `/api/preview-launch` calls only
  `ssh -G <alias>` (non-authenticating; 2s timeout). Enforced by:
  * `tests/test_ssh_hosts.py::test_module_source_never_calls_ssh`
    (grep-based invariant: no `subprocess.` / `os.system` / etc.
    in `src/argo_anywhere/web/ssh_hosts.py`).
  * `tests/test_preview_launch.py::test_api_preview_ssh_never_authenticates`
    (verifies `subprocess.run` is called with an argv list, not
    `shell=True`, and with `timeout <= 2.0`).
  Any endpoint addition that touches SSH MUST document its IP-block
  safety story in this bullet AND add a matching invariant test.

### Launcher cwd handling: D-031 (v3.1.0)

Web UI + engine both honor an explicit working directory now:

- **Web UI**: the launcher popover requires a cwd. Blank is
  rejected. Field pre-fills with MRU top entry from
  `~/.argo_anywhere/web_state.json`, else `$HOME` on first run.
  Browse button (pywebview only) opens a native folder picker.
  Missing directory → 409 → confirm modal → explicit `POST /api/mkdir`
  (never silent).
- **Engine**: `--cwd <path>` flag parsed early; `cd -- "$path" || die`
  before mode dispatch. Same forbid-list applied. Existing CLI
  invocations without `--cwd` are unaffected (backward compatible).
- **Forbid-list (project scope only; global unrestricted)**:
  authoritative source is `_scope_project_forbid_dirs` in the
  engine; Python parallel in `src/argo_anywhere/web/forbid.py`
  (tested against the bash list). Hard-block: `$HOME` exact + `/`,
  `/bin`, `/sbin`, `/usr`, `/etc`, `/var`, `/opt`, `/tmp`, `/var/tmp`,
  `/System`, `/Library`, `/private`. Soft-warn: cwd has no `.git`
  AND no project marker (`pyproject.toml`, `package.json`,
  `Cargo.toml`, `Makefile`, `go.mod`, ...) AND no existing tool
  config.
- **Cwd-aware scope default (one-directional nudge)**: cwd == `$HOME`
  → dropdown pre-selects `global`. Project markers do NOT auto-nudge
  toward `project` (only nudge in the safe direction).
- **pywebview app cwd** is `~/.argo_anywhere/` (not `$HOME`). Shown
  in launcher header + About popover. `mkdir -p` before the `os.chdir`
  in `cli._cmd_app` / launcher scripts (canonical install may not
  be bootstrapped yet per D-023).
- **`PtySession(cwd=)`** kwarg (`src/argo_anywhere/driver.py`)
  threads the request from the web layer to `subprocess.Popen`.
  Blank/None = inherit process cwd (preserves today's behavior for
  direct programmatic callers).

### Dual embedded terminals: Channel + Utility (D-031)

The web UI's embedded-terminal container is split horizontally
into two named panels with a draggable divider:

- **Channel (left)**: persistent; owns `connect`; SSH master + tunnel
  live here; ws-close does NOT terminate (per
  `terminate_on_close=not managed.owns_channel` in `pty_bridge.py`).
  One at a time; re-launch checks `channel_is_up` first and refuses
  gracefully with a "stop + replace" option if the channel is
  already up.
- **Utility (right)**: ephemeral; runs `configure` / `setup` /
  `tunnel`. ws-close terminates cleanly; can be relaunched freely.
  `configure` refuses if no Channel active (clear error directs
  user to `connect` first — explicit > magic).
- Info verbs (`status` / `list-models` / `list-tools`) continue
  using `/api/run` (Lane-1 captured output); NOT streamed to
  Utility.
- `run` and `client` are HARD-BLOCKED from both panels (UI disables
  + server refuses); browser tab close would kill the tool session.
  `client` is also REMOVED from the web-UI verb dropdown (CLI
  unchanged).
- Existing `Terminal` / `Hide` buttons act on the container (both
  panels show / hide together — no per-panel toggle in v1).
- Divider draggable with 25%/75% min/max limits; position
  persisted as `divider_pct` in `~/.argo_anywhere/web_state.json`.
- `SessionRegistry` (`src/argo_anywhere/web/registry.py`) gains
  named slots `channel` + `utility` alongside the existing
  id-keyed `_by_id` map.

### Multi-instance policy for the web UI (D-031)

Concurrent `argo-anywhere web` / `argo-anywhere app` instances are guarded
against by a pre-bind probe of ``/healthz`` (D-031, added mid-execution):

- ``/healthz`` includes ``{"app": "argo-anywhere", "pid": ..., "package_version": ..., "app_cwd_short": ...}`` so an incoming argo can identify an incumbent as a sibling (vs. an unrelated service on that port).
- ``_cmd_web`` and ``_cmd_app`` in ``src/argo_anywhere/cli.py`` call ``_probe_peer_web(host, port)`` before starting uvicorn. Sibling → refuse with pid + version + next-port hint. Foreign service on port → refuse with generic "not us" message.
- ``--force`` on either command bypasses the probe (for advanced use; both instances then share ``~/.argo_anywhere/web_state.json`` with last-write-wins semantics, and the uvicorn bind will still fail if the port is really busy).
- ``_cmd_app`` additionally opens the incumbent's URL in the default browser after refusing (most natural response to "argo-anywhere is already running"); still exits 1 so scripts see the refusal.
- Pre-D-031 servers (returning bare ``{"status": "ok"}``) classify as ``foreign`` → refuse safely without any coordination during an incremental upgrade.

**Why not just let uvicorn's bind fail?** Two reasons: (a) the bind-error stack trace is user-hostile compared to a targeted "there's already an argo-anywhere on :8799"; (b) foreign-service detection catches the case where port 8799 is genuinely used by something else on the user's box, before they see uvicorn's more generic error.

**Do NOT** rely on the guard for correctness against a determined caller — it's a UX safety-net, not a mutex. Two instances at the same port CAN'T both bind (kernel enforces); two instances on different ports MAY overwrite each other's ``web_state.json``. The Channel-panel single-instance discipline is enforced per-instance by ``SessionRegistry.panel_alive("channel")`` and cannot span instances (each has its own in-process registry).

### Focus-follow-window for spawned terminals (D-031)

Spawned native terminals must end up frontmost, not behind the browser
that triggered the launch. Two mechanisms, both best-effort:

- **macOS AppleScript path** (Terminal.app, iTerm2): ``activate`` MUST
  be the LAST statement in the tell-block. Calling it at the top races
  window-creation against the caller (the browser) re-taking focus by
  the time the script returns. Also explicitly ``select newWindow``
  (iTerm) / ``set index of window 1 of newTab to 1`` (Terminal.app)
  so the RIGHT window is frontmost, not just the app.
- **CLI-Popen path** (alacritty / kitty / wezterm / ghostty on macOS;
  the whole Linux catalog): after ``Popen``, call
  ``_raise_focus_macos_cli(term_id)`` on Darwin or
  ``_raise_focus_linux(label, pid)`` on Linux. Both are best-effort:
  ``osascript``/``wmctrl`` absent, TCC denied, Wayland compositor, or
  the raise call timing out -- silent no-op; launch itself still
  succeeds.

Never let focus-raise failures fail the launch. Pinned by regression
tests in ``tests/test_external_terminal.py``
(``test_macos_scripts_activate_last_for_focus``,
``test_open_macos_cli_terminal_triggers_focus_raise``,
``test_open_linux_cli_terminal_triggers_focus_raise``,
``test_focus_raise_never_fails_the_launch``).

### Light/dark theme toggle (D-031)

The web UI shipped dark-only in v3.0.x; v3.1.0 adds a
top-bar toggle cycling `auto → dark → light → auto` (default
`auto` reads `prefers-color-scheme`). Choice persisted as a
`theme` key in `~/.argo_anywhere/web_state.json` (values
`{"auto", "dark", "light"}`). Palette lives in CSS custom
properties gated on a `data-theme` attribute on `<html>`; the
two xterm.js panels (Channel + Utility) re-color on toggle by
assigning **`term.options = { theme }`**. Design mirrors the
sibling `scrollback` project. Any new UI color MUST be added via
CSS custom properties in **all three** palette blocks —
`:root[data-theme="dark"]`, `:root[data-theme="light"]`, and the
`@media (prefers-color-scheme: light) :root:not([data-theme])`
duplicate that backs `auto` — never hex literals, so the toggle
covers new surfaces without follow-up work.

> **Do not write `term.setOption('theme', ...)`.** That method was
> removed in xterm.js 5.x (the vendored build). This doc previously
> prescribed it, and the code matched: the call threw on every
> toggle inside a bare `catch {}`, so the page switched palette
> while both terminals kept their boot-time colors — shipped broken
> from v3.1.0 until 2026-08-09. The retint is pinned by
> `tests/test_web_ui_smoke.py`; when touching theme code, never
> wrap the retint in a silent catch.

### Single-instance constraint (one argo-proxy + one tunnel per user per node)

The script assumes each user runs **one** argo-proxy per compute node
and **one** SSH tunnel per local port. Concrete pinch points:

- `SCREEN_SESSION="argovproxy"` is a single global constant.
  argo-proxy is always started inside the screen/tmux session named
  `argovproxy` — no per-port suffix. This is genuinely per-node
  (sessions are node-local), so it constrains one proxy *per node*.
- `~/.config/argoproxy/config.yaml` is the single argo-proxy config
  file — and on CELS `$HOME` is **NFS shared across every compute
  node**, so it is one file for all of them, not one per node. The
  heading's "per node" is therefore optimistic for anything stored in
  `$HOME` (`$HOME/argovenv`, `REMOTE_SELF`, `REMOTE_LOG` too).
  **Since 2026-08-10 the `port:` line is no longer authoritative**:
  every launcher passes `--port "$PROXY_PORT"`, which argo-proxy
  applies as an env override at config load, so the requested port
  wins and the shared file is left unmodified. That is what makes two
  nodes on two ports work concurrently (verified live). Do NOT
  reintroduce a hard refusal when the file's port disagrees — that was
  the Q10 bug, and it made multi-node use impossible without
  hand-editing a file shared by every node. See
  [`notes/impl_shared_node_transport.md`](notes/impl_shared_node_transport.md)
  "Q10 fix".
- `local_tunnel_status` checks "is something on this port?" — can't
  tell which destination the tunnel targets. (`status` now surfaces
  the real destination separately via `local_tunnel_destination`.)

Implications:

- A user who runs `client` twice with **different ports on the same
  node** would silently destroy the first run's argo-proxy (the second
  run's bootstrap kills the existing screen session that happens to
  share the name). The detect-and-warn check in `mode_server`
  (introduced in audit fix G1) catches this and asks before killing.
- A user who runs `client` twice with **same port to different nodes**
  would silently reuse the first tunnel (which targets the first
  node). The detect-and-warn check in `ensure_or_reuse_tunnel` (also
  G1) catches this and refuses.
- `status` / `stop` / `clean` operate on a single `PROXY_PORT` value.
  No "show me ALL my tunnels" view exists.

Lifting the constraint is documented as out-of-scope for v2.0 but the
touchpoints are listed in PLAN.md Open Questions.

### `clean` subcommand risk tiers

Three risk tiers:

- **safe items** (state dir, mux sockets, tunnel, remote venv) deleted
  on global confirmation;
- **risky items** (OpenCode/argo-proxy configs and their `.bak.*`
  backups) get a per-file prompt;
- **non-interactive flags** for risky items: `--purge` opts into
  deletion of files + backups; `--purge-backups` only kills backups.
  Both flags skip the per-file prompt even without `-y` (the user
  explicitly opted into a destructive action).

`--dry-run` previews; `--local-only` skips remote.

### Smoke tests

After non-trivial edits:

```sh
bash -n argo-anywhere.sh                              # syntax
bash argo-anywhere.sh -h                              # short usage
bash argo-anywhere.sh help | head -50                 # long help renders
bash argo-anywhere.sh status                          # exit 1 if no tunnel
bash argo-anywhere.sh clean --dry-run -y --local-only # safe enumeration
```

The `status` summary's "ALL GREEN" branch only fires when the
script's tunnel is actually up — keep one running while you work if
you want full coverage.

For end-to-end verification (real SSH, real Duo prompt, real
argo-proxy on a compute node), follow [`docs/TESTING.md`](docs/TESTING.md).
Run before tagging a release and after any change to the prompt flow,
env-var handling, or SSH option logic.

## Citation + archival policy

- **CITATION.cff**: not yet (queued for first DOI release at v2.0.0
  tag; see PLAN.md Open Questions).
- **Zenodo handshake**: not yet (queued).
- **DOI**: none yet.
- **Software Heritage SWHID**: N/A.

---

*Created 2026-05-14 by Ahmed Attia (with substantial AI assistance
from Claude per [`CONTRIBUTORS.md`](CONTRIBUTORS.md)). Bootstrapped
from
[`scicomp-research-skills/templates/software-skeleton/`](https://github.com/a-attia/scicomp-research-skills/tree/main/templates/software-skeleton)
on 2026-05-14, replacing the project's prior 457-line ad-hoc AGENTS.md
(content migrated per the project-onboarding skill's content-check
discipline; full migration plan recorded in
`notes/agent_feedback.md` entry 1).*
