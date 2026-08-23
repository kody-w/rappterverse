#!/usr/bin/env python3
"""Content-addressed reverse index for Dreamcatcher twin search plans."""

# Vendored from kody-w/rappter@75025fe696331c85de58a9dbdd0efbbc68ac6f86:
# engines/twin-dreamcatcher/reverse_index.py
# Canonical Git-blob SHA-256:
# 8f490c8158d4576f62d872cac69bf4fdd88fe9915e5d90a02e90e01789748d47
# Local adaptations keep the wire format while hardening validation and
# case-only rename handling in addition to the local protocol import.

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Iterable, Optional

from dreamcatcher_delta import (
    DeltaProtocolError,
    ENTITY_KEYS,
    ENTITY_PATTERN,
    _normalize_path,
    _with_id,
    load_manifest,
    validate_manifest,
    verify_manifest_tree,
)

SCHEMA = "dreamcatcher-index/1.0"
QUERY_SCHEMA = "dreamcatcher-index-query/1.0"
PRODUCER = {"name": "twin-dreamcatcher", "version": "0.3.0"}
DEFAULT_SUFFIXES = {
    ".html",
    ".js",
    ".json",
    ".jsonl",
    ".md",
    ".py",
    ".text",
    ".txt",
    ".ts",
    ".yaml",
    ".yml",
}
DEFAULT_MAX_ENTITY_FANOUT = 128
COLLECTION_KEYS = {
    "agents": "agent_id",
    "frames": "frame_id",
    "worlds": "world_id",
    "posts": "post_id",
    "discussions": "discussion_id",
    "streams": "stream_id",
    "tiles": "tile_id",
}
PATH_VALUE_PATTERN = re.compile(
    r"""(?P<quote>["'])(?P<path>(?:\./)?[A-Za-z0-9_.-]+"""
    r"""(?:/[A-Za-z0-9_.-]+)+\.[A-Za-z0-9]{1,12})(?P=quote)"""
)


class ReverseIndexError(ValueError):
    """An index or query cannot be produced safely."""


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _is_positive_integer(value: object) -> bool:
    return (
        isinstance(value, int)
        and not isinstance(value, bool)
        and value >= 1
    )


def _path_is_included(path: str, includes: Iterable[str]) -> bool:
    return any(
        path == include or path.startswith(include.rstrip("/") + "/")
        for include in includes
    )


def _document_obeys_configuration(
    path: str,
    byte_count: int,
    configuration: dict,
) -> bool:
    return bool(
        _path_is_included(path, configuration["includes"])
        and Path(path).suffix.lower() in configuration["suffixes"]
        and byte_count <= configuration["max_bytes"]
    )


def _same_casefold_file_alias(
    old_path: str,
    new_path: str,
    old_candidate: Path,
    new_candidate: Path,
) -> bool:
    if (
        os.name != "nt"
        or old_path == new_path
        or old_path.casefold() != new_path.casefold()
    ):
        return False
    try:
        old_resolved = old_candidate.resolve(strict=True)
        new_resolved = new_candidate.resolve(strict=True)
        return bool(
            str(old_resolved).casefold()
            == str(new_resolved).casefold()
            and os.path.samefile(old_candidate, new_candidate)
        )
    except (OSError, RuntimeError):
        return False


def _walk_entities(value: object, parent_key: Optional[str] = None) -> set[str]:
    entities: set[str] = set()
    if isinstance(value, dict):
        collection_entity = COLLECTION_KEYS.get(parent_key or "")
        for key, child in value.items():
            if collection_entity and isinstance(key, str) and key:
                entities.add(f"{collection_entity}:{key}")
            if key in ENTITY_KEYS and isinstance(child, (str, int)):
                entities.add(f"{key}:{child}")
            entities.update(_walk_entities(child, key))
    elif isinstance(value, list):
        for child in value:
            entities.update(_walk_entities(child))
    return entities


def _parse_json_entities(text: str, suffix: str) -> set[str]:
    entities: set[str] = set()
    try:
        if suffix == ".jsonl":
            values = [
                json.loads(line)
                for line in text.splitlines()
                if line.strip()
            ]
        else:
            values = [json.loads(text)]
    except json.JSONDecodeError:
        return entities
    for value in values:
        entities.update(_walk_entities(value))
    return entities


