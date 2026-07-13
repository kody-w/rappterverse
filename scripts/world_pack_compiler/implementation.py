# SPDX-License-Identifier: Apache-2.0
"""Closed compiler implementation-source digest."""

from __future__ import annotations

from pathlib import Path
from typing import Tuple

from .crypto import implementation_digest

COMPILER_SOURCE_FILES: Tuple[str, ...] = (
    "scripts/compile_world_pack.py",
    "scripts/world_pack_compiler/__init__.py",
    "scripts/world_pack_compiler/canonical.py",
    "scripts/world_pack_compiler/core.py",
    "scripts/world_pack_compiler/crypto.py",
    "scripts/world_pack_compiler/implementation.py",
    "scripts/world_pack_compiler/legacy.py",
    "scripts/world_pack_compiler/trust.py",
)


def _read_implementation_sources() -> Tuple[Tuple[str, bytes], ...]:
    root = Path(__file__).resolve().parents[2]
    values = []
    for relative in COMPILER_SOURCE_FILES:
        path = root / relative
        if not path.is_file() or path.is_symlink():
            raise RuntimeError(
                "compiler source is missing or unsafe: {}".format(relative)
            )
        values.append((relative, path.read_bytes()))
    return tuple(values)


COMPILER_IMPLEMENTATION_SHA256 = implementation_digest(
    _read_implementation_sources()
)
