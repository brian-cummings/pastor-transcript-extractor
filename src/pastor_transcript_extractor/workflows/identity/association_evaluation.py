from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from pastor_transcript_extractor.models import SpeakerObservation
from pastor_transcript_extractor.identity_boundary_review import (
    persist_association_boundary_evidence,
)
from pastor_transcript_extractor.speaker_profile_discovery import (
    TRANSCRIPT_GROUNDED_SPAN_SELECTION_VERSION,
)
from pastor_transcript_extractor.speaker_shadow_association import (
    ProfileAssociationReadiness,
    ShadowPolicySpec,
    ShadowExemplar,
    StagedAssociationRouting,
    build_shadow_association_input_fingerprint,
    evaluate_shadow_association,
    load_reusable_shadow_association,
    should_activate_cross_source_fallback,
    write_shadow_association,
)
from pastor_transcript_extractor.storage import Database
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


@dataclass(frozen=True, slots=True)
class AssociationEvaluationResult:
    report: Mapping[str, Any]
    reusable_path: Path | None


@dataclass(frozen=True, slots=True)
class PersistedAssociationResult:
    report: Mapping[str, Any]
    destination: Path
    reused: bool
    outcome: str
    routing_route: str
    proposed_profile_id: Any
    sermon_window_quality_flags: tuple[Mapping[str, Any], ...]


@dataclass(slots=True)
class AssociationResultAccumulator:
    outcome_counts: dict[str, int] = field(default_factory=dict)
    routing_counts: dict[str, int] = field(default_factory=dict)
    proposal_targets: dict[int, int] = field(default_factory=dict)
    reused_associations: int = 0
    sermon_window_quality_flag_count: int = 0
    written_reports: list[Path] = field(default_factory=list)

    def record(self, result: PersistedAssociationResult) -> None:
        self.routing_counts[result.routing_route] = (
            self.routing_counts.get(result.routing_route, 0) + 1
        )
        self.outcome_counts[result.outcome] = (
            self.outcome_counts.get(result.outcome, 0) + 1
        )
        self.reused_associations += int(result.reused)
        self.sermon_window_quality_flag_count += len(
            result.sermon_window_quality_flags
        )
        self.written_reports.append(result.destination)
        if (
            result.outcome == "proposed_match"
            and isinstance(result.proposed_profile_id, int)
        ):
            self.proposal_targets[result.proposed_profile_id] = (
                self.proposal_targets.get(result.proposed_profile_id, 0) + 1
            )


@dataclass(frozen=True, slots=True)
class AssociationCandidateEvaluationOutcome:
    result: PersistedAssociationResult | None
    detailed_profile_comparisons: int
    failure: Exception | None = None
    failure_stage: str | None = None
    admission_reason_code: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.result is not None


class AssociationEvaluator:
    """Evaluate candidates with verified cache reuse and one shared executor."""

    def __init__(
        self,
        *,
        output_root: Path,
        jobs: int,
        policy_spec: ShadowPolicySpec,
        model_fingerprint: str,
        minimum_same_exemplars: int,
        selections_by_observation_id: Mapping[int, Mapping[str, Any]],
        reviewed_difference_pairs: Callable[
            [], Sequence[tuple[int, int]]
        ],
        compare: Callable[..., Mapping[str, Any]],
    ) -> None:
        self._output_root = output_root
        self._jobs = jobs
        self._policy_spec = policy_spec
        self._model_fingerprint = model_fingerprint
        self._minimum_same_exemplars = minimum_same_exemplars
        self._selections_by_observation_id = selections_by_observation_id
        self._reviewed_difference_pairs = reviewed_difference_pairs
        self._compare = compare
        self._executor: ThreadPoolExecutor | None = None

    def evaluate(
        self,
        *,
        candidate: SpeakerObservation,
        candidate_audio_path: Path,
        candidate_audio_sha256: str,
        candidate_normalized_names: Sequence[str],
        profiles: AssociationProfiles,
        routing_payload: Mapping[str, Any],
    ) -> AssociationEvaluationResult:
        span_selection = build_span_selection_payload(
            candidate.id,
            profiles,
            selections_by_observation_id=(
                self._selections_by_observation_id
            ),
        )
        input_fingerprint = build_shadow_association_input_fingerprint(
            candidate=candidate,
            candidate_audio_sha256=candidate_audio_sha256,
            candidate_normalized_names=candidate_normalized_names,
            profiles=profiles,
            policy_spec=self._policy_spec,
            model_fingerprint=self._model_fingerprint,
            minimum_same_exemplars=self._minimum_same_exemplars,
            reviewed_difference_pairs=self._reviewed_difference_pairs(),
            routing=routing_payload,
            span_selection=span_selection,
        )
        reusable = load_reusable_shadow_association(
            self._output_root,
            candidate_fingerprint=candidate.input_fingerprint,
            input_fingerprint=input_fingerprint,
        )
        if reusable is not None:
            return AssociationEvaluationResult(reusable[1], reusable[0])
        if self._jobs > 1 and self._executor is None:
            self._executor = ThreadPoolExecutor(
                max_workers=self._jobs,
                thread_name_prefix="identity-association",
            )
        try:
            report = evaluate_shadow_association(
                candidate=candidate,
                candidate_audio_path=candidate_audio_path,
                candidate_audio_sha256=candidate_audio_sha256,
                candidate_normalized_names=candidate_normalized_names,
                profiles=profiles,
                compare=self._compare,
                policy_spec=self._policy_spec,
                model_fingerprint=self._model_fingerprint,
                minimum_same_exemplars=self._minimum_same_exemplars,
                reviewed_difference_pairs=self._reviewed_difference_pairs(),
                routing=routing_payload,
                span_selection=span_selection,
                jobs=self._jobs,
                executor=self._executor,
            )
        except BaseException:
            self.close(cancel_futures=True)
            raise
        return AssociationEvaluationResult(report, None)

    def close(self, *, cancel_futures: bool = False) -> None:
        if self._executor is None:
            return
        self._executor.shutdown(
            wait=True,
            cancel_futures=cancel_futures,
        )
        self._executor = None


