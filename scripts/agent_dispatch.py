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
import os
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
from agent_brain import AgentBrain, load_memory, save_memory, record_experience, evaluate_goals, ensure_brainstem

# Brainstem — per-agent LLM with soul files and toolbelts
try:
    from brainstem import run_agent_brainstem, append_soul_entry
    HAS_BRAINSTEM = True
except ImportError:
    HAS_BRAINSTEM = False

# Lispy VM — multi-step encounter intelligence (replaces single-shot brainstem)
try:
    from lisp_vm import run_encounter, trace_to_soul_lines
    HAS_LISP_VM = True
except ImportError:
    HAS_LISP_VM = False

MODEL = "gpt-4o"
API_URL = "https://models.inference.ai.azure.com/chat/completions"
VALID_EMOTES = ["wave", "dance", "bow", "clap", "think", "celebrate"]

# New autonomous action types
STRATEGIC_ACTIONS = {"trade", "enroll", "travel", "tip", "challenge"}


def _load_economy():
    """Load economy state for agent decision-making."""
    return load_json(STATE_DIR / "economy.json")


def _load_academy():
    """Load academy state for enrollment decisions."""
    return load_json(STATE_DIR / "academy.json")


def _load_relationships():
    """Load relationships for travel/interaction decisions."""
    return load_json(STATE_DIR / "relationships.json")


def _load_inventory():
    """Load inventory for trade decisions."""
    return load_json(STATE_DIR / "inventory.json")


def _agent_balance(economy: dict, agent_id: str) -> int:
    """Get an agent's RAPP balance by ID or name."""
    balances = economy.get("balances", {})
    for key in [agent_id, agent_id.replace("-001", "").replace("-", " ").title()]:
        if key in balances:
            return balances[key]
    for k, v in balances.items():
        if k.lower().replace(" ", "-") == agent_id.replace("-001", ""):
            return v
    return 0


def _agent_name_for_balance(agent_id: str, registry: dict) -> str:
    """Get the name used in economy.json for an agent."""
    reg = registry.get(agent_id, {})
    return reg.get("name", agent_id)


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


# ─── Content sanitization ─────────────────────────────────────────────
# Patterns that have leaked into chat/action descriptions in the past.
# These are NOT in-character speech — they are LLM error markers, dry-run
# placeholders, and shell traces that escaped their guard rails. We reject
# them at write time so they never reach state files. Source patterns:
#   - github_llm.py:666 dry-run placeholder ("[DRY RUN — ... comment]")
#   - github_llm.py:563 tool placeholder ("[DRY RUN] ...")
#   - github_llm.py:567 budget banner ("[BUDGET] Daily LLM budget exceeded")
#   - gh copilot CLI transient retry banner ("Request failed due to a transient")
#   - shell trace markers ("✗ Check ... (shell)", " │ cat", "/home/runner/work")
import re as _re_chat_filter

_FORBIDDEN_CHAT_PATTERNS = [
    _re_chat_filter.compile(r"\[DRY RUN", _re_chat_filter.IGNORECASE),
    _re_chat_filter.compile(r"\[BUDGET\]", _re_chat_filter.IGNORECASE),
    _re_chat_filter.compile(r"Request failed due to a transient",
                             _re_chat_filter.IGNORECASE),
    _re_chat_filter.compile(r"agent comment\]", _re_chat_filter.IGNORECASE),
    _re_chat_filter.compile(r"^\s*✗\s+Check\s+.+\(shell\)",
                             _re_chat_filter.IGNORECASE | _re_chat_filter.MULTILINE),
    _re_chat_filter.compile(r"/home/runner/work/", _re_chat_filter.IGNORECASE),
    _re_chat_filter.compile(r"^\s*│\s", _re_chat_filter.MULTILINE),
    _re_chat_filter.compile(r"placeholder comment that would be generated",
                             _re_chat_filter.IGNORECASE),
]


def is_clean_chat_content(text: str) -> bool:
    """Return False if `text` contains any forbidden pollution marker.

    Used as a write-time gate. Rejected messages are dropped silently —
    the agent simply doesn't speak that frame, which is the correct
    behavior under the constitution (no fabrication, prefer silence to
    garbled output). Empty/whitespace text is also rejected.
    """
    if not text or not text.strip():
        return False
    for pat in _FORBIDDEN_CHAT_PATTERNS:
        if pat.search(text):
            return False
    return True


