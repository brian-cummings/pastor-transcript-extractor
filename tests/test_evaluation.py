from __future__ import annotations

import json
import unittest
from pathlib import Path

from pastor_transcript_extractor.evaluation import (
    aggregate_confidence_ablations,
    aggregate_results,
    build_markdown_report,
    build_confidence_ablations,
    build_failure_analysis,
    build_failure_markdown,
    evaluate_fixture_payload,
)


def segments() -> list[dict[str, object]]:
    return [
        {"start_seconds": index * 10.0, "end_seconds": (index + 1) * 10.0, "text": f"segment {index}"}
        for index in range(5)
    ]


def proposed(retained: list[int], *, confidence: str = "low") -> dict[str, object]:
    return {
        "segments": segments(),
        "sermon_window": {"source": "detected"},
        "classification": {
            "method": "adaptive_llm_v3",
            "model": "fixture-model",
            "prompt_version": "v2",
            "confidence_tier": confidence,
            "retained_segment_indexes": retained,
            "uncertain_block_ids": [],
            "confidence_reasons": [
                {
                    "code": "rule_llm_agreement",
                    "value": 0.0,
                    "effect": "forces_low",
                },
                {
                    "code": "central_consistency",
                    "warnings": [],
                    "effect": "passed",
                },
            ],
            "cache_stats": {"hits": 3, "misses": 0},
            "search": {
                "schema_version": 1,
                "algorithm_version": "adaptive_llm_v3",
                "model_digest": "digest",
                "selected_rank": 1,
                "rule_baseline": {"start_seconds": 0.0, "end_seconds": 20.0},
                "candidates": [
                    {"rank": 1, "start_seconds": 10.0, "end_seconds": 40.0},
                    {"rank": 2, "start_seconds": 0.0, "end_seconds": 10.0},
                ],
            },
        },
        "final_disposition": {
            "status": "accepted_sermon" if confidence == "high" else "rejected_no_sermon",
            "reason_codes": [],
        },
    }


