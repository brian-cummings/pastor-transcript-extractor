from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pastor_transcript_extractor.local_llm import LocalLlmResponse
from pastor_transcript_extractor.recording_verifier import (
    RecordingVerifierCache,
    RecordingVerifierCase,
    build_evidence_packet,
    run_diagnostics,
    title_program_decision,
    title_supports_worship_service,
    validate_partition_access,
    validate_verdict,
    verify_recording,
    verifier_prompt,
)


def proposed() -> dict[str, object]:
    return {
        "classification": {
            "search": {
                "selected_rank": 1,
                "candidates": [
                    {"rank": 1, "start_seconds": 150.0, "end_seconds": 450.0}
                ],
            }
        },
        "segments": [
            {
                "start_seconds": float(index * 30),
                "end_seconds": float((index + 1) * 30),
                "text": f"segment {index}",
            }
            for index in range(20)
        ],
    }


class FakeVerifierClient:
    model = "fixture-verifier"

    def __init__(
        self,
        decision: str,
        confidence: str = "high",
        reason_codes: list[str] | None = None,
    ) -> None:
        self.decision = decision
        self.confidence = confidence
        self.reason_codes = reason_codes or [
            "single_sustained_message",
            "sustained_biblical_exposition",
        ]
        self.calls = 0

    def generate_json(
        self, prompt: str, schema: dict[str, object]
    ) -> LocalLlmResponse:
        del prompt, schema
        self.calls += 1
        content = {
            "decision": self.decision,
            "confidence": self.confidence,
            "reason_codes": self.reason_codes,
        }
        return LocalLlmResponse(content, str(content), self.model)


