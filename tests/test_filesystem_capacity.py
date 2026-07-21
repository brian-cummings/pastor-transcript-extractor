from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from pastor_transcript_extractor import filesystem_capacity as capacity_module


class FilesystemCapacityTests(unittest.TestCase):
    def test_portable_capacity_is_used_off_macos(self) -> None:
        with (
            patch.object(capacity_module.sys, "platform", "linux"),
            patch.object(
                capacity_module.shutil,
                "disk_usage",
                return_value=SimpleNamespace(free=1234),
            ),
            patch.object(capacity_module, "_darwin_filesystem_capacity") as native,
        ):
            result = capacity_module.filesystem_capacity(Path("/archive"))

        self.assertEqual(1234, result.available_bytes)
        self.assertEqual("shutil_disk_usage", result.source)
        self.assertIsNone(result.filesystem_type)
        native.assert_not_called()

    def test_native_statfs_is_used_for_macos_smb(self) -> None:
        native_capacity = capacity_module._DarwinCapacity(
            available_bytes=8 * 1024**4,
            filesystem_type="smbfs",
        )
        with (
            patch.object(capacity_module.sys, "platform", "darwin"),
            patch.object(
                capacity_module.shutil,
                "disk_usage",
                return_value=SimpleNamespace(free=10 * 1024**3),
            ),
            patch.object(
                capacity_module,
                "_darwin_filesystem_capacity",
                return_value=native_capacity,
            ),
        ):
            result = capacity_module.filesystem_capacity(Path("/Volumes/home"))

        self.assertEqual(8 * 1024**4, result.available_bytes)
        self.assertEqual("darwin_statfs", result.source)
        self.assertEqual("smbfs", result.filesystem_type)
        self.assertEqual(10 * 1024**3, result.portable_available_bytes)

    def test_portable_capacity_remains_authoritative_for_macos_local_disk(self) -> None:
        native_capacity = capacity_module._DarwinCapacity(
            available_bytes=9999,
            filesystem_type="apfs",
        )
        with (
            patch.object(capacity_module.sys, "platform", "darwin"),
            patch.object(
                capacity_module.shutil,
                "disk_usage",
                return_value=SimpleNamespace(free=1234),
            ),
            patch.object(
                capacity_module,
                "_darwin_filesystem_capacity",
                return_value=native_capacity,
            ),
        ):
            result = capacity_module.filesystem_capacity(Path("/archive"))

        self.assertEqual(1234, result.available_bytes)
        self.assertEqual("shutil_disk_usage", result.source)

    def test_failed_native_query_falls_back_to_portable_capacity(self) -> None:
        with (
            patch.object(capacity_module.sys, "platform", "darwin"),
            patch.object(
                capacity_module.shutil,
                "disk_usage",
                return_value=SimpleNamespace(free=1234),
            ),
            patch.object(
                capacity_module,
                "_darwin_filesystem_capacity",
                side_effect=OSError("statfs failed"),
            ),
        ):
            result = capacity_module.filesystem_capacity(Path("/Volumes/home"))

        self.assertEqual(1234, result.available_bytes)
        self.assertEqual("shutil_disk_usage", result.source)

    def test_portable_error_is_preserved_when_no_supported_reading_exists(self) -> None:
        portable_error = OSError("disk usage failed")
        with (
            patch.object(capacity_module.sys, "platform", "darwin"),
            patch.object(
                capacity_module.shutil,
                "disk_usage",
                side_effect=portable_error,
            ),
            patch.object(
                capacity_module,
                "_darwin_filesystem_capacity",
                side_effect=OSError("statfs failed"),
            ),
        ):
            with self.assertRaises(OSError) as raised:
                capacity_module.filesystem_capacity(Path("/Volumes/home"))

        self.assertIs(portable_error, raised.exception)


if __name__ == "__main__":
    unittest.main()
