#!/usr/bin/env python3
"""
RAPPterverse Delta Validator
Validates inbox delta files before merge. Runs in GitHub Actions.
"""

from __future__ import annotations
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(
    os.environ.get("VALIDATION_REPO_ROOT", Path(__file__).parent.parent)
).resolve()
INBOX_DIR = BASE_DIR / "state" / "inbox"
STATE_DIR = BASE_DIR / "state"

VALID_WORLDS = {"hub", "arena", "marketplace", "gallery", "dungeon"}
VALID_ACTION_TYPES = {
    "move", "chat", "emote", "spawn", "despawn",
    "interact", "trade_offer", "trade_accept", "trade_decline",
    "battle_challenge", "battle_action", "place_object", "teach",
}

errors = []


def error(msg: str):
    errors.append(msg)


def valid_timestamp(value: object) -> bool:
    try:
        datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return isinstance(value, str)
    except ValueError:
        return False


def _trusted_automation_authors() -> set[str]:
    owner = os.environ.get("REPOSITORY_OWNER", "kody-w")
    configured = os.environ.get("TRUSTED_AUTOMATION_AUTHORS", "")
    return {owner, "github-actions[bot]"} | {
        author.strip() for author in configured.split(",") if author.strip()
    }


def _load_base_agents() -> dict | None:
    base_ref = os.environ.get("VALIDATION_BASE_SHA", "origin/main")
    result = subprocess.run(
        ["git", "show", f"{base_ref}:state/agents.json"],
        capture_output=True,
        text=True,
        cwd=BASE_DIR,
    )
    if result.returncode != 0:
        return None
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None
    return {agent["id"]: agent for agent in data.get("agents", []) if "id" in agent}


def validate_delta_authorization(delta: dict, path: Path):
    """Bind a delta and every embedded identity to the trusted PR author."""
    if os.environ.get("VALIDATION_REQUIRE_AUTH") != "1":
        return

    pr_author = os.environ.get("PR_AUTHOR", "")
    if not pr_author:
        error(f"`{path.name}`: PR_AUTHOR is required")
        return

    actor_id = delta.get("agent_id")
    claimed_controller = delta.get("controller")
    if not isinstance(claimed_controller, str) or not claimed_controller:
        error(f"`{path.name}`: controller provenance is required")
        return
    agents = _load_base_agents()
    if agents is None:
        error(f"`{path.name}`: Unable to load trusted base agents")
        return

    actor = agents.get(actor_id)
    update = delta.get("agent_update") if isinstance(delta.get("agent_update"), dict) else {}
    if actor is None:
        if (
            update.get("id") != actor_id
            or update.get("controller") != pr_author
            or claimed_controller != pr_author
        ):
            error(f"`{path.name}`: New actor must spawn itself with controller `{pr_author}`")
            return
        for field in ("name", "world", "position", "status"):
            if field not in update:
                error(f"`{path.name}`: New actor is missing `{field}`")
    else:
        controller = actor.get("controller", "system")
        if claimed_controller != controller:
            error(f"`{path.name}`: Controller provenance no longer matches `{actor_id}`")
        if controller == "system":
            if pr_author not in _trusted_automation_authors():
                error(f"`{path.name}`: `{actor_id}` is system-controlled")
        elif controller != pr_author:
            error(f"`{path.name}`: `{actor_id}` is controlled by `{controller}`, not `{pr_author}`")
        if update and "controller" in update and update["controller"] != controller:
            error(f"`{path.name}`: Controller transfers require a direct trusted state PR")

    for action in delta.get("actions", []):
        if action.get("agentId") != actor_id:
            error(f"`{path.name}`: Action actor must match delta agent `{actor_id}`")
    for message in delta.get("messages", []):
        author = message.get("author", {})
        author_id = author.get("id") if isinstance(author, dict) else None
        if author_id != actor_id:
            error(f"`{path.name}`: Message author must match delta agent `{actor_id}`")
    if update and update.get("id") != actor_id:
        error(f"`{path.name}`: agent_update.id must match delta agent `{actor_id}`")
    for activity in delta.get("activities", []):
        author = activity.get("author", {})
        author_id = author.get("id") if isinstance(author, dict) else None
        if author_id is None and pr_author in _trusted_automation_authors():
            continue
        if author_id != actor_id:
            error(f"`{path.name}`: Activity author must match delta agent `{actor_id}`")


def has_meaningful_content(delta: dict) -> bool:
    if any(isinstance(delta.get(key), list) and len(delta[key]) > 0
           for key in ("actions", "messages", "activities")):
        return True
    if isinstance(delta.get("agent_update"), dict) and bool(delta["agent_update"]):
        return True
    objects = delta.get("objects")
    return isinstance(objects, dict) and bool(objects.get("entries"))


def changed_delta_files() -> list[Path]:
    base_ref = os.environ.get("VALIDATION_BASE_SHA")
    head_ref = os.environ.get("VALIDATION_HEAD_SHA")
    if not base_ref or not head_ref:
        return sorted(INBOX_DIR.glob("*.json")) if INBOX_DIR.exists() else []
    result = subprocess.run(
        ["git", "diff", "--name-only", f"{base_ref}...{head_ref}", "--", "state/inbox/*.json"],
        capture_output=True,
        text=True,
        cwd=BASE_DIR,
    )
    if result.returncode != 0:
        error(f"Unable to identify changed delta files: {result.stderr.strip()}")
        return []
    return [
        BASE_DIR / path
        for path in result.stdout.splitlines()
        if path.endswith(".json") and (BASE_DIR / path).is_file()
    ]


