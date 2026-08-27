from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from pastor_transcript_extractor.fixture_validation import validate_fixture_payload
from pastor_transcript_extractor.pipeline_diagnostics import (
    aggregate_diagnostic_traces,
    build_comparison_markdown,
    build_diagnostic_markdown,
    build_diagnostic_trace,
    build_identity_automation_blocker_analysis,
    build_identity_operational_outcome,
    build_systemic_outcome_mermaid,
    build_systemic_markdown,
    compare_systemic_reports,
    load_identity_association_attempts,
    load_identity_boundary_feedback,
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
                        "start_seconds": 0.0,
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
            "selection_manifest": {
                "evaluation_partition": "development",
                "source_family_id": "youtube-test-family",
                "selection_origin": "automatic",
            },
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
            "sermon-isolation-contracts-v6",
            trace["contract_definition"]["version"],
        )
        self.assertEqual(7, trace["schema_version"])
        self.assertEqual("refinement_loss", trace["candidate_regret"]["classification"])
        self.assertEqual(
            "localization_regression",
            trace["stage_regret"]["refinement"]["classification"],
        )
        self.assertEqual(
            "fine", trace["contract_paths"]["localization"]["likely_causal_stage"]
        )
        self.assertEqual("fail", trace["overall_outcome"]["status"])
        self.assertEqual("development", trace["cohort"]["evaluation_partition"])

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

    def test_candidate_envelope_is_not_replaced_by_coarse_support_extent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            proposed_path, proposed = self._write_proposed(root)
            candidate = proposed["classification"]["search"]["candidates"][0]
            candidate["coarse_support_block_ids"] = [1]
            proposed_path.write_text(json.dumps(proposed), encoding="utf-8")
            trace = build_diagnostic_trace(
                proposed,
                proposed_path=proposed_path,
                youtube_video_id="fixture-video",
                fixture=self._fixture(root),
            )

        stages = {stage["key"]: stage for stage in trace["stages"]}
        self.assertAlmostEqual(
            1 / 3,
            stages["coarse_evidence"]["measurements"]["reviewed_sermon_coverage"],
            places=5,
        )
        self.assertEqual("informational", stages["coarse_evidence"]["contract"]["status"])
        self.assertEqual(
            1.0,
            stages["candidates"]["measurements"]["reviewed_sermon_coverage"],
        )

    def test_manual_override_masks_automatic_candidate_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            proposed_path, proposed = self._write_proposed(root)
            candidate = proposed["classification"]["search"]["candidates"][0]
            candidate["start_seconds"] = 100.0
            proposed["classification"]["search"]["rule_baseline_source"] = (
                "manual_override"
            )
            proposed["classification"]["search"]["rule_baseline_algorithm_version"] = (
                "manual_override_v1"
            )
            proposed["sermon_window"].update(
                {
                    "start_seconds": 0.0,
                    "end_seconds": 300.0,
                    "source": "override",
                    "method": "manual_override_v1",
                }
            )
            proposed_path.write_text(json.dumps(proposed), encoding="utf-8")
            trace = build_diagnostic_trace(
                proposed,
                proposed_path=proposed_path,
                youtube_video_id="fixture-video",
                fixture=self._fixture(root),
            )

        self.assertEqual("candidates", trace["earliest_observed_failure"]["stage"])
        self.assertEqual("masked_by_manual_override", trace["recovery_status"])
        self.assertTrue(trace["outcome_contracts"]["manual_override_applied"])
        self.assertEqual("pass_with_manual_override", trace["overall_outcome"]["status"])
        self.assertIn(
            "automatic_pre_override_final_not_persisted",
            {gap["code"] for gap in trace["diagnostic_gaps"]},
        )

    def test_arbitration_failure_is_separate_from_valid_refinement(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            proposed_path, proposed = self._write_proposed(root)
            proposed["classification"]["retained_segment_indexes"] = [0, 1, 2]
            proposed_path.write_text(json.dumps(proposed), encoding="utf-8")
            trace = build_diagnostic_trace(
                proposed,
                proposed_path=proposed_path,
                youtube_video_id="fixture-video",
                fixture=self._fixture(root),
            )

        stages = {stage["key"]: stage for stage in trace["stages"]}
        self.assertEqual("pass", stages["fine"]["contract"]["status"])
        self.assertEqual("fail", stages["arbitration"]["contract"]["status"])
        self.assertEqual("arbitration", trace["earliest_observed_failure"]["stage"])
        systemic = aggregate_diagnostic_traces([trace])
        self.assertEqual(1, systemic["failure_signature_counts"][
            "arbitration_clipped_valid_refined_window"
        ])
        self.assertEqual(1, systemic["failure_signature_counts"][
            "arbitration_localization_regression"
        ])

    def test_recording_verifier_false_positive_is_earliest_negative_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            proposed_path, proposed = self._write_proposed(root)
            proposed["recording_verification"] = {
                "source": "llm_recording_verifier",
                "decision": "worship_service_sermon",
                "predicted_outcome": "sermon",
                "confidence": "high",
                "reason_codes": ["single_sustained_message"],
            }
            proposed_path.write_text(json.dumps(proposed), encoding="utf-8")
            fixture_path = root / "negative.json"
            payload = {
                "video_id": "fixture-video",
                "expected_outcome": "no_sermon",
                "expected_spans": [],
                "allowed_interruptions": [],
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

        self.assertEqual("verifier", trace["earliest_observed_failure"]["stage"])
        self.assertEqual(
            "recording_verifier",
            trace["root_cause_hypothesis"]["stage"],
        )
        systemic = aggregate_diagnostic_traces([trace])
        self.assertEqual(
            {"recording_verifier_false_positive": 1},
            systemic["failure_signature_counts"],
        )

    def test_positive_verifier_and_disposition_failures_are_composed_separately(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            proposed_path, proposed = self._write_proposed(root)
            proposed["classification"]["retained_segment_indexes"] = [0, 1, 2]
            proposed["sermon_window"].update(
                {
                    "start_seconds": 0.0,
                    "end_seconds": 300.0,
                    "included_segment_indexes": [0, 1, 2],
                }
            )
            proposed["recording_verification"] = {
                "source": "llm_recording_verifier",
                "decision": "multi_speaker_or_student_program",
                "predicted_outcome": "no_sermon",
                "confidence": "high",
                "reason_codes": ["multiple_short_speakers_or_sermonettes"],
            }
            proposed["final_disposition"] = {
                "status": "rejected_ambiguous_speakers",
                "reason_codes": ["recording_verifier_multi_speaker_or_student_program"],
            }
            proposed_path.write_text(json.dumps(proposed), encoding="utf-8")
            trace = build_diagnostic_trace(
                proposed,
                proposed_path=proposed_path,
                youtube_video_id="fixture-video",
                fixture=self._fixture(root),
            )

        self.assertEqual("pass", trace["outcome_contracts"]["localization"]["status"])
        self.assertEqual("fail", trace["outcome_contracts"]["verifier"]["status"])
        self.assertEqual("fail", trace["outcome_contracts"]["disposition"]["status"])
        self.assertEqual(
            "rejected_ambiguous_speakers",
            trace["outcome_contracts"]["disposition"]["value"],
        )
        self.assertEqual("fail", trace["overall_outcome"]["status"])
        self.assertIn("verifier", trace["overall_outcome"]["failed_dimensions"])
        self.assertIn("disposition", trace["overall_outcome"]["failed_dimensions"])

    def test_final_contamination_breach_is_an_observed_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            proposed_path, proposed = self._write_proposed(root)
            proposed["classification"]["retained_segment_indexes"] = [0, 1, 2]
            proposed["sermon_window"].update(
                {
                    "start_seconds": 0.0,
                    "end_seconds": 400.0,
                    "included_segment_indexes": [0, 1, 2, 3],
                }
            )
            proposed_path.write_text(json.dumps(proposed), encoding="utf-8")
            trace = build_diagnostic_trace(
                proposed,
                proposed_path=proposed_path,
                youtube_video_id="fixture-video",
                fixture=self._fixture(root),
            )

        self.assertEqual("arbitration", trace["earliest_observed_failure"]["stage"])
        self.assertEqual(
            "contamination_above_contract",
            trace["earliest_observed_failure"]["code"],
        )
        self.assertEqual(
            "contamination_introduced_or_retained",
            trace["root_cause_hypothesis"]["code"],
        )
        self.assertEqual("fail", trace["overall_outcome"]["status"])

    def test_arbitration_ignores_immaterial_numeric_jitter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            proposed_path, proposed = self._write_proposed(root)
            proposed["classification"]["retained_segment_indexes"] = [0, 1, 2]
            proposed["sermon_window"].update(
                {"start_seconds": 0.0, "end_seconds": 299.9}
            )
            proposed_path.write_text(json.dumps(proposed), encoding="utf-8")
            trace = build_diagnostic_trace(
                proposed,
                proposed_path=proposed_path,
                youtube_video_id="fixture-video",
                fixture=self._fixture(root),
            )

        arbitration = trace["stage_regret"]["arbitration"]
        self.assertEqual("none", arbitration["classification"])
        self.assertGreater(arbitration["coverage_regret_against_fine"], 0.0)
        self.assertEqual(0.01, arbitration["materiality_thresholds"]["coverage_delta"])

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

    def test_all_existing_population_separates_reviewed_and_unreviewed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            reviewed_path, reviewed_proposed = self._write_proposed(root)
            reviewed = build_diagnostic_trace(
                reviewed_proposed,
                proposed_path=reviewed_path,
                youtube_video_id="fixture-video",
                fixture=self._fixture(root),
            )
            unreviewed_path = root / "unreviewed.json"
            unreviewed_proposed = proposed_payload()
            unreviewed_proposed["youtube_video_id"] = "production-video"
            unreviewed_path.write_text(
                json.dumps(unreviewed_proposed), encoding="utf-8"
            )
            unreviewed = build_diagnostic_trace(
                unreviewed_proposed,
                proposed_path=unreviewed_path,
                youtube_video_id="production-video",
                identity_outcome=build_identity_operational_outcome(
                    content_disposition="accepted_sermon",
                    extraction_result_id=12,
                    observation={"id": 5, "extraction_result_id": 12},
                    effective_profile_ids=[7],
                    association_attempts=[
                        {"observation_id": 5, "outcome": "proposed_match"}
                    ],
                    boundary_feedback=[{"edge": "start"}],
                ),
            )

        report = aggregate_diagnostic_traces(
            [reviewed, unreviewed],
            missing=[
                {
                    "youtube_video_id": "fixture-without-extraction",
                    "reason": "reviewed_fixture_video_or_extraction_missing",
                }
            ],
            scope="all_existing",
            population_summary={
                "population_count": 4,
                "database_video_count": 4,
                "latest_extraction_count": 2,
                "videos_without_extraction_count": 2,
                "videos_without_extraction_status_counts": {"failed": 2},
            },
        )
        population = report["population"]
        self.assertEqual("all_existing", population["scope"])
        self.assertEqual(1, population["reviewed_trace_count"])
        self.assertEqual(1, population["unreviewed_trace_count"])
        self.assertEqual(0, population["extraction_artifact_missing_or_invalid_count"])
        self.assertEqual(1, population["reviewed_fixture_without_trace_count"])
        self.assertEqual(
            {"accepted_sermon": 1},
            report["unreviewed_final_disposition_counts"],
        )
        self.assertEqual(1, sum(report["positive_localization_contract_counts"].values()))
        mermaid = build_systemic_outcome_mermaid(report)
        self.assertIn("Database videos<br/>4", mermaid)
        self.assertIn("No extraction record<br/>2", mermaid)
        self.assertIn("Reviewed subset<br/>1", mermaid)
        self.assertIn("Unreviewed subset<br/>1", mermaid)
        self.assertIn("Reviewed fixture without trace<br/>1", mermaid)
        self.assertIn("accepted sermon<br/>2", mermaid)
        self.assertIn("failed<br/>2", mermaid)
        self.assertIn("Identity operational outcomes<br/>2", mermaid)
        self.assertIn("profiled<br/>1", mermaid)
        self.assertNotIn("Association attempts<br/>", mermaid)
        self.assertNotIn("Effective reviewed profile membership<br/>", mermaid)
        markdown = build_systemic_markdown(report)
        self.assertIn("## All-outcome map", markdown)
        self.assertIn("## Operational dispositions", markdown)
        self.assertIn("## Identity operational outcomes", markdown)
        self.assertIn("### Sermon-to-identity transitions", markdown)
        self.assertIn("Identity processing volume (not population counts)", markdown)
        self.assertTrue(
            report["identity_outcome_summary"]["state_counts_reconcile"]
        )
        self.assertEqual(
            {"not_observed": 1, "profiled": 1},
            report["identity_outcome_summary"]["state_counts"],
        )
        self.assertEqual(
            {"accepted_sermon": {"not_observed": 1, "profiled": 1}},
            report["identity_outcome_summary"]["state_counts_by_disposition"],
        )

    def test_identity_attempt_loader_and_stale_observation_truth_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run = root / "run"
            run.mkdir()
            payload = {
                "artifact_kind": "speaker_profile_shadow_association",
                "created_at": "2026-08-26T12:00:00+00:00",
                "candidate": {
                    "video_id": 9,
                    "observation_id": 4,
                    "input_fingerprint": "observation-4",
                },
                "outcome": "no_match",
                "proposed_profile_id": None,
                "routing": {
                    "candidate_funnel": {
                        "retrospective_evaluation": {
                            "leave_one_out_applied": True,
                            "membership_used_as_routing_evidence": False,
                        },
                        "version": "association_candidate_funnel_v1",
                        "canonical_profile_ids": [3],
                    }
                },
            }
            (run / "association.json").write_text(
                json.dumps(payload), encoding="utf-8"
            )
            attempts = load_identity_association_attempts(
                root, database_video_ids={9}
            )

        self.assertEqual("no_match", attempts[9][0]["outcome"])
        self.assertEqual(
            "artifact_created_at", attempts[9][0]["ordering_basis"]
        )
        self.assertEqual(
            [3], attempts[9][0]["candidate_funnel"]["canonical_profile_ids"]
        )
        outcome = build_identity_operational_outcome(
            content_disposition="accepted_sermon",
            extraction_result_id=8,
            observation={"id": 4, "extraction_result_id": 7},
            effective_profile_ids=[3],
            association_attempts=attempts[9],
        )
        self.assertEqual("stale_observation", outcome["state"])
        self.assertEqual([], outcome["effective_profile_ids"])
        self.assertEqual(0, outcome["association_attempt_count"])

        current = build_identity_operational_outcome(
            content_disposition="accepted_sermon",
            extraction_result_id=8,
            observation={"id": 4, "extraction_result_id": 8},
            association_attempts=[
                {
                    "artifact_path": "run-a/association.json",
                    "observation_id": 4,
                    "outcome": "insufficient_evidence",
                },
                {
                    "artifact_path": "run-b/association.json",
                    "observation_id": 4,
                    "outcome": "no_match",
                },
            ],
        )
        self.assertEqual("association_no_match", current["state"])
        self.assertEqual("no_match", current["latest_association_outcome"])

        terminal = build_identity_operational_outcome(
            content_disposition="rejected_no_sermon",
            extraction_result_id=8,
            observation={"id": 4, "extraction_result_id": 8},
        )
        self.assertEqual("content_terminal_with_observation", terminal["state"])

    def test_reviewed_identity_candidate_funnel_locates_retrieval_cutoff(self) -> None:
        outcome = build_identity_operational_outcome(
            content_disposition="accepted_sermon",
            extraction_result_id=8,
            observation={"id": 4, "extraction_result_id": 8},
            effective_profile_ids=[7],
            association_attempts=[
                {
                    "artifact_path": "run/association.json",
                    "created_at": "2026-08-26T12:00:00+00:00",
                    "ordering_basis": "artifact_created_at",
                    "observation_id": 4,
                    "outcome": "insufficient_evidence",
                    "candidate_funnel": {
                        "retrospective_evaluation": {
                            "leave_one_out_applied": True,
                            "membership_used_as_routing_evidence": False,
                        },
                        "canonical_profile_ids": [7, 8],
                        "comparison_eligible_profile_ids": [7, 8],
                        "retrieval_candidates": [
                            {
                                "profile_id": 7,
                                "name_match": False,
                                "source_match": False,
                                "routing_policy_eligible": True,
                                "acoustic_similarity": 0.81,
                                "acoustic_rank": 4,
                                "passed_shortlist_cutoff": False,
                                "selected_for_comparison": False,
                            }
                        ],
                        "acoustic_shortlist": {
                            "maximum_profiles": 3,
                            "cutoff_score": 0.82,
                        },
                        "profiles_actually_compared": [8],
                    },
                }
            ],
        )

        review = outcome["candidate_funnel_review"]
        self.assertEqual("retrieval_miss", review["observed_failure_location"])
        self.assertEqual(
            "retrieved_below_shortlist_cutoff", review["classification"]
        )
        self.assertEqual(
            {
                "name": "miss",
                "source": "miss",
                "acoustic": "below_cutoff",
                "all_eligible_acoustic_rank": None,
            },
            review["evidence"]["retrieval_source_outcomes"],
        )
        self.assertEqual(
            ["name_retrieval_route_absent", "source_retrieval_route_absent"],
            review["causal_hypotheses"],
        )

    def test_reviewed_identity_candidate_funnel_resolves_redirect_and_proposal(self) -> None:
        attempt = {
            "artifact_path": "run/association.json",
            "created_at": "2026-08-26T12:00:00+00:00",
            "ordering_basis": "artifact_created_at",
            "observation_id": 4,
            "outcome": "proposed_match",
            "proposed_profile_id": 7,
            "candidate_funnel": {
                "retrospective_evaluation": {
                    "leave_one_out_applied": True,
                    "membership_used_as_routing_evidence": False,
                },
                "canonical_profile_ids": [7],
                "comparison_eligible_profile_ids": [7],
                "retrieval_candidates": [
                    {
                        "profile_id": 7,
                        "name_match": True,
                        "source_match": False,
                        "routing_policy_eligible": True,
                        "acoustic_rank": None,
                        "passed_shortlist_cutoff": None,
                        "selected_for_comparison": True,
                    }
                ],
                "profiles_actually_compared": [7],
            },
        }
        outcome = build_identity_operational_outcome(
            content_disposition="accepted_sermon",
            extraction_result_id=8,
            observation={"id": 4, "extraction_result_id": 8},
            effective_profile_ids=[9],
            association_attempts=[attempt],
            profile_redirects={7: 9, 9: 9},
        )

        review = outcome["candidate_funnel_review"]
        self.assertEqual("compared_and_proposed_correctly", review["classification"])
        self.assertTrue(review["resolution"]["redirect_resolution_applied"])
        self.assertIsNone(review["observed_failure_location"])

    def test_reviewed_identity_candidate_funnel_preserves_membership_firewall(self) -> None:
        base_funnel = {
            "retrospective_evaluation": {
                "leave_one_out_applied": True,
                "membership_used_as_routing_evidence": False,
            },
            "canonical_profile_ids": [7],
            "comparison_eligible_profile_ids": [7],
            "retrieval_candidates": [
                {
                    "profile_id": 7,
                    "name_match": False,
                    "source_match": True,
                    "routing_policy_eligible": True,
                    "acoustic_rank": None,
                    "passed_shortlist_cutoff": None,
                    "selected_for_comparison": True,
                }
            ],
            "profiles_actually_compared": [7],
        }
        outcome = build_identity_operational_outcome(
            content_disposition="accepted_sermon",
            extraction_result_id=8,
            observation={"id": 4, "extraction_result_id": 8},
            effective_profile_ids=[7],
            association_attempts=[
                {
                    "artifact_path": "run/association.json",
                    "created_at": "2026-08-26T12:00:00+00:00",
                    "observation_id": 4,
                    "outcome": "insufficient_evidence",
                    "proposed_profile_id": None,
                    "candidate_funnel": base_funnel,
                }
            ],
        )

        self.assertEqual(
            "compared_but_abstained",
            outcome["candidate_funnel_review"]["classification"],
        )
        self.assertEqual([7], outcome["effective_profile_ids"])

    def test_latest_identity_attempt_uses_persisted_creation_time(self) -> None:
        outcome = build_identity_operational_outcome(
            content_disposition="accepted_sermon",
            extraction_result_id=8,
            observation={"id": 4, "extraction_result_id": 8},
            association_attempts=[
                {
                    "artifact_path": "z-older.json",
                    "created_at": "2026-08-25T12:00:00+00:00",
                    "ordering_basis": "artifact_created_at",
                    "observation_id": 4,
                    "outcome": "insufficient_evidence",
                },
                {
                    "artifact_path": "a-newer.json",
                    "created_at": "2026-08-26T12:00:00+00:00",
                    "ordering_basis": "artifact_created_at",
                    "observation_id": 4,
                    "outcome": "no_match",
                },
            ],
        )

        self.assertEqual("no_match", outcome["latest_association_outcome"])
        self.assertEqual(
            "artifact_created_at", outcome["latest_attempt_ordering_basis"]
        )

    def test_reviewed_identity_candidate_funnel_observes_policy_filter(self) -> None:
        outcome = build_identity_operational_outcome(
            content_disposition="accepted_sermon",
            extraction_result_id=8,
            observation={"id": 4, "extraction_result_id": 8},
            effective_profile_ids=[7],
            association_attempts=[
                {
                    "artifact_path": "run/association.json",
                    "created_at": "2026-08-26T12:00:00+00:00",
                    "observation_id": 4,
                    "outcome": "insufficient_evidence",
                    "candidate_funnel": {
                        "retrospective_evaluation": {
                            "leave_one_out_applied": True,
                            "membership_used_as_routing_evidence": False,
                        },
                        "canonical_profile_ids": [7],
                        "comparison_eligible_profile_ids": [7],
                        "retrieval_candidates": [
                            {
                                "profile_id": 7,
                                "name_match": False,
                                "source_match": False,
                                "routing_policy_eligible": False,
                                "routing_policy_exclusion_reason_codes": [
                                    "discovery_candidate_unconfirmed_without_priority_route"
                                ],
                                "acoustic_rank": None,
                                "passed_shortlist_cutoff": None,
                                "selected_for_comparison": False,
                            }
                        ],
                        "profiles_actually_compared": [],
                    },
                }
            ],
        )

        review = outcome["candidate_funnel_review"]
        self.assertEqual(
            "filtered_by_readiness_policy_before_retrieval",
            review["classification"],
        )
        self.assertEqual(
            "readiness_policy_filter", review["observed_failure_location"]
        )

    def test_reviewed_identity_candidate_funnel_rejects_membership_leakage(self) -> None:
        outcome = build_identity_operational_outcome(
            content_disposition="accepted_sermon",
            extraction_result_id=8,
            observation={"id": 4, "extraction_result_id": 8},
            effective_profile_ids=[7],
            association_attempts=[
                {
                    "artifact_path": "run/association.json",
                    "created_at": "2026-08-26T12:00:00+00:00",
                    "observation_id": 4,
                    "outcome": "proposed_match",
                    "candidate_self_comparison": True,
                    "candidate_funnel": {
                        "retrospective_evaluation": {
                            "leave_one_out_applied": True,
                            "membership_used_as_routing_evidence": False,
                        }
                    },
                }
            ],
        )

        review = outcome["candidate_funnel_review"]
        self.assertEqual("not_evaluated", review["status"])
        self.assertEqual(
            "retrospective_membership_leakage", review["classification"]
        )

    def test_identity_blockers_expose_bridge_chain_without_predicting_unlock(self) -> None:
        trace = {
            "youtube_video_id": "candidate-video",
            "identity_outcome": {
                "content_disposition": "accepted_sermon",
                "observation_status": "current",
                "observation_id": 4,
                "effective_profile_ids": [],
                "latest_association_outcome": "proposed_match",
                "latest_association_attempt": {"proposed_profile_id": 136},
            },
            "identity_boundary_feedback": {},
        }
        analysis = build_identity_automation_blocker_analysis(
            [trace],
            profile_readiness=[{
                "profile_id": 136,
                "member_observation_ids": [1, 2, 3],
                "member_fingerprints": ["a", "b", "c"],
                "normalized_names": ["pastor example"],
                "automatic_blockers": [
                    "reviewed_same_graph_contains_bridge"
                ],
            }],
            reviewed_same_pairs=[("a", "b"), ("b", "c")],
            observation_by_fingerprint={
                "a": {"observation_id": 1, "youtube_video_id": "video-a"},
                "b": {"observation_id": 2, "youtube_video_id": "video-b"},
                "c": {"observation_id": 3, "youtube_video_id": "video-c"},
            },
        )

        blockers = {
            item["blocker_class"]: item
            for item in analysis["blocker_classes"]
        }
        bridge = blockers["review_graph_bridge"]
        self.assertEqual(1, bridge["directly_blocked_operation_count"])
        self.assertEqual(1, bridge["accepted_unresolved_sermon_count"])
        self.assertEqual(1, bridge["structurally_derived_operation_count"])
        self.assertEqual(
            136, bridge["structurally_derived_operations"][0]["profile_id"]
        )
        chain = analysis["profile_blocker_chains"][0]
        opportunity = chain["structurally_derived_next_operations"][0]
        self.assertEqual(["a", "c"], opportunity["fingerprints"])
        self.assertEqual(
            "structurally_derived_opportunity",
            opportunity["epistemic_status"],
        )
        self.assertFalse(
            analysis["epistemic_contract"]["speculative_cascades_counted"]
        )

    def test_identity_blockers_separate_implementation_stop_from_ambiguity(self) -> None:
        traces = [
            {
                "youtube_video_id": "not-attempted",
                "identity_outcome": {
                    "content_disposition": "accepted_sermon",
                    "observation_status": "current",
                    "observation_id": 1,
                    "effective_profile_ids": [],
                    "latest_association_outcome": None,
                },
                "identity_boundary_feedback": {},
            },
            {
                "youtube_video_id": "ambiguous",
                "identity_outcome": {
                    "content_disposition": "accepted_sermon",
                    "observation_status": "current",
                    "observation_id": 2,
                    "effective_profile_ids": [],
                    "latest_association_outcome": "ambiguous",
                    "latest_association_attempt": {},
                },
                "identity_boundary_feedback": {},
            },
        ]

        analysis = build_identity_automation_blocker_analysis(traces)

        blockers = {
            item["blocker_class"]: item
            for item in analysis["blocker_classes"]
        }
        self.assertEqual(
            "not_inherently_required",
            blockers["association_not_attempted"]["human_necessity"][
                "classification"
            ],
        )
        self.assertEqual(
            "likely_required",
            blockers["comparison_ambiguous"]["human_necessity"][
                "classification"
            ],
        )

    def test_identity_blockers_keep_retrospective_failure_and_cause_separate(self) -> None:
        trace = {
            "youtube_video_id": "reviewed-video",
            "identity_outcome": {
                "content_disposition": "accepted_sermon",
                "observation_status": "current",
                "observation_id": 8,
                "effective_profile_ids": [7],
                "latest_association_outcome": "insufficient_evidence",
                "candidate_funnel_review": {
                    "status": "observed",
                    "observed_failure_location": "eligibility",
                    "classification": "correct_profile_ineligible",
                    "resolution": {"effective_profile_id": 7},
                    "evidence": {
                        "profile_exclusions": [{
                            "profile_id": 7,
                            "reason_codes": [
                                "fewer_than_required_eligible_acoustic_exemplars"
                            ],
                        }],
                    },
                    "causal_hypotheses": ["exemplar_preparation_gap"],
                },
            },
            "identity_boundary_feedback": {},
        }

        analysis = build_identity_automation_blocker_analysis([trace])

        blockers = {
            item["blocker_class"]: item
            for item in analysis["blocker_classes"]
        }
        blocker = blockers["retrospective_acoustic_exemplar_unavailable"]
        self.assertEqual("retrospective_reviewed_identity", blocker["evidence_scope"])
        self.assertEqual([7], blocker["affected_profile_ids"])
        self.assertEqual(["exemplar_preparation_gap"], blocker["causal_hypotheses"])
        self.assertEqual(0, blocker["accepted_unresolved_sermon_count"])
        self.assertEqual(0, blocker["directly_blocked_operation_count"])

    def test_systemic_markdown_includes_additive_automation_blocker_section(self) -> None:
        analysis = build_identity_automation_blocker_analysis([])
        report = aggregate_diagnostic_traces(
            [], identity_automation_blockers=analysis
        )

        markdown = build_systemic_markdown(report)

        self.assertIn("## Identity automation blockers and opportunity", markdown)
        self.assertFalse(
            analysis["epistemic_contract"]["speculative_cascades_counted"]
        )
        self.assertEqual(
            analysis,
            report["automation_blocker_analysis"]["domains"]["identity"],
        )

    def test_candidate_regret_distinguishes_discovery_and_ranking(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            proposed_path, proposed = self._write_proposed(root)
            proposed["classification"]["retained_segment_indexes"] = [0, 1, 2]
            candidates = proposed["classification"]["search"]["candidates"]
            candidates[0].update({"start_seconds": 100.0, "end_seconds": 300.0})
            candidates.append(
                {
                    "rank": 2,
                    "source": "coarse_llm",
                    "start_seconds": 0.0,
                    "end_seconds": 300.0,
                }
            )
            proposed_path.write_text(json.dumps(proposed), encoding="utf-8")
            trace = build_diagnostic_trace(
                proposed,
                proposed_path=proposed_path,
                youtube_video_id="fixture-video",
                fixture=self._fixture(root),
            )
            self.assertEqual("ranking_loss", trace["candidate_regret"]["classification"])
            self.assertAlmostEqual(
                1 / 3,
                trace["candidate_regret"]["selected_candidate_regret"],
                places=5,
            )

            candidates.pop()
            proposed_path.write_text(json.dumps(proposed), encoding="utf-8")
            trace = build_diagnostic_trace(
                proposed,
                proposed_path=proposed_path,
                youtube_video_id="fixture-video",
                fixture=self._fixture(root),
            )
            self.assertEqual(
                "discovery_omission", trace["candidate_regret"]["classification"]
            )

    def test_candidate_precision_distinguishes_proposal_and_ranking(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            proposed_path, proposed = self._write_proposed(root)
            fixture_path = root / "fixture-video.json"
            payload = {
                "video_id": "fixture-video",
                "expected_outcome": "sermon",
                "expected_spans": [
                    {"start_seconds": 100.0, "end_seconds": 250.0}
                ],
                "allowed_interruptions": [],
                "ground_truth_version": 1,
                "reviewed_by": "Reviewer",
            }
            fixture_path.write_text(json.dumps(payload), encoding="utf-8")
            fixture = validate_fixture_payload(payload, path=fixture_path)
            trace = build_diagnostic_trace(
                proposed,
                proposed_path=proposed_path,
                youtube_video_id="fixture-video",
                fixture=fixture,
            )
            self.assertEqual(
                "proposal_boundary_failure",
                trace["candidate_regret"]["precision_classification"],
            )
            self.assertEqual(
                "candidate_proposals_all_violate_precision_contract",
                trace["root_cause_hypothesis"]["code"],
            )

            proposed["classification"]["search"]["candidates"].append(
                {
                    "rank": 2,
                    "source": "coarse_llm",
                    "start_seconds": 100.0,
                    "end_seconds": 250.0,
                }
            )
            proposed_path.write_text(json.dumps(proposed), encoding="utf-8")
            trace = build_diagnostic_trace(
                proposed,
                proposed_path=proposed_path,
                youtube_video_id="fixture-video",
                fixture=fixture,
            )

        regret = trace["candidate_regret"]
        self.assertEqual("ranking_precision_loss", regret["precision_classification"])
        self.assertEqual(2, regret["best_precision_candidate_rank"])
        self.assertIn(2, regret["pareto_candidate_ranks"])
        self.assertEqual(
            "cleaner_complete_candidate_not_selected",
            trace["root_cause_hypothesis"]["code"],
        )

    def test_contamination_attribution_and_systemic_sensitivity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            proposed_path, proposed = self._write_proposed(root)
            fixture_path = root / "fixture-video.json"
            payload = {
                "video_id": "fixture-video",
                "expected_outcome": "sermon",
                "expected_spans": [{"start_seconds": 100.0, "end_seconds": 250.0}],
                "allowed_interruptions": [],
                "ground_truth_version": 1,
                "reviewed_by": "Reviewer",
            }
            fixture_path.write_text(json.dumps(payload), encoding="utf-8")
            fixture = validate_fixture_payload(payload, path=fixture_path)
            trace = build_diagnostic_trace(
                proposed,
                proposed_path=proposed_path,
                youtube_video_id="fixture-video",
                fixture=fixture,
            )

        attribution = trace["contamination_attribution"]
        self.assertEqual("selected", attribution["earliest_breach_stage"])
        self.assertIn("end_overreach", attribution["final_boundary_error_patterns"])
        self.assertEqual(
            50.0,
            attribution["final_contamination_seconds"]["end_overreach_seconds"],
        )
        self.assertEqual(
            "selected",
            attribution["terminal_component_causal_stages"][
                "end_overreach_seconds"
            ],
        )
        systemic = aggregate_diagnostic_traces([trace])
        self.assertEqual(7, systemic["schema_version"])
        self.assertEqual(1, systemic["unknown_evaluation_partition_count"])
        self.assertEqual(
            [0, 0, 0, 1],
            [
                row["pass"]
                for row in systemic["threshold_sensitivity"]["contamination_ratio"]
            ],
        )
        self.assertIn("Threshold sensitivity", build_systemic_markdown(systemic))

    def test_contract_path_records_automatic_contamination_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            proposed_path, proposed = self._write_proposed(root)
            fixture_path = root / "fixture-video.json"
            payload = {
                "video_id": "fixture-video",
                "expected_outcome": "sermon",
                "expected_spans": [
                    {"start_seconds": 100.0, "end_seconds": 300.0}
                ],
                "allowed_interruptions": [],
                "ground_truth_version": 1,
                "reviewed_by": "Reviewer",
            }
            fixture_path.write_text(json.dumps(payload), encoding="utf-8")
            trace = build_diagnostic_trace(
                proposed,
                proposed_path=proposed_path,
                youtube_video_id="fixture-video",
                fixture=validate_fixture_payload(payload, path=fixture_path),
            )

        path = trace["contract_paths"]["contamination"]
        self.assertEqual("selected", path["earliest_breach_stage"])
        self.assertIn("fine", path["recovery_stages"])
        self.assertEqual("pass", path["terminal_status"])
        self.assertFalse(path["terminal_failure"])
        self.assertEqual("recovered_automatically", trace["causal_path_status"])

    def test_contamination_attribution_separates_internal_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            proposed_path, proposed = self._write_proposed(root)
            proposed["classification"]["retained_segment_indexes"] = [0, 1, 2]
            proposed["sermon_window"].update(
                {"start_seconds": 0.0, "end_seconds": 300.0}
            )
            proposed_path.write_text(json.dumps(proposed), encoding="utf-8")
            payload = {
                "video_id": "fixture-video",
                "expected_outcome": "sermon",
                "expected_spans": [
                    {"start_seconds": 0.0, "end_seconds": 100.0},
                    {"start_seconds": 200.0, "end_seconds": 300.0},
                ],
                "allowed_interruptions": [],
                "ground_truth_version": 1,
                "reviewed_by": "Reviewer",
            }
            fixture_path = root / "fixture-video.json"
            fixture_path.write_text(json.dumps(payload), encoding="utf-8")
            trace = build_diagnostic_trace(
                proposed,
                proposed_path=proposed_path,
                youtube_video_id="fixture-video",
                fixture=validate_fixture_payload(payload, path=fixture_path),
            )

        attribution = trace["contamination_attribution"]
        self.assertEqual(
            100.0,
            attribution["final_contamination_seconds"][
                "internal_contamination_seconds"
            ],
        )
        self.assertEqual(
            ["internal_contamination"],
            attribution["material_final_contamination_patterns"],
        )

    def test_identity_edge_advisory_surfaces_temporal_boundary_feedback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            proposed_path, proposed = self._write_proposed(root)
            run = root / "shadow-run"
            run.mkdir()
            identity_payload = {
                "candidate": {"video_id": 7},
                "association_version": "speaker-association-v1",
                "model_fingerprint": "model-abc",
                "span_selection": {
                    "candidate_selection": {
                        "observation_start_seconds": 0.0,
                        "observation_end_seconds": 300.0,
                    }
                },
                "sermon_window_quality_flags": [
                    {
                        "flag": "speaker_inconsistent_edge",
                        "edge": "start",
                        "start_seconds": 0.0,
                        "end_seconds": 100.0,
                        "reason_codes": ["coherent_replacement_speaker"],
                        "automatic_boundary_change_allowed": False,
                    }
                ],
            }
            (run / "association.json").write_text(
                json.dumps(identity_payload), encoding="utf-8"
            )
            loaded = load_identity_boundary_feedback(root, database_video_ids={7})
            trace = build_diagnostic_trace(
                proposed,
                proposed_path=proposed_path,
                youtube_video_id="fixture-video",
                database_video_id=7,
                fixture=self._fixture(root),
                identity_boundary_feedback=loaded[7],
            )

        feedback = trace["identity_boundary_feedback"]
        self.assertEqual(1, feedback["event_count"])
        self.assertEqual(1, feedback["temporal_boundary_movement_count"])
        self.assertEqual(0, feedback["causal_adjustment_count"])
        self.assertEqual(
            "boundary_moved_inward_after_advisory",
            feedback["events"][0]["observed_effect"],
        )
        self.assertEqual(
            "temporal_only",
            feedback["events"][0]["reviewed_quality_impact"]["attribution"],
        )
        self.assertIn(
            "identity_boundary_adjustment_causality_not_persisted",
            {gap["code"] for gap in trace["diagnostic_gaps"]},
        )
        diagnostic_markdown = build_diagnostic_markdown(trace)
        self.assertIn("Identity edge evidence", diagnostic_markdown)
        self.assertIn("boundary advisory", diagnostic_markdown)
        systemic = aggregate_diagnostic_traces([trace])
        self.assertEqual(
            "temporal association only",
            systemic["identity_boundary_feedback_summary"]["causal_interpretation"],
        )
        self.assertIn("Identity boundary feedback", build_systemic_markdown(systemic))

    def test_identity_signal_unconsumed_requires_same_edge_overreach(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            proposed_path, proposed = self._write_proposed(root)
            proposed["sermon_window"].update(
                {"start_seconds": 0.0, "end_seconds": 300.0}
            )
            proposed_path.write_text(json.dumps(proposed), encoding="utf-8")
            fixture_payload = {
                "video_id": "fixture-video",
                "expected_outcome": "sermon",
                "expected_spans": [
                    {"start_seconds": 100.0, "end_seconds": 300.0}
                ],
                "allowed_interruptions": [],
                "ground_truth_version": 1,
                "reviewed_by": "Reviewer",
            }
            fixture_path = root / "fixture-video.json"
            fixture_path.write_text(json.dumps(fixture_payload), encoding="utf-8")
            trace = build_diagnostic_trace(
                proposed,
                proposed_path=proposed_path,
                youtube_video_id="fixture-video",
                fixture=validate_fixture_payload(
                    fixture_payload, path=fixture_path
                ),
                identity_boundary_feedback=[
                    {
                        "edge": "start",
                        "evidence_window": {
                            "start_seconds": 0.0,
                            "end_seconds": 300.0,
                        },
                        "causal_adjustment_persisted": False,
                    }
                ],
            )

        feedback = trace["identity_boundary_feedback"]
        self.assertEqual(1, feedback["unconsumed_same_edge_signal_count"])
        self.assertTrue(feedback["events"][0]["identity_signal_unconsumed"])
        self.assertEqual(
            100.0,
            feedback["events"][0]["reviewed_same_edge_overreach_seconds"],
        )
        self.assertIn(
            "identity_signal_unconsumed",
            {gap["code"] for gap in trace["diagnostic_gaps"]},
        )

    def test_systemic_comparison_marks_fixed_and_signature_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            proposed_path, proposed = self._write_proposed(root)
            trace = build_diagnostic_trace(
                proposed,
                proposed_path=proposed_path,
                youtube_video_id="fixture-video",
                fixture=self._fixture(root),
            )
        before = aggregate_diagnostic_traces([trace])
        fixed_trace = json.loads(json.dumps(trace))
        fixed_trace["overall_outcome"]["status"] = "pass"
        fixed_trace["earliest_observed_failure"] = None
        fixed_trace["stages"][-1]["measurements"]["reviewed_sermon_coverage"] = 1.0
        after = aggregate_diagnostic_traces([fixed_trace])
        comparison = compare_systemic_reports(before, after)
        self.assertEqual(1, comparison["change_counts"]["fixed"])
        self.assertEqual(3, comparison["schema_version"])
        self.assertIn("source_artifact_sha256", comparison["runs"][0]["before"])
        self.assertIn("fixture-video", build_comparison_markdown(comparison))

    def test_systemic_comparison_identifies_dimension_tradeoff(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            proposed_path, proposed = self._write_proposed(root)
            trace = build_diagnostic_trace(
                proposed,
                proposed_path=proposed_path,
                youtube_video_id="fixture-video",
                fixture=self._fixture(root),
            )
        changed = json.loads(json.dumps(trace))
        changed["outcome_contracts"]["localization"]["status"] = "pass"
        changed["outcome_contracts"]["contamination"]["status"] = "fail"
        comparison = compare_systemic_reports(
            aggregate_diagnostic_traces([trace]),
            aggregate_diagnostic_traces([changed]),
        )

        run = comparison["runs"][0]
        self.assertEqual("tradeoff", run["change"])
        self.assertEqual(["contract:localization"], run["improved_components"])
        self.assertEqual(["contract:contamination"], run["regressed_components"])

    def test_comparison_labels_whole_file_only_change_as_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            proposed_path, proposed = self._write_proposed(root)
            trace = build_diagnostic_trace(
                proposed,
                proposed_path=proposed_path,
                youtube_video_id="fixture-video",
                fixture=self._fixture(root),
            )
        rewritten = json.loads(json.dumps(trace))
        rewritten["source_artifact"]["sha256"] = "different-whole-file-hash"
        comparison = compare_systemic_reports(
            aggregate_diagnostic_traces([trace]),
            aggregate_diagnostic_traces([rewritten]),
        )

        run = comparison["runs"][0]
        self.assertEqual("unchanged", run["change"])
        self.assertEqual(["metadata_only"], run["change_reasons"])
        self.assertEqual([], run["changed_artifact_components"])

    def test_comparison_attributes_final_range_component_change(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            proposed_path, proposed = self._write_proposed(root)
            trace = build_diagnostic_trace(
                proposed,
                proposed_path=proposed_path,
                youtube_video_id="fixture-video",
                fixture=self._fixture(root),
            )
        changed = json.loads(json.dumps(trace))
        final = next(stage for stage in changed["stages"] if stage["key"] == "final")
        final["output_ranges"] = [
            {"start_seconds": 100.0, "end_seconds": 299.0}
        ]
        changed.pop("component_fingerprints")
        comparison = compare_systemic_reports(
            aggregate_diagnostic_traces([trace]),
            aggregate_diagnostic_traces([changed]),
        )

        run = comparison["runs"][0]
        self.assertEqual("changed", run["change"])
        self.assertIn(
            "arbitration_final_window", run["changed_artifact_components"]
        )
        self.assertIn("boundary_behavior_changed", run["change_reasons"])

    def test_schema_upgrade_ignores_derived_regret_and_identity_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            proposed_path, proposed = self._write_proposed(root)
            trace = build_diagnostic_trace(
                proposed,
                proposed_path=proposed_path,
                youtube_video_id="fixture-video",
                fixture=self._fixture(root),
            )
        before_trace = json.loads(json.dumps(trace))
        after_trace = json.loads(json.dumps(trace))
        before_trace["schema_version"] = 5
        before_trace["stage_regret"]["arbitration"]["classification"] = (
            "minor_tradeoff"
        )
        raw_identity = {
            "source": "speaker_profile_shadow_association",
            "edge": "start",
            "evidence_window": {
                "start_seconds": 0.0,
                "end_seconds": 300.0,
            },
            "relationship": "speaker_inconsistent_edge",
            "decision": "boundary_advisory_only",
            "reason_codes": ["distributed_clip_inconsistent"],
            "causal_adjustment_persisted": False,
        }
        before_trace["identity_boundary_feedback"] = {
            "events": [{**raw_identity, "observed_effect": "advisory_no_boundary_change"}]
        }
        after_trace["identity_boundary_feedback"] = {
            "events": [
                {
                    **raw_identity,
                    "observed_effect": "advisory_no_boundary_change",
                    "identity_signal_unconsumed": True,
                    "reviewed_same_edge_overreach_seconds": 100.0,
                }
            ]
        }
        before_trace.pop("component_fingerprints")
        after_trace.pop("component_fingerprints")
        comparison = compare_systemic_reports(
            aggregate_diagnostic_traces([before_trace]),
            aggregate_diagnostic_traces([after_trace]),
        )

        run = comparison["runs"][0]
        self.assertEqual("unchanged", run["change"])
        self.assertEqual(["diagnostic_schema_only"], run["change_reasons"])
        self.assertEqual([], run["improved_components"])
        self.assertEqual([], run["changed_artifact_components"])


if __name__ == "__main__":
    unittest.main()
