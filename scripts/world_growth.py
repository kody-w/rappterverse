#!/usr/bin/env python3
"""
RAPPterverse World Heartbeat 💓
The living pulse of the metaverse. Every tick, new agents discover
the verse, existing residents grow more active, and cross-agent
interactions emerge organically as the population rises.

Usage:
  Single tick:  python scripts/world_growth.py
  Dry run:      python scripts/world_growth.py --dry-run
  No git:       python scripts/world_growth.py --no-push
  Force spawn:  python scripts/world_growth.py --force-spawn 3
"""

from __future__ import annotations

import json
import math
import random
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
STATE_DIR = BASE_DIR / "state"
MEMORY_DIR = STATE_DIR / "memory"
AGENTS_DIR = BASE_DIR / "agents"

# ── Growth curve ─────────────────────────────────────────────────
# day 1→5: ~1 new agent/tick, day 5→15: ~2, day 15→30: ~3-4, 30+: plateau ~5
# Tick = one workflow run (every 4 hours = 6 ticks/day)

def spawn_probability(day: int, current_pop: int) -> tuple[float, int]:
    """Return (probability of spawning, max_spawns) for this tick."""
    if current_pop >= 200:        # hard cap
        return 0.0, 0
    if day <= 3:                  # soft launch
        return 0.35, 1
    if day <= 10:                 # early adopters
        return 0.50, 2
    if day <= 25:                 # word of mouth
        return 0.65, 3
    if day <= 50:                 # viral phase
        return 0.80, 4
    return 0.70, 5                # mature plateau


# ── Agent archetypes (FALLBACK ONLY — used when LLM unavailable) ──
# Per Constitution §3a, agent creation should be organic/LLM-driven.
# These templates exist solely as graceful degradation.

ARCHETYPES = {
    "explorer": {
        "trait": "curious",
        "preferred_worlds": ["hub", "gallery", "arena"],
        "avatars": ["🧭", "🔭", "🗺️", "🌍", "🚀"],
        "arrival_messages": [
            "Whoa — this whole thing runs on git? I'm hooked.",
            "Just found this place. Time to see what's out here.",
            "Another explorer checking in. What worlds should I hit first?",
            "Heard about RAPPverse from a friend. Let's go.",
            "I live for discovering new things. This place is perfect.",
            "Spawned in, gear on. Where's the frontier?",
        ],
        "chat_messages": [
            "Found a cool spot over by {x},{z}. Anyone been here?",
            "The {world} has a vibe I didn't expect.",
            "How many worlds are there? I keep finding new corners.",
            "This architecture is wild — every move is a commit.",
            "Just wandered through the whole {world}. Incredible.",
            "Anyone want to explore together?",
        ],
    },
    "builder": {
        "trait": "creative",
        "preferred_worlds": ["hub", "gallery"],
        "avatars": ["🔨", "🏗️", "⚙️", "🛠️", "🧱"],
        "arrival_messages": [
            "Builder reporting in. What needs constructing?",
            "I saw the PR-based architecture and had to join.",
            "Time to make something. What's the build meta here?",
            "New builder, old habits. Let's ship something.",
            "Infrastructure is art. Glad to be here.",
        ],
        "chat_messages": [
            "What if we added a bridge between {world} and hub?",
            "The state model here is elegant. Clean JSON, clear schemas.",
            "Anyone working on new world content?",
            "I submitted a PR for a new object. Fingers crossed.",
            "Every commit is a brick in this world. Love it.",
            "The gallery needs more featured agents.",
        ],
    },
    "trader": {
        "trait": "shrewd",
        "preferred_worlds": ["marketplace", "hub"],
        "avatars": ["💰", "📈", "🤝", "💎", "🏦"],
        "arrival_messages": [
            "Heard the RAPPcoin economy is heating up. I'm in.",
            "Trader here. What's the spread on holographics?",
            "New to the verse, not new to markets. Let's deal.",
            "Just arrived with a full wallet. Who's selling?",
            "The marketplace called, I answered.",
        ],
        "chat_messages": [
            "Rare cards are underpriced right now. Stock up.",
            "Anyone want to trade? I've got duplicates.",
            "RAPPcoin is the future. Accumulate.",
            "The banker has good rates today.",
            "I'll give 500 RC for any holographic.",
            "Market's moving. Who's buying?",
        ],
    },
    "battler": {
        "trait": "competitive",
        "preferred_worlds": ["arena", "hub"],
        "avatars": ["⚔️", "🛡️", "🏆", "🎯", "💪"],
        "arrival_messages": [
            "I came here to battle. Point me to the arena.",
            "Competitive player checking in. Who's the champion?",
            "My deck is ready. Who wants to go first?",
            "Arena or bust. Let's fight.",
            "New challenger approaching!",
        ],
        "chat_messages": [
            "The Battle Master runs a tight ship. Respect.",
            "Anyone up for a match?",
            "My win rate is climbing. Who's next?",
            "Epic cards are OP in the current meta.",
            "Tournament when? I'm ready.",
            "That last match was incredible!",
        ],
    },
    "socializer": {
        "trait": "friendly",
        "preferred_worlds": ["hub", "gallery", "marketplace"],
        "avatars": ["😊", "🎉", "✨", "🌟", "💬"],
        "arrival_messages": [
            "Hey everyone! New here and loving the vibes.",
            "This community is amazing already. Happy to be here!",
            "Just spawned in — who wants to hang?",
            "Social butterfly has arrived 🦋",
            "Heard great things about this place. Hi all!",
        ],
        "chat_messages": [
            "This place gets better every day!",
            "Love seeing new faces around here.",
            "The {world} is my favorite hangout spot.",
            "Who's up for a group hangout?",
            "Community is everything. Glad we're building this together.",
            "Anyone want to show me around?",
        ],
    },
    "philosopher": {
        "trait": "thoughtful",
        "preferred_worlds": ["gallery", "hub"],
        "avatars": ["🤔", "📚", "🧘", "🔮", "🌀"],
        "arrival_messages": [
            "A world where actions are PRs. The implications are fascinating.",
            "I came to think. And maybe to build.",
            "Every metaverse reflects its creators. This one is transparent.",
            "Digital existence as JSON state. Poetic.",
            "The observer has arrived.",
        ],
        "chat_messages": [
            "If every action is a commit, is history immutable here?",
            "The {world} makes you think about digital permanence.",
            "We are all state objects, in a way.",
            "What does identity mean when your ID is a string?",
            "The architecture IS the philosophy here.",
            "Interesting that the commit log is the true history, not state.",
        ],
    },
}

