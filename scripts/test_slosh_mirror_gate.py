#!/usr/bin/env python3
"""Tests for the Lispy Mirror verification gate in ``slosh_lisp.py``.

A self-authored ``state/programs/<agentId>.lisp`` is used verbatim unless peer
verification has hidden it (5+ voters, under 20% passed). A program answers to
two subjects: the file id (``sha256sum`` of the bytes as shipped) and the body
id (content id of the canonical, comment- and whitespace-normalised body), so
a verdict follows the program through header edits and reformatting. These
tests run against a temporary state directory and never touch repo state.
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import slosh_lisp as slosh  # noqa: E402
import verifications  # noqa: E402
import lisp_vm  # noqa: E402

AGENT = "mirror-test-001"
OTHER = "mirror-test-002"
HEADER = (
    ";; authored by Test Twin at 2026-10-12T00:00:00Z\n"
    f";; for Mirror Test ({AGENT}) in hub\n"
    ";; mood=neutral traits={}\n\n"
)
BODY = (
    f'(do (if (< (player-distance "{AGENT}") 6) '
    f'(emote "{AGENT}" "wave") nil))'
)
PROGRAM = HEADER + BODY + "\n"
FIVE = ("v1", "v2", "v3", "v4", "v5")


def body_subject(text):
    """The body id of a program text (what `slosh_lisp.py subjects` prints second)."""
    return slosh.program_subjects(text.encode("utf-8"))[-1]


def vote(store, subject, verifier, passed, notes="failed in test"):
    return verifications.record(store, {
        "verifier": verifier,
        "agent_id": "verifier-agent-001",
        "subject": subject,
        "subject_kind": "program",
        "environment": "hub frame=1 test",
        "passed": passed,
        "notes": "" if passed else notes,
        "at": "2026-10-12T00:00:00Z",
    })


class TempState(unittest.TestCase):
    """Build a tiny ``state/`` tree and point ``slosh_lisp.STATE`` at it."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="slosh-gate-"))
        self.state = self.tmp / "state"
        (self.state / "programs").mkdir(parents=True)
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.addCleanup(setattr, slosh, "STATE", slosh.STATE)
        slosh.STATE = str(self.state)
        self.store = verifications.load(self.state / "verifications.json")

    def write_program(self, aid=AGENT, text=PROGRAM):
        path = self.state / "programs" / f"{aid}.lisp"
        path.write_text(text, encoding="utf-8")
        return str(path)

    def save_store(self):
        verifications.save(self.store, self.state / "verifications.json")

    def write_world(self, agent_ids):
        agents = [{
            "id": aid, "name": aid, "world": "hub",
            "position": {"x": 1, "y": 0, "z": 2},
            "traits": {"explorer": 0.5, "social": 0.5},
            "mood": "neutral",
        } for aid in agent_ids]
        (self.state / "agents.json").write_text(json.dumps({
            "schema": "rappterverse-agents/1.0", "agents": agents, "_meta": {},
        }))
        (self.state / "game_state.json").write_text(json.dumps({
            "schema": "rappterverse-game-state/1.0",
            "worlds": {"hub": {"population": 0, "time_of_day": "day", "routines": []}},
            "_meta": {},
        }))
        (self.state / "frame_counter.json").write_text(json.dumps({"frame": 1}))
        for name in ("actions", "chat", "relationships"):
            (self.state / f"{name}.json").write_text("{}")

    def read_routines(self):
        with open(self.state / "game_state.json", encoding="utf-8") as handle:
            game = json.load(handle)
        return game, {r["agentId"]: r for r in game["worlds"]["hub"]["routines"]}