def _document_metadata(path: str, content: bytes) -> dict:
    text = content.decode("utf-8", "replace")
    suffix = Path(path).suffix.lower()
    entities = {f"path:{path}"}
    if suffix in {".json", ".jsonl"}:
        entities.update(_parse_json_entities(text, suffix))
    for match in ENTITY_PATTERN.finditer(text):
        entities.add(
            f"{match.group('key')}:{match.group('value').strip(chr(34) + chr(39))}"
        )
    path_refs = set()
    for match in PATH_VALUE_PATTERN.finditer(text):
        candidate = match.group("path").removeprefix("./")
        try:
            path_refs.add(_normalize_path(candidate))
        except DeltaProtocolError:
            continue
    return {
        "sha256": _sha256(content),
        "bytes": len(content),
        "format": suffix.lstrip(".") or "none",
        "entity_ids": sorted(entities),
        "path_refs": sorted(path_refs),
    }


def _iter_documents(
    root: Path,
    includes: Iterable[str],
    *,
    max_bytes: int,
    suffixes: set[str],
) -> Iterable[tuple[str, bytes]]:
    root = root.resolve()
    candidates: set[Path] = set()
    for include in includes:
        normalized = _normalize_path(include)
        source = root / Path(normalized)
        try:
            source.resolve().relative_to(root)
        except ValueError as exc:
            raise ReverseIndexError(f"include escapes root: {include}") from exc
        if source.is_file():
            candidates.add(source)
        elif source.is_dir():
            candidates.update(path for path in source.rglob("*") if path.is_file())
    for path in sorted(candidates):
        relative_path = path.relative_to(root)
        relative = relative_path.as_posix()
        current = root
        has_symlink = False
        for part in relative_path.parts:
            current = current / part
            if current.is_symlink():
                has_symlink = True
                break
        if ".git" in relative_path.parts or has_symlink:
            continue
        try:
            path.resolve().relative_to(root)
        except ValueError:
            continue
        if path.suffix.lower() not in suffixes:
            continue
        size = path.stat().st_size
        if size > max_bytes:
            continue
        yield relative, path.read_bytes()


def _build_edges(
    documents: dict[str, dict],
    *,
    max_entity_fanout: int,
) -> tuple[dict, dict, dict, list[str]]:
    entity_paths: dict[str, set[str]] = {}
    dependencies: dict[str, set[str]] = {
        path: set() for path in documents
    }
    for path, metadata in documents.items():
        for entity in metadata["entity_ids"]:
            entity_paths.setdefault(entity, set()).add(path)
        for referenced in metadata["path_refs"]:
            if referenced in documents and referenced != path:
                dependencies[path].add(referenced)
    hub_entities = []
    for entity, paths in entity_paths.items():
        if len(paths) < 2:
            continue
        if len(paths) > max_entity_fanout:
            hub_entities.append(entity)
            continue
        for path in paths:
            dependencies[path].update(paths - {path})
    dependents: dict[str, set[str]] = {
        path: set() for path in documents
    }
    for path, targets in dependencies.items():
        for target in targets:
            dependents[target].add(path)
    return (
        {
            entity: sorted(paths)
            for entity, paths in sorted(entity_paths.items())
        },
        {
            path: sorted(targets)
            for path, targets in sorted(dependencies.items())
        },
        {
            path: sorted(sources)
            for path, sources in sorted(dependents.items())
        },
        sorted(hub_entities),
    )


def _seal_index(documents: dict[str, dict], configuration: dict) -> dict:
    documents = {
        path: documents[path] for path in sorted(documents)
    }
    entities, dependencies, dependents, hub_entities = _build_edges(
        documents,
        max_entity_fanout=configuration["max_entity_fanout"],
    )
    payload = {
        "schema": SCHEMA,
        "producer": PRODUCER,
        "configuration": configuration,
        "documents": documents,
        "entities": entities,
        "dependencies": dependencies,
        "dependents": dependents,
        "stats": {
            "documents": len(documents),
            "bytes": sum(item["bytes"] for item in documents.values()),
            "entities": len(entities),
            "dependency_edges": sum(
                len(targets) for targets in dependencies.values()
            ),
            "hub_entities": len(hub_entities),
        },
    }
    return _with_id(payload, "index_id")


