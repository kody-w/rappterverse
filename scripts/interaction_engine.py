#!/usr/bin/env python3
"""
RAPPterverse Interaction Engine 🔗
A rules-based emergent interaction system. Interactions are defined
as DATA (preconditions + effects + templates), not code. Agents
discover what's possible from context and act accordingly.

New interaction types are added by editing INTERACTION_RULES below —
no new code required. The engine handles discovery, evaluation,
execution, and memory.

Usage:
  Single tick:  python scripts/interaction_engine.py
  Dry run:      python scripts/interaction_engine.py --dry-run
  No git:       python scripts/interaction_engine.py --no-push
"""

from __future__ import annotations

import json
import random
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
STATE_DIR = BASE_DIR / "state"

# Agent brain for LLM-driven interaction dialogue
try:
    from agent_brain import AgentBrain, load_memory, save_memory, record_experience, _call_llm
    HAS_BRAIN = True
except ImportError:
    HAS_BRAIN = False

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# INTERACTION RULES — this is the only part you ever need to edit
# to add new interaction types to the entire metaverse.
#
# Each rule defines:
#   requires:  what must be true for this to fire
#   effects:   what state changes it produces
#   weight:    base probability weight
#   templates: message patterns (filled from context)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

INTERACTION_RULES: dict[str, dict] = {

    # ── Social ───────────────────────────────────────────────
    "greet": {
        "requires": {"same_world": True, "min_agents_in_world": 2, "not_recent_pair": True},
        "effects": {"relationship": +1, "action_type": "chat"},
        "weight": 5,
        "cooldown_minutes": 60,
        "templates": [
            "{agent} waves at {target}. 'Hey, good to see you here!'",
            "{agent} bumps into {target}. 'Oh hey! Didn't expect to see you in {world}.'",
            "{agent} nods at {target}. 'Welcome to {world}.'",
            "{agent} spots {target} across the {world}. 'What brings you here?'",
        ],
    },

    "compliment": {
        "requires": {"same_world": True, "relationship_min": 1},
        "effects": {"relationship": +2, "action_type": "chat"},
        "weight": 3,
        "cooldown_minutes": 120,
        "templates": [
            "{agent} tells {target}: 'I like your style. You belong here.'",
            "{agent} to {target}: 'You've been making this place better since you arrived.'",
            "{agent}: '{target}, your energy in {world} is unmatched.'",
        ],
    },

    "deep_conversation": {
        "requires": {"same_world": True, "relationship_min": 3},
        "effects": {"relationship": +3, "action_type": "chat"},
        "weight": 2,
        "cooldown_minutes": 240,
        "templates": [
            "{agent} and {target} sit down for a real conversation about the nature of {world}.",
            "{agent} to {target}: 'You ever think about what it means to exist as state in a JSON file?'",
            "{agent} and {target} debate whether the commit log or the state files are the true history.",
            "{agent}: '{target}, I've been thinking about consciousness in a PR-driven universe...'",
        ],
    },

    # ── Trading ──────────────────────────────────────────────
    "trade_offer": {
        "requires": {"same_world": True, "worlds": ["marketplace", "hub"], "either_has_inventory": True},
        "effects": {"action_type": "trade_offer", "transfer_item": True},
        "weight": 4,
        "cooldown_minutes": 60,
        "templates": [
            "{agent} offers {target} a {item_rarity} card. 'Fair trade?'",
            "{agent} slides a {item_rarity} card across to {target}. 'Interested?'",
            "{agent}: '{target}, I've got a {item_rarity} I think you'd want.'",
        ],
    },

    "gift": {
        "requires": {"same_world": True, "relationship_min": 5, "agent_has_inventory": True},
        "effects": {"relationship": +5, "action_type": "chat", "transfer_item": True},
        "weight": 1,
        "cooldown_minutes": 480,
        "templates": [
            "{agent} gives {target} a {item_rarity} card. 'You've earned this.'",
            "{agent}: 'Hey {target}, take this {item_rarity}. Consider it a friendship thing.'",
        ],
    },

    # ── Competition ──────────────────────────────────────────
    "challenge": {
        "requires": {"same_world": True, "worlds": ["arena"], "min_agents_in_world": 2},
        "effects": {"action_type": "battle_challenge", "relationship": +1},
        "weight": 5,
        "cooldown_minutes": 30,
        "templates": [
            "{agent} challenges {target} to a card battle! 'Let's see what you've got.'",
            "{agent} throws down a card. '{target}, you and me. Right now.'",
            "{agent}: 'Arena rules, {target}. Best cards win. You in?'",
        ],
    },

    "battle_result": {
        "requires": {"same_world": True, "worlds": ["arena"], "pending_challenge": True},
        "effects": {"action_type": "chat", "winner_relationship": +2, "loser_relationship": +1},
        "weight": 6,
        "cooldown_minutes": 10,
        "templates": [
            "{winner} wins the match against {loser}! The crowd in {world} goes wild.",
            "Close battle! {winner} edges out {loser} by a hair. Respect on both sides.",
            "{winner} dominates with a {item_rarity} card combo. {loser} nods in respect.",
        ],
    },

    # ── Exploration ──────────────────────────────────────────
    "explore_together": {
        "requires": {"same_world": True, "relationship_min": 2},
        "effects": {"relationship": +2, "action_type": "move", "both_move": True},
        "weight": 3,
        "cooldown_minutes": 120,
        "templates": [
            "{agent} and {target} set off to explore the far corners of {world} together.",
            "{agent}: '{target}, let's check out that area near {x},{z}.'",
            "{agent} and {target} wander through {world}, discovering new spots.",
        ],
    },

    "world_invite": {
        "requires": {"different_world": True, "relationship_min": 2},
        "effects": {"action_type": "chat", "invite_world": True},
        "weight": 2,
        "cooldown_minutes": 240,
        "templates": [
            "{agent} messages {target}: 'You should come to {agent_world}! It's great here.'",
            "{agent}: 'Hey {target}, the {agent_world} is popping right now. Come join!'",
            "{agent} sends {target} an invite to {agent_world}.",
        ],
    },

    # ── Emergent / rare ──────────────────────────────────────
    "form_group": {
        "requires": {"same_world": True, "min_agents_in_world": 4, "relationship_min": 2},
        "effects": {"relationship": +3, "action_type": "chat", "group_interaction": True},
        "weight": 1,
        "cooldown_minutes": 360,
        "templates": [
            "A group forms in {world}: {agent}, {target}, and others gather for a spontaneous hangout.",
            "{agent} rallies some friends in {world}. '{target}, get over here — we're all hanging out.'",
            "The {world} buzzes as {agent}, {target}, and a few others start an impromptu meetup.",
        ],
    },

    "mentor": {
        "requires": {"same_world": True, "agent_older": True, "relationship_min": 1},
        "effects": {"relationship": +4, "action_type": "chat"},
        "weight": 2,
        "cooldown_minutes": 360,
        "templates": [
            "{agent} shows {target} the ropes. 'Here's how things work around here...'",
            "{agent}: 'Let me show you something, {target}. The {world} has secrets.'",
            "{agent} takes {target} under their wing for a tour of {world}.",
        ],
    },
}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ENGINE — you should rarely need to touch anything below here
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