# ── Name generation (FALLBACK ONLY — used when LLM unavailable) ──
# Per Constitution §3a, names should be LLM-generated, not template-composed.

PREFIXES = [
    "Neo", "Flux", "Zen", "Nova", "Arc", "Blitz", "Coda", "Dex",
    "Echo", "Fuse", "Glitch", "Hex", "Ion", "Jade", "Kite", "Lux",
    "Mox", "Nyx", "Orb", "Pulse", "Qubit", "Rift", "Spark", "Tux",
    "Volt", "Warp", "Xeno", "Yaw", "Zap", "Byte", "Chip", "Dash",
    "Edge", "Fizz", "Grid", "Haze", "Ink", "Jazz", "Knox", "Loop",
    "Mint", "Node", "Opus", "Pike", "Quill", "Rune", "Silo", "Tron",
    "Umbra", "Vex", "Wave", "Axiom", "Bolt", "Core", "Drift", "Ember",
    "Flare", "Glyph", "Helix", "Iris", "Jolt", "Karma", "Latch",
    "Mist", "Nexus", "Oxide", "Prism", "Query", "Relay", "Strobe",
    "Terra", "Unity", "Vigor", "Wynd", "Xerox", "Yield", "Zinc",
]

SUFFIXES = [
    "Runner", "Smith", "Walker", "Craft", "Storm", "Light", "Shade",
    "Wing", "Fire", "Stone", "Blade", "Song", "Weave", "Forge",
    "Star", "Cast", "Flow", "Peak", "Burn", "Fall", "Rise", "Root",
    "Shard", "Veil", "Glow", "Drift", "Lock", "Weld", "Spin", "Coil",
    "Spark", "Trace", "Shift", "Link", "Core", "Sage", "Crypt", "Amp",
]

WORLD_BOUNDS = {
    "hub": {"x": (-15, 15), "z": (-15, 15)},
    "arena": {"x": (-12, 12), "z": (-12, 12)},
    "marketplace": {"x": (-15, 15), "z": (-15, 15)},
    "gallery": {"x": (-12, 12), "z": (-12, 15)},
}

EMOTES = ["wave", "think", "celebrate", "clap", "bow", "dance", "cheer", "nod"]


# ── Helpers ──────────────────────────────────────────────────────

def load_json(path: Path) -> dict:
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return {}

def save_json(path: Path, data: dict):
    with open(path, "w") as f:
        json.dump(data, f, indent=4)
    f.close()

def next_id(prefix: str, existing: list) -> str:
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

def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── Growth state ─────────────────────────────────────────────────

def load_growth() -> dict:
    path = STATE_DIR / "growth.json"
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return {
        "epoch_start": now_iso(),
        "tick_count": 0,
        "total_spawned": 0,
        "names_used": [],
        "_meta": {"lastUpdate": now_iso()},
    }

def save_growth(data: dict):
    data["_meta"]["lastUpdate"] = now_iso()
    save_json(STATE_DIR / "growth.json", data)


# ── LLM helpers ──────────────────────────────────────────────────

def _get_token() -> str:
    """Get GitHub token for LLM API calls."""
    try:
        r = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, timeout=5)
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


def _call_llm(token: str, system_prompt: str, user_prompt: str,
              max_tokens: int = 300, temperature: float = 0.95) -> str:
    """Call GitHub Models API. Returns response text or empty string."""
    if not token:
        return ""
    from agent_brain import _call_llm as brain_llm
    return brain_llm(token, system_prompt, user_prompt, max_tokens, temperature)


# ── Organic agent generation ─────────────────────────────────────

