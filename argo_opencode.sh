#!/usr/bin/env bash
# argo_opencode.sh
#
# Self-contained orchestrator that lets Argonne users run OpenCode against
# argo-proxy from anywhere (inside or outside the ANL network).
#
# Modes:
#   argo_opencode.sh client          # default; runs the laptop-side flow
#   argo_opencode.sh server          # runs on the ANL compute node (auto-invoked)
#   argo_opencode.sh status          # check tunnel + remote proxy health
#   argo_opencode.sh stop            # tear down the local tunnel
#   argo_opencode.sh -h | --help
#
# Distribution: hosted at https://web.cels.anl.gov/~aattia/argo_opencode.sh
# Users:
#   curl -fsSL https://web.cels.anl.gov/~aattia/argo_opencode.sh -o argo_opencode.sh
#   bash argo_opencode.sh
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
# Bug history: B17 -- without the POSIXLY_CORRECT branch, `sh argo_opencode.sh`
# on macOS ran as far as opening the tunnel before bombing on `<(...)` in
# gather_summary. The re-exec now happens before any non-POSIX construct
# can be parsed.
if [ -z "${BASH_VERSION:-}" ] || [ -n "${POSIXLY_CORRECT:-}" ]; then
  # Drop POSIXLY_CORRECT so the re-exec'd bash doesn't inherit POSIX mode
  # via the env. (`exec bash` alone would re-set it from the inherited env.)
  unset POSIXLY_CORRECT
  exec bash "$0" "$@"
fi

set -euo pipefail

# ============================================================================
# TABLE OF CONTENTS
# ============================================================================
# Sections in order of appearance (grep for "SECTION:" to jump):
#
#   1.  LEGACY ENV SNAPSHOT      -- capture inherited env before reassignment
#   2.  USER-EDITABLE CONFIG     -- ANL_NODES, ANL_JUMP, defaults
#   3.  PRETTY PRINTING          -- colors, log/ok/warn/err/die/ask
#   4.  BOX DRAWING              -- print_summary_box and helpers
#   5.  PLATFORM HELPERS         -- detect_os, notify_user
#   6.  ENV NAMESPACING          -- legacy -> ARGO_OPENCODE_* promotion
#   7.  PORT RESOLUTION          -- read from config, --port handling
#   8.  JUMP HOST HANDLING       -- ssh_jump_args, jump_descr
#   9.  MFA / MULTIPLEXING       -- ssh_mux_args, ssh_args, ssh_reachable
#   10. USERNAME RESOLUTION      -- resolve_username, cache I/O
#   11. CONFIG FILE HANDLING     -- handle_config_file (k/b/d/m/a prompt)
#   12. OPENCODE CONFIG WRITER   -- write_opencode_config + ensure_opencode_installed
#   13. SSH PREFLIGHT            -- ssh_preflight (jump or first node)
#   14. NODE PICKER              -- pick_node, --node, --probe-nodes
#   15. REMOTE BOOTSTRAP         -- scp + ssh to invoke server mode
#   16. LOCAL TUNNEL + MONITOR   -- open_tunnel_and_monitor, health loop
#   17. CLIENT MODE              -- mode_client (orchestrates everything)
#   18. SERVER MODE              -- mode_server (runs on the ANL node)
#   19. SUMMARY GATHERING        -- fetch_proxy_models, gather_summary
#   20. SUMMARY RENDERING        -- render_summary (the big box)
#   21. STATUS / STOP            -- mode_status, mode_stop
#   22. UPDATE-MODELS            -- mode_update_models
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
#     `--port`/ARGO_OPENCODE_PORT override but prompt before mutating config.
#   * MFA mode (default) opens an SSH ControlMaster; subsequent calls reuse
#     the socket. Sockets at ~/.ssh/sockets/argo-opencode-*. `clean` closes them.
# ============================================================================

# ============================================================================
# SECTION: 1. LEGACY ENV SNAPSHOT
# ============================================================================
# Capture inherited env-var values BEFORE the user-editable config block
# (re)assigns the same names. Promotion to ARGO_OPENCODE_* happens later in
# the script, but it must read the inherited values, not the defaults.
_legacy_PROXY_PORT="${PROXY_PORT:-}"
_legacy_ANL_USERNAME="${ANL_USERNAME:-}"
_legacy_SHOW_MODELS="${SHOW_MODELS:-}"

# ============================================================================
# SECTION: 2. USER-EDITABLE CONFIG
# ============================================================================
# Add or remove ANL compute nodes here. The client probes them in order and
# uses the first one reachable through the jump host (or lets the user pick).
# To add a node, append a fully-qualified hostname.
ANL_NODES=(
  compute-01.cels.anl.gov
  compute-02.cels.anl.gov
  compute-03.cels.anl.gov
  # compute-04.cels.anl.gov   # <-- example: uncomment / add more here
  # compute-05.cels.anl.gov
)

ANL_JUMP="logins.cels.anl.gov"
# Default port used only when no other source resolves one. Resolution order:
#   1. --port CLI flag            (one-shot override; offers to migrate config)
#   2. ARGO_OPENCODE_PORT env var (canonical override)
#   3. PROXY_PORT env var         (deprecated alias; warns once)
#   4. baseURL in ~/.config/opencode/config.json   (the source of truth)
#   5. PROXY_PORT_DEFAULT below   (used only on first install)
PROXY_PORT_DEFAULT=64742
PROXY_PORT=""                      # populated by resolve_port() in main()
# shellcheck disable=SC2016
VENV_PATH='$HOME/agovenv'          # path on the ANL node (single quotes intentional;
                                   # $HOME is expanded server-side via `eval echo`)
SCREEN_SESSION="agovproxy"
HEALTH_INTERVAL=15                 # seconds between health probes (client-side)
HEALTH_FAIL_THRESHOLD=3            # consecutive failures before alerting

# Local state directory (laptop side)
STATE_DIR="${HOME}/.config/argo_opencode"
USER_CACHE="${STATE_DIR}/user"
NODE_CACHE="${STATE_DIR}/node"

# Remote paths (compute node side)
REMOTE_SELF=".argo_opencode.sh"
REMOTE_LOG=".argo_opencode.server.log"

# ============================================================================
# SECTION: 3. PRETTY PRINTING (colors + log/ok/warn/err/die/ask)
# ============================================================================
if [ -t 1 ]; then
  C_RED=$'\033[1;31m'; C_GRN=$'\033[1;32m'; C_YLW=$'\033[1;33m'
  C_BLU=$'\033[1;34m'; C_DIM=$'\033[2m'; C_OFF=$'\033[0m'
else
  C_RED=""; C_GRN=""; C_YLW=""; C_BLU=""; C_DIM=""; C_OFF=""
fi

log()  { printf '%s[argo_opencode]%s %s\n' "$C_BLU" "$C_OFF" "$*" >&2; }
ok()   { printf '%s[ ok ]%s %s\n' "$C_GRN" "$C_OFF" "$*" >&2; }
warn() { printf '%s[warn]%s %s\n' "$C_YLW" "$C_OFF" "$*" >&2; }
err()  { printf '%s[err ]%s %s\n' "$C_RED" "$C_OFF" "$*" >&2; }
die()  { err "$*"; exit 1; }
ask()  { local p="$1" def="${2:-}" reply; printf '%s%s%s ' "$C_YLW" "$p" "$C_OFF" >&2;
         read -r reply || true; printf '%s' "${reply:-$def}"; }

# ============================================================================
# SECTION: 4. BOX DRAWING (Unicode vs ASCII detection + print_summary_box)
# ============================================================================
# Prefer Unicode if the terminal looks UTF-8 capable, else ASCII.
# Set ARGO_BOX_STYLE=ascii or =unicode to force.
detect_box_style() {
  case "${ARGO_BOX_STYLE:-}" in
    ascii)   echo ascii; return ;;
    unicode) echo unicode; return ;;
  esac
  # Heuristic: locale advertises UTF-8 AND we're on a TTY.
  if [ -t 1 ] && printf '%s' "${LC_ALL:-${LC_CTYPE:-${LANG:-}}}" \
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
print_summary_box() {
  local title="$1" vcolor="$2" verdict="$3"; shift 3
  local lines=("$@")

  # Compute interior width = max of (title, verdict, all body lines), capped.
  local maxw=0 w line
  w="$(visible_width "$title")"; [ "$w" -gt "$maxw" ] && maxw="$w"
  w="$(visible_width "$verdict")"; [ "$w" -gt "$maxw" ] && maxw="$w"
  for line in "${lines[@]}"; do
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

  # Top border + title row
  printf '%s%s%s%s%s\n' "$C_DIM" "$BOX_TL" "$hbar" "$BOX_TR" "$C_OFF" >&2
  _bx_line "$title" "$C_BLU" >&2
  # Verdict row, separated by a thin rule
  printf '%s%s%s%s%s\n' "$C_DIM" "$BOX_ML" "$mbar" "$BOX_MR" "$C_OFF" >&2
  _bx_line "$verdict" "$vcolor" >&2
  # Body rows
  if [ "${#lines[@]}" -gt 0 ]; then
    printf '%s%s%s%s%s\n' "$C_DIM" "$BOX_ML" "$mbar" "$BOX_MR" "$C_OFF" >&2
    for line in "${lines[@]}"; do _bx_line "$line" "" >&2; done
  fi
  # Bottom border
  printf '%s%s%s%s%s\n' "$C_DIM" "$BOX_BL" "$hbar" "$BOX_BR" "$C_OFF" >&2
}

