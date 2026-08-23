#!/bin/zsh
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && /bin/pwd -P)
source "$SCRIPT_DIR/stage14-runtime-common.sh"

if [[ "${1:-}" = "--self-check" ]]; then
  typeset -f stage14_require_regular_file >/dev/null
  typeset -f stage14_install_secure_dir >/dev/null
  stage14_self_check_ok
fi

usage() {
  print -u2 "用法：update-production-env.sh --create|--replace"
}

if (( $# != 1 )); then
  usage
  exit 2
fi

mode=$1
case "$mode" in
  --create|--replace) ;;
  *)
    usage
    exit 2
    ;;
esac

runtime_root=$(stage14_runtime_root)
shared_root=$(stage14_shared_root)
env_dir=$(stage14_env_dir)
current_link=$(stage14_current_root)
staging_dir="$shared_root/.env-stage.$$"
backup_dir="$shared_root/.env-backup.$$"

stage14_install_secure_dir "$runtime_root" 700
stage14_install_secure_dir "$shared_root" 700
if [[ -e "$env_dir" ]]; then
  test -d "$env_dir"
  test ! -L "$env_dir"
fi
test -L "$current_link"
current_release=$(stage14_resolve_symlink_target "$current_link")
current_sha=$(basename "$current_release")
stage14_assert_full_sha "$current_sha"

if [[ "$mode" = "--create" && -e "$env_dir/production.env" ]]; then
  print -u2 "shared/env 已存在，请改用 --replace"
  exit 1
fi

cleanup() {
  if [[ -d "$staging_dir" ]]; then
    /bin/rm -rf -- "$staging_dir"
  fi
  if [[ -d "$backup_dir" && ! -e "$env_dir" ]]; then
    mv "$backup_dir" "$env_dir"
  fi
  return 0
}
trap cleanup EXIT INT TERM

stage14_install_secure_dir "$staging_dir" 700

read -rs "database_url?输入 API Session Pooler DATABASE_URL："; print
read -rs "export_database_url?输入 EXPORT_DATABASE_URL："; print
read -rs "grading_database_url?输入评分 Worker DATABASE_URL："; print
read -r "supabase_url?输入 SUPABASE_URL："
read -rs "supabase_publishable_key?输入 SUPABASE_PUBLISHABLE_KEY："; print
read -rs "supabase_secret_key?输入 SUPABASE_SECRET_KEY："; print
read -r "supabase_storage_bucket?输入 SUPABASE_STORAGE_BUCKET："
read -rs "provider_master_key?输入 PROVIDER_MASTER_KEY："; print
read -r "frontend_origin?输入 FRONTEND_ORIGIN："
read -r "vite_api_base_url?输入 VITE_API_BASE_URL："
read -r "uptimerobot_heartbeat_url?输入 UPTIMEROBOT_HEARTBEAT_URL："

auth_invite_redirect_url="${frontend_origin%/}/auth/callback"

umask 077
cat >"$staging_dir/production.env" <<EOF
APP_ENV=production
DATABASE_URL=$database_url
EXPORT_DATABASE_URL=$export_database_url
REDIS_URL=redis://127.0.0.1:6379/0
SUPABASE_URL=$supabase_url
SUPABASE_PUBLISHABLE_KEY=$supabase_publishable_key
SUPABASE_SECRET_KEY=$supabase_secret_key
SUPABASE_STORAGE_BUCKET=$supabase_storage_bucket
SUPABASE_STORAGE_SIGNED_URL_TTL_SECONDS=60
SUPABASE_STORAGE_TIMEOUT_SECONDS=60.0
PROVIDER_MASTER_KEY=$provider_master_key
AUTH_INVITE_REDIRECT_URL=$auth_invite_redirect_url
FRONTEND_ORIGIN=$frontend_origin
VITE_API_BASE_URL=$vite_api_base_url
VITE_SUPABASE_URL=$supabase_url
VITE_SUPABASE_PUBLISHABLE_KEY=$supabase_publishable_key
UPTIMEROBOT_HEARTBEAT_URL=$uptimerobot_heartbeat_url
EOF
cat >"$staging_dir/grading-worker.env" <<EOF
DATABASE_URL=$grading_database_url
EOF
chmod 600 "$staging_dir/production.env" "$staging_dir/grading-worker.env"

"$current_release/infra/local/validate-release.sh" "$current_sha" --env-dir "$staging_dir"

if [[ -d "$env_dir" ]]; then
  mv "$env_dir" "$backup_dir"
fi
mv "$staging_dir" "$env_dir"
trap - EXIT INT TERM
if [[ -d "$backup_dir" ]]; then
  /bin/rm -rf "$backup_dir"
fi

print "stage14_environment_updated=true"
