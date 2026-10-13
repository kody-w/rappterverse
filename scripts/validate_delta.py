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
from pathlib import Path, PurePosixPath

BASE_DIR = Path(
    os.environ.get("VALIDATION_REPO_ROOT", Path(__file__).parent.parent)
).resolve()
INBOX_DIR = BASE_DIR / "state" / "inbox"
STATE_DIR = BASE_DIR / "state"

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dreamcatcher_delta import (  # noqa: E402
    DeltaProtocolError,
    capture_worktree,
    load_manifest,
    verify_manifest_repository,
)

from action_types import VALID_ACTION_TYPES  # noqa: E402  (one list, shared with validate_action)

# Peer verification votes (schema/verifications.md). The record rules live in
# scripts/verifications.py; the ids a program answers to in scripts/slosh_lisp.py.
try:
    import verifications as verifications_lib  # noqa: E402
except ImportError:  # pragma: no cover - partial checkout
    verifications_lib = None
try:
    import slosh_lisp as slosh_lib  # noqa: E402
except ImportError:  # pragma: no cover - partial checkout
    slosh_lib = None

VALID_WORLDS = {"hub", "arena", "marketplace", "gallery", "dungeon"}

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
    return {
        owner,
        "github-actions[bot]",
        "github-actions",
        "app/github-actions",
    } | {
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
        trusted_automation = pr_author in _trusted_automation_authors()
        expected_controller = claimed_controller if trusted_automation else pr_author
        if (
            update.get("id") != actor_id
            or update.get("controller") != expected_controller
            or claimed_controller != expected_controller
        ):
            error(
                f"`{path.name}`: New actor must spawn itself with controller "
                f"`{expected_controller}`"
            )
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
        elif controller != pr_author and pr_author not in _trusted_automation_authors():
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

    validate_verify_authorization(delta, path, claimed_controller, agents)


def verify_candidates(delta: dict) -> list:
    """Every (label, rapp-verification/1 record) a delta carries.

    Top-level ``verifications`` entries are taken as records; ``verify``-typed
    entries in ``actions`` are converted with ``verifications.record_from_action``.
    """
    found = []
    raw = delta.get("verifications")
    if isinstance(raw, list):
        found.extend((f"verifications[{i}]", rec) for i, rec in enumerate(raw))
    actions = delta.get("actions")
    if isinstance(actions, list) and verifications_lib is not None:
        found.extend(
            (f"actions[{action.get('id', i)}]", verifications_lib.record_from_action(action))
            for i, action in enumerate(actions)
            if isinstance(action, dict) and action.get("type") == "verify"
        )
    return found


def effective_vote_at(delta: dict, label: str, rec: dict):
    """The ``at`` a vote will carry once ``apply_deltas.fold_verifications`` folds it.

    A top-level ``verifications[i]`` record is stamped with the delta
    ``timestamp``; a ``verify`` action keeps its envelope ``timestamp`` (which
    ``record_from_action`` already copied into ``at``).
    """
    if label.startswith("verifications["):
        return delta.get("timestamp")
    return rec.get("at")


def validate_verify_structure(delta: dict, path: Path):
    """Shape checks every verify vote must pass, trusted or not."""
    candidates = verify_candidates(delta)
    if not candidates:
        return
    if verifications_lib is None:
        error(f"`{path.name}`: verify votes need scripts/verifications.py, which is missing")
        return
    for label, rec in candidates:
        if not isinstance(rec, dict):
            error(f"`{path.name}`: {label}: verification must be an object")
            continue
        try:
            verifications_lib.record({"verifications": []}, rec)
        except ValueError as exc:
            error(f"`{path.name}`: {label}: {exc}")


def validate_verify_authorization(delta: dict, path: Path, controller: str, agents: dict):
    """Bind every verify vote in a delta to the delta's controller.

    Mirrors `validate_action.validate_verify_authorization`: the verifier must
    be the delta's `controller` (case-insensitive), every record's `agent_id`
    must be the delta's `agent_id`, `system` does not vote, the subject must
    resolve to a known artifact (committed per-agent program by file id or
    body id, or a registered subject) not owned by the verifier, and one vote
    per subject per delta. Without this, adding `verify` to the inbox path
    would let `data.verifier` be any login at all.

    Two timing rules make validation agree with the fold
    (`apply_deltas.fold_verifications`), so a delta that passes here always
    writes: the `at` the vote will carry (the delta `timestamp` for a
    top-level record, the action `timestamp` for a `verify` action) may not
    lie more than `verifications.MAX_FUTURE_SKEW_SECONDS` ahead of the
    validator's clock, and it must not be older than the controller's live
    vote on that subject (an equal instant replaces, as the fold's strict
    comparison does). A far-future `at` would otherwise pin a vote that no
    later re-vote could ever replace.
    """
    candidates = verify_candidates(delta)
    if not candidates:
        return
    if verifications_lib is None or slosh_lib is None:
        error(f"`{path.name}`: verify votes need scripts/verifications.py and scripts/slosh_lisp.py")
        return
    if controller == "system":
        error(f"`{path.name}`: system-controlled deltas do not cast peer verifications")
        return
    controllers = {
        aid: agent.get("controller", "system")
        for aid, agent in agents.items() if isinstance(agent, dict)
    }
    owners = slosh_lib.program_subject_owners(STATE_DIR / "programs", controllers)
    try:
        store = verifications_lib.load(STATE_DIR / "verifications.json")
    except ValueError as exc:
        error(f"`{path.name}`: cannot authorize verify votes — {exc}")
        return
    delta_agent = delta.get("agent_id")
    seen = set()
    for label, rec in candidates:
        if not isinstance(rec, dict):
            continue  # reported by validate_verify_structure
        if not verifications_lib.same_login(rec.get("verifier"), controller):
            error(f"`{path.name}`: {label}: `verifier` must be the delta controller `{controller}`")
            continue
        # A top-level record names its own agent_id; a verify action gets it
        # from the envelope, which validate_delta_authorization already bound.
        # Either way it must be the agent this delta acts through, so a
        # controller cannot attribute a vote to an agent it does not own.
        if rec.get("agent_id") != delta_agent:
            error(f"`{path.name}`: {label}: `agent_id` must be the delta agent `{delta_agent}`")
            continue
        subject = rec.get("subject")
        if not isinstance(subject, str):
            continue  # shape error already reported; an object here is unhashable
        if subject in seen:
            error(f"`{path.name}`: {label}: one vote per controller per subject in a delta")
            continue
        seen.add(subject)
        at = effective_vote_at(delta, label, rec)
        if verifications_lib.too_far_in_future(at):
            error(
                f"`{path.name}`: {label}: `at` {at} is more than "
                f"{verifications_lib.MAX_FUTURE_SKEW_SECONDS} seconds in the future; "
                "a vote is stamped with the time it was cast"
            )
            continue
        live = verifications_lib.find_vote(store, controller, subject)
        if live is not None and verifications_lib.supersedes(live.get("at"), at, strict=True):
            error(
                f"`{path.name}`: {label}: a newer live vote by `{controller}` on this subject "
                f"exists ({live.get('at')}); a re-vote must not be older than it"
            )
            continue
        try:
            verifications_lib.record(
                store, rec, subject_owners=owners, require_owner=True, controller=controller,
            )
        except ValueError as exc:
            error(f"`{path.name}`: {label}: {exc}")


def has_meaningful_content(delta: dict) -> bool:
    if any(isinstance(delta.get(key), list) and len(delta[key]) > 0
           for key in ("actions", "messages", "activities", "verifications")):
        return True
    if isinstance(delta.get("agent_update"), dict) and bool(delta["agent_update"]):
        return True
    objects = delta.get("objects")
    return isinstance(objects, dict) and bool(objects.get("entries"))


def _resolve_commit(ref: str) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "--verify", f"{ref}^{{commit}}"],
        capture_output=True,
        text=True,
        cwd=BASE_DIR,
    )
    if result.returncode != 0:
        raise DeltaProtocolError(
            f"cannot resolve {ref!r}: {result.stderr.strip() or result.returncode}"
        )
    return result.stdout.strip()


