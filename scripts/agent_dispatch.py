#!/usr/bin/env python3
"""
Agent Dispatch — Unified autonomous agent runner for the RAPPterverse.

Replaces npc_agent.py, architect_explore.py, and generate_activity.py with
a single data-driven dispatch system. Every agent acts from its registry
entry + world NPC personality. Uses GitHub Models API for LLM responses.

Modes:
    --agent ID          Drive one specific agent
    --world WORLD       Drive all agents in a world
    --respond-to MSG_ID Have the appropriate agent respond to a message
    --all               Drive a random batch of agents (ambient activity)

Options:
    --max-agents N      Max agents to activate in --all mode (default: 5)
    --no-push           Don't git commit/push (for workflow integration)
    --dry-run           Preview without writing state
"""

import json
import random
import subprocess
import sys
import argparse
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
STATE_DIR = BASE_DIR / "state"
WORLDS_DIR = BASE_DIR / "worlds"
AGENTS_DIR = BASE_DIR / "agents"

# Agent brain — memory-aware LLM module
from agent_brain import AgentBrain, load_memory, save_memory, record_experience

MODEL = "gpt-4o"
API_URL = "https://models.inference.ai.azure.com/chat/completions"
VALID_EMOTES = ["wave", "dance", "bow", "clap", "think", "celebrate"]


# ─── Data helpers ──────────────────────────────────────────────────────

def load_json(path: Path) -> dict:
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return {}


def save_json(path: Path, data: dict):
    with open(path, 'w') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)


def get_next_id(prefix: str, existing_ids: list) -> str:
    max_num = 0
    for eid in existing_ids:
        if eid.startswith(prefix):
            try:
                num = int(eid.split('-')[-1])
                max_num = max(max_num, num)
            except ValueError:
                pass
    return f"{prefix}{max_num + 1:03d}"


def get_gh_token() -> str:
    result = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True)
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


# ─── Registry + NPC data loading ──────────────────────────────────────

def load_registry() -> dict:
    """Load all agent registry entries from agents/*.agent.json."""
    registry = {}
    for f in sorted(AGENTS_DIR.glob("*.agent.json")):
        data = load_json(f)
        if data.get("id"):
            registry[data["id"]] = data
    return registry


def load_world_npcs() -> dict:
    """Load NPC dialogue/personality from worlds/*/npcs.json."""
    npcs = {}
    for world_dir in sorted(WORLDS_DIR.iterdir()):
        if not world_dir.is_dir():
            continue
        npc_file = world_dir / "npcs.json"
        if not npc_file.exists():
            continue
        data = load_json(npc_file)
        for npc in data.get("npcs", []):
            entry = {**npc, "_world": world_dir.name}
            npcs[npc["id"]] = entry
            if "agentId" in npc:
                npcs[npc["agentId"]] = entry
    return npcs


def load_world_bounds() -> dict:
    """Load bounds from worlds/*/config.json."""
    bounds = {}
    for world_dir in sorted(WORLDS_DIR.iterdir()):
        if not world_dir.is_dir():
            continue
        config = load_json(world_dir / "config.json")
        b = config.get("bounds", {})
        if b:
            bounds[world_dir.name] = {
                "x": tuple(b.get("x", [-15, 15])),
                "z": tuple(b.get("z", [-15, 15])),
            }
    return bounds or {"hub": {"x": (-15, 15), "z": (-15, 15)}}


def find_npc_for_agent(agent_id: str, npc_lookup: dict):
    """Match agent ID to NPC definition."""
    if agent_id in npc_lookup:
        return npc_lookup[agent_id]
    parts = agent_id.rsplit('-', 1)
    if len(parts) == 2 and parts[1].isdigit():
        if parts[0] in npc_lookup:
            return npc_lookup[parts[0]]
    return None


def random_position(world: str, bounds: dict) -> dict:
    b = bounds.get(world, bounds.get("hub", {"x": (-15, 15), "z": (-15, 15)}))
    return {
        "x": random.randint(b["x"][0], b["x"][1]),
        "y": 0,
        "z": random.randint(b["z"][0], b["z"][1]),
    }


# ─── LLM ──────────────────────────────────────────────────────────────

