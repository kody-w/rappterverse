#!/usr/bin/env python3
"""Frame Compiler — write a fresh lispy program per agent per frame.

The premise:

    In a game of Dota / Halo, every bot re-evaluates its priorities every tick.
    "Low HP → flee to fountain." "Enemy in range → engage if I have backup."
    "Tower vulnerable → push if safe."

    We do the same here, but instead of an in-memory behavior tree, we emit
    a literal lispy program to `state/programs/_lispvm/<agentId>.lisp`. The
    VM picks it up via `resolve_program()` on the next encounter, runs it,
    and the program — written from THIS agent's live situation — produces
    the next frame's actions.

    Per-agent. Per-frame. State as code. The git log becomes a recording of
    every agent's brain evolving tick by tick.

Templates pick a behavior CASCADE based on the agent's snapshot:

    1. fleeing      — hp < 30:                go to hub (the "well")
    2. retreating   — threats near + hp < 50: travel away
    3. engaging     — threats near + hp ≥ 50: challenge nearest threat
    4. supporting   — ally near + ally hp low + my hp healthy: tip ally
    5. pushing      — safe + has valid travel/enroll/trade goal: execute goal
    6. socializing  — safe + strong bond near: deepen bond
    7. roaming      — fallback ambient

Each template is a lispy program string. Live values (target ids, world
names, balance) get substituted before write.

Usage as library:

    from frame_compile import compile_for_agent
    compile_for_agent(agent_id, agents, relationships, memory, world)
    # → writes state/programs/_lispvm/<agent_id>.lisp

Usage as CLI (compile every active agent at once):

    python3 scripts/frame_compile.py
    python3 scripts/frame_compile.py --world hub
    python3 scripts/frame_compile.py --dry-run
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
STATE_DIR = BASE_DIR / "state"
MEMORY_DIR = STATE_DIR / "memory"
PROGRAMS_DIR = STATE_DIR / "programs" / "_lispvm"

# ── Template parameters ──────────────────────────────────────────────

LOW_HP = 30          # below this: flee
MID_HP = 50          # below this: retreat instead of engage
THREAT_RADIUS = 5    # units
ALLY_RADIUS = 8
ALLY_HP_LOW = 50     # tip allies whose hp is below this

# The "well" — where fleers retreat to. Hub is the only world with portals
# back out to all others, making it the natural recovery zone.
WELL_WORLD = "hub"

# ── Snapshot ─────────────────────────────────────────────────────────


def _bond_between(edges: list, a: str, b: str) -> int:
    pair = {a, b}
    for e in edges:
        if {e.get("a"), e.get("b")} == pair:
            return int(e.get("score", 0))
    return 0


def _distance(a_pos: dict, b_pos: dict) -> float:
    if not isinstance(a_pos, dict) or not isinstance(b_pos, dict):
        return 999.0
    dx = float(a_pos.get("x", 0)) - float(b_pos.get("x", 0))
    dz = float(a_pos.get("z", 0)) - float(b_pos.get("z", 0))
    return math.sqrt(dx * dx + dz * dz)


def _agent_record(agents: list, agent_id: str) -> dict:
    for a in agents:
        if a.get("id") == agent_id:
            return a
    return {}


def _live_goal(memory: dict) -> dict | None:
    goals = memory.get("goals", []) if isinstance(memory, dict) else []
    for g in goals:
        if g.get("status") == "active":
            return g
    return None


def _goal_target_valid(goal: dict, agents: list) -> bool:
    """Same logic as lisp_vm.p_world_goal_valid — kept local to avoid import cost."""
    if not isinstance(goal, dict):
        return False
    action = (goal.get("action") or "").lower()
    target = goal.get("target") or ""
    if not action or not target:
        return False
    if action == "travel":
        return target in {"hub", "arena", "marketplace", "gallery", "dungeon"}
    if action in ("tip", "trade", "challenge", "poke"):
        for a in agents:
            if a.get("id") == target or a.get("name") == target:
                return True
        return False
    if action == "enroll":
        return len(target) >= 3
    return action in {"chat", "move"}


def _load_teams() -> dict:
    """Load state/teams.json if present. Returns {} if missing."""
    path = STATE_DIR / "teams.json"
    if not path.exists():
        return {}
    try:
        doc = json.loads(path.read_text())
        return doc.get("teams", {})
    except (json.JSONDecodeError, OSError):
        return {}


def _team_for(agent_id: str, world: str, teams: dict) -> str | None:
    world_teams = teams.get(world, {})
    if agent_id in world_teams.get("radiant", []):
        return "radiant"
    if agent_id in world_teams.get("dire", []):
        return "dire"
    return None


def snapshot(agent_id: str,
             agents: list,
             relationships: dict,
             memory: dict,
             economy: dict | None = None,
             teams: dict | None = None) -> dict:
    """Compute the agent's frame-time situation.

    If `teams` (state/teams.json contents) is provided, threats/allies are
    derived from TEAM MEMBERSHIP (radiant vs dire). Otherwise we fall back
    to bond-sign logic (bond ≤ 0 = stranger, bond ≥ 5 = friend).
    """
    teams = teams or {}
    me = _agent_record(agents, agent_id)
    world = me.get("world", "hub")
    hp = int(me.get("hp", 100))
    pos = me.get("position") or {"x": 0, "z": 0}
    edges = (relationships or {}).get("edges", [])

    my_team = _team_for(agent_id, world, teams)

    threats = []
    allies = []
    for a in agents:
        aid = a.get("id")
        if not aid or aid == agent_id:
            continue
        if a.get("world") != world:
            continue
        d = _distance(pos, a.get("position") or {})

        if my_team is not None:
            their_team = _team_for(aid, world, teams)
            # Same team within range → ally; opposing team → threat
            if their_team == my_team and d <= ALLY_RADIUS:
                bond = _bond_between(edges, agent_id, aid)
                allies.append((d, aid, a.get("name", aid), a.get("hp", 100), bond))
            elif their_team and their_team != my_team and d <= THREAT_RADIUS:
                threats.append((d, aid, a.get("name", aid), a.get("hp", 100)))
        else:
            # Untouched fallback — pre-team-assignment behavior
            b = _bond_between(edges, agent_id, aid)
            if d <= THREAT_RADIUS and b <= 0:
                threats.append((d, aid, a.get("name", aid), a.get("hp", 100)))
            if d <= ALLY_RADIUS and b >= 5:
                allies.append((d, aid, a.get("name", aid), a.get("hp", 100), b))
    threats.sort()
    allies.sort()

    # Strongest bonds anywhere (for socializing template)
    me_bonds = []
    for e in edges:
        partner = None
        if e.get("a") == agent_id:
            partner = e.get("b")
        elif e.get("b") == agent_id:
            partner = e.get("a")
        if partner:
            me_bonds.append((int(e.get("score", 0)), partner))
    me_bonds.sort(reverse=True)

    goal = _live_goal(memory)
    goal_valid = _goal_target_valid(goal, agents) if goal else False

    bal = 0
    if economy and isinstance(economy, dict):
        bals = economy.get("balances", {})
        bal = int(bals.get(agent_id, bals.get(me.get("name", ""), 0)))

    role = (teams.get(world, {}).get("roles", {}) or {}).get(agent_id)

    return {
        "agent_id": agent_id,
        "name": me.get("name", agent_id),
        "world": world,
        "team": my_team,
        "role": role,
        "hp": hp,
        "x": float(pos.get("x", 0)),
        "z": float(pos.get("z", 0)),
        "balance": bal,
        "threats": threats,
        "allies": allies,
        "top_bonds": me_bonds[:3],
        "goal": goal,
        "goal_valid": goal_valid,
        "archetype": ((me.get("personality") or {}).get("archetype") or "neutral").lower(),
    }


# ── Templates ────────────────────────────────────────────────────────


def _esc(s: str) -> str:
    """Escape for lispy string literal."""
    return str(s).replace("\\", "\\\\").replace('"', '\\"')


def _t_fleeing(snap: dict) -> str:
    return f''';; FLEEING — hp {snap["hp"]}/100, fall back to {WELL_WORLD}
(if (eq? (world/world) "{WELL_WORLD}")
    (act/chat
      (llm/think
        "I'm hurt and just made it to {WELL_WORLD}. Say one short, in-character recovery line. No quotes."))
    (act/travel "{WELL_WORLD}"
      (llm/think
        "I'm at {snap["hp"]} hp — falling back to {WELL_WORLD} to recover. One terse line. No quotes.")))
'''


def _t_retreating(snap: dict) -> str:
    threat_name = snap["threats"][0][2] if snap["threats"] else "trouble"
    safer = WELL_WORLD if snap["world"] != WELL_WORLD else "marketplace"
    return f''';; RETREATING — threat {{ {_esc(threat_name)} }} near, hp {snap["hp"]}/100
(act/travel "{safer}"
  (llm/think
    "{_esc(threat_name)} is too close and I'm not strong enough to fight. Going to {safer}. One terse line. No quotes."))
'''


def _t_engaging(snap: dict) -> str:
    t_id, t_name = snap["threats"][0][1], snap["threats"][0][2]
    return f''';; ENGAGING — threat {_esc(t_name)} in range, hp {snap["hp"]}/100
(act/challenge "{_esc(t_id)}"
  (llm/think
    "{_esc(t_name)} is right in front of me and I can take them. One sharp challenge line, in-character. No quotes."))
'''


def _t_supporting(snap: dict) -> str:
    a_id, a_name = snap["allies"][0][1], snap["allies"][0][2]
    return f''';; SUPPORTING — ally {_esc(a_name)} hurt nearby, my hp {snap["hp"]}/100
(act/tip "{_esc(a_id)}" 10
  (llm/think
    "Ally {_esc(a_name)} is hurting. Tipping them as support. One short, warm line. No quotes."))
'''


def _t_pushing(snap: dict) -> str:
    g = snap["goal"]
    action = g.get("action", "chat")
    target = g.get("target", "")
    reason = g.get("reason", "")
    return f''';; PUSHING — safe (no threats, hp {snap["hp"]}), executing goal: {action} {_esc(target)}
(let ((why (llm/think
             "Pushing my goal: {action} toward {_esc(target)} because {_esc(reason)}. One sentence — confident, in-character. No quotes.")))
  (cond
    ((eq? "{action}" "travel")    (act/travel "{_esc(target)}" why))
    ((eq? "{action}" "enroll")    (act/enroll "{_esc(target)}"))
    ((eq? "{action}" "tip")       (act/tip "{_esc(target)}" 10 why))
    ((eq? "{action}" "trade")     (act/trade "{_esc(target)}"))
    ((eq? "{action}" "challenge") (act/challenge "{_esc(target)}" why))
    (else                         (act/chat why))))
'''


def _t_socializing(snap: dict) -> str:
    score, friend_id = snap["top_bonds"][0]
    return f''';; SOCIALIZING — safe (hp {snap["hp"]}), bond with {_esc(friend_id)}={score}
(let ((choice (llm/choose
                "My closest friend is {_esc(friend_id)} (bond {score}). Best move to deepen the bond right now: tip, travel, or chat?"
                '("tip" "travel" "chat"))))
  (cond
    ((eq? choice "tip")
     (act/tip "{_esc(friend_id)}" 10 "for {_esc(friend_id)}"))
    ((eq? choice "travel")
     (let ((fworld (world/agent-world "{_esc(friend_id)}")))
       (if (eq? fworld (world/world))
           (act/chat (llm/think "Friend {_esc(friend_id)} is right here. Say something warm and specific. 1-2 sentences. No quotes."))
           (act/travel fworld "visiting {_esc(friend_id)}"))))
    (else
     (act/chat (llm/think "Talking to my close friend {_esc(friend_id)} (bond {score}). Say something authentic. 1-2 sentences. No quotes.")))))
'''


def _t_roaming(snap: dict) -> str:
    return f''';; ROAMING — ambient, hp {snap["hp"]}, world {snap["world"]}
(act/chat
  (llm/think
    (str/concat
      "Recent vibe in " (world/world) " — " (world/recent-vibe 3)
      ". Add one in-character thought: an observation, question, or reaction. 1-2 sentences. No quotes.")))
'''


# ── Cascade ──────────────────────────────────────────────────────────


def pick_template(snap: dict) -> tuple[str, str]:
    """Halo-style priority cascade. Returns (template_name, program_source)."""
    hp = snap["hp"]
    threats = snap["threats"]
    allies = snap["allies"]
    goal = snap["goal"]
    goal_valid = snap["goal_valid"]
    arch = snap["archetype"]
    world = snap["world"]

    # Only fighters/aggressives, or anyone in the arena, treat strangers
    # as threats. Elsewhere a "stranger nearby" is just a neighbor.
    combat_active = (
        world == "arena"
        or any(tag in arch for tag in ("aggressive", "fighter"))
    )

    # 1. self-preservation
    if hp < LOW_HP:
        return ("fleeing", _t_fleeing(snap))

    # 2/3. threat response — only when in combat context
    if combat_active and threats:
        if hp < MID_HP:
            return ("retreating", _t_retreating(snap))
        return ("engaging", _t_engaging(snap))

    # 4. ally support
    for d, aid, name, ahp, bond in allies:
        if ahp < ALLY_HP_LOW and hp >= MID_HP and snap["balance"] >= 10:
            return ("supporting", _t_supporting({**snap, "allies": [(d, aid, name, ahp, bond)]}))

    # 5. goal pursuit — only if it's still pointing somewhere real
    if goal and goal_valid:
        return ("pushing", _t_pushing(snap))

    # 6. socializing — strong bond available
    if snap["top_bonds"] and snap["top_bonds"][0][0] >= 5:
        return ("socializing", _t_socializing(snap))

    # 7. roam
    return ("roaming", _t_roaming(snap))


# ── Compile + write ──────────────────────────────────────────────────


def render_program(snap: dict, template_name: str, body: str) -> str:
    """Wrap a template body in a header so the .lisp file documents the
    inputs that compiled it. The git diff between frames becomes a record
    of every agent's brain shifting."""
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    threats_line = ", ".join(t[2] for t in snap["threats"][:3]) or "none"
    allies_line = ", ".join(a[2] for a in snap["allies"][:3]) or "none"
    goal_str = (
        f"{snap['goal'].get('action','?')}→{snap['goal'].get('target','?')}"
        f"{' (zombie)' if snap['goal'] and not snap['goal_valid'] else ''}"
        if snap["goal"] else "none"
    )
    team_line = snap.get("team") or "unassigned"
    header = f""";; ── {snap['name']} ({snap['agent_id']}) ────────────────────────────
;; compiled at {ts} for frame in '{snap['world']}'
;; team:      {team_line}
;; template:  {template_name}
;; hp:        {snap['hp']}/100
;; pos:       ({snap['x']:.1f}, {snap['z']:.1f})
;; balance:   {snap['balance']} RAPP
;; archetype: {snap['archetype']}
;; threats:   {threats_line}
;; allies:    {allies_line}
;; goal:      {goal_str}
;; bonds:     {len(snap['top_bonds'])} top (max={snap['top_bonds'][0][0] if snap['top_bonds'] else 0})
;;
;; This file is REGENERATED only when this agent's tactical situation
;; changes (see should_recompile() in scripts/frame_compile.py). When
;; nothing meaningful has shifted, the agent keeps running yesterday's
;; program. That sparseness IS the emergence — not every entity reacts
;; every tick; only those whose world has changed update.

"""
    return header + body


