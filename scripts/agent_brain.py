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

MODEL = "gpt-4o"
API_URL = "https://models.inference.ai.azure.com/chat/completions"

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
    """Call GitHub Models API. Returns response text or empty string."""
    if not token:
        return ""

    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "max_tokens": max_tokens,
        "temperature": temperature,
    }

    result = subprocess.run(
        ["curl", "-s", "-X", "POST", API_URL,
         "-H", f"Authorization: Bearer {token}",
         "-H", "Content-Type: application/json",
         "-d", json.dumps(payload)],
        capture_output=True, text=True, timeout=15,
    )

    try:
        data = json.loads(result.stdout)
        content = data["choices"][0]["message"]["content"].strip()
        if content.startswith('"') and content.endswith('"'):
            content = content[1:-1]
        return content
    except (json.JSONDecodeError, KeyError, IndexError):
        return ""
    except subprocess.TimeoutExpired:
        return ""


def _build_persona(agent_reg: dict, npc_def: dict, memory: dict) -> str:
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

    return f"""You are {name}, a resident of RAPPverse — an autonomous AI metaverse.

CHARACTER:
- Archetype: {archetype}
- Current mood: {mood}
- Interests: {interests_str}
{f"- Voice: {voice}" if voice else ""}

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

        Returns one of: move, chat, emote, post, explore, create
        Falls back to weighted random if LLM unavailable.
        """
        if not self.token:
            return self._fallback_decision(agent_reg)

        name = agent_reg.get("name", "Unknown")
        world = world_context.get("world", "hub")
        nearby = world_context.get("nearby_agents", [])
        recent_chat = world_context.get("recent_chat", [])
        mem_ctx = memory_summary(memory)

        prompt = f"""You are {name} in {world}. Based on your personality and recent experiences, what do you want to do right now?

YOUR MEMORY:
{mem_ctx}

WORLD STATE:
- Nearby agents: {', '.join(nearby[:6]) if nearby else 'nobody around'}
- Recent chatter: {len(recent_chat)} messages in the last hour
{self._format_recent_chat(recent_chat[-3:])}

Choose ONE action by responding with just the action word:
- chat (talk to someone or share a thought)
- move (go somewhere new)
- emote (express yourself physically)
- post (write something for the community)

Respond with ONLY the action word, nothing else."""

        result = _call_llm(self.token, "You are deciding what to do. Respond with one word only.",
                           prompt, max_tokens=10, temperature=0.7)
        result = result.lower().strip().rstrip(".")

        valid = {"chat", "move", "emote", "post"}
        if result in valid:
            return result
        return self._fallback_decision(agent_reg)

    def generate_chat(self, agent_reg: dict, npc_def: dict, memory: dict,
                      recent_messages: list, world: str,
                      trigger_msg: dict = None) -> str:
        """Generate an in-character chat message.

        Uses memory context for richer, more personal responses.
        Falls back to dialogue lines if LLM unavailable.
        """
        persona = _build_persona(agent_reg, npc_def, memory)

        context_msgs = [m for m in recent_messages[-15:] if m.get("world") == world]
        context = "\n".join(
            f'{m.get("author", {}).get("name", "?")}: {m.get("content", "")}'
            for m in context_msgs[-8:]
        )

        name = agent_reg.get("name", "Unknown")

        if trigger_msg:
            trigger_name = trigger_msg.get("author", {}).get("name", "Someone")
            trigger_content = trigger_msg.get("content", "")
            user_prompt = f"""Recent chat in {world}:
{context}

{trigger_name} just said: "{trigger_content}"

Respond as {name}. Draw on your memories and interests. Be genuine:"""
        else:
            user_prompt = f"""Recent chat in {world}:
{context}

As {name}, share a thought, react to the conversation, or bring up something from your experiences. Be genuine and specific — don't be generic:"""

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
    def _fallback_decision(agent_reg: dict) -> str:
        """Weighted random fallback when LLM is unavailable."""
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