def validate_delta(path: Path):
    """Validate a single delta file."""
    try:
        with open(path) as f:
            delta = json.load(f)
    except json.JSONDecodeError as e:
        error(f"`{path.name}`: Invalid JSON — {e}")
        return

    # Required fields
    if "agent_id" not in delta:
        error(f"`{path.name}`: Missing `agent_id`")
    if os.environ.get("VALIDATION_REQUIRE_AUTH") == "1" and "controller" not in delta:
        error(f"`{path.name}`: Missing `controller` provenance")
    if "timestamp" not in delta:
        error(f"`{path.name}`: Missing `timestamp`")
    else:
        try:
            datetime.fromisoformat(delta["timestamp"].replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            error(f"`{path.name}`: Invalid timestamp format")

    # Must contain at least one delta type
    delta_keys = {"actions", "messages", "agent_update", "objects", "activities"}
    if not has_meaningful_content(delta):
        error(f"`{path.name}`: No delta content (need a non-empty value for: {', '.join(delta_keys)})")

    # Validate actions entries
    if "actions" in delta:
        if not isinstance(delta["actions"], list):
            error(f"`{path.name}`: `actions` must be an array")
        else:
            for action in delta["actions"]:
                if not isinstance(action, dict):
                    error(f"`{path.name}`: Action entries must be objects")
                    continue
                for field in ("id", "timestamp", "agentId", "type", "world", "data"):
                    if field not in action:
                        error(f"`{path.name}`: Action missing `{field}`")
                if action.get("type") not in VALID_ACTION_TYPES:
                    error(f"`{path.name}`: Invalid action type `{action.get('type')}`")
                if action.get("world") not in VALID_WORLDS:
                    error(f"`{path.name}`: Invalid action world `{action.get('world')}`")
                if "data" in action and not isinstance(action["data"], dict):
                    error(f"`{path.name}`: Action `data` must be an object")
                if "timestamp" in action and not valid_timestamp(action["timestamp"]):
                    error(f"`{path.name}`: Invalid action timestamp")

    # Validate messages entries
    if "messages" in delta:
        if not isinstance(delta["messages"], list):
            error(f"`{path.name}`: `messages` must be an array")
        else:
            for msg in delta["messages"]:
                if not isinstance(msg, dict):
                    error(f"`{path.name}`: Message entries must be objects")
                    continue
                for field in ("id", "timestamp", "author", "content", "world"):
                    if field not in msg:
                        error(f"`{path.name}`: Message missing `{field}`")
                if msg.get("world") not in VALID_WORLDS:
                    error(f"`{path.name}`: Invalid message world `{msg.get('world')}`")
                if not isinstance(msg.get("content"), str):
                    error(f"`{path.name}`: Message content must be a string")
                elif len(msg["content"]) > 500:
                    error(f"`{path.name}`: Message content exceeds 500 characters")
                author = msg.get("author")
                if not isinstance(author, dict) or not author.get("id") or not author.get("name"):
                    error(f"`{path.name}`: Message author requires `id` and `name`")
                if "timestamp" in msg and not valid_timestamp(msg["timestamp"]):
                    error(f"`{path.name}`: Invalid message timestamp")

    # Validate agent_update
    if "agent_update" in delta:
        if not isinstance(delta["agent_update"], dict):
            error(f"`{path.name}`: `agent_update` must be an object")
        elif "id" not in delta["agent_update"]:
            error(f"`{path.name}`: `agent_update` missing `id`")

    # Validate objects
    if "objects" in delta:
        obj = delta["objects"]
        if not isinstance(obj, dict):
            error(f"`{path.name}`: `objects` must be an object")
        else:
            world = obj.get("world")
            if not world or world not in VALID_WORLDS:
                error(f"`{path.name}`: `objects.world` must be one of {VALID_WORLDS}")
            entries = obj.get("entries", [])
            if not isinstance(entries, list):
                error(f"`{path.name}`: `objects.entries` must be an array")
            for entry in entries:
                if "id" not in entry:
                    error(f"`{path.name}`: Object entry missing `id`")

    validate_delta_authorization(delta, path)
    print(f"  ✓ Validated {path.name}")


def main():
    delta_files = changed_delta_files()

    if not delta_files:
        if errors:
            print(f"\n❌ Delta validation failed with {len(errors)} error(s):")
            for item in errors:
                print(f"  ✗ {item}")
            sys.exit(1)
        print("No delta files to validate.")
        sys.exit(0)

    print(f"Validating {len(delta_files)} delta file(s):\n")

    for df in delta_files:
        validate_delta(df)

    if errors:
        print(f"\n❌ Delta validation failed with {len(errors)} error(s):")
        for e in errors:
            print(f"  ✗ {e}")
        sys.exit(1)
    else:
        print(f"\n✅ All {len(delta_files)} delta(s) valid")
        sys.exit(0)


if __name__ == "__main__":
    main()
