#!/bin/zsh
set -euo pipefail

PROJECT_ROOT=$(cd "$(dirname "$0")/../.." && pwd)
LAUNCH_AGENTS_DIR="$HOME/Library/LaunchAgents"
LOG_DIR="$PROJECT_ROOT/logs/production"
USER_DOMAIN="gui/$UID"

test -f "$PROJECT_ROOT/.env.stage14-production"
test -f "$PROJECT_ROOT/.env.stage14-grading-worker"
test -f "$PROJECT_ROOT/tmp/tailscale/tailscaled.state"
chmod 600 \
  "$PROJECT_ROOT/.env.stage14-production" \
  "$PROJECT_ROOT/.env.stage14-grading-worker" \
  "$PROJECT_ROOT/tmp/tailscale/tailscaled.state"
mkdir -p "$LAUNCH_AGENTS_DIR" "$LOG_DIR"

write_component_plist() {
  local component=$1
  local label="com.paper-grading.$component"
  local plist="$LAUNCH_AGENTS_DIR/$label.plist"

  cat >"$plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>$label</string>
  <key>ProgramArguments</key>
  <array>
    <string>$PROJECT_ROOT/infra/local/run-component.sh</string>
    <string>$component</string>
  </array>
  <key>WorkingDirectory</key>
  <string>$PROJECT_ROOT</string>
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
  launchctl bootout "$USER_DOMAIN" "$plist" 2>/dev/null || true
  launchctl bootstrap "$USER_DOMAIN" "$plist"
}

write_keep_awake_plist() {
  local label="com.paper-grading.keep-awake"
  local plist="$LAUNCH_AGENTS_DIR/$label.plist"

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
  launchctl bootout "$USER_DOMAIN" "$plist" 2>/dev/null || true
  launchctl bootstrap "$USER_DOMAIN" "$plist"
}

write_single_program_plist() {
  local component=$1
  local program=$2
  local interval=${3:-}
  local label="com.paper-grading.$component"
  local plist="$LAUNCH_AGENTS_DIR/$label.plist"
  local schedule

  if test -n "$interval"; then
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
  <string>$PROJECT_ROOT</string>
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
  launchctl bootout "$USER_DOMAIN" "$plist" 2>/dev/null || true
  launchctl bootstrap "$USER_DOMAIN" "$plist"
}

test "$(/opt/homebrew/bin/redis-cli ping)" = "PONG"
write_component_plist api
write_component_plist grading
write_component_plist export
write_keep_awake_plist
write_single_program_plist tailscale "$PROJECT_ROOT/infra/local/run-tailscale.sh"
write_single_program_plist watchdog "$PROJECT_ROOT/infra/local/watchdog.sh" 60

print "stage14_launch_agents_installed=true"
