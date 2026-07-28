from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from pastor_transcript_extractor.config import build_paths, ensure_directories
from pastor_transcript_extractor.models import SourceType, VideoStatus
from pastor_transcript_extractor.reviewed_speaker_evidence import (
    load_reviewed_speaker_evidence,
    observation_review_queue_priority,
    sync_reviewed_speaker_evidence,
)
from pastor_transcript_extractor.speaker_registry import (
    record_observation_disposition,
)
from pastor_transcript_extractor.storage import Database


class ReviewedSpeakerEvidenceTests(unittest.TestCase):
    def test_review_queue_reuses_qualification_and_skips_resolved_work(self) -> None:
        self.assertEqual(
            1,
            observation_review_queue_priority(
                qualification_action="qualified_single_speaker",
                grouping_action=None,
                attached_profile_ids=(),
                qualification_conflict=False,
                explicitly_targeted=False,
            ),
        )
        for qualification, grouping, profiles in (
            ("qualified_single_speaker", None, (7,)),
            ("qualified_single_speaker", "defer", ()),
            ("multiple_speakers", None, ()),
            ("invalid", None, ()),
            ("unresolved", None, ()),
        ):
            with self.subTest(
                qualification=qualification,
                grouping=grouping,
                profiles=profiles,
            ):
                self.assertIsNone(
                    observation_review_queue_priority(
                        qualification_action=qualification,
                        grouping_action=grouping,
                        attached_profile_ids=profiles,
                        qualification_conflict=False,
                        explicitly_targeted=False,
                    )
                )
        self.assertEqual(
            2,
            observation_review_queue_priority(
                qualification_action=None,
                grouping_action=None,
                attached_profile_ids=(),
                qualification_conflict=False,
                explicitly_targeted=False,
            ),
        )
        self.assertEqual(
            0,
            observation_review_queue_priority(
                qualification_action="invalid",
                grouping_action=None,
                attached_profile_ids=(),
                qualification_conflict=False,
                explicitly_targeted=True,
            ),
        )

    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.paths = build_paths(self.root / "app")
        ensure_directories(self.paths)
        self.database = Database(self.paths.database)
        self.database.initialize()
        self.source = self.database.add_source(
            "https://www.youtube.com/@reviewed",
            SourceType.CHANNEL,
            pastor_id=None,
        )
        self.observations = {
            fingerprint: self._add_observation(index, fingerprint)
            for index, fingerprint in enumerate(("a", "b", "c", "d"), start=1)
        }
        self.evaluation_root = self.root / "speaker-pairs"
        (self.evaluation_root / "fixtures").mkdir(parents=True)
        (self.evaluation_root / "drafts").mkdir(parents=True)
        (self.evaluation_root / "reviews").mkdir(parents=True)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _add_observation(self, index: int, fingerprint: str):
        video = self.database.add_video(
            source_id=self.source.id,
            pastor_id=None,
            youtube_video_id=f"video-{fingerprint}",
            title=f"Video {fingerprint}",
            url=f"https://www.youtube.com/watch?v=video-{fingerprint}",
            status=VideoStatus.EXTRACTED,
        )
        extraction = self.database.add_extraction_result(
            video_id=video.id,
            version=1,
            proposed_text_path=f"{fingerprint}.md",
            proposed_json_path=f"{fingerprint}.json",
        )
        return self.database.add_speaker_observation(
            video_id=video.id,
            extraction_result_id=extraction.id,
            role="principal_speaker_candidate",
            multiplicity_state="unknown",
            start_seconds=100.0,
            end_seconds=1000.0,
            artifact_path=f"{fingerprint}.speaker.json",
            content_sha256=f"content-{fingerprint}",
            extractor_version="speaker_evidence_v1",
            input_fingerprint=fingerprint,
        )

    def _write_fixture(
        self,
        pair_id: str,
        fingerprint_a: str,
        fingerprint_b: str,
        outcome: str,
    ) -> None:
        payload = {
            "schema_version": 1,
            "review_status": "approved",
            "pair_id": pair_id,
            "review_event_id": f"event-{pair_id}",
            "reviewer": "Reviewer One",
            "expected_outcome": outcome,
            "qualification": {
                "A": "qualified_single_speaker",
                "B": "qualified_single_speaker",
            },
            "observations": {
                "a": {"input_fingerprint": fingerprint_a},
                "b": {"input_fingerprint": fingerprint_b},
            },
        }
        (self.evaluation_root / "fixtures" / f"{pair_id}.json").write_text(
            json.dumps(payload),
            encoding="utf-8",
        )

    def _write_review(
        self,
        *,
        pair_id: str,
        event_id: str,
        fingerprint_a: str,
        fingerprint_b: str,
        qualification_a: str,
        qualification_b: str,
    ) -> None:
        draft = {
            "schema_version": 1,
            "review_status": "draft",
            "pair_id": pair_id,
            "draft_id": f"draft-{pair_id}",
            "observations": {
                "source_a": {"input_fingerprint": fingerprint_a},
                "source_b": {"input_fingerprint": fingerprint_b},
            },
            "presentation": {
                "A": {"source_key": "source_a"},
                "B": {"source_key": "source_b"},
            },
        }
        (self.evaluation_root / "drafts" / f"{pair_id}.json").write_text(
            json.dumps(draft),
            encoding="utf-8",
        )
        review_dir = self.evaluation_root / "reviews" / pair_id
        review_dir.mkdir(parents=True, exist_ok=True)
        review = {
            "schema_version": 1,
            "event_kind": "speaker_pair_human_review",
            "pair_id": pair_id,
            "draft_id": draft["draft_id"],
            "review_event_id": event_id,
            "reviewer": "Reviewer Two",
            "qualification": {
                "A": qualification_a,
                "B": qualification_b,
            },
            "pair_judgment": "cannot_determine",
            "approval_confirmed": False,
            "fixture_eligible": False,
        }
        (review_dir / f"{event_id}.json").write_text(
            json.dumps(review),
            encoding="utf-8",
        )

    def test_sync_materializes_reviewed_components_and_constraints_idempotently(self) -> None:
        self._write_fixture("pair-ab", "a", "b", "same_speaker")
        self._write_fixture("pair-bc", "b", "c", "same_speaker")
        self._write_fixture("pair-cd", "c", "d", "different_speaker")

        evidence = load_reviewed_speaker_evidence(self.evaluation_root)
        first = sync_reviewed_speaker_evidence(self.database, evidence)
        replay = sync_reviewed_speaker_evidence(self.database, evidence)

        profile_ids = {
            fingerprint: self.database.list_effective_profile_ids_for_observation(
                observation.id
            )
            for fingerprint, observation in self.observations.items()
        }
        self.assertEqual(1, len(profile_ids["a"]))
        self.assertEqual(profile_ids["a"], profile_ids["b"])
        self.assertEqual(profile_ids["b"], profile_ids["c"])
        self.assertEqual([], profile_ids["d"])
        self.assertEqual(1, first.profiles_added)
        self.assertEqual(3, first.membership_events_added)
        self.assertEqual(
            [
                (
                    self.observations["c"].id,
                    self.observations["d"].id,
                )
            ],
            self.database.list_effective_observation_difference_pairs(),
        )
        self.assertEqual(0, replay.profiles_added)
        self.assertEqual(0, replay.membership_events_added)
        self.assertEqual(0, replay.difference_events_added)
        self.assertEqual(0, replay.qualification_events_added)
        self.assertEqual((), replay.conflicts)

    def test_conflicting_qualifications_are_not_materialized(self) -> None:
        self._write_review(
            pair_id="pair-ab",
            event_id="event-single",
            fingerprint_a="a",
            fingerprint_b="b",
            qualification_a="qualified_single_speaker",
            qualification_b="qualified_single_speaker",
        )
        self._write_review(
            pair_id="pair-ac",
            event_id="event-multiple",
            fingerprint_a="a",
            fingerprint_b="c",
            qualification_a="multiple_speakers",
            qualification_b="qualified_single_speaker",
        )

        evidence = load_reviewed_speaker_evidence(self.evaluation_root)
        result = sync_reviewed_speaker_evidence(self.database, evidence)

        self.assertEqual(
            ("multiple_speakers", "qualified_single_speaker"),
            evidence.qualification_conflicts["a"],
        )
        self.assertIsNone(
            self.database.get_effective_observation_review_action(
                self.observations["a"].id
            )
        )
        self.assertTrue(
            any("qualification conflict for a" in value for value in result.conflicts)
        )

    def test_manual_qualification_override_blocks_component_materialization(self) -> None:
        self._write_fixture("pair-ab", "a", "b", "same_speaker")
        record_observation_disposition(
            self.database,
            observation_id=self.observations["a"].id,
            action="multiple_speakers",
            reviewer="Manual Reviewer",
            reason="Manual correction after pair review",
            review_event_key="manual-override-a",
        )

        evidence = load_reviewed_speaker_evidence(self.evaluation_root)
        result = sync_reviewed_speaker_evidence(self.database, evidence)

        self.assertEqual(
            "multiple_speakers",
            self.database.get_effective_observation_review_action(
                self.observations["a"].id
            ),
        )
        self.assertEqual([], self.database.list_speaker_profiles())
        self.assertTrue(
            any(
                "without effective single-speaker qualification" in value
                for value in result.conflicts
            )
        )

    def test_manual_adjudication_resolves_artifact_qualification_conflict(self) -> None:
        self._write_fixture("pair-ab", "a", "b", "same_speaker")
        self._write_review(
            pair_id="pair-ac",
            event_id="event-multiple",
            fingerprint_a="a",
            fingerprint_b="c",
            qualification_a="multiple_speakers",
            qualification_b="qualified_single_speaker",
        )
        record_observation_disposition(
            self.database,
            observation_id=self.observations["a"].id,
            action="qualified_single_speaker",
            reviewer="Adjudicator",
            reason="Resolved conflicting historical qualifications",
            review_event_key="adjudicate-a",
        )

        evidence = load_reviewed_speaker_evidence(self.evaluation_root)
        result = sync_reviewed_speaker_evidence(self.database, evidence)

        self.assertIn("a", evidence.qualification_conflicts)
        self.assertEqual(1, result.profiles_added)
        self.assertEqual(
            self.database.list_effective_profile_ids_for_observation(
                self.observations["a"].id
            ),
            self.database.list_effective_profile_ids_for_observation(
                self.observations["b"].id
            ),
        )
        self.assertFalse(
            any(
                "same component contains qualification conflict" in value
                for value in result.conflicts
            )
        )


if __name__ == "__main__":
    unittest.main()