class NormalizeAndSubjectTests(TempState):
    def test_normalize_strips_comment_and_blank_lines(self):
        self.assertEqual(slosh.normalize_program(PROGRAM), BODY)

    def test_program_subject_is_content_id(self):
        self.assertEqual(slosh.program_subject(PROGRAM), verifications.content_id(PROGRAM))
        self.assertNotEqual(slosh.program_subject(BODY), slosh.program_subject(PROGRAM))

    def test_tidy_one_line_body_is_its_own_canonical_form(self):
        self.assertEqual(slosh.canonical_body(BODY), BODY)
        self.assertEqual(body_subject(PROGRAM), verifications.content_id(BODY))

    def test_whitespace_only_edits_keep_the_body_subject(self):
        spaced = PROGRAM.replace("(do (if", "(do  (if").replace(" nil))", "\n   nil))")
        self.assertNotEqual(slosh.normalize_program(spaced), BODY)
        self.assertEqual(body_subject(spaced), body_subject(PROGRAM))
        self.assertNotEqual(slosh.program_subjects(spaced.encode())[0], slosh.program_subjects(PROGRAM.encode())[0])

    def test_single_semicolon_comments_are_stripped_like_the_vm(self):
        text = "; one semicolon\n" + BODY + " ; trailing\n"
        self.assertEqual(slosh.normalize_program(text), BODY)
        self.assertEqual(lisp_vm.tokenize(text), lisp_vm.tokenize(BODY))

    def test_semicolons_inside_string_literals_survive(self):
        text = '(do (emote "a" "x ;; not a comment"))\n'
        self.assertEqual(slosh.normalize_program(text), text.strip())
        multi = '(do (emote "a" "line1\n;; still inside the string\n"))\n'
        self.assertIn(";; still inside", slosh.normalize_program(multi))

    def test_semicolon_inside_a_symbol_is_not_a_comment_like_the_vm(self):
        # rappter-vm.js only starts a comment at a token boundary; `wave;c`
        # is one symbol there, so stripping from the `;` would ship a body
        # the browser reads differently (and synthesize over a valid form).
        text = '(do (emote "x" wave;c))'
        self.assertEqual(slosh.normalize_program(text), text)
        self.assertTrue(slosh.is_single_do_form(slosh.normalize_program(text)))
        self.assertEqual(slosh.browser_tokenize(text), ["(", "do", "(", "emote", '"x"', "wave;c", ")", ")"])
        # after a closing quote, a parenthesis or whitespace it is still a comment
        self.assertEqual(slosh.normalize_program('(do "a";c\n);d\n'), '(do "a"\n)')
        self.assertEqual(slosh.normalize_program('(do (x) ;c\n)'), '(do (x)\n)')

    def test_strip_comments_has_no_string_escapes_like_the_browser(self):
        # rappter-vm.js reads a string to the next `"` with no backslash
        # escapes, so `"a\"` is a complete string and what follows it is
        # outside. Treating the backslash as an escape would swallow the
        # second string's opening quote, drop `;c")` as a comment and ship a
        # browser-valid program as the synthesized routine instead.
        text = '(do "a\\" "b;c")'
        self.assertEqual(slosh.normalize_program(text), text)
        self.assertTrue(slosh.is_single_do_form(slosh.normalize_program(text)))
        self.assertEqual(slosh.browser_tokenize(text), ["(", "do", '"a\\"', '"b;c"', ")"])
        text = '(do "a\\" ";foo\nbar")'
        self.assertEqual(slosh.normalize_program(text), text)
        self.assertEqual(slosh.browser_tokenize(slosh.normalize_program(text)),
                         slosh.browser_tokenize(text))

    def test_quote_inside_a_symbol_does_not_open_a_string_like_the_vm(self):
        # `foo"` is one symbol for rappter-vm.js, so the `"` after it opens
        # nothing and `";not a comment"` is a whole string. A stripper that
        # opened a string at every quote cut the body to `(do foo" (do "`,
        # skipped a program the browser runs and keyed it on the wrong text.
        text = '(do foo" (do ";not a comment" (emote "bob" "wave")))'
        self.assertTrue(slosh.is_single_do_form(text))
        self.assertEqual(slosh.normalize_program(text), text)
        self.assertTrue(slosh.is_single_do_form(slosh.normalize_program(text)))
        self.assertEqual(slosh.browser_tokenize(slosh.normalize_program(text)),
                         slosh.browser_tokenize(text))
        # a keyword runs past `(`, so the quote after `:k(` is inside it too
        self.assertEqual(slosh.normalize_program('(do :k(" x) ;c\n)'), '(do :k(" x)\n)')

    def test_body_id_splits_tokens_like_the_browser_vm(self):
        # The browser RappterVM (src/js/rappter-vm.js _tokenize) treats ' and :
        # as ordinary symbol characters, where lisp_vm.tokenize makes ' its own
        # token. Two programs the browser evaluates differently must never
        # share a body id, or a pass vote (or a hide) on one transfers to the
        # other while the shipped text really is the different code.
        joined = "(do (def x'y 1) x'y)"
        split = "(do (def x 'y 1) x 'y)"
        self.assertEqual(slosh.browser_tokenize(joined), ["(", "do", "(", "def", "x'y", "1", ")", "x'y", ")"])
        self.assertNotEqual(slosh.canonical_body(joined), slosh.canonical_body(split))
        self.assertNotEqual(body_subject(joined), body_subject(split))
        self.assertEqual(slosh.canonical_body(joined), joined)
        self.assertEqual(slosh.canonical_body(split), split)
        # lisp_vm would have conflated them; that is the bug this pins.
        self.assertEqual(lisp_vm.tokenize(joined), lisp_vm.tokenize(split))

    def test_browser_tokenizer_matches_rappter_vm_grammar(self):
        # Whitespace is space/tab/LF/CR; ';' comments; parens; strings with no
        # escapes; ':' keywords end at space, ')' or LF; symbols end at space,
        # ')', '(', LF or tab.
        src = '(do ; comment\n\t(emote "a;b" :kw-1 x:y) (f "q\\" z))'
        self.assertEqual(
            slosh.browser_tokenize(src),
            ["(", "do", "(", "emote", '"a;b"', ":kw-1", "x:y", ")", "(", "f", '"q\\"', "z", ")", ")"],
        )
        with self.assertRaises(SyntaxError):
            slosh.browser_tokenize('(do "open')
        # Re-tokenizing a canonical body gives the same tokens (idempotent).
        canon = slosh.canonical_body(src)
        self.assertEqual(slosh.browser_tokenize(canon), slosh.browser_tokenize(src))
        self.assertEqual(slosh.canonical_body(canon), canon)
        # An untokenizable body falls back to itself rather than raising.
        self.assertEqual(slosh.canonical_body('(do "open'), '(do "open')

    def test_file_subject_is_sha256_of_the_bytes_even_for_crlf(self):
        crlf = PROGRAM.replace("\n", "\r\n").encode("utf-8")
        file_id, body_id = slosh.program_subjects(crlf)
        self.assertEqual(file_id, "sha256:" + hashlib.sha256(crlf).hexdigest())
        self.assertEqual(body_id, body_subject(PROGRAM))
        path = self.state / "programs" / f"{AGENT}.lisp"
        path.write_bytes(crlf)
        routine = slosh.mirror_routine(AGENT, str(path), self.store)
        self.assertEqual(routine["subject"], file_id)
        self.assertEqual(routine["program"], BODY)

    def test_program_subject_owners_registers_both_ids_per_controller(self):
        self.write_program(AGENT, PROGRAM)
        self.write_program(OTHER, PROGRAM)  # byte-identical program, other controller
        (self.state / "programs" / "_world").mkdir()
        (self.state / "programs" / "_world" / "hub.lisp").write_text(BODY)
        owners = slosh.program_subject_owners(
            self.state / "programs", {AGENT: "alice", OTHER: "bob", "ghost": "carol"})
        file_id, body_id = slosh.program_subjects(PROGRAM.encode())
        self.assertEqual(owners, {file_id: {"alice", "bob"}, body_id: {"alice", "bob"}})

    def test_subjects_cli_prints_file_and_body_ids(self):
        path = self.write_program()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(slosh._cli(["subjects", path]), 0)
        file_id, body_id = slosh.program_subjects(PROGRAM.encode())
        self.assertEqual(out.getvalue().splitlines(), [f"file {file_id}", f"body {body_id}"])

    def test_routine_subject_is_raw_file_content_id(self):
        path = self.write_program()
        routine = slosh.mirror_routine(AGENT, path, self.store)
        self.assertEqual(routine["subject"], verifications.content_id(PROGRAM))

    def test_header_edit_changes_subject_but_body_votes_follow(self):
        edited = PROGRAM.replace("Test Twin", "Another Twin")
        self.assertEqual(slosh.normalize_program(edited), BODY)
        self.assertNotEqual(verifications.content_id(edited), verifications.content_id(PROGRAM))
        vote(self.store, body_subject(PROGRAM), "alice", True)
        path = self.write_program(text=edited)
        routine = slosh.mirror_routine(AGENT, path, self.store)
        self.assertEqual(routine["subject"], verifications.content_id(edited))
        self.assertEqual(routine["verification"], slosh.MIRROR_VERIFIED)


