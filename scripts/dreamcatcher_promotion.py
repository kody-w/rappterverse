#!/usr/bin/env python3
"""Evaluate and validate Rappterverse Dreamcatcher promotion evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import statistics
import subprocess
import sys
from pathlib import Path
from typing import Iterable

from dreamcatcher_reverse_index import (
    DEFAULT_MAX_ENTITY_FANOUT,
    DEFAULT_SUFFIXES,
    PRODUCER as INDEX_PRODUCER,
    SCHEMA as INDEX_SCHEMA,
)

TELEMETRY_SCHEMA = "dreamcatcher-shadow-telemetry/1.1"
SUMMARY_SCHEMA = "dreamcatcher-promotion-summary/1.1"
REPOSITORY = "rappterverse"
CONTENT_ID_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40,64}$")
ERROR_CODE_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
SYNTHETIC_SUBJECT_PATTERN = re.compile(
    r"^\[state\] apply PR #([1-9]\d*)$"
)
TRUSTED_COMMITTERS = frozenset({
    (
        "rappterverse-bot",
        "41898282+github-actions[bot]@users.noreply.github.com",
    ),
})
MINIMUM_SAMPLES = 50
MAXIMUM_ERRORS = 0
MAXIMUM_COVERAGE_FAILURES = 0
MAXIMUM_P95_DURATION_MS = 5_000
MINIMUM_MEDIAN_DOCUMENTS_REDUCTION = 0.5
MINIMUM_MEDIAN_BYTES_REDUCTION = 0.25
THRESHOLDS = {
    "minimum_samples": MINIMUM_SAMPLES,
    "maximum_errors": MAXIMUM_ERRORS,
    "maximum_coverage_failures": MAXIMUM_COVERAGE_FAILURES,
    "maximum_p95_duration_ms": MAXIMUM_P95_DURATION_MS,
    "minimum_median_documents_reduction": (
        MINIMUM_MEDIAN_DOCUMENTS_REDUCTION
    ),
    "minimum_median_bytes_reduction": MINIMUM_MEDIAN_BYTES_REDUCTION,
}
TELEMETRY_FIELDS = {
    "schema",
    "repository",
    "mode",
    "source_pr",
    "source_head",
    "manifest_id",
    "search_queries",
    "policy_revision",
    "index_configuration_id",
    "promotion_evidence_id",
    "index_id",
    "query_id",
    "manifest_paths",
    "covered_paths",
    "selected_documents",
    "total_documents",
    "selected_bytes",
    "total_bytes",
    "coverage",
    "missing_paths",
    "missing_count",
    "hub_count",
    "duration_ms",
    "error_count",
    "error_code",
}
TRAILER_KEYS = {
    "Source-PR",
    "Source-Head",
    "Dreamcatcher-Mode",
    "Dreamcatcher-Delta",
    "Dreamcatcher-Search-Queries",
    "Dreamcatcher-Policy",
    "Dreamcatcher-Index-Configuration",
    "Dreamcatcher-Promotion-Evidence",
    "Dreamcatcher-Index",
    "Dreamcatcher-Query",
    "Dreamcatcher-Paths",
    "Dreamcatcher-Documents",
    "Dreamcatcher-Bytes",
    "Dreamcatcher-Coverage",
    "Dreamcatcher-Missing-Paths",
    "Dreamcatcher-Missing",
    "Dreamcatcher-Hubs",
    "Dreamcatcher-Duration-Ms",
    "Dreamcatcher-Errors",
    "Dreamcatcher-Error-Code",
}
INDEX_INCLUDES = ("state", "worlds", "feed")
INDEX_MAX_BYTES = 8 * 1024 * 1024
INDEX_MAX_ENTITY_FANOUT = DEFAULT_MAX_ENTITY_FANOUT
INDEX_SUFFIXES = frozenset(DEFAULT_SUFFIXES)
INDEX_DEPTH = 1
INDEX_INCLUDE_SCOPES = False


class PromotionEvidenceError(ValueError):
    """Promotion evidence or a promotion summary is malformed."""


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _content_id(value: object) -> str:
    return "sha256:" + hashlib.sha256(_canonical_bytes(value)).hexdigest()


INDEX_CONFIGURATION = {
    "schema": "dreamcatcher-index-configuration/1.0",
    "index_schema": INDEX_SCHEMA,
    "index_producer": dict(INDEX_PRODUCER),
    "build": {
        "includes": sorted(INDEX_INCLUDES),
        "max_bytes": INDEX_MAX_BYTES,
        "max_entity_fanout": INDEX_MAX_ENTITY_FANOUT,
        "suffixes": sorted(INDEX_SUFFIXES),
    },
    "query": {
        "depth": INDEX_DEPTH,
        "include_scopes": INDEX_INCLUDE_SCOPES,
    },
}
INDEX_CONFIGURATION_ID = _content_id(INDEX_CONFIGURATION)
PROMOTION_POLICY = {
    "schema": "dreamcatcher-promotion-policy/1.0",
    "telemetry_schema": TELEMETRY_SCHEMA,
    "summary_schema": SUMMARY_SCHEMA,
    "thresholds": dict(THRESHOLDS),
    "evidence": {
        "history": "first-parent",
        "parent_count": 1,
        "sample_mode": "shadow",
        "subject": "[state] apply PR #N",
        "trailers": sorted(TRAILER_KEYS),
        "trusted_committers": [
            {"name": name, "email": email}
            for name, email in sorted(TRUSTED_COMMITTERS)
        ],
    },
}
PROMOTION_POLICY_REVISION = _content_id(PROMOTION_POLICY)


def _require_int(
    value: object,
    field: str,
    *,
    minimum: int = 0,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise PromotionEvidenceError(
            f"{field} must be an integer >= {minimum}"
        )
    return value


def _require_number(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PromotionEvidenceError(f"{field} must be a number")
    number = float(value)
    if not math.isfinite(number):
        raise PromotionEvidenceError(f"{field} must be finite")
    return number


def _require_content_id(
    value: object,
    field: str,
    *,
    optional: bool = False,
) -> str | None:
    if optional and value is None:
        return None
    if not isinstance(value, str) or not CONTENT_ID_PATTERN.fullmatch(value):
        raise PromotionEvidenceError(f"{field} must be a SHA-256 content ID")
    return value


def validate_telemetry(record: dict) -> dict:
    """Validate one public-safe reconciler telemetry sample."""
    if not isinstance(record, dict):
        raise PromotionEvidenceError("telemetry sample must be an object")
    if set(record) != TELEMETRY_FIELDS:
        missing = sorted(TELEMETRY_FIELDS - set(record))
        extra = sorted(set(record) - TELEMETRY_FIELDS)
        raise PromotionEvidenceError(
            f"telemetry fields are invalid; missing={missing}, extra={extra}"
        )
    if record["schema"] != TELEMETRY_SCHEMA:
        raise PromotionEvidenceError("unsupported telemetry schema")
    if record["repository"] != REPOSITORY:
        raise PromotionEvidenceError("telemetry is not for Rappterverse")
    if record["mode"] not in {"shadow", "enforce"}:
        raise PromotionEvidenceError("telemetry mode must be shadow or enforce")
    _require_int(record["source_pr"], "source_pr", minimum=1)
    if (
        not isinstance(record["source_head"], str)
        or not COMMIT_PATTERN.fullmatch(record["source_head"])
    ):
        raise PromotionEvidenceError("source_head must be a commit ID")
    _require_content_id(record["manifest_id"], "manifest_id")
    _require_int(record["search_queries"], "search_queries")
    _require_content_id(record["policy_revision"], "policy_revision")
    _require_content_id(
        record["index_configuration_id"],
        "index_configuration_id",
    )
    promotion_evidence_id = _require_content_id(
        record["promotion_evidence_id"],
        "promotion_evidence_id",
        optional=True,
    )
    if record["mode"] == "shadow" and promotion_evidence_id is not None:
        raise PromotionEvidenceError(
            "shadow telemetry cannot claim promotion evidence"
        )
    if record["mode"] == "enforce" and promotion_evidence_id is None:
        raise PromotionEvidenceError(
            "enforce telemetry must bind promotion evidence"
        )

    error_count = _require_int(record["error_count"], "error_count")
    if error_count not in {0, 1}:
        raise PromotionEvidenceError("error_count must be 0 or 1")
    index_id = _require_content_id(
        record["index_id"], "index_id", optional=error_count > 0
    )
    query_id = _require_content_id(
        record["query_id"], "query_id", optional=error_count > 0
    )
    error_code = record["error_code"]
    if error_count == 0:
        if error_code is not None:
            raise PromotionEvidenceError(
                "successful telemetry cannot contain an error_code"
            )
    else:
        if index_id is not None or query_id is not None:
            raise PromotionEvidenceError(
                "failed telemetry cannot claim index or query evidence"
            )
        if (
            not isinstance(error_code, str)
            or not ERROR_CODE_PATTERN.fullmatch(error_code)
        ):
            raise PromotionEvidenceError(
                "failed telemetry requires a stable error_code"
            )

    manifest_paths = _require_int(record["manifest_paths"], "manifest_paths")
    covered_paths = _require_int(record["covered_paths"], "covered_paths")
    selected_documents = _require_int(
        record["selected_documents"],
        "selected_documents",
    )
    total_documents = _require_int(record["total_documents"], "total_documents")
    selected_bytes = _require_int(record["selected_bytes"], "selected_bytes")
    total_bytes = _require_int(record["total_bytes"], "total_bytes")
    for field in (
        "missing_paths",
        "missing_count",
        "hub_count",
        "duration_ms",
    ):
        _require_int(record[field], field)
    if covered_paths > manifest_paths:
        raise PromotionEvidenceError(
            "covered_paths cannot exceed manifest_paths"
        )
    if selected_documents > total_documents:
        raise PromotionEvidenceError(
            "selected_documents cannot exceed total_documents"
        )
    if selected_bytes > total_bytes:
        raise PromotionEvidenceError(
            "selected_bytes cannot exceed total_bytes"
        )
    if record["missing_paths"] != manifest_paths - covered_paths:
        raise PromotionEvidenceError(
            "missing_paths does not match uncovered manifest paths"
        )
    if error_count and any((
        covered_paths,
        selected_documents,
        total_documents,
        selected_bytes,
        total_bytes,
        record["missing_count"],
        record["hub_count"],
    )):
        raise PromotionEvidenceError(
            "failed telemetry must not claim index/query metrics"
        )
    expected_coverage = round(
        1.0 if manifest_paths == 0 else covered_paths / manifest_paths,
        6,
    )
    coverage = _require_number(record["coverage"], "coverage")
    if not 0.0 <= coverage <= 1.0:
        raise PromotionEvidenceError("coverage must be between 0 and 1")
    if abs(coverage - expected_coverage) > 1e-9:
        raise PromotionEvidenceError(
            "coverage does not match covered_paths/manifest_paths"
        )
    return record


def _reduction(selected: int, total: int) -> float:
    return 0.0 if total == 0 else 1.0 - selected / total


def _nearest_rank_percentile(values: list[int], percentile: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(percentile * len(ordered)))
    return ordered[rank - 1]


def _summary_ready(metrics: dict) -> bool:
    return bool(
        metrics["samples"] >= MINIMUM_SAMPLES
        and metrics["errors"] <= MAXIMUM_ERRORS
        and metrics["coverage_failures"] <= MAXIMUM_COVERAGE_FAILURES
        and metrics["p95_duration_ms"] is not None
        and metrics["p95_duration_ms"] <= MAXIMUM_P95_DURATION_MS
        and metrics["median_documents_reduction"] is not None
        and metrics["median_documents_reduction"]
        >= MINIMUM_MEDIAN_DOCUMENTS_REDUCTION
        and metrics["median_bytes_reduction"] is not None
        and metrics["median_bytes_reduction"]
        >= MINIMUM_MEDIAN_BYTES_REDUCTION
    )


def evaluate_records(
    records: Iterable[dict],
    *,
    policy_revision: str = PROMOTION_POLICY_REVISION,
    index_configuration_id: str = INDEX_CONFIGURATION_ID,
) -> dict:
    """Compute a bound verdict from matching shadow samples."""
    _require_content_id(policy_revision, "policy_revision")
    _require_content_id(
        index_configuration_id,
        "index_configuration_id",
    )
    available = [
        dict(validate_telemetry(dict(record))) for record in records
    ]
    validated = [
        record
        for record in available
        if (
            record["mode"] == "shadow"
            and record["policy_revision"] == policy_revision
            and record["index_configuration_id"]
            == index_configuration_id
        )
    ]
    validated.sort(key=lambda item: item["source_head"])
    source_heads = [record["source_head"] for record in validated]
    if len(source_heads) != len(set(source_heads)):
        raise PromotionEvidenceError(
            "promotion evidence contains duplicate source_head samples"
        )
    source_prs = [record["source_pr"] for record in validated]
    if len(source_prs) != len(set(source_prs)):
        raise PromotionEvidenceError(
            "promotion evidence contains duplicate source_pr samples"
        )

    document_reductions = [
        _reduction(
            record["selected_documents"],
            record["total_documents"],
        )
        for record in validated
    ]
    byte_reductions = [
        _reduction(record["selected_bytes"], record["total_bytes"])
        for record in validated
    ]
    metrics = {
        "samples": len(validated),
        "errors": sum(record["error_count"] for record in validated),
        "coverage_failures": sum(
            record["covered_paths"] != record["manifest_paths"]
            for record in validated
        ),
        "p95_duration_ms": _nearest_rank_percentile(
            [record["duration_ms"] for record in validated],
            0.95,
        ),
        "median_documents_reduction": (
            None
            if not document_reductions
            else float(statistics.median(document_reductions))
        ),
        "median_bytes_reduction": (
            None
            if not byte_reductions
            else float(statistics.median(byte_reductions))
        ),
    }
    payload = {
        "schema": SUMMARY_SCHEMA,
        "repository": REPOSITORY,
        "policy_revision": policy_revision,
        "index_configuration_id": index_configuration_id,
        "thresholds": dict(THRESHOLDS),
        "metrics": metrics,
        "ready": _summary_ready(metrics),
        "evidence_id": _content_id(validated),
    }
    result = dict(payload)
    result["summary_id"] = _content_id(payload)
    return result


def validate_promotion_summary(
    summary: dict,
    *,
    require_ready: bool = False,
    policy_revision: str = PROMOTION_POLICY_REVISION,
    index_configuration_id: str = INDEX_CONFIGURATION_ID,
) -> dict:
    """Validate an offline summary; this does not authenticate its evidence."""
    if not isinstance(summary, dict):
        raise PromotionEvidenceError("promotion summary must be an object")
    if set(summary) != {
        "schema",
        "repository",
        "policy_revision",
        "index_configuration_id",
        "thresholds",
        "metrics",
        "ready",
        "evidence_id",
        "summary_id",
    }:
        raise PromotionEvidenceError("promotion summary fields are invalid")
    if summary["schema"] != SUMMARY_SCHEMA:
        raise PromotionEvidenceError("unsupported promotion summary schema")
    if summary["repository"] != REPOSITORY:
        raise PromotionEvidenceError("promotion summary is not for Rappterverse")
    _require_content_id(summary["policy_revision"], "policy_revision")
    _require_content_id(
        summary["index_configuration_id"],
        "index_configuration_id",
    )
    if summary["policy_revision"] != policy_revision:
        raise PromotionEvidenceError(
            "promotion summary is for a different policy revision"
        )
    if summary["index_configuration_id"] != index_configuration_id:
        raise PromotionEvidenceError(
            "promotion summary is for a different index configuration"
        )
    if summary["thresholds"] != THRESHOLDS:
        raise PromotionEvidenceError("promotion thresholds do not match policy")
    metrics = summary["metrics"]
    expected_metric_fields = {
        "samples",
        "errors",
        "coverage_failures",
        "p95_duration_ms",
        "median_documents_reduction",
        "median_bytes_reduction",
    }
    if not isinstance(metrics, dict) or set(metrics) != expected_metric_fields:
        raise PromotionEvidenceError("promotion metrics are invalid")
    for field in ("samples", "errors", "coverage_failures"):
        _require_int(metrics[field], f"metrics.{field}")
    p95 = metrics["p95_duration_ms"]
    if p95 is not None:
        _require_int(p95, "metrics.p95_duration_ms")
    for field in (
        "median_documents_reduction",
        "median_bytes_reduction",
    ):
        value = metrics[field]
        if value is not None:
            number = _require_number(value, f"metrics.{field}")
            if not 0.0 <= number <= 1.0:
                raise PromotionEvidenceError(
                    f"metrics.{field} must be between 0 and 1"
                )
    if not isinstance(summary["ready"], bool):
        raise PromotionEvidenceError("ready must be boolean")
    if summary["ready"] != _summary_ready(metrics):
        raise PromotionEvidenceError(
            "promotion ready verdict does not match its metrics"
        )
    _require_content_id(summary["evidence_id"], "evidence_id")
    payload = {
        key: value for key, value in summary.items() if key != "summary_id"
    }
    if summary["summary_id"] != _content_id(payload):
        raise PromotionEvidenceError(
            "summary_id does not match the canonical promotion summary"
        )
    if require_ready and not summary["ready"]:
        raise PromotionEvidenceError(
            "promotion summary does not prove Rappterverse ready"
        )
    return summary


def load_promotion_summary(source: str) -> dict:
    """Load an offline summary without treating it as trusted evidence."""
    if not isinstance(source, str) or not source.strip():
        raise PromotionEvidenceError("promotion summary source is required")
    rendered = source.strip()
    try:
        if rendered.startswith("{"):
            value = json.loads(rendered)
        else:
            value = json.loads(Path(rendered).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PromotionEvidenceError(
            f"cannot read promotion summary: {exc}"
        ) from exc
    return validate_promotion_summary(value, require_ready=True)


def _parse_pair(value: str, field: str) -> tuple[int, int]:
    match = re.fullmatch(r"(\d+)/(\d+)", value)
    if not match:
        raise PromotionEvidenceError(f"{field} must use selected/total")
    return int(match.group(1)), int(match.group(2))


def _parse_integer(value: str, field: str) -> int:
    if not re.fullmatch(r"\d+", value):
        raise PromotionEvidenceError(f"{field} must be a non-negative integer")
    return int(value)


def _parse_float(value: str, field: str) -> float:
    try:
        return float(value)
    except ValueError as exc:
        raise PromotionEvidenceError(f"{field} must be a number") from exc


def telemetry_from_commit_message(message: str) -> dict | None:
    """Parse one synthetic commit's Dreamcatcher trailer sample."""
    values: dict[str, str] = {}
    unknown = []
    for line in message.splitlines():
        key, separator, value = line.partition(":")
        if not separator:
            continue
        if (
            key.startswith("Dreamcatcher-")
            and key not in TRAILER_KEYS
        ):
            unknown.append(key)
            continue
        if key not in TRAILER_KEYS:
            continue
        if key in values:
            raise PromotionEvidenceError(f"duplicate {key} trailer")
        values[key] = value.strip()
    if "Dreamcatcher-Mode" not in values:
        return None
    if unknown:
        raise PromotionEvidenceError(
            f"unsupported Dreamcatcher trailers: {sorted(set(unknown))}"
        )
    missing = sorted(TRAILER_KEYS - set(values))
    if missing:
        raise PromotionEvidenceError(
            f"Dreamcatcher trailer sample is missing {missing}"
        )

    source_pr_match = re.fullmatch(r"#([1-9]\d*)", values["Source-PR"])
    if not source_pr_match:
        raise PromotionEvidenceError("Source-PR trailer is invalid")
    covered_paths, manifest_paths = _parse_pair(
        values["Dreamcatcher-Paths"],
        "Dreamcatcher-Paths",
    )
    selected_documents, total_documents = _parse_pair(
        values["Dreamcatcher-Documents"],
        "Dreamcatcher-Documents",
    )
    selected_bytes, total_bytes = _parse_pair(
        values["Dreamcatcher-Bytes"],
        "Dreamcatcher-Bytes",
    )
    error_count = _parse_integer(
        values["Dreamcatcher-Errors"],
        "Dreamcatcher-Errors",
    )
    error_code_value = values["Dreamcatcher-Error-Code"]
    record = {
        "schema": TELEMETRY_SCHEMA,
        "repository": REPOSITORY,
        "mode": values["Dreamcatcher-Mode"],
        "source_pr": int(source_pr_match.group(1)),
        "source_head": values["Source-Head"],
        "manifest_id": values["Dreamcatcher-Delta"],
        "search_queries": _parse_integer(
            values["Dreamcatcher-Search-Queries"],
            "Dreamcatcher-Search-Queries",
        ),
        "policy_revision": values["Dreamcatcher-Policy"],
        "index_configuration_id": (
            values["Dreamcatcher-Index-Configuration"]
        ),
        "promotion_evidence_id": (
            None
            if values["Dreamcatcher-Promotion-Evidence"] == "none"
            else values["Dreamcatcher-Promotion-Evidence"]
        ),
        "index_id": (
            None
            if values["Dreamcatcher-Index"] == "unavailable"
            else values["Dreamcatcher-Index"]
        ),
        "query_id": (
            None
            if values["Dreamcatcher-Query"] == "unavailable"
            else values["Dreamcatcher-Query"]
        ),
        "manifest_paths": manifest_paths,
        "covered_paths": covered_paths,
        "selected_documents": selected_documents,
        "total_documents": total_documents,
        "selected_bytes": selected_bytes,
        "total_bytes": total_bytes,
        "coverage": _parse_float(
            values["Dreamcatcher-Coverage"],
            "Dreamcatcher-Coverage",
        ),
        "missing_paths": _parse_integer(
            values["Dreamcatcher-Missing-Paths"],
            "Dreamcatcher-Missing-Paths",
        ),
        "missing_count": _parse_integer(
            values["Dreamcatcher-Missing"],
            "Dreamcatcher-Missing",
        ),
        "hub_count": _parse_integer(
            values["Dreamcatcher-Hubs"],
            "Dreamcatcher-Hubs",
        ),
        "duration_ms": _parse_integer(
            values["Dreamcatcher-Duration-Ms"],
            "Dreamcatcher-Duration-Ms",
        ),
        "error_count": error_count,
        "error_code": (
            None if error_code_value == "none" else error_code_value
        ),
    }
    return validate_telemetry(record)


