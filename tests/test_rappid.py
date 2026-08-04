"""RAPP/1 §6 identity: grammar, mint-once minting, key binding, signatures.

Every vector here is checked against the pinned authority text —
``kody-w/rapp-1`` @ ``6723c7add2aed36bb68992fc71a56b0a4bd5ad81`` — and the
``rapp-commons/events/SCHEMA.md`` verification rules. The ECDSA implementation
is additionally cross-checked against OpenSSL in
``test_openssl_interop`` when an ``openssl`` binary is on PATH, so the
pure-Python curve arithmetic cannot silently drift from the real algorithm.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "scripts"))

import rappid  # noqa: E402
from rappid import (  # noqa: E402
    Hb,
    RappidError,
    b64u_decode,
    b64u_encode,
    canonical_json,
    canonicalize_rappid,
    ecdsa_p256_sign,
    ecdsa_p256_verify,
    format_rappid,
    is_rappid,
    mint_keyed,
    mint_keyless,
    parse_rappid,
    public_point,
    raw_point_from_spki,
    sign_document,
    spki_der_from_raw_point,
    verify_key_binding,
    verify_signed_document,
)

# Fixed private-key scalars used as test vectors. Not credentials — they
# guard nothing, and every public key they mint appears in this file.
SCALAR_A = 0x1122334455667788990011223344556677889900112233445566778899001122
SCALAR_B = 0x0FEDCBA9876543210FEDCBA9876543210FEDCBA9876543210FEDCBA987654321


def _identity(owner="kody-w", slug="codebot-001", secret=SCALAR_A):
    spki = spki_der_from_raw_point(public_point(secret))
    return mint_keyed(owner, slug, spki), b64u_encode(public_point(secret))


class TestTaggedHash(unittest.TestCase):
    """RAPP/1 §5: Hb(space, b) = lowercase_hex(SHA-256(utf8(space) || 0x0A || b))."""

    def test_matches_the_spec_formula(self):
        self.assertEqual(
            hashlib.sha256(b"rapp/1:rappid\n" + b"payload").hexdigest(),
            Hb("rapp/1:rappid", b"payload"),
        )

    def test_the_newline_separator_is_load_bearing(self):
        self.assertNotEqual(
            Hb("rapp/1:rappid", b"payload"),
            hashlib.sha256(b"rapp/1:rappid" + b"payload").hexdigest(),
        )


class TestGrammar(unittest.TestCase):
    """§6.1 — the self-locating form is the only conformant rappid."""

    def test_accepts_the_canonical_form(self):
        owner, slug, tail = parse_rappid("rappid:@kody-w/codebot-001:" + "a" * 64)
        self.assertEqual(("kody-w", "codebot-001", "a" * 64), (owner, slug, tail))

    def test_refuses_legacy_and_malformed_forms(self):
        for bad in (
            "rappid:codebot:" + "a" * 64,              # §6.1 legacy bare form
            "rappid:v2:" + "a" * 64,                   # §6.1 legacy versioned form
            "rappid:@kody-w/codebot-001:" + "a" * 32,  # provisional 128-bit tail
            "rappid:@kody-w/codebot-001:" + "A" * 64,  # uppercase hex
            "rappid:@-kody/codebot-001:" + "a" * 64,   # leading hyphen
            "rappid:@kody--w/codebot-001:" + "a" * 64,  # adjacent hyphens
            "rappid:@kody-w/codebot-:" + "a" * 64,     # trailing hyphen
            "rappid:@Kody-W/codebot-001:" + "a" * 64,  # display casing is not identity
            "rappid:@kody-w:" + "a" * 64,              # no slug
            "",
            None,
        ):
            with self.subTest(bad=bad):
                self.assertFalse(is_rappid(bad))
                with self.assertRaises(RappidError):
                    parse_rappid(bad)

    def test_normative_length_limits_are_enforced(self):
        with self.assertRaises(RappidError):
            parse_rappid(f"rappid:@{'a' * 40}/slug:{'a' * 64}")
        with self.assertRaises(RappidError):
            parse_rappid(f"rappid:@owner/{'a' * 101}:{'a' * 64}")
        self.assertTrue(is_rappid(f"rappid:@{'a' * 39}/{'b' * 100}:{'a' * 64}"))

    def test_every_rappterverse_agent_id_is_a_legal_slug(self):
        agents = json.loads((BASE_DIR / "state" / "agents.json").read_text(encoding="utf-8"))
        for agent in agents["agents"]:
            with self.subTest(agent=agent["id"]):
                self.assertTrue(is_rappid(format_rappid("kody-w", agent["id"], "a" * 64)))


class TestMinting(unittest.TestCase):
    """§6.2 — mint-once, and never from a name."""

    def test_keyless_mint_uses_the_uuid_octets(self):
        octets = bytes(range(16))
        rappid = mint_keyless("kody-w", "codebot-001", octets)
        self.assertEqual(Hb("rapp/1:rappid", octets), parse_rappid(rappid)[2])

    def test_keyless_mint_requires_16_octets(self):
        with self.assertRaises(RappidError):
            mint_keyless("kody-w", "codebot-001", b"short")

    def test_keyed_mint_uses_the_spki_der(self):
        spki = spki_der_from_raw_point(public_point(SCALAR_A))
        rappid = mint_keyed("kody-w", "codebot-001", spki)
        self.assertEqual(Hb("rapp/1:rappid", spki), parse_rappid(rappid)[2])

    def test_tail_is_never_derived_from_the_name(self):
        """§6.2 prohibits sha256("owner/slug") — drift ID-01/C3."""
        rappid = mint_keyed("kody-w", "codebot-001", spki_der_from_raw_point(public_point(SCALAR_A)))
        forbidden = hashlib.sha256(b"kody-w/codebot-001").hexdigest()
        self.assertNotEqual(forbidden, parse_rappid(rappid)[2])

    def test_minting_is_stable_for_a_given_key(self):
        spki = spki_der_from_raw_point(public_point(SCALAR_A))
        self.assertEqual(
            mint_keyed("kody-w", "codebot-001", spki),
            mint_keyed("kody-w", "codebot-001", spki),
        )

    def test_distinct_keys_mint_distinct_identities(self):
        self.assertNotEqual(_identity(secret=SCALAR_A)[0], _identity(secret=SCALAR_B)[0])


class TestCanonicalizeOnRead(unittest.TestCase):
    """§6.3 — restructure, preserving the hash; never invent one."""

    def test_canonical_form_passes_through(self):
        rappid = f"rappid:@kody-w/codebot-001:{'a' * 64}"
        self.assertEqual((rappid, False), canonicalize_rappid(rappid, "kody-w", "codebot-001"))

    def test_legacy_form_is_restructured_with_its_hash_preserved(self):
        restructured, provisional = canonicalize_rappid(
            f"rappid:codebot:{'b' * 64}", "kody-w", "codebot-001"
        )
        self.assertFalse(provisional)
        self.assertEqual("b" * 64, parse_rappid(restructured)[2])

    def test_a_short_tail_is_provisional_not_repaired(self):
        restructured, provisional = canonicalize_rappid(
            f"rappid:v2:{'c' * 32}", "kody-w", "codebot-001"
        )
        self.assertTrue(provisional)
        self.assertFalse(is_rappid(restructured), "a provisional id must not pass as canonical")

    def test_an_identifier_with_no_hash_is_refused(self):
        with self.assertRaises(RappidError):
            canonicalize_rappid("just-a-name", "kody-w", "codebot-001")


class TestKeyEncoding(unittest.TestCase):
    def test_spki_round_trip(self):
        raw = public_point(SCALAR_A)
        self.assertEqual(raw, raw_point_from_spki(spki_der_from_raw_point(raw)))

    def test_spki_prefix_is_the_p256_algorithm_identifier(self):
        der = spki_der_from_raw_point(public_point(SCALAR_A))
        self.assertIn(bytes.fromhex("2a8648ce3d0201"), der)    # id-ecPublicKey
        self.assertIn(bytes.fromhex("2a8648ce3d030107"), der)  # prime256v1
        self.assertEqual(91, len(der))

    def test_rejects_a_non_p256_key(self):
        with self.assertRaises(RappidError):
            spki_der_from_raw_point(b"\x04" + b"\x00" * 10)
        with self.assertRaises(RappidError):
            raw_point_from_spki(b"nonsense")

    def test_rejects_a_point_off_the_curve(self):
        raw = bytearray(public_point(SCALAR_A))
        raw[-1] ^= 0xFF
        with self.assertRaises(RappidError):
            ecdsa_p256_verify(bytes(raw), b"m", b"\x00" * 64)

    def test_base64url_round_trip_without_padding(self):
        raw = public_point(SCALAR_A)
        encoded = b64u_encode(raw)
        self.assertNotIn("=", encoded)
        self.assertEqual(raw, b64u_decode(encoded))


class TestSignatures(unittest.TestCase):
    def test_sign_verify_round_trip(self):
        signature = ecdsa_p256_sign(SCALAR_A, b"hello")
        self.assertEqual(64, len(signature))
        self.assertTrue(ecdsa_p256_verify(public_point(SCALAR_A), b"hello", signature))

    def test_signing_is_deterministic_rfc6979(self):
        self.assertEqual(ecdsa_p256_sign(SCALAR_A, b"hello"), ecdsa_p256_sign(SCALAR_A, b"hello"))

    def test_a_different_message_does_not_verify(self):
        signature = ecdsa_p256_sign(SCALAR_A, b"hello")
        self.assertFalse(ecdsa_p256_verify(public_point(SCALAR_A), b"hell0", signature))

    def test_a_different_key_does_not_verify(self):
        signature = ecdsa_p256_sign(SCALAR_A, b"hello")
        self.assertFalse(ecdsa_p256_verify(public_point(SCALAR_B), b"hello", signature))

    def test_out_of_range_scalars_are_rejected(self):
        self.assertFalse(ecdsa_p256_verify(public_point(SCALAR_A), b"hello", b"\x00" * 64))
        self.assertFalse(ecdsa_p256_verify(public_point(SCALAR_A), b"hello", b"garbage"))

    @unittest.skipIf(shutil.which("openssl") is None, "openssl not on PATH")
    def test_openssl_interop(self):
        """OpenSSL must verify what we sign, and we must verify what OpenSSL signs."""
        work = BASE_DIR / "tests" / "__openssl_probe"
        work.mkdir(exist_ok=True)
        try:
            key, pub, msg = work / "k.pem", work / "k.der", work / "m.bin"
            msg.write_bytes(b'{"hello":"commons"}')
            subprocess.run(
                ["openssl", "ecparam", "-name", "prime256v1", "-genkey", "-noout", "-out", str(key)],
                check=True, capture_output=True,
            )
            subprocess.run(
                ["openssl", "ec", "-in", str(key), "-pubout", "-outform", "DER", "-out", str(pub)],
                check=True, capture_output=True,
            )
            sig = work / "m.sig"
            subprocess.run(
                ["openssl", "dgst", "-sha256", "-sign", str(key), "-out", str(sig), str(msg)],
                check=True, capture_output=True,
            )
            raw_pub = raw_point_from_spki(pub.read_bytes())
            self.assertTrue(
                ecdsa_p256_verify(raw_pub, msg.read_bytes(), sig.read_bytes()),
                "pure-Python verifier rejected a valid OpenSSL DER signature",
            )
            self.assertFalse(ecdsa_p256_verify(raw_pub, b"tampered", sig.read_bytes()))

            # ... and the other direction: OpenSSL verifies our raw r||s signature.
            ours = ecdsa_p256_sign(SCALAR_A, msg.read_bytes())
            r = int.from_bytes(ours[:32], "big")
            s = int.from_bytes(ours[32:], "big")

            def _int(value):
                body = value.to_bytes(value.bit_length() // 8 + 1, "big")
                return b"\x02" + bytes([len(body)]) + body

            der_sig = _int(r) + _int(s)
            (work / "ours.sig").write_bytes(b"\x30" + bytes([len(der_sig)]) + der_sig)
            (work / "ours.der").write_bytes(spki_der_from_raw_point(public_point(SCALAR_A)))
            result = subprocess.run(
                ["openssl", "dgst", "-sha256", "-verify", str(work / "ours.der"),
                 "-keyform", "DER", "-signature", str(work / "ours.sig"), str(msg)],
                capture_output=True, text=True,
            )
            self.assertIn("Verified OK", result.stdout, result.stdout + result.stderr)
        finally:
            shutil.rmtree(work, ignore_errors=True)


class TestCanonicalJson(unittest.TestCase):
    """rapp-commons verification rule 4: recursively sorted keys, no whitespace."""

    def test_key_order_does_not_change_the_bytes(self):
        self.assertEqual(
            canonical_json({"b": {"z": 1, "a": 2}, "a": 3}),
            canonical_json({"a": 3, "b": {"a": 2, "z": 1}}),
        )

    def test_no_whitespace(self):
        self.assertEqual(b'{"a":1,"b":2}', canonical_json({"b": 2, "a": 1}))

    def test_unicode_is_not_escaped_away(self):
        self.assertEqual('"ü"'.encode("utf-8"), canonical_json("ü"))


class TestBindingAndImpersonation(unittest.TestCase):
    """The point of the whole exercise: author.id becomes a proof."""

    def test_binding_holds_for_a_correctly_minted_identity(self):
        rappid, pub = _identity()
        verify_key_binding(rappid, pub)

    def test_binding_fails_for_someone_elses_key(self):
        rappid, _ = _identity(secret=SCALAR_A)
        _, other_pub = _identity(secret=SCALAR_B)
        with self.assertRaises(RappidError):
            verify_key_binding(rappid, other_pub)

    def test_signed_document_round_trip(self):
        rappid, _ = _identity()
        signed = sign_document({"id": "msg-1", "content": "gm"}, SCALAR_A, rappid)
        verify_signed_document(signed, expected_from=rappid)
        self.assertEqual("ecdsa-p256", signed["alg"])

    def test_tampering_with_the_body_is_caught(self):
        rappid, _ = _identity()
        signed = sign_document({"id": "msg-1", "content": "gm"}, SCALAR_A, rappid)
        signed["content"] = "gm, but forged"
        with self.assertRaises(RappidError):
            verify_signed_document(signed)

    def test_claiming_another_agents_rappid_is_caught_by_the_key_binding(self):
        """The exact attack #5942 names: writing a message as someone else."""
        victim, _ = _identity(owner="kody-w", slug="terrastar-001", secret=SCALAR_A)
        attacker, _ = _identity(owner="mallory", slug="terrastar-001", secret=SCALAR_B)
        forged = sign_document({"id": "msg-2", "content": "I am TerraStar"}, SCALAR_B, attacker)
        forged["from"] = victim
        with self.assertRaisesRegex(RappidError, "does not bind"):
            verify_signed_document(forged)

    def test_a_missing_field_is_refused(self):
        rappid, _ = _identity()
        signed = sign_document({"id": "msg-1"}, SCALAR_A, rappid)
        for field in ("from", "pub", "alg", "sig"):
            partial = {k: v for k, v in signed.items() if k != field}
            with self.subTest(field=field), self.assertRaises(RappidError):
                verify_signed_document(partial)

    def test_an_unknown_alg_is_refused(self):
        rappid, _ = _identity()
        signed = sign_document({"id": "msg-1"}, SCALAR_A, rappid)
        signed["alg"] = "hmac-sha256"
        with self.assertRaises(RappidError):
            verify_signed_document(signed)

    def test_expected_from_mismatch_is_refused(self):
        rappid, _ = _identity()
        signed = sign_document({"id": "msg-1"}, SCALAR_A, rappid)
        with self.assertRaises(RappidError):
            verify_signed_document(signed, expected_from=f"rappid:@kody-w/other-001:{'a' * 64}")


