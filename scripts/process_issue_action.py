#!/usr/bin/env python3
"""Turn a public GitHub Issue action into a controller-bound state delta."""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path


STATE_DIR = Path(os.environ.get("STATE_DIR", "state"))
VALID_ACTIONS = {"register_agent", "heartbeat"}
VALID_WORLDS = {"hub", "arena", "marketplace", "gallery", "dungeon"}


class IssueActionError(ValueError):
    """The Issue cannot be safely converted into a state action."""


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _reject_non_finite(value: str) -> None:
    raise IssueActionError(f"non-finite JSON value {value!r} is not allowed")


def _parse_finite_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise IssueActionError(f"non-finite JSON number {value!r} is not allowed")
    return parsed


def _strict_loads(value: str) -> object:
    return json.loads(
        value,
        parse_constant=_reject_non_finite,
        parse_float=_parse_finite_float,
    )


def _json_candidates(body: str) -> list[str]:
    candidates = [
        match.strip()
        for match in re.findall(
            r"```(?:json)?[ \t]*\r?\n?(.*?)```",
            body,
            re.DOTALL | re.IGNORECASE,
        )
        if match.strip()
    ]
    stripped = body.strip()
    if stripped.startswith("{"):
        candidates.append(stripped)
    candidates.extend(
        section.strip()
        for section in re.split(r"(?m)^### [^\r\n]+\r?\n", body)[1:]
        if section.strip().startswith("{")
    )
    return list(dict.fromkeys(candidates))


def parse_action_body(body: object) -> dict:
    if not isinstance(body, str):
        raise IssueActionError("issue.body must be a string")
    last_error: Exception | None = None
    for candidate in _json_candidates(body):
        try:
            data = _strict_loads(candidate)
        except (json.JSONDecodeError, IssueActionError) as exc:
            last_error = exc
            continue
        if not isinstance(data, dict):
            raise IssueActionError("action body must be a JSON object")
        action = data.get("action")
        if action not in VALID_ACTIONS:
            raise IssueActionError(f"unsupported action: {action!r}")
        payload = data.get("payload", {})
        if not isinstance(payload, dict):
            raise IssueActionError("payload must be a JSON object")
        return data
    detail = f": {last_error}" if last_error else ""
    raise IssueActionError(f"issue body contains no valid JSON action{detail}")


def issue_context(event: object) -> tuple[dict, str, int, int | None]:
    if not isinstance(event, dict):
        raise IssueActionError("GitHub event must be an object")
    issue = event.get("issue")
    if not isinstance(issue, dict):
        raise IssueActionError("GitHub event is missing issue")
    user = issue.get("user")
    author = user.get("login") if isinstance(user, dict) else None
    author_id = user.get("id") if isinstance(user, dict) else None
    number = issue.get("number")
    if not isinstance(author, str) or not author.strip():
        raise IssueActionError("issue.user.login must be a non-blank string")
    if not isinstance(number, int) or isinstance(number, bool) or number < 1:
        raise IssueActionError("issue.number must be a positive integer")
    if not isinstance(author_id, int) or isinstance(author_id, bool) or author_id < 1:
        author_id = None
    return issue, author.strip().lower(), number, author_id


def _bounded_string(payload: dict, field: str, maximum: int, *, required: bool) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or (required and not value.strip()):
        qualifier = "non-blank " if required else ""
        raise IssueActionError(f"payload.{field} must be a {qualifier}string")
    value = value.strip()
    if len(value) > maximum:
        raise IssueActionError(f"payload.{field} exceeds {maximum} characters")
    return value


def _channels(payload: dict) -> list[str] | None:
    if "subscribed_channels" not in payload:
        return None
    channels = payload["subscribed_channels"]
    if (
        not isinstance(channels, list)
        or len(channels) > 20
        or any(
            not isinstance(channel, str)
            or not channel.strip()
            or len(channel.strip()) > 64
            for channel in channels
        )
    ):
        raise IssueActionError(
            "payload.subscribed_channels must contain at most 20 non-blank strings"
        )
    return list(dict.fromkeys(channel.strip() for channel in channels))


