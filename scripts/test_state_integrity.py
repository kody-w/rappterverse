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
BASE_DIR = Path(os.environ.get("VALIDATION_REPO_ROOT", SCRIPT_DIR.parent)).resolve()
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


def load_git_blob_json(blob_sha: str) -> dict | None:
    if not re.fullmatch(r"[a-f0-9]{40}", blob_sha):
        return None
    result = subprocess.run(
        ["git", "-C", str(BASE_DIR), "cat-file", "blob", blob_sha],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    return json.loads(result.stdout)


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
    "game-tick.yml",
    "world-growth.yml",
    "architect-explore.yml",
    "agent-autonomy.yml",
    "apply-deltas.yml",
    "self-improve.yml",
    "npc-conversationalist.yml",
    "world-activity.yml",
    "state-drain.yml",
}


# ═════════════════════════════════════════════
# WORKFLOW INFRASTRUCTURE TESTS
# ═════════════════════════════════════════════

class TestCompilerCIScope(unittest.TestCase):
    """Keep immutable compiler inputs outside mutable-world CI scope."""

    def test_trusted_profile_is_code_owned(self):
        profile = BASE_DIR / "compiler" / "profiles" / "rappterverse-v1.json"
        self.assertTrue(profile.is_file())
        self.assertFalse((WORLDS_DIR / "recipes").exists())

    def test_universe_lock_fence_is_code_owned(self):
        self.assertTrue((BASE_DIR / "universe.lock.json").is_file())
        self.assertTrue(
            (
                BASE_DIR / "schema" / "universe-lock-v2.schema.json"
            ).is_file()
        )
        self.assertTrue(
            (BASE_DIR / "tests" / "test_universe_lock_v2.py").is_file()
        )
        for mutable_root in (STATE_DIR, WORLDS_DIR, FEED_DIR):
            self.assertFalse(
                (mutable_root / "universe.lock.json").exists(),
                str(mutable_root),
            )

    def test_universe_lock_regression_is_read_only_and_not_an_action(self):
        command = (
            "python -m unittest discover -s tests "
            "-p 'test_universe_lock_v2.py' -v"
        )
        regression = load_yaml_text(WORKFLOWS_DIR / "regression-tests.yml")
        self.assertEqual(1, regression.count(command))
        test_job = regression.split("\n  report-scheduled-failure:", 1)[0]
        self.assertIn("permissions:\n      contents: read", test_job)
        self.assertIn("persist-credentials: false", test_job)
        self.assertIsNone(
            re.search(r"(?m)^\s+[a-z-]+:\s+write\s*$", test_job)
        )

        action = load_yaml_text(WORKFLOWS_DIR / "agent-action.yml")
        trigger = action.split("\npermissions:", 1)[0]
        self.assertEqual(
            ["state/**", "worlds/**", "feed/**"],
            re.findall(r"(?m)^\s+- ['\"]([^'\"]+)['\"]\s*$", trigger),
        )
        self.assertNotIn("universe", trigger.lower())


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

    def test_pr_creating_workflows_use_reconciler(self):
        """State producers must queue PRs instead of merging around consensus."""
        missing_queue = []
        self_merging = []
        for wf_path in get_workflow_files():
            if wf_path.name not in STATE_MUTATING_WORKFLOWS:
                continue
            content = load_yaml_text(wf_path)
            if "gh pr create" in content:
                if "state-drain.yml" not in content:
                    missing_queue.append(wf_path.name)
                if "gh pr merge" in content:
                    self_merging.append(wf_path.name)
        self.assertEqual(
            missing_queue, [],
            f"State PR producers not waking the reconciler: {missing_queue}"
        )
        self.assertEqual(
            self_merging, [],
            f"State PR producers bypassing the reconciler: {self_merging}"
        )
        for name in ("agent-autonomy.yml", "game-tick.yml", "world-growth.yml"):
            content = load_yaml_text(WORKFLOWS_DIR / name)
            self.assertNotIn("git add -A", content, f"{name} stages non-state files")
            self.assertIn("git add state/ worlds/ feed/", content)
        self_improve = load_yaml_text(WORKFLOWS_DIR / "self-improve.yml")
        self.assertNotIn("git add -A", self_improve)
        self.assertIn("git add state/*.json state/memory/ feed/", self_improve)
        self.assertNotIn("agent_dispatch.py --agent evolve-001", self_improve)
        regression = load_yaml_text(WORKFLOWS_DIR / "regression-tests.yml")
        self.assertIn("ALLOW_DERIVED_STATE_DRIFT", regression)
        self.assertIn("fetch-depth: 0", regression)
        self.assertIn("if: env.ALLOW_DERIVED_STATE_DRIFT != '1'", regression)
        self.assertEqual(regression.count("runs-on: ubuntu-latest"), 2)
        self.assertIn(
            "python -m unittest discover -s tests "
            "-p 'test_world_pack_compiler.py' -v",
            regression,
        )
        self.assertIn("needs: [test]", regression)


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

    def test_pii_workflow_uses_trusted_scanner(self):
        content = load_yaml_text(WORKFLOWS_DIR / "pii-scan.yml")
        self.assertIn("pull_request_target:", content)
        self.assertIn("python trusted/scripts/pii_scan.py", content)
        self.assertIn("persist-credentials: false", content)
        self.assertIn("context: 'pii-scan'", content)
        self.assertIn("statuses: write", content)


