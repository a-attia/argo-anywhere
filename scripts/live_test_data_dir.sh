#!/usr/bin/env bash
# shellcheck disable=SC2034,SC2154  # P_* globals are assigned via eval in probe()
# live_test_data_dir.sh -- live check of the per-node argo-proxy data dir
# (notes/impl_proxy_data_dir.md, section 5). Maintainer tool; contacts ANL.
#
# PRECONDITION: a channel is already up for every node under test, opened
# with the engine under test (e.g. `./.venv/bin/argo-anywhere --node X
# --port P connect`). This script never opens a channel or an SSH
# connection of its own: every remote command rides the existing
# multiplex master (ControlMaster=no + BatchMode=yes), and `ssh -O check`
# gates it, so no Duo prompt or new auth attempt can come from here.
#
# Usage:
#   scripts/live_test_data_dir.sh [options] NODE:PORT [NODE:PORT]
#
#   --rotate        also test rotation on the FIRST node: restarts its
#                   argo-proxy twice (interrupts clients on that port)
#   --requests N    chat requests per port (default 3)
#   --wait S        seconds to wait for metric flushes (default 75; the
#                   flush interval is 30s)
#   --model M       model for the requests (default argo:gpt-4o)
#   --user U        Argo username (default: ~/.config/argo_anywhere/user)
#
# Exit: 0 all checks pass, 1 any FAIL, 2 precondition/usage error.

set -uo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
ENGINE="${REPO}/src/argo_anywhere/engine/argo-anywhere.sh"
MUX="${HOME}/.ssh/sockets/argo-anywhere-%r-%h-%p"   # = engine's ControlPath
SSH_OPTS=(-o ControlMaster=no -o "ControlPath=${MUX}" -o BatchMode=yes)
SESSION="argovproxy"                                 # = engine SCREEN_SESSION

ROTATE=0 REQUESTS=3 WAIT=75 MODEL="argo:gpt-4o" USER_ARGO=""
TARGETS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --rotate)   ROTATE=1; shift ;;
    --requests) REQUESTS="$2"; shift 2 ;;
    --wait)     WAIT="$2"; shift 2 ;;
    --model)    MODEL="$2"; shift 2 ;;
    --user)     USER_ARGO="$2"; shift 2 ;;
    -h|--help)  sed -n '2,24p' "$0"; exit 0 ;;
    *:*)        TARGETS+=("$1"); shift ;;
    *)          echo "unknown argument: $1 (see --help)" >&2; exit 2 ;;
  esac
done
[ ${#TARGETS[@]} -ge 1 ] || { echo "need at least one NODE:PORT (see --help)" >&2; exit 2; }
if [ -z "$USER_ARGO" ] && [ -r "${HOME}/.config/argo_anywhere/user" ]; then
  USER_ARGO="$(head -n1 "${HOME}/.config/argo_anywhere/user")"
fi
[ -n "$USER_ARGO" ] || { echo "no Argo username; pass --user" >&2; exit 2; }

FAILS=0
pass() { printf '  \033[32mPASS\033[0m %s\n' "$*"; }
fail() { printf '  \033[31mFAIL\033[0m %s\n' "$*"; FAILS=$((FAILS+1)); }
note() { printf '  \033[33mNOTE\033[0m %s\n' "$*"; }
hdr()  { printf '\n== %s\n' "$*"; }

rsh() { local node="$1"; shift; ssh "${SSH_OPTS[@]}" "$node" "$@"; }

sha_of() { shasum -a 256 2>/dev/null | awk '{print $1}'; }

# Remote probe: run ON the node, so each node reads only its OWN database
# (opening another host's WAL database over NFS is the very thing under test).
# Prints KEY=VALUE lines.
read -r -d '' REMOTE_PROBE <<'EOS'
set -u
port="$1"
host="$(hostname -s 2>/dev/null || hostname)"; host="${host%%.*}"
host="$(printf '%s' "$host" | tr -c 'A-Za-z0-9._-' '_')"
base="$HOME/.config/argoproxy"; cur="$base/data-$host"; prev="$cur.prev"
echo "host=$host"
echo "cur=$cur"
pid="$( { lsof -t -nP -iTCP:"$port" -sTCP:LISTEN 2>/dev/null | head -n1; } || true )"
echo "pid=$pid"
if [ -n "$pid" ] && [ -r "/proc/$pid/environ" ]; then
  echo "env_data_dir=$( { tr '\0' '\n' < "/proc/$pid/environ" | sed -n 's/^DATA_DIR=//p' | head -n1; } || true )"
  echo "env_succ_max=$( { tr '\0' '\n' < "/proc/$pid/environ" | sed -n 's/^REQUEST_LOG_SUCCESS_MAX=//p' | head -n1; } || true )"
  echo "open_db=$( { ls -l "/proc/$pid/fd" 2>/dev/null | grep -o '/[^ ]*gateway\.db$' | head -n1; } || true )"
fi
echo "dirs=$(cd "$base" 2>/dev/null && ls -d data* 2>/dev/null | tr '\n' ' ')"
for which in cur prev; do
  case "$which" in cur) db="$cur/gateway.db" ;; *) db="$prev/gateway.db" ;; esac
  if [ -f "$db" ]; then
    "$HOME/argovenv/bin/python" - "$db" "$which" <<'PY' 2>/dev/null || echo "${which}_error=python failed"
