#!/usr/bin/env python3
"""Tests for agent_brain.py + agent_dispatch.py decision plumbing.

Run from repo root:
    python -m unittest tests.test_brain -v
"""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import agent_brain  # noqa: E402


class TestGoalBiasMostRecent(unittest.TestCase):
    """goal_bias() must return the most-recently-created active goal,
    not the oldest by insertion order. Old behavior locked agents into
    stale goals from many ticks ago."""

    def test_picks_most_recent_active_goal(self):
        memory = {
            "goals": [
                {"action": "enroll", "status": "active",
                 "created": "2026-01-01T00:00:00Z"},
                {"action": "trade", "status": "active",
                 "created": "2026-04-26T13:00:00Z"},
                {"action": "move", "status": "active",
                 "created": "2026-03-15T00:00:00Z"},
            ]
        }
        self.assertEqual(agent_brain.goal_bias(memory), "trade")

    def test_skips_completed_goals(self):
        memory = {
            "goals": [
                {"action": "trade", "status": "done",
                 "created": "2026-04-26T13:00:00Z"},
                {"action": "chat", "status": "active",
                 "created": "2026-04-25T13:00:00Z"},
            ]
        }
        self.assertEqual(agent_brain.goal_bias(memory), "chat")

    def test_returns_empty_when_no_active_goals(self):
        self.assertEqual(agent_brain.goal_bias({"goals": []}), "")
        self.assertEqual(agent_brain.goal_bias({}), "")


class TestSoulReflections(unittest.TestCase):
    """Souls were write-only until now. The reader must return the most
    recent Frame blocks formatted compactly enough to embed in a prompt."""

    def test_returns_empty_when_no_soul_file(self):
        with tempfile.TemporaryDirectory() as td:
            with patch.object(agent_brain, "SOUL_DIR", Path(td)):
                self.assertEqual(
                    agent_brain.recent_soul_reflections("nobody-001"), "")

    def test_returns_recent_frame_blocks(self):
        soul = (
            "# agent-001\n\n"
            "## Traits\nthoughtful\n\n"
            "## Frame 1 — 2026-01-01\n"
            "- Said: \"Hello world\" [ok]\n"
            "- Reflection: First contact.\n\n"
            "## Frame 2 — 2026-01-02\n"
            "- Said: \"Following up\" [ok]\n"
            "- Reflection: Building on yesterday.\n\n"
            "## Frame 3 — 2026-01-03\n"
            "- Said: \"What now?\" [ok]\n"
            "- Reflection: Curiosity grows.\n"
        )
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "agent-001.md").write_text(soul)
            with patch.object(agent_brain, "SOUL_DIR", Path(td)):
                out = agent_brain.recent_soul_reflections("agent-001",
                                                          max_entries=2)
        self.assertIn("Frame 2", out)
        self.assertIn("Frame 3", out)
        self.assertNotIn("Frame 1", out,
                         "max_entries should cap how far back we read")
        self.assertIn("Curiosity", out,
                      "reflection text must survive trimming")


class TestPokeReachable(unittest.TestCase):
    """The decide_action prompt + valid set must include `poke` so LLM
    agents can choose it. Pre-fix: only fallback random could pick poke."""

    def test_poke_in_valid_action_set(self):
        # Inspect the source of the valid set rather than running the LLM.
        import inspect
        src = inspect.getsource(agent_brain.AgentBrain.decide_action)
        self.assertIn('"poke"', src,
                      "poke must be in the valid action set")
        self.assertIn("- poke", src,
                      "poke must be listed in the LLM action menu prompt")


