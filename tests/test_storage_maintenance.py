from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from typer.testing import CliRunner

from pastor_transcript_extractor.cli import app
from pastor_transcript_extractor.config import build_paths
from pastor_transcript_extractor.storage import Database
from pastor_transcript_extractor.storage_maintenance import (
    StorageMaintenanceError,
    apply_storage_maintenance,
    plan_storage_maintenance,
    restore_storage_archive,
    verify_storage_archive,
)


class StorageMaintenanceTests(unittest.TestCase):
    def _roots(self, temporary: str) -> tuple[Path, Path, Path, Path]:
        root = Path(temporary)
        app_root = root / "app"
        repository_root = root / "repo"
        archive_root = root / "archive"
        (app_root / "evaluation").mkdir(parents=True)
        repository_root.mkdir()
        return root, app_root, repository_root, archive_root

    def _span(
        self,
        evaluation_root: Path,
        key: str,
        wav: bytes,
        *,
        version: str = "speaker_span_v1",
    ) -> str:
        root = evaluation_root / "speaker-pairs/cache/spans"
        root.mkdir(parents=True, exist_ok=True)
        wav_path = root / f"{key}.wav"
        wav_path.write_bytes(wav)
        wav_sha256 = hashlib.sha256(wav).hexdigest()
        (root / f"{key}.json").write_text(
            json.dumps(
                {
                    "cache_key": key,
                    "input": {"extractor_version": version},
                    "span": {"wav_sha256": wav_sha256},
                }
            ),
            encoding="utf-8",
        )
        return wav_sha256

    def test_plan_keeps_newest_diagnostic_and_review_pinned_legacy_span(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            _, app_root, repository_root, archive_root = self._roots(temporary)
            evaluation = app_root / "evaluation"
            old = evaluation / "diagnostics/20260101T000000Z/report.json"
            newest = evaluation / "diagnostics/20260102T000000Z/report.json"
            old.parent.mkdir(parents=True)
            newest.parent.mkdir(parents=True)
            old.write_text('{"old": true}', encoding="utf-8")
            newest.write_text('{"new": true}', encoding="utf-8")
            pinned = self._span(evaluation, "a" * 64, b"pinned")
            self._span(evaluation, "b" * 64, b"obsolete")
            review = repository_root / "evaluation/speaker-pairs/reviews/pair/review.json"
            review.parent.mkdir(parents=True)
            review.write_text(json.dumps({"clip": {"wav_sha256": pinned}}), encoding="utf-8")

            plan = plan_storage_maintenance(
                build_paths(app_root),
                repository_root=repository_root,
                archive_root=archive_root,
                keep_diagnostic_runs=1,
            )

            self.assertEqual([], list(plan.blocked))
            self.assertEqual(
                {"20260101T000000Z"},
                {unit.unit_id for unit in plan.units if unit.category == "diagnostics"},
            )
            legacy = next(unit for unit in plan.units if unit.category == "speaker-pairs")
            self.assertTrue(legacy.unit_id.startswith("unreferenced-speaker-span-v1-"))
            self.assertEqual(2, len(legacy.members))
            self.assertTrue(all(("b" * 64) in member.path for member in legacy.members))
            self.assertFalse(any(str(old.parent) == item.get("path") for item in plan.retained))
            self.assertTrue(
                any(str(newest.parent.resolve()) == item.get("path") for item in plan.retained)
            )

    def test_apply_is_verified_rerunnable_and_restorable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            _, app_root, repository_root, archive_root = self._roots(temporary)
            evaluation = app_root / "evaluation"
            old = evaluation / "diagnostics/20260101T000000Z/report.json"
            newest = evaluation / "diagnostics/20260102T000000Z/report.json"
            old.parent.mkdir(parents=True)
            newest.parent.mkdir(parents=True)
            old.write_bytes(b"historical diagnostic")
            newest.write_bytes(b"current diagnostic")
            self._span(evaluation, "c" * 64, b"legacy span")
            plan = plan_storage_maintenance(
                build_paths(app_root),
                repository_root=repository_root,
                archive_root=archive_root,
                keep_diagnostic_runs=1,
            )

            result = apply_storage_maintenance(plan, app_root=app_root)

            self.assertFalse(result.failures)
            self.assertEqual(3, result.removed_files)
            self.assertFalse(old.exists())
            self.assertTrue(newest.exists())
            self.assertFalse((archive_root / "diagnostics/20260101T000000Z.zip").exists())
            speaker_result = next(unit for unit in result.units if unit.category == "speaker-pairs")
            archive = Path(speaker_result.archive_path or "")
            verification = verify_storage_archive(archive)
            self.assertEqual(2, verification.member_count)

            restore = restore_storage_archive(
                archive,
                evaluation_root=evaluation,
                apply=True,
            )
            self.assertEqual(2, restore.restored)
            self.assertFalse(old.exists())
            repeated_restore = restore_storage_archive(
                archive,
                evaluation_root=evaluation,
                apply=True,
            )
            self.assertEqual(0, repeated_restore.restored)
            self.assertEqual(2, repeated_restore.already_present)

            repeated_plan = plan_storage_maintenance(
                build_paths(app_root),
                repository_root=repository_root,
                archive_root=archive_root,
                keep_diagnostic_runs=1,
            )
            repeated_apply = apply_storage_maintenance(repeated_plan, app_root=app_root)
            self.assertFalse(repeated_apply.failures)
            self.assertEqual(2, repeated_apply.removed_files)
            self.assertFalse(old.exists())

    def test_changed_source_is_not_archived_or_removed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            _, app_root, repository_root, archive_root = self._roots(temporary)
            evaluation = app_root / "evaluation"
            old = evaluation / "diagnostics/20260101T000000Z/report.json"
            newest = evaluation / "diagnostics/20260102T000000Z/report.json"
            old.parent.mkdir(parents=True)
            newest.parent.mkdir(parents=True)
            old.write_bytes(b"before")
            newest.write_bytes(b"new")
            plan = plan_storage_maintenance(
                build_paths(app_root),
                repository_root=repository_root,
                archive_root=archive_root,
                keep_diagnostic_runs=1,
            )
            old.write_bytes(b"changed after plan")

            result = apply_storage_maintenance(plan, app_root=app_root)

            self.assertEqual(1, len(result.failures))
            self.assertTrue(old.exists())
            self.assertFalse((archive_root / "diagnostics/20260101T000000Z.zip").exists())

    def test_unavailable_archive_mount_is_not_created(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root, app_root, repository_root, _ = self._roots(temporary)
            evaluation = app_root / "evaluation"
            old = evaluation / "diagnostics/20260101T000000Z/report.json"
            newest = evaluation / "diagnostics/20260102T000000Z/report.json"
            old.parent.mkdir(parents=True)
            newest.parent.mkdir(parents=True)
            old.write_bytes(b"old")
            newest.write_bytes(b"new")
            self._span(evaluation, "d" * 64, b"legacy")
            unavailable = root / "missing-mount/evaluation-storage"
            plan = plan_storage_maintenance(
                build_paths(app_root),
                repository_root=repository_root,
                archive_root=unavailable,
                keep_diagnostic_runs=1,
            )

            with self.assertRaises(StorageMaintenanceError):
                apply_storage_maintenance(plan, app_root=app_root)

            self.assertTrue(old.exists())
            self.assertFalse((root / "missing-mount").exists())

    def test_default_diagnostic_retention_keeps_three_newest_runs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            _, app_root, repository_root, archive_root = self._roots(temporary)
            evaluation = app_root / "evaluation"
            for day in range(1, 6):
                report = evaluation / f"diagnostics/2026010{day}T000000Z/report.json"
                report.parent.mkdir(parents=True)
                report.write_text(str(day), encoding="utf-8")

            plan = plan_storage_maintenance(
                build_paths(app_root),
                repository_root=repository_root,
                archive_root=archive_root,
            )

            diagnostic_units = [unit for unit in plan.units if unit.category == "diagnostics"]
            self.assertEqual(
                ["20260101T000000Z", "20260102T000000Z"],
                [unit.unit_id for unit in diagnostic_units],
            )
            self.assertTrue(all(unit.action == "discard_local" for unit in diagnostic_units))

    def test_cli_compact_is_dry_run_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root, app_root, repository_root, archive_root = self._roots(temporary)
            old = app_root / "evaluation/diagnostics/20260101T000000Z/report.json"
            newest = app_root / "evaluation/diagnostics/20260102T000000Z/report.json"
            old.parent.mkdir(parents=True)
            newest.parent.mkdir(parents=True)
            old.write_bytes(b"old")
            newest.write_bytes(b"new")
            manifest = root / "plan.json"

            result = CliRunner().invoke(
                app,
                [
                    "storage",
                    "compact",
                    "--base-dir",
                    str(app_root),
                    "--repo-root",
                    str(repository_root),
                    "--archive-root",
                    str(archive_root),
                    "--keep-diagnostic-runs",
                    "1",
                    "--manifest",
                    str(manifest),
                ],
            )

            self.assertEqual(0, result.exit_code, msg=result.output)
            self.assertIn("dry-run", result.output)
            self.assertIn("No files changed", result.output)
            self.assertTrue(old.exists())
            summary = json.loads(manifest.read_text())["summary"]
            self.assertEqual(0, summary["archive_units"])
            self.assertEqual(1, summary["discard_units"])

    def test_cli_reuses_configured_media_archive_namespace(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root, app_root, repository_root, archive_root = self._roots(temporary)
            database = Database(app_root / "app.db")
            database.initialize()
            database.configure_media_archive_destination(str(archive_root))
            manifest = root / "plan.json"

            result = CliRunner().invoke(
                app,
                [
                    "storage",
                    "compact",
                    "--base-dir",
                    str(app_root),
                    "--repo-root",
                    str(repository_root),
                    "--manifest",
                    str(manifest),
                ],
            )

            self.assertEqual(0, result.exit_code, msg=result.output)
            self.assertEqual(
                str((archive_root / "evaluation-storage").resolve()),
                json.loads(manifest.read_text())["archive_root"],
            )


if __name__ == "__main__":
    unittest.main()