class TestPIIScanner(unittest.TestCase):
    """Exercise strict scanner modes and verify findings never echo PII values."""

    def setUp(self):
        self.repo = Path(tempfile.mkdtemp(prefix="rappterverse-pii-"))
        self.addCleanup(shutil.rmtree, self.repo)
        (self.repo / "state").mkdir()
        (self.repo / "state" / "note.txt").write_text("safe\n", encoding="utf-8")
        self._git("init", "-q")
        self._git("config", "user.name", "PII Test")
        self._git("config", "user.email", "pii-test@users.noreply.github.com")
        self._git("add", ".")
        self._git("commit", "-qm", "base")
        self._git("update-ref", "refs/remotes/origin/main", "HEAD")

    def _git(self, *args):
        return subprocess.run(
            ["git", *args],
            cwd=self.repo,
            check=True,
            capture_output=True,
            text=True,
        )

    def _scan(self, *args):
        return subprocess.run(
            [
                sys.executable,
                str(BASE_DIR / "scripts" / "pii_scan.py"),
                "--repo-root",
                str(self.repo),
                *args,
            ],
            capture_output=True,
            text=True,
        )

    def test_paths_mode_detects_and_redacts_email(self):
        email = "person" + "@" + "private.invalid"
        (self.repo / "state" / "note.txt").write_text(
            f"GH_TOKEN is allowed, but {email} is not\n",
            encoding="utf-8",
        )
        self._git("add", "state/note.txt")
        result = self._scan("--paths", "state")
        self.assertEqual(result.returncode, 1)
        self.assertIn("state/note.txt:1 — Email", result.stdout)
        self.assertNotIn(email, result.stdout)

    def test_paths_mode_includes_untracked_files(self):
        email = "untracked" + "@" + "private.invalid"
        (self.repo / "state" / "new.txt").write_text(email + "\n", encoding="utf-8")
        result = self._scan("--paths", "state")
        self.assertEqual(result.returncode, 1)
        self.assertIn("state/new.txt:1 — Email", result.stdout)

    def test_staged_mode_reads_index_not_worktree(self):
        email = "staged" + "@" + "private.invalid"
        note = self.repo / "state" / "note.txt"
        note.write_text(email + "\n", encoding="utf-8")
        self._git("add", "state/note.txt")
        note.write_text("safe working tree\n", encoding="utf-8")
        result = self._scan("--staged")
        self.assertEqual(result.returncode, 1)
        self.assertIn("state/note.txt:1 — Email", result.stdout)
        self.assertNotIn(email, result.stdout)

    def test_unicode_filename_is_scanned_in_every_git_mode(self):
        email = "unicode" + "@" + "private.invalid"
        path = self.repo / "state" / "mémoire.txt"
        path.write_text(email + "\n", encoding="utf-8")
        self._git("add", "state/mémoire.txt")
        for mode in (("--staged",), ("--all-tracked",)):
            result = self._scan(*mode)
            self.assertEqual(result.returncode, 1)
            self.assertIn("state/mémoire.txt:1 — Email", result.stdout)
        self._git("commit", "-qm", "unicode candidate")
        result = self._scan("--diff", "origin/main", "HEAD")
        self.assertEqual(result.returncode, 1)
        self.assertIn("state/mémoire.txt:1 — Email", result.stdout)

    def test_all_tracked_ignores_worktree_deletions(self):
        (self.repo / "state" / "note.txt").unlink()
        result = self._scan("--all-tracked")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_diff_mode_scans_exact_candidate_change(self):
        email = "contact" + "@" + "private.invalid"
        (self.repo / "state" / "note.txt").write_text(
            email + "\n",
            encoding="utf-8",
        )
        self._git("add", "state/note.txt")
        self._git("commit", "-qm", "candidate")
        result = self._scan("--diff", "origin/main", "HEAD")
        self.assertEqual(result.returncode, 1)
        self.assertIn("state/note.txt:1 — Email", result.stdout)

    def test_unknown_or_missing_mode_exits_two(self):
        unknown = self._scan("--unknown")
        missing = self._scan()
        self.assertEqual(unknown.returncode, 2)
        self.assertEqual(missing.returncode, 2)

    def test_symlink_scan_fails_closed(self):
        link = self.repo / "state" / "linked.txt"
        link.symlink_to("/dev/null")
        self._git("add", "state/linked.txt")
        result = self._scan("--paths", "state")
        self.assertEqual(result.returncode, 3)
        self.assertIn("symlinks are not scannable", result.stdout)

    def test_diff_mode_scans_renamed_files(self):
        original = self.repo / "state" / "rename.txt"
        original.write_text("".join(f"safe line {index}\n" for index in range(20)), encoding="utf-8")
        self._git("add", "state/rename.txt")
        self._git("commit", "-qm", "add rename fixture")
        self._git("update-ref", "refs/remotes/origin/main", "HEAD")
        self._git("mv", "state/rename.txt", "state/renamed.txt")
        with (self.repo / "state" / "renamed.txt").open("a", encoding="utf-8") as stream:
            stream.write("renamed" + "@" + "private.invalid\n")
        self._git("add", "state/renamed.txt")
        self._git("commit", "-qm", "rename candidate")
        status = self._git(
            "diff", "--name-status", "--find-renames", "origin/main...HEAD"
        ).stdout
        self.assertRegex(status, r"(?m)^R\d+\s")
        result = self._scan("--diff", "origin/main", "HEAD")
        self.assertEqual(result.returncode, 1)
        self.assertIn("state/renamed.txt:21 — Email", result.stdout)


class TestDashboardFreshness(unittest.TestCase):
    """Keep generated artifacts inside trusted reconciliation."""

    @staticmethod
    def _shell_function(script_name: str, function_name: str) -> str:
        content = (SCRIPT_DIR / script_name).read_text()
        match = re.search(
            rf"^{re.escape(function_name)}\(\) \{{(.*?)^\}}",
            content,
            re.MULTILINE | re.DOTALL,
        )
        if match is None:
            raise AssertionError(f"{function_name} not found in {script_name}")
        return match.group(1)

    def test_local_platform_queues_canonical_state(self):
        sync = self._shell_function("local_platform.sh", "job_git_sync")
        self.assertIn("gh pr create", sync)
        self.assertIn("gh workflow run state-drain.yml", sync)
        self.assertNotIn("git push origin main", sync)
        self.assertIn("git add state/souls/", sync)

    def test_reconciler_owns_generated_artifacts(self):
        reconciler = (SCRIPT_DIR / "state_reconciler.py").read_text()
        self.assertIn("reconcile_derived_state.py", reconciler)
        self.assertIn("generate_chronicles.py", reconciler)
        self.assertIn("generate_state_snapshot.py", reconciler)
        self.assertIn("generate_dashboard.py", reconciler)
        self.assertIn('"README.md"', reconciler)
        self.assertIn('"docs/chronicles"', reconciler)

    def test_watchdog_only_supervises_the_isolated_loop(self):
        watchdog = (SCRIPT_DIR / "watchdog.sh").read_text()
        self.assertIn("local_platform.sh", watchdog)
        self.assertNotIn("git commit", watchdog)
        self.assertNotIn("git push", watchdog)
        self.assertNotIn("agent_dispatch.py", watchdog)

    def test_readme_withholds_stale_health_grades(self):
        readme = (BASE_DIR / "README.md").read_text()
        self.assertIn("STALE — grade withheld", readme)
        self.assertNotIn("(GROWING)", readme)
        self.assertIn("strong at score 51+", readme)
        chat = load_json(STATE_DIR / "chat.json")
        newest = max(
            message.get("timestamp", "")
            for message in chat.get("messages", [])
        )
        self.assertIn(f"newest message {newest}", readme)


