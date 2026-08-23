#!/bin/zsh
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && /bin/pwd -P)
source "$SCRIPT_DIR/stage14-runtime-common.sh"

if [[ "${1:-}" = "--self-check" ]]; then
  command -v launchctl >/dev/null
  test -x /usr/bin/curl
  test -x /usr/sbin/lsof
  stage14_self_check_ok
fi

labels=(
  com.paper-grading.api
  com.paper-grading.grading
  com.paper-grading.export
  com.paper-grading.keep-awake
  com.paper-grading.tailscale
  com.paper-grading.watchdog
)

stage14_require_regular_file "$(stage14_env_dir)/production.env"
stage14_install_secure_dir "$(stage14_state_dir)" 700
stage14_load_env_file "$(stage14_env_dir)/production.env"
current_root=$(stage14_resolve_symlink_target "$(stage14_current_root)")

for label in "${labels[@]}"; do
  launchctl print "gui/$UID/$label" >/dev/null
done

test "$(/opt/homebrew/bin/redis-cli -u "$REDIS_URL" ping)" = "PONG"
curl --fail --silent --show-error http://127.0.0.1:8000/health/live >/dev/null
curl --fail --silent --show-error http://127.0.0.1:8000/health/ready >/dev/null
status_json="$(${STAGE14_TAILSCALE_CLIENT_BIN:-/opt/homebrew/bin/tailscale} --socket="$(stage14_tailscale_socket)" funnel status --json)"
print -rn -- "$status_json" | /usr/bin/grep -Fq '127.0.0.1:8000'

listen_addresses=$(
  /usr/sbin/lsof -nP -iTCP:8000 -sTCP:LISTEN -Fn |
    /usr/bin/grep '^n' |
    /usr/bin/cut -c2-
)
test "$listen_addresses" = "127.0.0.1:8000"

worker_status="$("$current_root/.venv/bin/celery" -b "$REDIS_URL" inspect ping --json --timeout 10)"
for worker in grading maintenance exports; do
  print -rn -- "$worker_status" | /usr/bin/grep -Fq "${worker}@"
done

for queue in paper_grading.grading paper_grading.maintenance paper_grading.exports; do
  /opt/homebrew/bin/redis-cli -u "$REDIS_URL" LLEN "$queue" >/dev/null
done

print "stage14_local_runtime_verified=true"
