from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from typer.testing import CliRunner

from pastor_transcript_extractor.cli import app
from pastor_transcript_extractor.config import build_paths
from pastor_transcript_extractor.exporting import export_profile_transcript_collection
from pastor_transcript_extractor.models import SourceType, VideoStatus
from pastor_transcript_extractor.storage import Database


class ProfileTranscriptCollectionTests(unittest.TestCase):
    def _build_profile_sermon(self, root: Path) -> tuple[Database, int, int]:
        paths = build_paths(root)
        database = Database(paths.database)
        database.initialize()
        source = database.add_source(
            "https://www.youtube.com/watch?v=profile-sermon",
            SourceType.VIDEO,
            pastor_id=None,
        )
        video = database.add_video(
            source_id=source.id,
            pastor_id=None,
            youtube_video_id="profile-sermon",
            title="A Profile Sermon",
            url="https://www.youtube.com/watch?v=profile-sermon",
            status=VideoStatus.EXTRACTED,
        )
        proposed_path = root / "artifacts" / "proposed.md"
        proposed_json_path = root / "artifacts" / "proposed.json"
        proposed_path.parent.mkdir(parents=True, exist_ok=True)
        proposed_path.write_text("Full fallback transcript", encoding="utf-8")
        proposed_json_path.write_text(
            json.dumps(
                {
                    "transcript_source": "captions",
                    "sermon_window": {
                        "start_seconds": 10.0,
                        "end_seconds": 70.0,
                        "included_segment_indexes": [1],
                    },
                    "segments": [
                        {
                            "start_seconds": 0.0,
                            "end_seconds": 10.0,
                            "text": "Host introduction",
                        },
                        {
                            "start_seconds": 10.0,
                            "end_seconds": 70.0,
                            "text": "The profile sermon transcript.",
                        },
                    ],
                    "final_disposition": {"status": "accepted_sermon"},
                }
            ),
            encoding="utf-8",
        )
        extraction = database.add_extraction_result(
            video_id=video.id,
            version=1,
            proposed_text_path=str(proposed_path),
            proposed_json_path=str(proposed_json_path),
        )
        profile = database.ensure_speaker_profile(
            stable_key="reviewed-speaker",
            display_label="Reviewed Speaker",
            lifecycle_state="curated",
            created_reason="manual_review",
        )
        observation = database.add_speaker_observation(
            video_id=video.id,
            extraction_result_id=extraction.id,
            role="principal_speaker",
            multiplicity_state="single",
            start_seconds=10.0,
            end_seconds=70.0,
            artifact_path=str(proposed_json_path),
            content_sha256="profile-export-content",
            extractor_version="test",
            input_fingerprint="profile-export-observation",
        )
        database.add_profile_observation_event(
            profile_id=profile.id,
            observation_id=observation.id,
            action="attach",
            reviewer="reviewer",
            reason="Confirmed speaker",
            event_fingerprint="profile-export-attachment",
        )
        return database, profile.id, observation.id

    def test_exports_canonical_profile_collection_and_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            database, profile_id, observation_id = self._build_profile_sermon(root)

            result = export_profile_transcript_collection(
                database,
                build_paths(root),
                profile_id,
            )

            self.assertEqual(profile_id, result.profile_id)
            self.assertEqual(1, result.video_count)
            self.assertEqual(
                root.resolve()
                / "exports"
                / "profiles"
                / f"profile-{profile_id}"
                / "transcripts.md",
                result.export_path,
            )
            markdown = result.export_path.read_text(encoding="utf-8")
            manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
            self.assertIn("# Reviewed Speaker Sermon Transcript Collection", markdown)
            self.assertIn("The profile sermon transcript.", markdown)
            self.assertNotIn("Host introduction", markdown)
            self.assertEqual(
                "effective_reviewed_profile_membership",
                manifest["selection_semantics"],
            )
            self.assertEqual(
                [observation_id], manifest["videos"][0]["profile_observation_ids"]
            )

    def test_cli_exports_profile_collection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, profile_id, _ = self._build_profile_sermon(root)

            result = CliRunner().invoke(
                app,
                [
                    "identity",
                    "export-profile",
                    "--profile-id",
                    str(profile_id),
                    "--base-dir",
                    str(root),
                ],
            )

            self.assertEqual(0, result.exit_code, result.output)
            self.assertIn("Included 1 sermon(s); skipped 0.", result.output)

    def test_redirected_profile_exports_the_canonical_collection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            database, profile_id, _ = self._build_profile_sermon(root)
            retired = database.ensure_speaker_profile(
                stable_key="retired-speaker-profile",
                display_label="Retired Speaker Profile",
                lifecycle_state="retired",
                created_reason="manual_review",
            )
            database.add_profile_redirect_event(
                from_profile_id=retired.id,
                to_profile_id=profile_id,
                action="redirect",
                reviewer="reviewer",
                reason="Confirmed duplicate profile",
                event_fingerprint="profile-export-redirect",
            )

            result = export_profile_transcript_collection(
                database,
                build_paths(root),
                retired.id,
            )
            manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))

            self.assertEqual(retired.id, result.requested_profile_id)
            self.assertEqual(profile_id, result.profile_id)
            self.assertEqual(retired.id, manifest["requested_profile_id"])
            self.assertEqual(profile_id, manifest["profile_id"])


if __name__ == "__main__":
    unittest.main()
