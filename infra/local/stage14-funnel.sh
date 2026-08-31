#!/bin/zsh
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && /bin/pwd -P)
source "$SCRIPT_DIR/stage14-runtime-common.sh"

if [[ "${1:-}" = "--self-check" ]]; then
  self_check_client="${STAGE14_TAILSCALE_CLIENT_BIN:-/opt/homebrew/bin/tailscale}"
  test -x "$self_check_client"
  command -v /usr/bin/python3 >/dev/null
  "$self_check_client" serve get-config --help 2>&1 | /usr/bin/grep -Fq -- '--all'
  "$self_check_client" serve set-config --help 2>&1 | /usr/bin/grep -Fq -- '--all'
  "$self_check_client" funnel --help 2>&1 | /usr/bin/grep -Fq -- '--yes'
  stage14_self_check_ok
fi

action="${1:-}"
client="${STAGE14_TAILSCALE_CLIENT_BIN:-/opt/homebrew/bin/tailscale}"
socket="$(stage14_tailscale_socket)"
snapshot="$(stage14_tailscale_dir)/serve-config.json"
snapshot_temp="$snapshot.$$"

stage14_install_secure_dir "$(stage14_tailscale_dir)" 700
umask 077

cleanup_snapshot_temp() {
  if [[ -f "$snapshot_temp" && ! -L "$snapshot_temp" ]]; then
    /bin/rm -f -- "$snapshot_temp"
  fi
}

validate_snapshot() {
  local config_path=$1
  STAGE14_SERVE_CONFIG="$config_path" /usr/bin/python3 - <<'PY'
import json
import os
from pathlib import Path

payload = json.loads(Path(os.environ["STAGE14_SERVE_CONFIG"]).read_text(encoding="utf-8"))
if not isinstance(payload, dict) or not isinstance(payload.get("version"), str):
    raise SystemExit("stage14_funnel_snapshot_invalid")
PY
}

case "$action" in
  enable)
    if [[ -e "$snapshot" || -L "$snapshot" ]]; then
      stage14_require_regular_file "$snapshot"
      test "$(/usr/bin/stat -f '%u' "$snapshot")" = "$(/usr/bin/id -u)"
      test -s "$snapshot"
      validate_snapshot "$snapshot"
      chmod 600 "$snapshot"
    else
      test ! -e "$snapshot_temp"
      trap cleanup_snapshot_temp EXIT INT TERM
      "$client" --socket="$socket" serve get-config --all >"$snapshot_temp"
      test -s "$snapshot_temp"
      validate_snapshot "$snapshot_temp"
      chmod 600 "$snapshot_temp"
      /bin/mv "$snapshot_temp" "$snapshot"
      trap - EXIT INT TERM
    fi
    "$client" --socket="$socket" funnel --bg --yes http://127.0.0.1:8000 >/dev/null
    ;;
  status)
    status_json="$("$client" --socket="$socket" funnel status --json)"
    STATUS_JSON="$status_json" /usr/bin/python3 - <<'PY'
import json
import os

payload = json.loads(os.environ["STATUS_JSON"])
text = json.dumps(payload, sort_keys=True, separators=(",", ":"))
if text.count("127.0.0.1:8000") != 1:
    raise SystemExit(1)
PY
    ;;
  restore)
    stage14_require_regular_file "$snapshot"
    test "$(/usr/bin/stat -f '%u' "$snapshot")" = "$(/usr/bin/id -u)"
    validate_snapshot "$snapshot"
    "$client" --socket="$socket" serve set-config --all "$snapshot" >/dev/null
    /bin/rm -f -- "$snapshot"
    ;;
  *)
    print -u2 '用法：stage14-funnel.sh enable|status|restore'
    exit 2
    ;;
esac
