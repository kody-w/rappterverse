# SPDX-License-Identifier: Apache-2.0
"""Bounded RAPPterverse canonical JSON v2 implementation."""

from __future__ import annotations

import json
import unicodedata
from collections.abc import Mapping
from typing import Any, Dict, List, Tuple, Union

CANONICALIZATION_V2 = "rappterverse-canonical-json/v2"
MAX_JSON_NESTING_DEPTH = 64
MAX_CANONICAL_BYTES = 32_000_000
MAX_JSON_NODES = 500_000
MAX_STRING_BYTES = 2_000_000
MAX_INTEGER_BITS = 16_384
MAX_INTEGER_DECIMAL_DIGITS = 4_933
_DECIMAL_CHUNK_DIGITS = 18
_DECIMAL_CHUNK_BASE = 10**_DECIMAL_CHUNK_DIGITS


class CanonicalJSONV2Error(ValueError):
    """Raised when a value is outside the canonical JSON v2 domain."""


class CanonicalJSONV2DepthError(CanonicalJSONV2Error):
    """Raised when a value exceeds the deterministic nesting limit."""


def _walk_and_bound(
    value: Any,
    *,
    max_depth: int,
    max_nodes: int,
    max_string_bytes: int,
) -> None:
    stack = [(value, 0)]
    nodes = 0
    while stack:
        item, parent_depth = stack.pop()
        nodes += 1
        if nodes > max_nodes:
            raise CanonicalJSONV2Error(
                "maximum JSON node count {} exceeded".format(max_nodes)
            )
        if isinstance(item, str):
            try:
                length = len(item.encode("utf-8", errors="strict"))
            except UnicodeEncodeError as exc:
                raise CanonicalJSONV2Error("string is not strict UTF-8") from exc
            if length > max_string_bytes:
                raise CanonicalJSONV2Error(
                    "maximum string byte length {} exceeded".format(
                        max_string_bytes
                    )
                )
        elif isinstance(item, int) and not isinstance(item, bool):
            if item.bit_length() > MAX_INTEGER_BITS:
                raise CanonicalJSONV2Error("integer is too large")
        if isinstance(item, (list, tuple, Mapping)):
            depth = parent_depth + 1
            if depth > max_depth:
                raise CanonicalJSONV2DepthError(
                    "maximum JSON nesting depth {} exceeded".format(max_depth)
                )
            if isinstance(item, Mapping):
                for key, child in item.items():
                    if not isinstance(key, str):
                        raise CanonicalJSONV2Error(
                            "object keys must be strings"
                        )
                    stack.append((key, depth))
                    stack.append((child, depth))
            else:
                stack.extend((child, depth) for child in item)


def ensure_json_depth(
    value: Any, *, max_depth: int = MAX_JSON_NESTING_DEPTH
) -> None:
    """Reject values with more than ``max_depth`` nested containers."""

    _walk_and_bound(
        value,
        max_depth=max_depth,
        max_nodes=MAX_JSON_NODES,
        max_string_bytes=MAX_STRING_BYTES,
    )


def _normalize(value: Any, path: str = "$") -> Any:
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        raise CanonicalJSONV2Error(
            "{}: floating-point numbers are not allowed".format(path)
        )
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, (list, tuple)):
        return [
            _normalize(item, "{}[{}]".format(path, index))
            for index, item in enumerate(value)
        ]
    if isinstance(value, Mapping):
        normalized: Dict[str, Any] = {}
        original_keys: Dict[str, str] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise CanonicalJSONV2Error(
                    "{}: object keys must be strings".format(path)
                )
            normalized_key = unicodedata.normalize("NFC", key)
            if normalized_key in normalized:
                raise CanonicalJSONV2Error(
                    "{}: object keys {!r} and {!r} collide after NFC "
                    "normalization".format(
                        path, original_keys[normalized_key], key
                    )
                )
            original_keys[normalized_key] = key
            normalized[normalized_key] = _normalize(
                item, "{}.{}".format(path, normalized_key)
            )
        return normalized
    raise CanonicalJSONV2Error(
        "{}: unsupported JSON value type {}".format(path, type(value).__name__)
    )


def _format_integer(value: int) -> str:
    if value == 0:
        return "0"
    negative = value < 0
    remaining = -value if negative else value
    chunks: List[int] = []
    while remaining:
        remaining, chunk = divmod(remaining, _DECIMAL_CHUNK_BASE)
        chunks.append(chunk)
    encoded = str(chunks.pop())
    while chunks:
        encoded += "{:0{width}d}".format(
            chunks.pop(), width=_DECIMAL_CHUNK_DIGITS
        )
    return ("-" if negative else "") + encoded


def _encode_canonical(value: Any) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, int):
        return _format_integer(value)
    if isinstance(value, str):
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        )
    if isinstance(value, list):
        return "[" + ",".join(_encode_canonical(item) for item in value) + "]"
    if isinstance(value, dict):
        return "{" + ",".join(
            "{}:{}".format(
                json.dumps(
                    key,
                    ensure_ascii=False,
                    allow_nan=False,
                    separators=(",", ":"),
                ),
                _encode_canonical(value[key]),
            )
            for key in sorted(value)
        ) + "}"
    raise CanonicalJSONV2Error(
        "unsupported normalized JSON value type {}".format(
            type(value).__name__
        )
    )


