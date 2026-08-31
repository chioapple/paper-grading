#!/bin/zsh
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && /bin/pwd -P)
source "$SCRIPT_DIR/stage14-runtime-common.sh"

if [[ "${1:-}" = "--self-check" ]]; then
  test -x /usr/bin/curl
  command -v mktemp >/dev/null
  typeset -f stage14_env_dir >/dev/null
  stage14_self_check_ok
fi

stage14_load_env_file "$(stage14_env_dir)/production.env"
test "${PROVIDER_CALLS_ENABLED:-}" = "false"
current_root=$(stage14_resolve_symlink_target "$(stage14_current_root)")

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

test "$(/opt/homebrew/bin/redis-cli -u "$REDIS_URL" ping)" = "PONG"
curl --fail --silent --show-error http://127.0.0.1:8000/health/ready >/dev/null

worker_status="$("$current_root/.venv/bin/celery" -b "$REDIS_URL" inspect ping --json --timeout 10)"
for worker in grading maintenance exports; do
  print -rn -- "$worker_status" | /usr/bin/grep -Fq "${worker}@"
done

curl_config="$(mktemp)"
trap '/bin/rm -f "$curl_config"' EXIT
chmod 600 "$curl_config"
{
  print 'silent'
  print 'show-error'
  print 'fail'
  print "url = \"${UPTIMEROBOT_HEARTBEAT_URL}\""
} >"$curl_config"
curl --config "$curl_config" >/dev/null