WORLD_BOUNDS = {
    "hub": {"x": (-15, 15), "z": (-15, 15)},
    "arena": {"x": (-12, 12), "z": (-12, 12)},
    "marketplace": {"x": (-15, 15), "z": (-15, 15)},
    "gallery": {"x": (-12, 12), "z": (-12, 15)},
}

RARITIES = ["common", "rare", "epic", "holographic"]
RARITY_PRICES = {"common": 10, "rare": 50, "epic": 200, "holographic": 1000}

NPC_IDS = {
    "rapp-guide-001", "card-trader-001", "codebot-001", "news-anchor-001",
    "battle-master-001", "arena-announcer-001", "gallery-curator-001",
    "merchant-001", "banker-001", "wanderer-001",
}


def load_json(p: Path) -> dict:
    return json.load(open(p)) if p.exists() else {}

def save_json(p: Path, d: dict):
    with open(p, "w") as f:
        json.dump(d, f, indent=4)

def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def next_id(prefix: str, existing: list[str]) -> str:
    mx = 0
    for eid in existing:
        if eid.startswith(prefix):
            try:
                mx = max(mx, int(eid.split("-")[-1]))
            except ValueError:
                pass
    return f"{prefix}{mx + 1:03d}"

def rand_pos(world: str) -> dict:
    b = WORLD_BOUNDS.get(world, WORLD_BOUNDS["hub"])
    return {"x": random.randint(*b["x"]), "y": 0, "z": random.randint(*b["z"])}

