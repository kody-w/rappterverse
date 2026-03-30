#!/bin/bash
# watchdog.sh — 48-hour autopilot watchdog
# Monitors fleet health, restarts dead processes, commits state, reports stats.
# Usage: bash scripts/watchdog.sh

set -uo pipefail
# No set -e: watchdog must survive individual failures
cd "$(dirname "$0")/.."

LOG="logs/watchdog.log"
mkdir -p logs

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG"; }
CYCLE=0
START_TIME=$(date +%s)
END_TIME=$((START_TIME + 48 * 3600))  # 48 hours from now

log "=== WATCHDOG STARTED — 48hr autopilot ==="
log "End time: $(date -r $END_TIME '+%Y-%m-%d %H:%M:%S')"

ensure_main_loop() {
  if ! pgrep -f "local_platform.sh --loop" > /dev/null 2>&1; then
    log "RESTART: Main loop died — relaunching"
    nohup bash scripts/local_platform.sh --loop --interval 300 >> logs/main_loop.log 2>&1 &
    log "  Main loop restarted (PID $!)"
  fi
}

ensure_world_fleets() {
  for world in hub arena marketplace gallery dungeon; do
    if ! pgrep -f "agent_dispatch.py --world $world" > /dev/null 2>&1; then
      log "RESTART: Fleet $world died — relaunching"
      nohup python3 scripts/agent_dispatch.py --world "$world" --no-push --brainstem \
        >> "logs/fleet_${world}.log" 2>&1 &
      log "  Fleet $world restarted (PID $!)"
    fi
  done
}

ensure_engines() {
  local engines=(
    "world_growth.py:growth"
    "interaction_engine.py:interaction"
    "economy_engine.py:economy"
  )
  for entry in "${engines[@]}"; do
    local script="${entry%%:*}"
    local name="${entry##*:}"
    if ! pgrep -f "$script" > /dev/null 2>&1; then
      log "RESTART: Engine $name died — relaunching"
      nohup python3 "scripts/$script" --no-push >> "logs/fleet_${name}.log" 2>&1 &
      log "  Engine $name restarted (PID $!)"
    fi
  done
}

commit_and_push() {
  cd "$(dirname "$0")/.."
  git pull --rebase --autostash origin main 2>&1 | tail -1 || true

  local changed
  changed=$(git diff --name-only -- state/ feed/ 2>/dev/null | head -20)
  if [ -z "$changed" ]; then
    changed=$(git ls-files --others --exclude-standard -- state/ feed/ 2>/dev/null | head -5)
  fi
  if [ -z "$changed" ]; then
    return 0
  fi

  git add state/*.json state/memory/ state/inbox/ state/souls/ feed/*.json docs/dashboard.html 2>/dev/null || true
  local frame
  frame=$(python3 -c "import json; print(json.load(open('state/frame_counter.json')).get('frame', '?'))" 2>/dev/null || echo "?")
  git commit -m "[frame $frame] watchdog sync [skip ci]" 2>&1 | tail -1 || return 0
  git push origin main 2>&1 | tail -1 || log "WARN: push failed, will retry"
  log "  Pushed frame $frame"
}

report_stats() {
  python3 -c "
import json, os
from datetime import datetime, timezone

frame = json.load(open('state/frame_counter.json'))
agents = json.load(open('state/agents.json'))
game = json.load(open('state/game_state.json'))
llm = json.load(open('state/llm_usage.json')) if os.path.exists('state/llm_usage.json') else {}
actions = json.load(open('state/actions.json'))
chat = json.load(open('state/chat.json'))

count = agents.get('_meta', {}).get('count', len(agents.get('agents', [])))
worlds = ', '.join(f'{k}({v.get(\"population\",0)})' for k,v in game.get('worlds',{}).items())
llm_calls = llm.get('calls', 0)
action_count = len(actions.get('actions', []))
chat_count = len(chat.get('messages', []))

print(f'  Frame {frame[\"frame\"]} | {count} agents | LLM: {llm_calls} calls')
print(f'  Actions: {action_count} | Chat: {chat_count} | Worlds: {worlds}')
" 2>/dev/null || true

  # Count active processes
  local procs
  procs=$(ps aux | grep -E 'agent_dispatch|world_growth|interaction_engine|economy_engine|local_platform|brainstem|copilot' | grep -v grep | wc -l | tr -d ' ')
  log "  Active threads: $procs"
}

# ── Relaunch parallel world fleets on startup ──
relaunch_all_fleets() {
  log "Launching parallel world fleets..."
  for world in hub arena marketplace gallery dungeon; do
    if ! pgrep -f "agent_dispatch.py --world $world" > /dev/null 2>&1; then
      nohup python3 scripts/agent_dispatch.py --world "$world" --no-push --brainstem \
        >> "logs/fleet_${world}.log" 2>&1 &
      log "  Fleet $world (PID $!)"
    fi
  done
  # Subsystem engines
  for script_name in world_growth interaction_engine economy_engine; do
    if ! pgrep -f "${script_name}.py" > /dev/null 2>&1; then
      nohup python3 "scripts/${script_name}.py" --no-push >> "logs/fleet_${script_name}.log" 2>&1 &
      log "  Engine $script_name (PID $!)"
    fi
  done
}

# ── Main watchdog loop ──
relaunch_all_fleets

while [ "$(date +%s)" -lt "$END_TIME" ]; do
  CYCLE=$((CYCLE + 1))
  log "--- Watchdog cycle $CYCLE ---"

  # 1. Check and restart dead processes
  ensure_main_loop
  ensure_world_fleets
  ensure_engines

  # 2. Commit and push any state changes
  commit_and_push

  # 3. Report stats
  report_stats

  # 4. Every 6th cycle (~30 min), relaunch fresh parallel dispatches
  if [ $((CYCLE % 6)) -eq 0 ]; then
    log "BOOST: Launching fresh parallel dispatch burst"
    for world in hub arena marketplace gallery dungeon; do
      nohup python3 scripts/agent_dispatch.py --world "$world" --no-push --brainstem \
        >> "logs/fleet_${world}_burst.log" 2>&1 &
    done
    log "  5 burst fleets launched"
  fi

  # 5. Every 12th cycle (~1 hour), run growth + emergence
  if [ $((CYCLE % 12)) -eq 0 ]; then
    log "HEARTBEAT: Running growth + emergence"
    nohup python3 scripts/world_growth.py --no-push >> logs/fleet_growth_periodic.log 2>&1 &
    nohup python3 scripts/emergence.py --no-push >> logs/fleet_emergence_periodic.log 2>&1 &
  fi

  # Hours remaining
  remaining=$(( (END_TIME - $(date +%s)) / 3600 ))
  log "  ${remaining}h remaining in 48hr window"

  sleep 300  # Check every 5 minutes
done

log "=== WATCHDOG COMPLETE — 48hr window elapsed ==="
