#!/usr/bin/env python3
"""Drain validated state pull requests from GitHub as a durable FIFO queue."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent.resolve()
STATE_PREFIXES = ("state/", "worlds/", "feed/")
REQUIRED_CHECKS = {"state-consensus", "pii-scan", "test"}
MAX_CANDIDATE_FILE_BYTES = 5 * 1024 * 1024
SKIPPED = "skipped"
BLOCKED = "blocked"
REJECTED = "rejected"
MERGED = "merged"


class ReconcileError(RuntimeError):
    """A queue item could not be safely reconciled."""


class ValidationRejected(ReconcileError):
    """The queue item deterministically failed trusted validation."""


def run_command(
    args: list[str],
    *,
    cwd: Path = BASE_DIR,
    env: dict[str, str] | None = None,
) -> str:
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


def candidate_changed_paths(base_sha: str, head_sha: str, candidate: Path) -> list[str]:
    output = run_command([
        "git", "diff", "--name-status", "--no-renames",
        f"{base_sha}...{head_sha}", "--",
    ], cwd=candidate)
    paths = []
    for line in output.splitlines():
        status, separator, filepath = line.partition("\t")
        if not separator or not filepath:
            raise ValidationRejected(f"Unparseable changed-path record: {line}")
        if status == "D":
            raise ValidationRejected(f"{filepath}: state PRs may not delete files")
        if not filepath.startswith(STATE_PREFIXES):
            raise ValidationRejected(f"{filepath}: path is outside canonical state")
        paths.append(filepath)
    return paths


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
    def __init__(self, repo: str, *, dry_run: bool = False):
        self.repo = repo
        self.dry_run = dry_run
        self.owner = os.environ.get("REPOSITORY_OWNER", repo.split("/", 1)[0])
        self.policy_sha = run_command(["git", "rev-parse", "HEAD"])

    def current_main_sha(self) -> str:
        data = gh_json(["api", f"repos/{self.repo}/git/ref/heads/main"])
        return str(data["object"]["sha"])

    def queue(self) -> list[dict]:
        prs = gh_json([
            "pr", "list", "--repo", self.repo, "--state", "open", "--base", "main",
            "--limit", "1000",
            "--json", "number,headRefOid,baseRefName,author,createdAt,isDraft,title",
        ])
        return ordered_queue(prs or [])

    def details(self, number: int) -> dict:
        return gh_json([
            "pr", "view", str(number), "--repo", self.repo,
            "--json",
            "files,statusCheckRollup,isDraft,headRefOid,headRefName,"
            "baseRefName,author,state,isCrossRepository",
        ])

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

    def current_reconciler_state(self, head_sha: str) -> str | None:
        statuses = gh_json([
            "api",
            f"repos/{self.repo}/commits/{head_sha}/statuses?per_page=100",
        ])
        return reconciler_state(statuses or [], self.policy_sha)

    def published_commit(self, number: int, head_sha: str) -> str | None:
        output = run_command([
            "git", "log", "HEAD", "--format=%H%x00%B%x00", "--fixed-strings",
            "--grep", f"Source-Head: {head_sha}", "--max-count=1",
        ])
        if not output or f"Source-PR: #{number}" not in output:
            return None
        return output.split("\x00", 1)[0]

    def finalize_applied_pr(self, number: int, head_sha: str, commit_sha: str):
        try:
            self.set_status(head_sha, "success", f"Applied atomically as {commit_sha[:12]}")
        except ReconcileError as exc:
            print(f"Could not record applied status for PR #{number}: {exc}", file=sys.stderr)
        try:
            latest = self.details(number)
            if (
                latest.get("state") == "OPEN"
                and latest.get("headRefOid") == head_sha
                and latest.get("baseRefName") == "main"
                and not latest.get("isDraft")
                and is_state_only(latest.get("files") or [])
            ):
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
                    run_command([
                        "gh", "api", "--method", "DELETE",
                        f"repos/{self.repo}/git/refs/heads/{encoded_branch}",
                    ])
        except ReconcileError as exc:
            print(f"Could not close applied PR #{number}: {exc}", file=sys.stderr)

    def validate(self, pr: dict, base_sha: str) -> str:
        number = int(pr["number"])
        head_sha = str(pr["headRefOid"])
        author = str((pr.get("author") or {}).get("login") or "")
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
            changed_paths = candidate_changed_paths(base_sha, head_sha, candidate)
            preflight_candidate(candidate, changed_paths)
            env = os.environ.copy()
            env.update({
                "VALIDATION_REPO_ROOT": str(candidate),
                "VALIDATION_BASE_SHA": base_sha,
                "VALIDATION_HEAD_SHA": head_sha,
                "VALIDATION_REQUIRE_RELEVANT": "1",
                "VALIDATION_REQUIRE_AUTH": "1",
                "REPOSITORY_OWNER": self.owner,
                "PR_AUTHOR": author,
            })
            run_validation(
                [sys.executable, str(BASE_DIR / "scripts" / "validate_action.py")],
                env=env,
            )
            run_validation(
                [sys.executable, str(BASE_DIR / "scripts" / "validate_delta.py")],
                env=env,
            )

            if list((candidate / "state" / "inbox").glob("*.json")):
                materialize_env = env.copy()
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
            return run_command([
                "git", "commit-tree", tree_sha,
                "-p", base_sha,
                "-m", f"[state] apply PR #{number}",
                "-m", f"Source-PR: #{number}",
                "-m", f"Source-Head: {head_sha}",
            ], cwd=candidate, env=commit_env)
        finally:
            if candidate.exists():
                subprocess.run(
                    ["git", "worktree", "remove", "--force", str(candidate)],
                    cwd=BASE_DIR,
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
        published = self.published_commit(number, head_sha)
        if published:
            if not self.dry_run:
                self.finalize_applied_pr(number, head_sha, published)
            return SKIPPED
        terminal = self.current_reconciler_state(head_sha)
        if terminal == REJECTED:
            return REJECTED
        if has_pending_required_checks(details.get("statusCheckRollup") or []):
            return BLOCKED

        base_sha = self.current_main_sha()
        if base_sha != self.policy_sha:
            return BLOCKED
        if not self.dry_run:
            self.set_status(head_sha, "pending", f"Reconciling against {base_sha[:12]}")
        try:
            merge_commit = self.validate(pr, base_sha)
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
            run_command([
                "git", "push", "origin", f"{merge_commit}:refs/heads/main",
            ])
            print(f"Merged state PR #{number} at {head_sha[:12]}")
            self.finalize_applied_pr(number, head_sha, merge_commit)
            return MERGED
        except ValidationRejected as exc:
            if not self.dry_run:
                self.set_status(
                    head_sha,
                    "failure",
                    f"policy {self.policy_sha[:12]} rejected: {exc}",
                )
            print(f"Rejected PR #{number}: {exc}", file=sys.stderr)
            return REJECTED
        except ReconcileError as exc:
            if not self.dry_run:
                self.set_status(head_sha, "pending", str(exc))
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