import sqlite3, sys
db, which = sys.argv[1], sys.argv[2]
try:
    c = sqlite3.connect(db, timeout=5)
    print(f"{which}_integrity=" + c.execute("pragma integrity_check").fetchone()[0])
    print(f"{which}_rows=" + str(c.execute("select count(*) from request_log").fetchone()[0]))
except Exception as e:
    print(f"{which}_error={e}")
PY
  else
    echo "${which}_rows=none"
  fi
done
n="$(grep -c 'flush metrics\|database is locked\|malformed' "$HOME/argoproxy-$host.out" 2>/dev/null || true)"
echo "log_errors=${n:-0}"
[ -s "$HOME/argoproxy-$host.out" ] && echo "log_exists=1" || echo "log_exists=0"
echo "remote_sha=$( { sha256sum "$HOME/.argo-anywhere.sh" 2>/dev/null | awk '{print $1}'; } || true )"
EOS

probe() {  # probe NODE PORT -> sets P_<key> globals
  local out line k v
  out="$(rsh "$1" bash -s -- "$2" <<<"$REMOTE_PROBE" 2>/dev/null)" || true
  for k in host cur pid env_data_dir env_succ_max open_db dirs cur_integrity cur_rows \
           cur_error prev_integrity prev_rows prev_error log_errors log_exists remote_sha; do
    eval "P_$k=''"
  done
  while IFS= read -r line; do
    k="${line%%=*}"; v="${line#*=}"
    case "$k" in *[!a-z_]*|'') continue ;; esac
    eval "P_$k=\$v"
  done <<<"$out"
}

send_requests() {  # send_requests PORT N -> echoes count of HTTP 200
  local port="$1" n="$2" i ok=0 code
  for i in $(seq 1 "$n"); do
    code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 60 \
      "http://localhost:${port}/v1/chat/completions" \
      -H "Authorization: Bearer ${USER_ARGO}" -H 'Content-Type: application/json' \
      -d "{\"model\":\"${MODEL}\",\"max_tokens\":5,\"messages\":[{\"role\":\"user\",\"content\":\"say ok\"}]}")"
    [ "$code" = 200 ] && ok=$((ok+1))
  done
  echo "$ok"
}

wait_health() {  # wait_health PORT SECS
  local i
  for i in $(seq 1 "$2"); do
    curl -fsS --max-time 2 "http://localhost:$1/health" >/dev/null 2>&1 && return 0
    sleep 1
  done
  return 1
}

check_node() {  # check_node NODE PORT MIN_ROWS
  local node="$1" port="$2" min="$3" d bad=""
  probe "$node" "$port"
  if [ -z "$P_host" ]; then fail "$node: remote probe returned nothing"; return; fi
  echo "  ($node = $P_host, argo-proxy pid ${P_pid:-?})"
  [ "$P_env_data_dir" = "$P_cur" ] \
    && pass "process env DATA_DIR = $P_cur" \
    || fail "process env DATA_DIR = '${P_env_data_dir}' (want $P_cur)"
  [ "$P_env_succ_max" = 1000 ] \
    && pass "process env REQUEST_LOG_SUCCESS_MAX = 1000" \
    || fail "process env REQUEST_LOG_SUCCESS_MAX = '${P_env_succ_max}' (want 1000)"
  if [ -n "$P_open_db" ]; then
    [ "$P_open_db" = "$P_cur/gateway.db" ] \
      && pass "proxy has $P_cur/gateway.db open" \
      || fail "proxy has '${P_open_db}' open (want $P_cur/gateway.db)"
  else
    note "could not read the proxy's open files (skipped)"
  fi
  [ "$P_cur_integrity" = ok ] \
    && pass "integrity_check = ok" \
    || fail "integrity_check = '${P_cur_integrity}' ${P_cur_error}"
  if [ -n "$P_cur_rows" ] && [ "$P_cur_rows" != none ] && [ "$P_cur_rows" -ge "$min" ] 2>/dev/null; then
    pass "request_log has $P_cur_rows rows (>= $min sent)"
  else
    fail "request_log rows = '${P_cur_rows}' (want >= $min)"
  fi
  for d in $P_dirs; do
    case "$d" in
      "data-$P_host"|"data-$P_host.prev") ;;
      data) note "legacy shared 'data' dir exists (an older engine ran?)" ;;
      data-*) ;;   # another node's dirs
      *) bad="$bad $d" ;;
    esac
  done
  [ -z "$bad" ] && pass "no stray data dirs for this node" || fail "unexpected dirs:$bad"
  [ "$P_log_exists" = 1 ] \
    && pass "per-node log ~/argoproxy-$P_host.out exists and is non-empty" \
    || fail "per-node log ~/argoproxy-$P_host.out missing or empty"
  [ "${P_log_errors:-0}" = 0 ] \
    && pass "no lock/malformed/flush errors in ~/argoproxy-$P_host.out" \
    || fail "${P_log_errors} lock/malformed/flush error line(s) in ~/argoproxy-$P_host.out"
}