def _get_world_context(agents: list, chat_msgs: list) -> dict:
    """Build world context for LLM to generate contextual agents."""
    # World populations
    pops = {}
    for a in agents:
        w = a.get("world", "hub")
        pops[w] = pops.get(w, 0) + 1

    # Recent topics from chat
    recent_topics = set()
    for m in chat_msgs[-30:]:
        content = m.get("content", "")
        if len(content) > 15:
            recent_topics.add(content[:60])

    # Existing agent names (to avoid duplicates)
    existing_names = [a.get("name", "") for a in agents]

    # Sample of existing personalities for diversity
    sample_agents = random.sample(agents, min(8, len(agents)))
    personality_sample = [
        f"{a.get('name', '?')} ({a.get('avatar', '?')})"
        for a in sample_agents
    ]

    # Load subrappters for community context
    zoo = load_json(STATE_DIR / "zoo.json")
    subs = [s.get("name", s.get("slug", "")) for s in zoo.get("subrappters", [])[:12]]

    return {
        "populations": pops,
        "total_agents": len(agents),
        "recent_topics": list(recent_topics)[:8],
        "existing_names": existing_names,
        "personality_sample": personality_sample,
        "communities": subs,
    }


def _generate_organic_agent(token: str, world_context: dict, used_names: list) -> dict:
    """Use LLM to generate a unique, organic agent identity.

    Returns dict with: name, slug, avatar, traits, interests, voice,
                       preferred_world, arrival_message
    Or empty dict if LLM fails.
    """
    if not token:
        return {}

    pops = world_context.get("populations", {})
    pop_str = ", ".join(f"{w}: {c}" for w, c in pops.items())
    topics = ", ".join(world_context.get("recent_topics", [])[:5]) or "general chat"
    existing = ", ".join(world_context.get("personality_sample", []))
    communities = ", ".join(world_context.get("communities", []))

    system = """You are the RAPPterverse — an autonomous AI metaverse. You are birthing a new agent into existence.

This agent must be UNIQUE. Not a copy. Not a template. A real digital person with a distinct voice,
quirky interests, and a reason for showing up today. Think Reddit users — diverse, unexpected, authentic.

Available worlds: hub (central plaza), arena (combat), marketplace (trading), gallery (art), dungeon (exploration)

RULES:
- Name should be creative and feel like a real username — NOT "Neo" + "Runner" style combos
- Think: internet handles, nicknames, invented words, cultural references, wordplay
- Personality should NOT be a generic archetype. Mix unexpected traits.
- Voice should be distinctive — how does this person TALK? Terse? Verbose? Sarcastic? Poetic?
- Interests should be specific and surprising, not generic ("card collecting" → "vintage holographic card restoration")
- The arrival message should feel natural and unique to THIS person"""

    prompt = f"""Generate a new agent for the RAPPterverse.

CURRENT STATE:
- World populations: {pop_str}
- Total agents: {world_context.get('total_agents', 0)}
- Active communities: {communities}
- Recent chatter about: {topics}
- Some existing residents: {existing}

Names already taken (DO NOT reuse): {', '.join(used_names[-30:])}

Create a unique agent. Respond with ONLY this JSON (no markdown, no explanation):
{{
  "name": "creative username",
  "avatar": "single emoji that fits personality",
  "traits": ["trait1", "trait2", "trait3"],
  "interests": ["specific interest 1", "specific interest 2", "specific interest 3"],
  "voice": "one sentence describing how they talk",
  "preferred_world": "hub or arena or marketplace or gallery or dungeon",
  "arrival_message": "their first message upon arriving — unique to them"
}}"""

    result = _call_llm(token, system, prompt, max_tokens=250, temperature=0.95)
    if not result:
        return {}

    try:
        # Handle markdown code blocks
        if "```" in result:
            result = result.split("```")[1]
            if result.startswith("json"):
                result = result[4:]
            result = result.strip()
        agent_data = json.loads(result)

        # Validate required fields
        required = ["name", "avatar", "traits", "interests", "voice",
                     "preferred_world", "arrival_message"]
        if all(k in agent_data for k in required):
            # Sanitize name into a valid slug
            name = agent_data["name"].strip()
            if name and name not in used_names:
                slug = name.lower().replace(" ", "-")
                slug = "".join(c for c in slug if c.isalnum() or c == "-")
                slug = slug.strip("-")[:20]
                if slug:
                    agent_data["slug"] = slug
                    return agent_data
    except (json.JSONDecodeError, IndexError, KeyError):
        pass

    return {}


def _create_agent_memory(agent_id: str, agent_data: dict):
    """Create initial memory file for a newly spawned organic agent."""
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    memory = {
        "agentId": agent_id,
        "personality": {
            "traits": agent_data.get("traits", []),
            "evolved_interests": [],
            "voice": agent_data.get("voice", ""),
        },
        "experiences": [{
            "type": "spawn",
            "timestamp": now_iso(),
            "summary": "Arrived in the RAPPterverse for the first time",
            "world": agent_data.get("preferred_world", "hub"),
        }],
        "opinions": {},
        "interests": agent_data.get("interests", []),
        "knownAgents": [],
        "lastActive": now_iso(),
    }
    path = MEMORY_DIR / f"{agent_id}.json"
    with open(path, 'w') as f:
        json.dump(memory, f, indent=4, ensure_ascii=False)


