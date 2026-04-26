#!/usr/bin/env python3
"""agent_bakeoff.py — parallel multi-variant bakeoff over agent.py.

Calls `agent.py --agent X --variant V --seed S` for every (agent, variant)
pair concurrently, collects the JSON deltas, and scores them. Tells us
which variant of agent.py produces the most differentiated/coherent
behavior so we know what patterns to fold into the canonical agent.py.

Usage:
    python scripts/agent_bakeoff.py
    python scripts/agent_bakeoff.py --agents 8 --variants local,brainstem,rapp
    python scripts/agent_bakeoff.py --seed 42 --json > report.json
"""
from __future__ import annotations

import argparse
import json
import random
import subprocess
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AGENT_PY = ROOT / "agent.py"
STATE = ROOT / "state"


def load_agent_ids(n: int, seed: int) -> list[str]:
    """Pick N system agent ids deterministically by seed."""
    agents_path = STATE / "agents.json"
    data = json.loads(agents_path.read_text())
    ids = [a["id"] for a in data.get("agents", [])
           if a.get("status") == "active"
           and a.get("controller", "system") == "system"]
    rng = random.Random(seed)
    rng.shuffle(ids)
    return ids[:n]


def run_one(agent_id: str, variant: str, seed: int) -> dict:
    """Run agent.py once and parse its JSON delta."""
    proc = subprocess.run(
        [sys.executable, str(AGENT_PY),
         "--agent", agent_id, "--variant", variant, "--seed", str(seed)],
        capture_output=True, text=True, timeout=60,
    )
    if proc.returncode != 0:
        return {"agent_id": agent_id, "variant": variant, "seed": seed,
                "error": f"exit {proc.returncode}: {proc.stderr.strip()[:200]}"}
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        return {"agent_id": agent_id, "variant": variant, "seed": seed,
                "error": f"bad JSON: {e}", "raw": proc.stdout[:500]}


def run_matrix(agent_ids: list[str], variants: list[str],
               seed: int, parallel: int) -> list[dict]:
    """Fan out (agent × variant) calls in parallel."""
    jobs = [(aid, v, seed) for aid in agent_ids for v in variants]
    results = []
    with ThreadPoolExecutor(max_workers=parallel) as ex:
        futs = [ex.submit(run_one, aid, v, s) for aid, v, s in jobs]
        for f in as_completed(futs):
            results.append(f.result())
    return results


def score(results: list[dict]) -> dict:
    """Compute comparison metrics per variant + per agent."""
    by_variant: dict[str, list[dict]] = {}
    by_agent: dict[str, list[dict]] = {}
    for r in results:
        by_variant.setdefault(r.get("variant", "?"), []).append(r)
        by_agent.setdefault(r.get("agent_id", "?"), []).append(r)

    # Per-variant: action distribution, error rate, reasoning richness
    variant_scores: dict[str, dict] = {}
    for v, rs in by_variant.items():
        actions = [r.get("decision", {}).get("action") for r in rs]
        actions = [a for a in actions if a]
        errors = [r for r in rs if "error" in r or
                  (r.get("decision", {}) or {}).get("error")]
        reasonings = [(r.get("decision", {}) or {}).get("reasoning", "")
                      for r in rs]
        reasoning_lens = [len(x) for x in reasonings if x]
        variant_scores[v] = {
            "n": len(rs),
            "actions": dict(Counter(actions)),
            "action_diversity": len(set(actions)),
            "error_rate": round(len(errors) / max(len(rs), 1), 3),
            "avg_reasoning_chars": int(sum(reasoning_lens) / len(reasoning_lens))
                                   if reasoning_lens else 0,
        }

    # Per-agent divergence: did variants disagree on the SAME agent?
    divergence = {}
    for aid, rs in by_agent.items():
        picks = {r.get("variant"): (r.get("decision", {}) or {}).get("action")
                 for r in rs}
        unique = len({a for a in picks.values() if a})
        divergence[aid] = {"picks": picks, "unique_actions": unique}

    overall = {
        "total_pairs": len(results),
        "agents": len(by_agent),
        "variants": len(by_variant),
        "high_divergence_agents": sum(1 for d in divergence.values()
                                      if d["unique_actions"] >= 2),
    }
    return {
        "overall": overall,
        "per_variant": variant_scores,
        "per_agent_divergence": divergence,
    }


def render(results: list[dict], scores: dict) -> str:
    out = ["", "═" * 72,
           "  AGENT FACTORY BAKEOFF — variants of agent.py, parallel",
           "═" * 72, ""]
    o = scores["overall"]
    out.append(f"  pairs={o['total_pairs']}  agents={o['agents']}  "
               f"variants={o['variants']}  divergent_agents={o['high_divergence_agents']}")
    out.append("")
    out.append("── per-variant scoreboard ──")
    for v, s in scores["per_variant"].items():
        out.append(f"  {v:>10s}  n={s['n']:3d}  diversity={s['action_diversity']}  "
                   f"err={s['error_rate']:.0%}  avgreason={s['avg_reasoning_chars']}c")
        out.append(f"             actions: {s['actions']}")
    out.append("")
    out.append("── divergence sample (first 6 agents) ──")
    sample = list(scores["per_agent_divergence"].items())[:6]
    for aid, d in sample:
        if d["unique_actions"] >= 2:
            badge = "  ⚡"
        else:
            badge = "    "
        picks = "  ".join(f"{v}={a or 'X'}" for v, a in d["picks"].items())
        out.append(f"{badge} {aid:25s}  {picks}")
    out.append("")
    return "\n".join(out)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agents", type=int, default=6,
                        help="how many agents to test (default 6)")
    parser.add_argument("--variants", default="local,brainstem,rapp",
                        help="comma-separated agent.py variants to compare")
    parser.add_argument("--seed", type=int, default=42,
                        help="rng seed for agent selection + variant runs")
    parser.add_argument("--parallel", type=int, default=6,
                        help="max concurrent subprocess calls")
    parser.add_argument("--json", action="store_true",
                        help="emit machine-readable JSON")
    args = parser.parse_args()

    agent_ids = load_agent_ids(args.agents, args.seed)
    variants = [v.strip() for v in args.variants.split(",") if v.strip()]
    results = run_matrix(agent_ids, variants, args.seed, args.parallel)
    scores = score(results)

    if args.json:
        print(json.dumps({"results": results, "scores": scores}, indent=2))
    else:
        print(render(results, scores))


if __name__ == "__main__":
    main()