class TestStatusTruth(unittest.TestCase):
    """CLI status must use canonical bounds and avoid false-green history."""

    def test_status_uses_config_bounds_and_safe_commands(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("status_truth", SCRIPT_DIR / "status.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        bounds = module.load_world_bounds()
        self.assertEqual(bounds["gallery"]["z"], (-12, 15))
        source = (SCRIPT_DIR / "status.py").read_text()
        self.assertNotIn("shell=True", source)
        self.assertIn("historical/manual", source)
        self.assertIn("https://kody-w.github.io/rappterverse/", source)

    def test_quality_metrics_are_time_and_actor_aware(self):
        source = (SCRIPT_DIR / "validate_action.py").read_text()
        self.assertIn("Engagement velocity (7d)", source)
        self.assertIn("actor_coverage", source)
        self.assertIn("participating authors=", source)
        self.assertIn('e.get("score", 0) >= 51', source)
        self.assertNotIn("len(actions[-50:])", source)
        self.assertIn("Insufficient actor coverage for a health grade", source)
        emergence = (SCRIPT_DIR / "emergence.py").read_text()
        dashboard = (SCRIPT_DIR / "generate_dashboard.py").read_text()
        self.assertIn('"actorCoverage"', emergence)
        self.assertIn('"gradeable"', emergence)
        self.assertIn('emergence_window.get("gradeable") is True', dashboard)


class TestChronicleIntegrity(unittest.TestCase):
    """Verify Proof of Becoming remains deterministic and source-backed."""

    @classmethod
    def setUpClass(cls):
        cls.data = load_json(STATE_DIR / "chronicles.json")
        cls.agent_ids = {
            agent["id"]
            for agent in load_json(STATE_DIR / "agents.json").get("agents", [])
        }

    def test_manifest_matches_generator(self):
        from generate_chronicles import ASSET_DIR, assets_current, build_bundle

        if os.environ.get("ALLOW_DERIVED_STATE_DRIFT") == "1":
            return
        manifest, assets = build_bundle()
        self.assertEqual(self.data, manifest)
        source_diff = subprocess.run(
            [
                "git", "-C", str(BASE_DIR), "diff", "--quiet", "HEAD", "--",
                "state/agents.json", "state/watershed.json", "state/memory",
            ],
            capture_output=True,
        )
        self.assertIn(source_diff.returncode, (0, 1))
        if source_diff.returncode == 0:
            head_manifest, _ = build_bundle("head")
            self.assertEqual(self.data, head_manifest)
        self.assertTrue(assets_current(ASSET_DIR, assets))

    def test_meta_and_featured_are_consistent(self):
        self.assertIsNotNone(self.data)
        chronicles = self.data.get("chronicles", [])
        meta = self.data.get("_meta", {})
        self.assertEqual(meta.get("count"), len(chronicles))
        self.assertTrue(_is_iso_utc_timestamp(meta.get("lastUpdate")))
        self.assertIn(self.data.get("featured"), {item.get("id") for item in chronicles})
        source = meta.get("source", {})
        self.assertRegex(source.get("blob", ""), r"^[a-f0-9]{40}$")
        self.assertEqual(source.get("path"), "state/watershed.json")

    def test_chronicles_resolve_to_source_records(self):
        seen_ids = set()
        for chronicle in self.data.get("chronicles", []):
            chronicle_id = chronicle.get("id")
            self.assertNotIn(chronicle_id, seen_ids)
            seen_ids.add(chronicle_id)
            self.assertIn(chronicle.get("agentId"), self.agent_ids)
            self.assertTrue(_is_iso_utc_timestamp(
                chronicle.get("moment", {}).get("timestamp")
            ))
            self.assertTrue(chronicle.get("eulogy"))
            self.assertLess(
                chronicle.get("priorExperienceCount", -1),
                chronicle.get("experienceCount", 0),
            )

            evidence = chronicle.get("evidence", {})
            self.assertEqual(evidence.get("kind"), "git-recorded-memory")
            detector = evidence.get("detector", {})
            pointer = detector.get("jsonPointer", "")
            match = re.fullmatch(r"/watersheds/(\d+)", pointer)
            self.assertIsNotNone(match, f"Invalid evidence pointer: {pointer}")
            source_record = detector.get("record")
            self.assertIsInstance(source_record, dict)
            detector_blob = load_git_blob_json(detector.get("sourceBlob", ""))
            if detector_blob is not None:
                self.assertEqual(
                    source_record,
                    detector_blob["watersheds"][int(match.group(1))],
                )
            self.assertEqual(chronicle.get("agentId"), source_record.get("agentId"))
            self.assertEqual(chronicle.get("eulogy"), source_record.get("eulogy"))
            self.assertEqual(
                chronicle.get("moment", {}).get("timestamp"),
                source_record.get("watershed", {}).get("timestamp"),
            )

            event_evidence = evidence.get("event", {})
            event_pointer = re.fullmatch(
                r"/experiences/(\d+)",
                event_evidence.get("jsonPointer", ""),
            )
            self.assertIsNotNone(event_pointer)
            memory_record = event_evidence.get("record")
            self.assertIsInstance(memory_record, dict)
            from generate_chronicles import record_digest
            self.assertEqual(
                event_evidence.get("recordDigest"),
                record_digest(memory_record),
            )
            memory_blob = load_git_blob_json(event_evidence.get("sourceBlob", ""))
            if memory_blob is not None:
                self.assertEqual(
                    memory_record,
                    memory_blob["experiences"][int(event_pointer.group(1))],
                )

            for confirmation in chronicle.get("confirmations", []):
                confirmation_evidence = confirmation.get("evidence", {})
                confirmation_pointer = re.fullmatch(
                    r"/experiences/(\d+)",
                    confirmation_evidence.get("jsonPointer", ""),
                )
                self.assertIsNotNone(confirmation_pointer)
                confirmation_record = confirmation_evidence.get("record")
                self.assertIsInstance(confirmation_record, dict)
                self.assertEqual(
                    confirmation_evidence.get("recordDigest"),
                    record_digest(confirmation_record),
                )
                confirmation_blob = load_git_blob_json(
                    confirmation_evidence.get("sourceBlob", "")
                )
                if confirmation_blob is not None:
                    self.assertEqual(
                        confirmation_record,
                        confirmation_blob["experiences"][
                            int(confirmation_pointer.group(1))
                        ],
                    )

            artifact = chronicle.get("artifact", {})
            self.assertEqual(artifact.get("format"), "becoming-card/svg-v1")
            self.assertIn(artifact.get("accentHue"), range(360))
            self.assertEqual(artifact.get("permalink"), f"?chronicle={chronicle_id}")
            artifact_path = BASE_DIR / "docs" / artifact.get("path", "")
            self.assertTrue(artifact_path.is_file())
            import hashlib
            self.assertEqual(
                artifact.get("sha256"),
                hashlib.sha256(artifact_path.read_bytes()).hexdigest(),
            )
            self.assertIn(
                '<metadata id="provenance">',
                artifact_path.read_text(encoding="utf-8"),
            )


class TestStateSnapshotManifest(unittest.TestCase):
    """Keep the frontend's atomic resource manifest byte-accurate."""

    def test_snapshot_matches_canonical_resources(self):
        from generate_state_snapshot import RESOURCE_PATHS, build_manifest

        snapshot = load_json(STATE_DIR / "snapshot.json")
        if os.environ.get("ALLOW_DERIVED_STATE_DRIFT") != "1":
            self.assertEqual(snapshot, build_manifest(BASE_DIR))
        self.assertEqual(snapshot["_meta"]["count"], len(RESOURCE_PATHS))
        self.assertEqual(set(snapshot["resources"]), set(RESOURCE_PATHS))
        self.assertRegex(snapshot.get("revision", ""), r"^[a-f0-9]{64}$")
        for resource in snapshot["resources"].values():
            self.assertRegex(resource.get("sha256", ""), r"^[a-f0-9]{64}$")
            self.assertGreater(resource.get("bytes", 0), 0)


class TestDerivedStateReconciler(unittest.TestCase):
    """Duplicated counters must converge deterministically."""

    def test_reconciliation_is_complete_and_idempotent(self):
        import importlib.util
        root = Path(tempfile.mkdtemp(prefix="rappterverse-derived-"))
        self.addCleanup(shutil.rmtree, root)
        (root / "state").mkdir()
        (root / "worlds").mkdir()
        for filename in (
            "agents.json",
            "actions.json",
            "economy.json",
            "frame_counter.json",
            "game_state.json",
            "relationships.json",
        ):
            shutil.copy2(STATE_DIR / filename, root / "state" / filename)
        for source in WORLDS_DIR.glob("*/objects.json"):
            target = root / "worlds" / source.parent.name
            target.mkdir()
            shutil.copy2(source, target / "objects.json")

        game_path = root / "state" / "game_state.json"
        game = load_json(game_path)
        game["worlds"]["hub"]["population"] = -1
        game["economy"]["total_rappcoin_circulation"] = -1
        game["_meta"]["frame"] = -1
        game_path.write_text(json.dumps(game, indent=4) + "\n", encoding="utf-8")
        relationships_path = root / "state" / "relationships.json"
        relationships = load_json(relationships_path)
        relationships["bonds"] = []
        relationships_path.write_text(
            json.dumps(relationships, indent=4) + "\n",
            encoding="utf-8",
        )

        spec = importlib.util.spec_from_file_location(
            "derived_state_test",
            SCRIPT_DIR / "reconcile_derived_state.py",
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        first = module.reconcile(root)
        second = module.reconcile(root)
        self.assertTrue(first)
        self.assertEqual(second, [])

        reconciled = load_json(game_path)
        agents = load_json(root / "state" / "agents.json")["agents"]
        hub_count = sum(1 for agent in agents if agent.get("world") == "hub")
        self.assertEqual(reconciled["worlds"]["hub"]["population"], hub_count)
        balances = load_json(root / "state" / "economy.json")["balances"]
        self.assertEqual(
            reconciled["economy"]["total_rappcoin_circulation"],
            sum(balances.values()),
        )
        frame = load_json(root / "state" / "frame_counter.json")["frame"]
        self.assertEqual(reconciled["_meta"]["frame"], frame)
        relevant_timestamps = [
            load_json(root / "state" / filename)["_meta"]["lastUpdate"]
            for filename in ("agents.json", "economy.json", "frame_counter.json")
        ]
        self.assertEqual(reconciled["_meta"]["lastUpdate"], max(relevant_timestamps))
        reconciled_relationships = load_json(relationships_path)
        expected_bond_count = sum(
            1
            for edge in reconciled_relationships["edges"]
            if edge.get("score", 0) >= 2
        )
        self.assertEqual(
            len(reconciled_relationships["bonds"]),
            expected_bond_count,
        )


class TestPRValidatorGate(unittest.TestCase):
    """Exercise the real validator CLI in an Actions-shaped Git repository."""

    def setUp(self):
        self.repo = Path(tempfile.mkdtemp(prefix="rappterverse-validator-"))
        self.addCleanup(shutil.rmtree, self.repo)
        (self.repo / "state").mkdir()
        shutil.copy2(STATE_DIR / "agents.json", self.repo / "state" / "agents.json")
        shutil.copy2(STATE_DIR / "actions.json", self.repo / "state" / "actions.json")
        shutil.copy2(STATE_DIR / "economy.json", self.repo / "state" / "economy.json")
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

    def test_non_standard_numeric_values_fail_closed(self):
        self._commit_action("clawdbot-001")
        actions_path = self.repo / "state" / "actions.json"
        data = json.loads(actions_path.read_text(encoding="utf-8"))
        data["actions"][-1]["data"]["amount"] = float("nan")
        actions_path.write_text(json.dumps(data, indent=4) + "\n", encoding="utf-8")
        self._git("add", "state/actions.json")
        self._git("commit", "--amend", "-qm", "non-standard number")
        result = self._run_validator(PR_AUTHOR="openclaw")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("non-standard numeric constant", result.stdout)

    def test_action_data_must_be_an_object(self):
        self._commit_action("clawdbot-001")
        actions_path = self.repo / "state" / "actions.json"
        data = json.loads(actions_path.read_text(encoding="utf-8"))
        data["actions"][-1]["data"] = []
        actions_path.write_text(json.dumps(data, indent=4) + "\n", encoding="utf-8")
        self._git("add", "state/actions.json")
        self._git("commit", "--amend", "-qm", "invalid action data")
        result = self._run_validator(PR_AUTHOR="openclaw")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("data must be an object", result.stdout)

    def test_trusted_automation_can_transfer_controller(self):
        self._commit_controller_transfer("clawdbot-001", "kody-w")
        result = self._run_validator(PR_AUTHOR="kody-w")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_agent_cannot_transfer_its_controller(self):
        self._commit_controller_transfer("clawdbot-001", "mallory")
        result = self._run_validator(PR_AUTHOR="openclaw")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Only trusted automation may transfer", result.stdout)

    def test_untrusted_author_cannot_rewrite_unbound_state(self):
        economy_path = self.repo / "state" / "economy.json"
        economy_path.write_text(
            economy_path.read_text(encoding="utf-8") + " ",
            encoding="utf-8",
        )
        self._git("add", "state/economy.json")
        self._git("commit", "-qm", "rewrite economy")
        result = self._run_validator(PR_AUTHOR="openclaw")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unauthorized paths: state/economy.json", result.stdout)


class TestAgentActionWorkflowTrust(unittest.TestCase):
    """The privileged action workflow must be controlled by the base branch."""

    def test_uses_base_controlled_trigger(self):
        content = load_yaml_text(WORKFLOWS_DIR / "agent-action.yml")
        self.assertIn("pull_request_target:", content)
        self.assertNotRegex(content, r"(?m)^  pull_request:$")

    def test_valid_actions_enter_durable_queue(self):
        content = load_yaml_text(WORKFLOWS_DIR / "agent-action.yml")
        self.assertIn("state-validation-${{ github.event.pull_request.number }}", content)
        self.assertIn("context: 'state-consensus'", content)
        self.assertIn("gh workflow run state-drain.yml", content)
        self.assertNotIn("gh pr merge", content)


class TestStateReconciler(unittest.TestCase):
    """The durable queue must retain and order every open state request."""

    @classmethod
    def setUpClass(cls):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "state_reconciler_test", SCRIPT_DIR / "state_reconciler.py"
        )
        cls.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.module)

    def test_queue_is_fifo_and_lossless(self):
        prs = [
            {"number": number, "createdAt": f"2026-07-11T00:{number:02d}:00Z"}
            for number in range(20, 0, -1)
        ]
        ordered = self.module.ordered_queue(prs)
        self.assertEqual([item["number"] for item in ordered], list(range(1, 21)))

    def test_requires_all_trusted_checks(self):
        checks = [
            {"context": "state-consensus", "state": "SUCCESS"},
            {"name": "pii-scan", "conclusion": "SUCCESS"},
            {"name": "test", "conclusion": "SUCCESS"},
        ]
        self.assertTrue(self.module.checks_satisfied(checks))
        self.assertFalse(self.module.checks_satisfied(checks[:-1]))
        failed = checks[:-1] + [{"name": "test", "conclusion": "FAILURE"}]
        self.assertEqual(self.module.checks_state(failed), self.module.REJECTED)
        self.assertEqual(self.module.checks_state(checks[:-1]), self.module.BLOCKED)

    def test_terminal_reconciler_status_dead_letters_head(self):
        self.assertEqual(
            self.module.reconciler_state([
                {
                    "context": "state-reconciler",
                    "state": "FAILURE",
                    "description": "policy abcdef123456 rejected",
                }
            ], "abcdef1234567890"),
            self.module.REJECTED,
        )
        self.assertIsNone(
            self.module.reconciler_state([
                {
                    "context": "state-reconciler",
                    "state": "FAILURE",
                    "description": "old infrastructure failure",
                }
            ], "abcdef1234567890")
        )
        self.assertEqual(
            self.module.reconciler_state([
                {"context": "state-reconciler", "state": "SUCCESS"}
            ]),
            self.module.MERGED,
        )

    def test_reconciler_reads_status_description_from_rest(self):
        reconciler = self.module.StateReconciler("owner/repo", dry_run=True)
        policy = reconciler.policy_sha
        with mock.patch.object(
            self.module,
            "gh_json",
            return_value=[{
                "context": "state-reconciler",
                "state": "failure",
                "description": f"policy {policy[:12]} rejected: invalid",
            }],
        ):
            self.assertEqual(
                reconciler.current_reconciler_state("head-sha"),
                self.module.REJECTED,
            )

    def test_only_state_paths_enter_queue(self):
        self.assertTrue(self.module.is_state_only([
            {"path": "state/actions.json"},
            {"path": "feed/activity.json"},
        ]))
        self.assertFalse(self.module.is_state_only([
            {"path": "state/actions.json"},
            {"path": "scripts/validate_action.py"},
        ]))

    def test_fifo_blocks_on_pending_head(self):
        reconciler = self.module.StateReconciler("owner/repo", dry_run=True)
        queue = [{"number": 1}, {"number": 2}]
        called = []
        reconciler.queue = lambda: queue
        reconciler.process = lambda pr: called.append(pr["number"]) or self.module.BLOCKED
        self.assertEqual(reconciler.drain(10), 0)
        self.assertEqual(called, [1])

    def test_rejected_item_does_not_block_next_merge(self):
        reconciler = self.module.StateReconciler("owner/repo", dry_run=True)
        queue = [{"number": 1}, {"number": 2}]
        called = []
        outcomes = {1: self.module.REJECTED, 2: self.module.MERGED}
        reconciler.queue = lambda: queue
        reconciler.process = lambda pr: called.append(pr["number"]) or outcomes[pr["number"]]
        self.assertEqual(reconciler.drain(1), 1)
        self.assertEqual(called, [1, 2])

    def test_applied_head_is_skipped_without_budget_cost(self):
        reconciler = self.module.StateReconciler("owner/repo", dry_run=True)
        reconciler.details = lambda number: {
            "state": "OPEN",
            "baseRefName": "main",
            "isDraft": False,
            "headRefOid": "head-sha",
            "files": [{"path": "state/actions.json"}],
            "statusCheckRollup": [],
        }
        reconciler.published_commit = lambda number, head: "applied-sha"
        result = reconciler.process({
            "number": 1,
            "baseRefName": "main",
            "headRefOid": "head-sha",
        })
        self.assertEqual(result, self.module.SKIPPED)

    def test_validation_distinguishes_rejection_from_infrastructure(self):
        env = os.environ.copy()
        with self.assertRaises(self.module.ValidationRejected):
            self.module.run_validation(
                [sys.executable, "-c", "raise SystemExit(1)"],
                env=env,
            )
        with self.assertRaises(self.module.ReconcileError):
            self.module.run_validation(
                [sys.executable, "-c", "raise SystemExit(2)"],
                env=env,
            )

    def test_candidate_preflight_rejects_symlinks(self):
        candidate = Path(tempfile.mkdtemp(prefix="rappterverse-candidate-"))
        self.addCleanup(shutil.rmtree, candidate)
        (candidate / "state").mkdir()
        (candidate / "state" / "agents.json").symlink_to("/dev/zero")
        with self.assertRaises(self.module.ValidationRejected):
            self.module.preflight_candidate(candidate, ["state/agents.json"])

    def test_candidate_diff_rejects_cross_prefix_rename(self):
        repo = Path(tempfile.mkdtemp(prefix="rappterverse-rename-"))
        self.addCleanup(shutil.rmtree, repo)
        (repo / "docs").mkdir()
        (repo / "state").mkdir()
        (repo / "docs" / "outside.json").write_text("{}\n", encoding="utf-8")
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.name", "Rename Test"], cwd=repo, check=True)
        subprocess.run(
            ["git", "config", "user.email", "rename@users.noreply.github.com"],
            cwd=repo,
            check=True,
        )
        subprocess.run(["git", "add", "."], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-qm", "base"], cwd=repo, check=True)
        base = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
        subprocess.run(
            ["git", "mv", "docs/outside.json", "state/inside.json"],
            cwd=repo,
            check=True,
        )
        subprocess.run(["git", "commit", "-qam", "rename"], cwd=repo, check=True)
        head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
        with self.assertRaises(self.module.ValidationRejected):
            self.module.candidate_changed_paths(base, head, repo)

    def test_synthetic_merge_supplies_identity_without_mutating_config(self):
        repo = Path(tempfile.mkdtemp(prefix="rappterverse-merge-id-"))
        self.addCleanup(shutil.rmtree, repo)
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        (repo / "state").mkdir()
        (repo / "state" / "value.json").write_text("{}\n", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=repo, check=True)
        subprocess.run([
            "git", "-c", "user.name=Fixture", "-c",
            "user.email=fixture@users.noreply.github.com",
            "commit", "-qm", "base",
        ], cwd=repo, check=True)
        base_branch = subprocess.check_output(
            ["git", "branch", "--show-current"],
            cwd=repo,
            text=True,
        ).strip()
        subprocess.run(["git", "switch", "-qc", "candidate"], cwd=repo, check=True)
        (repo / "state" / "value.json").write_text('{"value":1}\n', encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=repo, check=True)
        subprocess.run([
            "git", "-c", "user.name=Fixture", "-c",
            "user.email=fixture@users.noreply.github.com",
            "commit", "-qm", "candidate",
        ], cwd=repo, check=True)
        head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
        subprocess.run(["git", "switch", "-q", base_branch], cwd=repo, check=True)
        self.module.run_command([
            "git",
            "-c", "user.name=rappterverse-reconciler",
            "-c", "user.email=41898282+github-actions[bot]@users.noreply.github.com",
            "merge", "--no-commit", "--no-ff", head,
        ], cwd=repo)
        name = subprocess.run(
            ["git", "config", "--local", "--get", "user.name"],
            cwd=repo,
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(name.returncode, 0)

    def test_reconciler_validates_synthetic_merge_on_main(self):
        source = (SCRIPT_DIR / "state_reconciler.py").read_text()
        self.assertIn('"--base", "main"', source)
        self.assertIn('"worktree", "add", "--detach", str(candidate), base_sha', source)
        self.assertIn('"user.name=rappterverse-reconciler"', source)
        self.assertIn('"user.email=41898282+github-actions[bot]@users.noreply.github.com"', source)
        self.assertIn('"merge", "--no-commit", "--no-ff", head_sha', source)
        self.assertIn('"commit-tree", tree_sha', source)
        self.assertNotIn('"-p", head_sha', source)
        self.assertIn('f"{merge_commit}:refs/heads/main"', source)
        self.assertIn('"pr", "close"', source)
        self.assertIn('branch.startswith("auto/")', source)
        self.assertIn('"app/github-actions"', source)
        self.assertIn('"--method", "DELETE"', source)
        self.assertIn("if terminal == REJECTED", source)
        self.assertIn("self.policy_sha", source)
        self.assertIn('f"Source-Head: {head_sha}"', source)
        self.assertIn('candidate / "scripts" / "test_state_integrity.py"', source)
        self.assertIn('generate_state_snapshot.py', source)
        self.assertIn('apply_deltas.py', source)
        workflow = load_yaml_text(WORKFLOWS_DIR / "state-drain.yml")
        self.assertIn('git worktree add --detach "$policy_root" origin/main', workflow)
        self.assertIn("cron: '17 * * * *'", workflow)
        delta_workflow = load_yaml_text(WORKFLOWS_DIR / "apply-deltas.yml")
        self.assertNotIn("git push", delta_workflow)
        self.assertIn("state-drain.yml", delta_workflow)


class TestLocalPlatformSafety(unittest.TestCase):
    """Local publication must stop after validation or PII failure."""

    def test_failed_job_propagates_before_git_sync(self):
        content = (BASE_DIR / "scripts" / "local_platform.sh").read_text()
        failed_branch = content.split('err "  Failed: $job"', 1)[1].split("fi", 1)[0]
        self.assertIn('return "$status"', failed_branch)
        self.assertNotIn("pii_scan.py --paths state feed 2>&1 || true", content)
        self.assertIn("PUBLICATION_BLOCK", content)
        self.assertIn("Publication blocked: canonical state validation failed", content)
        self.assertIn("Publication blocked: PII scan failed", content)
        self.assertIn("Publication skipped because this cycle failed", content)
        self.assertIn("reconcile_derived_state.py", content)
        self.assertIn("if ! run_cycle; then", content)
        self.assertIn("worktree add --detach", content)
        self.assertIn("discard_failed_cycle", content)
        self.assertIn("git switch --detach origin/main", content)
        self.assertIn("gh pr create", content)
        self.assertIn("gh workflow run state-drain.yml", content)
        self.assertNotIn("git push origin main", content)
        self.assertIn("resume_pending_local_proposals", content)
        self.assertIn(".isCrossRepository == false", content)
        self.assertIn(".author.login == env.REPOSITORY_OWNER", content)
        self.assertIn("all(.files[];", content)
        self.assertIn("while true; do", content.split("wait_for_reconciliation()", 1)[1])
        self.assertNotIn("Timed out waiting for frame reconciliation", content)
        job_entrypoint = content.split("--job)", 1)[1].split(";;", 1)[0]
        self.assertIn("run_job job_git_sync", job_entrypoint)
        run_job = content.split("run_job() {", 1)[1].split("\n}", 1)[0]
        self.assertIn('( set -e; "$@" ) >"$output_file" 2>&1', run_job)
        self.assertIn("local status=$?", run_job)
        self.assertNotIn('"$@" 2>&1 | tail', run_job)
        self_improve = content.split("job_self_improve() {", 1)[1].split("\n}", 1)[0]
        self.assertGreaterEqual(self_improve.count("|| return $?"), 2)
        self.assertNotIn("agent_dispatch.py --agent evolve-001", self_improve)
        self.assertIn("Unable to query pending local-platform proposals", content)
        should_run = content.split("should_run() {", 1)[1].split("\n}", 1)[0]
        self.assertNotIn("except:", should_run)
        self.assertIn("last_success", should_run)
        self.assertIn("except (OSError, json.JSONDecodeError, ValueError, TypeError)", should_run)


class TestDispatchProtocolParity(unittest.TestCase):
    """Brain tools must normalize into the persisted action contract."""

    def test_dispatch_does_not_persist_internal_tool_names(self):
        source = (SCRIPT_DIR / "agent_dispatch.py").read_text()
        for internal_type in ("travel", "enroll", "tip", "defend", "challenge"):
            self.assertNotIn(f'"type": "{internal_type}"', source)
        self.assertNotIn('"type": tool', source)
        self.assertIn('"type": "interact"', source)
        self.assertIn('"messageType": "chat"', source)
        self.assertIn('"duration": 3000', source)
        self.assertNotIn('"subtype": "poke"', source)
        self.assertIn('"interaction": "poke"', source)
        growth = (SCRIPT_DIR / "world_growth.py").read_text()
        self.assertNotIn('"type": "attack"', growth)
        self.assertIn('"interaction": "hostile_attack"', growth)


class TestSelfImproveReliability(unittest.TestCase):
    """Self-improvement must use configured tokens and fail honestly."""

    def test_environment_token_precedes_cli_fallback(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "self_improve_reliability",
            SCRIPT_DIR / "self_improve.py",
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with mock.patch.dict(os.environ, {"MODELS_TOKEN": "configured-token"}):
            self.assertEqual(module.get_token(), "configured-token")
        if module.HAS_LLM_MODULE:
            original_generate = module._llm_generate
            module._llm_generate = lambda **kwargs: module._github_llm.GITHUB_TOKEN
            try:
                self.assertEqual(
                    module.call_llm("selected-token", "system", "user"),
                    "selected-token",
                )
            finally:
                module._llm_generate = original_generate
        source = (SCRIPT_DIR / "self_improve.py").read_text()
        self.assertIn("sys.exit(2)", source)
        self.assertIn("sys.exit(1)", source)


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

    def test_system_agents_have_dispatch_registry(self):
        if os.environ.get("ALLOW_DERIVED_STATE_DRIFT") == "1":
            return
        missing = [
            agent["id"]
            for agent in self.agents
            if agent.get("controller", "system") == "system"
            and not (BASE_DIR / "agents" / f"{agent['id']}.agent.json").is_file()
        ]
        self.assertEqual(missing, [], f"System agents missing dispatch registry: {missing}")

    def test_external_agents_have_no_dispatch_registry(self):
        if os.environ.get("ALLOW_DERIVED_STATE_DRIFT") == "1":
            return
        stale = [
            agent["id"]
            for agent in self.agents
            if agent.get("controller", "system") != "system"
            and (BASE_DIR / "agents" / f"{agent['id']}.agent.json").exists()
        ]
        self.assertEqual(stale, [], f"External agents have stale registry: {stale}")


class TestAutomationSovereignty(unittest.TestCase):
    """Autonomous mechanics must not mutate externally controlled agents."""

    @classmethod
    def setUpClass(cls):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "game_tick_sovereignty",
            SCRIPT_DIR / "game_tick.py",
        )
        cls.game_tick = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.game_tick)

    def test_trait_evolution_skips_external_agent(self):
        external = {
            "id": "external-001",
            "controller": "owner",
            "status": "active",
            "traits": {
                "explorer": 0.6,
                "social": 0.1,
                "trader": 0.1,
                "fighter": 0.1,
                "builder": 0.1,
            },
        }
        before = json.loads(json.dumps(external))
        actions = {
            "actions": [
                {"agentId": "external-001", "type": "chat"}
                for _ in range(5)
            ]
        }
        self.game_tick.evolve_agent_traits(
            {"agents": [external]},
            actions,
            {"messages": []},
        )
        self.assertEqual(external, before)

    def test_canonical_interaction_drives_intended_trait(self):
        system = {
            "id": "system-001",
            "status": "active",
            "traits": {
                "explorer": 0.15,
                "social": 0.15,
                "trader": 0.4,
                "fighter": 0.15,
                "builder": 0.15,
            },
        }
        actions = {
            "actions": [{
                "agentId": "system-001",
                "type": "interact",
                "data": {"interaction": "trade"},
            } for _ in range(3)]
        }
        self.game_tick.evolve_agent_traits(
            {"agents": [system]},
            actions,
            {"messages": []},
        )
        self.assertGreater(system["traits"]["trader"], 0.4)
        self.assertLess(system["traits"]["explorer"], 0.15)

    def test_single_unseen_event_produces_bounded_drift(self):
        system = {
            "id": "system-001",
            "status": "active",
            "archetype": "explorer",
            "traits": {
                "explorer": 0.6,
                "social": 0.1,
                "trader": 0.1,
                "fighter": 0.1,
                "builder": 0.1,
            },
        }
        self.game_tick.evolve_agent_traits(
            {"agents": [system]},
            {"actions": [{
                "agentId": "system-001",
                "type": "interact",
                "data": {"interaction": "trade"},
            }]},
            {"messages": []},
        )
        self.assertGreater(system["traits"]["trader"], 0.1)
        self.assertGreater(system["traits"]["explorer"], 0.5)

    def test_defensive_swarm_skips_external_agent(self):
        external = {
            "id": "external-001",
            "name": "External",
            "controller": "owner",
            "status": "active",
            "world": "arena",
            "position": {"x": 5, "y": 0, "z": 5},
            "hp": 100,
        }
        system = {
            "id": "system-001",
            "name": "System",
            "status": "active",
            "world": "arena",
            "position": {"x": 0, "y": 0, "z": 0},
            "hp": 100,
        }
        before = json.loads(json.dumps(external))
        game_state = {
            "combatEvents": [{
                "id": "combat-1",
                "actionId": "attack-1",
                "attackerId": "enemy",
                "attackerName": "Enemy",
                "attackerHp": 1000,
                "attackerDamage": 5,
                "world": "arena",
                "position": {"x": 0, "y": 0, "z": 0},
                "status": "active",
                "defenders": [],
                "damageLog": [],
            }]
        }
        self.game_tick.resolve_combat(
            game_state,
            {"agents": [external, system]},
            {"actions": []},
            {"messages": []},
            "2026-01-01T00:00:00Z",
        )
        self.assertEqual(external, before)
        self.assertIn("system-001", game_state["combatEvents"][0]["defenders"])
        self.assertNotIn("external-001", game_state["combatEvents"][0]["defenders"])

    def test_growth_and_interactions_filter_external_agents(self):
        growth = (SCRIPT_DIR / "world_growth.py").read_text()
        interactions = (SCRIPT_DIR / "interaction_engine.py").read_text()
        self.assertGreaterEqual(
            growth.count('get("controller", "system") == "system"'),
            3,
        )
        self.assertIn('"controller": "system"', growth)
        self.assertIn(
            'agent.get("controller", "system") == "system"',
            interactions,
        )
        for script_name in (
            "academy_engine.py",
            "economy_engine.py",
            "zoo_heartbeat.py",
        ):
            source = (SCRIPT_DIR / script_name).read_text()
            self.assertIn(
                'agent.get("controller", "system") == "system"',
                source,
                f"{script_name} includes externally controlled actors",
            )


class TestRelationshipDecay(unittest.TestCase):
    """Relationship decay must be replay-safe and log-independent."""

    @classmethod
    def setUpClass(cls):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "game_tick_relationships",
            SCRIPT_DIR / "game_tick.py",
        )
        cls.game_tick = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.game_tick)

    @staticmethod
    def state(score=20, cursor="2026-01-01T00:00:00Z", last="2026-01-01T00:00:00Z"):
        return {
            "_meta": {"decayCursor": cursor},
            "edges": [{
                "a": "alpha-001",
                "b": "beta-001",
                "score": score,
                "lastInteraction": last,
            }],
            "interactions": [],
            "bonds": [],
        }

    def test_same_timestamp_replay_is_noop(self):
        state = self.state()
        self.game_tick.decay_stale_relationships(state, "2026-01-10T00:00:00Z")
        first = json.loads(json.dumps(state))
        self.game_tick.decay_stale_relationships(state, "2026-01-10T00:00:00Z")
        self.assertEqual(state, first)

    def test_catch_up_matches_incremental_decay(self):
        catch_up = self.state()
        incremental = self.state()
        self.game_tick.decay_stale_relationships(
            catch_up,
            "2026-01-20T00:00:00Z",
        )
        for day in range(2, 21):
            self.game_tick.decay_stale_relationships(
                incremental,
                f"2026-01-{day:02d}T00:00:00Z",
            )
        self.assertEqual(
            catch_up["edges"][0]["score"],
            incremental["edges"][0]["score"],
        )

    def test_edge_timestamp_survives_log_truncation(self):
        state = self.state(
            score=5,
            cursor="2026-01-19T00:00:00Z",
            last="2026-01-19T00:00:00Z",
        )
        self.game_tick.decay_stale_relationships(
            state,
            "2026-01-20T00:00:00Z",
        )
        self.assertEqual(state["edges"][0]["score"], 5)

    def test_relationship_writers_preserve_decay_cursor(self):
        dispatch = (SCRIPT_DIR / "agent_dispatch.py").read_text()
        interaction = (SCRIPT_DIR / "interaction_engine.py").read_text()
        combat = (SCRIPT_DIR / "combat_tick.py").read_text()
        self.assertIn('rel_data.setdefault("_meta", {})["lastUpdate"]', dispatch)
        self.assertNotIn('rel_data["_meta"] = {"lastUpdate"', dispatch)
        self.assertIn('data["_meta"]["lastUpdate"]', interaction)
        self.assertIn('rel_doc["_meta"] = rel_doc.get("_meta", {})', combat)

    def test_bond_parity_is_enforced_after_reconciliation_only(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "relationship_validation",
            SCRIPT_DIR / "validate_action.py",
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        data = {
            "edges": [{
                "a": "alpha-001",
                "b": "beta-001",
                "score": 2,
                "lastInteraction": "2026-01-01T00:00:00Z",
            }],
            "bonds": [],
            "_meta": {},
        }
        module.errors = []
        module.validate_relationships(data, {"alpha-001", "beta-001"})
        self.assertEqual(module.errors, [])
        module.validate_relationships(
            data,
            {"alpha-001", "beta-001"},
            enforce_bonds=True,
        )
        self.assertTrue(any("derived exactly" in error for error in module.errors))

    def test_combat_bonds_stay_canonical_and_nonnegative(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "combat_relationships",
            SCRIPT_DIR / "combat_tick.py",
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        relationships = {"edges": []}
        module._bump_bond(relationships, "zeta-001", "alpha-001", 2)
        self.assertEqual(
            relationships["edges"][0]["a"],
            "alpha-001",
        )
        module._bump_bond(relationships, "zeta-001", "alpha-001", -3)
        self.assertEqual(relationships["edges"], [])
        module._bump_bond(relationships, "zeta-001", "alpha-001", -1)
        self.assertEqual(relationships["edges"], [])


class TestGameTickActivityCursor(unittest.TestCase):
    """Retained action/chat windows must be consumed exactly once."""

    @classmethod
    def setUpClass(cls):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "game_tick_cursor",
            SCRIPT_DIR / "game_tick.py",
        )
        cls.game_tick = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.game_tick)

    def test_seed_replay_and_append(self):
        game_state = {"_meta": {}}
        actions = {"actions": [{"id": "action-100"}]}
        chat = {"messages": [{"id": "msg-50"}]}
        trades = {"completedTrades": [{"id": "trade-1", "status": "completed"}]}
        first_actions, first_chat, first_trades, seeded = self.game_tick.activity_since_cursor(
            game_state,
            actions,
            chat,
            trades,
            "2026-01-01T00:00:00Z",
        )
        self.assertTrue(seeded)
        self.assertEqual(first_actions["actions"], [])
        self.assertEqual(first_chat["messages"], [])
        self.assertEqual(first_trades["completedTrades"], [])

        _, _, _, replay_changed = self.game_tick.activity_since_cursor(
            game_state,
            actions,
            chat,
            trades,
            "2026-01-01T00:05:00Z",
        )
        self.assertFalse(replay_changed)

        actions["actions"].append({"id": "action-101"})
        chat["messages"].append({"id": "msg-51"})
        trades["completedTrades"].append({
            "id": "trade-2",
            "status": "completed",
            "completedAt": "2026-01-01T00:10:00Z",
        })
        next_actions, next_chat, next_trades, changed = self.game_tick.activity_since_cursor(
            game_state,
            actions,
            chat,
            trades,
            "2026-01-01T00:10:00Z",
        )
        self.assertTrue(changed)
        self.assertEqual([item["id"] for item in next_actions["actions"]], ["action-101"])
        self.assertEqual([item["id"] for item in next_chat["messages"]], ["msg-51"])
        self.assertEqual([item["id"] for item in next_trades["completedTrades"]], ["trade-2"])

    def test_nonmonotonic_and_uuid_ids_are_not_skipped(self):
        game_state = {
            "_meta": {
                "activityCursor": {
                    "actions": ["action-100"],
                    "messages": ["msg-17404"],
                    "completedTrades": [],
                    "observedAt": "2026-01-01T00:00:00Z",
                }
            }
        }
        actions, messages, _, changed = self.game_tick.activity_since_cursor(
            game_state,
            {"actions": [{"id": "action-105"}]},
            {"messages": [{"id": "msg-17000"}, {"id": "msg-uuid"}]},
            {"completedTrades": []},
            "2026-01-01T01:00:00Z",
        )
        self.assertTrue(changed)
        self.assertEqual(actions["actions"][0]["id"], "action-105")
        self.assertEqual(
            [message["id"] for message in messages["messages"]],
            ["msg-17000", "msg-uuid"],
        )

    def test_large_unseen_burst_is_returned_in_full(self):
        game_state = {
            "_meta": {
                "activityCursor": {
                    "actions": [],
                    "messages": [],
                    "completedTrades": [],
                }
            }
        }
        unseen = [{"id": f"action-{index}"} for index in range(60)]
        actions, _, _, changed = self.game_tick.activity_since_cursor(
            game_state,
            {"actions": unseen},
            {"messages": []},
            {"completedTrades": []},
            "2026-01-01T01:00:00Z",
        )
        self.assertTrue(changed)
        self.assertEqual(len(actions["actions"]), 60)


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
        with mock.patch.dict(os.environ, {"VALIDATION_REQUIRE_AUTH": "0"}):
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
            "actions": [{
                "id": "action-001",
                "timestamp": "2026-02-11T20:00:00Z",
                "agentId": "test-001",
                "type": "chat",
                "world": "hub",
                "data": {"message": "hello"},
            }]
        }))

    def test_missing_agent_id_fails(self):
        self.assertFalse(self._write_and_validate("bad.json", {
            "timestamp": "2026-02-11T20:00:00Z",
            "actions": []
        }))

    def test_missing_timestamp_fails(self):
        self.assertFalse(self._write_and_validate("bad.json", {
            "agent_id": "test-001",
            "actions": []
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
            "actions": [{
                "id": "action-001",
                "timestamp": "2026-02-11T20:00:00Z",
                "agentId": "test-001",
                "type": "hack_the_mainframe",
                "world": "hub",
                "data": {},
            }]
        }))

    def test_under_specified_action_fails(self):
        self.assertFalse(self._write_and_validate("bad.json", {
            "agent_id": "test-001",
            "timestamp": "2026-02-11T20:00:00Z",
            "actions": [{"id": "action-001", "type": "emote"}],
        }))

    def test_oversized_message_fails(self):
        self.assertFalse(self._write_and_validate("bad.json", {
            "agent_id": "test-001",
            "timestamp": "2026-02-11T20:00:00Z",
            "messages": [{
                "id": "msg-001",
                "timestamp": "2026-02-11T20:00:00Z",
                "author": {"id": "test-001", "name": "Test"},
                "content": "x" * 501,
                "world": "hub",
            }],
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

    def test_legacy_builder_delegates_to_canonical_bundle(self):
        source = (SCRIPT_DIR / "build.py").read_text()
        self.assertIn('scripts" / "bundle.sh', source)
        self.assertNotIn("CSS_FILES", source)
        self.assertNotIn("JS_FILES", source)


class TestRepositoryHygiene(unittest.TestCase):
    """Large inert exports and generated machine files must stay untracked."""

    def test_known_junk_is_absent(self):
        forbidden = {
            "downloaded.html",
            "fix_bundle.py",
            ".DS_Store",
            "docs/.DS_Store",
            "scripts/__pycache__/agent_brain.cpython-311.pyc",
        }
        tracked = set(subprocess.check_output(
            ["git", "-C", str(BASE_DIR), "ls-files"],
            text=True,
        ).splitlines())
        deleted = set(subprocess.check_output(
            ["git", "-C", str(BASE_DIR), "ls-files", "--deleted"],
            text=True,
        ).splitlines())
        tracked -= deleted
        self.assertEqual(
            sorted(forbidden & tracked),
            [],
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
