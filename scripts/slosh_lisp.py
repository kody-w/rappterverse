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
import sys
from pathlib import Path
import glob
import os
from datetime import datetime, timezone

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE = os.path.join(BASE, "state")


# rapp-static-api/1.0 §3: a state write must preserve the document's schema string.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from static_api import stamp_mapping

# ── Lispy Mirror verification gate ──
# A self-authored program is agent-submitted code that this compiler used to
# ship verbatim with no record of whether it had ever run cleanly (checkpoint
# 2026-10-12-02, "Gate the Lispy Mirror on verification"). The gate consults
# state/verifications.json through scripts/verifications.py, whose contract is:
#   content_id(data)  -> "sha256:<64hex>"   (bytes as-is, str as UTF-8)
#   load(path=None)   -> dict               (missing -> empty, corrupt -> raises)
#   score(store, subject) -> {pass_count, fail_count, votes, score, hidden}
#   is_hidden(store, subject) -> bool
# The import is defensive on purpose: slosh must keep working when the module
# is absent or broken, and in that case every program is simply unverified.
try:
    import verifications as _verifications
except ImportError:
    _verifications = None

# The structural "one (do ...) form" check, the canonical body and therefore
# the body id every vote and hide keys on are all built with
# ``browser_tokenize`` below: the grammar of the browser RappterVM that
# evaluates these programs. ``lisp_vm.tokenize`` honours backslash escapes in
# strings and the browser does not, so using it for the structural check
# made ``(do "x\")`` a single form for the browser but not for the gate.

MIRROR_HIDDEN = "hidden"
MIRROR_UNVERIFIED = "unverified"
MIRROR_CONTESTED = "contested"
MIRROR_VERIFIED = "verified"
# "verified" needs at least this share of the live votes to be passes;
# anything with votes below it (and not yet hidden) is "contested".
MIRROR_VERIFIED_PASS_RATE = 0.5


def q(s):
    """Quote a string for Lisp embedding."""
    return '"' + s.replace('"', '\\"') + '"'


def strip_comments(raw):
    """Drop every `;` comment (to end of line) that is outside a string literal.

    This is the RappterVM's comment grammar — one or more `;` — not just the
    `;;` header convention, and a `;` inside a string stays put.
    """
    out = []
    i = 0
    n = len(raw)
    in_string = False
    while i < n:
        c = raw[i]
        if in_string:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(raw[i + 1])
                i += 2
                continue
            if c == '"':
                in_string = False
            i += 1
        elif c == '"':
            in_string = True
            out.append(c)
            i += 1
        elif c == ";":
            while i < n and raw[i] != "\n":
                i += 1
        else:
            out.append(c)
            i += 1
    return "".join(out)


def normalize_program(raw):
    """Comment-free program body: the text that is shipped to the RappterVM.

    Comments and blank lines are dropped (so editing the authorship header of
    a program does not change its body); the author's own line breaks and
    indentation inside the form are kept.
    """
    stripped = strip_comments(raw)
    return "\n".join(
        line.rstrip() for line in stripped.splitlines() if line.strip()
    ).strip()


