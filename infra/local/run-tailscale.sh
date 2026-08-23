#!/bin/zsh
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && /bin/pwd -P)
source "$SCRIPT_DIR/stage14-runtime-common.sh"

SOCKET="$(stage14_tailscale_socket)"
STATE_FILE="$(stage14_tailscale_state)"
PIDFILE="$(stage14_tailscale_pidfile)"
DAEMON="${STAGE14_TAILSCALE_DAEMON_BIN:-/opt/homebrew/opt/tailscale/bin/tailscaled}"

stage14_install_secure_dir "$(stage14_tailscale_dir)" 700
touch "$STATE_FILE"
chmod 600 "$STATE_FILE"
print -r -- "$$" >"$PIDFILE"
chmod 600 "$PIDFILE"

exec "$DAEMON" --tun=userspace-networking --socket="$SOCKET" --state="$STATE_FILE"