class EvaluationTests(unittest.TestCase):
    def test_confidence_ablations_remove_veto_without_making_low_overlap_high(self) -> None:
        classification = proposed([1])["classification"]
        assert isinstance(classification, dict)

        ablations = build_confidence_ablations(classification)

        self.assertEqual("low", ablations["current"]["tier"])
        self.assertEqual("high", ablations["no_rule_overlap"]["tier"])
        self.assertEqual("medium", ablations["soft_rule_overlap"]["tier"])
        self.assertEqual("downgrade_one_tier", ablations["soft_rule_overlap"]["rule_overlap_effect"])

    def test_confidence_ablations_preserve_non_rule_safety_caps(self) -> None:
        classification = proposed([1])["classification"]
        assert isinstance(classification, dict)
        classification["uncertain_block_ids"] = [3]
        uncertain = build_confidence_ablations(classification)
        self.assertEqual("medium", uncertain["no_rule_overlap"]["tier"])
        self.assertEqual("medium", uncertain["soft_rule_overlap"]["tier"])

        reasons = classification["confidence_reasons"]
        assert isinstance(reasons, list)
        consistency = next(item for item in reasons if item["code"] == "central_consistency")
        consistency["warnings"] = ["center lacks sustained exposition"]
        failed = build_confidence_ablations(classification)
        self.assertEqual("low", failed["no_rule_overlap"]["tier"])
        self.assertEqual("low", failed["soft_rule_overlap"]["tier"])

    def test_confidence_ablations_keep_empty_candidate_low_without_overlap_evidence(self) -> None:
        classification = proposed([])["classification"]
        assert isinstance(classification, dict)
        classification["confidence_reasons"] = []

        ablations = build_confidence_ablations(classification)

        self.assertEqual("low", ablations["no_rule_overlap"]["tier"])
        self.assertEqual("low", ablations["soft_rule_overlap"]["tier"])
        self.assertEqual("not_applicable", ablations["soft_rule_overlap"]["rule_overlap_effect"])

    def test_failure_analysis_attributes_duplicate_block_ids_by_phase_order(self) -> None:
        fixture = {
            "video_id": "failure",
            "expected_outcome": "sermon",
            "expected_spans": [{"start_seconds": 10.0, "end_seconds": 30.0}],
            "allowed_interruptions": [],
        }
        payload = proposed([2, 3])
        classification = payload["classification"]
        assert isinstance(classification, dict)
        classification["blocks"] = [
            {"block_id": 1, "start_seconds": 0.0, "end_seconds": 30.0, "segment_indexes": [0, 1, 2]},
            {"block_id": 1, "start_seconds": 10.0, "end_seconds": 20.0, "segment_indexes": [1]},
        ]
        classification["classifications"] = [
            {"block_id": 1, "label": "sermon", "evidence": "coarse:exposition"},
            {"block_id": 1, "label": "music", "evidence": "fine:music_or_lyrics"},
        ]

        analysis = build_failure_analysis(fixture, payload)

        self.assertEqual(1, len(analysis["missed_segment_ranges"]))
        evidence = analysis["missed_range_classifications"]
        self.assertEqual(["coarse", "fine"], [item["phase"] for item in evidence])
        self.assertEqual(["sermon", "music"], [item["label"] for item in evidence])
        self.assertEqual("not_persisted", analysis["candidate_score_components_status"])
        self.assertIn("Failure Analysis: failure", build_failure_markdown(analysis))

    def test_rule_only_artifact_is_not_counted_as_production_path_evidence(self) -> None:
        fixture = {
            "video_id": "stale",
            "expected_outcome": "sermon",
            "expected_spans": [{"start_seconds": 0.0, "end_seconds": 10.0}],
            "allowed_interruptions": [],
            "ground_truth_version": 1,
        }
        payload = proposed([0])
        payload["classification"] = {
            "method": "rule_only",
            "retained_segment_indexes": [0],
        }

        result = evaluate_fixture_payload(
            fixture,
            payload,
            fixture_path=Path("stale.json"),
            proposed_path=Path("proposed.json"),
        )

        self.assertEqual("stale_or_non_adaptive_classification", result["status"])

    def test_positive_metrics_are_segment_based_and_interruptions_are_contamination_if_retained(self) -> None:
        fixture = {
            "video_id": "positive",
            "expected_outcome": "sermon",
            "expected_spans": [
                {"start_seconds": 10.0, "end_seconds": 20.0},
                {"start_seconds": 30.0, "end_seconds": 40.0},
            ],
            "allowed_interruptions": [{"start_seconds": 20.0, "end_seconds": 30.0}],
            "ground_truth_version": 1,
        }

        result = evaluate_fixture_payload(
            fixture,
            proposed([1, 2, 3, 4]),
            fixture_path=Path("positive.json"),
            proposed_path=Path("proposed.json"),
        )

        self.assertEqual(2, result["expected_retained_segment_count"])
        self.assertEqual(2, result["true_positive_retained_segment_count"])
        self.assertEqual(2, result["contaminating_segment_count"])
        self.assertEqual(1, result["retained_allowed_interruption_segment_count"])
        self.assertEqual(1.0, result["sermon_recall"])
        self.assertEqual(0.5, result["contamination_ratio"])
        self.assertTrue(result["correct_top_candidate"])
        self.assertEqual("digest", result["model_digest"])

    def test_negative_distinguishes_candidate_from_high_confidence_acceptance(self) -> None:
        fixture = {
            "video_id": "negative",
            "expected_outcome": "no_sermon",
            "expected_spans": [],
            "allowed_interruptions": [],
            "ground_truth_version": 1,
        }
        low = evaluate_fixture_payload(
            fixture,
            proposed([1], confidence="low"),
            fixture_path=Path("negative.json"),
            proposed_path=Path("proposed.json"),
        )
        high = evaluate_fixture_payload(
            fixture,
            proposed([1], confidence="high"),
            fixture_path=Path("negative.json"),
            proposed_path=Path("proposed.json"),
        )

        self.assertTrue(low["candidate_produced"])
        self.assertFalse(low["false_high_confidence_acceptance"])
        self.assertTrue(low["baseline_protection_prevented_replacement"])
        self.assertFalse(low["false_accepted_disposition"])
        self.assertTrue(high["false_high_confidence_acceptance"])
        self.assertTrue(high["false_accepted_disposition"])

    def test_aggregate_keeps_positive_and_negative_failure_gates_separate(self) -> None:
        aggregate = aggregate_results(
            [
                {
                    "status": "evaluated",
                    "expected_outcome": "sermon",
                    "sermon_recall": 0.8,
                    "contamination_ratio": 0.1,
                    "catastrophic_omission": True,
                    "correct_top_candidate": False,
                },
                {
                    "status": "evaluated",
                    "expected_outcome": "no_sermon",
                    "candidate_produced": True,
                    "false_high_confidence_acceptance": False,
                },
            ]
        )
        self.assertEqual(1, aggregate["catastrophic_omissions"])
        self.assertEqual(1, aggregate["negative_candidates_produced"])
        self.assertEqual(0, aggregate["negative_high_confidence_false_positives"])

    def test_ablation_aggregate_reports_negative_promotions_per_policy(self) -> None:
        result = {
            "video_id": "negative",
            "status": "evaluated",
            "expected_outcome": "no_sermon",
            "candidate_produced": True,
            "confidence_ablations": {
                "current": {"tier": "low"},
                "no_rule_overlap": {"tier": "high"},
                "soft_rule_overlap": {"tier": "medium"},
            },
        }

        aggregate = aggregate_confidence_ablations([result])

        self.assertEqual(0, aggregate["current"]["negative_high_confidence_false_positives"])
        self.assertEqual(1, aggregate["no_rule_overlap"]["negative_high_confidence_false_positives"])
        self.assertEqual(["negative"], aggregate["no_rule_overlap"]["negative_high_confidence_video_ids"])
        self.assertEqual(0, aggregate["soft_rule_overlap"]["negative_high_confidence_false_positives"])
        json.dumps(aggregate, sort_keys=True)

    def test_markdown_report_includes_per_fixture_ablation_transitions(self) -> None:
        result = {
            "video_id": "fixture",
            "status": "evaluated",
            "expected_outcome": "no_sermon",
            "candidate_produced": True,
            "false_high_confidence_acceptance": False,
            "confidence_tier": "low",
            "retained_segment_count": 1,
            "false_positive_ratio": 0.1,
            "baseline_protection_prevented_replacement": True,
            "confidence_ablations": {
                "current": {"tier": "low"},
                "no_rule_overlap": {"tier": "high"},
                "soft_rule_overlap": {"tier": "medium"},
            },
        }
        run = {
            "run_id": "run",
            "results": [result],
            "aggregate": {
                **aggregate_results([result]),
                "confidence_ablations": aggregate_confidence_ablations([result]),
            },
        }

        report = build_markdown_report(run)

        self.assertIn("| fixture | no_sermon | low | high | medium |", report)


if __name__ == "__main__":
    unittest.main()