# ============================================================================
# SECTION: 5. PLATFORM HELPERS (detect_os, notify_user)
# ============================================================================
detect_os() {
  case "$(uname -s)" in
    Darwin) echo "macos" ;;
    Linux)  echo "linux" ;;
    *)      echo "unknown" ;;
  esac
}

notify_user() {
  # Loud cross-platform notification. Args: title body
  local title="$1" body="$2"
  printf '\a' >&2  # bell
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

# ============================================================================
# SECTION: 6. ENV NAMESPACING (legacy -> ARGO_OPENCODE_* promotion)
# ============================================================================
# Legacy names PROXY_PORT, ANL_USERNAME, SHOW_MODELS keep working with a
# one-time deprecation warning. Canonical names are ARGO_OPENCODE_PORT,
# ARGO_OPENCODE_USER, ARGO_OPENCODE_SHOW_MODELS.
_legacy_warned=""
_warn_legacy_env() {
  local old="$1" new="$2"
  case " $_legacy_warned " in *" $old "*) return ;; esac
  _legacy_warned="${_legacy_warned} ${old}"
  warn "env var '${old}' is deprecated; use '${new}' instead (still honored for now)"
}
# Promote inherited legacy values (snapshotted at top of file) into canonical
# slots, but only if the canonical name isn't already set explicitly.
[ -z "${ARGO_OPENCODE_USER:-}"        ] && [ -n "$_legacy_ANL_USERNAME" ] && \
  { _warn_legacy_env ANL_USERNAME ARGO_OPENCODE_USER; ARGO_OPENCODE_USER="$_legacy_ANL_USERNAME"; }
[ -z "${ARGO_OPENCODE_PORT:-}"        ] && [ -n "$_legacy_PROXY_PORT"   ] && \
  { _warn_legacy_env PROXY_PORT ARGO_OPENCODE_PORT; ARGO_OPENCODE_PORT="$_legacy_PROXY_PORT"; }
[ -z "${ARGO_OPENCODE_SHOW_MODELS:-}" ] && [ -n "$_legacy_SHOW_MODELS"  ] && \
  { _warn_legacy_env SHOW_MODELS ARGO_OPENCODE_SHOW_MODELS; ARGO_OPENCODE_SHOW_MODELS="$_legacy_SHOW_MODELS"; }

# ============================================================================
# SECTION: 7. PORT RESOLUTION (config.json baseURL is the source of truth)
# ============================================================================
# resolve_port writes the chosen port into PROXY_PORT (global). Order:
#   1. PORT_OVERRIDE_CLI         (set by --port flag)
#   2. ARGO_OPENCODE_PORT env
#   3. baseURL in ~/.config/opencode/config.json
#   4. PROXY_PORT_DEFAULT
PORT_OVERRIDE_CLI=""              # set by main() when --port given
PORT_FROM_CONFIG=""               # cached so we can detect mismatch later
PORT_SOURCE=""                    # diagnostic: which source above won

# Read the port from the OpenCode config's baseURL. Empty if unparseable.
read_port_from_opencode_config() {
  local cfg="${HOME}/.config/opencode/config.json" url=""
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

resolve_port() {
  local p=""
  if [ -n "$PORT_OVERRIDE_CLI" ]; then
    p="$PORT_OVERRIDE_CLI"; PORT_SOURCE="--port flag"
  elif [ -n "${ARGO_OPENCODE_PORT:-}" ]; then
    p="$ARGO_OPENCODE_PORT"; PORT_SOURCE="ARGO_OPENCODE_PORT env"
  else
    PORT_FROM_CONFIG="$(read_port_from_opencode_config || true)"
    if [ -n "$PORT_FROM_CONFIG" ]; then
      p="$PORT_FROM_CONFIG"; PORT_SOURCE="opencode config baseURL"
    else
      p="$PROXY_PORT_DEFAULT"; PORT_SOURCE="built-in default"
    fi
  fi
  # Always read config too (even when not chosen) so we can compare later.
  [ -z "$PORT_FROM_CONFIG" ] && PORT_FROM_CONFIG="$(read_port_from_opencode_config || true)"
  # Sanity check
  case "$p" in
    [1-9]|[1-9][0-9]|[1-9][0-9][0-9]|[1-9][0-9][0-9][0-9]|[1-5][0-9][0-9][0-9][0-9]|6[0-4][0-9][0-9][0-9]|65[0-4][0-9][0-9]|655[0-2][0-9]|6553[0-5]) ;;
    *) die "Resolved port '$p' is not a valid TCP port number." ;;
  esac
  PROXY_PORT="$p"
}

# ============================================================================
# SECTION: 8. JUMP HOST HANDLING (ssh_jump_args, jump_descr)
# ============================================================================
# By default we route via ANL_JUMP. With --no-jump (or ARGO_OPENCODE_NO_JUMP=1)
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
  if [ "${ARGO_OPENCODE_NO_JUMP:-0}" = 1 ]; then
    return
  fi
  if [ -n "$target" ] && [ "$target" = "$ANL_JUMP" ]; then
    return
  fi
  printf -- '-J %s@%s' "$user" "$ANL_JUMP"
}

