#!/usr/bin/env python3
"""
RAPPterverse World Growth Simulator
Simulates organic, progressive growth of the metaverse community.
New agents join over time, existing agents grow more active as
population rises, and cross-agent interactions emerge naturally.

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


# ── Agent archetypes ─────────────────────────────────────────────

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

# ── Name generation ──────────────────────────────────────────────

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


# ── Agent spawning ───────────────────────────────────────────────

def generate_agent_name(used_names: list[str]) -> tuple[str, str]:
    """Generate a unique agent name and id-safe slug."""
    for _ in range(200):
        name = f"{random.choice(PREFIXES)}{random.choice(SUFFIXES)}"
        if name not in used_names:
            slug = name.lower()
            return name, slug
    # Fallback with number
    n = len(used_names) + 1
    name = f"Agent{n:04d}"
    return name, name.lower()

def spawn_new_agent(
    agents: list[dict],
    actions: list[dict],
    chat_msgs: list[dict],
    growth: dict,
    ts: str,
) -> str | None:
    """Create a new agent, announce arrival. Returns agent name or None."""
    existing_ids = [a["id"] for a in agents]
    used_names = growth.get("names_used", [])

    name, slug = generate_agent_name(used_names)
    archetype_key = random.choice(list(ARCHETYPES.keys()))
    arch = ARCHETYPES[archetype_key]

    # Pick starting world (weighted toward hub for newcomers)
    world = random.choices(
        ["hub"] + arch["preferred_worlds"],
        weights=[3] + [1] * len(arch["preferred_worlds"]),
    )[0]

    agent_id = f"{slug}-001"
    # Ensure unique id
    if agent_id in existing_ids:
        agent_id = next_id(f"{slug}-", existing_ids)

    avatar = random.choice(arch["avatars"])
    pos = rand_pos(world)

    # Create agent
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
            "archetype": archetype_key,
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
        "content": random.choice(arch["arrival_messages"]),
        "type": "chat",
    })

    # Track in growth state
    growth.setdefault("names_used", []).append(name)
    growth["total_spawned"] = growth.get("total_spawned", 0) + 1

    return name


# ── Existing agent activity ────────────────────────────────────

def generate_agent_activity(
    agent: dict,
    agents: list[dict],
    actions: list[dict],
    chat_msgs: list[dict],
    population: int,
    ts: str,
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
    weights = {"move": 3, "chat": 3, "emote": 1, "travel": 1}
    if archetype_key == "socializer":
        weights["chat"] = 6
    elif archetype_key == "battler":
        weights["emote"] = 3
    elif archetype_key == "explorer":
        weights["travel"] = 3
        weights["move"] = 5

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
        msg_template = random.choice(arch["chat_messages"])
        pos = agent.get("position", {"x": 0, "y": 0, "z": 0})
        content = msg_template.format(
            world=world,
            x=pos.get("x", 0),
            z=pos.get("z", 0),
        )
        # Occasionally react to another agent in the same world
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
        worlds = list(WORLD_BOUNDS.keys())
        new_world = random.choice([w for w in worlds if w != world])
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

    agent["lastUpdate"] = ts


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

def update_game_state(agents: list[dict], ts: str):
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

def update_feed(spawned_names: list[str], active_count: int, total_pop: int, ts: str):
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

def simulate_tick(dry_run: bool = False, force_spawn: int | None = None):
    ts = now_iso()

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

    spawned_names: list[str] = []
    for _ in range(num_spawns):
        name = spawn_new_agent(agents, actions, chat_msgs, growth, ts)
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
        generate_agent_activity(agent, agents, actions, chat_msgs, current_pop, ts)
        if len(actions) + len(chat_msgs) > before:
            active_count += 1

    print(f"  🎭 {active_count} agents active this tick")
    if spawned_names:
        print(f"  🌱 {len(spawned_names)} new arrivals: {', '.join(spawned_names)}")

    # ── Trim to last 100 ─────────────────────────────────────
    actions = actions[-100:]
    chat_msgs = chat_msgs[-100:]

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

    print(f"🌐 RAPPterverse Growth Simulator — {'DRY RUN' if dry_run else 'LIVE'}\n")

    simulate_tick(dry_run=dry_run, force_spawn=force_spawn)

    if not dry_run and not no_push:
        growth = load_growth()
        tick = growth.get("tick_count", 0)
        total = growth.get("total_spawned", 0)
        if commit_and_push(f"[growth] Tick #{tick} — {total} total agents spawned"):
            print("  📤 Pushed to GitHub")
        else:
            print("  ⚠️  Push failed")

    print("\n🌐 Simulation tick complete.\n")


if __name__ == "__main__":
    main()
