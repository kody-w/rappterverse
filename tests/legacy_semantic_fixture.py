"""Independent semantic builder for the pinned legacy-v1 golden."""

from __future__ import annotations

import ast
import hashlib
import json
import re
import subprocess
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, Mapping, Sequence, Set, Tuple

COMMIT = "676fdda8d3881a284bdb0c09174ee76acc0c9219"
WORLD_IDS = ("hub", "arena", "marketplace", "gallery", "dungeon")
STATIC_PATHS = tuple(
    "worlds/{}/{}.json".format(world_id, name)
    for world_id in WORLD_IDS
    for name in ("config", "objects", "npcs")
)
FRONTEND_PATHS = (
    "src/js/config.js",
    "src/js/inventory.js",
    "src/js/abilities.js",
    "src/js/equipment.js",
)
_TOKEN = re.compile(
    r"-?(?:0[xX][0-9a-fA-F]+|[0-9]+(?:\.[0-9]+)?)"
    r"|[A-Za-z_$][A-Za-z0-9_$-]*"
)
_CATALOG_ALIASES = {
    "damage": "baseDamage",
    "hp": "baseHp",
    "position": "placementDefinition",
    "status": "statusDefinition",
}
LEGACY_PACK_ROOT = (
    "sha256:813c41f3848d221c10988b2b3f12767ceb18c5699bb794c82f929b2d6f1a5a8f"
)
LEGACY_SEMANTIC_GOLDEN = {
    "abilities": {
        "count": 5,
        "sha256": "25626fddb73bec84d3a32760d92ff7ef279fdef32e1daa293369786cd9e0af98",
    },
    "equipment-items": {
        "count": 11,
        "sha256": "ed06c0fa946c2a20f2dab8a45c4427c2522bca63e269a875e6236f8aa2fd8421",
    },
    "equipment-slots": {
        "count": 3,
        "sha256": "8e38796d5df996370acd5d5c518f921d45afac57c2e73d9a8429ccfe79f62bb3",
    },
    "frontend-worlds": {
        "count": 5,
        "sha256": "ad27bec62953ff7c5b35a748437cf001673de894d9e92bda93d49375d89e39b1",
    },
    "inventory-items": {
        "count": 13,
        "sha256": "1419f842660c618bb78926af47a8f7549ea3ae2faf76319a43473e1fb45c39b3",
    },
    "item-records": {
        "count": 13,
        "sha256": "cb20448659daa44c59ddd8c3a9433bcf5ae978322b8c788789a959ede335ebf5",
    },
    "portal-endpoints": {
        "count": 9,
        "sha256": "531eedff1b5bd8e1e360d6e7bea79f59e6bd24ca5c08402b8bd51e28bf663b12",
    },
    "source-blobs": {
        "count": 19,
        "sha256": "8fbdff74a458bf148a5e7df4aad903efa22f63d4dccae72b98c40cebbcbaa4d4",
    },
    "world-configs": {
        "count": 5,
        "sha256": "0324af7a70e06f5bc43f489ff3639a9336f6e4e7e44f6c6546765cb0e592b00d",
    },
    "world-index": {
        "count": 5,
        "sha256": "d73be3fabf453d17917aa731ccba25a648f23be315babb035546f361b87ddd34",
    },
    "world-npcs": {
        "count": 32,
        "sha256": "6e53c8bdaf0ae7fa7199b7f77f0068ca31e674246db35899e52eebcc2b1a40ce",
    },
    "world-objects": {
        "count": 102,
        "sha256": "035432d0eadea910885061f72849b64d990e6f50240a04200f73afdba2a86284",
    },
}


def _git_blob(root: Path, path: str) -> bytes:
    return subprocess.check_output(
        ["git", "-C", str(root), "show", "{}:{}".format(COMMIT, path)]
    )


