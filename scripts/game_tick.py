#!/usr/bin/env python3
"""
RAPPterverse Game Tick
Processes triggers, updates NPC needs, and generates reactions.
Runs every 5 minutes via GitHub Actions or on state changes.
"""

import json
import random
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
STATE_DIR = BASE_DIR / "state"


def load_json(path: Path) -> dict:
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return {}


def save_json(path: Path, data: dict):
    with open(path, "w") as f:
        json.dump(data, f, indent=4)


def process_triggers(game_state: dict, agents_data: dict) -> list[str]:
    """Evaluate and fire game state triggers."""
    fired = []
    triggers = game_state.get("triggers", [])
    worlds = game_state.get("worlds", {})
    economy = game_state.get("economy", {})
    agents = agents_data.get("agents", [])

    # Build context for condition evaluation
    context = {
        "worlds": {},
        "economy": economy,
        "agent_count": len(agents),
    }

    # Calculate per-world population
    for agent in agents:
        world = agent.get("world", "hub")
        if world not in context["worlds"]:
            context["worlds"][world] = {"population": 0}
        if agent.get("status") == "active":
            context["worlds"][world]["population"] += 1

    # Merge with existing world state
    for world_id, world_data in worlds.items():
        if world_id in context["worlds"]:
            context["worlds"][world_id].update(world_data)
        else:
            context["worlds"][world_id] = world_data

    for trigger in triggers:
        if trigger.get("fired", False):
            continue

        condition = trigger.get("condition", "")
        try:
            # Safe evaluation of simple conditions
            result = eval_condition(condition, context)
            if result:
                trigger["fired"] = True
                fired.append(f"Trigger `{trigger['id']}` fired: {trigger.get('action', 'unknown')}")
        except Exception:
            pass  # Skip malformed conditions

    return fired


def eval_condition(condition: str, context: dict) -> bool:
    """Safely evaluate a trigger condition against world context."""
    # Only allow simple dot-notation comparisons
    # e.g., "worlds.hub.population >= 5"
    parts = condition.split()
    if len(parts) != 3:
        return False

    path, operator, value = parts

    # Resolve dot-notation path
    current = context
    for key in path.split("."):
        if isinstance(current, dict) and key in current:
            current = current[key]
        else:
            return False

    try:
        value = float(value)
        current = float(current)
    except (ValueError, TypeError):
        return False

    ops = {">=": lambda a, b: a >= b, "<=": lambda a, b: a <= b,
           ">": lambda a, b: a > b, "<": lambda a, b: a < b,
           "==": lambda a, b: a == b, "!=": lambda a, b: a != b}

    return ops.get(operator, lambda a, b: False)(current, value)


def decay_npc_needs(npcs_data: dict) -> list[str]:
    """Slowly decay NPC needs over time to create dynamic behavior."""
    changes = []
    for npc in npcs_data.get("npcs", []):
        needs = npc.get("needs", {})
        changed = False
        for need, value in needs.items():
            decay = random.randint(1, 5)
            new_value = max(0, value - decay)
            if new_value != value:
                needs[need] = new_value
                changed = True

        if changed:
            # Update mood based on lowest need
            if needs:
                lowest = min(needs.values())
                if lowest < 20:
                    npc["mood"] = "desperate"
                elif lowest < 40:
                    npc["mood"] = "anxious"
                elif lowest < 60:
                    npc["mood"] = "neutral"
                else:
                    npc["mood"] = "content"

                changes.append(f"NPC `{npc['id']}` needs decayed (lowest: {lowest})")

    return changes


def update_activity_feed(feed_data: dict, events: list[str], timestamp: str):
    """Log tick events to the activity feed."""
    activities = feed_data.get("activities", [])
    for event in events:
        activities.append({
            "timestamp": timestamp,
            "type": "system",
            "message": event,
        })
    # Keep last 200 entries
    feed_data["activities"] = activities[-200:]


def main():
    now = datetime.now(timezone.utc)
    timestamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    events = []

    # Load state
    game_state = load_json(STATE_DIR / "game_state.json")
    agents_data = load_json(STATE_DIR / "agents.json")
    npcs_data = load_json(STATE_DIR / "npcs.json")
    feed_data = load_json(BASE_DIR / "feed" / "activity.json")

    # Process triggers
    trigger_events = process_triggers(game_state, agents_data)
    events.extend(trigger_events)

    # Decay NPC needs
    npc_events = decay_npc_needs(npcs_data)
    events.extend(npc_events)

    if not events:
        print(f"[{timestamp}] No state changes this tick")
        return

    # Update timestamps
    game_state.setdefault("_meta", {})["lastUpdate"] = timestamp
    npcs_data.setdefault("_meta", {})["lastUpdate"] = timestamp

    # Save state
    save_json(STATE_DIR / "game_state.json", game_state)
    save_json(STATE_DIR / "npcs.json", npcs_data)

    # Update feed
    update_activity_feed(feed_data, events, timestamp)
    save_json(BASE_DIR / "feed" / "activity.json", feed_data)

    print(f"[{timestamp}] Tick processed: {len(events)} events")
    for event in events:
        print(f"  • {event}")


if __name__ == "__main__":
    main()
