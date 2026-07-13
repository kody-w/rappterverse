# SPDX-License-Identifier: Apache-2.0
"""Pure deterministic world-pack compiler core."""

from __future__ import annotations

import base64
import binascii
import copy
import hashlib
import heapq
import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from types import MappingProxyType
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence, Set, Tuple

from .canonical import (
    CANONICALIZATION_V2,
    CanonicalJSONV2Error,
    canonical_json_v2,
    parse_json_v2,
    parse_jsonl_v2,
)
from .crypto import (
    SeedBank,
    pack_leaf_hash,
    pack_tree_root,
    source_closure_digest,
    stable_display_id,
    stable_identity_digest,
)
from .implementation import COMPILER_IMPLEMENTATION_SHA256
from .trust import TRUSTED_PROFILE_PATH, TRUSTED_PROFILE_RAW_SHA256

COMPILER_VERSION = "rappterverse-world-pack-compiler/v1"
CLOSURE_VERSION = "rappterverse.verified-world-source-closure/v1"
PROFILE_VERSION = "rappterverse.world-pack-compiler-profile/v1"
PACK_VERSION = "rappterverse.world-pack/v1"
PUBLIC_CONTRACT_COMMIT = "cff8bb0358ce10449ee1d72018a7624009aa3599"
PUBLIC_REPOSITORY_ID = 1298777302
PUBLIC_REPOSITORY_NAME = "kody-w/rappterverse-data"
PUBLIC_DATASET_IDS = {
    "d01-civilization-ledger",
    "d02-counterfactual-multiverse",
    "d03-human-judgment",
    "d04-work-trajectories",
    "d05-agent-lifetimes",
    "d06-social-causality",
    "d07-market-tape",
    "d08-governance-precedent",
    "d09-failure-recovery",
    "d10-agent-lineage",
}

_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_RECORD_ID = re.compile(r"^record-d(?:0[1-9]|10)-[a-z0-9][a-z0-9.-]{0,95}$")
_SOURCE_ENTITY_ID = re.compile(
    r"^source:[a-z][a-z0-9-]{1,31}:[a-z0-9][a-z0-9._/-]{0,191}$"
)
_SAFE_ID = re.compile(r"^[a-z][a-z0-9._-]{0,127}$")
_SAFE_PATH = re.compile(
    r"^(?!/)(?!.*//)(?!.*\\)(?!.*(?:^|/)\.{1,2}(?:/|$))"
    r"[A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)*$"
)
_RELEASE_ID = re.compile(
    r"^release-[0-9]{4}-[0-9]{2}-[0-9]{2}-"
    r"[a-z0-9][a-z0-9.-]{0,63}$"
)
_RECEIPT_PATH = re.compile(
    r"^objects/review-receipts/sha256/([0-9a-f]{2})/([0-9a-f]{64})\.json$"
)
_REVIEW_SET_PATH = re.compile(
    r"^objects/active-review-sets/sha256/([0-9a-f]{2})/([0-9a-f]{64})\.json$"
)


class CompilationError(ValueError):
    """A deterministic fail-closed compiler error."""

    def __init__(self, code: str, message: str, location: str = "$") -> None:
        self.code = code
        self.location = location
        super().__init__("{} at {}: {}".format(code, location, message))


@dataclass(frozen=True)
class CompilationResult:
    """Immutable compilation result surface."""

    files: Mapping[str, bytes]
    report: Mapping[str, Any]
    root: str

    def __post_init__(self) -> None:
        immutable_files = {
            path: bytes(data) for path, data in self.files.items()
        }
        object.__setattr__(
            self, "files", MappingProxyType(immutable_files)
        )


@dataclass
class _Source:
    descriptor: Dict[str, Any]
    value: Dict[str, Any]
    recipe_descriptor: Dict[str, Any]
    recipe: Dict[str, Any]
    seed_bank: SeedBank


@dataclass
class _Entity:
    source: _Source
    value: Dict[str, Any]
    entity_id: str
    kind: str
    identity_record_id: str
    stable_id_input: str
    identity_digest: str
    display_id: str
    legacy_alias: bool
    references: List[Dict[str, Any]]
    seed_draws: List[Dict[str, Any]]


def _fail(code: str, message: str, location: str = "$") -> None:
    raise CompilationError(code, message, location)


def _closed(
    value: Any,
    required: Iterable[str],
    *,
    optional: Iterable[str] = (),
    location: str,
) -> Dict[str, Any]:
    if not isinstance(value, dict):
        _fail("SHAPE", "expected an object", location)
    required_set = set(required)
    allowed = required_set | set(optional)
    actual = set(value)
    missing = sorted(required_set - actual)
    extra = sorted(actual - allowed)
    if missing:
        _fail("SHAPE", "missing fields {}".format(missing), location)
    if extra:
        _fail("SHAPE", "unknown fields {}".format(extra), location)
    return value


def _list(value: Any, location: str) -> List[Any]:
    if not isinstance(value, list):
        _fail("SHAPE", "expected an array", location)
    return value


def _string(
    value: Any,
    location: str,
    *,
    minimum: int = 1,
    maximum: int = 4096,
) -> str:
    if not isinstance(value, str) or not minimum <= len(value) <= maximum:
        _fail("SHAPE", "expected a bounded string", location)
    return value


