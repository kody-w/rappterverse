#!/usr/bin/env python3
"""Drain validated state pull requests from GitHub as a durable FIFO queue."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(Path(__file__).resolve().parent))
from dreamcatcher_delta import (  # noqa: E402
    DeltaProtocolError,
    capture_worktree,
    verify_manifest_repository,
    write_manifest,
)
from dreamcatcher_promotion import (  # noqa: E402
    PROMOTION_KEY_ENV,
    PromotionEvidenceError,
    telemetry_from_synthetic_commit,
)
from dreamcatcher_shadow import (  # noqa: E402
    DreamcatcherConfigurationError,
    DreamcatcherEnforcementError,
    DreamcatcherRuntimeError,
    observe_candidate,
    resolve_mode,
    telemetry_json,
    telemetry_status_description,
    telemetry_trailers,
)

STATE_PREFIXES = ("state/", "worlds/", "feed/")
REQUIRED_CHECKS = {"state-consensus", "pii-scan", "test"}
MAX_CANDIDATE_FILE_BYTES = 5 * 1024 * 1024
SKIPPED = "skipped"
BLOCKED = "blocked"
REJECTED = "rejected"
MERGED = "merged"
INTERNAL_BRANCH_PREFIX = "state-reconciler/pr-"
INTERNAL_PR_MARKER = "<!-- state-reconciler-publication:v1 -->"
INTERNAL_PR_DESCRIPTION = (
    "Trusted synthetic state publication. The reconciler must rebase-merge "
    "this pull request."
)
MAIN_PR_GATE_CONTEXT = "main-pr-gate"
MAX_ABANDONED_PUBLICATION_CLEANUPS = 8
COMMIT_OID_PATTERN = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
SYNTHETIC_SUBJECT_PATTERN = re.compile(
    r"^\[state\] apply PR #([1-9]\d*)$"
)
SYNTHETIC_PUBLICATION_MARKERS = (
    "[state] apply pr #",
    "source-pr",
    "source-head",
    "policy-sha",
    "validated-base",
    "synthetic-commit",
    "synthetic-tree",
    "dreamcatcher-",
    "state-reconciler-publication",
)


def internal_branch_prefix(number: int, head_sha: str) -> str:
    if number < 1 or not COMMIT_OID_PATTERN.fullmatch(head_sha):
        raise ReconcileError("invalid source identity for internal publication")
    return f"{INTERNAL_BRANCH_PREFIX}{number}-{head_sha}-"


def legacy_internal_branch_name(number: int, head_sha: str) -> str:
    return internal_branch_prefix(number, head_sha)[:-1]


def internal_branch_name(
    number: int,
    head_sha: str,
    base_sha: str,
) -> str:
    if not COMMIT_OID_PATTERN.fullmatch(base_sha):
        raise ReconcileError("invalid base identity for internal publication")
    return f"{internal_branch_prefix(number, head_sha)}{base_sha}"


def internal_branch_base(
    branch: str,
    number: int,
    head_sha: str,
) -> str | None:
    prefix = internal_branch_prefix(number, head_sha)
    if not branch.startswith(prefix):
        return None
    base_sha = branch[len(prefix):]
    return base_sha if COMMIT_OID_PATTERN.fullmatch(base_sha) else None


def internal_pr_title(number: int, head_sha: str, base_sha: str) -> str:
    internal_branch_name(number, head_sha, base_sha)
    return (
        f"[state-reconciler] publish PR #{number} at {head_sha} "
        f"from {base_sha}"
    )


def legacy_internal_pr_title(number: int, head_sha: str) -> str:
    legacy_internal_branch_name(number, head_sha)
    return f"[state-reconciler] publish PR #{number} at {head_sha}"


def internal_pr_body(
    number: int,
    head_sha: str,
    policy_sha: str,
    base_sha: str,
    synthetic_commit: str,
    synthetic_tree: str,
) -> str:
    values = (head_sha, policy_sha, base_sha, synthetic_commit, synthetic_tree)
    if number < 1 or any(
        not COMMIT_OID_PATTERN.fullmatch(value) for value in values
    ):
        raise ReconcileError("invalid internal publication evidence")
    return "\n".join([
        INTERNAL_PR_MARKER,
        INTERNAL_PR_DESCRIPTION,
        "",
        f"Source-PR: #{number}",
        f"Source-Head: {head_sha}",
        f"Policy-SHA: {policy_sha}",
        f"Validated-Base: {base_sha}",
        f"Synthetic-Commit: {synthetic_commit}",
        f"Synthetic-Tree: {synthetic_tree}",
    ])


def parse_internal_pr_body(body: object) -> dict | None:
    if not isinstance(body, str):
        return None
    normalized = body.replace("\r\n", "\n")
    lines = normalized.splitlines()
    if (
        len(lines) != 9
        or lines[0] != INTERNAL_PR_MARKER
        or lines[1] != INTERNAL_PR_DESCRIPTION
        or lines[2] != ""
    ):
        return None
    labels = (
        "Source-PR: #",
        "Source-Head: ",
        "Policy-SHA: ",
        "Validated-Base: ",
        "Synthetic-Commit: ",
        "Synthetic-Tree: ",
    )
    if any(not line.startswith(label) for line, label in zip(lines[3:], labels)):
        return None
    try:
        number = int(lines[3][len(labels[0]):])
    except ValueError:
        return None
    values = {
        "source_pr": number,
        "source_head": lines[4][len(labels[1]):],
        "policy_sha": lines[5][len(labels[2]):],
        "base_sha": lines[6][len(labels[3]):],
        "synthetic_commit": lines[7][len(labels[4]):],
        "synthetic_tree": lines[8][len(labels[5]):],
    }
    try:
        canonical = internal_pr_body(
            values["source_pr"],
            values["source_head"],
            values["policy_sha"],
            values["base_sha"],
            values["synthetic_commit"],
            values["synthetic_tree"],
        )
    except ReconcileError:
        return None
    return values if normalized == canonical else None


def _pr_head_ref(pr: dict) -> str:
    return str(pr.get("headRefName") or (pr.get("head") or {}).get("ref") or "")


def _pr_head_sha(pr: dict) -> str:
    return str(pr.get("headRefOid") or (pr.get("head") or {}).get("sha") or "")


def _pr_base_ref(pr: dict) -> str:
    return str(pr.get("baseRefName") or (pr.get("base") or {}).get("ref") or "")


def _pr_base_sha(pr: dict) -> str:
    return str((pr.get("base") or {}).get("sha") or "")


def _pr_author(pr: dict) -> str:
    return str(
        (pr.get("author") or pr.get("user") or {}).get("login") or ""
    )


def _matches_internal_pr_shape(
    pr: dict,
    repo: str,
    owner: str,
    *,
    branch: str,
    title: str,
) -> bool:
    trusted_authors = {
        owner,
        "github-actions",
        "github-actions[bot]",
        "app/github-actions",
    }
    head_repo = str(
        ((pr.get("head") or {}).get("repo") or {}).get("full_name") or repo
    )
    return (
        _pr_base_ref(pr) == "main"
        and _pr_head_ref(pr) == branch
        and str(pr.get("title") or "") == title
        and not bool(pr.get("isDraft") or pr.get("draft"))
        and not bool(pr.get("isCrossRepository"))
        and head_repo.casefold() == repo.casefold()
        and _pr_author(pr) in trusted_authors
    )


def is_canonical_internal_pr(pr: dict, repo: str, owner: str) -> bool:
    evidence = parse_internal_pr_body(pr.get("body"))
    if evidence is None:
        return False
    return (
        _pr_head_sha(pr) == evidence["synthetic_commit"]
        and _matches_internal_pr_shape(
            pr,
            repo,
            owner,
            branch=internal_branch_name(
                evidence["source_pr"],
                evidence["source_head"],
                evidence["base_sha"],
            ),
            title=internal_pr_title(
                evidence["source_pr"],
                evidence["source_head"],
                evidence["base_sha"],
            ),
        )
    )


def is_legacy_internal_pr(pr: dict, repo: str, owner: str) -> bool:
    evidence = parse_internal_pr_body(pr.get("body"))
    if evidence is None:
        return False
    return (
        _pr_head_sha(pr) == evidence["synthetic_commit"]
        and _matches_internal_pr_shape(
            pr,
            repo,
            owner,
            branch=legacy_internal_branch_name(
                evidence["source_pr"],
                evidence["source_head"],
            ),
            title=legacy_internal_pr_title(
                evidence["source_pr"],
                evidence["source_head"],
            ),
        )
    )


class ReconcileError(RuntimeError):
    """A queue item could not be safely reconciled."""


class ValidationRejected(ReconcileError):
    """The queue item deterministically failed trusted validation."""


def has_synthetic_publication_markers(message: object) -> bool:
    if not isinstance(message, str):
        return False
    folded = message.casefold()
    return any(marker in folded for marker in SYNTHETIC_PUBLICATION_MARKERS)


def parse_synthetic_commit_identity(message: str) -> dict:
    try:
        telemetry_from_synthetic_commit(message)
    except PromotionEvidenceError as exc:
        raise ReconcileError(
            f"synthetic publication provenance is malformed: {exc}"
        ) from exc
    lines = message.splitlines()
    subject = SYNTHETIC_SUBJECT_PATTERN.fullmatch(lines[0] if lines else "")
    if subject is None:
        raise ReconcileError("synthetic publication subject is not canonical")
    trailers: dict[str, str] = {}
    for line in lines[1:]:
        if not line:
            continue
        key, separator, value = line.partition(":")
        if not separator or key in trailers:
            raise ReconcileError(
                "synthetic publication trailers are not canonical"
            )
        trailers[key] = value.strip()

    number = int(subject.group(1))
    if trailers.get("Source-PR") != f"#{number}":
        raise ReconcileError(
            "synthetic publication Source-PR trailer is invalid"
        )
    head_sha = trailers.get("Source-Head", "")
    if not COMMIT_OID_PATTERN.fullmatch(head_sha):
        raise ReconcileError(
            "synthetic publication Source-Head trailer is invalid"
        )
    delta = trailers.get("Dreamcatcher-Delta", "")
    queries = trailers.get("Dreamcatcher-Search-Queries", "")
    if (
        not re.fullmatch(r"sha256:[0-9a-f]{64}", delta)
        or not queries.isdigit()
    ):
        raise ReconcileError(
            "synthetic publication Dreamcatcher evidence is invalid"
        )
    return {
        "source_pr": number,
        "source_head": head_sha,
    }


def validate_synthetic_commit_message(
    message: str,
    number: int,
    head_sha: str,
):
    identity = parse_synthetic_commit_identity(message)
    if identity["source_pr"] != number:
        raise ReconcileError("synthetic publication subject is not canonical")
    if identity["source_head"] != head_sha:
        raise ReconcileError(
            "synthetic publication Source-Head trailer is invalid"
        )


def without_promotion_key() -> dict[str, str]:
    env = os.environ.copy()
    env.pop(PROMOTION_KEY_ENV, None)
    return env


def run_command(
    args: list[str],
    *,
    cwd: Path = BASE_DIR,
    env: dict[str, str] | None = None,
) -> str:
    if env is None:
        env = without_promotion_key()
    result = subprocess.run(
        args,
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}"
        raise ReconcileError(f"{' '.join(args)}: {detail}")
    return result.stdout.strip()


def run_validation(
    args: list[str],
    *,
    env: dict[str, str],
    cwd: Path = BASE_DIR,
    rejection_codes: tuple[int, ...] = (1,),
):
    try:
        result = subprocess.run(
            args,
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except subprocess.TimeoutExpired as exc:
        raise ReconcileError(f"{' '.join(args)} timed out") from exc
    if result.returncode == 0:
        return
    output = f"{result.stdout}\n{result.stderr}".strip()
    detail = output or f"{' '.join(args)} exited with {result.returncode}"
    if result.returncode in rejection_codes:
        raise ValidationRejected(detail)
    raise ReconcileError(detail)


def preflight_candidate(candidate: Path, changed_paths: list[str]):
    root = candidate.resolve()
    for filepath in changed_paths:
        relative = Path(filepath)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValidationRejected(f"{filepath}: path escapes candidate root")
        full_path = candidate / relative
        if full_path.is_symlink():
            raise ValidationRejected(f"{filepath}: symlinks are not allowed")
        try:
            full_path.resolve().relative_to(root)
        except ValueError as exc:
            raise ValidationRejected(f"{filepath}: path escapes candidate root") from exc
        if not full_path.is_file():
            raise ValidationRejected(f"{filepath}: changed path is not a regular file")
        if full_path.stat().st_size > MAX_CANDIDATE_FILE_BYTES:
            raise ValidationRejected(f"{filepath}: changed file exceeds size limit")


def manifest_changed_paths(manifest: dict) -> list[str]:
    paths = []
    for change in manifest["changes"]:
        status = change["status"]
        filepath = change["path"]
        if status == "D":
            raise ValidationRejected(f"{filepath}: state PRs may not delete files")
        if status == "R":
            raise ValidationRejected(
                f"{change['old_path']}: state PRs may not rename files"
            )
        if not filepath.startswith(STATE_PREFIXES):
            raise ValidationRejected(f"{filepath}: path is outside canonical state")
        paths.append(filepath)
    return paths


def capture_verified_pr_manifest(
    candidate: Path,
    base_sha: str,
    head_sha: str,
    *,
    number: int,
    author: str,
) -> dict:
    try:
        manifest = capture_worktree(
            candidate,
            base_sha,
            head=head_sha,
            source_id=f"pr-{number}",
            tile=author,
            include_untracked=False,
            paths=[],
        )
        verify_manifest_repository(manifest, candidate)
        return manifest
    except DeltaProtocolError as exc:
        raise ValidationRejected(
            f"Dreamcatcher delta verification failed: {exc}"
        ) from exc


def planned_inbox_paths(manifest: dict) -> list[str]:
    return [
        path
        for path in manifest["search_plan"]["paths"]
        if path.startswith("state/inbox/") and path.endswith(".json")
    ]


def synthetic_commit_messages(
    number: int,
    head_sha: str,
    manifest: dict,
    telemetry: dict | None = None,
) -> list[str]:
    messages = [
        f"[state] apply PR #{number}",
        f"Source-PR: #{number}",
        f"Source-Head: {head_sha}",
        f"Dreamcatcher-Delta: {manifest['manifest_id']}",
        "Dreamcatcher-Search-Queries: "
        f"{len(manifest['search_plan']['queries'])}",
    ]
    if telemetry is not None:
        if (
            telemetry.get("source_pr") != number
            or telemetry.get("source_head") != head_sha
            or telemetry.get("manifest_id") != manifest["manifest_id"]
            or telemetry.get("search_queries")
            != len(manifest["search_plan"]["queries"])
        ):
            raise ReconcileError(
                "Dreamcatcher telemetry does not match synthetic commit evidence"
            )
        return [
            messages[0],
            "\n".join([*messages[1:], *telemetry_trailers(telemetry)]),
        ]
    return messages


def generate_authenticated_promotion_evidence(
    *,
    evidence_repo: Path,
    evidence_revision: str,
    repository: str,
    target_base: str,
    target_head: str,
) -> dict:
    """Run one secret-bearing evidence scan for candidate evaluation."""
    output = run_command(
        [
            sys.executable,
            str(BASE_DIR / "scripts" / "dreamcatcher_promotion.py"),
            "--attest-bundle",
            "--repo-root",
            str(evidence_repo),
            "--revision",
            evidence_revision,
            "--repository",
            repository,
            "--target-base",
            target_base,
            "--target-head",
            target_head,
        ],
        env=os.environ.copy(),
    )
    try:
        value = json.loads(output)
    except json.JSONDecodeError as exc:
        raise ReconcileError(
            "Dreamcatcher promotion signer returned malformed evidence"
        ) from exc
    if not isinstance(value, dict):
        raise ReconcileError(
            "Dreamcatcher promotion signer returned malformed evidence"
        )
    return value


def generate_promotion_attestation(
    *,
    evidence_repo: Path,
    evidence_revision: str,
    repository: str,
    target_base: str,
    target_head: str,
) -> dict:
    """Return only the attestation for compatibility with existing callers."""
    return generate_authenticated_promotion_evidence(
        evidence_repo=evidence_repo,
        evidence_revision=evidence_revision,
        repository=repository,
        target_base=target_base,
        target_head=target_head,
    )["attestation"]


def gh_json(args: list[str]) -> object:
    output = run_command(["gh", *args])
    return json.loads(output or "null")


def check_name(check: dict) -> str:
    return str(check.get("name") or check.get("context") or "")


def check_passed(check: dict) -> bool:
    value = check.get("conclusion") or check.get("state") or check.get("status")
    return str(value or "").upper() == "SUCCESS"


def checks_state(checks: list[dict]) -> str:
    for name in REQUIRED_CHECKS:
        matching = [check for check in checks if check_name(check) == name]
        if not matching:
            return BLOCKED
        values = {
            str(
                check.get("conclusion")
                or check.get("state")
                or check.get("status")
                or ""
            ).upper()
            for check in matching
        }
        if values & {"PENDING", "IN_PROGRESS", "QUEUED", "EXPECTED", ""}:
            return BLOCKED
        if any(not check_passed(check) for check in matching):
            return REJECTED
    return "ready"


def checks_satisfied(checks: list[dict]) -> bool:
    return checks_state(checks) == "ready"


def has_pending_required_checks(checks: list[dict]) -> bool:
    for check in checks:
        if check_name(check) not in REQUIRED_CHECKS:
            continue
        value = str(
            check.get("conclusion")
            or check.get("state")
            or check.get("status")
            or ""
        ).upper()
        if value in {"PENDING", "IN_PROGRESS", "QUEUED", "EXPECTED", ""}:
            return True
    return False


def reconciler_state(checks: list[dict], policy_sha: str | None = None) -> str | None:
    for check in checks:
        if check_name(check) != "state-reconciler":
            continue
        value = check.get("conclusion") or check.get("state") or check.get("status")
        normalized = str(value or "").upper()
        if normalized == "SUCCESS":
            return MERGED
        if normalized in {"FAILURE", "ERROR"}:
            description = str(check.get("description") or "")
            if policy_sha and f"policy {policy_sha[:12]}" not in description:
                return None
            return REJECTED
    return None


def is_state_only(files: list[dict]) -> bool:
    paths = [str(item.get("path", "")) for item in files]
    return bool(paths) and all(path.startswith(STATE_PREFIXES) for path in paths)


def ordered_queue(prs: list[dict]) -> list[dict]:
    return sorted(prs, key=lambda pr: (str(pr.get("createdAt", "")), int(pr["number"])))


class StateReconciler:
    def __init__(
        self,
        repo: str,
        *,
        dry_run: bool = False,
        dreamcatcher_mode: str | None = None,
    ):
        self.repo = repo
        self.dry_run = dry_run
        self.owner = os.environ.get("REPOSITORY_OWNER", repo.split("/", 1)[0])
        self.policy_sha = run_command(["git", "rev-parse", "HEAD"])
        try:
            self.dreamcatcher_mode = resolve_mode(dreamcatcher_mode)
        except DreamcatcherConfigurationError as exc:
            raise ReconcileError(str(exc)) from exc
        self.last_dreamcatcher_telemetry: dict | None = None
        self._authenticated_evidence_cache: dict[
            tuple[str, str],
            dict,
        ] = {}

    def current_main_sha(self) -> str:
        data = gh_json(["api", f"repos/{self.repo}/git/ref/heads/main"])
        return str(data["object"]["sha"])

    def fetch_main_sha(self) -> str:
        ref = "refs/remotes/state-reconciler/main"
        run_command([
            "git", "fetch", "--force", "--no-tags", "origin", f"main:{ref}",
        ])
        fetched = run_command(["git", "rev-parse", ref])
        current = self.current_main_sha()
        if fetched != current:
            raise ReconcileError("main moved while its publication base was fetched")
        return fetched

    def is_internal_publication_pr(self, pr: dict) -> bool:
        return (
            is_canonical_internal_pr(pr, self.repo, self.owner)
            or is_legacy_internal_pr(pr, self.repo, self.owner)
        )

    def queue(self) -> list[dict]:
        prs = gh_json([
            "pr", "list", "--repo", self.repo, "--state", "open", "--base", "main",
            "--limit", "1000",
            "--json",
            "number,headRefOid,headRefName,baseRefName,author,createdAt,"
            "isDraft,title,body,isCrossRepository",
        ])
        return ordered_queue([
            pr for pr in (prs or [])
            if not self.is_internal_publication_pr(pr)
        ])

    def details(self, number: int) -> dict:
        return gh_json([
            "pr", "view", str(number), "--repo", self.repo,
            "--json",
            "files,statusCheckRollup,isDraft,headRefOid,headRefName,"
            "baseRefName,author,state,isCrossRepository",
        ])

    def internal_branch_sha(self, branch: str) -> str | None:
        encoded = urllib.parse.quote(branch, safe="")
        refs = gh_json([
            "api",
            f"repos/{self.repo}/git/matching-refs/heads/{encoded}",
        ])
        if not isinstance(refs, list):
            raise ReconcileError("GitHub returned malformed branch reference data")
        expected_ref = f"refs/heads/{branch}"
        matches = [item for item in refs if item.get("ref") == expected_ref]
        if len(matches) > 1:
            raise ReconcileError(f"duplicate remote reference for {branch}")
        if not matches:
            return None
        target = matches[0].get("object") or {}
        sha = str(target.get("sha") or "")
        if target.get("type") != "commit" or not COMMIT_OID_PATTERN.fullmatch(sha):
            raise ReconcileError(f"{branch} does not point to a commit")
        return sha

    def internal_publication_pr(
        self,
        number: int,
        head_sha: str,
        base_sha: str,
    ) -> dict | None:
        branch = internal_branch_name(number, head_sha, base_sha)
        return self.internal_publication_pr_for_branch(branch)

    def active_internal_publication_pr(
        self,
        number: int,
        head_sha: str,
        base_sha: str,
    ) -> dict | None:
        branch = internal_branch_name(number, head_sha, base_sha)
        if self.internal_branch_sha(branch) is None:
            return None
        return self.internal_publication_pr_for_branch(branch)

    def internal_publication_pr_for_branch(
        self,
        branch: str,
    ) -> dict | None:
        query = urllib.parse.urlencode({
            "state": "all",
            "head": f"{self.owner}:{branch}",
            "per_page": "100",
        })
        prs = gh_json(["api", f"repos/{self.repo}/pulls?{query}"])
        if not isinstance(prs, list):
            raise ReconcileError("GitHub returned malformed internal PR data")
        exact = [
            pr for pr in prs
            if _pr_head_ref(pr) == branch
            and str(
                ((pr.get("head") or {}).get("repo") or {}).get("full_name")
                or self.repo
            ).casefold() == self.repo.casefold()
        ]
        if len(prs) >= 100 or len(exact) > 1:
            raise ReconcileError(
                f"multiple internal publication PRs use {branch}"
            )
        return exact[0] if exact else None

    def internal_publication_branches(
        self,
        number: int,
        head_sha: str,
    ) -> dict[str, str]:
        prefix = internal_branch_prefix(number, head_sha)
        encoded = urllib.parse.quote(prefix, safe="")
        refs = gh_json([
            "api",
            f"repos/{self.repo}/git/matching-refs/heads/{encoded}",
        ])
        if not isinstance(refs, list):
            raise ReconcileError(
                "GitHub returned malformed publication branch data"
            )
        expected_prefix = f"refs/heads/{prefix}"
        branches: dict[str, str] = {}
        for item in refs:
            if not isinstance(item, dict):
                raise ReconcileError(
                    "GitHub returned malformed publication branch data"
                )
            ref = str(item.get("ref") or "")
            if not ref.startswith(expected_prefix):
                raise ReconcileError(
                    "GitHub returned an unrelated publication branch"
                )
            branch = ref[len("refs/heads/"):]
            if internal_branch_base(branch, number, head_sha) is None:
                raise ReconcileError(
                    f"malformed internal publication branch {branch}"
                )
            target = item.get("object") or {}
            sha = str(target.get("sha") or "")
            if (
                target.get("type") != "commit"
                or not COMMIT_OID_PATTERN.fullmatch(sha)
                or branch in branches
            ):
                raise ReconcileError(
                    f"malformed internal publication branch {branch}"
                )
            branches[branch] = sha
        return branches

    def refresh_internal_pr(self, number: int) -> dict:
        value = gh_json(["api", f"repos/{self.repo}/pulls/{number}"])
        if not isinstance(value, dict):
            raise ReconcileError("GitHub returned malformed internal PR details")
        return value

    def require_internal_pr(
        self,
        pr: dict,
        number: int,
        head_sha: str,
    ) -> dict:
        if not is_canonical_internal_pr(pr, self.repo, self.owner):
            raise ReconcileError("internal publication PR shape is not canonical")
        evidence = parse_internal_pr_body(pr.get("body"))
        if (
            evidence is None
            or evidence["source_pr"] != number
            or evidence["source_head"] != head_sha
        ):
            raise ReconcileError(
                "internal publication PR does not bind the source request"
            )
        return evidence

    def require_legacy_internal_pr(
        self,
        pr: dict,
        number: int,
        head_sha: str,
    ) -> dict:
        evidence = parse_internal_pr_body(pr.get("body"))
        if (
            evidence is None
            or evidence["source_pr"] != number
            or evidence["source_head"] != head_sha
            or not is_legacy_internal_pr(pr, self.repo, self.owner)
        ):
            raise ReconcileError(
                "legacy internal publication PR shape is not canonical"
            )
        return evidence

    def fetch_internal_pr_head(self, pr_number: int) -> str:
        ref = f"refs/remotes/state-reconciler/internal-pr-{pr_number}"
        run_command([
            "git", "fetch", "--force", "--no-tags", "origin",
            f"pull/{pr_number}/head:{ref}",
        ])
        return run_command(["git", "rev-parse", ref])

    def fetch_internal_branch(self, branch: str, number: int) -> str:
        ref = f"refs/remotes/state-reconciler/orphan-pr-{number}"
        run_command([
            "git", "fetch", "--force", "--no-tags", "origin",
            f"refs/heads/{branch}:{ref}",
        ])
        return run_command(["git", "rev-parse", ref])

    @staticmethod
    def commit_tree(commit_sha: str) -> str:
        return run_command(["git", "rev-parse", f"{commit_sha}^{{tree}}"])

    @staticmethod
    def commit_parents(commit_sha: str) -> list[str]:
        output = run_command(["git", "show", "-s", "--format=%P", commit_sha])
        return output.split() if output else []

    @staticmethod
    def commit_message(commit_sha: str) -> str:
        return run_command(["git", "show", "-s", "--format=%B", commit_sha])

    @staticmethod
    def validate_synthetic_message(
        message: str,
        number: int,
        head_sha: str,
    ):
        validate_synthetic_commit_message(message, number, head_sha)

    def verify_synthetic_commit(
        self,
        commit_sha: str,
        *,
        number: int,
        head_sha: str,
        base_sha: str,
        tree_sha: str,
    ) -> str:
        if not COMMIT_OID_PATTERN.fullmatch(commit_sha):
            raise ReconcileError("synthetic publication commit is invalid")
        if self.commit_parents(commit_sha) != [base_sha]:
            raise ReconcileError(
                "synthetic publication commit does not have the validated base"
            )
        if self.commit_tree(commit_sha) != tree_sha:
            raise ReconcileError("synthetic publication tree does not match")
        message = self.commit_message(commit_sha)
        self.validate_synthetic_message(message, number, head_sha)
        return message

    def ensure_internal_branch(self, branch: str, synthetic_commit: str):
        existing = self.internal_branch_sha(branch)
        if existing is not None and existing != synthetic_commit:
            raise ReconcileError(
                f"internal publication branch collision at {branch}"
            )
        if existing is None:
            try:
                run_command([
                    "git", "push", "origin",
                    f"{synthetic_commit}:refs/heads/{branch}",
                ])
            except ReconcileError:
                raced = self.internal_branch_sha(branch)
                if raced != synthetic_commit:
                    raise
        published = self.internal_branch_sha(branch)
        if published != synthetic_commit:
            raise ReconcileError(
                f"internal publication branch {branch} was not created safely"
            )

    def delete_internal_branch(self, branch: str, expected_sha: str):
        current = self.internal_branch_sha(branch)
        if current is None:
            return
        if current != expected_sha:
            raise ReconcileError(
                f"internal publication branch collision at {branch}"
            )
        encoded = urllib.parse.quote(branch, safe="")
        gh_json([
            "api", "--method", "DELETE",
            f"repos/{self.repo}/git/refs/heads/{encoded}",
        ])
        if self.internal_branch_sha(branch) is not None:
            raise ReconcileError(
                f"internal publication branch {branch} was not deleted"
            )

    def create_or_reuse_internal_pr(
        self,
        *,
        number: int,
        head_sha: str,
        policy_sha: str,
        base_sha: str,
        synthetic_commit: str,
        synthetic_tree: str,
    ) -> dict:
        branch = internal_branch_name(number, head_sha, base_sha)
        title = internal_pr_title(number, head_sha, base_sha)
        body = internal_pr_body(
            number,
            head_sha,
            policy_sha,
            base_sha,
            synthetic_commit,
            synthetic_tree,
        )
        existing = self.internal_publication_pr(number, head_sha, base_sha)
        if existing is None:
            try:
                gh_json([
                    "api", "--method", "POST", f"repos/{self.repo}/pulls",
                    "-f", f"title={title}",
                    "-f", f"head={branch}",
                    "-f", "base=main",
                    "-f", f"body={body}",
                ])
            except ReconcileError:
                existing = self.internal_publication_pr(
                    number,
                    head_sha,
                    base_sha,
                )
                if existing is None:
                    raise
            else:
                existing = self.internal_publication_pr(
                    number,
                    head_sha,
                    base_sha,
                )
        if existing is None:
            raise ReconcileError("internal publication PR was not created")
        evidence = self.require_internal_pr(existing, number, head_sha)
        expected = {
            "source_pr": number,
            "source_head": head_sha,
            "policy_sha": policy_sha,
            "base_sha": base_sha,
            "synthetic_commit": synthetic_commit,
            "synthetic_tree": synthetic_tree,
        }
        if evidence != expected:
            raise ReconcileError("internal publication PR evidence collided")
        state = str(existing.get("state") or "").lower()
        merged = bool(existing.get("merged") or existing.get("merged_at"))
        if state == "closed" and not merged:
            existing = gh_json([
                "api", "--method", "PATCH",
                f"repos/{self.repo}/pulls/{existing['number']}",
                "-f", "state=open",
            ])
            evidence = self.require_internal_pr(existing, number, head_sha)
            if (
                evidence != expected
                or str(existing.get("state") or "").lower() != "open"
            ):
                raise ReconcileError(
                    "internal publication PR could not be reopened safely"
                )
        return existing

    def set_status(
        self,
        sha: str,
        state: str,
        description: str,
        *,
        context: str = "state-reconciler",
    ):
        run_command([
            "gh", "api", "--method", "POST", f"repos/{self.repo}/statuses/{sha}",
            "-f", f"state={state}",
            "-f", f"context={context}",
            "-f", f"description={description[:140]}",
        ])

    def authorize_internal_main_pr_gate(
        self,
        internal_pr: dict,
        *,
        number: int,
        head_sha: str,
        evidence: dict,
    ) -> dict:
        if evidence["policy_sha"] != self.policy_sha:
            raise ReconcileError(
                "internal publication policy does not match the loaded policy"
            )
        branch = internal_branch_name(
            number,
            head_sha,
            evidence["base_sha"],
        )
        if self.internal_branch_sha(branch) != evidence["synthetic_commit"]:
            raise ReconcileError(
                f"internal publication branch collision at {branch}"
            )
        fetched = self.fetch_internal_branch(branch, number)
        if fetched != evidence["synthetic_commit"]:
            raise ReconcileError(
                f"internal publication branch {branch} moved while fetched"
            )
        self.verify_synthetic_commit(
            fetched,
            number=number,
            head_sha=head_sha,
            base_sha=evidence["base_sha"],
            tree_sha=evidence["synthetic_tree"],
        )
        internal_number = internal_pr.get("number")
        if not isinstance(internal_number, int) or internal_number < 1:
            raise ReconcileError("internal publication PR number is invalid")
        latest = self.refresh_internal_pr(internal_number)
        latest_evidence = self.require_internal_pr(latest, number, head_sha)
        latest_base_sha = _pr_base_sha(latest)
        if (
            latest_evidence != evidence
            or str(latest.get("state") or "").lower() != "open"
            or _pr_base_ref(latest) != "main"
            or latest_base_sha != evidence["base_sha"]
            or _pr_head_sha(latest) != evidence["synthetic_commit"]
        ):
            raise ReconcileError(
                "internal publication PR changed before gate authorization"
            )
        if self.fetch_main_sha() != evidence["base_sha"]:
            raise ReconcileError(
                "main advanced beyond the validated internal publication base"
            )
        self.set_status(
            evidence["synthetic_commit"],
            "success",
            f"Validated against {evidence['base_sha'][:12]}",
            context=MAIN_PR_GATE_CONTEXT,
        )
        return latest

    def note_status(self, sha: str, state: str, description: str, **kwargs):
        """Record progress, but never let bookkeeping take down the queue.

        GitHub caps a commit at 1000 statuses per context, so any head that is
        re-examined often enough eventually makes POST /statuses return 422
        forever. That is exactly what stopped the world on 2026-08-11: PR #5135
        is the oldest open item, so it is reconciled first every run, and once
        its head hit the cap the unguarded progress write escaped drain() and
        killed the whole sweep. No state merged for 3+ hours.

        A progress or verdict note is telemetry about a decision, not the
        decision. Losing one costs a line in the UI; raising costs every
        queued PR behind it. finalize_applied_pr already treats status writes
        this way -- the advisory paths in process() did not.

        The trusted-validation attestations (state-consensus, pii-scan, test)
        deliberately keep using set_status: those ARE gate evidence, and if
        they cannot be written the PR must not merge.
        """
        try:
            self.set_status(sha, state, description, **kwargs)
        except ReconcileError as exc:
            print(f"Could not record {state} status for {sha[:12]}: {exc}",
                  file=sys.stderr)

    def current_reconciler_state(self, head_sha: str) -> str | None:
        statuses = gh_json([
            "api",
            f"repos/{self.repo}/commits/{head_sha}/statuses?per_page=100",
        ])
        return reconciler_state(statuses or [], self.policy_sha)

    def published_commit(self, number: int, head_sha: str) -> str | None:
        main_sha = self.fetch_main_sha()
        output = run_command([
            "git", "log", main_sha, "--first-parent", "--format=%H",
            "--fixed-strings",
            "--grep", f"Source-PR: #{number}",
            "--grep", f"Source-Head: {head_sha}",
            "--all-match", "--max-count=2",
        ])
        if not output:
            return None
        commits = output.splitlines()
        matches = []
        for commit_sha in commits:
            message = self.commit_message(commit_sha)
            self.validate_synthetic_message(message, number, head_sha)
            matches.append(commit_sha)
        if len(matches) > 1:
            raise ReconcileError(
                f"Source-Head {head_sha} was published more than once"
            )
        return matches[0]

    def verify_published_commit(
        self,
        *,
        published_sha: str,
        internal_pr: dict,
        number: int,
        head_sha: str,
        evidence: dict,
    ):
        internal_sha = self.fetch_internal_pr_head(int(internal_pr["number"]))
        if internal_sha != evidence["synthetic_commit"]:
            raise ReconcileError("internal PR head no longer matches its evidence")
        expected_message = self.verify_synthetic_commit(
            internal_sha,
            number=number,
            head_sha=head_sha,
            base_sha=evidence["base_sha"],
            tree_sha=evidence["synthetic_tree"],
        )
        actual_message = self.verify_synthetic_commit(
            published_sha,
            number=number,
            head_sha=head_sha,
            base_sha=evidence["base_sha"],
            tree_sha=evidence["synthetic_tree"],
        )
        if actual_message != expected_message:
            raise ReconcileError(
                "rebase merge did not preserve canonical promotion evidence"
            )

    def discard_internal_publication(
        self,
        internal_pr: dict,
        number: int,
        head_sha: str,
    ):
        evidence = self.require_internal_pr(internal_pr, number, head_sha)
        if internal_pr.get("merged") or internal_pr.get("merged_at"):
            raise ReconcileError("cannot discard an already merged publication")
        state = str(internal_pr.get("state") or "").lower()
        if state == "open":
            gh_json([
                "api", "--method", "PATCH",
                f"repos/{self.repo}/pulls/{internal_pr['number']}",
                "-f", "state=closed",
            ])
        self.delete_internal_branch(
            internal_branch_name(
                number,
                head_sha,
                evidence["base_sha"],
            ),
            evidence["synthetic_commit"],
        )

    def discard_legacy_internal_publication(
        self,
        internal_pr: dict,
        number: int,
        head_sha: str,
    ):
        evidence = self.require_legacy_internal_pr(
            internal_pr,
            number,
            head_sha,
        )
        if internal_pr.get("merged") or internal_pr.get("merged_at"):
            raise ReconcileError("cannot discard an already merged publication")
        if str(internal_pr.get("state") or "").lower() == "open":
            gh_json([
                "api", "--method", "PATCH",
                f"repos/{self.repo}/pulls/{internal_pr['number']}",
                "-f", "state=closed",
            ])
        self.delete_internal_branch(
            legacy_internal_branch_name(number, head_sha),
            evidence["synthetic_commit"],
        )

    def cleanup_abandoned_publications(
        self,
        number: int,
        head_sha: str,
        *,
        keep_base: str | None,
    ) -> tuple[int, bool]:
        keep_branch = (
            internal_branch_name(number, head_sha, keep_base)
            if keep_base is not None
            else None
        )
        branches = dict(
            self.internal_publication_branches(number, head_sha)
        )
        legacy_branch = legacy_internal_branch_name(number, head_sha)
        legacy_sha = self.internal_branch_sha(legacy_branch)
        if legacy_sha is not None:
            branches[legacy_branch] = legacy_sha
        abandoned = [
            (branch, sha)
            for branch, sha in sorted(
                branches.items()
            )
            if branch != keep_branch
        ]
        batch = abandoned[:MAX_ABANDONED_PUBLICATION_CLEANUPS]
        for branch, _sha in batch:
            if branch == legacy_branch:
                internal_pr = self.internal_publication_pr_for_branch(branch)
                if internal_pr is None:
                    self.remove_legacy_orphan_internal_branch(
                        number,
                        head_sha,
                    )
                else:
                    self.discard_legacy_internal_publication(
                        internal_pr,
                        number,
                        head_sha,
                    )
                continue
            base_sha = internal_branch_base(branch, number, head_sha)
            if base_sha is None:
                raise ReconcileError(
                    f"malformed internal publication branch {branch}"
                )
            internal_pr = self.internal_publication_pr_for_branch(branch)
            if internal_pr is None:
                self.remove_orphan_internal_branch(
                    number,
                    head_sha,
                    base_sha,
                )
            else:
                self.discard_internal_publication(
                    internal_pr,
                    number,
                    head_sha,
                )
        return len(batch), len(abandoned) > len(batch)

    def discard_internal_for_source(self, number: int, head_sha: str):
        cleaned, remaining = self.cleanup_abandoned_publications(
            number,
            head_sha,
            keep_base=None,
        )
        if remaining:
            raise ReconcileError(
                f"cleaned {cleaned} abandoned internal publication attempts; "
                "more remain for retry"
            )

    def remove_legacy_orphan_internal_branch(
        self,
        number: int,
        head_sha: str,
    ) -> bool:
        branch = legacy_internal_branch_name(number, head_sha)
        branch_sha = self.internal_branch_sha(branch)
        if branch_sha is None:
            return False
        fetched = self.fetch_internal_branch(branch, number)
        if fetched != branch_sha:
            raise ReconcileError(
                f"internal publication branch {branch} moved while fetched"
            )
        parents = self.commit_parents(fetched)
        if (
            len(parents) != 1
            or not COMMIT_OID_PATTERN.fullmatch(parents[0])
        ):
            raise ReconcileError(
                "legacy orphan internal publication has invalid ancestry"
            )
        tree_sha = self.commit_tree(fetched)
        self.verify_synthetic_commit(
            fetched,
            number=number,
            head_sha=head_sha,
            base_sha=parents[0],
            tree_sha=tree_sha,
        )
        self.delete_internal_branch(branch, branch_sha)
        return True

    def remove_orphan_internal_branch(
        self,
        number: int,
        head_sha: str,
        base_sha: str,
    ) -> bool:
        branch = internal_branch_name(number, head_sha, base_sha)
        branch_sha = self.internal_branch_sha(branch)
        if branch_sha is None:
            return False
        fetched = self.fetch_internal_branch(branch, number)
        if fetched != branch_sha:
            raise ReconcileError(
                f"internal publication branch {branch} moved while fetched"
            )
        tree_sha = self.commit_tree(fetched)
        self.verify_synthetic_commit(
            fetched,
            number=number,
            head_sha=head_sha,
            base_sha=base_sha,
            tree_sha=tree_sha,
        )
        self.delete_internal_branch(branch, branch_sha)
        return True

    def merge_internal_publication(
        self,
        internal_pr: dict,
        *,
        number: int,
        head_sha: str,
        evidence: dict,
    ) -> str:
        internal_number = internal_pr.get("number")
        if not isinstance(internal_number, int) or internal_number < 1:
            raise ReconcileError("internal publication PR number is invalid")
        branch = internal_branch_name(
            number,
            head_sha,
            evidence["base_sha"],
        )
        state = str(internal_pr.get("state") or "").lower()
        merged = bool(internal_pr.get("merged") or internal_pr.get("merged_at"))
        if merged:
            published = self.published_commit(number, head_sha)
            if published is None:
                raise ReconcileError(
                    "internal PR is merged without canonical main provenance"
                )
            self.verify_published_commit(
                published_sha=published,
                internal_pr=internal_pr,
                number=number,
                head_sha=head_sha,
                evidence=evidence,
            )
            self.delete_internal_branch(branch, evidence["synthetic_commit"])
            return published
        if state != "open":
            raise ReconcileError("internal publication PR is not open")
        if self.internal_branch_sha(branch) != evidence["synthetic_commit"]:
            raise ReconcileError(
                f"internal publication branch collision at {branch}"
            )
        latest = self.refresh_internal_pr(internal_number)
        latest_evidence = self.require_internal_pr(latest, number, head_sha)
        if latest_evidence != evidence:
            raise ReconcileError("internal publication PR changed before merge")
        if (
            latest.get("number") != internal_number
            or str(latest.get("state") or "").lower() != "open"
            or _pr_base_ref(latest) != "main"
            or _pr_base_sha(latest) != evidence["base_sha"]
            or _pr_head_sha(latest) != evidence["synthetic_commit"]
        ):
            raise ReconcileError("internal publication PR changed before merge")
        if self.fetch_main_sha() != evidence["base_sha"]:
            self.discard_internal_publication(latest, number, head_sha)
            raise ReconcileError(
                "main advanced beyond the validated internal publication base"
            )
        # ``sha`` binds the head; the strict required-status rule binds the
        # merge atomically to the current base.
        try:
            result = gh_json([
                "api", "--method", "PUT",
                f"repos/{self.repo}/pulls/{latest['number']}/merge",
                "-f", "merge_method=rebase",
                "-f", f"sha={evidence['synthetic_commit']}",
            ])
        except ReconcileError:
            refreshed = self.refresh_internal_pr(int(latest["number"]))
            if not (refreshed.get("merged") or refreshed.get("merged_at")):
                raise
            result = {"merged": True}
            latest = refreshed
        if not isinstance(result, dict) or result.get("merged") is not True:
            message = (
                str(result.get("message") or "merge was not accepted")
                if isinstance(result, dict)
                else "GitHub returned a malformed merge response"
            )
            raise ReconcileError(f"internal rebase merge failed: {message}")
        published = self.fetch_main_sha()
        response_sha = str(result.get("sha") or "")
        if response_sha and response_sha != published:
            raise ReconcileError(
                "GitHub merge response does not match the fetched main head"
            )
        self.verify_published_commit(
            published_sha=published,
            internal_pr=latest,
            number=number,
            head_sha=head_sha,
            evidence=evidence,
        )
        self.delete_internal_branch(branch, evidence["synthetic_commit"])
        return published

    def publish_synthetic_commit(
        self,
        *,
        number: int,
        head_sha: str,
        base_sha: str,
        synthetic_commit: str,
    ) -> str:
        tree_sha = self.commit_tree(synthetic_commit)
        self.verify_synthetic_commit(
            synthetic_commit,
            number=number,
            head_sha=head_sha,
            base_sha=base_sha,
            tree_sha=tree_sha,
        )
        branch = internal_branch_name(number, head_sha, base_sha)
        self.ensure_internal_branch(branch, synthetic_commit)
        try:
            internal_pr = self.create_or_reuse_internal_pr(
                number=number,
                head_sha=head_sha,
                policy_sha=self.policy_sha,
                base_sha=base_sha,
                synthetic_commit=synthetic_commit,
                synthetic_tree=tree_sha,
            )
            evidence = self.require_internal_pr(
                internal_pr,
                number,
                head_sha,
            )
            internal_pr = self.authorize_internal_main_pr_gate(
                internal_pr,
                number=number,
                head_sha=head_sha,
                evidence=evidence,
            )
        except ReconcileError:
            try:
                if (
                    self.internal_publication_pr(
                        number,
                        head_sha,
                        base_sha,
                    )
                    is None
                ):
                    self.delete_internal_branch(branch, synthetic_commit)
            except ReconcileError as cleanup_error:
                print(
                    "Could not clean orphan internal publication branch: "
                    f"{cleanup_error}",
                    file=sys.stderr,
                )
            raise
        return self.merge_internal_publication(
            internal_pr,
            number=number,
            head_sha=head_sha,
            evidence=evidence,
        )

    def resume_internal_publication(
        self,
        internal_pr: dict,
        *,
        number: int,
        head_sha: str,
        base_sha: str,
    ) -> str:
        evidence = self.require_internal_pr(internal_pr, number, head_sha)
        if (
            evidence["policy_sha"] != self.policy_sha
            or evidence["base_sha"] != base_sha
        ):
            self.discard_internal_publication(internal_pr, number, head_sha)
            raise ReconcileError(
                "discarded stale internal publication after main advanced"
            )
        if (
            str(internal_pr.get("state") or "").lower() == "closed"
            and not (
                internal_pr.get("merged")
                or internal_pr.get("merged_at")
            )
        ):
            internal_pr = self.create_or_reuse_internal_pr(
                number=number,
                head_sha=head_sha,
                policy_sha=evidence["policy_sha"],
                base_sha=evidence["base_sha"],
                synthetic_commit=evidence["synthetic_commit"],
                synthetic_tree=evidence["synthetic_tree"],
            )
            evidence = self.require_internal_pr(
                internal_pr,
                number,
                head_sha,
            )
        internal_pr = self.authorize_internal_main_pr_gate(
            internal_pr,
            number=number,
            head_sha=head_sha,
            evidence=evidence,
        )
        return self.merge_internal_publication(
            internal_pr,
            number=number,
            head_sha=head_sha,
            evidence=evidence,
        )

    def complete_existing_publication(
        self,
        number: int,
        head_sha: str,
        published_sha: str,
    ):
        parents = self.commit_parents(published_sha)
        if (
            len(parents) != 1
            or not COMMIT_OID_PATTERN.fullmatch(parents[0])
        ):
            raise ReconcileError(
                "published Source-Head has invalid base ancestry"
            )
        base_sha = parents[0]
        internal_pr = self.internal_publication_pr(
            number,
            head_sha,
            base_sha,
        )
        legacy = False
        if internal_pr is None:
            internal_pr = self.internal_publication_pr_for_branch(
                legacy_internal_branch_name(number, head_sha)
            )
            legacy = internal_pr is not None
        if internal_pr is None:
            raise ReconcileError(
                "published Source-Head has no canonical internal PR"
            )
        evidence = (
            self.require_legacy_internal_pr(
                internal_pr,
                number,
                head_sha,
            )
            if legacy
            else self.require_internal_pr(
                internal_pr,
                number,
                head_sha,
            )
        )
        if evidence["base_sha"] != base_sha:
            raise ReconcileError(
                "published Source-Head internal PR base drifted"
            )
        if not (internal_pr.get("merged") or internal_pr.get("merged_at")):
            raise ReconcileError(
                "published Source-Head is not backed by a merged internal PR"
            )
        self.verify_published_commit(
            published_sha=published_sha,
            internal_pr=internal_pr,
            number=number,
            head_sha=head_sha,
            evidence=evidence,
        )
        self.delete_internal_branch(
            (
                legacy_internal_branch_name(number, head_sha)
                if legacy
                else internal_branch_name(
                    number,
                    head_sha,
                    evidence["base_sha"],
                )
            ),
            evidence["synthetic_commit"],
        )

    def finalize_applied_pr(self, number: int, head_sha: str, commit_sha: str):
        try:
            self.set_status(head_sha, "success", f"Applied atomically as {commit_sha[:12]}")
        except ReconcileError as exc:
            print(f"Could not record applied status for PR #{number}: {exc}", file=sys.stderr)
        latest = self.details(number)
        if latest.get("state") != "OPEN":
            return
        if (
            latest.get("headRefOid") != head_sha
            or latest.get("baseRefName") != "main"
            or latest.get("isDraft")
            or not is_state_only(latest.get("files") or [])
        ):
            raise ReconcileError(
                f"source PR #{number} changed before publication finalization"
            )
        run_command([
            "gh", "pr", "close", str(number), "--repo", self.repo,
            "--comment", f"Applied atomically to main as `{commit_sha}`.",
        ])
        branch = str(latest.get("headRefName") or "")
        author = str((latest.get("author") or {}).get("login") or "")
        trusted_branch_authors = {
            self.owner,
            "github-actions",
            "app/github-actions",
        }
        if (
            branch.startswith("auto/")
            and author in trusted_branch_authors
            and not latest.get("isCrossRepository")
        ):
            encoded_branch = urllib.parse.quote(branch, safe="")
            try:
                run_command([
                    "gh", "api", "--method", "DELETE",
                    f"repos/{self.repo}/git/refs/heads/{encoded_branch}",
                ])
            except ReconcileError as exc:
                print(
                    f"Could not delete source branch for PR #{number}: {exc}",
                    file=sys.stderr,
                )

    def finalize_rejected_pr(self, number: int, head_sha: str, reason: str):
        """Close a proposal that current policy deterministically rejected.

        Leaving terminal failures open makes the queue look occupied forever
        and forces every future sweep to rediscover the same impossible merge.
        Closing preserves the branch and full audit trail; an author can rebase
        and submit a fresh proposal against current state.
        """
        try:
            latest = self.details(number)
            if (
                latest.get("state") == "OPEN"
                and latest.get("headRefOid") == head_sha
                and latest.get("baseRefName") == "main"
                and not latest.get("isDraft")
                and is_state_only(latest.get("files") or [])
            ):
                detail = " ".join(str(reason).split())[:500]
                run_command([
                    "gh", "pr", "close", str(number), "--repo", self.repo,
                    "--comment",
                    "Closed because the current state-consensus policy "
                    f"deterministically rejected this proposal.\n\nReason: {detail}\n\n"
                    "Rebase the change onto current `main` and open a fresh PR "
                    "if the action is still relevant.",
                ])
        except ReconcileError as exc:
            print(f"Could not close rejected PR #{number}: {exc}", file=sys.stderr)

    def observe_dreamcatcher(
        self,
        candidate: Path,
        manifest: dict,
        *,
        number: int,
        base_sha: str,
        head_sha: str,
    ) -> dict | None:
        if (
            self.dreamcatcher_mode == "enforce"
            and os.environ.get("DREAMCATCHER_PROMOTION_SUMMARY")
        ):
            raise ReconcileError(
                "caller-authored Dreamcatcher promotion summaries are not accepted"
            )
        try:
            authenticated_evidence = None
            if self.dreamcatcher_mode == "enforce":
                cache_key = (base_sha, head_sha)
                authenticated_evidence = self._authenticated_evidence_cache.get(
                    cache_key
                )
                if authenticated_evidence is None:
                    authenticated_evidence = (
                        generate_authenticated_promotion_evidence(
                            evidence_repo=BASE_DIR,
                            evidence_revision=self.policy_sha,
                            repository=self.repo,
                            target_base=base_sha,
                            target_head=head_sha,
                        )
                    )
                    self._authenticated_evidence_cache[cache_key] = (
                        authenticated_evidence
                    )
            return observe_candidate(
                candidate,
                manifest,
                mode=self.dreamcatcher_mode,
                source_pr=number,
                source_head=head_sha,
                authenticated_promotion_evidence=authenticated_evidence,
                target_repository=self.repo,
                target_base=base_sha,
            )
        except DreamcatcherEnforcementError as exc:
            if self.dreamcatcher_mode == "shadow":
                print(
                    "Dreamcatcher shadow observation unavailable: "
                    f"{type(exc).__name__}",
                    file=sys.stderr,
                )
                return None
            raise ValidationRejected(str(exc)) from exc
        except (DreamcatcherConfigurationError, DreamcatcherRuntimeError) as exc:
            if self.dreamcatcher_mode == "shadow":
                print(
                    "Dreamcatcher shadow observation unavailable: "
                    f"{type(exc).__name__}",
                    file=sys.stderr,
                )
                return None
            raise ReconcileError(str(exc)) from exc
        except ReconcileError:
            raise
        except Exception as exc:
            if self.dreamcatcher_mode == "shadow":
                print(
                    "Dreamcatcher shadow observation unavailable: "
                    f"{type(exc).__name__}",
                    file=sys.stderr,
                )
                return None
            raise ReconcileError(
                "Dreamcatcher enforcement is temporarily unavailable"
            ) from exc

    def validate(self, pr: dict, base_sha: str) -> str:
        number = int(pr["number"])
        head_sha = str(pr["headRefOid"])
        self.last_dreamcatcher_telemetry = None
        author = str((pr.get("author") or {}).get("login") or "")
        if not author:
            raise ReconcileError(f"PR #{number} author is unavailable")
        ref = f"refs/remotes/state-queue/pr-{number}"
        run_command(["git", "fetch", "--force", "--no-tags", "origin", f"pull/{number}/head:{ref}"])
        fetched_sha = run_command(["git", "rev-parse", ref])
        if fetched_sha != head_sha:
            raise ReconcileError(f"PR #{number} head changed before reconciliation")

        temp_root = Path(tempfile.mkdtemp(prefix=f"rappterverse-pr-{number}-"))
        candidate = temp_root / "candidate"
        try:
            run_command(["git", "worktree", "add", "--detach", str(candidate), base_sha])
            try:
                run_command(
                    [
                        "git",
                        "-c", "user.name=rappterverse-reconciler",
                        "-c",
                        "user.email=41898282+github-actions[bot]@users.noreply.github.com",
                        "merge", "--no-commit", "--no-ff", head_sha,
                    ],
                    cwd=candidate,
                )
            except ReconcileError as exc:
                detail = str(exc).lower()
                if "conflict" in detail or "automatic merge failed" in detail:
                    raise ValidationRejected(f"synthetic merge conflict: {exc}") from exc
                raise
            manifest = capture_verified_pr_manifest(
                candidate,
                base_sha,
                head_sha,
                number=number,
                author=author,
            )
            changed_paths = manifest_changed_paths(manifest)
            manifest_path = temp_root / "dreamcatcher-delta.json"
            write_manifest(manifest_path, manifest)
            preflight_candidate(candidate, changed_paths)
            env = without_promotion_key()
            env.update({
                "VALIDATION_REPO_ROOT": str(candidate),
                "VALIDATION_BASE_SHA": base_sha,
                "VALIDATION_HEAD_SHA": head_sha,
                "VALIDATION_REQUIRE_RELEVANT": "1",
                "VALIDATION_REQUIRE_AUTH": "1",
                "REPOSITORY_OWNER": self.owner,
                "PR_AUTHOR": author,
            })
            delta_env = env.copy()
            delta_env.update({
                "DREAMCATCHER_DELTA_MANIFEST": str(manifest_path),
                "DREAMCATCHER_DELTA_SOURCE_ID": f"pr-{number}",
                "DREAMCATCHER_DELTA_TILE": author,
            })
            run_validation(
                [sys.executable, str(BASE_DIR / "scripts" / "validate_action.py")],
                env=env,
            )
            run_validation(
                [sys.executable, str(BASE_DIR / "scripts" / "validate_delta.py")],
                env=delta_env,
            )
            self.last_dreamcatcher_telemetry = self.observe_dreamcatcher(
                candidate,
                manifest,
                number=number,
                base_sha=base_sha,
                head_sha=head_sha,
            )

            if planned_inbox_paths(manifest):
                materialize_env = delta_env.copy()
                materialize_env["RAPPTERVERSE_REPO_ROOT"] = str(candidate)
                run_validation(
                    [sys.executable, str(BASE_DIR / "scripts" / "apply_deltas.py")],
                    env=materialize_env,
                    cwd=candidate,
                )
                run_command(
                    ["git", "add", "-A", "state", "worlds", "feed"],
                    cwd=candidate,
                )

            run_validation([
                sys.executable,
                str(BASE_DIR / "scripts" / "reconcile_derived_state.py"),
                "--repo-root",
                str(candidate),
            ], env=env, cwd=candidate)
            run_command(
                ["git", "add", "-A", "state", "worlds"],
                cwd=candidate,
            )

            run_validation([
                sys.executable,
                str(candidate / "scripts" / "generate_chronicles.py"),
            ], env=env, cwd=candidate)
            run_validation([
                sys.executable,
                str(candidate / "scripts" / "build_agent_registry.py"),
                "--fill-missing",
            ], env=env, cwd=candidate)
            run_validation([
                sys.executable,
                str(BASE_DIR / "scripts" / "generate_state_snapshot.py"),
                "--repo-root",
                str(candidate),
            ], env=env, cwd=candidate)
            run_validation([
                sys.executable,
                str(candidate / "scripts" / "generate_dashboard.py"),
            ], env=env, cwd=candidate)
            run_command([
                "git", "add",
                "README.md",
                "state/chronicles.json",
                "state/snapshot.json",
                "docs/chronicles",
                "agents",
            ], cwd=candidate)

            run_validation([
                sys.executable,
                str(BASE_DIR / "scripts" / "validate_action.py"),
                "--validate-state",
            ], env=env, cwd=candidate)

            run_validation([
                sys.executable,
                str(BASE_DIR / "scripts" / "pii_scan.py"),
                "--repo-root",
                str(candidate),
                "--paths",
                "README.md",
                "state",
                "worlds",
                "feed",
                "docs/chronicles",
                "agents",
            ], env=env)
            run_validation([
                sys.executable,
                str(candidate / "scripts" / "test_state_integrity.py"),
            ], env=env, cwd=candidate)

            tree_sha = run_command(["git", "write-tree"], cwd=candidate)
            commit_env = env.copy()
            commit_env.update({
                "GIT_AUTHOR_NAME": "rappterverse-bot",
                "GIT_AUTHOR_EMAIL": "41898282+github-actions[bot]@users.noreply.github.com",
                "GIT_COMMITTER_NAME": "rappterverse-bot",
                "GIT_COMMITTER_EMAIL": "41898282+github-actions[bot]@users.noreply.github.com",
            })
            commit_args = ["git", "commit-tree", tree_sha, "-p", base_sha]
            try:
                commit_messages = synthetic_commit_messages(
                    number,
                    head_sha,
                    manifest,
                    self.last_dreamcatcher_telemetry,
                )
            except Exception as exc:
                if self.dreamcatcher_mode != "shadow":
                    raise ReconcileError(
                        "Dreamcatcher enforcement evidence could not be recorded"
                    ) from exc
                print(
                    "Dreamcatcher shadow telemetry could not be attached: "
                    f"{type(exc).__name__}",
                    file=sys.stderr,
                )
                self.last_dreamcatcher_telemetry = None
                commit_messages = synthetic_commit_messages(
                    number,
                    head_sha,
                    manifest,
                )
            for message in commit_messages:
                commit_args.extend(["-m", message])
            return run_command(commit_args, cwd=candidate, env=commit_env)
        finally:
            if candidate.exists():
                subprocess.run(
                    ["git", "worktree", "remove", "--force", str(candidate)],
                    cwd=BASE_DIR,
                    env=without_promotion_key(),
                    capture_output=True,
                )
            shutil.rmtree(temp_root, ignore_errors=True)

    def process(self, pr: dict) -> str:
        number = int(pr["number"])
        details = self.details(number)
        if (
            pr.get("baseRefName") != "main"
            or details.get("baseRefName") != "main"
            or details.get("state") != "OPEN"
            or details.get("isDraft")
            or not is_state_only(details.get("files") or [])
        ):
            return SKIPPED
        if details.get("headRefOid") != pr.get("headRefOid"):
            return BLOCKED
        head_sha = str(pr["headRefOid"])
        try:
            published = self.published_commit(number, head_sha)
            if published:
                if not self.dry_run:
                    self.complete_existing_publication(
                        number,
                        head_sha,
                        published,
                    )
                    self.finalize_applied_pr(number, head_sha, published)
                return SKIPPED
            terminal = self.current_reconciler_state(head_sha)
            if terminal == REJECTED:
                if not self.dry_run:
                    self.discard_internal_for_source(number, head_sha)
                    self.finalize_rejected_pr(
                        number,
                        head_sha,
                        "a current-policy state-reconciler verdict already "
                        "rejected it",
                    )
                return REJECTED
            if has_pending_required_checks(
                details.get("statusCheckRollup") or []
            ):
                return BLOCKED

            base_sha = self.current_main_sha()
            if base_sha != self.policy_sha:
                return BLOCKED
            if not self.dry_run:
                self.note_status(
                    head_sha,
                    "pending",
                    f"Reconciling against {base_sha[:12]}",
                )
                cleaned, remaining = self.cleanup_abandoned_publications(
                    number,
                    head_sha,
                    keep_base=base_sha,
                )
                if cleaned:
                    suffix = "; more remain" if remaining else ""
                    raise ReconcileError(
                        f"removed {cleaned} stale internal publication "
                        f"attempt(s){suffix}; retry"
                    )
            internal_pr = (
                None
                if self.dry_run
                else self.active_internal_publication_pr(
                    number,
                    head_sha,
                    base_sha,
                )
            )
            merge_commit = None
            if internal_pr is None:
                if (
                    not self.dry_run
                    and self.remove_orphan_internal_branch(
                        number,
                        head_sha,
                        base_sha,
                    )
                ):
                    raise ReconcileError(
                        "removed an orphan internal publication branch; retry"
                    )
                merge_commit = self.validate(pr, base_sha)
                telemetry = self.last_dreamcatcher_telemetry
                if telemetry is not None:
                    try:
                        print(
                            "DREAMCATCHER_TELEMETRY="
                            f"{telemetry_json(telemetry)}"
                        )
                        if not self.dry_run:
                            self.note_status(
                                head_sha,
                                "success",
                                telemetry_status_description(telemetry),
                                context=f"dreamcatcher-{telemetry['mode']}",
                            )
                    except Exception as exc:
                        print(
                            "Could not publish Dreamcatcher telemetry: "
                            f"{type(exc).__name__}",
                            file=sys.stderr,
                        )
                if not self.dry_run:
                    self.set_status(
                        head_sha,
                        "success",
                        "Trusted synthetic state validation passed",
                        context="state-consensus",
                    )
                    self.set_status(
                        head_sha,
                        "success",
                        "Trusted differential PII scan passed",
                        context="pii-scan",
                    )
                    self.set_status(
                        head_sha,
                        "success",
                        "Trusted synthetic integrity tests passed",
                        context="test",
                    )
            latest = self.details(number)
            if (
                latest.get("state") != "OPEN"
                or latest.get("isDraft")
                or latest.get("baseRefName") != "main"
                or latest.get("headRefOid") != head_sha
                or not is_state_only(latest.get("files") or [])
            ):
                raise ReconcileError("PR changed or closed during reconciliation")
            if not self.dry_run:
                readiness = checks_state(latest.get("statusCheckRollup") or [])
                if readiness == REJECTED:
                    raise ValidationRejected("A required PR-head check failed")
                if readiness != "ready":
                    raise ReconcileError("Required PR-head checks are not current")
            if self.current_main_sha() != base_sha:
                raise ReconcileError("main advanced during reconciliation")
            if self.dry_run:
                print(f"[dry-run] PR #{number} validated against {base_sha[:12]}")
                return MERGED
            if internal_pr is None:
                if merge_commit is None:
                    raise ReconcileError(
                        "synthetic publication commit is unavailable"
                    )
                published = self.publish_synthetic_commit(
                    number=number,
                    head_sha=head_sha,
                    base_sha=base_sha,
                    synthetic_commit=merge_commit,
                )
            else:
                published = self.resume_internal_publication(
                    internal_pr,
                    number=number,
                    head_sha=head_sha,
                    base_sha=base_sha,
                )
            print(f"Merged state PR #{number} at {head_sha[:12]}")
            self.finalize_applied_pr(number, head_sha, published)
            return MERGED
        except ValidationRejected as exc:
            if not self.dry_run:
                try:
                    self.discard_internal_for_source(number, head_sha)
                except ReconcileError as cleanup_error:
                    self.note_status(
                        head_sha,
                        "pending",
                        f"internal publication cleanup blocked: {cleanup_error}",
                    )
                    print(
                        f"Blocked PR #{number}: {cleanup_error}",
                        file=sys.stderr,
                    )
                    return BLOCKED
                self.note_status(
                    head_sha,
                    "failure",
                    f"policy {self.policy_sha[:12]} rejected: {exc}",
                )
                self.finalize_rejected_pr(number, head_sha, str(exc))
            print(f"Rejected PR #{number}: {exc}", file=sys.stderr)
            return REJECTED
        except ReconcileError as exc:
            if not self.dry_run:
                self.note_status(head_sha, "pending", str(exc))
            print(f"Blocked PR #{number}: {exc}", file=sys.stderr)
            return BLOCKED

    def drain(self, max_items: int) -> int:
        if not self.dry_run and self.current_main_sha() != self.policy_sha:
            raise ReconcileError("main advanced beyond the loaded reconciliation policy")
        processed = 0
        for pr in self.queue():
            if processed >= max_items:
                break
            result = self.process(pr)
            if result == MERGED:
                processed += 1
            elif result == BLOCKED:
                print(f"State queue blocked by PR #{pr['number']} pending current checks")
                break
        print(f"State queue reconciliation complete: {processed} item(s) processed")
        return processed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=os.environ.get("GH_REPO", "kody-w/rappterverse"))
    parser.add_argument("--max-items", type=int, default=50)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.max_items < 1:
        raise SystemExit("--max-items must be positive")
    StateReconciler(args.repo, dry_run=args.dry_run).drain(args.max_items)
    return 0


if __name__ == "__main__":
    sys.exit(main())
