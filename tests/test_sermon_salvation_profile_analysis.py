from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from pastor_transcript_extractor.sermon_salvation_profile_analysis import (
    APPROVED_SALVATION_COLLECTION_REVIEW_FINGERPRINT,
    build_salvation_profile_repeatability,
    write_salvation_profile_repeatability,
)
from pastor_transcript_extractor.sermon_salvation_relationships import (
    SALVATION_RELATIONSHIP_MEASUREMENT_STATUSES,
    SALVATION_RELATIONSHIP_OBSERVATION_POLICY_VERSION,
    SALVATION_RELATIONSHIP_OBSERVATION_THRESHOLDS,
    SALVATION_RELATIONSHIPS_PACK_VERSION,
    UNRESOLVED_SALVATION_RELATIONSHIP_OBSERVATIONS,
)


class SalvationProfileRepeatabilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.cohort = {
            "cohort_id": "cohort",
            "cohort_sha256": "c" * 64,
            "pastors": [
                {
                    "display_name": "Pastor Example",
                    "pastor_id": 7,
                    "slug": "pastor-example",
                    "sermons": [
                        {
                            "video_id": 1,
                            "series_key": "a",
                            "period_key": "early",
                        },
                        {
                            "video_id": 2,
                            "series_key": "b",
                            "period_key": "late",
                        },
                        {
                            "video_id": 3,
                            "series_key": "c",
                            "period_key": "late",
                        },
                    ],
                }
            ],
        }
        self.readiness = {
            "ready": True,
            "input_fingerprint": "r" * 64,
            "pastors": [{"effective_profile_ids": [42]}],
        }
        self.review = {
            "input_fingerprint": APPROVED_SALVATION_COLLECTION_REVIEW_FINGERPRINT,
            "question_pack_version": SALVATION_RELATIONSHIPS_PACK_VERSION,
            "observation_policy_version": SALVATION_RELATIONSHIP_OBSERVATION_POLICY_VERSION,
            "observation_thresholds": dict(
                SALVATION_RELATIONSHIP_OBSERVATION_THRESHOLDS
            ),
            "measurement_statuses": dict(
                SALVATION_RELATIONSHIP_MEASUREMENT_STATUSES
            ),
            "cohort_sha256": self.cohort["cohort_sha256"],
            "readiness_input_fingerprint": self.readiness["input_fingerprint"],
            "source_artifacts": [
                {
                    "video_id": video_id,
                    "stored_artifact_sha256": str(video_id) * 64,
                    "effective_artifact_sha256": str(video_id) * 64,
                }
                for video_id in (1, 2, 3)
            ],
        }

    @staticmethod
    def _source(video_id: int, routed_count: int, *, observed: bool) -> dict:
        blocks = []
        for block_id in range(routed_count):
            observations = []
            if observed and block_id == 0:
                observations.append(
                    {
                        "relationship": "divine_grace_initiative",
                        "probability": 0.9,
                        "threshold": 0.65,
                    }
                )
            blocks.append(
                {
                    "block_id": block_id,
                    "route": {"route": True},
                    "observations": observations,
                }
            )
        return {
            "pastor": {"display_name": "Pastor Example", "pastor_id": 7},
            "video_id": video_id,
            "youtube_video_id": f"youtube-{video_id}",
            "title": f"Sermon {video_id}",
            "stored_artifact_sha256": str(video_id) * 64,
            "artifact": {
                "routed_block_count": routed_count,
                "blocks": blocks,
            },
        }

    def test_uses_equal_sermon_weighting_and_excludes_unresolved_leaves(self) -> None:
        report = build_salvation_profile_repeatability(
            [
                self._source(1, 1, observed=True),
                self._source(2, 10, observed=False),
                self._source(3, 10, observed=False),
            ],
            self.cohort,
            self.readiness,
            self.review,
        )

        grace = report["pastors"][0]["relationships"]["divine_grace_initiative"]
        self.assertEqual(0.333333, grace["equal_sermon_mean"])
        self.assertEqual(1, grace["sermons_with_observation"])
        self.assertEqual(1, grace["total_observation_count"])
        self.assertEqual(
            sorted(UNRESOLVED_SALVATION_RELATIONSHIP_OBSERVATIONS),
            report["unresolved_relationships"],
        )
        for unresolved in UNRESOLVED_SALVATION_RELATIONSHIP_OBSERVATIONS:
            self.assertNotIn(unresolved, report["measured_relationships"])
            self.assertNotIn(unresolved, report["pastors"][0]["relationships"])
        self.assertFalse(report["comparative_use_allowed"])
        self.assertEqual(0, report["provider_requests"])

    def test_rejects_unapproved_collection_review(self) -> None:
        review = {**self.review, "input_fingerprint": "wrong"}
        with self.assertRaisesRegex(ValueError, "approved nine-leaf"):
            build_salvation_profile_repeatability(
                [
                    self._source(1, 1, observed=True),
                    self._source(2, 1, observed=False),
                    self._source(3, 1, observed=False),
                ],
                self.cohort,
                self.readiness,
                review,
            )

    def test_writer_reuses_matching_fingerprint(self) -> None:
        report = build_salvation_profile_repeatability(
            [
                self._source(1, 1, observed=True),
                self._source(2, 1, observed=False),
                self._source(3, 1, observed=False),
            ],
            self.cohort,
            self.readiness,
            self.review,
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.json"
            _, _, reused = write_salvation_profile_repeatability(path, report)
            self.assertFalse(reused)
            json_before = path.read_bytes()
            markdown_before = path.with_suffix(".md").read_bytes()

            _, _, reused = write_salvation_profile_repeatability(path, report)

            self.assertTrue(reused)
            self.assertEqual(json_before, path.read_bytes())
            self.assertEqual(markdown_before, path.with_suffix(".md").read_bytes())


if __name__ == "__main__":
    unittest.main()
