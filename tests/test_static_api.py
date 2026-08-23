"""rapp-static-api/1.0 conformance for RAPPterverse.

Scores the repository against the spec's own §5 checklist:
https://raw.githubusercontent.com/kody-w/rapp-static-apis/main/SPEC.md

These are *structural* assertions only. Nothing here compares a hash in
``registry.json`` against the live bytes of a state file, because §3
("Liveness") makes the index the latest known state rather than a freshness
contract — gating every action PR on index staleness would recreate the
un-passable gate removed in docs/SPEC_DRIFT.md D6.
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "scripts"))

from static_api import (  # noqa: E402
    INDEX_SCHEMA,
    ISO_Z,
    STATUS_SCHEMA,
    declared_documents,
    detect_indent,
    load_manifest,
    rel_path,
    schema_for,
    stamp_mapping,
)

MANIFEST_PATH = BASE_DIR / "manifest.json"
REGISTRY_PATH = BASE_DIR / "registry.json"
STATUS_PATH = BASE_DIR / "api" / "v1" / "status.json"
BADGE_PATH = BASE_DIR / "api" / "v1" / "badge.json"
BUILD = BASE_DIR / "scripts" / "build_static_api.py"

SCHEMA_ID = r"^[a-z0-9][a-z0-9-]*/\d+\.\d+$"


class TestAnatomy(unittest.TestCase):
    """§2 — the required roles exist and are what the spec says they are."""

    def test_one_hand_authored_input(self):
        self.assertTrue(MANIFEST_PATH.is_file(), "manifest.json (role 1) missing")
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        self.assertEqual(INDEX_SCHEMA, manifest.get("schema"))
        self.assertTrue(manifest["raw_base"].startswith("https://raw.githubusercontent.com/"))

    def test_exactly_one_build_step(self):
        self.assertTrue(BUILD.is_file(), "scripts/build_static_api.py (role 2) missing")

    def test_generated_index_and_endpoints_exist(self):
        for path, label in (
            (REGISTRY_PATH, "index (role 3)"),
            (STATUS_PATH, "status endpoint (role 4)"),
            (BADGE_PATH, "badge endpoint (role 4)"),
        ):
            self.assertTrue(path.is_file(), f"{rel_path(path)}: {label} missing")

    def test_nojekyll_at_pages_root(self):
        """§5 item 4 — Pages source is main:/docs, so .nojekyll belongs in docs/."""
        manifest = load_manifest()
        nojekyll = BASE_DIR / manifest.get("pages_dir", "docs") / ".nojekyll"
        self.assertTrue(nojekyll.is_file(), f"{rel_path(nojekyll)} missing")

    def test_pwa_manifest_is_not_repurposed_as_the_index(self):
        """docs/manifest.json is a W3C web-app manifest, a different artifact."""
        pwa = BASE_DIR / "docs" / "manifest.json"
        if pwa.is_file():
            payload = json.loads(pwa.read_text(encoding="utf-8"))
            self.assertNotEqual(INDEX_SCHEMA, payload.get("schema"))
            self.assertIn("start_url", payload)


class TestIndex(unittest.TestCase):
    """§5 items 2 and 7 — a schema-tagged index that names its raw base URL."""

    @classmethod
    def setUpClass(cls):
        cls.registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))

    def test_index_is_schema_tagged(self):
        self.assertEqual(INDEX_SCHEMA, self.registry.get("schema"))

    def test_index_names_its_raw_base_url(self):
        self.assertEqual(
            "https://raw.githubusercontent.com/kody-w/rappterverse/main",
            self.registry.get("raw_base"),
        )

    def test_index_is_itself_fetchable_over_raw(self):
        raw_base = self.registry["raw_base"]
        self.assertTrue(
            (BASE_DIR / "registry.json").is_file(),
            f"the index must live at {raw_base}/registry.json",
        )

    def test_every_entry_carries_a_schema_id_and_a_raw_url(self):
        raw_base = self.registry["raw_base"]
        self.assertTrue(self.registry["entries"])
        for entry in self.registry["entries"]:
            self.assertRegex(entry["schema"], SCHEMA_ID, entry["name"])
            self.assertEqual(f"{raw_base}/{entry['path']}", entry["raw_url"])

    def test_generated_timestamp_is_iso8601_z(self):
        self.assertRegex(self.registry["generated"], ISO_Z)

    def test_every_manifest_entry_is_indexed(self):
        indexed = {e["name"] for e in self.registry["entries"]}
        declared = {e["name"] for e in load_manifest()["entries"]}
        self.assertEqual(declared, indexed)


class TestVersionedEndpoints(unittest.TestCase):
    """§5 item 5 — versioned JSON endpoints under api/v<major>/."""

    def test_status_endpoint_carries_its_own_schema_id(self):
        status = json.loads(STATUS_PATH.read_text(encoding="utf-8"))
        self.assertEqual(STATUS_SCHEMA, status["schema"])
        self.assertRegex(status["generated"], ISO_Z)

    def test_badge_is_a_shields_io_endpoint(self):
        badge = json.loads(BADGE_PATH.read_text(encoding="utf-8"))
        self.assertEqual(1, badge["schemaVersion"])
        for field in ("label", "message", "color"):
            self.assertIn(field, badge)

    def test_endpoints_live_under_a_major_version_directory(self):
        for path in (STATUS_PATH, BADGE_PATH):
            self.assertEqual("v1", path.parent.name)
            self.assertEqual("api", path.parent.parent.name)


class TestSchemaStrings(unittest.TestCase):
    """§3 — every generated document carries "<name>/<major>.<minor>"."""

    def test_every_declared_document_is_stamped(self):
        missing = []
        for path, schema in declared_documents():
            payload = json.loads(path.read_text(encoding="utf-8"))
            if payload.get("schema") != schema:
                missing.append(rel_path(path))
        self.assertEqual([], missing, f"{len(missing)} document(s) without a schema string")

    def test_the_repo_actually_serves_a_meaningful_number_of_them(self):
        """Guards against the manifest being quietly emptied to make this pass."""
        self.assertGreaterEqual(len(declared_documents()), 200)

    def test_schema_ids_are_well_formed(self):
        for _, schema in declared_documents():
            self.assertRegex(schema, SCHEMA_ID)

    def test_schema_is_the_first_key(self):
        for path, _ in declared_documents():
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual("schema", next(iter(payload)), rel_path(path))

    def test_documents_deliberately_left_alone_are_recorded_with_a_reason(self):
        for excluded in load_manifest()["documents_not_stamped"]:
            self.assertIn("path", excluded)
            self.assertTrue(excluded.get("reason"))

    def test_lispvm_index_is_not_stamped(self):
        """Its top level is an agent-id map — a `schema` key would read as an agent."""
        path = BASE_DIR / "state" / "programs" / "_lispvm" / "_index.json"
        if path.is_file():
            self.assertIsNone(schema_for(path))
            self.assertNotIn("schema", json.loads(path.read_text(encoding="utf-8")))

    def test_pinned_world_files_are_not_stamped(self):
        """worlds/** is sha256-pinned by scripts/world_pack_compiler/trust.py."""
        for world_file in sorted((BASE_DIR / "worlds").glob("*/*.json")):
            self.assertIsNone(schema_for(world_file), rel_path(world_file))