def _literal_slice(
    text: str, marker: str, terminator: str
) -> str:
    if text.count(marker) != 1:
        raise AssertionError("golden marker is not unique: {}".format(marker))
    index = text.index(marker) + len(marker)
    while index < len(text) and text[index].isspace():
        index += 1
    if index >= len(text) or text[index] not in "[{":
        raise AssertionError("golden marker has no literal RHS")
    start = index
    stack = []
    quote = None
    while index < len(text):
        character = text[index]
        if quote is not None:
            if character == "\\":
                index += 2
                continue
            if character == quote:
                quote = None
            index += 1
            continue
        if text.startswith("//", index):
            end = text.find("\n", index + 2)
            index = len(text) if end < 0 else end + 1
            continue
        if text.startswith("/*", index):
            end = text.find("*/", index + 2)
            if end < 0:
                raise AssertionError("unterminated golden comment")
            index = end + 2
            continue
        if character in ("'", '"'):
            quote = character
        elif character in "[{":
            stack.append("]" if character == "[" else "}")
        elif character in "]}":
            if not stack or stack.pop() != character:
                raise AssertionError("unbalanced golden literal")
            if not stack:
                end = index + 1
                index = end
                while index < len(text) and text[index].isspace():
                    index += 1
                if not text.startswith(terminator, index):
                    raise AssertionError("unexpected golden literal terminator")
                return text[start:end]
        index += 1
    raise AssertionError("unterminated golden literal")


def _python_literal(source: str) -> str:
    output = []
    index = 0
    while index < len(source):
        character = source[index]
        if character.isspace() or character in "{}[]:,":
            output.append(character)
            index += 1
            continue
        if source.startswith("//", index):
            end = source.find("\n", index + 2)
            index = len(source) if end < 0 else end
            continue
        if source.startswith("/*", index):
            end = source.find("*/", index + 2)
            if end < 0:
                raise AssertionError("unterminated golden comment")
            index = end + 2
            continue
        if character in ("'", '"'):
            quote = character
            end = index + 1
            while end < len(source):
                if source[end] == "\\":
                    end += 2
                    continue
                if source[end] == quote:
                    end += 1
                    break
                end += 1
            else:
                raise AssertionError("unterminated golden string")
            output.append(source[index:end])
            index = end
            continue
        match = _TOKEN.match(source, index)
        if not match:
            raise AssertionError("non-literal golden token")
        token = match.group(0)
        index = match.end()
        if token == "true":
            output.append("True")
        elif token == "false":
            output.append("False")
        elif token == "null":
            output.append("None")
        elif re.fullmatch(r"-?[0-9]+\.[0-9]+", token):
            output.append(repr(token))
        elif re.match(r"[A-Za-z_$]", token):
            lookahead = index
            while lookahead < len(source) and source[lookahead].isspace():
                lookahead += 1
            if lookahead >= len(source) or source[lookahead] != ":":
                raise AssertionError("non-key identifier in golden literal")
            output.append(repr(token))
        else:
            output.append(token)
    return "".join(output)


def _extract(
    data: bytes, marker: str, terminator: str
) -> Any:
    text = data.decode("utf-8", errors="strict")
    literal = _literal_slice(text, marker, terminator)
    return ast.literal_eval(_python_literal(literal))


def _json(data: bytes) -> Dict[str, Any]:
    return json.loads(data, parse_float=lambda token: token)


def _normalized(key: str) -> str:
    return "".join(
        character.lower() for character in key if character.isalnum()
    )


def _sanitize(value: Any, protected: Set[str]) -> Any:
    if isinstance(value, dict):
        return {
            key: _sanitize(child, protected)
            for key, child in sorted(value.items())
            if _normalized(key) not in protected
        }
    if isinstance(value, list):
        return [_sanitize(child, protected) for child in value]
    return value


def _catalog(value: Any, protected: Set[str]) -> Any:
    if isinstance(value, dict):
        result = {}
        for key, child in sorted(value.items()):
            normalized = _normalized(key)
            if key in _CATALOG_ALIASES:
                output_key = _CATALOG_ALIASES[key]
            elif normalized in protected:
                continue
            else:
                output_key = key
            if output_key in result:
                raise AssertionError("golden catalog key collision")
            result[output_key] = _catalog(child, protected)
        return result
    if isinstance(value, list):
        return [_catalog(child, protected) for child in value]
    return value


def _clamp(
    point: Mapping[str, Any], bounds: Mapping[str, Sequence[int]]
) -> Dict[str, Any]:
    result = dict(point)
    for axis in ("x", "z"):
        numeric = Decimal(point[axis])
        result[axis] = (
            bounds[axis][0]
            if numeric < bounds[axis][0]
            else bounds[axis][1]
            if numeric > bounds[axis][1]
            else point[axis]
        )
    return result


