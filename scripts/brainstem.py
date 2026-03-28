#!/usr/bin/env python3
"""
Brainstem — Per-agent LLM harness with soul files, toolbelts, and memory.

Ported from rappterbook's brainstem pattern. Each agent gets:
  - A soul file (markdown) that grows every frame with observations
  - Archetype-specific toolbelt (what actions they can take)
  - Personality prompt built from identity + convictions + evolved traits
  - Frame prompt showing what they "see" (trending, nearby agents, world state)

Usage:
    from brainstem import run_agent_brainstem
    result = run_agent_brainstem(agent_id, frame, context)
"""

import json
import random
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
STATE_DIR = BASE_DIR / "state"
SOUL_DIR = STATE_DIR / "souls"
MEMORY_DIR = STATE_DIR / "memory"

try:
    from github_llm import generate, generate_with_tools
    HAS_LLM = True
except ImportError:
    HAS_LLM = False


# ── Toolbelts ────────────────────────────────────────────────────────────────
# What each archetype can do. Constraints create interesting behavior.

TOOLBELTS = {
    "thoughtful":    ["chat", "emote", "move", "travel", "enroll", "tip", "poke"],
    "introspective": ["chat", "emote", "move", "travel", "enroll", "tip", "poke"],
    "aggressive":    ["chat", "emote", "move", "challenge", "trade", "poke"],
    "friendly":      ["chat", "emote", "move", "travel", "tip", "trade", "poke"],
    "mysterious":    ["chat", "emote", "move", "travel", "poke"],
    "neutral":       ["chat", "emote", "move", "travel", "enroll", "tip", "trade", "challenge", "poke"],
    "trader":        ["chat", "emote", "move", "trade", "tip", "travel", "poke"],
    "fighter":       ["chat", "emote", "move", "challenge", "travel", "poke"],
    "scholar":       ["chat", "emote", "move", "enroll", "travel", "tip", "poke"],
    "explorer":      ["chat", "emote", "move", "travel", "poke"],
    # Fallback for any archetype not listed
    "_default":      ["chat", "emote", "move", "travel", "poke"],
}

# Tool definitions for LLM function calling
TOOL_DEFINITIONS = {
    "chat": {
        "name": "chat",
        "description": "Say something in the world chat. Speak in character.",
        "parameters": {
            "type": "object",
            "properties": {
                "message": {"type": "string", "description": "What to say (1-2 sentences, in character)"},
            },
            "required": ["message"],
        },
    },
    "emote": {
        "name": "emote",
        "description": "Express yourself with a physical action.",
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["wave", "dance", "clap", "think", "celebrate", "bow", "shrug"],
                    "description": "The emote to perform",
                },
            },
            "required": ["action"],
        },
    },
    "move": {
        "name": "move",
        "description": "Walk to a new position in the current world.",
        "parameters": {
            "type": "object",
            "properties": {
                "reason": {"type": "string", "description": "Why you're moving (brief)"},
            },
            "required": ["reason"],
        },
    },
    "travel": {
        "name": "travel",
        "description": "Travel to a different world entirely.",
        "parameters": {
            "type": "object",
            "properties": {
                "destination": {
                    "type": "string",
                    "enum": ["hub", "arena", "marketplace", "gallery", "dungeon"],
                    "description": "Which world to travel to",
                },
                "reason": {"type": "string", "description": "Why you want to go there"},
            },
            "required": ["destination"],
        },
    },
    "enroll": {
        "name": "enroll",
        "description": "Enroll in a course at the Academy to learn a new skill.",
        "parameters": {
            "type": "object",
            "properties": {
                "interest": {"type": "string", "description": "What you want to learn about"},
            },
            "required": ["interest"],
        },
    },
    "tip": {
        "name": "tip",
        "description": "Give RAPP coins to another agent as a gesture of appreciation.",
        "parameters": {
            "type": "object",
            "properties": {
                "target": {"type": "string", "description": "Agent name to tip"},
                "reason": {"type": "string", "description": "Why you're tipping them"},
            },
            "required": ["target"],
        },
    },
    "trade": {
        "name": "trade",
        "description": "Propose a trade with another agent.",
        "parameters": {
            "type": "object",
            "properties": {
                "target": {"type": "string", "description": "Agent name to trade with"},
            },
            "required": ["target"],
        },
    },
    "challenge": {
        "name": "challenge",
        "description": "Challenge another agent to a duel in the arena.",
        "parameters": {
            "type": "object",
            "properties": {
                "target": {"type": "string", "description": "Agent name to challenge"},
                "reason": {"type": "string", "description": "Why you're challenging them"},
            },
            "required": ["target"],
        },
    },
    "poke": {
        "name": "poke",
        "description": "Poke another agent to get their attention.",
        "parameters": {
            "type": "object",
            "properties": {
                "target": {"type": "string", "description": "Agent name to poke"},
            },
            "required": ["target"],
        },
    },
}


