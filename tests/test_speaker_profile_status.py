from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pastor_transcript_extractor.config import build_paths, ensure_directories
from pastor_transcript_extractor.models import SourceType, VideoStatus
from pastor_transcript_extractor.reviewed_speaker_evidence import (
    ObservationQualification,
    PairRelation,
    ReviewProvenance,
    ReviewedSpeakerEvidence,
)
from pastor_transcript_extractor.speaker_profile_status import (
    build_profile_pipeline_status,
)
from pastor_transcript_extractor.speaker_registry import (
    attach_reviewed_observation,
    create_anonymous_profile,
    ensure_configured_pastor_profile,
    record_name_claim_review,
    record_observation_disposition,
    record_profile_redirect,
)
from pastor_transcript_extractor.storage import Database


class SpeakerProfileStatusTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.paths = build_paths(Path(self.tempdir.name))
        ensure_directories(self.paths)
        self.database = Database(self.paths.database)
        self.database.initialize()
        self.source_a = self.database.add_source(
            "https://www.youtube.com/@one",
            SourceType.CHANNEL,
            pastor_id=None,
        )
        self.source_b = self.database.add_source(
            "https://www.youtube.com/@two",
            SourceType.CHANNEL,
            pastor_id=None,
        )

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _observation(self, key: str, *, second_source: bool = False):
        source = self.source_b if second_source else self.source_a
        video = self.database.add_video(
            source_id=source.id,
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

    def _claim(
        self,
        observation,
        name: str,
        *,
        correlation_group_id: str | None = None,
    ):
        return self.database.add_speaker_name_claim(
            video_id=observation.video_id,
            observation_id=observation.id,
            display_name=name,
            normalized_name=name.lower(),
            claim_kind="explicit_speaker_attribution",
            channel="metadata",
            explicit_speaker_attribution=True,
            correlation_group_id=(
                correlation_group_id or f"group-{observation.id}"
            ),
            provenance_json="{}",
            artifact_path=observation.artifact_path,
            claim_fingerprint=f"claim-{observation.id}",
            extractor_version="speaker_evidence_v1",
        )

    def test_report_explains_linked_profile_and_review_backlog(self) -> None:
        observation_a = self._observation("a")
        observation_b = self._observation("b", second_source=True)
        frontier = self._observation("c")
        multiple = self._observation("d")
        self._observation("e")
        profile = create_anonymous_profile(
            self.database,
            reviewer="reviewer",
            reason="same pair",
            review_event_key="profile-a",
        )
        for observation in (observation_a, observation_b):
            attach_reviewed_observation(
                self.database,
                profile_id=profile.id,
                observation_id=observation.id,
                reviewer="reviewer",
                reason="same pair",
                review_event_key=f"attach-{observation.id}",
            )
        claim_a = self._claim(observation_a, "Alice Example")
        self._claim(frontier, "Alice Example")
        record_name_claim_review(
            self.database,
            claim_id=claim_a.id,
            profile_id=profile.id,
            attach=True,
            reviewer="reviewer",
            reason="consistent attribution",
            review_event_key="claim-a",
        )
        record_observation_disposition(
            self.database,
            observation_id=frontier.id,
            action="qualified_single_speaker",
            reviewer="reviewer",
            reason="pair review",
            review_event_key="frontier-single",
        )
        record_observation_disposition(
            self.database,
            observation_id=multiple.id,
            action="multiple_speakers",
            reviewer="reviewer",
            reason="pair review",
            review_event_key="multiple",
        )
        pastor = self.database.add_pastor("alice", "Alice Example")
        configured = ensure_configured_pastor_profile(self.database, pastor)
        record_profile_redirect(
            self.database,
            from_profile_id=configured.id,
            to_profile_id=profile.id,
            reviewer="reviewer",
            reason="reviewed attribution",
            review_event_key="configured-link",
        )
        evidence = ReviewedSpeakerEvidence(
            qualifications={},
            qualification_conflicts={},
            pair_relations={},
            pair_conflicts={},
            review_event_count=7,
        )

        status = build_profile_pipeline_status(self.database, evidence)

        self.assertEqual(status.registry_observation_count, 5)
        self.assertEqual(status.qualification_counts["qualified_single_speaker"], 3)
        self.assertEqual(status.qualification_counts["multiple_speakers"], 1)
        self.assertEqual(status.qualification_counts["unreviewed"], 1)
        self.assertEqual(status.canonical_profile_count, 1)
        self.assertEqual(status.profile_member_count, 2)
        self.assertEqual(status.named_ungrouped_single_count, 1)
        self.assertEqual(status.attributed_frontier_observation_count, 1)
        self.assertEqual(status.unmatched_named_ungrouped_single_count, 0)
        self.assertEqual(status.unnamed_ungrouped_single_count, 0)
        self.assertEqual(status.attached_name_claim_count, 1)
        self.assertEqual(status.configured_identity_count, 1)
        self.assertEqual(
            status.profiles[0].configured_identities, ("Alice Example",)
        )
        self.assertEqual(status.profiles[0].state, "linked")
        self.assertEqual(status.profiles[0].source_count, 2)
        self.assertEqual(status.profiles[0].attributed_frontier_count, 1)
        self.assertIn("1 attributed frontier", status.profiles[0].next_need)
        self.assertEqual(status.pending_qualification_count, 0)
        self.assertEqual(status.pending_same_component_count, 0)
        self.assertEqual(status.pending_difference_count, 0)

    def test_same_name_profiles_are_reported_as_merge_candidates(self) -> None:
        observations = [self._observation(key) for key in ("a", "b", "c", "d")]
        profiles = [
            create_anonymous_profile(
                self.database,
                reviewer="reviewer",
                reason="same pair",
                review_event_key=f"profile-{index}",
            )
            for index in range(2)
        ]
        for index, profile in enumerate(profiles):
            for observation in observations[index * 2 : index * 2 + 2]:
                attach_reviewed_observation(
                    self.database,
                    profile_id=profile.id,
                    observation_id=observation.id,
                    reviewer="reviewer",
                    reason="same pair",
                    review_event_key=f"attach-{observation.id}",
                )
                self._claim(observation, "Jordan Fowler")
        evidence = ReviewedSpeakerEvidence({}, {}, {}, {}, 2)

        status = build_profile_pipeline_status(self.database, evidence)

        self.assertEqual(status.merge_candidate_count, 2)
        self.assertEqual(
            {profile.state for profile in status.profiles},
            {"merge-candidate"},
        )
        self.assertIn("merge candidates", status.next_actions[0])

    def test_display_name_variants_do_not_create_attribution_conflict(self) -> None:
        observations = [self._observation(key) for key in ("a", "b")]
        profile = create_anonymous_profile(
            self.database,
            reviewer="reviewer",
            reason="same speaker",
            review_event_key="profile-sunia",
        )
        claims = []
        for observation, display_name in zip(
            observations,
            ("Sunia FukoFuka", "Sunia Fukofuka"),
            strict=True,
        ):
            attach_reviewed_observation(
                self.database,
                profile_id=profile.id,
                observation_id=observation.id,
                reviewer="reviewer",
                reason="same speaker",
                review_event_key=f"attach-{observation.id}",
            )
            claims.append(
                self._claim(
                    observation,
                    display_name,
                    correlation_group_id="speaker-credit-sunia",
                )
            )
        for claim in claims:
            record_name_claim_review(
                self.database,
                claim_id=claim.id,
                profile_id=profile.id,
                attach=True,
                reviewer="reviewer",
                reason="same normalized speaker credit",
                review_event_key=f"claim-{claim.id}",
            )

        status = build_profile_pipeline_status(
            self.database,
            ReviewedSpeakerEvidence({}, {}, {}, {}, 0),
        )

        row = status.profiles[0]
        self.assertEqual(row.state, "attributed")
        self.assertEqual(
            row.names,
            ("Sunia FukoFuka", "Sunia Fukofuka"),
        )
        self.assertEqual(status.attribution_conflict_count, 0)

    def test_named_backlog_separates_matching_frontiers_from_seeds(self) -> None:
        member = self._observation("member")
        matching = self._observation("matching")
        unmatched = self._observation("unmatched")
        profile = create_anonymous_profile(
            self.database,
            reviewer="reviewer",
            reason="same pair",
            review_event_key="profile",
        )
        attach_reviewed_observation(
            self.database,
            profile_id=profile.id,
            observation_id=member.id,
            reviewer="reviewer",
            reason="same pair",
            review_event_key="attach-member",
        )
        self._claim(member, "Alice Example")
        self._claim(matching, "Alice Example")
        self._claim(unmatched, "Bob Example")
        for observation in (matching, unmatched):
            record_observation_disposition(
                self.database,
                observation_id=observation.id,
                action="qualified_single_speaker",
                reviewer="reviewer",
                reason="pair review",
                review_event_key=f"single-{observation.id}",
            )

        status = build_profile_pipeline_status(
            self.database,
            ReviewedSpeakerEvidence({}, {}, {}, {}, 0),
        )

        self.assertEqual(status.named_ungrouped_single_count, 2)
        self.assertEqual(status.attributed_frontier_observation_count, 1)
        self.assertEqual(status.unmatched_named_ungrouped_single_count, 1)
        messages = [action.message for action in status.actions]
        self.assertTrue(any("match existing profiles" in item for item in messages))
        self.assertTrue(any("do not match an existing" in item for item in messages))

    def test_anonymous_bridge_profile_reports_both_reinforcement_and_name(self) -> None:
        observations = [self._observation(key) for key in ("a", "b", "c")]
        profile = create_anonymous_profile(
            self.database,
            reviewer="reviewer",
            reason="same component",
            review_event_key="anonymous-profile",
        )
        for observation in observations:
            attach_reviewed_observation(
                self.database,
                profile_id=profile.id,
                observation_id=observation.id,
                reviewer="reviewer",
                reason="same component",
                review_event_key=f"attach-{observation.id}",
            )
        provenance = (ReviewProvenance("event", "pair", "reviewer"),)
        evidence = ReviewedSpeakerEvidence(
            qualifications={},
            qualification_conflicts={},
            pair_relations={
                frozenset(("a", "b")): PairRelation(
                    frozenset(("a", "b")), "same_speaker", provenance
                ),
                frozenset(("b", "c")): PairRelation(
                    frozenset(("b", "c")), "same_speaker", provenance
                ),
            },
            pair_conflicts={},
            review_event_count=2,
        )

        status = build_profile_pipeline_status(self.database, evidence)

        row = status.profiles[0]
        self.assertEqual(row.state, "anonymous")
        self.assertTrue(row.shadow_ready)
        self.assertFalse(row.automatic_profile_ready)
        self.assertEqual(
            {need.code for need in row.needs},
            {
                "reviewed_same_graph_contains_bridge",
                "obtain_explicit_attribution",
            },
        )

    def test_report_detects_reviewed_evidence_that_needs_sync(self) -> None:
        observations = [self._observation(key) for key in ("a", "b", "c", "d")]
        provenance = (ReviewProvenance("event", "pair", "reviewer"),)
        evidence = ReviewedSpeakerEvidence(
            qualifications={
                observation.input_fingerprint: ObservationQualification(
                    "qualified_single_speaker",
                    provenance,
                )
                for observation in observations
            },
            qualification_conflicts={},
            pair_relations={
                frozenset(("a", "b")): PairRelation(
                    frozenset(("a", "b")),
                    "same_speaker",
                    provenance,
                ),
                frozenset(("c", "d")): PairRelation(
                    frozenset(("c", "d")),
                    "different_speaker",
                    provenance,
                ),
            },
            pair_conflicts={},
            review_event_count=1,
        )

        status = build_profile_pipeline_status(self.database, evidence)

        self.assertEqual(status.pending_qualification_count, 4)
        self.assertEqual(status.pending_same_component_count, 1)
        self.assertEqual(status.pending_difference_count, 1)
        self.assertIn("Run reviewed-evidence sync", status.next_actions[0])

    def test_report_includes_unpromoted_shadow_discovery_candidate(self) -> None:
        observations = [self._observation(key) for key in ("a", "b", "c")]
        report = {
            "result_sha256": "a" * 64,
            "counts": {
                "blocked_components_with_actionable_review_frontier": 1,
            },
            "components": [
                {
                    "component_id": "component-abc",
                    "outcome": "provisional_profile_candidate",
                    "blockers": [],
                    "member_count": 3,
                    "recording_count": 3,
                    "source_count": 1,
                    "normalized_names": [],
                    "members": [
                        {
                            "observation_id": observation.id,
                            "video_id": observation.video_id,
                            "input_fingerprint": observation.input_fingerprint,
                        }
                        for observation in observations
                    ],
                },
                {
                    "component_id": "blocked-component",
                    "outcome": "blocked",
                },
            ],
        }

        status = build_profile_pipeline_status(
            self.database,
            ReviewedSpeakerEvidence({}, {}, {}, {}, 0),
            discovery_report=report,
            discovery_report_path=Path("discovery.json"),
        )

        self.assertEqual(status.shadow_discovery_candidate_count, 1)
        self.assertEqual(status.promoted_discovery_candidate_count, 0)
        self.assertEqual(status.stale_discovery_candidate_count, 0)
        self.assertEqual(status.blocked_discovery_component_count, 1)
        self.assertEqual(status.actionable_discovery_frontier_component_count, 1)
        self.assertEqual(status.discovered_profiles[0].state, "shadow-candidate")
        self.assertEqual(status.discovered_profiles[0].member_count, 3)
        self.assertIn("reversible promotion", status.next_actions[0])
        self.assertIn("near-same ambiguous", status.next_actions[1])

    def test_report_explains_staged_discovery_frontier_next_action(self) -> None:
        status = build_profile_pipeline_status(
            self.database,
            ReviewedSpeakerEvidence({}, {}, {}, {}, 0),
            discovery_report={
                "result_sha256": "b" * 64,
                "counts": {
                    "blocked_components_with_actionable_review_frontier": 1,
                    "blocked_components_with_immediate_review_frontier": 0,
                    "blocked_components_with_staged_review_frontier": 1,
                },
                "components": [
                    {
                        "component_id": "staged-component",
                        "outcome": "blocked",
                    }
                ],
            },
            discovery_report_path=Path("discovery.json"),
        )

        self.assertEqual(1, status.actionable_discovery_frontier_component_count)
        self.assertEqual(0, status.immediate_discovery_frontier_component_count)
        self.assertEqual(1, status.staged_discovery_frontier_component_count)
        self.assertIn("staged near-same", status.next_actions[0])

    def test_report_warns_against_distant_staged_reviews(self) -> None:
        status = build_profile_pipeline_status(
            self.database,
            ReviewedSpeakerEvidence({}, {}, {}, {}, 0),
            discovery_report={
                "result_sha256": "c" * 64,
                "counts": {
                    "blocked_components_with_actionable_review_frontier": 0,
                    "blocked_components_with_immediate_review_frontier": 0,
                    "blocked_components_with_staged_review_frontier": 0,
                    "blocked_components_with_only_distant_staged_candidates": 2,
                },
                "components": [
                    {"component_id": "distant-a", "outcome": "blocked"},
                    {"component_id": "distant-b", "outcome": "blocked"},
                ],
            },
            discovery_report_path=Path("discovery.json"),
        )

        self.assertEqual(0, status.actionable_discovery_frontier_component_count)
        self.assertEqual(0, status.staged_discovery_frontier_component_count)
        self.assertEqual(2, status.distant_staged_discovery_component_count)
        self.assertIn("Do not review distant", status.next_actions[0])

    def test_report_links_promoted_discovery_candidate_to_profile(self) -> None:
        observations = [self._observation(key) for key in ("a", "b", "c")]
        component_id = "component-abc"
        profile = self.database.ensure_speaker_profile(
            stable_key=f"speaker:discovery:{component_id[:32]}",
            display_label=None,
            lifecycle_state="provisional",
            created_reason="shadow_discovery_candidate",
        )
        self.database.add_speaker_profile_discovery_promotion(
            profile_id=profile.id,
            component_id=component_id,
            discovery_result_sha256="a" * 64,
            discovery_artifact_path="discovery.json",
            seed_observation_ids_json="[]",
            event_fingerprint="promotion-event",
        )
        for observation in observations:
            attach_reviewed_observation(
                self.database,
                profile_id=profile.id,
                observation_id=observation.id,
                reviewer="system:test",
                reason="test discovery promotion",
                review_event_key=f"promoted-{observation.id}",
            )
        report = {
            "result_sha256": "a" * 64,
            "components": [
                {
                    "component_id": component_id,
                    "outcome": "provisional_profile_candidate",
                    "blockers": [],
                    "member_count": 3,
                    "recording_count": 3,
                    "source_count": 1,
                    "normalized_names": [],
                    "members": [],
                }
            ],
        }

        status = build_profile_pipeline_status(
            self.database,
            ReviewedSpeakerEvidence({}, {}, {}, {}, 0),
            discovery_report=report,
        )

        self.assertEqual(status.canonical_profile_count, 1)
        self.assertEqual(status.shadow_discovery_candidate_count, 0)
        self.assertEqual(status.promoted_discovery_candidate_count, 1)
        self.assertEqual(status.discovered_profiles[0].state, "promoted")
        self.assertEqual(
            status.discovered_profiles[0].promoted_profile_id,
            profile.id,
        )
        self.assertEqual(
            status.discovered_profiles[0].next_need,
            status.profiles[0].next_need,
        )
        self.assertEqual(
            {need.code for need in status.profiles[0].needs},
            {
                "generate_discovery_confirmation_proposal",
                "apply_discovery_confirmation",
            },
        )


if __name__ == "__main__":
    unittest.main()