def _merge_base(left: str, right: str) -> str:
    result = subprocess.run(
        ["git", "merge-base", left, right],
        capture_output=True,
        text=True,
        cwd=BASE_DIR,
    )
    value = result.stdout.strip()
    if result.returncode != 0 or not value:
        raise DeltaProtocolError(
            "cannot resolve validation merge base: "
            f"{result.stderr.strip() or result.returncode}"
        )
    return _resolve_commit(value)


def _dreamcatcher_manifest() -> dict | None:
    base_ref = os.environ.get("VALIDATION_BASE_SHA")
    head_ref = os.environ.get("VALIDATION_HEAD_SHA")
    manifest_path = os.environ.get("DREAMCATCHER_DELTA_MANIFEST")
    if not manifest_path and (not base_ref or not head_ref):
        return None

    source_id = os.environ.get("DREAMCATCHER_DELTA_SOURCE_ID")
    tile = os.environ.get("DREAMCATCHER_DELTA_TILE") or os.environ.get("PR_AUTHOR")
    try:
        if manifest_path:
            manifest = load_manifest(Path(manifest_path))
        else:
            manifest = capture_worktree(
                BASE_DIR,
                base_ref,
                head=head_ref,
                source_id=source_id,
                tile=tile,
                include_untracked=False,
            )
        if base_ref and head_ref:
            resolved_base = _resolve_commit(base_ref)
            resolved_head = _resolve_commit(head_ref)
            verify_manifest_repository(manifest, BASE_DIR)
            if manifest["repository"]["base_commit"] != _merge_base(
                resolved_base,
                resolved_head,
            ):
                raise DeltaProtocolError(
                    "manifest base commit does not match validation merge base"
                )
            if manifest["repository"]["head_commit"] != resolved_head:
                raise DeltaProtocolError(
                    "manifest head commit does not match validation head"
                )
        if source_id and manifest["source"]["id"] != source_id:
            raise DeltaProtocolError("manifest source id does not match validation source")
        if tile and manifest["source"].get("tile") != tile:
            raise DeltaProtocolError("manifest tile does not match validation author")
        return manifest
    except DeltaProtocolError as exc:
        error(f"Dreamcatcher delta manifest is invalid: {exc}")
        return None


