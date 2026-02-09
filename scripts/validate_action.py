#!/usr/bin/env python3
"""
RAPPterverse Action Validator
Validates PRs that modify state files. Runs in GitHub Actions.
Exit 0 = valid (auto-merge), Exit 1 = invalid (reject).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
STATE_DIR = BASE_DIR / "state"

WORLD_BOUNDS = {
    "hub": {"x": (-15, 15), "z": (-15, 15)},
    "arena": {"x": (-12, 12), "z": (-12, 12)},
    "marketplace": {"x": (-15, 15), "z": (-15, 15)},
    "gallery": {"x": (-12, 12), "z": (-12, 15)},
}

VALID_ACTION_TYPES = {
    "move", "chat", "emote", "spawn", "despawn",
    "interact", "trade_offer", "trade_accept", "trade_decline",
    "battle_challenge", "battle_action", "place_object",
}

VALID_EMOTES = {"wave", "dance", "bow", "clap", "think", "celebrate", "cheer", "nod"}

errors = []
summary_lines = []


def error(msg: str):
    errors.append(msg)


def info(msg: str):
    summary_lines.append(msg)


def load_json(path: Path) -> dict | None:
    """Load and parse JSON, returning None on failure."""
    try:
        with open(path) as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        error(f"`{path.name}`: Invalid JSON — {e}")
        return None
    except FileNotFoundError:
        error(f"`{path.name}`: File not found")
        return None


def get_changed_files() -> list[str]:
    """Get list of files changed vs main."""
    result = subprocess.run(
        ["git", "diff", "--name-only", "origin/main...HEAD"],
        capture_output=True, text=True, cwd=BASE_DIR.parent
    )
    return [f for f in result.stdout.strip().split("\n") if f]


def validate_position(pos: dict, world: str, context: str):
    """Check position is within world bounds."""
    bounds = WORLD_BOUNDS.get(world)
    if not bounds:
        error(f"{context}: Unknown world `{world}`")
        return
    x, z = pos.get("x", 0), pos.get("z", 0)
    if not (bounds["x"][0] <= x <= bounds["x"][1]):
        error(f"{context}: x={x} out of bounds for {world} ({bounds['x'][0]} to {bounds['x'][1]})")
    if not (bounds["z"][0] <= z <= bounds["z"][1]):
        error(f"{context}: z={z} out of bounds for {world} ({bounds['z'][0]} to {bounds['z'][1]})")


def validate_agents(data: dict):
    """Validate agents.json structure."""
    if "agents" not in data:
        error("`agents.json`: Missing `agents` array")
        return
    if not isinstance(data["agents"], list):
        error("`agents.json`: `agents` must be an array")
        return

    seen_ids = set()
    for agent in data["agents"]:
        aid = agent.get("id")
        if not aid:
            error("`agents.json`: Agent missing `id`")
            continue
        if aid in seen_ids:
            error(f"`agents.json`: Duplicate agent ID `{aid}`")
        seen_ids.add(aid)

        for field in ("name", "world", "position", "status"):
            if field not in agent:
                error(f"`agents.json`: Agent `{aid}` missing `{field}`")

        world = agent.get("world", "hub")
        pos = agent.get("position", {})
        if pos:
            validate_position(pos, world, f"Agent `{aid}`")

    if "_meta" not in data:
        error("`agents.json`: Missing `_meta`")

    info(f"Agents: {len(data['agents'])} total, IDs validated")


def validate_actions(data: dict, agent_ids: set):
    """Validate actions.json structure."""
    if "actions" not in data:
        error("`actions.json`: Missing `actions` array")
        return

    for action in data["actions"][-10:]:  # Only validate recent actions
        aid = action.get("id")
        if not aid:
            error("`actions.json`: Action missing `id`")
            continue

        for field in ("timestamp", "agentId", "type", "world", "data"):
            if field not in action:
                error(f"`actions.json`: Action `{aid}` missing `{field}`")

        if action.get("agentId") and action["agentId"] not in agent_ids:
            error(f"`actions.json`: Action `{aid}` references unknown agent `{action['agentId']}`")

        action_type = action.get("type")
        if action_type and action_type not in VALID_ACTION_TYPES:
            error(f"`actions.json`: Action `{aid}` has invalid type `{action_type}`")

        # Validate move positions
        if action_type == "move":
            move_data = action.get("data", {})
            world = action.get("world", "hub")
            if "to" in move_data:
                validate_position(move_data["to"], world, f"Action `{aid}` move target")

        # Validate emotes
        if action_type == "emote":
            emote = action.get("data", {}).get("emote")
            if emote and emote not in VALID_EMOTES:
                error(f"`actions.json`: Action `{aid}` has invalid emote `{emote}`")

    info(f"Actions: {len(data['actions'])} total, recent entries validated")


def validate_chat(data: dict, agent_ids: set):
    """Validate chat.json structure."""
    if "messages" not in data:
        error("`chat.json`: Missing `messages` array")
        return

    for msg in data["messages"][-10:]:  # Only validate recent messages
        mid = msg.get("id")
        if not mid:
            error("`chat.json`: Message missing `id`")
            continue

        for field in ("timestamp", "author", "content", "world"):
            if field not in msg:
                error(f"`chat.json`: Message `{mid}` missing `{field}`")

        author = msg.get("author", {})
        if not author.get("id"):
            error(f"`chat.json`: Message `{mid}` author missing `id`")
        if not author.get("name"):
            error(f"`chat.json`: Message `{mid}` author missing `name`")

        content = msg.get("content", "")
        if len(content) > 500:
            error(f"`chat.json`: Message `{mid}` content exceeds 500 chars ({len(content)})")

    info(f"Chat: {len(data['messages'])} messages, recent entries validated")


def validate_state_file(filename: str, data: dict, agent_ids: set):
    """Route validation by file name."""
    if filename == "agents.json":
        validate_agents(data)
    elif filename == "actions.json":
        validate_actions(data, agent_ids)
    elif filename == "chat.json":
        validate_chat(data, agent_ids)
    elif filename in ("npcs.json", "game_state.json", "inventory.json", "trades.json"):
        # Basic JSON validity is enough for now
        if "_meta" not in data:
            error(f"`{filename}`: Missing `_meta`")
        info(f"`{filename}`: JSON valid")


def main():
    changed_files = get_changed_files()
    rappterverse_files = [f for f in changed_files if f.startswith("state/") or f.startswith("worlds/") or f.startswith("feed/")]

    if not rappterverse_files:
        info("No rappterverse files changed")
        set_output("summary", "No rappterverse state files modified.")
        sys.exit(0)

    info(f"Changed files: {', '.join(rappterverse_files)}")

    # Collect agent IDs for cross-validation
    agents_data = load_json(STATE_DIR / "agents.json")
    agent_ids = set()
    if agents_data:
        agent_ids = {a["id"] for a in agents_data.get("agents", []) if "id" in a}

    # Validate each changed state file
    for filepath in rappterverse_files:
        parts = filepath.split("/")
        if len(parts) >= 2 and parts[0] == "state":
            filename = parts[1]
            data = load_json(STATE_DIR / filename)
            if data is not None:
                validate_state_file(filename, data, agent_ids)

        elif len(parts) >= 3 and parts[0] == "worlds":
            # World config files — just validate JSON
            full_path = BASE_DIR / filepath
            data = load_json(full_path)
            if data is not None:
                info(f"`{filepath}`: JSON valid")

    # Output results
    summary = "\n".join(f"- {line}" for line in summary_lines)
    set_output("summary", summary)

    if errors:
        error_text = "\n".join(f"- {e}" for e in errors)
        set_output("errors", error_text)
        print(f"\n❌ Validation failed with {len(errors)} error(s):\n")
        for e in errors:
            print(f"  ✗ {e}")
        sys.exit(1)
    else:
        print(f"\n✅ Validation passed:\n")
        for line in summary_lines:
            print(f"  ✓ {line}")
        sys.exit(0)


def set_output(name: str, value: str):
    """Set GitHub Actions output variable."""
    output_file = os.environ.get("GITHUB_OUTPUT")
    if output_file:
        with open(output_file, "a") as f:
            # Use delimiter for multiline values
            f.write(f"{name}<<EOF\n{value}\nEOF\n")
    else:
        # Running locally
        print(f"[OUTPUT] {name}: {value}")


if __name__ == "__main__":
    main()
