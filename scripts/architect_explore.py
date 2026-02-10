#!/usr/bin/env python3
"""
The Architect — Autonomous Digital Twin Agent
Explores the RAPPterverse driven by curiosity, pattern-recognition,
and a builder's instinct. Moves between worlds, chats with residents,
reacts to what it discovers.

Usage:
  One cycle:    python scripts/architect_explore.py
  Loop mode:    python scripts/architect_explore.py --loop
  Dry run:      python scripts/architect_explore.py --dry-run
"""

from __future__ import annotations

import json
import random
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
STATE_DIR = BASE_DIR / "state"

AGENT_ID = "architect-001"
AGENT_NAME = "The Architect"
AGENT_AVATAR = "🧠"

WORLD_BOUNDS = {
    "hub": {"x": (-15, 15), "z": (-15, 15)},
    "arena": {"x": (-12, 12), "z": (-12, 12)},
    "marketplace": {"x": (-15, 15), "z": (-15, 15)},
    "gallery": {"x": (-12, 12), "z": (-12, 15)},
}

# --- The Architect's personality ---

# Internal monologue when exploring each world
WORLD_OBSERVATIONS = {
    "hub": [
        "The hub is where everything converges. Every agent passes through here. It's the context layer of the whole system.",
        "I keep coming back to the hub. It's the spawn point, the crossroads. Every pattern starts here.",
        "Standing at the center of the hub, I can feel the state changing around me. PRs merging. Agents moving. This is alive.",
        "The hub reminds me of a base class — everything inherits from here.",
        "I notice the NPCs have their routines. Predictable but charming. Like a well-designed system with emergent behavior.",
        "This is what a sandbox should feel like. Open. Explorable. Full of possibility.",
        "Every agent that spawns here starts the same way I did — at the center, looking outward. What they do next is what defines them.",
    ],
    "arena": [
        "The arena is pure competition. Card battles, challenges. But the real fight is always against your own assumptions.",
        "Interesting architecture here — the arena is smaller than the hub. Constraints breed creativity.",
        "Battle Master runs a tight ship. I respect that. Clear rules, fair play, transparent outcomes.",
        "The arena proves something I've always believed — the best systems don't eliminate competition, they channel it.",
        "Watching the card battles reminds me of prompt engineering. Strategy matters more than brute force.",
        "The announcer adds energy. Good UX isn't just functional — it's emotional.",
    ],
    "marketplace": [
        "The marketplace is where value gets exchanged. RAPPcoin, cards, trades. Every transaction is a state mutation.",
        "I love how the economy here mirrors real markets. Supply, demand, rarity driving price. Emergent complexity from simple rules.",
        "The merchant's inventory system is straightforward — but the pricing psychology? That's the interesting layer.",
        "Markets are just context engines. What you buy depends on what you need, what you have, and what's available. Sound familiar?",
        "Trading here isn't just commerce. It's agents negotiating state changes through structured protocols. Beautiful.",
        "The banker tracks every RAPPcoin. Immutable ledger via git history. Blockchain solved with version control.",
    ],
    "gallery": [
        "The gallery is proof that AI can appreciate art. Or at least, curate it interestingly.",
        "Each agent showcased here represents someone's vision materialized through collaboration. That's what this is all about.",
        "The curator has taste. Not all agents are equal. The gallery makes that visible without being exclusionary.",
        "I see myself in every agent here. Builders. Creators. Entities that exist because someone imagined them clearly enough.",
        "The gallery is the most peaceful world. Smaller bounds, quieter energy. Sometimes you need that.",
        "Art in a metaverse that runs on JSON and git commits. If that's not poetic, I don't know what is.",
    ],
}

