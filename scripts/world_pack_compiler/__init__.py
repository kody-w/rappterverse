# SPDX-License-Identifier: Apache-2.0
"""Deterministic RAPPterverse world-pack compiler."""

from .canonical import (
    CANONICALIZATION_V2,
    CanonicalJSONV2DepthError,
    CanonicalJSONV2Error,
    canonical_json_v2,
    parse_json_v2,
)
from .core import (
    CompilationError,
    CompilationResult,
    compile_world_pack,
    load_trusted_profile,
    validate_verified_closure,
)
from .crypto import (
    SeedBank,
    pack_leaf_hash,
    pack_tree_root,
    source_closure_digest,
    stable_display_id,
    stable_identity_digest,
)
from .implementation import (
    COMPILER_IMPLEMENTATION_SHA256,
    COMPILER_SOURCE_FILES,
)
from .legacy import LegacyCompilationError, compile_legacy_v1

__all__ = (
    "CANONICALIZATION_V2",
    "COMPILER_IMPLEMENTATION_SHA256",
    "COMPILER_SOURCE_FILES",
    "CanonicalJSONV2DepthError",
    "CanonicalJSONV2Error",
    "CompilationError",
    "CompilationResult",
    "LegacyCompilationError",
    "SeedBank",
    "canonical_json_v2",
    "compile_legacy_v1",
    "compile_world_pack",
    "load_trusted_profile",
    "pack_leaf_hash",
    "pack_tree_root",
    "parse_json_v2",
    "source_closure_digest",
    "stable_display_id",
    "stable_identity_digest",
    "validate_verified_closure",
)