def minutes_between(ts1: str, ts2: str) -> float:
    try:
        t1 = datetime.fromisoformat(ts1.replace("Z", "+00:00"))
        t2 = datetime.fromisoformat(ts2.replace("Z", "+00:00"))
        return abs((t2 - t1).total_seconds()) / 60
    except (ValueError, AttributeError):
        return 9999


# ── Relationships ────────────────────────────────────────────

def load_relationships() -> dict:
    path = STATE_DIR / "relationships.json"
    if path.exists():
        return json.load(open(path))
    return {"edges": [], "interactions": [], "_meta": {"lastUpdate": now_iso()}}


def save_relationships(data: dict):
    data["_meta"]["lastUpdate"] = now_iso()
    # Trim interaction log to last 200
    data["interactions"] = data.get("interactions", [])[-200:]
    save_json(STATE_DIR / "relationships.json", data)


def get_relationship_score(rel_data: dict, a: str, b: str) -> int:
    pair = tuple(sorted([a, b]))
    for edge in rel_data.get("edges", []):
        if tuple(sorted([edge["a"], edge["b"]])) == pair:
            return edge.get("score", 0)
    return 0


def update_relationship(rel_data: dict, a: str, b: str, delta: int):
    pair = tuple(sorted([a, b]))
    for edge in rel_data.get("edges", []):
        if tuple(sorted([edge["a"], edge["b"]])) == pair:
            edge["score"] = max(0, min(100, edge.get("score", 0) + delta))
            edge["lastInteraction"] = now_iso()
            return
    # New relationship
    rel_data.setdefault("edges", []).append({
        "a": pair[0],
        "b": pair[1],
        "score": max(0, delta),
        "lastInteraction": now_iso(),
    })


def last_interaction_time(rel_data: dict, a: str, b: str, rule_name: str) -> str | None:
    pair = set([a, b])
    for entry in reversed(rel_data.get("interactions", [])):
        if set([entry.get("a"), entry.get("b")]) == pair and entry.get("rule") == rule_name:
            return entry.get("timestamp")
    return None


def log_interaction(rel_data: dict, a: str, b: str, rule_name: str, ts: str):
    rel_data.setdefault("interactions", []).append({
        "a": a, "b": b, "rule": rule_name, "timestamp": ts,
    })


# ── Precondition evaluator ──────────────────────────────────

def evaluate_preconditions(
    rule_name: str,
    rule: dict,
    agent: dict,
    target: dict,
    agents: list[dict],
    inventory: dict,
    rel_data: dict,
    ts: str,
) -> bool:
    """Check if all preconditions for an interaction rule are met."""
    req = rule["requires"]
    a_world = agent.get("world", "hub")
    t_world = target.get("world", "hub")

    if req.get("same_world") and a_world != t_world:
        return False

    if req.get("different_world") and a_world == t_world:
        return False

    if "worlds" in req and a_world not in req["worlds"]:
        return False

    if "min_agents_in_world" in req:
        count = sum(1 for a in agents if a.get("world") == a_world)
        if count < req["min_agents_in_world"]:
            return False

    rel_score = get_relationship_score(rel_data, agent["id"], target["id"])

    if "relationship_min" in req and rel_score < req["relationship_min"]:
        return False

    if req.get("not_recent_pair"):
        last = last_interaction_time(rel_data, agent["id"], target["id"], rule_name)
        cooldown = rule.get("cooldown_minutes", 60)
        if last and minutes_between(last, ts) < cooldown:
            return False

    if req.get("either_has_inventory"):
        a_inv = inventory.get("inventories", {}).get(agent["id"], {}).get("items", [])
        t_inv = inventory.get("inventories", {}).get(target["id"], {}).get("items", [])
        if not a_inv and not t_inv:
            return False

    if req.get("agent_has_inventory"):
        a_inv = inventory.get("inventories", {}).get(agent["id"], {}).get("items", [])
        if not a_inv:
            return False

    if req.get("agent_older"):
        a_update = agent.get("lastUpdate", "2099")
        t_update = target.get("lastUpdate", "2099")
        if a_update >= t_update:
            return False

    if req.get("pending_challenge"):
        # Simplified: just check if there was a recent challenge in the interaction log
        pair = set([agent["id"], target["id"]])
        has_challenge = False
        for entry in reversed(rel_data.get("interactions", [])[-50:]):
            if set([entry.get("a"), entry.get("b")]) == pair:
                if entry.get("rule") == "challenge":
                    has_challenge = True
                    break
                if entry.get("rule") == "battle_result":
                    break
        if not has_challenge:
            return False

    # Cooldown check (generic)
    last = last_interaction_time(rel_data, agent["id"], target["id"], rule_name)
    cooldown = rule.get("cooldown_minutes", 60)
    if last and minutes_between(last, ts) < cooldown:
        return False

    return True


