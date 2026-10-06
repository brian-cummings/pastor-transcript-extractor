from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from pastor_transcript_extractor.sermon_topic_review_adjudication import (
    create_topic_review_adjudication_draft,
    finalize_topic_review_adjudication,
)


def _packet() -> dict:
    return {
        "schema_version": 3,
        "generator_version": "typesafe-topic-review-v3",
        "input_fingerprint": "packet-fingerprint",
        "source": {
            "video_id": 42,
            "youtube_video_id": "youtube-42",
            "question_pack_version": "topics-v2-performed-worship-boundary",
        },
        "selection": {"mode": "whole_sermon"},
        "blocks": [
            {"block_id": 7},
            {"block_id": 8},
        ],
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
            json.dumps(
                {
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
                },
                sort_keys=True,
            ),
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
        self.assertIn("Prepared proposal", result.markdown_path.read_text())

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


if __name__ == "__main__":
    unittest.main()