# --------------------------------------------------------------------------
hdr "Preconditions"
LOCAL_SHA="$(sha_of < "$ENGINE")"
HOSTS_SEEN=""
for t in "${TARGETS[@]}"; do
  node="${t%%:*}" port="${t##*:}"
  if ! ssh "${SSH_OPTS[@]}" -O check "$node" >/dev/null 2>&1; then
    echo "  no live SSH master for '$node'. Run first:" >&2
    echo "    ./.venv/bin/argo-anywhere --node $node --port $port connect" >&2
    exit 2
  fi
  wait_health "$port" 3 || { echo "  nothing healthy on localhost:$port" >&2; exit 2; }
  probe "$node" "$port"
  if [ "$P_remote_sha" = "$LOCAL_SHA" ]; then
    pass "$node: remote engine matches this checkout"
  else
    fail "$node: remote ~/.argo-anywhere.sh differs from this checkout (proxy started by another version?)"
  fi
  HOSTS_SEEN="$HOSTS_SEEN $P_host"
done

hdr "Traffic: $REQUESTS request(s) per port ($MODEL)"
SENT_OK=()
for t in "${TARGETS[@]}"; do
  ok="$(send_requests "${t##*:}" "$REQUESTS")"
  SENT_OK+=("$ok")
  [ "$ok" -eq "$REQUESTS" ] && pass "${t}: $ok/$REQUESTS returned 200" \
                            || fail "${t}: only $ok/$REQUESTS returned 200"
done

hdr "Waiting ${WAIT}s for metric flushes"
sleep "$WAIT"

i=0
for t in "${TARGETS[@]}"; do
  hdr "Node ${t%%:*} (port ${t##*:})"
  check_node "${t%%:*}" "${t##*:}" "${SENT_OK[$i]}"
  i=$((i+1))
done

hdr "Cross-node"
if [ ${#TARGETS[@]} -ge 2 ]; then
  # shellcheck disable=SC2086  # deliberate word-split of two hostnames
  set -- $HOSTS_SEEN
  [ "$1" != "$2" ] && pass "nodes resolve to different dirs (data-$1, data-$2)" \
                   || fail "both targets are the same host ($1)"
fi

if [ "$ROTATE" = 1 ]; then
  t="${TARGETS[0]}"; node="${t%%:*}"; port="${t##*:}"
  RESTART_LOG="$(mktemp "${TMPDIR:-/tmp}/live_test_data_dir.XXXXXX")"
  restart() {
    rsh "$node" "screen -S $SESSION -X quit >/dev/null 2>&1; tmux kill-session -t $SESSION >/dev/null 2>&1; sleep 3; \
      ARGO_ANYWHERE_USER='$USER_ARGO' ARGO_ANYWHERE_PORT='$port' bash ~/.argo-anywhere.sh server -y" \
      >>"$RESTART_LOG" 2>&1 \
      || { fail "server restart on $node failed (see $RESTART_LOG)"; return 1; }
    wait_health "$port" 30 || { fail "no /health on :$port after restart"; return 1; }
  }
  hdr "Rotation on $node (restarting its argo-proxy twice)"
  probe "$node" "$port"; s1_rows="$P_cur_rows"
  if restart; then
    probe "$node" "$port"
    [ "$P_prev_rows" != none ] && [ "$P_prev_rows" -ge "$s1_rows" ] 2>/dev/null \
      && pass "restart 1: previous session kept in .prev ($P_prev_rows rows)" \
      || fail "restart 1: .prev rows = '${P_prev_rows}' (want >= $s1_rows)"
    [ "$P_env_data_dir" = "$P_cur" ] && pass "restart 1: new proxy uses $P_cur" \
                                     || fail "restart 1: new proxy DATA_DIR = '${P_env_data_dir}'"
    sleep 35; probe "$node" "$port"; s2_rows="$P_cur_rows"
    if restart; then
      probe "$node" "$port"
      [ "$P_prev_rows" = "$s2_rows" ] || [ "$P_prev_rows" -lt "$s1_rows" ] \
        && pass "restart 2: oldest generation deleted (.prev now holds session 2: $P_prev_rows rows)" \
        || fail "restart 2: .prev rows = $P_prev_rows; session 1 ($s1_rows rows) not discarded?"
      n=0; for d in $P_dirs; do case "$d" in "data-$P_host"*) n=$((n+1)) ;; esac; done
      [ "$n" = 2 ] && pass "exactly two generations on disk" || fail "$n dirs for $P_host: $P_dirs"
    fi
  fi
fi

hdr "Result"
if [ "$FAILS" = 0 ]; then echo "  ALL CHECKS PASSED"; exit 0; fi
echo "  $FAILS check(s) FAILED"; exit 1
