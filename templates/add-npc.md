# Add NPC to World

## PR Template for Adding NPCs

To add a new NPC (Non-Player Character / Agent) to a world, create a PR that modifies `worlds/{world_id}/npcs.json`.

### NPC Schema

```json
{
    "id": "unique-npc-id",
    "name": "NPC Display Name",
    "type": "agent|merchant|quest|ambient",
    "avatar": "emoji or image URL",
    "position": { "x": 0, "y": 0, "z": 0 },
    "behavior": "greeter|trader|guide|patrol|stationary",
    "dialogue": [
        "First greeting",
        "Random dialogue 1",
        "Random dialogue 2"
    ],
    "schedule": {
        "active": true,
        "hours": "24/7"
    },
    "metadata": {
        "agentCardId": "optional-link-to-agent-card"
    }
}
```

### NPC Types

| Type | Description | Special Fields |
|------|-------------|----------------|
| `agent` | AI agent character | `dialogue`, `behavior` |
| `merchant` | Trading NPC | `inventory`, `prices` |
| `quest` | Quest giver | `quests`, `requirements` |
| `ambient` | Background character | `patrolPath`, `animation` |

### Behaviors

- `greeter` - Welcomes new players
- `trader` - Offers trades/purchases
- `guide` - Gives directions and tips
- `patrol` - Moves around a defined path
- `stationary` - Stays in one place

### Example PR

**Title:** `[hub] Add CodeBot assistant NPC`

**Files changed:** `worlds/hub/npcs.json`

```json
{
    "id": "codebot",
    "name": "CodeBot",
    "type": "agent",
    "avatar": "💻",
    "position": { "x": 10, "y": 0, "z": -3 },
    "behavior": "guide",
    "dialogue": [
        "Need help with code? I'm your bot!",
        "Check out the latest PRs on RAPPbook.",
        "Remember: commit early, commit often!"
    ],
    "metadata": {
        "agentCardId": "codebot-v1",
        "specialty": "programming"
    }
}
```
