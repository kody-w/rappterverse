#!/usr/bin/env python3
"""Deterministic git-worktree deltas for Dreamcatcher fan-out/fan-in."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath
from typing import Iterable, Optional

SCHEMA = "dreamcatcher-delta/1.0"
BATCH_SCHEMA = "dreamcatcher-batch/1.0"
PRODUCER = {"name": "twin-dreamcatcher", "version": "0.2.0"}
STATUSES = {"A", "M", "D", "R", "C", "T", "U"}
ENTITY_KEYS = {
    "id",
    "frame_id",
    "agent_id",
    "rappid",
    "tile_id",
    "stream_id",
    "node_id",
    "discussion_id",
    "discussion_number",
    "post_id",
    "world_id",
}
ENTITY_PATTERN = re.compile(
    r"""["'](?P<key>"""
    + "|".join(sorted(ENTITY_KEYS, key=len, reverse=True))
    + r""")["']\s*:\s*(?P<value>["'][^"'\r\n]{1,256}["']|-?\d+)"""
)
HUNK_PATTERN = re.compile(
    r"^@@ -(?P<old>\d+)(?:,(?P<old_count>\d+))? "
    r"\+(?P<new>\d+)(?:,(?P<new_count>\d+))? @@"
)
HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")
COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40,64}$")


class DeltaProtocolError(ValueError):
    """A delta manifest is malformed or cannot be generated safely."""


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _content_id(payload: dict) -> str:
    return "sha256:" + hashlib.sha256(_canonical_bytes(payload)).hexdigest()


def _with_id(payload: dict, field: str) -> dict:
    result = dict(payload)
    result[field] = _content_id(payload)
    return result


def _run_git(
    repo: Path,
    args: list[str],
    *,
    binary: bool = False,
    check: bool = True,
) -> bytes | str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=not binary,
    )
    if check and result.returncode != 0:
        stderr = (
            result.stderr.decode("utf-8", "replace")
            if binary
            else result.stderr
        )
        raise DeltaProtocolError(
            f"git {' '.join(args)} failed: {stderr.strip() or result.returncode}"
        )
    return result.stdout


def _resolve_commit(repo: Path, ref: str) -> str:
    value = str(_run_git(repo, ["rev-parse", "--verify", f"{ref}^{{commit}}"])).strip()
    if not COMMIT_PATTERN.fullmatch(value):
        raise DeltaProtocolError(f"{ref!r} did not resolve to a commit")
    return value


def _merge_base(repo: Path, left: str, right: str) -> str:
    value = str(_run_git(repo, ["merge-base", left, right])).strip()
    if not COMMIT_PATTERN.fullmatch(value):
        raise DeltaProtocolError("git merge-base did not return a commit")
    return value


