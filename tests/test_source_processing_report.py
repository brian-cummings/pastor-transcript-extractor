from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from typer.testing import CliRunner

from pastor_transcript_extractor.cli import app
from pastor_transcript_extractor.storage import Database


class SourceProcessingReportCliTests(unittest.TestCase):
    def test_command_rejects_an_output_path_that_is_the_database(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            database_path = Path(tmp) / "app.db"
            Database(database_path).initialize()
            before_hash = hashlib.sha256(database_path.read_bytes()).hexdigest()

            result = CliRunner().invoke(
                app,
                [
                    "source-processing-report",
                    "--database",
                    str(database_path),
                    "--json",
                    str(database_path),
                ],
            )

            self.assertNotEqual(0, result.exit_code)
            self.assertIn("must not overwrite", result.output)
            self.assertEqual(before_hash, hashlib.sha256(database_path.read_bytes()).hexdigest())

    def test_command_writes_reconciled_reports_without_mutating_database(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            database_path = root / "app.db"
            database = Database(database_path)
            database.initialize()
            self._seed_report_fixture(database)
            before_hash = hashlib.sha256(database_path.read_bytes()).hexdigest()
            markdown_path = root / "reports" / "sources.md"
            json_path = root / "reports" / "sources.json"

            result = CliRunner().invoke(
                app,
                [
                    "source-processing-report",
                    "--database",
                    str(database_path),
                    "--markdown",
                    str(markdown_path),
                    "--json",
                    str(json_path),
                ],
            )

            self.assertEqual(0, result.exit_code, msg=result.output)
            self.assertEqual(before_hash, hashlib.sha256(database_path.read_bytes()).hexdigest())
            payload = json.loads(json_path.read_text(encoding="utf-8"))
            self.assertEqual(2, payload["summary"]["total_sources"])
            self.assertEqual(4, payload["summary"]["total_cataloged_videos"])
            self.assertEqual(1, payload["summary"]["videos_with_media_attempt"])
            self.assertEqual(3, payload["summary"]["videos_without_media_attempt"])
            self.assertEqual(1, payload["summary"]["videos_with_verified_audio"])
            self.assertEqual(1, payload["summary"]["successful_without_media_attempt"])
            self.assertEqual(1, payload["summary"]["sources_without_speaker_profile"])

            zero_source, populated_source = payload["sources"]
            self.assertEqual(2, zero_source["source_id"])
            self.assertIn("PROFILE_UNAVAILABLE", zero_source["flags"])
            self.assertIn("ZERO_VIDEOS", zero_source["flags"])
            self.assertEqual(1, populated_source["videos_with_verified_source_audio"])
            self.assertEqual(1, populated_source["videos_with_verified_normalized_audio"])
            self.assertEqual(1, populated_source["videos_with_transcript_artifacts"])
            self.assertEqual(1, populated_source["videos_with_caption_transcript_artifacts"])
            self.assertEqual(1, populated_source["videos_with_local_asr_transcript_artifacts"])
            self.assertIn("SUCCESS_WITHOUT_MEDIA_ATTEMPT", populated_source["flags"])
            self.assertIn("MEDIA_VERIFIED_BUT_NOT_EXTRACTED", populated_source["flags"])
            self.assertIn("CATALOGED_WITHOUT_PROCESSING", populated_source["flags"])
            self.assertIn("FAILED_WITHOUT_MEDIA_ATTEMPT", populated_source["flags"])
            markdown = markdown_path.read_text(encoding="utf-8")
            self.assertIn("# Source Processing Report", markdown)
            self.assertIn("Sample Organization", markdown)

    @staticmethod
    def _seed_report_fixture(database: Database) -> None:
        with database.connect() as connection:
            connection.execute(
                "INSERT INTO pastors (id, slug, display_name, added_at) VALUES (1, 'sample', 'Sample Pastor', '2026-01-01T00:00:00+00:00')"
            )
            connection.execute(
                "INSERT INTO organizations (id, slug, display_name, organization_type, added_at) VALUES (1, 'sample-org', 'Sample Organization', 'church', '2026-01-01T00:00:00+00:00')"
            )
            connection.execute(
                "INSERT INTO speaker_profiles (id, stable_key, display_label, lifecycle_state, created_reason, created_at) VALUES (1, 'profile-1', 'Sample Pastor', 'active', 'test', '2026-01-01T00:00:00+00:00')"
            )
            connection.execute(
                "INSERT INTO pastor_speaker_bindings (pastor_id, profile_id, binding_kind, created_at) VALUES (1, 1, 'manual', '2026-01-01T00:00:00+00:00')"
            )
            connection.execute(
                "INSERT INTO sources (id, pastor_id, url, source_type, added_at, organization_id) VALUES (1, 1, 'https://example.com/source-1', 'channel', '2026-01-01T00:00:00+00:00', 1)"
            )
            connection.execute(
                "INSERT INTO sources (id, pastor_id, url, source_type, added_at) VALUES (2, NULL, 'https://example.com/source-2', 'channel', '2026-01-01T00:00:00+00:00')"
            )
            videos = [
                (1, "video-1", "Extracted", "extracted"),
                (2, "video-2", "Discovered", "discovered"),
                (3, "video-3", "Failed", "failed"),
                (4, "video-4", "Verified discovered", "discovered"),
            ]
            for video_id, youtube_id, title, status in videos:
                connection.execute(
                    "INSERT INTO videos (id, source_id, pastor_id, youtube_video_id, title, url, channel_name, status) VALUES (?, 1, 1, ?, ?, ?, 'Sample Channel', ?)",
                    (video_id, youtube_id, title, f"https://example.com/{youtube_id}", status),
                )
            connection.execute(
                """INSERT INTO media_artifacts
                   (id, video_id, parent_media_artifact_id, artifact_kind, provenance_kind,
                    artifact_path, manifest_path, content_sha256, byte_size, acquisition_tool,
                    acquisition_tool_version, input_fingerprint, created_at)
                   VALUES (1, 4, NULL, 'source_audio', 'original_download', 'source.wav',
                           'source.json', 'source-sha', 10, 'test', '1', 'source-input',
                           '2026-01-02T00:00:00+00:00')"""
            )
            connection.execute(
                """INSERT INTO media_artifacts
                   (id, video_id, parent_media_artifact_id, artifact_kind, provenance_kind,
                    artifact_path, manifest_path, content_sha256, byte_size, acquisition_tool,
                    acquisition_tool_version, input_fingerprint, created_at)
                   VALUES (2, 4, 1, 'normalized_audio', 'derived', 'normalized.wav',
                           'normalized.json', 'normalized-sha', 10, 'test', '1', 'normalized-input',
                           '2026-01-02T00:01:00+00:00')"""
            )
            connection.execute(
                """INSERT INTO media_acquisition_attempts
                   (video_id, target_kind, outcome, reason_code, media_artifact_id,
                    service_version, input_fingerprint, created_at)
                   VALUES (4, 'normalized_audio', 'verified', 'ok', 2, '1', 'attempt-input',
                           '2026-01-02T00:02:00+00:00')"""
            )
            for source_kind in ("captions", "local_asr"):
                connection.execute(
                    "INSERT INTO transcript_artifacts (video_id, source_kind, created_at) VALUES (4, ?, '2026-01-02T00:03:00+00:00')",
                    (source_kind,),
                )


if __name__ == "__main__":
    unittest.main()
