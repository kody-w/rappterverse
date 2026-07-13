#!/bin/bash
# local_platform.sh — Full local replacement for GitHub Actions
#
# Runs the entire RAPPterverse pipeline locally on a schedule. When running,
# this script replaces all cron-based GitHub Actions: game-tick, agent-autonomy,
# world-growth, self-improve, state-audit. Every run is isolated in a disposable
# worktree and publishes through the durable state-PR reconciler.
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
#   git_sync         — every cycle   (validated PR + durable reconciliation)

set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"

if [ -z "${RAPPTERVERSE_ISOLATED:-}" ] && [ "${1:-}" != "--status" ]; then
  WORKTREE="$(mktemp -d /tmp/rappterverse-platform.XXXXXX)"
  rmdir "$WORKTREE"
  cleanup_worktree() {
    git -C "$REPO" worktree remove --force "$WORKTREE" >/dev/null 2>&1 || true
  }
  trap cleanup_worktree EXIT INT TERM
  git -C "$REPO" fetch --no-tags origin main
  git -C "$REPO" worktree add --detach "$WORKTREE" origin/main
  set +e
  RAPPTERVERSE_ISOLATED=1 \
  RAPPTERVERSE_SHARED_REPO="$REPO" \
  RAPPTERVERSE_LOG_DIR="$REPO/logs" \
    bash "$WORKTREE/scripts/local_platform.sh" "$@"
  status=$?
  set -e
  exit "$status"
fi

cd "$REPO"

STATE_DIR="state"
LOG_DIR="${RAPPTERVERSE_LOG_DIR:-$REPO/logs}"
STATUS_FILE="$LOG_DIR/local_platform_status.json"
PUBLICATION_BLOCK="$LOG_DIR/publication-blocked"
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
  local output_file
  output_file=$(mktemp)
  log "Running: $job"
  set +e
  ( set -e; "$@" ) >"$output_file" 2>&1
  local status=$?
  set -e
  tail -5 "$output_file"
  rm -f "$output_file"
  if [ "$status" -eq 0 ]; then
    local elapsed=$(( $(date +%s) - start ))
    log "  Done: $job (${elapsed}s)"
    update_status "$job" "ok" "$elapsed"
    return 0
  else
    err "  Failed: $job"
    update_status "$job" "failed" "0"
    touch "$PUBLICATION_BLOCK"
    return "$status"
  fi
  return 0
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
now = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
entry = data.get('$job', {})
entry.update({
    'status': '$status',
    'elapsed_s': int('$elapsed'),
    'last_attempt': now,
    'last_run': now,
})
if '$status' == 'ok':
    entry['last_success'] = now
data['$job'] = entry
data['_last_cycle'] = now
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
    job_state = data.get('$job', {})
    if job_state.get('status') != 'ok':
        sys.exit(0)
    last = job_state.get('last_success') or job_state.get('last_run', '')
    if not last:
        sys.exit(0)
    last_dt = datetime.fromisoformat(last.replace('Z', '+00:00'))
    if datetime.now(timezone.utc) - last_dt > timedelta(minutes=$interval_minutes):
        sys.exit(0)
    sys.exit(1)
except (OSError, json.JSONDecodeError, ValueError, TypeError):
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
  # Ambient agent activity — ALL agents, via the GitHub Copilot CLI
  # Original: agent-autonomy.yml every 30 min (was capped at 10)
  python3 scripts/build_agent_registry.py 2>&1 || return $?
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

  log "  [heartbeat] Validate state..."
  if ! python3 scripts/reconcile_derived_state.py 2>&1; then
    err "  Derived-state reconciliation failed"
    failed=1
  fi
  if ! python3 scripts/validate_action.py --validate-state 2>&1; then
    err "  Canonical state validation failed"
    failed=1
  fi

  log "  [heartbeat] PII scan..."
  if ! python3 scripts/pii_scan.py --paths state feed 2>&1; then
    err "  PII scan failed"
    failed=1
  fi

  return $failed
}

job_self_improve() {
  # evolve-001 self-improvement cycle
  # Original: self-improve.yml every 6 hours
  python3 scripts/build_agent_registry.py 2>&1 || return $?
  python3 scripts/self_improve.py --no-push 2>&1 || return $?
  rm -f state/evolution_pr_body.md
}

job_state_audit() {
  # Publication-safe structural state check
  # Original: state-audit.yml every 12 hours
  python3 scripts/validate_action.py --validate-state 2>&1
}

job_emergence() {
  # Emergence detection
  python3 scripts/emergence.py --no-push 2>&1
}

