#!/bin/bash
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
LABEL="com.rappterverse.local-platform"
DOMAIN="gui/$(id -u)"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG_DIR="$REPO/logs"
AGENT_BATCH="${RAPPTERVERSE_AGENT_BATCH:-8}"

mkdir -p "$HOME/Library/LaunchAgents" "$LOG_DIR"

launchctl bootout "$DOMAIN/$LABEL" >/dev/null 2>&1 || true

cat >"$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>$REPO/scripts/local_platform.sh</string>
    <string>--loop</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict>
    <key>HOME</key>
    <string>$HOME</string>
    <key>PATH</key>
    <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
    <key>RAPPTERVERSE_AGENT_BATCH</key>
    <string>$AGENT_BATCH</string>
  </dict>
  <key>KeepAlive</key>
  <true/>
  <key>RunAtLoad</key>
  <true/>
  <key>ProcessType</key>
  <string>Background</string>
  <key>StandardOutPath</key>
  <string>$LOG_DIR/local-platform.out.log</string>
  <key>StandardErrorPath</key>
  <string>$LOG_DIR/local-platform.err.log</string>
</dict>
</plist>
PLIST

plutil -lint "$PLIST"
launchctl bootstrap "$DOMAIN" "$PLIST"
launchctl kickstart -k "$DOMAIN/$LABEL"

echo "installed $LABEL"
echo "status: launchctl print $DOMAIN/$LABEL"
echo "logs:   $LOG_DIR/local-platform.out.log"
