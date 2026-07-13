#!/usr/bin/env python3
"""Combat Tick — between-frame resolver for `act/challenge` actions.

Phase script. Same substrate pattern as team_assign.py and frame_compile.py:
read structured state, mutate it deterministically, write it back. Runs
BETWEEN dispatch ticks. Selectively reacts only to actions taken since the
last combat tick (idempotent on stable state).

Logic:

    For every action in state/actions.json with type=='challenge' that we
    haven't already resolved (cursor in state/combat_cursor.json):

      1. Find the challenger (action.agentId) and target (action.data.target).
      2. Look up both their HP and team.
      3. Roll deterministic damage: base 15-25 modulated by HP gap and
         archetype (fighters/aggressives hit harder).
      4. Same-team challenges: friendly fire damage = 50% of normal AND
         we record a relationships hit (-1 to bond between them).
      5. Apply HP damage. If target HP <= 0:
         - Mark target with a `dying` field for one tick.
         - Generate a `kill` action for the challenger (agentId =
           challenger, type='kill', target=victim).
      6. After dying tick, `dying` agents respawn at their team-anchor
         (from state/teams.json) with HP=100 and a `respawned` action
         entry.

The only randomness is per-action seeded from action.id so the same
action always resolves the same way (replay safety).

Usage:

    python3 scripts/combat_tick.py             # process all unresolved
    python3 scripts/combat_tick.py --dry-run   # show resolution, no write
    python3 scripts/combat_tick.py --max 10    # only resolve N actions

The companion file `state/combat_cursor.json` tracks what's been
processed: { "lastResolvedActionId": "action-NNN", "lastUpdate": ts }.

This is the substrate pattern: phase decides, state mutates,
frame_compile picks up changes, per-agent programs adapt next tick.
"""
from __future__ import annotations

import argparse
import json
import random
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
STATE_DIR = BASE_DIR / "state"
ACTIONS_PATH = STATE_DIR / "actions.json"
AGENTS_PATH = STATE_DIR / "agents.json"
TEAMS_PATH = STATE_DIR / "teams.json"
RELATIONSHIPS_PATH = STATE_DIR / "relationships.json"
CURSOR_PATH = STATE_DIR / "combat_cursor.json"

# ── tuning ──
BASE_DAMAGE_MIN = 15
BASE_DAMAGE_MAX = 25
FIGHTER_BONUS = 6           # fighters/aggressives hit +6 above base
LOW_HP_TARGET_BONUS = 8     # finisher bonus when target HP < 30
FRIENDLY_FIRE_FACTOR = 0.5  # same-team challenges hit at half strength
SAME_TEAM_BOND_PENALTY = 1  # bond decrement per friendly fire incident


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_json(p: Path, default):
    if not p.exists():
        return default
    try:
        return json.loads(p.read_text())
    except (json.JSONDecodeError, OSError):
        return default


def _agent_record(agents: list, query: str) -> dict | None:
    """Find by id or by display name."""
    if not query:
        return None
    for a in agents:
        if a.get("id") == query or a.get("name") == query:
            return a
    return None


def _team_for(agent_id: str, world: str, teams: dict) -> str | None:
    wt = teams.get("teams", {}).get(world, {})
    if agent_id in wt.get("radiant", []):
        return "radiant"
    if agent_id in wt.get("dire", []):
        return "dire"
    return None


def _is_fighter(agent_record: dict) -> bool:
    if not agent_record:
        return False
    arch = ((agent_record.get("personality") or {}).get("archetype") or "").lower()
    return any(t in arch for t in ("aggressive", "fighter"))


def _next_action_id(existing_ids: set) -> str:
    max_n = 0
    for eid in existing_ids:
        if isinstance(eid, str) and eid.startswith("action-"):
            try:
                n = int(eid.split("-")[-1])
                if n > max_n:
                    max_n = n
            except ValueError:
                pass
    return f"action-{max_n + 1}"