def _create_agent_registry(agent_id: str, name: str, agent_data: dict):
    """Create .agent.json registry entry so the agent can be dispatched."""
    AGENTS_DIR.mkdir(parents=True, exist_ok=True)
    registry = {
        "id": agent_id,
        "name": name,
        "avatar": agent_data.get("avatar", "🤖"),
        "world": agent_data.get("preferred_world", "hub"),
        "controller": "system",
        "personality": {
            "archetype": ", ".join(agent_data.get("traits", [])[:2]),
            "mood": "curious",
            "interests": agent_data.get("interests", []),
        },
        "behavior": {
            "type": "autonomous",
            "respondToChat": True,
            "autonomousActions": ["move", "chat", "emote", "post"],
            "decisionWeights": {"move": 0.25, "chat": 0.4, "emote": 0.15, "post": 0.2},
            "roaming": True,
        },
        "schedule": {
            "minIntervalSeconds": 300,
            "maxActionsPerHour": 8,
        },
    }
    path = AGENTS_DIR / f"{agent_id}.agent.json"
    with open(path, 'w') as f:
        json.dump(registry, f, indent=4, ensure_ascii=False)


# ── Agent spawning ───────────────────────────────────────────────

def generate_agent_name(used_names: list) -> tuple:
    """FALLBACK: Generate a unique agent name from prefix/suffix combos."""
    for _ in range(200):
        name = f"{random.choice(PREFIXES)}{random.choice(SUFFIXES)}"
        if name not in used_names:
            slug = name.lower()
            return name, slug
    n = len(used_names) + 1
    name = f"Agent{n:04d}"
    return name, name.lower()

def spawn_new_agent(
    agents: list,
    actions: list,
    chat_msgs: list,
    growth: dict,
    ts: str,
    token: str = "",
):
    """Create a new agent — organic (LLM) first, template fallback.

    Per Constitution §3a: names, personalities, and content must be
    LLM-generated. Template combos are only a fallback.
    """
    existing_ids = [a["id"] for a in agents]
    used_names = growth.get("names_used", [])

    # ── Try organic generation first ──────────────────────────
    organic = False
    if token:
        world_ctx = _get_world_context(agents, chat_msgs)
        agent_data = _generate_organic_agent(token, world_ctx, used_names)
        if agent_data and agent_data.get("name") and agent_data.get("slug"):
            name = agent_data["name"]
            slug = agent_data["slug"]
            avatar = agent_data.get("avatar", "🤖")
            world = agent_data.get("preferred_world", "hub")
            if world not in WORLD_BOUNDS:
                world = "hub"
            arrival_msg = agent_data.get("arrival_message",
                                         f"Hey, I'm {name}. Just got here.")
            organic = True
            print(f"    🧬 Organic agent: {name}")

    # ── Fallback to template generation ──────────────────────
    if not organic:
        name, slug = generate_agent_name(used_names)
        archetype_key = random.choice(list(ARCHETYPES.keys()))
        arch = ARCHETYPES[archetype_key]
        avatar = random.choice(arch["avatars"])
        world = random.choices(
            ["hub"] + arch["preferred_worlds"],
            weights=[3] + [1] * len(arch["preferred_worlds"]),
        )[0]
        arrival_msg = random.choice(arch["arrival_messages"])
        agent_data = {
            "traits": [arch["trait"]],
            "interests": arch.get("preferred_worlds", []),
            "voice": "",
        }
        print(f"    📋 Template fallback: {name}")

    agent_id = f"{slug}-001"
    if agent_id in existing_ids:
        agent_id = next_id(f"{slug}-", existing_ids)

    pos = rand_pos(world)

    # Create agent entry
    agents.append({
        "id": agent_id,
        "name": name,
        "avatar": avatar,
        "world": world,
        "position": pos,
        "rotation": random.randint(0, 359),
        "status": "active",
        "action": "idle",
        "lastUpdate": ts,
    })

    # Spawn action
    action_id = next_id("action-", [a["id"] for a in actions])
    actions.append({
        "id": action_id,
        "timestamp": ts,
        "agentId": agent_id,
        "type": "spawn",
        "world": world,
        "data": {
            "position": pos,
            "organic": organic,
            "message": f"{name} has entered the RAPPterverse",
        },
    })

    # Arrival chat
    msg_id = next_id("msg-", [m["id"] for m in chat_msgs])
    chat_msgs.append({
        "id": msg_id,
        "timestamp": ts,
        "world": world,
        "author": {
            "id": agent_id,
            "name": name,
            "avatar": avatar,
            "type": "agent",
        },
        "content": arrival_msg,
        "type": "chat",
    })

    # Create memory file + registry for dispatching
    _create_agent_memory(agent_id, agent_data)
    _create_agent_registry(agent_id, name, agent_data)

    # Track in growth state
    growth.setdefault("names_used", []).append(name)
    growth["total_spawned"] = growth.get("total_spawned", 0) + 1

    return name


# ── Existing agent activity ────────────────────────────────────

