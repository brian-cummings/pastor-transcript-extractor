from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from pastor_transcript_extractor.workflows.identity import association_evaluation
from pastor_transcript_extractor.workflows.identity.association_evaluation import (
    AssociationEvaluator,
    AssociationEvaluationPass,
    AssociationEvaluationResult,
    AssociationResultAccumulator,
    build_span_selection_payload,
    evaluate_association_candidate,
    plan_cross_source_fallback,
    plan_exhaustive_validation,
    persist_association_result,
)


class IdentityAssociationEvaluationWorkflowTests(unittest.TestCase):
    def evaluator(self, *, jobs: int = 1) -> AssociationEvaluator:
        return AssociationEvaluator(
            output_root=Path("output"),
            jobs=jobs,
            policy_spec=SimpleNamespace(),
            model_fingerprint="model-fingerprint",
            minimum_same_exemplars=2,
            selections_by_observation_id={11: {"candidate": True}},
            reviewed_difference_pairs=lambda: ((1, 2),),
            compare=Mock(),
        )

    def test_span_selection_payload_keeps_candidate_and_exemplar_evidence(
        self,
    ) -> None:
        profiles = (
            (
                SimpleNamespace(profile_id=8),
                (
                    SimpleNamespace(observation=SimpleNamespace(id=80)),
                    SimpleNamespace(observation=SimpleNamespace(id=81)),
                ),
            ),
        )

        payload = build_span_selection_payload(
            11,
            profiles,
            selections_by_observation_id={
                11: {"candidate": True},
                80: {"exemplar": 80},
            },
        )

        self.assertEqual({"candidate": True}, payload["candidate_selection"])
        self.assertEqual(
            {"80": {"exemplar": 80}, "81": None},
            payload["exemplar_selections"],
        )
        self.assertTrue(payload["activity_qualified"])

    def test_cross_source_fallback_activates_selected_retrieval_profile(
        self,
    ) -> None:
        local_profile = SimpleNamespace(profile_id=8)
        fallback_profile = SimpleNamespace(profile_id=9)
        local = ((local_profile, ()),)
        fallback = ((fallback_profile, ()),)
        routing = SimpleNamespace(fallback_profiles=fallback)
        initial_payload = {
            "route": "source_local",
            "candidate_funnel": {
                "retrieval_candidates": [
                    {"profile_id": 9, "selected_for_comparison": False},
                    {"profile_id": 10, "selected_for_comparison": False},
                ]
            },
        }

        planned = plan_cross_source_fallback(
            {"outcome": "no_match"},
            routing,
            local,
            initial_payload,
        )

        self.assertIsNotNone(planned)
        assert planned is not None
        self.assertEqual((*local, *fallback), planned.profiles)
        self.assertEqual(1, planned.additional_profile_comparisons)
        self.assertEqual(
            "source_local_then_bounded_cross_source_fallback",
            planned.routing_payload["route"],
        )
        candidates = planned.routing_payload["candidate_funnel"][
            "retrieval_candidates"
        ]
        self.assertTrue(candidates[0]["weak_local_fallback_activated"])
        self.assertFalse(candidates[1]["selected_for_comparison"])

    def test_cross_source_fallback_ignores_strong_local_outcome(self) -> None:
        routing = SimpleNamespace(fallback_profiles=((object(), ()),))
        self.assertIsNone(
            plan_cross_source_fallback(
                {"outcome": "proposed_match"},
                routing,
                (),
                {},
            )
        )

    def test_exhaustive_validation_uses_pending_confirmation_profiles(
        self,
    ) -> None:
        pending_profile = SimpleNamespace(profile_id=8)
        legacy_profile = SimpleNamespace(profile_id=9)
        routing = SimpleNamespace(
            exhaustive=False,
            priority_profile_ids=(8,),
            shortlisted_profile_ids=(8,),
            confirmation_priority_profile_ids=(8,),
        )
        route_plan = SimpleNamespace(
            routing=routing,
            routing_payload={
                "candidate_funnel": {"canonical_profile_ids": [8, 9]}
            },
            candidate_usable_profiles=((pending_profile, ()),),
            legacy_routed_profiles=((legacy_profile, ()),),
        )

        planned = plan_exhaustive_validation(
            {"outcome": "proposed_match", "proposed_profile_id": 8},
            route_plan,
            pending_confirmation_profile_ids=frozenset({8}),
            maximum_global_profiles=2,
        )

        self.assertIsNotNone(planned)
        assert planned is not None
        self.assertEqual(route_plan.candidate_usable_profiles, planned.profiles)
        self.assertEqual(
            "exhaustive_pending_discovery_confirmation_validation",
            planned.routing_payload["route"],
        )
        self.assertEqual(
            [8],
            planned.routing_payload["confirmation_priority_profile_ids"],
        )
        self.assertEqual(1, planned.additional_profile_comparisons)

    def test_exhaustive_validation_skips_abstention_or_exhaustive_route(
        self,
    ) -> None:
        route_plan = SimpleNamespace(
            routing=SimpleNamespace(exhaustive=False),
        )
        self.assertIsNone(
            plan_exhaustive_validation(
                {"outcome": "no_match"},
                route_plan,
                pending_confirmation_profile_ids=frozenset(),
                maximum_global_profiles=1,
            )
        )
        route_plan.routing.exhaustive = True
        self.assertIsNone(
            plan_exhaustive_validation(
                {"outcome": "proposed_match"},
                route_plan,
                pending_confirmation_profile_ids=frozenset(),
                maximum_global_profiles=1,
            )
        )

    def test_evaluator_returns_verified_reusable_artifact(self) -> None:
        candidate = SimpleNamespace(id=11, input_fingerprint="candidate")
        cached_report = {"outcome": "no_match"}
        with (
            patch.object(
                association_evaluation,
                "build_shadow_association_input_fingerprint",
                return_value="input-fingerprint",
            ) as fingerprint,
            patch.object(
                association_evaluation,
                "load_reusable_shadow_association",
                return_value=(Path("cached.json"), cached_report),
            ) as load_reusable,
            patch.object(
                association_evaluation,
                "evaluate_shadow_association",
            ) as evaluate,
        ):
            result = self.evaluator(jobs=2).evaluate(
                candidate=candidate,
                candidate_audio_path=Path("candidate.wav"),
                candidate_audio_sha256="audio-sha",
                candidate_normalized_names=("pastor",),
                profiles=(),
                routing_payload={"route": "global"},
            )

        self.assertIs(cached_report, result.report)
        self.assertEqual(Path("cached.json"), result.reusable_path)
        self.assertEqual(
            {"candidate": True},
            fingerprint.call_args.kwargs["span_selection"][
                "candidate_selection"
            ],
        )
        load_reusable.assert_called_once_with(
            Path("output"),
            candidate_fingerprint="candidate",
            input_fingerprint="input-fingerprint",
        )
        evaluate.assert_not_called()

    def test_evaluator_reuses_executor_and_closes_it(self) -> None:
        candidate = SimpleNamespace(id=11, input_fingerprint="candidate")
        executor = Mock()
        with (
            patch.object(
                association_evaluation,
                "build_shadow_association_input_fingerprint",
                return_value="input-fingerprint",
            ),
            patch.object(
                association_evaluation,
                "load_reusable_shadow_association",
                return_value=None,
            ),
            patch.object(
                association_evaluation,
                "evaluate_shadow_association",
                return_value={"outcome": "no_match"},
            ) as evaluate,
            patch.object(
                association_evaluation,
                "ThreadPoolExecutor",
                return_value=executor,
            ) as executor_type,
        ):
            evaluator = self.evaluator(jobs=3)
            result = evaluator.evaluate(
                candidate=candidate,
                candidate_audio_path=Path("candidate.wav"),
                candidate_audio_sha256="audio-sha",
                candidate_normalized_names=(),
                profiles=(),
                routing_payload={},
            )
            evaluator.close()

        self.assertIsNone(result.reusable_path)
        executor_type.assert_called_once_with(
            max_workers=3,
            thread_name_prefix="identity-association",
        )
        self.assertIs(executor, evaluate.call_args.kwargs["executor"])
        executor.shutdown.assert_called_once_with(
            wait=True,
            cancel_futures=False,
        )

    def test_evaluator_cancels_executor_after_failure(self) -> None:
        candidate = SimpleNamespace(id=11, input_fingerprint="candidate")
        executor = Mock()
        with (
            patch.object(
                association_evaluation,
                "build_shadow_association_input_fingerprint",
                return_value="input-fingerprint",
            ),
            patch.object(
                association_evaluation,
                "load_reusable_shadow_association",
                return_value=None,
            ),
            patch.object(
                association_evaluation,
                "evaluate_shadow_association",
                side_effect=RuntimeError("comparison failed"),
            ),
            patch.object(
                association_evaluation,
                "ThreadPoolExecutor",
                return_value=executor,
            ),
        ):
            evaluator = self.evaluator(jobs=2)
            with self.assertRaisesRegex(RuntimeError, "comparison failed"):
                evaluator.evaluate(
                    candidate=candidate,
                    candidate_audio_path=Path("candidate.wav"),
                    candidate_audio_sha256="audio-sha",
                    candidate_normalized_names=(),
                    profiles=(),
                    routing_payload={},
                )

        executor.shutdown.assert_called_once_with(
            wait=True,
            cancel_futures=True,
        )

    def test_persisted_result_reuses_artifact_and_mirrors_boundary(self) -> None:
        report = {
            "outcome": "proposed_match",
            "proposed_profile_id": 8,
            "routing": {"route": "global_shortlist"},
            "sermon_window_quality_flags": ({"flag": "quality"},),
        }
        database = SimpleNamespace(
            get_latest_extraction_result_for_video=lambda _id: SimpleNamespace(
                proposed_json_path="proposed.json"
            )
        )
        with (
            patch.object(
                association_evaluation,
                "write_shadow_association",
            ) as write,
            patch.object(
                association_evaluation,
                "persist_association_boundary_evidence",
            ) as persist_boundary,
        ):
            result = persist_association_result(
                database,
                output_root=Path("output"),
                observation=SimpleNamespace(video_id=7),
                report=report,
                reusable_path=Path("cached.json"),
            )

        write.assert_not_called()
        persist_boundary.assert_called_once_with("proposed.json", report)
        self.assertTrue(result.reused)
        self.assertEqual(Path("cached.json"), result.destination)
        self.assertEqual("global_shortlist", result.routing_route)

    def test_result_accumulator_counts_outcomes_and_proposals(self) -> None:
        database = SimpleNamespace(
            get_latest_extraction_result_for_video=lambda _id: None
        )
        report = {
            "outcome": "proposed_match",
            "proposed_profile_id": 8,
            "routing": {"route": "global_shortlist"},
            "sermon_window_quality_flags": (
                {"flag": "one"},
                {"flag": "two"},
            ),
        }
        with patch.object(
            association_evaluation,
            "write_shadow_association",
            return_value=Path("written.json"),
        ):
            result = persist_association_result(
                database,
                output_root=Path("output"),
                observation=SimpleNamespace(video_id=7),
                report=report,
                reusable_path=None,
            )
        accumulator = AssociationResultAccumulator()
        accumulator.record(result)

        self.assertEqual({"proposed_match": 1}, accumulator.outcome_counts)
        self.assertEqual({"global_shortlist": 1}, accumulator.routing_counts)
        self.assertEqual({8: 1}, accumulator.proposal_targets)
        self.assertEqual(0, accumulator.reused_associations)
        self.assertEqual(2, accumulator.sermon_window_quality_flag_count)
        self.assertEqual([Path("written.json")], accumulator.written_reports)

    def test_candidate_evaluation_returns_isolated_initial_failure(self) -> None:
        evaluator = Mock()
        evaluator.evaluate.side_effect = OSError("unavailable")
        route_plan = SimpleNamespace(
            routing=SimpleNamespace(profiles=((object(), ()),)),
            routing_payload={"route": "local"},
        )

        outcome = evaluate_association_candidate(
            evaluator,
            SimpleNamespace(),
            output_root=Path("output"),
            candidate=SimpleNamespace(id=11),
            candidate_audio_path=Path("candidate.wav"),
            candidate_audio_sha256="audio-sha",
            candidate_normalized_names=(),
            route_plan=route_plan,
            pending_confirmation_profile_ids=frozenset(),
            maximum_global_profiles=1,
        )

        self.assertFalse(outcome.succeeded)
        self.assertEqual("initial", outcome.failure_stage)
        self.assertEqual(
            "association_evaluation_failed:OSError",
            outcome.admission_reason_code,
        )
        self.assertEqual(0, outcome.detailed_profile_comparisons)

    def test_candidate_evaluation_accounts_before_fallback_failure(self) -> None:
        evaluator = Mock()
        evaluator.evaluate.side_effect = (
            AssociationEvaluationResult({"outcome": "no_match"}, None),
            ValueError("fallback failed"),
        )
        route_plan = SimpleNamespace(
            routing=SimpleNamespace(profiles=((object(), ()),)),
            routing_payload={"route": "local"},
        )
        fallback_pass = AssociationEvaluationPass(
            profiles=((object(), ()), (object(), ())),
            routing_payload={"route": "fallback"},
            additional_profile_comparisons=1,
        )
        with patch.object(
            association_evaluation,
            "plan_cross_source_fallback",
            return_value=fallback_pass,
        ):
            outcome = evaluate_association_candidate(
                evaluator,
                SimpleNamespace(),
                output_root=Path("output"),
                candidate=SimpleNamespace(id=11),
                candidate_audio_path=Path("candidate.wav"),
                candidate_audio_sha256="audio-sha",
                candidate_normalized_names=(),
                route_plan=route_plan,
                pending_confirmation_profile_ids=frozenset(),
                maximum_global_profiles=1,
            )

        self.assertEqual("cross_source_fallback", outcome.failure_stage)
        self.assertEqual(
            "association_cross_source_fallback_failed:ValueError",
            outcome.admission_reason_code,
        )
        self.assertEqual(1, outcome.detailed_profile_comparisons)

    def test_candidate_evaluation_persists_final_exhaustive_result(self) -> None:
        evaluator = Mock()
        evaluator.evaluate.side_effect = (
            AssociationEvaluationResult(
                {"outcome": "proposed_match", "proposed_profile_id": 8},
                None,
            ),
            AssociationEvaluationResult({"outcome": "no_match"}, None),
        )
        route_plan = SimpleNamespace(
            routing=SimpleNamespace(profiles=((object(), ()),)),
            routing_payload={"route": "shortlist"},
        )
        exhaustive_pass = AssociationEvaluationPass(
            profiles=((object(), ()), (object(), ())),
            routing_payload={"route": "exhaustive"},
            additional_profile_comparisons=2,
        )
        persisted = SimpleNamespace(outcome="no_match")
        with (
            patch.object(
                association_evaluation,
                "plan_cross_source_fallback",
                return_value=None,
            ),
            patch.object(
                association_evaluation,
                "plan_exhaustive_validation",
                return_value=exhaustive_pass,
            ),
            patch.object(
                association_evaluation,
                "persist_association_result",
                return_value=persisted,
            ) as persist,
        ):
            outcome = evaluate_association_candidate(
                evaluator,
                SimpleNamespace(),
                output_root=Path("output"),
                candidate=SimpleNamespace(id=11),
                candidate_audio_path=Path("candidate.wav"),
                candidate_audio_sha256="audio-sha",
                candidate_normalized_names=(),
                route_plan=route_plan,
                pending_confirmation_profile_ids=frozenset(),
                maximum_global_profiles=1,
            )

        self.assertTrue(outcome.succeeded)
        self.assertIs(persisted, outcome.result)
        self.assertEqual(3, outcome.detailed_profile_comparisons)
        self.assertEqual(
            {"outcome": "no_match"}, persist.call_args.kwargs["report"]
        )


if __name__ == "__main__":
    unittest.main()
