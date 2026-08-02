from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from pastor_transcript_extractor.config import build_paths, ensure_directories
from pastor_transcript_extractor.models import SourceType, VideoStatus
from pastor_transcript_extractor.reviewed_speaker_evidence import (
    ObservationQualification,
    ReviewProvenance,
    ReviewedSpeakerEvidence,
)
from pastor_transcript_extractor.speaker_profile_automation import (
    _plan_pending_discovery_promotions,
    apply_profile_automatic_actions,
    plan_profile_automatic_actions,
)
from pastor_transcript_extractor.speaker_profile_promotion import (
    DiscoveryPromotionPlan,
    PromotionCandidate,
)
from pastor_transcript_extractor.storage import Database


class SpeakerProfileAutomationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.paths = build_paths(Path(self.tempdir.name))
        ensure_directories(self.paths)
        self.database = Database(self.paths.database)
        self.database.initialize()

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_plan_and_apply_pending_reviewed_evidence(self) -> None:
        source = self.database.add_source(
            "https://www.youtube.com/@one",
            SourceType.CHANNEL,
            pastor_id=None,
        )
        video = self.database.add_video(
            source_id=source.id,
            pastor_id=None,
            youtube_video_id="video-a",
            title="Video A",
            url="https://www.youtube.com/watch?v=video-a",
            status=VideoStatus.EXTRACTED,
        )
        extraction = self.database.add_extraction_result(
            video_id=video.id,
            version=1,
            proposed_text_path="a.md",
            proposed_json_path="a.json",
        )
        observation = self.database.add_speaker_observation(
            video_id=video.id,
            extraction_result_id=extraction.id,
            role="principal_speaker_candidate",
            multiplicity_state="unknown",
            start_seconds=100.0,
            end_seconds=1000.0,
            artifact_path="a.speaker.json",
            content_sha256="content-a",
            extractor_version="speaker_evidence_v1",
            input_fingerprint="fingerprint-a",
        )
        provenance = (ReviewProvenance("event", "pair", "reviewer"),)
        evidence = ReviewedSpeakerEvidence(
            qualifications={
                observation.input_fingerprint: ObservationQualification(
                    "qualified_single_speaker",
                    provenance,
                )
            },
            qualification_conflicts={},
            pair_relations={},
            pair_conflicts={},
            review_event_count=1,
        )

        plan = plan_profile_automatic_actions(
            Database(self.paths.database, readonly=True),
            evidence,
            association_report_paths=(),
            discovery_report_path=None,
        )

        self.assertEqual(plan.pending_sync_count, 1)
        self.assertEqual(len(plan.confirmation_plan.candidates), 0)
        self.assertIsNone(plan.promotion_plan)

        result = apply_profile_automatic_actions(
            self.database,
            evidence,
            association_report_paths=(),
            discovery_report_path=None,
        )

        self.assertEqual(result.sync_result.qualification_events_added, 1)
        self.assertEqual(result.confirmation_event_ids, ())
        self.assertEqual(result.promoted_profile_ids, ())
        self.assertEqual(
            self.database.get_effective_observation_review_action(observation.id),
            "qualified_single_speaker",
        )

    def test_completed_promotions_are_not_reported_as_pending(self) -> None:
        candidate = PromotionCandidate(
            component_id="component",
            observation_ids=(1, 2, 3),
            observation_fingerprints=("a", "b", "c"),
            recording_ids=(1, 2, 3),
            normalized_names=(),
            existing_profile_id=7,
        )
        source_plan = DiscoveryPromotionPlan(
            report_path=Path("discovery.json"),
            report_result_sha256="a" * 64,
            candidates=(candidate,),
            skipped=(),
        )
        database = MagicMock()
        database.get_speaker_profile_discovery_promotion.return_value = {
            "component_id": "component"
        }
        database.resolve_speaker_profile_id.side_effect = lambda value: value
        database.list_effective_profile_ids_for_observation.return_value = [7]

        with patch(
            "pastor_transcript_extractor.speaker_profile_automation."
            "plan_discovery_promotions",
            return_value=source_plan,
        ):
            plan = _plan_pending_discovery_promotions(
                database,
                Path("discovery.json"),
            )

        self.assertEqual(plan.candidates, ())


if __name__ == "__main__":
    unittest.main()
