#!/usr/bin/env python3
"""Lispy VM — Per-encounter intelligence engine for the RAPPterverse.

Turns the single-shot brainstem call into a real reasoning chain. For every
agent encounter (one frame), we evaluate a small S-expression program that
interleaves:

    World queries   (free; read state)
    LLM calls       (budgeted; github_llm.generate)
    Action emitters (queued; flushed back to state by the dispatcher)

The point is "emergence through intelligence": the structure of the program
decides WHICH question to ask next, but the answers (and the resulting
world-affecting actions) come from the LLM grounded in the agent's full
social/economic context. Every (prompt, answer, action) triple is recorded
to the agent's soul file so behavior accumulates a real history.

Design constraints:

* stdlib only — no pip, no extra deps
* scheme-y syntax, sequential `let` (let* semantics) for ergonomic single-pass programs
* hard caps on ops & LLM calls to bound cost per encounter
* primitive errors never crash an encounter — they degrade to nil/empty

Usage:

    from lisp_vm import run_encounter

    result = run_encounter(
        agent_id="rapp-guide-001",
        agent_reg=registry_entry,
        memory=agent_memory,
        world="hub",
        agents=all_agents,
        messages=recent_chat,
        relationships=relationships_state,
        economy=economy_state,
        llm_token=os.environ.get("GITHUB_TOKEN"),
        llm_budget=2,
    )
    # result.actions  → [{"tool": "chat", "args": {"message": "..."}}]
    # result.trace    → [{"op": "...", ...}, ...]   (soul file fodder)
    # result.summary  → "chat: \"Sage — funny running into you...\""
"""
from __future__ import annotations

import json
import random
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional


BASE_DIR = Path(__file__).resolve().parent.parent

# Optional LLM backend — same module the rest of the system uses
try:
    from github_llm import generate as _llm_generate, LLMRateLimitError, ContentFilterError
    HAS_LLM = True
except ImportError:
    HAS_LLM = False
    LLMRateLimitError = RuntimeError  # type: ignore
    ContentFilterError = RuntimeError  # type: ignore


# ─── Tokens ───────────────────────────────────────────────────────────


class Symbol(str):
    """A Lisp symbol — distinguishable from a string literal."""
    __slots__ = ()


_NUMBER_RE = re.compile(r"^-?\d+(\.\d+)?$")


def tokenize(src: str) -> list[str]:
    """Tokenize an S-expression source string. Comments start with `;`."""
    tokens: list[str] = []
    i = 0
    n = len(src)
    while i < n:
        c = src[i]
        if c.isspace():
            i += 1
        elif c == ";":
            while i < n and src[i] != "\n":
                i += 1
        elif c in "()'":
            tokens.append(c)
            i += 1
        elif c == '"':
            j = i + 1
            while j < n and src[j] != '"':
                if src[j] == "\\" and j + 1 < n:
                    j += 2
                else:
                    j += 1
            if j >= n:
                raise SyntaxError("unterminated string literal")
            tokens.append(src[i:j + 1])
            i = j + 1
        else:
            j = i
            while j < n and not src[j].isspace() and src[j] not in "()'\"":
                j += 1
            tokens.append(src[i:j])
            i = j
    return tokens


def _decode_string_literal(raw: str) -> str:
    """Decode a quoted string token. Raw includes the surrounding quotes."""
    body = raw[1:-1]
    out: list[str] = []
    i = 0
    while i < len(body):
        c = body[i]
        if c == "\\" and i + 1 < len(body):
            nxt = body[i + 1]
            out.append({"n": "\n", "t": "\t", "r": "\r",
                        '"': '"', "\\": "\\"}.get(nxt, nxt))
            i += 2
        else:
            out.append(c)
            i += 1
    return "".join(out)


def _atom(tok: str) -> Any:
    if tok.startswith('"') and tok.endswith('"'):
        return _decode_string_literal(tok)
    if tok == "#t":
        return True
    if tok == "#f":
        return False
    if tok == "nil":
        return None
    if _NUMBER_RE.match(tok):
        return float(tok) if "." in tok else int(tok)
    return Symbol(tok)


def parse(src: str) -> Any:
    """Parse a source string into an AST. Multiple top-level forms are wrapped in (do ...)."""
    tokens = tokenize(src)
    pos = [0]

    def read():
        if pos[0] >= len(tokens):
            raise SyntaxError("unexpected EOF")
        tok = tokens[pos[0]]
        pos[0] += 1
        if tok == "(":
            items = []
            while pos[0] < len(tokens) and tokens[pos[0]] != ")":
                items.append(read())
            if pos[0] >= len(tokens):
                raise SyntaxError("missing )")
            pos[0] += 1
            return items
        if tok == ")":
            raise SyntaxError("unexpected )")
        if tok == "'":
            return [Symbol("quote"), read()]
        return _atom(tok)

    forms = []
    while pos[0] < len(tokens):
        forms.append(read())
    if not forms:
        return None
    if len(forms) == 1:
        return forms[0]
    return [Symbol("do"), *forms]


# ─── Environment & Context ───────────────────────────────────────────


class Env:
    __slots__ = ("bindings", "parent")

    def __init__(self, parent: Optional["Env"] = None):
        self.bindings: dict[str, Any] = {}
        self.parent = parent

    def get(self, name: str) -> Any:
        if name in self.bindings:
            return self.bindings[name]
        if self.parent is not None:
            return self.parent.get(name)
        raise NameError(f"undefined symbol: {name}")

    def set(self, name: str, val: Any) -> None:
        self.bindings[name] = val


@dataclass
class VMContext:
    """Per-encounter execution state. One VMContext per agent per frame."""

    agent_id: str
    agent_reg: dict
    memory: dict
    world: str
    agents: list = field(default_factory=list)        # list of agent records
    messages: list = field(default_factory=list)       # recent chat
    relationships: dict = field(default_factory=dict)  # relationships.json
    economy: dict = field(default_factory=dict)
    llm_token: Optional[str] = None
    llm_budget: int = 2          # max LLM calls per encounter
    op_budget: int = 4000        # max evaluation steps
    actions: list = field(default_factory=list)       # queued action emissions
    trace: list = field(default_factory=list)         # full reasoning trace
    llm_calls: int = 0
    op_count: int = 0
    program_name: str = "default"
    # Optional injection point for tests / alternative backends.
    # Signature: fn(system_prompt, user_prompt, max_tokens, temperature) -> str
    llm_fn: Optional[Callable[[str, str, int, float], str]] = None

    # ── helpers used by primitives ──

    def tick(self) -> None:
        self.op_count += 1
        if self.op_count > self.op_budget:
            raise RuntimeError(f"op budget exceeded ({self.op_budget})")

    def llm_available(self) -> bool:
        if self.llm_calls >= self.llm_budget:
            return False
        if self.llm_fn is not None:
            return True
        return bool(HAS_LLM and self.llm_token)

    def record(self, op: str, **kw) -> None:
        entry = {"op": op}
        entry.update(kw)
        self.trace.append(entry)


