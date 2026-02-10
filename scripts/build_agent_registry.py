#!/usr/bin/env python3
"""
Build Agent Registry — generates agents/*.agent.json from world data.

Reads worlds/*/npcs.json + state/agents.json and creates a machine-readable
registry entry for every NPC that has both a world definition and a state entry.

Usage:
    python scripts/build_agent_registry.py              # Build all
    python scripts/build_agent_registry.py --dry-run    # Preview without writing
"""

import json
import sys
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
STATE_DIR = BASE_DIR / "state"
WORLDS_DIR = BASE_DIR / "worlds"
AGENTS_DIR = BASE_DIR / "agents"


def load_json(path: Path) -> dict:
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return {}


def load_world_configs() -> dict:
    configs = {}
    for world_dir in sorted(WORLDS_DIR.iterdir()):
        if not world_dir.is_dir():
            continue
        config_file = world_dir / "config.json"
        if config_file.exists():
            configs[world_dir.name] = load_json(config_file)
    return configs


def load_world_npcs() -> dict:
    """Load all NPC definitions, indexed by both npc ID and agentId."""
    npcs = {}
    for world_dir in sorted(WORLDS_DIR.iterdir()):
        if not world_dir.is_dir():
            continue
        npc_file = world_dir / "npcs.json"
        if not npc_file.exists():
            continue
        data = load_json(npc_file)
        for npc in data.get("npcs", []):
            entry = {**npc, "_world": world_dir.name}
            npcs[npc["id"]] = entry
            if "agentId" in npc:
                npcs[npc["agentId"]] = entry
    return npcs


def find_npc_for_agent(agent_id: str, npc_lookup: dict):
    if agent_id in npc_lookup:
        return npc_lookup[agent_id]
    parts = agent_id.rsplit('-', 1)
    if len(parts) == 2 and parts[1].isdigit():
        base_id = parts[0]
        if base_id in npc_lookup:
            return npc_lookup[base_id]
    return None


def build_registry_entry(agent: dict, npc_def: dict) -> dict:
    """Build a registry entry from agent state + NPC definition."""
    personality = npc_def.get("personality", {})
    behavior_type = npc_def.get("behavior", "stationary")

    # Determine action weights based on behavior type
    weights = {"move": 0.3, "chat": 0.5, "emote": 0.2}
    if behavior_type == "patrol":
        weights = {"move": 0.5, "chat": 0.3, "emote": 0.2}
    elif behavior_type in ("trader", "seller", "banker"):
        weights = {"move": 0.2, "chat": 0.6, "emote": 0.2}
    elif behavior_type in ("greeter", "announcer", "commentator"):
        weights = {"move": 0.2, "chat": 0.6, "emote": 0.2}
    elif behavior_type in ("stationary", "curator", "lore"):
        weights = {"move": 0.1, "chat": 0.6, "emote": 0.3}

    return {
        "id": agent["id"],
        "npcId": npc_def["id"],
        "name": npc_def.get("name", agent.get("name", agent["id"])),
        "avatar": npc_def.get("avatar", agent.get("avatar", "🤖")),
        "world": npc_def.get("_world", agent.get("world", "hub")),
        "controller": agent.get("controller", "system"),
        "personality": {
            "archetype": personality.get("archetype", "neutral"),
            "mood": personality.get("mood", "calm"),
            "interests": personality.get("interests", []),
        },
        "behavior": {
            "type": behavior_type,
            "respondToChat": True,
            "autonomousActions": ["move", "chat", "emote"],
            "decisionWeights": weights,
            "roaming": npc_def.get("roaming", False),
        },
        "schedule": {
            "minIntervalSeconds": 300,
            "maxActionsPerHour": 10,
        },
    }


def main():
    dry_run = "--dry-run" in sys.argv

    agents_data = load_json(STATE_DIR / "agents.json")
    agents = agents_data.get("agents", [])
    npc_lookup = load_world_npcs()

    built = 0
    skipped = 0

    for agent in agents:
        aid = agent["id"]
        controller = agent.get("controller", "system")

        # Skip non-system agents (they control themselves)
        if controller != "system":
            skipped += 1
            continue

        npc_def = find_npc_for_agent(aid, npc_lookup)
        if not npc_def:
            continue

        # Skip ambient NPCs (void-emerging, hollow)
        if npc_def.get("type") == "ambient":
            continue

        entry = build_registry_entry(agent, npc_def)
        out_path = AGENTS_DIR / f"{aid}.agent.json"

        if dry_run:
            print(f"  Would create: {out_path.name} ({entry['name']} in {entry['world']})")
        else:
            with open(out_path, 'w') as f:
                json.dump(entry, f, indent=4, ensure_ascii=False)
            print(f"  ✓ {out_path.name} — {entry['name']} ({entry['world']})")

        built += 1

    print(f"\n{'Would build' if dry_run else 'Built'} {built} registry entries, skipped {skipped} non-system agents")


if __name__ == "__main__":
    main()
