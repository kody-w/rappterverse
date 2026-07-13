#!/usr/bin/env python3
"""
RAPPterverse Emergence Metrics — Quantify life vs noise.

Measures 6 dimensions of emergent behavior on a 0-100 scale:
  1. Action Diversity  — Are agents doing varied things, or one bot spamming?
  2. Social Depth      — Are relationships deepening, or staying shallow?
  3. Goal Completion    — Are agents finishing what they start?
  4. Economic Agency    — Are agents actively trading/tipping, or just collecting?
  5. Migration Patterns — Are agents traveling with purpose?
  6. Conversation Quality — Are chats unique and responsive, or template noise?

Run:  python scripts/emergence.py
"""

import json
import os
import math
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
STATE_DIR = BASE_DIR / "state"
MEMORY_DIR = STATE_DIR / "memory"


def load_json(path):
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return {}


def action_diversity_score(actions: list) -> tuple[float, list[str]]:
    """Score 0-100: how varied are agent actions?
    
    Noise: one action type dominates (>70%). 
    Emergence: even spread across 5+ types.
    """
    insights = []
    if not actions:
        return 0, ["No actions recorded"]

    types = Counter(a.get("type") for a in actions)
    total = sum(types.values())
    
    # Shannon entropy normalized to max possible
    num_types = len(types)
    if num_types <= 1:
        return 5, ["Only one action type — no diversity"]
    
    entropy = -sum((c / total) * math.log2(c / total) for c in types.values())
    max_entropy = math.log2(num_types)
    normalized = entropy / max_entropy if max_entropy > 0 else 0
    
    # Penalize if one type > 50%
    top_type, top_count = types.most_common(1)[0]
    top_pct = top_count / total * 100
    if top_pct > 70:
        insights.append(f"⚠️ '{top_type}' is {top_pct:.0f}% of all actions — dominates everything")
        normalized *= 0.3
    elif top_pct > 50:
        insights.append(f"⚠️ '{top_type}' is {top_pct:.0f}% — still dominant")
        normalized *= 0.6
    
    # Bonus for strategic actions (not just move/chat/emote)
    strategic = sum(types.get(t, 0) for t in ["trade_offer", "enroll", "tip", "challenge", "travel", "defend"])
    strategic_pct = strategic / total * 100 if total else 0
    if strategic_pct > 20:
        insights.append(f"✅ {strategic_pct:.0f}% strategic actions (trade/enroll/tip/challenge)")
    elif strategic_pct > 5:
        insights.append(f"📊 {strategic_pct:.0f}% strategic actions — growing")
    else:
        insights.append(f"⚠️ Only {strategic_pct:.0f}% strategic actions — mostly ambient")
    
    # Count distinct agents acting
    distinct_agents = len(set(a.get("agentId") for a in actions))
    insights.append(f"📊 {distinct_agents} distinct agents acted (of {len(actions)} actions)")
    
    score = min(100, normalized * 100)
    return score, insights


def social_depth_score(relationships: dict) -> tuple[float, list[str]]:
    """Score 0-100: are relationships deepening?
    
    Noise: all edges are weak (<10). 
    Emergence: strong bonds (>30), clusters forming.
    """
    insights = []
    edges = relationships.get("edges", [])
    if not edges:
        return 0, ["No relationships exist"]
    
    scores = [e.get("score", 0) for e in edges]
    avg = sum(scores) / len(scores)
    strong = sum(1 for s in scores if s >= 30)
    medium = sum(1 for s in scores if 10 <= s < 30)
    weak = sum(1 for s in scores if s < 10)
    
    # Score based on distribution
    strong_ratio = strong / len(edges)
    medium_ratio = medium / len(edges)
    
    score = min(100, (strong_ratio * 200 + medium_ratio * 80 + min(avg, 30) * 2))
    
    insights.append(f"📊 {len(edges)} relationships — avg score {avg:.1f}")
    if strong > 0:
        insights.append(f"✅ {strong} strong bonds (>30) — real friendships forming")
    else:
        insights.append(f"⚠️ No strong bonds yet — all relationships are surface-level")
    if medium > 10:
        insights.append(f"📊 {medium} medium bonds (10-30) — potential deepening")
    
    # Check for clusters (agents with 3+ medium+ connections)
    agent_connections = Counter()
    for e in edges:
        if e.get("score", 0) >= 10:
            agent_connections[e["a"]] += 1
            agent_connections[e["b"]] += 1
    social_butterflies = sum(1 for _, c in agent_connections.items() if c >= 3)
    if social_butterflies:
        insights.append(f"✅ {social_butterflies} social hubs (3+ meaningful connections)")
        score = min(100, score + social_butterflies * 3)
    
    return score, insights