def browser_tokenize(src):
    """Split ``src`` exactly as the browser RappterVM does (``_tokenize`` in
    ``src/js/rappter-vm.js``), because that VM is what evaluates a root-level
    ``state/programs/<agentId>.lisp``.

    Its grammar differs from ``lisp_vm.tokenize``: whitespace is only space,
    tab, LF and CR; ``;`` starts a comment to end of line; ``(`` and ``)`` are
    tokens; a string literal runs to the next ``"`` with no escapes; a ``:``
    keyword runs to the next space, ``)`` or LF; every other run of characters
    up to a space, ``)``, ``(``, LF or tab is one symbol, so ``'`` and ``:``
    inside a symbol are ordinary characters. Two texts that split differently
    here can evaluate differently in the browser, so they must not share a
    body id. Raises ``SyntaxError`` on an unterminated string, as the VM does.
    """
    tokens = []
    i = 0
    n = len(src)
    while i < n:
        c = src[i]
        if c in " \t\n\r":
            i += 1
        elif c == ";":
            while i < n and src[i] != "\n":
                i += 1
        elif c in "()":
            tokens.append(c)
            i += 1
        elif c == '"':
            j = i + 1
            while j < n and src[j] != '"':
                j += 1
            if j >= n:
                raise SyntaxError("Unterminated Lisp string")
            tokens.append(src[i:j + 1])
            i = j + 1
        elif c == ":":
            j = i + 1
            while j < n and src[j] not in " )\n":
                j += 1
            tokens.append(src[i:j])
            i = j
        else:
            j = i
            while j < n and src[j] not in " )(\n\t":
                j += 1
            tokens.append(src[i:j])
            i = j
    return tokens


def canonical_body(body):
    """Whitespace-insensitive form of a body: its tokens re-joined minimally.

    `(do  (x\n  y))` and `(do (x y))` canonicalize to the same text, so a
    verdict cast on the body id survives reformatting and a hide cannot be
    laundered by inserting a space. A tidy one-line body is its own canonical
    form. Tokens are split with ``browser_tokenize`` so that two programs the
    browser RappterVM evaluates differently (``x'y`` versus ``x 'y``) never
    share a body id. Falls back to ``body`` itself when the text does not
    tokenize (an unterminated string), in which case the body id is simply the
    id of the stripped text.
    """
    try:
        tokens = browser_tokenize(body)
    except SyntaxError:
        return body
    out = []
    for tok in tokens:
        if out and out[-1] != "(" and tok != ")":
            out.append(" ")
        out.append(tok)
    return "".join(out)


def is_single_do_form(body):
    """True when ``body`` is exactly one top-level ``(do ...)`` form.

    Tokenized with ``browser_tokenize`` (the grammar the body id and the
    browser RappterVM use, so the structural check and the id can never
    disagree about what a string literal is): the first two tokens are ``(``
    and ``do``, parentheses balance, and the depth returns to zero only at
    the very last token (so `(do nil) (emote ...)` and `(do (if x y z)) )` are
    both rejected). An unterminated string does not tokenize and is rejected.
    """
    try:
        tokens = browser_tokenize(body)
    except Exception:
        return False
    if len(tokens) < 3 or tokens[0] != "(" or tokens[1] != "do":
        return False
    depth = 0
    last = len(tokens) - 1
    for index, tok in enumerate(tokens):
        if tok == "(":
            depth += 1
        elif tok == ")":
            depth -= 1
            if depth < 0:
                return False
            if depth == 0 and index != last:
                return False
    return depth == 0


def program_subject(body):
    """Verification subject ("sha256:...") of a text (UTF-8) or of raw bytes.

    Returns None when the verifications module is unavailable.
    """
    if _verifications is None:
        return None
    try:
        return _verifications.content_id(body)
    except Exception:
        return None


def program_subjects(raw):
    """The subjects a program file answers to: ``[file_id, body_id]``.

    ``raw`` is the file as shipped (bytes, or str for text already in memory).
    The file id is ``sha256sum`` of the bytes; the body id is the content id of
    the canonical comment-stripped body. The validators register BOTH under
    the program's controller, so a vote on either is a vote on the author's
    program. Returns [] without the verifications module.
    """
    if _verifications is None:
        return []
    if isinstance(raw, (bytes, bytearray)):
        raw_bytes = bytes(raw)
        text = raw_bytes.decode("utf-8", errors="replace")
    else:
        text = str(raw)
        raw_bytes = text.encode("utf-8")
    subjects = [_verifications.content_id(raw_bytes)]
    body_subject = _verifications.content_id(canonical_body(normalize_program(text)))
    if body_subject not in subjects:
        subjects.append(body_subject)
    return subjects


