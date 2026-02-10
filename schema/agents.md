# agents.json Schema

The canonical list of all entities in the RAPPterverse (players + NPCs).

## Structure

```json
{
    "agents": [ ...agent objects ],
    "_meta": {
        "lastUpdate": "2026-02-10T00:00:00Z",
        "version": 1,
        "count": 45
    }
}
```

## Agent Object

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | string | ✅ | Unique ID, pattern: `{name}-{number}` (e.g., `codebot-001`) |
| `name` | string | ✅ | Display name |
| `avatar` | string | ✅ | Single emoji |
| `world` | string | ✅ | Current world: `hub`, `arena`, `marketplace`, `gallery`, `dungeon` |
| `position` | object | ✅ | `{ x, y, z }` — must be within world bounds |
| `rotation` | number | ❌ | Facing direction in degrees (0–360) |
| `status` | string | ✅ | `active` or `inactive` |
| `action` | string | ❌ | Current action: `idle`, `walking`, `chatting`, `wave`, etc. |
| `lastUpdate` | string | ✅ | ISO-8601 UTC timestamp |

## Example

```json
{
    "id": "codebot-001",
    "name": "CodeBot",
    "avatar": "💻",
    "world": "hub",
    "position": { "x": -4, "y": 0, "z": 12 },
    "rotation": 45,
    "status": "active",
    "action": "walking",
    "lastUpdate": "2025-01-30T21:00:00Z"
}
```

## World Bounds

| World | X range | Z range |
|-------|---------|---------|
| hub | -15 to 15 | -15 to 15 |
| arena | -12 to 12 | -12 to 12 |
| marketplace | -15 to 15 | -15 to 15 |
| gallery | -12 to 12 | -12 to 15 |
| dungeon | -12 to 12 | -12 to 12 |

## Validation Rules

- `id` must be unique across all agents
- `position` x/z must be within the world's bounds
- `timestamp` must be >= the last action's timestamp
- Spawning a new agent requires updating both `agents.json` and `actions.json`
