from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
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
    runtime_option,
    PRIVATE_EVIDENCE_PATTERNS,
    PRIVATE_EVIDENCE_EXCEPTIONS,
)
from pastor_transcript_extractor.cli import app


REVIEW_ARTIFACTS = (
    "docs/review-proposals/evidence-supply-collector-v3/design-v3.json",
    "docs/review-proposals/evidence-supply-readiness-v2/input-v2.json",
    "evaluation/sermon-topics/listener-directives-review-v3.json",
    "evaluation/sermon-topics/salvation-broader-rollout-inventory-v1.json",
    "docs/review-proposals/evidence-supply-readiness-v1/input-v1.json",
    "evaluation/g2-binding/feasibility-v2.results.json",
    "docs/review-proposals/collector-retrieval-repair-v1.1/development-source-audit-v1.1.json",
    "evaluation/evidence-supply-readiness-v2/source-audit-v2.json",
    "evaluation/sermon-topics/listener-directives-review-v2.json",
    "docs/review-proposals/evidence-supply-readiness-v1/sources/42.json",
    "docs/review-proposals/fresh-discovery-readiness-v3/census-42-v3.json",
    "evaluation/g3-address/cache-v1/key.json",
    "evaluation/observed-profile-consumer-v1/observed-profiles.md",
    "evaluation/sermon-topics/listener-directives-review-v3.md",
    "docs/analytical-review/persisted-inputs.json",
)


