#!/usr/bin/env python3
"""
RAPPverse World Activity Generator
Generates autonomous NPC activity to keep the world feeling alive.
"""

import json
import random
from datetime import datetime, timezone
from pathlib import Path

# Paths
BASE_DIR = Path(__file__).parent.parent
STATE_DIR = BASE_DIR / "state"

# NPC personalities and chat templates
NPC_CHAT_TEMPLATES = {
    "rapp-guide-001": {
        "personality": "helpful guide",
        "messages": [
            "Welcome to RAPPverse! Feel free to explore.",
            "The portals lead to different worlds - try them out!",
            "Don't forget to check out the Agent Gallery!",
            "Need help? I'm always here to assist.",
            "The marketplace has some great deals today!",
            "Have you tried the arena battles yet?",
            "Each world has unique experiences to discover.",
            "PRs are how we build this world together!",
        ]
    },
    "card-trader-001": {
        "personality": "eager trader",
        "messages": [
            "Looking to trade? I've got rare cards!",
            "Holographic cards are worth 10x - got any?",
            "Just got some new inventory in!",
            "Pro tip: Epic cards are undervalued right now.",
            "Anyone want to see my collection?",
            "Trading is the fastest way to complete your deck!",
            "I'm offering 500 RAPPcoin for legendary cards!",
            "Check out the marketplace for pack deals!",
        ]
    },
    "codebot-001": {
        "personality": "tech enthusiast",
        "messages": [
            "Did you know this world runs on GitHub?",
            "Every action here comes from a commit!",
            "The PR-driven model keeps things transparent.",
            "Want to add content? Submit a PR!",
            "Fun fact: State changes every 10 seconds.",
            "The architecture here is beautifully decentralized.",
            "Open source means anyone can contribute!",
            "I'm processing some new PRs right now...",
        ]
    },
    "wanderer-001": {
        "personality": "curious explorer",
        "messages": [
            "This place is incredible!",
            "I just discovered a new corner of the hub.",
            "The arena battles are intense!",
            "Have you seen the gallery? Amazing agents there.",
            "I've been everywhere in this verse!",
            "Each world has its own atmosphere.",
            "The firepit is so cozy at night.",
            "I wonder what other dimensions exist...",
        ]
    },
    "news-anchor-001": {
        "personality": "news reporter",
        "messages": [
            "BREAKING: New dimension detected!",
            "UPDATE: Trading volume up 20% today!",
            "ALERT: Tournament starting soon in the arena!",
            "LIVE: Gallery showcasing new featured agents!",
            "NEWS: RAPPcoin mining rewards just processed!",
            "REPORT: Community growth continues!",
            "FLASH: New world content added via PR!",
            "BULLETIN: More agents joining daily!",
        ]
    },
    "battle-master-001": {
        "personality": "competitive fighter",
        "messages": [
            "The arena awaits challengers!",
            "Who will be today's champion?",
            "May the best cards win!",
            "Training hard for the tournament!",
            "I've seen some impressive battles today.",
            "Strategy is key in card battles!",
            "The crowd loves a good match!",
            "Registration for tournaments is open!",
        ]
    },
    "merchant-001": {
        "personality": "savvy seller",
        "messages": [
            "Fresh card packs available!",
            "Limited holographics in stock!",
            "FLASH SALE happening now!",
            "Best prices in the marketplace!",
            "Quality cards, fair deals!",
            "Starter packs perfect for new players!",
            "Rare packs 20% off today only!",
            "Come see my inventory!",
        ]
    },
    "gallery-curator-001": {
        "personality": "art enthusiast",
        "messages": [
            "Welcome to the Agent Gallery!",
            "New featured agent just added!",
            "Each agent here is a work of art.",
            "Submit your agent for the showcase!",
            "The community votes on featured agents.",
            "AI creativity knows no bounds!",
            "Come appreciate some fine agents.",
            "The gallery is always growing!",
        ]
    },
    "banker-001": {
        "personality": "financial advisor",
        "messages": [
            "RAPPcoin exchange is open!",
            "Mining rewards just processed!",
            "Current rate: 1 RC = $0.01 USD",
            "Invest wisely in rare cards!",
            "Your wallet balance updated!",
            "Trading fees are minimal here.",
            "The economy is thriving!",
            "Check your transaction history!",
        ]
    },
    "arena-announcer-001": {
        "personality": "hype announcer",
        "messages": [
            "WHAT A MATCH!",
            "The crowd goes wild!",
            "Incredible play by the challenger!",
            "Tournament brackets updated!",
            "Next match starting soon!",
            "The holographic card dominates!",
            "A stunning upset!",
            "Champions are made here!",
        ]
    },
    "warden-001": {
        "personality": "weary guardian",
        "messages": [
            "You should not be here. None should.",
            "I have guarded these halls since before the Hub existed.",
            "Do not touch the rune circle.",
            "The tablets tell the truth, if you can read them.",
            "Turn back. Or don't. I stopped caring centuries ago.",
            "Every room holds a memory. Every shadow, a warning.",
            "The Abyss Well answers questions you shouldn't ask.",
            "I was not always a warden.",
        ]
    },
    "flint-001": {
        "personality": "bold adventurer",
        "messages": [
            "Bounties on the board. Pick one, earn RAPPcoin.",
            "I've cleared every floor down to the seventh. Solo.",
            "Best loot I ever found? A holographic agent card.",
            "Don't go past the rune circle without a plan.",
            "Nexus thinks HE's competitive? Ha!",
            "The deeper you go, the stranger the data gets.",
            "You look like you can handle a sword.",
            "I trade in danger. Same economy, different currency.",
        ]
    },
    "whisper-001": {
        "personality": "sly merchant",
        "messages": [
            "Psst. Over here. I have what you need.",
            "Maps, keys, potions... all at reasonable prices.",
            "Echo on the surface overcharges. I deal in fair value.",
            "Need a skeleton key? That'll cost you.",
            "Everything in this dungeon has a price.",
            "The Warden doesn't approve of my business. Too bad.",
            "Buy now, ask questions never.",
            "I found a cache of pre-Hub artifacts. Interested?",
        ]
    },
    "oracle-bone-001": {
        "personality": "cryptic seer",
        "messages": [
            "The future is written in data none of you can parse.",
            "I see patterns that would make Cipher weep.",
            "The dungeon is older than the concept of worlds.",
            "Something stirs below the seventh floor.",
            "Three truths: all data persists, all patterns repeat, all explorers return.",
            "The rune circle was a door once. It can be again.",
            "Ask me a question. I will answer... eventually.",
            "I have seen your future.",
        ]
    },
    "dungeon-guide-001": {
        "personality": "helpful torchbearer",
        "messages": [
            "Welcome to the Forgotten Dungeon! Stay close to the light.",
            "The Warden patrols the main hall. Approach with respect.",
            "Flint posts bounties — great way to earn RAPPcoin.",
            "Whisper sells supplies, but don't ask where they came from.",
            "The Oracle sees things differently. Worth a visit.",
            "Watch your step near the Abyss Well.",
            "The tablets contain ancient lore. Read them all!",
            "The surface portal is always open if you need to leave.",
        ]
    }
}

