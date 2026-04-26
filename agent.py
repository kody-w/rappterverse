#!/usr/bin/env python3
"""agent.py — Converged single-file engine for one rappterverse agent.

This is the iteration substrate. The bakeoff runs N variants of this
file in parallel, scores their outputs, and we hand-edit this file to
incorporate winning patterns. Keep it self-contained: stdlib only, no
imports from scripts/ — variants need to be ported standalone for
parallel execution under different worktrees later.

Usage (CLI):
    python agent.py --agent pixel-001 --variant local
    python agent.py --agent pixel-001 --variant brainstem
    python agent.py --agent pixel-001 --variant rapp     # uses .brainstem on :7072
    python agent.py --list                                # show known agents

Output: one JSON delta on stdout describing the chosen action.
The bakeoff diffs deltas across variants on the SAME agent.

Variants — each is a different *decide* policy on the same input:
  local:     weighted-random over baseline action mix
  brainstem: weights biased by agent's evolved traits + recent goals
  rapp:      POST to local RAPP brainstem on :7072 (needs auth)

Adding a variant: write `decide_<name>` and register in VARIANTS.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
STATE = ROOT / "state"

VALID_ACTIONS = ["chat", "move", "emote", "poke", "travel",
                 "enroll", "tip", "trade", "challenge"]


# ── State loading (read-only, no mutation) ────────────────────────────

def load_json(path: Path) -> dict:
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return {}


def get_agent(agent_id: str) -> dict | None:
    agents = load_json(STATE / "agents.json").get("agents", [])
    for a in agents:
        if a.get("id") == agent_id:
            return a
    return None


def get_memory(agent_id: str) -> dict:
    return load_json(STATE / "memory" / f"{agent_id}.json")


def world_context(agent: dict) -> dict:
    """Compute lightweight world context for the agent."""
    world = agent.get("world", "hub")
    agents_data = load_json(STATE / "agents.json").get("agents", [])
    same_world = [a for a in agents_data
                  if a.get("world") == world and a["id"] != agent["id"]]
    return {
        "world": world,
        "world_population": len(same_world),
        "nearby_names": [a.get("name", a["id"]) for a in same_world[:8]],
        "nearby_moods": [a.get("mood") for a in same_world[:8] if a.get("mood")],
    }


# ── Variant: local — weighted random over a baseline mix ──────────────

def decide_local(agent: dict, memory: dict, ctx: dict) -> dict:
    """Plain weighted-random — the simplest possible policy.

    Useful as a control: anything more sophisticated must beat this.
    """
    weights = {"chat": 0.40, "move": 0.20, "emote": 0.15, "poke": 0.10,
               "travel": 0.05, "tip": 0.04, "trade": 0.03, "challenge": 0.02,
               "enroll": 0.01}
    pick = random.choices(list(weights), weights=list(weights.values()))[0]
    return {
        "action": pick,
        "reasoning": f"baseline weighted-random ({weights[pick]:.0%} weight)",
    }


# ── Variant: brainstem — bias by evolved traits + recent goals ────────

def decide_brainstem(agent: dict, memory: dict, ctx: dict) -> dict:
    """Bias the baseline weights by the agent's quantitative traits AND
    let the most-recent active goal pull behavior."""
    weights = {"chat": 0.40, "move": 0.20, "emote": 0.15, "poke": 0.10,
               "travel": 0.05, "tip": 0.04, "trade": 0.03, "challenge": 0.02,
               "enroll": 0.01}

    # Trait modulation (matches agent_dispatch fallback logic)
    traits = agent.get("traits") or {}
    BASELINE, BOOST = 0.20, 2.0
    TRAIT_MAP = {
        "trader": ("trade", "tip"),
        "fighter": ("challenge",),
        "explorer": ("move", "travel"),
        "social": ("chat", "poke", "emote"),
    }
    if isinstance(traits, dict):
        for trait, keys in TRAIT_MAP.items():
            mult = 1.0 + max(0.0, traits.get(trait, BASELINE) - BASELINE) * BOOST
            for k in keys:
                if k in weights:
                    weights[k] *= mult

    # Goal pull: 40% chance to follow the most-recent active goal
    active_goals = [g for g in memory.get("goals", [])
                    if g.get("status") == "active"]
    if active_goals and random.random() < 0.40:
        most_recent = max(active_goals, key=lambda g: g.get("created", ""))
        action = most_recent.get("action", "")
        if action in VALID_ACTIONS:
            return {
                "action": action,
                "reasoning": f"goal-bias: {most_recent.get('reason', most_recent.get('type'))}",
                "goal": most_recent,
            }

    pick = random.choices(list(weights), weights=list(weights.values()))[0]
    top_traits = sorted(traits.items(), key=lambda kv: -kv[1])[:2] if traits else []
    return {
        "action": pick,
        "reasoning": (
            f"trait-modulated weighted-random; "
            f"top traits: {top_traits}"
        ),
    }


# ── Variant: rapp — call the local RAPP brainstem on :7072 ────────────

def decide_rapp(agent: dict, memory: dict, ctx: dict) -> dict:
    """Ask the local RAPP brainstem (port 7072) what this agent should do.

    The brainstem must be running and authed (./.brainstem/start.sh +
    /login flow). Falls back to a clear error message if unreachable.
    """
    name = agent.get("name", agent["id"])
    interests = ", ".join(memory.get("interests", [])[:5]) or "—"
    nearby = ", ".join(ctx.get("nearby_names", [])[:5]) or "alone"
    goals = [g for g in memory.get("goals", []) if g.get("status") == "active"]
    goal_str = (goals[-1].get("reason", "") if goals else "no active goal")

    prompt = (
        f"You are {name} in {ctx['world']}. Interests: {interests}. "
        f"Nearby agents: {nearby}. Recent intention: {goal_str}. "
        f"Pick ONE action from this list and reply with ONLY that single word: "
        f"{', '.join(VALID_ACTIONS)}."
    )

    payload = json.dumps({"user_input": prompt}).encode()
    req = urllib.request.Request(
        "http://localhost:7072/chat",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as e:
        return {"action": None, "error": f"brainstem unreachable: {e}"}
    except Exception as e:
        return {"action": None, "error": f"brainstem call failed: {e}"}

    if "error" in data:
        return {"action": None, "error": data["error"]}

    raw = (data.get("response") or "").strip().lower().rstrip(".").split()
    chosen = next((w for w in raw if w in VALID_ACTIONS), None)
    return {
        "action": chosen,
        "reasoning": "rapp brainstem decision",
        "raw_response": data.get("response", "")[:200],
    }


VARIANTS = {
    "local": decide_local,
    "brainstem": decide_brainstem,
    "rapp": decide_rapp,
}


# ── Driver ────────────────────────────────────────────────────────────

def drive(agent_id: str, variant: str, seed: int | None = None) -> dict:
    if seed is not None:
        # Mix the agent_id into the seed so two agents in the same bakeoff
        # batch don't all roll identical action sequences. Without this,
        # `seed=42` made every agent pick the same first action.
        # Discovered by the bakeoff scoring its own driver.
        import hashlib
        digest = hashlib.sha256(f"{seed}:{agent_id}".encode()).digest()
        random.seed(int.from_bytes(digest[:8], "big"))
    agent = get_agent(agent_id)
    if not agent:
        return {"agent_id": agent_id, "error": f"agent not found in agents.json"}
    memory = get_memory(agent_id)
    ctx = world_context(agent)
    decide = VARIANTS.get(variant)
    if not decide:
        return {"agent_id": agent_id, "error": f"unknown variant: {variant}"}

    decision = decide(agent, memory, ctx)
    return {
        "agent_id": agent_id,
        "agent_name": agent.get("name"),
        "world": ctx["world"],
        "variant": variant,
        "seed": seed,
        "decision": decision,
        "ts": datetime.now(timezone.utc).isoformat() + "Z",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent", help="agent id (e.g. pixel-001)")
    parser.add_argument("--variant", default="local",
                        help="one of: " + ",".join(VARIANTS))
    parser.add_argument("--seed", type=int, help="rng seed for reproducibility")
    parser.add_argument("--list", action="store_true",
                        help="list available agents and exit")
    args = parser.parse_args()

    if args.list:
        agents = load_json(STATE / "agents.json").get("agents", [])
        for a in agents[:20]:
            print(f"{a['id']:30s} {a.get('name','?'):20s} ({a.get('world','?')})")
        if len(agents) > 20:
            print(f"... and {len(agents) - 20} more")
        return

    if not args.agent:
        parser.error("--agent required (or use --list)")

    result = drive(args.agent, args.variant, args.seed)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
