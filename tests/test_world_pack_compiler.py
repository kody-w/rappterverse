"""Focused deterministic world-pack compiler and legacy parity tests."""

from __future__ import annotations

import base64
import builtins
import copy
import hashlib
import hmac
import json
import os
import random
import re
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
if str(Path(__file__).parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).parent))

from world_pack_compiler import (  # noqa: E402
    COMPILER_IMPLEMENTATION_SHA256,
    COMPILER_SOURCE_FILES,
    CanonicalJSONV2DepthError,
    CanonicalJSONV2Error,
    CompilationError,
    LegacyCompilationError,
    SeedBank,
    canonical_json_v2,
    compile_legacy_v1,
    compile_world_pack,
    load_trusted_profile,
    pack_leaf_hash,
    pack_tree_root,
    parse_json_v2,
    source_closure_digest,
    stable_display_id,
    stable_identity_digest,
    validate_verified_closure,
)
from world_pack_compiler.canonical import (  # noqa: E402
    MAX_INTEGER_DECIMAL_DIGITS,
)
from world_pack_compiler.core import (  # noqa: E402
    _detect_cycle,
    _record_artifact_descriptor,
    _safe_path,
)
from world_pack_compiler.crypto import (  # noqa: E402
    CryptoError,
    implementation_digest,
)
from world_pack_compiler.legacy import (  # noqa: E402
    _catalog_defaults,
    _compile_legacy_v1_for_test,
    _extract_js_literal,
)
import world_pack_compiler.legacy as legacy_module  # noqa: E402
import compile_world_pack as compiler_cli  # noqa: E402
from world_pack_compiler.trust import (  # noqa: E402
    LEGACY_LOCK_RAW_SHA256,
    LEGACY_MAIN_COMMIT,
    LEGACY_MAIN_TREE,
    LEGACY_REQUIRED_SOURCE_DESCRIPTORS,
    TRUSTED_PROFILE_PATH,
    TRUSTED_PROFILE_RAW_SHA256,
)
from legacy_semantic_fixture import (  # noqa: E402
    LEGACY_PACK_ROOT,
    LEGACY_SEMANTIC_GOLDEN,
    build_actual_domains,
    build_expected_domains,
    semantic_summary,
)
from world_pack_fixture import (  # noqa: E402
    CHANNELS,
    _all_receipts,
    _blob,
    _descriptor,
    _object_descriptor,
    default_world_entity,
    make_closure,
    rebuild_source,
    resign_closure,
    rewrite_release_id,
    source_document,
)


def _entity(
    entity_id,
    kind,
    *,
    attributes=None,
    references=None,
    name=None,
    preserved=None,
):
    return {
        "attributes": attributes or {},
        "description": "{} fixture".format(kind),
        "entityId": entity_id,
        "immutableBase": True,
        "kind": kind,
        "name": name or entity_id.rsplit(":", 1)[-1],
        "preservedOverlayFields": preserved or [],
        "references": references or [],
        "sourceRecordIds": ["record-d01-item-001"],
        "tags": ["fixture"],
    }


def _ref(relation, target, required=True):
    return {
        "relation": relation,
        "required": required,
        "targetEntityId": target,
    }


def _decode_json(data):
    return parse_json_v2(data, require_stored=True)


class CanonicalJSONV2Tests(unittest.TestCase):
    def test_public_golden_vectors(self):
        vectors = (
            (
                {"z": ["Cafe\u0301", {"beta": False, "alpha": 7}], "a": None},
                '{"a":null,"z":["Café",{"alpha":7,"beta":false}]}',
            ),
            ({"é": "composed", "A": 1}, '{"A":1,"é":"composed"}'),
        )
        for value, expected in vectors:
            with self.subTest(expected=expected):
                self.assertEqual(expected.encode(), canonical_json_v2(value))
                self.assertEqual(
                    expected.encode() + b"\n",
                    canonical_json_v2(value, stored=True),
                )

    def test_rejects_duplicates_nonfinite_floats_utf8_bom_and_collisions(self):
        invalid = (
            b'{"a":1,"a":2}',
            b'{"a":NaN}',
            b'{"a":Infinity}',
            b'{"a":1.5}',
            b"\xff",
            b'\xef\xbb\xbf{"a":1}',
            '{"é":1,"e\u0301":2}',
        )
        for value in invalid:
            with self.subTest(value=value):
                with self.assertRaises(CanonicalJSONV2Error):
                    parse_json_v2(value)
        with self.assertRaises(CanonicalJSONV2Error):
            canonical_json_v2({"nested": [1.0]})

    def test_nesting_and_size_are_bounded(self):
        value = 0
        for _ in range(64):
            value = [value]
        self.assertEqual(value, parse_json_v2(canonical_json_v2(value)))
        value = [value]
        with self.assertRaises(CanonicalJSONV2DepthError):
            canonical_json_v2(value)
        with self.assertRaises(CanonicalJSONV2Error):
            canonical_json_v2({"large": "x" * 100}, max_bytes=50)

    def test_stored_form_requires_exact_terminal_lf(self):
        self.assertEqual(
            {"a": 1}, parse_json_v2(b'{"a":1}\n', require_stored=True)
        )
        for data in (b'{"a":1}', b'{ "a":1 }\n', b'{"a":1}\n\n'):
            with self.subTest(data=data):
                with self.assertRaises(CanonicalJSONV2Error):
                    parse_json_v2(data, require_stored=True)

    def test_integer_parsing_ignores_python_process_digit_limit(self):
        token = b"1" + (b"0" * 4_499)
        stored = token + b"\n"
        setter = getattr(sys, "set_int_max_str_digits", None)
        getter = getattr(sys, "get_int_max_str_digits", None)
        original = getter() if getter is not None else None
        settings = (None,) if setter is None else (640, 0)
        try:
            for setting in settings:
                with self.subTest(process_limit=setting):
                    if setter is not None:
                        setter(setting)
                    parsed = parse_json_v2(stored, require_stored=True)
                    self.assertGreater(parsed.bit_length(), 14_000)
                    self.assertEqual(stored, canonical_json_v2(parsed, stored=True))
        finally:
            if setter is not None and original is not None:
                setter(original)

        over_digit_bound = b"1" + (b"0" * MAX_INTEGER_DECIMAL_DIGITS)
        over_bit_bound = b"9" * MAX_INTEGER_DECIMAL_DIGITS
        for invalid in (over_digit_bound, over_bit_bound):
            with self.subTest(length=len(invalid)):
                with self.assertRaises(CanonicalJSONV2Error):
                    parse_json_v2(invalid)


