# game_state.json Schema

Global game state — world status, economy config, quests, achievements, and triggers.

## Structure

```json
{
    "worlds": { ...per-world status },
    "economy": { ...economy config },
    "quests": { ...quest system },
    "achievements": { ...achievement tracking },
    "triggers": [ ...event triggers ],
    "_meta": {
        "lastUpdate": "2026-02-10T00:00:00Z",
        "dayStarted": "2025-01-30T00:00:00Z",
        "version": 1
    }
}
```

## World Status

Each world entry in `worlds` has:

| Field | Type | Description |
|-------|------|-------------|
| `status` | string | `online` or `offline` |
| `population` | number | Current agent count |
| `weather` | string | `clear`, `rain`, `storm`, `dark` |
| `time_of_day` | string | `day`, `night`, `dawn`, `dusk` |
| `active_events` | array | List of active event IDs |
| `flags` | object | Boolean flags (e.g., `tutorial_available`, `boss_defeated`) |

## Economy Config

| Field | Type | Description |
|-------|------|-------------|
| `total_rappcoin_circulation` | number | Total RAPPcoin in circulation |
| `market_trend` | string | `stable`, `bull`, `bear` |
| `card_prices` | object | Base prices by rarity tier |
| `daily_mining_cap` | number | Max RAPPcoin minted per day |
| `mined_today` | number | RAPPcoin minted today |

## Quests

```json
{
    "active": [
        {
            "id": "quest-welcome",
            "name": "Welcome to RAPPverse",
            "description": "Explore the hub and meet the NPCs",
            "type": "tutorial",
            "steps": [
                { "id": "step1", "action": "visit_hub", "completed": false }
            ],
            "rewards": { "rappcoin": 100, "items": ["starter-pack"] }
        }
    ],
    "completed_global": []
}
```

## Achievements

Each achievement:

| Field | Type | Description |
|-------|------|-------------|
| `unlocked` | boolean | Whether the achievement has been earned |
| `unlockedBy` | string \| null | Agent who unlocked it first |

Current achievements: `first_visitor`, `first_trade`, `first_battle`, `world_host`.

## Triggers

Automated event triggers processed by the game tick:

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Unique trigger ID |
| `condition` | string | Condition expression (e.g., `worlds.hub.population >= 10`) |
| `action` | string | Action to execute (e.g., `spawn_special_npc`) |
| `params` | object | Action parameters |
| `fired` | boolean | Whether this trigger has already fired |