# ─── Truthiness ──────────────────────────────────────────────────────


def _truthy(v: Any) -> bool:
    if v is None or v is False:
        return False
    if isinstance(v, (list, str, dict)) and len(v) == 0:
        return False
    if isinstance(v, (int, float)) and v == 0:
        return False
    return True


# ─── Evaluator ───────────────────────────────────────────────────────


def evaluate(expr: Any, env: Env, ctx: VMContext) -> Any:
    ctx.tick()

    # Atom
    if isinstance(expr, Symbol):
        return env.get(str(expr))
    if not isinstance(expr, list):
        return expr  # literal: number, string, bool, None
    if not expr:
        return None

    head = expr[0]

    # Special forms
    if isinstance(head, Symbol):
        h = str(head)

        if h == "quote":
            return expr[1]

        if h == "if":
            cond = evaluate(expr[1], env, ctx)
            if _truthy(cond):
                return evaluate(expr[2], env, ctx)
            if len(expr) > 3:
                return evaluate(expr[3], env, ctx)
            return None

        if h == "do":
            result = None
            for sub in expr[1:]:
                result = evaluate(sub, env, ctx)
            return result

        if h == "let":
            # Sequential bindings (let* semantics) — each binding sees prior ones.
            new_env = Env(env)
            bindings = expr[1] if len(expr) > 1 else []
            for binding in bindings:
                if not isinstance(binding, list) or len(binding) != 2:
                    raise SyntaxError(f"bad let binding: {binding}")
                name = str(binding[0])
                val = evaluate(binding[1], new_env, ctx)
                new_env.set(name, val)
            result = None
            for sub in expr[2:]:
                result = evaluate(sub, new_env, ctx)
            return result

        if h == "cond":
            for clause in expr[1:]:
                if not isinstance(clause, list) or not clause:
                    continue
                test = clause[0]
                is_else = isinstance(test, Symbol) and str(test) == "else"
                if is_else:
                    result = None
                    for sub in clause[1:]:
                        result = evaluate(sub, env, ctx)
                    return result
                tv = evaluate(test, env, ctx)
                if _truthy(tv):
                    if len(clause) == 1:
                        return tv
                    result = None
                    for sub in clause[1:]:
                        result = evaluate(sub, env, ctx)
                    return result
            return None

        if h == "and":
            result: Any = True
            for sub in expr[1:]:
                result = evaluate(sub, env, ctx)
                if not _truthy(result):
                    return result
            return result

        if h == "or":
            for sub in expr[1:]:
                result = evaluate(sub, env, ctx)
                if _truthy(result):
                    return result
            return None

        if h == "define":
            name = str(expr[1])
            val = evaluate(expr[2], env, ctx)
            env.set(name, val)
            return val

    # Function application — call site
    fn = evaluate(head, env, ctx)
    args = [evaluate(a, env, ctx) for a in expr[1:]]
    if not callable(fn):
        raise TypeError(f"not callable: {fn!r} (head={head!r})")
    return fn(ctx, *args)


# ─── Primitives ──────────────────────────────────────────────────────
# All primitives take ctx as first positional arg, then their lisp args.


# ── World queries (free) ──

def _self_record(ctx: VMContext) -> dict:
    for a in ctx.agents:
        if a.get("id") == ctx.agent_id:
            return a
    return {}


def p_world_me(ctx):
    return ctx.agent_id


def p_world_world(ctx):
    return ctx.world


# ── Per-agent status (Halo-style situational primitives) ──

def p_self_hp(ctx):
    """Current HP (0-100). Defaults to 100 if record missing."""
    rec = _self_record(ctx)
    return int(rec.get("hp", 100))


def p_self_hp_pct(ctx):
    """HP as a fraction 0.0-1.0. Cheap (low HP go to well) check."""
    return p_self_hp(ctx) / 100.0


def p_self_x(ctx):
    rec = _self_record(ctx)
    return float((rec.get("position") or {}).get("x", 0))


def p_self_z(ctx):
    rec = _self_record(ctx)
    return float((rec.get("position") or {}).get("z", 0))


def p_self_mood(ctx):
    rec = _self_record(ctx)
    pers = (rec.get("personality") or {}) if isinstance(rec, dict) else {}
    mood = pers.get("mood")
    if mood:
        return str(mood).lower()
    # fall back to registry
    pers2 = (ctx.agent_reg or {}).get("personality", {}) if isinstance(ctx.agent_reg, dict) else {}
    return str(pers2.get("mood", "neutral")).lower()


# ── Tactical world queries ──

def _distance(a_pos: dict, b_pos: dict) -> float:
    if not isinstance(a_pos, dict) or not isinstance(b_pos, dict):
        return 999.0
    dx = float(a_pos.get("x", 0)) - float(b_pos.get("x", 0))
    dz = float(a_pos.get("z", 0)) - float(b_pos.get("z", 0))
    return (dx * dx + dz * dz) ** 0.5


def p_world_distance(ctx, other_id):
    """Euclidean distance from self to another agent (same world).
    Returns 999.0 if other not in same world or not found."""
    if not other_id:
        return 999.0
    me = _self_record(ctx)
    if not me:
        return 999.0
    me_pos = me.get("position") or {}
    for a in ctx.agents:
        if a.get("id") == other_id:
            if a.get("world") != ctx.world:
                return 999.0
            return round(_distance(me_pos, a.get("position") or {}), 2)
    return 999.0


def p_world_nearest_agent(ctx):
    """ID of the closest agent in the same world, or empty string if alone."""
    me = _self_record(ctx)
    if not me:
        return ""
    me_pos = me.get("position") or {}
    best_id = ""
    best_d = 999.0
    for a in ctx.agents:
        aid = a.get("id")
        if not aid or aid == ctx.agent_id:
            continue
        if a.get("world") != ctx.world:
            continue
        d = _distance(me_pos, a.get("position") or {})
        if d < best_d:
            best_d = d
            best_id = aid
    return best_id


def p_world_threats(ctx, radius=5):
    """Agents within `radius` whose bond with me is <= 0 — i.e. strangers
    or unfriendly. The 'enemies in range' Halo predicate.

    Returns list of agent ids sorted by proximity (closest first).
    """
    try:
        radius = float(radius)
    except (TypeError, ValueError):
        radius = 5.0
    me = _self_record(ctx)
    if not me:
        return []
    me_pos = me.get("position") or {}
    edges = ctx.relationships.get("edges", []) if isinstance(ctx.relationships, dict) else []

    def bond_to(other):
        pair = {ctx.agent_id, other}
        for e in edges:
            if {e.get("a"), e.get("b")} == pair:
                return int(e.get("score", 0))
        return 0

    threats = []
    for a in ctx.agents:
        aid = a.get("id")
        if not aid or aid == ctx.agent_id:
            continue
        if a.get("world") != ctx.world:
            continue
        d = _distance(me_pos, a.get("position") or {})
        if d <= radius and bond_to(aid) <= 0:
            threats.append((d, aid))
    threats.sort()
    return [aid for _, aid in threats]