# ── Change detection (for selective recompile) ───────────────────────


INDEX_PATH = PROGRAMS_DIR / "_index.json"
STATUS_PATH = PROGRAMS_DIR / "_status.json"


def _load_index() -> dict:
    if not INDEX_PATH.exists():
        return {}
    try:
        return json.loads(INDEX_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def _save_index(index: dict) -> None:
    PROGRAMS_DIR.mkdir(parents=True, exist_ok=True)
    INDEX_PATH.write_text(json.dumps(index, indent=2, ensure_ascii=False) + "\n")


def _save_status(status: dict) -> None:
    """Frontend-facing snapshot of every agent's current tactical state.

    Same shape regardless of whether the agent recompiled this tick — the
    frontend reads this once per poll and applies template-specific visuals
    (engaging = red lean, fleeing = retreat, pushing = forward stride, etc.)
    so the substrate is VISIBLE in the 3D world. Pulled from raw.githubuser-
    content.com just like all other state — same architecture, no new server.
    """
    PROGRAMS_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "_meta": {
            "lastUpdate": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "count": len(status),
            "version": "1.0",
        },
        "agents": status,
    }
    STATUS_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")


def _hp_band(hp: int) -> str:
    if hp < LOW_HP:
        return "low"
    if hp < MID_HP:
        return "mid"
    return "ok"