class StableIdentityAndSeedTests(unittest.TestCase):
    def test_stable_id_golden(self):
        digest = stable_identity_digest(
            "rappterverse/world-pack/v1",
            "world",
            "record-d01-item-001",
            "source:world:synthetic-fixture",
        )
        self.assertEqual(
            "ae40e0a4df5ec0568cff77193d6f749a"
            "769c188a21f0f5c6abd1e88bafd09d77",
            digest,
        )
        self.assertEqual(
            "world-vzaobjg7l3afndh7o4mt233utj",
            stable_display_id("world", digest, 26),
        )

    def test_seed_golden_and_channel_isolation(self):
        seeds = {channel: "fixture-" + channel for channel in CHANNELS}
        first = SeedBank(
            seeds,
            "rappterverse/world-pack/v1",
            "rappterverse/test",
            CHANNELS,
        )
        self.assertEqual(
            "3d33b3378ac2dba0d84f5431855cd17c"
            "8644b204c444b8455fbbfff1ddbf9c95",
            first.draw("visuals", "entity-1", "color", 0).hex(),
        )
        self.assertEqual(
            25,
            first.bounded_int(
                "immutable-layout", "entity-1", "x", 0, 31
            ),
        )
        changed = dict(seeds)
        changed["audio"] = "changed-only-audio"
        second = SeedBank(
            changed,
            "rappterverse/world-pack/v1",
            "rappterverse/test",
            CHANNELS,
        )
        for channel in CHANNELS:
            with self.subTest(channel=channel):
                same = first.draw(channel, "entity-1", "purpose", 3)
                other = second.draw(channel, "entity-1", "purpose", 3)
                self.assertEqual(channel != "audio", same == other)

    def test_draws_are_counter_addressed_not_global(self):
        seeds = {channel: channel for channel in CHANNELS}
        bank = SeedBank(
            seeds,
            "rappterverse/world-pack/v1",
            "rappterverse/test",
            CHANNELS,
        )
        expected = bank.draw("frames", "entity", "later", 9)
        for index in range(100):
            bank.draw("visuals", "unrelated", "extra", index)
        self.assertEqual(expected, bank.draw("frames", "entity", "later", 9))

    def test_rejection_sampler_range_fails_before_any_hmac_draw(self):
        bank = SeedBank(
            {channel: channel for channel in CHANNELS},
            "rappterverse/world-pack/v1",
            "rappterverse/test",
            CHANNELS,
        )
        with mock.patch(
            "world_pack_compiler.crypto.hmac.new", wraps=hmac.new
        ) as hmac_new:
            for width in (0, -1, (1 << 256) + 1):
                with self.subTest(width=width):
                    with self.assertRaises(CryptoError):
                        bank.bounded_int(
                            "frames", "entity", "oversized", 0, width
                        )
            self.assertEqual(0, hmac_new.call_count)
        with mock.patch(
            "world_pack_compiler.crypto.hmac.new", wraps=hmac.new
        ) as hmac_new:
            bank.bounded_int(
                "frames", "entity", "full-width", 0, 1 << 256
            )
            self.assertEqual(1, hmac_new.call_count)
        with mock.patch.object(
            bank, "draw", return_value=b"\xff" * 32
        ) as draw:
            with self.assertRaisesRegex(
                CryptoError, "deterministic limit"
            ):
                bank.bounded_int(
                    "frames",
                    "entity",
                    "forced-rejection",
                    0,
                    (1 << 255) + 1,
                )
            self.assertEqual(256, draw.call_count)

    def test_immutable_layout_ignores_release_content(self):
        first = compile_world_pack(make_closure(), load_trusted_profile())
        changed = make_closure()
        changed["dataCommit"] = "b" * 40
        changed = resign_closure(changed)
        second = compile_world_pack(changed, load_trusted_profile())
        first_world = _decode_json(first.files["worlds.json"])["worlds"][0]
        second_world = _decode_json(second.files["worlds.json"])["worlds"][0]
        self.assertEqual(first_world["id"], second_world["id"])
        self.assertEqual(
            first_world["identitySha256"], second_world["identitySha256"]
        )


class PackDigestTests(unittest.TestCase):
    @staticmethod
    def independent_root(files):
        def frame(value):
            return len(value).to_bytes(8, "big") + value

        leaves = []
        for path in sorted(files):
            path_bytes = path.encode()
            leaf = hashlib.sha256(
                b"rappterverse-world-pack-leaf/v1\0"
                + frame(path_bytes)
                + frame(b"100644")
                + frame(files[path])
            ).digest()
            leaves.append(frame(path_bytes) + leaf)
        body = (
            b"rappterverse-world-pack-tree/v1\0"
            + len(leaves).to_bytes(8, "big")
            + b"".join(leaves)
        )
        return "sha256:" + hashlib.sha256(body).hexdigest()

    def test_leaf_and_tree_golden_with_independent_implementation(self):
        files = {"a.json": b"{}\n", "z.json": b"[]\n"}
        self.assertEqual(
            "a5e0391bc67b131aa56b0a23c0e378cd"
            "3c08e8eeeef40b997b5e0c0e37d36c55",
            pack_leaf_hash("a.json", b"{}\n"),
        )
        expected = (
            "sha256:8520b2d7d906d9c2a0afe1bf020ae90f"
            "e4a62df6014d07f7713c7b09500456b3"
        )
        self.assertEqual(expected, pack_tree_root(files))
        self.assertEqual(expected, self.independent_root(files))

    def test_manifest_excludes_outer_root_and_lists_payload_only(self):
        result = compile_world_pack(make_closure(), load_trusted_profile())
        manifest = _decode_json(result.files["pack-manifest.json"])
        self.assertNotIn("packRoot", manifest)
        listed = [item["path"] for item in manifest["payloadFiles"]]
        self.assertNotIn("pack-manifest.json", listed)
        self.assertEqual(
            sorted(set(result.files) - {"pack-manifest.json"}), listed
        )
        self.assertEqual(result.root, self.independent_root(result.files))

    def test_output_tamper_changes_root(self):
        result = compile_world_pack(make_closure(), load_trusted_profile())
        tampered = dict(result.files)
        target = next(path for path in tampered if path != "pack-manifest.json")
        tampered[target] += b" "
        self.assertNotEqual(result.root, pack_tree_root(tampered))

    def test_result_files_cannot_diverge_from_root_or_report(self):
        results = (
            ("normal", compile_world_pack(make_closure(), load_trusted_profile())),
            ("legacy", compile_legacy_v1()),
        )
        for label, result in results:
            with self.subTest(result=label):
                path = next(iter(result.files))
                original = result.files[path]
                with self.assertRaises(TypeError):
                    result.files[path] = original + b"tampered"
                self.assertEqual(original, result.files[path])
                recomputed = pack_tree_root(result.files)
                self.assertEqual(result.root, recomputed)
                self.assertEqual(result.report["packRoot"], recomputed)


class ClosureAndProjectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.profile = load_trusted_profile()

    def test_fixture_compiles_only_immutable_defaults(self):
        result = compile_world_pack(make_closure(), self.profile)
        self.assertEqual(1, result.report["entityCount"])
        self.assertEqual(
            {
                "pack-manifest.json",
                "provenance.jsonl",
                "worlds.json",
                next(
                    path
                    for path in result.files
                    if path.startswith("worlds/") and path.endswith("/config.json")
                ),
            },
            set(result.files),
        )
        provenance = parse_json_v2(
            result.files["provenance.jsonl"], require_stored=True
        )
        self.assertEqual(
            COMPILER_IMPLEMENTATION_SHA256,
            provenance["compiler"]["implementationSha256"],
        )
        self.assertEqual(
            make_closure()["sourceClosureSha256"],
            result.report["release"]["sourceClosureSha256"],
        )
        validated = validate_verified_closure(make_closure(), self.profile)
        self.assertNotIn("_validated", validated)
        self.assertEqual(
            set(make_closure()),
            set(validated),
        )

    def test_verified_marker_is_insufficient_and_tamper_fails(self):
        closure = make_closure()
        closure["verified"] = False
        closure = resign_closure(closure)
        with self.assertRaisesRegex(CompilationError, "verified must be true"):
            compile_world_pack(closure, self.profile)
        closure = make_closure()
        closure["dataCommit"] = "b" * 40
        with self.assertRaisesRegex(CompilationError, "source closure digest"):
            compile_world_pack(closure, self.profile)

    def test_blob_digest_size_path_and_canonical_form_fail_closed(self):
        mutations = []
        value = make_closure()
        value["worldPackSources"][0]["descriptor"]["bytes"] += 1
        mutations.append(value)
        value = make_closure()
        value["projectionRecipes"][0]["descriptor"]["path"] = "../recipe.json"
        mutations.append(value)
        value = make_closure()
        raw = base64.b64decode(
            value["projectionRecipes"][0]["bytesBase64"]
        ).rstrip() + b" \n"
        value["projectionRecipes"][0]["bytesBase64"] = base64.b64encode(
            raw
        ).decode()
        value["projectionRecipes"][0]["descriptor"]["bytes"] = len(raw)
        value["projectionRecipes"][0]["descriptor"]["sha256"] = hashlib.sha256(
            raw
        ).hexdigest()
        mutations.append(value)
        for closure in mutations:
            closure = resign_closure(closure)
            with self.subTest(index=mutations.index(closure) if closure in mutations else -1):
                with self.assertRaises((CompilationError, CanonicalJSONV2Error)):
                    compile_world_pack(closure, self.profile)

    def test_record_artifact_descriptor_paths_reject_duplicates_and_conflicts(self):
        duplicate = make_closure()
        duplicate["recordArtifacts"].append(
            copy.deepcopy(duplicate["recordArtifacts"][0])
        )
        duplicate = resign_closure(duplicate)
        with self.assertRaisesRegex(
            CompilationError, "duplicate record artifact descriptor path"
        ):
            compile_world_pack(duplicate, self.profile)

        conflicting = make_closure()
        first = conflicting["recordArtifacts"][0]
        data = base64.b64decode(first["bytesBase64"])
        descriptor = _descriptor(
            first["descriptor"]["path"],
            "record-shard",
            "application/x-ndjson",
            data,
            "records-conflicting",
        )
        conflicting["recordArtifacts"].append(_blob(descriptor, data))
        conflicting["verificationProof"]["reviewReceipts"] = _all_receipts(
            conflicting
        )
        conflicting = resign_closure(conflicting)
        with self.assertRaisesRegex(
            CompilationError, "conflicting record artifact descriptor path"
        ):
            compile_world_pack(conflicting, self.profile)

    def test_record_provenance_lookup_is_linear_at_scale_without_timing(self):
        class CountingIndex(dict):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.lookups = 0
                self.iterations = 0

            def __getitem__(self, key):
                self.lookups += 1
                return super().__getitem__(key)

            def __iter__(self):
                self.iterations += 1
                return super().__iter__()

            def items(self):
                self.iterations += 1
                return super().items()

            def values(self):
                self.iterations += 1
                return super().values()

        artifact_count = 4_096
        record_count = 40_000
        self.assertEqual(
            artifact_count, self.profile["limits"]["maxRecordArtifacts"]
        )
        self.assertGreaterEqual(
            self.profile["limits"]["maxRecords"], record_count
        )
        paths = [
            "records/shard-{:04d}.jsonl".format(index)
            for index in range(artifact_count)
        ]
        index = CountingIndex(
            (path, {"path": path}) for path in paths
        )
        for ordinal in range(record_count):
            descriptor = _record_artifact_descriptor(
                index, paths[ordinal % artifact_count], "$.records"
            )
            self.assertEqual(
                paths[ordinal % artifact_count], descriptor["path"]
            )
        self.assertEqual(record_count, index.lookups)
        self.assertEqual(0, index.iterations)

    def test_record_artifact_limit_still_rejects_4097_wrappers(self):
        closure = make_closure()
        wrapper = closure["recordArtifacts"][0]
        closure["recordArtifacts"] = [
            copy.deepcopy(wrapper) for _ in range(4_097)
        ]
        closure = resign_closure(closure)
        with self.assertRaisesRegex(
            CompilationError, "too many record artifacts"
        ):
            compile_world_pack(closure, self.profile)

    def test_unknown_kind_attribute_and_nested_protected_field_fail(self):
        cases = (
            lambda source: source["entities"][0].update({"kind": "unknown"}),
            lambda source: source["entities"][0]["attributes"].update(
                {"mystery": True}
            ),
            lambda source: source["entities"][0]["attributes"].update(
                {"properties": {"memory": {"secret": "mutable"}}}
            ),
        )
        expected = ("UNKNOWN_KIND", "UNKNOWN_ATTRIBUTE", "PROTECTED_OVERLAY_FIELD")
        for mutate, code in zip(cases, expected):
            with self.subTest(code=code):
                closure = rebuild_source(make_closure(), mutate)
                with self.assertRaises(CompilationError) as caught:
                    compile_world_pack(closure, self.profile)
                self.assertEqual(code, caught.exception.code)

    def test_required_and_optional_unresolved_references(self):
        world = default_world_entity()
        missing_object = _entity(
            "source:object:missing-world",
            "object",
            references=[
                _ref("in-world", "source:world:not-present", True)
            ],
        )
        with self.assertRaisesRegex(CompilationError, "required reference"):
            compile_world_pack(
                make_closure([world, missing_object]), self.profile
            )
        agent = _entity(
            "source:agent-blueprint:optional-home",
            "agent-blueprint",
            references=[
                _ref("home-world", "source:world:not-present", False)
            ],
        )
        result = compile_world_pack(make_closure([world, agent]), self.profile)
        self.assertEqual(
            ["OPTIONAL_REFERENCE_UNRESOLVED"],
            [warning["code"] for warning in result.report["warnings"]],
        )

    def test_bounds_portals_and_duplicate_stable_keys(self):
        world = default_world_entity()
        outside = _entity(
            "source:object:outside",
            "object",
            attributes={
                "placement": {"x": 100, "y": 0, "z": 0},
                "stableKey": "outside",
            },
            references=[_ref("in-world", world["entityId"])],
        )
        with self.assertRaisesRegex(CompilationError, "outside its world"):
            compile_world_pack(make_closure([world, outside]), self.profile)
        first = _entity(
            "source:object:first",
            "object",
            attributes={"stableKey": "same"},
            references=[_ref("in-world", world["entityId"])],
        )
        second = _entity(
            "source:object:second",
            "object",
            attributes={"stableKey": "same"},
            references=[_ref("in-world", world["entityId"])],
        )
        with self.assertRaisesRegex(CompilationError, "duplicate scoped"):
            compile_world_pack(
                make_closure([world, first, second]), self.profile
            )
        portal = _entity(
            "source:portal:valid",
            "portal",
            references=[
                _ref("in-world", world["entityId"]),
                _ref("portal-target", world["entityId"]),
            ],
        )
        result = compile_world_pack(
            make_closure([world, portal]), self.profile
        )
        objects_path = next(path for path in result.files if path.endswith("/objects.json"))
        row = _decode_json(result.files[objects_path])["objects"][0]
        self.assertEqual(row["worldId"], row["destinationWorldId"])

    def test_quest_cycle_and_typed_item_currency_references(self):
        world = default_world_entity()
        first = _entity(
            "source:quest:first",
            "quest",
            references=[_ref("depends-on", "source:quest:second")],
        )
        second = _entity(
            "source:quest:second",
            "quest",
            references=[_ref("depends-on", "source:quest:first")],
        )
        with self.assertRaisesRegex(CompilationError, "cycle"):
            compile_world_pack(
                make_closure([world, first, second]), self.profile
            )
        item = _entity("source:item:key", "item")
        currency = _entity("source:currency:rapp", "currency")
        quest = _entity(
            "source:quest:typed",
            "quest",
            references=[
                _ref("reward-item", item["entityId"]),
                _ref("reward-currency", currency["entityId"]),
            ],
        )
        result = compile_world_pack(
            make_closure([world, item, currency, quest]), self.profile
        )
        economy = _decode_json(result.files["economy.json"])
        self.assertEqual(1, len(economy["items"]))
        self.assertEqual(1, len(economy["currencies"]))

    def test_governance_incident_and_lineage_validation(self):
        world = default_world_entity()
        governance = _entity(
            "source:governance:council",
            "governance",
            attributes={"roles": ["member", "steward"]},
            references=[_ref("jurisdiction", world["entityId"])],
        )
        incident = _entity(
            "source:incident:recovery",
            "incident",
            references=[_ref("recovery-target", world["entityId"])],
        )
        parent = _entity(
            "source:lineage:parent",
            "lineage",
            attributes={"generation": 0},
        )
        child = _entity(
            "source:lineage:child",
            "lineage",
            attributes={"generation": 1},
            references=[_ref("parent", parent["entityId"])],
        )
        result = compile_world_pack(
            make_closure([world, governance, incident, parent, child]),
            self.profile,
        )
        self.assertIn("governance.json", result.files)
        self.assertIn("incidents.json", result.files)
        self.assertIn("lineages.json", result.files)
        bad_governance = copy.deepcopy(governance)
        bad_governance["attributes"]["roles"] = []
        with self.assertRaisesRegex(CompilationError, "roles"):
            compile_world_pack(
                make_closure([world, bad_governance]), self.profile
            )
        missing_recovery = copy.deepcopy(incident)
        missing_recovery["references"] = []
        with self.assertRaisesRegex(CompilationError, "required relation"):
            compile_world_pack(
                make_closure([world, missing_recovery]), self.profile
            )
        bad_child = copy.deepcopy(child)
        bad_child["attributes"]["generation"] = 0
        with self.assertRaisesRegex(CompilationError, "prior generation"):
            compile_world_pack(
                make_closure([world, parent, bad_child]), self.profile
            )

    def test_truncated_and_full_identity_collisions_fail_without_suffixes(self):
        entities = []
        for index in range(40):
            entity = default_world_entity()
            entity["entityId"] = "source:world:collision-{:03d}".format(index)
            entity["name"] = "Collision {}".format(index)
            entities.append(entity)
        profile = copy.deepcopy(self.profile)
        profile["identity"]["displayLength"] = 1
        with self.assertRaisesRegex(CompilationError, "display ID collision"):
            compile_world_pack(make_closure(entities), profile)
        first = default_world_entity()
        second = default_world_entity()
        second["entityId"] = "source:world:second"
        first["attributes"]["stableIdInput"] = "same"
        second["attributes"]["stableIdInput"] = "same"
        with self.assertRaisesRegex(CompilationError, "full identity digest"):
            compile_world_pack(make_closure([first, second]), self.profile)

    def test_profile_and_source_mutation_are_bound(self):
        first = compile_world_pack(make_closure(), self.profile)
        profile = copy.deepcopy(self.profile)
        profile["identity"]["namespace"] += "/changed"
        second = compile_world_pack(make_closure(), profile)
        self.assertNotEqual(
            first.report["profile"]["profileSha256"],
            second.report["profile"]["profileSha256"],
        )
        self.assertNotEqual(first.root, second.root)
        self.assertNotIn("profileSha256", self.profile)
        bad = copy.deepcopy(self.profile)
        bad["profileSha256"] = "sha256:" + "0" * 64
        with self.assertRaisesRegex(CompilationError, "unknown fields"):
            compile_world_pack(make_closure(), bad)

    def test_profile_semantics_use_the_same_nfc_value_that_is_hashed(self):
        composed = copy.deepcopy(self.profile)
        composed["identity"]["namespace"] += "/café"
        decomposed = copy.deepcopy(self.profile)
        decomposed["identity"]["namespace"] += "/cafe\u0301"
        first = compile_world_pack(make_closure(), composed)
        second = compile_world_pack(make_closure(), decomposed)
        self.assertEqual(
            first.report["profile"]["profileSha256"],
            second.report["profile"]["profileSha256"],
        )
        self.assertEqual(first.files, second.files)
        self.assertEqual(first.root, second.root)

    def test_release_id_contract_rejects_bad_patterns_and_dates(self):
        invalid_ids = (
            "bad",
            "release-2026-7-12-short-date",
            "release-2026-07-12-Uppercase",
            "release-2026-02-30-invalid-date",
        )
        for release_id in invalid_ids:
            with self.subTest(release_id=release_id):
                closure = rewrite_release_id(make_closure(), release_id)
                with self.assertRaises(CompilationError) as caught:
                    compile_world_pack(closure, self.profile)
                self.assertEqual("RELEASE", caught.exception.code)

    def test_pure_api_uses_no_network_clock_random_subprocess_or_mutable_state(self):
        closure = make_closure()
        with mock.patch("socket.socket", side_effect=AssertionError("network")), \
            mock.patch("urllib.request.urlopen", side_effect=AssertionError("network")), \
            mock.patch("time.time", side_effect=AssertionError("clock")), \
            mock.patch("random.random", side_effect=AssertionError("random")), \
            mock.patch("os.urandom", side_effect=AssertionError("random")), \
            mock.patch("os.getenv", side_effect=AssertionError("environment")), \
            mock.patch.object(builtins, "open", side_effect=AssertionError("filesystem")), \
            mock.patch("subprocess.run", side_effect=AssertionError("process")):
            result = compile_world_pack(closure, self.profile)
        self.assertTrue(result.root.startswith("sha256:"))