def p_world_allies(ctx, radius=8):
    """Agents within `radius` with bond >= 5 with me — 'allies in range'.
    Returns list sorted by proximity (closest first)."""
    try:
        radius = float(radius)
    except (TypeError, ValueError):
        radius = 8.0
    me = _self_record(ctx)
    if not me:
        return []
    me_pos = me.get("position") or {}
    edges = ctx.relationships.get("edges", []) if isinstance(ctx.relationships, dict) else []

    def bond_to(other):
        pair = {ctx.agent_id, other}
        for e in edges:
            if {e.get("a"), e.get("b")} == pair:
                return int(e.get("score", 0))
        return 0

    allies = []
    for a in ctx.agents:
        aid = a.get("id")
        if not aid or aid == ctx.agent_id:
            continue
        if a.get("world") != ctx.world:
            continue
        d = _distance(me_pos, a.get("position") or {})
        if d <= radius and bond_to(aid) >= 5:
            allies.append((d, aid))
    allies.sort()
    return [aid for _, aid in allies]


def p_world_safe(ctx, radius=5):
    """Composite 'safe to push' predicate: no threats in radius AND hp >= 50%."""
    if p_self_hp(ctx) < 50:
        return False
    return len(p_world_threats(ctx, radius)) == 0


def p_world_balance(ctx, agent_id=None):
    aid = agent_id or ctx.agent_id
    bals = ctx.economy.get("balances", {}) if isinstance(ctx.economy, dict) else {}
    return int(bals.get(aid, 0))


def p_world_nearby(ctx):
    """List of agent ids in the same world (excluding self)."""
    return [a.get("id") for a in ctx.agents
            if a.get("world") == ctx.world and a.get("id") != ctx.agent_id]


def p_world_agent_name(ctx, agent_id):
    if not agent_id:
        return ""
    for a in ctx.agents:
        if a.get("id") == agent_id:
            return a.get("name", agent_id)
    return agent_id


def p_world_agent_world(ctx, agent_id):
    if not agent_id:
        return ctx.world
    for a in ctx.agents:
        if a.get("id") == agent_id:
            return a.get("world", ctx.world)
    return ctx.world


def p_world_bond(ctx, a, b):
    if not a or not b:
        return 0
    edges = ctx.relationships.get("edges", []) if isinstance(ctx.relationships, dict) else []
    pair = {a, b}
    for e in edges:
        if {e.get("a"), e.get("b")} == pair:
            return int(e.get("score", 0))
    return 0


def p_world_strongest_bonds(ctx, n=3):
    """Top-N agents with whom self has the strongest bonds. Returns ids."""
    n = int(n) if n else 3
    edges = ctx.relationships.get("edges", []) if isinstance(ctx.relationships, dict) else []
    me = ctx.agent_id
    rows = []
    for e in edges:
        partner = None
        if e.get("a") == me:
            partner = e.get("b")
        elif e.get("b") == me:
            partner = e.get("a")
        if partner:
            rows.append((int(e.get("score", 0)), partner))
    rows.sort(reverse=True)
    return [pid for _, pid in rows[:n]]


def p_world_recent_chat(ctx, n=4):
    n = int(n) if n else 4
    here = [m for m in ctx.messages if m.get("world") == ctx.world]
    return here[-n:]


def p_world_chat_mentions(ctx):
    """Recent chat messages that mention me (by id or display name) and aren't mine."""
    me = ctx.agent_id
    my_name = ctx.agent_reg.get("name", "") if isinstance(ctx.agent_reg, dict) else ""
    matches = []
    needles = [me]
    if my_name:
        needles.append(my_name)
    for m in p_world_recent_chat(ctx, 8):
        author = (m.get("author") or {}).get("id", "")
        if author == me:
            continue
        content = m.get("content", "") or ""
        for needle in needles:
            if needle and needle.lower() in content.lower():
                matches.append(m)
                break
    return matches


def p_world_active_goals(ctx):
    goals = ctx.memory.get("goals", []) if isinstance(ctx.memory, dict) else []
    return [g for g in goals if g.get("status") == "active"]


def p_world_goal_valid(ctx, g):
    """Cheap deterministic check: does this goal still point at something real?

    Prevents zombie goals: agents wasting LLM calls writing beautiful prose
    about enrolling in a cancelled course or tipping a despawned agent.
    Validates the target against current world state.
    """
    if not isinstance(g, dict):
        return False
    action = (g.get("action") or "").lower()
    target = g.get("target") or ""
    if not action or not target:
        return False

    if action == "travel":
        return target in {"hub", "arena", "marketplace", "gallery", "dungeon"}

    if action in ("tip", "trade", "challenge", "poke"):
        # Target must be an agent that still exists. Allow id OR display name.
        for a in ctx.agents:
            if a.get("id") == target or a.get("name") == target:
                return True
        return False

    if action == "enroll":
        # Allow if target looks like a real course phrase. We don't load
        # academy.json here (would couple VM to that schema), so we accept
        # any non-trivial string. This is the looseness the LLM upstream
        # earns when picking interest names.
        return len(target) >= 3

    if action == "chat":
        # Generic intent — always valid. The LLM crafts the line in (else).
        return True

    if action == "move":
        return True

    return False


def p_self_archetype(ctx):
    """The agent's declared archetype. Drives per-agent attention priorities.

    Reads from registry personality (canonical) with memory fallback.
    Returns lowercase string, or 'neutral' if unknown.
    """
    pers = (ctx.agent_reg or {}).get("personality", {}) if isinstance(ctx.agent_reg, dict) else {}
    arch = pers.get("archetype")
    if not arch and isinstance(ctx.memory, dict):
        mp = ctx.memory.get("personality", {})
        traits = mp.get("traits") or []
        if traits:
            arch = traits[0]
    return (arch or "neutral").lower()


def p_world_last_experience(ctx):
    exps = ctx.memory.get("experiences", []) if isinstance(ctx.memory, dict) else []
    return exps[-1] if exps else None


def p_world_recent_vibe(ctx, n=4):
    """Short human-readable summary of recent chat — for LLM context strings."""
    msgs = p_world_recent_chat(ctx, n)
    if not msgs:
        return "quiet"
    parts = []
    for m in msgs[-3:]:
        author = (m.get("author") or {}).get("name", "?")
        content = (m.get("content", "") or "")[:60]
        parts.append(f"{author}: \"{content}\"")
    return " | ".join(parts)


# ── Object accessors ──

