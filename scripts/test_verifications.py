#!/usr/bin/env python3
"""Tests for the peer verification primitive and every path that writes it.

Covers scripts/verifications.py (record rules, scoring, store round trip),
the inbox fold in scripts/apply_deltas.py, the direct-PR fold in
scripts/reconcile_derived_state.py, and the validators' agreement on the
action-type list. Everything runs against temporary state directories.
"""

from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
BASE_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))

import action_types  # noqa: E402
import apply_deltas  # noqa: E402
import slosh_lisp  # noqa: E402
import verifications  # noqa: E402

SUBJECT_A = "sha256:" + "a" * 64
SUBJECT_B = "sha256:" + "b" * 64


def vote(verifier: str, subject: str = SUBJECT_A, passed: bool = True, **extra) -> dict:
    rec = {
        "schema": "rapp-verification/1",
        "verifier": verifier,
        "agent_id": f"{verifier}-agent-001",
        "subject": subject,
        "subject_kind": "program",
        "environment": "lispvm 0.4 / test",
        "passed": passed,
        "notes": "" if passed else "reproducible failure: loops on empty inventory",
        "at": "2026-10-13T01:02:03Z",
    }
    rec.update(extra)
    return rec


def verify_action(agent_id: str, verifier: str, subject: str, passed: bool = True,
                  action_id: str = "act-1", at: str = "2026-10-13T03:00:00Z", **data) -> dict:
    payload = {
        "verifier": verifier,
        "subject": subject,
        "subject_kind": "program",
        "environment": "lispvm 0.4 / test",
        "passed": passed,
        "notes": "" if passed else "broke after the rename",
    }
    payload.update(data)
    return {
        "id": action_id, "timestamp": at, "agentId": agent_id,
        "type": "verify", "world": "hub", "data": payload,
    }


class ScoreMathTests(unittest.TestCase):
    def test_wilson_lower_bound_matches_hand_computed_values(self) -> None:
        # z = 1.959964, z^2 = 3.841459.
        # 1 of 1: (1 + z^2/2 - z^2/2) / (1 + z^2) = 1 / 4.841459 = 0.206549
        store = {"verifications": []}
        verifications.record(store, vote("alice"))
        self.assertAlmostEqual(verifications.score(store, SUBJECT_A)["score"], 0.2065, places=4)

        # 5 of 5: 1 / (1 + z^2/5) = 1 / 1.7682918 = 0.565518
        for name in ("bob", "carol", "dave", "erin"):
            verifications.record(store, vote(name))
        result = verifications.score(store, SUBJECT_A)
        self.assertEqual((result["pass_count"], result["fail_count"], result["votes"]), (5, 0, 5))
        self.assertAlmostEqual(result["score"], 0.5655, places=4)
        self.assertFalse(result["hidden"])

    def test_no_votes_scores_zero(self) -> None:
        result = verifications.score({"verifications": []}, SUBJECT_B)
        self.assertEqual(result["votes"], 0)
        self.assertEqual(result["score"], 0.0)
        self.assertFalse(result["hidden"])
        self.assertFalse(verifications.is_hidden({"verifications": []}, SUBJECT_B))


class ContentIdTests(unittest.TestCase):
    def test_content_id_shape(self) -> None:
        cid = verifications.content_id("(say hi)")
        self.assertRegex(cid, r"^sha256:[0-9a-f]{64}$")
        self.assertEqual(cid, verifications.content_id("(say hi)"))
        self.assertNotEqual(cid, verifications.content_id("(say bye)"))

    def test_bytes_hash_as_is_so_crlf_files_match_sha256sum(self) -> None:
        crlf = b";; hdr\r\n(do nil)\r\n"
        expected = "sha256:" + hashlib.sha256(crlf).hexdigest()
        self.assertEqual(verifications.content_id(crlf), expected)
        self.assertNotEqual(verifications.content_id(crlf.decode().replace("\r\n", "\n")), expected)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "x.lisp"
            path.write_bytes(crlf)
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                verifications._main(["content-id", str(path)])
            self.assertEqual(out.getvalue().strip(), expected)
        with self.assertRaises(TypeError):
            verifications.content_id(42)


