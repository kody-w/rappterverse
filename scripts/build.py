#!/usr/bin/env python3
"""Compatibility wrapper for the canonical frontend bundler."""

from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parent.parent


def build():
    subprocess.run(
        ["bash", str(ROOT / "scripts" / "bundle.sh")],
        cwd=ROOT,
        check=True,
    )

if __name__ == '__main__':
    build()
