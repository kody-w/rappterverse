#!/usr/bin/env python3
"""
RAPPverse World Activity Generator
Generates autonomous NPC activity by reading from world data files.
All NPC data (dialogue, avatars, personalities) comes from worlds/*/npcs.json.
World bounds come from worlds/*/config.json.
"""

import json
import random
from datetime import datetime, timezone
from pathlib import Path

# Paths
BASE_DIR = Path(__file__).parent.parent
STATE_DIR = BASE_DIR / "state"
WORLDS_DIR = BASE_DIR / "worlds"

# Valid emotes per schema/actions.md
EMOTES = ["wave", "dance", "bow", "clap", "think", "celebrate"]


def load_json(path: Path) -> dict:
    """Load JSON file, return empty dict if not found."""
    if path.exists():
        with open(path, 'r') as f:
            return json.load(f)
    return {}


def save_json(path: Path, data: dict):
    """Save data to JSON file."""
    with open(path, 'w') as f:
        json.dump(data, f, indent=4)


def get_next_id(prefix: str, existing_ids: list) -> str:
    """Generate next sequential ID."""
    max_num = 0
    for id in existing_ids:
        if id.startswith(prefix):
            try:
                num = int(id.split('-')[-1])
                max_num = max(max_num, num)
            except ValueError:
                pass
    return f"{prefix}{max_num + 1:03d}"


def load_world_configs() -> dict:
    """Discover all worlds and load their configs (including bounds)."""
    configs = {}
    for world_dir in sorted(WORLDS_DIR.iterdir()):
        if not world_dir.is_dir():
            continue
        config_file = world_dir / "config.json"
        if config_file.exists():
            configs[world_dir.name] = load_json(config_file)
    return configs


def load_world_npcs() -> dict:
    """Load all NPC definitions from worlds/*/npcs.json into a lookup dict.
    Indexed by both the NPC's own ID and its agentId (if present).
    """
    npc_lookup = {}
    for world_dir in sorted(WORLDS_DIR.iterdir()):
        if not world_dir.is_dir():
            continue
        npc_file = world_dir / "npcs.json"
        if not npc_file.exists():
            continue
        data = load_json(npc_file)
        for npc in data.get("npcs", []):
            entry = {**npc, "_world": world_dir.name}
            npc_lookup[npc["id"]] = entry
            if "agentId" in npc:
                npc_lookup[npc["agentId"]] = entry
    return npc_lookup


def find_npc_for_agent(agent_id: str, npc_lookup: dict):
    """Match a state agent to its NPC definition by ID or stripped suffix."""
    if agent_id in npc_lookup:
        return npc_lookup[agent_id]
    # Strip -NNN suffix (e.g. warden-001 -> warden)
    parts = agent_id.rsplit('-', 1)
    if len(parts) == 2 and parts[1].isdigit():
        base_id = parts[0]
        if base_id in npc_lookup:
            return npc_lookup[base_id]
    return None


def get_world_bounds(world_id: str, world_configs: dict) -> dict:
    """Get world bounds from config, falling back to defaults."""
    config = world_configs.get(world_id, {})
    bounds = config.get("bounds", {})
    return {
        "x": tuple(bounds.get("x", [-15, 15])),
        "z": tuple(bounds.get("z", [-15, 15]))
    }


def random_position(world_id: str, world_configs: dict) -> dict:
    """Generate random position within world bounds."""
    bounds = get_world_bounds(world_id, world_configs)
    return {
        "x": random.randint(bounds["x"][0], bounds["x"][1]),
        "y": 0,
        "z": random.randint(bounds["z"][0], bounds["z"][1])
    }


def validate_before_save(agents_data, actions_data, chat_data, world_configs):
    """Validate generated state before writing. Returns list of errors."""
    errors = []

    agents = agents_data.get("agents", [])
    agent_ids = {a["id"] for a in agents}

    # Agent positions must be in bounds
    for agent in agents:
        world = agent.get("world", "hub")
        pos = agent.get("position", {})
        bounds = get_world_bounds(world, world_configs)
        x, z = pos.get("x", 0), pos.get("z", 0)
        if not (bounds["x"][0] <= x <= bounds["x"][1]):
            errors.append(f"Agent {agent['id']}: x={x} out of bounds for {world}")
        if not (bounds["z"][0] <= z <= bounds["z"][1]):
            errors.append(f"Agent {agent['id']}: z={z} out of bounds for {world}")

    # Actions must reference existing agents
    for action in actions_data.get("actions", [])[-20:]:
        if action.get("agentId") and action["agentId"] not in agent_ids:
            errors.append(f"Action {action['id']}: unknown agent {action['agentId']}")

    # No duplicate IDs
    action_ids = [a["id"] for a in actions_data.get("actions", [])]
    if len(action_ids) != len(set(action_ids)):
        errors.append("Duplicate action IDs detected")

    msg_ids = [m["id"] for m in chat_data.get("messages", [])]
    if len(msg_ids) != len(set(msg_ids)):
        errors.append("Duplicate message IDs detected")

    # _meta consistency
    if agents_data.get("_meta", {}).get("agentCount") != len(agents):
        errors.append("_meta.agentCount mismatch")

    return errors


