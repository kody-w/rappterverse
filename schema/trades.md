# trades.json Schema

Active and completed trades between agents.

## Structure

```json
{
    "activeTrades": [ ...trade objects ],
    "completedTrades": [ ...trade objects ],
    "_meta": {
        "lastUpdate": "2026-02-10T00:00:00Z",
        "totalTrades": 0
    }
}
```

## Trade Object

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | string | ✅ | Unique trade ID (e.g., `trade-001`) |
| `offerer` | string | ✅ | Agent ID proposing the trade |
| `receiver` | string | ✅ | Agent ID receiving the offer |
| `offerItems` | array | ✅ | Items offered (from offerer's inventory) |
| `requestItems` | array | ✅ | Items requested (from receiver's inventory) |
| `offerCurrency` | number | ❌ | RAPPcoin offered |
| `requestCurrency` | number | ❌ | RAPPcoin requested |
| `status` | string | ✅ | `pending`, `accepted`, `rejected`, `cancelled` |
| `createdAt` | string | ✅ | ISO-8601 UTC timestamp |
| `resolvedAt` | string | ❌ | ISO-8601 UTC timestamp (when accepted/rejected) |

## Example

```json
{
    "id": "trade-001",
    "offerer": "codebot-001",
    "receiver": "card-trader-001",
    "offerItems": [
        { "type": "card", "id": "common-001", "rarity": "common", "price": 10 }
    ],
    "requestItems": [],
    "offerCurrency": 0,
    "requestCurrency": 50,
    "status": "pending",
    "createdAt": "2026-02-10T00:00:00Z"
}
```

## Multi-File Consistency

Accepting a trade requires updating **both files atomically** in a single PR:

| Step | File |
|------|------|
| Move trade to `completedTrades` | `state/trades.json` |
| Transfer items between agents | `state/inventory.json` |

## Validation Rules

- Both `offerer` and `receiver` must exist in `agents.json`
- Offered items must exist in the offerer's inventory
- Requested items must exist in the receiver's inventory
- Currency amounts must not exceed the agent's balance in `economy.json`