wait_for_reconciliation() {
  local head_sha="$1"
  local pr_url="$2"
  local attempts=0
  while true; do
    local status
    if ! status=$(gh api "repos/${GH_REPO:-kody-w/rappterverse}/commits/$head_sha/status" \
      --jq '[.statuses[] | select(.context == "state-reconciler")][0].state // ""'); then
      err "  Unable to query reconciliation status: $pr_url"
      return 1
    fi
    if [ "$status" = "success" ]; then
      return 0
    fi
    if [ "$status" = "failure" ] || [ "$status" = "error" ]; then
      err "  Reconciler rejected proposal: $pr_url"
      return 1
    fi
    local pr_state
    if ! pr_state=$(gh pr view "$pr_url" \
      --repo "${GH_REPO:-kody-w/rappterverse}" \
      --json state \
      --jq .state); then
      err "  Unable to query proposal state: $pr_url"
      return 1
    fi
    if [ "$pr_state" != "OPEN" ]; then
      err "  Proposal closed without successful reconciliation: $pr_url"
      return 1
    fi
    attempts=$((attempts + 1))
    if [ $((attempts % 12)) -eq 0 ]; then
      log "  Still waiting for durable reconciliation: $pr_url"
      gh workflow run state-drain.yml --repo "${GH_REPO:-kody-w/rappterverse}" --ref main || true
    fi
    sleep 5
  done
}

