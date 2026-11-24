from __future__ import annotations

import os
import stat
import tempfile
import unittest
from pathlib import Path

from hded_backup_manager.backup_engine import prepare_backup_directory


class BackupDirectoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="hded-backup-tests-")
        self.root = Path(self.temp.name).resolve()
        self.bench = self.root / "bench"
        self.site = self.bench / "sites" / "hded.erp"
        self.site.mkdir(parents=True)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def prepare(self, path: str = "", **kwargs) -> Path:
        return prepare_backup_directory(
            site_path=self.site,
            bench_dir=self.bench,
            local_path=path,
            **kwargs,
        )

    def test_default_directory_is_inside_site_private_backups(self) -> None:
        result = self.prepare()
        self.assertEqual(result, self.site / "private" / "backups")
        self.assertTrue(result.is_dir())
        self.assertEqual(stat.S_IMODE(result.stat().st_mode), 0o700)

    def test_custom_directory_is_created_and_private(self) -> None:
        target = self.root / "external-backups" / "hded"
        result = self.prepare(str(target))
        self.assertEqual(result, target)
        self.assertTrue(result.is_dir())
        self.assertEqual(stat.S_IMODE(result.stat().st_mode), 0o700)
        self.assertTrue(os.access(result, os.W_OK | os.X_OK))

    def test_relative_path_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.prepare("backups")

    def test_path_inside_bench_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.prepare(str(self.bench / "unsafe-backups"))

    def test_system_root_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.prepare("/var")

    def test_symlink_path_is_rejected(self) -> None:
        target = self.root / "real-backups"
        target.mkdir()
        link = self.root / "backup-link"
        link.symlink_to(target, target_is_directory=True)
        with self.assertRaises(ValueError):
            self.prepare(str(link))

    def test_separate_mount_requirement_rejects_root_filesystem(self) -> None:
        target = self.root / "not-a-separate-volume"
        with self.assertRaises(ValueError):
            self.prepare(str(target), require_mount=True)


if __name__ == "__main__":
    unittest.main()
