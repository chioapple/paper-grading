#!/bin/zsh
set -euo pipefail

PROJECT_ROOT=$(cd "$(dirname "$0")/../.." && pwd)
set -a
source "$PROJECT_ROOT/.env.stage14-production"
set +a

test -n "${UPTIMEROBOT_HEARTBEAT_URL:?missing UPTIMEROBOT_HEARTBEAT_URL}"
case "$UPTIMEROBOT_HEARTBEAT_URL" in
  https://heartbeat.uptimerobot.com/*) ;;
  *) exit 2 ;;
esac

unset DATABASE_URL
unset EXPORT_DATABASE_URL
unset SUPABASE_URL
unset SUPABASE_PUBLISHABLE_KEY
unset SUPABASE_SECRET_KEY
unset SUPABASE_STORAGE_BUCKET
unset PROVIDER_MASTER_KEY
unset AUTH_INVITE_REDIRECT_URL
unset FRONTEND_ORIGIN
unset VITE_API_BASE_URL
unset VITE_SUPABASE_URL
unset VITE_SUPABASE_PUBLISHABLE_KEY

test "$(/opt/homebrew/bin/redis-cli ping)" = "PONG"
curl --fail --silent --show-error http://127.0.0.1:8000/health/ready >/dev/null

worker_status=$(
  "$PROJECT_ROOT/.venv/bin/celery" -b "$REDIS_URL" inspect ping --timeout 10
)
for worker in grading maintenance exports; do
  print "$worker_status" | rg -q "$worker@"
done

curl --fail --silent --show-error "$UPTIMEROBOT_HEARTBEAT_URL" >/dev/null
