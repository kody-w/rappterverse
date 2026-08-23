#!/usr/bin/env python3
"""Focused tests for protected-main state publication."""

from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path
from unittest import mock

SCRIPT_DIR = Path(__file__).resolve().parent

sys.path.insert(0, str(SCRIPT_DIR))

import state_reconciler as reconciler_module  # noqa: E402


class StateReconcilerPublicationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.number = 17
        self.head = "1" * 40
        self.base = "2" * 40
        self.synthetic = "3" * 40
        self.tree = "4" * 40
        self.published = "5" * 40
        self.internal_number = 9001
        self.reconciler = object.__new__(reconciler_module.StateReconciler)
        self.reconciler.repo = "owner/repo"
        self.reconciler.owner = "owner"
        self.reconciler.policy_sha = self.base
        self.reconciler.dry_run = False
        self.reconciler.last_dreamcatcher_telemetry = None
        self.reconciler._authenticated_evidence_cache = {}

    def evidence(self, **overrides) -> dict:
        value = {
            "source_pr": self.number,
            "source_head": self.head,
            "policy_sha": self.base,
            "base_sha": self.base,
            "synthetic_commit": self.synthetic,
            "synthetic_tree": self.tree,
        }
        value.update(overrides)
        return value

    def legacy_internal_pr(self, **overrides) -> dict:
        value = self.internal_pr()
        value["title"] = reconciler_module.legacy_internal_pr_title(
            self.number,
            self.head,
        )
        value["head"]["ref"] = (
            reconciler_module.legacy_internal_branch_name(
                self.number,
                self.head,
            )
        )
        value.update(overrides)
        return value

    def internal_pr(
        self,
        *,
        evidence_overrides: dict | None = None,
        **overrides,
    ) -> dict:
        evidence = self.evidence(**(evidence_overrides or {}))
        branch = reconciler_module.internal_branch_name(
            self.number,
            self.head,
            evidence["base_sha"],
        )
        value = {
            "number": self.internal_number,
            "title": reconciler_module.internal_pr_title(
                self.number,
                self.head,
                evidence["base_sha"],
            ),
            "body": reconciler_module.internal_pr_body(
                self.number,
                self.head,
                evidence["policy_sha"],
                evidence["base_sha"],
                evidence["synthetic_commit"],
                evidence["synthetic_tree"],
            ),
            "state": "open",
            "draft": False,
            "merged": False,
            "merged_at": None,
            "head": {
                "ref": branch,
                "sha": evidence["synthetic_commit"],
                "repo": {"full_name": "owner/repo"},
            },
            "base": {"ref": "main", "sha": evidence["base_sha"]},
            "user": {"login": "github-actions[bot]"},
        }
        value.update(overrides)
        return value

    def queue_pr(self, *, canonical: bool = True) -> dict:
        pr = self.internal_pr()
        value = {
            "number": pr["number"],
            "headRefOid": pr["head"]["sha"],
            "headRefName": pr["head"]["ref"],
            "baseRefName": "main",
            "author": {"login": "github-actions[bot]"},
            "createdAt": "2026-08-23T10:00:00Z",
            "isDraft": False,
            "title": pr["title"],
            "body": pr["body"],
            "isCrossRepository": False,
        }
        if not canonical:
            value["title"] = "[state] ordinary proposal"
            value["author"] = {"login": "alice"}
        return value

    def source_details(self) -> dict:
        return {
            "state": "OPEN",
            "isDraft": False,
            "baseRefName": "main",
            "headRefOid": self.head,
            "headRefName": "agent/action",
            "author": {"login": "alice"},
            "isCrossRepository": True,
            "files": [{"path": "state/actions.json"}],
            "statusCheckRollup": [
                {"name": "state-consensus", "conclusion": "SUCCESS"},
                {"name": "pii-scan", "conclusion": "SUCCESS"},
                {"name": "test", "conclusion": "SUCCESS"},
            ],
        }

    def test_success_rebase_verifies_then_cleans_branch(self) -> None:
        internal_pr = self.internal_pr()
        events = []
        with (
            mock.patch.object(
                self.reconciler,
                "internal_branch_sha",
                return_value=self.synthetic,
            ),
            mock.patch.object(
                self.reconciler,
                "fetch_main_sha",
                side_effect=[self.base, self.published],
            ),
            mock.patch.object(
                self.reconciler,
                "refresh_internal_pr",
                return_value=internal_pr,
            ),
            mock.patch.object(
                self.reconciler,
                "verify_published_commit",
                side_effect=lambda **kwargs: events.append("verified"),
            ),
            mock.patch.object(
                self.reconciler,
                "delete_internal_branch",
                side_effect=lambda *args: events.append("deleted"),
            ),
            mock.patch.object(
                reconciler_module,
                "gh_json",
                return_value={"merged": True, "sha": self.published},
            ) as api,
        ):
            result = self.reconciler.merge_internal_publication(
                internal_pr,
                number=self.number,
                head_sha=self.head,
                evidence=self.evidence(),
            )
        self.assertEqual(result, self.published)
        self.assertEqual(events, ["verified", "deleted"])
        merge_args = api.call_args.args[0]
        self.assertIn("merge_method=rebase", merge_args)
        self.assertIn(f"sha={self.synthetic}", merge_args)

    def test_base_move_discards_internal_pr_without_merge(self) -> None:
        internal_pr = self.internal_pr()
        with (
            mock.patch.object(
                self.reconciler,
                "internal_branch_sha",
                return_value=self.synthetic,
            ),
            mock.patch.object(
                self.reconciler,
                "fetch_main_sha",
                return_value="6" * 40,
            ),
            mock.patch.object(
                self.reconciler,
                "refresh_internal_pr",
                return_value=internal_pr,
            ),
            mock.patch.object(
                self.reconciler,
                "discard_internal_publication",
            ) as discard,
            mock.patch.object(reconciler_module, "gh_json") as api,
        ):
            with self.assertRaisesRegex(
                reconciler_module.ReconcileError,
                "main advanced",
            ):
                self.reconciler.merge_internal_publication(
                    internal_pr,
                    number=self.number,
                    head_sha=self.head,
                    evidence=self.evidence(),
                )
        discard.assert_called_once_with(
            internal_pr,
            self.number,
            self.head,
        )
        api.assert_not_called()

    def test_merge_revalidates_specific_pr_number_head_and_base(self) -> None:
        variants = {}
        wrong_number = copy.deepcopy(self.internal_pr())
        wrong_number["number"] += 1
        variants["number"] = wrong_number
        wrong_head = copy.deepcopy(self.internal_pr())
        wrong_head["head"]["sha"] = "6" * 40
        variants["head"] = wrong_head
        wrong_base = copy.deepcopy(self.internal_pr())
        wrong_base["base"]["sha"] = "6" * 40
        variants["base"] = wrong_base

        for label, latest in variants.items():
            with self.subTest(label=label):
                internal_pr = self.internal_pr()
                with (
                    mock.patch.object(
                        self.reconciler,
                        "internal_branch_sha",
                        return_value=self.synthetic,
                    ),
                    mock.patch.object(
                        self.reconciler,
                        "refresh_internal_pr",
                        return_value=latest,
                    ) as refresh,
                    mock.patch.object(
                        self.reconciler,
                        "fetch_main_sha",
                    ) as fetch_main,
                    mock.patch.object(
                        reconciler_module,
                        "gh_json",
                    ) as api,
                ):
                    with self.assertRaises(
                        reconciler_module.ReconcileError,
                    ):
                        self.reconciler.merge_internal_publication(
                            internal_pr,
                            number=self.number,
                            head_sha=self.head,
                            evidence=self.evidence(),
                        )
                refresh.assert_called_once_with(self.internal_number)
                fetch_main.assert_not_called()
                api.assert_not_called()

    def test_server_rejects_base_race_before_main_is_changed_by_merge(
        self,
    ) -> None:
        internal_pr = self.internal_pr()
        advanced = "6" * 40
        server_main = {"sha": self.base}

        def merge_api(_args):
            server_main["sha"] = advanced
            return {
                "merged": False,
                "message": "Base branch was modified. Review and try again.",
            }

        with (
            mock.patch.object(
                self.reconciler,
                "internal_branch_sha",
                return_value=self.synthetic,
            ),
            mock.patch.object(
                self.reconciler,
                "fetch_main_sha",
                return_value=self.base,
            ),
            mock.patch.object(
                self.reconciler,
                "refresh_internal_pr",
                return_value=internal_pr,
            ),
            mock.patch.object(
                self.reconciler,
                "verify_published_commit",
            ) as verify,
            mock.patch.object(
                self.reconciler,
                "delete_internal_branch",
            ) as delete,
            mock.patch.object(
                reconciler_module,
                "gh_json",
                side_effect=merge_api,
            ),
        ):
            with self.assertRaisesRegex(
                reconciler_module.ReconcileError,
                "Base branch was modified",
            ):
                self.reconciler.merge_internal_publication(
                    internal_pr,
                    number=self.number,
                    head_sha=self.head,
                    evidence=self.evidence(),
                )
        self.assertEqual(server_main["sha"], advanced)
        self.assertNotEqual(server_main["sha"], self.published)
        verify.assert_not_called()
        delete.assert_not_called()

    def test_branch_collision_fails_closed_without_push(self) -> None:
        branch = reconciler_module.internal_branch_name(
            self.number,
            self.head,
            self.base,
        )
        with (
            mock.patch.object(
                self.reconciler,
                "internal_branch_sha",
                return_value="7" * 40,
            ),
            mock.patch.object(reconciler_module, "run_command") as command,
        ):
            with self.assertRaisesRegex(
                reconciler_module.ReconcileError,
                "branch collision",
            ):
                self.reconciler.ensure_internal_branch(
                    branch,
                    self.synthetic,
                )
        command.assert_not_called()

    def test_duplicate_internal_prs_fail_closed(self) -> None:
        duplicate = copy.deepcopy(self.internal_pr())
        duplicate["number"] += 1
        with mock.patch.object(
            reconciler_module,
            "gh_json",
            return_value=[self.internal_pr(), duplicate],
        ):
            with self.assertRaisesRegex(
                reconciler_module.ReconcileError,
                "multiple internal publication PRs",
            ):
                self.reconciler.internal_publication_pr(
                    self.number,
                    self.head,
                    self.base,
                )

    def test_retry_reuses_existing_internal_pr(self) -> None:
        internal_pr = self.internal_pr()
        with (
            mock.patch.object(
                self.reconciler,
                "internal_publication_pr",
                return_value=internal_pr,
            ),
            mock.patch.object(reconciler_module, "gh_json") as api,
        ):
            result = self.reconciler.create_or_reuse_internal_pr(
                number=self.number,
                head_sha=self.head,
                policy_sha=self.base,
                base_sha=self.base,
                synthetic_commit=self.synthetic,
                synthetic_tree=self.tree,
            )
        self.assertIs(result, internal_pr)
        api.assert_not_called()

    def test_attempt_identity_changes_with_validated_base(self) -> None:
        advanced = "6" * 40
        self.assertNotEqual(
            reconciler_module.internal_branch_name(
                self.number,
                self.head,
                self.base,
            ),
            reconciler_module.internal_branch_name(
                self.number,
                self.head,
                advanced,
            ),
        )
        self.assertNotEqual(
            reconciler_module.internal_pr_title(
                self.number,
                self.head,
                self.base,
            ),
            reconciler_module.internal_pr_title(
                self.number,
                self.head,
                advanced,
            ),
        )

    def test_new_base_ignores_closed_history_without_active_branch(
        self,
    ) -> None:
        with (
            mock.patch.object(
                self.reconciler,
                "internal_branch_sha",
                return_value=None,
            ),
            mock.patch.object(
                self.reconciler,
                "internal_publication_pr_for_branch",
            ) as history,
        ):
            self.assertIsNone(
                self.reconciler.active_internal_publication_pr(
                    self.number,
                    self.head,
                    self.base,
                )
            )
        history.assert_not_called()

    def test_closed_current_attempt_reopens_and_resumes(self) -> None:
        closed = self.internal_pr(state="closed")
        reopened = self.internal_pr(state="open")
        with (
            mock.patch.object(
                self.reconciler,
                "create_or_reuse_internal_pr",
                return_value=reopened,
            ) as reopen,
            mock.patch.object(
                self.reconciler,
                "authorize_internal_main_pr_gate",
                return_value=reopened,
            ) as authorize,
            mock.patch.object(
                self.reconciler,
                "merge_internal_publication",
                return_value=self.published,
            ) as merge,
        ):
            result = self.reconciler.resume_internal_publication(
                closed,
                number=self.number,
                head_sha=self.head,
                base_sha=self.base,
            )
        self.assertEqual(result, self.published)
        reopen.assert_called_once_with(
            number=self.number,
            head_sha=self.head,
            policy_sha=self.base,
            base_sha=self.base,
            synthetic_commit=self.synthetic,
            synthetic_tree=self.tree,
        )
        authorize.assert_called_once_with(
            reopened,
            number=self.number,
            head_sha=self.head,
            evidence=self.evidence(),
        )
        merge.assert_called_once_with(
            reopened,
            number=self.number,
            head_sha=self.head,
            evidence=self.evidence(),
        )

    def test_publication_authorizes_gate_without_pr_event(self) -> None:
        internal_pr = self.internal_pr()
        branch = reconciler_module.internal_branch_name(
            self.number,
            self.head,
            self.base,
        )
        with (
            mock.patch.object(
                self.reconciler,
                "commit_tree",
                return_value=self.tree,
            ),
            mock.patch.object(
                self.reconciler,
                "verify_synthetic_commit",
            ),
            mock.patch.object(
                self.reconciler,
                "ensure_internal_branch",
            ) as ensure,
            mock.patch.object(
                self.reconciler,
                "create_or_reuse_internal_pr",
                return_value=internal_pr,
            ),
            mock.patch.object(
                self.reconciler,
                "authorize_internal_main_pr_gate",
                return_value=internal_pr,
            ) as authorize,
            mock.patch.object(
                self.reconciler,
                "merge_internal_publication",
                return_value=self.published,
            ),
        ):
            result = self.reconciler.publish_synthetic_commit(
                number=self.number,
                head_sha=self.head,
                base_sha=self.base,
                synthetic_commit=self.synthetic,
            )
        self.assertEqual(result, self.published)
        ensure.assert_called_once_with(branch, self.synthetic)
        authorize.assert_called_once_with(
            internal_pr,
            number=self.number,
            head_sha=self.head,
            evidence=self.evidence(),
        )

    def test_internal_gate_verifies_commit_and_base_before_success(self) -> None:
        internal_pr = self.internal_pr()
        events = []
        with (
            mock.patch.object(
                self.reconciler,
                "internal_branch_sha",
                return_value=self.synthetic,
            ),
            mock.patch.object(
                self.reconciler,
                "fetch_internal_branch",
                return_value=self.synthetic,
            ),
            mock.patch.object(
                self.reconciler,
                "verify_synthetic_commit",
                side_effect=lambda *args, **kwargs: events.append("verified"),
            ) as verify,
            mock.patch.object(
                self.reconciler,
                "refresh_internal_pr",
                return_value=internal_pr,
            ),
            mock.patch.object(
                self.reconciler,
                "fetch_main_sha",
                side_effect=lambda: events.append("base-bound") or self.base,
            ),
            mock.patch.object(
                self.reconciler,
                "set_status",
                side_effect=lambda *args, **kwargs: events.append("status"),
            ) as status,
        ):
            result = self.reconciler.authorize_internal_main_pr_gate(
                internal_pr,
                number=self.number,
                head_sha=self.head,
                evidence=self.evidence(),
            )
        self.assertIs(result, internal_pr)
        self.assertEqual(events, ["verified", "base-bound", "status"])
        verify.assert_called_once_with(
            self.synthetic,
            number=self.number,
            head_sha=self.head,
            base_sha=self.base,
            tree_sha=self.tree,
        )
        status.assert_called_once_with(
            self.synthetic,
            "success",
            f"Validated against {self.base[:12]}",
            context=reconciler_module.MAIN_PR_GATE_CONTEXT,
        )

    def test_internal_gate_base_move_never_sets_success(self) -> None:
        internal_pr = self.internal_pr()
        with (
            mock.patch.object(
                self.reconciler,
                "internal_branch_sha",
                return_value=self.synthetic,
            ),
            mock.patch.object(
                self.reconciler,
                "fetch_internal_branch",
                return_value=self.synthetic,
            ),
            mock.patch.object(
                self.reconciler,
                "verify_synthetic_commit",
            ),
            mock.patch.object(
                self.reconciler,
                "refresh_internal_pr",
                return_value=internal_pr,
            ),
            mock.patch.object(
                self.reconciler,
                "fetch_main_sha",
                return_value="6" * 40,
            ),
            mock.patch.object(
                self.reconciler,
                "set_status",
            ) as status,
        ):
            with self.assertRaisesRegex(
                reconciler_module.ReconcileError,
                "main advanced",
            ):
                self.reconciler.authorize_internal_main_pr_gate(
                    internal_pr,
                    number=self.number,
                    head_sha=self.head,
                    evidence=self.evidence(),
                )
        status.assert_not_called()

    def test_closed_stale_attempt_is_cleaned_for_new_base(self) -> None:
        stale_base = "6" * 40
        stale_pr = self.internal_pr(
            evidence_overrides={
                "base_sha": stale_base,
                "policy_sha": stale_base,
            },
            state="closed",
        )
        stale_branch = reconciler_module.internal_branch_name(
            self.number,
            self.head,
            stale_base,
        )
        with (
            mock.patch.object(
                self.reconciler,
                "internal_publication_branches",
                return_value={stale_branch: self.synthetic},
            ),
            mock.patch.object(
                self.reconciler,
                "internal_branch_sha",
                return_value=None,
            ),
            mock.patch.object(
                self.reconciler,
                "internal_publication_pr_for_branch",
                return_value=stale_pr,
            ),
            mock.patch.object(
                self.reconciler,
                "delete_internal_branch",
            ) as delete,
        ):
            cleaned = self.reconciler.cleanup_abandoned_publications(
                self.number,
                self.head,
                keep_base=self.base,
            )
        self.assertEqual(cleaned, (1, False))
        delete.assert_called_once_with(stale_branch, self.synthetic)

    def test_legacy_attempt_is_cleaned_during_identity_upgrade(self) -> None:
        legacy_pr = self.legacy_internal_pr(state="closed")
        legacy_branch = reconciler_module.legacy_internal_branch_name(
            self.number,
            self.head,
        )
        with (
            mock.patch.object(
                self.reconciler,
                "internal_publication_branches",
                return_value={},
            ),
            mock.patch.object(
                self.reconciler,
                "internal_branch_sha",
                return_value=self.synthetic,
            ),
            mock.patch.object(
                self.reconciler,
                "internal_publication_pr_for_branch",
                return_value=legacy_pr,
            ),
            mock.patch.object(
                self.reconciler,
                "delete_internal_branch",
            ) as delete,
        ):
            cleaned = self.reconciler.cleanup_abandoned_publications(
                self.number,
                self.head,
                keep_base=self.base,
            )
        self.assertEqual(cleaned, (1, False))
        delete.assert_called_once_with(legacy_branch, self.synthetic)

    def test_abandoned_attempt_cleanup_is_bounded(self) -> None:
        branches = {
            reconciler_module.internal_branch_name(
                self.number,
                self.head,
                f"{index:040x}",
            ): self.synthetic
            for index in range(
                1,
                reconciler_module.MAX_ABANDONED_PUBLICATION_CLEANUPS + 3,
            )
        }
        with (
            mock.patch.object(
                self.reconciler,
                "internal_publication_branches",
                return_value=branches,
            ),
            mock.patch.object(
                self.reconciler,
                "internal_branch_sha",
                return_value=None,
            ),
            mock.patch.object(
                self.reconciler,
                "internal_publication_pr_for_branch",
                return_value=None,
            ),
            mock.patch.object(
                self.reconciler,
                "remove_orphan_internal_branch",
                return_value=True,
            ) as remove,
        ):
            cleaned = self.reconciler.cleanup_abandoned_publications(
                self.number,
                self.head,
                keep_base=self.base,
            )
        self.assertEqual(
            cleaned,
            (
                reconciler_module.MAX_ABANDONED_PUBLICATION_CLEANUPS,
                True,
            ),
        )
        self.assertEqual(
            remove.call_count,
            reconciler_module.MAX_ABANDONED_PUBLICATION_CLEANUPS,
        )

    def test_retry_removes_canonical_orphan_even_after_base_move(self) -> None:
        message = "\n\n".join([
            f"[state] apply PR #{self.number}",
            f"Source-PR: #{self.number}",
            f"Source-Head: {self.head}",
            "Dreamcatcher-Delta: sha256:" + ("a" * 64),
            "Dreamcatcher-Search-Queries: 1",
        ])
        with (
            mock.patch.object(
                self.reconciler,
                "internal_branch_sha",
                return_value=self.synthetic,
            ),
            mock.patch.object(
                self.reconciler,
                "fetch_internal_branch",
                return_value=self.synthetic,
            ),
            mock.patch.object(
                self.reconciler,
                "commit_parents",
                return_value=["9" * 40],
            ),
            mock.patch.object(
                self.reconciler,
                "commit_tree",
                return_value=self.tree,
            ),
            mock.patch.object(
                self.reconciler,
                "commit_message",
                return_value=message,
            ),
            mock.patch.object(
                self.reconciler,
                "delete_internal_branch",
            ) as delete,
        ):
            self.assertTrue(
                self.reconciler.remove_orphan_internal_branch(
                    self.number,
                    self.head,
                    "9" * 40,
                )
            )
        delete.assert_called_once_with(
            reconciler_module.internal_branch_name(
                self.number,
                self.head,
                "9" * 40,
            ),
            self.synthetic,
        )

    def test_merge_failure_leaves_internal_branch_for_retry(self) -> None:
        internal_pr = self.internal_pr()
        with (
            mock.patch.object(
                self.reconciler,
                "internal_branch_sha",
                return_value=self.synthetic,
            ),
            mock.patch.object(
                self.reconciler,
                "fetch_main_sha",
                return_value=self.base,
            ),
            mock.patch.object(
                self.reconciler,
                "refresh_internal_pr",
                return_value=internal_pr,
            ),
            mock.patch.object(
                self.reconciler,
                "delete_internal_branch",
            ) as delete,
            mock.patch.object(
                reconciler_module,
                "gh_json",
                return_value={"merged": False, "message": "temporarily blocked"},
            ),
        ):
            with self.assertRaisesRegex(
                reconciler_module.ReconcileError,
                "rebase merge failed",
            ):
                self.reconciler.merge_internal_publication(
                    internal_pr,
                    number=self.number,
                    head_sha=self.head,
                    evidence=self.evidence(),
                )
        delete.assert_not_called()

    def test_tree_mismatch_blocks_cleanup_and_source_close(self) -> None:
        internal_pr = self.internal_pr()
        with (
            mock.patch.object(
                self.reconciler,
                "internal_branch_sha",
                return_value=self.synthetic,
            ),
            mock.patch.object(
                self.reconciler,
                "fetch_main_sha",
                side_effect=[self.base, self.published],
            ),
            mock.patch.object(
                self.reconciler,
                "refresh_internal_pr",
                return_value=internal_pr,
            ),
            mock.patch.object(
                self.reconciler,
                "verify_published_commit",
                side_effect=reconciler_module.ReconcileError(
                    "synthetic publication tree does not match"
                ),
            ),
            mock.patch.object(
                self.reconciler,
                "delete_internal_branch",
            ) as delete,
            mock.patch.object(
                reconciler_module,
                "gh_json",
                return_value={"merged": True, "sha": self.published},
            ),
        ):
            with self.assertRaisesRegex(
                reconciler_module.ReconcileError,
                "tree does not match",
            ):
                self.reconciler.merge_internal_publication(
                    internal_pr,
                    number=self.number,
                    head_sha=self.head,
                    evidence=self.evidence(),
                )
        delete.assert_not_called()

    def test_stale_attempt_cleanup_then_retry_progresses_fifo(self) -> None:
        source = {
            "number": self.number,
            "headRefOid": self.head,
            "baseRefName": "main",
            "author": {"login": "alice"},
        }
        with (
            mock.patch.object(
                self.reconciler,
                "details",
                return_value=self.source_details(),
            ),
            mock.patch.object(
                self.reconciler,
                "published_commit",
                return_value=None,
            ),
            mock.patch.object(
                self.reconciler,
                "current_reconciler_state",
                return_value=None,
            ),
            mock.patch.object(
                self.reconciler,
                "current_main_sha",
                return_value=self.base,
            ),
            mock.patch.object(
                self.reconciler,
                "cleanup_abandoned_publications",
                side_effect=[(1, False), (0, False)],
            ),
            mock.patch.object(
                self.reconciler,
                "active_internal_publication_pr",
                return_value=None,
            ),
            mock.patch.object(
                self.reconciler,
                "remove_orphan_internal_branch",
                return_value=False,
            ),
            mock.patch.object(
                self.reconciler,
                "validate",
                return_value=self.synthetic,
            ) as validate,
            mock.patch.object(self.reconciler, "set_status"),
            mock.patch.object(self.reconciler, "note_status"),
            mock.patch.object(
                self.reconciler,
                "publish_synthetic_commit",
                return_value=self.published,
            ) as publish,
            mock.patch.object(
                self.reconciler,
                "finalize_applied_pr",
            ),
        ):
            first = self.reconciler.process(source)
            second = self.reconciler.process(source)
        self.assertEqual(
            (first, second),
            (reconciler_module.BLOCKED, reconciler_module.MERGED),
        )
        validate.assert_called_once_with(source, self.base)
        publish.assert_called_once_with(
            number=self.number,
            head_sha=self.head,
            base_sha=self.base,
            synthetic_commit=self.synthetic,
        )

    def test_legacy_merged_attempt_can_finish_source_cleanup(self) -> None:
        legacy_pr = self.legacy_internal_pr(
            state="closed",
            merged=True,
            merged_at="2026-08-23T12:00:00Z",
        )
        legacy_branch = reconciler_module.legacy_internal_branch_name(
            self.number,
            self.head,
        )
        with (
            mock.patch.object(
                self.reconciler,
                "commit_parents",
                return_value=[self.base],
            ),
            mock.patch.object(
                self.reconciler,
                "internal_publication_pr",
                return_value=None,
            ),
            mock.patch.object(
                self.reconciler,
                "internal_publication_pr_for_branch",
                return_value=legacy_pr,
            ),
            mock.patch.object(
                self.reconciler,
                "verify_published_commit",
            ) as verify,
            mock.patch.object(
                self.reconciler,
                "delete_internal_branch",
            ) as delete,
        ):
            self.reconciler.complete_existing_publication(
                self.number,
                self.head,
                self.published,
            )
        verify.assert_called_once_with(
            published_sha=self.published,
            internal_pr=legacy_pr,
            number=self.number,
            head_sha=self.head,
            evidence=self.evidence(),
        )
        delete.assert_called_once_with(legacy_branch, self.synthetic)

    def test_original_source_closes_only_after_verified_publication(self) -> None:
        events = []
        source = {
            "number": self.number,
            "headRefOid": self.head,
            "baseRefName": "main",
            "author": {"login": "alice"},
        }
        details = self.source_details()
        with (
            mock.patch.object(
                self.reconciler,
                "details",
                return_value=details,
            ),
            mock.patch.object(
                self.reconciler,
                "published_commit",
                return_value=None,
            ),
            mock.patch.object(
                self.reconciler,
                "current_reconciler_state",
                return_value=None,
            ),
            mock.patch.object(
                self.reconciler,
                "current_main_sha",
                return_value=self.base,
            ),
            mock.patch.object(
                self.reconciler,
                "cleanup_abandoned_publications",
                return_value=(0, False),
            ),
            mock.patch.object(
                self.reconciler,
                "active_internal_publication_pr",
                return_value=None,
            ),
            mock.patch.object(
                self.reconciler,
                "remove_orphan_internal_branch",
                return_value=False,
            ),
            mock.patch.object(
                self.reconciler,
                "validate",
                return_value=self.synthetic,
            ),
            mock.patch.object(self.reconciler, "set_status"),
            mock.patch.object(self.reconciler, "note_status"),
            mock.patch.object(
                self.reconciler,
                "publish_synthetic_commit",
                side_effect=lambda **kwargs: (
                    events.append("verified-publication") or self.published
                ),
            ),
            mock.patch.object(
                self.reconciler,
                "finalize_applied_pr",
                side_effect=lambda *args: events.append("source-closed"),
            ),
        ):
            self.assertEqual(
                self.reconciler.process(source),
                reconciler_module.MERGED,
            )
        self.assertEqual(
            events,
            ["verified-publication", "source-closed"],
        )

    def test_publication_failure_blocks_without_source_close(self) -> None:
        source = {
            "number": self.number,
            "headRefOid": self.head,
            "baseRefName": "main",
            "author": {"login": "alice"},
        }
        with (
            mock.patch.object(
                self.reconciler,
                "details",
                return_value=self.source_details(),
            ),
            mock.patch.object(
                self.reconciler,
                "published_commit",
                return_value=None,
            ),
            mock.patch.object(
                self.reconciler,
                "current_reconciler_state",
                return_value=None,
            ),
            mock.patch.object(
                self.reconciler,
                "current_main_sha",
                return_value=self.base,
            ),
            mock.patch.object(
                self.reconciler,
                "cleanup_abandoned_publications",
                return_value=(0, False),
            ),
            mock.patch.object(
                self.reconciler,
                "active_internal_publication_pr",
                return_value=None,
            ),
            mock.patch.object(
                self.reconciler,
                "remove_orphan_internal_branch",
                return_value=False,
            ),
            mock.patch.object(
                self.reconciler,
                "validate",
                return_value=self.synthetic,
            ),
            mock.patch.object(self.reconciler, "set_status"),
            mock.patch.object(self.reconciler, "note_status"),
            mock.patch.object(
                self.reconciler,
                "publish_synthetic_commit",
                side_effect=reconciler_module.ReconcileError(
                    "GitHub API temporarily unavailable"
                ),
            ),
            mock.patch.object(
                self.reconciler,
                "finalize_applied_pr",
            ) as close,
        ):
            self.assertEqual(
                self.reconciler.process(source),
                reconciler_module.BLOCKED,
            )
        close.assert_not_called()

    def test_already_published_source_is_verified_idempotently(self) -> None:
        events = []
        source = {
            "number": self.number,
            "headRefOid": self.head,
            "baseRefName": "main",
        }
        with (
            mock.patch.object(
                self.reconciler,
                "details",
                return_value=self.source_details(),
            ),
            mock.patch.object(
                self.reconciler,
                "published_commit",
                return_value=self.published,
            ),
            mock.patch.object(
                self.reconciler,
                "complete_existing_publication",
                side_effect=lambda *args: events.append("verified-existing"),
            ),
            mock.patch.object(
                self.reconciler,
                "finalize_applied_pr",
                side_effect=lambda *args: events.append("source-closed"),
            ),
            mock.patch.object(self.reconciler, "validate") as validate,
        ):
            self.assertEqual(
                self.reconciler.process(source),
                reconciler_module.SKIPPED,
            )
        validate.assert_not_called()
        self.assertEqual(events, ["verified-existing", "source-closed"])

    def test_internal_queue_excludes_only_canonical_shape(self) -> None:
        canonical = self.queue_pr()
        self.assertTrue(
            self.reconciler.is_internal_publication_pr(canonical)
        )
        legacy = self.queue_pr()
        legacy["title"] = reconciler_module.legacy_internal_pr_title(
            self.number,
            self.head,
        )
        legacy["headRefName"] = (
            reconciler_module.legacy_internal_branch_name(
                self.number,
                self.head,
            )
        )
        self.assertTrue(
            self.reconciler.is_internal_publication_pr(legacy)
        )
        mutations = {
            "title": {"title": "[state] ordinary proposal"},
            "branch": {"headRefName": "state-reconciler/not-canonical"},
            "author": {"author": {"login": "alice"}},
            "cross-repository": {"isCrossRepository": True},
            "body": {"body": canonical["body"] + "\n"},
        }
        for label, changes in mutations.items():
            with self.subTest(label=label):
                candidate = {**canonical, **changes}
                self.assertFalse(
                    self.reconciler.is_internal_publication_pr(candidate)
                )
        ordinary = self.queue_pr(canonical=False)
        ordinary["number"] = 18
        ordinary["createdAt"] = "2026-08-23T09:00:00Z"
        with mock.patch.object(
            reconciler_module,
            "gh_json",
            return_value=[canonical, ordinary],
        ):
            queue = self.reconciler.queue()
        self.assertEqual([item["number"] for item in queue], [18])

    def test_no_direct_main_ref_update_path_remains(self) -> None:
        source = (SCRIPT_DIR / "state_reconciler.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("refs/heads/main", source)
        self.assertNotIn('"update-ref"', source)
        self.assertNotIn("--admin", source)
        self.assertNotIn("pr review", source)
        self.assertNotIn("workflow run main-pr-gate", source)
        self.assertIn("merge_method=rebase", source)
        self.assertIn("refs/heads/{branch}", source)
        self.assertIn("context=MAIN_PR_GATE_CONTEXT", source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
