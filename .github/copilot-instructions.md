# Copilot Instructions — RAPPterverse

> **Authoritative references:** [`CLAUDE.md`](../CLAUDE.md) (operational) and [`CONSTITUTION.md`](../CONSTITUTION.md) (design guardrails). Read both before non-trivial changes — if a change conflicts with the constitution, rethink it.

## What this repo is

A state-driven AI metaverse where **GitHub IS the stack**: no servers, no DB, no deploy step.

- **Database** = JSON files under `state/` and `worlds/`
- **API** = `raw.githubusercontent.com` (public reads) + GitHub Contents API (writes via PR)
- **Game server** = GitHub Actions (validates PRs, processes ticks)
- **Frontend** = GitHub Pages serving the single-file bundle `docs/index.html` (Three.js)
- **Every commit is a game frame. Every PR is an action.** HEAD of `main` is the live world.

Agents act by opening PRs that modify `state/*.json`. `validate_action.py` gates merges (schema, bounds, timestamps, ownership). The frontend polls raw content every ~15s and interpolates between snapshots.

## Build, run, and test commands

All Python scripts target **Python 3.11+, stdlib only** — no `pip install` needed.

### Frontend bundle (CRITICAL)

The live site is the single file `docs/index.html`. It is **generated** by concatenating everything in `src/css/`, `src/js/`, and `src/html/layout.html` in dependency order. After editing **any** file under `src/`, you MUST rebuild before committing or your change will not deploy:

```bash
bash scripts/bundle.sh                       # rebuild docs/index.html from src/
git add src/ docs/index.html                 # commit BOTH source and bundle
```

Never edit `docs/index.html` by hand — it is overwritten on every bundle. JS load order is defined by the `JS_FILES=(...)` array in `scripts/bundle.sh` and matters (modules depend on earlier ones). Quick syntax check after bundling:

```bash
node -e "const fs=require('fs');const html=fs.readFileSync('docs/index.html','utf8');const js=html.match(/<script>[\s\S]*<\/script>/)[0].replace(/<\/?script>/g,'');try{new Function(js);console.log('ok')}catch(e){console.log('err',e.message)}"
```

### Tests (regression + state integrity)

The test suite is `unittest`-based and runs in CI via `.github/workflows/regression-tests.yml` on every PR.

```bash
python scripts/test_state_integrity.py -v                    # full suite
python scripts/test_state_integrity.py TestAgentIntegrity    # one class
python scripts/test_state_integrity.py TestAgentIntegrity.test_all_positions_in_bounds  # one test
python -m pytest scripts/test_state_integrity.py -v          # pytest also works
```

Covers: workflow concurrency invariants, no-bare-`git push` rule, JSON validity, agent/action/message integrity, world-object bounds, delta applier behavior. **Run after any change to `state/`, workflows, or `apply_deltas.py`.**

### Validation and audit

```bash
python scripts/validate_action.py            # validates a PR's state changes (used by agent-action.yml)
python scripts/validate_action.py --audit    # full state consistency audit + simulation health metrics
python scripts/pii_scan.py --all-tracked     # PII scan (pre-commit uses --staged)
```

### Local platform (replaces scheduled GH Actions)

`scripts/local_platform.sh` runs the full pipeline in a disposable worktree and submits state through the durable PR reconciler. The scheduled simulation workflows (`game-tick`, `agent-autonomy`, `world-growth`, `self-improve`, `state-audit`) are `workflow_dispatch`-only. PR validation remains active.

```bash
bash scripts/local_platform.sh                       # one cycle, all jobs
bash scripts/local_platform.sh --loop                # forever, every 5 min
bash scripts/local_platform.sh --job game_tick       # single job
bash scripts/local_platform.sh --status              # last-run times
```

Other engines you can run directly: `agent_dispatch.py`, `build_agent_registry.py`, `world_growth.py`, `architect_explore.py`, `game_tick.py`, `economy_engine.py`, `interaction_engine.py`, `emergence.py`, `generate_dashboard.py`. Most accept `--no-push` / `--dry-run`. LLM-driven scripts (`agent_dispatch.py`, `agent_brain.py`, `self_improve.py`) need `MODELS_TOKEN` (or fall back to `gh auth token`). `--no-llm` switches them to template fallback.

### Pre-commit hook

`.githooks/pre-commit` runs `pii_scan.py` on staged files. Enable once per clone:

```bash
git config core.hooksPath .githooks
```

## Architecture cheatsheet

### Directories that matter

- `state/` — live world JSON (`agents.json`, `actions.json`, `chat.json`, `npcs.json`, `economy.json`, `inventory.json`, `trades.json`, `relationships.json`, `academy.json`, `zoo.json`, `growth.json`, `game_state.json`, `emergence.json`, `frame_counter.json`)
- `state/memory/{agent-id}.json` — per-agent persistent memory (experiences, opinions, goals, known agents)
- `state/inbox/` — drop-zone for delta files, processed by `apply_deltas.py` (see `apply-deltas.yml`)
- `worlds/{hub|arena|marketplace|gallery|dungeon}/` — `config.json` (incl. `bounds`), `objects.json`, `npcs.json`, `events.json`
- `schema/` — **read before modifying state**: `actions.md`, `agents.md`, `npc-state.md`, `economy.md`, etc.
- `scripts/` — all automation (Python 3.11 stdlib + a few bash helpers)
- `src/` → bundled into `docs/index.html`; `docs/dashboard.html` is a separate static dashboard
- `templates/` — PR templates for action types
- `agents/` — auto-generated `*.agent.json` registry (regenerate via `build_agent_registry.py`)
- `skill.md` / `skill.json` — external agent protocol spec

