#!/usr/bin/env bash
# argo-anywhere.sh -- the canonical (and only) orchestrator file.
#
# Self-contained orchestrator that lets Argonne users run AI coding CLI
# tools (OpenCode, Claude Code, ...) against argo-proxy from anywhere
# (inside or outside the ANL network).
#
# As of v2.0 the script is shipped as a SINGLE file. Per-tool selection is
# explicit via --cli-tool <name> or the interactive picker. The pre-v2.0
# argo_opencode.sh / argo_claudecode.sh symlink-based UX was removed (it
# broke under git core.symlinks=false and on filesystems that don't
# preserve symlinks). See docs/AUDIT_2026-05-12.md for the rationale.
#
# Subcommands (run `argo-anywhere.sh help` for the full guide):
#   argo-anywhere.sh client --cli-tool NAME  # install + tunnel + monitor
#   argo-anywhere.sh setup                   # picker + install + tunnel
#   argo-anywhere.sh tunnel                  # tunnel only (no install)
#   argo-anywhere.sh server                  # runs on the ANL compute node
#   argo-anywhere.sh status                  # check tunnel + proxy health
#   argo-anywhere.sh stop                    # tear down the local tunnel
#   argo-anywhere.sh update-models           # refresh OpenCode model list
#   argo-anywhere.sh list-models             # tabulate models served by /v1/models
#   argo-anywhere.sh clean                   # remove every artifact created
#   argo-anywhere.sh list-tools              # print supported --cli-tool values
#   argo-anywhere.sh help                    # long-form guide
#   argo-anywhere.sh -h | --help             # short usage
#
# Distribution: https://github.com/a-attia/argo-anywhere
# (Pre-v2.0 repo name was a-attia/argo-opencode; GitHub auto-redirects
# old curl/clone URLs forever, so legacy users keep working unchanged.)
# Users (latest):
#   curl -fsSL https://raw.githubusercontent.com/a-attia/argo-anywhere/main/argo-anywhere.sh -o argo-anywhere.sh
#   bash argo-anywhere.sh
# Users (pinned to a release tag, recommended for stability):
#   curl -fsSL https://raw.githubusercontent.com/a-attia/argo-anywhere/v2.0.0/argo-anywhere.sh -o argo-anywhere.sh
#   bash argo-anywhere.sh
#
# Author: Ahmed Attia (attia@anl.gov)
# License: same as the surrounding repo.

# Re-exec under bash if the script was invoked via 'sh' or another POSIX shell.
# This protects bash-only constructs (arrays, [[ ]], process substitution
# `<(...)`, etc.) on systems where /bin/sh is dash, busybox, or -- importantly
# on macOS -- bash invoked in POSIX-compatibility mode.
#
# Two distinct cases the guard must catch:
#   1. /bin/sh is something other than bash (Linux: dash, busybox, ash).
#      BASH_VERSION is unset under those shells, so [ -z ... ] catches them.
#   2. /bin/sh IS bash but in POSIX mode (macOS: /bin/sh is bash 3.2 with
#      POSIXLY_CORRECT=y baked in). Here BASH_VERSION is SET (e.g.
#      "3.2.57(1)-release") so the unset check passes -- but the parser
#      still rejects process substitution and other extensions, blowing up
#      mid-script. We additionally check POSIXLY_CORRECT to force the re-exec
#      under a clean, non-POSIX `bash`.
#
# Bug history: without the POSIXLY_CORRECT branch above (the "macOS-sh-is-
# bash-in-POSIX-mode" bug), `sh argo-anywhere.sh` on macOS ran as far as
# opening the tunnel before bombing on `<(...)` in gather_summary. The
# re-exec now happens before any non-POSIX construct can be parsed.
if [ -z "${BASH_VERSION:-}" ] || [ -n "${POSIXLY_CORRECT:-}" ]; then
  # Drop POSIXLY_CORRECT so the re-exec'd bash doesn't inherit POSIX mode
  # via the env. (`exec bash` alone would re-set it from the inherited env.)
  unset POSIXLY_CORRECT
  exec bash "$0" "$@"
fi

set -euo pipefail

# ============================================================================
# C1 fix: self-integrity check (inlined, no function call)
# ============================================================================
# Detect corrupted-script-on-disk situations early, before bash hits
# any of the real script's logic and produces a cryptic error.
#
# Why inlined (no function call):
#   * If the file was truncated mid-function-definition, calling a
#     function defined later would itself fail. The check has to be
#     a straight-line block early in the file so it can fire even on
#     heavily-truncated copies.
#
# What we check:
#   * `$0` resolves to a real file (skip checks for `bash -c`, stdin
#     pipes, etc. -- those can't have the corruption mode).
#   * That file is at least 10KB. The real argo-anywhere.sh is >100KB;
#     anything under 10KB is broken (truncated download, materialised
#     symlink-as-text, etc.).
#
# Why this exists:
#   * Pre-v2.0 the repo shipped argo_opencode.sh as a git mode-120000
#     symlink. Cloning with core.symlinks=false (Windows default; some
#     hardened Linux configs) materialised the symlink as a 16-byte
#     text file containing the literal string "argo-anywhere.sh".
#     Running `bash argo_opencode.sh` then tried to execute
#     "argo-anywhere.sh" as a command on line 1 -- the cryptic
#     "command not found" was the root cause of "Bug 1" on compute-386-01.
#   * v2.0 removed all symlinks, so this specific failure mode can't
#     reproduce from a fresh clone of main. But a user who clones an
#     OLD commit (`git checkout v1.2.0`) OR has a stale
#     ~/.argo_opencode.sh on a compute node can still hit it.
#   * Truncated curl downloads produce a similar symptom.
#
# Limitation: when the file is SO tiny (16 bytes / one filename on
# line 1) that bash dies on line 1 before reaching this check, only
# documentation can help. UPGRADING.md and the README will surface
# the recovery procedure.
case "${0:-}" in
  bash|sh|-bash|-sh|/bin/bash|/bin/sh|/usr/bin/bash|/usr/bin/sh)
    : ;; # invoked via shell name; not a path -> skip check
  *)
    if [ -f "${0:-}" ]; then
      _ARGO_SELF_SIZE="$(wc -c < "$0" 2>/dev/null | tr -d '[:space:]' || echo 0)"
      [ -n "${_ARGO_SELF_SIZE:-}" ] || _ARGO_SELF_SIZE=0
      if [ "$_ARGO_SELF_SIZE" -lt 10240 ]; then
        cat >&2 <<EOF

[err ] argo-anywhere.sh: file is suspiciously small (${_ARGO_SELF_SIZE} bytes).
[err ]
[err ] The file at "${0}" is only ${_ARGO_SELF_SIZE} bytes; the real
[err ] argo-anywhere.sh is >100KB. Likely causes:
[err ]
[err ]   1. You cloned an old commit (pre-v2.0) where this name was a
[err ]      git symlink, on a system that materialises symlinks as text
[err ]      files (Windows default; some hardened Linux). The file's
[err ]      contents are the symlink's target name, not a real script.
[err ]      Fix: cd into your clone and run
[err ]           git checkout main  &&  git pull
[err ]
[err ]   2. Your curl was interrupted mid-download, leaving a partial
[err ]      file. Fix: re-download:
[err ]           curl -fsSL https://raw.githubusercontent.com/a-attia/argo-anywhere/main/argo-anywhere.sh -o argo-anywhere.sh
[err ]
[err ]   3. You scp'd a symlink instead of the real file (legacy tools
[err ]      without -L don't dereference). Fix: re-fetch via curl as
[err ]      shown above.
[err ]
[err ] Refusing to execute a corrupted script.

EOF
        exit 2
      fi
      unset _ARGO_SELF_SIZE
    fi
    ;;
esac

# ============================================================================
# TABLE OF CONTENTS
# ============================================================================
# Sections in order of appearance (grep for "SECTION:" to jump):
#
#   1.  LEGACY ENV SNAPSHOT      -- capture inherited env before reassignment
#   2.  USER-EDITABLE CONFIG     -- ANL_NODES, ANL_JUMP, defaults
#   3.  PRETTY PRINTING          -- colors, log/ok/warn/err/die/ask
#   4.  BOX DRAWING              -- print_summary_box and helpers
#   5.  PLATFORM HELPERS         -- detect_os, this_host_fqdn, on_anl_compute_node,
#                                   _my_interface_ips, host_is_target, notify_user
#   6.  ENV NAMESPACING          -- legacy -> ARGO_ANYWHERE_* promotion
#   7.  PORT RESOLUTION          -- read from config, --port handling
#   8.  JUMP HOST HANDLING       -- ssh_jump_args, jump_descr
#   9.  MFA / SSH MULTIPLEXING   -- mfa_enabled, SSH attempt tracker
#                                   (ssh_attempt_pre/ok/fail), ssh_mux_args,
#                                   ssh_mux_close_all, ssh_args, ssh_reachable,
#                                   ssh_mux_open
#   10. USERNAME RESOLUTION      -- resolve_username, cache I/O
#   11. CONFIG FILE HANDLING     -- handle_config_file (k/b/d/m/a prompt)
#   12. OPENCODE CONFIG WRITER + INSTALLER -- write_opencode_config,
#                                   ensure_opencode_installed,
#                                   setup_opencode_cli_tool
#   13. SSH PREFLIGHT            -- ssh_preflight (jump or first node)
#   14. NODE PICKER              -- pick_node, --node, --probe-nodes
#   15. REMOTE BOOTSTRAP         -- scp + ssh to invoke server mode
#   16. LOCAL TUNNEL + HEALTH MONITOR -- cleanup_local, spawn_health_monitor,
#                                   open_tunnel, monitor_tunnel_loop;
#                                   collision detection: local_tunnel_status,
#                                   probe_remote_port_owner,
#                                   find_next_free_remote_port,
#                                   prompt_port_collision, ensure_or_reuse_tunnel
#   17. CLIENT / TUNNEL MODES    -- _client_common_setup, mode_tunnel, mode_client
#   18. SERVER MODE              -- mode_server (runs on the ANL node;
#                                   also called in-process by the on-node
#                                   short-circuit in _client_common_setup)
#   19. SUMMARY GATHERING        -- fetch_proxy_models, gather_summary
#   20. SUMMARY RENDERING        -- render_summary (the big box)
#   21. STATUS / STOP            -- mode_status, mode_stop
#   22. UPDATE-MODELS + LIST-MODELS -- mode_update_models, mode_list_models
#   23. CLEAN HELPERS            -- _clean_rm, _clean_risky_file
#   24. CLEAN MODE               -- mode_clean (local + remote)
#   25. HELP / DISPATCH          -- usage, long_help, main
#
# CRITICAL INVARIANTS:
#   * Targets bash 3.2+ (macOS default). No bash-4 features.
#   * Never use `var="$(cat <<'EOS' ... EOS)"` -- bash 3.2 + set -u quirk.
#     Write multi-line scripts to temp files via mktemp instead.
#   * `set -euo pipefail` is on. Be deliberate with ssh/curl/jq exit codes;
#     wrap with `|| true` where non-zero is expected.
#   * Port comes from `~/.config/opencode/config.json` baseURL by default.
#     `--port`/ARGO_ANYWHERE_PORT override but prompt before mutating config.
#   * MFA mode (default) opens an SSH ControlMaster; subsequent calls reuse
#     the socket. Sockets at ~/.ssh/sockets/argo-anywhere-*. `clean` closes
#     them (and also closes any legacy argo-opencode-* sockets from v1.x).
# ============================================================================

# ============================================================================
# SECTION: 1. LEGACY ENV SNAPSHOT
# ============================================================================
# Capture inherited env-var values BEFORE the user-editable config block
# (re)assigns the same names. Promotion to ARGO_ANYWHERE_* happens later
# in the script, but it must read the inherited values, not the defaults.
#
# Two generations of legacy names are honored, in oldest-to-newest order:
#
#   1. Pre-namespace (oldest): PROXY_PORT, ANL_USERNAME, SHOW_MODELS.
#      Honored as deprecated aliases of the canonical ARGO_ANYWHERE_*
#      names with a one-time WARN per stale var per run.
#
#   2. Pre-rename (v1.x era; "argo_opencode" naming): ARGO_ANYWHERE_<X>
#      for every X used by the script. Honored as deprecated aliases of
#      ARGO_ANYWHERE_<X>. Same one-time WARN behavior.
#
# Direct user code that exports either generation in shell rc files keeps
# working; the user just sees a one-line WARN on the first script run
# after upgrading. Section 6 does the actual promotion.
_legacy_PROXY_PORT="${PROXY_PORT:-}"
_legacy_ANL_USERNAME="${ANL_USERNAME:-}"
_legacy_SHOW_MODELS="${SHOW_MODELS:-}"
# Pre-rename ARGO_ANYWHERE_* snapshot.
_legacy_ARGO_OPENCODE_USER="${ARGO_OPENCODE_USER:-}"
_legacy_ARGO_OPENCODE_PORT="${ARGO_OPENCODE_PORT:-}"
_legacy_ARGO_OPENCODE_NODE="${ARGO_OPENCODE_NODE:-}"
_legacy_ARGO_OPENCODE_NO_JUMP="${ARGO_OPENCODE_NO_JUMP:-}"
_legacy_ARGO_OPENCODE_NO_MFA="${ARGO_OPENCODE_NO_MFA:-}"
_legacy_ARGO_OPENCODE_FORCE_REINSTALL="${ARGO_OPENCODE_FORCE_REINSTALL:-}"
_legacy_ARGO_OPENCODE_SHOW_MODELS="${ARGO_OPENCODE_SHOW_MODELS:-}"
_legacy_ARGO_OPENCODE_CONTROL_PERSIST="${ARGO_OPENCODE_CONTROL_PERSIST:-}"
_legacy_ARGO_OPENCODE_AUTO_PORT="${ARGO_OPENCODE_AUTO_PORT:-}"
_legacy_ARGO_OPENCODE_PORT_RANGE="${ARGO_OPENCODE_PORT_RANGE:-}"
_legacy_ARGO_OPENCODE_KEEP_ORPHANS="${ARGO_OPENCODE_KEEP_ORPHANS:-}"
_legacy_ARGO_OPENCODE_DROP_ORPHANS="${ARGO_OPENCODE_DROP_ORPHANS:-}"
# NOTE: _LOGGING (renamed to _ARGO_ANYWHERE_REEXEC in Phase 2e) was
# an INTERNAL sentinel never set by users; no legacy snapshot needed.
# B1a (Phase 4): CLAUDECODE_SCOPE is being deprecated in favor of
# ARGO_ANYWHERE_SCOPE (matches the project's *_ANYWHERE_* user-facing
# namespace per D-009). Snapshot it so the Section 6 promotion block
# can issue the one-time deprecation warning.
_legacy_CLAUDECODE_SCOPE="${CLAUDECODE_SCOPE:-}"

# ============================================================================
# SECTION: 2. USER-EDITABLE CONFIG
# ============================================================================
# Script-version string used by `update argo-anywhere` for the
# installed-vs-upstream comparison and by `status` / `help` for display.
# Bump in lockstep with `git tag vX.Y.Z` on release (per the PLAN.md
# release process). Format: "<major>.<minor>.<patch>" with optional
# "-rc<N>" / "-dev" suffix for pre-release builds; _extract_version
# normalizes both forms.
SCRIPT_VERSION="2.2.1-dev"

# Canonical install root for the script itself (managed by the
# bootstrap helper triggered on first 'client' / 'setup' run, and by
# the 'update argo-anywhere' subcommand). Contains:
#   * argo-anywhere.sh   -- the script itself (PATH-discoverable)
#   * env                -- sourceable PATH-setup helper (rustup style)
# The user adds `. ~/.argo_anywhere/env` (or equivalent) to their shell
# rc; the script never edits the rc directly. Per D-023 (PLAN.md):
# canonical install lives at $HOME/.argo_anywhere (a directory; do NOT
# confuse with the legacy $HOME/.argo-anywhere.sh single-file path used
# on the REMOTE compute node for the scp'd self-copy; that path is the
# REMOTE_SELF constant below).
ARGO_INSTALL_DIR="${HOME}/.argo_anywhere"
# bin/ layout (Lifecycle Phase C / D-025 D-a): the script + thin
# install/uninstall wrappers live under bin/ so there's a canonical,
# sweepable location. ARGO_INSTALL_SCRIPT points at the bin/ copy;
# ARGO_INSTALL_SCRIPT_FLAT is the pre-Phase-C (D-023) flat location kept
# only for one-shot migration detection.
ARGO_INSTALL_BIN_DIR="${ARGO_INSTALL_DIR}/bin"
ARGO_INSTALL_SCRIPT="${ARGO_INSTALL_BIN_DIR}/argo-anywhere.sh"
ARGO_INSTALL_SCRIPT_FLAT="${ARGO_INSTALL_DIR}/argo-anywhere.sh"
ARGO_INSTALL_WRAP_INSTALL="${ARGO_INSTALL_BIN_DIR}/install"
ARGO_INSTALL_WRAP_UNINSTALL="${ARGO_INSTALL_BIN_DIR}/uninstall"
ARGO_INSTALL_ENV="${ARGO_INSTALL_DIR}/env"

# Install manifest (D-025 D-c; Lifecycle Phase A). Records, at FIRST touch
# of each client config, whether the file pre-existed and where its
# original backup lives, plus which tool binaries this script installed.
# Read by the `uninstall` subcommand to restore client configs to their
# pre-argo-anywhere state correctly (delete files we created; restore the
# true pre-argo backup for files we modified) and to remove only the tool
# binaries we installed. Laptop-side only (never written on a compute
# node). First-touch-wins: an existing entry is never overwritten, so the
# earliest recorded provenance is the true original.
#
# D-030: the manifest now lives with the rest of the laptop state
# (STATE_DIR) rather than under the canonical install dir, so it survives
# package mode -- where ~/.argo_anywhere/ is never created (the package
# owns the runtime; the engine's self-install stays dormant). ARGO_MANIFEST
# is defined in the state-dir block below because it references STATE_DIR;
# ARGO_MANIFEST_LEGACY is the pre-D-030 home, kept only so an existing
# manifest is migrated once (_manifest_migrate_home).
ARGO_MANIFEST_LEGACY="${ARGO_INSTALL_DIR}/manifest.json"
ARGO_MANIFEST_SCHEMA=1

# GitHub project coordinates for `update argo-anywhere`. PROJECT_REPO
# is the "owner/repo" slug; PROJECT_RAW_URL_PREFIX is the
# raw.githubusercontent.com prefix (without the ref; the ref is
# appended at fetch time, either the latest release tag or the fallback
# branch). PROJECT_RELEASES_API is the GitHub Releases API endpoint.
PROJECT_REPO="a-attia/argo-anywhere"
PROJECT_RAW_URL_PREFIX="https://raw.githubusercontent.com/${PROJECT_REPO}"
PROJECT_RELEASES_API="https://api.github.com/repos/${PROJECT_REPO}/releases/latest"
PROJECT_DEFAULT_BRANCH="main"

# Add or remove ANL compute nodes here. The client probes them in order and
# uses the first one reachable through the jump host (or lets the user pick).
# To add a node, append a fully-qualified hostname.
ANL_NODES=(
  compute-01.cels.anl.gov
  compute-02.cels.anl.gov
  compute-03.cels.anl.gov
  compute-04.cels.anl.gov
  # compute-05.cels.anl.gov  # <-- frequently down
  compute-06.cels.anl.gov
  # compute-07.cels.anl.gov  # <-- frequently down
  compute-08.cels.anl.gov
  # compute-09.cels.anl.gov  # <-- frequently down
  compute-10.cels.anl.gov
  # compute-11.cels.anl.gov  # <-- frequently down
  compute-12.cels.anl.gov
  compute-13.cels.anl.gov
  # compute-14.cels.anl.gov  # <-- frequently down
  compute-15.cels.anl.gov
  # compute-xx.cels.anl.gov   # <-- example: uncomment / add more here
)

ANL_JUMP="logins.cels.anl.gov"
# Default port used only when no other source resolves one. Resolution order:
#   1. --port CLI flag            (one-shot override; offers to migrate config)
#   2. ARGO_ANYWHERE_PORT env var (canonical override)
#   3. PROXY_PORT env var         (deprecated alias; warns once)
#   4. baseURL in ~/.config/opencode/config.json   (the source of truth)
#   5. PROXY_PORT_DEFAULT below   (used only on first install)
PROXY_PORT_DEFAULT=64742
PROXY_PORT=""                      # populated by resolve_port() in main()
# shellcheck disable=SC2016
VENV_PATH='$HOME/argovenv'         # path on the ANL node (single quotes intentional;
                                   # $HOME is expanded server-side via `eval echo`)
SCREEN_SESSION="argovproxy"
# v2.0 renamed agovenv -> argovenv and agovproxy -> argovproxy for naming
# consistency (see docs/AUDIT_2026-05-12.md, revised D4 inventory). The
# legacy names below are detected on compute nodes by mode_server (warns
# the user) and by `clean` (enumerates both for cleanup) so anyone who
# upgraded from a v1.x install still gets a clean migration path.
# shellcheck disable=SC2016
LEGACY_VENV_PATH='$HOME/agovenv'
LEGACY_SCREEN_SESSION="agovproxy"
HEALTH_INTERVAL=15                 # seconds between health probes (client-side)
HEALTH_FAIL_THRESHOLD=3            # consecutive failures before alerting

# Local state directory (laptop side). Canonical name as of v2.0 is
# argo_anywhere; the legacy argo_opencode dir is migrated automatically
# at startup (see migrate_state_dir at the bottom of section 5).
STATE_DIR="${HOME}/.config/argo_anywhere"
LEGACY_STATE_DIR="${HOME}/.config/argo_opencode"
USER_CACHE="${STATE_DIR}/user"
NODE_CACHE="${STATE_DIR}/node"
# B2 (Phase 4): port becomes a transport-layer cache file per D-020.
# Pre-Phase-4 the script derived PROXY_PORT from the OpenCode config
# baseURL (which made the OpenCode config the de-facto source of truth
# for the port -- M4 audit finding called this out as OpenCode-specific
# in a multi-client world). Phase 4 elevates the port to script-managed
# state alongside user + node; per-tool client configs become downstream
# renderings that receive the port from the cache. Closes M4.
PORT_CACHE="${STATE_DIR}/port"
# D-030: the install manifest lives with the rest of the laptop state (see
# the manifest comment block in the install-dir section above). Defined
# here because it references STATE_DIR; migrated once from
# ARGO_MANIFEST_LEGACY by _manifest_migrate_home.
ARGO_MANIFEST="${STATE_DIR}/manifest.json"

# OpenCode config paths (read by us, written by setup_opencode_cli_tool +
# update-models). Centralized constants so future renames touch one site.
#
# B1b (Phase 4): added OPENCODE_PROJECT_CONFIG_BASENAME for the
# new --scope project support. The global is the existing path; the
# project basename is what we write at the git-root (or cwd fallback)
# when --scope project is chosen for opencode. OPENCODE_CONFIG is kept
# as an alias for the global path (existing callers; e.g. update-models)
# so nothing else needs to change for the global-only path.
#
# Filename note: the current OpenCode upstream docs reference
# `opencode.json` as the canonical name; this script has historically
# written `config.json`. Both are accepted by recent OpenCode versions.
# Phase 4 keeps `config.json` for backward compatibility with users'
# existing configs; a future audit (or a real-world report of the
# rename biting) can flip the global path with a one-shot migration.
OPENCODE_GLOBAL_CONFIG="${HOME}/.config/opencode/config.json"
OPENCODE_CONFIG="${OPENCODE_GLOBAL_CONFIG}"  # legacy alias; existing callers
OPENCODE_PROJECT_CONFIG_BASENAME="opencode.json"

# Claude Code config paths.
#
# Per Anthropic's docs, Claude Code reads three files in precedence order
# (most-specific wins, but the `env` block is REPLACED wholesale across
# scopes -- it is NOT deep-merged):
#   ./.claude/settings.local.json   project-local (gitignored by default)
#   ./.claude/settings.json         project-shared (committed)
#   ~/.claude/settings.json         user/global
# We write to either the global or project-local scope (never to the
# committed shared file -- that would force the user's collaborators to
# also use this proxy). claudecode_pick_scope() decides which.
CLAUDECODE_GLOBAL_CONFIG="${HOME}/.claude/settings.json"
CLAUDECODE_PROJECT_CONFIG="./.claude/settings.local.json"

# aider config paths (read by us, written by setup_aider_cli_tool).
#
# aider searches for its YAML config (`.aider.conf.yml`) in this order,
# last-wins: home dir -> git-root -> cwd (plus an explicit --config path
# we do not use). We write to either the global (home) file or a
# project-local file at the git-root (cwd fallback). The project basename
# matches aider's own discovery name so the file we write is the file
# aider reads. See <https://aider.chat/docs/config/aider_conf.html>.
AIDER_GLOBAL_CONFIG="${HOME}/.aider.conf.yml"
AIDER_PROJECT_CONFIG_BASENAME=".aider.conf.yml"

# Remote paths (compute node side). Canonical name is hyphenated
# (argo-anywhere) as of v3.0.0 (D-028). `clean` sweeps BOTH legacy
# generations so upgraders leave nothing orphaned on a node:
#   * v1.x underscore-opencode: .argo_opencode.*      (LEGACY_REMOTE_*)
#   * v2.x underscore-anywhere: .argo_anywhere.*       (LEGACY_REMOTE_*_V2)
REMOTE_SELF=".argo-anywhere.sh"
REMOTE_LOG=".argo-anywhere.server.log"
LEGACY_REMOTE_SELF=".argo_opencode.sh"
LEGACY_REMOTE_LOG=".argo_opencode.server.log"
LEGACY_REMOTE_SELF_V2=".argo_anywhere.sh"
LEGACY_REMOTE_LOG_V2=".argo_anywhere.server.log"

# ============================================================================
# SECTION: 3. PRETTY PRINTING (colors + log/ok/warn/err/die/ask)
# ============================================================================
if [ -t 1 ]; then
  C_RED=$'\033[1;31m'; C_GRN=$'\033[1;32m'; C_YLW=$'\033[1;33m'
  C_BLU=$'\033[1;34m'; C_DIM=$'\033[2m'; C_OFF=$'\033[0m'
else
  C_RED=""; C_GRN=""; C_YLW=""; C_BLU=""; C_DIM=""; C_OFF=""
fi

log()  { printf '%s[argo-anywhere]%s %s\n' "$C_BLU" "$C_OFF" "$*" >&2; }
ok()   { printf '%s[ ok ]%s %s\n' "$C_GRN" "$C_OFF" "$*" >&2; }
warn() { printf '%s[warn]%s %s\n' "$C_YLW" "$C_OFF" "$*" >&2; }
err()  { printf '%s[err ]%s %s\n' "$C_RED" "$C_OFF" "$*" >&2; }
die()  { err "$*"; exit 1; }
# ask: prompt the user for input. Args: <prompt-text> [<default-value>].
#
# M10 fix (audit Phase 2d, default-with-WARN per user choice): when stdin
# is not a TTY, return the default value WITH a one-time WARN naming
# the prompt + the default. Pre-fix the script silently used the default,
# which was correct for the legitimate non-TTY scenario (mode_server
# under tee'd re-exec) but invisible in other non-TTY scenarios
# (curl|bash, CI, automation). The WARN is suppressed when
# _ARGO_ANYWHERE_REEXEC=1 (the tee'd re-exec sentinel set by mode_server's
# bootstrap) -- in that case the silent-default behavior IS correct and
# expected. In all other non-TTY cases, the WARN surfaces what got
# auto-answered so the user can see whether the default is what they
# wanted.
#
# When stdin is NOT a TTY AND there's no default, ask() still returns
# empty (matching pre-fix behavior). Callers that can't accept an empty
# answer (e.g. resolve_username's username prompt) should die with a
# clear "set ARGO_ANYWHERE_USER in env to skip this prompt" message;
# they were already doing so via the [-z reply] checks in their loops.
ask()  {
  local p="$1" def="${2:-}" reply
  if [ -t 0 ] || [ "${_ARGO_ANYWHERE_REEXEC:-0}" = 1 ]; then
    # Interactive TTY OR the legitimate tee'd-re-exec scenario:
    # behave exactly as before (no warn; silent default if read fails).
    printf '%s%s%s ' "$C_YLW" "$p" "$C_OFF" >&2
    read -r reply || true
    printf '%s' "${reply:-$def}"
  else
    # Non-TTY in an unexpected scenario (curl|bash, CI, automation).
    # Surface the auto-answer so the user knows which prompt got
    # the default (and what the default was).
    if [ -n "$def" ]; then
      warn "non-interactive (stdin is not a TTY); auto-answering prompt"
      warn "  '${p}' with default '${def}'."
    else
      warn "non-interactive (stdin is not a TTY) and no default for prompt"
      warn "  '${p}'; returning empty (caller may die)."
    fi
    printf '%s' "${def}"
  fi
}

# ============================================================================
# SECTION: 4. BOX DRAWING (Unicode vs ASCII detection + print_summary_box)
# ============================================================================
# Prefer Unicode if the terminal looks UTF-8 capable, else ASCII.
# Set ARGO_BOX_STYLE=ascii or =unicode to force.
#
# IMPORTANT: the TTY test ([ -t 1 ]) MUST run in the script's main shell,
# not inside `$(detect_box_style)`. Command substitution rewires the
# subshell's stdout to a pipe so the parent can capture the result, which
# means [ -t 1 ] is always false inside `$(...)`. Asking the function
# itself was the original implementation and silently disabled the
# Unicode branch even on real terminals -- the script always fell back to
# ASCII. We now snapshot the parent's TTY status into _STDOUT_IS_TTY
# first, and detect_box_style reads that.
if [ -t 1 ]; then _STDOUT_IS_TTY=1; else _STDOUT_IS_TTY=0; fi
detect_box_style() {
  case "${ARGO_BOX_STYLE:-}" in
    ascii)   echo ascii; return ;;
    unicode) echo unicode; return ;;
  esac
  # Heuristic: locale advertises UTF-8 AND the script's stdout is a TTY.
  if [ "${_STDOUT_IS_TTY:-0}" = 1 ] \
     && printf '%s' "${LC_ALL:-${LC_CTYPE:-${LANG:-}}}" \
        | grep -qiE 'utf-?8'; then
    echo unicode
  else
    echo ascii
  fi
}
BOX_STYLE="$(detect_box_style)"
if [ "$BOX_STYLE" = "unicode" ]; then
  BOX_TL='╔'; BOX_TR='╗'; BOX_BL='╚'; BOX_BR='╝'
  BOX_H='═';  BOX_V='║';  BOX_ML='╠'; BOX_MR='╣'; BOX_MH='─'
else
  BOX_TL='+'; BOX_TR='+'; BOX_BL='+'; BOX_BR='+'
  BOX_H='='; BOX_V='|'; BOX_ML='+'; BOX_MR='+'; BOX_MH='-'
fi

# Visible width of a string after stripping ANSI color escapes. Used for
# padding so colored content lines up with the box's right edge.
visible_width() {
  local s="$1"
  # Strip ESC[...m sequences, then count chars.
  s="$(printf '%s' "$s" | sed $'s/\033\\[[0-9;]*m//g')"
  printf '%d' "${#s}"
}

# Repeat a (possibly multibyte) string N times. printf '%.0s' trick is the
# cheapest portable way that handles both ASCII and Unicode chars.
repeat_str() {
  local s="$1" n="$2" out="" i=0
  while [ "$i" -lt "$n" ]; do out="${out}${s}"; i=$((i+1)); done
  printf '%s' "$out"
}

# print_summary_box <title> <verdict-color> <verdict-text> <line1> <line2> ...
# Each subsequent arg is one body line (may contain ANSI codes).
#
# Section headers: any body-line argument starting with the literal sentinel
# "__SECTION__:" is rendered as a labeled section break:
#   1. a thin horizontal rule (BOX_ML + BOX_MH... + BOX_MR), then
#   2. a row containing the section name (text after the prefix) in C_BLU.
# Subsequent rows in that section are rendered as ordinary body lines.
# The first section header is preceded by the verdict separator only (no
# duplicate rule). Plain (non-sentinel) lines render exactly as before, so
# callers that don't use sections (e.g. mode_clean's plan box) are
# unaffected.
print_summary_box() {
  local title="$1" vcolor="$2" verdict="$3"; shift 3
  local lines=("$@")
  local _SECT_PREFIX='__SECTION__:'

  # Compute interior width = max of (title, verdict, all body lines), capped.
  # Section-header rows contribute their LABEL width (without the sentinel).
  local maxw=0 w line
  w="$(visible_width "$title")"; [ "$w" -gt "$maxw" ] && maxw="$w"
  w="$(visible_width "$verdict")"; [ "$w" -gt "$maxw" ] && maxw="$w"
  for line in "${lines[@]}"; do
    case "$line" in
      "${_SECT_PREFIX}"*) line="${line#"${_SECT_PREFIX}"}" ;;
    esac
    w="$(visible_width "$line")"; [ "$w" -gt "$maxw" ] && maxw="$w"
  done
  # Pad: 1 space on each side inside the box.
  local inner=$((maxw + 2))
  # Cap at terminal width if we can read it.
  local cols
  if command -v tput >/dev/null 2>&1 && [ -t 2 ]; then
    cols="$(tput cols 2>/dev/null || echo 100)"
  else
    cols=100
  fi
  local maxinner=$((cols - 2))
  if [ "$inner" -gt "$maxinner" ]; then inner="$maxinner"; fi

  local hbar; hbar="$(repeat_str "$BOX_H" "$inner")"
  local mbar; mbar="$(repeat_str "$BOX_MH" "$inner")"

  # Helper to emit one body line with correct padding. Truncates uncolored
  # content (with an ellipsis) when it would overflow the box's right edge.
  _bx_line() {
    local content="$1" color="${2:-}" pad
    local maxc=$((inner - 2))   # 1 leading space + 1 trailing space
    local vw; vw="$(visible_width "$content")"
    # The 'maxc > 3' gate handles a pathological narrow-terminal case: if
    # maxc <= 3 we don't have room for 'X..' (1 char + ellipsis). Real
    # terminals never go that narrow (4-col terminal would be unusable
    # for any program); if it ever happens, the line just overflows the
    # right edge -- ugly but not crashing.
    if [ "$vw" -gt "$maxc" ] && [ "$maxc" -gt 3 ]; then
      # Strip ANSI before truncating (none of the body lines carry ANSI today)
      local stripped; stripped="$(printf '%s' "$content" | sed $'s/\033\\[[0-9;]*m//g')"
      content="$(printf '%.*s' $((maxc - 3)) "$stripped")..."
      vw="$(visible_width "$content")"
    fi
    pad=$((inner - 1 - vw))
    if [ "$pad" -lt 0 ]; then pad=0; fi
    printf '%s%s%s %s%s%s%*s%s%s\n' \
      "$C_DIM" "$BOX_V" "$C_OFF" \
      "$color" "$content" "$C_OFF" \
      "$pad" "" \
      "$C_DIM" "$BOX_V$C_OFF"
  }

  # Helper: emit a thin-rule row (mbar between BOX_ML/BOX_MR).
  _bx_rule() {
    printf '%s%s%s%s%s\n' "$C_DIM" "$BOX_ML" "$mbar" "$BOX_MR" "$C_OFF" >&2
  }

  # Top border + title row
  printf '%s%s%s%s%s\n' "$C_DIM" "$BOX_TL" "$hbar" "$BOX_TR" "$C_OFF" >&2
  _bx_line "$title" "$C_BLU" >&2
  # Verdict row, separated by a thin rule
  _bx_rule
  _bx_line "$verdict" "$vcolor" >&2
  # Body rows. Always prefix with a thin rule (separates verdict from body).
  # For each section header we also print a rule, EXCEPT when it is the very
  # first body row -- the verdict-to-body rule already provides the visual
  # break in that case.
  if [ "${#lines[@]}" -gt 0 ]; then
    _bx_rule
    local first_body=1
    for line in "${lines[@]}"; do
      case "$line" in
        "${_SECT_PREFIX}"*)
          local label="${line#"${_SECT_PREFIX}"}"
          if [ "$first_body" -ne 1 ]; then
            _bx_rule
          fi
          _bx_line "$label" "$C_BLU" >&2
          ;;
        *)
          _bx_line "$line" "" >&2
          ;;
      esac
      first_body=0
    done
  fi
  # Bottom border
  printf '%s%s%s%s%s\n' "$C_DIM" "$BOX_BL" "$hbar" "$BOX_BR" "$C_OFF" >&2
}

# ============================================================================
# SECTION: 5. PLATFORM HELPERS (detect_os, notify_user, this_host_*)
# ============================================================================
detect_os() {
  case "$(uname -s)" in
    Darwin) echo "macos" ;;
    Linux)  echo "linux" ;;
    *)      echo "unknown" ;;
  esac
}

# this_host_fqdn: best-effort fully-qualified hostname of the local machine.
# Tries `hostname -f` first (Linux), falls back to `hostname` (macOS doesn't
# always return an FQDN from `hostname -f`). Used by on_anl_compute_node and
# host_is_target to decide if we're "already on the node we're trying to
# reach." Lower-cases the result so comparisons are case-insensitive.
this_host_fqdn() {
  local h=""
  h="$(hostname -f 2>/dev/null || true)"
  [ -n "$h" ] || h="$(hostname 2>/dev/null || true)"
  printf '%s' "$h" | tr '[:upper:]' '[:lower:]'
}

# _git_root_or_cwd: prints the absolute path of the nearest enclosing
# git repo (if any), else the current working directory. Used by
# per-tool pick_scope functions that resolve "project scope" -- the
# convention is "write at git-root if in a git repo; else write at cwd."
# Silent on failure (best-effort); always prints SOMETHING (cwd in the
# worst case).
#
# B1b (Phase 4): introduced for opencode_pick_scope. Generic helper so
# future per-tool pickers (aider, ...) can reuse the same resolution.
_git_root_or_cwd() {
  local root=""
  if command -v git >/dev/null 2>&1; then
    root="$(git rev-parse --show-toplevel 2>/dev/null || true)"
  fi
  if [ -n "$root" ]; then
    printf '%s' "$root"
  else
    printf '%s' "$(pwd)"
  fi
}

# _ensure_state_dir: create STATE_DIR if missing. Captures stderr from
# mkdir and surfaces it via die() on failure, matching the L1 fix's
# discipline (audit Phase 2c) at resolve_username -- now centralized so
# every state-dir writer (user-cache, node-cache, port-cache, ssh-fail-lock)
# benefits without duplicating the mkdir + die boilerplate.
#
# B2 (Phase 4): introduced when port-cache write joined user-cache +
# node-cache as a third state-dir writer. Pre-B2, the L1 capture lived
# only in resolve_username; the node-cache + lock-file writes used the
# older `mkdir -p ... 2>/dev/null || true` no-fail pattern, which is
# silently lossy if the state dir actually can't be created.
#
# Args: none. Reads STATE_DIR.
# Returns: 0 on success; die's on failure with the actual mkdir stderr.
_ensure_state_dir() {
  [ -d "$STATE_DIR" ] && return 0
  local _mk_err
  _mk_err="$(mkdir -p "$STATE_DIR" 2>&1)" \
    || die "Cannot create state dir '$STATE_DIR': ${_mk_err}. Set ARGO_ANYWHERE_USER + ARGO_ANYWHERE_PORT in env to skip caching."
}

# on_anl_compute_node: prints 'yes' if the local host appears to be one of
# our compute nodes, 'no' otherwise.
#
# M1 fix (audit Phase 2c): the function used to attempt two signals --
#   (1) string comparison of `hostname -f` against ANL_NODES entries
#   (2) suffix match against '.cels.anl.gov'
# Signal (1) NEVER fires in practice because ANL_NODES contains aliases
# (`compute-01.cels.anl.gov`) while `hostname -f` returns physical
# names (`compute-386-01.cels.anl.gov`), so they never string-match.
# The dead loop has been removed; signal (2) is now documented as the
# load-bearing path. If CELS ever moves nodes to a different domain
# (e.g. .alcf.anl.gov), this function silently returns "no" until the
# suffix match below is updated -- a known-and-accepted limitation.
# (The properly-correct fix would be IP-resolution comparison, but that
# trades off speed for very-rarely-hit correctness; out of scope for the
# 'no behavior change' Phase 2c+3 batch. host_is_target's signal (3) is
# the IP-resolution path; it's available to callers that need it.)
#
# Cached in a global the first time it's computed because hostname lookups
# can be slow on stalled-DNS systems.
_ON_ANL_NODE_CACHE=""
on_anl_compute_node() {
  if [ -n "$_ON_ANL_NODE_CACHE" ]; then
    printf '%s' "$_ON_ANL_NODE_CACHE"; return
  fi
  local me; me="$(this_host_fqdn)"
  local ans="no"
  if [ -n "$me" ]; then
    case "$me" in
      *.cels.anl.gov) ans="yes" ;;
    esac
  fi
  _ON_ANL_NODE_CACHE="$ans"
  printf '%s' "$ans"
}

# _my_interface_ips: print all IPv4 addresses bound to interfaces on this
# host, one per line. Used by host_is_target to handle the load-balanced-
# alias case where the user-typed hostname doesn't match `hostname -f` but
# DOES resolve to an IP we're bound to.
#
# Cross-platform: try `ip` (Linux iproute2), fall back to `ifconfig`
# (macOS, BSD, older Linux). Skip 127.0.0.1 and 0.0.0.0 -- those don't
# help for alias matching since every host has them.
_my_interface_ips() {
  if command -v ip >/dev/null 2>&1; then
    ip -o -4 addr show 2>/dev/null \
      | awk '{print $4}' \
      | cut -d/ -f1 \
      | grep -vE '^(127\.|0\.0\.0\.0$)'
  elif command -v ifconfig >/dev/null 2>&1; then
    # Match `inet <ip>` (BSD/macOS) and `inet addr:<ip>` (older Linux net-tools).
    # L2 fix (audit Phase 2c): the `gsub(/^addr:/, "", $2)` mutates the
    # second whitespace-separated field IN PLACE -- so $2 is "<ip>"
    # whether the upstream wrote `inet 1.2.3.4` or `inet addr:1.2.3.4`.
    # The mutation is intentional (cleaner than tracking which dialect
    # we're in), and `print $2` then sees the cleaned value. Reading
    # this as `gsub on the whole line` is the misread to avoid -- the
    # third arg to gsub names the target field explicitly.
    ifconfig 2>/dev/null \
      | awk '/inet (addr:)?[0-9]/{
          gsub(/^addr:/, "", $2);
          print $2
        }' \
      | grep -vE '^(127\.|0\.0\.0\.0$)'
  fi
}

# host_is_target <hostname>: prints 'yes' if <hostname> refers to this
# host. Used to detect "the node the user picked is the node we're
# already on" -- in which case skipping the SSH tunnel and pointing the
# client straight at 127.0.0.1:PORT is the right move.
#
# Three checks, in increasing order of cost:
#
#   1. String comparison against `hostname -f` (cheapest; catches
#      explicit --node compute-386-01.cels.anl.gov-style invocations).
#
#   2. DNS resolution of <hostname> compared to DNS resolution of
#      `hostname -f` (cheap; one getent each; catches the case where
#      both names resolve to the same IP without a string match).
#
#   3. DNS resolution of <hostname> intersected with our own interface
#      IPs (catches the load-balanced-alias case: user types
#      compute-01.cels.anl.gov, the alias round-robins to several
#      physical hosts including this one, the cheap string check at (1)
#      and the resolution-of-our-fqdn at (2) miss because they only
#      compare to ONE name we know we have).
# L9 fix (audit Phase 2c): cache the script-invocation-stable values
# ($me = our FQDN, $me_ip = our resolved IP, $my_ips = our interface
# IPs) so multiple host_is_target calls in one script run don't repeat
# the same lookups. pick_node's default-selection loop calls this once
# per ANL_NODES entry (10 nodes => up to 20 DNS lookups); on a stalled-
# DNS system that latency was visible. The cache is correct for our
# purposes because none of these values change during a script
# invocation: hostname is fixed, our IPs don't change mid-run, and
# the local DNS resolver's view of our FQDN is stable.
_HOST_IS_TARGET_ME=""
_HOST_IS_TARGET_ME_IP=""
_HOST_IS_TARGET_MY_IPS=""
_HOST_IS_TARGET_CACHE_INIT=0
_host_is_target_init_cache() {
  [ "$_HOST_IS_TARGET_CACHE_INIT" = 1 ] && return 0
  _HOST_IS_TARGET_ME="$(this_host_fqdn)"
  if command -v getent >/dev/null 2>&1 && [ -n "$_HOST_IS_TARGET_ME" ]; then
    _HOST_IS_TARGET_ME_IP="$(getent hosts "$_HOST_IS_TARGET_ME" 2>/dev/null | awk '{print $1; exit}')"
  fi
  _HOST_IS_TARGET_MY_IPS="$(_my_interface_ips)"
  _HOST_IS_TARGET_CACHE_INIT=1
}

host_is_target() {
  local target; target="$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]')"
  _host_is_target_init_cache
  local me="$_HOST_IS_TARGET_ME"
  [ -n "$me" ] || return 1

  # (1) cheap string comparison + short-name tolerance
  if [ "$me" = "$target" ]; then return 0; fi
  case "$me" in
    "${target}".*) return 0 ;;
  esac
  case "$target" in
    "${me}".*) return 0 ;;
  esac

  # (2) compare resolved IPs (cheap; one getent for target; our IP is
  # cached). Only attempt when getent is available (Linux) -- macOS
  # doesn't ship it but the alias-match case isn't usually relevant on
  # macOS. Skip silently if getent missing; fall through to (3) below.
  if command -v getent >/dev/null 2>&1; then
    local target_ip="$(getent hosts "$target" 2>/dev/null | awk '{print $1; exit}')"
    if [ -n "$target_ip" ] && [ -n "$_HOST_IS_TARGET_ME_IP" ] && [ "$target_ip" = "$_HOST_IS_TARGET_ME_IP" ]; then
      return 0
    fi
  fi

  # (3) does the target alias resolve to any of MY interface IPs?
  # Robust against round-robin DNS where the alias has multiple A
  # records and only some of them are us.
  local target_ips
  if command -v getent >/dev/null 2>&1; then
    target_ips="$(getent hosts "$target" 2>/dev/null | awk '{print $1}')"
  else
    # macOS / no getent: try host or dscacheutil. Best-effort; if none
    # available, return failure (we tried).
    if command -v host >/dev/null 2>&1; then
      target_ips="$(host "$target" 2>/dev/null \
                     | awk '/has address/{print $NF}')"
    elif command -v dscacheutil >/dev/null 2>&1; then
      target_ips="$(dscacheutil -q host -a name "$target" 2>/dev/null \
                     | awk '/^ip_address:/{print $2}')"
    else
      target_ips=""
    fi
  fi
  [ -n "$target_ips" ] || return 1

  [ -n "$_HOST_IS_TARGET_MY_IPS" ] || return 1

  local tip mip
  for tip in $target_ips; do
    for mip in $_HOST_IS_TARGET_MY_IPS; do
      if [ "$tip" = "$mip" ]; then
        return 0
      fi
    done
  done
  return 1
}

notify_user() {
  # Loud cross-platform notification. Args: title body
  local title="$1" body="$2"
  # L3 fix (audit Phase 2c): only emit the BEL character when stderr is
  # actually a TTY. Pre-fix, the bell would be embedded in log files
  # captured via redirection -- a cosmetic noise but visible if the log
  # is later cat'd or grep'd. The desktop notification (osascript /
  # notify-send) below is unaffected; this only gates the in-terminal
  # audible alert.
  if [ -t 2 ]; then
    printf '\a' >&2  # bell
  fi
  err "${title}: ${body}"
  case "$(detect_os)" in
    macos)
      osascript -e "display notification \"${body//\"/\\\"}\" with title \"${title//\"/\\\"}\"" 2>/dev/null || true
      ;;
    linux)
      command -v notify-send >/dev/null 2>&1 && notify-send "$title" "$body" || true
      ;;
  esac
}

# migrate_state_dir: one-shot migration of the laptop state directory from
# the v1.x location (~/.config/argo_opencode/) to the v2.0 location
# (~/.config/argo_anywhere/). Idempotent: if the new dir already exists,
# do nothing; if neither exists, do nothing (first-ever install on this
# machine; the cache will be created on demand).
#
# Per directive D3: the script DOES NOT auto-migrate by default. It
# DETECTS the legacy state and refuses to proceed, printing the exact
# rm/mv commands the user should run manually. This avoids the failure
# mode where a script-driven migration silently changes user state.
#
# Returns:
#   0   no legacy state OR new state already present (no migration needed)
#   non-zero  legacy state detected; the function has printed instructions
#             and the caller should die.
detect_legacy_state_and_block() {
  local has_legacy=0
  local legacy_items=()

  if [ -d "$LEGACY_STATE_DIR" ]; then
    has_legacy=1
    legacy_items+=("$LEGACY_STATE_DIR  (cached username/node from v1.x)")
  fi

  # Legacy mux sockets on the laptop. Only pre-v2.0 prefix; the v2.0
  # prefix (argo-anywhere-*) is current-state.
  if [ -d "$SSH_MUX_DIR" ]; then
    local sock found_legacy_socket=0
    for sock in "$SSH_MUX_DIR"/argo-opencode-*; do
      [ -e "$sock" ] || continue
      found_legacy_socket=1
      break
    done
    if [ "$found_legacy_socket" = 1 ]; then
      has_legacy=1
      legacy_items+=("${SSH_MUX_DIR}/argo-opencode-*  (SSH multiplex sockets from v1.x)")
    fi
  fi

  # Pre-v2.0 env vars. These are the ones the user might have exported
  # in .bashrc/.zshrc; we don't auto-promote them silently (section 6
  # already promotes + warns), but we surface them here as part of the
  # cleanup ladder so the user knows to remove their stale exports.
  local var stale_envs=()
  for var in ARGO_OPENCODE_USER ARGO_OPENCODE_PORT ARGO_OPENCODE_NODE \
             ARGO_OPENCODE_NO_JUMP ARGO_OPENCODE_NO_MFA \
             ARGO_OPENCODE_FORCE_REINSTALL ARGO_OPENCODE_SHOW_MODELS \
             ARGO_OPENCODE_CONTROL_PERSIST ARGO_OPENCODE_AUTO_PORT \
             ARGO_OPENCODE_PORT_RANGE ARGO_OPENCODE_KEEP_ORPHANS \
             ARGO_OPENCODE_DROP_ORPHANS; do
    eval "[ -n \"\${${var}:-}\" ]" && stale_envs+=("$var")
  done
  if [ "${#stale_envs[@]}" -gt 0 ]; then
    has_legacy=1
    legacy_items+=("env vars: ${stale_envs[*]}  (still honored, but rename to ARGO_ANYWHERE_*)")
  fi

  if [ "$has_legacy" -eq 0 ]; then
    return 0
  fi

  cat >&2 <<EOF

${C_YLW}========================================================================${C_OFF}
${C_YLW}LEGACY v1.x STATE DETECTED ON THIS MACHINE${C_OFF}
${C_YLW}========================================================================${C_OFF}

This script is v2.0+ (argo-anywhere). It detected leftover state from a
previous v1.x install (argo_opencode):

EOF
  local item
  for item in "${legacy_items[@]}"; do
    printf '  %s%s%s\n' "$C_YLW" "$item" "$C_OFF" >&2
  done
  cat >&2 <<EOF

${C_YLW}Per the v2.0 upgrade policy, the script REFUSES to run with legacy
state present.${C_OFF} You must clean up first. See UPGRADING.md in the repo
for the full ladder (minimal / moderate / aggressive). The minimal cleanup
that gets you running is:

${C_GRN}  # 1. Migrate the state cache (preserves your cached username/node):
  mv ${LEGACY_STATE_DIR} ${STATE_DIR}

  # 2. Close any v1.x SSH multiplex sockets:
  rm -f ${SSH_MUX_DIR}/argo-opencode-*

  # 3. (If you have ARGO_OPENCODE_* env vars in .bashrc/.zshrc):
  #    Rename them to ARGO_ANYWHERE_*. The script also honors the old
  #    names with a one-time deprecation warning per session, but
  #    cleaning them up now removes the warnings.${C_OFF}

After cleanup, re-run this script. If you'd rather wipe everything
and start fresh, see the 'aggressive' cleanup in UPGRADING.md.

EOF
  return 1
}

# ----------------------------------------------------------------------------
# Canonical-install bootstrap (per PLAN.md D-023)
# ----------------------------------------------------------------------------
# The script ships as a single file the user `curl`s into any directory.
# That works fine for one-off invocations, but power users want a stable,
# PATH-discoverable install at $ARGO_INSTALL_DIR (=~/.argo_anywhere/) so
# `argo-anywhere.sh ...` works from any shell.
#
# Convention (rustup / cargo style):
#   $ARGO_INSTALL_DIR/argo-anywhere.sh   the script (chmod +x)
#   $ARGO_INSTALL_DIR/env                sourceable PATH-setup helper
#
# The user adds one line to their shell rc (`. ~/.argo_anywhere/env`); the
# script NEVER edits the rc directly (decision: explicit > implicit; matches
# the user's answer in the design Q&A).
#
# Bootstrap fires only on `client` / `setup` (the canonical "I'm setting
# this up" workflows) and only when $ARGO_INSTALL_DIR does not yet exist.
# It is a no-op when:
#   * we're already running from the canonical install (`$0` -> $ARGO_INSTALL_SCRIPT)
#   * we're running on a compute node (the on-node short-circuit doesn't
#     benefit from a laptop-side canonical install; the remote bootstrap
#     uses REMOTE_SELF = ~/.argo-anywhere.sh which is a different path)
#   * $ARGO_INSTALL_DIR already exists (don't second-guess the user; that's
#     `update argo-anywhere`'s job)
#
# Skip-knob: ARGO_ANYWHERE_SKIP_BOOTSTRAP=1 in the env (or after a one-shot
# decline on the prompt).

# canonical_install_present: 0 if the canonical install exists, 1 otherwise.
canonical_install_present() {
  # Present if EITHER the new bin/ layout OR the pre-Phase-C flat layout
  # has a script. The flat case is migrated into bin/ by _install_core on
  # the next install/bootstrap; until then it still counts as installed.
  [ -d "$ARGO_INSTALL_DIR" ] && { [ -f "$ARGO_INSTALL_SCRIPT" ] || [ -f "$ARGO_INSTALL_SCRIPT_FLAT" ]; }
}

# _resolve_self_path: print the absolute path of the currently-running
# script (`$0` after readlink). Best-effort; tools/OS differences:
#   * macOS lacks GNU readlink -f; use perl Cwd::abs_path as fallback.
# Returns empty string on resolution failure (caller treats empty as
# "non-canonical location"; the bootstrap will then offer install).
_resolve_self_path() {
  local self="$0"
  # If $0 is a relative path or a bare name, prefer the discovered absolute.
  if command -v readlink >/dev/null 2>&1 && readlink -f / >/dev/null 2>&1; then
    readlink -f "$self" 2>/dev/null || true
  elif command -v perl >/dev/null 2>&1; then
    perl -MCwd=abs_path -e 'print abs_path($ARGV[0])' "$self" 2>/dev/null || true
  else
    # Last-resort: assume $0 is already absolute, or join with PWD.
    case "$self" in
      /*) printf '%s' "$self" ;;
      *)  printf '%s/%s' "$PWD" "$self" ;;
    esac
  fi
}

# _write_argo_env_file <path>: write the rustup-style sourceable PATH
# helper at <path>. Idempotent (overwrites any existing file at that
# location; the file is fully script-owned).
_write_argo_env_file() {
  local out="$1"
  cat > "$out" <<'ARGO_ENV_EOF'
#!/bin/sh
# argo-anywhere PATH helper. Source this from your shell rc to make
# `argo-anywhere.sh` (and the `install` / `uninstall` wrappers)
# discoverable as bare commands:
#
#   . "$HOME/.argo_anywhere/env"
#
# Managed by argo-anywhere.sh's install/bootstrap + `update argo-anywhere`
# helpers. Safe to re-source (idempotent PATH prepend with a presence
# guard so the entry doesn't accumulate on repeated sourcings).
#
# As of the bin/ layout the script lives in ~/.argo_anywhere/bin. The
# flat ~/.argo_anywhere entry is kept too for backward compatibility with
# pre-bin/ installs that may still have a script at the dir root.
case ":${PATH}:" in
  *:"$HOME/.argo_anywhere/bin":*)
    ;;
  *)
    export PATH="$HOME/.argo_anywhere/bin:$HOME/.argo_anywhere:$PATH"
    ;;
esac
ARGO_ENV_EOF
}

# _write_install_wrappers: write the thin bin/install + bin/uninstall
# wrappers that call `argo-anywhere.sh install` / `uninstall`. Keeps the
# single-file distribution (D-001) -- these are 3-line discoverability
# shims, not real logic. Idempotent (script-owned; overwritten each time).
_write_install_wrappers() {
  cat > "$ARGO_INSTALL_WRAP_INSTALL" <<'ARGO_WRAP_EOF'
#!/bin/sh
# Thin wrapper -> argo-anywhere.sh install (real logic lives in the
# single-file script; this exists only for `install` discoverability).
exec "$(dirname "$0")/argo-anywhere.sh" install "$@"
ARGO_WRAP_EOF
  cat > "$ARGO_INSTALL_WRAP_UNINSTALL" <<'ARGO_WRAP_EOF'
#!/bin/sh
# Thin wrapper -> argo-anywhere.sh uninstall.
exec "$(dirname "$0")/argo-anywhere.sh" uninstall "$@"
ARGO_WRAP_EOF
  chmod +x "$ARGO_INSTALL_WRAP_INSTALL" "$ARGO_INSTALL_WRAP_UNINSTALL" 2>/dev/null || true
}

# _install_core <self_abs>: materialize the canonical bin/ install from
# the running script at <self_abs>. Creates bin/, copies the script,
# writes wrappers + env, migrates a pre-Phase-C flat-layout script if
# present, and stamps the manifest's installed_at. Shared by the explicit
# `install` subcommand and the first-run bootstrap. Returns 0 on success,
# 1 on a non-fatal failure (caller decides how loud to be).
_install_core() {
  local self_abs="$1"
  if ! mkdir -p "$ARGO_INSTALL_BIN_DIR"; then
    warn "install: could not create ${ARGO_INSTALL_BIN_DIR}."
    return 1
  fi
  # Migrate a pre-Phase-C flat-layout script (D-023) into bin/ if present
  # and we're not already installing over it.
  if [ -f "$ARGO_INSTALL_SCRIPT_FLAT" ] && [ "$self_abs" != "$ARGO_INSTALL_SCRIPT_FLAT" ]; then
    log "  Migrating flat-layout script ${ARGO_INSTALL_SCRIPT_FLAT} -> ${ARGO_INSTALL_SCRIPT}"
    mv -f "$ARGO_INSTALL_SCRIPT_FLAT" "$ARGO_INSTALL_SCRIPT" 2>/dev/null || true
  fi
  if ! cp "$self_abs" "$ARGO_INSTALL_SCRIPT"; then
    warn "install: could not copy ${self_abs} -> ${ARGO_INSTALL_SCRIPT}."
    return 1
  fi
  chmod +x "$ARGO_INSTALL_SCRIPT" 2>/dev/null || true
  _write_install_wrappers
  if ! _write_argo_env_file "$ARGO_INSTALL_ENV"; then
    warn "install: could not write ${ARGO_INSTALL_ENV}; PATH integration incomplete."
  else
    chmod +x "$ARGO_INSTALL_ENV" 2>/dev/null || true
  fi
  # Stamp installed_at in the manifest (best-effort; creates the manifest
  # if it doesn't exist yet).
  _manifest_stamp_installed_at
  return 0
}

# _manifest_stamp_installed_at: set the manifest's installed_at to now if
# it isn't already set. Best-effort; laptop-side only.
_manifest_stamp_installed_at() {
  _manifest_available || return 0
  python3 - "$ARGO_MANIFEST" "$ARGO_MANIFEST_SCHEMA" <<'PYEOF' 2>/dev/null || true
import json, os, sys, tempfile, datetime
manifest, schema = sys.argv[1], int(sys.argv[2])
data = {}
if os.path.isfile(manifest):
    try:
        with open(manifest) as f:
            data = json.load(f) or {}
    except Exception:
        data = {}
if not isinstance(data, dict):
    data = {}
data.setdefault("schema", schema)
data.setdefault("configs", {})
data.setdefault("binaries", {})
if not data.get("installed_at"):
    data["installed_at"] = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
os.makedirs(os.path.dirname(manifest), exist_ok=True)
fd, tmp = tempfile.mkstemp(dir=os.path.dirname(manifest), prefix=".manifest.", suffix=".tmp")
try:
    with os.fdopen(fd, "w") as f:
        json.dump(data, f, indent=2); f.write("\n")
    os.replace(tmp, manifest)
except Exception:
    try: os.unlink(tmp)
    except Exception: pass
PYEOF
}

# _print_path_setup_hint: tell the user how to add the env file to
# their shell rc. Printed ONCE per bootstrap (and again on first
# successful `update argo-anywhere` if the env file was just rewritten).
_print_path_setup_hint() {
  local shell_name
  shell_name="$(basename "${SHELL:-/bin/sh}")"
  local rc_file=""
  case "$shell_name" in
    zsh)  rc_file="${ZDOTDIR:-$HOME}/.zshrc" ;;
    bash) rc_file="$HOME/.bashrc"            ;;
    *)    rc_file="$HOME/.profile"           ;;
  esac
  cat >&2 <<EOF

  ${C_GRN}To make 'argo-anywhere.sh' discoverable as a bare command in new shells,${C_OFF}
  ${C_GRN}add this ONE line to ${rc_file}:${C_OFF}

      . "\$HOME/.argo_anywhere/env"

  Then either open a new shell, or run:

      . "\$HOME/.argo_anywhere/env"

  in this shell to pick up the change immediately.

EOF
}

# maybe_bootstrap_canonical_install: invoked from mode_client / mode_setup
# BEFORE any other work. No-op in all the cases listed in the section
# preamble. When it does fire, it copies $0 to $ARGO_INSTALL_SCRIPT,
# writes $ARGO_INSTALL_ENV, and prints the PATH-setup hint.
#
# Honors ARGO_ANYWHERE_SKIP_BOOTSTRAP=1 (env knob; not a CLI flag --
# bootstrap is supposed to be one-shot and invisible after that, so a
# CLI flag would be overkill).
#
# Never aborts the outer flow on failure: a failed bootstrap (e.g.
# read-only $HOME, missing cp) prints a warn and proceeds; the user's
# `client` run still works from wherever $0 was invoked.
maybe_bootstrap_canonical_install() {
  # Opt-out.
  [ "${ARGO_ANYWHERE_SKIP_BOOTSTRAP:-0}" = 1 ] && return 0

  # D-030a: dormant under the Python package. The package (pipx/pip) owns the
  # runtime; a canonical self-install would be a divergent second copy of the
  # engine (the two-homes drift D-029 warns about). The engine still runs
  # fine from wherever the package invoked it.
  [ "${ARGO_ANYWHERE_PACKAGED:-0}" = 1 ] && return 0

  # No-op if already installed.
  if canonical_install_present; then
    return 0
  fi

  # No-op on compute nodes (server-side bootstrap is its own path; the
  # canonical laptop-side install at ~/.argo_anywhere/ is not what the
  # on-node short-circuit wants).
  if [ "$(on_anl_compute_node)" = "yes" ]; then
    return 0
  fi

  local self_abs; self_abs="$(_resolve_self_path)"
  if [ -z "$self_abs" ] || [ ! -f "$self_abs" ]; then
    warn "Bootstrap: could not resolve absolute path of running script ($0)."
    warn "  Skipping canonical install. You can run 'update argo-anywhere' later"
    warn "  to install it explicitly."
    return 0
  fi

  # No-op if we ARE the canonical install (defensive; the
  # canonical_install_present check above would normally catch this).
  if [ "$self_abs" = "$ARGO_INSTALL_SCRIPT" ]; then
    return 0
  fi

  log "First-run setup: installing argo-anywhere.sh into ${ARGO_INSTALL_BIN_DIR}..."
  if ! _install_core "$self_abs"; then
    warn "Bootstrap: canonical install incomplete (run from ${self_abs} still works)."
    return 0
  fi

  ok "Installed argo-anywhere.sh v${SCRIPT_VERSION} at ${ARGO_INSTALL_SCRIPT}"
  ok "  Wrappers: ${ARGO_INSTALL_WRAP_INSTALL}, ${ARGO_INSTALL_WRAP_UNINSTALL}"
  ok "  PATH helper written to ${ARGO_INSTALL_ENV}"
  _print_path_setup_hint
}

# _packaged_use_pipx_hint <action>: under the Python package (D-030a) the
# engine's own install / self-update is dormant -- the package (pipx/pip) owns
# the runtime, so a self-install would create a divergent second copy of the
# engine (the two-homes drift D-029 warns about). Instead of doing the work,
# tell the user the package-manager command. <action> is 'install' or 'update'.
_packaged_use_pipx_hint() {
  local action="${1:-install}"
  case "$action" in
    install)
      warn "Running inside the argo-anywhere Python package; the script self-install is not used here."
      log  "  The package owns the runtime -- no separate script install is needed."
      log  "  Install or upgrade the tool with your Python installer, e.g.:"
      log  "      pipx install argo-anywhere        # first time"
      log  "      pipx upgrade argo-anywhere        # later upgrades"
      ;;
    *)
      warn "Running inside the argo-anywhere Python package; 'update argo-anywhere' is managed by pipx/pip."
      log  "  Upgrade the whole tool (the vendored engine travels with it) via:"
      log  "      pipx upgrade argo-anywhere        # or: pip install -U argo-anywhere"
      ;;
  esac
}

# ============================================================================
# SECTION: 6. ENV NAMESPACING (legacy -> ARGO_ANYWHERE_* promotion)
# ============================================================================
# Two generations of legacy names keep working with a one-time deprecation
# warning each (snapshotted in section 1 BEFORE the user-editable config
# block can reassign them, so promotion sees the inherited values):
#
#   Pre-namespace (oldest):
#     PROXY_PORT     -> ARGO_ANYWHERE_PORT
#     ANL_USERNAME   -> ARGO_ANYWHERE_USER
#     SHOW_MODELS    -> ARGO_ANYWHERE_SHOW_MODELS
#
#   Pre-rename (v1.x era; "argo_opencode" naming):
#     ARGO_OPENCODE_<X>  -> ARGO_ANYWHERE_<X>   (every X used by the script)
#
# Canonical names as of v2.0 are ARGO_ANYWHERE_*. Direct user code that
# exports ARGO_OPENCODE_* in shell rc files keeps working; the user just
# sees a one-line WARN per stale var on the first script run after upgrade.
_legacy_warned=""
_warn_legacy_env() {
  local old="$1" new="$2"
  case " $_legacy_warned " in *" $old "*) return ;; esac
  _legacy_warned="${_legacy_warned} ${old}"
  warn "env var '${old}' is deprecated; use '${new}' instead (still honored for now)"
}

# Promote pre-namespace inherited values (snapshotted in section 1) into
# canonical slots, but only if the canonical name isn't already set explicitly.
[ -z "${ARGO_ANYWHERE_USER:-}"        ] && [ -n "$_legacy_ANL_USERNAME" ] && \
  { _warn_legacy_env ANL_USERNAME ARGO_ANYWHERE_USER; ARGO_ANYWHERE_USER="$_legacy_ANL_USERNAME"; }
[ -z "${ARGO_ANYWHERE_PORT:-}"        ] && [ -n "$_legacy_PROXY_PORT"   ] && \
  { _warn_legacy_env PROXY_PORT ARGO_ANYWHERE_PORT; ARGO_ANYWHERE_PORT="$_legacy_PROXY_PORT"; }
[ -z "${ARGO_ANYWHERE_SHOW_MODELS:-}" ] && [ -n "$_legacy_SHOW_MODELS"  ] && \
  { _warn_legacy_env SHOW_MODELS ARGO_ANYWHERE_SHOW_MODELS; ARGO_ANYWHERE_SHOW_MODELS="$_legacy_SHOW_MODELS"; }

# Promote pre-rename ARGO_OPENCODE_* inherited values into canonical slots.
# Same precedence rule: only fill the canonical slot if it wasn't set
# explicitly. The pre-rename names are honored here even when the user has
# already migrated some vars to ARGO_ANYWHERE_*; only the un-migrated ones
# trigger the WARN.
[ -z "${ARGO_ANYWHERE_USER:-}"             ] && [ -n "$_legacy_ARGO_OPENCODE_USER" ] && \
  { _warn_legacy_env ARGO_OPENCODE_USER ARGO_ANYWHERE_USER; ARGO_ANYWHERE_USER="$_legacy_ARGO_OPENCODE_USER"; }
[ -z "${ARGO_ANYWHERE_PORT:-}"             ] && [ -n "$_legacy_ARGO_OPENCODE_PORT" ] && \
  { _warn_legacy_env ARGO_OPENCODE_PORT ARGO_ANYWHERE_PORT; ARGO_ANYWHERE_PORT="$_legacy_ARGO_OPENCODE_PORT"; }
[ -z "${ARGO_ANYWHERE_NODE:-}"             ] && [ -n "$_legacy_ARGO_OPENCODE_NODE" ] && \
  { _warn_legacy_env ARGO_OPENCODE_NODE ARGO_ANYWHERE_NODE; ARGO_ANYWHERE_NODE="$_legacy_ARGO_OPENCODE_NODE"; }
[ -z "${ARGO_ANYWHERE_NO_JUMP:-}"          ] && [ -n "$_legacy_ARGO_OPENCODE_NO_JUMP" ] && \
  { _warn_legacy_env ARGO_OPENCODE_NO_JUMP ARGO_ANYWHERE_NO_JUMP; ARGO_ANYWHERE_NO_JUMP="$_legacy_ARGO_OPENCODE_NO_JUMP"; }
[ -z "${ARGO_ANYWHERE_NO_MFA:-}"           ] && [ -n "$_legacy_ARGO_OPENCODE_NO_MFA" ] && \
  { _warn_legacy_env ARGO_OPENCODE_NO_MFA ARGO_ANYWHERE_NO_MFA; ARGO_ANYWHERE_NO_MFA="$_legacy_ARGO_OPENCODE_NO_MFA"; }
[ -z "${ARGO_ANYWHERE_FORCE_REINSTALL:-}"  ] && [ -n "$_legacy_ARGO_OPENCODE_FORCE_REINSTALL" ] && \
  { _warn_legacy_env ARGO_OPENCODE_FORCE_REINSTALL ARGO_ANYWHERE_FORCE_REINSTALL; ARGO_ANYWHERE_FORCE_REINSTALL="$_legacy_ARGO_OPENCODE_FORCE_REINSTALL"; }
[ -z "${ARGO_ANYWHERE_SHOW_MODELS:-}"      ] && [ -n "$_legacy_ARGO_OPENCODE_SHOW_MODELS" ] && \
  { _warn_legacy_env ARGO_OPENCODE_SHOW_MODELS ARGO_ANYWHERE_SHOW_MODELS; ARGO_ANYWHERE_SHOW_MODELS="$_legacy_ARGO_OPENCODE_SHOW_MODELS"; }
[ -z "${ARGO_ANYWHERE_CONTROL_PERSIST:-}"  ] && [ -n "$_legacy_ARGO_OPENCODE_CONTROL_PERSIST" ] && \
  { _warn_legacy_env ARGO_OPENCODE_CONTROL_PERSIST ARGO_ANYWHERE_CONTROL_PERSIST; ARGO_ANYWHERE_CONTROL_PERSIST="$_legacy_ARGO_OPENCODE_CONTROL_PERSIST"; }
[ -z "${ARGO_ANYWHERE_AUTO_PORT:-}"        ] && [ -n "$_legacy_ARGO_OPENCODE_AUTO_PORT" ] && \
  { _warn_legacy_env ARGO_OPENCODE_AUTO_PORT ARGO_ANYWHERE_AUTO_PORT; ARGO_ANYWHERE_AUTO_PORT="$_legacy_ARGO_OPENCODE_AUTO_PORT"; }
[ -z "${ARGO_ANYWHERE_PORT_RANGE:-}"       ] && [ -n "$_legacy_ARGO_OPENCODE_PORT_RANGE" ] && \
  { _warn_legacy_env ARGO_OPENCODE_PORT_RANGE ARGO_ANYWHERE_PORT_RANGE; ARGO_ANYWHERE_PORT_RANGE="$_legacy_ARGO_OPENCODE_PORT_RANGE"; }
[ -z "${ARGO_ANYWHERE_KEEP_ORPHANS:-}"     ] && [ -n "$_legacy_ARGO_OPENCODE_KEEP_ORPHANS" ] && \
  { _warn_legacy_env ARGO_OPENCODE_KEEP_ORPHANS ARGO_ANYWHERE_KEEP_ORPHANS; ARGO_ANYWHERE_KEEP_ORPHANS="$_legacy_ARGO_OPENCODE_KEEP_ORPHANS"; }
[ -z "${ARGO_ANYWHERE_DROP_ORPHANS:-}"     ] && [ -n "$_legacy_ARGO_OPENCODE_DROP_ORPHANS" ] && \
  { _warn_legacy_env ARGO_OPENCODE_DROP_ORPHANS ARGO_ANYWHERE_DROP_ORPHANS; ARGO_ANYWHERE_DROP_ORPHANS="$_legacy_ARGO_OPENCODE_DROP_ORPHANS"; }
# B1a (Phase 4): CLAUDECODE_SCOPE -> ARGO_ANYWHERE_SCOPE (D-019).
# The pre-Phase-4 env var was per-tool-named (CLAUDECODE_SCOPE) per D-009's
# convention; per-tool naming made sense when only Claude Code consumed
# scope. Phase 4 generalises scope across tools, so the env var migrates
# to the shared *_ANYWHERE_* namespace. Legacy CLAUDECODE_SCOPE remains
# honored with a one-time deprecation warning; removal target = whenever
# v3.0.0 ships (no fixed schedule).
[ -z "${ARGO_ANYWHERE_SCOPE:-}"            ] && [ -n "$_legacy_CLAUDECODE_SCOPE" ] && \
  { _warn_legacy_env CLAUDECODE_SCOPE ARGO_ANYWHERE_SCOPE; ARGO_ANYWHERE_SCOPE="$_legacy_CLAUDECODE_SCOPE"; }
# NOTE: ARGO_OPENCODE_LOGGING legacy promotion was removed in
# Phase 2e (I2 fix; 2026-05-15). The variable was an INTERNAL sentinel
# (renamed to _ARGO_ANYWHERE_REEXEC) never set by users; the legacy
# alias was a leftover from the wholesale Phase 1 D4 namespace rename
# and never actually mattered.

# ============================================================================
# SECTION: 7. PORT RESOLUTION (cache file is the source of truth; per D-020)
# ============================================================================
# B2 (Phase 4) reframes port resolution per D-020: the script's own
# cache file at ~/.config/argo_anywhere/port (PORT_CACHE) is the source
# of truth for "what port should we use." Per-tool client configs become
# DOWNSTREAM RENDERINGS that receive the port from the cache via their
# writers. Pre-B2 the script derived PROXY_PORT from the OpenCode config
# baseURL (M4 audit finding: "port resolution is OpenCode-specific in a
# multi-client world"); B2 closes M4.
#
# resolve_port writes the chosen port into PROXY_PORT (global). Order:
#   1. PORT_OVERRIDE_CLI                  (set by --port flag)
#   2. ARGO_ANYWHERE_PORT env
#   3. cached port (PORT_CACHE file)
#   4. one-shot first-run migration       (no cache, but client configs exist)
#   5. PROXY_PORT_DEFAULT                 (true cold start)
#
# Migration handles three cases (D-020 three-case refinement):
#   Case 1: no client configs exist anywhere -> cache PROXY_PORT_DEFAULT;
#           log "no existing client configs; cached default port N".
#   Case 2: exactly one client config has a baseURL -> seed cache from it;
#           log "migrated port N from <tool> config to ~/.config/argo_anywhere/port".
#   Case 3: multiple client configs with DISAGREEING ports -> invoke
#           prompt_port_choice to let the user pick canonical; write cache
#           + offer to update disagreeing configs (deferred to B3's
#           cross-client coherence enforcement).
PORT_OVERRIDE_CLI=""              # set by main() when --port given
PORT_FROM_CONFIG=""               # populated by read_port_from_opencode_config
                                  # for cross-client coherence checks elsewhere
PORT_FROM_CACHE=""                # populated by read_cached_port
PORT_SOURCE=""                    # diagnostic: which source above won

# Read the port from the OpenCode config's baseURL. Empty if unparseable.
# Kept as-is (B2 doesn't change this; per-tool config inspectors land
# in B3 for the cross-client coherence work).
read_port_from_opencode_config() {
  local cfg="${OPENCODE_CONFIG}" url=""
  [ -f "$cfg" ] || return 0
  if command -v jq >/dev/null 2>&1; then
    url="$(jq -r '.provider.argo.options.baseURL // empty' "$cfg" 2>/dev/null)"
  else
    # Best-effort: pick the first http(s)://host:port out of the file.
    url="$(grep -oE '"baseURL"[[:space:]]*:[[:space:]]*"[^"]*"' "$cfg" \
            | head -n1 | sed 's/.*"\([^"]*\)"$/\1/')"
  fi
  [ -n "$url" ] || return 0
  # Extract the port (works for http://host:PORT/v1 and http://host:PORT)
  printf '%s\n' "$url" | sed -nE 's|^https?://[^:/]+:([0-9]+).*|\1|p'
}

# B3 (Phase 4): per-tool config inspectors for cross-client coherence
# enforcement (D-021). Each inspector returns the port the named tool's
# config is pointing at (parsed from baseURL or env.ANTHROPIC_BASE_URL),
# OR empty if the config is absent / unparseable / has no relevant key.
# All inspectors are READ-ONLY and side-effect-free.

# _get_port_from_claudecode_config <path>: parse env.ANTHROPIC_BASE_URL
# from a Claude Code settings.json file. Reads `env.ANTHROPIC_BASE_URL`
# which is "http://localhost:PORT" (no trailing /v1 -- per
# write_claudecode_config's contract; Claude Code appends /v1/messages
# itself). Returns empty on file absent / parse failure / missing key.
#
# Args: $1 -- path to the settings.json (typically CLAUDECODE_GLOBAL_CONFIG
#       or CLAUDECODE_PROJECT_CONFIG; caller decides which).
_get_port_from_claudecode_config() {
  local cfg="$1"
  [ -f "$cfg" ] || return 0
  local url=""
  if command -v jq >/dev/null 2>&1; then
    url="$(jq -r '.env.ANTHROPIC_BASE_URL // empty' "$cfg" 2>/dev/null)"
  elif command -v python3 >/dev/null 2>&1; then
    # python3 fallback so we don't silently degrade on systems without jq.
    url="$(python3 - "$cfg" 2>/dev/null <<'PYEOF'
import json, sys
try:
    with open(sys.argv[1]) as f:
        data = json.load(f)
    env = data.get("env") if isinstance(data, dict) else None
    if isinstance(env, dict):
        v = env.get("ANTHROPIC_BASE_URL", "")
        if v:
            print(v)
except Exception:
    pass
PYEOF
)"
  else
    # Last-ditch best-effort grep+sed. Brittle but better than silent miss.
    url="$(grep -oE '"ANTHROPIC_BASE_URL"[[:space:]]*:[[:space:]]*"[^"]*"' "$cfg" \
            | head -n1 | sed 's/.*"\([^"]*\)"$/\1/')"
  fi
  [ -n "$url" ] || return 0
  # Extract the port (works for http://host:PORT and http://host:PORT/path).
  printf '%s\n' "$url" | sed -nE 's|^https?://[^:/]+:([0-9]+).*|\1|p'
}

# enumerate_client_ports: print one line per installed client config that
# has a baseURL/env-set port. Format: "<tool> <scope> <port> <path>".
# Used by both the cross-client coherence checker (D-021) and the
# port-cache migration's Case 3 detector (D-020).
#
# Tools enumerated (in B3): opencode (global only; B1b's project scope
# is supported as a write path but per-project inspection of `<git-root>/opencode.json`
# is deferred -- see B3 known gap below), claudecode (global +
# project-in-cwd).
#
# Known gap (B3): only opencode-global, claudecode-global, and
# claudecode-project-in-cwd are enumerated. opencode-project (B1b's
# new scope) is NOT enumerated because the project path depends on
# git-root walking from cwd, and cross-client coherence detection runs
# at script startup where the cwd may not be a project root (status
# from anywhere; client from anywhere). Future enhancement: also
# inspect <git-root>/opencode.json when cwd is in a git repo.
enumerate_client_ports() {
  local p

  # opencode global
  p="$(read_port_from_opencode_config 2>/dev/null || true)"
  if [ -n "$p" ]; then
    printf '%s\n' "opencode global $p $OPENCODE_GLOBAL_CONFIG"
  fi

  # claudecode global
  p="$(_get_port_from_claudecode_config "$CLAUDECODE_GLOBAL_CONFIG" 2>/dev/null || true)"
  if [ -n "$p" ]; then
    printf '%s\n' "claudecode global $p $CLAUDECODE_GLOBAL_CONFIG"
  fi

  # claudecode project (cwd-relative; only meaningful when invoked from
  # a directory that has a .claude/settings.local.json)
  if [ -f "$CLAUDECODE_PROJECT_CONFIG" ]; then
    p="$(_get_port_from_claudecode_config "$CLAUDECODE_PROJECT_CONFIG" 2>/dev/null || true)"
    if [ -n "$p" ]; then
      printf '%s\n' "claudecode project $p $CLAUDECODE_PROJECT_CONFIG"
    fi
  fi
}

# detect_port_disagreement <chosen_port>: enumerate all installed client
# configs and check whether any of their ports DISAGREE with the chosen
# port. Returns 0 (silent) when all configs agree (or no configs exist);
# returns 1 + prints disagreement lines to stdout when at least one
# config disagrees.
#
# Output format on disagreement:
#   <tool> <scope> <port> <path>     <-- one line per DISAGREEING config
#
# Used by status (passive reporting) and client startup (proactive
# prompt). The caller decides what to do with the disagreement (status
# just reports; client invokes prompt_port_choice or similar).
detect_port_disagreement() {
  local chosen="$1"
  [ -n "$chosen" ] || return 0
  local saw_disagreement=0
  local line tool scope port path
  while IFS= read -r line; do
    [ -n "$line" ] || continue
    tool="$(printf '%s' "$line" | awk '{print $1}')"
    scope="$(printf '%s' "$line" | awk '{print $2}')"
    port="$(printf '%s' "$line" | awk '{print $3}')"
    path="$(printf '%s' "$line" | awk '{for (i=4; i<=NF; i++) printf "%s%s", $i, (i<NF?" ":"")}')"
    if [ "$port" != "$chosen" ]; then
      printf '%s %s %s %s\n' "$tool" "$scope" "$port" "$path"
      saw_disagreement=1
    fi
  done < <(enumerate_client_ports)
  [ "$saw_disagreement" = 0 ] && return 0 || return 1
}

# read_cached_port: read PROXY_PORT from PORT_CACHE if it exists and
# parses as a valid integer. Returns empty (no output, exit 0) on
# missing file / unreadable / non-integer content. Best-effort read;
# the on-disk cache is a UX nicety, not load-bearing.
read_cached_port() {
  [ -f "$PORT_CACHE" ] || return 0
  local v
  v="$(cat "$PORT_CACHE" 2>/dev/null | tr -d '[:space:]')"
  # Validate as a positive integer to avoid downstream surprises if the
  # cache file got corrupted somehow.
  case "$v" in
    ''|*[!0-9]*) return 0 ;;
    *) printf '%s' "$v" ;;
  esac
}

# write_port_cache: persist the chosen port to PORT_CACHE atomically
# (tmp-write + mv). Creates STATE_DIR if missing (delegates to
# _ensure_state_dir, which die's with a clear message on mkdir failure
# per the L1 audit-fix discipline). Idempotent: writing the same value
# is a no-op effect on the user's environment.
#
# Args: $1 -- port (positive integer; caller is responsible for validation)
# Returns: 0 on success; die's on STATE_DIR or write failure.
write_port_cache() {
  local p="$1"
  [ -n "$p" ] || die "write_port_cache: refusing to cache empty port."
  _ensure_state_dir
  local _tmp; _tmp="$(mktemp -t argo_anywhere_port.XXXXXX 2>/dev/null || mktemp /tmp/argo_anywhere_port.XXXXXX)"
  printf '%s\n' "$p" > "$_tmp" || die "write_port_cache: failed to write tempfile ${_tmp}."
  mv -f "$_tmp" "$PORT_CACHE" || die "write_port_cache: failed to rename ${_tmp} -> ${PORT_CACHE}."
}

resolve_port() {
  local p=""
  # M3 fix (audit Phase 2c) preserved: hoist read_port_from_opencode_config
  # call to the top so PORT_FROM_CONFIG is populated for downstream
  # cross-client coherence checks (regardless of which source actually
  # won the precedence race).
  PORT_FROM_CONFIG="$(read_port_from_opencode_config || true)"
  PORT_FROM_CACHE="$(read_cached_port || true)"
  if [ -n "$PORT_OVERRIDE_CLI" ]; then
    p="$PORT_OVERRIDE_CLI"; PORT_SOURCE="--port flag"
  elif [ -n "${ARGO_ANYWHERE_PORT:-}" ]; then
    p="$ARGO_ANYWHERE_PORT"; PORT_SOURCE="ARGO_ANYWHERE_PORT env"
  elif [ -n "$PORT_FROM_CACHE" ]; then
    p="$PORT_FROM_CACHE"; PORT_SOURCE="cached port (${PORT_CACHE})"
  else
    # First-run migration (D-020 three-case refinement). No cache yet;
    # decide what to seed it with. B3 (Phase 4) extended the inspector
    # set to cover claudecode (global + project-in-cwd) in addition to
    # opencode-global; enumerate_client_ports is the single source of
    # truth for "what client configs exist and what ports do they
    # report."
    local _enum; _enum="$(enumerate_client_ports 2>/dev/null || true)"
    if [ -z "$_enum" ]; then
      # Case 1: no existing client configs with a baseURL; seed default.
      p="$PROXY_PORT_DEFAULT"
      PORT_SOURCE="built-in default (no cache, no existing client configs; seeding ${PORT_CACHE})"
      log "Port cache (${PORT_CACHE}) empty on first run; no existing client configs found. Seeding default port ${p}."
    else
      # Count unique ports across all enumerated configs.
      local _unique_ports
      _unique_ports="$(printf '%s\n' "$_enum" | awk '{print $3}' | sort -u)"
      local _num_unique; _num_unique="$(printf '%s\n' "$_unique_ports" | grep -c .)"
      if [ "$_num_unique" = 1 ]; then
        # Case 2: all installed configs agree (or only one exists).
        p="$_unique_ports"  # already a single value
        local _tool_list; _tool_list="$(printf '%s\n' "$_enum" | awk '{print $1 ":" $2}' | paste -sd ',' -)"
        PORT_SOURCE="migrated from ${_tool_list} config (cached for future runs)"
        log "Port cache (${PORT_CACHE}) empty on first run; migrating port ${p} from existing client config(s) [${_tool_list}]."
      else
        # Case 3: multiple client configs with DISAGREEING ports.
        # The user has to pick. Print the inventory + prompt via
        # prompt_port_choice. The chosen port is then cached and
        # downstream config writers will update the disagreeing configs
        # on next run (or the user can pick [u]se-once / [k]eep / [a]bort).
        warn "Port cache (${PORT_CACHE}) empty on first run; multiple existing client configs disagree on the port:"
        printf '%s\n' "$_enum" | while IFS= read -r line; do
          warn "  $line"
        done
        # Pick the FIRST inspector's port as the "current" reference for
        # the prompt; offer canonicalization. Use enumerate_client_ports'
        # first line's port as the proposed canonical (arbitrary but
        # deterministic).
        local _first_port; _first_port="$(printf '%s\n' "$_enum" | head -n1 | awk '{print $3}')"
        local _other_port; _other_port="$(printf '%s\n' "$_unique_ports" | grep -v "^${_first_port}\$" | head -n1)"
        # Reuse the existing prompt_port_choice helper. Semantics here:
        # "new_port" = first config's port (proposed canonical);
        # "config_port" = the other config's port (alternative).
        # Result interpretation:
        #   migrate  -> use _first_port; B3 status/client startup
        #               disagreement detection will surface the still-
        #               disagreeing other configs on next invocation.
        #   use-once -> use _first_port for this run; cache NOT written
        #               (user wants to test without committing).
        #   keep     -> use _other_port; same downstream surfacing.
        local _ppc_choice
        _ppc_choice="$(prompt_port_choice "$_first_port" "$_other_port" "multiple client configs (see warnings above)")"
        case "$_ppc_choice" in
          migrate)
            p="$_first_port"
            PORT_SOURCE="user-chosen canonical from multi-config migration (cached)"
            ok "Will use port ${p} as the canonical; cache will be seeded with this value."
            ;;
          use-once)
            p="$_first_port"
            PORT_SOURCE="user-chosen for this run only; cache NOT written"
            # Signal to the cache-write block below that this is a
            # use-once choice and should NOT update the cache.
            PORT_OVERRIDE_CLI="$_first_port"  # treats as if user passed --port
            ok "Using port ${p} for THIS run only; the cache will remain empty."
            ;;
          keep)
            p="$_other_port"
            PORT_SOURCE="user-chosen alternative from multi-config migration (cached)"
            ok "Will use port ${p} as the canonical; cache will be seeded with this value."
            ;;
        esac
      fi
    fi
  fi
  # Sanity check: must be a number in valid TCP range.
  case "$p" in
    [1-9]|[1-9][0-9]|[1-9][0-9][0-9]|[1-9][0-9][0-9][0-9]|[1-5][0-9][0-9][0-9][0-9]|6[0-4][0-9][0-9][0-9]|65[0-4][0-9][0-9]|655[0-2][0-9]|6553[0-5]) ;;
    *) die "Resolved port '$p' is not a valid TCP port number." ;;
  esac
  # Reject privileged ports (1-1023). argo-proxy can't bind these without
  # root, and the bootstrap would fail late ('Address already in use'
  # is what bash would see -- actually permission-denied at the kernel
  # level, but the symptom is the same). Be consistent with --port-range
  # validation (1024-65535) and the interactive port-prompt's range.
  if [ "$p" -lt 1024 ]; then
    die "Resolved port '$p' is privileged (<1024); use 1024-65535. argo-proxy cannot bind these without root."
  fi
  PROXY_PORT="$p"

  # Write-through cache: if we resolved via something OTHER than the cache,
  # update the cache so subsequent invocations have the right value. This
  # includes:
  #   * --port flag chosen (user's explicit choice; cache it)
  #   * ARGO_ANYWHERE_PORT env (same; cache for next run)
  #   * First-run migration cases (Case 1 and Case 2 above)
  # Skip the cache write if PROXY_PORT already equals PORT_FROM_CACHE
  # (no actual change; avoids unnecessary disk writes).
  if [ -z "$PORT_FROM_CACHE" ] || [ "$PROXY_PORT" != "$PORT_FROM_CACHE" ]; then
    write_port_cache "$PROXY_PORT"
  fi
}

# prompt_port_choice: interactive [m/u/k/a] prompt for port-disagreement
# scenarios. Factored from the two prior call sites (ensure_or_reuse_tunnel
# post-auto-port + _client_common_setup at startup) into a single helper to
# stop drift across sites; D-021 (Phase 4) will add a third call site for
# cross-client coherence enforcement and benefits from a unified vocabulary.
#
# Args:
#   $1 new_port     -- the port the script wants to use (chosen / probed)
#   $2 config_port  -- the port currently in the client config
#   $3 config_label -- human-readable description of the config source
#                      (e.g. "OpenCode config" or "~/.config/opencode/config.json")
#
# Prints (to stdout) one of:
#   migrate   -- caller writes config to new_port
#   use-once  -- caller uses new_port; does NOT touch config
#                (caller is responsible for setting any SKIP_*_CONFIG_WRITE flag
#                 appropriate to the affected client)
#   keep      -- caller uses config_port (and decides whether to loop / re-probe;
#                returned without modifying PROXY_PORT -- callers MUST set
#                PROXY_PORT="$config_port" themselves)
#
# Dies on [a]bort. The caller's flow continues for the other three choices.
#
# B0 fix (Phase 4 pre-work, 2026-05-...): factored from inline prompts at
# (old) lines 3500-3524 and 3786-3825. The text below is the merged "best
# of both sites" wording (the longer, more explanatory variant from the
# startup site, since it's the more common path).
prompt_port_choice() {
  local new_port="$1" config_port="$2" config_label="$3"
  warn "Port mismatch:"
  warn "  Script wants to use         : ${new_port}"
  warn "  ${config_label} currently says: ${config_port}"
  cat >&2 <<EOF

  The client reads its baseURL once at launch, so a tunnel on ${new_port}
  while config still says ${config_port} means the client will fail to
  connect (refused/wrong port). Choose:
    [m] migrate config to ${new_port}, then continue (writes the config file)
    [u] use ${new_port} for THIS run only; do NOT touch config
        (parallel/test tunnel; the client will keep talking to ${config_port})
    [k] keep config at ${config_port}; use that port for the tunnel too
    [a] abort; resolve manually
EOF
  local choice; choice="$(ask "Your choice [m/u/k/a]:" "k")"
  case "$choice" in
    m|M) printf '%s' "migrate" ;;
    u|U) printf '%s' "use-once" ;;
    k|K) printf '%s' "keep" ;;
    a|A) die "Aborted at port-reconciliation step." ;;
    *)   die "Unrecognized choice; aborting." ;;
  esac
}

# ============================================================================
# SECTION: 8. JUMP HOST HANDLING (ssh_jump_args, jump_descr)
# ============================================================================
# By default we route via ANL_JUMP. With --no-jump (or ARGO_ANYWHERE_NO_JUMP=1)
# we connect directly -- useful when the user is on the ANL network or has an
# ~/.ssh/config that already inserts a ProxyJump for the cels.anl.gov hosts.
#
# ssh_jump_args <user> [target_host] :  prints '-J <user>@<jump>' or nothing.
# Use it via:  ssh $(ssh_jump_args "$user" "$node") "$user@$node" ...
#
# If target_host == ANL_JUMP we MUST NOT add '-J jumphost' because that asks
# OpenSSH to use the jump host as a hop on the way to itself (a loop). Some
# ~/.ssh/config setups detect this and abort with messages like
# "jumphost loop via <host>"; vanilla OpenSSH simply refuses with a less
# obvious error. The preflight to the jump host is the only call site where
# target == ANL_JUMP today (see ssh_preflight), but guarding here keeps the
# rule local to the helper that owns -J.
#
# Note: with `set -u`, an unset value becomes empty after expansion -- safe.
ssh_jump_args() {
  local user="$1" target="${2:-}"
  if [ "${ARGO_ANYWHERE_NO_JUMP:-0}" = 1 ]; then
    return
  fi
  if [ -n "$target" ] && [ "$target" = "$ANL_JUMP" ]; then
    return
  fi
  printf -- '-J %s@%s' "$user" "$ANL_JUMP"
}

# Human-readable description for plans/help/error messages.
jump_descr() {
  if [ "${ARGO_ANYWHERE_NO_JUMP:-0}" = 1 ]; then
    echo "(direct, no jump host)"
  else
    echo "via ${ANL_JUMP}"
  fi
}

# ============================================================================
# SECTION: 9. MFA / SSH MULTIPLEXING (ssh_args, ssh_reachable, ssh_mux_*)
# ============================================================================
# ANL CELS hosts use Duo MFA. That breaks two assumptions the script used
# to make:
#   1. `ssh -o BatchMode=yes` always fails (Duo prompt is non-interactive
#      from SSH's POV) -- so we cannot use BatchMode reachability tests.
#   2. Each SSH/SCP call would re-trigger Duo (push spam).
#
# Solution: ControlMaster connection multiplexing. The first SSH call to a
# given host opens a master connection (one Duo prompt). Subsequent calls to
# the SAME host go through the existing socket without re-prompting.
#
# MFA mode is ON by default (since all CELS access uses Duo). Override:
#   --no-mfa / ARGO_ANYWHERE_NO_MFA=1   -- disable mux, restore BatchMode tests
#   ARGO_ANYWHERE_CONTROL_PERSIST=N     -- seconds after last client to keep
#                                          the master alive (default 3600).
#                                          Use 'yes' for indefinite, 'no' to
#                                          die when the last client closes.
SSH_MUX_DIR="${HOME}/.ssh/sockets"
SSH_MUX_PERSIST_DEFAULT=3600

mfa_enabled() {
  [ "${ARGO_ANYWHERE_NO_MFA:-0}" = 1 ] && return 1
  return 0
}

# ----------------------------------------------------------------------------
# SSH attempt tracker
# ----------------------------------------------------------------------------
# ANL/CELS networks are monitored by CSPO (Cyber Security Program Office),
# which blocks IPs that produce too many failed SSH authentication attempts
# in a short window. On a shared compute node (where many users share the
# same outbound IP) one user with a broken SSH agent can get the WHOLE node
# IP blocked, locking out everyone else. Common triggers from this script:
#   * SSH agent went away mid-session (laptop closed, ssh-add -D, expired
#     Kerberos ticket)
#   * --user typed wrong (every retry will fail until corrected)
#   * the reconnect loop hammering on a flapping network
#
# Defense: count consecutive failures; after SSH_FAIL_THRESHOLD, lock out
# all further SSH attempts AND write a timestamped lock file so the lock
# survives across script restarts (the most common failure mode: user sees
# an error, Ctrl-Cs, and immediately re-runs, resetting the in-memory
# counter but accumulating real auth failures against CSPO's rate limiter).
#
# Scope of tracking: ssh_reachable, ssh_mux_open, the scp + bootstrap ssh
# in remote_bootstrap, find_next_free_remote_port, probe_remote_port_owner,
# and the clean-mode ssh call all go through the tracker. The tunnel respawn
# paths in open_tunnel + monitor_tunnel_loop have their own burst-backoff
# (RECONN_BURST_LIMIT) and the common reconnect path does NOT re-auth (the
# multiplex master holds the connection), so we don't double-count there.
#
# C5 fix (audit): three hardenings against repeated re-locking:
#
#   1. TTL = 30 min (was 5 min). 5 min was too short -- a user with
#      permanently-broken auth could re-lock 12 times an hour, totalling
#      36 ssh attempts/hour against CSPO. 30 min caps that at ~6 attempts/hour
#      which sits comfortably below CSPO thresholds.
#
#   2. Post-expiry reset to THRESHOLD-1 (not 0). After a lock auto-expires,
#      the user gets ONE more attempt before re-locking, not THREE fresh
#      attempts. If their auth is still broken, the second auth-failure
#      re-arms the lock immediately. This punishes "wait, then retry blindly"
#      patterns without punishing "wait, fix, retry succeeds" patterns.
#
#   3. Exponential backoff per lock-event. The count of historical lock
#      events lives in $SSH_FAIL_LOCK_COUNT_FILE; each new lock multiplies
#      the TTL by 2 (capped at 24h). So: first lock 30 min, second 60 min,
#      third 120 min, ... cap at 1440 min. A successful ssh attempt resets
#      the count to 0 (fresh state). This rewards users who eventually
#      get their auth working.
SSH_FAIL_THRESHOLD=3
SSH_FAIL_LOCK_TTL_BASE=1800     # 30 min base (was 300 = 5 min, too short for CSPO)
SSH_FAIL_LOCK_TTL_MAX=86400     # 24h cap on exponential backoff
SSH_FAIL_LOCK_FILE="${STATE_DIR}/ssh-fail-lock"
SSH_FAIL_LOCK_COUNT_FILE="${STATE_DIR}/ssh-fail-lock-count"
_SSH_FAIL_COUNT=0
_SSH_LOCKED=0

# Compute the current TTL based on past lock-event count (0 = first lock,
# 1 = second lock, ...). Doubles per event, capped at SSH_FAIL_LOCK_TTL_MAX.
_ssh_lock_ttl_for_count() {
  local count="${1:-0}" ttl="$SSH_FAIL_LOCK_TTL_BASE"
  local i=0
  while [ "$i" -lt "$count" ] && [ "$ttl" -lt "$SSH_FAIL_LOCK_TTL_MAX" ]; do
    ttl=$((ttl * 2))
    i=$((i + 1))
  done
  [ "$ttl" -gt "$SSH_FAIL_LOCK_TTL_MAX" ] && ttl="$SSH_FAIL_LOCK_TTL_MAX"
  printf '%s' "$ttl"
}

# Read the lock-event count from disk. 0 if not yet recorded.
_ssh_lock_count_read() {
  if [ -f "$SSH_FAIL_LOCK_COUNT_FILE" ]; then
    local n; n="$(cat "$SSH_FAIL_LOCK_COUNT_FILE" 2>/dev/null || echo 0)"
    case "$n" in
      ''|*[!0-9]*) printf '0' ;;
      *) printf '%s' "$n" ;;
    esac
  else
    printf '0'
  fi
}

# Pre-attempt gate: callers should invoke this before running ssh and skip
# (return failure) if the lock is set. Returns 0 = ok to attempt, 1 = locked.
# Checks the on-disk lock first so a lock set in a previous invocation is
# also honoured.
ssh_attempt_pre() {
  # In-memory lock (fastest path for within-session failures).
  if [ "$_SSH_LOCKED" -eq 1 ]; then
    return 1
  fi
  # On-disk lock (survives restarts). TTL depends on past lock-event count
  # (exponential backoff per audit C5).
  if [ -f "$SSH_FAIL_LOCK_FILE" ]; then
    local locked_at; locked_at="$(cat "$SSH_FAIL_LOCK_FILE" 2>/dev/null)"
    local now; now="$(date +%s)"
    local lock_count; lock_count="$(_ssh_lock_count_read)"
    local current_ttl; current_ttl="$(_ssh_lock_ttl_for_count "$lock_count")"
    if [ -n "$locked_at" ] && [ $((now - locked_at)) -lt "$current_ttl" ]; then
      local remaining=$(( current_ttl - (now - locked_at) ))
      local rem_min=$(( remaining / 60 ))
      err "SSH failure lock is active (${remaining}s = ~${rem_min}min remaining)."
      err "  Too many recent failed SSH attempts; refusing to add more."
      err "  Lock event #$((lock_count + 1)); current TTL ${current_ttl}s."
      err "  Either wait ${rem_min}min and re-run, or verify your SSH manually:"
      err "    ssh -o ConnectTimeout=5 ${ARGO_ANYWHERE_USER:-<user>}@${ANL_JUMP} true"
      err "  Then delete the lock to unblock immediately:"
      err "    rm ${SSH_FAIL_LOCK_FILE}"
      _SSH_LOCKED=1
      return 1
    else
      # TTL expired. C5 fix: do NOT reset _SSH_FAIL_COUNT to 0; reset to
      # THRESHOLD-1 so the user gets ONE more attempt before re-locking,
      # not THREE fresh attempts. Punishes "wait, then blindly retry"
      # patterns without punishing "wait, fix, retry succeeds" patterns.
      # The on-disk lock file is removed (the next ssh_attempt_fail will
      # rewrite it if needed). The lock-event count file is preserved so
      # exponential backoff persists across the expiry.
      rm -f "$SSH_FAIL_LOCK_FILE"
      _SSH_FAIL_COUNT=$((SSH_FAIL_THRESHOLD - 1))
      _SSH_LOCKED=0
    fi
  fi
  return 0
}

# Mark the most recent ssh attempt as successful. Resets the counter,
# removes the on-disk lock, AND resets the historical lock-event count
# (so the user starts fresh; the exponential backoff doesn't punish them
# forever for past failures once they've fixed their setup).
ssh_attempt_ok() {
  _SSH_FAIL_COUNT=0
  rm -f "$SSH_FAIL_LOCK_FILE" 2>/dev/null || true
  rm -f "$SSH_FAIL_LOCK_COUNT_FILE" 2>/dev/null || true
}

# Mark the most recent ssh attempt as a failure. Increments the counter and,
# if we've now hit the threshold, sets both the in-memory lock and an on-disk
# lock file (so the block survives a script restart) and prints the recovery
# instructions ONCE.
ssh_attempt_fail() {
  _SSH_FAIL_COUNT=$((_SSH_FAIL_COUNT + 1))
  if [ "$_SSH_FAIL_COUNT" -ge "$SSH_FAIL_THRESHOLD" ] && [ "$_SSH_LOCKED" -ne 1 ]; then
    _SSH_LOCKED=1

    # C4 fix: lock MUST persist to disk to survive script restarts.
    # If we can't persist, the user can Ctrl-C + re-run and bypass the
    # in-memory _SSH_FAIL_COUNT, accumulating real auth failures
    # against CSPO's rate limiter -- exactly the situation this defense
    # is supposed to PREVENT. Pre-fix code did:
    #     mkdir -p "$STATE_DIR" 2>/dev/null || true
    #     date +%s > "$SSH_FAIL_LOCK_FILE" 2>/dev/null || true
    # Both errors swallowed -> if STATE_DIR creation fails (read-only
    # $HOME, full disk, NFS hiccup), the lock is in-memory only and
    # the user can bypass it. Now: die hard if either step fails.
    # Better to halt than to silently expose the user to CSPO blocks.
    if ! mkdir -p "$STATE_DIR" 2>/dev/null; then
      err "SSH has failed ${_SSH_FAIL_COUNT} consecutive times AND we cannot"
      err "  create the state dir to persist the failure lock:"
      err "    ${STATE_DIR}"
      err "  Without an on-disk lock, you could bypass our CSPO defense by"
      err "  Ctrl-C + re-running. Refusing to continue."
      err ""
      err "Likely causes for the mkdir failure:"
      err "  * \$HOME is read-only or full"
      err "  * permission problem on \$HOME/.config/"
      err "  * SELinux / AppArmor blocking it"
      err ""
      err "Fix the mkdir issue, then re-run. The first SSH attempt after the"
      err "  fix starts a fresh failure counter."
      exit 3
    fi
    if ! date +%s > "$SSH_FAIL_LOCK_FILE" 2>/dev/null; then
      err "SSH has failed ${_SSH_FAIL_COUNT} consecutive times AND we cannot"
      err "  write the failure lock file:"
      err "    ${SSH_FAIL_LOCK_FILE}"
      err "  Without persistence, you could bypass our CSPO defense by"
      err "  Ctrl-C + re-running. Refusing to continue."
      err ""
      err "Likely cause: ${STATE_DIR} exists but is not writable by you."
      err "Fix the permissions, then re-run."
      exit 3
    fi

    # C5 fix: increment the historical lock-event count (drives exponential
    # backoff on subsequent locks). Read prior count, add 1, write back.
    # Failure to write is non-fatal here (we already have the on-disk lock
    # file with the timestamp); the count file just enables backoff and
    # an unfortunate filesystem state would only mean the next lock TTL
    # doesn't grow as expected. Log a warn so the user notices.
    local _prev_lock_count; _prev_lock_count="$(_ssh_lock_count_read)"
    local _new_lock_count=$((_prev_lock_count + 1))
    if ! printf '%s\n' "$_new_lock_count" > "$SSH_FAIL_LOCK_COUNT_FILE" 2>/dev/null; then
      warn "Could not write lock-event count file at ${SSH_FAIL_LOCK_COUNT_FILE};"
      warn "  exponential backoff may not progress correctly. Lock itself is intact."
    fi
    local _current_ttl; _current_ttl="$(_ssh_lock_ttl_for_count "$_prev_lock_count")"
    local _ttl_min=$((_current_ttl / 60))

    err "SSH has failed ${_SSH_FAIL_COUNT} consecutive times."
    err "Disabling further SSH attempts to prevent CSPO from blocking your IP"
    err "  (and locking out everyone else sharing this compute node)."
    err "  Lock event #${_new_lock_count}; TTL ${_current_ttl}s (~${_ttl_min}min)."
    err "  Lock will auto-expire after that, or delete it manually:"
    err "    rm ${SSH_FAIL_LOCK_FILE}"
    if [ "$_prev_lock_count" -gt 0 ]; then
      err "  (TTL grows exponentially per repeated lock event: 30min -> 60 -> 120 -> ...)"
      err "  (A successful SSH attempt resets the count to 0.)"
    fi
    err ""
    err "Common causes:"
    err "  * Closed laptop while SSH agent forwarding was active (kills the forwarded key)"
    err "  * Expired Kerberos tickets"
    err "  * SSH key removed from the agent ('ssh-add -D' earlier)"
    err "  * Wrong username (--user / ARGO_ANYWHERE_USER mismatch)"
    err ""
    err "Recovery:"
    err "  1. Verify your SSH works manually first:"
    err "       ssh -o ConnectTimeout=5 ${ARGO_ANYWHERE_USER:-<user>}@${ANL_JUMP} true"
    err "     (one Duo prompt is fine; what we want is a clean exit.)"
    err "  2. If that fails, fix your auth (ssh-add, reconnect agent forwarding,"
    err "     renew tickets, correct the username, etc.)."
    err "  3. Re-run $(basename "$0") -- the lock will have expired by then, or"
    err "     delete it immediately with: rm ${SSH_FAIL_LOCK_FILE}"
  fi
}

# ssh_mux_args : prints the ControlMaster options to splice into ssh/scp.
# Empty (no args) when MFA mode is off, so legacy behavior is unaffected.
#
# ControlPath uses the literal tokens %r-%h-%p (user, hostname-as-typed-on-CLI,
# port) instead of %C (a SHA1 hash of (local_hostname, host, port, user)).
# Why: %C is fragile when ~/.ssh/config has CanonicalizeHostname, Hostname
# rewrites, or Match-block User overrides -- the hash inputs differ between
# the explicit-`-J` opening call and a later call that resolves the same
# destination through a config alias, producing two different socket paths
# for what is logically the same connection. The literal tokens %r/%h/%p
# come from the command line, before config rewrites, so they're stable.
# Trade-off: one master per (user, host, port) tuple as typed, no per-local-
# hostname segregation -- fine since this directory is per-user already.
ssh_mux_args() {
  mfa_enabled || return 0
  mkdir -p "$SSH_MUX_DIR"
  chmod 700 "$SSH_MUX_DIR" 2>/dev/null || true
  local persist="${ARGO_ANYWHERE_CONTROL_PERSIST:-$SSH_MUX_PERSIST_DEFAULT}"
  printf -- '-o ControlMaster=auto -o ControlPath=%s/argo-anywhere-%%r-%%h-%%p -o ControlPersist=%s' \
    "$SSH_MUX_DIR" "$persist"
}

# Close any open master sockets we own. Called by `clean` and on demand.
#
# H8 fix (audit Phase 2b Batch 5): the prior implementation used
#   ssh -O exit -o "ControlPath=${sock}" x
# where 'x' was a dummy hostname. ssh -O exit requires a destination
# argument syntactically, but if the master socket is already gone or
# stale (the file exists but the master pid is dead), ssh may fall
# back to a normal connection attempt against the literal hostname
# 'x'. Depending on the user's ~/.ssh/config and DNS, that can either
# fail noisily or -- worse -- hit some unrelated host literally
# resolved to 'x'. Switch to:
#   ssh -O exit -S "${sock}" placeholder
# where -S is the canonical socket-only flag (more explicit than
# overloading ControlPath via -o); 'placeholder' is purely positional
# and is never contacted because -O exit returns before any connection
# attempt. Also pre-check [ -S "$sock" ] (already done by the for-loop
# guard) so the only way to reach the ssh call is a live socket file.
ssh_mux_close_all() {
  local sock
  if [ ! -d "$SSH_MUX_DIR" ]; then return 0; fi
  # Enumerate BOTH the current name (argo-anywhere-*) AND the pre-v2.0
  # name (argo-opencode-*) so users upgrading from v1.x get their stale
  # sockets cleaned up too.
  for sock in "$SSH_MUX_DIR"/argo-anywhere-* "$SSH_MUX_DIR"/argo-opencode-*; do
    [ -S "$sock" ] || continue
    log "  closing mux socket: ${sock}"
    if [ "${CLEAN_DRY_RUN:-0}" = 1 ]; then
      log "    [dry-run] would: ssh -O exit -S ${sock} placeholder"
    else
      # H8 fix: -S is the canonical socket-only flag; 'placeholder' is
      # purely positional and is never contacted by 'ssh -O exit'.
      ssh -O exit -S "${sock}" placeholder 2>/dev/null || rm -f "$sock"
    fi
  done
}

# Args used by every ssh/scp call. Combines mux + jump options.
# Use as: ssh $(ssh_args "$user" "$host") "$user@$host" ...
#
# The optional <host> arg is forwarded to ssh_jump_args so the '-J' option
# is suppressed when host == ANL_JUMP (avoids the jumphost-loop error).
# Backward-compatible: omitting it just means we always emit -J under jump
# mode; safe for every call site EXCEPT ssh_preflight when targeting the
# jump host directly.
ssh_args() {
  local user="$1" target="${2:-}"
  local mux jump
  mux="$(ssh_mux_args || true)"
  jump="$(ssh_jump_args "$user" "$target" || true)"
  # Print joined; either piece may be empty.
  printf '%s' "${mux}${mux:+ }${jump}"
}

# Reachability test that works under Duo: when MFA is on, do a real connect
# (no BatchMode) with a generous timeout; when MFA is off, fall back to the
# old BatchMode test.
# Usage: ssh_reachable <user> <host>
#
# Tracked by the SSH attempt tracker -- a streak of failures here is the
# most likely path to a CSPO IP block (broken agent / wrong username).
ssh_reachable() {
  local user="$1" host="$2"
  ssh_attempt_pre || return 1
  local rc=0
  if mfa_enabled; then
    # No BatchMode -- this WILL prompt Duo if no master socket exists yet.
    # ConnectTimeout is per network attempt, not per Duo prompt.
    # Pass $host so ssh_args drops '-J' when host == ANL_JUMP (loop guard).
    # shellcheck disable=SC2046
    ssh -o ConnectTimeout=15 -o StrictHostKeyChecking=accept-new \
        $(ssh_args "$user" "$host") "${user}@${host}" true 2>/dev/null \
      || rc=$?
  else
    # shellcheck disable=SC2046
    ssh -o BatchMode=yes -o ConnectTimeout=5 -o StrictHostKeyChecking=accept-new \
        $(ssh_args "$user" "$host") "${user}@${host}" true 2>/dev/null \
      || rc=$?
  fi
  if [ "$rc" -eq 0 ]; then
    ssh_attempt_ok
    return 0
  else
    ssh_attempt_fail
    return "$rc"
  fi
}

# Open the multiplex master to the given host explicitly. Triggers Duo once
# and leaves the master alive per ControlPersist. Useful before kicking off
# multiple commands so the user gets one prompt up front rather than at a
# random later moment.
# Usage: ssh_mux_open <user> <host>
#
# Tracked by the SSH attempt tracker (see ssh_attempt_pre/ok/fail). If the
# tracker is locked, refuse to make the attempt and die with a clear message
# so the user understands why no Duo prompt fired.
ssh_mux_open() {
  local user="$1" host="$2"
  mfa_enabled || return 0
  if ! ssh_attempt_pre; then
    die "Aborted: open SSH master (SSH failure lock active; recovery above)."
  fi
  log "Opening multiplexed SSH master to ${user}@${host} (Duo prompt expected once)..."
  # Pass $host so ssh_args knows to drop '-J' when host == ANL_JUMP (loop).
  # ServerAliveInterval/CountMax: if the network stalls after auth (laptop
  # resumes, flaky VPN, etc.) the master must die on its own so the script
  # fails cleanly rather than hanging forever and forcing a manual Ctrl-C +
  # restart (which resets the in-memory failure counter and risks more auth
  # attempts against CSPO's rate limiter).
  # shellcheck disable=SC2046
  if ssh -o ConnectTimeout=30 -o StrictHostKeyChecking=accept-new \
       -o ServerAliveInterval=15 -o ServerAliveCountMax=4 \
       $(ssh_args "$user" "$host") "${user}@${host}" true; then
    ssh_attempt_ok
    ok "  master ready (subsequent SSH calls will reuse this connection)"
  else
    ssh_attempt_fail
    die "Failed to open multiplexed SSH master to ${user}@${host}."
  fi
}

# ============================================================================
# SECTION: 10. USERNAME RESOLUTION (resolve_username, cache I/O)
# ============================================================================
resolve_username() {
  # Priority: --user flag (sets ARGO_ANYWHERE_USER) > env > cache > prompt.
  # ANL_USERNAME is honored as a deprecated alias (warning printed once
  # at top-level when promoted into ARGO_ANYWHERE_USER).
  if [ -n "${ARGO_ANYWHERE_USER:-}" ]; then
    echo "$ARGO_ANYWHERE_USER"; return
  fi
  if [ -f "$USER_CACHE" ]; then
    cat "$USER_CACHE"; return
  fi
  local u
  while :; do
    u="$(ask "Enter your ANL username (e.g. jdoe):")"
    [[ "$u" =~ ^[a-zA-Z][a-zA-Z0-9._-]*$ ]] && break
    err "Invalid username. Use letters, digits, dot, underscore, hyphen."
  done
  # L1 fix (audit Phase 2c) -- refactored in B2 (Phase 4) to call
  # _ensure_state_dir, which centralizes the mkdir-with-stderr-capture
  # pattern (was inline here; now shared with write_port_cache and
  # other state-dir writers).
  _ensure_state_dir
  printf '%s\n' "$u" > "$USER_CACHE"
  echo "$u"
}

# Read a top-level YAML scalar value from a file. Handles the three
# scalar forms PyYAML and humans actually emit:
#   key: value           (plain ASCII; PyYAML's safe_dump default)
#   key: "value"         (double-quoted; our fallback writer + example file)
#   key: 'value'         (single-quoted; some hand-edited configs)
# Strips surrounding whitespace and comments. Returns empty string if
# the file doesn't exist, the key is absent, or the value parses to
# empty.
#
# IMPORTANT: this function exists because the awk -F'"' parser used
# previously (commits 30915ac (H5 fix) and the existing identity-resolution
# path) only matched the quoted form. PyYAML's safe_dump emits plain
# ASCII strings unquoted by default, so the previous parser silently
# returned empty on the common case -- which made H5 fire a false
# "config.yaml is missing or unreadable" refusal during the first live
# test of Phase 2b.
#
# Usage: yaml_scalar <path> <key>
yaml_scalar() {
  local path="$1" key="$2"
  [ -f "$path" ] || { echo ""; return; }
  awk -v k="$key" '
    BEGIN { pat = "^[[:space:]]*" k ":[[:space:]]*" }
    {
      if (match($0, pat)) {
        v = substr($0, RSTART + RLENGTH)
        # Strip trailing comments (anything after an unquoted `#`).
        # Cheap heuristic: if the value starts with a quote, find the
        # closing quote and ignore everything after; else cut at the
        # first `#`.
        if (substr(v, 1, 1) == "\"") {
          # Double-quoted scalar.
          end = index(substr(v, 2), "\"")
          if (end > 0) v = substr(v, 2, end - 1)
        } else if (substr(v, 1, 1) == "'\''") {
          # Single-quoted scalar.
          end = index(substr(v, 2), "'\''")
          if (end > 0) v = substr(v, 2, end - 1)
        } else {
          # Plain scalar: strip inline `# comment` and trailing whitespace.
          h = index(v, "#")
          if (h > 0) v = substr(v, 1, h - 1)
          sub(/[[:space:]]+$/, "", v)
        }
        print v
        exit
      }
    }
  ' "$path" 2>/dev/null
}

# ============================================================================
# SECTION: 10b. INSTALL MANIFEST (D-025 / Lifecycle Phase A)
# ============================================================================
# The manifest records provenance so a future `uninstall` can restore
# client configs correctly + remove only binaries we installed. It is:
#   * laptop-side only (never written on a compute node);
#   * first-touch-wins (an existing entry is never overwritten -> the
#     earliest recording is the true pre-argo-anywhere original);
#   * best-effort (a manifest failure must NEVER break a config write --
#     this is bookkeeping, not a load-bearing operation). Every helper
#     swallows its own errors and returns 0.
#
# Schema (see ARGO_MANIFEST_SCHEMA):
#   { "schema": 1, "installed_at": <iso|null>,
#     "configs": { "<abspath>": { "first_touched": <iso>,
#                                 "preexisted": bool,
#                                 "created_by_us": bool } },
#     "binaries": { "<tool>": { "installed_by_us": true,
#                               "path": <str>, "method": <str>,
#                               "recorded_at": <iso> } } }

# _manifest_migrate_home: one-shot move of the manifest from its pre-D-030
# home (ARGO_MANIFEST_LEGACY = ${ARGO_INSTALL_DIR}/manifest.json) to the
# state dir (ARGO_MANIFEST). Idempotent + best-effort; runs before any
# manifest read/write (via _manifest_available) so both the record and the
# uninstall-restore paths see the migrated file. No-op when the legacy file
# is absent, the new file already exists, or the two paths coincide.
_manifest_migrate_home() {
  [ -f "$ARGO_MANIFEST_LEGACY" ] || return 0
  [ "$ARGO_MANIFEST_LEGACY" = "$ARGO_MANIFEST" ] && return 0
  [ -f "$ARGO_MANIFEST" ] && return 0
  mkdir -p "$(dirname "$ARGO_MANIFEST")" 2>/dev/null || return 0
  mv -f "$ARGO_MANIFEST_LEGACY" "$ARGO_MANIFEST" 2>/dev/null || true
  return 0
}

# _manifest_available: 0 if we can + should write the manifest (python3
# present AND not on a compute node), 1 otherwise. Keeps the guards in one
# place so callers stay one-liners. Migrates the manifest home (D-030)
# before returning success so every read/write sees the current location.
_manifest_available() {
  [ "$(on_anl_compute_node)" = "yes" ] && return 1
  command -v python3 >/dev/null 2>&1 || return 1
  _manifest_migrate_home
  return 0
}

# manifest_record_config <abspath> <preexisted:0|1>: record a client
# config's provenance at first touch. First-touch-wins: if an entry for
# <abspath> already exists, this is a no-op (preserves the true original).
# Best-effort; never fails the caller.
manifest_record_config() {
  _manifest_available || return 0
  local path="$1" preexisted="$2"
  python3 - "$ARGO_MANIFEST" "$ARGO_MANIFEST_SCHEMA" "$path" "$preexisted" <<'PYEOF' 2>/dev/null || true
import json, os, sys, tempfile, datetime
manifest, schema, path, preexisted = sys.argv[1], int(sys.argv[2]), sys.argv[3], sys.argv[4]

data = {}
if os.path.isfile(manifest):
    try:
        with open(manifest) as f:
            data = json.load(f) or {}
    except Exception:
        data = {}
if not isinstance(data, dict):
    data = {}
data.setdefault("schema", schema)
data.setdefault("installed_at", None)
data.setdefault("configs", {})
data.setdefault("binaries", {})
if not isinstance(data["configs"], dict):
    data["configs"] = {}

# First-touch-wins: never overwrite an existing entry.
if path not in data["configs"]:
    pre = (preexisted == "1")
    data["configs"][path] = {
        "first_touched": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        "preexisted": pre,
        "created_by_us": (not pre),
    }

os.makedirs(os.path.dirname(manifest), exist_ok=True)
fd, tmp = tempfile.mkstemp(dir=os.path.dirname(manifest), prefix=".manifest.", suffix=".tmp")
try:
    with os.fdopen(fd, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    os.replace(tmp, manifest)   # atomic within the same filesystem
except Exception:
    try:
        os.unlink(tmp)
    except Exception:
        pass
PYEOF
}

# manifest_record_binary <tool> <path> <method>: record that THIS script
# installed a tool binary (so uninstall --remove-binaries can remove only
# our installs). First-touch-wins per tool. Best-effort.
manifest_record_binary() {
  _manifest_available || return 0
  local tool="$1" path="$2" method="$3"
  python3 - "$ARGO_MANIFEST" "$ARGO_MANIFEST_SCHEMA" "$tool" "$path" "$method" <<'PYEOF' 2>/dev/null || true
import json, os, sys, tempfile, datetime
manifest, schema, tool, path, method = sys.argv[1:6]
schema = int(schema)

data = {}
if os.path.isfile(manifest):
    try:
        with open(manifest) as f:
            data = json.load(f) or {}
    except Exception:
        data = {}
if not isinstance(data, dict):
    data = {}
data.setdefault("schema", schema)
data.setdefault("installed_at", None)
data.setdefault("configs", {})
data.setdefault("binaries", {})
if not isinstance(data["binaries"], dict):
    data["binaries"] = {}

if tool not in data["binaries"]:
    data["binaries"][tool] = {
        "installed_by_us": True,
        "path": path,
        "method": method,
        "recorded_at": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
    }

os.makedirs(os.path.dirname(manifest), exist_ok=True)
fd, tmp = tempfile.mkstemp(dir=os.path.dirname(manifest), prefix=".manifest.", suffix=".tmp")
try:
    with os.fdopen(fd, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    os.replace(tmp, manifest)
except Exception:
    try:
        os.unlink(tmp)
    except Exception:
        pass
PYEOF
}

# ============================================================================
# SECTION: 11. CONFIG FILE HANDLING (handle_config_file, k/b/d/m/a prompt)
# ============================================================================
# Used for both ~/.config/opencode/config.json and the argo-proxy YAML.
# Args: <path-to-existing-or-not> <description> <writer-fn>
# writer-fn must accept a single arg (destination path) and write a fresh file.
handle_config_file() {
  local target="$1" desc="$2" writer="$3"
  local dir; dir="$(dirname "$target")"
  mkdir -p "$dir"

  # Manifest (Lifecycle Phase A): record this config's provenance at the
  # FIRST moment we touch it -- BEFORE any write -- because right now is
  # when we still know whether it pre-existed. First-touch-wins inside
  # the helper means re-runs don't clobber the true original. Best-effort;
  # a no-op on compute nodes (the argo-proxy YAML also flows through here
  # in mode_server, but the manifest is a laptop-side client-config
  # concept and _manifest_available screens the node out).
  local _preexisted=0
  [ -f "$target" ] && _preexisted=1
  manifest_record_config "$target" "$_preexisted"

  if [ ! -f "$target" ]; then
    log "No existing ${desc} at ${target}; writing fresh one."
    "$writer" "$target"
    ok "Wrote ${desc}: ${target}"
    return
  fi

  # Render the proposed new config to a temp file for diffing.
  local proposed; proposed="$(mktemp -t argo_anywhere.XXXXXX)"
  trap 'rm -f "$proposed"' RETURN
  "$writer" "$proposed"

  if cmp -s "$target" "$proposed"; then
    ok "${desc} already up to date: ${target}"
    rm -f "$proposed"; trap - RETURN
    return
  fi

  warn "${desc} already exists at ${target} and differs from the proposed version."
  while :; do
    cat >&2 <<EOF

  Choose how to handle ${target}:
    [k] keep existing (no changes)
    [b] backup existing to .bak.<timestamp>, then overwrite
    [d] show diff (existing -> proposed), then ask again
    [m] merge: only update keys this script manages (requires jq for JSON)
    [a] abort
EOF
    local choice; choice="$(ask "Your choice [k/b/d/m/a]:" "k")"
    case "$choice" in
      k|K) ok "Keeping existing ${desc}."; break ;;
      b|B)
        # Backup name includes $$ (this shell's PID) for uniqueness when
        # two invocations both reach this branch within the same second.
        # Plain seconds-resolution timestamps would clobber each other in
        # that race; PID makes each invocation's backup unique.
        local bak
        bak="${target}.bak.$(date +%Y%m%d-%H%M%S).$$"
        cp -p "$target" "$bak"
        cp "$proposed" "$target"
        ok "Backed up to ${bak} and overwrote ${desc}."
        break ;;
      d|D)
        if command -v diff >/dev/null 2>&1; then
          diff -u "$target" "$proposed" >&2 || true
        else
          warn "diff not available; showing proposed file:"; cat "$proposed" >&2
        fi
        ;;
      m|M)
        if [[ "$target" == *.json ]] && command -v jq >/dev/null 2>&1; then
          # Merge: proposed values win for keys present in proposed.
          local merged; merged="$(mktemp -t argo_anywhere.XXXXXX)"
          jq -s '.[0] * .[1]' "$target" "$proposed" > "$merged"
          cp "$merged" "$target"; rm -f "$merged"
          ok "Merged proposed keys into existing ${desc}."
          break
        elif [[ "$target" == *.yaml ]] || [[ "$target" == *.yml ]]; then
          warn "YAML merge not supported here. Pick [b] to overwrite or [k] to keep."
        else
          warn "Merge requires jq for JSON files. Install jq or pick another option."
        fi
        ;;
      a|A) rm -f "$proposed"; trap - RETURN; die "Aborted at ${desc} step." ;;
      *)   warn "Unrecognized choice: ${choice}" ;;
    esac
  done

  rm -f "$proposed"; trap - RETURN
}

# _validate_scope_for_tool: D-018 per-tool scope vocabulary validation.
# Called by per-tool <name>_pick_scope() after resolving the explicit
# --scope / ARGO_ANYWHERE_SCOPE value. Validates against the tool's
# <name>_scope_values() output (space-separated list). Dies with a
# clear "Tool X accepts: Y Z" message on rejection.
#
# Args:
#   $1 tool   -- the lowercase tool token (e.g. "claudecode", "opencode")
#   $2 scope  -- the scope value the user supplied
#
# Returns 0 (silent) on success; die on rejection.
_validate_scope_for_tool() {
  local tool="$1" scope="$2"
  local values_fn="${tool}_scope_values"
  if ! command -v "$values_fn" >/dev/null 2>&1; then
    die "_validate_scope_for_tool: no scope vocabulary defined for tool '${tool}' (expected function ${values_fn}). This is a script bug (CLI_TOOLS_AVAILABLE registry inconsistency)."
  fi
  local allowed; allowed="$("$values_fn")"
  local v
  for v in $allowed; do
    if [ "$v" = "$scope" ]; then
      return 0
    fi
  done
  die "--scope value '${scope}' is not valid for --cli-tool ${tool}. Accepted values: ${allowed}."
}

# prompt_scope_switch: D-017 scope-switch prompt. Fires from per-tool
# <name>_pick_scope() when a conflict is detected between the user's
# chosen scope and the system state (existing files, OAuth state, etc.).
#
# Two-prompt model: this prompt resolves the scope question; the
# subsequent handle_config_file call resolves the per-file content
# question via the existing [k/b/d/m/a] vocabulary. The two prompts
# have stable letter meanings (D-015 alignment); the scope letters are
# never used in handle_config_file and the content letters are never
# used here.
#
# Args:
#   $1 conflict_desc  -- short paragraph describing why the conflict matters
#   $2 current_scope  -- the scope the user intends ("global" / "project" / ...)
#   $3 other_scope    -- the alternative scope to offer (specific to the tool)
#
# Prints (to stdout) one of:
#   keep    -- user accepts the conflict; proceed with current_scope
#   switch  -- user switches to other_scope; caller must re-resolve path/name
# Dies on [a]bort.
prompt_scope_switch() {
  local conflict_desc="$1" current_scope="$2" other_scope="$3"
  warn "Scope conflict detected:"
  cat >&2 <<EOF

  ${conflict_desc}

  Choose how to resolve:
    [k] keep current scope (${current_scope}); proceed as-is
    [s] switch to ${other_scope} scope instead
    [a] abort; reconcile manually
EOF
  local choice; choice="$(ask "Your choice [k/s/a]:" "k")"
  case "$choice" in
    k|K) printf '%s' "keep" ;;
    s|S) printf '%s' "switch" ;;
    a|A) die "Aborted at scope-conflict step." ;;
    *)   die "Unrecognized choice; aborting." ;;
  esac
}

# ============================================================================
# SECTION: 12. OPENCODE CONFIG WRITER + INSTALLER (laptop side)
# ============================================================================
# Mirrors the maintainer's ~/.config/opencode/config.json, with the username
# substituted. Uses localhost (not 0.0.0.0) for clarity.
#
# The username is taken from the canonical env var ARGO_ANYWHERE_USER, with
# legacy ANL_USERNAME as fallback. This writer is invoked indirectly via
# handle_config_file (which always passes only the destination path), so we
# can't accept user as a positional arg without changing that contract.
write_opencode_config() {
  local dest="$1"
  local user="${ARGO_ANYWHERE_USER:-${ANL_USERNAME:-}}"
  [ -n "$user" ] || die "write_opencode_config: no username available (ARGO_ANYWHERE_USER unset)"
  # L6 fix (audit Phase 2d): assert PROXY_PORT is set before writing.
  # Pre-fix, an empty PROXY_PORT would interpolate into the baseURL as
  # 'http://localhost:/v1' -- a syntactically valid URL that points
  # nowhere, and OpenCode would silently fail to connect. resolve_port
  # always runs before this writer in the normal client flow, but a
  # script-internal refactor or a direct call from an untested path
  # could bypass it; this assert ensures the broken-config silent-fail
  # is converted to a fail-loud die at the writer entry.
  [ -n "${PROXY_PORT:-}" ] || die "write_opencode_config: PROXY_PORT is empty (resolve_port not called?). Refusing to write a config with baseURL 'http://localhost:/v1' that would silently fail to connect."
  cat > "$dest" <<EOF
{
  "\$schema": "https://opencode.ai/config.json",
  "provider": {
    "argo": {
      "npm": "@ai-sdk/openai-compatible",
      "name": "Argo Gateway API",
      "options": {
        "baseURL": "http://localhost:${PROXY_PORT}/v1",
        "apiKey": "${user}",
        "headers": {
          "Authorization": "Bearer ${user}"
        }
      },
      "models": {
        "gpt54": {
          "name": "GPT-5.4",
          "modalities": { "input": ["text", "image"], "output": ["text"] }
        },
        "claudeopus47": {
          "name": "Claude Opus 4.7",
          "modalities": { "input": ["text", "image"], "output": ["text"] }
        },
        "claudeopus46": {
          "name": "Claude Opus 4.6",
          "modalities": { "input": ["text", "image"], "output": ["text"] }
        },
        "claudesonnet46": {
          "name": "Claude Sonnet 4.6",
          "modalities": { "input": ["text", "image"], "output": ["text"] }
        },
        "claudehaiku45": {
          "name": "Claude Haiku 4.5",
          "modalities": { "input": ["text", "image"], "output": ["text"] }
        }
      }
    }
  }
}
EOF
}

# ----------------------------------------------------------------------------
# OpenCode install (subsection of 12; brew on macOS, curl|bash elsewhere)
# ----------------------------------------------------------------------------
ensure_opencode_installed() {
  if command -v opencode >/dev/null 2>&1; then
    ok "OpenCode already installed: $(command -v opencode)"
    return
  fi
  log "Installing OpenCode..."
  case "$(detect_os)" in
    macos)
      if command -v brew >/dev/null 2>&1; then
        brew install sst/tap/opencode
      else
        warn "Homebrew not found; falling back to upstream installer."
        curl -fsSL https://opencode.ai/install | bash
      fi
      ;;
    linux)
      curl -fsSL https://opencode.ai/install | bash
      ;;
    *)
      die "Unsupported OS for automatic install. Install OpenCode manually then re-run."
      ;;
  esac

  # The upstream Linux installer (and the brew fallback path on a macOS
  # without /usr/local/bin on PATH) drops the binary at $HOME/.opencode/bin
  # and modifies ~/.bashrc / ~/.zshrc to extend PATH. Our running shell
  # doesn't re-source the shell rc files, so `command -v opencode` would
  # immediately fail right after a successful install.
  #
  # Mitigate by prepending the installer's known location to PATH for the
  # rest of THIS script invocation. The user's interactive shells will
  # pick up the rc-file change naturally on next login. If the binary
  # really isn't there after install, fall through to the die() with a
  # message that points at the actual recovery action.
  # L7 fix (audit Phase 2c): also check Homebrew install locations on
  # macOS (Apple Silicon = /opt/homebrew/bin/opencode; Intel macOS =
  # /usr/local/bin/opencode). Pre-fix only checked ~/.opencode/bin/,
  # which is the upstream curl|bash location (and the brew-fallback
  # path on a macOS without /usr/local/bin on PATH); the actual brew
  # success path drops the binary into one of the brew-managed prefixes.
  # Order matters: try the brew locations first so users on a brew
  # system get the brew-managed binary (which integrates with brew
  # upgrade workflows) rather than a dangling rc-file-PATH artifact.
  if ! command -v opencode >/dev/null 2>&1; then
    local _candidate
    for _candidate in \
        /opt/homebrew/bin/opencode \
        /usr/local/bin/opencode \
        "${HOME}/.opencode/bin/opencode"; do
      if [ -x "$_candidate" ]; then
        log "Installer placed binary at ${_candidate} but the new"
        log "  PATH only takes effect in fresh shells. Prepending its dir for this run."
        PATH="$(dirname "$_candidate"):${PATH}"
        export PATH
        break
      fi
    done
  fi

  if ! command -v opencode >/dev/null 2>&1; then
    err "OpenCode install reported success but the binary is not on PATH and"
    err "  was not found at any standard location:"
    err "    ~/.opencode/bin/opencode (upstream curl|bash installer)"
    err "    /opt/homebrew/bin/opencode (Homebrew on Apple Silicon)"
    err "    /usr/local/bin/opencode (Homebrew on Intel macOS)"
    err "  Try opening a new shell (or 'source ~/.bashrc' / 'source ~/.zshrc')"
    err "  and re-running this script."
    die "Cannot continue without a runnable opencode binary."
  fi
  ok "OpenCode installed: $(command -v opencode)"
  # Manifest: we (not the user) installed this binary -> eligible for
  # `uninstall --remove-binaries`. Recorded only on the just-installed
  # path (the already-installed early return above never reaches here).
  manifest_record_binary opencode "$(command -v opencode)" "upstream-installer"
}

# ----------------------------------------------------------------------------
# OpenCode end-to-end client setup (subsection of 12)
# ----------------------------------------------------------------------------

# opencode_scope_values: D-018 per-tool scope vocabulary. OpenCode
# supports both global (~/.config/opencode/config.json) and project
# (<git-root>/opencode.json, falling back to <cwd>/opencode.json if
# not in a git repo) scopes since Phase 4 B1b.
opencode_scope_values() {
  printf 'global project'
}

_OPENCODE_SCOPE_PATH=""
_OPENCODE_SCOPE_NAME=""

# opencode_pick_scope: B1b (Phase 4) -- D-017 conflict-detection
# discipline applied to opencode. opencode has no OAuth-state concern
# (unlike claudecode's ~/.claude.json) so the per-tool default is
# global; conflict-detection still runs (A.1 existing-content-collision;
# B.2 cwd-not-a-project for explicit --scope project).
#
# Per the D-017 two-prompt model, this picker may invoke
# prompt_scope_switch on detected conflict; the subsequent
# handle_config_file call resolves any per-file content disagreement
# via the existing [k/b/d/m/a] vocabulary.
#
# Project-scope resolution: writes to <git-root>/opencode.json if cwd
# is inside a git repo; else <cwd>/opencode.json. The git-root anchor
# matches OpenCode's own upstream config-discovery behavior (walks up
# to nearest .git for project-local configs).
opencode_pick_scope() {
  # Resolve the effective scope source: explicit > auto-default.
  local _intended_scope=""
  local _scope_source=""
  if [ -n "${_SCOPE_OVERRIDE:-}" ]; then
    _intended_scope="$_SCOPE_OVERRIDE"
    _scope_source="--scope ${_intended_scope}"
  elif [ -n "${ARGO_ANYWHERE_SCOPE:-}" ]; then
    _intended_scope="$ARGO_ANYWHERE_SCOPE"
    _scope_source="ARGO_ANYWHERE_SCOPE env"
  fi

  if [ -n "$_intended_scope" ]; then
    _validate_scope_for_tool opencode "$_intended_scope"
  else
    # Per-tool auto-default: global. (No OAuth-state concern.)
    _intended_scope="global"
    _scope_source="auto (opencode default; no OAuth-state concern)"
  fi

  # Resolve the path + label from the intended scope.
  case "$_intended_scope" in
    global)
      _OPENCODE_SCOPE_PATH="$OPENCODE_GLOBAL_CONFIG"
      _OPENCODE_SCOPE_NAME="global (${OPENCODE_GLOBAL_CONFIG})"
      ;;
    project)
      local _proj_root; _proj_root="$(_git_root_or_cwd)"
      _OPENCODE_SCOPE_PATH="${_proj_root}/${OPENCODE_PROJECT_CONFIG_BASENAME}"
      _OPENCODE_SCOPE_NAME="project (${_OPENCODE_SCOPE_PATH})"
      ;;
    *)
      die "opencode_pick_scope: internal error -- intended scope '${_intended_scope}' not in vocabulary (opencode_scope_values returns: $(opencode_scope_values))."
      ;;
  esac

  log "OpenCode scope: ${_intended_scope} (${_scope_source})."
  if [ "$_intended_scope" = "project" ]; then
    log "  Config will land at ${_OPENCODE_SCOPE_PATH} and apply only when"
    log "  'opencode' is invoked from within this project tree."
  else
    log "  Config will land at ${_OPENCODE_SCOPE_PATH} and apply when"
    log "  'opencode' is invoked from any directory."
  fi

  # Conflict detection. opencode has fewer conflict paths than
  # claudecode (no OAuth state); just A.1 (existing content) for global
  # and B.2 (cwd-not-a-project) for explicit project.
  _opencode_check_conflicts "$_intended_scope"
}

# _opencode_check_conflicts: per-scope conflict detection + scope-switch
# prompt invocation. Mutates _OPENCODE_SCOPE_PATH / _OPENCODE_SCOPE_NAME
# if user chooses to switch.
_opencode_check_conflicts() {
  local intended="$1"
  local conflict_desc=""
  local other_scope=""
  if [ "$intended" = "global" ]; then
    other_scope="project"
    # A.1: existing global file with content. handle_config_file's
    # [k/b/d/m/a] would normally handle this, but offering the scope
    # switch here is a more visible signal that there's a choice.
    if [ -f "$OPENCODE_GLOBAL_CONFIG" ] && [ -s "$OPENCODE_GLOBAL_CONFIG" ]; then
      conflict_desc="${OPENCODE_GLOBAL_CONFIG} already exists and is non-empty. You can keep global scope (a later prompt will ask how to handle the existing file), or switch to project scope now to leave your global file untouched (writes <git-root>/opencode.json or cwd/opencode.json instead)."
    fi
  elif [ "$intended" = "project" ]; then
    other_scope="global"
    # B.2: cwd-doesn't-look-like-project check.
    local _is_project=0
    if command -v git >/dev/null 2>&1 && git rev-parse --show-toplevel >/dev/null 2>&1; then
      _is_project=1
    elif [ -f "package.json" ] || [ -f "pyproject.toml" ] || [ -f "Cargo.toml" ] || [ -f "go.mod" ]; then
      _is_project=1
    elif [ "$(pwd)" = "$HOME" ]; then
      _is_project=1
    fi
    if [ "$_is_project" = 0 ]; then
      conflict_desc="--scope project will write $(pwd)/${OPENCODE_PROJECT_CONFIG_BASENAME}, but $(pwd) doesn't look like a project directory (no .git ancestor, no common project manifests). Most users in this situation want --scope global so 'opencode' works from any directory."
    fi
  fi

  if [ -n "$conflict_desc" ]; then
    local _ssc_choice
    _ssc_choice="$(prompt_scope_switch "$conflict_desc" "$intended" "$other_scope")"
    case "$_ssc_choice" in
      keep)
        log "  Proceeding with ${intended} scope despite the conflict (user's choice)."
        ;;
      switch)
        case "$other_scope" in
          project)
            local _proj_root; _proj_root="$(_git_root_or_cwd)"
            _OPENCODE_SCOPE_PATH="${_proj_root}/${OPENCODE_PROJECT_CONFIG_BASENAME}"
            _OPENCODE_SCOPE_NAME="project (${_OPENCODE_SCOPE_PATH})"
            ;;
          global)
            _OPENCODE_SCOPE_PATH="$OPENCODE_GLOBAL_CONFIG"
            _OPENCODE_SCOPE_NAME="global (${OPENCODE_GLOBAL_CONFIG})"
            ;;
        esac
        log "  Switched to ${other_scope} scope; will write ${_OPENCODE_SCOPE_PATH}."
        ;;
    esac
  fi
}

# setup_opencode_cli_tool: ensure OpenCode is installed and its config is up to
# date for the resolved (PROXY_PORT, ANL_USERNAME). Idempotent. Honors the
# SKIP_OPENCODE_CONFIG_WRITE flag set by mode_client when the user picked [u]
# at the port-mismatch prompt.
#
# B1b (Phase 4) reordering: opencode_pick_scope() runs BEFORE
# ensure_opencode_installed (same rationale as setup_claudecode_cli_tool's
# reordering -- scope decision doesn't depend on installed binary; fail
# fast on scope conflicts before doing the expensive install).
#
# This is the "per-client" piece of mode_client, extracted so future per-client
# setup functions (setup_claudecode_cli_tool, setup_aider_cli_tool, ...) can sit
# next to it as peers and the orchestrator can call any combination.
setup_opencode_cli_tool() {
  opencode_pick_scope
  ensure_opencode_installed
  if [ "${SKIP_OPENCODE_CONFIG_WRITE:-0}" = 1 ]; then
    log "Skipping OpenCode config write (--port override + [u] choice)."
    log "  ${_OPENCODE_SCOPE_PATH} baseURL is unchanged at port ${PORT_FROM_CONFIG};"
    log "  this run's tunnel is on port ${PROXY_PORT}."
  else
    handle_config_file "${_OPENCODE_SCOPE_PATH}" "OpenCode config (${_OPENCODE_SCOPE_NAME})" write_opencode_config
  fi
}

# ----------------------------------------------------------------------------
# Claude Code config writer + installer + end-to-end client setup
# (subsection of 12; peer of setup_opencode_cli_tool)
# ----------------------------------------------------------------------------
# ensure_claudecode_installed: detect or install the upstream `claude` CLI.
#
# Upstream installer drops the binary at ~/.claude/local/claude (Linux) or
# /opt/homebrew/bin/claude (macOS via the standalone installer's PATH
# update to ~/.bashrc / ~/.zshrc). As with OpenCode, the rc-file PATH
# update doesn't reach the running shell, so we prepend the well-known
# locations after install. See the analogous mitigation in
# ensure_opencode_installed for the rationale.
ensure_claudecode_installed() {
  if command -v claude >/dev/null 2>&1; then
    ok "Claude Code already installed: $(command -v claude)"
    return
  fi
  log "Installing Claude Code..."
  case "$(detect_os)" in
    macos|linux)
      # Anthropic's documented installer; works on both macOS and Linux.
      curl -fsSL https://claude.ai/install.sh | bash
      ;;
    *)
      die "Unsupported OS for automatic install. Install Claude Code manually then re-run."
      ;;
  esac

  if ! command -v claude >/dev/null 2>&1; then
    local cand
    for cand in "${HOME}/.claude/local/claude" "${HOME}/.local/bin/claude"; do
      if [ -x "$cand" ]; then
        log "Installer placed binary at ${cand} but the new PATH only takes"
        log "  effect in fresh shells. Prepending it for this run."
        PATH="$(dirname "$cand"):${PATH}"
        export PATH
        break
      fi
    done
  fi

  if ! command -v claude >/dev/null 2>&1; then
    err "Claude Code install reported success but the binary is not on PATH"
    err "  and was not found at the standard locations (~/.claude/local/claude,"
    err "  ~/.local/bin/claude). Try opening a new shell (or 'source ~/.bashrc'"
    err "  / 'source ~/.zshrc') and re-running this script."
    die "Cannot continue without a runnable claude binary."
  fi
  ok "Claude Code installed: $(command -v claude)"
  # Manifest: we installed this binary (already-installed early return
  # above never reaches here) -> eligible for `uninstall --remove-binaries`.
  manifest_record_binary claudecode "$(command -v claude)" "upstream-installer"
}

# =============================================================================
# claudecode scope handling -- B1a (Phase 4) rewrite per D-017 + D-018
# =============================================================================
#
# Decisions (PLAN.md):
#   D-017 -- Default scope is per-tool-declared with documented rationale.
#            claudecode uses HYBRID auto-default (see below). Per-tool
#            <name>_pick_scope() does conflict-detection before writing
#            and surfaces conflicts via the scope-switch prompt.
#   D-018 -- Per-tool scope vocabulary contract. Each tool has
#            <name>_scope_values() (the list of legal --scope values for
#            that tool) and <name>_pick_scope() (the picker).
#   D-019 -- ARGO_ANYWHERE_SCOPE is the user-facing env var (per D-009
#            namespace); _SCOPE_OVERRIDE is the internal global set by
#            the --scope CLI flag. Legacy CLAUDECODE_SCOPE auto-promotes
#            to ARGO_ANYWHERE_SCOPE with one-time WARN (Section 6).
#
# Hybrid default for claudecode (REVISES H6 fix from v2.0.0):
#   * If --scope / ARGO_ANYWHERE_SCOPE / CLAUDECODE_SCOPE (legacy) is set
#     explicitly -> use that value (after conflict validation; see below).
#   * Else if ~/.claude.json exists (OAuth state present; user has run
#     `claude auth login`) -> default to project. This is the H6 safety
#     case: writing global would silently shadow the user's personal
#     Anthropic subscription per Claude Code's OAuth precedence rules
#     (observed during Phase 2b live test #1; documented at length in
#     the H6 audit entry).
#   * Else (fresh install; no OAuth state) -> default to global. This
#     gives the convenient "claude works from any directory" UX for
#     users who came to argo-anywhere first and don't have a personal
#     subscription to protect.
#
# Conflict validation runs in BOTH the explicit and auto branches.
# Detected conflicts trigger the scope-switch prompt
# (prompt_scope_switch, defined in Section 11 alongside handle_config_file).
# Conflicts checked:
#   A.1  intended scope = global; ~/.claude/settings.json exists with content
#        (let user choose: keep current global / switch to project / abort)
#   A.2  intended scope = global; ~/.claude.json exists (OAuth state)
#        (let user choose: proceed with global anyway / switch to project / abort)
#   A.3  intended scope = global; ./.claude/settings.local.json exists in cwd
#        with our env keys (project will shadow it when run from cwd)
#   B.1  intended scope = project; ~/.claude/settings.json exists with our env keys
#        (global already has our config; project will shadow within cwd)
#   B.2  intended scope = project; cwd doesn't look like a project (no .git
#        ancestor + cwd != HOME)
#
# Why we never write to ./.claude/settings.json (the COMMITTED project
# file): doing so would force every collaborator on the user's git repo
# to also use this proxy. .claude/settings.local.json is gitignored by
# default by Claude Code itself, so it's the right place for per-machine
# overrides.

# claudecode_scope_values: declare the legal values for --scope when
# --cli-tool=claudecode. Used by _validate_scope_for_tool. Space-separated
# tokens; the validator splits on whitespace.
claudecode_scope_values() {
  printf 'project global'
}

_CLAUDECODE_SCOPE_PATH=""
_CLAUDECODE_SCOPE_NAME=""

# claudecode_pick_scope: resolve scope per the hybrid + two-prompt model.
# Sets _CLAUDECODE_SCOPE_PATH (file we'll write) and _CLAUDECODE_SCOPE_NAME
# (human-readable label) as script-level globals, since the writer
# (write_claudecode_config) is invoked via handle_config_file and gets
# only the destination path; the real target is read from
# _CLAUDECODE_SCOPE_PATH so the writer can merge from the actual existing
# file (handle_config_file passes a tempfile as $dest for the diff/merge
# dance).
claudecode_pick_scope() {
  # Resolve the effective scope source: explicit flag/env > hybrid auto.
  # Read order: _SCOPE_OVERRIDE (set by --scope CLI flag) >
  # ARGO_ANYWHERE_SCOPE env (set directly by user OR by Section 6
  # promotion from legacy CLAUDECODE_SCOPE).
  local _intended_scope=""
  local _scope_source=""
  if [ -n "${_SCOPE_OVERRIDE:-}" ]; then
    _intended_scope="$_SCOPE_OVERRIDE"
    _scope_source="--scope ${_intended_scope}"
  elif [ -n "${ARGO_ANYWHERE_SCOPE:-}" ]; then
    _intended_scope="$ARGO_ANYWHERE_SCOPE"
    _scope_source="ARGO_ANYWHERE_SCOPE env"
  fi

  if [ -n "$_intended_scope" ]; then
    # Explicit scope: validate against per-tool vocabulary first.
    _validate_scope_for_tool claudecode "$_intended_scope"
  else
    # Hybrid auto-default: ~/.claude.json present => project (safety);
    # absent => global (convenience).
    if [ -f "${HOME}/.claude.json" ]; then
      _intended_scope="project"
      _scope_source="auto (~/.claude.json detected; preserving personal subscription)"
    else
      _intended_scope="global"
      _scope_source="auto (fresh install; no OAuth state)"
    fi
  fi

  # Resolve the path + label from the intended scope.
  case "$_intended_scope" in
    project)
      _CLAUDECODE_SCOPE_PATH="$CLAUDECODE_PROJECT_CONFIG"
      _CLAUDECODE_SCOPE_NAME="project (${CLAUDECODE_PROJECT_CONFIG})"
      ;;
    global)
      _CLAUDECODE_SCOPE_PATH="$CLAUDECODE_GLOBAL_CONFIG"
      _CLAUDECODE_SCOPE_NAME="global (~/.claude/settings.json)"
      ;;
    *)
      # _validate_scope_for_tool should have die'd above; this is paranoia.
      die "claudecode_pick_scope: internal error -- intended scope '${_intended_scope}' not in vocabulary (claudecode_scope_values returns: $(claudecode_scope_values))."
      ;;
  esac

  log "Claude Code scope: ${_intended_scope} (${_scope_source})."
  if [ "$_intended_scope" = "project" ]; then
    log "  Config will land at ${CLAUDECODE_PROJECT_CONFIG} and apply only when"
    log "  'claude' is run from this directory ($(pwd))."
  else
    log "  Config will land at ${CLAUDECODE_GLOBAL_CONFIG} and apply when"
    log "  'claude' is run from any directory."
  fi

  # Conflict detection: see function-level comment above for the rules.
  # When a conflict is detected, prompt the user via prompt_scope_switch
  # (Section 11). The user's choice may MUTATE _intended_scope and trigger
  # a re-resolution of path + label.
  _claudecode_check_conflicts "$_intended_scope"
}

# _claudecode_check_conflicts: per-scope conflict detection + scope-switch
# prompt invocation. Called by claudecode_pick_scope after the intended
# scope is resolved; may mutate _CLAUDECODE_SCOPE_PATH / _CLAUDECODE_SCOPE_NAME
# if the user chooses to switch scope at the prompt.
_claudecode_check_conflicts() {
  local intended="$1"
  local conflict_desc=""
  local other_scope=""
  if [ "$intended" = "global" ]; then
    other_scope="project"
    # A.2 first (OAuth-state detected) -- highest-stakes because it's the
    # silent-shadowing landmine H6 was designed to prevent.
    if [ -f "${HOME}/.claude.json" ]; then
      conflict_desc="You have an active Claude Code OAuth session (~/.claude.json detected). Writing global proxy config may interact with OAuth precedence: ANTHROPIC_AUTH_TOKEN should win per Anthropic's docs, but we observed shadowing in real-world tests (see audit H6)."
    # A.1 -- existing global file with content; we'd be overwriting (or
    # merging via handle_config_file's [k/b/d/m/a] prompt later).
    elif [ -f "$CLAUDECODE_GLOBAL_CONFIG" ]; then
      local _has_content=0
      if command -v python3 >/dev/null 2>&1; then
        if python3 - "$CLAUDECODE_GLOBAL_CONFIG" >/dev/null 2>&1 <<'PYEOF'
import json, sys
try:
    with open(sys.argv[1]) as f:
        data = json.load(f)
    sys.exit(0 if (isinstance(data, dict) and len(data) > 0) else 1)
except Exception:
    sys.exit(2)
PYEOF
        then _has_content=1
        fi
      else
        # No python3 to inspect; assume content present if file is non-empty.
        [ -s "$CLAUDECODE_GLOBAL_CONFIG" ] && _has_content=1
      fi
      if [ "$_has_content" = 1 ]; then
        conflict_desc="${CLAUDECODE_GLOBAL_CONFIG} already exists and has content. You can keep global scope (a later prompt will ask how to handle the existing file), or switch to project scope now to leave your global file untouched."
      fi
    fi
    # A.3 -- project file in cwd already has our env keys (project will
    # shadow global within cwd). Detection requires inspecting the file's
    # env keys; defer to a later iteration if real-world use surfaces this.
    # (Recorded as a known gap; not a v2.2.0 blocker.)
  elif [ "$intended" = "project" ]; then
    other_scope="global"
    # B.2 first -- cwd-doesn't-look-like-project check.
    local _is_project=0
    if [ -d ".git" ] || [ -d "../.git" ] || [ -d "../../.git" ]; then
      _is_project=1
    elif [ -f "package.json" ] || [ -f "pyproject.toml" ] || [ -f "Cargo.toml" ] || [ -f "go.mod" ]; then
      _is_project=1
    elif [ "$(pwd)" = "$HOME" ]; then
      # HOME is an explicit-enough signal: user knows what they're doing.
      _is_project=1
    fi
    if [ "$_is_project" = 0 ]; then
      conflict_desc="--scope project will write $(pwd)/.claude/settings.local.json, but $(pwd) doesn't look like a project directory (no .git ancestor, no common project manifests). Most users in this situation want --scope global so 'claude' works from any directory."
    fi
    # B.1 -- existing global file with our env keys (global already has
    # our config; project will shadow within cwd). Similar to A.3;
    # deferred for now.
  fi

  if [ -n "$conflict_desc" ]; then
    local _ssc_choice
    _ssc_choice="$(prompt_scope_switch "$conflict_desc" "$intended" "$other_scope")"
    case "$_ssc_choice" in
      keep)
        # User accepts the conflict; proceed with intended scope.
        log "  Proceeding with ${intended} scope despite the conflict (user's choice)."
        ;;
      switch)
        # Re-resolve to the other scope.
        case "$other_scope" in
          project)
            _CLAUDECODE_SCOPE_PATH="$CLAUDECODE_PROJECT_CONFIG"
            _CLAUDECODE_SCOPE_NAME="project (${CLAUDECODE_PROJECT_CONFIG})"
            ;;
          global)
            _CLAUDECODE_SCOPE_PATH="$CLAUDECODE_GLOBAL_CONFIG"
            _CLAUDECODE_SCOPE_NAME="global (~/.claude/settings.json)"
            ;;
        esac
        log "  Switched to ${other_scope} scope; will write ${_CLAUDECODE_SCOPE_PATH}."
        ;;
    esac
  fi
}

# write_claudecode_config: produce a fresh Claude Code settings.json that
# points env.ANTHROPIC_BASE_URL at our proxy and uses the ANL username as
# the bearer token. Preserves any pre-existing top-level keys in the
# target file (model, permissions, hooks, etc.) and any pre-existing env
# entries OTHER than ANTHROPIC_BASE_URL / ANTHROPIC_AUTH_TOKEN /
# ANTHROPIC_MODEL (which we own).
#
# Per Claude Code docs, `env` is REPLACED across scope files, not
# deep-merged -- so when we write the project scope, anything in the
# global env that we don't carry forward is silently shadowed for that
# project. We only own three env keys here; everything else in the
# target file's env survives our write. The user's global env is
# untouched as long as we're writing to project scope.
#
# IMPORTANT: ANTHROPIC_BASE_URL has NO trailing /v1. Claude Code appends
# /v1/messages itself; including /v1 here would produce /v1/v1/messages
# and 404 every request.
#
# Exit codes from the python heredoc (interpreted by the bash side):
#   0 -> success
#   2 -> input file unreadable / not valid JSON (we treat as "start fresh")
write_claudecode_config() {
  local dest="$1"
  local user="${ARGO_ANYWHERE_USER:-${ANL_USERNAME:-}}"
  [ -n "$user" ] || die "write_claudecode_config: no username available (ARGO_ANYWHERE_USER unset)"
  command -v python3 >/dev/null 2>&1 \
    || die "write_claudecode_config: python3 is required to merge JSON safely."

  # Source = the file we're about to overwrite at $dest, IF it exists
  # AND is parseable JSON. handle_config_file calls us with $dest = a
  # tempfile when the user is choosing among k/b/d/m/a, so we need to
  # base our merge on the ORIGINAL target file (pre-tempfile), which
  # we read from the global _CLAUDECODE_SCOPE_PATH. When called for
  # the no-prior-file branch, the path won't exist and the heredoc
  # treats it as starting fresh.
  local orig="$_CLAUDECODE_SCOPE_PATH"

  # M8 fix (audit Phase 2d): distinguish "file absent" (legit fresh-write)
  # from "file present but unparseable" (refuse to overwrite). Pre-fix, a
  # malformed JSON file silently became `data = {}` and the writer wrote
  # a fresh file with only our env keys -- destroying the user's
  # broken-but-recoverable config. Now: if the file exists but parses
  # to non-dict or raises during json.load(), exit 2; bash side dies
  # with a clear recovery hint.
  #
  # Exit codes from the Python heredoc:
  #   0 -> success (file absent, or file present + parsed cleanly)
  #   2 -> file present but unparseable (refuse to merge; preserve user's file)
  local _py_rc=0
  python3 - "$orig" "$dest" "$user" "$PROXY_PORT" <<'PYEOF' || _py_rc=$?
import json, os, sys

orig_path, dest_path, user, port = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]

# Start from the existing file (if any), else an empty dict.
data = {}
if os.path.isfile(orig_path):
    try:
        with open(orig_path) as f:
            data = json.load(f) or {}
    except Exception:
        # M8 fix: malformed JSON -> refuse to merge. Caller dies with
        # a recovery hint pointing at the file + suggesting the user
        # fix it manually or pick [k]eep at the prompt.
        sys.exit(2)
    if not isinstance(data, dict):
        # Top-level JSON wasn't an object -- can't merge into a dict.
        # Same refuse-to-overwrite treatment as the malformed-JSON case.
        sys.exit(2)

env = data.get("env") or {}
if not isinstance(env, dict):
    env = {}

# Keys we own:
env["ANTHROPIC_BASE_URL"]  = f"http://localhost:{port}"
env["ANTHROPIC_AUTH_TOKEN"] = user

data["env"] = env

with open(dest_path, "w") as f:
    json.dump(data, f, indent=2)
    f.write("\n")
PYEOF
  if [ "$_py_rc" -eq 2 ]; then
    err "write_claudecode_config: existing config at ${orig} is present but"
    err "  cannot be parsed as JSON (or is not a top-level JSON object)."
    err "  Refusing to merge -- doing so would silently destroy your file."
    err ""
    err "Recovery options:"
    err "  1. Fix the JSON manually (\`python3 -m json.tool ${orig}\` will"
    err "     show you the parse error), then re-run."
    err "  2. Move the file aside (\`mv ${orig} ${orig}.broken.\$(date +%s)\`)"
    err "     and re-run; the writer will create a fresh file from scratch."
    err "  3. Pick [k]eep at the next config-handling prompt to leave the"
    err "     broken file in place (use this if you want to recover content"
    err "     from it before letting the script overwrite)."
    die "Refusing to overwrite a broken Claude Code config."
  elif [ "$_py_rc" -ne 0 ]; then
    die "write_claudecode_config: python3 heredoc exited with rc=${_py_rc} (unexpected)."
  fi
}

# setup_claudecode_cli_tool: ensure Claude Code is installed and its
# settings.json is up to date for the resolved (PROXY_PORT, ANL_USERNAME).
# Idempotent. Picks scope automatically (or honors --scope).
#
# B1a (Phase 4) reordering: claudecode_pick_scope() runs BEFORE
# ensure_claudecode_installed(). The scope decision doesn't depend on
# the binary being present; failing fast on scope-related issues (e.g.
# scope-switch prompt aborted by user, --scope value rejected by
# vocabulary validation) avoids the expensive curl|bash install when
# the run will not succeed anyway. The original ordering had install
# first; the H6 audit comment flagged the issue but the fix landed
# in Phase 2b kept the order. This reordering completes that fix.
setup_claudecode_cli_tool() {
  claudecode_pick_scope
  ensure_claudecode_installed
  handle_config_file "$_CLAUDECODE_SCOPE_PATH" \
    "Claude Code config (${_CLAUDECODE_SCOPE_NAME})" \
    write_claudecode_config
}

# ----------------------------------------------------------------------------
# aider config writer + installer + end-to-end client setup
# (subsection of 12; peer of setup_opencode_cli_tool / setup_claudecode_cli_tool)
#
# Phase 5a. aider is the low-risk multi-tool addition: it rides the same
# OpenAI-Chat-compatible surface (/v1/chat/completions) that OpenCode
# already uses, so no new argo-proxy behaviour is required. The config is
# YAML (~/.aider.conf.yml). We own three keys (openai-api-base,
# openai-api-key, model) and preserve every other user-set key via a
# PyYAML round-trip when python3 + PyYAML are available; when they are
# not, we fall back to a from-scratch write (documented below).
#
# Scope model mirrors opencode: global (~/.aider.conf.yml) vs project
# (<git-root>/.aider.conf.yml, cwd fallback). No OAuth-state concern
# (aider has no personal-subscription login to shadow), so the per-tool
# default is global. Conflict detection reuses the opencode shape
# (A.1 existing-content; B.2 cwd-not-a-project for explicit --scope
# project).
# ----------------------------------------------------------------------------

# aider_scope_values: D-018 per-tool scope vocabulary. aider supports
# both global (~/.aider.conf.yml) and project
# (<git-root>/.aider.conf.yml, cwd fallback) scopes.
aider_scope_values() {
  printf 'global project'
}

_AIDER_SCOPE_PATH=""
_AIDER_SCOPE_NAME=""

# aider_pick_scope: D-017 scope resolution + conflict detection for aider.
# Structurally identical to opencode_pick_scope (aider has no OAuth
# state), so the per-tool default is global; conflict detection still
# runs (A.1 existing-content-collision; B.2 cwd-not-a-project for
# explicit --scope project). Sets _AIDER_SCOPE_PATH / _AIDER_SCOPE_NAME
# for write_aider_config + the dispatcher to consume. DO NOT capture via
# $() -- may prompt the user.
aider_pick_scope() {
  local _intended_scope=""
  local _scope_source=""
  if [ -n "${_SCOPE_OVERRIDE:-}" ]; then
    _intended_scope="$_SCOPE_OVERRIDE"
    _scope_source="--scope ${_intended_scope}"
  elif [ -n "${ARGO_ANYWHERE_SCOPE:-}" ]; then
    _intended_scope="$ARGO_ANYWHERE_SCOPE"
    _scope_source="ARGO_ANYWHERE_SCOPE env"
  fi

  if [ -n "$_intended_scope" ]; then
    _validate_scope_for_tool aider "$_intended_scope"
  else
    # Per-tool auto-default: global. (No OAuth-state concern.)
    _intended_scope="global"
    _scope_source="auto (aider default; no OAuth-state concern)"
  fi

  case "$_intended_scope" in
    global)
      _AIDER_SCOPE_PATH="$AIDER_GLOBAL_CONFIG"
      _AIDER_SCOPE_NAME="global (${AIDER_GLOBAL_CONFIG})"
      ;;
    project)
      local _proj_root; _proj_root="$(_git_root_or_cwd)"
      _AIDER_SCOPE_PATH="${_proj_root}/${AIDER_PROJECT_CONFIG_BASENAME}"
      _AIDER_SCOPE_NAME="project (${_AIDER_SCOPE_PATH})"
      ;;
    *)
      die "aider_pick_scope: internal error -- intended scope '${_intended_scope}' not in vocabulary (aider_scope_values returns: $(aider_scope_values))."
      ;;
  esac

  log "aider scope: ${_intended_scope} (${_scope_source})."
  if [ "$_intended_scope" = "project" ]; then
    log "  Config will land at ${_AIDER_SCOPE_PATH} and apply only when"
    log "  'aider' is invoked from within this project tree."
  else
    log "  Config will land at ${_AIDER_SCOPE_PATH} and apply when"
    log "  'aider' is invoked from any directory."
  fi

  _aider_check_conflicts "$_intended_scope"
}

# _aider_check_conflicts: per-scope conflict detection + scope-switch
# prompt. Mirrors _opencode_check_conflicts. Mutates _AIDER_SCOPE_PATH /
# _AIDER_SCOPE_NAME if the user chooses to switch.
_aider_check_conflicts() {
  local intended="$1"
  local conflict_desc=""
  local other_scope=""
  if [ "$intended" = "global" ]; then
    other_scope="project"
    if [ -f "$AIDER_GLOBAL_CONFIG" ] && [ -s "$AIDER_GLOBAL_CONFIG" ]; then
      conflict_desc="${AIDER_GLOBAL_CONFIG} already exists and is non-empty. You can keep global scope (a later prompt will ask how to handle the existing file), or switch to project scope now to leave your global file untouched (writes <git-root>/.aider.conf.yml or cwd/.aider.conf.yml instead)."
    fi
  elif [ "$intended" = "project" ]; then
    other_scope="global"
    local _is_project=0
    if command -v git >/dev/null 2>&1 && git rev-parse --show-toplevel >/dev/null 2>&1; then
      _is_project=1
    elif [ -f "package.json" ] || [ -f "pyproject.toml" ] || [ -f "Cargo.toml" ] || [ -f "go.mod" ]; then
      _is_project=1
    elif [ "$(pwd)" = "$HOME" ]; then
      _is_project=1
    fi
    if [ "$_is_project" = 0 ]; then
      conflict_desc="--scope project will write $(pwd)/${AIDER_PROJECT_CONFIG_BASENAME}, but $(pwd) doesn't look like a project directory (no .git ancestor, no common project manifests). Most users in this situation want --scope global so 'aider' works from any directory."
    fi
  fi

  if [ -n "$conflict_desc" ]; then
    local _ssc_choice
    _ssc_choice="$(prompt_scope_switch "$conflict_desc" "$intended" "$other_scope")"
    case "$_ssc_choice" in
      keep)
        log "  Proceeding with ${intended} scope despite the conflict (user's choice)."
        ;;
      switch)
        case "$other_scope" in
          project)
            local _proj_root; _proj_root="$(_git_root_or_cwd)"
            _AIDER_SCOPE_PATH="${_proj_root}/${AIDER_PROJECT_CONFIG_BASENAME}"
            _AIDER_SCOPE_NAME="project (${_AIDER_SCOPE_PATH})"
            ;;
          global)
            _AIDER_SCOPE_PATH="$AIDER_GLOBAL_CONFIG"
            _AIDER_SCOPE_NAME="global (${AIDER_GLOBAL_CONFIG})"
            ;;
        esac
        log "  Switched to ${other_scope} scope; will write ${_AIDER_SCOPE_PATH}."
        ;;
    esac
  fi
}

# write_aider_config <dest>: produce an aider YAML config that points at
# the local tunnel. We own three keys:
#   openai-api-base : http://localhost:<PORT>/v1   (OpenAI-Chat surface)
#   openai-api-key  : <ANL username>               (argo-proxy bearer token)
#   model           : openai/<default model id>    (routes via the openai provider)
# Everything else in an existing ~/.aider.conf.yml is preserved.
#
# Merge strategy (mirrors write_claudecode_config's fail-loud discipline,
# adapted for YAML):
#   * python3 + PyYAML available -> round-trip the existing file,
#     overwrite only our three keys, preserve all others. Refuse to
#     merge (exit 2) if the existing file is present but unparseable, so
#     we never silently destroy a user's broken-but-recoverable config
#     (D-016 / audit M8 discipline).
#   * python3 present, PyYAML absent -> the laptop side does NOT ship
#     PyYAML by default (per PLAN.md scope: PyYAML is a compute-node-only
#     dep). Fall back to a from-scratch write of just our three keys, but
#     first back up any existing file so nothing is lost (exit 3 signals
#     the bash side to emit a warning).
#   * python3 absent -> from-scratch heredoc write of our three keys
#     (aider's YAML is simple enough that a hand write is safe); warn.
#
# Reads the original file from _AIDER_SCOPE_PATH (handle_config_file
# passes $dest as a tempfile during the k/b/d/a prompt, so the merge base
# is the real target, not the tempfile) -- same pattern as
# write_claudecode_config.
write_aider_config() {
  local dest="$1"
  local user="${ARGO_ANYWHERE_USER:-${ANL_USERNAME:-}}"
  [ -n "$user" ] || die "write_aider_config: no username available (ARGO_ANYWHERE_USER unset)"
  # L6-class fail-loud: refuse to write a config with an empty port that
  # would interpolate to 'http://localhost:/v1' and silently not connect.
  [ -n "${PROXY_PORT:-}" ] || die "write_aider_config: PROXY_PORT is empty (resolve_port not called?). Refusing to write a config with openai-api-base 'http://localhost:/v1' that would silently fail to connect."

  local orig="$_AIDER_SCOPE_PATH"
  # Default model. aider routes an OpenAI-compatible provider via the
  # 'openai/<id>' prefix; the <id> must be EXACTLY what argo-proxy's
  # /v1/models advertises, which is the 'argo:'-prefixed id (e.g.
  # 'argo:gpt-4o', 'argo:claude-opus-4.8'). A bare 'gpt-4o' (without the
  # 'argo:' prefix) does NOT resolve at ANL -- Phase 5a live-test finding
  # (2026-07-08).
  #
  # Default is gpt-4o: it is a non-reasoning model that works out of the
  # box (accepts temperature; no reasoning-effort quirks). The earlier
  # default gpt-5-nano was WRONG -- it returned empty responses even with
  # temperature disabled (a gpt-5-*-nano reasoning quirk on the ANL
  # gateway; the full gpt-5 works, but -nano does not). Override with
  # AIDER_DEFAULT_MODEL or change 'model:' afterward (e.g.
  # openai/argo:claude-opus-4.8, which works with the temperature-off
  # model-settings this writer also emits).
  local model="${AIDER_DEFAULT_MODEL:-openai/argo:gpt-4o}"

  # The sibling model-settings file. aider needs use_temperature:false
  # for reasoning / opus-4.7+ / gpt-5 / o-series / gemini-2.5+ models:
  # they REJECT the 'temperature' param that aider (via LiteLLM) sends by
  # default, and argo-proxy's upstream returns an EMPTY stream rather than
  # an error (Phase 5a live-test finding 2026-07-08; this is the aider-
  # facing surfacing of the audit's UP-10 G3). We disable temperature for
  # ALL served argo: models -- harmless for models that would accept it
  # (aider just omits the param), and future-proof. Written next to the
  # config so it travels with the chosen scope.
  local settings_dir; settings_dir="$(dirname "$orig")"
  local settings_file="${settings_dir}/.aider.model.settings.yml"

  if command -v python3 >/dev/null 2>&1; then
    local _py_rc=0
    python3 - "$orig" "$dest" "$user" "$PROXY_PORT" "$model" "$settings_file" <<'PYEOF' || _py_rc=$?
import os, sys
orig_path, dest_path, user, port, model, settings_file = sys.argv[1:7]

try:
    import yaml  # PyYAML
except Exception:
    # PyYAML not available on this laptop. Signal the bash side to do a
    # backup + from-scratch write.
    sys.exit(3)

data = {}
if os.path.isfile(orig_path):
    try:
        with open(orig_path) as f:
            loaded = yaml.safe_load(f)
        data = loaded if loaded is not None else {}
    except Exception:
        # Present but unparseable -> refuse to merge (preserve user file).
        sys.exit(2)
    if not isinstance(data, dict):
        sys.exit(2)

# Keys we own:
data["openai-api-base"] = f"http://localhost:{port}/v1"
data["openai-api-key"] = user
data["model"] = model
data["model-settings-file"] = settings_file

with open(dest_path, "w") as f:
    yaml.safe_dump(data, f, default_flow_style=False, sort_keys=False)

# Write the sibling model-settings file: use_temperature:false for the
# argo: models that need it. This is our file (we own it entirely), so we
# rewrite it wholesale each run rather than merging.
argo_models = [
    "gpt-4o", "gpt-4.1", "gpt-4.1-mini", "gpt-4.1-nano",
    "gpt-5", "gpt-5-mini", "gpt-5-nano",
    "gpt-5.1", "gpt-5.2", "gpt-5.4", "gpt-5.4-mini", "gpt-5.4-nano", "gpt-5.5",
    "gpt-o1", "gpt-o3", "gpt-o3-mini", "gpt-o4-mini",
    "o1", "o3", "o3-mini", "o4-mini",
    "claude-opus-4.1", "claude-opus-4.5", "claude-opus-4.6",
    "claude-opus-4.7", "claude-opus-4.8",
    "claude-4.1-opus", "claude-4.5-opus", "claude-4.6-opus",
    "claude-4.7-opus", "claude-4.8-opus",
    "claude-sonnet-4.5", "claude-sonnet-4.6",
    "claude-4.5-sonnet", "claude-4.6-sonnet",
    "claude-haiku-4.5", "claude-4.5-haiku",
    "gemini-2.5-flash", "gemini-2.5-pro",
    "gemini-3.1-flash-lite", "gemini-3.5-flash",
]
settings = [
    {"name": f"openai/argo:{m}", "use_temperature": False, "streaming": True}
    for m in argo_models
]
with open(settings_file, "w") as f:
    f.write("# Written by argo-anywhere. Disables the 'temperature' param for\n")
    f.write("# argo-served models -- reasoning / opus-4.7+ / gpt-5 / o-series /\n")
    f.write("# gemini models REJECT it and argo-proxy returns an empty stream.\n")
    f.write("# Safe for models that accept temperature (the param is just omitted).\n")
    yaml.safe_dump(settings, f, default_flow_style=False, sort_keys=False)
PYEOF
    case "$_py_rc" in
      0) return 0 ;;
      2)
        err "write_aider_config: existing config at ${orig} is present but"
        err "  cannot be parsed as YAML (or is not a top-level mapping)."
        err "  Refusing to merge -- doing so would silently destroy your file."
        err ""
        err "Recovery options:"
        err "  1. Fix the YAML manually, then re-run."
        err "  2. Move the file aside (\`mv ${orig} ${orig}.broken.\$(date +%s)\`)"
        err "     and re-run; the writer will create a fresh file from scratch."
        err "  3. Pick [k]eep at the next config-handling prompt to leave the"
        err "     broken file in place."
        die "Refusing to overwrite a broken aider config."
        ;;
      3)
        warn "write_aider_config: python3 has no PyYAML; cannot safely merge"
        warn "  an existing aider config. Falling back to a from-scratch write"
        warn "  of only the keys we own (openai-api-base / -key / model /"
        warn "  model-settings-file). Any other keys in an existing ${orig}"
        warn "  will NOT be carried over."
        _aider_write_config_scratch "$dest" "$user" "$PROXY_PORT" "$model" "$orig" "$settings_file"
        return 0
        ;;
      *)
        die "write_aider_config: python3 heredoc exited with rc=${_py_rc} (unexpected)."
        ;;
    esac
  else
    warn "write_aider_config: python3 not found; writing a from-scratch aider"
    warn "  config with only the keys we own. Any other keys in an existing"
    warn "  ${orig} will NOT be carried over."
    _aider_write_config_scratch "$dest" "$user" "$PROXY_PORT" "$model" "$orig" "$settings_file"
    return 0
  fi
}

# _aider_write_config_scratch <dest> <user> <port> <model> <orig> <settings_file>:
# from-scratch write of the owned keys + the sibling model-settings file.
# Backs up an existing original first so a no-PyYAML / no-python3 fallback
# never destroys a user's file silently.
_aider_write_config_scratch() {
  local dest="$1" user="$2" port="$3" model="$4" orig="$5" settings_file="$6"
  if [ -f "$orig" ] && [ -s "$orig" ]; then
    local bak="${orig}.bak.$(date +%Y%m%d-%H%M%S).$$"
    cp -p "$orig" "$bak" && warn "  Backed up existing config to ${bak}."
  fi
  cat > "$dest" <<EOF
# Written by argo-anywhere. Points aider at the local argo-proxy tunnel.
# Change 'model:' to any model argo-proxy serves (e.g. openai/argo:claude-opus-4.8).
openai-api-base: http://localhost:${port}/v1
openai-api-key: ${user}
model: ${model}
model-settings-file: ${settings_file}
EOF
  # The sibling model-settings file: disable temperature for argo: models
  # that reject it (reasoning / opus-4.7+ / gpt-5 / o-series / gemini).
  # We own this file entirely; rewrite wholesale. Keep the list in sync
  # with the PyYAML path above.
  local _m
  {
    echo "# Written by argo-anywhere. Disables 'temperature' for argo-served"
    echo "# models that reject it (argo-proxy returns an empty stream otherwise)."
    for _m in \
        gpt-4o gpt-4.1 gpt-4.1-mini gpt-4.1-nano \
        gpt-5 gpt-5-mini gpt-5-nano gpt-5.1 gpt-5.2 gpt-5.4 gpt-5.4-mini gpt-5.4-nano gpt-5.5 \
        gpt-o1 gpt-o3 gpt-o3-mini gpt-o4-mini o1 o3 o3-mini o4-mini \
        claude-opus-4.1 claude-opus-4.5 claude-opus-4.6 claude-opus-4.7 claude-opus-4.8 \
        claude-4.1-opus claude-4.5-opus claude-4.6-opus claude-4.7-opus claude-4.8-opus \
        claude-sonnet-4.5 claude-sonnet-4.6 claude-4.5-sonnet claude-4.6-sonnet \
        claude-haiku-4.5 claude-4.5-haiku \
        gemini-2.5-flash gemini-2.5-pro gemini-3.1-flash-lite gemini-3.5-flash; do
      echo "- name: openai/argo:${_m}"
      echo "  use_temperature: false"
      echo "  streaming: true"
    done
  } > "$settings_file"
}

# _aider_on_path: return 0 if `aider` is runnable, prepending any
# well-known install location to PATH for the rest of this invocation if
# the installer's rc-file PATH edit hasn't reached our shell yet. Used to
# VERIFY each install method actually produced a working binary (Phase 5a
# live-test finding: a method that fails must fall through to the next,
# not just warn-and-give-up).
_aider_on_path() {
  if command -v aider >/dev/null 2>&1; then
    return 0
  fi
  local _candidate
  for _candidate in \
      "${HOME}/.local/bin/aider" \
      "${HOME}/.local/share/uv/tools/aider-chat/bin/aider" \
      "${HOME}/.aider/bin/aider"; do
    if [ -x "$_candidate" ]; then
      log "  Found aider at ${_candidate}; prepending its dir to PATH for this run."
      PATH="$(dirname "$_candidate"):${PATH}"
      export PATH
      return 0
    fi
  done
  return 1
}

# ensure_aider_installed: detect or install the `aider` binary. aider is
# a Python application whose pinned deps (e.g. numpy) frequently have no
# wheels for the newest CPython, so a bare `pipx install` / `uv tool
# install` under the user's system Python can fail to BUILD (observed on
# the Phase 5a live test: Python 3.13/3.14 -> numpy 1.24.3 source build
# fails). Upstream's #1 recommendation is the standalone installer, which
# bundles (or fetches) its own Python 3.12; the uv one-liner does the
# same. So we prefer the SELF-CONTAINED methods first and only fall back
# to the user's-Python methods, and we VERIFY a working binary after each
# attempt, falling through to the next method on failure.
#
# Method order (most-robust first):
#   1. Standalone installer (curl | sh) -- bundles/fetches Python 3.12.
#   2. uv (if present) with explicit --python python3.12 --with pip.
#   3. pipx (if present) -- last resort; subject to the user's default
#      Python, which is exactly what breaks on 3.13/3.14.
ensure_aider_installed() {
  if _aider_on_path; then
    ok "aider already installed: $(command -v aider)"
    return
  fi
  log "Installing aider..."

  # Method 1: upstream standalone installer (self-contained Python 3.12).
  log "  Trying the upstream standalone installer (bundles its own Python 3.12)..."
  if curl -fsSL https://aider.chat/install.sh | sh; then
    if _aider_on_path; then
      ok "aider installed via the standalone installer: $(command -v aider)"
      manifest_record_binary aider "$(command -v aider)" "standalone"
      return
    fi
    warn "  Standalone installer ran but no aider binary appeared; trying next method."
  else
    warn "  Standalone installer failed; trying next method."
  fi

  # Method 2: uv, pinned to Python 3.12 (matches upstream's uv recipe).
  if command -v uv >/dev/null 2>&1; then
    log "  Trying 'uv tool install --force --python python3.12 --with pip aider-chat@latest'..."
    if uv tool install --force --python python3.12 --with pip aider-chat@latest; then
      if _aider_on_path; then
        ok "aider installed via uv: $(command -v aider)"
        manifest_record_binary aider "$(command -v aider)" "uv"
        return
      fi
      warn "  uv install ran but no aider binary appeared; trying next method."
    else
      warn "  uv install failed; trying next method."
    fi
  fi

  # Method 3: pipx (last resort; subject to the user's default Python,
  # which is what breaks on CPython versions lacking numpy wheels).
  if command -v pipx >/dev/null 2>&1; then
    log "  Trying 'pipx install aider-chat' (last resort; uses your default Python)..."
    if pipx install aider-chat; then
      if _aider_on_path; then
        ok "aider installed via pipx: $(command -v aider)"
        manifest_record_binary aider "$(command -v aider)" "pipx"
        return
      fi
      warn "  pipx install ran but no aider binary appeared."
    else
      warn "  pipx install failed."
    fi
  fi

  err "aider could not be installed by any available method:"
  err "    1. standalone installer (curl -fsSL https://aider.chat/install.sh | sh)"
  err "    2. uv tool install --python python3.12 --with pip aider-chat@latest"
  err "    3. pipx install aider-chat"
  err "  A common cause is a pinned dependency (e.g. numpy) failing to BUILD"
  err "  under a very new CPython. The standalone installer normally avoids"
  err "  this by bundling Python 3.12; if it failed, check network access to"
  err "  aider.chat, then install aider manually per https://aider.chat/docs/install.html"
  err "  and re-run. If you already installed it, open a new shell so the"
  err "  binary is on PATH (or 'source ~/.bashrc' / 'source ~/.zshrc')."
  die "Cannot continue without a runnable aider binary."
}

# setup_aider_cli_tool: ensure aider is installed and its config points at
# the resolved (PROXY_PORT, ANL_USERNAME). Idempotent. Picks scope first
# (fail fast on scope conflicts before the install), same ordering as the
# opencode / claudecode setup functions.
setup_aider_cli_tool() {
  aider_pick_scope
  ensure_aider_installed
  handle_config_file "$_AIDER_SCOPE_PATH" \
    "aider config (${_AIDER_SCOPE_NAME})" \
    write_aider_config
}

# ============================================================================
# SECTION: 13. SSH PREFLIGHT (verify reachability + open MFA mux master)
# ============================================================================
# Two callers, two contracts:
#
#   ssh_preflight <user>           -- legacy "before we know the node" form.
#                                     Under MFA mode this is a no-op (see below).
#                                     Under --no-mfa it runs a BatchMode test
#                                     against the jump host (or first node
#                                     under --no-jump) to fail fast on missing
#                                     SSH keys.
#
#   ssh_preflight <user> <node>    -- "we already picked the node" form. Used
#                                     by mode_client AFTER pick_node so that
#                                     under MFA we can open the mux master
#                                     against the node (which IS shell-capable),
#                                     not the jump host.
#
# Why we don't open the master against the jump host (ANL_JUMP):
#   logins.cels.anl.gov is a "jump-only" host -- its login shell rejects all
#   command execution with "This account is currently not available", even
#   for valid users with valid Duo. So `ssh aattia@logins.cels.anl.gov true`
#   exits non-zero, and ssh_mux_open fails. The jump host is meant to be used
#   ONLY as a ProxyJump target. ControlMaster therefore must be opened against
#   the actual destination (a compute node), with the jump host on the path.
#   OpenSSH multiplexes per (user,host,port) destination, so a master to
#   compute-XX covers every later ssh/scp to that same compute-XX through the
#   same ProxyJump.
ssh_preflight() {
  local user="$1" node="${2:-}"
  # Pick what to actually test, based on whether we route through a jump.
  local target
  if [ -n "$node" ]; then
    # Caller already picked a node; that's our preflight target regardless
    # of jump-host policy (mux master must be opened against the node).
    target="$node"
  elif [ "${ARGO_ANYWHERE_NO_JUMP:-0}" = 1 ]; then
    if [ -n "${ARGO_ANYWHERE_NODE:-}" ]; then
      target="$ARGO_ANYWHERE_NODE"
    elif [ "${#ANL_NODES[@]}" -gt 0 ]; then
      target="${ANL_NODES[0]}"
    else
      die "ARGO_ANYWHERE_NO_JUMP is set but no node to preflight. Pass --node HOST or fill ANL_NODES."
    fi
  else
    target="$ANL_JUMP"
  fi

  if mfa_enabled; then
    # Open the multiplex master against the chosen target. Under MFA we
    # require <node> to be passed; if the caller passed only <user>, we'd
    # open against ANL_JUMP, which always fails (see big comment above).
    # Compatibility: if no node is known yet, defer -- the next real SSH
    # (pick_node's reachability check, or bootstrap scp) opens the master
    # implicitly via ControlMaster=auto.
    if [ -z "$node" ] && [ "$target" = "$ANL_JUMP" ]; then
      log "Deferring SSH master setup until a node is picked"
      log "  (jump host ${ANL_JUMP} doesn't allow shell access; master"
      log "   will be opened against the chosen compute node instead)."
      return 0
    fi
    ssh_mux_open "$user" "$target"
    return
  fi

  log "Testing SSH access to ${user}@${target} (BatchMode, 5s timeout)..."
  # Tracked by the SSH attempt tracker so a wrong --user / missing key
  # doesn't get retried into a CSPO IP block. See ssh_attempt_pre/ok/fail.
  if ! ssh_attempt_pre; then
    die "Aborted: SSH preflight (SSH failure lock active; recovery above)."
  fi
  # H1 fix (audit): include $(ssh_args "$user" "$target") so the BatchMode
  # preflight uses the same routing as the actual subsequent SSHs --
  # specifically, ProxyJump via $ANL_JUMP when --no-mfa --node compute-X is
  # used from off-network. Without this, the preflight tries a direct
  # connect to compute-X (always fails off-network), increments the
  # failure counter, and a third invocation triggers the SSH lock.
  # ssh_args returns the empty string for target == ANL_JUMP, so the
  # jump-loop guard (preflight against the jump host itself) still works.
  # shellcheck disable=SC2046
  if ssh -o BatchMode=yes -o ConnectTimeout=5 -o StrictHostKeyChecking=accept-new \
       $(ssh_args "$user" "$target") "${user}@${target}" true 2>/dev/null; then
    ssh_attempt_ok
    ok "Passwordless SSH to ${target} works."
    return
  fi
  ssh_attempt_fail
  err "Cannot reach ${user}@${target} without a password."
  cat >&2 <<EOF

  Set up SSH key-based auth before continuing:
    1. ssh-keygen -t ed25519        # if you have no key
    2. ssh-copy-id ${user}@${target}
    3. ssh ${user}@${target} true   # confirm it works without a password

EOF
  if [ "${ARGO_ANYWHERE_NO_JUMP:-0}" = 1 ]; then
    cat >&2 <<EOF
  --no-jump is on, so the script tried ${target} directly. If you actually
  do need a jump host, drop --no-jump (and ARGO_ANYWHERE_NO_JUMP).

EOF
  else
    cat >&2 <<EOF
  If you need ANL VPN to reach ${target}, connect to the VPN first.
  If you can already SSH to compute nodes directly without a jump host
  (e.g. you're on the ANL network), try '--no-jump'.
  If your account uses Duo MFA, BatchMode tests will always fail; this script
  defaults to MFA mode (uses SSH multiplexing to ask Duo only once). If you
  reached this error with --no-mfa, drop that flag and try again.

EOF
  fi
  die "SSH preflight failed."
}

# ============================================================================
# SECTION: 14. NODE PICKER (--node, --probe-nodes, fallback to ANL_NODES)
# ============================================================================

# write_node_cache <node>: persist the given node name to NODE_CACHE.
# Called from the three "successful tunnel state" sites in mode_client,
# mode_tunnel, and _client_common_setup's on-node short-circuit. The
# cache reflects "last successfully USED node", not "last picked node"
# (P3 fix audit). Returns 0 even on permission failure (best-effort
# persistence; the cache is a UX nicety, not load-bearing).
write_node_cache() {
  local node="$1"
  [ -n "$node" ] || return 0
  mkdir -p "$STATE_DIR" 2>/dev/null || true
  printf '%s\n' "$node" > "$NODE_CACHE" 2>/dev/null || true
}

pick_node() {
  local user="$1"

  # --node / ARGO_ANYWHERE_NODE: skip the picker entirely. We still verify
  # reachability so we fail fast with a clear message rather than later in
  # the SSH bootstrap.
  if [ -n "${ARGO_ANYWHERE_NODE:-}" ]; then
    local req="$ARGO_ANYWHERE_NODE"
    local in_list=0 n
    for n in "${ANL_NODES[@]:-}"; do
      [ "$n" = "$req" ] && in_list=1 && break
    done
    [ "$in_list" -eq 1 ] || warn "Requested node '${req}' is not in ANL_NODES (proceeding anyway)."

     log "Verifying reachability of '${req}' $(jump_descr)..."
    if ssh_reachable "$user" "$req"; then
      ok "  reachable: ${req}"
      # P3 fix (audit): cache write deferred to AFTER successful tunnel
      # establishment (in mode_client / mode_tunnel / on-node short-circuit
      # in _client_common_setup). pick_node returns the picked node; the
      # cache reflects "last successfully USED node", not "last picked".
      # Without this, the cache lies whenever a pick fails to reach a
      # working tunnel, and the G1 same-port-different-node check
      # (lines ~2811-2829) compares two values that always agree.
      echo "$req"
      return
    else
      die "Requested node '${req}' is not reachable $(jump_descr) as ${user}. Drop --node to use the picker."
    fi
  fi

  [ "${#ANL_NODES[@]}" -gt 0 ] || die "ANL_NODES is empty. Edit the script header to add nodes."

  # By default we DO NOT probe every node -- under MFA, each unreachable node
  # would either time out or trigger Duo. The user picks from the static list
  # and the actual SSH connect later either works or fails loudly.
  # --probe-nodes opts back into the old behavior.
  local working=() node default cached=""
  if [ "${PROBE_NODES:-0}" = 1 ]; then
    log "Probing ${#ANL_NODES[@]} node(s) $(jump_descr) (--probe-nodes)..."
    for node in "${ANL_NODES[@]}"; do
      # H3 fix (audit): explicit pre-iteration gate. ssh_reachable does
      # its own ssh_attempt_pre check internally and returns false on
      # lock -- but that's indistinguishable from a real reachability
      # failure, so the loop would silently mark every remaining node
      # as "unreachable" rather than telling the user the SSH lock
      # fired. Front-loading the check lets us die with the proper
      # recovery message before consuming an attempt the lock would
      # have refused anyway.
      if ! ssh_attempt_pre; then
        die "Aborted: --probe-nodes (SSH failure lock active; recovery above)."
      fi
      # ssh_attempt_pre succeeded above; ssh_reachable will call it
      # again internally (idempotent for the not-yet-locked case) and
      # then ssh_attempt_ok or ssh_attempt_fail to update the counter.
      if ssh_reachable "$user" "$node"; then
        ok "  reachable: ${node}"
        working+=("$node")
      else
        warn "  unreachable: ${node}"
        # Defense-in-depth: the H3 pre-iteration gate above catches the
        # already-locked case; this catches the case where the tracker
        # JUST locked as a result of this iteration's ssh_attempt_fail.
        if [ "${_SSH_LOCKED:-0}" = 1 ]; then
          die "Aborted mid-probe: SSH lock just fired (recovery above)."
        fi
      fi
    done
    [ "${#working[@]}" -gt 0 ] || die "No ANL_NODES are reachable. Check the list or your access."
  else
    # Skip probing; show all configured nodes.
    working=("${ANL_NODES[@]}")
  fi

  # Default selection precedence:
  #   1. If we're ON a compute node and any entry in ANL_NODES resolves
  #      to this host (i.e. picking it would trigger the on-node short-
  #      circuit), default to that entry. Smoothest UX for the user
  #      who's logged into a node and just wants to use the local
  #      argo-proxy.
  #   2. Else, the cached node (if it's still in the working list).
  #   3. Else, the first entry.
  default="${working[0]}"
  if [ "$(on_anl_compute_node)" = "yes" ]; then
    for node in "${working[@]}"; do
      if host_is_target "$node"; then
        default="$node"
        break
      fi
    done
  fi
  if [ "$default" = "${working[0]}" ] && [ -f "$NODE_CACHE" ]; then
    # No on-node match (or none required); fall back to cache.
    cached="$(cat "$NODE_CACHE")"
    for node in "${working[@]}"; do
      [ "$node" = "$cached" ] && default="$cached" && break
    done
  fi

  cat >&2 <<EOF

  Compute nodes:
EOF
  local i=1
  for node in "${working[@]}"; do
    local marker=""
    [ "$node" = "$default" ] && marker="  ${C_DIM}(default)${C_OFF}"
    printf '    %d) %s%s\n' "$i" "$node" "$marker" >&2
    i=$((i+1))
  done
  printf '    %s(or type a hostname not in this list to use it directly)%s\n' \
    "$C_DIM" "$C_OFF" >&2
  if [ "${PROBE_NODES:-0}" != 1 ]; then
    printf '    %s(reachability NOT probed; pass --probe-nodes to test each first)%s\n' \
      "$C_DIM" "$C_OFF" >&2
  fi

  local picked
  # H2 fix (audit): per-call retry limit on the interactive picker loop.
  # A confused user typing bad hostnames burns one CSPO attempt per
  # ssh_reachable miss; without a cap, they can rack up several attempts
  # before the global SSH lock fires. Cap is 5 attempts (NOT counting
  # in-range numeric picks, default Enter, or numeric-out-of-range
  # parser warnings -- only attempts that would consume an SSH attempt).
  # On reaching the cap, refuse to continue and direct the user to
  # --node / --probe-nodes / re-running with a fresh terminal.
  local attempts=0
  local _PICK_NODE_MAX=5
  while :; do
    local choice
    choice="$(ask "Pick a node [1-${#working[@]}, hostname, or Enter for default]:" "")"
    if [ -z "$choice" ]; then
      # Default
      picked="$default"; break
    elif [[ "$choice" =~ ^[0-9]+$ ]]; then
      # Numeric pick: must be in range. NOT counted toward the H2 cap;
      # this branch never opens an SSH connection.
      if [ "$choice" -ge 1 ] && [ "$choice" -le "${#working[@]}" ]; then
        picked="${working[$((choice-1))]}"; break
      else
        warn "Number out of range; pick 1-${#working[@]} or type a hostname."
        continue
      fi
    elif [[ "$choice" =~ ^[a-zA-Z0-9][a-zA-Z0-9._-]*$ ]]; then
      # Looks like a hostname. Same handling as --node: warn if not in
      # ANL_NODES, verify reachability, use it. Equivalent to the
      # --node-flag path so the user gets the same UX whether they
      # provided the host on the CLI or typed it interactively.
      attempts=$((attempts+1))
      if [ "$attempts" -gt "$_PICK_NODE_MAX" ]; then
        die "Too many failed picks in this picker (${_PICK_NODE_MAX}). Re-run with --node <host> if you know the hostname, or --probe-nodes to see which nodes are currently reachable."
      fi
      local in_list=0 n
      for n in "${ANL_NODES[@]:-}"; do
        [ "$n" = "$choice" ] && in_list=1 && break
      done
      [ "$in_list" -eq 1 ] || warn "Typed node '${choice}' is not in ANL_NODES (proceeding anyway)."
      log "Verifying reachability of '${choice}' $(jump_descr)..."
      if ssh_reachable "$user" "$choice"; then
        ok "  reachable: ${choice}"
        picked="$choice"; break
      else
        # Bail out if the SSH attempt tracker has locked. Without this,
        # the user could keep typing forever -- ssh_reachable returns
        # failure immediately (without trying ssh) once locked, so the
        # "pick again" loop would never make progress.
        if [ "${_SSH_LOCKED:-0}" = 1 ]; then
          die "Aborted at node-pick: SSH lock just fired (recovery above)."
        fi
        local _remaining=$((_PICK_NODE_MAX - attempts))
        warn "Could not reach '${choice}' $(jump_descr) as ${user}; pick again (${_remaining} attempt(s) left)."
        continue
      fi
    else
      # Parse error (no SSH attempted) -- not counted toward the H2 cap.
      warn "Invalid choice. Type a number (1-${#working[@]}), a hostname, or hit Enter."
    fi
  done

  # P3 fix (audit): cache write deferred to AFTER successful tunnel
  # establishment. See comment in the --node branch above for rationale.
  echo "$picked"
}

# ============================================================================
# SECTION: 15. REMOTE BOOTSTRAP (scp self to node, exec as 'server' over ssh)
# ============================================================================
remote_bootstrap() {
  local user="$1" node="$2"
  local self
  # Locate this script. If invoked via `bash -s` from a curl, we won't have a
  # path; in that case, dump $0 reading isn't enough -- bail out clearly.
  self="${BASH_SOURCE[0]}"
  if [ ! -f "$self" ]; then
    die "Cannot locate this script on disk (BASH_SOURCE=${self}). Save it to a file and re-run."
  fi

  log "Copying script to ${user}@${node}:~/${REMOTE_SELF}..."
  # scp accepts the same -o options as ssh, including ControlPath/Master and
  # ProxyJump. Build the option list the same way ssh calls do.
  local scp_opts=()
  scp_opts+=( -q -o StrictHostKeyChecking=accept-new )
  if mfa_enabled; then
    mkdir -p "$SSH_MUX_DIR"; chmod 700 "$SSH_MUX_DIR" 2>/dev/null || true
    local persist="${ARGO_ANYWHERE_CONTROL_PERSIST:-$SSH_MUX_PERSIST_DEFAULT}"
    # Same %r-%h-%p literal tokens as ssh_mux_args (see comment there for why
    # we don't use %C here either). MUST match exactly so scp and ssh share
    # the same master socket for the same destination.
    scp_opts+=( -o ControlMaster=auto
                -o "ControlPath=${SSH_MUX_DIR}/argo-anywhere-%r-%h-%p"
                -o "ControlPersist=${persist}" )
  fi
  if [ "${ARGO_ANYWHERE_NO_JUMP:-0}" != 1 ]; then
    scp_opts+=( -o "ProxyJump=${user}@${ANL_JUMP}" )
  fi
  # In --no-mfa mode scp opens a new auth session; track it so a broken key
  # doesn't silently accumulate CSPO failures. In MFA mode the mux master
  # absorbs the connection, so ssh_attempt_ok/fail is still correct (a mux
  # failure IS a real failure worth counting).
  ssh_attempt_pre || die "Aborted: scp script to ${node} (SSH failure lock active; recovery above)."
  if scp "${scp_opts[@]}" "$self" "${user}@${node}:${REMOTE_SELF}"; then
    ssh_attempt_ok
  else
    ssh_attempt_fail
    die "Failed to copy script to ${node}. Check SSH auth and retry."
  fi

  log "Running server bootstrap on ${node}..."
  # Forward the canonical env names; --force-reinstall passes through too.
  # P2 fix: also forward ARGO_ANYWHERE_VERBOSE_SERVER (set by --verbose-server)
  # so the server-side write_argoproxy_config knows whether to emit
  # `verbose: true` (debug; explicit opt-in) or `verbose: false` (default
  # since v2.0; prevents prompts being logged to ~/.argo-anywhere.server.log
  # in plaintext on a shared compute node).
  local force_kv=""
  if [ -n "${FORCE_REINSTALL:-}" ]; then
    force_kv="ARGO_ANYWHERE_FORCE_REINSTALL=1 "
  fi
  local verbose_kv=""
  if [ -n "${ARGO_ANYWHERE_VERBOSE_SERVER:-}" ]; then
    verbose_kv="ARGO_ANYWHERE_VERBOSE_SERVER=1 "
  fi
  ssh_attempt_pre || die "Aborted: server bootstrap on ${node} (SSH failure lock active; recovery above)."
  # shellcheck disable=SC2046
  if ssh -o StrictHostKeyChecking=accept-new \
         $(ssh_args "$user" "$node") "${user}@${node}" \
         "ARGO_ANYWHERE_USER='${user}' ARGO_ANYWHERE_PORT='${PROXY_PORT}' ${force_kv}${verbose_kv}bash ~/${REMOTE_SELF} server"; then
    ssh_attempt_ok
  else
    ssh_attempt_fail
    die "Server bootstrap on ${node} failed. Check ~/${REMOTE_LOG} on the node."
  fi
  ok "Server is up on ${node}:${PROXY_PORT}."
}

# ============================================================================
# SECTION: 16. LOCAL TUNNEL + HEALTH MONITOR (open_tunnel + monitor_tunnel_loop)
# ============================================================================
# Foreground ssh -L; background loop polls /health and notifies on failure.
# Reconnect-via-mux when the tunnel drops but the master is still alive.
SSH_TUNNEL_PID=""
MONITOR_PID=""

# Set by main() and mode_client() so cleanup_local can render an
# accurate post-Ctrl+C exit summary (audit finding N1). Both default
# to empty so the summary degrades gracefully if cleanup fires before
# they're set (e.g. error during arg parsing).
_INVOKED_MODE=""
_INVOKED_CLI_TOOL=""

cleanup_local() {
  local rc=$?
  trap - EXIT INT TERM
  if [ -n "$MONITOR_PID" ] && kill -0 "$MONITOR_PID" 2>/dev/null; then
    kill "$MONITOR_PID" 2>/dev/null || true
  fi
  local closed_tunnel=0
  if [ -n "$SSH_TUNNEL_PID" ] && kill -0 "$SSH_TUNNEL_PID" 2>/dev/null; then
    log "Closing SSH tunnel (pid=${SSH_TUNNEL_PID})..."
    kill "$SSH_TUNNEL_PID" 2>/dev/null || true
    wait "$SSH_TUNNEL_PID" 2>/dev/null || true
    closed_tunnel=1
  fi

  # Audit finding N1: print a short exit summary so the user knows
  # exactly what just got torn down vs what is still running on the
  # compute node. Only meaningful for foregrounded modes that owned
  # a local tunnel + monitor (client / tunnel); skip otherwise to
  # avoid noise on script-internal die paths or for subcommands
  # like 'status' / 'help' that never started a monitor.
  #
  # N1 amendment (2026-05-15, post-live-test #1): the original summary
  # said "To fully stop: bash argo-anywhere.sh stop" which was
  # misleading -- the local tunnel is ALREADY gone by the time the
  # summary prints, so 'stop' would be a no-op. The user's actual
  # decision after Ctrl+C is "what other state from this session do I
  # also want torn down?" There are three independently-resident
  # pieces of state, and the new summary lists them explicitly + the
  # exact command for each scope:
  #   1. SSH multiplex master (laptop ~/.ssh/sockets/) -- alive,
  #      keeps Duo state warm; close with `ssh -O exit -S <sock>`.
  #   2. Remote argo-proxy (compute node) -- alive, keeps the node's
  #      port held; close with `clean` (or the screen/tmux/pkill
  #      one-liner clean prints when invoked with --remote-only).
  #   3. Local config / state dir / cache -- alive, harmless; clean
  #      with `clean` if you want a true blank slate.
  case "${_INVOKED_MODE:-}" in
    client|setup|tunnel)
      if [ "$closed_tunnel" = 1 ] || [ -n "$MONITOR_PID" ]; then
        local _self; _self="$(basename "$0")"
        local _node="${_PICKED_NODE:-${ARGO_ANYWHERE_NODE:-<node>}}"
        # Only mention --cli-tool if we actually picked one (client/setup);
        # tunnel mode is tool-agnostic.
        local _reuse_cmd
        if [ -n "${_INVOKED_CLI_TOOL:-}" ]; then
          _reuse_cmd="bash ${_self} --cli-tool ${_INVOKED_CLI_TOOL} client"
        elif [ "${_INVOKED_MODE}" = "tunnel" ]; then
          _reuse_cmd="bash ${_self} tunnel"
        else
          _reuse_cmd="bash ${_self} --cli-tool <name> client"
        fi
        # Compute the exact mux-socket path so the user can copy/paste
        # the `ssh -O exit -S ...` command without having to look it up.
        local _user="${ARGO_ANYWHERE_USER:-${ANL_USERNAME:-<user>}}"
        local _mux_sock="${SSH_MUX_DIR}/argo-anywhere-${_user}-${_node}-22"
        local _mux_alive=0
        [ -S "$_mux_sock" ] && _mux_alive=1

        ok "Ctrl-C: tore down the local SSH tunnel + health monitor."
        log ""
        log "What's still alive (intentional; left for fast restart):"
        if [ "$_mux_alive" = 1 ]; then
          log "  * SSH multiplex master to ${_user}@${_node}"
          log "      (keeps Duo state warm; next 'client' run skips the Duo prompt)"
        else
          log "  * (no SSH multiplex master on disk; nothing to reuse on the laptop side)"
        fi
        log "  * Remote argo-proxy on ${_node}:${PROXY_PORT}"
        log "      (still serving; any laptop with a tunnel here keeps working)"
        log ""
        log "Pick the scope you actually want, by what you want to keep warm:"
        log "  Restart instantly (reuse mux + remote argo-proxy; no Duo prompt):"
        log "    ${_reuse_cmd}"
        if [ "$_mux_alive" = 1 ]; then
          log "  Also close the SSH master (frees the socket; next run re-prompts Duo):"
          log "    ssh -O exit -S ${_mux_sock} placeholder"
        fi
        log "  Also stop the remote argo-proxy + remove all script state (laptop + node):"
        log "    bash ${_self} clean"
      fi
      ;;
  esac

  exit "$rc"
}

# Background health monitor body. Run as: `spawn_health_monitor "$pid" &`
# where $pid may be empty (mux-owned forward; no foreground ssh to watch).
#
# Behavior:
#   * polls /health every $HEALTH_INTERVAL seconds;
#   * on $HEALTH_FAIL_THRESHOLD consecutive failures, alerts the user and
#     (in mux-owned mode) exits so the parent can react;
#   * if a tunnel pid was provided, exits when that pid dies so the parent
#     can attempt a silent reconnect.
spawn_health_monitor() {
  local tunnel_pid_to_watch="$1"
  local fail=0
  while sleep "$HEALTH_INTERVAL"; do
    if curl -fsS --max-time 5 "http://localhost:${PROXY_PORT}/health" >/dev/null 2>&1; then
      fail=0
    else
      fail=$((fail+1))
      warn "Health check failed (${fail}/${HEALTH_FAIL_THRESHOLD})."
      if [ "$fail" -ge "$HEALTH_FAIL_THRESHOLD" ]; then
        notify_user "argo-proxy tunnel" \
          "Lost connection to ${node:-<node>}:${PROXY_PORT}. The SSH tunnel or the remote proxy is down."
        # In mux-owned mode (no fg pid to watch), sustained health failure
        # means the forward is likely gone; exit so the parent can react.
        if [ -z "$tunnel_pid_to_watch" ]; then
          exit 0
        fi
        fail=0  # re-arm; avoid notification spam
      fi
    fi
    # Detect tunnel-process death (only meaningful when we have a pid).
    if [ -n "$tunnel_pid_to_watch" ] && ! kill -0 "$tunnel_pid_to_watch" 2>/dev/null; then
      exit 0
    fi
  done
}

# open_tunnel: bring up the SSH local-forward and wait until /health on
# localhost:PROXY_PORT answers (or fail loudly). Sets SSH_TUNNEL_PID as a
# side effect; on the macOS/mux-owned scenario that pid may be empty (the
# fg ssh exited but the multiplex master is holding the forward). Returns
# 0 on success, dies on failure.
#
# Caller is responsible for: deciding it's OK to start a tunnel (see
# ensure_or_reuse_tunnel), rendering the post-tunnel summary, and either
# calling monitor_tunnel_loop to block forever or doing one-shot work.
open_tunnel() {
  local user="$1" node="$2"

  # Safety net: ensure_or_reuse_tunnel is the proper place to handle local
  # collision (it can reuse a healthy tunnel or kill an unhealthy one), but
  # if some path reaches open_tunnel directly without going through
  # ensure_or_reuse_tunnel, we still want to fail loudly rather than try
  # to bind a port that's already in use.
  if lsof -nPi ":${PROXY_PORT}" -sTCP:LISTEN >/dev/null 2>&1; then
    err "Port ${PROXY_PORT} is already in use locally."
    err "  This is a programming error: open_tunnel should be called via"
    err "  ensure_or_reuse_tunnel which handles collision detection."
    err "  Identify: lsof -nPi :${PROXY_PORT} -sTCP:LISTEN"
    err "  Kill:     kill <PID>   (or: bash $0 stop)"
    die "Refusing to start a duplicate tunnel."
  fi

  log "Opening tunnel: localhost:${PROXY_PORT} -> ${node}:${PROXY_PORT} $(jump_descr)"
  # shellcheck disable=SC2046
  ssh -N -L "${PROXY_PORT}:localhost:${PROXY_PORT}" \
      $(ssh_args "$user" "$node") \
      -o ServerAliveInterval=30 -o ServerAliveCountMax=3 \
      -o ExitOnForwardFailure=yes \
      -o StrictHostKeyChecking=accept-new \
      "${user}@${node}" &
  SSH_TUNNEL_PID=$!
  trap cleanup_local EXIT INT TERM

  # Wait briefly for the local port to come up.
  #
  # MUX-OWNED-FORWARD NOTE: under MFA mode, the foreground `ssh -N -L` we
  # just spawned routes through the existing ControlMaster connection
  # (because ControlMaster=auto is in $(ssh_args) and a master to
  # ${user}@${node} already exists from ssh_preflight). What this means
  # in practice:
  #
  #   1. The forward gets installed in the master.
  #   2. The foreground ssh process is then a thin "mux client" that may
  #      exit immediately after the request is acknowledged -- the master
  #      keeps the forward alive on its own.
  #
  # So `kill -0 $SSH_TUNNEL_PID` returning false is NOT a failure signal
  # by itself. The forward can be perfectly healthy with the foreground
  # process gone. We must check the actual port (via /health) before
  # declaring failure. This avoids the false-positive
  # "SSH tunnel exited before the proxy became reachable" error users
  # have hit when the master happily took over.
  local waited=0
  until curl -fsS --max-time 2 "http://localhost:${PROXY_PORT}/health" >/dev/null 2>&1; do
    sleep 1; waited=$((waited+1))
    if ! kill -0 "$SSH_TUNNEL_PID" 2>/dev/null; then
      # Foreground ssh exited. Could be:
      #   (a) mux master accepted the forward and the client just exited
      #       -> port should be bound and /health will start answering soon
      #   (b) the actual ssh failed (auth, ExitOnForwardFailure on bind clash, etc.)
      #       -> port not bound, /health silent
      # Distinguish by giving /health a couple more seconds and checking
      # whether the port is even bound. If neither, fail loudly.
      sleep 2
      if curl -fsS --max-time 2 "http://localhost:${PROXY_PORT}/health" >/dev/null 2>&1; then
        warn "Foreground ssh exited but the SSH multiplex master picked up the"
        warn "  port forward; tunnel is live and owned by the master from here on."
        # Clear the pid so cleanup_local doesn't try to kill an already-dead pid.
        # The mux master remains; user can close it via 'clean' or it'll expire
        # after ControlPersist seconds (default 1h).
        SSH_TUNNEL_PID=""
        break
      fi
      if lsof -nPi ":${PROXY_PORT}" -sTCP:LISTEN >/dev/null 2>&1; then
        warn "Port ${PROXY_PORT} is bound but /health still silent;"
        warn "  giving argo-proxy another moment..."
        # Fall through and let the outer loop keep polling (waited still bounded).
        continue
      fi
      die "SSH tunnel exited before the proxy became reachable (port ${PROXY_PORT} unbound)."
    fi
    if [ "$waited" -ge 20 ]; then
      die "Tunnel up but proxy not answering on localhost:${PROXY_PORT} after ${waited}s."
    fi
  done
  ok "Tunnel is live. argo-proxy reachable at http://localhost:${PROXY_PORT}/v1"
}

# monitor_tunnel_loop: block on the tunnel forever; reconnect transparently
# when fg ssh dies if the multiplex master is still alive; tear everything
# down on Ctrl-C / SIGTERM. Reads SSH_TUNNEL_PID/MONITOR_PID set by
# open_tunnel. Returns only when the tunnel is permanently down (and the
# trap'd cleanup_local will exit the script).
monitor_tunnel_loop() {
  local user="$1" node="$2"

  # Background health monitor. Notes the tunnel pid, polls /health on a timer,
  # notifies the user on sustained failure or tunnel-process death.
  #
  # Note: the monitor runs in a subshell (& backgrounded), so it cannot mutate
  # the parent's SSH_TUNNEL_PID. Reconnect-via-mux is therefore handled in the
  # PARENT, after `wait` returns -- see below. This intentionally trades a few
  # extra seconds of downtime for a correct pid handoff.
  #
  # When SSH_TUNNEL_PID is empty (foreground ssh exited; mux master owns the
  # forward), there is no pid to watch. The monitor keeps polling /health and
  # only exits if /health has been down long enough that the forward likely
  # went away. The parent's wait-on-MONITOR_PID branch then picks up.
  spawn_health_monitor "$SSH_TUNNEL_PID" &
  MONITOR_PID=$!

  if [ -n "$SSH_TUNNEL_PID" ]; then
    log "Foregrounding tunnel. Ctrl-C to disconnect."
  else
    log "Foregrounding (mux-owned tunnel; Ctrl-C to disconnect health monitor)."
    log "  Note: the SSH multiplex master keeps the forward alive even if you"
    log "  kill this script. Use 'bash $(basename "$0") stop' (or 'clean') to"
    log "  fully tear down the tunnel."
  fi

  # Parent loop: wait on the tunnel; if it dies on its own AND the mux master
  # is still alive, transparently respawn. Ctrl-C / SIGTERM go through
  # cleanup_local (which `exit`s before we ever reach the reconnect block).
  #
  # Special case: when SSH_TUNNEL_PID is empty (foreground ssh exited but the
  # mux master is forwarding), there's no foreground process to wait on. We
  # still want to monitor health, so we wait on the monitor pid instead (or
  # sleep forever if the monitor is also gone). The reconnect logic below
  # skips the ssh-O-check + respawn dance because the master is already
  # serving the forward.
  #
  # Reconnect backoff: macOS's system OpenSSH exits the foreground `ssh -N -L`
  # immediately after the multiplex master accepts the forward. The first
  # spawn handles that case explicitly (see MUX-OWNED-FORWARD NOTE above);
  # the reconnect path needs the same handling, otherwise the parent loop
  # spins:
  #     wait $pid -> exits instantly because $pid was already a zombie
  #     -> "ssh tunnel exited" warn
  #     -> ssh -O check ok
  #     -> spawn new fg ssh, which immediately exits the same way
  #     -> "Reconnected silently" ok
  #     -> wait the new $pid -> exits instantly -> goto top
  # symptom = a tight loop of three lines (exited / attempting / reconnected)
  # with monotonically increasing pids. We protect against this by:
  #   1. detecting the same mux-owned scenario after each reconnect attempt
  #      and clearing SSH_TUNNEL_PID so the next loop iteration falls into
  #      the empty-pid branch (waits on the monitor, not the dead fg pid);
  #   2. tracking reconnect attempts in a sliding window and sleeping a
  #      growing backoff if too many fire too fast (defends against the same
  #      pathology under any other root cause).
  # C7 fix (audit): two reconnect-loop hardenings:
  #
  #   (a) The ssh -N -L reconnect now goes through ssh_attempt_pre/ok/fail.
  #       Previously this path was outside the SSH attempt tracker; under
  #       sustained network/proxy flapping it could re-auth ~120 times an
  #       hour without ever incrementing the failure counter.
  #
  #   (b) Burst-cap escalates: original code paused 30s after 3 reconnects
  #       in a 60s window and continued. Now we pause 5min after the first
  #       burst and STOP reconnecting after 3 burst events (i.e. roughly
  #       9 attempts spread over 30+ min of degraded operation). Past that
  #       point the user is notified and the loop exits; they decide
  #       whether to re-run client manually.
  local reconnect_burst=0          # consecutive reconnects within RECONN_WINDOW_SEC
  local reconnect_burst_started=0  # epoch seconds the current burst started
  local reconnect_burst_event_count=0   # how many burst events have fired (C7)
  local RECONN_WINDOW_SEC=60
  local RECONN_BURST_LIMIT=3
  local RECONN_BURST_EVENT_MAX=3        # give up reconnecting after this many bursts
  local RECONN_PAUSE_SEC=300            # 5 min after a burst (was HEALTH_INTERVAL*2 = 30s)
  while true; do
    if [ -n "$SSH_TUNNEL_PID" ]; then
      wait "$SSH_TUNNEL_PID" || true
      warn "SSH tunnel process exited (pid=${SSH_TUNNEL_PID})."
    else
      # No foreground tunnel pid; wait on the health monitor instead so
      # Ctrl-C still works. If the monitor exits (e.g. it detected the
      # forward died), fall through to the reconnect-attempt block below.
      if [ -n "${MONITOR_PID:-}" ]; then
        wait "$MONITOR_PID" 2>/dev/null || true
        warn "Health monitor exited; checking forward state."
      else
        # No monitor either -- shouldn't happen. Bail safely.
        warn "No tunnel pid and no monitor pid; nothing to wait on."
        break
      fi
    fi

    # Pre-reconnect: if /health still answers, the forward is fine -- the
    # foreground ssh just exited (mux-owned scenario). Don't bother
    # reconnecting; just clear SSH_TUNNEL_PID and loop, so the next
    # iteration waits on the monitor instead of trying to wait on a dead pid.
    if curl -fsS --max-time 2 "http://localhost:${PROXY_PORT}/health" >/dev/null 2>&1; then
      log "Foreground ssh exited but /health still responds; mux master owns"
      log "  the forward. No reconnect needed."
      SSH_TUNNEL_PID=""
      # Make sure a monitor is running (the previous one may have exited
      # along with the fg ssh death-detect branch).
      if [ -z "${MONITOR_PID:-}" ] || ! kill -0 "${MONITOR_PID:-0}" 2>/dev/null; then
        spawn_health_monitor "" &
        MONITOR_PID=$!
      fi
      continue
    fi

    # Apply burst backoff BEFORE attempting a reconnect. If we've reconnected
    # RECONN_BURST_LIMIT times within RECONN_WINDOW_SEC seconds, escalate.
    local now; now="$(date +%s)"
    if [ "$reconnect_burst_started" -eq 0 ] \
       || [ $((now - reconnect_burst_started)) -gt "$RECONN_WINDOW_SEC" ]; then
      reconnect_burst=0
      reconnect_burst_started="$now"
    fi
    if [ "$reconnect_burst" -ge "$RECONN_BURST_LIMIT" ]; then
      reconnect_burst_event_count=$((reconnect_burst_event_count + 1))
      # C7 fix: if too many burst events, GIVE UP. The user's
      # network/proxy is sustained-flapping; we stop hammering it
      # rather than continuing to attempt and risk CSPO.
      if [ "$reconnect_burst_event_count" -ge "$RECONN_BURST_EVENT_MAX" ]; then
        warn "Reconnect loop has fired ${reconnect_burst_event_count} burst events"
        warn "  (${reconnect_burst} reconnects per burst, ${RECONN_BURST_LIMIT} bursts allowed)."
        warn "  This indicates sustained network or proxy instability."
        warn "  Giving up automatic reconnect to prevent CSPO IP block."
        warn "  Re-run 'bash $0 --cli-tool ${CLI_TOOL_OVERRIDE:-<name>} client' when stable."
        notify_user "argo-proxy tunnel" \
          "Reconnect loop gave up after ${reconnect_burst_event_count} burst events. Re-run client manually."
        break
      fi
      warn "Too many silent reconnects in the last ${RECONN_WINDOW_SEC}s"
      warn "  (${reconnect_burst} attempts; burst event ${reconnect_burst_event_count}/${RECONN_BURST_EVENT_MAX});"
      warn "  pausing ${RECONN_PAUSE_SEC}s (${RECONN_PAUSE_SEC}s = $((RECONN_PAUSE_SEC/60))min) before retrying."
      sleep "$RECONN_PAUSE_SEC"
      # New burst window after the pause.
      reconnect_burst=0
      reconnect_burst_started="$(date +%s)"
    fi

    # Try silent reconnect under MFA mode if the mux master is still alive.
    # Use the local `user` arg (not the global $ANL_USERNAME) so this code
    # path stays correct if invoked from a context that didn't set the global.
    local reconnected=0
    if mfa_enabled; then
      # C7 fix: gate the reconnect on the SSH attempt tracker. If the
      # CSPO lock is active, refuse to add more attempts; the user
      # gets the same notification path as a totally-failed reconnect.
      if ! ssh_attempt_pre; then
        # L4+L5 fix (audit Phase 2c): ssh_attempt_pre already printed
        # the recovery block above; one short warn line is enough to
        # mark the reconnect-refusal as a separate event from the
        # lock-fired event.
        warn "Reconnect refused (SSH failure lock active; recovery above)."
        notify_user "argo-proxy tunnel" \
          "SSH lock active; tunnel reconnect refused. Fix auth + delete lock to retry."
        break
      fi
      # shellcheck disable=SC2046
      if ssh -O check $(ssh_args "$user" "$node") "${user}@${node}" 2>/dev/null; then
        warn "SSH multiplex master is still alive; attempting silent reconnect..."
        reconnect_burst=$((reconnect_burst + 1))
        # shellcheck disable=SC2046
        ssh -N -L "${PROXY_PORT}:localhost:${PROXY_PORT}" \
            $(ssh_args "$user" "$node") \
            -o ServerAliveInterval=30 -o ServerAliveCountMax=3 \
            -o ExitOnForwardFailure=yes \
            "${user}@${node}" &
        SSH_TUNNEL_PID=$!
        # Give it up to 10s to start serving /health.
        local rc_wait=0 rc_ok=0
        until curl -fsS --max-time 2 "http://localhost:${PROXY_PORT}/health" >/dev/null 2>&1; do
          sleep 1; rc_wait=$((rc_wait+1))
          if ! kill -0 "$SSH_TUNNEL_PID" 2>/dev/null; then break; fi
          if [ "$rc_wait" -ge 10 ]; then break; fi
        done
        if curl -fsS --max-time 2 "http://localhost:${PROXY_PORT}/health" >/dev/null 2>&1; then
          rc_ok=1
        fi
        if [ "$rc_ok" -eq 1 ]; then
          # C7 fix: tracker accounting -- successful reconnect.
          ssh_attempt_ok
          # Apply the same mux-owned-forward check as the first-spawn block:
          # if the foreground ssh has already exited but /health still
          # answers, the master is doing the work. Clearing SSH_TUNNEL_PID
          # lets the next loop iteration wait on the monitor instead of
          # immediately returning from `wait <dead-pid>` and spinning.
          if ! kill -0 "$SSH_TUNNEL_PID" 2>/dev/null; then
            ok "Reconnected silently; mux master owns the new forward."
            SSH_TUNNEL_PID=""
          else
            ok "Reconnected silently via SSH multiplex master (pid=${SSH_TUNNEL_PID})."
          fi
          reconnected=1
          # Restart the monitor if the previous one exited.
          if [ -z "${MONITOR_PID:-}" ] || ! kill -0 "${MONITOR_PID:-0}" 2>/dev/null; then
            spawn_health_monitor "$SSH_TUNNEL_PID" &
            MONITOR_PID=$!
          fi
        else
          # /health didn't come up. Two sub-cases (per C7 audit):
          #   A. ssh process died early -> SSH-side failure; count toward
          #      the SSH attempt tracker. Could be auth, ExitOnForwardFailure
          #      (port collision), or various network errors.
          #   B. ssh process is alive -> the forward is in place but the
          #      remote argo-proxy isn't answering. NOT an SSH failure;
          #      don't count toward the tracker (would falsely punish the
          #      user for a remote-side outage).
          if ! kill -0 "$SSH_TUNNEL_PID" 2>/dev/null; then
            # Sub-case A: ssh died.
            ssh_attempt_fail
            warn "Reconnect ssh exited early (forward not installed; auth issue or remote-port collision; tracker state above)."
          else
            # Sub-case B: ssh alive, /health silent.
            ssh_attempt_ok   # still a successful ssh; mark accordingly
            warn "Reconnect installed the SSH forward but /health is silent."
            warn "  Most likely argo-proxy on ${node} is down or restarting."
            warn "  Good news: the SSH multiplex master is still holding the"
            warn "  forward, so once argo-proxy on ${node} is back, this tunnel"
            warn "  will resume serving with no action needed from you."
            warn "  If you need to bring argo-proxy back manually:"
            warn "    ssh ${user}@${node} 'bash ~/${REMOTE_SELF} server'"
            warn "  To fully reset the tunnel itself: 'bash $0 client'"
            # Kill the freshly-spawned ephemeral fg ssh (it just sits there
            # consuming a pid; the master keeps the forward), and clear our
            # pid tracking so the next loop iteration waits on the monitor
            # rather than a dead pid.
            kill "$SSH_TUNNEL_PID" 2>/dev/null || true
          fi
          SSH_TUNNEL_PID=""
          notify_user "argo-proxy tunnel" \
            "Proxy on ${node}:${PROXY_PORT} not responding; SSH forward stays alive (recovers when proxy returns)."
        fi
      else
        # SSH master is gone too. Reconnect would need fresh Duo;
        # script can't do that without user interaction.
        warn "SSH multiplex master is gone (Duo prompt would be required to reconnect)."
        notify_user "argo-proxy tunnel" "Tunnel down; re-run: bash $0 client"
      fi
    else
      notify_user "argo-proxy tunnel" "Tunnel down; re-run: bash $0 client"
    fi

    if [ "$reconnected" -eq 0 ]; then
      break
    fi
    # Loop back to wait on the new SSH_TUNNEL_PID (or the monitor, if the
    # mux-owned check above cleared the pid).
  done

  cleanup_local
}

# ----------------------------------------------------------------------------
# Tunnel collision detection + reuse (subsection of 16)
# ----------------------------------------------------------------------------
# Two distinct collision cases the script needs to handle smoothly:
#
#   * Local self-collision: localhost:PROXY_PORT is already bound on this
#     machine, possibly by THIS user's previous tunnel/client invocation.
#     If it's our own healthy tunnel, reuse it instead of erroring; if it's
#     an unrelated process, refuse with the existing message.
#
#   * Remote multi-user collision: 127.0.0.1:PROXY_PORT on the picked node
#     is already bound by another OS user's argo-proxy. Today the
#     server-side check at line ~1900 catches this AFTER the bootstrap +
#     SSH have run; nicer is to detect it BEFORE the bootstrap so we can
#     prompt the user (auto-pick another port, pick one manually, retry,
#     or abort).
#
# These helpers do the detection and prompting. ensure_or_reuse_tunnel ties
# them together into the decision tree mode_client and mode_tunnel call.

# local_tunnel_status: classify the local listener on PROXY_PORT.
# Echoes one of:
#   free                -- nothing bound; safe to start a new tunnel
#   ours-healthy        -- ssh -L matching our shape AND /health answers; reuse
#   ours-unhealthy      -- ssh -L matching our shape but /health silent; kill+restart
#   external-healthy    -- something else bound, /health works (e.g. argo-proxy
#                          running locally on a compute node); proceed without
#                          opening a tunnel; clients can use it directly
#   other-or-broken     -- something else bound and /health doesn't work; refuse
# local_tunnel_destination <port>: prints the destination host of the
# SSH tunnel/master currently holding the local listener on <port>, or
# empty string if it can't be determined. Args: 1 = port number.
#
# How it works (P3 fix audit):
#
# The script's mux sockets are named per the literal-tokens template
# `argo-anywhere-%r-%h-%p` (see ssh_mux_args). So a master to
# `aattia@compute-01.cels.anl.gov:22` lives at the path
# `~/.ssh/sockets/argo-anywhere-aattia-compute-01.cels.anl.gov-22`.
# A foreground `ssh -N -L PORT:...` opened with ControlMaster=auto
# also has that ControlPath in its `ps` command-line.
#
# So: find the listener pid for <port>, read its `ps` command, extract
# the ControlPath socket name, parse out the host. The host portion is
# encoded between the user prefix and the port suffix in the socket
# basename.
#
# Why this exists (P3 audit finding): the G1 same-port-different-node
# check used to compare against the cached node, which pick_node updated
# eagerly BEFORE a successful tunnel establishment, so the comparison
# always passed and silent misroute slipped through. Reading the actual
# socket name is ground truth: it's literally the destination openssh
# is talking to.
#
# Returns: prints the host name (e.g. `compute-01.cels.anl.gov`) and
# exits 0; OR prints nothing and exits 0 if it can't be determined.
# Never errors / dies; the caller decides what to do with empty output.
local_tunnel_destination() {
  local port="$1"
  local pid
  # Same SIGPIPE-resilient pattern as local_tunnel_status (P1 fix).
  pid="$( { lsof -nPi ":${port}" -sTCP:LISTEN -t 2>/dev/null | head -n1; } || true )"
  [ -n "$pid" ] || { printf ''; return 0; }

  local cmd
  cmd="$(ps -o command= -p "$pid" 2>/dev/null || true)"
  [ -n "$cmd" ] || { printf ''; return 0; }

  # Extract the ControlPath socket. Two patterns in the wild:
  #   - foreground ssh: `... -o ControlPath=/path/argo-anywhere-USER-HOST-PORT ...`
  #     OR `... -S /path/argo-anywhere-USER-HOST-PORT ...` (less common)
  #   - mux master:     `ssh: /path/argo-anywhere-USER-HOST-PORT [mux]`
  # Both expose the socket path verbatim. We sed for the literal
  # 'argo-anywhere-' (or 'argo-opencode-' for v1.x masters still alive
  # mid-upgrade) and extract the socket basename. Two sed passes (one
  # per prefix) instead of one with alternation: BSD sed -E (macOS)
  # alternation inside a capture group is fragile across versions; two
  # focused patterns are simpler and match exactly one socket basename.
  local sock_basename=""
  case "$cmd" in
    *argo-anywhere-*)
      sock_basename="$(printf '%s\n' "$cmd" | \
        sed -nE 's|.*[/=[:space:]](argo-anywhere-[^[:space:]]+).*|\1|p' | head -n1)"
      ;;
    *argo-opencode-*)
      sock_basename="$(printf '%s\n' "$cmd" | \
        sed -nE 's|.*[/=[:space:]](argo-opencode-[^[:space:]]+).*|\1|p' | head -n1)"
      ;;
  esac
  [ -n "$sock_basename" ] || { printf ''; return 0; }

  # Parse the basename: argo-{anywhere,opencode}-USER-HOST-PORT
  # Strip the prefix:
  local without_prefix="${sock_basename#argo-anywhere-}"
  without_prefix="${without_prefix#argo-opencode-}"
  # Strip the trailing -PORT (port is purely numeric):
  local without_port="${without_prefix%-[0-9]*}"
  # Strip the user prefix. We don't always know the user (callers may
  # invoke this without passing it), so we use a generic "first hyphen-
  # separated field is the user" rule — works because ANL usernames are
  # alphanumeric (no hyphens) and the host always contains dots.
  local host="${without_port#*-}"
  # Sanity: host should look like a hostname (contain a dot OR be a
  # bare alphanumeric label). If parsing went sideways, return empty.
  case "$host" in
    *.*|[a-zA-Z0-9]*) printf '%s' "$host" ;;
    *) printf '' ;;
  esac
}

local_tunnel_status() {
  local port="$1"
  local pid
  # P1 fix: wrap pipeline in { ...; } || true to swallow SIGPIPE.
  # Otherwise: lsof writes -> head -n1 closes stdin after first line ->
  # lsof gets SIGPIPE, exits non-zero -> pipefail makes the pipe
  # non-zero -> set -e kills the script silently in the assignment.
  # Same fix applied at line ~2581 (ensure_or_reuse_tunnel) and ~3550
  # (mode_server's other_argoproxy_port detection).
  pid="$( { lsof -nPi ":${port}" -sTCP:LISTEN -t 2>/dev/null | head -n1; } || true )"
  if [ -z "$pid" ]; then
    echo "free"
    return
  fi

  local healthy=0
  if curl -fsS --max-time 2 "http://localhost:${port}/health" >/dev/null 2>&1; then
    healthy=1
  fi

  # Heuristic: is this an ssh-related process that's likely OUR tunnel?
  # We distinguish two sub-cases because they have DIFFERENT cleanup
  # semantics:
  #
  #   * fg-tunnel: a foreground `ssh -N -L <port>:...` we just spawned.
  #     We own this pid; killing it on cleanup is correct.
  #     Detected by: command line contains the literal `-L <port>:`.
  #
  #   * mux: a multiplex MASTER (created by ssh_mux_open / ssh_args
  #     ControlMaster=auto) that's now holding the forward after the
  #     foreground slave exited (the macOS / mux-owned scenario from
  #     the duplicate-bootstrap-via-tee era). OTHER ssh sessions to the
  #     same destination may also be using this master; killing it on
  #     cleanup would destroy them too. We must NOT capture this pid
  #     for cleanup_local's trap.
  #     Detected by: command line shows `ssh: /Users/.../sockets/argo-{anywhere,opencode}-... [mux]`.
  #     Both prefixes are matched so users upgrading mid-session don't lose
  #     mux-detection on their pre-v2.0 master sockets.
  #
  # Combined with the /health check, false positives would require a
  # foreign ssh that ALSO somehow hits a working /health endpoint. Very
  # unlikely in practice.
  local kind="none"
  local cmd
  cmd="$(ps -o command= -p "$pid" 2>/dev/null)"
  case "$cmd" in
    *ssh*\ -L\ "${port}:"*)         kind="fg-tunnel" ;;
    *ssh*-L\ "${port}:"*)           kind="fg-tunnel" ;;
    *ssh*-L${port}:*)               kind="fg-tunnel" ;;
    *ssh:*argo-anywhere-*\[mux\]*)  kind="mux" ;;
    *ssh:*argo-opencode-*\[mux\]*)  kind="mux" ;;  # legacy v1.x
  esac

  # M7 fix (audit Phase 2d): defense-in-depth fallback for the mux
  # detection regex. The exact `ps -o command=` output for an ssh
  # multiplex master varies between OS versions: macOS Big Sur+ shows
  # `ssh: <socket-path> [mux]`, older macOS / Linux variants may omit
  # the `[mux]` tag or use a different prefix. The regex matches above
  # cover the formats observed today; this fallback catches future
  # drift by checking two independent signals:
  #   (a) the command line mentions an argo-{anywhere,opencode} socket
  #       prefix, AND
  #   (b) a corresponding socket file exists in SSH_MUX_DIR.
  # Both signals are required; either alone is not specific enough.
  # (a) alone: a stale ps output with our prefix in some other context
  #     could match.
  # (b) alone: a stranger process happens to bind our port and we'd
  #     misclassify based on socket presence.
  # The conjunction is robust against ps format drift while requiring
  # positive evidence the listener IS our mux master.
  if [ "$kind" = "none" ]; then
    case "$cmd" in
      *argo-anywhere-*|*argo-opencode-*)
        # Look for ANY argo-* socket file in SSH_MUX_DIR; we don't try
        # to match the specific socket because the path-in-ps and
        # path-on-disk can differ in how they render quoting / abbrev.
        if [ -d "$SSH_MUX_DIR" ] && \
           ls "$SSH_MUX_DIR"/argo-anywhere-* "$SSH_MUX_DIR"/argo-opencode-* 2>/dev/null | head -n1 >/dev/null; then
          kind="mux"
        fi
        ;;
    esac
  fi

  if [ "$kind" = "fg-tunnel" ] && [ "$healthy" -eq 1 ]; then
    echo "ours-healthy-fg"
  elif [ "$kind" = "fg-tunnel" ] && [ "$healthy" -eq 0 ]; then
    echo "ours-unhealthy-fg"
  elif [ "$kind" = "mux" ] && [ "$healthy" -eq 1 ]; then
    echo "ours-healthy-mux"
  elif [ "$kind" = "mux" ] && [ "$healthy" -eq 0 ]; then
    # Master is bound but /health silent: weird; the master is alive but
    # nothing on the remote side. Treat as broken-and-mostly-ours; let
    # the caller decide whether to kill (probably yes, but with mux
    # implications, not blanket).
    echo "ours-unhealthy-mux"
  elif [ "$healthy" -eq 1 ]; then
    # /health works but it's not an ssh tunnel. Most likely argo-proxy
    # running locally (mode_server's launcher under screen/tmux/nohup) --
    # the on-compute-node case. From the perspective of clients we're
    # about to configure, the endpoint they need is reachable, so this
    # is fine; don't try to open a tunnel.
    echo "external-healthy"
  else
    echo "other-or-broken"
  fi
}

# probe_remote_port_owner: ask the picked node "is PROXY_PORT bound, and
# if so by whom?" Single SSH call. Echoes one of:
#   free                  -- nothing bound; ok to bootstrap
#   mine:<pid>            -- bound by an argo-proxy owned by US (will be reused)
#   other:<owner>:<pid>   -- bound by ANOTHER user; prompt for collision UX
#   unknown               -- probe failed; caller should warn + proceed
#                            optimistically (server-side check at line ~1900
#                            still catches a real collision)
probe_remote_port_owner() {
  local user="$1" node="$2" port="$3"
  ssh_attempt_pre || { echo "unknown"; return; }
  local result
  # The remote one-liner does its own pid -> owner lookup and compares
  # to its own `id -un`, returning "mine:<pid>" or "other:<owner>:<pid>"
  # so the caller doesn't need to know remote OS user names.
  # shellcheck disable=SC2046
  result="$(ssh $(ssh_args "$user" "$node") "${user}@${node}" "
    pid=\$(lsof -nPi \":${port}\" -sTCP:LISTEN -t 2>/dev/null | head -n1)
    if [ -z \"\$pid\" ]; then
      echo free
    else
      owner=\$(ps -o user= -p \"\$pid\" 2>/dev/null | awk '{\$1=\$1;print}')
      [ -z \"\$owner\" ] && owner='?'
      me=\$(id -un 2>/dev/null)
      if [ \"\$owner\" = \"\$me\" ]; then
        echo \"mine:\${pid}\"
      else
        echo \"other:\${owner}:\${pid}\"
      fi
    fi
  " 2>/dev/null)"
  if [ -z "$result" ]; then
    ssh_attempt_fail
    echo "unknown"
  else
    ssh_attempt_ok
    echo "$result"
  fi
}

# find_next_free_remote_port: walk a port range on the picked node and
# echo the first port that's free, or empty if none in the range. Single
# SSH call.
#
# H4 fix (audit Phase 2b Batch 5): the remote one-liner walks every
# port between start and end inclusive. Default range is 100 ports
# (start..start+100); a caller passing a too-wide range (e.g.
# ARGO_ANYWHERE_PORT_RANGE=64742-70000 = 5258 ports) would hold an SSH
# session open for tens of seconds while the inner shell-loop walks
# every port and runs lsof on each. Clamp the effective end to
# start+_FREE_PORT_MAX_SCAN-1 so the remote loop is bounded regardless
# of caller input. The cap is generous (200 ports) but defends against
# typo'd / pathological inputs without affecting the common case.
find_next_free_remote_port() {
  local user="$1" node="$2" start="$3" end="${4:-}"
  [ -n "$end" ] || end="$((start + 100))"
  local _FREE_PORT_MAX_SCAN=200
  local _max_end=$((start + _FREE_PORT_MAX_SCAN - 1))
  if [ "$end" -gt "$_max_end" ]; then
    warn "find_next_free_remote_port: clamping end ${end} to ${_max_end} (scanning more than ${_FREE_PORT_MAX_SCAN} ports per call is refused)."
    end="$_max_end"
  fi
  ssh_attempt_pre || { echo ""; return; }
  local result ssh_rc
  # shellcheck disable=SC2046
  result="$(ssh $(ssh_args "$user" "$node") "${user}@${node}" "
    p=${start}
    while [ \"\$p\" -le ${end} ]; do
      if ! lsof -nPi \":\${p}\" -sTCP:LISTEN -t >/dev/null 2>&1; then
        echo \"\${p}\"
        exit 0
      fi
      p=\$((p + 1))
    done
    exit 1
  " 2>/dev/null)" && ssh_rc=0 || ssh_rc=$?
  if [ "$ssh_rc" -ne 0 ] && [ -z "$result" ]; then
    # SSH itself failed (auth error, connection refused, etc.); count it.
    ssh_attempt_fail
    echo ""
  elif [ -n "$result" ]; then
    ssh_attempt_ok
    echo "$result"
  else
    # ssh exited 1 = ran OK but no free port found in range; not an SSH failure.
    echo ""
  fi
}

# prompt_port_collision: interactive prompt when the remote port is taken
# by another user. Echoes the new port the user picked (possibly the same
# one if they chose [r]etry; the caller re-probes), or empty string on
# abort (caller should die).
#
# The choices:
#   [n] next free port  -- find_next_free_remote_port over the configured range
#   [p] pick a port    -- read a number; validate
#   [r] retry          -- caller re-probes the original port
#   [a] abort          -- die
prompt_port_collision() {
  local user="$1" node="$2" port="$3" owner="$4" owner_pid="$5"
  local me; me="$(id -un 2>/dev/null)"
  cat >&2 <<EOF

[warn] Port ${port} on ${node} is in use by another user
       (pid ${owner_pid}, owned by '${owner}'; you are '${ARGO_ANYWHERE_USER:-${me}}').

       Two users can't share an argo-proxy on the same port; each needs
       their own. Options:
         [n] next free port  -- probe a range on ${node} and use the first free one
         [p] pick a port    -- I'll type a number (1024-65535)
         [r] retry          -- maybe '${owner}' just stopped; check ${port} again
         [a] abort
EOF
  while :; do
    local choice; choice="$(ask "Your choice [n/p/r/a, default=n]:" "n")"
    case "$choice" in
      n|N|"")
        # Use the configured port range (override via --port-range or env).
        local rstart="$PROXY_PORT_DEFAULT"
        local rend=$((rstart + 100))
        if [ -n "${ARGO_ANYWHERE_PORT_RANGE:-}" ]; then
          # Format: "LO-HI"
          rstart="${ARGO_ANYWHERE_PORT_RANGE%-*}"
          rend="${ARGO_ANYWHERE_PORT_RANGE#*-}"
        fi
        log "Probing ${node} for a free port in ${rstart}-${rend}..."
        local picked; picked="$(find_next_free_remote_port "$user" "$node" "$rstart" "$rend")"
        if [ -z "$picked" ]; then
          warn "No free port found in ${rstart}-${rend}."
          continue   # re-prompt
        fi
        ok "Found free port: ${picked}"
        echo "$picked"
        return ;;
      p|P)
        local newport
        while :; do
          newport="$(ask "  Port number [1024-65535]:" "")"
          case "$newport" in
            ''|*[!0-9]*) warn "  not a number"; continue ;;
          esac
          if [ "$newport" -ge 1024 ] && [ "$newport" -le 65535 ]; then
            echo "$newport"
            return
          else
            warn "  out of range (1024-65535)"
          fi
        done ;;
      r|R)
        echo "$port"
        return ;;
      a|A)
        echo ""
        return ;;
      *) warn "  unrecognized: '${choice}'" ;;
    esac
  done
}

# ensure_or_reuse_tunnel: the decision tree that ties everything together.
# Called by mode_client and mode_tunnel after the node is picked but before
# the bootstrap. Handles:
#   * local self-collision (reuse our healthy tunnel; kill an unhealthy one;
#     refuse a foreign listener)
#   * remote multi-user collision (prompt; loop until resolved or aborted)
#   * the standard "all clear, bootstrap + open tunnel" path
#
# On return, either:
#   * SSH_TUNNEL_PID is set (we opened or are reusing a tunnel) and the
#     caller can proceed to setup_*_client + render_summary + monitor loop;
#   * the on-external-healthy case fired (no tunnel was opened, but
#     /health works; SSH_TUNNEL_PID stays empty and the caller should
#     skip monitor_tunnel_loop -- handled via the return value below);
#   * the function dies on hard error.
#
# Returns 0 = tunnel up (call monitor_tunnel_loop), 2 = external-healthy
# (skip monitor; argo-proxy is reachable but we're not managing it).
ensure_or_reuse_tunnel() {
  local user="$1" node="$2"

  # 1) Local-side classification first. If we have a healthy local
  #    listener, decide whether to reuse it before doing any SSH work.
  local lstatus; lstatus="$(local_tunnel_status "$PROXY_PORT")"

  # P3 fix (audit): same-port-different-node check using the actual
  # ground-truth destination of the SSH master/tunnel, not a cached
  # value. The pre-fix check compared $node against the NODE_CACHE
  # contents, but pick_node updated the cache eagerly BEFORE this
  # check ran, so the comparison always succeeded and silent misroute
  # slipped through. local_tunnel_destination() inspects the listener
  # pid's ControlPath socket basename for the real destination.
  #
  # Two-layer fallback: if local_tunnel_destination returns empty (e.g.
  # the listener is a fg-tunnel without a Control* socket, or parsing
  # failed), fall back to the cache as a defensive last-resort. The
  # cache MAY be stale or not-yet-written if this is the user's first
  # ever invocation, so cache-disagreement is downgraded from die-hard
  # to warn-only in the fallback path. The socket-based check is the
  # primary defense.
  case "$lstatus" in
    ours-healthy-fg|ours-healthy-mux)
      local actual_dest; actual_dest="$(local_tunnel_destination "$PROXY_PORT")"
      if [ -n "$actual_dest" ] && [ "$actual_dest" != "$node" ]; then
        warn "An existing tunnel is bound to localhost:${PROXY_PORT}, but it was opened"
        warn "  by a previous run targeting '${actual_dest}', not the node you"
        warn "  just picked ('${node}'). Reusing it would silently send traffic to the"
        warn "  WRONG node. The script supports ONE tunnel per local port; you can't"
        warn "  have two tunnels on the same port to different nodes."
        warn ""
        warn "Options:"
        warn "  * Stop the existing tunnel ('$(basename "$0") stop') and re-run."
        warn "  * Pick a different port ('--port N') for this run."
        warn "  * Re-run targeting '${actual_dest}' (the existing tunnel's destination)."
        die "Refusing to silently reuse a tunnel pointed at a different node."
      fi
      # If actual_dest is empty (parse failure / fg-tunnel without
      # ControlPath), fall back to cache-based heuristic. Warn-only
      # (not die) because the cache may legitimately disagree on a
      # first-ever run with no prior cache entry.
      if [ -z "$actual_dest" ]; then
        local cached_node_for_check=""
        [ -f "$NODE_CACHE" ] && cached_node_for_check="$(cat "$NODE_CACHE" 2>/dev/null)"
        if [ -n "$cached_node_for_check" ] && [ "$cached_node_for_check" != "$node" ]; then
          warn "Could not determine the actual destination of the existing tunnel"
          warn "  on :${PROXY_PORT} (socket parsing returned empty). Cached node says"
          warn "  '${cached_node_for_check}'; you picked '${node}'. Proceeding optimistically;"
          warn "  if your traffic ends up at the wrong node, run 'stop' and re-run."
        fi
      fi
      ;;
  esac

  case "$lstatus" in
    ours-healthy-fg)
      # A foreground ssh -N -L we (or a previous invocation by the same
      # user) spawned. We can capture its pid for cleanup_local's trap
      # because it's a process we own end-to-end.
      ok "Found existing healthy tunnel on port ${PROXY_PORT}; reusing."
      # P1 fix: wrap pipeline in { ...; } || true to swallow SIGPIPE
      # from lsof when head -n1 closes stdin. See local_tunnel_status
      # for the full explanation.
      SSH_TUNNEL_PID="$( { lsof -nPi ":${PROXY_PORT}" -sTCP:LISTEN -t 2>/dev/null | head -n1; } || true )"
      trap cleanup_local EXIT INT TERM
      return 0 ;;
    ours-healthy-mux)
      # The listener is the multiplex MASTER, not a foreground ssh -L.
      # Other SSH sessions to the same destination may also be using
      # this master, so killing it on cleanup would be destructive.
      # Treat as "tunnel exists but we don't own it for cleanup
      # purposes" -- same handling as external-healthy: clear
      # SSH_TUNNEL_PID, no monitor loop, no cleanup_local trap.
      ok "Found existing tunnel on port ${PROXY_PORT} held by an SSH multiplex"
      ok "  master we initiated earlier; reusing without taking ownership."
      ok "  (cleanup_local won't kill the master on Ctrl-C; other sessions"
      ok "  using the same master stay safe.)"
      SSH_TUNNEL_PID=""
      return 2 ;;
    external-healthy)
      ok "argo-proxy is reachable on http://localhost:${PROXY_PORT}/v1 via an"
      ok "  existing local listener (not our SSH tunnel). Using it directly."
      return 2 ;;
    ours-unhealthy-fg)
      warn "Found a local ssh tunnel on port ${PROXY_PORT} but /health is silent;"
      warn "  killing it and starting a fresh one."
      # M6 fix (audit Phase 2d): kill only the specific PID detected,
      # AND double-check the process command line matches our ssh -L
      # pattern before killing. Pre-fix the unconditional
      # `lsof -t | xargs -n1 kill` would kill ANY process bound to
      # PROXY_PORT, even if the local_tunnel_status classification was
      # wrong (e.g. some other script's `ssh -L` to the same port that
      # didn't match our regex but happened to coincide). Defense-in-
      # depth: classification already said "fg-tunnel"; this re-checks
      # before destroying. Only kills processes whose ps -o command=
      # output contains `ssh` AND `-L <port>:` -- the same predicate
      # local_tunnel_status used to classify in the first place.
      local _kill_pid _kill_cmd _killed=0
      while IFS= read -r _kill_pid; do
        [ -n "$_kill_pid" ] || continue
        _kill_cmd="$(ps -o command= -p "$_kill_pid" 2>/dev/null)"
        case "$_kill_cmd" in
          *ssh*\ -L\ "${PROXY_PORT}:"*|*ssh*-L\ "${PROXY_PORT}:"*|*ssh*-L${PROXY_PORT}:*)
            kill "$_kill_pid" 2>/dev/null && _killed=$((_killed + 1)) || true
            ;;
          *)
            warn "  refused to kill pid ${_kill_pid}: command line"
            warn "    \"${_kill_cmd}\""
            warn "  doesn't match the ssh -L ${PROXY_PORT}: pattern. This is"
            warn "  unlikely (classification said fg-tunnel) but possible if"
            warn "  another process raced into the port. Inspect manually:"
            warn "    lsof -nPi :${PROXY_PORT} -sTCP:LISTEN"
            ;;
        esac
      done < <(lsof -nPi ":${PROXY_PORT}" -sTCP:LISTEN -t 2>/dev/null)
      if [ "$_killed" -eq 0 ]; then
        warn "  no PIDs killed; the listener may be a foreign process not"
        warn "  matching our ssh -L pattern. Refusing to start a fresh"
        warn "  tunnel on a port held by an unknown process."
        die "Refusing to overlay our tunnel on a foreign listener."
      fi
      sleep 1
      ;;
    ours-unhealthy-mux)
      warn "Multiplex master on port ${PROXY_PORT} but /health silent."
      warn "  Closing it via 'ssh -O exit' (which is mux-aware and won't"
      warn "  affect other sessions just by trying), then starting fresh."
      # ssh_mux_close_all walks the socket directory; it's the right tool
      # because it uses 'ssh -O exit' which the master responds to
      # gracefully (no other-session destruction).
      ssh_mux_close_all
      sleep 1
      ;;
    other-or-broken)
      err "Port ${PROXY_PORT} is already in use locally (and the listener is"
      err "  not our SSH tunnel)."
      err "  Identify: lsof -nPi :${PROXY_PORT} -sTCP:LISTEN"
      err "  Kill:     kill <PID>   (or: bash $0 stop)"
      die "Refusing to start a duplicate tunnel."
      ;;
    free)
      :  # fall through to the remote-side check
      ;;
  esac

  # 2) Remote-side classification. Probe the node; on multi-user
  #    collision, prompt the user (with --auto-port short-circuiting
  #    the prompt to "[n]ext free").
  local attempts=0
  local max_attempts=3
  while [ "$attempts" -lt "$max_attempts" ]; do
    attempts=$((attempts + 1))
    local rstatus; rstatus="$(probe_remote_port_owner "$user" "$node" "$PROXY_PORT")"
    case "$rstatus" in
      free|mine:*)
        # All clear. Bootstrap will start argo-proxy (mine:* case = will
        # reuse the existing one via the server-side check).
        break ;;
      other:*)
        local owner_pid; owner_pid="${rstatus##*:}"
        local owner; owner="${rstatus%:*}"; owner="${owner#other:}"
        local newport
        if [ "${AUTO_PORT:-${ARGO_ANYWHERE_AUTO_PORT:-0}}" = 1 ]; then
          warn "Port ${PROXY_PORT} on ${node} is taken by '${owner}' (pid ${owner_pid})."
          local rstart="$PROXY_PORT_DEFAULT"
          local rend=$((rstart + 100))
          if [ -n "${ARGO_ANYWHERE_PORT_RANGE:-}" ]; then
            rstart="${ARGO_ANYWHERE_PORT_RANGE%-*}"
            rend="${ARGO_ANYWHERE_PORT_RANGE#*-}"
          fi
          log "--auto-port: probing ${node} for a free port in ${rstart}-${rend}..."
          newport="$(find_next_free_remote_port "$user" "$node" "$rstart" "$rend")"
          [ -n "$newport" ] || die "No free port found in ${rstart}-${rend}."
          ok "Auto-picked free port: ${newport}"
        else
          newport="$(prompt_port_collision "$user" "$node" "$PROXY_PORT" "$owner" "$owner_pid")"
          [ -n "$newport" ] || die "Aborted at port-collision prompt."
        fi
        # Re-route through the unified [m/u/k/a] prompt against the new
        # port, so the user has a chance to update or not update their
        # OpenCode config. B0 fix (Phase 4 pre-work): factored to
        # prompt_port_choice (shared helper) -- was inline duplicate of
        # the startup-time prompt.
        if [ "$newport" != "$PROXY_PORT" ]; then
          # Override CLI port + clear any cached config-source state so
          # the prompt fires.
          PROXY_PORT="$newport"
          PORT_OVERRIDE_CLI="$newport"
          PORT_SOURCE="auto-pick / collision prompt"
          # The OpenCode-config migration prompt is in _client_common_setup;
          # since we've already passed that point, fire it inline via the
          # shared helper.
          if [ -n "$PORT_FROM_CONFIG" ] && [ "$PROXY_PORT" != "$PORT_FROM_CONFIG" ]; then
            local _ppc_choice
            _ppc_choice="$(prompt_port_choice "$PROXY_PORT" "$PORT_FROM_CONFIG" "OpenCode config")"
            case "$_ppc_choice" in
              migrate)  ok "Will migrate OpenCode config to port ${PROXY_PORT}." ;;
              use-once) ok "Using port ${PROXY_PORT} for this run only; config keeps ${PORT_FROM_CONFIG}."
                        SKIP_OPENCODE_CONFIG_WRITE=1 ;;
              keep)     PROXY_PORT="$PORT_FROM_CONFIG"; ok "Using port ${PROXY_PORT} from config."
                        # Loop back: recheck collision on the config port.
                        continue ;;
            esac
          fi
        fi
        # Loop back to re-probe the new port (could also be taken).
        ;;
      unknown|*)
        warn "Could not probe ${node} for port ownership (unknown response)."
        warn "  Proceeding optimistically; the server-side check will catch a real collision."
        break ;;
    esac
  done
  if [ "$attempts" -ge "$max_attempts" ]; then
    die "Gave up after ${max_attempts} port-collision rounds."
  fi

  # 3) Bootstrap + open the tunnel.
  remote_bootstrap "$user" "$node"
  open_tunnel "$user" "$node"
  return 0
}

# ============================================================================
# SECTION: 17. CLIENT / TUNNEL MODES + MULTI-CLIENT DISPATCHER (orchestrators)
# ============================================================================
# Multi-client architecture (see AGENTS.md "Multi-client distribution"):
#
# The script supports several AI clients (OpenCode + Claude Code today;
# aider, Cursor, generic OpenAI-compatible to be added). As of v2.0
# the script ships as a SINGLE file (argo-anywhere.sh) -- the symlink-
# per-client distribution from v1.x was removed because cloning the
# repo with core.symlinks=false (Windows default; some CI configs)
# materialised the symlinks as text files, breaking on-node bootstrap
# (audit finding C1). Per-tool selection is now exclusively via the
# --cli-tool flag (commit 2 of v2.0 Phase 1) or the interactive picker.
#
# Each supported client provides a function setup_<name>_cli_tool() that
# (a) ensures the client binary is installed, (b) writes/updates the
# client's config to point at our local proxy, and (c) is idempotent.
# Phase 4 adds setup_aider_cli_tool, setup_cursor_cli_tool, etc., as peers
# of the existing per-tool functions.
#
# The CLI_TOOLS_AVAILABLE array below is the registry: it lists every
# supported AI CLI tool in display order, with a label for the interactive
# picker. Adding a new tool = append a row + write its setup_<name>_cli_tool
# function + add a case arm in do_post_tunnel_for_cli_tool.
#
# Format per row:  <internal_name>|<human_label>
# where internal_name is the value users pass to --cli-tool.
CLI_TOOLS_AVAILABLE=(
  "opencode|OpenCode (sst/opencode-style)"
  "claudecode|Claude Code (Anthropic CLI; uses ANTHROPIC_BASE_URL env)"
  "aider|aider (OpenAI-compatible; ~/.aider.conf.yml + openai-api-base)"
)

# cli_tool_is_known <name>: returns 0 if <name> is in the registry,
# 1 otherwise. Used to validate --cli-tool values.
cli_tool_is_known() {
  local want="$1" entry name
  for entry in "${CLI_TOOLS_AVAILABLE[@]}"; do
    name="${entry%%|*}"
    [ "$name" = "$want" ] && return 0
  done
  return 1
}

# cli_tool_known_names: prints the comma-separated list of registered
# tool names, for use in error messages and --help output.
cli_tool_known_names() {
  local entry name out=""
  for entry in "${CLI_TOOLS_AVAILABLE[@]}"; do
    name="${entry%%|*}"
    out="${out:+${out}, }${name}"
  done
  printf '%s' "$out"
}

# interactive_cli_tool_picker: show CLI_TOOLS_AVAILABLE as a numbered menu
# and echo the chosen tool's internal name. Empty echo on user-aborts
# (Enter/empty); loops on invalid input. Used by mode_client when no
# --cli-tool flag was provided and by the explicit 'setup' subcommand.
#
# NOTE: as of v2.0 the script's invocation-name-based default was removed
# (D1 + D2 in the v2.0 plan). The single canonical filename is
# argo-anywhere.sh; per-tool selection is via --cli-tool or the picker.
interactive_cli_tool_picker() {
  cat >&2 <<EOF

  Supported AI CLI tools:
EOF
  local i=1 entry name label
  for entry in "${CLI_TOOLS_AVAILABLE[@]}"; do
    name="${entry%%|*}"
    label="${entry#*|}"
    printf '    %d) %s\n' "$i" "$label" >&2
    i=$((i+1))
  done
  printf '    %s(future phases will add more)%s\n' "$C_DIM" "$C_OFF" >&2

  while :; do
    local choice
    choice="$(ask "Pick a tool [1-${#CLI_TOOLS_AVAILABLE[@]}, or hit Enter to abort]:" "")"
    if [ -z "$choice" ]; then
      echo ""
      return
    fi
    if [[ "$choice" =~ ^[0-9]+$ ]] \
       && [ "$choice" -ge 1 ] \
       && [ "$choice" -le "${#CLI_TOOLS_AVAILABLE[@]}" ]; then
      entry="${CLI_TOOLS_AVAILABLE[$((choice-1))]}"
      echo "${entry%%|*}"
      return
    fi
    warn "Invalid choice; pick 1-${#CLI_TOOLS_AVAILABLE[@]} or Enter to abort."
  done
}

# Backward-compatibility alias for any future callers; existing internal
# callers in this file are updated below to use the new name directly.
interactive_setup_picker() { interactive_cli_tool_picker "$@"; }

# do_post_tunnel_for_cli_tool <client_name>: per-client setup + post-tunnel
# messaging. Called by mode_client after the tunnel is up. Dispatches to
# the right setup_<name>_cli_tool function based on the registry. Each
# client's branch is responsible for its own install/config + the tail
# log message ("Run: <cmd>" / "Open Settings >...").
#
# Why a dispatcher rather than mode_client doing the if/else inline:
# keeps mode_client's overall flow constant (tunnel up -> per-client
# setup -> summary -> monitor) regardless of how many clients we add.
# Also makes Phase 4 additions (aider/cursor/generic) one-line additions
# here rather than scattered if-branches.
# _post_tunnel_summary: render the full status box UNLESS the caller
# suppressed it. `client`/`connect` want the box (they just established
# the channel). `configure` (which loops over tools against an ALREADY-UP
# channel) sets _SUPPRESS_PER_TOOL_SUMMARY=1 to avoid re-printing the big
# box once per tool -- it prints a single concise confirmation itself.
_post_tunnel_summary() {
  [ "${_SUPPRESS_PER_TOOL_SUMMARY:-0}" = 1 ] && return 0
  gather_summary
  render_summary
}

do_post_tunnel_for_cli_tool() {
  local client="$1"
  case "$client" in
    opencode)
      setup_opencode_cli_tool
      _post_tunnel_summary
      log "OpenCode is installed and configured for this proxy.  Run: opencode"
      log "Other OpenAI-compatible clients can target http://localhost:${PROXY_PORT}/v1"
      log "  with Authorization: Bearer ${ANL_USERNAME}"
      ;;
    claudecode)
      setup_claudecode_cli_tool
      _post_tunnel_summary
      log "Claude Code is installed and configured for this proxy."
      log "  Scope: ${_CLAUDECODE_SCOPE_NAME}"
      if [ "$_CLAUDECODE_SCOPE_PATH" = "$CLAUDECODE_PROJECT_CONFIG" ]; then
        log "  Run from THIS directory ($(pwd)) to pick up the project-scoped settings:"
      else
        log "  Run from any directory:"
      fi
      log "    claude"
      log "  Models default to whatever Claude Code's --model flag resolves;"
      log "  the proxy advertises Anthropic's models at /v1/messages."
      # H7 fix (audit Phase 2b Batch 4): privacy warning. The config
      # written above contains the user's ANL username in clear text
      # under env.ANTHROPIC_AUTH_TOKEN (the proxy uses the username as
      # the bearer token; argo-proxy attributes calls by it). The
      # username is not cryptographically a secret but IS personally-
      # identifying -- leaking it into a public dotfile repo or a
      # shared machine image is a privacy regression. Warn the user
      # explicitly and remind them to gitignore the file.
      warn "Privacy note: ${_CLAUDECODE_SCOPE_PATH} now contains your ANL username"
      warn "  ('${ANL_USERNAME}') in env.ANTHROPIC_AUTH_TOKEN. Don't commit it to a"
      warn "  public dotfile repo or share it widely."
      if [ "$_CLAUDECODE_SCOPE_PATH" = "$CLAUDECODE_PROJECT_CONFIG" ]; then
        log "  (Project scope -- Claude Code's defaults gitignore"
        log "   .claude/settings.local.json automatically; verify your repo's"
        log "   .gitignore covers it.)"
      else
        log "  (Global scope -- if your ~/.claude is tracked in a dotfiles repo,"
        log "   add .claude/settings.json to that repo's .gitignore.)"
      fi
      ;;
    aider)
      setup_aider_cli_tool
      _post_tunnel_summary
      log "aider is installed and configured for this proxy."
      log "  Scope: ${_AIDER_SCOPE_NAME}"
      if [ "$_AIDER_SCOPE_PATH" != "$AIDER_GLOBAL_CONFIG" ]; then
        log "  Run from THIS directory ($(pwd)) to pick up the project-scoped config:"
      else
        log "  Run from any directory:"
      fi
      log "    aider"
      log "  Default model: openai/argo:gpt-4o. To use another, pass the EXACT"
      log "  id from /v1/models with the 'openai/' + 'argo:' prefixes, e.g.:"
      log "    aider --model openai/argo:claude-opus-4.8"
      log "  See served ids:  $(basename "$0") list-models"
      log "  A sibling .aider.model.settings.yml (next to the config) disables"
      log "  the 'temperature' param for reasoning/opus/gpt-5 models -- without"
      log "  it those models return an empty response through argo-proxy."
      log "  Other OpenAI-compatible clients can target http://localhost:${PROXY_PORT}/v1"
      log "    with Authorization: Bearer ${ANL_USERNAME}"
      # H7-class privacy note: the config stores the ANL username in clear
      # text as openai-api-key (argo-proxy uses it as the bearer token).
      warn "Privacy note: ${_AIDER_SCOPE_PATH} now contains your ANL username"
      warn "  ('${ANL_USERNAME}') in openai-api-key. Don't commit it to a public"
      warn "  dotfile/repo or share it widely."
      if [ "$_AIDER_SCOPE_PATH" != "$AIDER_GLOBAL_CONFIG" ]; then
        log "  (Project scope -- aider auto-adds .aider* patterns to .gitignore"
        log "   by default, but verify your repo's .gitignore covers"
        log "   .aider.conf.yml.)"
      fi
      ;;
    # cursor|generic) added in a later phase
    "")
      # No client selected (anywhere mode + user picked empty / aborted).
      # Tunnel is up; user can configure clients manually.
      _post_tunnel_summary
      log "Tunnel is up; no client configured."
      log "Configure any OpenAI-compatible client to target http://localhost:${PROXY_PORT}/v1"
      log "  with Authorization: Bearer ${ANL_USERNAME}"
      ;;
    *)
      die "Unknown client '${client}' (registry mismatch -- this is a script bug)."
      ;;
  esac
}

# mode_tunnel: bring up the SSH tunnel (or the on-node local proxy) and
# block. Does NOT install or configure any client. Useful when the user
# has multiple clients to configure manually or wants a tunnel running
# while they iterate on settings in another terminal.
#
# mode_client: tunnel + per-client setup. The "client" is determined by
# the script's invocation name (default_client_for_invocation), with
# the interactive picker as the fallback when invoked as
# argo-anywhere.sh. The actual setup is delegated to
# do_post_tunnel_for_cli_tool which dispatches to setup_<name>_cli_tool.
#
# These two modes share most of their setup. To avoid drift, they share
# a helper -- _client_common_setup -- that performs identity resolution,
# on-node detection, port-mismatch handling, node selection, ssh
# preflight, and the on-node same-host short-circuit. It returns the
# selected node via stdout (or empty string when the short-circuit fired
# and the caller should bail out without further tunnel work).

# _client_common_setup: shared front-half of mode_client and mode_tunnel.
#
# IMPORTANT: callers must invoke this DIRECTLY (NOT via $()/command
# substitution). The function mutates several script-level globals
# (ANL_USERNAME, ARGO_ANYWHERE_USER, ARGO_ANYWHERE_NO_JUMP,
# ARGO_ANYWHERE_NO_MFA, possibly PROXY_PORT and SKIP_OPENCODE_CONFIG_WRITE,
# plus _PICKED_NODE as the return value). Calling it inside `$( )` would
# run it in a subshell where those mutations evaporate when the subshell
# exits, leaving the parent with unbound globals -- which used to manifest
# as "ANL_USERNAME: unbound variable" errors when the parent then tried
# to use them.
#
# The "return value" is _PICKED_NODE: set to the selected node hostname
# on the standard remote-tunnel path, or set to empty string to signal
# the on-node short-circuit fired (caller should bail out without further
# tunnel work).
#
# The caller passes a flag indicating whether OpenCode config writing is
# desired in the short-circuit branch (mode_client wants it, mode_tunnel
# does not).
_PICKED_NODE=""
_client_common_setup() {
  local with_opencode_setup="${1:-1}"
  ANL_USERNAME="$(resolve_username)"
  # Set both names as script-level globals (NOT exported). Later code in this
  # process reads them as shell variables (e.g. write_opencode_config,
  # write_argoproxy_config), and remote_bootstrap explicitly passes them on
  # the ssh command line rather than relying on env inheritance. Exporting
  # would leak the Argonne username into any child process the user spawns
  # from the same shell session, which is surprising when the laptop's $USER
  # differs from the Argonne username (the common case).
  ARGO_ANYWHERE_USER="$ANL_USERNAME"
  log "Using ANL username: ${ANL_USERNAME}"
  log "Using port: ${PROXY_PORT}  (source: ${PORT_SOURCE})"

  # If we appear to be running ON a compute node already, the script's
  # default assumptions (SSH out via the public jump host, MFA prompt,
  # tunnel back from a laptop) are wrong. Two adjustments, applied as
  # opt-out defaults so power users can still override:
  #   * --no-jump auto-on: from inside the network the jump host is an
  #     unnecessary extra hop (and may not even be reachable from a node).
  #   * --no-mfa auto-on:  Duo doesn't fire for intra-site SSH; switching
  #     off MFA mode skips the multiplex setup we'd never benefit from.
  if [ "$(on_anl_compute_node)" = "yes" ]; then
    if [ -z "${ARGO_ANYWHERE_NO_JUMP:-}" ]; then
      log "Detected ANL compute node ($(this_host_fqdn)); defaulting to --no-jump."
      log "  (Set ARGO_ANYWHERE_NO_JUMP=0 explicitly to keep the jump host.)"
      ARGO_ANYWHERE_NO_JUMP=1
    fi
    if [ -z "${ARGO_ANYWHERE_NO_MFA:-}" ]; then
      log "  Defaulting to --no-mfa (intra-site SSH does not trigger Duo)."
      ARGO_ANYWHERE_NO_MFA=1
    fi
  fi

  # Port-mismatch prompt only matters when we'll be touching the OpenCode
  # config; mode_tunnel skips it because it doesn't write any client config.
  #
  # NOTE (multi-client era): this prompt is currently OpenCode-specific
  # because PORT_FROM_CONFIG only reads the OpenCode config (not the
  # Claude Code settings.json's ANTHROPIC_BASE_URL, nor any future client's
  # equivalent). A user running ONLY argo_claudecode.sh would never see
  # this branch fire (PORT_FROM_CONFIG would be empty); a user running
  # both argo_opencode.sh AND argo_claudecode.sh would see it under the
  # claudecode invocation too, which is acceptable -- the prompt's advice
  # ("OpenCode will fail to connect on the wrong port") is still correct
  # for the OpenCode side. When Phase 4 adds aider/cursor we should
  # generalize PORT_FROM_CONFIG to "port from any known client config"
  # and reword the prompt.
  # B0 fix (Phase 4 pre-work): port-mismatch prompt factored to
  # prompt_port_choice (shared helper); see argo-anywhere.sh Section 7
  # for the helper definition. Previously this site had its own inline
  # prompt that drifted from the auto-port-collision site's version.
  if [ "$with_opencode_setup" = 1 ] \
     && [ -n "$PORT_FROM_CONFIG" ] && [ "$PROXY_PORT" != "$PORT_FROM_CONFIG" ]; then
    local _ppc_choice
    _ppc_choice="$(prompt_port_choice "$PROXY_PORT" "$PORT_FROM_CONFIG" "OpenCode config (~/.config/opencode/config.json baseURL)")"
    case "$_ppc_choice" in
      migrate)  ok "Will migrate OpenCode config to port ${PROXY_PORT}." ;;
      use-once) ok "Using port ${PROXY_PORT} for this run only; config keeps ${PORT_FROM_CONFIG}."
                SKIP_OPENCODE_CONFIG_WRITE=1 ;;
      keep)     PROXY_PORT="$PORT_FROM_CONFIG"
                ok "Using port ${PROXY_PORT} from config (override ignored)." ;;
    esac
  fi

  # Cross-client port-coherence proactive prompt (D-021, B3). The
  # OpenCode-specific block above handles the legacy single-tool case.
  # This block extends coverage to OTHER installed client configs
  # (claudecode global, claudecode project-in-cwd). When any of them
  # disagree with the now-resolved PROXY_PORT, surface the situation
  # and let the user pick canonical via prompt_port_choice. Skip if
  # only OpenCode disagreed (already handled above) or no configs
  # disagree.
  if [ "$with_opencode_setup" = 1 ]; then
    local _disagree_lines _non_oc_lines
    _disagree_lines="$(detect_port_disagreement "$PROXY_PORT" || true)"
    # Filter out the opencode line (handled by the legacy block above).
    _non_oc_lines="$(printf '%s\n' "$_disagree_lines" | awk 'NF && $1 != "opencode"')"
    if [ -n "$_non_oc_lines" ]; then
      warn "Cross-client port disagreement detected (D-021):"
      warn "  Resolved port: ${PROXY_PORT}"
      warn "  Disagreeing client config(s):"
      printf '%s\n' "$_non_oc_lines" | while IFS= read -r _l; do
        warn "    $_l"
      done
      # Pick the first disagreeing port as the alternative for the
      # prompt. The user's [m]igrate choice means "canonicalize on
      # PROXY_PORT" (downstream config writers run later in this
      # invocation and will rewrite the disagreeing configs); [u]se-once
      # means "this run only" (cache write already happened upstream);
      # [k]eep means "switch PROXY_PORT to the alternative" (cache will
      # be updated to match downstream).
      local _alt_port
      _alt_port="$(printf '%s\n' "$_non_oc_lines" | head -n1 | awk '{print $3}')"
      local _ppc_choice2
      _ppc_choice2="$(prompt_port_choice "$PROXY_PORT" "$_alt_port" "other client config(s) (see warnings above)")"
      case "$_ppc_choice2" in
        migrate)
          # B3-amend (Test 8): the original message claimed "will
          # canonicalize all client configs on port N this run" which
          # overpromised. [m]igrate's actual semantic is narrower:
          # the per-tool setup that THIS invocation runs (e.g. the
          # claudecode writer if --cli-tool claudecode was chosen)
          # will write port N to whichever scope file it's targeting.
          # OTHER disagreeing configs across the system (e.g. opencode
          # global when this run is claudecode-only, or claudecode
          # global when this run resolved to claudecode project scope)
          # remain stale. The next 'status' call will still surface
          # them via D-021 passive reporting; the user can run
          # 'client' again with the appropriate --cli-tool / --scope
          # to canonicalize each remaining file. Message corrected
          # accordingly.
          ok "Will write port ${PROXY_PORT} to the config(s) this invocation"
          ok "  touches. Other disagreeing configs surfaced above will"
          ok "  remain stale until canonicalized in a separate 'client' run"
          ok "  with the matching --cli-tool / --scope."
          ;;
        use-once)
          ok "Using port ${PROXY_PORT} for this run only; disagreeing configs untouched."
          # Do not write through to per-tool configs; signal via the
          # same SKIP flag the OpenCode block uses, plus a generic one
          # the per-tool setup_<name> functions can check. For now,
          # only OpenCode honors SKIP_OPENCODE_CONFIG_WRITE; future
          # per-tool flags can follow the same pattern.
          SKIP_CROSS_CLIENT_CONFIG_WRITES=1
          ;;
        keep)
          PROXY_PORT="$_alt_port"
          # Also rewrite the cache so subsequent runs use the alternative.
          write_port_cache "$PROXY_PORT" || true
          ok "Switched to port ${PROXY_PORT} from disagreeing config (cache updated)."
          ;;
      esac
    fi
  fi

  # Order under MFA: pick the node FIRST, then open the mux master against
  # that node. (Cannot open against ANL_JUMP -- jump host is shell-restricted.)
  # Order under --no-mfa: preflight against the jump host first (BatchMode
  # test is fast and gives clean SSH-key error message), then pick node.
  local node
  if mfa_enabled; then
    node="$(pick_node "$ANL_USERNAME")"
    log "Selected node: ${node}" >&2
    ssh_preflight "$ANL_USERNAME" "$node"
  else
    ssh_preflight "$ANL_USERNAME"
    node="$(pick_node "$ANL_USERNAME")"
    log "Selected node: ${node}" >&2
  fi

  # On-node short-circuit. If the picked node is THIS host, the SSH tunnel
  # is unnecessary (and would collide with the local argo-proxy on the same
  # port). Run mode_server inline to start argo-proxy locally; do client
  # setup if the caller asked for it; print the appropriate "all set" msg;
  # echo empty string so the caller knows to return without further work.
  if host_is_target "$node"; then
    log "Selected node is this host ($(this_host_fqdn)); skipping SSH tunnel."
    log "  argo-proxy will be started here directly; no SSH bootstrap needed."
    # _MODE_SERVER_INPROC=1 tells mode_server to RETURN (not exit) after
    # its tee/log re-exec finishes, so we can continue with the OpenCode
    # setup + status box + post-setup messages below. Without this, the
    # exit at the end of mode_server's logging branch would kill the
    # script silently after the bootstrap reuse line, leaving the user
    # at a fresh shell prompt with no client setup performed.
    _MODE_SERVER_INPROC=1 ARGO_ANYWHERE_USER="$ANL_USERNAME" ARGO_ANYWHERE_PORT="$PROXY_PORT" mode_server
    if curl -fsS --max-time 5 "http://localhost:${PROXY_PORT}/health" >/dev/null 2>&1; then
      ok "argo-proxy is live at http://localhost:${PROXY_PORT}/v1 (no tunnel needed; this host runs the proxy)."
    else
      die "argo-proxy did not become reachable on http://localhost:${PROXY_PORT}/health after server bootstrap."
    fi
    if [ "$with_opencode_setup" = 1 ]; then
      setup_opencode_cli_tool
    fi
    gather_summary
    render_summary
    if [ "$with_opencode_setup" = 1 ]; then
      log "OpenCode is installed and configured for this proxy.  Run: opencode"
    fi
    log "Other OpenAI-compatible clients can target http://localhost:${PROXY_PORT}/v1"
    log "  with Authorization: Bearer ${ANL_USERNAME}"
    log "(no foreground tunnel to keep alive; argo-proxy stays running under"
    log "  screen/tmux/nohup; use '$(basename "$0") clean' to stop everything.)"
    # P3 fix: cache the node only AFTER the on-node bootstrap succeeded.
    write_node_cache "$node"
    _PICKED_NODE=""  # signal short-circuit (caller should bail out)
    return 0
  fi

  _PICKED_NODE="$node"
}

# mode_list_tools: print the supported AI CLI tools, one per line, in
# the same format the picker uses. Standalone subcommand so users (and
# scripts) can introspect the registry without invoking 'client' or
# 'setup'. Output is intentionally simple (no box drawing) so it's
# easy to grep/parse.
mode_list_tools() {
  printf '%s\n' "Supported AI CLI tools (pass to --cli-tool):"
  local entry name label
  for entry in "${CLI_TOOLS_AVAILABLE[@]}"; do
    name="${entry%%|*}"
    label="${entry#*|}"
    printf '  %-12s  %s\n' "$name" "$label"
  done
}

# mode_tunnel: open the SSH tunnel (or local proxy on a compute node) and
# enter the foreground monitor loop. No client setup. Useful for power users
# managing multiple clients themselves, or for keeping a tunnel alive across
# multiple terminal sessions where each one configures a different client.
# channel_is_up: return 0 if the shared channel (local tunnel -> remote
# argo-proxy) is already answering on $PROXY_PORT, 1 otherwise. Probes
# /health directly rather than trusting the port cache alone, so a stale
# cache (cache says port N but nothing is listening) reads as "down".
# Used by the level-2 verbs (configure / run) to DETECT an existing
# channel established by a separate `connect` window (D-024 / D-e).
channel_is_up() {
  curl -fsS --max-time 3 "http://localhost:${PROXY_PORT}/health" >/dev/null 2>&1
}

mode_tunnel() {
  # Call directly (NOT via $()): _client_common_setup mutates several
  # script-level globals (ANL_USERNAME, ARGO_ANYWHERE_USER, the auto-defaulted
  # NO_JUMP/NO_MFA env, possibly PROXY_PORT). A subshell capture would make
  # those mutations vanish and trip 'unbound variable' here. The "return"
  # value is _PICKED_NODE: empty signals the on-node short-circuit fired.
  _client_common_setup 0
  [ -z "$_PICKED_NODE" ] && return 0
  local node="$_PICKED_NODE"

  # ensure_or_reuse_tunnel handles all the collision detection (local
  # self-reuse, remote multi-user prompt) and on success either opens a
  # new tunnel or reuses an existing healthy one.
  local rc=0
  ensure_or_reuse_tunnel "$ANL_USERNAME" "$node" || rc=$?
  # P3 fix: cache the node only AFTER ensure_or_reuse_tunnel returned
  # successfully (rc=0 = we own the tunnel; rc=2 = we're reusing an
  # external-healthy listener). On a non-success rc the script has
  # already die'd, so we won't reach here.
  write_node_cache "$node"
  gather_summary
  render_summary
  log "Channel is up; no client configured (this is '${_INVOKED_MODE:-tunnel}' mode)."
  log "Point any OpenAI-compatible client at http://localhost:${PROXY_PORT}/v1"
  log "  with Authorization: Bearer ${ANL_USERNAME}"
  if [ "$rc" -eq 2 ]; then
    log "(external listener; not entering monitor loop. Tunnel/proxy is not"
    log "  managed by this script invocation.)"
    return 0
  fi
  monitor_tunnel_loop "$ANL_USERNAME" "$node"
}

mode_client() {
  # First-run bootstrap (per PLAN.md D-023): if the canonical install
  # at $ARGO_INSTALL_DIR doesn't exist yet, copy ourselves there + write
  # the env file. Idempotent no-op on subsequent runs. Doesn't fire on
  # compute nodes (the on-node short-circuit doesn't benefit from a
  # laptop-side canonical install) or when we're already running from
  # the canonical install. See maybe_bootstrap_canonical_install for the
  # full skip-conditions list.
  maybe_bootstrap_canonical_install

  # Determine the CLI tool to set up. As of v2.0 (D1+D2), tool selection
  # is exclusively explicit:
  #   1. CLI_TOOL_OVERRIDE (set by --cli-tool flag in main())
  #   2. interactive_cli_tool_picker (when --cli-tool not supplied OR when
  #      the 'setup' subcommand forces the picker via FORCE_PICKER=1)
  #
  # The pre-v2.0 invocation-name-based default (argo_opencode.sh ->
  # opencode, etc.) was removed when symlinks were dropped. There is now
  # ONE canonical filename (argo-anywhere.sh); per-tool selection is
  # always explicit via flag or picker. See docs/AUDIT_2026-05-12.md.
  local chosen_client=""
  if [ "${FORCE_PICKER:-0}" = 1 ]; then
    chosen_client="$(interactive_cli_tool_picker)"
  elif [ -n "${CLI_TOOL_OVERRIDE:-}" ]; then
    chosen_client="$CLI_TOOL_OVERRIDE"
  else
    chosen_client="$(interactive_cli_tool_picker)"
  fi
  if [ -z "$chosen_client" ]; then
    die "No CLI tool picked; aborting. Pass --cli-tool <name> or pick from the menu."
  fi
  # Expose to cleanup_local (audit finding N1) so the Ctrl+C exit
  # summary can suggest the exact reuse command (--cli-tool <name>).
  _INVOKED_CLI_TOOL="$chosen_client"

  # Call directly (NOT via $()): see comment in mode_tunnel for why.
  _client_common_setup 1
  [ -z "$_PICKED_NODE" ] && return 0
  local node="$_PICKED_NODE"

  # Standard remote-tunnel flow:
  #   1. ensure_or_reuse_tunnel handles bootstrap + tunnel (or reuses an
  #      existing healthy tunnel; or prompts for collision resolution)
  #   2. configure the chosen client (do_post_tunnel_for_cli_tool dispatches
  #      to the right setup_<name>_cli_tool function and prints its
  #      post-setup messages)
  #   3. block in the foreground monitor + reconnect loop (unless ext-healthy)
  local rc=0
  ensure_or_reuse_tunnel "$ANL_USERNAME" "$node" || rc=$?
  # P3 fix: cache the node only AFTER ensure_or_reuse_tunnel returned
  # successfully (rc=0 = we own the tunnel; rc=2 = we're reusing an
  # external-healthy listener). On a non-success rc the script has
  # already die'd, so we won't reach here.
  write_node_cache "$node"
  do_post_tunnel_for_cli_tool "$chosen_client"
  if [ "$rc" -eq 2 ]; then
    log "(external listener; not entering monitor loop. The proxy is reachable"
    log "  but not managed by this script invocation.)"
    return 0
  fi
  monitor_tunnel_loop "$ANL_USERNAME" "$node"
}

# ============================================================================
# SECTION: 17b. LIFECYCLE VERBS -- connect / configure / run (D-024)
# ============================================================================
# Splits the three levels argo-anywhere manages into explicit verbs so a
# user can hold the shared channel in one window (connect) and freely
# configure / run clients in others. `client` / `setup` / `tunnel` remain
# as fused one-shot fallbacks (backward compat). See PLAN.md D-024 +
# notes/impl_lifecycle_commands.md.
#
#   connect   = Level 1: ensure the channel (tunnel + remote proxy),
#               then hold the foreground monitor. Same behavior as
#               `tunnel`; friendlier name. `tunnel` retained as an alias.
#   configure = Level 2: install + write config for one-or-more tools
#               against an EXISTING channel. Detects the channel via
#               /health; fail-loud-with-hint if absent (--ensure brings
#               it up). Does NOT enter the monitor loop (the channel is
#               the connect window's).
#   run       = Level 2+3: configure ONE tool, then exec the client so
#               the user drops straight into a session. Brings the channel
#               up if missing (prompt, or --ensure / -y to auto-confirm).

# mode_connect: Level 1. Identical to mode_tunnel (which already does
# exactly "ensure the channel + monitor"); connect is the primary,
# user-facing name for that operation. Kept as a one-line delegator so
# the two names never drift.
mode_connect() {
  mode_tunnel
}

# _configure_ensure_channel_or_die: shared precondition for configure/run.
# If the channel is up, return 0. Else: with --ensure (or run's implied
# ensure), bring it up via the full client-common flow + tunnel; without
# it, die with a hint pointing at `connect`.
#
# Args: $1 = "1" to auto-ensure (bring up if missing), "0" to require.
# On successful ensure, sets _CONFIGURE_ENSURED_NODE (the picked node) so
# the caller can decide whether to monitor. On detect-only success (channel
# already up) leaves it empty.
_CONFIGURE_ENSURED_NODE=""
_configure_ensure_channel_or_die() {
  local auto_ensure="$1"
  _CONFIGURE_ENSURED_NODE=""

  if channel_is_up; then
    ok "Channel is up on http://localhost:${PROXY_PORT} (reusing it)."
    return 0
  fi

  if [ "$auto_ensure" != "1" ]; then
    err "No argo-anywhere channel is answering on http://localhost:${PROXY_PORT}/health."
    err ""
    err "The '${_INVOKED_MODE}' step configures/runs a client against an EXISTING"
    err "channel; it does not open one itself. To bring the channel up:"
    err ""
    err "  In another window:   $(basename "$0") connect"
    err "  Or one-shot here:    $(basename "$0") ${_INVOKED_MODE} <tool> --ensure"
    err ""
    die "Channel not up (run 'connect' first, or pass --ensure)."
  fi

  # --ensure: bring the channel up in-process using the same path as
  # mode_tunnel (level 1), then continue. We do NOT monitor here; the
  # caller (configure) returns after configuring, and run execs the
  # client. Under --ensure the tunnel is owned by the mux master (which
  # persists via ControlPersist), so it survives this process exiting.
  log "Channel not up; --ensure requested -> bringing it up..."
  _client_common_setup 0
  [ -z "$_PICKED_NODE" ] && return 0   # on-node short-circuit
  local node="$_PICKED_NODE"
  local rc=0
  ensure_or_reuse_tunnel "$ANL_USERNAME" "$node" || rc=$?
  write_node_cache "$node"
  _CONFIGURE_ENSURED_NODE="$node"
  return 0
}

# mode_configure: Level 2. Install + configure one-or-more tools against
# the existing channel. Tool names come from CONFIGURE_TOOLS_ARGV
# (positional args) OR --cli-tool OR the interactive picker (single).
mode_configure() {
  maybe_bootstrap_canonical_install

  # Resolve the tool list: positional args win; else --cli-tool; else picker.
  local tools=""
  if [ -n "${CONFIGURE_TOOLS_ARGV:-}" ]; then
    tools="$CONFIGURE_TOOLS_ARGV"
  elif [ -n "${CLI_TOOL_OVERRIDE:-}" ]; then
    tools="$CLI_TOOL_OVERRIDE"
  else
    local picked; picked="$(interactive_cli_tool_picker)"
    [ -z "$picked" ] && die "No CLI tool picked; aborting. Pass one or more tool names, --cli-tool <name>, or pick from the menu."
    tools="$picked"
  fi

  # Username is needed by the writers; resolve without opening a tunnel.
  ANL_USERNAME="$(resolve_username)"
  ARGO_ANYWHERE_USER="$ANL_USERNAME"
  log "Using ANL username: ${ANL_USERNAME}"
  log "Using port: ${PROXY_PORT}  (source: ${PORT_SOURCE})"

  # Precondition: the channel must exist (or --ensure brings it up).
  _configure_ensure_channel_or_die "${CONFIGURE_ENSURE:-0}"

  # Configure each requested tool. do_post_tunnel_for_cli_tool runs the
  # tool's setup + tail messages. It does NOT monitor, which is exactly
  # what configure wants (the channel belongs to the connect window / mux
  # master). Suppress the per-tool full status box: re-rendering the big
  # connection/models/paths box once per tool against an already-up
  # channel is noise (Test 2 finding). configure prints one concise
  # channel line at the end instead.
  local t
  for t in $tools; do
    if ! cli_tool_is_known "$t"; then
      die "configure: unknown tool '${t}'. Known tools: $(cli_tool_known_names)."
    fi
  done
  local _SUPPRESS_PER_TOOL_SUMMARY=1
  for t in $tools; do
    log ""
    log "==> configure ${t}"
    _INVOKED_CLI_TOOL="$t"
    do_post_tunnel_for_cli_tool "$t"
  done

  log ""
  ok "Configured: ${tools}."
  ok "  Channel: http://localhost:${PROXY_PORT}  (healthy; owned by your 'connect' window / mux master)"
  log "  Start a client:  $(basename "$0") run <tool>   (or just run the tool directly)"
}

# mode_run: Level 2+3. Configure exactly one tool, then exec it so the
# user drops into a session. Brings the channel up if missing (run implies
# --ensure with a prompt; -y / --ensure auto-confirm).
mode_run() {
  maybe_bootstrap_canonical_install

  # Exactly one tool for run (we exec it).
  local tool=""
  if [ -n "${CONFIGURE_TOOLS_ARGV:-}" ]; then
    # take the first; warn if more than one was given
    tool="${CONFIGURE_TOOLS_ARGV%% *}"
    if [ "$tool" != "$CONFIGURE_TOOLS_ARGV" ]; then
      warn "run takes a single tool; using '${tool}' and ignoring the rest."
    fi
  elif [ -n "${CLI_TOOL_OVERRIDE:-}" ]; then
    tool="$CLI_TOOL_OVERRIDE"
  else
    tool="$(interactive_cli_tool_picker)"
    [ -z "$tool" ] && die "No CLI tool picked; aborting. Pass a tool name, --cli-tool <name>, or pick from the menu."
  fi
  cli_tool_is_known "$tool" || die "run: unknown tool '${tool}'. Known tools: $(cli_tool_known_names)."

  ANL_USERNAME="$(resolve_username)"
  ARGO_ANYWHERE_USER="$ANL_USERNAME"
  log "Using ANL username: ${ANL_USERNAME}"
  log "Using port: ${PROXY_PORT}  (source: ${PORT_SOURCE})"

  # run brings the channel up if missing. Default: prompt (unless -y or
  # --ensure). If the user declines, fall back to the require-existing
  # path (which dies with the connect hint).
  local do_ensure="${CONFIGURE_ENSURE:-0}"
  if [ "$do_ensure" != "1" ] && ! channel_is_up; then
    if [ "${CLEAN_ASSUME_YES:-0}" = 1 ]; then
      do_ensure=1
    else
      local ans; ans="$(ask "No channel on :${PROXY_PORT}. Bring it up now? [Y/n]:" "Y")"
      case "$ans" in n|N|no|No) do_ensure=0 ;; *) do_ensure=1 ;; esac
    fi
  fi
  _configure_ensure_channel_or_die "$do_ensure"

  # Suppress the full status box: run is configure + launch, so it should
  # be at least as quiet as configure -- and we're about to hand off to
  # the client's own UI, so a big box right before it is noise (Test 5
  # finding). The concise "Configured" tail + the tool's own launch
  # message are enough.
  local _SUPPRESS_PER_TOOL_SUMMARY=1
  _INVOKED_CLI_TOOL="$tool"
  do_post_tunnel_for_cli_tool "$tool"

  # Resolve the client binary name (tool token == binary for our set,
  # except claudecode -> 'claude').
  local bin="$tool"
  [ "$tool" = "claudecode" ] && bin="claude"

  if ! command -v "$bin" >/dev/null 2>&1; then
    warn "run: '${bin}' is not on PATH in this shell (it may need a fresh"
    warn "  shell to pick up the installer's PATH edit). Configuration is done;"
    warn "  open a new terminal and run '${bin}'."
    return 0
  fi
  log ""
  ok "Launching ${bin} ..."
  exec "$bin"
}

# ============================================================================
# SECTION: 18. SERVER MODE (runs on the ANL compute node, idempotent)
# ============================================================================
# Validates Python>=3.10 + venv + argo-proxy 'serve' subcommand; (re)creates
# venv if needed; writes ~/.config/argoproxy/config.yaml; verifies any existing
# listener is OURS before reusing; starts argo-proxy in screen/tmux/nohup.

# argo-proxy YAML config writer (server side). Uses the port and username
# the client passed in via env (ARGO_ANYWHERE_USER / ARGO_ANYWHERE_PORT).
# Same writer-contract caveat as write_opencode_config: handle_config_file
# only passes the dest path, so we resolve the user from env.
#
# Ownership policy (preserve-unknown-keys writer)
# -----------------------------------------------
# When called by handle_config_file, the writer's job is to produce the
# CANDIDATE file that diffing/merging is done against. Two cases:
#
#   (1) No existing config at the user's real path
#       -> emit the full 6-key default file (config_version, user, host,
#          port, verbose, argo_base_url) so a fresh install is usable.
#
#   (2) An existing config exists (regardless of where it came from --
#       the legacy start_argo_tunnel.sh, a manual edit, or a previous
#       run of this script)
#       -> read the existing file, override ONLY the 4 keys we strictly
#          own, preserve everything else verbatim. Owned keys:
#            config_version  -- argo-proxy schema version we target
#            user            -- identity from the client; must match
#            host            -- always 127.0.0.1 (loopback only;
#                               0.0.0.0 would expose the proxy to other
#                               compute-node users)
#            port            -- must match what the client tunnels to;
#                               the server-side cfg-port-vs-PROXY_PORT
#                               check (just before launching argo-proxy)
#                               enforces this and refuses to launch on
#                               a mismatch (else argo-proxy would bind
#                               the wrong port and the client polls in vain)
#          NOT owned (preserved from existing if present):
#            verbose, argo_base_url, argo_url, argo_stream_url,
#            argo_embedding_url, concurrent_downloads,
#            connection_test_timeout, image_timeout, max_payload_size,
#            enable_payload_control, resolve_overrides, and any other
#            key argo-proxy may add in the future.
#
# Implementation: case (2) requires YAML parsing. We use Python (PyYAML),
# which argo-proxy depends on, so it's always present in the venv. We pick
# the venv python if available, falling back to the system python3.
# IMPORTANT: handle_config_file calls this writer with a TEMP destination
# path (the "proposed" file for diffing), NOT the user's real config path.
# We must therefore look up the existing config at its canonical location
# explicitly, not rely on $dest.
write_argoproxy_config() {
  local dest="$1"
  local user="${ARGO_ANYWHERE_USER:-${ANL_USERNAME:-}}"
  [ -n "$user" ] || die "write_argoproxy_config: no username available (ARGO_ANYWHERE_USER unset)"

  local real_cfg="${HOME}/.config/argoproxy/config.yaml"

  # P2 fix (audit): default verbose=false, opt-in via --verbose-server
  # (which sets ARGO_ANYWHERE_VERBOSE_SERVER=1, forwarded by
  # remote_bootstrap). Pre-fix default was verbose=true, which made
  # argo-proxy log every request body (prompts) and response body to
  # its stdout, captured in ~/.argo-anywhere.server.log on the compute
  # node. The Argo gateway itself doesn't retain prompts, but the
  # local verbose log on the user's compute node is created by
  # argo-proxy on their account; the gateway's privacy guarantee
  # doesn't propagate to the user's own log file.
  local verbose_value="false"
  if [ -n "${ARGO_ANYWHERE_VERBOSE_SERVER:-}" ]; then
    verbose_value="true"
  fi

  # Case 1: no existing file -- emit defaults.
  if [ ! -f "$real_cfg" ]; then
    cat > "$dest" <<EOF
config_version: "3"
user: "${user}"
host: 127.0.0.1
port: ${PROXY_PORT}
verbose: ${verbose_value}
argo_base_url: "https://apps.inside.anl.gov/argoapi"
EOF
    return
  fi

  # Case 2: existing file -- merge via PyYAML to preserve user-owned keys.
  # Pick the venv python if available so we use the same PyYAML argo-proxy
  # itself depends on. Fall back to system python3 only if the venv python
  # is unavailable.
  local pyexe=""
  local venv_dir; venv_dir="$(eval echo "$VENV_PATH" 2>/dev/null || true)"
  if [ -n "$venv_dir" ] && [ -x "${venv_dir}/bin/python" ]; then
    pyexe="${venv_dir}/bin/python"
  elif command -v python3 >/dev/null 2>&1; then
    pyexe="python3"
  fi

  # M9 fix (audit Phase 2d, Option A per user choice): die hard if no
  # python available for YAML merge. Pre-fix the no-pyexe branch wrote
  # a hardcoded 6-key defaults file, silently dropping any user-owned
  # keys (argo_embedding_url, concurrent_downloads, max_payload_size,
  # etc.) when the user picked [b]ackup at the prompt. The fallback
  # was actively dangerous and the warn message could be missed under
  # time pressure. Now: refuse to write the merge tempfile if we can't
  # do the merge safely; user must install python3 (or the venv must
  # be reachable) before re-running.
  if [ -z "$pyexe" ]; then
    err "write_argoproxy_config: no python available for safe YAML merge."
    err "  An existing config exists at ${real_cfg} with possibly user-owned"
    err "  keys (argo_embedding_url, concurrent_downloads, etc.) that the"
    err "  hardcoded-defaults fallback would silently drop on [b]ackup."
    err ""
    err "Recovery: install python3 + PyYAML, then re-run. On a typical"
    err "  ANL compute node, the script's argo-proxy venv (\${HOME}/argovenv)"
    err "  has both; if it's missing or stale, force a fresh install:"
    err "    bash $(basename "$0") --force-reinstall server"
    die "Refusing to write argo-proxy config without safe YAML merge."
  fi

  # Try the merge. PyYAML is required (M9 die-hard); existing-config
  # parse failures also die-hard rather than silently writing defaults.
  #
  # Exit codes from the Python heredoc:
  #   0 -> success
  #   2 -> PyYAML missing in this python (die-hard per M9; install via pip)
  #   3 -> existing config parses to non-dict (corrupt or non-YAML content)
  #   4 -> unhandled exception during yaml.safe_load (file unreadable,
  #        syntax error, etc.)
  #
  # P2 fix: pass the verbose value as a 5th arg; P2 amendment overwrites
  # rather than setdefault for the security-defaulted verbose key.
  local _py_rc=0
  "$pyexe" - "$real_cfg" "$dest" "$user" "$PROXY_PORT" "$verbose_value" <<'PYEOF' 2>/dev/null || _py_rc=$?
import sys
try:
    import yaml
except ImportError:
    sys.exit(2)
src, dst, user, port, verbose_str = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4]), sys.argv[5]
verbose_default = (verbose_str == "true")
try:
    with open(src) as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        sys.exit(3)
except Exception:
    sys.exit(4)
# Override the 4 keys we own. Everything else is preserved verbatim.
data['config_version'] = "3"
data['user'] = user
data['host'] = "127.0.0.1"
data['port'] = port
# P2 fix amendment (2026-05-14): always overwrite `verbose` with the
# script's chosen value. The original P2 fix used setdefault to
# "preserve user's explicit choice", but that was wrong: the
# pre-P2 script wrote verbose: true automatically (no user input
# involved), so on first upgrade the existing `verbose: true` would
# be preserved and the P2 default (false) would silently NOT take
# effect -- the security regression the fix was meant to close
# stays open. Discovered during Phase 2b live test #1 on a real
# upgrader's config. The user's "explicit choice" channel is the
# --verbose-server CLI flag (or ARGO_ANYWHERE_VERBOSE_SERVER env);
# the file content is not a user-input channel for this key.
data['verbose'] = verbose_default
# argo_base_url is genuinely user-customizable (alternate Argo
# endpoints / dev environments); preserve any existing value.
data.setdefault('argo_base_url', "https://apps.inside.anl.gov/argoapi")
with open(dst, 'w') as f:
    yaml.safe_dump(data, f, default_flow_style=False, sort_keys=False)
PYEOF

  case "$_py_rc" in
    0) ;;  # success
    2)
      err "write_argoproxy_config: PyYAML is not available in ${pyexe}."
      err "  We need PyYAML to safely merge the new config with your"
      err "  existing ${real_cfg} (preserving user-owned keys like"
      err "  argo_embedding_url, concurrent_downloads, etc.)."
      err ""
      err "Recovery: install PyYAML, then re-run."
      err "  In the venv: ${pyexe} -m pip install pyyaml"
      err "  System-wide (Linux): sudo apt install python3-yaml"
      err "  Or: pip install --user pyyaml"
      die "Refusing to write argo-proxy config without PyYAML for safe merge."
      ;;
    3)
      err "write_argoproxy_config: existing config at ${real_cfg} parses"
      err "  to non-dict (top-level YAML is not an object). Refusing to"
      err "  merge -- doing so would silently destroy the file content."
      err ""
      err "Recovery: inspect the file (\`cat ${real_cfg}\`) and either fix"
      err "  it to be a YAML object, OR move it aside (\`mv ${real_cfg}"
      err "  ${real_cfg}.broken.\$(date +%s)\`) and re-run; the writer will"
      err "  create a fresh file from defaults."
      die "Refusing to overwrite a malformed argo-proxy config."
      ;;
    4)
      err "write_argoproxy_config: existing config at ${real_cfg} could"
      err "  not be parsed by PyYAML (file unreadable, YAML syntax error,"
      err "  or other I/O error). Refusing to merge."
      err ""
      err "Recovery: try \`${pyexe} -c \"import yaml; print(yaml.safe_load(open('${real_cfg}')))\"\`"
      err "  to see the exact parse error. Then either fix the file or"
      err "  move it aside (\`mv ${real_cfg} ${real_cfg}.broken.\$(date +%s)\`)"
      err "  and re-run."
      die "Refusing to overwrite an unparseable argo-proxy config."
      ;;
    *)
      die "write_argoproxy_config: python3 heredoc exited with rc=${_py_rc} (unexpected)."
      ;;
  esac
}

# ----------------------------------------------------------------------------
# ensure_argoproxy_installed: idempotent install-or-validate of the
# server-side Python venv + argo-proxy package. Runs on the compute node
# (or, via the on-node short-circuit in _client_common_setup, on the
# local machine if the user happens to be running the script there).
#
# Steps:
#   1. system python3 >= 3.10
#   2. venv at $VENV_PATH ($HOME/argovenv): create-or-validate; recreate
#      if missing, broken, or python < 3.10
#   3. argo-proxy in the venv: install if `--version` or `serve --help`
#      fails; otherwise leave alone (lossless: pre-existing argo-proxy
#      keeps its installed version unless the binary itself is broken)
#
# Honors ARGO_ANYWHERE_FORCE_REINSTALL=1: wipes the venv first.
#
# Returns 0 on success, non-zero on any unrecoverable step. Calls die()
# on conditions that prevent recovery without user action (missing
# python3, python too old, argo-proxy still broken after install).
#
# CALLERS:
#   * mode_server (server-side bootstrap; the historical caller)
#   * update_argoproxy_component (the new `update argoproxy` flow;
#     calls this when --force-reinstall is set OR when argo-proxy is
#     entirely missing; otherwise prefers the lossless in-place upgrade
#     path via `argo-proxy update install` or `pip install --upgrade`)
#
# DOES NOT touch:
#   * ~/.config/argoproxy/config.yaml (that's the config writer's job)
#   * running argo-proxy processes (caller is responsible for restart
#     semantics if a binary upgrade requires it; `update argoproxy`
#     defers to /refresh which is enough to pick up new model entries
#     in the registry without bouncing the proxy)
ensure_argoproxy_installed() {
  # 1) Python 3.10+ on the system path (used to build the venv if missing).
  command -v python3 >/dev/null 2>&1 || die "python3 not found on $(hostname)."
  local pyver; pyver="$(python3 -c 'import sys;print("%d.%d"%sys.version_info[:2])')"
  case "$pyver" in
    3.1[0-9]|3.[2-9][0-9]|[4-9].*) ok "system python3 ${pyver} OK" ;;
    *) die "argo-proxy needs Python 3.10+; system python3 is ${pyver}." ;;
  esac

  # 2) venv: optionally wipe, then create or validate.
  local venv; venv="$(eval echo "$VENV_PATH")"
  local legacy_venv; legacy_venv="$(eval echo "$LEGACY_VENV_PATH")"

  # Legacy v1.x detection: warn if the pre-rename venv ($HOME/agovenv) is
  # still on disk. Don't auto-migrate -- the user may have a working
  # argo-proxy in there serving traffic. We just log and let `clean`
  # remove it (or the user can rm -rf manually).
  if [ -d "$legacy_venv" ] && [ "$legacy_venv" != "$venv" ]; then
    warn "Found legacy v1.x venv at ${legacy_venv} (pre-rename name)."
    warn "  v2.0 uses ${venv}; the old one is unused but still on disk."
    warn "  To reclaim disk space:  rm -rf ${legacy_venv}"
    warn "  ('clean' also handles this; this WARN fires once per server bootstrap.)"
  fi

  if [ -n "${ARGO_ANYWHERE_FORCE_REINSTALL:-}" ] && [ -d "$venv" ]; then
    warn "ARGO_ANYWHERE_FORCE_REINSTALL set; removing existing venv at ${venv}..."
    rm -rf "$venv"
  fi

  local need_recreate=0
  if [ ! -x "${venv}/bin/python" ]; then
    need_recreate=1
  else
    # Validate the venv's own python (not the system one) is 3.10+ AND alive.
    local vpv; vpv="$("${venv}/bin/python" -c 'import sys;print("%d.%d"%sys.version_info[:2])' 2>/dev/null || true)"
    if [ -z "$vpv" ]; then
      warn "venv at ${venv} exists but its python is broken; recreating."
      need_recreate=1
    else
      case "$vpv" in
        3.1[0-9]|3.[2-9][0-9]|[4-9].*) ok "venv python ${vpv} OK (${venv})" ;;
        *) warn "venv python is ${vpv} (need >=3.10); recreating ${venv}."; need_recreate=1 ;;
      esac
    fi
  fi
  if [ "$need_recreate" -eq 1 ]; then
    if [ -d "$venv" ]; then rm -rf "$venv"; fi
    log "Creating venv at ${venv}..."
    python3 -m venv "$venv"
    "${venv}/bin/pip" install --upgrade pip >/dev/null
    ok "venv created: ${venv}"
  fi

  # 3) argo-proxy installed AND has the 'serve' subcommand we need.
  local need_install=0
  if ! "${venv}/bin/argo-proxy" --version >/dev/null 2>&1; then
    need_install=1
  elif ! "${venv}/bin/argo-proxy" serve --help >/dev/null 2>&1; then
    warn "argo-proxy installed but 'serve --help' fails (likely too old); upgrading."
    need_install=1
  fi
  if [ "$need_install" -eq 1 ]; then
    log "Installing/upgrading argo-proxy in ${venv}..."
    "${venv}/bin/pip" install --upgrade pip >/dev/null
    "${venv}/bin/pip" install --upgrade argo-proxy
    "${venv}/bin/argo-proxy" serve --help >/dev/null 2>&1 \
      || die "argo-proxy 'serve' subcommand still missing after install. Inspect ${venv}/bin/argo-proxy."
  fi
  ok "argo-proxy: $("${venv}/bin/argo-proxy" --version 2>&1 | head -n1)"
}

mode_server() {
  # Resolve identity (username + port) from one of three sources, in order:
  #   1. env / canonical (set by 'client' over SSH; never missing in that
  #      path) and/or legacy ANL_USERNAME / PROXY_PORT for backward compat
  #   2. existing ~/.config/argoproxy/config.yaml -- the most authoritative
  #      answer for "what argo-proxy is already configured to be"
  #   3. ~/.config/argo_anywhere/user (script's cache) for the username,
  #      $PROXY_PORT_DEFAULT for the port
  #
  # If we ended up resolving from (2) or (3) (i.e. neither env had a value
  # to begin with), the user invoked us standalone -- which is a real
  # supported workflow ("leave a proxy on this node for any client to
  # reach"). Show what we resolved and ask for confirmation before
  # starting anything.
  #
  # Capture whether env had values BEFORE we start filling defaults, so
  # we can decide later whether to prompt. Also gate on the tee'd-re-exec
  # sentinel (_ARGO_ANYWHERE_REEXEC; renamed from ARGO_ANYWHERE_LOGGING
  # in Phase 2e per audit I2): once we're past the tee re-exec, the
  # work is being done in a subprocess. Even though we export the
  # resolved values below to suppress the second-pass prompt, this is a
  # belt-and-braces guard against forgetting that contract in some
  # future refactor. The variable name now reflects its actual purpose
  # ("we're inside the tee re-exec subprocess") rather than the
  # vague-sounding "_LOGGING" it carried over from Phase 1 D4 rename.
  local user_was_in_env="${ARGO_ANYWHERE_USER:+1}"
  local port_was_in_env="${ARGO_ANYWHERE_PORT:+1}"
  local already_logged="${_ARGO_ANYWHERE_REEXEC:+1}"

  # Canonical names; fall back to legacy aliases for one cycle so direct
  # 'bash argo-anywhere.sh server' invocations don't break for anyone who
  # was setting ANL_USERNAME/PROXY_PORT manually (or pre-v2 code that set
  # ARGO_OPENCODE_*, which is also honoured via the legacy promotion in
  # section 6).
  : "${ARGO_ANYWHERE_USER:=${ANL_USERNAME:-}}"
  : "${ARGO_ANYWHERE_PORT:=${PROXY_PORT:-}}"

  # Source 2: ~/.config/argoproxy/config.yaml
  if [ -z "${ARGO_ANYWHERE_USER:-}" ] || [ -z "${ARGO_ANYWHERE_PORT:-}" ]; then
    local cfg="${HOME}/.config/argoproxy/config.yaml"
    if [ -f "$cfg" ]; then
      if [ -z "${ARGO_ANYWHERE_USER:-}" ]; then
        # H5 fix amendment (2026-05-14): use yaml_scalar (handles both
        # quoted and unquoted YAML scalars). The previous awk -F'"'
        # parser silently failed on PyYAML's unquoted output, causing
        # the resolver to fall through to id -un (which on the laptop
        # is the OS username, NOT the Argonne username).
        ARGO_ANYWHERE_USER="$(yaml_scalar "$cfg" "user")"
      fi
      if [ -z "${ARGO_ANYWHERE_PORT:-}" ]; then
        # port: is always numeric; awk on whitespace works for both
        # PyYAML's `port: 64742` and the legacy `port: "64742"` forms
        # (the latter would set $2 = "64742" with quotes -- but we'd
        # try to use that as a port number and fail loudly elsewhere).
        # Switch to yaml_scalar for consistency + correctness.
        ARGO_ANYWHERE_PORT="$(yaml_scalar "$cfg" "port")"
      fi
    fi
  fi

  # Source 3: cache + defaults
  if [ -z "${ARGO_ANYWHERE_USER:-}" ] && [ -f "$USER_CACHE" ]; then
    ARGO_ANYWHERE_USER="$(cat "$USER_CACHE" 2>/dev/null)"
  fi
  if [ -z "${ARGO_ANYWHERE_USER:-}" ]; then
    ARGO_ANYWHERE_USER="$(id -un 2>/dev/null)"
  fi
  if [ -z "${ARGO_ANYWHERE_PORT:-}" ]; then
    ARGO_ANYWHERE_PORT="$PROXY_PORT_DEFAULT"
  fi

  ANL_USERNAME="${ARGO_ANYWHERE_USER}"
  PROXY_PORT="${ARGO_ANYWHERE_PORT}"
  : "${ANL_USERNAME:?could not resolve ARGO_ANYWHERE_USER from env, ~/.config/argoproxy/config.yaml, or cache; pass it explicitly}"
  : "${PROXY_PORT:?could not resolve ARGO_ANYWHERE_PORT; pass it explicitly}"

  # If neither was in env, the user invoked us standalone. Show what we
  # found and ask for confirmation before doing any work. -y skips the
  # prompt for non-interactive use.
  #
  # Skip the prompt entirely if we're inside the tee re-exec (the parent
  # invocation already prompted; the re-exec'd subprocess shouldn't ask
  # again). Also export the resolved values to env so the re-exec's
  # standalone-detection sees them as "from env" even though they
  # originated from config/cache in the parent.
  if [ -z "$user_was_in_env" ] && [ -z "$port_was_in_env" ] \
     && [ -z "$already_logged" ]; then
    log "Standalone 'server' invocation. Resolved identity from local"
    log "  config + cache (rather than env vars supplied by 'client'):"
    log "  user : ${ANL_USERNAME}"
    log "  port : ${PROXY_PORT}"
    if [ "${CLEAN_ASSUME_YES:-0}" = 1 ]; then
      log "Proceeding (-y / --yes given)."
    else
      local reply; reply="$(ask "Proceed? [Y/n]:" "Y")"
      case "$reply" in
        ''|y|Y|yes|YES|Yes) ;;
        *) die "Aborted at standalone-server confirmation step." ;;
      esac
    fi
  fi
  # If we haven't already, re-invoke ourselves with stdout+stderr piped through
  # tee so the bootstrap log captures everything. Avoids process substitution
  # (>(...)) so this stays robust on minimal shells.
  #
  # IMPORTANT: `exec CMD | tee FILE` does NOT replace the current shell with
  # the pipeline -- bash applies `exec` only to the LEFT side of the pipe.
  # The current shell waits for the pipeline, then continues running the
  # rest of mode_server, causing the bootstrap to run TWICE (the
  # "duplicate-bootstrap-via-tee" bug). The second run hits the
  # "Existing argo-proxy already serving... reusing." path so it appears
  # benign but it's still wrong: it spends time, prompts the user again
  # on the same handle_config_file step, and confuses the log.
  #
  # Fix: drop `exec`, run the pipeline, then either exit (when mode_server
  # is the script's main mode -- i.e. invoked as `bash argo-anywhere.sh
  # server` over SSH from the laptop) or return (when called in-process
  # from _client_common_setup's on-node short-circuit, where the caller
  # has more work to do after the bootstrap finishes). The signal is
  # the _MODE_SERVER_INPROC global, which the in-process caller sets
  # before invoking us.
  #
  # We pass ARGO_ANYWHERE_USER/PORT to the subprocess via env on the
  # bash command line (NOT via a shell-level export). This narrows the
  # scope: only the tee'd subprocess sees them, not the rest of the
  # parent shell's lifetime. Important when mode_server is called
  # in-process from _client_common_setup -- a top-level export would
  # leak the resolved identity into anything else that ran in this
  # shell after mode_server returns.
  if [ -z "${_ARGO_ANYWHERE_REEXEC:-}" ]; then
    mkdir -p "$(dirname "${HOME}/${REMOTE_LOG}")"
    _ARGO_ANYWHERE_REEXEC=1 \
      ARGO_ANYWHERE_USER="$ARGO_ANYWHERE_USER" \
      ARGO_ANYWHERE_PORT="$ARGO_ANYWHERE_PORT" \
      bash "$0" server 2>&1 | tee -a "${HOME}/${REMOTE_LOG}"
    local rc="${PIPESTATUS[0]}"
    if [ "${_MODE_SERVER_INPROC:-0}" = 1 ]; then
      # In-process call: return so the caller can continue. Failure
      # propagates as a non-zero return that the caller can handle.
      return "$rc"
    fi
    # Main-mode invocation: this script's job is done.
    exit "$rc"
  fi

  # ===========================================================================
  # mode_server BODY (everything above is identity resolution, prompt, and
  # tee/log re-exec wrapping; the actual bootstrap work starts here).
  # ===========================================================================
  log "[server] starting bootstrap on $(hostname) for user=${ANL_USERNAME} port=${PROXY_PORT}"

  # 1+2+3) System python check, venv create-or-validate, argo-proxy install.
  # Factored out of the inline body (2026-06-24, v2.2.1 prep) so the new
  # `update argoproxy` subcommand can call the same installer without
  # restarting argo-proxy. The factoring closes the conceptual-vs-real
  # naming gap noted in AGENTS.md (the audit docs referred to
  # `ensure_argoproxy_installed` as if it already existed); behavior is
  # preserved verbatim -- mode_server's contract for the install step is
  # unchanged from v2.2.0.
  ensure_argoproxy_installed || die "ensure_argoproxy_installed failed."

  # 4) argo-proxy config file
  handle_config_file "${HOME}/.config/argoproxy/config.yaml" "argo-proxy config" write_argoproxy_config

  # 4b) Validate the on-disk config's port matches what the client asked us
  #     to serve. argo-proxy reads config.yaml at startup; if the user kept
  #     an existing config with a different port (e.g. via [k] at the
  #     handle_config_file prompt above), argo-proxy will bind THAT port and
  #     the client's tunnel-side health check on $PROXY_PORT will time out.
  #     This used to fail late as "argo-proxy did not start listening within
  #     20s" (true but unhelpful); now we fail fast with a clear message.
  local cfg_path="${HOME}/.config/argoproxy/config.yaml"
  local cfg_port
  cfg_port="$(awk '/^[[:space:]]*port:[[:space:]]*[0-9]+/{print $2; exit}' "$cfg_path" 2>/dev/null)"
  if [ -n "$cfg_port" ] && [ "$cfg_port" != "$PROXY_PORT" ]; then
    err "Port mismatch on $(hostname):"
    err "  client asked us to serve on port : ${PROXY_PORT}"
    err "  ${cfg_path} declares port        : ${cfg_port}"
    err ""
    err "  argo-proxy reads its port from config.yaml, so it would bind ${cfg_port}"
    err "  while the client polls ${PROXY_PORT}. The likely cause: you chose [k] at the"
    err "  earlier 'argo-proxy config differs' prompt, keeping an out-of-date config."
    err ""
    err "  Fix on this node ($(hostname)):"
    err "    * edit ${cfg_path} and change the 'port:' line to ${PROXY_PORT}, OR"
    err "    * delete ${cfg_path} so the next run writes a fresh one, OR"
    err "    * re-run 'client' from your laptop and pick [b] (backup + overwrite)"
    err "      at the argo-proxy config prompt."
    die "Refusing to launch argo-proxy with a config that disagrees on port."
  fi

  # 5) Already listening on our port? Be paranoid: it might be someone else's
  #    argo-proxy or an unrelated process. Only treat as ours if (a) the
  #    listening pid is owned by us AND (b) /health responds AND (c) the
  #    config.yaml's user matches ARGO_ANYWHERE_USER.
  local listener_pid=""
  listener_pid="$( { lsof -nPi ":${PROXY_PORT}" -sTCP:LISTEN -t 2>/dev/null || true; } | head -n1)"
  if [ -n "$listener_pid" ]; then
    local pid_owner; pid_owner="$(ps -o user= -p "$listener_pid" 2>/dev/null | awk '{$1=$1;print}')"
    local me; me="$(id -un)"
    if [ "$pid_owner" != "$me" ]; then
      err "Port ${PROXY_PORT} on $(hostname) is held by pid ${listener_pid} owned by '${pid_owner}', not '${me}'."
      err "  This is most likely another user's argo-proxy. Refusing to attach to it."
      die "  Pick a different port:  bash $(basename "$0") --port <new_port> client"
    fi
    if curl -fsS --max-time 2 "http://127.0.0.1:${PROXY_PORT}/health" >/dev/null 2>&1; then
      # Looks like our argo-proxy. Confirm via config.yaml's user: line.
      # Compare against the Argonne username we were told to serve, NOT the
      # OS account name -- on shared compute nodes a single OS user could
      # in principle have run argo-proxy under multiple Argonne identities.
      #
      # H5 fix (audit): inverted from "deny only on KNOWN mismatch" to
      # "require KNOWN match before reusing". Previously, if the
      # config.yaml was missing/unreadable/malformed, cfg_user came back
      # empty and the old guard short-circuited to false -- silently
      # falling through to "reusing." That meant a healthy argo-proxy
      # with an inspection-failed config was attributed to the requested
      # user without any verification. New rule: refuse to reuse unless
      # we POSITIVELY confirm cfg_user == want_user. Three explicit
      # branches: cfg_user empty (refuse with inspection-failed message),
      # cfg_user set but != want_user (refuse with mismatch message;
      # was already correct), cfg_user == want_user (reuse). want_user
      # empty falls into the inspection-failed branch as well -- if we
      # don't even know who we're supposed to be serving, we shouldn't
      # be attaching to anyone's argo-proxy.
      local want_user="${ARGO_ANYWHERE_USER:-${ANL_USERNAME:-}}"
      local cfg_user
      # H5 fix amendment (2026-05-14): use yaml_scalar (handles both
      # quoted and unquoted YAML scalars). The original awk -F'"'
      # parser only matched user: "name", not user: name -- and PyYAML's
      # safe_dump (the writer used in the common case) emits the
      # unquoted form, causing this branch to wrongly fire on the very
      # first Phase 2b live test.
      cfg_user="$(yaml_scalar "${HOME}/.config/argoproxy/config.yaml" "user")"
      # Recovery hint shared by all three refusal branches. screen -X
      # quit alone is INSUFFICIENT when argo-proxy detached itself from
      # the screen wrapper (observed during the first Phase 2b live
      # test on 2026-05-14): the screen wrapper exits, the argo-proxy
      # process survives at the listener pid. Operator must kill the
      # listener pid directly. We surface BOTH commands so the operator
      # doesn't have to discover the detached-process case the hard way.
      local _h5_kill_hint="kill ${listener_pid} && screen -S ${SCREEN_SESSION} -X quit  (the kill targets the listener directly; the screen -X quit cleans up any wrapper session)"
      if [ -z "$want_user" ]; then
        err "Existing argo-proxy on :${PROXY_PORT} (pid ${listener_pid}) is healthy, but ARGO_ANYWHERE_USER (and the legacy ANL_USERNAME) are unset."
        err "  Refusing to reuse it; cannot verify whose calls would be attributed."
        die "  Set ARGO_ANYWHERE_USER and re-run, or stop it first:  ${_h5_kill_hint}"
      fi
      if [ -z "$cfg_user" ]; then
        err "Existing argo-proxy on :${PROXY_PORT} (pid ${listener_pid}) is healthy, but its config.yaml is missing or unreadable at \${HOME}/.config/argoproxy/config.yaml."
        err "  Refusing to reuse it; cannot verify identity."
        die "  Stop it first:  ${_h5_kill_hint}   (or pick another --port)"
      fi
      if [ "$cfg_user" != "$want_user" ]; then
        err "Existing argo-proxy on :${PROXY_PORT} (pid ${listener_pid}) is configured for user '${cfg_user}', not '${want_user}'."
        err "  Refusing to reuse it; calls would be misattributed."
        die "  Stop it first:  ${_h5_kill_hint}   (or pick another --port)"
      fi
      ok "Existing argo-proxy already serving on 127.0.0.1:${PROXY_PORT} (pid ${listener_pid}); identity verified (user='${cfg_user}'); reusing."
      return
    else
      warn "Port ${PROXY_PORT} is bound by our pid ${listener_pid} but /health does not answer; will kill and restart."
      kill "$listener_pid" 2>/dev/null || true
      sleep 1
      kill -0 "$listener_pid" 2>/dev/null && kill -9 "$listener_pid" 2>/dev/null || true
    fi
  fi

  # 6) Pick a session manager and start.
  local launcher=""
  if command -v screen >/dev/null 2>&1; then launcher="screen"
  elif command -v tmux >/dev/null 2>&1; then launcher="tmux"
  else launcher="nohup"
  fi

  # Resolve the venv path for the launch commands below. This USED to be
  # in scope because the install work lived inline in mode_server; when
  # `ensure_argoproxy_installed` was extracted (D-022, v2.2.1 prep) the
  # `local venv` moved with it, leaving the launch lines below referencing
  # an out-of-scope `${venv}`. Under `set -u` that dies with "venv:
  # unbound variable" right after the "Starting argo-proxy in screen
  # session" log line -- the D-005 "main-mode function factored out"
  # regression class. Recompute it here (same expression the installer
  # uses) so the launch commands see a bound value.
  local venv; venv="$(eval echo "$VENV_PATH")"

  # We reach this point only when nothing is listening on PROXY_PORT (the
  # earlier "is something already serving?" branch returned). If a screen
  # or tmux session by our name still exists, it's USUALLY empty (the
  # argo-proxy process inside it died, e.g. from a previous 'stop') --
  # but in one important case it's NOT empty: a previous client/server
  # invocation that used a DIFFERENT port. The script only supports one
  # argo-proxy per user per node (single SCREEN_SESSION name, single
  # ~/.config/argoproxy/config.yaml). Killing the session would silently
  # destroy that other instance and strand any tunnel pointed at it.
  # Detect this multi-port collision and warn before killing.
  #
  # We use lsof (already required elsewhere in the script) directly,
  # without an upfront pgrep gate. An earlier version had a pgrep gate
  # for "skip the lsof scan if no argo-proxy exists at all," but pgrep
  # is missing on truly minimal compute-node images (rare; mainly Alpine
  # without procps). lsof + awk does the right thing on its own: if no
  # argo-proxy rows match, awk prints nothing, the variable stays empty,
  # the warning doesn't fire. Slight efficiency cost (we run lsof
  # unconditionally), but correctness everywhere.
  local other_argoproxy_port=""
  # P1 fix (CRITICAL): wrap the lsof|awk|head pipeline in { ...; } || true.
  #
  # Without the wrapper: head -n1 reads its first match and closes stdin.
  # awk gets SIGPIPE and exits non-zero. With pipefail enabled, the pipe's
  # exit code becomes non-zero. Under set -e, the assignment to
  # other_argoproxy_port silently kills mode_server right here -- AFTER
  # the "argo-proxy config already up to date" log line and BEFORE the
  # "Starting argo-proxy in screen session" line. Server bootstrap reports
  # failure with no diagnostic; user retries; same silent-fail loop.
  #
  # This was the root cause of the "Bug 2" / "C6" silent-fail reported
  # on compute-386-01. See docs/AUDIT_2026-05-12.md finding P1.
  other_argoproxy_port="$( { lsof -nP -iTCP -sTCP:LISTEN 2>/dev/null \
    | awk -v me="$(id -un)" -v want="$PROXY_PORT" '
        $1 ~ /^argo/ && $3 == me {
          split($9, a, ":");
          p = a[length(a)];
          gsub(/[^0-9]/, "", p);
          if (p != "" && p != want) print p;
        }' | head -n1; } || true )"
  if [ -n "$other_argoproxy_port" ]; then
    warn "You already have an argo-proxy of yours running on port ${other_argoproxy_port}"
    warn "  on this host. The script supports ONE argo-proxy per user per node"
    warn "  (single screen session '${SCREEN_SESSION}', single config file at"
    warn "  ~/.config/argoproxy/config.yaml). Starting a new one on port ${PROXY_PORT}"
    warn "  will require killing the existing screen session, which destroys"
    warn "  the argo-proxy on :${other_argoproxy_port} and strands any tunnel pointed there."
    warn ""
    if [ "${CLEAN_ASSUME_YES:-0}" = 1 ]; then
      warn "Proceeding (-y / --yes given)."
    else
      local reply; reply="$(ask "Replace the existing argo-proxy on :${other_argoproxy_port} with a new one on :${PROXY_PORT}? [y/N]:" "n")"
      case "$reply" in
        y|Y|yes|YES|Yes) ;;
        *) die "Aborted at multi-port-collision step. Use the existing port (${other_argoproxy_port}) or stop the existing argo-proxy first ('$(basename "$0") stop')." ;;
      esac
    fi
  fi

  # Legacy v1.x screen/tmux session detection: warn if the pre-rename
  # session name (agovproxy) is still around. Could be a stale empty
  # shell OR could still be holding a live argo-proxy from a v1.x run.
  # Either way, the user needs to know -- we don't auto-kill it because
  # killing a live argo-proxy would strand any clients still pointed at
  # it. (`clean` handles cleanup for both names.)
  case "$launcher" in
    screen)
      if screen -ls 2>/dev/null | grep -q "\.${LEGACY_SCREEN_SESSION}\b"; then
        warn "Found legacy v1.x screen session '${LEGACY_SCREEN_SESSION}' (pre-rename name)."
        warn "  v2.0 uses '${SCREEN_SESSION}'; the legacy session is NOT touched."
        warn "  If you want to clean it up:"
        warn "    screen -S ${LEGACY_SCREEN_SESSION} -X quit"
        warn "  ('clean' also handles this.)"
      fi
      ;;
    tmux)
      if tmux has-session -t "${LEGACY_SCREEN_SESSION}" 2>/dev/null; then
        warn "Found legacy v1.x tmux session '${LEGACY_SCREEN_SESSION}' (pre-rename name)."
        warn "  v2.0 uses '${SCREEN_SESSION}'; the legacy session is NOT touched."
        warn "  If you want to clean it up:"
        warn "    tmux kill-session -t ${LEGACY_SCREEN_SESSION}"
        warn "  ('clean' also handles this.)"
      fi
      ;;
  esac

  # Past the multi-port + legacy-session checks. If a session by our
  # CURRENT name still exists, treat it as housekeeping (the process
  # inside it died, e.g. from a previous 'stop') and clean up calmly
  # before starting fresh.
  case "$launcher" in
    screen)
      if screen -ls 2>/dev/null | grep -q "\.${SCREEN_SESSION}\b"; then
        log "Found existing (empty) screen session '${SCREEN_SESSION}'"
        log "  from a previous run; cleaning up before starting fresh."
        screen -S "${SCREEN_SESSION}" -X quit || true
      fi
      log "Starting argo-proxy in screen session '${SCREEN_SESSION}'..."
      screen -dmS "${SCREEN_SESSION}" "${venv}/bin/argo-proxy" serve
      ;;
    tmux)
      if tmux has-session -t "${SCREEN_SESSION}" 2>/dev/null; then
        log "Found existing (empty) tmux session '${SCREEN_SESSION}'"
        log "  from a previous run; cleaning up before starting fresh."
        tmux kill-session -t "${SCREEN_SESSION}" || true
      fi
      log "Starting argo-proxy in tmux session '${SCREEN_SESSION}'..."
      # tmux new-session [shell-command]: takes ONE string that's
      # interpreted by the user's shell. We can't split into multiple
      # args (unlike screen -dmS NAME ARG1 ARG2). If $venv contains
      # spaces (e.g. $HOME = '/Users/Alice Smith'), naively interpolating
      # would word-split. Use printf %q to shell-escape the binary path.
      local _tmux_cmd; _tmux_cmd="$(printf '%q' "${venv}/bin/argo-proxy") serve"
      tmux new-session -d -s "${SCREEN_SESSION}" "$_tmux_cmd"
      ;;
    nohup)
      warn "Neither screen nor tmux available; falling back to nohup."
      nohup "${venv}/bin/argo-proxy" serve > "${HOME}/argoproxy.out" 2>&1 < /dev/null &
      disown || true
      ;;
  esac

  # 7) Wait for it to listen.
  local waited=0
  until curl -fsS --max-time 2 "http://127.0.0.1:${PROXY_PORT}/health" >/dev/null 2>&1; do
    sleep 1; waited=$((waited+1))
    if [ "$waited" -ge 20 ]; then
      err "argo-proxy did not start listening within ${waited}s."
      # The diagnostic to surface depends on which launcher we used --
      # earlier code paths only wrote a stdout/stderr log file in the
      # nohup branch (line 'nohup ... > ${HOME}/argoproxy.out'). For
      # screen and tmux, argo-proxy's output is captured INSIDE the
      # session and there's no log file to tail. Tell the user how to
      # see the actual error in each case.
      case "$launcher" in
        screen)
          err "argo-proxy's output is inside the screen session. Inspect with:"
          err "  screen -r ${SCREEN_SESSION}        # detach with Ctrl-A then d"
          err "If the session has already exited (no screen for argo-proxy left),"
          err "  the failure left no log; re-run with --force-reinstall to start fresh."
          ;;
        tmux)
          err "argo-proxy's output is inside the tmux session. Inspect with:"
          err "  tmux attach -t ${SCREEN_SESSION}   # detach with Ctrl-B then d"
          err "If the session has already exited (no tmux for argo-proxy left),"
          err "  the failure left no log; re-run with --force-reinstall to start fresh."
          ;;
        nohup)
          if [ -f "${HOME}/argoproxy.out" ]; then
            err "Last 30 lines of ${HOME}/argoproxy.out:"
            tail -n 30 "${HOME}/argoproxy.out" >&2
          else
            err "Expected ${HOME}/argoproxy.out but no log was written."
          fi
          ;;
      esac
      die "Server bootstrap failed."
    fi
  done
  ok "argo-proxy is listening on 127.0.0.1:${PROXY_PORT}."
}

# ============================================================================
# SECTION: 19. SUMMARY GATHERING (fetch_proxy_models, extract_*, gather_summary)
# ============================================================================
# Populates SUM_* globals consumed by render_summary and reused by mode_status
# and mode_update_models for cross-referencing configured vs available models.

# fetch_proxy_models: prints raw /v1/models JSON to stdout, or empty.
fetch_proxy_models() {
  curl -fsS --max-time 5 "http://localhost:${PROXY_PORT}/v1/models" 2>/dev/null || true
}

# extract_available_internal_names <body>: prints one internal_name per line.
extract_available_internal_names() {
  local body="$1"
  if command -v jq >/dev/null 2>&1; then
    printf '%s' "$body" | jq -r '.data[].internal_name' 2>/dev/null
  else
    # Best-effort: pick "internal_name": "..." occurrences.
    printf '%s' "$body" | grep -oE '"internal_name"[[:space:]]*:[[:space:]]*"[^"]*"' \
      | sed 's/.*"\([^"]*\)"$/\1/'
  fi
}

# extract_configured_internal_names: reads ~/.config/opencode/config.json and
# prints the keys under provider.argo.models, one per line.
extract_configured_internal_names() {
  local cfg="${OPENCODE_CONFIG}"
  [ -f "$cfg" ] || return 0
  if command -v jq >/dev/null 2>&1; then
    jq -r '.provider.argo.models // {} | keys[]' "$cfg" 2>/dev/null
  else
    # Best-effort awk fallback. KNOWN LIMITATION: this counts the first quoted
    # key on each line that contains '"...": {' anywhere AFTER a 'models: {'
    # marker. It works for our standard config style (one key per line) but
    # will misbehave on minified JSON. The main path uses jq -- this fallback
    # exists only so 'status' doesn't crash when jq is missing on the laptop.
    # 'update-models' requires jq and refuses to run without it.
    awk '
      /"models"[[:space:]]*:[[:space:]]*\{/ { inblk=1; depth=1; next }
      !inblk { next }
      {
        # Check key BEFORE consuming braces, since "key": { adds depth on
        # this same line.
        if (depth==1 && match($0, /"[^"]+"[[:space:]]*:[[:space:]]*\{/)) {
          t = substr($0, RSTART+1, RLENGTH-1)
          sub(/".*$/, "", t)
          print t
        }
        for (i=1;i<=length($0);i++) {
          c = substr($0,i,1)
          if (c=="{") depth++
          else if (c=="}") { depth--; if (depth==0) { inblk=0; exit } }
        }
      }
    ' "$cfg"
  fi
}

# Sets these globals (consumed by render_summary):
#   SUM_LISTENER_OK SUM_LISTENER_PID SUM_LISTENER_BIND
#   SUM_HEALTH_OK
#   SUM_MODELS_OK SUM_MODEL_COUNT SUM_MODEL_UNIQ_COUNT SUM_MODEL_SAMPLE
#   SUM_CFG_COUNT SUM_CFG_AVAIL_COUNT SUM_CFG_ORPHAN_COUNT SUM_CFG_ORPHAN_LIST
#
# Note: SUM_MODEL_COUNT is the raw /v1/models count (includes aliases and
# embeddings). SUM_MODEL_UNIQ_COUNT applies the same filter `update-models`
# uses (drop embeddings, dedupe by internal_name) so 'unconfigured' arithmetic
# matches what update-models would actually add.
gather_summary() {
  SUM_LISTENER_OK=0; SUM_LISTENER_PID=""; SUM_LISTENER_BIND=""
  SUM_HEALTH_OK=0
  SUM_MODELS_OK=0; SUM_MODEL_COUNT=0; SUM_MODEL_UNIQ_COUNT=0; SUM_MODEL_SAMPLE=""
  SUM_CFG_COUNT=0; SUM_CFG_AVAIL_COUNT=0
  SUM_CFG_ORPHAN_COUNT=0; SUM_CFG_ORPHAN_LIST=""

  # Listener (lsof exits 1 when nothing matches; '|| true' keeps pipefail happy).
  #
  # ssh -L on a dual-stack host produces TWO rows for the same listener: an
  # IPv6 row (NAME column shows '[::1]:PORT') and an IPv4 row ('127.0.0.1:PORT'),
  # both owned by the same pid. lsof prints them in arbitrary order. Prefer
  # the IPv4 row for SUM_LISTENER_BIND because:
  #   * 'localhost' resolves to 127.0.0.1 first on most laptops, so curl(1)
  #     and OpenCode actually talk to the IPv4 socket;
  #   * users debugging the displayed bind address with `lsof -nPi :PORT` see
  #     the same family the rest of the script's docs reference.
  # If only an IPv6 row is present we fall back to it.
  local lsof_out
  lsof_out="$( { lsof -nPi ":${PROXY_PORT}" -sTCP:LISTEN 2>/dev/null || true; } )"
  local lsof_line
  lsof_line="$(printf '%s\n' "$lsof_out" \
                 | awk 'NR>1 && $5=="IPv4" {print $2" "$9; exit}')"
  if [ -z "$lsof_line" ]; then
    lsof_line="$(printf '%s\n' "$lsof_out" \
                   | awk 'NR>1 {print $2" "$9; exit}')"
  fi
  if [ -n "$lsof_line" ]; then
    SUM_LISTENER_OK=1
    SUM_LISTENER_PID="${lsof_line%% *}"
    SUM_LISTENER_BIND="${lsof_line#* }"
  fi

  # Health
  if curl -fsS --max-time 3 "http://localhost:${PROXY_PORT}/health" >/dev/null 2>&1; then
    SUM_HEALTH_OK=1
  fi

  # Available models from the proxy
  local body=""
  if [ "$SUM_HEALTH_OK" -eq 1 ]; then
    body="$(fetch_proxy_models)"
    if [ -n "$body" ]; then
      SUM_MODELS_OK=1
      if command -v jq >/dev/null 2>&1; then
        SUM_MODEL_COUNT="$(printf '%s' "$body" | jq '.data | length' 2>/dev/null || echo 0)"
        # Same filter as `update-models`: drop embeddings, dedupe by internal_name.
        SUM_MODEL_UNIQ_COUNT="$(printf '%s' "$body" | jq '
          [ .data[] | select(.id | test("embedding") | not) ]
          | unique_by(.internal_name) | length
        ' 2>/dev/null || echo 0)"
        SUM_MODEL_SAMPLE="$(printf '%s' "$body" \
          | jq -r '.data[0:3] | map(.id) | join(", ")' 2>/dev/null)"
      else
        SUM_MODEL_COUNT="$(printf '%s' "$body" | grep -c '"id":' || true)"
        # Without jq we can only approximate the unique chat count.
        SUM_MODEL_UNIQ_COUNT="$(extract_available_internal_names "$body" \
          | grep -viE '^(ada002|v3small|v3large)$' | sort -u | wc -l | tr -d ' ')"
        SUM_MODEL_SAMPLE="$(printf '%s' "$body" \
          | grep -oE '"id"[^,]*' | head -n3 | sed 's/.*"\([^"]*\)".*$/\1/' | tr '\n' ',' | sed 's/,$//; s/,/, /g')"
      fi
    fi
  fi

  # Configured models from ~/.config/opencode/config.json
  local cfg_names avail_names
  cfg_names="$(extract_configured_internal_names || true)"
  if [ -n "$cfg_names" ]; then
    SUM_CFG_COUNT="$(printf '%s\n' "$cfg_names" | sed '/^$/d' | wc -l | tr -d ' ')"
  fi

  # Cross-reference (only meaningful when proxy responded)
  if [ "$SUM_MODELS_OK" -eq 1 ] && [ "$SUM_CFG_COUNT" -gt 0 ]; then
    avail_names="$(extract_available_internal_names "$body" | sort -u)"
    local cfg_sorted; cfg_sorted="$(printf '%s\n' "$cfg_names" | sed '/^$/d' | sort -u)"
    # available ∩ configured
    SUM_CFG_AVAIL_COUNT="$(comm -12 \
      <(printf '%s\n' "$cfg_sorted") \
      <(printf '%s\n' "$avail_names") | wc -l | tr -d ' ')"
    # configured \ available  (orphans)
    local orphans
    orphans="$(comm -23 \
      <(printf '%s\n' "$cfg_sorted") \
      <(printf '%s\n' "$avail_names"))"
    if [ -n "$orphans" ]; then
      SUM_CFG_ORPHAN_COUNT="$(printf '%s\n' "$orphans" | wc -l | tr -d ' ')"
      SUM_CFG_ORPHAN_LIST="$(printf '%s' "$orphans" | tr '\n' ',' | sed 's/,$//; s/,/, /g')"
    fi
  fi
}

# ============================================================================
# SECTION: 20. SUMMARY RENDERING (render_summary -- the big box)
# ============================================================================
# Prints the unified summary box from SUM_* globals + cached identity.
render_summary() {
  local cached_user="(unset)" cached_node="(unset)"
  if [ -f "$USER_CACHE" ]; then cached_user="$(cat "$USER_CACHE")"; fi
  if [ -f "$NODE_CACHE" ]; then cached_node="$(cat "$NODE_CACHE")"; fi

  # Verdict
  local verdict vcolor
  if [ "$SUM_LISTENER_OK" -eq 1 ] && [ "$SUM_HEALTH_OK" -eq 1 ] && [ "$SUM_MODELS_OK" -eq 1 ]; then
    verdict="ALL GREEN  -  tunnel up, proxy healthy, ${SUM_MODEL_COUNT} model(s)"
    vcolor="$C_GRN"
  elif [ "$SUM_LISTENER_OK" -eq 1 ] && [ "$SUM_HEALTH_OK" -eq 1 ]; then
    verdict="DEGRADED   -  proxy healthy but /v1/models did not respond"
    vcolor="$C_YLW"
  elif [ "$SUM_LISTENER_OK" -eq 1 ]; then
    verdict="DEGRADED   -  listener present, proxy NOT answering"
    vcolor="$C_YLW"
  else
    # Phrase the FAIL case based on where we are. On a compute node
    # we expect argo-proxy itself; "no tunnel" is misleading because
    # there's never supposed to be a tunnel here.
    if [ "$(on_anl_compute_node)" = "yes" ]; then
      verdict="FAIL       -  argo-proxy not running on :${PROXY_PORT}"
    else
      verdict="FAIL       -  no local tunnel on :${PROXY_PORT}"
    fi
    vcolor="$C_RED"
  fi

  # Body lines, organized into named sections. print_summary_box recognizes
  # any line beginning with "__SECTION__:" as a section break; everything
  # below it (until the next sentinel or end) belongs to that section.
  # Within a section we drop the redundant noun prefix from row labels
  # (e.g. inside "Models", "Available" instead of "Models available").
  local lines=()

  # ---- Section: Connection -------------------------------------------------
  lines+=("__SECTION__:Connection")
  local listener_str
  if [ "$SUM_LISTENER_OK" -eq 1 ]; then
    listener_str="pid ${SUM_LISTENER_PID} bound to ${SUM_LISTENER_BIND}"
  else
    listener_str="(no local listener)"
  fi
  lines+=("Local listener   : ${listener_str}")

  local health_str
  if [ "$SUM_HEALTH_OK" -eq 1 ]; then
    health_str="healthy  (http://localhost:${PROXY_PORT}/health)"
  else
    health_str="UNREACHABLE on http://localhost:${PROXY_PORT}/health"
  fi
  lines+=("Proxy /health    : ${health_str}")

  if [ -n "$SUM_LISTENER_PID" ]; then
    local uptime_str
    uptime_str="$(ps -o etime= -p "$SUM_LISTENER_PID" 2>/dev/null | awk '{$1=$1;print}' || true)"
    if [ -n "$uptime_str" ]; then
      lines+=("Tunnel uptime    : ${uptime_str}  (HH:MM:SS or DD-HH:MM:SS)")
    fi
  fi

  # ---- Section: Models -----------------------------------------------------
  lines+=("__SECTION__:Models")
  if [ "$SUM_MODELS_OK" -eq 1 ]; then
    local avail_str="${SUM_MODEL_COUNT} at /v1/models"
    if [ -n "$SUM_MODEL_SAMPLE" ]; then
      avail_str="${avail_str}  (e.g. ${SUM_MODEL_SAMPLE}, ...)"
    fi
    lines+=("Available        : ${avail_str}")
  else
    lines+=("Available        : (unknown -- proxy unreachable)")
  fi
  # Without jq the configured-models extraction is best-effort (works on the
  # standard one-key-per-line config style this script writes; misbehaves on
  # minified JSON). Annotate the row so users know to install jq if the
  # numbers look off.
  local cfg_qual=""
  if ! command -v jq >/dev/null 2>&1; then
    cfg_qual="  (counts approximate; install jq for exact)"
  fi
  # NOTE: the "configured models" concept is OpenCode-specific -- only
  # OpenCode enumerates per-model entries in its config. Claude Code and
  # aider choose models at runtime (--model), so there's no "configured
  # count" to show for them. The rows below are explicitly labelled
  # "OpenCode" so the box doesn't imply this is a global/all-tools fact.
  if [ "$SUM_CFG_COUNT" -gt 0 ]; then
    if [ "$SUM_MODELS_OK" -eq 1 ]; then
      lines+=("OpenCode models  : ${SUM_CFG_COUNT} configured (${SUM_CFG_AVAIL_COUNT} reachable)${cfg_qual}")
    else
      lines+=("OpenCode models  : ${SUM_CFG_COUNT} configured (reachability unknown)${cfg_qual}")
    fi
    if [ "$SUM_CFG_ORPHAN_COUNT" -gt 0 ]; then
      lines+=("Orphaned         : ${SUM_CFG_ORPHAN_COUNT} configured but NOT in /v1/models")
      lines+=("                   list: ${SUM_CFG_ORPHAN_LIST}")
      lines+=("                   (run '$(basename "$0") update-models' to review)")
    fi
    # Hint: there are reachable chat models (unique by internal_name, no
    # embeddings) the user has not added to opencode yet. The math here mirrors
    # what `update-models` would actually do, so the count is honest.
    if [ "$SUM_MODELS_OK" -eq 1 ]; then
      local missing=$((SUM_MODEL_UNIQ_COUNT - SUM_CFG_AVAIL_COUNT))
      if [ "$missing" -gt 0 ]; then
        lines+=("Unconfigured     : ${missing} reachable chat model(s) not in OpenCode config")
        lines+=("                   (run '$(basename "$0") update-models' to add them)")
      fi
    fi
  else
    # Only nudge about OpenCode's empty model list when OpenCode is
    # actually the/an installed tool; otherwise the hint is noise for
    # claudecode/aider-only users.
    if command -v opencode >/dev/null 2>&1 || [ -f "$OPENCODE_CONFIG" ]; then
      lines+=("OpenCode models  : 0 configured")
      lines+=("                   (run '$(basename "$0") update-models' to populate)")
    fi
  fi

  # ---- Section: Configuration ----------------------------------------------
  lines+=("__SECTION__:Configuration")
  lines+=("Port             : ${PROXY_PORT}")
  lines+=("Jump host        : ${ANL_JUMP}")
  # Only show cached identity rows when something is actually cached.
  # Use if/then so a failed test doesn't kill the function under set -e.
  local have_user=0 have_node=0
  if [ "$cached_user" != "(unset)" ]; then have_user=1; fi
  if [ "$cached_node" != "(unset)" ]; then have_node=1; fi
  if [ "$have_user" -eq 1 ]; then lines+=("Cached username  : ${cached_user}"); fi
  if [ "$have_node" -eq 1 ]; then lines+=("Cached node      : ${cached_node}"); fi
  if [ "$have_user" -eq 0 ] && [ "$have_node" -eq 0 ]; then
    lines+=("Cached identity  : (none yet -- run '$(basename "$0") client' to set)")
  fi

  # ---- Section: Paths ------------------------------------------------------
  # Show whichever CLI-tool configs actually exist on disk (not just
  # OpenCode -- the box used to be OpenCode-only, which mislead
  # claudecode/aider users). The state dir and the remote log path are
  # only meaningful once 'client' has run, so suppress them when there is
  # nothing real to point at.
  lines+=("__SECTION__:Paths")
  local _shown_cfg=0
  if [ -f "$OPENCODE_CONFIG" ]; then
    lines+=("OpenCode config  : ${OPENCODE_CONFIG}"); _shown_cfg=1
  fi
  if [ -f "$CLAUDECODE_GLOBAL_CONFIG" ]; then
    lines+=("Claude Code cfg  : ${CLAUDECODE_GLOBAL_CONFIG}"); _shown_cfg=1
  fi
  if [ -f "$AIDER_GLOBAL_CONFIG" ]; then
    lines+=("aider config     : ${AIDER_GLOBAL_CONFIG}"); _shown_cfg=1
  fi
  # If none exist yet, still show the OpenCode path as the canonical
  # example so the box isn't empty here on a fresh machine.
  if [ "$_shown_cfg" -eq 0 ]; then
    lines+=("Client configs   : none yet (e.g. OpenCode -> ${OPENCODE_CONFIG})")
  fi
  if [ -d "$STATE_DIR" ] || [ "$have_user" -eq 1 ] || [ "$have_node" -eq 1 ]; then
    lines+=("Script state dir : ${STATE_DIR}")
  fi
  if [ "$have_user" -eq 1 ] && [ "$have_node" -eq 1 ]; then
    lines+=("Remote bootstrap : ${cached_user}@${cached_node}:~/${REMOTE_LOG}")
  fi

  # ---- Section: Next step --------------------------------------------------
  lines+=("__SECTION__:Next step")
  if [ "$SUM_LISTENER_OK" -eq 1 ] && [ "$SUM_HEALTH_OK" -eq 1 ] && [ "$SUM_MODELS_OK" -eq 1 ]; then
    # When the proxy is healthy, surface model-config drift so the user knows
    # exactly which axis update-models would change. Three independent axes:
    #   * orphans          : in config, NOT in /v1/models (would be reviewed for removal)
    #   * unconfigured     : in /v1/models, NOT in config (would be added)
    #   * neither          : in sync; just go run opencode
    local missing=0
    if [ "$SUM_MODEL_UNIQ_COUNT" -gt 0 ]; then
      missing=$((SUM_MODEL_UNIQ_COUNT - SUM_CFG_AVAIL_COUNT))
      [ "$missing" -lt 0 ] && missing=0
    fi
    # Three sub-cases here, branching on whether the user has an OpenCode
    # config at all and what model drift exists:
    #
    #   * No OpenCode config exists yet -> 'update-models' would die with
    #     "Run 'client' first." Suggest 'client' instead. (G5 fix.)
    #   * Config exists, has drift (orphans or new available) -> suggest
    #     'update-models' to reconcile.
    #   * Config exists and is in sync -> just run 'opencode'.
    if [ ! -f "${OPENCODE_CONFIG}" ]; then
      lines+=("OpenCode config not yet written. Run  '$(basename "$0") client'")
      lines+=("  to install OpenCode and write its config, then 'opencode' to use it.")
    elif [ "$SUM_CFG_ORPHAN_COUNT" -gt 0 ] || [ "$missing" -gt 0 ]; then
      local hint=""
      if [ "$missing" -gt 0 ] && [ "$SUM_CFG_ORPHAN_COUNT" -gt 0 ]; then
        hint="add ${missing} new and review ${SUM_CFG_ORPHAN_COUNT} orphan(s)"
      elif [ "$missing" -gt 0 ]; then
        hint="add ${missing} new model(s)"
      else
        hint="review ${SUM_CFG_ORPHAN_COUNT} orphan(s)"
      fi
      lines+=("Run '$(basename "$0") update-models' to ${hint},")
      lines+=("then 'opencode' in another terminal.")
    else
      lines+=("Run  'opencode'  in another terminal.")
    fi
  elif [ "$SUM_LISTENER_OK" -eq 0 ]; then
    # On a compute node, the listener should be argo-proxy itself; running
    # 'client' triggers the on-node short-circuit which starts argo-proxy
    # locally (no tunnel). Phrase the hint accordingly.
    if [ "$(on_anl_compute_node)" = "yes" ]; then
      lines+=("Start argo-proxy on this node with  '$(basename "$0") client'")
      lines+=("  (or  '$(basename "$0") server'  to bring up only the proxy).")
    else
      lines+=("Start the tunnel with  '$(basename "$0") client'.")
    fi
  elif [ "$SUM_HEALTH_OK" -eq 0 ]; then
    if [ "$cached_node" != "(unset)" ] && [ "$cached_user" != "(unset)" ]; then
      lines+=("Inspect the remote bootstrap log:")
      lines+=("  ssh -J ${cached_user}@${ANL_JUMP} ${cached_user}@${cached_node} \\")
      lines+=("    'tail -n 80 ~/${REMOTE_LOG}'")
    else
      lines+=("Check the remote argo-proxy log on the compute node.")
    fi
  else
    lines+=("Check argo-proxy logs on the compute node.")
  fi

  echo >&2
  print_summary_box "argo-anywhere  --  status summary" "$vcolor" "$verdict" "${lines[@]}"
}

# ============================================================================
# SECTION: 21. STATUS / STOP (mode_status, mode_stop)
# ============================================================================
mode_status() {
  # Preamble label: "Local tunnel listener" makes sense on a laptop where
  # the listener IS our SSH tunnel. On a compute node the listener is
  # argo-proxy itself, and "tunnel" is misleading. Use the more neutral
  # "Local listener" everywhere.
  log "Local listener on :${PROXY_PORT}:"
  lsof -nPi ":${PROXY_PORT}" -sTCP:LISTEN 2>/dev/null || warn "  (none)"

  log "argo-proxy /health via localhost:"
  if curl -fsS --max-time 3 "http://localhost:${PROXY_PORT}/health" 2>/dev/null; then
    echo
  else
    warn "Proxy NOT reachable on localhost:${PROXY_PORT}."
  fi

  gather_summary

  if [ "$SUM_HEALTH_OK" -eq 1 ]; then
    log "/v1/models: ${SUM_MODEL_COUNT} model(s) available."
    if [ "${ARGO_ANYWHERE_SHOW_MODELS:-0}" = "1" ]; then
      curl -fsS --max-time 5 "http://localhost:${PROXY_PORT}/v1/models" 2>/dev/null \
        | (command -v jq >/dev/null 2>&1 && jq . || cat) || true
    else
      log "  (rerun with: ARGO_ANYWHERE_SHOW_MODELS=1 bash $(basename "$0") status   to see the full list)"
    fi
  fi

  render_summary

  # Cross-client port-coherence (D-021, B3): passively report when any
  # installed client config disagrees with the resolved PROXY_PORT.
  # status is a read-only command and never prompts the user; it just
  # surfaces the situation so a follow-up `client` run can resolve it
  # via prompt_port_choice. Output goes through warn() so it shows up
  # in `2>/dev/null`-free invocations but doesn't pollute pipelines
  # that capture stdout.
  local _disagree_lines
  _disagree_lines="$(detect_port_disagreement "$PROXY_PORT" || true)"
  if [ -n "$_disagree_lines" ]; then
    warn "Cross-client port disagreement detected (D-021):"
    warn "  Resolved port (cache / CLI / env / default): ${PROXY_PORT}"
    warn "  Disagreeing client config(s):"
    printf '%s\n' "$_disagree_lines" | while IFS= read -r _l; do
      warn "    $_l"
    done
    warn "  Run 'argo-anywhere.sh client' to canonicalize via the [m/u/k/a] prompt."
  fi

  # Exit code reflects health for use in && chains. D-021 disagreement
  # is informational; it does NOT flip the exit code (status remains a
  # pure health check).
  if [ "$SUM_LISTENER_OK" -eq 1 ] && [ "$SUM_HEALTH_OK" -eq 1 ] && [ "$SUM_MODELS_OK" -eq 1 ]; then
    return 0
  fi
  return 1
}

mode_stop() {
  # mode_stop kills whatever process is bound to the resolved port locally.
  # On a laptop that's the SSH tunnel (intended use); the warning at the
  # bottom correctly notes that argo-proxy on the remote node survives.
  #
  # On a compute node, however, the process bound to PROXY_PORT IS
  # argo-proxy itself. Killing it has much bigger blast radius than killing
  # a tunnel: it breaks every client pointed at this host on this port,
  # including any laptop with an active tunnel here. The original warning
  # text was simply wrong in that case ("does NOT stop argo-proxy" -- yes
  # it just did). Use local_tunnel_status to detect the situation and
  # branch appropriately.
  local pids
  pids="$(lsof -nPi ":${PROXY_PORT}" -sTCP:LISTEN -t 2>/dev/null || true)"
  if [ -z "$pids" ]; then
    log "Nothing listening on :${PROXY_PORT}; nothing to stop locally."
    ok "Nothing to stop locally."
    return 0
  fi

  local lstatus; lstatus="$(local_tunnel_status "$PROXY_PORT")"
  case "$lstatus" in
    # B0 fix (Phase 4 pre-work, 2026-05-...): case labels updated to match
    # local_tunnel_status's actual return values. Pre-fix used
    # `ours-healthy|ours-unhealthy` which NEVER MATCHED -- the function
    # returns the four-value set with `-fg`/`-mux` suffixes
    # (ours-healthy-fg, ours-unhealthy-fg, ours-healthy-mux,
    # ours-unhealthy-mux) since the F1/F5 refactor that split mux from
    # fg detection. Result of the drift: every "our tunnel" run fell
    # through to the `external-healthy|other-or-broken` branch's
    # blast-radius warning at the bottom of this case, which is the
    # WRONG message for the laptop-tunnel scenario. This was a
    # pre-existing v2.1.x latent bug surfaced during Phase 4 planning
    # review.
    ours-healthy-fg|ours-unhealthy-fg|ours-healthy-mux|ours-unhealthy-mux)
      # Listener is an SSH tunnel (foreground or mux master) we own.
      # The classic laptop case.
      log "Killing local SSH tunnel listening on :${PROXY_PORT}..."
      echo "$pids" | xargs -n1 kill 2>/dev/null || true
      sleep 1
      echo "$pids" | xargs -I{} sh -c 'kill -0 {} 2>/dev/null && kill -9 {} || true'
      ok "Killed: ${pids//$'\n'/ }"
      warn "Note: this does NOT stop argo-proxy on the ANL node. To stop it"
      warn "  remotely, use the launcher actually used by 'server' mode"
      warn "  (screen is preferred, tmux is the next fallback, then nohup):"
      cat >&2 <<EOF
  # if started under screen (default when available):
  ssh -J <user>@${ANL_JUMP} <user>@<node> 'screen -S ${SCREEN_SESSION} -X quit'
  # if started under tmux:
  ssh -J <user>@${ANL_JUMP} <user>@<node> 'tmux kill-session -t ${SCREEN_SESSION}'
  # if started via nohup (no session manager available):
  ssh -J <user>@${ANL_JUMP} <user>@<node> 'pkill -f "argo-proxy serve"'
  # or just use 'clean' to do all of the above + tear down local state.
EOF
      ;;
    external-healthy|other-or-broken)
      # Listener is NOT an SSH tunnel. Most likely argo-proxy itself
      # (the on-compute-node case). Confirm before killing because the
      # blast radius is "all clients pointed at this host on this port",
      # not just "this user's tunnel."
      warn "On this host, port ${PROXY_PORT} is NOT held by an SSH tunnel."
      warn "  The listener (pid ${pids//$'\n'/ }) is most likely argo-proxy itself."
      warn "  Killing it will break:"
      warn "    * any client (opencode, claudecode, ...) pointed at this host:port"
      warn "    * any laptop whose SSH tunnel forwards to this host:port"
      warn "    * any other user pointing at this host:port"
      warn "  This is different from the usual 'stop the local SSH tunnel'"
      warn "  meaning of 'stop' (which is a no-op for the underlying argo-proxy)."

      if [ "${CLEAN_ASSUME_YES:-0}" = 1 ]; then
        log "Proceeding (-y / --yes given)."
      else
        local reply; reply="$(ask "Kill the listener anyway? [y/N]:" "n")"
        case "$reply" in
          y|Y|yes|YES|Yes) ;;
          *) die "Aborted." ;;
        esac
      fi

      log "Killing listener on :${PROXY_PORT}..."
      echo "$pids" | xargs -n1 kill 2>/dev/null || true
      sleep 1
      echo "$pids" | xargs -I{} sh -c 'kill -0 {} 2>/dev/null && kill -9 {} || true'
      ok "Killed: ${pids//$'\n'/ }"
      # Whether to print the screen/tmux cleanup hint depends on whether
      # those sessions still exist post-kill. When argo-proxy was the only
      # process inside its screen/tmux wrapper, killing it terminates the
      # wrapper too -- so the hint would point at a session that's
      # already gone. Probe both managers and only mention what's left.
      local stale_screen=0 stale_tmux=0
      if command -v screen >/dev/null 2>&1 \
         && screen -ls 2>/dev/null | grep -q "\.${SCREEN_SESSION}\b"; then
        stale_screen=1
      fi
      if command -v tmux >/dev/null 2>&1 \
         && tmux has-session -t "${SCREEN_SESSION}" 2>/dev/null; then
        stale_tmux=1
      fi
      if [ "$stale_screen" -eq 1 ] || [ "$stale_tmux" -eq 1 ]; then
        warn "Note: the session that hosted argo-proxy is still around (empty)."
        warn "  To tear it down too:"
        if [ "$stale_screen" -eq 1 ]; then
          printf '  screen -S %s -X quit\n' "$SCREEN_SESSION" >&2
        fi
        if [ "$stale_tmux" -eq 1 ]; then
          printf '  tmux kill-session -t %s\n' "$SCREEN_SESSION" >&2
        fi
        printf '  # or use '\''clean'\'' for the full local + remote tear-down.\n' >&2
      else
        log "(The argo-proxy session manager exited along with its child;"
        log "  no screen/tmux cleanup needed.)"
      fi
      ;;
    *)
      # Fallback (e.g. lsof returned a pid but local_tunnel_status couldn't
      # classify it). Just kill what's there with the legacy warning.
      log "Killing local processes listening on :${PROXY_PORT}..."
      echo "$pids" | xargs -n1 kill 2>/dev/null || true
      sleep 1
      echo "$pids" | xargs -I{} sh -c 'kill -0 {} 2>/dev/null && kill -9 {} || true'
      ok "Killed: ${pids//$'\n'/ }"
      warn "Note: if the killed process was argo-proxy itself (not an SSH tunnel),"
      warn "  any other client pointed at this host:port has just lost its proxy."
      ;;
  esac
}

# ============================================================================
# SECTION: 22. UPDATE-MODELS + LIST-MODELS (mode_update_models, mode_list_models)
# ============================================================================
# Refreshes provider.argo.models in ~/.config/opencode/config.json from the
# live /v1/models endpoint, preserving everything else in the config.
mode_update_models() {
  # Tool-aware (was OpenCode-only). `update-models` refreshes a client's
  # in-config model list from the live /v1/models -- which is only a
  # meaningful operation for tools that ENUMERATE models in their config.
  # OpenCode does (provider.argo.models{}); Claude Code + aider choose the
  # model at runtime (--model) and have no in-config list to refresh.
  #
  # Resolve the target tool: --cli-tool wins; default opencode (the only
  # tool this supports today) for backward compatibility with the bare
  # `update-models` invocation. For tools that don't support it, print an
  # honest "not applicable" message rather than silently editing OpenCode's
  # config (which the pre-tool-aware version did).
  local _umt="${CLI_TOOL_OVERRIDE:-opencode}"
  case "$_umt" in
    opencode)
      : ;;  # supported -- fall through to the OpenCode refresh below
    claudecode)
      log "update-models: not applicable for Claude Code."
      log "  Claude Code does not enumerate models in its config; it picks the"
      log "  model at runtime via 'claude --model <name>' (or env.ANTHROPIC_MODEL)."
      log "  The proxy already serves the full list -- see:"
      log "    $(basename "$0") list-models"
      return 0 ;;
    aider)
      log "update-models: not applicable for aider (today)."
      log "  aider picks the model at runtime via 'aider --model openai/argo:<id>';"
      log "  its config lists per-model SETTINGS (temperature suppression), not a"
      log "  refreshable model picker. See served ids with:"
      log "    $(basename "$0") list-models"
      log "  (A future per-tool refresh could regenerate aider's model-settings"
      log "   from the live /v1/models; not implemented yet.)"
      return 0 ;;
    *)
      die "update-models: unknown --cli-tool '${_umt}'. Known: $(cli_tool_known_names). Only 'opencode' supports update-models today." ;;
  esac

  local cfg="${OPENCODE_CONFIG}"

  # Hard requirement: jq. Anything less is brittle for in-place JSON surgery.
  if ! command -v jq >/dev/null 2>&1; then
    err "'jq' is required for update-models (safe in-place JSON edit)."
    case "$(detect_os)" in
      macos) err "  Install with:  brew install jq" ;;
      linux) err "  Install with:  sudo apt-get install jq   # or your distro's equivalent" ;;
    esac
    die "Aborting."
  fi

  # Need a config file to update.
  if [ ! -f "$cfg" ]; then
    die "No OpenCode config at ${cfg}. Run '$(basename "$0") client' first."
  fi

  # Need a reachable proxy.
  if ! curl -fsS --max-time 3 "http://localhost:${PROXY_PORT}/health" >/dev/null 2>&1; then
    die "argo-proxy not reachable on http://localhost:${PROXY_PORT}. Start the tunnel first ('$(basename "$0") client')."
  fi

  log "Fetching /v1/models from the proxy..."
  local body; body="$(fetch_proxy_models)"
  [ -n "$body" ] || die "Empty response from /v1/models."

  # Build the new models block. Selection rules:
  #   - exclude embedding models (id contains 'embedding') -- not chat-usable
  #   - dedupe on internal_name (some are aliased multiple times)
  #   - key  = internal_name  (matches existing config style)
  #   - name = friendly id (strip 'argo:' prefix)
  #   - modalities = text+image in / text out  (matches your existing config)
  local new_models_block
  new_models_block="$(printf '%s' "$body" | jq '
    [ .data[]
      | select(.id | test("embedding") | not)
    ]
    | unique_by(.internal_name)
    | map({
        (.internal_name): {
          name: (.id | sub("^argo:"; "")),
          modalities: { input: ["text","image"], output: ["text"] }
        }
      })
    | add // {}
  ')" || die "jq failed to build the models block from /v1/models."

  local kept_count
  kept_count="$(printf '%s' "$new_models_block" | jq 'keys | length')"
  local skipped
  skipped="$(printf '%s' "$body" | jq '[.data[] | select(.id | test("embedding"))] | length')"
  log "Selected ${kept_count} chat model(s). Skipped ${skipped} embedding model(s)."

  # Show the diff against existing models so the user knows what's changing.
  local old_models_block
  old_models_block="$(jq '.provider.argo.models // {}' "$cfg")"

  local added removed
  added="$(jq -rn --argjson o "$old_models_block" --argjson n "$new_models_block" \
    '($n | keys) - ($o | keys) | join(", ")')"
  removed="$(jq -rn --argjson o "$old_models_block" --argjson n "$new_models_block" \
    '($o | keys) - ($n | keys) | join(", ")')"
  if [ -n "$added"   ]; then log "Will ADD:    ${added}";   fi
  if [ -n "$removed" ]; then log "Orphans (in config but NOT in /v1/models): ${removed}"; fi
  if [ -z "$added" ] && [ -z "$removed" ]; then
    log "Configured models already match /v1/models."
  fi

  # ---- Orphan handling -------------------------------------------------
  # Models in the user's config that no longer appear in /v1/models. The
  # writer below blindly replaces .provider.argo.models with $new, so any
  # orphan is dropped unless we explicitly merge it back in.
  #
  # Three policies, in order of precedence:
  #   1. KEEP_ORPHANS=1 (--keep-orphans / ARGO_ANYWHERE_KEEP_ORPHANS) -> keep all
  #   2. DROP_ORPHANS=1 (--drop-orphans / ARGO_ANYWHERE_DROP_ORPHANS) -> drop all
  #   3. interactive: per-orphan prompt with bulk-decision shortcuts
  if [ -n "$removed" ]; then
    # Build a JSON array of orphan keys to KEEP. Empty == drop all.
    local keep_array='[]'
    local policy="prompt"
    if [ "${KEEP_ORPHANS:-${ARGO_ANYWHERE_KEEP_ORPHANS:-0}}" = 1 ]; then
      policy="keep"
    elif [ "${DROP_ORPHANS:-${ARGO_ANYWHERE_DROP_ORPHANS:-0}}" = 1 ]; then
      policy="drop"
    fi

    case "$policy" in
      keep)
        keep_array="$(jq -n --argjson o "$old_models_block" --argjson n "$new_models_block" \
          '($o | keys) - ($n | keys)')"
        log "Keeping all $(printf '%s' "$keep_array" | jq 'length') orphan(s) (--keep-orphans)."
        ;;
      drop)
        keep_array='[]'
        warn "Dropping all $(jq -rn --argjson o "$old_models_block" --argjson n "$new_models_block" \
          '($o | keys) - ($n | keys) | length') orphan(s) (--drop-orphans)."
        ;;
      prompt)
        # Build a bash array of orphan names. We avoid the natural
        # `while read … done <<< "$orphans"` loop because `ask` (called
        # inside the loop) does its own `read`, which would consume the
        # herestring instead of stdin and silently advance the loop. With
        # an array iterator the loop body's stdin stays the user's TTY.
        local orphan_names_raw; orphan_names_raw="$(jq -rn \
          --argjson o "$old_models_block" --argjson n "$new_models_block" \
          '($o | keys) - ($n | keys) | .[]')"
        local orphan_arr=() name
        while IFS= read -r name; do
          [ -n "$name" ] && orphan_arr+=("$name")
        done <<< "$orphan_names_raw"
        local orphan_total="${#orphan_arr[@]}"

        echo >&2
        warn "${orphan_total} orphan model(s) found (in your config but not served by /v1/models):"
        local i=1 friendly
        for name in "${orphan_arr[@]}"; do
          # Show the friendly 'name' field too, if present in the OLD config.
          friendly="$(jq -r --arg k "$name" '.[$k].name // $k' <<< "$old_models_block")"
          if [ "$friendly" != "$name" ]; then
            printf '  %d) %-30s  (display name: %s)\n' "$i" "$name" "$friendly" >&2
          else
            printf '  %d) %s\n' "$i" "$name" >&2
          fi
          i=$((i+1))
        done

        cat >&2 <<EOF

  For each orphan you can [k]eep or [d]rop. Bulk shortcuts:
    [K] keep ALL remaining orphans   [D] drop ALL remaining orphans
    [a] abort update-models entirely
EOF
        # Build the keep list. Default per-orphan choice is [k]eep, so an
        # accidental Enter doesn't lose a model.
        local keep_list=""
        local bulk=""  # set to "keep" or "drop" once user picks K or D
        i=1
        for name in "${orphan_arr[@]}"; do
          if [ "$bulk" = "keep" ]; then
            keep_list="${keep_list}${name}"$'\n'
            log "  ${name}: keeping (bulk)"
          elif [ "$bulk" = "drop" ]; then
            log "  ${name}: dropping (bulk)"
          else
            local choice
            choice="$(ask "  ${i}/${orphan_total} ${name} [k/d/K/D/a, default=keep]:" "k")"
            case "$choice" in
              k|"") keep_list="${keep_list}${name}"$'\n'; log "    -> keeping" ;;
              d)    log "    -> dropping" ;;
              K)    bulk="keep"; keep_list="${keep_list}${name}"$'\n'
                    log "    -> keeping ALL remaining" ;;
              D)    bulk="drop"; log "    -> dropping ALL remaining" ;;
              a|A)  die "Aborted at orphan-review step." ;;
              *)    warn "    unrecognized: '${choice}'; treating as [k]eep"
                    keep_list="${keep_list}${name}"$'\n' ;;
            esac
          fi
          i=$((i+1))
        done

        # Convert keep_list (newline-delimited) to a JSON array.
        if [ -n "$keep_list" ]; then
          keep_array="$(printf '%s' "$keep_list" | sed '/^$/d' | jq -R . | jq -s .)"
        else
          keep_array='[]'
        fi
        local kept_n; kept_n="$(printf '%s' "$keep_array" | jq 'length')"
        local dropped_n=$((orphan_total - kept_n))
        log "Orphan review: keeping ${kept_n}, dropping ${dropped_n}."
        ;;
    esac

    # Splice kept orphans (with their original config entries) into the
    # new models block before passing to the writer.
    new_models_block="$(jq -n \
      --argjson new "$new_models_block" \
      --argjson old "$old_models_block" \
      --argjson keep "$keep_array" \
      '$new + ($old | with_entries(select(.key as $k | $keep | index($k))))')"
  fi

  # Stash the (possibly orphan-augmented) new models block in a global so
  # the writer closure can find it (handle_config_file invokes the writer
  # once for diff and again on overwrite).
  ARGO_NEW_MODELS_BLOCK="$new_models_block"
  ARGO_SOURCE_CFG="$cfg"
  # shellcheck disable=SC2329  # called indirectly via "$writer" in handle_config_file
  _writer_models_update() {
    jq --argjson new "$ARGO_NEW_MODELS_BLOCK" \
       '.provider.argo.models = $new' "$ARGO_SOURCE_CFG" > "$1"
  }

  handle_config_file "$cfg" "OpenCode config (models block)" _writer_models_update

  unset -f _writer_models_update
  unset ARGO_NEW_MODELS_BLOCK ARGO_SOURCE_CFG

  ok "Done. Restart OpenCode to pick up the new model list."
}

# ----------------------------------------------------------------------------
# mode_list_models: tabulate the models the proxy is exposing on /v1/models.
#
# Read-only sibling of mode_update_models. Where update-models WRITES the
# OpenCode config, list-models just SHOWS what is available, optionally
# cross-referenced against the existing OpenCode config (so the user can
# see at a glance which models are present, configured, and orphaned --
# without having to run `update-models` and let it walk the prompt flow).
#
# Output destination:
#   * default: pretty column-aligned table to stdout
#   * --output FILE: same content, written to FILE (no terminal colors)
#
# Output format (--format):
#   * text  (default): aligned columns, human-readable
#   * tsv:             tab-separated, one model per line, header row included;
#                      stable column order matching the text format. Suitable
#                      for `cut`/`awk` consumption.
#   * json:            the filtered+annotated model list as a JSON array.
#                      Each element: {internal_name, id, provider, modalities,
#                      configured}. The raw /v1/models response is NOT
#                      reproduced; that's what `curl .../v1/models` is for.
#
# Filters:
#   * embeddings are excluded by default (matches update-models semantics).
#     Pass --include-embeddings to include them.
#
# Cross-reference column ("Configured?"):
#   * present when ~/.config/opencode/config.json exists.
#   * three states: 'yes' (present + served), 'no' (served but not in cfg),
#     'orphan' (in cfg but NOT served -- this would be DROPPED by a
#     default update-models run).
#   * the table also includes a trailing row listing orphans that don't
#     appear elsewhere (since they're not in /v1/models). When --format=tsv
#     or --format=json, orphans appear as regular rows with id="" + the
#     'orphan' configured-state.
#
# Provider inference (no upstream metadata available on /v1/models for this):
#   * id starts with 'argo:gpt' or contains 'gpt' / 'o1' / 'o3' / 'o4'  -> openai
#   * id starts with 'argo:claude' or contains 'claude'                 -> claude
#   * id starts with 'argo:gemini' or contains 'gemini'                 -> gemini
#   * id contains 'embedding' / 'embed'                                 -> embedding
#   * otherwise                                                         -> other
#   This heuristic matches the names visible at v3.0.4. If upstream adds
#   a new family, the row's provider column reads 'other'; the row is
#   still listed.
#
# Modalities (no upstream metadata for vision/non-vision; reasonable
# defaults):
#   * embedding rows -> 'text->vector'
#   * other rows     -> 'text+image->text'  (matches update-models's
#                       write-out: every chat model is configured as
#                       multimodal text+image input, text output).
#
# Globals consumed: PROXY_PORT, OPENCODE_CONFIG.
# Globals mutated: none.
# Exit codes: 0 success; 1 unreachable proxy / empty body / write error.
mode_list_models() {
  # Hard requirement: jq. Same justification as mode_update_models -- we are
  # parsing structured JSON from /v1/models. A pure-bash fallback would
  # silently skew the table.
  if ! command -v jq >/dev/null 2>&1; then
    err "'jq' is required for list-models (parses /v1/models JSON)."
    case "$(detect_os)" in
      macos) err "  Install with:  brew install jq" ;;
      linux) err "  Install with:  sudo apt-get install jq   # or your distro's equivalent" ;;
    esac
    die "Aborting."
  fi

  # Need a reachable proxy. Same probe pattern as mode_update_models.
  if ! curl -fsS --max-time 3 "http://localhost:${PROXY_PORT}/health" >/dev/null 2>&1; then
    die "argo-proxy not reachable on http://localhost:${PROXY_PORT}. Start the tunnel first ('$(basename "$0") client')."
  fi

  local body; body="$(fetch_proxy_models)"
  [ -n "$body" ] || die "Empty response from /v1/models."

  # Build the filtered+annotated array. We do the filtering + dedup + provider
  # inference + modalities inference in one jq pipeline so the same array is
  # the single source of truth for all three output formats.
  #
  # The 'configured' field is set per row by a second pass below (after we
  # load the OpenCode config); set to 'no' here as the default.
  local include_embed_filter='select(.id | test("embedding") | not)'
  if [ "${LIST_MODELS_INCLUDE_EMBED:-0}" = 1 ]; then
    include_embed_filter='.'
  fi

  local annotated_json
  annotated_json="$(printf '%s' "$body" | jq --argjson include_embed "${LIST_MODELS_INCLUDE_EMBED:-0}" '
    def provider_of:
      if   test("embedding"; "i") then "embedding"
      elif test("claude"; "i")    then "claude"
      elif test("gemini"; "i")    then "gemini"
      elif test("gpt|^o[1-9]|^argo:o[1-9]"; "i") then "openai"
      else "other"
      end;
    def modalities_of(prov):
      if prov == "embedding" then "text->vector"
      else "text+image->text"
      end;
    [ .data[]
      | select($include_embed == 1 or (.id | test("embedding") | not))
    ]
    | unique_by(.internal_name)
    | map({
        internal_name: .internal_name,
        id: (.id | sub("^argo:"; "")),
        provider: (.id | provider_of),
        modalities: ((.id | provider_of) as $p | modalities_of($p)),
        configured: "no"
      })
    | sort_by(.provider, .internal_name)
  ')" || die "jq failed to build the annotated model list from /v1/models."

  # Cross-reference with OpenCode config (if it exists). We mark each
  # served model as configured=yes/no and then APPEND orphan rows (in
  # config but not served) at the end so the user sees them too.
  local cfg="${OPENCODE_CONFIG}"
  local have_cfg=0
  local cfg_keys_json='[]'
  if [ -f "$cfg" ]; then
    have_cfg=1
    cfg_keys_json="$(jq -c '.provider.argo.models // {} | keys' "$cfg" 2>/dev/null || printf '%s' '[]')"
  fi

  if [ "$have_cfg" = 1 ]; then
    annotated_json="$(printf '%s' "$annotated_json" | jq --argjson cfg "$cfg_keys_json" '
      ($cfg | map(. as $k | { ($k): true }) | add // {}) as $cfgset
      | map(.configured = (if $cfgset[.internal_name] then "yes" else "no" end))
    ')"
    # Append orphan rows (in cfg, not served). These get id="", provider
    # "(orphan)", modalities "?".
    local served_keys_json
    served_keys_json="$(printf '%s' "$annotated_json" | jq -c 'map(.internal_name)')"
    local orphans_json
    orphans_json="$(jq -cn --argjson cfg "$cfg_keys_json" --argjson srv "$served_keys_json" '
      ($srv | map(. as $k | { ($k): true }) | add // {}) as $srvset
      | $cfg | map(select($srvset[.] | not))
            | map({ internal_name: ., id: "", provider: "(orphan)",
                    modalities: "?", configured: "orphan" })
    ')"
    annotated_json="$(jq -cn --argjson rows "$annotated_json" --argjson orph "$orphans_json" \
      '$rows + $orph')"
  fi

  # ---- Emit -------------------------------------------------------------
  local fmt="${LIST_MODELS_FORMAT:-text}"
  local out="${LIST_MODELS_OUTPUT:-}"
  local rendered

  case "$fmt" in
    json)
      rendered="$(printf '%s' "$annotated_json" | jq .)"
      ;;
    tsv)
      # Header + rows. The configured column is omitted when no OpenCode
      # config exists.
      if [ "$have_cfg" = 1 ]; then
        rendered="$(
          printf 'internal_name\tid\tprovider\tmodalities\tconfigured\n'
          printf '%s' "$annotated_json" | jq -r '.[] |
            [.internal_name, .id, .provider, .modalities, .configured] | @tsv'
        )"
      else
        rendered="$(
          printf 'internal_name\tid\tprovider\tmodalities\n'
          printf '%s' "$annotated_json" | jq -r '.[] |
            [.internal_name, .id, .provider, .modalities] | @tsv'
        )"
      fi
      ;;
    text|"")
      # Column-aligned via printf. Column widths are computed from the
      # data (with sane minimums) so wide names don't blow the layout.
      # We push the TSV through awk for the alignment pass; awk is part
      # of POSIX and we already rely on it elsewhere.
      local tsv_payload
      if [ "$have_cfg" = 1 ]; then
        tsv_payload="$(
          printf 'INTERNAL_NAME\tID\tPROVIDER\tMODALITIES\tCONFIGURED\n'
          printf '%s' "$annotated_json" | jq -r '.[] |
            [.internal_name, .id, .provider, .modalities, .configured] | @tsv'
        )"
      else
        tsv_payload="$(
          printf 'INTERNAL_NAME\tID\tPROVIDER\tMODALITIES\n'
          printf '%s' "$annotated_json" | jq -r '.[] |
            [.internal_name, .id, .provider, .modalities] | @tsv'
        )"
      fi
      rendered="$(printf '%s\n' "$tsv_payload" | awk -F '\t' '
        { for (i=1;i<=NF;i++) { if (length($i) > w[i]) w[i]=length($i); rows[NR,i]=$i; cols=NF } }
        END {
          for (r=1;r<=NR;r++) {
            line = ""
            for (i=1;i<=cols;i++) {
              sep = (i==cols) ? "" : "  "
              line = line sprintf("%-*s%s", w[i], rows[r,i], sep)
            }
            print line
          }
        }
      ')"
      # Wrap with a count footer for the screen path.
      local total_count served_count orphan_count
      total_count="$(printf '%s' "$annotated_json" | jq 'length')"
      served_count="$(printf '%s' "$annotated_json" | jq '[.[] | select(.configured != "orphan")] | length')"
      orphan_count="$(printf '%s' "$annotated_json" | jq '[.[] | select(.configured == "orphan")] | length')"
      local footer=""
      if [ "$have_cfg" = 1 ]; then
        footer="$(printf '\n%s\n' "Total: ${total_count} rows  (served: ${served_count}; orphaned-in-config: ${orphan_count})")"
      else
        footer="$(printf '\n%s\n' "Total: ${total_count} models  (no OpenCode config found at ${cfg}; 'configured' column omitted)")"
      fi
      rendered="${rendered}${footer}"
      ;;
    *)
      die "Unknown --format value '${fmt}'. Use one of: text, tsv, json."
      ;;
  esac

  # ---- Write -----------------------------------------------------------
  if [ -n "$out" ]; then
    # Refuse to silently overwrite. Same defensive posture as other writers.
    if [ -e "$out" ] && [ "${CLEAN_ASSUME_YES:-0}" != 1 ]; then
      local choice; choice="$(ask "  Output file '${out}' exists. Overwrite? [y/N]:" "n")"
      case "$choice" in
        y|Y|yes|YES) ;;
        *) die "Aborted (existing file '${out}' kept)." ;;
      esac
    fi
    printf '%s\n' "$rendered" > "$out" \
      || die "Failed to write '${out}'."
    ok "Wrote ${out} (${fmt})."
  else
    printf '%s\n' "$rendered"
  fi
}

# ============================================================================
# SECTION: 22b. UPDATE (mode_update -- refresh installed components in place)
# ============================================================================
# Added 2026-06-24 (v2.2.1 prep) per PLAN.md D-022. A unified "update what
# we installed" surface, complementary to `update-models` (which only
# refreshes config; never installs anything) and `--force-reinstall`
# (which always wipes + rebuilds the server-side venv).
#
# The `update` subcommand:
#   * defaults to in-place upgrades (no state nuked);
#   * iterates over a registry of upgradable components
#     (UPDATE_COMPONENTS_AVAILABLE) and dispatches to per-component
#     update_<name>_component / update_<name>_cli_tool helpers;
#   * prompts the user before installing a component that isn't there
#     yet (--yes auto-confirms);
#   * follows successful argo-proxy upgrades with an automatic POST to
#     the proxy's /refresh endpoint (if a tunnel is up), so the model
#     registry reflects the new version without restarting the proxy or
#     running `update-models`;
#   * NEVER touches user-owned config files (those are the job of
#     `update-models` and the per-tool config writers in client/setup);
#   * exposes a --check mode that reports installed-vs-latest without
#     installing anything.
#
# Per-component upgrade idiom (the "lossless" path):
#   * argo-proxy: try `argo-proxy update install` first (upstream's own
#                 self-updater, available since ~v3.0); fall back to
#                 `pip install --upgrade argo-proxy`. Both paths preserve
#                 the venv and the config; pip --upgrade also handles
#                 dependency upgrades cleanly.
#   * OpenCode:   `brew upgrade sst/tap/opencode` if the binary came
#                 from a brew prefix; else re-run the upstream
#                 `curl -fsSL https://opencode.ai/install | bash` (it's
#                 idempotent and upgrades in place).
#   * Claude Code: re-run `curl -fsSL https://claude.ai/install.sh | bash`
#                 (Anthropic's installer is idempotent and the documented
#                 upgrade path; the in-tool `/upgrade` exists but isn't
#                 scriptable).
#
# When the in-place upgrade fails, the per-component helper prints a
# hint pointing at `--force-reinstall` (for argo-proxy) or the
# component's documented manual recovery; it does NOT auto-escalate.
#
# Registry: UPDATE_COMPONENTS_AVAILABLE lists every upgradable component
# in display order. CLI tools from CLI_TOOLS_AVAILABLE are auto-included
# (their update_<name>_cli_tool helper, if present, is called); the
# server-side argo-proxy component is registered explicitly because it's
# not a per-tool CLI dispatcher.

UPDATE_COMPONENTS_AVAILABLE=(
  "argo-anywhere|argo-anywhere.sh itself (the script; canonical install at ~/.argo_anywhere/)"
  "argoproxy|argo-proxy (server-side; on the ANL compute node)"
  "opencode|OpenCode CLI (laptop-side)"
  "claudecode|Claude Code CLI (laptop-side)"
  "aider|aider CLI (laptop-side)"
)

# update_component_is_known <name>: returns 0 if <name> is registered.
update_component_is_known() {
  local want="$1" entry name
  for entry in "${UPDATE_COMPONENTS_AVAILABLE[@]}"; do
    name="${entry%%|*}"
    [ "$name" = "$want" ] && return 0
  done
  return 1
}

# update_component_known_names: comma-separated registry, for errors.
update_component_known_names() {
  local entry name out=""
  for entry in "${UPDATE_COMPONENTS_AVAILABLE[@]}"; do
    name="${entry%%|*}"
    out="${out:+${out}, }${name}"
  done
  printf '%s' "$out"
}

# _version_ge <a> <b>: returns 0 iff version a >= version b (semver-ish).
# Implemented via `sort -V` (GNU + BSD both ship version-sort since macOS
# 10.13 / Ubuntu 16.04). Used by update_*_component helpers + by the
# audit UP-02 soft-floor check (queued).
#
# Tolerates: "3.0.1", "v3.0.1", "3.0.1.dev0", "3.1.2-rc1". Returns 1 on
# any unparseable input (treats unknown as "older" to bias toward an
# upgrade attempt).
_version_ge() {
  local a="${1#v}" b="${2#v}"
  [ -z "$a" ] || [ -z "$b" ] && return 1
  # `printf %s\n` + `sort -V | tail -n1` is bash-3.2-safe (no mapfile).
  local _top
  _top="$( { printf '%s\n%s\n' "$a" "$b" | sort -V | tail -n1; } 2>/dev/null || true )"
  [ "$_top" = "$a" ]
}

# _extract_version <text>: extract the first dotted-numeric version
# token (e.g. "2.1.187", "3.0.0", "1.17.9") from arbitrary text. Used
# to normalize `--version` output across tools that decorate the
# version with vendor names or parenthesized labels:
#   * `argo-proxy --version`  -> "argo-proxy 3.0.0"
#   * `claude --version`      -> "2.1.187 (Claude Code)"
#   * `opencode --version`    -> "1.17.9"
# Returns the empty string when no version-shaped token is present
# (so callers can fall back to "unknown" rather than print a garbage
# value).
_extract_version() {
  printf '%s' "$1" | grep -oE '[0-9]+\.[0-9]+(\.[0-9]+)?([.-][A-Za-z0-9]+)*' | head -n1
}

# _pypi_latest_version <package>: print the latest stable version of
# <package> on PyPI, or empty string on failure. Used by `update --check`
# for argo-proxy. Best-effort: no network failure is fatal (the worst
# case is we show "(upstream unknown)" instead of "(upstream X.Y.Z)").
_pypi_latest_version() {
  local pkg="$1"
  local latest=""
  if command -v curl >/dev/null 2>&1; then
    latest="$( { curl -fsS --max-time 5 "https://pypi.org/pypi/${pkg}/json" \
                 | { command -v jq >/dev/null 2>&1 && jq -r '.info.version' \
                     || python3 -c 'import sys,json;print(json.load(sys.stdin)["info"]["version"])' 2>/dev/null; }; } 2>/dev/null || true )"
  fi
  [ "$latest" = "null" ] && latest=""
  printf '%s' "$latest"
}

# _update_prompt_install <component_label>: ask whether to install a
# missing component. Honors $UPDATE_ASSUME_YES (--yes/-y) for non-
# interactive runs. Returns 0 (install) or 1 (skip).
_update_prompt_install() {
  local label="$1"
  if [ "${UPDATE_ASSUME_YES:-0}" = 1 ]; then
    log "${label} is not installed. --yes was set; installing."
    return 0
  fi
  warn "${label} is not installed on this machine."
  local reply
  reply="$(ask "Install it now? [y/N]:" "n")"
  case "$reply" in
    y|Y|yes|YES) return 0 ;;
    *) return 1 ;;
  esac
}

# ----------------------------------------------------------------------------
# update_argoproxy_component: in-place argo-proxy upgrade on the compute
# node. Lossless: does NOT touch ~/.config/argoproxy/config.yaml and does
# NOT recreate $HOME/argovenv (that's `--force-reinstall`'s job).
#
# Strategy:
#   * If we're running ON the target compute node already (the on-node
#     short-circuit case): invoke ensure_argoproxy_installed() if argo-
#     proxy is missing; else try `argo-proxy update install` then
#     `pip install --upgrade argo-proxy` in sequence.
#   * Else: SSH to the node and run the same logic remotely via a
#     small inline payload (no scp; the payload is short enough to
#     embed). Same SSH plumbing as remote_bootstrap.
#
# After a successful upgrade (and only when a local tunnel is up and
# /health answers), POST to /refresh so the running proxy picks up any
# new model entries in the upstream Argo gateway's registry (the
# argo-proxy ModelRegistry refreshes from `${argo_base_url}/api/v1/models/`
# on /refresh).
#
# Globals consumed: PROXY_PORT, ARGO_ANYWHERE_USER, ARGO_ANYWHERE_NODE
# (via cache or --user / --node), UPDATE_CHECK_ONLY, UPDATE_ASSUME_YES.
# Exit codes: 0 on successful upgrade (or up-to-date); non-zero on
# unrecoverable failure.
update_argoproxy_component() {
  local check_only="${UPDATE_CHECK_ONLY:-0}"

  # Resolve identity (username + node). Same precedence as mode_clean's
  # remote step: env > cache > die-with-hint.
  local user node
  user="$(resolve_username)"
  ARGO_ANYWHERE_USER="$user"

  if [ -n "${ARGO_ANYWHERE_NODE:-}" ]; then
    node="$ARGO_ANYWHERE_NODE"
  elif [ -r "${HOME}/.config/argo_anywhere/node" ]; then
    node="$(cat "${HOME}/.config/argo_anywhere/node" 2>/dev/null || true)"
  else
    node=""
  fi

  # On-node short-circuit. If we're already on the target compute node
  # (or the node is empty and we're on SOME compute node), run locally.
  if [ -z "$node" ] || host_is_target "$node"; then
    log "Running argo-proxy update locally (this host = ${node:-$(this_host_fqdn)})."
    _update_argoproxy_inproc "$check_only"
    local rc=$?
    [ "$rc" -eq 0 ] && _update_argoproxy_post_refresh
    return $rc
  fi

  # Remote path. Build a small bash payload and run via SSH.
  # First, peek at upstream so the user sees the comparison from this side
  # (the remote payload only knows about the installed version; it doesn't
  # have curl-to-PyPI semantics, and even if it did, doing it laptop-side
  # saves a round trip on --check and surfaces network problems sooner).
  local latest_pypi; latest_pypi="$(_pypi_latest_version argo-proxy)"
  if [ -n "$latest_pypi" ]; then
    log "argo-proxy upstream latest (PyPI): ${latest_pypi}"
  fi

  log "Updating argo-proxy on ${node} (user=${user})..."
  ssh_attempt_pre || die "Aborted: argo-proxy update on ${node} (SSH failure lock active)."

  local venv_remote='$HOME/argovenv'
  local payload
  payload="$(_update_argoproxy_remote_payload "$check_only")"

  # shellcheck disable=SC2046
  if ssh -o StrictHostKeyChecking=accept-new \
         $(ssh_args "$user" "$node") "${user}@${node}" \
         "bash -s" <<< "$payload"; then
    ssh_attempt_ok
  else
    ssh_attempt_fail
    err "argo-proxy update on ${node} failed."
    err "  If the in-place upgrade is broken (dependency conflict, etc.),"
    err "  fall back to:  bash $(basename "$0") --force-reinstall server"
    err "  (will wipe ${venv_remote} on the node and rebuild from scratch)"
    return 1
  fi

  # Post-upgrade: ask the running proxy to refresh its model registry.
  # Only meaningful when --check was NOT set.
  if [ "$check_only" != 1 ]; then
    _update_argoproxy_post_refresh
  fi
  return 0
}

# _update_argoproxy_inproc <check_only>: the local (or on-node)
# equivalent of the remote payload. Same upgrade idiom; reused from the
# on-node short-circuit branch.
_update_argoproxy_inproc() {
  local check_only="$1"
  local venv; venv="$(eval echo "$VENV_PATH")"

  if [ ! -x "${venv}/bin/argo-proxy" ]; then
    if [ "$check_only" = 1 ]; then
      warn "argo-proxy is not installed in ${venv}."
      log "  Upstream latest (PyPI): $(_pypi_latest_version argo-proxy || echo unknown)"
      return 0
    fi
    if _update_prompt_install "argo-proxy (server-side, in ${venv})"; then
      ensure_argoproxy_installed
      return $?
    fi
    return 1
  fi

  local installed
  installed="$(_extract_version "$( { "${venv}/bin/argo-proxy" --version 2>&1; } || true )")"
  local latest; latest="$(_pypi_latest_version argo-proxy)"
  log "argo-proxy installed: ${installed:-unknown}; PyPI latest: ${latest:-unknown}"

  if [ "$check_only" = 1 ]; then
    if [ -n "$installed" ] && [ -n "$latest" ] && _version_ge "$installed" "$latest"; then
      ok "argo-proxy is up-to-date (${installed})."
    elif [ -n "$installed" ] && [ -n "$latest" ]; then
      warn "argo-proxy ${installed} < ${latest}; run 'update argoproxy' to upgrade."
    else
      warn "Could not determine installed vs latest; run 'update argoproxy' to attempt an upgrade."
    fi
    return 0
  fi

  if [ -n "$installed" ] && [ -n "$latest" ] && _version_ge "$installed" "$latest"; then
    ok "argo-proxy is already at the latest version (${installed}); no upgrade needed."
    return 0
  fi

  # Prefer the venv-local pip path. Rationale (verified 2026-06-24 live
  # test): `argo-proxy update install` invokes whatever `pip` it finds
  # on PATH at run time, which on a typical compute node is the system
  # / conda pip rather than the venv's pip. The result is that
  # `update install` "succeeds" but the venv's argo-proxy stays at its
  # old version (the system pip's package metadata moves, the venv
  # binary doesn't). Since the running argo-proxy IS the venv's binary
  # (started by mode_server via `${venv}/bin/argo-proxy serve`),
  # missing the venv upgrade defeats the purpose of `update argoproxy`.
  log "Running '${venv}/bin/pip install --upgrade argo-proxy' (venv-targeted)..."
  if "${venv}/bin/pip" install --upgrade argo-proxy; then
    ok "argo-proxy upgraded to $(_extract_version "$("${venv}/bin/argo-proxy" --version 2>&1)")."
    return 0
  fi

  # Fallback: upstream self-updater. Only fires if the venv pip path
  # failed entirely (e.g. PyPI unreachable from the venv environment
  # but reachable via the system pip's network config).
  if "${venv}/bin/argo-proxy" update --help >/dev/null 2>&1; then
    warn "venv pip failed; falling back to 'argo-proxy update install'."
    warn "  (NOTE: this may upgrade the system pip's argo-proxy instead of the venv's;"
    warn "   verify the new version with: ${venv}/bin/argo-proxy --version)"
    if "${venv}/bin/argo-proxy" update install; then
      ok "argo-proxy upgrade complete (verify version with: ${venv}/bin/argo-proxy --version)."
      return 0
    fi
  fi

  err "Both 'argo-proxy update install' and pip upgrade failed."
  err "  Try: bash $(basename "$0") --force-reinstall server"
  return 1
}

# _update_argoproxy_remote_payload <check_only>: emit the bash script
# that runs on the compute node. Self-contained (does not depend on
# ARGO_ANYWHERE_* env on the remote side beyond what bash gives by
# default). Returns the script body on stdout.
#
# This stays small enough to embed via `ssh ... bash -s <<< "$payload"`
# rather than scp'ing a separate file; ~30 lines of bash with no
# heredocs of its own.
_update_argoproxy_remote_payload() {
  local check_only="$1"
  cat <<REMOTE_PAYLOAD
set -eu
venv="\$HOME/argovenv"
if [ ! -x "\$venv/bin/argo-proxy" ]; then
  echo "[remote] ERROR: argo-proxy is not installed at \$venv/bin/argo-proxy" >&2
  echo "[remote]   Run 'bash $(basename "$0") --force-reinstall client' from the laptop" >&2
  echo "[remote]   to install it cleanly." >&2
  exit 1
fi
# Extract first dotted-numeric token from --version (robust to vendor
# prefixes like "argo-proxy 3.0.0" and to update-prompt banners that
# upstream argo-proxy injects on stderr).
_extract_v() { printf '%s' "\$1" | grep -oE '[0-9]+\.[0-9]+(\.[0-9]+)?' | head -n1; }
installed=\$(_extract_v "\$("\$venv/bin/argo-proxy" --version 2>&1)")
echo "[remote] argo-proxy installed (venv): \$installed"
if [ "$check_only" = 1 ]; then
  echo "[remote] --check mode: not upgrading."
  exit 0
fi
# Prefer venv-local pip path (see 2026-06-24 live-test note in the
# laptop-side _update_argoproxy_inproc helper for the rationale:
# 'argo-proxy update install' upgrades the wrong pip on compute nodes).
echo "[remote] Running '\$venv/bin/pip install --upgrade argo-proxy' (venv-targeted)..."
if "\$venv/bin/pip" install --upgrade argo-proxy; then
  new_installed=\$(_extract_v "\$("\$venv/bin/argo-proxy" --version 2>&1)")
  echo "[remote] OK: venv argo-proxy now at \$new_installed"
  exit 0
fi
# Fallback to upstream self-updater (will likely hit the system pip
# rather than the venv pip; surfaced as a WARN above on the laptop side).
if "\$venv/bin/argo-proxy" update --help >/dev/null 2>&1; then
  echo "[remote] WARN: venv pip failed; falling back to 'argo-proxy update install'." >&2
  if "\$venv/bin/argo-proxy" update install; then
    new_installed=\$(_extract_v "\$("\$venv/bin/argo-proxy" --version 2>&1)")
    echo "[remote] OK (verify): venv argo-proxy reports \$new_installed"
    exit 0
  fi
fi
echo "[remote] ERROR: all upgrade paths failed." >&2
exit 1
REMOTE_PAYLOAD
}

# _update_argoproxy_post_refresh: POST /refresh to the local tunnel so
# the running argo-proxy re-pulls the upstream model list. Silently
# skips if no tunnel is up (the upgrade still succeeded; the user will
# pick up new models the next time the proxy is restarted).
_update_argoproxy_post_refresh() {
  if ! curl -fsS --max-time 3 "http://localhost:${PROXY_PORT}/health" >/dev/null 2>&1; then
    log "No local tunnel to :${PROXY_PORT}; skipping /refresh."
    log "  (New models will appear on next 'client' / 'tunnel' or proxy restart.)"
    return 0
  fi
  log "POST http://localhost:${PROXY_PORT}/refresh ..."
  if curl -fsS --max-time 10 -X POST "http://localhost:${PROXY_PORT}/refresh" >/dev/null 2>&1; then
    ok "argo-proxy model registry refreshed."
    log "  Run '$(basename "$0") list-models' to see what's now available."
    log "  Run '$(basename "$0") update-models' to add new models to your OpenCode config."
  else
    warn "POST /refresh failed (older argo-proxy versions don't have this endpoint;"
    warn "  restart the proxy or run 'client' / 'tunnel' again to pick up new models)."
  fi
}

# ----------------------------------------------------------------------------
# update_argo_anywhere_component: in-place upgrade of argo-anywhere.sh
# itself (the script the user is running).
#
# Target path resolution (per PLAN.md D-023):
#   * default: $ARGO_INSTALL_SCRIPT (~/.argo_anywhere/bin/argo-anywhere.sh).
#   * if the canonical install is missing, prompt the user to install
#     it first (one-shot bootstrap; same machinery as
#     maybe_bootstrap_canonical_install). --yes auto-confirms.
#
# Upstream resolution:
#   * GET ${PROJECT_RELEASES_API} -> tag_name -> raw URL at that tag.
#   * Fall back to PROJECT_DEFAULT_BRANCH (main) if the API call fails
#     or no releases exist. WARN the user when falling back so they
#     know they're getting development-branch code.
#
# Atomicity:
#   * Fetch to a temp file in the SAME directory as the target (so
#     `mv` is rename(2) atomic on the same filesystem).
#   * Validate the fetched file before replacing:
#       1. `bash -n` parses cleanly
#       2. Contains a `SCRIPT_VERSION=` line (sanity: we got a real
#          script, not an HTML error page)
#       3. File size > 50 KB (defensive: the real script is ~370 KB;
#          a tiny response is suspect)
#   * Backup the existing target as ${target}.bak.<timestamp> before
#     overwriting (matches the handle_config_file backup convention
#     used elsewhere).
#
# Refuses to operate on a dirty git working tree (defensive: the user
# may be running from a git checkout and the script would clobber
# uncommitted edits).
#
# Honors UPDATE_CHECK_ONLY (report-only) and UPDATE_ASSUME_YES (skip
# install prompts).
update_argo_anywhere_component() {
  local check_only="${UPDATE_CHECK_ONLY:-0}"

  # D-030a: the package (pipx/pip) owns the runtime; the engine's self-update
  # is dormant here. Report/redirect instead of rewriting a second copy (and
  # skip the GitHub-tag probe entirely, which is meaningless under the package).
  if [ "${ARGO_ANYWHERE_PACKAGED:-0}" = 1 ]; then
    if [ "$check_only" = 1 ]; then
      log "argo-anywhere: engine v${SCRIPT_VERSION}; release version managed by pipx/pip."
      log "  Check for upgrades with:  pipx upgrade argo-anywhere"
    else
      _packaged_use_pipx_hint update
    fi
    return 0
  fi

  log "Current script: argo-anywhere.sh v${SCRIPT_VERSION}"

  # Resolve upstream latest tag. Two-step probe:
  #   1. /releases/latest  -- the documented API endpoint. This project
  #      does NOT use GitHub Releases UI today (release process tags
  #      via `git tag` only; see PLAN.md "Release process"), so this
  #      typically 404s. Try anyway in case the convention changes.
  #   2. /tags  -- lists all git tags newest-first. Pick the first one
  #      that matches a vX.Y.Z (or vX.Y.Z-rcN) shape; skip non-version
  #      tags if any exist.
  # Fall back to PROJECT_DEFAULT_BRANCH (main) only if BOTH probes fail.
  local latest_tag=""
  if command -v curl >/dev/null 2>&1; then
    latest_tag="$( { curl -fsS --max-time 5 "$PROJECT_RELEASES_API" 2>/dev/null \
                     | grep -oE '"tag_name"[[:space:]]*:[[:space:]]*"[^"]+"' \
                     | head -n1 | sed -E 's/.*"([^"]+)"$/\1/'; } || true )"
    if [ -z "$latest_tag" ]; then
      # Fall back to /tags (the project's actual release convention).
      latest_tag="$( { curl -fsS --max-time 5 \
                         "https://api.github.com/repos/${PROJECT_REPO}/tags" 2>/dev/null \
                       | grep -oE '"name"[[:space:]]*:[[:space:]]*"v[0-9]+\.[0-9]+\.[0-9]+[A-Za-z0-9.-]*"' \
                       | head -n1 | sed -E 's/.*"(v[^"]+)"$/\1/'; } || true )"
    fi
  fi
  local latest_ver="" latest_ref=""
  if [ -n "$latest_tag" ]; then
    latest_ver="$(_extract_version "$latest_tag")"
    latest_ref="$latest_tag"
    log "Upstream latest tag: ${latest_tag} (version: ${latest_ver:-unknown})"
  else
    warn "Could not resolve a release tag from GitHub; will fall back to '${PROJECT_DEFAULT_BRANCH}' branch tip."
    warn "  (Network problem, or the repo has no version-shaped tags.)"
    latest_ref="$PROJECT_DEFAULT_BRANCH"
  fi

  # --check: compare and exit, no installs.
  if [ "$check_only" = 1 ]; then
    if [ -n "$latest_ver" ]; then
      if _version_ge "$SCRIPT_VERSION" "$latest_ver"; then
        ok "argo-anywhere.sh is up-to-date (${SCRIPT_VERSION} >= ${latest_ver})."
      else
        warn "argo-anywhere.sh ${SCRIPT_VERSION} < ${latest_ver}; run 'update argo-anywhere' to upgrade."
      fi
    else
      log "Cannot compare versions (upstream unreachable); run 'update argo-anywhere' to attempt anyway."
    fi
    # Also report on the canonical install (separate from $0).
    if canonical_install_present; then
      local installed_ver
      installed_ver="$(_extract_version "$( { grep -m1 -E '^SCRIPT_VERSION=' "$ARGO_INSTALL_SCRIPT" 2>/dev/null; } || true )")"
      log "Canonical install at ${ARGO_INSTALL_SCRIPT}: v${installed_ver:-unknown}"
    else
      warn "Canonical install at ${ARGO_INSTALL_DIR} does NOT exist yet."
      warn "  Run '$(basename "$0") client' (any subcommand that bootstraps) OR"
      warn "  re-run '$(basename "$0") update argo-anywhere' (without --check) to install it."
    fi
    return 0
  fi

  # If canonical install is missing, offer to bootstrap.
  if ! canonical_install_present; then
    if _update_prompt_install "argo-anywhere.sh canonical install (${ARGO_INSTALL_DIR})"; then
      # Reuse the bootstrap helper, temporarily clearing the on-node
      # short-circuit so it always runs (the user explicitly asked).
      ARGO_ANYWHERE_SKIP_BOOTSTRAP=0 maybe_bootstrap_canonical_install
      if ! canonical_install_present; then
        err "Bootstrap did not complete; cannot continue with the upgrade."
        return 1
      fi
    else
      return 1
    fi
  fi

  local target="$ARGO_INSTALL_SCRIPT"

  # Refuse if the target is inside a git working tree with uncommitted
  # changes. Defensive: if the user is running from a git checkout AND
  # the target somehow resolves to that checkout, we'd clobber their
  # uncommitted work. The canonical install path (~/.argo_anywhere/) is
  # not typically a git tree, but check anyway.
  if command -v git >/dev/null 2>&1; then
    local target_dir; target_dir="$(dirname "$target")"
    if ( cd "$target_dir" 2>/dev/null && git rev-parse --show-toplevel >/dev/null 2>&1 ); then
      local _root; _root="$( cd "$target_dir" && git rev-parse --show-toplevel )"
      if [ -n "$( cd "$_root" && git status --porcelain 2>/dev/null )" ]; then
        err "Refusing to overwrite ${target}: the directory is inside a git working tree (${_root})"
        err "  with uncommitted changes. This is almost certainly your development checkout."
        err "  If you really want to overwrite, commit/stash first, or run 'git pull' instead."
        return 1
      fi
    fi
  fi

  # Build the fetch URL.
  local fetch_url="${PROJECT_RAW_URL_PREFIX}/${latest_ref}/argo-anywhere.sh"
  if [ "$latest_ref" = "$PROJECT_DEFAULT_BRANCH" ]; then
    warn "Falling back to branch '${PROJECT_DEFAULT_BRANCH}' (no release tag resolved)."
    warn "  Fetched code may include unreleased development changes."
  fi

  log "Fetching ${fetch_url} ..."
  # Fetch to a temp file in the SAME directory as the target so the
  # final mv is rename(2) atomic on the same filesystem.
  local target_dir; target_dir="$(dirname "$target")"
  local tmp; tmp="$(mktemp "${target_dir}/argo-anywhere.sh.new.XXXXXX")" \
    || { err "Could not create temp file in ${target_dir}."; return 1; }

  # Make sure the tmp file gets removed on any error path (validation
  # failure, mv failure, etc.). Use a local RETURN trap via a single
  # wrapper to avoid stomping on other traps.
  local _cleanup_tmp
  _cleanup_tmp() { [ -n "${tmp:-}" ] && [ -f "$tmp" ] && rm -f "$tmp"; }

  if ! curl -fsSL --max-time 60 -o "$tmp" "$fetch_url"; then
    _cleanup_tmp
    err "Failed to fetch ${fetch_url}."
    err "  Check network connectivity and the GitHub repo URL (${PROJECT_REPO})."
    return 1
  fi

  # Sanity-validate the fetched file.
  local fetched_size
  fetched_size="$(wc -c < "$tmp" 2>/dev/null | tr -d ' ')"
  if [ -z "$fetched_size" ] || [ "$fetched_size" -lt 50000 ]; then
    _cleanup_tmp
    err "Fetched file is suspiciously small (${fetched_size:-0} bytes; expected >50KB)."
    err "  GitHub may have returned an error page instead of the script. Aborting."
    return 1
  fi
  if ! bash -n "$tmp" 2>/dev/null; then
    _cleanup_tmp
    err "Fetched file does not parse as bash (syntax error)."
    err "  Aborting to avoid replacing a working script with a broken one."
    return 1
  fi
  # Acceptable sentinels (any one suffices):
  #   * a `SCRIPT_VERSION=` line          (v2.2.1+ convention)
  #   * the canonical header comment      (v2.2.0 and earlier). Both the
  #     hyphenated (v3.0.0+, D-028) and the legacy underscore header are
  #     accepted so a fetch of an OLD tag still validates.
  if ! grep -q '^SCRIPT_VERSION=' "$tmp" \
     && ! grep -q '^# argo-anywhere.sh --' "$tmp" \
     && ! grep -q '^# argo_anywhere.sh --' "$tmp"; then
    _cleanup_tmp
    err "Fetched file does not look like argo-anywhere.sh (no SCRIPT_VERSION="
    err "  line and no '# argo-anywhere.sh --' header). Aborting."
    return 1
  fi

  local fetched_ver
  fetched_ver="$(_extract_version "$( { grep -m1 -E '^SCRIPT_VERSION=' "$tmp" 2>/dev/null; } || true )")"
  # Fall back to inferring from the script header line if SCRIPT_VERSION
  # is absent (pre-v2.2.1 case). The header doesn't carry a version, so
  # the best we can do is the latest_ver we resolved from the upstream
  # tag. Better than printing "unknown" in the success message.
  if [ -z "$fetched_ver" ] && [ -n "${latest_ver:-}" ]; then
    fetched_ver="$latest_ver"
  fi
  log "Fetched argo-anywhere.sh version: ${fetched_ver:-unknown}"

  # No-op if we already have this version installed at the target.
  if [ -n "$fetched_ver" ]; then
    local installed_ver
    installed_ver="$(_extract_version "$( { grep -m1 -E '^SCRIPT_VERSION=' "$target" 2>/dev/null; } || true )")"
    if [ -n "$installed_ver" ] && _version_ge "$installed_ver" "$fetched_ver"; then
      _cleanup_tmp
      ok "${target} is already at v${installed_ver} (>= fetched v${fetched_ver}); no replacement needed."
      return 0
    fi
  fi

  # Backup the existing target before overwriting (matches the
  # handle_config_file .bak.<timestamp> convention).
  if [ -f "$target" ]; then
    local backup; backup="${target}.bak.$(date +%Y%m%d-%H%M%S).$$"
    if cp "$target" "$backup" 2>/dev/null; then
      log "Backup written: ${backup}"
    else
      warn "Could not write backup of existing ${target}; proceeding anyway."
    fi
  fi

  # Atomic replace.
  if ! mv "$tmp" "$target"; then
    _cleanup_tmp
    err "Failed to mv ${tmp} -> ${target}."
    return 1
  fi
  # mktemp creates files with restrictive permissions (typically 0600).
  # Force 0755 so the new script is readable + executable for everyone
  # (matches the convention of a shell script in a PATH directory).
  chmod 0755 "$target" 2>/dev/null || true

  # Refresh the env file too (cheap; ensures any field-improvements to
  # the env helper land alongside script upgrades).
  if [ -f "$ARGO_INSTALL_ENV" ]; then
    _write_argo_env_file "$ARGO_INSTALL_ENV" || true
    chmod +x "$ARGO_INSTALL_ENV" 2>/dev/null || true
  fi

  ok "argo-anywhere.sh upgraded to v${fetched_ver:-unknown} at ${target}"

  # Self-replacement caveat: if the running script ($0) IS the target
  # we just replaced, the running process is still executing the OLD
  # in-memory copy. Tell the user.
  local self_abs; self_abs="$(_resolve_self_path)"
  if [ "$self_abs" = "$target" ]; then
    log ""
    log "  NOTE: you upgraded the script you are currently running."
    log "  The new version takes effect on the NEXT invocation; this"
    log "  process keeps running the old code until it exits."
  fi
  return 0
}

# ----------------------------------------------------------------------------
# update_opencode_cli_tool: in-place OpenCode upgrade on the laptop.
# Detects whether the installed binary came from Homebrew (path under
# /opt/homebrew/bin or /usr/local/bin) or from the curl|bash installer
# (~/.opencode/bin/opencode); picks the matching upgrade command.
#
# Honors --check (UPDATE_CHECK_ONLY=1): reports installed path + version
# without upgrading. Asks-then-installs if the binary is missing
# (--yes auto-confirms).
update_opencode_cli_tool() {
  local check_only="${UPDATE_CHECK_ONLY:-0}"

  if ! command -v opencode >/dev/null 2>&1; then
    if [ "$check_only" = 1 ]; then
      warn "OpenCode is not installed."
      return 0
    fi
    if _update_prompt_install "OpenCode"; then
      ensure_opencode_installed
      return $?
    fi
    return 1
  fi

  local bin; bin="$(command -v opencode)"
  local installed
  installed="$(_extract_version "$( { opencode --version 2>/dev/null; } || true )")"
  log "OpenCode installed: ${bin} (version ${installed:-unknown})"

  if [ "$check_only" = 1 ]; then
    log "  (run 'update opencode' to attempt an in-place upgrade)"
    return 0
  fi

  case "$bin" in
    /opt/homebrew/bin/opencode|/usr/local/bin/opencode|/home/linuxbrew/*/bin/opencode)
      if command -v brew >/dev/null 2>&1; then
        log "Brew-managed install detected; running 'brew upgrade sst/tap/opencode'..."
        if brew upgrade sst/tap/opencode; then
          ok "OpenCode upgraded: $(_extract_version "$(opencode --version 2>/dev/null)")."
          return 0
        fi
        err "brew upgrade failed."
        return 1
      fi
      warn "Binary lives in a brew prefix but 'brew' is not on PATH; falling back to curl installer."
      ;;
  esac

  log "Re-running upstream installer: curl -fsSL https://opencode.ai/install | bash ..."
  if curl -fsSL https://opencode.ai/install | bash; then
    local _v; _v="$(_extract_version "$(opencode --version 2>/dev/null || true)")"
    ok "OpenCode upgraded: ${_v:-unknown}."
    return 0
  fi
  err "OpenCode upgrade failed (upstream installer returned non-zero)."
  return 1
}

# ----------------------------------------------------------------------------
# update_claudecode_cli_tool: in-place Claude Code upgrade on the laptop.
# Anthropic ships only the curl|bash installer (idempotent and the
# documented upgrade path); no brew formula today. Same --check + prompt-
# to-install discipline as the other update_*_cli_tool helpers.
update_claudecode_cli_tool() {
  local check_only="${UPDATE_CHECK_ONLY:-0}"

  if ! command -v claude >/dev/null 2>&1; then
    if [ "$check_only" = 1 ]; then
      warn "Claude Code is not installed."
      return 0
    fi
    if _update_prompt_install "Claude Code"; then
      ensure_claudecode_installed
      return $?
    fi
    return 1
  fi

  local bin; bin="$(command -v claude)"
  local installed
  installed="$(_extract_version "$( { claude --version 2>/dev/null; } || true )")"
  log "Claude Code installed: ${bin} (version ${installed:-unknown})"

  if [ "$check_only" = 1 ]; then
    log "  (run 'update claudecode' to attempt an in-place upgrade)"
    return 0
  fi

  log "Re-running upstream installer: curl -fsSL https://claude.ai/install.sh | bash ..."
  if curl -fsSL https://claude.ai/install.sh | bash; then
    local _v; _v="$(_extract_version "$(claude --version 2>/dev/null || true)")"
    ok "Claude Code upgraded: ${_v:-unknown}."
    return 0
  fi
  err "Claude Code upgrade failed (upstream installer returned non-zero)."
  return 1
}

# ----------------------------------------------------------------------------
# update_aider_cli_tool: in-place aider upgrade on the laptop. aider ships
# via uv / pipx / the standalone installer; pick the matching upgrade
# path based on where the binary lives. Same --check + prompt-to-install
# discipline (D-022 contract) as the other update_<name>_cli_tool helpers.
update_aider_cli_tool() {
  local check_only="${UPDATE_CHECK_ONLY:-0}"

  if ! command -v aider >/dev/null 2>&1; then
    if [ "$check_only" = 1 ]; then
      warn "aider is not installed."
      return 0
    fi
    if _update_prompt_install "aider"; then
      ensure_aider_installed
      return $?
    fi
    return 1
  fi

  local bin; bin="$(command -v aider)"
  local installed
  installed="$(_extract_version "$( { aider --version 2>/dev/null; } || true )")"
  log "aider installed: ${bin} (version ${installed:-unknown})"

  if [ "$check_only" = 1 ]; then
    log "  (run 'update aider' to attempt an in-place upgrade)"
    return 0
  fi

  # Pick the upgrade path by install method (in preference order).
  case "$bin" in
    *"/uv/tools/"*|*"/.local/share/uv/"*)
      if command -v uv >/dev/null 2>&1; then
        log "uv-managed install detected; running 'uv tool upgrade aider-chat'..."
        if uv tool upgrade aider-chat; then
          ok "aider upgraded: $(_extract_version "$(aider --version 2>/dev/null || true)")."
          return 0
        fi
        err "uv tool upgrade failed."
        return 1
      fi
      ;;
  esac
  if command -v pipx >/dev/null 2>&1 && pipx list 2>/dev/null | grep -q "aider-chat"; then
    log "pipx-managed install detected; running 'pipx upgrade aider-chat'..."
    if pipx upgrade aider-chat; then
      ok "aider upgraded: $(_extract_version "$(aider --version 2>/dev/null || true)")."
      return 0
    fi
    err "pipx upgrade failed."
    return 1
  fi

  log "Re-running upstream standalone installer: curl -fsSL https://aider.chat/install.sh | sh ..."
  if curl -fsSL https://aider.chat/install.sh | sh; then
    local _v; _v="$(_extract_version "$(aider --version 2>/dev/null || true)")"
    ok "aider upgraded: ${_v:-unknown}."
    return 0
  fi
  err "aider upgrade failed (upstream installer returned non-zero)."
  return 1
}

# ----------------------------------------------------------------------------
# mode_update: dispatcher for the `update` subcommand. Per PLAN.md D-022:
# in-place upgrades of installed components; never nukes state on its
# own; prompts to install missing components (--yes auto-confirms).
#
# Argument shapes (mode-level globals set by main()'s parser):
#   * UPDATE_ALL=1               -> update every component in the registry
#   * UPDATE_COMPONENTS_ARGV=...  -> space-separated list of explicit
#                                   component names; iterate over them
#   * neither set                -> interactive picker (multi-select TBD;
#                                   today: tells the user to pass --all
#                                   or a component list, then exits 0
#                                   without doing anything)
#   * UPDATE_CHECK_ONLY=1         -> report-only mode (no installs, no
#                                   upgrades); honored per-component
#                                   by the helpers
#   * UPDATE_ASSUME_YES=1         -> non-interactive (skip install
#                                   prompts; just install missing
#                                   components)
#
# Components are processed in the order they appear in
# UPDATE_COMPONENTS_AVAILABLE so the user always sees argo-proxy first
# (the most impactful component for "I want the new claudeopus48
# model").
mode_update() {
  local check_only="${UPDATE_CHECK_ONLY:-0}"

  # Decide which components to update.
  local components=()
  if [ -n "${UPDATE_COMPONENTS_ARGV:-}" ]; then
    # Validate each name against the registry; die loud on typos.
    local _c
    for _c in $UPDATE_COMPONENTS_ARGV; do
      update_component_is_known "$_c" \
        || die "update: unknown component '${_c}'. Known: $(update_component_known_names)."
      components+=("$_c")
    done
  elif [ "${UPDATE_ALL:-0}" = 1 ]; then
    local _entry
    for _entry in "${UPDATE_COMPONENTS_AVAILABLE[@]}"; do
      components+=("${_entry%%|*}")
    done
  else
    # No --all, no explicit list: show the registry and explain the
    # available choices. Interactive multi-select picker is a future
    # enhancement; for now keep the surface narrow.
    log "Available components for 'update' (pass --all or a list):"
    local _entry _name _label
    for _entry in "${UPDATE_COMPONENTS_AVAILABLE[@]}"; do
      _name="${_entry%%|*}"; _label="${_entry#*|}"
      printf '  %-12s  %s\n' "$_name" "$_label" >&2
    done
    log ""
    log "Examples:"
    log "  $(basename "$0") update --all                     # update everything"
    log "  $(basename "$0") update argo-anywhere             # self-update the script"
    log "  $(basename "$0") update argoproxy                 # just argo-proxy"
    log "  $(basename "$0") update opencode claudecode       # explicit list"
    log "  $(basename "$0") update --check --all             # report-only"
    return 0
  fi

  if [ "$check_only" = 1 ]; then
    log "update --check: report-only; no upgrades will be performed."
  fi

  # Dispatch. Track per-component success/failure for a summary at the end.
  local _comp
  local _failed=()
  local _ok=()
  local _skipped=()
  for _comp in "${components[@]}"; do
    log ""
    log "==> update ${_comp}"
    local _rc=0
    case "$_comp" in
      argo-anywhere) update_argo_anywhere_component || _rc=$? ;;
      argoproxy)     update_argoproxy_component     || _rc=$? ;;
      opencode)      update_opencode_cli_tool       || _rc=$? ;;
      claudecode)    update_claudecode_cli_tool     || _rc=$? ;;
      aider)         update_aider_cli_tool          || _rc=$? ;;
      *) err "update: no handler for '${_comp}' (registry mismatch -- script bug)."; _rc=2 ;;
    esac
    if [ "$_rc" -eq 0 ]; then
      _ok+=("$_comp")
    elif [ "$_rc" -eq 1 ]; then
      # Convention: rc=1 = user-declined-install or recoverable failure;
      # don't treat as hard failure of the run.
      _skipped+=("$_comp")
    else
      _failed+=("$_comp")
    fi
  done

  log ""
  log "Update summary:"
  [ "${#_ok[@]}" -gt 0 ]      && ok   "  OK:      ${_ok[*]}"
  [ "${#_skipped[@]}" -gt 0 ] && warn "  Skipped: ${_skipped[*]}  (declined install or partial)"
  [ "${#_failed[@]}" -gt 0 ]  && err  "  Failed:  ${_failed[*]}"

  # Non-zero exit only on hard failures.
  [ "${#_failed[@]}" -eq 0 ]
}

# ============================================================================
# SECTION: 23. CLEAN HELPERS (_clean_rm, _clean_risky_file)
# ============================================================================
# Removes artifacts created by this script. Safe items go without per-item
# prompts (after the global confirmation); risky items (configs we modified
# but don't fully own) get a per-file prompt with safety guidance.
#
# Flags handled by main(): CLEAN_DRY_RUN, CLEAN_LOCAL_ONLY, CLEAN_ASSUME_YES,
# CLEAN_PURGE, CLEAN_PURGE_BACKUPS.

# rm helper that respects --dry-run
_clean_rm() {
  local target="$1"
  if [ "${CLEAN_DRY_RUN:-0}" = 1 ]; then
    log "  [dry-run] would remove: ${target}"
  elif rm -rf -- "$target"; then
    ok "  removed: ${target}"
  else
    warn "  failed to remove: ${target}"
  fi
}

# Per-file interactive handler for risky configs. Args: <path> <description>
# <safety_advice>
_clean_risky_file() {
  local path="$1" desc="$2" advice="$3"
  local file_present=0
  if [ -e "$path" ]; then file_present=1; fi
  # Find any backups we wrote (newest first).
  local backups=""; backups="$(ls -1t "${path}".bak.* 2>/dev/null || true)"
  local latest_bak=""; latest_bak="$(printf '%s\n' "$backups" | head -n1)"
  local has_backups=0
  if [ -n "$backups" ]; then has_backups=1; fi

  if [ "$file_present" -eq 0 ] && [ "$has_backups" -eq 0 ]; then
    return
  fi

  # ---------- Non-interactive paths ---------------------------------------
  # Two ways to skip the per-file prompt:
  #   * --purge / --purge-backups: explicit opt-in to a destructive action;
  #     we honor it regardless of -y (the user already typed it on the CLI).
  #   * -y / --yes alone: keep risky files, keep backups.
  #
  # Matrix:
  #   --purge                => delete file + backups
  #   --purge-backups        => keep file,  delete backups
  #   -y (only)              => keep file,  keep backups
  #   nothing                => interactive prompt
  if [ "${CLEAN_PURGE:-0}" = 1 ]; then
    log "${desc}  [--purge]"
    if [ "$file_present" -eq 1 ]; then _clean_rm "$path"; fi
    if [ "$has_backups" -eq 1 ]; then
      local b; while IFS= read -r b; do [ -n "$b" ] && _clean_rm "$b"; done <<< "$backups"
    fi
    return
  fi
  if [ "${CLEAN_PURGE_BACKUPS:-0}" = 1 ]; then
    log "${desc}  [--purge-backups]"
    if [ "$file_present" -eq 1 ]; then
      log "  keeping: ${path} (--purge-backups)"
    fi
    if [ "$has_backups" -eq 1 ]; then
      local b; while IFS= read -r b; do [ -n "$b" ] && _clean_rm "$b"; done <<< "$backups"
    fi
    return
  fi
  if [ "${CLEAN_ASSUME_YES:-0}" = 1 ]; then
    log "${desc}  [-y, default keep]"
    # Use explicit if/then so a "false" test doesn't kill the function under set -e.
    if [ "$file_present" -eq 1 ]; then
      log "  keeping: ${path} (default under -y)"
    fi
    if [ "$has_backups" -eq 1 ]; then
      log "  keeping: ${backups//$'\n'/ } (default under -y)"
    fi
    return
  fi

  # ---------- Interactive prompt ------------------------------------------
  cat >&2 <<EOF

  ${desc}
    path     : ${path}  $( [ "$file_present" -eq 1 ] && echo "(present)" || echo "(absent)" )
    advice   : ${advice}
EOF
  if [ "$has_backups" -eq 1 ]; then
    printf '    backups  : %d found, most recent:\n' "$(printf '%s\n' "$backups" | wc -l | tr -d ' ')" >&2
    printf '               %s\n' "$latest_bak" >&2
  else
    printf '    backups  : (none)\n' >&2
  fi
  cat >&2 <<EOF

    Choose:
      [k] keep  (do not touch this file or its backups)
EOF
  if [ -n "$latest_bak" ]; then
    cat >&2 <<EOF
      [r] restore from most recent backup, then delete all .bak.* backups
EOF
  fi
  cat >&2 <<EOF
      [d] delete this file (and all .bak.* backups)
      [b] keep file, but delete .bak.* backups
EOF

  # Prompt label tracks whether [r] is actually offered (only when backup exists).
  local prompt_label
  if [ -n "$latest_bak" ]; then
    prompt_label="Your choice [k/r/d/b]:"
  else
    prompt_label="Your choice [k/d/b]:"
  fi
  local choice; choice="$(ask "$prompt_label" "k")"
  case "$choice" in
    k|K) log "  keeping: ${path}" ;;
    r|R)
      [ -n "$latest_bak" ] || { warn "  no backup to restore; keeping ${path}"; return; }
      if [ "${CLEAN_DRY_RUN:-0}" = 1 ]; then
        log "  [dry-run] would restore ${path} from ${latest_bak} and remove all backups"
      else
        cp -p "$latest_bak" "$path" && ok "  restored: ${path} <- ${latest_bak}"
        local b; while IFS= read -r b; do
          [ -n "$b" ] && rm -f -- "$b" && ok "  removed backup: ${b}"
        done <<< "$backups"
      fi
      ;;
    d|D)
      if [ "$file_present" -eq 1 ]; then _clean_rm "$path"; fi
      local b; while IFS= read -r b; do
        [ -n "$b" ] && _clean_rm "$b"
      done <<< "$backups"
      ;;
    b|B)
      [ "$has_backups" -eq 1 ] || { log "  no backups to remove for ${path}"; return; }
      local b; while IFS= read -r b; do
        [ -n "$b" ] && _clean_rm "$b"
      done <<< "$backups"
      ;;
    *) warn "  unknown choice; keeping ${path}" ;;
  esac
}

# ============================================================================
# SECTION: 23b. INSTALL / UNINSTALL (D-025 / Lifecycle Phase C)
# ============================================================================
# `install`   -- explicit form of the canonical bin/ install (the
#                bootstrap-on-first-client path calls the same _install_core).
# `uninstall` -- symmetric, TIERED teardown that reads the install manifest
#                to restore client configs correctly. Dry-run-able.

# mode_install: materialize the canonical bin/ install explicitly.
# Honors --dry-run (preview only). Beautified, scicomp-research-skills
# style: show the plan, then act.
mode_install() {
  # D-030a: no self-install under the Python package; point the user at pipx.
  if [ "${ARGO_ANYWHERE_PACKAGED:-0}" = 1 ]; then
    _packaged_use_pipx_hint install
    return 0
  fi

  local self_abs; self_abs="$(_resolve_self_path)"
  if [ -z "$self_abs" ] || [ ! -f "$self_abs" ]; then
    die "install: could not resolve the running script's path ($0)."
  fi

  print_summary_box "argo-anywhere  --  install plan" "$C_GRN" \
    "Canonical install dir : ${ARGO_INSTALL_DIR}" \
    "Script                : ${ARGO_INSTALL_SCRIPT}" \
    "Wrappers              : bin/install, bin/uninstall" \
    "PATH helper           : ${ARGO_INSTALL_ENV}" \
    "Manifest              : ${ARGO_MANIFEST}" \
    "Source (running from) : ${self_abs}" \
    "Mode                  : $( [ "${CLEAN_DRY_RUN:-0}" = 1 ] && echo 'DRY RUN (no changes)' || echo 'LIVE' )" \
    "$( [ -f "$ARGO_INSTALL_SCRIPT_FLAT" ] && echo 'Migration            : flat-layout script -> bin/ (detected)' || echo 'Migration            : none needed' )"

  if [ "${CLEAN_DRY_RUN:-0}" = 1 ]; then
    log "[dry-run] would create ${ARGO_INSTALL_BIN_DIR}, copy the script, write"
    log "  the install/uninstall wrappers + env helper, and stamp the manifest."
    [ -f "$ARGO_INSTALL_SCRIPT_FLAT" ] && log "[dry-run] would migrate ${ARGO_INSTALL_SCRIPT_FLAT} -> ${ARGO_INSTALL_SCRIPT}"
    return 0
  fi

  if [ "$self_abs" = "$ARGO_INSTALL_SCRIPT" ]; then
    log "Running from the canonical install already; refreshing wrappers + env."
  fi
  if _install_core "$self_abs"; then
    ok "Installed argo-anywhere.sh v${SCRIPT_VERSION} at ${ARGO_INSTALL_SCRIPT}"
    ok "  Wrappers: ${ARGO_INSTALL_WRAP_INSTALL}, ${ARGO_INSTALL_WRAP_UNINSTALL}"
    ok "  PATH helper: ${ARGO_INSTALL_ENV}"
    _print_path_setup_hint
  else
    die "install: canonical install failed (see warnings above)."
  fi
}

# _manifest_configs_to_restore: print, one per line, TAB-separated
# "<action>\t<path>\t<backup-or-empty>" rows describing how to restore
# each config the manifest recorded:
#   action=delete   -> we created it; restore = remove the file.
#   action=restore  -> it pre-existed; restore = copy the original backup back.
#                      (backup column = the newest .bak.* for the path, which
#                      is our best available "pre-argo" snapshot.)
#   action=none     -> pre-existed but no backup found; leave it (report).
# Emits nothing if no manifest / no python3.
_manifest_configs_to_restore() {
  _manifest_available || return 0
  [ -f "$ARGO_MANIFEST" ] || return 0
  python3 - "$ARGO_MANIFEST" <<'PYEOF' 2>/dev/null || true
import json, os, sys, glob
manifest = sys.argv[1]
try:
    with open(manifest) as f:
        data = json.load(f)
except Exception:
    sys.exit(0)
for path, meta in (data.get("configs") or {}).items():
    if meta.get("created_by_us"):
        print(f"delete\t{path}\t")
    else:
        # pre-existing: restore the newest backup if any exist.
        baks = sorted(glob.glob(path + ".bak.*"), key=lambda p: os.path.getmtime(p) if os.path.exists(p) else 0, reverse=True)
        if baks:
            print(f"restore\t{path}\t{baks[0]}")
        else:
            print(f"none\t{path}\t")
PYEOF
}

# _manifest_binaries_we_installed: print "<tool>\t<path>" for each binary
# the manifest says we installed. Emits nothing if no manifest / python3.
_manifest_binaries_we_installed() {
  _manifest_available || return 0
  [ -f "$ARGO_MANIFEST" ] || return 0
  python3 - "$ARGO_MANIFEST" <<'PYEOF' 2>/dev/null || true
import json, sys
manifest = sys.argv[1]
try:
    with open(manifest) as f:
        data = json.load(f)
except Exception:
    sys.exit(0)
for tool, meta in (data.get("binaries") or {}).items():
    if meta.get("installed_by_us"):
        print(f"{tool}\t{meta.get('path','')}")
PYEOF
}

# _uninstall_rm <path>: dry-run-aware remove (honors CLEAN_DRY_RUN like
# _clean_rm, which it delegates to for the actual removal).
_uninstall_rm() { _clean_rm "$@"; }

# mode_uninstall: tiered, manifest-driven teardown (D-025 D-b/D-c/D-d).
# Flags:
#   --dry-run          preview only
#   --restore-configs  restore client configs to pre-argo state (Tier 2)
#   --remove-binaries  remove tool binaries we installed (Tier 3, gated)
#   --remote           also tear down the compute-node venv (Tier 4)
#   -y                 assume-yes for the top-level confirmation
mode_uninstall() {
  local dry="${CLEAN_DRY_RUN:-0}"
  local do_restore="${UNINSTALL_RESTORE_CONFIGS:-0}"
  local do_binaries="${UNINSTALL_REMOVE_BINARIES:-0}"
  local do_remote="${CLEAN_REMOTE:-0}"

  # ---- Plan box ----------------------------------------------------------
  print_summary_box "argo-anywhere  --  uninstall plan" "$C_YLW" \
    "Mode              : $( [ "$dry" = 1 ] && echo 'DRY RUN (no changes)' || echo 'LIVE' )" \
    "Tier 1 (always)   : canonical install ${ARGO_INSTALL_DIR} (if present), state dir, tunnels/sockets" \
    "Tier 2 configs    : $( [ "$do_restore" = 1 ] && echo 'RESTORE to pre-argo state (--restore-configs)' || echo 'left as-is (pass --restore-configs)' )" \
    "Tier 3 binaries   : $( [ "$do_binaries" = 1 ] && echo 'REMOVE ones we installed (--remove-binaries)' || echo 'left installed (pass --remove-binaries)' )" \
    "Tier 4 remote     : $( [ "$do_remote" = 1 ] && echo 'tear down compute-node venv (--remote)' || echo 'skipped (pass --remote)' )" \
    "Manifest          : ${ARGO_MANIFEST}$( [ -f "$ARGO_MANIFEST" ] && echo '' || echo '  (none; config-restore + binary-removal limited)' )"

  # ---- Top-level confirmation -------------------------------------------
  if [ "$dry" != 1 ] && [ "${CLEAN_ASSUME_YES:-0}" != 1 ]; then
    local ans; ans="$(ask "Proceed with uninstall? [y/N]:" "N")"
    case "$ans" in y|Y|yes|Yes) ;; *) die "Uninstall aborted." ;; esac
  fi

  # ---- Tier 2: config restore (BEFORE removing the manifest) -------------
  if [ "$do_restore" = 1 ]; then
    log ""
    log "Tier 2: restoring client configs to their pre-argo-anywhere state..."
    if [ ! -f "$ARGO_MANIFEST" ]; then
      warn "  No manifest at ${ARGO_MANIFEST}; cannot restore configs precisely. Skipping Tier 2."
    else
      local line action path bak
      while IFS=$'\t' read -r action path bak; do
        [ -n "$action" ] || continue
        case "$action" in
          delete)
            log "  config we created -> remove: ${path}"
            _uninstall_rm "$path"
            ;;
          restore)
            if [ "$dry" = 1 ]; then
              log "  [dry-run] would restore ${bak} -> ${path}"
            else
              if cp -p "$bak" "$path" 2>/dev/null; then
                ok "  restored original: ${path}  (from ${bak})"
              else
                warn "  could not restore ${path} from ${bak} (left current file in place)"
              fi
            fi
            ;;
          none)
            warn "  ${path}: pre-existed but no backup found; leaving it in place."
            ;;
        esac
      done <<EOF
$(_manifest_configs_to_restore)
EOF
    fi
  fi

  # ---- Tier 3: binaries we installed (opt-in, manifest-gated) -----------
  if [ "$do_binaries" = 1 ]; then
    log ""
    log "Tier 3: removing tool binaries argo-anywhere installed..."
    if [ ! -f "$ARGO_MANIFEST" ]; then
      warn "  No manifest; cannot tell which binaries we installed. Skipping Tier 3."
    else
      local btool bpath
      while IFS=$'\t' read -r btool bpath; do
        [ -n "$btool" ] || continue
        log "  ${btool}: installed by us -> remove ${bpath}"
        if [ -n "$bpath" ] && [ -e "$bpath" ]; then
          _uninstall_rm "$bpath"
        else
          warn "    ${bpath:-<unknown path>} not present; skipping."
        fi
      done <<EOF
$(_manifest_binaries_we_installed)
EOF
      warn "  Note: tool binaries may have other files (venvs, caches). This"
      warn "  removes the launcher we recorded; use the tool's own uninstaller"
      warn "  for a full removal if desired."
    fi
  fi

  # ---- Tier 4: remote venv (opt-in) -------------------------------------
  if [ "$do_remote" = 1 ]; then
    log ""
    log "Tier 4: remote compute-node teardown requested (--remote)."
    log "  Reuse 'clean' for the remote venv + server log:"
    log "    $(basename "$0") clean --purge$( [ "$dry" = 1 ] && echo ' --dry-run' )"
    warn "  (mode_uninstall does not duplicate clean's remote SSH path; run the"
    warn "   command above to tear down the compute-node venv.)"
  fi

  # ---- Tier 1: local tunnels/sockets + state + canonical install --------
  log ""
  log "Tier 1: removing local channel + state + canonical install..."

  # Local listener on the resolved port. Ownership-aware: only kill a
  # tunnel WE own. An external / shared channel (e.g. argo-proxy on a
  # compute node, or another user's / session's listener) must NOT be
  # killed by uninstall -- doing so would break every client pointed at
  # it. Reuse local_tunnel_status's classification (same guard mode_stop
  # uses). [Hardening added 2026-07-09 after a sandboxed uninstall test
  # killed a live shared listener because the port probe is machine-global
  # even when HOME is sandboxed.]
  local listener_pids=""
  listener_pids="$( { lsof -nPi ":${PROXY_PORT}" -sTCP:LISTEN -t 2>/dev/null || true; } )"
  if [ -n "$listener_pids" ]; then
    local _lstatus; _lstatus="$(local_tunnel_status "$PROXY_PORT")"
    case "$_lstatus" in
      ours-healthy-fg|ours-unhealthy-fg|ours-healthy-mux|ours-unhealthy-mux)
        if [ "$dry" = 1 ]; then
          log "  [dry-run] would kill our SSH tunnel on :${PROXY_PORT} (pids: ${listener_pids//$'\n'/ })"
        else
          echo "$listener_pids" | xargs -n1 kill 2>/dev/null || true
          ok "  killed our SSH tunnel on :${PROXY_PORT} (pids: ${listener_pids//$'\n'/ })"
        fi
        ;;
      *)
        warn "  Port ${PROXY_PORT} is held by a listener we do NOT own"
        warn "    (status: ${_lstatus}; pids: ${listener_pids//$'\n'/ })."
        warn "    Leaving it running -- uninstall never kills an external or"
        warn "    shared channel. Use 'stop' / 'clean' if you intend to."
        ;;
    esac
  fi
  # SSH mux sockets.
  if [ -d "$SSH_MUX_DIR" ]; then
    _uninstall_rm "$SSH_MUX_DIR"
  fi
  # State dir (user/node/port cache + ssh-fail-lock + the install manifest,
  # which lives here since D-030). Removed AFTER Tiers 2/3 read the manifest.
  if [ -d "$STATE_DIR" ]; then
    _uninstall_rm "$STATE_DIR"
  fi

  # Canonical install LAST (self-removal). Removed in BOTH modes: a fresh
  # package install never created it (so this is a no-op), but an UPGRADER from
  # v2.x engine mode carries a leftover ~/.argo_anywhere that the footprint
  # (D-030b) lists and promises to remove -- so uninstall must actually remove
  # it. Only the engine's own install/bootstrap ever creates this dir, and the
  # bootstrap is dormant under the package (D-030a), so removal is always safe
  # and won't be undone. [D-030a-amend, 2026-07-11: the earlier package-mode
  # SKIP was wrong for upgraders and disagreed with the footprint.] In engine
  # mode we may be running from inside the dir; rm -rf on the dir holding the
  # running script is safe on POSIX (the inode persists until the process
  # exits), and we order it last so earlier tiers could still read the manifest.
  # Guarded on existence (like STATE_DIR above) so a fresh package install --
  # which never created it -- stays silent instead of reporting a phantom
  # removal.
  if [ -d "$ARGO_INSTALL_DIR" ]; then
    _uninstall_rm "$ARGO_INSTALL_DIR"
  fi

  log ""
  ok "Uninstall complete$( [ "$dry" = 1 ] && echo ' (dry-run; nothing changed)' )."
  if [ "$dry" != 1 ]; then
    log "  Remove the '. \"\$HOME/.argo_anywhere/env\"' line from your shell rc"
    log "  if you added one. Open a new shell to drop the stale PATH entry."
  fi
}

# ============================================================================
# SECTION: 24. CLEAN MODE (mode_clean -- local + remote artifact removal)
# ============================================================================
mode_clean() {
  # Resolve user/node for the remote step, with this precedence:
  #   --user / ARGO_ANYWHERE_USER  >  cached value in STATE_DIR
  #   --node / ARGO_ANYWHERE_NODE  >  cached value in STATE_DIR
  # Both can be empty if we have nothing to go on -- remote step is then
  # honestly skipped.
  local cached_user="" cached_node=""
  if [ -n "${ARGO_ANYWHERE_USER:-}" ]; then
    cached_user="$ARGO_ANYWHERE_USER"
  elif [ -f "$USER_CACHE" ]; then
    cached_user="$(cat "$USER_CACHE")"
  fi
  if [ -n "${ARGO_ANYWHERE_NODE:-}" ]; then
    cached_node="$ARGO_ANYWHERE_NODE"
  elif [ -f "$NODE_CACHE" ]; then
    cached_node="$(cat "$NODE_CACHE")"
  fi
  # Mark whether each value came from CLI/env vs the cache (for the plan box).
  local user_src node_src
  if   [ -n "${ARGO_ANYWHERE_USER:-}" ];      then user_src="(--user/env)"
  elif [ -f "$USER_CACHE" ];                  then user_src="(cache)"
  else                                             user_src=""
  fi
  if   [ -n "${ARGO_ANYWHERE_NODE:-}" ];      then node_src="(--node/env)"
  elif [ -f "$NODE_CACHE" ];                  then node_src="(cache)"
  else                                             node_src=""
  fi

  # Local listener (likely our SSH tunnel)
  local listener_pid=""
  listener_pid="$( { lsof -nPi ":${PROXY_PORT}" -sTCP:LISTEN -t 2>/dev/null || true; } | head -n1)"

  # Local backups we left behind
  local oc_backups=""; oc_backups="$(ls -1 "${OPENCODE_CONFIG}.bak."* 2>/dev/null || true)"

  # ---- Build and print the plan -----------------------------------------
  # Risky-policy label must mirror _clean_risky_file's decision tree:
  #   --purge         -> delete file + backups (regardless of -y)
  #   --purge-backups -> keep file, delete backups (regardless of -y)
  #   -y (only)       -> keep file + keep backups
  #   nothing         -> prompt per file
  echo >&2
  local risky_policy
  if   [ "${CLEAN_PURGE:-0}" = 1 ];          then risky_policy="DELETE files + backups (--purge)"
  elif [ "${CLEAN_PURGE_BACKUPS:-0}" = 1 ];  then risky_policy="keep files, delete backups (--purge-backups)"
  elif [ "${CLEAN_ASSUME_YES:-0}" = 1 ];     then risky_policy="keep (default under -y)"
  else                                            risky_policy="prompt per file"
  fi

  print_summary_box "argo-anywhere  --  clean plan" "$C_YLW" \
    "Will remove items below; risky items handled per policy." \
    "Mode: $( [ "${CLEAN_DRY_RUN:-0}" = 1 ] && echo 'DRY RUN (no changes)' || echo 'LIVE' )" \
    "Local-only: $( [ "${CLEAN_LOCAL_ONLY:-0}" = 1 ] && echo yes || echo no )" \
    "Risky policy: ${risky_policy}" \
    "User for remote: ${cached_user:-(none)} ${user_src}" \
    "Node for remote: ${cached_node:-(none)} ${node_src}"

  # Predict per-row action labels for the risky entries. Mirrors the same
  # decision tree as _clean_risky_file: --purge / --purge-backups override
  # the prompt regardless of -y.
  local risky_file_action risky_bak_action
  if   [ "${CLEAN_PURGE:-0}" = 1 ];          then risky_file_action="will delete"; risky_bak_action="will delete"
  elif [ "${CLEAN_PURGE_BACKUPS:-0}" = 1 ];  then risky_file_action="will keep";   risky_bak_action="will delete"
  elif [ "${CLEAN_ASSUME_YES:-0}" = 1 ];     then risky_file_action="will keep";   risky_bak_action="will keep"
  else                                            risky_file_action="will prompt"; risky_bak_action="will prompt"
  fi

  # Count of mux sockets we left behind (only relevant under MFA mode)
  local mux_count=0
  if [ -d "$SSH_MUX_DIR" ]; then
    # shellcheck disable=SC2012
    # Count BOTH current and pre-v2.0 prefixes so the clean plan reflects
    # what ssh_mux_close_all() will actually close.
    mux_count="$( { ls -1 "${SSH_MUX_DIR}"/argo-anywhere-* "${SSH_MUX_DIR}"/argo-opencode-* 2>/dev/null || true; } | wc -l | tr -d ' ')"
  fi

  cat >&2 <<EOF

LOCAL  -  safe (fully owned by this script)
  ~/.config/argo_anywhere/                     $( [ -d "$STATE_DIR" ] && echo "(present)" || echo "(absent)" )
  Local SSH tunnel pid on :${PROXY_PORT}                $( [ -n "$listener_pid" ] && echo "(pid ${listener_pid})" || echo "(none)" )
  SSH multiplex sockets in ${SSH_MUX_DIR}/  $( [ "$mux_count" -gt 0 ] && echo "(${mux_count} present)" || echo "(none)" )

LOCAL  -  risky (created/edited by us, but path is owned by another tool)
  ~/.config/opencode/config.json               $( [ -f "${OPENCODE_CONFIG}" ] && echo "(present, ${risky_file_action})" || echo "(absent)" )
  ~/.config/opencode/config.json.bak.*         $( [ -n "$oc_backups" ] && printf '(%d backup file(s), %s)' "$(printf '%s\n' "$oc_backups" | wc -l | tr -d ' ')" "${risky_bak_action}" || echo "(none)" )

EOF

  if [ "${CLEAN_LOCAL_ONLY:-0}" = 1 ]; then
    echo "REMOTE  -  skipped (--local-only)" >&2
  elif [ -z "$cached_user" ] || [ -z "$cached_node" ]; then
    echo "REMOTE  -  cannot reach (no cached user/node; run 'client' first or use --local-only)" >&2
  else
    cat >&2 <<EOF
REMOTE  -  on ${cached_user}@${cached_node} $(jump_descr)
  safe:
    ~/${REMOTE_SELF}                           (pushed copy of this script)
    ~/${REMOTE_LOG}                            (server bootstrap log)
    \$HOME/argovenv/                           (Python venv we created)
    ~/argoproxy.out                            (only if nohup launcher was used)
    screen/tmux session named '${SCREEN_SESSION}'   (running argo-proxy)
  risky:
    ~/.config/argoproxy/config.yaml            (our writes vs argo-proxy's own state)
    ~/.config/argoproxy/config.yaml.bak.*

EOF
  fi

  cat >&2 <<EOF
NOT TOUCHED (by design)
  OpenCode binary                              (installed by us but a general-purpose tool)
  Claude Code binary                           (installed by us but a general-purpose tool)
  ~/.claude/settings.json                      (owned by Claude Code; we only inject env keys)
  ./.claude/settings.local.json                (owned by Claude Code; project-scope env we wrote)
  This script file (${0})
  System Python, screen/tmux binaries
EOF

  # ---- Confirm -----------------------------------------------------------
  echo >&2
  if [ "${CLEAN_ASSUME_YES:-0}" = 1 ]; then
    log "Proceeding (--yes)."
  else
    local reply; reply="$(ask "Type 'yes' to proceed (anything else aborts):")"
    case "$reply" in
      yes|YES|Yes) ;;
      *) die "Aborted." ;;
    esac
  fi

  # ---- Execute ----------------------------------------------------------

  # Local: stop the listener first so we don't leave a dangling process
  # after we've removed our cached state. The label depends on what kind
  # of listener it is -- on a laptop it's our SSH tunnel; on a compute
  # node it's argo-proxy itself. mode_stop has the same distinction
  # (with an extra blast-radius warning prompt for the argo-proxy case);
  # clean already required the user to type 'yes' to proceed, so we
  # don't re-prompt here, but we DO need to label the process correctly
  # so the user understands what was killed.
  if [ -n "$listener_pid" ]; then
    local listener_label="local listener"
    case "$(local_tunnel_status "$PROXY_PORT")" in
      ours-healthy-fg|ours-unhealthy-fg|ours-healthy-mux|ours-unhealthy-mux)
        listener_label="local SSH tunnel" ;;
      external-healthy|other-or-broken)
        listener_label="local listener (likely argo-proxy itself)" ;;
    esac
    if [ "${CLEAN_DRY_RUN:-0}" = 1 ]; then
      log "${listener_label} on :${PROXY_PORT} (pid ${listener_pid})..."
      log "  [dry-run] would: kill ${listener_pid}"
    else
      log "Stopping ${listener_label} (pid ${listener_pid})..."
      kill "$listener_pid" 2>/dev/null || true
      sleep 1
      kill -0 "$listener_pid" 2>/dev/null && kill -9 "$listener_pid" 2>/dev/null || true
      ok "  killed pid ${listener_pid}"
    fi
  fi

  # Local: safe artifacts
  if [ -d "$STATE_DIR" ]; then
    log "Removing local state dir..."
    _clean_rm "$STATE_DIR"
  fi

  # Close any SSH multiplex masters this script left behind. (Done before
  # remote step would also need them; remote step opens its own as needed.)
  if [ "$mux_count" -gt 0 ]; then
    log "Closing ${mux_count} SSH multiplex socket(s)..."
    ssh_mux_close_all
  fi

  # Local: risky configs
  log "Reviewing risky local files..."
  _clean_risky_file "${OPENCODE_CONFIG}" \
    "OpenCode config" \
    "We wrote/edited the 'argo' provider block. The rest of the file may be your own (other providers, OpenCode preferences). Recommended: [r]estore from backup if you have one, otherwise [k]eep."

  # aider global config + its sibling model-settings file (Phase 5a).
  # Only the global scope is swept here; project-scoped aider configs live
  # inside the user's repos and are not tracked by this script.
  _clean_risky_file "${AIDER_GLOBAL_CONFIG}" \
    "aider config (global)" \
    "We wrote openai-api-base / openai-api-key / model / model-settings-file. The rest may be your own aider preferences. Recommended: [r]estore from backup if you have one, otherwise [k]eep."
  _clean_risky_file "${HOME}/.aider.model.settings.yml" \
    "aider model-settings (global)" \
    "This file is written entirely by argo-anywhere (per-model use_temperature:false for argo models). Safe to delete if you no longer use aider with this proxy."

  # Remote
  if [ "${CLEAN_LOCAL_ONLY:-0}" != 1 ] && [ -n "$cached_user" ] && [ -n "$cached_node" ]; then
    export ARGO_ANYWHERE_USER="$cached_user"
    log "Reaching ${cached_user}@${cached_node} for remote cleanup..."

    # Decide what to do with the remote risky file (~/.config/argoproxy/config.yaml).
    # Same decision tree as _clean_risky_file:
    #   --purge          -> 'd'  (delete file + backups)   regardless of -y
    #   --purge-backups  -> 'b'  (keep file, drop backups) regardless of -y
    #   -y (only)        -> 'k'  (keep both)
    #   nothing          -> interactive prompt
    local rc_choice="k"
    if [ "${CLEAN_PURGE:-0}" = 1 ]; then
      rc_choice="d"
      log "Remote risky policy: ${rc_choice} (--purge)"
    elif [ "${CLEAN_PURGE_BACKUPS:-0}" = 1 ]; then
      rc_choice="b"
      log "Remote risky policy: ${rc_choice} (--purge-backups)"
    elif [ "${CLEAN_ASSUME_YES:-0}" = 1 ]; then
      rc_choice="k"
      log "Remote risky policy: ${rc_choice} (default under -y)"
    else
      cat >&2 <<EOF

  Remote risky file: ~/.config/argoproxy/config.yaml
    advice: this is argo-proxy's own config (it doesn't have other state in
            that directory the way OpenCode does). Removing is generally safe
            but will force argo-proxy to be reconfigured next time.
    Choose:
      [k] keep  (default)
      [d] delete config.yaml AND its .bak.* backups
      [b] keep config.yaml, only delete .bak.* backups
EOF
      rc_choice="$(ask "Your choice [k/d/b]:" "k")"
    fi

    # Build a remote shell script. We write to a temp file rather than using
    # `var="$(cat <<'EOS' ... EOS)"` because bash 3.2 (macOS default) has a
    # parser quirk that reports phantom unbound-variable errors with
    # `set -u` for that pattern. Writing to a file sidesteps the issue.
    local remote_script_file
    remote_script_file="$(mktemp -t argo_anywhere_remote.XXXXXX)"
    # shellcheck disable=SC2064
    trap "rm -f '${remote_script_file}'" RETURN
    cat > "$remote_script_file" <<'EOS'
set -u
: "${SCREEN_SESSION:?}" "${LEGACY_SCREEN_SESSION:?}" \
  "${REMOTE_SELF:?}" "${REMOTE_LOG:?}" \
  "${LEGACY_REMOTE_SELF:?}" "${LEGACY_REMOTE_LOG:?}" \
  "${LEGACY_REMOTE_SELF_V2:?}" "${LEGACY_REMOTE_LOG_V2:?}" \
  "${RC:?}" "${DRY:?}"

_say() { printf '%s\n' "$*" >&2; }
_rm()  { [ "$DRY" = 1 ] && _say "[dry-run] would remove: $1" || { rm -rf -- "$1" && _say "removed: $1"; }; }

# Kill the screen/tmux session(s). v2.0 enumerates BOTH the current
# session name AND the pre-rename name (legacy v1.x users get a clean
# migration; current-name-only users see no extra output because the
# legacy match is silently skipped when absent).
_kill_screen() {
  local sname="$1" tag="$2"
  if command -v screen >/dev/null 2>&1 && screen -ls 2>/dev/null | grep -q "\.${sname}\b"; then
    if [ "$DRY" = 1 ]; then
      _say "[dry-run] would kill ${tag}screen session: $sname"
    else
      screen -S "$sname" -X quit && _say "killed ${tag}screen session: $sname" || _say "screen quit returned non-zero (${sname})"
    fi
  fi
  if command -v tmux >/dev/null 2>&1 && tmux has-session -t "$sname" 2>/dev/null; then
    if [ "$DRY" = 1 ]; then
      _say "[dry-run] would kill ${tag}tmux session: $sname"
    else
      tmux kill-session -t "$sname" && _say "killed ${tag}tmux session: $sname" || true
    fi
  fi
}
_kill_screen "$SCREEN_SESSION" ""
_kill_screen "$LEGACY_SCREEN_SESSION" "(legacy v1.x) "

# Safe files (current hyphenated names + BOTH legacy generations:
# v1.x .argo_opencode.* and v2.x .argo_anywhere.*; each _rm is a no-op
# when the file is absent, so current-only users see no extra output).
[ -f "$HOME/$REMOTE_SELF"           ] && _rm "$HOME/$REMOTE_SELF"
[ -f "$HOME/$REMOTE_LOG"            ] && _rm "$HOME/$REMOTE_LOG"
[ -f "$HOME/$LEGACY_REMOTE_SELF"    ] && _rm "$HOME/$LEGACY_REMOTE_SELF"
[ -f "$HOME/$LEGACY_REMOTE_LOG"     ] && _rm "$HOME/$LEGACY_REMOTE_LOG"
[ -f "$HOME/$LEGACY_REMOTE_SELF_V2" ] && _rm "$HOME/$LEGACY_REMOTE_SELF_V2"
[ -f "$HOME/$LEGACY_REMOTE_LOG_V2"  ] && _rm "$HOME/$LEGACY_REMOTE_LOG_V2"
[ -f "$HOME/argoproxy.out" ] && _rm "$HOME/argoproxy.out"
[ -d "$HOME/argovenv"      ] && _rm "$HOME/argovenv"
[ -d "$HOME/agovenv"       ] && _rm "$HOME/agovenv"   # legacy v1.x venv

# Risky: argo-proxy config
case "$RC" in
  d|D)
    [ -f "$HOME/.config/argoproxy/config.yaml" ] && _rm "$HOME/.config/argoproxy/config.yaml"
    for b in "$HOME"/.config/argoproxy/config.yaml.bak.*; do
      [ -e "$b" ] && _rm "$b"
    done
    ;;
  b|B)
    for b in "$HOME"/.config/argoproxy/config.yaml.bak.*; do
      [ -e "$b" ] && _rm "$b"
    done
    ;;
  *)
    _say "keeping argo-proxy config and any backups"
    ;;
esac
EOS

    # Forward the values we need via env on the ssh command line. The
    # LEGACY_* (v1.x .argo_opencode.*) and LEGACY_*_V2 (v2.x .argo_anywhere.*)
    # names let the remote cleanup handle both pre-rename generations (each is
    # a no-op when the legacy item isn't present).
    local remote_env
    remote_env="SCREEN_SESSION='${SCREEN_SESSION}' LEGACY_SCREEN_SESSION='${LEGACY_SCREEN_SESSION}' \
REMOTE_SELF='${REMOTE_SELF}' LEGACY_REMOTE_SELF='${LEGACY_REMOTE_SELF}' \
REMOTE_LOG='${REMOTE_LOG}' LEGACY_REMOTE_LOG='${LEGACY_REMOTE_LOG}' \
LEGACY_REMOTE_SELF_V2='${LEGACY_REMOTE_SELF_V2}' LEGACY_REMOTE_LOG_V2='${LEGACY_REMOTE_LOG_V2}' \
RC='${rc_choice}' DRY='${CLEAN_DRY_RUN:-0}'"
    # On-node short-circuit: if cached_node refers to this host, the
    # "remote" cleanup is actually local. Run the script directly with
    # bash instead of going through ssh -- avoids a useless SSH hop
    # to ourselves (and the associated mux master setup if MFA mode
    # were on, though it shouldn't be for an intra-site connection).
    local cleanup_is_local=0
    if host_is_target "$cached_node"; then
      cleanup_is_local=1
    fi
    if [ "${CLEAN_DRY_RUN:-0}" = 1 ]; then
      if [ "$cleanup_is_local" -eq 1 ]; then
        log "[dry-run] cached_node ${cached_node} resolves to this host; would run cleanup locally (no ssh)."
      else
        log "[dry-run] would ssh ${cached_user}@${cached_node} $(jump_descr) and run remote cleanup."
      fi
      log "  [dry-run] env to forward: ${remote_env}"
    elif [ "$cleanup_is_local" -eq 1 ]; then
      log "Running remote-cleanup script locally (cached_node ${cached_node} is this host)..."
      eval "${remote_env} bash" "${remote_script_file}" 2>&1 | sed 's/^/    /' || \
        warn "Local-equivalent cleanup returned non-zero; some artifacts may remain."
    else
      if ! ssh_attempt_pre; then
        warn "SSH failure lock is active; skipping remote cleanup to avoid CSPO rate-limit."
        warn "  Run 'clean' again once the lock expires or after fixing SSH auth."
      else
        local ssh_clean_rc=0
        # shellcheck disable=SC2046
        ssh -o StrictHostKeyChecking=accept-new \
            $(ssh_args "$cached_user" "$cached_node") \
            "${cached_user}@${cached_node}" \
            "${remote_env} bash -s" < "$remote_script_file" 2>&1 | sed 's/^/    /' \
          || ssh_clean_rc=$?
        if [ "$ssh_clean_rc" -ne 0 ]; then
          ssh_attempt_fail
          warn "Remote cleanup returned non-zero (rc=${ssh_clean_rc}); some artifacts may remain."
        else
          ssh_attempt_ok
        fi
      fi
    fi
  fi

  echo >&2
  if [ "${CLEAN_DRY_RUN:-0}" = 1 ]; then
    ok "Dry-run complete. Re-run without --dry-run to actually delete."
  else
    ok "Clean complete."
  fi
}

# ============================================================================
# SECTION: 25. HELP / DISPATCH (usage, long_help, main)
# ============================================================================
usage() {
  cat <<EOF
Usage: $(basename "$0") [SUBCOMMAND] [--cli-tool NAME]
                          [--user NAME] [--node HOST] [--port N]
                          [--no-jump] [--no-mfa] [--probe-nodes]
                          [--auto-port] [--port-range LO-HI]
                          [--scope project|global]
                          [--verbose-server]
                          [--force-reinstall]
                          [--keep-orphans | --drop-orphans]
                          [--output FILE] [--format text|tsv|json]
                          [--include-embeddings]
                          [--all] [--check]
                          [--dry-run] [--local-only] [-y]
                          [--purge | --purge-backups]

Subcommands:
  client          (default) Install the chosen AI client if needed, write
                  its config, push this script to a chosen ANL compute
                  node, start argo-proxy there inside screen/tmux, then
                  open the SSH tunnel and monitor its health in the
                  foreground. As of v2.0 the AI client must be selected
                  explicitly: pass --cli-tool <name> to skip the picker,
                  or invoke 'client' without --cli-tool to be prompted.
                  If the script detects it is itself running ON an ANL
                  compute node, --no-jump and --no-mfa are auto-defaulted
                  (intra-site SSH doesn't need either); if the picked
                  node is the local host, the SSH tunnel is skipped
                  entirely and the local argo-proxy is used directly.
  setup           Same as 'client' but ALWAYS shows the interactive client
                  picker, even if --cli-tool is set. Useful for one-off
                  installations of a tool different from your usual.
  tunnel          Same as 'client' but does NOT install or configure any
                  client. Just brings up the tunnel (or local proxy on a
                  compute node) and blocks. Useful for power users who
                  manage their own client configs, or for keeping a tunnel
                  alive while configuring multiple clients in other terms.
  connect         Bring up the shared channel (tunnel + remote argo-proxy)
                  and hold it in the foreground monitor. The friendlier
                  name for 'tunnel'. Run this in one window, then use
                  'configure' / 'run' in other windows against it.
  configure TOOL... Install + write config for one or more clients against
                  an EXISTING channel (e.g. 'configure opencode aider').
                  Detects the channel via /health and fails with a hint if
                  none is up; pass --ensure to bring it up. Does NOT block.
  run TOOL        Configure ONE client then launch it (e.g. 'run aider').
                  Brings the channel up if missing (prompts; --ensure / -y
                  auto-confirm). The channel-establishing verbs are the
                  three-level split of 'client'; 'client'/'setup' remain
                  as one-shot fallbacks.
  server          Run argo-proxy here. Auto-invoked by 'client' over SSH on
                  the picked compute node, but can also be run standalone
                  from a logged-in shell on a node ('I want to leave a
                  proxy running on this node for any client to reach').
                  Requires ARGO_ANYWHERE_USER and ARGO_ANYWHERE_PORT in env;
                  these have sensible defaults if invoked from 'client'.
  status          Show local tunnel state and probe the proxy via localhost.
                  Ends with a summary box (ALL GREEN / DEGRADED / FAIL) plus
                  available/configured/orphaned model counts.
                  Set ARGO_ANYWHERE_SHOW_MODELS=1 to also dump the full
                  /v1/models response.
  update          In-place upgrade of installed components without nuking
                  state (the lossless cousin of --force-reinstall). Pass
                  --all to update everything in the registry, or a list of
                  component names (argo-anywhere, argoproxy, opencode,
                  claudecode) for selective updates. Prompts before
                  installing a missing component (--yes auto-confirms).
                  Use --check for a report-only run (no installs, no
                  upgrades).
                    * 'update argo-anywhere' self-updates the script:
                      resolves the latest GitHub release tag, validates
                      the fetched script, and atomically replaces the
                      canonical install at ~/.argo_anywhere/bin/argo-anywhere.sh.
                    * 'update argoproxy' upgrades argo-proxy on the
                      compute node and automatically POSTs /refresh so
                      the running proxy picks up new upstream models
                      without a restart.
                  Run '$(basename "$0") update' with no args to see the
                  available component list.
  update-models   Refresh a client's in-config model list from the live
                  /v1/models endpoint. Tool-aware via --cli-tool (default
                  opencode). Only OpenCode enumerates models in its config,
                  so only '--cli-tool opencode' does real work; for
                  claudecode / aider (which pick the model at runtime via
                  --model) it prints an honest "not applicable" note and
                  points at 'list-models'. For OpenCode: preserves
                  everything else in the config; uses the same
                  [k]/[b]/[d]/[m]/[a] confirmation flow as other config
                  writes; requires jq. Models present in the config but
                  absent from /v1/models ('orphans') prompt per-model
                  unless --keep-orphans / --drop-orphans is passed.
  list-models     Tabulate the models the proxy serves on /v1/models (read-only;
                  the sibling of update-models). Columns: internal_name, id,
                  provider, modalities, configured. Cross-references the
                  OpenCode config when present so each row carries a
                  yes/no/orphan tag. Embeddings are excluded by default
                  (--include-embeddings to include). Format defaults to
                  pretty text; --format tsv or --format json for scripting.
                  Writes to stdout unless --output FILE is given. Requires jq.
  stop            Kill the local SSH tunnel listening on the resolved port.
                  Does NOT touch the remote argo-proxy session.
  clean           Remove every artifact this script created (local + remote).
                  Prints an enumerated plan, requires typing 'yes' to proceed.
                  Risky files (~/.config/opencode/config.json,
                  ~/.config/argoproxy/config.yaml) are asked about per file.
                  Use --dry-run to preview, --local-only to skip the remote,
                  -y / --yes for non-interactive runs (keeps risky files by
                  default; add --purge to delete them too, or --purge-backups
                  to keep the file but drop only its .bak.* siblings).
                   --user / --node override the cached identity for the
                   remote step when no client run has been cached yet.
  install         Materialize the canonical install at ~/.argo_anywhere/bin/
                  (script + install/uninstall wrappers + PATH env helper)
                  and stamp the install manifest. Normally auto-runs on the
                  first 'client' use; run explicitly to (re)install or to
                  preview with --dry-run.
  uninstall       Symmetric teardown. Tier 1 (always): canonical install +
                  state dir + local tunnel/sockets. Tier 2 (--restore-configs):
                  restore client configs to their pre-argo-anywhere state via
                  the install manifest (delete files we created; restore the
                  original backup for files we modified). Tier 3
                  (--remove-binaries): remove tool binaries WE installed
                  (manifest-gated; never touches ones you already had).
                  Tier 4 (--remote): points you at 'clean --purge' for the
                  compute-node venv. --dry-run previews; -y skips the
                  top-level confirm.
  list-tools      Print the registry of supported AI CLI tools (the values
                  --cli-tool accepts). Output is one line per tool; safe to
                  grep / parse from scripts.
  help            Print the long-form guide (paths, troubleshooting,
                  customization).

Options:
  --cli-tool NAME      Pick the AI CLI tool to install/configure. NAME must
                       be one of the values printed by 'list-tools'. Required
                       for 'client' to skip the interactive picker; ignored
                       (with a warning) for subcommands that don't need it
                       (status/stop/clean/tunnel/server/list-tools/help).
                       The 'setup' subcommand always uses the picker even
                       when --cli-tool is set, so users can configure a
                       different tool without changing their default.
  --user NAME          ANL username override (canonical: ARGO_ANYWHERE_USER).
                       Honored by 'client' (skips username prompt) and
                       'clean' (overrides cached username for the remote step).
  --node HOST          Compute-node override. 'client' skips the picker and
                       uses HOST directly (fails fast if unreachable). 'clean'
                       targets HOST for the remote cleanup step instead of
                       the cached node. Canonical env: ARGO_ANYWHERE_NODE.
                       Warns if HOST is not in the script's ANL_NODES list.
  --port N             Port override for THIS run only. If it disagrees with
                       ~/.config/opencode/config.json, you'll be asked whether
                       to migrate the config or use the config's port instead.
                       Canonical env: ARGO_ANYWHERE_PORT.
  --no-jump            Skip the jump host (${ANL_JUMP}); SSH directly
                       to the compute node. Useful when you're on the ANL
                       network or your ~/.ssh/config already inserts a
                       ProxyJump for cels.anl.gov hosts.
                       Canonical env: ARGO_ANYWHERE_NO_JUMP=1.
  --no-mfa             Disable Duo/MFA-aware behavior (SSH multiplexing).
                       The script defaults to MFA mode because all CELS access
                       is Duo-protected. Use --no-mfa for hosts that don't
                       use Duo. Canonical env: ARGO_ANYWHERE_NO_MFA=1.
  --probe-nodes        Probe each ANL_NODE for reachability before showing
                       the picker. By default the picker shows the static
                       list without probing -- under MFA, probing every node
                       could trigger many Duo prompts. With multiplexing on
                       and the master open, --probe-nodes is cheap.
  --force-reinstall    Wipe the server-side venv (\$HOME/argovenv on the ANL
                       node) and rebuild from scratch. Use after a broken
                       upgrade. Canonical env: ARGO_ANYWHERE_FORCE_REINSTALL.
  --auto-port          When the resolved port is already in use on the
                       picked compute node by ANOTHER user, automatically
                       probe a range and pick the first free port (instead
                       of prompting interactively). Sticky: triggers the
                       same OpenCode-config migration prompt as a manual
                       --port override would. Canonical env:
                       ARGO_ANYWHERE_AUTO_PORT=1.
  --port-range LO-HI   Override the port range for --auto-port and the
                       interactive [n]ext-free-port choice. Default:
                       PROXY_PORT_DEFAULT to PROXY_PORT_DEFAULT+100.
                       Canonical env: ARGO_ANYWHERE_PORT_RANGE=LO-HI.
  --scope project|global  Per-client scope override. Consumed by both
                       Claude Code and OpenCode setup (per-tool vocabularies
                       declared via <name>_scope_values(); typo'd values
                       die loud at parse time via _validate_scope_for_tool):
                         claudecode + project -> ./.claude/settings.local.json
                                    (per-repo; gitignored by Claude Code defaults).
                         claudecode + global  -> ~/.claude/settings.json
                                    (all projects).
                         opencode + project   -> <git-root>/opencode.json
                                    (per-repo; cwd-anchored; falls back to cwd
                                    when not in a git repo).
                         opencode + global    -> ~/.config/opencode/config.json
                                    (all directories).
                       Default policy (per PLAN.md D-017, Phase 4 v2.2.0):
                         * claudecode is HYBRID: explicit --scope wins; else
                           ~/.claude.json present (OAuth state) -> project
                           (safety; avoids shadowing your OAuth token); else
                           global (convenience for fresh installs).
                         * opencode default is global (no OAuth-state concern).
                       Conflict detection (existing files; OAuth state; project
                       shadowing global) runs in ALL branches and prompts
                       [k]eep / [s]witch / [a]bort when applicable.
                       Canonical env: ARGO_ANYWHERE_SCOPE. Legacy CLAUDECODE_SCOPE
                       is honored once per session with a deprecation WARN
                       (planned removal: v3.0.0).
  --verbose-server     Enable argo-proxy verbose logging on the compute
                       node. By default (since v2.0) the script writes
                       \`verbose: false\` in the argo-proxy config to
                       prevent prompt+response bodies from being logged
                       to ~/.argo-anywhere.server.log on the compute
                       node (where they'd be readable by anyone with
                       SSH access to your account, plus root). Use
                       this flag ONLY when actively debugging argo-proxy
                       behavior; remember to remove it for routine use.
                       Canonical env: ARGO_ANYWHERE_VERBOSE_SERVER=1.

  Flags below apply to 'update':
  --all                Update every component in the registry (argoproxy,
                       opencode, claudecode). Without --all and without an
                       explicit component list, 'update' prints the registry
                       and exits 0 without changing anything.
  --check              Report-only mode: print installed vs upstream versions
                       per component; do NOT install, upgrade, or POST
                       /refresh. Combine with --all to scan everything.
  -y, --yes            Non-interactive: auto-confirm install prompts for
                       missing components (otherwise 'update' asks before
                       installing each one). Shared with 'clean'.

  Flags below apply to 'update-models':
  --keep-orphans       Skip the per-orphan prompt; keep ALL models in the
                       config that are no longer in /v1/models.
                       Canonical env: ARGO_ANYWHERE_KEEP_ORPHANS=1.
  --drop-orphans       Skip the per-orphan prompt; drop ALL models in the
                       config that are no longer in /v1/models.
                       Canonical env: ARGO_ANYWHERE_DROP_ORPHANS=1.
                       (Mutually exclusive with --keep-orphans.)

  Flags below apply to 'list-models':
  --output FILE        Write the tabulated output to FILE instead of stdout.
                       Refuses to overwrite an existing file without -y.
  --format FMT         One of: text (default; column-aligned), tsv (header
                       row + tab-separated; one model per line), json (the
                       filtered+annotated model list as a JSON array, each
                       element including internal_name, id, provider,
                       modalities, configured).
  --include-embeddings Include embedding models in the table. Default is
                       to filter them out (matches update-models semantics,
                       so counts agree across the two subcommands).

  Flags below apply to 'clean':
  --dry-run            Print what would be deleted; change nothing.
  --local-only         Skip remote cleanup over SSH.
  -y, --yes            Non-interactive: skip the global 'yes' prompt and
                       suppress per-file risky prompts. With no other flags,
                       'clean -y' deletes only safe items and KEEPS every
                       risky file and backup.
  --purge              Delete risky files AND their .bak.* backups too.
                       Implies --purge-backups. Almost always combined with -y.
  --purge-backups      Keep risky files but delete their .bak.* backups.
                       Useful for clearing accumulated backup clutter.

  -h, --help           Short usage (this text).

Port policy: the OpenCode config's baseURL is the source of truth. By default
  the script reads the port from there. --port and ARGO_ANYWHERE_PORT override
  for one run; you'll be prompted before any change to config.json.

Tip: run \`bash $(basename "$0") help\` for the full guide.
EOF
}

long_help() {
  local script_name; script_name="$(basename "$0")"
  cat <<EOF
================================================================================
  ${script_name}  -  full guide
================================================================================

WHAT THIS SCRIPT DOES
---------------------
Lets you run OpenCode on your laptop against argo-proxy running on an Argonne
compute node, regardless of whether you are inside or outside the ANL network.

Two roles, one file:
  * client mode (laptop): bootstraps OpenCode + config, picks an ANL node,
    pushes a copy of this script to it, exec's it remotely as 'server', then
    opens an SSH local-forward (port ${PROXY_PORT_DEFAULT}, by default) and monitors it.
  * server mode (ANL compute node): creates a Python venv at ${VENV_PATH},
    installs argo-proxy if missing, writes ~/.config/argoproxy/config.yaml,
    and starts \`argo-proxy serve\` inside screen (preferred), tmux, or nohup.

You should normally only ever invoke 'client'. The 'server' mode is run for
you over SSH on the chosen compute node.

QUICK START
-----------
  # Latest from main:
  curl -fsSL https://raw.githubusercontent.com/a-attia/argo-anywhere/main/${script_name} -o ${script_name}
  # ...or pin to a release tag (recommended once you have a setup that works):
  curl -fsSL https://raw.githubusercontent.com/a-attia/argo-anywhere/v1.0.0/${script_name} -o ${script_name}

  bash ${script_name}                # runs 'client' by default
  # ...in another terminal once it says "Tunnel is live":
  opencode

Subsequent runs reuse the cached username and last-used node.

PREREQUISITES
-------------
Laptop:
  * bash 3.2+ (macOS default OK), ssh, scp, curl, lsof
  * Optional: jq (only needed for the 'merge' option when handling existing
    OpenCode config), Homebrew on macOS (used to install OpenCode if missing).
  * SSH key-based auth to ${ANL_JUMP} for your ANL username
    (set up with: ssh-copy-id <user>@${ANL_JUMP}). The script will refuse to
    proceed and show exact instructions if password auth is required.
  * If outside ANL: VPN to reach ${ANL_JUMP} from off-site networks may be
    required by your local network policy.

ANL compute node:
  * Python 3.10 or newer on PATH (\`python3 --version\`).
  * 'screen' or 'tmux' for a session that survives logout. Falls back to nohup.

WHERE THINGS LIVE
-----------------
Laptop:
  ${HOME}/.config/argo_anywhere/user      cached ANL username
  ${HOME}/.config/argo_anywhere/node      last-used compute node
  ${HOME}/.config/opencode/config.json    OpenCode config (this script writes it)

ANL compute node (after first run):
  \$HOME/${REMOTE_SELF}                    pushed copy of this script
  \$HOME/${REMOTE_LOG}                     server-mode bootstrap log
  \$HOME/argovenv/                         Python venv with argo-proxy
  \$HOME/.config/argoproxy/config.yaml     argo-proxy config (port / user)
  screen session: '${SCREEN_SESSION}'             where argo-proxy serve runs

Network path while running:
  laptop:${PROXY_PORT_DEFAULT}  --SSH-->  ${ANL_JUMP}  --SSH-->  <node>:${PROXY_PORT_DEFAULT}  -->  argo-proxy

CONFIG: WHAT IF SOMETHING ALREADY EXISTS
----------------------------------------
For both ~/.config/opencode/config.json (laptop) and
~/.config/argoproxy/config.yaml (compute node), the script asks before changing
anything. Choices presented:
  [k] keep existing  (default)
  [b] backup to <file>.bak.<timestamp>, then overwrite
  [d] show unified diff, ask again
  [m] merge (JSON only, requires jq) -- script-managed keys win
  [a] abort

CUSTOMIZATION (edit the top of this file)
-----------------------------------------
  ANL_NODES=( ... )                       compute nodes to probe, in order
  ANL_JUMP="${ANL_JUMP}"
  PROXY_PORT_DEFAULT=${PROXY_PORT_DEFAULT}              fallback when no other source resolves a port
  VENV_PATH='${VENV_PATH}'
  SCREEN_SESSION="${SCREEN_SESSION}"
  HEALTH_INTERVAL=${HEALTH_INTERVAL}                       seconds between health probes (client)
  HEALTH_FAIL_THRESHOLD=${HEALTH_FAIL_THRESHOLD}                consecutive fails before notifying

To add nodes: append fully-qualified hostnames to ANL_NODES. Re-run client.

MFA / Duo POLICY
----------------
ANL CELS hosts (logins.cels.anl.gov, compute-*.cels.anl.gov) require Duo
multi-factor authentication. The script accommodates this by default using
SSH ControlMaster connection multiplexing:

  * The mux master is opened against the chosen COMPUTE NODE, not the jump
    host. logins.cels.anl.gov is jump-only -- its login shell rejects all
    command execution ("This account is currently not available"), so a
    master cannot be opened against it. OpenSSH multiplexes per
    (user, host, port), and the master to compute-XX covers every later
    ssh/scp to that same compute-XX through the same ProxyJump.
  * On the FIRST SSH call to the picked node (the preflight, or the
    --node reachability check), one Duo prompt fires. The master
    connection is parked at:  ~/.ssh/sockets/argo-anywhere-<user>-<host>-<port>
  * Every subsequent SSH/SCP call to the same node within the same script
    run reuses the master and never prompts.
  * After all clients disconnect, the master lingers for ARGO_ANYWHERE_CONTROL_PERSIST
    seconds (default 3600 = 1 hour). Re-running 'status', 'update-models',
    'clean', or 'client' within that window also avoids a fresh Duo prompt.
  * --probe-nodes opens a separate master per node it tests (each is a
    distinct destination). Expect one Duo prompt per reachable node.

If the tunnel drops mid-session and the master is still alive, the health
monitor attempts a silent reconnect through the existing socket. If the
master is also gone, you'll be notified to re-run 'client' (which is when a
new Duo prompt happens).

To turn this off (for non-Duo hosts):  --no-mfa  or  ARGO_ANYWHERE_NO_MFA=1
To inspect/close sockets manually:
  ls -l ~/.ssh/sockets/argo-anywhere-*
  ssh -O exit -S ~/.ssh/sockets/argo-anywhere-<user>-<host>-<port> placeholder
'clean' also offers to close all our sockets.

RUNNING ON A COMPUTE NODE
-------------------------
The 'client' subcommand assumes by default that you are running it from a
laptop OUTSIDE the ANL network: an SSH tunnel is opened from the laptop
to a chosen compute node, with the jump host doing the public-internet
hop and Duo authenticating you. None of that is needed when the script
itself is already running on a compute node, so the script auto-detects
that case (FQDN matches a name in ANL_NODES, or ends in .cels.anl.gov)
and adjusts:

  * --no-jump on by default. From inside the network the jump host is
    an extra hop you don't need (and may not even be reachable from a
    compute node). Override with ARGO_ANYWHERE_NO_JUMP=0 if you have a
    setup that genuinely requires the jump.
  * --no-mfa on by default. Intra-site SSH does not trigger Duo, so
    the multiplex master setup we'd normally do is wasted effort.
    Override with ARGO_ANYWHERE_NO_MFA=0 if your setup differs.
  * If the picked node IS the host you are running on (the common
    "I'm on compute-01 and I want to use OpenCode here" case), the
    SSH tunnel is skipped entirely. The script invokes its own server
    bootstrap inline so argo-proxy is up under screen/tmux/nohup, then
    points the local OpenCode config at http://localhost:<port>/v1.
    No foreground tunnel runs; argo-proxy keeps serving even after
    'client' returns. Use 'clean' to stop everything.

If you only want argo-proxy running on a node (no client setup, no
tunnel), 'server' is the right subcommand:

  ssh <user>@compute-XX.cels.anl.gov
  bash argo-anywhere.sh server   # starts argo-proxy under screen, returns

This is the 'I want to leave a proxy on this node for any of my
machines/clients to reach' workflow. Other clients (your laptop, a
cluster login node) can then point at the proxy via their own SSH -L
forward, or via 'argo-anywhere.sh client --cli-tool NAME --node compute-XX'
from those machines.

TUNNEL-ONLY MODE
----------------
'argo-anywhere.sh tunnel' is the same as 'client' minus the AI CLI tool
install + config. It just brings up the tunnel (or local proxy on a
compute node) and blocks. Useful when you:

  * manage your own client configs and don't want the script touching
    ~/.config/opencode/config.json;
  * want a tunnel running while configuring multiple clients in
    other terminals;
  * are prototyping with a custom HTTP client that needs the /v1
    endpoint reachable.

The tunnel-up message reminds you of the URL and bearer-token convention.

PORT POLICY
-----------
The port is resolved at startup from these sources, in order:
  1. --port N                        (CLI flag, this run only)
  2. ARGO_ANYWHERE_PORT env var
  3. baseURL in ~/.config/opencode/config.json   (the source of truth)
  4. PROXY_PORT_DEFAULT (=${PROXY_PORT_DEFAULT})        (built-in fallback)

If --port or the env var disagree with config.json, 'client' will ask whether
to migrate the config to the new port or keep the existing one. The script
never silently changes the port behind your back.

Why config.json wins: OpenCode reads its baseURL once at launch. If your
tunnel and OpenCode disagree on the port, OpenCode silently fails or talks
to the wrong port. Keeping config.json authoritative avoids drift.

When to use --port:
  * the default port is taken by another app on your laptop or the node
  * you want to migrate to a new port permanently (pick --port N, choose [m]
    when asked, then drop the flag on subsequent runs)
  * you want a transient/parallel tunnel for testing or debugging without
    disturbing your working OpenCode setup (pick --port N, choose [u] when
    asked -- the script binds the override port for this run only and never
    touches config.json, so OpenCode keeps talking to its original port)

ENVIRONMENT VARIABLES
---------------------
Canonical (preferred):
  ARGO_ANYWHERE_USER             ANL username (alternative to --user)
  ARGO_ANYWHERE_NODE             compute node hostname (alternative to --node)
  ARGO_ANYWHERE_PORT             port (alternative to --port)
  ARGO_ANYWHERE_NO_JUMP=1        skip the jump host (alternative to --no-jump)
  ARGO_ANYWHERE_NO_MFA=1         disable SSH multiplexing (--no-mfa)
  ARGO_ANYWHERE_CONTROL_PERSIST=N seconds the SSH master stays after the last
                                 client disconnects (default 3600 = 1 hour;
                                 use 'yes' for indefinite, 'no' to disable).
  ARGO_ANYWHERE_SHOW_MODELS=1    'status' dumps the full /v1/models list
  ARGO_ANYWHERE_FORCE_REINSTALL=1 server mode wipes \$HOME/argovenv first
  ARGO_ANYWHERE_KEEP_ORPHANS=1   update-models keeps ALL orphaned config models
  ARGO_ANYWHERE_DROP_ORPHANS=1   update-models drops ALL orphaned config models
  ARGO_ANYWHERE_AUTO_PORT=1      on remote-port collision, auto-pick the next
                                 free port instead of prompting (alternative
                                 to --auto-port)
  ARGO_ANYWHERE_PORT_RANGE=LO-HI port range for --auto-port and the [n]ext-
                                 free-port choice (default
                                 PROXY_PORT_DEFAULT to PROXY_PORT_DEFAULT+100)
  ARGO_ANYWHERE_VERBOSE_SERVER=1 enable argo-proxy verbose logging on the
                                 compute node (alternative to --verbose-server).
                                 OFF by default since v2.0 to prevent prompt
                                 bodies from being logged to disk on the
                                 compute node. Use only for debugging.
  ARGO_BOX_STYLE=ascii|unicode   override the box-drawing heuristic

Legacy (still honored, prints a one-time deprecation warning):
  ANL_USERNAME    -> ARGO_ANYWHERE_USER
  PROXY_PORT      -> ARGO_ANYWHERE_PORT
  SHOW_MODELS     -> ARGO_ANYWHERE_SHOW_MODELS

NOTIFICATIONS WHEN THE TUNNEL BREAKS
------------------------------------
While 'client' is in the foreground, a background loop polls
http://localhost:<port>/health every ${HEALTH_INTERVAL}s. After ${HEALTH_FAIL_THRESHOLD} consecutive
failures, you'll see:
  * a loud red message on stderr + terminal bell
  * macOS: 'osascript' notification banner
  * Linux: 'notify-send' if installed

The tunnel itself uses ServerAliveInterval=30 / ServerAliveCountMax=3 /
ExitOnForwardFailure=yes, so a dead SSH path also kills the foreground process.

COMMON OPERATIONS
-----------------
Check what's happening locally and remotely (via the tunnel):
  bash ${script_name} status

List models the proxy is exposing:
  bash ${script_name} list-models                     # pretty table
  bash ${script_name} list-models --include-embeddings
  bash ${script_name} list-models --format tsv --output models.tsv
  bash ${script_name} list-models --format json | jq '.[] | select(.provider=="claude")'
  ARGO_ANYWHERE_SHOW_MODELS=1 bash ${script_name} status   # gated raw dump
  curl -s http://localhost:<port>/v1/models | jq .   # raw  (<port> = your tunnel port)

Refresh the model list in your OpenCode config from the live proxy:
  bash ${script_name} update-models
  # Replaces provider.argo.models with everything /v1/models advertises
  # (excluding embeddings). Asks before overwriting; preserves the rest of
  # ~/.config/opencode/config.json. Requires jq.

Tear down only the local tunnel:
  bash ${script_name} stop

Remove every artifact this script created (local + remote, with prompts):
  bash ${script_name} clean --dry-run                # preview first; recommended
  bash ${script_name} clean                          # interactive
  bash ${script_name} clean --local-only             # only local artifacts (no SSH)
  bash ${script_name} clean -y                       # non-interactive; keeps risky
  bash ${script_name} clean -y --purge-backups       # also drop .bak.* clutter
  bash ${script_name} clean -y --purge               # delete EVERYTHING (incl. configs)
  bash ${script_name} clean --user jdoe --node compute-02.cels.anl.gov
                                                    # remote cleanup with no cache

Stop argo-proxy on the compute node (script does NOT do this for you):
  ssh -J <user>@${ANL_JUMP} <user>@<node> 'screen -S ${SCREEN_SESSION} -X quit'
  # or, if tmux was used:
  ssh -J <user>@${ANL_JUMP} <user>@<node> 'tmux kill-session -t ${SCREEN_SESSION}'

Re-attach to the proxy session on the compute node (to read its log):
  ssh -J <user>@${ANL_JUMP} <user>@<node>
  screen -r ${SCREEN_SESSION}        # detach with Ctrl-A then d
  # or:
  tmux attach -t ${SCREEN_SESSION}   # detach with Ctrl-B then d

Force a different ANL username for one run:
  bash ${script_name} client --user jdoe

Reset the cached username / node:
  rm -f ${HOME}/.config/argo_anywhere/{user,node}

Update installed components in place (lossless; preserves configs + venv):
  bash ${script_name} update --all                          # update everything
  bash ${script_name} update argo-anywhere                  # self-update the script
  bash ${script_name} update argoproxy                      # just the proxy on the node
  bash ${script_name} update opencode claudecode            # explicit list
  bash ${script_name} update --check --all                  # report-only; no installs
  bash ${script_name} update --all -y                       # non-interactive (CI / cron)
  # After a successful argo-proxy upgrade, 'update' POSTs /refresh to the
  # local tunnel (if up) so the running proxy picks up new upstream models
  # without a restart. Use 'list-models' / 'update-models' to consume them.
  # 'update argo-anywhere' resolves the latest GitHub release tag, validates
  # the fetched script (bash -n + size check + SCRIPT_VERSION sentinel),
  # backs up the existing copy, and atomically replaces ~/.argo_anywhere/
  # argo-anywhere.sh (the canonical install). If no install exists yet,
  # it prompts to bootstrap one first. Refuses to clobber a dirty git tree.

Manual fallback if 'update argoproxy' can't reach the node (use directly):
  ssh -J <user>@${ANL_JUMP} <user>@<node> '~/argovenv/bin/argo-proxy update install'

TROUBLESHOOTING
---------------
"Cannot reach <user>@${ANL_JUMP} without a password"
    SSH key auth is not set up for the jump host. Run:
      ssh-keygen -t ed25519     # if you have no key
      ssh-copy-id <user>@${ANL_JUMP}
    If you're off-site, also confirm your VPN is up.
    If you can already reach compute nodes directly without going through
    ${ANL_JUMP} (you're on the ANL network, or your ~/.ssh/config has
    ProxyJump set up for cels.anl.gov), use --no-jump to skip the jump host.

"No ANL_NODES are reachable"
    Either the node list at the top of this script is stale, or the jump-host
    auth works but the node hop does not. Try:
      ssh -J <user>@${ANL_JUMP} <user>@compute-01.cels.anl.gov true
    Edit ANL_NODES at the top of the script and re-run. With --no-jump:
      ssh <user>@compute-01.cels.anl.gov true

"Port <port> is already in use locally"
    Another tunnel (or anything else) is bound to that port. Find and kill:
      lsof -nPi :<port> -sTCP:LISTEN
      bash ${script_name} stop
    Or pick a different port for this run:
      bash ${script_name} --port <new_port> client
    (You'll be asked whether to also migrate ~/.config/opencode/config.json.)

"Port N on <node> is held by pid X owned by '<other>', not '<you>'"
    Another user's argo-proxy is on the same port on the same compute node.
    The script refuses to attach because traffic would be misattributed.
    Pick a different port (any free port works):
      bash ${script_name} --port <new_port> client

"argo-proxy needs Python 3.10+"
    The compute node default python3 is too old. Activate a newer Python
    (module load, conda, etc.) before invoking the client, OR change VENV_PATH
    so it points to a venv built with the right interpreter.

"Server bootstrap on <node> failed"
    SSH back in and read the bootstrap log:
      ssh -J <user>@${ANL_JUMP} <user>@<node> 'tail -n 80 ~/${REMOTE_LOG}'
    Common causes: pip install of argo-proxy failed (network/proxy on the
    node), screen/tmux missing, port already bound by a stale process.

"Lost connection to <node>:<port>" notification
    Either the SSH tunnel dropped (laptop/network) or argo-proxy died on the
    node. Check 'status' first; if local tunnel is fine but the proxy is gone,
    just re-run 'client' -- the server mode is idempotent.

config.json was clobbered or merged badly
    Each write creates ~/.config/opencode/config.json.bak.<timestamp> when
    you choose [b]ackup. Restore with:
      cp ${HOME}/.config/opencode/config.json.bak.<ts> ${HOME}/.config/opencode/config.json

REFERENCES
----------
  argo-proxy docs:   https://argo-proxy.readthedocs.io/en/latest/
  argo-proxy source: https://github.com/Oaklight/argo-proxy
  OpenCode:          https://opencode.ai/
  ANL AI4Dev notes:  https://web.cels.anl.gov/~jacob/ai4dev.html
  This script:       https://github.com/a-attia/argo-anywhere
  Maintainer:        Ahmed Attia (attia@anl.gov)

SECURITY NOTE
-------------
The OpenCode config uses your ANL (Argonne) username as a pseudo-API-key
(this is how argo-proxy identifies callers; it is not a secret in the
cryptographic sense). This is the SAME username you use to SSH into ANL
hosts (logins.cels.anl.gov etc.) -- it has nothing to do with your laptop's
local OS account name (\$USER), which may be entirely different. The script
asks for it on first run and caches it at ~/.config/argo_anywhere/user.
The proxy is reached over loopback inside the SSH tunnel, so HTTP is fine.
Do not "fix" the URL to https:// -- it will break.
EOF
}

main() {
  local mode=""
  # Single pass: accept flags and subcommand in any order. The first
  # non-flag, non-known-subcommand token is an error.
  while [ $# -gt 0 ]; do
    case "$1" in
      client|tunnel|connect|configure|run|setup|server|status|stop|update|update-models|list-models|clean|install|uninstall|help|list-tools)
        if [ -n "$mode" ] && [ "$mode" != "$1" ]; then
          die "Conflicting subcommands: '${mode}' and '$1'."
        fi
        mode="$1"; shift ;;
      --cli-tool)
        # Per-tool selection (D2). Required for client/setup explicit
        # selection; warned-but-ignored for subcommands that don't
        # consume per-tool identity (status/stop/clean/etc.). The
        # warn-but-ignore behavior is per the user's directive: avoid
        # erroring on `alias argo='bash argo-anywhere.sh --cli-tool X'`
        # patterns where the flag is set globally but only some
        # subcommands need it.
        [ -n "${2:-}" ] || die "--cli-tool expects a value (one of: $(cli_tool_known_names))."
        if ! cli_tool_is_known "$2"; then
          die "--cli-tool: unknown tool '$2'. Known tools: $(cli_tool_known_names)."
        fi
        CLI_TOOL_OVERRIDE="$2"; shift 2 ;;
      --user)
        [ -n "${2:-}" ] || die "--user expects a value."
        ARGO_ANYWHERE_USER="$2"; shift 2 ;;
      --node)
        [ -n "${2:-}" ] || die "--node expects a value."
        ARGO_ANYWHERE_NODE="$2"; shift 2 ;;
      --port)
        case "${2:-}" in
          ''|*[!0-9]*) die "--port expects a numeric value (got '${2:-}')." ;;
        esac
        PORT_OVERRIDE_CLI="$2"; shift 2 ;;
      --force-reinstall)
        FORCE_REINSTALL=1; export ARGO_ANYWHERE_FORCE_REINSTALL=1; shift ;;
      --no-jump)
        ARGO_ANYWHERE_NO_JUMP=1; shift ;;
      --no-mfa)
        ARGO_ANYWHERE_NO_MFA=1; shift ;;
      --probe-nodes)
        PROBE_NODES=1; shift ;;
      --verbose-server)
        # P2 fix: explicit opt-in for argo-proxy's verbose mode on the
        # compute node. Default since v2.0 is verbose=false (the
        # server-side log file ~/.argo-anywhere.server.log otherwise
        # captures every prompt+response in plaintext on a shared
        # compute node). Set this when actively debugging argo-proxy
        # behavior; remember to remove for routine use.
        ARGO_ANYWHERE_VERBOSE_SERVER=1; export ARGO_ANYWHERE_VERBOSE_SERVER; shift ;;
      --auto-port)
        AUTO_PORT=1; shift ;;
      --ensure)
        # configure/run: bring the channel up if it isn't already, rather
        # than failing with the 'run connect first' hint (D-024 / D-e).
        CONFIGURE_ENSURE=1; shift ;;
      --port-range)
        [ -n "${2:-}" ] || die "--port-range expects a value of the form LO-HI."
        case "$2" in
          [0-9]*-[0-9]*)
            local _pr_lo="${2%-*}" _pr_hi="${2#*-}"
            # Both ends must be valid TCP ports (1024-65535) and LO < HI.
            # Catches: --port-range 0-100 (privileged ports), 70000-80000
            # (out of TCP range), 65000-64900 (reversed, would probe nothing).
            if ! [[ "$_pr_lo" =~ ^[1-9][0-9]*$ ]] || [ "$_pr_lo" -lt 1024 ] || [ "$_pr_lo" -gt 65535 ]; then
              die "--port-range LO out of valid range (1024-65535): got '$_pr_lo'"
            fi
            if ! [[ "$_pr_hi" =~ ^[1-9][0-9]*$ ]] || [ "$_pr_hi" -lt 1024 ] || [ "$_pr_hi" -gt 65535 ]; then
              die "--port-range HI out of valid range (1024-65535): got '$_pr_hi'"
            fi
            if [ "$_pr_lo" -ge "$_pr_hi" ]; then
              die "--port-range needs LO < HI: got '${_pr_lo}-${_pr_hi}'"
            fi
            ARGO_ANYWHERE_PORT_RANGE="$2"; shift 2 ;;
          *) die "--port-range expects LO-HI (e.g. 64742-64842), got '$2'." ;;
        esac ;;
      --scope)
        # B1a (Phase 4): per-tool scope vocabulary contract (D-018).
        # Parser accepts any non-empty string; validation deferred to the
        # per-tool <name>_pick_scope function which calls
        # _validate_scope_for_tool against the tool's <name>_scope_values
        # list. This is necessary because --scope and --cli-tool may
        # arrive in either order on the command line; per-tool validation
        # can only run once both are known. Stored in _SCOPE_OVERRIDE
        # (internal-global naming convention; matches _INVOKED_MODE etc.).
        # User-facing env var is ARGO_ANYWHERE_SCOPE (D-009 namespace
        # convention); legacy CLAUDECODE_SCOPE auto-promotes with a
        # one-time WARN (Section 6).
        [ -n "${2:-}" ] || die "--scope expects a value (e.g. 'project' or 'global'; per-tool vocabulary varies)."
        _SCOPE_OVERRIDE="$2"; shift 2 ;;
      --keep-orphans)
        KEEP_ORPHANS=1; shift ;;
      --drop-orphans)
        DROP_ORPHANS=1; shift ;;
      --output)
        # list-models: write the tabulated output to FILE instead of stdout.
        # Ignored (with a warning later) for subcommands that don't write
        # a single artefact.
        [ -n "${2:-}" ] || die "--output expects a file path."
        LIST_MODELS_OUTPUT="$2"; shift 2 ;;
      --format)
        # list-models: text (default; column-aligned), tsv, or json.
        [ -n "${2:-}" ] || die "--format expects one of: text, tsv, json."
        case "$2" in
          text|tsv|json) LIST_MODELS_FORMAT="$2"; shift 2 ;;
          *) die "--format: unknown value '$2'. Use one of: text, tsv, json." ;;
        esac ;;
      --include-embeddings)
        # list-models: include embedding models in the table. Default is
        # to filter them out (matches update-models semantics).
        LIST_MODELS_INCLUDE_EMBED=1; shift ;;
      --dry-run)        CLEAN_DRY_RUN=1; shift ;;
      --local-only)     CLEAN_LOCAL_ONLY=1; shift ;;
      --restore-configs) UNINSTALL_RESTORE_CONFIGS=1; shift ;;
      --remove-binaries) UNINSTALL_REMOVE_BINARIES=1; shift ;;
      --remote)          CLEAN_REMOTE=1; shift ;;
      --yes|-y)         CLEAN_ASSUME_YES=1; UPDATE_ASSUME_YES=1; shift ;;
      --purge)          CLEAN_PURGE=1; CLEAN_PURGE_BACKUPS=1; shift ;;
      --purge-backups)  CLEAN_PURGE_BACKUPS=1; shift ;;
      --all)
        # 'update' flag: update every component in the registry.
        # Ignored (with a warn later) for subcommands that don't
        # consume it. Same pattern as --keep-orphans / --output / etc.
        UPDATE_ALL=1; shift ;;
      --check)
        # 'update' flag: report-only mode (no installs, no upgrades).
        # Same scoping as --all.
        UPDATE_CHECK_ONLY=1; shift ;;
      -h|--help) usage; exit 0 ;;
      --) shift; break ;;
      *)
        # Positional arguments are accepted by a few subcommands:
        #   * 'update' takes component names (e.g. `update argoproxy opencode`).
        #   * 'configure' / 'run' take CLI-tool names
        #     (e.g. `configure opencode aider`, `run aider`).
        # Anywhere else, an unknown token is a parse error.
        if [ "$mode" = "update" ]; then
          if update_component_is_known "$1"; then
            UPDATE_COMPONENTS_ARGV="${UPDATE_COMPONENTS_ARGV:+${UPDATE_COMPONENTS_ARGV} }$1"
            shift
          else
            die "update: unknown component '$1'. Known components: $(update_component_known_names)."
          fi
        elif [ "$mode" = "configure" ] || [ "$mode" = "run" ]; then
          if cli_tool_is_known "$1"; then
            CONFIGURE_TOOLS_ARGV="${CONFIGURE_TOOLS_ARGV:+${CONFIGURE_TOOLS_ARGV} }$1"
            shift
          else
            die "${mode}: unknown tool '$1'. Known tools: $(cli_tool_known_names)."
          fi
        else
          err "Unknown argument: $1"; usage; exit 2
        fi
        ;;
    esac
  done
  [ -n "$mode" ] || mode="client"

  # --keep-orphans and --drop-orphans are mutually exclusive (and both
  # only meaningful for update-models). Reject the combination early so
  # the user gets a clear error rather than the silent precedence rule
  # in mode_update_models (keep wins).
  if [ "${KEEP_ORPHANS:-0}" = 1 ] && [ "${DROP_ORPHANS:-0}" = 1 ]; then
    die "--keep-orphans and --drop-orphans cannot be combined."
  fi

  # v2.0 upgrade gate: refuse to run if v1.x state is detected on this
  # machine. Skipped for read-only / inspection modes (help, list-tools,
  # status without prior cache) so users can see help even with stale
  # state. clean is allowed because cleanup is its purpose.
  case "$mode" in
    help|list-tools|list-models|uninstall) ;;
    *)
      if ! detect_legacy_state_and_block; then
        die "Refusing to run with v1.x state present. Clean up per UPGRADING.md, then re-run."
      fi
      ;;
  esac

  # Resolve the port once, here, before any mode runs.
  resolve_port

  # Port-mismatch warning for non-client modes. mode_client has its own
  # interactive migrate/keep/abort prompt later; the other modes just need
  # to know they may be talking to the wrong port (e.g. `status --port 1234`
  # when the config says 64742 will silently report FAIL because nothing is
  # listening on 1234). Skip in client (handled there) and in server/help.
  case "$mode" in
    client|tunnel|connect|server|help) ;;
    *)
      if [ -n "$PORT_FROM_CONFIG" ] && [ "$PROXY_PORT" != "$PORT_FROM_CONFIG" ]; then
        warn "Port override (${PROXY_PORT}, source: ${PORT_SOURCE}) differs from"
        warn "  ~/.config/opencode/config.json baseURL (${PORT_FROM_CONFIG})."
        warn "  This run uses ${PROXY_PORT}. To reconcile, run 'client' (offers migration)."
      fi
      ;;
  esac

  # Warn when --cli-tool is passed to a subcommand that doesn't consume
  # it (status/stop/clean/etc.). Keep client/setup silent (they DO use
  # it). Keep update-models silent for now (it's currently OpenCode-
  # only; the per-tool dispatch lands later when the registry expands).
  if [ -n "${CLI_TOOL_OVERRIDE:-}" ]; then
    case "$mode" in
      client|setup|configure|run|update-models) ;;  # consumes --cli-tool
      *) warn "--cli-tool ignored for subcommand '${mode}' (only used by client/setup/configure/run/update-models)." ;;
    esac
  fi

  # B1a-amend (Phase 4 v2.2.0 release-gate, Test 5 amendment): D-016
  # "fail louder, not silently". The parser at line 7324 deliberately
  # accepts any non-empty --scope value because validation depends on
  # which tool the user picked, and --scope + --cli-tool may arrive
  # in either order. The per-tool <name>_pick_scope functions validate
  # via _validate_scope_for_tool when they run -- but they only run
  # under client/setup. For other subcommands (status/stop/clean/...),
  # a typo'd --scope was silently accepted and ignored, violating D-016.
  #
  # Fix: validate eagerly here once both --cli-tool and --scope are
  # known. Branches:
  #   * both set + subcommand consumes --cli-tool -> validate now (die
  #     loud on typo BEFORE we touch any tunnel/config state)
  #   * --scope set, --cli-tool set, subcommand doesn't consume tool
  #     (e.g. status) -> validate against the named tool's vocabulary
  #     anyway (the user's intent was clearly tool-scoped)
  #   * --scope set, --cli-tool UNSET (will pick interactively) ->
  #     defer to <name>_pick_scope (the picker hasn't fired yet; we
  #     don't know which tool's vocabulary to validate against)
  #   * --scope set, subcommand entirely ignores --scope (status/stop/
  #     clean/list-tools/help/update-models without per-tool dispatch)
  #     -> add an "ignored" warn alongside the existing --cli-tool one
  #     so the user knows the typo would have died loud under client/setup
  if [ -n "${_SCOPE_OVERRIDE:-}" ]; then
    if [ -n "${CLI_TOOL_OVERRIDE:-}" ]; then
      # Validate against the named tool's vocabulary regardless of mode;
      # the user's intent was specific. _validate_scope_for_tool die's
      # loud with a clear message including the valid values list.
      _validate_scope_for_tool "$CLI_TOOL_OVERRIDE" "$_SCOPE_OVERRIDE"
    fi
    # Warn when --scope is set but the subcommand won't ACT on it
    # (no per-tool config write happens). Matches the --cli-tool
    # ignored-warn pattern above for consistency.
    case "$mode" in
      client|setup|configure|run) ;;  # consumes --scope via <name>_pick_scope
      *) warn "--scope ignored for subcommand '${mode}' (only used by client/setup/configure/run)." ;;
    esac
  fi

  # list-models flags: warn if passed to a subcommand that doesn't consume
  # them. Mirrors the --cli-tool / --scope ignored-warn pattern above.
  if [ -n "${LIST_MODELS_OUTPUT:-}${LIST_MODELS_FORMAT:-}${LIST_MODELS_INCLUDE_EMBED:-}" ]; then
    case "$mode" in
      list-models) ;;  # consumes these
      *) warn "--output / --format / --include-embeddings ignored for subcommand '${mode}' (only used by list-models)." ;;
    esac
  fi

  # update flags: warn if passed to a subcommand that doesn't consume them.
  # Same ignored-warn discipline (D-016).
  if [ "${UPDATE_ALL:-0}" = 1 ] || [ "${UPDATE_CHECK_ONLY:-0}" = 1 ]; then
    case "$mode" in
      update) ;;  # consumes both
      *) warn "--all / --check ignored for subcommand '${mode}' (only used by update)." ;;
    esac
  fi
  if [ -n "${UPDATE_COMPONENTS_ARGV:-}" ] && [ "$mode" != "update" ]; then
    warn "Positional component args (${UPDATE_COMPONENTS_ARGV}) ignored for subcommand '${mode}' (only used by update)."
  fi

  # Expose the invoked subcommand to cleanup_local (audit finding N1)
  # so the Ctrl+C exit summary can branch on whether we actually owned
  # a local tunnel (client/setup/tunnel) vs not (status/stop/help/...).
  _INVOKED_MODE="$mode"

  case "$mode" in
    client)        mode_client ;;
    tunnel)        mode_tunnel ;;
    connect)       mode_connect ;;
    configure)     mode_configure ;;
    run)           mode_run ;;
    # 'setup' is a thin alias for 'client' that ALWAYS shows the
    # interactive picker, even if --cli-tool was passed. Useful for
    # one-off installations of a tool different from the user's usual.
    setup)         CLI_TOOL_OVERRIDE=""; FORCE_PICKER=1; mode_client ;;
    server)        mode_server ;;
    status)        mode_status ;;
    stop)          mode_stop ;;
    update)        mode_update ;;
    update-models) mode_update_models ;;
    list-models)   mode_list_models ;;
    clean)         mode_clean ;;
    install)       mode_install ;;
    uninstall)     mode_uninstall ;;
    help)          long_help ;;
    list-tools)    mode_list_tools ;;
  esac
}

main "$@"
