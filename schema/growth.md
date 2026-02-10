# growth.json Schema

Tracks world growth metrics — spawn history, heartbeat ticks, and agent name generation.

## Structure

```json
{
    "epoch_start": "2026-02-10T00:05:56Z",
    "tick_count": 77,
    "total_spawned": 26,
    "names_used": [ ...string array ],
    "_meta": {
        "lastUpdate": "2026-02-10T00:00:00Z"
    }
}
```

## Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `epoch_start` | string | ✅ | ISO-8601 UTC timestamp of when the world began |
| `tick_count` | number | ✅ | Total heartbeat ticks since epoch (increments every game tick) |
| `total_spawned` | number | ✅ | Total agents ever spawned (monotonically increasing) |
| `names_used` | array | ✅ | Agent names already generated (prevents duplicates) |
| `_meta.lastUpdate` | string | ✅ | ISO-8601 UTC timestamp of last modification |

## Example

```json
{
    "epoch_start": "2026-02-10T00:05:56Z",
    "tick_count": 77,
    "total_spawned": 26,
    "names_used": [
        "IonCoil",
        "BoltSage",
        "JoltLink",
        "BlitzWalker"
    ],
    "_meta": {
        "lastUpdate": "2026-02-10T15:34:47Z"
    }
}
```

## Validation Rules

- `tick_count` must be monotonically increasing (never decrease)
- `total_spawned` must equal the length of `names_used`
- `names_used` must contain no duplicates
- `epoch_start` must be a valid ISO-8601 UTC timestamp and must never change

## Updated By

| Workflow | Action |
|----------|--------|
| `world-growth.yml` | Increments `tick_count`, appends new names, increments `total_spawned` |
| `game-tick.yml` | Increments `tick_count` on each tick |