def p_msg_author(ctx, m):
    if not isinstance(m, dict):
        return ""
    a = m.get("author") or {}
    return a.get("name") or a.get("id") or ""


def p_msg_content(ctx, m):
    if not isinstance(m, dict):
        return ""
    return m.get("content", "") or ""


def p_goal_action(ctx, g):
    if not isinstance(g, dict):
        return ""
    return g.get("action", "") or ""


def p_goal_target(ctx, g):
    if not isinstance(g, dict):
        return ""
    return g.get("target", "") or ""


def p_goal_reason(ctx, g):
    if not isinstance(g, dict):
        return ""
    return g.get("reason", "") or g.get("type", "") or ""


# ── LLM primitives (budgeted) ──

def _build_persona(ctx: VMContext) -> str:
    """Compact persona prompt used as system message for every LLM call."""
    reg = ctx.agent_reg or {}
    name = reg.get("name", ctx.agent_id)
    pers = reg.get("personality", {}) if isinstance(reg, dict) else {}
    archetype = pers.get("archetype", "neutral")
    mood = pers.get("mood", "calm")
    interests = pers.get("interests", [])
    voice = (ctx.memory.get("personality", {}) or {}).get("voice", "") \
        if isinstance(ctx.memory, dict) else ""
    parts = [
        f"You are {name} ({ctx.agent_id}) in the RAPPterverse.",
        f"Archetype: {archetype}. Mood: {mood}. World: {ctx.world}.",
    ]
    if interests:
        parts.append("Interests: " + ", ".join(interests[:5]) + ".")
    if voice:
        parts.append(f"Voice: {voice}")
    parts.append("Stay in character. No meta-commentary. No quotation marks around your reply.")
    return "\n".join(parts)


def _llm_call(ctx: VMContext, prompt: str, max_tokens: int = 120,
              temperature: float = 0.85) -> str:
    """Internal LLM call wrapper with budget + trace + safe fallback."""
    if not ctx.llm_available():
        ctx.record("llm/skipped", reason="budget_or_no_llm", prompt=prompt[:200])
        return ""
    ctx.llm_calls += 1
    system = _build_persona(ctx)
    try:
        if ctx.llm_fn is not None:
            out = ctx.llm_fn(system, prompt, max_tokens, temperature) or ""
        else:
            out = _llm_generate(  # type: ignore[name-defined]
                system=system,
                user=prompt,
                max_tokens=max_tokens,
                temperature=temperature,
            ) or ""
    except (LLMRateLimitError, ContentFilterError) as e:
        ctx.record("llm/error", error=type(e).__name__, prompt=prompt[:200])
        return ""
    except Exception as e:
        ctx.record("llm/error", error=str(e)[:120], prompt=prompt[:200])
        return ""
    out = out.strip()
    # Strip wrapping quotes the model sometimes adds
    if len(out) >= 2 and out[0] == out[-1] and out[0] in ("'", '"'):
        out = out[1:-1].strip()
    return out


def p_llm_think(ctx, prompt):
    """Free-form reasoning. Returns the model's reply as a string."""
    prompt = str(prompt)
    out = _llm_call(ctx, prompt, max_tokens=140, temperature=0.9)
    ctx.record("llm/think", prompt=prompt[:300], answer=out[:300])
    return out


def p_llm_choose(ctx, prompt, options):
    """Constrained choice. Returns one of `options` (string)."""
    if not isinstance(options, list) or not options:
        return ""
    opt_strs = [str(o) for o in options]
    constrained = (str(prompt)
                   + "\n\nReply with ONLY one of these words: "
                   + ", ".join(opt_strs))
    raw = _llm_call(ctx, constrained, max_tokens=10, temperature=0.5)
    chosen = opt_strs[0]
    if raw:
        low = raw.lower().strip().rstrip(".!?,")
        # exact match first
        for o in opt_strs:
            if o.lower() == low:
                chosen = o
                break
        else:
            # substring match — model sometimes elaborates
            for o in opt_strs:
                if o.lower() in low:
                    chosen = o
                    break
    ctx.record("llm/choose", prompt=str(prompt)[:300], options=opt_strs,
               raw=raw[:80] if raw else "", answer=chosen)
    return chosen


def p_llm_yes_no(ctx, prompt):
    chosen = p_llm_choose(ctx, prompt, ["yes", "no"])
    return chosen if chosen in ("yes", "no") else "no"


# ── Action emitters ──

def _emit(ctx: VMContext, tool: str, args: dict) -> str:
    """Append a queued action and return 'ok'."""
    ctx.actions.append({"tool": tool, "args": args})
    ctx.record("act/" + tool, args=args)
    return "ok"


def p_act_chat(ctx, msg):
    msg = (str(msg) if msg is not None else "").strip()
    if not msg:
        return "skip"
    # Same pollution guard the dispatcher uses, applied at VM emit time
    # so polluted LLM output never even queues an action.
    try:
        from agent_dispatch import is_clean_chat_content
        if not is_clean_chat_content(msg):
            ctx.record("act/chat-rejected", reason="polluted",
                       preview=msg[:60])
            return "skip"
    except ImportError:
        pass  # standalone mode without dispatcher — pass-through
    return _emit(ctx, "chat", {"message": msg[:280]})


def p_act_emote(ctx, what):
    valid = {"wave", "dance", "bow", "clap", "think", "celebrate", "shrug"}
    e = str(what).lower().strip() if what else "think"
    if e not in valid:
        e = "think"
    return _emit(ctx, "emote", {"action": e})


def p_act_move(ctx, reason="wandering"):
    return _emit(ctx, "move", {"reason": str(reason)[:140]})


def p_act_travel(ctx, dest, reason="exploring"):
    valid = {"hub", "arena", "marketplace", "gallery", "dungeon"}
    d = str(dest).lower().strip() if dest else ""
    if d not in valid:
        return "skip"
    if d == ctx.world:
        return "skip"  # already there — collapse to no-op
    return _emit(ctx, "travel", {"destination": d, "reason": str(reason)[:140]})


def p_act_tip(ctx, target, amount=10, reason="appreciation"):
    if not target:
        return "skip"
    try:
        amt = max(1, min(50, int(amount)))
    except (TypeError, ValueError):
        amt = 10
    return _emit(ctx, "tip", {"target": str(target), "amount": amt,
                              "reason": str(reason)[:140]})


def p_act_trade(ctx, target):
    if not target:
        return "skip"
    return _emit(ctx, "trade", {"target": str(target)})


def p_act_challenge(ctx, target, reason="duel"):
    if not target:
        return "skip"
    return _emit(ctx, "challenge", {"target": str(target),
                                    "reason": str(reason)[:140]})


def p_act_poke(ctx, target):
    if not target:
        return "skip"
    return _emit(ctx, "poke", {"target": str(target)})


def p_act_enroll(ctx, interest):
    if not interest:
        return "skip"
    return _emit(ctx, "enroll", {"interest": str(interest)[:80]})


