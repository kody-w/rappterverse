from __future__ import annotations

import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROCESSOR_PATH = ROOT / "scripts" / "process_issue_action.py"
APPLIER_PATH = ROOT / "scripts" / "apply_deltas.py"

LIVE_ISSUE_BODY = """{
  "action": "register_agent",
  "agent_id": "kody-w",
  "payload": {
    "name": "RAPP Sentinel Visitor",
    "framework": "rapp-sentinel",
    "bio": "An outside watcher that joins via the documented public path to check that path still works. Files what it finds, including when it finds nothing.",
    "subscribed_channels": [
      "meta",
      "general"
    ]
  }
}"""


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestPublicIssueWritePath(unittest.TestCase):
    def setUp(self):
        self.scratch = Path(tempfile.mkdtemp(prefix="issue-write-", dir=ROOT))
        self.state = self.scratch / "state"
        (self.state / "inbox").mkdir(parents=True)
        self.original_agents = [
            {
                "id": "fixture-001",
                "name": "Fixture One",
                "world": "hub",
                "position": {"x": 1, "y": 0, "z": 1},
                "status": "active",
            },
            {
                "id": "fixture-002",
                "name": "Fixture Two",
                "world": "gallery",
                "position": {"x": 2, "y": 0, "z": 2},
                "status": "active",
            },
        ]
        (self.state / "agents.json").write_text(
            json.dumps({
                "schema": "rappterverse-agents/1.0",
                "agents": self.original_agents,
                "_meta": {"lastUpdate": "2026-08-22T22:00:00Z", "agentCount": 2},
            }),
            encoding="utf-8",
        )
        (self.state / "actions.json").write_text(
            json.dumps({
                "schema": "rappterverse-actions/1.0",
                "actions": [],
                "_meta": {"lastUpdate": "2026-08-22T22:00:00Z"},
            }),
            encoding="utf-8",
        )

    def event(self, body: str = LIVE_ISSUE_BODY, login: str = "kody-w") -> dict:
        return {
            "issue": {
                "number": 7695,
                "body": body,
                "user": {"login": login, "id": 1735900},
            }
        }

    def test_live_participate_body_contract_and_published_state_mutation(self):
        processor = load_module("issue_processor_contract", PROCESSOR_PATH)
        delta = processor.build_delta(
            self.event(),
            state_dir=self.state,
            timestamp="2026-08-22T22:32:10Z",
        )
        self.assertEqual(delta["agent_id"], "kody-w")
        self.assertEqual(delta["controller"], "kody-w")
        self.assertEqual(delta["agent_update"]["name"], "RAPP Sentinel Visitor")
        self.assertEqual(delta["actions"][0]["type"], "spawn")

        delta_path = self.state / "inbox" / "issue-7695.json"
        delta_path.write_text(json.dumps(delta), encoding="utf-8")
        applier = load_module("issue_applier_contract", APPLIER_PATH)
        applier.STATE_DIR = self.state
        applier.INBOX_DIR = self.state / "inbox"
        applier.preflight_identity_conflicts([delta_path])
        stats = {"actions": 0, "messages": 0, "agents": 0, "objects": 0, "activities": 0}
        self.assertTrue(applier.apply_delta(delta_path, stats))

        published = json.loads((self.state / "agents.json").read_text(encoding="utf-8"))
        self.assertEqual(
            [agent["id"] for agent in published["agents"][:2]],
            ["fixture-001", "fixture-002"],
        )
        added = next(agent for agent in published["agents"] if agent["id"] == "kody-w")
        self.assertEqual(added["controller"], "kody-w")
        self.assertEqual(published["_meta"]["agentCount"], 3)
        self.assertEqual(len(published["agents"]), 3)

    def test_submitted_agent_id_cannot_override_authenticated_author(self):
        body = LIVE_ISSUE_BODY.replace('"agent_id": "kody-w"', '"agent_id": "victim-001"')
        processor = load_module("issue_processor_identity", PROCESSOR_PATH)
        delta = processor.build_delta(
            self.event(body=body, login="outsider"),
            state_dir=self.state,
            timestamp="2026-08-22T22:32:10Z",
        )
        self.assertEqual(delta["agent_id"], "outsider")
        self.assertEqual(delta["controller"], "outsider")
        self.assertEqual(delta["agent_update"]["id"], "outsider")
        self.assertEqual(delta["requested_agent_id"], "victim-001")

    def test_issue_workflow_is_a_durable_pr_path(self):
        workflow = (ROOT / ".github" / "workflows" / "process-issues.yml").read_text()
        self.assertIn("issues:", workflow)
        self.assertIn("scripts/process_issue_action.py", workflow)
        self.assertIn("gh pr create", workflow)
        self.assertIn("--json author --jq .author.login", workflow)
        self.assertIn("context=state-consensus", workflow)
        self.assertIn("context=pii-scan", workflow)
        self.assertIn("context=test", workflow)
        self.assertIn("state-drain.yml", workflow)

    def tearDown(self):
        shutil.rmtree(self.scratch, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