class RecordRuleTests(unittest.TestCase):
    def test_revote_replaces_earlier_vote_in_place(self) -> None:
        store = {"verifications": []}
        verifications.record(store, vote("alice", passed=True))
        verifications.record(store, vote("bob", passed=True))
        verifications.record(store, vote("alice", passed=False, at="2026-10-14T00:00:00Z"))
        self.assertEqual(len(store["verifications"]), 2)
        self.assertEqual(store["verifications"][0]["verifier"], "alice")
        self.assertFalse(store["verifications"][0]["passed"])
        self.assertEqual(store["verifications"][0]["at"], "2026-10-14T00:00:00Z")
        result = verifications.score(store, SUBJECT_A)
        self.assertEqual((result["pass_count"], result["fail_count"]), (1, 1))

    def test_revote_dedupes_case_insensitively(self) -> None:
        store = {"verifications": []}
        verifications.record(store, vote("Alice"))
        verifications.record(store, vote("alice", passed=False))
        self.assertEqual(len(store["verifications"]), 1)
        self.assertIsNotNone(verifications.find_vote(store, "ALICE", SUBJECT_A))

    def test_self_verify_is_rejected_from_every_owner_source(self) -> None:
        with self.assertRaisesRegex(ValueError, "self-verify"):
            verifications.record({"verifications": []}, vote("alice"), subject_owner="alice")
        with self.assertRaisesRegex(ValueError, "self-verify"):
            verifications.record({"verifications": []}, vote("alice"), {SUBJECT_A: "alice"})
        with self.assertRaisesRegex(ValueError, "self-verify"):
            verifications.record({"verifications": []}, vote("alice"), {SUBJECT_A: {"bob", "alice"}})
        with self.assertRaisesRegex(ValueError, "self-verify"):
            verifications.record(
                {"verifications": [], "subjects": {SUBJECT_A: {"owner": "alice"}}},
                vote("alice"),
            )
        with self.assertRaisesRegex(ValueError, "self-verify"):
            verifications.record({"verifications": []}, vote("alice", subject_owner="alice"))
        # Case differences do not evade it (GitHub logins are case-insensitive).
        with self.assertRaisesRegex(ValueError, "self-verify"):
            verifications.record({"verifications": []}, vote("Alice"), subject_owner="alice")
        # Another controller's subject is fine, and the keyword alias still works.
        store = verifications.record({"verifications": []}, vote("alice"), subject_owner="bob")
        self.assertEqual(len(store["verifications"]), 1)
        store = verifications.record({"verifications": []}, vote("alice"), subject_owners={SUBJECT_A: "bob"})
        self.assertEqual(len(store["verifications"]), 1)

    def test_declared_subject_owner_never_clears_a_vote(self) -> None:
        # A voter cannot name someone else as owner to get past require_owner.
        with self.assertRaisesRegex(ValueError, "not a known artifact"):
            verifications.record({"verifications": []}, vote("alice", subject_owner="bob"), require_owner=True)

    def test_require_owner_fails_closed_on_unknown_subjects(self) -> None:
        with self.assertRaisesRegex(ValueError, "not a known artifact"):
            verifications.record({"verifications": []}, vote("alice"), require_owner=True)
        store = verifications.record(
            {"verifications": []}, vote("alice"), {SUBJECT_A: "bob"}, require_owner=True,
        )
        # The binding is remembered, so a later vote on the same subject still
        # resolves (and bob still cannot vote) even without the map.
        self.assertEqual(store["subjects"][SUBJECT_A], {"owner": "bob", "kind": "program"})
        verifications.record(store, vote("carol"), require_owner=True)
        with self.assertRaisesRegex(ValueError, "self-verify"):
            verifications.record(store, vote("bob"), require_owner=True)

    def test_multiple_controllers_can_own_one_subject(self) -> None:
        store = verifications.record(
            {"verifications": []}, vote("carol"), {SUBJECT_A: ["bob", "alice"]}, require_owner=True,
        )
        self.assertEqual(store["subjects"][SUBJECT_A]["owners"], ["alice", "bob"])
        for owner in ("alice", "bob"):
            with self.assertRaisesRegex(ValueError, "self-verify"):
                verifications.record(store, vote(owner), require_owner=True)

    def test_system_is_not_a_verifier(self) -> None:
        with self.assertRaisesRegex(ValueError, "system"):
            verifications.record({"verifications": []}, vote("system"))
        with self.assertRaisesRegex(ValueError, "system"):
            verifications.record({"verifications": []}, vote("SYSTEM"))

    def test_hide_threshold_needs_five_votes_and_under_twenty_percent(self) -> None:
        store = {"verifications": []}
        for name in ("alice", "bob", "carol", "dave"):
            verifications.record(store, vote(name, passed=False))
        self.assertFalse(verifications.is_hidden(store, SUBJECT_A))  # 4 votes: not yet
        verifications.record(store, vote("erin", passed=True))
        self.assertFalse(verifications.is_hidden(store, SUBJECT_A))  # 1/5 = 0.20, not < 0.20
        verifications.record(store, vote("erin", passed=False))
        self.assertTrue(verifications.is_hidden(store, SUBJECT_A))  # 0/5
        self.assertTrue(verifications.score(store, SUBJECT_A)["hidden"])

    def test_notes_required_when_failed(self) -> None:
        for notes in ("", "   ", None):
            with self.subTest(notes=repr(notes)):
                with self.assertRaisesRegex(ValueError, "notes"):
                    verifications.record({"verifications": []}, vote("alice", passed=False, notes=notes))
        store = verifications.record({"verifications": []}, vote("alice", passed=True, notes=""))
        self.assertEqual(len(store["verifications"]), 1)

    def test_malformed_records_are_rejected(self) -> None:
        bad = {
            "subject": vote("alice", subject="sha1:abc"),
            "kind": vote("alice", subject_kind="meme"),
            "kind-without-resolver": vote("alice", subject_kind="chronicle"),
            "schema": vote("alice", schema="rapp-verification/0"),
            "environment": vote("alice", environment="x" * 101),
            "notes": vote("alice", notes="n" * 1001),
            "at": vote("alice", at="yesterday"),
            "passed": vote("alice", passed="yes"),
        }
        for label, rec in bad.items():
            with self.subTest(label=label):
                with self.assertRaises(ValueError):
                    verifications.record({"verifications": []}, rec)

    def test_record_from_action_maps_envelope_and_data(self) -> None:
        rec = verifications.record_from_action(verify_action("a-1", "alice", SUBJECT_A, subject_owner="bob"))
        self.assertEqual(rec["agent_id"], "a-1")
        self.assertEqual(rec["at"], "2026-10-13T03:00:00Z")
        self.assertEqual(rec["verifier"], "alice")
        self.assertEqual(rec["subject_owner"], "bob")
        self.assertEqual(rec["schema"], verifications.RECORD_SCHEMA)


