from __future__ import annotations

import unittest
from pathlib import Path

from pastor_transcript_extractor.fixture_validation import validate_fixture_payload
from pastor_transcript_extractor.ground_truth_review import (
    approved_negative_fixture_payload,
    approved_fixture_payload,
    parse_interruptions,
    parse_timestamp,
    retained_spans,
    suggested_envelope,
    transcript_context,
    youtube_timestamp_url,
)


class GroundTruthReviewTests(unittest.TestCase):
    def test_parses_absolute_and_relative_timestamps(self) -> None:
        self.assertEqual(5926.0, parse_timestamp("1:38:46"))
        self.assertEqual(105.0, parse_timestamp("+5", current=100.0))
        self.assertEqual(70.0, parse_timestamp("-30", current=100.0))

    def test_parses_interruptions_and_splits_retained_spans(self) -> None:
        interruptions = parse_interruptions("2:00-2:30, 4:00-4:10")
        spans = retained_spans(60.0, 300.0, interruptions)
        self.assertEqual([(60.0, 120.0), (150.0, 240.0), (250.0, 300.0)], spans)

    def test_approved_payload_passes_fixture_validation(self) -> None:
        fixture = approved_fixture_payload(
            video_id="abc123",
            start_seconds=60.0,
            end_seconds=300.0,
            interruptions=[(120.0, 150.0)],
            reviewer="reviewer",
            failure_mode="incorrect_rule_window",
            notes="Reviewed against video.",
        )
        validated = validate_fixture_payload(fixture, path=Path("abc123.json"))
        self.assertEqual([(60.0, 120.0), (150.0, 300.0)], validated.expected_spans)

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


if __name__ == "__main__":
    unittest.main()