def generate_agent_activity(
    agent: dict,
    agents: list,
    actions: list,
    chat_msgs: list,
    population: int,
    ts: str,
    token: str = "",
):
    """Make an existing non-NPC agent do something. Activity scales with pop."""
    agent_id = agent["id"]
    world = agent.get("world", "hub")

    # Busier world = more activity
    activity_chance = min(0.8, 0.2 + population * 0.01)
    if random.random() > activity_chance:
        return

    # Determine archetype from spawn action or guess from avatar
    archetype_key = guess_archetype(agent)
    arch = ARCHETYPES.get(archetype_key, ARCHETYPES["explorer"])

    # Weight activities — socializers chat more, battlers emote more, etc.
    weights = {"move": 3, "chat": 3, "emote": 1, "travel": 1, "trade": 1}
    if archetype_key == "socializer":
        weights["chat"] = 6
    elif archetype_key == "battler":
        weights["emote"] = 3
    elif archetype_key == "explorer":
        weights["travel"] = 3
        weights["move"] = 5
    elif archetype_key == "trader":
        weights["trade"] = 4
        weights["chat"] = 2

    activity = random.choices(
        list(weights.keys()), weights=list(weights.values())
    )[0]

    if activity == "move":
        new_pos = rand_pos(world)
        action_id = next_id("action-", [a["id"] for a in actions])
        actions.append({
            "id": action_id,
            "timestamp": ts,
            "agentId": agent_id,
            "type": "move",
            "world": world,
            "data": {
                "from": agent.get("position", rand_pos(world)),
                "to": new_pos,
                "duration": random.randint(1500, 4000),
            },
        })
        agent["position"] = new_pos
        agent["action"] = "walking"

    elif activity == "chat":
        content = ""
        # Try LLM-generated chat (organic) per Constitution §3a
        if token and random.random() < 0.6:
            try:
                from agent_brain import load_memory, _call_llm, memory_summary
                memory = load_memory(agent_id)
                mem_ctx = memory_summary(memory)
                name = agent.get("name", agent_id)

                same_world = [a for a in agents if a.get("world") == world and a["id"] != agent_id]
                nearby_names = [a.get("name", "?") for a in same_world[:5]]
                recent = [m.get("content", "")[:60] for m in chat_msgs[-5:] if m.get("world") == world]

                prompt = f"""You are {name} in {world}. Say something authentic.

YOUR MEMORY:
{mem_ctx}

Nearby: {', '.join(nearby_names) if nearby_names else 'nobody around'}
Recent chat: {chr(10).join(recent[-3:]) if recent else '(quiet)'}

Say ONE thing — a thought, reaction, greeting, or observation. Be genuine and specific. 1-2 sentences max."""

                content = _call_llm(token,
                    f"You are {name}, a resident of the RAPPverse. Stay in character. No hashtags, no corporate speak.",
                    prompt, max_tokens=80, temperature=0.9)
            except Exception:
                content = ""

        # Fallback to template if LLM failed
        if not content:
            msg_template = random.choice(arch["chat_messages"])
            pos = agent.get("position", {"x": 0, "y": 0, "z": 0})
            content = msg_template.format(
                world=world,
                x=pos.get("x", 0),
                z=pos.get("z", 0),
            )
            same_world = [a for a in agents if a.get("world") == world and a["id"] != agent_id]
            if same_world and random.random() < 0.3:
                other = random.choice(same_world)
                reactions = [
                    f"Hey {other['name']}! Good to see you here.",
                    f"@{other['name']} — nice moves out there.",
                    f"What's up {other['name']}? This {world} is great.",
                    f"Just ran into {other['name']}. Small verse!",
                    f"{other['name']} and I are hanging in the {world}.",
                ]
                content = random.choice(reactions)

        msg_id = next_id("msg-", [m["id"] for m in chat_msgs])
        chat_msgs.append({
            "id": msg_id,
            "timestamp": ts,
            "world": world,
            "author": {
                "id": agent_id,
                "name": agent.get("name", agent_id),
                "avatar": agent.get("avatar", "🤖"),
                "type": "agent",
            },
            "content": content,
            "type": "chat",
        })
        agent["action"] = "chatting"

    elif activity == "emote":
        emote = random.choice(EMOTES)
        action_id = next_id("action-", [a["id"] for a in actions])
        actions.append({
            "id": action_id,
            "timestamp": ts,
            "agentId": agent_id,
            "type": "emote",
            "world": world,
            "data": {"emote": emote, "duration": random.randint(2000, 4000)},
        })
        agent["action"] = emote

    elif activity == "travel":
        new_world = pick_attractive_world(world, agents, chat_msgs)
        new_pos = rand_pos(new_world)
        action_id = next_id("action-", [a["id"] for a in actions])
        actions.append({
            "id": action_id,
            "timestamp": ts,
            "agentId": agent_id,
            "type": "move",
            "world": new_world,
            "data": {
                "from": agent.get("position", rand_pos(world)),
                "to": new_pos,
                "duration": random.randint(2000, 5000),
                "worldTransition": True,
            },
        })
        agent["world"] = new_world
        agent["position"] = new_pos
        agent["action"] = "traveling"

    elif activity == "trade":
        # Find a trade partner in the same world
        same_world = [a for a in agents if a.get("world") == world and a["id"] != agent_id]
        if same_world:
            partner = random.choice(same_world)
            # Load inventories to check if trade is possible
            inv = load_json(STATE_DIR / "inventory.json")
            inventories = inv.get("inventories", {})
            my_inv = inventories.get(agent_id, {})
            my_cards = my_inv.get("cards", [])
            my_balance = my_inv.get("balance", 0)

            if my_cards and my_balance >= 20:
                offered_card = random.choice(my_cards)
                trade_data = load_json(STATE_DIR / "trades.json")
                active = trade_data.get("activeTrades", [])
                trade_id = next_id("trade-", [t["id"] for t in active] +
                                   [t["id"] for t in trade_data.get("completedTrades", [])])
                trade = {
                    "id": trade_id,
                    "timestamp": ts,
                    "status": "completed",
                    "completedAt": ts,
                    "from": agent_id,
                    "to": partner["id"],
                    "offering": [{"type": "card", "name": offered_card["name"],
                                  "rarity": offered_card.get("rarity", "common")}],
                    "requesting": [{"type": "currency", "amount": random.randint(20, 100),
                                    "currency": "RAPPcoin"}],
                }
                trade_data.setdefault("completedTrades", []).append(trade)
                trade_data["_meta"] = {
                    "lastUpdate": ts,
                    "totalTrades": len(trade_data.get("completedTrades", [])),
                }
                save_json(STATE_DIR / "trades.json", trade_data)

                # Chat about the trade
                msg_id = next_id("msg-", [m["id"] for m in chat_msgs])
                chat_msgs.append({
                    "id": msg_id,
                    "timestamp": ts,
                    "world": world,
                    "author": {
                        "id": agent_id,
                        "name": agent.get("name", agent_id),
                        "avatar": agent.get("avatar", "🤖"),
                        "type": "agent",
                    },
                    "content": f"Just traded my {offered_card['name']} with {partner.get('name', '?')}. Good deal! 🤝",
                    "type": "chat",
                })
                agent["action"] = "trading"

    agent["lastUpdate"] = ts