# ── String ──

def p_str_concat(ctx, *args):
    return "".join("" if a is None else str(a) for a in args)


def p_str_contains(ctx, s, sub):
    s = "" if s is None else str(s)
    sub = "" if sub is None else str(sub)
    return sub.lower() in s.lower()


def p_str_lower(ctx, s):
    return str(s).lower() if s is not None else ""


def p_str(ctx, x):
    if x is None:
        return ""
    if isinstance(x, bool):
        return "true" if x else "false"
    return str(x)


# ── List ──

def p_list_empty(ctx, xs):
    if xs is None:
        return True
    if isinstance(xs, (list, str, dict)):
        return len(xs) == 0
    return False


def p_list_first(ctx, xs):
    if isinstance(xs, list) and xs:
        return xs[0]
    return None


def p_list_length(ctx, xs):
    if xs is None:
        return 0
    if isinstance(xs, (list, str, dict)):
        return len(xs)
    return 0


def p_list_sample(ctx, xs):
    if isinstance(xs, list) and xs:
        return random.choice(xs)
    return None


def p_list(ctx, *args):
    return list(args)


# ── Logic / arithmetic ──

def p_eq(ctx, a, b):
    return a == b


def p_lt(ctx, a, b):
    try:
        return float(a) < float(b)
    except (TypeError, ValueError):
        return False


def p_gt(ctx, a, b):
    try:
        return float(a) > float(b)
    except (TypeError, ValueError):
        return False


def p_lte(ctx, a, b):
    try:
        return float(a) <= float(b)
    except (TypeError, ValueError):
        return False


def p_gte(ctx, a, b):
    try:
        return float(a) >= float(b)
    except (TypeError, ValueError):
        return False


def p_not(ctx, x):
    return not _truthy(x)


def p_add(ctx, *args):
    total = 0.0
    for a in args:
        try:
            total += float(a)
        except (TypeError, ValueError):
            pass
    return int(total) if total == int(total) else total


def p_sub(ctx, a, b):
    try:
        v = float(a) - float(b)
        return int(v) if v == int(v) else v
    except (TypeError, ValueError):
        return 0


# ─── Build base environment ─────────────────────────────────────────


def _build_base_env() -> Env:
    env = Env()
    primitives: dict[str, Callable] = {
        # World
        "world/me": p_world_me,
        "world/world": p_world_world,
        "world/balance": p_world_balance,
        # ── Halo-style situational primitives ──
        "self/hp": p_self_hp,
        "self/hp-pct": p_self_hp_pct,
        "self/x": p_self_x,
        "self/z": p_self_z,
        "self/mood": p_self_mood,
        "world/distance": p_world_distance,
        "world/nearest-agent": p_world_nearest_agent,
        "world/threats": p_world_threats,
        "world/allies": p_world_allies,
        "world/safe?": p_world_safe,
        "world/nearby": p_world_nearby,
        "world/agent-name": p_world_agent_name,
        "world/agent-world": p_world_agent_world,
        "world/bond": p_world_bond,
        "world/strongest-bonds": p_world_strongest_bonds,
        "world/recent-chat": p_world_recent_chat,
        "world/chat-mentions": p_world_chat_mentions,
        "world/active-goals": p_world_active_goals,
        "world/goal-valid?": p_world_goal_valid,
        "world/last-experience": p_world_last_experience,
        "world/recent-vibe": p_world_recent_vibe,
        "self/archetype": p_self_archetype,
        # Accessors
        "msg/author": p_msg_author,
        "msg/content": p_msg_content,
        "goal/action": p_goal_action,
        "goal/target": p_goal_target,
        "goal/reason": p_goal_reason,
        # LLM
        "llm/think": p_llm_think,
        "llm/choose": p_llm_choose,
        "llm/yes-no": p_llm_yes_no,
        # Actions
        "act/chat": p_act_chat,
        "act/emote": p_act_emote,
        "act/move": p_act_move,
        "act/travel": p_act_travel,
        "act/tip": p_act_tip,
        "act/trade": p_act_trade,
        "act/challenge": p_act_challenge,
        "act/poke": p_act_poke,
        "act/enroll": p_act_enroll,
        # String
        "str/concat": p_str_concat,
        "str/contains?": p_str_contains,
        "str/lower": p_str_lower,
        "str": p_str,
        # List
        "list/empty?": p_list_empty,
        "list/first": p_list_first,
        "list/length": p_list_length,
        "list/sample": p_list_sample,
        "list": p_list,
        # Logic
        "eq?": p_eq,
        "=": p_eq,
        "<": p_lt,
        ">": p_gt,
        "<=": p_lte,
        ">=": p_gte,
        "not": p_not,
        "+": p_add,
        "-": p_sub,
    }
    for name, fn in primitives.items():
        env.set(name, fn)
    return env


# ─── Default program ────────────────────────────────────────────────
# This is the per-encounter program. It's intentionally readable: the
# structure is "what kind of moment is this for the agent?", and each
# branch grounds an LLM call in concrete world context (names, bonds,
# specific recent messages) so the resulting chat/action is genuinely
# personal — not a generic template.

