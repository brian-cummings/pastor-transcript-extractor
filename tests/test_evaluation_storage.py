from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from typer.testing import CliRunner

from pastor_transcript_extractor.config import build_paths
from pastor_transcript_extractor.evaluation_migration import (
    MigrationError,
    apply_migration,
    backup_database,
    migrate_database_paths,
    plan_migration,
)
from pastor_transcript_extractor.evaluation_storage import (
    build_evaluation_paths,
    portable_artifact_path,
    resolve_artifact_path,
    runtime_default,
)
from pastor_transcript_extractor.cli import app


class EvaluationPathTests(unittest.TestCase):
    def test_configured_root_and_explicit_override(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary) / "app"
            paths = build_paths(base)
            self.assertEqual(base.resolve() / "evaluation", paths.evaluation)
            self.assertEqual(paths.evaluation, build_evaluation_paths(paths).root)
            explicit = Path(temporary) / "elsewhere"
            self.assertEqual(
                explicit.resolve(),
                runtime_default(explicit, paths=paths, relative="diagnostics"),
            )
            self.assertEqual(
                paths.evaluation / "diagnostics",
                runtime_default(None, paths=paths, relative="diagnostics"),
            )

    def test_legacy_translation_and_repository_input_preservation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo = root / "repo"
            paths = build_paths(root / "app")
            legacy = repo / "evaluation/speaker-pairs/cache/item.json"
            relocated = paths.evaluation / "speaker-pairs/cache/item.json"
            relocated.parent.mkdir(parents=True)
            relocated.write_text("{}", encoding="utf-8")
            self.assertEqual(
                relocated.resolve(),
                resolve_artifact_path(legacy, paths=paths, repo_root=repo),
            )
            reviewed = repo / "evaluation/speaker-pairs/reviews/review.json"
            self.assertEqual(
                reviewed.resolve(),
                resolve_artifact_path(reviewed, paths=paths, repo_root=repo),
            )
            self.assertEqual(
                "speaker-pairs/cache/item.json",
                portable_artifact_path(relocated, paths=paths),
            )


