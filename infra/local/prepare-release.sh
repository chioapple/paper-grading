#!/bin/zsh
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && /bin/pwd -P)
source "$SCRIPT_DIR/stage14-runtime-common.sh"

if [[ "${1:-}" = "--self-check" ]]; then
  project_root=$(stage14_project_root)
  command -v git >/dev/null
  command -v npm >/dev/null
  test -f "$project_root/backend/pyproject.toml"
  test -f "$project_root/frontend/package-lock.json"
  test -x "$project_root/.venv/bin/python"
  stage14_self_check_ok
fi

usage() {
  print -u2 "用法：prepare-release.sh <完整 SHA>"
}

if [[ "${1:-}" = "--help" ]]; then
  usage
  exit 0
fi

if [[ $# -ne 1 ]]; then
  usage
  exit 2
fi

sha=$1
stage14_assert_full_sha "$sha"

project_root=$(stage14_project_root)
runtime_root=$(stage14_runtime_root)
releases_root=$(stage14_releases_root)
shared_root=$(stage14_shared_root)
shared_bin="$shared_root/bin"
target_release=$(stage14_release_path "$sha")
sealed_flag=$(stage14_release_sealed_flag "$sha")
manifest_path=$(stage14_release_manifest "$sha")
temp_switcher="$shared_bin/.switch-release.sh.$$"
temp_helper="$shared_bin/.stage14-runtime-common.sh.$$"

# 封存目录固定为 releases/$sha。
git -C "$project_root" cat-file -e "${sha}^{commit}"
test -n "${VITE_API_BASE_URL:-}"
test -n "${VITE_SUPABASE_URL:-}"
test -n "${VITE_SUPABASE_PUBLISHABLE_KEY:-}"
test -d "$project_root/.venv"

stage14_install_secure_dir "$runtime_root" 700
stage14_install_secure_dir "$releases_root" 700
stage14_install_secure_dir "$shared_root" 700
stage14_install_secure_dir "$shared_bin" 700
stage14_install_secure_dir "$(stage14_state_dir)" 700
stage14_install_secure_dir "$(stage14_logs_dir)" 700
stage14_install_secure_dir "$(stage14_acceptance_dir)" 700
stage14_install_secure_dir "$(stage14_tailscale_dir)" 700

if [[ -e "$target_release" ]]; then
  test -f "$sealed_flag"
  test -f "$manifest_path"
else
  cleanup() {
    if [[ -d "$target_release" && ! -e "$sealed_flag" ]]; then
      /bin/rm -rf -- "$target_release"
    fi
    /bin/rm -f "$temp_switcher" "$temp_helper"
  }
  trap cleanup EXIT INT TERM

  mkdir "$target_release"
  git -C "$project_root" archive "$sha" | /usr/bin/tar -x -C "$target_release"
  "$project_root/.venv/bin/python" -m venv "$target_release/.venv"
  "$target_release/.venv/bin/python" -m pip install --disable-pip-version-check \
    -e "$target_release/backend[dev]"

  (
    cd "$target_release/frontend"
    npm ci
    npm run build:sites
  )

  test -f "$target_release/frontend/dist/server/index.js"
  test -f "$target_release/frontend/.openai/hosting.json"

  publishable_key_sha=$(stage14_hash_value "$VITE_SUPABASE_PUBLISHABLE_KEY")
  cat >"$manifest_path" <<EOF
{
  "sha": "$sha",
  "vite_api_base_url": "$VITE_API_BASE_URL",
  "vite_supabase_url": "$VITE_SUPABASE_URL",
  "vite_supabase_publishable_key_sha256": "$publishable_key_sha"
}
EOF

  touch "$sealed_flag"
  chmod -R a-w "$target_release"
  trap - EXIT INT TERM
fi

# 稳定 manager 固定安装到 shared/bin/switch-release.sh。
cp "$target_release/infra/local/switch-release.sh" "$temp_switcher"
cp "$target_release/infra/local/stage14-runtime-common.sh" "$temp_helper"
chmod 700 "$temp_switcher" "$temp_helper"
mv -f "$temp_switcher" "$shared_bin/switch-release.sh"
mv -f "$temp_helper" "$shared_bin/stage14-runtime-common.sh"
/usr/bin/cmp -s "$target_release/infra/local/switch-release.sh" "$shared_bin/switch-release.sh"
/usr/bin/cmp -s "$target_release/infra/local/stage14-runtime-common.sh" "$shared_bin/stage14-runtime-common.sh"
test "$(/usr/bin/stat -f '%Lp' "$shared_bin/switch-release.sh")" = "700"
test "$(/usr/bin/stat -f '%Su' "$shared_bin/switch-release.sh")" = "$USER"

print "stage14_release_prepared=true"
