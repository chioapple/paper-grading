#!/bin/zsh
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && /bin/pwd -P)
source "$SCRIPT_DIR/stage14-runtime-common.sh"

curl_bin="${STAGE14_CURL_BIN:-/usr/bin/curl}"

if [[ "${1:-}" = "--self-check" ]]; then
  test -x "$curl_bin"
  stage14_self_check_ok
fi

if [[ $# -ne 0 ]]; then
  print -u2 "用法：verify-supabase-browser-config.sh"
  exit 2
fi

supabase_url="${VITE_SUPABASE_URL:-}"
publishable_key="${VITE_SUPABASE_PUBLISHABLE_KEY:-}"

if [[ ! "$supabase_url" =~ '^https://[A-Za-z0-9.-]+$' ]]; then
  print -u2 "stage14_supabase_url_invalid=true"
  exit 1
fi

if [[ ! "$publishable_key" =~ '^sb_publishable_[A-Za-z0-9_-]{20,}$' ]]; then
  print -u2 "stage14_supabase_publishable_key_invalid=true"
  exit 1
fi

curl_config=$(mktemp)
trap '/bin/rm -f -- "$curl_config"' EXIT INT TERM
/bin/chmod 600 "$curl_config"
{
  print 'fail'
  print 'silent'
  print 'show-error'
  print 'output = "/dev/null"'
  print 'connect-timeout = 10'
  print 'max-time = 20'
  print -r -- "url = \"$supabase_url/auth/v1/settings\""
  print -r -- "header = \"apikey: $publishable_key\""
  print -r -- "header = \"Authorization: Bearer $publishable_key\""
} >"$curl_config"

if ! "$curl_bin" --config "$curl_config"; then
  print -u2 "stage14_supabase_publishable_key_invalid=true"
  exit 1
fi

print "stage14_supabase_browser_config_verified=true"
