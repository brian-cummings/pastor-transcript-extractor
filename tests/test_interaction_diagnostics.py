from __future__ import annotations

import unittest
import tempfile
from pathlib import Path

from pastor_transcript_extractor.interaction_diagnostics import (
    DiagnosticBlock,
    DiagnosticInferenceCache,
    build_diagnostic_blocks,
    deduplicate_caption_text,
    interaction_schema,
    interaction_prompt,
    interaction_consistency_warnings,
    numbered_evidence_lines,
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

    def test_numbers_deduplicated_lines_for_stable_evidence(self) -> None:
        self.assertEqual(
            "[L001] First line\n[L002] Second line",
            numbered_evidence_lines("First line\nSecond line"),
        )

        schema = interaction_schema("First line\nSecond line")
        evidence_items = schema["properties"]["audience_turn_taking_evidence_line_ids"]["items"]
        self.assertEqual(["L001", "L002"], evidence_items["enum"])

    def test_prompt_numbers_only_current_evidence_lines(self) -> None:
        block = DiagnosticBlock(1, [1], 10.0, 20.0, "current", "Current evidence")
        previous = DiagnosticBlock(0, [0], 0.0, 10.0, "previous", "Previous context")

        prompt = interaction_prompt(block, previous, None)

        self.assertIn("CURRENT:\n[L001] Current evidence", prompt)
        self.assertIn("PREVIOUS:\nPrevious context", prompt)
        self.assertNotIn("[L001] Previous context", prompt)

    def test_requires_valid_line_ids_for_positive_signals(self) -> None:
        content = {
            "interaction_mode": "facilitated_group_discussion",
            "audience_turn_taking": True,
            "audience_turn_taking_evidence_line_ids": ["L001", "L002"],
            "lesson_material_references": False,
            "lesson_material_references_evidence_line_ids": [],
            "multiple_sustained_speakers": True,
            "multiple_sustained_speakers_evidence_line_ids": ["L002"],
        }
        text = "What do you think?\nI think it means grace."
        self.assertEqual([], validate_interaction_evidence(content, text))

        content["multiple_sustained_speakers_evidence_line_ids"] = ["L003"]
        self.assertIn(
            "ungrounded_multiple_sustained_speakers",
            validate_interaction_evidence(content, text),
        )

    def test_mode_inconsistency_is_a_warning_without_erasing_grounded_signals(self) -> None:
        content = {
            "interaction_mode": "facilitated_group_discussion",
            "audience_turn_taking": True,
            "audience_turn_taking_evidence_line_ids": ["L001"],
            "lesson_material_references": False,
            "lesson_material_references_evidence_line_ids": [],
            "multiple_sustained_speakers": False,
            "multiple_sustained_speakers_evidence_line_ids": [],
        }

        self.assertEqual([], validate_interaction_evidence(content, "Audience answer"))
        self.assertEqual(
            ["inconsistent_facilitated_group_discussion"],
            interaction_consistency_warnings(content),
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