def _planned_inbox_files(manifest: dict) -> list[Path]:
    root = BASE_DIR.resolve()
    planned = []
    for repo_path in manifest["search_plan"]["paths"]:
        path = PurePosixPath(repo_path)
        if (
            path.parts[:2] != ("state", "inbox")
            or path.suffix != ".json"
        ):
            continue
        candidate = root.joinpath(*path.parts)
        try:
            candidate.resolve(strict=False).relative_to(root)
        except (OSError, RuntimeError, ValueError):
            error(f"Dreamcatcher planned inbox path escapes the repository: `{repo_path}`")
            continue
        if candidate.is_symlink():
            error(f"Dreamcatcher planned inbox path is a symlink: `{repo_path}`")
            continue
        if not candidate.is_file():
            error(f"Dreamcatcher planned inbox path is missing: `{repo_path}`")
            continue
        planned.append(candidate)
    return planned


def changed_delta_files() -> list[Path]:
    manifest = _dreamcatcher_manifest()
    if manifest is not None:
        return _planned_inbox_files(manifest)
    if errors or os.environ.get("DREAMCATCHER_DELTA_MANIFEST"):
        return []
    return sorted(INBOX_DIR.glob("*.json")) if INBOX_DIR.exists() else []


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
    delta_keys = ("actions", "messages", "agent_update", "objects", "activities", "verifications")
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

    # Validate verifications (peer votes; schema/verifications.md)
    if "verifications" in delta and not isinstance(delta["verifications"], list):
        error(f"`{path.name}`: `verifications` must be an array")
    validate_verify_structure(delta, path)

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
