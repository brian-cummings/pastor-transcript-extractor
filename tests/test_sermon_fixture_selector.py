from __future__ import annotations

from datetime import datetime, timezone
import unittest

from pastor_transcript_extractor.sermon_fixture_selector import (
    SermonFixtureCandidate,
    SermonSelectionHistory,
    select_next_sermon_fixture,
    sermon_candidate_from_proposal,
)


def candidate(
    video_id: str,
    *,
    has_candidate: bool = True,
    suspicious: bool = False,
    confidence: str | None = "high",
    group: str = "pastor:1",
    signals: tuple[str, ...] = (),
) -> SermonFixtureCandidate:
    return SermonFixtureCandidate(
        video_id=video_id,
        corpus_group=group,
        recording_date=datetime(2026, 7, int(video_id[-1]) if video_id[-1].isdigit() else 1, tzinfo=timezone.utc),
        duration_seconds=3600.0,
        proposal_source="adaptive_llm_v3",
        confidence_tier=confidence,
        has_candidate=has_candidate,
        suspicious_boundary=suspicious,
        has_warnings=False,
        source_family_id=group,
        recording_condition_group_id=f"condition:{group}",
        nomination_signals=signals,
    )


class SermonFixtureSelectorTests(unittest.TestCase):
    def test_selection_replays_deterministically_and_excludes_drafts(self) -> None:
        candidates = [candidate("video1", suspicious=True), candidate("video2", suspicious=True)]
        history = SermonSelectionHistory(excluded_video_ids=frozenset(("video1",)))

        first = select_next_sermon_fixture(candidates, history)
        replay = select_next_sermon_fixture(list(reversed(candidates)), history)

        self.assertEqual(first, replay)
        self.assertEqual("video2", first.candidate.video_id)
        self.assertEqual("boundary_risk", first.manifest["selection_stratum"])

    def test_rotation_covers_no_candidate_and_standard_candidates(self) -> None:
        candidates = [
            candidate("video1", suspicious=True),
            candidate("video2", has_candidate=False, confidence="low"),
            candidate("video3"),
        ]

        no_candidate = select_next_sermon_fixture(
            candidates, SermonSelectionHistory(automatic_selection_count=1)
        )
        standard = select_next_sermon_fixture(
            candidates, SermonSelectionHistory(automatic_selection_count=2)
        )

        self.assertEqual("no_candidate", no_candidate.manifest["selection_stratum"])
        self.assertEqual("standard_candidate", standard.manifest["selection_stratum"])

    def test_proposal_metadata_is_a_hint_and_never_expected_truth(self) -> None:
        parsed = sermon_candidate_from_proposal(
            video_id="abc",
            corpus_group="pastor:1",
            recording_date=None,
            duration_seconds=90.0,
            proposal={
                "segments": [{"start_seconds": 0, "end_seconds": 90, "text": "music"}],
                "classification": {
                    "method": "adaptive_llm_v3",
                    "retained_segment_indexes": [],
                    "confidence_tier": "low",
                    "warnings": ["no plausible candidate"],
                },
                "sermon_window": {"start_seconds": None, "end_seconds": None},
            },
        )
        selection = select_next_sermon_fixture([parsed], SermonSelectionHistory())

        self.assertEqual("no_candidate", parsed.stratum)
        self.assertNotIn("expected_outcome", selection.manifest)
        self.assertNotIn("expected_spans", selection.manifest)

    def test_underrepresented_source_family_has_priority_within_stratum(self) -> None:
        selected = select_next_sermon_fixture(
            [candidate("video1", suspicious=True, group="pastor:used"), candidate("video2", suspicious=True, group="pastor:new")],
            SermonSelectionHistory(corpus_group_use={"pastor:used": 4}),
        )

        self.assertEqual("video2", selected.candidate.video_id)
        self.assertIn("source_family_unrepresented", selected.manifest["reason_codes"])

    def test_unrepresented_diagnostic_signal_has_priority_within_family(self) -> None:
        selected = select_next_sermon_fixture(
            [
                candidate("video1", suspicious=True),
                candidate("video2", suspicious=True, signals=("rule_llm_disagreement",)),
            ],
            SermonSelectionHistory(),
        )

        self.assertEqual("video2", selected.candidate.video_id)
        self.assertIn(
            "signal_rule_llm_disagreement_unrepresented",
            selected.manifest["reason_codes"],
        )

    def test_extracts_objective_information_gain_signals(self) -> None:
        parsed = sermon_candidate_from_proposal(
            video_id="diagnostic",
            corpus_group="family-a",
            recording_date=None,
            duration_seconds=100.0,
            proposal={
                "segments": [{"start_seconds": 0, "end_seconds": 20, "text": "text"}],
                "classification": {
                    "method": "adaptive_llm_v3",
                    "retained_segment_indexes": [0],
                    "confidence_tier": "medium",
                    "confidence_reasons": [
                        {"code": "rule_llm_agreement", "value": 0.2}
                    ],
                    "blocks": [
                        {"normalization": {"deduplication_ratio": 0.8}}
                    ],
                    "search": {
                        "selected_rank": 1,
                        "discovery": {"rescue_triggered": True},
                        "candidates": [
                            {
                                "rank": 1,
                                "source": "rule_fallback",
                                "start_seconds": 0,
                                "end_seconds": 90,
                                "score": 100,
                                "boundary_recovery": {
                                    "start": {"probed_block_ids": [1, 2, 3]},
                                    "end": {"probed_block_ids": [4, 5, 6]},
                                    "discarded_component_block_ids": [[7]],
                                },
                            },
                            {
                                "rank": 2,
                                "source": "coarse_llm",
                                "start_seconds": 10,
                                "end_seconds": 80,
                                "score": 95,
                            },
                        ],
                    },
                },
            },
        )

        self.assertEqual(
            {
                "candidate_near_recording_boundary",
                "extreme_caption_deduplication",
                "likelihood_rescue_activation",
                "long_continuity_expansion",
                "low_transcript_coverage",
                "multiple_similarly_ranked_candidates",
                "retained_block_fragmentation",
                "rule_fallback_activation",
                "rule_llm_disagreement",
            },
            set(parsed.nomination_signals),
        )


if __name__ == "__main__":
    unittest.main()
