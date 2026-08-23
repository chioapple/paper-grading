#!/bin/zsh
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && /bin/pwd -P)
source "$SCRIPT_DIR/stage14-runtime-common.sh"

if [[ "${1:-}" = "--self-check" ]]; then
  typeset -f stage14_env_dir >/dev/null
  typeset -f stage14_state_dir >/dev/null
  stage14_self_check_ok
fi

CURRENT_ROOT=$(stage14_resolve_symlink_target "$(stage14_current_root)")
COMMON_ENV="$(stage14_env_dir)/production.env"
GRADING_ENV="$(stage14_env_dir)/grading-worker.env"
export PYTHONDONTWRITEBYTECODE=1

# shared/env/production.env 与 shared/env/grading-worker.env 是唯一环境来源。

load_environment() {
  local file_path=$1
  stage14_require_regular_file "$file_path"
  set -a
  source "$file_path"
  set +a
}

test -x "$CURRENT_ROOT/.venv/bin/python"
load_environment "$COMMON_ENV"

case "${1:-}" in
  api)
    unset EXPORT_DATABASE_URL
    unset VITE_API_BASE_URL
    unset VITE_SUPABASE_URL
    unset VITE_SUPABASE_PUBLISHABLE_KEY
    unset UPTIMEROBOT_HEARTBEAT_URL
    cd "$CURRENT_ROOT/backend"
    exec "$CURRENT_ROOT/.venv/bin/uvicorn" app.main:app --host 127.0.0.1 --port 8000
    ;;
  grading)
    load_environment "$GRADING_ENV"
    export CELERYBEAT_SCHEDULE_FILENAME="$(stage14_state_dir)/celerybeat-schedule"
    unset EXPORT_DATABASE_URL
    unset SUPABASE_PUBLISHABLE_KEY
    unset AUTH_INVITE_REDIRECT_URL
    unset FRONTEND_ORIGIN
    unset VITE_API_BASE_URL
    unset VITE_SUPABASE_URL
    unset VITE_SUPABASE_PUBLISHABLE_KEY
    unset UPTIMEROBOT_HEARTBEAT_URL
    cd "$CURRENT_ROOT/backend"
    exec "$CURRENT_ROOT/.venv/bin/python" -m app.workers.supervisor
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
    cd "$CURRENT_ROOT/backend"
    exec "$CURRENT_ROOT/.venv/bin/celery" \
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
