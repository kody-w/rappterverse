#!/usr/bin/env python3
"""Route the universal protected-main status without executing PR code."""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from pathlib import Path

from state_reconciler import (
    COMMIT_OID_PATTERN,
    INTERNAL_BRANCH_PREFIX,
    MAIN_PR_GATE_CONTEXT,
    ReconcileError,
    has_synthetic_publication_markers,
    is_canonical_internal_pr,
    parse_internal_pr_body,
    parse_synthetic_commit_identity,
)

ORDINARY_DESCRIPTION = "Trusted ordinary main PR gate"
RESERVED_DESCRIPTION = "Reserved publication awaits trusted reconciler"
MALFORMED_DESCRIPTION = "Malformed synthetic publication is reserved"
TRUSTED_STATUS_CREATORS = {"github-actions[bot]"}

ApiCall = Callable[..., object]


class GateError(RuntimeError):
    """The protected-main gate could not make a safe decision."""


class GateBlocked(GateError):
    """The pull request must remain blocked."""


def _pull_request(event: object) -> dict:
    if not isinstance(event, dict):
        raise GateError("workflow event is malformed")
    pr = event.get("pull_request")
    if not isinstance(pr, dict):
        raise GateError("workflow event has no pull request")
    return pr


def _head_ref(pr: dict) -> str:
    return str((pr.get("head") or {}).get("ref") or "")


def _head_sha(pr: dict) -> str:
    return str((pr.get("head") or {}).get("sha") or "")


def _base_ref(pr: dict) -> str:
    return str((pr.get("base") or {}).get("ref") or "")


def _base_sha(pr: dict) -> str:
    return str((pr.get("base") or {}).get("sha") or "")


def _head_commit_metadata(
    api: ApiCall,
    repo: str,
    head_sha: str,
) -> dict:
    value = api(
        f"repos/{repo}/git/commits/{head_sha}",
        method="GET",
    )
    if not isinstance(value, dict) or value.get("sha") != head_sha:
        raise GateError("GitHub returned malformed head commit data")
    message = value.get("message")
    tree = value.get("tree")
    parents = value.get("parents")
    if (
        not isinstance(message, str)
        or not isinstance(tree, dict)
        or not COMMIT_OID_PATTERN.fullmatch(str(tree.get("sha") or ""))
        or not isinstance(parents, list)
    ):
        raise GateError("GitHub returned malformed head commit data")
    parent_shas = []
    for parent in parents:
        if not isinstance(parent, dict):
            raise GateError("GitHub returned malformed head commit data")
        sha = str(parent.get("sha") or "")
        if not COMMIT_OID_PATTERN.fullmatch(sha):
            raise GateError("GitHub returned malformed head commit data")
        parent_shas.append(sha)
    return {
        "message": message,
        "tree_sha": str(tree["sha"]),
        "parent_shas": parent_shas,
    }


def _internal_branch_shas(api: ApiCall, repo: str) -> set[str]:
    encoded = urllib.parse.quote(INTERNAL_BRANCH_PREFIX, safe="")
    value = api(
        f"repos/{repo}/git/matching-refs/heads/{encoded}",
        method="GET",
    )
    if not isinstance(value, list):
        raise GateError("GitHub returned malformed internal branch data")
    if len(value) >= 100:
        raise GateError("too many internal publication branches to route safely")
    shas: set[str] = set()
    expected_prefix = f"refs/heads/{INTERNAL_BRANCH_PREFIX}"
    for item in value:
        if not isinstance(item, dict):
            raise GateError("GitHub returned malformed internal branch data")
        ref = str(item.get("ref") or "")
        target = item.get("object")
        if not isinstance(target, dict):
            raise GateError("GitHub returned malformed internal branch data")
        sha = str(target.get("sha") or "")
        if (
            not ref.startswith(expected_prefix)
            or target.get("type") != "commit"
            or not COMMIT_OID_PATTERN.fullmatch(sha)
        ):
            raise GateError("GitHub returned malformed internal branch data")
        shas.add(sha)
    return shas


def _latest_gate_status(
    api: ApiCall,
    repo: str,
    head_sha: str,
) -> dict | None:
    value = api(
        f"repos/{repo}/commits/{head_sha}/statuses?per_page=100",
        method="GET",
    )
    if not isinstance(value, list):
        raise GateError("GitHub returned malformed commit status data")
    for status in value:
        if (
            isinstance(status, dict)
            and status.get("context") == MAIN_PR_GATE_CONTEXT
        ):
            return status
    return None


def _post_status(
    api: ApiCall,
    repo: str,
    head_sha: str,
    *,
    state: str,
    description: str,
    target_url: str,
):
    api(
        f"repos/{repo}/statuses/{head_sha}",
        method="POST",
        payload={
            "state": state,
            "context": MAIN_PR_GATE_CONTEXT,
            "description": description,
            "target_url": target_url,
        },
    )


def _block_reserved(
    api: ApiCall,
    repo: str,
    head_sha: str,
    target_url: str,
    reason: str,
    *,
    description: str = RESERVED_DESCRIPTION,
):
    _post_status(
        api,
        repo,
        head_sha,
        state="pending",
        description=description,
        target_url=target_url,
    )
    raise GateBlocked(reason)


