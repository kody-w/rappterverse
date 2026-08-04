#!/usr/bin/env python3
"""RAPP/1 §6 identity — rappid grammar, mint-once minting, and key binding.

Authority: ``kody-w/rapp-1`` @ ``6723c7add2aed36bb68992fc71a56b0a4bd5ad81``,
``SPEC.md``, 41880 bytes, sha256
``6d06daba65d7c045716f3d6e95db8401ab58e727820e4114466d847f62cae49b``
(pin re-fetched and re-hashed before this module was written).

    §6.1  grammar        rappid:@<owner>/<slug>:<64 hex>
    §6.2  minting        keyless  tail = Hb("rapp/1:rappid", uuid4_octets)
                         keyed    tail = Hb("rapp/1:rappid", SPKI_DER)
    §6.3  canonicalize-on-read; provisional identifiers
    §5    Hb(space, b)   = lowercase_hex(SHA-256(utf8(space) || 0x0A || b))

Signature verification follows ``rapp-commons/events/SCHEMA.md`` "Verification
rules" 3 and 4 exactly: re-derive the SPKI DER from the base64url raw public
point, check the tail binding, then verify ECDSA P-256 over the canonical JSON
of the object with ``sig`` omitted (recursively sorted keys, no whitespace).

**What this module is not.** It does not emit a RAPP/1 §7 frame, and it does
not wrap anything in a ``rapp-commons-event/1.0`` envelope. See
``schema/identity.md`` and ``docs/SPEC_DRIFT.md`` D8 for exactly what is and is
not adopted, and why. Bolting on a half-envelope is the failure mode D2 warns
about; this is the identity layer only.

Everything below is stdlib-only (repo constraint). The ECDSA implementation is
verification-and-deterministic-signing over NIST P-256; it is not written to be
constant-time, which is sound for public-key verification and acceptable here
because the deterministic nonce (RFC 6979) removes the usual nonce-reuse
failure mode. Do not reuse it to guard a high-value secret against a local
timing attacker.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import re
import uuid

# ── RAPP/1 §6.1 grammar ──────────────────────────────────────────────────────
# lclabel = lcalnum *( ["-"] lcalnum )  — no leading, trailing or adjacent hyphen.
_LCLABEL = r"[a-z0-9](?:-?[a-z0-9])*"
RAPPID_RE = re.compile(rf"^rappid:@({_LCLABEL})/({_LCLABEL}):([0-9a-f]{{64}})$")

OWNER_MAX = 39   # a GitHub login
SLUG_MAX = 100

RAPPID_SPACE = "rapp/1:rappid"


class RappidError(ValueError):
    """A rappid, key or signature that RAPP/1 §6 says must be refused."""


def Hb(space: str, payload: bytes) -> str:
    """RAPP/1 §5 tagged hash: ``lowercase_hex(SHA-256(utf8(space) || 0x0A || b))``."""
    return hashlib.sha256(space.encode("utf-8") + b"\x0a" + payload).hexdigest()


def parse_rappid(value: str) -> tuple[str, str, str]:
    """Split a §6.1 rappid into ``(owner, slug, tail)`` or raise :class:`RappidError`.

    Lengths are normative: owner 1-39, slug 1-100. Longer MUST be refused.
    """
    if not isinstance(value, str):
        raise RappidError("rappid must be a string")
    match = RAPPID_RE.match(value)
    if not match:
        raise RappidError(
            f"not a RAPP/1 §6.1 rappid: {value!r} "
            "(expected rappid:@<owner>/<slug>:<64 lowercase hex>)"
        )
    owner, slug, tail = match.groups()
    if len(owner) > OWNER_MAX:
        raise RappidError(f"owner exceeds {OWNER_MAX} chars: {owner!r}")
    if len(slug) > SLUG_MAX:
        raise RappidError(f"slug exceeds {SLUG_MAX} chars: {slug!r}")
    return owner, slug, tail


def is_rappid(value) -> bool:
    try:
        parse_rappid(value)
        return True
    except RappidError:
        return False


def format_rappid(owner: str, slug: str, tail: str) -> str:
    candidate = f"rappid:@{owner.lower()}/{slug.lower()}:{tail.lower()}"
    parse_rappid(candidate)
    return candidate


def mint_keyless(owner: str, slug: str, uuid_octets: bytes | None = None) -> str:
    """§6.2 keyless mint: ``tail = Hb("rapp/1:rappid", uuid4_octets)``.

    Mint **once**, then store it. Re-minting is forbidden except by the
    owner-authorized §6.3 re-anchor.
    """
    octets = uuid_octets if uuid_octets is not None else uuid.uuid4().bytes
    if len(octets) != 16:
        raise RappidError("keyless mint requires the 16 octets of a UUIDv4")
    return format_rappid(owner, slug, Hb(RAPPID_SPACE, octets))


def mint_keyed(owner: str, slug: str, spki_der: bytes) -> str:
    """§6.2 keyed mint: ``tail = Hb("rapp/1:rappid", SPKI_DER)``."""
    return format_rappid(owner, slug, Hb(RAPPID_SPACE, spki_der))


def canonicalize_rappid(value: str, owner: str, slug: str) -> tuple[str, bool]:
    """§6.3 canonicalize-on-read. Returns ``(rappid, provisional)``.

    Restructures a legacy form into §6.1 **preserving the existing hash** — a
    tail is never invented on read. A restructured identifier whose tail is not
    exactly 64 lowercase hex is *provisional*: it exists only inside the reading
    process and MUST NOT be emitted or stored. Only the owner-authorized
    re-anchor can turn it into a usable identity.
    """
    if not isinstance(value, str):
        raise RappidError("rappid must be a string")
    if is_rappid(value):
        return value, False
    tail = value.rsplit(":", 1)[-1].strip().lower()
    if not re.fullmatch(r"[0-9a-f]+", tail or ""):
        raise RappidError(f"no recoverable hash in legacy identifier {value!r}")
    if len(tail) == 64:
        return format_rappid(owner, slug, tail), False
    return f"rappid:@{owner.lower()}/{slug.lower()}:{tail}", True


# ── base64url / canonical JSON ───────────────────────────────────────────────

def b64u_decode(value: str) -> bytes:
    if not isinstance(value, str):
        raise RappidError("expected a base64url string")
    padded = value + "=" * (-len(value) % 4)
    try:
        return base64.urlsafe_b64decode(padded.encode("ascii"))
    except (binascii.Error, UnicodeEncodeError) as exc:
        raise RappidError(f"invalid base64url: {exc}") from exc


def b64u_encode(payload: bytes) -> str:
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def canonical_json(obj) -> bytes:
    """rapp-commons verification rule 4: recursively sorted keys, no whitespace."""
    return json.dumps(
        obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def signing_bytes(document: dict) -> bytes:
    """The canonical bytes a ``sig`` covers: the document with ``sig`` omitted."""
    return canonical_json({k: v for k, v in document.items() if k != "sig"})


# ── NIST P-256 (secp256r1) ───────────────────────────────────────────────────

_P = 0xFFFFFFFF00000001000000000000000000000000FFFFFFFFFFFFFFFFFFFFFFFF
_A = _P - 3
_B = 0x5AC635D8AA3A93E7B3EBBD55769886BC651D06B0CC53B0F63BCE3C3E27D2604B
_N = 0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551
_GX = 0x6B17D1F2E12C4247F8BCE6E563A440F277037D812DEB33A0F4A13945D898C296
_GY = 0x4FE342E2FE1A7F9B8EE7EB4A7C0F9E162BCE33576B315ECECBB6406837BF51F5
_G = (_GX, _GY)

# DER SubjectPublicKeyInfo prefix for id-ecPublicKey + prime256v1, then the
# 65-octet uncompressed point. RFC 5280 §4.1.2.7 / RFC 5480 §2.
_SPKI_PREFIX = bytes.fromhex(
    "3059301306072a8648ce3d020106082a8648ce3d030107034200"
)


def _inv(value: int, modulus: int) -> int:
    return pow(value, -1, modulus)


def _add(p, q):
    if p is None:
        return q
    if q is None:
        return p
    x1, y1 = p
    x2, y2 = q
    if x1 == x2 and (y1 + y2) % _P == 0:
        return None
    if p == q:
        lam = (3 * x1 * x1 + _A) * _inv(2 * y1, _P) % _P
    else:
        lam = (y2 - y1) * _inv(x2 - x1, _P) % _P
    x3 = (lam * lam - x1 - x2) % _P
    return (x3, (lam * (x1 - x3) - y1) % _P)


def _mul(k: int, point):
    result = None
    addend = point
    k %= _N
    while k:
        if k & 1:
            result = _add(result, addend)
        addend = _add(addend, addend)
        k >>= 1
    return result


def _on_curve(point) -> bool:
    if point is None:
        return False
    x, y = point
    if not (0 <= x < _P and 0 <= y < _P):
        return False
    return (y * y - (x * x * x + _A * x + _B)) % _P == 0


def spki_der_from_raw_point(raw: bytes) -> bytes:
    """Build the DER SubjectPublicKeyInfo for a 65-octet uncompressed P-256 point."""
    if len(raw) != 65 or raw[0] != 0x04:
        raise RappidError(
            "public key must be the 65-octet uncompressed P-256 point (0x04 || X || Y)"
        )
    return _SPKI_PREFIX + raw


def raw_point_from_spki(der: bytes) -> bytes:
    if not der.startswith(_SPKI_PREFIX) or len(der) != len(_SPKI_PREFIX) + 65:
        raise RappidError("not a P-256 SubjectPublicKeyInfo")
    return der[len(_SPKI_PREFIX):]


def _point_from_raw(raw: bytes):
    if len(raw) != 65 or raw[0] != 0x04:
        raise RappidError("expected a 65-octet uncompressed point")
    point = (int.from_bytes(raw[1:33], "big"), int.from_bytes(raw[33:65], "big"))
    if not _on_curve(point):
        raise RappidError("public key is not a point on P-256")
    return point


def _decode_signature(sig: bytes) -> tuple[int, int]:
    """Accept either the 64-octet raw ``r||s`` (WebCrypto) or a DER SEQUENCE."""
    if len(sig) == 64:
        return int.from_bytes(sig[:32], "big"), int.from_bytes(sig[32:], "big")
    if not sig or sig[0] != 0x30:
        raise RappidError("signature is neither 64-octet raw r||s nor DER")
    body, offset = sig[1:], 0

    def _len(buf, idx):
        first = buf[idx]
        if first < 0x80:
            return first, idx + 1
        count = first & 0x7F
        return int.from_bytes(buf[idx + 1: idx + 1 + count], "big"), idx + 1 + count

    total, offset = _len(body, 0)
    if total != len(body) - offset:
        raise RappidError("malformed DER signature length")
    values = []
    for _ in range(2):
        if body[offset] != 0x02:
            raise RappidError("malformed DER signature: expected INTEGER")
        size, offset = _len(body, offset + 1)
        values.append(int.from_bytes(body[offset: offset + size], "big"))
        offset += size
    return values[0], values[1]


def ecdsa_p256_verify(raw_pub: bytes, message: bytes, signature: bytes) -> bool:
    """Verify an ECDSA P-256 / SHA-256 signature. Returns ``False``, never raises
    on a merely *wrong* signature — a malformed key still raises."""
    point = _point_from_raw(raw_pub)
    try:
        r, s = _decode_signature(signature)
    except RappidError:
        return False
    if not (1 <= r < _N and 1 <= s < _N):
        return False
    e = int.from_bytes(hashlib.sha256(message).digest(), "big")
    w = _inv(s, _N)
    combined = _add(_mul(e * w % _N, _G), _mul(r * w % _N, point))
    if combined is None:
        return False
    return combined[0] % _N == r


def _rfc6979_k(secret: int, digest: bytes) -> int:
    """RFC 6979 §3.2 deterministic nonce, HMAC-SHA256."""
    v = b"\x01" * 32
    k = b"\x00" * 32
    octets = secret.to_bytes(32, "big") + digest
    k = hmac.new(k, v + b"\x00" + octets, hashlib.sha256).digest()
    v = hmac.new(k, v, hashlib.sha256).digest()
    k = hmac.new(k, v + b"\x01" + octets, hashlib.sha256).digest()
    v = hmac.new(k, v, hashlib.sha256).digest()
    while True:
        v = hmac.new(k, v, hashlib.sha256).digest()
        candidate = int.from_bytes(v, "big")
        if 1 <= candidate < _N:
            return candidate
        k = hmac.new(k, v + b"\x00", hashlib.sha256).digest()
        v = hmac.new(k, v, hashlib.sha256).digest()


def ecdsa_p256_sign(secret: int, message: bytes) -> bytes:
    """Deterministic (RFC 6979) ECDSA P-256 signature as 64-octet raw ``r||s``."""
    if not 1 <= secret < _N:
        raise RappidError("private scalar out of range")
    digest = hashlib.sha256(message).digest()
    e = int.from_bytes(digest, "big")
    while True:
        k = _rfc6979_k(secret, digest)
        point = _mul(k, _G)
        r = point[0] % _N
        if r == 0:
            continue
        s = _inv(k, _N) * (e + r * secret) % _N
        if s == 0:
            continue
        if s > _N // 2:          # low-S, the usual canonical form
            s = _N - s
        return r.to_bytes(32, "big") + s.to_bytes(32, "big")


def public_point(secret: int) -> bytes:
    """The 65-octet uncompressed public point for a private scalar."""
    point = _mul(secret, _G)
    return b"\x04" + point[0].to_bytes(32, "big") + point[1].to_bytes(32, "big")


# ── the two checks that make author.id a proof instead of an assertion ───────

def verify_key_binding(rappid: str, pub_b64u: str) -> None:
    """rapp-commons verification rule 3 / RAPP/1 §10 key discovery.

    Re-derives the SPKI DER from the base64url raw public point and checks
    ``Hb("rapp/1:rappid", SPKI_DER)`` equals the rappid's tail. Raises on
    mismatch — this is the check that makes a keyed rappid self-certifying.
    """
    _, _, tail = parse_rappid(rappid)
    spki = spki_der_from_raw_point(b64u_decode(pub_b64u))
    derived = Hb(RAPPID_SPACE, spki)
    if not hmac.compare_digest(derived, tail):
        raise RappidError(
            "key does not bind to this rappid: "
            f'Hb("{RAPPID_SPACE}", SPKI_DER) = {derived[:12]}…, tail = {tail[:12]}…'
        )


def verify_signed_document(document: dict, expected_from: str | None = None) -> None:
    """Verify a signed document's identity claim end to end.

    Checks, in order: the required fields are present; ``alg`` is the one
    algorithm this profile defines; ``from`` is a §6.1 rappid; the key binds to
    that rappid (rule 3); and ``sig`` verifies over the canonical JSON of the
    document with ``sig`` omitted (rule 4). Raises :class:`RappidError` with a
    specific reason on any failure.
    """
    for field in ("from", "pub", "alg", "sig"):
        if field not in document:
            raise RappidError(f"signed document is missing `{field}`")
    if document["alg"] != "ecdsa-p256":
        raise RappidError(f"unsupported alg {document['alg']!r} (expected 'ecdsa-p256')")

    claimed = document["from"]
    parse_rappid(claimed)
    if expected_from is not None and claimed != expected_from:
        raise RappidError(
            f"`from` {claimed} does not match the registered rappid {expected_from}"
        )
    verify_key_binding(claimed, document["pub"])
    if not ecdsa_p256_verify(
        b64u_decode(document["pub"]),
        signing_bytes(document),
        b64u_decode(document["sig"]),
    ):
        raise RappidError("signature does not verify over the canonical bytes")


def sign_document(document: dict, secret: int, rappid: str) -> dict:
    """Return ``document`` with ``from``/``pub``/``alg``/``sig`` filled in."""
    raw_pub = public_point(secret)
    signed = {k: v for k, v in document.items() if k != "sig"}
    signed["from"] = rappid
    signed["pub"] = b64u_encode(raw_pub)
    signed["alg"] = "ecdsa-p256"
    verify_key_binding(rappid, signed["pub"])
    signed["sig"] = b64u_encode(ecdsa_p256_sign(secret, canonical_json(signed)))
    return signed


def _cli(argv=None) -> int:
    import argparse
    import secrets
    import sys

    parser = argparse.ArgumentParser(
        prog="rappid.py", description="RAPP/1 §6 identity for RAPPterverse agents"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    mint = sub.add_parser("mint", help="mint a keyed rappid and a fresh private key")
    mint.add_argument("--owner", required=True, help="your lowercase GitHub login")
    mint.add_argument("--slug", required=True, help="the agent id, e.g. codebot-001")

    show = sub.add_parser("pub", help="show the rappid and public key for a private key")
    show.add_argument("--owner", required=True)
    show.add_argument("--slug", required=True)
    show.add_argument("--secret", required=True, help="private scalar, hex")

    sign = sub.add_parser("sign", help="sign a JSON document read from stdin")
    sign.add_argument("--rappid", required=True)
    sign.add_argument("--secret", required=True, help="private scalar, hex")

    check = sub.add_parser("verify", help="verify a signed JSON document from stdin")

    args = parser.parse_args(argv)

    if args.command == "mint":
        secret = secrets.randbelow(_N - 1) + 1
        rappid = mint_keyed(args.owner, args.slug, spki_der_from_raw_point(public_point(secret)))
        print(json.dumps({
            "rappid": rappid,
            "pub": b64u_encode(public_point(secret)),
            "secret_hex": f"{secret:064x}",
            "warning": "Keep secret_hex out of the repository. It is your identity.",
        }, indent=2))
        return 0

    if args.command == "pub":
        secret = int(args.secret, 16)
        rappid = mint_keyed(args.owner, args.slug, spki_der_from_raw_point(public_point(secret)))
        print(json.dumps({"rappid": rappid, "pub": b64u_encode(public_point(secret))}, indent=2))
        return 0

    if args.command == "sign":
        document = json.load(sys.stdin)
        print(json.dumps(sign_document(document, int(args.secret, 16), args.rappid), indent=4))
        return 0

    if args.command == "verify":
        document = json.load(sys.stdin)
        try:
            verify_signed_document(document)
        except RappidError as exc:
            print(f"✗ {exc}")
            return 1
        print(f"✓ signature verifies and binds to {document['from']}")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(_cli())
