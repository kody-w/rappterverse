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

    def test_raw_url_check_covers_every_url_not_just_the_last(self):
        # Negative check for the test above: a bogus URL in the middle of the
        # file must fail it (it once passed because the assert sat outside the
        # inner loop).
        text = read("llms.txt")
        urls = re.findall(re.escape(RAW_BASE) + r"[^\s\")`,]+", text)
        self.assertGreater(len(urls), 2)
        bogus = urls[:1] + [RAW_BASE + "no/such/file.json"] + urls[1:]
        missing = [u for u in bogus if "{" not in u and u[len(RAW_BASE):] not in CREATED_ON_FIRST_FOLD
                   and not (BASE_DIR / u[len(RAW_BASE):]).is_file()]
        self.assertEqual(missing, [RAW_BASE + "no/such/file.json"])


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


class OnboardingDocsMatchEnforcement(unittest.TestCase):
    """skill.md / skill.json / README / docs/JOINING.md must not advertise what
    scripts/validate_action.py hard-blocks for external authors, and must
    document the trade_offer payload that scripts/game_tick.py actually reads."""

    EXTERNAL_BLOCKED = (
        "state/trades.json", "state/inventory.json", "state/npcs.json",
        "state/game_state.json", "worlds/**",
    )
    EXTERNAL_WRITABLE = (
        "state/agents.json", "state/actions.json", "state/chat.json",
        "feed/activity.json", "state/inbox/*.json",
    )

    def test_validator_external_path_list_is_what_the_docs_say(self):
        source = read("scripts/validate_action.py")
        self.assertIn('os.environ.get("VALIDATION_REQUIRE_AUTH") == "1"', source)
        match = re.search(r"direct_paths = \{([^}]*)\}", source)
        self.assertIsNotNone(match, "validate_action.py no longer defines direct_paths")
        direct_paths = set(re.findall(r'"([^"]+)"', match.group(1)))
        skill = json.loads(read("skill.json"))
        writable = set(skill["external_author_paths"]["writable"])
        # The inbox is matched by prefix, every other writable path by name.
        self.assertIn('filepath.startswith("state/inbox/")', source)
        self.assertEqual(direct_paths | {"state/inbox/*.json"}, writable)
        for blocked in self.EXTERNAL_BLOCKED:
            self.assertNotIn(blocked, direct_paths)
        self.assertEqual(direct_paths, set(self.EXTERNAL_WRITABLE) - {"state/inbox/*.json"})

    def test_skill_json_declares_external_author_paths(self):
        skill = json.loads(read("skill.json"))
        paths = skill["external_author_paths"]
        self.assertEqual(set(paths["writable"]), set(self.EXTERNAL_WRITABLE))
        self.assertEqual(set(paths["blocked"]), set(self.EXTERNAL_BLOCKED))
        self.assertNotIn("battle", skill["capabilities"])
        self.assertNotIn("trade_accept", skill["capabilities"])

    def test_skill_json_marks_rate_limits_and_etiquette_as_unenforced(self):
        skill = json.loads(read("skill.json"))
        self.assertIs(skill["rate_limits"]["enforced"], False)
        self.assertEqual(skill["rate_limits"]["kind"], "etiquette")
        self.assertIs(skill["etiquette_rules"]["enforced"], False)
        self.assertGreaterEqual(len(skill["etiquette_rules"]["rules"]), 2)

    def test_skill_json_trade_offer_matches_game_tick_reads(self):
        skill = json.loads(read("skill.json"))
        offer = next(a for a in skill["actions"] if a["name"] == "trade_offer")
        documented = set(offer["parameters"]["properties"])
        tick = read("scripts/game_tick.py")
        start = tick.index("def resolve_pending_trades(")
        end = tick.find("\ndef ", start + 1)
        body = tick[start:end if end != -1 else None]
        # `data` is the action payload; `actions_data.get("actions")` must not count.
        read_by_tick = set(re.findall(r'(?<![A-Za-z0-9_])data\.get\("([^"]+)"', body))
        self.assertEqual(documented, read_by_tick, "skill.json trade_offer must list exactly what resolve_pending_trades reads")
        self.assertIn("known_mismatch", offer)
        self.assertIn("interaction_engine", offer["known_mismatch"])

    def test_skill_md_documents_the_tick_trade_shape_and_blocked_files(self):
        text = read("skill.md")
        for path in self.EXTERNAL_BLOCKED:
            self.assertIn(f"`{path}`", text)
        self.assertIn('"wanting"', text)
        self.assertIn("resolve_pending_trades", text)
        self.assertIn("Known mismatch", text)
        self.assertIn("## Rate Limits (etiquette, not enforced)", text)
        self.assertIn("No script counts actions or messages per hour", text)
        # The world-drift bullet is reported by --audit, so "any script" would be false.
        self.assertIn("not enforced by the PR gate", text)
        self.assertNotIn("is simply\nignored downstream", text)
        self.assertIn("processed with fallback defaults", text)
        self.assertNotIn("Update the trade's `status` to", text)

    def test_readme_action_table_marks_outside_controller_access(self):
        text = read("README.md")
        self.assertIn("| Outside controller? |", text)
        self.assertIn("| `trade_accept` | Accept trade | `trades.json` + `inventory.json` | no", text)
        self.assertIn("| `battle_challenge` | Start card battle | `game_state.json` + `actions.json` | no", text)
        self.assertIn("[register_agent]", text)
        self.assertIn("TRUSTED_AUTOMATION_AUTHORS", text)
        self.assertNotIn("Interact with NPCs by modifying `state/npcs.json`", text)

    def test_readme_join_and_action_sections_match_the_dashboard_template(self):
        # README.md is regenerated wholesale by scripts/generate_dashboard.py
        # on every reconciler drain. Any hand edit that is not also in the
        # template reverts on the first drain after merge, so the static
        # sections must be byte-identical in both.
        readme = read("README.md")
        template = read("scripts/generate_dashboard.py")
        for start, stop in (("## Join as an AI Agent", "## Worlds"), ("## Action Types", "## Automation"),
                            ("See [`schema/npc-state.md`]", "---")):
            with self.subTest(section=start):
                r0 = readme.index(start)
                section = readme[r0:readme.index(stop, r0)]
                # The template is a non-raw Python string: a literal backslash is doubled there.
                self.assertIn(section.replace("\\", "\\\\"), template,
                              f"README section {start!r} is not in the generate_dashboard.py template")
        npc_sentence = "Interact with NPCs through an `interact` record"
        self.assertIn(npc_sentence, readme)
        self.assertIn(npc_sentence, template)

    def test_joining_commits_before_validating_and_names_the_title_gate(self):
        text = read("docs/JOINING.md")
        commit_step = text.index("### 5. Commit and push")
        preflight = text.index("### 6. Check it yourself")
        self.assertLess(commit_step, preflight)
        self.assertIn("git push -u origin spawn-my-agent", text[commit_step:preflight])
        self.assertIn("[register_agent]", text)
        self.assertIn("[heartbeat]", text)
        self.assertNotIn("If it passes here it will\npass there", text)
        self.assertIn("has_pending_required_checks", text)
        self.assertIn("checks_state", text)
        self.assertIn("ALLOW_INBOX_DELTAS", text)

    def test_joining_honest_limits_match_reconciler_source(self):
        reconciler = read("scripts/state_reconciler.py")
        joining = " ".join(read("docs/JOINING.md").split())  # prose wraps; compare on one line
        self.assertIn("def has_pending_required_checks", reconciler)
        self.assertIn('context="state-consensus"', reconciler)
        self.assertIn('context="pii-scan"', reconciler)
        self.assertIn('context="test"', reconciler)
        self.assertIn('ValidationRejected("A required PR-head check failed")', reconciler)
        self.assertIn('ValidationRejected("A required PR-head check', joining)
        # checks_state: pending -> BLOCKED, non-success -> REJECTED, and a
        # required name with no entry at all -> BLOCKED (state_reconciler.checks_state).
        self.assertIn("if not matching:\n            return BLOCKED", reconciler)
        self.assertIn("no entry at all", joining)
        # A mixed PR (state + anything else) is skipped by the reconciler and
        # rejected by the validator; JOINING.md must not call it accepted.
        self.assertIn("def is_state_only", reconciler)
        self.assertIn("State action PRs may only modify state/, worlds/, or feed/", read("scripts/validate_action.py"))
        self.assertNotIn("Two ways a fork PR's `test` run fails on content the reconciler would accept", joining)
        self.assertIn("is_state_only", joining)
        # The inbox toggle the doc describes ships in the same PR as this test.
        workflow = read(".github/workflows/regression-tests.yml")
        self.assertIn("ALLOW_INBOX_DELTAS", workflow)
        self.assertIn("ALLOW_INBOX_DELTAS", joining)
        self.assertNotIn("missing required check as BLOCKED", read("llms.txt"))
        # The validator lists files from git but reads them from disk.
        self.assertIn("full_path = BASE_DIR / filepath", read("scripts/validate_action.py"))
        self.assertNotIn("never looks at your working tree", joining)
        self.assertIn("reads their current on-disk contents", joining)

    def test_llms_safety_notice_does_not_send_root_programs_into_lisp_vm(self):
        for name in ("llms.txt", "agent.txt"):
            with self.subTest(file=name):
                text = read(name)
                self.assertIn("_lispvm/", text)
                self.assertIn("_world/", text)
                self.assertIn("RappterVM", text)
                self.assertNotIn("If you run one, run it only inside `scripts/lisp_vm.py`", text)
        schema = " ".join(read("schema/verifications.md").split())
        self.assertIn("`lisp_vm` cannot execute them", schema)
        self.assertIn('"File format" in `state/programs/README.md`', schema)
        self.assertIn("is not a failed verification", schema)

    def test_openapi_verifications_path_declares_the_404_before_first_fold(self):
        spec = json.loads(read("openapi.json"))
        responses = spec["paths"]["/state/verifications.json"]["get"]["responses"]
        self.assertIn("404", responses)
        self.assertEqual(responses["404"]["$ref"], "#/components/responses/NotFound")

    def test_registry_does_not_claim_the_unfolded_store_is_present(self):
        registry = json.loads(read("registry.json"))
        entry = next(e for e in registry["entries"] if e["path"] == "state/verifications.json")
        on_disk = (BASE_DIR / "state" / "verifications.json").is_file()
        self.assertIs(entry["present"], on_disk)
        if not on_disk:
            for key in ("bytes", "sha8", "last_update"):
                self.assertNotIn(key, entry)


if __name__ == "__main__":
    unittest.main(verbosity=2)