class IterativeGraphValidationTests(unittest.TestCase):
    def test_2001_node_graphs_are_iterative_and_deep_cycles_are_stable(self):
        nodes = ["node-{:04d}".format(index) for index in range(2_001)]
        acyclic = {
            node: ([] if index == 0 else [nodes[index - 1]])
            for index, node in enumerate(nodes)
        }
        for code in ("QUEST_CYCLE", "LINEAGE_CYCLE"):
            with self.subTest(code=code, graph="acyclic"):
                _detect_cycle(acyclic, code)
            cyclic = copy.deepcopy(acyclic)
            cyclic[nodes[0]] = [nodes[-1]]
            with self.subTest(code=code, graph="cyclic"):
                with self.assertRaises(CompilationError) as caught:
                    _detect_cycle(cyclic, code)
                self.assertEqual(code, caught.exception.code)
                self.assertEqual(nodes[0], caught.exception.location)

    def test_compiler_validates_a_2001_quest_chain_without_recursion(self):
        quests = []
        for index in range(2_001):
            entity_id = "source:quest:deep-{:04d}".format(index)
            quests.append(
                _entity(
                    entity_id,
                    "quest",
                    references=(
                        []
                        if index == 0
                        else [
                            _ref(
                                "depends-on",
                                "source:quest:deep-{:04d}".format(index - 1),
                            )
                        ]
                    ),
                )
            )
        profile = copy.deepcopy(load_trusted_profile())
        profile["limits"]["maxOutputFileBytes"] = 10_000_000
        result = compile_world_pack(
            make_closure([default_world_entity(), *quests]), profile
        )
        self.assertEqual(2_002, result.report["entityCount"])

        quests[0]["references"] = [
            _ref("depends-on", quests[-1]["entityId"])
        ]
        with self.assertRaises(CompilationError) as caught:
            compile_world_pack(
                make_closure([default_world_entity(), *quests]), profile
            )
        self.assertEqual("QUEST_CYCLE", caught.exception.code)


class ReproducibilityAndCLITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.profile = load_trusted_profile()
        cls.work_root = ROOT / ".test-work"
        cls.work_root.mkdir(exist_ok=True)

    @classmethod
    def tearDownClass(cls):
        if cls.work_root.exists() and not any(cls.work_root.iterdir()):
            cls.work_root.rmdir()

    def _two_source_closure(self):
        closure = make_closure()
        source = source_document(closure)
        second = copy.deepcopy(source)
        second["namespace"] = "rappterverse/synthetic-fixture-two"
        second["worldPackSourceId"] = "world-pack-source-synthetic-fixture-two"
        second["entities"][0]["entityId"] = "source:world:synthetic-fixture-two"
        second["entities"][0]["name"] = "Synthetic Fixture World Two"
        data = canonical_json_v2(second, stored=True)
        descriptor = _object_descriptor(
            "world-pack-sources",
            "world-pack-source",
            "application/json",
            data,
            "json",
            "source-two",
        )
        closure["worldPackSources"].append(_blob(descriptor, data))
        release = parse_json_v2(
            base64.b64decode(closure["release"]["manifest"]["bytesBase64"])
        )
        release["worldPackSources"].append(descriptor)
        release["totals"]["worldPackSources"] = 2
        release_bytes = canonical_json_v2(release, stored=True)
        old = closure["release"]["manifest"]["descriptor"]
        release_descriptor = _descriptor(
            old["path"],
            "release-manifest",
            "application/json",
            release_bytes,
            "release",
        )
        release_descriptor["reviewReceiptRef"] = old["reviewReceiptRef"]
        closure["release"]["manifest"] = _blob(
            release_descriptor, release_bytes
        )
        closure["verificationProof"]["reviewReceipts"] = _all_receipts(closure)
        return resign_closure(closure)

    def test_input_collection_order_is_irrelevant(self):
        closure = self._two_source_closure()
        first = compile_world_pack(closure, self.profile)
        reordered = copy.deepcopy(closure)
        reordered["worldPackSources"].reverse()
        reordered["verificationProof"]["reviewReceipts"].reverse()
        reordered = resign_closure(reordered)
        second = compile_world_pack(reordered, self.profile)
        self.assertEqual(first.files, second.files)
        self.assertEqual(first.root, second.root)
        self.assertEqual(first.report, second.report)

    def test_cli_reproducible_across_cwd_locale_timezone_and_hash_seed(self):
        closure = make_closure()
        with tempfile.TemporaryDirectory(dir=self.work_root) as directory:
            root = Path(directory)
            closure_path = root / "closure.json"
            closure_path.write_bytes(canonical_json_v2(closure, stored=True))
            outputs = (root / "first", root / "second")
            environments = (
                {"LC_ALL": "C", "TZ": "UTC", "PYTHONHASHSEED": "1"},
                {
                    "LC_ALL": "en_US.UTF-8",
                    "TZ": "Pacific/Honolulu",
                    "PYTHONHASHSEED": "777",
                },
            )
            for index, (output, additions) in enumerate(
                zip(outputs, environments)
            ):
                environment = os.environ.copy()
                environment.update(additions)
                result = subprocess.run(
                    [
                        sys.executable,
                        str(SCRIPTS / "compile_world_pack.py"),
                        "--closure",
                        str(closure_path),
                        "--output",
                        str(output),
                    ],
                    cwd=ROOT if index == 0 else SCRIPTS,
                    env=environment,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    check=False,
                )
                self.assertEqual(
                    0,
                    result.returncode,
                    result.stderr.decode(errors="replace"),
                )
            first_files = {
                path.relative_to(outputs[0]).as_posix(): path.read_bytes()
                for path in outputs[0].rglob("*")
                if path.is_file()
            }
            second_files = {
                path.relative_to(outputs[1]).as_posix(): path.read_bytes()
                for path in outputs[1].rglob("*")
                if path.is_file()
            }
            self.assertEqual(first_files, second_files)

    def test_cli_expected_hashes_are_comparisons_only(self):
        closure = make_closure()
        with tempfile.TemporaryDirectory(dir=self.work_root) as directory:
            root = Path(directory)
            closure_path = root / "closure.json"
            closure_path.write_bytes(canonical_json_v2(closure, stored=True))
            output = root / "output"
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS / "compile_world_pack.py"),
                    "--closure",
                    str(closure_path),
                    "--output",
                    str(output),
                    "--expect-compiler-sha256",
                    "sha256:" + "0" * 64,
                ],
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            self.assertNotEqual(0, result.returncode)
            self.assertFalse(output.exists())

    def test_existing_output_and_symlink_are_immutable(self):
        closure = make_closure()
        with tempfile.TemporaryDirectory(dir=self.work_root) as directory:
            root = Path(directory)
            closure_path = root / "closure.json"
            closure_path.write_bytes(canonical_json_v2(closure, stored=True))
            output = root / "output"
            output.mkdir()
            sentinel = output / "sentinel"
            sentinel.write_text("unchanged", encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS / "compile_world_pack.py"),
                    "--closure",
                    str(closure_path),
                    "--output",
                    str(output),
                ],
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            self.assertNotEqual(0, result.returncode)
            self.assertEqual("unchanged", sentinel.read_text(encoding="utf-8"))
            self.assertEqual(["sentinel"], [path.name for path in output.iterdir()])
            symlink = root / "closure-link.json"
            try:
                symlink.symlink_to(closure_path)
            except (OSError, NotImplementedError):
                self.skipTest("symlinks are unavailable")
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS / "compile_world_pack.py"),
                    "--closure",
                    str(symlink),
                    "--output",
                    str(root / "symlink-output"),
                ],
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            self.assertNotEqual(0, result.returncode)
            self.assertFalse((root / "symlink-output").exists())

    def test_existing_empty_output_is_atomically_replaced(self):
        closure = make_closure()
        with tempfile.TemporaryDirectory(dir=self.work_root) as directory:
            root = Path(directory)
            closure_path = root / "closure.json"
            closure_path.write_bytes(canonical_json_v2(closure, stored=True))
            output = root / "output"
            output.mkdir()
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS / "compile_world_pack.py"),
                    "--closure",
                    str(closure_path),
                    "--output",
                    str(output),
                ],
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            self.assertEqual(
                0, result.returncode, result.stderr.decode(errors="replace")
            )
            self.assertTrue((output / "pack-manifest.json").is_file())
            self.assertFalse(
                (root / ".output.world-pack-staging").exists()
            )

    def test_random_private_staging_is_atomic_and_does_not_overwrite(self):
        result = compile_world_pack(make_closure(), self.profile)
        with tempfile.TemporaryDirectory(dir=self.work_root) as directory:
            root = Path(directory)
            output = root / "output"
            events = []

            def inspect_staging(event, path):
                events.append((event, path.name))
                self.assertEqual("staging-created", event)
                self.assertFalse(output.exists())
                self.assertEqual(0o700, stat.S_IMODE(path.lstat().st_mode))

            compiler_cli._write_atomic(
                output,
                result.files,
                result.report,
                _event_hook=inspect_staging,
            )
            self.assertEqual(1, len(events))
            self.assertRegex(
                events[0][1], r"^\.world-pack-staging-[0-9a-f]{32}$"
            )
            before = {
                path.relative_to(output).as_posix(): path.read_bytes()
                for path in output.rglob("*")
                if path.is_file()
            }
            with self.assertRaisesRegex(
                compiler_cli.CLIError, "output directory must be empty"
            ):
                compiler_cli._write_atomic(
                    output, result.files, result.report
                )
            after = {
                path.relative_to(output).as_posix(): path.read_bytes()
                for path in output.rglob("*")
                if path.is_file()
            }
            self.assertEqual(before, after)
            self.assertFalse(
                any(
                    path.name.startswith(".world-pack-staging-")
                    for path in root.iterdir()
                )
            )

    def test_staging_symlink_swap_cannot_write_or_publish_outside(self):
        result = compile_world_pack(make_closure(), self.profile)
        with tempfile.TemporaryDirectory(dir=self.work_root) as directory:
            root = Path(directory)
            output = root / "output"
            outside = root / "outside"
            outside.mkdir()
            sentinel = outside / "sentinel"
            sentinel.write_bytes(b"outside-unchanged")
            held_original = root / "held-original-staging"
            swapped_paths = []

            def swap_staging(event, path):
                self.assertEqual("staging-created", event)
                path.rename(held_original)
                path.symlink_to(outside, target_is_directory=True)
                swapped_paths.append(path)

            with self.assertRaisesRegex(
                compiler_cli.CLIError, "staging directory identity changed"
            ):
                compiler_cli._write_atomic(
                    output,
                    result.files,
                    result.report,
                    _event_hook=swap_staging,
                )
            self.assertFalse(output.exists())
            self.assertEqual(b"outside-unchanged", sentinel.read_bytes())
            self.assertEqual(
                ["sentinel"],
                sorted(path.name for path in outside.iterdir()),
            )
            self.assertEqual(1, len(swapped_paths))
            self.assertTrue(swapped_paths[0].is_symlink())
            self.assertTrue(held_original.is_dir())
            self.assertEqual([], list(held_original.iterdir()))

    def test_atomic_output_fails_closed_without_dir_fd_primitives(self):
        result = compile_world_pack(make_closure(), self.profile)
        with tempfile.TemporaryDirectory(dir=self.work_root) as directory:
            output = Path(directory) / "output"
            with mock.patch.object(os, "supports_dir_fd", set()):
                with self.assertRaisesRegex(
                    compiler_cli.CLIError,
                    "secure output publication primitives unavailable",
                ):
                    compiler_cli._write_atomic(
                        output, result.files, result.report
                    )
            self.assertFalse(output.exists())

    def test_dangling_output_symlink_is_rejected(self):
        closure = make_closure()
        with tempfile.TemporaryDirectory(dir=self.work_root) as directory:
            root = Path(directory)
            closure_path = root / "closure.json"
            closure_path.write_bytes(canonical_json_v2(closure, stored=True))
            output = root / "dangling-output"
            try:
                output.symlink_to(
                    root / "missing-output-target", target_is_directory=True
                )
            except (OSError, NotImplementedError):
                self.skipTest("symlinks are unavailable")
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS / "compile_world_pack.py"),
                    "--closure",
                    str(closure_path),
                    "--output",
                    str(output),
                ],
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            self.assertNotEqual(0, result.returncode)
            self.assertIn(
                b"output path contains a symlink", result.stderr
            )
            self.assertTrue(os.path.lexists(output))
            self.assertTrue(output.is_symlink())

    def test_dangling_parent_component_symlink_is_rejected(self):
        closure = make_closure()
        with tempfile.TemporaryDirectory(dir=self.work_root) as directory:
            root = Path(directory)
            closure_path = root / "closure.json"
            closure_path.write_bytes(canonical_json_v2(closure, stored=True))
            parent = root / "dangling-parent"
            try:
                parent.symlink_to(
                    root / "missing-parent-target", target_is_directory=True
                )
            except (OSError, NotImplementedError):
                self.skipTest("symlinks are unavailable")
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS / "compile_world_pack.py"),
                    "--closure",
                    str(closure_path),
                    "--output",
                    str(parent / "output"),
                ],
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            self.assertNotEqual(0, result.returncode)
            self.assertIn(
                b"output path contains a symlink", result.stderr
            )
            self.assertTrue(os.path.lexists(parent))
            self.assertTrue(parent.is_symlink())


