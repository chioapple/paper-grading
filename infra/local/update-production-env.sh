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

if [[ "$frontend_origin" != https://* || "$frontend_origin" = */ ]]; then
  print -u2 "FRONTEND_ORIGIN 必须以 https:// 开头且不带尾斜杠"
  exit 1
fi
if [[ "$vite_api_base_url" != https://* || "$vite_api_base_url" = */ ]]; then
  print -u2 "VITE_API_BASE_URL 必须以 https:// 开头且不带尾斜杠"
  exit 1
fi

auth_invite_redirect_url="${frontend_origin%/}/auth/callback"

quote_env_value() {
  local value=$1
  if [[ "$value" = *$'\n'* || "$value" = *$'\r'* ]]; then
    print -u2 "环境值不得包含换行符"
    return 1
  fi
  printf '%q' "$value"
}

database_url_q=$(quote_env_value "$database_url")
export_database_url_q=$(quote_env_value "$export_database_url")
grading_database_url_q=$(quote_env_value "$grading_database_url")
supabase_url_q=$(quote_env_value "$supabase_url")
supabase_publishable_key_q=$(quote_env_value "$supabase_publishable_key")
supabase_secret_key_q=$(quote_env_value "$supabase_secret_key")
supabase_storage_bucket_q=$(quote_env_value "$supabase_storage_bucket")
provider_master_key_q=$(quote_env_value "$provider_master_key")
auth_invite_redirect_url_q=$(quote_env_value "$auth_invite_redirect_url")
frontend_origin_q=$(quote_env_value "$frontend_origin")
vite_api_base_url_q=$(quote_env_value "$vite_api_base_url")

umask 077
cat >"$staging_dir/production.env" <<EOF
APP_ENV=production
DATABASE_URL=$database_url_q
EXPORT_DATABASE_URL=$export_database_url_q
READINESS_DATABASE_TIMEOUT_SECONDS=15.0
REDIS_URL=redis://127.0.0.1:6379/0
SUPABASE_URL=$supabase_url_q
SUPABASE_PUBLISHABLE_KEY=$supabase_publishable_key_q
SUPABASE_SECRET_KEY=$supabase_secret_key_q
SUPABASE_STORAGE_BUCKET=$supabase_storage_bucket_q
SUPABASE_STORAGE_SIGNED_URL_TTL_SECONDS=60
SUPABASE_STORAGE_TIMEOUT_SECONDS=60.0
PROVIDER_MASTER_KEY=$provider_master_key_q
PROVIDER_CALLS_ENABLED=false
AUTH_INVITE_REDIRECT_URL=$auth_invite_redirect_url_q
FRONTEND_ORIGIN=$frontend_origin_q
VITE_API_BASE_URL=$vite_api_base_url_q
VITE_SUPABASE_URL=$supabase_url_q
VITE_SUPABASE_PUBLISHABLE_KEY=$supabase_publishable_key_q
EOF
cat >"$staging_dir/grading-worker.env" <<EOF
DATABASE_URL=$grading_database_url_q
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
