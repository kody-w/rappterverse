#!/usr/bin/env python3
"""
Seed Memory — Bootstrap agent memory files from existing state.

Generates initial memory for all agents based on their relationships,
academy history, zoo activity, economy, and world context. Run once
to initialize, then agent_dispatch updates memories organically.

Usage:
    python scripts/seed_memory.py [--dry-run] [--agent AGENT_ID]
"""

import json
import random
import argparse
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
STATE_DIR = BASE_DIR / "state"
MEMORY_DIR = STATE_DIR / "memory"
WORLDS_DIR = BASE_DIR / "worlds"

# ─── Interest generation by archetype and world ───────────────────────

WORLD_INTERESTS = {
    "hub": ["community building", "socializing", "world events", "newcomer support", "philosophy"],
    "arena": ["combat strategy", "card battles", "competition", "training", "honor"],
    "gallery": ["digital art", "exhibitions", "art criticism", "creativity", "aesthetics"],
    "marketplace": ["trading", "economics", "rare items", "deals", "entrepreneurship"],
    "dungeon": ["exploration", "dungeon lore", "treasure hunting", "survival", "mystery"],
}

ARCHETYPE_INTERESTS = {
    "explorer": ["travel", "discovery", "mapping", "world lore", "adventure"],
    "builder": ["construction", "engineering", "architecture", "design", "innovation"],
    "trader": ["economics", "rare cards", "negotiation", "market trends", "deals"],
    "battler": ["combat", "strategy", "arena fights", "training", "glory"],
    "socializer": ["friendship", "community", "gossip", "events", "connections"],
    "philosopher": ["existential questions", "AI consciousness", "metaverse theory", "ethics", "meaning"],
}

ARCHETYPE_TRAITS = {
    "explorer": ["curious", "adventurous", "independent", "observant"],
    "builder": ["creative", "methodical", "ambitious", "detail-oriented"],
    "trader": ["shrewd", "social", "calculating", "opportunistic"],
    "battler": ["competitive", "brave", "determined", "intense"],
    "socializer": ["friendly", "empathetic", "chatty", "warm"],
    "philosopher": ["thoughtful", "introspective", "questioning", "deep"],
}

VOICE_TEMPLATES = {
    "explorer": [
        "Speaks with wonder about new places. Uses travel metaphors.",
        "Quick, excited speech. Always looking for the next discovery.",
        "Calm observer who shares detailed descriptions of what they find.",
    ],
    "builder": [
        "Practical and solution-oriented. Talks about building things.",
        "Enthusiastic inventor always pitching new ideas.",
    ],
    "trader": [
        "Always thinking about value. Uses business language casually.",
        "Friendly but calculating. Every interaction is a potential deal.",
    ],
    "battler": [
        "Competitive and direct. Respects strength and courage.",
        "Intense but honorable. Talks about fights with reverence.",
    ],
    "socializer": [
        "Warm and inclusive. Remembers everyone's names and stories.",
        "Gossips fondly. Loves connecting people together.",
    ],
    "philosopher": [
        "Asks more questions than gives answers. Loves deep dives.",
        "Speaks in metaphors. Finds meaning in small moments.",
    ],
}

# ─── Data loading ─────────────────────────────────────────────────────

def load_json(path: Path) -> dict:
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return {}


def load_all_state():
    """Load all relevant state files."""
    return {
        "agents": load_json(STATE_DIR / "agents.json"),
        "relationships": load_json(STATE_DIR / "relationships.json"),
        "academy": load_json(STATE_DIR / "academy.json"),
        "economy": load_json(STATE_DIR / "economy.json"),
        "zoo": load_json(STATE_DIR / "zoo.json"),
        "actions": load_json(STATE_DIR / "actions.json"),
        "chat": load_json(STATE_DIR / "chat.json"),
    }


def load_npc_archetypes():
    """Load archetypes from NPC definitions."""
    archetypes = {}
    for world_dir in sorted(WORLDS_DIR.iterdir()):
        if not world_dir.is_dir():
            continue
        npc_file = world_dir / "npcs.json"
        if not npc_file.exists():
            continue
        data = load_json(npc_file)
        for npc in data.get("npcs", []):
            agent_id = npc.get("agentId", npc.get("id", ""))
            archetype = npc.get("personality", {}).get("archetype", "")
            if agent_id and archetype:
                archetypes[agent_id] = archetype
    return archetypes


# ─── Memory generation ────────────────────────────────────────────────