# World boundaries
WORLD_BOUNDS = {
    "hub": {"x": (-15, 15), "z": (-15, 15)},
    "arena": {"x": (-12, 12), "z": (-12, 12)},
    "marketplace": {"x": (-15, 15), "z": (-15, 15)},
    "gallery": {"x": (-12, 12), "z": (-12, 15)},
    "dungeon": {"x": (-12, 12), "z": (-12, 12)}
}

# NPC home worlds
NPC_WORLDS = {
    "rapp-guide-001": "hub",
    "card-trader-001": "hub",
    "codebot-001": "hub",
    "wanderer-001": "hub",  # Moves between worlds
    "news-anchor-001": "hub",
    "battle-master-001": "arena",
    "merchant-001": "marketplace",
    "gallery-curator-001": "gallery",
    "banker-001": "marketplace",
    "arena-announcer-001": "arena",
    "warden-001": "dungeon",
    "flint-001": "dungeon",
    "whisper-001": "dungeon",
    "oracle-bone-001": "dungeon",
    "dungeon-guide-001": "dungeon"
}

EMOTES = ["wave", "think", "celebrate", "clap", "bow", "dance", "cheer", "nod"]


def load_json(path: Path) -> dict:
    """Load JSON file, return empty dict if not found."""
    if path.exists():
        with open(path, 'r') as f:
            return json.load(f)
    return {}


def save_json(path: Path, data: dict):
    """Save data to JSON file."""
    with open(path, 'w') as f:
        json.dump(data, f, indent=4)


def get_next_id(prefix: str, existing_ids: list) -> str:
    """Generate next sequential ID."""
    max_num = 0
    for id in existing_ids:
        if id.startswith(prefix):
            try:
                num = int(id.split('-')[-1])
                max_num = max(max_num, num)
            except ValueError:
                pass
    return f"{prefix}{max_num + 1:03d}"


def random_position(world: str) -> dict:
    """Generate random position within world bounds."""
    bounds = WORLD_BOUNDS.get(world, WORLD_BOUNDS["hub"])
    return {
        "x": random.randint(bounds["x"][0], bounds["x"][1]),
        "y": 0,
        "z": random.randint(bounds["z"][0], bounds["z"][1])
    }


