from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from pastor_transcript_extractor.config import build_paths, ensure_directories
from pastor_transcript_extractor.identity_leverage import (
    build_profile_leverage_snapshot,
    compare_profile_leverage_snapshots,
    profile_neighborhood_video_ids,
)
from pastor_transcript_extractor.models import SourceType, VideoStatus
from pastor_transcript_extractor.speaker_registry import (
    attach_reviewed_observation,
    create_anonymous_profile,
)
from pastor_transcript_extractor.storage import Database


class IdentityLeverageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        paths = build_paths(self.root / "app")
        ensure_directories(paths)
        self.database = Database(paths.database)
        self.database.initialize()
        self.source = self.database.add_source(
            "https://www.youtube.com/@test",
            SourceType.CHANNEL,
            pastor_id=None,
        )
        self.associations = self.root / "associations" / "run"
        self.associations.mkdir(parents=True)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _observation(self, key: str):
        video = self.database.add_video(
            source_id=self.source.id,
            pastor_id=None,
            youtube_video_id=f"video-{key}",
            title=key,
            url=f"https://www.youtube.com/watch?v=video-{key}",
            status=VideoStatus.EXTRACTED,
        )
        extraction = self.database.add_extraction_result(
            video_id=video.id,
            version=1,
            proposed_text_path=f"{key}.md",
            proposed_json_path=f"{key}.json",
        )
        return self.database.add_speaker_observation(
            video_id=video.id,
            extraction_result_id=extraction.id,
            role="principal_speaker_candidate",
            multiplicity_state="unknown",
            start_seconds=0.0,
            end_seconds=1200.0,
            artifact_path=f"{key}.speaker.json",
            content_sha256=f"content-{key}",
            extractor_version="speaker_evidence_v1",
            input_fingerprint=key,
        )

    def _report(
        self,
        observation,
        *,
        profile_id: int,
        outcome: str,
        proposed: int | None = None,
        exemplar_excluded: bool = False,
        automatic_profile_ready: bool | None = None,
        created_at: str = "2026-08-26T12:00:00+00:00",
        suffix: str = "",
    ) -> None:
        payload = {
            "artifact_kind": "speaker_profile_shadow_association",
            "created_at": created_at,
            "candidate": {
                "observation_id": observation.id,
                "video_id": observation.video_id,
            },
            "outcome": outcome,
            "proposed_profile_id": proposed,
            "profiles": [{
                "profile_id": profile_id,
                **({
                    "profile_readiness": {
                        "automatic_profile_ready": automatic_profile_ready,
                    }
                } if automatic_profile_ready is not None else {}),
            }],
            "routing": {
                "candidate_funnel": {
                    "retrieval_candidates": [{
                        "profile_id": profile_id,
                        "selected_for_comparison": True,
                        "source_match": True,
                    }],
                    "excluded_profiles": ([{
                        "profile_id": profile_id,
                        "stage": "acoustic_exemplar_availability",
                    }] if exemplar_excluded else []),
                }
            },
        }
        (self.associations / f"{observation.id}{suffix}.json").write_text(
            json.dumps(payload), encoding="utf-8"
        )

    def test_snapshot_records_bounded_profile_neighborhood(self) -> None:
        target = create_anonymous_profile(
            self.database,
            reviewer="human",
            reason="test",
            review_event_key="profile-target",
        )
        unrelated = create_anonymous_profile(
            self.database,
            reviewer="human",
            reason="test",
            review_event_key="profile-unrelated",
        )
        relevant_observation = self._observation("relevant")
        unrelated_observation = self._observation("unrelated")
        self._report(
            relevant_observation,
            profile_id=target.id,
            outcome="insufficient_evidence",
            exemplar_excluded=True,
        )
        self._report(
            unrelated_observation,
            profile_id=unrelated.id,
            outcome="proposed_match",
            proposed=unrelated.id,
        )

        snapshot = build_profile_leverage_snapshot(
            self.database,
            association_root=self.associations.parent,
            profile_ids=[target.id],
            decision_kind="exemplar_media_fix",
        )

        self.assertEqual(1, snapshot["state"]["neighborhood_observation_count"])
        self.assertEqual(
            [relevant_observation.id],
            snapshot["state"]["abstention_observation_ids"],
        )
        self.assertEqual(
            [relevant_observation.video_id],
            profile_neighborhood_video_ids(
                self.database,
                association_root=self.associations.parent,
                profile_ids=[target.id],
            ),
        )

    def test_comparison_reports_only_observed_yield(self) -> None:
        target = create_anonymous_profile(
            self.database,
            reviewer="human",
            reason="test",
            review_event_key="profile-target",
        )
        observation = self._observation("candidate")
        self._report(
            observation,
            profile_id=target.id,
            outcome="insufficient_evidence",
            exemplar_excluded=True,
        )
        before = build_profile_leverage_snapshot(
            self.database,
            association_root=self.associations.parent,
            profile_ids=[target.id],
            decision_kind="readiness_promotion",
        )
        attach_reviewed_observation(
            self.database,
            profile_id=target.id,
            observation_id=observation.id,
            reviewer="human",
            reason="confirmed",
            review_event_key="attach-candidate",
        )
        self._report(
            observation,
            profile_id=target.id,
            outcome="proposed_match",
            proposed=target.id,
        )
        after = build_profile_leverage_snapshot(
            self.database,
            association_root=self.associations.parent,
            profile_ids=[target.id],
            decision_kind="readiness_promotion",
            profile_level_decisions=1,
        )

        result = compare_profile_leverage_snapshots(before, after)

        self.assertEqual(1, result["observed"]["newly_resolved_sermon_count"])
        self.assertEqual(
            1.0,
            result["observed"][
                "sermons_resolved_per_profile_level_human_decision"
            ],
        )
        self.assertEqual(1, result["observed"]["abstentions_eliminated"])
        self.assertEqual(
            1,
            result["observed"][
                "unresolved_cases_repaired_through_exemplar_media_fixes"
            ],
        )
        self.assertIsNone(
            result["observed"]["prospective_confirmation_precision"]
        )
        self.assertFalse(result["interpretation"]["predicted_unlocks_used"])
        self.assertFalse(result["interpretation"]["membership_firewall_changed"])

    def test_prospective_precision_is_bounded_by_unresolved_baseline(self) -> None:
        target = create_anonymous_profile(
            self.database,
            reviewer="human",
            reason="test",
            review_event_key="profile-target",
        )
        observation = self._observation("candidate")
        self._report(
            observation,
            profile_id=target.id,
            outcome="proposed_match",
            proposed=target.id,
        )
        before = build_profile_leverage_snapshot(
            self.database,
            association_root=self.associations.parent,
            profile_ids=[target.id],
            decision_kind="prospective_confirmation",
        )
        attach_reviewed_observation(
            self.database,
            profile_id=target.id,
            observation_id=observation.id,
            reviewer="human",
            reason="confirmed",
            review_event_key="attach-candidate",
        )
        after = build_profile_leverage_snapshot(
            self.database,
            association_root=self.associations.parent,
            profile_ids=[target.id],
            decision_kind="prospective_confirmation",
            sermon_level_reviews=1,
            prospective_correct=1,
        )

        result = compare_profile_leverage_snapshots(before, after)

        self.assertEqual(
            1.0, result["observed"]["prospective_confirmation_precision"]
        )
        self.assertEqual(
            1.0, result["observed"]["sermons_resolved_per_sermon_level_review"]
        )

    def test_readiness_promotion_counts_existing_proposal_made_actionable(self) -> None:
        target = create_anonymous_profile(
            self.database,
            reviewer="human",
            reason="test",
            review_event_key="profile-target",
        )
        observation = self._observation("candidate")
        self._report(
            observation,
            profile_id=target.id,
            outcome="proposed_match",
            proposed=target.id,
            automatic_profile_ready=False,
            suffix="-blocked",
        )
        before = build_profile_leverage_snapshot(
            self.database,
            association_root=self.associations.parent,
            profile_ids=[target.id],
            decision_kind="readiness_promotion",
        )
        self._report(
            observation,
            profile_id=target.id,
            outcome="proposed_match",
            proposed=target.id,
            automatic_profile_ready=True,
            created_at="2026-08-26T12:01:00+00:00",
            suffix="-ready",
        )
        after = build_profile_leverage_snapshot(
            self.database,
            association_root=self.associations.parent,
            profile_ids=[target.id],
            decision_kind="readiness_promotion",
            profile_level_decisions=1,
        )

        result = compare_profile_leverage_snapshots(before, after)

        self.assertEqual(0, result["observed"]["newly_resolved_sermon_count"])
        self.assertEqual(1, result["observed"]["downstream_proposals_enabled"])
        self.assertEqual(1, result["observed"]["proposals_made_actionable"])
        self.assertEqual([], result["observed"]["new_proposal_observation_ids"])


if __name__ == "__main__":
    unittest.main()
