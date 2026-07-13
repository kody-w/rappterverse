#!/usr/bin/env python3
"""Export divergent RAPPterverse event lineages without silently merging them."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOCK_PATH = ROOT / "bootstrap" / "legacy-source-lock.json"
STREAMS = {
    "actions": ("state/actions.json", "actions"),
    "messages": ("state/chat.json", "messages"),
}
SHARD_TARGET_BYTES = 768_000
SHARD_HARD_BYTES = 1_000_000


class ExportError(RuntimeError):
    pass


def git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise ExportError(result.stderr.strip() or f"git exited {result.returncode}")
    return result.stdout


def canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def sha256(value: object) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def load_blob(commit: str, path: str) -> dict | None:
    result = subprocess.run(
        ["git", "show", f"{commit}:{path}"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ExportError(f"{commit}:{path}: invalid JSON") from exc
    if not isinstance(value, dict):
        raise ExportError(f"{commit}:{path}: root must be an object")
    return value


def commits_for(ref: str, path: str) -> list[str]:
    output = git("log", "--first-parent", "--reverse", "--format=%H", ref, "--", path)
    return [line for line in output.splitlines() if line]


def export_stream(
    lineage: str,
    ref: str,
    path: str,
    key: str,
) -> tuple[list[dict], list[dict]]:
    records: dict[tuple[str, str], dict] = {}
    exclusions = []
    for commit in commits_for(ref, path):
        try:
            document = load_blob(commit, path)
        except ExportError as exc:
            blob = git("rev-parse", f"{commit}:{path}").strip()
            exclusions.append({
                "lineage": lineage,
                "commit": commit,
                "path": path,
                "blob": blob,
                "reason": "invalid_json",
                "error": str(exc),
            })
            continue
        if document is None:
            continue
        values = document.get(key, [])
        if not isinstance(values, list):
            raise ExportError(f"{commit}:{path}: `{key}` must be an array")
        for value in values:
            if not isinstance(value, dict) or not value.get("id"):
                continue
            content_hash = sha256(value)
            natural_id = str(value["id"])
            record_key = (natural_id, content_hash)
            record = records.setdefault(record_key, {
                "lineage": lineage,
                "naturalId": natural_id,
                "contentSha256": content_hash,
                "firstSeenCommit": commit,
                "lastSeenCommit": commit,
                "value": value,
            })
            record["lastSeenCommit"] = commit
    ordered = sorted(
        records.values(),
        key=lambda item: (
            str(item["value"].get("timestamp", "")),
            item["naturalId"],
            item["contentSha256"],
        ),
    )
    return ordered, exclusions


def write_jsonl(path: Path, records: list[dict]):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for record in records:
            stream.write(canonical_json(record).decode("utf-8"))
            stream.write("\n")


def write_shards(directory: Path, records: list[dict]) -> list[dict]:
    directory.mkdir(parents=True, exist_ok=True)
    shards = []
    batch = []
    batch_bytes = 0

    def seal():
        nonlocal batch, batch_bytes
        if not batch:
            return
        path = directory / f"part-{len(shards):05d}.jsonl"
        write_jsonl(path, batch)
        size = path.stat().st_size
        if size > SHARD_HARD_BYTES:
            raise ExportError(f"{path}: shard exceeds {SHARD_HARD_BYTES} bytes")
        shards.append({
            "path": str(path.name),
            "bytes": size,
            "records": len(batch),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        })
        batch = []
        batch_bytes = 0

    for record in records:
        encoded = canonical_json(record) + b"\n"
        if len(encoded) > SHARD_HARD_BYTES:
            raise ExportError(
                f"{record.get('naturalId')}: record exceeds {SHARD_HARD_BYTES} bytes"
            )
        if batch and batch_bytes + len(encoded) > SHARD_TARGET_BYTES:
            seal()
        batch.append(record)
        batch_bytes += len(encoded)
    seal()
    return shards


def export(output: Path) -> dict:
    lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    output.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema": "rappterverse.legacy-source-export/v1",
        "sourceLockSha256": sha256(lock),
        "streams": {},
        "collisions": {},
    }

    for stream_name, (path, key) in STREAMS.items():
        all_records = []
        all_exclusions = []
        lineage_shards = {}
        by_natural_id: dict[str, set[str]] = {}
        for lineage in ("main", "frames"):
            ref = lock["sources"][lineage]["commit"]
            records, exclusions = export_stream(lineage, ref, path, key)
            lineage_shards[lineage] = write_shards(
                output / stream_name / lineage,
                records,
            )
            write_jsonl(
                output / stream_name / f"{lineage}-exclusions.jsonl",
                exclusions,
            )
            all_records.extend(records)
            all_exclusions.extend(exclusions)
            for record in records:
                by_natural_id.setdefault(record["naturalId"], set()).add(
                    record["contentSha256"]
                )

        collisions = [
            {
                "naturalId": natural_id,
                "contentSha256": sorted(hashes),
            }
            for natural_id, hashes in sorted(by_natural_id.items())
            if len(hashes) > 1
        ]
        write_jsonl(output / stream_name / "collisions.jsonl", collisions)
        manifest["streams"][stream_name] = {
            "recordCount": len(all_records),
            "exclusionCount": len(all_exclusions),
            "lineageCounts": {
                lineage: sum(1 for record in all_records if record["lineage"] == lineage)
                for lineage in ("main", "frames")
            },
            "lineageShards": lineage_shards,
        }
        manifest["collisions"][stream_name] = len(collisions)

    manifest_path = output / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=4, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    try:
        manifest = export(parse_args().output.resolve())
    except ExportError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
