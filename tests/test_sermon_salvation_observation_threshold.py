from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from pastor_transcript_extractor.sermon_salvation_observation_threshold import (
    AMBIGUOUS_SALVATION_OBSERVATION_CALIBRATION,
    SETTLED_SALVATION_OBSERVATION_THRESHOLDS,
    build_salvation_observation_boundaries_review,
    build_salvation_observation_threshold_review,
    write_salvation_observation_boundaries_review,
    write_salvation_observation_threshold_review,
)
from pastor_transcript_extractor.sermon_salvation_relationships import (
    SALVATION_RELATIONSHIPS,
    SALVATION_RELATIONSHIPS_PACK_VERSION,
)


def _case(video_id: int, block_id: int, probability: float) -> dict[str, object]:
    return {
        "pastor": {"display_name": "Pastor", "slug": "pastor"},
        "video_id": video_id,
        "youtube_video_id": f"youtube-{video_id}",
        "title": f"Sermon {video_id}",
        "block_id": block_id,
        "start_seconds": 60.0,
        "end_seconds": 120.0,
        "leading_context": "Leading.",
        "target_text": "Target.",
        "trailing_context": "Trailing.",
        "leaf_probabilities": {
            relationship: probability
            for relationship in SALVATION_RELATIONSHIPS
        },
    }


class SalvationObservationThresholdTests(unittest.TestCase):
    def test_focuses_per_relationship_review_on_ambiguous_windows(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            paths = (root / "v2.json", root / "v3.json")
            packets = (
                {
                    "input_fingerprint": "v2-fingerprint",
                    "leaf_pack_version": SALVATION_RELATIONSHIPS_PACK_VERSION,
                    "cases": [_case(1, 10, 0.59)],
                },
                {
                    "input_fingerprint": "v3-fingerprint",
                    "leaf_pack_version": SALVATION_RELATIONSHIPS_PACK_VERSION,
                    "cases": [_case(2, 20, 0.69)],
                },
            )
            for path, packet in zip(paths, packets, strict=True):
                path.write_text(json.dumps(packet), encoding="utf-8")

            review = build_salvation_observation_boundaries_review(paths)

            self.assertEqual(
                set(SETTLED_SALVATION_OBSERVATION_THRESHOLDS),
                set(review["settled_thresholds"]),
            )
            self.assertEqual(
                set(AMBIGUOUS_SALVATION_OBSERVATION_CALIBRATION),
                set(review["ambiguous_calibration"]),
            )
            self.assertTrue(
                all(
                    probe["relationship"]
                    in AMBIGUOUS_SALVATION_OBSERVATION_CALIBRATION
                    for probe in review["probes"]
                )
            )
            self.assertFalse(
                any(
                    probe["relationship"]
                    in SETTLED_SALVATION_OBSERVATION_THRESHOLDS
                    for probe in review["probes"]
                )
            )

            output = root / "boundaries.json"
            _json_path, _markdown_path, reused = (
                write_salvation_observation_boundaries_review(output, review)
            )
            self.assertFalse(reused)
            _json_path, _markdown_path, reused = (
                write_salvation_observation_boundaries_review(output, review)
            )
            self.assertTrue(reused)

    def test_builds_two_sided_probe_for_every_relationship(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            paths = (root / "v2.json", root / "v3.json")
            packets = (
                {
                    "input_fingerprint": "v2-fingerprint",
                    "leaf_pack_version": SALVATION_RELATIONSHIPS_PACK_VERSION,
                    "cases": [_case(1, 10, 0.69)],
                },
                {
                    "input_fingerprint": "v3-fingerprint",
                    "leaf_pack_version": SALVATION_RELATIONSHIPS_PACK_VERSION,
                    "cases": [_case(2, 20, 0.71)],
                },
            )
            for path, packet in zip(paths, packets, strict=True):
                path.write_text(json.dumps(packet), encoding="utf-8")

            review = build_salvation_observation_threshold_review(paths)

            self.assertEqual(24, review["judgment_count"])
            self.assertEqual(24, len(review["probes"]))
            self.assertEqual(12, review["counts_by_threshold"]["0.70"])
            self.assertEqual(
                {"below", "at_or_above"},
                {
                    probe["boundary_side"]
                    for probe in review["probes"]
                    if probe["relationship"] == SALVATION_RELATIONSHIPS[0]
                },
            )

            output = root / "review.json"
            _json_path, _markdown_path, reused = (
                write_salvation_observation_threshold_review(output, review)
            )
            self.assertFalse(reused)
            _json_path, _markdown_path, reused = (
                write_salvation_observation_threshold_review(output, review)
            )
            self.assertTrue(reused)

    def test_exposes_one_sided_threshold_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            paths = (root / "v2.json", root / "v3.json")
            for index, path in enumerate(paths):
                path.write_text(
                    json.dumps(
                        {
                            "input_fingerprint": f"fingerprint-{index}",
                            "leaf_pack_version": (
                                SALVATION_RELATIONSHIPS_PACK_VERSION
                            ),
                            "cases": [_case(index + 1, index + 10, 0.4)],
                        }
                    ),
                    encoding="utf-8",
                )

            review = build_salvation_observation_threshold_review(paths)

            self.assertEqual(12, len(review["probes"]))
            self.assertTrue(
                all(
                    sides == ["strongest_available_below"]
                    for sides in review["probe_sides_by_relationship"].values()
                )
            )


if __name__ == "__main__":
    unittest.main()