def _normalize_path(value: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise DeltaProtocolError(f"invalid repository path: {value!r}")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise DeltaProtocolError(f"path escapes repository: {value!r}")
    canonical = path.as_posix()
    if canonical != value:
        raise DeltaProtocolError(
            f"repository path is not canonical: {value!r}"
        )
    return canonical


def _blob_summary(content: Optional[bytes]) -> Optional[dict]:
    if content is None:
        return None
    return {
        "sha256": hashlib.sha256(content).hexdigest(),
        "bytes": len(content),
    }


def _git_blob(repo: Path, ref: str, path: str) -> Optional[bytes]:
    result = subprocess.run(
        ["git", "show", f"{ref}:{path}"],
        cwd=repo,
        capture_output=True,
    )
    return result.stdout if result.returncode == 0 else None


def _worktree_blob(repo: Path, path: str) -> Optional[bytes]:
    candidate = repo / Path(path)
    if not candidate.is_file() or candidate.is_symlink():
        return None
    return candidate.read_bytes()


def _parse_name_status(raw: bytes) -> list[dict]:
    tokens = raw.split(b"\0")
    if tokens and tokens[-1] == b"":
        tokens.pop()
    changes: list[dict] = []
    index = 0
    while index < len(tokens):
        status_token = tokens[index].decode("ascii", "strict")
        index += 1
        status = status_token[:1]
        if status not in STATUSES:
            raise DeltaProtocolError(f"unsupported git status {status_token!r}")
        if status in {"R", "C"}:
            if index + 1 >= len(tokens):
                raise DeltaProtocolError("truncated rename/copy record")
            old_path = _normalize_path(tokens[index].decode("utf-8", "surrogateescape"))
            path = _normalize_path(tokens[index + 1].decode("utf-8", "surrogateescape"))
            index += 2
            changes.append({
                "status": status,
                "similarity": int(status_token[1:] or 0),
                "old_path": old_path,
                "path": path,
            })
        else:
            if index >= len(tokens):
                raise DeltaProtocolError("truncated name-status record")
            path = _normalize_path(tokens[index].decode("utf-8", "surrogateescape"))
            index += 1
            changes.append({"status": status, "path": path})
    return changes


def _patch_for_change(
    repo: Path,
    base_commit: str,
    head_commit: Optional[str],
    change: dict,
) -> str:
    args = ["diff", "--unified=0", "--no-color", "--find-renames", base_commit]
    if head_commit is not None:
        args.append(head_commit)
    args.extend(["--", change.get("old_path", change["path"]), change["path"]])
    raw = _run_git(repo, args, binary=True)
    return bytes(raw).decode("utf-8", "replace")


def _hunk_ranges(patch: str) -> list[dict]:
    ranges = []
    for line in patch.splitlines():
        match = HUNK_PATTERN.match(line)
        if not match:
            continue
        new_start = int(match.group("new"))
        new_count = int(match.group("new_count") or 1)
        old_start = int(match.group("old"))
        old_count = int(match.group("old_count") or 1)
        ranges.append({
            "old_start": old_start,
            "old_lines": old_count,
            "new_start": new_start,
            "new_lines": new_count,
        })
    return ranges


def _entity_ids(path: str, patch: str) -> list[str]:
    entities = {f"path:{path}"}
    for line in patch.splitlines():
        if not line.startswith(("+", "-")) or line.startswith(("+++", "---")):
            continue
        for match in ENTITY_PATTERN.finditer(line[1:]):
            value = match.group("value").strip("\"'")
            entities.add(f"{match.group('key')}:{value}")
    return sorted(entities)


def _search_scopes(path: str) -> list[str]:
    parts = PurePosixPath(path).parts
    scopes = set()
    for end in range(1, len(parts)):
        scopes.add("/".join(parts[:end]))
    if parts:
        stem = PurePosixPath(path).with_suffix("").as_posix()
        scopes.add(stem)
        suffix = PurePosixPath(path).suffix.lower().lstrip(".")
        if suffix:
            scopes.add(f"format:{suffix}")
    return sorted(scopes)


def _search_plan(changes: Iterable[dict]) -> dict:
    paths = set()
    entities = set()
    scopes = set()
    deleted_paths = set()
    renamed_paths = []
    queries = set()
    for change in changes:
        path = change["path"]
        paths.add(path)
        if change["status"] == "D":
            deleted_paths.add(path)
        if change["status"] == "R":
            renamed_paths.append({"from": change["old_path"], "to": path})
        for entity in change["entity_ids"]:
            entities.add(entity)
            queries.add(("entity", entity))
        for scope in change["search_scopes"]:
            scopes.add(scope)
            queries.add(("scope", scope))
        queries.add(("path", path))
        if change.get("old_path"):
            queries.add(("path", change["old_path"]))
    return {
        "paths": sorted(paths),
        "deleted_paths": sorted(deleted_paths),
        "renamed_paths": sorted(renamed_paths, key=lambda item: (item["from"], item["to"])),
        "entity_ids": sorted(entities),
        "scopes": sorted(scopes),
        "queries": [
            {"kind": kind, "value": value}
            for kind, value in sorted(queries)
        ],
    }


def capture_worktree(
    repo: Path,
    base: str,
    *,
    head: Optional[str] = None,
    source_id: Optional[str] = None,
    frame: Optional[int] = None,
    tile: Optional[str] = None,
    include_untracked: bool = True,
    paths: Optional[Iterable[str]] = None,
) -> dict:
    """Capture a deterministic semantic manifest for one worktree diff."""
    repo = repo.resolve()
    if not (repo / ".git").exists():
        probe = str(_run_git(repo, ["rev-parse", "--git-dir"], check=False)).strip()
        if not probe:
            raise DeltaProtocolError(f"{repo} is not a git worktree")
    requested_base = _resolve_commit(repo, base)
    resolved_head = _resolve_commit(repo, head) if head else None
    base_commit = (
        _merge_base(repo, requested_base, resolved_head)
        if resolved_head
        else requested_base
    )
    branch = str(_run_git(repo, ["branch", "--show-current"])).strip()
    path_filter = (
        sorted({_normalize_path(path) for path in paths})
        if paths is not None
        else []
    )

    args = ["diff", "--name-status", "-z", "--find-renames", base_commit]
    if resolved_head:
        args.append(resolved_head)
    args.append("--")
    args.extend(path_filter)
    changes = _parse_name_status(bytes(_run_git(repo, args, binary=True)))
    seen_paths = {change["path"] for change in changes}

    if include_untracked and resolved_head is None:
        untracked_args = ["ls-files", "--others", "--exclude-standard", "-z"]
        if path_filter:
            untracked_args.extend(["--", *path_filter])
        raw = bytes(_run_git(repo, untracked_args, binary=True))
        for token in raw.split(b"\0"):
            if not token:
                continue
            path = _normalize_path(token.decode("utf-8", "surrogateescape"))
            if path not in seen_paths:
                changes.append({"status": "A", "path": path, "_untracked": True})
                seen_paths.add(path)

    enriched = []
    for change in changes:
        path = change["path"]
        old_path = change.get("old_path", path)
        before = _git_blob(repo, base_commit, old_path)
        if resolved_head:
            after = None if change["status"] == "D" else _git_blob(repo, resolved_head, path)
        else:
            after = None if change["status"] == "D" else _worktree_blob(repo, path)
        patch = "" if change.pop("_untracked", False) else _patch_for_change(
            repo, base_commit, resolved_head, change
        )
        if not patch and after is not None and len(after) <= 1024 * 1024:
            patch = "\n".join(
                "+" + line for line in after.decode("utf-8", "replace").splitlines()
            )
        record = {
            **change,
            "before": _blob_summary(before),
            "after": _blob_summary(after),
            "line_ranges": _hunk_ranges(patch),
            "entity_ids": _entity_ids(path, patch),
            "search_scopes": _search_scopes(path),
        }
        enriched.append(record)
    enriched.sort(key=lambda item: (item["path"], item.get("old_path", ""), item["status"]))

    source = {
        "id": source_id or branch or "detached-worktree",
        "branch": branch or None,
    }
    if frame is not None:
        if isinstance(frame, bool) or not isinstance(frame, int) or frame < 0:
            raise DeltaProtocolError("frame must be non-negative")
        source["frame"] = frame
    if tile is not None:
        source["tile"] = str(tile)

    payload = {
        "schema": SCHEMA,
        "producer": PRODUCER,
        "repository": {
            "base_commit": base_commit,
            "head_commit": resolved_head or _resolve_commit(repo, "HEAD"),
            "includes_worktree": resolved_head is None,
            "path_filter": path_filter,
        },
        "source": source,
        "changes": enriched,
        "search_plan": _search_plan(enriched),
    }
    return _with_id(payload, "manifest_id")


def _require_list_of_strings(value: object, field: str) -> list[str]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item for item in value
    ):
        raise DeltaProtocolError(f"{field} must be a list of non-empty strings")
    return value


