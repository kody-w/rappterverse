#!/usr/bin/env python3
"""Recompute duplicated projections from their canonical JSON collections."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path


def load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def save_json(path: Path, data: dict):
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=4, ensure_ascii=False, allow_nan=False)
        handle.write("\n")


def reconcile(repo_root: Path) -> list[str]:
    state_dir = repo_root / "state"
    agents = load_json(state_dir / "agents.json")
    actions = load_json(state_dir / "actions.json")
    economy = load_json(state_dir / "economy.json")
    frame = load_json(state_dir / "frame_counter.json")
    game_state = load_json(state_dir / "game_state.json")
    relationships = load_json(state_dir / "relationships.json")
    changed = []

    populations = Counter(
        agent.get("world", "hub")
        for agent in agents.get("agents", [])
    )
    game_changed = False
    for world, world_state in game_state.get("worlds", {}).items():
        expected = populations.get(world, 0)
        if world_state.get("population") != expected:
            world_state["population"] = expected
            game_changed = True

    circulation = sum(
        value
        for value in economy.get("balances", {}).values()
        if isinstance(value, (int, float))
    )
    game_economy = game_state.setdefault("economy", {})
    if game_economy.get("total_rappcoin_circulation") != circulation:
        game_economy["total_rappcoin_circulation"] = circulation
        game_changed = True

    frame_number = frame.get("frame", 0)
    if game_state.setdefault("_meta", {}).get("frame") != frame_number:
        game_state["_meta"]["frame"] = frame_number
        game_changed = True

    source_timestamps = [
        data.get("_meta", {}).get("lastUpdate", "")
        for data in (agents, economy, frame)
    ]
    projection_timestamp = max(filter(None, source_timestamps), default="")
    if game_changed:
        if projection_timestamp:
            game_state["_meta"]["lastUpdate"] = projection_timestamp
        save_json(state_dir / "game_state.json", game_state)
        changed.append("state/game_state.json")

    action_list = actions.get("actions", [])
    expected_action = action_list[-1].get("id") if action_list else None
    action_meta = actions.setdefault("_meta", {})
    if action_meta.get("lastProcessedId") != expected_action:
        action_meta["lastProcessedId"] = expected_action
        save_json(state_dir / "actions.json", actions)
        changed.append("state/actions.json")

    for objects_path in sorted((repo_root / "worlds").glob("*/objects.json")):
        objects = load_json(objects_path)
        expected_count = len(objects.get("objects", []))
        meta = objects.setdefault("_meta", {})
        count_key = "objectCount" if "objectCount" in meta else "count"
        if meta.get(count_key) != expected_count:
            meta[count_key] = expected_count
            save_json(objects_path, objects)
            changed.append(objects_path.relative_to(repo_root).as_posix())

    expected_bonds = [
        {
            "agents": [edge["a"], edge["b"]],
            "strength": edge.get("score", 0),
            "type": "social",
            "lastInteraction": edge.get("lastInteraction", ""),
        }
        for edge in relationships.get("edges", [])
        if edge.get("score", 0) >= 2
    ]
    if relationships.get("bonds", []) != expected_bonds:
        relationships["bonds"] = expected_bonds
        save_json(state_dir / "relationships.json", relationships)
        changed.append("state/relationships.json")

    return changed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).parent.parent)
    args = parser.parse_args()
    changed = reconcile(args.repo_root.resolve())
    if changed:
        print("Reconciled derived state: " + ", ".join(changed))
    else:
        print("Derived state already consistent")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
