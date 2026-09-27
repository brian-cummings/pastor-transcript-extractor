from __future__ import annotations

from types import SimpleNamespace
import unittest

from pastor_transcript_extractor.workflows.identity.association_evaluation import (
    build_span_selection_payload,
    plan_cross_source_fallback,
    plan_exhaustive_validation,
)


class IdentityAssociationEvaluationWorkflowTests(unittest.TestCase):
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
        self.assertEqual([8], planned.routing_payload[
            "confirmation_priority_profile_ids"
        ])
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


if __name__ == "__main__":
    unittest.main()
