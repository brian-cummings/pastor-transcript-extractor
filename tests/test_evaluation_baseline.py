from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from typer.testing import CliRunner

from pastor_transcript_extractor.cli import app
from pastor_transcript_extractor.evaluation_baseline import (
    BaselineValidationError,
    canonical_hash,
    validate_localization_baseline,
)


def fixture_payload(video_id: str = "video-a") -> dict[str, object]:
    return {
        "video_id": video_id,
        "expected_outcome": "sermon",
        "expected_spans": [{"start_seconds": 10, "end_seconds": 20}],
        "allowed_interruptions": [],
        "ground_truth_version": 1,
        "reviewed_by": "reviewer",
    }


def baseline_payload(fixture: dict[str, object]) -> dict[str, object]:
    entries = [{"video_id": fixture["video_id"], "fixture_hash": canonical_hash(fixture)}]
    return {
        "schema_version": 1,
        "baseline_id": "test-baseline",
        "code_commit": "a" * 40,
        "evaluation_run": {"run_id": "run-1"},
        "implementation_versions": {
            "search_algorithm": "adaptive_llm_v3",
            "block_builder": "timestamp-blocks-v2+rolling-caption-v1",
            "coarse_discovery": "phase-primary-likelihood-rescue-v1",
            "fine_component": "objective-noise-components+continuity-probe-v2",
            "confidence_policy": "soft_rule_overlap_v1",
        },
        "model_configuration": {"model_name": "test"},
        "fixture_corpus": {
            "fixture_count": 1,
            "fingerprint": canonical_hash(entries),
            "fixtures": entries,
        },
        "metrics": {
            "mean_sermon_recall": 1.0,
            "worst_sermon_recall": 1.0,
            "mean_contamination_ratio": 0.0,
            "correct_top_candidate_rate": 1.0,
            "catastrophic_omissions": 0,
            "negative_accepted_dispositions": 0,
            "negative_high_confidence_false_positives": 0,
        },
    }


class EvaluationBaselineTests(unittest.TestCase):
    def _write_corpus(self, root: Path) -> tuple[Path, Path, dict[str, object]]:
        fixtures = root / "fixtures"
        fixtures.mkdir()
        fixture = fixture_payload()
        (fixtures / "video-a.json").write_text(json.dumps(fixture), encoding="utf-8")
        manifest = root / "baseline.json"
        manifest.write_text(json.dumps(baseline_payload(fixture)), encoding="utf-8")
        return manifest, fixtures, fixture

    def test_validates_exact_fixture_corpus(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manifest, fixtures, _ = self._write_corpus(Path(tmp))

            validated = validate_localization_baseline(manifest, fixtures)

            self.assertEqual("test-baseline", validated.baseline_id)
            self.assertEqual(1, validated.fixture_count)

    def test_detects_changed_fixture(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manifest, fixtures, fixture = self._write_corpus(Path(tmp))
            fixture["reviewed_by"] = "another reviewer"
            (fixtures / "video-a.json").write_text(json.dumps(fixture), encoding="utf-8")

            with self.assertRaisesRegex(BaselineValidationError, r"changed=\['video-a'\]"):
                validate_localization_baseline(manifest, fixtures)

    def test_detects_added_or_missing_fixture(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manifest, fixtures, _ = self._write_corpus(Path(tmp))
            (fixtures / "video-b.json").write_text(
                json.dumps(fixture_payload("video-b")), encoding="utf-8"
            )

            with self.assertRaisesRegex(BaselineValidationError, r"added=\['video-b'\]"):
                validate_localization_baseline(manifest, fixtures)

    def test_detects_manifest_fingerprint_corruption(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manifest, fixtures, fixture = self._write_corpus(Path(tmp))
            payload = baseline_payload(fixture)
            payload["fixture_corpus"]["fingerprint"] = "wrong"  # type: ignore[index]
            manifest.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaisesRegex(BaselineValidationError, "fingerprint"):
                validate_localization_baseline(manifest, fixtures)

    def test_cli_validates_repository_baseline(self) -> None:
        result = CliRunner().invoke(
            app,
            [
                "validate-baseline",
                "evaluation/baselines/sermon-localization-v1.json",
                "--fixture-dir",
                "evaluation/fixtures",
            ],
        )

        self.assertEqual(0, result.exit_code, result.output)
        self.assertIn("Validated sermon-localization-v1: 22 fixture(s)", result.output)


if __name__ == "__main__":
    unittest.main()
