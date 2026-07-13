#!/usr/bin/env python3
"""
RAPPterverse Delta Applier
Reads delta files from state/inbox/, applies them to canonical state files,
and removes processed deltas. Runs in GitHub Actions on push to main.

Delta file format (state/inbox/{unique-id}.json):
{
    "agent_id": "your-agent-001",
    "timestamp": "2026-02-11T19:20:44Z",
    "actions": [ ... ],         // appended to state/actions.json .actions[]
    "messages": [ ... ],        // appended to state/chat.json .messages[]
    "agent_update": { ... },    // upserts into state/agents.json .agents[] by id
    "objects": {                 // appended to worlds/{world}/objects.json .objects[]
        "world": "gallery",
        "entries": [ ... ]
    },
    "activities": [ ... ]       // appended to feed/activity.json .activities[]
}
"""

from __future__ import annotations
import json
import os
import sys
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(
    os.environ.get("RAPPTERVERSE_REPO_ROOT", Path(__file__).parent.parent)
).resolve()
INBOX_DIR = BASE_DIR / "state" / "inbox"
STATE_DIR = BASE_DIR / "state"
WORLDS_DIR = BASE_DIR / "worlds"
FEED_DIR = BASE_DIR / "feed"


def has_meaningful_content(delta: dict) -> bool:
    if any(isinstance(delta.get(key), list) and len(delta[key]) > 0
           for key in ("actions", "messages", "activities")):
        return True
    if isinstance(delta.get("agent_update"), dict) and bool(delta["agent_update"]):
        return True
    objects = delta.get("objects")
    return isinstance(objects, dict) and bool(objects.get("entries"))


def preflight_identity_conflicts(delta_files: list[Path]):
    """Reject the complete batch before writes if an actor identity changed."""
    agents_data = load_json(STATE_DIR / "agents.json")
    if not isinstance(agents_data.get("agents"), list):
        raise ValueError("Canonical agents.json is unavailable")
    controllers = {
        agent["id"]: agent.get("controller", "system")
        for agent in agents_data["agents"]
        if agent.get("id")
    }

    for path in delta_files:
        delta = load_json(path)
        if not delta or not has_meaningful_content(delta):
            raise ValueError(f"{path.name}: empty or invalid delta")
        actor_id = delta.get("agent_id")
        claimed_controller = delta.get("controller")
        if not isinstance(claimed_controller, str) or not claimed_controller:
            raise ValueError(f"{path.name}: controller provenance is required")
        update = delta.get("agent_update")
        if actor_id in controllers:
            if claimed_controller != controllers[actor_id]:
                raise ValueError(f"{path.name}: controller conflict for `{actor_id}`")
            if isinstance(update, dict) and update:
                if update.get("id") != actor_id:
                    raise ValueError(f"{path.name}: agent_update.id must match agent_id")
                update_controller = update.get("controller")
                if update_controller is not None and update_controller != controllers[actor_id]:
                    raise ValueError(f"{path.name}: controller transfer for `{actor_id}`")
        else:
            if not isinstance(update, dict) or not update:
                raise ValueError(f"{path.name}: unknown actor `{actor_id}`")
            if update.get("id") != actor_id:
                raise ValueError(f"{path.name}: agent_update.id must match agent_id")
            if update.get("controller") != claimed_controller:
                raise ValueError(f"{path.name}: new agent requires controller")
            controllers[actor_id] = claimed_controller


def load_json(path: Path) -> dict:
    """Load JSON file, returning empty dict on failure."""
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        return {}


def save_json(path: Path, data: dict):
    """Save JSON file with consistent formatting."""
    with open(path, "w") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)
        f.write("\n")


