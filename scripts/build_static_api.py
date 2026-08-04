#!/usr/bin/env python3
"""The one rapp-static-api/1.0 build step for RAPPterverse.

    python3 scripts/build_static_api.py            # regenerate
    python3 scripts/build_static_api.py --check    # verify only, non-zero on drift

Spec: https://raw.githubusercontent.com/kody-w/rapp-static-apis/main/SPEC.md

Input  : manifest.json                 (the only hand-authored file)
Output : registry.json                 (the index — §2 role 3)
         api/v1/status.json            (§2 role 4)
         api/v1/badge.json             (shields.io endpoint)
         docs/.nojekyll                (§2 role 6 — Pages source is /docs)
         a `schema` string on every declared served document (§3)

The build is a pure function of the manifest plus the bytes already in the
repository — it fetches nothing. It is idempotent and stable-write: re-running
with no state change produces byte-identical output, so scheduled runs commit
nothing.

Liveness (§3): `sha8` and `count` in the index are *latest known*, not a
freshness contract. State moves on every merged action PR; a client that needs
live truth refetches the `raw_url` each entry names. Staleness of the index is
expected and conformant — which is why no PR is gated on rebuilding it.

Python 3.11+, stdlib only.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from static_api import (  # noqa: E402
    INDEX_SCHEMA,
    ISO_Z,
    ROOT,
    STATUS_SCHEMA,
    declared_documents,
    load_manifest,
    rel_path,
    sha8,
    stamp_file,
    utc_now,
    write_json_stable,
)

REGISTRY_PATH = ROOT / "registry.json"
STATUS_PATH = ROOT / "api" / "v1" / "status.json"
BADGE_PATH = ROOT / "api" / "v1" / "badge.json"


def _count(document, count_key):
    if not count_key or not isinstance(document, dict):
        return None
    value = document.get(count_key)
    if isinstance(value, (list, dict, str)):
        return len(value)
    if isinstance(value, int):
        return value
    return None


def _last_update(document):
    if isinstance(document, dict):
        meta = document.get("_meta")
        if isinstance(meta, dict):
            stamp = meta.get("lastUpdate")
            if isinstance(stamp, str):
                return stamp
    return None


def _entry_urls(manifest: dict, relative: str) -> dict:
    raw_base = manifest["raw_base"].rstrip("/")
    pages_base = manifest.get("pages_base", "").rstrip("/")
    urls = {"raw_url": f"{raw_base}/{relative}"}
    pages_dir = manifest.get("pages_dir")
    if pages_base and pages_dir and relative.startswith(pages_dir + "/"):
        urls["pages_url"] = f"{pages_base}/{relative[len(pages_dir) + 1:]}"
    return urls


def build_registry(manifest: dict) -> dict:
    raw_base = manifest["raw_base"].rstrip("/")
    entries = []
    timestamps_total = 0
    timestamps_conformant = 0

    for entry in manifest.get("entries", []):
        relative = entry["path"]
        path = ROOT / relative
        record = {
            "name": entry["name"],
            "schema": entry["schema"],
            "path": relative,
            "description": entry.get("description"),
            **_entry_urls(manifest, relative),
            "doc": (f"{raw_base}/{entry['doc']}" if entry.get("doc") else None),
        }
        if path.is_file():
            payload = path.read_bytes()
            document = json.loads(payload)
            last_update = _last_update(document)
            if last_update is not None:
                timestamps_total += 1
                if ISO_Z.match(last_update):
                    timestamps_conformant += 1
            record.update(
                {
                    "bytes": len(payload),
                    "sha8": sha8(payload),
                    "count": _count(document, entry.get("count_key")),
                    "last_update": last_update,
                    "present": True,
                }
            )
        else:
            record.update({"present": False})
        entries.append(record)

    collections = []
    for collection in manifest.get("collections", []):
        directory = ROOT / collection["dir"]
        members = (
            sorted(directory.glob(collection.get("glob", "*.json")))
            if directory.is_dir()
            else []
        )
        collections.append(
            {
                "name": collection["name"],
                "schema": collection["schema"],
                "dir": collection["dir"],
                "description": collection.get("description"),
                "count": len(members),
                "url_pattern": f"{raw_base}/{collection['url_pattern']}",
                "doc": (
                    f"{raw_base}/{collection['doc']}" if collection.get("doc") else None
                ),
                "sha8": sha8(
                    b"".join(
                        rel_path(m).encode("utf-8") + m.read_bytes() for m in members
                    )
                ),
            }
        )

    documented = sum(1 for e in manifest.get("entries", []) if e.get("doc"))
    stamped = len(declared_documents(manifest))

    return {
        "schema": INDEX_SCHEMA,
        "name": manifest["name"],
        "title": manifest.get("title"),
        "description": manifest.get("description"),
        "spec": manifest.get("spec"),
        "raw_base": raw_base,
        "pages_base": manifest.get("pages_base"),
        "generated": utc_now(),
        "summary": {
            "entries": len(entries),
            "collections": len(collections),
            "documents_carrying_schema": stamped,
            "entries_with_prose_doc": documented,
            "timestamps_iso8601_z": f"{timestamps_conformant}/{timestamps_total}",
        },
        "entries": entries,
        "collections": collections,
        "not_served_as_static_api": manifest.get("documents_not_stamped", []),
        "json_schemas": [
            f"{raw_base}/{p}" for p in manifest.get("schema_docs", [])
        ],
    }


def build_status(manifest: dict, registry: dict) -> dict:
    by_name = {e["name"]: e for e in registry["entries"]}

    def count_of(name):
        return (by_name.get(name) or {}).get("count")

    def stamp_of(name):
        return (by_name.get(name) or {}).get("last_update")

    game_state_path = ROOT / "state" / "game_state.json"
    worlds = {}
    if game_state_path.is_file():
        payload = json.loads(game_state_path.read_text(encoding="utf-8"))
        worlds = {
            world_id: world.get("population")
            for world_id, world in (payload.get("worlds") or {}).items()
        }

    frame = None
    frame_path = ROOT / "state" / "frame_counter.json"
    if frame_path.is_file():
        frame = json.loads(frame_path.read_text(encoding="utf-8")).get("frame")

    return {
        "schema": STATUS_SCHEMA,
        "generated": utc_now(),
        "raw_base": registry["raw_base"],
        "registry": f"{registry['raw_base']}/registry.json",
        "frame": frame,
        "summary": {
            "agents": count_of("agents"),
            "actions": count_of("actions"),
            "messages": count_of("chat"),
            "worlds": len(worlds),
            "documents": registry["summary"]["documents_carrying_schema"],
            "agent_memories": next(
                (c["count"] for c in registry["collections"] if c["name"] == "agent-memory"),
                None,
            ),
        },
        "populations": worlds,
        "last_update": {
            "agents": stamp_of("agents"),
            "actions": stamp_of("actions"),
            "chat": stamp_of("chat"),
            "game_state": stamp_of("game-state"),
        },
    }


def build_badge(status: dict) -> dict:
    agents = status["summary"]["agents"]
    return {
        "schemaVersion": 1,
        "label": "rappterverse",
        "message": f"{agents} agents" if agents is not None else "unknown",
        "color": "blue",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify structural conformance without writing; exit 1 on drift",
    )
    args = parser.parse_args()

    manifest = load_manifest()
    if not manifest:
        print("ERROR: manifest.json is missing or unreadable", file=sys.stderr)
        return 1

    documents = declared_documents(manifest)
    pages_dir = ROOT / manifest.get("pages_dir", "docs")
    nojekyll = pages_dir / ".nojekyll"

    # Stamp before indexing: the index records each document's sha8, so the
    # schema strings have to be on disk first or a single run cannot converge.
    stamped = 0
    if not args.check:
        stamped = sum(1 for path, schema in documents if stamp_file(path, schema))

    registry = build_registry(manifest)
    status = build_status(manifest, registry)
    badge = build_badge(status)

    if args.check:
        problems = []
        for path, schema in documents:
            document = json.loads(path.read_text(encoding="utf-8"))
            if document.get("schema") != schema:
                problems.append(
                    f"{rel_path(path)}: schema is "
                    f"{document.get('schema')!r}, expected {schema!r}"
                )
        if not nojekyll.is_file():
            problems.append(f"{rel_path(nojekyll)}: missing (spec §5 item 4)")
        for path, label in (
            (REGISTRY_PATH, "index"),
            (STATUS_PATH, "status endpoint"),
            (BADGE_PATH, "badge endpoint"),
        ):
            if not path.is_file():
                problems.append(f"{rel_path(path)}: missing ({label})")
        if problems:
            print(f"✗ rapp-static-api/1.0: {len(problems)} conformance problem(s)")
            for problem in problems:
                print(f"  - {problem}")
            return 1
        print(
            f"✓ rapp-static-api/1.0: {len(documents)} document(s) carry a schema "
            "string; index, status, badge and .nojekyll present"
        )
        return 0

    written = []
    if write_json_stable(REGISTRY_PATH, registry):
        written.append("registry.json")
    if write_json_stable(STATUS_PATH, status):
        written.append("api/v1/status.json")
    if write_json_stable(BADGE_PATH, badge, ts_keys=()):
        written.append("api/v1/badge.json")
    if not nojekyll.is_file():
        nojekyll.parent.mkdir(parents=True, exist_ok=True)
        nojekyll.write_text("", encoding="utf-8")
        written.append(rel_path(nojekyll))

    print(f"rapp-static-api/1.0 build: {len(documents)} declared document(s)")
    print(f"  schema strings stamped this run : {stamped}")
    print(f"  generated files rewritten       : {', '.join(written) or 'none (stable)'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
