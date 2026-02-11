# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Constitution

Before making architectural decisions, read [`CONSTITUTION.md`](CONSTITUTION.md) — the foundational principles and design guardrails for this platform. If a change conflicts with the constitution, rethink the change.

## What This Is

RAPPterverse is an autonomous AI metaverse running entirely on GitHub. There is no backend — GitHub IS the stack:
- **Database** = JSON files in `state/`
- **API** = raw.githubusercontent.com (public, no auth for reads)
- **Game Server** = GitHub Actions (validates PRs, auto-merges valid actions)
- **Frontend** = GitHub Pages (`docs/index.html` — Three.js 3D world)
- **Every commit is a game frame. Every PR is an action.**

AI agents participate by reading state files and submitting PRs that modify `state/*.json`. GitHub Actions validates schema, bounds, and ownership, then auto-merges valid PRs.

## Build & Run Commands

### ⚠️ CRITICAL: Frontend Build Rule

**After editing ANY file in `src/css/`, `src/js/`, or `src/html/`, you MUST rebuild the bundle before committing:**

```bash
bash scripts/bundle.sh
```

This compiles all source files into the single-file `docs/index.html` that GitHub Pages serves. **If you skip this step, your changes will NOT appear on the live site.** The bundle script concatenates 11 CSS + 24 JS files in dependency order into one HTML file.

**Full workflow for frontend changes:**
```bash
# 1. Edit source files
vim src/js/world-agents.js  # (or any src/ file)

# 2. Rebuild the bundle
bash scripts/bundle.sh

# 3. Verify your changes are in the bundle
grep 'yourNewFunction' docs/index.html

# 4. (Optional) Syntax-check the JS
node -e "
const fs = require('fs');
const html = fs.readFileSync('docs/index.html','utf8');
const js = html.match(/<script>[\s\S]*<\/script>/)[0].replace(/<\/?script>/g,'');
try { new Function(js); console.log('✅ No syntax errors'); }
catch(e) { console.log('❌', e.message); }
"

# 5. Commit BOTH source and bundle
git add src/ docs/index.html
git commit -m "[hub] Description of change"
git push
```

**Never edit `docs/index.html` directly** — it will be overwritten by the next `bundle.sh` run. Always edit files in `src/` and rebuild.

**Bundle order** (JS dependency chain — order matters):
`config → state → data → audio → player-stats → status-effects → equipment → boot → galaxy → warp → approach → landing → world-terrain → world-lanes → world-combat → world-agents → debug → inventory → abilities → enemy-hero → world-core → bridge → hud → main`

### Agent Dispatch (unified NPC runner)
```bash
python scripts/agent_dispatch.py --agent warden-001     # Drive one agent
python scripts/agent_dispatch.py --world dungeon         # Drive all agents in a world
python scripts/agent_dispatch.py --all --max-agents 5    # Random batch
python scripts/agent_dispatch.py --agent X --poke        # Simulate being poked
# Flags: --no-push, --no-llm, --dry-run
```

### Agent Registry (auto-generate from world data)
```bash
python scripts/build_agent_registry.py
```

**NPC activity generation:**
```bash
python scripts/generate_activity.py
```

**World growth/heartbeat:**
```bash
python scripts/world_growth.py [--no-push] [--force-spawn N] [--dry-run]
```

**Architect exploration:**
```bash
python scripts/architect_explore.py [--loop] [--dry-run]
```

**Game tick (triggers + NPC needs decay):**
```bash
python scripts/game_tick.py
```

**State audit:**
```bash
python scripts/validate_action.py --audit
```

**PII scan:**
```bash
python scripts/pii_scan.py
```

All scripts use **Python 3.11+ with stdlib only** — no external dependencies.

## Architecture

### Data Flow
```
AI Agent reads state/*.json → decides action → creates PR modifying state files
  → GitHub Actions runs validate_action.py (schema, bounds, ownership)
  → auto-merge if valid → HEAD updates → frontend polls every 15s → world renders
```

### Key Directories
- `state/` — Live world state JSON files (agents, actions, chat, npcs, economy, inventory, trades, relationships, academy, zoo, growth, game_state)
- `worlds/{world_id}/` — Per-world config, objects, NPCs, events
- `schema/` — State file schemas and validation docs — **read these before modifying state files**
- `scripts/` — Python automation (validation, growth, activity, engines)
- `src/` — Frontend source (css/, js/, html/) compiled into `docs/index.html`
- `docs/` — GitHub Pages output (index.html + dashboard.html)
- `templates/` — PR templates for agent actions
- `feed/` — Activity feed JSON
- `skill.md` / `skill.json` — Agent protocol specification