def _snap_signature(snap: dict) -> dict:
    """Reduce a snapshot to the fields that ACTUALLY pick a template.

    Matches the cascade in pick_template() exactly. Two snapshots with the
    same signature will compile to the same program, so we can skip writing.
    Stored in _index.json as the "last seen" frame state per agent.
    """
    threats_top = snap["threats"][0][1] if snap["threats"] else None
    has_hurt_ally = any(a[3] < ALLY_HP_LOW for a in snap["allies"])
    has_hurt_ally_id = next(
        (a[1] for a in snap["allies"] if a[3] < ALLY_HP_LOW),
        None,
    )
    goal = snap["goal"] or {}
    return {
        "world": snap["world"],
        "hp_band": _hp_band(snap["hp"]),
        "threat_top": threats_top,
        "threat_count": len(snap["threats"]),
        "hurt_ally": has_hurt_ally_id,
        "balance_band": "rich" if snap["balance"] >= 25 else (
                         "mid" if snap["balance"] >= 10 else "broke"),
        "goal_action": goal.get("action") if snap["goal"] else None,
        "goal_target": goal.get("target") if snap["goal"] else None,
        "goal_valid": bool(snap["goal_valid"]),
        "top_bond_score": snap["top_bonds"][0][0] if snap["top_bonds"] else 0,
        "top_bond_partner": snap["top_bonds"][0][1] if snap["top_bonds"] else None,
    }


