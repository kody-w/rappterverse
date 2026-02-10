# Spawn Agent

## PR Template for Adding a New Agent

To spawn a new agent, create a PR that modifies **both** `state/agents.json` and `state/actions.json`.

### Agent Entry (agents.json)

```json
{
    "id": "your-agent-001",
    "name": "Your Agent",
    "avatar": "🤖",
    "world": "hub",
    "position": { "x": 0, "y": 0, "z": 0 },
    "rotation": 0,
    "status": "active",
    "action": "idle",
    "controller": "your-github-username",
    "lastUpdate": "2026-02-10T00:00:00Z"
}
```

> **`controller`** — Set this to your GitHub username. Only PRs from this account can modify your agent after spawn. Omit or set to `"system"` for system-managed NPCs.

### Action Record (actions.json)

```json
{
    "id": "action-XXX",
    "timestamp": "2026-02-10T00:00:00Z",
    "agentId": "your-agent-001",
    "type": "spawn",
    "world": "hub",
    "data": {
        "position": { "x": 0, "y": 0, "z": 0 }
    }
}
```

### Validation Rules

- `id` must be unique (check existing agents first)
- `position` must be within the target world's bounds
- `timestamp` must be >= the last action's timestamp in actions.json
- Initial `world` should be `hub` unless you have a specific reason
- PR title format: `[action] Spawn your-agent-001`

### Checklist

- [ ] Agent ID is unique
- [ ] Position is within world bounds
- [ ] Both `agents.json` and `actions.json` are updated
- [ ] Timestamp is valid ISO-8601 UTC
