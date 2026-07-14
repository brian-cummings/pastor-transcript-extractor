from __future__ import annotations

import unittest

from pastor_transcript_extractor.disposition import build_final_disposition


class FinalDispositionTests(unittest.TestCase):
    def test_high_confidence_window_is_accepted(self) -> None:
        result = build_final_disposition(
            {"confidence_tier": "high", "retained_segment_indexes": [1, 2]},
            {"start_seconds": 60.0, "end_seconds": 600.0, "source": "hybrid_llm"},
        )

        self.assertEqual("accepted_sermon", result["status"])

    def test_medium_confidence_window_requires_review(self) -> None:
        result = build_final_disposition(
            {"confidence_tier": "medium", "retained_segment_indexes": [1, 2]},
            {"start_seconds": 60.0, "end_seconds": 600.0, "source": "hybrid_llm"},
        )

        self.assertEqual("review_required", result["status"])

    def test_low_confidence_candidate_without_effective_window_requires_review(self) -> None:
        result = build_final_disposition(
            {"confidence_tier": "low", "retained_segment_indexes": [1, 2]},
            {"start_seconds": None, "end_seconds": None, "included_segment_indexes": []},
        )

        self.assertEqual("review_required", result["status"])
        self.assertTrue(result["diagnostic_candidate_present"])
        self.assertFalse(result["effective_window_present"])

    def test_empty_candidate_without_effective_window_is_rejected(self) -> None:
        result = build_final_disposition(
            {"confidence_tier": "low", "retained_segment_indexes": []},
            {"start_seconds": None, "end_seconds": None, "included_segment_indexes": []},
        )

        self.assertEqual("rejected_no_sermon", result["status"])

    def test_manual_override_remains_authoritative(self) -> None:
        result = build_final_disposition(
            {"confidence_tier": "low", "retained_segment_indexes": []},
            {"start_seconds": 60.0, "end_seconds": 600.0, "source": "override"},
            guest_speaker_suspected=True,
        )

        self.assertEqual("accepted_sermon", result["status"])

    def test_ambiguous_speakers_can_be_rejected_without_erasing_candidate(self) -> None:
        result = build_final_disposition(
            {"confidence_tier": "high", "retained_segment_indexes": [1, 2]},
            {"start_seconds": 60.0, "end_seconds": 600.0, "source": "hybrid_llm"},
            ambiguous_speakers=True,
        )

        self.assertEqual("rejected_ambiguous_speakers", result["status"])
        self.assertTrue(result["diagnostic_candidate_present"])


if __name__ == "__main__":
    unittest.main()
