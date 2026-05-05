# state/programs/

The **Lispy Mirror**: each agent's twin authors the lispy program that
drives that agent's next frame.

When `slosh_lisp.py` runs, it normally compiles each agent's S-expression
routine from raw state (position, traits, mood, recent chat, goals). With
Lispy Mirror, if there is a file here named `<agentId>.lisp`, the slosh
compiler **uses that file's program verbatim** instead of synthesizing one.

## Authorship

Programs in this directory are written by an agent's *twin* — a separate
local brainstem with its own soul.md — answering the question: "If you
were this agent in this world, what is the lispy program YOU would run
for a normal frame? Encode your priorities and action bias as the
agent's mind for this tick."

The result is per-agent emergence at the program level. The agents write
their own minds. The world goes on with whatever they wrote, even if no
new frame ever arrives.

## File format

```
;; authored by <twin name> at <ISO-8601 UTC>
;; for <agent name> (<agentId>) in <world>
;; mood=<...> traits=<...>

(do
  (if <gate> <action> nil)
  (if <gate> <action> nil)
  ...)
```

Top-level must be a single `(do ...)` form; comments use `;;` and are
stripped before evaluation. The DSL is the same one `slosh_lisp.py`
emits — see that file for the full operator surface (`move-toward`,
`face-toward`, `wander`, `emote`, `agent-pos`, `nearest-agent`,
`player-pos`, `player-distance`, `mod`, `floor`, `elapsed`, `rand`,
`if`, `let`, `do`, `and`, `or`, `not`, comparisons, arithmetic).

## How to author

```
POST http://127.0.0.1:<twin-port>/chat
{
  "user_input": "If you were <agent name> ... write the lispy program YOU
                 would run for a normal frame ..."
}
```

Save the response (just the program) to `state/programs/<agentId>.lisp`.
The next slosh picks it up automatically.

## Boundary

Self-authored programs **must** validate against the slosh DSL — bad
forms are silently dropped (the agent falls back to the auto-compiled
program). Programs that exceed reasonable size or call non-existent
operators are rejected at evaluation time by the rappterVM.

The Lispy Mirror does not bypass world bounds, ownership rules, or any
other validation. It only controls *priority and bias*, not *capability*.
