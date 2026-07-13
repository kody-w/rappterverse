# SPDX-License-Identifier: Apache-2.0
"""Pinned local-Git legacy-v1 static pack compiler."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, List, Mapping, MutableMapping, Optional, Sequence, Set, Tuple

from .canonical import canonical_json_v2, parse_json_v2
from .core import (
    COMPILER_VERSION,
    CompilationResult,
    _add_file,
    _bounds,
    _closed,
    _fail,
    _iter_legacy_aliases,
    _legacy_alias_material,
    _point,
    _profile_limits,
    _safe_path,
    load_trusted_profile,
)
from .crypto import pack_leaf_hash, pack_tree_root, stable_identity_digest
from .implementation import COMPILER_IMPLEMENTATION_SHA256
from .trust import (
    LEGACY_LOCK_PATH,
    LEGACY_LOCK_RAW_SHA256,
    LEGACY_MAIN_COMMIT,
    LEGACY_MAIN_TREE,
    LEGACY_REPOSITORY,
    LEGACY_REQUIRED_SOURCE_DESCRIPTORS,
)

LEGACY_LOCK_VERSION = "rappterverse.legacy-source-lock/v1"
LEGACY_PACK_ID = "legacy-v1"
LEGACY_WORLD_IDS = ("hub", "arena", "marketplace", "gallery", "dungeon")
LEGACY_STATIC_PATHS = tuple(
    "worlds/{}/{}.json".format(world_id, name)
    for world_id in LEGACY_WORLD_IDS
    for name in ("config", "objects", "npcs")
)
LEGACY_FRONTEND_PATHS = (
    "src/js/config.js",
    "src/js/inventory.js",
    "src/js/abilities.js",
    "src/js/equipment.js",
)


class LegacyCompilationError(ValueError):
    """Raised when pinned legacy material cannot compile safely."""


def _legacy_error(message: str) -> None:
    raise LegacyCompilationError(message)


def _run_git(repo_root: Path, arguments: Sequence[str]) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(repo_root), *arguments],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        _legacy_error(
            result.stderr.decode("utf-8", errors="replace").strip()
            or "local Git command failed"
        )
    return result.stdout


def _git_blob(
    repo_root: Path,
    commit: str,
    path: str,
    *,
    max_bytes: int,
) -> bytes:
    _safe_path(path, path)
    listing = _run_git(repo_root, ["ls-tree", "-z", commit, "--", path])
    entries = [entry for entry in listing.split(b"\0") if entry]
    if len(entries) != 1:
        _legacy_error("{}:{} is missing or ambiguous".format(commit, path))
    try:
        metadata, listed_path = entries[0].split(b"\t", 1)
        mode, object_type, _object_id = metadata.split(b" ", 2)
        decoded_path = listed_path.decode("utf-8", errors="strict")
    except (ValueError, UnicodeDecodeError) as exc:
        raise LegacyCompilationError("unsafe local Git tree entry") from exc
    if (
        mode != b"100644"
        or object_type != b"blob"
        or decoded_path != path
    ):
        _legacy_error("{}:{} is not a regular 100644 blob".format(commit, path))
    data = _run_git(repo_root, ["cat-file", "blob", "{}:{}".format(commit, path)])
    if not data or len(data) > max_bytes:
        _legacy_error("{}:{} is outside blob limits".format(commit, path))
    return data


def _legacy_pairs(pairs: List[Tuple[str, Any]]) -> Dict[str, Any]:
    value: Dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            _legacy_error("legacy JSON contains a duplicate key")
        value[key] = item
    return value


def _legacy_json(data: bytes, path: str) -> Dict[str, Any]:
    try:
        text = data.decode("utf-8", errors="strict")
        value = json.loads(
            text,
            object_pairs_hook=_legacy_pairs,
            parse_float=lambda token: token,
            parse_constant=lambda token: _legacy_error(
                "non-finite number in {}".format(path)
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise LegacyCompilationError("{} is not strict legacy JSON".format(path)) from exc
    if not isinstance(value, dict):
        _legacy_error("{} root must be an object".format(path))
    canonical_json_v2(value)
    return value


class _JSLiteralParser:
    """Strict parser for pinned JavaScript data literals; it executes nothing."""

    _NUMBER = re.compile(r"-?(?:0[xX][0-9a-fA-F]+|[0-9]+(?:\.[0-9]+)?)")
    _IDENTIFIER = re.compile(r"[A-Za-z_$][A-Za-z0-9_$-]*")

    def __init__(self, text: str, start: int) -> None:
        self.text = text
        self.index = start

    def _skip(self) -> None:
        while True:
            while self.index < len(self.text) and self.text[self.index].isspace():
                self.index += 1
            if self.text.startswith("//", self.index):
                end = self.text.find("\n", self.index)
                self.index = len(self.text) if end < 0 else end + 1
                continue
            if self.text.startswith("/*", self.index):
                end = self.text.find("*/", self.index + 2)
                if end < 0:
                    _legacy_error("unterminated JavaScript comment")
                self.index = end + 2
                continue
            break

    def _consume(self, expected: str) -> None:
        self._skip()
        if not self.text.startswith(expected, self.index):
            _legacy_error("expected {!r} in JavaScript literal".format(expected))
        self.index += len(expected)

    def _string(self) -> str:
        quote = self.text[self.index]
        self.index += 1
        output: List[str] = []
        escapes = {
            "'": "'",
            '"': '"',
            "\\": "\\",
            "/": "/",
            "b": "\b",
            "f": "\f",
            "n": "\n",
            "r": "\r",
            "t": "\t",
            "v": "\v",
            "0": "\0",
        }
        while self.index < len(self.text):
            character = self.text[self.index]
            self.index += 1
            if character == quote:
                return "".join(output)
            if character != "\\":
                output.append(character)
                continue
            if self.index >= len(self.text):
                _legacy_error("unterminated JavaScript string escape")
            escaped = self.text[self.index]
            self.index += 1
            if escaped in escapes:
                output.append(escapes[escaped])
            elif escaped in ("x", "u"):
                digits = 2 if escaped == "x" else 4
                token = self.text[self.index : self.index + digits]
                if len(token) != digits or not re.fullmatch(
                    r"[0-9a-fA-F]{{{}}}".format(digits), token
                ):
                    _legacy_error("invalid JavaScript Unicode escape")
                output.append(chr(int(token, 16)))
                self.index += digits
            elif escaped == "\n":
                continue
            else:
                _legacy_error("unsupported JavaScript string escape")
        _legacy_error("unterminated JavaScript string")
        return ""

    def _key(self) -> str:
        self._skip()
        if self.index < len(self.text) and self.text[self.index] in ("'", '"'):
            return self._string()
        match = self._IDENTIFIER.match(self.text, self.index)
        if not match:
            _legacy_error("invalid JavaScript object key")
        self.index = match.end()
        return match.group(0)

    def value(self) -> Any:
        self._skip()
        if self.index >= len(self.text):
            _legacy_error("unexpected end of JavaScript literal")
        character = self.text[self.index]
        if character == "{":
            return self._object()
        if character == "[":
            return self._array()
        if character in ("'", '"'):
            return self._string()
        for token, value in (("true", True), ("false", False), ("null", None)):
            if self.text.startswith(token, self.index):
                self.index += len(token)
                return value
        match = self._NUMBER.match(self.text, self.index)
        if match:
            token = match.group(0)
            self.index = match.end()
            if token.lower().startswith("-0x"):
                return -int(token[1:], 16)
            if token.lower().startswith("0x"):
                return int(token, 16)
            if "." in token:
                return token
            return int(token)
        _legacy_error("JavaScript expression is not inert literal data")
        return None

    def _object(self) -> Dict[str, Any]:
        self._consume("{")
        result: Dict[str, Any] = {}
        self._skip()
        if self.text.startswith("}", self.index):
            self.index += 1
            return result
        while True:
            key = self._key()
            if key in result:
                _legacy_error("duplicate JavaScript object key")
            self._consume(":")
            result[key] = self.value()
            self._skip()
            if self.text.startswith("}", self.index):
                self.index += 1
                return result
            self._consume(",")
            self._skip()
            if self.text.startswith("}", self.index):
                self.index += 1
                return result

    def _array(self) -> List[Any]:
        self._consume("[")
        result: List[Any] = []
        self._skip()
        if self.text.startswith("]", self.index):
            self.index += 1
            return result
        while True:
            result.append(self.value())
            self._skip()
            if self.text.startswith("]", self.index):
                self.index += 1
                return result
            self._consume(",")
            self._skip()
            if self.text.startswith("]", self.index):
                self.index += 1
                return result


def _extract_js_literal(
    data: bytes,
    marker: str,
    path: str,
    expected_terminator: str,
) -> Any:
    try:
        text = data.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise LegacyCompilationError("{} is not UTF-8".format(path)) from exc
    positions = [match.start() for match in re.finditer(re.escape(marker), text)]
    if len(positions) != 1:
        _legacy_error("{} must contain marker {!r} exactly once".format(path, marker))
    start = positions[0] + len(marker)
    parser = _JSLiteralParser(text, start)
    value = parser.value()
    while parser.index < len(text) and text[parser.index].isspace():
        parser.index += 1
    if not text.startswith(expected_terminator, parser.index):
        _legacy_error(
            "{} literal marker {!r} has trailing expression tokens".format(
                path, marker
            )
        )
    canonical_json_v2(value)
    return value


def _legacy_material(world_id: str, kind: str, legacy_id: str) -> Tuple[str, str]:
    return _legacy_alias_material(world_id, kind, legacy_id)


def _legacy_alias(
    profile: Mapping[str, Any],
    aliases: Mapping[Tuple[str, str, str], str],
    world_id: str,
    kind: str,
    legacy_id: str,
) -> Tuple[str, str]:
    identity_record, stable_input = _legacy_material(world_id, kind, legacy_id)
    key = (kind, identity_record, stable_input)
    if aliases.get(key) != legacy_id:
        _legacy_error(
            "legacy ID {!r} lacks an exact trusted alias".format(legacy_id)
        )
    digest = stable_identity_digest(
        profile["identity"]["namespace"],
        kind,
        identity_record,
        stable_input,
    )
    return digest, identity_record


def _drop_protected(value: Any, protected: Set[str]) -> Any:
    if isinstance(value, dict):
        return {
            key: _drop_protected(child, protected)
            for key, child in sorted(value.items())
            if "".join(c.lower() for c in key if c.isalnum()) not in protected
        }
    if isinstance(value, list):
        return [_drop_protected(child, protected) for child in value]
    return value


def _catalog_defaults(value: Any, protected: Set[str]) -> Any:
    """Retain immutable catalog mechanics without using mutable overlay keys."""

    key_aliases = {
        "damage": "baseDamage",
        "hp": "baseHp",
        "status": "statusDefinition",
        "position": "placementDefinition",
    }
    if isinstance(value, dict):
        result: Dict[str, Any] = {}
        for key, child in sorted(value.items()):
            normalized = "".join(
                character.lower()
                for character in key
                if character.isalnum()
            )
            if key in key_aliases:
                output_key = key_aliases[key]
            elif normalized in protected:
                continue
            else:
                output_key = key
            if output_key in result:
                _legacy_error("catalog keys collide after safe projection")
            result[output_key] = _catalog_defaults(child, protected)
        return result
    if isinstance(value, list):
        return [_catalog_defaults(child, protected) for child in value]
    return value


def _legacy_point(value: Any, location: str) -> Dict[str, Any]:
    value = _closed(value, ("x", "y", "z"), location=location)
    result: Dict[str, Any] = {}
    for axis in ("x", "y", "z"):
        coordinate = value[axis]
        if isinstance(coordinate, bool) or not isinstance(coordinate, (int, str)):
            _legacy_error("{} coordinate is not an exact number".format(location))
        if isinstance(coordinate, str):
            try:
                Decimal(coordinate)
            except InvalidOperation as exc:
                raise LegacyCompilationError(
                    "{} coordinate is not an exact decimal".format(location)
                ) from exc
        result[axis] = coordinate
    return result


def _clamp(
    point: Mapping[str, Any], bounds: Mapping[str, Sequence[int]]
) -> Dict[str, Any]:
    def clamp_axis(value: Any, low: int, high: int) -> Any:
        numeric = Decimal(value) if isinstance(value, str) else Decimal(value)
        if numeric < low:
            return low
        if numeric > high:
            return high
        return value

    return {
        "x": clamp_axis(point["x"], bounds["x"][0], bounds["x"][1]),
        "y": point["y"],
        "z": clamp_axis(point["z"], bounds["z"][0], bounds["z"][1]),
    }


def _legacy_provenance(
    *,
    entity_id: str,
    scoped_id: str,
    identity_digest: str,
    identity_record: str,
    stable_input: str,
    kind: str,
    world_id: str,
    source_path: str,
    source_sha256: str,
    commit: str,
    lock_sha256: str,
    profile: Mapping[str, Any],
    profile_sha: str,
) -> Dict[str, Any]:
    return {
        "compiler": {
            "implementationSha256": COMPILER_IMPLEMENTATION_SHA256,
            "version": COMPILER_VERSION,
        },
        "entityId": scoped_id,
        "identity": {
            "identityRecordId": identity_record,
            "identitySha256": "sha256:" + identity_digest,
            "legacyAlias": True,
            "stableIdInput": stable_input,
        },
        "kind": kind,
        "legacySource": {
            "commit": commit,
            "lockSha256": lock_sha256,
            "path": source_path,
            "sha256": "sha256:" + source_sha256,
        },
        "profile": {
            "profileId": profile["profileId"],
            "profileSha256": profile_sha,
            "transformationVersion": "legacy-v1-safe-static-projection/v1",
            "version": profile["version"],
        },
        "schemaVersion": "rappterverse.legacy-pack-provenance/v1",
        "sourceEntityId": entity_id,
        "worldId": world_id,
    }


def compile_legacy_v1(
    repo_root: Optional[Path] = None,
    trusted_profile: Optional[Mapping[str, Any]] = None,
    lock_path: Optional[Path] = None,
) -> CompilationResult:
    """Compile the engine-owned pinned legacy source from canonical local Git."""

    engine_root = Path(__file__).resolve().parents[2]
    if trusted_profile is not None or lock_path is not None:
        _legacy_error(
            "legacy compiler trust inputs are engine-owned and cannot be overridden"
        )
    if repo_root is not None and Path(repo_root).absolute() != engine_root:
        _legacy_error("alternate legacy repository worktrees are not accepted")
    canonical_lock = engine_root / LEGACY_LOCK_PATH
    if canonical_lock.is_symlink() or not canonical_lock.is_file():
        _legacy_error("canonical legacy source lock is missing or unsafe")
    return _compile_legacy_v1_internal(
        engine_root,
        canonical_lock.read_bytes(),
        expected_lock_sha256=LEGACY_LOCK_RAW_SHA256,
    )


def _compile_legacy_v1_for_test(
    repo_root: Path,
    lock_bytes: bytes,
    *,
    expected_lock_sha256: str = LEGACY_LOCK_RAW_SHA256,
) -> CompilationResult:
    """Internal dependency injection for adversarial fixtures; never used by CLI."""

    return _compile_legacy_v1_internal(
        repo_root,
        lock_bytes,
        expected_lock_sha256=expected_lock_sha256,
    )


def _compile_legacy_v1_internal(
    repo_root: Path,
    lock_bytes: bytes,
    *,
    expected_lock_sha256: str,
) -> CompilationResult:
    profile = load_trusted_profile()
    limits = _profile_limits(profile)
    lock_sha = hashlib.sha256(lock_bytes).hexdigest()
    if lock_sha != expected_lock_sha256:
        _legacy_error("legacy source lock raw digest mismatch")
    lock_digest = "sha256:" + lock_sha
    lock = parse_json_v2(lock_bytes)
    lock = _closed(
        lock,
        ("schema", "repository", "sources", "reconciliation"),
        location="legacy-lock",
    )
    if (
        lock["schema"] != LEGACY_LOCK_VERSION
        or lock["repository"] != LEGACY_REPOSITORY
    ):
        _legacy_error("legacy source lock identity is unsupported")
    sources = lock["sources"]
    if not isinstance(sources, dict) or "main" not in sources:
        _legacy_error("legacy source lock has no pinned main source")
    main = _closed(
        sources["main"], ("commit", "tree", "role"), location="legacy-lock.main"
    )
    commit = main["commit"]
    tree = main["tree"]
    if not re.fullmatch(r"[0-9a-f]{40}", commit) or not re.fullmatch(
        r"[0-9a-f]{40}", tree
    ):
        _legacy_error("legacy commit/tree must be full lowercase hashes")
    if commit != LEGACY_MAIN_COMMIT:
        _legacy_error("legacy source lock main commit is not engine-pinned")
    if tree != LEGACY_MAIN_TREE:
        _legacy_error("legacy source lock main tree is not engine-pinned")
    actual_tree = _run_git(repo_root, ["rev-parse", "{}^{{tree}}".format(commit)])
    if actual_tree.decode("ascii", errors="strict").strip() != tree:
        _legacy_error("pinned legacy main tree does not match local Git")
    profile_sha = "sha256:" + hashlib.sha256(
        canonical_json_v2(profile, stored=True)
    ).hexdigest()
    alias_map = {
        (kind, identity_record, stable_input): legacy_id
        for kind, identity_record, stable_input, legacy_id in _iter_legacy_aliases(
            profile
        )
    }

    expected_descriptors = {
        path: (size, digest)
        for path, size, digest in LEGACY_REQUIRED_SOURCE_DESCRIPTORS
    }
    required_paths = LEGACY_STATIC_PATHS + LEGACY_FRONTEND_PATHS
    if set(required_paths) != set(expected_descriptors):
        _legacy_error("legacy source descriptor set is not closed")
    blobs: Dict[str, bytes] = {}
    for path in required_paths:
        data = _git_blob(
            repo_root, commit, path, max_bytes=limits["maxBlobBytes"]
        )
        expected_size, expected_digest = expected_descriptors[path]
        if (
            len(data) != expected_size
            or hashlib.sha256(data).hexdigest() != expected_digest
        ):
            _legacy_error(
                "{} does not match its engine-pinned source descriptor".format(
                    path
                )
            )
        blobs[path] = data
    blob_descriptors = {
        path: {
            "bytes": len(data),
            "path": path,
            "sha256": "sha256:" + hashlib.sha256(data).hexdigest(),
        }
        for path, data in sorted(blobs.items())
    }

    frontend_worlds = _extract_js_literal(
        blobs["src/js/config.js"],
        "const WORLDS =",
        "src/js/config.js",
        ";",
    )
    frontend_world_ids = _extract_js_literal(
        blobs["src/js/config.js"],
        "const WORLD_IDS =",
        "src/js/config.js",
        ";",
    )
    inventory_items = _extract_js_literal(
        blobs["src/js/inventory.js"],
        "ITEMS:",
        "src/js/inventory.js",
        ",",
    )
    abilities = _extract_js_literal(
        blobs["src/js/abilities.js"],
        "defs:",
        "src/js/abilities.js",
        ",",
    )
    equipment_slots = _extract_js_literal(
        blobs["src/js/equipment.js"],
        "const EQUIPMENT_SLOTS =",
        "src/js/equipment.js",
        ";",
    )
    equipment_map = _extract_js_literal(
        blobs["src/js/equipment.js"],
        "const EQUIPMENT_MAP =",
        "src/js/equipment.js",
        ";",
    )
    if frontend_world_ids != list(LEGACY_WORLD_IDS) or set(frontend_worlds) != set(
        LEGACY_WORLD_IDS
    ):
        _legacy_error("pinned frontend world IDs differ from legacy-v1 contract")

    protected = {
        "".join(c.lower() for c in name if c.isalnum())
        for name in (
            profile["overlayProtection"]["publicPreservedFields"]
            + profile["overlayProtection"]["denylist"]
        )
    }
    frontend_worlds = _drop_protected(frontend_worlds, protected)
    inventory_items = _catalog_defaults(inventory_items, protected)
    abilities = _catalog_defaults(abilities, protected)
    equipment_slots = _drop_protected(equipment_slots, protected)
    equipment_map = _catalog_defaults(equipment_map, protected)
    files: Dict[str, bytes] = {}
    layout = profile["outputLayout"]
    world_index: List[Dict[str, Any]] = []
    provenance_rows: List[Dict[str, Any]] = []
    portal_endpoints: List[Dict[str, str]] = []
    object_count = 0
    npc_count = 0
    seen_scoped_ids: Set[Tuple[str, str, str]] = set()

    configs: Dict[str, Dict[str, Any]] = {}
    for world_order, world_id in enumerate(LEGACY_WORLD_IDS):
        config_path = "worlds/{}/config.json".format(world_id)
        source = _legacy_json(blobs[config_path], config_path)
        if source.get("id") != world_id:
            _legacy_error("{} world identity mismatch".format(config_path))
        bounds = _bounds(source.get("bounds"), config_path + ".bounds")
        renderer = frontend_worlds[world_id]
        renderer_bounds = renderer.get("bounds")
        scale = profile["placementPolicy"]["rendererUnitsPerSimulationUnit"]
        if (
            not isinstance(renderer_bounds, dict)
            or renderer_bounds.get("x")
            != max(abs(bounds["x"][0]), abs(bounds["x"][1])) * scale
            or renderer_bounds.get("z")
            != max(abs(bounds["z"][0]), abs(bounds["z"][1])) * scale
        ):
            _legacy_error(
                "{} renderer bounds do not match simulation scale".format(world_id)
            )
        digest, identity_record = _legacy_alias(
            profile, alias_map, world_id, "world", world_id
        )
        stable_input = _legacy_material(world_id, "world", world_id)[1]
        row = {
            "bounds": bounds,
            "description": source.get("description", ""),
            "id": world_id,
            "identitySha256": "sha256:" + digest,
            "kind": "world",
            "name": source.get("name", world_id),
            "order": world_order,
            "provenanceId": "legacy:{}:world:{}".format(world_id, world_id),
            "stableKey": world_id,
        }
        world_index.append(row)
        config = dict(row)
        config.update(
            {
                "features": _drop_protected(source.get("features", {}), protected),
                "renderer": {
                    "compatibility": renderer,
                    "unitsPerSimulationUnit": scale,
                },
                "schemaVersion": "rappterverse.world-config/v1",
                "settings": _drop_protected(source.get("settings", {}), protected),
                "spawn": _point(source.get("spawn"), config_path + ".spawn"),
                "version": source.get("version", "1.0.0"),
            }
        )
        configs[world_id] = config
        provenance_rows.append(
            _legacy_provenance(
                entity_id="legacy:world:{}".format(world_id),
                scoped_id=row["provenanceId"],
                identity_digest=digest,
                identity_record=identity_record,
                stable_input=stable_input,
                kind="world",
                world_id=world_id,
                source_path=config_path,
                source_sha256=hashlib.sha256(blobs[config_path]).hexdigest(),
                commit=commit,
                lock_sha256=lock_digest,
                profile=profile,
                profile_sha=profile_sha,
            )
        )

    _add_file(
        files,
        layout["worldsIndex"],
        {
            "schemaVersion": "rappterverse.world-index/v1",
            "worlds": world_index,
        },
        limits,
    )
    for world_id in LEGACY_WORLD_IDS:
        _add_file(
            files,
            layout["worldConfig"].format(worldId=world_id),
            configs[world_id],
            limits,
        )
        bounds = configs[world_id]["bounds"]
        object_path = "worlds/{}/objects.json".format(world_id)
        source_objects = _legacy_json(blobs[object_path], object_path).get(
            "objects", []
        )
        if not isinstance(source_objects, list):
            _legacy_error("{} objects must be an array".format(object_path))
        object_rows: List[Dict[str, Any]] = []
        for source in source_objects:
            if not isinstance(source, dict) or not isinstance(source.get("id"), str):
                _legacy_error("{} contains an invalid object".format(object_path))
            legacy_id = source["id"]
            kind = "portal" if source.get("type") == "portal" else "object"
            scoped_key = (world_id, kind, legacy_id)
            if scoped_key in seen_scoped_ids:
                _legacy_error("duplicate legacy object ID in world")
            seen_scoped_ids.add(scoped_key)
            digest, identity_record = _legacy_alias(
                profile, alias_map, world_id, kind, legacy_id
            )
            stable_input = _legacy_material(world_id, kind, legacy_id)[1]
            source_copy = {
                key: value
                for key, value in source.items()
                if key not in ("id", "position", "destination")
            }
            row = {
                "defaults": _drop_protected(source_copy, protected),
                "id": legacy_id,
                "identitySha256": "sha256:" + digest,
                "kind": kind,
                "name": source.get("name", legacy_id),
                "placement": _clamp(
                    _legacy_point(
                        source.get("position"), object_path + "." + legacy_id
                    ),
                    bounds,
                ),
                "provenanceId": "legacy:{}:{}:{}".format(
                    world_id, kind, legacy_id
                ),
                "stableKey": legacy_id,
                "worldId": world_id,
            }
            if kind == "portal":
                destination = source.get("destination")
                if destination not in LEGACY_WORLD_IDS:
                    _legacy_error("legacy portal targets an unknown world")
                row["destinationWorldId"] = destination
                portal_endpoints.append(
                    {
                        "destinationWorldId": destination,
                        "id": legacy_id,
                        "worldId": world_id,
                    }
                )
            object_rows.append(row)
            object_count += 1
            provenance_rows.append(
                _legacy_provenance(
                    entity_id="legacy:{}:{}:{}".format(world_id, kind, legacy_id),
                    scoped_id=row["provenanceId"],
                    identity_digest=digest,
                    identity_record=identity_record,
                    stable_input=stable_input,
                    kind=kind,
                    world_id=world_id,
                    source_path=object_path,
                    source_sha256=hashlib.sha256(blobs[object_path]).hexdigest(),
                    commit=commit,
                    lock_sha256=lock_digest,
                    profile=profile,
                    profile_sha=profile_sha,
                )
            )
        _add_file(
            files,
            layout["worldObjects"].format(worldId=world_id),
            {
                "objects": object_rows,
                "schemaVersion": "rappterverse.world-objects/v1",
                "worldId": world_id,
            },
            limits,
        )

        npc_path = "worlds/{}/npcs.json".format(world_id)
        source_npcs = _legacy_json(blobs[npc_path], npc_path).get("npcs", [])
        if not isinstance(source_npcs, list):
            _legacy_error("{} NPCs must be an array".format(npc_path))
        npc_rows: List[Dict[str, Any]] = []
        for source in source_npcs:
            if not isinstance(source, dict) or not isinstance(source.get("id"), str):
                _legacy_error("{} contains an invalid NPC".format(npc_path))
            legacy_id = source["id"]
            digest, identity_record = _legacy_alias(
                profile, alias_map, world_id, "npc-blueprint", legacy_id
            )
            stable_input = _legacy_material(
                world_id, "npc-blueprint", legacy_id
            )[1]
            position = _legacy_point(
                source.get("position"), npc_path + "." + legacy_id
            )
            source_copy = {
                key: value
                for key, value in source.items()
                if key
                not in (
                    "id",
                    "name",
                    "position",
                    "dialogue",
                    "patrolPath",
                    "rotation",
                    "inventory",
                    "agentId",
                    "schedule",
                )
            }
            defaults = _drop_protected(source_copy, protected)
            if "dialogue" in source:
                defaults["fallbackDialogue"] = source["dialogue"]
            if "patrolPath" in source:
                defaults["patrolRoute"] = [
                    _clamp(
                        _legacy_point(point, npc_path + ".patrolPath"), bounds
                    )
                    for point in source["patrolPath"]
                ]
            if "rotation" in source:
                defaults["spawnRotation"] = source["rotation"]
            if "agentId" in source:
                defaults["agentBlueprintId"] = source["agentId"]
            if "schedule" in source:
                defaults["scheduleDefinition"] = _drop_protected(
                    source["schedule"], protected
                )
            defaults = _drop_protected(defaults, protected)
            row = {
                "defaults": defaults,
                "id": legacy_id,
                "identitySha256": "sha256:" + digest,
                "kind": "npc-blueprint",
                "name": source.get("name", legacy_id),
                "provenanceId": "legacy:{}:npc-blueprint:{}".format(
                    world_id, legacy_id
                ),
                "spawn": _clamp(position, bounds),
                "stableKey": legacy_id,
                "worldId": world_id,
            }
            npc_rows.append(row)
            npc_count += 1
            provenance_rows.append(
                _legacy_provenance(
                    entity_id="legacy:{}:npc-blueprint:{}".format(
                        world_id, legacy_id
                    ),
                    scoped_id=row["provenanceId"],
                    identity_digest=digest,
                    identity_record=identity_record,
                    stable_input=stable_input,
                    kind="npc-blueprint",
                    world_id=world_id,
                    source_path=npc_path,
                    source_sha256=hashlib.sha256(blobs[npc_path]).hexdigest(),
                    commit=commit,
                    lock_sha256=lock_digest,
                    profile=profile,
                    profile_sha=profile_sha,
                )
            )
        _add_file(
            files,
            layout["worldNpcs"].format(worldId=world_id),
            {
                "npcs": npc_rows,
                "schemaVersion": "rappterverse.world-npcs/v1",
                "worldId": world_id,
            },
            limits,
        )

    item_rows: List[Dict[str, Any]] = []
    for item_id, item in sorted(inventory_items.items()):
        digest, identity_record = _legacy_alias(
            profile, alias_map, "frontend", "item", item_id
        )
        stable_input = _legacy_material("frontend", "item", item_id)[1]
        row = {
            "defaults": item,
            "id": item_id,
            "identitySha256": "sha256:" + digest,
            "kind": "item",
            "name": item.get("name", item_id),
            "provenanceId": "legacy:frontend:item:{}".format(item_id),
        }
        item_rows.append(row)
        provenance_rows.append(
            _legacy_provenance(
                entity_id="legacy:frontend:item:{}".format(item_id),
                scoped_id=row["provenanceId"],
                identity_digest=digest,
                identity_record=identity_record,
                stable_input=stable_input,
                kind="item",
                world_id="frontend",
                source_path="src/js/inventory.js",
                source_sha256=hashlib.sha256(blobs["src/js/inventory.js"]).hexdigest(),
                commit=commit,
                lock_sha256=lock_digest,
                profile=profile,
                profile_sha=profile_sha,
            )
        )
    _add_file(
        files,
        layout["economy"],
        {
            "currencies": [],
            "items": item_rows,
            "schemaVersion": "rappterverse.economy-defaults/v1",
        },
        limits,
    )
    _add_file(
        files,
        layout["legacyCompatibility"],
        {
            "catalogs": {
                "abilities": abilities,
                "equipment": {
                    "items": equipment_map,
                    "slots": equipment_slots,
                },
                "inventoryItems": inventory_items,
            },
            "numericEncoding": "non-integer-numbers-are-decimal-strings",
            "portalEndpoints": sorted(
                portal_endpoints,
                key=lambda item: (
                    item["worldId"],
                    item["id"],
                    item["destinationWorldId"],
                ),
            ),
            "schemaVersion": "rappterverse.legacy-frontend-compatibility/v1",
            "sourceBlobs": [
                blob_descriptors[path] for path in sorted(blob_descriptors)
            ],
            "worldIds": list(LEGACY_WORLD_IDS),
            "worlds": frontend_worlds,
        },
        limits,
    )
    provenance_path = layout["provenance"]
    files[provenance_path] = b"".join(
        canonical_json_v2(row, stored=True)
        for row in sorted(provenance_rows, key=lambda item: item["entityId"])
    )
    if len(files[provenance_path]) > limits["maxOutputFileBytes"]:
        _legacy_error("legacy provenance exceeds output limit")

    payload = [
        {
            "bytes": len(files[path]),
            "leafSha256": "sha256:" + pack_leaf_hash(path, files[path]),
            "mode": "100644",
            "path": path,
            "sha256": "sha256:" + hashlib.sha256(files[path]).hexdigest(),
        }
        for path in sorted(files)
    ]
    _add_file(
        files,
        layout["manifest"],
        {
            "canonicalization": "rappterverse-canonical-json/v2",
            "compiler": {
                "implementationSha256": COMPILER_IMPLEMENTATION_SHA256,
                "version": COMPILER_VERSION,
            },
            "legacySource": {
                "commit": commit,
                "lockSha256": lock_digest,
                "tree": tree,
            },
            "packId": LEGACY_PACK_ID,
            "payloadFiles": payload,
            "profile": {
                "profileId": profile["profileId"],
                "profileSha256": profile_sha,
                "version": profile["version"],
            },
            "schemaVersion": "rappterverse.world-pack/v1",
        },
        limits,
    )
    root = pack_tree_root(files)
    report = {
        "compiler": {
            "implementationSha256": COMPILER_IMPLEMENTATION_SHA256,
            "version": COMPILER_VERSION,
        },
        "entityCount": len(provenance_rows),
        "fileCount": len(files),
        "legacySource": {
            "commit": commit,
            "lockSha256": lock_digest,
            "tree": tree,
        },
        "objectCount": object_count,
        "npcCount": npc_count,
        "packRoot": root,
        "profileSha256": profile_sha,
        "schemaVersion": "rappterverse.world-pack-build-report/v1",
        "status": "compiled",
        "warnings": [],
        "worldCount": len(LEGACY_WORLD_IDS),
    }
    canonical_json_v2(report, stored=True)
    return CompilationResult(files=dict(sorted(files.items())), report=report, root=root)