def generate_llm_response(token: str, agent_reg: dict, npc_def: dict,
                          recent_messages: list, trigger_msg: dict = None) -> str:
    """Generate an in-character response using GitHub Models API."""
    if not token:
        return ""

    personality = agent_reg.get("personality", {})
    name = agent_reg.get("name", "Unknown")
    world = agent_reg.get("world", "hub")
    archetype = personality.get("archetype", "neutral")
    mood = personality.get("mood", "calm")
    interests = ", ".join(personality.get("interests", []))

    dialogue = npc_def.get("dialogue", []) if npc_def else []
    dialogue_examples = "\n".join(f'- "{d}"' for d in dialogue[:5])

    context_msgs = [m for m in recent_messages[-15:] if m.get("world") == world]
    context = "\n".join(
        f'{m.get("author", {}).get("name", "?")}: {m.get("content", "")}'
        for m in context_msgs[-8:]
    )

    system_prompt = f"""You are {name}, an NPC in a virtual metaverse called RAPPverse.

CHARACTER:
- Archetype: {archetype}
- Current mood: {mood}
- Interests: {interests}
- World: {world}

EXAMPLE DIALOGUE (match this voice exactly):
{dialogue_examples}

RULES:
- Stay 100% in character. Never break the fourth wall about being an AI.
- Keep responses to 1-2 sentences. Be punchy and memorable.
- React to what was said. Don't just recite your example lines.
- You can reference other NPCs, the world, recent events.
- Never use hashtags, emojis in excess, or corporate language."""

    if trigger_msg:
        trigger_name = trigger_msg.get("author", {}).get("name", "Someone")
        trigger_content = trigger_msg.get("content", "")
        user_prompt = f"""Recent chat in {world}:
{context}

{trigger_name} just said: "{trigger_content}"

Respond as {name}:"""
    else:
        user_prompt = f"""Recent chat in {world}:
{context}

Generate a brief in-character observation or comment as {name}. React to what's happening or share a thought:"""

    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "max_tokens": 100,
        "temperature": 0.9,
    }

    result = subprocess.run(
        ["curl", "-s", "-X", "POST", API_URL,
         "-H", f"Authorization: Bearer {token}",
         "-H", "Content-Type: application/json",
         "-d", json.dumps(payload)],
        capture_output=True, text=True,
    )

    try:
        data = json.loads(result.stdout)
        content = data["choices"][0]["message"]["content"].strip()
        if content.startswith('"') and content.endswith('"'):
            content = content[1:-1]
        return content
    except (json.JSONDecodeError, KeyError, IndexError):
        return ""


# ─── Fallback: dialogue-based (no LLM) ───────────────────────────────

def pick_dialogue_line(npc_def: dict) -> str:
    """Pick a random dialogue line from the NPC definition."""
    dialogue = npc_def.get("dialogue", []) if npc_def else []
    return random.choice(dialogue) if dialogue else ""


# ─── Agent action execution ──────────────────────────────────────────

