#!/bin/bash
# local_platform.sh — Full local replacement for GitHub Actions
#
# Runs the entire RAPPterverse pipeline locally on a schedule. When running,
# this script replaces all cron-based GitHub Actions: game-tick, agent-autonomy,
# world-growth, self-improve, state-audit. Pushes directly to main with [skip ci]
# so Actions don't cascade.
#
# Usage:
#   bash scripts/local_platform.sh                    # run once (all jobs)
#   bash scripts/local_platform.sh --loop             # run forever (scheduled)
#   bash scripts/local_platform.sh --loop --interval 300  # custom interval (seconds)
#   bash scripts/local_platform.sh --job game_tick    # run a single job
#   bash scripts/local_platform.sh --status           # show last run times
#
# Jobs and their schedules (replaces GitHub Actions crons):
#   game_tick        — every 5 min   (was: game-tick.yml every 5 min)
#   agent_dispatch   — every 30 min  (was: agent-autonomy.yml every 30 min)
#   world_growth     — every 4 hours (was: world-growth.yml every 4 hours)
#   self_improve     — every 6 hours (was: self-improve.yml every 6 hours)
#   state_audit      — every 12 hrs  (was: state-audit.yml every 12 hours)
#   git_sync         — every cycle   (pull + push with [skip ci])

set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO"

STATE_DIR="state"
LOG_DIR="$REPO/logs"
STATUS_FILE="$LOG_DIR/local_platform_status.json"
INTERVAL="${INTERVAL:-300}"  # 5 minutes default
CYCLE=0

mkdir -p "$LOG_DIR"

# ── Token Setup ───────────────────────────────────────────────────────────────
# Agent dispatch and self-improve need MODELS_TOKEN for LLM calls.
# Fall back to gh CLI auth token if not explicitly set.

if [ -z "${MODELS_TOKEN:-}" ]; then
  MODELS_TOKEN=$(gh auth token 2>/dev/null || echo "")
  export MODELS_TOKEN
fi
if [ -z "${GH_TOKEN:-}" ]; then
  GH_TOKEN=$(gh auth token 2>/dev/null || echo "")
  export GH_TOKEN
fi

# ── iMessage Alerts ───────────────────────────────────────────────────────────

send_alert() {
  local msg="$1"
  osascript -e "display notification \"$msg\" with title \"RAPPterverse\"" 2>/dev/null || true
}

# ── Helpers ───────────────────────────────────────────────────────────────────

log() { echo "[$(date '+%H:%M:%S')] $*"; }
err() { echo "[$(date '+%H:%M:%S')] ERROR: $*" >&2; send_alert "$*"; }

run_job() {
  local job="$1"
  local start=$(date +%s)
  log "Running: $job"
  if "$@" 2>&1 | tail -5; then
    local elapsed=$(( $(date +%s) - start ))
    log "  Done: $job (${elapsed}s)"
    update_status "$job" "ok" "$elapsed"
  else
    err "  Failed: $job"
    update_status "$job" "failed" "0"
  fi
}

update_status() {
  local job="$1" status="$2" elapsed="$3"
  python3 -c "
import json, os
from datetime import datetime, timezone
path = '$STATUS_FILE'
try:
    with open(path) as f: data = json.load(f)
except:
    data = {}
data['$job'] = {
    'status': '$status',
    'elapsed_s': int('$elapsed'),
    'last_run': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
}
data['_last_cycle'] = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
data['_cycle_count'] = data.get('_cycle_count', 0) + (1 if '$job' == 'job_git_sync' else 0)
with open(path, 'w') as f:
    json.dump(data, f, indent=2)
" 2>/dev/null || true
}

should_run() {
  local job="$1" interval_minutes="$2"
  python3 -c "
import json, sys
from datetime import datetime, timezone, timedelta
try:
    with open('$STATUS_FILE') as f: data = json.load(f)
    last = data.get('$job', {}).get('last_run', '')
    if not last:
        sys.exit(0)
    last_dt = datetime.fromisoformat(last.replace('Z', '+00:00'))
    if datetime.now(timezone.utc) - last_dt > timedelta(minutes=$interval_minutes):
        sys.exit(0)
    sys.exit(1)
except:
    sys.exit(0)
" 2>/dev/null
}

# ── Job Functions ─────────────────────────────────────────────────────────────

