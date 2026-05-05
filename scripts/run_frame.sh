#!/usr/bin/env bash
# run_frame.sh — one tick of the substrate.
#
# This is the canonical "advance the world by one frame" entry point.
# Every phase below is the same substrate pattern (decision → state →
# next frame). Each phase is opt-in; pass --skip-<phase> to disable.
#
# Phases (in order):
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
# NOTE: This script does NOT advance state/frame_counter.json. The frame
# number is the maximum [frame N] in git history (see scripts/frame_clock.py).
# The metaverse's pump is the source of truth for frames. Running this
# script tunes the substrate within whatever frame is current.
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

# 0. Frame clock — sync state/frame_counter.json to the highest [frame N]
#    found in git history. Read-only relative to the universal clock; just
#    keeps the on-disk cache honest. Safe to skip; pump on `frames` branch
#    is the actual source of truth.
if [[ "$DRY_RUN" != "true" ]]; then
  phase "frame-clock (sync from git log)"
  python3 scripts/frame_clock.py sync || true
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
