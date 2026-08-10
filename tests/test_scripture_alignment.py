from __future__ import annotations

from pathlib import Path
import unittest

from typer.testing import CliRunner

from pastor_transcript_extractor.cli import app
from pastor_transcript_extractor.scripture_alignment import (
    AlignmentSegment,
    bible_source_provenance,
    detect_scripture_alignments,
)
from pastor_transcript_extractor.scripture_alignment_evaluation import (
    evaluate_scripture_alignment,
)


FIXTURE = Path("evaluation/scripture-alignments/reviewed-v1.json")


class ScriptureAlignmentTests(unittest.TestCase):
    def test_detects_substantial_text_and_rejects_common_religious_language(self) -> None:
        accepted = detect_scripture_alignments(
            [
                AlignmentSegment(
                    4,
                    "For God so loved the world that he gave his only born Son, "
                    "that whoever believes in him should not perish but have eternal life.",
                    40.0,
                    50.0,
                )
            ]
        )
        rejected = detect_scripture_alignments(
            [
                AlignmentSegment(
                    5,
                    "God is with you today, so do not be afraid as you walk through "
                    "this difficult season.",
                )
            ]
        )

        self.assertEqual(1, len(accepted))
        self.assertEqual("John 3:16", accepted[0]["canonical_reference"])
        self.assertEqual("independent", accepted[0]["alignment_class"])
        self.assertEqual(1.0, accepted[0]["alignment_score"])
        self.assertEqual([], rejected)

    def test_bundled_translation_has_checksum_backed_provenance(self) -> None:
        provenance = bible_source_provenance()

        self.assertEqual("World English Bible", provenance["translation_name"])
        self.assertEqual("2020 stable text edition", provenance["translation_version"])
        self.assertEqual("Public Domain", provenance["license"])
        self.assertEqual(64, len(str(provenance["artifact_content_sha256"])))

    def test_reviewed_evaluation_reports_precision_and_recall(self) -> None:
        result = evaluate_scripture_alignment(FIXTURE)

        self.assertEqual(12, result.case_count)
        self.assertEqual(12, result.passed_case_count)
        self.assertEqual(1.0, result.overall.precision)
        self.assertEqual(1.0, result.overall.recall)
        self.assertEqual(5, result.overall.true_negative_cases)

    def test_cli_exposes_reviewed_evaluation(self) -> None:
        result = CliRunner().invoke(
            app, ["analysis", "evaluate-scripture-alignment", str(FIXTURE)]
        )

        self.assertEqual(0, result.exit_code, msg=result.output)
        self.assertIn("1.000", result.output)
        self.assertIn("World English", result.output)


if __name__ == "__main__":
    unittest.main()
