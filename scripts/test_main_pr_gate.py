#!/usr/bin/env python3
"""Tests for the universal protected-main pull-request gate."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
BASE_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))

import main_pr_gate as gate  # noqa: E402
import state_reconciler as reconciler  # noqa: E402


class FakeApi:
    def __init__(
        self,
        *,
        commit: dict | None = None,
        refs: list[dict] | None = None,
        statuses: list[dict] | None = None,
    ):
        self.commit = commit
        self.refs = refs or []
        self.statuses = statuses or []
        self.calls: list[tuple[str, str, dict | None]] = []
        self.posts: list[dict] = []

    def __call__(
        self,
        endpoint: str,
        *,
        method: str = "GET",
        payload: dict | None = None,
    ) -> object:
        self.calls.append((endpoint, method, payload))
        if "/git/commits/" in endpoint:
            if self.commit is None:
                raise AssertionError("head commit fixture is missing")
            return self.commit
        if "/git/matching-refs/" in endpoint:
            return self.refs
        if "/commits/" in endpoint and endpoint.endswith(
            "/statuses?per_page=100"
        ):
            return self.statuses
        if "/statuses/" in endpoint and method == "POST":
            assert payload is not None
            self.posts.append(payload)
            return {"id": len(self.posts)}
        raise AssertionError(f"unexpected API call: {method} {endpoint}")


class MainPrGatePolicyTests(unittest.TestCase):
    repo = "owner/repo"
    owner = "owner"
    source_number = 17
    source_head = "1" * 40
    base = "2" * 40
    synthetic = "3" * 40
    tree = "4" * 40
    target_url = "https://github.com/owner/repo/actions/runs/99"

    def ordinary_event(
        self,
        *,
        branch: str = "feature/docs",
        head_sha: str | None = None,
    ) -> dict:
        return {
            "repository": {"full_name": self.repo},
            "pull_request": {
                "number": 41,
                "title": "Document the protected path",
                "body": "Ordinary documentation change.",
                "draft": False,
                "base": {"ref": "main", "sha": self.base},
                "head": {
                    "ref": branch,
                    "sha": head_sha or self.source_head,
                    "repo": {"full_name": "contributor/repo"},
                },
                "user": {"login": "alice"},
            },
        }

    def internal_event(self) -> dict:
        branch = reconciler.internal_branch_name(
            self.source_number,
            self.source_head,
            self.base,
        )
        return {
            "repository": {"full_name": self.repo},
            "pull_request": {
                "number": 9001,
                "title": reconciler.internal_pr_title(
                    self.source_number,
                    self.source_head,
                    self.base,
                ),
                "body": reconciler.internal_pr_body(
                    self.source_number,
                    self.source_head,
                    self.base,
                    self.base,
                    self.synthetic,
                    self.tree,
                ),
                "draft": False,
                "base": {"ref": "main", "sha": self.base},
                "head": {
                    "ref": branch,
                    "sha": self.synthetic,
                    "repo": {"full_name": self.repo},
                },
                "user": {"login": "github-actions[bot]"},
            },
        }

    def internal_ref(self) -> dict:
        branch = self.internal_event()["pull_request"]["head"]["ref"]
        return {
            "ref": f"refs/heads/{branch}",
            "object": {"type": "commit", "sha": self.synthetic},
        }

    def synthetic_message(self) -> str:
        return "\n\n".join([
            f"[state] apply PR #{self.source_number}",
            f"Source-PR: #{self.source_number}",
            f"Source-Head: {self.source_head}",
            "Dreamcatcher-Delta: sha256:" + ("a" * 64),
            "Dreamcatcher-Search-Queries: 1",
        ])

    def commit_object(
        self,
        *,
        sha: str,
        message: str,
        tree_sha: str,
        parents: list[str],
    ) -> dict:
        return {
            "sha": sha,
            "message": message,
            "tree": {"sha": tree_sha},
            "parents": [{"sha": parent} for parent in parents],
        }

    def ordinary_commit(
        self,
        *,
        sha: str | None = None,
        message: str = "Document the protected path",
    ) -> dict:
        return self.commit_object(
            sha=sha or self.source_head,
            message=message,
            tree_sha="6" * 40,
            parents=[self.base],
        )

    def synthetic_commit(
        self,
        *,
        tree_sha: str | None = None,
        parents: list[str] | None = None,
    ) -> dict:
        return self.commit_object(
            sha=self.synthetic,
            message=self.synthetic_message(),
            tree_sha=tree_sha or self.tree,
            parents=parents or [self.base],
        )

    def trusted_status(self) -> dict:
        return {
            "context": gate.MAIN_PR_GATE_CONTEXT,
            "state": "success",
            "description": f"Validated against {self.base[:12]}",
            "creator": {
                "login": "github-actions[bot]",
                "type": "Bot",
            },
        }

    def test_ordinary_pr_receives_gate_without_candidate_execution(self) -> None:
        api = FakeApi(commit=self.ordinary_commit())
        result = gate.route_main_pr(
            self.ordinary_event(),
            repo=self.repo,
            owner=self.owner,
            api=api,
            target_url=self.target_url,
        )
        self.assertEqual(result, "ordinary-passed")
        self.assertEqual(
            api.posts,
            [{
                "state": "success",
                "context": "main-pr-gate",
                "description": gate.ORDINARY_DESCRIPTION,
                "target_url": self.target_url,
            }],
        )
        self.assertIn(
            (
                f"repos/{self.repo}/git/commits/{self.source_head}",
                "GET",
                None,
            ),
            api.calls,
        )

    def test_attacker_internal_prefix_branch_stays_blocked(self) -> None:
        api = FakeApi(commit=self.ordinary_commit())
        with self.assertRaisesRegex(
            gate.GateBlocked,
            "does not contain canonical",
        ):
            gate.route_main_pr(
                self.ordinary_event(
                    branch="state-reconciler/pr-attacker"
                ),
                repo=self.repo,
                owner=self.owner,
                api=api,
                target_url=self.target_url,
            )
        self.assertEqual(api.posts[0]["state"], "pending")
        self.assertEqual(api.posts[0]["context"], "main-pr-gate")

    def test_attacker_cannot_reuse_internal_commit_status(self) -> None:
        event = self.internal_event()
        event["pull_request"]["head"]["repo"]["full_name"] = "mallory/repo"
        event["pull_request"]["user"]["login"] = "mallory"
        api = FakeApi(
            commit=self.synthetic_commit(),
            refs=[self.internal_ref()],
            statuses=[self.trusted_status()],
        )
        with self.assertRaisesRegex(
            gate.GateBlocked,
            "reserved for its canonical",
        ):
            gate.route_main_pr(
                event,
                repo=self.repo,
                owner=self.owner,
                api=api,
                target_url=self.target_url,
            )
        self.assertEqual(api.posts, [])

    def test_ordinary_alias_of_internal_commit_stays_blocked(self) -> None:
        api = FakeApi(
            commit=self.synthetic_commit(),
            refs=[self.internal_ref()],
        )
        with self.assertRaisesRegex(
            gate.GateBlocked,
            "reserved for its canonical",
        ):
            gate.route_main_pr(
                self.ordinary_event(head_sha=self.synthetic),
                repo=self.repo,
                owner=self.owner,
                api=api,
                target_url=self.target_url,
            )
        self.assertEqual(api.posts, [])

    def test_alias_branch_cannot_disguise_synthetic_commit(self) -> None:
        event = self.internal_event()
        event["pull_request"]["head"]["ref"] = "feature/publication-alias"
        api = FakeApi(commit=self.synthetic_commit())
        with self.assertRaisesRegex(
            gate.GateBlocked,
            "reserved for its canonical",
        ):
            gate.route_main_pr(
                event,
                repo=self.repo,
                owner=self.owner,
                api=api,
                target_url=self.target_url,
            )
        self.assertEqual(api.posts, [])

    def test_shared_synthetic_sha_event_never_overwrites_gate_status(
        self,
    ) -> None:
        api = FakeApi(
            commit=self.synthetic_commit(),
            statuses=[self.trusted_status()],
        )
        self.assertEqual(
            gate.route_main_pr(
                self.internal_event(),
                repo=self.repo,
                owner=self.owner,
                api=api,
                target_url=self.target_url,
            ),
            "internal-verified",
        )
        with self.assertRaisesRegex(
            gate.GateBlocked,
            "reserved for its canonical",
        ):
            gate.route_main_pr(
                self.ordinary_event(head_sha=self.synthetic),
                repo=self.repo,
                owner=self.owner,
                api=api,
                target_url=self.target_url,
            )
        self.assertEqual(api.posts, [])

    def test_partial_synthetic_markers_stay_explicitly_pending(self) -> None:
        messages = (
            "[state] apply PR #",
            "Routine change\n\nSource-PR: #17",
            f"Routine change\n\nSource-Head: {self.source_head}",
            f"Routine change\n\nPolicy-SHA: {self.base}",
            "Routine change\n\nDreamcatcher-Policy: sha256:" + ("a" * 64),
        )
        for message in messages:
            with self.subTest(message=message):
                api = FakeApi(
                    commit=self.ordinary_commit(message=message),
                )
                with self.assertRaisesRegex(
                    gate.GateBlocked,
                    "markers are malformed",
                ):
                    gate.route_main_pr(
                        self.ordinary_event(),
                        repo=self.repo,
                        owner=self.owner,
                        api=api,
                        target_url=self.target_url,
                    )
                self.assertEqual(api.posts[0]["state"], "pending")
                self.assertEqual(
                    api.posts[0]["description"],
                    gate.MALFORMED_DESCRIPTION,
                )

    def test_synthetic_commit_requires_one_parent(self) -> None:
        api = FakeApi(
            commit=self.synthetic_commit(
                parents=[self.base, "7" * 40],
            ),
        )
        with self.assertRaisesRegex(
            gate.GateBlocked,
            "ancestry is malformed",
        ):
            gate.route_main_pr(
                self.internal_event(),
                repo=self.repo,
                owner=self.owner,
                api=api,
                target_url=self.target_url,
            )
        self.assertEqual(api.posts[0]["state"], "pending")
        self.assertEqual(
            api.posts[0]["description"],
            gate.MALFORMED_DESCRIPTION,
        )

    def test_head_commit_object_metadata_must_match_event(self) -> None:
        valid = self.ordinary_commit()
        variants = {
            "sha": {**valid, "sha": "7" * 40},
            "tree": {**valid, "tree": {"sha": "not-a-tree"}},
            "parent": {**valid, "parents": [{"sha": "not-a-parent"}]},
        }
        for label, commit in variants.items():
            with self.subTest(label=label):
                api = FakeApi(commit=commit)
                with self.assertRaisesRegex(
                    gate.GateError,
                    "malformed head commit data",
                ):
                    gate.route_main_pr(
                        self.ordinary_event(),
                        repo=self.repo,
                        owner=self.owner,
                        api=api,
                        target_url=self.target_url,
                    )
                self.assertEqual(api.posts, [])

    def test_internal_pr_only_verifies_existing_trusted_status(self) -> None:
        api = FakeApi(
            commit=self.synthetic_commit(),
            refs=[self.internal_ref()],
            statuses=[self.trusted_status()],
        )
        result = gate.route_main_pr(
            self.internal_event(),
            repo=self.repo,
            owner=self.owner,
            api=api,
            target_url=self.target_url,
        )
        self.assertEqual(result, "internal-verified")
        self.assertEqual(api.posts, [])

    def test_internal_pr_without_trusted_status_stays_blocked(self) -> None:
        untrusted = self.trusted_status()
        untrusted["creator"] = {"login": "mallory", "type": "User"}
        ordinary = self.trusted_status()
        ordinary["description"] = gate.ORDINARY_DESCRIPTION
        for label, statuses in (
            ("missing", []),
            ("untrusted", [untrusted]),
            ("ordinary-workflow", [ordinary]),
        ):
            with self.subTest(label=label):
                api = FakeApi(
                    commit=self.synthetic_commit(),
                    refs=[self.internal_ref()],
                    statuses=statuses,
                )
                with self.assertRaisesRegex(
                    gate.GateBlocked,
                    "no trusted reconciler gate status",
                ):
                    gate.route_main_pr(
                        self.internal_event(),
                        repo=self.repo,
                        owner=self.owner,
                        api=api,
                        target_url=self.target_url,
                    )
                self.assertEqual(api.posts, [])

    def test_internal_status_is_bound_to_event_base(self) -> None:
        event = self.internal_event()
        event["pull_request"]["base"]["sha"] = "5" * 40
        api = FakeApi(
            commit=self.synthetic_commit(),
            refs=[self.internal_ref()],
            statuses=[self.trusted_status()],
        )
        with self.assertRaisesRegex(
            gate.GateBlocked,
            "does not match",
        ):
            gate.route_main_pr(
                event,
                repo=self.repo,
                owner=self.owner,
                api=api,
                target_url=self.target_url,
            )
        self.assertEqual(api.posts, [])

    def test_internal_status_is_bound_to_commit_tree(self) -> None:
        api = FakeApi(
            commit=self.synthetic_commit(tree_sha="7" * 40),
            statuses=[self.trusted_status()],
        )
        with self.assertRaisesRegex(
            gate.GateBlocked,
            "does not match",
        ):
            gate.route_main_pr(
                self.internal_event(),
                repo=self.repo,
                owner=self.owner,
                api=api,
                target_url=self.target_url,
            )
        self.assertEqual(api.posts, [])


class MainPrGateWorkflowTests(unittest.TestCase):
    def test_workflow_is_trusted_metadata_only_routing(self) -> None:
        content = (
            BASE_DIR / ".github" / "workflows" / "main-pr-gate.yml"
        ).read_text(encoding="utf-8")
        trigger = content.split("\npermissions:", 1)[0]
        self.assertIn("pull_request_target:", trigger)
        self.assertIn("branches: [main]", trigger)
        self.assertNotIn("\n  pull_request:", trigger)
        self.assertNotIn("paths:", trigger)
        self.assertIn("statuses: write", content)
        self.assertIn(
            "ref: ${{ github.event.pull_request.base.sha }}",
            content,
        )
        self.assertIn("path: trusted", content)
        self.assertIn("persist-credentials: false", content)
        self.assertIn(
            "run: python trusted/scripts/main_pr_gate.py",
            content,
        )
        self.assertNotIn(
            "github.event.pull_request.head.repo.full_name",
            content,
        )
        self.assertNotIn(
            "ref: ${{ github.event.pull_request.head.sha }}",
            content,
        )
        self.assertNotIn("path: candidate", content)
        self.assertNotIn("pull-requests: write", content)
        self.assertNotIn("contents: write", content)
        self.assertIn("name: Route protected main PR", content)
        self.assertNotIn("name: main-pr-gate", content)
        gate_source = (
            BASE_DIR / "scripts" / "main_pr_gate.py"
        ).read_text(encoding="utf-8")
        self.assertIn(
            'f"repos/{repo}/git/commits/{head_sha}"',
            gate_source,
        )
        self.assertIn("has_synthetic_publication_markers", gate_source)

    def test_test_and_pii_workflows_remain_independent(self) -> None:
        gate_workflow = (
            BASE_DIR / ".github" / "workflows" / "main-pr-gate.yml"
        ).read_text(encoding="utf-8")
        regression = (
            BASE_DIR / ".github" / "workflows" / "regression-tests.yml"
        ).read_text(encoding="utf-8")
        pii = (
            BASE_DIR / ".github" / "workflows" / "pii-scan.yml"
        ).read_text(encoding="utf-8")
        self.assertNotIn("regression-tests.yml", gate_workflow)
        self.assertNotIn("pii-scan.yml", gate_workflow)
        self.assertNotIn("main-pr-gate", regression)
        self.assertNotIn("main-pr-gate", pii)


if __name__ == "__main__":
    unittest.main(verbosity=2)