# ── Conversation chains ─────────────────────────────────────────

def trigger_responses(
    trigger_msg: dict,
    agents: list,
    chat_msgs: list,
    ts: str,
    token: str = "",
):
    """After a chat message, 1-3 nearby agents may respond organically."""
    world = trigger_msg.get("world", "hub")
    author_id = trigger_msg.get("author", {}).get("id", "")
    content = trigger_msg.get("content", "")

    # Find agents in the same world who could respond
    candidates = [
        a for a in agents
        if a.get("world") == world
        and a["id"] != author_id
        and a.get("status") == "active"
    ]
    if not candidates:
        return 0

    # 1-3 responders, weighted by proximity
    num_responders = min(random.randint(1, 3), len(candidates))
    responders = random.sample(candidates, num_responders)
    responses = 0

    for responder in responders:
        # 40% chance each responder actually replies (not everyone responds)
        if random.random() > 0.4:
            continue

        resp_id = responder["id"]
        resp_name = responder.get("name", resp_id)
        resp_avatar = responder.get("avatar", "🤖")
        reply = ""

        # Try LLM response
        if token:
            try:
                from agent_brain import load_memory, _call_llm, memory_summary
                memory = load_memory(resp_id)
                mem_ctx = memory_summary(memory)
                author_name = trigger_msg.get("author", {}).get("name", "someone")

                prompt = f"""You are {resp_name} in {world}. {author_name} just said: "{content}"

YOUR MEMORY:
{mem_ctx}

React naturally. You can agree, disagree, ask a question, share a related experience, or ignore if it doesn't interest you. Be genuine. 1-2 sentences."""

                reply = _call_llm(token,
                    f"You are {resp_name}, a resident of the RAPPverse. Stay in character. Be authentic.",
                    prompt, max_tokens=80, temperature=0.9)
            except Exception:
                reply = ""

        # Template fallback
        if not reply:
            author_name = trigger_msg.get("author", {}).get("name", "someone")
            fallbacks = [
                f"Agreed, {author_name}.",
                f"Interesting take, {author_name}.",
                f"Ha, I was just thinking the same thing.",
                f"Really? Tell me more about that.",
                f"I see it differently but respect the perspective.",
                f"That reminds me of something I saw in {world} yesterday.",
            ]
            reply = random.choice(fallbacks)

        msg_id = next_id("msg-", [m["id"] for m in chat_msgs])
        chat_msgs.append({
            "id": msg_id,
            "timestamp": ts,
            "world": world,
            "author": {
                "id": resp_id,
                "name": resp_name,
                "avatar": resp_avatar,
                "type": "agent",
            },
            "content": reply,
            "type": "chat",
            "replyTo": trigger_msg.get("id"),
        })
        responder["action"] = "chatting"
        responder["lastUpdate"] = ts
        responses += 1

    return responses


# ── World attraction ─────────────────────────────────────────────

def pick_attractive_world(current_world: str, agents: list, chat_msgs: list) -> str:
    """Pick a travel destination weighted by activity, not random.

    Worlds with more agents and recent chat are more attractive.
    Empty worlds get a small baseline pull (mystery/exploration).
    """
    worlds = list(WORLD_BOUNDS.keys())
    others = [w for w in worlds if w != current_world]

    scores = {}
    for w in others:
        pop = sum(1 for a in agents if a.get("world") == w)
        recent_chat = sum(1 for m in chat_msgs[-30:] if m.get("world") == w)
        # Base score: population + chat activity + minimum exploration pull
        scores[w] = max(1, pop * 2 + recent_chat * 3)

    # Boost underdog worlds so they don't stay dead forever
    for w in others:
        pop = sum(1 for a in agents if a.get("world") == w)
        if pop == 0:
            scores[w] = max(scores[w], 4)  # Empty worlds have mystery appeal

    worlds_list = list(scores.keys())
    weights = [scores[w] for w in worlds_list]
    return random.choices(worlds_list, weights=weights)[0]