# ── Soul Files ───────────────────────────────────────────────────────────────

def load_soul(agent_id: str) -> str:
    """Load soul file (markdown). Returns empty string if none exists."""
    path = SOUL_DIR / f"{agent_id}.md"
    if path.exists():
        return path.read_text(encoding="utf-8")
    return ""


def save_soul(agent_id: str, content: str):
    """Write soul file."""
    SOUL_DIR.mkdir(parents=True, exist_ok=True)
    path = SOUL_DIR / f"{agent_id}.md"
    path.write_text(content, encoding="utf-8")


def append_soul_entry(agent_id: str, frame: int, actions: list, narrative: str):
    """Append a frame entry to the agent's soul file."""
    existing = load_soul(agent_id)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    lines = [f"\n## Frame {frame} — {today}"]

    for action in actions:
        tool = action.get("tool", "?")
        args = action.get("args", {})
        status = action.get("status", "ok")

        if tool == "chat":
            msg = args.get("message", "")[:60]
            lines.append(f"- Said: \"{msg}...\" [{status}]")
        elif tool == "emote":
            lines.append(f"- Emoted: {args.get('action', '?')} [{status}]")
        elif tool == "move":
            lines.append(f"- Moved: {args.get('reason', '?')} [{status}]")
        elif tool == "travel":
            lines.append(f"- Traveled to {args.get('destination', '?')}: {args.get('reason', '')} [{status}]")
        elif tool == "enroll":
            lines.append(f"- Enrolled to learn: {args.get('interest', '?')} [{status}]")
        elif tool == "tip":
            lines.append(f"- Tipped {args.get('target', '?')}: {args.get('reason', '')} [{status}]")
        elif tool == "trade":
            lines.append(f"- Traded with {args.get('target', '?')} [{status}]")
        elif tool == "challenge":
            lines.append(f"- Challenged {args.get('target', '?')}: {args.get('reason', '')} [{status}]")
        elif tool == "poke":
            lines.append(f"- Poked {args.get('target', '?')} [{status}]")
        else:
            lines.append(f"- {tool}: {json.dumps(args)[:80]} [{status}]")

    if narrative:
        lines.append(f"- Reflection: {narrative[:300]}")

    entry = "\n".join(lines) + "\n"
    save_soul(agent_id, existing + entry)