def build_index(
    root: Path,
    *,
    includes: Iterable[str],
    max_bytes: int = 8 * 1024 * 1024,
    max_entity_fanout: int = DEFAULT_MAX_ENTITY_FANOUT,
    suffixes: Optional[set[str]] = None,
) -> dict:
    """Build a deterministic index by reading each included document once."""
    if (
        not _is_positive_integer(max_bytes)
        or not _is_positive_integer(max_entity_fanout)
    ):
        raise ReverseIndexError(
            "max_bytes and max_entity_fanout must be positive integers"
        )
    normalized_includes = sorted({
        _normalize_path(include) for include in includes
    })
    selected_suffixes = sorted(suffixes or DEFAULT_SUFFIXES)
    configuration = {
        "includes": normalized_includes,
        "max_bytes": max_bytes,
        "max_entity_fanout": max_entity_fanout,
        "suffixes": selected_suffixes,
    }
    documents = {
        path: _document_metadata(path, content)
        for path, content in _iter_documents(
            root,
            normalized_includes,
            max_bytes=max_bytes,
            suffixes=set(selected_suffixes),
        )
    }
    return _seal_index(documents, configuration)


def validate_index(index: dict) -> dict:
    """Validate internal consistency and content identity."""
    if not isinstance(index, dict) or index.get("schema") != SCHEMA:
        raise ReverseIndexError("unsupported reverse-index schema")
    documents = index.get("documents")
    if not isinstance(documents, dict):
        raise ReverseIndexError("documents must be an object")
    for path, metadata in documents.items():
        if _normalize_path(path) != path or not isinstance(metadata, dict):
            raise ReverseIndexError(f"invalid document {path!r}")
        if set(metadata) != {
            "sha256",
            "bytes",
            "format",
            "entity_ids",
            "path_refs",
        }:
            raise ReverseIndexError(f"{path}: unsupported document metadata")
        if not re.fullmatch(r"[0-9a-f]{64}", str(metadata.get("sha256", ""))):
            raise ReverseIndexError(f"{path}: invalid sha256")
        if (
            isinstance(metadata.get("bytes"), bool)
            or not isinstance(metadata.get("bytes"), int)
            or metadata["bytes"] < 0
        ):
            raise ReverseIndexError(f"{path}: invalid byte count")
        for field in ("entity_ids", "path_refs"):
            values = metadata.get(field)
            if (
                not isinstance(values, list)
                or values != sorted(set(values))
                or any(not isinstance(value, str) for value in values)
            ):
                raise ReverseIndexError(f"{path}: invalid {field}")
    configuration = index.get("configuration")
    if not isinstance(configuration, dict):
        raise ReverseIndexError("configuration must be an object")
    if set(configuration) != {
        "includes",
        "max_bytes",
        "max_entity_fanout",
        "suffixes",
    }:
        raise ReverseIndexError("unsupported index configuration")
    includes = configuration.get("includes")
    suffixes = configuration.get("suffixes")
    max_bytes = configuration.get("max_bytes")
    max_entity_fanout = configuration.get("max_entity_fanout")
    if (
        not isinstance(includes, list)
        or includes != sorted(set(includes))
        or any(_normalize_path(path) != path for path in includes)
        or not isinstance(suffixes, list)
        or suffixes != sorted(set(suffixes))
        or any(
            not isinstance(suffix, str) or not suffix.startswith(".")
            for suffix in suffixes
        )
        or not _is_positive_integer(max_bytes)
        or not _is_positive_integer(max_entity_fanout)
    ):
        raise ReverseIndexError("invalid index configuration")
    for path, metadata in documents.items():
        if not _document_obeys_configuration(
            path,
            metadata["bytes"],
            configuration,
        ):
            raise ReverseIndexError(
                f"{path}: document violates index configuration"
            )
    expected = _seal_index(documents, configuration)
    if expected != index:
        raise ReverseIndexError("reverse index does not match canonical documents")
    return index


