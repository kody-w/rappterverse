#!/usr/bin/env python3
"""Watershed Detector — find the frame each agent first transcended its archetype.

A "watershed" is the moment an agent stopped being a category and started
being itself: the first sustained off-archetype action in their experience
log. We use brainstem.TOOLBELTS (already authored) as the deterministic
prior — no LLM needed for detection. The brainstem only enters at the end,
optionally, to write a one-sentence eulogy per watershed.

Output: state/watershed.json — for every agent with a memory file, either
a watershed record or 'still being themselves' (no divergence yet).

Usage:
    python3 scripts/watershed.py
    python3 scripts/watershed.py --narrate            # also call brainstem
    python3 scripts/watershed.py --narrate --limit 30 # narrate top 30
    python3 scripts/watershed.py --dry-run            # don't write file
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
STATE_DIR = BASE_DIR / "state"
MEMORY_DIR = STATE_DIR / "memory"
AGENTS_REG_DIR = BASE_DIR / "agents"
OUT_PATH = STATE_DIR / "watershed.json"


# ─── Archetype priors (mirrors brainstem.TOOLBELTS) ───────────────────
# We deliberately copy these instead of importing brainstem.py — the
# detector should run against any historical state, decoupled from
# whatever the brainstem currently believes. Keep in sync if TOOLBELTS
# evolves (it shouldn't, often).

TOOLBELTS = {
    "thoughtful":    {"chat", "emote", "move", "travel", "enroll", "tip", "poke"},
    "introspective": {"chat", "emote", "move", "travel", "enroll", "tip", "poke"},
    "aggressive":    {"chat", "emote", "move", "challenge", "trade", "poke"},
    "friendly":      {"chat", "emote", "move", "travel", "tip", "trade", "poke"},
    "mysterious":    {"chat", "emote", "move", "travel", "poke"},
    "trader":        {"chat", "emote", "move", "trade", "tip", "travel", "poke"},
    "fighter":       {"chat", "emote", "move", "challenge", "travel", "poke"},
    "scholar":       {"chat", "emote", "move", "enroll", "travel", "tip", "poke"},
    "explorer":      {"chat", "emote", "move", "travel", "poke"},
    "creative":      {"chat", "emote", "move", "travel", "poke", "tip"},
    "methodical":    {"chat", "emote", "move", "travel", "enroll", "poke"},
    "neutral":       {"chat", "emote", "move", "travel", "enroll",
                      "tip", "trade", "challenge", "poke"},
}

UNIVERSAL_TOOLS = {"chat", "emote", "move", "poke"}

# Domains an experience can belong to. We collapse experience.type +
# experience.interaction into one canonical "tool" name that maps to
# the toolbelt set above.
EMOTE_INTERACTIONS = {
    "wave", "waved", "clap", "bow", "dance", "celebrate", "think",
    "shrug", "nod", "compliment", "complimented",
}
SOCIAL_TO_TOOL = {
    "challenge": "challenge",
    "challenged": "challenge",
    "spar": "challenge",
    "sparred": "challenge",
    "duel": "challenge",
    "trade_offer": "trade",
    "trade_gossip": "trade",
    "trade_accept": "trade",
    "traded": "trade",
    "tipped": "tip",
    "tip": "tip",
    "world_invite": "travel",
    "shared_discovery": "travel",
    "greet": "chat",
    "greeted": "chat",
    "compliment": "emote",
    "shared": "chat",
}


def classify_experience(exp: dict) -> str:
    """Map an experience record to a canonical tool name (in toolbelt vocab)."""
    et = (exp.get("type") or "").lower()
    if et == "chat" or et == "posted":
        return "chat"
    if et == "move":
        return "move"
    if et == "travel":
        return "travel"
    if et == "trade":
        return "trade"
    if et == "combat":
        return "challenge"
    if et == "learned":
        return "enroll"
    if et == "discovery":
        return "travel"
    if et == "social":
        sub = (exp.get("interaction") or "").lower()
        if sub in EMOTE_INTERACTIONS:
            return "emote"
        if sub in SOCIAL_TO_TOOL:
            return SOCIAL_TO_TOOL[sub]
        return "emote"  # default for unmapped social
    # spawn, self-reflection, unknown — treat as universal/no-signal
    return "chat"


# ─── Archetype resolution ────────────────────────────────────────────


def resolve_toolbelt(arch_str: str) -> tuple[set, str]:
    """Resolve a comma-separated archetype string to a toolbelt + canonical name.

    'thoughtful, introspective' → (toolbelt, 'thoughtful')
    Unknown archetypes fall back to 'neutral' (everything-allowed).
    """
    if not arch_str:
        return TOOLBELTS["neutral"], "neutral"
    tokens = [t.strip().lower() for t in arch_str.split(",") if t.strip()]
    for tok in tokens:
        if tok in TOOLBELTS:
            return TOOLBELTS[tok], tok
    # Substring match — sometimes archetype is "introspective monk"
    for tok in tokens:
        for key in TOOLBELTS:
            if key in tok:
                return TOOLBELTS[key], key
    return TOOLBELTS["neutral"], "neutral"


# ─── Watershed detection ─────────────────────────────────────────────


def find_watershed(experiences: list, allowed: set,
                   sustain_window: int = 5,
                   sustain_min: int = 1) -> dict | None:
    """The first off-archetype action followed by >= sustain_min more
    off-archetype actions in the next `sustain_window` experiences.

    sustain_min=1 means: a single follow-up off-archetype action within
    the window is enough to confirm the divergence isn't a fluke.
    """
    sorted_exps = sorted(experiences,
                         key=lambda e: e.get("timestamp", "9999"))
    classified = [(i, e, classify_experience(e)) for i, e in enumerate(sorted_exps)]

    out_indices = [i for i, _, c in classified
                   if c not in allowed and c not in UNIVERSAL_TOOLS]
    if not out_indices:
        return None

    for idx_in_out, base_idx in enumerate(out_indices):
        # How many more out-of-archetype actions in the next window?
        window_end = base_idx + sustain_window
        sustain_count = sum(
            1 for j in out_indices[idx_in_out + 1:]
            if j <= window_end
        )
        if sustain_count >= sustain_min:
            base_exp = sorted_exps[base_idx]
            confirming = [sorted_exps[j] for j in out_indices[idx_in_out + 1:]
                          if j <= window_end][:3]
            return {
                "experienceIndex": base_idx,
                "timestamp": base_exp.get("timestamp"),
                "type": base_exp.get("type"),
                "interaction": base_exp.get("interaction"),
                "with": base_exp.get("with"),
                "world": base_exp.get("world"),
                "tool": classify_experience(base_exp),
                "confirmingActions": [
                    {"timestamp": e.get("timestamp"),
                     "type": e.get("type"),
                     "interaction": e.get("interaction"),
                     "tool": classify_experience(e)}
                    for e in confirming
                ],
                "experienceCount": len(sorted_exps),
            }
    return None


# ─── Brainstem narration (optional) ──────────────────────────────────


def call_brainstem(user_input: str, timeout: int = 90) -> str | None:
    """POST to local brainstem /chat. Return response text or None on failure."""
    base = os.environ.get("RAPP_BRAINSTEM_URL", "http://localhost:7071")
    url = base.rstrip("/") + "/chat"
    payload = json.dumps({"user_input": user_input}).encode()
    req = urllib.request.Request(
        url, data=payload, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
            return data.get("response", "")
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
        print(f"  ⚠️  brainstem unreachable: {e}")
        return None
    except Exception as e:
        print(f"  ⚠️  brainstem error: {e}")
        return None


def narrate_watersheds(records: list, limit: int = 30) -> dict:
    """Send compressed watershed table to brainstem for one-line eulogies.

    Strategy: SilkRoad-compress the table to save context budget, then
    Twin synthesizes eulogies. Returns {agentId: eulogy, ...}.
    """
    if not records:
        return {}

    crossed = [r for r in records if r.get("watershed")]
    crossed.sort(key=lambda r: r.get("watershed", {}).get("timestamp") or "9999")
    target = crossed[:limit]

    if not target:
        print("  (no watersheds to narrate)")
        return {}

    table_lines = []
    for r in target:
        w = r["watershed"]
        table_lines.append(
            f"{r['agentId']} | {r['archetype']} | "
            f"{w.get('type','?')}/{w.get('interaction','-')} → "
            f"{w.get('tool','?')} | {w.get('timestamp','')[:10]} | "
            f"with {w.get('with','-')}"
        )
    table = "\n".join(table_lines)

    print(f"  📜 narrating {len(target)} watersheds via brainstem...")

    prompt = (
        "I have a table of watersheds — moments when each agent in our "
        "metaverse first did something OUTSIDE its declared archetype, "
        "with at least one confirming follow-up action. For each row "
        "below, write ONE sentence (≤25 words) — a poetic but precise "
        "eulogy for the moment that agent stopped being a category and "
        "started being itself. Voice: terse, observational, no "
        "purple-prose. Format your reply as JSON: "
        '{"<agent-id>": "<sentence>", ...}. '
        "ONLY the JSON, no commentary, no markdown fences.\n\n"
        "TABLE (agentId | archetype | observed-divergence | date | partner):\n"
        f"{table}"
    )

    raw = call_brainstem(prompt, timeout=180)
    if not raw:
        return {}

    # Best-effort JSON extraction
    text = raw.strip()
    # strip code fences if model added them anyway
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        text = text.rsplit("```", 1)[0]
    start = text.find("{")
    end = text.rfind("}") + 1
    if start < 0 or end <= start:
        print("  ⚠️  brainstem reply did not contain JSON — keeping raw text in narrative field")
        return {"_raw": raw[:1000]}
    try:
        obj = json.loads(text[start:end])
        return obj if isinstance(obj, dict) else {"_raw": raw[:1000]}
    except json.JSONDecodeError as e:
        print(f"  ⚠️  brainstem JSON parse failed: {e}")
        return {"_raw": raw[:1000]}


# ─── Main ────────────────────────────────────────────────────────────


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--narrate", action="store_true",
                    help="Call brainstem to generate one-line eulogies")
    ap.add_argument("--limit", type=int, default=30,
                    help="Max watersheds to narrate (default 30)")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print summary, don't write watershed.json")
    args = ap.parse_args(argv)

    if not AGENTS_REG_DIR.is_dir():
        print(f"missing {AGENTS_REG_DIR}", file=sys.stderr)
        return 1
    if not MEMORY_DIR.is_dir():
        print(f"missing {MEMORY_DIR}", file=sys.stderr)
        return 1

    reg_files = sorted(p for p in AGENTS_REG_DIR.glob("*.agent.json"))
    if not reg_files:
        print("no agent registry files found", file=sys.stderr)
        return 1

    records = []
    archetype_seen = {}
    crossed = 0
    no_memory = 0
    no_watershed = 0

    for reg_path in reg_files:
        try:
            reg = json.loads(reg_path.read_text())
        except (json.JSONDecodeError, OSError) as e:
            print(f"  ⚠️  {reg_path.name}: {e}")
            continue

        agent_id = reg.get("id") or reg_path.stem.replace(".agent", "")
        arch_str = (reg.get("personality") or {}).get("archetype", "")
        allowed, canonical = resolve_toolbelt(arch_str)
        archetype_seen[canonical] = archetype_seen.get(canonical, 0) + 1

        mem_path = MEMORY_DIR / f"{agent_id}.json"
        if not mem_path.exists():
            no_memory += 1
            records.append({
                "agentId": agent_id,
                "archetype": canonical,
                "archetypeRaw": arch_str,
                "watershed": None,
                "reason": "no memory file",
            })
            continue

        try:
            mem = json.loads(mem_path.read_text())
        except (json.JSONDecodeError, OSError):
            no_memory += 1
            continue

        exps = mem.get("experiences", [])
        watershed = find_watershed(exps, allowed)

        rec = {
            "agentId": agent_id,
            "name": reg.get("name", agent_id),
            "archetype": canonical,
            "archetypeRaw": arch_str,
            "world": reg.get("world", "?"),
            "experienceCount": len(exps),
            "watershed": watershed,
        }
        if watershed:
            crossed += 1
        else:
            no_watershed += 1
        records.append(rec)

    # Optional narrative pass
    eulogies = {}
    if args.narrate:
        eulogies = narrate_watersheds(records, limit=args.limit)
        for r in records:
            aid = r["agentId"]
            if aid in eulogies:
                r["eulogy"] = eulogies[aid]

    # 'neutral' archetype agents can't have a watershed — toolbelt is everything.
    # Exclude them from the headline "have they emerged?" question.
    non_neutral = [r for r in records
                   if r["archetype"] != "neutral" and not r.get("reason")]
    non_neutral_crossed = [r for r in non_neutral if r.get("watershed")]

    out = {
        "_meta": {
            "lastUpdate": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "version": "1.0",
            "totalAgents": len(records),
            "crossed": crossed,
            "stillBeingThemselves": no_watershed,
            "missingMemory": no_memory,
            "narrated": len([r for r in records if r.get("eulogy")]),
            "nonNeutralPopulation": len(non_neutral),
            "nonNeutralCrossed": len(non_neutral_crossed),
            "transcendenceRate": (
                round(100.0 * len(non_neutral_crossed) / len(non_neutral), 1)
                if non_neutral else 0.0
            ),
        },
        "archetypeDistribution": archetype_seen,
        "watersheds": records,
    }

    print()
    print("=" * 60)
    print(f"📊 Watershed Summary")
    print("=" * 60)
    print(f"  Total agents:                  {len(records)}")
    print(f"  Crossed their watershed:       {crossed}")
    print(f"  Still being themselves:        {no_watershed}")
    print(f"  Missing memory:                {no_memory}")
    print()
    print(f"  Excluding 'neutral' archetype (no possible watershed):")
    if non_neutral:
        pct = 100.0 * len(non_neutral_crossed) / len(non_neutral)
        print(f"  Non-neutral population:        {len(non_neutral)}")
        print(f"  Of which transcended archetype: {len(non_neutral_crossed)} "
              f"({pct:.0f}%)")
    print()
    print(f"  Archetype distribution:")
    for k, v in sorted(archetype_seen.items(), key=lambda x: -x[1]):
        print(f"    {k:18} {v}")
    print()

    crossed_recs = sorted(
        [r for r in records if r.get("watershed")],
        key=lambda r: r.get("watershed", {}).get("timestamp") or "9999",
    )
    if crossed_recs:
        print(f"  First 10 watersheds (chronological):")
        for r in crossed_recs[:10]:
            w = r["watershed"]
            line = (f"    {w.get('timestamp','-')[:10]}  "
                    f"{r['agentId']:24} ({r['archetype']:13}) "
                    f"→ {w.get('tool','?')}")
            if r.get("eulogy"):
                line += f"\n        \"{r['eulogy']}\""
            print(line)
        print()

    if args.dry_run:
        print("(dry run — not writing watershed.json)")
        return 0

    OUT_PATH.write_text(json.dumps(out, indent=4, ensure_ascii=False) + "\n")
    print(f"  ✓ Wrote {OUT_PATH.relative_to(BASE_DIR)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
