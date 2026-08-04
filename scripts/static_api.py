#!/usr/bin/env python3
"""rapp-static-api/1.0 support library for RAPPterverse.

Spec: https://raw.githubusercontent.com/kody-w/rapp-static-apis/main/SPEC.md

Two consumers:

1. ``scripts/build_static_api.py`` — the single build step. It stamps the
   ``schema`` string onto every served document declared in ``manifest.json``
   and regenerates ``registry.json`` + ``api/v1/*.json``.
2. Every state writer under ``scripts/`` — each one's ``save_json`` helper calls
   :func:`stamp_mapping` so a state write never *drops* the schema string that
   the build put there. Without this the stamp would survive exactly one tick.

Python 3.11+, stdlib only (repo constraint — no ``pip install``).
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = ROOT / "manifest.json"

INDEX_SCHEMA = "rapp-static-api/1.0"
STATUS_SCHEMA = "rappterverse-status/1.0"

# ISO-8601 UTC with Z — rapp-static-api/1.0 §3 "Timestamps".
ISO_Z = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$")

_MANIFEST_CACHE: dict | None = None
_PATH_SCHEMA_CACHE: dict[str, str] | None = None


def utc_now() -> str:
    """Current time as ISO-8601 UTC with a ``Z`` suffix."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_manifest(path: Path | None = None) -> dict:
    """Load the one hand-authored input. Cached; safe to call per write."""
    global _MANIFEST_CACHE
    if path is not None:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    if _MANIFEST_CACHE is None:
        try:
            with open(MANIFEST_PATH, encoding="utf-8") as handle:
                _MANIFEST_CACHE = json.load(handle)
        except (OSError, ValueError):
            _MANIFEST_CACHE = {}
    return _MANIFEST_CACHE


def _path_schema_map() -> dict[str, str]:
    """Map of repo-relative path -> schema id, for the single-document entries."""
    global _PATH_SCHEMA_CACHE
    if _PATH_SCHEMA_CACHE is None:
        manifest = load_manifest()
        _PATH_SCHEMA_CACHE = {
            entry["path"]: entry["schema"]
            for entry in manifest.get("entries", [])
            if entry.get("path") and entry.get("schema")
        }
    return _PATH_SCHEMA_CACHE


def rel_path(path) -> str:
    """Repo-relative POSIX path, or the path as given when it is outside the repo."""
    candidate = Path(path).resolve()
    try:
        return candidate.relative_to(ROOT).as_posix()
    except ValueError:
        return Path(path).as_posix()


def schema_for(path) -> str | None:
    """The ``schema`` string a document at ``path`` must carry, or ``None``.

    Resolution order: exact single-document entry, then collection glob. A path
    the manifest does not declare returns ``None`` — absence is not an error,
    it is how ``documents_not_stamped`` stays honest.
    """
    relative = rel_path(path)
    exact = _path_schema_map().get(relative)
    if exact:
        return exact
    for collection in load_manifest().get("collections", []):
        directory = collection.get("dir")
        pattern = collection.get("glob", "*.json")
        if not directory:
            continue
        parent, _, name = relative.rpartition("/")
        if parent == directory and fnmatch.fnmatch(name, pattern):
            return collection.get("schema")
    return None


def stamp_mapping(data, path):
    """Return ``data`` with its manifest-declared ``schema`` string as the first key.

    Non-mappings and undeclared paths are returned untouched. Idempotent.
    """
    schema = schema_for(path)
    if schema is None or not isinstance(data, dict):
        return data
    if data.get("schema") == schema and next(iter(data), None) == "schema":
        return data
    stamped = {"schema": schema}
    for key, value in data.items():
        if key != "schema":
            stamped[key] = value
    return stamped


def detect_indent(text: str) -> str:
    """The leading whitespace of the first indented line, defaulting to 4 spaces."""
    for line in text.split("\n")[1:]:
        stripped = line.lstrip(" \t")
        if stripped and stripped != line:
            return line[: len(line) - len(stripped)]
    return "    "


def stamp_file(path: Path, schema: str) -> bool:
    """Insert or correct the ``schema`` string in a JSON file on disk.

    Works textually so the change is exactly one line and no other byte of the
    document is reformatted — indentation, key order and the presence or
    absence of a trailing newline are all preserved. Returns ``True`` if the
    file was modified.
    """
    original = path.read_text(encoding="utf-8")
    try:
        data = json.loads(original)
    except ValueError:
        return False
    if not isinstance(data, dict):
        return False
    if data.get("schema") == schema and next(iter(data), None) == "schema":
        return False

    indent = detect_indent(original)
    line = f'{indent}"schema": {json.dumps(schema)},'

    if "schema" in data:
        # Replace an existing (possibly stale or misplaced) top-level schema line.
        lines = original.split("\n")
        depth = 0
        for i, raw in enumerate(lines):
            if depth == 1 and raw.lstrip().startswith('"schema"'):
                lines[i] = line if raw.rstrip().endswith(",") else line.rstrip(",")
                path.write_text("\n".join(lines), encoding="utf-8")
                return True
            depth += raw.count("{") + raw.count("[") - raw.count("}") - raw.count("]")
        return False

    opening = original.index("{")
    newline = original.index("\n", opening) if "\n" in original[opening:] else -1
    if newline == -1:
        return False
    updated = original[: newline + 1] + line + "\n" + original[newline + 1 :]
    if json.loads(updated) != {"schema": schema, **data}:
        return False
    path.write_text(updated, encoding="utf-8")
    return True


def sha8(payload: bytes) -> str:
    """rapp-static-api/1.0 §3 "Hashing": the first 12 hex chars of the SHA-256."""
    return hashlib.sha256(payload).hexdigest()[:12]


def write_json_stable(path: Path, obj: dict, ts_keys=("generated",)) -> bool:
    """Stable-write a generated document (§3 "Idempotent + stable-write").

    If the only difference from the file already on disk is a timestamp key,
    the old timestamp is kept so git sees no diff. Returns ``True`` on write.
    """
    new = json.loads(json.dumps(obj, ensure_ascii=False))
    if path.exists():
        try:
            old = json.loads(path.read_text(encoding="utf-8"))
            if {k: v for k, v in new.items() if k not in ts_keys} == {
                k: v for k, v in old.items() if k not in ts_keys
            }:
                for key in ts_keys:
                    if key in old:
                        new[key] = old[key]
        except ValueError:
            pass
    rendered = json.dumps(new, indent=2, ensure_ascii=False) + "\n"
    if path.exists() and path.read_text(encoding="utf-8") == rendered:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(rendered, encoding="utf-8")
    return True


def declared_documents(manifest: dict | None = None) -> list[tuple[Path, str]]:
    """Every (path, schema) pair the manifest says must carry a schema string."""
    manifest = manifest if manifest is not None else load_manifest()
    documents: list[tuple[Path, str]] = []
    for entry in manifest.get("entries", []):
        path = ROOT / entry["path"]
        if path.is_file():
            documents.append((path, entry["schema"]))
    for collection in manifest.get("collections", []):
        directory = ROOT / collection["dir"]
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob(collection.get("glob", "*.json"))):
            if path.is_file():
                documents.append((path, collection["schema"]))
    return documents
