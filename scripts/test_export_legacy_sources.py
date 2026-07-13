#!/usr/bin/env python3

import json
import tempfile
import unittest
from pathlib import Path

import export_legacy_sources


class TestLegacySourceExport(unittest.TestCase):
    def test_lock_resolves_exact_commits_and_trees(self):
        lock = json.loads(export_legacy_sources.LOCK_PATH.read_text())
        for source in lock["sources"].values():
            self.assertEqual(
                export_legacy_sources.git("rev-parse", source["commit"]).strip(),
                source["commit"],
            )
            self.assertEqual(
                export_legacy_sources.git(
                    "rev-parse", f"{source['commit']}^{{tree}}"
                ).strip(),
                source["tree"],
            )

    def test_export_is_deterministic(self):
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            first_manifest = export_legacy_sources.export(Path(first))
            second_manifest = export_legacy_sources.export(Path(second))
            self.assertEqual(first_manifest, second_manifest)
            first_files = {
                path.relative_to(first): path.read_bytes()
                for path in Path(first).rglob("*")
                if path.is_file()
            }
            second_files = {
                path.relative_to(second): path.read_bytes()
                for path in Path(second).rglob("*")
                if path.is_file()
            }
            self.assertEqual(first_files, second_files)
            self.assertTrue(first_files)
            self.assertTrue(all(len(content) <= 1_000_000 for content in first_files.values()))


if __name__ == "__main__":
    unittest.main()