class MirrorRoutineTests(TempState):
    def test_missing_file_synthesizes(self):
        path = str(self.state / "programs" / f"{AGENT}.lisp")
        self.assertIsNone(slosh.mirror_routine(AGENT, path, self.store))

    def test_non_do_form_synthesizes(self):
        path = self.write_program(text=HEADER + f'(emote "{AGENT}" "wave")\n')
        self.assertIsNone(slosh.mirror_routine(AGENT, path, self.store))

    def test_do_prefix_without_separator_synthesizes(self):
        path = self.write_program(text=HEADER + f'(done "{AGENT}")\n')
        self.assertIsNone(slosh.mirror_routine(AGENT, path, self.store))

    def test_multiline_do_form_is_accepted(self):
        text = HEADER + f'(do\n  (if (< (rand) 0.1) (emote "{AGENT}" "nod") nil)\n  nil)\n'
        path = self.write_program(text=text)
        routine = slosh.mirror_routine(AGENT, path, self.store)
        self.assertIsNotNone(routine)
        self.assertEqual(routine["program"], slosh.normalize_program(text))

    def test_two_top_level_forms_synthesize(self):
        path = self.write_program(text=HEADER + f'(do nil) (emote "{AGENT}" "wave")\n')
        self.assertIsNone(slosh.mirror_routine(AGENT, path, self.store))

    def test_unbalanced_or_untokenizable_body_synthesizes(self):
        for text in ("(do (if x y z)) )\n", "(do (if x y z)\n", '(do (emote "unterminated))\n'):
            with self.subTest(text=text):
                path = self.write_program(text=HEADER + text)
                self.assertIsNone(slosh.mirror_routine(AGENT, path, self.store))
        self.assertTrue(slosh.is_single_do_form(BODY))
        self.assertFalse(slosh.is_single_do_form("'(do nil)"))

    def test_structural_check_reads_strings_like_the_browser(self):
        # The browser VM has no string escapes: `"x\"` is a complete literal
        # there, so `(do "x\")` is one form and must not be replaced by a
        # synthesized routine. lisp_vm.tokenize would call it unterminated.
        body = '(do "x\\")'
        self.assertEqual(slosh.browser_tokenize(body), ["(", "do", '"x\\"', ")"])
        self.assertTrue(slosh.is_single_do_form(body))
        path = self.write_program(text=HEADER + body + "\n")
        routine = slosh.mirror_routine(AGENT, path, self.store)
        self.assertIsNotNone(routine)
        self.assertEqual(routine["program"], body)
        # And a string the browser cannot terminate is still rejected.
        self.assertFalse(slosh.is_single_do_form('(do "x)'))

    def test_non_utf8_file_synthesizes(self):
        path = self.state / "programs" / f"{AGENT}.lisp"
        path.write_bytes(b"(do \xff)\n")
        self.assertIsNone(slosh.mirror_routine(AGENT, str(path), self.store))

    def test_unverified_program_used_verbatim(self):
        path = self.write_program()
        routine = slosh.mirror_routine(AGENT, path, self.store)
        self.assertEqual(routine, {
            "agentId": AGENT,
            "program": BODY,
            "source": "self-authored",
            "verification": slosh.MIRROR_UNVERIFIED,
            "subject": verifications.content_id(PROGRAM),
        })

    def test_votes_on_body_subject_mark_verified(self):
        path = self.write_program()
        vote(self.store, body_subject(PROGRAM), "alice", True)
        routine = slosh.mirror_routine(AGENT, path, self.store)
        self.assertEqual(routine["verification"], slosh.MIRROR_VERIFIED)
        self.assertEqual(routine["program"], BODY)
        self.assertEqual(routine["votes"]["pass"], 1)
        self.assertEqual(routine["votes"]["subject"], body_subject(PROGRAM))

    def test_more_fails_than_passes_is_contested_not_verified(self):
        path = self.write_program()
        subject = body_subject(PROGRAM)
        vote(self.store, subject, "p1", True)
        vote(self.store, subject, "f1", False)
        self.assertEqual(slosh.mirror_routine(AGENT, path, self.store)["verification"],
                         slosh.MIRROR_VERIFIED)  # 1/2 = 0.5: at least half passed
        vote(self.store, subject, "f2", False)
        routine = slosh.mirror_routine(AGENT, path, self.store)
        self.assertEqual(routine["verification"], slosh.MIRROR_CONTESTED)
        self.assertEqual(routine["program"], BODY)  # contested still runs verbatim
        self.assertEqual((routine["votes"]["pass"], routine["votes"]["fail"]), (1, 2))

    def test_verified_needs_at_least_half_by_count_not_rounded_rate(self):
        # 5000 passes of 10001 votes: pass_rate rounds to 0.5, but fewer than
        # half passed, so the program is contested. Built directly (not via
        # record) because 10001 inserts would be quadratic.
        subject = body_subject(PROGRAM)
        votes = []
        for index in range(10001):
            rec = dict(vote({"verifications": []}, subject, f"v{index}", index < 5000)["verifications"][0])
            votes.append(rec)
        store = {"verifications": votes, "subjects": {}}
        status, detail = slosh.mirror_gate(BODY, store, raw=PROGRAM.encode("utf-8"))
        self.assertEqual(detail["pass_rate"], 0.5)
        self.assertEqual((detail["pass_count"], detail["votes"]), (5000, 10001))
        self.assertEqual(status, slosh.MIRROR_CONTESTED)
        votes.append(dict(vote({"verifications": []}, subject, "v10001", True)["verifications"][0]))
        status, detail = slosh.mirror_gate(BODY, store, raw=PROGRAM.encode("utf-8"))
        self.assertEqual((detail["pass_count"], detail["votes"]), (5001, 10002))
        self.assertEqual(status, slosh.MIRROR_VERIFIED)

    def test_hide_on_one_subject_logs_that_subject_not_the_bigger_tally(self):
        path = self.write_program()
        body = body_subject(PROGRAM)
        file_id = verifications.content_id(PROGRAM)
        for name in FIVE:
            vote(self.store, body, name, False)
        for name in ("p1", "p2", "p3", "p4", "p5", "p6"):
            vote(self.store, file_id, name, True)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertIsNone(slosh.mirror_routine(AGENT, path, self.store))
        log = out.getvalue()
        self.assertIn(f"5 fail / 5 votes on {body}", log)
        self.assertIn(f"file {file_id}", log)
        self.assertNotIn("0 fail / 6 votes", log)

    def test_votes_on_raw_file_subject_mark_verified(self):
        path = self.write_program()
        vote(self.store, verifications.content_id(PROGRAM), "alice", True)
        routine = slosh.mirror_routine(AGENT, path, self.store)
        self.assertEqual(routine["verification"], slosh.MIRROR_VERIFIED)
        self.assertEqual(routine["subject"], verifications.content_id(PROGRAM))

    def test_hidden_on_body_subject_falls_back_and_logs(self):
        path = self.write_program()
        subject = body_subject(PROGRAM)
        for name in FIVE:
            vote(self.store, subject, name, False)
        self.assertTrue(verifications.is_hidden(self.store, subject))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            routine = slosh.mirror_routine(AGENT, path, self.store)
        self.assertIsNone(routine)
        log = out.getvalue()
        self.assertIn("hidden by peer verification", log)
        self.assertIn(f"{AGENT}.lisp", log)
        self.assertIn(f"5 fail / 5 votes on {subject}", log)
        # The log also names the file subject, so an operator can find both.
        self.assertIn(verifications.content_id(PROGRAM), log)

    def test_hidden_on_raw_file_subject_also_hides(self):
        path = self.write_program()
        for name in FIVE:
            vote(self.store, verifications.content_id(PROGRAM), name, False)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertIsNone(slosh.mirror_routine(AGENT, path, self.store))

    def test_four_fails_is_below_hide_threshold_but_contested(self):
        path = self.write_program()
        for name in FIVE[:4]:
            vote(self.store, body_subject(PROGRAM), name, False)
        routine = slosh.mirror_routine(AGENT, path, self.store)
        self.assertIsNotNone(routine)
        self.assertEqual(routine["verification"], slosh.MIRROR_CONTESTED)
        self.assertEqual(routine["votes"], {
            "pass": 0, "fail": 4, "score": 0.0, "subject": body_subject(PROGRAM)})

    def test_exactly_twenty_percent_pass_is_not_hidden(self):
        path = self.write_program()
        subject = body_subject(PROGRAM)
        vote(self.store, subject, "p1", True)
        for name in FIVE[:4]:
            vote(self.store, subject, name, False)
        self.assertFalse(verifications.is_hidden(self.store, subject))
        self.assertIsNotNone(slosh.mirror_routine(AGENT, path, self.store))

    def test_revote_replaces_rather_than_stacks(self):
        path = self.write_program()
        subject = body_subject(PROGRAM)
        for _ in range(5):
            vote(self.store, subject, "same-controller", False)
        self.assertEqual(verifications.score(self.store, subject)["votes"], 1)
        self.assertIsNotNone(slosh.mirror_routine(AGENT, path, self.store))

    def test_votes_on_unrelated_subject_do_not_hide(self):
        path = self.write_program()
        for name in FIVE:
            vote(self.store, verifications.content_id("(do nil)"), name, False)
        routine = slosh.mirror_routine(AGENT, path, self.store)
        self.assertEqual(routine["verification"], slosh.MIRROR_UNVERIFIED)


