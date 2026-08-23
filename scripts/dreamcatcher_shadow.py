#!/usr/bin/env python3
"""Public-safe, non-authoritative Dreamcatcher index telemetry."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Callable

from dreamcatcher_delta import validate_manifest
from dreamcatcher_promotion import (
    INDEX_CONFIGURATION,
    INDEX_CONFIGURATION_ID,
    INDEX_DEPTH,
    INDEX_INCLUDE_SCOPES,
    INDEX_INCLUDES,
    INDEX_MAX_BYTES,
    INDEX_MAX_ENTITY_FANOUT,
    INDEX_SUFFIXES,
    PROMOTION_POLICY_REVISION,
    REPOSITORY,
    TELEMETRY_SCHEMA,
    PromotionEvidenceError,
    require_authenticated_repository_readiness,
    require_attested_repository_readiness,
    validate_telemetry,
)
from dreamcatcher_reverse_index import (
    ReverseIndexError,
    build_index,
    expand_search_plan,
)

MODES = {"off", "shadow", "enforce"}
DEFAULT_MODE = "shadow"


class DreamcatcherConfigurationError(RuntimeError):
    """Dreamcatcher mode or promotion configuration is invalid."""


class DreamcatcherEnforcementError(RuntimeError):
    """A promoted query deterministically missed candidate paths."""


class DreamcatcherRuntimeError(RuntimeError):
    """Indexing or evidence evaluation is temporarily unavailable."""


def resolve_mode(value: str | None = None) -> str:
    """Resolve the exact off|shadow|enforce mode, defaulting to shadow."""
    selected = (
        os.environ.get("DREAMCATCHER_MODE", DEFAULT_MODE)
        if value is None
        else value
    )
    if not isinstance(selected, str) or selected.strip() not in MODES:
        raise DreamcatcherConfigurationError(
            "DREAMCATCHER_MODE must be off, shadow, or enforce"
        )
    return selected.strip()


def _elapsed_ms(start_ns: int, end_ns: int) -> int:
    elapsed = max(0, end_ns - start_ns)
    return (elapsed + 999_999) // 1_000_000


def _error_code(phase: str, error: Exception) -> str:
    if isinstance(error, ReverseIndexError):
        return f"{phase}-reverse-index-error"
    if isinstance(error, OSError):
        return f"{phase}-io-error"
    return f"{phase}-error"


def _failed_telemetry(
    manifest: dict,
    *,
    mode: str,
    source_pr: int,
    source_head: str,
    duration_ms: int,
    error_code: str,
) -> dict:
    manifest_paths = len(manifest.get("search_plan", {}).get("paths", []))
    record = {
        "schema": TELEMETRY_SCHEMA,
        "repository": REPOSITORY,
        "mode": mode,
        "source_pr": source_pr,
        "source_head": source_head,
        "manifest_id": manifest.get("manifest_id"),
        "search_queries": len(
            manifest.get("search_plan", {}).get("queries", [])
        ),
        "policy_revision": PROMOTION_POLICY_REVISION,
        "index_configuration_id": INDEX_CONFIGURATION_ID,
        "promotion_evidence_id": None,
        "promotion_attestation": None,
        "index_id": None,
        "query_id": None,
        "manifest_paths": manifest_paths,
        "covered_paths": 0,
        "selected_documents": 0,
        "total_documents": 0,
        "selected_bytes": 0,
        "total_bytes": 0,
        "coverage": 1.0 if manifest_paths == 0 else 0.0,
        "missing_paths": manifest_paths,
        "missing_count": 0,
        "hub_count": 0,
        "duration_ms": duration_ms,
        "error_count": 1,
        "error_code": error_code,
    }
    return validate_telemetry(record)


def observe_candidate(
    candidate: Path,
    manifest: dict,
    *,
    mode: str | None = None,
    source_pr: int,
    source_head: str,
    promotion_summary: dict | None = None,
    promotion_attestation: dict | None = None,
    authenticated_promotion_evidence: dict | None = None,
    evidence_repo: Path | None = None,
    evidence_revision: str = "HEAD",
    target_repository: str = REPOSITORY,
    target_base: str | None = None,
    clock_ns: Callable[[], int] = time.perf_counter_ns,
) -> dict | None:
    """Build/query the candidate index without changing its accepted tree."""
    selected_mode = resolve_mode(mode)
    if selected_mode == "off":
        return None
    promotion_evidence_id = None
    promotion_attestation_signature = None
    if selected_mode == "enforce":
        if promotion_summary is not None:
            raise DreamcatcherConfigurationError(
                "caller-authored promotion summaries are not trusted"
            )
        if authenticated_promotion_evidence is not None:
            if promotion_attestation is not None or evidence_repo is not None:
                raise DreamcatcherConfigurationError(
                    "authenticated promotion evidence is ambiguous"
                )
        elif evidence_repo is None:
            raise DreamcatcherConfigurationError(
                "enforce mode requires canonical repository evidence"
            )
        elif promotion_attestation is None:
            raise DreamcatcherConfigurationError(
                "enforce mode requires a target-bound promotion attestation"
            )
        if target_base is None:
            raise DreamcatcherConfigurationError(
                "enforce mode requires a target-bound promotion attestation"
            )
        try:
            if authenticated_promotion_evidence is not None:
                attested_summary = require_authenticated_repository_readiness(
                    authenticated_promotion_evidence,
                    repository=target_repository,
                    target_base=target_base,
                    target_head=source_head,
                )
                promotion_attestation = authenticated_promotion_evidence[
                    "attestation"
                ]
            else:
                attested_summary = require_attested_repository_readiness(
                    evidence_repo,
                    evidence_revision,
                    attestation=promotion_attestation,
                    repository=target_repository,
                    target_base=target_base,
                    target_head=source_head,
                )
        except PromotionEvidenceError as exc:
            raise DreamcatcherConfigurationError(
                f"valid promotion attestation is unavailable: {exc}"
            ) from exc
        except Exception as exc:
            raise DreamcatcherRuntimeError(
                "Dreamcatcher promotion evidence evaluation failed"
            ) from exc
        promotion_evidence_id = attested_summary["evidence_id"]
        promotion_attestation_signature = promotion_attestation["signature"]

    start_ns = clock_ns()
    phase = "manifest"
    try:
        validated_manifest = validate_manifest(manifest)
        phase = "index"
        index = build_index(
            candidate,
            includes=INDEX_INCLUDES,
            max_bytes=INDEX_MAX_BYTES,
            max_entity_fanout=INDEX_MAX_ENTITY_FANOUT,
            suffixes=set(INDEX_SUFFIXES),
        )
        if index["configuration"] != INDEX_CONFIGURATION["build"]:
            raise ReverseIndexError(
                "reverse index configuration does not match policy"
            )
        phase = "query"
        query = expand_search_plan(
            index,
            validated_manifest["search_plan"],
            depth=INDEX_DEPTH,
            include_scopes=INDEX_INCLUDE_SCOPES,
        )
        duration_ms = _elapsed_ms(start_ns, clock_ns())
        manifest_paths = validated_manifest["search_plan"]["paths"]
        selected_paths = set(query["selected_paths"])
        covered_paths = sum(path in selected_paths for path in manifest_paths)
        record = {
            "schema": TELEMETRY_SCHEMA,
            "repository": REPOSITORY,
            "mode": selected_mode,
            "source_pr": source_pr,
            "source_head": source_head,
            "manifest_id": validated_manifest["manifest_id"],
            "search_queries": len(
                validated_manifest["search_plan"]["queries"]
            ),
            "policy_revision": PROMOTION_POLICY_REVISION,
            "index_configuration_id": INDEX_CONFIGURATION_ID,
            "promotion_evidence_id": promotion_evidence_id,
            "promotion_attestation": promotion_attestation_signature,
            "index_id": index["index_id"],
            "query_id": query["query_id"],
            "manifest_paths": len(manifest_paths),
            "covered_paths": covered_paths,
            "selected_documents": query["stats"]["selected_documents"],
            "total_documents": query["stats"]["total_documents"],
            "selected_bytes": query["stats"]["selected_bytes"],
            "total_bytes": query["stats"]["total_bytes"],
            "coverage": round(
                1.0
                if not manifest_paths
                else covered_paths / len(manifest_paths),
                6,
            ),
            "missing_paths": len(manifest_paths) - covered_paths,
            "missing_count": len(query["missing_entities"]),
            "hub_count": len(query["hub_entities"]),
            "duration_ms": duration_ms,
            "error_count": 0,
            "error_code": None,
        }
        phase = "telemetry"
        record = validate_telemetry(record)
    except Exception as exc:
        duration_ms = _elapsed_ms(start_ns, clock_ns())
        if selected_mode == "enforce":
            raise DreamcatcherRuntimeError(
                f"Dreamcatcher {phase} failed"
            ) from exc
        try:
            return _failed_telemetry(
                manifest,
                mode=selected_mode,
                source_pr=source_pr,
                source_head=source_head,
                duration_ms=duration_ms,
                error_code=_error_code(phase, exc),
            )
        except Exception:
            return None

    if (
        selected_mode == "enforce"
        and record["covered_paths"] != record["manifest_paths"]
    ):
        raise DreamcatcherEnforcementError(
            "Dreamcatcher query did not cover every manifest path"
        )
    return record


def telemetry_json(record: dict) -> str:
    """Render one canonical JSONL-compatible telemetry sample."""
    validate_telemetry(record)
    return json.dumps(
        record,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def telemetry_trailers(record: dict) -> list[str]:
    """Render deterministic synthetic-commit trailers."""
    record = validate_telemetry(record)
    return [
        f"Dreamcatcher-Mode: {record['mode']}",
        f"Dreamcatcher-Policy: {record['policy_revision']}",
        "Dreamcatcher-Index-Configuration: "
        f"{record['index_configuration_id']}",
        "Dreamcatcher-Promotion-Evidence: "
        f"{record['promotion_evidence_id'] or 'none'}",
        "Dreamcatcher-Promotion-Attestation: "
        f"{record['promotion_attestation'] or 'none'}",
        f"Dreamcatcher-Index: {record['index_id'] or 'unavailable'}",
        f"Dreamcatcher-Query: {record['query_id'] or 'unavailable'}",
        "Dreamcatcher-Paths: "
        f"{record['covered_paths']}/{record['manifest_paths']}",
        "Dreamcatcher-Documents: "
        f"{record['selected_documents']}/{record['total_documents']}",
        "Dreamcatcher-Bytes: "
        f"{record['selected_bytes']}/{record['total_bytes']}",
        f"Dreamcatcher-Coverage: {record['coverage']:.6f}",
        f"Dreamcatcher-Missing-Paths: {record['missing_paths']}",
        f"Dreamcatcher-Missing: {record['missing_count']}",
        f"Dreamcatcher-Hubs: {record['hub_count']}",
        f"Dreamcatcher-Duration-Ms: {record['duration_ms']}",
        f"Dreamcatcher-Errors: {record['error_count']}",
        f"Dreamcatcher-Error-Code: {record['error_code'] or 'none'}",
    ]


def _short_id(value: str | None) -> str:
    return "none" if value is None else value.removeprefix("sha256:")[:8]


def _compact_count(value: int) -> str:
    for divisor, suffix in (
        (1_000_000_000, "g"),
        (1_000_000, "m"),
        (1_000, "k"),
    ):
        if value >= divisor:
            return f"{value / divisor:.1f}{suffix}"
    return str(value)


def telemetry_status_description(record: dict) -> str:
    """Fit every required metric into one GitHub status description."""
    record = validate_telemetry(record)
    description = (
        f"{record['mode']} "
        f"m={_short_id(record['manifest_id'])} "
        f"i={_short_id(record['index_id'])} "
        f"q={_short_id(record['query_id'])} "
        f"p={record['covered_paths']}/{record['manifest_paths']} "
        f"d={record['selected_documents']}/{record['total_documents']} "
        f"b={record['selected_bytes']}/{record['total_bytes']} "
        f"c={record['coverage']:.6f} "
        f"x={record['missing_count']} "
        f"h={record['hub_count']} "
        f"ms={record['duration_ms']} "
        f"e={record['error_count']}"
    )
    if len(description) > 140:
        description = (
            f"{record['mode']} "
            f"m={_short_id(record['manifest_id'])[:6]} "
            f"i={_short_id(record['index_id'])[:6]} "
            f"q={_short_id(record['query_id'])[:6]} "
            f"p={record['covered_paths']}/{record['manifest_paths']} "
            f"d={record['selected_documents']}/{record['total_documents']} "
            f"b={_compact_count(record['selected_bytes'])}/"
            f"{_compact_count(record['total_bytes'])} "
            f"c={record['coverage']:.3f} "
            f"x={record['missing_count']} "
            f"h={record['hub_count']} "
            f"ms={record['duration_ms']} "
            f"e={record['error_count']}"
        )
    if len(description) > 140:
        description = description[:140]
    return description
