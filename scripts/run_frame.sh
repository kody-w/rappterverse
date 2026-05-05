#!/usr/bin/env bash
# run_frame.sh — one tick of the substrate.
#
# This is the canonical "advance the world by one frame" entry point.
# Every phase below is the same substrate pattern (decision → state →
# next frame). Each phase is opt-in; pass --skip-<phase> to disable.
#
# Phases (in order):
#   0. advance-frame      Bumps state/frame_counter.json by 1. Skip with
#                         --dry-run or --skip-frame.
#   1. team-assign        Idempotent. Reseeds teams.json if missing/stale
#                         OR if --reassign-teams is passed.
#   2. combat-resolve     Reads unresolved act/challenge actions, applies
#                         HP damage and kill/respawn events.
#   3. frame-compile      --changed-only by default. Recompiles per-agent
#                         .lisp programs only for agents whose tactical
#                         signature shifted.
#   4. agent-dispatch     --all --brainstem with --max-agents N (default 5).
#                         Each agent runs its compiled program.
#   5. cleanup            Idempotent scrub of any pollution that snuck in.
#
# Usage:
#   bash scripts/run_frame.sh
#   bash scripts/run_frame.sh --max-agents 10
#   bash scripts/run_frame.sh --reassign-teams
#   bash scripts/run_frame.sh --dry-run
#   bash scripts/run_frame.sh --skip-combat --skip-cleanup
#   bash scripts/run_frame.sh --no-llm     # forces every agent to sleep
#
# Exits non-zero on any phase failure. State changes persist regardless
# of what fails AFTER them — phases are isolated.

set -euo pipefail
cd "$(dirname "$0")/.."

# ── flags ──
MAX_AGENTS=5
REASSIGN_TEAMS=false
DRY_RUN=false
SKIP_TEAMS=false
SKIP_COMBAT=false
SKIP_COMPILE=false
SKIP_DISPATCH=false
SKIP_CLEANUP=false
SKIP_FRAME=false
NO_LLM=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --max-agents)       MAX_AGENTS="$2"; shift 2 ;;
    --reassign-teams)   REASSIGN_TEAMS=true; shift ;;
    --dry-run)          DRY_RUN=true; shift ;;
    --skip-teams)       SKIP_TEAMS=true; shift ;;
    --skip-combat)      SKIP_COMBAT=true; shift ;;
    --skip-compile)     SKIP_COMPILE=true; shift ;;
    --skip-dispatch)    SKIP_DISPATCH=true; shift ;;
    --skip-cleanup)     SKIP_CLEANUP=true; shift ;;
    --skip-frame)       SKIP_FRAME=true; shift ;;
    --no-llm)           NO_LLM=true; shift ;;
    -h|--help)
      sed -n '/^#/p' "$0" | sed 's/^# \?//'
      exit 0 ;;
    *)
      echo "unknown flag: $1" >&2; exit 1 ;;
  esac
done

DRY_FLAG=""
if [[ "$DRY_RUN" == "true" ]]; then DRY_FLAG="--dry-run"; fi

NO_LLM_FLAG=""
if [[ "$NO_LLM" == "true" ]]; then NO_LLM_FLAG="--no-llm"; fi

# ── phase header ──
phase() {
  echo
  echo "════════════════════════════════════════════════════════════════"
  echo "▶ $1"
  echo "════════════════════════════════════════════════════════════════"
}

# 0. Frame counter — bump first so all state in this tick is "as of frame N+1".
#    Skipped on --dry-run and --skip-frame-counter. Mirrors local_platform.sh's
#    advance_frame so frame_counter.json keeps moving even when running this
#    script directly instead of the full local_platform loop.
if [[ "$DRY_RUN" != "true" && "$SKIP_FRAME" != "true" ]]; then
  phase "advance-frame"
  python3 -c "
import json
from datetime import datetime, timezone
path = 'state/frame_counter.json'
try:
    with open(path) as f: data = json.load(f)
except Exception:
    data = {'frame': 0}
data['frame'] = data.get('frame', 0) + 1
now = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
data['last_frame_at'] = now
data['_meta'] = {
    'lastUpdate': now,
    'version': data.get('_meta', {}).get('version', 1),
}
with open(path, 'w') as f:
    json.dump(data, f, indent=4)
    f.write('\n')
print(f'  frame {data[\"frame\"]} @ {now}')
"
fi

# 1. Teams ── only assign if missing or --reassign-teams
if [[ "$SKIP_TEAMS" != "true" ]]; then
  if [[ "$REASSIGN_TEAMS" == "true" || ! -f state/teams.json ]]; then
    phase "team-assign"
    python3 scripts/team_assign.py $DRY_FLAG
  else
    echo
    echo "▶ team-assign  (skipped — state/teams.json exists; "
    echo "                pass --reassign-teams to force)"
  fi
fi

# 2. Combat resolution
if [[ "$SKIP_COMBAT" != "true" ]]; then
  phase "combat-resolve"
  python3 scripts/combat_tick.py $DRY_FLAG
fi

# 3. Frame compile (selective recompile)
if [[ "$SKIP_COMPILE" != "true" ]]; then
  phase "frame-compile (--changed-only)"
  python3 scripts/frame_compile.py --changed-only --summary $DRY_FLAG
fi

# 4. Agent dispatch — agents run their compiled programs
if [[ "$SKIP_DISPATCH" != "true" ]]; then
  phase "agent-dispatch (--all --brainstem)"
  if [[ "$DRY_RUN" == "true" ]]; then
    python3 scripts/agent_dispatch.py --all --max-agents "$MAX_AGENTS" \
      --brainstem --dry-run $NO_LLM_FLAG --no-push
  else
    python3 scripts/agent_dispatch.py --all --max-agents "$MAX_AGENTS" \
      --brainstem $NO_LLM_FLAG --no-push
  fi
fi

# 5. Cleanup any pollution from this tick
if [[ "$SKIP_CLEANUP" != "true" ]]; then
  phase "cleanup-state"
  python3 scripts/cleanup_state.py $DRY_FLAG
fi

echo
echo "✓ frame complete"
