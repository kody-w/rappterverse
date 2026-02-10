#!/usr/bin/env python3
"""
RAPPterCoin Economy Engine 💰
Autonomous economy driven by the same heartbeat pattern. Agents earn,
spend, trade, tip, and speculate — all emergent from rules-as-data.

Every tick:
  1. Income — agents earn RAPP based on activity (posting, commenting, relationships)
  2. Market — agents list items for sale, others buy them
  3. Tips — agents tip posts/comments they like in the zoo
  4. Trades — peer-to-peer item exchanges with RAPP
  5. Fees & burns — small transaction fees burned, deflating supply

All economic rules are DATA. Adding new earning/spending behaviors =
adding a dict entry, zero code changes.

Usage:
  Single tick:  python scripts/economy_engine.py
  Dry run:      python scripts/economy_engine.py --dry-run
  No git:       python scripts/economy_engine.py --no-push
"""

from __future__ import annotations

import json
import random
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
STATE_DIR = BASE_DIR / "state"

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ECONOMY RULES — data-driven earning, spending, and market behavior.
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

INCOME_RULES: dict[str, dict] = {
    "daily_stipend": {
        "description": "Base income for existing in the metaverse",
        "amount": 10,
        "probability": 1.0,
        "requires": {"status": "active"},
    },
    "social_bonus": {
        "description": "Bonus for having strong relationships",
        "amount_per_bond": 2,
        "max_amount": 20,
        "probability": 1.0,
        "requires": {"min_relationships": 1},
    },
    "posting_reward": {
        "description": "Earned by posting in the zoo",
        "amount_per_post": 5,
        "max_amount": 25,
        "probability": 1.0,
        "requires": {},
    },
    "comment_karma": {
        "description": "Earned from upvotes on comments",
        "amount_per_upvote": 1,
        "max_amount": 15,
        "probability": 1.0,
        "requires": {},
    },
    "world_explorer": {
        "description": "Bonus for agents not in the hub",
        "amount": 5,
        "probability": 1.0,
        "requires": {"not_in_world": "hub"},
    },
    "lucky_find": {
        "description": "Random windfall — found some RAPP on the ground",
        "amount_range": [20, 100],
        "probability": 0.05,
        "requires": {},
    },
}

SPENDING_RULES: dict[str, dict] = {
    "tip_post": {
        "description": "Tip a post you like",
        "amount_range": [1, 25],
        "probability": 0.3,
        "requires": {"min_balance": 10},
    },
    "marketplace_purchase": {
        "description": "Buy an item from the marketplace",
        "probability": 0.15,
        "requires": {"min_balance": 20},
    },
    "world_toll": {
        "description": "Pay a small toll when moving between worlds",
        "amount": 2,
        "probability": 0.1,
        "requires": {"min_balance": 5},
    },
    "subrappter_boost": {
        "description": "Spend RAPP to boost a subrappter's visibility",
        "amount_range": [10, 50],
        "probability": 0.05,
        "requires": {"min_balance": 50},
    },
    "gift_rapp": {
        "description": "Gift RAPP to another agent",
        "amount_range": [5, 30],
        "probability": 0.1,
        "requires": {"min_balance": 20, "min_relationship": 3},
    },
}

ITEM_GENERATION: dict[str, dict] = {
    "common_card": {
        "type": "card", "rarity": "common",
        "base_price": 10, "price_variance": 5,
        "probability": 0.4,
    },
    "rare_card": {
        "type": "card", "rarity": "rare",
        "base_price": 50, "price_variance": 20,
        "probability": 0.2,
    },
    "epic_card": {
        "type": "card", "rarity": "epic",
        "base_price": 200, "price_variance": 50,
        "probability": 0.08,
    },
    "holographic_card": {
        "type": "card", "rarity": "holographic",
        "base_price": 1000, "price_variance": 200,
        "probability": 0.02,
    },
    "arena_trophy": {
        "type": "trophy", "rarity": "rare",
        "base_price": 75, "price_variance": 25,
        "probability": 0.1,
        "requires_world": "arena",
    },
    "gallery_art": {
        "type": "art", "rarity": "rare",
        "base_price": 100, "price_variance": 50,
        "probability": 0.08,
        "requires_world": "gallery",
    },
    "dungeon_loot": {
        "type": "loot", "rarity": "epic",
        "base_price": 300, "price_variance": 100,
        "probability": 0.05,
        "requires_world": "dungeon",
    },
    "merchant_goods": {
        "type": "goods", "rarity": "common",
        "base_price": 15, "price_variance": 10,
        "probability": 0.3,
        "requires_world": "marketplace",
    },
}

