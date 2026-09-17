from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pastor_transcript_extractor.config import build_paths, ensure_directories
from pastor_transcript_extractor.models import SourceType, VideoStatus
from pastor_transcript_extractor.reviewed_speaker_evidence import (
    ReviewedSpeakerEvidence,
)
from pastor_transcript_extractor.source_profile_consolidation import (
    apply_source_profile_consolidation,
    build_source_profile_consolidation_plan,
    list_source_profile_cohorts,
    source_profile_candidates,
)
from pastor_transcript_extractor.speaker_registry import (
    attach_reviewed_observation,
    create_anonymous_profile,
)
from pastor_transcript_extractor.storage import Database


class SourceProfileConsolidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.paths = build_paths(self.root / "app")
        ensure_directories(self.paths)
        self.database = Database(self.paths.database)
        self.database.initialize()
        self.source = self.database.add_source(
            "https://www.youtube.com/@source-cohort",
            SourceType.CHANNEL,
            pastor_id=None,
        )

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _evidence(self) -> ReviewedSpeakerEvidence:
        return ReviewedSpeakerEvidence(
            qualifications={},
            qualification_conflicts={},
            pair_relations={},
            pair_conflicts={},
            review_event_count=0,
        )

    def _observation(self, key: str):
        video = self.database.add_video(
            source_id=self.source.id,
            pastor_id=None,
            youtube_video_id=f"video-{key}",
            title=f"Video {key}",
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
            start_seconds=100.0,
            end_seconds=1000.0,
            artifact_path=f"{key}.speaker.json",
            content_sha256=f"content-{key}",
            extractor_version="speaker_evidence_v1",
            input_fingerprint=key,
        )

    def _profile(self, key: str):
        profile = create_anonymous_profile(
            self.database,
            reviewer="reviewer",
            reason="reviewed pair",
            review_event_key=f"profile-{key}",
        )
        observations = tuple(
            self._observation(f"{key}-{index}") for index in range(2)
        )
        for observation in observations:
            attach_reviewed_observation(
                self.database,
                profile_id=profile.id,
                observation_id=observation.id,
                reviewer="reviewer",
                reason="reviewed pair",
                review_event_key=f"attach-{key}-{observation.id}",
            )
        return profile, observations

    def test_complete_link_profile_cohort_needs_one_proposal(self) -> None:
        profiles = [self._profile(key) for key in ("a", "b", "c")]
        candidates, excluded = source_profile_candidates(
            self.database,
            self._evidence(),
            source_id=self.source.id,
            exemplars_per_profile=2,
        )
        self.assertEqual((), excluded)
        comparisons = {
            tuple(sorted((left.id, right.id))): {
                "outcome": "same_speaker",
                "metrics": {"cross_p10": 0.80 + (left.id + right.id) / 1000},
            }
            for index, (_, left_observations) in enumerate(profiles)
            for _, right_observations in profiles[index + 1 :]
            for left in left_observations
            for right in right_observations
        }

        plan = build_source_profile_consolidation_plan(
            self.database,
            source_id=self.source.id,
            candidates=candidates,
            comparisons=comparisons,
        )

        self.assertEqual(1, len(plan.proposals))
        self.assertEqual(
            tuple(profile.id for profile, _ in profiles),
            plan.proposals[0].profile_ids,
        )
        self.assertEqual(12, plan.proposals[0].comparison_count)
        self.assertTrue(all(item.eligible for item in plan.pair_evidence))

    def test_source_inventory_lists_only_sources_meeting_minimum(self) -> None:
        profiles = [self._profile(key) for key in ("a", "b", "c")]
        other_source = self.database.add_source(
            "https://www.youtube.com/@single-profile",
            SourceType.CHANNEL,
            pastor_id=None,
        )
        other_profile = create_anonymous_profile(
            self.database,
            reviewer="reviewer",
            reason="reviewed pair",
            review_event_key="other-profile",
        )
        for index in range(2):
            video = self.database.add_video(
                source_id=other_source.id,
                pastor_id=None,
                youtube_video_id=f"other-{index}",
                title=f"Other {index}",
                url=f"https://www.youtube.com/watch?v=other-{index}",
                status=VideoStatus.EXTRACTED,
            )
            extraction = self.database.add_extraction_result(
                video_id=video.id,
                version=1,
                proposed_text_path=f"other-{index}.md",
                proposed_json_path=f"other-{index}.json",
            )
            observation = self.database.add_speaker_observation(
                video_id=video.id,
                extraction_result_id=extraction.id,
                role="principal_speaker_candidate",
                multiplicity_state="unknown",
                start_seconds=100.0,
                end_seconds=1000.0,
                artifact_path=f"other-{index}.speaker.json",
                content_sha256=f"content-other-{index}",
                extractor_version="speaker_evidence_v1",
                input_fingerprint=f"other-{index}",
            )
            attach_reviewed_observation(
                self.database,
                profile_id=other_profile.id,
                observation_id=observation.id,
                reviewer="reviewer",
                reason="reviewed pair",
                review_event_key=f"attach-other-{index}",
            )

        summaries = list_source_profile_cohorts(
            self.database,
            self._evidence(),
            exemplars_per_profile=2,
            minimum_profiles=2,
        )

        self.assertEqual(1, len(summaries))
        self.assertEqual(self.source.id, summaries[0].source_id)
        self.assertEqual(3, summaries[0].profile_count)
        self.assertEqual(6, summaries[0].member_count)
        self.assertEqual(6, summaries[0].exemplar_count)
        self.assertEqual(12, summaries[0].comparison_upper_bound)
        self.assertEqual(
            {profile.id for profile, _ in profiles},
            {
                candidate.profile_id
                for candidate in source_profile_candidates(
                    self.database,
                    self._evidence(),
                    source_id=self.source.id,
                    exemplars_per_profile=2,
                )[0]
            },
        )

    def test_ambiguous_edge_fails_closed_without_blocking_safe_pair(self) -> None:
        profiles = [self._profile(key) for key in ("a", "b", "c")]
        candidates, _ = source_profile_candidates(
            self.database,
            self._evidence(),
            source_id=self.source.id,
            exemplars_per_profile=2,
        )
        comparisons = {
            tuple(sorted((left.id, right.id))): {"outcome": "same_speaker"}
            for index, (_, left_observations) in enumerate(profiles)
            for _, right_observations in profiles[index + 1 :]
            for left in left_observations
            for right in right_observations
        }
        ambiguous_pair = tuple(
            sorted((profiles[0][1][0].id, profiles[2][1][0].id))
        )
        comparisons[ambiguous_pair] = {"outcome": "insufficient_evidence"}

        plan = build_source_profile_consolidation_plan(
            self.database,
            source_id=self.source.id,
            candidates=candidates,
            comparisons=comparisons,
        )

        self.assertEqual(
            (profiles[0][0].id, profiles[1][0].id),
            plan.proposals[0].profile_ids,
        )
        blocked = next(
            item
            for item in plan.pair_evidence
            if item.profile_ids == (profiles[0][0].id, profiles[2][0].id)
        )
        self.assertFalse(blocked.eligible)
        self.assertIn("incomplete_or_ambiguous_complete_link", blocked.blockers)

    def test_approved_cohort_merges_all_members_append_only(self) -> None:
        profiles = [self._profile(key) for key in ("a", "b", "c")]
        candidates, _ = source_profile_candidates(
            self.database,
            self._evidence(),
            source_id=self.source.id,
            exemplars_per_profile=2,
        )
        comparisons = {
            tuple(sorted((left.id, right.id))): {"outcome": "same_speaker"}
            for index, (_, left_observations) in enumerate(profiles)
            for _, right_observations in profiles[index + 1 :]
            for left in left_observations
            for right in right_observations
        }
        plan = build_source_profile_consolidation_plan(
            self.database,
            source_id=self.source.id,
            candidates=candidates,
            comparisons=comparisons,
        )

        canonical_id = apply_source_profile_consolidation(
            self.database,
            plan=plan,
            proposal=plan.proposals[0],
            reviewer="brian",
            artifact_sha256="a" * 64,
        )

        self.assertEqual(profiles[0][0].id, canonical_id)
        self.assertEqual(
            {canonical_id},
            {
                self.database.resolve_speaker_profile_id(profile.id)
                for profile, _ in profiles
            },
        )
        self.assertEqual(
            6,
            len(
                self.database.list_effective_observation_ids_for_profile(
                    canonical_id
                )
            ),
        )

    def test_apply_revalidates_attribution_conflicts(self) -> None:
        profiles = [self._profile(key) for key in ("a", "b")]
        candidates, _ = source_profile_candidates(
            self.database,
            self._evidence(),
            source_id=self.source.id,
            exemplars_per_profile=2,
        )
        comparisons = {
            tuple(sorted((left.id, right.id))): {"outcome": "same_speaker"}
            for left in profiles[0][1]
            for right in profiles[1][1]
        }
        plan = build_source_profile_consolidation_plan(
            self.database,
            source_id=self.source.id,
            candidates=candidates,
            comparisons=comparisons,
        )
        for index, (_, observations) in enumerate(profiles):
            observation = observations[0]
            self.database.add_speaker_name_claim(
                video_id=observation.video_id,
                observation_id=observation.id,
                display_name=("Alex Example", "Jordan Example")[index],
                normalized_name=("alex example", "jordan example")[index],
                claim_kind="explicit_speaker_attribution",
                channel="metadata",
                explicit_speaker_attribution=True,
                correlation_group_id=f"group-{index}",
                provenance_json="{}",
                artifact_path=observation.artifact_path,
                claim_fingerprint=f"claim-{index}",
                extractor_version="speaker_evidence_v1",
            )
        conflicts: list[str] = []

        canonical_id = apply_source_profile_consolidation(
            self.database,
            plan=plan,
            proposal=plan.proposals[0],
            reviewer="brian",
            artifact_sha256="b" * 64,
            conflicts=conflicts,
        )

        self.assertIsNone(canonical_id)
        self.assertIn("conflicting explicit attributions", conflicts[0])
        self.assertEqual(
            {profile.id for profile, _ in profiles},
            {
                self.database.resolve_speaker_profile_id(profile.id)
                for profile, _ in profiles
            },
        )


if __name__ == "__main__":
    unittest.main()