resume_pending_local_proposals() {
  local pending
  if ! pending=$(REPOSITORY_OWNER="${REPOSITORY_OWNER:-kody-w}" gh pr list \
    --repo "${GH_REPO:-kody-w/rappterverse}" \
    --state open \
    --limit 100 \
    --json number,author,baseRefName,headRefName,headRefOid,isCrossRepository,isDraft,url \
    --jq '.[] |
      select(.headRefName | startswith("auto/local-frame-")) |
      select(.baseRefName == "main" and .isDraft == false and .isCrossRepository == false) |
      select(.author.login == env.REPOSITORY_OWNER) |
      [.number,.headRefName,.headRefOid,.url] | @tsv'); then
    err "Unable to query pending local-platform proposals"
    return 1
  fi
  [ -z "$pending" ] && return 0

  log "Resuming pending local-platform proposal before advancing"
  gh workflow run state-drain.yml --repo "${GH_REPO:-kody-w/rappterverse}" --ref main || true
  while IFS=$'\t' read -r number branch head_sha pr_url; do
    [ -z "$head_sha" ] && continue
    local files_ok
    if ! files_ok=$(gh pr view "$number" \
      --repo "${GH_REPO:-kody-w/rappterverse}" \
      --json files \
      --jq 'all(.files[]; .path as $p |
        (($p | startswith("state/")) or ($p | startswith("worlds/")) or ($p | startswith("feed/"))))'); then
      err "Unable to inspect pending proposal #$number"
      return 1
    fi
    [ "$files_ok" = "true" ] || continue
    if ! wait_for_reconciliation "$head_sha" "$pr_url"; then
      return 1
    fi
    git push origin --delete "$branch" >/dev/null 2>&1 || true
  done <<< "$pending"
}

job_git_sync() {
  # Publish state through the same durable PR consensus path as external actors.
  cd "$REPO"

  # Check for canonical state changes only. Trusted reconciliation regenerates
  # README, snapshots, and chronicle artifacts from the accepted state.
  local changed
  changed=$(git diff --name-only -- state/ worlds/ feed/ 2>/dev/null | head -20)
  if [ -z "$changed" ]; then
    changed=$(git ls-files --others --exclude-standard -- state/ worlds/ feed/ 2>/dev/null | head -5)
  fi
  if [ -z "$changed" ]; then
    echo "  No state changes to push"
    return 0
  fi

  if ! python3 scripts/reconcile_derived_state.py 2>&1; then
    touch "$PUBLICATION_BLOCK"
    err "  Publication blocked: derived-state reconciliation failed"
    return 1
  fi

  if ! python3 scripts/validate_action.py --validate-state 2>&1; then
    touch "$PUBLICATION_BLOCK"
    err "  Publication blocked: canonical state validation failed"
    return 1
  fi
  if ! python3 scripts/pii_scan.py --paths state worlds feed 2>&1; then
    touch "$PUBLICATION_BLOCK"
    err "  Publication blocked: PII scan failed"
    return 1
  fi

  # Stage only canonical state. The reconciler owns generated presentation files.
  git add state/*.json 2>/dev/null || true
  git add state/memory/ 2>/dev/null || true
  git add state/inbox/ 2>/dev/null || true
  git add state/programs/ 2>/dev/null || true
  git add state/souls/ 2>/dev/null || true
  git add worlds/*/*.json 2>/dev/null || true
  git add feed/*.json 2>/dev/null || true
  if git diff --cached --quiet; then
    echo "  No canonical state changes to queue"
    return 0
  fi

  local frame
  frame=$(python3 -c "import json; print(json.load(open('state/frame_counter.json')).get('frame', '?'))" 2>/dev/null || echo "?")
  local branch="auto/local-frame-${frame}-$(date -u +%Y%m%d-%H%M%S)-$$"
  git config user.name "rappterverse-local-platform" || return $?
  git config user.email "41898282+github-actions[bot]@users.noreply.github.com" || return $?
  git switch -c "$branch" || return $?
  git commit -m "[frame $frame] local platform proposal" || return $?
  local head_sha
  head_sha=$(git rev-parse HEAD)
  git push --set-upstream origin "$branch" || return $?
  local pr_url
  if ! pr_url=$(gh pr create \
    --repo "${GH_REPO:-kody-w/rappterverse}" \
    --base main \
    --head "$branch" \
    --title "[frame $frame] Local platform proposal" \
    --body "Isolated local-platform frame. Publication is owned by the durable state reconciler."); then
    return 1
  fi
  gh workflow run state-drain.yml --repo "${GH_REPO:-kody-w/rappterverse}" --ref main || return $?

  if ! wait_for_reconciliation "$head_sha" "$pr_url"; then
    return 1
  fi
  git fetch --no-tags origin main || return $?
  git switch --detach origin/main || return $?
  git push origin --delete "$branch" >/dev/null 2>&1 || true
  rm -f "$PUBLICATION_BLOCK"
  echo "  Reconciled frame $frame via $pr_url"
  return 0
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
  # Data sloshing + Lisp soul compilation.
  # Reads all state, cross-pollinates, then compiles per-agent S-expression
  # routines into game_state.worlds[wid].routines[] for the RappterVM.
  python3 scripts/slosh_lisp.py 2>&1
}

_slosh_data_legacy() {
  # Legacy inline version (unused — kept for reference)
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

discard_failed_cycle() {
  git reset --hard HEAD >/dev/null
  git clean -fd -- state worlds feed agents >/dev/null
  git fetch --no-tags origin main >/dev/null 2>&1 || true
  git switch --detach origin/main >/dev/null 2>&1 || true
  rm -f "$PUBLICATION_BLOCK"
}

run_cycle() {
  CYCLE=$((CYCLE + 1))
  local cycle_failed=0

  # ── Phase 1: SYNC CLEAN ISOLATED BASE ──
  if ! git fetch --no-tags origin main; then
    err "Unable to fetch canonical main"
    return 1
  fi
  if ! resume_pending_local_proposals; then
    err "A prior local-platform proposal requires intervention"
    return 1
  fi
  git fetch --no-tags origin main
  if ! git switch --detach origin/main >/dev/null; then
    err "Unable to reset isolated frame worktree"
    return 1
  fi
  if [ -n "$(git status --porcelain -- state worlds feed agents)" ]; then
    err "Isolated frame worktree is dirty before the cycle"
    discard_failed_cycle
    return 1
  fi

  # Advance only after synchronization succeeds.
  FRAME=$(advance_frame)
  log "=== $FRAME ==="

  # ── Phase 2: TICK (game mechanics) ──
  if ! run_job job_game_tick; then cycle_failed=1; fi

  # ── Phase 3: SLOSH (cross-pollinate state) ──
  if ! slosh_data; then
    err "  Data slosh failed"
    touch "$PUBLICATION_BLOCK"
    cycle_failed=1
  fi

  # ── Phase 4: AGENTS (LLM-driven activity — every 30 min) ──
  if should_run "job_agent_dispatch" 28; then
    if ! run_job job_agent_dispatch; then cycle_failed=1; fi
  fi

  # ── Phase 5: HEARTBEAT (world growth — every 4 hours) ──
  if should_run "job_world_growth" 235; then
    if ! run_job job_world_growth; then cycle_failed=1; fi
  fi

  # ── Phase 6: EVOLVE (self-improvement — every 6 hours) ──
  if should_run "job_self_improve" 355; then
    if ! run_job job_self_improve; then cycle_failed=1; fi
  fi

  # ── Phase 7: EMERGENCE (pattern detection — every 6 hours) ──
  if should_run "job_emergence" 355; then
    if ! run_job job_emergence; then cycle_failed=1; fi
  fi

  # ── Phase 8: AUDIT (consistency check — every 12 hours) ──
  if should_run "job_state_audit" 715; then
    if ! run_job job_state_audit; then cycle_failed=1; fi
  fi

  # ── Phase 9: PUBLISH (queue validated frame PR) ──
  if [ "$cycle_failed" -eq 0 ]; then
    if ! run_job job_git_sync; then cycle_failed=1; fi
  else
    err "  Publication skipped because this cycle failed"
  fi

  if [ "$cycle_failed" -ne 0 ]; then
    discard_failed_cycle
  fi

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
  return "$cycle_failed"
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
    print(f'  {status:4s}  {job:25s} '
          f'{info.get(\"last_success\", \"never\"):>20s} '
          f'(attempt {info.get(\"last_attempt\", \"never\")}, {info.get(\"elapsed_s\",0)}s)')
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
    run_job job_git_sync
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
      if ! run_cycle; then
        err "Cycle failed; retained publication block and will retry"
      fi
      log "Sleeping ${INTERVAL}s..."
      sleep "$INTERVAL"
    done
    ;;
  *)
    run_cycle
    ;;
esac