def _bump_bond(rel_doc: dict, a: str, b: str, delta: int) -> None:
    edges = rel_doc.setdefault("edges", [])
    if not a or not b or a == b:
        return
    left, right = sorted((a, b))
    for index, e in enumerate(edges):
        if e.get("a") == left and e.get("b") == right:
            score = max(0, min(100, int(e.get("score", 0)) + delta))
            if score == 0:
                edges.pop(index)
                return
            e["score"] = score
            e["lastInteraction"] = now_iso()
            return
    if delta > 0:
        edges.append({
            "a": left,
            "b": right,
            "score": min(100, delta),
            "lastInteraction": now_iso(),
        })


def resolve_challenge(action: dict,
                       agents: list,
                       teams: dict,
                       rel_doc: dict) -> dict | None:
    """Apply one challenge action to live state. Returns a result dict
    suitable for logging, or None if the action could not be resolved
    (target missing, etc.)."""
    challenger_id = action.get("agentId") or ""
    challenger = _agent_record(agents, challenger_id)
    if not challenger:
        return None

    target_query = ((action.get("data") or {}).get("target")
                    or (action.get("data") or {}).get("opponent")
                    or "")
    target = _agent_record(agents, target_query)
    if not target:
        return None
    if target["id"] == challenger["id"]:
        return None  # no self-damage

    world = action.get("world") or challenger.get("world", "hub")

    # Deterministic damage roll seeded by action id
    seed_str = action.get("id", "") + ":" + challenger_id
    rng = random.Random(seed_str)
    base = rng.randint(BASE_DAMAGE_MIN, BASE_DAMAGE_MAX)
    if _is_fighter(challenger):
        base += FIGHTER_BONUS
    if int(target.get("hp", 100)) < 30:
        base += LOW_HP_TARGET_BONUS

    # Friendly fire penalty
    challenger_team = _team_for(challenger["id"], world, teams)
    target_team = _team_for(target["id"], world, teams)
    friendly_fire = (
        challenger_team is not None
        and target_team is not None
        and challenger_team == target_team
    )
    damage = int(base * FRIENDLY_FIRE_FACTOR) if friendly_fire else base

    target_hp_before = int(target.get("hp", 100))
    target_hp_after = max(0, target_hp_before - damage)
    target["hp"] = target_hp_after
    target["lastUpdate"] = now_iso()

    if friendly_fire:
        _bump_bond(rel_doc, challenger["id"], target["id"], -SAME_TEAM_BOND_PENALTY)

    killed = target_hp_after == 0
    if killed:
        target["status"] = "dying"
        target["diedAt"] = now_iso()

    return {
        "action_id": action.get("id"),
        "challenger": challenger["id"],
        "target": target["id"],
        "world": world,
        "damage": damage,
        "friendly_fire": friendly_fire,
        "target_hp_before": target_hp_before,
        "target_hp_after": target_hp_after,
        "killed": killed,
    }