class ImplementationAndSchemaTests(unittest.TestCase):
    def test_compiler_implementation_digest_uses_closed_actual_sources(self):
        self.assertEqual(
            "sha256:20facd2f04e20f78e132938b766b918b"
            "a07c1798460654c99c588c1cd7d67dca",
            COMPILER_IMPLEMENTATION_SHA256,
        )
        source_files = tuple(
            (path, (ROOT / path).read_bytes()) for path in COMPILER_SOURCE_FILES
        )
        self.assertEqual(
            COMPILER_IMPLEMENTATION_SHA256,
            implementation_digest(source_files),
        )
        changed = list(source_files)
        changed[0] = (changed[0][0], changed[0][1] + b"\n")
        self.assertNotEqual(
            COMPILER_IMPLEMENTATION_SHA256,
            implementation_digest(changed),
        )
        self.assertEqual(len(COMPILER_SOURCE_FILES), len(set(COMPILER_SOURCE_FILES)))
        self.assertIn(
            "scripts/world_pack_compiler/trust.py", COMPILER_SOURCE_FILES
        )

    def test_engine_schemas_are_json_and_every_typed_object_is_closed(self):
        schemas = (
            ROOT / "schema" / "world-pack-compiler-profile-v1.schema.json",
            ROOT / "schema" / "verified-world-source-closure-v1.schema.json",
            ROOT / "schema" / "world-pack-v1.schema.json",
        )
        for path in schemas:
            schema = json.loads(path.read_text(encoding="utf-8"))
            stack = [("$", schema)]
            while stack:
                location, value = stack.pop()
                if isinstance(value, dict):
                    if value.get("type") == "object":
                        self.assertIs(
                            False,
                            value.get("additionalProperties"),
                            "{} {}".format(path.name, location),
                        )
                    stack.extend(
                        (location + "." + key, child)
                        for key, child in value.items()
                    )
                elif isinstance(value, list):
                    stack.extend(
                        ("{}[{}]".format(location, index), child)
                        for index, child in enumerate(value)
                    )

    def test_seed_channels_schema_and_runtime_reject_non_arrays(self):
        schema = json.loads(
            (
                ROOT
                / "schema"
                / "world-pack-compiler-profile-v1.schema.json"
            ).read_text(encoding="utf-8")
        )
        channels_schema = schema["$defs"]["SeedDerivation"]["properties"][
            "channels"
        ]
        self.assertEqual("array", channels_schema["type"])
        for channels in (None, "immutable-layout"):
            with self.subTest(channels=channels):
                self.assertFalse(isinstance(channels, list))
                profile = copy.deepcopy(load_trusted_profile())
                profile["seedDerivation"]["channels"] = channels
                with self.assertRaisesRegex(
                    CompilationError, "seed channels"
                ):
                    compile_world_pack(make_closure(), profile)

    def test_runtime_and_both_schemas_share_strict_safe_path_vectors(self):
        closure_schema = json.loads(
            (
                ROOT
                / "schema"
                / "verified-world-source-closure-v1.schema.json"
            ).read_text(encoding="utf-8")
        )
        pack_schema = json.loads(
            (ROOT / "schema" / "world-pack-v1.schema.json").read_text(
                encoding="utf-8"
            )
        )
        patterns = (
            closure_schema["$defs"]["SafePath"]["pattern"],
            pack_schema["$defs"]["PayloadFile"]["properties"]["path"][
                "pattern"
            ],
        )
        self.assertEqual(patterns[0], patterns[1])
        collision = ("café/file.json", "cafe\u0301/file.json")
        self.assertEqual(
            __import__("unicodedata").normalize("NFC", collision[1]),
            collision[0],
        )
        vectors = {
            "a": True,
            ".hidden": True,
            "a/b.json": True,
            "a/.../b": True,
            "": False,
            ".": False,
            "..": False,
            "a/.": False,
            "a/..": False,
            "a//b": False,
            "/absolute": False,
            "a\\b": False,
            "a/\ncontrol": False,
            collision[0]: False,
            collision[1]: False,
        }
        for value, expected in vectors.items():
            with self.subTest(path=value):
                schema_results = [
                    re.fullmatch(pattern, value) is not None
                    for pattern in patterns
                ]
                try:
                    _safe_path(value, "$.path")
                    runtime = True
                except CompilationError:
                    runtime = False
                self.assertEqual([expected, expected], schema_results)
                self.assertEqual(expected, runtime)

    def test_release_id_schema_contract_is_exact(self):
        expected = (
            r"^release-[0-9]{4}-[0-9]{2}-[0-9]{2}-"
            r"[a-z0-9][a-z0-9.-]{0,63}$"
        )
        closure = json.loads(
            (
                ROOT
                / "schema"
                / "verified-world-source-closure-v1.schema.json"
            ).read_text(encoding="utf-8")
        )
        pack = json.loads(
            (ROOT / "schema" / "world-pack-v1.schema.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(
            expected,
            closure["$defs"]["Release"]["properties"]["releaseId"][
                "pattern"
            ],
        )
        self.assertEqual(
            expected,
            pack["$defs"]["Release"]["properties"]["releaseId"]["pattern"],
        )

    def test_engine_owned_profile_and_legacy_sources_match_raw_pins(self):
        self.assertEqual(
            "compiler/profiles/rappterverse-v1.json",
            TRUSTED_PROFILE_PATH,
        )
        self.assertFalse((ROOT / "worlds" / "recipes").exists())
        profile_bytes = (ROOT / TRUSTED_PROFILE_PATH).read_bytes()
        lock_bytes = (
            ROOT / "bootstrap" / "legacy-source-lock.json"
        ).read_bytes()
        self.assertEqual(
            TRUSTED_PROFILE_RAW_SHA256,
            hashlib.sha256(profile_bytes).hexdigest(),
        )
        self.assertEqual(
            "sha256:0d7831570dde56b7958dd204d0e9c20e"
            "7b7439ea0049012ee347dcd21c70d5cb",
            "sha256:"
            + hashlib.sha256(
                canonical_json_v2(load_trusted_profile(), stored=True)
            ).hexdigest(),
        )
        self.assertEqual(
            LEGACY_LOCK_RAW_SHA256,
            hashlib.sha256(lock_bytes).hexdigest(),
        )
        self.assertEqual(
            LEGACY_MAIN_TREE,
            subprocess.check_output(
                [
                    "git",
                    "-C",
                    str(ROOT),
                    "rev-parse",
                    "{}^{{tree}}".format(LEGACY_MAIN_COMMIT),
                ],
                text=True,
            ).strip(),
        )
        for path, size, digest in LEGACY_REQUIRED_SOURCE_DESCRIPTORS:
            data = subprocess.check_output(
                [
                    "git",
                    "-C",
                    str(ROOT),
                    "show",
                    "{}:{}".format(LEGACY_MAIN_COMMIT, path),
                ]
            )
            self.assertEqual(size, len(data), path)
            self.assertEqual(digest, hashlib.sha256(data).hexdigest(), path)


class LegacyTrustAndExtractionTests(unittest.TestCase):
    def test_public_api_rejects_overrides_and_alternate_worktrees(self):
        profile = load_trusted_profile()
        lock_path = ROOT / "bootstrap" / "legacy-source-lock.json"
        for call in (
            lambda: compile_legacy_v1(ROOT.parent),
            lambda: compile_legacy_v1(ROOT, trusted_profile=profile),
            lambda: compile_legacy_v1(ROOT, lock_path=lock_path),
        ):
            with self.subTest(call=call):
                with self.assertRaisesRegex(
                    LegacyCompilationError, "engine-owned|alternate"
                ):
                    call()

    def test_production_cli_has_no_legacy_trust_override(self):
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPTS / "compile_world_pack.py"),
                "--legacy-v1",
                "--repo-root",
                str(ROOT.parent),
                "--output",
                str(ROOT / ".test-work" / "must-not-exist"),
            ],
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        self.assertEqual(2, result.returncode)
        self.assertIn(b"unrecognized arguments: --repo-root", result.stderr)

    def test_substituted_lock_commit_and_tree_are_independently_rejected(self):
        original = (
            ROOT / "bootstrap" / "legacy-source-lock.json"
        ).read_bytes()
        changed = json.loads(original)
        changed["repository"] = "attacker/repository"
        changed_bytes = canonical_json_v2(changed, stored=True)
        with self.assertRaisesRegex(LegacyCompilationError, "raw digest"):
            _compile_legacy_v1_for_test(ROOT, changed_bytes)

        for field, value, expected in (
            ("commit", "0" * 40, "main commit"),
            ("tree", "0" * 40, "main tree"),
        ):
            changed = json.loads(original)
            changed["sources"]["main"][field] = value
            changed_bytes = canonical_json_v2(changed, stored=True)
            with self.subTest(field=field):
                with self.assertRaisesRegex(LegacyCompilationError, expected):
                    _compile_legacy_v1_for_test(
                        ROOT,
                        changed_bytes,
                        expected_lock_sha256=hashlib.sha256(
                            changed_bytes
                        ).hexdigest(),
                    )

    def test_substituted_pinned_blob_is_rejected_by_source_descriptor(self):
        original = legacy_module._git_blob

        def substituted(repo_root, commit, path, *, max_bytes):
            data = original(
                repo_root, commit, path, max_bytes=max_bytes
            )
            if path == "worlds/hub/config.json":
                return data + b" "
            return data

        with mock.patch.object(
            legacy_module, "_git_blob", side_effect=substituted
        ):
            with self.assertRaisesRegex(
                LegacyCompilationError, "source descriptor"
            ):
                compile_legacy_v1()

    def test_js_literal_extraction_requires_the_exact_terminator(self):
        valid = b"const VALUE = ['hub', 'arena']   ;\nconst NEXT = 1;"
        self.assertEqual(
            ["hub", "arena"],
            _extract_js_literal(valid, "const VALUE =", "fixture.js", ";"),
        )
        invalid = (
            b"const VALUE = ['hub'].concat(['arena']);",
            b"const VALUE = ['hub'] + ['arena'];",
            b"const VALUE = makeWorlds();",
            b"const VALUE = ['hub'] trailing;",
            b"const VALUE = ['hub'] /* hidden */;",
        )
        for data in invalid:
            with self.subTest(data=data):
                with self.assertRaises(LegacyCompilationError):
                    _extract_js_literal(
                        data, "const VALUE =", "fixture.js", ";"
                    )

    def test_recursive_catalog_protection_keeps_only_static_mechanics(self):
        profile = load_trusted_profile()
        protected = {
            "".join(character.lower() for character in name if character.isalnum())
            for name in (
                profile["overlayProtection"]["publicPreservedFields"]
                + profile["overlayProtection"]["denylist"]
            )
        }
        projected = _catalog_defaults(
            {
                "damage": 12,
                "cooldown": 3,
                "nested": {
                    "current_Hp": 99,
                    "controller-id": "attacker",
                    "inventory": ["forged"],
                    "balances": {"rapp": 999},
                    "history": [{"event": "forged"}],
                    "mechanic": {"range": 7},
                },
            },
            protected,
        )
        self.assertEqual(12, projected["baseDamage"])
        self.assertEqual(3, projected["cooldown"])
        self.assertEqual({"mechanic": {"range": 7}}, projected["nested"])


