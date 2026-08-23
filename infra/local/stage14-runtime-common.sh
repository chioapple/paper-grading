#!/bin/zsh

# 阶段 14 本机运行根共享工具。

if [[ "${STAGE14_RUNTIME_COMMON_LOADED:-0}" = "1" ]] && typeset -f stage14_project_root >/dev/null 2>&1; then
  return 0
fi
typeset -g STAGE14_RUNTIME_COMMON_LOADED=1

STAGE14_COMMON_SOURCE="${(%):-%N}"
STAGE14_COMMON_DIR=$(cd "$(dirname "$STAGE14_COMMON_SOURCE")" && /bin/pwd -P)
STAGE14_PROJECT_ROOT_DEFAULT=$(cd "$STAGE14_COMMON_DIR/../.." && /bin/pwd -P)

stage14_project_root() {
  print -r -- "${STAGE14_PROJECT_ROOT:-$STAGE14_PROJECT_ROOT_DEFAULT}"
}

stage14_runtime_root() {
  print -r -- "${STAGE14_RUNTIME_ROOT:-$HOME/Library/Application Support/Paper Grading}"
}

stage14_releases_root() {
  print -r -- "$(stage14_runtime_root)/releases"
}

stage14_shared_root() {
  print -r -- "$(stage14_runtime_root)/shared"
}

stage14_current_root() {
  print -r -- "$(stage14_runtime_root)/current"
}

stage14_env_dir() {
  print -r -- "$(stage14_shared_root)/env"
}

stage14_logs_dir() {
  print -r -- "$(stage14_shared_root)/logs"
}

stage14_state_dir() {
  print -r -- "$(stage14_shared_root)/state"
}

stage14_acceptance_dir() {
  print -r -- "$(stage14_shared_root)/acceptance"
}

stage14_tailscale_dir() {
  print -r -- "$(stage14_shared_root)/tailscale"
}

stage14_tailscale_socket() {
  print -r -- "$(stage14_tailscale_dir)/tailscaled.sock"
}

stage14_tailscale_state() {
  print -r -- "$(stage14_tailscale_dir)/tailscaled.state"
}

stage14_tailscale_pidfile() {
  print -r -- "$(stage14_tailscale_dir)/tailscaled.pid"
}

stage14_assert_full_sha() {
  local sha=$1
  print -rn -- "$sha" | /usr/bin/grep -Eq '^[0-9a-f]{40}$'
}

stage14_release_path() {
  local sha=$1
  print -r -- "$(stage14_releases_root)/$sha"
}

stage14_release_manifest() {
  local sha=$1
  print -r -- "$(stage14_release_path "$sha")/.release-manifest.json"
}

stage14_release_sealed_flag() {
  local sha=$1
  print -r -- "$(stage14_release_path "$sha")/SEALED"
}

stage14_install_secure_dir() {
  local dir_path=$1
  local mode=$2
  STAGE14_SECURE_DIR="$dir_path" /usr/bin/python3 - <<'PY'
import os
from pathlib import Path

path = Path(os.environ["STAGE14_SECURE_DIR"])
home = Path.home()
if not path.is_absolute():
    raise SystemExit(1)
for candidate in reversed((path, *path.parents)):
    if candidate == Path("/"):
        continue
    if candidate.is_symlink():
        raise SystemExit(1)
    if candidate.exists():
        stat = candidate.stat()
        if not candidate.is_dir():
            raise SystemExit(1)
        if (candidate == home or home in candidate.parents) and stat.st_uid != os.getuid():
            raise SystemExit(1)
PY
  /usr/bin/install -d -m "$mode" "$dir_path"
  /bin/chmod "$mode" "$dir_path"
}

stage14_require_regular_file() {
  local file_path=$1
  test -f "$file_path"
  test ! -L "$file_path"
}

stage14_hash_value() {
  local value=$1
  print -rn -- "$value" | /usr/bin/shasum -a 256 | /usr/bin/awk '{print $1}'
}

stage14_resolve_symlink_target() {
  local link_path=$1
  /usr/bin/stat -f '%Y' "$link_path"
}

stage14_load_env_file() {
  local file_path=$1
  stage14_require_regular_file "$file_path"
  set -a
  source "$file_path"
  set +a
}

stage14_self_check_ok() {
  print "stage14_self_check=true"
  exit 0
}
