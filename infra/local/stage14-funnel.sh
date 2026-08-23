#!/bin/zsh
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && /bin/pwd -P)
source "$SCRIPT_DIR/stage14-runtime-common.sh"

if [[ "${1:-}" = "--self-check" ]]; then
  test -x "${STAGE14_TAILSCALE_CLIENT_BIN:-/opt/homebrew/bin/tailscale}"
  command -v /usr/bin/python3 >/dev/null
  stage14_self_check_ok
fi

action="${1:-}"
client="${STAGE14_TAILSCALE_CLIENT_BIN:-/opt/homebrew/bin/tailscale}"
socket="$(stage14_tailscale_socket)"
snapshot="$(stage14_tailscale_dir)/serve-config.json"

stage14_install_secure_dir "$(stage14_tailscale_dir)" 700

case "$action" in
  enable)
    "$client" --socket="$socket" serve get-config "$snapshot" --all >/dev/null
    chmod 600 "$snapshot"
    "$client" --socket="$socket" funnel --bg http://127.0.0.1:8000 >/dev/null
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
    "$client" --socket="$socket" serve set-config "$snapshot" --all >/dev/null
    ;;
  *)
    print -u2 '用法：stage14-funnel.sh enable|status|restore'
    exit 2
    ;;
esac
