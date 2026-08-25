from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from pastor_transcript_extractor.fixture_validation import validate_fixture_payload
from pastor_transcript_extractor.pipeline_diagnostics import (
    aggregate_diagnostic_traces,
    build_diagnostic_markdown,
    build_diagnostic_trace,
    build_systemic_markdown,
)


def proposed_payload() -> dict[str, object]:
    segments = [
        {
            "start_seconds": float(index * 100),
            "end_seconds": float((index + 1) * 100),
            "text": f"segment {index}",
            "label": "sermon",
        }
        for index in range(4)
    ]
    blocks = [
        {
            "block_id": index,
            "segment_indexes": [index],
            "start_seconds": float(index * 100),
            "end_seconds": float((index + 1) * 100),
            "text": f"block {index}",
        }
        for index in range(3)
    ]
    return {
        "youtube_video_id": "fixture-video",
        "transcript_source": "captions",
        "segments": segments,
        "classification": {
            "method": "adaptive_llm_v3",
            "confidence_tier": "medium",
            "retained_segment_indexes": [1, 2],
            "warnings": ["candidate start moved forward"],
            "blocks": blocks,
            "classifications": [
                {
                    "block_id": index,
                    "label": "sermon",
                    "evidence": "coarse:biblical_exposition",
                }
                for index in range(3)
            ],
            "search": {
                "schema_version": 1,
                "algorithm_version": "adaptive_llm_v3",
                "selected_rank": 1,
                "rule_baseline": {
                    "start_seconds": 0.0,
                    "end_seconds": 300.0,
                    "confidence": 0.9,
                },
                "rule_baseline_source": "recomputed_rules",
                "rule_baseline_algorithm_version": "rule_based_v1",
                "discovery": {
                    "selected_mode": "primary",
                    "rescue_triggered": False,
                },
                "candidates": [
                    {
                        "rank": 1,
                        "source": "coarse_llm",
                        "start_seconds": 100.0,
                        "end_seconds": 300.0,
                        "score": 300.0,
                        "score_components": {"duration_seconds": 300.0},
                        "coarse_support_block_ids": [0, 1, 2],
                        "fine_support_block_ids": [1, 2],
                        "refinement_reasons": ["removed objective separator"],
                        "boundary_recovery": {
                            "start": {"status": "semantic_transition"},
                            "end": {"status": "semantic_transition"},
                        },
                    }
                ],
            },
        },
        "sermon_window": {
            "start_seconds": 100.0,
            "end_seconds": 300.0,
            "source": "hybrid_llm",
        },
        "final_disposition": {
            "status": "accepted_sermon",
            "reason_codes": ["high_confidence_effective_sermon_window"],
        },
    }


