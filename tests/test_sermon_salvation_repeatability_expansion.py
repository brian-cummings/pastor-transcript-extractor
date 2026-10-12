from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from pastor_transcript_extractor.sermon_salvation_repeatability_expansion import (
    build_salvation_repeatability_expansion_plan,
    evaluate_salvation_repeatability_expansion_plan,
)


class SalvationRepeatabilityExpansionTests(unittest.TestCase):
    def test_builds_inventory_without_assigning_series_from_titles(self) -> None:
        cohort = {
            "cohort_id": "cohort",
            "cohort_sha256": "c" * 64,
            "pastors": [
                {
                    "display_name": "Pastor Example",
                    "pastor_id": 7,
                    "slug": "pastor-example",
                    "sermons": [
                        {"video_id": 1},
                        {"video_id": 2},
                        {"video_id": 3},
                    ],
                }
            ],
        }
        readiness = {
            "ready": True,
            "input_fingerprint": "r" * 64,
            "pastors": [{"effective_profile_ids": [42]}],
        }
        candidates = [
            {
                "profile_id": 42,
                "video_id": video_id,
                "youtube_video_id": f"youtube-{video_id}",
                "title": f"Series-like title {video_id}",
                "published_at": f"2026-01-{video_id:02d}T00:00:00",
                "period_key": "2026-h1",
                "eligible_block_count": 5,
                "gate_input_fingerprint": str(video_id) * 64,
            }
            for video_id in range(1, 13)
        ]

        report = build_salvation_repeatability_expansion_plan(
            candidates,
            cohort,
            readiness,
        )

        pastor = report["pastors"][0]
        self.assertEqual(12, pastor["eligible_candidate_count"])
        self.assertEqual(
            "candidate_count_sufficient_series_review_required",
            pastor["selection_status"],
        )
        self.assertTrue(pastor["candidates"][0]["already_in_baseline"])
        self.assertNotIn("series_key", pastor["candidates"][0])
        self.assertEqual(0, report["provider_requests"])
        self.assertEqual(
            [3, 4, 5, 6, 8, 10, 12],
            report["selection_contract"]["convergence_sample_sizes"],
        )

    def test_evaluator_rejects_production_ineligible_videos_before_gate(self) -> None:
        cohort = {
            "cohort_id": "cohort",
            "pastors": [
                {
                    "display_name": "Pastor Example",
                    "sermons": [{"video_id": 1}],
                }
            ],
        }
        readiness = {
            "ready": True,
            "input_fingerprint": "r" * 64,
            "pastors": [{"effective_profile_ids": [42]}],
        }
        video = Mock(duration_seconds=10, published_at=None)
        database = Mock()
        database.list_videos.return_value = [video]
        with (
            patch(
                "pastor_transcript_extractor.sermon_salvation_repeatability_expansion.assess_topic_stage4_readiness",
                return_value=readiness,
            ),
            patch(
                "pastor_transcript_extractor.sermon_salvation_repeatability_expansion.assess_topic_profile_projection"
            ) as gate,
        ):
            report = evaluate_salvation_repeatability_expansion_plan(
                database,
                cohort,
            )

        gate.assert_not_called()
        self.assertEqual(0, report["pastors"][0]["eligible_candidate_count"])


if __name__ == "__main__":
    unittest.main()
