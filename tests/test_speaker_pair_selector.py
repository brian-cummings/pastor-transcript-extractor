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
) -> PairCandidateObservation:
    return PairCandidateObservation(
        input_fingerprint=fingerprint,
        video_id=f"video-{fingerprint}",
        recording_date=datetime(2026, 7, day, tzinfo=timezone.utc),
        explicit_attributions=frozenset((name,)) if name else frozenset(),
        quality_signature=("wav", 16_000, 1),
        source_family_id=source_family,
        evaluation_partition=partition,
    )


class SpeakerPairSelectorTests(unittest.TestCase):
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
        manifest = {"selection_origin": "automatic", "reason_codes": ["varied_audio_quality"]}
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
        unattributed = select_next_speaker_pair(
            candidates,
            PairSelectionHistory(automatic_selection_count=2),
        )

        self.assertEqual("contradicting_attribution", contradicting.manifest["selection_stratum"])
        self.assertEqual("unattributed", unattributed.manifest["selection_stratum"])

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