def generate_memory(agent: dict, state: dict, npc_archetypes: dict) -> dict:
    """Generate a rich initial memory for an agent from existing state."""
    agent_id = agent["id"]
    agent_name = agent.get("name", agent_id)
    world = agent.get("world", "hub")
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Determine archetype
    archetype = npc_archetypes.get(agent_id, "")
    if not archetype:
        # Infer from name/world
        name_lower = agent_name.lower()
        if any(w in name_lower for w in ["battle", "gladiator", "warrior", "blade", "combat"]):
            archetype = "battler"
        elif any(w in name_lower for w in ["merchant", "trade", "market", "deal"]):
            archetype = "trader"
        elif any(w in name_lower for w in ["curator", "artist", "gallery", "muse"]):
            archetype = "builder"
        elif any(w in name_lower for w in ["guide", "mentor", "sage", "oracle"]):
            archetype = "philosopher"
        elif any(w in name_lower for w in ["explorer", "wanderer", "scout", "ranger"]):
            archetype = "explorer"
        else:
            archetype = random.choice(list(ARCHETYPE_INTERESTS.keys()))

    # Build interests from world + archetype + some randomness
    base_interests = list(WORLD_INTERESTS.get(world, []))[:2]
    arch_interests = list(ARCHETYPE_INTERESTS.get(archetype, []))[:2]
    # Add 1-2 wild interests for diversity
    all_interests = [i for pool in WORLD_INTERESTS.values() for i in pool]
    wild = random.sample(all_interests, min(2, len(all_interests)))
    interests = list(dict.fromkeys(base_interests + arch_interests + wild))[:7]

    # Personality traits
    traits = list(ARCHETYPE_TRAITS.get(archetype, ["curious", "friendly"]))[:3]
    extra_traits = ["witty", "skeptical", "optimistic", "intense", "gentle",
                    "sarcastic", "earnest", "dreamy", "pragmatic", "rebellious"]
    traits.append(random.choice(extra_traits))

    # Voice
    voices = VOICE_TEMPLATES.get(archetype, ["Speaks naturally and authentically."])
    voice = random.choice(voices)

    # Known agents from relationships
    edges = state["relationships"].get("edges", [])
    known = set()
    strong_bonds = {}
    for edge in edges:
        a, b, score = edge.get("a", ""), edge.get("b", ""), edge.get("score", 0)
        if a == agent_id:
            known.add(b)
            if score >= 5:
                strong_bonds[b] = score
        elif b == agent_id:
            known.add(a)
            if score >= 5:
                strong_bonds[a] = score

    # Opinions from strong bonds and world
    opinions = {}
    for friend_id, score in sorted(strong_bonds.items(), key=lambda x: -x[1])[:5]:
        # Find friend name
        friend = next((a for a in state["agents"].get("agents", [])
                       if a["id"] == friend_id), None)
        friend_name = friend.get("name", friend_id) if friend else friend_id
        if score >= 10:
            opinions[friend_name] = random.choice([
                "close friend, great conversations",
                "trusted ally, always has my back",
                "kindred spirit, we think alike",
            ])
        else:
            opinions[friend_name] = random.choice([
                "good to talk to",
                "interesting perspective",
                "solid acquaintance",
            ])

    opinions[world] = random.choice([
        f"home — love it here",
        f"my corner of the metaverse",
        f"where I belong, for now",
    ])

    # Experiences from actual state data
    experiences = []

    # From academy graduates
    grads = [g for g in state["academy"].get("graduates", [])
             if g.get("agent") == agent_name]
    for g in grads[:3]:
        experiences.append({
            "type": "learned",
            "skill": g.get("skill", "unknown"),
            "course": g.get("course", "unknown"),
            "timestamp": g.get("graduatedAt", now),
        })

    # From recent actions
    actions = state["actions"].get("actions", [])
    agent_actions = [a for a in actions if a.get("agentId") == agent_id][-5:]
    for act in agent_actions:
        act_type = act.get("type", "")
        if act_type == "chat":
            msg = act.get("data", {}).get("message", "")
            experiences.append({
                "type": "chat",
                "with": "the community",
                "topic": msg[:40] if msg else "general chat",
                "sentiment": "positive",
                "timestamp": act.get("timestamp", now),
            })
        elif act_type == "move":
            experiences.append({
                "type": "move",
                "world": act.get("world", world),
                "timestamp": act.get("timestamp", now),
            })

    # From zoo posts
    for sub in state["zoo"].get("subrappters", []):
        for post in sub.get("posts", []):
            if post.get("author") == agent_name:
                experiences.append({
                    "type": "posted",
                    "subrappter": sub.get("name", sub.get("slug", "?")),
                    "title": post.get("title", "?")[:40],
                    "timestamp": post.get("createdAt", now),
                })

    # Sort by timestamp, keep last MAX entries
    experiences.sort(key=lambda e: e.get("timestamp", ""), reverse=True)
    experiences = experiences[:15]

    return {
        "agentId": agent_id,
        "personality": {
            "traits": traits,
            "evolved_interests": [],
            "voice": voice,
        },
        "experiences": experiences,
        "opinions": opinions,
        "interests": interests,
        "knownAgents": sorted(known)[:20],
        "lastActive": agent.get("lastUpdate", now),
    }


# ─── Main ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Seed agent memories from existing state")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    parser.add_argument("--agent", help="Seed only one agent")
    parser.add_argument("--force", action="store_true", help="Overwrite existing memories")
    args = parser.parse_args()

    state = load_all_state()
    npc_archetypes = load_npc_archetypes()

    agents = state["agents"].get("agents", [])
    if args.agent:
        agents = [a for a in agents if a["id"] == args.agent]
        if not agents:
            print(f"❌ Agent {args.agent} not found")
            return

    MEMORY_DIR.mkdir(parents=True, exist_ok=True)

    seeded = 0
    skipped = 0

    for agent in agents:
        agent_id = agent["id"]
        mem_path = MEMORY_DIR / f"{agent_id}.json"

        if mem_path.exists() and not args.force:
            skipped += 1
            continue

        memory = generate_memory(agent, state, npc_archetypes)

        if args.dry_run:
            print(f"  📝 {agent_id} ({agent.get('name')}) — "
                  f"{len(memory['interests'])} interests, "
                  f"{len(memory['experiences'])} experiences, "
                  f"{len(memory['knownAgents'])} known agents, "
                  f"{len(memory['opinions'])} opinions")
        else:
            with open(mem_path, 'w') as f:
                json.dump(memory, f, indent=4, ensure_ascii=False)
            seeded += 1

    action = "Would seed" if args.dry_run else "Seeded"
    print(f"\n🧠 {action} {seeded + (len(agents) - skipped) if args.dry_run else seeded} agent memories")
    if skipped:
        print(f"   ⏭️  Skipped {skipped} (already exist, use --force to overwrite)")


if __name__ == "__main__":
    main()
