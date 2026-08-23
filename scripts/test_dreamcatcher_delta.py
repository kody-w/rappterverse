#!/usr/bin/env python3
"""Focused tests for the vendored Dreamcatcher worktree-delta protocol."""

from __future__ import annotations

import copy
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dreamcatcher_delta as dp  # noqa: E402


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise AssertionError(result.stderr or result.stdout)
    return result.stdout.strip()


class DreamcatcherDeltaTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="rappterverse-dreamcatcher-"))
        self.seed = self.tmp / "seed"
        self.seed.mkdir()
        _git(self.seed, "init", "-b", "main")
        _git(self.seed, "config", "user.name", "Dreamcatcher Test")
        _git(
            self.seed,
            "config",
            "user.email",
            "dreamcatcher@users.noreply.github.com",
        )
        _git(self.seed, "config", "core.autocrlf", "false")
        (self.seed / "state").mkdir()
        (self.seed / "agents").mkdir()
        (self.seed / "state" / "frames.jsonl").write_text(
            json.dumps({"frame_id": "frame-1", "tile_id": "tile-a"}) + "\n",
            encoding="utf-8",
        )
        (self.seed / "state" / "deleted.json").write_text(
            '{"id":"delete-me"}\n',
            encoding="utf-8",
        )
        (self.seed / "state" / "alpha.txt").write_text(
            "alpha\nbeta\ngamma\ndelta\nepsilon\nzeta\n",
            encoding="utf-8",
        )
        (self.seed / "state" / "beta.txt").write_text(
            "one\ntwo\n",
            encoding="utf-8",
        )
        (self.seed / "agents" / "old.py").write_text(
            "# agent\n",
            encoding="utf-8",
        )
        _git(self.seed, "add", ".")
        _git(self.seed, "commit", "-m", "seed")
        self.base = _git(self.seed, "rev-parse", "HEAD")

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _clone(self, name: str) -> Path:
        target = self.tmp / name
        subprocess.run(
            ["git", "clone", "--quiet", str(self.seed), str(target)],
            check=True,
        )
        _git(target, "config", "user.name", "Dreamcatcher Test")
        _git(
            target,
            "config",
            "user.email",
            "dreamcatcher@users.noreply.github.com",
        )
        _git(target, "config", "core.autocrlf", "false")
        return target

    def test_capture_is_deterministic_and_matches_canonical_search_plan(self) -> None:
        repo = self._clone("capture")
        with (repo / "state" / "frames.jsonl").open(
            "a",
            encoding="utf-8",
        ) as handle:
            handle.write(json.dumps({
                "frame_id": "frame-2",
                "tile_id": "tile-b",
                "agent_id": "agent-7",
            }) + "\n")
        _git(repo, "mv", "agents/old.py", "agents/new.py")
        (repo / "state" / "deleted.json").unlink()
        (repo / "state" / "new.json").write_text(
            '{"world_id":"hub","id":"new-record"}\n',
            encoding="utf-8",
        )

        manifest = dp.capture_worktree(
            repo,
            self.base,
            source_id="worker-7",
            frame=42,
            tile="north-east",
        )
        repeated = dp.capture_worktree(
            repo,
            self.base,
            source_id="worker-7",
            frame=42,
            tile="north-east",
        )

        self.assertEqual(repeated, manifest)
        self.assertEqual(manifest["schema"], "dreamcatcher-delta/1.0")
        self.assertEqual(
            {
                (change["status"], change.get("old_path"), change["path"])
                for change in manifest["changes"]
            },
            {
                ("R", "agents/old.py", "agents/new.py"),
                ("D", None, "state/deleted.json"),
                ("M", None, "state/frames.jsonl"),
                ("A", None, "state/new.json"),
            },
        )
        self.assertEqual(manifest["search_plan"], {
            "paths": [
                "agents/new.py",
                "state/deleted.json",
                "state/frames.jsonl",
                "state/new.json",
            ],
            "deleted_paths": ["state/deleted.json"],
            "renamed_paths": [{
                "from": "agents/old.py",
                "to": "agents/new.py",
            }],
            "entity_ids": [
                "agent_id:agent-7",
                "frame_id:frame-2",
                "id:delete-me",
                "id:new-record",
                "path:agents/new.py",
                "path:state/deleted.json",
                "path:state/frames.jsonl",
                "path:state/new.json",
                "tile_id:tile-b",
                "world_id:hub",
            ],
            "scopes": [
                "agents",
                "agents/new",
                "format:json",
                "format:jsonl",
                "format:py",
                "state",
                "state/deleted",
                "state/frames",
                "state/new",
            ],
            "queries": [
                {"kind": "entity", "value": "agent_id:agent-7"},
                {"kind": "entity", "value": "frame_id:frame-2"},
                {"kind": "entity", "value": "id:delete-me"},
                {"kind": "entity", "value": "id:new-record"},
                {"kind": "entity", "value": "path:agents/new.py"},
                {"kind": "entity", "value": "path:state/deleted.json"},
                {"kind": "entity", "value": "path:state/frames.jsonl"},
                {"kind": "entity", "value": "path:state/new.json"},
                {"kind": "entity", "value": "tile_id:tile-b"},
                {"kind": "entity", "value": "world_id:hub"},
                {"kind": "path", "value": "agents/new.py"},
                {"kind": "path", "value": "agents/old.py"},
                {"kind": "path", "value": "state/deleted.json"},
                {"kind": "path", "value": "state/frames.jsonl"},
                {"kind": "path", "value": "state/new.json"},
                {"kind": "scope", "value": "agents"},
                {"kind": "scope", "value": "agents/new"},
                {"kind": "scope", "value": "format:json"},
                {"kind": "scope", "value": "format:jsonl"},
                {"kind": "scope", "value": "format:py"},
                {"kind": "scope", "value": "state"},
                {"kind": "scope", "value": "state/deleted"},
                {"kind": "scope", "value": "state/frames"},
                {"kind": "scope", "value": "state/new"},
            ],
        })
        self.assertEqual(manifest["repository"]["path_filter"], [])
        self.assertEqual(dp.validate_manifest(manifest), manifest)

    def test_capture_can_scope_one_tile_path(self) -> None:
        repo = self._clone("scoped")
        (repo / "state" / "alpha.txt").write_text(
            "changed\n",
            encoding="utf-8",
        )
        (repo / "state" / "beta.txt").write_text(
            "also changed\n",
            encoding="utf-8",
        )
        manifest = dp.capture_worktree(
            repo,
            self.base,
            source_id="tile-alpha",
            paths=["state/alpha.txt"],
        )
        self.assertEqual(
            manifest["repository"]["path_filter"],
            ["state/alpha.txt"],
        )
        self.assertEqual(
            manifest["search_plan"]["paths"],
            ["state/alpha.txt"],
        )
        self.assertEqual(len(manifest["changes"]), 1)

    def test_noncanonical_repository_paths_are_rejected(self) -> None:
        invalid_paths = (
            "state//x",
            "state/./x",
            "./state/x",
            "state/x/",
            "state/a/../x",
            "../state/x",
            "/state/x",
            "state\\x",
        )
        for value in invalid_paths:
            with self.subTest(value=value):
                with self.assertRaises(dp.DeltaProtocolError):
                    dp._normalize_path(value)

        repo = self._clone("noncanonical")
        (repo / "state" / "alpha.txt").write_text(
            "changed\n",
            encoding="utf-8",
        )
        manifest = dp.capture_worktree(repo, self.base)
        for value in invalid_paths:
            with self.subTest(manifest_path=value):
                malformed = copy.deepcopy(manifest)
                malformed["changes"][0]["path"] = value
                with self.assertRaises(dp.DeltaProtocolError):
                    dp.validate_manifest(malformed)

    def test_repository_verification_rejects_stale_worktree(self) -> None:
        repo = self._clone("verify")
        path = repo / "state" / "new.json"
        path.write_text('{"id":"first"}\n', encoding="utf-8")
        manifest = dp.capture_worktree(repo, self.base)

        self.assertEqual(dp.verify_manifest_repository(manifest, repo), manifest)
        path.write_text(
            '{"id":"changed-after-capture"}\n',
            encoding="utf-8",
        )
        with self.assertRaisesRegex(dp.DeltaProtocolError, "exact declared"):
            dp.verify_manifest_repository(manifest, repo)

    def test_headed_capture_uses_merge_base_after_main_advances(self) -> None:
        (self.seed / "state" / "main-only.txt").write_text(
            "advanced main\n",
            encoding="utf-8",
        )
        _git(self.seed, "add", ".")
        _git(self.seed, "commit", "-m", "advance main")
        repo = self._clone("stale-worker")
        _git(repo, "checkout", "-b", "worker", self.base)
        (repo / "state" / "alpha.txt").write_text(
            "worker change\n",
            encoding="utf-8",
        )
        _git(repo, "add", ".")
        _git(repo, "commit", "-m", "worker")

        manifest = dp.capture_worktree(
            repo,
            "origin/main",
            head="HEAD",
            source_id="stale-pr",
        )

        self.assertEqual(manifest["repository"]["base_commit"], self.base)
        self.assertEqual(manifest["repository"]["path_filter"], [])
        self.assertEqual(
            manifest["search_plan"]["paths"],
            ["state/alpha.txt"],
        )
        self.assertNotIn(
            "state/main-only.txt",
            manifest["search_plan"]["paths"],
        )
        self.assertEqual(dp.verify_manifest_repository(manifest, repo), manifest)

        manifest_path = self.tmp / "stale-pr-manifest.json"
        dp.write_manifest(manifest_path, manifest)
        spec = importlib.util.spec_from_file_location(
            "validate_delta_stale_pr_test",
            Path(__file__).resolve().parent / "validate_delta.py",
        )
        validator = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(validator)
        validator.BASE_DIR = repo
        validator.INBOX_DIR = repo / "state" / "inbox"
        validator.STATE_DIR = repo / "state"
        validator.errors = []
        with mock.patch.dict(os.environ, {
            "VALIDATION_BASE_SHA": "origin/main",
            "VALIDATION_HEAD_SHA": "HEAD",
            "DREAMCATCHER_DELTA_MANIFEST": str(manifest_path),
            "DREAMCATCHER_DELTA_SOURCE_ID": "stale-pr",
        }, clear=False):
            os.environ.pop("DREAMCATCHER_DELTA_TILE", None)
            actual = validator._dreamcatcher_manifest()

        self.assertEqual(validator.errors, [])
        self.assertEqual(actual, manifest)

    def test_repository_verification_rejects_omitted_change(self) -> None:
        repo = self._clone("incomplete")
        (repo / "state" / "alpha.txt").write_text(
            "changed alpha\n",
            encoding="utf-8",
        )
        (repo / "state" / "beta.txt").write_text(
            "changed beta\n",
            encoding="utf-8",
        )
        manifest = dp.capture_worktree(repo, self.base)
        incomplete_payload = copy.deepcopy(manifest)
        incomplete_payload.pop("manifest_id")
        incomplete_payload["changes"] = incomplete_payload["changes"][:1]
        incomplete_payload["search_plan"] = dp._search_plan(
            incomplete_payload["changes"]
        )
        incomplete = dp._with_id(incomplete_payload, "manifest_id")

        self.assertEqual(dp.validate_manifest(incomplete), incomplete)
        with self.assertRaisesRegex(dp.DeltaProtocolError, "exact declared"):
            dp.verify_manifest_repository(incomplete, repo)

    def test_validator_capture_matches_canonical_manifest(self) -> None:
        repo = self._clone("validator")
        (repo / "state" / "inbox").mkdir()
        (repo / "state" / "inbox" / "action.json").write_text(
            '{"agent_id":"test-001","timestamp":"2026-01-01T00:00:00Z"}\n',
            encoding="utf-8",
        )
        _git(repo, "add", "state/inbox/action.json")
        _git(repo, "commit", "-m", "add inbox delta")
        head = _git(repo, "rev-parse", "HEAD")
        expected = dp.capture_worktree(
            repo,
            self.base,
            head=head,
            source_id="pr-7",
            tile="alice",
            include_untracked=False,
        )
        spec = importlib.util.spec_from_file_location(
            "validate_delta_protocol_test",
            Path(__file__).resolve().parent / "validate_delta.py",
        )
        validator = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(validator)
        validator.BASE_DIR = repo
        validator.INBOX_DIR = repo / "state" / "inbox"
        validator.STATE_DIR = repo / "state"
        validator.errors = []

        with mock.patch.dict(os.environ, {
            "VALIDATION_BASE_SHA": self.base,
            "VALIDATION_HEAD_SHA": head,
            "DREAMCATCHER_DELTA_SOURCE_ID": "pr-7",
            "DREAMCATCHER_DELTA_TILE": "alice",
        }, clear=False):
            os.environ.pop("DREAMCATCHER_DELTA_MANIFEST", None)
            actual = validator._dreamcatcher_manifest()

        self.assertEqual(validator.errors, [])
        self.assertEqual(actual, expected)

    def test_batch_classifies_identical_disjoint_and_conflicting_writes(self) -> None:
        identical_a = self._clone("identical-a")
        identical_b = self._clone("identical-b")
        for repo in (identical_a, identical_b):
            (repo / "state" / "beta.txt").write_text(
                "ONE\ntwo\n",
                encoding="utf-8",
            )
        one = dp.capture_worktree(identical_a, self.base, source_id="one")
        two = dp.capture_worktree(identical_b, self.base, source_id="two")
        identical = dp.batch_manifests([two, one])
        self.assertTrue(identical["ready"])
        self.assertEqual(identical["collisions"][0]["kind"], "identical")

        disjoint_a = self._clone("disjoint-a")
        disjoint_b = self._clone("disjoint-b")
        lines = (disjoint_a / "state" / "alpha.txt").read_text().splitlines()
        lines[0] = "ALPHA"
        (disjoint_a / "state" / "alpha.txt").write_text(
            "\n".join(lines) + "\n",
            encoding="utf-8",
        )
        lines = (disjoint_b / "state" / "alpha.txt").read_text().splitlines()
        lines[5] = "ZETA"
        (disjoint_b / "state" / "alpha.txt").write_text(
            "\n".join(lines) + "\n",
            encoding="utf-8",
        )
        disjoint = dp.batch_manifests([
            dp.capture_worktree(disjoint_a, self.base, source_id="three"),
            dp.capture_worktree(disjoint_b, self.base, source_id="four"),
        ])
        self.assertTrue(disjoint["ready"])
        self.assertEqual(disjoint["collisions"][0]["kind"], "disjoint-hunks")

        conflict_a = self._clone("conflict-a")
        conflict_b = self._clone("conflict-b")
        (conflict_a / "state" / "beta.txt").write_text(
            "ONE\ntwo\n",
            encoding="utf-8",
        )
        (conflict_b / "state" / "beta.txt").write_text(
            "uno\ntwo\n",
            encoding="utf-8",
        )
        conflicting = dp.batch_manifests([
            dp.capture_worktree(conflict_a, self.base, source_id="five"),
            dp.capture_worktree(conflict_b, self.base, source_id="six"),
        ])
        self.assertFalse(conflicting["ready"])
        self.assertEqual(conflicting["conflicts"][0]["kind"], "conflict")

    def test_batch_uses_shared_base_coordinates_for_hunks(self) -> None:
        repo = self._clone("shifted-hunks")
        (repo / "state" / "beta.txt").write_text(
            "ONE\ntwo\n",
            encoding="utf-8",
        )
        first = dp.capture_worktree(repo, self.base, source_id="first")
        second_payload = copy.deepcopy(first)
        second_payload.pop("manifest_id")
        second_payload["source"]["id"] = "second"
        second_payload["source"]["branch"] = "worker/second"
        second_payload["repository"]["head_commit"] = "f" * 40
        second_payload["changes"][0]["after"]["sha256"] = "e" * 64
        second_payload["changes"][0]["line_ranges"][0]["new_start"] += 5
        second = dp._with_id(second_payload, "manifest_id")

        batch = dp.batch_manifests([first, second])

        self.assertFalse(batch["ready"])
        self.assertEqual(batch["conflicts"][0]["path"], "state/beta.txt")

    def test_batch_detects_rename_source_conflict(self) -> None:
        renamed = self._clone("renamed-source")
        modified = self._clone("modified-source")
        _git(renamed, "mv", "agents/old.py", "agents/new.py")
        (modified / "agents" / "old.py").write_text(
            "# changed agent\n",
            encoding="utf-8",
        )
        rename_manifest = dp.capture_worktree(
            renamed,
            self.base,
            source_id="rename",
        )
        modify_manifest = dp.capture_worktree(
            modified,
            self.base,
            source_id="modify",
        )

        batch = dp.batch_manifests([rename_manifest, modify_manifest])

        self.assertFalse(batch["ready"])
        self.assertTrue(any(
            conflict["path"] == "agents/old.py"
            for conflict in batch["conflicts"]
        ))


if __name__ == "__main__":
    unittest.main(verbosity=2)
