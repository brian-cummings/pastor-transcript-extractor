from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from pastor_transcript_extractor.identity_coordination import (
    build_identity_coordination_report,
    write_identity_coordination_report,
)


class IdentityCoordinationTests(unittest.TestCase):
    def _case(
        self,
        youtube_video_id: str,
        coverage_state: str,
        reason_code: str,
        *,
        observation_id: int | None = None,
        attempts: list[dict[str, object]] | None = None,
        profiles: list[int] | None = None,
    ) -> dict[str, object]:
        return {
            "video_id": int(youtube_video_id),
            "youtube_video_id": youtube_video_id,
            "extraction_result_id": int(youtube_video_id) + 100,
            "observation_id": observation_id,
            "observation_fingerprint": (
                f"observation-{observation_id}"
                if observation_id is not None
                else None
            ),
            "content_status": "accepted_sermon",
            "coverage_state": coverage_state,
            "accounted": coverage_state != "unaccounted",
            "reason_code": reason_code,
            "effective_profile_ids": profiles or [],
            "association_attempts": attempts or [],
        }

    def _audit(self, cases: list[dict[str, object]]) -> dict[str, object]:
        return {
            "artifact_kind": "speaker_association_coverage_audit",
            "audit_fingerprint": "audit",
            "cases": cases,
        }

    def test_report_assigns_one_actionable_state_per_extraction(self) -> None:
        report = build_identity_coordination_report(
            self._audit(
                [
                    self._case(
                        "1",
                        "associated",
                        "effective_profile_membership",
                        observation_id=1,
                        profiles=[57],
                    ),
                    self._case(
                        "2",
                        "unaccounted",
                        "association_attempt_missing",
                        observation_id=2,
                    ),
                    self._case(
                        "3",
                        "evaluated",
                        "versioned_association_attempt",
                        observation_id=3,
                        attempts=[
                            {
                                "outcome": "insufficient_evidence",
                                "proposed_profile_id": None,
                            }
                        ],
                    ),
                    self._case(
                        "4",
                        "evaluated",
                        "versioned_association_attempt",
                        observation_id=4,
                        attempts=[
                            {
                                "outcome": "proposed_match",
                                "proposed_profile_id": 58,
                            }
                        ],
                    ),
                ]
            )
        )

        self.assertEqual(
            {
                "associated": 1,
                "association_required": 1,
                "discovery_batch_candidate": 1,
                "profile_match_proposed": 1,
            },
            report["workflow_state_counts"],
        )
        self.assertEqual(1, report["counts"]["terminal"])
        self.assertEqual(3, report["counts"]["action_required"])
        self.assertFalse(report["registry_mutation_allowed"])

    def test_confirmation_candidate_takes_priority_over_generic_proposal(
        self,
    ) -> None:
        report = build_identity_coordination_report(
            self._audit(
                [
                    self._case(
                        "5",
                        "evaluated",
                        "versioned_association_attempt",
                        observation_id=5,
                        attempts=[
                            {
                                "outcome": "proposed_match",
                                "proposed_profile_id": 65,
                            }
                        ],
                    )
                ]
            ),
            confirmation_observation_ids=[5],
        )

        case = report["cases"][0]
        self.assertEqual(
            "provisional_confirmation_proposed",
            case["workflow_state"],
        )
        self.assertEqual(
            "review_or_apply_provisional_confirmation",
            case["next_action"],
        )

    def test_single_video_filter_and_content_terminal(self) -> None:
        report = build_identity_coordination_report(
            self._audit(
                [
                    self._case(
                        "6",
                        "content_terminal",
                        "content_rejected",
                    ),
                    self._case(
                        "7",
                        "blocked",
                        "reviewed_invalid",
                        observation_id=7,
                    ),
                ]
            ),
            youtube_video_id="6",
        )

        self.assertEqual(1, report["counts"]["extractions"])
        self.assertEqual("content_terminal", report["cases"][0]["workflow_state"])
        self.assertTrue(report["cases"][0]["terminal"])

    def test_content_review_is_actionable_not_terminal(self) -> None:
        case = self._case(
            "9",
            "content_terminal",
            "content_review_required",
        )
        case["content_status"] = "review_required"

        report = build_identity_coordination_report(self._audit([case]))

        self.assertEqual(
            "content_review_required",
            report["cases"][0]["workflow_state"],
        )
        self.assertEqual("review_content", report["cases"][0]["next_action"])
        self.assertFalse(report["cases"][0]["terminal"])

    def test_report_write_is_content_addressed_and_replayable(self) -> None:
        report = build_identity_coordination_report(
            self._audit(
                [
                    self._case(
                        "8",
                        "unaccounted",
                        "association_attempt_missing",
                        observation_id=8,
                    )
                ]
            )
        )
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            first = write_identity_coordination_report(root, report)
            second = write_identity_coordination_report(root, report)

            self.assertEqual(first, second)
            payload = json.loads(first.read_text(encoding="utf-8"))
            self.assertEqual(
                report["coordination_fingerprint"],
                payload["coordination_fingerprint"],
            )
            self.assertIn("created_at", payload)


if __name__ == "__main__":
    unittest.main()
