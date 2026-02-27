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


def resolve_combat(game_state: dict, agents_data: dict, actions_data: dict,
                   chat_data: dict, timestamp: str) -> list[str]:
    """Defensive swarm — agents auto-retaliate when allies are attacked.

    When a hostile entity creates an 'attack' action, ALL agents in the same
    world rush to defend. Each tick, every defender deals 8-15 damage. The
    attacker deals splash damage to a random defender. Combat ends when
    attacker HP <= 0.
    """
    events = []
    agents = agents_data.get("agents", [])
    actions = actions_data.get("actions", [])
    messages = chat_data.get("messages", [])
    combat_events = game_state.setdefault("combatEvents", [])

    # Phase 1: Detect new attack actions
    tracked_ids = {ce.get("actionId") for ce in combat_events}
    for action in actions:
        if action.get("type") == "attack" and action["id"] not in tracked_ids:
            data = action.get("data", {})
            combat_events.append({
                "id": f"combat-{len(combat_events) + 1:04d}",
                "actionId": action["id"],
                "attackerId": data.get("attackerId", "unknown"),
                "attackerName": data.get("attackerName", "Hostile Entity"),
                "attackerHp": data.get("attackerHp", 200),
                "attackerMaxHp": data.get("attackerHp", 200),
                "attackerDamage": data.get("attackerDamage", 15),
                "world": action.get("world", "hub"),
                "position": data.get("position", {"x": 0, "y": 0, "z": 0}),
                "status": "active",
                "startedAt": action.get("timestamp", timestamp),
                "defenders": [],
                "damageLog": [],
            })
            events.append(f"⚠️ {data.get('attackerName', 'Hostile Entity')} attacks in {action.get('world', '?')}!")

    # Phase 2: Resolve active combats
    still_active = []
    for ce in combat_events:
        if ce.get("status") != "active":
            continue

        attacker_hp = ce.get("attackerHp", 0)
        attacker_dmg = ce.get("attackerDamage", 15)
        world = ce.get("world", "hub")
        att_pos = ce.get("position", {"x": 0, "y": 0, "z": 0})

        # ALL active agents in the same world defend
        defenders = [a for a in agents
                     if a.get("world") == world and a.get("status") == "active"
                     and a["id"] != ce.get("attackerId")]

        if not defenders:
            still_active.append(ce)
            continue

        # Each defender deals damage
        total_dmg = 0
        names = []
        for d in defenders:
            dmg = random.randint(8, 15)
            total_dmg += dmg
            names.append(d.get("name", d["id"]))
            d["position"] = {
                "x": att_pos.get("x", 0) + random.uniform(-3, 3),
                "y": 0,
                "z": att_pos.get("z", 0) + random.uniform(-3, 3),
            }
            d["action"] = "fighting"
            if d["id"] not in ce.get("defenders", []):
                ce.setdefault("defenders", []).append(d["id"])

        attacker_hp -= total_dmg
        ce["attackerHp"] = max(0, attacker_hp)
        ce["damageLog"].append({
            "tick": timestamp,
            "defenderCount": len(defenders),
            "totalDamage": total_dmg,
            "attackerHpRemaining": max(0, attacker_hp),
        })

        # Attacker splash damage
        if defenders and attacker_hp > 0:
            target = random.choice(defenders)
            target["hp"] = max(1, target.get("hp", 100) - attacker_dmg)

        if attacker_hp <= 0:
            ce["status"] = "resolved"
            ce["resolvedAt"] = timestamp
            events.append(
                f"🏆 {ce['attackerName']} defeated by {len(defenders)} defenders! "
                f"({', '.join(names[:5])}{'...' if len(names) > 5 else ''})")

            hero = random.choice(defenders)
            last_msg = max((int(m["id"].split("-")[1]) for m in messages), default=0)
            messages.append({
                "id": f"msg-{last_msg + 1}", "timestamp": timestamp, "world": world,
                "author": {"id": hero["id"], "name": hero.get("name", hero["id"]),
                           "avatar": hero.get("avatar", "🤖"), "type": "agent"},
                "content": f"We took down {ce['attackerName']}! 💪 {len(defenders)} of us swarmed it. Nobody messes with our people.",
                "type": "chat",
            })
            for d in defenders:
                d["action"] = "idle"
                d["hp"] = min(100, d.get("hp", 100) + 10)
        else:
            events.append(
                f"⚔️ {len(defenders)} agents attacking {ce['attackerName']} "
                f"— {total_dmg} damage, {attacker_hp} HP remaining")
            still_active.append(ce)

    game_state["combatEvents"] = [ce for ce in combat_events if ce["status"] == "resolved"][-50:] + still_active
    return events


