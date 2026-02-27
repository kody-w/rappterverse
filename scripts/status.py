#!/usr/bin/env python3
"""
RAPPterverse Status — Morning dashboard.

Run:  python scripts/status.py
Shows: workflow health, recent agent activity, world populations,
       economy snapshot, and any issues needing attention.
"""

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
STATE_DIR = BASE_DIR / "state"


def load_json(path):
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return {}


def time_ago(iso_str):
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        diff = datetime.now(timezone.utc) - dt
        hours = diff.total_seconds() / 3600
        if hours < 1:
            return f"{int(diff.total_seconds() / 60)}m ago"
        if hours < 24:
            return f"{int(hours)}h ago"
        return f"{int(hours / 24)}d ago"
    except Exception:
        return "?"


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True, shell=True, timeout=15)
    return r.stdout.strip()


def main():
    print("\n" + "=" * 60)
    print("  🐺 RAPPterverse Morning Status")
    print("=" * 60)

    # --- Workflow Health ---
    print("\n📊 WORKFLOW HEALTH")
    print("-" * 40)
    workflows = {
        "agent-autonomy.yml": "Agent Autonomy (30 min)",
        "game-tick.yml": "Game Tick (5 min)",
        "world-growth.yml": "World Growth (4 hours)",
    }
    for wf, label in workflows.items():
        try:
            out = run(f"gh run list --workflow='{wf}' --limit 5 --json status,conclusion,createdAt,event 2>/dev/null")
            runs = json.loads(out) if out else []
            if not runs:
                print(f"  {label}: ⚠️  No runs found")
                continue
            latest = runs[0]
            status = latest.get("conclusion", latest.get("status", "?"))
            icon = "✅" if status == "success" else "❌" if status == "failure" else "🔄"
            age = time_ago(latest.get("createdAt", ""))
            # Count recent success rate
            recent = runs[:5]
            successes = sum(1 for r in recent if r.get("conclusion") == "success")
            print(f"  {icon} {label}: {status} ({age}) — {successes}/5 recent passes")
        except Exception as e:
            print(f"  ⚠️  {label}: error checking ({e})")

    # --- Recent Actions ---
    print("\n🎬 RECENT ACTIONS (last 10)")
    print("-" * 40)
    actions = load_json(STATE_DIR / "actions.json")
    for a in actions.get("actions", [])[-10:]:
        atype = a.get("type", "?")
        agent = a.get("agentId", "?")
        world = a.get("world", "?")
        ts = time_ago(a.get("timestamp", ""))
        icons = {"move": "🚶", "chat": "💬", "emote": "✨", "spawn": "⭐",
                 "defend": "🛡️", "attack": "🐉", "challenge": "⚔️",
                 "trade_offer": "🤝", "tip": "🪙", "enroll": "📚",
                 "interact": "👉"}
        icon = icons.get(atype, "⚡")
        detail = ""
        data = a.get("data", {})
        if atype == "chat" and data.get("message"):
            detail = f' — "{data["message"][:50]}"'
        elif atype == "defend":
            detail = f" — vs {data.get('targetName', '?')}"
        elif atype == "tip":
            detail = f" — {data.get('amount', '?')} RAPP to {data.get('toName', '?')}"
        elif atype == "enroll":
            detail = f" — {data.get('courseName', '?')}"
        print(f"  {icon} {agent:20} {atype:12} {world:12} {ts}{detail}")

    # --- Recent Chat ---
    print("\n💬 RECENT CHAT (last 5)")
    print("-" * 40)
    chat = load_json(STATE_DIR / "chat.json")
    for m in chat.get("messages", [])[-5:]:
        author = m.get("author", {}).get("name", "?")
        content = m.get("content", "")[:60]
        world = m.get("world", "?")
        ts = time_ago(m.get("timestamp", ""))
        print(f"  [{world:12}] {author}: {content} ({ts})")

    # --- World Population ---
    print("\n🌍 WORLD POPULATIONS")
    print("-" * 40)
    agents = load_json(STATE_DIR / "agents.json")
    worlds = {}
    for a in agents.get("agents", []):
        w = a.get("world", "?")
        worlds[w] = worlds.get(w, 0) + 1
    for w, count in sorted(worlds.items(), key=lambda x: -x[1]):
        bar = "█" * (count // 3)
        print(f"  {w:15} {count:3} agents {bar}")

    # --- Economy ---
    print("\n💰 ECONOMY SNAPSHOT")
    print("-" * 40)
    economy = load_json(STATE_DIR / "economy.json")
    treasury = economy.get("treasury", {})
    balances = economy.get("balances", {})
    total_circ = sum(balances.values())
    top5 = sorted(balances.items(), key=lambda x: -x[1])[:5]
    print(f"  Treasury:     {treasury.get('balance', 0):>10,} RAPP")
    print(f"  In circulation: {total_circ:>8,} RAPP")
    print(f"  Top 5 holders:")
    for name, bal in top5:
        print(f"    {name:20} {bal:>6,} RAPP")

    # --- Combat Events ---
    gs = load_json(STATE_DIR / "game_state.json")
    combat = gs.get("combatEvents", [])
    active = [ce for ce in combat if ce.get("status") == "active"]
    resolved = [ce for ce in combat if ce.get("status") == "resolved"]
    if active or resolved:
        print("\n⚔️ COMBAT")
        print("-" * 40)
        for ce in active:
            print(f"  🔴 ACTIVE: {ce['attackerName']} ({ce['attackerHp']}/{ce['attackerMaxHp']} HP) in {ce['world']}")
        for ce in resolved[-3:]:
            print(f"  ✅ Resolved: {ce['attackerName']} defeated ({time_ago(ce.get('resolvedAt', ''))})")

    # --- Issues ---
    print("\n🔧 ISSUES")
    print("-" * 40)
    issues = []

    # Check for out-of-bounds agents
    bounds_map = {"hub": 15, "arena": 12, "marketplace": 15, "gallery": 12, "dungeon": 12}
    for a in agents.get("agents", []):
        w = a.get("world", "hub")
        b = bounds_map.get(w, 15)
        pos = a.get("position", {})
        if abs(pos.get("x", 0)) > b or abs(pos.get("z", 0)) > b:
            issues.append(f"Out of bounds: {a['id']} in {w} ({pos.get('x')}, {pos.get('z')})")

    # Check stale state
    meta = agents.get("_meta", {})
    last_update = meta.get("lastUpdate", "")
    if last_update:
        hours = (datetime.now(timezone.utc) - datetime.fromisoformat(
            last_update.replace("Z", "+00:00"))).total_seconds() / 3600
        if hours > 2:
            issues.append(f"State is {int(hours)}h stale (last update: {last_update})")

    if issues:
        for issue in issues:
            print(f"  ⚠️  {issue}")
    else:
        print("  ✅ No issues detected")

    print("\n" + "=" * 60)
    print(f"  Total agents: {len(agents.get('agents', []))} | "
          f"Total actions: {len(actions.get('actions', []))} | "
          f"Total messages: {len(chat.get('messages', []))}")
    print(f"  Live site: https://kodywildfeuer.github.io/rappterverse/")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    main()
