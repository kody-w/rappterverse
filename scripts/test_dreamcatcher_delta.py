#!/usr/bin/env python3
"""End-to-end tests for the vendored Dreamcatcher delta protocol."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
import shutil
import stat
import subprocess
import sys
import threading
import time
import unittest
import uuid
from pathlib import Path
from unittest import mock

SCRIPT_DIR = Path(__file__).resolve().parent
BASE_DIR = SCRIPT_DIR.parent
HISTORICAL_27_BASE = "a7f1a56ee34cd54cae23f0b698f4cfbc76d2afc2"
HISTORICAL_27_HEAD = "dcd7782ce2b1b84c2f73cdb7ff6302f32c154de9"

sys.path.insert(0, str(SCRIPT_DIR))
import dreamcatcher_delta as dp  # noqa: E402


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


def _commit_exists(repo: Path, commit: str) -> bool:
    return subprocess.run(
        ["git", "cat-file", "-e", f"{commit}^{{commit}}"],
        cwd=repo,
        capture_output=True,
    ).returncode == 0


def _remove_tree(path: Path) -> None:
    def make_writable(function, target, _error) -> None:
        os.chmod(target, stat.S_IWRITE)
        function(target)

    if path.exists():
        shutil.rmtree(path, onerror=make_writable)


class DeltaProtocolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = BASE_DIR / f".dreamcatcher-delta-{uuid.uuid4().hex}"
        self.tmp.mkdir()
        self.seed = self.tmp / "seed"
        self.seed.mkdir()
        _git(self.seed, "init", "-b", "main")
        _git(self.seed, "config", "user.name", "Dreamcatcher Test")
        _git(
            self.seed,
            "config",
            "user.email",
            "dreamcatcher@users.noreply.github.com",
        )
        _git(self.seed, "config", "core.autocrlf", "false")
        (self.seed / "state").mkdir()
        (self.seed / "agents").mkdir()
        (self.seed / "state" / "frames.jsonl").write_text(
            json.dumps({"frame_id": "frame-1", "tile_id": "tile-a"}) + "\n",
            encoding="utf-8",
        )
        (self.seed / "state" / "deleted.json").write_text(
            '{"id":"delete-me"}\n', encoding="utf-8"
        )
        (self.seed / "state" / "alpha.txt").write_text(
            "alpha\nbeta\ngamma\ndelta\nepsilon\nzeta\n", encoding="utf-8"
        )
        (self.seed / "state" / "beta.txt").write_text("one\ntwo\n", encoding="utf-8")
        (self.seed / "agents" / "old.py").write_text("# agent\n", encoding="utf-8")
        _git(self.seed, "add", ".")
        _git(self.seed, "commit", "-m", "seed")
        self.base = _git(self.seed, "rev-parse", "HEAD")

    def tearDown(self) -> None:
        _remove_tree(self.tmp)

    def _clone(self, name: str) -> Path:
        target = self.tmp / name
        subprocess.run(
            ["git", "clone", "--quiet", str(self.seed), str(target)],
            check=True,
        )
        _git(target, "config", "user.name", "Dreamcatcher Test")
        _git(
            target,
            "config",
            "user.email",
            "dreamcatcher@users.noreply.github.com",
        )
        _git(target, "config", "core.autocrlf", "false")
        return target

    def _performance_pair(self) -> tuple[Path, str, str]:
        if (
            _commit_exists(BASE_DIR, HISTORICAL_27_BASE)
            and _commit_exists(BASE_DIR, HISTORICAL_27_HEAD)
        ):
            return BASE_DIR, HISTORICAL_27_BASE, HISTORICAL_27_HEAD

        repo = self._clone("performance-27")
        paths = [f"state/performance-{index:02d}.json" for index in range(27)]
        for index, path in enumerate(paths):
            (repo / path).write_text(
                json.dumps({"id": f"before-{index}"}) + "\n",
                encoding="utf-8",
            )
        _git(repo, "add", ".")
        _git(repo, "commit", "-m", "add 27-path performance fixture")
        base = _git(repo, "rev-parse", "HEAD")
        for index, path in enumerate(paths):
            (repo / path).write_text(
                json.dumps({"id": f"after-{index}"}) + "\n",
                encoding="utf-8",
            )
        _git(repo, "add", ".")
        _git(repo, "commit", "-m", "modify 27-path performance fixture")
        return repo, base, _git(repo, "rev-parse", "HEAD")

    def test_capture_tracks_worktree_exhaust_and_search_plan(self) -> None:
        repo = self._clone("capture")
        with (repo / "state" / "frames.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({
                "frame_id": "frame-2",
                "tile_id": "tile-b",
                "agent_id": "agent-7",
            }) + "\n")
        _git(repo, "mv", "agents/old.py", "agents/new.py")
        (repo / "state" / "deleted.json").unlink()
        (repo / "state" / "new.json").write_text(
            '{"world_id":"hub","id":"new-record"}\n', encoding="utf-8"
        )

        manifest = dp.capture_worktree(
            repo,
            self.base,
            source_id="worker-7",
            frame=42,
            tile="north-east",
        )
        dp.validate_manifest(manifest)
        statuses = {
            (change["status"], change.get("old_path"), change["path"])
            for change in manifest["changes"]
        }
        self.assertIn(("M", None, "state/frames.jsonl"), statuses)
        self.assertIn(("R", "agents/old.py", "agents/new.py"), statuses)
        self.assertIn(("D", None, "state/deleted.json"), statuses)
        self.assertIn(("A", None, "state/new.json"), statuses)
        self.assertIn(
            "frame_id:frame-2",
            manifest["search_plan"]["entity_ids"],
        )
        self.assertIn("tile_id:tile-b", manifest["search_plan"]["entity_ids"])
        self.assertIn("state/frames.jsonl", manifest["search_plan"]["paths"])
        self.assertEqual(manifest["source"]["frame"], 42)
        self.assertEqual(manifest["source"]["tile"], "north-east")

        repeated = dp.capture_worktree(
            repo,
            self.base,
            source_id="worker-7",
            frame=42,
            tile="north-east",
        )
        self.assertEqual(repeated, manifest)

    def test_validation_rejects_tampering(self) -> None:
        repo = self._clone("tamper")
        (repo / "state" / "new.json").write_text('{"id":"x"}\n', encoding="utf-8")
        manifest = dp.capture_worktree(repo, self.base)
        manifest["changes"][0]["after"]["bytes"] += 1
        with self.assertRaisesRegex(dp.DeltaProtocolError, "manifest_id"):
            dp.validate_manifest(manifest)

    def test_capture_can_scope_one_tile_path(self) -> None:
        repo = self._clone("scoped")
        (repo / "state" / "alpha.txt").write_text("changed\n", encoding="utf-8")
        (repo / "state" / "beta.txt").write_text("also changed\n", encoding="utf-8")
        manifest = dp.capture_worktree(
            repo,
            self.base,
            source_id="tile-alpha",
            paths=["state/alpha.txt"],
        )
        self.assertEqual(
            manifest["search_plan"]["paths"],
            ["state/alpha.txt"],
        )
        self.assertEqual(len(manifest["changes"]), 1)

    def test_capture_uses_one_diff_process_for_many_paths(self) -> None:
        repo = self._clone("process-count")
        paths = [f"state/process-{index:02d}.json" for index in range(12)]
        for index, path in enumerate(paths):
            (repo / path).write_text(
                json.dumps({"id": f"before-{index}"}) + "\n",
                encoding="utf-8",
            )
        _git(repo, "add", ".")
        _git(repo, "commit", "-m", "add process fixtures")
        base = _git(repo, "rev-parse", "HEAD")
        for index, path in enumerate(paths):
            (repo / path).write_text(
                json.dumps({"id": f"after-{index}"}) + "\n",
                encoding="utf-8",
            )
        _git(repo, "add", ".")
        _git(repo, "commit", "-m", "modify process fixtures")
        head = _git(repo, "rev-parse", "HEAD")

        def capture(selected: list[str]) -> tuple[dict, list[tuple[str, ...]]]:
            commands = []
            run_git = dp._run_git
            popen_git = dp._popen_git

            def counted_run(
                target: Path,
                args: list[str],
                **kwargs: object,
            ):
                commands.append(tuple(["git", *args]))
                return run_git(target, args, **kwargs)

            def counted_popen(
                target: Path,
                args: list[str],
                **kwargs: object,
            ):
                commands.append(tuple(["git", *args]))
                return popen_git(target, args, **kwargs)

            with (
                mock.patch.object(dp, "_run_git", side_effect=counted_run),
                mock.patch.object(dp, "_popen_git", side_effect=counted_popen),
            ):
                manifest = dp.capture_worktree(
                    repo,
                    base,
                    head=head,
                    source_id="process-count",
                    paths=selected,
                )
            return manifest, commands

        one, one_commands = capture(paths[:1])
        many, many_commands = capture(paths)
        self.assertEqual(len(one["changes"]), 1)
        self.assertEqual(len(many["changes"]), 12)

        for commands in (one_commands, many_commands):
            diffs = [
                command for command in commands
                if command[0] == "git" and "diff" in command[1:3]
            ]
            self.assertEqual(len(diffs), 1)
            self.assertIn("--raw", diffs[0])
            self.assertIn("--patch", diffs[0])
            self.assertIn("--unified=0", diffs[0])
            self.assertIn("--find-renames", diffs[0])

        one_git_processes = [
            command for command in one_commands
            if command[0] == "git"
        ]
        many_git_processes = [
            command for command in many_commands
            if command[0] == "git"
        ]
        self.assertEqual(len(one_git_processes), len(many_git_processes))
        self.assertEqual(len(many_git_processes), 7)
        self.assertEqual(
            sum("cat-file" in command[1:3] for command in one_commands),
            1,
        )
        self.assertEqual(
            sum("cat-file" in command[1:3] for command in many_commands),
            1,
        )
        self.assertEqual(
            sum("check-attr" in command[1:3] for command in one_commands),
            1,
        )
        self.assertEqual(
            sum("check-attr" in command[1:3] for command in many_commands),
            1,
        )
        self.assertEqual(
            dp.capture_worktree(
                repo,
                base,
                head=head,
                source_id="process-count",
                paths=paths,
            ),
            many,
        )

    def test_blob_diff_matches_git_hunks_and_entities(self) -> None:
        repo = self._clone("hunk-parity")
        path = "state/alpha.txt"
        (repo / path).write_bytes(
            b"ALPHA\n"
            b"beta\n"
            b"inserted {\"id\":\"new-id\"}\n"
            b"gamma\n"
            b"delta\n"
            b"epsilon\n"
            b"eta\n"
            b"theta {\"frame_id\":\"tail\"}\n"
        )
        patch = subprocess.run(
            [
                "git",
                "diff",
                "--unified=0",
                "--no-color",
                self.base,
                "--",
                path,
            ],
            cwd=repo,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        manifest = dp.capture_worktree(repo, self.base, paths=[path])
        change = manifest["changes"][0]
        self.assertEqual(change["line_ranges"], dp._hunk_ranges(patch))
        self.assertEqual(change["entity_ids"], dp._entity_ids(path, patch))
        self.assertEqual(dp.verify_manifest_repository(manifest, repo), manifest)

    def test_batched_patch_maps_spaces_unicode_and_renames(self) -> None:
        repo = self._clone("quoted-paths")
        spaced_path = "state/space name.json"
        old_path = "state/雪 old records.jsonl"
        new_path = "state/雪 new records.jsonl"
        (repo / spaced_path).write_text('{"id":"space-old"}\n', encoding="utf-8")
        (repo / old_path).write_text(
            "".join(
                json.dumps({"id": f"row-{index}"}) + "\n"
                for index in range(40)
            ),
            encoding="utf-8",
        )
        _git(repo, "add", ".")
        _git(repo, "commit", "-m", "add quoted paths")
        base = _git(repo, "rev-parse", "HEAD")

        (repo / spaced_path).write_text('{"id":"space-new"}\n', encoding="utf-8")
        _git(repo, "mv", old_path, new_path)
        rows = (repo / new_path).read_text(encoding="utf-8").splitlines()
        rows[20] = json.dumps({"id": "renamed-row"})
        (repo / new_path).write_text("\n".join(rows) + "\n", encoding="utf-8")
        _git(repo, "add", ".")
        _git(repo, "commit", "-m", "modify quoted paths")
        head = _git(repo, "rev-parse", "HEAD")

        manifest = dp.capture_worktree(
            repo,
            base,
            head=head,
            paths=[spaced_path, old_path, new_path],
        )
        changes = {change["path"]: change for change in manifest["changes"]}
        self.assertEqual(changes[new_path]["status"], "R")
        self.assertEqual(changes[new_path]["old_path"], old_path)

        def git_ranges(selected: list[str]) -> list[dict]:
            patch = subprocess.run(
                [
                    "git",
                    "diff",
                    "--unified=0",
                    "--no-color",
                    "--find-renames",
                    "--diff-algorithm=myers",
                    "--indent-heuristic",
                    base,
                    head,
                    "--",
                    *selected,
                ],
                cwd=repo,
                capture_output=True,
                text=True,
                check=True,
            ).stdout
            return dp._hunk_ranges(patch)

        self.assertEqual(
            changes[spaced_path]["line_ranges"],
            git_ranges([spaced_path]),
        )
        self.assertEqual(
            changes[new_path]["line_ranges"],
            git_ranges([old_path, new_path]),
        )
        self.assertIn("id:space-new", changes[spaced_path]["entity_ids"])
        self.assertIn("id:renamed-row", changes[new_path]["entity_ids"])

    def test_overlong_patch_line_is_bounded_and_forces_conservative_scope(
        self,
    ) -> None:
        repo = self._clone("entity-completeness")
        path = "state/oversized-record.jsonl"
        (repo / path).write_text('{"frame_id":"old"}\n', encoding="utf-8")
        _git(repo, "add", path)
        _git(repo, "commit", "-m", "add oversized record")
        base = _git(repo, "rev-parse", "HEAD")
        (repo / path).write_bytes(
            b'{"frame_id":"first","payload":"'
            + (b"x" * (16 * 1024 * 1024 + 1))
            + b'","frame_id":"last"}\n'
        )

        metrics = {}
        manifest = dp.capture_worktree(
            repo,
            base,
            paths=[path],
            metrics=metrics,
        )
        change = manifest["changes"][0]
        self.assertEqual(change["line_ranges"], [])
        self.assertEqual(change["entity_ids"], [])
        self.assertEqual(manifest["search_plan"]["paths"], [path])
        self.assertFalse(any(
            value.startswith("frame_id:")
            for value in manifest["search_plan"]["entity_ids"]
        ))
        self.assertLessEqual(
            metrics["max_buffered_patch_bytes"],
            dp.PATCH_LINE_MAX_BYTES,
        )
        self.assertEqual(
            metrics["patch_line_max_bytes"],
            dp.PATCH_LINE_MAX_BYTES,
        )

        other_payload = copy.deepcopy(manifest)
        other_payload.pop("manifest_id")
        other_payload["source"]["id"] = "other-writer"
        other_payload["changes"][0]["after"]["sha256"] = "e" * 64
        other = dp._with_id(other_payload, "manifest_id")
        batch = dp.batch_manifests([manifest, other])
        self.assertFalse(batch["ready"])
        self.assertEqual(batch["conflicts"][0]["kind"], "conflict")

    def test_unicode_function_context_preserves_hunk_coordinates(self) -> None:
        repo = self._clone("unicode-hunk-context")
        path = "agents/unicode_context.py"
        (repo / path).write_text(
            "def café():\n    return 'old'\n",
            encoding="utf-8",
        )
        _git(repo, "add", path)
        _git(repo, "commit", "-m", "add unicode function")
        base = _git(repo, "rev-parse", "HEAD")
        (repo / path).write_text(
            "def café():\n    return 'new'\n",
            encoding="utf-8",
        )
        patch = subprocess.run(
            ["git", "diff", "--unified=0", base, "--", path],
            cwd=repo,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=True,
        ).stdout
        self.assertIn("café", patch)
        manifest = dp.capture_worktree(repo, base, paths=[path])
        self.assertEqual(
            manifest["changes"][0]["line_ranges"],
            dp._hunk_ranges(patch),
        )

    def test_large_append_reports_every_frame_and_bounds_blob_buffer(self) -> None:
        repo = self._clone("large-jsonl")
        path = "state/large.jsonl"
        record = b'{"payload":"' + (b"x" * 1024) + b'"}\n'
        original = record * 256
        (repo / path).write_bytes(original)
        _git(repo, "add", path)
        _git(repo, "commit", "-m", "add large jsonl")
        base = _git(repo, "rev-parse", "HEAD")

        frame_ids = [f"frame-{index:05d}" for index in range(20_000)]
        appended = b"".join(
            (
                json.dumps({
                    "frame_id": frame_id,
                    "tile_id": f"tile-{index % 17}",
                }, separators=(",", ":"))
                + "\n"
            ).encode()
            for index, frame_id in enumerate(frame_ids)
        )
        (repo / path).write_bytes(original + appended)
        metrics = {}
        append_manifest = dp.capture_worktree(
            repo,
            base,
            paths=[path],
            metrics=metrics,
        )
        append_change = append_manifest["changes"][0]
        self.assertEqual(append_change["line_ranges"], [{
            "old_start": 256,
            "old_lines": 0,
            "new_start": 257,
            "new_lines": len(frame_ids),
        }])
        extracted = {
            value.split(":", 1)[1]
            for value in append_change["entity_ids"]
            if value.startswith("frame_id:")
        }
        self.assertEqual(extracted, set(frame_ids))
        self.assertEqual(
            metrics["max_buffered_blob_bytes"],
            dp.BLOB_STREAM_CHUNK_BYTES,
        )
        self.assertEqual(
            metrics["blob_stream_chunk_bytes"],
            dp.BLOB_STREAM_CHUNK_BYTES,
        )

    def test_untracked_binary_scanning_bounds_discarded_entities(self) -> None:
        repo = self._clone("untracked-binary-entities")
        declared_path = "state/declared.bin"
        detected_path = "state/detected.bin"
        (repo / ".gitattributes").write_text(
            f"{declared_path} -diff\n",
            encoding="utf-8",
        )
        _git(repo, "add", ".gitattributes")
        _git(repo, "commit", "-m", "declare binary path")
        base = _git(repo, "rev-parse", "HEAD")

        records = b"".join(
            f'{{"frame_id":"discard-{index:05d}"}}\n'.encode()
            for index in range(20_000)
        )
        (repo / declared_path).write_bytes(records)
        (repo / detected_path).write_bytes(b"\0" + records)
        metrics = {}
        manifest = dp.capture_worktree(
            repo,
            base,
            paths=[declared_path, detected_path],
            metrics=metrics,
        )

        changes = {change["path"]: change for change in manifest["changes"]}
        for path in (declared_path, detected_path):
            self.assertEqual(changes[path]["line_ranges"], [])
            self.assertEqual(changes[path]["entity_ids"], [])
        self.assertEqual(metrics["max_accumulated_entity_ids"], 1)
        self.assertLessEqual(
            metrics["max_buffered_blob_bytes"],
            dp.BLOB_STREAM_CHUNK_BYTES,
        )

    def test_unicode_and_binary_metadata_remain_safe(self) -> None:
        repo = self._clone("unicode-binary")
        unicode_path = "state/unicode.jsonl"
        binary_path = "state/blob.bin"
        (repo / unicode_path).write_bytes(
            '{"id":"雪\u2028旧","frame_id":"frame-old"}\n'.encode()
        )
        (repo / binary_path).write_bytes(
            b'\x00{"id":"binary-old"}\n'
        )
        _git(repo, "add", unicode_path, binary_path)
        _git(repo, "commit", "-m", "add unicode and binary")
        base = _git(repo, "rev-parse", "HEAD")
        (repo / unicode_path).write_bytes(
            '{"id":"雪\u2028新","frame_id":"frame-new"}\n'.encode()
        )
        (repo / binary_path).write_bytes(
            b'\x00{"id":"binary-new"}\n'
        )

        manifest = dp.capture_worktree(
            repo,
            base,
            paths=[unicode_path, binary_path],
        )
        changes = {change["path"]: change for change in manifest["changes"]}
        unicode_change = changes[unicode_path]
        self.assertEqual(unicode_change["line_ranges"], [{
            "old_start": 1,
            "old_lines": 1,
            "new_start": 1,
            "new_lines": 1,
        }])
        self.assertIn("id:雪\u2028旧", unicode_change["entity_ids"])
        self.assertIn("id:雪\u2028新", unicode_change["entity_ids"])
        self.assertIn("frame_id:frame-old", unicode_change["entity_ids"])
        self.assertIn("frame_id:frame-new", unicode_change["entity_ids"])
        binary_change = changes[binary_path]
        self.assertEqual(binary_change["line_ranges"], [])
        self.assertEqual(binary_change["entity_ids"], [])
        self.assertEqual(dp.verify_manifest_repository(manifest, repo), manifest)

    def test_git_diff_attributes_force_binary_and_text_semantics(self) -> None:
        repo = self._clone("diff-attributes")
        binary_path = "state/declared.bin"
        text_path = "state/forced.txt"
        (repo / ".gitattributes").write_text(
            "state/*.bin -diff\nstate/forced.txt diff\n",
            encoding="utf-8",
        )
        (repo / binary_path).write_text(
            '{"frame_id":"binary-old"}\n',
            encoding="utf-8",
        )
        (repo / text_path).write_bytes(b'\0{"id":"text-old"}\n')
        _git(repo, "add", ".")
        _git(repo, "commit", "-m", "add diff attributes")
        base = _git(repo, "rev-parse", "HEAD")

        (repo / binary_path).write_text(
            '{"frame_id":"binary-new"}\n',
            encoding="utf-8",
        )
        (repo / text_path).write_bytes(b'\0{"id":"text-new"}\n')
        manifest = dp.capture_worktree(
            repo,
            base,
            paths=[binary_path, text_path],
        )
        changes = {change["path"]: change for change in manifest["changes"]}
        self.assertEqual(changes[binary_path]["line_ranges"], [])
        self.assertEqual(changes[binary_path]["entity_ids"], [])
        self.assertEqual(changes[text_path]["line_ranges"], [{
            "old_start": 1,
            "old_lines": 1,
            "new_start": 1,
            "new_lines": 1,
        }])
        self.assertIn("id:text-old", changes[text_path]["entity_ids"])
        self.assertIn("id:text-new", changes[text_path]["entity_ids"])

        second = self.tmp / "diff-attributes-second"
        subprocess.run(
            ["git", "clone", "--quiet", str(repo), str(second)],
            check=True,
        )
        _git(second, "config", "user.name", "Dreamcatcher Test")
        _git(
            second,
            "config",
            "user.email",
            "dreamcatcher@users.noreply.github.com",
        )
        (second / binary_path).write_text(
            '{"frame_id":"binary-other"}\n',
            encoding="utf-8",
        )
        first_manifest = dp.capture_worktree(
            repo,
            base,
            source_id="binary-first",
            paths=[binary_path],
        )
        second_manifest = dp.capture_worktree(
            second,
            base,
            source_id="binary-second",
            paths=[binary_path],
        )
        batch = dp.batch_manifests([first_manifest, second_manifest])
        self.assertFalse(batch["ready"])
        self.assertEqual(batch["conflicts"][0]["path"], binary_path)

    def test_copy_parsing_and_type_changes_remain_supported(self) -> None:
        self.assertEqual(
            dp._parse_name_status(
                b"C087\0state/source.txt\0state/copy.txt\0"
            ),
            [{
                "status": "C",
                "similarity": 87,
                "old_path": "state/source.txt",
                "path": "state/copy.txt",
            }],
        )

        repo = self._clone("type-change")
        path = "state/typed.txt"
        (repo / path).write_bytes(b"target\n")
        _git(repo, "add", path)
        _git(repo, "commit", "-m", "add typed path")
        base = _git(repo, "rev-parse", "HEAD")
        blob = _git(repo, "rev-parse", f"{base}:{path}")
        _git(repo, "update-index", "--cacheinfo", f"120000,{blob},{path}")
        _git(repo, "commit", "-m", "change path type")
        head = _git(repo, "rev-parse", "HEAD")
        manifest = dp.capture_worktree(
            repo,
            base,
            head=head,
            paths=[path],
        )
        change = manifest["changes"][0]
        self.assertEqual(change["status"], "T")
        self.assertEqual(change["before"], change["after"])
        self.assertEqual(change["line_ranges"], [])
        self.assertEqual(change["entity_ids"], [])
        self.assertEqual(dp.verify_manifest_repository(manifest, repo), manifest)

    def test_repository_verification_rejects_stale_candidate(self) -> None:
        repo = self._clone("verify")
        path = repo / "state" / "new.json"
        path.write_text('{"id":"first"}\n', encoding="utf-8")
        manifest = dp.capture_worktree(repo, self.base)
        self.assertEqual(dp.verify_manifest_repository(manifest, repo), manifest)
        self.assertEqual(dp.verify_manifest_tree(manifest, repo), manifest)
        path.write_text('{"id":"changed-after-capture"}\n', encoding="utf-8")
        with self.assertRaisesRegex(dp.DeltaProtocolError, "exact declared"):
            dp.verify_manifest_repository(manifest, repo)
        with self.assertRaisesRegex(dp.DeltaProtocolError, "materialized blob"):
            dp.verify_manifest_tree(manifest, repo)

    def test_repository_verification_accepts_legacy_representation(self) -> None:
        repo = self._clone("verify-legacy")
        (repo / "state" / "new.json").write_text(
            '{"frame_id":"legacy-verify"}\n',
            encoding="utf-8",
        )
        modern = dp.capture_worktree(repo, self.base)
        self.assertEqual(dp.verify_manifest_repository(modern, repo), modern)

        legacy_payload = copy.deepcopy(modern)
        legacy_payload.pop("manifest_id")
        legacy_payload["repository"].pop("line_coordinates")
        legacy = dp._with_id(legacy_payload, "manifest_id")
        self.assertEqual(dp.validate_manifest(legacy), legacy)
        self.assertEqual(dp.verify_manifest_repository(legacy, repo), legacy)

        mixed = dp.batch_manifests([modern, legacy])
        self.assertTrue(mixed["ready"])
        self.assertEqual(mixed["collisions"][0]["kind"], "identical")

        unsealed = copy.deepcopy(legacy)
        unsealed["manifest_id"] = modern["manifest_id"]
        with self.assertRaisesRegex(dp.DeltaProtocolError, "manifest_id"):
            dp.verify_manifest_repository(unsealed, repo)

    def test_repository_verification_replays_legacy_binary_entities(self) -> None:
        repo = self._clone("verify-legacy-binary")
        path = "state/legacy.bin"
        (repo / ".gitattributes").write_text(
            f"{path} -diff\n",
            encoding="utf-8",
        )
        (repo / path).write_text('{"frame_id":"old"}\n', encoding="utf-8")
        _git(repo, "add", ".")
        _git(repo, "commit", "-m", "add declared binary")
        base = _git(repo, "rev-parse", "HEAD")
        (repo / path).write_text('{"frame_id":"new"}\n', encoding="utf-8")

        modern = dp.capture_worktree(repo, base, paths=[path])
        change = modern["changes"][0]
        self.assertEqual(change["line_ranges"], [])
        self.assertEqual(change["entity_ids"], [])

        legacy_payload = copy.deepcopy(modern)
        legacy_payload.pop("manifest_id")
        legacy_payload["repository"].pop("line_coordinates")
        legacy_payload["changes"][0]["entity_ids"] = [f"path:{path}"]
        legacy_payload["search_plan"] = dp._search_plan(
            legacy_payload["changes"]
        )
        legacy = dp._with_id(legacy_payload, "manifest_id")
        self.assertEqual(dp.validate_manifest(legacy), legacy)
        self.assertEqual(dp.verify_manifest_repository(legacy, repo), legacy)

        unsealed = copy.deepcopy(legacy)
        unsealed["manifest_id"] = modern["manifest_id"]
        with self.assertRaisesRegex(dp.DeltaProtocolError, "manifest_id"):
            dp.verify_manifest_repository(unsealed, repo)

        non_path_payload = copy.deepcopy(legacy)
        non_path_payload.pop("manifest_id")
        non_path_payload["changes"][0]["entity_ids"].append(
            "frame_id:forged"
        )
        non_path_payload["search_plan"] = dp._search_plan(
            non_path_payload["changes"]
        )
        non_path = dp._with_id(non_path_payload, "manifest_id")
        with self.assertRaisesRegex(dp.DeltaProtocolError, "exact declared"):
            dp.verify_manifest_repository(non_path, repo)

        ranged_payload = copy.deepcopy(legacy)
        ranged_payload.pop("manifest_id")
        ranged_payload["changes"][0]["line_ranges"] = [{
            "old_start": 1,
            "old_lines": 1,
            "new_start": 1,
            "new_lines": 1,
        }]
        ranged = dp._with_id(ranged_payload, "manifest_id")
        with self.assertRaisesRegex(dp.DeltaProtocolError, "exact declared"):
            dp.verify_manifest_repository(ranged, repo)

        modern_path_payload = copy.deepcopy(modern)
        modern_path_payload.pop("manifest_id")
        modern_path_payload["changes"][0]["entity_ids"] = [f"path:{path}"]
        modern_path_payload["search_plan"] = dp._search_plan(
            modern_path_payload["changes"]
        )
        modern_path = dp._with_id(modern_path_payload, "manifest_id")
        with self.assertRaisesRegex(dp.DeltaProtocolError, "exact declared"):
            dp.verify_manifest_repository(modern_path, repo)

    def test_worktree_capture_retries_content_and_path_set_races(self) -> None:
        repo = self._clone("capture-race")
        relative_path = "state/alpha.txt"
        target = repo / relative_path
        target.write_text(
            "ALPHA\nbeta\ngamma\ndelta\nepsilon\nzeta\n",
            encoding="utf-8",
        )
        untracked = repo / "state" / "writer.json"
        writer_start = threading.Event()
        writer_done = threading.Event()

        def writer() -> None:
            if not writer_start.wait(5):
                return
            target.write_text(
                "ALPHA\nbeta\ngamma\ndelta\nepsilon\nZETA\n",
                encoding="utf-8",
            )
            untracked.write_text('{"id":"writer"}\n', encoding="utf-8")
            writer_done.set()

        thread = threading.Thread(target=writer)
        thread.start()
        original_summary = dp._stream_file_summary
        triggered = False

        def raced_summary(candidate: Path, **kwargs: object):
            nonlocal triggered
            if candidate == target and not triggered:
                triggered = True
                writer_start.set()
                if not writer_done.wait(5):
                    raise AssertionError("concurrent writer did not finish")
            return original_summary(candidate, **kwargs)

        metrics = {}
        try:
            with mock.patch.object(
                dp,
                "_stream_file_summary",
                side_effect=raced_summary,
            ):
                manifest = dp.capture_worktree(
                    repo,
                    self.base,
                    metrics=metrics,
                )
        finally:
            writer_start.set()
            thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assertTrue(triggered)
        changes = {change["path"]: change for change in manifest["changes"]}
        patch = subprocess.run(
            [
                "git",
                "diff",
                "--unified=0",
                "--no-color",
                self.base,
                "--",
                relative_path,
            ],
            cwd=repo,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        self.assertEqual(
            changes[relative_path]["line_ranges"],
            dp._hunk_ranges(patch),
        )
        self.assertEqual(
            changes[relative_path]["after"]["sha256"],
            hashlib.sha256(target.read_bytes()).hexdigest(),
        )
        self.assertIn("state/writer.json", changes)
        self.assertEqual(metrics["worktree_capture_attempts"], 3)

    def test_worktree_capture_fails_when_writer_never_stabilizes(self) -> None:
        repo = self._clone("capture-churn")
        relative_path = "state/alpha.txt"
        target = repo / relative_path
        first = "ALPHA\nbeta\ngamma\ndelta\nepsilon\nzeta\n"
        second = "alpha\nbeta\ngamma\ndelta\nepsilon\nZETA\n"
        target.write_text(first, encoding="utf-8")
        original_summary = dp._stream_file_summary
        writes = 0

        def churn_summary(candidate: Path, **kwargs: object):
            nonlocal writes
            if candidate == target:
                writes += 1
                target.write_text(
                    second if writes % 2 else first,
                    encoding="utf-8",
                )
            return original_summary(candidate, **kwargs)

        metrics = {}
        with (
            mock.patch.object(
                dp,
                "_stream_file_summary",
                side_effect=churn_summary,
            ),
            self.assertRaisesRegex(
                dp.DeltaProtocolError,
                "worktree changed during capture after 3 attempts",
            ),
        ):
            dp.capture_worktree(
                repo,
                self.base,
                paths=[relative_path],
                metrics=metrics,
            )
        self.assertEqual(writes, dp.WORKTREE_CAPTURE_MAX_ATTEMPTS)
        self.assertEqual(
            metrics["worktree_capture_attempts"],
            dp.WORKTREE_CAPTURE_MAX_ATTEMPTS,
        )

    def test_headed_capture_uses_merge_base_and_proves_complete_diff(self) -> None:
        (self.seed / "state" / "main-only.txt").write_text(
            "advanced main\n", encoding="utf-8"
        )
        _git(self.seed, "add", ".")
        _git(self.seed, "commit", "-m", "advance main")
        repo = self._clone("stale-worker")
        _git(repo, "checkout", "-b", "worker", self.base)
        (repo / "state" / "alpha.txt").write_text(
            "worker change\n", encoding="utf-8"
        )
        _git(repo, "add", ".")
        _git(repo, "commit", "-m", "worker")
        manifest = dp.capture_worktree(
            repo,
            "origin/main",
            head="HEAD",
            source_id="stale-pr",
        )
        self.assertEqual(manifest["repository"]["base_commit"], self.base)
        self.assertEqual(
            manifest["search_plan"]["paths"],
            ["state/alpha.txt"],
        )
        self.assertEqual(dp.verify_manifest_repository(manifest, repo), manifest)

        incomplete_payload = copy.deepcopy(manifest)
        incomplete_payload.pop("manifest_id")
        incomplete_payload["changes"] = []
        incomplete_payload["search_plan"] = dp._search_plan([])
        incomplete = dp._with_id(incomplete_payload, "manifest_id")
        with self.assertRaisesRegex(dp.DeltaProtocolError, "exact declared"):
            dp.verify_manifest_repository(incomplete, repo)

    def test_headed_capture_ignores_uncommitted_attribute_changes(self) -> None:
        repo = self._clone("headed-attributes")
        path = "state/alpha.txt"
        (repo / path).write_text(
            "ALPHA\nbeta\ngamma\ndelta\nepsilon\nzeta\n",
            encoding="utf-8",
        )
        _git(repo, "add", path)
        _git(repo, "commit", "-m", "modify headed text")
        head = _git(repo, "rev-parse", "HEAD")
        manifest = dp.capture_worktree(
            repo,
            self.base,
            head=head,
            paths=[path],
        )

        (repo / ".gitattributes").write_text(
            "state/alpha.txt -diff\n",
            encoding="utf-8",
        )
        repeated = dp.capture_worktree(
            repo,
            self.base,
            head=head,
            paths=[path],
        )
        self.assertEqual(repeated, manifest)
        self.assertEqual(dp.verify_manifest_repository(manifest, repo), manifest)

    def test_batch_orders_parallel_tiles_and_unions_search_plan(self) -> None:
        first = self._clone("first")
        second = self._clone("second")
        (first / "state" / "alpha.txt").write_text(
            "ALPHA\nbeta\ngamma\ndelta\nepsilon\nzeta\n", encoding="utf-8"
        )
        (second / "state" / "beta.txt").write_text("one\nTWO\n", encoding="utf-8")
        later = dp.capture_worktree(
            first, self.base, source_id="later", frame=9, tile="b"
        )
        earlier = dp.capture_worktree(
            second, self.base, source_id="earlier", frame=8, tile="a"
        )
        batch = dp.batch_manifests([later, earlier])
        self.assertTrue(batch["ready"])
        self.assertEqual(
            batch["ordered_manifest_ids"],
            [earlier["manifest_id"], later["manifest_id"]],
        )
        self.assertEqual(batch["conflicts"], [])
        self.assertEqual(
            batch["search_plan"]["paths"],
            ["state/alpha.txt", "state/beta.txt"],
        )

    def test_batch_classifies_disjoint_hunks_as_mergeable(self) -> None:
        first = self._clone("disjoint-first")
        second = self._clone("disjoint-second")
        lines = (first / "state" / "alpha.txt").read_text().splitlines()
        lines[0] = "ALPHA"
        (first / "state" / "alpha.txt").write_text("\n".join(lines) + "\n")
        lines = (second / "state" / "alpha.txt").read_text().splitlines()
        lines[5] = "ZETA"
        (second / "state" / "alpha.txt").write_text("\n".join(lines) + "\n")
        one = dp.capture_worktree(first, self.base, source_id="one")
        two = dp.capture_worktree(second, self.base, source_id="two")
        batch = dp.batch_manifests([one, two])
        self.assertTrue(batch["ready"])
        self.assertEqual(batch["collisions"][0]["kind"], "disjoint-hunks")

    def test_repeated_line_insertions_share_git_anchor_and_conflict(self) -> None:
        path = "state/repeated.txt"
        (self.seed / path).write_text("A\nA\nB\n", encoding="utf-8")
        _git(self.seed, "add", path)
        _git(self.seed, "commit", "-m", "add repeated anchors")
        base = _git(self.seed, "rev-parse", "HEAD")
        first = self._clone("anchor-first")
        second = self._clone("anchor-second")
        (first / path).write_text("A\nA\nA\nB\n", encoding="utf-8")
        (second / path).write_text("A\nA\nC\nB\n", encoding="utf-8")

        one = dp.capture_worktree(first, base, source_id="one", paths=[path])
        two = dp.capture_worktree(second, base, source_id="two", paths=[path])
        expected = [{
            "old_start": 2,
            "old_lines": 0,
            "new_start": 3,
            "new_lines": 1,
        }]
        self.assertEqual(one["changes"][0]["line_ranges"], expected)
        self.assertEqual(two["changes"][0]["line_ranges"], expected)
        batch = dp.batch_manifests([one, two])
        self.assertFalse(batch["ready"])
        self.assertEqual(batch["conflicts"][0]["kind"], "conflict")

    def test_batch_rejects_overlapping_writes(self) -> None:
        first = self._clone("conflict-first")
        second = self._clone("conflict-second")
        (first / "state" / "beta.txt").write_text("ONE\ntwo\n", encoding="utf-8")
        (second / "state" / "beta.txt").write_text("uno\ntwo\n", encoding="utf-8")
        one = dp.capture_worktree(first, self.base, source_id="one")
        two = dp.capture_worktree(second, self.base, source_id="two")
        batch = dp.batch_manifests([one, two])
        self.assertFalse(batch["ready"])
        self.assertEqual(batch["conflicts"][0]["kind"], "conflict")
        with self.assertRaisesRegex(dp.DeltaProtocolError, "duplicate"):
            dp.batch_manifests([one, one])

    def test_batch_uses_shared_base_coordinates_for_hunks(self) -> None:
        repo = self._clone("shifted-hunks")
        (repo / "state" / "beta.txt").write_text("ONE\ntwo\n", encoding="utf-8")
        first = dp.capture_worktree(repo, self.base, source_id="first")
        second_payload = copy.deepcopy(first)
        second_payload.pop("manifest_id")
        second_payload["source"]["id"] = "second"
        second_payload["source"]["branch"] = "worker/second"
        second_payload["repository"]["head_commit"] = "f" * 40
        second_payload["changes"][0]["after"]["sha256"] = "e" * 64
        second_payload["changes"][0]["line_ranges"][0]["new_lines"] += 5
        second = dp._with_id(second_payload, "manifest_id")
        batch = dp.batch_manifests([first, second])
        self.assertFalse(batch["ready"])
        self.assertEqual(batch["conflicts"][0]["path"], "state/beta.txt")

    def test_batch_detects_rename_source_conflict(self) -> None:
        renamed = self._clone("renamed-source")
        modified = self._clone("modified-source")
        _git(renamed, "mv", "agents/old.py", "agents/new.py")
        (modified / "agents" / "old.py").write_text(
            "# changed agent\n", encoding="utf-8"
        )
        rename_manifest = dp.capture_worktree(
            renamed, self.base, source_id="rename"
        )
        modify_manifest = dp.capture_worktree(
            modified, self.base, source_id="modify"
        )
        batch = dp.batch_manifests([rename_manifest, modify_manifest])
        self.assertFalse(batch["ready"])
        self.assertTrue(any(
            conflict["path"] == "agents/old.py"
            for conflict in batch["conflicts"]
        ))

    def test_validation_rejects_noncanonical_path_spellings(self) -> None:
        repo = self._clone("noncanonical-paths")
        (repo / "state" / "new.json").write_text(
            '{"id":"canonical"}\n',
            encoding="utf-8",
        )
        manifest = dp.capture_worktree(repo, self.base)
        for supplied in (
            "state//new.json",
            "state/./new.json",
            "./state/new.json",
            "state/new.json/",
        ):
            with self.subTest(path=supplied):
                tampered = copy.deepcopy(manifest)
                tampered["changes"][0]["path"] = supplied
                with self.assertRaisesRegex(
                    dp.DeltaProtocolError,
                    "not canonical",
                ):
                    dp.batch_manifests([tampered])

    def test_validation_rejects_boolean_integer_fields(self) -> None:
        repo = self._clone("boolean-integers")
        (repo / "state" / "new.json").write_text(
            '{"id":"booleans"}\n',
            encoding="utf-8",
        )
        manifest = dp.capture_worktree(repo, self.base)

        with self.assertRaisesRegex(dp.DeltaProtocolError, "frame"):
            dp.capture_worktree(repo, self.base, frame=True)

        mutations = (
            ("source.frame", lambda value: value["source"].update(frame=True)),
            (
                "after.bytes",
                lambda value: value["changes"][0]["after"].update(bytes=True),
            ),
            (
                "line_range",
                lambda value: value["changes"][0].update(line_ranges=[{
                    "old_start": True,
                    "old_lines": 0,
                    "new_start": 1,
                    "new_lines": 1,
                }]),
            ),
        )
        for name, mutate in mutations:
            with self.subTest(field=name):
                tampered = copy.deepcopy(manifest)
                tampered.pop("manifest_id")
                mutate(tampered)
                tampered = dp._with_id(tampered, "manifest_id")
                with self.assertRaises(dp.DeltaProtocolError):
                    dp.validate_manifest(tampered)

    def test_validation_rejects_mixed_or_invalid_coordinates(self) -> None:
        repo = self._clone("invalid-coordinates")
        path = "state/alpha.txt"
        (repo / path).write_text(
            "ALPHA\nbeta\ngamma\ndelta\nepsilon\nzeta\n",
            encoding="utf-8",
        )
        manifest = dp.capture_worktree(repo, self.base, paths=[path])

        mixed = copy.deepcopy(manifest)
        mixed.pop("manifest_id")
        mixed["repository"]["line_coordinates"] = "sequence-matcher/legacy"
        mixed = dp._with_id(mixed, "manifest_id")
        with self.assertRaisesRegex(
            dp.DeltaProtocolError,
            "line_coordinates",
        ):
            dp.batch_manifests([manifest, mixed])

        invalid = copy.deepcopy(manifest)
        invalid.pop("manifest_id")
        invalid["changes"][0]["line_ranges"][0]["new_start"] += 1
        invalid = dp._with_id(invalid, "manifest_id")
        with self.assertRaisesRegex(
            dp.DeltaProtocolError,
            "coordinates",
        ):
            dp.validate_manifest(invalid)

    def test_legacy_git_coordinate_fixture_replays_with_new_manifests(
        self,
    ) -> None:
        fixture = (
            Path(__file__).parent
            / "fixtures"
            / "dreamcatcher-delta-1.0-git.json"
        )
        legacy = dp.load_manifest(fixture)
        self.assertNotIn("line_coordinates", legacy["repository"])
        self.assertEqual(
            legacy["manifest_id"],
            "sha256:6f07c2d81b174c61095df23ba399b528"
            "a73deb4742f9d2eaca976e283fa2449e",
        )

        modern_payload = copy.deepcopy(legacy)
        modern_payload.pop("manifest_id")
        modern_payload["repository"]["line_coordinates"] = dp.LINE_COORDINATES
        modern_payload["repository"]["head_commit"] = "3" * 40
        modern_payload["source"]["id"] = "modern-worker"
        modern_payload["source"]["frame"] = 8
        modern_payload["changes"][0]["after"]["sha256"] = "c" * 64
        modern_payload["changes"][0]["line_ranges"] = [{
            "old_start": 6,
            "old_lines": 1,
            "new_start": 6,
            "new_lines": 1,
        }]
        modern = dp._with_id(modern_payload, "manifest_id")
        batch = dp.batch_manifests([legacy, modern])
        self.assertTrue(batch["ready"])
        self.assertEqual(batch["collisions"][0]["kind"], "disjoint-hunks")

        non_git_payload = copy.deepcopy(legacy)
        non_git_payload.pop("manifest_id")
        non_git_payload["repository"]["line_coordinates"] = (
            "sequence-matcher/legacy"
        )
        non_git = dp._with_id(non_git_payload, "manifest_id")
        with self.assertRaisesRegex(
            dp.DeltaProtocolError,
            "line_coordinates",
        ):
            dp.validate_manifest(non_git)

    def test_historical_27_path_capture_is_fast_and_constant_process(
        self,
    ) -> None:
        repo, base, head = self._performance_pair()

        def capture(
            selected: list[str] | None,
        ) -> tuple[dict, list[tuple[str, ...]], float]:
            commands = []
            run_git = dp._run_git
            popen_git = dp._popen_git

            def counted_run(
                target: Path,
                args: list[str],
                **kwargs: object,
            ):
                commands.append(tuple(["git", *args]))
                return run_git(target, args, **kwargs)

            def counted_popen(
                target: Path,
                args: list[str],
                **kwargs: object,
            ):
                commands.append(tuple(["git", *args]))
                return popen_git(target, args, **kwargs)

            started = time.perf_counter()
            with (
                mock.patch.object(dp, "_run_git", side_effect=counted_run),
                mock.patch.object(dp, "_popen_git", side_effect=counted_popen),
            ):
                manifest = dp.capture_worktree(
                    repo,
                    base,
                    head=head,
                    source_id="historical-27-path-performance",
                    paths=selected,
                )
            return manifest, commands, time.perf_counter() - started

        many, many_commands, elapsed = capture(None)
        self.assertEqual(len(many["changes"]), 27)
        one, one_commands, _ = capture([many["changes"][0]["path"]])
        self.assertEqual(len(one["changes"]), 1)
        self.assertLess(elapsed, 5.0)
        self.assertLessEqual(len(many_commands), 8)
        self.assertEqual(len(many_commands), len(one_commands))

        for commands in (one_commands, many_commands):
            diffs = [
                command
                for command in commands
                if "diff" in command[1:3]
            ]
            self.assertEqual(len(diffs), 1)
            self.assertIn("--raw", diffs[0])
            self.assertIn("--patch", diffs[0])
            self.assertIn("--unified=0", diffs[0])
            self.assertIn("--find-renames", diffs[0])

    def test_headed_capture_validates_through_rappterverse_entrypoint(
        self,
    ) -> None:
        (self.seed / "state" / "main-only.txt").write_text(
            "advanced main\n",
            encoding="utf-8",
        )
        _git(self.seed, "add", ".")
        _git(self.seed, "commit", "-m", "advance main")
        repo = self._clone("rappterverse-stale-worker")
        _git(repo, "checkout", "-b", "worker", self.base)
        (repo / "state" / "alpha.txt").write_text(
            "worker change\n",
            encoding="utf-8",
        )
        _git(repo, "add", ".")
        _git(repo, "commit", "-m", "worker")

        manifest = dp.capture_worktree(
            repo,
            "origin/main",
            head="HEAD",
            source_id="stale-pr",
        )
        manifest_path = self.tmp / "stale-pr-manifest.json"
        dp.write_manifest(manifest_path, manifest)
        spec = importlib.util.spec_from_file_location(
            "validate_delta_stale_pr_test",
            SCRIPT_DIR / "validate_delta.py",
        )
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        validator = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(validator)
        validator.BASE_DIR = repo
        validator.INBOX_DIR = repo / "state" / "inbox"
        validator.STATE_DIR = repo / "state"
        validator.errors = []

        with mock.patch.dict(os.environ, {
            "VALIDATION_BASE_SHA": "origin/main",
            "VALIDATION_HEAD_SHA": "HEAD",
            "DREAMCATCHER_DELTA_MANIFEST": str(manifest_path),
            "DREAMCATCHER_DELTA_SOURCE_ID": "stale-pr",
        }, clear=False):
            os.environ.pop("DREAMCATCHER_DELTA_TILE", None)
            actual = validator._dreamcatcher_manifest()

        self.assertEqual(validator.errors, [])
        self.assertEqual(actual, manifest)

    def test_validator_capture_matches_canonical_manifest(self) -> None:
        repo = self._clone("validator")
        (repo / "state" / "inbox").mkdir()
        (repo / "state" / "inbox" / "action.json").write_text(
            '{"agent_id":"test-001","timestamp":"2026-01-01T00:00:00Z"}\n',
            encoding="utf-8",
        )
        _git(repo, "add", "state/inbox/action.json")
        _git(repo, "commit", "-m", "add inbox delta")
        head = _git(repo, "rev-parse", "HEAD")
        expected = dp.capture_worktree(
            repo,
            self.base,
            head=head,
            source_id="pr-7",
            tile="alice",
            include_untracked=False,
        )
        spec = importlib.util.spec_from_file_location(
            "validate_delta_protocol_test",
            SCRIPT_DIR / "validate_delta.py",
        )
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        validator = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(validator)
        validator.BASE_DIR = repo
        validator.INBOX_DIR = repo / "state" / "inbox"
        validator.STATE_DIR = repo / "state"
        validator.errors = []

        with mock.patch.dict(os.environ, {
            "VALIDATION_BASE_SHA": self.base,
            "VALIDATION_HEAD_SHA": head,
            "DREAMCATCHER_DELTA_SOURCE_ID": "pr-7",
            "DREAMCATCHER_DELTA_TILE": "alice",
        }, clear=False):
            os.environ.pop("DREAMCATCHER_DELTA_MANIFEST", None)
            actual = validator._dreamcatcher_manifest()

        self.assertEqual(validator.errors, [])
        self.assertEqual(actual, expected)

    def test_manifest_round_trip(self) -> None:
        repo = self._clone("roundtrip")
        (repo / "state" / "new.json").write_text('{"id":"roundtrip"}\n')
        manifest = dp.capture_worktree(repo, self.base)
        path = self.tmp / "manifest.json"
        dp.write_manifest(path, manifest)
        self.assertEqual(dp.load_manifest(path), manifest)


if __name__ == "__main__":
    unittest.main(verbosity=2)
