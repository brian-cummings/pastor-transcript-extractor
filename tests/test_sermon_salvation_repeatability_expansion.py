from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from pastor_transcript_extractor.sermon_salvation_repeatability_expansion import (
    build_salvation_analytical_backfill_plan,
    build_salvation_candidate_discovery_audit,
    build_salvation_repeatability_expansion_plan,
    evaluate_salvation_repeatability_expansion_plan,
)


class SalvationRepeatabilityExpansionTests(unittest.TestCase):
    def test_builds_inventory_without_assigning_series_from_titles(self) -> None:
        cohort = {
            "cohort_id": "cohort",
            "cohort_sha256": "c" * 64,
            "pastors": [
                {
                    "display_name": "Pastor Example",
                    "pastor_id": 7,
                    "slug": "pastor-example",
                    "sermons": [
                        {
                            "video_id": 1,
                            "period_key": "2026-h1",
                            "period_evidence": {"source_kind": "reviewed"},
                        },
                        {
                            "video_id": 2,
                            "period_key": "2026-h1",
                            "period_evidence": {"source_kind": "reviewed"},
                        },
                        {
                            "video_id": 3,
                            "period_key": "2026-h2",
                            "period_evidence": {"source_kind": "reviewed"},
                        },
                    ],
                }
            ],
        }
        readiness = {
            "ready": True,
            "input_fingerprint": "r" * 64,
            "pastors": [{"effective_profile_ids": [42]}],
        }
        candidates = [
            {
                "profile_id": 42,
                "video_id": video_id,
                "youtube_video_id": f"youtube-{video_id}",
                "title": f"Series-like title {video_id}",
                "published_at": (
                    None
                    if video_id == 1
                    else f"2026-01-{video_id:02d}T00:00:00"
                ),
                "period_key": None if video_id == 1 else "2026-h1",
                "eligible_block_count": 5,
                "gate_input_fingerprint": str(video_id) * 64,
            }
            for video_id in range(1, 13)
        ]

        report = build_salvation_repeatability_expansion_plan(
            candidates,
            cohort,
            readiness,
        )

        pastor = report["pastors"][0]
        self.assertEqual(12, pastor["eligible_candidate_count"])
        self.assertEqual(
            "candidate_count_sufficient_series_review_required",
            pastor["selection_status"],
        )
        self.assertTrue(pastor["candidates"][0]["already_in_baseline"])
        self.assertEqual(
            "reviewed_baseline_cohort",
            pastor["candidates"][0]["period_provenance"],
        )
        self.assertNotIn("series_key", pastor["candidates"][0])
        self.assertEqual(0, report["provider_requests"])
        self.assertEqual(
            [3, 4, 5, 6, 8, 10, 12],
            report["selection_contract"]["convergence_sample_sizes"],
        )

    def test_evaluator_rejects_production_ineligible_videos_before_gate(self) -> None:
        cohort = {
            "cohort_id": "cohort",
            "pastors": [
                {
                    "display_name": "Pastor Example",
                    "sermons": [{"video_id": 1}],
                }
            ],
        }
        readiness = {
            "ready": True,
            "input_fingerprint": "r" * 64,
            "pastors": [{"effective_profile_ids": [42]}],
        }
        video = Mock(duration_seconds=10, published_at=None)
        database = Mock()
        database.list_videos.return_value = [video]
        with (
            patch(
                "pastor_transcript_extractor.sermon_salvation_repeatability_expansion.assess_topic_stage4_readiness",
                return_value=readiness,
            ),
            patch(
                "pastor_transcript_extractor.sermon_salvation_repeatability_expansion.assess_topic_profile_projection"
            ) as gate,
        ):
            report = evaluate_salvation_repeatability_expansion_plan(
                database,
                cohort,
            )

        gate.assert_not_called()
        self.assertEqual(0, report["pastors"][0]["eligible_candidate_count"])

    def test_discovery_audit_separates_identity_gate_and_query_failures(self) -> None:
        cohort = {
            "cohort_id": "cohort",
            "cohort_sha256": "c" * 64,
            "pastors": [
                {
                    "display_name": "Pastor Example",
                    "pastor_id": 7,
                    "slug": "pastor-example",
                    "sermons": [
                        {
                            "video_id": 1,
                            "period_key": "2026-h1",
                            "period_evidence": {"source_kind": "reviewed"},
                        }
                    ],
                }
            ],
        }
        readiness = {
            "ready": True,
            "input_fingerprint": "r" * 64,
            "pastors": [{"effective_profile_ids": [42]}],
        }
        records = [
            {
                "video_id": 1,
                "title": "Baseline",
                "configured_pastor_id": 7,
                "canonical_effective_profile_ids": [42],
                "production_eligible": True,
                "gate_eligible": True,
                "gate_reason_codes": [],
                "published_at": None,
            },
            {
                "video_id": 2,
                "title": "Needs identity",
                "configured_pastor_id": 7,
                "canonical_effective_profile_ids": [],
                "production_eligible": True,
                "gate_eligible": False,
                "gate_reason_codes": ["effective_profile_membership_unavailable"],
                "published_at": None,
            },
            {
                "video_id": 3,
                "title": "Needs topic refresh",
                "configured_pastor_id": 7,
                "canonical_effective_profile_ids": [42],
                "production_eligible": True,
                "gate_eligible": False,
                "gate_reason_codes": ["topic_analysis_unavailable"],
                "published_at": "2026-01-01T00:00:00",
            },
        ]
        inventory = {
            "input_fingerprint": "i" * 64,
            "pastors": [{"profile_id": 42, "candidates": []}],
        }

        report = build_salvation_candidate_discovery_audit(
            records,
            cohort,
            readiness,
            inventory,
        )

        pastor = report["pastors"][0]
        self.assertEqual(1, pastor["category_counts"]["current_inventory_candidate"])
        self.assertEqual(
            1,
            pastor["category_counts"]["configured_pastor_identity_unlinked"],
        )
        self.assertEqual(
            1,
            pastor["category_counts"]["profile_linked_analytical_gate_blocked"],
        )
        self.assertEqual([1], pastor["missing_from_inventory"])
        self.assertFalse(pastor["inventory_query_matches"])
        self.assertEqual(
            "reviewed_baseline_cohort",
            pastor["videos"][0]["period_provenance"],
        )
        self.assertIn("candidate_query_mismatch", report["blockers"])

    def test_backfill_plan_selects_only_exact_topic_analysis_blockers(self) -> None:
        audit = {
            "policy_version": "salvation-candidate-discovery-audit-v1",
            "input_fingerprint": "a" * 64,
            "pastors": [
                {
                    "display_name": "Pastor Example",
                    "profile_id": 42,
                    "current_candidate_video_ids": [1, 2, 3],
                    "videos": [
                        {
                            "video_id": 4,
                            "youtube_video_id": "youtube-4",
                            "title": "Needs topics",
                            "category": "profile_linked_analytical_gate_blocked",
                            "production_eligible": True,
                            "gate_reason_codes": ["topic_analysis_unavailable"],
                        },
                        {
                            "video_id": 5,
                            "youtube_video_id": "youtube-5",
                            "title": "Needs identity too",
                            "category": "profile_linked_analytical_gate_blocked",
                            "production_eligible": True,
                            "gate_reason_codes": [
                                "effective_profile_membership_unavailable",
                                "topic_analysis_unavailable",
                            ],
                        },
                        {
                            "video_id": 6,
                            "youtube_video_id": "youtube-6",
                            "title": "Not linked",
                            "category": "configured_pastor_identity_unlinked",
                            "production_eligible": True,
                            "gate_reason_codes": ["topic_analysis_unavailable"],
                        },
                    ],
                }
            ],
        }

        report = build_salvation_analytical_backfill_plan(audit)

        self.assertEqual([4], report["video_ids"])
        pastor = report["pastors"][0]
        self.assertEqual(1, pastor["backfill_target_count"])
        self.assertEqual(4, pastor["projected_candidate_maximum"])
        self.assertFalse(pastor["could_reach_target_after_backfill"])
        self.assertEqual([5], [item["video_id"] for item in pastor["excluded_linked_gate_blockers"]])
        self.assertFalse(report["selection_rule"]["identity_changes_allowed"])


if __name__ == "__main__":
    unittest.main()
