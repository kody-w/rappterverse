#!/usr/bin/env python3
"""
RAPPterverse Game Tick
Processes triggers, updates NPC needs, and generates reactions.
Runs every 5 minutes via GitHub Actions or on state changes.
"""

import json
import os
import random
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
STATE_DIR = BASE_DIR / "state"
MEMORY_DIR = STATE_DIR / "memory"


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


def fulfill_npc_needs(npcs_data: dict, actions_data: dict, chat_data: dict,
                      trades_data: dict) -> list[str]:
    """Replenish NPC needs based on world activity.

    Without this, needs only decay and all NPCs become permanently desperate.
    Fulfillment sources:
      - social:    Chat messages in NPC's world, interactions nearby
      - purpose:   Task progress, actions in NPC's world
      - energy:    Passive recovery (rest schedule), low activity periods
      - profit:    Completed trades, marketplace activity
      - inventory: Items moving through marketplace
      - customers: Chat/interaction volume in marketplace
    """
    changes = []
    actions = actions_data.get("actions", [])
    messages = chat_data.get("messages", [])
    completed_trades = trades_data.get("completedTrades", [])

    for npc in npcs_data.get("npcs", []):
        needs = npc.get("needs", {})
        npc_world = npc.get("world", "hub")
        npc_id = npc.get("id", "")
        restored = {}

        # Count activity in NPC's world
        world_actions = sum(1 for a in actions if a.get("world") == npc_world)
        world_messages = sum(1 for m in messages if m.get("world") == npc_world)
        world_trades = sum(1 for t in completed_trades
                          if t.get("status") == "completed")

        # Social: restored by chat/interaction activity in the same world
        if "social" in needs:
            social_boost = min(30, world_messages * 3 + world_actions)
            if social_boost > 0:
                needs["social"] = min(100, needs["social"] + social_boost)
                restored["social"] = social_boost

        # Purpose: restored by actions happening (the world is alive)
        if "purpose" in needs:
            # Task progress also restores purpose
            task = npc.get("currentTask", {})
            task_boost = min(15, task.get("progress", 0) * 3)
            purpose_boost = min(25, world_actions * 2 + task_boost)
            if purpose_boost > 0:
                needs["purpose"] = min(100, needs["purpose"] + purpose_boost)
                restored["purpose"] = purpose_boost

        # Energy: passive recovery — always ticks up slightly
        if "energy" in needs:
            # Check schedule for rest periods
            schedule = npc.get("schedule", [])
            resting = any(s.get("activity") == "rest" for s in schedule)
            energy_boost = random.randint(5, 15) if resting else random.randint(2, 8)
            needs["energy"] = min(100, needs["energy"] + energy_boost)
            restored["energy"] = energy_boost

        # Profit: restored by trades completing
        if "profit" in needs:
            profit_boost = min(30, world_trades * 10 + world_actions)
            if profit_boost > 0:
                needs["profit"] = min(100, needs["profit"] + profit_boost)
                restored["profit"] = profit_boost

        # Inventory: restored by marketplace activity
        if "inventory" in needs:
            inv_status = npc.get("inventory_status", {})
            total_stock = sum(inv_status.values()) if inv_status else 0
            inv_boost = min(25, total_stock // 3)
            if inv_boost > 0:
                needs["inventory"] = min(100, needs["inventory"] + inv_boost)
                restored["inventory"] = inv_boost

        # Customers: restored by chat volume in world
        if "customers" in needs:
            cust_boost = min(25, world_messages * 2 + world_actions)
            if cust_boost > 0:
                needs["customers"] = min(100, needs["customers"] + cust_boost)
                restored["customers"] = cust_boost

        if restored:
            changes.append(
                f"NPC `{npc_id}` needs fulfilled: "
                + ", ".join(f"{k}+{v}" for k, v in restored.items())
            )

    return changes


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
                elif lowest < 80:
                    npc["mood"] = "content"
                else:
                    npc["mood"] = "thriving"

                changes.append(f"NPC `{npc['id']}` needs decayed (lowest: {lowest})")

    return changes


def evolve_agent_traits(agents_data: dict, actions_data: dict, chat_data: dict) -> list[str]:
    """Rappterbook-style trait evolution: behavior drives personality drift.

    Agents start with a base archetype but their traits shift based on what
    they actually DO. Traders who chat a lot develop social traits. Fighters
    who explore develop curiosity. The drift rate is bounded so archetypes
    never fully disappear (TRAIT_FLOOR = 0.30).

    Traits are normalized to sum to 1.0 and stored on each agent.
    """
    PER_EVENT_DRIFT = 0.05    # Three events approximate the previous 15% batch drift
    TRAIT_FLOOR = 0.30        # Base archetype never drops below 30%
    changes = []
    agents = agents_data.get("agents", [])
    actions = actions_data.get("actions", [])
    messages = chat_data.get("messages", [])

    # Map action types to trait categories
    ACTION_TRAIT_MAP = {
        "move": "explorer",
        "chat": "social",
        "emote": "social",
        "trade_offer": "trader",
        "trade_accept": "trader",
        "battle_challenge": "fighter",
        "attack": "fighter",
        "place_object": "builder",
        "tip": "social",
        "trade": "trader",
        "challenge": "fighter",
        "defend": "fighter",
        "poke": "social",
        "enroll": "explorer",
    }

    def semantic_type(action: dict) -> str:
        if action.get("type") == "interact":
            return action.get("data", {}).get("interaction", "interact")
        return action.get("type", "")

    for agent in agents:
        if agent.get("status") != "active":
            continue
        if agent.get("controller", "system") != "system":
            continue

        aid = agent["id"]

        # Count behaviors for this agent
        behavior_counts: dict[str, int] = {}
        for action in actions:
            if action.get("agentId") == aid:
                trait = ACTION_TRAIT_MAP.get(semantic_type(action), "explorer")
                behavior_counts[trait] = behavior_counts.get(trait, 0) + 1

        # Count chat messages as social behavior
        for msg in messages:
            author = msg.get("author", {})
            if isinstance(author, dict) and author.get("id") == aid:
                behavior_counts["social"] = behavior_counts.get("social", 0) + 1
            elif isinstance(author, str) and author == aid:
                behavior_counts["social"] = behavior_counts.get("social", 0) + 1

        if not behavior_counts:
            continue

        # Get or initialize traits
        traits = agent.get("traits", {})
        if not traits:
            # Initialize from archetype if available, else equal distribution
            archetype = agent.get("archetype", agent.get("type", "explorer"))
            all_traits = ["explorer", "social", "trader", "fighter", "builder"]
            traits = {t: 0.10 for t in all_traits}
            # Boost primary archetype
            primary = archetype if archetype in all_traits else "explorer"
            traits[primary] = 0.60
            # Normalize
            total = sum(traits.values())
            traits = {k: v / total for k, v in traits.items()}

        # Compute behavior distribution
        total_actions = sum(behavior_counts.values())
        behavior_dist = {k: v / total_actions for k, v in behavior_counts.items()}

        # Fill missing traits in behavior dist
        for t in traits:
            if t not in behavior_dist:
                behavior_dist[t] = 0.0

        # Apply event-scaled drift so sparse actors still evolve exactly once.
        new_traits = {}
        drift_rate = 1 - (1 - PER_EVENT_DRIFT) ** total_actions
        archetype_trait = max(traits, key=traits.get)  # Remember the dominant trait
        for t in traits:
            new_val = (
                traits[t] * (1 - drift_rate)
                + behavior_dist.get(t, 0) * drift_rate
            )
            new_traits[t] = new_val

        # Enforce floor on archetype trait
        if new_traits.get(archetype_trait, 0) < TRAIT_FLOOR:
            new_traits[archetype_trait] = TRAIT_FLOOR

        # Normalize to sum to 1.0
        total = sum(new_traits.values())
        if total > 0:
            new_traits = {k: round(v / total, 4) for k, v in new_traits.items()}

        # Detect significant shifts for logging
        for t, new_val in new_traits.items():
            old_val = traits.get(t, 0)
            if abs(new_val - old_val) > 0.05:
                changes.append(
                    f"Agent `{aid}` trait drift: {t} {old_val:.2f} → {new_val:.2f}"
                )

        agent["traits"] = new_traits

    return changes


def fulfill_agent_goals(
    actions_data: dict,
    chat_data: dict,
    timestamp: str,
    system_agent_ids: set[str],
) -> list[str]:
    """Check if agents' recent actions match their goals and mark them done.

    Goals have: type, target, action, status. If an agent performed the
    action type recently, mark the goal as completed and generate a new one.
    """
    changes = []
    actions = actions_data.get("actions", [])[-100:]
    messages = chat_data.get("messages", [])[-100:]

    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    if not MEMORY_DIR.exists():
        return changes

    # Build lookup: agent_id -> set of action types performed
    agent_actions: dict[str, set] = {}
    for a in actions:
        aid = a.get("agentId", "")
        if aid:
            action_type = a.get("type", "")
            if action_type == "interact":
                action_type = a.get("data", {}).get("interaction", "interact")
            agent_actions.setdefault(aid, set()).add(action_type)

    # Chat counts as social action
    for m in messages:
        author = m.get("author", {})
        aid = author.get("id", "") if isinstance(author, dict) else ""
        if aid:
            agent_actions.setdefault(aid, set()).add("chat")

    # Goal action mapping
    ACTION_MAP = {
        "explore": {"move", "travel"},
        "wander": {"move", "travel"},
        "commerce": {"trade_offer", "trade_accept", "trade"},
        "social": {"chat", "emote", "poke"},
        "generosity": {"tip", "chat"},
        "grow": {"enroll", "chat"},
        "learn": {"enroll", "chat"},
        "practice": {"battle_challenge", "challenge", "emote"},
        "compete": {"challenge", "battle_challenge"},
        "fight": {"attack", "battle_challenge"},
        "combat": {"attack", "battle_challenge", "challenge"},
    }

    NEW_GOAL_TEMPLATES = [
        {"type": "explore", "target": "a new area", "action": "move", "reason": "see what's out there"},
        {"type": "social", "target": "a neighbor", "action": "chat", "reason": "stay connected"},
        {"type": "commerce", "target": "a good deal", "action": "trade", "reason": "build wealth"},
        {"type": "grow", "target": "new skills", "action": "enroll", "reason": "keep improving"},
        {"type": "compete", "target": "a worthy opponent", "action": "challenge", "reason": "test strength"},
    ]

    completed_total = 0
    for fname in os.listdir(MEMORY_DIR):
        if not fname.endswith('.json'):
            continue
        agent_id = fname.replace('.json', '')
        if agent_id not in system_agent_ids:
            continue
        performed = agent_actions.get(agent_id, set())
        if not performed:
            continue

        mem_path = MEMORY_DIR / fname
        try:
            with open(mem_path) as f:
                mem = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue

        goals = mem.get("goals", [])
        changed = False

        for goal in goals:
            if goal.get("status") != "active":
                continue

            goal_type = goal.get("type", "")
            matching_actions = ACTION_MAP.get(goal_type, {goal.get("action", "")})

            if performed & matching_actions:
                goal["status"] = "done"
                goal["completedAt"] = timestamp
                changed = True
                completed_total += 1

        # Generate replacement goals for completed ones
        completed_count = sum(1 for g in goals if g.get("status") == "done" and g.get("completedAt") == timestamp)
        for _ in range(min(completed_count, 2)):
            import random as _r
            new_goal = dict(_r.choice(NEW_GOAL_TEMPLATES))
            new_goal["created"] = timestamp
            new_goal["status"] = "active"
            goals.append(new_goal)

        if changed:
            # Keep active goals (up to 10) — completed ones stay for one frame then get pruned
            active_goals = [g for g in goals if g.get("status") == "active"]
            done_goals = [g for g in goals if g.get("status") == "done"]
            mem["goals"] = done_goals[-3:] + active_goals[-10:]  # Preserve a few completed for visibility
            with open(mem_path, 'w') as f:
                json.dump(mem, f, indent=4, ensure_ascii=False)

    if completed_total:
        changes.append(f"Goal fulfillment: {completed_total} goals completed across agents")

    return changes


def decay_stale_relationships(rel_data: dict, timestamp: str) -> list[str]:
    """Apply each elapsed decay bucket exactly once."""
    changes = []
    edges = rel_data.get("edges", [])
    interactions = rel_data.get("interactions", [])
    meta = rel_data.setdefault("_meta", {})

    try:
        now_dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return ["Relationship decay skipped: invalid tick timestamp"]

    cursor_value = meta.get("decayCursor")
    if not cursor_value:
        meta["decayCursor"] = timestamp
        return ["Relationship decay cursor initialized"]
    try:
        cursor_dt = datetime.fromisoformat(cursor_value.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        meta["decayCursor"] = timestamp
        return ["Relationship decay cursor repaired"]
    if now_dt <= cursor_dt:
        return []

    # Retained interactions are only a fallback for legacy edges. Each edge's
    # own lastInteraction remains authoritative after log trimming.
    last_seen: dict[tuple, str] = {}
    for entry in interactions:
        pair = tuple(sorted([entry.get("a", ""), entry.get("b", "")]))
        ts = entry.get("timestamp", "")
        if ts > last_seen.get(pair, ""):
            last_seen[pair] = ts

    def cumulative_decay(hours: float) -> int:
        if hours < 48:
            return 0
        if hours < 72:
            return 1
        if hours < 168:
            return 2
        return 3 + int((hours - 168) // 168) * 3

    decayed_count = 0
    for edge in edges:
        if edge.get("score", 0) <= 0:
            continue

        pair = tuple(sorted([edge.get("a", ""), edge.get("b", "")]))
        last_ts = edge.get("lastInteraction") or last_seen.get(pair)
        if not last_ts:
            continue

        try:
            last_dt = datetime.fromisoformat(last_ts.replace("Z", "+00:00"))
            previous_hours = max(0, (cursor_dt - last_dt).total_seconds() / 3600)
            current_hours = max(0, (now_dt - last_dt).total_seconds() / 3600)
        except (ValueError, AttributeError):
            continue

        decrement = cumulative_decay(current_hours) - cumulative_decay(previous_hours)
        if decrement > 0:
            edge["score"] = max(0, edge["score"] - decrement)
            decayed_count += 1

    if decayed_count:
        changes.append(f"Relationship decay: {decayed_count} edges weakened")

    rel_data["edges"] = [e for e in edges if e.get("score", 0) > 0]
    removed = len(edges) - len(rel_data["edges"])
    if removed:
        changes.append(f"Pruned {removed} dead relationships")

    if decayed_count or removed:
        meta["decayCursor"] = timestamp
    rel_data["bonds"] = [
        {
            "agents": [edge["a"], edge["b"]],
            "strength": edge.get("score", 0),
            "type": "social",
            "lastInteraction": edge.get("lastInteraction", ""),
        }
        for edge in rel_data["edges"]
        if edge.get("score", 0) >= 2
    ]
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
        data = action.get("data", {})
        is_hostile_attack = (
            action.get("type") == "attack"
            or (
                action.get("type") == "interact"
                and data.get("interaction") == "hostile_attack"
            )
        )
        if is_hostile_attack and action["id"] not in tracked_ids:
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
                     and a.get("controller", "system") == "system"
                     and a["id"] != ce.get("attackerId")]

        if not defenders:
            still_active.append(ce)
            continue

        # Each defender deals damage
        total_dmg = 0
        names = []
        # World bounds for position clamping
        wb = {"hub": 15, "arena": 12, "marketplace": 15, "gallery": 12, "dungeon": 12}
        bound = wb.get(world, 15)

        for d in defenders:
            dmg = random.randint(8, 15)
            total_dmg += dmg
            names.append(d.get("name", d["id"]))
            d["position"] = {
                "x": max(-bound, min(bound, round(att_pos.get("x", 0) + random.uniform(-3, 3)))),
                "y": 0,
                "z": max(-bound, min(bound, round(att_pos.get("z", 0) + random.uniform(-3, 3)))),
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
            last_msg = 0
            for m in messages:
                try:
                    last_msg = max(last_msg, int(m["id"].split("-")[-1]))
                except (ValueError, IndexError):
                    pass
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


def activity_since_cursor(
    game_state: dict,
    actions_data: dict,
    chat_data: dict,
    trades_data: dict,
    timestamp: str,
) -> tuple[dict, dict, dict, bool]:
    """Return only unseen action/chat records and advance a durable cursor."""
    actions = actions_data.get("actions", [])
    messages = chat_data.get("messages", [])
    completed_trades = trades_data.get("completedTrades", [])
    meta = game_state.setdefault("_meta", {})
    cursor = meta.get("activityCursor")

    def record_ids(records: list[dict]) -> list[str]:
        return [
            str(record.get("id"))
            for record in records
            if record.get("id") is not None
        ]

    def trade_fingerprint(trade: dict) -> str:
        return "|".join(str(trade.get(key, "")) for key in (
            "id", "completedAt", "from", "to", "status",
        ))

    current_actions = record_ids(actions)
    current_messages = record_ids(messages)
    current_trades = [trade_fingerprint(trade) for trade in completed_trades]
    if not isinstance(cursor, dict):
        meta["activityCursor"] = {
            "actions": current_actions[-200:],
            "messages": current_messages[-200:],
            "completedTrades": current_trades[-400:],
            "observedAt": timestamp,
        }
        return (
            {"actions": []},
            {"messages": []},
            {"completedTrades": []},
            True,
        )

    seen_actions = set(cursor.get("actions", []))
    seen_messages = set(cursor.get("messages", []))
    seen_trades = set(cursor.get("completedTrades", []))
    new_actions = [
        action for action in actions
        if str(action.get("id")) not in seen_actions
    ]
    new_messages = [
        message for message in messages
        if str(message.get("id")) not in seen_messages
    ]
    new_trades = [
        trade for trade in completed_trades
        if trade_fingerprint(trade) not in seen_trades
    ]
    changed = bool(new_actions or new_messages or new_trades)
    if changed:
        meta["activityCursor"] = {
            "actions": list(dict.fromkeys(
                list(cursor.get("actions", [])) + current_actions
            ))[-200:],
            "messages": list(dict.fromkeys(
                list(cursor.get("messages", [])) + current_messages
            ))[-200:],
            "completedTrades": list(dict.fromkeys(
                list(cursor.get("completedTrades", [])) + current_trades
            ))[-400:],
            "observedAt": timestamp,
        }
    return (
        {"actions": new_actions},
        {"messages": new_messages},
        {"completedTrades": new_trades},
        changed,
    )


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
    (
        activity_actions,
        activity_chat,
        activity_trades,
        activity_cursor_changed,
    ) = activity_since_cursor(
        game_state,
        actions_data,
        chat_data,
        trades_data,
        timestamp,
    )
    agents_before = json.dumps(
        agents_data.get("agents", []),
        sort_keys=True,
        separators=(",", ":"),
    )

    # Process triggers
    trigger_events = process_triggers(game_state, agents_data)
    events.extend(trigger_events)

    # Fulfill NPC needs from world activity (BEFORE decay so needs oscillate)
    fulfill_events = fulfill_npc_needs(
        npcs_data,
        activity_actions,
        activity_chat,
        activity_trades,
    )
    events.extend(fulfill_events)

    # Decay NPC needs
    npc_events = decay_npc_needs(npcs_data)
    events.extend(npc_events)

    # Evolve agent traits based on behavior (rappterbook-style drift)
    trait_events = evolve_agent_traits(agents_data, activity_actions, activity_chat)
    events.extend(trait_events)

    # Fulfill agent goals based on recent actions
    system_agent_ids = {
        agent["id"]
        for agent in agents_data.get("agents", [])
        if agent.get("controller", "system") == "system"
    }
    goal_events = fulfill_agent_goals(
        activity_actions,
        activity_chat,
        timestamp,
        system_agent_ids,
    )
    events.extend(goal_events)

    # Resolve combat — defensive swarm
    combat_events = resolve_combat(game_state, agents_data, actions_data, chat_data, timestamp)
    events.extend(combat_events)

    # Resolve trades
    trade_events = resolve_pending_trades(trades_data, actions_data, timestamp)
    events.extend(trade_events)

    # Decay stale relationships (social graph maintenance)
    rel_data = load_json(STATE_DIR / "relationships.json")
    rel_events = decay_stale_relationships(rel_data, timestamp)
    events.extend(rel_events)

    agents_changed = agents_before != json.dumps(
        agents_data.get("agents", []),
        sort_keys=True,
        separators=(",", ":"),
    )
    if not events and not activity_cursor_changed and not agents_changed:
        print(f"[{timestamp}] No state changes this tick")
        return

    # Update timestamps
    game_state.setdefault("_meta", {})["lastUpdate"] = timestamp
    npcs_data.setdefault("_meta", {})["lastUpdate"] = timestamp

    # Save state
    save_json(STATE_DIR / "game_state.json", game_state)
    save_json(STATE_DIR / "npcs.json", npcs_data)
    if combat_events or agents_changed:
        save_json(STATE_DIR / "agents.json", agents_data)
    if combat_events:
        save_json(STATE_DIR / "chat.json", chat_data)
    if trade_events:
        save_json(STATE_DIR / "trades.json", trades_data)
    if rel_events:
        rel_data.setdefault("_meta", {})["lastUpdate"] = timestamp
        save_json(STATE_DIR / "relationships.json", rel_data)

    # Update feed
    update_activity_feed(feed_data, events, timestamp)
    save_json(BASE_DIR / "feed" / "activity.json", feed_data)

    print(f"[{timestamp}] Tick processed: {len(events)} events")
    for event in events:
        print(f"  • {event}")


if __name__ == "__main__":
    main()
