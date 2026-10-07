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
    load_topic_stage4_cohort,
)


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


if __name__ == "__main__":
    unittest.main()
