"""Fail-closed tests for the inert universe-lock v2 safety sentinel."""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from world_pack_compiler import (  # noqa: E402
    CanonicalJSONV2DepthError,
    CanonicalJSONV2Error,
    canonical_json_v2,
    parse_json_v2,
)

LOCK_PATH = ROOT / "universe.lock.json"
SCHEMA_PATH = ROOT / "schema" / "universe-lock-v2.schema.json"
WORKFLOWS = ROOT / ".github" / "workflows"

EXPECTED_LOCK = {
    "schemaVersion": "rappterverse.universe-lock/v2",
    "mode": "disabled",
    "generation": 0,
    "reason": "awaiting-signed-approval",
    "activation": None,
}
EXPECTED_BYTES = (
    b'{"activation":null,"generation":0,"mode":"disabled",'
    b'"reason":"awaiting-signed-approval",'
    b'"schemaVersion":"rappterverse.universe-lock/v2"}\n'
)
LOCK_FIELDS = frozenset(EXPECTED_LOCK)
FORBIDDEN_FIELDS = (
    "repository",
    "commit",
    "manifest",
    "compiler",
    "pack",
    "approval",
    "updater",
    "fallback",
)


class UniverseLockV2Error(ValueError):
    """Raised when inert lock data has any shape other than the sentinel."""


def _load_lock(data: bytes) -> dict[str, object]:
    value = parse_json_v2(data, require_stored=True, max_bytes=1_024)
    if not isinstance(value, dict):
        raise UniverseLockV2Error("universe lock root must be an object")
    if set(value) != LOCK_FIELDS:
        raise UniverseLockV2Error("universe lock fields are not the closed set")
    if (
        type(value["schemaVersion"]) is not str
        or value["schemaVersion"] != EXPECTED_LOCK["schemaVersion"]
        or type(value["mode"]) is not str
        or value["mode"] != EXPECTED_LOCK["mode"]
        or type(value["generation"]) is not int
        or value["generation"] != EXPECTED_LOCK["generation"]
        or type(value["reason"]) is not str
        or value["reason"] != EXPECTED_LOCK["reason"]
        or value["activation"] is not None
    ):
        raise UniverseLockV2Error("universe lock is not the disabled sentinel")
    return value


