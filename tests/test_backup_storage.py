from __future__ import annotations

import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from hded_backup_manager.backup_engine import (
    DEFAULT_SETTINGS,
    _is_vboxsf_path,
    prepare_backup_directory,
    read_settings,
    write_settings,
)


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

    def test_backup_mode_defaults_to_scheduled(self) -> None:
        path = self.site / "private" / "hded_backup_manager_settings.json"
        settings = read_settings(path)
        self.assertEqual(settings["backup_mode"], "scheduled")
        self.assertIsNone(settings["one_time_completed_at"])

    def test_virtualbox_shared_folder_keeps_mount_permissions(self) -> None:
        target = self.root / "windows-share" / "backups"
        with patch(
            "hded_backup_manager.backup_engine._filesystem_type",
            return_value="vboxsf",
        ), patch("hded_backup_manager.backup_engine.os.chmod") as chmod:
            result = self.prepare(str(target))
        self.assertEqual(result, target)
        chmod.assert_not_called()
        self.assertTrue(os.access(result, os.W_OK | os.X_OK))

    def test_vboxsf_detection_falls_back_to_mountinfo_when_findmnt_reports_autofs(self) -> None:
        mountinfo = (
            "36 25 0:53 / /mnt/HDED_Backups rw,relatime - vboxsf DHDED_Backups rw\n"
        )
        with patch(
            "hded_backup_manager.backup_engine._filesystem_type",
            return_value="autofs",
        ), patch("pathlib.Path.read_text", return_value=mountinfo):
            self.assertTrue(_is_vboxsf_path(Path("/mnt/HDED_Backups")))
            self.assertTrue(_is_vboxsf_path(Path("/mnt/HDED_Backups/ERPNext")))
            self.assertFalse(_is_vboxsf_path(Path("/mnt/HDED_Backups_Other")))

    def test_virtualbox_shared_folder_mount_root_can_be_selected(self) -> None:
        target = self.root / "windows-share"
        target.mkdir()
        target.chmod(0o770)
        with patch(
            "hded_backup_manager.backup_engine._filesystem_type",
            return_value="vboxsf",
        ), patch(
            "hded_backup_manager.backup_engine.os.path.ismount",
            return_value=True,
        ), patch("hded_backup_manager.backup_engine.os.chmod") as chmod:
            result = self.prepare(str(target))
        self.assertEqual(result, target)
        chmod.assert_not_called()

    def test_one_time_completion_is_saved_with_private_permissions(self) -> None:
        path = self.site / "private" / "hded_backup_manager_settings.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        settings = dict(DEFAULT_SETTINGS)
        settings.update({
            "backup_mode": "one_time",
            "one_time_completed_at": "2026-11-24T21:00:00+03:00",
            "one_time_timestamp": "20261124_210000",
        })
        write_settings(path, settings)
        loaded = read_settings(path)
        self.assertEqual(loaded["backup_mode"], "one_time")
        self.assertEqual(loaded["one_time_timestamp"], "20261124_210000")
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)


if __name__ == "__main__":
    unittest.main()