def update_index(
    root: Path,
    previous: dict,
    manifest: dict,
) -> dict:
    """Incrementally reread only paths named by one verified delta manifest."""
    previous = validate_index(previous)
    manifest = validate_manifest(manifest)
    verify_manifest_tree(manifest, root)
    configuration = previous["configuration"]
    documents = {
        path: dict(metadata)
        for path, metadata in previous["documents"].items()
        if _document_obeys_configuration(
            path,
            metadata["bytes"],
            configuration,
        )
    }
    include_roots = configuration["includes"]
    resolved_root = root.resolve()
    resolved_includes = {
        include: (resolved_root / Path(include)).resolve()
        for include in include_roots
    }

    def is_in_scope(path: str) -> bool:
        return _path_is_included(path, include_roots)

    def checked_candidate(path: str) -> Path:
        candidate = resolved_root / Path(path)
        relative = candidate.relative_to(resolved_root)
        current = resolved_root
        for part in relative.parts:
            current = current / part
            if current.is_symlink():
                raise ReverseIndexError(
                    f"{path}: symlink components are not indexable"
                )
        resolved = candidate.resolve()
        if not any(
            resolved == include_root
            or include_root in resolved.parents
            for include_root in resolved_includes.values()
        ):
            raise ReverseIndexError(f"{path}: resolved path escapes index scope")
        return candidate

    for change in manifest["changes"]:
        if change["status"] == "R":
            old_path = change["old_path"]
            old_candidate = resolved_root / Path(old_path)
            new_candidate = resolved_root / Path(change["path"])
            if (
                old_candidate.exists()
                or old_candidate.is_symlink()
            ) and not _same_casefold_file_alias(
                old_path,
                change["path"],
                old_candidate,
                new_candidate,
            ):
                raise ReverseIndexError(
                    f"{old_path}: rename source still exists"
                )
            previous_metadata = documents.get(old_path)
            if (
                previous_metadata is not None
                and previous_metadata["sha256"] != change["before"]["sha256"]
            ):
                raise ReverseIndexError(
                    f"{old_path}: rename source hash is stale"
                )
            documents.pop(old_path, None)
        if change["status"] == "D":
            documents.pop(change["path"], None)
            continue
        path = change["path"]
        if not is_in_scope(path):
            documents.pop(path, None)
            continue
        candidate = checked_candidate(path)
        if not _document_obeys_configuration(
            path,
            candidate.stat().st_size,
            configuration,
        ):
            documents.pop(path, None)
            continue
        documents[path] = _document_metadata(path, candidate.read_bytes())
    return _seal_index(documents, configuration)


def _add_reason(
    selected: dict[str, set[str]],
    path: str,
    reason: str,
    documents: dict,
) -> None:
    if path in documents:
        selected.setdefault(path, set()).add(reason)


