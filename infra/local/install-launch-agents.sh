#!/bin/zsh
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && /bin/pwd -P)
source "$SCRIPT_DIR/stage14-runtime-common.sh"

if [[ "${1:-}" = "--self-check" ]]; then
  command -v launchctl >/dev/null
  command -v plutil >/dev/null
  typeset -f stage14_install_secure_dir >/dev/null
  stage14_self_check_ok
fi

CURRENT_LINK=$(stage14_current_root)
test -L "$CURRENT_LINK"
CURRENT_ROOT="$CURRENT_LINK"
RUNTIME_ROOT=$(stage14_runtime_root)
LAUNCH_AGENTS_DIR="$HOME/Library/LaunchAgents"
LOG_DIR="$(stage14_logs_dir)"
ENV_DIR="$(stage14_env_dir)"
STATE_DIR="$(stage14_state_dir)"
USER_DOMAIN="gui/$UID"
TRANSACTION_FILE="$STATE_DIR/launchagent-first-install.paths"
TRANSACTION_TEMP="$STATE_DIR/.launchagent-first-install.$$.paths"
umask 077

stage14_install_secure_dir "$RUNTIME_ROOT" 700
stage14_install_secure_dir "$(stage14_shared_root)" 700
stage14_install_secure_dir "$ENV_DIR" 700
stage14_install_secure_dir "$STATE_DIR" 700
stage14_install_secure_dir "$LOG_DIR" 700
stage14_install_secure_dir "$LAUNCH_AGENTS_DIR" 700
stage14_install_secure_dir "$(stage14_tailscale_dir)" 700
stage14_require_regular_file "$ENV_DIR/production.env"
stage14_require_regular_file "$ENV_DIR/grading-worker.env"
touch "$(stage14_tailscale_state)"
chmod 600 "$(stage14_tailscale_state)" "$ENV_DIR/production.env" "$ENV_DIR/grading-worker.env"
for component in api grading export keep-awake tailscale watchdog; do
  touch "$LOG_DIR/$component.stdout.log" "$LOG_DIR/$component.stderr.log"
  chmod 600 "$LOG_DIR/$component.stdout.log" "$LOG_DIR/$component.stderr.log"
done

rollback_first_install() {
  local record_file="$TRANSACTION_FILE"
  local plist label
  if [[ -f "$TRANSACTION_TEMP" ]]; then
    record_file="$TRANSACTION_TEMP"
  fi
  if [[ ! -f "$record_file" ]]; then
    print "stage14_first_install_rollback=true"
    return 0
  fi
  while IFS= read -r plist; do
    case "$plist" in
      "$LAUNCH_AGENTS_DIR"/com.paper-grading.*.plist) ;;
      *) return 1 ;;
    esac
    test ! -L "$plist"
    label="${${plist:t}%.plist}"
    launchctl bootout "$USER_DOMAIN" "$plist" >/dev/null 2>&1 || true
    if [[ -f "$plist" ]]; then
      /bin/rm -f -- "$plist"
    fi
  done <"$record_file"
  /bin/rm -f -- "$record_file"
  print "stage14_first_install_rollback=true"
}

if [[ "${1:-}" = "--rollback-first-install" ]]; then
  rollback_first_install
  exit 0
fi

for label in api grading export keep-awake tailscale watchdog; do
  test ! -e "$LAUNCH_AGENTS_DIR/com.paper-grading.$label.plist"
done

: >"$TRANSACTION_TEMP"
chmod 600 "$TRANSACTION_TEMP"
trap 'rollback_first_install >/dev/null; exit 1' ZERR INT TERM

record_if_new() {
  local plist=$1
  if [[ ! -e "$plist" ]]; then
    print -r -- "$plist" >>"$TRANSACTION_TEMP"
  fi
}

write_component_plist() {
  local component=$1
  local label="com.paper-grading.$component"
  local plist="$LAUNCH_AGENTS_DIR/$label.plist"
  record_if_new "$plist"

  cat >"$plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>$label</string>
  <key>ProgramArguments</key>
  <array>
    <string>$CURRENT_ROOT/infra/local/run-component.sh</string>
    <string>$component</string>
  </array>
  <key>WorkingDirectory</key>
  <string>$CURRENT_ROOT</string>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>ThrottleInterval</key>
  <integer>10</integer>
  <key>StandardOutPath</key>
  <string>$LOG_DIR/$component.stdout.log</string>
  <key>StandardErrorPath</key>
  <string>$LOG_DIR/$component.stderr.log</string>
</dict>
</plist>
EOF
  plutil -lint "$plist" >/dev/null
  launchctl bootout "$USER_DOMAIN" "$plist" >/dev/null 2>&1 || true
  launchctl bootstrap "$USER_DOMAIN" "$plist"
}

write_keep_awake_plist() {
  local label="com.paper-grading.keep-awake"
  local plist="$LAUNCH_AGENTS_DIR/$label.plist"
  record_if_new "$plist"

  cat >"$plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>$label</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/caffeinate</string>
    <string>-dimsu</string>
  </array>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>ThrottleInterval</key>
  <integer>10</integer>
  <key>StandardOutPath</key>
  <string>$LOG_DIR/keep-awake.stdout.log</string>
  <key>StandardErrorPath</key>
  <string>$LOG_DIR/keep-awake.stderr.log</string>
</dict>
</plist>
EOF
  plutil -lint "$plist" >/dev/null
  launchctl bootout "$USER_DOMAIN" "$plist" >/dev/null 2>&1 || true
  launchctl bootstrap "$USER_DOMAIN" "$plist"
}

write_single_program_plist() {
  local component=$1
  local program=$2
  local interval=${3:-}
  local label="com.paper-grading.$component"
  local plist="$LAUNCH_AGENTS_DIR/$label.plist"
  local schedule
  record_if_new "$plist"

  if [[ -n "$interval" ]]; then
    schedule="<key>StartInterval</key><integer>$interval</integer>"
  else
    schedule="<key>RunAtLoad</key><true/><key>KeepAlive</key><true/>"
  fi

  cat >"$plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>$label</string>
  <key>ProgramArguments</key>
  <array>
    <string>$program</string>
  </array>
  <key>WorkingDirectory</key>
  <string>$CURRENT_ROOT</string>
  $schedule
  <key>ThrottleInterval</key>
  <integer>10</integer>
  <key>StandardOutPath</key>
  <string>$LOG_DIR/$component.stdout.log</string>
  <key>StandardErrorPath</key>
  <string>$LOG_DIR/$component.stderr.log</string>
</dict>
</plist>
EOF
  plutil -lint "$plist" >/dev/null
  launchctl bootout "$USER_DOMAIN" "$plist" >/dev/null 2>&1 || true
  launchctl bootstrap "$USER_DOMAIN" "$plist"
}

write_component_plist api
write_component_plist grading
write_component_plist export
write_keep_awake_plist
write_single_program_plist tailscale "$CURRENT_ROOT/infra/local/run-tailscale.sh"
write_single_program_plist watchdog "$CURRENT_ROOT/infra/local/watchdog.sh" 60

mv -f "$TRANSACTION_TEMP" "$TRANSACTION_FILE"
trap - ZERR INT TERM

print "stage14_launch_agents_installed=true"
