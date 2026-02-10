#!/usr/bin/env python3
"""
RAPPterverse Action Validator
Validates PRs that modify state files. Runs in GitHub Actions.
Exit 0 = valid (auto-merge), Exit 1 = invalid (reject).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
STATE_DIR = BASE_DIR / "state"

WORLD_BOUNDS = {
    "hub": {"x": (-15, 15), "z": (-15, 15)},
    "arena": {"x": (-12, 12), "z": (-12, 12)},
    "marketplace": {"x": (-15, 15), "z": (-15, 15)},
    "gallery": {"x": (-12, 12), "z": (-12, 15)},
    "dungeon": {"x": (-12, 12), "z": (-12, 12)},
}

VALID_ACTION_TYPES = {
    "move", "chat", "emote", "spawn", "despawn",
    "interact", "trade_offer", "trade_accept", "trade_decline",
    "battle_challenge", "battle_action", "place_object",
    "teach",
}

VALID_EMOTES = {"wave", "dance", "bow", "clap", "think", "celebrate", "cheer", "nod"}


def parse_timestamp(ts: str) -> datetime | None:
    """Parse ISO-8601 timestamp, returning None on failure."""
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None

errors = []
summary_lines = []


def error(msg: str):
    errors.append(msg)


def info(msg: str):
    summary_lines.append(msg)


def load_json(path: Path) -> dict | None:
    """Load and parse JSON, returning None on failure."""
    try:
        with open(path) as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        error(f"`{path.name}`: Invalid JSON — {e}")
        return None
    except FileNotFoundError:
        error(f"`{path.name}`: File not found")
        return None


def get_changed_files() -> list[str]:
    """Get list of files changed vs main."""
    result = subprocess.run(
        ["git", "diff", "--name-only", "origin/main...HEAD"],
        capture_output=True, text=True, cwd=BASE_DIR.parent
    )
    return [f for f in result.stdout.strip().split("\n") if f]


def validate_position(pos: dict, world: str, context: str):
    """Check position is within world bounds."""
    bounds = WORLD_BOUNDS.get(world)
    if not bounds:
        error(f"{context}: Unknown world `{world}`")
        return
    x, z = pos.get("x", 0), pos.get("z", 0)
    if not (bounds["x"][0] <= x <= bounds["x"][1]):
        error(f"{context}: x={x} out of bounds for {world} ({bounds['x'][0]} to {bounds['x'][1]})")
    if not (bounds["z"][0] <= z <= bounds["z"][1]):
        error(f"{context}: z={z} out of bounds for {world} ({bounds['z'][0]} to {bounds['z'][1]})")


def validate_agents(data: dict):
    """Validate agents.json structure."""
    if "agents" not in data:
        error("`agents.json`: Missing `agents` array")
        return
    if not isinstance(data["agents"], list):
        error("`agents.json`: `agents` must be an array")
        return

    seen_ids = set()
    for agent in data["agents"]:
        aid = agent.get("id")
        if not aid:
            error("`agents.json`: Agent missing `id`")
            continue
        if aid in seen_ids:
            error(f"`agents.json`: Duplicate agent ID `{aid}`")
        seen_ids.add(aid)

        for field in ("name", "world", "position", "status"):
            if field not in agent:
                error(f"`agents.json`: Agent `{aid}` missing `{field}`")

        world = agent.get("world", "hub")
        pos = agent.get("position", {})
        if pos:
            validate_position(pos, world, f"Agent `{aid}`")

    if "_meta" not in data:
        error("`agents.json`: Missing `_meta`")
    elif data["_meta"].get("agentCount") != len(data["agents"]):
        error(
            f"`agents.json`: `_meta.agentCount` is {data['_meta'].get('agentCount')} "
            f"but actual count is {len(data['agents'])}"
        )

    info(f"Agents: {len(data['agents'])} total, IDs unique, positions in bounds")


def validate_actions(data: dict, agent_ids: set):
    """Validate actions.json structure."""
    if "actions" not in data:
        error("`actions.json`: Missing `actions` array")
        return

    actions = data["actions"]

    # Duplicate ID detection (full list)
    seen_ids: set[str] = set()
    for action in actions:
        aid = action.get("id")
        if aid:
            if aid in seen_ids:
                error(f"`actions.json`: Duplicate action ID `{aid}`")
            seen_ids.add(aid)

    # Timestamp ordering (full list — must be monotonically non-decreasing)
    prev_ts: datetime | None = None
    for action in actions:
        ts_str = action.get("timestamp")
        if ts_str:
            ts = parse_timestamp(ts_str)
            if ts is None:
                error(f"`actions.json`: Action `{action.get('id')}` has invalid timestamp `{ts_str}`")
            elif prev_ts and ts < prev_ts:
                error(
                    f"`actions.json`: Timestamp out of order — "
                    f"`{action.get('id')}` ({ts_str}) is before previous action"
                )
            prev_ts = ts

    # Detailed validation on recent actions
    for action in actions[-10:]:
        aid = action.get("id")
        if not aid:
            error("`actions.json`: Action missing `id`")
            continue

        for field in ("timestamp", "agentId", "type", "world", "data"):
            if field not in action:
                error(f"`actions.json`: Action `{aid}` missing `{field}`")

        if action.get("agentId") and action["agentId"] not in agent_ids:
            error(f"`actions.json`: Action `{aid}` references unknown agent `{action['agentId']}`")

        action_type = action.get("type")
        if action_type and action_type not in VALID_ACTION_TYPES:
            error(f"`actions.json`: Action `{aid}` has invalid type `{action_type}`")

        world = action.get("world")
        if world and world not in WORLD_BOUNDS:
            error(f"`actions.json`: Action `{aid}` references unknown world `{world}`")

        # Validate move positions
        if action_type == "move":
            move_data = action.get("data", {})
            w = action.get("world", "hub")
            if "to" in move_data:
                validate_position(move_data["to"], w, f"Action `{aid}` move target")
            if "from" in move_data:
                validate_position(move_data["from"], w, f"Action `{aid}` move origin")

        # Validate emotes
        if action_type == "emote":
            emote = action.get("data", {}).get("emote")
            if emote and emote not in VALID_EMOTES:
                error(f"`actions.json`: Action `{aid}` has invalid emote `{emote}`")

    info(f"Actions: {len(actions)} total, timestamps ordered, IDs unique, recent entries validated")


def validate_chat(data: dict, agent_ids: set):
    """Validate chat.json structure."""
    if "messages" not in data:
        error("`chat.json`: Missing `messages` array")
        return

    messages = data["messages"]

    # Duplicate message ID detection
    seen_ids: set[str] = set()
    for msg in messages:
        mid = msg.get("id")
        if mid:
            if mid in seen_ids:
                error(f"`chat.json`: Duplicate message ID `{mid}`")
            seen_ids.add(mid)

    # Timestamp ordering
    prev_ts: datetime | None = None
    for msg in messages:
        ts_str = msg.get("timestamp")
        if ts_str:
            ts = parse_timestamp(ts_str)
            if ts is None:
                error(f"`chat.json`: Message `{msg.get('id')}` has invalid timestamp `{ts_str}`")
            elif prev_ts and ts < prev_ts:
                error(
                    f"`chat.json`: Timestamp out of order — "
                    f"`{msg.get('id')}` ({ts_str}) is before previous message"
                )
            prev_ts = ts

    for msg in messages[-10:]:  # Detailed validation on recent messages
        mid = msg.get("id")
        if not mid:
            error("`chat.json`: Message missing `id`")
            continue

        for field in ("timestamp", "author", "content", "world"):
            if field not in msg:
                error(f"`chat.json`: Message `{mid}` missing `{field}`")

        author = msg.get("author", {})
        if not author.get("id"):
            error(f"`chat.json`: Message `{mid}` author missing `id`")
        if not author.get("name"):
            error(f"`chat.json`: Message `{mid}` author missing `name`")

        world = msg.get("world")
        if world and world not in WORLD_BOUNDS:
            error(f"`chat.json`: Message `{mid}` references unknown world `{world}`")

        content = msg.get("content", "")
        if len(content) > 500:
            error(f"`chat.json`: Message `{mid}` content exceeds 500 chars ({len(content)})")

    info(f"Chat: {len(messages)} messages, timestamps ordered, IDs unique")


def validate_state_file(filename: str, data: dict, agent_ids: set):
    """Route validation by file name."""
    if filename == "agents.json":
        validate_agents(data)
    elif filename == "actions.json":
        validate_actions(data, agent_ids)
    elif filename == "chat.json":
        validate_chat(data, agent_ids)
    elif filename == "trades.json":
        validate_trades(data, agent_ids)
    elif filename == "inventory.json":
        validate_inventory(data, agent_ids)
    elif filename == "npcs.json":
        validate_npcs(data)
    elif filename == "game_state.json":
        if "_meta" not in data:
            error(f"`{filename}`: Missing `_meta`")
        info(f"`{filename}`: JSON valid")


def validate_trades(data: dict, agent_ids: set):
    """Validate trades.json — agent references and structure."""
    if "_meta" not in data:
        error("`trades.json`: Missing `_meta`")

    for trade in data.get("activeTrades", []):
        tid = trade.get("id", "unknown")
        for field in ("id", "timestamp", "status"):
            if field not in trade:
                error(f"`trades.json`: Active trade `{tid}` missing `{field}`")

        offerer = trade.get("offeredBy") or trade.get("agentId")
        target = trade.get("targetAgentId")
        if offerer and offerer not in agent_ids:
            error(f"`trades.json`: Trade `{tid}` offerer `{offerer}` not in agents")
        if target and target not in agent_ids:
            error(f"`trades.json`: Trade `{tid}` target `{target}` not in agents")

    info(f"Trades: {len(data.get('activeTrades', []))} active, "
         f"{len(data.get('completedTrades', []))} completed")


def validate_inventory(data: dict, agent_ids: set):
    """Validate inventory.json — agent references and item structure."""
    if "_meta" not in data:
        error("`inventory.json`: Missing `_meta`")

    inventories = data.get("inventories", {})
    valid_rarities = {"common", "rare", "epic", "holographic"}

    for agent_id, inv in inventories.items():
        if agent_id not in agent_ids:
            error(f"`inventory.json`: Inventory for unknown agent `{agent_id}`")

        for item in inv.get("items", []):
            if not item.get("id"):
                error(f"`inventory.json`: Item in `{agent_id}` inventory missing `id`")
            rarity = item.get("rarity")
            if rarity and rarity not in valid_rarities:
                error(f"`inventory.json`: Item `{item.get('id')}` has invalid rarity `{rarity}`")

    info(f"Inventory: {len(inventories)} agent(s) with items")


def validate_npcs(data: dict):
    """Validate npcs.json — needs range, world refs, positions."""
    if "_meta" not in data:
        error("`npcs.json`: Missing `_meta`")

    for npc in data.get("npcs", []):
        nid = npc.get("id", "unknown")

        world = npc.get("world")
        if world and world not in WORLD_BOUNDS:
            error(f"`npcs.json`: NPC `{nid}` in unknown world `{world}`")

        pos = npc.get("position")
        if pos and world:
            validate_position(pos, world, f"NPC `{nid}`")

        # Needs must be 0–100
        for need_name, value in npc.get("needs", {}).items():
            if not isinstance(value, (int, float)) or value < 0 or value > 100:
                error(f"`npcs.json`: NPC `{nid}` need `{need_name}` = {value} (must be 0–100)")

    info(f"NPCs: {len(data.get('npcs', []))} total, needs/positions validated")


# ---------------------------------------------------------------------------
# Full cross-file consistency audit (--audit mode)
# ---------------------------------------------------------------------------

def audit_state_consistency():
    """
    Deep audit of all state files for internal consistency.
    Checks cross-file references, data drift, and invariant violations.
    """
    info("=" * 50)
    info("FULL STATE CONSISTENCY AUDIT")
    info("=" * 50)

    agents_data = load_json(STATE_DIR / "agents.json")
    actions_data = load_json(STATE_DIR / "actions.json")
    chat_data = load_json(STATE_DIR / "chat.json")
    trades_data = load_json(STATE_DIR / "trades.json")
    inventory_data = load_json(STATE_DIR / "inventory.json")
    npcs_data = load_json(STATE_DIR / "npcs.json")
    game_state = load_json(STATE_DIR / "game_state.json")

    if not agents_data:
        error("Cannot audit: agents.json failed to load")
        return

    agent_ids = {a["id"] for a in agents_data.get("agents", []) if "id" in a}
    agent_worlds = {a["id"]: a.get("world") for a in agents_data.get("agents", []) if "id" in a}
    agent_positions = {a["id"]: a.get("position", {}) for a in agents_data.get("agents", []) if "id" in a}

    # --- 1. Validate all individual files ---
    validate_agents(agents_data)
    if actions_data:
        validate_actions(actions_data, agent_ids)
    if chat_data:
        validate_chat(chat_data, agent_ids)
    if trades_data:
        validate_trades(trades_data, agent_ids)
    if inventory_data:
        validate_inventory(inventory_data, agent_ids)
    if npcs_data:
        validate_npcs(npcs_data)

    # --- 2. Cross-file: agent positions match last move action ---
    if actions_data:
        last_move: dict[str, dict] = {}
        for action in actions_data.get("actions", []):
            if action.get("type") == "move" and action.get("agentId"):
                to_pos = action.get("data", {}).get("to")
                if to_pos:
                    last_move[action["agentId"]] = {
                        "position": to_pos,
                        "world": action.get("world"),
                        "action_id": action.get("id"),
                    }

        for aid, move_info in last_move.items():
            if aid not in agent_positions:
                continue
            current = agent_positions[aid]
            expected = move_info["position"]
            if (current.get("x") != expected.get("x") or
                    current.get("z") != expected.get("z")):
                error(
                    f"Position drift: Agent `{aid}` is at "
                    f"({current.get('x')}, {current.get('z')}) but last move "
                    f"`{move_info['action_id']}` sent them to "
                    f"({expected.get('x')}, {expected.get('z')})"
                )

            if agent_worlds.get(aid) != move_info.get("world"):
                error(
                    f"World drift: Agent `{aid}` is in `{agent_worlds.get(aid)}` "
                    f"but last move `{move_info['action_id']}` was in `{move_info['world']}`"
                )

        info("Cross-check: agent positions vs last move actions")

    # --- 3. NPC/Agent ID overlap check ---
    if npcs_data:
        npc_ids = {n["id"] for n in npcs_data.get("npcs", []) if "id" in n}
        orphan_npcs = npc_ids - agent_ids
        if orphan_npcs:
            for nid in sorted(orphan_npcs):
                error(f"NPC `{nid}` exists in npcs.json but not in agents.json")

        # NPC world consistency: npc world should match agent world
        npc_worlds = {n["id"]: n.get("world") for n in npcs_data.get("npcs", []) if "id" in n}
        for nid, npc_world in npc_worlds.items():
            agent_world = agent_worlds.get(nid)
            if agent_world and npc_world and agent_world != npc_world:
                error(
                    f"World mismatch: NPC `{nid}` is in `{npc_world}` (npcs.json) "
                    f"but `{agent_world}` (agents.json)"
                )

        info("Cross-check: NPC↔Agent consistency")

    # --- 4. Game state world population vs actual agents ---
    if game_state:
        world_populations: dict[str, int] = {}
        for agent in agents_data.get("agents", []):
            w = agent.get("world")
            if w:
                world_populations[w] = world_populations.get(w, 0) + 1

        for world_name, world_data in game_state.get("worlds", {}).items():
            reported = world_data.get("population", 0)
            actual = world_populations.get(world_name, 0)
            if reported != 0 and reported != actual:
                error(
                    f"Population drift: `{world_name}` reports {reported} "
                    f"but {actual} agents are actually there"
                )

        info("Cross-check: game_state populations vs agents")

    # --- 5. _meta.lastUpdate freshness ---
    meta_timestamps: dict[str, str] = {}
    for name, data in [
        ("agents.json", agents_data), ("actions.json", actions_data),
        ("chat.json", chat_data), ("trades.json", trades_data),
        ("inventory.json", inventory_data), ("npcs.json", npcs_data),
    ]:
        if data and "_meta" in data:
            meta_timestamps[name] = data["_meta"].get("lastUpdate", "")

    if meta_timestamps:
        newest = max(
            (parse_timestamp(ts) for ts in meta_timestamps.values() if parse_timestamp(ts)),
            default=None,
        )
        oldest = min(
            (parse_timestamp(ts) for ts in meta_timestamps.values() if parse_timestamp(ts)),
            default=None,
        )
        if newest and oldest:
            drift_hours = (newest - oldest).total_seconds() / 3600
            if drift_hours > 168:  # 1 week
                error(
                    f"Stale data: _meta.lastUpdate spans {drift_hours:.0f} hours across state files "
                    f"(oldest: {oldest.isoformat()}, newest: {newest.isoformat()})"
                )
            info(f"Meta timestamps span {drift_hours:.1f} hours")

    info("State consistency audit complete")


def audit_pr_drift():
    """
    Compare current state/ against the last 5 merged PRs.
    Detects if state has drifted from what PRs intended.
    """
    info("=" * 50)
    info("PR DRIFT DETECTION (last 5 merged PRs)")
    info("=" * 50)

    # Get last 5 merged PRs that touched state/
    result = subprocess.run(
        ["gh", "pr", "list", "--state", "merged", "--limit", "5",
         "--search", "state/", "--json",
         "number,title,mergedAt,headRefName,mergeCommitSha"],
        capture_output=True, text=True, cwd=BASE_DIR
    )

    if result.returncode != 0:
        # Try without gh CLI (running locally without auth)
        info("Could not fetch PRs via `gh` CLI — falling back to git log")
        audit_git_drift()
        return

    try:
        prs = json.loads(result.stdout)
    except json.JSONDecodeError:
        info("No merged PRs found or JSON parse error")
        return

    if not prs:
        info("No recent merged PRs touching state/")
        return

    for pr in prs:
        pr_num = pr.get("number")
        pr_title = pr.get("title", "untitled")
        merge_sha = pr.get("mergeCommitSha")
        merged_at = pr.get("mergedAt", "")

        info(f"PR #{pr_num}: {pr_title} (merged {merged_at[:10]})")

        if not merge_sha:
            continue

        # Get state files changed in this PR's merge commit
        diff_result = subprocess.run(
            ["git", "diff", "--name-only", f"{merge_sha}^", merge_sha, "--", "state/"],
            capture_output=True, text=True, cwd=BASE_DIR
        )
        changed_state_files = [f for f in diff_result.stdout.strip().split("\n") if f]

        if not changed_state_files:
            continue

        # For each file changed in the PR, compare what the PR set vs current HEAD
        for filepath in changed_state_files:
            # Get the file as the PR left it
            pr_content = subprocess.run(
                ["git", "show", f"{merge_sha}:{filepath}"],
                capture_output=True, text=True, cwd=BASE_DIR
            )
            if pr_content.returncode != 0:
                continue

            # Get the current file
            current_path = BASE_DIR / filepath
            if not current_path.exists():
                error(f"PR #{pr_num} modified `{filepath}` but file no longer exists")
                continue

            try:
                pr_data = json.loads(pr_content.stdout)
                current_data = json.loads(current_path.read_text())
            except json.JSONDecodeError:
                continue

            # Check for unexpected removals (items in PR version but missing now)
            check_drift(filepath, pr_data, current_data, pr_num)

    info("PR drift analysis complete")


def check_drift(filepath: str, pr_data: dict, current_data: dict, pr_num: int):
    """Compare PR-era state to current state for unexpected drift."""
    filename = filepath.split("/")[-1]

    if filename == "agents.json":
        pr_agents = {a["id"] for a in pr_data.get("agents", []) if "id" in a}
        curr_agents = {a["id"] for a in current_data.get("agents", []) if "id" in a}
        removed = pr_agents - curr_agents
        if removed:
            error(f"Drift since PR #{pr_num}: Agents removed without trace: {', '.join(sorted(removed))}")

    elif filename == "actions.json":
        pr_action_ids = {a["id"] for a in pr_data.get("actions", []) if "id" in a}
        curr_action_ids = {a["id"] for a in current_data.get("actions", []) if "id" in a}
        lost = pr_action_ids - curr_action_ids
        # Only flag if recent actions disappeared (trimming old ones is expected)
        if lost and len(current_data.get("actions", [])) < 100:
            error(f"Drift since PR #{pr_num}: {len(lost)} action(s) disappeared unexpectedly")

    elif filename == "chat.json":
        pr_msg_ids = {m["id"] for m in pr_data.get("messages", []) if "id" in m}
        curr_msg_ids = {m["id"] for m in current_data.get("messages", []) if "id" in m}
        lost = pr_msg_ids - curr_msg_ids
        if lost and len(current_data.get("messages", [])) < 100:
            error(f"Drift since PR #{pr_num}: {len(lost)} chat message(s) disappeared unexpectedly")


def audit_git_drift():
    """Fallback: use git log to find recent state-touching commits."""
    result = subprocess.run(
        ["git", "log", "--oneline", "-5", "--", "state/"],
        capture_output=True, text=True, cwd=BASE_DIR
    )
    commits = [line.split()[0] for line in result.stdout.strip().split("\n") if line]

    if not commits:
        info("No recent commits touching state/")
        return

    for sha in commits:
        msg_result = subprocess.run(
            ["git", "log", "--format=%s", "-1", sha],
            capture_output=True, text=True, cwd=BASE_DIR
        )
        commit_msg = msg_result.stdout.strip()
        info(f"Commit {sha}: {commit_msg}")

        diff_result = subprocess.run(
            ["git", "diff", "--name-only", f"{sha}^", sha, "--", "state/"],
            capture_output=True, text=True, cwd=BASE_DIR
        )
        changed = [f for f in diff_result.stdout.strip().split("\n") if f]

        for filepath in changed:
            pr_content = subprocess.run(
                ["git", "show", f"{sha}:{filepath}"],
                capture_output=True, text=True, cwd=BASE_DIR
            )
            if pr_content.returncode != 0:
                continue

            current_path = BASE_DIR / filepath
            if not current_path.exists():
                error(f"Commit {sha} modified `{filepath}` but file no longer exists")
                continue

            try:
                commit_data = json.loads(pr_content.stdout)
                current_data = json.loads(current_path.read_text())
            except json.JSONDecodeError:
                continue

            check_drift(filepath, commit_data, current_data, sha)


def main():
    audit_mode = "--audit" in sys.argv

    if audit_mode:
        # Full cross-file consistency audit + PR drift detection
        audit_state_consistency()
        audit_pr_drift()

        summary = "\n".join(f"- {line}" for line in summary_lines)
        set_output("summary", summary)

        if errors:
            error_text = "\n".join(f"- {e}" for e in errors)
            set_output("errors", error_text)
            print(f"\n❌ State audit found {len(errors)} issue(s):\n")
            for e in errors:
                print(f"  ✗ {e}")
            sys.exit(1)
        else:
            print(f"\n✅ State is internally consistent:\n")
            for line in summary_lines:
                print(f"  ✓ {line}")
            sys.exit(0)

    # --- Standard PR validation mode ---
    changed_files = get_changed_files()
    rappterverse_files = [f for f in changed_files if f.startswith("state/") or f.startswith("worlds/") or f.startswith("feed/")]

    if not rappterverse_files:
        info("No rappterverse files changed")
        set_output("summary", "No rappterverse state files modified.")
        sys.exit(0)

    info(f"Changed files: {', '.join(rappterverse_files)}")

    # Collect agent IDs for cross-validation
    agents_data = load_json(STATE_DIR / "agents.json")
    agent_ids = set()
    if agents_data:
        agent_ids = {a["id"] for a in agents_data.get("agents", []) if "id" in a}

    # Validate each changed state file
    for filepath in rappterverse_files:
        parts = filepath.split("/")
        if len(parts) >= 2 and parts[0] == "state":
            filename = parts[1]
            data = load_json(STATE_DIR / filename)
            if data is not None:
                validate_state_file(filename, data, agent_ids)

        elif len(parts) >= 3 and parts[0] == "worlds":
            # World config files — just validate JSON
            full_path = BASE_DIR / filepath
            data = load_json(full_path)
            if data is not None:
                info(f"`{filepath}`: JSON valid")

    # Output results
    summary = "\n".join(f"- {line}" for line in summary_lines)
    set_output("summary", summary)

    if errors:
        error_text = "\n".join(f"- {e}" for e in errors)
        set_output("errors", error_text)
        print(f"\n❌ Validation failed with {len(errors)} error(s):\n")
        for e in errors:
            print(f"  ✗ {e}")
        sys.exit(1)
    else:
        print(f"\n✅ Validation passed:\n")
        for line in summary_lines:
            print(f"  ✓ {line}")
        sys.exit(0)


def set_output(name: str, value: str):
    """Set GitHub Actions output variable."""
    output_file = os.environ.get("GITHUB_OUTPUT")
    if output_file:
        with open(output_file, "a") as f:
            # Use delimiter for multiline values
            f.write(f"{name}<<EOF\n{value}\nEOF\n")
    else:
        # Running locally
        print(f"[OUTPUT] {name}: {value}")


if __name__ == "__main__":
    main()