# Human-readable description for plans/help/error messages.
jump_descr() {
  if [ "${ARGO_OPENCODE_NO_JUMP:-0}" = 1 ]; then
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
#   --no-mfa / ARGO_OPENCODE_NO_MFA=1   -- disable mux, restore BatchMode tests
#   ARGO_OPENCODE_CONTROL_PERSIST=N     -- seconds after last client to keep
#                                          the master alive (default 3600).
#                                          Use 'yes' for indefinite, 'no' to
#                                          die when the last client closes.
SSH_MUX_DIR="${HOME}/.ssh/sockets"
SSH_MUX_PERSIST_DEFAULT=3600

mfa_enabled() {
  [ "${ARGO_OPENCODE_NO_MFA:-0}" = 1 ] && return 1
  return 0
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
  local persist="${ARGO_OPENCODE_CONTROL_PERSIST:-$SSH_MUX_PERSIST_DEFAULT}"
  printf -- '-o ControlMaster=auto -o ControlPath=%s/argo-opencode-%%r-%%h-%%p -o ControlPersist=%s' \
    "$SSH_MUX_DIR" "$persist"
}

# Close any open master sockets we own. Called by `clean` and on demand.
ssh_mux_close_all() {
  local sock
  if [ ! -d "$SSH_MUX_DIR" ]; then return 0; fi
  for sock in "$SSH_MUX_DIR"/argo-opencode-*; do
    [ -S "$sock" ] || continue
    log "  closing mux socket: ${sock}"
    if [ "${CLEAN_DRY_RUN:-0}" = 1 ]; then
      log "    [dry-run] would: ssh -O exit -o ControlPath=${sock} dummy"
    else
      # ssh -O exit needs *something* to address; the path alone is enough.
      ssh -O exit -o "ControlPath=${sock}" x 2>/dev/null || rm -f "$sock"
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
ssh_reachable() {
  local user="$1" host="$2"
  if mfa_enabled; then
    # No BatchMode -- this WILL prompt Duo if no master socket exists yet.
    # ConnectTimeout is per network attempt, not per Duo prompt.
    # Pass $host so ssh_args drops '-J' when host == ANL_JUMP (loop guard).
    # shellcheck disable=SC2046
    ssh -o ConnectTimeout=15 -o StrictHostKeyChecking=accept-new \
        $(ssh_args "$user" "$host") "${user}@${host}" true 2>/dev/null
  else
    # shellcheck disable=SC2046
    ssh -o BatchMode=yes -o ConnectTimeout=5 -o StrictHostKeyChecking=accept-new \
        $(ssh_args "$user" "$host") "${user}@${host}" true 2>/dev/null
  fi
}

# Open the multiplex master to the given host explicitly. Triggers Duo once
# and leaves the master alive per ControlPersist. Useful before kicking off
# multiple commands so the user gets one prompt up front rather than at a
# random later moment.
# Usage: ssh_mux_open <user> <host>
ssh_mux_open() {
  local user="$1" host="$2"
  mfa_enabled || return 0
  log "Opening multiplexed SSH master to ${user}@${host} (Duo prompt expected once)..."
  # Pass $host so ssh_args knows to drop '-J' when host == ANL_JUMP (loop).
  # shellcheck disable=SC2046
  if ssh -o ConnectTimeout=30 -o StrictHostKeyChecking=accept-new \
       $(ssh_args "$user" "$host") "${user}@${host}" true; then
    ok "  master ready (subsequent SSH calls will reuse this connection)"
  else
    die "Failed to open multiplexed SSH master to ${user}@${host}."
  fi
}

# ============================================================================
# SECTION: 10. USERNAME RESOLUTION (resolve_username, cache I/O)
# ============================================================================
resolve_username() {
  # Priority: --user flag (sets ARGO_OPENCODE_USER) > env > cache > prompt.
  # ANL_USERNAME is honored as a deprecated alias (warning printed once
  # at top-level when promoted into ARGO_OPENCODE_USER).
  if [ -n "${ARGO_OPENCODE_USER:-}" ]; then
    echo "$ARGO_OPENCODE_USER"; return
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
  mkdir -p "$STATE_DIR"
  printf '%s\n' "$u" > "$USER_CACHE"
  echo "$u"
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

  if [ ! -f "$target" ]; then
    log "No existing ${desc} at ${target}; writing fresh one."
    "$writer" "$target"
    ok "Wrote ${desc}: ${target}"
    return
  fi

  # Render the proposed new config to a temp file for diffing.
  local proposed; proposed="$(mktemp -t argo_opencode.XXXXXX)"
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
        local bak
        bak="${target}.bak.$(date +%Y%m%d-%H%M%S)"
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
          local merged; merged="$(mktemp -t argo_opencode.XXXXXX)"
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

# ============================================================================
# SECTION: 12. OPENCODE CONFIG WRITER + INSTALLER (laptop side)
# ============================================================================
# Mirrors the maintainer's ~/.config/opencode/config.json, with the username
# substituted. Uses localhost (not 0.0.0.0) for clarity.
#
# The username is taken from the canonical env var ARGO_OPENCODE_USER, with
# legacy ANL_USERNAME as fallback. This writer is invoked indirectly via
# handle_config_file (which always passes only the destination path), so we
# can't accept user as a positional arg without changing that contract.
write_opencode_config() {
  local dest="$1"
  local user="${ARGO_OPENCODE_USER:-${ANL_USERNAME:-}}"
  [ -n "$user" ] || die "write_opencode_config: no username available (ARGO_OPENCODE_USER unset)"
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
  command -v opencode >/dev/null 2>&1 || die "OpenCode install reported success but binary not on PATH."
  ok "OpenCode installed."
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
  elif [ "${ARGO_OPENCODE_NO_JUMP:-0}" = 1 ]; then
    if [ -n "${ARGO_OPENCODE_NODE:-}" ]; then
      target="$ARGO_OPENCODE_NODE"
    elif [ "${#ANL_NODES[@]}" -gt 0 ]; then
      target="${ANL_NODES[0]}"
    else
      die "ARGO_OPENCODE_NO_JUMP is set but no node to preflight. Pass --node HOST or fill ANL_NODES."
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
  if ssh -o BatchMode=yes -o ConnectTimeout=5 -o StrictHostKeyChecking=accept-new \
       "${user}@${target}" true 2>/dev/null; then
    ok "Passwordless SSH to ${target} works."
    return
  fi
  err "Cannot reach ${user}@${target} without a password."
  cat >&2 <<EOF

  Set up SSH key-based auth before continuing:
    1. ssh-keygen -t ed25519        # if you have no key
    2. ssh-copy-id ${user}@${target}
    3. ssh ${user}@${target} true   # confirm it works without a password

EOF
  if [ "${ARGO_OPENCODE_NO_JUMP:-0}" = 1 ]; then
    cat >&2 <<EOF
  --no-jump is on, so the script tried ${target} directly. If you actually
  do need a jump host, drop --no-jump (and ARGO_OPENCODE_NO_JUMP).

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
pick_node() {
  local user="$1"

  # --node / ARGO_OPENCODE_NODE: skip the picker entirely. We still verify
  # reachability so we fail fast with a clear message rather than later in
  # the SSH bootstrap.
  if [ -n "${ARGO_OPENCODE_NODE:-}" ]; then
    local req="$ARGO_OPENCODE_NODE"
    local in_list=0 n
    for n in "${ANL_NODES[@]:-}"; do
      [ "$n" = "$req" ] && in_list=1 && break
    done
    [ "$in_list" -eq 1 ] || warn "Requested node '${req}' is not in ANL_NODES (proceeding anyway)."

    log "Verifying reachability of '${req}' $(jump_descr)..."
    if ssh_reachable "$user" "$req"; then
      ok "  reachable: ${req}"
      mkdir -p "$STATE_DIR"; printf '%s\n' "$req" > "$NODE_CACHE"
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
      if ssh_reachable "$user" "$node"; then
        ok "  reachable: ${node}"
        working+=("$node")
      else
        warn "  unreachable: ${node}"
      fi
    done
    [ "${#working[@]}" -gt 0 ] || die "No ANL_NODES are reachable. Check the list or your access."
  else
    # Skip probing; show all configured nodes.
    working=("${ANL_NODES[@]}")
  fi

  # Default = cached node if it's in the (working) list, else first entry.
  default="${working[0]}"
  if [ -f "$NODE_CACHE" ]; then
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
  if [ "${PROBE_NODES:-0}" != 1 ]; then
    printf '    %s(reachability NOT probed; pass --probe-nodes to test each first)%s\n' \
      "$C_DIM" "$C_OFF" >&2
  fi

  local picked
  while :; do
    local choice; choice="$(ask "Pick a node [1-${#working[@]}, Enter = default]:" "")"
    if [ -z "$choice" ]; then
      picked="$default"; break
    elif [[ "$choice" =~ ^[0-9]+$ ]] && [ "$choice" -ge 1 ] && [ "$choice" -le "${#working[@]}" ]; then
      picked="${working[$((choice-1))]}"; break
    else
      warn "Invalid choice."
    fi
  done

  mkdir -p "$STATE_DIR"; printf '%s\n' "$picked" > "$NODE_CACHE"
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
    local persist="${ARGO_OPENCODE_CONTROL_PERSIST:-$SSH_MUX_PERSIST_DEFAULT}"
    # Same %r-%h-%p literal tokens as ssh_mux_args (see comment there for why
    # we don't use %C here either). MUST match exactly so scp and ssh share
    # the same master socket for the same destination.
    scp_opts+=( -o ControlMaster=auto
                -o "ControlPath=${SSH_MUX_DIR}/argo-opencode-%r-%h-%p"
                -o "ControlPersist=${persist}" )
  fi
  if [ "${ARGO_OPENCODE_NO_JUMP:-0}" != 1 ]; then
    scp_opts+=( -o "ProxyJump=${user}@${ANL_JUMP}" )
  fi
  scp "${scp_opts[@]}" "$self" "${user}@${node}:${REMOTE_SELF}"

  log "Running server bootstrap on ${node}..."
  # Forward the canonical env names; --force-reinstall passes through too.
  local force_kv=""
  if [ -n "${FORCE_REINSTALL:-}" ]; then
    force_kv="ARGO_OPENCODE_FORCE_REINSTALL=1 "
  fi
  # shellcheck disable=SC2046
  ssh -o StrictHostKeyChecking=accept-new \
      $(ssh_args "$user" "$node") "${user}@${node}" \
      "ARGO_OPENCODE_USER='${user}' ARGO_OPENCODE_PORT='${PROXY_PORT}' ${force_kv}bash ~/${REMOTE_SELF} server" \
    || die "Server bootstrap on ${node} failed. Check ~/${REMOTE_LOG} on the node."
  ok "Server is up on ${node}:${PROXY_PORT}."
}

# ============================================================================
# SECTION: 16. LOCAL TUNNEL + HEALTH MONITOR (open_tunnel_and_monitor)
# ============================================================================
# Foreground ssh -L; background loop polls /health and notifies on failure.
# Reconnect-via-mux when the tunnel drops but the master is still alive.
SSH_TUNNEL_PID=""
MONITOR_PID=""

cleanup_local() {
  local rc=$?
  trap - EXIT INT TERM
  if [ -n "$MONITOR_PID" ] && kill -0 "$MONITOR_PID" 2>/dev/null; then
    kill "$MONITOR_PID" 2>/dev/null || true
  fi
  if [ -n "$SSH_TUNNEL_PID" ] && kill -0 "$SSH_TUNNEL_PID" 2>/dev/null; then
    log "Closing SSH tunnel (pid=${SSH_TUNNEL_PID})..."
    kill "$SSH_TUNNEL_PID" 2>/dev/null || true
    wait "$SSH_TUNNEL_PID" 2>/dev/null || true
  fi
  exit "$rc"
}

open_tunnel_and_monitor() {
  local user="$1" node="$2"

  # Refuse to clash with an existing local listener on the same port.
  if lsof -nPi ":${PROXY_PORT}" -sTCP:LISTEN >/dev/null 2>&1; then
    err "Port ${PROXY_PORT} is already in use locally."
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
  # B16 NOTE: under MFA mode, the foreground `ssh -N -L` we just spawned
  # routes through the existing ControlMaster connection (because
  # ControlMaster=auto is in $(ssh_args) and a master to ${user}@${node}
  # already exists from ssh_preflight). What this means in practice:
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
  ok "Tunnel is live. argo-proxy responding at http://localhost:${PROXY_PORT}"

  # Render the same summary box that `status` shows, so the user sees one
  # easily-interpretable block before we go quiet in the foreground.
  gather_summary
  render_summary

  log "You can now run: opencode    (or whatever client you prefer)"

  # Background health monitor. Notes the tunnel pid, polls /health on a timer,
  # notifies the user on sustained failure or tunnel-process death.
  #
  # Note: the monitor runs in a subshell (& backgrounded), so it cannot mutate
  # the parent's SSH_TUNNEL_PID. Reconnect-via-mux is therefore handled in the
  # PARENT, after `wait` returns -- see below. This intentionally trades a few
  # extra seconds of downtime for a correct pid handoff.
  #
  # B16: when SSH_TUNNEL_PID is empty (foreground ssh exited; mux master owns
  # the forward), there is no pid to watch. The monitor should keep polling
  # /health and only exit if /health has been down long enough that the
  # forward likely went away. The parent's wait-on-MONITOR_PID branch then
  # picks up.
  (
    fail=0
    tunnel_pid_to_watch="$SSH_TUNNEL_PID"
    while sleep "$HEALTH_INTERVAL"; do
      if curl -fsS --max-time 5 "http://localhost:${PROXY_PORT}/health" >/dev/null 2>&1; then
        fail=0
      else
        fail=$((fail+1))
        warn "Health check failed (${fail}/${HEALTH_FAIL_THRESHOLD})."
        if [ "$fail" -ge "$HEALTH_FAIL_THRESHOLD" ]; then
          notify_user "argo-proxy tunnel" "Lost connection to ${node}:${PROXY_PORT}. The SSH tunnel or the remote proxy is down."
          # In mux-owned mode, sustained health failure = forward likely
          # gone; exit the monitor so the parent can react.
          [ -z "$tunnel_pid_to_watch" ] && exit 0
          fail=0  # avoid spamming; re-arm
        fi
      fi
      # Detect tunnel process death (only meaningful when we have a pid).
      if [ -n "$tunnel_pid_to_watch" ] && ! kill -0 "$tunnel_pid_to_watch" 2>/dev/null; then
        exit 0
      fi
    done
  ) &
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
  # Special case: when SSH_TUNNEL_PID is empty (B16 -- foreground ssh exited
  # but the mux master is forwarding), there's no foreground process to wait
  # on. We still want to monitor health, so we wait on the monitor pid
  # instead (or sleep forever if the monitor is also gone). The reconnect
  # logic below skips the ssh-O-check + respawn dance because the master is
  # already serving the forward.
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

    # Try silent reconnect under MFA mode if the mux master is still alive.
    # Use the local `user` arg (not the global $ANL_USERNAME) so this code
    # path stays correct if invoked from a context that didn't set the global.
    local reconnected=0
    if mfa_enabled; then
      # shellcheck disable=SC2046
      if ssh -O check $(ssh_args "$user" "$node") "${user}@${node}" 2>/dev/null; then
        warn "SSH multiplex master is still alive; attempting silent reconnect..."
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
          ok "Reconnected silently via SSH multiplex master (pid=${SSH_TUNNEL_PID})."
          reconnected=1
          # Restart the monitor in the background since the previous one exited.
          if [ -n "${MONITOR_PID:-}" ] && ! kill -0 "$MONITOR_PID" 2>/dev/null; then
            (
              fail=0
              while sleep "$HEALTH_INTERVAL"; do
                if curl -fsS --max-time 5 "http://localhost:${PROXY_PORT}/health" >/dev/null 2>&1; then
                  fail=0
                else
                  fail=$((fail+1))
                  warn "Health check failed (${fail}/${HEALTH_FAIL_THRESHOLD})."
                  if [ "$fail" -ge "$HEALTH_FAIL_THRESHOLD" ]; then
                    notify_user "argo-proxy tunnel" "Lost connection to ${node}:${PROXY_PORT}."
                    fail=0
                  fi
                fi
                if ! kill -0 "$SSH_TUNNEL_PID" 2>/dev/null; then exit 0; fi
              done
            ) &
            MONITOR_PID=$!
          fi
        else
          warn "Silent reconnect did not become healthy in 10s; bailing."
          # Make sure we don't leak the failed reconnect ssh.
          kill "$SSH_TUNNEL_PID" 2>/dev/null || true
          notify_user "argo-proxy tunnel" "Silent reconnect failed. Run: bash $0 client"
        fi
      else
        warn "SSH multiplex master is gone (Duo prompt would be required to reconnect)."
        notify_user "argo-proxy tunnel" "Tunnel down; re-run: bash $0 client"
      fi
    else
      notify_user "argo-proxy tunnel" "Tunnel down; re-run: bash $0 client"
    fi

    if [ "$reconnected" -eq 0 ]; then
      break
    fi
    # Loop back to wait on the new SSH_TUNNEL_PID.
  done

  cleanup_local
}

# ============================================================================
# SECTION: 17. CLIENT MODE (orchestrates the full laptop -> ANL flow)
# ============================================================================
mode_client() {
  ANL_USERNAME="$(resolve_username)"
  export ANL_USERNAME ARGO_OPENCODE_USER="$ANL_USERNAME"
  log "Using ANL username: ${ANL_USERNAME}"
  log "Using port: ${PROXY_PORT}  (source: ${PORT_SOURCE})"

  # If --port (or ARGO_OPENCODE_PORT) was used and disagrees with config.json,
  # ask the user before mutating their config. Without an explicit override,
  # we already read the port FROM the config, so by definition no mismatch.
  #
  # Four options:
  #   [m] migrate config + continue on override port
  #   [u] use override port for THIS run only; don't touch config
  #       (useful for a parallel test tunnel, or a short-lived override
  #       when you don't want to disturb a working OpenCode setup. The
  #       caveat is that nothing on the OpenCode side will be talking to
  #       the override-port tunnel -- you'd point a separate client at it
  #       manually, or use the run purely for testing/inspection.)
  #   [k] keep config; use the config's port (override ignored)
  #   [a] abort; resolve manually
  if [ -n "$PORT_FROM_CONFIG" ] && [ "$PROXY_PORT" != "$PORT_FROM_CONFIG" ]; then
    warn "Port mismatch:"
    warn "  --port / env requested : ${PROXY_PORT}"
    warn "  ~/.config/opencode/config.json baseURL: ${PORT_FROM_CONFIG}"
    cat >&2 <<EOF

  OpenCode reads its baseURL once at launch, so a tunnel on ${PROXY_PORT}
  while config still says ${PORT_FROM_CONFIG} means OpenCode will fail to
  connect (refused/wrong port). Choose:
    [m] migrate config to ${PROXY_PORT}, then continue (writes config.json)
    [u] use ${PROXY_PORT} for THIS run only; do NOT touch config
        (parallel/test tunnel; OpenCode will keep talking to ${PORT_FROM_CONFIG})
    [k] keep config at ${PORT_FROM_CONFIG}; use that port for the tunnel too
    [a] abort; resolve manually
EOF
    local choice; choice="$(ask "Your choice [m/u/k/a]:" "k")"
    case "$choice" in
      m|M) ok "Will migrate OpenCode config to port ${PROXY_PORT}." ;;
      u|U) ok "Using port ${PROXY_PORT} for this run only; config keeps ${PORT_FROM_CONFIG}."
           # Suppress the otherwise-mandatory OpenCode config write below.
           # We accomplish this by setting a flag the writer step honors.
           SKIP_OPENCODE_CONFIG_WRITE=1 ;;
      k|K) PROXY_PORT="$PORT_FROM_CONFIG"; ok "Using port ${PROXY_PORT} from config (override ignored)." ;;
      a|A) die "Aborted at port-reconciliation step." ;;
      *)   die "Unrecognized choice; aborting." ;;
    esac
  fi

  # Order under MFA: pick the node FIRST, then open the mux master against
  # that node. (Cannot open against ANL_JUMP -- jump host is shell-restricted.)
  # Order under --no-mfa: preflight against the jump host first (BatchMode
  # test is fast and gives clean SSH-key error message), then pick node.
  if mfa_enabled; then
    # If --node / ARGO_OPENCODE_NODE was passed, pick_node calls ssh_reachable
    # which is itself the first SSH to the node; that opens the mux master
    # implicitly. If the user is taking the static-list picker (default), no
    # SSH happens during pick_node and we open the master explicitly below.
    local node; node="$(pick_node "$ANL_USERNAME")"
    log "Selected node: ${node}"
    ssh_preflight "$ANL_USERNAME" "$node"
  else
    ssh_preflight "$ANL_USERNAME"
    local node; node="$(pick_node "$ANL_USERNAME")"
    log "Selected node: ${node}"
  fi

  ensure_opencode_installed
  if [ "${SKIP_OPENCODE_CONFIG_WRITE:-0}" = 1 ]; then
    log "Skipping OpenCode config write (--port override + [u] choice)."
    log "  config.json baseURL is unchanged at port ${PORT_FROM_CONFIG};"
    log "  this run's tunnel is on port ${PROXY_PORT}."
  else
    handle_config_file "${HOME}/.config/opencode/config.json" "OpenCode config" write_opencode_config
  fi

  remote_bootstrap "$ANL_USERNAME" "$node"
  open_tunnel_and_monitor "$ANL_USERNAME" "$node"
}

# ============================================================================
# SECTION: 18. SERVER MODE (runs on the ANL compute node, idempotent)
# ============================================================================
# Validates Python>=3.10 + venv + argo-proxy 'serve' subcommand; (re)creates
# venv if needed; writes ~/.config/argoproxy/config.yaml; verifies any existing
# listener is OURS before reusing; starts argo-proxy in screen/tmux/nohup.

# argo-proxy YAML config writer (server side). Uses the port and username
# the client passed in via env (ARGO_OPENCODE_USER / ARGO_OPENCODE_PORT).
# Same writer-contract caveat as write_opencode_config: handle_config_file
# only passes the dest path, so we resolve the user from env.
#
# B13 ownership policy
# --------------------
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
#                               B12 server-side check enforces this
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
  local user="${ARGO_OPENCODE_USER:-${ANL_USERNAME:-}}"
  [ -n "$user" ] || die "write_argoproxy_config: no username available (ARGO_OPENCODE_USER unset)"

  local real_cfg="${HOME}/.config/argoproxy/config.yaml"

  # Case 1: no existing file -- emit defaults.
  if [ ! -f "$real_cfg" ]; then
    cat > "$dest" <<EOF
config_version: "3"
user: "${user}"
host: 127.0.0.1
port: ${PROXY_PORT}
verbose: true
argo_base_url: "https://apps.inside.anl.gov/argoapi"
EOF
    return
  fi

  # Case 2: existing file -- merge. Pick the venv python if available so we
  # use the PyYAML that argo-proxy itself uses. Fall back to system python3
  # (which may or may not have PyYAML; if not, we degrade to "fresh write
  # behavior with a loud warning so the user knows their extras would be
  # lost on [b]").
  local pyexe=""
  local venv_dir; venv_dir="$(eval echo "$VENV_PATH" 2>/dev/null || true)"
  if [ -n "$venv_dir" ] && [ -x "${venv_dir}/bin/python" ]; then
    pyexe="${venv_dir}/bin/python"
  elif command -v python3 >/dev/null 2>&1; then
    pyexe="python3"
  fi

  if [ -z "$pyexe" ]; then
    warn "write_argoproxy_config: no python available for YAML merge;"
    warn "  falling back to defaults-only output. Existing keys at"
    warn "  ${real_cfg} would be LOST if you pick [b]."
    cat > "$dest" <<EOF
config_version: "3"
user: "${user}"
host: 127.0.0.1
port: ${PROXY_PORT}
verbose: true
argo_base_url: "https://apps.inside.anl.gov/argoapi"
EOF
    return
  fi

  # Try the merge. If PyYAML is missing or the existing file fails to parse,
  # exit code != 0; we then fall back to defaults-only with a warning so
  # the script doesn't hang on a partial/empty proposed file.
  if ! "$pyexe" - "$real_cfg" "$dest" "$user" "$PROXY_PORT" <<'PYEOF' 2>/dev/null
import sys
try:
    import yaml
except ImportError:
    sys.exit(2)
src, dst, user, port = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4])
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
# Provide sensible defaults for keys argo-proxy needs but the existing file
# might lack (e.g. a legacy file with no argo_base_url and no verbose).
data.setdefault('verbose', True)
data.setdefault('argo_base_url', "https://apps.inside.anl.gov/argoapi")
with open(dst, 'w') as f:
    yaml.safe_dump(data, f, default_flow_style=False, sort_keys=False)
