from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from pastor_transcript_extractor.models import Video, VideoStatus
from pastor_transcript_extractor.sermon_salvation_routing import (
    PRIOR_CALIBRATION_FINGERPRINT,
    PROPOSED_SALVATION_ROUTE_THRESHOLD,
    build_salvation_routing_review_packet,
    write_salvation_routing_review,
)
from pastor_transcript_extractor.sermon_topics import TOPICS, TOPIC_PACK_VERSION


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
        duration_seconds=1200,
        status=VideoStatus.EXTRACTED,
    )


def _score(*, support: float, incidental: float = 0.0) -> dict[str, object]:
    return {
        "score": incidental + 2 * support,
        "probabilities": {
            "0": 1.0 - support - incidental,
            "1": incidental,
            "2": support,
            "3": 0.0,
            "4": 0.0,
        },
        "confidence": 0.5,
    }


def _block(block_id: int, support: float) -> dict[str, object]:
    scores = {topic: _score(support=0.0) for topic in TOPICS}
    scores["salvation_gospel"] = (
        _score(support=support, incidental=0.9)
        if support == 0.02
        else _score(support=support)
    )
    return {
        "block_id": block_id,
        "start_seconds": float(block_id * 60),
        "end_seconds": float((block_id + 1) * 60),
        "context": {
            "leading_context": f"Leading {block_id}",
            "target_text": f"Target {block_id}",
            "trailing_context": f"Trailing {block_id}",
        },
        "content_role": "principal_sermon",
        "projection_eligibility": {"eligible": True, "exclusion_reasons": []},
        "reliability": {"sparse": False},
        "scores": scores,
        "request_key": f"request-{block_id}",
    }


class SalvationRoutingReviewTests(unittest.TestCase):
    def setUp(self) -> None:
        self.videos = [_video(1), _video(2)]
        self.database = _Database(self.videos)
        self.cohort = {
            "cohort_sha256": "cohort-sha",
            "pastors": [
                {
                    "display_name": "Pastor One",
                    "pastor_id": 1,
                    "slug": "pastor-one",
                    "sermons": [{"video_id": 1}],
                },
                {
                    "display_name": "Pastor Two",
                    "pastor_id": 2,
                    "slug": "pastor-two",
                    "sermons": [{"video_id": 2}],
                },
            ],
        }

    def _analysis(self, video_id: int):
        offset = video_id * 10
        return {
            "question_pack_version": TOPIC_PACK_VERSION,
            "blocks": [
                _block(offset + 1, 0.95),
                _block(offset + 2, 0.02),
                _block(offset + 3, 0.66),
                _block(offset + 4, 0.64),
            ],
        }

    def test_packet_samples_only_revised_boundary_without_activating_route(
        self,
    ) -> None:
        gates = {
            video.id: SimpleNamespace(
                eligible=True,
                source_path=f"/cached/{video.id}.json",
                topic_analysis_fingerprint=f"topic-{video.id}",
                video_id=video.id,
            )
            for video in self.videos
        }
        with (
            patch(
                "pastor_transcript_extractor.sermon_salvation_routing."
                "assess_topic_stage4_readiness",
                return_value={
                    "ready": True,
                    "blockers": [],
                    "input_fingerprint": "readiness-fingerprint",
                },
            ),
            patch(
                "pastor_transcript_extractor.sermon_salvation_routing."
                "assess_topic_profile_projection",
                side_effect=lambda _database, video: gates[video.id],
            ),
            patch(
                "pastor_transcript_extractor.sermon_salvation_routing."
                "read_topic_analysis_for_gate",
                side_effect=lambda gate: (self._analysis(gate.video_id), {}),
            ),
        ):
            packet = build_salvation_routing_review_packet(
                self.database,
                self.cohort,
            )
            replay = build_salvation_routing_review_packet(
                self.database,
                self.cohort,
            )

        self.assertEqual(8, packet["candidate_count"])
        self.assertEqual(4, packet["proposed_route_count"])
        self.assertEqual(0.65, PROPOSED_SALVATION_ROUTE_THRESHOLD)
        self.assertEqual(
            PRIOR_CALIBRATION_FINGERPRINT,
            packet["prior_calibration"]["input_fingerprint"],
        )
        self.assertEqual(4, len(packet["cases"]))
        self.assertEqual(
            {
                "boundary_route",
                "boundary_nonroute",
            },
            {case["stratum"] for case in packet["cases"]},
        )
        self.assertEqual(
            [0.64, 0.64, 0.66, 0.66],
            sorted(
                case["candidate"]["supporting_or_above_probability"]
                for case in packet["cases"]
            ),
        )
        self.assertFalse(packet["route_policy_active"])
        self.assertEqual(packet["input_fingerprint"], replay["input_fingerprint"])

        with tempfile.TemporaryDirectory() as tempdir:
            path = Path(tempdir) / "routing.json"
            first = write_salvation_routing_review(path, packet)
            second = write_salvation_routing_review(path, packet)
            self.assertFalse(first[2])
            self.assertTrue(second[2])
            self.assertIn("Target", path.with_suffix(".md").read_text())

    def test_readiness_blocks_packet_before_candidate_collection(self) -> None:
        with patch(
            "pastor_transcript_extractor.sermon_salvation_routing."
            "assess_topic_stage4_readiness",
            return_value={
                "ready": False,
                "blockers": ["not-ready"],
                "input_fingerprint": "blocked",
            },
        ):
            with self.assertRaisesRegex(ValueError, "not-ready"):
                build_salvation_routing_review_packet(
                    self.database,
                    self.cohort,
                )


if __name__ == "__main__":
    unittest.main()
