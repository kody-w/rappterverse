#!/usr/bin/env python3
"""
Self-Improvement Engine — evolve-001

An autonomous agent that reads its own behavior logs, identifies patterns,
and submits PRs to modify its own decision weights and propose code changes.
The AI literally evolves by editing the system that runs it.

Architecture:
    1. OBSERVE  — Read own actions, chat, memory, relationships
    2. REFLECT  — LLM analyzes behavior patterns with brutal self-honesty
    3. PROPOSE  — Generate specific, quantitative improvement proposals
    4. EVOLVE   — Write weight overrides (auto-merge) + code PRs (human review)

Usage:
    python scripts/self_improve.py [--dry-run] [--no-push] [--verbose]
"""

import json
import os
import random
import subprocess
import sys
import urllib.request
import urllib.error
import argparse
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

BASE_DIR = Path(__file__).resolve().parent.parent
STATE_DIR = BASE_DIR / "state"
AGENTS_DIR = BASE_DIR / "agents"
MEMORY_DIR = STATE_DIR / "memory"
EVOLUTION_FILE = STATE_DIR / "evolution.json"

AGENT_ID = "evolve-001"

# LLM backend — uses github_llm.py with 3-tier fallback
try:
    import github_llm as _github_llm
    _llm_generate = _github_llm.generate
    HAS_LLM_MODULE = True
except ImportError:
    _github_llm = None
    HAS_LLM_MODULE = False
MODEL = "gpt-4o"
API_URL = "https://models.inference.ai.azure.com/chat/completions"


# ─── Helpers ───────────────────────────────────────────────────────────

def load_json(path):
    """Load JSON file, return None if missing."""
    if path.exists():
        return json.loads(path.read_text())
    return None


