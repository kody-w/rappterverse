#!/usr/bin/env python3
"""Behavioral parity tests for canonical and vendored Dreamcatcher modules."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import stat
import subprocess
import sys
import unittest
import uuid
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
BASE_DIR = SCRIPT_DIR.parent
CORE_COMMIT = "75025fe696331c85de58a9dbdd0efbbc68ac6f86"
CANONICAL_HASHES = {
    "delta": "edabf77d2c0431eed4a116536fd3446c7b079b9ac249751582948618b934bb9b",
    "delta_schema": (
        "74ed88c5b50be2f7a023afa3de2599ed8e0c2d5de594b8cf6fe26afb9a3fbbd1"
    ),
    "reverse": "8f490c8158d4576f62d872cac69bf4fdd88fe9915e5d90a02e90e01789748d47",
    "index_schema": (
        "02e565bf1f891922ef52266bba93f925c0bf3e3d9292275e3dcbd12f5f64b1d0"
    ),
}
VENDOR_HEADER = (
    f"# Vendored from kody-w/rappter@{CORE_COMMIT}:\n"
    "# engines/twin-dreamcatcher/reverse_index.py\n"
    "# Canonical Git-blob SHA-256:\n"
    f"# {CANONICAL_HASHES['reverse']}\n"
    "# Local adaptations keep the wire format while hardening validation and\n"
    "# case-only rename handling in addition to the local protocol import.\n"
    "\n"
).encode()
# LF-stable wire snapshots from the pinned canonical implementation.
CANONICAL_INDEX_IDS = {
    "before": (
        "sha256:bd0d753af53a51c7171abb302d29ff4a7612e0c47c975b7b9ab0a2efb5ab7cd6"
    ),
    "updated": (
        "sha256:740c58c4c192f3afa82632de08b1fb22818da725765d7e8c6a519ed88d7579af"
    ),
    "query": (
        "sha256:de27e71e367a83e79f4e3c71701e7c413bbe942aac74a34a41939600793891d8"
    ),
}
CANONICAL_WIRE_HASHES = {
    "before": (
        "7f0d34b30125a475f5a4e7bbcd5d5e5cdb1654a3cace63ecce653f9e941ccef8"
    ),
    "updated": (
        "a82d50b7f6168c6e6607d8462a0e9c0e85ee0050df4a1a6409c6d8623617c291"
    ),
    "query": (
        "1465342287102f169b75f69e446eaee276867d353afbd7ec6b6c369569c5da9d"
    ),
}


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise AssertionError(result.stderr or result.stdout)
    return result.stdout.strip()


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        (json.dumps(value, separators=(",", ":")) + "\n").encode("utf-8")
    )


def _remove_tree(path: Path) -> None:
    def make_writable(function, target, _error) -> None:
        os.chmod(target, stat.S_IWRITE)
        function(target)

    if path.exists():
        shutil.rmtree(path, onerror=make_writable)


def _normalized(path: Path) -> bytes:
    return path.read_bytes().replace(b"\r\n", b"\n")


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _wire(value: dict) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


class DreamcatcherParityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = BASE_DIR / f".dreamcatcher-parity-{uuid.uuid4().hex}"
        self.tmp.mkdir()
        self.module_names: list[str] = []

    def tearDown(self) -> None:
        for name in self.module_names:
            sys.modules.pop(name, None)
        _remove_tree(self.tmp)

    def _core_dir(self) -> Path | None:
        configured = os.environ.get("DREAMCATCHER_CORE_DIR")
        candidates = []
        if configured:
            candidates.append(Path(configured))
        candidates.append(
            BASE_DIR.parent / "rappter" / "engines" / "twin-dreamcatcher"
        )
        for candidate in candidates:
            if all(
                (candidate / name).is_file()
                for name in (
                    "delta_protocol.py",
                    "delta.schema.json",
                    "reverse_index.py",
                    "index.schema.json",
                )
            ):
                return candidate
        return None

    def _load(
        self,
        stem: str,
        path: Path,
        *,
        dependency_name: str | None = None,
        dependency: object | None = None,
    ) -> object:
        name = f"_dreamcatcher_parity_{stem}_{uuid.uuid4().hex}"
        spec = importlib.util.spec_from_file_location(name, path)
        if spec is None or spec.loader is None:
            raise AssertionError(f"cannot load module from {path}")
        module = importlib.util.module_from_spec(spec)
        previous = (
            sys.modules.get(dependency_name)
            if dependency_name is not None
            else None
        )
        had_previous = (
            dependency_name is not None
            and dependency_name in sys.modules
        )
        sys.modules[name] = module
        self.module_names.append(name)
        if dependency_name is not None:
            sys.modules[dependency_name] = dependency
        try:
            spec.loader.exec_module(module)
        finally:
            if dependency_name is not None:
                if had_previous:
                    sys.modules[dependency_name] = previous
                else:
                    sys.modules.pop(dependency_name, None)
        return module

    def _implementations(self) -> tuple[object, object, object, object]:
        vendor_delta = SCRIPT_DIR / "dreamcatcher_delta.py"
        vendor_reverse = SCRIPT_DIR / "dreamcatcher_reverse_index.py"
        vendor_delta_schema = BASE_DIR / "schema" / "delta.schema.json"
        vendor_index_schema = BASE_DIR / "schema" / "index.schema.json"
        core_dir = self._core_dir()

        self.assertEqual(
            _sha256(_normalized(vendor_delta)),
            CANONICAL_HASHES["delta"],
        )
        self.assertEqual(
            _sha256(_normalized(vendor_delta_schema)),
            CANONICAL_HASHES["delta_schema"],
        )
        self.assertEqual(
            _normalized(vendor_reverse).count(VENDOR_HEADER),
            1,
        )
        self.assertEqual(
            _sha256(_normalized(vendor_index_schema)),
            CANONICAL_HASHES["index_schema"],
        )

        vendor_dp = self._load("vendor_delta", vendor_delta)
        vendor_ri = self._load(
            "vendor_reverse",
            vendor_reverse,
            dependency_name="dreamcatcher_delta",
            dependency=vendor_dp,
        )
        if core_dir is not None:
            core_delta = core_dir / "delta_protocol.py"
            core_reverse = core_dir / "reverse_index.py"
            self.assertEqual(vendor_delta.read_bytes(), core_delta.read_bytes())
            self.assertEqual(
                vendor_delta_schema.read_bytes(),
                (core_dir / "delta.schema.json").read_bytes(),
            )
            self.assertEqual(
                vendor_index_schema.read_bytes(),
                (core_dir / "index.schema.json").read_bytes(),
            )
            self.assertEqual(
                _sha256(_normalized(core_reverse)),
                CANONICAL_HASHES["reverse"],
            )
            core_dp = self._load("core_delta", core_delta)
            core_ri = self._load(
                "core_reverse",
                core_reverse,
                dependency_name="delta_protocol",
                dependency=core_dp,
            )
        else:
            core_dp = vendor_dp
            core_ri = vendor_ri
        return core_dp, vendor_dp, core_ri, vendor_ri

    def _fixture(self) -> tuple[Path, str]:
        repo = self.tmp / "fixture"
        _write_json(repo / "state" / "agents.json", {
            "agents": {
                "agent-1": {
                    "agent_id": "agent-1",
                    "world_id": "hub",
                }
            }
        })
        _write_json(repo / "state" / "actions.json", {
            "actions": [{
                "id": "action-1",
                "agent_id": "agent-1",
                "authority": "state/agents.json",
            }]
        })
        _write_json(repo / "state" / "legacy.json", {
            "frame_id": "frame-legacy",
            "agent_id": "agent-1",
        })
        _write_json(repo / "state" / "deleted.json", {
            "id": "delete-me",
            "world_id": "hub",
        })
        _write_json(repo / "worlds" / "hub" / "config.json", {
            "world_id": "hub",
            "authority": "state/agents.json",
        })
        _write_json(repo / "feed" / "activity.json", {
            "activities": [{
                "id": "activity-1",
                "agent_id": "agent-1",
            }]
        })
        _git(repo, "init", "-q", "-b", "main")
        _git(repo, "config", "user.name", "Dreamcatcher Test")
        _git(
            repo,
            "config",
            "user.email",
            "dreamcatcher@users.noreply.github.com",
        )
        _git(repo, "config", "core.autocrlf", "false")
        _git(repo, "add", ".")
        _git(repo, "commit", "-qm", "seed")
        return repo, _git(repo, "rev-parse", "HEAD")

    def test_core_and_vendor_wire_output_is_identical(self) -> None:
        core_dp, vendor_dp, core_ri, vendor_ri = self._implementations()
        repo, base = self._fixture()
        includes = ["feed", "state", "worlds"]

        core_before = core_ri.build_index(repo, includes=includes)
        vendor_before = vendor_ri.build_index(repo, includes=includes)
        self.assertEqual(core_before, vendor_before)
        self.assertEqual(
            vendor_before["index_id"],
            CANONICAL_INDEX_IDS["before"],
        )
        self.assertEqual(
            _sha256(_wire(vendor_before)),
            CANONICAL_WIRE_HASHES["before"],
        )

        actions_path = repo / "state" / "actions.json"
        actions = json.loads(actions_path.read_text(encoding="utf-8"))
        actions["actions"].append({
            "id": "action-2",
            "agent_id": "agent-1",
            "frame_id": "frame-2",
        })
        _write_json(actions_path, actions)
        _git(repo, "mv", "state/legacy.json", "state/renamed.json")
        (repo / "state" / "deleted.json").unlink()
        _write_json(repo / "state" / "new.json", {
            "id": "new-record",
            "world_id": "hub",
            "authority": "state/agents.json",
        })
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "candidate")
        head = _git(repo, "rev-parse", "HEAD")
        capture_args = {
            "head": head,
            "source_id": "pr-42",
            "frame": 42,
            "tile": "north-east",
            "include_untracked": False,
        }

        core_manifest = core_dp.capture_worktree(repo, base, **capture_args)
        vendor_manifest = vendor_dp.capture_worktree(repo, base, **capture_args)
        self.assertEqual(core_manifest, vendor_manifest)
        self.assertEqual(_wire(core_manifest), _wire(vendor_manifest))
        self.assertEqual(
            core_manifest["manifest_id"],
            vendor_manifest["manifest_id"],
        )

        core_index = core_ri.update_index(
            repo,
            core_before,
            core_manifest,
        )
        vendor_index = vendor_ri.update_index(
            repo,
            vendor_before,
            vendor_manifest,
        )
        self.assertEqual(core_index, vendor_index)
        for field in (
            "documents",
            "entities",
            "dependencies",
            "dependents",
            "stats",
            "index_id",
        ):
            self.assertEqual(core_index[field], vendor_index[field])
        self.assertEqual(_wire(core_index), _wire(vendor_index))
        self.assertEqual(
            core_index,
            core_ri.build_index(repo, includes=includes),
        )
        self.assertEqual(
            vendor_index,
            vendor_ri.build_index(repo, includes=includes),
        )
        self.assertEqual(
            vendor_index["index_id"],
            CANONICAL_INDEX_IDS["updated"],
        )
        self.assertEqual(
            _sha256(_wire(vendor_index)),
            CANONICAL_WIRE_HASHES["updated"],
        )

        core_query = core_ri.expand_search_plan(
            core_index,
            core_manifest["search_plan"],
            depth=2,
        )
        vendor_query = vendor_ri.expand_search_plan(
            vendor_index,
            vendor_manifest["search_plan"],
            depth=2,
        )
        self.assertEqual(core_query, vendor_query)
        self.assertEqual(core_query["stats"], vendor_query["stats"])
        self.assertEqual(core_query["query_id"], vendor_query["query_id"])
        self.assertEqual(_wire(core_query), _wire(vendor_query))
        self.assertEqual(
            vendor_query["query_id"],
            CANONICAL_INDEX_IDS["query"],
        )
        self.assertEqual(
            _sha256(_wire(vendor_query)),
            CANONICAL_WIRE_HASHES["query"],
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
