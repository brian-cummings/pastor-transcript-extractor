from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from pastor_transcript_extractor.speaker_profile_discovery import (
    TRANSCRIPT_GROUNDED_SPAN_SELECTION_VERSION,
)
from pastor_transcript_extractor.speaker_shadow_association import (
    ProfileAssociationReadiness,
    ShadowExemplar,
    StagedAssociationRouting,
    should_activate_cross_source_fallback,
)
from pastor_transcript_extractor.workflows.identity.association import (
    AssociationProfileRoutePlan,
)


AssociationProfiles = tuple[
    tuple[ProfileAssociationReadiness, Sequence[ShadowExemplar]], ...
]


@dataclass(frozen=True, slots=True)
class AssociationEvaluationPass:
    profiles: AssociationProfiles
    routing_payload: Mapping[str, Any]
    additional_profile_comparisons: int


def build_span_selection_payload(
    candidate_observation_id: int,
    profiles: Sequence[
        tuple[ProfileAssociationReadiness, Sequence[ShadowExemplar]]
    ],
    *,
    selections_by_observation_id: Mapping[int, Mapping[str, Any]],
) -> dict[str, Any]:
    """Build the versioned span evidence included in an evaluation fingerprint."""
    return {
        "version": TRANSCRIPT_GROUNDED_SPAN_SELECTION_VERSION,
        "required_label": "sermon",
        "span_count": 5,
        "duration_seconds": 12.0,
        "minimum_words": 8,
        "minimum_unique_words": 4,
        "candidate_multiplier": 3,
        "activity_qualified": True,
        "distributed_first": True,
        "within_observation_consistency_fallback": True,
        "candidate_selection": selections_by_observation_id.get(
            candidate_observation_id
        ),
        "exemplar_selections": {
            str(exemplar.observation.id): selections_by_observation_id.get(
                exemplar.observation.id
            )
            for _profile, exemplars in profiles
            for exemplar in exemplars
        },
    }


def plan_cross_source_fallback(
    report: Mapping[str, Any],
    routing: StagedAssociationRouting,
    candidate_profiles: AssociationProfiles,
    initial_routing_payload: Mapping[str, Any],
) -> AssociationEvaluationPass | None:
    """Plan the bounded cross-source pass after a weak local outcome."""
    if not should_activate_cross_source_fallback(
        str(report["outcome"]), routing
    ):
        return None
    fallback_profiles = tuple(
        (*candidate_profiles, *routing.fallback_profiles)
    )
    fallback_profile_ids = [
        profile.profile_id
        for profile, _exemplars in routing.fallback_profiles
    ]
    initial_candidate_funnel = dict(
        initial_routing_payload.get("candidate_funnel") or {}
    )
    activated_retrieval_candidates = [
        {
            **entry,
            "routing_policy_eligible": True,
            "selected_for_comparison": True,
            "passed_shortlist_cutoff": True,
            "weak_local_fallback_activated": True,
        }
        if isinstance(entry, Mapping)
        and entry.get("profile_id") in fallback_profile_ids
        else entry
        for entry in initial_candidate_funnel.get("retrieval_candidates", [])
    ]
    payload = {
        **initial_routing_payload,
        "route": "source_local_then_bounded_cross_source_fallback",
        "initial_local_outcome": report["outcome"],
        "weak_local_fallback_activated": True,
        "fallback_profile_ids": fallback_profile_ids,
        "profiles_actually_compared": sorted(
            profile.profile_id
            for profile, _exemplars in fallback_profiles
        ),
        "candidate_funnel": {
            **initial_candidate_funnel,
            "retrieval_candidates": activated_retrieval_candidates,
            "weak_local_fallback_activated": True,
            "initial_local_outcome": report["outcome"],
            "profiles_actually_compared": sorted(
                profile.profile_id
                for profile, _exemplars in fallback_profiles
            ),
        },
    }
    return AssociationEvaluationPass(
        profiles=fallback_profiles,
        routing_payload=payload,
        additional_profile_comparisons=len(routing.fallback_profiles),
    )


def plan_exhaustive_validation(
    report: Mapping[str, Any],
    route_plan: AssociationProfileRoutePlan,
    *,
    pending_confirmation_profile_ids: frozenset[int],
    maximum_global_profiles: int,
) -> AssociationEvaluationPass | None:
    """Plan exhaustive validation after a shortlisted proposed match."""
    routing = route_plan.routing
    if report["outcome"] != "proposed_match" or routing.exhaustive:
        return None
    proposed_profile_id = report.get("proposed_profile_id")
    is_pending_confirmation = (
        proposed_profile_id in pending_confirmation_profile_ids
    )
    profiles = (
        route_plan.candidate_usable_profiles
        if is_pending_confirmation
        else route_plan.legacy_routed_profiles
    )
    initial_candidate_funnel = dict(
        route_plan.routing_payload.get("candidate_funnel") or {}
    )
    payload: dict[str, Any] = {
        "route": (
            "exhaustive_pending_discovery_confirmation_validation"
            if is_pending_confirmation
            else "exhaustive_validation_after_shortlist_proposal"
        ),
        "exhaustive": True,
        "priority_profile_ids": list(routing.priority_profile_ids),
        "shortlisted_profile_ids": list(routing.shortlisted_profile_ids),
        "total_routable_profiles": len(profiles),
        "maximum_global_profiles": maximum_global_profiles,
        "retrieval_evidence_only": False,
        "initial_shortlist_result": "proposed_match",
        "candidate_funnel": {
            **initial_candidate_funnel,
            "profiles_actually_compared": sorted(
                profile.profile_id for profile, _exemplars in profiles
            ),
            "exhaustive_validation_after_shortlist": True,
        },
    }
    if routing.confirmation_priority_profile_ids:
        payload["confirmation_priority_profile_ids"] = list(
            routing.confirmation_priority_profile_ids
        )
    return AssociationEvaluationPass(
        profiles=profiles,
        routing_payload=payload,
        additional_profile_comparisons=len(profiles),
    )