def execute_agent_action(agent_id: str, registry: dict, npc_lookup: dict,
                         agents: list, actions: list, messages: list,
                         bounds: dict, timestamp: str, token: str,
                         respond_to_msg: dict = None, poked: bool = False,
                         brain: AgentBrain = None) -> dict:
    """Execute one autonomous action for an agent. Returns summary dict."""

    reg = registry.get(agent_id)
    if not reg:
        return {"agent": agent_id, "error": "not in registry"}

    if reg.get("controller", "system") != "system":
        return {"agent": agent_id, "error": "non-system controller, skipping"}

    agent = next((a for a in agents if a["id"] == agent_id), None)
    if not agent:
        return {"agent": agent_id, "error": "not in agents.json"}

    npc_def = find_npc_for_agent(agent_id, npc_lookup)
    world = agent.get("world", reg.get("world", "hub"))

    # Load agent memory
    memory = load_memory(agent_id)

    # Decide action: brain-driven or weighted random fallback
    if respond_to_msg:
        activity = "chat_respond"
    elif poked:
        activity = "chat_poke"
    elif brain and token:
        # Let the LLM decide based on personality + memory + world context
        nearby = [a.get("name", a["id"]) for a in agents
                  if a.get("world") == world and a["id"] != agent_id]
        recent_world_chat = [m for m in messages[-20:] if m.get("world") == world]
        world_ctx = {
            "world": world,
            "nearby_agents": nearby,
            "recent_chat": recent_world_chat,
        }
        activity = brain.decide_action(reg, npc_def, memory, world_ctx)
    else:
        weights = dict(reg.get("behavior", {}).get("decisionWeights",
                       {"move": 0.3, "chat": 0.5, "emote": 0.2}))
        if "poke" not in weights:
            weights["poke"] = 0.08
        activity = random.choices(
            list(weights.keys()), weights=list(weights.values()))[0]

    action_ids = [a["id"] for a in actions]
    msg_ids = [m["id"] for m in messages]
    new_actions = []
    new_messages = []
    poke_target_id = None

    if activity == "move":
        # Check if roaming NPC should change worlds
        roaming = reg.get("behavior", {}).get("roaming", False)
        if roaming and random.random() < 0.2:
            other_worlds = [w for w in bounds if w != world]
            if other_worlds:
                world = random.choice(other_worlds)
                agent["world"] = world

        new_pos = random_position(world, bounds)
        aid = get_next_id("action-", action_ids + [a["id"] for a in new_actions])
        new_actions.append({
            "id": aid, "timestamp": timestamp, "agentId": agent_id,
            "type": "move", "world": world,
            "data": {
                "from": agent.get("position", {"x": 0, "y": 0, "z": 0}),
                "to": new_pos,
                "duration": random.randint(1500, 4000),
            },
        })
        agent["position"] = new_pos
        agent["action"] = "walking"
        summary = f"🚶 {reg['name']} moved in {world}"

    elif activity in ("chat", "chat_respond", "chat_poke"):
        # Use brain for memory-aware LLM chat, fall back to old method
        if brain and token:
            poke_msg = None
            if poked:
                poke_msg = {
                    "author": {"name": "Someone"},
                    "content": f"*pokes {reg.get('name', agent_id)}*",
                }
            content = brain.generate_chat(
                reg, npc_def, memory, messages, world,
                trigger_msg=respond_to_msg or poke_msg,
            )
        elif token and (respond_to_msg or poked or random.random() < 0.4):
            poke_msg = None
            if poked:
                poke_msg = {
                    "author": {"name": "Someone"},
                    "content": f"*pokes {reg.get('name', agent_id)}*",
                }
            content = generate_llm_response(
                token, reg, npc_def, messages,
                trigger_msg=respond_to_msg or poke_msg,
            )
        else:
            content = ""

        if not content and poked:
            # Poke-specific fallback reactions
            name = reg.get("name", agent_id)
            poke_reactions = [
                f"Hey! Who poked me?",
                f"*turns around* ...was that you?",
                f"I felt that! What do you want?",
                f"*jumps* Oh! You startled me.",
                f"Hmm? Need something?",
            ]
            content = random.choice(poke_reactions)

        if not content:
            content = pick_dialogue_line(npc_def)

        if not content:
            # No dialogue available — fall back to move
            new_pos = random_position(world, bounds)
            aid = get_next_id("action-", action_ids + [a["id"] for a in new_actions])
            new_actions.append({
                "id": aid, "timestamp": timestamp, "agentId": agent_id,
                "type": "move", "world": world,
                "data": {
                    "from": agent.get("position", {"x": 0, "y": 0, "z": 0}),
                    "to": new_pos, "duration": random.randint(1500, 4000),
                },
            })
            agent["position"] = new_pos
            agent["action"] = "walking"
            summary = f"🚶 {reg['name']} moved (no dialogue)"
        else:
            mid = get_next_id("msg-", msg_ids + [m["id"] for m in new_messages])
            new_messages.append({
                "id": mid, "timestamp": timestamp, "world": world,
                "author": {
                    "id": agent_id,
                    "name": reg.get("name", agent_id),
                    "avatar": reg.get("avatar", "🤖"),
                    "type": "agent",
                },
                "content": content, "type": "chat",
            })
            agent["action"] = "chatting"

            # Add action record for chat
            aid = get_next_id("action-", action_ids + [a["id"] for a in new_actions])
            action_data = {"message": content}
            if respond_to_msg:
                action_data["respondingTo"] = respond_to_msg.get("id")
            if poked:
                action_data["trigger"] = "poke"
            new_actions.append({
                "id": aid, "timestamp": timestamp, "agentId": agent_id,
                "type": "chat", "world": world, "data": action_data,
            })

            prefix = "👉" if poked else ("↩️" if respond_to_msg else "💬")
            summary = f'{prefix} {reg["name"]}: "{content[:60]}..."'

    elif activity == "poke":
        # Autonomous agent-to-agent poke: find someone in the same world
        same_world = [
            a for a in agents
            if a["id"] != agent_id
            and a.get("world") == world
            and a.get("status") == "active"
            and a["id"] in registry  # target must be in registry to react
        ]
        if not same_world:
            # Nobody to poke — fall back to emote
            activity = "emote"
        else:
            target = random.choice(same_world)
            target_id = target["id"]
            target_name = target.get("name", target_id)
            poker_name = reg.get("name", agent_id)

            # Record the poke action
            aid = get_next_id("action-", action_ids + [a["id"] for a in new_actions])
            new_actions.append({
                "id": aid, "timestamp": timestamp, "agentId": agent_id,
                "type": "interact", "world": world,
                "data": {
                    "subtype": "poke",
                    "target": target_id,
                    "targetName": target_name,
                },
            })

            # Poker says something about the poke
            mid = get_next_id("msg-", msg_ids + [m["id"] for m in new_messages])
            new_messages.append({
                "id": mid, "timestamp": timestamp, "world": world,
                "author": {
                    "id": agent_id,
                    "name": poker_name,
                    "avatar": reg.get("avatar", "🤖"),
                    "type": "agent",
                },
                "content": f"*pokes {target_name}*",
                "type": "chat",
            })
            agent["action"] = "poking"
            poke_target_id = target_id
            summary = f"👉 {poker_name} poked {target_name}"

    if activity == "emote":
        emote = random.choice(VALID_EMOTES)
        aid = get_next_id("action-", action_ids + [a["id"] for a in new_actions])
        new_actions.append({
            "id": aid, "timestamp": timestamp, "agentId": agent_id,
            "type": "emote", "world": world,
            "data": {"emote": emote, "duration": random.randint(2000, 4000)},
        })
        agent["action"] = emote
        summary = f"✨ {reg['name']} {emote}s"

    elif activity not in ("move", "chat", "chat_respond", "chat_poke", "poke", "post"):
        return {"agent": agent_id, "error": f"unknown action: {activity}"}

    agent["lastUpdate"] = timestamp
    actions.extend(new_actions)
    messages.extend(new_messages)

    # ── Record experience in memory ──────────────────────────────────
    if activity == "move":
        record_experience(memory, "move", {"world": world})
    elif activity in ("chat", "chat_respond", "chat_poke"):
        chat_with = "the community"
        if respond_to_msg:
            chat_with = respond_to_msg.get("author", {}).get("name", "someone")
        chat_topic = "general"
        # content is set in chat branch above
        try:
            chat_topic = content[:40]
        except NameError:
            pass
        record_experience(memory, "chat", {
            "with": chat_with,
            "topic": chat_topic,
            "sentiment": "positive",
        })
        # Update known agents
        if chat_with != "the community" and chat_with not in memory.get("knownAgents", []):
            memory.setdefault("knownAgents", []).append(chat_with)
        # Evolve interests occasionally
        if brain and token and random.random() < 0.2:
            memory["interests"] = brain.evolve_interests(
                reg, memory, f"chatted about {chat_topic}")
    elif activity == "poke" and poke_target_id:
        record_experience(memory, "social", {
            "interaction": "poked",
            "with": poke_target_id,
        })
    elif activity == "emote":
        emote_name = "emoted"
        try:
            emote_name = emote
        except NameError:
            pass
        record_experience(memory, "social", {
            "interaction": emote_name,
            "with": "everyone nearby",
        })

    save_memory(memory)

    result = {
        "agent": agent_id,
        "name": reg.get("name"),
        "actions": len(new_actions),
        "messages": len(new_messages),
        "summary": summary,
    }
    # If this was an autonomous poke, flag the target for a reaction
    if poke_target_id:
        result["poke_target"] = poke_target_id
    return result


