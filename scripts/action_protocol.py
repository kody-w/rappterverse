#!/usr/bin/env python3
"""ActionV1 emote canary: strict validation, pure reduction, and materialization."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

ACTION_SCHEMA = "rappterverse.action/v1"
REQUEST_ID_RE = re.compile(r"^[0-9A-HJKMNP-TV-Z]{26}$")
AGENT_ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*-[0-9]{3}$")
VALID_WORLDS = {"hub", "arena", "marketplace", "gallery", "dungeon"}
VALID_EMOTES = {"wave", "dance", "bow", "clap", "think", "celebrate", "cheer", "nod"}
ROOT_KEYS = {"schema", "requestId", "actor", "submittedAt", "intent"}
ACTOR_KEYS = {"id", "controller", "sequence"}
INTENT_KEYS = {"type", "expectedWorld", "emote", "durationMs"}


class ActionProtocolError(ValueError):
    """The action cannot be admitted or reduced."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ReductionResult:
    disposition: str
    actions: dict
    cursors: dict
    receipts: dict
    request_index: dict
    receipt: dict


def is_action_v1(value: object) -> bool:
    return isinstance(value, dict) and value.get("schema") == ACTION_SCHEMA


def _timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise ActionProtocolError("invalid_timestamp", "submittedAt must be an ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ActionProtocolError("invalid_timestamp", "submittedAt must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ActionProtocolError("invalid_timestamp", "submittedAt must include a UTC offset")
    return parsed


def _canonical_timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _exact_keys(value: dict, expected: set[str], context: str):
    missing = expected - value.keys()
    extra = value.keys() - expected
    if missing:
        raise ActionProtocolError("missing_field", f"{context} missing: {', '.join(sorted(missing))}")
    if extra:
        raise ActionProtocolError("unknown_field", f"{context} has unknown fields: {', '.join(sorted(extra))}")


def validate_envelope(
    envelope: dict,
    agents_by_id: dict[str, dict],
    pr_author: str,
    trusted_automation: set[str] | None = None,
    *,
    check_world: bool = True,
) -> list[str]:
    try:
        if not is_action_v1(envelope):
            raise ActionProtocolError("invalid_schema", f"schema must be {ACTION_SCHEMA}")
        _exact_keys(envelope, ROOT_KEYS, "ActionV1")
        request_id = envelope["requestId"]
        if not isinstance(request_id, str) or not REQUEST_ID_RE.fullmatch(request_id):
            raise ActionProtocolError("invalid_request_id", "requestId must be a 26-character uppercase ULID")
        _timestamp(envelope["submittedAt"])

        actor = envelope["actor"]
        if not isinstance(actor, dict):
            raise ActionProtocolError("invalid_actor", "actor must be an object")
        _exact_keys(actor, ACTOR_KEYS, "actor")
        if not isinstance(actor["id"], str) or not AGENT_ID_RE.fullmatch(actor["id"]):
            raise ActionProtocolError("invalid_actor_id", "actor.id has an invalid format")
        if not isinstance(actor["controller"], str) or not actor["controller"]:
            raise ActionProtocolError("invalid_controller", "actor.controller is required")
        if not isinstance(actor["sequence"], int) or isinstance(actor["sequence"], bool) or actor["sequence"] < 1:
            raise ActionProtocolError("invalid_sequence", "actor.sequence must be a positive integer")

        agent = agents_by_id.get(actor["id"])
        if not agent:
            raise ActionProtocolError("unknown_actor", f"actor {actor['id']} does not exist")
        controller = agent.get("controller", "system")
        if actor["controller"] != controller:
            raise ActionProtocolError("controller_mismatch", "actor.controller does not match canonical ownership")
        trusted = trusted_automation or set()
        if controller == "system":
            if pr_author not in trusted:
                raise ActionProtocolError("unauthorized_actor", "system actor requires trusted automation")
        elif controller != pr_author:
            raise ActionProtocolError("unauthorized_actor", "PR author does not control actor")

        intent = envelope["intent"]
        if not isinstance(intent, dict):
            raise ActionProtocolError("invalid_intent", "intent must be an object")
        _exact_keys(intent, INTENT_KEYS, "intent")
        if intent["type"] != "emote":
            raise ActionProtocolError("unsupported_intent", "the canary supports only emote")
        if intent["expectedWorld"] not in VALID_WORLDS:
            raise ActionProtocolError("invalid_world", "intent.expectedWorld is invalid")
        if check_world and intent["expectedWorld"] != agent.get("world"):
            raise ActionProtocolError("stale_world", "intent.expectedWorld does not match canonical actor world")
        if intent["emote"] not in VALID_EMOTES:
            raise ActionProtocolError("invalid_emote", "intent.emote is invalid")
        duration = intent["durationMs"]
        if not isinstance(duration, int) or isinstance(duration, bool) or not 0 <= duration <= 10000:
            raise ActionProtocolError("invalid_duration", "intent.durationMs must be 0..10000")
    except ActionProtocolError as exc:
        return [f"{exc.code}: {exc}"]
    return []


def _intent_hash(envelope: dict) -> str:
    value = {
        "actor": envelope["actor"],
        "intent": envelope["intent"],
    }
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def request_index_shard(request_id: str) -> str:
    return hashlib.sha256(request_id.encode("utf-8")).hexdigest()[:2]


def find_exact_receipt(
    envelope: dict,
    cursors_data: dict | None,
    receipts_data: dict | None,
    request_index_data: dict | None = None,
) -> dict | None:
    actor = envelope.get("actor", {})
    actor_id = actor.get("id")
    sequence = actor.get("sequence")
    request_id = envelope.get("requestId")
    try:
        expected_hash = _intent_hash(envelope)
    except (KeyError, TypeError):
        return None
    actor_cursor = (cursors_data or {}).get("actors", {}).get(actor_id, {})
    durable_request = (request_index_data or {}).get("requests", {}).get(request_id)
    if (
        durable_request
        and durable_request.get("actorId") == actor_id
        and durable_request.get("sequence") == sequence
        and durable_request.get("intentHash") == expected_hash
    ):
        return copy.deepcopy(durable_request)
    # Compatibility with the pre-shard canary projection.
    request_entry = actor_cursor.get("requests", {}).get(request_id)
    if (
        request_entry
        and request_entry.get("sequence") == sequence
        and request_entry.get("intentHash") == expected_hash
    ):
        return copy.deepcopy(request_entry.get("receipt"))
    sequence_entry = actor_cursor.get("sequences", {}).get(str(sequence))
    if (
        sequence_entry
        and sequence_entry.get("requestId") == request_id
        and sequence_entry.get("intentHash") == expected_hash
    ):
        return copy.deepcopy(sequence_entry.get("receipt"))
    return next(
        (
            copy.deepcopy(receipt)
            for receipt in (receipts_data or {}).get("receipts", [])
            if receipt.get("actorId") == actor_id
            and receipt.get("sequence") == sequence
            and receipt.get("requestId") == request_id
            and receipt.get("intentHash") == expected_hash
        ),
        None,
    )


def _next_action_number(actions: list[dict], cursor_value: object) -> int:
    numbers = []
    for action in actions:
        match = re.fullmatch(r"action-(\d+)", str(action.get("id", "")))
        if match:
            numbers.append(int(match.group(1)))
    cursor = cursor_value if isinstance(cursor_value, int) and not isinstance(cursor_value, bool) else 1
    return max([cursor, *(number + 1 for number in numbers)])


def _default_cursors() -> dict:
    return {
        "schema": "rappterverse.action-cursors/v1",
        "nextActionNumber": 1,
        "actors": {},
        "_meta": {"version": 1, "lastUpdate": "1970-01-01T00:00:00Z", "actorCount": 0},
    }


def _default_receipts() -> dict:
    return {
        "schema": "rappterverse.action-receipts/v1",
        "receipts": [],
        "_meta": {"version": 1, "count": 0, "totalApplied": 0, "lastUpdate": "1970-01-01T00:00:00Z"},
    }


def _default_request_index() -> dict:
    return {
        "schema": "rappterverse.action-request-index/v1",
        "requests": {},
        "_meta": {"version": 1, "count": 0, "lastUpdate": "1970-01-01T00:00:00Z"},
    }


def reduce_emote(
    actions_data: dict,
    cursors_data: dict | None,
    receipts_data: dict | None,
    agents_data: dict,
    envelope: dict,
    source: dict,
    request_index_data: dict | None = None,
) -> ReductionResult:
    actions_doc = copy.deepcopy(actions_data)
    cursors_doc = copy.deepcopy(cursors_data or _default_cursors())
    receipts_doc = copy.deepcopy(receipts_data or _default_receipts())
    request_index_doc = copy.deepcopy(request_index_data or _default_request_index())
    actor = envelope["actor"]
    actor_id = actor["id"]
    sequence = actor["sequence"]
    intent_hash = _intent_hash(envelope)
    agents_by_id = {
        agent["id"]: agent for agent in agents_data.get("agents", []) if agent.get("id")
    }
    validation = validate_envelope(
        envelope,
        agents_by_id,
        source["author"],
        set(source.get("trustedAutomation", [])),
        check_world=False,
    )
    if validation:
        raise ActionProtocolError("invalid_envelope", validation[0])

    actor_cursor = cursors_doc.setdefault("actors", {}).get(actor_id)
    last_sequence = int(actor_cursor.get("lastSequence", 0)) if actor_cursor else 0
    exact_receipt = find_exact_receipt(
        envelope,
        cursors_doc,
        receipts_doc,
        request_index_doc,
    )
    if exact_receipt:
        return ReductionResult(
            "noop",
            actions_doc,
            cursors_doc,
            receipts_doc,
            request_index_doc,
            exact_receipt,
        )
    request_entry = request_index_doc.get("requests", {}).get(envelope["requestId"])
    if not request_entry:
        request_entry = (actor_cursor or {}).get("requests", {}).get(envelope["requestId"])
    if request_entry:
        raise ActionProtocolError("idempotency_conflict", "requestId was reused")
    sequence_entry = (actor_cursor or {}).get("sequences", {}).get(str(sequence))
    if sequence_entry:
        raise ActionProtocolError("idempotency_conflict", "sequence was reused with another intent")
    existing = next(
        (
            receipt
            for receipt in receipts_doc.get("receipts", [])
            if receipt.get("actorId") == actor_id and receipt.get("sequence") == sequence
        ),
        None,
    )
    existing_request = next(
        (
            receipt
            for receipt in receipts_doc.get("receipts", [])
            if receipt.get("requestId") == envelope["requestId"]
        ),
        None,
    )
    if existing_request:
        raise ActionProtocolError("idempotency_conflict", "requestId was reused")
    if sequence <= last_sequence:
        if (
            existing
            and existing.get("requestId") == envelope["requestId"]
            and existing.get("intentHash") == intent_hash
        ):
            return ReductionResult(
                "noop",
                actions_doc,
                cursors_doc,
                receipts_doc,
                request_index_doc,
                copy.deepcopy(existing),
            )
        if existing:
            raise ActionProtocolError("idempotency_conflict", "sequence was reused with another intent")
        raise ActionProtocolError("stale_sequence", "sequence is older than the durable actor cursor")
    if sequence != last_sequence + 1:
        raise ActionProtocolError("sequence_gap", "sequence must be contiguous per actor")
    if envelope["intent"]["expectedWorld"] != agents_by_id[actor_id].get("world"):
        raise ActionProtocolError("stale_world", "intent.expectedWorld does not match canonical actor world")

    actions = actions_doc.setdefault("actions", [])
    action_number = _next_action_number(actions, cursors_doc.get("nextActionNumber"))
    action_id = f"action-{action_number:06d}"
    accepted_at = _timestamp(source["acceptedAt"])
    if actions and actions[-1].get("timestamp"):
        accepted_at = max(accepted_at, _timestamp(actions[-1]["timestamp"]))
    timestamp = _canonical_timestamp(accepted_at)
    intent = envelope["intent"]
    action = {
        "id": action_id,
        "timestamp": timestamp,
        "agentId": actor_id,
        "type": "emote",
        "world": intent["expectedWorld"],
        "data": {
            "emote": intent["emote"],
            "duration": intent["durationMs"],
            "protocol": "ActionV1",
            "requestId": envelope["requestId"],
        },
    }
    actions.append(action)
    actions_doc["actions"] = actions[-100:]
    actions_doc.setdefault("_meta", {})["lastUpdate"] = timestamp

    receipt_id = f"receipt-{actor_id}-{sequence:012d}"
    receipt = {
        "id": receipt_id,
        "requestId": envelope["requestId"],
        "actorId": actor_id,
        "sequence": sequence,
        "intentHash": intent_hash,
        "outcome": "applied",
        "canonicalActionId": action_id,
        "source": {
            "pr": source["pr"],
            "headSha": source["headSha"],
            "author": source["author"],
            "baseSha": source["baseSha"],
            "policySha": source["policySha"],
        },
        "acceptedAt": timestamp,
    }
    receipts = receipts_doc.setdefault("receipts", [])
    receipts.append(receipt)
    receipts_doc["receipts"] = receipts[-100:]
    receipt_meta = receipts_doc.setdefault("_meta", {})
    receipt_meta["version"] = 1
    receipt_meta["count"] = len(receipts_doc["receipts"])
    receipt_meta["totalApplied"] = int(receipt_meta.get("totalApplied", 0)) + 1
    receipt_meta["lastUpdate"] = timestamp

    cursors_doc["schema"] = "rappterverse.action-cursors/v1"
    cursors_doc["nextActionNumber"] = action_number + 1
    cursors_doc.setdefault("actors", {})[actor_id] = {
        "lastSequence": sequence,
        "lastRequestId": envelope["requestId"],
        "lastIntentHash": intent_hash,
        "lastReceiptId": receipt_id,
    }
    cursor_meta = cursors_doc.setdefault("_meta", {})
    cursor_meta["version"] = 1
    cursor_meta["lastUpdate"] = timestamp
    cursor_meta["actorCount"] = len(cursors_doc["actors"])

    request_index_doc["schema"] = "rappterverse.action-request-index/v1"
    request_index_doc.setdefault("requests", {})[envelope["requestId"]] = copy.deepcopy(receipt)
    request_meta = request_index_doc.setdefault("_meta", {})
    request_meta["version"] = 1
    request_meta["count"] = len(request_index_doc["requests"])
    request_meta["lastUpdate"] = timestamp

    return ReductionResult(
        "applied",
        actions_doc,
        cursors_doc,
        receipts_doc,
        request_index_doc,
        receipt,
    )


def _load_json(path: Path, default: dict | None = None) -> dict:
    if not path.exists():
        return copy.deepcopy(default or {})
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


def _save_json(path: Path, value: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, indent=4, ensure_ascii=False)
        stream.write("\n")


def materialize_action_v1(repo_root: Path, envelope_path: Path, source: dict) -> ReductionResult:
    envelope = _load_json(envelope_path)
    state = repo_root / "state"
    request_index_path = (
        state
        / "protocol"
        / "request_index"
        / f"{request_index_shard(envelope.get('requestId', ''))}.json"
    )
    result = reduce_emote(
        _load_json(state / "actions.json"),
        _load_json(state / "protocol" / "action_cursors.json", _default_cursors()),
        _load_json(state / "protocol" / "action_receipts.json", _default_receipts()),
        _load_json(state / "agents.json"),
        envelope,
        source,
        _load_json(request_index_path, _default_request_index()),
    )
    _save_json(state / "actions.json", result.actions)
    _save_json(state / "protocol" / "action_cursors.json", result.cursors)
    _save_json(state / "protocol" / "action_receipts.json", result.receipts)
    _save_json(request_index_path, result.request_index)
    envelope_path.unlink()
    return result


def normalize_delta_v0_emote(delta: dict) -> dict | None:
    actions = delta.get("actions")
    if not isinstance(actions, list) or len(actions) != 1:
        return None
    action = actions[0]
    if action.get("type") != "emote":
        return None
    data = action.get("data", {})
    return {
        "actorId": action.get("agentId"),
        "type": "emote",
        "world": action.get("world"),
        "emote": data.get("emote"),
        "duration": data.get("duration", 0),
    }


def normalize_direct_v0_emote(action: dict) -> dict | None:
    if action.get("type") != "emote":
        return None
    data = action.get("data", {})
    return {
        "actorId": action.get("agentId"),
        "type": "emote",
        "world": action.get("world"),
        "emote": data.get("emote"),
        "duration": data.get("duration", 0),
    }