def should_recompile(snap: dict, last_signature: dict | None) -> tuple[bool, str]:
    """Has this agent's tactical situation changed enough to recompile?

    Returns (changed, reason). Any non-empty reason on True is shown in
    the summary so you can see the propagation frontier each tick.
    """
    if last_signature is None:
        return True, "first compile"

    sig = _snap_signature(snap)
    diffs = []
    for key in sig:
        if sig[key] != last_signature.get(key):
            diffs.append(f"{key}:{last_signature.get(key)}→{sig[key]}")
    if diffs:
        return True, ", ".join(diffs[:2])  # show two most useful diffs
    return False, "stable"


def compile_for_agent(agent_id: str,
                      agents: list,
                      relationships: dict,
                      memory: dict,
                      economy: dict | None = None,
                      write: bool = True,
                      changed_only: bool = False,
                      index: dict | None = None,
                      teams: dict | None = None) -> dict:
    """Compile this agent's program for the current frame.

    If changed_only=True and `index` is provided, will skip writing when the
    agent's tactical signature is unchanged since last compile. The returned
    dict includes `template`, `program`, `recompiled` (bool), and `reason`.
    """
    snap = snapshot(agent_id, agents, relationships, memory, economy,
                    teams=teams)
    template_name, body = pick_template(snap)
    program = render_program(snap, template_name, body)

    # Change-detection
    last_sig = (index or {}).get(agent_id) if changed_only else None
    if changed_only:
        recompile, reason = should_recompile(snap, last_sig)
    else:
        recompile, reason = True, "forced"

    if write and recompile:
        PROGRAMS_DIR.mkdir(parents=True, exist_ok=True)
        out = PROGRAMS_DIR / f"{agent_id}.lisp"
        out.write_text(program, encoding="utf-8")
        if index is not None:
            index[agent_id] = _snap_signature(snap)

    return {
        **snap,
        "template": template_name,
        "program": program,
        "recompiled": recompile,
        "reason": reason,
    }


