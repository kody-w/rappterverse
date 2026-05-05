#!/usr/bin/env python3
"""Team Assignment — partition each world's agents into teams + spawn positions.

Run once at "match start" (or whenever a world's roster changes). Produces
state/teams.json with a deterministic two-team split per world plus role-
based spawn coordinates. From that point, the frame compiler treats team
membership — not raw bond signs — as the truth-source for "ally vs enemy".

Algorithm (deterministic, no LLM required — but the same logic could be
expressed as a one-shot lispy program later when the engine wants to
reason about it dynamically):

    1. Pick two seed agents per world: the two highest-degree nodes in
       the bond graph that are NOT bonded to each other. They become the
       cores of `radiant` and `dire`.
    2. Greedy assignment: for each remaining agent, sum their bond scores
       to each team. Join the team with higher total bond. Ties broken
       by smaller current team size (keeps teams balanced).
    3. Within each team, assign ROLES from archetype:
         frontline  ← aggressive / fighter
         mid        ← scholar / thoughtful / introspective
         support    ← friendly / creative / explorer
         flex       ← anything else
       Roles get fixed spawn-anchor coordinates per world. Agent positions
       reset to their anchor (with small jitter) at match start.

Usage:

    python3 scripts/team_assign.py                 # all worlds, write state
    python3 scripts/team_assign.py --world arena   # one world
    python3 scripts/team_assign.py --dry-run       # show, don't write
    python3 scripts/team_assign.py --reset-positions  # also rewrite agents.json

Output:

    state/teams.json  — { "_meta": {...},
                          "teams": { "<world>": {
                                       "radiant": ["agentId", ...],
                                       "dire":    ["agentId", ...],
                                       "roles":   { "agentId": "frontline" }
                                    }, ... }}
"""
from __future__ import annotations

import argparse
import json
import random
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
STATE_DIR = BASE_DIR / "state"
WORLDS_DIR = BASE_DIR / "worlds"
TEAMS_PATH = STATE_DIR / "teams.json"

# ── Role spawn anchors per world ─────────────────────────────────────
# Two teams (radiant on -x side, dire on +x side). Within a team, three
# role slots arranged to mirror MOBA lanes: support/back, mid, frontline.
# Anchors are deliberately inside the world bounds with margin.

ROLE_ANCHORS = {
    "hub":         {"frontline": (0, 0),   "mid": (0, -3),   "support": (0, -6)},
    "arena":       {"frontline": (0, 8),   "mid": (0, 0),    "support": (0, -8)},
    "marketplace": {"frontline": (0, 8),   "mid": (0, 0),    "support": (0, -10)},
    "gallery":     {"frontline": (0, 10),  "mid": (0, 0),    "support": (0, -8)},
    "dungeon":     {"frontline": (0, 8),   "mid": (0, 0),    "support": (0, -8)},
}

# Side multiplier — radiant on negative x, dire on positive
SIDE_X = {"radiant": -1, "dire": 1}


def _archetype_to_role(archetype: str) -> str:
    a = (archetype or "").lower()
    if any(t in a for t in ("aggressive", "fighter")):
        return "frontline"
    if any(t in a for t in ("scholar", "thoughtful", "introspective", "methodical")):
        return "mid"
    if any(t in a for t in ("friendly", "creative", "explorer")):
        return "support"
    return "mid"  # flex defaults to mid


def _bond_table(edges: list) -> dict:
    """{(a,b): score} where (a,b) is sorted tuple."""
    out = {}
    for e in edges:
        a, b = e.get("a"), e.get("b")
        if not a or not b:
            continue
        key = tuple(sorted([a, b]))
        out[key] = max(out.get(key, 0), int(e.get("score", 0)))
    return out


def _bond(table: dict, a: str, b: str) -> int:
    return table.get(tuple(sorted([a, b])), 0)


def _degree(agent_id: str, agents_in_world: list, table: dict) -> int:
    return sum(_bond(table, agent_id, a["id"])
               for a in agents_in_world
               if a["id"] != agent_id)


