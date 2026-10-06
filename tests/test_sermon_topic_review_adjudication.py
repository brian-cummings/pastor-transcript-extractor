from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from pastor_transcript_extractor.sermon_topic_review_adjudication import (
    create_topic_review_adjudication_draft,
    finalize_topic_review_adjudication,
)
from pastor_transcript_extractor.sermon_topics import TOPICS


def _block(block_id: int) -> dict:
    return {
        "block_id": block_id,
        "start_seconds": float(block_id * 10),
        "end_seconds": float(block_id * 10 + 10),
        "content_role": "principal_sermon",
        "content_role_confidence": 1.0,
        "content_role_probabilities": {"principal_sermon": 1.0},
        "sermon_probability": 1.0,
        "reliability": {
            "analyzable_lexical_word_count": 20,
            "sparse": False,
            "final_sermon_overlap_seconds": 10.0,
        },
        "projection_eligibility": {
            "eligible": True,
            "exclusion_reasons": [],
        },
        "leading_context": "Leading sentence.",
        "target_text": f"Target block {block_id}.",
        "trailing_context": "Trailing sentence.",
        "scores": {
            topic: {
                "score": 1.0,
                "probabilities": {
                    "0": 0.0,
                    "1": 1.0,
                    "2": 0.0,
                    "3": 0.0,
                    "4": 0.0,
                },
                "confidence": 1.0,
            }
            for topic in TOPICS
        },
    }


def _packet() -> dict:
    return {
        "schema_version": 3,
        "generator_version": "typesafe-topic-review-v3",
        "input_fingerprint": "packet-fingerprint",
        "source": {
            "video_id": 42,
            "youtube_video_id": "youtube-42",
            "title": "Review fixture",
            "classification_method": "typesafe_test",
            "final_disposition_status": "accepted_sermon",
            "question_pack_version": "topics-v2-performed-worship-boundary",
        },
        "selection": {"mode": "whole_sermon"},
        "cases": [
            {
                "case_id": "fixture-case",
                "label": "Fixture review case",
                "block_ids": [7, 8],
                "review_focus": "Review the cached topic evidence.",
                "reviewed_interpretation": None,
            }
        ],
        "blocks": [_block(7), _block(8)],
    }


def _proposal() -> dict:
    return {
        "schema_version": 1,
        "workflow_version": "topic-review-proposal-v1",
        "source_packet_fingerprint": "packet-fingerprint",
        "topic_level_corrections": [
            {
                "block_ids": [7],
                "topic": "salvation_gospel",
                "reviewed_level": 3,
                "notes": "The saving-work claim is substantial.",
            }
        ],
        "projection_eligibility_corrections": [],
        "notes": "Prepared from the cached review evidence.",
    }


class SermonTopicReviewAdjudicationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.packet_path = self.root / "packet.json"
        self.packet_path.write_text(
            json.dumps(_packet(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        self.draft_path = self.root / "packet.review-draft.json"

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_create_is_reusable_and_protects_review_edits(self) -> None:
        first = create_topic_review_adjudication_draft(
            self.packet_path, self.draft_path
        )
        replay = create_topic_review_adjudication_draft(
            self.packet_path, self.draft_path
        )

        self.assertFalse(first.reused)
        self.assertTrue(replay.reused)
        draft = json.loads(self.draft_path.read_text(encoding="utf-8"))
        self.assertEqual(
            [
                "selected_blocks_reviewed",
                "missed_topic_episode_search_complete",
                "projection_boundary_review_complete",
            ],
            draft["required_checks"],
        )
        self.assertEqual("packet.json", draft["source_packet"]["path"])

        draft["notes"] = "Reviewed and retained for adjudication."
        self.draft_path.write_text(
            json.dumps(draft, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ValueError, "refusing to overwrite"):
            create_topic_review_adjudication_draft(
                self.packet_path, self.draft_path
            )

    def test_create_migrates_only_unchanged_prior_workflow_draft(self) -> None:
        proposal_path = self.root / "proposal.json"
        proposal_path.write_text(json.dumps(_proposal()), encoding="utf-8")
        create_topic_review_adjudication_draft(
            self.packet_path,
            self.draft_path,
            proposal_path=proposal_path,
        )
        legacy = json.loads(self.draft_path.read_text(encoding="utf-8"))
        legacy["workflow_version"] = "topic-review-adjudication-v1"
        self.draft_path.write_text(json.dumps(legacy), encoding="utf-8")
        self.draft_path.with_suffix(".md").write_text(
            "# Prior generated instructions\n",
            encoding="utf-8",
        )

        migrated = create_topic_review_adjudication_draft(
            self.packet_path,
            self.draft_path,
            proposal_path=proposal_path,
        )

        self.assertFalse(migrated.reused)
        updated = json.loads(self.draft_path.read_text(encoding="utf-8"))
        self.assertEqual(
            "topic-review-adjudication-v2",
            updated["workflow_version"],
        )
        self.assertIn(
            "How to interpret and decide",
            migrated.markdown_path.read_text(encoding="utf-8"),
        )

    def test_create_refuses_migration_after_prior_draft_review_edit(self) -> None:
        proposal_path = self.root / "proposal.json"
        proposal_path.write_text(json.dumps(_proposal()), encoding="utf-8")
        create_topic_review_adjudication_draft(
            self.packet_path,
            self.draft_path,
            proposal_path=proposal_path,
        )
        legacy = json.loads(self.draft_path.read_text(encoding="utf-8"))
        legacy["workflow_version"] = "topic-review-adjudication-v1"
        legacy["checks"]["selected_blocks_reviewed"] = True
        self.draft_path.write_text(json.dumps(legacy), encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "review edits"):
            create_topic_review_adjudication_draft(
                self.packet_path,
                self.draft_path,
                proposal_path=proposal_path,
            )

    def test_finalize_accepts_review_and_reuses_logical_result(self) -> None:
        create_topic_review_adjudication_draft(self.packet_path, self.draft_path)
        output = self.root / "packet.reviewed.json"

        first = finalize_topic_review_adjudication(
            self.draft_path,
            output,
            reviewer="Brian",
            accept_as_reviewed=True,
        )
        replay = finalize_topic_review_adjudication(
            self.draft_path,
            output,
            reviewer="Brian",
            accept_as_reviewed=True,
        )

        self.assertFalse(first.reused)
        self.assertTrue(replay.reused)
        reviewed = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual("reviewed", reviewed["review_status"])
        self.assertEqual("Brian", reviewed["reviewed_by"])
        self.assertTrue(all(reviewed["checks"].values()))
        self.assertEqual(first.review_fingerprint, replay.review_fingerprint)

    def test_proposal_prefills_draft_without_completing_review(self) -> None:
        proposal_path = self.root / "proposal.json"
        proposal_path.write_text(
            json.dumps(_proposal(), sort_keys=True),
            encoding="utf-8",
        )

        result = create_topic_review_adjudication_draft(
            self.packet_path,
            self.draft_path,
            proposal_path=proposal_path,
        )

        self.assertFalse(result.reused)
        draft = json.loads(self.draft_path.read_text(encoding="utf-8"))
        self.assertEqual(1, len(draft["topic_level_corrections"]))
        self.assertFalse(any(draft["checks"].values()))
        self.assertEqual(64, len(draft["proposal_source"]["sha256"]))
        self.assertEqual("proposal.json", draft["proposal_source"]["path"])
        markdown = result.markdown_path.read_text()
        self.assertIn("How to interpret and decide", markdown)
        self.assertIn("Prepared proposal", markdown)
        self.assertIn("Proposed reviewed level: `3` — Substantial", markdown)
        self.assertIn("expected score 1.000; P0=0.000, P1=1.000", markdown)
        self.assertIn("Cached source packet evidence", markdown)
        self.assertIn("Target block 7.", markdown)

    def test_finalize_rejects_changed_proposal_content(self) -> None:
        proposal_path = self.root / "proposal.json"
        proposal_path.write_text(json.dumps(_proposal()), encoding="utf-8")
        create_topic_review_adjudication_draft(
            self.packet_path,
            self.draft_path,
            proposal_path=proposal_path,
        )
        changed = _proposal()
        changed["notes"] = "Changed after the review draft was prepared."
        proposal_path.write_text(json.dumps(changed), encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "proposal content hash has changed"):
            finalize_topic_review_adjudication(
                self.draft_path,
                self.root / "reviewed.json",
                reviewer="Brian",
                accept_as_reviewed=True,
            )

    def test_proposal_rejects_stale_packet_or_invalid_corrections(self) -> None:
        proposal_path = self.root / "proposal.json"
        proposal = {
            "schema_version": 1,
            "workflow_version": "topic-review-proposal-v1",
            "source_packet_fingerprint": "stale-fingerprint",
            "topic_level_corrections": [],
            "projection_eligibility_corrections": [],
            "notes": "Prepared proposal.",
        }
        proposal_path.write_text(json.dumps(proposal), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "another source packet"):
            create_topic_review_adjudication_draft(
                self.packet_path,
                self.draft_path,
                proposal_path=proposal_path,
            )

        proposal["source_packet_fingerprint"] = "packet-fingerprint"
        proposal["topic_level_corrections"] = [
            {
                "block_ids": [999],
                "topic": "salvation_gospel",
                "reviewed_level": 3,
                "notes": "Not a packet block.",
            }
        ]
        proposal_path.write_text(json.dumps(proposal), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "source packet blocks"):
            create_topic_review_adjudication_draft(
                self.packet_path,
                self.draft_path,
                proposal_path=proposal_path,
            )

    def test_finalize_validates_corrections_and_source_hash(self) -> None:
        create_topic_review_adjudication_draft(self.packet_path, self.draft_path)
        draft = json.loads(self.draft_path.read_text(encoding="utf-8"))
        draft["checks"] = {
            key: True for key in draft["checks"]
        }
        draft["topic_level_corrections"] = [
            {
                "block_ids": [7, 8],
                "topic": "salvation_gospel",
                "reviewed_level": 3,
                "notes": "The saving-work claim is substantial across both blocks.",
            }
        ]
        draft["projection_eligibility_corrections"] = [
            {
                "block_id": 8,
                "eligible": False,
                "notes": "This block is performed music rather than preaching.",
            }
        ]
        self.draft_path.write_text(
            json.dumps(draft, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        result = finalize_topic_review_adjudication(
            self.draft_path,
            self.root / "corrected.reviewed.json",
            reviewer="reviewer-2",
        )

        self.assertEqual(1, result.topic_correction_count)
        self.assertEqual(1, result.projection_correction_count)
        packet = _packet()
        packet["blocks"].append({"block_id": 9})
        self.packet_path.write_text(json.dumps(packet), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "content hash has changed"):
            finalize_topic_review_adjudication(
                self.draft_path,
                self.root / "stale.reviewed.json",
                reviewer="reviewer-2",
            )

    def test_finalize_rejects_incomplete_whole_sermon_review(self) -> None:
        create_topic_review_adjudication_draft(self.packet_path, self.draft_path)

        with self.assertRaisesRegex(ValueError, "Incomplete required review checks"):
            finalize_topic_review_adjudication(
                self.draft_path,
                self.root / "reviewed.json",
                reviewer="Brian",
            )

    def test_review_fingerprint_is_independent_of_artifact_paths(self) -> None:
        first_dir = self.root / "first"
        second_dir = self.root / "second"
        first_draft = first_dir / "draft.json"
        second_draft = second_dir / "draft.json"
        create_topic_review_adjudication_draft(self.packet_path, first_draft)
        create_topic_review_adjudication_draft(self.packet_path, second_draft)

        first = finalize_topic_review_adjudication(
            first_draft,
            first_dir / "reviewed.json",
            reviewer="Brian",
            accept_as_reviewed=True,
        )
        second_output = second_dir / "nested" / "reviewed.json"
        second = finalize_topic_review_adjudication(
            second_draft,
            second_output,
            reviewer="Brian",
            accept_as_reviewed=True,
        )

        self.assertEqual(first.review_fingerprint, second.review_fingerprint)
        reviewed = json.loads(second_output.read_text(encoding="utf-8"))
        resolved_source = (
            second_output.parent / reviewed["source_packet"]["path"]
        ).resolve()
        self.assertEqual(self.packet_path.resolve(), resolved_source)

    def test_proposal_review_fingerprint_is_independent_of_artifact_paths(self) -> None:
        proposal_path = self.root / "proposal.json"
        proposal_path.write_text(json.dumps(_proposal()), encoding="utf-8")
        first_dir = self.root / "first-proposal"
        second_dir = self.root / "second-proposal"
        first_draft = first_dir / "draft.json"
        second_draft = second_dir / "draft.json"
        create_topic_review_adjudication_draft(
            self.packet_path,
            first_draft,
            proposal_path=proposal_path,
        )
        create_topic_review_adjudication_draft(
            self.packet_path,
            second_draft,
            proposal_path=proposal_path,
        )

        first = finalize_topic_review_adjudication(
            first_draft,
            first_dir / "reviewed.json",
            reviewer="Brian",
            accept_as_reviewed=True,
        )
        second_output = second_dir / "nested" / "reviewed.json"
        second = finalize_topic_review_adjudication(
            second_draft,
            second_output,
            reviewer="Brian",
            accept_as_reviewed=True,
        )

        self.assertEqual(first.review_fingerprint, second.review_fingerprint)
        reviewed = json.loads(second_output.read_text(encoding="utf-8"))
        resolved_proposal = (
            second_output.parent / reviewed["proposal_source"]["path"]
        ).resolve()
        self.assertEqual(proposal_path.resolve(), resolved_proposal)


if __name__ == "__main__":
    unittest.main()
