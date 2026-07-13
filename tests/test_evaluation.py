from __future__ import annotations

import unittest
from pathlib import Path

from pastor_transcript_extractor.evaluation import aggregate_results, evaluate_fixture_payload


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
    }


class EvaluationTests(unittest.TestCase):
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
        self.assertTrue(high["false_high_confidence_acceptance"])

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


if __name__ == "__main__":
    unittest.main()
