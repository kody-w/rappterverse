#!/usr/bin/env python3
"""Generate the canonical resource-hash manifest consumed by the frontend."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from datetime import datetime
from pathlib import Path

RESOURCE_PATHS = (
    "state/agents.json",
    "state/chat.json",
    "state/actions.json",
    "state/npcs.json",
    "state/game_state.json",
    "state/frame_counter.json",
    "state/programs/_lispvm/_status.json",
    "state/chronicles.json",
    "worlds/hub/config.json",
    "worlds/arena/config.json",
    "worlds/marketplace/config.json",
    "worlds/gallery/config.json",
    "worlds/dungeon/config.json",
    "worlds/hub/objects.json",
    "worlds/arena/objects.json",
    "worlds/marketplace/objects.json",
    "worlds/gallery/objects.json",
    "worlds/dungeon/objects.json",
)


def reject_json_constant(value: str):
    raise ValueError(f"non-standard numeric constant {value}")


def load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle, parse_constant=reject_json_constant)


def ensure_finite(value: object, path: str):
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f"{path}: non-finite numeric value")
    if isinstance(value, dict):
        for key, child in value.items():
            ensure_finite(child, f"{path}/{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            ensure_finite(child, f"{path}/{index}")


def build_manifest(repo_root: Path) -> dict:
    resources = {}
    timestamps = []
    for relative_path in RESOURCE_PATHS:
        path = repo_root / relative_path
        content = path.read_bytes()
        data = json.loads(
            content.decode("utf-8"),
            parse_constant=reject_json_constant,
        )
        ensure_finite(data, relative_path)
        resources[relative_path] = {
            "sha256": hashlib.sha256(content).hexdigest(),
            "bytes": len(content),
        }
        timestamp = data.get("_meta", {}).get("lastUpdate")
        if isinstance(timestamp, str):
            try:
                datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            except ValueError:
                continue
            timestamps.append(timestamp)

    revision_source = "\n".join(
        f"{path}:{entry['sha256']}"
        for path, entry in sorted(resources.items())
    ).encode("utf-8")
    return {
        "_meta": {
            "lastUpdate": max(timestamps),
            "version": 1,
            "count": len(resources),
        },
        "revision": hashlib.sha256(revision_source).hexdigest(),
        "resources": resources,
    }


def write_manifest(path: Path, manifest: dict) -> None:
    with path.open("w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=4, allow_nan=False)
        handle.write("\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).parent.parent)
    parser.add_argument("--check", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo_root = args.repo_root.resolve()
    output_path = repo_root / "state" / "snapshot.json"
    manifest = build_manifest(repo_root)
    if args.check:
        if not output_path.exists() or load_json(output_path) != manifest:
            print("state/snapshot.json is stale", file=sys.stderr)
            return 1
        print(f"Snapshot current: {manifest['_meta']['count']} resources")
        return 0
    write_manifest(output_path, manifest)
    print(
        f"Generated state snapshot {manifest['revision'][:12]} "
        f"for {manifest['_meta']['count']} resources"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