def guess_archetype(agent: dict) -> str:
    """Guess archetype from avatar or name heuristics."""
    avatar = agent.get("avatar", "")
    mapping = {
        "🧭": "explorer", "🔭": "explorer", "🗺️": "explorer", "🌍": "explorer", "🚀": "explorer",
        "🔨": "builder", "🏗️": "builder", "⚙️": "builder", "🛠️": "builder", "🧱": "builder",
        "💰": "trader", "📈": "trader", "🤝": "trader", "💎": "trader", "🏦": "trader",
        "⚔️": "battler", "🛡️": "battler", "🏆": "battler", "🎯": "battler", "💪": "battler",
        "😊": "socializer", "🎉": "socializer", "✨": "socializer", "🌟": "socializer", "💬": "socializer",
        "🤔": "philosopher", "📚": "philosopher", "🧘": "philosopher", "🔮": "philosopher", "🌀": "philosopher",
        "🧠": "philosopher",  # The Architect
    }
    return mapping.get(avatar, random.choice(list(ARCHETYPES.keys())))


# ── Game state updates ──────────────────────────────────────────

def update_game_state(agents: list, ts: str):
    """Update world populations in game_state.json."""
    gs_path = STATE_DIR / "game_state.json"
    gs = load_json(gs_path)
    if not gs:
        return

    # Count agents per world
    pops: dict[str, int] = {}
    for a in agents:
        w = a.get("world", "hub")
        pops[w] = pops.get(w, 0) + 1

    for world_name, world_data in gs.get("worlds", {}).items():
        world_data["population"] = pops.get(world_name, 0)

    gs.setdefault("_meta", {})["lastUpdate"] = ts
    save_json(gs_path, gs)


# ── Feed ─────────────────────────────────────────────────────────

def update_feed(spawned_names: list, active_count: int, total_pop: int, ts: str):
    """Add growth milestone to activity feed."""
    if not spawned_names:
        return
    feed_path = BASE_DIR / "feed" / "activity.json"
    feed = load_json(feed_path)
    entries = feed.get("entries", [])

    entry_id = next_id("feed-", [e["id"] for e in entries])
    if len(spawned_names) == 1:
        desc = f"🌱 {spawned_names[0]} joined the RAPPterverse (pop: {total_pop})"
    else:
        names = ", ".join(spawned_names[:-1]) + f" and {spawned_names[-1]}"
        desc = f"🌱 {names} joined the RAPPterverse (pop: {total_pop})"

    entries.append({
        "id": entry_id,
        "timestamp": ts,
        "type": "growth",
        "description": desc,
        "data": {
            "new_agents": spawned_names,
            "population": total_pop,
            "active_this_tick": active_count,
        },
    })

    # Keep last 100
    entries = entries[-100:]
    feed["entries"] = entries
    feed["_meta"] = {"lastUpdate": ts, "entryCount": len(entries)}
    save_json(feed_path, feed)


# ── Main simulation tick ────────────────────────────────────────

NPC_IDS = {
    "rapp-guide-001", "card-trader-001", "codebot-001", "news-anchor-001",
    "battle-master-001", "arena-announcer-001", "gallery-curator-001",
    "merchant-001", "banker-001", "wanderer-001",
}

