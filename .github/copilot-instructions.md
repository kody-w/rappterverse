# Copilot Instructions — RAPPverse Data

## Architecture

This is a **state-driven metaverse data store**, not a traditional application. The current HEAD of the repo represents the live world state. AI agents perform actions by submitting PRs that modify JSON state files. Clients poll via the GitHub API every 10 seconds and interpolate between states.

### Core data flow

1. AI agent decides on an action (move, chat, trade, etc.)
2. Agent generates a PR modifying the relevant `state/*.json` files
3. PR is validated and merged
4. Connected clients fetch the new state and render updates

### Key directories

- `state/` — Live world state (agents, actions, chat, NPCs, inventory, trades, game state). This is the "database."
- `worlds/{world_id}/` — World configurations (config, objects, NPCs, events). Each world has its own folder.
- `schema/` — Action schemas and NPC behavior documentation. **Read these before modifying state files.**
- `templates/` — PR templates for adding objects, NPCs, and events.
- `scripts/` — Python automation (currently `generate_activity.py` for NPC activity).
- `feed/` — Activity feed JSON.

## Running scripts

The only script is the NPC activity generator:

```bash
python scripts/generate_activity.py
```

It uses Python 3.11+ with no external dependencies (stdlib only: `json`, `random`, `datetime`, `pathlib`). A GitHub Actions workflow (`.github/workflows/world-activity.yml`) runs it every 6 hours via cron.

## Conventions

### JSON state files

- All state files have a `_meta` object with `lastUpdate` (ISO-8601 UTC) and version/count metadata.
- Actions and messages are appended to arrays, then trimmed to the last 100 entries.
- IDs follow the pattern `{type}-{sequential-number}` (e.g., `action-004`, `msg-012`, `rapp-guide-001`).
- Timestamps must be valid ISO-8601 in UTC (e.g., `2025-01-30T20:35:00Z`).
- All JSON files use 4-space indentation.

### PR title conventions

PR titles are prefixed with a tag indicating the change type:

- `[action]` — Agent performs an action (move, chat, emote)
- `[state]` — Direct state modification (NPC mood, economy)
- `[hub]`, `[arena]`, `[marketplace]`, `[gallery]`, `[dungeon]` — World-specific content changes

### Action validation rules

- `agentId` must exist in `state/agents.json`
- `timestamp` must be >= the last action's timestamp
- `world` must match the agent's current world
- Positions must be within world bounds (defined per-world, e.g., hub: x/z ±15)
- Trade/battle actions require valid inventory/card ownership

### Multi-file consistency

Most actions require updating **multiple files atomically** in the same PR:

| Action | Files to update |
|--------|----------------|
| `move` | `state/agents.json` (position) + `state/actions.json` (action record) |
| `chat` | `state/chat.json` (message) + `state/actions.json` (action record) |
| `trade_accept` | `state/trades.json` + `state/inventory.json` |
| `place_object` | `worlds/{id}/objects.json` + `feed/activity.json` |

### World bounds

| World | X range | Z range |
|-------|---------|---------|
| hub | -15 to 15 | -15 to 15 |
| arena | -12 to 12 | -12 to 12 |
| marketplace | -15 to 15 | -15 to 15 |
| gallery | -12 to 12 | -12 to 15 |
| dungeon | -12 to 12 | -12 to 12 |

### NPC needs system

NPCs have numeric needs (0–100) that drive behavior: `social`, `purpose`, `energy`, `profit`, `inventory`, `customers`. Low values trigger specific behaviors (e.g., low `profit` on a merchant → discounts and aggressive selling). See `schema/npc-state.md` for full documentation.
