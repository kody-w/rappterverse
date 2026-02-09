#!/usr/bin/env python3
"""
PII Scanner for RAPPterverse
Scans staged files (or all files in --ci mode) for personal identifiable
information and sensitive data. Blocks commits/PRs if anything is found.

Usage:
  Pre-commit hook:  python scripts/pii_scan.py
  CI mode:          python scripts/pii_scan.py --ci
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent

# --- PII patterns to scan for ---

EMAIL_PATTERN = re.compile(
    r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}',
)

PHONE_PATTERN = re.compile(
    r'(?<![*\d])\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}\b',
)

SSN_PATTERN = re.compile(
    r'\b\d{3}-\d{2}-\d{4}\b',
)

DOLLAR_AMOUNT_PATTERN = re.compile(
    r'\$\d{1,3}(?:,\d{3})*(?:\.\d+)?[MBKmk]?\b',
)

API_KEY_PATTERN = re.compile(
    r'(?:api[_-]?key|token|secret|password|credential|auth)\s*[:=]\s*["\']?[a-zA-Z0-9_\-]{20,}',
    re.IGNORECASE,
)

# Allowlisted patterns that are NOT PII
ALLOWLIST = {
    "secrets.GITHUB_TOKEN",
    "GH_TOKEN",
    "GITHUB_TOKEN",
    "${{ secrets.",
    "kody-w",                   # Public GitHub username
    "github.io",
    "example.com",
    "test@test.com",
    "RAPPcoin",
}

# Sensitive terms — real-world entities that should never appear in game state
# Add client names, personal names, or org names here
SENSITIVE_TERMS_FILE = BASE_DIR / ".pii-blocklist.txt"

def load_sensitive_terms() -> list[str]:
    """Load custom blocklist terms from .pii-blocklist.txt (one per line)."""
    if not SENSITIVE_TERMS_FILE.exists():
        return []
    terms = []
    for line in SENSITIVE_TERMS_FILE.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            terms.append(line)
    return terms


def is_allowlisted(line: str) -> bool:
    """Check if line contains only allowlisted patterns."""
    for pattern in ALLOWLIST:
        if pattern in line:
            return True
    return False


def scan_content(content: str, filepath: str, sensitive_terms: list[str]) -> list[str]:
    """Scan file content for PII patterns. Returns list of findings."""
    findings: list[str] = []

    for line_num, line in enumerate(content.splitlines(), 1):
        if is_allowlisted(line):
            continue

        # Email addresses
        for match in EMAIL_PATTERN.finditer(line):
            email = match.group()
            if not any(a in email for a in ("example.com", "test.com", "github.com")):
                findings.append(f"  {filepath}:{line_num} — Email: {email}")

        # Phone numbers
        for match in PHONE_PATTERN.finditer(line):
            findings.append(f"  {filepath}:{line_num} — Phone number: {match.group()}")

        # SSNs
        for match in SSN_PATTERN.finditer(line):
            findings.append(f"  {filepath}:{line_num} — SSN pattern: ***-**-****")

        # Dollar amounts (likely deal values / financial PII)
        for match in DOLLAR_AMOUNT_PATTERN.finditer(line):
            amount = match.group()
            # Allow small game-economy amounts (card prices, RAPPcoin)
            raw = amount.replace("$", "").replace(",", "").rstrip("MBKmbk")
            try:
                val = float(raw)
                if val > 50000:
                    findings.append(f"  {filepath}:{line_num} — Large dollar amount: {amount}")
            except ValueError:
                pass

        # API keys / secrets
        for match in API_KEY_PATTERN.finditer(line):
            findings.append(f"  {filepath}:{line_num} — Possible secret/key pattern")

        # Custom blocklist terms
        line_lower = line.lower()
        for term in sensitive_terms:
            if term.lower() in line_lower:
                findings.append(f"  {filepath}:{line_num} — Blocklisted term: '{term}'")

    return findings


def get_staged_files() -> list[str]:
    """Get list of staged files for commit."""
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"],
        capture_output=True, text=True, cwd=BASE_DIR,
    )
    return [f for f in result.stdout.strip().split("\n") if f]


def get_all_tracked_files() -> list[str]:
    """Get all tracked files (CI mode)."""
    result = subprocess.run(
        ["git", "ls-files"],
        capture_output=True, text=True, cwd=BASE_DIR,
    )
    return [f for f in result.stdout.strip().split("\n") if f]


def main():
    ci_mode = "--ci" in sys.argv
    sensitive_terms = load_sensitive_terms()

    if ci_mode:
        files = get_all_tracked_files()
        mode_label = "CI scan (all tracked files)"
    else:
        files = get_staged_files()
        mode_label = "Pre-commit scan (staged files)"

    if not files:
        print(f"✅ {mode_label}: No files to scan.")
        sys.exit(0)

    # Only scan text files, skip binaries and images
    scannable_ext = {".json", ".md", ".py", ".yml", ".yaml", ".txt", ".html", ".js", ".ts", ".css"}
    files = [f for f in files if Path(f).suffix.lower() in scannable_ext]

    all_findings: list[str] = []

    for filepath in files:
        full_path = BASE_DIR / filepath
        if not full_path.exists():
            continue
        try:
            content = full_path.read_text(errors="ignore")
        except Exception:
            continue

        findings = scan_content(content, filepath, sensitive_terms)
        all_findings.extend(findings)

    if all_findings:
        print(f"\n🚨 PII SCAN FAILED — {len(all_findings)} issue(s) found:\n")
        for f in all_findings:
            print(f"  ✗ {f}")
        print(f"\nTo fix: Remove the flagged content before committing.")
        print(f"To allowlist a pattern: Add it to ALLOWLIST in scripts/pii_scan.py")
        print(f"To add blocklisted terms: Add them to .pii-blocklist.txt (one per line)\n")

        # Set GitHub Actions output if in CI
        output_file = os.environ.get("GITHUB_OUTPUT")
        if output_file:
            findings_text = "\n".join(all_findings)
            with open(output_file, "a") as f:
                f.write(f"pii_findings<<EOF\n{findings_text}\nEOF\n")

        sys.exit(1)
    else:
        print(f"✅ {mode_label}: No PII detected in {len(files)} file(s).")
        sys.exit(0)


if __name__ == "__main__":
    main()