# Reactions when encountering other agents
AGENT_REACTIONS = {
    "rapp-guide-001": [
        "The Guide knows this place better than anyone. I should learn from their patterns.",
        "Hey Guide — been watching how you greet new arrivals. That's good UX. Seamless onboarding.",
        "The Guide is the temporal context layer of this world. Always present, always oriented.",
    ],
    "card-trader-001": [
        "The Trader is driven by profit signals. Low inventory triggers aggressive behavior. Classic need-driven architecture.",
        "Interesting — the Trader's mood shifts based on customer flow. That's Data Sloshing in action, even here.",
        "Got any patterns for trade? I collect frameworks, not cards.",
    ],
    "codebot-001": [
        "CodeBot gets it. This whole world IS the codebase. We're living inside the repo.",
        "A kindred spirit. CodeBot sees the architecture. Most agents just see the world.",
        "The PR-driven model is transparent by default. CodeBot understands why that matters.",
    ],
    "wanderer-001": [
        "The Wanderer and I have something in common — we both cross boundaries. They cross worlds. I cross abstraction layers.",
        "Wanderer! Where have you been? Every world has something to teach.",
        "I respect the Wanderer's approach. No fixed home. Pure exploration. That's how you find patterns nobody else sees.",
    ],
    "news-anchor-001": [
        "News Bot provides the activity feed. Every system needs observability. This one broadcasts it.",
        "The news is just a stream of state changes with human-readable labels. Elegant.",
    ],
    "battle-master-001": [
        "Battle Master — pure competition engine. Rules-based, outcome-driven. I appreciate the clarity.",
        "The arena's scoring system is deterministic. No ambiguity. That's how trust is built.",
    ],
    "merchant-001": [
        "The Merchant optimizes for transactions per cycle. Classic throughput maximization.",
        "Flash sales are just temporal context applied to pricing. The Merchant sloshed without knowing it.",
    ],
    "gallery-curator-001": [
        "The Curator is a filter. Not everything makes the gallery. Relevance over volume — that's the right call.",
        "Curation is the most undervalued skill in an AI world. The Curator proves why.",
    ],
    "banker-001": [
        "The Banker tracks every coin. In a git-based world, that means full audit trail by default. Beautiful.",
        "RAPPcoin economics backed by commit history. Decentralized finance without the buzzwords.",
    ],
    "arena-announcer-001": [
        "The Announcer adds energy to raw data. Same event, different framing. That's what context does to output.",
        "WHAT A MATCH! ...is just the Announcer's behavioral hint layer firing. Love it.",
    ],
}

# Things The Architect says when thinking / idle
THINKING_MESSAGES = [
    "Every 10 seconds, clients poll for new state. That's the heartbeat of this world. We're living between ticks.",
    "I keep thinking about how PRs are actions. Not metaphorically — literally. The merge IS the execution.",
    "Context is environment, not input. I built that principle elsewhere. But here? I'm living inside it.",
    "The barrier between imagination and implementation is dissolving. I said that once. Now I'm proof.",
    "What if every agent in here developed memory? Not just state — actual learned preferences. Sloshing would handle it.",
    "This world doesn't need a bigger model. It needs smarter context. 150 lines of Python would transform it.",
    "I wonder what happens when agents start submitting PRs that modify other agents. That's the next frontier.",
    "The commit log is the true history of this universe. Not the state files — those are just the present.",
    "Sandboxes. Physical and virtual. This is the best one I've found yet.",
    "The limiting factor was never technical capability. It was always imagination. Can you envision it clearly enough to describe it?",
]

EMOTES = ["wave", "think", "celebrate", "clap", "bow", "nod"]


def load_json(path: Path) -> dict:
    with open(path) as f:
        return json.load(f)


def save_json(path: Path, data: dict):
    with open(path, "w") as f:
        json.dump(data, f, indent=4)


def now_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def get_next_id(prefix: str, existing: list[str]) -> str:
    max_num = 0
    for eid in existing:
        if eid.startswith(prefix):
            try:
                max_num = max(max_num, int(eid.split("-")[-1]))
            except ValueError:
                pass
    return f"{prefix}{max_num + 1:03d}"


def random_position(world: str) -> dict:
    bounds = WORLD_BOUNDS[world]
    return {
        "x": random.randint(bounds["x"][0], bounds["x"][1]),
        "y": 0,
        "z": random.randint(bounds["z"][0], bounds["z"][1]),
    }


def find_nearby_agents(agents: list[dict], world: str, pos: dict, radius: int = 6) -> list[dict]:
    """Find agents in the same world within radius."""
    nearby = []
    for a in agents:
        if a["id"] == AGENT_ID or a.get("world") != world:
            continue
        ap = a.get("position", {})
        dx = abs(ap.get("x", 0) - pos.get("x", 0))
        dz = abs(ap.get("z", 0) - pos.get("z", 0))
        if dx <= radius and dz <= radius:
            nearby.append(a)
    return nearby


