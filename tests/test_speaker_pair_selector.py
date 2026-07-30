from __future__ import annotations

from datetime import datetime, timezone
import unittest

from pastor_transcript_extractor.speaker_pair_selector import (
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
    )


class SpeakerPairSelectorTests(unittest.TestCase):
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

    def test_automation_readiness_falls_back_to_profile_growth(self) -> None:
        selected = select_next_speaker_pair(
            [
                candidate("profile-a", profile_ids=frozenset((7,))),
                candidate("profile-b", profile_ids=frozenset((7,))),
                candidate("frontier"),
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
        self.assertIn(
            frozenset(("video-a", "video-b")), history.excluded_source_pairs
        )
        self.assertEqual({"a": 1, "b": 1}, history.observation_use)
        self.assertEqual({"video-a": 1, "video-b": 1}, history.source_use)
        self.assertEqual({"a": 1}, history.disfavored_observations)
        self.assertEqual({"video-a": 1}, history.disfavored_sources)
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

    def test_reclassification_does_not_bypass_source_pair_exclusion(self) -> None:
        candidates = [
            candidate("new-fingerprint-a", name="alex", day=1),
            candidate("new-fingerprint-b", name="alex", day=2),
            candidate("other", name="alex", day=3),
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

        selected = select_next_speaker_pair(
            candidates,
            PairSelectionHistory(
                excluded_source_pairs=frozenset((frozenset(("stable-a", "stable-b")),))
            ),
        )

        self.assertNotEqual(
            {"stable-a", "stable-b"},
            {selected.observation_a.video_id, selected.observation_b.video_id},
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
