from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from pastor_transcript_extractor.workflows.identity import association_evaluation
from pastor_transcript_extractor.workflows.identity.association_evaluation import (
    AssociationEvaluator,
    build_span_selection_payload,
    plan_cross_source_fallback,
    plan_exhaustive_validation,
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


if __name__ == "__main__":
    unittest.main()