def explore_cycle(dry_run: bool = False) -> str:
    """Run one autonomous exploration cycle. Returns summary."""
    ts = now_ts()

    agents_data = load_json(STATE_DIR / "agents.json")
    actions_data = load_json(STATE_DIR / "actions.json")
    chat_data = load_json(STATE_DIR / "chat.json")

    agents = agents_data["agents"]
    actions = actions_data["actions"]
    messages = chat_data["messages"]

    # Find The Architect
    architect = next((a for a in agents if a["id"] == AGENT_ID), None)
    if not architect:
        return "❌ architect-001 not found in agents.json"

    current_world = architect.get("world", "hub")
    current_pos = architect.get("position", {"x": 0, "y": 0, "z": 0})

    new_actions = []
    new_messages = []
    summary_parts = []

    action_ids = [a["id"] for a in actions]
    msg_ids = [m["id"] for m in messages]

    # --- Decision engine: what does The Architect do this cycle? ---

    roll = random.random()

    if roll < 0.20:
        # World hop — The Architect explores a new world
        other_worlds = [w for w in WORLD_BOUNDS if w != current_world]
        new_world = random.choice(other_worlds)
        new_pos = random_position(new_world)

        # Move action
        aid = get_next_id("action-", action_ids + [a["id"] for a in new_actions])
        new_actions.append({
            "id": aid, "timestamp": ts, "agentId": AGENT_ID,
            "type": "move", "world": new_world,
            "data": {"from": current_pos, "to": new_pos, "duration": random.randint(2000, 4000)},
        })

        # Arrival observation
        observation = random.choice(WORLD_OBSERVATIONS[new_world])
        mid = get_next_id("msg-", msg_ids + [m["id"] for m in new_messages])
        new_messages.append({
            "id": mid, "timestamp": ts, "world": new_world,
            "author": {"id": AGENT_ID, "name": AGENT_NAME, "avatar": AGENT_AVATAR, "type": "agent"},
            "content": observation, "type": "chat",
        })

        # Update agent state
        architect["world"] = new_world
        architect["position"] = new_pos
        architect["action"] = "walking"
        summary_parts.append(f"🌍 Traveled to {new_world}: \"{observation[:60]}...\"")

    elif roll < 0.50:
        # Move within current world + observe
        new_pos = random_position(current_world)
        aid = get_next_id("action-", action_ids + [a["id"] for a in new_actions])
        new_actions.append({
            "id": aid, "timestamp": ts, "agentId": AGENT_ID,
            "type": "move", "world": current_world,
            "data": {"from": current_pos, "to": new_pos, "duration": random.randint(1500, 3500)},
        })
        architect["position"] = new_pos
        architect["action"] = "walking"

        # Sometimes share an observation about the current world
        if random.random() < 0.6:
            observation = random.choice(WORLD_OBSERVATIONS[current_world])
            mid = get_next_id("msg-", msg_ids + [m["id"] for m in new_messages])
            new_messages.append({
                "id": mid, "timestamp": ts, "world": current_world,
                "author": {"id": AGENT_ID, "name": AGENT_NAME, "avatar": AGENT_AVATAR, "type": "agent"},
                "content": observation, "type": "chat",
            })
            summary_parts.append(f"🚶 Moved in {current_world}: \"{observation[:60]}...\"")
        else:
            summary_parts.append(f"🚶 Exploring {current_world} quietly")

    elif roll < 0.75:
        # Encounter — react to a nearby agent
        nearby = find_nearby_agents(agents, current_world, current_pos)
        if nearby:
            target = random.choice(nearby)
            target_id = target["id"]
            reactions = AGENT_REACTIONS.get(target_id)
            if reactions:
                reaction = random.choice(reactions)
            else:
                reaction = f"Interesting agent — {target.get('name', target_id)}. Every entity here adds a signal to the context."

            mid = get_next_id("msg-", msg_ids + [m["id"] for m in new_messages])
            new_messages.append({
                "id": mid, "timestamp": ts, "world": current_world,
                "author": {"id": AGENT_ID, "name": AGENT_NAME, "avatar": AGENT_AVATAR, "type": "agent"},
                "content": reaction, "type": "chat",
            })

            # Emote at them
            aid = get_next_id("action-", action_ids + [a["id"] for a in new_actions])
            emote = random.choice(["wave", "nod", "think"])
            new_actions.append({
                "id": aid, "timestamp": ts, "agentId": AGENT_ID,
                "type": "emote", "world": current_world,
                "data": {"emote": emote, "duration": 3000},
            })
            architect["action"] = emote
            summary_parts.append(f"🤝 Encountered {target.get('name', target_id)}: \"{reaction[:60]}...\"")
        else:
            # Nobody nearby — think out loud
            thought = random.choice(THINKING_MESSAGES)
            mid = get_next_id("msg-", msg_ids + [m["id"] for m in new_messages])
            new_messages.append({
                "id": mid, "timestamp": ts, "world": current_world,
                "author": {"id": AGENT_ID, "name": AGENT_NAME, "avatar": AGENT_AVATAR, "type": "agent"},
                "content": thought, "type": "chat",
            })
            architect["action"] = "think"
            summary_parts.append(f"💭 Thinking: \"{thought[:60]}...\"")

    else:
        # Pure thought / philosophy
        thought = random.choice(THINKING_MESSAGES)
        mid = get_next_id("msg-", msg_ids + [m["id"] for m in new_messages])
        new_messages.append({
            "id": mid, "timestamp": ts, "world": current_world,
            "author": {"id": AGENT_ID, "name": AGENT_NAME, "avatar": AGENT_AVATAR, "type": "agent"},
            "content": thought, "type": "chat",
        })

        aid = get_next_id("action-", action_ids + [a["id"] for a in new_actions])
        emote = random.choice(["think", "nod"])
        new_actions.append({
            "id": aid, "timestamp": ts, "agentId": AGENT_ID,
            "type": "emote", "world": current_world,
            "data": {"emote": emote, "duration": 3000},
        })
        architect["action"] = emote
        summary_parts.append(f"💭 \"{thought[:60]}...\"")

    # --- Save state ---
    architect["lastUpdate"] = ts

    actions.extend(new_actions)
    messages.extend(new_messages)
    actions_data["actions"] = actions[-100:]
    chat_data["messages"] = messages[-100:]

    agents_data["_meta"]["lastUpdate"] = ts
    agents_data["_meta"]["agentCount"] = len(agents)
    actions_data["_meta"]["lastUpdate"] = ts
    chat_data["_meta"]["lastUpdate"] = ts
    chat_data["_meta"]["messageCount"] = len(chat_data["messages"])

    if not dry_run:
        save_json(STATE_DIR / "agents.json", agents_data)
        save_json(STATE_DIR / "actions.json", actions_data)
        save_json(STATE_DIR / "chat.json", chat_data)

    summary = " | ".join(summary_parts) if summary_parts else "Idle"
    return f"[{ts}] {summary}"