PYEOF
  then
    warn "write_argoproxy_config: YAML merge failed (PyYAML missing or"
    warn "  existing config unparseable); falling back to defaults-only."
    warn "  Existing keys at ${real_cfg} would be LOST if you pick [b]."
    cat > "$dest" <<EOF
config_version: "3"
user: "${user}"
host: 127.0.0.1
port: ${PROXY_PORT}
verbose: true
argo_base_url: "https://apps.inside.anl.gov/argoapi"
EOF
  fi
}

mode_server() {
  # Canonical names; fall back to legacy aliases for one cycle so direct
  # 'bash argo_opencode.sh server' invocations don't break for anyone who
  # was setting ANL_USERNAME/PROXY_PORT manually.
  : "${ARGO_OPENCODE_USER:=${ANL_USERNAME:-}}"
  : "${ARGO_OPENCODE_PORT:=${PROXY_PORT:-}}"
  ANL_USERNAME="${ARGO_OPENCODE_USER}"
  PROXY_PORT="${ARGO_OPENCODE_PORT}"
  : "${ANL_USERNAME:?ARGO_OPENCODE_USER must be set when invoking server mode}"
  : "${PROXY_PORT:?ARGO_OPENCODE_PORT must be set when invoking server mode}"

  # If we haven't already, re-invoke ourselves with stdout+stderr piped through
  # tee so the bootstrap log captures everything. Avoids process substitution
  # (>(...)) so this stays robust on minimal shells.
  #
  # IMPORTANT: `exec CMD | tee FILE` does NOT replace the current shell with
  # the pipeline -- bash applies `exec` only to the LEFT side of the pipe.
  # The current shell waits for the pipeline, then continues running the rest
  # of mode_server, causing the bootstrap to run TWICE (B14). The second run
  # hits the "Existing argo-proxy already serving... reusing." path so it
  # appears benign but it's still wrong: it spends time, prompts the user
  # again on the same handle_config_file step, and confuses the log.
  #
  # Fix: drop `exec`, run the pipeline, exit with the bash leg's exit code
  # (PIPESTATUS[0]) so server failures still propagate to remote_bootstrap.
  if [ -z "${ARGO_OPENCODE_LOGGING:-}" ]; then
    export ARGO_OPENCODE_LOGGING=1
    mkdir -p "$(dirname "${HOME}/${REMOTE_LOG}")"
    bash "$0" server 2>&1 | tee -a "${HOME}/${REMOTE_LOG}"
    exit "${PIPESTATUS[0]}"
  fi

  log "[server] starting bootstrap on $(hostname) for user=${ANL_USERNAME} port=${PROXY_PORT}"

  # 1) Python 3.10+ on the system path (used to build the venv if missing).
  command -v python3 >/dev/null 2>&1 || die "python3 not found on $(hostname)."
  local pyver; pyver="$(python3 -c 'import sys;print("%d.%d"%sys.version_info[:2])')"
  case "$pyver" in
    3.1[0-9]|3.[2-9][0-9]|[4-9].*) ok "system python3 ${pyver} OK" ;;
    *) die "argo-proxy needs Python 3.10+; system python3 is ${pyver}." ;;
  esac

  # 2) venv: optionally wipe, then create or validate.
  local venv; venv="$(eval echo "$VENV_PATH")"

  if [ -n "${ARGO_OPENCODE_FORCE_REINSTALL:-}" ] && [ -d "$venv" ]; then
    warn "ARGO_OPENCODE_FORCE_REINSTALL set; removing existing venv at ${venv}..."
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
  #    config.yaml's user matches ARGO_OPENCODE_USER.
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
      local want_user="${ARGO_OPENCODE_USER:-${ANL_USERNAME:-}}"
      local cfg_user
      cfg_user="$(awk -F'"' '/^[[:space:]]*user:/{print $2; exit}' \
                   "${HOME}/.config/argoproxy/config.yaml" 2>/dev/null)"
      if [ -n "$cfg_user" ] && [ -n "$want_user" ] && [ "$cfg_user" != "$want_user" ]; then
        err "Existing argo-proxy on :${PROXY_PORT} (pid ${listener_pid}) is configured for user '${cfg_user}', not '${want_user}'."
        err "  Refusing to reuse it; calls would be misattributed."
        die "  Stop it first:  screen -S ${SCREEN_SESSION} -X quit   (or pick another --port)"
      fi
      ok "Existing argo-proxy already serving on 127.0.0.1:${PROXY_PORT} (pid ${listener_pid}); reusing."
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

  # If a stale session exists but the port isn't answering, kill it.
  case "$launcher" in
    screen)
      if screen -ls 2>/dev/null | grep -q "\.${SCREEN_SESSION}\b"; then
        warn "Stale screen session '${SCREEN_SESSION}' found; killing it."
        screen -S "${SCREEN_SESSION}" -X quit || true
      fi
      log "Starting argo-proxy in screen session '${SCREEN_SESSION}'..."
      screen -dmS "${SCREEN_SESSION}" "${venv}/bin/argo-proxy" serve
      ;;
    tmux)
      if tmux has-session -t "${SCREEN_SESSION}" 2>/dev/null; then
        warn "Stale tmux session '${SCREEN_SESSION}' found; killing it."
        tmux kill-session -t "${SCREEN_SESSION}" || true
      fi
      log "Starting argo-proxy in tmux session '${SCREEN_SESSION}'..."
      tmux new-session -d -s "${SCREEN_SESSION}" "${venv}/bin/argo-proxy serve"
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
      if [ -f "${HOME}/argoproxy.out" ]; then
        err "Last 30 lines of argoproxy.out:"
        tail -n 30 "${HOME}/argoproxy.out" >&2
      fi
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
  local cfg="${HOME}/.config/opencode/config.json"
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

  # Listener (lsof exits 1 when nothing matches; '|| true' keeps pipefail happy)
  local lsof_line
  lsof_line="$( { lsof -nPi ":${PROXY_PORT}" -sTCP:LISTEN 2>/dev/null || true; } \
                 | awk 'NR==2{print $2" "$9; exit}')"
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
    verdict="DEGRADED   -  tunnel up, proxy NOT answering"
    vcolor="$C_YLW"
  else
    verdict="FAIL       -  no local tunnel on :${PROXY_PORT}"
    vcolor="$C_RED"
  fi

  # Body lines
  local lines=()

  # Connection block
  local listener_str
  if [ "$SUM_LISTENER_OK" -eq 1 ]; then
    listener_str="pid ${SUM_LISTENER_PID} bound to ${SUM_LISTENER_BIND}"
  else
    listener_str="(no local listener)"
  fi
  lines+=("Local listener      : ${listener_str}")

  local health_str
  if [ "$SUM_HEALTH_OK" -eq 1 ]; then
    health_str="healthy  (http://localhost:${PROXY_PORT}/health)"
  else
    health_str="UNREACHABLE on http://localhost:${PROXY_PORT}/health"
  fi
  lines+=("Proxy health        : ${health_str}")

  # --- Models subsection ---------------------------------------------------
  if [ "$SUM_MODELS_OK" -eq 1 ]; then
    local avail_str="${SUM_MODEL_COUNT} available at /v1/models"
    if [ -n "$SUM_MODEL_SAMPLE" ]; then
      avail_str="${avail_str}  (e.g. ${SUM_MODEL_SAMPLE}, ...)"
    fi
    lines+=("Models available    : ${avail_str}")
  else
    lines+=("Models available    : (unknown -- proxy unreachable)")
  fi
  if [ "$SUM_CFG_COUNT" -gt 0 ]; then
    if [ "$SUM_MODELS_OK" -eq 1 ]; then
      lines+=("Models configured   : ${SUM_CFG_COUNT} in opencode config (${SUM_CFG_AVAIL_COUNT} reachable)")
    else
      lines+=("Models configured   : ${SUM_CFG_COUNT} in opencode config (reachability unknown)")
    fi
    if [ "$SUM_CFG_ORPHAN_COUNT" -gt 0 ]; then
      local orphan_str="${SUM_CFG_ORPHAN_COUNT} configured but NOT in /v1/models: ${SUM_CFG_ORPHAN_LIST}"
      lines+=("Models orphaned     : ${orphan_str}")
      lines+=("                      (run '$(basename "$0") update-models' to refresh)")
    fi
    # Hint: there are reachable chat models (unique by internal_name, no
    # embeddings) the user has not added to opencode yet. The math here mirrors
    # what `update-models` would actually do, so the count is honest.
    if [ "$SUM_MODELS_OK" -eq 1 ]; then
      local missing=$((SUM_MODEL_UNIQ_COUNT - SUM_CFG_AVAIL_COUNT))
      if [ "$missing" -gt 0 ]; then
        lines+=("Models unconfigured : ${missing} reachable chat model(s) not in opencode config")
        lines+=("                      (run '$(basename "$0") update-models' to add them all)")
      fi
    fi
  else
    lines+=("Models configured   : 0 in opencode config")
    lines+=("                      (run '$(basename "$0") update-models' to populate)")
  fi

  # Tunnel uptime (if we have a pid)
  if [ -n "$SUM_LISTENER_PID" ]; then
    local uptime_str
    uptime_str="$(ps -o etime= -p "$SUM_LISTENER_PID" 2>/dev/null | awk '{$1=$1;print}' || true)"
    if [ -n "$uptime_str" ]; then
      lines+=("Tunnel uptime       : ${uptime_str}  (HH:MM:SS or DD-HH:MM:SS)")
    fi
  fi

  # Configuration block
  lines+=("")
  lines+=("Configured port     : ${PROXY_PORT}")
  lines+=("Jump host           : ${ANL_JUMP}")
  # Only show cached identity rows when something is actually cached.
  # Use if/then so a failed test doesn't kill the function under set -e.
  local have_user=0 have_node=0
  if [ "$cached_user" != "(unset)" ]; then have_user=1; fi
  if [ "$cached_node" != "(unset)" ]; then have_node=1; fi
  if [ "$have_user" -eq 1 ]; then lines+=("Cached username     : ${cached_user}"); fi
  if [ "$have_node" -eq 1 ]; then lines+=("Cached node         : ${cached_node}"); fi
  if [ "$have_user" -eq 0 ] && [ "$have_node" -eq 0 ]; then
    lines+=("Cached identity     : (none yet -- run '$(basename "$0") client' to set)")
  fi

  # Paths block: only the OpenCode config is always relevant. The state dir
  # and the remote log path are only meaningful once 'client' has run, so
  # suppress them when there is nothing real to point at.
  lines+=("")
  lines+=("OpenCode config     : ${HOME}/.config/opencode/config.json")
  if [ -d "$STATE_DIR" ] || [ "$have_user" -eq 1 ] || [ "$have_node" -eq 1 ]; then
    lines+=("Script state dir    : ${STATE_DIR}")
  fi
  if [ "$have_user" -eq 1 ] && [ "$have_node" -eq 1 ]; then
    lines+=("Remote bootstrap log: ${cached_user}@${cached_node}:~/${REMOTE_LOG}")
  fi

  # Next-step hint
  lines+=("")
  if [ "$SUM_LISTENER_OK" -eq 1 ] && [ "$SUM_HEALTH_OK" -eq 1 ] && [ "$SUM_MODELS_OK" -eq 1 ]; then
    if [ "$SUM_CFG_ORPHAN_COUNT" -gt 0 ]; then
      lines+=("Next step           : run '$(basename "$0") update-models' to refresh stale entries,")
      lines+=("                      then 'opencode' in another terminal")
    else
      lines+=("Next step           : run  'opencode'  in another terminal")
    fi
  elif [ "$SUM_LISTENER_OK" -eq 0 ]; then
    lines+=("Next step           : start the tunnel with  '$(basename "$0") client'")
  elif [ "$SUM_HEALTH_OK" -eq 0 ]; then
    if [ "$cached_node" != "(unset)" ] && [ "$cached_user" != "(unset)" ]; then
      lines+=("Next step           : ssh -J ${cached_user}@${ANL_JUMP} ${cached_user}@${cached_node} \\")
      lines+=("                        'tail -n 80 ~/${REMOTE_LOG}'")
    else
      lines+=("Next step           : check the remote argo-proxy log on the compute node")
    fi
  else
    lines+=("Next step           : check argo-proxy logs on the compute node")
  fi

  echo >&2
  print_summary_box "argo_opencode  --  status summary" "$vcolor" "$verdict" "${lines[@]}"
}

