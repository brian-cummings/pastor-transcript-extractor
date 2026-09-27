from __future__ import annotations

import tempfile
from pathlib import Path
import unittest

from typer.testing import CliRunner

from pastor_transcript_extractor.cli import app
from pastor_transcript_extractor.commands.identity.evaluation import (
    _select_bakeoff_fixtures,
)


class IdentityEvaluationCommandTests(unittest.TestCase):
    def test_development_scope_includes_legacy_unassigned_fixtures(self) -> None:
        fixtures = [
            {"pair_id": "legacy"},
            {"pair_id": "development", "evaluation_partition": "development"},
            {"pair_id": "held-out", "evaluation_partition": "held_out"},
        ]

        selected = _select_bakeoff_fixtures(fixtures, "development")

        self.assertEqual(["legacy", "development"], [item["pair_id"] for item in selected])

    def test_invalid_evaluation_scope_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "evaluation scope must be one of"):
            _select_bakeoff_fixtures([{"pair_id": "one"}], "production")

    def test_validate_pair_fixtures_reports_an_empty_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = CliRunner().invoke(
                app,
                ["identity", "validate-pair-fixtures", str(Path(tmp))],
            )

        self.assertNotEqual(0, result.exit_code)
        self.assertIn("No speaker-pair fixtures found", result.output)


if __name__ == "__main__":
    unittest.main()
