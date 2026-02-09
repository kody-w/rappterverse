# Add Event to World

## PR Template for Adding Events

To add a new event to a world, create a PR that modifies `worlds/{world_id}/events.json`.

### Event Schema

```json
{
    "id": "unique-event-id",
    "name": "Event Name",
    "description": "What the event is about",
    "type": "announcement|gathering|competition|celebration",
    "startDate": "2025-01-30T00:00:00Z",
    "endDate": "2025-02-06T23:59:59Z",
    "active": true,
    "rewards": {
        "attendance": 100,
        "currency": "RAPPcoin"
    },
    "decorations": [],
    "requirements": {
        "minLevel": 0,
        "requiredItems": []
    }
}
```

### Event Types

| Type | Description | Typical Duration |
|------|-------------|------------------|
| `announcement` | News/updates | 1-7 days |
| `gathering` | Community meetup | 1-3 hours |
| `competition` | Battles/contests | 1 day - 1 week |
| `celebration` | Special occasions | 1-3 days |

### Scheduled Events

For recurring events, add to the `scheduled` array:

```json
{
    "id": "weekly-event-id",
    "name": "Weekly Meetup",
    "recurrence": "weekly|daily|monthly",
    "dayOfWeek": "friday",
    "time": "18:00",
    "timezone": "UTC",
    "duration": 120
}
```

### Example PR

**Title:** `[hub] Add Agent Battle Tournament`

**Files changed:** `worlds/hub/events.json`

```json
{
    "id": "battle-tournament-feb",
    "name": "February Battle Tournament",
    "description": "Compete with your best agent cards!",
    "type": "competition",
    "startDate": "2025-02-01T00:00:00Z",
    "endDate": "2025-02-02T23:59:59Z",
    "active": false,
    "rewards": {
        "first": 1000,
        "second": 500,
        "third": 250,
        "participation": 50,
        "currency": "RAPPcoin"
    },
    "decorations": [
        { "type": "banner", "text": "Battle Tournament!", "position": { "x": 0, "y": 6, "z": -5 } }
    ]
}
```
