# SPDX-License-Identifier: Apache-2.0
"""Immutable engine-owned compiler trust pins."""

from __future__ import annotations

from typing import Tuple

TRUSTED_PROFILE_PATH = "compiler/profiles/rappterverse-v1.json"
TRUSTED_PROFILE_RAW_SHA256 = (
    "b3ccc178a4a6bdabf0e5989b66a3caf407e258147fcf0460d00cc0372fdfdae5"
)

LEGACY_LOCK_PATH = "bootstrap/legacy-source-lock.json"
LEGACY_LOCK_RAW_SHA256 = (
    "169e7bed296edf964df5002393d4efe1cdcce74d08bad829e34301fe00191ff1"
)
LEGACY_REPOSITORY = "kody-w/rappterverse"
LEGACY_MAIN_COMMIT = "676fdda8d3881a284bdb0c09174ee76acc0c9219"
LEGACY_MAIN_TREE = "9790c8f85a183f5541c59a86082f65da5a5aa3c2"

# (repository-relative path, exact byte count, raw SHA-256)
LEGACY_REQUIRED_SOURCE_DESCRIPTORS: Tuple[Tuple[str, int, str], ...] = (
    (
        "src/js/abilities.js",
        16015,
        "bf91bebaa4e2d6714eb2b376b4e2dbccd5c47327eb592e34cabf7dbe693edfa4",
    ),
    (
        "src/js/config.js",
        9280,
        "98cacc0fa3ad9ba5f90053801f7c783d5a3defaf0226ca660a699ad81de25744",
    ),
    (
        "src/js/equipment.js",
        6173,
        "90b0a97afde0a753100834e77a118f4d35eb2bba58d4f27c3fb7868eb0672677",
    ),
    (
        "src/js/inventory.js",
        13789,
        "f29e766646f8921489b4469c5438216f9f806725e355f2087c49d11f9141662e",
    ),
    (
        "worlds/arena/config.json",
        537,
        "e5cedc8c71d3b0be817f41356d6e41a40f216469ed7d9d7042328c5023c69e38",
    ),
    (
        "worlds/arena/npcs.json",
        3790,
        "4f7d694e07582661562e43f04341f7b746e7a91a0b9bcdec4c3ef3f42a98d30d",
    ),
    (
        "worlds/arena/objects.json",
        3280,
        "04bd0cbdbc50e2502e2ada27cbaf366e64cc9fde0601083c5b7a03f1f367b369",
    ),
    (
        "worlds/dungeon/config.json",
        788,
        "fb3cc09c66a9cd6c4997d56c79e31ea76d4524f4ad7fa6005a86a3d451cd94cd",
    ),
    (
        "worlds/dungeon/npcs.json",
        7436,
        "79f60203f0374fb75ff468e81ae46cff68bb1bf5f4d07b67ee4722c76146f510",
    ),
    (
        "worlds/dungeon/objects.json",
        9654,
        "513525e9cf6bc933a6c0a1d4b2da7ef50f6b1aac2043606ddd99e7e16950872f",
    ),
    (
        "worlds/gallery/config.json",
        519,
        "8241c56103bc2e64df4ddc72aace6ef8826391d189e9ff162d86a54ac53cf5e7",
    ),
    (
        "worlds/gallery/npcs.json",
        3728,
        "a7ac8ef14bbbda1109dca4f7059a71a137d72193dd9f3136d79d90f76fc89e68",
    ),
    (
        "worlds/gallery/objects.json",
        2794,
        "048a7bfa2d2a9ec00dafe7521f4cdacf8bf81cb0c22f45f8c3ffa7b82a2c400a",
    ),
    (
        "worlds/hub/config.json",
        692,
        "9ea72252022ee805a1db7c18ab6bac9c7f730380693191eb65e3434b6673c753",
    ),
    (
        "worlds/hub/npcs.json",
        11112,
        "f53e042e3cea96517638c61d04b1fd28cfff3c6f1cf8244b97f8ba37dda15c34",
    ),
    (
        "worlds/hub/objects.json",
        15921,
        "db91b5173088b4cc583ab6fcab10e5884a61f25fe5b39db573d607177e2ebc1c",
    ),
    (
        "worlds/marketplace/config.json",
        560,
        "7732529c1ad20fefd96ff7f6a3fcd5664adc00e33f796e24d2bac9b87a6b8ef5",
    ),
    (
        "worlds/marketplace/npcs.json",
        4556,
        "d54b2a185c651e53fee24c973e075b3e19a6f398457147de2f88520ca13f8612",
    ),
    (
        "worlds/marketplace/objects.json",
        2812,
        "87667868c59f2a3cab261c1f433c7ed0cb659a58c0ef36ed62853c5e616d1d02",
    ),
)
