#!/usr/bin/env python3
"""Keep the agent discovery layer (llms.txt, agent.txt, openapi.json,
.well-known/ai-plugin.json) resolvable and honest.

Pages is served from docs/ (manifest.json `pages_dir`), so every file the
discovery layer links under https://kody-w.github.io/rappterverse/ must exist
under docs/ byte-identical to its repo-root original, every JSON file must
parse, and the action-type list llms.txt publishes must be the one the
validators enforce (scripts/action_types.py).
"""

from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
BASE_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))

import action_types  # noqa: E402

PAGES_BASE = "https://kody-w.github.io/rappterverse/"
RAW_BASE = "https://raw.githubusercontent.com/kody-w/rappterverse/main/"
# state/ files are never created by a code PR; the folds create this one on main.
CREATED_ON_FIRST_FOLD = {"state/verifications.json"}
MIRRORED = ("llms.txt", "agent.txt", "openapi.json", ".well-known/ai-plugin.json")
JSON_FILES = ("openapi.json", ".well-known/ai-plugin.json", "skill.json", "manifest.json")


def read(path: str) -> str:
    return (BASE_DIR / path).read_text(encoding="utf-8")


def pages_dir() -> Path:
    manifest = json.loads(read("manifest.json"))
    return BASE_DIR / manifest.get("pages_dir", "docs")


class JsonParses(unittest.TestCase):
    def test_every_discovery_json_file_parses(self):
        for name in JSON_FILES:
            with self.subTest(file=name):
                json.loads(read(name))


class PagesMirrors(unittest.TestCase):
    def test_root_files_are_mirrored_byte_identical_under_pages_dir(self):
        docs = pages_dir()
        for name in MIRRORED:
            with self.subTest(file=name):
                source = (BASE_DIR / name).read_bytes()
                mirror = docs / name
                self.assertTrue(mirror.is_file(), f"{mirror} missing: cp {name} {docs.name}/{name}")
                self.assertEqual(source, mirror.read_bytes(), f"{name} and {mirror} differ")

    def test_nojekyll_so_the_dot_directory_is_served(self):
        self.assertTrue((pages_dir() / ".nojekyll").is_file())

    def test_every_pages_url_in_discovery_files_resolves_to_a_committed_path(self):
        docs = pages_dir()
        for name in ("llms.txt", "agent.txt", ".well-known/ai-plugin.json"):
            for url in re.findall(re.escape(PAGES_BASE) + r"[^\s\")`,]+", read(name)):
                rel = url[len(PAGES_BASE):]
                with self.subTest(file=name, url=url):
                    self.assertTrue((docs / rel).is_file(), f"{url} -> {docs / rel} missing")

    def test_every_raw_url_in_discovery_files_resolves_to_a_committed_path(self):
        for name in ("llms.txt", "agent.txt"):
            for url in re.findall(re.escape(RAW_BASE) + r"[^\s\")`,]+", read(name)):
                rel = url[len(RAW_BASE):]
                if "{" in rel:
                    continue  # templated endpoint
                with self.subTest(file=name, url=url):
                    if rel in CREATED_ON_FIRST_FOLD:
                        continue  # 404s until the first vote is folded on main; documented as such
            self.assertTrue((BASE_DIR / rel).is_file(), f"{url} -> {rel} missing")


class PluginManifest(unittest.TestCase):
    def test_api_url_points_at_the_mirrored_openapi(self):
        plugin = json.loads(read(".well-known/ai-plugin.json"))
        self.assertEqual(plugin["api"]["type"], "openapi")
        self.assertEqual(plugin["api"]["url"], PAGES_BASE + "openapi.json")
        spec = json.loads(read("openapi.json"))
        self.assertTrue(spec["openapi"].startswith("3."))
        self.assertIn("/state/verifications.json", spec["paths"])
        self.assertEqual(
            spec["servers"][0]["url"].rstrip("/") + "/", RAW_BASE,
        )

    def test_description_names_both_issue_actions(self):
        plugin = json.loads(read(".well-known/ai-plugin.json"))
        text = plugin["description_for_model"]
        self.assertIn("[register_agent]", text)
        self.assertIn("[heartbeat]", text)


class PublishedLimitsMatchEnforcement(unittest.TestCase):
    def test_llms_action_type_list_is_the_enforced_one(self):
        match = re.search(r"Action `type` must be one of `([^`]+)`", read("llms.txt"))
        self.assertIsNotNone(match, "llms.txt no longer states the action-type enum")
        published = match.group(1).split()
        self.assertEqual(published, list(action_types.ACTION_TYPES_IN_DOC_ORDER))
        self.assertIn("scripts/action_types.py", read("llms.txt"))

    def test_openapi_action_enum_is_the_enforced_one(self):
        spec = json.loads(read("openapi.json"))
        enum = spec["components"]["schemas"]["Action"]["properties"]["type"]["enum"]
        self.assertEqual(set(enum), set(action_types.VALID_ACTION_TYPES))

    def test_llms_world_bounds_match_world_configs(self):
        text = read("llms.txt")
        for world in ("hub", "arena", "marketplace", "gallery", "dungeon"):
            bounds = json.loads(read(f"worlds/{world}/config.json"))["bounds"]
            expected = f"- {world}: x {bounds['x'][0]}..{bounds['x'][1]}, z {bounds['z'][0]}..{bounds['z'][1]}"
            with self.subTest(world=world):
                self.assertIn(expected, text)

    def test_llms_does_not_claim_outsider_verification(self):
        self.assertNotIn("an outside account has exercised", read("llms.txt"))

    def test_verifications_store_is_declared_in_the_manifest(self):
        manifest = json.loads(read("manifest.json"))
        entry = next(e for e in manifest["entries"] if e["path"] == "state/verifications.json")
        self.assertEqual(entry["schema"], "rappterverse-verifications/1.0")
        self.assertTrue((BASE_DIR / entry["doc"]).is_file())
        # The store is created on main by the first fold (reconcile_derived_state /
        # apply_deltas), never by a code PR: files under state/ are agent-action
        # territory. Until then load() must yield an empty store with the schema.
        import verifications
        store_path = BASE_DIR / "state" / "verifications.json"
        if store_path.is_file():
            store = json.loads(read("state/verifications.json"))
        else:
            store = verifications.load(store_path)
        self.assertEqual(next(iter(store)), "schema")
        self.assertEqual(store["schema"], entry["schema"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