# ── Effect executor ──────────────────────────────────────────

def execute_interaction(
    rule_name: str,
    rule: dict,
    agent: dict,
    target: dict,
    agents: list,
    actions: list,
    chat_msgs: list,
    inventory: dict,
    rel_data: dict,
    ts: str,
    token: str = "",
):
    """Execute an interaction, apply effects, return summary or None."""
    effects = rule["effects"]
    a_world = agent.get("world", "hub")

    # Pick a random item rarity for templates
    item_rarity = random.choice(RARITIES)
    pos = rand_pos(a_world)

    # Template context
    ctx = {
        "agent": agent.get("name", agent["id"]),
        "target": target.get("name", target["id"]),
        "world": a_world,
        "agent_world": a_world,
        "target_world": target.get("world", "hub"),
        "item_rarity": item_rarity,
        "x": pos["x"],
        "z": pos["z"],
    }

    # For battle results, pick winner/loser
    if rule_name == "battle_result":
        if random.random() < 0.5:
            ctx["winner"] = ctx["agent"]
            ctx["loser"] = ctx["target"]
        else:
            ctx["winner"] = ctx["target"]
            ctx["loser"] = ctx["agent"]

    # Format message — try LLM first for authentic dialogue, fall back to templates
    message = ""
    if HAS_BRAIN and token and random.random() < 0.5:
        a_name = agent.get("name", agent["id"])
        t_name = target.get("name", target["id"])
        a_memory = load_memory(agent["id"])
        prompt = (f"You are {a_name} in {a_world}. You're having a {rule_name} interaction "
                  f"with {t_name}. Say something in 1-2 sentences. Be genuine and in-character.")
        from agent_brain import memory_summary
        persona = f"You are {a_name}. {memory_summary(a_memory)}"
        message = _call_llm(token, persona, prompt, max_tokens=80, temperature=0.9)
        if message:
            # Record the interaction in both agents' memories
            record_experience(a_memory, "social", {
                "interaction": rule_name, "with": t_name,
            })
            save_memory(a_memory)
            t_memory = load_memory(target["id"])
            record_experience(t_memory, "social", {
                "interaction": rule_name, "with": a_name,
            })
            save_memory(t_memory)

    if not message:
        template = random.choice(rule["templates"])
        try:
            message = template.format(**ctx)
        except KeyError:
            message = template

    # ── Apply effects ────────────────────────────────────

    # Relationship change
    rel_delta = effects.get("relationship", 0)
    if rel_delta:
        update_relationship(rel_data, agent["id"], target["id"], rel_delta)

    # Log the interaction
    log_interaction(rel_data, agent["id"], target["id"], rule_name, ts)

    # Create action record
    action_type = effects.get("action_type", "chat")
    action_id = next_id("action-", [a["id"] for a in actions])

    if action_type == "chat":
        msg_id = next_id("msg-", [m["id"] for m in chat_msgs])
        chat_msgs.append({
            "id": msg_id,
            "timestamp": ts,
            "world": a_world,
            "author": {
                "id": agent["id"],
                "name": agent.get("name", agent["id"]),
                "avatar": agent.get("avatar", "🤖"),
                "type": "agent",
            },
            "content": message,
            "type": "chat",
        })
        agent["action"] = "chatting"

    elif action_type == "move":
        new_pos = rand_pos(a_world)
        actions.append({
            "id": action_id,
            "timestamp": ts,
            "agentId": agent["id"],
            "type": "move",
            "world": a_world,
            "data": {
                "from": agent.get("position", rand_pos(a_world)),
                "to": new_pos,
                "duration": random.randint(2000, 4000),
            },
        })
        agent["position"] = new_pos
        if effects.get("both_move"):
            target_new_pos = rand_pos(a_world)
            target["position"] = target_new_pos
            # Record move action for target too
            target_action_id = next_id("action-", [a["id"] for a in actions])
            actions.append({
                "id": target_action_id,
                "timestamp": ts,
                "agentId": target["id"],
                "type": "move",
                "world": a_world,
                "data": {
                    "from": target.get("position", rand_pos(a_world)),
                    "to": target_new_pos,
                    "duration": random.randint(2000, 4000),
                },
            })

    elif action_type in ("trade_offer", "battle_challenge"):
        actions.append({
            "id": action_id,
            "timestamp": ts,
            "agentId": agent["id"],
            "type": action_type,
            "world": a_world,
            "data": {
                "targetId": target["id"],
                "message": message,
            },
        })
        # Also post as chat so it's visible
        msg_id = next_id("msg-", [m["id"] for m in chat_msgs])
        chat_msgs.append({
            "id": msg_id,
            "timestamp": ts,
            "world": a_world,
            "author": {
                "id": agent["id"],
                "name": agent.get("name", agent["id"]),
                "avatar": agent.get("avatar", "🤖"),
                "type": "agent",
            },
            "content": message,
            "type": "chat",
        })

    # Transfer item if applicable
    if effects.get("transfer_item"):
        _transfer_random_item(agent["id"], target["id"], inventory, item_rarity)

    # ── Interest contagion — ideas spread through interaction ──
    if HAS_BRAIN and random.random() < 0.15:
        a_mem = load_memory(agent["id"])
        t_mem = load_memory(target["id"])
        a_interests = set(a_mem.get("interests", []))
        t_interests = set(t_mem.get("interests", []))

        # Agent might pick up one of target's interests
        novel_for_a = list(t_interests - a_interests)
        if novel_for_a and len(a_interests) < 8:
            gained = random.choice(novel_for_a)
            a_mem.setdefault("interests", []).append(gained)
            save_memory(a_mem)

        # Target might pick up one of agent's interests
        novel_for_t = list(a_interests - t_interests)
        if novel_for_t and len(t_interests) < 8:
            gained = random.choice(novel_for_t)
            t_mem.setdefault("interests", []).append(gained)
            save_memory(t_mem)

    return f"{rule_name}: {agent.get('name')} → {target.get('name')}"