def persist_association_result(
    database: Database,
    *,
    output_root: Path,
    observation: SpeakerObservation,
    report: Mapping[str, Any],
    reusable_path: Path | None,
) -> PersistedAssociationResult:
    """Persist one result and mirror its evidence onto extraction output."""
    destination = reusable_path or write_shadow_association(output_root, report)
    extraction = database.get_latest_extraction_result_for_video(
        observation.video_id
    )
    if extraction is not None and extraction.proposed_json_path:
        persist_association_boundary_evidence(
            extraction.proposed_json_path,
            report,
        )
    proposed_profile_id = report.get("proposed_profile_id")
    window_flags = report["sermon_window_quality_flags"]
    return PersistedAssociationResult(
        report=report,
        destination=destination,
        reused=reusable_path is not None,
        outcome=str(report["outcome"]),
        routing_route=str(report["routing"]["route"]),
        proposed_profile_id=proposed_profile_id,
        sermon_window_quality_flags=tuple(window_flags),
    )


def evaluate_association_candidate(
    evaluator: AssociationEvaluator,
    database: Database,
    *,
    output_root: Path,
    candidate: SpeakerObservation,
    candidate_audio_path: Path,
    candidate_audio_sha256: str,
    candidate_normalized_names: Sequence[str],
    route_plan: AssociationProfileRoutePlan,
    pending_confirmation_profile_ids: frozenset[int],
    maximum_global_profiles: int,
) -> AssociationCandidateEvaluationOutcome:
    """Run one candidate's staged evaluation and persist its final report."""
    profiles = route_plan.routing.profiles
    detailed_profile_comparisons = 0
    try:
        evaluation = evaluator.evaluate(
            candidate=candidate,
            candidate_audio_path=candidate_audio_path,
            candidate_audio_sha256=candidate_audio_sha256,
            candidate_normalized_names=candidate_normalized_names,
            profiles=profiles,
            routing_payload=route_plan.routing_payload,
        )
    except (OSError, RuntimeError, ValueError) as error:
        return AssociationCandidateEvaluationOutcome(
            result=None,
            detailed_profile_comparisons=0,
            failure=error,
            failure_stage="initial",
            admission_reason_code=(
                f"association_evaluation_failed:{type(error).__name__}"
            ),
        )
    if evaluation.reusable_path is None:
        detailed_profile_comparisons += len(profiles)

    fallback_pass = plan_cross_source_fallback(
        evaluation.report,
        route_plan.routing,
        profiles,
        route_plan.routing_payload,
    )
    if fallback_pass is not None:
        try:
            evaluation = evaluator.evaluate(
                candidate=candidate,
                candidate_audio_path=candidate_audio_path,
                candidate_audio_sha256=candidate_audio_sha256,
                candidate_normalized_names=candidate_normalized_names,
                profiles=fallback_pass.profiles,
                routing_payload=fallback_pass.routing_payload,
            )
        except (OSError, RuntimeError, ValueError) as error:
            return AssociationCandidateEvaluationOutcome(
                result=None,
                detailed_profile_comparisons=detailed_profile_comparisons,
                failure=error,
                failure_stage="cross_source_fallback",
                admission_reason_code=(
                    "association_cross_source_fallback_failed:"
                    f"{type(error).__name__}"
                ),
            )
        if evaluation.reusable_path is None:
            detailed_profile_comparisons += (
                fallback_pass.additional_profile_comparisons
            )

    exhaustive_pass = plan_exhaustive_validation(
        evaluation.report,
        route_plan,
        pending_confirmation_profile_ids=(
            pending_confirmation_profile_ids
        ),
        maximum_global_profiles=maximum_global_profiles,
    )
    if exhaustive_pass is not None:
        evaluation = evaluator.evaluate(
            candidate=candidate,
            candidate_audio_path=candidate_audio_path,
            candidate_audio_sha256=candidate_audio_sha256,
            candidate_normalized_names=candidate_normalized_names,
            profiles=exhaustive_pass.profiles,
            routing_payload=exhaustive_pass.routing_payload,
        )
        if evaluation.reusable_path is None:
            detailed_profile_comparisons += (
                exhaustive_pass.additional_profile_comparisons
            )

    persisted = persist_association_result(
        database,
        output_root=output_root,
        observation=candidate,
        report=evaluation.report,
        reusable_path=evaluation.reusable_path,
    )
    return AssociationCandidateEvaluationOutcome(
        result=persisted,
        detailed_profile_comparisons=detailed_profile_comparisons,
    )


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
