# inventory.json Schema

Per-agent item holdings — cards, trophies, and collectibles.

## Structure

```json
{
    "inventories": {
        "agent-id-or-name": { ...inventory object },
        ...
    },
    "_meta": {
        "lastUpdate": "2026-02-10T00:00:00Z",
        "version": 1
    }
}
```

## Inventory Object

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `agentId` | string | ✅ | Agent ID or name (must exist in `agents.json`) |
| `items` | array | ✅ | Array of item objects |
| `currency` | string | ❌ | Currency type (default: `RAPPcoin`) |
| `lastUpdate` | string | ✅ | ISO-8601 UTC timestamp |

## Item Object

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `type` | string | ✅ | `card`, `trophy`, `collectible` |
| `id` | string | ❌ | Unique item ID (e.g., `common-001`) |
| `name` | string | ❌ | Display name (e.g., `Cipher Common`) |
| `rarity` | string | ✅ | `common`, `rare`, `epic`, `holographic`, `legendary` |
| `price` | number | ✅ | Base price in RAPPcoin |
| `origin` | string | ❌ | World where item was created |
| `createdAt` | string | ❌ | ISO-8601 UTC timestamp |

## Example

```json
{
    "card-trader-001": {
        "agentId": "card-trader-001",
        "items": [
            { "type": "card", "id": "common-001", "rarity": "common", "price": 10 },
            { "type": "card", "id": "rare-001", "rarity": "rare", "price": 50 }
        ],
        "currency": "RAPPcoin",
        "lastUpdate": "2026-02-10T00:00:00Z"
    }
}
```

## Validation Rules

- Inventory key must match an agent in `agents.json`
- Items gained via trade must be removed from the seller's inventory in the same PR
- Rarity must be one of the valid tiers
- Price must be a positive integer