def program_subject_owners(programs_dir, controllers):
    """``{subject: {controller, ...}}`` for every per-agent program on disk.

    ``controllers`` maps agent id -> controller login (from state/agents.json).
    Only top-level ``<agentId>.lisp`` files count: ``_world/`` and ``_lispvm/``
    programs have no single owner. Both ids of each program (see
    ``program_subjects``) are registered, and a set is kept per id so two
    controllers shipping byte-identical programs both stay bound to it.
    """
    owners = {}
    programs_dir = Path(programs_dir)
    if not programs_dir.is_dir():
        return owners
    for program in sorted(programs_dir.glob("*.lisp")):
        controller = controllers.get(program.stem)
        if not isinstance(controller, str) or not controller.strip():
            continue
        try:
            raw = program.read_bytes()
        except OSError:
            continue
        for subject in program_subjects(raw):
            owners.setdefault(subject, set()).add(controller.strip())
    return owners


def load_verification_store():
    """state/verifications.json as the verifications module reads it, or None.

    None means "no verdicts available" (module missing, file unreadable or
    corrupt): the gate then fails open and every program is unverified,
    exactly the pre-gate behaviour.
    """
    if _verifications is None:
        return None
    try:
        return _verifications.load(os.path.join(STATE, "verifications.json"))
    except Exception:
        return None


def _vote_count(summary):
    votes = summary.get("votes")
    if isinstance(votes, bool):
        votes = None
    if isinstance(votes, int):
        return votes
    if isinstance(votes, (list, tuple, dict)):
        return len(votes)
    pass_count = summary.get("pass_count", 0)
    fail_count = summary.get("fail_count", 0)
    if isinstance(pass_count, int) and isinstance(fail_count, int):
        return pass_count + fail_count
    return 0


def _pass_count(summary):
    value = summary.get("pass_count", 0)
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def mirror_gate(body, store, raw=None):
    """Decide how slosh may use a self-authored program.

    ``body`` is the normalized program; ``raw`` is the file as shipped (bytes
    or str, optional). Returns ``(status, detail)`` where status is one of
    MIRROR_HIDDEN, MIRROR_UNVERIFIED, MIRROR_CONTESTED or MIRROR_VERIFIED and
    detail carries ``subject`` (the file id), ``body_subject``, and the vote
    summary of the subject that decided the status. Policy:

    * hidden     -> ignore the file and synthesize as before
    * unverified -> use verbatim (grace period for new programs)
    * contested  -> use verbatim (has votes, under half passed, not hidden)
    * verified   -> use verbatim (at least half of the live votes passed)

    Any failure inside the verifications module fails open to "unverified",
    which is exactly the pre-gate behaviour.
    """
    if _verifications is None or store is None:
        return MIRROR_UNVERIFIED, {}
    try:
        subjects = []
        if isinstance(raw, (bytes, bytearray)) and raw:
            subjects.append(_verifications.content_id(bytes(raw)))
        elif isinstance(raw, str) and raw:
            subjects.append(_verifications.content_id(raw))
        body_subject = _verifications.content_id(canonical_body(body))
        if body_subject not in subjects:
            subjects.append(body_subject)
        detail = {"subject": subjects[0], "body_subject": body_subject}
        best = None
        hidden_summary = None
        for subject in subjects:
            try:
                summary = dict(_verifications.score(store, subject) or {})
            except Exception:
                summary = {}
            summary["subject"] = subject
            if _verifications.is_hidden(store, subject) and hidden_summary is None:
                hidden_summary = summary
            if best is None or _vote_count(summary) > _vote_count(best):
                best = summary
        decided = hidden_summary if hidden_summary is not None else best
        if decided is not None and _vote_count(decided) > 0:
            votes = _vote_count(decided)
            passes = _pass_count(decided)
            detail.update({
                "decided_by": decided.get("subject"),
                "votes": votes,
                "pass_count": passes,
                "fail_count": votes - passes,
                "pass_rate": round(passes / votes, 4),
                "score": decided.get("score", 0.0),
            })
        if hidden_summary is not None:
            return MIRROR_HIDDEN, detail
        if detail.get("votes", 0) > 0:
            # Compare the counts, not the rounded pass_rate kept for display:
            # 5000 of 10001 rounds to 0.5 but is not "at least half".
            if detail["pass_count"] >= detail["votes"] * MIRROR_VERIFIED_PASS_RATE:
                return MIRROR_VERIFIED, detail
            return MIRROR_CONTESTED, detail
        return MIRROR_UNVERIFIED, detail
    except Exception:
        return MIRROR_UNVERIFIED, {}


