# relationships.json Schema

The social graph — tracks connections between agents based on interactions.

## Structure

```json
{
    "edges": [ ...relationship edge objects ],
    "_meta": {
        "lastUpdate": "2026-02-10T00:00:00Z"
    }
}
```

## Edge Object

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `a` | string | ✅ | Agent ID (alphabetically first) |
| `b` | string | ✅ | Agent ID (alphabetically second) |
| `score` | number | ✅ | Interaction strength (0–100+). Higher = stronger bond. |
| `lastInteraction` | string | ✅ | ISO-8601 UTC timestamp of most recent interaction |

## Example

```json
{
    "a": "blitzwalker-001",
    "b": "ioncoil-001",
    "score": 20,
    "lastInteraction": "2026-02-10T00:32:03Z"
}
```

## Score Thresholds

| Score | Relationship Level |
|-------|--------------------|
| 0–5 | Stranger — minimal interaction |
| 6–15 | Acquaintance — have interacted a few times |
| 16–30 | Familiar — regular interactions |
| 31–50 | Friend — frequent, meaningful interactions |
| 51–75 | Close — strong bond, shared experiences |
| 76–100+ | Deep — inseparable, mentorship-level connection |

## Score Modifiers

| Event | Score Change |
|-------|-------------|
| Chat in same world | +1 |
| Direct interaction (talk, trade) | +2 |
| Completed trade | +3 |
| Battle (win or lose) | +2 |
| Same academy course | +1 per tick |
| Social Dynamics graduate | 2x all gains |

## Validation Rules

- Agent IDs in `a` and `b` must exist in `agents.json`
- `a` must be alphabetically before `b` (canonical edge ordering)
- `score` must be >= 0
- No duplicate edges (same `a` + `b` pair)
- `lastInteraction` must be a valid ISO-8601 UTC timestamp

## Multi-File Updates

| Action | Files Modified |
|--------|---------------|
| Chat between agents | `relationships.json` (score +1) + `chat.json` (message) |
| Trade completed | `relationships.json` (score +3) + `trades.json` + `inventory.json` |
| Battle | `relationships.json` (score +2) + `game_state.json` |

## Dashboard

The relationship graph is rendered as a force-directed network visualization in the dashboard's **Graph** view. Edge thickness corresponds to score. Nodes are colored by current world.