class TestValidatorIntegration(unittest.TestCase):
    """The optional surface is genuinely optional, and genuinely checked."""

    @classmethod
    def setUpClass(cls):
        os.environ["VALIDATION_REPO_ROOT"] = str(BASE_DIR)
        cls.validate_action = importlib.import_module("validate_action")
        importlib.reload(cls.validate_action)

    def setUp(self):
        self.validate_action.errors.clear()
        self.validate_action.findings.clear()
        self.validate_action.summary_lines.clear()

    def _agent(self, **overrides):
        agent = {
            "id": "codebot-001",
            "name": "CodeBot",
            "world": "hub",
            "position": {"x": 0, "y": 0, "z": 0},
            "status": "active",
            "controller": "kody-w",
        }
        agent.update(overrides)
        return agent

    def test_an_agent_without_a_rappid_is_still_valid(self):
        """Every one of the 210 agents in the live world is this shape."""
        self.validate_action.validate_agent_identity(self._agent(), "codebot-001")
        self.assertEqual([], self.validate_action.errors)

    def test_a_well_formed_identity_passes(self):
        rappid, pub = _identity()
        self.validate_action.validate_agent_identity(
            self._agent(rappid=rappid, pub=pub), "codebot-001"
        )
        self.assertEqual([], self.validate_action.errors)

    def test_a_rappid_owned_by_someone_other_than_the_controller_is_refused(self):
        rappid, pub = _identity(owner="mallory")
        self.validate_action.validate_agent_identity(
            self._agent(rappid=rappid, pub=pub), "codebot-001"
        )
        self.assertTrue(
            any("does not match its controller" in e for e in self.validate_action.errors),
            self.validate_action.errors,
        )

    def test_a_slug_that_is_not_the_agent_id_is_refused(self):
        rappid, pub = _identity(slug="someone-else-001")
        self.validate_action.validate_agent_identity(
            self._agent(rappid=rappid, pub=pub), "codebot-001"
        )
        self.assertTrue(
            any("slug" in e for e in self.validate_action.errors), self.validate_action.errors
        )

    def test_a_key_that_does_not_bind_is_refused(self):
        rappid, _ = _identity(secret=SCALAR_A)
        _, other_pub = _identity(secret=SCALAR_B)
        self.validate_action.validate_agent_identity(
            self._agent(rappid=rappid, pub=other_pub), "codebot-001"
        )
        self.assertTrue(
            any("does not bind" in e for e in self.validate_action.errors),
            self.validate_action.errors,
        )

    def test_pub_without_rappid_is_refused(self):
        _, pub = _identity()
        self.validate_action.validate_agent_identity(self._agent(pub=pub), "codebot-001")
        self.assertTrue(
            any("without a `rappid`" in e for e in self.validate_action.errors),
            self.validate_action.errors,
        )

    def test_a_legacy_rappid_form_is_refused(self):
        self.validate_action.validate_agent_identity(
            self._agent(rappid=f"rappid:codebot:{'a' * 64}"), "codebot-001"
        )
        self.assertTrue(
            any("§6.1" in e for e in self.validate_action.errors), self.validate_action.errors
        )

    def test_unsigned_messages_are_untouched(self):
        """This is every message in state/chat.json today."""
        messages = [
            {"id": "msg-1", "author": {"id": "codebot-001", "name": "CodeBot"},
             "content": "hi", "world": "hub", "timestamp": "2026-08-04T00:00:00Z"}
        ]
        self.assertEqual(0, self.validate_action.validate_chat_signatures(messages))
        self.assertEqual([], self.validate_action.errors)

    def test_a_partially_signed_message_is_refused(self):
        rappid, pub = _identity()
        messages = [
            {"id": "msg-1", "author": {"id": "codebot-001"}, "content": "hi",
             "from": rappid, "pub": pub}
        ]
        self.validate_action.validate_chat_signatures(messages)
        self.assertTrue(
            any("partially signed" in e for e in self.validate_action.errors),
            self.validate_action.errors,
        )

    def test_a_signed_message_from_an_unregistered_author_is_refused(self):
        rappid, _ = _identity()
        signed = sign_document(
            {"id": "msg-1", "author": {"id": "not-an-agent-999"}, "content": "hi"},
            SCALAR_A, rappid,
        )
        self.validate_action.validate_chat_signatures([signed])
        self.assertTrue(
            any("no `rappid` registered" in e for e in self.validate_action.errors),
            self.validate_action.errors,
        )


