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

# ── Helpers ───────────────────────────────────────────────────────────────────

log() { echo "[$(date '+%H:%M:%S')] $*"; }
err() { echo "[$(date '+%H:%M:%S')] ERROR: $*" >&2; }

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
    data = json.load(open(path))
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
    data = json.load(open('$STATUS_FILE'))
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
  # Ambient agent activity — up to 10 random agents
  # Original: agent-autonomy.yml every 30 min
  python3 scripts/build_agent_registry.py 2>&1
  python3 scripts/agent_dispatch.py --all --max-agents 10 --no-push 2>&1
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
    # Also check untracked files in state/
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

  # Commit with [skip ci] to prevent Actions cascade
  local msg="[local] platform sync cycle $CYCLE [skip ci]"
  git commit -m "$msg" 2>&1 | tail -1 || {
    echo "  Nothing to commit"
    return 0
  }

  # Push
  git push origin main 2>&1 | tail -2 || {
    err "  Push failed — will retry next cycle"
    return 1
  }
  echo "  Pushed state changes"
}

# ── Single Cycle ──────────────────────────────────────────────────────────────

run_cycle() {
  CYCLE=$((CYCLE + 1))
  log "=== Cycle $CYCLE ==="

  # Every cycle (5 min): game tick
  run_job job_game_tick

  # Every 30 min: agent dispatch
  if should_run "job_agent_dispatch" 28; then
    run_job job_agent_dispatch
  fi

  # Every 4 hours: world heartbeat
  if should_run "job_world_growth" 235; then
    run_job job_world_growth
  fi

  # Every 6 hours: self-improvement
  if should_run "job_self_improve" 355; then
    run_job job_self_improve
  fi

  # Every 6 hours: emergence detection
  if should_run "job_emergence" 355; then
    run_job job_emergence
  fi

  # Every 12 hours: state audit
  if should_run "job_state_audit" 715; then
    run_job job_state_audit
  fi

  # Always last: git sync
  run_job job_git_sync

  # Status line
  python3 -c "
import json
try:
    a = json.load(open('state/agents.json'))
    g = json.load(open('state/game_state.json'))
    count = a.get('_meta', {}).get('count', len(a.get('agents', [])))
    print(f'  Status: {count} agents | game_state version {g.get(\"_meta\",{}).get(\"version\",\"?\")}')
except Exception as e:
    print(f'  Status: (could not read state: {e})')
" 2>/dev/null || true

  log "=== Cycle $CYCLE complete ==="
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