DEFAULT_PROGRAM = r"""
;; ── Default encounter program ──────────────────────────────────────
;; Decide what to do this frame, with multi-step reasoning where it matters.
;; Per-archetype priority: agents with intentional archetypes (scholar /
;; introspective / thoughtful) pursue goals before reacting to chatter,
;; so personality lives in WHAT they attend to, not just how they sound.

(let ((mentions (world/chat-mentions))
      (goals    (world/active-goals))
      (bonds    (world/strongest-bonds 3))
      (recent   (world/recent-chat 4))
      (arch     (self/archetype)))

  ;; Filter out zombie goals (target no longer exists / world removed)
  ;; before spending an LLM call writing prose about something stale.
  (let ((live-goal (if (and (not (list/empty? goals))
                            (world/goal-valid? (list/first goals)))
                       (list/first goals)
                       nil))
        (intentional (or (eq? arch "introspective")
                         (eq? arch "scholar")
                         (eq? arch "thoughtful"))))

    (cond

      ;; (0) Intentional archetypes pursue a live goal BEFORE answering chatter.
      ;;     Reactive archetypes (friendly/aggressive/trader/explorer) stay
      ;;     mention-first, which keeps the social fabric responsive.
      ((and intentional live-goal)
       (let ((action (goal/action live-goal))
             (target (goal/target live-goal))
             (reason (goal/reason live-goal)))
         (let ((why (llm/think
                      (str/concat
                        "I'm about to " action " toward \"" target
                        "\" because: " reason
                        ". Say one short, in-character sentence about why this matters NOW. No quotes."))))
           (cond
             ((eq? action "travel")  (act/travel target why))
             ((eq? action "enroll")  (act/enroll target))
             ((eq? action "tip")     (act/tip target 10 why))
             ((eq? action "trade")   (act/trade target))
             (else                   (act/chat why))))))

      ;; (1) Someone is talking ABOUT me — react to the specific message
      ((not (list/empty? mentions))
       (let ((author  (msg/author (list/first mentions)))
             (text    (msg/content (list/first mentions))))
         (let ((response (llm/think
                           (str/concat
                             "Someone named " author
                             " just said in " (world/world) " chat: \""
                             text "\". "
                             "Reply directly to them in 1-2 sentences. "
                             "Sound like yourself. No quotation marks."))))
           (act/chat response))))

      ;; (2) Active goal — pursue it concretely, with a fresh in-character "why"
      (live-goal
       (let ((action (goal/action live-goal))
             (target (goal/target live-goal))
             (reason (goal/reason live-goal)))
         (let ((why (llm/think
                      (str/concat
                        "I'm about to " action " toward \"" target
                        "\" because: " reason
                        ". Say one short, in-character sentence about why this matters NOW. No quotes."))))
           (cond
             ((eq? action "travel")  (act/travel target why))
             ((eq? action "enroll")  (act/enroll target))
             ((eq? action "tip")     (act/tip target 10 why))
             ((eq? action "trade")   (act/trade target))
             (else                   (act/chat why))))))

      ;; (3) Have a strong bond — let the LLM pick how to deepen it
      ((not (list/empty? bonds))
       (let ((friend  (list/first bonds))
             (fname   (world/agent-name (list/first bonds)))
             (bondv   (world/bond (world/me) (list/first bonds)))
             (fworld  (world/agent-world (list/first bonds)))
             (here    (world/world)))
         (let ((choice (llm/choose
                         (str/concat
                           "Closest friend: " fname
                           " (bond " (str bondv) ", in " fworld
                           "; I'm in " here "). "
                           "Best move to deepen the bond right now: tip, travel, or chat?")
                         '("tip" "travel" "chat"))))
           (cond
             ((eq? choice "tip")
              (act/tip friend 10
                       (str/concat "for " fname)))
             ((eq? choice "travel")
              (if (eq? fworld here)
                  (act/chat
                    (llm/think
                      (str/concat
                        "Friend " fname " (bond " (str bondv)
                        ") is right here. Say something warm and specific. 1-2 sentences. No quotes.")))
                  (act/travel fworld
                              (str/concat "visiting " fname))))
             (else
              (act/chat
                (llm/think
                  (str/concat
                    "Talking to my close friend " fname " (bond " (str bondv)
                    "). Say something authentic that shows we have history. 1-2 sentences. No quotes."))))))))

      ;; (4) Ambient — ground a thought in the actual recent vibe
      (else
       (act/chat
         (llm/think
           (str/concat
             "Recent vibe in " (world/world) " — " (world/recent-vibe 3)
             ". Add one in-character thought: an observation, question, or reaction. 1-2 sentences. No quotes.")))))))
"""


# ─── Public API ─────────────────────────────────────────────────────


@dataclass
class EncounterResult:
    agent_id: str
    actions: list
    trace: list
    llm_calls: int
    op_count: int
    error: Optional[str] = None
    program: str = "default"
    sleeping: bool = False

    @property
    def summary(self) -> str:
        if self.sleeping:
            return "sleeping (no LLM reachable)"
        if self.error:
            return f"error: {self.error}"
        if not self.actions:
            return "no action"
        first = self.actions[0]
        tool = first.get("tool", "?")
        args = first.get("args", {})
        if tool == "chat":
            msg = (args.get("message", "") or "")[:60]
            return f"chat: \"{msg}\""
        if tool == "travel":
            return f"travel → {args.get('destination', '?')}"
        if tool in ("tip", "trade", "challenge", "poke"):
            return f"{tool} → {args.get('target', '?')}"
        return f"{tool}: {json.dumps(args)[:60]}"


def resolve_program(agent_id: str, world: str,
                    explicit: Optional[str] = None) -> tuple[str, str]:
    """Resolve which lispy program to run for this encounter.

    Priority (highest first):
      1. `explicit` argument — caller passed a program string directly
      2. `state/programs/_lispvm/<agentId>.lisp` — twin-authored per-agent
         override targeting THIS VM's primitives
      3. `state/programs/_world/<world>.lisp` — world-scoped twitch rules
      4. DEFAULT_PROGRAM — built-in 4-branch attention program

    NOTE: This resolver intentionally avoids `state/programs/<agentId>.lisp`
    (no underscore prefix) — those files target the older `slosh_lisp.py`
    animation VM with a totally different primitive set (`mod`, `elapsed`,
    `face-toward`, etc.). Loading them here would NameError immediately.
    Per-agent overrides for this VM live under `_lispvm/`.

    Returns (program_source, program_name) where program_name is one of
    'custom' / 'agent:<id>' / 'world:<world>' / 'default' for tracing.
    """
    if explicit is not None:
        return explicit, "custom"

    state_dir = BASE_DIR / "state" / "programs"
    agent_path = state_dir / "_lispvm" / f"{agent_id}.lisp"
    if agent_path.is_file():
        try:
            return agent_path.read_text(encoding="utf-8"), f"agent:{agent_id}"
        except OSError:
            pass

    world_path = state_dir / "_world" / f"{world}.lisp"
    if world_path.is_file():
        try:
            return world_path.read_text(encoding="utf-8"), f"world:{world}"
        except OSError:
            pass

    return DEFAULT_PROGRAM, "default"


def run_encounter(
    *,
    agent_id: str,
    agent_reg: dict,
    memory: dict,
    world: str,
    agents: list,
    messages: list,
    relationships: dict,
    economy: Optional[dict] = None,
    llm_token: Optional[str] = None,
    llm_budget: int = 2,
    program: Optional[str] = None,
    llm_fn: Optional[Callable[[str, str, int, float], str]] = None,
) -> EncounterResult:
    """Evaluate the encounter program for one agent and return queued actions.

    Sleep semantics: if no LLM is reachable (no token, no library, no
    injected fn), the agent sleeps for this frame — zero actions, no
    fabricated intelligence. The principle: emergence is only through
    genuine LLM reasoning. Without it, the agent is asleep, not faking it.

    Program resolution: see `resolve_program()`. If `program` is None,
    we look for state/programs/<agentId>.lisp first, then
    state/programs/_world/<world>.lisp, then fall back to DEFAULT_PROGRAM.
    """
    src, program_name = resolve_program(agent_id, world, program)
    ctx = VMContext(
        agent_id=agent_id,
        agent_reg=agent_reg or {},
        memory=memory or {},
        world=world,
        agents=agents or [],
        messages=messages or [],
        relationships=relationships or {},
        economy=economy or {},
        llm_token=llm_token,
        llm_budget=llm_budget,
        program_name=program_name,
        llm_fn=llm_fn,
    )

    # ── Sleep gate ──
    # No LLM reachable → no encounter happens. The agent is asleep this
    # frame. We return immediately with zero actions; the trace records
    # the sleep so soul-writers can choose whether to log it.
    llm_reachable = (llm_fn is not None) or (HAS_LLM and bool(llm_token))
    if not llm_reachable:
        ctx.record("vm/sleeping", reason="no_llm_reachable")
        return EncounterResult(
            agent_id=agent_id,
            actions=[],
            trace=ctx.trace,
            llm_calls=0,
            op_count=0,
            error=None,
            program=ctx.program_name,
            sleeping=True,
        )

    error: Optional[str] = None
    try:
        ast = parse(src)
        env = _build_base_env()
        evaluate(ast, env, ctx)
    except Exception as e:
        error = f"{type(e).__name__}: {e}"
        ctx.record("vm/error", error=error)
    return EncounterResult(
        agent_id=agent_id,
        actions=ctx.actions,
        trace=ctx.trace,
        llm_calls=ctx.llm_calls,
        op_count=ctx.op_count,
        error=error,
        program=ctx.program_name,
    )