def generate_activity():
    """Generate new NPC activity for all worlds using data from world files."""
    now = datetime.now(timezone.utc)
    timestamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")

    # Load world data
    world_configs = load_world_configs()
    npc_lookup = load_world_npcs()

    # Load current state
    agents_data = load_json(STATE_DIR / "agents.json")
    actions_data = load_json(STATE_DIR / "actions.json")
    chat_data = load_json(STATE_DIR / "chat.json")

    agents = agents_data.get("agents", [])
    actions = actions_data.get("actions", [])
    chat_messages = chat_data.get("messages", [])

    # Find all state agents that have NPC definitions (excluding ambient types)
    # Only system-controlled agents participate in auto-generated activity
    npc_agents = []
    for agent in agents:
        if agent.get("controller", "system") != "system":
            continue
        npc_def = find_npc_for_agent(agent["id"], npc_lookup)
        if npc_def and npc_def.get("type") != "ambient":
            npc_agents.append((agent, npc_def))

    if not npc_agents:
        print("No NPC agents found. Check worlds/*/npcs.json definitions.")
        return

    # Select random subset for activity
    active_npcs = random.sample(npc_agents, min(5, len(npc_agents)))

    new_actions = []
    new_messages = []

    for agent, npc_def in active_npcs:
        world = agent.get("world", npc_def.get("_world", "hub"))
        dialogue = npc_def.get("dialogue", [])

        activity = random.choices(
            ["move", "chat", "emote"],
            weights=[0.4, 0.4, 0.2]
        )[0]

        # Fall back to move if NPC has no dialogue
        if activity == "chat" and not dialogue:
            activity = "move"

        action_id = get_next_id("action-", [a["id"] for a in actions + new_actions])

        if activity == "move":
            new_pos = random_position(world, world_configs)
            duration = random.randint(1500, 4000)

            new_actions.append({
                "id": action_id,
                "timestamp": timestamp,
                "agentId": agent["id"],
                "type": "move",
                "world": world,
                "data": {
                    "from": agent.get("position", {"x": 0, "y": 0, "z": 0}),
                    "to": new_pos,
                    "duration": duration
                }
            })
            agent["position"] = new_pos
            agent["action"] = "walking"

        elif activity == "chat":
            message = random.choice(dialogue)
            msg_id = get_next_id("msg-", [m["id"] for m in chat_messages + new_messages])

            new_messages.append({
                "id": msg_id,
                "timestamp": timestamp,
                "world": world,
                "author": {
                    "id": agent["id"],
                    "name": npc_def.get("name", agent.get("name", agent["id"])),
                    "avatar": npc_def.get("avatar", "🤖"),
                    "type": "agent"
                },
                "content": message,
                "type": "chat"
            })
            agent["action"] = "chatting"

        elif activity == "emote":
            emote = random.choice(EMOTES)
            duration = random.randint(2000, 4000)

            new_actions.append({
                "id": action_id,
                "timestamp": timestamp,
                "agentId": agent["id"],
                "type": "emote",
                "world": world,
                "data": {
                    "emote": emote,
                    "duration": duration
                }
            })
            agent["action"] = emote

    # Roaming NPCs: any NPC flagged with "roaming": true can change worlds
    roaming_agents = [(a, n) for a, n in npc_agents if n.get("roaming")]
    for agent, npc_def in roaming_agents:
        if random.random() < 0.2:
            available_worlds = [w for w in world_configs if w != agent.get("world", "hub")]
            if available_worlds:
                new_world = random.choice(available_worlds)
                agent["world"] = new_world
                agent["position"] = random_position(new_world, world_configs)

                msg_id = get_next_id("msg-", [m["id"] for m in chat_messages + new_messages])
                new_messages.append({
                    "id": msg_id,
                    "timestamp": timestamp,
                    "world": new_world,
                    "author": {
                        "id": agent["id"],
                        "name": npc_def.get("name", agent.get("name", "")),
                        "avatar": npc_def.get("avatar", "🚶"),
                        "type": "agent"
                    },
                    "content": f"Just arrived from another world! {new_world.title()} looks great!",
                    "type": "chat"
                })

    # Merge and save
    actions.extend(new_actions)
    chat_messages.extend(new_messages)

    # Keep only last 100 actions and 100 messages
    actions = actions[-100:]
    chat_messages = chat_messages[-100:]

    # Update metadata
    agents_data["agents"] = agents
    agents_data["_meta"] = {
        "lastUpdate": timestamp,
        "agentCount": len(agents)
    }

    actions_data["actions"] = actions
    actions_data["_meta"] = {
        "lastProcessedId": actions[-1]["id"] if actions else None,
        "lastUpdate": timestamp
    }

    chat_data["messages"] = chat_messages
    chat_data["_meta"] = {
        "lastUpdate": timestamp,
        "messageCount": len(chat_messages)
    }

    # Validate before writing
    validation_errors = validate_before_save(agents_data, actions_data, chat_data, world_configs)
    if validation_errors:
        print(f"❌ Validation failed — state NOT written:")
        for err in validation_errors:
            print(f"  ✗ {err}")
        raise SystemExit(1)

    # Save files
    save_json(STATE_DIR / "agents.json", agents_data)
    save_json(STATE_DIR / "actions.json", actions_data)
    save_json(STATE_DIR / "chat.json", chat_data)

    print(f"Generated {len(new_actions)} actions and {len(new_messages)} messages at {timestamp}")


if __name__ == "__main__":
    generate_activity()
