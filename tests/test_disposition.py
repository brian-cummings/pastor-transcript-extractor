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

    def test_manual_override_is_authoritative_only_for_content_boundaries(self) -> None:
        result = build_final_disposition(
            {"confidence_tier": "low", "retained_segment_indexes": []},
            {"start_seconds": 60.0, "end_seconds": 600.0, "source": "override"},
            guest_speaker_suspected=True,
        )

        self.assertEqual("review_required", result["status"])
        self.assertIn("manual_override_applies_to_content_boundary_only", result["reason_codes"])
        self.assertTrue(result["manual_content_override_present"])

    def test_manual_content_override_can_accept_when_no_identity_concern_exists(self) -> None:
        result = build_final_disposition(
            {"confidence_tier": "low", "retained_segment_indexes": []},
            {"start_seconds": 60.0, "end_seconds": 600.0, "source": "override"},
        )

        self.assertEqual("accepted_sermon", result["status"])
        self.assertEqual(["manual_content_boundary_override_is_authoritative"], result["reason_codes"])

    def test_ambiguous_speakers_can_be_rejected_without_erasing_candidate(self) -> None:
        result = build_final_disposition(
            {"confidence_tier": "high", "retained_segment_indexes": [1, 2]},
            {"start_seconds": 60.0, "end_seconds": 600.0, "source": "hybrid_llm"},
            ambiguous_speakers=True,
        )

        self.assertEqual("rejected_ambiguous_speakers", result["status"])
        self.assertTrue(result["diagnostic_candidate_present"])

    def test_recording_verifier_can_resolve_medium_confidence_candidate(self) -> None:
        result = build_final_disposition(
            {"confidence_tier": "medium", "retained_segment_indexes": [1, 2]},
            {"start_seconds": 60.0, "end_seconds": 600.0, "source": "hybrid_llm"},
            recording_verification={
                "policy_version": "policy",
                "decision": "worship_service_sermon",
                "predicted_outcome": "sermon",
            },
        )

        self.assertEqual("accepted_sermon", result["status"])
        self.assertEqual(
            ["recording_verifier_confirmed_worship_service_sermon"],
            result["reason_codes"],
        )

    def test_recording_verifier_rejects_program_without_erasing_candidate(self) -> None:
        result = build_final_disposition(
            {"confidence_tier": "medium", "retained_segment_indexes": [1, 2]},
            {"start_seconds": 60.0, "end_seconds": 600.0, "source": "hybrid_llm"},
            recording_verification={
                "policy_version": "policy",
                "decision": "multi_speaker_or_student_program",
                "predicted_outcome": "no_sermon",
            },
        )

        self.assertEqual("rejected_ambiguous_speakers", result["status"])
        self.assertTrue(result["diagnostic_candidate_present"])

    def test_guest_speaker_safeguard_precedes_recording_verifier(self) -> None:
        result = build_final_disposition(
            {"confidence_tier": "medium", "retained_segment_indexes": [1, 2]},
            {"start_seconds": 60.0, "end_seconds": 600.0, "source": "hybrid_llm"},
            guest_speaker_suspected=True,
            recording_verification={
                "decision": "worship_service_sermon",
                "predicted_outcome": "sermon",
            },
        )

        self.assertEqual("review_required", result["status"])
        self.assertEqual(["guest_speaker_suspected"], result["reason_codes"])

    def test_verified_no_sermon_can_reject_despite_guest_signal(self) -> None:
        result = build_final_disposition(
            {"confidence_tier": "medium", "retained_segment_indexes": [1, 2]},
            {"start_seconds": 60.0, "end_seconds": 600.0, "source": "hybrid_llm"},
            guest_speaker_suspected=True,
            recording_verification={
                "decision": "religious_education_or_bible_class",
                "predicted_outcome": "no_sermon",
            },
        )

        self.assertEqual("rejected_no_sermon", result["status"])


if __name__ == "__main__":
    unittest.main()