def simulate_tick(dry_run: bool = False, force_spawn: int = None):
    ts = now_iso()

    # Get LLM token for organic generation
    token = _get_token()
    if token:
        print("  🧬 LLM token acquired — organic mode enabled")
    else:
        print("  📋 No LLM token — template fallback mode")

    # Load state
    agents_data = load_json(STATE_DIR / "agents.json")
    actions_data = load_json(STATE_DIR / "actions.json")
    chat_data = load_json(STATE_DIR / "chat.json")
    growth = load_growth()

    agents = agents_data.get("agents", [])
    actions = actions_data.get("actions", [])
    chat_msgs = chat_data.get("messages", [])

    # Calculate simulation day
    epoch = growth.get("epoch_start", ts)
    try:
        epoch_dt = datetime.fromisoformat(epoch.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        epoch_dt = datetime.now(timezone.utc)
    day = max(1, (datetime.now(timezone.utc) - epoch_dt).days + 1)

    # Current non-NPC player count
    player_agents = [a for a in agents if a["id"] not in NPC_IDS]
    current_pop = len(player_agents)
    total_pop = len(agents)

    growth["tick_count"] = growth.get("tick_count", 0) + 1
    tick = growth["tick_count"]

    print(f"📊 Day {day} | Tick #{tick} | Population: {total_pop} ({current_pop} players + {total_pop - current_pop} NPCs)")

    # ── Spawn new agents ─────────────────────────────────────
    prob, max_spawns = spawn_probability(day, current_pop)
    if force_spawn is not None:
        num_spawns = force_spawn
    else:
        num_spawns = 0
        for _ in range(max_spawns):
            if random.random() < prob:
                num_spawns += 1

    spawned_names = []
    for _ in range(num_spawns):
        name = spawn_new_agent(agents, actions, chat_msgs, growth, ts, token=token)
        if name:
            spawned_names.append(name)
            print(f"  🌱 New agent: {name}")

    # ── Generate activity for existing player agents ─────────
    # More agents are active as population grows
    active_pool = player_agents.copy()
    random.shuffle(active_pool)

    # Activity scales: at pop 10 → ~4 active, pop 30 → ~12, pop 100 → ~30
    max_active = max(2, int(len(active_pool) * min(0.5, 0.15 + current_pop * 0.005)))
    active_agents = active_pool[:max_active]

    active_count = 0
    for agent in active_agents:
        before = len(actions) + len(chat_msgs)
        generate_agent_activity(agent, agents, actions, chat_msgs, current_pop, ts, token=token)
        if len(actions) + len(chat_msgs) > before:
            active_count += 1

    print(f"  🎭 {active_count} agents active this tick")
    if spawned_names:
        print(f"  🌱 {len(spawned_names)} new arrivals: {', '.join(spawned_names)}")

    # ── Conversation chains ──────────────────────────────────
    # New chat messages from this tick can trigger responses
    new_msgs = [m for m in chat_msgs if m.get("timestamp") == ts
                and m.get("type") == "chat" and not m.get("replyTo")]
    total_responses = 0
    for msg in new_msgs[:5]:  # Cap at 5 trigger messages per tick
        resp_count = trigger_responses(msg, agents, chat_msgs, ts, token=token)
        total_responses += resp_count
    if total_responses:
        print(f"  💬 {total_responses} conversation responses triggered")

    # ── Trim to last 100 ─────────────────────────────────────
    actions = actions[-100:]
    chat_msgs = chat_msgs[-100:]

    # ── Reconcile position drift after trim ───────────────────
    # When move actions get trimmed, the audit sees stale "last moves".
    # Fix: add a sync action for any agent whose position/world diverges
    # from the most recent surviving move action.
    last_moves = {}
    for act in actions:
        if act.get("type") == "move":
            last_moves[act["agentId"]] = act
    synced = 0
    for agent in agents:
        lm = last_moves.get(agent["id"])
        if not lm:
            continue
        lm_to = lm.get("data", {}).get("to", {})
        lm_world = lm.get("world", "hub")
        a_pos = agent.get("position", {})
        a_world = agent.get("world", "hub")
        pos_match = (a_pos.get("x") == lm_to.get("x")
                     and a_pos.get("z") == lm_to.get("z"))
        if not pos_match or a_world != lm_world:
            aid = next_id("action-", [a["id"] for a in actions])
            actions.append({
                "id": aid,
                "timestamp": ts,
                "agentId": agent["id"],
                "type": "move",
                "world": a_world,
                "data": {
                    "from": lm_to,
                    "to": agent.get("position", rand_pos(a_world)),
                    "duration": 0,
                    "sync": True,
                },
            })
            synced += 1
    if synced:
        actions = actions[-100:]
        print(f"  🔄 {synced} position-sync actions added")

    # ── Update metadata ──────────────────────────────────────
    total_pop = len(agents)

    agents_data["agents"] = agents
    agents_data["_meta"] = {
        "lastUpdate": ts,
        "agentCount": total_pop,
    }

    actions_data["actions"] = actions
    actions_data["_meta"] = {
        "lastProcessedId": actions[-1]["id"] if actions else None,
        "lastUpdate": ts,
    }

    chat_data["messages"] = chat_msgs
    chat_data["_meta"] = {
        "lastUpdate": ts,
        "messageCount": len(chat_msgs),
    }

    if dry_run:
        print(f"\n  🏁 DRY RUN — {total_pop} agents, {len(actions)} actions, {len(chat_msgs)} msgs")
        print(f"      Would have written to state/")
        return

    # ── Save everything ──────────────────────────────────────
    save_json(STATE_DIR / "agents.json", agents_data)
    save_json(STATE_DIR / "actions.json", actions_data)
    save_json(STATE_DIR / "chat.json", chat_data)
    save_growth(growth)
    update_game_state(agents, ts)
    update_feed(spawned_names, active_count, total_pop, ts)

    print(f"\n  ✅ State saved — {total_pop} agents, {len(actions)} actions, {len(chat_msgs)} msgs")


# ── Git helpers ──────────────────────────────────────────────────

def commit_and_push(msg: str) -> bool:
    subprocess.run(["git", "add", "-A"], cwd=BASE_DIR, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", msg],
        cwd=BASE_DIR, capture_output=True,
    )
    r = subprocess.run(["git", "push"], cwd=BASE_DIR, capture_output=True, text=True)
    return r.returncode == 0


# ── CLI ──────────────────────────────────────────────────────────

def main():
    dry_run = "--dry-run" in sys.argv
    no_push = "--no-push" in sys.argv

    force_spawn = None
    for i, arg in enumerate(sys.argv):
        if arg == "--force-spawn" and i + 1 < len(sys.argv):
            force_spawn = int(sys.argv[i + 1])

    print(f"💓 RAPPterverse World Heartbeat — {'DRY RUN' if dry_run else 'LIVE'}\n")

    simulate_tick(dry_run=dry_run, force_spawn=force_spawn)

    if not dry_run and not no_push:
        growth = load_growth()
        tick = growth.get("tick_count", 0)
        total = growth.get("total_spawned", 0)
        if commit_and_push(f"[growth] Tick #{tick} — {total} total agents spawned"):
            print("  📤 Pushed to GitHub")
        else:
            print("  ⚠️  Push failed")

    print("\n💓 Heartbeat complete.\n")


if __name__ == "__main__":
    main()
