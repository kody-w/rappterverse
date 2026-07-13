#!/usr/bin/env python3
"""Fail-closed PII scanner for staged, diff, path, or full-tree inputs."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

SCANNER_ROOT = Path(__file__).parent.parent.resolve()
SCANNABLE_EXTENSIONS = {
    ".json", ".md", ".py", ".yml", ".yaml", ".txt", ".html", ".js", ".ts", ".css"
}

EMAIL_PATTERN = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
PHONE_PATTERN = re.compile(
    r"(?<![*\d])\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}\b"
)
SSN_PATTERN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
DOLLAR_AMOUNT_PATTERN = re.compile(r"\$\d{1,3}(?:,\d{3})*(?:\.\d+)?[MBKmk]?\b")
API_KEY_PATTERN = re.compile(
    r"(?:api[_-]?key|token|secret|password|credential|auth)"
    r"\s*[:=]\s*[\"']?[a-zA-Z0-9_\-]{20,}",
    re.IGNORECASE,
)

ALLOWED_EMAIL_DOMAINS = {"example.com", "test.com", "github.com"}
SENSITIVE_TERMS_FILE = SCANNER_ROOT / ".pii-blocklist.txt"


class ScanError(RuntimeError):
    """Raised when the scanner cannot prove that its selected input was scanned."""


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--staged", action="store_const", const="staged", dest="mode")
    modes.add_argument(
        "--all-tracked", "--ci", action="store_const", const="all-tracked", dest="mode"
    )
    modes.add_argument("--diff", nargs=2, metavar=("BASE", "HEAD"))
    modes.add_argument("--paths", nargs="+", metavar="PATH")
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=SCANNER_ROOT,
        help="Repository checkout containing the files to scan",
    )
    args = parser.parse_args(argv)
    if args.diff:
        args.mode = "diff"
    elif args.paths:
        args.mode = "paths"
    args.repo_root = args.repo_root.resolve()
    return args


def load_sensitive_terms() -> list[str]:
    if not SENSITIVE_TERMS_FILE.exists():
        return []
    return [
        line.strip()
        for line in SENSITIVE_TERMS_FILE.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def _email_is_allowed(email: str) -> bool:
    domain = email.rsplit("@", 1)[-1].lower()
    return domain in ALLOWED_EMAIL_DOMAINS or domain.endswith(".github.com")


def scan_content(content: str, filepath: str, sensitive_terms: list[str]) -> list[str]:
    """Return redacted category/path/line findings without echoing matched values."""
    findings: list[str] = []
    seen: set[tuple[int, str]] = set()

    def record(line_number: int, category: str):
        key = (line_number, category)
        if key not in seen:
            seen.add(key)
            findings.append(f"{filepath}:{line_number} — {category}")

    for line_number, line in enumerate(content.splitlines(), 1):
        if any(not _email_is_allowed(match.group()) for match in EMAIL_PATTERN.finditer(line)):
            record(line_number, "Email")
        if PHONE_PATTERN.search(line):
            record(line_number, "Phone number")
        if SSN_PATTERN.search(line):
            record(line_number, "SSN pattern")

        for match in DOLLAR_AMOUNT_PATTERN.finditer(line):
            raw = match.group().replace("$", "").replace(",", "").rstrip("MBKmbk")
            try:
                if float(raw) > 50000:
                    record(line_number, "Large dollar amount")
            except ValueError:
                record(line_number, "Unparseable dollar amount")

        if API_KEY_PATTERN.search(line):
            record(line_number, "Possible secret/key pattern")

        lower_line = line.lower()
        if any(term.lower() in lower_line for term in sensitive_terms):
            record(line_number, "Blocklisted term")

    return findings


def run_git(repo_root: Path, *args: str, nul: bool = False) -> list[str]:
    result = subprocess.run(
        ["git", *args],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or f"git exited with status {result.returncode}"
        raise ScanError(detail)
    separator = "\0" if nul else "\n"
    return [item for item in result.stdout.split(separator) if item]


def selected_files(args: argparse.Namespace) -> tuple[list[str], str]:
    if args.mode == "staged":
        files = run_git(
            args.repo_root,
            "diff", "--cached", "--name-only", "--diff-filter=ACMRT", "-z",
            nul=True,
        )
        label = "staged diff"
    elif args.mode == "all-tracked":
        files = run_git(args.repo_root, "ls-files", "-z", nul=True)
        deleted = set(run_git(
            args.repo_root,
            "ls-files", "--deleted", "-z",
            nul=True,
        ))
        files = [filepath for filepath in files if filepath not in deleted]
        label = "all tracked files"
    elif args.mode == "diff":
        base, head = args.diff
        files = run_git(
            args.repo_root,
            "diff",
            "--name-only",
            "--diff-filter=ACMRT",
            "-z",
            f"{base}...{head}",
            "--",
            nul=True,
        )
        label = f"diff {base[:12]}...{head[:12]}"
    else:
        files = run_git(
            args.repo_root,
            "ls-files",
            "--cached",
            "--others",
            "--exclude-standard",
            "-z",
            "--",
            *args.paths,
            nul=True,
        )
        label = "paths " + ", ".join(args.paths)
    return sorted(set(files)), label


def read_scannable_file(
    repo_root: Path,
    filepath: str,
    *,
    source: str = "working",
) -> str | None:
    relative = Path(filepath)
    if relative.is_absolute() or ".." in relative.parts:
        raise ScanError(f"{filepath}: path escapes repository")
    if relative.suffix.lower() not in SCANNABLE_EXTENSIONS:
        return None

    if source == "index":
        entry = run_git(
            repo_root,
            "ls-files", "--stage", "-z", "--", filepath,
            nul=True,
        )
        if not entry:
            raise ScanError(f"{filepath}: staged file is missing or unreadable")
        mode = entry[0].split(maxsplit=1)[0]
        if mode == "120000":
            raise ScanError(f"{filepath}: symlinks are not scannable")
        result = subprocess.run(
            ["git", "show", f":{filepath}"],
            cwd=repo_root,
            capture_output=True,
        )
        if result.returncode != 0:
            detail = result.stderr.decode("utf-8", errors="replace").strip()
            raise ScanError(f"{filepath}: {detail or 'unable to read staged content'}")
        try:
            return result.stdout.decode("utf-8")
        except UnicodeError as exc:
            raise ScanError(f"{filepath}: staged file is unreadable") from exc

    full_path = repo_root / relative
    if full_path.is_symlink():
        raise ScanError(f"{filepath}: symlinks are not scannable")
    try:
        full_path.resolve().relative_to(repo_root)
    except ValueError as exc:
        raise ScanError(f"{filepath}: path escapes repository") from exc
    if not full_path.is_file():
        raise ScanError(f"{filepath}: selected file is missing or unreadable")
    try:
        return full_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ScanError(f"{filepath}: selected file is unreadable") from exc


def set_output(name: str, value: str):
    output_file = os.environ.get("GITHUB_OUTPUT")
    if not output_file:
        return
    with open(output_file, "a", encoding="utf-8") as stream:
        stream.write(f"{name}<<EOF\n{value}\nEOF\n")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        files, label = selected_files(args)
        sensitive_terms = load_sensitive_terms()
        findings: list[str] = []
        scanned = 0
        for filepath in files:
            content = read_scannable_file(
                args.repo_root,
                filepath,
                source="index" if args.mode == "staged" else "working",
            )
            if content is None:
                continue
            scanned += 1
            findings.extend(scan_content(content, filepath, sensitive_terms))
    except ScanError as exc:
        message = f"Scanner error — {exc}"
        print(f"❌ {message}")
        set_output("pii_findings", message)
        return 3

    if findings:
        summary = "\n".join(findings)
        print(f"\n🚨 PII SCAN FAILED — {len(findings)} redacted finding(s):\n")
        for finding in findings:
            print(f"  ✗ {finding}")
        print("\nRemove the flagged content before publishing.")
        set_output("pii_findings", summary)
        return 1

    print(f"✅ PII scan ({label}): No PII detected in {scanned} file(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
