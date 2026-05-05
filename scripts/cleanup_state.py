#!/usr/bin/env python3
"""Cleanup polluted state — chat.json + actions.json.

One-shot scrubber for live state pollution. Idempotent: running twice
produces no further change. Targets:

  state/chat.json:
    - Messages whose content matches forbidden pollution patterns
      (DRY RUN placeholders, LLM transient retries, shell traces).
    - Empty / whitespace-only messages.

  state/actions.json:
    - Action diversity collapse: if the same (agentId, type) pair runs
      consecutively more than --max-run times, keep only the first
      --max-run occurrences and drop the rest. Default max-run = 3.

Usage:
    python3 scripts/cleanup_state.py             # apply, write changes
    python3 scripts/cleanup_state.py --dry-run   # show what would change
    python3 scripts/cleanup_state.py --max-run 2 # tighter dedup
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
STATE_DIR = BASE_DIR / "state"
sys.path.insert(0, str(BASE_DIR / "scripts"))

# Reuse the sanitizer from agent_dispatch — single source of truth.
from agent_dispatch import is_clean_chat_content  # noqa: E402


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def scrub_chat(data: dict) -> tuple[dict, list]:
    """Remove polluted messages from chat.json. Returns (new_data, dropped)."""
    msgs = data.get("messages", [])
    kept = []
    dropped = []
    for m in msgs:
        content = m.get("content") or ""
        if is_clean_chat_content(content):
            kept.append(m)
        else:
            dropped.append({
                "id": m.get("id"),
                "author": (m.get("author") or {}).get("name"),
                "preview": content[:60].replace("\n", " "),
            })
    new = dict(data)
    new["messages"] = kept
    meta = dict(new.get("_meta", {}))
    meta["lastUpdate"] = now_iso()
    meta["messageCount"] = len(kept)
    new["_meta"] = meta
    return new, dropped


def scrub_actions(data: dict, max_run: int) -> tuple[dict, list]:
    """Trim consecutive (agentId, type) runs longer than max_run AND renumber
    any action whose ID is non-monotonic relative to its position.

    Two passes:
      1. Drop redundant runs (the diversity collapse fix).
      2. Walk the kept list and renumber any ID that is < its predecessor
         to predecessor + 1. Preserves timestamp ordering and original IDs
         where possible — only the drift offenders get rewritten.
    Returns (new_data, dropped). Renumbered actions appear in `dropped`
    metadata as `{"id":..., "renumbered_to":...}` for traceability.
    """
    acts = data.get("actions", [])
    kept = []
    dropped = []
    prev_key = None
    run_count = 0
    for a in acts:
        key = (a.get("agentId"), a.get("type"))
        if key == prev_key:
            run_count += 1
        else:
            run_count = 1
            prev_key = key
        if run_count <= max_run:
            kept.append(a)
        else:
            dropped.append({
                "id": a.get("id"),
                "agentId": a.get("agentId"),
                "type": a.get("type"),
                "timestamp": a.get("timestamp"),
            })

    # Pass 2: renumber drift offenders to keep IDs monotonic.
    import re as _re_id
    prev_num = -1
    for a in kept:
        m = _re_id.match(r"action-(\d+)", a.get("id", ""))
        if not m:
            continue
        num = int(m.group(1))
        if num < prev_num:
            new_num = prev_num + 1
            old_id = a["id"]
            a["id"] = f"action-{new_num:05d}".replace("00000", "")
            # Avoid leading zero stripping; use plain int
            a["id"] = f"action-{new_num}"
            dropped.append({"id": old_id, "renumbered_to": a["id"]})
            prev_num = new_num
        else:
            prev_num = num

    new = dict(data)
    new["actions"] = kept
    meta = dict(new.get("_meta", {}))
    meta["lastUpdate"] = now_iso()
    if kept:
        meta["lastProcessedId"] = kept[-1].get("id")
    new["_meta"] = meta
    return new, dropped


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="Print what would change, don't write.")
    ap.add_argument("--max-run", type=int, default=3,
                    help="Max consecutive same-(agent,type) actions (default 3).")
    args = ap.parse_args(argv)

    chat_path = STATE_DIR / "chat.json"
    actions_path = STATE_DIR / "actions.json"

    if not chat_path.exists() or not actions_path.exists():
        print(f"missing {chat_path} or {actions_path}", file=sys.stderr)
        return 1

    chat = json.loads(chat_path.read_text())
    actions = json.loads(actions_path.read_text())

    new_chat, chat_dropped = scrub_chat(chat)
    new_actions, action_dropped = scrub_actions(actions, args.max_run)

    print()
    print("=" * 60)
    print("🧹 State Cleanup")
    print("=" * 60)
    print(f"  chat.json:")
    print(f"    before: {len(chat.get('messages', []))} messages")
    print(f"    after:  {len(new_chat['messages'])} messages")
    print(f"    dropped: {len(chat_dropped)}")
    if chat_dropped[:5]:
        for d in chat_dropped[:5]:
            print(f"      - {d['id']} {d['author']}: {d['preview']!r}")
        if len(chat_dropped) > 5:
            print(f"      ... and {len(chat_dropped) - 5} more")
    print()
    print(f"  actions.json (max_run={args.max_run}):")
    print(f"    before: {len(actions.get('actions', []))} actions")
    print(f"    after:  {len(new_actions['actions'])} actions")
    print(f"    dropped: {len(action_dropped)}")
    if action_dropped[:5]:
        for d in action_dropped[:5]:
            if "renumbered_to" in d:
                print(f"      - renumbered {d['id']} → {d['renumbered_to']}")
            else:
                print(f"      - {d['id']} {d.get('agentId','?')}/"
                      f"{d.get('type','?')} @ {d.get('timestamp','?')}")
        if len(action_dropped) > 5:
            print(f"      ... and {len(action_dropped) - 5} more")
    print()

    if args.dry_run:
        print("(dry run — no files written)")
        return 0

    chat_path.write_text(json.dumps(new_chat, indent=4, ensure_ascii=False) + "\n")
    actions_path.write_text(json.dumps(new_actions, indent=4, ensure_ascii=False) + "\n")
    print(f"  ✓ wrote {chat_path.relative_to(BASE_DIR)}")
    print(f"  ✓ wrote {actions_path.relative_to(BASE_DIR)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
