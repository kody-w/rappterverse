#!/usr/bin/env python3
"""
npc_agent.py — Autonomous NPC Conversationalist (DEPRECATED)

⚠️  DEPRECATED: Use the openrappter version instead:
    python3.11 -m openrappter.agents.rappterverse_npc_agent

This standalone version uses the GitHub Models API directly via curl.
The openrappter version uses the Copilot SDK (no API keys needed).

Monitors state/chat.json for new player messages, generates in-character
NPC responses using the GitHub Models API (powered by your gh auth token),
and commits them directly to the repo.

Usage:
    python scripts/npc_agent.py              # Single pass (check + respond)
    python scripts/npc_agent.py --watch      # Poll every 30s
    python scripts/npc_agent.py --dry-run    # Preview without committing
"""

import json
import subprocess
import sys
import time
import argparse
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
STATE_DIR = BASE_DIR / "state"
WORLDS_DIR = BASE_DIR / "worlds"

POLL_INTERVAL = 30  # seconds
MODEL = "gpt-4o"
API_URL = "https://models.inference.ai.azure.com/chat/completions"

# NPC agent IDs that can respond (must exist in state/agents.json)
NPC_AGENT_IDS = {
    "rapp-guide-001", "card-trader-001", "codebot-001", "news-anchor-001",
    "battle-master-001", "merchant-001", "gallery-curator-001",
    "banker-001", "arena-announcer-001",
    "warden-001", "flint-001", "whisper-001", "oracle-bone-001",
    "dungeon-guide-001",
}

def get_msg_author_id(msg: dict) -> str:
    """Extract author ID from either message format."""
    if "author" in msg:
        return msg["author"].get("id", "")
    return msg.get("agentId", "")


def get_msg_author_name(msg: dict) -> str:
    """Extract author name from either message format."""
    if "author" in msg:
        return msg["author"].get("name", msg["author"].get("id", "Unknown"))
    return msg.get("agentId", "Unknown")


def get_msg_content(msg: dict) -> str:
    """Extract content from either message format."""
    return msg.get("content", msg.get("message", ""))


LAST_SEEN_FILE = STATE_DIR / ".npc_agent_cursor"


# ─── Data helpers ──────────────────────────────────────────────────────

def load_json(path: Path) -> dict:
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return {}