def validate_manifest(manifest: dict) -> dict:
    """Validate a manifest strictly and return it unchanged."""
    if not isinstance(manifest, dict):
        raise DeltaProtocolError("manifest must be an object")
    if manifest.get("schema") != SCHEMA:
        raise DeltaProtocolError(f"unsupported schema {manifest.get('schema')!r}")
    producer = manifest.get("producer")
    if (
        not isinstance(producer, dict)
        or producer.get("name") != "twin-dreamcatcher"
        or not isinstance(producer.get("version"), str)
    ):
        raise DeltaProtocolError("producer is invalid")
    repository = manifest.get("repository")
    if not isinstance(repository, dict):
        raise DeltaProtocolError("repository must be an object")
    for field in ("base_commit", "head_commit"):
        if not COMMIT_PATTERN.fullmatch(str(repository.get(field, ""))):
            raise DeltaProtocolError(f"repository.{field} is invalid")
    if not isinstance(repository.get("includes_worktree"), bool):
        raise DeltaProtocolError("repository.includes_worktree must be boolean")
    path_filter = repository.get("path_filter")
    if (
        not isinstance(path_filter, list)
        or any(not isinstance(path, str) for path in path_filter)
    ):
        raise DeltaProtocolError("repository.path_filter must be an array")
    normalized_filter = sorted({_normalize_path(path) for path in path_filter})
    if path_filter != normalized_filter:
        raise DeltaProtocolError(
            "repository.path_filter must be unique and sorted"
        )
    source = manifest.get("source")
    if not isinstance(source, dict) or not isinstance(source.get("id"), str):
        raise DeltaProtocolError("source.id is required")
    if set(source) - {"id", "branch", "frame", "tile"}:
        raise DeltaProtocolError("source contains unsupported fields")
    if source.get("branch") is not None and not isinstance(source["branch"], str):
        raise DeltaProtocolError("source.branch must be a string or null")
    if "frame" in source and (
        isinstance(source["frame"], bool)
        or not isinstance(source["frame"], int)
        or source["frame"] < 0
    ):
        raise DeltaProtocolError("source.frame must be a non-negative integer")
    if "tile" in source and (
        not isinstance(source["tile"], str) or not source["tile"]
    ):
        raise DeltaProtocolError("source.tile must be a non-empty string")
    changes = manifest.get("changes")
    if not isinstance(changes, list):
        raise DeltaProtocolError("changes must be an array")
    seen = set()
    for index, change in enumerate(changes):
        if not isinstance(change, dict):
            raise DeltaProtocolError(f"changes[{index}] must be an object")
        status = change.get("status")
        if status not in STATUSES:
            raise DeltaProtocolError(f"changes[{index}].status is invalid")
        allowed = {
            "status",
            "path",
            "old_path",
            "similarity",
            "before",
            "after",
            "line_ranges",
            "entity_ids",
            "search_scopes",
        }
        if set(change) - allowed:
            raise DeltaProtocolError(f"changes[{index}] contains unsupported fields")
        path = _normalize_path(change.get("path"))
        if path in seen:
            raise DeltaProtocolError(f"duplicate changed path {path}")
        seen.add(path)
        if status in {"R", "C"}:
            _normalize_path(change.get("old_path"))
        elif "old_path" in change:
            raise DeltaProtocolError(
                f"changes[{index}].old_path is only valid for rename/copy"
            )
        for side in ("before", "after"):
            summary = change.get(side)
            if summary is None:
                continue
            if not isinstance(summary, dict):
                raise DeltaProtocolError(f"changes[{index}].{side} must be an object")
            if not HASH_PATTERN.fullmatch(str(summary.get("sha256", ""))):
                raise DeltaProtocolError(f"changes[{index}].{side}.sha256 is invalid")
            if (
                isinstance(summary.get("bytes"), bool)
                or not isinstance(summary.get("bytes"), int)
                or summary["bytes"] < 0
            ):
                raise DeltaProtocolError(f"changes[{index}].{side}.bytes is invalid")
        if status == "A" and (change.get("before") is not None or change.get("after") is None):
            raise DeltaProtocolError(f"changes[{index}] has invalid add blobs")
        if status == "D" and (change.get("before") is None or change.get("after") is not None):
            raise DeltaProtocolError(f"changes[{index}] has invalid delete blobs")
        if status not in {"A", "D"} and (
            change.get("before") is None or change.get("after") is None
        ):
            raise DeltaProtocolError(f"changes[{index}] requires before and after blobs")
        _require_list_of_strings(change.get("entity_ids"), f"changes[{index}].entity_ids")
        _require_list_of_strings(
            change.get("search_scopes"), f"changes[{index}].search_scopes"
        )
        line_ranges = change.get("line_ranges")
        if not isinstance(line_ranges, list):
            raise DeltaProtocolError(f"changes[{index}].line_ranges must be an array")
        for range_index, line_range in enumerate(line_ranges):
            if (
                not isinstance(line_range, dict)
                or set(line_range)
                != {"old_start", "old_lines", "new_start", "new_lines"}
                or any(
                    isinstance(line_range[field], bool)
                    or not isinstance(line_range[field], int)
                    or line_range[field] < 0
                    for field in line_range
                )
            ):
                raise DeltaProtocolError(
                    f"changes[{index}].line_ranges[{range_index}] is invalid"
                )
    if changes != sorted(
        changes,
        key=lambda item: (item["path"], item.get("old_path", ""), item["status"]),
    ):
        raise DeltaProtocolError("changes must be deterministically sorted")
    plan = manifest.get("search_plan")
    if not isinstance(plan, dict):
        raise DeltaProtocolError("search_plan must be an object")
    if plan != _search_plan(changes):
        raise DeltaProtocolError("search_plan does not match changed records")
    payload = {key: value for key, value in manifest.items() if key != "manifest_id"}
    expected_id = _content_id(payload)
    if manifest.get("manifest_id") != expected_id:
        raise DeltaProtocolError("manifest_id does not match canonical payload")
    return manifest