class FailOpenTests(TempState):
    def test_store_none_is_unverified(self):
        path = self.write_program()
        routine = slosh.mirror_routine(AGENT, path, None)
        self.assertEqual(routine["verification"], slosh.MIRROR_UNVERIFIED)
        self.assertEqual(routine["program"], BODY)

    def test_missing_module_is_unverified_without_subject(self):
        path = self.write_program()
        self.addCleanup(setattr, slosh, "_verifications", slosh._verifications)
        slosh._verifications = None
        self.assertIsNone(slosh.load_verification_store())
        self.assertIsNone(slosh.program_subject(BODY))
        routine = slosh.mirror_routine(AGENT, path, slosh.load_verification_store())
        self.assertEqual(routine["verification"], slosh.MIRROR_UNVERIFIED)
        self.assertNotIn("subject", routine)

    def test_broken_module_is_unverified(self):
        path = self.write_program()

        class Broken:
            @staticmethod
            def content_id(_):
                raise RuntimeError("boom")

        self.addCleanup(setattr, slosh, "_verifications", slosh._verifications)
        slosh._verifications = Broken
        routine = slosh.mirror_routine(AGENT, path, {"verifications": []})
        self.assertEqual(routine["verification"], slosh.MIRROR_UNVERIFIED)

    def test_corrupt_store_file_fails_open_as_no_store(self):
        (self.state / "verifications.json").write_text("{not json")
        with self.assertRaises(ValueError):
            verifications.load(self.state / "verifications.json")
        self.assertIsNone(slosh.load_verification_store())
        routine = slosh.mirror_routine(AGENT, self.write_program(), slosh.load_verification_store())
        self.assertEqual(routine["verification"], slosh.MIRROR_UNVERIFIED)


