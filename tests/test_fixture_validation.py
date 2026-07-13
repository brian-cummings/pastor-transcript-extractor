from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