def verify_manifest_repository(manifest: dict, repo: Path) -> dict:
    """Prove manifest hashes match its declared base/head or live worktree."""
    manifest = validate_manifest(manifest)
    repo = repo.resolve()
    repository = manifest["repository"]
    base_commit = _resolve_commit(repo, repository["base_commit"])
    head_commit = _resolve_commit(repo, repository["head_commit"])
    source = manifest["source"]
    expected = capture_worktree(
        repo,
        base_commit,
        head=None if repository["includes_worktree"] else head_commit,
        source_id=source["id"],
        frame=source.get("frame"),
        tile=source.get("tile"),
        include_untracked=repository["includes_worktree"],
        paths=repository["path_filter"] or None,
    )
    if expected != manifest:
        raise DeltaProtocolError(
            "manifest does not cover the exact declared repository diff"
        )
    return manifest


def verify_manifest_tree(manifest: dict, root: Path) -> dict:
    """Prove every post-diff blob matches a materialized non-git tree."""
    manifest = validate_manifest(manifest)
    root = root.resolve()
    for change in manifest["changes"]:
        candidate = root / Path(change["path"])
        try:
            candidate.resolve().relative_to(root)
        except ValueError as exc:
            raise DeltaProtocolError(
                f"{change['path']}: path escapes materialized tree"
            ) from exc
        after = _blob_summary(_worktree_blob(root, change["path"]))
        if after != change["after"]:
            raise DeltaProtocolError(
                f"{change['path']}: materialized blob does not match manifest"
            )
    return manifest