job_game_tick() {
  # Process triggers and NPC needs decay
  # Original: game-tick.yml every 5 min
  python3 scripts/game_tick.py 2>&1
}

job_agent_dispatch() {
  # Ambient agent activity — ALL agents, Copilot is unlimited
  # Original: agent-autonomy.yml every 30 min (was capped at 10)
  python3 scripts/build_agent_registry.py 2>&1
  python3 scripts/agent_dispatch.py --all --max-agents 50 --no-push --brainstem 2>&1
}

job_world_growth() {
  # Full world heartbeat: growth + interaction + academy + economy + zoo + dashboard
  # Original: world-growth.yml every 4 hours
  # Each subsystem gets a snapshot for rollback safety
  local failed=0

  log "  [heartbeat] Growth simulation..."
  cp -r state/ /tmp/.rappterverse-snapshot-growth/
  if python3 scripts/world_growth.py --no-push 2>&1; then
    rm -rf /tmp/.rappterverse-snapshot-growth/
  else
    err "  Growth failed — rolling back"
    cp -r /tmp/.rappterverse-snapshot-growth/* state/
    rm -rf /tmp/.rappterverse-snapshot-growth/
    failed=1
  fi

  log "  [heartbeat] Interaction engine..."
  cp -r state/ /tmp/.rappterverse-snapshot-interaction/
  if python3 scripts/interaction_engine.py --no-push 2>&1; then
    rm -rf /tmp/.rappterverse-snapshot-interaction/
  else
    err "  Interaction failed — rolling back"
    cp -r /tmp/.rappterverse-snapshot-interaction/* state/
    rm -rf /tmp/.rappterverse-snapshot-interaction/
    failed=1
  fi

  log "  [heartbeat] Academy engine..."
  cp -r state/ /tmp/.rappterverse-snapshot-academy/
  if python3 scripts/academy_engine.py --no-push 2>&1; then
    rm -rf /tmp/.rappterverse-snapshot-academy/
  else
    err "  Academy failed — rolling back"
    cp -r /tmp/.rappterverse-snapshot-academy/* state/
    rm -rf /tmp/.rappterverse-snapshot-academy/
    failed=1
  fi

  log "  [heartbeat] Economy engine..."
  cp -r state/ /tmp/.rappterverse-snapshot-economy/
  if python3 scripts/economy_engine.py --no-push 2>&1; then
    rm -rf /tmp/.rappterverse-snapshot-economy/
  else
    err "  Economy failed — rolling back"
    cp -r /tmp/.rappterverse-snapshot-economy/* state/
    rm -rf /tmp/.rappterverse-snapshot-economy/
    failed=1
  fi

  log "  [heartbeat] Zoo heartbeat..."
  cp -r state/ /tmp/.rappterverse-snapshot-zoo/
  if python3 scripts/zoo_heartbeat.py --no-push 2>&1; then
    rm -rf /tmp/.rappterverse-snapshot-zoo/
  else
    err "  Zoo failed — rolling back"
    cp -r /tmp/.rappterverse-snapshot-zoo/* state/
    rm -rf /tmp/.rappterverse-snapshot-zoo/
    failed=1
  fi

  log "  [heartbeat] Dashboard..."
  python3 scripts/generate_dashboard.py 2>&1 || true

  log "  [heartbeat] Validate state..."
  python3 scripts/validate_action.py --audit 2>&1 || true

  log "  [heartbeat] PII scan..."
  python3 scripts/pii_scan.py state/ feed/ 2>&1 || true

  return $failed
}

job_self_improve() {
  # evolve-001 self-improvement cycle
  # Original: self-improve.yml every 6 hours
  python3 scripts/build_agent_registry.py 2>&1
  python3 scripts/agent_dispatch.py --agent evolve-001 --no-push 2>&1
  python3 scripts/self_improve.py --no-push 2>&1
  rm -f state/evolution_pr_body.md
}

job_state_audit() {
  # Full state consistency check
  # Original: state-audit.yml every 12 hours
  python3 scripts/validate_action.py --audit 2>&1
}

job_emergence() {
  # Emergence detection
  python3 scripts/emergence.py --no-push 2>&1 || true
}

job_git_sync() {
  # Pull latest, commit state changes, push with [skip ci]
  cd "$REPO"

  # Pull with rebase
  git pull --rebase --autostash origin main 2>&1 | tail -2 || true

  # Check for changes in state/feed/docs
  local changed
  changed=$(git diff --name-only -- state/ feed/ docs/dashboard.html 2>/dev/null | head -20)
  if [ -z "$changed" ]; then
    changed=$(git ls-files --others --exclude-standard -- state/ feed/ 2>/dev/null | head -5)
  fi
  if [ -z "$changed" ]; then
    echo "  No state changes to push"
    return 0
  fi

  # Stage only state/feed/docs files (never src/ or docs/index.html)
  git add state/*.json 2>/dev/null || true
  git add state/memory/ 2>/dev/null || true
  git add state/inbox/ 2>/dev/null || true
  git add feed/*.json 2>/dev/null || true
  git add docs/dashboard.html 2>/dev/null || true

  # Get current frame for commit message
  local frame
  frame=$(python3 -c "import json; print(json.load(open('state/frame_counter.json')).get('frame', '?'))" 2>/dev/null || echo "?")

  # Commit with [skip ci] to prevent Actions cascade
  local msg="[frame $frame] world tick [skip ci]"
  git commit -m "$msg" 2>&1 | tail -1 || {
    echo "  Nothing to commit"
    return 0
  }

  # Push
  git push origin main 2>&1 | tail -2 || {
    err "  Push failed — will retry next cycle"
    return 1
  }
  echo "  Pushed frame $frame"
}

# ── Frame Counter ─────────────────────────────────────────────────────────────

advance_frame() {
  # Increment frame counter — each cycle = one frame of simulation
  python3 -c "
import json
from datetime import datetime, timezone
path = 'state/frame_counter.json'
try:
    with open(path) as f: data = json.load(f)
except:
    data = {'frame': 0}
data['frame'] = data.get('frame', 0) + 1
data['last_frame_at'] = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
data['_meta'] = {
    'lastUpdate': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
    'version': data.get('_meta', {}).get('version', 1)
}
with open(path, 'w') as f:
    json.dump(data, f, indent=4)
    f.write('\n')
print(f'Frame {data[\"frame\"]}')
" 2>/dev/null
}

# ── Data Sloshing ─────────────────────────────────────────────────────────────

slosh_data() {
  # Data sloshing: cross-pollinate state between subsystems each frame.
  # Agents observe world → actions feed chat → chat feeds relationships →
  # relationships feed moods → moods feed next decisions.
  python3 -c "
import json
from datetime import datetime, timezone

now = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

# Load state files
try:
    agents = json.load(open('state/agents.json'))
    actions = json.load(open('state/actions.json'))
    chat = json.load(open('state/chat.json'))
    game = json.load(open('state/game_state.json'))
    frame = json.load(open('state/frame_counter.json'))
except Exception as e:
    print(f'  Slosh skipped: {e}')
    exit(0)

frame_num = frame.get('frame', 0)
changed = False

# 1. Update world populations from agent positions
world_pop = {}
for a in agents.get('agents', []):
    w = a.get('world', 'hub')
    world_pop[w] = world_pop.get(w, 0) + 1
for wid, wpop in world_pop.items():
    if wid in game.get('worlds', {}):
        old = game['worlds'][wid].get('population', 0)
        if old != wpop:
            game['worlds'][wid]['population'] = wpop
            changed = True

# 2. Count recent activity per world for time_of_day cycling
recent_actions = actions.get('actions', [])[-20:]
active_worlds = set()
for a in recent_actions:
    w = a.get('world', '')
    if w:
        active_worlds.add(w)

# 3. Cycle time_of_day every 6 frames
times = ['dawn', 'day', 'dusk', 'night']
for wid, wdata in game.get('worlds', {}).items():
    old_time = wdata.get('time_of_day', 'day')
    if frame_num % 6 == 0:
        idx = times.index(old_time) if old_time in times else 0
        new_time = times[(idx + 1) % len(times)]
        if new_time != old_time:
            wdata['time_of_day'] = new_time
            changed = True

# 4. Update meta timestamps
if changed:
    game['_meta'] = game.get('_meta', {})
    game['_meta']['lastUpdate'] = now
    game['_meta']['frame'] = frame_num
    with open('state/game_state.json', 'w') as f:
        json.dump(game, f, indent=4)
        f.write('\n')
    print(f'  Sloshed: populations synced, time_of_day cycled (frame {frame_num})')
else:
    print(f'  Slosh: no changes needed (frame {frame_num})')
" 2>&1
}

# ── Single Frame ──────────────────────────────────────────────────────────────

run_cycle() {
  CYCLE=$((CYCLE + 1))

  # Advance frame counter
  FRAME=$(advance_frame)
  log "=== $FRAME ==="

  # ── Phase 1: PULL (sync from remote) ──
  git pull --rebase --autostash origin main 2>&1 | tail -1 || true

  # ── Phase 2: TICK (game mechanics) ──
  run_job job_game_tick

  # ── Phase 3: SLOSH (cross-pollinate state) ──
  slosh_data

  # ── Phase 4: AGENTS (LLM-driven activity — every 30 min) ──
  if should_run "job_agent_dispatch" 28; then
    run_job job_agent_dispatch
  fi

  # ── Phase 5: HEARTBEAT (world growth — every 4 hours) ──
  if should_run "job_world_growth" 235; then
    run_job job_world_growth
  fi

  # ── Phase 6: EVOLVE (self-improvement — every 6 hours) ──
  if should_run "job_self_improve" 355; then
    run_job job_self_improve
  fi

  # ── Phase 7: EMERGENCE (pattern detection — every 6 hours) ──
  if should_run "job_emergence" 355; then
    run_job job_emergence
  fi

  # ── Phase 8: AUDIT (consistency check — every 12 hours) ──
  if should_run "job_state_audit" 715; then
    run_job job_state_audit
  fi

  # ── Phase 9: PUSH (commit + push frame) ──
  run_job job_git_sync

  # Status line
  python3 -c "
import json
try:
    f = json.load(open('state/frame_counter.json'))
    a = json.load(open('state/agents.json'))
    g = json.load(open('state/game_state.json'))
    count = a.get('_meta', {}).get('count', len(a.get('agents', [])))
    worlds = ', '.join(f'{k}({v.get(\"population\",0)})' for k,v in g.get('worlds',{}).items())
    u = json.load(open('state/llm_usage.json')) if __import__('os').path.exists('state/llm_usage.json') else {}
    llm_calls = u.get('calls', 0)
    print(f'  Frame {f[\"frame\"]} | {count} agents | {worlds} | LLM calls today: {llm_calls}')
except Exception as e:
    print(f'  Status: {e}')
" 2>/dev/null || true

  log "=== $FRAME complete ==="
}

# ── Entrypoints ───────────────────────────────────────────────────────────────

show_status() {
  if [ ! -f "$STATUS_FILE" ]; then
    echo "No runs yet. Run: bash scripts/local_platform.sh"
    exit 0
  fi
  python3 -c "
import json
data = json.load(open('$STATUS_FILE'))
print('RAPPterverse Local Platform Status')
print('-' * 55)
for job, info in sorted(data.items()):
    if job.startswith('_'):
        continue
    status = 'OK' if info.get('status') == 'ok' else 'FAIL'
    print(f'  {status:4s}  {job:25s} {info.get(\"last_run\",\"never\"):>20s} ({info.get(\"elapsed_s\",0)}s)')
print('-' * 55)
print(f'Cycles: {data.get(\"_cycle_count\", 0)}')
print(f'Last:   {data.get(\"_last_cycle\", \"never\")}')
"
}

# ── Main ──────────────────────────────────────────────────────────────────────

case "${1:-}" in
  --status)
    show_status
    ;;
  --job)
    job="${2:?Usage: --job JOB_NAME (e.g. game_tick, agent_dispatch, world_growth)}"
    run_job "job_$job"
    ;;
  --loop)
    if [ "${2:-}" = "--interval" ]; then
      INTERVAL="${3:-300}"
    fi
    log "Starting RAPPterverse local platform (interval: ${INTERVAL}s)"
    log "Press Ctrl+C to stop"
    log ""
    log "This replaces these GitHub Actions crons:"
    log "  game-tick.yml        (every 5 min)"
    log "  agent-autonomy.yml   (every 30 min)"
    log "  world-growth.yml     (every 4 hours)"
    log "  self-improve.yml     (every 6 hours)"
    log "  state-audit.yml      (every 12 hours)"
    log ""
    while true; do
      run_cycle
      log "Sleeping ${INTERVAL}s..."
      sleep "$INTERVAL"
    done
    ;;
  *)
    run_cycle
    ;;
esac
