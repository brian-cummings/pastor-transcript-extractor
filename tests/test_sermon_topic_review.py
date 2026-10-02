from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from pastor_transcript_extractor.commands.analysis.content import analysis_topic_review
from pastor_transcript_extractor.sermon_topic_review import (
    VIDEO_4548_REVIEW_CASES,
    TopicReviewCase,
    build_topic_review_packet,
    render_topic_review_markdown,
    write_topic_review_packet,
)
from pastor_transcript_extractor.sermon_topics import TOPICS


def _scores(value: float = 2.0) -> dict[str, dict]:
    return {
        topic: {
            "score": value,
            "probabilities": {
                "0": 0.05,
                "1": 0.1,
                "2": 0.7,
                "3": 0.1,
                "4": 0.05,
            },
            "confidence": 0.75,
        }
        for topic in TOPICS
    }


def _block(block_id: int, *, score: float = 2.0) -> dict:
    return {
        "block_id": block_id,
        "start_seconds": block_id * 60.0,
        "end_seconds": (block_id + 1) * 60.0,
        "segment_indexes": [block_id],
        "context": {
            "leading_context": "Leading sentence.",
            "target_text": f"Target block {block_id}.",
            "trailing_context": "Trailing sentence.",
            "diagnostics": {"policy_version": "topic-context-sentences-v1"},
        },
        "content_role": "principal_sermon",
        "content_role_probabilities": {
            "principal_sermon": 0.9,
            "sermon_integrated_prayer_or_scripture": 0.05,
            "worship_music_or_service_prayer": 0.05,
        },
        "content_role_confidence": 0.8,
        "sermon_probability": 0.95,
        "scores": _scores(score),
        "reliability": {
            "analyzable_lexical_word_count": 80,
            "block_duration_seconds": 60.0,
            "analyzable_words_per_minute": 80.0,
            "final_sermon_overlap_seconds": 60.0,
            "retained_source_segment_indexes": [block_id],
            "sparse": False,
            "non_analyzable": False,
        },
        "projection_eligibility": {
            "policy_version": "sermon-topic-full-block-role-density-v1",
            "eligible": True,
            "exclusion_reasons": [],
        },
        "resolved_model_id": "jev-1.13.0",
        "request_key": "request-1",
    }


def _classification(blocks: list[dict]) -> dict:
    return {
        "method": "typesafe_first_v16_topic_review_packets",
        "final_disposition": {"status": "accepted_sermon"},
        "search": {
            "topic_analysis": {
                "question_pack_version": "topics-v2-performed-worship-boundary",
                "question_pack_digest": "digest",
                "context_policy_version": "topic-context-sentences-v1",
                "reliability_policy_version": "topic-density-v1",
                "requested_model_id": "jev-1.13.0",
                "sermon_projection": {
                    "policy_version": "sermon-topic-full-block-role-density-v1"
                },
                "blocks": blocks,
            }
        },
    }