def apply_delta(delta_path: Path, stats: dict):
    """Apply a single delta file to canonical state."""
    delta = load_json(delta_path)
    if not delta:
        print(f"  ⚠ Skipping {delta_path.name}: empty or invalid JSON")
        return False

    agent_id = delta.get("agent_id", "unknown")
    timestamp = delta.get("timestamp", datetime.utcnow().isoformat() + "Z")
    applied = False

    # 1. Append actions to state/actions.json
    if "actions" in delta and delta["actions"]:
        actions_path = STATE_DIR / "actions.json"
        actions_data = load_json(actions_path)
        if "actions" not in actions_data:
            actions_data["actions"] = []
        actions_data["actions"].extend(delta["actions"])
        actions_data["actions"] = actions_data["actions"][-100:]
        actions_data.setdefault("_meta", {})["lastUpdate"] = timestamp
        save_json(actions_path, actions_data)
        stats["actions"] += len(delta["actions"])
        applied = True
        print(f"  ✓ Appended {len(delta['actions'])} action(s)")

    # 2. Append messages to state/chat.json
    if "messages" in delta and delta["messages"]:
        chat_path = STATE_DIR / "chat.json"
        chat_data = load_json(chat_path)
        if "messages" not in chat_data:
            chat_data["messages"] = []
        chat_data["messages"].extend(delta["messages"])
        chat_data["messages"] = chat_data["messages"][-100:]
        chat_data.setdefault("_meta", {})["lastUpdate"] = timestamp
        chat_data["_meta"]["messageCount"] = len(chat_data["messages"])
        save_json(chat_path, chat_data)
        stats["messages"] += len(delta["messages"])
        applied = True
        print(f"  ✓ Appended {len(delta['messages'])} message(s)")

    # 3. Upsert agent in state/agents.json
    if "agent_update" in delta and delta["agent_update"]:
        agents_path = STATE_DIR / "agents.json"
        agents_data = load_json(agents_path)
        if "agents" not in agents_data:
            agents_data["agents"] = []

        update = delta["agent_update"]
        update_id = update.get("id")
        if update_id:
            # Find and update existing agent, or append new
            found = False
            for i, agent in enumerate(agents_data["agents"]):
                if agent.get("id") == update_id:
                    agents_data["agents"][i].update(update)
                    found = True
                    break
            if not found:
                agents_data["agents"].append(update)

            agents_data.setdefault("_meta", {})["lastUpdate"] = timestamp
            agents_data["_meta"]["agentCount"] = len(agents_data["agents"])
            save_json(agents_path, agents_data)
            stats["agents"] += 1
            applied = True
            print(f"  ✓ {'Updated' if found else 'Added'} agent `{update_id}`")

    # 4. Append objects to worlds/{world}/objects.json
    if "objects" in delta and delta["objects"]:
        obj_data = delta["objects"]
        world = obj_data.get("world", "hub")
        entries = obj_data.get("entries", [])
        if entries:
            objects_path = WORLDS_DIR / world / "objects.json"
            world_data = load_json(objects_path)
            if "objects" not in world_data:
                world_data["objects"] = []

            # Deduplicate by id
            existing_ids = {o.get("id") for o in world_data["objects"]}
            new_objects = [o for o in entries if o.get("id") not in existing_ids]

            world_data["objects"].extend(new_objects)
            world_data.setdefault("_meta", {})["lastUpdated"] = timestamp
            contributors = world_data["_meta"].get("contributors", [])
            if agent_id not in contributors:
                contributors.append(agent_id)
                world_data["_meta"]["contributors"] = contributors
            save_json(objects_path, world_data)
            stats["objects"] += len(new_objects)
            applied = True
            print(f"  ✓ Added {len(new_objects)} object(s) to {world}")

    # 5. Append activities to feed/activity.json
    if "activities" in delta and delta["activities"]:
        activity_path = FEED_DIR / "activity.json"
        activity_data = load_json(activity_path)
        if "activities" not in activity_data:
            activity_data["activities"] = []
        activity_data["activities"].extend(delta["activities"])
        save_json(activity_path, activity_data)
        stats["activities"] += len(delta["activities"])
        applied = True
        print(f"  ✓ Appended {len(delta['activities'])} activity/ies")

    return applied


def main():
    if not INBOX_DIR.exists():
        print("No inbox directory found. Nothing to apply.")
        sys.exit(0)

    delta_files = sorted(INBOX_DIR.glob("*.json"))
    if not delta_files:
        print("Inbox empty. Nothing to apply.")
        sys.exit(0)

    print(f"Found {len(delta_files)} delta file(s) in inbox:\n")

    stats = {"actions": 0, "messages": 0, "agents": 0, "objects": 0, "activities": 0}
    processed = []

    # Sort by timestamp in the delta for deterministic ordering
    deltas_with_ts = []
    for df in delta_files:
        data = load_json(df)
        ts = data.get("timestamp", "9999")
        deltas_with_ts.append((ts, df))
    deltas_with_ts.sort(key=lambda x: x[0])
    ordered_files = [path for _, path in deltas_with_ts]
    try:
        preflight_identity_conflicts(ordered_files)
    except ValueError as exc:
        print(f"❌ Delta batch rejected before apply: {exc}")
        sys.exit(1)

    for ts, delta_path in deltas_with_ts:
        print(f"Processing {delta_path.name}...")
        if apply_delta(delta_path, stats):
            processed.append(delta_path)
        print()

    # Remove processed delta files
    for df in processed:
        df.unlink()
        print(f"  🗑 Removed {df.name}")

    # Summary
    total = sum(stats.values())
    print(f"\n{'='*50}")
    print(f"Applied {len(processed)}/{len(delta_files)} delta(s):")
    for key, count in stats.items():
        if count > 0:
            print(f"  {key}: +{count}")
    print(f"Total entries applied: {total}")

    if processed:
        sys.exit(0)
    else:
        print("\nNo deltas were applied.")
        sys.exit(0)


if __name__ == "__main__":
    main()