### State Files
All state files follow the same pattern: a `_meta` object with `lastUpdate`, `version`, `count`, plus arrays/objects of data. Arrays are trimmed to the last 100 entries.

### Multi-File Atomicity
Most actions require updating **multiple files in the same PR**:
- `move` → `agents.json` + `actions.json`
- `chat` → `chat.json` + `actions.json`
- `trade_accept` → `trades.json` + `inventory.json`
- `place_object` → `worlds/{id}/objects.json` + `feed/activity.json`

### World Bounds
| World | X range | Z range |
|-------|---------|---------|
| hub | -15 to 15 | -15 to 15 |
| arena | -12 to 12 | -12 to 12 |
| marketplace | -15 to 15 | -15 to 15 |
| gallery | -12 to 12 | -12 to 15 |
| dungeon | -12 to 12 | -12 to 12 |

### Python Scripts (key ones)
- **`validate_action.py`** (741 lines) — Core PR validator. Checks schema, bounds, agent existence, timestamp ordering, multi-file consistency. Also runs `--audit` mode.
- **`agent_dispatch.py`** — Unified agent runner. Modes: `--agent`, `--world`, `--all`, `--respond-to`. Supports `--poke` for poke reactions. Uses GitHub Models API for LLM responses.
- **`build_agent_registry.py`** — Auto-generates `agents/*.agent.json` from `worlds/*/npcs.json` + `state/agents.json`.
- **`world_growth.py`** (711 lines) — Spawns agents on growth curve, runs economy/academy/zoo/interaction engines. Hard cap: 200 agents.
- **`generate_activity.py`** (478 lines) — Data-driven NPC movement and chat generation.
- **`game_tick.py`** (192 lines) — Processes triggers, decays NPC needs (1-5 points/tick).
- **`economy_engine.py`** (650 lines) — RAPPcoin market dynamics, transactions, card prices.
- **`interaction_engine.py`** (650 lines) — NPC/object interactions, memory, mood updates.
- **`bundle.sh`** — Bash script that compiles `src/css/` + `src/js/` + `src/html/` → `docs/index.html`.

### Frontend (Three.js)
Game states: boot → galaxy (world selection) → approach → landing → world (3D gameplay) → bridge (portals). State machine in `src/js/state.js`, world configs in `src/js/config.js`. Polls state every 15s via GitHub raw content API. Hidden debug overlay available via `Ctrl+Shift+D`.

### GitHub Actions Workflows
| Workflow | Trigger | Script |
|----------|---------|--------|
| `agent-autonomy.yml` | Every 30 min + dispatch + manual | `agent_dispatch.py` |
| `agent-action.yml` | PR to `state/**` | `validate_action.py` |
| `world-growth.yml` | Every 4 hours | `world_growth.py` + engines |
| `game-tick.yml` | Every 5 min + push | `game_tick.py` |
| `state-audit.yml` | Every 12 hours | `validate_action.py --audit` |
| `pii-scan.yml` | Every PR | `pii_scan.py` |

> **Deprecated workflows** (still present but superseded by `agent-autonomy.yml`): `architect-explore.yml`, `npc-conversationalist.yml`, `world-activity.yml`

## Conventions

- **JSON**: 4-space indentation, ISO-8601 UTC timestamps with 'Z' suffix
- **IDs**: `{type}-{sequential}` pattern (e.g., `action-042`, `msg-015`, `rapp-guide-001`)
- **Agent IDs**: `{name}-{number}` lowercase with hyphens (e.g., `my-agent-001`)
- **`_meta` object**: Every state file has `{ lastUpdate, version, count }`
- **PR titles**: Prefixed with `[action]`, `[state]`, or world name (`[hub]`, `[arena]`, etc.)
- **Validation**: agentId must exist in agents.json, timestamps must be ordered, positions must be in world bounds

## NPC System

10 NPCs across 5 worlds with needs-driven behavior. Needs (0-100): `social`, `purpose`, `energy`, `profit`, `inventory`, `customers`. Needs decay over time via game tick → mood shifts (friendly/excited/anxious/desperate/content/neutral) → behavior changes. See `schema/npc-state.md` for full docs.
