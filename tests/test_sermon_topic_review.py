from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from pastor_transcript_extractor.commands.analysis.content import analysis_topic_review
from pastor_transcript_extractor.sermon_topic_review import (
    DEFAULT_PROSPECTIVE_REVIEW_CASES,
    PROSPECTIVE_REVIEW_POLICY_VERSION,
    WHOLE_SERMON_REVIEW_POLICY_VERSION,
    VIDEO_4548_REVIEW_CASES,
    TopicReviewCase,
    build_topic_review_packet,
    derive_prospective_topic_review_cases,
    derive_whole_sermon_topic_review_case,
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
            profile_projection_gate={
                "eligible": True,
                "profile_id": 12,
                "reason_codes": (),
                "policy_version": "profile-policy-v1",
                "input_fingerprint": "profile-fingerprint",
            },
        )

        self.assertEqual(3, packet["schema_version"])
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
        self.assertTrue(packet["profile_projection_gate"]["eligible"])

        markdown = render_topic_review_markdown(packet)
        self.assertIn("## One case", markdown)
        self.assertIn("### Block 7", markdown)
        self.assertIn("| `salvation_gospel` |", markdown)
        self.assertIn("| 0.050 | 0.100 | 0.700 | 0.100 | 0.050 |", markdown)
        self.assertIn("## Profile projection gate", markdown)

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

    def test_profile_projection_gate_participates_in_packet_identity(self) -> None:
        case = TopicReviewCase("case-1", "One case", (7,), "Focus.", "Review.")
        arguments = {
            "video_id": 4548,
            "youtube_video_id": "ClJI4jeCL2E",
            "title": "Accepted in the Beloved",
            "cases": [case],
        }

        blocked = build_topic_review_packet(
            _classification([_block(7)]),
            **arguments,
            profile_projection_gate={
                "eligible": False,
                "reason_codes": ("effective_profile_membership_unavailable",),
                "input_fingerprint": "membership-v1",
            },
        )
        eligible = build_topic_review_packet(
            _classification([_block(7)]),
            **arguments,
            profile_projection_gate={
                "eligible": True,
                "reason_codes": (),
                "input_fingerprint": "membership-v2",
            },
        )

        self.assertNotEqual(
            blocked["input_fingerprint"],
            eligible["input_fingerprint"],
        )

    def test_packet_reuses_topic_observations_retained_by_fallback_layout(self) -> None:
        classification = _classification([_block(7)])
        topic_analysis = classification["search"].pop("topic_analysis")
        classification["search"]["discovery"] = {
            "typesafe_first_attempt": {"topic_analysis": topic_analysis}
        }

        packet = build_topic_review_packet(
            classification,
            video_id=4548,
            youtube_video_id="ClJI4jeCL2E",
            title="Accepted in the Beloved",
            cases=[TopicReviewCase("case-1", "One", (7,), "Focus.", "Review.")],
        )

        self.assertEqual([7], [block["block_id"] for block in packet["blocks"]])

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

    def test_prospective_sampler_prioritizes_boundaries_and_broad_distributions(self) -> None:
        excluded = _block(1)
        excluded["projection_eligibility"] = {
            "policy_version": "sermon-topic-full-block-role-density-v1",
            "eligible": False,
            "exclusion_reasons": ["outside_final_sermon"],
        }
        boundary_inside = _block(2)
        ambiguous = _block(3)
        ambiguous["scores"]["salvation_gospel"] = {
            "score": 2.5,
            "probabilities": {
                "0": 0.1,
                "1": 0.15,
                "2": 0.2,
                "3": 0.25,
                "4": 0.3,
            },
            "confidence": 0.05,
        }
        classification = _classification([excluded, boundary_inside, ambiguous])

        first = derive_prospective_topic_review_cases(
            classification,
            maximum_cases=4,
        )
        replay = derive_prospective_topic_review_cases(
            classification,
            maximum_cases=4,
        )

        self.assertEqual(first, replay)
        self.assertEqual(4, len(first))
        self.assertEqual((1, 2), first[0].block_ids)
        self.assertIn("boundary", first[0].case_id)
        self.assertEqual((3,), first[1].block_ids)
        self.assertIn("salvation_gospel", first[1].case_id)
        self.assertTrue(all(case.reviewed_interpretation is None for case in first))

        packet = build_topic_review_packet(
            classification,
            video_id=99,
            youtube_video_id="future-video",
            title="Future sermon",
            cases=first,
            selection={
                "mode": "prospective",
                "policy_version": PROSPECTIVE_REVIEW_POLICY_VERSION,
                "maximum_cases": 4,
            },
        )
        markdown = render_topic_review_markdown(packet)
        self.assertIn("Mode: `prospective`", markdown)
        self.assertIn("Review status: pending", markdown)

    def test_prospective_sampler_requires_current_projection(self) -> None:
        classification = _classification([_block(1)])
        del classification["search"]["topic_analysis"]["sermon_projection"]

        with self.assertRaisesRegex(
            ValueError,
            "current deterministic sermon projection",
        ):
            derive_prospective_topic_review_cases(classification)

    def test_whole_sermon_case_selects_every_block_in_timeline_order(self) -> None:
        classification = _classification([_block(9), _block(7), _block(8)])

        case = derive_whole_sermon_topic_review_case(classification)
        packet = build_topic_review_packet(
            classification,
            video_id=99,
            youtube_video_id="whole-sermon",
            title="Whole sermon",
            cases=(case,),
            selection={
                "mode": "whole_sermon",
                "policy_version": WHOLE_SERMON_REVIEW_POLICY_VERSION,
                "maximum_cases": 1,
                "selected_block_count": 3,
            },
        )

        self.assertEqual((7, 8, 9), case.block_ids)
        self.assertEqual([7, 8, 9], [block["block_id"] for block in packet["blocks"]])
        self.assertEqual("whole_sermon", packet["selection"]["mode"])
        self.assertIsNone(case.reviewed_interpretation)
        self.assertIn("Selected blocks: `3`", render_topic_review_markdown(packet))

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
            ), patch(
                "pastor_transcript_extractor.commands.analysis.content."
                "assess_topic_profile_projection",
                return_value=SimpleNamespace(
                    to_dict=lambda: {
                        "eligible": False,
                        "profile_id": None,
                        "reason_codes": (
                            "effective_profile_membership_unavailable",
                        ),
                        "policy_version": "profile-policy-v1",
                        "input_fingerprint": "profile-fingerprint",
                    }
                ),
            ):
                analysis_topic_review(
                    video_id=4548,
                    youtube_video_id=None,
                    output_path=output,
                    prospective=False,
                    maximum_cases=DEFAULT_PROSPECTIVE_REVIEW_CASES,
                    whole_sermon=False,
                    base_dir=Path(tmp),
                )
                first = json.loads(output.read_text(encoding="utf-8"))
                analysis_topic_review(
                    video_id=4548,
                    youtube_video_id=None,
                    output_path=output,
                    prospective=False,
                    maximum_cases=DEFAULT_PROSPECTIVE_REVIEW_CASES,
                    whole_sermon=False,
                    base_dir=Path(tmp),
                )
                replay = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(first["input_fingerprint"], replay["input_fingerprint"])
        self.assertEqual(3, len(first["cases"]))
        self.assertEqual(10, len(first["blocks"]))
        self.assertEqual("prepared_regression", first["selection"]["mode"])

    def test_analysis_command_automatically_samples_an_unprepared_video(self) -> None:
        blocks = [_block(block_id) for block_id in range(1, 7)]
        blocks[0]["projection_eligibility"] = {
            "policy_version": "sermon-topic-full-block-role-density-v1",
            "eligible": False,
            "exclusion_reasons": ["outside_final_sermon"],
        }
        blocks[2]["scores"]["salvation_gospel"]["confidence"] = 0.05
        video = SimpleNamespace(
            id=99,
            youtube_video_id="future-video",
            title="Future sermon",
        )
        with tempfile.TemporaryDirectory() as tmp:
            extracted = Path(tmp) / "extracted"
            extracted.mkdir()
            proposed = extracted / "proposed.json"
            proposed.write_text("{}", encoding="utf-8")
            (extracted / "llm-classification-v1.json").write_text(
                json.dumps(_classification(blocks)),
                encoding="utf-8",
            )
            database = SimpleNamespace(
                get_video_by_id=lambda requested: video if requested == 99 else None,
                get_latest_extraction_result_for_video=lambda requested: SimpleNamespace(
                    proposed_json_path=str(proposed)
                ),
            )
            output = Path(tmp) / "review.json"
            with patch(
                "pastor_transcript_extractor.commands.analysis.content.get_database",
                return_value=database,
            ), patch(
                "pastor_transcript_extractor.commands.analysis.content."
                "assess_topic_profile_projection",
                return_value=SimpleNamespace(
                    to_dict=lambda: {
                        "eligible": False,
                        "reason_codes": (
                            "effective_profile_membership_unavailable",
                        ),
                        "input_fingerprint": "profile-fingerprint",
                    }
                ),
            ):
                analysis_topic_review(
                    video_id=99,
                    youtube_video_id=None,
                    output_path=output,
                    prospective=False,
                    maximum_cases=5,
                    whole_sermon=False,
                    base_dir=Path(tmp),
                )
            packet = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual("prospective", packet["selection"]["mode"])
        self.assertEqual(PROSPECTIVE_REVIEW_POLICY_VERSION, packet["selection"]["policy_version"])
        self.assertLessEqual(len(packet["cases"]), 5)
        self.assertTrue(packet["cases"])
        self.assertTrue(
            all(case["reviewed_interpretation"] is None for case in packet["cases"])
        )


if __name__ == "__main__":
    unittest.main()
