#!/bin/bash
# watchdog.sh — supervise the single isolated local-platform loop.

set -uo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
LOG_DIR="$REPO/logs"
LOG="$LOG_DIR/watchdog.log"
MAIN_LOG="$LOG_DIR/main_loop.log"
INTERVAL="${INTERVAL:-300}"
END_TIME=$(( $(date +%s) + 48 * 3600 ))

mkdir -p "$LOG_DIR"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG"; }

main_loop_pid() {
  pgrep -f "$REPO/scripts/local_platform.sh --loop" | head -1
}

ensure_main_loop() {
  local pid
  pid=$(main_loop_pid)
  if [ -n "$pid" ]; then
    log "Local platform healthy (PID $pid)"
    return 0
  fi

  log "RESTART: isolated local-platform loop is not running"
  nohup bash "$REPO/scripts/local_platform.sh" --loop --interval "$INTERVAL" \
    >> "$MAIN_LOG" 2>&1 &
  pid=$!
  sleep 2
  if ! kill -0 "$pid" 2>/dev/null; then
    log "ERROR: local-platform restart failed"
    return 1
  fi
  log "Local platform restarted (PID $pid)"
}

log "=== WATCHDOG STARTED — isolated writer supervision ==="
while [ "$(date +%s)" -lt "$END_TIME" ]; do
  ensure_main_loop || true
  bash "$REPO/scripts/local_platform.sh" --status >> "$LOG" 2>&1 || true
  sleep "$INTERVAL"
done
log "=== WATCHDOG COMPLETE — 48hr window elapsed ==="
