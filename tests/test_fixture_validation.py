from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from threading import Barrier
from types import SimpleNamespace
from unittest.mock import patch

from typer.testing import CliRunner

from pastor_transcript_extractor.cli import app
from pastor_transcript_extractor.fixture_validation import (
    FixtureValidationError,
    validate_fixture_directory,
    validate_fixture_payload,
)


def valid_payload(video_id: str = "abc123") -> dict[str, object]:
    return {
        "video_id": video_id,
        "expected_outcome": "sermon",
        "expected_spans": [
            {"start_seconds": 100.0, "end_seconds": 300.0},
            {"start_seconds": 320.0, "end_seconds": 500.0},
        ],
        "allowed_interruptions": [{"start_seconds": 300.0, "end_seconds": 320.0}],
        "ground_truth_version": 1,
        "reviewed_by": "manual",
        "failure_mode": "incorrect_rule_window",
    }


class FixtureValidationTests(unittest.TestCase):
    def test_accepts_valid_span_fixture(self) -> None:
        fixture = validate_fixture_payload(valid_payload(), path=Path("fixture.json"))
        self.assertEqual("abc123", fixture.video_id)
        self.assertEqual([(100.0, 300.0), (320.0, 500.0)], fixture.expected_spans)

    def test_rejects_overlapping_expected_spans(self) -> None:
        payload = valid_payload()
        payload["expected_spans"] = [
            {"start_seconds": 100, "end_seconds": 350},
            {"start_seconds": 300, "end_seconds": 500},
        ]
        with self.assertRaisesRegex(FixtureValidationError, "overlapping"):
            validate_fixture_payload(payload, path=Path("fixture.json"))

    def test_rejects_interruption_outside_sermon_envelope(self) -> None:
        payload = valid_payload()
        payload["allowed_interruptions"] = [{"start_seconds": 20, "end_seconds": 30}]
        with self.assertRaisesRegex(FixtureValidationError, "inside the expected sermon envelope"):
            validate_fixture_payload(payload, path=Path("fixture.json"))

    def test_rejects_interruption_overlapping_retained_span(self) -> None:
        payload = valid_payload()
        payload["allowed_interruptions"] = [{"start_seconds": 200, "end_seconds": 220}]
        with self.assertRaisesRegex(FixtureValidationError, "cannot overlap"):
            validate_fixture_payload(payload, path=Path("fixture.json"))

    def test_rejects_negative_or_reversed_timestamps(self) -> None:
        for start, end in [(-1, 10), (20, 20), (30, 20)]:
            payload = valid_payload()
            payload["expected_spans"] = [{"start_seconds": start, "end_seconds": end}]
            with self.assertRaises(FixtureValidationError):
                validate_fixture_payload(payload, path=Path("fixture.json"))

    def test_requires_reviewer_and_version(self) -> None:
        for field in ["reviewed_by", "ground_truth_version"]:
            payload = valid_payload()
            del payload[field]
            with self.assertRaises(FixtureValidationError):
                validate_fixture_payload(payload, path=Path("fixture.json"))

    def test_directory_rejects_duplicate_video_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory / "one.json").write_text(json.dumps(valid_payload()), encoding="utf-8")
            (directory / "two.json").write_text(json.dumps(valid_payload()), encoding="utf-8")
            with self.assertRaisesRegex(FixtureValidationError, "duplicate video_id"):
                validate_fixture_directory(directory)

    def test_accepts_no_sermon_fixture_with_empty_ranges(self) -> None:
        payload = valid_payload()
        payload["expected_outcome"] = "no_sermon"
        payload["expected_spans"] = []
        payload["allowed_interruptions"] = []

        fixture = validate_fixture_payload(payload, path=Path("negative.json"))

        self.assertEqual("no_sermon", fixture.expected_outcome)
        self.assertEqual([], fixture.expected_spans)

    def test_no_sermon_fixture_rejects_spans_or_interruptions(self) -> None:
        for field in ["expected_spans", "allowed_interruptions"]:
            payload = valid_payload()
            payload["expected_outcome"] = "no_sermon"
            payload["expected_spans"] = []
            payload["allowed_interruptions"] = []
            payload[field] = [{"start_seconds": 10, "end_seconds": 20}]
            with self.assertRaisesRegex(FixtureValidationError, "no_sermon fixtures"):
                validate_fixture_payload(payload, path=Path("negative.json"))

    def test_requires_expected_outcome(self) -> None:
        payload = valid_payload()
        del payload["expected_outcome"]
        with self.assertRaisesRegex(FixtureValidationError, "expected_outcome"):
            validate_fixture_payload(payload, path=Path("fixture.json"))