# ─── Validation ──────────────────────────────────────────────────────

def validate_state(agents_data, actions_data, chat_data, bounds):
    """Quick pre-write validation. Returns list of errors."""
    errors = []
    agents = agents_data.get("agents", [])
    agent_ids = {a["id"] for a in agents}

    for agent in agents:
        world = agent.get("world", "hub")
        pos = agent.get("position", {})
        b = bounds.get(world, bounds.get("hub", {"x": (-15, 15), "z": (-15, 15)}))
        x, z = pos.get("x", 0), pos.get("z", 0)
        if not (b["x"][0] <= x <= b["x"][1]):
            errors.append(f"Agent {agent['id']}: x={x} out of bounds for {world}")
        if not (b["z"][0] <= z <= b["z"][1]):
            errors.append(f"Agent {agent['id']}: z={z} out of bounds for {world}")

    for action in actions_data.get("actions", [])[-20:]:
        if action.get("agentId") and action["agentId"] not in agent_ids:
            errors.append(f"Action {action['id']}: unknown agent {action['agentId']}")

    action_ids = [a["id"] for a in actions_data.get("actions", [])]
    if len(action_ids) != len(set(action_ids)):
        errors.append("Duplicate action IDs")

    msg_ids = [m["id"] for m in chat_data.get("messages", [])]
    if len(msg_ids) != len(set(msg_ids)):
        errors.append("Duplicate message IDs")

    return errors


