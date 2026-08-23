#!/usr/bin/env python3
"""Tests for the protected-main ruleset installer."""

from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path
from unittest import mock

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import install_main_pr_ruleset as ruleset  # noqa: E402


class MainRulesetTests(unittest.TestCase):
    def test_payload_is_exact_pr_only_policy(self) -> None:
        payload = ruleset.desired_ruleset()
        self.assertEqual(payload["target"], "branch")
        self.assertEqual(payload["enforcement"], "active")
        self.assertEqual(payload["bypass_actors"], [])
        self.assertEqual(
            payload["conditions"]["ref_name"],
            {"include": ["refs/heads/main"], "exclude": []},
        )
        self.assertEqual(
            {rule["type"] for rule in payload["rules"]},
            {
                "deletion",
                "non_fast_forward",
                "pull_request",
                "required_status_checks",
            },
        )
        pull_request = next(
            rule for rule in payload["rules"]
            if rule["type"] == "pull_request"
        )
        self.assertEqual(
            pull_request["parameters"]["required_approving_review_count"],
            0,
        )
        self.assertEqual(
            pull_request["parameters"]["allowed_merge_methods"],
            ["rebase"],
        )
        self.assertTrue(
            pull_request["parameters"][
                "require_extra_approval_for_unattributed_changes"
            ]
        )
        status_checks = next(
            rule for rule in payload["rules"]
            if rule["type"] == "required_status_checks"
        )
        self.assertEqual(
            status_checks["parameters"],
            {
                "do_not_enforce_on_create": False,
                "required_status_checks": [{
                    "context": ruleset.MAIN_PR_GATE_CONTEXT,
                }],
                "strict_required_status_checks_policy": True,
            },
        )
        self.assertEqual(ruleset.MAIN_PR_GATE_CONTEXT, "main-pr-gate")

    def test_policy_has_no_direct_push_bypass(self) -> None:
        payload = ruleset.desired_ruleset()
        self.assertEqual(payload["bypass_actors"], [])
        self.assertIn(
            "pull_request",
            {rule["type"] for rule in payload["rules"]},
        )
        status_rule = next(
            rule for rule in payload["rules"]
            if rule["type"] == "required_status_checks"
        )
        self.assertFalse(
            status_rule["parameters"]["do_not_enforce_on_create"]
        )

    def test_live_response_round_trips_idempotently(self) -> None:
        live = {
            "id": 42,
            "name": ruleset.RULESET_NAME,
            "target": "branch",
            "enforcement": "active",
            "bypass_actors": [],
            "source": "owner/repo",
            "source_type": "Repository",
            "node_id": "RRS_live",
            "created_at": "2026-08-23T00:00:00Z",
            "updated_at": "2026-08-23T00:00:00Z",
            "conditions": {
                "ref_name": {
                    "include": ["refs/heads/main"],
                    "exclude": [],
                },
            },
            "rules": [
                {"type": "deletion"},
                {"type": "non_fast_forward"},
                {
                    "type": "pull_request",
                    "parameters": {
                        "allowed_merge_methods": ["rebase"],
                        "dismiss_stale_reviews_on_push": False,
                        "dismissal_restriction": {
                            "enabled": False,
                            "allowed_actors": [],
                        },
                        "require_code_owner_review": False,
                        "require_extra_approval_for_unattributed_changes": True,
                        "require_last_push_approval": False,
                        "required_approving_review_count": 0,
                        "required_review_thread_resolution": False,
                        "required_reviewers": [],
                    },
                },
                {
                    "type": "required_status_checks",
                    "parameters": {
                        "do_not_enforce_on_create": False,
                        "required_status_checks": [{
                            "context": ruleset.MAIN_PR_GATE_CONTEXT,
                            "integration_id": None,
                        }],
                        "strict_required_status_checks_policy": True,
                    },
                },
            ],
        }
        self.assertEqual(
            ruleset.normalize_ruleset(live),
            ruleset.desired_ruleset(),
        )

    def test_extra_required_context_is_configuration_drift(self) -> None:
        drifted = copy.deepcopy(ruleset.desired_ruleset())
        status_rule = next(
            rule for rule in drifted["rules"]
            if rule["type"] == "required_status_checks"
        )
        status_rule["parameters"]["required_status_checks"].append({
            "context": "test",
        })
        with mock.patch.object(
            ruleset,
            "gh_api",
            side_effect=[
                [{"id": 42, "name": ruleset.RULESET_NAME}],
                drifted,
            ],
        ):
            with self.assertRaisesRegex(
                ruleset.RulesetError,
                "configuration drift",
            ):
                ruleset.install_or_verify("owner/repo")

    def test_missing_ruleset_is_created_then_verified(self) -> None:
        desired = ruleset.desired_ruleset()
        with mock.patch.object(
            ruleset,
            "gh_api",
            side_effect=[[], {"id": 42}, desired],
        ) as api:
            result = ruleset.install_or_verify("owner/repo")
        self.assertEqual(result, "installed ruleset main-pr-only-rebase (42)")
        self.assertEqual(api.call_args_list[1].kwargs["method"], "POST")
        self.assertEqual(api.call_args_list[1].kwargs["payload"], desired)

    def test_exact_existing_ruleset_is_idempotent(self) -> None:
        desired = ruleset.desired_ruleset()
        with mock.patch.object(
            ruleset,
            "gh_api",
            side_effect=[[{"id": 42, "name": ruleset.RULESET_NAME}], desired],
        ) as api:
            result = ruleset.install_or_verify("owner/repo")
        self.assertEqual(result, "verified ruleset main-pr-only-rebase (42)")
        self.assertEqual(api.call_count, 2)

    def test_configuration_drift_is_refused(self) -> None:
        drifted = copy.deepcopy(ruleset.desired_ruleset())
        drifted["bypass_actors"] = [{
            "actor_id": 5,
            "actor_type": "RepositoryRole",
            "bypass_mode": "always",
        }]
        with mock.patch.object(
            ruleset,
            "gh_api",
            side_effect=[
                [{"id": 42, "name": ruleset.RULESET_NAME}],
                drifted,
            ],
        ):
            with self.assertRaisesRegex(
                ruleset.RulesetError,
                "bypass actors",
            ):
                ruleset.install_or_verify("owner/repo")

    def test_duplicate_name_is_refused(self) -> None:
        summaries = [
            {"id": 41, "name": ruleset.RULESET_NAME},
            {"id": 42, "name": ruleset.RULESET_NAME},
        ]
        with mock.patch.object(ruleset, "gh_api", return_value=summaries):
            with self.assertRaisesRegex(
                ruleset.RulesetError,
                "duplicate rulesets",
            ):
                ruleset.install_or_verify("owner/repo")

    def test_verify_only_refuses_missing_ruleset(self) -> None:
        with mock.patch.object(ruleset, "gh_api", return_value=[]):
            with self.assertRaisesRegex(
                ruleset.RulesetError,
                "not installed",
            ):
                ruleset.install_or_verify(
                    "owner/repo",
                    verify_only=True,
                )


if __name__ == "__main__":
    unittest.main(verbosity=2)
