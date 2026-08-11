from __future__ import annotations

from datetime import datetime, timezone
import unittest

from pastor_transcript_extractor.speaker_pair_selector import (
    AcousticPairRanking,
    AssociationConfirmationPair,
    DiscoveryResolutionPair,
    PairCandidateObservation,
    PairSelectionHistory,
    SelectionStratum,
    SourceRelation,
    select_next_speaker_pair,
    selection_history_from_artifacts,
)


def candidate(
    fingerprint: str,
    *,
    name: str | None = None,
    day: int = 1,
    source_family: str | None = None,
    partition: str | None = None,
    profile_ids: frozenset[int] = frozenset(),
    different_from: frozenset[str] = frozenset(),
    consistency_score: float | None = None,
    bootstrap_profile_id: int | None = None,
    configured_title_match: bool = False,
) -> PairCandidateObservation:
    return PairCandidateObservation(
        input_fingerprint=fingerprint,
        video_id=f"video-{fingerprint}",
        recording_date=datetime(2026, 7, day, tzinfo=timezone.utc),
        explicit_attributions=frozenset((name,)) if name else frozenset(),
        quality_signature=("wav", 16_000, 1),
        source_family_id=source_family,
        evaluation_partition=partition,
        reviewed_profile_ids=profile_ids,
        explicitly_different_from=different_from,
        observation_consistency_score=consistency_score,
        configured_profile_bootstrap_id=bootstrap_profile_id,
        configured_target_title_match=configured_title_match,
    )


