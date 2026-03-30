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

# ── LISP SOUL COMPILER ──
# Data slosh → S-expression programs → RappterVM evaluates at 20Hz
#
# This is the bridge between frame-based LLM thought and continuous
# mid-frame sentience. The slosh reads the ENTIRE agent state — their
# actions, conversations, relationships, goals, personality, position —
# and compiles it into pure Lisp. The VM evaluates this Lisp between
# frames. If no new frame ever arrives, agents keep living from these
# programs. The world goes on.
#
# Each routine is a REAL S-expression — not a string template. The VM
# parses it once and evaluates the AST at 20Hz. Data is code.

try:
    rels = json.load(open('state/relationships.json'))
except:
    rels = {'edges': []}

# Load memories for goal-driven behavior
import glob as _glob
memories = {}
for mf in _glob.glob('state/memory/*.json'):
    try:
        md = json.load(open(mf))
        mid = mf.split('/')[-1].replace('.json', '')
        memories[mid] = md
    except:
        pass

for wid, wdata in game.get('worlds', {}).items():
    routines = []
    world_agents = [a for a in agents.get('agents', []) if a.get('world') == wid]
    world_chat = [m for m in chat.get('messages', [])[-30:] if m.get('world') == wid]
    world_actions = [a for a in actions.get('actions', [])[-50:] if a.get('world') == wid]

    # Index: who talked to whom
    chat_graph = {}
    for m in world_chat:
        aid = m.get('author', {}).get('id', '')
        if aid:
            chat_graph.setdefault(aid, set())
            for m2 in world_chat:
                aid2 = m2.get('author', {}).get('id', '')
                if aid2 and aid2 != aid:
                    chat_graph[aid].add(aid2)

    # Index: relationship edges per agent
    rel_graph = {}
    for edge in rels.get('edges', []):
        a, b, score = edge.get('a',''), edge.get('b',''), edge.get('score', 0)
        if score >= 2:
            rel_graph.setdefault(a, []).append((b, score))
            rel_graph.setdefault(b, []).append((a, score))

    for ag in world_agents:
        aid = ag.get('id', '')
        if not aid:
            continue
        pos = ag.get('position', {})
        px, pz = pos.get('x', 0), pos.get('z', 0)
        mood = ag.get('mood', ag.get('state', 'neutral'))
        mem = memories.get(aid, {})
        goals = [g for g in mem.get('goals', []) if g.get('status') == 'active']
        traits = ag.get('traits', {})

        # ── Compose the agent's soul program as S-expressions ──
        exprs = []

        # (1) HOME ORBIT — patrol around current position
        #     (do (if (< (mod (floor (elapsed)) 20) 10)
        #             (wander "aid" radius)
        #             (move-toward "aid" home-x home-z 0.01)))
        wander_radius = 3 + (traits.get('explorer', 0) * 8)  # explorers wander further
        exprs.append(
            f'(if (< (mod (floor (elapsed)) 20) 10) '
            f'(wander \"{aid}\" {wander_radius:.1f}) '
            f'(move-toward \"{aid}\" {px:.1f} {pz:.1f} 0.01))'
        )

        # (2) SOCIAL GRAVITY — approach conversation partners
        partners = list(chat_graph.get(aid, set()))
        for p in partners[:2]:  # max 2 social pulls
            exprs.append(
                f'(if (> (distance \"{aid}\" \"{p}\") 5) '
                f'(move-toward \"{aid}\" '
                f'(get (agent-pos \"{p}\") \"x\") '
                f'(get (agent-pos \"{p}\") \"z\") '
                f'{0.010 + traits.get("social", 0) * 0.008:.3f}) nil)'
            )

        # (3) BOND MAGNETISM — gravitate toward strong relationships
        agent_rels = sorted(rel_graph.get(aid, []), key=lambda x: -x[1])
        for partner, score in agent_rels[:1]:  # strongest bond
            strength = min(score / 20, 0.015)
            exprs.append(
                f'(if (and (> (distance \"{aid}\" \"{partner}\") 4) '
                f'(< (mod (floor (elapsed)) 30) 15)) '
                f'(move-toward \"{aid}\" '
                f'(get (agent-pos \"{partner}\") \"x\") '
                f'(get (agent-pos \"{partner}\") \"z\") '
                f'{strength:.4f}) '
                f'(face-toward \"{aid}\" '
                f'(get (agent-pos \"{partner}\") \"x\") '
                f'(get (agent-pos \"{partner}\") \"z\")))'
            )

        # (4) GOAL DRIVE — active goals influence movement
        for goal in goals[:1]:
            gtype = goal.get('type', '')
            if gtype in ('explore', 'wander'):
                exprs.append(f'(if (= (mod (floor (elapsed)) 8) 0) (wander \"{aid}\" 12) nil)')
            elif gtype in ('social', 'generosity'):
                exprs.append(
                    f'(if (= (mod (floor (elapsed)) 12) 0) '
                    f'(let (near (nearest-agent \"{aid}\")) '
                    f'(if near (move-toward \"{aid}\" '
                    f'(get (agent-pos near) \"x\") '
                    f'(get (agent-pos near) \"z\") 0.02) nil)) nil)'
                )
            elif gtype in ('commerce', 'compete', 'combat'):
                exprs.append(
                    f'(if (< (mod (floor (elapsed)) 6) 3) '
                    f'(emote \"{aid}\" \"look-around\") nil)'
                )

        # (5) PERSONALITY EXPRESSION — traits shape idle behavior
        if traits.get('fighter', 0) > 0.4:
            exprs.append(f'(if (< (rand) 0.003) (emote \"{aid}\" \"bounce\") nil)')
        if traits.get('social', 0) > 0.4:
            exprs.append(f'(if (< (rand) 0.005) (emote \"{aid}\" \"nod\") nil)')

        # (6) MOOD COLORING — anxiety makes them fidgety, friendly makes them open
        if mood in ('anxious', 'desperate'):
            exprs.append(f'(if (< (player-distance \"{aid}\") 6) (wander \"{aid}\" 8) nil)')
        elif mood in ('friendly', 'excited'):
            exprs.append(
                f'(if (< (player-distance \"{aid}\") 10) '
                f'(face-toward \"{aid}\" '
                f'(get (player-pos) \"x\") (get (player-pos) \"z\")) nil)'
            )

        if exprs:
            # Wrap all expressions in a (do ...) block — one program per agent
            program = '(do ' + ' '.join(exprs) + ')'
            routines.append({'agentId': aid, 'program': program})
            changed = True

    wdata['routines'] = routines[:60]  # Cap per world

# 5. Update meta timestamps
if changed:
    game['_meta'] = game.get('_meta', {})
    game['_meta']['lastUpdate'] = now
    game['_meta']['frame'] = frame_num
    with open('state/game_state.json', 'w') as f:
        json.dump(game, f, indent=4)
        f.write('\n')
    routine_count = sum(len(w.get('routines', [])) for w in game.get('worlds', {}).values())
    print(f'  Sloshed: pops synced, time cycled, {routine_count} Lisp routines compiled (frame {frame_num})')
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