def build_expected_domains(root: Path) -> Dict[str, Any]:
    blobs = {
        path: _git_blob(root, path)
        for path in STATIC_PATHS + FRONTEND_PATHS
    }
    profile = json.loads(
        (root / "compiler" / "profiles" / "rappterverse-v1.json").read_text(
            encoding="utf-8"
        )
    )
    protected = {
        _normalized(name)
        for name in (
            profile["overlayProtection"]["publicPreservedFields"]
            + profile["overlayProtection"]["denylist"]
        )
    }
    frontend_worlds = _sanitize(
        _extract(blobs["src/js/config.js"], "const WORLDS =", ";"),
        protected,
    )
    world_ids = _extract(
        blobs["src/js/config.js"], "const WORLD_IDS =", ";"
    )
    if world_ids != list(WORLD_IDS):
        raise AssertionError("golden world ID contract changed")
    inventory = _catalog(
        _extract(blobs["src/js/inventory.js"], "ITEMS:", ","),
        protected,
    )
    abilities = _catalog(
        _extract(blobs["src/js/abilities.js"], "defs:", ","),
        protected,
    )
    slots = _sanitize(
        _extract(
            blobs["src/js/equipment.js"], "const EQUIPMENT_SLOTS =", ";"
        ),
        protected,
    )
    equipment = _catalog(
        _extract(
            blobs["src/js/equipment.js"], "const EQUIPMENT_MAP =", ";"
        ),
        protected,
    )

    world_index = []
    world_configs = {}
    world_objects = {}
    world_npcs = {}
    portals = []
    for order, world_id in enumerate(WORLD_IDS):
        config_path = "worlds/{}/config.json".format(world_id)
        source_config = _json(blobs[config_path])
        required_config_keys = {
            "bounds",
            "created",
            "description",
            "features",
            "id",
            "name",
            "settings",
            "spawn",
            "version",
        }
        if not (
            required_config_keys <= set(source_config)
            and set(source_config) <= required_config_keys | {"lastUpdated"}
        ):
            raise AssertionError("golden world config fields changed")
        summary = {
            "bounds": source_config["bounds"],
            "description": source_config["description"],
            "id": world_id,
            "kind": "world",
            "name": source_config["name"],
            "order": order,
            "stableKey": world_id,
        }
        world_index.append(summary)
        world_configs[world_id] = {
            **summary,
            "features": _sanitize(source_config["features"], protected),
            "renderer": {
                "compatibility": frontend_worlds[world_id],
                "unitsPerSimulationUnit": 10,
            },
            "schemaVersion": "rappterverse.world-config/v1",
            "settings": _sanitize(source_config["settings"], protected),
            "spawn": source_config["spawn"],
            "version": source_config["version"],
        }
        bounds = source_config["bounds"]

        object_path = "worlds/{}/objects.json".format(world_id)
        object_rows = []
        for source in _json(blobs[object_path])["objects"]:
            kind = "portal" if source.get("type") == "portal" else "object"
            defaults = _sanitize(
                {
                    key: value
                    for key, value in source.items()
                    if key not in ("id", "position", "destination")
                },
                protected,
            )
            row = {
                "defaults": defaults,
                "id": source["id"],
                "kind": kind,
                "name": source.get("name", source["id"]),
                "placement": _clamp(source["position"], bounds),
                "stableKey": source["id"],
                "worldId": world_id,
            }
            if kind == "portal":
                row["destinationWorldId"] = source["destination"]
                portals.append(
                    {
                        "destinationWorldId": source["destination"],
                        "id": source["id"],
                        "worldId": world_id,
                    }
                )
            object_rows.append(row)
        world_objects[world_id] = object_rows

        npc_path = "worlds/{}/npcs.json".format(world_id)
        npc_rows = []
        for source in _json(blobs[npc_path])["npcs"]:
            defaults = _sanitize(
                {
                    key: value
                    for key, value in source.items()
                    if key
                    not in (
                        "id",
                        "name",
                        "position",
                        "dialogue",
                        "patrolPath",
                        "rotation",
                        "inventory",
                        "agentId",
                        "schedule",
                    )
                },
                protected,
            )
            if "dialogue" in source:
                defaults["fallbackDialogue"] = source["dialogue"]
            if "patrolPath" in source:
                defaults["patrolRoute"] = [
                    _clamp(point, bounds) for point in source["patrolPath"]
                ]
            if "rotation" in source:
                defaults["spawnRotation"] = source["rotation"]
            if "agentId" in source:
                defaults["agentBlueprintId"] = source["agentId"]
            if "schedule" in source:
                defaults["scheduleDefinition"] = _sanitize(
                    source["schedule"], protected
                )
            defaults = _sanitize(defaults, protected)
            npc_rows.append(
                {
                    "defaults": defaults,
                    "id": source["id"],
                    "kind": "npc-blueprint",
                    "name": source.get("name", source["id"]),
                    "spawn": _clamp(source["position"], bounds),
                    "stableKey": source["id"],
                    "worldId": world_id,
                }
            )
        world_npcs[world_id] = npc_rows

    return {
        "abilities": abilities,
        "equipment-items": equipment,
        "equipment-slots": slots,
        "frontend-worlds": frontend_worlds,
        "inventory-items": inventory,
        "item-records": [
            {
                "defaults": item,
                "id": item_id,
                "kind": "item",
                "name": item.get("name", item_id),
            }
            for item_id, item in sorted(inventory.items())
        ],
        "portal-endpoints": sorted(
            portals,
            key=lambda item: (
                item["worldId"],
                item["id"],
                item["destinationWorldId"],
            ),
        ),
        "source-blobs": [
            {
                "bytes": len(blobs[path]),
                "path": path,
                "sha256": "sha256:" + hashlib.sha256(blobs[path]).hexdigest(),
            }
            for path in sorted(blobs)
        ],
        "world-configs": world_configs,
        "world-index": world_index,
        "world-npcs": world_npcs,
        "world-objects": world_objects,
    }


