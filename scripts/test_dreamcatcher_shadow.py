#!/usr/bin/env python3
"""Focused tests for Rappterverse Dreamcatcher shadow telemetry."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import time
import unittest
import uuid
from pathlib import Path
from unittest import mock

SCRIPT_DIR = Path(__file__).resolve().parent
BASE_DIR = SCRIPT_DIR.parent
PROMOTION_TEST_KEY = "dreamcatcher-test-key-" + ("x" * 40)
sys.path.insert(0, str(SCRIPT_DIR))

import dreamcatcher_delta as dp  # noqa: E402
import dreamcatcher_promotion as promotion  # noqa: E402
import dreamcatcher_reverse_index as reverse_index  # noqa: E402
import dreamcatcher_shadow as shadow  # noqa: E402
import state_reconciler  # noqa: E402


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


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


def _content_id(label: str) -> str:
    return "sha256:" + hashlib.sha256(label.encode("utf-8")).hexdigest()


def _remove_tree(path: Path) -> None:
    def make_writable(function, target, _error) -> None:
        os.chmod(target, stat.S_IWRITE)
        function(target)

    if path.exists():
        shutil.rmtree(path, onerror=make_writable)


class RepositoryScratchTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = BASE_DIR / f".dreamcatcher-test-{uuid.uuid4().hex}"
        self.tmp.mkdir()

    def tearDown(self) -> None:
        _remove_tree(self.tmp)

    def make_repo(self, name: str = "repo") -> tuple[Path, str]:
        repo = self.tmp / name
        (repo / "state").mkdir(parents=True)
        (repo / "worlds" / "hub").mkdir(parents=True)
        (repo / "feed").mkdir()
        _write_json(repo / "state" / "agents.json", {
            "agents": {
                "agent-1": {
                    "agent_id": "agent-1",
                    "name": "One",
                }
            }
        })
        _write_json(repo / "state" / "actions.json", {
            "actions": [{
                "id": "action-1",
                "agent_id": "agent-1",
            }]
        })
        _write_json(repo / "state" / "unrelated.json", {
            "id": "unrelated-1",
            "value": 42,
        })
        _write_json(repo / "worlds" / "hub" / "config.json", {
            "world_id": "hub",
            "name": "Hub",
        })
        _write_json(repo / "feed" / "activity.json", {
            "activities": [],
        })
        _git(repo, "init", "-q", "-b", "main")
        _git(repo, "config", "user.name", "Dreamcatcher Test")
        _git(
            repo,
            "config",
            "user.email",
            "dreamcatcher@users.noreply.github.com",
        )
        _git(repo, "config", "core.autocrlf", "false")
        _git(repo, "add", ".")
        _git(repo, "commit", "-qm", "seed")
        return repo, _git(repo, "rev-parse", "HEAD")

    def modified_actions_manifest(
        self,
        repo: Path,
        base: str,
    ) -> tuple[dict, str]:
        actions_path = repo / "state" / "actions.json"
        actions = json.loads(actions_path.read_text(encoding="utf-8"))
        actions["actions"].append({
            "id": "action-2",
            "agent_id": "agent-1",
        })
        _write_json(actions_path, actions)
        _git(repo, "add", "state/actions.json")
        _git(repo, "commit", "-qm", "append action")
        head = _git(repo, "rev-parse", "HEAD")
        manifest = dp.capture_worktree(
            repo,
            base,
            head=head,
            source_id="pr-7",
            tile="alice",
            include_untracked=False,
        )
        return manifest, head

    def commit_telemetry(
        self,
        repo: Path,
        telemetry: dict,
        *,
        expected_identity: bool = True,
    ) -> str:
        manifest = {
            "manifest_id": telemetry["manifest_id"],
            "search_plan": {
                "queries": [
                    {"kind": "path", "value": "state/actions.json"}
                    for _ in range(telemetry["search_queries"])
                ],
            },
        }
        messages = state_reconciler.synthetic_commit_messages(
            telemetry["source_pr"],
            telemetry["source_head"],
            manifest,
            telemetry,
        )
        identity = (
            (
                "rappterverse-bot",
                "41898282+github-actions[bot]@users.noreply.github.com",
            )
            if expected_identity
            else ("Untrusted", "untrusted@example.com")
        )
        command = [
            "-c",
            f"user.name={identity[0]}",
            "-c",
            f"user.email={identity[1]}",
            "commit",
            "--allow-empty",
        ]
        for message in messages:
            command.extend(["-m", message])
        _git(repo, *command)
        return _git(repo, "rev-parse", "HEAD")


class ReverseIndexVendorTests(RepositoryScratchTest):
    def test_vendor_provenance_and_canonical_hashes(self) -> None:
        reverse_source = (
            SCRIPT_DIR / "dreamcatcher_reverse_index.py"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "kody-w/rappter@75025fe696331c85de58a9dbdd0efbbc68ac6f86",
            reverse_source,
        )
        self.assertIn("from dreamcatcher_delta import (", reverse_source)
        self.assertIn(
            "hardening validation and\n# case-only rename handling",
            reverse_source,
        )
        self.assertIn(
            "8f490c8158d4576f62d872cac69bf4fdd88fe9915e5d90a02e90e01789748d47",
            reverse_source,
        )
        self.assertEqual(
            hashlib.sha256(
                (BASE_DIR / "schema" / "index.schema.json")
                .read_bytes()
                .replace(b"\r\n", b"\n")
            ).hexdigest(),
            "02e565bf1f891922ef52266bba93f925c0bf3e3d9292275e3dcbd12f5f64b1d0",
        )
        self.assertEqual(
            hashlib.sha256(
                (SCRIPT_DIR / "dreamcatcher_delta.py")
                .read_bytes()
                .replace(b"\r\n", b"\n")
            ).hexdigest(),
            "edabf77d2c0431eed4a116536fd3446c7b079b9ac249751582948618b934bb9b",
        )
        self.assertNotIn(
            "# Vendored from",
            (SCRIPT_DIR / "dreamcatcher_delta.py").read_text(
                encoding="utf-8"
            ),
        )
        self.assertEqual(
            hashlib.sha256(
                (BASE_DIR / "schema" / "delta.schema.json")
                .read_bytes()
                .replace(b"\r\n", b"\n")
            ).hexdigest(),
            "74ed88c5b50be2f7a023afa3de2599ed8e0c2d5de594b8cf6fe26afb9a3fbbd1",
        )

    def test_index_is_deterministic_and_selects_dependency_closure(self) -> None:
        repo, base = self.make_repo()
        manifest, _ = self.modified_actions_manifest(repo, base)
        first = reverse_index.build_index(
            repo,
            includes=shadow.INDEX_INCLUDES,
        )
        second = reverse_index.build_index(
            repo,
            includes=shadow.INDEX_INCLUDES,
        )
        self.assertEqual(first, second)
        query = reverse_index.expand_search_plan(
            first,
            manifest["search_plan"],
            depth=1,
        )
        self.assertEqual(
            query["selected_paths"],
            ["state/actions.json", "state/agents.json"],
        )
        self.assertEqual(query["stats"]["selected_documents"], 2)
        self.assertEqual(query["stats"]["total_documents"], 5)
        self.assertGreater(query["stats"]["documents_reduction"], 0.5)
        self.assertEqual(query["missing_paths"], [])
        self.assertEqual(query["missing_entities"], [])

    def test_missing_ids_paths_and_hubs_are_reported_without_expansion(self) -> None:
        repo, _ = self.make_repo()
        for number in range(5):
            _write_json(repo / "state" / f"hub-{number}.json", {
                "world_id": "hub",
                "value": number,
            })
        index = reverse_index.build_index(
            repo,
            includes=["state"],
            max_entity_fanout=2,
        )
        query = reverse_index.expand_search_plan(index, {
            "paths": ["state/not-present.json"],
            "renamed_paths": [],
            "entity_ids": ["agent_id:not-present", "world_id:hub"],
            "scopes": ["state"],
        })
        self.assertEqual(query["selected_paths"], [])
        self.assertEqual(query["missing_paths"], ["state/not-present.json"])
        self.assertEqual(
            query["missing_entities"],
            ["agent_id:not-present"],
        )
        self.assertEqual(query["hub_entities"], ["world_id:hub"])
        for number in range(5):
            self.assertEqual(
                index["dependencies"][f"state/hub-{number}.json"],
                [],
            )

    def test_repository_index_build_stays_within_promotion_bound(self) -> None:
        state_before = hashlib.sha256(
            (BASE_DIR / "state" / "agents.json").read_bytes()
        ).hexdigest()
        started = time.perf_counter()
        index = reverse_index.build_index(
            BASE_DIR,
            includes=shadow.INDEX_INCLUDES,
        )
        elapsed = time.perf_counter() - started
        self.assertLessEqual(elapsed, 5.0)
        self.assertGreaterEqual(index["stats"]["documents"], 400)
        self.assertGreater(index["stats"]["bytes"], 0)
        self.assertEqual(
            hashlib.sha256(
                (BASE_DIR / "state" / "agents.json").read_bytes()
            ).hexdigest(),
            state_before,
        )

    def test_integer_configuration_rejects_booleans(self) -> None:
        repo, _ = self.make_repo()
        for field in ("max_bytes", "max_entity_fanout"):
            kwargs = {
                "includes": ["state"],
                "max_bytes": 1024,
                "max_entity_fanout": 16,
            }
            kwargs[field] = True
            with self.subTest(build_field=field):
                with self.assertRaisesRegex(
                    reverse_index.ReverseIndexError,
                    "positive integers",
                ):
                    reverse_index.build_index(repo, **kwargs)

        index = reverse_index.build_index(repo, includes=["state"])
        for field in ("max_bytes", "max_entity_fanout"):
            malformed = copy.deepcopy(index)
            malformed["configuration"][field] = True
            with self.subTest(validate_field=field):
                with self.assertRaisesRegex(
                    reverse_index.ReverseIndexError,
                    "invalid index configuration",
                ):
                    reverse_index.validate_index(malformed)

    def test_every_index_document_must_obey_configuration(self) -> None:
        repo, _ = self.make_repo()
        index = reverse_index.build_index(repo, includes=["state"])
        source_path = sorted(index["documents"])[0]
        cases = (
            ("worlds/outside.json", None),
            ("state/unsupported.bin", None),
            (
                source_path,
                index["configuration"]["max_bytes"] + 1,
            ),
        )
        for replacement, byte_count in cases:
            malformed = copy.deepcopy(index)
            metadata = malformed["documents"].pop(source_path)
            if byte_count is not None:
                metadata["bytes"] = byte_count
            malformed["documents"][replacement] = metadata
            with self.subTest(path=replacement, bytes=byte_count):
                with self.assertRaisesRegex(
                    reverse_index.ReverseIndexError,
                    "violates index configuration",
                ):
                    reverse_index.validate_index(malformed)

    def test_incremental_index_keeps_only_compliant_documents(self) -> None:
        repo, _ = self.make_repo()
        base = _git(repo, "rev-parse", "HEAD")
        before = reverse_index.build_index(
            repo,
            includes=["state"],
            max_bytes=256,
            suffixes={".json"},
        )
        _write_json(
            repo / "state" / "actions.json",
            {"actions": [{"payload": "x" * 512}]},
        )
        _git(
            repo,
            "mv",
            "state/unrelated.json",
            "state/unrelated.bin",
        )
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "make documents noncompliant")
        head = _git(repo, "rev-parse", "HEAD")
        manifest = dp.capture_worktree(
            repo,
            base,
            head=head,
            source_id="pr-18",
            tile="alice",
            include_untracked=False,
        )
        updated = reverse_index.update_index(repo, before, manifest)
        self.assertNotIn("state/actions.json", updated["documents"])
        self.assertNotIn("state/unrelated.json", updated["documents"])
        self.assertNotIn("state/unrelated.bin", updated["documents"])
        self.assertEqual(
            updated,
            reverse_index.build_index(
                repo,
                includes=["state"],
                max_bytes=256,
                suffixes={".json"},
            ),
        )

    def test_case_only_rename_preserves_parity_and_stale_detection(self) -> None:
        repo, _ = self.make_repo()
        old_path = "state/CaseOnly.json"
        new_path = "state/caseonly.json"
        _write_json(repo / old_path, {"id": "case-only"})
        _git(repo, "add", old_path)
        _git(repo, "commit", "-qm", "add case-only fixture")
        base = _git(repo, "rev-parse", "HEAD")
        before = reverse_index.build_index(repo, includes=["state"])

        temporary = "state/case-only-temporary.json"
        _git(repo, "mv", old_path, temporary)
        _git(repo, "mv", temporary, new_path)
        _git(repo, "commit", "-qm", "case-only rename")
        head = _git(repo, "rev-parse", "HEAD")
        manifest = dp.capture_worktree(
            repo,
            base,
            head=head,
            source_id="pr-19",
            tile="alice",
            include_untracked=False,
        )
        self.assertTrue(any(
            change["status"] == "R"
            and change["old_path"] == old_path
            and change["path"] == new_path
            for change in manifest["changes"]
        ))

        updated = reverse_index.update_index(repo, before, manifest)
        self.assertNotIn(old_path, updated["documents"])
        self.assertIn(new_path, updated["documents"])
        self.assertEqual(
            updated,
            reverse_index.build_index(repo, includes=["state"]),
        )

        stale_documents = copy.deepcopy(before["documents"])
        stale_documents[old_path]["sha256"] = "0" * 64
        stale = reverse_index._seal_index(
            stale_documents,
            before["configuration"],
        )
        with self.assertRaisesRegex(
            reverse_index.ReverseIndexError,
            "rename source hash is stale",
        ):
            reverse_index.update_index(repo, stale, manifest)

    def test_casefold_alias_also_requires_same_resolved_identity(self) -> None:
        repo, _ = self.make_repo()
        first = repo / "state" / "agents.json"
        second = repo / "state" / "actions.json"
        self.assertEqual(
            reverse_index._same_casefold_file_alias(
                "state/Agents.json",
                "state/agents.json",
                first,
                first,
            ),
            os.name == "nt",
        )
        self.assertFalse(reverse_index._same_casefold_file_alias(
            "state/Agents.json",
            "state/agents.json",
            first,
            second,
        ))
        self.assertFalse(reverse_index._same_casefold_file_alias(
            "state/agents.json",
            "state/actions.json",
            first,
            first,
        ))


class ShadowTelemetryTests(RepositoryScratchTest):
    def test_mode_defaults_to_shadow_and_rejects_unknown_values(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DREAMCATCHER_MODE", None)
            self.assertEqual(shadow.resolve_mode(), "shadow")
        with self.assertRaisesRegex(
            shadow.DreamcatcherConfigurationError,
            "off, shadow, or enforce",
        ):
            shadow.resolve_mode("audit")

    def test_off_preserves_legacy_messages_and_never_builds_index(self) -> None:
        repo, base = self.make_repo()
        manifest, head = self.modified_actions_manifest(repo, base)
        with mock.patch.object(shadow, "build_index") as build:
            telemetry = shadow.observe_candidate(
                repo,
                manifest,
                mode="off",
                source_pr=7,
                source_head=head,
            )
        self.assertIsNone(telemetry)
        build.assert_not_called()
        self.assertEqual(
            state_reconciler.synthetic_commit_messages(7, head, manifest),
            [
                "[state] apply PR #7",
                "Source-PR: #7",
                f"Source-Head: {head}",
                f"Dreamcatcher-Delta: {manifest['manifest_id']}",
                "Dreamcatcher-Search-Queries: "
                f"{len(manifest['search_plan']['queries'])}",
            ],
        )

    def test_shadow_index_error_is_recorded_but_not_raised(self) -> None:
        repo, base = self.make_repo()
        manifest, head = self.modified_actions_manifest(repo, base)
        ticks = iter([1_000_000, 3_000_000])
        with mock.patch.object(
            shadow,
            "build_index",
            side_effect=RuntimeError("shadow failure"),
        ):
            telemetry = shadow.observe_candidate(
                repo,
                manifest,
                mode="shadow",
                source_pr=7,
                source_head=head,
                clock_ns=lambda: next(ticks),
            )
        self.assertEqual(telemetry["mode"], "shadow")
        self.assertEqual(telemetry["error_count"], 1)
        self.assertEqual(telemetry["error_code"], "index-error")
        self.assertIsNone(telemetry["index_id"])
        self.assertIsNone(telemetry["query_id"])
        self.assertEqual(telemetry["duration_ms"], 2)
        self.assertEqual(telemetry["coverage"], 0.0)

    def test_exact_metrics_trailers_json_and_status(self) -> None:
        repo, base = self.make_repo()
        manifest, head = self.modified_actions_manifest(repo, base)
        ticks = iter([1_000_000, 4_500_000])
        telemetry = shadow.observe_candidate(
            repo,
            manifest,
            mode="shadow",
            source_pr=7,
            source_head=head,
            clock_ns=lambda: next(ticks),
        )
        expected_bytes = sum(
            (repo / path).stat().st_size
            for path in (
                "state/actions.json",
                "state/agents.json",
                "state/unrelated.json",
                "worlds/hub/config.json",
                "feed/activity.json",
            )
        )
        selected_bytes = sum(
            (repo / path).stat().st_size
            for path in ("state/actions.json", "state/agents.json")
        )
        self.assertEqual(telemetry["manifest_paths"], 1)
        self.assertEqual(telemetry["covered_paths"], 1)
        self.assertEqual(telemetry["selected_documents"], 2)
        self.assertEqual(telemetry["total_documents"], 5)
        self.assertEqual(telemetry["selected_bytes"], selected_bytes)
        self.assertEqual(telemetry["total_bytes"], expected_bytes)
        self.assertEqual(telemetry["coverage"], 1.0)
        self.assertEqual(telemetry["missing_paths"], 0)
        self.assertEqual(telemetry["missing_count"], 0)
        self.assertEqual(telemetry["hub_count"], 0)
        self.assertEqual(telemetry["duration_ms"], 4)
        self.assertEqual(
            telemetry["policy_revision"],
            promotion.PROMOTION_POLICY_REVISION,
        )
        self.assertEqual(
            telemetry["index_configuration_id"],
            promotion.INDEX_CONFIGURATION_ID,
        )
        self.assertIsNone(telemetry["promotion_evidence_id"])
        self.assertIsNone(telemetry["promotion_attestation"])
        self.assertEqual(
            shadow.telemetry_trailers(telemetry),
            [
                "Dreamcatcher-Mode: shadow",
                "Dreamcatcher-Policy: "
                f"{promotion.PROMOTION_POLICY_REVISION}",
                "Dreamcatcher-Index-Configuration: "
                f"{promotion.INDEX_CONFIGURATION_ID}",
                "Dreamcatcher-Promotion-Evidence: none",
                "Dreamcatcher-Promotion-Attestation: none",
                f"Dreamcatcher-Index: {telemetry['index_id']}",
                f"Dreamcatcher-Query: {telemetry['query_id']}",
                "Dreamcatcher-Paths: 1/1",
                "Dreamcatcher-Documents: 2/5",
                f"Dreamcatcher-Bytes: {selected_bytes}/{expected_bytes}",
                "Dreamcatcher-Coverage: 1.000000",
                "Dreamcatcher-Missing-Paths: 0",
                "Dreamcatcher-Missing: 0",
                "Dreamcatcher-Hubs: 0",
                "Dreamcatcher-Duration-Ms: 4",
                "Dreamcatcher-Errors: 0",
                "Dreamcatcher-Error-Code: none",
            ],
        )
        rendered = shadow.telemetry_json(telemetry)
        self.assertEqual(json.loads(rendered), telemetry)
        status = shadow.telemetry_status_description(telemetry)
        self.assertLessEqual(len(status), 140)
        for marker in ("shadow", "m=", "i=", "q=", "d=2/5", "c=1.000000"):
            self.assertIn(marker, status)

        messages = state_reconciler.synthetic_commit_messages(
            7,
            head,
            manifest,
            telemetry,
        )
        self.assertEqual(messages[0], "[state] apply PR #7")
        self.assertEqual(
            messages[1].splitlines()[:4],
            [
                "Source-PR: #7",
                f"Source-Head: {head}",
                f"Dreamcatcher-Delta: {manifest['manifest_id']}",
                "Dreamcatcher-Search-Queries: "
                f"{len(manifest['search_plan']['queries'])}",
            ],
        )
        parsed = promotion.telemetry_from_commit_message(
            "\n\n".join(messages)
        )
        self.assertEqual(parsed, telemetry)

    def test_main_advanced_manifest_stays_pr_scoped_against_current_index(self) -> None:
        repo = self.tmp / "advanced"
        repo.mkdir()
        (repo / "state").mkdir()
        _write_json(repo / "state" / "base.json", {"id": "base"})
        _git(repo, "init", "-q", "-b", "main")
        _git(repo, "config", "user.name", "Dreamcatcher Test")
        _git(
            repo,
            "config",
            "user.email",
            "dreamcatcher@users.noreply.github.com",
        )
        _git(repo, "add", ".")
        _git(repo, "commit", "-qm", "base")
        branch_point = _git(repo, "rev-parse", "HEAD")

        _git(repo, "switch", "-qc", "stale-pr")
        _write_json(repo / "state" / "pr-only.json", {"id": "pr-only"})
        _git(repo, "add", ".")
        _git(repo, "commit", "-qm", "pr")
        head = _git(repo, "rev-parse", "HEAD")

        _git(repo, "switch", "-q", "main")
        _write_json(repo / "state" / "main-only.json", {"id": "main-only"})
        _git(repo, "add", ".")
        _git(repo, "commit", "-qm", "main advanced")
        current_main = _git(repo, "rev-parse", "HEAD")

        candidate = self.tmp / "advanced-candidate"
        _git(repo, "worktree", "add", "--detach", str(candidate), current_main)
        try:
            state_reconciler.run_command([
                "git",
                "-c",
                "user.name=rappterverse-reconciler",
                "-c",
                "user.email=41898282+github-actions[bot]@users.noreply.github.com",
                "merge",
                "--no-commit",
                "--no-ff",
                head,
            ], cwd=candidate)
            manifest = state_reconciler.capture_verified_pr_manifest(
                candidate,
                current_main,
                head,
                number=17,
                author="alice",
            )
            telemetry = shadow.observe_candidate(
                candidate,
                manifest,
                mode="shadow",
                source_pr=17,
                source_head=head,
            )
        finally:
            subprocess.run(
                ["git", "worktree", "remove", "--force", str(candidate)],
                cwd=repo,
                capture_output=True,
            )
        self.assertEqual(manifest["repository"]["base_commit"], branch_point)
        self.assertEqual(
            manifest["search_plan"]["paths"],
            ["state/pr-only.json"],
        )
        self.assertEqual(telemetry["manifest_paths"], 1)
        self.assertEqual(telemetry["covered_paths"], 1)
        self.assertEqual(telemetry["selected_documents"], 1)
        self.assertEqual(telemetry["total_documents"], 3)

    def test_unsupported_changed_path_is_telemetry_only_in_shadow(self) -> None:
        repo, base = self.make_repo()
        blob = repo / "state" / "opaque.bin"
        blob.write_bytes(b"opaque")
        _git(repo, "add", "state/opaque.bin")
        _git(repo, "commit", "-qm", "add opaque state")
        head = _git(repo, "rev-parse", "HEAD")
        manifest = dp.capture_worktree(
            repo,
            base,
            head=head,
            source_id="pr-8",
            tile="alice",
            include_untracked=False,
        )
        telemetry = shadow.observe_candidate(
            repo,
            manifest,
            mode="shadow",
            source_pr=8,
            source_head=head,
        )
        self.assertEqual(telemetry["error_count"], 0)
        self.assertEqual(telemetry["covered_paths"], 0)
        self.assertEqual(telemetry["manifest_paths"], 1)
        self.assertEqual(telemetry["coverage"], 0.0)
        self.assertEqual(telemetry["missing_paths"], 1)


class PromotionEvaluatorTests(RepositoryScratchTest):
    def sample(
        self,
        number: int,
        *,
        duration_ms: int = 5_000,
        selected_documents: int = 5,
        total_documents: int = 10,
        selected_bytes: int = 750,
        total_bytes: int = 1_000,
        covered_paths: int = 1,
        manifest_paths: int = 1,
        error_count: int = 0,
        mode: str = "shadow",
        policy_revision: str = promotion.PROMOTION_POLICY_REVISION,
        index_configuration_id: str = promotion.INDEX_CONFIGURATION_ID,
        promotion_evidence_id: str | None = None,
        promotion_attestation: str | None = None,
    ) -> dict:
        if error_count:
            covered_paths = 0
            selected_documents = 0
            total_documents = 0
            selected_bytes = 0
            total_bytes = 0
        return {
            "schema": promotion.TELEMETRY_SCHEMA,
            "repository": promotion.REPOSITORY,
            "mode": mode,
            "source_pr": number,
            "source_head": f"{number:040x}",
            "manifest_id": _content_id(f"manifest-{number}"),
            "search_queries": 1,
            "policy_revision": policy_revision,
            "index_configuration_id": index_configuration_id,
            "promotion_evidence_id": promotion_evidence_id,
            "promotion_attestation": promotion_attestation,
            "index_id": (
                None if error_count else _content_id(f"index-{number}")
            ),
            "query_id": (
                None if error_count else _content_id(f"query-{number}")
            ),
            "manifest_paths": manifest_paths,
            "covered_paths": covered_paths,
            "selected_documents": selected_documents,
            "total_documents": total_documents,
            "selected_bytes": selected_bytes,
            "total_bytes": total_bytes,
            "coverage": round(
                1.0
                if manifest_paths == 0
                else covered_paths / manifest_paths,
                6,
            ),
            "missing_paths": manifest_paths - covered_paths,
            "missing_count": 0,
            "hub_count": 0,
            "duration_ms": duration_ms,
            "error_count": error_count,
            "error_code": "index-error" if error_count else None,
        }

    def ready_summary(self) -> dict:
        return promotion.evaluate_records(
            self.sample(number) for number in range(1, 51)
        )

    def evidence_repo(
        self,
        *,
        count: int = 50,
        name: str = "evidence",
    ) -> Path:
        repo, _ = self.make_repo(name)
        for number in range(1, count + 1):
            self.commit_telemetry(repo, self.sample(number))
        return repo

    def append_empty_commits_fast(self, repo: Path, count: int) -> None:
        parent = _git(repo, "rev-parse", "HEAD")
        stream = []
        for index in range(1, count + 1):
            message = f"ordinary performance commit {index}\n".encode("utf-8")
            source = parent if index == 1 else f":{index - 1}"
            stream.extend([
                f"commit refs/heads/main\nmark :{index}\n".encode("ascii"),
                (
                    "author Performance Test <performance@example.com> "
                    f"{1700000000 + index} +0000\n"
                ).encode("ascii"),
                (
                    "committer Performance Test <performance@example.com> "
                    f"{1700000000 + index} +0000\n"
                ).encode("ascii"),
                f"data {len(message)}\n".encode("ascii"),
                message,
                f"from {source}\n\n".encode("ascii"),
            ])
        stream.append(b"done\n")
        imported = subprocess.run(
            ["git", "fast-import", "--quiet"],
            cwd=repo,
            input=b"".join(stream),
            capture_output=True,
        )
        self.assertEqual(
            imported.returncode,
            0,
            imported.stderr.decode("utf-8", "replace"),
        )

    def test_gate_accepts_exact_fifty_sample_boundaries(self) -> None:
        summary = self.ready_summary()
        self.assertTrue(summary["ready"])
        self.assertEqual(
            summary["policy_revision"],
            promotion.PROMOTION_POLICY_REVISION,
        )
        self.assertEqual(
            summary["index_configuration_id"],
            promotion.INDEX_CONFIGURATION_ID,
        )
        self.assertEqual(summary["metrics"], {
            "samples": 50,
            "errors": 0,
            "coverage_failures": 0,
            "p95_duration_ms": 5_000,
            "median_documents_reduction": 0.5,
            "median_bytes_reduction": 0.25,
        })
        self.assertEqual(
            promotion.validate_promotion_summary(summary, require_ready=True),
            summary,
        )

    def test_each_promotion_gate_fails_closed(self) -> None:
        self.assertFalse(
            promotion.evaluate_records(
                self.sample(number) for number in range(1, 50)
            )["ready"]
        )
        errors = [self.sample(number) for number in range(1, 51)]
        errors[-1] = self.sample(50, error_count=1)
        self.assertFalse(promotion.evaluate_records(errors)["ready"])
        incomplete = [self.sample(number) for number in range(1, 51)]
        incomplete[-1] = self.sample(50, covered_paths=0)
        self.assertFalse(promotion.evaluate_records(incomplete)["ready"])
        slow = [
            self.sample(number, duration_ms=5_001)
            for number in range(1, 51)
        ]
        self.assertFalse(promotion.evaluate_records(slow)["ready"])
        dense_docs = [
            self.sample(number, selected_documents=6)
            for number in range(1, 51)
        ]
        self.assertFalse(promotion.evaluate_records(dense_docs)["ready"])
        dense_bytes = [
            self.sample(number, selected_bytes=751)
            for number in range(1, 51)
        ]
        self.assertFalse(promotion.evaluate_records(dense_bytes)["ready"])
        other_policy = [
            self.sample(
                number,
                policy_revision=_content_id("other-policy"),
            )
            for number in range(1, 51)
        ]
        filtered = promotion.evaluate_records(other_policy)
        self.assertEqual(filtered["metrics"]["samples"], 0)
        self.assertFalse(filtered["ready"])

    def test_malformed_evidence_and_verdicts_fail_explicitly(self) -> None:
        with self.assertRaisesRegex(
            promotion.PromotionEvidenceError,
            "JSONL line 1",
        ):
            promotion.parse_jsonl("{not-json")
        malformed = self.sample(1)
        malformed["selected_documents"] = 11
        with self.assertRaisesRegex(
            promotion.PromotionEvidenceError,
            "cannot exceed",
        ):
            promotion.validate_telemetry(malformed)
        duplicated = [self.sample(1), self.sample(1)]
        with self.assertRaisesRegex(
            promotion.PromotionEvidenceError,
            "duplicate source_head",
        ):
            promotion.evaluate_records(duplicated)
        summary = self.ready_summary()
        summary["ready"] = False
        with self.assertRaisesRegex(
            promotion.PromotionEvidenceError,
            "ready verdict",
        ):
            promotion.validate_promotion_summary(summary)
        with self.assertRaisesRegex(
            promotion.PromotionEvidenceError,
            "missing",
        ):
            promotion.telemetry_from_commit_message(
                "Dreamcatcher-Mode: shadow\n"
            )
        sample = self.sample(2)
        messages = state_reconciler.synthetic_commit_messages(
            2,
            sample["source_head"],
            {
                "manifest_id": sample["manifest_id"],
                "search_plan": {
                    "queries": [{
                        "kind": "path",
                        "value": "state/actions.json",
                    }],
                },
            },
            sample,
        )
        with self.assertRaisesRegex(
            promotion.PromotionEvidenceError,
            "unsupported Dreamcatcher trailers",
        ):
            promotion.telemetry_from_commit_message(
                "\n\n".join(messages) + "\nDreamcatcher-Unrecognized: 1"
            )
        with self.assertRaisesRegex(
            promotion.PromotionEvidenceError,
            "Source-PR does not match",
        ):
            promotion.telemetry_from_synthetic_commit(
                "\n\n".join(messages).replace(
                    "[state] apply PR #2",
                    "[state] apply PR #3",
                    1,
                )
            )
        inconsistent = self.sample(3)
        inconsistent["missing_paths"] = 1
        with self.assertRaisesRegex(
            promotion.PromotionEvidenceError,
            "missing_paths",
        ):
            promotion.validate_telemetry(inconsistent)

    def test_jsonl_and_commit_trailer_inputs_produce_valid_samples(self) -> None:
        records = [self.sample(number) for number in range(1, 51)]
        jsonl = "\n".join(
            json.dumps(record, sort_keys=True) for record in records
        )
        parsed = promotion.parse_jsonl(jsonl)
        self.assertTrue(promotion.evaluate_records(parsed)["ready"])

        repo, _ = self.make_repo("history")
        telemetry = records[0]
        self.commit_telemetry(repo, telemetry)
        body = _git(repo, "log", "-1", "--format=%B")
        parsed_trailers = subprocess.run(
            ["git", "interpret-trailers", "--parse"],
            cwd=repo,
            input=body,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        for key in promotion.TRAILER_KEYS:
            self.assertIn(f"{key}:", parsed_trailers)
        scanned = promotion.load_commit_evidence(repo)
        self.assertEqual(scanned, [telemetry])
        legacy_body = body.replace(
            "Dreamcatcher-Promotion-Attestation: none\n",
            "",
        )
        self.assertEqual(
            promotion.telemetry_from_synthetic_commit(legacy_body),
            telemetry,
        )

    def test_batch_commit_metadata_matches_individual_git_show(self) -> None:
        repo, _ = self.make_repo("metadata-parity")
        self.commit_telemetry(repo, self.sample(1))
        ordinary_message = (
            "ordinary \x1e\x1f framing commit\n\n"
            + ("f" * 40)
            + " commit 123\n"
            "author-shaped text <not-a-header@example.com> 1 +0000\n"
        )
        commit_env = os.environ.copy()
        commit_env["GIT_AUTHOR_DATE"] = "2024-02-03T04:05:06+05:30"
        commit_env["GIT_COMMITTER_DATE"] = "2024-02-03T04:05:06-07:00"
        created = subprocess.run(
            [
                "git",
                "-c",
                "user.name=Parity Author",
                "-c",
                "user.email=parity@example.com",
                "commit",
                "--allow-empty",
                "--cleanup=verbatim",
                "-F",
                "-",
            ],
            cwd=repo,
            input=ordinary_message,
            capture_output=True,
            text=True,
            env=commit_env,
        )
        self.assertEqual(
            created.returncode,
            0,
            created.stderr or created.stdout,
        )
        commits = _git(
            repo,
            "rev-list",
            "--first-parent",
            "HEAD",
        ).splitlines()
        git_env = os.environ.copy()
        git_env.pop(promotion.PROMOTION_KEY_ENV, None)
        git_env["GIT_NO_REPLACE_OBJECTS"] = "1"
        metadata = promotion._load_commit_metadata_batch(
            repo,
            git_env,
            commits,
        )

        def show(commit: str, format_string: str) -> bytes:
            return subprocess.run(
                [
                    "git",
                    "show",
                    "--no-patch",
                    "--no-notes",
                    "--no-show-signature",
                    "--no-color",
                    f"--format=format:{format_string}",
                    commit,
                ],
                cwd=repo,
                capture_output=True,
                check=True,
            ).stdout

        def show_identity(
            commit: str,
            format_string: str,
        ) -> tuple[str, str, str]:
            values = tuple(
                value.decode("utf-8", "replace")
                for value in show(commit, format_string).split(b"\x00")
            )
            self.assertEqual(len(values), 3)
            return (
                values[0],
                values[1],
                promotion._canonical_utc_timestamp(values[2]),
            )

        self.assertEqual(metadata[0].author[2], "2024-02-02T22:35:06Z")
        self.assertEqual(metadata[0].committer[2], "2024-02-03T11:05:06Z")
        for commit, actual in zip(commits, metadata, strict=True):
            with self.subTest(commit=commit):
                self.assertEqual(
                    actual.parents,
                    tuple(show(commit, "%P").decode("ascii").split()),
                )
                self.assertEqual(
                    actual.subject,
                    show(commit, "%s").decode("utf-8", "replace"),
                )
                self.assertEqual(
                    actual.message,
                    show(commit, "%B").decode("utf-8", "replace"),
                )
                self.assertEqual(
                    actual.author,
                    show_identity(commit, "%an%x00%ae%x00%aI"),
                )
                self.assertEqual(
                    actual.committer,
                    show_identity(commit, "%cn%x00%ce%x00%cI"),
                )
                self.assertEqual(actual.signatures, ())

    def test_commit_evidence_is_first_parent_canonical_not_identity_auth(self) -> None:
        repo, _ = self.make_repo("first-parent")
        _git(repo, "switch", "-qc", "side")
        self.commit_telemetry(repo, self.sample(1))
        _git(repo, "switch", "-q", "main")
        _git(
            repo,
            "-c",
            "user.name=Merge Test",
            "-c",
            "user.email=merge@example.com",
            "merge",
            "--no-ff",
            "-m",
            "ordinary merged branch",
            "side",
        )
        self.assertEqual(promotion.load_commit_evidence(repo), [])

        expected_identity = self.sample(2)
        self.commit_telemetry(repo, expected_identity)
        self.assertEqual(
            promotion.load_commit_evidence(repo),
            [expected_identity],
        )

        unexpected_identity = self.sample(3)
        self.commit_telemetry(
            repo,
            unexpected_identity,
            expected_identity=False,
        )
        self.assertEqual(
            promotion.load_commit_evidence(repo),
            [unexpected_identity, expected_identity],
        )

    def test_commit_evidence_reads_actual_objects_not_replace_refs(self) -> None:
        repo, seed = self.make_repo("actual-objects")
        _git(repo, "commit", "--allow-empty", "-qm", "ordinary target")
        target = _git(repo, "rev-parse", "HEAD")
        _git(repo, "switch", "-qc", "replacement", seed)
        replacement = self.commit_telemetry(repo, self.sample(1))
        _git(repo, "switch", "-q", "main")
        _git(repo, "replace", target, replacement)
        self.assertEqual(_git(repo, "replace", "-l"), target)
        self.assertEqual(promotion.load_commit_evidence(repo), [])

    def test_ordinary_commit_delimiters_cannot_inject_evidence(self) -> None:
        repo, _ = self.make_repo("delimiter-injection")
        fake_records = []
        for number in range(1, 51):
            telemetry = self.sample(number)
            manifest = {
                "manifest_id": telemetry["manifest_id"],
                "search_plan": {
                    "queries": [{
                        "kind": "path",
                        "value": "state/actions.json",
                    }],
                },
            }
            synthetic_message = "\n\n".join(
                state_reconciler.synthetic_commit_messages(
                    telemetry["source_pr"],
                    telemetry["source_head"],
                    manifest,
                    telemetry,
                )
            )
            fake_records.append(
                "\x1e"
                f"{number:040x}\x1f{'f' * 40}\x1f"
                f"{synthetic_message}"
            )
        commit_message = (
            "ordinary commit with delimiter-shaped body\n\n"
            + "".join(fake_records)
        )
        self.assertEqual(commit_message.count("\x1e"), 50)
        created = subprocess.run(
            [
                "git",
                "commit",
                "--allow-empty",
                "--cleanup=verbatim",
                "-F",
                "-",
            ],
            cwd=repo,
            input=commit_message,
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            created.returncode,
            0,
            created.stderr or created.stdout,
        )
        stored_message = subprocess.run(
            [
                "git",
                "show",
                "--no-patch",
                "--format=format:%B",
                "HEAD",
            ],
            cwd=repo,
            capture_output=True,
            check=True,
        ).stdout.decode("utf-8")
        self.assertEqual(stored_message.count("\x1e"), 50)
        self.assertEqual(promotion.load_commit_evidence(repo), [])

    def test_commit_evidence_history_is_bounded(self) -> None:
        repo, _ = self.make_repo("bounded-history")
        samples = [self.sample(number) for number in range(1, 4)]
        for sample in samples:
            self.commit_telemetry(repo, sample)
        with mock.patch.object(
            promotion,
            "MAXIMUM_COMMIT_EVIDENCE_COMMITS",
            2,
        ):
            self.assertEqual(
                promotion.load_commit_evidence(repo),
                [samples[2], samples[1]],
            )

    def test_malformed_commit_object_fails_closed(self) -> None:
        repo, _ = self.make_repo("malformed-object")
        telemetry = self.sample(1)
        manifest = {
            "manifest_id": telemetry["manifest_id"],
            "search_plan": {
                "queries": [{
                    "kind": "path",
                    "value": "state/actions.json",
                }],
            },
        }
        message = "\n\n".join(
            state_reconciler.synthetic_commit_messages(
                telemetry["source_pr"],
                telemetry["source_head"],
                manifest,
                telemetry,
            )
        ) + "\n"
        raw_object = (
            f"tree {_git(repo, 'rev-parse', 'HEAD^{tree}')}\n"
            f"parent {_git(repo, 'rev-parse', 'HEAD')}\n"
            "author Malformed Test <malformed@example.com> "
            "1700000000 +0000\n\n"
        ).encode("ascii") + message.encode("utf-8")
        written = subprocess.run(
            [
                "git",
                "hash-object",
                "--literally",
                "-t",
                "commit",
                "-w",
                "--stdin",
            ],
            cwd=repo,
            input=raw_object,
            capture_output=True,
            check=True,
        )
        malformed = written.stdout.decode("ascii").strip()
        self.assertEqual(_git(repo, "cat-file", "-t", malformed), "commit")
        _git(repo, "update-ref", "refs/heads/main", malformed)
        with self.assertRaisesRegex(
            promotion.PromotionEvidenceError,
            "expected one committer header",
        ):
            promotion.load_commit_evidence(repo)

    def test_512_commit_scan_uses_constant_git_processes(self) -> None:
        repo, _ = self.make_repo("process-bound")
        self.append_empty_commits_fast(
            repo,
            promotion.MAXIMUM_COMMIT_EVIDENCE_COMMITS,
        )
        self.assertEqual(
            len(
                _git(
                    repo,
                    "rev-list",
                    "--first-parent",
                    f"--max-count={promotion.MAXIMUM_COMMIT_EVIDENCE_COMMITS}",
                    "HEAD",
                ).splitlines()
            ),
            promotion.MAXIMUM_COMMIT_EVIDENCE_COMMITS,
        )
        with (
            mock.patch.object(
                promotion,
                "_run_evidence_git",
                wraps=promotion._run_evidence_git,
            ) as run_git,
            mock.patch.object(
                promotion,
                "_start_evidence_object_stream",
                wraps=promotion._start_evidence_object_stream,
            ) as start_stream,
        ):
            self.assertEqual(promotion.load_commit_evidence(repo), [])
        self.assertEqual(run_git.call_count, 2)
        self.assertEqual(start_stream.call_count, 1)
        self.assertEqual(
            [call.args[2][0] for call in run_git.call_args_list],
            ["rev-parse", "rev-list"],
        )

    def test_hmac_attestation_binds_evidence_policy_index_repo_and_target(
        self,
    ) -> None:
        evidence = self.evidence_repo(name="attested-evidence")
        summary = promotion.require_repository_readiness(evidence)
        repository = "owner/rappterverse"
        target_base = "a" * 40
        target_head = "b" * 40
        with mock.patch.dict(
            os.environ,
            {promotion.PROMOTION_KEY_ENV: PROMOTION_TEST_KEY},
            clear=False,
        ):
            attestation = promotion.create_promotion_attestation(
                summary,
                repository=repository,
                target_base=target_base,
                target_head=target_head,
            )
            self.assertEqual(
                promotion.verify_promotion_attestation(
                    attestation,
                    summary,
                    repository=repository,
                    target_base=target_base,
                    target_head=target_head,
                ),
                attestation,
            )
            self.assertNotIn(
                PROMOTION_TEST_KEY,
                json.dumps(attestation, sort_keys=True),
            )

            for field, value in (
                ("evidence_id", _content_id("other-evidence")),
                ("summary_id", _content_id("other-summary")),
                ("policy_revision", _content_id("other-policy")),
                (
                    "index_configuration_id",
                    _content_id("other-index"),
                ),
                ("repository", "other/rappterverse"),
                ("target_base", "c" * 40),
                ("target_head", "d" * 40),
                (
                    "signature",
                    "hmac-sha256:" + ("0" * 64),
                ),
            ):
                tampered = copy.deepcopy(attestation)
                tampered[field] = value
                with self.subTest(field=field):
                    with self.assertRaises(
                        promotion.PromotionAttestationError
                    ):
                        promotion.verify_promotion_attestation(
                            tampered,
                            summary,
                            repository=repository,
                            target_base=target_base,
                            target_head=target_head,
                        )

            with self.assertRaisesRegex(
                promotion.PromotionAttestationError,
                "bindings",
            ):
                promotion.verify_promotion_attestation(
                    attestation,
                    summary,
                    repository=repository,
                    target_base=target_base,
                    target_head="e" * 40,
                )

        with mock.patch.dict(
            os.environ,
            {promotion.PROMOTION_KEY_ENV: "different-" + PROMOTION_TEST_KEY},
            clear=False,
        ):
            with self.assertRaisesRegex(
                promotion.PromotionAttestationError,
                "authentication failed",
            ):
                promotion.verify_promotion_attestation(
                    attestation,
                    summary,
                    repository=repository,
                    target_base=target_base,
                    target_head=target_head,
                )

        self.commit_telemetry(evidence, self.sample(51))
        changed_summary = promotion.require_repository_readiness(evidence)
        with mock.patch.dict(
            os.environ,
            {promotion.PROMOTION_KEY_ENV: PROMOTION_TEST_KEY},
            clear=False,
        ):
            with self.assertRaisesRegex(
                promotion.PromotionAttestationError,
                "bindings",
            ):
                promotion.verify_promotion_attestation(
                    attestation,
                    changed_summary,
                    repository=repository,
                    target_base=target_base,
                    target_head=target_head,
                )

        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(promotion.PROMOTION_KEY_ENV, None)
            with self.assertRaisesRegex(
                promotion.PromotionAttestationError,
                promotion.PROMOTION_KEY_ENV,
            ):
                promotion.create_promotion_attestation(
                    summary,
                    repository=repository,
                    target_base=target_base,
                    target_head=target_head,
                )

    def test_trusted_signer_cli_generates_verifiable_attestation(self) -> None:
        evidence = self.evidence_repo(name="signer-evidence")
        repository = "owner/rappterverse"
        target_base = "a" * 40
        target_head = "b" * 40
        with mock.patch.dict(
            os.environ,
            {promotion.PROMOTION_KEY_ENV: PROMOTION_TEST_KEY},
            clear=False,
        ):
            authenticated = (
                state_reconciler.generate_authenticated_promotion_evidence(
                    evidence_repo=evidence,
                    evidence_revision="HEAD",
                    repository=repository,
                    target_base=target_base,
                    target_head=target_head,
                )
            )
            summary = promotion.require_authenticated_repository_readiness(
                authenticated,
                repository=repository,
                target_base=target_base,
                target_head=target_head,
            )
            tampered = copy.deepcopy(authenticated)
            tampered["summary"]["metrics"]["p95_duration_ms"] = 4_999
            tampered["summary"]["summary_id"] = promotion._content_id({
                key: value
                for key, value in tampered["summary"].items()
                if key != "summary_id"
            })
            with self.assertRaisesRegex(
                promotion.PromotionAttestationError,
                "bindings",
            ):
                promotion.require_authenticated_repository_readiness(
                    tampered,
                    repository=repository,
                    target_base=target_base,
                    target_head=target_head,
                )
        self.assertTrue(summary["ready"])
        self.assertNotIn(
            PROMOTION_TEST_KEY,
            json.dumps(authenticated, sort_keys=True),
        )

    def test_authenticated_evidence_reuses_one_repository_scan(self) -> None:
        evidence = self.evidence_repo(name="single-scan-evidence")
        repository = "owner/rappterverse"
        target_base = "a" * 40
        target_head = "b" * 40
        with (
            mock.patch.dict(
                os.environ,
                {promotion.PROMOTION_KEY_ENV: PROMOTION_TEST_KEY},
                clear=False,
            ),
            mock.patch.object(
                promotion,
                "load_commit_evidence",
                wraps=promotion.load_commit_evidence,
            ) as scan,
        ):
            authenticated = promotion.authenticate_repository_readiness(
                evidence,
                repository=repository,
                target_base=target_base,
                target_head=target_head,
            )
            summary = promotion.require_authenticated_repository_readiness(
                authenticated,
                repository=repository,
                target_base=target_base,
                target_head=target_head,
            )
        self.assertTrue(summary["ready"])
        scan.assert_called_once_with(evidence, "HEAD")

    def test_reconciler_scrubs_signing_key_from_other_subprocesses(self) -> None:
        completed = subprocess.CompletedProcess(
            ["git", "status"],
            0,
            stdout="",
            stderr="",
        )
        with (
            mock.patch.dict(
                os.environ,
                {promotion.PROMOTION_KEY_ENV: PROMOTION_TEST_KEY},
                clear=False,
            ),
            mock.patch.object(
                state_reconciler.subprocess,
                "run",
                return_value=completed,
            ) as run,
        ):
            state_reconciler.run_command(["git", "status"])
        self.assertNotIn(
            promotion.PROMOTION_KEY_ENV,
            run.call_args.kwargs["env"],
        )

    def test_canonical_looking_merge_commit_is_not_evidence(self) -> None:
        repo, _ = self.make_repo("merge-shape")
        _git(repo, "switch", "-qc", "side")
        (repo / "state" / "side.json").write_text("{}\n", encoding="utf-8")
        _git(repo, "add", ".")
        _git(repo, "commit", "-qm", "side change")
        _git(repo, "switch", "-q", "main")
        sample = self.sample(4)
        manifest = {
            "manifest_id": sample["manifest_id"],
            "search_plan": {
                "queries": [{
                    "kind": "path",
                    "value": "state/actions.json",
                }],
            },
        }
        message = "\n\n".join(
            state_reconciler.synthetic_commit_messages(
                sample["source_pr"],
                sample["source_head"],
                manifest,
                sample,
            )
        )
        _git(
            repo,
            "-c",
            "user.name=rappterverse-bot",
            "-c",
            "user.email=41898282+github-actions[bot]@users.noreply.github.com",
            "merge",
            "--no-ff",
            "-m",
            message,
            "side",
        )
        with self.assertRaisesRegex(
            promotion.PromotionEvidenceError,
            "must have one parent",
        ):
            promotion.load_commit_evidence(repo)

    def test_jsonl_cli_returns_ready_and_malformed_exit_codes(self) -> None:
        jsonl = "\n".join(
            json.dumps(self.sample(number), sort_keys=True)
            for number in range(1, 51)
        )
        ready = subprocess.run(
            [
                sys.executable,
                str(SCRIPT_DIR / "dreamcatcher_promotion.py"),
                "--jsonl",
                "-",
            ],
            input=jsonl,
            capture_output=True,
            text=True,
        )
        self.assertEqual(ready.returncode, 0, ready.stderr)
        self.assertTrue(json.loads(ready.stdout)["ready"])
        malformed = subprocess.run(
            [
                sys.executable,
                str(SCRIPT_DIR / "dreamcatcher_promotion.py"),
                "--jsonl",
                "-",
            ],
            input="{bad",
            capture_output=True,
            text=True,
        )
        self.assertEqual(malformed.returncode, 2)
        self.assertIn("error: JSONL line 1", malformed.stderr)

    def test_enforce_recomputes_authenticated_readiness(self) -> None:
        repo, base = self.make_repo()
        manifest, head = self.modified_actions_manifest(repo, base)
        with self.assertRaisesRegex(
            shadow.DreamcatcherConfigurationError,
            "canonical repository evidence",
        ):
            shadow.observe_candidate(
                repo,
                manifest,
                mode="enforce",
                source_pr=7,
                source_head=head,
            )

        invented = self.ready_summary()
        with self.assertRaisesRegex(
            shadow.DreamcatcherConfigurationError,
            "caller-authored",
        ):
            shadow.observe_candidate(
                repo,
                manifest,
                mode="enforce",
                source_pr=7,
                source_head=head,
                promotion_summary=invented,
            )

        with mock.patch.object(
            shadow,
            "require_attested_repository_readiness",
            side_effect=OSError("history unavailable"),
        ):
            with self.assertRaisesRegex(
                shadow.DreamcatcherRuntimeError,
                "evidence evaluation failed",
            ):
                shadow.observe_candidate(
                    repo,
                    manifest,
                    mode="enforce",
                    source_pr=7,
                    source_head=head,
                    promotion_attestation={},
                    evidence_repo=repo,
                    target_base=base,
                )

        evidence = self.evidence_repo(count=49)
        with self.assertRaisesRegex(
            shadow.DreamcatcherConfigurationError,
            "valid promotion attestation is unavailable",
        ):
            shadow.observe_candidate(
                repo,
                manifest,
                mode="enforce",
                source_pr=7,
                source_head=head,
                promotion_attestation={},
                evidence_repo=evidence,
                target_base=base,
            )
        self.commit_telemetry(evidence, self.sample(50))
        repository = "owner/rappterverse"
        with self.assertRaisesRegex(
            shadow.DreamcatcherConfigurationError,
            "target-bound promotion attestation",
        ):
            shadow.observe_candidate(
                repo,
                manifest,
                mode="enforce",
                source_pr=7,
                source_head=head,
                evidence_repo=evidence,
                target_repository=repository,
                target_base=base,
            )
        with mock.patch.dict(
            os.environ,
            {promotion.PROMOTION_KEY_ENV: PROMOTION_TEST_KEY},
            clear=False,
        ):
            authenticated = promotion.authenticate_repository_readiness(
                evidence,
                repository=repository,
                target_base=base,
                target_head=head,
            )
            trusted = promotion.require_authenticated_repository_readiness(
                authenticated,
                repository=repository,
                target_base=base,
                target_head=head,
            )
            telemetry = shadow.observe_candidate(
                repo,
                manifest,
                mode="enforce",
                source_pr=7,
                source_head=head,
                authenticated_promotion_evidence=authenticated,
                target_repository=repository,
                target_base=base,
            )
        self.assertEqual(telemetry["mode"], "enforce")
        self.assertEqual(telemetry["coverage"], 1.0)
        self.assertEqual(
            telemetry["promotion_evidence_id"],
            trusted["evidence_id"],
        )
        self.assertEqual(
            telemetry["promotion_attestation"],
            authenticated["attestation"]["signature"],
        )

    def test_enforce_only_rejects_deterministic_path_coverage(self) -> None:
        repo, base = self.make_repo()
        blob = repo / "state" / "opaque.bin"
        blob.write_bytes(b"opaque")
        _git(repo, "add", "state/opaque.bin")
        _git(repo, "commit", "-qm", "opaque")
        head = _git(repo, "rev-parse", "HEAD")
        manifest = dp.capture_worktree(
            repo,
            base,
            head=head,
            source_id="pr-9",
            tile="alice",
            include_untracked=False,
        )
        evidence = self.evidence_repo(name="coverage-evidence")
        repository = "owner/rappterverse"
        with mock.patch.dict(
            os.environ,
            {promotion.PROMOTION_KEY_ENV: PROMOTION_TEST_KEY},
            clear=False,
        ):
            attestation = promotion.attest_repository_readiness(
                evidence,
                repository=repository,
                target_base=base,
                target_head=head,
            )
            with self.assertRaisesRegex(
                shadow.DreamcatcherEnforcementError,
                "cover every manifest path",
            ):
                shadow.observe_candidate(
                    repo,
                    manifest,
                    mode="enforce",
                    source_pr=9,
                    source_head=head,
                    promotion_attestation=attestation,
                    evidence_repo=evidence,
                    target_repository=repository,
                    target_base=base,
                )

            for failure in (
                reverse_index.ReverseIndexError("broken"),
                OSError("unavailable"),
                RuntimeError("implementation bug"),
            ):
                with self.subTest(failure=type(failure).__name__):
                    with mock.patch.object(
                        shadow,
                        "build_index",
                        side_effect=failure,
                    ):
                        with self.assertRaisesRegex(
                            shadow.DreamcatcherRuntimeError,
                            "index failed",
                        ):
                            shadow.observe_candidate(
                                repo,
                                manifest,
                                mode="enforce",
                                source_pr=9,
                                source_head=head,
                                promotion_attestation=attestation,
                                evidence_repo=evidence,
                                target_repository=repository,
                                target_base=base,
                            )

    def test_summary_loader_accepts_inline_and_path_but_rejects_tampering(self) -> None:
        summary = self.ready_summary()
        inline = json.dumps(summary, sort_keys=True)
        self.assertEqual(promotion.load_promotion_summary(inline), summary)
        path = self.tmp / "promotion.json"
        path.write_text(inline, encoding="utf-8")
        self.assertEqual(promotion.load_promotion_summary(str(path)), summary)
        tampered = copy.deepcopy(summary)
        tampered["metrics"]["samples"] = 49
        path.write_text(json.dumps(tampered), encoding="utf-8")
        with self.assertRaisesRegex(
            promotion.PromotionEvidenceError,
            "ready verdict|summary_id",
        ):
            promotion.load_promotion_summary(str(path))

    def test_reconciler_classifies_only_coverage_as_terminal(self) -> None:
        manifest = {
            "manifest_id": _content_id("manifest"),
            "search_plan": {"queries": []},
        }
        candidate = self.tmp / "candidate"
        candidate.mkdir()
        reconciler = state_reconciler.StateReconciler(
            "owner/repo",
            dry_run=True,
            dreamcatcher_mode="enforce",
        )
        cases = (
            (
                shadow.DreamcatcherEnforcementError("coverage"),
                state_reconciler.ValidationRejected,
            ),
            (
                shadow.DreamcatcherRuntimeError("index"),
                state_reconciler.ReconcileError,
            ),
            (
                shadow.DreamcatcherConfigurationError("evidence"),
                state_reconciler.ReconcileError,
            ),
            (OSError("filesystem"), state_reconciler.ReconcileError),
        )
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DREAMCATCHER_PROMOTION_SUMMARY", None)
            for failure, expected in cases:
                with self.subTest(failure=type(failure).__name__):
                    with (
                        mock.patch.object(
                            state_reconciler,
                            "generate_authenticated_promotion_evidence",
                            return_value={},
                        ),
                        mock.patch.object(
                            state_reconciler,
                            "observe_candidate",
                            side_effect=failure,
                        ),
                    ):
                        with self.assertRaises(expected):
                            reconciler.observe_dreamcatcher(
                                candidate,
                                manifest,
                                number=7,
                                base_sha="0" * 40,
                                head_sha="1" * 40,
                            )

        with mock.patch.dict(
            os.environ,
            {"DREAMCATCHER_PROMOTION_SUMMARY": json.dumps(self.ready_summary())},
            clear=False,
        ):
            with self.assertRaisesRegex(
                state_reconciler.ReconcileError,
                "caller-authored",
            ):
                reconciler.observe_dreamcatcher(
                    candidate,
                    manifest,
                    number=7,
                    base_sha="0" * 40,
                    head_sha="1" * 40,
                )

        shadow_reconciler = state_reconciler.StateReconciler(
            "owner/repo",
            dry_run=True,
            dreamcatcher_mode="shadow",
        )
        for failure in (
            RuntimeError("telemetry bug"),
            shadow.DreamcatcherEnforcementError("unexpected coverage"),
        ):
            with self.subTest(shadow_failure=type(failure).__name__):
                with mock.patch.object(
                    state_reconciler,
                    "observe_candidate",
                    side_effect=failure,
                ):
                    self.assertIsNone(
                        shadow_reconciler.observe_dreamcatcher(
                            candidate,
                            manifest,
                            number=7,
                            base_sha="0" * 40,
                            head_sha="1" * 40,
                        )
                    )

        reconciler._authenticated_evidence_cache.clear()
        with mock.patch.object(
            state_reconciler,
            "generate_authenticated_promotion_evidence",
            side_effect=state_reconciler.ReconcileError(
                "promotion signer unavailable"
            ),
        ):
            with self.assertRaisesRegex(
                state_reconciler.ReconcileError,
                "signer unavailable",
            ):
                reconciler.observe_dreamcatcher(
                    candidate,
                    manifest,
                    number=7,
                    base_sha="0" * 40,
                    head_sha="1" * 40,
                )

    def test_reconciler_caches_authenticated_evidence_for_target(self) -> None:
        manifest = {
            "manifest_id": _content_id("cache-manifest"),
            "search_plan": {"queries": []},
        }
        candidate = self.tmp / "cache-candidate"
        candidate.mkdir()
        authenticated = {"authenticated": True}
        reconciler = state_reconciler.StateReconciler(
            "owner/repo",
            dry_run=True,
            dreamcatcher_mode="enforce",
        )
        with (
            mock.patch.object(
                state_reconciler,
                "generate_authenticated_promotion_evidence",
                return_value=authenticated,
            ) as generate,
            mock.patch.object(
                state_reconciler,
                "observe_candidate",
                return_value=None,
            ) as observe,
        ):
            for _ in range(2):
                self.assertIsNone(
                    reconciler.observe_dreamcatcher(
                        candidate,
                        manifest,
                        number=7,
                        base_sha="0" * 40,
                        head_sha="1" * 40,
                    )
                )
        generate.assert_called_once()
        self.assertEqual(observe.call_count, 2)
        for call in observe.call_args_list:
            self.assertIs(
                call.kwargs["authenticated_promotion_evidence"],
                authenticated,
            )

    def test_retryable_enforce_failure_does_not_close_pr(self) -> None:
        reconciler = state_reconciler.StateReconciler(
            "owner/repo",
            dreamcatcher_mode="enforce",
        )
        head = "2" * 40
        pr = {
            "number": 7,
            "headRefOid": head,
            "baseRefName": "main",
        }
        details = {
            "state": "OPEN",
            "isDraft": False,
            "baseRefName": "main",
            "headRefOid": head,
            "files": [{"path": "state/actions.json"}],
            "statusCheckRollup": [],
        }
        with (
            mock.patch.object(reconciler, "details", return_value=details),
            mock.patch.object(reconciler, "published_commit", return_value=None),
            mock.patch.object(
                reconciler,
                "current_reconciler_state",
                return_value=None,
            ),
            mock.patch.object(
                reconciler,
                "current_main_sha",
                return_value=reconciler.policy_sha,
            ),
            mock.patch.object(
                reconciler,
                "validate",
                side_effect=state_reconciler.ReconcileError(
                    "index unavailable"
                ),
            ),
            mock.patch.object(reconciler, "note_status"),
            mock.patch.object(reconciler, "finalize_rejected_pr") as close,
        ):
            self.assertEqual(reconciler.process(pr), state_reconciler.BLOCKED)
        close.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