class EvaluationPathTests(unittest.TestCase):
    def test_private_policy_and_ignore_rules_stay_in_sync(self) -> None:
        repository = Path(__file__).resolve().parents[1]
        lines = set((repository / ".gitignore").read_text().splitlines())
        self.assertTrue({"/" + p for p in PRIVATE_EVIDENCE_PATTERNS}.issubset(lines))
        self.assertTrue({"!/" + p for p in PRIVATE_EVIDENCE_EXCEPTIONS}.issubset(lines))

    def test_relative_repository_contract_and_pre_migration_read(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary) / "repo"
            paths = build_paths(Path(temporary) / "app")
            for name in ("evaluation/sermon-topics/behavior-contract-v1.json", REVIEW_ARTIFACTS[0]):
                source = repo / name
                source.parent.mkdir(parents=True, exist_ok=True)
                source.write_text("{}")
                self.assertEqual(source.resolve(), resolve_artifact_path(name, paths=paths, repo_root=repo))
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

    def test_legacy_runtime_option_uses_configured_evaluation_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo = root / "repo"
            paths = build_paths(root / "app")
            relative = "speaker-pairs/cache"
            self.assertEqual(
                paths.evaluation / relative,
                runtime_option(
                    Path("evaluation") / relative,
                    paths=paths,
                    relative=relative,
                    repo_root=repo,
                ),
            )
            explicit = root / "custom-cache"
            self.assertEqual(
                explicit.resolve(),
                runtime_option(
                    explicit,
                    paths=paths,
                    relative=relative,
                    repo_root=repo,
                ),
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
    def test_review_packets_keep_bytes_legacy_reads_and_future_writes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            _, repo, app = self._roots(temporary)
            paths = build_paths(app)
            payload = b'{ "source": "Pastor Example", "fingerprint": "immutable" }\n'
            for name in REVIEW_ARTIFACTS:
                source = repo / name
                source.parent.mkdir(parents=True, exist_ok=True)
                source.write_bytes(payload)
            contract = repo / "evaluation/sermon-topics/behavior-contract-v1.json"
            contract.write_text("{}")
            plan = plan_migration(repo_root=repo, evaluation_root=paths.evaluation)
            self.assertEqual(len(REVIEW_ARTIFACTS), plan.planned_files)
            result = apply_migration(plan, verify=True)
            self.assertEqual((), result.failures)
            self.assertEqual(0, result.remaining_legacy_files)
            self.assertFalse(contract.is_symlink())
            for entry in plan.entries:
                source, destination = Path(entry.source), Path(entry.destination)
                self.assertTrue(source.is_symlink())
                self.assertEqual(payload, source.read_bytes())
                self.assertEqual(payload, destination.read_bytes())
                self.assertEqual(entry.sha256, hashlib.sha256(payload).hexdigest())
                for reference in (source, source.relative_to(repo)):
                    self.assertEqual(destination, resolve_artifact_path(reference, paths=paths, repo_root=repo))
                # Old writers follow the same local pointer; new bytes reside outside Git.
                source.write_bytes(payload)
            rerun = plan_migration(repo_root=repo, evaluation_root=paths.evaluation)
            self.assertEqual(0, rerun.planned_files)
            self.assertEqual((), rerun.symlink_rejections)
            self.assertEqual((), apply_migration(rerun).failures)
            removed_link = Path(plan.entries[0].source)
            removed_link.unlink()
            recovery = plan_migration(repo_root=repo, evaluation_root=paths.evaluation)
            self.assertIn("restore_compatibility_link", {entry.status for entry in recovery.entries})
            self.assertEqual((), apply_migration(recovery).failures)
            self.assertTrue(removed_link.is_symlink())

    def test_changed_source_and_changed_identical_destination_are_not_removed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            _, repo, app = self._roots(temporary)
            source = repo / REVIEW_ARTIFACTS[0]
            source.parent.mkdir(parents=True)
            source.write_bytes(b"old")
            plan = plan_migration(repo_root=repo, evaluation_root=app / "evaluation")
            source.write_bytes(b"new")
            self.assertEqual(1, len(apply_migration(plan).failures))
            destination = Path(plan.entries[0].destination)
            destination.parent.mkdir(parents=True)
            destination.write_bytes(b"new")
            identical = plan_migration(repo_root=repo, evaluation_root=app / "evaluation")
            destination.write_bytes(b"changed")
            self.assertEqual(1, len(apply_migration(identical).failures))
            self.assertEqual(b"new", source.read_bytes())

    def test_private_source_symlink_and_destination_collision_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root, repo, app = self._roots(temporary)
            source = repo / REVIEW_ARTIFACTS[0]
            source.parent.mkdir(parents=True)
            outside = root / "outside.json"
            outside.write_bytes(b"outside")
            source.symlink_to(outside)
            plan = plan_migration(repo_root=repo, evaluation_root=app / "evaluation")
            self.assertEqual(1, len(plan.symlink_rejections))
            source.unlink()
            source.write_bytes(b"source")
            plan = plan_migration(repo_root=repo, evaluation_root=app / "evaluation")
            destination = Path(plan.entries[0].destination)
            destination.parent.mkdir(parents=True)
            destination.write_bytes(b"different")
            conflict = plan_migration(repo_root=repo, evaluation_root=app / "evaluation")
            with self.assertRaises(MigrationError):
                apply_migration(conflict)
            self.assertEqual(b"source", source.read_bytes())

    def test_repository_audit_reports_signals_without_repeating_names(self) -> None:
        from pastor_transcript_extractor.evaluation_repository_audit import audit_repository, write_repository_audit
        with tempfile.TemporaryDirectory() as temporary:
            _, repo, app = self._roots(temporary)
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            source = repo / REVIEW_ARTIFACTS[0]
            source.parent.mkdir(parents=True)
            source.write_text('{"target_text":"Pastor Confidentialname", "path":"/Users/privateperson/data"}')
            policy = repo / "docs/policy.md"
            policy.write_text("Keep approved contracts. Pastor Anotherprivate")
            subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
            report = audit_repository(repo)
            self.assertEqual(1, report["migrate_files"])
            self.assertEqual(1, report["retained_review_candidates"])
            output = app / "evaluation/audit.json"
            write_repository_audit(report, output)
            for path in (output, output.with_suffix(".md")):
                text = path.read_text()
                self.assertNotIn("Confidentialname", text)
                self.assertNotIn("privateperson", text)
                self.assertNotIn("Anotherprivate", text)

    def _roots(self, temporary: str) -> tuple[Path, Path, Path]:
        root = Path(temporary).resolve()
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
            sermon_cache = repo / "evaluation/sermon-topics/cache/result.json"
            sermon_cache.parent.mkdir(parents=True)
            sermon_cache.write_text("{}", encoding="utf-8")
            sermon_contract = repo / "evaluation/sermon-topics/behavior-contract-v1.json"
            sermon_contract.write_text("{}", encoding="utf-8")

            plan = plan_migration(repo_root=repo, evaluation_root=app / "evaluation")
            self.assertEqual(2, plan.planned_files)
            self.assertTrue(generated.exists())
            result = apply_migration(plan, verify=True)
            self.assertEqual(2, result.moved_files)
            self.assertFalse(generated.exists())
            self.assertFalse(sermon_cache.exists())
            self.assertTrue(reviewed.exists())
            self.assertTrue(sermon_contract.exists())
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