class SermonTopicReviewTests(unittest.TestCase):
    def test_packet_preserves_complete_distributions_and_review_context(self) -> None:
        case = TopicReviewCase(
            "case-1",
            "One case",
            (7,),
            "Inspect all distributions.",
            "Reviewed interpretation.",
        )

        packet = build_topic_review_packet(
            _classification([_block(7)]),
            video_id=4548,
            youtube_video_id="ClJI4jeCL2E",
            title="Accepted in the Beloved",
            cases=[case],
            source_artifact_path=Path("classification.json"),
        )

        self.assertEqual(1, packet["schema_version"])
        self.assertEqual(1, len(packet["blocks"]))
        reviewed = packet["blocks"][0]
        self.assertEqual(set(TOPICS), set(reviewed["scores"]))
        for score in reviewed["scores"].values():
            self.assertEqual({"0", "1", "2", "3", "4"}, set(score["probabilities"]))
            self.assertEqual(0.75, score["confidence"])
        self.assertEqual("Target block 7.", reviewed["target_text"])
        self.assertIn(
            "not topic presence",
            packet["interpretation_contract"]["confidence"],
        )

        markdown = render_topic_review_markdown(packet)
        self.assertIn("## One case", markdown)
        self.assertIn("### Block 7", markdown)
        self.assertIn("| `salvation_gospel` |", markdown)
        self.assertIn("| 0.050 | 0.100 | 0.700 | 0.100 | 0.050 |", markdown)

    def test_writer_reuses_unchanged_packet_and_rewrites_changed_input(self) -> None:
        case = TopicReviewCase("case-1", "One case", (7,), "Focus.", "Review.")
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "packet.json"
            first_packet = build_topic_review_packet(
                _classification([_block(7)]),
                video_id=4548,
                youtube_video_id="ClJI4jeCL2E",
                title="Accepted in the Beloved",
                cases=[case],
            )
            first = write_topic_review_packet(output, first_packet)
            replay = write_topic_review_packet(output, first_packet)
            output.with_suffix(".md").write_text("tampered\n", encoding="utf-8")
            repaired = write_topic_review_packet(output, first_packet)
            changed_packet = build_topic_review_packet(
                _classification([_block(7, score=3.0)]),
                video_id=4548,
                youtube_video_id="ClJI4jeCL2E",
                title="Accepted in the Beloved",
                cases=[case],
            )
            changed = write_topic_review_packet(output, changed_packet)

            persisted = json.loads(output.read_text(encoding="utf-8"))

        self.assertFalse(first.reused)
        self.assertTrue(replay.reused)
        self.assertFalse(repaired.reused)
        self.assertFalse(changed.reused)
        self.assertNotEqual(first.input_fingerprint, changed.input_fingerprint)
        self.assertEqual(changed.input_fingerprint, persisted["input_fingerprint"])

    def test_missing_review_block_is_rejected(self) -> None:
        case = TopicReviewCase("missing", "Missing", (99,), "Focus.", "Review.")

        with self.assertRaisesRegex(ValueError, "absent: 99"):
            build_topic_review_packet(
                _classification([_block(7)]),
                video_id=4548,
                youtube_video_id="ClJI4jeCL2E",
                title="Accepted in the Beloved",
                cases=[case],
            )

    def test_video_4548_cases_are_bounded_and_named(self) -> None:
        self.assertEqual(3, len(VIDEO_4548_REVIEW_CASES))
        self.assertEqual(
            {52, 53, 54, 55, 69, 77, 78, 79, 80, 81},
            {
                block_id
                for case in VIDEO_4548_REVIEW_CASES
                for block_id in case.block_ids
            },
        )

    def test_analysis_command_writes_and_reuses_prepared_video_packet(self) -> None:
        block_ids = sorted(
            {
                block_id
                for case in VIDEO_4548_REVIEW_CASES
                for block_id in case.block_ids
            }
        )
        video = SimpleNamespace(
            id=4548,
            youtube_video_id="ClJI4jeCL2E",
            title="Accepted in the Beloved",
        )
        with tempfile.TemporaryDirectory() as tmp:
            extracted = Path(tmp) / "extracted"
            extracted.mkdir()
            proposed = extracted / "proposed.json"
            proposed.write_text("{}", encoding="utf-8")
            (extracted / "llm-classification-v1.json").write_text(
                json.dumps(_classification([_block(block_id) for block_id in block_ids])),
                encoding="utf-8",
            )
            database = SimpleNamespace(
                get_video_by_id=lambda requested: video if requested == 4548 else None,
                get_latest_extraction_result_for_video=lambda requested: SimpleNamespace(
                    proposed_json_path=str(proposed)
                ),
            )
            output = Path(tmp) / "review.json"
            with patch(
                "pastor_transcript_extractor.commands.analysis.content.get_database",
                return_value=database,
            ):
                analysis_topic_review(
                    video_id=4548,
                    youtube_video_id=None,
                    output_path=output,
                    base_dir=Path(tmp),
                )
                first = json.loads(output.read_text(encoding="utf-8"))
                analysis_topic_review(
                    video_id=4548,
                    youtube_video_id=None,
                    output_path=output,
                    base_dir=Path(tmp),
                )
                replay = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(first["input_fingerprint"], replay["input_fingerprint"])
        self.assertEqual(3, len(first["cases"]))
        self.assertEqual(10, len(first["blocks"]))


if __name__ == "__main__":
    unittest.main()
