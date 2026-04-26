#!/usr/bin/env python3
"""Bakeoff harness — run engine variants side-by-side, score the outputs.

Both `agent_dispatch.py` paths write to state, so for a clean
side-by-side we use `--dry-run` (no state mutation) and capture stdout.
This is Phase 1 of the dream-catcher protocol: same input, two outputs,
eyeball + metric the difference. Phase 2 will add git-worktree isolation
for full state-mutating runs.

Usage:
    python scripts/bakeoff.py                          # 5 agents, both variants
    python scripts/bakeoff.py --max-agents 10
    python scripts/bakeoff.py --variants local,brainstem
    python scripts/bakeoff.py --json                   # machine-readable
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DISPATCH = ROOT / "scripts" / "agent_dispatch.py"

# Variant name → extra flags passed to agent_dispatch.py
VARIANTS = {
    "local":     [],              # default agent_brain.py path
    "brainstem": ["--brainstem"], # soul-file path with toolbelts
    "no_llm":    ["--no-llm"],    # baseline: dialogue lines only
}


def run_variant(name: str, max_agents: int) -> dict:
    """Run one dispatch variant in dry-run and capture the result."""
    flags = VARIANTS.get(name)
    if flags is None:
        raise ValueError(f"unknown variant: {name}")
    cmd = [
        sys.executable, str(DISPATCH),
        "--all", "--max-agents", str(max_agents),
        "--no-push", "--dry-run",
        *flags,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    return {
        "variant": name,
        "cmd": " ".join(cmd[1:]),
        "stdout": proc.stdout,
        "stderr": proc.stderr,
        "returncode": proc.returncode,
    }


def score(result: dict) -> dict:
    """Extract comparison metrics from a variant's stdout.

    Lines look like:
      🚶 Name moved
      ✨ Name claps
      🧠 agent-001 [chat] "message text..."
      🌀 Name traveled to gallery
    """
    out = result["stdout"]

    # Per-agent action lines start with one of these emojis.
    action_emojis = ("🤖", "🚶", "✨", "🧠", "🌀", "🤝", "🪙", "💬", "⚔️", "📚", "👋")
    action_lines = [
        ln.strip() for ln in out.splitlines()
        if ln.strip() and any(ln.lstrip().startswith(e) for e in action_emojis)
        and "Agent " not in ln  # skip the header banner
    ]

    # Pull chat content for uniqueness scoring
    chat_pattern = re.compile(r'\[chat\]\s*"([^"]*)"|moved \(([^)]*)\)')
    chats = []
    for ln in action_lines:
        m = chat_pattern.search(ln)
        if m:
            chats.append(m.group(1) or m.group(2) or "")

    # Action-type histogram (first emoji on each action line)
    types = {}
    for ln in action_lines:
        head = ln.split()[0] if ln else ""
        types[head] = types.get(head, 0) + 1

    # Reference scoring: how often does the line mention another agent by name?
    # Heuristic: capitalized word followed by lowercase = likely an agent name reference.
    name_ref = re.compile(r"\b[A-Z][a-z]+(?:[A-Z][a-z]+)+\b")
    refs = sum(1 for ln in action_lines for _ in name_ref.findall(ln))

    return {
        "actions": len(action_lines),
        "messages": sum(1 for c in chats if c),
        "unique_messages": len({c for c in chats if c}),
        "action_types": types,
        "agent_references": refs,
    }


def render_report(results: list[dict], scores: list[dict]) -> str:
    lines = ["", "═" * 68, "  BAKEOFF — engine variant comparison", "═" * 68, ""]
    for r, s in zip(results, scores):
        lines.append(f"── {r['variant']:>10s} ── ({r['cmd']})")
        lines.append(f"   actions={s['actions']}  messages={s['messages']}  "
                     f"unique={s['unique_messages']}  refs={s['agent_references']}")
        lines.append(f"   types: {s['action_types']}")
        lines.append("")
    lines.append("── tail of each variant's output ──")
    for r in results:
        lines.append(f"\n[{r['variant']}]")
        for ln in (r["stdout"].splitlines() or [""])[-8:]:
            lines.append(f"  {ln}")
    lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-agents", type=int, default=5)
    parser.add_argument("--variants", default="local,brainstem",
                        help="comma-separated subset of: " + ",".join(VARIANTS))
    parser.add_argument("--json", action="store_true",
                        help="emit machine-readable JSON instead of text report")
    args = parser.parse_args()

    variant_names = [v.strip() for v in args.variants.split(",") if v.strip()]
    results = [run_variant(v, args.max_agents) for v in variant_names]
    scores = [score(r) for r in results]

    if args.json:
        print(json.dumps({
            "max_agents": args.max_agents,
            "variants": [
                {**r, "score": s} for r, s in zip(results, scores)
            ],
        }, indent=2))
    else:
        print(render_report(results, scores))


if __name__ == "__main__":
    main()
