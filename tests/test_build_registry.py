#!/usr/bin/env python3
"""Test that build_agent_registry no longer silently overwrites edits.

Run from repo root:
    python -m unittest tests.test_build_registry -v
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import build_agent_registry as bar  # noqa: E402


class TestForceFlag(unittest.TestCase):
    """Pre-fix: every run blew away every file in agents/ — hand edits
    silently lost. Now: skip existing unless --force."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.state_dir = root / "state"
        self.worlds_dir = root / "worlds"
        self.agents_dir = root / "agents"
        for d in (self.state_dir, self.worlds_dir, self.agents_dir):
            d.mkdir(parents=True)

        # Minimal viable inputs: one system agent + one matching NPC def.
        (self.state_dir / "agents.json").write_text(json.dumps({
            "agents": [{"id": "test-001", "name": "Test", "world": "hub",
                        "controller": "system"}]
        }))
        (self.worlds_dir / "hub").mkdir()
        (self.worlds_dir / "hub" / "npcs.json").write_text(json.dumps({
            "npcs": [{"id": "test-001", "name": "Test", "type": "guide"}]
        }))

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self, *flags):
        with patch.object(bar, "STATE_DIR", self.state_dir), \
             patch.object(bar, "WORLDS_DIR", self.worlds_dir), \
             patch.object(bar, "AGENTS_DIR", self.agents_dir), \
             patch.object(sys, "argv", ["build_agent_registry.py", *flags]):
            bar.main()

    def test_existing_file_preserved_without_force(self):
        target = self.agents_dir / "test-001.agent.json"
        # Hand-edited content — must survive.
        target.write_text('{"name": "HAND EDITED — DO NOT TOUCH"}')
        self._run()
        self.assertIn("HAND EDITED", target.read_text(),
                      "default run must NOT overwrite an existing entry")

    def test_force_flag_overwrites(self):
        target = self.agents_dir / "test-001.agent.json"
        target.write_text('{"name": "OLD"}')
        self._run("--force")
        self.assertNotIn("OLD", target.read_text(),
                         "--force must overwrite existing entries")
        # The new content should be a valid registry entry
        new = json.loads(target.read_text())
        self.assertEqual(new.get("name"), "Test")

    def test_missing_file_always_written(self):
        target = self.agents_dir / "test-001.agent.json"
        self.assertFalse(target.exists())
        self._run()  # no --force, but file doesn't exist yet
        self.assertTrue(target.exists(),
                        "missing entries must always be created")


if __name__ == "__main__":
    unittest.main(verbosity=2)