class EvaluationMigrationTests(unittest.TestCase):
    def _roots(self, temporary: str) -> tuple[Path, Path, Path]:
        root = Path(temporary)
        repo = root / "repo"
        app = root / "app"
        repo.mkdir()
        return root, repo, app

    def test_dry_run_apply_idempotency_and_source_inputs_remain(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            _, repo, app = self._roots(temporary)
            generated = repo / "evaluation/diagnostics/run/report.json"
            generated.parent.mkdir(parents=True)
            generated.write_text('{"ok": true}', encoding="utf-8")
            reviewed = repo / "evaluation/fixtures/reviewed.json"
            reviewed.parent.mkdir(parents=True)
            reviewed.write_text("{}", encoding="utf-8")

            plan = plan_migration(repo_root=repo, evaluation_root=app / "evaluation")
            self.assertEqual(1, plan.planned_files)
            self.assertTrue(generated.exists())
            result = apply_migration(plan, verify=True)
            self.assertEqual(1, result.moved_files)
            self.assertFalse(generated.exists())
            self.assertTrue(reviewed.exists())
            rerun = plan_migration(repo_root=repo, evaluation_root=app / "evaluation")
            self.assertEqual(0, rerun.planned_files)
            self.assertEqual(0, apply_migration(rerun).moved_files)

    def test_cli_dry_run_is_default_and_writes_manifest_without_moving(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root, repo, app_root = self._roots(temporary)
            source = repo / "evaluation/results/run.json"
            source.parent.mkdir(parents=True)
            source.write_text("{}", encoding="utf-8")
            manifest = root / "manifest.json"
            result = CliRunner().invoke(
                app,
                [
                    "migrate-evaluation-storage",
                    "--base-dir",
                    str(app_root),
                    "--repo-root",
                    str(repo),
                    "--manifest",
                    str(manifest),
                ],
            )
            self.assertEqual(0, result.exit_code, msg=result.output)
            self.assertIn("dry-run", result.output)
            self.assertTrue(source.exists())
            self.assertEqual(1, json.loads(manifest.read_text())["summary"]["planned_files"])

    def test_symlink_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root, repo, app_root = self._roots(temporary)
            outside = root / "outside.json"
            outside.write_text("{}", encoding="utf-8")
            link = repo / "evaluation/results/escape.json"
            link.parent.mkdir(parents=True)
            link.symlink_to(outside)
            plan = plan_migration(repo_root=repo, evaluation_root=app_root / "evaluation")
            self.assertEqual(1, len(plan.symlink_rejections))
            self.assertTrue(plan.symlink_rejections[0].endswith("/results/escape.json"))
            with self.assertRaises(MigrationError):
                apply_migration(plan)

    def test_identical_destination_is_reused_and_conflict_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            _, repo, app = self._roots(temporary)
            source = repo / "evaluation/results/run.json"
            destination = app / "evaluation/results/run.json"
            source.parent.mkdir(parents=True)
            destination.parent.mkdir(parents=True)
            source.write_bytes(b"same")
            destination.write_bytes(b"same")
            plan = plan_migration(repo_root=repo, evaluation_root=app / "evaluation")
            self.assertEqual(1, plan.already_migrated)
            apply_migration(plan)
            self.assertFalse(source.exists())

            source.write_bytes(b"source")
            destination.write_bytes(b"destination")
            conflict = plan_migration(repo_root=repo, evaluation_root=app / "evaluation")
            self.assertEqual(1, len(conflict.conflicts))
            with self.assertRaises(MigrationError):
                apply_migration(conflict)
            self.assertEqual(b"source", source.read_bytes())

    def test_copy_failure_keeps_source_and_no_partial_destination(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            _, repo, app = self._roots(temporary)
            source = repo / "evaluation/diagnostics/run.bin"
            source.parent.mkdir(parents=True)
            source.write_bytes(b"important")
            plan = plan_migration(repo_root=repo, evaluation_root=app / "evaluation")

            def fail_copy(_source: Path, temporary_destination: Path) -> None:
                temporary_destination.write_bytes(b"partial")
                raise OSError("injected copy failure")

            result = apply_migration(plan, copy_file=fail_copy, force_copy=True)
            self.assertEqual(1, len(result.failures))
            self.assertTrue(source.exists())
            self.assertFalse((app / "evaluation/diagnostics/run.bin").exists())

    def test_immutable_json_bytes_and_cache_name_survive_relocation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            _, repo, app = self._roots(temporary)
            source = (
                repo
                / "evaluation/speaker-profile-discovery/promotion-judgments"
                / "group-abc/input-fingerprint.json"
            )
            source.parent.mkdir(parents=True)
            source.write_text(
                json.dumps({"result_sha256": "content-addressed", "legacy_path": str(source)}),
                encoding="utf-8",
            )
            before = hashlib.sha256(source.read_bytes()).hexdigest()
            plan = plan_migration(repo_root=repo, evaluation_root=app / "evaluation")
            apply_migration(plan, verify=True)
            destination = (
                app
                / "evaluation/speaker-profile-discovery/promotion-judgments"
                / "group-abc/input-fingerprint.json"
            )
            self.assertEqual(before, hashlib.sha256(destination.read_bytes()).hexdigest())
            self.assertEqual("input-fingerprint.json", destination.name)

    def test_database_updates_are_enumerated_and_rollback_atomically(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            _, repo, app = self._roots(temporary)
            database = app / "app.db"
            app.mkdir()
            connection = sqlite3.connect(database)
            connection.execute(
                "CREATE TABLE speaker_profile_discovery_promotions ("
                "discovery_artifact_path TEXT, promotion_judgment_artifact_path TEXT)"
            )
            old = str(repo / "evaluation/speaker-profile-discovery/shadow-runs/report.json")
            connection.execute(
                "INSERT INTO speaker_profile_discovery_promotions VALUES (?, NULL)", (old,)
            )
            connection.commit()
            connection.close()

            backup = app / "app.db.pre-evaluation-migration.bak"
            self.assertTrue(backup_database(database, backup))
            self.assertFalse(backup_database(database, backup))
            backup_connection = sqlite3.connect(backup)
            self.assertEqual(
                old,
                backup_connection.execute(
                    "SELECT discovery_artifact_path FROM speaker_profile_discovery_promotions"
                ).fetchone()[0],
            )
            backup_connection.close()
            plan = plan_migration(
                repo_root=repo,
                evaluation_root=app / "evaluation",
                database_path=database,
            )
            self.assertEqual(1, len(plan.database_changes))
            with self.assertRaises(RuntimeError):
                migrate_database_paths(
                    database,
                    plan.database_changes,
                    before_commit=lambda: (_ for _ in ()).throw(RuntimeError("stop")),
                )
            connection = sqlite3.connect(database)
            self.assertEqual(
                old,
                connection.execute(
                    "SELECT discovery_artifact_path FROM speaker_profile_discovery_promotions"
                ).fetchone()[0],
            )
            connection.close()


if __name__ == "__main__":
    unittest.main()