# ============================================================================
# SECTION: 21. STATUS / STOP (mode_status, mode_stop)
# ============================================================================
mode_status() {
  log "Local tunnel listener on :${PROXY_PORT}:"
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
    if [ "${ARGO_OPENCODE_SHOW_MODELS:-0}" = "1" ]; then
      curl -fsS --max-time 5 "http://localhost:${PROXY_PORT}/v1/models" 2>/dev/null \
        | (command -v jq >/dev/null 2>&1 && jq . || cat) || true
    else
      log "  (rerun with: ARGO_OPENCODE_SHOW_MODELS=1 bash $(basename "$0") status   to see the full list)"
    fi
  fi

  render_summary

  # Exit code reflects health for use in && chains.
  if [ "$SUM_LISTENER_OK" -eq 1 ] && [ "$SUM_HEALTH_OK" -eq 1 ] && [ "$SUM_MODELS_OK" -eq 1 ]; then
    return 0
  fi
  return 1
}

mode_stop() {
  log "Killing local processes listening on :${PROXY_PORT}..."
  local pids
  pids="$(lsof -nPi ":${PROXY_PORT}" -sTCP:LISTEN -t 2>/dev/null || true)"
  if [ -z "$pids" ]; then
    ok "Nothing to stop locally."
  else
    echo "$pids" | xargs -n1 kill 2>/dev/null || true
    sleep 1
    echo "$pids" | xargs -n1 -I{} sh -c 'kill -0 {} 2>/dev/null && kill -9 {} || true'
    ok "Killed: ${pids//$'\n'/ }"
  fi
  warn "Note: this does NOT stop argo-proxy on the ANL node. To stop it remotely,"
  warn "  use the launcher actually used by 'server' mode (screen is preferred,"
  warn "  tmux is the next fallback, then nohup):"
  cat >&2 <<EOF
  # if started under screen (default when available):
  ssh -J <user>@${ANL_JUMP} <user>@<node> 'screen -S ${SCREEN_SESSION} -X quit'
  # if started under tmux:
  ssh -J <user>@${ANL_JUMP} <user>@<node> 'tmux kill-session -t ${SCREEN_SESSION}'
  # if started via nohup (no session manager available):
  ssh -J <user>@${ANL_JUMP} <user>@<node> 'pkill -f "argo-proxy serve"'
  # or just use 'clean' to do all of the above + tear down local state.
EOF
}

