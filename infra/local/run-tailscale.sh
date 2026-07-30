#!/bin/zsh
set -euo pipefail

PROJECT_ROOT=$(cd "$(dirname "$0")/../.." && pwd)
STATE_DIR="$PROJECT_ROOT/tmp/tailscale"
SOCKET="$STATE_DIR/tailscaled.sock"
STATE_FILE="$STATE_DIR/tailscaled.state"
DAEMON=/opt/homebrew/opt/tailscale/bin/tailscaled
CLIENT=/opt/homebrew/bin/tailscale

mkdir -p "$STATE_DIR"
chmod 700 "$STATE_DIR"
test -x "$DAEMON"
test -x "$CLIENT"
test -f "$STATE_FILE"

"$DAEMON" \
  --tun=userspace-networking \
  --socket="$SOCKET" \
  --state="$STATE_FILE" &
daemon_pid=$!

shutdown() {
  kill "$daemon_pid" 2>/dev/null || true
  wait "$daemon_pid" 2>/dev/null || true
}
trap shutdown EXIT INT TERM

for _ in {1..30}; do
  test -S "$SOCKET" && break
  sleep 1
done
test -S "$SOCKET"

"$CLIENT" --socket="$SOCKET" status >/dev/null
"$CLIENT" --socket="$SOCKET" funnel --bg 8000 >/dev/null
wait "$daemon_pid"