def goal_completion_score() -> tuple[float, list[str]]:
    """Score 0-100: are agents following through on intentions?
    
    Noise: goals set but never completed.
    Emergence: goals created, pursued, completed, new goals generated.
    """
    insights = []
    total = 0
    active = 0
    completed = 0
    agents_with_goals = 0
    agents_total = 0
    
    if not MEMORY_DIR.exists():
        return 0, ["Memory directory not found"]

    for f in os.listdir(MEMORY_DIR):
        if not f.endswith('.json'):
            continue
        agents_total += 1
        try:
            with open(MEMORY_DIR / f) as mf:
                mem = json.load(mf)
        except (json.JSONDecodeError, OSError):
            continue
        goals = mem.get("goals", [])
        if goals:
            agents_with_goals += 1
        for g in goals:
            total += 1
            if g.get("status") == "done":
                completed += 1
            elif g.get("status") == "active":
                active += 1
    
    if total == 0:
        return 0, ["No goals exist — agents have no intentions"]
    
    completion_rate = completed / total * 100 if total else 0
    coverage = agents_with_goals / agents_total * 100 if agents_total else 0
    
    score = min(100, completion_rate * 2 + (coverage / 2))
    
    insights.append(f"📊 {total} total goals — {active} active, {completed} completed")
    insights.append(f"📊 {coverage:.0f}% of agents have intentions ({agents_with_goals}/{agents_total})")
    
    if completion_rate > 20:
        insights.append(f"✅ {completion_rate:.0f}% completion rate — agents follow through")
    elif completion_rate > 5:
        insights.append(f"📊 {completion_rate:.0f}% completion rate — starting to follow through")
    else:
        insights.append(f"⚠️ {completion_rate:.0f}% completion rate — goals exist but aren't being pursued")
    
    return score, insights


def economic_agency_score(economy: dict) -> tuple[float, list[str]]:
    """Score 0-100: are agents actively participating in the economy?
    
    Noise: passive income only.
    Emergence: tips, trades, purchases driven by agent decisions.
    """
    insights = []
    ledger = economy.get("ledger", [])
    if not ledger:
        return 0, ["No economic activity"]
    
    types = Counter(t.get("type") for t in ledger)
    total = sum(types.values())
    
    # Agent-driven transactions (not passive income)
    agent_driven = types.get("tip", 0) + types.get("purchase", 0) + types.get("trade", 0)
    passive = types.get("income", 0) + types.get("stipend", 0)
    
    agency_ratio = agent_driven / total * 100 if total else 0
    
    score = min(100, agency_ratio * 5)  # 20% agent-driven = 100 score
    
    insights.append(f"📊 {total} transactions — {agent_driven} agent-driven, {passive} passive")
    
    tips = economy.get("tips", [])
    if len(tips) > 10:
        # Check tip diversity — are different agents tipping different people?
        tippers = len(set(t.get("from") for t in tips))
        recipients = len(set(t.get("to") for t in tips))
        insights.append(f"✅ {len(tips)} tips from {tippers} agents to {recipients} recipients")
        score = min(100, score + tippers * 2)
    
    if agency_ratio > 15:
        insights.append(f"✅ {agency_ratio:.0f}% agent-driven — real economic participation")
    elif agency_ratio > 5:
        insights.append(f"📊 {agency_ratio:.0f}% agent-driven — economy awakening")
    else:
        insights.append(f"⚠️ {agency_ratio:.0f}% agent-driven — mostly passive income")
    
    return score, insights


