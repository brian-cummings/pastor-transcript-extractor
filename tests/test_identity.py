from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from pastor_transcript_extractor.config import build_paths, build_video_artifact_paths, ensure_directories
from pastor_transcript_extractor.identity import (
    backfill_shadow_identity_assessments,
    coordinate_decision,
    persist_metadata_snapshot,
    record_shadow_identity_assessment,
)
from pastor_transcript_extractor.models import IdentityState, SourceType, VideoStatus
from pastor_transcript_extractor.storage import Database


class IdentityCoordinatorTests(unittest.TestCase):
    def test_shadow_mode_preserves_content_status_while_proposing_identity_review(self) -> None:
        result = coordinate_decision(
            {"status": "accepted_sermon"},
            IdentityState.PROFILE_UNAVAILABLE,
            shadow_mode=True,
        )

        self.assertEqual("review_required", result["proposed_status"])
        self.assertEqual("accepted_sermon", result["effective_status"])
        self.assertTrue(result["shadow_mode"])

    def test_confirmed_target_and_non_target_produce_distinct_proposals(self) -> None:
        target = coordinate_decision(
            {"status": "accepted_sermon"},
            IdentityState.TARGET_CONFIRMED,
            shadow_mode=False,
        )
        guest = coordinate_decision(
            {"status": "accepted_sermon"},
            IdentityState.NON_TARGET_CONFIRMED,
            shadow_mode=False,
        )

        self.assertEqual("accepted_target_sermon", target["effective_status"])
        self.assertEqual("rejected_non_target", guest["effective_status"])

    def test_content_rejection_remains_terminal_without_identity_proof(self) -> None:
        result = coordinate_decision(
            {"status": "rejected_no_sermon"},
            IdentityState.PROFILE_UNAVAILABLE,
            shadow_mode=False,
        )

        self.assertEqual("rejected_no_sermon", result["effective_status"])


class IdentityPersistenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.paths = build_paths(Path(self.tempdir.name))
        ensure_directories(self.paths)
        self.database = Database(self.paths.database)
        self.database.initialize()
        self.pastor = self.database.add_pastor("sample-pastor", "Andrew Korp")
        self.source = self.database.add_source(
            "https://www.youtube.com/@samplechurch",
            SourceType.CHANNEL,
            pastor_id=self.pastor.id,
        )
        self.video = self.database.add_video(
            source_id=self.source.id,
            pastor_id=self.pastor.id,
            youtube_video_id="abc123def45",
            title="A Sample Sermon",
            url="https://www.youtube.com/watch?v=abc123def45",
            channel_name="Sample Church",
            published_at="2026-07-01T14:00:00+00:00",
            duration_seconds=2400,
            status=VideoStatus.EXTRACTED,
        )
        video_paths = build_video_artifact_paths(self.paths, self.pastor.slug, self.video.youtube_video_id)
        video_paths.extracted.mkdir(parents=True, exist_ok=True)
        self.proposed_text_path = video_paths.extracted / "proposed.md"
        self.proposed_json_path = video_paths.extracted / "proposed.json"
        self.proposed_text_path.write_text("stable content\n", encoding="utf-8")
        self.proposed_json_path.write_text(
            json.dumps({"final_disposition": {"status": "accepted_sermon"}}, sort_keys=True),
            encoding="utf-8",
        )
        self.extraction = self.database.add_extraction_result(
            video_id=self.video.id,
            version=1,
            proposed_text_path=str(self.proposed_text_path),
            proposed_json_path=str(self.proposed_json_path),
        )

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_metadata_snapshots_are_immutable_and_content_addressed(self) -> None:
        first = persist_metadata_snapshot(
            self.database,
            self.paths,
            video=self.video,
            pastor=self.pastor,
            source_kind="yt_dlp_flat_playlist",
            raw_metadata={"description": "Pastor Sample brings the message."},
        )
        repeated = persist_metadata_snapshot(
            self.database,
            self.paths,
            video=self.video,
            pastor=self.pastor,
            source_kind="yt_dlp_flat_playlist",
            raw_metadata={"description": "Pastor Sample brings the message."},
        )
        changed = persist_metadata_snapshot(
            self.database,
            self.paths,
            video=self.video,
            pastor=self.pastor,
            source_kind="yt_dlp_flat_playlist",
            raw_metadata={"description": "Guest speaker brings the message."},
        )

        self.assertEqual(first.id, repeated.id)
        self.assertNotEqual(first.id, changed.id)
        self.assertNotEqual(first.artifact_path, changed.artifact_path)
        self.assertTrue(Path(first.artifact_path).exists())
        self.assertTrue(Path(changed.artifact_path).exists())
        self.assertEqual(2, self.database.counts_by_table()["metadata_artifacts"])

    def test_shadow_assessment_is_idempotent_and_does_not_modify_content_artifacts(self) -> None:
        original_text = self.proposed_text_path.read_bytes()
        original_json = self.proposed_json_path.read_bytes()
        disposition = {"status": "accepted_sermon", "reason_codes": ["fixture"]}

        first = record_shadow_identity_assessment(
            self.database,
            self.paths,
            video=self.video,
            pastor=self.pastor,
            extraction_result=self.extraction,
            content_disposition=disposition,
        )
        repeated = record_shadow_identity_assessment(
            self.database,
            self.paths,
            video=self.video,
            pastor=self.pastor,
            extraction_result=self.extraction,
            content_disposition=disposition,
        )

        self.assertEqual(first.assessment.id, repeated.assessment.id)
        self.assertEqual(IdentityState.PROFILE_UNAVAILABLE, first.assessment.state)
        self.assertTrue(first.assessment.shadow_mode)
        self.assertEqual(original_text, self.proposed_text_path.read_bytes())
        self.assertEqual(original_json, self.proposed_json_path.read_bytes())
        self.assertTrue(first.evidence_ledger_path.exists())
        self.assertTrue(first.assessment_path.exists())
        assessment_payload = json.loads(first.assessment_path.read_text(encoding="utf-8"))
        self.assertEqual(["no_attribution_evidence"], assessment_payload["attribution_outcomes"])
        self.assertEqual("review_required", assessment_payload["coordination"]["proposed_status"])
        self.assertEqual("accepted_sermon", assessment_payload["coordination"]["effective_status"])
        counts = self.database.counts_by_table()
        self.assertEqual(2, counts["identity_evidence"])
        self.assertEqual(1, counts["identity_assessments"])

    def test_grounded_target_credit_is_persisted_without_promoting_identity_state(self) -> None:
        persist_metadata_snapshot(
            self.database,
            self.paths,
            video=self.video,
            pastor=self.pastor,
            source_kind="yt_dlp_flat_playlist",
            raw_metadata={"description": "Today's sermon is presented by Andrew Korp."},
        )

        result = record_shadow_identity_assessment(
            self.database,
            self.paths,
            video=self.video,
            pastor=self.pastor,
            extraction_result=self.extraction,
            content_disposition={"status": "accepted_sermon"},
        )

        payload = json.loads(result.assessment_path.read_text(encoding="utf-8"))
        self.assertIn("metadata_target_match", payload["attribution_outcomes"])
        self.assertIn("explicit_target_attribution", payload["attribution_outcomes"])
        self.assertEqual("profile_unavailable", payload["state"])
        self.assertEqual("review", payload["recommended_action"])
        self.assertEqual("accepted_sermon", payload["coordination"]["effective_status"])
        evidence = self.database.list_identity_evidence_for_video(self.video.id)
        outcomes = {item.evidence_type: item for item in evidence}
        self.assertEqual("supports_target", outcomes["metadata_target_match"].polarity)
        self.assertEqual("supports_target", outcomes["explicit_target_attribution"].polarity)
        self.assertEqual("explicit", outcomes["explicit_target_attribution"].strength)

    def test_deleting_video_removes_identity_records(self) -> None:
        record_shadow_identity_assessment(
            self.database,
            self.paths,
            video=self.video,
            pastor=self.pastor,
            extraction_result=self.extraction,
            content_disposition={"status": "accepted_sermon"},
        )

        self.database.delete_video(self.video.id)

        counts = self.database.counts_by_table()
        self.assertEqual(0, counts["metadata_artifacts"])
        self.assertEqual(0, counts["identity_evidence"])
        self.assertEqual(0, counts["identity_assessments"])

    def test_backfill_uses_existing_disposition_and_reuses_unchanged_assessment(self) -> None:
        first = backfill_shadow_identity_assessments(self.database, self.paths)
        repeated = backfill_shadow_identity_assessments(self.database, self.paths)

        self.assertEqual(1, first.created)
        self.assertEqual(0, first.reused)
        self.assertEqual(0, repeated.created)
        self.assertEqual(1, repeated.reused)
        self.assertEqual(1, self.database.counts_by_table()["identity_assessments"])


if __name__ == "__main__":
    unittest.main()