def telemetry_from_synthetic_commit(message: str) -> dict | None:
    """Require the canonical synthetic state-commit message shape."""
    lines = message.splitlines()
    if not lines:
        return None
    subject_match = SYNTHETIC_SUBJECT_PATTERN.fullmatch(lines[0])
    if not subject_match:
        return None
    for line in lines[1:]:
        if not line:
            continue
        key, separator, _ = line.partition(":")
        if not separator or key not in TRAILER_KEYS:
            raise PromotionEvidenceError(
                "synthetic commit body must contain only canonical trailers"
            )
    record = telemetry_from_commit_message(message)
    if record is None:
        return None
    if record["source_pr"] != int(subject_match.group(1)):
        raise PromotionEvidenceError(
            "Source-PR does not match the synthetic commit subject"
        )
    return record


def parse_jsonl(text: str) -> list[dict]:
    """Parse strict JSONL telemetry, rejecting every malformed sample."""
    records = []
    for line_number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise PromotionEvidenceError(
                f"JSONL line {line_number} is invalid: {exc}"
            ) from exc
        try:
            records.append(dict(validate_telemetry(value)))
        except PromotionEvidenceError as exc:
            raise PromotionEvidenceError(
                f"JSONL line {line_number}: {exc}"
            ) from exc
    return records