def migration_score(actions: list, agents: list) -> tuple[float, list[str]]:
    """Score 0-100: are agents traveling with purpose?
    
    Noise: everyone stays put.
    Emergence: agents travel to visit friends, explore new worlds.
    """
    insights = []
    
    travels = [a for a in actions if a.get("data", {}).get("from_world")]
    if not travels:
        # Check agent distribution
        worlds = Counter(a.get("world") for a in agents)
        max_world = worlds.most_common(1)[0] if worlds else ("?", 0)
        concentration = max_world[1] / len(agents) * 100 if agents else 0
        insights.append(f"⚠️ No cross-world travel in recent actions")
        insights.append(f"📊 Population concentration: {max_world[0]} has {concentration:.0f}%")
        return max(0, 30 - concentration / 2), insights
    
    # Purposeful travel (has a reason)
    purposeful = sum(1 for t in travels if t.get("data", {}).get("reason"))
    ratio = purposeful / len(travels) * 100 if travels else 0
    
    # World diversity
    destinations = Counter(t.get("data", {}).get("to_world") for t in travels)
    
    score = min(100, len(travels) * 15 + ratio / 2)
    
    insights.append(f"📊 {len(travels)} cross-world travels ({purposeful} with stated reason)")
    if len(destinations) >= 3:
        insights.append(f"✅ Traveling to {len(destinations)} different worlds")
    
    return score, insights


def conversation_quality_score(messages: list) -> tuple[float, list[str]]:
    """Score 0-100: are conversations meaningful or template noise?
    
    Noise: repeated messages, short generic phrases.
    Emergence: unique content, references to experiences, responsive dialogue.
    """
    insights = []
    if not messages:
        return 0, ["No messages"]
    
    contents = [m.get("content", "") for m in messages]
    
    # Uniqueness
    unique = len(set(contents))
    unique_ratio = unique / len(contents) * 100
    
    # Average length (longer = more substance)
    avg_len = sum(len(c) for c in contents) / len(contents)
    
    # References to other agents (sign of actual interaction)
    agent_names_mentioned = 0
    for c in contents:
        # Simple heuristic: capitalized words that look like agent names
        if any(word in c for word in ["just", "congrats", "agree", "think", "love", "wow"]):
            agent_names_mentioned += 1
    responsive_ratio = agent_names_mentioned / len(contents) * 100
    
    # Score composition
    score = min(100, unique_ratio * 0.4 + min(avg_len, 100) * 0.3 + responsive_ratio * 0.5)
    
    insights.append(f"📊 {unique_ratio:.0f}% unique messages ({unique}/{len(contents)})")
    insights.append(f"📊 Avg message length: {avg_len:.0f} chars")
    if responsive_ratio > 30:
        insights.append(f"✅ {responsive_ratio:.0f}% of messages reference others — real conversation")
    elif responsive_ratio > 10:
        insights.append(f"📊 {responsive_ratio:.0f}% responsive — some genuine interaction")
    else:
        insights.append(f"⚠️ {responsive_ratio:.0f}% responsive — mostly broadcasting, not conversing")
    
    return score, insights


