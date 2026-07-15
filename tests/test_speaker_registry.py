from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from pastor_transcript_extractor.config import build_paths, build_video_artifact_paths, ensure_directories
from pastor_transcript_extractor.identity_attribution import extract_grounded_attributions
from pastor_transcript_extractor.models import SourceType, VideoStatus
from pastor_transcript_extractor.speaker_registry import (
    create_profile,
    neutral_claim_payloads,
    persist_neutral_speaker_evidence,
    project_target_attribution_outcomes,
    record_name_claim_review,
    record_observation_review,
    record_profile_redirect,
)
from pastor_transcript_extractor.storage import Database


class SpeakerRegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.paths = build_paths(Path(self.tempdir.name))
        ensure_directories(self.paths)
        self.database = Database(self.paths.database)
        self.database.initialize()
        self.pastor = self.database.add_pastor("akorp", "Andrew Korp")
        self.source = self.database.add_source(
            "https://www.youtube.com/@samplechurch",
            SourceType.CHANNEL,
            pastor_id=self.pastor.id,
        )
        self.video = self.database.add_video(
            source_id=self.source.id,
            pastor_id=self.pastor.id,
            youtube_video_id="abc123def45",
            title="Pastor Andrew Korp - Grace",
            url="https://www.youtube.com/watch?v=abc123def45",
            channel_name="Sample Church",
            published_at="2026-07-01T14:00:00+00:00",
            duration_seconds=2400,
            status=VideoStatus.EXTRACTED,
        )
        video_paths = build_video_artifact_paths(
            self.paths, self.pastor.slug, self.video.youtube_video_id
        )
        video_paths.extracted.mkdir(parents=True, exist_ok=True)
        self.proposed_payload = {
            "sermon_window": {"start_seconds": 120.0, "end_seconds": 1800.0},
            "segments": [],
            "final_disposition": {"status": "accepted_sermon"},
        }
        proposed_path = video_paths.extracted / "proposed.json"
        proposed_path.write_text(json.dumps(self.proposed_payload), encoding="utf-8")
        self.extraction = self.database.add_extraction_result(
            video_id=self.video.id,
            version=1,
            proposed_text_path=str(video_paths.extracted / "proposed.md"),
            proposed_json_path=str(proposed_path),
        )

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _attribution(self, title: str = "Pastor Andrew Korp - Grace"):
        return extract_grounded_attributions(
            metadata_payload={
                "source_kind": "database_backfill",
                "video": {"title": title},
                "raw_metadata": {},
            },
            proposed_payload=self.proposed_payload,
            target_name=self.pastor.display_name,
            metadata_artifact_id=7,
            metadata_content_sha256="abc123",
        )

    def _persist(self, title: str = "Pastor Andrew Korp - Grace", *, payload=None):
        proposed_payload = payload or self.proposed_payload
        attribution = extract_grounded_attributions(
            metadata_payload={
                "source_kind": "database_backfill",
                "video": {"title": title},
                "raw_metadata": {},
            },
            proposed_payload=proposed_payload,
            target_name=self.pastor.display_name,
            metadata_artifact_id=7,
            metadata_content_sha256="abc123",
        )
        return persist_neutral_speaker_evidence(
            self.database,
            self.paths,
            video=self.video,
            pastor=self.pastor,
            extraction_result=self.extraction,
            proposed_payload=proposed_payload,
            attribution=attribution,
        )

    def test_neutral_claim_projection_reproduces_target_outcomes(self) -> None:
        attribution = self._attribution('"Integrity" By Elder Robert McLean')
        result = self._persist('"Integrity" By Elder Robert McLean')

        self.assertEqual(attribution.outcomes, result.compatibility_outcomes)
        self.assertEqual(
            attribution.outcomes,
            project_target_attribution_outcomes(result.claims, target_name="Andrew Korp"),
        )

    def test_projection_matches_source_extractor_for_conflict_spoken_and_empty_cases(self) -> None:
        cases = (
            (
                "Pastor Andrew Korp - Grace",
                [(100.0, 110.0, "Our speaker today is Elder Robert McLean.")],
            ),
            ("Worship Service", [(100.0, 110.0, "Our speaker today is Pastor Andrew Korp.")]),
            ("Worship Service", []),
        )
        for title, segments in cases:
            with self.subTest(title=title, segments=segments):
                payload = {
                    **self.proposed_payload,
                    "segments": [
                        {"start_seconds": start, "end_seconds": end, "text": text}
                        for start, end, text in segments
                    ],
                }
                attribution = extract_grounded_attributions(
                    metadata_payload={
                        "source_kind": "database_backfill",
                        "video": {"title": title},
                        "raw_metadata": {},
                    },
                    proposed_payload=payload,
                    target_name="Andrew Korp",
                    metadata_artifact_id=7,
                    metadata_content_sha256="abc123",
                )
                self.assertEqual(
                    attribution.outcomes,
                    project_target_attribution_outcomes(
                        neutral_claim_payloads(attribution), target_name="Andrew Korp"
                    ),
                )

    def test_persistence_creates_unprofiled_identity_but_no_membership(self) -> None:
        result = self._persist()
        repeated = self._persist()

        self.assertEqual("unprofiled", result.configured_profile.lifecycle_state)
        self.assertEqual(result.configured_profile.id, repeated.configured_profile.id)
        self.assertIsNotNone(result.observation)
        self.assertEqual(result.observation.id, repeated.observation.id)
        self.assertEqual("unknown", result.observation.multiplicity_state)
        self.assertEqual(result.artifact_path, repeated.artifact_path)
        self.assertEqual(result.artifact_path.read_bytes(), repeated.artifact_path.read_bytes())
        provenance = json.loads(result.claims[0].provenance_json)
        self.assertEqual("video.title", provenance["field_path"])
        self.assertEqual("Pastor Andrew Korp - Grace", provenance["exact_excerpt"])
        self.assertFalse(
            self.database.is_observation_attached(
                result.configured_profile.id, result.observation.id
            )
        )
        with self.database.connect() as connection:
            self.assertEqual(
                0, connection.execute("SELECT COUNT(*) FROM profile_name_claim_events").fetchone()[0]
            )

    def test_no_window_does_not_invent_a_voice_observation(self) -> None:
        payload = {"sermon_window": {"start_seconds": None, "end_seconds": None}, "segments": []}
        result = self._persist(payload=payload)

        self.assertIsNone(result.observation)
        self.assertEqual(1, len(result.claims))
        self.assertIsNone(result.claims[0].observation_id)

    def test_reviewed_observation_attachment_and_detachment_are_replayable(self) -> None:
        result = self._persist()
        profile = create_profile(
            self.database,
            display_label=None,
            stable_key="speaker:anonymous-1",
            created_reason="manual_review",
        )
        observation_id = result.observation.id
        first = record_observation_review(
            self.database,
            profile_id=profile.id,
            observation_id=observation_id,
            attach=True,
            reviewer="reviewer",
            reason="Same principal speaker",
            review_event_key="review-1",
        )
        replay = record_observation_review(
            self.database,
            profile_id=profile.id,
            observation_id=observation_id,
            attach=True,
            reviewer="reviewer",
            reason="Same principal speaker",
            review_event_key="review-1",
        )

        self.assertEqual(first, replay)
        self.assertTrue(self.database.is_observation_attached(profile.id, observation_id))
        record_observation_review(
            self.database,
            profile_id=profile.id,
            observation_id=observation_id,
            attach=False,
            reviewer="reviewer",
            reason="Review corrected",
            review_event_key="review-2",
        )
        self.assertFalse(self.database.is_observation_attached(profile.id, observation_id))

    def test_name_claim_attach_and_reject_require_review_events(self) -> None:
        result = self._persist()
        claim = result.claims[0]
        attach_event = record_name_claim_review(
            self.database,
            claim_id=claim.id,
            profile_id=result.configured_profile.id,
            attach=True,
            reviewer="reviewer",
            reason="Verified against service recording",
            review_event_key="name-review-1",
        )
        replay = record_name_claim_review(
            self.database,
            claim_id=claim.id,
            profile_id=result.configured_profile.id,
            attach=True,
            reviewer="reviewer",
            reason="Verified against service recording",
            review_event_key="name-review-1",
        )
        reject_event = record_name_claim_review(
            self.database,
            claim_id=claim.id,
            profile_id=None,
            attach=False,
            reviewer="reviewer",
            reason="Attribution was incorrect",
            review_event_key="name-review-2",
        )

        self.assertEqual(attach_event, replay)
        self.assertNotEqual(attach_event, reject_event)

    def test_profile_redirect_is_reversible_and_cycle_safe(self) -> None:
        first = create_profile(
            self.database,
            display_label=None,
            stable_key="speaker:first",
            created_reason="manual_review",
        )
        second = create_profile(
            self.database,
            display_label=None,
            stable_key="speaker:second",
            created_reason="manual_review",
        )
        record_profile_redirect(
            self.database,
            from_profile_id=first.id,
            to_profile_id=second.id,
            reviewer="reviewer",
            reason="Reviewed duplicate profiles",
            review_event_key="merge-1",
        )
        self.assertEqual(second.id, self.database.get_effective_profile_redirect(first.id))
        with self.assertRaises(ValueError):
            record_profile_redirect(
                self.database,
                from_profile_id=second.id,
                to_profile_id=first.id,
                reviewer="reviewer",
                reason="Would create cycle",
                review_event_key="merge-2",
            )
        record_profile_redirect(
            self.database,
            from_profile_id=first.id,
            to_profile_id=None,
            reviewer="reviewer",
            reason="Merge reversed",
            review_event_key="merge-3",
        )
        self.assertIsNone(self.database.get_effective_profile_redirect(first.id))

    def test_deleting_video_removes_occurrences_but_preserves_curated_profile(self) -> None:
        result = self._persist()
        record_observation_review(
            self.database,
            profile_id=result.configured_profile.id,
            observation_id=result.observation.id,
            attach=True,
            reviewer="reviewer",
            reason="Reviewed attachment",
            review_event_key="delete-fixture-observation",
        )
        record_name_claim_review(
            self.database,
            claim_id=result.claims[0].id,
            profile_id=result.configured_profile.id,
            attach=True,
            reviewer="reviewer",
            reason="Reviewed name",
            review_event_key="delete-fixture-name",
        )

        self.database.delete_video(self.video.id)

        counts = self.database.counts_by_table()
        self.assertEqual(1, counts["speaker_profiles"])
        self.assertEqual(0, counts["speaker_observations"])
        self.assertEqual(0, counts["speaker_name_claims"])
        with self.database.connect() as connection:
            self.assertEqual(
                0, connection.execute("SELECT COUNT(*) FROM profile_observation_events").fetchone()[0]
            )
            self.assertEqual(
                0, connection.execute("SELECT COUNT(*) FROM profile_name_claim_events").fetchone()[0]
            )


if __name__ == "__main__":
    unittest.main()
