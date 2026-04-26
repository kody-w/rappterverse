#!/usr/bin/env python3
"""Test that brainstem logs every frame to soul, not just successful actions.

Pre-fix: only `if action: append_soul_entry(...)` — no_llm / error / empty
/ no_action frames vanished from the soul. Souls described a partial life.

Run from repo root:
    python -m unittest tests.test_brainstem_soul -v
"""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import brainstem  # noqa: E402


class TestIdleSoulLogging(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.soul_dir = Path(self.tmp.name)
        self._patch = patch.object(brainstem, "SOUL_DIR", self.soul_dir)
        self._patch.start()

    def tearDown(self):
        self._patch.stop()
        self.tmp.cleanup()

    def _read_soul(self, agent_id: str) -> str:
        path = self.soul_dir / f"{agent_id}.md"
        return path.read_text() if path.exists() else ""

    def test_no_llm_path_still_logs_frame(self):
        # Force HAS_LLM False so the function takes the no_llm branch.
        with patch.object(brainstem, "HAS_LLM", False):
            result = brainstem.run_agent_brainstem(
                agent_id="silent-001",
                agent_reg={"name": "Silent", "personality": {"archetype": "guide"}},
                frame=42,
                world="hub",
                nearby_agents=[],
                recent_chat=[],
                relationships=[],
            )
        self.assertEqual(result["status"], "no_llm")
        soul = self._read_soul("silent-001")
        self.assertIn("Frame 42", soul,
                      "no_llm frame must still appear in soul (was dropped pre-fix)")
        self.assertIn("[no_llm]", soul,
                      "soul entry must record the actual status, not 'ok'")

    def test_llm_error_path_logs_frame_with_error_status(self):
        # HAS_LLM True but generate() raises.
        def boom(**_kwargs):
            raise RuntimeError("api outage")

        with patch.object(brainstem, "HAS_LLM", True), \
             patch.object(brainstem, "generate", boom):
            result = brainstem.run_agent_brainstem(
                agent_id="ghosted-001",
                agent_reg={"name": "Ghosted", "personality": {"archetype": "guide"}},
                frame=7,
                world="hub", nearby_agents=[], recent_chat=[], relationships=[],
            )
        self.assertEqual(result["status"], "error")
        soul = self._read_soul("ghosted-001")
        self.assertIn("Frame 7", soul)
        self.assertIn("[error]", soul)
        self.assertIn("api outage", soul,
                      "error narrative must surface for debugging")

    def test_successful_action_still_logged_normally(self):
        # Sanity: the regression test for the original happy path.
        def good_llm(**_kwargs):
            return '{"tool": "chat", "args": {"message": "hello world"}, "reflection": "feeling chatty"}'

        with patch.object(brainstem, "HAS_LLM", True), \
             patch.object(brainstem, "generate", good_llm), \
             patch.object(brainstem, "get_toolbelt",
                          lambda *_: ["chat", "move"]):
            result = brainstem.run_agent_brainstem(
                agent_id="happy-001",
                agent_reg={"name": "Happy", "personality": {"archetype": "guide"}},
                frame=1,
                world="hub", nearby_agents=[], recent_chat=[], relationships=[],
            )
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["action"]["tool"], "chat")
        soul = self._read_soul("happy-001")
        self.assertIn("Frame 1", soul)
        self.assertIn("Said:", soul)
        self.assertIn("feeling chatty", soul,
                      "reflection must survive in the soul")


if __name__ == "__main__":
    unittest.main(verbosity=2)