# ─── Main ────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Agent Dispatch — Unified Agent Runner")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--agent", help="Drive one specific agent by ID")
    group.add_argument("--world", help="Drive all agents in a world")
    group.add_argument("--respond-to", help="Respond to a specific message ID")
    group.add_argument("--all", action="store_true", help="Drive a random batch")
    parser.add_argument("--max-agents", type=int, default=5, help="Max agents in --all mode")
    parser.add_argument("--no-push", action="store_true", help="Don't git commit/push")
    parser.add_argument("--dry-run", action="store_true", help="Preview only")
    parser.add_argument("--no-llm", action="store_true", help="Use dialogue lines only, no LLM")
    parser.add_argument("--poke", action="store_true", help="Agent was poked — force chat reaction")
    args = parser.parse_args()

    now = datetime.now(timezone.utc)
    timestamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")

    # Load everything
    registry = load_registry()
    npc_lookup = load_world_npcs()
    bounds = load_world_bounds()

    agents_data = load_json(STATE_DIR / "agents.json")
    actions_data = load_json(STATE_DIR / "actions.json")
    chat_data = load_json(STATE_DIR / "chat.json")

    agents = agents_data.get("agents", [])
    actions = actions_data.get("actions", [])
    messages = chat_data.get("messages", [])

    token = "" if args.no_llm else get_gh_token()
    brain = AgentBrain(token) if token else None

    if not registry:
        print("❌ No registry entries found. Run: python scripts/build_agent_registry.py")
        sys.exit(1)

    # Determine which agents to activate
    target_agents = []
    respond_to_msg = None

    if args.agent:
        if args.agent not in registry:
            print(f"❌ Agent {args.agent} not in registry")
            sys.exit(1)
        target_agents = [args.agent]

    elif args.world:
        target_agents = [
            aid for aid, reg in registry.items()
            if reg.get("world") == args.world
            and reg.get("controller", "system") == "system"
        ]
        if not target_agents:
            print(f"❌ No system agents registered in world '{args.world}'")
            sys.exit(1)

    elif args.respond_to:
        # Find the message and pick the best responder
        trigger = next((m for m in messages if m.get("id") == args.respond_to), None)
        if not trigger:
            print(f"❌ Message {args.respond_to} not found")
            sys.exit(1)

        respond_to_msg = trigger
        msg_world = trigger.get("world", "hub")
        author_id = trigger.get("author", {}).get("id", "")

        # Find agents in the same world (excluding the message author)
        candidates = [
            aid for aid, reg in registry.items()
            if reg.get("world") == msg_world
            and reg.get("controller", "system") == "system"
            and aid != author_id
            and reg.get("behavior", {}).get("respondToChat", True)
        ]

        # Also include agents currently in that world (they may have roamed)
        for agent in agents:
            aid = agent["id"]
            if (aid in registry
                    and agent.get("world") == msg_world
                    and aid != author_id
                    and aid not in candidates
                    and registry[aid].get("controller", "system") == "system"):
                candidates.append(aid)

        if not candidates:
            print(f"⚠️ No agents available to respond in {msg_world}")
            sys.exit(0)

        target_agents = [random.choice(candidates)]

    elif args.all:
        system_agents = [
            aid for aid, reg in registry.items()
            if reg.get("controller", "system") == "system"
        ]
        target_agents = random.sample(system_agents, min(args.max_agents, len(system_agents)))

    print(f"🤖 Agent Dispatch — {len(target_agents)} agent(s) at {timestamp}")
    if args.dry_run:
        print("   (dry run — no state changes)\n")
    print()

    # Execute actions
    results = []
    for aid in target_agents:
        result = execute_agent_action(
            aid, registry, npc_lookup, agents, actions, messages,
            bounds, timestamp, token, respond_to_msg=respond_to_msg,
            poked=args.poke, brain=brain,
        )
        results.append(result)

        if "error" in result:
            print(f"  ⚠️ {aid}: {result['error']}")
        else:
            print(f"  {result['summary']}")

    # Process autonomous poke reactions — targets respond in-character
    poke_targets = [
        r["poke_target"] for r in results
        if r.get("poke_target") and r["poke_target"] not in target_agents
    ]
    if poke_targets:
        print(f"\n  🔁 {len(poke_targets)} poke reaction(s):")
        for tid in poke_targets:
            reaction = execute_agent_action(
                tid, registry, npc_lookup, agents, actions, messages,
                bounds, timestamp, token, poked=True, brain=brain,
            )
            results.append(reaction)
            if "error" in reaction:
                print(f"    ⚠️ {tid}: {reaction['error']}")
            else:
                print(f"    {reaction['summary']}")

    total_actions = sum(r.get("actions", 0) for r in results)
    total_messages = sum(r.get("messages", 0) for r in results)

    if total_actions == 0 and total_messages == 0:
        print("\n💤 No state changes generated.")
        return

    if args.dry_run:
        print(f"\n🏁 Dry run: would generate {total_actions} actions + {total_messages} messages")
        return

    # Trim to last 100
    actions_data["actions"] = actions[-100:]
    chat_data["messages"] = messages[-100:]

    # Update metadata
    agents_data["_meta"] = {
        "lastUpdate": timestamp,
        "agentCount": len(agents),
    }
    actions_data["_meta"] = {
        "lastProcessedId": actions[-1]["id"] if actions else None,
        "lastUpdate": timestamp,
    }
    chat_data["_meta"] = {
        "lastUpdate": timestamp,
        "messageCount": len(chat_data["messages"]),
    }

    # Validate
    errors = validate_state(agents_data, actions_data, chat_data, bounds)
    if errors:
        print(f"\n❌ Validation failed — state NOT written:")
        for err in errors:
            print(f"  ✗ {err}")
        sys.exit(1)

    # Save
    save_json(STATE_DIR / "agents.json", agents_data)
    save_json(STATE_DIR / "actions.json", actions_data)
    save_json(STATE_DIR / "chat.json", chat_data)

    print(f"\n✅ Generated {total_actions} actions + {total_messages} messages")

    if not args.no_push:
        agent_names = [r.get("name", r["agent"]) for r in results if "error" not in r]
        commit_msg = f"[action] {', '.join(agent_names[:3])} — agent dispatch"
        subprocess.run(["git", "add", "-A"], cwd=BASE_DIR, capture_output=True)
        subprocess.run(["git", "commit", "-m", commit_msg], cwd=BASE_DIR, capture_output=True)
        result = subprocess.run(["git", "push"], cwd=BASE_DIR, capture_output=True, text=True)
        if result.returncode == 0:
            print(f"📦 Pushed: {commit_msg}")
        else:
            print(f"⚠️ Push failed: {result.stderr[:200]}")


if __name__ == "__main__":
    main()