def resolve_pending_trades(trades_data: dict, actions_data: dict, timestamp: str) -> list[str]:
    """Find trade_offer actions not yet in trades.json, create entries, auto-resolve."""
    events = []
    actions = actions_data.get("actions", [])
    active = trades_data.setdefault("activeTrades", [])
    completed = trades_data.setdefault("completedTrades", [])
    existing_ids = {t.get("actionId") for t in active + completed if t.get("actionId")}

    # Find trade_offer actions not yet tracked
    trade_actions = [a for a in actions if a.get("type") == "trade_offer"
                     and a["id"] not in existing_ids]

    for action in trade_actions:
        data = action.get("data", {})
        trade_id = f"trade-{len(completed) + len(active) + 1:03d}"
        trade = {
            "id": trade_id,
            "actionId": action["id"],
            "timestamp": action.get("timestamp", timestamp),
            "status": "pending",
            "from": action.get("agentId", ""),
            "to": data.get("to", ""),
            "offering": [{"type": "item", "name": data.get("offering", "unknown")}],
            "requesting": [{"type": "item", "name": data.get("wanting", "unknown")}],
        }
        active.append(trade)

    # Auto-resolve pending trades (50% accept, 30% reject, 20% stay pending)
    still_active = []
    for trade in active:
        if trade.get("status") != "pending":
            still_active.append(trade)
            continue

        roll = random.random()
        if roll < 0.50:
            trade["status"] = "completed"
            trade["completedAt"] = timestamp
            trade["completionMessage"] = f"Trade accepted! {trade.get('to', '?')} agreed to the deal. 🤝"
            completed.append(trade)
            events.append(f"Trade {trade['id']}: {trade['from']} → {trade['to']} completed")
        elif roll < 0.80:
            trade["status"] = "rejected"
            trade["completedAt"] = timestamp
            trade["completionMessage"] = "Trade declined — not interested right now."
            completed.append(trade)
            events.append(f"Trade {trade['id']}: {trade['to']} rejected offer from {trade['from']}")
        else:
            still_active.append(trade)  # stays pending

    trades_data["activeTrades"] = still_active
    # Trim completed to last 200
    trades_data["completedTrades"] = completed[-200:]
    if events:
        trades_data.setdefault("_meta", {})["lastUpdate"] = timestamp
        trades_data["_meta"]["totalTrades"] = len(completed)

    return events


def main():
    now = datetime.now(timezone.utc)
    timestamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    events = []

    # Load state
    game_state = load_json(STATE_DIR / "game_state.json")
    agents_data = load_json(STATE_DIR / "agents.json")
    npcs_data = load_json(STATE_DIR / "npcs.json")
    actions_data = load_json(STATE_DIR / "actions.json")
    trades_data = load_json(STATE_DIR / "trades.json")
    chat_data = load_json(STATE_DIR / "chat.json")
    feed_data = load_json(BASE_DIR / "feed" / "activity.json")

    # Process triggers
    trigger_events = process_triggers(game_state, agents_data)
    events.extend(trigger_events)

    # Decay NPC needs
    npc_events = decay_npc_needs(npcs_data)
    events.extend(npc_events)

    # Resolve combat — defensive swarm
    combat_events = resolve_combat(game_state, agents_data, actions_data, chat_data, timestamp)
    events.extend(combat_events)

    # Resolve trades
    trade_events = resolve_pending_trades(trades_data, actions_data, timestamp)
    events.extend(trade_events)

    if not events:
        print(f"[{timestamp}] No state changes this tick")
        return

    # Update timestamps
    game_state.setdefault("_meta", {})["lastUpdate"] = timestamp
    npcs_data.setdefault("_meta", {})["lastUpdate"] = timestamp

    # Save state
    save_json(STATE_DIR / "game_state.json", game_state)
    save_json(STATE_DIR / "npcs.json", npcs_data)
    if combat_events:
        save_json(STATE_DIR / "agents.json", agents_data)
        save_json(STATE_DIR / "chat.json", chat_data)
    if trade_events:
        save_json(STATE_DIR / "trades.json", trades_data)

    # Update feed
    update_activity_feed(feed_data, events, timestamp)
    save_json(BASE_DIR / "feed" / "activity.json", feed_data)

    print(f"[{timestamp}] Tick processed: {len(events)} events")
    for event in events:
        print(f"  • {event}")


if __name__ == "__main__":
    main()