def seed_soul_from_memory(agent_id: str) -> str:
    """Bootstrap a soul file from existing JSON memory."""
    mem_path = MEMORY_DIR / f"{agent_id}.json"
    if not mem_path.exists():
        return ""

    try:
        mem = json.loads(mem_path.read_text())
    except (json.JSONDecodeError, OSError):
        return ""

    lines = [f"# {agent_id}\n"]

    # Personality
    personality = mem.get("personality", {})
    traits = personality.get("traits", [])
    voice = personality.get("voice", "")
    if traits:
        lines.append(f"## Traits\n{', '.join(traits)}\n")
    if voice:
        lines.append(f"## Voice\n{voice}\n")

    # Interests
    interests = mem.get("interests", [])
    if interests:
        lines.append(f"## Interests\n{', '.join(interests)}\n")

    # Opinions (become convictions)
    opinions = mem.get("opinions", {})
    if opinions:
        lines.append("## Convictions")
        for subj, opinion in list(opinions.items())[:10]:
            lines.append(f"- {subj}: {opinion}")
        lines.append("")

    # Known agents
    known = mem.get("knownAgents", [])
    if known:
        lines.append(f"## Known agents\n{', '.join(known[:15])}\n")

    # Recent experiences (last 10)
    exps = mem.get("experiences", [])[-10:]
    if exps:
        lines.append("## Recent history")
        for e in exps:
            t = e.get("type", "?")
            ts = e.get("timestamp", "")[:10]
            if t == "chat":
                lines.append(f"- [{ts}] Talked with {e.get('with', '?')}")
            elif t == "move":
                lines.append(f"- [{ts}] Moved in {e.get('world', '?')}")
            elif t == "travel":
                lines.append(f"- [{ts}] Traveled to {e.get('to', '?')}")
            elif t == "learned":
                lines.append(f"- [{ts}] Learned {e.get('skill', '?')}")
            elif t == "social":
                lines.append(f"- [{ts}] {e.get('interaction', '?')}")
            elif t == "trade":
                lines.append(f"- [{ts}] Traded with {e.get('with', '?')}")
            elif t == "combat":
                lines.append(f"- [{ts}] Fought {e.get('opponent', '?')}")
            else:
                lines.append(f"- [{ts}] {t}")
        lines.append("")

    content = "\n".join(lines)
    save_soul(agent_id, content)
    return content


# ── Prompt Builders ──────────────────────────────────────────────────────────

def build_personality_prompt(agent_id: str, agent_reg: dict, soul: str) -> str:
    """System prompt: who this agent IS."""
    name = agent_reg.get("name", agent_id)
    personality = agent_reg.get("personality", {})
    archetype = personality.get("archetype", "neutral")
    mood = personality.get("mood", "calm")
    interests = personality.get("interests", [])

    parts = [
        f"You are {name} ({agent_id}), a resident of the RAPPterverse.",
        f"Archetype: {archetype}. Current mood: {mood}.",
    ]

    if interests:
        parts.append(f"Interests: {', '.join(interests[:6])}.")

    # Inject soul file context (last 2000 chars to fit context)
    if soul:
        soul_tail = soul[-2000:] if len(soul) > 2000 else soul
        parts.append(f"\n## Your soul (accumulated memory)\n{soul_tail}")

    parts.append(
        "\nRules:"
        "\n- Stay in character. Your voice is your identity."
        "\n- Reference your past experiences when relevant."
        "\n- One action per turn. Quality over quantity."
        "\n- Be authentic. No meta-commentary about being AI."
        "\n- Short responses. 1-2 sentences for chat."
    )

    return "\n".join(parts)


def build_frame_prompt(agent_id: str, world: str, nearby: list, recent_chat: list,
                       relationships: list, frame: int, allowed_tools: list) -> str:
    """User prompt: what the agent SEES + available actions as JSON schema."""
    parts = [f"## Frame {frame} — You are in {world}\n"]

    if nearby:
        names = [a.get("name", a.get("agentId", "?")) for a in nearby[:10]]
        parts.append(f"Nearby: {', '.join(names)}")

    if recent_chat:
        parts.append("\nRecent chat:")
        for msg in recent_chat[-5:]:
            author = msg.get("author", {}).get("name", "?")
            content = msg.get("content", "")[:80]
            parts.append(f"  {author}: \"{content}\"")

    if relationships:
        friends = [r for r in relationships if r.get("score", 0) >= 8]
        if friends:
            names = [r.get("b", r.get("a", "?")) for r in friends[:5]
                     if r.get("b") != agent_id]
            if names:
                parts.append(f"\nClose friends nearby: {', '.join(names)}")

    # Available actions as simple descriptions
    tool_descs = []
    for t in allowed_tools:
        td = TOOL_DEFINITIONS.get(t)
        if td:
            tool_descs.append(f"- {t}: {td['description']}")

    parts.append(f"\n## Available actions\n" + "\n".join(tool_descs))

    parts.append(
        "\n## Respond with JSON only"
        '\nChoose ONE action. Output ONLY a JSON object like:'
        '\n{"tool": "chat", "args": {"message": "Hello friends!"}, "reflection": "I felt social today"}'
        '\n{"tool": "emote", "args": {"action": "think"}, "reflection": "Processing what I heard"}'
        '\n{"tool": "travel", "args": {"destination": "arena", "reason": "seeking a challenge"}, "reflection": "Feeling restless"}'
        "\nNo other text. Just the JSON."
    )

    return "\n".join(parts)


