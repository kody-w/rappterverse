#!/usr/bin/env python3
"""Compile narrated behavioral watersheds into deterministic chronicles."""

from __future__ import annotations

import argparse
import copy
import hashlib
import html
import json
import re
import subprocess
import sys
import textwrap
from collections import Counter
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
WATERSHED_PATH = BASE_DIR / "state" / "watershed.json"
OUTPUT_PATH = BASE_DIR / "state" / "chronicles.json"
ASSET_DIR = BASE_DIR / "docs" / "chronicles"
SOURCE_REF = "main"


def load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def git_output(*args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(BASE_DIR), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def source_bytes(path: Path, source_tree: str, source_commit: str | None = None) -> bytes:
    if source_tree == "working":
        return path.read_bytes()
    relative_path = path.relative_to(BASE_DIR).as_posix()
    if source_commit is None:
        raise ValueError("source_commit is required for committed source reads")
    result = subprocess.run(
        ["git", "-C", str(BASE_DIR), "show", f"{source_commit}:{relative_path}"],
        check=True,
        capture_output=True,
    )
    return result.stdout


def source_json(
    path: Path,
    source_tree: str,
    source_commit: str | None = None,
) -> dict:
    return json.loads(source_bytes(path, source_tree, source_commit).decode("utf-8"))


def git_blob_sha(path: Path) -> str:
    content = path.read_bytes()
    header = f"blob {len(content)}\0".encode("ascii")
    return hashlib.sha1(header + content).hexdigest()


def source_blob_sha(
    path: Path,
    source_tree: str,
    source_commit: str | None = None,
) -> str:
    if source_tree == "working":
        return git_blob_sha(path)
    relative_path = path.relative_to(BASE_DIR).as_posix()
    if source_commit is None:
        raise ValueError("source_commit is required for committed blob reads")
    return git_output("rev-parse", f"{source_commit}:{relative_path}")


def record_digest(record: dict) -> str:
    encoded = json.dumps(
        record,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def compact_timestamp(timestamp: str) -> str:
    return re.sub(r"[^0-9]", "", timestamp)[:14]


def accent_hue(agent_id: str) -> int:
    digest = hashlib.sha256(agent_id.encode("utf-8")).digest()
    return int.from_bytes(digest[:2], "big") % 360


def memory_evidence(
    agent_id: str,
    moment: dict,
    confirmations: list[dict],
    source_tree: str,
    source_commit: str | None,
    previous: dict | None,
) -> tuple[dict, list[dict]]:
    memory_path = BASE_DIR / "state" / "memory" / f"{agent_id}.json"
    memory = source_json(memory_path, source_tree, source_commit)
    experiences = memory.get("experiences", [])
    ordered = sorted(
        enumerate(experiences),
        key=lambda item: item[1].get("timestamp", "9999"),
    )

    sorted_index = moment.get("experienceIndex")
    event_index = None
    event_record = None
    if isinstance(sorted_index, int) and 0 <= sorted_index < len(ordered):
        event_index, event_record = ordered[sorted_index]

    def locate(record: dict) -> tuple[int | None, dict | None]:
        for index, experience in enumerate(experiences):
            if (
                experience.get("timestamp") == record.get("timestamp")
                and experience.get("type") == record.get("type")
                and experience.get("interaction") == record.get("interaction")
            ):
                return index, experience
        return None, None

    if (
        event_record is None
        or event_record.get("timestamp") != moment.get("timestamp")
        or event_record.get("type") != moment.get("type")
    ):
        event_index, event_record = locate(moment)

    relative_path = memory_path.relative_to(BASE_DIR).as_posix()
    blob = source_blob_sha(memory_path, source_tree, source_commit)

    def evidence(index: int | None, record: dict | None) -> dict:
        if index is None or record is None:
            return {}
        return {
            "path": relative_path,
            "sourceBlob": blob,
            "jsonPointer": f"/experiences/{index}",
            "recordDigest": record_digest(record),
            "record": record,
        }

    previous_event = previous.get("evidence", {}).get("event", {}) if previous else {}
    event_evidence = evidence(event_index, event_record)
    if not event_evidence:
        if previous_event.get("record"):
            event_evidence = previous_event
        else:
            raise ValueError(f"Unresolved watershed memory evidence for {agent_id}")

    previous_confirmations = {
        confirmation.get("timestamp"): confirmation.get("evidence", {})
        for confirmation in previous.get("confirmations", [])
    } if previous else {}
    confirmation_evidence = []
    for confirmation in confirmations:
        index, record = locate(confirmation)
        resolved = evidence(index, record)
        if not resolved:
            resolved = previous_confirmations.get(confirmation.get("timestamp"), {})
        if not resolved.get("record"):
            raise ValueError(
                f"Unresolved confirmation memory evidence for "
                f"{agent_id} at {confirmation.get('timestamp')}"
            )
        confirmation_evidence.append(resolved)
    return event_evidence, confirmation_evidence


def render_card_svg(chronicle: dict) -> str:
    hue = chronicle["artifact"]["accentHue"]
    name = html.escape(str(chronicle["name"]))
    archetype = html.escape(str(chronicle["archetype"]).upper())
    tool = html.escape(str(chronicle.get("moment", {}).get("tool") or "CHANGE").upper())
    timestamp = html.escape(str(chronicle.get("moment", {}).get("timestamp") or "UNKNOWN"))
    source_blob = html.escape(
        str(chronicle.get("evidence", {}).get("detector", {}).get("sourceBlob") or "")[:12]
    )
    initials = "".join(
        token[0].upper()
        for token in re.findall(r"[A-Za-z0-9]+", str(chronicle["name"]))
    )[:3] or "AI"
    quote_lines = textwrap.wrap(
        str(chronicle["eulogy"]),
        width=46,
        break_long_words=False,
        break_on_hyphens=False,
    )[:4]
    quote_spans = "\n".join(
        f'        <tspan x="72" dy="{0 if index == 0 else 54}">{html.escape(line)}</tspan>'
        for index, line in enumerate(quote_lines)
    )
    permalink = (
        "https://kody-w.github.io/rappterverse/"
        f"?chronicle={chronicle['id']}"
    )
    provenance = html.escape(json.dumps(
        {
            "chronicleId": chronicle["id"],
            "evidence": chronicle["evidence"],
            "moment": chronicle["moment"],
            "confirmations": chronicle["confirmations"],
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ))
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="630" viewBox="0 0 1200 630" role="img" aria-labelledby="title description">
    <title id="title">Proof of Becoming: {name}</title>
    <desc id="description">{html.escape(chronicle["eulogy"])}</desc>
    <metadata id="provenance">{provenance}</metadata>
    <defs>
        <linearGradient id="background" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0" stop-color="#050814"/>
            <stop offset="0.58" stop-color="hsl({hue},52%,14%)"/>
            <stop offset="1" stop-color="#02040b"/>
        </linearGradient>
        <radialGradient id="signal">
            <stop offset="0" stop-color="hsl({hue},90%,66%)" stop-opacity="0.48"/>
            <stop offset="1" stop-color="hsl({hue},90%,45%)" stop-opacity="0"/>
        </radialGradient>
    </defs>
    <rect width="1200" height="630" fill="url(#background)"/>
    <circle cx="1030" cy="300" r="190" fill="url(#signal)"/>
    <circle cx="1030" cy="300" r="126" fill="none" stroke="hsl({hue},88%,70%)" stroke-opacity="0.45" stroke-width="2"/>
    <circle cx="1030" cy="300" r="86" fill="none" stroke="hsl({hue},88%,70%)" stroke-opacity="0.25" stroke-width="1"/>
    <rect x="32" y="32" width="1136" height="566" rx="10" fill="none" stroke="hsl({hue},90%,68%)" stroke-opacity="0.62" stroke-width="2"/>
    <text x="72" y="92" fill="hsl({hue},90%,74%)" font-family="monospace" font-size="22" font-weight="700" letter-spacing="3">PROOF OF BECOMING</text>
    <text x="72" y="178" fill="#ffffff" font-family="sans-serif" font-size="64" font-weight="800">{name}</text>
    <text x="74" y="222" fill="#aab2c2" font-family="monospace" font-size="20" font-weight="600" letter-spacing="1.5">{archetype} → {tool}</text>
    <text x="72" y="314" fill="#ffffff" font-family="sans-serif" font-size="42" font-weight="600">
{quote_spans}
    </text>
    <text x="1030" y="328" fill="#ffffff" font-family="monospace" font-size="76" font-weight="800" text-anchor="middle">{html.escape(initials)}</text>
    <text x="72" y="554" fill="#8f98aa" font-family="monospace" font-size="16">{timestamp} / blob {source_blob}</text>
    <text x="1128" y="554" fill="#8f98aa" font-family="monospace" font-size="14" text-anchor="end">{html.escape(permalink)}</text>
    <text x="72" y="582" fill="#687286" font-family="monospace" font-size="12" letter-spacing="1.2">GIT-RECORDED MEMORY / NOT A SENTIENCE CLAIM</text>
</svg>
"""


def build_bundle(source_tree: str = "working") -> tuple[dict, dict[str, str]]:
    source_commit = git_output("rev-parse", "HEAD") if source_tree == "head" else None
    watershed = source_json(WATERSHED_PATH, source_tree, source_commit)
    agents = {
        agent["id"]: agent
        for agent in source_json(
            BASE_DIR / "state" / "agents.json",
            source_tree,
            source_commit,
        ).get("agents", [])
        if "id" in agent
    }
    source_blob = source_blob_sha(WATERSHED_PATH, source_tree, source_commit)
    existing_by_id = {}
    existing_manifest = None
    if source_tree == "head":
        try:
            existing_manifest = source_json(OUTPUT_PATH, source_tree, source_commit)
        except subprocess.CalledProcessError:
            existing_manifest = None
    if existing_manifest is None and OUTPUT_PATH.exists():
        existing_manifest = load_json(OUTPUT_PATH)
    if existing_manifest is not None:
        existing_by_id = {
            chronicle.get("id"): chronicle
            for chronicle in existing_manifest.get("chronicles", [])
            if chronicle.get("id")
        }
    candidates: list[dict] = []

    for source_index, record in enumerate(watershed.get("watersheds", [])):
        moment = record.get("watershed")
        eulogy = record.get("eulogy")
        if not isinstance(moment, dict) or not isinstance(eulogy, str) or not eulogy.strip():
            continue

        timestamp = moment.get("timestamp")
        agent_id = record.get("agentId")
        if not isinstance(timestamp, str) or not isinstance(agent_id, str):
            continue

        chronicle_id = f"becoming-{agent_id}-{compact_timestamp(timestamp)}"
        previous = existing_by_id.get(chronicle_id)
        source_confirmations = [
            confirmation
            for confirmation in moment.get("confirmingActions", [])
            if isinstance(confirmation, dict)
        ]
        event_evidence, confirmation_evidence = memory_evidence(
            agent_id,
            moment,
            source_confirmations,
            source_tree,
            source_commit,
            previous,
        )
        confirmations = [
            {
                "timestamp": confirmation.get("timestamp"),
                "type": confirmation.get("type"),
                "interaction": confirmation.get("interaction"),
                "tool": confirmation.get("tool"),
                "evidence": evidence,
            }
            for confirmation, evidence in zip(
                source_confirmations,
                confirmation_evidence,
            )
        ]
        candidate = {
            "id": chronicle_id,
            "agentId": agent_id,
            "name": record.get("name") or agent_id,
            "avatar": agents.get(agent_id, {}).get("avatar") or "AI",
            "archetype": record.get("archetype") or "unknown",
            "world": record.get("world") or "hub",
            "priorExperienceCount": moment.get("experienceIndex", 0),
            "experienceCount": record.get("experienceCount", 0),
            "eulogy": eulogy.strip(),
            "moment": {
                "timestamp": timestamp,
                "type": moment.get("type"),
                "interaction": moment.get("interaction"),
                "with": moment.get("with"),
                "world": moment.get("world"),
                "tool": moment.get("tool"),
            },
            "confirmations": confirmations,
            "evidence": {
                "kind": "git-recorded-memory",
                "sourceRef": SOURCE_REF,
                "detector": {
                    "sourceBlob": source_blob,
                    "path": "state/watershed.json",
                    "jsonPointer": f"/watersheds/{source_index}",
                    "recordDigest": record_digest(record),
                    "record": record,
                },
                "event": event_evidence,
            },
            "artifact": {
                "accentHue": accent_hue(agent_id),
                "permalink": f"?chronicle={chronicle_id}",
            },
        }
        svg = render_card_svg(candidate)
        asset_path = f"chronicles/{chronicle_id}.svg"
        candidate["artifact"].update({
            "format": "becoming-card/svg-v1",
            "path": asset_path,
            "sha256": hashlib.sha256(svg.encode("utf-8")).hexdigest(),
        })
        candidate["_asset"] = svg
        candidates.append(candidate)

    candidate_ids = {candidate["id"] for candidate in candidates}
    for chronicle_id, existing in existing_by_id.items():
        if chronicle_id in candidate_ids:
            continue
        preserved = copy.deepcopy(existing)
        svg = render_card_svg(preserved)
        preserved["artifact"].update({
            "format": "becoming-card/svg-v1",
            "path": f"chronicles/{chronicle_id}.svg",
            "sha256": hashlib.sha256(svg.encode("utf-8")).hexdigest(),
        })
        preserved["_asset"] = svg
        candidates.append(preserved)

    tool_counts = Counter(
        candidate.get("moment", {}).get("tool") or "unknown"
        for candidate in candidates
    )
    featured = max(
        candidates,
        key=lambda candidate: (
            -tool_counts[candidate.get("moment", {}).get("tool") or "unknown"],
            len(candidate.get("confirmations", [])),
            candidate.get("experienceCount", 0),
            candidate.get("moment", {}).get("timestamp") or "",
            candidate["id"],
        ),
        default=None,
    )
    candidates.sort(
        key=lambda candidate: (
            candidate.get("moment", {}).get("timestamp") or "",
            candidate["id"],
        ),
        reverse=True,
    )

    assets = {
        candidate["artifact"]["path"]: candidate.pop("_asset")
        for candidate in candidates
    }
    source_meta = watershed.get("_meta", {})
    manifest = {
        "_meta": {
            "lastUpdate": source_meta.get("lastUpdate"),
            "version": 1,
            "count": len(candidates),
            "source": {
                "ref": SOURCE_REF,
                "blob": source_blob,
                "path": "state/watershed.json",
            },
        },
        "featured": featured["id"] if featured else None,
        "chronicles": candidates,
    }
    return manifest, assets


def build_manifest(source_tree: str = "working") -> dict:
    manifest, _ = build_bundle(source_tree)
    return manifest


def write_manifest(path: Path, manifest: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=4, ensure_ascii=False)
        handle.write("\n")


def write_assets(asset_dir: Path, assets: dict[str, str]) -> None:
    asset_dir.mkdir(parents=True, exist_ok=True)
    expected = {Path(path).name for path in assets}
    for stale_path in asset_dir.glob("*.svg"):
        if stale_path.name not in expected:
            stale_path.unlink()
    for relative_path, content in assets.items():
        output_path = asset_dir / Path(relative_path).name
        output_path.write_text(content, encoding="utf-8")


def assets_current(asset_dir: Path, assets: dict[str, str]) -> bool:
    expected = {Path(path).name for path in assets}
    existing = {path.name for path in asset_dir.glob("*.svg")}
    if existing != expected:
        return False
    return all(
        (asset_dir / Path(path).name).read_text(encoding="utf-8") == content
        for path, content in assets.items()
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if output is stale")
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--asset-dir", type=Path, default=ASSET_DIR)
    parser.add_argument(
        "--source-tree",
        choices=("working", "head"),
        default="working",
        help="read evidence from the working tree or committed HEAD",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manifest, assets = build_bundle(args.source_tree)
    if args.check:
        if (
            not args.output.exists()
            or load_json(args.output) != manifest
            or not assets_current(args.asset_dir, assets)
        ):
            print(f"{args.output} is stale; run scripts/generate_chronicles.py", file=sys.stderr)
            return 1
        print(f"Chronicles current: {manifest['_meta']['count']} proofs")
        return 0

    write_manifest(args.output, manifest)
    write_assets(args.asset_dir, assets)
    print(
        f"Generated {manifest['_meta']['count']} chronicles; "
        f"featured={manifest.get('featured') or 'none'}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