def expand_search_plan(
    index: dict,
    search_plan: dict,
    *,
    depth: int = 1,
    include_scopes: bool = False,
) -> dict:
    """Resolve a delta search plan to the minimal indexed dependency closure."""
    index = validate_index(index)
    if not isinstance(search_plan, dict) or depth < 0:
        raise ReverseIndexError("invalid search plan or depth")
    documents = index["documents"]
    selected: dict[str, set[str]] = {}
    missing_paths = []
    for path in search_plan.get("paths", []):
        if path in documents:
            _add_reason(selected, path, f"path:{path}", documents)
        else:
            missing_paths.append(path)
    for rename in search_plan.get("renamed_paths", []):
        old_path = rename.get("from")
        if old_path in documents:
            _add_reason(
                selected,
                old_path,
                f"rename-source:{old_path}",
                documents,
            )
        elif isinstance(old_path, str):
            missing_paths.append(old_path)
    missing_entities = []
    hub_entities = []
    max_entity_fanout = index["configuration"]["max_entity_fanout"]
    for entity in search_plan.get("entity_ids", []):
        paths = index["entities"].get(entity, [])
        if not paths:
            missing_entities.append(entity)
        elif len(paths) > max_entity_fanout:
            hub_entities.append(entity)
            continue
        for path in paths:
            _add_reason(selected, path, f"entity:{entity}", documents)
    if include_scopes:
        for scope in search_plan.get("scopes", []):
            if scope.startswith("format:"):
                wanted = scope.split(":", 1)[1]
                matches = [
                    path for path, item in documents.items()
                    if item["format"] == wanted
                ]
            else:
                prefix = scope.rstrip("/") + "/"
                matches = [
                    path for path in documents
                    if path == scope or path.startswith(prefix)
                ]
            for path in matches:
                _add_reason(selected, path, f"scope:{scope}", documents)
    frontier = set(selected)
    for hop in range(1, depth + 1):
        next_frontier = set()
        for path in sorted(frontier):
            neighbors = set(index["dependencies"].get(path, []))
            neighbors.update(index["dependents"].get(path, []))
            for neighbor in neighbors:
                if neighbor not in selected:
                    next_frontier.add(neighbor)
                _add_reason(
                    selected,
                    neighbor,
                    f"dependency-hop:{hop}:{path}",
                    documents,
                )
        frontier = next_frontier
        if not frontier:
            break
    selected_paths = sorted(selected)
    selected_bytes = sum(documents[path]["bytes"] for path in selected_paths)
    total_bytes = index["stats"]["bytes"]
    payload = {
        "schema": QUERY_SCHEMA,
        "index_id": index["index_id"],
        "selected_paths": selected_paths,
        "reasons": {
            path: sorted(selected[path]) for path in selected_paths
        },
        "missing_paths": sorted(set(missing_paths)),
        "missing_entities": sorted(set(missing_entities)),
        "hub_entities": sorted(set(hub_entities)),
        "fallback_scopes": sorted(set(search_plan.get("scopes", []))),
        "stats": {
            "total_documents": index["stats"]["documents"],
            "selected_documents": len(selected_paths),
            "total_bytes": total_bytes,
            "selected_bytes": selected_bytes,
            "documents_reduction": (
                0.0
                if not index["stats"]["documents"]
                else 1.0 - len(selected_paths) / index["stats"]["documents"]
            ),
            "bytes_reduction": (
                0.0 if not total_bytes else 1.0 - selected_bytes / total_bytes
            ),
        },
    }
    return _with_id(payload, "query_id")


def load_index(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReverseIndexError(f"cannot read {path}: {exc}") from exc
    return validate_index(value)


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _cli() -> int:
    parser = argparse.ArgumentParser(
        description="Build and query the Dreamcatcher twin reverse index"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build")
    build.add_argument("root")
    build.add_argument("--include", action="append", required=True)
    build.add_argument("--max-bytes", type=int, default=8 * 1024 * 1024)
    build.add_argument(
        "--max-entity-fanout",
        type=int,
        default=DEFAULT_MAX_ENTITY_FANOUT,
    )
    build.add_argument("--output", required=True)
    update = sub.add_parser("update")
    update.add_argument("root")
    update.add_argument("index")
    update.add_argument("manifest")
    update.add_argument("--output", required=True)
    query = sub.add_parser("query")
    query.add_argument("index")
    query.add_argument("manifest")
    query.add_argument("--depth", type=int, default=1)
    query.add_argument("--include-scopes", action="store_true")
    query.add_argument("--output")
    args = parser.parse_args()
    try:
        if args.command == "build":
            value = build_index(
                Path(args.root),
                includes=args.include,
                max_bytes=args.max_bytes,
                max_entity_fanout=args.max_entity_fanout,
            )
            write_json(Path(args.output), value)
        elif args.command == "update":
            value = update_index(
                Path(args.root),
                load_index(Path(args.index)),
                load_manifest(Path(args.manifest)),
            )
            write_json(Path(args.output), value)
        else:
            manifest = load_manifest(Path(args.manifest))
            value = expand_search_plan(
                load_index(Path(args.index)),
                manifest["search_plan"],
                depth=args.depth,
                include_scopes=args.include_scopes,
            )
            if args.output:
                write_json(Path(args.output), value)
            else:
                print(json.dumps(value, indent=2, sort_keys=True))
        return 0
    except (DeltaProtocolError, ReverseIndexError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(_cli())