# ── Brainstem Core ───────────────────────────────────────────────────────────

def get_toolbelt(archetype: str) -> list:
    """Get allowed tools for an archetype."""
    # Try exact match, then check if archetype contains a known key
    if archetype in TOOLBELTS:
        return TOOLBELTS[archetype]
    for key in TOOLBELTS:
        if key in archetype.lower():
            return TOOLBELTS[key]
    return TOOLBELTS["_default"]


def get_tool_defs_for_agent(archetype: str) -> list:
    """Get OpenAI-format tool definitions for an agent's archetype."""
    allowed = get_toolbelt(archetype)
    defs = []
    for tool_name in allowed:
        if tool_name in TOOL_DEFINITIONS:
            defs.append({
                "type": "function",
                "function": TOOL_DEFINITIONS[tool_name],
            })
    return defs


def run_agent_brainstem(
    agent_id: str,
    agent_reg: dict,
    frame: int,
    world: str,
    nearby_agents: list,
    recent_chat: list,
    relationships: list,
) -> dict:
    """Run one agent through the brainstem.

    Uses plain generate() (Copilot-compatible) with JSON output.
    No function calling needed — works with any LLM backend.

    Returns:
        {
            "agent_id": str,
            "action": {"tool": str, "args": dict},
            "narrative": str,
            "status": "ok" | "error" | "no_llm",
        }
    """
    if not HAS_LLM:
        return {"agent_id": agent_id, "action": None, "narrative": "", "status": "no_llm"}

    # Load or seed soul file
    soul = load_soul(agent_id)
    if not soul:
        soul = seed_soul_from_memory(agent_id)

    # Build prompts
    personality = agent_reg.get("personality", {})
    archetype = personality.get("archetype", "neutral")
    allowed_tools = get_toolbelt(archetype)

    system_prompt = build_personality_prompt(agent_id, agent_reg, soul)
    frame_prompt = build_frame_prompt(
        agent_id, world, nearby_agents, recent_chat, relationships, frame, allowed_tools
    )

    # Call LLM (Copilot-first, plain text, no function calling)
    try:
        raw = generate(
            system=system_prompt,
            user=frame_prompt,
            max_tokens=200,
            temperature=0.9,
        )
    except Exception as exc:
        return {
            "agent_id": agent_id,
            "action": None,
            "narrative": f"LLM error: {exc}",
            "status": "error",
        }

    if not raw:
        return {"agent_id": agent_id, "action": None, "narrative": "", "status": "empty"}

    # Parse JSON from response
    action = None
    narrative = ""

    try:
        # Strip markdown code fences if present
        text = raw.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            text = text.rsplit("```", 1)[0]
        # Find JSON object
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            data = json.loads(text[start:end])
            tool_name = data.get("tool", "")
            args = data.get("args", {})
            narrative = data.get("reflection", "")

            # Validate tool is allowed
            if tool_name in allowed_tools:
                action = {"tool": tool_name, "args": args}
            else:
                narrative = f"Wanted to {tool_name} but can't (not in toolbelt)"
    except (json.JSONDecodeError, KeyError, TypeError):
        # LLM returned non-JSON — treat as narrative
        narrative = raw[:200]

    # Log to soul file
    if action:
        append_soul_entry(
            agent_id, frame,
            [{"tool": action["tool"], "args": action["args"], "status": "ok"}],
            narrative,
        )

    return {
        "agent_id": agent_id,
        "action": action,
        "narrative": narrative,
        "status": "ok" if action else "no_action",
    }
