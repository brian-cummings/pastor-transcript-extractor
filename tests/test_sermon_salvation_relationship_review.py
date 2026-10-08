from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from pastor_transcript_extractor.models import Video, VideoStatus
from pastor_transcript_extractor.sermon_classifier_typesafe import (
    SALVATION_RELATIONSHIPS_PACK,
    TypeSafeBlockAnswer,
)
from pastor_transcript_extractor.sermon_salvation_relationship_review import (
    evaluate_salvation_relationship_review,
    write_salvation_relationship_review,
)
from pastor_transcript_extractor.sermon_salvation_relationships import (
    SALVATION_RELATIONSHIPS,
    SALVATION_RELATIONSHIPS_PACK_VERSION,
)
from pastor_transcript_extractor.sermon_topics import TOPICS, TOPIC_PACK_VERSION


class _Database:
    def __init__(self, videos: list[Video]) -> None:
        self._videos = videos

    def list_videos(self) -> list[Video]:
        return self._videos


class _Client:
    def __init__(self) -> None:
        self.calls = 0

    def assess_blocks(
        self,
        recording_context,
        blocks,
        *,
        requested_packs=None,
        topic_contexts=None,
        **_kwargs,
    ):
        del recording_context
        self.calls += 1
        self.assert_leaf_request(requested_packs, topic_contexts, blocks)
        return {
            block.block_id: TypeSafeBlockAnswer(
                choice="unclear",
                probabilities={},
                confidence=None,
                resolved_model_id="jev-1.13.0",
                request_provenance={"request_key": f"request-{self.calls}"},
                salvation_relationship_probabilities={
                    relationship: 0.75
                    for relationship in SALVATION_RELATIONSHIPS
                },
                salvation_relationship_question_version=(
                    SALVATION_RELATIONSHIPS_PACK_VERSION
                ),
                salvation_relationship_context={},
            )
            for block in blocks
        }

    @staticmethod
    def assert_leaf_request(requested_packs, topic_contexts, blocks) -> None:
        if requested_packs != frozenset({SALVATION_RELATIONSHIPS_PACK}):
            raise AssertionError(requested_packs)
        if set(topic_contexts or {}) != {block.block_id for block in blocks}:
            raise AssertionError("missing contexts")


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


def _block(block_id: int, support: float) -> dict[str, object]:
    scores = {
        topic: {
            "score": 0.0,
            "probabilities": {
                "0": 1.0,
                "1": 0.0,
                "2": 0.0,
                "3": 0.0,
                "4": 0.0,
            },
            "confidence": 1.0,
        }
        for topic in TOPICS
    }
    scores["salvation_gospel"] = {
        "score": support * 2,
        "probabilities": {
            "0": 1.0 - support,
            "1": 0.0,
            "2": support,
            "3": 0.0,
            "4": 0.0,
        },
        "confidence": 0.5,
    }
    return {
        "block_id": block_id,
        "start_seconds": float(block_id * 60),
        "end_seconds": float((block_id + 1) * 60),
        "segment_indexes": [block_id],
        "context": {
            "leading_context": f"Leading {block_id}.",
            "target_text": f"Target {block_id} salvation relationship.",
            "trailing_context": f"Trailing {block_id}.",
            "diagnostics": {"policy_version": "context-v1"},
        },
        "scores": scores,
        "projection_eligibility": {"eligible": True},
    }


class SalvationRelationshipReviewTests(unittest.TestCase):
    def test_bounded_sample_replays_from_per_video_leaf_caches(self) -> None:
        videos = [_video(1), _video(2)]
        database = _Database(videos)
        cohort = {
            "cohort_sha256": "cohort-sha",
            "pastors": [
                {
                    "display_name": f"Pastor {video.id}",
                    "pastor_id": video.id,
                    "slug": f"pastor-{video.id}",
                    "sermons": [{"video_id": video.id}],
                }
                for video in videos
            ],
        }
        analyses = {
            video.id: {
                "question_pack_version": TOPIC_PACK_VERSION,
                "blocks": [
                    _block(video.id * 10 + index, support)
                    for index, support in enumerate(
                        (0.55, 0.65, 0.75, 0.95),
                        start=1,
                    )
                ],
            }
            for video in videos
        }
        client = _Client()
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            gates = {
                video.id: SimpleNamespace(
                    eligible=True,
                    source_path=str(
                        root / str(video.id) / "classification.json"
                    ),
                    topic_analysis_fingerprint=f"topic-{video.id}",
                )
                for video in videos
            }
            with (
                patch(
                    "pastor_transcript_extractor."
                    "sermon_salvation_relationship_review."
                    "assess_topic_stage4_readiness",
                    return_value={
                        "ready": True,
                        "blockers": [],
                        "input_fingerprint": "readiness-sha",
                    },
                ),
                patch(
                    "pastor_transcript_extractor."
                    "sermon_salvation_relationship_review."
                    "assess_topic_profile_projection",
                    side_effect=lambda _database, video: gates[video.id],
                ),
                patch(
                    "pastor_transcript_extractor."
                    "sermon_salvation_relationship_review."
                    "read_topic_analysis_for_gate",
                    side_effect=lambda gate: (
                        analyses[
                            int(Path(gate.source_path).parent.name)
                        ],
                        {},
                    ),
                ),
            ):
                first, first_execution = evaluate_salvation_relationship_review(
                    database,
                    cohort,
                    model="jev-1.13.0",
                    client=client,
                )
                replay, replay_execution = evaluate_salvation_relationship_review(
                    database,
                    cohort,
                    model="jev-1.13.0",
                    client=client,
                )

            output = root / "review.json"
            first_write = write_salvation_relationship_review(output, first)
            replay_write = write_salvation_relationship_review(output, replay)

        self.assertEqual(6, len(first["cases"]))
        self.assertEqual(8, first["routed_candidate_count"])
        self.assertEqual(first["input_fingerprint"], replay["input_fingerprint"])
        self.assertEqual({"hits": 0, "misses": 6, "provider_requests": 2}, first_execution)
        self.assertEqual({"hits": 6, "misses": 0, "provider_requests": 0}, replay_execution)
        self.assertEqual(2, client.calls)
        self.assertFalse(first_write[2])
        self.assertTrue(replay_write[2])


if __name__ == "__main__":
    unittest.main()
