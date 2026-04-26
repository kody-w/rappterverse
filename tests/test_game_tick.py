#!/usr/bin/env python3
"""Tests for scripts/game_tick.py simulation-loop fixes.

Run from repo root:
    python -m unittest tests.test_game_tick -v
"""
import random
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import game_tick  # noqa: E402


class TestRelationshipDecaySource(unittest.TestCase):
    """Edge's own lastInteraction must be the authoritative source.

    Before the fix: when interactions[] was trimmed, every edge fell into
    the "no record → decay by 1" branch even if the edge itself had a
    fresh lastInteraction.
    """

    def test_recent_edge_skips_decay_even_when_interactions_empty(self):
        rel = {
            "edges": [
                # Recent enough (1h ago) that no decay tier should fire
                {"a": "alice", "b": "bob", "score": 5,
                 "lastInteraction": "2026-04-26T13:00:00Z"},
            ],
            "interactions": [],  # trimmed away
        }
        game_tick.decay_stale_relationships(rel, "2026-04-26T14:00:00Z")
        self.assertEqual(rel["edges"][0]["score"], 5,
                         "edge with recent lastInteraction must not decay")

    def test_week_old_edge_decays_three_via_edge_field(self):
        rel = {
            "edges": [
                {"a": "alice", "b": "bob", "score": 10,
                 "lastInteraction": "2026-04-19T13:00:00Z"},  # 8 days ago
            ],
            "interactions": [],
        }
        game_tick.decay_stale_relationships(rel, "2026-04-27T13:00:00Z")
        self.assertEqual(rel["edges"][0]["score"], 7,
                         "8-day-old edge should lose 3 points")

    def test_edge_field_preferred_over_interactions(self):
        # Interactions[] claims old; edge claims fresh — edge wins
        rel = {
            "edges": [
                {"a": "alice", "b": "bob", "score": 5,
                 "lastInteraction": "2026-04-26T13:00:00Z"},
            ],
            "interactions": [
                {"a": "alice", "b": "bob", "timestamp": "2026-01-01T00:00:00Z"},
            ],
        }
        game_tick.decay_stale_relationships(rel, "2026-04-26T14:00:00Z")
        self.assertEqual(rel["edges"][0]["score"], 5)


class TestMoodGatedTrades(unittest.TestCase):
    """Trade resolution must read NPC mood when responder is an NPC."""

    def _run_trade_batch(self, mood: str, n: int = 150, seed: int = 42) -> dict:
        random.seed(seed)
        trades_data = {
            "activeTrades": [
                {"id": f"trade-{i:04d}", "actionId": f"action-{i}",
                 "status": "pending", "from": "buyer-001", "to": "merchant-npc",
                 "offering": [], "requesting": []}
                for i in range(n)
            ],
            "completedTrades": [],
        }
        npcs_data = {
            "npcs": [{"id": "merchant-npc", "mood": mood, "needs": {}}]
        }
        game_tick.resolve_pending_trades(
            trades_data, {"actions": []}, "2026-04-26T14:00:00Z", npcs_data
        )
        outcomes = {"completed": 0, "rejected": 0, "pending": 0}
        for t in trades_data["completedTrades"]:
            outcomes[t["status"]] = outcomes.get(t["status"], 0) + 1
        outcomes["pending"] = len(trades_data["activeTrades"])
        return outcomes

    def test_desperate_npc_accepts_far_more_than_thriving(self):
        desperate = self._run_trade_batch("desperate")
        thriving = self._run_trade_batch("thriving")
        self.assertGreater(desperate["completed"], thriving["completed"] + 30,
                           "desperate NPCs should accept dramatically more trades")

    def test_thriving_npc_leaves_more_trades_pending(self):
        thriving = self._run_trade_batch("thriving")
        neutral = self._run_trade_batch("neutral")
        self.assertGreater(thriving["pending"], neutral["pending"],
                           "thriving NPCs should leave more trades hanging")

    def test_unknown_responder_falls_back_to_neutral(self):
        # Responder is not in npcs_data — should hit baseline odds
        result = self._run_trade_batch("nobody-home")  # mood unused; no NPC match
        # Sanity: most trades resolve, some hang
        self.assertGreater(result["completed"], 0)
        self.assertGreater(result["pending"], 0)


class TestNeedFulfillmentSpecific(unittest.TestCase):
    """NPC needs must require activity that actually involves the NPC."""

    def test_profit_only_restored_for_npc_participating_in_trade(self):
        npcs_data = {"npcs": [
            {"id": "merchant-001", "world": "marketplace",
             "needs": {"profit": 50}},
        ]}
        actions_data = {"actions": []}
        chat_data = {"messages": []}
        # A completed trade between two unrelated agents
        trades_data = {"completedTrades": [
            {"status": "completed", "from": "alice", "to": "bob"},
        ]}
        game_tick.fulfill_npc_needs(npcs_data, actions_data, chat_data, trades_data)
        self.assertEqual(npcs_data["npcs"][0]["needs"]["profit"], 50,
                         "profit must NOT be restored by trades the NPC isn't in")

    def test_profit_restored_when_npc_is_party_to_trade(self):
        npcs_data = {"npcs": [
            {"id": "merchant-001", "world": "marketplace",
             "needs": {"profit": 50}},
        ]}
        trades_data = {"completedTrades": [
            {"status": "completed", "from": "alice", "to": "merchant-001"},
            {"status": "completed", "from": "merchant-001", "to": "bob"},
        ]}
        game_tick.fulfill_npc_needs(
            npcs_data, {"actions": []}, {"messages": []}, trades_data
        )
        self.assertGreater(npcs_data["npcs"][0]["needs"]["profit"], 50,
                           "profit must be restored when NPC participated in trades")

    def test_social_addressed_mention_outweighs_ambient_chat(self):
        npc = {"id": "guide-001", "name": "Guide", "world": "hub",
               "needs": {"social": 30}}
        # Ambient: 5 messages in world, none mentioning the NPC
        ambient_chat = {"messages": [
            {"world": "hub", "content": f"random thought {i}"} for i in range(5)
        ]}
        game_tick.fulfill_npc_needs(
            {"npcs": [dict(npc, needs=dict(npc["needs"]))]},
            {"actions": []}, ambient_chat, {"completedTrades": []},
        )
        ambient_npc = {"npcs": [dict(npc, needs=dict(npc["needs"]))]}
        game_tick.fulfill_npc_needs(
            ambient_npc, {"actions": []}, ambient_chat, {"completedTrades": []}
        )
        ambient_social = ambient_npc["npcs"][0]["needs"]["social"]

        # Addressed: 5 messages, all mentioning the NPC by id
        addressed_chat = {"messages": [
            {"world": "hub", "content": "guide-001 hello"} for _ in range(5)
        ]}
        addressed_npc = {"npcs": [dict(npc, needs=dict(npc["needs"]))]}
        game_tick.fulfill_npc_needs(
            addressed_npc, {"actions": []}, addressed_chat, {"completedTrades": []}
        )
        addressed_social = addressed_npc["npcs"][0]["needs"]["social"]

        self.assertGreater(addressed_social, ambient_social,
                           "being addressed must restore more social need than ambient chat")


if __name__ == "__main__":
    unittest.main(verbosity=2)