def assign_world(agents_in_world: list, edges: list,
                 archetype_lookup: dict | None = None,
                 seed: int | None = None) -> dict:
    """Partition one world's agents into radiant/dire + assign roles + anchors.

    archetype_lookup: optional {agent_id: archetype_string}. If absent, we
    read from each agent record's personality.archetype which is usually
    empty for auto-spawned agents.

    Returns:
        {
          "radiant": [agentId,...],
          "dire":    [agentId,...],
          "roles":   {agentId: 'frontline'|'mid'|'support'},
          "anchors": {agentId: {"x": float, "z": float}},
        }
    """
    archetype_lookup = archetype_lookup or {}
    if not agents_in_world:
        return {"radiant": [], "dire": [], "roles": {}, "anchors": {}}

    rng = random.Random(seed if seed is not None else 42)
    table = _bond_table(edges)

    # Sort agents by descending degree — high-degree nodes anchor teams
    sorted_agents = sorted(
        agents_in_world,
        key=lambda a: (-_degree(a["id"], agents_in_world, table), a["id"]),
    )

    if len(sorted_agents) == 1:
        only = sorted_agents[0]["id"]
        return {
            "radiant": [only], "dire": [], "roles": {}, "anchors": {},
        }

    # Pick seeds: highest-degree node + the highest-degree node that
    # is NOT directly bonded to it. If everyone's bonded to seed1, pick #2.
    seed1 = sorted_agents[0]["id"]
    seed2 = None
    for cand in sorted_agents[1:]:
        if _bond(table, seed1, cand["id"]) <= 0:
            seed2 = cand["id"]
            break
    if seed2 is None:
        seed2 = sorted_agents[1]["id"]

    radiant = {seed1}
    dire = {seed2}

    # Greedy bond-affinity assignment
    remaining = [a["id"] for a in sorted_agents if a["id"] not in (seed1, seed2)]
    rng.shuffle(remaining)  # reduce ordering bias
    for aid in remaining:
        r_score = sum(_bond(table, aid, m) for m in radiant)
        d_score = sum(_bond(table, aid, m) for m in dire)
        if r_score > d_score:
            radiant.add(aid)
        elif d_score > r_score:
            dire.add(aid)
        else:
            # tie — go to smaller team
            (radiant if len(radiant) <= len(dire) else dire).add(aid)

    # Role assignment per agent — prefer registry archetype if provided,
    # else fall back to whatever's on the agent record (often empty).
    arch_inline = {a["id"]: ((a.get("personality") or {}).get("archetype") or "")
                   for a in agents_in_world}
    roles = {}
    for aid in radiant | dire:
        arch = archetype_lookup.get(aid) or arch_inline.get(aid, "")
        roles[aid] = _archetype_to_role(arch)

    # Anchor positions
    world_id = agents_in_world[0].get("world", "hub")
    anchors_for_world = ROLE_ANCHORS.get(world_id, ROLE_ANCHORS["hub"])

    anchor_coords: dict = {}
    # Distribute role slots — multiple frontliners get jittered around the anchor
    for team_name, members in (("radiant", radiant), ("dire", dire)):
        side = SIDE_X[team_name]
        # Group by role for jitter spacing
        by_role = defaultdict(list)
        for aid in members:
            by_role[roles[aid]].append(aid)
        for role, role_members in by_role.items():
            base = anchors_for_world.get(role, (0, 0))
            for i, aid in enumerate(role_members):
                # Spread along z, offset by team side along x
                spread = (i - (len(role_members) - 1) / 2) * 1.2
                anchor_coords[aid] = {
                    "x": float(base[0] + side * (4 + 0.4 * abs(spread))),
                    "z": float(base[1] + spread),
                }

    return {
        "radiant": sorted(radiant),
        "dire": sorted(dire),
        "roles": roles,
        "anchors": anchor_coords,
    }