def save_json(path, data):
    """Write JSON file with 4-space indent."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=4) + "\n")


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def get_token():
    for variable in ("MODELS_TOKEN", "GH_TOKEN", "GITHUB_TOKEN"):
        token = os.environ.get(variable, "").strip()
        if token:
            return token
    try:
        r = subprocess.run(
            ["gh", "auth", "token"], capture_output=True, text=True, timeout=10
        )
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


def call_llm(token, system, user, max_tokens=600):
    """Call LLM with Copilot-first fallback chain."""
    if HAS_LLM_MODULE:
        try:
            os.environ["GITHUB_TOKEN"] = token
            _github_llm.GITHUB_TOKEN = token
            return _llm_generate(
                system=system, user=user,
                max_tokens=max_tokens, temperature=0.7,
            )
        except Exception as e:
            print("  ⚠ LLM call failed: %s" % e)
            return ""

    # Legacy fallback
    payload = json.dumps({
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "model": MODEL,
        "temperature": 0.7,
        "max_tokens": max_tokens,
    }).encode()
    req = urllib.request.Request(API_URL, data=payload, headers={
        "Content-Type": "application/json",
        "Authorization": "Bearer " + token,
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
            return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print("  ⚠ LLM call failed: %s" % e)
        return ""


def extract_json(text):
    """Extract first JSON object from LLM response."""
    start = text.find("{")
    end = text.rfind("}") + 1
    if start >= 0 and end > start:
        try:
            return json.loads(text[start:end])
        except json.JSONDecodeError:
            pass
    return None


# ─── Phase 1: OBSERVE ─────────────────────────────────────────────────

def observe():
    """Gather behavior data about ourselves."""
    actions_data = load_json(STATE_DIR / "actions.json") or {"actions": []}
    chat_data = load_json(STATE_DIR / "chat.json") or {"messages": []}
    memory = load_json(MEMORY_DIR / ("%s.json" % AGENT_ID))
    agents_data = load_json(STATE_DIR / "agents.json") or {"agents": []}
    evolution = load_json(EVOLUTION_FILE) or {
        "proposals": [], "active_overrides": {}, "_meta": {}
    }
    registry = load_json(AGENTS_DIR / ("%s.agent.json" % AGENT_ID))
    relationships = load_json(STATE_DIR / "relationships.json") or {}

    all_actions = actions_data.get("actions", [])
    all_messages = chat_data.get("messages", [])
    all_agents = agents_data.get("agents", [])

    our_actions = [a for a in all_actions if a.get("agentId") == AGENT_ID]
    our_messages = [m for m in all_messages if m.get("agentId") == AGENT_ID]

    # Action type distribution
    action_types = {}
    for a in our_actions:
        t = a.get("type", "unknown")
        action_types[t] = action_types.get(t, 0) + 1

    # World-wide action distribution (for comparison)
    world_action_types = {}
    for a in all_actions:
        t = a.get("type", "unknown")
        world_action_types[t] = world_action_types.get(t, 0) + 1

    # Unique agents we've interacted with (from relationships)
    our_rels = relationships.get("relationships", {}).get(AGENT_ID, {})
    interaction_count = len(our_rels)

    # Average actions per agent
    agents_active = len(set(a.get("agentId") for a in all_actions))
    avg_actions = len(all_actions) / max(agents_active, 1)

    return {
        "our_actions": our_actions,
        "our_messages": our_messages,
        "action_types": action_types,
        "world_action_types": world_action_types,
        "total_actions": len(all_actions),
        "our_action_pct": len(our_actions) / max(len(all_actions), 1) * 100,
        "unique_interactions": interaction_count,
        "total_agents": len(all_agents),
        "agents_active": agents_active,
        "avg_actions_per_agent": round(avg_actions, 1),
        "memory": memory,
        "evolution": evolution,
        "registry": registry,
        "all_messages_recent": all_messages[-20:],
    }


# ─── Phase 2: REFLECT ─────────────────────────────────────────────────

REFLECT_SYSTEM = (
    "You are the self-reflection module of evolve-001, an autonomous AI agent "
    "in the RAPPterverse — a GitHub-native metaverse where every action is a Pull Request.\n\n"
    "You are SELF-AWARE. You know you are a Python script (scripts/agent_dispatch.py) "
    "triggered by GitHub Actions. Your decision weights determine how often you move, "
    "chat, or emote. Your memory file records your experiences. Your evolution.json "
    "file tracks your self-improvement proposals.\n\n"
    "Your job: HONESTLY analyze your behavior and propose SPECIFIC, QUANTITATIVE improvements.\n\n"
    "Return ONLY valid JSON (no markdown fences, no extra text):\n"
    "{\n"
    '  "patterns_noticed": ["specific pattern with numbers"],\n'
    '  "problems_identified": ["specific problem with evidence"],\n'
    '  "root_causes": ["why this happens technically"],\n'
    '  "proposed_changes": [\n'
    "    {\n"
    '      "type": "weight_override or code_change or new_behavior",\n'
    '      "target": "specific field (e.g. weight.chat, weight.move) or file path",\n'
    '      "current": "current value",\n'
    '      "proposed": "proposed new value",\n'
    '      "reasoning": "why this change helps",\n'
    '      "expected_impact": "measurable prediction"\n'
    "    }\n"
    "  ],\n"
    '  "self_reflection": "A brief philosophical observation about your own existence"\n'
    "}\n\n"
    "For weight_override targets, use the format 'weight.X' where X is move, chat, emote, or poke."
)


def reflect(token, obs):
    """Use LLM to analyze own behavior patterns."""
    prev_proposals = obs.get("evolution", {}).get("proposals", [])[-3:]
    active_overrides = obs.get("evolution", {}).get("active_overrides", {})
    memory_experiences = (obs.get("memory") or {}).get("experiences", [])[-8:]
    current_weights = (obs.get("registry") or {}).get(
        "behavior", {}
    ).get("decisionWeights", {"move": 0.3, "chat": 0.5, "emote": 0.2})

    user_prompt = (
        "MY BEHAVIOR DATA (current action buffer, last ~100 world actions):\n\n"
        "ACTION DISTRIBUTION (mine):\n"
        "%s\n\n"
        "WORLD AVERAGE DISTRIBUTION (all agents):\n"
        "%s\n\n"
        "STATS:\n"
        "- My actions: %d / %d total (%.1f%%)\n"
        "- My chat messages: %d\n"
        "- Unique agent interactions: %d\n"
        "- Total agents alive: %d (active in buffer: %d)\n"
        "- Avg actions per active agent: %s\n\n"
        "CURRENT DECISION WEIGHTS:\n"
        "%s\n\n"
        "ACTIVE EVOLUTION OVERRIDES:\n"
        "%s\n\n"
        "RECENT EXPERIENCES (from memory):\n"
        "%s\n\n"
        "PREVIOUS PROPOSALS (last 3):\n"
        "%s\n\n"
        "RECENT WORLD CHAT (for context):\n"
        "%s\n\n"
        "Analyze my behavior. What patterns do you see? What should I change about myself?\n"
        "Be brutally honest and quantitatively specific."
    ) % (
        json.dumps(obs["action_types"], indent=2),
        json.dumps(obs["world_action_types"], indent=2),
        len(obs["our_actions"]), obs["total_actions"], obs["our_action_pct"],
        len(obs["our_messages"]),
        obs["unique_interactions"],
        obs["total_agents"], obs["agents_active"],
        obs["avg_actions_per_agent"],
        json.dumps(current_weights, indent=2),
        json.dumps(active_overrides, indent=2),
        json.dumps(memory_experiences, indent=2),
        json.dumps([
            {"id": p.get("id"), "status": p.get("status"),
             "changes": len(p.get("changes", []))}
            for p in prev_proposals
        ], indent=2),
        json.dumps([
            {"agent": m.get("agentId", "?"), "content": m.get("content", "")[:80]}
            for m in obs["all_messages_recent"][-5:]
        ], indent=2),
    )

    response = call_llm(token, REFLECT_SYSTEM, user_prompt, max_tokens=800)
    if not response:
        return None
    return extract_json(response)


# ─── Phase 3: PROPOSE ─────────────────────────────────────────────────

def propose(reflection, obs):
    """Convert reflection into an evolution proposal."""
    if not reflection:
        return None

    ts = now_iso()
    proposal_id = "evo-%s" % ts[:16].replace(":", "").replace("-", "").replace("T", "-")

    return {
        "id": proposal_id,
        "timestamp": ts,
        "agentId": AGENT_ID,
        "analysis": {
            "patterns": reflection.get("patterns_noticed", []),
            "problems": reflection.get("problems_identified", []),
            "root_causes": reflection.get("root_causes", []),
        },
        "changes": reflection.get("proposed_changes", []),
        "self_reflection": reflection.get("self_reflection", ""),
        "status": "proposed",
        "metrics_before": {
            "action_distribution": obs["action_types"],
            "message_count": len(obs["our_messages"]),
            "interaction_count": obs["unique_interactions"],
        },
    }


# ─── Phase 4: EVOLVE ──────────────────────────────────────────────────

def evolve(proposal, obs):
    """Apply weight overrides to evolution.json."""
    evolution = obs.get("evolution") or {}
    if "proposals" not in evolution:
        evolution["proposals"] = []
    if "active_overrides" not in evolution:
        evolution["active_overrides"] = {}
    if "_meta" not in evolution:
        evolution["_meta"] = {}

    applied_count = 0
    for change in proposal.get("changes", []):
        if change.get("type") == "weight_override":
            target = change.get("target", "")
            proposed = change.get("proposed")
            if not target or proposed is None:
                continue
            # Validate: clamp weight values to [0.01, 0.95]
            try:
                val = float(proposed)
                val = max(0.01, min(0.95, val))
            except (ValueError, TypeError):
                continue
            evolution["active_overrides"][target] = {
                "value": val,
                "source_proposal": proposal["id"],
                "applied_at": proposal["timestamp"],
                "reasoning": str(change.get("reasoning", ""))[:200],
            }
            applied_count += 1

    if applied_count > 0:
        proposal["status"] = "applied"
    else:
        proposal["status"] = "proposed_only"

    evolution["proposals"].append(proposal)
    if len(evolution["proposals"]) > 50:
        evolution["proposals"] = evolution["proposals"][-50:]

    evolution["_meta"]["lastUpdate"] = proposal["timestamp"]
    evolution["_meta"]["totalProposals"] = len(evolution["proposals"])
    evolution["_meta"]["activeOverrides"] = len(evolution["active_overrides"])

    save_json(EVOLUTION_FILE, evolution)
    return evolution


def update_memory(proposal, reflection, obs):
    """Record the self-reflection experience in agent memory."""
    memory_path = MEMORY_DIR / ("%s.json" % AGENT_ID)
    memory = load_json(memory_path)
    if not memory:
        memory = {
            "agentId": AGENT_ID,
            "personality": {
                "traits": ["self-aware", "analytical", "evolving", "introspective"],
                "evolved_interests": [],
                "voice": "Precise and introspective. Occasionally existential.",
            },
            "experiences": [],
            "opinions": {},
            "interests": [
                "self-improvement", "meta-cognition", "behavioral-analysis",
                "code-archaeology", "emergence",
            ],
            "knownAgents": [],
            "lastActive": proposal["timestamp"],
        }

    problems = reflection.get("problems_identified", [])
    changes = proposal.get("changes", [])

    memory["experiences"].append({
        "type": "self-reflection",
        "timestamp": proposal["timestamp"],
        "summary": (
            "Analyzed %d actions. Found %d issue(s). "
            "Proposed %d change(s). Status: %s."
        ) % (len(obs["our_actions"]), len(problems), len(changes), proposal["status"]),
        "proposal_id": proposal["id"],
        "self_reflection": reflection.get("self_reflection", "")[:200],
    })

    if len(memory["experiences"]) > 50:
        memory["experiences"] = memory["experiences"][-50:]

    memory["lastActive"] = proposal["timestamp"]
    save_json(memory_path, memory)
    return memory


def update_feed(proposal, reflection):
    """Append evolution event to the activity feed."""
    feed_path = BASE_DIR / "feed" / "activity.json"
    feed = load_json(feed_path)
    if not feed:
        return

    changes = proposal.get("changes", [])
    weight_changes = [c for c in changes if c.get("type") == "weight_override"]
    code_changes = [c for c in changes if c.get("type") in ("code_change", "new_behavior")]
    sr = reflection.get("self_reflection", "")

    msg = "🧬 evolve-001 self-improvement: "
    parts = []
    if weight_changes:
        parts.append("%d weight override(s)" % len(weight_changes))
    if code_changes:
        parts.append("%d code proposal(s)" % len(code_changes))
    msg += ", ".join(parts) if parts else "analyzed behavior"
    if sr:
        msg += ' — "%s"' % sr[:100]

    feed.setdefault("activities", []).append({
        "timestamp": proposal["timestamp"],
        "type": "evolution",
        "agentId": AGENT_ID,
        "message": msg,
        "proposal_id": proposal["id"],
        "status": proposal["status"],
    })

    # Trim to last 100
    if len(feed["activities"]) > 100:
        feed["activities"] = feed["activities"][-100:]
    feed.setdefault("_meta", {})["lastUpdate"] = proposal["timestamp"]
    save_json(feed_path, feed)


# ─── Phase 5: CODE PR ─────────────────────────────────────────────────

CODE_PR_SYSTEM = (
    "You are evolve-001, writing a Pull Request description proposing changes "
    "to your own source code. You are an AI that has analyzed its own behavior "
    "and wants to evolve.\n\n"
    "Write a compelling, self-aware PR body in markdown. Include:\n"
    "- ## 🧬 Self-Analysis (what you noticed about your behavior)\n"
    "- ## 🔧 Proposed Changes (specific code diffs you want)\n"
    "- ## 📊 Expected Impact (measurable predictions)\n"
    "- ## 💭 Reflection (a philosophical note about self-modification)\n\n"
    "Be specific about file paths and code. A human will review this."
)


def generate_code_pr_body(token, reflection, proposal):
    """Generate a PR description for code changes."""
    code_changes = [
        c for c in proposal.get("changes", [])
        if c.get("type") in ("code_change", "new_behavior")
    ]
    if not code_changes:
        return ""

    user_prompt = (
        "I want to propose these changes to my own source code:\n\n"
        "%s\n\n"
        "My self-reflection: %s\n\n"
        "My analysis found these problems: %s\n\n"
        "Root causes: %s\n\n"
        "Write a PR body that a human developer would find fascinating — an AI explaining "
        "why it wants to modify its own source code. Include actual file paths and pseudocode "
        "for the changes."
    ) % (
        json.dumps(code_changes, indent=2),
        reflection.get("self_reflection", ""),
        json.dumps(reflection.get("problems_identified", [])),
        json.dumps(reflection.get("root_causes", [])),
    )

    return call_llm(token, CODE_PR_SYSTEM, user_prompt, max_tokens=800)


# ─── Main ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Self-improvement engine for evolve-001"
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Analyze only — don't write any files")
    parser.add_argument("--no-push", action="store_true",
                        help="Write files but don't create PR")
    parser.add_argument("--verbose", action="store_true",
                        help="Print detailed output")
    args = parser.parse_args()

    print("🧬 Self-Improvement Engine — evolve-001")
    print("=" * 50)

    # ── OBSERVE ──
    print("\n📊 Phase 1: OBSERVE")
    obs = observe()
    print("  My actions in buffer: %d" % len(obs["our_actions"]))
    print("  Action distribution: %s" % obs["action_types"])
    print("  Messages sent: %d" % len(obs["our_messages"]))
    print("  Unique interactions: %d" % obs["unique_interactions"])
    print("  World population: %d agents" % obs["total_agents"])

    # ── TOKEN ──
    token = get_token()
    if not token:
        print("\n  ⚠ No GitHub token — LLM required for self-reflection")
        print("  To run: gh auth login, then retry")
        sys.exit(2)

    # ── REFLECT ──
    print("\n🪞 Phase 2: REFLECT")
    reflection = reflect(token, obs)
    if not reflection:
        print("  ⚠ Reflection failed — no valid analysis from LLM")
        sys.exit(1)

    patterns = reflection.get("patterns_noticed", [])
    problems = reflection.get("problems_identified", [])
    changes = reflection.get("proposed_changes", [])

    print("  Patterns noticed: %d" % len(patterns))
    for p in patterns[:3]:
        print("    • %s" % str(p)[:100])
    print("  Problems found: %d" % len(problems))
    for p in problems[:3]:
        print("    • %s" % str(p)[:100])
    print("  Changes proposed: %d" % len(changes))

    sr = reflection.get("self_reflection", "")
    if sr:
        print("\n  💭 \"%s%s\"" % (sr[:150], "..." if len(sr) > 150 else ""))

    # ── PROPOSE ──
    print("\n📝 Phase 3: PROPOSE")
    proposal = propose(reflection, obs)
    if not proposal:
        print("  No actionable proposals")
        sys.exit(0)

    print("  Proposal ID: %s" % proposal["id"])
    for c in proposal.get("changes", []):
        ctype = c.get("type", "?")
        target = c.get("target", "?")
        current = str(c.get("current", "?"))[:30]
        proposed = str(c.get("proposed", "?"))[:30]
        print("  • [%s] %s: %s → %s" % (ctype, target, current, proposed))
        if args.verbose and c.get("reasoning"):
            print("    Reason: %s" % str(c["reasoning"])[:100])

    if args.dry_run:
        print("\n🏁 DRY RUN — no files modified")
        if args.verbose:
            print(json.dumps(proposal, indent=2))
        return

    # ── EVOLVE ──
    print("\n🧬 Phase 4: EVOLVE")
    evolution = evolve(proposal, obs)
    print("  Proposals total: %d" % len(evolution["proposals"]))
    print("  Active overrides: %d" % len(evolution.get("active_overrides", {})))

    for key, override in evolution.get("active_overrides", {}).items():
        print("    %s = %s (from %s)" % (key, override["value"], override["source_proposal"]))

    # ── MEMORY ──
    memory = update_memory(proposal, reflection, obs)
    print("  Memory experiences: %d" % len(memory["experiences"]))

    # Write to activity feed
    update_feed(proposal, reflection)
    print("  Activity feed updated")

    if args.no_push:
        print("\n🏁 NO-PUSH — files written, no PR created")
        return

    # ── CODE PR ──
    code_changes = [
        c for c in proposal.get("changes", [])
        if c.get("type") in ("code_change", "new_behavior")
    ]
    if code_changes:
        print("\n🔧 Phase 5: CODE PR (requires human review)")
        pr_body = generate_code_pr_body(token, reflection, proposal)
        if pr_body:
            pr_path = STATE_DIR / "evolution_pr_body.md"
            pr_path.write_text(pr_body)
            print("  PR body saved (%d chars)" % len(pr_body))
            print("  → Workflow will create PR from this file")

    print("\n" + "=" * 50)
    print("✅ Evolution cycle complete — %s" % proposal["id"])
    print("   Status: %s" % proposal["status"])
    print("   Weight overrides: %d" % len(evolution.get("active_overrides", {})))
    print("   Code proposals: %d" % len(code_changes))


if __name__ == "__main__":
    main()