class SpeakerPairSelectorTests(unittest.TestCase):
    def test_profile_growth_prioritizes_empty_configured_profile_bootstrap(
        self,
    ) -> None:
        selected = select_next_speaker_pair(
            [
                candidate(
                    "bootstrap-a",
                    name="mihail baciu",
                    bootstrap_profile_id=27,
                    configured_title_match=True,
                    source_family="source-a",
                ),
                candidate(
                    "bootstrap-b",
                    name="mihail baciu",
                    bootstrap_profile_id=27,
                    configured_title_match=True,
                    source_family="source-a",
                ),
                candidate("ordinary-a", name="alex"),
                candidate("ordinary-b", name="alex"),
            ],
            PairSelectionHistory(),
            selection_goal="profile-growth",
        )

        self.assertEqual(
            {"bootstrap-a", "bootstrap-b"},
            {
                selected.observation_a.input_fingerprint,
                selected.observation_b.input_fingerprint,
            },
        )
        self.assertEqual(
            "configured_profile_bootstrap",
            selected.manifest["selection_objective"],
        )
        self.assertEqual(
            {
                "profile_id": 27,
                "role": "human_review_nomination_only",
                "identity_evidence": False,
                "title_match_count": 2,
            },
            selected.manifest["configured_profile_bootstrap"],
        )

    def test_configured_bootstrap_requires_two_title_matches_or_acoustic_support(
        self,
    ) -> None:
        with self.assertRaisesRegex(
            ValueError,
            "no actionable profile-growth pair",
        ):
            select_next_speaker_pair(
                [
                    candidate(
                        "title-match",
                        name="mihail baciu",
                        bootstrap_profile_id=27,
                        configured_title_match=True,
                        source_family="source-a",
                    ),
                    candidate(
                        "generic-service",
                        bootstrap_profile_id=27,
                        source_family="source-a",
                    ),
                ],
                PairSelectionHistory(),
                selection_goal="profile-growth",
            )

    def test_configured_bootstrap_accepts_one_title_match_with_acoustic_support(
        self,
    ) -> None:
        selected = select_next_speaker_pair(
            [
                candidate(
                    "title-match",
                    name="mihail baciu",
                    bootstrap_profile_id=27,
                    configured_title_match=True,
                    source_family="source-a",
                ),
                candidate(
                    "generic-service",
                    bootstrap_profile_id=27,
                    source_family="source-a",
                ),
            ],
            PairSelectionHistory(),
            selection_goal="profile-growth",
            profile_growth_acoustic_pairs=(
                AcousticPairRanking(
                    fingerprint_a="title-match",
                    fingerprint_b="generic-service",
                    same_boundary_margin=0.08,
                    centroid_similarity=0.94,
                    report_result_sha256="a" * 64,
                    report_path="discovery.json",
                ),
            ),
        )

        self.assertEqual(
            "configured_profile_bootstrap",
            selected.manifest["selection_objective"],
        )
        self.assertEqual(
            1,
            selected.manifest["configured_profile_bootstrap"][
                "title_match_count"
            ],
        )

    def _association_nomination(
        self,
        candidate_fingerprint: str,
        exemplar_fingerprint: str,
        *,
        profile_id: int = 7,
        margin: float = 0.08,
        provisional_assignment_active: bool = False,
    ) -> AssociationConfirmationPair:
        return AssociationConfirmationPair(
            candidate_fingerprint=candidate_fingerprint,
            exemplar_fingerprint=exemplar_fingerprint,
            profile_id=profile_id,
            same_comparison_count=2,
            same_boundary_margin=margin,
            report_result_sha256="a" * 64,
            report_path="association.json",
            provisional_assignment_active=provisional_assignment_active,
        )

    def test_default_selection_goal_preserves_evaluation_selector(self) -> None:
        selected = select_next_speaker_pair(
            [
                candidate("profile-a", profile_ids=frozenset((7,))),
                candidate("profile-b", profile_ids=frozenset((7,))),
                candidate("other"),
            ],
            PairSelectionHistory(),
        )

        self.assertEqual("evaluation", selected.manifest["selection_goal"])
        self.assertEqual(
            "reviewed_same_profile_nomination",
            selected.manifest["selection_objective"],
        )
        self.assertEqual(
            {
                selected.observation_a.input_fingerprint,
                selected.observation_b.input_fingerprint,
            },
            set(
                selected.manifest[
                    "selected_observation_fingerprints"
                ].values()
            ),
        )

    def test_activity_rejection_excludes_failed_observation_from_all_pairs(
        self,
    ) -> None:
        rejection = {
            "event_kind": "speaker_pair_automatic_selection_rejection",
            "review_status": "rejected_automatically",
            "reason": "insufficient_speech_activity",
            "failed_observation_fingerprint": "silent",
            "pair_id": "pair-rejected",
            "observations": {
                "source_a": {
                    "input_fingerprint": "silent",
                    "youtube_video_id": "video-silent",
                },
                "source_b": {
                    "input_fingerprint": "prior-partner",
                    "youtube_video_id": "video-prior-partner",
                },
            },
        }
        history = selection_history_from_artifacts(
            drafts=[rejection],
            reviews=[],
            fixtures=[],
        )

        selected = select_next_speaker_pair(
            [
                candidate("silent"),
                candidate("prior-partner"),
                candidate("fresh-a"),
                candidate("fresh-b"),
            ],
            history,
        )

        self.assertNotIn(
            "silent",
            {
                selected.observation_a.input_fingerprint,
                selected.observation_b.input_fingerprint,
            },
        )

    def test_activity_policy_upgrade_reopens_previously_rejected_observation(
        self,
    ) -> None:
        rejection = {
            "event_kind": "speaker_pair_automatic_selection_rejection",
            "reason": "insufficient_speech_activity",
            "failed_observation_fingerprint": "quiet",
            "pair_id": "pair-v2-rejected",
            "observations": {
                "source_a": {
                    "input_fingerprint": "quiet",
                    "youtube_video_id": "video-quiet",
                    "clip_selection": {
                        "policy_version": "speaker_pair_clip_activity_v2"
                    },
                },
                "source_b": {
                    "input_fingerprint": "partner",
                    "youtube_video_id": "video-partner",
                },
            },
        }

        history = selection_history_from_artifacts(
            drafts=[rejection],
            reviews=[],
            fixtures=[],
            current_clip_activity_policy_version=(
                "speaker_pair_clip_activity_v3"
            ),
        )

        self.assertEqual(
            frozenset(),
            history.automatically_unreviewable_observations,
        )
        self.assertNotIn(
            frozenset(("quiet", "partner")),
            history.excluded_pairs,
        )

    def test_profile_growth_prefers_profile_frontier_without_reconfirming_members(
        self,
    ) -> None:
        selected = select_next_speaker_pair(
            [
                candidate(
                    "profile-a",
                    name="alex",
                    profile_ids=frozenset((7,)),
                ),
                candidate(
                    "profile-b",
                    name="alex",
                    profile_ids=frozenset((7,)),
                ),
                candidate("frontier", name="alex"),
                candidate("seed-a", name="blair"),
                candidate("seed-b", name="blair"),
            ],
            PairSelectionHistory(),
            selection_goal="profile-growth",
        )

        selected_fingerprints = {
            selected.observation_a.input_fingerprint,
            selected.observation_b.input_fingerprint,
        }
        self.assertIn("frontier", selected_fingerprints)
        self.assertEqual(
            1,
            len(selected_fingerprints & {"profile-a", "profile-b"}),
        )
        self.assertEqual("profile-growth", selected.manifest["selection_goal"])
        self.assertEqual(
            "profile_growth_frontier",
            selected.manifest["selection_objective"],
        )

    def test_profile_growth_seeds_new_profile_before_expanding_mature_profile(
        self,
    ) -> None:
        selected = select_next_speaker_pair(
            [
                *[
                    candidate(
                        f"mature-{index}",
                        name="jordan",
                        profile_ids=frozenset((7,)),
                    )
                    for index in range(4)
                ],
                candidate("mature-frontier-a", name="jordan"),
                candidate("mature-frontier-b", name="jordan"),
                candidate("seed-a", name="blair"),
                candidate("seed-b", name="blair"),
            ],
            PairSelectionHistory(),
            selection_goal="profile-growth",
        )

        self.assertEqual(
            {"seed-a", "seed-b"},
            {
                selected.observation_a.input_fingerprint,
                selected.observation_b.input_fingerprint,
            },
        )
        self.assertEqual(
            "profile_growth_seed",
            selected.manifest["selection_objective"],
        )

    def test_profile_growth_rotates_between_equally_blocked_profiles(self) -> None:
        selected = select_next_speaker_pair(
            [
                candidate(
                    "used-a",
                    name="jordan",
                    profile_ids=frozenset((7,)),
                ),
                candidate(
                    "used-b",
                    name="jordan",
                    profile_ids=frozenset((7,)),
                ),
                candidate("used-frontier", name="jordan"),
                candidate(
                    "fresh-a",
                    name="blair",
                    profile_ids=frozenset((8,)),
                ),
                candidate(
                    "fresh-b",
                    name="blair",
                    profile_ids=frozenset((8,)),
                ),
                candidate("fresh-frontier", name="blair"),
            ],
            PairSelectionHistory(
                profile_growth_selections=(
                    frozenset(("used-a", "used-b", "prior-frontier")),
                ),
            ),
            selection_goal="profile-growth",
        )

        self.assertIn(
            "fresh-frontier",
            {
                selected.observation_a.input_fingerprint,
                selected.observation_b.input_fingerprint,
            },
        )
        self.assertTrue(
            {
                selected.observation_a.input_fingerprint,
                selected.observation_b.input_fingerprint,
            }
            & {"fresh-a", "fresh-b"}
        )

    def test_profile_growth_balances_known_quality_with_unknown_exploration(
        self,
    ) -> None:
        candidates = [
            candidate(
                "profile-a",
                name="alex",
                profile_ids=frozenset((7,)),
            ),
            candidate(
                "profile-b",
                name="alex",
                profile_ids=frozenset((7,)),
            ),
            candidate("known-frontier", name="alex"),
            candidate("unknown-frontier", name="alex"),
        ]
        exploit = select_next_speaker_pair(
            candidates,
            PairSelectionHistory(
                qualified_single_observations=frozenset(
                    ("known-frontier",)
                ),
            ),
            selection_goal="profile-growth",
        )
        explore = select_next_speaker_pair(
            candidates,
            PairSelectionHistory(
                profile_growth_selections=(
                    frozenset(("prior-a",)),
                    frozenset(("prior-b",)),
                ),
                qualified_single_observations=frozenset(
                    ("known-frontier",)
                ),
            ),
            selection_goal="profile-growth",
        )

        self.assertIn(
            "known-frontier",
            {
                exploit.observation_a.input_fingerprint,
                exploit.observation_b.input_fingerprint,
            },
        )
        self.assertIn(
            "unknown-frontier",
            {
                explore.observation_a.input_fingerprint,
                explore.observation_b.input_fingerprint,
            },
        )

    def test_profile_growth_prefers_stronger_shadow_consistency_score(self) -> None:
        selected = select_next_speaker_pair(
            [
                candidate(
                    "profile-a",
                    name="alex",
                    profile_ids=frozenset((7,)),
                ),
                candidate(
                    "profile-b",
                    name="alex",
                    profile_ids=frozenset((7,)),
                ),
                candidate("weak", name="alex", consistency_score=0.2),
                candidate("strong", name="alex", consistency_score=0.8),
            ],
            PairSelectionHistory(
                profile_growth_selections=(
                    frozenset(("prior-a",)),
                    frozenset(("prior-b",)),
                ),
            ),
            selection_goal="profile-growth",
        )

        self.assertIn(
            "strong",
            {
                selected.observation_a.input_fingerprint,
                selected.observation_b.input_fingerprint,
            },
        )
        self.assertEqual(
            0.8,
            selected.manifest["observation_consistency_scores"][
                (
                    "a"
                    if selected.observation_a.input_fingerprint == "strong"
                    else "b"
                )
            ],
        )

    def test_profile_growth_prefers_cached_acoustic_same_pair_for_review(
        self,
    ) -> None:
        selected = select_next_speaker_pair(
            [
                candidate(
                    "bridge-a", name="alex", profile_ids=frozenset((7,))
                ),
                candidate(
                    "bridge-b", name="alex", profile_ids=frozenset((8,))
                ),
                candidate("acoustic-a"),
                candidate("acoustic-b"),
            ],
            PairSelectionHistory(),
            selection_goal="profile-growth",
            profile_growth_acoustic_pairs=(
                AcousticPairRanking(
                    fingerprint_a="acoustic-a",
                    fingerprint_b="acoustic-b",
                    same_boundary_margin=0.08,
                    centroid_similarity=0.94,
                    report_result_sha256="a" * 64,
                    report_path="discovery.json",
                ),
            ),
        )

        self.assertEqual(
            {"acoustic-a", "acoustic-b"},
            {
                selected.observation_a.input_fingerprint,
                selected.observation_b.input_fingerprint,
            },
        )
        self.assertEqual(
            "profile_growth_seed", selected.manifest["selection_objective"]
        )
        ranking = selected.manifest["profile_growth_acoustic_ranking"]
        self.assertEqual("review_ranking_only", ranking["role"])
        self.assertFalse(ranking["identity_evidence"])
        self.assertEqual(
            "approved_blinded_pair_review_only",
            ranking["durable_evidence_source"],
        )
        self.assertIn(
            "cached_acoustic_same_ranking", selected.manifest["reason_codes"]
        )

    def test_profile_growth_uses_ambiguous_acoustic_pair_only_as_fallback(
        self,
    ) -> None:
        ranking = AcousticPairRanking(
            fingerprint_a="explore-a",
            fingerprint_b="explore-b",
            same_boundary_margin=-0.01,
            centroid_similarity=0.95,
            report_result_sha256="a" * 64,
            report_path="discovery.json",
            outcome="insufficient_evidence",
            reason="ambiguous_similarity",
        )
        selected = select_next_speaker_pair(
            [candidate("explore-a"), candidate("explore-b")],
            PairSelectionHistory(),
            selection_goal="profile-growth",
            profile_growth_acoustic_pairs=(ranking,),
        )

        self.assertEqual(
            "profile_growth_exploratory_seed",
            selected.manifest["selection_objective"],
        )
        self.assertIn(
            "cached_acoustic_uncertain_nomination",
            selected.manifest["reason_codes"],
        )
        provenance = selected.manifest["profile_growth_acoustic_ranking"]
        self.assertEqual("insufficient_evidence", provenance["outcome"])
        self.assertEqual("review_ranking_only", provenance["role"])
        self.assertFalse(provenance["identity_evidence"])
        self.assertNotIn("expected_outcome", selected.manifest)

    def test_profile_growth_prefers_attribution_signal_over_exploration(
        self,
    ) -> None:
        selected = select_next_speaker_pair(
            [
                candidate("named-a", name="alex"),
                candidate("named-b", name="alex"),
                candidate("explore-a"),
                candidate("explore-b"),
            ],
            PairSelectionHistory(),
            selection_goal="profile-growth",
            profile_growth_acoustic_pairs=(
                AcousticPairRanking(
                    fingerprint_a="explore-a",
                    fingerprint_b="explore-b",
                    same_boundary_margin=-0.01,
                    centroid_similarity=0.95,
                    report_result_sha256="a" * 64,
                    report_path="discovery.json",
                    outcome="insufficient_evidence",
                    reason="ambiguous_similarity",
                ),
            ),
        )

        self.assertEqual(
            {"named-a", "named-b"},
            {
                selected.observation_a.input_fingerprint,
                selected.observation_b.input_fingerprint,
            },
        )
        self.assertEqual(
            "profile_growth_seed", selected.manifest["selection_objective"]
        )

    def test_profile_growth_rejects_distant_ambiguous_acoustic_pair(
        self,
    ) -> None:
        with self.assertRaisesRegex(ValueError, "nomination context"):
            select_next_speaker_pair(
                [candidate("explore-a"), candidate("explore-b")],
                PairSelectionHistory(),
                selection_goal="profile-growth",
                profile_growth_acoustic_pairs=(
                    AcousticPairRanking(
                        fingerprint_a="explore-a",
                        fingerprint_b="explore-b",
                        same_boundary_margin=-0.151,
                        centroid_similarity=0.8,
                        report_result_sha256="a" * 64,
                        report_path="discovery.json",
                        outcome="insufficient_evidence",
                        reason="ambiguous_similarity",
                    ),
                ),
            )

    def test_automation_readiness_withholds_exploratory_acoustic_pair(
        self,
    ) -> None:
        with self.assertRaisesRegex(
            ValueError, "no actionable automation-readiness pair"
        ):
            select_next_speaker_pair(
                [candidate("explore-a"), candidate("explore-b")],
                PairSelectionHistory(),
                selection_goal="automation-readiness",
                profile_growth_acoustic_pairs=(
                    AcousticPairRanking(
                        fingerprint_a="explore-a",
                        fingerprint_b="explore-b",
                        same_boundary_margin=-0.01,
                        centroid_similarity=0.95,
                        report_result_sha256="a" * 64,
                        report_path="discovery.json",
                        outcome="insufficient_evidence",
                        reason="ambiguous_similarity",
                    ),
                ),
            )

    def test_profile_growth_rejects_unbound_acoustic_ranking_context(
        self,
    ) -> None:
        with self.assertRaisesRegex(ValueError, "provenance-bound"):
            select_next_speaker_pair(
                [candidate("a"), candidate("b")],
                PairSelectionHistory(),
                selection_goal="profile-growth",
                profile_growth_acoustic_pairs=(
                    AcousticPairRanking(
                        fingerprint_a="a",
                        fingerprint_b="b",
                        same_boundary_margin=0.1,
                        centroid_similarity=0.9,
                        report_result_sha256="",
                        report_path="",
                        outcome="different_speaker",
                    ),
                ),
            )

    def test_automation_readiness_prioritizes_profile_reinforcement(self) -> None:
        selected = select_next_speaker_pair(
            [
                candidate("profile-a", profile_ids=frozenset((7,))),
                candidate("profile-b", profile_ids=frozenset((7,))),
                candidate("profile-c", profile_ids=frozenset((7,))),
                candidate("frontier"),
            ],
            PairSelectionHistory(),
            selection_goal="automation-readiness",
        )

        self.assertEqual(
            2,
            len(
                {
                    selected.observation_a.input_fingerprint,
                    selected.observation_b.input_fingerprint,
                }
                & {"profile-a", "profile-b", "profile-c"}
            ),
        )
        self.assertEqual(
            "automation-readiness",
            selected.manifest["selection_goal"],
        )
        self.assertEqual(
            "profile_reinforcement",
            selected.manifest["selection_objective"],
        )

    def test_automation_readiness_prioritizes_association_confirmation(
        self,
    ) -> None:
        selected = select_next_speaker_pair(
            [
                candidate("candidate"),
                candidate("exemplar", profile_ids=frozenset((7,))),
                candidate("profile-a", profile_ids=frozenset((8,))),
                candidate("profile-b", profile_ids=frozenset((8,))),
                candidate("profile-c", profile_ids=frozenset((8,))),
            ],
            PairSelectionHistory(),
            selection_goal="automation-readiness",
            association_confirmation_pairs=(
                self._association_nomination("candidate", "exemplar"),
            ),
        )

        self.assertEqual(
            {"candidate", "exemplar"},
            {
                selected.observation_a.input_fingerprint,
                selected.observation_b.input_fingerprint,
            },
        )
        self.assertEqual(
            "shadow_association_confirmation",
            selected.manifest["selection_objective"],
        )
        provenance = selected.manifest["shadow_association_confirmation"]
        self.assertEqual("review_nomination_only", provenance["role"])
        self.assertFalse(provenance["identity_evidence"])

    def test_association_confirmation_can_grow_automatic_ready_profile(
        self,
    ) -> None:
        selected = select_next_speaker_pair(
            [
                candidate("candidate"),
                candidate("ready", profile_ids=frozenset((7,))),
            ],
            PairSelectionHistory(),
            selection_goal="automation-readiness",
            association_confirmation_pairs=(
                self._association_nomination("candidate", "ready"),
            ),
            automatic_profile_ready_ids=frozenset((7,)),
        )

        self.assertEqual(
            "shadow_association_confirmation",
            selected.manifest["selection_objective"],
        )

    def test_active_machine_assignment_is_reviewed_before_shadow_nomination(
        self,
    ) -> None:
        selected = select_next_speaker_pair(
            [
                candidate("shadow-candidate"),
                candidate("shadow-exemplar", profile_ids=frozenset((7,))),
                candidate("active-candidate"),
                candidate("active-exemplar", profile_ids=frozenset((8,))),
            ],
            PairSelectionHistory(),
            selection_goal="automation-readiness",
            association_confirmation_pairs=(
                self._association_nomination(
                    "shadow-candidate",
                    "shadow-exemplar",
                    profile_id=7,
                    margin=0.20,
                ),
                self._association_nomination(
                    "active-candidate",
                    "active-exemplar",
                    profile_id=8,
                    margin=0.01,
                    provisional_assignment_active=True,
                ),
            ),
        )

        self.assertEqual(
            {"active-candidate", "active-exemplar"},
            {
                selected.observation_a.input_fingerprint,
                selected.observation_b.input_fingerprint,
            },
        )
        self.assertEqual(
            "machine_assignment_validation",
            selected.manifest["selection_objective"],
        )
        provenance = selected.manifest["shadow_association_confirmation"]
        self.assertTrue(provenance["provisional_assignment_active"])
        self.assertFalse(provenance["identity_evidence"])

    def test_stale_association_candidate_is_excluded_after_profile_assignment(
        self,
    ) -> None:
        with self.assertRaisesRegex(
            ValueError,
            "no actionable profile-growth pair remains",
        ):
            select_next_speaker_pair(
                [
                    candidate(
                        "candidate", profile_ids=frozenset((9,))
                    ),
                    candidate("exemplar", profile_ids=frozenset((7,))),
                ],
                PairSelectionHistory(),
                selection_goal="profile-growth",
                association_confirmation_pairs=(
                    self._association_nomination("candidate", "exemplar"),
                ),
            )

    def test_association_exemplar_must_still_belong_to_proposed_profile(
        self,
    ) -> None:
        with self.assertRaisesRegex(
            ValueError,
            "no actionable profile-growth pair remains",
        ):
            select_next_speaker_pair(
                [
                    candidate("candidate"),
                    candidate("exemplar", profile_ids=frozenset((8,))),
                ],
                PairSelectionHistory(),
                selection_goal="profile-growth",
                association_confirmation_pairs=(
                    self._association_nomination("candidate", "exemplar"),
                ),
            )

    def test_automation_readiness_excludes_ready_profiles(self) -> None:
        selected = select_next_speaker_pair(
            [
                candidate("ready-a", profile_ids=frozenset((7,))),
                candidate("ready-b", profile_ids=frozenset((7,))),
                candidate("ready-c", profile_ids=frozenset((7,))),
                candidate("blocked-a", profile_ids=frozenset((8,))),
                candidate("blocked-b", profile_ids=frozenset((8,))),
                candidate("blocked-c", profile_ids=frozenset((8,))),
            ],
            PairSelectionHistory(),
            selection_goal="automation-readiness",
            automatic_profile_ready_ids=frozenset((7,)),
        )

        selected_fingerprints = {
            selected.observation_a.input_fingerprint,
            selected.observation_b.input_fingerprint,
        }
        self.assertTrue(
            selected_fingerprints <= {
                "blocked-a",
                "blocked-b",
                "blocked-c",
            }
        )
        self.assertEqual(
            [7],
            selected.manifest[
                "automatic_profile_ready_ids_excluded_from_reinforcement"
            ],
        )

    def test_automation_readiness_prioritizes_discovery_overlap_resolution(
        self,
    ) -> None:
        selected = select_next_speaker_pair(
            [
                candidate("overlap-left"),
                candidate("overlap-right"),
                candidate("profile-a", profile_ids=frozenset((7,))),
                candidate("profile-b", profile_ids=frozenset((7,))),
                candidate("profile-c", profile_ids=frozenset((7,))),
            ],
            PairSelectionHistory(),
            selection_goal="automation-readiness",
            discovery_resolution_pairs=(
                DiscoveryResolutionPair(
                    fingerprint_a="overlap-left",
                    fingerprint_b="overlap-right",
                    component_ids=("component-a", "component-b"),
                    member_fingerprints=(
                        "bridge-a",
                        "bridge-b",
                        "overlap-left",
                        "overlap-right",
                    ),
                    observations_unlocked=4,
                ),
            ),
        )

        self.assertEqual(
            {"overlap-left", "overlap-right"},
            {
                selected.observation_a.input_fingerprint,
                selected.observation_b.input_fingerprint,
            },
        )
        self.assertEqual(
            "discovery_component_overlap_resolution",
            selected.manifest["selection_objective"],
        )
        self.assertEqual(
            {
                "component_ids": ["component-a", "component-b"],
                "member_fingerprints": [
                    "bridge-a",
                    "bridge-b",
                    "overlap-left",
                    "overlap-right",
                ],
                "observations_unlocked": 4,
            },
            selected.manifest["discovery_resolution"],
        )
        self.assertNotIn(
            "profile_growth_components",
            selected.manifest,
        )

    def test_automation_readiness_prefers_near_same_discovery_frontier(self) -> None:
        selected = select_next_speaker_pair(
            [
                candidate("near-a"),
                candidate("near-b"),
                candidate("staged-a"),
                candidate("staged-b"),
                candidate("overlap-a"),
                candidate("overlap-b"),
            ],
            PairSelectionHistory(),
            selection_goal="automation-readiness",
            discovery_resolution_pairs=(
                DiscoveryResolutionPair(
                    fingerprint_a="overlap-a",
                    fingerprint_b="overlap-b",
                    component_ids=("overlap",),
                    member_fingerprints=("overlap-a", "overlap-b"),
                    observations_unlocked=5,
                ),
                DiscoveryResolutionPair(
                    fingerprint_a="near-a",
                    fingerprint_b="near-b",
                    component_ids=("blocked",),
                    member_fingerprints=("near-a", "near-b"),
                    observations_unlocked=3,
                    resolution_kind="near_same_ambiguous_frontier",
                    same_boundary_distance=0.01,
                ),
                DiscoveryResolutionPair(
                    fingerprint_a="staged-a",
                    fingerprint_b="staged-b",
                    component_ids=("staged",),
                    member_fingerprints=("staged-a", "staged-b"),
                    observations_unlocked=3,
                    resolution_kind="staged_near_same_ambiguous_frontier",
                    same_boundary_distance=0.001,
                    required_review_count=2,
                ),
            ),
        )

        self.assertEqual(
            {"near-a", "near-b"},
            {
                selected.observation_a.input_fingerprint,
                selected.observation_b.input_fingerprint,
            },
        )
        self.assertEqual(
            "discovery_near_same_frontier_review",
            selected.manifest["selection_objective"],
        )
        self.assertEqual(
            "near_same_ambiguous_frontier",
            selected.manifest["discovery_resolution"]["resolution_kind"],
        )

    def test_automation_readiness_selects_staged_bottleneck_before_overlap(
        self,
    ) -> None:
        selected = select_next_speaker_pair(
            [
                candidate("candidate"),
                candidate("seed-a"),
                candidate("seed-b"),
                candidate("overlap-a"),
                candidate("overlap-b"),
            ],
            PairSelectionHistory(),
            selection_goal="automation-readiness",
            discovery_resolution_pairs=(
                DiscoveryResolutionPair(
                    fingerprint_a="overlap-a",
                    fingerprint_b="overlap-b",
                    component_ids=("overlap",),
                    member_fingerprints=("overlap-a", "overlap-b"),
                    observations_unlocked=5,
                ),
                DiscoveryResolutionPair(
                    fingerprint_a="candidate",
                    fingerprint_b="seed-b",
                    component_ids=("seed",),
                    member_fingerprints=("seed-a", "seed-b"),
                    observations_unlocked=3,
                    resolution_kind="staged_near_same_ambiguous_frontier",
                    same_boundary_distance=0.06,
                    seed_fingerprints=("seed-a", "seed-b"),
                    candidate_fingerprint="candidate",
                    companion_pair_fingerprints=("candidate", "seed-a"),
                    required_review_count=2,
                ),
            ),
        )

        self.assertEqual(
            {"candidate", "seed-b"},
            {
                selected.observation_a.input_fingerprint,
                selected.observation_b.input_fingerprint,
            },
        )
        self.assertEqual(
            "discovery_staged_near_same_frontier_review",
            selected.manifest["selection_objective"],
        )
        resolution = selected.manifest["discovery_resolution"]
        self.assertEqual(2, resolution["required_review_count"])
        self.assertEqual(
            ["candidate", "seed-a"],
            resolution["companion_pair_fingerprints"],
        )

    def test_automation_readiness_falls_back_to_profile_growth(self) -> None:
        selected = select_next_speaker_pair(
            [
                candidate(
                    "profile-a", name="alex", profile_ids=frozenset((7,))
                ),
                candidate(
                    "profile-b", name="alex", profile_ids=frozenset((7,))
                ),
                candidate("frontier", name="alex"),
            ],
            PairSelectionHistory(),
            selection_goal="automation-readiness",
        )

        self.assertIn(
            "frontier",
            {
                selected.observation_a.input_fingerprint,
                selected.observation_b.input_fingerprint,
            },
        )
        self.assertEqual(
            "profile_growth_frontier",
            selected.manifest["selection_objective"],
        )

    def test_automation_readiness_uses_cached_acoustic_same_fallback(self) -> None:
        selected = select_next_speaker_pair(
            [candidate("acoustic-a"), candidate("acoustic-b")],
            PairSelectionHistory(),
            selection_goal="automation-readiness",
            profile_growth_acoustic_pairs=(
                AcousticPairRanking(
                    fingerprint_a="acoustic-a",
                    fingerprint_b="acoustic-b",
                    same_boundary_margin=0.04,
                    centroid_similarity=0.95,
                    report_result_sha256="a" * 64,
                    report_path="discovery.json",
                ),
            ),
        )

        self.assertEqual(
            {"acoustic-a", "acoustic-b"},
            {
                selected.observation_a.input_fingerprint,
                selected.observation_b.input_fingerprint,
            },
        )
        self.assertIn(
            "cached_acoustic_same_ranking",
            selected.manifest["reason_codes"],
        )

    def test_profile_growth_withholds_generic_cross_source_pair(self) -> None:
        with self.assertRaisesRegex(
            ValueError,
            "no actionable profile-growth pair remains",
        ):
            select_next_speaker_pair(
                [
                    candidate("a", source_family="church-a"),
                    candidate("b", source_family="church-b"),
                ],
                PairSelectionHistory(),
                selection_goal="profile-growth",
            )

    def test_profile_growth_withholds_conflicting_attributions_without_acoustics(
        self,
    ) -> None:
        with self.assertRaisesRegex(
            ValueError,
            "no actionable profile-growth pair remains",
        ):
            select_next_speaker_pair(
                [candidate("a", name="alex"), candidate("b", name="blair")],
                PairSelectionHistory(),
                selection_goal="profile-growth",
            )

    def test_profile_growth_uses_attribution_from_reviewed_component(self) -> None:
        reviewed_same = frozenset(("anchor-a", "anchor-b"))
        already_tried_direct = frozenset(("anchor-a", "frontier"))
        selected = select_next_speaker_pair(
            [
                candidate("anchor-a", name="alex"),
                candidate("anchor-b"),
                candidate("frontier", name="alex"),
            ],
            PairSelectionHistory(
                excluded_pairs=frozenset(
                    (reviewed_same, already_tried_direct)
                ),
                reviewed_identity_outcomes={
                    reviewed_same: "same_speaker",
                    already_tried_direct: "cannot_determine",
                },
            ),
            selection_goal="profile-growth",
        )

        self.assertEqual(
            {"anchor-b", "frontier"},
            {
                selected.observation_a.input_fingerprint,
                selected.observation_b.input_fingerprint,
            },
        )
        self.assertEqual(
            SelectionStratum.PARTIAL_ATTRIBUTION,
            selected.manifest["selection_stratum"],
        )

    def test_profile_growth_does_not_expand_automatic_ready_profile_by_name(
        self,
    ) -> None:
        with self.assertRaisesRegex(
            ValueError,
            "no actionable profile-growth pair remains",
        ):
            select_next_speaker_pair(
                [
                    candidate(
                        "ready-a", name="alex", profile_ids=frozenset((7,))
                    ),
                    candidate(
                        "ready-b", name="alex", profile_ids=frozenset((7,))
                    ),
                    candidate("frontier", name="alex"),
                ],
                PairSelectionHistory(),
                selection_goal="profile-growth",
                automatic_profile_ready_ids=frozenset((7,)),
            )

    def test_profile_growth_allows_ready_profile_reconciliation_by_name(
        self,
    ) -> None:
        selected = select_next_speaker_pair(
            [
                candidate(
                    "ready", name="alex", profile_ids=frozenset((7,))
                ),
                candidate(
                    "duplicate", name="alex", profile_ids=frozenset((8,))
                ),
            ],
            PairSelectionHistory(),
            selection_goal="profile-growth",
            automatic_profile_ready_ids=frozenset((7,)),
        )

        self.assertEqual(
            "attribution_reconciliation_bridge",
            selected.manifest["selection_objective"],
        )

    def test_automation_readiness_skips_profile_without_bridge_edges(self) -> None:
        ready_edges = {
            frozenset(("ready-a", "ready-b")),
            frozenset(("ready-b", "ready-c")),
            frozenset(("ready-c", "ready-d")),
            frozenset(("ready-d", "ready-a")),
        }
        bridge_edges = {
            frozenset(("bridge-a", "bridge-b")),
            frozenset(("bridge-b", "bridge-c")),
        }
        reviewed_edges = ready_edges | bridge_edges
        selected = select_next_speaker_pair(
            [
                *[
                    candidate(
                        fingerprint,
                        profile_ids=frozenset((7,)),
                    )
                    for fingerprint in (
                        "ready-a",
                        "ready-b",
                        "ready-c",
                        "ready-d",
                    )
                ],
                *[
                    candidate(
                        fingerprint,
                        profile_ids=frozenset((8,)),
                    )
                    for fingerprint in (
                        "bridge-a",
                        "bridge-b",
                        "bridge-c",
                    )
                ],
            ],
            PairSelectionHistory(
                excluded_pairs=frozenset(reviewed_edges),
                reviewed_identity_outcomes={
                    edge: "same_speaker" for edge in reviewed_edges
                },
            ),
            selection_goal="automation-readiness",
        )

        self.assertEqual(
            {"bridge-a", "bridge-c"},
            {
                selected.observation_a.input_fingerprint,
                selected.observation_b.input_fingerprint,
            },
        )
        self.assertEqual(
            "profile_reinforcement",
            selected.manifest["selection_objective"],
        )

    def test_profile_growth_respects_difference_against_any_component_member(
        self,
    ) -> None:
        selected = select_next_speaker_pair(
            [
                candidate(
                    "profile-a",
                    name="alex",
                    profile_ids=frozenset((7,)),
                    different_from=frozenset(("blocked",)),
                ),
                candidate(
                    "profile-b",
                    name="alex",
                    profile_ids=frozenset((7,)),
                ),
                candidate("blocked", name="alex"),
                candidate("seed-a", name="blair"),
                candidate("seed-b", name="blair"),
            ],
            PairSelectionHistory(),
            selection_goal="profile-growth",
        )

        self.assertEqual(
            {"seed-a", "seed-b"},
            {
                selected.observation_a.input_fingerprint,
                selected.observation_b.input_fingerprint,
            },
        )
        self.assertEqual(
            "profile_growth_seed",
            selected.manifest["selection_objective"],
        )

    def test_profile_growth_expands_reviewed_component_before_registry_sync(
        self,
    ) -> None:
        same_pair = frozenset(("anchor-a", "anchor-b"))
        selected = select_next_speaker_pair(
            [
                candidate("anchor-a", name="alex"),
                candidate("anchor-b", name="alex"),
                candidate("frontier", name="alex"),
                candidate("other", name="blair"),
            ],
            PairSelectionHistory(
                excluded_pairs=frozenset((same_pair,)),
                reviewed_pair_outcomes={same_pair: "same_speaker"},
            ),
            selection_goal="profile-growth",
        )

        selected_fingerprints = {
            selected.observation_a.input_fingerprint,
            selected.observation_b.input_fingerprint,
        }
        self.assertIn("frontier", selected_fingerprints)
        self.assertTrue(
            selected_fingerprints & {"anchor-a", "anchor-b"}
        )
        self.assertEqual(
            "profile_growth_frontier",
            selected.manifest["selection_objective"],
        )

    def test_profile_growth_nominates_shared_name_profile_bridge_for_reconciliation(
        self,
    ) -> None:
        selected = select_next_speaker_pair(
            [
                candidate(
                    "profile-a",
                    name="jordan fowler",
                    profile_ids=frozenset((7,)),
                ),
                candidate(
                    "profile-b",
                    name="jordan fowler",
                    profile_ids=frozenset((8,)),
                ),
                candidate("unattributed"),
            ],
            PairSelectionHistory(),
            selection_goal="profile-growth",
        )

        self.assertEqual(
            {"profile-a", "profile-b"},
            {
                selected.observation_a.input_fingerprint,
                selected.observation_b.input_fingerprint,
            },
        )
        self.assertEqual(
            "attribution_reconciliation_bridge",
            selected.manifest["selection_objective"],
        )

    def test_unknown_selection_goal_fails_closed(self) -> None:
        with self.assertRaisesRegex(
            ValueError,
            "selection goal must be one of",
        ):
            select_next_speaker_pair(
                [candidate("a"), candidate("b")],
                PairSelectionHistory(),
                selection_goal="unknown",
            )

    def test_profile_growth_excludes_prior_multiple_or_invalid_observations(
        self,
    ) -> None:
        selected = select_next_speaker_pair(
            [
                candidate(
                    "profile",
                    name="alex",
                    profile_ids=frozenset((7,)),
                ),
                candidate("unqualified", name="alex"),
                candidate("seed-a", name="blair"),
                candidate("seed-b", name="blair"),
            ],
            PairSelectionHistory(
                disfavored_observations={"unqualified": 1},
            ),
            selection_goal="profile-growth",
        )

        self.assertEqual(
            {"seed-a", "seed-b"},
            {
                selected.observation_a.input_fingerprint,
                selected.observation_b.input_fingerprint,
            },
        )

    def test_same_profile_membership_nominates_positive_pair_without_assigning_truth(self) -> None:
        selected = select_next_speaker_pair(
            [
                candidate("profile-a", profile_ids=frozenset((7,))),
                candidate("profile-b", profile_ids=frozenset((7,))),
                candidate("other"),
            ],
            PairSelectionHistory(),
        )

        self.assertEqual(
            {"profile-a", "profile-b"},
            {
                selected.observation_a.input_fingerprint,
                selected.observation_b.input_fingerprint,
            },
        )
        self.assertEqual(
            "reviewed_same_profile_nomination",
            selected.manifest["selection_objective"],
        )
        self.assertNotIn("expected_outcome", selected.manifest)

    def test_different_profiles_do_not_nominate_negative_pair(self) -> None:
        selected = select_next_speaker_pair(
            [
                candidate("a", profile_ids=frozenset((1,))),
                candidate("b", profile_ids=frozenset((2,))),
                candidate("c"),
            ],
            PairSelectionHistory(),
        )

        self.assertNotEqual(
            "reviewed_different_constraint_nomination",
            selected.manifest["selection_objective"],
        )

    def test_explicit_different_constraint_nominates_only_that_pair(self) -> None:
        selected = select_next_speaker_pair(
            [
                candidate("a", different_from=frozenset(("b",))),
                candidate("b"),
                candidate("c"),
            ],
            PairSelectionHistory(),
        )

        self.assertEqual(
            {"a", "b"},
            {
                selected.observation_a.input_fingerprint,
                selected.observation_b.input_fingerprint,
            },
        )
        self.assertEqual(
            "reviewed_different_constraint_nomination",
            selected.manifest["selection_objective"],
        )
        self.assertNotIn("expected_outcome", selected.manifest)

    def test_replay_is_deterministic_regardless_of_input_order(self) -> None:
        candidates = [
            candidate("a", name="alex", day=1),
            candidate("b", name="alex", day=2),
            candidate("c", name="alex", day=3),
        ]
        history = PairSelectionHistory()

        first = select_next_speaker_pair(candidates, history)
        replay = select_next_speaker_pair(list(reversed(candidates)), history)

        self.assertEqual(first, replay)
        self.assertEqual(SelectionStratum.SHARED_ATTRIBUTION, first.manifest["selection_stratum"])

    def test_reviewed_and_drafted_pairs_are_excluded(self) -> None:
        candidates = [candidate("a", name="alex"), candidate("b", name="alex"), candidate("c", name="alex")]
        excluded = frozenset((frozenset(("a", "b")), frozenset(("a", "c"))))

        selected = select_next_speaker_pair(
            candidates,
            PairSelectionHistory(excluded_pairs=excluded),
        )

        self.assertEqual({"b", "c"}, {selected.observation_a.input_fingerprint, selected.observation_b.input_fingerprint})

    def test_history_is_derived_from_drafts_reviews_and_fixtures(self) -> None:
        manifest = {
            "selection_origin": "automatic",
            "selection_goal": "profile-growth",
            "profile_growth_components": [["a"], ["b"]],
            "reason_codes": ["varied_audio_quality"],
        }
        draft = {
            "pair_id": "pair-ab",
            "selection_manifest": manifest,
            "observations": {
                "source_a": {
                    "input_fingerprint": "a",
                    "youtube_video_id": "video-a",
                },
                "source_b": {
                    "input_fingerprint": "b",
                    "youtube_video_id": "video-b",
                },
            },
            "presentation": {
                "A": {"source_key": "source_a"},
                "B": {"source_key": "source_b"},
            },
        }
        review = {
            "pair_id": "pair-ab",
            "selection_manifest": manifest,
            "qualification": {"A": "invalid_audio", "B": "qualified_single_speaker"},
        }
        fixture = {
            "pair_id": "pair-ab",
            "expected_outcome": "same_speaker",
            "evaluation_partition": "validation",
            "selection_manifest": manifest,
            "observations": {
                "a": {
                    "input_fingerprint": "a",
                    "youtube_video_id": "video-a",
                },
                "b": {
                    "input_fingerprint": "b",
                    "youtube_video_id": "video-b",
                },
            },
        }

        history = selection_history_from_artifacts(
            drafts=[draft], reviews=[review], fixtures=[fixture]
        )

        self.assertIn(frozenset(("a", "b")), history.excluded_pairs)
        self.assertEqual({"a": 1, "b": 1}, history.observation_use)
        self.assertEqual({"video-a": 1, "video-b": 1}, history.source_use)
        self.assertEqual({"a": 1}, history.disfavored_observations)
        self.assertEqual({}, history.disfavored_sources)
        self.assertEqual(1, history.automatic_selection_count)
        self.assertEqual(
            "same_speaker",
            history.reviewed_pair_outcomes[frozenset(("a", "b"))],
        )
        self.assertEqual(
            "validation",
            history.reviewed_pair_partitions[frozenset(("a", "b"))],
        )
        self.assertEqual(
            "same_speaker",
            history.reviewed_identity_outcomes[frozenset(("a", "b"))],
        )
        self.assertEqual(
            (frozenset(("a", "b")),),
            history.profile_growth_selections,
        )

    def test_visual_review_event_expands_components_without_an_acoustic_fixture(
        self,
    ) -> None:
        draft = {
            "pair_id": "pair-ab",
            "selection_manifest": {"evaluation_scope": "validation"},
            "observations": {
                "source_a": {
                    "input_fingerprint": "a",
                    "youtube_video_id": "video-a",
                },
                "source_b": {
                    "input_fingerprint": "b",
                    "youtube_video_id": "video-b",
                },
            },
        }
        review = {
            "pair_id": "pair-ab",
            "approval_confirmed": True,
            "fixture_eligible": False,
            "identity_evidence_eligible": True,
            "review_evidence_mode": "audio_plus_visual",
            "qualification": {
                "A": "qualified_single_speaker",
                "B": "qualified_single_speaker",
            },
            "pair_judgment": "same_speaker",
        }

        history = selection_history_from_artifacts(
            drafts=[draft],
            reviews=[review],
            fixtures=[],
        )

        self.assertEqual(
            "same_speaker",
            history.reviewed_identity_outcomes[frozenset(("a", "b"))],
        )
        self.assertNotIn(
            frozenset(("a", "b")),
            history.reviewed_pair_outcomes,
        )

    def test_unapproved_review_does_not_expand_identity_components(self) -> None:
        draft = {
            "pair_id": "pair-ab",
            "observations": {
                "source_a": {"input_fingerprint": "a"},
                "source_b": {"input_fingerprint": "b"},
            },
        }
        review = {
            "pair_id": "pair-ab",
            "approval_confirmed": False,
            "fixture_eligible": False,
            "qualification": {
                "A": "qualified_single_speaker",
                "B": "qualified_single_speaker",
            },
            "pair_judgment": "same_speaker",
        }

        history = selection_history_from_artifacts(
            drafts=[draft],
            reviews=[review],
            fixtures=[],
        )

        self.assertNotIn(
            frozenset(("a", "b")),
            history.reviewed_identity_outcomes,
        )

    def test_drafted_sources_are_deprioritized_even_without_a_fixture(self) -> None:
        candidates = [
            candidate("reviewed-a", name="alex", day=1),
            candidate("reviewed-b", name="alex", day=2),
            candidate("new-a", name="alex", day=3),
            candidate("new-b", name="alex", day=4),
        ]
        draft = {
            "pair_id": "pair-reviewed",
            "observations": {
                "source_a": {
                    "input_fingerprint": "reviewed-a",
                    "youtube_video_id": "video-reviewed-a",
                },
                "source_b": {
                    "input_fingerprint": "reviewed-b",
                    "youtube_video_id": "video-reviewed-b",
                },
            },
        }
        history = selection_history_from_artifacts(
            drafts=[draft], reviews=[], fixtures=[]
        )

        selected = select_next_speaker_pair(candidates, history)

        self.assertEqual(
            {"video-new-a", "video-new-b"},
            {selected.observation_a.video_id, selected.observation_b.video_id},
        )

    def test_reclassification_allows_replacement_observation_pair(self) -> None:
        candidates = [
            candidate("new-fingerprint-a", name="alex", day=1),
            candidate("new-fingerprint-b", name="alex", day=2),
        ]
        candidates[0] = PairCandidateObservation(
            input_fingerprint="new-fingerprint-a",
            video_id="stable-a",
            recording_date=candidates[0].recording_date,
            explicit_attributions=candidates[0].explicit_attributions,
            quality_signature=candidates[0].quality_signature,
        )
        candidates[1] = PairCandidateObservation(
            input_fingerprint="new-fingerprint-b",
            video_id="stable-b",
            recording_date=candidates[1].recording_date,
            explicit_attributions=candidates[1].explicit_attributions,
            quality_signature=candidates[1].quality_signature,
        )

        history = selection_history_from_artifacts(
            drafts=[
                {
                    "pair_id": "obsolete-pair",
                    "observations": {
                        "source_a": {
                            "input_fingerprint": "old-fingerprint-a",
                            "youtube_video_id": "stable-a",
                        },
                        "source_b": {
                            "input_fingerprint": "old-fingerprint-b",
                            "youtube_video_id": "stable-b",
                        },
                    },
                }
            ],
            reviews=[],
            fixtures=[],
        )
        selected = select_next_speaker_pair(candidates, history)

        self.assertEqual(
            {"stable-a", "stable-b"},
            {selected.observation_a.video_id, selected.observation_b.video_id},
        )
        self.assertIn(
            frozenset(("old-fingerprint-a", "old-fingerprint-b")),
            history.excluded_pairs,
        )

    def test_two_unseen_observations_beat_anchor_reuse(self) -> None:
        candidates = [
            candidate("anchor", name="alex", day=1),
            candidate("new-a", name="alex", day=2),
            candidate("new-b", name="alex", day=3),
        ]

        selected = select_next_speaker_pair(
            candidates,
            PairSelectionHistory(observation_use={"anchor": 2}),
        )

        self.assertEqual(
            {"new-a", "new-b"},
            {selected.observation_a.input_fingerprint, selected.observation_b.input_fingerprint},
        )
        self.assertIn("both_observations_unused", selected.manifest["reason_codes"])

    def test_attribution_metadata_selects_stratum_but_never_assigns_truth(self) -> None:
        selected = select_next_speaker_pair(
            [candidate("a", name="alex"), candidate("b", name="alex")],
            PairSelectionHistory(),
        )

        self.assertEqual("shared_attribution", selected.manifest["selection_stratum"])
        self.assertNotIn("expected_outcome", selected.manifest)
        self.assertNotIn("profile", selected.manifest)

    def test_one_sided_name_evidence_is_partial_attribution(self) -> None:
        selected = select_next_speaker_pair(
            [candidate("named", name="alex"), candidate("unknown")],
            PairSelectionHistory(),
        )

        self.assertEqual(
            "partial_attribution",
            selected.manifest["selection_stratum"],
        )

    def test_rotation_advances_and_falls_back_to_available_stratum(self) -> None:
        candidates = [
            candidate("same-a", name="alex"),
            candidate("same-b", name="alex"),
            candidate("different", name="blair"),
            candidate("unknown"),
        ]

        contradicting = select_next_speaker_pair(
            candidates,
            PairSelectionHistory(automatic_selection_count=1),
        )
        partial = select_next_speaker_pair(
            candidates,
            PairSelectionHistory(automatic_selection_count=2),
        )

        self.assertEqual("contradicting_attribution", contradicting.manifest["selection_stratum"])
        self.assertEqual("partial_attribution", partial.manifest["selection_stratum"])

    def test_same_fixture_imbalance_selects_unused_anchor_expansion(self) -> None:
        same_pair = frozenset(("anchor-a", "anchor-b"))
        different_pairs = (
            frozenset(("different-a", "different-b")),
            frozenset(("different-c", "different-d")),
            frozenset(("different-e", "different-f")),
        )
        outcomes = {
            same_pair: "same_speaker",
            **{pair: "different_speaker" for pair in different_pairs},
        }
        partitions = {pair: "validation" for pair in outcomes}
        candidates = [
            candidate(
                "anchor-a",
                name="alex",
                source_family="family-a",
                partition="validation",
            ),
            candidate(
                "anchor-b",
                name="alex",
                source_family="family-a",
                partition="validation",
            ),
            candidate(
                "unused",
                name="alex",
                source_family="family-a",
                partition="validation",
            ),
            candidate(
                "cross-family",
                source_family="family-b",
                partition="validation",
            ),
        ]

        selected = select_next_speaker_pair(
            candidates,
            PairSelectionHistory(
                excluded_pairs=frozenset((same_pair,)),
                observation_use={"anchor-a": 1, "anchor-b": 1},
                reviewed_pair_outcomes=outcomes,
                reviewed_pair_partitions=partitions,
            ),
            evaluation_partition="validation",
        )

        selected_fingerprints = {
            selected.observation_a.input_fingerprint,
            selected.observation_b.input_fingerprint,
        }
        self.assertIn("unused", selected_fingerprints)
        self.assertTrue(selected_fingerprints & same_pair)
        self.assertEqual(
            "same_speaker_anchor_expansion",
            selected.manifest["selection_objective"],
        )
        self.assertIn(
            "reviewed_same_anchor_expansion",
            selected.manifest["reason_codes"],
        )
        self.assertEqual(
            {"same_speaker": 1, "different_speaker": 3},
            selected.manifest["reviewed_outcome_counts"],
        )
        self.assertNotIn("expected_outcome", selected.manifest)
        self.assertNotIn("profile", selected.manifest)

    def test_same_source_family_alone_is_not_a_same_likely_candidate(self) -> None:
        same_pair = frozenset(("anchor-a", "anchor-b"))
        different_pairs = (
            frozenset(("different-a", "different-b")),
            frozenset(("different-c", "different-d")),
            frozenset(("different-e", "different-f")),
        )
        outcomes = {
            same_pair: "same_speaker",
            **{pair: "different_speaker" for pair in different_pairs},
        }
        candidates = [
            candidate(
                "anchor-a",
                name="alex",
                source_family="church",
                partition="validation",
            ),
            candidate(
                "anchor-b",
                name="alex",
                source_family="church",
                partition="validation",
            ),
            candidate(
                "unknown",
                source_family="church",
                partition="validation",
            ),
        ]

        selected = select_next_speaker_pair(
            candidates,
            PairSelectionHistory(
                excluded_pairs=frozenset((same_pair,)),
                reviewed_pair_outcomes=outcomes,
                reviewed_pair_partitions={
                    pair: "validation" for pair in outcomes
                },
            ),
            evaluation_partition="validation",
        )

        self.assertEqual(
            "diversity_rotation",
            selected.manifest["selection_objective"],
        )
        self.assertEqual(
            "partial_attribution",
            selected.manifest["selection_stratum"],
        )
        self.assertIn(
            "same_likely_candidates_exhausted",
            selected.manifest["reason_codes"],
        )

    def test_anchor_expansion_respects_different_constraint_against_either_anchor(
        self,
    ) -> None:
        same_pair = frozenset(("anchor-a", "anchor-b"))
        blocked_pair = frozenset(("anchor-a", "blocked"))
        other_different_pairs = (
            frozenset(("different-a", "different-b")),
            frozenset(("different-c", "different-d")),
            frozenset(("different-e", "different-f")),
        )
        outcomes = {
            same_pair: "same_speaker",
            blocked_pair: "different_speaker",
            **{pair: "different_speaker" for pair in other_different_pairs},
        }
        candidates = [
            candidate(
                fingerprint,
                name="alex",
                source_family="family-a",
                partition="validation",
            )
            for fingerprint in ("anchor-a", "anchor-b", "blocked", "available")
        ]

        selected = select_next_speaker_pair(
            candidates,
            PairSelectionHistory(
                excluded_pairs=frozenset((same_pair, blocked_pair)),
                reviewed_pair_outcomes=outcomes,
                reviewed_pair_partitions={
                    pair: "validation" for pair in outcomes
                },
            ),
            evaluation_partition="validation",
        )

        selected_fingerprints = {
            selected.observation_a.input_fingerprint,
            selected.observation_b.input_fingerprint,
        }
        self.assertIn("available", selected_fingerprints)
        self.assertNotIn("blocked", selected_fingerprints)

    def test_anchor_expansion_blocks_recomparison_across_overlapping_same_pairs(
        self,
    ) -> None:
        same_ab = frozenset(("anchor-a", "anchor-b"))
        same_bc = frozenset(("anchor-b", "anchor-c"))
        blocked_pair = frozenset(("anchor-a", "blocked"))
        other_different_pairs = (
            frozenset(("different-a", "different-b")),
            frozenset(("different-c", "different-d")),
            frozenset(("different-e", "different-f")),
        )
        outcomes = {
            same_ab: "same_speaker",
            same_bc: "same_speaker",
            blocked_pair: "different_speaker",
            **{pair: "different_speaker" for pair in other_different_pairs},
        }
        candidates = [
            candidate(
                fingerprint,
                name="alex",
                source_family="family-a",
                partition="validation",
            )
            for fingerprint in (
                "anchor-a",
                "anchor-b",
                "anchor-c",
                "blocked",
                "available",
            )
        ]

        selected = select_next_speaker_pair(
            candidates,
            PairSelectionHistory(
                excluded_pairs=frozenset((same_ab, same_bc, blocked_pair)),
                observation_use={
                    "anchor-a": 1,
                    "anchor-b": 2,
                    "anchor-c": 1,
                },
                reviewed_pair_outcomes=outcomes,
                reviewed_pair_partitions={
                    pair: "validation" for pair in outcomes
                },
            ),
            evaluation_partition="validation",
        )

        selected_fingerprints = {
            selected.observation_a.input_fingerprint,
            selected.observation_b.input_fingerprint,
        }
        self.assertIn("available", selected_fingerprints)
        self.assertNotIn("blocked", selected_fingerprints)
        self.assertEqual(
            ["anchor-a", "anchor-b", "anchor-c"],
            selected.manifest["anchor_component_fingerprints"],
        )

    def test_anchor_expansion_does_not_activate_for_other_partition_imbalance(
        self,
    ) -> None:
        same_pair = frozenset(("anchor-a", "anchor-b"))
        held_out_different_pairs = (
            frozenset(("held-a", "held-b")),
            frozenset(("held-c", "held-d")),
            frozenset(("held-e", "held-f")),
        )
        outcomes = {
            same_pair: "same_speaker",
            **{pair: "different_speaker" for pair in held_out_different_pairs},
        }
        partitions = {
            same_pair: "validation",
            **{pair: "held_out" for pair in held_out_different_pairs},
        }
        candidates = [
            candidate(
                "anchor-a",
                source_family="family-a",
                partition="validation",
            ),
            candidate(
                "anchor-b",
                source_family="family-a",
                partition="validation",
            ),
            candidate(
                "unused",
                source_family="family-a",
                partition="validation",
            ),
        ]

        selected = select_next_speaker_pair(
            candidates,
            PairSelectionHistory(
                excluded_pairs=frozenset((same_pair,)),
                reviewed_pair_outcomes=outcomes,
                reviewed_pair_partitions=partitions,
            ),
            evaluation_partition="validation",
        )

        self.assertEqual(
            "diversity_rotation",
            selected.manifest["selection_objective"],
        )
        self.assertEqual(
            {"same_speaker": 1, "different_speaker": 0},
            selected.manifest["reviewed_outcome_counts"],
        )

    def test_source_relation_rotates_between_same_and_cross_family_pairs(self) -> None:
        candidates = [
            candidate(
                "same-a",
                name="alex",
                source_family="family-a",
                partition="development",
            ),
            candidate(
                "same-b",
                name="alex",
                source_family="family-a",
                partition="development",
            ),
            candidate(
                "cross",
                name="alex",
                source_family="family-b",
                partition="development",
            ),
        ]

        same = select_next_speaker_pair(candidates, PairSelectionHistory())
        cross = select_next_speaker_pair(
            candidates,
            PairSelectionHistory(automatic_selection_count=1),
        )

        self.assertEqual(
            SourceRelation.SAME_SOURCE_FAMILY,
            same.manifest["source_relation"],
        )
        self.assertEqual(
            SourceRelation.CROSS_SOURCE_FAMILY,
            cross.manifest["source_relation"],
        )
        self.assertNotIn("expected_outcome", same.manifest)

    def test_cross_family_pairs_never_cross_evaluation_partitions(self) -> None:
        candidates = [
            candidate(
                "dev-a",
                name="alex",
                source_family="family-a",
                partition="development",
            ),
            candidate(
                "held",
                name="alex",
                source_family="family-b",
                partition="held_out",
            ),
            candidate(
                "dev-b",
                name="alex",
                source_family="family-c",
                partition="development",
            ),
        ]

        selected = select_next_speaker_pair(
            candidates,
            PairSelectionHistory(automatic_selection_count=1),
        )

        self.assertEqual(
            {"dev-a", "dev-b"},
            {
                selected.observation_a.input_fingerprint,
                selected.observation_b.input_fingerprint,
            },
        )
        self.assertEqual(
            {"development"},
            set(selected.manifest["evaluation_partitions"].values()),
        )

    def test_explicit_evaluation_scope_only_nominates_from_that_partition(self) -> None:
        candidates = [
            candidate(
                "dev",
                name="alex",
                source_family="development-family",
                partition="development",
            ),
            candidate(
                "validation-a",
                name="alex",
                source_family="validation-family-a",
                partition="validation",
            ),
            candidate(
                "validation-b",
                name="alex",
                source_family="validation-family-b",
                partition="validation",
            ),
            candidate(
                "held",
                name="alex",
                source_family="held-family",
                partition="held_out",
            ),
        ]

        selected = select_next_speaker_pair(
            candidates,
            PairSelectionHistory(automatic_selection_count=1),
            evaluation_partition="validation",
        )

        self.assertEqual(
            {"validation-a", "validation-b"},
            {
                selected.observation_a.input_fingerprint,
                selected.observation_b.input_fingerprint,
            },
        )
        self.assertEqual("validation", selected.manifest["evaluation_scope"])
        self.assertEqual(
            {"validation"},
            set(selected.manifest["evaluation_partitions"].values()),
        )

    def test_explicit_evaluation_scope_requires_two_candidates(self) -> None:
        with self.assertRaisesRegex(ValueError, "fewer than two.*validation"):
            select_next_speaker_pair(
                [
                    candidate(
                        "validation-only",
                        source_family="validation-family",
                        partition="validation",
                    ),
                    candidate(
                        "development",
                        source_family="development-family",
                        partition="development",
                    ),
                ],
                PairSelectionHistory(),
                evaluation_partition="validation",
            )

    def test_underrepresented_source_family_wins_within_relation(self) -> None:
        candidates = [
            candidate(
                "used-a",
                name="alex",
                source_family="used-family",
                partition="development",
            ),
            candidate(
                "used-b",
                name="alex",
                source_family="used-family",
                partition="development",
            ),
            candidate(
                "new-a",
                name="alex",
                source_family="new-family",
                partition="development",
            ),
            candidate(
                "new-b",
                name="alex",
                source_family="new-family",
                partition="development",
            ),
        ]

        selected = select_next_speaker_pair(
            candidates,
            PairSelectionHistory(source_family_use={"used-family": 4}),
        )

        self.assertEqual(
            {"new-a", "new-b"},
            {
                selected.observation_a.input_fingerprint,
                selected.observation_b.input_fingerprint,
            },
        )
        self.assertIn(
            "source_families_unrepresented",
            selected.manifest["reason_codes"],
        )

    def test_known_quality_failure_outranks_source_family_coverage(self) -> None:
        candidates = [
            candidate(
                "clean-a",
                name="alex",
                source_family="represented-family",
                partition="development",
            ),
            candidate(
                "clean-b",
                name="alex",
                source_family="represented-family",
                partition="development",
            ),
            candidate(
                "failed-a",
                name="alex",
                source_family="unrepresented-family",
                partition="development",
            ),
            candidate(
                "failed-b",
                name="alex",
                source_family="unrepresented-family",
                partition="development",
            ),
        ]

        selected = select_next_speaker_pair(
            candidates,
            PairSelectionHistory(
                source_family_use={"represented-family": 4},
                disfavored_observations={"failed-a": 1},
            ),
        )

        self.assertEqual(
            {"clean-a", "clean-b"},
            {
                selected.observation_a.input_fingerprint,
                selected.observation_b.input_fingerprint,
            },
        )

    def test_source_context_history_counts_each_pair_once(self) -> None:
        manifest = {
            "selection_origin": "automatic",
            "source_relation": "cross_source_family",
            "source_family_ids": {"a": "family-a", "b": "family-b"},
        }
        draft = {
            "pair_id": "pair-ab",
            "selection_manifest": manifest,
            "observations": {},
        }
        fixture = {
            "pair_id": "pair-ab",
            "selection_manifest": manifest,
            "observations": {},
        }

        history = selection_history_from_artifacts(
            drafts=[draft],
            reviews=[],
            fixtures=[fixture],
        )

        self.assertEqual(
            {"family-a": 1, "family-b": 1},
            history.source_family_use,
        )
        self.assertEqual(
            {"cross_source_family": 1},
            history.source_relation_counts,
        )


if __name__ == "__main__":
    unittest.main()
