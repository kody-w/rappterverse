"""Synthetic, deterministic world-pack compiler fixture builder."""

from __future__ import annotations

import base64
import copy
import hashlib
from typing import Any, Callable, Dict, List, Mapping, Optional

from world_pack_compiler import canonical_json_v2, parse_json_v2, source_closure_digest

DATA_COMMIT = "cff8bb0358ce10449ee1d72018a7624009aa3599"
RELEASE_ID = "release-2026-07-12-synthetic-fixture"
DATASET_IDS = (
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
)
CHANNELS = (
    "immutable-layout",
    "frames",
    "engines",
    "visuals",
    "audio",
    "narrative",
    "economy",
    "governance",
)


def _receipt(label: str) -> Dict[str, str]:
    digest = hashlib.sha256(("receipt:" + label).encode("utf-8")).hexdigest()
    return {
        "path": "objects/review-receipts/sha256/{}/{}.json".format(
            digest[:2], digest
        ),
        "sha256": digest,
    }


def _descriptor(
    path: str,
    kind: str,
    media_type: str,
    data: bytes,
    receipt_label: str,
) -> Dict[str, Any]:
    return {
        "artifactKind": kind,
        "bytes": len(data),
        "mediaType": media_type,
        "path": path,
        "reviewReceiptRef": _receipt(receipt_label)["path"],
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def _object_descriptor(
    namespace: str,
    kind: str,
    media_type: str,
    data: bytes,
    extension: str,
    receipt_label: str,
) -> Dict[str, Any]:
    digest = hashlib.sha256(data).hexdigest()
    return _descriptor(
        "objects/{}/sha256/{}/{}.{}".format(
            namespace, digest[:2], digest, extension
        ),
        kind,
        media_type,
        data,
        receipt_label,
    )


def _blob(descriptor: Mapping[str, Any], data: bytes) -> Dict[str, Any]:
    return {
        "bytesBase64": base64.b64encode(data).decode("ascii"),
        "descriptor": dict(descriptor),
    }


def default_record() -> Dict[str, Any]:
    return {
        "datasetId": "d01-civilization-ledger",
        "episodeId": "episode-d01-001",
        "eventTime": "2026-07-12T20:00:00Z",
        "generation": {
            "deliberationId": "deliberation-d01-item-001",
            "generatorCommit": "a" * 40,
            "providerReasoningId": None,
            "runId": "run-d01-fixture",
            "seed": "fixture-seed-d01",
            "transcriptId": "transcript-d01-item-001",
        },
        "governance": {
            "contamination": "public-generated-contamination-risk",
            "license": "CC-BY-4.0",
            "privacy": "synthetic-nonpersonal",
            "qualityPassed": True,
            "safetyReviewPassed": True,
        },
        "payload": {
            "datasetCode": "d01",
            "fixture": True,
            "transition": "synthetic-state-change",
        },
        "provenance": {
            "externalContentIncluded": False,
            "lineageComplete": True,
            "rightsBasis": "synthetic",
            "rightsStatementId": "rights-project-synthetic-v2",
            "sources": [
                {
                    "generatorCommit": "a" * 40,
                    "sourceId": "urn:rappterverse:synthetic:d01-fixture",
                    "sourceType": "deterministic-synthetic",
                }
            ],
        },
        "recordId": "record-d01-item-001",
        "recordType": "synthetic-transition",
        "schemaVersion": "rappterverse.public-record/v2",
        "sequence": 0,
        "split": "train",
    }


def default_world_entity() -> Dict[str, Any]:
    return {
        "attributes": {"dataset": "d01-civilization-ledger"},
        "description": "A tiny world used only by compiler tests.",
        "entityId": "source:world:synthetic-fixture",
        "immutableBase": True,
        "kind": "world",
        "name": "Synthetic Fixture World",
        "preservedOverlayFields": ["position", "status"],
        "references": [],
        "sourceRecordIds": ["record-d01-item-001"],
        "tags": ["fixture", "synthetic"],
    }


def _dataset_release(dataset_id: str, index: int) -> Dict[str, Any]:
    digest = hashlib.sha256(("dataset:" + dataset_id).encode("utf-8")).hexdigest()
    receipt = _receipt("dataset-group-{}".format(index // 4))
    return {
        "contentBytes": 1,
        "counts": {
            "deliberations": 1,
            "providerReasoning": 0,
            "records": 1,
            "transcripts": 1,
        },
        "datasetId": dataset_id,
        "datasetVersion": "v2.0.0",
        "manifest": {
            "artifactKind": "dataset-manifest",
            "bytes": 1,
            "mediaType": "application/json",
            "path": "releases/{}/datasets/{}.json".format(
                RELEASE_ID, dataset_id
            ),
            "reviewReceiptRef": receipt["path"],
            "sha256": digest,
        },
    }


def _all_receipts(closure: Mapping[str, Any]) -> List[Dict[str, str]]:
    paths = {
        closure["release"]["manifest"]["descriptor"]["reviewReceiptRef"],
        *[
            item["descriptor"]["reviewReceiptRef"]
            for key in ("recordArtifacts", "worldPackSources", "projectionRecipes")
            for item in closure[key]
        ],
    }
    release = parse_json_v2(
        base64.b64decode(closure["release"]["manifest"]["bytesBase64"])
    )
    paths.update(
        item["manifest"]["reviewReceiptRef"] for item in release["datasets"]
    )
    paths.update(
        item["reviewReceiptRef"] for item in release["worldPackSources"]
    )
    return [
        {"path": path, "sha256": path.rsplit("/", 1)[-1][:-5]}
        for path in sorted(paths)
    ]


def make_closure(
    entities: Optional[List[Dict[str, Any]]] = None,
    *,
    source_namespace: str = "rappterverse/synthetic-fixture",
    channel_seeds: Optional[Mapping[str, str]] = None,
) -> Dict[str, Any]:
    record_bytes = canonical_json_v2(default_record(), stored=True)
    record_descriptor = _object_descriptor(
        "records",
        "record-shard",
        "application/x-ndjson",
        record_bytes,
        "jsonl",
        "records",
    )
    recipe = {
        "configuration": {"fixture": True},
        "deterministic": True,
        "engine": "rappterverse-world-pack-projection/v1",
        "recipeId": "recipe-d01-fixture",
        "schemaVersion": "rappterverse.projection-recipe/v2",
        "version": "v1",
    }
    recipe_bytes = canonical_json_v2(recipe, stored=True)
    recipe_descriptor = _object_descriptor(
        "projection-recipes",
        "projection-recipe",
        "application/json",
        recipe_bytes,
        "json",
        "recipe",
    )
    seeds = channel_seeds or {
        channel: "fixture-{}-seed".format(channel) for channel in CHANNELS
    }
    source = {
        "canonicalization": "rappterverse-canonical-json/v2",
        "entities": copy.deepcopy(
            entities if entities is not None else [default_world_entity()]
        ),
        "namespace": source_namespace,
        "projectionRecipe": dict(recipe_descriptor),
        "releaseId": RELEASE_ID,
        "schemaVersion": "rappterverse.world-pack-source/v2",
        "seedChannels": [
            {"channel": channel, "seed": seeds[channel]} for channel in CHANNELS
        ],
        "sortedByStableKey": True,
        "worldPackSourceId": "world-pack-source-synthetic-fixture",
    }
    source_bytes = canonical_json_v2(source, stored=True)
    source_descriptor = _object_descriptor(
        "world-pack-sources",
        "world-pack-source",
        "application/json",
        source_bytes,
        "json",
        "source",
    )
    release = {
        "createdAt": "2026-07-12T20:00:00Z",
        "datasets": [
            _dataset_release(dataset_id, index)
            for index, dataset_id in enumerate(DATASET_IDS)
        ],
        "policy": {
            "path": "policies/publication-trust-v2.json",
            "policyId": "rappterverse-publication-trust",
            "policyVersion": "2.0.0",
            "sha256": "c" * 64,
        },
        "previousReleaseId": None,
        "previousReleasePointer": None,
        "releaseId": RELEASE_ID,
        "schemaVersion": "rappterverse.release-manifest/v2",
        "sequence": 1,
        "totals": {
            "contentBytes": 10,
            "datasets": 10,
            "deliberations": 10,
            "providerReasoning": 0,
            "records": 10,
            "transcripts": 10,
            "worldPackSources": 1,
        },
        "worldPackSources": [dict(source_descriptor)],
    }
    release_bytes = canonical_json_v2(release, stored=True)
    release_descriptor = _descriptor(
        "releases/{}/manifest.json".format(RELEASE_ID),
        "release-manifest",
        "application/json",
        release_bytes,
        "release",
    )
    review_set_digest = hashlib.sha256(b"active-review-set").hexdigest()
    closure: Dict[str, Any] = {
        "dataCommit": DATA_COMMIT,
        "projectionRecipes": [_blob(recipe_descriptor, recipe_bytes)],
        "publicContract": {
            "canonicalization": "rappterverse-canonical-json/v2",
            "commit": DATA_COMMIT,
            "repository": "kody-w/rappterverse-data",
        },
        "publicRepository": {
            "name": "kody-w/rappterverse-data",
            "repositoryId": 1298777302,
        },
        "recordArtifacts": [_blob(record_descriptor, record_bytes)],
        "records": [
            {
                "artifactPath": record_descriptor["path"],
                "lineIndex": 0,
                "lineSha256": hashlib.sha256(record_bytes).hexdigest(),
                "recordId": "record-d01-item-001",
            }
        ],
        "release": {
            "manifest": _blob(release_descriptor, release_bytes),
            "releaseId": RELEASE_ID,
        },
        "schemaVersion": "rappterverse.verified-world-source-closure/v1",
        "verificationProof": {
            "activeReviewSet": {
                "path": "objects/active-review-sets/sha256/{}/{}.json".format(
                    review_set_digest[:2], review_set_digest
                ),
                "sha256": review_set_digest,
            },
            "reviewReceipts": [],
            "verifier": "rappterverse-universe-source-verifier/v1",
        },
        "verified": True,
        "worldPackSources": [_blob(source_descriptor, source_bytes)],
    }
    closure["verificationProof"]["reviewReceipts"] = _all_receipts(closure)
    closure["sourceClosureSha256"] = source_closure_digest(closure)
    return closure


def source_document(closure: Mapping[str, Any]) -> Dict[str, Any]:
    return parse_json_v2(
        base64.b64decode(closure["worldPackSources"][0]["bytesBase64"])
    )


def rebuild_source(
    closure: Mapping[str, Any],
    mutate: Callable[[Dict[str, Any]], None],
) -> Dict[str, Any]:
    result = copy.deepcopy(closure)
    source = source_document(result)
    mutate(source)
    source_bytes = canonical_json_v2(source, stored=True)
    old_source_descriptor = result["worldPackSources"][0]["descriptor"]
    source_descriptor = _object_descriptor(
        "world-pack-sources",
        "world-pack-source",
        "application/json",
        source_bytes,
        "json",
        "source",
    )
    source_descriptor["reviewReceiptRef"] = old_source_descriptor[
        "reviewReceiptRef"
    ]
    result["worldPackSources"] = [_blob(source_descriptor, source_bytes)]
    release = parse_json_v2(
        base64.b64decode(result["release"]["manifest"]["bytesBase64"])
    )
    release["worldPackSources"] = [dict(source_descriptor)]
    release_bytes = canonical_json_v2(release, stored=True)
    old_release_descriptor = result["release"]["manifest"]["descriptor"]
    release_descriptor = _descriptor(
        old_release_descriptor["path"],
        "release-manifest",
        "application/json",
        release_bytes,
        "release",
    )
    release_descriptor["reviewReceiptRef"] = old_release_descriptor[
        "reviewReceiptRef"
    ]
    result["release"]["manifest"] = _blob(release_descriptor, release_bytes)
    result["verificationProof"]["reviewReceipts"] = _all_receipts(result)
    result.pop("sourceClosureSha256", None)
    result["sourceClosureSha256"] = source_closure_digest(result)
    return result


def resign_closure(closure: Mapping[str, Any]) -> Dict[str, Any]:
    result = copy.deepcopy(closure)
    result.pop("sourceClosureSha256", None)
    result["sourceClosureSha256"] = source_closure_digest(result)
    return result


def rewrite_release_id(
    closure: Mapping[str, Any], release_id: str
) -> Dict[str, Any]:
    result = copy.deepcopy(closure)
    old_release_id = result["release"]["releaseId"]
    source = source_document(result)
    source["releaseId"] = release_id
    source_bytes = canonical_json_v2(source, stored=True)
    old_source_descriptor = result["worldPackSources"][0]["descriptor"]
    source_descriptor = _object_descriptor(
        "world-pack-sources",
        "world-pack-source",
        "application/json",
        source_bytes,
        "json",
        "source",
    )
    source_descriptor["reviewReceiptRef"] = old_source_descriptor[
        "reviewReceiptRef"
    ]
    result["worldPackSources"] = [_blob(source_descriptor, source_bytes)]

    release = parse_json_v2(
        base64.b64decode(result["release"]["manifest"]["bytesBase64"])
    )
    release["releaseId"] = release_id
    release["worldPackSources"] = [dict(source_descriptor)]
    for dataset in release["datasets"]:
        dataset["manifest"]["path"] = dataset["manifest"]["path"].replace(
            old_release_id, release_id
        )
    release_bytes = canonical_json_v2(release, stored=True)
    old_release_descriptor = result["release"]["manifest"]["descriptor"]
    release_descriptor = _descriptor(
        "releases/{}/manifest.json".format(release_id),
        "release-manifest",
        "application/json",
        release_bytes,
        "release",
    )
    release_descriptor["reviewReceiptRef"] = old_release_descriptor[
        "reviewReceiptRef"
    ]
    result["release"] = {
        "manifest": _blob(release_descriptor, release_bytes),
        "releaseId": release_id,
    }
    result["verificationProof"]["reviewReceipts"] = _all_receipts(result)
    return resign_closure(result)