class TestTimestamps(unittest.TestCase):
    """§3 — ISO-8601 UTC with Z."""

    def test_meta_last_update_is_iso8601_z(self):
        offenders = []
        for path, _ in declared_documents():
            meta = json.loads(path.read_text(encoding="utf-8")).get("_meta")
            if isinstance(meta, dict) and isinstance(meta.get("lastUpdate"), str):
                if not ISO_Z.match(meta["lastUpdate"]):
                    offenders.append(f"{rel_path(path)}: {meta['lastUpdate']}")
        self.assertEqual([], offenders)


class TestBuildIsPureAndStable(unittest.TestCase):
    """§3 — one build step, idempotent, stable-write."""

    def test_check_mode_passes_on_a_clean_tree(self):
        result = subprocess.run(
            [sys.executable, str(BUILD), "--check"],
            cwd=BASE_DIR, capture_output=True, text=True,
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_build_fetches_nothing(self):
        """A pure function of the manifest plus the bytes already in the repo."""
        source = BUILD.read_text(encoding="utf-8")
        for network in ("urllib.request", "requests", "http.client", "socket"):
            self.assertNotIn(network, source)

    def test_stable_write_preserves_a_timestamp_only_diff(self):
        from static_api import write_json_stable

        scratch = BASE_DIR / "tests" / "__stable_write_probe.json"
        try:
            self.assertTrue(write_json_stable(scratch, {"schema": "x/1.0", "generated": "A"}))
            self.assertFalse(write_json_stable(scratch, {"schema": "x/1.0", "generated": "B"}))
            self.assertEqual("A", json.loads(scratch.read_text(encoding="utf-8"))["generated"])
            self.assertTrue(write_json_stable(scratch, {"schema": "x/1.1", "generated": "B"}))
        finally:
            scratch.unlink(missing_ok=True)


class TestWritersPreserveTheStamp(unittest.TestCase):
    """A stamp that a single tick erases is worse than no stamp at all."""

    WRITERS = (
        "academy_engine", "agent_brain", "agent_dispatch", "apply_deltas",
        "architect_explore", "cleanup_state", "combat_tick", "economy_engine",
        "emergence", "frame_clock", "frame_compile", "game_tick",
        "generate_activity", "generate_chronicles", "generate_state_snapshot",
        "github_llm", "interaction_engine", "npc_agent",
        "reconcile_derived_state", "seed_memory", "self_improve", "slosh_lisp",
        "team_assign", "watershed", "world_growth", "zoo_heartbeat",
    )

    def test_every_state_writer_stamps(self):
        unstamped = [
            name for name in self.WRITERS
            if "stamp_mapping" not in (BASE_DIR / "scripts" / f"{name}.py").read_text(encoding="utf-8")
        ]
        self.assertEqual([], unstamped, f"state writers that would drop the schema string: {unstamped}")

    # (module, enclosing function) pairs that write JSON to a file the manifest
    # does not serve. Each one is a deliberate exclusion recorded in
    # manifest.json under `documents_not_stamped`.
    UNSERVED_WRITE_SITES = {
        ("build_agent_registry.py", "main"),          # agents/*.agent.json
        ("world_growth.py", "_create_agent_registry"),  # agents/*.agent.json
        ("frame_compile.py", "_save_index"),          # state/programs/_lispvm/_index.json
        ("export_legacy_sources.py", "export"),       # a caller-supplied output directory
        ("dreamcatcher_reverse_index.py", "write_json"),  # caller-supplied index/query output
    }

    def test_no_file_write_bypasses_the_stamp(self):
        """Catch the *next* writer that forgets, not just the ones patched here.

        Grepping each module for the string `stamp_mapping` is too weak: a file
        can stamp in one place and bypass it in another, which is exactly how
        `game_tick.main` came to rewrite `state/memory/*.json` unstamped while
        its own `save_json` helper stamped correctly. This walks the AST for
        every call that actually writes JSON to disk — `json.dump(obj, fh)` and
        `path.write_text(json.dumps(...))` — and requires each one to stamp.
        """
        offenders = []
        for path in sorted((BASE_DIR / "scripts").glob("*.py")):
            if path.name in {"static_api.py", "build_static_api.py", "rappid.py"}:
                continue
            if path.name.startswith("test_"):
                continue  # test fixtures write to sandbox copies, not served state
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source)
            enclosing = {}
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    for line in range(node.lineno, (node.end_lineno or node.lineno) + 1):
                        enclosing[line] = node.name

            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                if not self._is_json_file_write(node):
                    continue
                function = enclosing.get(node.lineno, "<module>")
                if (path.name, function) in self.UNSERVED_WRITE_SITES:
                    continue
                if self._stamps(source, node, tree, function):
                    continue
                offenders.append(f"{path.name}:{node.lineno} in {function}()")

        self.assertEqual(
            [], offenders,
            "JSON written to disk without static_api.stamp_mapping — a served "
            "document would lose its schema string on the next tick. Either "
            "stamp it, or add the (module, function) pair to "
            "UNSERVED_WRITE_SITES with a matching entry in manifest.json's "
            f"documents_not_stamped: {offenders}",
        )

    @staticmethod
    def _is_json_file_write(node: ast.Call) -> bool:
        func = node.func
        # json.dump(obj, fh) — the two-argument form is the only one that writes.
        if isinstance(func, ast.Attribute) and func.attr == "dump" and len(node.args) >= 2:
            if isinstance(func.value, ast.Name) and func.value.id == "json":
                return True
        # path.write_text(json.dumps(...))
        if isinstance(func, ast.Attribute) and func.attr == "write_text":
            for arg in ast.walk(node):
                if (
                    isinstance(arg, ast.Attribute)
                    and arg.attr == "dumps"
                    and isinstance(arg.value, ast.Name)
                    and arg.value.id == "json"
                ):
                    return True
        return False

    @staticmethod
    def _stamps(source: str, node: ast.Call, tree: ast.AST, function: str) -> bool:
        if "stamp_mapping" in ast.get_source_segment(source, node):
            return True
        # The `save_json(path, data)` helper pattern: stamp once at the top of
        # the function, then dump. Accept a stamp anywhere in the same function.
        for candidate in ast.walk(tree):
            if not isinstance(candidate, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if candidate.name != function:
                continue
            if candidate.lineno <= node.lineno <= (candidate.end_lineno or candidate.lineno):
                body = ast.get_source_segment(source, candidate) or ""
                if "stamp_mapping" in body:
                    return True
        return False

    def test_stamp_mapping_puts_schema_first_and_is_idempotent(self):
        target = BASE_DIR / "state" / "agents.json"
        once = stamp_mapping({"agents": [], "_meta": {}}, target)
        self.assertEqual("schema", next(iter(once)))
        self.assertEqual("rappterverse-agents/1.0", once["schema"])
        self.assertEqual(once, stamp_mapping(once, target))

    def test_stamp_mapping_leaves_undeclared_documents_alone(self):
        undeclared = BASE_DIR / "state" / "combat_cursor.json"
        self.assertEqual({"a": 1}, stamp_mapping({"a": 1}, undeclared))

    def test_stamp_mapping_tolerates_non_mappings(self):
        self.assertEqual([1, 2], stamp_mapping([1, 2], BASE_DIR / "state" / "agents.json"))

    def test_detect_indent_matches_each_file(self):
        self.assertEqual("    ", detect_indent('{\n    "a": 1\n}'))
        self.assertEqual("  ", detect_indent('{\n  "a": 1\n}'))
        self.assertEqual("    ", detect_indent("{}"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