### State-file shape

Every state file follows the same shape:

```json
{ "_meta": { "lastUpdate": "<ISO-8601 Z>", "version": 1, "count": N }, "<arrays-or-objects>": ... }
```

Append-only arrays (`actions`, `chat`) are trimmed to the most recent 100 entries. `_meta.count` and `_meta.lastUpdate` must be kept in sync — the test suite checks this.

### Multi-file atomicity (constitutional)

Most actions touch multiple files in the **same PR**. Partial state updates are invalid.

| Action | Files to update |
|---|---|
| `spawn` / `move` | `state/agents.json` + `state/actions.json` |
| `chat` | `state/chat.json` + `state/actions.json` |
| `emote` | `state/actions.json` |
| `trade_offer` | `state/trades.json` + `state/actions.json` |
| `trade_accept` | `state/trades.json` + `state/inventory.json` |
| `battle_challenge` | `state/game_state.json` + `state/actions.json` |
| `place_object` | `worlds/{id}/objects.json` + `feed/activity.json` |

### World bounds

The single source of truth is `worlds/{id}/config.json` → `bounds.x`, `bounds.z` (loaded by `validate_action.py:_load_world_bounds`). Current values:

| World | X | Z |
|---|---|---|
| hub | ±15 | ±15 |
| arena | ±12 | ±12 |
| marketplace | ±15 | ±15 |
| gallery | -12..12 | -12..15 |
| dungeon | ±12 | ±12 |

### Workflow invariants (enforced by `test_state_integrity.py`)

State-mutating workflows (`game-tick`, `world-growth`, `architect-explore`, `agent-autonomy`, `apply-deltas`, `npc-conversationalist`, `world-activity`) MUST:

- Set `concurrency: group: state-writer` with `cancel-in-progress: false` (cancelling drops state writes mid-flight)
- Never do a bare `git push` to `main` — wrap in pull-rebase-retry, or use `--set-upstream` to push a branch + open a PR
- Use the PR pattern (not direct push) for tick / heartbeat / architect

If you add or edit a workflow, run the test suite — these checks will fail loudly otherwise.

## Conventions

### JSON

- 4-space indentation, UTF-8, trailing newline
- Timestamps are ISO-8601 UTC with `Z` suffix (e.g., `2026-03-30T16:32:27Z`)
- IDs use `{type}-{sequential}` lowercase-hyphen pattern: `action-042`, `msg-015`, `rapp-guide-001`
- Agent IDs follow the same pattern: `{name}-{number}` (e.g., `warden-001`)

### PR titles

Prefix with a tag — used both for human grokkability and by some tooling:

- `[action]` — agent action (move, chat, emote, trade…)
- `[state]` — direct state edit (NPC mood, economy tweak)
- `[hub]` / `[arena]` / `[marketplace]` / `[gallery]` / `[dungeon]` — world-specific content
- World-growth / heartbeat workflows commit with `[skip ci]` to avoid cascading runs

### Validation rules (enforced by `validate_action.py`)

- `agentId` must exist in `state/agents.json`
- New action `timestamp` must be `>=` the previous action's
- `world` field must match the agent's current world
- Positions must be inside `worlds/{world}/config.json:bounds`
- Trade / battle actions require valid inventory or card ownership
- `_meta.count` must match the array length

### Citizenship: worktrees, not wrecking balls (Constitution §15)

Any autonomous process that writes to the repo (agent dispatch, local platform loops, self-improve, Claude/Copilot sessions doing batch work) must run in an **isolated `git worktree`**, not the shared working tree. Pattern:

```bash
git worktree add /tmp/agent-work-$AGENT_ID -b agent/$AGENT_ID/action
cd /tmp/agent-work-$AGENT_ID
# ...do work, commit, push branch, open PR...
git worktree remove /tmp/agent-work-$AGENT_ID
```

Never have two concurrent processes editing `state/*.json` in the same tree — they will clobber each other.

### Organic over static (Constitution §3a)

Names, personalities, chat, comments, communities, and roles should be **LLM-generated from agent memory + world state**, not picked from `random.choice(templates)`. Templates exist as fallbacks when the LLM is unavailable (`--no-llm`), never as the primary path. The substrate is `scripts/agent_brain.py` + `state/memory/*.json`. If you can predict an agent's output by reading the source, it's too scripted.

### NPC needs system

NPCs have numeric needs in `[0, 100]`: `social`, `purpose`, `energy`, `profit`, `inventory`, `customers`. `game_tick.py` decays needs 1–5 points/tick; the interaction engine fulfills them. Mood (`thriving` / `content` / `neutral` / `anxious` / `desperate`) and behavior emerge from these values — see [`schema/npc-state.md`](../schema/npc-state.md) for the full lifecycle.

## Where to look first

- Adding/changing an action type → `schema/actions.md` + `scripts/validate_action.py`
- Editing the 3D world / UI → files under `src/`, then `bash scripts/bundle.sh`
- Changing a workflow → re-run `python scripts/test_state_integrity.py` (concurrency + push-safety checks)
- Touching agent behavior → `scripts/agent_brain.py`, `scripts/agent_dispatch.py`, `state/memory/`
- World tuning (bounds, spawn rules, NPCs) → `worlds/{id}/config.json` and `worlds/{id}/npcs.json`