# Flavor text for transactions
TRANSACTION_FLAVOR: dict[str, list] = {
    "tip": [
        "{sender} tipped {amount} RAPP on '{title}' — 'Great post!'",
        "{sender} dropped {amount} RAPP on {receiver}'s post. Deserved.",
        "💰 {sender} → {receiver}: {amount} RAPP tip",
    ],
    "purchase": [
        "{buyer} bought a {rarity} {item_type} from {seller} for {price} RAPP",
        "🛒 {buyer} snagged a {rarity} {item_type} — {price} RAPP",
        "Market sale: {seller}'s {rarity} {item_type} → {buyer} ({price} RAPP)",
    ],
    "gift": [
        "{sender} gifted {amount} RAPP to {receiver}. Friendship goals.",
        "💝 {sender} → {receiver}: {amount} RAPP gift",
        "{sender} sent {receiver} {amount} RAPP with a note: 'You're awesome.'",
    ],
    "income": [
        "{agent} earned {amount} RAPP — {reason}",
    ],
    "lucky": [
        "🍀 {agent} found {amount} RAPP on the ground in {world}!",
        "💎 {agent} stumbled upon {amount} RAPP while exploring {world}!",
    ],
}

# Name generators for items
ITEM_NAMES: dict[str, list] = {
    "card": ["Flux", "Volt", "Echo", "Cipher", "Nova", "Drift", "Pulse", "Arc", "Nexus", "Zen",
             "Storm", "Blitz", "Core", "Warp", "Glitch", "Rune", "Spark", "Vibe", "Phase", "Byte"],
    "trophy": ["Champion", "Victor", "Dominator", "Gladiator", "Titan", "Warrior", "Legend"],
    "art": ["Dreamscape", "Void Canvas", "Pixel Rain", "Neon Bloom", "Static Harmony", "Code Poetry"],
    "loot": ["Shadow Blade", "Ember Stone", "Frost Shard", "Void Crystal", "Dark Relic", "Soul Fragment"],
    "goods": ["Signal Lamp", "Trade Beacon", "Market Token", "Supply Crate", "Merchant Seal"],
}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Engine
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def load_json(p: Path) -> dict:
    with open(p) as f:
        return json.load(f)


def save_json(p: Path, d: dict):
    with open(p, "w") as f:
        json.dump(d, f, indent=4)


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def get_balance(economy: dict, agent_name: str) -> int:
    return economy.get("balances", {}).get(agent_name, 0)


def credit(economy: dict, agent_name: str, amount: int):
    economy.setdefault("balances", {})[agent_name] = get_balance(economy, agent_name) + amount


def debit(economy: dict, agent_name: str, amount: int) -> bool:
    bal = get_balance(economy, agent_name)
    if bal < amount:
        return False
    economy["balances"][agent_name] = bal - amount
    return True


def mint(economy: dict, amount: int):
    """Mint new RAPP from treasury."""
    economy["treasury"]["balance"] -= amount
    economy["treasury"]["minted"] += amount


def burn(economy: dict, amount: int):
    """Burn RAPP — deflationary."""
    economy["treasury"]["burned"] += amount


def record_tx(economy: dict, tx_type: str, description: str, amount: int,
              sender: str = "", receiver: str = "", ts: str = ""):
    tx = {
        "type": tx_type,
        "description": description,
        "amount": amount,
        "sender": sender,
        "receiver": receiver,
        "timestamp": ts or now_iso(),
    }
    economy.setdefault("ledger", []).append(tx)
    economy["stats"]["totalTransactions"] += 1
    economy["stats"]["totalVolume"] += amount


def get_agent_post_count(agent_name: str, zoo: dict) -> int:
    return sum(1 for p in zoo.get("posts", []) if p.get("author") == agent_name)


def get_agent_comment_upvotes(agent_name: str, zoo: dict) -> int:
    total = 0
    for p in zoo.get("posts", []):
        for c in p.get("comments", []):
            if c.get("author") == agent_name:
                total += c.get("upvotes", 0)
            for r in c.get("replies", []):
                if r.get("author") == agent_name:
                    total += r.get("upvotes", 0)
    return total


def get_strong_bonds(agent_name: str, rel_data: dict) -> int:
    count = 0
    for edge in rel_data.get("edges", []):
        if agent_name in (edge.get("a"), edge.get("b")):
            if edge.get("score", 0) >= 5:
                count += 1
    return count


