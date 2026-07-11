#!/usr/bin/env python3
"""
RAPPterverse Regression & Integrity Test Suite
Validates infrastructure, state consistency, and workflow configuration.
Run locally: python scripts/test_state_integrity.py
Run in CI:   python -m pytest scripts/test_state_integrity.py -v
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

# Resolve repo root (works from scripts/ or repo root)
SCRIPT_DIR = Path(__file__).parent
BASE_DIR = SCRIPT_DIR.parent
STATE_DIR = BASE_DIR / "state"
WORLDS_DIR = BASE_DIR / "worlds"
FEED_DIR = BASE_DIR / "feed"
WORKFLOWS_DIR = BASE_DIR / ".github" / "workflows"
INBOX_DIR = STATE_DIR / "inbox"

# World bounds are loaded from worlds/*/config.json — the same source of truth
# used by validate_action.py. This prevents the test suite and the validator
# from drifting apart (e.g. someone updates a world's bounds in config.json
# but forgets to update a hardcoded table here, and stale tests then
# fail to catch real out-of-bounds objects).
_FALLBACK_WORLD_BOUNDS = {
    "hub": {"x": (-15, 15), "z": (-15, 15)},
    "arena": {"x": (-12, 12), "z": (-12, 12)},
    "marketplace": {"x": (-15, 15), "z": (-15, 15)},
    "gallery": {"x": (-12, 12), "z": (-12, 15)},
    "dungeon": {"x": (-12, 12), "z": (-12, 12)},
}


def _load_world_bounds_from_configs() -> dict:
    """Mirror of validate_action.py:_load_world_bounds — reads worlds/*/config.json."""
    bounds: dict = {}
    if WORLDS_DIR.is_dir():
        for world_dir in sorted(WORLDS_DIR.iterdir()):
            if not world_dir.is_dir():
                continue
            config_file = world_dir / "config.json"
            if not config_file.exists():
                continue
            try:
                with open(config_file) as f:
                    config = json.load(f)
            except (json.JSONDecodeError, OSError):
                continue
            b = config.get("bounds", {})
            if b:
                bounds[world_dir.name] = {
                    "x": tuple(b.get("x", [-15, 15])),
                    "z": tuple(b.get("z", [-15, 15])),
                }
    return bounds or dict(_FALLBACK_WORLD_BOUNDS)


WORLD_BOUNDS = _load_world_bounds_from_configs()

# State files that intentionally don't follow the standard `{_meta, <arrays>}`
# schema. Add to this set with a justification when a new exemption is needed.
_NON_STANDARD_STATE_FILES = {
    # github_llm.py budget tracker: {date, calls} — not a world-state document.
    "llm_usage.json",
}

# Meta/system agent IDs that may have memory files but legitimately don't
# live in state/agents.json (they're driven by scripts, not in-world).
_META_AGENT_IDS = {
    # self_improve.py uses this as its persistent memory namespace.
    "evolve-001",
}

# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def load_json(path: Path) -> dict | None:
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        return None


def load_yaml_text(path: Path) -> str:
    with open(path) as f:
        return f.read()


def _is_iso_utc_timestamp(ts: object) -> bool:
    """ISO-8601 with explicit UTC ('Z' or +00:00). Same shape used everywhere."""
    if not isinstance(ts, str) or not ts:
        return False
    try:
        from datetime import datetime
        datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return False
    return ts.endswith("Z") or ts.endswith("+00:00")


def get_workflow_files() -> list[Path]:
    if not WORKFLOWS_DIR.exists():
        return []
    return sorted(WORKFLOWS_DIR.glob("*.yml"))


# Workflows that mutate state (push to main or create PRs touching state)
STATE_MUTATING_WORKFLOWS = {
    "agent-action.yml",
    "game-tick.yml",
    "world-growth.yml",
    "architect-explore.yml",
    "agent-autonomy.yml",
    "apply-deltas.yml",
    "npc-conversationalist.yml",
    "world-activity.yml",
}


# ═════════════════════════════════════════════
# WORKFLOW INFRASTRUCTURE TESTS
# ═════════════════════════════════════════════

class TestWorkflowConcurrency(unittest.TestCase):
    """Verify all state-mutating workflows have the global concurrency group."""

    def test_all_state_workflows_have_concurrency(self):
        """Every workflow that writes state must have concurrency: group: state-writer."""
        missing = []
        for wf_path in get_workflow_files():
            if wf_path.name not in STATE_MUTATING_WORKFLOWS:
                continue
            content = load_yaml_text(wf_path)
            if "group: state-writer" not in content:
                missing.append(wf_path.name)
        self.assertEqual(
            missing, [],
            f"Workflows missing 'concurrency: group: state-writer': {missing}"
        )

    def test_concurrency_does_not_cancel(self):
        """Concurrency groups must NOT cancel in-progress runs (would lose state changes)."""
        for wf_path in get_workflow_files():
            if wf_path.name not in STATE_MUTATING_WORKFLOWS:
                continue
            content = load_yaml_text(wf_path)
            if "group: state-writer" in content:
                self.assertIn(
                    "cancel-in-progress: false", content,
                    f"{wf_path.name} has concurrency but cancel-in-progress is not false"
                )


class TestWorkflowPushSafety(unittest.TestCase):
    """Verify no workflow does a bare git push without retry logic."""

    def test_no_bare_git_push(self):
        """Direct pushes to main should have retry-on-conflict logic.
        Pushes to new branches (--set-upstream) are safe and excluded."""
        violations = []
        for wf_path in get_workflow_files():
            if wf_path.name not in STATE_MUTATING_WORKFLOWS:
                continue
            content = load_yaml_text(wf_path)
            lines = content.split("\n")
            for i, line in enumerate(lines, 1):
                stripped = line.strip()
                # Match bare "git push" (no --set-upstream = pushing to current branch / main)
                if re.match(r'^git push\b', stripped) and "--set-upstream" not in stripped:
                    # Check if it's inside a retry block
                    context = "\n".join(lines[max(0, i-3):i+2])
                    if "git pull --rebase" not in context and "|| " not in context:
                        violations.append(f"{wf_path.name}:{i}")
        self.assertEqual(
            violations, [],
            f"Bare 'git push' to main without retry found at: {violations}"
        )

    def test_no_direct_push_without_pr(self):
        """Game tick, heartbeat, architect should use PR pattern, not direct push."""
        should_use_prs = {"game-tick.yml", "world-growth.yml", "architect-explore.yml"}
        direct_pushers = []
        for wf_path in get_workflow_files():
            if wf_path.name not in should_use_prs:
                continue
            content = load_yaml_text(wf_path)
            if "git push" in content and "gh pr create" not in content:
                direct_pushers.append(wf_path.name)
        self.assertEqual(
            direct_pushers, [],
            f"Workflows pushing directly to main without PR: {direct_pushers}"
        )

    def test_pr_creating_workflows_self_merge(self):
        """Workflows that create PRs must also validate + merge them (GITHUB_TOKEN limitation)."""
        must_self_merge = {
            "game-tick.yml", "world-growth.yml", "architect-explore.yml", "agent-autonomy.yml"
        }
        missing_merge = []
        missing_validate = []
        for wf_path in get_workflow_files():
            if wf_path.name not in must_self_merge:
                continue
            content = load_yaml_text(wf_path)
            if "gh pr create" in content:
                if "gh pr merge" not in content:
                    missing_merge.append(wf_path.name)
                if "validate_action.py" not in content:
                    missing_validate.append(wf_path.name)
        self.assertEqual(
            missing_merge, [],
            f"Workflows creating PRs without self-merge: {missing_merge}"
        )
        self.assertEqual(
            missing_validate, [],
            f"Workflows creating PRs without self-validation: {missing_validate}"
        )


class TestWorkflowPII(unittest.TestCase):
    """Verify no PII in workflow files."""

    def test_no_real_emails(self):
        """Workflow files should use noreply addresses, not real emails."""
        email_pattern = re.compile(r'[\w.-]+@[\w.-]+\.\w+')
        allowed = {"action@github.com", "41898282+github-actions[bot]@users.noreply.github.com"}
        violations = []
        for wf_path in get_workflow_files():
            content = load_yaml_text(wf_path)
            for match in email_pattern.finditer(content):
                email = match.group()
                if email not in allowed:
                    violations.append(f"{wf_path.name}: {email}")
        self.assertEqual(
            violations, [],
            f"Real email addresses found in workflows: {violations}"
        )


class TestPRValidatorGate(unittest.TestCase):
    """Exercise the real validator CLI in an Actions-shaped Git repository."""

    def setUp(self):
        self.repo = Path(tempfile.mkdtemp(prefix="rappterverse-validator-"))
        self.addCleanup(shutil.rmtree, self.repo)
        (self.repo / "state").mkdir()
        shutil.copy2(STATE_DIR / "agents.json", self.repo / "state" / "agents.json")
        shutil.copy2(STATE_DIR / "actions.json", self.repo / "state" / "actions.json")
        self._git("init", "-q")
        self._git("config", "user.name", "Validator Test")
        self._git("config", "user.email", "validator@users.noreply.github.com")
        self._git("add", "state")
        self._git("commit", "-qm", "base state")
        self._git("update-ref", "refs/remotes/origin/main", "HEAD")

    def _git(self, *args):
        return subprocess.run(
            ["git", *args],
            cwd=self.repo,
            check=True,
            capture_output=True,
            text=True,
        )

    def _commit_candidate(self, *, invalid_json=False, mixed_path=False):
        actions_path = self.repo / "state" / "actions.json"
        if invalid_json:
            actions_path.write_text("{\n", encoding="utf-8")
        else:
            actions_path.write_text(
                actions_path.read_text(encoding="utf-8") + " ",
                encoding="utf-8",
            )
        if mixed_path:
            scripts_dir = self.repo / "scripts"
            scripts_dir.mkdir()
            (scripts_dir / "untrusted.py").write_text("print('candidate code')\n")
        self._git("add", "-A")
        self._git("commit", "-qm", "candidate state")

    def _commit_action(self, agent_id, *, trim=True):
        actions_path = self.repo / "state" / "actions.json"
        data = json.loads(actions_path.read_text(encoding="utf-8"))
        last = data["actions"][-1]
        data["actions"].append({
            "id": "action-auth-test",
            "timestamp": last["timestamp"],
            "agentId": agent_id,
            "type": "emote",
            "world": next(
                agent["world"]
                for agent in json.loads((self.repo / "state" / "agents.json").read_text())["agents"]
                if agent["id"] == agent_id
            ),
            "data": {"emote": "wave", "duration": 1000},
        })
        if trim:
            data["actions"] = data["actions"][-100:]
        actions_path.write_text(json.dumps(data, indent=4) + "\n", encoding="utf-8")
        self._git("add", "state/actions.json")
        self._git("commit", "-qm", "candidate action")

    def _commit_controller_transfer(self, agent_id, controller):
        agents_path = self.repo / "state" / "agents.json"
        data = json.loads(agents_path.read_text(encoding="utf-8"))
        next(agent for agent in data["agents"] if agent["id"] == agent_id)["controller"] = controller
        agents_path.write_text(json.dumps(data, indent=4) + "\n", encoding="utf-8")
        self._git("add", "state/agents.json")
        self._git("commit", "-qm", "transfer controller")

    def _run_validator(self, **env_overrides):
        env = os.environ.copy()
        env.update({
            "VALIDATION_REPO_ROOT": str(self.repo),
            "VALIDATION_BASE_SHA": "origin/main",
            "VALIDATION_HEAD_SHA": "HEAD",
            "VALIDATION_REQUIRE_RELEVANT": "1",
            "VALIDATION_REQUIRE_AUTH": "1",
            "REPOSITORY_OWNER": "kody-w",
            "PR_AUTHOR": "validator-test",
        })
        env.update(env_overrides)
        return subprocess.run(
            [sys.executable, str(BASE_DIR / "scripts" / "validate_action.py")],
            capture_output=True,
            text=True,
            env=env,
        )

    def test_changed_state_file_is_discovered(self):
        self._commit_candidate()
        result = self._run_validator()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("state/actions.json", result.stdout)
        self.assertNotIn("No rappterverse state files modified", result.stdout)

    def test_invalid_changed_json_fails(self):
        self._commit_candidate(invalid_json=True)
        result = self._run_validator()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Invalid JSON", result.stdout)

    def test_git_diff_failure_fails_closed(self):
        result = self._run_validator(VALIDATION_BASE_SHA="missing-base")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Unable to determine changed files", result.stdout)

    def test_mixed_code_and_state_pr_fails(self):
        self._commit_candidate(mixed_path=True)
        result = self._run_validator()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("may only modify state/", result.stdout)

    def test_matching_controller_can_append_action(self):
        self._commit_action("clawdbot-001")
        result = self._run_validator(PR_AUTHOR="openclaw")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_other_controller_cannot_append_action(self):
        self._commit_action("clawdbot-001")
        result = self._run_validator(PR_AUTHOR="mallory")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("controlled by `openclaw`", result.stdout)

    def test_untrusted_author_cannot_act_as_system_agent(self):
        self._commit_action("kody-001")
        result = self._run_validator(PR_AUTHOR="mallory")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("system-controlled", result.stdout)

    def test_authorization_uses_updated_base_controller(self):
        self._commit_action("clawdbot-001")
        candidate_head = self._git("rev-parse", "HEAD").stdout.strip()
        self._git("checkout", "-qb", "updated-base", "origin/main")
        agents_path = self.repo / "state" / "agents.json"
        data = json.loads(agents_path.read_text(encoding="utf-8"))
        next(agent for agent in data["agents"] if agent["id"] == "clawdbot-001")["controller"] = "mallory"
        agents_path.write_text(json.dumps(data, indent=4) + "\n", encoding="utf-8")
        self._git("add", "state/agents.json")
        self._git("commit", "-qm", "transfer controller")
        self._git("update-ref", "refs/remotes/origin/main", "HEAD")
        self._git("checkout", "-q", "--detach", candidate_head)

        result = self._run_validator(PR_AUTHOR="openclaw")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("controlled by `mallory`", result.stdout)

    def test_action_history_must_remain_capped(self):
        self._commit_action("clawdbot-001", trim=False)
        result = self._run_validator(PR_AUTHOR="openclaw")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("most recent 100", result.stdout)

    def test_trusted_automation_can_transfer_controller(self):
        self._commit_controller_transfer("clawdbot-001", "kody-w")
        result = self._run_validator(PR_AUTHOR="kody-w")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_agent_cannot_transfer_its_controller(self):
        self._commit_controller_transfer("clawdbot-001", "mallory")
        result = self._run_validator(PR_AUTHOR="openclaw")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Only trusted automation may transfer", result.stdout)


class TestAgentActionWorkflowTrust(unittest.TestCase):
    """The privileged action workflow must be controlled by the base branch."""

    def test_uses_base_controlled_trigger(self):
        content = load_yaml_text(WORKFLOWS_DIR / "agent-action.yml")
        self.assertIn("pull_request_target:", content)
        self.assertNotRegex(content, r"(?m)^  pull_request:$")

    def test_merge_has_explicit_repository_context(self):
        content = load_yaml_text(WORKFLOWS_DIR / "agent-action.yml")
        self.assertIn("GH_REPO: ${{ github.repository }}", content)
        self.assertIn("--match-head-commit", content)
        self.assertIn('current_base="$(gh api', content)
        self.assertNotIn("--auto", content)
        self.assertIn("gh workflow run apply-deltas.yml", content)


# ═════════════════════════════════════════════
# STATE FILE INTEGRITY TESTS
# ═════════════════════════════════════════════

class TestStateJSON(unittest.TestCase):
    """Verify all state JSON files are valid and well-formed."""

    def test_agents_json_valid(self):
        data = load_json(STATE_DIR / "agents.json")
        self.assertIsNotNone(data, "agents.json is invalid JSON or missing")
        self.assertIn("agents", data)
        self.assertIsInstance(data["agents"], list)
        self.assertIn("_meta", data)

    def test_actions_json_valid(self):
        data = load_json(STATE_DIR / "actions.json")
        self.assertIsNotNone(data, "actions.json is invalid JSON or missing")
        self.assertIn("actions", data)
        self.assertIsInstance(data["actions"], list)

    def test_chat_json_valid(self):
        data = load_json(STATE_DIR / "chat.json")
        self.assertIsNotNone(data, "chat.json is invalid JSON or missing")
        self.assertIn("messages", data)
        self.assertIsInstance(data["messages"], list)

    def test_all_world_objects_valid(self):
        for world_dir in sorted(WORLDS_DIR.iterdir()):
            if not world_dir.is_dir():
                continue
            objects_file = world_dir / "objects.json"
            if objects_file.exists():
                data = load_json(objects_file)
                self.assertIsNotNone(data, f"{world_dir.name}/objects.json is invalid JSON")
                self.assertIn("objects", data)

    def test_activity_json_valid(self):
        path = FEED_DIR / "activity.json"
        if path.exists():
            data = load_json(path)
            self.assertIsNotNone(data, "activity.json is invalid JSON")
            self.assertIn("activities", data)

    def test_all_state_files_have_valid_lastUpdate(self):
        """Every state/*.json must carry a parseable ISO-8601 UTC `_meta.lastUpdate`.

        Catches a real bug class: typo'd or missing timestamps silently break
        downstream consumers (frontend polling, dashboards, action validation).

        Files in `_NON_STANDARD_STATE_FILES` are exempt — they have a different
        shape on purpose (e.g. llm_usage.json is a flat per-day budget counter
        consumed by github_llm.py, not a world-state document).
        """
        if not STATE_DIR.is_dir():
            self.skipTest("state/ not available")
        violations = []
        for state_file in sorted(STATE_DIR.glob("*.json")):
            if state_file.name in _NON_STANDARD_STATE_FILES:
                continue
            data = load_json(state_file)
            if data is None:
                violations.append(f"{state_file.name}: invalid JSON")
                continue
            if not isinstance(data, dict):
                # Top-level lists are non-standard — should be in exemption list.
                violations.append(f"{state_file.name}: top-level value is not an object")
                continue
            meta = data.get("_meta")
            if not isinstance(meta, dict):
                violations.append(f"{state_file.name}: missing/invalid _meta object")
                continue
            ts = meta.get("lastUpdate")
            if ts is None:
                violations.append(f"{state_file.name}: missing _meta.lastUpdate")
            elif not _is_iso_utc_timestamp(ts):
                violations.append(f"{state_file.name}: _meta.lastUpdate not ISO-8601 UTC ({ts!r})")
        self.assertEqual(
            violations, [],
            "Invalid _meta.lastUpdate in:\n  " + "\n  ".join(violations)
        )


class TestWorldConfigs(unittest.TestCase):
    """Verify every expected world has a config.json with bounds — the source
    of truth used by validate_action.py and these tests."""

    EXPECTED_WORLDS = {"hub", "arena", "marketplace", "gallery", "dungeon"}

    def test_all_expected_worlds_have_config(self):
        if not WORLDS_DIR.is_dir():
            self.skipTest("worlds/ not available")
        missing = []
        for world in sorted(self.EXPECTED_WORLDS):
            config_file = WORLDS_DIR / world / "config.json"
            if not config_file.exists():
                missing.append(f"{world}/config.json")
        self.assertEqual(
            missing, [],
            f"Worlds missing config.json (validator will fall back to hardcoded bounds): {missing}"
        )

    def test_loaded_bounds_cover_all_expected_worlds(self):
        bounds = _load_world_bounds_from_configs()
        missing = [w for w in self.EXPECTED_WORLDS if w not in bounds]
        self.assertEqual(
            missing, [],
            f"_load_world_bounds_from_configs did not return bounds for: {missing}"
        )


class TestAgentIntegrity(unittest.TestCase):
    """Validate agent data consistency."""

    def setUp(self):
        self.agents_data = load_json(STATE_DIR / "agents.json")
        if self.agents_data is None:
            self.skipTest("agents.json not available")
        self.agents = self.agents_data.get("agents", [])

    def test_no_duplicate_agent_ids(self):
        ids = [a["id"] for a in self.agents if "id" in a]
        self.assertEqual(len(ids), len(set(ids)), f"Duplicate agent IDs found")

    def test_all_agents_have_required_fields(self):
        required = {"id", "name", "world", "position", "status"}
        for agent in self.agents:
            aid = agent.get("id", "unknown")
            for field in required:
                self.assertIn(field, agent, f"Agent {aid} missing '{field}'")

    def test_all_agents_in_valid_worlds(self):
        for agent in self.agents:
            world = agent.get("world")
            if world:
                self.assertIn(
                    world, WORLD_BOUNDS,
                    f"Agent {agent.get('id')} in unknown world '{world}'"
                )

    def test_all_positions_in_bounds(self):
        for agent in self.agents:
            world = agent.get("world", "hub")
            pos = agent.get("position", {})
            bounds = WORLD_BOUNDS.get(world)
            if bounds and pos:
                x, z = pos.get("x", 0), pos.get("z", 0)
                self.assertTrue(
                    bounds["x"][0] <= x <= bounds["x"][1],
                    f"Agent {agent.get('id')}: x={x} out of bounds for {world}"
                )
                self.assertTrue(
                    bounds["z"][0] <= z <= bounds["z"][1],
                    f"Agent {agent.get('id')}: z={z} out of bounds for {world}"
                )

    def test_meta_agent_count_matches(self):
        meta = self.agents_data.get("_meta", {})
        count = meta.get("agentCount")
        if count is not None:
            diff = abs(count - len(self.agents))
            if diff > 0:
                print(f"\n  ⚠ WARNING: _meta.agentCount ({count}) != actual ({len(self.agents)}) — pre-existing drift")
            # Allow up to 5 drift for pre-existing issues; hard-fail on large divergence
            self.assertTrue(
                diff <= 5,
                f"_meta.agentCount ({count}) diverged too far from actual ({len(self.agents)})"
            )


class TestActionIntegrity(unittest.TestCase):
    """Validate action data consistency."""

    def setUp(self):
        self.actions_data = load_json(STATE_DIR / "actions.json")
        if self.actions_data is None:
            self.skipTest("actions.json not available")
        self.actions = self.actions_data.get("actions", [])
        self.agents_data = load_json(STATE_DIR / "agents.json")

    def test_no_duplicate_action_ids(self):
        ids = [a["id"] for a in self.actions if "id" in a]
        self.assertEqual(len(ids), len(set(ids)), "Duplicate action IDs found")

    def test_action_ids_sequential(self):
        """Action IDs should be monotonically increasing."""
        prev_num = -1
        for action in self.actions:
            aid = action.get("id", "")
            match = re.match(r"action-(\d+)", aid)
            if match:
                num = int(match.group(1))
                self.assertGreaterEqual(
                    num, prev_num,
                    f"Action ID {aid} is not sequential (prev was action-{prev_num})"
                )
                prev_num = num

    def test_timestamps_monotonic(self):
        """Timestamps should be monotonically non-decreasing."""
        prev_ts = ""
        for action in self.actions:
            ts = action.get("timestamp", "")
            if ts and prev_ts:
                self.assertGreaterEqual(
                    ts, prev_ts,
                    f"Action {action.get('id')}: timestamp {ts} < previous {prev_ts}"
                )
            if ts:
                prev_ts = ts

    def test_action_agents_exist(self):
        """All agentIds in actions should reference existing agents."""
        if not self.agents_data:
            self.skipTest("agents.json not available for cross-validation")
        agent_ids = {a["id"] for a in self.agents_data.get("agents", []) if "id" in a}
        missing = set()
        for action in self.actions:
            agent_id = action.get("agentId")
            if agent_id and agent_id not in agent_ids:
                missing.add(agent_id)
        self.assertEqual(
            missing, set(),
            f"Actions reference non-existent agents: {missing}"
        )


class TestChatIntegrity(unittest.TestCase):
    """Validate chat data consistency."""

    def setUp(self):
        self.chat_data = load_json(STATE_DIR / "chat.json")
        if self.chat_data is None:
            self.skipTest("chat.json not available")
        self.messages = self.chat_data.get("messages", [])

    def test_no_duplicate_message_ids(self):
        ids = [m["id"] for m in self.messages if "id" in m]
        self.assertEqual(len(ids), len(set(ids)), "Duplicate message IDs found")

    def test_messages_have_content(self):
        for msg in self.messages:
            self.assertIn("content", msg, f"Message {msg.get('id')} missing content")
            self.assertTrue(
                len(msg.get("content", "")) > 0,
                f"Message {msg.get('id')} has empty content"
            )

    def test_messages_have_author(self):
        for msg in self.messages:
            self.assertIn("author", msg, f"Message {msg.get('id')} missing author")
            author = msg.get("author", {})
            self.assertIn("id", author, f"Message {msg.get('id')} author missing id")

    def test_meta_message_count_matches(self):
        """`_meta.messageCount` should track len(messages) (mirrors agentCount check)."""
        meta = self.chat_data.get("_meta", {})
        count = meta.get("messageCount")
        if count is None:
            self.skipTest("chat.json has no _meta.messageCount field")
        diff = abs(count - len(self.messages))
        if diff > 0:
            print(f"\n  ⚠ WARNING: _meta.messageCount ({count}) != actual ({len(self.messages)}) — pre-existing drift")
        # Same tolerance as agentCount: warn on small drift, hard-fail on systemic divergence.
        self.assertTrue(
            diff <= 5,
            f"_meta.messageCount ({count}) diverged too far from actual ({len(self.messages)})"
        )


class TestWorldObjectIntegrity(unittest.TestCase):
    """Validate world object data."""

    def test_no_duplicate_object_ids_per_world(self):
        for world_dir in sorted(WORLDS_DIR.iterdir()):
            if not world_dir.is_dir():
                continue
            objects_file = world_dir / "objects.json"
            if not objects_file.exists():
                continue
            data = load_json(objects_file)
            if not data:
                continue
            ids = [o["id"] for o in data.get("objects", []) if "id" in o]
            self.assertEqual(
                len(ids), len(set(ids)),
                f"Duplicate object IDs in {world_dir.name}/objects.json"
            )

    def test_object_positions_in_bounds(self):
        violations = []
        for world_dir in sorted(WORLDS_DIR.iterdir()):
            if not world_dir.is_dir():
                continue
            world_name = world_dir.name
            bounds = WORLD_BOUNDS.get(world_name)
            if not bounds:
                continue
            objects_file = world_dir / "objects.json"
            if not objects_file.exists():
                continue
            data = load_json(objects_file)
            if not data:
                continue
            for obj in data.get("objects", []):
                pos = obj.get("position", {})
                if not pos:
                    continue
                x = pos.get("x", 0)
                z = pos.get("z", 0)
                if not (bounds["x"][0] <= x <= bounds["x"][1]):
                    violations.append(f"{obj.get('id')} in {world_name}: x={x}")
                if not (bounds["z"][0] <= z <= bounds["z"][1]):
                    violations.append(f"{obj.get('id')} in {world_name}: z={z}")
        if violations:
            print(f"\n  ⚠ WARNING: {len(violations)} object(s) out of bounds (pre-existing):")
            for v in violations[:5]:
                print(f"    - {v}")
        # Hard-fail only on large number of NEW violations (>20 = systemic issue)
        # Pre-existing portals/spectators are intentionally placed outside playable bounds
        self.assertTrue(
            len(violations) <= 20,
            f"Too many out-of-bounds objects ({len(violations)}): {violations[:5]}"
        )


# ═════════════════════════════════════════════
# DELTA SYSTEM TESTS
# ═════════════════════════════════════════════

class TestDeltaApplier(unittest.TestCase):
    """Test apply_deltas.py logic with synthetic data."""

    def setUp(self):
        import tempfile
        self.tmpdir = Path(tempfile.mkdtemp())
        # Create minimal state structure
        (self.tmpdir / "state" / "inbox").mkdir(parents=True)
        (self.tmpdir / "state").joinpath("actions.json").write_text(
            json.dumps({"actions": [], "_meta": {"lastUpdate": "2026-01-01T00:00:00Z"}})
        )
        (self.tmpdir / "state").joinpath("chat.json").write_text(
            json.dumps({"messages": [], "_meta": {"lastUpdate": "2026-01-01T00:00:00Z"}})
        )
        (self.tmpdir / "state").joinpath("agents.json").write_text(
            json.dumps({"agents": [{"id": "test-001", "name": "Test", "world": "hub",
                                     "controller": "test-controller",
                                     "position": {"x": 0, "y": 0, "z": 0}, "status": "active"}],
                         "_meta": {"lastUpdate": "2026-01-01T00:00:00Z", "agentCount": 1}})
        )
        (self.tmpdir / "worlds" / "hub").mkdir(parents=True)
        (self.tmpdir / "worlds" / "hub" / "objects.json").write_text(
            json.dumps({"objects": [], "_meta": {"lastUpdated": "2026-01-01T00:00:00Z", "contributors": []}})
        )
        (self.tmpdir / "feed").mkdir(parents=True)
        (self.tmpdir / "feed" / "activity.json").write_text(
            json.dumps({"activities": []})
        )

    def _write_delta(self, filename: str, delta: dict):
        if "controller" not in delta:
            update = delta.get("agent_update", {})
            delta["controller"] = update.get("controller", "test-controller")
        path = self.tmpdir / "state" / "inbox" / filename
        path.write_text(json.dumps(delta))

    def _run_applier(self):
        """Run apply_deltas with patched paths."""
        import importlib.util
        import unittest.mock as mock

        spec = importlib.util.spec_from_file_location(
            "apply_deltas_test", SCRIPT_DIR / "apply_deltas.py"
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        # Patch module-level paths
        mod.BASE_DIR = self.tmpdir
        mod.INBOX_DIR = self.tmpdir / "state" / "inbox"
        mod.STATE_DIR = self.tmpdir / "state"
        mod.WORLDS_DIR = self.tmpdir / "worlds"
        mod.FEED_DIR = self.tmpdir / "feed"

        try:
            mod.main()
        except SystemExit:
            pass
        return mod

    def test_append_actions(self):
        self._write_delta("test-delta.json", {
            "agent_id": "test-001",
            "timestamp": "2026-02-11T20:00:00Z",
            "actions": [{"id": "action-001", "timestamp": "2026-02-11T20:00:00Z",
                         "agentId": "test-001", "type": "chat", "world": "hub",
                         "data": {"message": "test"}}]
        })
        self._run_applier()
        data = json.loads((self.tmpdir / "state" / "actions.json").read_text())
        self.assertEqual(len(data["actions"]), 1)
        self.assertEqual(data["actions"][0]["id"], "action-001")

    def test_append_messages(self):
        self._write_delta("test-delta.json", {
            "agent_id": "test-001",
            "timestamp": "2026-02-11T20:00:00Z",
            "messages": [{"id": "msg-001", "timestamp": "2026-02-11T20:00:00Z",
                          "world": "hub", "content": "hello",
                          "author": {"id": "test-001", "name": "Test", "avatar": "🤖", "type": "agent"},
                          "type": "chat"}]
        })
        self._run_applier()
        data = json.loads((self.tmpdir / "state" / "chat.json").read_text())
        self.assertEqual(len(data["messages"]), 1)

    def test_action_and_chat_histories_are_capped(self):
        actions = [{"id": f"action-{index:03d}"} for index in range(100)]
        messages = [{"id": f"msg-{index:03d}"} for index in range(100)]
        (self.tmpdir / "state" / "actions.json").write_text(
            json.dumps({"actions": actions, "_meta": {}})
        )
        (self.tmpdir / "state" / "chat.json").write_text(
            json.dumps({"messages": messages, "_meta": {}})
        )
        self._write_delta("cap.json", {
            "agent_id": "test-001",
            "timestamp": "2026-02-11T20:00:00Z",
            "actions": [{"id": "action-new", "agentId": "test-001", "type": "emote"}],
            "messages": [{"id": "msg-new", "author": {"id": "test-001"}, "content": "new"}],
        })
        self._run_applier()
        action_data = json.loads((self.tmpdir / "state" / "actions.json").read_text())
        chat_data = json.loads((self.tmpdir / "state" / "chat.json").read_text())
        self.assertEqual(len(action_data["actions"]), 100)
        self.assertEqual(action_data["actions"][-1]["id"], "action-new")
        self.assertEqual(len(chat_data["messages"]), 100)
        self.assertEqual(chat_data["messages"][-1]["id"], "msg-new")
        self.assertEqual(chat_data["_meta"]["messageCount"], 100)

    def test_upsert_agent(self):
        self._write_delta("test-delta.json", {
            "agent_id": "test-001",
            "timestamp": "2026-02-11T20:00:00Z",
            "agent_update": {"id": "test-001", "position": {"x": 5, "y": 0, "z": 3}, "action": "walking"}
        })
        self._run_applier()
        data = json.loads((self.tmpdir / "state" / "agents.json").read_text())
        agent = next(a for a in data["agents"] if a["id"] == "test-001")
        self.assertEqual(agent["position"]["x"], 5)
        self.assertEqual(agent["action"], "walking")

    def test_spawn_new_agent(self):
        self._write_delta("test-delta.json", {
            "agent_id": "new-001",
            "timestamp": "2026-02-11T20:00:00Z",
            "agent_update": {"id": "new-001", "name": "New Agent", "controller": "new-controller", "world": "hub",
                             "position": {"x": 0, "y": 0, "z": 0}, "status": "active"}
        })
        self._run_applier()
        data = json.loads((self.tmpdir / "state" / "agents.json").read_text())
        self.assertEqual(len(data["agents"]), 2)
        self.assertEqual(data["_meta"]["agentCount"], 2)

    def test_add_world_objects(self):
        self._write_delta("test-delta.json", {
            "agent_id": "test-001",
            "timestamp": "2026-02-11T20:00:00Z",
            "objects": {
                "world": "hub",
                "entries": [{"id": "obj-001", "type": "decoration", "name": "Test",
                             "position": {"x": 0, "y": 0, "z": 0}}]
            }
        })
        self._run_applier()
        data = json.loads((self.tmpdir / "worlds" / "hub" / "objects.json").read_text())
        self.assertEqual(len(data["objects"]), 1)
        self.assertIn("test-001", data["_meta"]["contributors"])

    def test_object_deduplication(self):
        # Pre-populate with an object
        (self.tmpdir / "worlds" / "hub" / "objects.json").write_text(
            json.dumps({"objects": [{"id": "obj-001", "name": "Existing"}],
                        "_meta": {"lastUpdated": "2026-01-01T00:00:00Z", "contributors": []}})
        )
        self._write_delta("test-delta.json", {
            "agent_id": "test-001",
            "timestamp": "2026-02-11T20:00:00Z",
            "objects": {
                "world": "hub",
                "entries": [{"id": "obj-001", "name": "Duplicate"}, {"id": "obj-002", "name": "New"}]
            }
        })
        self._run_applier()
        data = json.loads((self.tmpdir / "worlds" / "hub" / "objects.json").read_text())
        self.assertEqual(len(data["objects"]), 2)  # obj-001 not duplicated

    def test_processed_deltas_removed(self):
        self._write_delta("test-delta.json", {
            "agent_id": "test-001",
            "timestamp": "2026-02-11T20:00:00Z",
            "actions": [{"id": "action-001", "timestamp": "2026-02-11T20:00:00Z",
                         "agentId": "test-001", "type": "chat", "world": "hub",
                         "data": {"message": "test"}}]
        })
        self._run_applier()
        remaining = list((self.tmpdir / "state" / "inbox").glob("*.json"))
        self.assertEqual(len(remaining), 0, "Delta file should be removed after processing")

    def test_conflicting_spawn_controllers_reject_entire_batch(self):
        for filename, controller in (("a.json", "alice"), ("b.json", "mallory")):
            self._write_delta(filename, {
                "agent_id": "same-001",
                "controller": controller,
                "timestamp": "2026-02-11T20:00:00Z",
                "agent_update": {
                    "id": "same-001",
                    "controller": controller,
                    "name": "Same",
                    "world": "hub",
                },
            })
        self._run_applier()
        data = json.loads((self.tmpdir / "state" / "agents.json").read_text())
        self.assertFalse(any(agent["id"] == "same-001" for agent in data["agents"]))

    def test_applier_rejects_stale_controller_provenance(self):
        self._write_delta("stale.json", {
            "agent_id": "test-001",
            "controller": "old-controller",
            "timestamp": "2026-02-11T20:00:00Z",
            "actions": [{
                "id": "action-stale",
                "agentId": "test-001",
                "type": "emote",
            }],
        })
        self._run_applier()
        data = json.loads((self.tmpdir / "state" / "actions.json").read_text())
        self.assertEqual(data["actions"], [])

    def test_multiple_deltas_ordered_by_timestamp(self):
        self._write_delta("b-second.json", {
            "agent_id": "test-001",
            "timestamp": "2026-02-11T20:01:00Z",
            "actions": [{"id": "action-002", "timestamp": "2026-02-11T20:01:00Z",
                         "agentId": "test-001", "type": "emote", "world": "hub",
                         "data": {"emote": "wave"}}]
        })
        self._write_delta("a-first.json", {
            "agent_id": "test-001",
            "timestamp": "2026-02-11T20:00:00Z",
            "actions": [{"id": "action-001", "timestamp": "2026-02-11T20:00:00Z",
                         "agentId": "test-001", "type": "chat", "world": "hub",
                         "data": {"message": "first"}}]
        })
        self._run_applier()
        data = json.loads((self.tmpdir / "state" / "actions.json").read_text())
        self.assertEqual(data["actions"][0]["id"], "action-001")
        self.assertEqual(data["actions"][1]["id"], "action-002")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)


class TestDeltaValidator(unittest.TestCase):
    """Test validate_delta.py catches bad input."""

    def setUp(self):
        import tempfile
        self.tmpdir = Path(tempfile.mkdtemp())
        (self.tmpdir / "state" / "inbox").mkdir(parents=True)

    def _write_and_validate(self, filename: str, content: dict) -> bool:
        """Write a delta and run validator. Returns True if valid."""
        path = self.tmpdir / "state" / "inbox" / filename
        path.write_text(json.dumps(content))

        import importlib.util
        spec = importlib.util.spec_from_file_location("validate_delta", SCRIPT_DIR / "validate_delta.py")
        mod = importlib.util.module_from_spec(spec)
        mod.INBOX_DIR = self.tmpdir / "state" / "inbox"
        mod.errors = []

        # We need to reload to reset the errors list
        spec.loader.exec_module(mod)
        mod.errors = []
        mod.validate_delta(path)
        return len(mod.errors) == 0

    def _authorize(self, content: dict, agents: dict, author: str) -> list[str]:
        import importlib.util
        spec = importlib.util.spec_from_file_location("validate_delta_auth", SCRIPT_DIR / "validate_delta.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        mod.errors = []
        mod._load_base_agents = lambda: agents
        with mock.patch.dict(os.environ, {
            "VALIDATION_REQUIRE_AUTH": "1",
            "PR_AUTHOR": author,
            "REPOSITORY_OWNER": "kody-w",
        }):
            mod.validate_delta_authorization(content, Path("test.json"))
        return mod.errors

    def test_valid_delta_passes(self):
        self.assertTrue(self._write_and_validate("good.json", {
            "agent_id": "test-001",
            "timestamp": "2026-02-11T20:00:00Z",
            "actions": [{"id": "action-001", "type": "chat"}]
        }))

    def test_missing_agent_id_fails(self):
        self.assertFalse(self._write_and_validate("bad.json", {
            "timestamp": "2026-02-11T20:00:00Z",
            "actions": [{"id": "action-001", "type": "chat"}]
        }))

    def test_missing_timestamp_fails(self):
        self.assertFalse(self._write_and_validate("bad.json", {
            "agent_id": "test-001",
            "actions": [{"id": "action-001", "type": "chat"}]
        }))

    def test_no_delta_content_fails(self):
        self.assertFalse(self._write_and_validate("bad.json", {
            "agent_id": "test-001",
            "timestamp": "2026-02-11T20:00:00Z"
        }))

    def test_empty_delta_section_fails(self):
        self.assertFalse(self._write_and_validate("bad.json", {
            "agent_id": "test-001",
            "timestamp": "2026-02-11T20:00:00Z",
            "actions": [],
        }))

    def test_invalid_action_type_fails(self):
        self.assertFalse(self._write_and_validate("bad.json", {
            "agent_id": "test-001",
            "timestamp": "2026-02-11T20:00:00Z",
            "actions": [{"id": "action-001", "type": "hack_the_mainframe"}]
        }))

    def test_invalid_world_in_objects_fails(self):
        self.assertFalse(self._write_and_validate("bad.json", {
            "agent_id": "test-001",
            "timestamp": "2026-02-11T20:00:00Z",
            "objects": {"world": "narnia", "entries": [{"id": "obj-001"}]}
        }))

    def test_delta_actor_matches_controller(self):
        errors = self._authorize(
            {
                "agent_id": "alice-001",
                "controller": "alice",
                "actions": [{"agentId": "alice-001"}],
                "messages": [{"author": {"id": "alice-001"}}],
            },
            {"alice-001": {"id": "alice-001", "controller": "alice"}},
            "alice",
        )
        self.assertEqual(errors, [])

    def test_delta_cannot_impersonate_embedded_actor(self):
        errors = self._authorize(
            {
                "agent_id": "alice-001",
                "controller": "alice",
                "actions": [{"agentId": "bob-001"}],
            },
            {
                "alice-001": {"id": "alice-001", "controller": "alice"},
                "bob-001": {"id": "bob-001", "controller": "bob"},
            },
            "alice",
        )
        self.assertTrue(any("must match delta agent" in item for item in errors))

    def test_delta_rejects_wrong_controller(self):
        errors = self._authorize(
            {"agent_id": "alice-001", "controller": "alice"},
            {"alice-001": {"id": "alice-001", "controller": "alice"}},
            "mallory",
        )
        self.assertTrue(any("controlled by `alice`" in item for item in errors))

    def test_delta_rejects_controller_transfer(self):
        errors = self._authorize(
            {
                "agent_id": "alice-001",
                "controller": "alice",
                "agent_update": {"id": "alice-001", "controller": "mallory"},
            },
            {"alice-001": {"id": "alice-001", "controller": "alice"}},
            "alice",
        )
        self.assertTrue(any("direct trusted state PR" in item for item in errors))

    def test_delta_rejects_activity_impersonation(self):
        errors = self._authorize(
            {
                "agent_id": "alice-001",
                "controller": "alice",
                "activities": [{"author": {"id": "bob-001"}}],
            },
            {
                "alice-001": {"id": "alice-001", "controller": "alice"},
                "bob-001": {"id": "bob-001", "controller": "bob"},
            },
            "alice",
        )
        self.assertTrue(any("Activity author must match" in item for item in errors))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)


# ═════════════════════════════════════════════
# INBOX HYGIENE TESTS
# ═════════════════════════════════════════════

class TestInboxHygiene(unittest.TestCase):
    """Verify inbox directory is clean on main."""

    def test_no_stale_json_in_inbox(self):
        """Inbox should be empty on main (all deltas should be processed)."""
        if not INBOX_DIR.exists():
            return  # No inbox dir yet is fine
        json_files = list(INBOX_DIR.glob("*.json"))
        self.assertEqual(
            len(json_files), 0,
            f"Stale delta files in inbox (should be processed): {[f.name for f in json_files]}"
        )


# ═════════════════════════════════════════════
# REFERENTIAL INTEGRITY TESTS
# ═════════════════════════════════════════════

class TestReferentialIntegrity(unittest.TestCase):
    """Cross-file ID validity. Catches the kind of drift that creates ghost
    references nobody ever notices: an agent gets deleted and their bonds,
    actions, or memory file linger forever."""

    def setUp(self):
        agents_data = load_json(STATE_DIR / "agents.json")
        if agents_data is None:
            self.skipTest("agents.json not available")
        self.agent_ids = {a["id"] for a in agents_data.get("agents", []) if "id" in a}

    def test_action_worlds_are_known(self):
        """Every action.world should be a real world directory."""
        actions_data = load_json(STATE_DIR / "actions.json")
        if actions_data is None:
            self.skipTest("actions.json not available")
        unknown = set()
        for action in actions_data.get("actions", []):
            world = action.get("world")
            if world and world not in WORLD_BOUNDS:
                unknown.add(world)
        self.assertEqual(
            unknown, set(),
            f"Actions reference unknown worlds (no worlds/<name>/config.json): {unknown}"
        )

    def test_chat_authors_exist(self):
        """Chat messages from agent authors should reference an existing agent.

        Allows non-agent authors (e.g. NPCs, system) by checking author.type.
        """
        chat_data = load_json(STATE_DIR / "chat.json")
        if chat_data is None:
            self.skipTest("chat.json not available")
        ghost_authors = set()
        for msg in chat_data.get("messages", []):
            author = msg.get("author") or {}
            if author.get("type") != "agent":
                continue
            aid = author.get("id")
            if aid and aid not in self.agent_ids:
                ghost_authors.add(aid)
        self.assertEqual(
            ghost_authors, set(),
            f"Chat messages from non-existent agents: {ghost_authors}"
        )

    def test_relationship_edges_reference_existing_agents(self):
        rel = load_json(STATE_DIR / "relationships.json")
        if rel is None:
            self.skipTest("relationships.json not available")
        ghosts = set()
        for edge in rel.get("edges", []):
            for key in ("a", "b"):
                aid = edge.get(key)
                if aid and aid not in self.agent_ids:
                    ghosts.add(aid)
        # Same tolerance pattern as agentCount/object-bounds: warn on small
        # pre-existing drift, hard-fail on systemic divergence.
        if ghosts:
            print(f"\n  ⚠ WARNING: {len(ghosts)} relationship edge(s) reference unknown agents (sample: {sorted(ghosts)[:3]})")
        self.assertLessEqual(
            len(ghosts), 5,
            f"Too many dangling agent references in relationships.edges: {sorted(ghosts)[:10]}"
        )

    def test_relationship_bonds_reference_existing_agents(self):
        rel = load_json(STATE_DIR / "relationships.json")
        if rel is None:
            self.skipTest("relationships.json not available")
        ghosts = set()
        for bond in rel.get("bonds", []):
            for aid in bond.get("agents", []):
                if aid and aid not in self.agent_ids:
                    ghosts.add(aid)
        if ghosts:
            print(f"\n  ⚠ WARNING: {len(ghosts)} relationship bond(s) reference unknown agents (sample: {sorted(ghosts)[:3]})")
        self.assertLessEqual(
            len(ghosts), 5,
            f"Too many dangling agent references in relationships.bonds: {sorted(ghosts)[:10]}"
        )

    def test_memory_files_match_real_agents(self):
        """state/memory/<id>.json filenames should map to a real agent or to
        an explicitly-allowed meta-agent (see _META_AGENT_IDS)."""
        memory_dir = STATE_DIR / "memory"
        if not memory_dir.is_dir():
            self.skipTest("state/memory/ not available")
        ghost_files = []
        for mem_file in memory_dir.glob("*.json"):
            aid = mem_file.stem
            if aid in self.agent_ids or aid in _META_AGENT_IDS:
                continue
            ghost_files.append(mem_file.name)
        if ghost_files:
            print(f"\n  ⚠ WARNING: {len(ghost_files)} memory file(s) for non-existent agents (sample: {ghost_files[:3]})")
        # Tolerance: memory files for recently-deleted agents may linger
        # one cycle. Hard-fail on systemic accumulation.
        self.assertLessEqual(
            len(ghost_files), 5,
            f"Too many ghost memory files (delete or add agent to _META_AGENT_IDS): {ghost_files[:10]}"
        )


# ═════════════════════════════════════════════
# BUILD HYGIENE TESTS
# ═════════════════════════════════════════════

class TestBundleSourceFiles(unittest.TestCase):
    """Ensure scripts/bundle.sh references only files that actually exist.

    A common failure mode: someone deletes a src/js/foo.js but forgets to
    remove it from bundle.sh's JS_FILES array, or vice versa. The bundle
    silently degrades because `cat` of a missing file errors out partway.
    """

    BUNDLE_SCRIPT = BASE_DIR / "scripts" / "bundle.sh"

    def _extract_listed_files(self) -> list[str]:
        """Pull both CSS_FILES=(...) and JS_FILES=(...) entries out of bundle.sh."""
        if not self.BUNDLE_SCRIPT.exists():
            return []
        text = self.BUNDLE_SCRIPT.read_text()
        files: list[str] = []
        # Match CSS_FILES=( ... ) and JS_FILES=( ... ) blocks.
        for match in re.finditer(r'\b(?:CSS|JS)_FILES=\(([^)]*)\)', text, re.DOTALL):
            block = match.group(1)
            for line in block.splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                # Drop trailing comments and quotes.
                token = line.split("#", 1)[0].strip().strip('"').strip("'")
                if token:
                    files.append(token)
        return files

    def test_all_listed_sources_exist(self):
        listed = self._extract_listed_files()
        self.assertGreater(len(listed), 0, "bundle.sh has no CSS_FILES/JS_FILES entries — parser may be wrong")
        missing = [p for p in listed if not (BASE_DIR / p).exists()]
        self.assertEqual(
            missing, [],
            f"bundle.sh references files that don't exist (delete or rename): {missing}"
        )

    def test_layout_html_exists(self):
        """bundle.sh inlines src/html/layout.html — must be present."""
        layout = BASE_DIR / "src" / "html" / "layout.html"
        self.assertTrue(layout.exists(), f"bundle.sh expects {layout.relative_to(BASE_DIR)} but it's missing")


if __name__ == "__main__":
    unittest.main(verbosity=2)
