#!/bin/zsh
set -euo pipefail

PROJECT_ROOT=$(cd "$(dirname "$0")/../.." && pwd)
COMMON_ENV="$PROJECT_ROOT/.env.stage14-production"
GRADING_ENV="$PROJECT_ROOT/.env.stage14-grading-worker"

load_environment() {
  local file_path=$1
  test -f "$file_path"
  set -a
  source "$file_path"
  set +a
}

test -x "$PROJECT_ROOT/.venv/bin/python"
load_environment "$COMMON_ENV"

case "${1:-}" in
  api)
    unset EXPORT_DATABASE_URL
    unset VITE_API_BASE_URL
    unset VITE_SUPABASE_URL
    unset VITE_SUPABASE_PUBLISHABLE_KEY
    unset UPTIMEROBOT_HEARTBEAT_URL
    cd "$PROJECT_ROOT/backend"
    exec "$PROJECT_ROOT/.venv/bin/uvicorn" \
      app.main:app \
      --host 127.0.0.1 \
      --port 8000
    ;;
  grading)
    load_environment "$GRADING_ENV"
    unset EXPORT_DATABASE_URL
    unset SUPABASE_PUBLISHABLE_KEY
    unset AUTH_INVITE_REDIRECT_URL
    unset FRONTEND_ORIGIN
    unset VITE_API_BASE_URL
    unset VITE_SUPABASE_URL
    unset VITE_SUPABASE_PUBLISHABLE_KEY
    unset UPTIMEROBOT_HEARTBEAT_URL
    cd "$PROJECT_ROOT/backend"
    exec "$PROJECT_ROOT/.venv/bin/python" -m app.workers.supervisor
    ;;
  export)
    unset PROVIDER_MASTER_KEY
    unset DATABASE_URL
    unset SUPABASE_PUBLISHABLE_KEY
    unset AUTH_INVITE_REDIRECT_URL
    unset FRONTEND_ORIGIN
    unset VITE_API_BASE_URL
    unset VITE_SUPABASE_URL
    unset VITE_SUPABASE_PUBLISHABLE_KEY
    unset UPTIMEROBOT_HEARTBEAT_URL
    cd "$PROJECT_ROOT/backend"
    exec "$PROJECT_ROOT/.venv/bin/celery" \
      -A app.export.celery_app:celery_app \
      worker \
      --loglevel=INFO \
      --concurrency=1 \
      --queues=paper_grading.exports \
      --hostname=exports@%h
    ;;
  *)
    print -u2 "用法：run-component.sh api|grading|export"
    exit 2
    ;;
esac
