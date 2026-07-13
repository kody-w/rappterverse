# SPDX-License-Identifier: Apache-2.0
"""Domain-separated deterministic IDs, seed draws, and pack digests."""

from __future__ import annotations

import base64
import copy
import hashlib
import hmac
from typing import Dict, Iterable, Mapping, Sequence, Tuple

from .canonical import canonical_json_v2

STABLE_ID_DOMAIN = "rappterverse-stable-entity-id/v1"
SEED_EXTRACT_DOMAIN = b"rappterverse-world-pack-seed-extract/v1\0"
SEED_EXPAND_DOMAIN = b"rappterverse-world-pack-seed-expand/v1\0"
DRAW_DOMAIN = b"rappterverse-world-pack-draw/v1\0"
PACK_LEAF_DOMAIN = b"rappterverse-world-pack-leaf/v1\0"
PACK_TREE_DOMAIN = b"rappterverse-world-pack-tree/v1\0"
SOURCE_CLOSURE_DOMAIN = b"rappterverse-source-closure/v1\0"
IMPLEMENTATION_DOMAIN = b"rappterverse-compiler-implementation/v1\0"
MAX_REJECTION_ATTEMPTS = 256


class CryptoError(ValueError):
    """Raised for an invalid deterministic cryptographic operation."""


def _frame(value: bytes) -> bytes:
    return len(value).to_bytes(8, "big") + value