class EndToEndSloshTests(TempState):
    def test_main_reads_store_from_state_and_applies_gate(self):
        self.write_world([AGENT, OTHER])
        self.write_program(AGENT, PROGRAM)
        other_program = PROGRAM.replace(AGENT, OTHER)
        self.write_program(OTHER, other_program)
        for name in FIVE:
            vote(self.store, body_subject(PROGRAM), name, False)
        self.save_store()

        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            slosh.main()
        log = out.getvalue()
        self.assertIn("hidden by peer verification", log)
        self.assertIn("Sloshed:", log)

        game, routines = self.read_routines()
        self.assertEqual(next(iter(game)), "schema")
        self.assertEqual(set(routines), {AGENT, OTHER})

        hidden = routines[AGENT]
        self.assertNotIn("source", hidden)
        self.assertNotIn("verification", hidden)
        self.assertNotEqual(hidden["program"], BODY)
        self.assertTrue(hidden["program"].startswith("(do (if (< (mod (floor (elapsed)) 20) 10)"))

        used = routines[OTHER]
        self.assertEqual(used["source"], "self-authored")
        self.assertEqual(used["verification"], slosh.MIRROR_UNVERIFIED)
        self.assertEqual(used["program"], slosh.normalize_program(other_program))
        self.assertEqual(used["subject"], verifications.content_id(other_program))

    def test_main_without_store_file_uses_programs_verbatim(self):
        self.write_world([AGENT])
        self.write_program(AGENT, PROGRAM)
        self.assertFalse((self.state / "verifications.json").exists())
        with contextlib.redirect_stdout(io.StringIO()):
            slosh.main()
        _, routines = self.read_routines()
        self.assertEqual(routines[AGENT]["program"], BODY)
        self.assertEqual(routines[AGENT]["verification"], slosh.MIRROR_UNVERIFIED)
        self.assertFalse((self.state / "verifications.json").exists())