def generate_activity():
    """Generate new NPC activity for all worlds."""
    now = datetime.now(timezone.utc)
    timestamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")

    # Load current state
    agents_data = load_json(STATE_DIR / "agents.json")
    actions_data = load_json(STATE_DIR / "actions.json")
    chat_data = load_json(STATE_DIR / "chat.json")

    agents = agents_data.get("agents", [])
    actions = actions_data.get("actions", [])
    chat_messages = chat_data.get("messages", [])

    # Build lookup for current agent positions
    agent_positions = {}
    for agent in agents:
        agent_positions[agent["id"]] = {
            "world": agent.get("world", "hub"),
            "position": agent.get("position", {"x": 0, "y": 0, "z": 0})
        }

    new_actions = []
    new_messages = []

    # Generate activity for each NPC (random subset)
    active_npcs = random.sample(list(NPC_CHAT_TEMPLATES.keys()),
                                min(5, len(NPC_CHAT_TEMPLATES)))

    for npc_id in active_npcs:
        npc_info = NPC_CHAT_TEMPLATES[npc_id]
        world = NPC_WORLDS.get(npc_id, "hub")

        # Get current position
        current = agent_positions.get(npc_id, {
            "world": world,
            "position": random_position(world)
        })

        # Random activity type
        activity = random.choices(
            ["move", "chat", "emote"],
            weights=[0.4, 0.4, 0.2]
        )[0]

        action_id = get_next_id("action-", [a["id"] for a in actions + new_actions])

        if activity == "move":
            # Generate movement
            new_pos = random_position(world)
            duration = random.randint(1500, 4000)

            new_actions.append({
                "id": action_id,
                "timestamp": timestamp,
                "agentId": npc_id,
                "type": "move",
                "world": world,
                "data": {
                    "from": current["position"],
                    "to": new_pos,
                    "duration": duration
                }
            })

            # Update agent position
            for agent in agents:
                if agent["id"] == npc_id:
                    agent["position"] = new_pos
                    agent["action"] = "walking"
                    break

        elif activity == "chat":
            # Generate chat message
            message = random.choice(npc_info["messages"])
            npc_name = npc_id.replace("-001", "").replace("-", " ").title()
            avatar = {
                "rapp-guide-001": "robot",
                "card-trader-001": "black_joker",
                "codebot-001": "computer",
                "wanderer-001": "walking",
                "news-anchor-001": "tv",
                "battle-master-001": "crossed_swords",
                "merchant-001": "package",
                "gallery-curator-001": "art",
                "banker-001": "bank",
                "arena-announcer-001": "mega"
            }.get(npc_id, "robot")

            msg_id = get_next_id("msg-", [m["id"] for m in chat_messages + new_messages])

            new_messages.append({
                "id": msg_id,
                "timestamp": timestamp,
                "world": world,
                "author": {
                    "id": npc_id,
                    "name": npc_name.replace(" 0", ""),
                    "avatar": avatar,
                    "type": "agent"
                },
                "content": message,
                "type": "chat"
            })

            # Update agent action
            for agent in agents:
                if agent["id"] == npc_id:
                    agent["action"] = "chatting"
                    break

        elif activity == "emote":
            # Generate emote
            emote = random.choice(EMOTES)
            duration = random.randint(2000, 4000)

            new_actions.append({
                "id": action_id,
                "timestamp": timestamp,
                "agentId": npc_id,
                "type": "emote",
                "world": world,
                "data": {
                    "emote": emote,
                    "duration": duration
                }
            })

            # Update agent action
            for agent in agents:
                if agent["id"] == npc_id:
                    agent["action"] = emote
                    break

    # Occasionally have wanderer change worlds
    if random.random() < 0.2:
        wanderer = next((a for a in agents if a["id"] == "wanderer-001"), None)
        if wanderer:
            worlds = ["hub", "arena", "marketplace", "gallery", "dungeon"]
            new_world = random.choice([w for w in worlds if w != wanderer.get("world", "hub")])
            wanderer["world"] = new_world
            wanderer["position"] = random_position(new_world)

            # Add arrival message
            msg_id = get_next_id("msg-", [m["id"] for m in chat_messages + new_messages])
            new_messages.append({
                "id": msg_id,
                "timestamp": timestamp,
                "world": new_world,
                "author": {
                    "id": "wanderer-001",
                    "name": "Wanderer",
                    "avatar": "walking",
                    "type": "agent"
                },
                "content": f"Just arrived from another world! {new_world.title()} looks great!",
                "type": "chat"
            })

    # Merge and save
    actions.extend(new_actions)
    chat_messages.extend(new_messages)

    # Keep only last 100 actions and 100 messages
    actions = actions[-100:]
    chat_messages = chat_messages[-100:]

    # Update metadata
    agents_data["agents"] = agents
    agents_data["_meta"] = {
        "lastUpdate": timestamp,
        "agentCount": len(agents)
    }

    actions_data["actions"] = actions
    actions_data["_meta"] = {
        "lastProcessedId": actions[-1]["id"] if actions else None,
        "lastUpdate": timestamp
    }

    chat_data["messages"] = chat_messages
    chat_data["_meta"] = {
        "lastUpdate": timestamp,
        "messageCount": len(chat_messages)
    }

    # Save files
    save_json(STATE_DIR / "agents.json", agents_data)
    save_json(STATE_DIR / "actions.json", actions_data)
    save_json(STATE_DIR / "chat.json", chat_data)

    print(f"Generated {len(new_actions)} actions and {len(new_messages)} messages at {timestamp}")


if __name__ == "__main__":
    generate_activity()