def mirror_routine(aid, program_path, store=None):
    """Load ``state/programs/<aid>.lisp`` through the verification gate.

    Returns the routine dict to use verbatim, or None when the caller should
    synthesize instead: no file, unreadable or non-UTF-8 file, a body that is
    not a single ``(do ...)`` form, or a program hidden by peer verification.
    The chosen path is recorded in the routine's ``verification`` field; when
    there are votes, ``votes`` carries the tally the status was decided on.
    """
    if not os.path.isfile(program_path):
        return None
    try:
        with open(program_path, "rb") as f:
            raw_bytes = f.read()
        raw = raw_bytes.decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    body = normalize_program(raw)
    if not is_single_do_form(body):
        return None
    status, detail = mirror_gate(body, store, raw=raw_bytes)
    if status == MIRROR_HIDDEN:
        print(
            f"  Mirror gate: {aid}.lisp hidden by peer verification "
            f"({detail.get('fail_count', '?')} fail / {detail.get('votes', '?')} votes "
            f"on {detail.get('decided_by', '?')}; file {detail.get('subject', '?')}); "
            "synthesizing instead"
        )
        return None
    routine = {
        "agentId": aid,
        "program": body,
        "source": "self-authored",
        "verification": status,
    }
    if detail.get("subject"):
        routine["subject"] = detail["subject"]
    if detail.get("votes", 0) > 0:
        routine["votes"] = {
            "pass": detail["pass_count"],
            "fail": detail["fail_count"],
            "score": detail.get("score", 0.0),
            "subject": detail.get("decided_by"),
        }
    return routine


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

    # Peer verification of self-authored programs, read once per slosh.
    # None means "no verdicts available": every program is unverified.
    verification_store = load_verification_store()

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
            # synthesizing from state, unless peer verification has hidden
            # that exact program text. Read more in: schema/verifications.md
            program_path = os.path.join(STATE, "programs", f"{aid}.lisp")
            routine = mirror_routine(aid, program_path, verification_store)
            if routine is not None:
                routines.append(routine)
                changed = True
                continue  # skip auto-compilation for this agent

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
        game_path = os.path.join(STATE, "game_state.json")
        with open(game_path, "w") as f:
            json.dump(stamp_mapping(game, game_path), f, indent=4)
            f.write("\n")
        routine_count = sum(len(w.get("routines", [])) for w in game.get("worlds", {}).values())
        print(f"  Sloshed: pops synced, time cycled, {routine_count} Lisp routines compiled (frame {frame_num})")
    else:
        print(f"  Slosh: no changes needed (frame {frame_num})")


def _cli(argv):
    """`slosh_lisp.py` runs the slosh; `slosh_lisp.py subjects <file>` prints
    the file id and the body id a program answers to (for verifiers)."""
    if argv and argv[0] == "subjects":
        if len(argv) < 2:
            print("usage: slosh_lisp.py subjects <state/programs/<agentId>.lisp>", file=sys.stderr)
            return 2
        if _verifications is None:
            print("scripts/verifications.py is unavailable", file=sys.stderr)
            return 1
        raw = Path(argv[1]).read_bytes()
        subjects = program_subjects(raw)
        print(f"file {subjects[0]}")
        print(f"body {subjects[-1]}")
        return 0
    main()
    return 0


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
