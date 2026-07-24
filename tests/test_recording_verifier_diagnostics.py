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

    def __init__(self, decision: str, confidence: str = "high") -> None:
        self.decision = decision
        self.confidence = confidence
        self.calls = 0

    def generate_json(
        self, prompt: str, schema: dict[str, object]
    ) -> LocalLlmResponse:
        del prompt, schema
        self.calls += 1
        content = {
            "decision": self.decision,
            "confidence": self.confidence,
            "reason_codes": ["single_sustained_message"],
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
        self.assertEqual("recording-sermon-verifier-v2", result["prompt_version"])
        self.assertEqual("recording-sermon-verifier-policy-v3", result["policy_version"])


if __name__ == "__main__":
    unittest.main()