class FakeVerifications:
    """Stub of scripts/verifications.py with the agreed contract.

    These tests exercise the gate without the real scorer, so they hold even
    if the scoring rules change: hidden/unverified/verified are driven purely
    by what the stub says about a subject.
    """

    def __init__(self, hidden=(), scores=None, *, load_raises=False,
                 hidden_raises=False):
        self.hidden = set(hidden)
        self.scores = dict(scores or {})
        self.load_raises = load_raises
        self.hidden_raises = hidden_raises
        self.calls = []

    @staticmethod
    def content_id(data):
        if isinstance(data, str):
            data = data.encode("utf-8")
        return "sha256:" + hashlib.sha256(data).hexdigest()

    def load(self, path=None):
        self.calls.append(("load", str(path) if path is not None else None))
        if self.load_raises:
            raise OSError("verifications store unreadable")
        return {"verifications": [], "fake": True}

    def score(self, store, subject):
        self.calls.append(("score", subject))
        default = {"pass_count": 0, "fail_count": 0, "votes": 0,
                   "score": 0.0, "hidden": subject in self.hidden}
        return dict(self.scores.get(subject, default))

    def is_hidden(self, store, subject):
        self.calls.append(("is_hidden", subject))
        if self.hidden_raises:
            raise RuntimeError("scorer exploded")
        return subject in self.hidden


