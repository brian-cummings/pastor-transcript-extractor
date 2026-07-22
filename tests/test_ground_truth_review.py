from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from pastor_transcript_extractor.cli import (
    _prompt_failure_mode,
    review_ground_truth,
    review_next_ground_truth,
)
from pastor_transcript_extractor.fixture_validation import validate_fixture_payload
from pastor_transcript_extractor.ground_truth_review import (
    approved_negative_fixture_payload,
    open_video_url,
    approved_fixture_payload,
    parse_interruptions,
    parse_timestamp,
    retained_spans,
    suggested_envelope,
    transcript_context,
    youtube_timestamp_url,
)


class GroundTruthReviewTests(unittest.TestCase):
    def test_failure_mode_prompt_lists_conventional_options_and_supports_other(self) -> None:
        with patch("pastor_transcript_extractor.cli.typer.prompt", return_value="incorrect_rule_window"):
            self.assertEqual(
                "incorrect_rule_window",
                _prompt_failure_mode(contains_sermon=True),
            )
        with patch(
            "pastor_transcript_extractor.cli.typer.prompt",
            side_effect=["other", "compound_service_edge_case"],
        ):
            self.assertEqual(
                "compound_service_edge_case",
                _prompt_failure_mode(contains_sermon=False),
            )

    def test_review_opens_at_candidate_start_or_zero_when_no_candidate_exists(self) -> None:
        cases = [
            (
                {
                    "classification": {
                        "method": "adaptive_llm_v3",
                        "retained_segment_indexes": [1],
                    },
                    "segments": [
                        {"start_seconds": 0.0, "end_seconds": 10.0, "text": "noise"},
                        {"start_seconds": 100.0, "end_seconds": 200.0, "text": "sermon"},
                    ],
                },
                "https://www.youtube.com/watch?v=abc123&t=100s",
            ),
            (
                {"segments": [{"start_seconds": 0.0, "end_seconds": 69.0, "text": "test"}]},
                "https://www.youtube.com/watch?v=abc123&t=0s",
            ),
        ]
        for payload, expected_url in cases:
            with self.subTest(expected_url=expected_url), tempfile.TemporaryDirectory() as tmp:
                proposed_path = Path(tmp) / "proposed.json"
                proposed_path.write_text(json.dumps(payload), encoding="utf-8")
                database = SimpleNamespace(
                    get_video_by_youtube_id=lambda _: SimpleNamespace(
                        id=1,
                        url="https://www.youtube.com/watch?v=abc123&t=99s",
                        title="Fixture",
                        duration_seconds=200,
                    ),
                    get_latest_extraction_result_for_video=lambda _: SimpleNamespace(
                        proposed_json_path=str(proposed_path)
                    ),
                )
                with (
                    patch("pastor_transcript_extractor.cli.get_database", return_value=database),
                    patch("pastor_transcript_extractor.cli.open_video_url") as open_url,
                    patch("pastor_transcript_extractor.cli.typer.confirm", side_effect=RuntimeError("stop")),
                    self.assertRaisesRegex(RuntimeError, "stop"),
                ):
                    review_ground_truth(
                        "abc123",
                        reviewer="reviewer",
                        evaluation_dir=Path(tmp) / "evaluation",
                        open_video=True,
                        base_dir=None,
                    )
                open_url.assert_called_once_with(expected_url)

    def test_parses_absolute_and_relative_timestamps(self) -> None:
        self.assertEqual(5926.0, parse_timestamp("1:38:46"))
        self.assertEqual(105.0, parse_timestamp("+5", current=100.0))
        self.assertEqual(70.0, parse_timestamp("-30", current=100.0))

    def test_parses_interruptions_and_splits_retained_spans(self) -> None:
        interruptions = parse_interruptions("2:00-2:30, 4:00-4:10")
        spans = retained_spans(60.0, 300.0, interruptions)
        self.assertEqual([(60.0, 120.0), (150.0, 240.0), (250.0, 300.0)], spans)

    def test_approved_payload_passes_fixture_validation(self) -> None:
        manifest = {
            "selector_version": "sermon_fixture_selector_v1",
            "selection_origin": "automatic",
            "selection_stratum": "no_candidate",
            "corpus_snapshot_fingerprint": "f" * 64,
            "reason_codes": ["stratum_no_candidate"],
        }
        fixture = approved_fixture_payload(
            video_id="abc123",
            start_seconds=60.0,
            end_seconds=300.0,
            interruptions=[(120.0, 150.0)],
            reviewer="reviewer",
            failure_mode="incorrect_rule_window",
            notes="Reviewed against video.",
            selection_manifest=manifest,
        )
        validated = validate_fixture_payload(fixture, path=Path("abc123.json"))
        self.assertEqual([(60.0, 120.0), (150.0, 300.0)], validated.expected_spans)
        self.assertEqual("sermon", fixture["expected_outcome"])
        self.assertEqual(manifest, fixture["selection_manifest"])
        self.assertNotIn("expected_outcome", manifest)

    def test_suggestion_prefers_classification_candidate_over_rule_window(self) -> None:
        payload = {
            "classification": {
                "method": "adaptive_llm_v3",
                "retained_segment_indexes": [1, 2],
            },
            "sermon_window": {"start_seconds": 10.0, "end_seconds": 20.0},
            "segments": [
                {"start_seconds": 0.0, "end_seconds": 10.0, "text": "noise"},
                {"start_seconds": 100.0, "end_seconds": 150.0, "text": "start"},
                {"start_seconds": 150.0, "end_seconds": 220.0, "text": "end"},
            ],
        }
        self.assertEqual((100.0, 220.0, "adaptive_llm_v3"), suggested_envelope(payload))

    def test_suggestion_uses_full_video_when_no_candidate_exists(self) -> None:
        payload = {"segments": [{"start_seconds": 0.0, "end_seconds": 69.0, "text": "test"}]}
        self.assertEqual(
            (0.0, 69.0, "no_candidate_full_video"),
            suggested_envelope(payload, fallback_end_seconds=69.0),
        )

    def test_context_marks_segment_containing_boundary(self) -> None:
        context = transcript_context(
            [
                {"start_seconds": 90.0, "end_seconds": 110.0, "text": "Our sermon title today"},
                {"start_seconds": 110.0, "end_seconds": 130.0, "text": "Let us pray"},
            ],
            100.0,
        )
        self.assertIn("> [0:01:30] Our sermon title today", context)

    def test_negative_payload_passes_fixture_validation(self) -> None:
        fixture = approved_negative_fixture_payload(
            video_id="negative123",
            reviewer="reviewer",
            failure_mode="non_sermon_event",
            notes="Reviewed the complete graduation ceremony.",
        )
        validated = validate_fixture_payload(fixture, path=Path("negative.json"))
        self.assertEqual("no_sermon", validated.expected_outcome)
        self.assertEqual([], validated.expected_spans)

    def test_youtube_timestamp_url_replaces_existing_time_and_supports_zero(self) -> None:
        self.assertEqual(
            "https://www.youtube.com/watch?v=abc123&t=0s",
            youtube_timestamp_url("https://www.youtube.com/watch?v=abc123&t=99s", 0.0),
        )
        self.assertEqual(
            "https://youtu.be/abc123?t=65s",
            youtube_timestamp_url("https://youtu.be/abc123", 65.9),
        )

    def test_open_video_url_uses_cross_platform_browser_launcher(self) -> None:
        with patch(
            "pastor_transcript_extractor.ground_truth_review.webbrowser.open",
            return_value=True,
        ) as browser_open:
            open_video_url("https://www.youtube.com/watch?v=abc&t=0s")
        browser_open.assert_called_once_with(
            "https://www.youtube.com/watch?v=abc&t=0s",
            new=2,
            autoraise=True,
        )

    def test_positive_review_omits_redundant_checks_and_defaults_write_to_yes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            proposed_path = root / "proposed.json"
            proposed_path.write_text(
                json.dumps(
                    {
                        "segments": [
                            {"start_seconds": 10.0, "end_seconds": 100.0, "text": "sermon"}
                        ],
                        "classification": {
                            "method": "adaptive_llm_v3",
                            "retained_segment_indexes": [0],
                        },
                    }
                ),
                encoding="utf-8",
            )
            database = SimpleNamespace(
                get_video_by_youtube_id=lambda _: SimpleNamespace(
                    id=1,
                    url="https://www.youtube.com/watch?v=abc123",
                    title="Fixture",
                    duration_seconds=100,
                ),
                get_latest_extraction_result_for_video=lambda _: SimpleNamespace(
                    proposed_json_path=str(proposed_path)
                ),
            )
            with (
                patch("pastor_transcript_extractor.cli.get_database", return_value=database),
                patch(
                    "pastor_transcript_extractor.cli.typer.prompt",
                    side_effect=["0:00:10", "0:01:40", "", "unknown", ""],
                ),
                patch(
                    "pastor_transcript_extractor.cli.typer.confirm", return_value=True
                ) as confirm,
            ):
                review_ground_truth(
                    "abc123",
                    reviewer="reviewer",
                    evaluation_dir=root / "evaluation",
                    open_video=False,
                    base_dir=None,
                )

            prompts = [call.args[0] for call in confirm.call_args_list]
            self.assertNotIn(
                "Have you reviewed the entire sermon envelope for missing sermon content?",
                prompts,
            )
            self.assertNotIn(
                "Are all listed interruptions genuinely non-sermon content?",
                prompts,
            )
            final = confirm.call_args_list[-1]
            self.assertEqual(
                "Write this manually approved ground-truth fixture?", final.args[0]
            )
            self.assertTrue(final.kwargs["default"])

    def test_negative_review_omits_redundant_check_and_defaults_write_to_yes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            proposed_path = root / "proposed.json"
            proposed_path.write_text(
                json.dumps(
                    {
                        "segments": [
                            {"start_seconds": 0.0, "end_seconds": 100.0, "text": "event"}
                        ]
                    }
                ),
                encoding="utf-8",
            )
            database = SimpleNamespace(
                get_video_by_youtube_id=lambda _: SimpleNamespace(
                    id=1,
                    url="https://www.youtube.com/watch?v=negative123",
                    title="Negative fixture",
                    duration_seconds=100,
                ),
                get_latest_extraction_result_for_video=lambda _: SimpleNamespace(
                    proposed_json_path=str(proposed_path)
                ),
            )
            with (
                patch("pastor_transcript_extractor.cli.get_database", return_value=database),
                patch(
                    "pastor_transcript_extractor.cli.typer.prompt",
                    side_effect=["non_sermon_event", "No worship-service sermon found."],
                ),
                patch(
                    "pastor_transcript_extractor.cli.typer.confirm",
                    side_effect=[False, True],
                ) as confirm,
            ):
                review_ground_truth(
                    "negative123",
                    reviewer="reviewer",
                    evaluation_dir=root / "evaluation",
                    open_video=False,
                    base_dir=None,
                )

            prompts = [call.args[0] for call in confirm.call_args_list]
            self.assertNotIn(
                "Have you reviewed the entire video and confirmed there is no "
                "worship-service sermon?",
                prompts,
            )
            final = confirm.call_args_list[-1]
            self.assertEqual(
                "Write this manually approved negative fixture?", final.args[0]
            )
            self.assertTrue(final.kwargs["default"])

    def test_review_next_ground_truth_excludes_existing_draft_and_delegates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            evaluation = root / "evaluation"
            (evaluation / "drafts").mkdir(parents=True)
            (evaluation / "drafts" / "video1.json").write_text(
                json.dumps({"video_id": "video1", "review_status": "unreviewed"}),
                encoding="utf-8",
            )
            videos = []
            extractions = {}
            for index in (1, 2):
                proposed = root / f"proposed-{index}.json"
                proposed.write_text(
                    json.dumps(
                        {
                            "segments": [{"start_seconds": 0, "end_seconds": 100, "text": "text"}],
                            "classification": {
                                "method": "adaptive_llm_v3",
                                "retained_segment_indexes": [0],
                                "confidence_tier": "medium",
                            },
                        }
                    ),
                    encoding="utf-8",
                )
                videos.append(
                    SimpleNamespace(
                        id=index,
                        youtube_video_id=f"video{index}",
                        pastor_id=1,
                        source_id=1,
                        published_at=None,
                        duration_seconds=100,
                    )
                )
                extractions[index] = SimpleNamespace(proposed_json_path=str(proposed))
            database = SimpleNamespace(
                list_videos=lambda: videos,
                get_latest_extraction_result_for_video=lambda video_id: extractions[video_id],
                get_source_by_id=lambda _: SimpleNamespace(url="https://example.test/channel"),
                get_latest_transcript_artifact_for_video=lambda _: SimpleNamespace(
                    source_kind=SimpleNamespace(value="captions")
                ),
            )
            registry_path = root / "source-families.json"
            registry_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "registry_version": "test-v1",
                        "partition_policy": {
                            "version": "source_family_partition_v1",
                            "salt": "test",
                            "development_percent": 60,
                            "validation_percent": 20,
                        },
                        "source_families": [
                            {
                                "source_family_id": "family-a",
                                "source_urls": ["https://example.test/channel"],
                                "partition": "development",
                                "partition_origin": "manual",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            with (
                patch("pastor_transcript_extractor.cli.get_database", return_value=database),
                patch("pastor_transcript_extractor.cli.review_ground_truth") as review,
            ):
                review_next_ground_truth(
                    reviewer="reviewer",
                    evaluation_dir=evaluation,
                    source_family_registry=registry_path,
                    open_video=False,
                    base_dir=None,
                )

            self.assertEqual("video2", review.call_args.kwargs["youtube_video_id"])
            manifest = json.loads(review.call_args.kwargs["selection_manifest_json"])
            self.assertEqual("automatic", manifest["selection_origin"])
            self.assertEqual("sermon_fixture_selector_v2", manifest["selector_version"])
            self.assertEqual("family-a", manifest["source_family_id"])
            self.assertNotIn("source_family_unrepresented", manifest["reason_codes"])
            self.assertNotIn("expected_outcome", manifest)

    def test_manual_resume_preserves_automatic_selection_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            proposed_path = root / "proposed.json"
            proposed_path.write_text(
                json.dumps({"segments": [{"start_seconds": 0, "end_seconds": 69, "text": "test"}]}),
                encoding="utf-8",
            )
            evaluation = root / "evaluation"
            (evaluation / "drafts").mkdir(parents=True)
            manifest = {
                "selector_version": "sermon_fixture_selector_v1",
                "selection_origin": "automatic",
                "selection_stratum": "no_candidate",
                "corpus_snapshot_fingerprint": "f" * 64,
                "reason_codes": ["stratum_no_candidate"],
            }
            (evaluation / "drafts" / "abc123.json").write_text(
                json.dumps({"video_id": "abc123", "selection_manifest": manifest}),
                encoding="utf-8",
            )
            database = SimpleNamespace(
                get_video_by_youtube_id=lambda _: SimpleNamespace(
                    id=1,
                    url="https://www.youtube.com/watch?v=abc123",
                    title="Fixture",
                    duration_seconds=69,
                ),
                get_latest_extraction_result_for_video=lambda _: SimpleNamespace(
                    proposed_json_path=str(proposed_path)
                ),
            )
            with (
                patch("pastor_transcript_extractor.cli.get_database", return_value=database),
                patch("pastor_transcript_extractor.cli.typer.confirm", side_effect=RuntimeError("stop")),
                self.assertRaisesRegex(RuntimeError, "stop"),
            ):
                review_ground_truth(
                    "abc123",
                    reviewer="reviewer",
                    evaluation_dir=evaluation,
                    open_video=False,
                    base_dir=None,
                )

            rewritten = json.loads((evaluation / "drafts" / "abc123.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest, rewritten["selection_manifest"])


if __name__ == "__main__":
    unittest.main()
