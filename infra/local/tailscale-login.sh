#!/bin/zsh
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && /bin/pwd -P)
source "$SCRIPT_DIR/stage14-runtime-common.sh"

if [[ "${1:-}" = "--self-check" ]]; then
  test -x "${STAGE14_TAILSCALE_CLIENT_BIN:-/opt/homebrew/bin/tailscale}"
  test -x "${STAGE14_TAILSCALE_DAEMON_BIN:-/opt/homebrew/opt/tailscale/bin/tailscaled}"
  typeset -f stage14_prepare_tailscale_state >/dev/null
  stage14_self_check_ok
fi

action="${1:-}"
socket="$(stage14_tailscale_socket)"
pidfile="$(stage14_tailscale_pidfile)"
state_file="$(stage14_tailscale_state)"
client="${STAGE14_TAILSCALE_CLIENT_BIN:-/opt/homebrew/bin/tailscale}"
daemon="${STAGE14_TAILSCALE_DAEMON_BIN:-/opt/homebrew/opt/tailscale/bin/tailscaled}"

stage14_install_secure_dir "$(stage14_tailscale_dir)" 700

cleanup_stale() {
  if [[ -f "$pidfile" ]]; then
    pid=$(tr -d '[:space:]' <"$pidfile")
    if [[ -n "$pid" ]] && ! kill -0 "$pid" 2>/dev/null; then
      /bin/rm -f "$pidfile"
    fi
  fi
  if [[ -S "$socket" && ! -f "$pidfile" ]]; then
    /bin/rm -f "$socket"
  fi
}

start_daemon() {
  cleanup_stale
  stage14_prepare_tailscale_state
  if [[ -f "$pidfile" ]]; then
    pid=$(tr -d '[:space:]' <"$pidfile")
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null && [[ -S "$socket" ]]; then
      return 0
    fi
  fi
  /usr/bin/nohup "$daemon" --tun=userspace-networking --socket="$socket" \
    --state="$state_file" >/dev/null 2>&1 &
  daemon_pid=$!
  print -r -- "$daemon_pid" >"$pidfile"
  chmod 600 "$pidfile"
  for _ in {1..30}; do
    [[ -S "$socket" ]] && return 0
    sleep 1
  done
  exit 1
}

case "$action" in
  start)
    start_daemon
    test -S "$socket"
    ;;
  login)
    start_daemon
    "$client" --socket="$socket" up
    ;;
  status)
    cleanup_stale
    if [[ "${2:-}" = "--expect-running" ]]; then
      status_text="$("$client" --socket="$socket" status --json 2>/dev/null || true)"
      STATUS_JSON="$status_text" /usr/bin/python3 - <<'PY'
import json
import os

payload = json.loads(os.environ["STATUS_JSON"])
if payload.get("BackendState") != "Running":
    raise SystemExit(1)
PY
    elif [[ "${2:-}" = "--expect-stopped" ]]; then
      test ! -S "$socket"
      test ! -f "$pidfile"
    else
      "$client" --socket="$socket" status
    fi
    ;;
  stop)
    cleanup_stale
    if [[ -f "$pidfile" ]]; then
      pid=$(tr -d '[:space:]' <"$pidfile")
      if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
        kill "$pid"
        for _ in {1..30}; do
          if ! kill -0 "$pid" 2>/dev/null; then
            break
          fi
          sleep 1
        done
      fi
      /bin/rm -f "$pidfile"
    fi
    if [[ -S "$socket" ]]; then
      /bin/rm -f "$socket"
    fi
    ;;
  *)
    print -u2 '用法：tailscale-login.sh start|login|status [--expect-running|--expect-stopped]|stop'
    exit 2
    ;;
esac
