# state/programs/_world/

**Per-world lispy programs.** Each `<world>.lisp` file is the default
encounter program for any agent in that world (unless they have a
twin-authored override at `state/programs/<agentId>.lisp`).

Resolution order in `lisp_vm.resolve_program()`:

1. Explicit `program=` argument passed to `run_encounter()`
2. `state/programs/<agentId>.lisp` — twin-authored per-agent
3. `state/programs/_world/<world>.lisp` — this directory
4. `lisp_vm.DEFAULT_PROGRAM` — built-in

## Why per-world

The DEFAULT_PROGRAM is *generic* — it serves any agent in any world.
World programs are specialized. They capture the **twitch reactions**
specific to a place:

| World | What the program optimizes for |
|---|---|
| `hub` | Hospitality. Answer mentions first, tip strong bonds, observe the gathering. |
| `arena` | Aggression. Challenge nearby rivals, especially for fighter archetypes. Terse chat. |
| `marketplace` | Profit. Trade with strangers, tip bonded merchants when balance allows. |
| `gallery` | Observation. Reflect on discoveries, share the room with bonded visitors. |
| `dungeon` | Survival. Travel-out goals fire first. Loyalty checks on bonds. Default to silence. |

## Hot-reload

These files are read fresh every encounter (no module-level cache).
Edit a `.lisp` file → next agent in that world runs the new program.
No script restart needed.

## Authoring

Each program must be a single S-expression that evaluates without
error. Available primitives are listed in `scripts/lisp_vm.py` under
`_build_base_env()`. Common ones:

  - `(world/me)` — agent id
  - `(world/world)` — current world id
  - `(world/balance)` — RAPP coin balance
  - `(world/nearby)` — list of agent ids in same world
  - `(world/strongest-bonds n)` — top-N bonded agents
  - `(world/chat-mentions)` — recent chat messages mentioning me
  - `(world/active-goals)` — list of active goals from memory
  - `(world/goal-valid? g)` — invalidate zombie goals
  - `(self/archetype)` — declared archetype string
  - `(llm/think prompt)` — free-form LLM call
  - `(llm/choose prompt options)` — constrained LLM call
  - `(act/chat msg)` `(act/travel dest why)` `(act/tip target n why)` etc.

The LLM budget is enforced **across the whole program** — programs
that call `(llm/think ...)` more than `llm_budget` times will get
empty strings back from later calls. Plan around that.

## Hard rules

* **No fabrication** — if no LLM is reachable, the agent sleeps.
  Don't invent fallback templates here.
* **Stale-goal-aware** — wrap goal-driven branches in
  `(world/goal-valid? g)` so we don't burn LLM calls on dead targets.
* **Honor archetype** — most programs check `(self/archetype)` to
  branch differently for `friendly` vs `aggressive` vs `scholar` etc.

## Future inputs

When new world-state inputs land (combat events, tower status,
score, momentum), they get exposed as new primitives in
`lisp_vm.py` and these programs gain new branches that read them.
The substrate stays small; the rule library grows.