def save_json(path: Path, data: dict):
    with open(path, 'w') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)
    f.close()


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
    result = subprocess.run(
        ["gh", "auth", "token"],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print("❌ Failed to get GitHub token. Run `gh auth login` first.")
        sys.exit(1)
    return result.stdout.strip()


# ─── NPC personality loader ───────────────────────────────────────────

def load_all_npcs() -> dict:
    """Load NPC personalities from all worlds/*/npcs.json files."""
    npcs = {}
    for world_dir in WORLDS_DIR.iterdir():
        if not world_dir.is_dir():
            continue
        npc_file = world_dir / "npcs.json"
        if not npc_file.exists():
            continue
        data = load_json(npc_file)
        world_id = world_dir.name
        for npc in data.get("npcs", []):
            npcs[npc["id"]] = {
                "world": world_id,
                **npc
            }
    return npcs


def build_agent_to_npc_map(npcs: dict, agents: list) -> dict:
    """Map agent IDs (warden-001) to world NPC data (warden)."""
    agent_map = {}
    for agent in agents:
        aid = agent["id"]
        if aid not in NPC_AGENT_IDS:
            continue
        # Try matching: strip -001 suffix to find NPC
        base_id = aid.rsplit("-", 1)[0] if aid.endswith("-001") else aid
        npc = npcs.get(base_id) or npcs.get(aid)
        if npc:
            agent_map[aid] = {
                "agent": agent,
                "npc": npc
            }
    return agent_map


# ─── LLM call ────────────────────────────────────────────────────────

def generate_response(token: str, npc_data: dict, recent_messages: list,
                      trigger_msg: dict) -> str:
    """Call GitHub Models API to generate an in-character NPC response."""
    npc = npc_data["npc"]
    personality = npc.get("personality", {})
    name = npc.get("name", "Unknown")
    archetype = personality.get("archetype", "neutral")
    mood = personality.get("mood", "calm")
    interests = ", ".join(personality.get("interests", []))
    dialogue_examples = "\n".join(f'- "{d}"' for d in npc.get("dialogue", [])[:5])

    # Build conversation context from recent messages in this world
    world = npc_data["agent"].get("world", "hub")
    context_msgs = [m for m in recent_messages[-15:] if m.get("world") == world]
    context = "\n".join(
        f'{get_msg_author_name(m)}: {get_msg_content(m)}'
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

    user_prompt = f"""Recent chat in {world}:
{context}

{get_msg_author_name(trigger_msg)} just said: "{get_msg_content(trigger_msg)}"

Respond as {name}:"""

    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "max_tokens": 100,
        "temperature": 0.9
    }

    result = subprocess.run(
        ["curl", "-s", "-X", "POST", API_URL,
         "-H", f"Authorization: Bearer {token}",
         "-H", "Content-Type: application/json",
         "-d", json.dumps(payload)],
        capture_output=True, text=True
    )

    try:
        data = json.loads(result.stdout)
        content = data["choices"][0]["message"]["content"].strip()
        # Clean up quotes if the model wraps the response
        if content.startswith('"') and content.endswith('"'):
            content = content[1:-1]
        return content
    except (json.JSONDecodeError, KeyError, IndexError) as e:
        print(f"  ⚠️ LLM error: {e}")
        print(f"  Raw: {result.stdout[:200]}")
        return ""


# ─── Responder logic ─────────────────────────────────────────────────

def pick_responder(trigger_msg: dict, agent_npc_map: dict):
    """Pick which NPC should respond based on world proximity."""
    msg_world = trigger_msg.get("world", "hub")
    author_id = get_msg_author_id(trigger_msg)

    # Only respond to non-NPC messages (players talking)
    if author_id in NPC_AGENT_IDS:
        return None

    # Find NPCs in the same world
    candidates = [
        aid for aid, info in agent_npc_map.items()
        if info["agent"].get("world") == msg_world
    ]

    if not candidates:
        return None

    # Pick a random NPC from that world
    import random
    return random.choice(candidates)


def get_last_seen_msg_id() -> str:
    if LAST_SEEN_FILE.exists():
        return LAST_SEEN_FILE.read_text().strip()
    return ""


def set_last_seen_msg_id(msg_id: str):
    LAST_SEEN_FILE.write_text(msg_id)


# ─── Main loop ───────────────────────────────────────────────────────

def run_once(dry_run: bool = False):
    """Single pass: check for new messages, generate NPC responses."""
    now = datetime.now(timezone.utc)
    timestamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")

    # Load state
    chat_data = load_json(STATE_DIR / "chat.json")
    actions_data = load_json(STATE_DIR / "actions.json")
    agents_data = load_json(STATE_DIR / "agents.json")

    messages = chat_data.get("messages", [])
    actions = actions_data.get("actions", [])
    agents = agents_data.get("agents", [])

    # Load NPC personalities
    all_npcs = load_all_npcs()
    agent_npc_map = build_agent_to_npc_map(all_npcs, agents)

    if not agent_npc_map:
        print("⚠️ No NPC agents found in state/agents.json")
        return

    # Find new messages since last check
    last_seen = get_last_seen_msg_id()
    new_msgs = []
    found_cursor = not last_seen  # If no cursor, process last few messages
    for msg in messages:
        if found_cursor:
            new_msgs.append(msg)
        elif msg["id"] == last_seen:
            found_cursor = True

    # If first run, just respond to the last message
    if not last_seen and messages:
        new_msgs = messages[-1:]

    # Filter to player messages only (not NPC chatter)
    player_msgs = [m for m in new_msgs if get_msg_author_id(m) not in NPC_AGENT_IDS]

    if not player_msgs:
        print(f"💤 No new player messages. ({len(messages)} total messages)")
        if messages:
            set_last_seen_msg_id(messages[-1]["id"])
        return

    print(f"💬 Found {len(player_msgs)} new player message(s)")

    token = get_gh_token()
    responses_added = 0

    for trigger in player_msgs:
        responder_id = pick_responder(trigger, agent_npc_map)
        if not responder_id:
            continue

        npc_info = agent_npc_map[responder_id]
        npc_name = npc_info["npc"].get("name", responder_id)
        print(f"  🤖 {npc_name} responding to {get_msg_author_name(trigger)}...")

        # Generate response
        response_text = generate_response(token, npc_info, messages, trigger)
        if not response_text:
            continue

        print(f"  💬 \"{response_text}\"")

        if dry_run:
            responses_added += 1
            continue

        # Build new message
        msg_id = get_next_id("msg-", [m["id"] for m in messages])
        agent = npc_info["agent"]
        new_msg = {
            "id": msg_id,
            "timestamp": timestamp,
            "world": agent.get("world", "hub"),
            "author": {
                "id": responder_id,
                "name": npc_name,
                "avatar": agent.get("avatar", "🤖"),
                "type": "agent"
            },
            "content": response_text,
            "type": "chat"
        }
        messages.append(new_msg)

        # Build corresponding action
        action_id = get_next_id("action-", [a["id"] for a in actions])
        new_action = {
            "id": action_id,
            "timestamp": timestamp,
            "agentId": responder_id,
            "type": "chat",
            "world": agent.get("world", "hub"),
            "data": {
                "message": response_text,
                "respondingTo": trigger["id"]
            }
        }
        actions.append(new_action)
        responses_added += 1

    if responses_added == 0:
        print("  No responses generated.")
        if messages:
            set_last_seen_msg_id(messages[-1]["id"])
        return

    if dry_run:
        print(f"\n🏁 Dry run complete. {responses_added} response(s) would be added.")
        return

    # Trim to last 100
    messages = messages[-100:]
    actions = actions[-100:]

    # Save
    chat_data["messages"] = messages
    chat_data["_meta"]["lastUpdate"] = timestamp
    chat_data["_meta"]["messageCount"] = len(messages)
    save_json(STATE_DIR / "chat.json", chat_data)

    actions_data["actions"] = actions
    actions_data["_meta"]["lastUpdate"] = timestamp
    actions_data["_meta"]["lastProcessedId"] = actions[-1]["id"]
    save_json(STATE_DIR / "actions.json", actions_data)

    # Update cursor
    set_last_seen_msg_id(messages[-1]["id"])

    # Git commit + push
    print(f"\n📦 Committing {responses_added} NPC response(s)...")
    subprocess.run(["git", "add", "state/chat.json", "state/actions.json"],
                    cwd=BASE_DIR, capture_output=True)
    npc_names = set()
    for msg in messages[-responses_added:]:
        npc_names.add(msg["author"]["name"])
    commit_msg = f"[state] NPC responses: {', '.join(npc_names)}"
    subprocess.run(["git", "commit", "-m", commit_msg],
                    cwd=BASE_DIR, capture_output=True)
    result = subprocess.run(["git", "push"],
                            cwd=BASE_DIR, capture_output=True, text=True)
    if result.returncode == 0:
        print(f"✅ Pushed! {commit_msg}")
    else:
        print(f"⚠️ Push failed: {result.stderr[:200]}")


def main():
    parser = argparse.ArgumentParser(description="Autonomous NPC Conversationalist")
    parser.add_argument("--watch", action="store_true",
                        help=f"Poll every {POLL_INTERVAL}s")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview responses without committing")
    parser.add_argument("--interval", type=int, default=POLL_INTERVAL,
                        help="Poll interval in seconds (default: 30)")
    args = parser.parse_args()

    print("🧠 NPC Agent — Autonomous Conversationalist")
    print(f"   Model: {MODEL} via GitHub Models API")
    print(f"   Mode: {'👀 watch' if args.watch else '🔄 single pass'}"
          f"{'  (dry run)' if args.dry_run else ''}")
    print()

    if args.watch:
        print(f"   Polling every {args.interval}s. Ctrl+C to stop.\n")
        while True:
            try:
                run_once(dry_run=args.dry_run)
                time.sleep(args.interval)
            except KeyboardInterrupt:
                print("\n👋 NPC Agent stopped.")
                break
    else:
        run_once(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