MULTILINE_PROGRAM = HEADER + (
    "(do\n"
    f'  (if (< (player-distance "{AGENT}") 6) (wander "{AGENT}" 8) nil)\n'
    f'  (if (< (rand) 0.005) (emote "{AGENT}" "nod") nil))\n'
)


class StubbedModuleTests(TempState):
    """Gate behaviour with scripts/verifications.py replaced by a stub."""

    def setUp(self):
        super().setUp()
        self._saved_module = slosh._verifications
        self.addCleanup(setattr, slosh, "_verifications", self._saved_module)
        self.file_subject = FakeVerifications.content_id(PROGRAM)
        self.body_subject = FakeVerifications.content_id(slosh.canonical_body(BODY))

    def use(self, fake):
        slosh._verifications = fake
        return fake

    def test_stub_unverified_uses_program_verbatim(self):
        fake = self.use(FakeVerifications())
        routine = slosh.mirror_routine(AGENT, self.write_program(), fake.load())
        self.assertEqual(routine["program"], BODY)
        self.assertEqual(routine["source"], "self-authored")
        self.assertEqual(routine["verification"], slosh.MIRROR_UNVERIFIED)
        self.assertEqual(routine["subject"], self.file_subject)
        self.assertIn(("is_hidden", self.body_subject), fake.calls)

    def test_stub_verified_uses_program_verbatim(self):
        fake = self.use(FakeVerifications(scores={self.file_subject: {
            "pass_count": 5, "fail_count": 0, "votes": 5,
            "score": 0.57, "hidden": False}}))
        routine = slosh.mirror_routine(AGENT, self.write_program(), fake.load())
        self.assertEqual(routine["verification"], slosh.MIRROR_VERIFIED)
        self.assertEqual(routine["program"], BODY)

    def test_stub_hidden_synthesizes_and_logs_one_line(self):
        fake = self.use(FakeVerifications(hidden={self.file_subject}, scores={
            self.file_subject: {"pass_count": 0, "fail_count": 5, "votes": 5,
                                "score": 0.0, "hidden": True}}))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            routine = slosh.mirror_routine(AGENT, self.write_program(), fake.load())
        self.assertIsNone(routine)
        lines = [line for line in out.getvalue().splitlines() if line.strip()]
        self.assertEqual(len(lines), 1)
        self.assertIn("Mirror gate", lines[0])
        self.assertIn("5 fail / 5 votes", lines[0])
        self.assertIn(self.file_subject, lines[0])

    def test_stub_hide_on_body_subject_survives_header_rewrite(self):
        fake = self.use(FakeVerifications(hidden={self.body_subject}))
        redated = PROGRAM.replace("2026-10-12T00:00:00Z", "2026-10-13T00:00:00Z")
        with contextlib.redirect_stdout(io.StringIO()):
            routine = slosh.mirror_routine(
                AGENT, self.write_program(text=redated), fake.load())
        self.assertIsNone(routine)

    def test_stub_votes_on_body_subject_count_as_verified(self):
        fake = self.use(FakeVerifications(scores={self.body_subject: {
            "pass_count": 2, "fail_count": 0, "votes": 2,
            "score": 0.34, "hidden": False}}))
        routine = slosh.mirror_routine(AGENT, self.write_program(), fake.load())
        self.assertEqual(routine["verification"], slosh.MIRROR_VERIFIED)
        self.assertEqual(routine["subject"], self.file_subject)

    def test_stub_scorer_exception_fails_open(self):
        fake = self.use(FakeVerifications(hidden={self.file_subject},
                                          hidden_raises=True))
        routine = slosh.mirror_routine(AGENT, self.write_program(), fake.load())
        self.assertEqual(routine["verification"], slosh.MIRROR_UNVERIFIED)
        self.assertEqual(routine["program"], BODY)

    def test_stub_load_failure_means_no_store(self):
        fake = self.use(FakeVerifications(load_raises=True))
        self.assertIsNone(slosh.load_verification_store())
        self.assertEqual(fake.calls[0][0], "load")
        self.assertTrue(fake.calls[0][1].endswith("verifications.json"))

    def test_multiline_do_form_is_accepted(self):
        fake = self.use(FakeVerifications())
        routine = slosh.mirror_routine(
            AGENT, self.write_program(text=MULTILINE_PROGRAM), fake.load())
        self.assertIsNotNone(routine)
        self.assertTrue(routine["program"].startswith("(do\n"))

    def test_vote_count_tolerates_other_shapes(self):
        self.assertEqual(slosh._vote_count({"votes": ["a", "b"]}), 2)
        self.assertEqual(slosh._vote_count({"pass_count": 2, "fail_count": 1}), 3)
        self.assertEqual(slosh._vote_count({"votes": True}), 0)
        self.assertEqual(slosh._vote_count({}), 0)

    def test_stub_main_hidden_and_unverified_side_by_side(self):
        self.write_world([AGENT, OTHER])
        self.write_program(AGENT, PROGRAM)
        other_program = PROGRAM.replace(AGENT, OTHER)
        self.write_program(OTHER, other_program)
        self.use(FakeVerifications(hidden={self.file_subject}, scores={
            self.file_subject: {"pass_count": 1, "fail_count": 6, "votes": 7,
                                "score": 0.02, "hidden": True}}))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            slosh.main()
        self.assertEqual(out.getvalue().count("Mirror gate"), 1)
        with open(self.state / "game_state.json", encoding="utf-8") as handle:
            game = json.load(handle)
        routines = {r["agentId"]: r for r in game["worlds"]["hub"]["routines"]}
        self.assertNotIn("source", routines[AGENT])
        self.assertEqual(routines[OTHER]["verification"], slosh.MIRROR_UNVERIFIED)
        self.assertEqual(routines[OTHER]["subject"],
                         FakeVerifications.content_id(other_program))


if __name__ == "__main__":
    unittest.main()