class RecordingVerifierDiagnosticTests(unittest.TestCase):
    def test_evidence_packet_samples_recording_and_selected_candidate(self) -> None:
        packet = build_evidence_packet("Fixture title", proposed())

        self.assertIn("RECORDING TITLE:\nFixture title", packet)
        self.assertIn("RECORDING OPENING", packet)
        self.assertIn("CANDIDATE OPENING (around 150s)", packet)
        self.assertIn("CANDIDATE MIDDLE (around 300s)", packet)
        self.assertIn("CANDIDATE END (around 450s)", packet)

    def test_prompt_distinguishes_one_sermon_from_program_structure(self) -> None:
        case = RecordingVerifierCase(
            "video",
            "Fixture",
            "sermon",
            "development",
            "evidence",
        )

        prompt = verifier_prompt(case)

        self.assertIn("one sustained Christian worship-service sermon", prompt)
        self.assertIn("sequence of short talks or sermonettes", prompt)
        self.assertIn("title is useful context but may be stale or misleading", prompt)
        self.assertIn("Bible Class or Sabbath School title is religious education", prompt)

    def test_verdict_requires_unique_grounded_sermon_reason(self) -> None:
        with self.assertRaisesRegex(ValueError, "unsupported structured evidence"):
            validate_verdict(
                {
                    "decision": "worship_service_sermon",
                    "confidence": "high",
                    "reason_codes": [
                        "sermon_title_or_introduction",
                        "sermon_title_or_introduction",
                    ],
                }
            )
    def test_title_gate_protects_explicit_classes_but_not_combined_service(self) -> None:
        self.assertEqual(
            "religious_education_or_bible_class",
            title_program_decision("Pastor's Bible Class - June 6"),
        )
        self.assertEqual(
            "religious_education_or_bible_class",
            title_program_decision("Apison Adult Sabbath School"),
        )
        self.assertIsNone(
            title_program_decision("July 4 Sabbath School & Church")
        )
        self.assertEqual(
            "non_sermon_event",
            title_program_decision("DACS Kindergarten Graduation"),
        )
        self.assertEqual(
            "multi_speaker_or_student_program",
            title_program_decision(
                "AAA Super Sabbath - Chaplain & Students - Impact for Eternity"
            ),
        )
        self.assertTrue(title_supports_worship_service("July 4 Sabbath Service"))
        self.assertFalse(title_supports_worship_service("In Their Own Eyes"))

    def test_held_out_partition_requires_frozen_policy_confirmation(self) -> None:
        validate_partition_access("development", confirm_frozen_policy=False)
        validate_partition_access("legacy", confirm_frozen_policy=False)
        with self.assertRaisesRegex(ValueError, "requires confirmation"):
            validate_partition_access("held_out", confirm_frozen_policy=False)
        validate_partition_access("held_out", confirm_frozen_policy=True)
        with self.assertRaisesRegex(ValueError, "sustained-message evidence"):
            validate_verdict(
                {
                    "decision": "worship_service_sermon",
                    "confidence": "high",
                    "reason_codes": ["sermon_title_or_introduction"],
                }
            )

    def test_diagnostic_records_accuracy_and_reuses_cache(self) -> None:
        case = RecordingVerifierCase(
            "video",
            "Fixture",
            "sermon",
            "development",
            "evidence",
        )
        client = FakeVerifierClient("worship_service_sermon")
        with tempfile.TemporaryDirectory() as tmp:
            cache = RecordingVerifierCache(Path(tmp))
            first = run_diagnostics(
                client,
                model_digest="digest",
                cases=[case],
                cache=cache,
            )
            second = run_diagnostics(
                client,
                model_digest="digest",
                cases=[case],
                cache=cache,
            )

        self.assertEqual(1, first["correct_count"])
        self.assertEqual(1, first["high_confidence_correct_count"])
        self.assertEqual(1, first["cache_misses"])
        self.assertEqual(1, second["cache_hits"])
        self.assertEqual(1, client.calls)

    def test_title_gate_resolves_without_calling_model(self) -> None:
        case = RecordingVerifierCase(
            "video",
            "Pastor's Bible Class",
            "no_sermon",
            "development",
            "evidence",
        )
        client = FakeVerifierClient("worship_service_sermon")
        with tempfile.TemporaryDirectory() as tmp:
            result = run_diagnostics(
                client,
                model_digest="digest",
                cases=[case],
                cache=RecordingVerifierCache(Path(tmp)),
            )

        self.assertEqual(1, result["correct_count"])
        self.assertEqual(1, result["title_gate_decisions"])
        self.assertEqual(0, result["cache_misses"])
        self.assertEqual(0, client.calls)

    def test_production_verifier_persists_versioned_resolved_artifact(self) -> None:
        client = FakeVerifierClient("worship_service_sermon")
        with tempfile.TemporaryDirectory() as tmp:
            result = verify_recording(
                title="Sabbath Worship Service",
                proposed={
                    "youtube_video_id": "video",
                    **proposed(),
                },
                client=client,
                model_digest="digest",
                cache_dir=Path(tmp),
            )

        self.assertEqual("sermon", result["predicted_outcome"])
        self.assertEqual("llm_recording_verifier", result["source"])
        self.assertEqual("recording-sermon-verifier-v4", result["prompt_version"])
        self.assertEqual("recording-sermon-verifier-policy-v5", result["policy_version"])
        self.assertEqual(
            ["sustained_biblical_exposition"],
            result["sermon_specific_reason_codes"],
        )

    def test_single_sustained_message_non_sermon_event_requires_review(self) -> None:
        self._assert_single_sustained_shape_requires_review(
            "Community religious event and extended keynote speech"
        )

    def test_single_sustained_message_instructional_program_requires_review(self) -> None:
        self._assert_single_sustained_shape_requires_review(
            "Religious instructional program"
        )

    def test_single_sustained_message_translated_multi_speaker_program_requires_review(self) -> None:
        self._assert_single_sustained_shape_requires_review(
            "Translated alternating-speaker program"
        )

    def test_mixed_positive_and_alternating_speaker_evidence_requires_review(self) -> None:
        client = FakeVerifierClient(
            "worship_service_sermon",
            reason_codes=[
                "single_sustained_message",
                "sustained_biblical_exposition",
                "translated_or_alternating_speakers",
            ],
        )
        with tempfile.TemporaryDirectory() as tmp:
            result = verify_recording(
                title="Ambiguous translated program",
                proposed={"youtube_video_id": "mixed", **proposed()},
                client=client,
                model_digest="digest",
                cache_dir=Path(tmp),
            )

        self.assertIsNone(result["predicted_outcome"])
        self.assertEqual(["translated_or_alternating_speakers"], result["contradictory_reason_codes"])
        self.assertIn("explicit_contradictory_program_evidence", result["policy_reason_codes"])

    def test_multi_speaker_attribution_cannot_negate_coherent_principal_message(self) -> None:
        payload = proposed()
        candidate = payload["classification"]["search"]["candidates"][0]
        candidate.update(
            {
                "fine_support_block_ids": list(range(12)),
                "boundary_recovery": {
                    "discarded_component_block_ids": [],
                    "objective_separator_block_ids": [],
                },
            }
        )
        client = FakeVerifierClient(
            "multi_speaker_or_student_program",
            reason_codes=[
                "multiple_short_speakers_or_sermonettes",
                "facilitated_group_structure",
            ],
        )
        with tempfile.TemporaryDirectory() as tmp:
            result = verify_recording(
                title="Worship service with a principal message",
                proposed={"youtube_video_id": "fc-shape", **payload},
                client=client,
                model_digest="digest",
                cache_dir=Path(tmp),
            )

        self.assertIsNone(result["predicted_outcome"])
        self.assertEqual("unclear", result["decision"])
        self.assertEqual("medium", result["confidence"])
        self.assertEqual(
            "multi_speaker_or_student_program",
            result["model_verdict"]["decision"],
        )
        self.assertIn(
            "coherent_principal_candidate_conflicts_with_multi_speaker_rejection",
            result["policy_reason_codes"],
        )

    def _assert_single_sustained_shape_requires_review(self, title: str) -> None:
        client = FakeVerifierClient(
            "worship_service_sermon",
            reason_codes=["single_sustained_message"],
        )
        with tempfile.TemporaryDirectory() as tmp:
            result = verify_recording(
                title=title,
                proposed={"youtube_video_id": "shape", **proposed()},
                client=client,
                model_digest="digest",
                cache_dir=Path(tmp),
            )

        self.assertIsNone(result["predicted_outcome"])
        self.assertEqual("unclear", result["decision"])
        self.assertEqual("medium", result["confidence"])
        self.assertEqual("worship_service_sermon", result["model_verdict"]["decision"])
        self.assertIn(
            "missing_independent_sermon_specific_evidence",
            result["policy_reason_codes"],
        )


if __name__ == "__main__":
    unittest.main()
