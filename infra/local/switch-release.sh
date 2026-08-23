#!/bin/zsh
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && /bin/pwd -P)
source "$SCRIPT_DIR/stage14-runtime-common.sh"

if [[ "${1:-}" = "--self-check" ]]; then
  typeset -f stage14_assert_full_sha >/dev/null
  typeset -f stage14_resolve_symlink_target >/dev/null
  stage14_self_check_ok
fi

usage() {
  print -u2 "用法：switch-release.sh <完整 SHA> [--prepare-only]"
}

if [[ "${1:-}" = "--help" ]]; then
  usage
  exit 0
fi

if (( $# != 1 && $# != 2 )); then
  usage
  exit 2
fi

sha=$1
mode="${2:-}"
if [[ -n "$mode" ]]; then
  test "$mode" = "--prepare-only"
fi

stage14_assert_full_sha "$sha"

runtime_root=$(stage14_runtime_root)
target_release=$(stage14_release_path "$sha")
sealed_flag=$(stage14_release_sealed_flag "$sha")
current_link=$(stage14_current_root)
temp_link="$runtime_root/.current.$sha.$$"

test -d "$target_release"
test -f "$sealed_flag"
stage14_install_secure_dir "$runtime_root" 700
if [[ -e "$current_link" ]]; then
  test -L "$current_link"
fi

ln -s "$target_release" "$temp_link"
/bin/mv -f -h "$temp_link" "$current_link"
test "$(stage14_resolve_symlink_target "$current_link")" = "$target_release"

if [[ "$mode" = "--prepare-only" ]]; then
  print "stage14_release_switch_prepared=true"
else
  print "stage14_release_switched=true"
fi