class UniverseLockV2Tests(unittest.TestCase):
    def assert_rejected(self, value: object) -> None:
        with self.assertRaises(
            (CanonicalJSONV2Error, UniverseLockV2Error)
        ):
            if isinstance(value, bytes):
                _load_lock(value)
            else:
                _load_lock(canonical_json_v2(value, stored=True))

    def test_schema_is_closed_and_has_one_possible_instance(self):
        schema = parse_json_v2(SCHEMA_PATH.read_bytes())
        self.assertEqual(
            {
                "$schema",
                "$id",
                "title",
                "description",
                "type",
                "additionalProperties",
                "minProperties",
                "maxProperties",
                "required",
                "properties",
            },
            set(schema),
        )
        self.assertEqual("object", schema["type"])
        self.assertIs(False, schema["additionalProperties"])
        self.assertEqual(5, schema["minProperties"])
        self.assertEqual(5, schema["maxProperties"])
        self.assertEqual(LOCK_FIELDS, set(schema["required"]))
        self.assertEqual(
            {
                "schemaVersion": {
                    "type": "string",
                    "const": EXPECTED_LOCK["schemaVersion"],
                },
                "mode": {
                    "type": "string",
                    "const": EXPECTED_LOCK["mode"],
                },
                "generation": {
                    "type": "integer",
                    "const": EXPECTED_LOCK["generation"],
                },
                "reason": {
                    "type": "string",
                    "const": EXPECTED_LOCK["reason"],
                },
                "activation": {"type": "null", "const": None},
            },
            schema["properties"],
        )
        self.assertFalse(
            set(FORBIDDEN_FIELDS) & set(schema["properties"])
        )

    def test_stored_lock_has_documented_exact_canonical_v2_bytes(self):
        data = LOCK_PATH.read_bytes()
        self.assertEqual(EXPECTED_BYTES, data)
        self.assertEqual(
            canonical_json_v2(EXPECTED_LOCK, stored=True),
            data,
        )
        self.assertEqual(EXPECTED_LOCK, _load_lock(data))

    def test_duplicate_nonfinite_utf8_and_depth_inputs_are_rejected(self):
        duplicate = EXPECTED_BYTES.replace(
            b'"mode":"disabled",',
            b'"mode":"disabled","mode":"disabled",',
        )
        invalid_inputs = (
            duplicate,
            EXPECTED_BYTES.replace(b'"generation":0', b'"generation":NaN'),
            EXPECTED_BYTES.replace(
                b'"generation":0', b'"generation":Infinity'
            ),
            EXPECTED_BYTES.replace(
                b'"generation":0', b'"generation":-Infinity'
            ),
            EXPECTED_BYTES.replace(b'"disabled"', b'"\xff"'),
            b"\xef\xbb\xbf" + EXPECTED_BYTES,
            EXPECTED_BYTES.replace(b'"disabled"', b'"\\ud800"'),
        )
        for value in invalid_inputs:
            with self.subTest(value=value):
                self.assert_rejected(value)

        nested = b"[" * 65 + b"null" + b"]" * 65
        too_deep = EXPECTED_BYTES.replace(b'"activation":null', b'"activation":' + nested)
        with self.assertRaises(CanonicalJSONV2DepthError):
            _load_lock(too_deep)

    def test_noncanonical_storage_and_unknown_fields_are_rejected(self):
        noncanonical = (
            EXPECTED_BYTES[:-1],
            EXPECTED_BYTES[:-1] + b"\r\n",
            EXPECTED_BYTES + b"\n",
            EXPECTED_BYTES.replace(b":null", b": null", 1),
        )
        for value in noncanonical:
            with self.subTest(value=value):
                self.assert_rejected(value)

        for field in ("extension", *FORBIDDEN_FIELDS):
            candidate = dict(EXPECTED_LOCK)
            candidate[field] = None
            with self.subTest(field=field):
                self.assert_rejected(candidate)

    def test_non_null_activation_repository_and_compiler_are_rejected(self):
        for value in ({}, [], "signed", 0, False):
            candidate = dict(EXPECTED_LOCK)
            candidate["activation"] = value
            with self.subTest(field="activation", value=value):
                self.assert_rejected(candidate)
        for field, value in (
            ("repository", {"name": "example/repository"}),
            ("compiler", {"version": "example"}),
        ):
            candidate = dict(EXPECTED_LOCK)
            candidate[field] = value
            with self.subTest(field=field):
                self.assert_rejected(candidate)

    def test_transition_cannot_be_inferred_or_expressed(self):
        for field in LOCK_FIELDS:
            candidate = dict(EXPECTED_LOCK)
            del candidate[field]
            with self.subTest(missing=field):
                self.assert_rejected(candidate)

        mutations = (
            ("schemaVersion", "rappterverse.universe-lock/v3"),
            ("mode", "enabled"),
            ("generation", 1),
            ("generation", False),
            ("reason", "approved"),
            ("activation", {"approved": True}),
        )
        for field, value in mutations:
            candidate = dict(EXPECTED_LOCK)
            candidate[field] = value
            with self.subTest(field=field, value=value):
                self.assert_rejected(candidate)

        for field in (
            "transition",
            "nextMode",
            "nextGeneration",
            "source",
            "target",
            *FORBIDDEN_FIELDS,
        ):
            candidate = dict(EXPECTED_LOCK)
            candidate[field] = {"value": "not-permitted"}
            with self.subTest(transition_field=field):
                self.assert_rejected(candidate)

    def test_no_runtime_code_consumes_or_imports_the_sentinel(self):
        markers = ("universe.lock", "universe-lock-v2", "universe_lock")
        offenders = []
        for root in (ROOT / "scripts", ROOT / "src"):
            for path in sorted(root.rglob("*")):
                if (
                    not path.is_file()
                    or path.name.startswith("test_")
                    or path.suffix not in {".py", ".js", ".sh", ".html"}
                ):
                    continue
                text = path.read_text(encoding="utf-8").lower()
                if any(marker in text for marker in markers):
                    offenders.append(path.relative_to(ROOT).as_posix())
        self.assertEqual([], offenders)

    def test_no_updater_workflow_or_lock_write_permission_exists(self):
        focused_command = (
            "python -m unittest discover -s tests "
            "-p 'test_universe_lock_v2.py' -v"
        )
        artifact_markers = (
            "universe.lock.json",
            "universe-lock-v2.schema.json",
            "rappterverse.universe-lock/v2",
        )
        focused_workflows = []
        for path in sorted(WORKFLOWS.glob("*.yml")):
            text = path.read_text(encoding="utf-8")
            lower_name = path.stem.lower()
            self.assertIsNone(
                re.search(
                    r"(?:universe.*(?:lock|updat)|(?:lock|updat).*universe)",
                    lower_name,
                ),
                path.name,
            )
            for marker in artifact_markers:
                self.assertNotIn(marker, text, path.name)
            if focused_command in text:
                focused_workflows.append(path.name)

        self.assertEqual(["regression-tests.yml"], focused_workflows)
        regression = (WORKFLOWS / "regression-tests.yml").read_text(
            encoding="utf-8"
        )
        test_job = regression.split("\n  report-scheduled-failure:", 1)[0]
        self.assertIn("permissions:\n      contents: read", test_job)
        self.assertIn("persist-credentials: false", test_job)
        self.assertIsNone(
            re.search(r"(?m)^\s+[a-z-]+:\s+write\s*$", test_job)
        )

    def test_state_action_trigger_remains_disjoint(self):
        workflow = (WORKFLOWS / "agent-action.yml").read_text(encoding="utf-8")
        trigger = workflow.split("\npermissions:", 1)[0]
        self.assertEqual(
            ["state/**", "worlds/**", "feed/**"],
            re.findall(r"(?m)^\s+- ['\"]([^'\"]+)['\"]\s*$", trigger),
        )
        self.assertNotIn("universe", trigger.lower())


if __name__ == "__main__":
    unittest.main()