class StoreRoundTripTests(unittest.TestCase):
    def test_save_then_load_keeps_schema_first_and_counts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state" / "verifications.json"
            store = verifications.load(path)  # missing file -> empty store
            self.assertEqual(store["verifications"], [])
            verifications.record(store, vote("alice"))
            verifications.record(store, vote("bob", subject=SUBJECT_B))
            verifications.save(store, path)
            text = path.read_text(encoding="utf-8")
            self.assertTrue(text.endswith("\n"))
            self.assertEqual(next(iter(json.loads(text))), "schema")
            reloaded = verifications.load(path)
            self.assertEqual(reloaded["schema"], verifications.DOC_SCHEMA)
            self.assertEqual(reloaded["_meta"]["verificationCount"], 2)
            self.assertEqual(reloaded["_meta"]["subjectCount"], 2)

    def test_corrupt_store_raises_instead_of_loading_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "verifications.json"
            path.write_text("{not json", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "unreadable"):
                verifications.load(path)
            path.write_text("[]", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "unreadable"):
                verifications.load(path)


class TempStateMixin:
    """A tiny state/ tree with two controllers and one program each."""

    def make_state(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.root = root
        self.state_dir = root / "state"
        (self.state_dir / "programs").mkdir(parents=True)
        (self.state_dir / "inbox").mkdir()
        self.bob_program = (
            ";; authored by Bob's twin\n\n"
            "(do (if (< (rand) 0.1) (emote \"bob-agent-001\" \"wave\") nil))\n"
        )
        self.alice_program = (
            ";; authored by Alice's twin\n\n"
            "(do (if (< (rand) 0.2) (emote \"alice-agent-001\" \"nod\") nil))\n"
        )
        (self.state_dir / "programs" / "bob-agent-001.lisp").write_text(self.bob_program, encoding="utf-8")
        (self.state_dir / "programs" / "alice-agent-001.lisp").write_text(self.alice_program, encoding="utf-8")
        (self.state_dir / "agents.json").write_text(json.dumps({
            "agents": [
                {"id": "alice-agent-001", "controller": "alice"},
                {"id": "bob-agent-001", "controller": "bob"},
                {"id": "npc-001", "controller": "system"},
            ],
            "_meta": {"agentCount": 3},
        }), encoding="utf-8")
        self.bob_file_id, self.bob_body_id = slosh_lisp.program_subjects(self.bob_program.encode("utf-8"))
        self.alice_file_id, self.alice_body_id = slosh_lisp.program_subjects(self.alice_program.encode("utf-8"))

    def cleanup_state(self):
        self._tmp.cleanup()


class ApplyDeltasFoldTests(TempStateMixin, unittest.TestCase):
    def setUp(self) -> None:
        self.make_state()
        self._saved_state_dir = apply_deltas.STATE_DIR
        apply_deltas.STATE_DIR = self.state_dir

    def tearDown(self) -> None:
        apply_deltas.STATE_DIR = self._saved_state_dir
        self.cleanup_state()

    def write_delta(self, delta: dict) -> Path:
        path = self.state_dir / "inbox" / "delta-1.json"
        path.write_text(json.dumps(delta), encoding="utf-8")
        return path

    def apply(self, delta: dict) -> tuple:
        stats = {"actions": 0, "messages": 0, "agents": 0, "objects": 0, "activities": 0, "verifications": 0}
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            applied = apply_deltas.apply_delta(self.write_delta(delta), stats)
        return applied, stats, out.getvalue()

    def test_verifications_delta_folds_into_temp_store(self) -> None:
        delta = {
            "agent_id": "alice-agent-001",
            "controller": "alice",
            "timestamp": "2026-10-13T02:00:00Z",
            "verifications": [
                vote("alice", subject=self.bob_file_id, passed=True),       # valid
                vote("alice", subject=self.alice_body_id, passed=True),     # self-verify via body id
                vote("bob", subject=self.bob_file_id, passed=True),         # not the delta controller
                vote("alice", subject=SUBJECT_B, passed=False, notes=""),   # fail without notes
                "not a record",                                             # unknown shape
                vote("alice", subject="sha256:nope"),                       # malformed subject
                vote("alice", subject=SUBJECT_A, passed=True),              # unknown artifact
            ],
        }
        self.assertTrue(apply_deltas.has_meaningful_content(delta))
        applied, stats, log = self.apply(delta)
        self.assertTrue(applied)
        self.assertEqual(stats["verifications"], 1)
        self.assertIn("self-verify", log)
        self.assertIn("must be the delta controller", log)
        self.assertIn("notes", log)
        self.assertIn("not an object", log)
        self.assertIn("subject", log)
        self.assertIn("not a known artifact", log)

        store_path = self.state_dir / "verifications.json"
        self.assertTrue(store_path.is_file())
        store = json.loads(store_path.read_text(encoding="utf-8"))
        self.assertEqual(next(iter(store)), "schema")
        self.assertEqual(store["schema"], verifications.DOC_SCHEMA)
        self.assertEqual([v["verifier"] for v in store["verifications"]], ["alice"])
        self.assertEqual(store["subjects"][self.bob_file_id]["owner"], "bob")
        self.assertEqual(store["_meta"]["verificationCount"], 1)
        self.assertEqual(store["_meta"]["lastUpdate"], "2026-10-13T02:00:00Z")

        # A second delta re-voting replaces, never duplicates, and verify actions fold too.
        second = {
            "agent_id": "alice-agent-001",
            "controller": "alice",
            "timestamp": "2026-10-13T03:00:00Z",
            "actions": [verify_action("alice-agent-001", "alice", self.bob_file_id, passed=False)],
        }
        (self.state_dir / "actions.json").write_text(json.dumps({"actions": []}), encoding="utf-8")
        applied, stats, _ = self.apply(second)
        self.assertTrue(applied)
        self.assertEqual(stats["verifications"], 1)
        store = json.loads(store_path.read_text(encoding="utf-8"))
        self.assertEqual(len(store["verifications"]), 1)
        self.assertFalse(store["verifications"][0]["passed"])

    def test_owner_vote_on_body_id_is_rejected_end_to_end(self) -> None:
        # Bob edits only his header: the file id changes, the body id does not,
        # and Bob still cannot pass-vote either id.
        edited = self.bob_program.replace("Bob's twin", "Bob's other twin")
        (self.state_dir / "programs" / "bob-agent-001.lisp").write_text(edited, encoding="utf-8")
        new_file_id, body_id = slosh_lisp.program_subjects(edited.encode("utf-8"))
        self.assertNotEqual(new_file_id, self.bob_file_id)
        self.assertEqual(body_id, self.bob_body_id)
        delta = {
            "agent_id": "bob-agent-001", "controller": "bob", "timestamp": "2026-10-13T02:00:00Z",
            "verifications": [vote("bob", subject=body_id), vote("bob", subject=new_file_id)],
        }
        applied, stats, log = self.apply(delta)
        self.assertFalse(applied)
        self.assertEqual(stats["verifications"], 0)
        self.assertEqual(log.count("self-verify"), 2)
        # Whitespace-only edits map to the same body id, so neither does that launder it.
        spaced = edited.replace("(do (if", "(do  (if")
        self.assertEqual(slosh_lisp.program_subjects(spaced.encode("utf-8"))[1], body_id)

    def test_system_delta_cannot_vote(self) -> None:
        delta = {
            "agent_id": "npc-001", "controller": "system", "timestamp": "2026-10-13T02:00:00Z",
            "verifications": [vote("system", subject=self.bob_file_id)],
        }
        applied, stats, log = self.apply(delta)
        self.assertFalse(applied)
        self.assertIn("system", log)

    def test_corrupt_store_is_never_overwritten(self) -> None:
        store_path = self.state_dir / "verifications.json"
        store_path.write_text("{broken", encoding="utf-8")
        delta = {
            "agent_id": "alice-agent-001", "controller": "alice", "timestamp": "2026-10-13T02:00:00Z",
            "verifications": [vote("alice", subject=self.bob_file_id)],
        }
        applied, stats, log = self.apply(delta)
        self.assertFalse(applied)
        self.assertIn("unreadable", log)
        self.assertEqual(store_path.read_text(encoding="utf-8"), "{broken")

    def test_delta_with_only_bad_verifications_does_not_crash_or_write(self) -> None:
        delta = {
            "agent_id": "alice-agent-001",
            "controller": "alice",
            "timestamp": "2026-10-13T02:00:00Z",
            "verifications": [vote("alice", subject="sha256:short"), 42],
        }
        applied, stats, log = self.apply(delta)
        self.assertFalse(applied)
        self.assertEqual(stats["verifications"], 0)
        self.assertIn("Skipping verification", log)
        self.assertFalse((self.state_dir / "verifications.json").exists())


class ReconcileFoldTests(TempStateMixin, unittest.TestCase):
    """Direct state/actions.json PRs: the reconciler folds verify actions."""

    def setUp(self) -> None:
        self.make_state()
        spec = importlib.util.spec_from_file_location(
            "reconcile_derived_state_under_test", SCRIPT_DIR / "reconcile_derived_state.py",
        )
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)

    def tearDown(self) -> None:
        self.cleanup_state()

    def fold(self, actions: list) -> tuple:
        agents = json.loads((self.state_dir / "agents.json").read_text(encoding="utf-8"))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            changed = self.module.fold_verify_actions(self.root, agents, {"actions": actions})
        return changed, out.getvalue()

    def test_verify_actions_fold_once_and_idempotently(self) -> None:
        actions = [
            verify_action("alice-agent-001", "alice", self.bob_file_id, action_id="act-1"),
            verify_action("bob-agent-001", "bob", self.alice_body_id, passed=False, action_id="act-2"),
            verify_action("bob-agent-001", "bob", self.bob_body_id, action_id="act-3"),      # self-verify
            verify_action("alice-agent-001", "mallory", self.bob_file_id, action_id="act-4"),  # wrong verifier
            verify_action("npc-001", "system", self.bob_file_id, action_id="act-5"),          # system
            verify_action("alice-agent-001", "alice", SUBJECT_A, action_id="act-6"),           # unknown
        ]
        changed, log = self.fold(actions)
        self.assertTrue(changed)
        self.assertIn("self-verify", log)
        self.assertIn("not the actor's controller", log)
        self.assertIn("no peer controller", log)
        self.assertIn("not a known artifact", log)
        store = verifications.load(self.state_dir / "verifications.json")
        self.assertEqual(
            sorted((v["verifier"], v["subject"]) for v in store["verifications"]),
            sorted([("alice", self.bob_file_id), ("bob", self.alice_body_id)]),
        )
        self.assertEqual(next(iter(json.loads((self.state_dir / "verifications.json").read_text()))), "schema")
        # Second pass: nothing changes, nothing written.
        changed, _ = self.fold(actions)
        self.assertFalse(changed)

    def test_window_action_never_overwrites_a_newer_live_vote(self) -> None:
        store = verifications.load(self.state_dir / "verifications.json")
        verifications.record(store, vote("alice", subject=self.bob_file_id, passed=False,
                                          at="2026-10-20T00:00:00Z"), {self.bob_file_id: "bob"})
        verifications.save(store, self.state_dir / "verifications.json")
        changed, _ = self.fold([verify_action("alice-agent-001", "alice", self.bob_file_id,
                                              at="2026-10-13T03:00:00Z")])
        self.assertFalse(changed)
        store = verifications.load(self.state_dir / "verifications.json")
        self.assertFalse(store["verifications"][0]["passed"])

    def test_no_verify_actions_means_no_store(self) -> None:
        changed, _ = self.fold([{"id": "a", "type": "move", "agentId": "alice-agent-001", "data": {}}])
        self.assertFalse(changed)
        self.assertFalse((self.state_dir / "verifications.json").exists())


class ValidatorAgreementTests(unittest.TestCase):
    def test_both_validators_share_one_action_type_list(self) -> None:
        import validate_action
        import validate_delta
        self.assertIs(validate_action.VALID_ACTION_TYPES, action_types.VALID_ACTION_TYPES)
        self.assertIs(validate_delta.VALID_ACTION_TYPES, action_types.VALID_ACTION_TYPES)
        self.assertIn("verify", action_types.VALID_ACTION_TYPES)

    def test_validate_delta_counts_verifications_as_content(self) -> None:
        import validate_delta
        self.assertTrue(validate_delta.has_meaningful_content({"verifications": [vote("alice")]}))
        self.assertFalse(validate_delta.has_meaningful_content({"verifications": []}))


if __name__ == "__main__":
    unittest.main(verbosity=2)