def route_main_pr(
    event: object,
    *,
    repo: str,
    owner: str,
    api: ApiCall,
    target_url: str,
) -> str:
    pr = _pull_request(event)
    head_ref = _head_ref(pr)
    head_sha = _head_sha(pr)
    if _base_ref(pr) != "main":
        raise GateError("pull request does not target main")
    if not COMMIT_OID_PATTERN.fullmatch(head_sha):
        raise GateError("pull request head is not a commit")

    commit = _head_commit_metadata(api, repo, head_sha)
    if has_synthetic_publication_markers(commit["message"]):
        try:
            identity = parse_synthetic_commit_identity(commit["message"])
        except ReconcileError as exc:
            _block_reserved(
                api,
                repo,
                head_sha,
                target_url,
                f"synthetic publication markers are malformed: {exc}",
                description=MALFORMED_DESCRIPTION,
            )
        if len(commit["parent_shas"]) != 1:
            _block_reserved(
                api,
                repo,
                head_sha,
                target_url,
                "synthetic publication commit ancestry is malformed",
                description=MALFORMED_DESCRIPTION,
            )

        evidence = parse_internal_pr_body(pr.get("body"))
        if (
            evidence is None
            or not is_canonical_internal_pr(pr, repo, owner)
        ):
            raise GateBlocked(
                "synthetic publication commit is reserved for its canonical "
                "internal pull request"
            )
        if (
            identity["source_pr"] != evidence["source_pr"]
            or identity["source_head"] != evidence["source_head"]
            or evidence["synthetic_commit"] != head_sha
            or commit["tree_sha"] != evidence["synthetic_tree"]
            or commit["parent_shas"] != [evidence["base_sha"]]
            or _base_sha(pr) != evidence["base_sha"]
        ):
            raise GateBlocked(
                "synthetic publication commit does not match its canonical "
                "internal pull request evidence"
            )

        status = _latest_gate_status(api, repo, head_sha)
        creator = (status or {}).get("creator") or {}
        expected_description = (
            f"Validated against {evidence['base_sha'][:12]}"
        )
        if (
            not isinstance(status, dict)
            or str(status.get("state") or "").lower() != "success"
            or status.get("description") != expected_description
            or creator.get("login") not in TRUSTED_STATUS_CREATORS
            or creator.get("type") != "Bot"
        ):
            raise GateBlocked(
                "internal publication has no trusted reconciler gate status",
            )
        return "internal-verified"

    internal_shas = _internal_branch_shas(api, repo)
    reserved = (
        head_ref.startswith(INTERNAL_BRANCH_PREFIX)
        or head_sha in internal_shas
    )
    if reserved:
        _block_reserved(
            api,
            repo,
            head_sha,
            target_url,
            "reserved publication branch does not contain canonical "
            "synthetic commit markers",
            description=MALFORMED_DESCRIPTION,
        )
    _post_status(
        api,
        repo,
        head_sha,
        state="success",
        description=ORDINARY_DESCRIPTION,
        target_url=target_url,
    )
    return "ordinary-passed"


def github_api(
    endpoint: str,
    *,
    method: str = "GET",
    payload: dict | None = None,
) -> object:
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise GateError("GITHUB_TOKEN is required")
    api_url = os.environ.get("GITHUB_API_URL", "https://api.github.com")
    data = None
    if payload is not None:
        data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    request = urllib.request.Request(
        f"{api_url.rstrip('/')}/{endpoint.lstrip('/')}",
        data=data,
        method=method,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "rappterverse-main-pr-gate",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace").strip()
        raise GateError(
            f"GitHub API {method} {endpoint} failed: "
            f"{detail or exc.reason}"
        ) from exc
    except urllib.error.URLError as exc:
        raise GateError(
            f"GitHub API {method} {endpoint} failed: {exc.reason}"
        ) from exc
    if not body:
        return None
    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise GateError("GitHub returned malformed JSON") from exc


def main() -> int:
    event_path = os.environ.get("GITHUB_EVENT_PATH")
    repo = os.environ.get("GITHUB_REPOSITORY")
    owner = os.environ.get("GITHUB_REPOSITORY_OWNER")
    server_url = os.environ.get("GITHUB_SERVER_URL")
    run_id = os.environ.get("GITHUB_RUN_ID")
    if not all((event_path, repo, owner, server_url, run_id)):
        print("main-pr-gate refused: workflow environment is incomplete",
              file=sys.stderr)
        return 2
    try:
        event = json.loads(Path(event_path).read_text(encoding="utf-8"))
        result = route_main_pr(
            event,
            repo=repo,
            owner=owner,
            api=github_api,
            target_url=f"{server_url}/{repo}/actions/runs/{run_id}",
        )
    except GateBlocked as exc:
        print(f"main-pr-gate blocked: {exc}", file=sys.stderr)
        return 1
    except (GateError, OSError, json.JSONDecodeError) as exc:
        print(f"main-pr-gate refused: {exc}", file=sys.stderr)
        return 2
    print(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