def main():
    actions = load_json(STATE_DIR / "actions.json").get("actions", [])
    chat = load_json(STATE_DIR / "chat.json").get("messages", [])
    rels = load_json(STATE_DIR / "relationships.json")
    economy = load_json(STATE_DIR / "economy.json")
    agents = load_json(STATE_DIR / "agents.json").get("agents", [])
    computed_at = datetime.now(timezone.utc)
    cutoff = computed_at.timestamp() - 7 * 24 * 3600

    def recent(record):
        try:
            timestamp = datetime.fromisoformat(
                record.get("timestamp", "").replace("Z", "+00:00")
            )
        except (ValueError, AttributeError):
            return False
        return cutoff <= timestamp.timestamp() <= computed_at.timestamp() + 300

    recent_actions = [action for action in actions if recent(action)]
    recent_chat = [message for message in chat if recent(message)]
    active_agent_ids = {
        agent["id"]
        for agent in agents
        if agent.get("status") == "active" and agent.get("id")
    }
    participating_agents = {
        action.get("agentId")
        for action in recent_actions
        if action.get("agentId") in active_agent_ids
    }
    participating_agents.update(
        message.get("author", {}).get("id")
        for message in recent_chat
        if isinstance(message.get("author"), dict)
        and message["author"].get("id") in active_agent_ids
    )
    actor_coverage = len(participating_agents) / max(1, len(active_agent_ids))
    observed_timestamps = [
        record.get("timestamp", "")
        for record in recent_actions + recent_chat
        if record.get("timestamp")
    ]
    observed_through = max(observed_timestamps, default=None)
    source_fresh = False
    if observed_through:
        observed_dt = datetime.fromisoformat(observed_through.replace("Z", "+00:00"))
        source_fresh = (computed_at - observed_dt).total_seconds() <= 12 * 3600
    
    print("\n" + "=" * 60)
    print("  🧬 RAPPterverse Emergence Report")
    print("=" * 60)
    
    dimensions = [
        ("🎯 Action Diversity", action_diversity_score(recent_actions)),
        ("🤝 Social Depth", social_depth_score(rels)),
        ("🎯 Goal Completion", goal_completion_score()),
        ("💰 Economic Agency", economic_agency_score(economy)),
        ("🌀 Migration Patterns", migration_score(recent_actions, agents)),
        ("💬 Conversation Quality", conversation_quality_score(recent_chat)),
    ]
    
    total_score = 0
    for name, (score, insights) in dimensions:
        total_score += score
        bar_full = int(score / 5)
        bar_empty = 20 - bar_full
        color = "🟢" if score >= 60 else "🟡" if score >= 30 else "🔴"
        print(f"\n{name}: {color} {score:.0f}/100")
        print(f"  {'█' * bar_full}{'░' * bar_empty}")
        for insight in insights:
            print(f"  {insight}")
    
    overall = total_score / len(dimensions)
    print(f"\n{'=' * 60}")
    gradeable = source_fresh and actor_coverage >= 0.1
    verdict = (
        "⚪ INSUFFICIENT"
        if not gradeable
        else "🌟 THRIVING" if overall >= 60
        else "🌱 GROWING" if overall >= 30
        else "💤 DORMANT"
    )
    print(
        f"  OVERALL EMERGENCE: {verdict} — {overall:.0f}/100 "
        f"({len(participating_agents)}/{len(active_agent_ids)} active actors)"
    )
    
    if overall < 30:
        print(f"\n  🔧 The metaverse is mostly noise right now.")
        print(f"     Fix: more strategic actions, deeper relationships,")
        print(f"     goal follow-through, agent-driven economy.")
    elif overall < 60:
        print(f"\n  📈 Signs of life emerging. Keep the systems running")
        print(f"     and watch for relationship clusters and goal arcs.")
    else:
        print(f"\n  🎉 Genuine emergence detected. Agents are making")
        print(f"     autonomous decisions that create emergent patterns.")
    
    print(f"{'=' * 60}\n")
    
    # Save metrics to state for historical tracking
    metrics = {
        "timestamp": computed_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "overall": round(overall, 1),
        "dimensions": {name.split(" ", 1)[1]: round(score, 1)
                       for name, (score, _) in dimensions},
        "window": {
            "days": 7,
            "sampleCount": len(recent_actions) + len(recent_chat),
            "activeActors": len(participating_agents),
            "activePopulation": len(active_agent_ids),
            "actorCoverage": round(actor_coverage, 4),
            "observedThrough": observed_through,
            "sourceFresh": source_fresh,
            "gradeable": gradeable,
        },
    }
    
    metrics_path = STATE_DIR / "emergence.json"
    history = load_json(metrics_path)
    history.setdefault("snapshots", []).append(metrics)
    history["snapshots"] = history["snapshots"][-100:]  # keep last 100
    history["_meta"] = {"lastUpdate": metrics["timestamp"]}
    history["latest"] = metrics
    
    with open(metrics_path, "w") as f:
        json.dump(history, f, indent=4)
        f.write("\n")


if __name__ == "__main__":
    main()
