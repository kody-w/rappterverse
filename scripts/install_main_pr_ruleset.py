#!/usr/bin/env python3
"""Install or verify the exact PR-only ruleset for ``main``."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys

RULESET_NAME = "main-pr-only-rebase"
MAIN_PR_GATE_CONTEXT = "main-pr-gate"
REPOSITORY_PATTERN = re.compile(
    r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$"
)
PULL_REQUEST_PARAMETERS = {
    "allowed_merge_methods": ["rebase"],
    "dismiss_stale_reviews_on_push": False,
    "require_code_owner_review": False,
    "require_extra_approval_for_unattributed_changes": True,
    "require_last_push_approval": False,
    "required_approving_review_count": 0,
    "required_review_thread_resolution": False,
}
REQUIRED_STATUS_CHECK_PARAMETERS = {
    "do_not_enforce_on_create": False,
    "required_status_checks": [
        {"context": MAIN_PR_GATE_CONTEXT},
    ],
    "strict_required_status_checks_policy": True,
}


class RulesetError(RuntimeError):
    """The ruleset could not be installed or verified safely."""


def desired_ruleset() -> dict:
    return {
        "name": RULESET_NAME,
        "target": "branch",
        "enforcement": "active",
        "bypass_actors": [],
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
                "parameters": dict(PULL_REQUEST_PARAMETERS),
            },
            {
                "type": "required_status_checks",
                "parameters": {
                    **REQUIRED_STATUS_CHECK_PARAMETERS,
                    "required_status_checks": [
                        dict(check)
                        for check in REQUIRED_STATUS_CHECK_PARAMETERS[
                            "required_status_checks"
                        ]
                    ],
                },
            },
        ],
    }


def gh_api(
    endpoint: str,
    *,
    method: str = "GET",
    payload: dict | None = None,
) -> object:
    args = ["gh", "api", endpoint]
    if method != "GET":
        args.extend(["--method", method])
    input_text = None
    if payload is not None:
        args.extend(["--input", "-"])
        input_text = json.dumps(payload, separators=(",", ":"))
    env = os.environ.copy()
    if "GH_TOKEN" not in env and env.get("GITHUB_TOKEN"):
        env["GH_TOKEN"] = env["GITHUB_TOKEN"]
    result = subprocess.run(
        args,
        input=input_text,
        text=True,
        capture_output=True,
        env=env,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise RulesetError(f"{' '.join(args)}: {detail}")
    try:
        return json.loads(result.stdout or "null")
    except json.JSONDecodeError as exc:
        raise RulesetError("GitHub returned malformed ruleset JSON") from exc


def _normalize_pull_request_parameters(parameters: object) -> dict:
    if not isinstance(parameters, dict):
        raise RulesetError("pull_request rule parameters are missing")
    allowed_defaults = {"required_reviewers", "dismissal_restriction"}
    unexpected = set(parameters) - set(PULL_REQUEST_PARAMETERS) - allowed_defaults
    if unexpected:
        raise RulesetError(
            f"pull_request rule has unexpected parameters: {sorted(unexpected)}"
        )
    reviewers = parameters.get("required_reviewers", [])
    if reviewers not in (None, []):
        raise RulesetError("pull_request rule has additional required reviewers")
    dismissal = parameters.get("dismissal_restriction")
    if dismissal not in (None, {}):
        if (
            not isinstance(dismissal, dict)
            or set(dismissal) - {"enabled", "allowed_actors"}
            or dismissal.get("enabled") is not False
            or dismissal.get("allowed_actors", []) != []
        ):
            raise RulesetError(
                "pull_request review dismissal restriction drifted"
            )
    return {
        key: parameters.get(key)
        for key in PULL_REQUEST_PARAMETERS
    }


def _normalize_required_status_checks_parameters(parameters: object) -> dict:
    if not isinstance(parameters, dict):
        raise RulesetError("required_status_checks rule parameters are missing")
    expected = set(REQUIRED_STATUS_CHECK_PARAMETERS)
    unexpected = set(parameters) - expected
    if unexpected:
        raise RulesetError(
            "required_status_checks rule has unexpected parameters: "
            f"{sorted(unexpected)}"
        )
    checks = parameters.get("required_status_checks")
    if not isinstance(checks, list):
        raise RulesetError("required status check contexts are malformed")
    normalized_checks = []
    for check in checks:
        if (
            not isinstance(check, dict)
            or set(check) - {"context", "integration_id"}
            or not isinstance(check.get("context"), str)
            or not check["context"]
            or check.get("integration_id") is not None
        ):
            raise RulesetError("required status check context drifted")
        normalized_checks.append({"context": check["context"]})
    if len({
        check["context"]
        for check in normalized_checks
    }) != len(normalized_checks):
        raise RulesetError("required status check contexts are duplicated")
    return {
        "do_not_enforce_on_create": parameters.get(
            "do_not_enforce_on_create",
            False,
        ),
        "required_status_checks": normalized_checks,
        "strict_required_status_checks_policy": parameters.get(
            "strict_required_status_checks_policy"
        ),
    }


def normalize_ruleset(value: object) -> dict:
    if not isinstance(value, dict):
        raise RulesetError("ruleset details are malformed")
    conditions = value.get("conditions")
    if not isinstance(conditions, dict) or set(conditions) != {"ref_name"}:
        raise RulesetError("ruleset conditions drifted")
    ref_name = conditions.get("ref_name")
    if not isinstance(ref_name, dict):
        raise RulesetError("ruleset ref-name condition is malformed")
    if set(ref_name) != {"include", "exclude"}:
        raise RulesetError("ruleset ref-name condition drifted")

    rules = value.get("rules")
    if not isinstance(rules, list):
        raise RulesetError("ruleset rules are malformed")
    by_type: dict[str, dict] = {}
    for rule in rules:
        if not isinstance(rule, dict):
            raise RulesetError("ruleset contains a malformed rule")
        rule_type = str(rule.get("type") or "")
        if rule_type in by_type:
            raise RulesetError(f"ruleset duplicates the {rule_type} rule")
        by_type[rule_type] = rule
    expected_types = {
        "deletion",
        "non_fast_forward",
        "pull_request",
        "required_status_checks",
    }
    if set(by_type) != expected_types:
        raise RulesetError(
            f"ruleset rule types drifted: {sorted(by_type)}"
        )
    for rule_type in ("deletion", "non_fast_forward"):
        parameters = by_type[rule_type].get("parameters")
        if parameters not in (None, {}):
            raise RulesetError(f"{rule_type} rule parameters drifted")

    bypass_actors = value.get("bypass_actors", [])
    if bypass_actors != []:
        raise RulesetError("ruleset contains bypass actors")
    return {
        "name": value.get("name"),
        "target": value.get("target"),
        "enforcement": value.get("enforcement"),
        "bypass_actors": [],
        "conditions": {
            "ref_name": {
                "include": ref_name.get("include"),
                "exclude": ref_name.get("exclude"),
            },
        },
        "rules": [
            {"type": "deletion"},
            {"type": "non_fast_forward"},
            {
                "type": "pull_request",
                "parameters": _normalize_pull_request_parameters(
                    by_type["pull_request"].get("parameters")
                ),
            },
            {
                "type": "required_status_checks",
                "parameters": _normalize_required_status_checks_parameters(
                    by_type["required_status_checks"].get("parameters")
                ),
            },
        ],
    }


def install_or_verify(repo: str, *, verify_only: bool = False) -> str:
    if not REPOSITORY_PATTERN.fullmatch(repo):
        raise RulesetError("--repo must be OWNER/REPOSITORY")
    summaries = gh_api(
        f"repos/{repo}/rulesets?"
        "includes_parents=false&targets=branch&per_page=100"
    )
    if not isinstance(summaries, list):
        raise RulesetError("GitHub returned malformed ruleset summaries")
    named = [
        item for item in summaries
        if (
            isinstance(item, dict)
            and str(item.get("name") or "").casefold()
            == RULESET_NAME.casefold()
        )
    ]
    if len(named) > 1:
        raise RulesetError(f"duplicate rulesets named {RULESET_NAME}")

    if named:
        ruleset_id = named[0].get("id")
        if not isinstance(ruleset_id, int):
            raise RulesetError("existing ruleset has no numeric id")
        details = gh_api(f"repos/{repo}/rulesets/{ruleset_id}")
        if normalize_ruleset(details) != desired_ruleset():
            raise RulesetError(
                f"ruleset {RULESET_NAME} exists with configuration drift"
            )
        return f"verified ruleset {RULESET_NAME} ({ruleset_id})"

    if verify_only:
        raise RulesetError(f"ruleset {RULESET_NAME} is not installed")
    created = gh_api(
        f"repos/{repo}/rulesets",
        method="POST",
        payload=desired_ruleset(),
    )
    if not isinstance(created, dict) or not isinstance(created.get("id"), int):
        raise RulesetError("GitHub did not return the created ruleset id")
    ruleset_id = created["id"]
    details = gh_api(f"repos/{repo}/rulesets/{ruleset_id}")
    if normalize_ruleset(details) != desired_ruleset():
        raise RulesetError("created ruleset does not match the requested policy")
    return f"installed ruleset {RULESET_NAME} ({ruleset_id})"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo",
        default=os.environ.get("GH_REPO"),
        required=os.environ.get("GH_REPO") is None,
        help="repository in OWNER/REPOSITORY form (defaults to GH_REPO)",
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="refuse to create a missing ruleset",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        print(install_or_verify(args.repo, verify_only=args.verify_only))
    except RulesetError as exc:
        print(f"Ruleset refused: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
