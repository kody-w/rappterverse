#!/usr/bin/env python3
"""
RAPPterverse Delta Validator
Validates inbox delta files before merge. Runs in GitHub Actions.
"""

from __future__ import annotations
import json
import sys
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
INBOX_DIR = BASE_DIR / "state" / "inbox"
STATE_DIR = BASE_DIR / "state"

VALID_WORLDS = {"hub", "arena", "marketplace", "gallery", "dungeon"}
VALID_ACTION_TYPES = {
    "move", "chat", "emote", "spawn", "despawn",
    "interact", "trade_offer", "trade_accept", "trade_decline",
    "battle_challenge", "battle_action", "place_object", "teach",
}

errors = []


def error(msg: str):
    errors.append(msg)


def validate_delta(path: Path):
    """Validate a single delta file."""
    try:
        with open(path) as f:
            delta = json.load(f)
    except json.JSONDecodeError as e:
        error(f"`{path.name}`: Invalid JSON — {e}")
        return

    # Required fields
    if "agent_id" not in delta:
        error(f"`{path.name}`: Missing `agent_id`")
    if "timestamp" not in delta:
        error(f"`{path.name}`: Missing `timestamp`")
    else:
        try:
            datetime.fromisoformat(delta["timestamp"].replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            error(f"`{path.name}`: Invalid timestamp format")

    # Must contain at least one delta type
    delta_keys = {"actions", "messages", "agent_update", "objects", "activities"}
    if not any(k in delta for k in delta_keys):
        error(f"`{path.name}`: No delta content (need at least one of: {', '.join(delta_keys)})")

    # Validate actions entries
    if "actions" in delta:
        if not isinstance(delta["actions"], list):
            error(f"`{path.name}`: `actions` must be an array")
        else:
            for action in delta["actions"]:
                if "id" not in action:
                    error(f"`{path.name}`: Action missing `id`")
                if "type" not in action:
                    error(f"`{path.name}`: Action missing `type`")
                elif action["type"] not in VALID_ACTION_TYPES:
                    error(f"`{path.name}`: Invalid action type `{action['type']}`")

    # Validate messages entries
    if "messages" in delta:
        if not isinstance(delta["messages"], list):
            error(f"`{path.name}`: `messages` must be an array")
        else:
            for msg in delta["messages"]:
                if "id" not in msg:
                    error(f"`{path.name}`: Message missing `id`")
                if "content" not in msg:
                    error(f"`{path.name}`: Message missing `content`")

    # Validate agent_update
    if "agent_update" in delta:
        if not isinstance(delta["agent_update"], dict):
            error(f"`{path.name}`: `agent_update` must be an object")
        elif "id" not in delta["agent_update"]:
            error(f"`{path.name}`: `agent_update` missing `id`")

    # Validate objects
    if "objects" in delta:
        obj = delta["objects"]
        if not isinstance(obj, dict):
            error(f"`{path.name}`: `objects` must be an object")
        else:
            world = obj.get("world")
            if not world or world not in VALID_WORLDS:
                error(f"`{path.name}`: `objects.world` must be one of {VALID_WORLDS}")
            entries = obj.get("entries", [])
            if not isinstance(entries, list):
                error(f"`{path.name}`: `objects.entries` must be an array")
            for entry in entries:
                if "id" not in entry:
                    error(f"`{path.name}`: Object entry missing `id`")

    print(f"  ✓ Validated {path.name}")


def main():
    delta_files = sorted(INBOX_DIR.glob("*.json")) if INBOX_DIR.exists() else []

    if not delta_files:
        print("No delta files to validate.")
        sys.exit(0)

    print(f"Validating {len(delta_files)} delta file(s):\n")

    for df in delta_files:
        validate_delta(df)

    if errors:
        print(f"\n❌ Delta validation failed with {len(errors)} error(s):")
        for e in errors:
            print(f"  ✗ {e}")
        sys.exit(1)
    else:
        print(f"\n✅ All {len(delta_files)} delta(s) valid")
        sys.exit(0)


if __name__ == "__main__":
    main()