def assign_all(world_filter: str | None = None,
               seed: int | None = None) -> dict:
    agents_doc = json.loads((STATE_DIR / "agents.json").read_text())
    agents = agents_doc.get("agents", [])
    rel_doc = json.loads((STATE_DIR / "relationships.json").read_text())
    edges = rel_doc.get("edges", [])

    # Read archetypes from registry — agents.json typically has them blank
    archetype_lookup = {}
    reg_dir = BASE_DIR / "agents"
    if reg_dir.is_dir():
        for p in reg_dir.glob("*.agent.json"):
            try:
                d = json.loads(p.read_text())
                aid = d.get("id") or p.stem.replace(".agent", "")
                arch = (d.get("personality") or {}).get("archetype") or ""
                if arch:
                    archetype_lookup[aid] = arch
            except (json.JSONDecodeError, OSError):
                continue

    by_world = defaultdict(list)
    for a in agents:
        if world_filter and a.get("world") != world_filter:
            continue
        by_world[a.get("world", "hub")].append(a)

    result = {}
    for world, members in by_world.items():
        result[world] = assign_world(members, edges,
                                     archetype_lookup=archetype_lookup,
                                     seed=seed)
    return result


def reset_positions_in_agents_json(teams: dict, jitter: float = 0.5) -> int:
    """Apply each team's anchor positions to state/agents.json. Adds light jitter
    so agents don't stack exactly. Returns count of agents updated."""
    rng = random.Random(0xCAFE)
    path = STATE_DIR / "agents.json"
    doc = json.loads(path.read_text())
    agents = doc.get("agents", [])

    anchor_lookup = {}
    for world, t in teams.items():
        for aid, anc in t.get("anchors", {}).items():
            anchor_lookup[aid] = anc

    updated = 0
    for a in agents:
        anc = anchor_lookup.get(a.get("id"))
        if not anc:
            continue
        a["position"] = {
            "x": round(anc["x"] + rng.uniform(-jitter, jitter), 2),
            "y": a.get("position", {}).get("y", 0),
            "z": round(anc["z"] + rng.uniform(-jitter, jitter), 2),
        }
        updated += 1

    if updated:
        meta = dict(doc.get("_meta", {}))
        meta["lastUpdate"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        doc["_meta"] = meta
        path.write_text(json.dumps(doc, indent=4, ensure_ascii=False) + "\n")
    return updated


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--world", help="Only assign teams for this world.")
    ap.add_argument("--seed", type=int, default=42,
                    help="RNG seed (deterministic by default).")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print the partition, don't write state/teams.json.")
    ap.add_argument("--reset-positions", action="store_true",
                    help="Also rewrite state/agents.json so each agent's "
                         "position matches its team-role anchor (jittered).")
    args = ap.parse_args(argv)

    teams = assign_all(world_filter=args.world, seed=args.seed)

    print()
    print("=" * 60)
    print(f"⚔️  Team Assignment")
    print("=" * 60)
    for world, t in teams.items():
        r, d = len(t["radiant"]), len(t["dire"])
        print(f"  {world:12} radiant={r:3}  dire={d:3}")
        # role breakdown
        roles_r = defaultdict(int)
        roles_d = defaultdict(int)
        for aid, role in t["roles"].items():
            (roles_r if aid in t["radiant"] else roles_d)[role] += 1
        if roles_r or roles_d:
            print(f"               roles radiant={dict(roles_r)} "
                  f"dire={dict(roles_d)}")
    print()

    if args.dry_run:
        print("(dry run — not writing state/teams.json)")
        return 0

    out = {
        "_meta": {
            "lastUpdate": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "version": "1.0",
            "seed": args.seed,
            "method": "greedy bond-affinity, archetype roles, mirrored anchors",
        },
        "teams": teams,
    }
    TEAMS_PATH.write_text(json.dumps(out, indent=4, ensure_ascii=False) + "\n")
    print(f"  ✓ wrote {TEAMS_PATH.relative_to(BASE_DIR)}")

    if args.reset_positions:
        n = reset_positions_in_agents_json(teams)
        print(f"  ✓ reset positions on {n} agents in state/agents.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