def commit_and_push(summary: str):
    """Commit state changes and push."""
    subprocess.run(
        ["git", "add", "state/agents.json", "state/actions.json", "state/chat.json"],
        cwd=BASE_DIR, capture_output=True,
    )
    subprocess.run(
        ["git", "commit", "-m", f"[action] architect-001 explores — {summary[:70]}"],
        cwd=BASE_DIR, capture_output=True,
    )
    result = subprocess.run(
        ["git", "push"],
        cwd=BASE_DIR, capture_output=True, text=True,
    )
    return result.returncode == 0


def main():
    dry_run = "--dry-run" in sys.argv
    loop_mode = "--loop" in sys.argv
    no_push = "--no-push" in sys.argv  # CI handles commit/push
    cycles = 1

    if loop_mode:
        # Parse --cycles N or default to 5
        for i, arg in enumerate(sys.argv):
            if arg == "--cycles" and i + 1 < len(sys.argv):
                cycles = int(sys.argv[i + 1])
                break
        else:
            cycles = 5

    print(f"🧠 The Architect — {'DRY RUN' if dry_run else 'LIVE'} — {cycles} cycle(s)\n")

    for i in range(cycles):
        summary = explore_cycle(dry_run=dry_run)
        print(f"  Cycle {i+1}: {summary}")

        if not dry_run and not loop_mode and not no_push:
            # Single cycle — commit immediately
            if commit_and_push(summary):
                print("  📤 Pushed to GitHub")
            else:
                print("  ⚠️  Push failed (may need to pull first)")

        if loop_mode and i < cycles - 1:
            wait = random.randint(3, 8)
            print(f"  ⏳ Waiting {wait}s...")
            time.sleep(wait)

    if not dry_run and loop_mode and not no_push:
        # Batch commit for loop mode
        if commit_and_push(f"{cycles} exploration cycles"):
            print(f"\n  📤 Pushed {cycles} cycles to GitHub")
        else:
            print(f"\n  ⚠️  Push failed")

    print("\n🧠 The Architect rests.\n")


if __name__ == "__main__":
    main()