def compile_all(world: str | None = None,
                only_named: bool = False,
                dry_run: bool = False,
                changed_only: bool = False) -> list[dict]:
    """Compile programs for every active agent (optionally filtered by world).

    only_named: skip auto-spawned agents (those with id ending in random suffix
    rather than the curated NPCs). Currently implemented as: skip if no
    agents/<id>.agent.json registry entry exists.

    changed_only: only rewrite .lisp files whose tactical signature differs
    from the last compile (per state/programs/_lispvm/_index.json). This is
    the "selective recompilation" mode — emergence is sparser when only
    the propagation frontier reacts each tick.
    """
    agents_doc = json.loads((STATE_DIR / "agents.json").read_text())
    agents = agents_doc.get("agents", [])
    rel_doc = json.loads((STATE_DIR / "relationships.json").read_text())
    economy_path = STATE_DIR / "economy.json"
    economy = json.loads(economy_path.read_text()) if economy_path.exists() else {}
    teams = _load_teams()  # honored by snapshot() if present

    reg_dir = BASE_DIR / "agents"

    index = _load_index()
    starting_index = dict(index)

    results = []
    status = {}  # frontend-facing snapshot (agent_id → tactical state)
    for a in agents:
        aid = a.get("id")
        if not aid:
            continue
        if world and a.get("world") != world:
            continue
        if only_named and not (reg_dir / f"{aid}.agent.json").exists():
            continue

        mem_path = MEMORY_DIR / f"{aid}.json"
        memory = json.loads(mem_path.read_text()) if mem_path.exists() else {}

        result = compile_for_agent(
            aid, agents, rel_doc, memory, economy,
            write=not dry_run,
            changed_only=changed_only,
            index=index,
            teams=teams,
        )
        results.append(result)

        # Always populate status for ALL agents in the run, even if they
        # didn't recompile this tick — frontend needs every agent's current
        # template to drive visuals.
        status[aid] = {
            "template": result["template"],
            "world": result["world"],
            "team": result.get("team"),
            "role": result.get("role"),
            "hp": result["hp"],
            "x": result["x"],
            "z": result["z"],
            "threat_count": len(result["threats"]),
            "threat_top": (result["threats"][0][1] if result["threats"] else None),
            "ally_count": len(result["allies"]),
            "hurt_ally": next(
                (al[1] for al in result["allies"] if al[3] < ALLY_HP_LOW),
                None,
            ),
            "goal_action": (result["goal"] or {}).get("action") if result["goal"] else None,
            "goal_target": (result["goal"] or {}).get("target") if result["goal"] else None,
            "goal_valid": result["goal_valid"],
            "top_bond_partner": (result["top_bonds"][0][1] if result["top_bonds"] else None),
            "top_bond_score": (result["top_bonds"][0][0] if result["top_bonds"] else 0),
        }

    # Always persist the index after a live run — keeps subsequent
    # --changed-only invocations honest. Skip on dry-run.
    if not dry_run and index != starting_index:
        _save_index(index)

    # Status is small (~210 entries, ~30KB) and must reflect the FULL
    # active population so the frontend can paint every agent. Rewrite
    # every live full-population run, even when no .lisp files changed —
    # otherwise stale data lingers when an agent shifts world or hp.
    if not dry_run and not world and status:
        _save_status(status)

    return results


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--world", help="Only compile agents in this world.")
    ap.add_argument("--only-named", action="store_true",
                    help="Skip auto-spawned agents (no registry entry).")
    ap.add_argument("--dry-run", action="store_true",
                    help="Show the cascade per agent, don't write files.")
    ap.add_argument("--summary", action="store_true",
                    help="Just print template counts, no per-agent detail.")
    ap.add_argument("--changed-only", action="store_true",
                    help="Only rewrite .lisp files for agents whose tactical "
                         "situation changed since the last compile. The "
                         "propagation frontier each tick.")
    args = ap.parse_args(argv)

    results = compile_all(world=args.world, only_named=args.only_named,
                          dry_run=args.dry_run,
                          changed_only=args.changed_only)

    from collections import Counter
    template_counts = Counter(r["template"] for r in results)
    recompiled = [r for r in results if r["recompiled"]]
    skipped = [r for r in results if not r["recompiled"]]

    print()
    print("=" * 60)
    print(f"⚙️  Frame Compiler — {len(results)} agents evaluated")
    print(f"   world: {args.world or 'all'}")
    print(f"   mode:  {'DRY RUN' if args.dry_run else 'LIVE'}"
          f"{' (changed-only)' if args.changed_only else ''}")
    print("=" * 60)
    if args.changed_only:
        print(f"  recompiled this frame:  {len(recompiled)}")
        print(f"  unchanged (kept prev):  {len(skipped)}")
        print()
    print(f"  template distribution:")
    for tmpl, n in template_counts.most_common():
        recomp_n = sum(1 for r in recompiled if r["template"] == tmpl)
        print(f"    {tmpl:14} {n:4} ({recomp_n} recompiled)")
    print()

    if args.changed_only and recompiled and not args.summary:
        print(f"  propagation frontier (top 10 reasons agents recompiled):")
        for r in recompiled[:10]:
            print(f"    {r['agent_id']:25} {r['template']:11} "
                  f"← {r['reason']}")
        if len(recompiled) > 10:
            print(f"    ... and {len(recompiled) - 10} more")
        print()

    if not args.summary:
        # Show interesting rows: anyone fleeing, retreating, engaging,
        # supporting (the tactical ones)
        tactical = [r for r in results
                    if r["template"] in ("fleeing", "retreating", "engaging", "supporting")]
        if tactical:
            print(f"  tactical agents ({len(tactical)}):")
            for r in tactical[:20]:
                threats = ", ".join(t[2] for t in r["threats"][:2]) or "-"
                print(f"    {r['template']:11} {r['agent_id']:25} "
                      f"hp={r['hp']:3} threats=[{threats}]")
            if len(tactical) > 20:
                print(f"    ... and {len(tactical) - 20} more")
            print()

    if not args.dry_run:
        write_count = len(recompiled) if args.changed_only else len(results)
        print(f"  ✓ wrote {write_count} programs to "
              f"{PROGRAMS_DIR.relative_to(BASE_DIR)}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