def canonical_json_v2(
    value: Any,
    *,
    stored: bool = False,
    max_bytes: int = MAX_CANONICAL_BYTES,
) -> bytes:
    """Return bounded canonical JSON v2 bytes."""

    try:
        ensure_json_depth(value)
        normalized = _normalize(value)
        encoded = _encode_canonical(normalized).encode(
            "utf-8", errors="strict"
        )
    except CanonicalJSONV2Error:
        raise
    except RecursionError as exc:
        raise CanonicalJSONV2DepthError(
            "maximum JSON nesting depth {} exceeded".format(
                MAX_JSON_NESTING_DEPTH
            )
        ) from exc
    except (TypeError, UnicodeEncodeError, ValueError) as exc:
        raise CanonicalJSONV2Error(
            "value is not strict UTF-8 JSON: {}".format(exc)
        ) from exc
    result = encoded + (b"\n" if stored else b"")
    if len(result) > max_bytes:
        raise CanonicalJSONV2Error(
            "maximum canonical byte length {} exceeded".format(max_bytes)
        )
    return result


def _reject_float(token: str) -> None:
    raise CanonicalJSONV2Error(
        "floating-point number token {!r} is not allowed".format(token)
    )


def _reject_constant(token: str) -> None:
    raise CanonicalJSONV2Error(
        "non-finite number token {!r} is not JSON".format(token)
    )


def _parse_integer(token: str) -> int:
    negative = token.startswith("-")
    digits = token[1:] if negative else token
    if len(digits) > MAX_INTEGER_DECIMAL_DIGITS:
        raise CanonicalJSONV2Error(
            "integer exceeds {} decimal digits".format(
                MAX_INTEGER_DECIMAL_DIGITS
            )
        )
    value = 0
    first = len(digits) % _DECIMAL_CHUNK_DIGITS
    index = 0
    if first:
        value = int(digits[:first])
        index = first
    while index < len(digits):
        value = (
            value * _DECIMAL_CHUNK_BASE
            + int(digits[index : index + _DECIMAL_CHUNK_DIGITS])
        )
        index += _DECIMAL_CHUNK_DIGITS
    if value.bit_length() > MAX_INTEGER_BITS:
        raise CanonicalJSONV2Error(
            "integer exceeds {} bits".format(MAX_INTEGER_BITS)
        )
    return -value if negative else value


def _object_pairs(pairs: List[Tuple[str, Any]]) -> Dict[str, Any]:
    value: Dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise CanonicalJSONV2Error("duplicate object key {!r}".format(key))
        value[key] = item
    return value


def parse_json_v2(
    data: Union[bytes, str],
    *,
    require_stored: bool = False,
    max_bytes: int = MAX_CANONICAL_BYTES,
) -> Any:
    """Parse strict UTF-8 JSON and optionally require canonical stored bytes."""

    if isinstance(data, bytes):
        raw = data
        if len(raw) > max_bytes:
            raise CanonicalJSONV2Error(
                "maximum input byte length {} exceeded".format(max_bytes)
            )
        try:
            text = raw.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise CanonicalJSONV2Error("input is not valid UTF-8") from exc
    elif isinstance(data, str):
        text = data
        try:
            raw = text.encode("utf-8", errors="strict")
        except UnicodeEncodeError as exc:
            raise CanonicalJSONV2Error("input is not valid UTF-8") from exc
        if len(raw) > max_bytes:
            raise CanonicalJSONV2Error(
                "maximum input byte length {} exceeded".format(max_bytes)
            )
    else:
        raise CanonicalJSONV2Error("input must be bytes or text")
    if text.startswith("\ufeff"):
        raise CanonicalJSONV2Error("UTF-8 BOM is not allowed")
    try:
        value = json.loads(
            text,
            object_pairs_hook=_object_pairs,
            parse_int=_parse_integer,
            parse_float=_reject_float,
            parse_constant=_reject_constant,
        )
    except CanonicalJSONV2Error:
        raise
    except RecursionError as exc:
        raise CanonicalJSONV2DepthError(
            "maximum JSON nesting depth {} exceeded".format(
                MAX_JSON_NESTING_DEPTH
            )
        ) from exc
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise CanonicalJSONV2Error("input is not strict JSON") from exc
    try:
        ensure_json_depth(value)
        normalized = _normalize(value)
    except RecursionError as exc:
        raise CanonicalJSONV2DepthError(
            "maximum JSON nesting depth {} exceeded".format(
                MAX_JSON_NESTING_DEPTH
            )
        ) from exc
    expected = canonical_json_v2(
        normalized, stored=require_stored, max_bytes=max_bytes
    )
    if require_stored and raw != expected:
        raise CanonicalJSONV2Error("stored JSON is not canonical JSON v2")
    return normalized


def parse_jsonl_v2(
    data: bytes,
    *,
    max_bytes: int = 1_000_000,
    max_lines: int = 100_000,
) -> List[Tuple[Any, bytes]]:
    """Parse canonical JSONL and return values paired with exact line bytes."""

    if not data or len(data) > max_bytes:
        raise CanonicalJSONV2Error("JSONL byte length is outside limits")
    if not data.endswith(b"\n") or b"\r" in data:
        raise CanonicalJSONV2Error(
            "canonical JSONL must use LF and end with one LF"
        )
    raw_lines = data.splitlines(keepends=True)
    if len(raw_lines) > max_lines:
        raise CanonicalJSONV2Error("maximum JSONL line count exceeded")
    parsed: List[Tuple[Any, bytes]] = []
    for index, line in enumerate(raw_lines):
        if line == b"\n":
            raise CanonicalJSONV2Error(
                "blank JSONL line at index {}".format(index)
            )
        value = parse_json_v2(
            line, require_stored=True, max_bytes=max_bytes
        )
        parsed.append((value, line))
    return parsed