class LegacyV1ParityTests(unittest.TestCase):
    COMMIT = "676fdda8d3881a284bdb0c09174ee76acc0c9219"
    WORLD_IDS = ("hub", "arena", "marketplace", "gallery", "dungeon")

    @staticmethod
    def _git_json(path):
        raw = subprocess.check_output(
            ["git", "-C", str(ROOT), "show", "{}:{}".format(LegacyV1ParityTests.COMMIT, path)]
        )
        return json.loads(raw)

    @staticmethod
    def _state_hashes():
        return {
            path.relative_to(ROOT).as_posix(): hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
            for path in sorted((ROOT / "state").rglob("*"))
            if path.is_file()
        }

    def test_complete_static_semantics_match_independent_pinned_blob_golden(self):
        result = compile_legacy_v1()
        expected = build_expected_domains(ROOT)
        actual = build_actual_domains(result.files)
        self.assertEqual(expected, actual)
        self.assertEqual(LEGACY_SEMANTIC_GOLDEN, semantic_summary(expected))
        self.assertEqual(LEGACY_SEMANTIC_GOLDEN, semantic_summary(actual))
        self.assertEqual(LEGACY_PACK_ROOT, result.root)
        manifest = _decode_json(result.files["pack-manifest.json"])
        expected_lock_digest = "sha256:" + LEGACY_LOCK_RAW_SHA256
        self.assertEqual(
            {
                "commit": LEGACY_MAIN_COMMIT,
                "lockSha256": expected_lock_digest,
                "tree": LEGACY_MAIN_TREE,
            },
            manifest["legacySource"],
        )
        provenance = [
            parse_json_v2(line)
            for line in result.files["provenance.jsonl"].splitlines()
        ]
        lock_digests = [
            manifest["legacySource"]["lockSha256"],
            result.report["legacySource"]["lockSha256"],
            *[
                row["legacySource"]["lockSha256"]
                for row in provenance
            ],
        ]
        self.assertEqual(
            [expected_lock_digest] * len(lock_digests), lock_digests
        )

    def test_all_static_world_defaults_preserve_ids_counts_and_portals(self):
        result = compile_legacy_v1(ROOT)
        worlds = _decode_json(result.files["worlds.json"])["worlds"]
        self.assertEqual(list(self.WORLD_IDS), [world["id"] for world in worlds])
        self.assertEqual(102, result.report["objectCount"])
        self.assertEqual(32, result.report["npcCount"])
        expected_portals = []
        for world_id in self.WORLD_IDS:
            source_config = self._git_json(
                "worlds/{}/config.json".format(world_id)
            )
            packed_config = _decode_json(
                result.files["worlds/{}/config.json".format(world_id)]
            )
            for key in ("id", "name", "description", "bounds", "features"):
                self.assertEqual(source_config[key], packed_config[key])
            source_objects = self._git_json(
                "worlds/{}/objects.json".format(world_id)
            )["objects"]
            packed_objects = _decode_json(
                result.files["worlds/{}/objects.json".format(world_id)]
            )["objects"]
            self.assertEqual(
                [item["id"] for item in source_objects],
                [item["id"] for item in packed_objects],
            )
            source_npcs = self._git_json(
                "worlds/{}/npcs.json".format(world_id)
            )["npcs"]
            packed_npcs = _decode_json(
                result.files["worlds/{}/npcs.json".format(world_id)]
            )["npcs"]
            self.assertEqual(
                [item["id"] for item in source_npcs],
                [item["id"] for item in packed_npcs],
            )
            expected_portals.extend(
                {
                    "destinationWorldId": item["destination"],
                    "id": item["id"],
                    "worldId": world_id,
                }
                for item in source_objects
                if item.get("type") == "portal"
            )
        compatibility = _decode_json(result.files["legacy-compatibility.json"])
        self.assertEqual(
            sorted(
                expected_portals,
                key=lambda item: (
                    item["worldId"],
                    item["id"],
                    item["destinationWorldId"],
                ),
            ),
            compatibility["portalEndpoints"],
        )

    def test_renderer_scale_and_frontend_catalog_parity(self):
        result = compile_legacy_v1(ROOT)
        compatibility = _decode_json(result.files["legacy-compatibility.json"])
        self.assertEqual(list(self.WORLD_IDS), compatibility["worldIds"])
        for world_id in self.WORLD_IDS:
            source = self._git_json(
                "worlds/{}/config.json".format(world_id)
            )
            renderer = compatibility["worlds"][world_id]
            self.assertEqual(
                max(map(abs, source["bounds"]["x"])) * 10,
                renderer["bounds"]["x"],
            )
            self.assertEqual(
                max(map(abs, source["bounds"]["z"])) * 10,
                renderer["bounds"]["z"],
            )
            packed = _decode_json(
                result.files["worlds/{}/config.json".format(world_id)]
            )
            self.assertEqual(10, packed["renderer"]["unitsPerSimulationUnit"])
        self.assertEqual(
            {
                "health_potion",
                "mana_crystal",
                "scrap_metal",
                "power_cell",
                "frost_blade",
                "magma_sword",
                "void_dagger",
                "star_blade",
                "guardian_plate",
                "nano_armor",
                "berserker_badge",
                "vampiric_fang",
                "swift_boots",
            },
            set(compatibility["catalogs"]["inventoryItems"]),
        )
        self.assertEqual(
            ["Slash", "Pulse Shot", "Shield", "Dash", "Nova"],
            [
                item["name"]
                for item in compatibility["catalogs"]["abilities"]
            ],
        )

    def test_effective_then_noop_static_load_preserves_semantics(self):
        result = compile_legacy_v1(ROOT)
        registry = {}

        def load():
            changed = 0
            for world_id in self.WORLD_IDS:
                for category in ("objects", "npcs"):
                    path = "worlds/{}/{}.json".format(world_id, category)
                    rows = _decode_json(result.files[path])[category]
                    key = (world_id, category)
                    ids = tuple(item["id"] for item in rows)
                    if registry.get(key) != ids:
                        registry[key] = ids
                        changed += 1
            compatibility = _decode_json(
                result.files["legacy-compatibility.json"]
            )
            endpoints = tuple(
                (item["worldId"], item["id"], item["destinationWorldId"])
                for item in compatibility["portalEndpoints"]
            )
            if registry.get("portals") != endpoints:
                registry["portals"] = endpoints
                changed += 1
            catalogs = tuple(
                sorted(compatibility["catalogs"]["inventoryItems"])
            )
            if registry.get("catalogs") != catalogs:
                registry["catalogs"] = catalogs
                changed += 1
            return changed

        self.assertGreater(load(), 0)
        snapshot = copy.deepcopy(registry)
        self.assertEqual(0, load())
        self.assertEqual(snapshot, registry)

    def test_compilation_does_not_read_or_mutate_overlay_state(self):
        before = self._state_hashes()
        result = compile_legacy_v1(ROOT)
        after = self._state_hashes()
        self.assertEqual(before, after)
        compatibility = _decode_json(result.files["legacy-compatibility.json"])
        source_paths = [item["path"] for item in compatibility["sourceBlobs"]]
        self.assertTrue(all(not path.startswith("state/") for path in source_paths))
        self.assertEqual(19, len(source_paths))

    def test_legacy_defaults_exclude_mutable_overlay_fields(self):
        result = compile_legacy_v1(ROOT)
        profile = load_trusted_profile()
        forbidden = {
            "".join(
                character.lower()
                for character in name
                if character.isalnum()
            )
            for name in (
                profile["overlayProtection"]["publicPreservedFields"]
                + profile["overlayProtection"]["denylist"]
            )
        }
        for path, data in result.files.items():
            if path in ("pack-manifest.json", "provenance.jsonl"):
                continue
            value = _decode_json(data)
            stack = [value]
            while stack:
                item = stack.pop()
                if isinstance(item, dict):
                    normalized = {
                        "".join(c.lower() for c in key if c.isalnum())
                        for key in item
                    }
                    self.assertFalse(
                        forbidden & normalized,
                        "{} contains protected fields {}".format(
                            path, sorted(forbidden & normalized)
                        ),
                    )
                    stack.extend(item.values())
                elif isinstance(item, list):
                    stack.extend(item)

    def test_cli_generates_small_pack_under_worlds_packs_convention(self):
        work_root = ROOT / ".test-work"
        work_root.mkdir(exist_ok=True)
        try:
            with tempfile.TemporaryDirectory(dir=work_root) as directory:
                root = Path(directory)
                output = root / "worlds" / "_packs" / "legacy-v1"
                output.parent.mkdir(parents=True)
                result = subprocess.run(
                    [
                        sys.executable,
                        str(SCRIPTS / "compile_world_pack.py"),
                        "--legacy-v1",
                        "--output",
                        str(output),
                    ],
                    cwd=ROOT,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    check=False,
                )
                self.assertEqual(
                    0,
                    result.returncode,
                    result.stderr.decode(errors="replace"),
                )
                report = _decode_json((output / "build-report.json").read_bytes())
                self.assertEqual("compiled", report["status"])
                files = [path for path in output.rglob("*") if path.is_file()]
                self.assertTrue(files)
                self.assertTrue(all(path.stat().st_size <= 1_000_000 for path in files))
        finally:
            if work_root.exists() and not any(work_root.iterdir()):
                work_root.rmdir()


if __name__ == "__main__":
    unittest.main()