def _stored_json(data: bytes) -> Any:
    return json.loads(data.decode("utf-8"))


def _without_identity(row: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        key: value
        for key, value in row.items()
        if key not in ("identitySha256", "provenanceId")
    }


def build_actual_domains(files: Mapping[str, bytes]) -> Dict[str, Any]:
    compatibility = _stored_json(files["legacy-compatibility.json"])
    economy = _stored_json(files["economy.json"])
    return {
        "abilities": compatibility["catalogs"]["abilities"],
        "equipment-items": compatibility["catalogs"]["equipment"]["items"],
        "equipment-slots": compatibility["catalogs"]["equipment"]["slots"],
        "frontend-worlds": compatibility["worlds"],
        "inventory-items": compatibility["catalogs"]["inventoryItems"],
        "item-records": [
            _without_identity(row) for row in economy["items"]
        ],
        "portal-endpoints": compatibility["portalEndpoints"],
        "source-blobs": compatibility["sourceBlobs"],
        "world-configs": {
            world_id: _without_identity(
                _stored_json(
                    files["worlds/{}/config.json".format(world_id)]
                )
            )
            for world_id in WORLD_IDS
        },
        "world-index": [
            _without_identity(row)
            for row in _stored_json(files["worlds.json"])["worlds"]
        ],
        "world-npcs": {
            world_id: [
                _without_identity(row)
                for row in _stored_json(
                    files["worlds/{}/npcs.json".format(world_id)]
                )["npcs"]
            ]
            for world_id in WORLD_IDS
        },
        "world-objects": {
            world_id: [
                _without_identity(row)
                for row in _stored_json(
                    files["worlds/{}/objects.json".format(world_id)]
                )["objects"]
            ]
            for world_id in WORLD_IDS
        },
    }


def semantic_summary(domains: Mapping[str, Any]) -> Dict[str, Dict[str, Any]]:
    counts = {
        "abilities": len(domains["abilities"]),
        "equipment-items": len(domains["equipment-items"]),
        "equipment-slots": len(domains["equipment-slots"]),
        "frontend-worlds": len(domains["frontend-worlds"]),
        "inventory-items": len(domains["inventory-items"]),
        "item-records": len(domains["item-records"]),
        "portal-endpoints": len(domains["portal-endpoints"]),
        "source-blobs": len(domains["source-blobs"]),
        "world-configs": len(domains["world-configs"]),
        "world-index": len(domains["world-index"]),
        "world-npcs": sum(len(rows) for rows in domains["world-npcs"].values()),
        "world-objects": sum(
            len(rows) for rows in domains["world-objects"].values()
        ),
    }
    return {
        name: {
            "count": counts[name],
            "sha256": hashlib.sha256(
                json.dumps(
                    value,
                    ensure_ascii=False,
                    allow_nan=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest(),
        }
        for name, value in sorted(domains.items())
    }
