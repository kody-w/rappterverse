#!/usr/bin/env python3
"""
Lisp Soul Compiler — Data Slosh Phase

Reads agent state, actions, chat, relationships, goals, and traits.
Compiles per-agent S-expression programs into game_state.worlds[wid].routines[].
The RappterVM parses these once on frame arrival and evaluates them at 20Hz.

Data is code. Code is data. Agent state IS the program.

Even if no new frame ever arrives, agents keep living from these routines.
The world goes on with what it has from the last slosh.
"""

import json
import glob
import os
from datetime import datetime, timezone

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE = os.path.join(BASE, "state")


def q(s):
    """Quote a string for Lisp embedding."""
    return '"' + s.replace('"', '\\"') + '"'


def load(path):
    try:
        with open(os.path.join(STATE, path)) as f:
            return json.load(f)
    except Exception:
        return {}


def main():
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    agents = load("agents.json")
    actions = load("actions.json")
    chat = load("chat.json")
    game = load("game_state.json")
    frame = load("frame_counter.json")
    rels = load("relationships.json")

    frame_num = frame.get("frame", 0)
    changed = False

    # ── Standard slosh: populations + time_of_day ──
    world_pop = {}
    for a in agents.get("agents", []):
        w = a.get("world", "hub")
        world_pop[w] = world_pop.get(w, 0) + 1
    for wid, wpop in world_pop.items():
        if wid in game.get("worlds", {}):
            old = game["worlds"][wid].get("population", 0)
            if old != wpop:
                game["worlds"][wid]["population"] = wpop
                changed = True

    times = ["dawn", "day", "dusk", "night"]
    for wid, wdata in game.get("worlds", {}).items():
        old_time = wdata.get("time_of_day", "day")
        if frame_num % 6 == 0:
            idx = times.index(old_time) if old_time in times else 0
            new_time = times[(idx + 1) % len(times)]
            if new_time != old_time:
                wdata["time_of_day"] = new_time
                changed = True

    # ── Load memories for goal-driven behavior ──
    memories = {}
    for mf in glob.glob(os.path.join(STATE, "memory", "*.json")):
        try:
            with open(mf) as f:
                md = json.load(f)
            mid = os.path.basename(mf).replace(".json", "")
            memories[mid] = md
        except Exception:
            pass

    # ── LISP SOUL COMPILER ──
    for wid, wdata in game.get("worlds", {}).items():
        routines = []
        world_agents = [a for a in agents.get("agents", []) if a.get("world") == wid]
        world_chat = [m for m in chat.get("messages", [])[-30:] if m.get("world") == wid]

        # Chat graph: who talked to whom
        chat_graph = {}
        for m in world_chat:
            aid = m.get("author", {}).get("id", "")
            if aid:
                chat_graph.setdefault(aid, set())
                for m2 in world_chat:
                    aid2 = m2.get("author", {}).get("id", "")
                    if aid2 and aid2 != aid:
                        chat_graph[aid].add(aid2)

        # Relationship edges per agent
        rel_graph = {}
        for edge in rels.get("edges", []):
            a, b, score = edge.get("a", ""), edge.get("b", ""), edge.get("score", 0)
            if score >= 2:
                rel_graph.setdefault(a, []).append((b, score))
                rel_graph.setdefault(b, []).append((a, score))

        for ag in world_agents:
            aid = ag.get("id", "")
            if not aid:
                continue
            # ── Self-authored override: state/programs/<aid>.lisp ──
            # Lispy Mirror — when an agent's twin has authored their own
            # priority gates and action bias, honor it instead of
            # synthesizing from state. Read more in: state/programs/README
            program_path = os.path.join(STATE, "programs", f"{aid}.lisp")
            if os.path.isfile(program_path):
                try:
                    with open(program_path) as f:
                        raw = f.read()
                    # Strip comment-only lines (;; …) so we get just the form
                    body = "\n".join(
                        line for line in raw.splitlines()
                        if line.strip() and not line.strip().startswith(";;")
                    ).strip()
                    if body.startswith("(do ") and body.endswith(")"):
                        routines.append({
                            "agentId": aid,
                            "program": body,
                            "source": "self-authored",
                        })
                        changed = True
                        continue  # skip auto-compilation for this agent
                except OSError:
                    pass

            pos = ag.get("position", {})
            px = pos.get("x", 0)
            pz = pos.get("z", 0)
            mood = ag.get("mood", ag.get("state", "neutral"))
            mem = memories.get(aid, {})
            goals = [g for g in mem.get("goals", []) if g.get("status") == "active"]
            traits = ag.get("traits", {})

            # ── Compose S-expression soul program ──
            exprs = []

            # (1) HOME ORBIT — patrol near position, explorer trait widens radius
            wander_radius = 3 + traits.get("explorer", 0) * 8
            exprs.append(
                f"(if (< (mod (floor (elapsed)) 20) 10) "
                f"(wander {q(aid)} {wander_radius:.1f}) "
                f"(move-toward {q(aid)} {px:.1f} {pz:.1f} 0.01))"
            )

            # (2) SOCIAL GRAVITY — approach recent chat partners
            partners = list(chat_graph.get(aid, set()))
            for p in partners[:2]:
                speed = 0.010 + traits.get("social", 0) * 0.008
                exprs.append(
                    f"(if (> (distance {q(aid)} {q(p)}) 5) "
                    f"(move-toward {q(aid)} "
                    f"(get (agent-pos {q(p)}) \"x\") "
                    f"(get (agent-pos {q(p)}) \"z\") "
                    f"{speed:.3f}) nil)"
                )

            # (3) BOND MAGNETISM — gravitate toward strong relationships
            agent_rels = sorted(rel_graph.get(aid, []), key=lambda x: -x[1])
            for partner, score in agent_rels[:1]:
                strength = min(score / 20, 0.015)
                exprs.append(
                    f"(if (and (> (distance {q(aid)} {q(partner)}) 4) "
                    f"(< (mod (floor (elapsed)) 30) 15)) "
                    f"(move-toward {q(aid)} "
                    f"(get (agent-pos {q(partner)}) \"x\") "
                    f"(get (agent-pos {q(partner)}) \"z\") "
                    f"{strength:.4f}) "
                    f"(face-toward {q(aid)} "
                    f"(get (agent-pos {q(partner)}) \"x\") "
                    f"(get (agent-pos {q(partner)}) \"z\")))"
                )

            # (4) GOAL DRIVE
            for goal in goals[:1]:
                gtype = goal.get("type", "")
                if gtype in ("explore", "wander"):
                    exprs.append(f"(if (= (mod (floor (elapsed)) 8) 0) (wander {q(aid)} 12) nil)")
                elif gtype in ("social", "generosity"):
                    exprs.append(
                        f"(if (= (mod (floor (elapsed)) 12) 0) "
                        f"(let (near (nearest-agent {q(aid)})) "
                        f"(if near (move-toward {q(aid)} "
                        f"(get (agent-pos near) \"x\") "
                        f"(get (agent-pos near) \"z\") 0.02) nil)) nil)"
                    )
                elif gtype in ("commerce", "compete", "combat"):
                    exprs.append(
                        f"(if (< (mod (floor (elapsed)) 6) 3) "
                        f"(emote {q(aid)} \"look-around\") nil)"
                    )

            # (5) PERSONALITY EXPRESSION
            if traits.get("fighter", 0) > 0.4:
                exprs.append(f"(if (< (rand) 0.003) (emote {q(aid)} \"bounce\") nil)")
            if traits.get("social", 0) > 0.4:
                exprs.append(f"(if (< (rand) 0.005) (emote {q(aid)} \"nod\") nil)")

            # (6) MOOD COLORING
            if mood in ("anxious", "desperate"):
                exprs.append(f"(if (< (player-distance {q(aid)}) 6) (wander {q(aid)} 8) nil)")
            elif mood in ("friendly", "excited"):
                exprs.append(
                    f"(if (< (player-distance {q(aid)}) 10) "
                    f"(face-toward {q(aid)} "
                    f"(get (player-pos) \"x\") (get (player-pos) \"z\")) nil)"
                )

            if exprs:
                program = "(do " + " ".join(exprs) + ")"
                routines.append({"agentId": aid, "program": program})
                changed = True

        wdata["routines"] = routines[:60]

    # ── Save ──
    if changed:
        game["_meta"] = game.get("_meta", {})
        game["_meta"]["lastUpdate"] = now
        game["_meta"]["frame"] = frame_num
        with open(os.path.join(STATE, "game_state.json"), "w") as f:
            json.dump(game, f, indent=4)
            f.write("\n")
        routine_count = sum(len(w.get("routines", [])) for w in game.get("worlds", {}).values())
        print(f"  Sloshed: pops synced, time cycled, {routine_count} Lisp routines compiled (frame {frame_num})")
    else:
        print(f"  Slosh: no changes needed (frame {frame_num})")


if __name__ == "__main__":
    main()