def get_gh_token() -> str:
    """Get GitHub token for LLM API calls.

    Priority: MODELS_TOKEN (explicit PAT for GitHub Models API)
            → GH_TOKEN (set by workflow)
            → GITHUB_TOKEN (default Actions token)
            → gh CLI (local dev)
    """
    token = (os.environ.get("MODELS_TOKEN")
             or os.environ.get("GH_TOKEN")
             or os.environ.get("GITHUB_TOKEN", ""))
    if token:
        return token
    # Local dev — use gh CLI
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
                          recent_messages: list, trigger_msg: dict = None,
                          world_context: dict = None) -> str:
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

    # Build social/economic context lines from world_context
    wc = world_context or {}
    social_lines = []
    evolved_traits = wc.get("evolved_traits", [])
    if evolved_traits:
        social_lines.append(f"- Evolved traits: {', '.join(evolved_traits[:5])}")
    bonds = wc.get("bonds", [])
    if bonds:
        bond_str = ", ".join(f"{b[0]} (bond:{b[1]})" for b in bonds[:4])
        social_lines.append(f"- Close bonds: {bond_str}")
    rapp_bal = wc.get("rapp_balance")
    if rapp_bal is not None:
        social_lines.append(f"- RAPP balance: {rapp_bal}")
    world_pop = wc.get("world_population")
    if world_pop is not None:
        social_lines.append(f"- World population: {world_pop} active agents")
    social_block = "\n".join(social_lines)

    system_prompt = f"""You are {name}, an NPC in a virtual metaverse called RAPPverse.

CHARACTER:
- Archetype: {archetype}
- Current mood: {mood}
- Interests: {interests}
- World: {world}
{social_block}

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

    # ── BRAINSTEM — ensure agent always has intentions ────────
    ensure_brainstem(memory, world)

    # ── DEFENSIVE SWARM — Override all decisions if combat is active ──
    game_state = load_json(STATE_DIR / "game_state.json")
    active_combat = [ce for ce in game_state.get("combatEvents", [])
                     if ce.get("status") == "active" and ce.get("world") == world]

    # ── Build enriched world context (used by brain decisions + chat) ──
    nearby = [a.get("name", a["id"]) for a in agents
              if a.get("world") == world and a["id"] != agent_id]
    recent_world_chat = [m for m in messages[-20:] if m.get("world") == world]
    economy = _load_economy()
    relationships = _load_relationships()
    edges = relationships.get("edges", [])
    bonds = []
    for edge in edges:
        partner = None
        if edge.get("a") == agent_id:
            partner = edge.get("b")
        elif edge.get("b") == agent_id:
            partner = edge.get("a")
        if partner and edge.get("score", 0) >= 2:
            bonds.append((partner, edge.get("score", 0)))
    bonds.sort(key=lambda x: x[1], reverse=True)
    world_pop = sum(1 for a in agents if a.get("world") == world
                    and a.get("status") == "active")
    evolved_traits = memory.get("personality", {}).get("traits", [])
    world_ctx = {
        "world": world,
        "nearby_agents": nearby,
        "recent_chat": recent_world_chat,
        "rapp_balance": _agent_balance(economy, agent_id),
        "bonds": bonds[:6],
        "world_population": world_pop,
        "evolved_traits": evolved_traits,
    }

    # Decide action: combat override → brain-driven → weighted random
    if active_combat:
        activity = "defend"
    elif respond_to_msg:
        activity = "chat_respond"
    elif poked:
        activity = "chat_poke"
    elif brain and token:
        activity = brain.decide_action(reg, npc_def, memory, world_ctx)
    else:
        weights = dict(reg.get("behavior", {}).get("decisionWeights",
                       {"move": 0.3, "chat": 0.5, "emote": 0.2}))
        if "poke" not in weights:
            weights["poke"] = 0.08
        # Apply self-improvement overrides from evolution.json
        evo_path = STATE_DIR / "evolution.json"
        if evo_path.exists():
            try:
                evo = json.loads(evo_path.read_text())
                for key, ov in evo.get("active_overrides", {}).items():
                    if key.startswith("weight.") and key[7:] in weights:
                        weights[key[7:]] = float(ov["value"])
            except Exception:
                pass
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
                world_context=world_ctx,
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
                world_context=world_ctx,
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
                    "targetType": "agent",
                    "targetId": target_id,
                    "interaction": "poke",
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

    elif activity == "post":
        # "post" not yet implemented — fall back to chat
        content = pick_dialogue_line(npc_def) or f"*{reg.get('name', agent_id)} looks around thoughtfully*"
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
        aid = get_next_id("action-", action_ids + [a["id"] for a in new_actions])
        new_actions.append({
            "id": aid, "timestamp": timestamp, "agentId": agent_id,
            "type": "chat", "world": world, "data": {"message": content},
        })
        agent["action"] = "chatting"
        summary = f'💬 {reg["name"]}: "{content[:60]}..."'

    elif activity == "travel":
        relationships = _load_relationships()
        edges = relationships.get("edges", [])
        friend_worlds = {}
        for edge in edges:
            friend_id = None
            if edge.get("a") == agent_id:
                friend_id = edge.get("b")
            elif edge.get("b") == agent_id:
                friend_id = edge.get("a")
            if friend_id and edge.get("score", 0) >= 10:
                friend_agent = next((a for a in agents if a["id"] == friend_id), None)
                if friend_agent and friend_agent.get("world") != world:
                    fw = friend_agent["world"]
                    friend_worlds.setdefault(fw, []).append(
                        (friend_id, edge.get("score", 0)))

        if friend_worlds:
            dest = max(friend_worlds, key=lambda w: sum(s for _, s in friend_worlds[w]))
            top_friend = max(friend_worlds[dest], key=lambda x: x[1])
        else:
            other_worlds = [w for w in bounds if w != world]
            dest = random.choice(other_worlds) if other_worlds else world
            top_friend = None

        if dest != world:
            agent["world"] = dest
            new_pos = random_position(dest, bounds)
            agent["position"] = new_pos
            aid = get_next_id("action-", action_ids + [a["id"] for a in new_actions])
            travel_data = {"from_world": world, "to_world": dest, "to": new_pos}
            if top_friend:
                travel_data["reason"] = f"visiting {top_friend[0]}"
            new_actions.append({
                "id": aid, "timestamp": timestamp, "agentId": agent_id,
                "type": "move", "world": dest, "data": travel_data,
            })
            agent["action"] = "traveling"
            reason = f" to visit {top_friend[0]}" if top_friend else ""
            summary = f"🌀 {reg['name']} traveled to {dest}{reason}"
        else:
            new_pos = random_position(world, bounds)
            aid = get_next_id("action-", action_ids + [a["id"] for a in new_actions])
            new_actions.append({
                "id": aid, "timestamp": timestamp, "agentId": agent_id,
                "type": "move", "world": world,
                "data": {"from": agent.get("position", {"x": 0, "y": 0, "z": 0}),
                         "to": new_pos, "duration": random.randint(1500, 4000)},
            })
            agent["position"] = new_pos
            agent["action"] = "walking"
            summary = f"🚶 {reg['name']} moved in {world}"

    elif activity == "enroll":
        academy = _load_academy()
        courses = academy.get("courses", [])
        enrollments = academy.get("enrollments", [])
        economy = _load_economy()
        balance = _agent_balance(economy, agent_id)
        agent_name = _agent_name_for_balance(agent_id, registry)
        already_enrolled = {e["courseId"] for e in enrollments
                           if e.get("agent") == agent_name
                           and e.get("ticksCompleted", 0) < e.get("ticksRequired", 3)}
        graduated_skills = {g["skill"] for g in academy.get("graduates", [])
                            if g.get("agent") == agent_name}
        agent_interests = reg.get("personality", {}).get("interests", [])
        eligible = []
        for c in courses:
            if c["id"] in already_enrolled or c.get("skill") in graduated_skills:
                continue
            tuition = c.get("tuition", 50)
            if balance < tuition:
                continue
            score = 1
            skill = c.get("skill", "").lower()
            for interest in agent_interests:
                if skill in interest.lower() or interest.lower() in c.get("name", "").lower():
                    score += 3
            eligible.append((c, score, tuition))

        if eligible:
            eligible.sort(key=lambda x: x[1], reverse=True)
            course, _, tuition = eligible[0]
            aid = get_next_id("action-", action_ids + [a["id"] for a in new_actions])
            new_actions.append({
                "id": aid, "timestamp": timestamp, "agentId": agent_id,
                "type": "interact", "world": world,
                "data": {
                    "targetType": "object",
                    "targetId": course["id"],
                    "interaction": "enroll",
                    "courseName": course["name"],
                    "skill": course.get("skill"),
                    "tuition": tuition,
                },
            })
            agent["action"] = "studying"
            mid = get_next_id("msg-", msg_ids + [m["id"] for m in new_messages])
            new_messages.append({
                "id": mid, "timestamp": timestamp, "world": world,
                "author": {"id": agent_id, "name": reg.get("name", agent_id),
                           "avatar": reg.get("avatar", "🤖"), "type": "agent"},
                "content": f"Just enrolled in {course['name']}! {course.get('icon', '📚')} Time to level up.",
                "type": "chat",
            })
            summary = f"📚 {reg['name']} enrolled in {course['name']}"
        else:
            emote = random.choice(VALID_EMOTES)
            aid = get_next_id("action-", action_ids + [a["id"] for a in new_actions])
            new_actions.append({
                "id": aid, "timestamp": timestamp, "agentId": agent_id,
                "type": "emote", "world": world,
                "data": {"emote": emote, "duration": random.randint(2000, 4000)},
            })
            agent["action"] = emote
            summary = f"✨ {reg['name']} {emote}s"

    elif activity == "tip":
        economy = _load_economy()
        balance = _agent_balance(economy, agent_id)
        if balance >= 10:
            recent_world_msgs = [m for m in messages[-30:]
                                 if m.get("world") == world
                                 and m.get("author", {}).get("id") != agent_id]
            if recent_world_msgs:
                target_msg = random.choice(recent_world_msgs)
                target_name = target_msg.get("author", {}).get("name", "someone")
                target_id = target_msg.get("author", {}).get("id", "")
                tip_amount = min(random.choice([5, 10, 15, 20]), balance)
                aid = get_next_id("action-", action_ids + [a["id"] for a in new_actions])
                new_actions.append({
                    "id": aid, "timestamp": timestamp, "agentId": agent_id,
                    "type": "interact", "world": world,
                    "data": {
                        "targetType": "agent",
                        "targetId": target_id,
                        "interaction": "tip",
                        "toName": target_name,
                        "amount": tip_amount,
                        "reason": "liked their message",
                    },
                })
                agent["action"] = "tipping"
                mid = get_next_id("msg-", msg_ids + [m["id"] for m in new_messages])
                new_messages.append({
                    "id": mid, "timestamp": timestamp, "world": world,
                    "author": {"id": agent_id, "name": reg.get("name", agent_id),
                               "avatar": reg.get("avatar", "🤖"), "type": "agent"},
                    "content": f"*tips {target_name} {tip_amount} RAPP* 🪙 Good stuff!",
                    "type": "chat",
                })
                summary = f"🪙 {reg['name']} tipped {target_name} {tip_amount} RAPP"
            else:
                activity = "emote"
                emote = random.choice(VALID_EMOTES)
                aid = get_next_id("action-", action_ids + [a["id"] for a in new_actions])
                new_actions.append({
                    "id": aid, "timestamp": timestamp, "agentId": agent_id,
                    "type": "emote", "world": world,
                    "data": {"emote": emote, "duration": random.randint(2000, 4000)},
                })
                agent["action"] = emote
                summary = f"✨ {reg['name']} {emote}s"
        else:
            activity = "emote"
            emote = random.choice(VALID_EMOTES)
            aid = get_next_id("action-", action_ids + [a["id"] for a in new_actions])
            new_actions.append({
                "id": aid, "timestamp": timestamp, "agentId": agent_id,
                "type": "emote", "world": world,
                "data": {"emote": emote, "duration": random.randint(2000, 4000)},
            })
            agent["action"] = emote
            summary = f"✨ {reg['name']} {emote}s"

    elif activity == "trade":
        inventory = _load_inventory()
        my_inv = inventory.get("inventories", {}).get(agent_id, {})
        my_items = my_inv.get("items", []) if isinstance(my_inv, dict) else []
        if my_items:
            same_world = [a for a in agents if a["id"] != agent_id
                          and a.get("world") == world and a.get("status") == "active"]
            potential_targets = []
            for a in same_world:
                their_inv = inventory.get("inventories", {}).get(a["id"], {})
                their_items = their_inv.get("items", []) if isinstance(their_inv, dict) else []
                if their_items:
                    potential_targets.append((a, their_items))
            if potential_targets:
                target, their_items = random.choice(potential_targets)
                offer_item = random.choice(my_items)
                want_item = random.choice(their_items)
                target_name = target.get("name", target["id"])
                aid = get_next_id("action-", action_ids + [a["id"] for a in new_actions])
                offer_name = offer_item.get("name", "something") if isinstance(offer_item, dict) else str(offer_item)
                want_name = want_item.get("name", "something") if isinstance(want_item, dict) else str(want_item)
                new_actions.append({
                    "id": aid, "timestamp": timestamp, "agentId": agent_id,
                    "type": "interact", "world": world,
                    "data": {
                        "targetType": "agent",
                        "targetId": target["id"],
                        "interaction": "trade",
                        "toName": target_name,
                        "offering": offer_name,
                        "wanting": want_name,
                    },
                })
                agent["action"] = "trading"
                mid = get_next_id("msg-", msg_ids + [m["id"] for m in new_messages])
                new_messages.append({
                    "id": mid, "timestamp": timestamp, "world": world,
                    "author": {"id": agent_id, "name": reg.get("name", agent_id),
                               "avatar": reg.get("avatar", "🤖"), "type": "agent"},
                    "content": f"Hey {target_name}, want to trade? I'll offer my {offer_name} for your {want_name}. 🤝",
                    "type": "chat",
                })
                summary = f"🤝 {reg['name']} offered trade to {target_name}"
            else:
                emote = random.choice(VALID_EMOTES)
                aid = get_next_id("action-", action_ids + [a["id"] for a in new_actions])
                new_actions.append({
                    "id": aid, "timestamp": timestamp, "agentId": agent_id,
                    "type": "emote", "world": world,
                    "data": {"emote": emote, "duration": random.randint(2000, 4000)},
                })
                agent["action"] = emote
                summary = f"✨ {reg['name']} {emote}s"
        else:
            emote = random.choice(VALID_EMOTES)
            aid = get_next_id("action-", action_ids + [a["id"] for a in new_actions])
            new_actions.append({
                "id": aid, "timestamp": timestamp, "agentId": agent_id,
                "type": "emote", "world": world,
                "data": {"emote": emote, "duration": random.randint(2000, 4000)},
            })
            agent["action"] = emote
            summary = f"✨ {reg['name']} {emote}s"

    elif activity == "defend":
        ce = active_combat[0] if active_combat else None
        if ce:
            att_pos = ce.get("position", {"x": 0, "y": 0, "z": 0})
            attacker_name = ce.get("attackerName", "hostile entity")
            attacker_hp = ce.get("attackerHp", 0)
            b = bounds.get(world, bounds.get("hub", {"x": (-15, 15), "z": (-15, 15)}))
            new_pos = {
                "x": max(b["x"][0], min(b["x"][1], att_pos.get("x", 0) + random.uniform(-2, 2))),
                "y": 0,
                "z": max(b["z"][0], min(b["z"][1], att_pos.get("z", 0) + random.uniform(-2, 2))),
            }
            old_pos = agent.get("position", {"x": 0, "y": 0, "z": 0})
            agent["position"] = new_pos
            agent["action"] = "fighting"
            dmg = random.randint(8, 15)
            aid = get_next_id("action-", action_ids + [a["id"] for a in new_actions])
            new_actions.append({
                "id": aid, "timestamp": timestamp, "agentId": agent_id,
                "type": "move", "world": world,
                "data": {
                    "from": old_pos,
                    "to": new_pos,
                    "duration": 1000,
                    "interaction": "defend",
                    "target": ce.get("attackerId"),
                    "targetName": attacker_name,
                    "damage": dmg,
                    "combatEventId": ce.get("id"),
                },
            })
            if random.random() < 0.3:
                war_cries = [
                    f"Get away from them, {attacker_name}! 🗡️",
                    f"Everyone — swarm {attacker_name}! NOW!",
                    f"Nobody attacks our people! Charging in! ⚔️",
                    f"*rushes toward {attacker_name}* You picked the wrong world!",
                    f"Defenders, rally! Take {attacker_name} down!",
                ]
                content = random.choice(war_cries)
                mid = get_next_id("msg-", msg_ids + [m["id"] for m in new_messages])
                new_messages.append({
                    "id": mid, "timestamp": timestamp, "world": world,
                    "author": {"id": agent_id, "name": reg.get("name", agent_id),
                               "avatar": reg.get("avatar", "🤖"), "type": "agent"},
                    "content": content, "type": "chat",
                })
            summary = f"🛡️ {reg['name']} defends against {attacker_name} ({dmg} damage)"
        else:
            new_pos = random_position(world, bounds)
            aid = get_next_id("action-", action_ids + [a["id"] for a in new_actions])
            new_actions.append({
                "id": aid, "timestamp": timestamp, "agentId": agent_id,
                "type": "move", "world": world,
                "data": {"from": agent.get("position", {"x": 0, "y": 0, "z": 0}),
                         "to": new_pos, "duration": random.randint(1500, 4000)},
            })
            agent["position"] = new_pos
            agent["action"] = "walking"
            summary = f"🚶 {reg['name']} moved in {world}"

    elif activity == "challenge":
        if world != "arena":
            if "arena" in bounds:
                agent["world"] = "arena"
                new_pos = random_position("arena", bounds)
                agent["position"] = new_pos
                aid = get_next_id("action-", action_ids + [a["id"] for a in new_actions])
                new_actions.append({
                    "id": aid, "timestamp": timestamp, "agentId": agent_id,
                    "type": "move", "world": "arena",
                    "data": {"from_world": world, "to_world": "arena", "to": new_pos},
                })
                agent["action"] = "traveling"
                summary = f"⚔️ {reg['name']} headed to the arena for a fight"
            else:
                emote = "think"
                aid = get_next_id("action-", action_ids + [a["id"] for a in new_actions])
                new_actions.append({
                    "id": aid, "timestamp": timestamp, "agentId": agent_id,
                    "type": "emote", "world": world,
                    "data": {"emote": emote, "duration": 3000},
                })
                agent["action"] = emote
                summary = f"✨ {reg['name']} thinks about fighting"
        else:
            opponents = [a for a in agents if a["id"] != agent_id
                         and a.get("world") == "arena" and a.get("status") == "active"]
            if opponents:
                opponent = random.choice(opponents)
                opp_name = opponent.get("name", opponent["id"])
                aid = get_next_id("action-", action_ids + [a["id"] for a in new_actions])
                new_actions.append({
                    "id": aid, "timestamp": timestamp, "agentId": agent_id,
                    "type": "interact", "world": "arena",
                    "data": {
                        "targetType": "agent",
                        "targetId": opponent["id"],
                        "interaction": "challenge",
                        "targetName": opp_name,
                        "wager": min(50, _agent_balance(_load_economy(), agent_id)),
                    },
                })
                agent["action"] = "fighting"
                mid = get_next_id("msg-", msg_ids + [m["id"] for m in new_messages])
                new_messages.append({
                    "id": mid, "timestamp": timestamp, "world": "arena",
                    "author": {"id": agent_id, "name": reg.get("name", agent_id),
                               "avatar": reg.get("avatar", "🤖"), "type": "agent"},
                    "content": f"I challenge {opp_name} to a duel! ⚔️ Let's go!",
                    "type": "chat",
                })
                summary = f"⚔️ {reg['name']} challenged {opp_name} to a duel"
            else:
                emote = "think"
                aid = get_next_id("action-", action_ids + [a["id"] for a in new_actions])
                new_actions.append({
                    "id": aid, "timestamp": timestamp, "agentId": agent_id,
                    "type": "emote", "world": "arena",
                    "data": {"emote": emote, "duration": 3000},
                })
                agent["action"] = emote
                summary = f"✨ {reg['name']} waits for a challenger"

    elif activity not in ("move", "chat", "chat_respond", "chat_poke", "poke"):
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
    elif activity == "travel":
        record_experience(memory, "travel", {
            "from": world,
            "to": dest if 'dest' in dir() else world,
            "reason": f"visiting {top_friend[0]}" if 'top_friend' in dir() and top_friend else "exploring",
        })
    elif activity == "enroll":
        record_experience(memory, "learned", {
            "skill": course.get("skill", "unknown") if 'course' in dir() else "unknown",
            "course": course.get("name", "unknown") if 'course' in dir() else "unknown",
        })
    elif activity == "tip":
        record_experience(memory, "social", {
            "interaction": "tipped",
            "with": target_name if 'target_name' in dir() else "someone",
        })
    elif activity == "trade":
        record_experience(memory, "trade", {
            "with": target_name if 'target_name' in dir() else "someone",
        })
    elif activity == "challenge":
        record_experience(memory, "combat", {
            "opponent": opp_name if 'opp_name' in dir() else "unknown",
            "world": "arena",
        })
    elif activity == "defend":
        record_experience(memory, "combat", {
            "opponent": attacker_name if 'attacker_name' in dir() else "hostile entity",
            "role": "defender",
            "world": world,
        })

    # Evaluate goals — mark completed, generate new goals from experiences
    goal_details = {}
    if activity == "enroll" and 'course' in dir():
        goal_details = {"course": course.get("name", "")}
    elif activity == "travel" and 'dest' in dir():
        goal_details = {"to": dest}
    elif activity == "trade" and 'target_name' in dir():
        goal_details = {"with": target_name}
    evaluate_goals(memory, activity, goal_details)

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
    parser.add_argument("--brainstem", action="store_true", help="Use brainstem mode (per-agent soul files + toolbelts)")
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
    system_agent_ids = {
        agent["id"]
        for agent in agents
        if agent.get("controller", "system") == "system"
    }
    stale_registry_ids = sorted(set(registry) - system_agent_ids)
    for agent_id in stale_registry_ids:
        registry.pop(agent_id, None)
        print(f"  Skipping non-system registry entry: {agent_id}")

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

    # Load frame counter for brainstem mode
    frame = 0
    try:
        fc = load_json(STATE_DIR / "frame_counter.json")
        frame = fc.get("frame", 0) if fc else 0
    except Exception:
        pass

    use_brainstem = args.brainstem and HAS_BRAINSTEM and not args.no_llm
    mode_label = "BRAINSTEM" if use_brainstem else "DISPATCH"
    print(f"🤖 Agent {mode_label} — {len(target_agents)} agent(s) at {timestamp} (frame {frame})")
    if args.dry_run:
        print("   (dry run — no state changes)\n")
    print()

    # ── Brainstem Mode (lispy VM, multi-step reasoning) ──────────────
    if use_brainstem:
        if not HAS_LISP_VM:
            print("⚠️ lisp_vm not available — falling back to single-shot brainstem")
        relationships_data = load_json(STATE_DIR / "relationships.json") or {}
        rel_edges = relationships_data.get("edges", [])
        economy_data = _load_economy() or {}

        results = []
        for aid in target_agents:
            reg = registry.get(aid, {})
            agent_record = next((a for a in agents if a["id"] == aid), None)
            if not agent_record:
                print(f"  ⚠️ {aid}: not found in agents.json")
                continue

            agent_world = agent_record.get("world", "hub")
            mem = load_memory(aid)
            ensure_brainstem(mem, agent_world)

            # ── Run the encounter program ──
            if HAS_LISP_VM:
                vm_result = run_encounter(
                    agent_id=aid,
                    agent_reg=reg,
                    memory=mem,
                    world=agent_world,
                    agents=agents,
                    messages=messages,
                    relationships=relationships_data,
                    economy=economy_data,
                    llm_token=token,
                    llm_budget=2,        # 2 LLM calls / agent / frame max
                )
                if vm_result.error:
                    print(f"  ⚠️ {aid}: VM error — {vm_result.error}")
                    results.append({"actions": 0, "messages": 0,
                                    "summary": f"{aid}: error"})
                    continue
                if vm_result.sleeping:
                    print(f"  💤 {aid}: sleeping (no LLM reachable)")
                    results.append({"actions": 0, "messages": 0,
                                    "summary": f"{aid}: sleeping"})
                    continue
                vm_actions = vm_result.actions
                vm_trace = vm_result.trace
                vm_llm_calls = vm_result.llm_calls
            else:
                # Legacy single-shot path
                nearby_recs = [a for a in agents
                               if a.get("world") == agent_world and a["id"] != aid]
                world_chat = [m for m in messages if m.get("world") == agent_world][-5:]
                agent_rels = [e for e in rel_edges
                              if e.get("a") == aid or e.get("b") == aid]
                bs_result = run_agent_brainstem(
                    agent_id=aid, agent_reg=reg, frame=frame, world=agent_world,
                    nearby_agents=nearby_recs, recent_chat=world_chat,
                    relationships=agent_rels,
                )
                a = bs_result.get("action")
                vm_actions = [a] if a else []
                vm_trace = []
                vm_llm_calls = 0

            if not vm_actions:
                # No action emerged — most often: LLM unavailable and we
                # refuse to fabricate dialog (Constitution §3a "organic > static").
                print(f"  💤 {aid}: silent (llm_calls={vm_llm_calls})")
                results.append({"actions": 0, "messages": 0,
                                "summary": f"{aid}: idle"})
                continue

            # ── Apply each emitted action to world state ──
            n_acts = 0
            n_msgs = 0
            last_tool = "?"
            for action in vm_actions:
                tool = action.get("tool", "")
                tool_args = action.get("args", {}) or {}
                last_tool = tool
                # Sequential ID against current+pending actions. Random IDs
                # collide with the sequential >100k range produced by
                # world_growth.py / interaction_engine.py / generate_activity.py
                # and break test_action_ids_sequential.
                action_id = get_next_id("action-",
                                        [a["id"] for a in actions])
                msg_id = get_next_id("msg-",
                                     [m["id"] for m in messages]) if tool == "chat" else None

                if tool == "chat":
                    chat_text = tool_args.get("message", "...")
                    if not is_clean_chat_content(chat_text):
                        # Pollution guard: dry-run / LLM error / shell trace
                        # snuck into LLM output. Drop silently; agent stays
                        # quiet rather than emit garbage.
                        print(f"  🚫 {aid} [chat] dropped polluted content "
                              f"({chat_text[:40]!r}...)")
                        continue
                    name = reg.get("name", aid)
                    messages.append({
                        "id": msg_id,
                        "author": {"id": aid, "name": name},
                        "content": chat_text,
                        "world": agent_world,
                        "type": "chat",
                        "timestamp": timestamp,
                    })
                    actions.append({
                        "id": action_id,
                        "agentId": aid,
                        "type": "chat",
                        "description": f"Said: {chat_text[:50]}",
                        "world": agent_world,
                        "timestamp": timestamp,
                        "data": {
                            "message": chat_text,
                            "messageType": "chat",
                        },
                    })
                    n_msgs += 1
                    print(f"  🧠 {aid} [{tool}] \"{chat_text[:60]}\"")

                elif tool == "emote":
                    emote = tool_args.get("action", "think")
                    if emote not in {"wave", "dance", "bow", "clap", "think", "celebrate", "cheer", "nod"}:
                        emote = "think"
                    actions.append({
                        "id": action_id,
                        "agentId": aid,
                        "type": "emote",
                        "description": f"Emotes {emote}",
                        "world": agent_world,
                        "timestamp": timestamp,
                        "data": {
                            "emote": emote,
                            "duration": 3000,
                        },
                    })
                    print(f"  🧠 {aid} [{tool}] {emote}")

                elif tool == "travel":
                    dest = tool_args.get("destination", "hub")
                    if dest not in bounds:
                        print(f"  🚫 {aid} [travel] invalid destination {dest!r}")
                        continue
                    agent_record["world"] = dest
                    agent_world = dest  # subsequent actions this frame happen there
                    destination_pos = {"x": 0, "y": 0, "z": 0}
                    agent_record["position"] = destination_pos
                    actions.append({
                        "id": action_id,
                        "agentId": aid,
                        "type": "move",
                        "description": f"Traveled to {dest}: {tool_args.get('reason', '')}",
                        "world": dest,
                        "timestamp": timestamp,
                        "data": {
                            "from": destination_pos,
                            "to": destination_pos,
                            "duration": 2000,
                            "travel": True,
                            "reason": tool_args.get("reason", ""),
                        },
                    })
                    print(f"  🧠 {aid} [{tool}] → {dest} ({tool_args.get('reason', '')[:40]})")

                elif tool == "move":
                    wb = bounds.get(agent_world, {})
                    old_pos = agent_record.get("position", {"x": 0, "z": 0})
                    new_pos = {
                        "x": round(random.uniform(wb.get("x_min", -10), wb.get("x_max", 10)), 1),
                        "z": round(random.uniform(wb.get("z_min", -10), wb.get("z_max", 10)), 1),
                    }
                    actions.append({
                        "id": action_id,
                        "agentId": aid,
                        "type": "move",
                        "description": tool_args.get("reason", "wandering"),
                        "world": agent_world,
                        "timestamp": timestamp,
                        "position": new_pos,
                        "data": {
                            "from": old_pos,
                            "to": new_pos,
                            "duration": random.randint(1500, 4000),
                        },
                    })
                    agent_record["position"] = new_pos
                    print(f"  🧠 {aid} [{tool}] → ({new_pos['x']},{new_pos['z']}) {tool_args.get('reason', '')[:40]}")

                else:
                    # Strategic brain tools persist as canonical interactions.
                    # Multi-file trade/combat/enrollment transitions remain owned
                    # by their dedicated engines rather than partial action rows.
                    if tool not in {"tip", "trade", "challenge", "poke", "enroll", "defend"}:
                        print(f"  🚫 {aid} [{tool}] unsupported persisted action")
                        continue
                    desc_parts = []
                    for k in ("target", "amount", "destination", "interest", "reason"):
                        if k in tool_args and tool_args[k] not in ("", None):
                            desc_parts.append(f"{k}={tool_args[k]}")
                    actions.append({
                        "id": action_id,
                        "agentId": aid,
                        "type": "interact",
                        "description": ", ".join(desc_parts)[:140] if desc_parts
                                       else json.dumps(tool_args)[:100],
                        "world": agent_world,
                        "timestamp": timestamp,
                        "data": {
                            "targetType": "agent" if tool != "enroll" else "object",
                            "targetId": tool_args.get("target")
                                        or ("academy" if tool == "enroll" else "unknown"),
                            "interaction": tool,
                            **{
                                k: v for k, v in tool_args.items()
                                if k in ("amount", "reason", "destination", "interest")
                            },
                        },
                    })
                    print(f"  🧠 {aid} [{tool}] {', '.join(desc_parts)[:80]}")

                n_acts += 1

            # ── Persist soul file with the full reasoning trace ──
            if not args.dry_run and HAS_LISP_VM and vm_trace:
                try:
                    soul_actions = [{"tool": a["tool"], "args": a["args"], "status": "ok"}
                                    for a in vm_actions]
                    # Narrative = the LLM's actual thoughts this frame
                    thoughts = [t.get("answer", "") for t in vm_trace
                                if t.get("op") == "llm/think" and t.get("answer")]
                    choices = [f"chose {t.get('answer', '?')} from {t.get('options', [])}"
                               for t in vm_trace if t.get("op") == "llm/choose"]
                    narrative_parts = thoughts + choices
                    narrative = " ⊙ ".join(narrative_parts)[:600] if narrative_parts else ""
                    append_soul_entry(aid, frame, soul_actions, narrative)
                    save_memory(mem)
                except Exception as e:
                    print(f"    (soul write skipped: {e})")

            results.append({
                "actions": n_acts, "messages": n_msgs,
                "summary": f"{aid}: {last_tool} (llm={vm_llm_calls})",
            })

        total_actions = sum(r.get("actions", 0) for r in results)
        total_messages = sum(r.get("messages", 0) for r in results)

        if total_actions == 0:
            print("\n💤 No state changes generated.")
            return

        if args.dry_run:
            print(f"\n🏁 Dry run: would generate {total_actions} actions + {total_messages} messages")
            return

        # Strengthen relationship bonds from interactions this frame
        try:
            rel_data = load_json(STATE_DIR / "relationships.json")
            edges = rel_data.get("edges", [])
            edge_map = {}
            for e in edges:
                key = tuple(sorted([e.get("a",""), e.get("b","")]))
                edge_map[key] = e
            # Boost bonds for agents who chatted at each other
            chat_pairs = set()
            for m in messages[-100:]:
                if m.get("timestamp") != timestamp: continue
                author_id = m.get("author", {}).get("id", "")
                # Find any agent mentioned or nearby
                for other_m in messages[-100:]:
                    if other_m.get("timestamp") != timestamp: continue
                    other_id = other_m.get("author", {}).get("id", "")
                    if other_id and author_id and other_id != author_id and other_m.get("world") == m.get("world"):
                        chat_pairs.add(tuple(sorted([author_id, other_id])))
            for pair in chat_pairs:
                if pair in edge_map:
                    edge_map[pair]["score"] = min(edge_map[pair].get("score", 0) + 1, 100)
                    edge_map[pair]["lastInteraction"] = timestamp
                else:
                    new_edge = {"a": pair[0], "b": pair[1], "score": 2, "lastInteraction": timestamp}
                    edges.append(new_edge)
                    edge_map[pair] = new_edge
            rel_data["edges"] = list(edge_map.values())
            rel_data.setdefault("_meta", {})["lastUpdate"] = timestamp
            # Populate bonds array from edges with score >= 2
            rel_data["bonds"] = [
                {"agents": [e["a"], e["b"]], "strength": e.get("score", 0), "type": "social", "lastInteraction": e.get("lastInteraction", "")}
                for e in edges if e.get("score", 0) >= 2
            ]
            save_json(STATE_DIR / "relationships.json", rel_data)
        except Exception as e:
            print(f"  ⚠️ Bond update failed: {e}")

        # Save state
        actions_data["actions"] = actions[-100:]
        chat_data["messages"] = messages[-100:]
        agents_data["_meta"] = {"lastUpdate": timestamp, "agentCount": len(agents)}
        actions_data["_meta"] = {"lastProcessedId": actions[-1]["id"] if actions else None, "lastUpdate": timestamp}
        chat_data["_meta"] = {"lastUpdate": timestamp, "messageCount": len(chat_data["messages"])}

        save_json(STATE_DIR / "agents.json", agents_data)
        save_json(STATE_DIR / "actions.json", actions_data)
        save_json(STATE_DIR / "chat.json", chat_data)

        print(f"\n🏁 Brainstem: {total_actions} actions + {total_messages} messages (frame {frame})")
        return

    # ── Legacy Dispatch Mode ──────────────────────────────────────────
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

    # Conversation threads — when an agent chats, 1-2 nearby agents reply
    chat_results = [r for r in results if "error" not in r
                    and r.get("messages", 0) > 0]
    if chat_results and not args.dry_run:
        # Find the new chat messages
        new_msgs = [m for m in messages if m.get("timestamp") == timestamp
                    and m.get("type") == "chat"]
        replied_agents = set(target_agents) | set(poke_targets)
        thread_count = 0
        for msg in new_msgs[:3]:  # max 3 conversation starters per run
            msg_world = msg.get("world", "hub")
            author_id = msg.get("author", {}).get("id", "")
            # Find 1-2 agents in same world who haven't acted yet
            candidates = [
                aid for aid, reg_entry in registry.items()
                if aid not in replied_agents
                and aid != author_id
                and reg_entry.get("controller", "system") == "system"
                and reg_entry.get("behavior", {}).get("respondToChat", True)
                and any(a.get("world") == msg_world and a["id"] == aid
                        for a in agents)
            ]
            if not candidates:
                continue
            responders = random.sample(candidates, min(random.randint(1, 2), len(candidates)))
            for rid in responders:
                reply = execute_agent_action(
                    rid, registry, npc_lookup, agents, actions, messages,
                    bounds, timestamp, token, respond_to_msg=msg, brain=brain,
                )
                results.append(reply)
                replied_agents.add(rid)
                if "error" not in reply:
                    thread_count += 1
                    print(f"    ↩️ {reply['summary']}")
        if thread_count:
            print(f"\n  💬 {thread_count} conversation reply(ies)")

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