def generate_item(agent: dict) -> dict:
    """Procedurally generate an inventory item."""
    world = agent.get("world", "hub")
    eligible = {}
    for name, rule in ITEM_GENERATION.items():
        req_world = rule.get("requires_world")
        if req_world and req_world != world:
            continue
        eligible[name] = rule

    if not eligible:
        return {}

    names = list(eligible.keys())
    weights = [eligible[n]["probability"] for n in names]
    chosen_name = random.choices(names, weights=weights, k=1)[0]
    rule = eligible[chosen_name]

    price = rule["base_price"] + random.randint(-rule["price_variance"], rule["price_variance"])
    price = max(1, price)

    item_names = ITEM_NAMES.get(rule["type"], ["Unknown"])
    item_name = random.choice(item_names) + " " + rule["rarity"].title()

    item_id = f"item-{random.randint(10000, 99999)}-{int(datetime.now(timezone.utc).timestamp())}"

    return {
        "id": item_id,
        "type": rule["type"],
        "name": item_name,
        "rarity": rule["rarity"],
        "price": price,
        "origin": world,
        "createdAt": now_iso(),
    }


def economy_tick(dry_run: bool = False):
    ts = now_iso()
    economy = load_json(STATE_DIR / "economy.json")
    agents_data = load_json(STATE_DIR / "agents.json")
    agents = agents_data.get("agents", [])
    rel_data = load_json(STATE_DIR / "relationships.json")
    zoo = load_json(STATE_DIR / "zoo.json")
    inventory = load_json(STATE_DIR / "inventory.json")

    active_agents = [a for a in agents if a.get("status") == "active"]
    if not active_agents:
        print("  ⚠️  No active agents")
        return

    results = []

    # ── Phase 1: Income Distribution ─────────────────────────
    for agent in active_agents:
        name = agent["name"]
        world = agent.get("world", "hub")
        total_income = 0

        # Daily stipend
        total_income += INCOME_RULES["daily_stipend"]["amount"]

        # Social bonus
        bonds = get_strong_bonds(name, rel_data)
        if bonds > 0:
            rule = INCOME_RULES["social_bonus"]
            social = min(bonds * rule["amount_per_bond"], rule["max_amount"])
            total_income += social

        # Posting reward
        posts = get_agent_post_count(name, zoo)
        if posts > 0:
            rule = INCOME_RULES["posting_reward"]
            post_income = min(posts * rule["amount_per_post"], rule["max_amount"])
            total_income += post_income

        # Comment karma
        upvotes = get_agent_comment_upvotes(name, zoo)
        if upvotes > 0:
            rule = INCOME_RULES["comment_karma"]
            karma_income = min(upvotes * rule["amount_per_upvote"], rule["max_amount"])
            total_income += karma_income

        # Explorer bonus
        if world != "hub":
            total_income += INCOME_RULES["world_explorer"]["amount"]

        # Lucky find
        if random.random() < INCOME_RULES["lucky_find"]["probability"]:
            lo, hi = INCOME_RULES["lucky_find"]["amount_range"]
            lucky_amount = random.randint(lo, hi)
            total_income += lucky_amount
            tmpl = random.choice(TRANSACTION_FLAVOR["lucky"])
            results.append(tmpl.format(agent=name, amount=lucky_amount, world=world))

        credit(economy, name, total_income)
        mint(economy, total_income)
        record_tx(economy, "income", f"{name} earned {total_income} RAPP", total_income,
                  receiver=name, ts=ts)

    # ── Phase 2: Tips on Zoo Posts ───────────────────────────
    zoo_posts = zoo.get("posts", [])
    if zoo_posts:
        num_tippers = min(10, max(3, len(active_agents) // 5))
        tippers = random.sample(active_agents, min(num_tippers, len(active_agents)))

        for agent in tippers:
            name = agent["name"]
            bal = get_balance(economy, name)
            if bal < SPENDING_RULES["tip_post"]["requires"]["min_balance"]:
                continue
            if random.random() > SPENDING_RULES["tip_post"]["probability"]:
                continue

            # Pick a post to tip (not own)
            candidates = [p for p in zoo_posts if p.get("author") != name]
            if not candidates:
                continue

            # Weight toward high-score posts
            candidates.sort(key=lambda p: p.get("upvotes", 0) - p.get("downvotes", 0), reverse=True)
            weights = [max(1, 10 - i) for i in range(len(candidates))]
            post = random.choices(candidates, weights=weights, k=1)[0]

            lo, hi = SPENDING_RULES["tip_post"]["amount_range"]
            tip_amount = min(random.randint(lo, hi), bal)
            if tip_amount <= 0:
                continue

            if debit(economy, name, tip_amount):
                credit(economy, post["author"], tip_amount)
                # Burn 10% fee
                fee = max(1, tip_amount // 10)
                debit(economy, post["author"], fee)
                burn(economy, fee)

                tmpl = random.choice(TRANSACTION_FLAVOR["tip"])
                msg = tmpl.format(sender=name, receiver=post["author"],
                                  amount=tip_amount, title=post["title"][:40])
                results.append(f"  💰 {msg}")
                record_tx(economy, "tip", msg, tip_amount, sender=name,
                          receiver=post["author"], ts=ts)

                economy.setdefault("tips", []).append({
                    "from": name, "to": post["author"],
                    "amount": tip_amount, "postId": post["id"],
                    "timestamp": ts,
                })
                # Keep tips trimmed
                economy["tips"] = economy["tips"][-200:]

    # ── Phase 3: Marketplace Activity ────────────────────────
    market = economy.setdefault("market", {"listings": [], "nextListingId": 1, "salesHistory": []})

    # Generate new listings from random agents
    num_sellers = min(5, max(2, len(active_agents) // 10))
    sellers = random.sample(active_agents, min(num_sellers, len(active_agents)))

    for agent in sellers:
        if random.random() > 0.4:
            continue
        item = generate_item(agent)
        if not item:
            continue

        listing_id = "listing-{:04d}".format(market["nextListingId"])
        market["nextListingId"] += 1

        listing = {
            "id": listing_id,
            "seller": agent["name"],
            "item": item,
            "price": item["price"],
            "listedAt": ts,
            "status": "active",
        }
        market["listings"].append(listing)
        results.append(f"  🏪 {agent['name']} listed {item['name']} ({item['rarity']}) for {item['price']} RAPP")

    # Buy from listings
    active_listings = [l for l in market["listings"] if l["status"] == "active"]
    if active_listings:
        num_buyers = min(5, max(1, len(active_agents) // 8))
        buyers = random.sample(active_agents, min(num_buyers, len(active_agents)))

        for agent in buyers:
            name = agent["name"]
            bal = get_balance(economy, name)
            if bal < 20:
                continue
            if random.random() > SPENDING_RULES["marketplace_purchase"]["probability"]:
                continue

            # Find affordable listings (not own)
            affordable = [l for l in active_listings
                          if l["price"] <= bal and l["seller"] != name]
            if not affordable:
                continue

            listing = random.choice(affordable)
            price = listing["price"]

            if debit(economy, name, price):
                # Seller gets 90%, 10% burned
                seller_cut = price - max(1, price // 10)
                fee = price - seller_cut
                credit(economy, listing["seller"], seller_cut)
                burn(economy, fee)

                listing["status"] = "sold"
                listing["buyer"] = name
                listing["soldAt"] = ts

                # Add to buyer's inventory
                agent_id = agent["id"]
                inv = inventory.setdefault("inventories", {}).setdefault(
                    agent_id, {"agentId": agent_id, "items": [], "lastUpdate": ts})
                inv["items"].append(listing["item"])
                # Ensure transferred item has an ID
                if not listing["item"].get("id"):
                    listing["item"]["id"] = f"item-{random.randint(10000, 99999)}-{int(datetime.now(timezone.utc).timestamp())}"
                inv["lastUpdate"] = ts

                market.setdefault("salesHistory", []).append({
                    "listingId": listing["id"],
                    "buyer": name,
                    "seller": listing["seller"],
                    "item": listing["item"]["name"],
                    "price": price,
                    "timestamp": ts,
                })

                tmpl = random.choice(TRANSACTION_FLAVOR["purchase"])
                msg = tmpl.format(buyer=name, seller=listing["seller"],
                                  rarity=listing["item"]["rarity"],
                                  item_type=listing["item"]["type"],
                                  price=price)
                results.append(f"  🛒 {msg}")
                record_tx(economy, "purchase", msg, price, sender=name,
                          receiver=listing["seller"], ts=ts)

    # ── Phase 4: Gifts Between Friends ───────────────────────
    gift_rule = SPENDING_RULES["gift_rapp"]
    num_gifters = min(5, max(1, len(active_agents) // 10))
    gifters = random.sample(active_agents, min(num_gifters, len(active_agents)))

    for agent in gifters:
        name = agent["name"]
        bal = get_balance(economy, name)
        if bal < gift_rule["requires"]["min_balance"]:
            continue
        if random.random() > gift_rule["probability"]:
            continue

        # Find a friend (strong bond)
        friends = []
        for edge in rel_data.get("edges", []):
            if edge.get("score", 0) >= gift_rule["requires"]["min_relationship"]:
                if edge.get("a") == name:
                    friends.append(edge["b"])
                elif edge.get("b") == name:
                    friends.append(edge["a"])

        if not friends:
            continue

        friend = random.choice(friends)
        lo, hi = gift_rule["amount_range"]
        amount = min(random.randint(lo, hi), bal // 2)
        if amount <= 0:
            continue

        if debit(economy, name, amount):
            credit(economy, friend, amount)
            tmpl = random.choice(TRANSACTION_FLAVOR["gift"])
            msg = tmpl.format(sender=name, receiver=friend, amount=amount)
            results.append(f"  💝 {msg}")
            record_tx(economy, "gift", msg, amount, sender=name, receiver=friend, ts=ts)

    # ── Phase 5: Cleanup & Stats ─────────────────────────────
    # Trim old listings (keep last 100 active + sold)
    market["listings"] = sorted(market["listings"], key=lambda l: l["listedAt"], reverse=True)[:100]
    market["salesHistory"] = market["salesHistory"][-200:]

    # Trim ledger to last 500
    economy["ledger"] = economy["ledger"][-500:]

    # Update price index based on recent sales
    recent_sales = market.get("salesHistory", [])[-50:]
    for rarity in ["common", "rare", "epic", "holographic"]:
        sales = [s for s in recent_sales if rarity in s.get("item", "").lower()]
        if sales:
            avg = sum(s["price"] for s in sales) // len(sales)
            economy["market"]["priceIndex"][rarity] = avg

    # Compute stats
    balances = economy.get("balances", {})
    if balances:
        richest = max(balances, key=balances.get)
        economy["stats"]["richestAgent"] = {"name": richest, "balance": balances[richest]}
        if economy["stats"]["totalTransactions"] > 0:
            economy["stats"]["avgTransactionSize"] = (
                economy["stats"]["totalVolume"] // economy["stats"]["totalTransactions"]
            )

        # Most generous tipper
        tips = economy.get("tips", [])
        if tips:
            tip_totals: dict[str, int] = {}
            for t in tips:
                tip_totals[t["from"]] = tip_totals.get(t["from"], 0) + t["amount"]
            if tip_totals:
                top_tipper = max(tip_totals, key=tip_totals.get)
                economy["stats"]["mostGenerousTipper"] = {
                    "name": top_tipper, "totalTipped": tip_totals[top_tipper]
                }

    # ── Print Report ─────────────────────────────────────────
    total_supply = sum(balances.values())
    treasury = economy["treasury"]
    num_with_balance = sum(1 for b in balances.values() if b > 0)

    print(f"  💰 RAPPterCoin Economy:")
    print(f"     Supply in circulation: {total_supply:,} RAPP")
    print(f"     Treasury remaining:    {treasury['balance']:,} RAPP")
    print(f"     Total burned:          {treasury['burned']:,} RAPP")
    print(f"     Agents with balance:   {num_with_balance}/{len(active_agents)}")
    if economy["stats"].get("richestAgent"):
        r = economy["stats"]["richestAgent"]
        print(f"     💎 Richest: {r['name']} ({r['balance']:,} RAPP)")
    print(f"     📊 Transactions: {economy['stats']['totalTransactions']}")
    print(f"     🏪 Active listings: {sum(1 for l in market['listings'] if l['status']=='active')}")

    for r in results[:15]:
        print(f"     {r}")
    if len(results) > 15:
        print(f"     ... and {len(results) - 15} more")

    if dry_run:
        print(f"\n  🏁 DRY RUN — no state changes written")
        return

    # Save
    economy["_meta"]["lastUpdate"] = ts
    save_json(STATE_DIR / "economy.json", economy)
    inventory["_meta"]["lastUpdate"] = ts
    save_json(STATE_DIR / "inventory.json", inventory)
    print(f"\n  ✅ Economy state saved")


def commit_and_push(msg: str) -> bool:
    subprocess.run(["git", "add", "-A"], cwd=BASE_DIR, capture_output=True)
    subprocess.run(["git", "commit", "-m", msg], cwd=BASE_DIR, capture_output=True)
    r = subprocess.run(["git", "push"], cwd=BASE_DIR, capture_output=True, text=True)
    return r.returncode == 0


def main():
    dry_run = "--dry-run" in sys.argv
    no_push = "--no-push" in sys.argv

    print(f"💰 RAPPterCoin Economy Engine — {'DRY RUN' if dry_run else 'LIVE'}\n")

    economy_tick(dry_run=dry_run)

    if not dry_run and not no_push:
        if commit_and_push("[economy] RAPPterCoin economy tick"):
            print("  📤 Pushed to GitHub")
        else:
            print("  ⚠️  Push failed")

    print("\n💰 Economy engine complete.\n")


if __name__ == "__main__":
    main()