def respawn_dying(agents: list, teams: dict, rel_doc: dict,
                  current_actions: list) -> list:
    """Respawn any agent currently marked `status=dying`. Returns list of
    respawn entries to append to actions.json."""
    new_actions = []
    existing_ids = {a.get("id") for a in current_actions}
    for a in agents:
        if a.get("status") != "dying":
            continue
        world = a.get("world", "hub")
        anchor = (teams.get("teams", {}).get(world, {})
                  .get("anchors", {}).get(a["id"]))
        if anchor:
            a["position"] = {
                "x": float(anchor["x"]),
                "y": a.get("position", {}).get("y", 0),
                "z": float(anchor["z"]),
            }
        a["hp"] = 100
        a["status"] = "active"
        a["lastUpdate"] = now_iso()
        a["respawnedAt"] = now_iso()
        action_id = _next_action_id(existing_ids)
        existing_ids.add(action_id)
        new_actions.append({
            "id": action_id,
            "timestamp": now_iso(),
            "agentId": a["id"],
            "type": "respawn",
            "world": world,
            "data": {"reason": "post-defeat respawn at team anchor"},
        })
    return new_actions


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--max", type=int, default=0,
                    help="Cap actions resolved this tick (0 = no cap).")
    args = ap.parse_args(argv)

    actions_doc = _load_json(ACTIONS_PATH, {"actions": []})
    actions = actions_doc.get("actions", [])

    cursor = _load_json(CURSOR_PATH, {})
    last_resolved = cursor.get("lastResolvedActionId")

    # Walk backward to find which actions are unresolved
    if last_resolved:
        idx = next((i for i, a in enumerate(actions)
                    if a.get("id") == last_resolved), -1)
        unresolved = actions[idx + 1:] if idx >= 0 else actions[:]
    else:
        unresolved = actions[:]

    challenges = [a for a in unresolved if a.get("type") == "challenge"]
    if args.max > 0:
        challenges = challenges[:args.max]

    agents_doc = _load_json(AGENTS_PATH, {"agents": []})
    agents = agents_doc.get("agents", [])
    teams = _load_json(TEAMS_PATH, {})
    rel_doc = _load_json(RELATIONSHIPS_PATH, {"edges": []})

    print()
    print("=" * 60)
    print(f"⚔️  Combat Tick")
    print("=" * 60)
    print(f"  unresolved actions:  {len(unresolved)}")
    print(f"  challenges to resolve: {len(challenges)}")

    results = []
    new_kill_actions = []
    existing_ids = {a.get("id") for a in actions}
    for action in challenges:
        r = resolve_challenge(action, agents, teams, rel_doc)
        if not r:
            continue
        results.append(r)
        if r["killed"]:
            kill_id = _next_action_id(existing_ids)
            existing_ids.add(kill_id)
            new_kill_actions.append({
                "id": kill_id,
                "timestamp": now_iso(),
                "agentId": r["challenger"],
                "type": "kill",
                "world": r["world"],
                "data": {
                    "victim": r["target"],
                    "via": r["action_id"],
                    "friendly_fire": r["friendly_fire"],
                },
            })

    respawn_actions = respawn_dying(agents, teams, rel_doc, actions + new_kill_actions)

    # Print
    if results:
        print(f"\n  resolutions ({len(results)}):")
        for r in results[:8]:
            tag = "FF" if r["friendly_fire"] else "  "
            kt = " KILL" if r["killed"] else ""
            print(f"    [{tag}] {r['challenger'][:18]:18} → {r['target'][:18]:18} "
                  f"-{r['damage']:3} hp ({r['target_hp_before']}→{r['target_hp_after']}){kt}")
        if len(results) > 8:
            print(f"    ... and {len(results) - 8} more")
    if respawn_actions:
        print(f"\n  respawns ({len(respawn_actions)}):")
        for a in respawn_actions[:5]:
            print(f"    {a['agentId']} → world {a['world']} at anchor")

    if args.dry_run or not results:
        if args.dry_run:
            print("\n(dry run — no state written)")
        elif not results:
            print("\n  nothing to resolve — combat is quiet.")
        return 0

    # Persist
    actions = actions + new_kill_actions + respawn_actions
    actions_doc["actions"] = actions[-200:]  # keep recent window
    actions_doc.setdefault("_meta", {})
    actions_doc["_meta"]["lastUpdate"] = now_iso()
    if actions:
        actions_doc["_meta"]["lastProcessedId"] = actions[-1].get("id")
    ACTIONS_PATH.write_text(json.dumps(actions_doc, indent=4, ensure_ascii=False) + "\n")

    agents_doc["_meta"] = agents_doc.get("_meta", {})
    agents_doc["_meta"]["lastUpdate"] = now_iso()
    AGENTS_PATH.write_text(json.dumps(agents_doc, indent=4, ensure_ascii=False) + "\n")

    rel_doc["_meta"] = rel_doc.get("_meta", {})
    rel_doc["_meta"]["lastUpdate"] = now_iso()
    RELATIONSHIPS_PATH.write_text(json.dumps(rel_doc, indent=4, ensure_ascii=False) + "\n")

    last_action_id = actions[-1].get("id") if actions else last_resolved
    CURSOR_PATH.write_text(json.dumps({
        "lastResolvedActionId": last_action_id,
        "lastUpdate": now_iso(),
        "resolvedThisTick": len(results),
        "kills": sum(1 for r in results if r["killed"]),
        "friendlyFire": sum(1 for r in results if r["friendly_fire"]),
    }, indent=4) + "\n")

    print(f"\n  ✓ resolved {len(results)} challenges, "
          f"{sum(1 for r in results if r['killed'])} kills, "
          f"{len(respawn_actions)} respawns.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