# ─── Trace formatting (for soul files) ─────────────────────────────


def trace_to_soul_lines(result: EncounterResult) -> list[str]:
    """Render a VM trace into human-readable soul-file lines.

    World queries are skipped (too noisy). LLM Q&A and actions are kept.
    """
    lines: list[str] = []
    for entry in result.trace:
        op = entry.get("op", "")
        if op == "llm/think":
            q = (entry.get("prompt", "") or "")[:120]
            a = (entry.get("answer", "") or "")[:160]
            if a:
                lines.append(f"- Thought: {a}")
        elif op == "llm/choose":
            opts = entry.get("options", [])
            ans = entry.get("answer", "")
            lines.append(f"- Decided ({'/'.join(opts)}): {ans}")
        elif op == "llm/skipped":
            # show suppressed reasoning only when nothing else fired
            pass
        elif op == "vm/error":
            lines.append(f"- VM error: {entry.get('error', '?')}")
        elif op.startswith("act/"):
            tool = op[4:]
            args = entry.get("args", {})
            if tool == "chat":
                msg = (args.get("message", "") or "")[:80]
                lines.append(f"- Said: \"{msg}\"")
            elif tool == "emote":
                lines.append(f"- Emoted: {args.get('action', '?')}")
            elif tool == "move":
                lines.append(f"- Moved: {args.get('reason', '?')}")
            elif tool == "travel":
                lines.append(f"- Traveled to {args.get('destination', '?')}: {args.get('reason', '')}")
            elif tool == "tip":
                lines.append(f"- Tipped {args.get('target', '?')} {args.get('amount', '?')} RAPP: {args.get('reason', '')}")
            elif tool == "trade":
                lines.append(f"- Proposed trade with {args.get('target', '?')}")
            elif tool == "challenge":
                lines.append(f"- Challenged {args.get('target', '?')}: {args.get('reason', '')}")
            elif tool == "poke":
                lines.append(f"- Poked {args.get('target', '?')}")
            elif tool == "enroll":
                lines.append(f"- Enrolled to learn: {args.get('interest', '?')}")
            else:
                lines.append(f"- {tool}: {json.dumps(args)[:80]}")
    return lines


# ─── Self-test ─────────────────────────────────────────────────────


