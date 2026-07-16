from __future__ import annotations

from datetime import datetime, timezone
import unittest

from pastor_transcript_extractor.speaker_pair_selector import (
    PairCandidateObservation,
    PairSelectionHistory,
    SelectionStratum,
    select_next_speaker_pair,
    selection_history_from_artifacts,
)


def candidate(
    fingerprint: str,
    *,
    name: str | None = None,
    day: int = 1,
) -> PairCandidateObservation:
    return PairCandidateObservation(
        input_fingerprint=fingerprint,
        video_id=f"video-{fingerprint}",
        recording_date=datetime(2026, 7, day, tzinfo=timezone.utc),
        explicit_attributions=frozenset((name,)) if name else frozenset(),
        quality_signature=("wav", 16_000, 1),
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
                "source_a": {"input_fingerprint": "a"},
                "source_b": {"input_fingerprint": "b"},
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
                "a": {"input_fingerprint": "a"},
                "b": {"input_fingerprint": "b"},
            },
        }

        history = selection_history_from_artifacts(
            drafts=[draft], reviews=[review], fixtures=[fixture]
        )

        self.assertIn(frozenset(("a", "b")), history.excluded_pairs)
        self.assertEqual({"a": 1, "b": 1}, history.observation_use)
        self.assertEqual({"a": 1}, history.disfavored_observations)
        self.assertEqual(1, history.automatic_selection_count)

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


if __name__ == "__main__":
    unittest.main()
