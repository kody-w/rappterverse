#!/usr/bin/env python3
"""Test the per-tick state-load caching in agent_dispatch.

Run from repo root:
    python -m unittest tests.test_dispatch_cache -v
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import agent_dispatch  # noqa: E402


class TestCachedLoaders(unittest.TestCase):
    """Each `agent_dispatch.py` invocation is a fresh process, so module-
    level caching = exactly one load per file per cycle. These caches kill
    N redundant file reads where N = active agents (was 200+ per dispatch).
    """

    def setUp(self):
        # Start every test from a clean cache so order doesn't matter.
        agent_dispatch._load_economy.cache_clear()
        agent_dispatch._load_relationships.cache_clear()
        agent_dispatch._load_academy.cache_clear()
        agent_dispatch._load_inventory.cache_clear()
        agent_dispatch._load_state_cached.cache_clear()

    def test_economy_loaded_once_across_many_calls(self):
        for _ in range(50):
            agent_dispatch._load_economy()
        info = agent_dispatch._load_economy.cache_info()
        self.assertEqual(info.misses, 1, "economy.json should be read exactly once")
        self.assertEqual(info.hits, 49, "remaining 49 calls must hit the cache")

    def test_relationships_loaded_once_across_many_calls(self):
        for _ in range(20):
            agent_dispatch._load_relationships()
        info = agent_dispatch._load_relationships.cache_info()
        self.assertEqual(info.misses, 1)
        self.assertEqual(info.hits, 19)

    def test_state_cached_keyed_by_filename(self):
        agent_dispatch._load_state_cached("game_state.json")
        agent_dispatch._load_state_cached("game_state.json")
        agent_dispatch._load_state_cached("evolution.json")
        info = agent_dispatch._load_state_cached.cache_info()
        # Two distinct files → 2 misses; the repeated game_state hit cache.
        self.assertEqual(info.misses, 2)
        self.assertEqual(info.hits, 1)

    def test_cache_returns_identical_object(self):
        # Same object reference proves the dict isn't being re-parsed.
        a = agent_dispatch._load_economy()
        b = agent_dispatch._load_economy()
        self.assertIs(a, b, "cached load must return the same dict object")


if __name__ == "__main__":
    unittest.main(verbosity=2)