def _integer(
    value: Any,
    location: str,
    *,
    minimum: Optional[int] = None,
    maximum: Optional[int] = None,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        _fail("SHAPE", "expected an integer", location)
    if minimum is not None and value < minimum:
        _fail("LIMIT", "integer is below minimum", location)
    if maximum is not None and value > maximum:
        _fail("LIMIT", "integer exceeds maximum", location)
    return value


def _unique_strings(
    value: Any,
    location: str,
    *,
    minimum_items: int = 0,
    maximum_items: int,
    maximum_length: int,
) -> List[str]:
    values = _list(value, location)
    if not minimum_items <= len(values) <= maximum_items:
        _fail("LIMIT", "array length is outside limits", location)
    result: List[str] = []
    seen: Set[str] = set()
    for index, item in enumerate(values):
        item = _string(
            item,
            "{}[{}]".format(location, index),
            maximum=maximum_length,
        )
        if item in seen:
            _fail("SHAPE", "array values must be unique", location)
        seen.add(item)
        result.append(item)
    return result


def _safe_path(path: Any, location: str) -> str:
    path = _string(path, location, maximum=512)
    if (
        unicodedata.normalize("NFC", path) != path
        or not _SAFE_PATH.fullmatch(path)
    ):
        _fail("PATH", "unsafe relative path", location)
    return path


def _release_id(value: Any, location: str) -> str:
    value = _string(value, location, maximum=83)
    if not _RELEASE_ID.fullmatch(value):
        _fail("RELEASE", "invalid release ID", location)
    try:
        date.fromisoformat(value[8:18])
    except ValueError as exc:
        raise CompilationError(
            "RELEASE", "release ID contains an invalid calendar date", location
        ) from exc
    return value


def _hex(value: Any, length: int, location: str) -> str:
    value = _string(value, location, minimum=length, maximum=length)
    pattern = _HEX40 if length == 40 else _HEX64
    if not pattern.fullmatch(value):
        _fail("DIGEST", "expected lowercase hexadecimal", location)
    return value


def _prefixed_digest(value: Any, location: str) -> str:
    value = _string(value, location, minimum=71, maximum=71)
    if not _DIGEST.fullmatch(value):
        _fail("DIGEST", "expected sha256:<64 lowercase hex>", location)
    return value


def _descriptor(
    value: Any,
    location: str,
    *,
    expected_kind: Optional[str] = None,
    expected_media: Optional[str] = None,
) -> Dict[str, Any]:
    descriptor = _closed(
        value,
        (
            "path",
            "artifactKind",
            "mediaType",
            "bytes",
            "sha256",
            "reviewReceiptRef",
        ),
        location=location,
    )
    _safe_path(descriptor["path"], location + ".path")
    kind = _string(descriptor["artifactKind"], location + ".artifactKind", maximum=64)
    media = _string(descriptor["mediaType"], location + ".mediaType", maximum=64)
    _integer(descriptor["bytes"], location + ".bytes", minimum=1, maximum=1_000_000)
    digest = _hex(descriptor["sha256"], 64, location + ".sha256")
    receipt = _string(
        descriptor["reviewReceiptRef"],
        location + ".reviewReceiptRef",
        maximum=160,
    )
    match = _RECEIPT_PATH.fullmatch(receipt)
    if not match or match.group(1) != match.group(2)[:2]:
        _fail("PATH", "invalid content-addressed review receipt path", location)
    if expected_kind is not None and kind != expected_kind:
        _fail(
            "DESCRIPTOR",
            "expected artifact kind {!r}".format(expected_kind),
            location,
        )
    if expected_media is not None and media != expected_media:
        _fail(
            "DESCRIPTOR",
            "expected media type {!r}".format(expected_media),
            location,
        )
    object_match = re.search(r"/sha256/([0-9a-f]{2})/([0-9a-f]{64})\.", descriptor["path"])
    if object_match and (
        object_match.group(1) != digest[:2] or object_match.group(2) != digest
    ):
        _fail("DESCRIPTOR", "content-addressed path disagrees with digest", location)
    return descriptor


def _receipt_ref(value: Any, location: str) -> Dict[str, str]:
    ref = _closed(value, ("path", "sha256"), location=location)
    path = _string(ref["path"], location + ".path", maximum=200)
    digest = _hex(ref["sha256"], 64, location + ".sha256")
    match = _RECEIPT_PATH.fullmatch(path)
    if not match or match.group(1) != digest[:2] or match.group(2) != digest:
        _fail("DESCRIPTOR", "receipt path and digest disagree", location)
    return ref


def _review_set_ref(value: Any, location: str) -> Dict[str, str]:
    ref = _closed(value, ("path", "sha256"), location=location)
    path = _string(ref["path"], location + ".path", maximum=200)
    digest = _hex(ref["sha256"], 64, location + ".sha256")
    match = _REVIEW_SET_PATH.fullmatch(path)
    if not match or match.group(1) != digest[:2] or match.group(2) != digest:
        _fail("DESCRIPTOR", "review-set path and digest disagree", location)
    return ref


def _decode_blob(
    wrapper: Any,
    location: str,
    *,
    expected_kind: str,
    expected_media: str,
    max_blob_bytes: int,
) -> Tuple[Dict[str, Any], bytes]:
    wrapper = _closed(wrapper, ("descriptor", "bytesBase64"), location=location)
    descriptor = _descriptor(
        wrapper["descriptor"],
        location + ".descriptor",
        expected_kind=expected_kind,
        expected_media=expected_media,
    )
    encoded = _string(
        wrapper["bytesBase64"],
        location + ".bytesBase64",
        maximum=((max_blob_bytes + 2) // 3) * 4,
    )
    try:
        data = base64.b64decode(encoded.encode("ascii"), validate=True)
    except (UnicodeEncodeError, binascii.Error) as exc:
        raise CompilationError(
            "BLOB", "bytesBase64 is not canonical base64", location
        ) from exc
    if base64.b64encode(data).decode("ascii") != encoded:
        _fail("BLOB", "bytesBase64 is not canonical base64", location)
    if len(data) > max_blob_bytes:
        _fail("LIMIT", "blob exceeds trusted profile limit", location)
    if descriptor["bytes"] != len(data):
        _fail("BLOB", "descriptor byte count disagrees with blob", location)
    if hashlib.sha256(data).hexdigest() != descriptor["sha256"]:
        _fail("BLOB", "descriptor digest disagrees with blob", location)
    return descriptor, data


def _record_artifact_descriptor(
    descriptors_by_path: Mapping[str, Dict[str, Any]],
    path: str,
    location: str,
) -> Dict[str, Any]:
    try:
        return descriptors_by_path[path]
    except KeyError:
        _fail(
            "RECORD",
            "record provenance points outside supplied artifacts",
            location,
        )


def _profile_limits(profile: Mapping[str, Any]) -> Dict[str, int]:
    limits = _closed(
        profile.get("limits"),
        (
            "maxClosureBytes",
            "maxBlobBytes",
            "maxRecordArtifacts",
            "maxRecords",
            "maxWorldPackSources",
            "maxEntities",
            "maxReferencesPerEntity",
            "maxOutputFiles",
            "maxOutputFileBytes",
            "maxWarnings",
        ),
        location="$.profile.limits",
    )
    result = {}
    for key, value in limits.items():
        result[key] = _integer(
            value, "$.profile.limits." + key, minimum=1, maximum=100_000_000
        )
    return result


def _validate_profile(profile: Any) -> Dict[str, Any]:
    profile = parse_json_v2(canonical_json_v2(profile))
    profile = _closed(
        profile,
        (
            "schemaVersion",
            "profileId",
            "version",
            "transformationVersion",
            "publicContract",
            "identity",
            "outputLayout",
            "entityKinds",
            "datasetRecipes",
            "overlayProtection",
            "seedDerivation",
            "placementPolicy",
            "legacyAliases",
            "limits",
        ),
        location="$.profile",
    )
    if profile["schemaVersion"] != PROFILE_VERSION:
        _fail("PROFILE", "unsupported profile schema", "$.profile.schemaVersion")
    _string(profile["profileId"], "$.profile.profileId", maximum=128)
    _string(profile["version"], "$.profile.version", maximum=32)
    _string(
        profile["transformationVersion"],
        "$.profile.transformationVersion",
        maximum=128,
    )
    contract = _closed(
        profile["publicContract"],
        ("repositoryId", "repositoryName", "commit", "canonicalization"),
        location="$.profile.publicContract",
    )
    _integer(
        contract["repositoryId"],
        "$.profile.publicContract.repositoryId",
        minimum=1,
    )
    _string(
        contract["repositoryName"],
        "$.profile.publicContract.repositoryName",
        maximum=128,
    )
    _hex(contract["commit"], 40, "$.profile.publicContract.commit")
    if contract["commit"] != PUBLIC_CONTRACT_COMMIT:
        _fail("PROFILE", "profile does not pin the public v2 contract commit")
    if (
        contract["repositoryId"] != PUBLIC_REPOSITORY_ID
        or contract["repositoryName"] != PUBLIC_REPOSITORY_NAME
    ):
        _fail("PROFILE", "profile does not pin the public repository identity")
    if contract["canonicalization"] != CANONICALIZATION_V2:
        _fail("PROFILE", "profile canonicalization is unsupported")

    identity = _closed(
        profile["identity"],
        (
            "domain",
            "namespace",
            "digest",
            "encoding",
            "displayLength",
            "identityRecordAttribute",
            "stableIdInputAttribute",
        ),
        location="$.profile.identity",
    )
    if identity["domain"] != "rappterverse-stable-entity-id/v1":
        _fail("PROFILE", "stable identity domain is unsupported")
    _string(identity["namespace"], "$.profile.identity.namespace", maximum=128)
    if identity["digest"] != "sha256" or identity["encoding"] != "base32-lower":
        _fail("PROFILE", "stable identity algorithm is unsupported")
    _integer(identity["displayLength"], "$.profile.identity.displayLength", minimum=1, maximum=52)
    _string(
        identity["identityRecordAttribute"],
        "$.profile.identity.identityRecordAttribute",
        maximum=64,
    )
    _string(
        identity["stableIdInputAttribute"],
        "$.profile.identity.stableIdInputAttribute",
        maximum=64,
    )

    layout = _closed(
        profile["outputLayout"],
        (
            "manifest",
            "worldsIndex",
            "worldConfig",
            "worldObjects",
            "worldNpcs",
            "agentBlueprints",
            "quests",
            "economy",
            "governance",
            "incidents",
            "lineages",
            "provenance",
            "legacyCompatibility",
        ),
        location="$.profile.outputLayout",
    )
    for key, path in layout.items():
        path = _string(path, "$.profile.outputLayout." + key, maximum=128)
        if key in ("worldConfig", "worldObjects", "worldNpcs"):
            if path.count("{worldId}") != 1:
                _fail("PROFILE", "world output path must contain {worldId}", key)
            _safe_path(path.replace("{worldId}", "world"), key)
        else:
            _safe_path(path, "$.profile.outputLayout." + key)
    if layout["manifest"] != "pack-manifest.json":
        _fail("PROFILE", "manifest output path must be pack-manifest.json")

    kinds = profile["entityKinds"]
    if not isinstance(kinds, dict) or not kinds:
        _fail("PROFILE", "entityKinds must be a non-empty object")
    expected_kinds = {
        "world",
        "portal",
        "agent-blueprint",
        "npc-blueprint",
        "quest",
        "object",
        "item",
        "currency",
        "governance",
        "incident",
        "lineage",
    }
    if set(kinds) != expected_kinds:
        _fail("PROFILE", "entity kind set is not the closed v1 set")
    prefixes: Set[str] = set()
    for kind, config in kinds.items():
        where = "$.profile.entityKinds." + kind
        config = _closed(
            config,
            ("prefix", "output", "allowedAttributes", "allowedRelations", "requiredRelations"),
            location=where,
        )
        prefix = _string(config["prefix"], where + ".prefix", maximum=24)
        if not _SAFE_ID.fullmatch(prefix) or prefix in prefixes:
            _fail("PROFILE", "kind prefixes must be unique safe IDs", where)
        prefixes.add(prefix)
        _string(config["output"], where + ".output", maximum=32)
        attrs = _unique_strings(
            config["allowedAttributes"],
            where + ".allowedAttributes",
            maximum_items=256,
            maximum_length=64,
        )
        relations = config["allowedRelations"]
        if not isinstance(relations, dict):
            _fail("PROFILE", "allowedRelations must be an object", where)
        for relation, target_kinds in relations.items():
            _string(relation, where + ".allowedRelations", maximum=128)
            targets = _unique_strings(
                target_kinds,
                where + ".allowedRelations." + relation,
                minimum_items=1,
                maximum_items=len(expected_kinds),
                maximum_length=64,
            )
            if not set(targets) <= expected_kinds:
                _fail("PROFILE", "relation permits an unknown target kind", where)
        required_relations = _unique_strings(
            config["requiredRelations"],
            where + ".requiredRelations",
            maximum_items=32,
            maximum_length=128,
        )
        if not set(required_relations) <= set(relations):
            _fail("PROFILE", "required relation is not allowed", where)

    recipes = profile["datasetRecipes"]
    if not isinstance(recipes, dict) or len(recipes) != 10:
        _fail("PROFILE", "datasetRecipes must define exactly ten datasets")
    for dataset_id, recipe_ids in recipes.items():
        if not re.fullmatch(r"d(?:0[1-9]|10)-[a-z0-9-]+", dataset_id):
            _fail("PROFILE", "invalid dataset ID", "$.profile.datasetRecipes")
        _unique_strings(
            recipe_ids,
            "$.profile.datasetRecipes." + dataset_id,
            minimum_items=1,
            maximum_items=64,
            maximum_length=120,
        )

    overlay = _closed(
        profile["overlayProtection"],
        ("publicPreservedFields", "denylist", "recursive"),
        location="$.profile.overlayProtection",
    )
    for key in ("publicPreservedFields", "denylist"):
        _unique_strings(
            overlay[key],
            "$.profile.overlayProtection." + key,
            maximum_items=256,
            maximum_length=64,
        )
    if overlay["recursive"] is not True:
        _fail("PROFILE", "overlay protection must be recursive")

    seed = _closed(
        profile["seedDerivation"],
        ("algorithm", "channels", "drawAddress", "boundedInteger"),
        location="$.profile.seedDerivation",
    )
    if seed["algorithm"] != "hkdf-hmac-sha256/v1":
        _fail("PROFILE", "unsupported seed algorithm")
    required_channels = [
        "immutable-layout",
        "frames",
        "engines",
        "visuals",
        "audio",
        "narrative",
        "economy",
        "governance",
    ]
    if seed["channels"] != required_channels:
        _fail("PROFILE", "seed channels or ordering are not the closed v1 set")
    if seed["drawAddress"] != "entityId/purpose/index":
        _fail("PROFILE", "unsupported seed draw address")
    if seed["boundedInteger"] != "sha256-rejection-sampling":
        _fail("PROFILE", "unsupported bounded integer policy")

    placement = _closed(
        profile["placementPolicy"],
        (
            "channel",
            "attribute",
            "defaultBounds",
            "rendererUnitsPerSimulationUnit",
        ),
        location="$.profile.placementPolicy",
    )
    if placement["channel"] != "immutable-layout":
        _fail("PROFILE", "placement must use immutable-layout")
    _string(placement["attribute"], "$.profile.placementPolicy.attribute", maximum=64)
    _bounds(placement["defaultBounds"], "$.profile.placementPolicy.defaultBounds")
    _integer(
        placement["rendererUnitsPerSimulationUnit"],
        "$.profile.placementPolicy.rendererUnitsPerSimulationUnit",
        minimum=1,
        maximum=1000,
    )
    aliases = _list(profile["legacyAliases"], "$.profile.legacyAliases")
    alias_keys: Set[Tuple[str, str, str]] = set()
    for index, group in enumerate(aliases):
        where = "$.profile.legacyAliases[{}]".format(index)
        group = _closed(group, ("scope", "entities"), location=where)
        scope = _string(group["scope"], where + ".scope", maximum=128)
        if not _SAFE_ID.fullmatch(scope):
            _fail("PROFILE", "legacy alias scope is unsafe", where)
        if not isinstance(group["entities"], dict) or not group["entities"]:
            _fail("PROFILE", "legacy alias entities must be non-empty", where)
        if not set(group["entities"]) <= expected_kinds:
            _fail("PROFILE", "legacy alias group has an unknown kind", where)
        for kind, legacy_ids in group["entities"].items():
            legacy_ids = _unique_strings(
                legacy_ids,
                where + ".entities." + kind,
                minimum_items=1,
                maximum_items=10000,
                maximum_length=128,
            )
            for legacy_id in legacy_ids:
                if not _SAFE_ID.fullmatch(legacy_id):
                    _fail("PROFILE", "legacy alias ID is unsafe", where)
                identity_record, stable_input = _legacy_alias_material(
                    scope, kind, legacy_id
                )
                key = (kind, identity_record, stable_input)
                if key in alias_keys:
                    _fail("PROFILE", "duplicate legacy alias material", where)
                alias_keys.add(key)
    _profile_limits(profile)
    canonical_json_v2(profile, stored=True)
    return profile


def load_trusted_profile(path: Optional[Path] = None) -> Dict[str, Any]:
    """Load the engine-owned canonical profile from a non-symlink file."""

    root = Path(__file__).resolve().parents[2]
    canonical_path = root / TRUSTED_PROFILE_PATH
    if path is not None and path.absolute() != canonical_path:
        _fail(
            "PROFILE",
            "alternate trusted profile paths are not accepted",
            str(path),
        )
    path = canonical_path
    if path.is_symlink() or not path.is_file():
        _fail("PROFILE", "trusted profile is missing or is a symlink", str(path))
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != TRUSTED_PROFILE_RAW_SHA256:
        _fail("PROFILE", "trusted profile raw digest mismatch", str(path))
    profile = parse_json_v2(data)
    return _validate_profile(profile)


def _bounds(value: Any, location: str) -> Dict[str, List[int]]:
    value = _closed(value, ("x", "z"), location=location)
    result: Dict[str, List[int]] = {}
    for axis in ("x", "z"):
        pair = _list(value[axis], location + "." + axis)
        if len(pair) != 2:
            _fail("BOUNDS", "bounds must contain exactly two integers", location)
        low = _integer(pair[0], location + "." + axis + "[0]")
        high = _integer(pair[1], location + "." + axis + "[1]")
        if low >= high:
            _fail("BOUNDS", "lower bound must be less than upper bound", location)
        result[axis] = [low, high]
    return result


def _point(value: Any, location: str) -> Dict[str, int]:
    value = _closed(value, ("x", "y", "z"), location=location)
    return {
        axis: _integer(value[axis], location + "." + axis)
        for axis in ("x", "y", "z")
    }


def _record_shape(record: Any, location: str) -> Dict[str, Any]:
    record = _closed(
        record,
        (
            "schemaVersion",
            "datasetId",
            "recordId",
            "recordType",
            "episodeId",
            "sequence",
            "split",
            "eventTime",
            "payload",
            "provenance",
            "generation",
            "governance",
        ),
        location=location,
    )
    if record["schemaVersion"] != "rappterverse.public-record/v2":
        _fail("RECORD", "record is not public-record/v2", location)
    if not _RECORD_ID.fullmatch(_string(record["recordId"], location + ".recordId", maximum=128)):
        _fail("RECORD", "invalid record ID", location)
    _string(record["datasetId"], location + ".datasetId", maximum=64)
    _string(record["recordType"], location + ".recordType", maximum=64)
    _string(record["episodeId"], location + ".episodeId", maximum=128)
    _integer(record["sequence"], location + ".sequence", minimum=0)
    if record["split"] not in ("train", "validation", "test", "unassigned"):
        _fail("RECORD", "invalid record split", location)
    _string(record["eventTime"], location + ".eventTime", maximum=40)
    for key in ("payload", "provenance", "generation", "governance"):
        if not isinstance(record[key], dict):
            _fail("RECORD", "{} must be an object".format(key), location)
    return record


def _release_manifest_shape(
    manifest: Any, location: str
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    manifest = _closed(
        manifest,
        (
            "schemaVersion",
            "releaseId",
            "createdAt",
            "sequence",
            "previousReleaseId",
            "previousReleasePointer",
            "policy",
            "datasets",
            "worldPackSources",
            "totals",
        ),
        location=location,
    )
    if manifest["schemaVersion"] != "rappterverse.release-manifest/v2":
        _fail("RELEASE", "release manifest is not v2", location)
    _release_id(manifest["releaseId"], location + ".releaseId")
    _string(manifest["createdAt"], location + ".createdAt", maximum=40)
    sequence = _integer(manifest["sequence"], location + ".sequence", minimum=1)
    if sequence == 1:
        if (
            manifest["previousReleaseId"] is not None
            or manifest["previousReleasePointer"] is not None
        ):
            _fail("RELEASE", "genesis release must have no predecessor", location)
    else:
        _release_id(
            manifest["previousReleaseId"],
            location + ".previousReleaseId",
        )
        previous = _closed(
            manifest["previousReleasePointer"],
            ("path", "artifactKind", "mediaType", "bytes", "sha256"),
            location=location + ".previousReleasePointer",
        )
        _safe_path(previous["path"], location + ".previousReleasePointer.path")
        _string(previous["artifactKind"], location + ".previousReleasePointer.artifactKind", maximum=64)
        _string(previous["mediaType"], location + ".previousReleasePointer.mediaType", maximum=64)
        _integer(previous["bytes"], location + ".previousReleasePointer.bytes", minimum=1, maximum=1_000_000)
        _hex(previous["sha256"], 64, location + ".previousReleasePointer.sha256")
    policy = _closed(
        manifest["policy"],
        ("path", "policyId", "policyVersion", "sha256"),
        location=location + ".policy",
    )
    _safe_path(policy["path"], location + ".policy.path")
    _string(policy["policyId"], location + ".policy.policyId", maximum=128)
    _string(policy["policyVersion"], location + ".policy.policyVersion", maximum=32)
    _hex(policy["sha256"], 64, location + ".policy.sha256")
    datasets = _list(manifest["datasets"], location + ".datasets")
    if len(datasets) != 10:
        _fail("RELEASE", "release manifest must contain exactly ten datasets", location)
    dataset_ids: Set[str] = set()
    nested_descriptors: List[Dict[str, Any]] = []
    for index, dataset in enumerate(datasets):
        where = "{}.datasets[{}]".format(location, index)
        dataset = _closed(
            dataset,
            ("datasetId", "datasetVersion", "manifest", "counts", "contentBytes"),
            location=where,
        )
        dataset_id = _string(dataset["datasetId"], where + ".datasetId", maximum=64)
        if dataset_id in dataset_ids:
            _fail("RELEASE", "duplicate dataset ID", where)
        dataset_ids.add(dataset_id)
        _string(dataset["datasetVersion"], where + ".datasetVersion", maximum=32)
        nested_descriptors.append(
            _descriptor(
                dataset["manifest"],
                where + ".manifest",
                expected_kind="dataset-manifest",
                expected_media="application/json",
            )
        )
        counts = _closed(
            dataset["counts"],
            ("records", "transcripts", "deliberations", "providerReasoning"),
            location=where + ".counts",
        )
        for key, count in counts.items():
            _integer(count, where + ".counts." + key, minimum=0)
        _integer(dataset["contentBytes"], where + ".contentBytes", minimum=1)
    if dataset_ids != PUBLIC_DATASET_IDS:
        _fail("RELEASE", "release manifest dataset set is not the closed v2 set", location)
    sources = _list(manifest["worldPackSources"], location + ".worldPackSources")
    if not sources:
        _fail("RELEASE", "release manifest has no world-pack sources", location)
    for index, descriptor in enumerate(sources):
        nested_descriptors.append(
            _descriptor(
                descriptor,
                "{}.worldPackSources[{}]".format(location, index),
                expected_kind="world-pack-source",
                expected_media="application/json",
            )
        )
    totals = _closed(
        manifest["totals"],
        (
            "datasets",
            "records",
            "transcripts",
            "deliberations",
            "providerReasoning",
            "worldPackSources",
            "contentBytes",
        ),
        location=location + ".totals",
    )
    for key, count in totals.items():
        _integer(count, location + ".totals." + key, minimum=0)
    if totals["datasets"] != 10 or totals["worldPackSources"] != len(sources):
        _fail("RELEASE", "release totals disagree with manifest arrays", location)
    return manifest, nested_descriptors


def _world_source_shape(
    source: Any,
    location: str,
    profile: Mapping[str, Any],
    limits: Mapping[str, int],
) -> Dict[str, Any]:
    source = _closed(
        source,
        (
            "schemaVersion",
            "worldPackSourceId",
            "releaseId",
            "projectionRecipe",
            "namespace",
            "seedChannels",
            "entities",
            "sortedByStableKey",
            "canonicalization",
        ),
        location=location,
    )
    if source["schemaVersion"] != "rappterverse.world-pack-source/v2":
        _fail("SOURCE", "world-pack source is not v2", location)
    _string(source["worldPackSourceId"], location + ".worldPackSourceId", maximum=128)
    _release_id(source["releaseId"], location + ".releaseId")
    _descriptor(
        source["projectionRecipe"],
        location + ".projectionRecipe",
        expected_kind="projection-recipe",
        expected_media="application/json",
    )
    _string(source["namespace"], location + ".namespace", maximum=128)
    if source["sortedByStableKey"] is not True:
        _fail("SOURCE", "sortedByStableKey must be true", location)
    if source["canonicalization"] != CANONICALIZATION_V2:
        _fail("SOURCE", "canonicalization is not v2", location)
    channels = _list(source["seedChannels"], location + ".seedChannels")
    expected_channels = profile["seedDerivation"]["channels"]
    if len(channels) != len(expected_channels):
        _fail("SEED", "exactly eight seed channels are required", location)
    seen_channels: Set[str] = set()
    for index, channel in enumerate(channels):
        where = "{}.seedChannels[{}]".format(location, index)
        channel = _closed(channel, ("channel", "seed"), location=where)
        name = _string(channel["channel"], where + ".channel", maximum=64)
        _string(channel["seed"], where + ".seed", maximum=256)
        if name in seen_channels:
            _fail("SEED", "duplicate seed channel", where)
        seen_channels.add(name)
    if seen_channels != set(expected_channels):
        _fail("SEED", "seed channel set is not the closed v1 set", location)
    entities = _list(source["entities"], location + ".entities")
    if not entities or len(entities) > limits["maxEntities"]:
        _fail("LIMIT", "world-pack source entity count is outside limits", location)
    return source


def _source_entity_shape(
    value: Any,
    location: str,
    profile: Mapping[str, Any],
    limits: Mapping[str, int],
) -> Dict[str, Any]:
    value = _closed(
        value,
        (
            "entityId",
            "kind",
            "name",
            "description",
            "sourceRecordIds",
            "tags",
            "attributes",
            "references",
            "immutableBase",
            "preservedOverlayFields",
        ),
        location=location,
    )
    entity_id = _string(value["entityId"], location + ".entityId", maximum=256)
    if not _SOURCE_ENTITY_ID.fullmatch(entity_id):
        _fail("ENTITY", "invalid source entity ID", location)
    kind = _string(value["kind"], location + ".kind", maximum=64)
    if kind not in profile["entityKinds"]:
        _fail("UNKNOWN_KIND", "entity kind is not trusted", location)
    _string(value["name"], location + ".name", maximum=256)
    _string(value["description"], location + ".description", maximum=4096)
    records = _unique_strings(
        value["sourceRecordIds"],
        location + ".sourceRecordIds",
        minimum_items=1,
        maximum_items=1024,
        maximum_length=128,
    )
    for record_id in records:
        if not _RECORD_ID.fullmatch(
            record_id
        ):
            _fail("ENTITY", "invalid source record ID", location)
    _unique_strings(
        value["tags"],
        location + ".tags",
        maximum_items=128,
        maximum_length=64,
    )
    if not isinstance(value["attributes"], dict):
        _fail("ENTITY", "attributes must be an object", location)
    allowed = set(profile["entityKinds"][kind]["allowedAttributes"])
    unknown = sorted(set(value["attributes"]) - allowed)
    if unknown:
        _fail(
            "UNKNOWN_ATTRIBUTE",
            "attributes are not trusted: {}".format(unknown),
            location + ".attributes",
        )
    references = _list(value["references"], location + ".references")
    if len(references) > limits["maxReferencesPerEntity"]:
        _fail("LIMIT", "entity has too many references", location)
    seen_references: Set[Tuple[str, str]] = set()
    for index, reference in enumerate(references):
        where = "{}.references[{}]".format(location, index)
        reference = _closed(
            reference, ("relation", "targetEntityId", "required"), location=where
        )
        relation = _string(reference["relation"], where + ".relation", maximum=128)
        if relation not in profile["entityKinds"][kind]["allowedRelations"]:
            _fail("REFERENCE", "relation is not allowed for entity kind", where)
        target = _string(reference["targetEntityId"], where + ".targetEntityId", maximum=256)
        if not _SOURCE_ENTITY_ID.fullmatch(target):
            _fail("REFERENCE", "invalid target source entity ID", where)
        if not isinstance(reference["required"], bool):
            _fail("REFERENCE", "required must be boolean", where)
        key = (relation, target)
        if key in seen_references:
            _fail("REFERENCE", "duplicate entity reference", where)
        seen_references.add(key)
    if value["immutableBase"] is not True:
        _fail("ENTITY", "immutableBase must be true", location)
    preserved = _unique_strings(
        value["preservedOverlayFields"],
        location + ".preservedOverlayFields",
        maximum_items=64,
        maximum_length=64,
    )
    public_fields = set(profile["overlayProtection"]["publicPreservedFields"])
    if not set(preserved) <= public_fields:
        _fail("OVERLAY", "preserved overlay fields are invalid", location)
    canonical_json_v2(value)
    return value


def _normalize_field_name(value: str) -> str:
    return "".join(character.lower() for character in value if character.isalnum())


def _check_protected_fields(
    value: Any,
    protected: Set[str],
    location: str,
) -> None:
    stack = [(value, location)]
    while stack:
        item, where = stack.pop()
        if isinstance(item, dict):
            for key, child in item.items():
                if _normalize_field_name(key) in protected:
                    _fail(
                        "PROTECTED_OVERLAY_FIELD",
                        "field {!r} belongs to mutable overlay state".format(key),
                        where,
                    )
                stack.append((child, where + "." + key))
        elif isinstance(item, list):
            stack.extend(
                (child, "{}[{}]".format(where, index))
                for index, child in enumerate(item)
            )


def _validate_recipe(recipe: Any, location: str) -> Dict[str, Any]:
    recipe = _closed(
        recipe,
        (
            "schemaVersion",
            "recipeId",
            "version",
            "engine",
            "configuration",
            "deterministic",
        ),
        location=location,
    )
    if recipe["schemaVersion"] != "rappterverse.projection-recipe/v2":
        _fail("RECIPE", "projection recipe is not v2", location)
    _string(recipe["recipeId"], location + ".recipeId", maximum=128)
    _string(recipe["version"], location + ".version", maximum=32)
    if recipe["engine"] != "rappterverse-world-pack-projection/v1":
        _fail("RECIPE", "projection engine is not trusted", location)
    if not isinstance(recipe["configuration"], dict):
        _fail("RECIPE", "configuration must be inert JSON data", location)
    if recipe["deterministic"] is not True:
        _fail("RECIPE", "recipe must declare deterministic=true", location)
    return recipe


def _validate_verified_closure_internal(
    verified_closure: Any, trusted_profile: Mapping[str, Any]
) -> Dict[str, Any]:
    """Validate and normalize a future-verifier-produced in-memory closure."""

    profile = _validate_profile(copy.deepcopy(trusted_profile))
    limits = _profile_limits(profile)
    closure = _closed(
        copy.deepcopy(verified_closure),
        (
            "schemaVersion",
            "verified",
            "publicRepository",
            "dataCommit",
            "publicContract",
            "release",
            "recordArtifacts",
            "records",
            "worldPackSources",
            "projectionRecipes",
            "verificationProof",
            "sourceClosureSha256",
        ),
        location="$",
    )
    if closure["schemaVersion"] != CLOSURE_VERSION:
        _fail("CLOSURE", "unsupported verified closure schema")
    if closure["verified"] is not True:
        _fail("CLOSURE", "verified must be true, but is never sufficient evidence")

    repository = _closed(
        closure["publicRepository"],
        ("repositoryId", "name"),
        location="$.publicRepository",
    )
    if _integer(repository["repositoryId"], "$.publicRepository.repositoryId", minimum=1) != profile["publicContract"]["repositoryId"]:
        _fail("CLOSURE", "public repository numeric ID is not trusted")
    if repository["name"] != profile["publicContract"]["repositoryName"]:
        _fail("CLOSURE", "public repository name is not trusted")
    _hex(closure["dataCommit"], 40, "$.dataCommit")
    contract = _closed(
        closure["publicContract"],
        ("repository", "commit", "canonicalization"),
        location="$.publicContract",
    )
    if (
        contract["repository"] != profile["publicContract"]["repositoryName"]
        or contract["commit"] != profile["publicContract"]["commit"]
        or contract["canonicalization"] != CANONICALIZATION_V2
    ):
        _fail("CLOSURE", "public contract binding does not match trusted profile")

    supplied_digest = _prefixed_digest(
        closure["sourceClosureSha256"], "$.sourceClosureSha256"
    )
    digest_material = dict(closure)
    del digest_material["sourceClosureSha256"]
    actual_digest = source_closure_digest(digest_material)
    if supplied_digest != actual_digest:
        _fail("SOURCE_MUTATION", "source closure digest does not match contents")
    if len(canonical_json_v2(closure, stored=True)) > limits["maxClosureBytes"]:
        _fail("LIMIT", "closure exceeds trusted profile byte limit")

    proof = _closed(
        closure["verificationProof"],
        ("verifier", "activeReviewSet", "reviewReceipts"),
        location="$.verificationProof",
    )
    if proof["verifier"] != "rappterverse-universe-source-verifier/v1":
        _fail("CLOSURE", "unknown verifier boundary")
    _review_set_ref(proof["activeReviewSet"], "$.verificationProof.activeReviewSet")
    receipt_refs = _list(
        proof["reviewReceipts"], "$.verificationProof.reviewReceipts"
    )
    receipts_by_path: Dict[str, str] = {}
    for index, receipt in enumerate(receipt_refs):
        receipt = _receipt_ref(
            receipt, "$.verificationProof.reviewReceipts[{}]".format(index)
        )
        if receipt["path"] in receipts_by_path:
            _fail("CLOSURE", "duplicate review receipt proof")
        receipts_by_path[receipt["path"]] = receipt["sha256"]

    release = _closed(
        closure["release"],
        ("releaseId", "manifest"),
        location="$.release",
    )
    release_id = _release_id(release["releaseId"], "$.release.releaseId")
    release_descriptor, release_bytes = _decode_blob(
        release["manifest"],
        "$.release.manifest",
        expected_kind="release-manifest",
        expected_media="application/json",
        max_blob_bytes=limits["maxBlobBytes"],
    )
    if release_descriptor["path"] != "releases/{}/manifest.json".format(release_id):
        _fail("RELEASE", "release manifest path does not bind release ID")
    release_manifest, release_nested_descriptors = _release_manifest_shape(
        parse_json_v2(
            release_bytes,
            require_stored=True,
            max_bytes=limits["maxBlobBytes"],
        ),
        "$.release.manifest",
    )
    if release_manifest["releaseId"] != release_id:
        _fail("RELEASE", "release manifest identity mismatch")
    manifest_sources = _list(
        release_manifest.get("worldPackSources"), "$.release.manifest.worldPackSources"
    )
    manifest_source_descriptors: Dict[str, Dict[str, Any]] = {}
    for index, descriptor in enumerate(manifest_sources):
        descriptor = _descriptor(
            descriptor,
            "$.release.manifest.worldPackSources[{}]".format(index),
            expected_kind="world-pack-source",
            expected_media="application/json",
        )
        if descriptor["path"] in manifest_source_descriptors:
            _fail("RELEASE", "duplicate world-pack source descriptor")
        manifest_source_descriptors[descriptor["path"]] = descriptor

    record_artifacts = _list(closure["recordArtifacts"], "$.recordArtifacts")
    if len(record_artifacts) > limits["maxRecordArtifacts"]:
        _fail("LIMIT", "too many record artifacts")
    artifact_lines: Dict[str, List[Tuple[Dict[str, Any], bytes]]] = {}
    record_artifact_descriptors: Dict[str, Dict[str, Any]] = {}
    all_descriptors: List[Dict[str, Any]] = [
        release_descriptor,
        *release_nested_descriptors,
    ]
    for index, wrapper in enumerate(record_artifacts):
        where = "$.recordArtifacts[{}]".format(index)
        descriptor, data = _decode_blob(
            wrapper,
            where,
            expected_kind="record-shard",
            expected_media="application/x-ndjson",
            max_blob_bytes=limits["maxBlobBytes"],
        )
        path = descriptor["path"]
        if path in record_artifact_descriptors:
            qualifier = (
                "duplicate"
                if record_artifact_descriptors[path] == descriptor
                else "conflicting"
            )
            _fail(
                "CLOSURE",
                "{} record artifact descriptor path".format(qualifier),
                where,
            )
        parsed = parse_jsonl_v2(
            data,
            max_bytes=limits["maxBlobBytes"],
            max_lines=limits["maxRecords"],
        )
        typed_lines = [
            (_record_shape(value, "{}:{}".format(path, line_index)), raw)
            for line_index, (value, raw) in enumerate(parsed)
        ]
        artifact_lines[path] = typed_lines
        record_artifact_descriptors[path] = descriptor
        all_descriptors.append(descriptor)

    record_refs = _list(closure["records"], "$.records")
    if not record_refs or len(record_refs) > limits["maxRecords"]:
        _fail("LIMIT", "record count is outside trusted limits")
    records: Dict[str, Dict[str, Any]] = {}
    record_provenance: Dict[str, Dict[str, Any]] = {}
    seen_line_addresses: Set[Tuple[str, int]] = set()
    for index, ref in enumerate(record_refs):
        where = "$.records[{}]".format(index)
        ref = _closed(
            ref,
            ("recordId", "artifactPath", "lineIndex", "lineSha256"),
            location=where,
        )
        record_id = _string(ref["recordId"], where + ".recordId", maximum=128)
        if not _RECORD_ID.fullmatch(record_id) or record_id in records:
            _fail("RECORD", "record IDs must be globally unique", where)
        path = _safe_path(ref["artifactPath"], where + ".artifactPath")
        line_index = _integer(ref["lineIndex"], where + ".lineIndex", minimum=0)
        line_digest = _hex(ref["lineSha256"], 64, where + ".lineSha256")
        descriptor = _record_artifact_descriptor(
            record_artifact_descriptors, path, where
        )
        if line_index >= len(artifact_lines[path]):
            _fail("RECORD", "record provenance points outside supplied artifacts", where)
        address = (path, line_index)
        if address in seen_line_addresses:
            _fail("RECORD", "multiple records point to one artifact line", where)
        seen_line_addresses.add(address)
        record, raw_line = artifact_lines[path][line_index]
        if record["recordId"] != record_id:
            _fail("RECORD", "record ID disagrees with artifact line", where)
        if hashlib.sha256(raw_line).hexdigest() != line_digest:
            _fail("RECORD", "record line digest mismatch", where)
        records[record_id] = record
        record_provenance[record_id] = {
            "artifact": descriptor,
            "lineIndex": line_index,
            "lineSha256": line_digest,
        }
    all_line_addresses = {
        (path, index)
        for path, lines in artifact_lines.items()
        for index in range(len(lines))
    }
    if seen_line_addresses != all_line_addresses:
        _fail("CLOSURE", "record artifacts contain undeclared extra lines")

    recipes_wrappers = _list(closure["projectionRecipes"], "$.projectionRecipes")
    recipe_values: Dict[str, Tuple[Dict[str, Any], Dict[str, Any]]] = {}
    for index, wrapper in enumerate(recipes_wrappers):
        where = "$.projectionRecipes[{}]".format(index)
        descriptor, data = _decode_blob(
            wrapper,
            where,
            expected_kind="projection-recipe",
            expected_media="application/json",
            max_blob_bytes=limits["maxBlobBytes"],
        )
        if descriptor["path"] in recipe_values:
            _fail("CLOSURE", "duplicate projection recipe path", where)
        recipe = _validate_recipe(
            parse_json_v2(data, require_stored=True, max_bytes=limits["maxBlobBytes"]),
            where,
        )
        recipe_values[descriptor["path"]] = (descriptor, recipe)
        all_descriptors.append(descriptor)

    source_wrappers = _list(closure["worldPackSources"], "$.worldPackSources")
    if not source_wrappers or len(source_wrappers) > limits["maxWorldPackSources"]:
        _fail("LIMIT", "world-pack source count is outside limits")
    source_values: Dict[str, Dict[str, Any]] = {}
    recipe_paths_used: Set[str] = set()
    entity_ids: Set[str] = set()
    referenced_record_ids: Set[str] = set()
    protected = {
        _normalize_field_name(name)
        for name in (
            profile["overlayProtection"]["publicPreservedFields"]
            + profile["overlayProtection"]["denylist"]
        )
    }
    total_entities = 0
    for index, wrapper in enumerate(source_wrappers):
        where = "$.worldPackSources[{}]".format(index)
        descriptor, data = _decode_blob(
            wrapper,
            where,
            expected_kind="world-pack-source",
            expected_media="application/json",
            max_blob_bytes=limits["maxBlobBytes"],
        )
        if descriptor["path"] in source_values:
            _fail("CLOSURE", "duplicate world-pack source path", where)
        if descriptor["path"] not in manifest_source_descriptors:
            _fail("CLOSURE", "source is not in the bound release manifest", where)
        if descriptor != manifest_source_descriptors[descriptor["path"]]:
            _fail("CLOSURE", "source descriptor differs from release manifest", where)
        source = _world_source_shape(
            parse_json_v2(data, require_stored=True, max_bytes=limits["maxBlobBytes"]),
            where,
            profile,
            limits,
        )
        if source["releaseId"] != release_id:
            _fail("SOURCE", "world-pack source release ID mismatch", where)
        recipe_descriptor = source["projectionRecipe"]
        recipe_path = recipe_descriptor["path"]
        if recipe_path not in recipe_values:
            _fail("SOURCE", "projection recipe bytes are absent", where)
        if recipe_values[recipe_path][0] != recipe_descriptor:
            _fail("SOURCE", "projection recipe descriptor mismatch", where)
        recipe_paths_used.add(recipe_path)
        for entity_index, entity in enumerate(source["entities"]):
            entity_where = "{}.entities[{}]".format(where, entity_index)
            entity = _source_entity_shape(entity, entity_where, profile, limits)
            if entity["entityId"] in entity_ids:
                _fail("DUPLICATE_ID", "source entity IDs must be globally unique", entity_where)
            entity_ids.add(entity["entityId"])
            total_entities += 1
            if total_entities > limits["maxEntities"]:
                _fail("LIMIT", "total entity count exceeds trusted limit")
            _check_protected_fields(entity["attributes"], protected, entity_where + ".attributes")
            for record_id in entity["sourceRecordIds"]:
                if record_id not in records:
                    _fail("RECORD", "source entity references an absent record", entity_where)
                referenced_record_ids.add(record_id)
                dataset_id = records[record_id]["datasetId"]
                recipe_id = recipe_values[recipe_path][1]["recipeId"]
                if dataset_id not in profile["datasetRecipes"]:
                    _fail("RECIPE", "record dataset is not mapped by trusted profile", entity_where)
                if recipe_id not in profile["datasetRecipes"][dataset_id]:
                    _fail("RECIPE", "recipe is not trusted for record dataset", entity_where)
        source_values[descriptor["path"]] = source
        all_descriptors.append(descriptor)
    if set(source_values) != set(manifest_source_descriptors):
        _fail("CLOSURE", "release manifest sources and supplied sources differ")
    if recipe_paths_used != set(recipe_values):
        _fail("CLOSURE", "projection recipe closure contains extra files")
    if referenced_record_ids != set(records):
        _fail("CLOSURE", "record closure contains unreferenced extra records")

    required_receipts = {descriptor["reviewReceiptRef"] for descriptor in all_descriptors}
    if required_receipts != set(receipts_by_path):
        _fail("CLOSURE", "review receipt proof set is incomplete or contains extras")

    closure["_validated"] = {
        "profile": profile,
        "limits": limits,
        "releaseManifest": release_manifest,
        "releaseDescriptor": release_descriptor,
        "records": records,
        "recordProvenance": record_provenance,
        "recipeValues": recipe_values,
        "sourceValues": source_values,
    }
    return closure


def validate_verified_closure(
    verified_closure: Any, trusted_profile: Mapping[str, Any]
) -> Dict[str, Any]:
    """Return a validated normalized closure without compiler-private fields."""

    closure = _validate_verified_closure_internal(
        verified_closure, trusted_profile
    )
    closure.pop("_validated")
    return closure


def _legacy_alias_material(
    scope: str, kind: str, legacy_id: str
) -> Tuple[str, str]:
    return (
        "legacy-record:{}:{}:{}".format(scope, kind, legacy_id),
        "legacy/{}/{}/{}".format(scope, kind, legacy_id),
    )


def _iter_legacy_aliases(
    profile: Mapping[str, Any]
) -> Iterable[Tuple[str, str, str, str]]:
    for group in profile["legacyAliases"]:
        for kind, legacy_ids in sorted(group["entities"].items()):
            for legacy_id in legacy_ids:
                identity_record, stable_input = _legacy_alias_material(
                    group["scope"], kind, legacy_id
                )
                yield kind, identity_record, stable_input, legacy_id


def _alias_index(profile: Mapping[str, Any]) -> Dict[str, str]:
    identity = profile["identity"]
    result: Dict[str, str] = {}
    for kind, identity_record, stable_input, legacy_id in _iter_legacy_aliases(
        profile
    ):
        digest = stable_identity_digest(
            identity["namespace"],
            kind,
            identity_record,
            stable_input,
        )
        if digest in result:
            _fail("PROFILE", "legacy aliases collide by full identity digest")
        result[digest] = legacy_id
    return result


def _relation_values(entity: _Entity, relation: str) -> List[Dict[str, Any]]:
    return [ref for ref in entity.references if ref["relation"] == relation]


def _detect_cycle(graph: Mapping[str, Sequence[str]], code: str) -> None:
    nodes = set(graph)
    for targets in graph.values():
        nodes.update(targets)
    dependencies = {
        node: set(graph.get(node, ()))
        for node in nodes
    }
    dependents: Dict[str, Set[str]] = {node: set() for node in nodes}
    for node, targets in dependencies.items():
        for target in targets:
            dependents[target].add(node)
    ready = [node for node, targets in dependencies.items() if not targets]
    heapq.heapify(ready)
    processed = 0
    while ready:
        target = heapq.heappop(ready)
        processed += 1
        for dependent in sorted(dependents[target]):
            dependencies[dependent].discard(target)
            if not dependencies[dependent]:
                heapq.heappush(ready, dependent)
    if processed != len(nodes):
        cyclic = min(node for node, targets in dependencies.items() if targets)
        _fail(code, "dependency graph contains a cycle", cyclic)


def _derived_placement(
    entity: _Entity,
    bounds: Mapping[str, Sequence[int]],
    profile: Mapping[str, Any],
) -> Dict[str, int]:
    attribute = profile["placementPolicy"]["attribute"]
    explicit = entity.value["attributes"].get(attribute)
    if explicit is not None:
        point = _point(explicit, "$.entity.{}.attributes.{}".format(entity.entity_id, attribute))
    else:
        x_low, x_high = bounds["x"]
        z_low, z_high = bounds["z"]
        point = {
            "x": x_low
            + entity.source.seed_bank.bounded_int(
                "immutable-layout",
                entity.display_id,
                "placement-x",
                0,
                x_high - x_low + 1,
            ),
            "y": 0,
            "z": z_low
            + entity.source.seed_bank.bounded_int(
                "immutable-layout",
                entity.display_id,
                "placement-z",
                0,
                z_high - z_low + 1,
            ),
        }
        entity.seed_draws.extend(
            [
                {"channel": "immutable-layout", "purpose": "placement-x", "index": 0},
                {"channel": "immutable-layout", "purpose": "placement-z", "index": 0},
            ]
        )
    if not (
        bounds["x"][0] <= point["x"] <= bounds["x"][1]
        and bounds["z"][0] <= point["z"] <= bounds["z"][1]
    ):
        _fail("BOUNDS", "entity placement is outside its world", entity.entity_id)
    return point


def _base_row(entity: _Entity) -> Dict[str, Any]:
    return {
        "description": entity.value["description"],
        "id": entity.display_id,
        "identitySha256": "sha256:" + entity.identity_digest,
        "kind": entity.kind,
        "name": entity.value["name"],
        "provenanceId": entity.display_id,
        "tags": sorted(entity.value["tags"]),
    }


def _safe_defaults(entity: _Entity, profile: Mapping[str, Any]) -> Dict[str, Any]:
    consumed = {
        profile["identity"]["identityRecordAttribute"],
        profile["identity"]["stableIdInputAttribute"],
        profile["placementPolicy"]["attribute"],
        "bounds",
        "spawn",
        "features",
        "renderer",
        "rendererScale",
        "worldKey",
        "roles",
        "generation",
        "stableKey",
    }
    return {
        key: copy.deepcopy(value)
        for key, value in sorted(entity.value["attributes"].items())
        if key not in consumed
    }


def _provenance_row(
    entity: _Entity,
    closure: Mapping[str, Any],
    profile: Mapping[str, Any],
    profile_sha: str,
    records: Mapping[str, Mapping[str, Any]],
    record_provenance: Mapping[str, Mapping[str, Any]],
) -> Dict[str, Any]:
    descriptor = entity.source.descriptor
    recipe_descriptor = entity.source.recipe_descriptor
    record_rows = []
    for record_id in sorted(entity.value["sourceRecordIds"]):
        record_rows.append(
            {
                "datasetId": records[record_id]["datasetId"],
                "recordId": record_id,
                "source": record_provenance[record_id],
            }
        )
    relevant_receipts = sorted(
        {
            closure["_validated"]["releaseDescriptor"]["reviewReceiptRef"],
            descriptor["reviewReceiptRef"],
            recipe_descriptor["reviewReceiptRef"],
            *[
                item["source"]["artifact"]["reviewReceiptRef"]
                for item in record_rows
            ],
        }
    )
    proof_by_path = {
        item["path"]: item
        for item in closure["verificationProof"]["reviewReceipts"]
    }
    return {
        "compiler": {
            "implementationSha256": COMPILER_IMPLEMENTATION_SHA256,
            "version": COMPILER_VERSION,
        },
        "entityId": entity.display_id,
        "identity": {
            "identityRecordId": entity.identity_record_id,
            "identitySha256": "sha256:" + entity.identity_digest,
            "legacyAlias": entity.legacy_alias,
            "stableIdInput": entity.stable_id_input,
        },
        "profile": {
            "profileId": profile["profileId"],
            "profileSha256": profile_sha,
            "transformationVersion": profile["transformationVersion"],
            "version": profile["version"],
        },
        "projectionRecipe": {
            "path": recipe_descriptor["path"],
            "recipeId": entity.source.recipe["recipeId"],
            "sha256": "sha256:" + recipe_descriptor["sha256"],
        },
        "records": record_rows,
        "release": {
            "dataCommit": closure["dataCommit"],
            "manifestPath": closure["_validated"]["releaseDescriptor"]["path"],
            "manifestSha256": "sha256:"
            + closure["_validated"]["releaseDescriptor"]["sha256"],
            "releaseId": closure["release"]["releaseId"],
            "repositoryId": closure["publicRepository"]["repositoryId"],
            "repositoryName": closure["publicRepository"]["name"],
        },
        "reviewProof": {
            "activeReviewSet": closure["verificationProof"]["activeReviewSet"],
            "reviewReceipts": [proof_by_path[path] for path in relevant_receipts],
            "verifier": closure["verificationProof"]["verifier"],
        },
        "schemaVersion": "rappterverse.world-pack-provenance/v1",
        "seed": {
            "channelRootSha256": entity.source.seed_bank.root_digests(),
            "draws": sorted(
                entity.seed_draws,
                key=lambda item: (item["channel"], item["purpose"], item["index"]),
            ),
            "sourceNamespace": entity.source.value["namespace"],
        },
        "sourceEntityId": entity.entity_id,
        "worldPackSource": {
            "path": descriptor["path"],
            "sha256": "sha256:" + descriptor["sha256"],
            "worldPackSourceId": entity.source.value["worldPackSourceId"],
        },
    }


def _add_file(
    files: MutableMapping[str, bytes],
    path: str,
    value: Any,
    limits: Mapping[str, int],
) -> None:
    _safe_path(path, path)
    if path in files:
        _fail("DUPLICATE_PATH", "compiler attempted a duplicate output path", path)
    data = canonical_json_v2(
        value, stored=True, max_bytes=limits["maxOutputFileBytes"]
    )
    files[path] = data
    if len(files) > limits["maxOutputFiles"]:
        _fail("LIMIT", "compiler output file count exceeds trusted limit")


def compile_world_pack(
    verified_closure: Mapping[str, Any],
    trusted_profile: Mapping[str, Any],
) -> CompilationResult:
    """Compile verified in-memory source data without external side effects."""

    closure = _validate_verified_closure_internal(
        verified_closure, trusted_profile
    )
    profile = closure["_validated"]["profile"]
    limits = closure["_validated"]["limits"]
    records = closure["_validated"]["records"]
    record_provenance = closure["_validated"]["recordProvenance"]
    profile_sha = "sha256:" + hashlib.sha256(
        canonical_json_v2(profile, stored=True)
    ).hexdigest()
    aliases = _alias_index(profile)
    warnings: List[Dict[str, Any]] = []

    recipe_values = closure["_validated"]["recipeValues"]
    sources: Dict[str, _Source] = {}
    wrapper_by_path = {
        wrapper["descriptor"]["path"]: wrapper
        for wrapper in closure["worldPackSources"]
    }
    for path, source_value in sorted(closure["_validated"]["sourceValues"].items()):
        descriptor = wrapper_by_path[path]["descriptor"]
        recipe_descriptor = source_value["projectionRecipe"]
        recipe = recipe_values[recipe_descriptor["path"]][1]
        seed_map = {
            item["channel"]: item["seed"]
            for item in source_value["seedChannels"]
        }
        sources[path] = _Source(
            descriptor=descriptor,
            value=source_value,
            recipe_descriptor=recipe_descriptor,
            recipe=recipe,
            seed_bank=SeedBank(
                seed_map,
                profile["identity"]["namespace"],
                source_value["namespace"],
                profile["seedDerivation"]["channels"],
            ),
        )

    entities: List[_Entity] = []
    entities_by_source_id: Dict[str, _Entity] = {}
    display_ids: Dict[str, str] = {}
    full_digests: Set[str] = set()
    identity_record_attr = profile["identity"]["identityRecordAttribute"]
    stable_input_attr = profile["identity"]["stableIdInputAttribute"]
    for source_path, source in sorted(sources.items()):
        for value in sorted(source.value["entities"], key=lambda item: item["entityId"]):
            attrs = value["attributes"]
            identity_record_id = attrs.get(
                identity_record_attr, min(value["sourceRecordIds"])
            )
            if (
                not isinstance(identity_record_id, str)
                or identity_record_id not in value["sourceRecordIds"]
            ):
                _fail(
                    "STABLE_ID",
                    "identity record must be one of sourceRecordIds",
                    value["entityId"],
                )
            stable_input = attrs.get(stable_input_attr, value["entityId"])
            if not isinstance(stable_input, str) or not stable_input:
                _fail("STABLE_ID", "stable ID input must be a non-empty string", value["entityId"])
            digest = stable_identity_digest(
                profile["identity"]["namespace"],
                value["kind"],
                identity_record_id,
                stable_input,
            )
            if digest in full_digests:
                _fail("STABLE_ID_COLLISION", "duplicate full identity digest", value["entityId"])
            full_digests.add(digest)
            alias = aliases.get(digest)
            display_id = alias or stable_display_id(
                profile["entityKinds"][value["kind"]]["prefix"],
                digest,
                profile["identity"]["displayLength"],
            )
            previous_digest = display_ids.get(display_id)
            if previous_digest is not None and previous_digest != digest:
                _fail(
                    "STABLE_ID_COLLISION",
                    "truncated or aliased display ID collision",
                    display_id,
                )
            display_ids[display_id] = digest
            entity = _Entity(
                source=source,
                value=value,
                entity_id=value["entityId"],
                kind=value["kind"],
                identity_record_id=identity_record_id,
                stable_id_input=stable_input,
                identity_digest=digest,
                display_id=display_id,
                legacy_alias=alias is not None,
                references=[],
                seed_draws=[],
            )
            entities.append(entity)
            entities_by_source_id[entity.entity_id] = entity

    for entity in entities:
        kind_config = profile["entityKinds"][entity.kind]
        relation_counts: Dict[str, int] = {}
        for reference in sorted(
            entity.value["references"],
            key=lambda item: (
                item["relation"],
                item["targetEntityId"],
                item["required"],
            ),
        ):
            relation = reference["relation"]
            target = entities_by_source_id.get(reference["targetEntityId"])
            if target is None:
                if reference["required"]:
                    _fail(
                        "MISSING_REFERENCE",
                        "required reference target is absent",
                        entity.entity_id,
                    )
                warnings.append(
                    {
                        "code": "OPTIONAL_REFERENCE_UNRESOLVED",
                        "relation": relation,
                        "sourceEntityId": entity.entity_id,
                        "targetEntityId": reference["targetEntityId"],
                    }
                )
                continue
            if target.kind not in kind_config["allowedRelations"][relation]:
                _fail(
                    "REFERENCE_KIND",
                    "reference target kind is not allowed",
                    entity.entity_id,
                )
            relation_counts[relation] = relation_counts.get(relation, 0) + 1
            entity.references.append(
                {
                    "relation": relation,
                    "required": reference["required"],
                    "targetEntityId": target.display_id,
                    "targetKind": target.kind,
                }
            )
        for relation in kind_config["requiredRelations"]:
            if relation_counts.get(relation, 0) != 1:
                _fail(
                    "MISSING_REFERENCE",
                    "required relation {!r} must resolve exactly once".format(relation),
                    entity.entity_id,
                )
    if len(warnings) > limits["maxWarnings"]:
        _fail("LIMIT", "optional reference warning count exceeds trusted limit")
    warnings.sort(
        key=lambda item: (
            item["code"],
            item["sourceEntityId"],
            item["relation"],
            item["targetEntityId"],
        )
    )

    worlds = [entity for entity in entities if entity.kind == "world"]
    if not worlds:
        _fail("WORLD", "compiled pack must contain at least one world")
    world_bounds: Dict[str, Dict[str, List[int]]] = {}
    world_rows: List[Dict[str, Any]] = []
    world_configs: Dict[str, Dict[str, Any]] = {}
    stable_world_keys: Set[str] = set()
    for world in sorted(worlds, key=lambda item: item.display_id):
        attrs = world.value["attributes"]
        bounds = _bounds(
            attrs.get("bounds", profile["placementPolicy"]["defaultBounds"]),
            world.entity_id + ".bounds",
        )
        world_bounds[world.display_id] = bounds
        world_key = attrs.get("worldKey", world.display_id)
        if not isinstance(world_key, str) or not _SAFE_ID.fullmatch(world_key):
            _fail("WORLD", "worldKey must be a safe ID", world.entity_id)
        if world_key in stable_world_keys:
            _fail("DUPLICATE_STABLE_KEY", "duplicate world stable key", world.entity_id)
        stable_world_keys.add(world_key)
        spawn = _point(attrs.get("spawn", {"x": 0, "y": 0, "z": 0}), world.entity_id + ".spawn")
        if not (
            bounds["x"][0] <= spawn["x"] <= bounds["x"][1]
            and bounds["z"][0] <= spawn["z"] <= bounds["z"][1]
        ):
            _fail("BOUNDS", "world spawn is outside bounds", world.entity_id)
        summary = _base_row(world)
        summary.update({"bounds": bounds, "stableKey": world_key})
        world_rows.append(summary)
        config = dict(summary)
        config.update(
            {
                "features": copy.deepcopy(attrs.get("features", {})),
                "renderer": copy.deepcopy(
                    attrs.get(
                        "renderer",
                        {
                            "unitsPerSimulationUnit": profile["placementPolicy"][
                                "rendererUnitsPerSimulationUnit"
                            ]
                        },
                    )
                ),
                "schemaVersion": "rappterverse.world-config/v1",
                "spawn": spawn,
            }
        )
        defaults = _safe_defaults(world, profile)
        if defaults:
            config["defaults"] = defaults
        world_configs[world.display_id] = config

    world_objects: Dict[str, List[Dict[str, Any]]] = {
        world.display_id: [] for world in worlds
    }
    world_npcs: Dict[str, List[Dict[str, Any]]] = {
        world.display_id: [] for world in worlds
    }
    top_rows: Dict[str, List[Dict[str, Any]]] = {
        "agent-blueprint": [],
        "quest": [],
        "item": [],
        "currency": [],
        "governance": [],
        "incident": [],
        "lineage": [],
    }
    stable_keys: Set[Tuple[str, str, str]] = set()

    for entity in sorted(entities, key=lambda item: (item.kind, item.display_id)):
        if entity.kind == "world":
            continue
        row = _base_row(entity)
        row["references"] = copy.deepcopy(entity.references)
        defaults = _safe_defaults(entity, profile)
        if defaults:
            row["defaults"] = defaults
        membership = _relation_values(entity, "in-world")
        if entity.kind in ("object", "portal", "npc-blueprint"):
            world_id = membership[0]["targetEntityId"]
            if world_id not in world_bounds:
                _fail("WORLD", "entity membership does not target a world", entity.entity_id)
            row["worldId"] = world_id
            placement = _derived_placement(entity, world_bounds[world_id], profile)
            if entity.kind == "npc-blueprint":
                row["spawn"] = placement
            else:
                row["placement"] = placement
            stable_key = entity.value["attributes"].get("stableKey", entity.display_id)
            if not isinstance(stable_key, str) or not _SAFE_ID.fullmatch(stable_key):
                _fail("DUPLICATE_STABLE_KEY", "invalid stable key", entity.entity_id)
            scoped_key = (entity.kind, world_id, stable_key)
            if scoped_key in stable_keys:
                _fail("DUPLICATE_STABLE_KEY", "duplicate scoped stable key", entity.entity_id)
            stable_keys.add(scoped_key)
            row["stableKey"] = stable_key
            if entity.kind == "portal":
                target = _relation_values(entity, "portal-target")[0]
                row["destinationWorldId"] = target["targetEntityId"]
                world_objects[world_id].append(row)
            elif entity.kind == "object":
                world_objects[world_id].append(row)
            else:
                world_npcs[world_id].append(row)
        elif entity.kind in top_rows:
            if entity.kind == "governance":
                roles = entity.value["attributes"].get("roles")
                row["roles"] = sorted(
                    _unique_strings(
                        roles,
                        entity.entity_id + ".roles",
                        minimum_items=1,
                        maximum_items=1024,
                        maximum_length=128,
                    )
                )
                row["jurisdictionWorldIds"] = sorted(
                    ref["targetEntityId"]
                    for ref in _relation_values(entity, "jurisdiction")
                )
            if entity.kind == "lineage":
                generation = entity.value["attributes"].get("generation")
                row["generation"] = _integer(
                    generation, entity.entity_id + ".generation", minimum=0
                )
            top_rows[entity.kind].append(row)
        else:
            _fail("UNKNOWN_KIND", "entity kind has no output mapping", entity.entity_id)

    quest_graph = {
        entity.display_id: [
            ref["targetEntityId"]
            for ref in _relation_values(entity, "depends-on")
        ]
        for entity in entities
        if entity.kind == "quest"
    }
    _detect_cycle(quest_graph, "QUEST_CYCLE")
    lineage_graph = {
        entity.display_id: [
            ref["targetEntityId"] for ref in _relation_values(entity, "parent")
        ]
        for entity in entities
        if entity.kind == "lineage"
    }
    _detect_cycle(lineage_graph, "LINEAGE_CYCLE")
    lineage_generation = {
        row["id"]: row["generation"] for row in top_rows["lineage"]
    }
    for child, parents in lineage_graph.items():
        for parent in parents:
            if lineage_generation[parent] >= lineage_generation[child]:
                _fail(
                    "LINEAGE_GENERATION",
                    "lineage parent must be from a prior generation",
                    child,
                )

    files: Dict[str, bytes] = {}
    layout = profile["outputLayout"]
    _add_file(
        files,
        layout["worldsIndex"],
        {
            "schemaVersion": "rappterverse.world-index/v1",
            "worlds": world_rows,
        },
        limits,
    )
    for world_id in sorted(world_configs):
        _add_file(
            files,
            layout["worldConfig"].format(worldId=world_id),
            world_configs[world_id],
            limits,
        )
        if world_objects[world_id]:
            _add_file(
                files,
                layout["worldObjects"].format(worldId=world_id),
                {
                    "objects": sorted(
                        world_objects[world_id], key=lambda item: item["id"]
                    ),
                    "schemaVersion": "rappterverse.world-objects/v1",
                    "worldId": world_id,
                },
                limits,
            )
        if world_npcs[world_id]:
            _add_file(
                files,
                layout["worldNpcs"].format(worldId=world_id),
                {
                    "npcs": sorted(
                        world_npcs[world_id], key=lambda item: item["id"]
                    ),
                    "schemaVersion": "rappterverse.world-npcs/v1",
                    "worldId": world_id,
                },
                limits,
            )
    if top_rows["agent-blueprint"]:
        _add_file(
            files,
            layout["agentBlueprints"],
            {
                "agentBlueprints": sorted(
                    top_rows["agent-blueprint"], key=lambda item: item["id"]
                ),
                "schemaVersion": "rappterverse.agent-blueprints/v1",
            },
            limits,
        )
    if top_rows["quest"]:
        _add_file(
            files,
            layout["quests"],
            {
                "quests": sorted(top_rows["quest"], key=lambda item: item["id"]),
                "schemaVersion": "rappterverse.quests/v1",
            },
            limits,
        )
    if top_rows["item"] or top_rows["currency"]:
        _add_file(
            files,
            layout["economy"],
            {
                "currencies": sorted(
                    top_rows["currency"], key=lambda item: item["id"]
                ),
                "items": sorted(top_rows["item"], key=lambda item: item["id"]),
                "schemaVersion": "rappterverse.economy-defaults/v1",
            },
            limits,
        )
    for kind, layout_key, root_key, schema_version in (
        ("governance", "governance", "governance", "rappterverse.governance-defaults/v1"),
        ("incident", "incidents", "incidents", "rappterverse.incident-defaults/v1"),
        ("lineage", "lineages", "lineages", "rappterverse.lineage-defaults/v1"),
    ):
        if top_rows[kind]:
            _add_file(
                files,
                layout[layout_key],
                {
                    root_key: sorted(top_rows[kind], key=lambda item: item["id"]),
                    "schemaVersion": schema_version,
                },
                limits,
            )

    provenance_rows = [
        _provenance_row(
            entity,
            closure,
            profile,
            profile_sha,
            records,
            record_provenance,
        )
        for entity in sorted(entities, key=lambda item: item.display_id)
    ]
    provenance_bytes = b"".join(
        canonical_json_v2(
            row, stored=True, max_bytes=limits["maxOutputFileBytes"]
        )
        for row in provenance_rows
    )
    if len(provenance_bytes) > limits["maxOutputFileBytes"]:
        _fail("LIMIT", "provenance output exceeds trusted file limit")
    provenance_path = layout["provenance"]
    if provenance_path in files:
        _fail("DUPLICATE_PATH", "duplicate provenance output path")
    files[provenance_path] = provenance_bytes

    payload_descriptors = [
        {
            "bytes": len(files[path]),
            "leafSha256": "sha256:" + pack_leaf_hash(path, files[path]),
            "mode": "100644",
            "path": path,
            "sha256": "sha256:" + hashlib.sha256(files[path]).hexdigest(),
        }
        for path in sorted(files)
    ]
    manifest = {
        "canonicalization": CANONICALIZATION_V2,
        "compiler": {
            "implementationSha256": COMPILER_IMPLEMENTATION_SHA256,
            "version": COMPILER_VERSION,
        },
        "packId": "{}--{}".format(
            closure["release"]["releaseId"], profile["profileId"]
        ),
        "payloadFiles": payload_descriptors,
        "profile": {
            "profileId": profile["profileId"],
            "profileSha256": profile_sha,
            "version": profile["version"],
        },
        "release": {
            "dataCommit": closure["dataCommit"],
            "releaseId": closure["release"]["releaseId"],
            "sourceClosureSha256": closure["sourceClosureSha256"],
        },
        "schemaVersion": PACK_VERSION,
    }
    _add_file(files, layout["manifest"], manifest, limits)
    root = pack_tree_root(files)
    report = {
        "compiler": {
            "implementationSha256": COMPILER_IMPLEMENTATION_SHA256,
            "version": COMPILER_VERSION,
        },
        "entityCount": len(entities),
        "fileCount": len(files),
        "packRoot": root,
        "profile": {
            "profileId": profile["profileId"],
            "profileSha256": profile_sha,
            "version": profile["version"],
        },
        "release": {
            "dataCommit": closure["dataCommit"],
            "releaseId": closure["release"]["releaseId"],
            "sourceClosureSha256": closure["sourceClosureSha256"],
        },
        "schemaVersion": "rappterverse.world-pack-build-report/v1",
        "status": "compiled",
        "warnings": warnings,
    }
    canonical_json_v2(report, stored=True)
    return CompilationResult(files=dict(sorted(files.items())), report=report, root=root)
