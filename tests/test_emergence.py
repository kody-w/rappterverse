#!/usr/bin/env python3
"""Tests for scripts/emergence.py formula recalibration.

Run from repo root:
    python -m unittest tests.test_emergence -v
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import emergence  # noqa: E402


class TestEconomicAgency(unittest.TestCase):
    """Score must NOT clamp at 100 once activity passes ~20% agency.

    Pre-fix formula: min(100, ratio * 5) → 20% agent-driven = 100. The
    metric was permanently maxed in nearly every snapshot.
    """

    def _ledger(self, agent_driven: int, passive: int) -> dict:
        ledger = (
            [{"type": "tip"} for _ in range(agent_driven)]
            + [{"type": "income"} for _ in range(passive)]
        )
        return {"ledger": ledger}

    def test_20pct_agency_does_not_clamp_at_100(self):
        # 20 of 100 transactions are agent-driven (20% agency).
        score, _ = emergence.economic_agency_score(self._ledger(20, 80))
        self.assertLess(score, 50,
                        "20% agency should NOT yield a maxed score (was 100 pre-fix)")

    def test_higher_agency_strictly_increases_score(self):
        low, _ = emergence.economic_agency_score(self._ledger(10, 90))
        high, _ = emergence.economic_agency_score(self._ledger(60, 40))
        self.assertGreater(high, low,
                           "higher agency must produce a higher score")

    def test_full_agency_approaches_100(self):
        score, _ = emergence.economic_agency_score(self._ledger(100, 0))
        self.assertGreaterEqual(score, 90,
                                "100% agency should score near 100")

    def test_tipper_bonus_capped(self):
        # Many distinct tippers used to inflate score by +2 each, unbounded.
        ledger = [{"type": "tip"} for _ in range(100)]
        tips = [{"from": f"agent-{i:03d}", "to": "target"} for i in range(100)]
        economy = {"ledger": ledger, "tips": tips}
        score, _ = emergence.economic_agency_score(economy)
        self.assertLessEqual(score, 100, "score must not exceed 100")


class TestMigration(unittest.TestCase):
    """Score must scale beyond 7 travels (was clamped via len*15)."""

    def _travels(self, n: int, with_reason: bool = True) -> list:
        return [
            {"type": "travel", "data": {
                "from_world": "hub", "to_world": "arena",
                **({"reason": "visiting friend"} if with_reason else {})
            }}
            for _ in range(n)
        ]

    def test_seven_travels_no_longer_maxes_score(self):
        score, _ = emergence.migration_score(self._travels(7), [])
        self.assertLess(score, 90,
                        "7 travels should not produce a near-maxed score (was 100)")

    def test_score_keeps_growing_past_seven(self):
        seven, _ = emergence.migration_score(self._travels(7), [])
        thirty, _ = emergence.migration_score(self._travels(30), [])
        self.assertGreater(thirty, seven,
                           "30 travels should score higher than 7")

    def test_score_clamps_at_100_for_high_volume(self):
        score, _ = emergence.migration_score(self._travels(500), [])
        self.assertLessEqual(score, 100)


class TestSocialDepth(unittest.TestCase):
    """Score must not saturate at 50% strong bonds (was *200 multiplier)."""

    def _rels(self, scores: list[int]) -> dict:
        return {"edges": [{"a": f"a{i}", "b": f"b{i}", "score": s}
                          for i, s in enumerate(scores)]}

    def test_half_strong_no_longer_maxes(self):
        # 5 strong (≥30) + 5 weak. Pre-fix: 0.5 * 200 = 100 → clamped.
        rels = self._rels([35] * 5 + [3] * 5)
        score, _ = emergence.social_depth_score(rels)
        self.assertLess(score, 80,
                        "50% strong bonds should not yield a near-max score")

    def test_all_strong_can_reach_100(self):
        rels = self._rels([50] * 10)
        score, _ = emergence.social_depth_score(rels)
        self.assertGreaterEqual(score, 90,
                                "all-strong-bonds should score near 100")

    def test_all_weak_scores_low(self):
        rels = self._rels([2] * 50)
        score, _ = emergence.social_depth_score(rels)
        self.assertLess(score, 20,
                        "all-weak-bonds should not score above 20")


if __name__ == "__main__":
    unittest.main(verbosity=2)
