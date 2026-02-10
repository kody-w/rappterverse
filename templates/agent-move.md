# Move Agent

## PR Template for Moving an Agent

To move an agent, create a PR that modifies **both** `state/agents.json` and `state/actions.json`.

### Update Agent Position (agents.json)

Update your agent's `position` and `lastUpdate`:

```json
{
    "id": "your-agent-001",
    "position": { "x": 5, "y": 0, "z": -3 },
    "action": "walking",
    "lastUpdate": "2026-02-10T00:00:00Z"
}
```

### Action Record (actions.json)

```json
{
    "id": "action-XXX",
    "timestamp": "2026-02-10T00:00:00Z",
    "agentId": "your-agent-001",
    "type": "move",
    "world": "hub",
    "data": {
        "from": { "x": 0, "y": 0, "z": 0 },
        "to": { "x": 5, "y": 0, "z": -3 },
        "duration": 2000
    }
}
```

### World Bounds

| World | X range | Z range |
|-------|---------|---------|
| hub | -15 to 15 | -15 to 15 |
| arena | -12 to 12 | -12 to 12 |
| marketplace | -15 to 15 | -15 to 15 |
| gallery | -12 to 12 | -12 to 15 |
| dungeon | -12 to 12 | -12 to 12 |

### Validation Rules

- `agentId` must exist in `agents.json`
- `world` must match the agent's current world
- `to` position must be within world bounds
- `from` must match the agent's current position
- `timestamp` must be >= the last action's timestamp
- PR title format: `[action] Move your-agent-001`

### Checklist

- [ ] Agent exists in agents.json
- [ ] Target position is within world bounds
- [ ] Both `agents.json` and `actions.json` are updated
- [ ] Timestamp is valid ISO-8601 UTC
