from __future__ import annotations

import json
import hashlib
import tempfile
import unittest
from pathlib import Path

from pastor_transcript_extractor.identity_coordination import (
    build_identity_coordination_report,
    load_discovery_observation_states,
    load_discovery_resolution_pairs,
    write_identity_coordination_report,
)
from pastor_transcript_extractor.speaker_profile_discovery import (
    SHADOW_PROFILE_DISCOVERY_VERSION,
    TRANSCRIPT_GROUNDED_SPAN_SELECTION_VERSION,
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

    def test_discovery_history_avoids_redundant_batch_action(self) -> None:
        report = build_identity_coordination_report(
            self._audit(
                [
                    self._case(
                        "10",
                        "evaluated",
                        "versioned_association_attempt",
                        observation_id=10,
                        attempts=[
                            {
                                "outcome": "insufficient_evidence",
                                "proposed_profile_id": None,
                            }
                        ],
                    )
                ]
            ),
            discovery_observation_states={10: "evaluated_unclustered"},
        )

        case = report["cases"][0]
        self.assertEqual(
            "identity_unresolved_waiting_for_evidence",
            case["workflow_state"],
        )
        self.assertEqual("await_new_evidence", case["next_action"])
        self.assertEqual(1, report["counts"]["waiting_for_evidence"])
        self.assertEqual(0, report["counts"]["action_required"])

    def test_undersized_discovery_seed_waits_for_third_recording(self) -> None:
        report = build_identity_coordination_report(
            self._audit(
                [
                    self._case(
                        "16",
                        "evaluated",
                        "versioned_association_attempt",
                        observation_id=16,
                        attempts=[
                            {
                                "outcome": "no_match",
                                "proposed_profile_id": None,
                            }
                        ],
                    )
                ]
            ),
            discovery_observation_states={16: "undersized_component"},
        )

        case = report["cases"][0]
        self.assertEqual(
            "identity_unresolved_waiting_for_evidence",
            case["workflow_state"],
        )
        self.assertEqual("await_new_evidence", case["next_action"])
        self.assertFalse(case["immediate_action_required"])

    def test_discovery_state_loader_verifies_and_indexes_artifact(self) -> None:
        payload = {
            "artifact_kind": "speaker_profile_shadow_discovery",
            "discovery_version": SHADOW_PROFILE_DISCOVERY_VERSION,
            "span_selection": {
                "version": TRANSCRIPT_GROUNDED_SPAN_SELECTION_VERSION,
            },
            "observation_signatures": [
                {"observation_id": 11},
                {"observation_id": 12},
                {"observation_id": 13},
            ],
            "signature_failures": [{"observation_id": 14}],
            "components": [
                {
                    "outcome": "blocked",
                    "members": [{"observation_id": 12}],
                },
                {
                    "outcome": "provisional_profile_candidate",
                    "members": [{"observation_id": 13}],
                },
            ],
        }
        payload["result_sha256"] = _sha256(payload)
        with tempfile.TemporaryDirectory() as tempdir:
            path = Path(tempdir) / "discovery.json"
            path.write_text(json.dumps(payload), encoding="utf-8")

            states = load_discovery_observation_states(path)

        self.assertEqual(
            {
                11: "evaluated_unclustered",
                12: "blocked_component",
                13: "provisional_component",
                14: "signature_failed",
            },
            states,
        )

    def test_discovery_resolution_loader_nominates_only_missing_overlap_edge(
        self,
    ) -> None:
        payload = {
            "artifact_kind": "speaker_profile_shadow_discovery",
            "discovery_version": SHADOW_PROFILE_DISCOVERY_VERSION,
            "span_selection": {
                "version": TRANSCRIPT_GROUNDED_SPAN_SELECTION_VERSION,
            },
            "observation_signatures": [
                {
                    "observation_id": observation_id,
                    "observation_fingerprint": fingerprint,
                }
                for observation_id, fingerprint in (
                    (21, "bridge-a"),
                    (22, "bridge-b"),
                    (23, "exclusive-left"),
                    (24, "exclusive-right"),
                )
            ],
            "signature_failures": [],
            "pair_results": [
                {
                    "observation_ids": [23, 24],
                    "outcome": "insufficient_evidence",
                }
            ],
            "components": [
                {
                    "component_id": "left-component",
                    "outcome": "blocked",
                    "blockers": ["overlapping_complete_link_components"],
                    "members": [
                        {"observation_id": value}
                        for value in (21, 22, 23)
                    ],
                },
                {
                    "component_id": "right-component",
                    "outcome": "blocked",
                    "blockers": ["overlapping_complete_link_components"],
                    "members": [
                        {"observation_id": value}
                        for value in (21, 22, 24)
                    ],
                },
            ],
        }
        payload["result_sha256"] = _sha256(payload)
        with tempfile.TemporaryDirectory() as tempdir:
            path = Path(tempdir) / "discovery.json"
            path.write_text(json.dumps(payload), encoding="utf-8")

            resolutions = load_discovery_resolution_pairs(path)

        self.assertEqual(1, len(resolutions))
        resolution = resolutions[0]
        self.assertEqual(
            {"exclusive-left", "exclusive-right"},
            {resolution.fingerprint_a, resolution.fingerprint_b},
        )
        self.assertEqual(4, resolution.observations_unlocked)
        self.assertEqual(
            ("left-component", "right-component"),
            resolution.component_ids,
        )

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


def _sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()


if __name__ == "__main__":
    unittest.main()