class PipelineDiagnosticTests(unittest.TestCase):
    def _write_proposed(self, root: Path) -> tuple[Path, dict[str, object]]:
        payload = proposed_payload()
        path = root / "proposed.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path, payload

    def _fixture(self, root: Path):
        path = root / "fixture-video.json"
        payload = {
            "video_id": "fixture-video",
            "expected_outcome": "sermon",
            "expected_spans": [{"start_seconds": 0.0, "end_seconds": 300.0}],
            "allowed_interruptions": [],
            "ground_truth_version": 1,
            "reviewed_by": "Reviewer",
        }
        path.write_text(json.dumps(payload), encoding="utf-8")
        return validate_fixture_payload(payload, path=path)

    def test_trace_localizes_fine_refinement_coverage_loss(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            proposed_path, proposed = self._write_proposed(root)

            trace = build_diagnostic_trace(
                proposed,
                proposed_path=proposed_path,
                youtube_video_id="fixture-video",
                database_video_id=7,
                fixture=self._fixture(root),
                media_duration_seconds=400.0,
            )

        stages = {stage["key"]: stage for stage in trace["stages"]}
        self.assertEqual(1.0, stages["transcript"]["measurements"]["previous_stage_retention"])
        self.assertEqual(1.0, stages["selected"]["measurements"]["reviewed_sermon_coverage"])
        self.assertAlmostEqual(
            2 / 3,
            stages["fine"]["measurements"]["reviewed_sermon_coverage"],
            places=5,
        )
        self.assertEqual(100.0, stages["fine"]["transition"]["seconds_removed"])
        self.assertEqual("fine", trace["earliest_observed_failure"]["stage"])
        self.assertEqual("fine_refinement", trace["root_cause_hypothesis"]["stage"])
        self.assertEqual(
            "sermon-isolation-contracts-v1",
            trace["contract_definition"]["version"],
        )

    def test_human_views_are_deterministic_projections_of_trace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            proposed_path, proposed = self._write_proposed(root)
            trace = build_diagnostic_trace(
                proposed,
                proposed_path=proposed_path,
                youtube_video_id="fixture-video",
                fixture=self._fixture(root),
            )

        report = build_diagnostic_markdown(trace)
        self.assertIn("## Pipeline loss map", report)
        self.assertIn("flowchart LR", report)
        self.assertIn("## Timeline overlay", report)
        self.assertIn("Ground truth", report)
        self.assertIn("Fine refinement", report)
        self.assertIn("-33.3%", report)
        self.assertNotIn("-->| |", report)

    def test_unreviewed_trace_does_not_claim_sermon_recall(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            proposed_path, proposed = self._write_proposed(root)
            trace = build_diagnostic_trace(
                proposed,
                proposed_path=proposed_path,
                youtube_video_id="production-video",
            )

        self.assertTrue(
            all(
                stage["contract"]["status"] in {"not_evaluated", "fail"}
                for stage in trace["stages"]
            )
        )
        self.assertTrue(
            all(
                "reviewed_sermon_coverage" not in stage["measurements"]
                for stage in trace["stages"]
            )
        )
        self.assertIn(
            "Ground truth is unavailable; no sermon recall or contamination claims are made.",
            build_diagnostic_markdown(trace),
        )

    def test_allowed_interruption_is_not_counted_as_contamination(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            proposed_path, proposed = self._write_proposed(root)
            fixture_path = root / "fixture-video.json"
            payload = {
                "video_id": "fixture-video",
                "expected_outcome": "sermon",
                "expected_spans": [
                    {"start_seconds": 0.0, "end_seconds": 100.0},
                    {"start_seconds": 120.0, "end_seconds": 300.0},
                ],
                "allowed_interruptions": [
                    {"start_seconds": 100.0, "end_seconds": 120.0}
                ],
                "ground_truth_version": 1,
                "reviewed_by": "Reviewer",
            }
            fixture = validate_fixture_payload(payload, path=fixture_path)
            trace = build_diagnostic_trace(
                proposed,
                proposed_path=proposed_path,
                youtube_video_id="fixture-video",
                fixture=fixture,
            )

        rule = next(stage for stage in trace["stages"] if stage["key"] == "rule")
        self.assertEqual(0.0, rule["measurements"]["contamination_ratio"])

    def test_systemic_view_separates_observed_failures_from_hypotheses(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            proposed_path, proposed = self._write_proposed(root)
            trace = build_diagnostic_trace(
                proposed,
                proposed_path=proposed_path,
                youtube_video_id="fixture-video",
                fixture=self._fixture(root),
            )

        systemic = aggregate_diagnostic_traces([trace])
        self.assertEqual({"fine": 1}, systemic["observed_failure_counts"])
        self.assertEqual(
            {"coverage_lost_during_fine_refinement": 1},
            systemic["root_cause_hypothesis_counts"],
        )
        markdown = build_systemic_markdown(systemic)
        self.assertIn("Observed contract violations", markdown)
        self.assertIn("Root-cause hypotheses", markdown)


if __name__ == "__main__":
    unittest.main()
