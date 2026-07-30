#!/bin/zsh
set -euo pipefail

PROJECT_ROOT=$(cd "$(dirname "$0")/../.." && pwd)
labels=(
  com.paper-grading.api
  com.paper-grading.grading
  com.paper-grading.export
  com.paper-grading.keep-awake
  com.paper-grading.tailscale
  com.paper-grading.watchdog
)

for label in "${labels[@]}"; do
  launchctl print "gui/$UID/$label" >/dev/null
done

test "$(/opt/homebrew/bin/redis-cli ping)" = "PONG"
curl --fail --silent --show-error http://127.0.0.1:8000/health/live >/dev/null
curl --fail --silent --show-error http://127.0.0.1:8000/health/ready >/dev/null
/opt/homebrew/bin/tailscale \
  --socket="$PROJECT_ROOT/tmp/tailscale/tailscaled.sock" \
  funnel status >/dev/null

listen_addresses=$(
  lsof -nP -iTCP:8000 -sTCP:LISTEN -Fn |
    rg '^n' |
    cut -c2-
)
test "$listen_addresses" = "127.0.0.1:8000"

for queue in \
  paper_grading.grading \
  paper_grading.maintenance \
  paper_grading.exports; do
  /opt/homebrew/bin/redis-cli LLEN "$queue"
done

print "stage14_local_runtime_verified=true"