class FixtureReclassificationCliTests(unittest.TestCase):
    def test_reclassify_requires_exactly_one_video_selector(self) -> None:
        result = CliRunner().invoke(
            app,
            [
                "reclassify",
                "--video-id",
                "1",
                "--fixture-dir",
                "evaluation/fixtures",
            ],
        )

        self.assertNotEqual(0, result.exit_code)
        self.assertIn("exactly one", result.output)

    def test_reclassify_rejects_all_with_another_selector(self) -> None:
        result = CliRunner().invoke(
            app,
            ["reclassify", "--all", "--video-id", "1"],
        )

        self.assertNotEqual(0, result.exit_code)
        self.assertIn("exactly one", result.output)

    def test_reclassify_all_skips_non_reusable_artifacts_and_reports_counts(self) -> None:
        class FakeOllamaClient:
            def __init__(self, config: object) -> None:
                self.model = getattr(config, "model")

            def model_digest(self) -> str:
                return "fixture-digest"

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            proposed_paths: dict[int, Path] = {}
            for video_id in (1, 2):
                path = root / f"proposed-{video_id}.json"
                path.write_text(
                    json.dumps({
                        "segments": [{
                            "start_seconds": 0.0,
                            "end_seconds": 60.0,
                            "text": "Reusable transcript segment",
                        }]
                    }),
                    encoding="utf-8",
                )
                proposed_paths[video_id] = path
            videos = [
                SimpleNamespace(
                    id=video_id,
                    title=f"Video {video_id}",
                    youtube_video_id=f"youtube-{video_id}",
                )
                for video_id in range(1, 5)
            ]
            extractions = {
                1: SimpleNamespace(proposed_json_path=str(proposed_paths[1])),
                2: SimpleNamespace(proposed_json_path=str(proposed_paths[2])),
                3: SimpleNamespace(proposed_json_path=str(root / "missing.json")),
                4: None,
            }
            database = SimpleNamespace(
                list_videos=lambda: videos,
                get_latest_extraction_result_for_video=lambda video_id: extractions[video_id],
            )

            def reclassify(*args, **kwargs):
                del kwargs
                video_id = args[2]
                if video_id == 2:
                    raise RuntimeError("fixture failure")
                return SimpleNamespace(
                    reused=True,
                    confidence_tier="medium",
                    disposition_status="review_required",
                    retained_segment_count=4,
                    cache_hits=2,
                    cache_misses=0,
                    classification_path=root / "classification.json",
                )

            with patch(
                "pastor_transcript_extractor.cli.get_database", return_value=database
            ), patch(
                "pastor_transcript_extractor.cli.OllamaClient", FakeOllamaClient
            ), patch(
                "pastor_transcript_extractor.cli.reclassify_video",
                side_effect=reclassify,
            ) as reclassify_mock:
                result = CliRunner().invoke(
                    app,
                    [
                        "reclassify",
                        "--all",
                        "--jobs",
                        "2",
                        "--base-dir",
                        str(root / "data"),
                    ],
                )

            self.assertEqual(0, result.exit_code, msg=result.output)
            self.assertIn("Discovered 4 video(s) in the corpus", result.output)
            self.assertEqual(
                {1, 2},
                {call.args[2] for call in reclassify_mock.call_args_list},
            )
            self.assertIn(
                "Reclassified 0 video(s); reused 1; skipped 2; failed 1.",
                result.output,
            )

    def test_reclassify_discovers_fixture_videos_in_deterministic_order(self) -> None:
        class FakeOllamaClient:
            def __init__(self, config: object) -> None:
                self.model = getattr(config, "model")

            def model_digest(self) -> str:
                return "fixture-digest"

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture_dir = root / "fixtures"
            fixture_dir.mkdir()
            (fixture_dir / "a.json").write_text(
                json.dumps(valid_payload("youtube-a")), encoding="utf-8"
            )
            (fixture_dir / "b.json").write_text(
                json.dumps(valid_payload("youtube-b")), encoding="utf-8"
            )
            videos = {
                "youtube-a": SimpleNamespace(id=20, title="Fixture A"),
                "youtube-b": SimpleNamespace(id=10, title="Fixture B"),
            }
            database = SimpleNamespace(
                get_video_by_youtube_id=lambda video_id: videos.get(video_id),
                get_latest_extraction_result_for_video=lambda _: SimpleNamespace(),
            )
            result_payload = SimpleNamespace(
                reused=False,
                confidence_tier="medium",
                disposition_status="review_required",
                retained_segment_count=4,
                cache_hits=2,
                cache_misses=1,
                classification_path=root / "classification.json",
            )
            with patch(
                "pastor_transcript_extractor.cli.get_database", return_value=database
            ), patch(
                "pastor_transcript_extractor.cli.OllamaClient", FakeOllamaClient
            ), patch(
                "pastor_transcript_extractor.cli.reclassify_video",
                return_value=result_payload,
            ) as reclassify_mock:
                result = CliRunner().invoke(
                    app,
                    [
                        "reclassify",
                        "--fixture-dir",
                        str(fixture_dir),
                        "--force",
                        "--base-dir",
                        str(root / "data"),
                    ],
                )

            self.assertEqual(0, result.exit_code, msg=result.output)
            self.assertIn("Discovered 2 fixture video(s)", result.output)
            self.assertEqual(
                [20, 10],
                [call.args[2] for call in reclassify_mock.call_args_list],
            )

    def test_reclassify_rejects_fixture_missing_from_database_before_inference(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture_dir = root / "fixtures"
            fixture_dir.mkdir()
            (fixture_dir / "missing.json").write_text(
                json.dumps(valid_payload("missing-video")), encoding="utf-8"
            )
            database = SimpleNamespace(get_video_by_youtube_id=lambda _: None)
            with patch(
                "pastor_transcript_extractor.cli.get_database", return_value=database
            ), patch("pastor_transcript_extractor.cli.OllamaClient") as client_mock:
                result = CliRunner().invoke(
                    app,
                    [
                        "reclassify",
                        "--fixture-dir",
                        str(fixture_dir),
                        "--base-dir",
                        str(root / "data"),
                    ],
                )

            self.assertNotEqual(0, result.exit_code)
            self.assertIn("missing-video", result.output)
            client_mock.assert_not_called()

    def test_reclassify_runs_fixture_videos_with_requested_workers(self) -> None:
        class FakeOllamaClient:
            def __init__(self, config: object) -> None:
                self.model = getattr(config, "model")

            def model_digest(self) -> str:
                return "fixture-digest"

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture_dir = root / "fixtures"
            fixture_dir.mkdir()
            for fixture_id in ("youtube-a", "youtube-b"):
                (fixture_dir / f"{fixture_id}.json").write_text(
                    json.dumps(valid_payload(fixture_id)), encoding="utf-8"
                )
            videos = {
                "youtube-a": SimpleNamespace(id=20, title="Fixture A"),
                "youtube-b": SimpleNamespace(id=10, title="Fixture B"),
            }
            database = SimpleNamespace(
                get_video_by_youtube_id=lambda video_id: videos.get(video_id),
                get_latest_extraction_result_for_video=lambda _: SimpleNamespace(),
            )
            barrier = Barrier(2)

            def reclassify(*args, **kwargs):
                barrier.wait(timeout=2)
                return SimpleNamespace(
                    reused=False,
                    confidence_tier="medium",
                    disposition_status="review_required",
                    retained_segment_count=4,
                    cache_hits=0,
                    cache_misses=1,
                    classification_path=root / "classification.json",
                )

            with patch(
                "pastor_transcript_extractor.cli.get_database", return_value=database
            ), patch(
                "pastor_transcript_extractor.cli.OllamaClient", FakeOllamaClient
            ), patch(
                "pastor_transcript_extractor.cli.reclassify_video",
                side_effect=reclassify,
            ):
                result = CliRunner().invoke(
                    app,
                    [
                        "reclassify",
                        "--fixture-dir",
                        str(fixture_dir),
                        "--force",
                        "--jobs",
                        "2",
                        "--base-dir",
                        str(root / "data"),
                    ],
                )

            self.assertEqual(0, result.exit_code, msg=result.output)
            self.assertIn("Reclassified 2 video(s)", result.output)


if __name__ == "__main__":
    unittest.main()