def sha256_prefixed(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def stable_identity_digest(
    identity_namespace: str,
    entity_kind: str,
    identity_record_id: str,
    stable_id_input: str,
) -> str:
    material = [
        STABLE_ID_DOMAIN,
        identity_namespace,
        entity_kind,
        identity_record_id,
        stable_id_input,
    ]
    return hashlib.sha256(canonical_json_v2(material)).hexdigest()


def stable_display_id(prefix: str, digest_hex: str, length: int) -> str:
    try:
        digest = bytes.fromhex(digest_hex)
    except ValueError as exc:
        raise CryptoError("identity digest must be lowercase hexadecimal") from exc
    encoded = base64.b32encode(digest).decode("ascii").rstrip("=").lower()
    if length < 1 or length > len(encoded):
        raise CryptoError("stable ID display length is outside bounds")
    return "{}-{}".format(prefix, encoded[:length])


def hkdf_extract(salt: bytes, ikm: bytes) -> bytes:
    return hmac.new(salt, ikm, hashlib.sha256).digest()


def hkdf_expand(prk: bytes, info: bytes, length: int) -> bytes:
    if length < 1 or length > 255 * hashlib.sha256().digest_size:
        raise CryptoError("HKDF output length is outside bounds")
    result = b""
    block = b""
    counter = 1
    while len(result) < length:
        block = hmac.new(
            prk, block + info + bytes([counter]), hashlib.sha256
        ).digest()
        result += block
        counter += 1
    return result[:length]


def derive_channel_root(
    channel: str,
    seed: str,
    identity_namespace: str,
    source_namespace: str,
) -> bytes:
    salt = hashlib.sha256(
        SEED_EXTRACT_DOMAIN + _frame(channel.encode("utf-8"))
    ).digest()
    prk = hkdf_extract(salt, seed.encode("utf-8"))
    info = (
        SEED_EXPAND_DOMAIN
        + _frame(channel.encode("utf-8"))
        + _frame(identity_namespace.encode("utf-8"))
        + _frame(source_namespace.encode("utf-8"))
    )
    return hkdf_expand(prk, info, 32)


class SeedBank:
    """Independent counter-addressed deterministic seed channels."""

    def __init__(
        self,
        seeds: Mapping[str, str],
        identity_namespace: str,
        source_namespace: str,
        required_channels: Sequence[str],
    ) -> None:
        if set(seeds) != set(required_channels) or len(seeds) != len(
            required_channels
        ):
            raise CryptoError("seed channel set must match the trusted profile")
        self._roots = {
            channel: derive_channel_root(
                channel,
                seeds[channel],
                identity_namespace,
                source_namespace,
            )
            for channel in required_channels
        }

    def root_digests(self) -> Dict[str, str]:
        return {
            channel: sha256_prefixed(root)
            for channel, root in sorted(self._roots.items())
        }

    def draw(self, channel: str, entity_id: str, purpose: str, index: int) -> bytes:
        if channel not in self._roots:
            raise CryptoError("unknown seed channel {!r}".format(channel))
        if not entity_id or not purpose or index < 0:
            raise CryptoError("draw address is invalid")
        message = (
            DRAW_DOMAIN
            + _frame(channel.encode("utf-8"))
            + _frame(entity_id.encode("utf-8"))
            + _frame(purpose.encode("utf-8"))
            + index.to_bytes(8, "big")
        )
        return hmac.new(self._roots[channel], message, hashlib.sha256).digest()

    def bounded_int(
        self,
        channel: str,
        entity_id: str,
        purpose: str,
        index: int,
        upper_bound: int,
    ) -> int:
        if isinstance(upper_bound, bool) or not isinstance(upper_bound, int):
            raise CryptoError("bounded integer upper bound must be an integer")
        if upper_bound <= 0:
            raise CryptoError("bounded integer upper bound must be positive")
        space = 1 << 256
        if upper_bound > space:
            raise CryptoError(
                "bounded integer upper bound exceeds the SHA-256 sample space"
            )
        cutoff = space - (space % upper_bound)
        attempt = 0
        while attempt < MAX_REJECTION_ATTEMPTS:
            block = self.draw(
                channel,
                entity_id,
                "{}#{}".format(purpose, attempt),
                index,
            )
            candidate = int.from_bytes(block, "big")
            if candidate < cutoff:
                return candidate % upper_bound
            attempt += 1
        raise CryptoError("rejection sampler exceeded deterministic limit")


def source_closure_digest(closure_without_digest: Mapping[str, object]) -> str:
    normalized = copy.deepcopy(dict(closure_without_digest))
    for key in ("recordArtifacts", "worldPackSources", "projectionRecipes"):
        if isinstance(normalized.get(key), list):
            normalized[key] = sorted(
                normalized[key],
                key=canonical_json_v2,
            )
    if isinstance(normalized.get("records"), list):
        normalized["records"] = sorted(
            normalized["records"],
            key=canonical_json_v2,
        )
    proof = normalized.get("verificationProof")
    if isinstance(proof, dict) and isinstance(proof.get("reviewReceipts"), list):
        proof["reviewReceipts"] = sorted(
            proof["reviewReceipts"],
            key=canonical_json_v2,
        )
    return sha256_prefixed(
        SOURCE_CLOSURE_DOMAIN + canonical_json_v2(normalized)
    )


def pack_leaf_hash(path: str, data: bytes, mode: str = "100644") -> str:
    path_bytes = path.encode("utf-8")
    mode_bytes = mode.encode("ascii")
    material = (
        PACK_LEAF_DOMAIN
        + _frame(path_bytes)
        + _frame(mode_bytes)
        + _frame(data)
    )
    return hashlib.sha256(material).hexdigest()


def pack_tree_root(files: Mapping[str, bytes]) -> str:
    entries = []
    for path in sorted(files):
        path_bytes = path.encode("utf-8")
        leaf = bytes.fromhex(pack_leaf_hash(path, files[path]))
        entries.append(_frame(path_bytes) + leaf)
    material = (
        PACK_TREE_DOMAIN
        + len(entries).to_bytes(8, "big")
        + b"".join(entries)
    )
    return "sha256:" + hashlib.sha256(material).hexdigest()


def implementation_digest(
    source_files: Iterable[Tuple[str, bytes]]
) -> str:
    entries = []
    for path, data in sorted(source_files, key=lambda item: item[0]):
        entries.append(_frame(path.encode("utf-8")) + _frame(data))
    return sha256_prefixed(
        IMPLEMENTATION_DOMAIN
        + len(entries).to_bytes(8, "big")
        + b"".join(entries)
    )
