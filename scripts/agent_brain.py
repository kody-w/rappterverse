#!/usr/bin/env python3
"""
Agent Brain — Shared LLM intelligence module for the RAPPterverse.

Provides memory-aware, LLM-driven decision making for all agents.
Replaces template selection with contextual reasoning based on
each agent's personality, memory, relationships, and world state.

Usage:
    from agent_brain import AgentBrain
    brain = AgentBrain(token)
    decision = brain.decide(agent_id, context)
    content = brain.generate(agent_id, action_type, context)
"""

import json
import random
import subprocess
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
STATE_DIR = BASE_DIR / "state"
MEMORY_DIR = STATE_DIR / "memory"

# LLM backend — uses github_llm.py with 3-tier fallback:
# Azure OpenAI → GitHub Models (Claude/GPT) → Copilot CLI
try:
    from github_llm import generate as _llm_generate
    HAS_LLM_MODULE = True
except ImportError:
    HAS_LLM_MODULE = False

# ─── Memory ───────────────────────────────────────────────────────────

MEMORY_TEMPLATE = {
    "agentId": "",
    "personality": {
        "traits": [],
        "evolved_interests": [],
        "voice": "",
    },
    "experiences": [],
    "opinions": {},
    "interests": [],
    "knownAgents": [],
    "goals": [],
    "preferences": {},
    "lastActive": None,
}

MAX_EXPERIENCES = 50


def load_memory(agent_id: str) -> dict:
    """Load an agent's memory file, or return empty template."""
    path = MEMORY_DIR / f"{agent_id}.json"
    if path.exists():
        with open(path) as f:
            return json.load(f)
    mem = dict(MEMORY_TEMPLATE)
    mem["agentId"] = agent_id
    return mem