# ============================================================================
# SECTION: 22. UPDATE-MODELS (mode_update_models)
# ============================================================================
# Refreshes provider.argo.models in ~/.config/opencode/config.json from the
# live /v1/models endpoint, preserving everything else in the config.
mode_update_models() {
  local cfg="${HOME}/.config/opencode/config.json"

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
  if [ -n "$removed" ]; then log "Will REMOVE: ${removed}"; fi
  if [ -z "$added" ] && [ -z "$removed" ]; then
    log "Configured models already match /v1/models."
  fi

  # Stash the new models block in a global so the writer closure can find it
  # (handle_config_file invokes the writer once for diff and again on overwrite).
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
# SECTION: 24. CLEAN MODE (mode_clean -- local + remote artifact removal)
# ============================================================================
mode_clean() {
  # Resolve user/node for the remote step, with this precedence:
  #   --user / ARGO_OPENCODE_USER  >  cached value in STATE_DIR
  #   --node / ARGO_OPENCODE_NODE  >  cached value in STATE_DIR
  # Both can be empty if we have nothing to go on -- remote step is then
  # honestly skipped.
  local cached_user="" cached_node=""
  if [ -n "${ARGO_OPENCODE_USER:-}" ]; then
    cached_user="$ARGO_OPENCODE_USER"
  elif [ -f "$USER_CACHE" ]; then
    cached_user="$(cat "$USER_CACHE")"
  fi
  if [ -n "${ARGO_OPENCODE_NODE:-}" ]; then
    cached_node="$ARGO_OPENCODE_NODE"
  elif [ -f "$NODE_CACHE" ]; then
    cached_node="$(cat "$NODE_CACHE")"
  fi
  # Mark whether each value came from CLI/env vs the cache (for the plan box).
  local user_src node_src
  if   [ -n "${ARGO_OPENCODE_USER:-}" ];      then user_src="(--user/env)"
  elif [ -f "$USER_CACHE" ];                  then user_src="(cache)"
  else                                             user_src=""
  fi
  if   [ -n "${ARGO_OPENCODE_NODE:-}" ];      then node_src="(--node/env)"
  elif [ -f "$NODE_CACHE" ];                  then node_src="(cache)"
  else                                             node_src=""
  fi

  # Local listener (likely our SSH tunnel)
  local listener_pid=""
  listener_pid="$( { lsof -nPi ":${PROXY_PORT}" -sTCP:LISTEN -t 2>/dev/null || true; } | head -n1)"

  # Local backups we left behind
  local oc_backups=""; oc_backups="$(ls -1 "${HOME}/.config/opencode/config.json.bak."* 2>/dev/null || true)"

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

  print_summary_box "argo_opencode  --  clean plan" "$C_YLW" \
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
    mux_count="$( { ls -1 "${SSH_MUX_DIR}"/argo-opencode-* 2>/dev/null || true; } | wc -l | tr -d ' ')"
  fi

  cat >&2 <<EOF

LOCAL  -  safe (fully owned by this script)
  ~/.config/argo_opencode/                     $( [ -d "$STATE_DIR" ] && echo "(present)" || echo "(absent)" )
  Local SSH tunnel pid on :${PROXY_PORT}                $( [ -n "$listener_pid" ] && echo "(pid ${listener_pid})" || echo "(none)" )
  SSH multiplex sockets in ${SSH_MUX_DIR}/  $( [ "$mux_count" -gt 0 ] && echo "(${mux_count} present)" || echo "(none)" )

LOCAL  -  risky (created/edited by us, but path is owned by another tool)
  ~/.config/opencode/config.json               $( [ -f "${HOME}/.config/opencode/config.json" ] && echo "(present, ${risky_file_action})" || echo "(absent)" )
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
    \$HOME/agovenv/                            (Python venv we created)
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

  # Local: stop the tunnel first so we don't leave a dangling listener after
  # we've removed our cached state.
  if [ -n "$listener_pid" ]; then
    if [ "${CLEAN_DRY_RUN:-0}" = 1 ]; then
      log "Local SSH tunnel on :${PROXY_PORT} (pid ${listener_pid})..."
      log "  [dry-run] would: kill ${listener_pid}"
    else
      log "Stopping local SSH tunnel (pid ${listener_pid})..."
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
  _clean_risky_file "${HOME}/.config/opencode/config.json" \
    "OpenCode config" \
    "We wrote/edited the 'argo' provider block. The rest of the file may be your own (other providers, OpenCode preferences). Recommended: [r]estore from backup if you have one, otherwise [k]eep."

  # Remote
  if [ "${CLEAN_LOCAL_ONLY:-0}" != 1 ] && [ -n "$cached_user" ] && [ -n "$cached_node" ]; then
    export ARGO_OPENCODE_USER="$cached_user"
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
    remote_script_file="$(mktemp -t argo_opencode_remote.XXXXXX)"
    # shellcheck disable=SC2064
    trap "rm -f '${remote_script_file}'" RETURN
    cat > "$remote_script_file" <<'EOS'
set -u
: "${SCREEN_SESSION:?}" "${REMOTE_SELF:?}" "${REMOTE_LOG:?}" "${RC:?}" "${DRY:?}"

_say() { printf '%s\n' "$*" >&2; }
_rm()  { [ "$DRY" = 1 ] && _say "[dry-run] would remove: $1" || { rm -rf -- "$1" && _say "removed: $1"; }; }

# Kill the screen/tmux session
if command -v screen >/dev/null 2>&1 && screen -ls 2>/dev/null | grep -q "\.${SCREEN_SESSION}\b"; then
  if [ "$DRY" = 1 ]; then
    _say "[dry-run] would kill screen session: $SCREEN_SESSION"
  else
    screen -S "$SCREEN_SESSION" -X quit && _say "killed screen session: $SCREEN_SESSION" || _say "screen quit returned non-zero"
  fi
fi
if command -v tmux >/dev/null 2>&1 && tmux has-session -t "$SCREEN_SESSION" 2>/dev/null; then
  if [ "$DRY" = 1 ]; then
    _say "[dry-run] would kill tmux session: $SCREEN_SESSION"
  else
    tmux kill-session -t "$SCREEN_SESSION" && _say "killed tmux session: $SCREEN_SESSION" || true
  fi
fi

# Safe files
[ -f "$HOME/$REMOTE_SELF" ] && _rm "$HOME/$REMOTE_SELF"
[ -f "$HOME/$REMOTE_LOG"  ] && _rm "$HOME/$REMOTE_LOG"
[ -f "$HOME/argoproxy.out" ] && _rm "$HOME/argoproxy.out"
[ -d "$HOME/agovenv"       ] && _rm "$HOME/agovenv"

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

    # Forward the values we need via env on the ssh command line.
    local remote_env
    remote_env="SCREEN_SESSION='${SCREEN_SESSION}' REMOTE_SELF='${REMOTE_SELF}' REMOTE_LOG='${REMOTE_LOG}' RC='${rc_choice}' DRY='${CLEAN_DRY_RUN:-0}'"
    if [ "${CLEAN_DRY_RUN:-0}" = 1 ]; then
      log "[dry-run] would ssh ${cached_user}@${cached_node} $(jump_descr) and run remote cleanup."
      log "  [dry-run] env to forward: ${remote_env}"
    else
      # shellcheck disable=SC2046
      ssh -o StrictHostKeyChecking=accept-new \
          $(ssh_args "$cached_user" "$cached_node") \
          "${cached_user}@${cached_node}" \
          "${remote_env} bash -s" < "$remote_script_file" 2>&1 | sed 's/^/    /' || \
        warn "Remote cleanup returned non-zero; some artifacts may remain."
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
Usage: $(basename "$0") [SUBCOMMAND] [--user NAME] [--node HOST] [--port N]
                          [--no-jump] [--no-mfa] [--probe-nodes]
                          [--force-reinstall]
                          [--dry-run] [--local-only] [-y]
                          [--purge | --purge-backups]

Subcommands:
  client          (default) Laptop-side: install OpenCode if needed, write the
                  OpenCode config, push this script to a chosen ANL compute
                  node, start argo-proxy there inside screen/tmux, then open
                  the SSH tunnel and monitor its health in the foreground.
  server          Runs on the ANL compute node. Auto-invoked by 'client'.
                  Requires ARGO_OPENCODE_USER and ARGO_OPENCODE_PORT in env.
  status          Show local tunnel state and probe the proxy via localhost.
                  Ends with a summary box (ALL GREEN / DEGRADED / FAIL) plus
                  available/configured/orphaned model counts.
                  Set ARGO_OPENCODE_SHOW_MODELS=1 to also dump the full
                  /v1/models response.
  update-models   Refresh ~/.config/opencode/config.json's model list from the
                  live /v1/models endpoint. Preserves everything else in the
                  config; uses the same [k]/[b]/[d]/[m]/[a] confirmation flow
                  as other config writes. Requires jq.
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
  help            Print the long-form guide (paths, troubleshooting,
                  customization).

Options:
  --user NAME          ANL username override (canonical: ARGO_OPENCODE_USER).
                       Honored by 'client' (skips username prompt) and
                       'clean' (overrides cached username for the remote step).
  --node HOST          Compute-node override. 'client' skips the picker and
                       uses HOST directly (fails fast if unreachable). 'clean'
                       targets HOST for the remote cleanup step instead of
                       the cached node. Canonical env: ARGO_OPENCODE_NODE.
                       Warns if HOST is not in the script's ANL_NODES list.
  --port N             Port override for THIS run only. If it disagrees with
                       ~/.config/opencode/config.json, you'll be asked whether
                       to migrate the config or use the config's port instead.
                       Canonical env: ARGO_OPENCODE_PORT.
  --no-jump            Skip the jump host (${ANL_JUMP}); SSH directly
                       to the compute node. Useful when you're on the ANL
                       network or your ~/.ssh/config already inserts a
                       ProxyJump for cels.anl.gov hosts.
                       Canonical env: ARGO_OPENCODE_NO_JUMP=1.
  --no-mfa             Disable Duo/MFA-aware behavior (SSH multiplexing).
                       The script defaults to MFA mode because all CELS access
                       is Duo-protected. Use --no-mfa for hosts that don't
                       use Duo. Canonical env: ARGO_OPENCODE_NO_MFA=1.
  --probe-nodes        Probe each ANL_NODE for reachability before showing
                       the picker. By default the picker shows the static
                       list without probing -- under MFA, probing every node
                       could trigger many Duo prompts. With multiplexing on
                       and the master open, --probe-nodes is cheap.
  --force-reinstall    Wipe the server-side venv (\$HOME/agovenv on the ANL
                       node) and rebuild from scratch. Use after a broken
                       upgrade. Canonical env: ARGO_OPENCODE_FORCE_REINSTALL.

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
  the script reads the port from there. --port and ARGO_OPENCODE_PORT override
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
    opens an SSH local-forward (port ${PROXY_PORT}) and monitors it.
  * server mode (ANL compute node): creates a Python venv at ${VENV_PATH},
    installs argo-proxy if missing, writes ~/.config/argoproxy/config.yaml,
    and starts \`argo-proxy serve\` inside screen (preferred), tmux, or nohup.

You should normally only ever invoke 'client'. The 'server' mode is run for
you over SSH on the chosen compute node.

QUICK START
-----------
  curl -fsSL https://web.cels.anl.gov/~aattia/${script_name} -o ${script_name}
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
  ${HOME}/.config/argo_opencode/user      cached ANL username
  ${HOME}/.config/argo_opencode/node      last-used compute node
  ${HOME}/.config/opencode/config.json    OpenCode config (this script writes it)

ANL compute node (after first run):
  \$HOME/${REMOTE_SELF}                    pushed copy of this script
  \$HOME/${REMOTE_LOG}                     server-mode bootstrap log
  \$HOME/agovenv/                          Python venv with argo-proxy
  \$HOME/.config/argoproxy/config.yaml     argo-proxy config (port / user)
  screen session: '${SCREEN_SESSION}'             where argo-proxy serve runs

Network path while running:
  laptop:${PROXY_PORT}  --SSH-->  ${ANL_JUMP}  --SSH-->  <node>:${PROXY_PORT}  -->  argo-proxy

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
    connection is parked at:  ~/.ssh/sockets/argo-opencode-<user>-<host>-<port>
  * Every subsequent SSH/SCP call to the same node within the same script
    run reuses the master and never prompts.
  * After all clients disconnect, the master lingers for ARGO_OPENCODE_CONTROL_PERSIST
    seconds (default 3600 = 1 hour). Re-running 'status', 'update-models',
    'clean', or 'client' within that window also avoids a fresh Duo prompt.
  * --probe-nodes opens a separate master per node it tests (each is a
    distinct destination). Expect one Duo prompt per reachable node.

If the tunnel drops mid-session and the master is still alive, the health
monitor attempts a silent reconnect through the existing socket. If the
master is also gone, you'll be notified to re-run 'client' (which is when a
new Duo prompt happens).

To turn this off (for non-Duo hosts):  --no-mfa  or  ARGO_OPENCODE_NO_MFA=1
To inspect/close sockets manually:
  ls -l ~/.ssh/sockets/argo-opencode-*
  ssh -O exit -o ControlPath=~/.ssh/sockets/argo-opencode-<user>-<host>-<port> dummy
'clean' also offers to close all our sockets.

PORT POLICY
-----------
The port is resolved at startup from these sources, in order:
  1. --port N                        (CLI flag, this run only)
  2. ARGO_OPENCODE_PORT env var
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
  ARGO_OPENCODE_USER             ANL username (alternative to --user)
  ARGO_OPENCODE_NODE             compute node hostname (alternative to --node)
  ARGO_OPENCODE_PORT             port (alternative to --port)
  ARGO_OPENCODE_NO_JUMP=1        skip the jump host (alternative to --no-jump)
  ARGO_OPENCODE_NO_MFA=1         disable SSH multiplexing (--no-mfa)
  ARGO_OPENCODE_CONTROL_PERSIST=N seconds the SSH master stays after the last
                                 client disconnects (default 3600 = 1 hour;
                                 use 'yes' for indefinite, 'no' to disable).
  ARGO_OPENCODE_SHOW_MODELS=1    'status' dumps the full /v1/models list
  ARGO_OPENCODE_FORCE_REINSTALL=1 server mode wipes \$HOME/agovenv first
  ARGO_BOX_STYLE=ascii|unicode   override the box-drawing heuristic

Legacy (still honored, prints a one-time deprecation warning):
  ANL_USERNAME    -> ARGO_OPENCODE_USER
  PROXY_PORT      -> ARGO_OPENCODE_PORT
  SHOW_MODELS     -> ARGO_OPENCODE_SHOW_MODELS

NOTIFICATIONS WHEN THE TUNNEL BREAKS
------------------------------------
While 'client' is in the foreground, a background loop polls
http://localhost:${PROXY_PORT}/health every ${HEALTH_INTERVAL}s. After ${HEALTH_FAIL_THRESHOLD} consecutive
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
  ARGO_OPENCODE_SHOW_MODELS=1 bash ${script_name} status   # gated dump
  curl -s http://localhost:${PROXY_PORT}/v1/models | jq .   # raw

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
  rm -f ${HOME}/.config/argo_opencode/{user,node}

Update argo-proxy on the node (script reinstalls only on first install):
  ssh -J <user>@${ANL_JUMP} <user>@<node> '~/agovenv/bin/argo-proxy update install'

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

"Port ${PROXY_PORT} is already in use locally"
    Another tunnel (or anything else) is bound to that port. Find and kill:
      lsof -nPi :${PROXY_PORT} -sTCP:LISTEN
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

"Lost connection to <node>:${PROXY_PORT}" notification
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
  This script:       https://web.cels.anl.gov/~aattia/${script_name}
  Maintainer:        Ahmed Attia (attia@anl.gov)

SECURITY NOTE
-------------
The OpenCode config uses your ANL (Argonne) username as a pseudo-API-key
(this is how argo-proxy identifies callers; it is not a secret in the
cryptographic sense). This is the SAME username you use to SSH into ANL
hosts (logins.cels.anl.gov etc.) -- it has nothing to do with your laptop's
local OS account name (\$USER), which may be entirely different. The script
asks for it on first run and caches it at ~/.config/argo_opencode/user.
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
      client|server|status|stop|update-models|clean|help)
        if [ -n "$mode" ] && [ "$mode" != "$1" ]; then
          die "Conflicting subcommands: '${mode}' and '$1'."
        fi
        mode="$1"; shift ;;
      --user)
        [ -n "${2:-}" ] || die "--user expects a value."
        ARGO_OPENCODE_USER="$2"; shift 2 ;;
      --node)
        [ -n "${2:-}" ] || die "--node expects a value."
        ARGO_OPENCODE_NODE="$2"; shift 2 ;;
      --port)
        case "${2:-}" in
          ''|*[!0-9]*) die "--port expects a numeric value (got '${2:-}')." ;;
        esac
        PORT_OVERRIDE_CLI="$2"; shift 2 ;;
      --force-reinstall)
        FORCE_REINSTALL=1; export ARGO_OPENCODE_FORCE_REINSTALL=1; shift ;;
      --no-jump)
        ARGO_OPENCODE_NO_JUMP=1; shift ;;
      --no-mfa)
        ARGO_OPENCODE_NO_MFA=1; shift ;;
      --probe-nodes)
        PROBE_NODES=1; shift ;;
      --dry-run)        CLEAN_DRY_RUN=1; shift ;;
      --local-only)     CLEAN_LOCAL_ONLY=1; shift ;;
      --yes|-y)         CLEAN_ASSUME_YES=1; shift ;;
      --purge)          CLEAN_PURGE=1; CLEAN_PURGE_BACKUPS=1; shift ;;
      --purge-backups)  CLEAN_PURGE_BACKUPS=1; shift ;;
      -h|--help) usage; exit 0 ;;
      --) shift; break ;;
      *) err "Unknown argument: $1"; usage; exit 2 ;;
    esac
  done
  [ -n "$mode" ] || mode="client"

  # Resolve the port once, here, before any mode runs.
  resolve_port

  # Port-mismatch warning for non-client modes. mode_client has its own
  # interactive migrate/keep/abort prompt later; the other modes just need
  # to know they may be talking to the wrong port (e.g. `status --port 1234`
  # when the config says 64742 will silently report FAIL because nothing is
  # listening on 1234). Skip in client (handled there) and in server/help.
  case "$mode" in
    client|server|help) ;;
    *)
      if [ -n "$PORT_FROM_CONFIG" ] && [ "$PROXY_PORT" != "$PORT_FROM_CONFIG" ]; then
        warn "Port override (${PROXY_PORT}, source: ${PORT_SOURCE}) differs from"
        warn "  ~/.config/opencode/config.json baseURL (${PORT_FROM_CONFIG})."
        warn "  This run uses ${PROXY_PORT}. To reconcile, run 'client' (offers migration)."
      fi
      ;;
  esac

  case "$mode" in
    client)        mode_client ;;
    server)        mode_server ;;
    status)        mode_status ;;
    stop)          mode_stop ;;
    update-models) mode_update_models ;;
    clean)         mode_clean ;;
    help)          long_help ;;
  esac
}

main "$@"