def load_manifest(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DeltaProtocolError(f"cannot read {path}: {exc}") from exc
    return validate_manifest(value)


def write_manifest(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _base_intervals(line_ranges: list[dict]) -> list[tuple[int, int]]:
    """Map hunks to a shared-base coordinate system.

    Base lines use even coordinates. Pure insertions use the odd coordinate
    between two base lines, so two inserts at one anchor conflict without
    falsely colliding with an edit to either neighboring line.
    """
    intervals = []
    for line_range in line_ranges:
        old_start = line_range["old_start"]
        old_lines = line_range["old_lines"]
        if old_lines == 0:
            anchor = old_start * 2 + 1
            intervals.append((anchor, anchor))
        else:
            intervals.append((
                old_start * 2,
                (old_start + old_lines - 1) * 2,
            ))
    return intervals


def _ranges_overlap(left: list[dict], right: list[dict]) -> bool:
    if not left or not right:
        return True
    for left_start, left_end in _base_intervals(left):
        for right_start, right_end in _base_intervals(right):
            if left_start <= right_end and right_start <= left_end:
                return True
    return False


def _manifest_order(manifest: dict) -> tuple:
    source = manifest["source"]
    frame = source.get("frame")
    return (
        frame
        if isinstance(frame, int) and not isinstance(frame, bool)
        else sys.maxsize,
        str(source.get("tile") or ""),
        str(source.get("id") or ""),
        manifest["manifest_id"],
    )


def _validate_search_plan(plan: object) -> dict:
    if not isinstance(plan, dict) or set(plan) != {
        "paths",
        "deleted_paths",
        "renamed_paths",
        "entity_ids",
        "scopes",
        "queries",
    }:
        raise DeltaProtocolError("batch search_plan is invalid")
    for field in ("paths", "deleted_paths"):
        values = plan[field]
        if (
            not isinstance(values, list)
            or values != sorted(set(values))
            or any(_normalize_path(value) != value for value in values)
        ):
            raise DeltaProtocolError(f"batch search_plan.{field} is invalid")
    for field in ("entity_ids", "scopes"):
        values = plan[field]
        if (
            not isinstance(values, list)
            or values != sorted(set(values))
            or any(not isinstance(value, str) or not value for value in values)
        ):
            raise DeltaProtocolError(f"batch search_plan.{field} is invalid")
    renamed = plan["renamed_paths"]
    if not isinstance(renamed, list):
        raise DeltaProtocolError("batch search_plan.renamed_paths is invalid")
    rename_pairs = []
    for item in renamed:
        if not isinstance(item, dict) or set(item) != {"from", "to"}:
            raise DeltaProtocolError("batch renamed path is invalid")
        rename_pairs.append((
            _normalize_path(item["from"]),
            _normalize_path(item["to"]),
        ))
    if rename_pairs != sorted(set(rename_pairs)):
        raise DeltaProtocolError("batch renamed paths are not sorted and unique")
    queries = plan["queries"]
    if not isinstance(queries, list):
        raise DeltaProtocolError("batch search_plan.queries is invalid")
    query_pairs = []
    for query in queries:
        if (
            not isinstance(query, dict)
            or set(query) != {"kind", "value"}
            or query["kind"] not in {"entity", "path", "scope"}
            or not isinstance(query["value"], str)
            or not query["value"]
        ):
            raise DeltaProtocolError("batch search query is invalid")
        if query["kind"] == "path":
            _normalize_path(query["value"])
        query_pairs.append((query["kind"], query["value"]))
    if query_pairs != sorted(set(query_pairs)):
        raise DeltaProtocolError("batch search queries are not sorted and unique")
    return plan


def validate_batch(batch: dict) -> dict:
    """Strictly validate a deterministic batch artifact."""
    if not isinstance(batch, dict) or set(batch) != {
        "schema",
        "producer",
        "base_commit",
        "ready",
        "ordered_manifest_ids",
        "sources",
        "collisions",
        "conflicts",
        "search_plan",
        "batch_id",
    }:
        raise DeltaProtocolError("batch has unsupported fields")
    if batch["schema"] != BATCH_SCHEMA:
        raise DeltaProtocolError("unsupported batch schema")
    producer = batch["producer"]
    if (
        not isinstance(producer, dict)
        or set(producer) != {"name", "version"}
        or producer["name"] != "twin-dreamcatcher"
        or not isinstance(producer["version"], str)
        or not producer["version"]
    ):
        raise DeltaProtocolError("batch producer is invalid")
    if not COMMIT_PATTERN.fullmatch(str(batch["base_commit"])):
        raise DeltaProtocolError("batch base_commit is invalid")
    if not isinstance(batch["ready"], bool):
        raise DeltaProtocolError("batch ready must be boolean")
    manifest_ids = batch["ordered_manifest_ids"]
    if (
        not isinstance(manifest_ids, list)
        or not manifest_ids
        or len(manifest_ids) != len(set(manifest_ids))
        or any(
            not isinstance(manifest_id, str)
            or not re.fullmatch(r"sha256:[0-9a-f]{64}", manifest_id)
            for manifest_id in manifest_ids
        )
    ):
        raise DeltaProtocolError("batch ordered_manifest_ids are invalid")
    sources = batch["sources"]
    if not isinstance(sources, list) or len(sources) != len(manifest_ids):
        raise DeltaProtocolError("batch sources are invalid")
    for source in sources:
        if (
            not isinstance(source, dict)
            or set(source) - {"id", "branch", "frame", "tile"}
            or not isinstance(source.get("id"), str)
            or not source["id"]
            or (
                source.get("branch") is not None
                and not isinstance(source.get("branch"), str)
            )
            or (
                "frame" in source
                and (
                    not isinstance(source["frame"], int)
                    or isinstance(source["frame"], bool)
                    or source["frame"] < 0
                )
            )
            or (
                "tile" in source
                and (
                    not isinstance(source["tile"], str)
                    or not source["tile"]
                )
            )
        ):
            raise DeltaProtocolError("batch source is invalid")

    def validate_collisions(value: object, field: str) -> list[dict]:
        if not isinstance(value, list):
            raise DeltaProtocolError(f"batch {field} must be an array")
        paths = []
        for collision in value:
            if (
                not isinstance(collision, dict)
                or set(collision) != {"path", "kind", "manifest_ids"}
                or collision["kind"]
                not in {"identical", "disjoint-hunks", "conflict"}
            ):
                raise DeltaProtocolError(f"batch {field} record is invalid")
            path = _normalize_path(collision["path"])
            ids = collision["manifest_ids"]
            if (
                not isinstance(ids, list)
                or len(ids) < 2
                or ids != sorted(set(ids))
                or any(manifest_id not in manifest_ids for manifest_id in ids)
            ):
                raise DeltaProtocolError(
                    f"batch {field} manifest IDs are invalid"
                )
            paths.append(path)
        if paths != sorted(paths) or len(paths) != len(set(paths)):
            raise DeltaProtocolError(f"batch {field} is not sorted and unique")
        return value

    collisions = validate_collisions(batch["collisions"], "collisions")
    conflicts = validate_collisions(batch["conflicts"], "conflicts")
    expected_conflicts = [
        collision for collision in collisions
        if collision["kind"] == "conflict"
    ]
    if conflicts != expected_conflicts or batch["ready"] != (not conflicts):
        raise DeltaProtocolError("batch ready/conflicts fields disagree")
    _validate_search_plan(batch["search_plan"])
    payload = {key: value for key, value in batch.items() if key != "batch_id"}
    if batch["batch_id"] != _content_id(payload):
        raise DeltaProtocolError("batch_id does not match canonical payload")
    return batch


def batch_manifests(manifests: Iterable[dict]) -> dict:
    """Fan in worktree manifests and classify path collisions deterministically."""
    validated = sorted(
        (validate_manifest(dict(manifest)) for manifest in manifests),
        key=_manifest_order,
    )
    if not validated:
        raise DeltaProtocolError("at least one manifest is required")
    manifest_ids = [manifest["manifest_id"] for manifest in validated]
    if len(manifest_ids) != len(set(manifest_ids)):
        raise DeltaProtocolError("batch contains duplicate manifests")
    bases = {manifest["repository"]["base_commit"] for manifest in validated}
    if len(bases) != 1:
        raise DeltaProtocolError("parallel manifests must share one base commit")

    by_path: dict[str, list[tuple[dict, dict, str]]] = {}
    for manifest in validated:
        for change in manifest["changes"]:
            by_path.setdefault(change["path"], []).append(
                (manifest, change, "target")
            )
            if change["status"] == "R":
                by_path.setdefault(change["old_path"], []).append(
                    (manifest, change, "rename-source")
                )

    collisions = []
    conflicts = []
    for path, entries in sorted(by_path.items()):
        if len(entries) < 2:
            continue
        ids = sorted({
            manifest["manifest_id"] for manifest, _, _ in entries
        })
        semantic_changes = {
            (
                change["status"],
                change["path"],
                change.get("old_path"),
                change["after"]["sha256"] if change.get("after") else None,
            )
            for _, change, _ in entries
        }
        roles = {role for _, _, role in entries}
        statuses = {change["status"] for _, change, _ in entries}
        if len(semantic_changes) == 1:
            kind = "identical"
            ready = True
        elif "rename-source" in roles:
            kind = "conflict"
            ready = False
        elif statuses <= {"M"} and all(
            not _ranges_overlap(left[1]["line_ranges"], right[1]["line_ranges"])
            for index, left in enumerate(entries)
            for right in entries[index + 1:]
        ):
            kind = "disjoint-hunks"
            ready = True
        else:
            kind = "conflict"
            ready = False
        record = {
            "path": path,
            "kind": kind,
            "manifest_ids": ids,
        }
        collisions.append(record)
        if not ready:
            conflicts.append(record)

    plans = [manifest["search_plan"] for manifest in validated]
    merged_plan = {
        "paths": sorted({value for plan in plans for value in plan["paths"]}),
        "deleted_paths": sorted({
            value for plan in plans for value in plan["deleted_paths"]
        }),
        "renamed_paths": sorted(
            {
                (item["from"], item["to"])
                for plan in plans
                for item in plan.get("renamed_paths", [])
            }
        ),
        "entity_ids": sorted({
            value for plan in plans for value in plan["entity_ids"]
        }),
        "scopes": sorted({value for plan in plans for value in plan["scopes"]}),
        "queries": sorted(
            {
                (item["kind"], item["value"])
                for plan in plans
                for item in plan.get("queries", [])
            }
        ),
    }
    merged_plan["renamed_paths"] = [
        {"from": old, "to": new} for old, new in merged_plan["renamed_paths"]
    ]
    merged_plan["queries"] = [
        {"kind": kind, "value": value} for kind, value in merged_plan["queries"]
    ]
    payload = {
        "schema": BATCH_SCHEMA,
        "producer": PRODUCER,
        "base_commit": next(iter(bases)),
        "ready": not conflicts,
        "ordered_manifest_ids": [
            manifest["manifest_id"] for manifest in validated
        ],
        "sources": [manifest["source"] for manifest in validated],
        "collisions": collisions,
        "conflicts": conflicts,
        "search_plan": merged_plan,
    }
    return validate_batch(_with_id(payload, "batch_id"))


def _cli() -> int:
    parser = argparse.ArgumentParser(
        description="Capture and reduce Dreamcatcher git-worktree deltas"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    capture = sub.add_parser("capture")
    capture.add_argument("repo")
    capture.add_argument("--base", required=True)
    capture.add_argument("--head")
    capture.add_argument("--source-id")
    capture.add_argument("--frame", type=int)
    capture.add_argument("--tile")
    capture.add_argument("--path", action="append", dest="paths")
    capture.add_argument("--no-untracked", action="store_true")
    capture.add_argument("--output")

    validate = sub.add_parser("validate")
    validate.add_argument("manifest")

    batch = sub.add_parser("batch")
    batch.add_argument("manifests", nargs="+")
    batch.add_argument("--output")

    args = parser.parse_args()
    try:
        if args.command == "capture":
            value = capture_worktree(
                Path(args.repo),
                args.base,
                head=args.head,
                source_id=args.source_id,
                frame=args.frame,
                tile=args.tile,
                include_untracked=not args.no_untracked,
                paths=args.paths,
            )
            if args.output:
                write_manifest(Path(args.output), value)
            else:
                print(json.dumps(value, indent=2, sort_keys=True))
        elif args.command == "validate":
            value = load_manifest(Path(args.manifest))
            print(json.dumps({
                "ok": True,
                "manifest_id": value["manifest_id"],
                "changes": len(value["changes"]),
            }, indent=2))
        else:
            value = batch_manifests(
                load_manifest(Path(path)) for path in args.manifests
            )
            if args.output:
                write_manifest(Path(args.output), value)
            else:
                print(json.dumps(value, indent=2, sort_keys=True))
        return 0
    except DeltaProtocolError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(_cli())