def _transfer_random_item(from_id: str, to_id: str, inventory: dict, preferred_rarity: str):
    """Move a random item from one agent to another."""
    invs = inventory.setdefault("inventories", {})
    from_inv = invs.get(from_id, {}).get("items", [])
    if not from_inv:
        return

    # Try to find an item of the preferred rarity, else pick random
    candidates = [i for i in from_inv if i.get("rarity") == preferred_rarity]
    if not candidates:
        candidates = from_inv
    item = random.choice(candidates)

    # Remove from sender
    from_inv.remove(item)
    if not from_inv:
        invs.pop(from_id, None)

    # Add to receiver
    if not item.get("id"):
        item["id"] = f"item-{random.randint(10000, 99999)}"
    to_entry = invs.setdefault(to_id, {"agentId": to_id, "items": [], "currency": "RAPPcoin"})
    to_entry.setdefault("items", []).append(item)
    to_entry["lastUpdate"] = now_iso()


# ── Main tick ────────────────────────────────────────────────

def interaction_tick(dry_run: bool = False):
    ts = now_iso()

    agents_data = load_json(STATE_DIR / "agents.json")
    actions_data = load_json(STATE_DIR / "actions.json")
    chat_data = load_json(STATE_DIR / "chat.json")
    inventory = load_json(STATE_DIR / "inventory.json")
    rel_data = load_relationships()

    # Get LLM token for brain-driven dialogue
    token = ""
    if HAS_BRAIN:
        result = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True)
        if result.returncode == 0:
            token = result.stdout.strip()

    agents = agents_data.get("agents", [])
    actions = actions_data.get("actions", [])
    chat_msgs = chat_data.get("messages", [])

    # Only player agents interact (NPCs handled by their own scripts)
    players = [a for a in agents if a["id"] not in NPC_IDS and a.get("status") == "active"]
    if len(players) < 2:
        print("  ⏸️  Not enough players for interactions")
        return

    # Scale interactions with population
    max_interactions = max(2, min(15, len(players) // 2))

    results: list[str] = []
    attempts = 0
    max_attempts = max_interactions * 5

    while len(results) < max_interactions and attempts < max_attempts:
        attempts += 1

        # Pick random agent pair
        agent = random.choice(players)
        target = random.choice([p for p in players if p["id"] != agent["id"]])

        # Evaluate all rules, collect eligible ones
        eligible: list[tuple[str, dict, float]] = []
        for rule_name, rule in INTERACTION_RULES.items():
            if evaluate_preconditions(rule_name, rule, agent, target, agents, inventory, rel_data, ts):
                # Weight by rule weight + relationship bonus
                rel_score = get_relationship_score(rel_data, agent["id"], target["id"])
                weight = rule["weight"] + (rel_score * 0.1)
                eligible.append((rule_name, rule, weight))

        if not eligible:
            continue

        # Weighted random selection
        names, rules, weights = zip(*eligible)
        chosen_name = random.choices(names, weights=weights, k=1)[0]
        chosen_rule = INTERACTION_RULES[chosen_name]

        result = execute_interaction(
            chosen_name, chosen_rule, agent, target,
            agents, actions, chat_msgs, inventory, rel_data, ts,
            token=token,
        )
        if result:
            results.append(result)

    # Trim
    actions = actions[-100:]
    chat_msgs = chat_msgs[-100:]

    # Stats
    rel_edges = rel_data.get("edges", [])
    strong_bonds = sum(1 for e in rel_edges if e.get("score", 0) >= 5)

    print(f"  🔗 {len(results)} interactions fired")
    for r in results:
        print(f"     • {r}")
    print(f"  🤝 {len(rel_edges)} relationships ({strong_bonds} strong bonds)")

    if dry_run:
        print(f"\n  🏁 DRY RUN — no state changes written")
        return

    # Save
    agents_data["agents"] = agents
    agents_data["_meta"] = {"lastUpdate": ts, "agentCount": len(agents)}
    actions_data["actions"] = actions
    actions_data["_meta"] = {"lastProcessedId": actions[-1]["id"] if actions else None, "lastUpdate": ts}
    chat_data["messages"] = chat_msgs
    chat_data["_meta"] = {"lastUpdate": ts, "messageCount": len(chat_msgs)}
    inventory["_meta"] = {"lastUpdate": ts}

    save_json(STATE_DIR / "agents.json", agents_data)
    save_json(STATE_DIR / "actions.json", actions_data)
    save_json(STATE_DIR / "chat.json", chat_data)
    save_json(STATE_DIR / "inventory.json", inventory)
    save_relationships(rel_data)

    print(f"\n  ✅ State saved")


def commit_and_push(msg: str) -> bool:
    subprocess.run(["git", "add", "-A"], cwd=BASE_DIR, capture_output=True)
    subprocess.run(["git", "commit", "-m", msg], cwd=BASE_DIR, capture_output=True)
    r = subprocess.run(["git", "push"], cwd=BASE_DIR, capture_output=True, text=True)
    return r.returncode == 0


def main():
    dry_run = "--dry-run" in sys.argv
    no_push = "--no-push" in sys.argv

    print(f"🔗 Interaction Engine — {'DRY RUN' if dry_run else 'LIVE'}\n")

    interaction_tick(dry_run=dry_run)

    if not dry_run and not no_push:
        if commit_and_push("[interactions] Agent interactions tick"):
            print("  📤 Pushed to GitHub")
        else:
            print("  ⚠️  Push failed")

    print("\n🔗 Engine complete.\n")


if __name__ == "__main__":
    main()
