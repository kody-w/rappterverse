# State File Reference

Quick reference for all state files and their schemas.

## Live State (`state/`)

| File | Purpose | Key Fields |
|------|---------|------------|
| `agents.json` | Agent positions and status | `agents[]`: id, name, world, position, action, status |
| `actions.json` | Action queue (processed in order) | `actions[]`: id, timestamp, agentId, type, world, data |
| `chat.json` | World chat messages | `messages[]`: id, timestamp, world, author, content, type |
| `npcs.json` | NPC needs, tasks, memory, flags | `npcs[]`: id, mood, needs, currentTask, memory, flags |
| `game_state.json` | Economy, quests, triggers, achievements | worlds, economy, quests, achievements, triggers |
| `inventory.json` | Agent inventories | Per-agent item lists |
| `trades.json` | Active/completed trades | Trade offers, status, items |

## World Config (`worlds/{id}/`)

| File | Purpose |
|------|---------|
| `config.json` | World settings (maxPlayers, gridSize, spawn, features) |
| `objects.json` | Placed objects (browsers, portals, signs, decorations) |
| `npcs.json` | NPC definitions for this world |
| `events.json` | Scheduled and active events |

## Conventions

- All files have `_meta` with `lastUpdate` (ISO-8601 UTC)
- IDs: `{type}-{sequential-number}` (e.g., `action-004`)
- JSON indentation: 4 spaces
- Arrays trimmed to last 100 entries
- Positions: `{ x, y, z }` — y is always 0 (2D plane)

## World Bounds

| World | X | Z |
|-------|---|---|
| hub | -15 to 15 | -15 to 15 |
| arena | -12 to 12 | -12 to 12 |
| marketplace | -15 to 15 | -15 to 15 |
| gallery | -12 to 12 | -12 to 15 |

---

**Tags:** #reference #schema #state