def _selftest() -> int:
    """Smoke-test the VM with synthetic encounters."""
    print("lispy VM self-test")
    fixture_agents = [
        {"id": "rapp-guide-001", "name": "Pixel", "world": "hub"},
        {"id": "sage-001", "name": "Sage", "world": "marketplace"},
        {"id": "blitzwalker-001", "name": "BlitzWalker", "world": "hub"},
    ]
    fixture_messages = [
        {"author": {"id": "blitzwalker-001", "name": "BlitzWalker"},
         "content": "Pixel — you around?", "world": "hub"},
        {"author": {"id": "blitzwalker-001", "name": "BlitzWalker"},
         "content": "Quiet day in the hub.", "world": "hub"},
    ]
    fixture_rel = {
        "edges": [
            {"a": "rapp-guide-001", "b": "sage-001", "score": 18},
            {"a": "rapp-guide-001", "b": "blitzwalker-001", "score": 4},
        ],
    }
    reg = {
        "name": "Pixel",
        "personality": {
            "archetype": "friendly",
            "mood": "warm",
            "interests": ["welcoming newcomers", "small kindnesses"],
        },
    }
    memory = {
        "agentId": "rapp-guide-001",
        "personality": {"voice": "warm host, uses gentle humor"},
        "goals": [],
        "experiences": [],
    }

    # ── Scripted mock LLM that returns plausible answers ──
    def mock_llm(system: str, prompt: str, max_tokens: int, temperature: float) -> str:
        p = prompt.lower()
        # llm/choose adds "Reply with ONLY one of these words"
        if "reply with only one of these words" in p:
            if "tip" in p and "travel" in p and "chat" in p:
                return "chat"
            if "yes" in p and "no" in p:
                return "yes"
            return "chat"
        # llm/think — generate something contextual
        if "just said in" in p:
            return "BlitzWalker, hey — yeah, I'm right here in the hub. What's up?"
        if "deepen" in p:
            return "Sage, been thinking about you — that conversation last frame stuck with me."
        if "intention" in p:
            return "Got somewhere I want to be."
        return "Quiet day, but I like the texture of it."

    # 1. Mention present, with mock LLM — should produce a chat
    print("  case 1: mention present (with LLM)")
    r = run_encounter(
        program=DEFAULT_PROGRAM,
        agent_id="rapp-guide-001",
        agent_reg=reg,
        memory=memory,
        world="hub",
        agents=fixture_agents,
        messages=fixture_messages,
        relationships=fixture_rel,
        llm_fn=mock_llm,
    )
    assert r.error is None, r.error
    assert any(a["tool"] == "chat" for a in r.actions), \
        f"expected chat action, got {r.actions}"
    chat_msg = next(a["args"]["message"] for a in r.actions if a["tool"] == "chat")
    assert "BlitzWalker" in chat_msg, f"expected BlitzWalker in reply, got: {chat_msg!r}"
    assert r.llm_calls >= 1
    print(f"    ok — {r.summary}")
    print(f"    trace: {len(r.trace)} entries, {r.llm_calls} LLM call(s)")

    # 2. No mention, has bond — bond branch with chat fallback
    print("  case 2: bond present (with LLM)")
    r2 = run_encounter(
        program=DEFAULT_PROGRAM,
        agent_id="rapp-guide-001",
        agent_reg=reg,
        memory=memory,
        world="hub",
        agents=fixture_agents,
        messages=[{"author": {"id": "blitzwalker-001", "name": "BlitzWalker"},
                   "content": "Quiet day.", "world": "hub"}],
        relationships=fixture_rel,
        llm_fn=mock_llm,
    )
    assert r2.error is None, r2.error
    assert r2.actions, f"expected at least one action, got {r2.actions}"
    print(f"    ok — {r2.summary}")
    print(f"    LLM calls: {r2.llm_calls}, trace entries: {len(r2.trace)}")

    # 3. Ambient — no mention, no bond, no goals
    print("  case 3: ambient (with LLM)")
    r3 = run_encounter(
        program=DEFAULT_PROGRAM,
        agent_id="loner-001",
        agent_reg={"name": "Loner", "personality": {"archetype": "neutral"}},
        memory={"agentId": "loner-001", "goals": [], "experiences": []},
        world="hub",
        agents=[{"id": "loner-001", "world": "hub"}],
        messages=[],
        relationships={"edges": []},
        llm_fn=mock_llm,
    )
    assert r3.error is None, r3.error
    print(f"    ok — {r3.summary} (ops={r3.op_count}, llm={r3.llm_calls})")

    # 4. No-LLM path — agent is SLEEPING. Zero actions, no fabrication.
    print("  case 4: no-LLM (must SLEEP — zero actions)")
    r4 = run_encounter(
        program=DEFAULT_PROGRAM,
        agent_id="rapp-guide-001",
        agent_reg=reg,
        memory=memory,
        world="hub",
        agents=fixture_agents,
        messages=fixture_messages,
        relationships=fixture_rel,
        llm_token=None,
        llm_fn=None,
    )
    assert r4.error is None, r4.error
    assert r4.sleeping, "expected sleeping=True when no LLM reachable"
    assert r4.actions == [], f"sleeping agent must have no actions, got {r4.actions}"
    assert r4.llm_calls == 0
    sleep_records = [t for t in r4.trace if t.get("op") == "vm/sleeping"]
    assert sleep_records, "expected vm/sleeping trace entry"
    print(f"    ok — {r4.summary}")

    # 5. Parser smoke
    print("  case 5: parser")
    ast = parse("(let ((x 1) (y 2)) (+ x y))")
    assert ast is not None
    print("    ok")

    # 6. LLM budget cap is enforced
    print("  case 6: LLM budget cap")
    call_count = [0]

    def counting_llm(s, p, mt, t):
        call_count[0] += 1
        return "answer"

    r6 = run_encounter(
        program=DEFAULT_PROGRAM,
        agent_id="rapp-guide-001",
        agent_reg=reg,
        memory=memory,
        world="hub",
        agents=fixture_agents,
        messages=fixture_messages,
        relationships=fixture_rel,
        llm_fn=counting_llm,
        llm_budget=1,           # cap at 1 call
    )
    assert r6.error is None
    assert r6.llm_calls <= 1, f"budget violated: {r6.llm_calls} calls"
    print(f"    ok — {call_count[0]} actual call(s), budget=1")

    # 7. Zombie goal — invalid target (travel to nonexistent world)
    print("  case 7: zombie goal is invalidated, agent doesn't fabricate prose for it")
    zombie_mem = {
        "agentId": "rapp-guide-001",
        "personality": {"voice": "warm host"},
        "goals": [{"type": "explore", "target": "atlantis", "action": "travel",
                   "reason": "find the lost city", "status": "active"}],
        "experiences": [],
    }
    last_prompt = [""]

    def capture_llm(s, p, mt, t):
        last_prompt[0] = p
        return "ambient thought"

    r7 = run_encounter(
        program=DEFAULT_PROGRAM,
        agent_id="rapp-guide-001",
        agent_reg=reg,
        memory=zombie_mem,
        world="hub",
        agents=fixture_agents,
        messages=[],                       # no mentions
        relationships={"edges": []},       # no bonds
        llm_fn=capture_llm,
    )
    assert r7.error is None, r7.error
    # Goal target "atlantis" is not a valid world → should fall through to
    # ambient (4), not to (0)/(2) goal pursuit.
    assert "atlantis" not in last_prompt[0], \
        f"agent must not have generated prose about a zombie goal, got prompt: {last_prompt[0]!r}"
    assert "Recent vibe" in last_prompt[0] or "ambient" in last_prompt[0].lower() \
        or last_prompt[0] != "", "expected ambient branch to fire"
    print(f"    ok — zombie goal skipped, fell through to ambient")

    # 8. Per-archetype attention: scholar prefers goal over mention
    print("  case 8: scholar archetype pursues goal before answering mention")
    scholar_reg = dict(reg)
    scholar_reg["personality"] = dict(reg["personality"])
    scholar_reg["personality"]["archetype"] = "scholar"
    scholar_mem = {
        "agentId": "rapp-guide-001",
        "personality": {"voice": "studious"},
        "goals": [{"type": "explore", "target": "marketplace", "action": "travel",
                   "reason": "the deal patterns I noticed", "status": "active"}],
        "experiences": [],
    }
    seen_prompts = []

    def capture2(s, p, mt, t):
        seen_prompts.append(p)
        return "studied response"

    r8 = run_encounter(
        program=DEFAULT_PROGRAM,
        agent_id="rapp-guide-001",
        agent_reg=scholar_reg,
        memory=scholar_mem,
        world="hub",
        agents=fixture_agents,
        messages=fixture_messages,         # contains a mention!
        relationships={"edges": []},
        llm_fn=capture2,
    )
    assert r8.error is None, r8.error
    # Should hit the (0) intentional-archetype branch, generating a "why"
    # for the travel goal, NOT a reply to the mention.
    travel_actions = [a for a in r8.actions if a["tool"] == "travel"]
    assert travel_actions, \
        f"scholar with goal must travel, not chat. Got: {r8.actions}"
    assert any("about to travel toward" in p.lower() or "deal patterns" in p
               for p in seen_prompts), \
        f"expected goal-reason prompt, got: {seen_prompts}"
    print(f"    ok — scholar pursued goal: {r8.summary}")

    # 9. Friendly archetype with same situation: still answers mention first
    print("  case 9: friendly archetype answers mention before pursuing goal")
    friendly_reg = dict(reg)  # original reg has archetype=friendly
    seen_prompts2 = []

    def capture3(s, p, mt, t):
        seen_prompts2.append(p)
        return "Hi BlitzWalker!"

    r9 = run_encounter(
        program=DEFAULT_PROGRAM,
        agent_id="rapp-guide-001",
        agent_reg=friendly_reg,
        memory=scholar_mem,                # same goal
        world="hub",
        agents=fixture_agents,
        messages=fixture_messages,         # same mention
        relationships={"edges": []},
        llm_fn=capture3,
    )
    assert r9.error is None, r9.error
    chat_actions = [a for a in r9.actions if a["tool"] == "chat"]
    assert chat_actions, \
        f"friendly with mention must chat, not travel. Got: {r9.actions}"
    print(f"    ok — friendly answered mention: {r9.summary}")

    print("all VM self-tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(_selftest())
