from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from pastor_transcript_extractor.models import Video, VideoStatus
from pastor_transcript_extractor.sermon_topic_stage4 import (
    assess_topic_stage4_readiness,
    evaluate_topic_stage4,
    load_topic_stage4_cohort,
    summarize_topic_stage4_pastor,
    write_topic_stage4_report,
)
from pastor_transcript_extractor.sermon_topics import TOPICS


class _Database:
    def __init__(self, videos: list[Video]) -> None:
        self._videos = videos

    def list_videos(self) -> list[Video]:
        return self._videos


def _video(video_id: int) -> Video:
    return Video(
        id=video_id,
        source_id=1,
        pastor_id=None,
        youtube_video_id=f"youtube-{video_id}",
        title=f"Sermon {video_id}",
        url=f"https://www.youtube.com/watch?v=youtube-{video_id}",
        channel_name=None,
        published_at=None,
        duration_seconds=60,
        status=VideoStatus.EXTRACTED,
    )


def _cohort(*, missing_period: bool = False) -> dict[str, object]:
    return {
        "cohort_id": "stage4-test",
        "cohort_sha256": "cohort",
        "question_pack_version": "topics-v3-mission-discourse-boundary",
        "pastors": [
            {
                "pastor_id": 1,
                "display_name": "Test Pastor",
                "slug": "test-pastor",
                "sermons": [
                    {
                        "video_id": 1,
                        "youtube_video_id": "youtube-1",
                        "series_key": "series-a",
                        "period_key": "period-a",
                    },
                    {
                        "video_id": 2,
                        "youtube_video_id": "youtube-2",
                        "series_key": "series-b",
                        "period_key": None if missing_period else "period-b",
                    },
                    {
                        "video_id": 3,
                        "youtube_video_id": "youtube-3",
                        "series_key": "series-b",
                        "period_key": "period-b",
                    },
                ],
            }
        ],
    }


def _gate(
    video_id: int,
    *,
    profile_id: int = 7,
    eligible: bool = True,
) -> SimpleNamespace:
    return SimpleNamespace(
        eligible=eligible,
        input_fingerprint=f"gate-{video_id}-{profile_id}-{eligible}",
        profile_id=profile_id,
        reason_codes=() if eligible else ("disposition_not_accepted",),
        topic_question_pack_version="topics-v3-mission-discourse-boundary",
    )


class SermonTopicStage4Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.database = _Database([_video(1), _video(2), _video(3)])

    def test_ready_requires_one_reviewed_profile_and_independent_strata(self) -> None:
        gates = {video_id: _gate(video_id) for video_id in (1, 2, 3)}
        with patch(
            "pastor_transcript_extractor.sermon_topic_stage4."
            "assess_topic_profile_projection",
            side_effect=lambda _database, video: gates[video.id],
        ):
            report = assess_topic_stage4_readiness(self.database, _cohort())

        self.assertTrue(report["ready"])
        self.assertEqual([], report["blockers"])
        self.assertEqual([7], report["pastors"][0]["effective_profile_ids"])
        self.assertEqual(
            ["period-a", "period-b"],
            report["pastors"][0]["period_keys"],
        )

    def test_split_identity_ineligible_sermon_and_missing_period_are_visible(self) -> None:
        gates = {
            1: _gate(1, profile_id=7),
            2: _gate(2, profile_id=8),
            3: _gate(3, profile_id=8, eligible=False),
        }
        with patch(
            "pastor_transcript_extractor.sermon_topic_stage4."
            "assess_topic_profile_projection",
            side_effect=lambda _database, video: gates[video.id],
        ):
            report = assess_topic_stage4_readiness(
                self.database,
                _cohort(missing_period=True),
            )

        self.assertFalse(report["ready"])
        blockers = report["pastors"][0]["blockers"]
        self.assertIn("split_effective_profile_membership", blockers)
        self.assertIn("disposition_not_accepted", blockers)
        self.assertIn("incomplete_eligible_sermon_set", blockers)
        self.assertIn("period_metadata_missing", blockers)

    def test_loader_rejects_duplicate_videos_and_fingerprints_exact_file(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            path = Path(tempdir) / "cohort.json"
            cohort = _cohort()
            path.write_text(json.dumps(cohort), encoding="utf-8")
            loaded = load_topic_stage4_cohort(path)
            self.assertEqual(str(path.resolve()), loaded["cohort_path"])
            self.assertEqual(64, len(loaded["cohort_sha256"]))

            cohort["pastors"][0]["sermons"][2]["video_id"] = 1
            path.write_text(json.dumps(cohort), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Duplicate"):
                load_topic_stage4_cohort(path)

    def test_diagnostics_keep_sermons_visible_and_compare_declared_strata(self) -> None:
        sermons = []
        for video_id, support, expected, series, period in (
            (1, 0.1, 0.2, "series-a", "period-a"),
            (2, 0.4, 0.5, "series-b", "period-a"),
            (3, 0.7, 0.8, "series-b", "period-b"),
        ):
            sermons.append(
                {
                    "period_key": period,
                    "profile_id": 7,
                    "series_key": series,
                    "sermon_analysis_input_fingerprint": f"run-{video_id}",
                    "sermon_analysis_run_id": video_id,
                    "topic_measurements": {
                        topic: {
                            "developed_emphasis_probability": support,
                            "normalized_expected_prominence": expected,
                        }
                        for topic in TOPICS
                    },
                    "video_id": video_id,
                    "youtube_video_id": f"youtube-{video_id}",
                }
            )

        report = summarize_topic_stage4_pastor(
            _cohort()["pastors"][0],
            sermons,
        )
        metrics = report["topics"]["discipleship_spiritual_formation"]
        primary = metrics["developed_emphasis_probability"]
        sensitivity = metrics["normalized_expected_prominence_sensitivity"]

        self.assertEqual(0.4, primary["equal_sermon_mean"])
        self.assertEqual(0.15, primary["leave_one_sermon_max_absolute_delta"])
        self.assertEqual(0.45, primary["maximum_between_series_delta"])
        self.assertEqual(0.45, primary["maximum_between_period_delta"])
        self.assertEqual(0.5, sensitivity["equal_sermon_mean"])
        self.assertEqual(3, len(report["sermons"]))

    def test_report_writer_reuses_exact_fingerprint(self) -> None:
        report = {
            "input_fingerprint": "fingerprint",
            "status": "diagnostic_only_threshold_not_calibrated",
            "comparative_use_allowed": False,
            "interpretation": "Diagnostic only.",
            "pastors": [],
        }
        with tempfile.TemporaryDirectory() as tempdir:
            path = Path(tempdir) / "report.json"
            first = write_topic_stage4_report(path, report)
            replay = write_topic_stage4_report(path, report)

            self.assertFalse(first[2])
            self.assertTrue(replay[2])
            self.assertTrue(path.with_suffix(".md").exists())

    def test_evaluation_fails_before_materialization_when_readiness_blocks(self) -> None:
        with patch(
            "pastor_transcript_extractor.sermon_topic_stage4."
            "assess_topic_stage4_readiness",
            return_value={"ready": False, "blockers": ["identity"]},
        ):
            with self.assertRaisesRegex(ValueError, "identity"):
                evaluate_topic_stage4(self.database, _cohort())


if __name__ == "__main__":
    unittest.main()