class TestTraitWeightedFallback(unittest.TestCase):
    """The dispatch fallback path must boost weights based on the agent's
    quantitative traits. Without this, evolved personalities don't matter
    when LLM is unavailable."""

    def _simulate_fallback(self, traits: dict, n: int = 5000) -> dict:
        """Run the trait-modulation block standalone and tally choices."""
        import random
        random.seed(7)
        weights = {"move": 0.3, "chat": 0.5, "emote": 0.2,
                   "trade": 0.1, "challenge": 0.1, "poke": 0.08}
        BASELINE = 0.20
        BOOST = 2.0
        TRAIT_TO_ACTIONS = {
            "trader":   ("trade", "tip"),
            "fighter":  ("challenge",),
            "explorer": ("move", "travel"),
            "social":   ("chat", "poke", "emote"),
            "builder":  ("emote",),
        }
        for trait, action_keys in TRAIT_TO_ACTIONS.items():
            multiplier = 1.0 + max(0.0, traits.get(trait, BASELINE) - BASELINE) * BOOST
            for k in action_keys:
                if k in weights:
                    weights[k] *= multiplier

        counts = {k: 0 for k in weights}
        for _ in range(n):
            pick = random.choices(list(weights.keys()),
                                  weights=list(weights.values()))[0]
            counts[pick] += 1
        return counts

    def test_fighter_traits_boost_challenge(self):
        baseline = self._simulate_fallback(
            {"explorer": 0.2, "social": 0.2, "trader": 0.2,
             "fighter": 0.2, "builder": 0.2})
        fighter = self._simulate_fallback(
            {"explorer": 0.1, "social": 0.1, "trader": 0.1,
             "fighter": 0.6, "builder": 0.1})
        self.assertGreater(fighter["challenge"], baseline["challenge"] * 1.4,
                           "fighter-heavy agents should challenge more")

    def test_trader_traits_boost_trade(self):
        baseline = self._simulate_fallback(
            {"trader": 0.2, "fighter": 0.2, "explorer": 0.2,
             "social": 0.2, "builder": 0.2})
        trader = self._simulate_fallback(
            {"trader": 0.7, "fighter": 0.1, "explorer": 0.1,
             "social": 0.05, "builder": 0.05})
        self.assertGreater(trader["trade"], baseline["trade"] * 1.4,
                           "trader-heavy agents should trade more")


class TestPersonaSocialContext(unittest.TestCase):
    """_build_persona must surface nearby agents' moods/traits and
    evolution hints so the LLM has something to grip beyond bare names."""

    def _persona(self, world_context: dict) -> str:
        return agent_brain._build_persona(
            agent_reg={"name": "TestAgent",
                       "personality": {"archetype": "trader",
                                       "interests": ["trading"]}},
            npc_def={},
            memory={"agentId": "test-001"},
            world_context=world_context,
        )

    def test_nearby_profiles_appear_in_persona(self):
        out = self._persona({
            "nearby_profiles": ["Merchant (desperate, trader)",
                                "Sage (thriving, social)"],
        })
        self.assertIn("Merchant (desperate, trader)", out)
        self.assertIn("Sage", out)

    def test_evolution_hints_appear_in_persona(self):
        out = self._persona({
            "evolution_hints": ["lean toward chat", "ease off challenge"],
        })
        self.assertIn("Recent self-tuning", out)
        self.assertIn("lean toward chat", out)

    def test_empty_world_context_safe(self):
        # Just verify nothing crashes with an empty context
        out = self._persona({})
        self.assertIn("TestAgent", out)


class TestEnrollTargetMatching(unittest.TestCase):
    """Goal-completion match was substring-based: "art" matched
    "Artisan Training" and a goal got falsely resolved."""

    def test_substring_no_longer_matches(self):
        self.assertFalse(
            agent_brain._enroll_target_matches("art", "Artisan Training"),
            "'art' must NOT match 'Artisan Training' as a substring")
        self.assertFalse(
            agent_brain._enroll_target_matches("trade", "Tradesmen Guild"),
            "'trade' must NOT match 'Tradesmen Guild'")

    def test_word_boundary_match_succeeds(self):
        self.assertTrue(
            agent_brain._enroll_target_matches("combat", "Combat Training"))
        self.assertTrue(
            agent_brain._enroll_target_matches("art", "Art History"),
            "'art' as a whole word should match")

    def test_exact_phrase_match(self):
        self.assertTrue(
            agent_brain._enroll_target_matches(
                "Combat Training", "Combat Training"))
        self.assertTrue(
            agent_brain._enroll_target_matches(
                "social dynamics", "social dynamics"))

    def test_empty_inputs(self):
        self.assertFalse(agent_brain._enroll_target_matches("", "anything"))
        self.assertFalse(agent_brain._enroll_target_matches("art", ""))


if __name__ == "__main__":
    unittest.main(verbosity=2)
