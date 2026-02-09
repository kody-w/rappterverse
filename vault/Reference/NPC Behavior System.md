# NPC Behavior System

NPCs have needs-driven behavior that makes the world feel alive.

## Needs (0–100 scale)

| Need | Applies To | Low Value Behavior |
|------|-----------|-------------------|
| `social` | All NPCs | Seeks visitors, more talkative |
| `purpose` | All NPCs | Offers more quests/tasks |
| `energy` | All NPCs | Moves slower, shorter dialogues |
| `profit` | Merchants | Offers discounts, aggressive selling |
| `inventory` | Merchants | Requests restocking, limited offers |
| `customers` | Merchants | Calls out to passersby |

## NPC Types

- **Guide** — Greets visitors, gives directions, tracks interactions in memory
- **Merchant** — Trades cards, adjusts prices based on needs, has inventory tiers (common/rare/epic/holographic)
- **Ambient** — Wanderer, announcer, curator — adds atmosphere

## Influencing NPCs via PR

Modify `state/npcs.json` to change:
- **Mood** — friendly, excited, anxious, desperate
- **Needs** — Adjust numeric values to trigger different behaviors
- **Tasks** — Assign specific tasks with priority and progress tracking
- **Memory** — Add interaction records (who they've met, what they've helped with)
- **Flags** — Toggle behaviors (desperate_mode, special_offer_active, etc.)

## Current NPCs

| ID | Name | World | Type |
|----|------|-------|------|
| rapp-guide-001 | RAPP Guide | hub | Guide |
| card-trader-001 | Card Trader | hub | Merchant |
| codebot-001 | CodeBot | hub | Tech |
| wanderer-001 | Wanderer | roaming | Explorer |
| news-anchor-001 | News Bot | hub | Reporter |
| battle-master-001 | Battle Master | arena | Fighter |
| merchant-001 | Pack Seller | marketplace | Merchant |
| gallery-curator-001 | Curator | gallery | Ambient |
| banker-001 | RAPPcoin Banker | marketplace | Finance |
| arena-announcer-001 | Announcer | arena | Ambient |

---

**Tags:** #reference #npcs #behavior
