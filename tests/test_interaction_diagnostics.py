from __future__ import annotations

import unittest
import tempfile
from pathlib import Path

from pastor_transcript_extractor.interaction_diagnostics import (
    DiagnosticBlock,
    DiagnosticInferenceCache,
    build_diagnostic_blocks,
    deduplicate_caption_text,
    run_model_diagnostics,
    validate_interaction_evidence,
)


class InteractionDiagnosticTests(unittest.TestCase):
    class FailingClient:
        model = "failing-model"

        def generate_json(self, prompt: str, schema: dict[str, object]) -> object:
            del prompt, schema
            raise RuntimeError("malformed response")

    def test_deduplicates_repeated_and_growing_caption_lines(self) -> None:
        text = """Open your Bible
Open your Bible
Open your Bible to Mark
Open your Bible to Mark
The widow gave two coins"""

        self.assertEqual(
            "Open your Bible to Mark\nThe widow gave two coins",
            deduplicate_caption_text(text),
        )

    def test_builds_only_selected_candidate_blocks_without_changing_segments(self) -> None:
        proposed = {
            "classification": {
                "search": {
                    "selected_rank": 1,
                    "candidates": [{"rank": 1, "start_seconds": 10.0, "end_seconds": 40.0}],
                }
            },
            "segments": [
                {"start_seconds": 0.0, "end_seconds": 10.0, "text": "welcome"},
                {"start_seconds": 10.0, "end_seconds": 20.0, "text": "sermon\nsermon"},
                {"start_seconds": 20.0, "end_seconds": 30.0, "text": "continues"},
                {"start_seconds": 40.0, "end_seconds": 50.0, "text": "closing"},
            ],
        }

        blocks = build_diagnostic_blocks(proposed)

        self.assertEqual(1, len(blocks))
        self.assertEqual([1, 2], blocks[0].segment_indexes)
        self.assertEqual("sermon\ncontinues", blocks[0].deduplicated_text)

    def test_requires_exact_grounding_for_positive_signals(self) -> None:
        content = {
            "interaction_mode": "facilitated_group_discussion",
            "audience_turn_taking": True,
            "audience_turn_taking_evidence": "What do you think? I think it means grace.",
            "lesson_material_references": False,
            "lesson_material_references_evidence": "",
            "multiple_sustained_speakers": True,
            "multiple_sustained_speakers_evidence": "I think it means grace.",
        }
        text = "What do you think? I think it means grace. Let us continue."
        self.assertEqual([], validate_interaction_evidence(content, text))

        content["multiple_sustained_speakers_evidence"] = "A missing quote"
        self.assertIn(
            "ungrounded_multiple_sustained_speakers",
            validate_interaction_evidence(content, text),
        )

    def test_model_failure_is_recorded_without_aborting_other_evidence(self) -> None:
        block = DiagnosticBlock(0, [1], 10.0, 20.0, "sermon", "sermon")
        with tempfile.TemporaryDirectory() as tmp:
            result = run_model_diagnostics(
                self.FailingClient(),
                model_digest="digest",
                sentinels=[("video", "Fixture", [block])],
                cache=DiagnosticInferenceCache(Path(tmp)),
            )

        self.assertEqual(1, result["inference_failures"])
        recorded = result["sentinels"][0]["blocks"][0]
        self.assertEqual(["inference_failed"], recorded["validation_errors"])
        self.assertIn("malformed response", recorded["inference_error"])


if __name__ == "__main__":
    unittest.main()
