#!/usr/bin/env python3
"""
RAPPterverse Action Validator
Validates PRs that modify state files. Runs in GitHub Actions.
Exit 0 = valid (auto-merge), Exit 1 = invalid (reject).
"""

from __future__ import annotations

import json
import math
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(
    os.environ.get("VALIDATION_REPO_ROOT", Path(__file__).parent.parent)
).resolve()
STATE_DIR = BASE_DIR / "state"
WORLDS_DIR = BASE_DIR / "worlds"
FEED_DIR = BASE_DIR / "feed"


def _load_world_bounds() -> dict:
    """Load world bounds from worlds/*/config.json (single source of truth)."""
    bounds = {}
    if WORLDS_DIR.is_dir():
        for world_dir in sorted(WORLDS_DIR.iterdir()):
            if not world_dir.is_dir():
                continue
            config_file = world_dir / "config.json"
            if config_file.exists():
                try:
                    with open(config_file) as f:
                        config = json.load(f)
                    b = config.get("bounds", {})
                    if b:
                        bounds[world_dir.name] = {
                            "x": tuple(b.get("x", [-15, 15])),
                            "z": tuple(b.get("z", [-15, 15])),
                        }
                except (json.JSONDecodeError, OSError):
                    pass
    # Fallback if no config files found (e.g. running in CI without full checkout)
    if not bounds:
        bounds = {
            "hub": {"x": (-15, 15), "z": (-15, 15)},
            "arena": {"x": (-12, 12), "z": (-12, 12)},
            "marketplace": {"x": (-15, 15), "z": (-15, 15)},
            "gallery": {"x": (-12, 12), "z": (-12, 15)},
            "dungeon": {"x": (-12, 12), "z": (-12, 12)},
        }
    return bounds


WORLD_BOUNDS = _load_world_bounds()

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


def reject_json_constant(value: str):
    raise ValueError(f"non-standard numeric constant {value}")


