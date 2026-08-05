from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from typer.testing import CliRunner

from pastor_transcript_extractor.cli import app
from pastor_transcript_extractor.fixture_correction import (
    load_fixture_window_correction,
    persist_fixture_window_override,
)
from pastor_transcript_extractor.fixture_validation import FixtureValidationError


def fixture_payload(
    video_id: str = "video-1",
    *,
    expected_outcome: str = "sermon",
) -> dict[str, object]:
    return {
        "video_id": video_id,
        "ground_truth_version": 2,
        "reviewed_by": "fixture-reviewer",
        "expected_outcome": expected_outcome,
        "expected_spans": (
            [{"start_seconds": 120.0, "end_seconds": 900.0}]
            if expected_outcome == "sermon"
            else []
        ),
        "allowed_interruptions": [],
    }


class FixtureCorrectionTests(unittest.TestCase):
    def test_loads_one_continuous_positive_fixture(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture_dir = Path(tmp)
            fixture_path = fixture_dir / "video-1.json"
            fixture_path.write_text(
                json.dumps(fixture_payload()),
                encoding="utf-8",
            )

            correction = load_fixture_window_correction(
                fixture_dir,
                "video-1",
            )

            self.assertEqual(120.0, correction.start_seconds)
            self.assertEqual(900.0, correction.end_seconds)
            self.assertEqual(2, correction.ground_truth_version)
            self.assertEqual("fixture-reviewer", correction.reviewed_by)

    def test_rejects_negative_fixture(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture_dir = Path(tmp)
            (fixture_dir / "video-1.json").write_text(
                json.dumps(fixture_payload(expected_outcome="no_sermon")),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                FixtureValidationError,
                "only positive sermon fixtures",
            ):
                load_fixture_window_correction(fixture_dir, "video-1")

    def test_rejects_fixture_with_multiple_spans(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture_dir = Path(tmp)
            payload = fixture_payload()
            payload["expected_spans"] = [
                {"start_seconds": 120.0, "end_seconds": 300.0},
                {"start_seconds": 360.0, "end_seconds": 900.0},
            ]
            payload["allowed_interruptions"] = [
                {"start_seconds": 300.0, "end_seconds": 360.0}
            ]
            (fixture_dir / "video-1.json").write_text(
                json.dumps(payload),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                FixtureValidationError,
                "exactly one continuous expected span",
            ):
                load_fixture_window_correction(fixture_dir, "video-1")

    def test_persists_auditable_override(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture_path = root / "fixtures" / "video-1.json"
            fixture_path.parent.mkdir()
            fixture_path.write_text(
                json.dumps(fixture_payload()),
                encoding="utf-8",
            )
            correction = load_fixture_window_correction(
                fixture_path.parent,
                "video-1",
            )
            override_path = root / "review" / "window_override.json"

            persist_fixture_window_override(correction, override_path)

            override = json.loads(override_path.read_text(encoding="utf-8"))
            self.assertEqual(120.0, override["start_seconds"])
            self.assertEqual(900.0, override["end_seconds"])
            self.assertEqual("fixture-reviewer", override["updated_by"])
            self.assertIn("ground_truth_version=2", override["notes"])
            self.assertIn("updated_at", override)


class FixtureCorrectionCliTests(unittest.TestCase):
    def test_applies_fixture_reclassifies_and_regenerates_observation(self) -> None:
        class FakeOllamaClient:
            def __init__(self, config: object) -> None:
                self.model = getattr(config, "model")

            def model_digest(self) -> str:
                return f"digest-{self.model}"

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture_dir = root / "fixtures"
            fixture_dir.mkdir()
            (fixture_dir / "video-1.json").write_text(
                json.dumps(fixture_payload()),
                encoding="utf-8",
            )
            proposed_path = root / "proposed.json"
            proposed_path.write_text(
                json.dumps(
                    {
                        "segments": [
                            {
                                "start_seconds": 0.0,
                                "end_seconds": 1000.0,
                                "text": "Reusable transcript",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            extraction = SimpleNamespace(id=11, proposed_json_path=str(proposed_path))
            video = SimpleNamespace(
                id=7,
                youtube_video_id="video-1",
                title="Fixture correction",
                pastor_id=None,
            )
            previous = SimpleNamespace(input_fingerprint="old-fingerprint")
            database = SimpleNamespace(
                get_video_by_youtube_id=lambda _: video,
                get_latest_extraction_result_for_video=lambda _: extraction,
                get_latest_speaker_observation_for_video=lambda _: previous,
            )
            video_paths = SimpleNamespace(review=root / "review")
            observation = SimpleNamespace(
                extraction_result_id=11,
                start_seconds=120.0,
                end_seconds=900.0,
                input_fingerprint="new-fingerprint",
            )

            def fake_reclassify(*args, **kwargs):
                self.assertTrue(kwargs["force"])
                proposed_path.write_text(
                    json.dumps(
                        {
                            "sermon_window": {
                                "source": "override",
                                "start_seconds": 120.0,
                                "end_seconds": 900.0,
                            },
                            "final_disposition": {"status": "accepted_sermon"},
                        }
                    ),
                    encoding="utf-8",
                )
                return SimpleNamespace(proposed_json_path=proposed_path)

            with patch(
                "pastor_transcript_extractor.cli.get_database",
                return_value=database,
            ), patch(
                "pastor_transcript_extractor.cli.resolve_video_artifact_paths",
                return_value=video_paths,
            ), patch(
                "pastor_transcript_extractor.cli.OllamaClient",
                FakeOllamaClient,
            ), patch(
                "pastor_transcript_extractor.cli.reclassify_video",
                side_effect=fake_reclassify,
            ) as reclassify_mock, patch(
                "pastor_transcript_extractor.cli.record_neutral_speaker_evidence",
                return_value=SimpleNamespace(
                    neutral_evidence=SimpleNamespace(observation=observation)
                ),
            ) as evidence_mock, patch(
                "pastor_transcript_extractor.cli.assess_automatic_speaker_observation",
                return_value=SimpleNamespace(reason_code="eligible"),
            ):
                result = CliRunner().invoke(
                    app,
                    [
                        "apply-fixture-correction",
                        "video-1",
                        "--fixture-dir",
                        str(fixture_dir),
                        "--base-dir",
                        str(root / "data"),
                    ],
                )

            self.assertEqual(0, result.exit_code, msg=result.output)
            self.assertEqual(1, reclassify_mock.call_count)
            self.assertEqual(1, evidence_mock.call_count)
            self.assertIn("speaker_fingerprint_regenerated=new-fingerprint", result.output)
            self.assertIn("automatic_pair_eligibility=eligible", result.output)
            override = json.loads(
                (root / "review" / "window_override.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(120.0, override["start_seconds"])
            self.assertEqual(900.0, override["end_seconds"])


if __name__ == "__main__":
    unittest.main()
