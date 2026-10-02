from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from pastor_transcript_extractor.models import SourceType, VideoStatus
from pastor_transcript_extractor.sermon_topic_projection import (
    TOPIC_PROFILE_PROJECTION_ACTIVATION_REQUIREMENT,
    assess_topic_profile_projection,
)
from pastor_transcript_extractor.speaker_registry import (
    attach_reviewed_observation,
    create_anonymous_profile,
    record_observation_review,
)
from pastor_transcript_extractor.storage import Database


class SermonTopicProjectionGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.base_dir = Path(self.tempdir.name)
        self.database = Database(self.base_dir / "app.db")
        self.database.initialize()
        pastor = self.database.add_pastor("sample", "Sample")
        source = self.database.add_source(
            "https://www.youtube.com/@sample",
            SourceType.CHANNEL,
            pastor_id=pastor.id,
        )
        self.video = self.database.add_video(
            source_id=source.id,
            pastor_id=None,
            youtube_video_id="topic-gate",
            title="Topic gate sermon",
            url="https://www.youtube.com/watch?v=topic-gate",
            status=VideoStatus.EXTRACTED,
        )
        self.proposed_path = self.base_dir / "proposed.json"
        self.payload = {
            "final_disposition": {"status": "accepted_sermon"},
            "sermon_window": {
                "start_seconds": 120.0,
                "end_seconds": 1800.0,
                "included_segment_indexes": [0],
            },
            "segments": [
                {
                    "start_seconds": 120.0,
                    "end_seconds": 180.0,
                    "text": "Sermon text.",
                }
            ],
            "classification": {
                "final_disposition": {"status": "accepted_sermon"},
                "search": {
                    "topic_analysis": {
                        "question_pack_version": (
                            "topics-v2-performed-worship-boundary"
                        ),
                        "blocks": [],
                        "sermon_projection": {
                            "policy_version": (
                                "sermon-topic-full-block-role-density-v1"
                            ),
                            "final_disposition_status": "accepted_sermon",
                            "eligible_block_count": 1,
                        },
                    }
                },
            },
        }
        self._write_payload()
        self.extraction = self.database.add_extraction_result(
            video_id=self.video.id,
            version=1,
            proposed_text_path=str(self.proposed_path.with_suffix(".md")),
            proposed_json_path=str(self.proposed_path),
        )
        self.observation = self._add_observation("observation-v1")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _write_payload(self) -> None:
        self.proposed_path.write_text(
            json.dumps(self.payload, sort_keys=True),
            encoding="utf-8",
        )

    def _add_observation(self, fingerprint: str):
        return self.database.add_speaker_observation(
            video_id=self.video.id,
            extraction_result_id=self.extraction.id,
            role="principal_speaker_candidate",
            multiplicity_state="single",
            start_seconds=120.0,
            end_seconds=1800.0,
            artifact_path=str(self.proposed_path),
            content_sha256=f"content-{fingerprint}",
            extractor_version="test",
            input_fingerprint=fingerprint,
        )

    def _attach_reviewed(self):
        profile = create_anonymous_profile(
            self.database,
            reviewer="reviewer",
            reason="Reviewed principal speaker",
            review_event_key="topic-profile",
        )
        attach_reviewed_observation(
            self.database,
            profile_id=profile.id,
            observation_id=self.observation.id,
            reviewer="reviewer",
            reason="Reviewed same speaker",
            review_event_key="topic-membership",
        )
        return profile

    def test_accepted_sermon_with_reviewed_membership_is_eligible_and_stable(self) -> None:
        profile = self._attach_reviewed()

        first = assess_topic_profile_projection(self.database, self.video)
        replay = assess_topic_profile_projection(self.database, self.video)

        self.assertTrue(first.eligible)
        self.assertEqual((), first.reason_codes)
        self.assertEqual(profile.id, first.profile_id)
        self.assertEqual((profile.id,), first.direct_profile_ids)
        self.assertEqual(TOPIC_PROFILE_PROJECTION_ACTIVATION_REQUIREMENT, first.activation_requirement)
        self.assertEqual(first.input_fingerprint, replay.input_fingerprint)

    def test_reviewed_membership_is_inherited_by_reclassified_observation(self) -> None:
        profile = self._attach_reviewed()
        replacement = self._add_observation("observation-v2")

        gate = assess_topic_profile_projection(self.database, self.video)

        self.assertTrue(gate.eligible)
        self.assertEqual(replacement.id, gate.observation_id)
        self.assertEqual((), gate.direct_profile_ids)
        self.assertEqual((profile.id,), gate.inherited_profile_ids)

    def test_nonaccepted_sermon_is_blocked_without_discarding_membership(self) -> None:
        profile = self._attach_reviewed()
        self.payload["final_disposition"] = {"status": "review_required"}
        self.payload["classification"]["final_disposition"] = {
            "status": "review_required"
        }
        self.payload["classification"]["search"]["topic_analysis"][
            "sermon_projection"
        ]["final_disposition_status"] = "review_required"
        self._write_payload()

        gate = assess_topic_profile_projection(self.database, self.video)

        self.assertFalse(gate.eligible)
        self.assertIn("disposition_not_accepted", gate.reason_codes)
        self.assertEqual((profile.id,), gate.direct_profile_ids)

    def test_stale_sermon_projection_disposition_is_blocked(self) -> None:
        self._attach_reviewed()
        self.payload["classification"]["search"]["topic_analysis"][
            "sermon_projection"
        ]["final_disposition_status"] = "review_required"
        self._write_payload()

        gate = assess_topic_profile_projection(self.database, self.video)

        self.assertFalse(gate.eligible)
        self.assertIn("sermon_projection_disposition_stale", gate.reason_codes)

    def test_missing_or_detached_membership_is_blocked(self) -> None:
        missing = assess_topic_profile_projection(self.database, self.video)
        self.assertFalse(missing.eligible)
        self.assertIn(
            "effective_profile_membership_unavailable",
            missing.reason_codes,
        )

        profile = self._attach_reviewed()
        record_observation_review(
            self.database,
            profile_id=profile.id,
            observation_id=self.observation.id,
            attach=False,
            reviewer="reviewer",
            reason="Correct reviewed membership",
            review_event_key="topic-membership-detach",
        )
        detached = assess_topic_profile_projection(self.database, self.video)
        self.assertFalse(detached.eligible)
        self.assertIn(
            "effective_profile_membership_unavailable",
            detached.reason_codes,
        )

    def test_ambiguous_effective_membership_is_blocked(self) -> None:
        first = self._attach_reviewed()
        second = create_anonymous_profile(
            self.database,
            reviewer="reviewer",
            reason="Second reviewed profile",
            review_event_key="topic-profile-2",
        )
        self.database.add_profile_observation_event(
            profile_id=second.id,
            observation_id=self.observation.id,
            action="attach",
            reviewer="reviewer",
            reason="Conflicting reviewed attachment",
            event_fingerprint="conflicting-topic-membership",
        )

        gate = assess_topic_profile_projection(self.database, self.video)

        self.assertFalse(gate.eligible)
        self.assertEqual((first.id, second.id), gate.effective_profile_ids)
        self.assertIn("ambiguous_effective_profile_membership", gate.reason_codes)

    def test_membership_without_review_provenance_is_blocked(self) -> None:
        profile = self.database.ensure_speaker_profile(
            stable_key="unreviewed-membership",
            display_label=None,
            lifecycle_state="active",
            created_reason="test",
        )
        self.database.add_profile_observation_event(
            profile_id=profile.id,
            observation_id=self.observation.id,
            action="attach",
            reviewer="",
            reason="",
            event_fingerprint="unreviewed-topic-membership",
        )

        gate = assess_topic_profile_projection(self.database, self.video)

        self.assertFalse(gate.eligible)
        self.assertIn("membership_review_provenance_missing", gate.reason_codes)

    def test_unprofiled_membership_is_not_an_analysis_profile(self) -> None:
        profile = self.database.ensure_speaker_profile(
            stable_key="configured-unprofiled",
            display_label="Configured Person",
            lifecycle_state="unprofiled",
            created_reason="configured_requested_identity",
        )
        self.database.add_profile_observation_event(
            profile_id=profile.id,
            observation_id=self.observation.id,
            action="attach",
            reviewer="reviewer",
            reason="Reviewed membership",
            event_fingerprint="unprofiled-topic-membership",
        )

        gate = assess_topic_profile_projection(self.database, self.video)

        self.assertFalse(gate.eligible)
        self.assertIn("profile_lifecycle_ineligible", gate.reason_codes)

    def test_topic_projection_evidence_is_required(self) -> None:
        self._attach_reviewed()
        topic_analysis = self.payload["classification"]["search"]["topic_analysis"]
        topic_analysis["sermon_projection"]["eligible_block_count"] = 0
        self._write_payload()

        gate = assess_topic_profile_projection(self.database, self.video)

        self.assertFalse(gate.eligible)
        self.assertIn(
            "sermon_projection_has_no_eligible_evidence",
            gate.reason_codes,
        )


if __name__ == "__main__":
    unittest.main()
