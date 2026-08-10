from __future__ import annotations

from pathlib import Path
import unittest

from typer.testing import CliRunner

from pastor_transcript_extractor.cli import app
from pastor_transcript_extractor.scripture_reference_evaluation import (
    evaluate_scripture_detector,
)
from pastor_transcript_extractor.sermon_analysis import (
    detect_scripture_references_in_texts,
)


FIXTURE = Path("evaluation/scripture-references/contextual-v1.json")


class ScriptureReferenceDetectionTests(unittest.TestCase):
    def test_explicit_detection_remains_distinct_and_is_not_duplicated(self) -> None:
        detected = detect_scripture_references_in_texts(
            ["Read John 3:16 and Romans 8:1-4."]
        )

        self.assertEqual(2, len(detected))
        self.assertEqual({"explicit"}, {item["detection_class"] for item in detected})
        self.assertEqual(
            {"John 3:16", "Romans 8:1-4"},
            {item["canonical_reference"] for item in detected},
        )
        self.assertEqual(
            {"book_chapter_verse_pattern"},
            {item["detection_method"] for item in detected},
        )

    def test_contextual_forms_preserve_method_confidence_and_specificity(self) -> None:
        detected = detect_scripture_references_in_texts(
            [
                "Turn with me to John chapter three verse sixteen. "
                "The book of Romans will be next."
            ]
        )

        by_reference = {item["canonical_reference"]: item for item in detected}
        self.assertEqual({"John 3:16", "Romans"}, set(by_reference))
        self.assertEqual("contextual", by_reference["John 3:16"]["detection_class"])
        self.assertEqual("high", by_reference["John 3:16"]["detection_confidence"])
        self.assertEqual(
            "book_chapter_spoken", by_reference["John 3:16"]["detection_method"]
        )
        self.assertIsNone(by_reference["Romans"]["chapter"])
        self.assertEqual("cued_book_reference", by_reference["Romans"]["detection_method"])

    def test_immediate_continuation_resolves_but_unanchored_verse_does_not(self) -> None:
        detected = detect_scripture_references_in_texts(
            [
                "John chapter three is our text.",
                "Verse seventeen continues the thought.",
                "There is an intervening comment.",
                "Verse eighteen is important.",
            ]
        )

        self.assertEqual(
            ["John 3", "John 3:17"],
            [item["canonical_reference"] for item in detected],
        )
        continuation = detected[1]
        self.assertEqual("continuation_verse", continuation["detection_method"])
        self.assertEqual("medium", continuation["detection_confidence"])
        self.assertEqual(0, continuation["context_source_segment_index"])

    def test_ambiguous_language_and_invalid_chapters_are_negative(self) -> None:
        detected = detect_scripture_references_in_texts(
            [
                "Romans built roads and Acts of kindness mattered.",
                "John preached about the third chapter of our report.",
                "John chapter ninety-nine was written by mistake.",
                "Return to the verse after the chorus.",
            ]
        )

        self.assertEqual([], detected)

    def test_reviewed_fixture_reports_precision_recall_and_known_unsupported_forms(self) -> None:
        result = evaluate_scripture_detector(FIXTURE)

        self.assertEqual(25, result.case_count)
        self.assertEqual(23, result.passed_case_count)
        self.assertEqual(16, result.overall.true_positive)
        self.assertEqual(0, result.overall.false_positive)
        self.assertEqual(2, result.overall.false_negative)
        self.assertEqual(1.0, result.overall.precision)
        self.assertAlmostEqual(16 / 18, result.overall.recall)
        self.assertEqual(1.0, result.by_class["explicit"].recall)
        self.assertAlmostEqual(14 / 16, result.by_class["contextual"].recall)
        self.assertEqual(
            {"unsupported-colloquial-number-pair", "unsupported-next-verse"},
            {str(item["case_id"]) for item in result.failures},
        )

    def test_evaluation_cli_makes_metrics_and_misses_visible(self) -> None:
        result = CliRunner().invoke(
            app, ["analysis", "evaluate-scripture-detector", str(FIXTURE)]
        )

        self.assertEqual(0, result.exit_code, msg=result.output)
        self.assertIn("1.000", result.output)
        self.assertIn("0.889", result.output)
        self.assertIn("unsupported-colloquial-number-pair", result.output)


if __name__ == "__main__":
    unittest.main()