def load_jsonl(path: str) -> list[dict]:
    try:
        text = sys.stdin.read() if path == "-" else Path(path).read_text(
            encoding="utf-8"
        )
    except OSError as exc:
        raise PromotionEvidenceError(f"cannot read JSONL evidence: {exc}") from exc
    return parse_jsonl(text)


def load_commit_evidence(repo_root: Path, revision: str = "HEAD") -> list[dict]:
    """Load authenticated samples from canonical first-parent commits."""
    try:
        result = subprocess.run(
            [
                "git",
                "log",
                "--first-parent",
                revision,
                "--format=%H%x1f%P%x1f%cn%x1f%ce%x1f%B%x1e",
            ],
            cwd=repo_root,
            capture_output=True,
        )
    except OSError as exc:
        raise PromotionEvidenceError(
            f"cannot scan commit evidence: {exc}"
        ) from exc
    if result.returncode != 0:
        detail = (
            result.stderr.decode("utf-8", "replace").strip()
            or f"git log exited {result.returncode}"
        )
        raise PromotionEvidenceError(f"cannot scan commit evidence: {detail}")
    records = []
    output = result.stdout.decode("utf-8", "replace")
    for raw_record in output.split("\x1e"):
        raw_record = raw_record.strip("\r\n")
        if not raw_record:
            continue
        fields = raw_record.split("\x1f", 4)
        if len(fields) != 5:
            raise PromotionEvidenceError("git log returned a malformed record")
        commit, parents_value, committer_name, committer_email, message = fields
        if not COMMIT_PATTERN.fullmatch(commit):
            raise PromotionEvidenceError("git log returned a malformed commit")
        lines = message.splitlines()
        if (
            not lines
            or not SYNTHETIC_SUBJECT_PATTERN.fullmatch(lines[0])
        ):
            continue
        if not any(
            line.startswith("Dreamcatcher-Mode:")
            for line in lines[1:]
        ):
            continue
        parents = parents_value.split()
        if (
            len(parents) != 1
            or not COMMIT_PATTERN.fullmatch(parents[0])
        ):
            raise PromotionEvidenceError(
                f"commit {commit}: synthetic evidence must have one parent"
            )
        if (committer_name, committer_email) not in TRUSTED_COMMITTERS:
            raise PromotionEvidenceError(
                f"commit {commit}: synthetic evidence committer is untrusted"
            )
        try:
            record = telemetry_from_synthetic_commit(message)
        except PromotionEvidenceError as exc:
            raise PromotionEvidenceError(f"commit {commit}: {exc}") from exc
        if record is not None and record["mode"] == "shadow":
            records.append(record)
    return records


def require_repository_readiness(
    repo_root: Path,
    revision: str = "HEAD",
) -> dict:
    """Recompute readiness from authenticated repository evidence."""
    summary = evaluate_records(load_commit_evidence(repo_root, revision))
    return validate_promotion_summary(summary, require_ready=True)


def _cli() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--jsonl",
        help="Read telemetry JSONL from this path, or '-' for stdin",
    )
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--revision", default="HEAD")
    args = parser.parse_args()
    try:
        records = (
            load_jsonl(args.jsonl)
            if args.jsonl
            else load_commit_evidence(Path(args.repo_root), args.revision)
        )
        summary = evaluate_records(records)
    except PromotionEvidenceError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if summary["ready"] else 1


if __name__ == "__main__":
    sys.exit(_cli())