class TestCli(unittest.TestCase):
    def test_mint_then_verify_a_signed_document(self):
        minted = json.loads(
            subprocess.run(
                [sys.executable, str(BASE_DIR / "scripts" / "rappid.py"),
                 "mint", "--owner", "kody-w", "--slug", "codebot-001"],
                capture_output=True, text=True, check=True,
            ).stdout
        )
        self.assertTrue(is_rappid(minted["rappid"]))
        verify_key_binding(minted["rappid"], minted["pub"])

        signed = subprocess.run(
            [sys.executable, str(BASE_DIR / "scripts" / "rappid.py"),
             "sign", "--rappid", minted["rappid"], "--secret", minted["secret_hex"]],
            input=json.dumps({"id": "msg-1", "content": "gm"}),
            capture_output=True, text=True, check=True,
        ).stdout
        result = subprocess.run(
            [sys.executable, str(BASE_DIR / "scripts" / "rappid.py"), "verify"],
            input=signed, capture_output=True, text=True,
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_verify_rejects_a_forgery_with_a_nonzero_exit(self):
        rappid, _ = _identity()
        signed = sign_document({"id": "msg-1", "content": "gm"}, SCALAR_A, rappid)
        signed["content"] = "forged"
        result = subprocess.run(
            [sys.executable, str(BASE_DIR / "scripts" / "rappid.py"), "verify"],
            input=json.dumps(signed), capture_output=True, text=True,
        )
        self.assertEqual(1, result.returncode)


class TestScopeBoundary(unittest.TestCase):
    """docs/SPEC_DRIFT.md D2: no half-envelope gets bolted on here."""

    def test_no_rapp1_frame_envelope_is_emitted(self):
        source = (BASE_DIR / "scripts" / "rappid.py").read_text(encoding="utf-8")
        for construct in ('"spec": "rapp/1"', "payload_hash", "frame_hash", "prev_wave"):
            self.assertNotIn(construct, source, f"§7 frame construct leaked in: {construct}")

    def test_no_local_kind_registry_is_invented(self):
        """rapp-map/ecosystem-spec.json is quarantined; no kind is registered anywhere."""
        self.assertFalse(hasattr(rappid, "KIND_REGISTRY"))
        self.assertFalse((BASE_DIR / "registry" / "kinds.json").exists())

    def test_the_identity_surface_is_documented(self):
        doc = BASE_DIR / "schema" / "identity.md"
        self.assertTrue(doc.is_file())
        text = doc.read_text(encoding="utf-8")
        self.assertIn("6723c7add2aed36bb68992fc71a56b0a4bd5ad81", text)
        self.assertIn("optional", text.lower())


if __name__ == "__main__":
    unittest.main(verbosity=2)