def validate_finite_numbers(value: object, context: str):
    if isinstance(value, float) and not math.isfinite(value):
        error(f"`{context}`: non-finite numeric value")
    elif isinstance(value, dict):
        for key, child in value.items():
            validate_finite_numbers(child, f"{context}/{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            validate_finite_numbers(child, f"{context}/{index}")


def load_json(path: Path) -> dict | None:
    """Load and parse JSON, returning None on failure."""
    try:
        with open(path) as f:
            return json.load(f, parse_constant=reject_json_constant)
    except (json.JSONDecodeError, ValueError) as e:
        error(f"`{path.name}`: Invalid JSON — {e}")
        return None
    except FileNotFoundError:
        error(f"`{path.name}`: File not found")
        return None


def get_changed_files() -> list[str]:
    """Get list of files changed vs main."""
    base_ref = os.environ.get("VALIDATION_BASE_SHA", "origin/main")
    head_ref = os.environ.get("VALIDATION_HEAD_SHA", "HEAD")
    result = subprocess.run(
        ["git", "diff", "--name-only", f"{base_ref}...{head_ref}", "--"],
        capture_output=True, text=True, cwd=BASE_DIR
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or f"git exited with status {result.returncode}"
        raise RuntimeError(f"Unable to determine changed files: {detail}")
    return [f for f in result.stdout.strip().split("\n") if f]


def load_base_json(filepath: str):
    """Load a file's content from origin/main for comparison."""
    base_ref = os.environ.get("VALIDATION_BASE_SHA", "origin/main")
    result = subprocess.run(
        ["git", "show", f"{base_ref}:{filepath}"],
        capture_output=True, text=True, cwd=BASE_DIR
    )
    if result.returncode == 0:
        try:
            return json.loads(result.stdout, parse_constant=reject_json_constant)
        except (json.JSONDecodeError, ValueError):
            return None
    return None


def trusted_automation_authors() -> set[str]:
    """Return base-controlled identities allowed to act for system agents."""
    owner = os.environ.get("REPOSITORY_OWNER", "kody-w")
    configured = os.environ.get("TRUSTED_AUTOMATION_AUTHORS", "")
    return {owner, "github-actions[bot]"} | {
        author.strip() for author in configured.split(",") if author.strip()
    }


def authorize_actor(
    actor_id: str | None,
    agents_by_id: dict,
    pr_author: str,
    context: str,
) -> bool:
    """Bind a semantic actor to the GitHub identity controlling that agent."""
    if not actor_id:
        error(f"{context}: Missing actor ID")
        return False
    agent = agents_by_id.get(actor_id)
    if not agent:
        error(f"{context}: Unknown actor `{actor_id}`")
        return False

    controller = agent.get("controller", "system")
    if controller == "system":
        if pr_author not in trusted_automation_authors():
            error(f"{context}: `{actor_id}` is system-controlled; `{pr_author}` is not trusted automation")
            return False
    elif controller != pr_author:
        error(f"{context}: `{actor_id}` is controlled by `{controller}`, not `{pr_author}`")
        return False
    return True


def validate_agent_consent(current_agents: list, pr_author: str):
    """Enforce controller ownership for additions, modifications, and deletions."""
    if not pr_author:
        error("Agent authorization requires PR_AUTHOR")
        return

    base_data = load_base_json("state/agents.json")
    if not base_data:
        error("`agents.json`: Unable to load trusted base state for authorization")
        return

    base_agents = {a["id"]: a for a in base_data.get("agents", []) if "id" in a}
    current_by_id = {a["id"]: a for a in current_agents if "id" in a}

    for aid in base_agents.keys() - current_by_id.keys():
        controller = base_agents[aid].get("controller", "system")
        if controller == "system":
            if pr_author not in trusted_automation_authors():
                error(f"`agents.json`: Only trusted automation may delete system agent `{aid}`")
        elif controller != pr_author:
            error(f"`agents.json`: Only controller `{controller}` may delete agent `{aid}`")

    for agent in current_agents:
        aid = agent.get("id")
        if not aid:
            continue

        base_agent = base_agents.get(aid)
        if not base_agent:
            controller = agent.get("controller")
            if controller == "system":
                if pr_author not in trusted_automation_authors():
                    error(f"`agents.json`: Only trusted automation may create system agent `{aid}`")
            elif controller != pr_author:
                error(
                    f"`agents.json`: New agent `{aid}` must set controller to PR author "
                    f"`{pr_author}`"
                )
            continue

        # Check if this agent was actually modified
        if agent == base_agent:
            continue

        controller = base_agent.get("controller", "system")
        if agent.get("controller", "system") != controller:
            if pr_author not in trusted_automation_authors():
                error(f"`agents.json`: Only trusted automation may transfer controller for `{aid}`")
            continue
        if controller == "system":
            if pr_author not in trusted_automation_authors():
                error(f"`agents.json`: Only trusted automation may modify system agent `{aid}`")
        elif pr_author != controller:
            error(
                f"`agents.json`: Agent `{aid}` is controlled by `{controller}`, "
                f"but PR author is `{pr_author}` — consent required"
            )

    info("Consent: agent controller permissions verified")


def validate_append_only_actors(
    filepath: str,
    key: str,
    current_records: list,
    agents_by_id: dict,
    pr_author: str,
) -> list:
    """Reject history rewrites and authorize every newly appended semantic actor."""
    base_data = load_base_json(filepath)
    if not base_data or not isinstance(base_data.get(key), list):
        error(f"`{filepath}`: Unable to load trusted base history")
        return []

    base_records = base_data[key]
    base_by_id = {record.get("id"): record for record in base_records if record.get("id")}
    current_by_id = {record.get("id"): record for record in current_records if record.get("id")}
    base_ids = [record.get("id") for record in base_records if record.get("id")]
    current_ids = [record.get("id") for record in current_records if record.get("id")]
    if len(current_ids) != len(current_records):
        error(f"`{filepath}`: Every record must have an ID")

    retained = [record_id for record_id in current_ids if record_id in base_by_id]
    for record_id in retained:
        if current_by_id[record_id] != base_by_id[record_id]:
            error(f"`{filepath}`: Existing record `{record_id}` is immutable")

    added = [record for record in current_records if record.get("id") not in base_by_id]
    added_ids = [record.get("id") for record in added if record.get("id")]
    expected_ids = (base_ids + added_ids)[-100:]
    if current_ids != expected_ids:
        error(f"`{filepath}`: History must equal the most recent 100 base + appended records")
    for record in added:
        if key == "actions":
            actor_id = record.get("agentId")
        else:
            author = record.get("author", {})
            actor_id = author.get("id") if isinstance(author, dict) else None
        authorize_actor(actor_id, agents_by_id, pr_author, f"`{filepath}` record `{record.get('id')}`")

    info(f"`{filepath}`: {len(added)} new record(s) authorized")
    return added


def validate_feed_authorization(data: dict, agents_by_id: dict, pr_author: str):
    """External authors may only append feed records attributed to themselves."""
    if pr_author in trusted_automation_authors():
        info("`feed/activity.json`: trusted automation authorized")
        return
    base_data = load_base_json("feed/activity.json")
    if not base_data:
        error("`feed/activity.json`: Unable to load trusted base history")
        return

    for key in ("activities", "entries"):
        base_records = base_data.get(key, [])
        current_records = data.get(key, [])
        if current_records[:len(base_records)] != base_records:
            error(f"`feed/activity.json`: External authors may not rewrite `{key}` history")
            continue
        for index, record in enumerate(current_records[len(base_records):], start=len(base_records)):
            author = record.get("author", {})
            actor_id = author.get("id") if isinstance(author, dict) else None
            authorize_actor(
                actor_id,
                agents_by_id,
                pr_author,
                f"`feed/activity.json` {key}[{index}]",
            )


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

        # Validate traits if present
        traits = agent.get("traits")
        if traits is not None:
            if not isinstance(traits, dict):
                error(f"`agents.json`: Agent `{aid}` traits must be a dict, got {type(traits).__name__}")
            else:
                for t_name, t_val in traits.items():
                    if not isinstance(t_val, (int, float)):
                        error(f"`agents.json`: Agent `{aid}` trait `{t_name}` must be numeric")
                    elif not (0 <= t_val <= 1):
                        error(f"`agents.json`: Agent `{aid}` trait `{t_name}` = {t_val} out of range [0, 1]")
                trait_sum = sum(traits.values())
                if traits and abs(trait_sum - 1.0) > 0.05:
                    error(f"`agents.json`: Agent `{aid}` traits sum to {trait_sum:.3f}, expected ~1.0")

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

    # Full retained window validation prevents invalid rows being hidden by
    # appending enough newer records.
    for action in actions:
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
        action_data = action.get("data")
        if "data" in action and not isinstance(action_data, dict):
            error(f"`actions.json`: Action `{aid}` data must be an object")
            action_data = {}
        elif action_data is None:
            action_data = {}

        # Validate move positions
        if action_type == "move":
            move_data = action_data
            w = action.get("world", "hub")
            if "to" in move_data:
                validate_position(move_data["to"], w, f"Action `{aid}` move target")
            if "from" in move_data:
                validate_position(move_data["from"], w, f"Action `{aid}` move origin")

        # Validate emotes
        if action_type == "emote":
            emote = action_data.get("emote")
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

    for msg in messages:
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
    elif filename == "relationships.json":
        validate_relationships(data, agent_ids)
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


def validate_relationships(
    data: dict,
    agent_ids: set,
    *,
    enforce_bonds: bool = False,
):
    edges = data.get("edges")
    if not isinstance(edges, list):
        error("`relationships.json`: Missing `edges` array")
        return
    seen = set()
    expected_bonds = []
    for edge in edges:
        a = edge.get("a")
        b = edge.get("b")
        pair = (a, b)
        if a not in agent_ids or b not in agent_ids:
            error(f"`relationships.json`: Unknown endpoint in `{a}` ↔ `{b}`")
        if not a or not b or a >= b:
            error(f"`relationships.json`: Non-canonical pair `{a}` ↔ `{b}`")
        if pair in seen:
            error(f"`relationships.json`: Duplicate pair `{a}` ↔ `{b}`")
        seen.add(pair)
        score = edge.get("score")
        if not isinstance(score, (int, float)) or not 0 <= score <= 100:
            error(f"`relationships.json`: Invalid score for `{a}` ↔ `{b}`")
        if parse_timestamp(edge.get("lastInteraction", "")) is None:
            error(f"`relationships.json`: Invalid lastInteraction for `{a}` ↔ `{b}`")
        if isinstance(score, (int, float)) and score >= 2:
            expected_bonds.append({
                "agents": [a, b],
                "strength": score,
                "type": "social",
                "lastInteraction": edge.get("lastInteraction", ""),
            })
    if enforce_bonds and data.get("bonds", []) != expected_bonds:
        error("`relationships.json`: `bonds` must be derived exactly from `edges`")
    cursor = data.get("_meta", {}).get("decayCursor")
    if cursor is not None and parse_timestamp(cursor) is None:
        error("`relationships.json`: Invalid `_meta.decayCursor`")
    info(f"Relationships: {len(edges)} canonical edges")


def validate_canonical_state():
    """Validate complete canonical files without scoring simulation health."""
    agents_data = load_json(STATE_DIR / "agents.json")
    if not agents_data:
        error("Cannot validate canonical state: agents.json failed to load")
        return
    agent_ids = {
        agent["id"]
        for agent in agents_data.get("agents", [])
        if "id" in agent
    }
    validate_agents(agents_data)
    validate_finite_numbers(agents_data, "state/agents.json")
    for filename in (
        "actions.json",
        "chat.json",
        "trades.json",
        "inventory.json",
        "npcs.json",
        "game_state.json",
        "relationships.json",
    ):
        data = load_json(STATE_DIR / filename)
        if data is None:
            error(f"`{filename}`: failed to load")
        else:
            validate_finite_numbers(data, f"state/{filename}")
            if filename == "relationships.json":
                validate_relationships(data, agent_ids, enforce_bonds=True)
            else:
                validate_state_file(filename, data, agent_ids)

    for world_dir in sorted(WORLDS_DIR.iterdir()):
        objects_path = world_dir / "objects.json"
        if not objects_path.is_file():
            continue
        data = load_json(objects_path)
        if data is None or not isinstance(data.get("objects"), list):
            error(f"`{world_dir.name}/objects.json`: missing objects array")
            continue
        validate_finite_numbers(data, f"worlds/{world_dir.name}/objects.json")
        seen_ids = set()
        for obj in data["objects"]:
            object_id = obj.get("id")
            if not object_id:
                error(f"`{world_dir.name}/objects.json`: object missing id")
            elif object_id in seen_ids:
                error(f"`{world_dir.name}/objects.json`: duplicate object `{object_id}`")
            seen_ids.add(object_id)
            if isinstance(obj.get("position"), dict):
                validate_position(
                    obj["position"],
                    world_dir.name,
                    f"Object `{object_id or 'unknown'}`",
                )
    info("Canonical state files validated")


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


def audit_quality_metrics():
    """Rappterbook-style quality metrics: measure simulation health.

    Computes:
    - Interaction depth (avg relationship score, % with bonds)
    - Author diversity (Gini coefficient of activity distribution)
    - World balance (Shannon entropy of population spread)
    - Engagement velocity (actions/messages in recent window)
    - Trait evolution health (% of agents with evolved traits)
    """
    import math

    info("=" * 50)
    info("SIMULATION QUALITY METRICS")
    info("=" * 50)

    agents_data = load_json(STATE_DIR / "agents.json")
    actions_data = load_json(STATE_DIR / "actions.json")
    chat_data = load_json(STATE_DIR / "chat.json")
    rel_data = load_json(STATE_DIR / "relationships.json")

    agents = agents_data.get("agents", [])
    active = [a for a in agents if a.get("status") == "active"]
    actions = actions_data.get("actions", [])
    messages = chat_data.get("messages", [])
    edges = rel_data.get("edges", [])

    score = 0
    max_score = 0

    # ── 1. Interaction Depth (0-20 points) ──
    max_score += 20
    if edges:
        avg_score = sum(e.get("score", 0) for e in edges) / len(edges)
        strong_bonds = sum(1 for e in edges if e.get("score", 0) >= 51)
        bond_pct = strong_bonds / max(1, len(edges)) * 100

        depth_score = min(20, int(avg_score * 2 + bond_pct * 0.1))
        score += depth_score
        info(f"Interaction depth: avg={avg_score:.1f}, strong bonds={strong_bonds} ({bond_pct:.0f}%) → {depth_score}/20")
    else:
        info("Interaction depth: no relationships yet → 0/20")

    # ── 2. Author Diversity — Gini coefficient (0-20 points) ──
    max_score += 20
    now_utc = datetime.now(timezone.utc)
    recent_cutoff = now_utc.timestamp() - 7 * 24 * 3600

    def is_recent(record: dict) -> bool:
        parsed = parse_timestamp(record.get("timestamp", ""))
        return bool(
            parsed
            and recent_cutoff <= parsed.timestamp() <= now_utc.timestamp() + 300
        )

    active_ids = {agent["id"] for agent in active if agent.get("id")}
    gini = 1.0
    action_counts: dict[str, int] = {agent_id: 0 for agent_id in active_ids}
    recent_action_records = [action for action in actions if is_recent(action)]
    recent_message_records = [message for message in messages if is_recent(message)]
    for a in recent_action_records:
        aid = a.get("agentId", "")
        if aid in action_counts:
            action_counts[aid] = action_counts.get(aid, 0) + 1
    for m in recent_message_records:
        author = m.get("author", {})
        aid = author.get("id", "") if isinstance(author, dict) else str(author)
        if aid in action_counts:
            action_counts[aid] = action_counts.get(aid, 0) + 1

    if len(action_counts) > 1 and sum(action_counts.values()) > 0:
        values = sorted(action_counts.values())
        n = len(values)
        mean = sum(values) / n
        if mean > 0:
            gini = sum(abs(values[i] - values[j]) for i in range(n) for j in range(n)) / (2 * n * n * mean)
        else:
            gini = 0
        # Gini 0 = perfect equality, 1 = total inequality
        diversity_score = max(0, int(20 * (1 - gini)))
        score += diversity_score
        participating = sum(1 for value in values if value > 0)
        info(
            f"Author diversity: Gini={gini:.3f}, "
            f"participating authors={participating}/{len(active_ids)} "
            f"→ {diversity_score}/20"
        )
        if gini > 0.4:
            error(f"High inequality: Gini={gini:.3f} — activity dominated by few agents")
    else:
        info("Author diversity: insufficient data → 0/20")

    # ── 3. World Balance — Shannon entropy (0-20 points) ──
    max_score += 20
    world_pops: dict[str, int] = {}
    for agent in active:
        w = agent.get("world", "hub")
        world_pops[w] = world_pops.get(w, 0) + 1

    if len(world_pops) > 1:
        total_pop = sum(world_pops.values())
        entropy = 0.0
        for w, count in world_pops.items():
            p = count / total_pop
            if p > 0:
                entropy -= p * math.log2(p)
        max_entropy = math.log2(len(world_pops))
        normalized = entropy / max_entropy if max_entropy > 0 else 0
        balance_score = int(20 * normalized)
        score += balance_score
        info(f"World balance: entropy={entropy:.2f}/{max_entropy:.2f} (normalized={normalized:.2f}), worlds={dict(world_pops)} → {balance_score}/20")
        if normalized < 0.5:
            error(f"Population imbalance: most agents concentrated in few worlds")
    else:
        info("World balance: single world → 0/20")

    # ── 4. Engagement Velocity (0-20 points) ──
    max_score += 20
    recent_actions = len(recent_action_records)
    recent_messages = len(recent_message_records)
    velocity = recent_actions + recent_messages

    participating = sum(1 for value in action_counts.values() if value > 0)
    actor_coverage = participating / max(1, len(active_ids))
    velocity_score = min(20, int(velocity * 0.4 * actor_coverage))
    score += velocity_score
    info(
        f"Engagement velocity (7d): {recent_actions} actions + "
        f"{recent_messages} messages, {participating}/{len(active_ids)} actors "
        f"→ {velocity_score}/20"
    )

    # ── 5. Trait Evolution Health (0-20 points) ──
    max_score += 20
    agents_with_traits = sum(1 for a in active if a.get("traits"))
    if active:
        trait_pct = agents_with_traits / len(active) * 100
        drifted = 0
        comparable = 0
        trait_names = {"explorer", "social", "trader", "fighter", "builder"}
        for a in active:
            traits = a.get("traits", {})
            archetype = a.get("archetype")
            if traits and archetype in trait_names:
                comparable += 1
                if any(
                    abs(
                        traits.get(trait, 0)
                        - (0.6 if trait == archetype else 0.1)
                    ) > 0.05
                    for trait in trait_names
                ):
                    drifted += 1

        drift_pct = drifted / max(1, comparable) * 100
        trait_score = min(20, int(trait_pct * 0.1 + drift_pct * 0.1))
        score += trait_score
        info(
            f"Trait evolution: {agents_with_traits}/{len(active)} have traits "
            f"({trait_pct:.0f}%), {drifted}/{comparable} comparable agents "
            f"drifted ({drift_pct:.0f}%) → {trait_score}/20"
        )
    else:
        info("Trait evolution: no active agents → 0/20")

    # ── Summary ──
    gradeable = actor_coverage >= 0.1 and gini <= 0.6
    grade = (
        "INSUFFICIENT"
        if not gradeable
        else "A" if score >= 80
        else "B" if score >= 60
        else "C" if score >= 40
        else "D" if score >= 20
        else "F"
    )
    info(f"\n  SIMULATION QUALITY SCORE: {score}/{max_score} ({grade})")
    info(
        "  "
        + (
            "Insufficient actor coverage for a health grade"
            if not gradeable
            else "Healthy"
            if score >= 60
            else "Needs attention"
            if score >= 30
            else "Critical — simulation may be stale"
        )
    )


def main():
    audit_mode = "--audit" in sys.argv
    canonical_mode = "--validate-state" in sys.argv

    if canonical_mode:
        validate_canonical_state()
        if errors:
            print(f"\n❌ Canonical state validation found {len(errors)} issue(s):")
            for item in errors:
                print(f"  ✗ {item}")
            sys.exit(1)
        print("\n✅ Canonical state files are valid")
        sys.exit(0)

    if audit_mode:
        # Full cross-file consistency audit + PR drift detection + quality metrics
        audit_state_consistency()
        audit_quality_metrics()
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
    try:
        changed_files = get_changed_files()
    except RuntimeError as exc:
        error(str(exc))
        set_output("errors", f"- {exc}")
        set_output("summary", "Validation could not inspect the proposed changes.")
        print(f"\n❌ Validation failed:\n\n  ✗ {exc}")
        sys.exit(1)

    allowed_prefixes = ("state/", "worlds/", "feed/")
    rappterverse_files = [
        f for f in changed_files if f.startswith(allowed_prefixes)
    ]
    unexpected_files = [
        f for f in changed_files if not f.startswith(allowed_prefixes)
    ]
    if unexpected_files:
        error(
            "State action PRs may only modify state/, worlds/, or feed/: "
            + ", ".join(unexpected_files)
        )

    if not rappterverse_files:
        if os.environ.get("VALIDATION_REQUIRE_RELEVANT") == "1":
            error("No state/, worlds/, or feed/ files were found in this state-triggered PR")
        else:
            info("No rappterverse files changed")
            set_output("summary", "No rappterverse state files modified.")
            sys.exit(0)

    info(f"Changed files: {', '.join(rappterverse_files)}")
    pr_author = os.environ.get("PR_AUTHOR", "")
    if (
        os.environ.get("VALIDATION_REQUIRE_AUTH") == "1"
        and pr_author
        and pr_author not in trusted_automation_authors()
    ):
        direct_paths = {
            "state/agents.json",
            "state/actions.json",
            "state/chat.json",
            "feed/activity.json",
        }
        unauthorized_paths = [
            filepath
            for filepath in rappterverse_files
            if filepath not in direct_paths and not filepath.startswith("state/inbox/")
        ]
        if unauthorized_paths:
            error(
                "External authors must use controller-bound direct histories or "
                "state/inbox deltas; unauthorized paths: "
                + ", ".join(unauthorized_paths)
            )

    # Collect agent IDs for cross-validation
    agents_data = load_json(STATE_DIR / "agents.json")
    agent_ids = set()
    if agents_data:
        agent_ids = {a["id"] for a in agents_data.get("agents", []) if "id" in a}

    # Validate each changed state file
    for filepath in rappterverse_files:
        parts = filepath.split("/")
        full_path = BASE_DIR / filepath
        if parts[0] == "state":
            filename = parts[-1]
            data = load_json(full_path)
            if data is not None:
                validate_finite_numbers(data, filepath)
                if len(parts) == 2:
                    validate_state_file(filename, data, agent_ids)
                else:
                    info(f"`{filepath}`: JSON valid")

        elif len(parts) >= 3 and parts[0] == "worlds":
            # World config files — just validate JSON
            data = load_json(full_path)
            if data is not None:
                validate_finite_numbers(data, filepath)
                info(f"`{filepath}`: JSON valid")
        elif parts[0] == "feed":
            data = load_json(full_path)
            if data is not None:
                validate_finite_numbers(data, filepath)
                info(f"`{filepath}`: JSON valid")

    # Actor authorization is semantic: bind every new effect to its controller.
    if os.environ.get("VALIDATION_REQUIRE_AUTH") == "1" and not pr_author:
        error("PR_AUTHOR is required for state authorization")
    if pr_author and agents_data:
        base_agents_data = load_base_json("state/agents.json")
        if not base_agents_data:
            error("Unable to load trusted base agents for actor authorization")
            base_agents_data = {"agents": []}
        agents_by_id = {
            agent["id"]: agent for agent in base_agents_data.get("agents", []) if "id" in agent
        }
        if "state/agents.json" in rappterverse_files:
            for agent in agents_data.get("agents", []):
                if agent.get("id") not in agents_by_id:
                    agents_by_id[agent["id"]] = agent
        if "state/agents.json" in rappterverse_files:
            validate_agent_consent(agents_data.get("agents", []), pr_author)
        if "state/actions.json" in rappterverse_files:
            actions_data = load_json(STATE_DIR / "actions.json")
            if actions_data:
                validate_append_only_actors(
                    "state/actions.json",
                    "actions",
                    actions_data.get("actions", []),
                    agents_by_id,
                    pr_author,
                )
        if "state/chat.json" in rappterverse_files:
            chat_data = load_json(STATE_DIR / "chat.json")
            if chat_data:
                validate_append_only_actors(
                    "state/chat.json",
                    "messages",
                    chat_data.get("messages", []),
                    agents_by_id,
                    pr_author,
                )
        if "feed/activity.json" in rappterverse_files:
            feed_data = load_json(FEED_DIR / "activity.json")
            if feed_data:
                validate_feed_authorization(feed_data, agents_by_id, pr_author)

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