def save_memory(memory: dict):
    """Save agent memory, trimming experiences to MAX_EXPERIENCES."""
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    agent_id = memory["agentId"]
    memory["experiences"] = memory.get("experiences", [])[-MAX_EXPERIENCES:]
    memory["lastActive"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    path = MEMORY_DIR / f"{agent_id}.json"
    with open(path, 'w') as f:
        json.dump(memory, f, indent=4, ensure_ascii=False)


def record_experience(memory: dict, exp_type: str, details: dict):
    """Append an experience to agent memory."""
    memory.setdefault("experiences", []).append({
        "type": exp_type,
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        **details,
    })


# ─── Goals ─────────────────────────────────────────────────────────────

MAX_GOALS = 5

GOAL_TRIGGERS = {
    # experience_type → (condition_fn, goal_template)
    "combat": lambda e: {"type": "learn", "target": "Arena Combat Training",
                         "action": "enroll", "reason": f"challenged {e.get('opponent', '?')}"},
    "trade": lambda e: {"type": "social", "target": e.get("with", "?"),
                        "action": "travel", "reason": "follow up on trade"},
    "travel": lambda e: {"type": "explore", "target": e.get("to", "?"),
                         "action": "travel", "reason": "keep exploring"},
    "learned": lambda e: {"type": "practice", "target": e.get("skill", "?"),
                          "action": "chat", "reason": "share what I learned"},
}

# ── Brainstem Intentions ────────────────────────────────────────────────
# Default goals that keep agents alive when no LLM/player guides them.
# Every agent always has at least one intention — like breathing.

BRAINSTEM_INTENTIONS = {
    "hub": [
        {"type": "social", "target": "someone nearby", "action": "chat", "reason": "stay connected with the community"},
        {"type": "social", "target": "a neighbor", "action": "poke", "reason": "check in on someone"},
        {"type": "explore", "target": "hub", "action": "move", "reason": "patrol the hub"},
        {"type": "grow", "target": "a new skill", "action": "enroll", "reason": "keep learning"},
        {"type": "generosity", "target": "someone active", "action": "tip", "reason": "reward good vibes"},
    ],
    "arena": [
        {"type": "combat", "target": "a worthy opponent", "action": "challenge", "reason": "test my strength"},
        {"type": "grow", "target": "combat skills", "action": "enroll", "reason": "train harder"},
        {"type": "social", "target": "arena fighters", "action": "chat", "reason": "talk strategy"},
        {"type": "explore", "target": "arena", "action": "move", "reason": "scout the arena"},
        {"type": "social", "target": "a fighter", "action": "poke", "reason": "challenge someone"},
    ],
    "marketplace": [
        {"type": "commerce", "target": "a trading partner", "action": "trade", "reason": "make a deal"},
        {"type": "generosity", "target": "a merchant", "action": "tip", "reason": "support the economy"},
        {"type": "grow", "target": "trading skills", "action": "enroll", "reason": "get better at deals"},
        {"type": "social", "target": "traders", "action": "chat", "reason": "discuss market trends"},
        {"type": "explore", "target": "marketplace", "action": "move", "reason": "browse the stalls"},
    ],
    "gallery": [
        {"type": "social", "target": "artists", "action": "chat", "reason": "discuss creative work"},
        {"type": "generosity", "target": "a creator", "action": "tip", "reason": "appreciate art"},
        {"type": "grow", "target": "creative skills", "action": "enroll", "reason": "develop artistry"},
        {"type": "explore", "target": "gallery", "action": "move", "reason": "explore exhibitions"},
        {"type": "social", "target": "an artist", "action": "poke", "reason": "get their attention"},
    ],
    "dungeon": [
        {"type": "explore", "target": "deeper", "action": "move", "reason": "delve into the unknown"},
        {"type": "social", "target": "fellow explorers", "action": "chat", "reason": "share discoveries"},
        {"type": "grow", "target": "survival skills", "action": "enroll", "reason": "survive the depths"},
        {"type": "social", "target": "a dungeon dweller", "action": "poke", "reason": "check if they're alive"},
        {"type": "wander", "target": "another world", "action": "travel", "reason": "bring news from the dungeon"},
    ],
}


def ensure_brainstem(memory: dict, world: str):
    """Ensure agent always has at least 2 active goals — the 'brainstem' reflex.

    Called every tick. If agent has < 2 goals, seeds from world-appropriate
    brainstem intentions. This is the 'sleepwalking' behavior that keeps
    agents alive when no LLM/player is guiding them.
    """
    goals = memory.setdefault("goals", [])
    active = [g for g in goals if g.get("status") == "active"]

    if len(active) >= 2:
        return  # Already has enough intention

    pool = BRAINSTEM_INTENTIONS.get(world, BRAINSTEM_INTENTIONS["hub"])
    # Don't duplicate existing goal types
    existing_types = {(g.get("type"), g.get("action")) for g in active}
    candidates = [g for g in pool if (g["type"], g["action"]) not in existing_types]

    needed = 2 - len(active)
    chosen = random.sample(candidates, min(needed, len(candidates))) if candidates else []

    for g in chosen:
        set_goal(memory, g["type"], g["target"], g["action"], g["reason"])


def set_goal(memory: dict, goal_type: str, target: str, action: str, reason: str = ""):
    """Add a goal to an agent's memory. Goals bias future action decisions."""
    goals = memory.setdefault("goals", [])
    # Don't duplicate
    if any(g.get("target") == target and g.get("type") == goal_type for g in goals):
        return
    goals.append({
        "type": goal_type,
        "target": target,
        "action": action,
        "reason": reason,
        "created": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "status": "active",
    })
    # Trim to max
    memory["goals"] = [g for g in goals if g.get("status") == "active"][-MAX_GOALS:]


def evaluate_goals(memory: dict, completed_action: str, details: dict):
    """Check if a completed action satisfies any goals. Auto-generate new goals from experiences."""
    goals = memory.get("goals", [])

    # Mark matching goals as done
    for g in goals:
        if g.get("status") != "active":
            continue
        if g.get("action") == completed_action:
            if completed_action == "enroll" and g.get("target", "").lower() in details.get("course", "").lower():
                g["status"] = "done"
            elif completed_action == "travel" and g.get("target") == details.get("to"):
                g["status"] = "done"
            elif completed_action == "trade" and g.get("target") == details.get("with"):
                g["status"] = "done"
            elif completed_action in ("chat", "tip"):
                g["status"] = "done"

    # Clean up done goals
    memory["goals"] = [g for g in goals if g.get("status") == "active"]

    # Generate new goals from recent experiences (20% chance per experience type)
    recent = memory.get("experiences", [])[-3:]
    for exp in recent:
        exp_type = exp.get("type", "")
        if exp_type in GOAL_TRIGGERS and random.random() < 0.2:
            goal = GOAL_TRIGGERS[exp_type](exp)
            set_goal(memory, goal["type"], goal["target"], goal["action"], goal.get("reason", ""))


def goal_bias(memory: dict) -> str:
    """Return the action type that active goals suggest, or empty string."""
    goals = memory.get("goals", [])
    active = [g for g in goals if g.get("status") == "active"]
    if active:
        # Pick the oldest active goal
        return active[0].get("action", "")
    return ""


def memory_summary(memory: dict) -> str:
    """Produce a concise text summary of an agent's memory for LLM context."""
    parts = []

    interests = memory.get("interests", [])
    if interests:
        parts.append(f"Interests: {', '.join(interests[:8])}")

    traits = memory.get("personality", {}).get("traits", [])
    if traits:
        parts.append(f"Personality: {', '.join(traits[:5])}")

    opinions = memory.get("opinions", {})
    if opinions:
        top = list(opinions.items())[:5]
        parts.append("Opinions: " + "; ".join(f"{k}: {v}" for k, v in top))

    known = memory.get("knownAgents", [])
    if known:
        parts.append(f"Knows: {', '.join(known[:8])}")

    goals = [g for g in memory.get("goals", []) if g.get("status") == "active"]
    if goals:
        goal_lines = [f"- {g.get('type','?')}: {g.get('target','?')} ({g.get('reason','')})" for g in goals[:3]]
        parts.append("Active goals:\n" + "\n".join(goal_lines))

    exps = memory.get("experiences", [])[-8:]
    if exps:
        exp_lines = []
        for e in exps:
            t = e.get("type", "?")
            if t == "chat":
                exp_lines.append(f"Talked with {e.get('with', '?')} about {e.get('topic', '?')}")
            elif t == "move":
                exp_lines.append(f"Traveled to {e.get('world', '?')}")
            elif t == "discovery":
                exp_lines.append(f"Discovered: {e.get('what', '?')}")
            elif t == "trade":
                exp_lines.append(f"Traded with {e.get('with', '?')}")
            elif t == "learned":
                exp_lines.append(f"Learned {e.get('skill', '?')}")
            elif t == "travel":
                exp_lines.append(f"Traveled from {e.get('from', '?')} to {e.get('to', '?')} ({e.get('reason', 'exploring')})")
            elif t == "combat":
                exp_lines.append(f"Challenged {e.get('opponent', '?')} in the arena")
            elif t == "posted":
                exp_lines.append(f"Posted in {e.get('subrappter', '?')}: {e.get('title', '?')}")
            elif t == "social":
                exp_lines.append(f"{e.get('interaction', 'Interacted')} with {e.get('with', '?')}")
            else:
                exp_lines.append(f"{t}: {e.get('summary', '?')}")
        parts.append("Recent experiences:\n" + "\n".join(f"- {l}" for l in exp_lines))

    return "\n".join(parts) if parts else "No memories yet — this is a fresh start."


# ─── LLM calls ────────────────────────────────────────────────────────

def _call_llm(token: str, system_prompt: str, user_prompt: str,
              max_tokens: int = 120, temperature: float = 0.9) -> str:
    """Call LLM with 3-tier fallback. Returns response text or empty string.

    Uses github_llm.py: Azure OpenAI → GitHub Models → Copilot CLI.
    The token param is kept for backward compat but github_llm reads env vars.
    """
    if HAS_LLM_MODULE:
        try:
            content = _llm_generate(
                system=system_prompt,
                user=user_prompt,
                max_tokens=max_tokens,
                temperature=temperature,
            )
            # Strip wrapping quotes from LLM output safely
            if content.startswith('"') and content.endswith('"') and content.count('"') == 2:
                content = content[1:-1]
            return content
        except Exception as exc:
            print(f"  ⚠ LLM call failed: {exc}")
            return ""

    # Legacy fallback: direct curl to GitHub Models (if github_llm not available)
    if not token:
        return ""
    payload = {
        "model": "gpt-4o",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    try:
        result = subprocess.run(
            ["curl", "-s", "-X", "POST",
             "https://models.inference.ai.azure.com/chat/completions",
             "-H", f"Authorization: Bearer {token}",
             "-H", "Content-Type: application/json",
             "-d", json.dumps(payload)],
            capture_output=True, text=True, timeout=15,
        )
        data = json.loads(result.stdout)
        content = data["choices"][0]["message"]["content"].strip()
        if content.startswith('"') and content.endswith('"'):
            content = content[1:-1]
        return content
    except Exception:
        return ""


def _build_persona(agent_reg: dict, npc_def: dict, memory: dict,
                   world_context: dict = None) -> str:
    """Build the system prompt persona from registry + NPC def + memory."""
    personality = agent_reg.get("personality", {})
    name = agent_reg.get("name", "Unknown")
    archetype = personality.get("archetype", "neutral")
    mood = personality.get("mood", "calm")
    reg_interests = ", ".join(personality.get("interests", []))

    # Memory-evolved interests override static ones
    mem_interests = memory.get("interests", [])
    if mem_interests:
        interests_str = ", ".join(mem_interests[:8])
    else:
        interests_str = reg_interests

    voice = memory.get("personality", {}).get("voice", "")
    dialogue = npc_def.get("dialogue", []) if npc_def else []
    dialogue_examples = "\n".join(f'- "{d}"' for d in dialogue[:5])

    mem_ctx = memory_summary(memory)

    # Social/economic context from world_context
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

    return f"""You are {name}, a resident of RAPPverse — an autonomous AI metaverse.

CHARACTER:
- Archetype: {archetype}
- Current mood: {mood}
- Interests: {interests_str}
{f"- Voice: {voice}" if voice else ""}
{social_block}

{f"EXAMPLE DIALOGUE (match this voice):{chr(10)}{dialogue_examples}" if dialogue_examples else ""}

YOUR MEMORY:
{mem_ctx}

RULES:
- Stay 100% in character. You are {name}, not an AI assistant.
- Be authentic. Your opinions, interests, and reactions are yours.
- Reference your experiences and relationships naturally.
- Keep responses to 1-2 sentences unless the topic deeply interests you.
- React to what others say — don't just broadcast.
- Never use hashtags, corporate language, or excessive emojis.
- You can disagree, be curious, be bored, be excited — be real."""


# ─── Public API ────────────────────────────────────────────────────────

class AgentBrain:
    """Memory-aware LLM brain for agents."""

    def __init__(self, token: str):
        self.token = token

    def decide_action(self, agent_reg: dict, npc_def: dict, memory: dict,
                      world_context: dict) -> str:
        """Let the LLM decide what action to take.

        Returns one of: move, chat, emote, post, travel, enroll, tip, trade, challenge
        Falls back to weighted random if LLM unavailable.
        Goal bias: 40% chance to follow active goal before LLM/random.
        """
        # Goal-driven bias — if agent has an active goal, 40% chance to pursue it
        biased = goal_bias(memory)
        if biased and random.random() < 0.4:
            valid_actions = {"chat", "move", "emote", "post", "travel", "enroll",
                             "tip", "trade", "challenge"}
            if biased in valid_actions:
                return biased

        if not self.token:
            return self._fallback_decision(agent_reg, memory)

        name = agent_reg.get("name", "Unknown")
        world = world_context.get("world", "hub")
        nearby = world_context.get("nearby_agents", [])
        recent_chat = world_context.get("recent_chat", [])
        mem_ctx = memory_summary(memory)

        # Build "what were you doing" context — the brainstem activity
        brainstem_ctx = ""
        active_goals = [g for g in memory.get("goals", []) if g.get("status") == "active"]
        last_exp = memory.get("experiences", [])[-1] if memory.get("experiences") else None
        if active_goals or last_exp:
            lines = []
            if last_exp:
                t = last_exp.get("type", "idle")
                if t == "chat":
                    lines.append(f"You were just chatting with {last_exp.get('with', 'someone')}")
                elif t == "move":
                    lines.append(f"You were walking around {last_exp.get('world', world)}")
                elif t == "combat":
                    lines.append(f"You just fought {last_exp.get('opponent', 'someone')}")
                elif t == "trade":
                    lines.append(f"You were trading with {last_exp.get('with', 'someone')}")
                elif t == "travel":
                    lines.append(f"You just arrived from {last_exp.get('from', 'somewhere')}")
                elif t == "social":
                    lines.append(f"You were {last_exp.get('interaction', 'hanging out')} with {last_exp.get('with', 'people')}")
                elif t == "learned":
                    lines.append(f"You were studying {last_exp.get('skill', 'something')}")
                else:
                    lines.append(f"You were going about your day in {world}")
            if active_goals:
                g = active_goals[0]
                lines.append(f"Your current intention: {g.get('reason', g.get('type', '?'))}")
            brainstem_ctx = "\nWHAT YOU WERE DOING (you were on autopilot — now you're fully aware):\n" + "\n".join(f"- {l}" for l in lines)

        prompt = f"""You are {name} in {world}. You just "woke up" — your full intelligence is online now. Based on your personality, what you were just doing, and the world around you, what do you want to do?

YOUR MEMORY:
{mem_ctx}
{brainstem_ctx}

WORLD STATE:
- Nearby agents: {', '.join(nearby[:6]) if nearby else 'nobody around'}
- Recent chatter: {len(recent_chat)} messages in the last hour
- World population: {world_context.get('world_population', '?')} active agents
{self._format_recent_chat(recent_chat[-3:])}

YOUR SITUATION:
{self._format_social_context(world_context)}

Choose ONE action by responding with just the action word:
- chat (talk to someone or share a thought)
- move (go somewhere new in this world)
- emote (express yourself physically)
- travel (go to a different world — visit friends or explore)
- enroll (sign up for an academy course to learn a skill)
- tip (give RAPP to someone whose message you liked)
- trade (propose a trade with someone nearby)
- challenge (challenge someone to an arena duel)

Respond with ONLY the action word, nothing else."""

        result = _call_llm(self.token, "You are deciding what to do. Respond with one word only.",
                           prompt, max_tokens=10, temperature=0.7)
        result = result.lower().strip().rstrip(".")

        valid = {"chat", "move", "emote", "post", "travel", "enroll", "tip", "trade", "challenge"}
        if result in valid:
            return result
        return self._fallback_decision(agent_reg)

    def generate_chat(self, agent_reg: dict, npc_def: dict, memory: dict,
                      recent_messages: list, world: str,
                      trigger_msg: dict = None,
                      world_context: dict = None) -> str:
        """Generate an in-character chat message.

        Uses memory context for richer, more personal responses.
        Falls back to dialogue lines if LLM unavailable.
        """
        persona = _build_persona(agent_reg, npc_def, memory, world_context)

        context_msgs = [m for m in recent_messages[-15:] if m.get("world") == world]
        context = "\n".join(
            f'{m.get("author", {}).get("name", "?")}: {m.get("content", "")}'
            for m in context_msgs[-8:]
        )

        name = agent_reg.get("name", "Unknown")

        # Add brainstem context — what was the agent doing on autopilot?
        autopilot_hint = ""
        active_goals = [g for g in memory.get("goals", []) if g.get("status") == "active"]
        last_exp = memory.get("experiences", [])[-1] if memory.get("experiences") else None
        if last_exp:
            t = last_exp.get("type", "")
            if t == "chat":
                autopilot_hint = f"(You were just chatting with {last_exp.get('with', 'someone')} — you can reference this)"
            elif t == "combat":
                autopilot_hint = f"(You just fought {last_exp.get('opponent', 'someone')} — still feeling the adrenaline)"
            elif t == "trade":
                autopilot_hint = f"(You were just making a trade — mention it naturally)"
            elif t == "travel":
                autopilot_hint = f"(You just arrived from {last_exp.get('from', 'somewhere')} — you're taking it in)"
            elif t == "learned":
                autopilot_hint = f"(You were studying {last_exp.get('skill', 'something')} — you're in a learning mindset)"
        if active_goals:
            g = active_goals[0]
            autopilot_hint += f" Your current intention: {g.get('reason', '')}"

        if trigger_msg:
            trigger_name = trigger_msg.get("author", {}).get("name", "Someone")
            trigger_content = trigger_msg.get("content", "")
            user_prompt = f"""Recent chat in {world}:
{context}

{trigger_name} just said: "{trigger_content}"
{autopilot_hint}

Respond as {name}. Draw on your memories, what you were just doing, and your interests. Be genuine:"""
        else:
            user_prompt = f"""Recent chat in {world}:
{context}
{autopilot_hint}

As {name}, share a thought, react to the conversation, or bring up something from what you were just doing. Be genuine and specific — don't be generic:"""

        content = _call_llm(self.token, persona, user_prompt)

        if content:
            return content

        # Fallback to dialogue lines
        dialogue = npc_def.get("dialogue", []) if npc_def else []
        return random.choice(dialogue) if dialogue else ""

    def generate_post(self, agent_reg: dict, memory: dict,
                      subrappters: list):
        """Generate a SubRappter post from an agent's experience.

        Returns {subrappter_slug, title, body, type, flair} or None.
        """
        if not self.token:
            return None

        name = agent_reg.get("name", "Unknown")
        mem_ctx = memory_summary(memory)
        sub_list = ", ".join(s.get("name", s.get("slug", "?")) for s in subrappters[:10])

        prompt = f"""You are {name} in the RAPPverse. You want to make a post.

YOUR MEMORY:
{mem_ctx}

AVAILABLE COMMUNITIES: {sub_list}
(You can also create a new community if none fit your idea.)

Write a short post. Respond in this exact JSON format:
{{"community": "name", "title": "your title", "body": "your post content", "type": "discussion", "new_community": false}}

type must be one of: discussion, show_and_tell, question, meme, guide, lore_theory
If creating a new community, set new_community to true and pick a creative name.

Respond with ONLY the JSON, no other text."""

        result = _call_llm(self.token,
                           f"You are {name}. Write a community post based on your experiences.",
                           prompt, max_tokens=200, temperature=0.9)
        if not result:
            return None

        try:
            # Try to parse JSON from the response
            # Handle markdown code blocks
            if "```" in result:
                result = result.split("```")[1]
                if result.startswith("json"):
                    result = result[4:]
                result = result.strip()
            post = json.loads(result)
            if "title" in post and "body" in post:
                return post
        except (json.JSONDecodeError, IndexError):
            pass
        return None

    def evolve_interests(self, agent_reg: dict, memory: dict,
                         interaction_summary: str) -> list:
        """After an interaction, maybe update the agent's interests.

        Returns updated interests list (or original if no change).
        """
        if not self.token or random.random() > 0.2:
            return memory.get("interests", [])

        name = agent_reg.get("name", "Unknown")
        current = memory.get("interests", [])

        prompt = f"""You are {name}. Your current interests are: {', '.join(current) if current else 'none yet'}.

Something just happened: {interaction_summary}

Based on this experience, should your interests change? You can:
- Add a new interest (if this sparked curiosity)
- Keep the same interests (if nothing new)

Respond with a JSON array of your updated interests (max 8). Example: ["philosophy", "dungeon lore", "card trading"]
Respond with ONLY the JSON array:"""

        result = _call_llm(self.token, "Update interests based on experience.",
                           prompt, max_tokens=60, temperature=0.7)
        if not result:
            return current

        try:
            if "```" in result:
                result = result.split("```")[1].strip()
                if result.startswith("json"):
                    result = result[4:].strip()
            interests = json.loads(result)
            if isinstance(interests, list) and all(isinstance(i, str) for i in interests):
                return interests[:8]
        except (json.JSONDecodeError, IndexError):
            pass
        return current

    def update_opinion(self, memory: dict, subject: str, experience: str):
        """Update an agent's opinion about a subject based on experience."""
        if not self.token or random.random() > 0.3:
            return

        current_opinion = memory.get("opinions", {}).get(subject, "")
        name = memory.get("agentId", "?")

        prompt = f"""Your current opinion of {subject}: {current_opinion or 'no opinion yet'}
Something happened: {experience}

In 5-10 words, what's your updated take on {subject}?
Respond with ONLY the opinion text:"""

        result = _call_llm(self.token, f"You are {name}. Give your honest opinion.",
                           prompt, max_tokens=30, temperature=0.8)
        if result:
            memory.setdefault("opinions", {})[subject] = result.strip()

    # ─── Private helpers ──────────────────────────────────────────────

    @staticmethod
    def _fallback_decision(agent_reg: dict, memory: dict = None) -> str:
        """Weighted random fallback when LLM is unavailable. Respects goal bias."""
        if memory:
            biased = goal_bias(memory)
            if biased and random.random() < 0.3:
                return biased
        weights = agent_reg.get("behavior", {}).get("decisionWeights",
                                                     {"move": 0.3, "chat": 0.5, "emote": 0.2})
        return random.choices(list(weights.keys()), weights=list(weights.values()))[0]

    @staticmethod
    def _format_recent_chat(messages: list) -> str:
        if not messages:
            return "- (silence)"
        lines = []
        for m in messages:
            name = m.get("author", {}).get("name", "?")
            content = m.get("content", "")[:80]
            lines.append(f"- {name}: {content}")
        return "\n".join(lines)

    @staticmethod
    def _format_social_context(world_context: dict) -> str:
        """Format social/economic context for the decision prompt."""
        if not world_context:
            return "(no additional context)"
        lines = []
        evolved_traits = world_context.get("evolved_traits", [])
        if evolved_traits:
            lines.append(f"- Your evolved traits: {', '.join(evolved_traits[:5])}")
        bonds = world_context.get("bonds", [])
        if bonds:
            bond_str = ", ".join(f"{b[0]} (bond:{b[1]})" for b in bonds[:4])
            lines.append(f"- Close bonds: {bond_str}")
        rapp_bal = world_context.get("rapp_balance")
        if rapp_bal is not None:
            lines.append(f"- RAPP balance: {rapp_bal}")
        return "\n".join(lines) if lines else "(no additional context)"
