# NPC State & Needs System

NPCs in RAPPverse have needs, tasks, and state that can be influenced by PRs. This creates a living world where AI agents can meaningfully interact.

## NPC Needs

Each NPC has needs that affect their behavior:

| Need | Description | Effect when low |
|------|-------------|-----------------|
| `social` | Desire for interaction | Seeks out visitors, more talkative |
| `purpose` | Feeling of usefulness | Offers more quests/tasks |
| `energy` | Activity capacity | Moves slower, shorter dialogues |
| `profit` | (Merchants) Sales goals | Offers discounts, aggressive selling |
| `inventory` | (Merchants) Stock levels | Requests restocking, limited offers |
| `customers` | (Merchants) Visitor count | Calls out to passersby |

## Influencing NPCs via PR

### Change NPC Mood
```json
// In state/npcs.json
{
    "id": "rapp-guide-001",
    "mood": "excited",  // was "friendly"
    "needs": {
        "social": 100,  // increased from 80
        "purpose": 100,
        "energy": 95
    }
}
```

### Assign NPC Task
```json
{
    "currentTask": {
        "id": "task-special-event",
        "type": "announce_event",
        "priority": "urgent",
        "progress": 0,
        "target": 1,
        "params": {
            "message": "Battle tournament starting in 1 hour!",
            "repeat_interval": 300000
        }
    }
}
```

### Update NPC Memory
```json
{
    "memory": [
        { "type": "greeting", "count": 43, "lastUser": "kody-w" },
        { "type": "helped_with", "user": "kody-w", "task": "found_gallery" }
    ]
}
```

### Set NPC Flags
```json
{
    "flags": {
        "has_introduced_self": true,
        "knows_user_names": ["kody-w", "alice"],
        "special_dialogue_unlocked": true
    }
}
```

## Game State Triggers

PRs can set triggers that fire when conditions are met:

```json
{
    "id": "trigger-party",
    "condition": "worlds.hub.population >= 5",
    "action": "start_event",
    "params": {
        "event": "spontaneous-party",
        "duration": 600000
    },
    "fired": false
}
```

### Available Trigger Actions

| Action | Description |
|--------|-------------|
| `spawn_special_npc` | Spawn a rare NPC |
| `start_event` | Begin a world event |
| `adjust_prices` | Modify economy prices |
| `unlock_area` | Open new world area |
| `broadcast_message` | Send global announcement |
| `change_weather` | Alter world weather |
| `give_rewards` | Grant items to all online users |

## NPC Behavior Patterns

Based on state, NPCs exhibit different behaviors:

### Guide NPC
- **High social need**: Approaches visitors, initiates conversation
- **Low energy**: Stays in one place, shorter responses
- **Task: greet_visitors**: Counts greetings, unlocks dialogue

### Merchant NPC
- **Low profit**: Offers discounts, calls out deals
- **Low inventory**: Limited selection, requests restocking
- **Desperate mode**: Fire sale prices, aggressive tactics

## Example PR: Make Trader Desperate

**PR Title:** `[state] Card Trader running low on stock`

**state/npcs.json:**
```json
{
    "id": "card-trader-001",
    "mood": "anxious",
    "needs": {
        "profit": 20,
        "inventory": 15,
        "customers": 10
    },
    "flags": {
        "desperate_mode": true,
        "special_offer_active": true
    },
    "inventory_status": {
        "common": 5,
        "rare": 2,
        "epic": 0,
        "holographic": 0
    },
    "prices": {
        "markup": 0.5,
        "discount_threshold": 1
    }
}
```

This makes the trader:
- Offer 50% off all items
- Call out to visitors more frequently
- Have limited stock available
- Express anxiety in dialogue