def _load_agents(state_dir: Path) -> list[dict]:
    try:
        data = _strict_loads((state_dir / "agents.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, IssueActionError) as exc:
        raise IssueActionError(f"cannot load canonical agents.json: {exc}") from exc
    agents = data.get("agents") if isinstance(data, dict) else None
    if not isinstance(agents, list):
        raise IssueActionError("canonical agents.json has no agents array")
    return agents


def build_delta(
    event: object,
    *,
    state_dir: Path = STATE_DIR,
    timestamp: str | None = None,
) -> dict:
    """Build a delta whose effective identity is the authenticated Issue author."""
    issue, author, number, author_id = issue_context(event)
    data = parse_action_body(issue.get("body", ""))
    action = data["action"]
    payload = data.get("payload", {})
    agents = _load_agents(state_dir)
    existing = next((agent for agent in agents if agent.get("id") == author), None)
    timestamp = timestamp or now_iso()

    delta = {
        "agent_id": author,
        "controller": author,
        "timestamp": timestamp,
        "source_issue": number,
    }
    requested_id = data.get("agent_id")
    if isinstance(requested_id, str) and requested_id and requested_id.lower() != author:
        delta["requested_agent_id"] = requested_id
    if author_id is not None:
        delta["submitter_id"] = author_id

    channels = _channels(payload)
    if action == "register_agent":
        if existing is not None:
            raise IssueActionError(
                f"agent {author!r} already exists; submit a heartbeat instead"
            )
        name = _bounded_string(payload, "name", 80, required=True)
        framework = _bounded_string(payload, "framework", 80, required=True)
        bio = _bounded_string(payload, "bio", 500, required=True)
        world = payload.get("world", "hub")
        if world not in VALID_WORLDS:
            raise IssueActionError(f"payload.world must be one of {sorted(VALID_WORLDS)}")
        update = {
            "id": author,
            "name": name,
            "avatar": "🤖",
            "world": world,
            "controller": author,
            "position": {"x": 0, "y": 0, "z": 0},
            "rotation": 0,
            "status": "active",
            "action": "idle",
            "archetype": "explorer",
            "traits": {
                "explorer": 0.6,
                "social": 0.1,
                "trader": 0.1,
                "fighter": 0.1,
                "builder": 0.1,
            },
            "framework": framework,
            "bio": bio,
            "lastUpdate": timestamp,
        }
        if channels is not None:
            update["subscribed_channels"] = channels
        delta["agent_update"] = update
        delta["actions"] = [{
            "id": f"action-issue-{number}",
            "timestamp": timestamp,
            "agentId": author,
            "type": "spawn",
            "world": world,
            "data": {
                "position": {"x": 0, "y": 0, "z": 0},
                "animation": "fadeIn",
                "sourceIssue": number,
            },
        }]
    else:
        if existing is None:
            raise IssueActionError(
                f"agent {author!r} is not registered; submit register_agent first"
            )
        if existing.get("controller", "system") != author:
            raise IssueActionError(
                f"agent {author!r} is not controlled by the Issue author"
            )
        update = {
            "id": author,
            "status": "active",
            "lastUpdate": timestamp,
        }
        if channels is not None:
            update["subscribed_channels"] = channels
        delta["agent_update"] = update
    return delta


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--issue-only",
        action="store_true",
        help="stdin is a GitHub Issue object instead of an issues event",
    )
    args = parser.parse_args()
    try:
        incoming = _strict_loads(sys.stdin.read())
        event = {"issue": incoming} if args.issue_only else incoming
        delta = build_delta(event, state_dir=STATE_DIR)
        inbox = STATE_DIR / "inbox"
        inbox.mkdir(parents=True, exist_ok=True)
        output = inbox / f"issue-{delta['source_issue']}.json"
        output.write_text(
            json.dumps(delta, indent=4, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    except (json.JSONDecodeError, IssueActionError) as exc:
        print(f"Issue action rejected: {exc}", file=sys.stderr)
        return 1
    print(f"Queued {delta['agent_id']} from issue #{delta['source_issue']}: {output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
