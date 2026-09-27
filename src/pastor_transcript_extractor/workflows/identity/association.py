from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from pastor_transcript_extractor.identity_leverage import (
    profile_neighborhood_video_ids,
)
from pastor_transcript_extractor.identity_attribution import (
    title_byline_selection_hint,
)
from pastor_transcript_extractor.media_artifacts import MediaVerificationCache
from pastor_transcript_extractor.models import SpeakerObservation, Video
from pastor_transcript_extractor.pipeline_diagnostics import (
    load_identity_association_attempts,
)
from pastor_transcript_extractor.speaker_pair_diagnostics import SpanSpec
from pastor_transcript_extractor.speaker_shadow_association import (
    ProfileAssociationReadiness,
    ShadowExemplar,
    StagedAssociationRouting,
    leave_one_out_profile_readiness,
    select_profile_exemplars,
    select_routed_association_profiles,
    select_staged_association_profiles,
)
from pastor_transcript_extractor.storage import Database
from pastor_transcript_extractor.speaker_pair_eligibility import (
    AutomaticSpeakerObservationEligibility,
    assess_automatic_speaker_observation,
)


@dataclass(frozen=True, slots=True)
class ShadowAssociationRequest:
    """Complete public input for one shadow-association operation."""

    youtube_video_id: str | None
    all_eligible: bool
    unattempted_only: bool
    neighborhood_profile_ids: tuple[int, ...]
    include_profiled: bool
    limit: int | None
    plan_only: bool
    minimum_profile_members: int
    maximum_exemplars: int
    minimum_same_exemplars: int
    maximum_global_profiles: int
    jobs: int
    model_path: Path
    model_sha256: str
    policy_path: Path
    evaluation_root: Path
    cache_dir: Path
    output_root: Path
    base_dir: Path | None


@dataclass(frozen=True, slots=True)
class AssociationScopeResult:
    """Resolved candidate-video scope and persisted-attempt exclusions."""

    videos: tuple[Video, ...]
    attempted_observation_fingerprints: frozenset[str]
    database_video_count: int
    observed_video_count: int
    inventory_reported: bool


@dataclass(frozen=True, slots=True)
class AssociationCandidateAssessment:
    """One video's terminal eligibility or span-preparation admission."""

    video: Video
    eligibility: AutomaticSpeakerObservationEligibility | None
    audio_path: Path | None
    exclusion_reason: str | None
    admission_observation: SpeakerObservation | None
    admission_stage: str | None
    admission_media_sha256: str | None = None

    @property
    def admitted(self) -> bool:
        return self.exclusion_reason is None


@dataclass(frozen=True, slots=True)
class AssociationSpanInput:
    video: Video
    eligibility: AutomaticSpeakerObservationEligibility
    audio_path: Path


@dataclass(frozen=True, slots=True)
class PreparedAssociationCandidate:
    input: AssociationSpanInput
    span_specs: tuple[SpanSpec, ...]
    span_selection: Mapping[str, Any] | None


@dataclass(frozen=True, slots=True)
class AssociationSpanExclusion:
    input: AssociationSpanInput
    reason: str


@dataclass(frozen=True, slots=True)
class AssociationSpanPreparationResult:
    outcomes: tuple[
        PreparedAssociationCandidate | AssociationSpanExclusion, ...
    ]

    @property
    def candidates(self) -> tuple[PreparedAssociationCandidate, ...]:
        return tuple(
            outcome
            for outcome in self.outcomes
            if isinstance(outcome, PreparedAssociationCandidate)
        )

    @property
    def exclusions(self) -> tuple[AssociationSpanExclusion, ...]:
        return tuple(
            outcome
            for outcome in self.outcomes
            if isinstance(outcome, AssociationSpanExclusion)
        )


@dataclass(frozen=True, slots=True)
class AssociationProfileRoutePlan:
    """Candidate-specific profile selection and durable routing evidence."""

    routing: StagedAssociationRouting
    routing_payload: Mapping[str, Any]
    explicit_candidate_names: tuple[str, ...]
    exhaustive_profile_comparison_count: int
    candidate_usable_profiles: tuple[
        tuple[ProfileAssociationReadiness, Sequence[ShadowExemplar]], ...
    ]
    legacy_routed_profiles: tuple[
        tuple[ProfileAssociationReadiness, Sequence[ShadowExemplar]], ...
    ]


def validate_shadow_association_request(
    request: ShadowAssociationRequest,
) -> None:
    """Validate selection-mode invariants before any external access."""
    selection_modes = sum(
        (
            request.youtube_video_id is not None,
            request.all_eligible,
            bool(request.neighborhood_profile_ids),
        )
    )
    if selection_modes != 1:
        raise ValueError(
            "Pass exactly one of --youtube-video-id, --all-eligible, or "
            "--neighborhood-profile-id."
        )
    if request.unattempted_only and not request.all_eligible:
        raise ValueError("--unattempted-only requires --all-eligible.")
    if request.minimum_same_exemplars > request.maximum_exemplars:
        raise ValueError(
            "--minimum-same-exemplars cannot exceed --maximum-exemplars."
        )


def resolve_association_scope(
    request: ShadowAssociationRequest,
    *,
    database: Database,
    videos_by_id: Mapping[int, Video],
    current_observation_by_video_id: Mapping[int, SpeakerObservation],
) -> AssociationScopeResult:
    """Resolve one-video, neighborhood, or observed-corpus association scope."""
    inventory_reported = False
    if request.youtube_video_id is not None:
        video = database.get_video_by_youtube_id(request.youtube_video_id)
        if video is None:
            raise ValueError(
                f"Unknown YouTube video ID: {request.youtube_video_id}"
            )
        videos = (video,)
    elif request.neighborhood_profile_ids:
        video_ids = profile_neighborhood_video_ids(
            database,
            association_root=request.output_root,
            profile_ids=request.neighborhood_profile_ids,
        )
        videos = tuple(
            videos_by_id[video_id]
            for video_id in video_ids
            if video_id in videos_by_id
        )
        if not videos:
            raise ValueError(
                "No persisted affected neighborhood was found for the requested "
                "profile id(s)."
            )
    else:
        videos = tuple(
            video
            for video in videos_by_id.values()
            if video.id in current_observation_by_video_id
        )
        inventory_reported = True

    attempted: set[str] = set()
    if request.unattempted_only:
        persisted_attempts = load_identity_association_attempts(
            request.output_root,
            database_video_ids={video.id for video in videos},
        )
        attempted = {
            fingerprint
            for attempts in persisted_attempts.values()
            for attempt in attempts
            if isinstance(
                fingerprint := attempt.get("observation_fingerprint"), str
            )
        }
    return AssociationScopeResult(
        videos=videos,
        attempted_observation_fingerprints=frozenset(attempted),
        database_video_count=len(videos_by_id),
        observed_video_count=len(
            {
                video_id
                for video_id in videos_by_id
                if video_id in current_observation_by_video_id
            }
        ),
        inventory_reported=inventory_reported,
    )


def assess_association_candidate(
    database: Database,
    video: Video,
    *,
    unattempted_only: bool,
    attempted_observation_fingerprints: frozenset[str],
    include_profiled: bool,
    verification_cache: MediaVerificationCache,
) -> AssociationCandidateAssessment:
    """Apply metadata, membership, review, and verified-media admission gates."""
    latest_observation = (
        database.get_latest_speaker_observation_for_video(video.id)
        if unattempted_only
        else None
    )
    if (
        latest_observation is not None
        and latest_observation.input_fingerprint
        in attempted_observation_fingerprints
    ):
        return AssociationCandidateAssessment(
            video,
            None,
            None,
            "association_already_attempted",
            None,
            None,
        )

    eligibility = assess_automatic_speaker_observation(
        database,
        video.id,
        verification_cache=verification_cache,
        verify_media=False,
    )
    if not eligibility.eligible or eligibility.observation is None:
        return AssociationCandidateAssessment(
            video,
            eligibility,
            None,
            eligibility.reason_code,
            latest_observation,
            "metadata_eligibility",
        )
    observation = eligibility.observation
    media_sha256 = (
        eligibility.media_artifact.content_sha256
        if eligibility.media_artifact is not None
        else None
    )
    if (
        not include_profiled
        and database.list_effective_profile_ids_for_observation(observation.id)
    ):
        return AssociationCandidateAssessment(
            video,
            eligibility,
            None,
            "already_profiled",
            observation,
            "membership_filter",
            media_sha256,
        )
    review_action = database.get_effective_observation_review_action(observation.id)
    if review_action not in {None, "qualified_single_speaker"}:
        reason = f"reviewed_{review_action}"
        return AssociationCandidateAssessment(
            video,
            eligibility,
            None,
            reason,
            observation,
            "observation_review_filter",
            media_sha256,
        )

    verified = assess_automatic_speaker_observation(
        database,
        video.id,
        verification_cache=verification_cache,
        verify_media=True,
    )
    if not verified.eligible or verified.observation is None:
        return AssociationCandidateAssessment(
            video,
            verified,
            None,
            verified.reason_code,
            latest_observation,
            "verified_media_eligibility",
        )
    if verified.media_artifact is None:
        return AssociationCandidateAssessment(
            video,
            verified,
            None,
            "verified_normalized_media_unavailable",
            verified.observation,
            "verified_media_eligibility",
        )
    return AssociationCandidateAssessment(
        video,
        verified,
        Path(verified.media_artifact.artifact_path),
        None,
        None,
        None,
        verified.media_artifact.content_sha256,
    )


def prepare_association_candidate_spans(
    inputs: Sequence[AssociationSpanInput],
    *,
    jobs: int,
    target_count: int | None,
    prepare_spans: Callable[
        [AssociationSpanInput],
        tuple[tuple[SpanSpec, ...], Mapping[str, Any] | None],
    ],
    progress_callback: Callable[[int, int, int], None] | None = None,
) -> AssociationSpanPreparationResult:
    """Prepare spans concurrently in stable batches with an admission cap."""
    outcomes: list[PreparedAssociationCandidate | AssociationSpanExclusion] = []
    candidate_count = 0
    batch_size = max(1, jobs)

    def prepare(item: AssociationSpanInput):
        try:
            span_specs, span_selection = prepare_spans(item)
        except Exception as error:
            reason = str(error) or "activity_qualified_spans_unavailable"
            return item, (), None, reason
        if not span_specs:
            return item, (), None, "speech_grounded_spans_unavailable"
        return item, span_specs, span_selection, None

    with ThreadPoolExecutor(max_workers=jobs) as executor:
        for batch_start in range(0, len(inputs), batch_size):
            if target_count is not None and candidate_count >= target_count:
                break
            batch = inputs[batch_start : batch_start + batch_size]
            for item, span_specs, span_selection, reason in executor.map(
                prepare, batch
            ):
                if target_count is not None and candidate_count >= target_count:
                    break
                if reason is not None:
                    outcomes.append(AssociationSpanExclusion(item, reason))
                else:
                    outcomes.append(
                        PreparedAssociationCandidate(
                            item,
                            tuple(span_specs),
                            span_selection,
                        )
                    )
                    candidate_count += 1
            if progress_callback is not None:
                progress_callback(
                    min(batch_start + len(batch), len(inputs)),
                    len(inputs),
                    candidate_count,
                )
    return AssociationSpanPreparationResult(outcomes=tuple(outcomes))


def _profile_readiness_funnel_payload(
    profile_readiness: Sequence[ProfileAssociationReadiness],
    comparison_profiles: Sequence[
        tuple[ProfileAssociationReadiness, Sequence[ShadowExemplar]]
    ],
    *,
    eligible_exemplars: Sequence[ShadowExemplar],
    minimum_same_exemplars: int,
    leave_one_out_observation_id: int | None = None,
) -> dict[str, Any]:
    comparison_profile_ids = {
        profile.profile_id for profile, _exemplars in comparison_profiles
    }
    return {
        "canonical_profile_ids": sorted(
            profile.profile_id for profile in profile_readiness
        ),
        "review_ready_profile_ids": sorted(
            profile.profile_id
            for profile in profile_readiness
            if profile.review_ready
        ),
        "comparison_eligible_profile_ids": sorted(comparison_profile_ids),
        "leave_one_out_observation_id": leave_one_out_observation_id,
        "excluded_profiles": [
            {
                "profile_id": profile.profile_id,
                "stage": (
                    "profile_readiness"
                    if not profile.review_ready
                    else "acoustic_exemplar_availability"
                ),
                "reason_codes": (
                    list(profile.shadow_blockers)
                    if not profile.review_ready
                    else ["fewer_than_required_eligible_acoustic_exemplars"]
                ),
                "eligible_exemplar_count": sum(
                    exemplar.profile_id == profile.profile_id
                    and exemplar.observation.id != leave_one_out_observation_id
                    for exemplar in eligible_exemplars
                ),
                "required_exemplar_count": minimum_same_exemplars,
            }
            for profile in profile_readiness
            if profile.profile_id not in comparison_profile_ids
        ],
    }


def plan_association_profile_route(
    database: Database,
    *,
    video: Video,
    observation: SpeakerObservation,
    readiness: Sequence[ProfileAssociationReadiness],
    usable_profiles: Sequence[
        tuple[ProfileAssociationReadiness, Sequence[ShadowExemplar]]
    ],
    eligible_exemplars: Sequence[ShadowExemplar],
    videos_by_id: Mapping[int, Video],
    observations_by_id: Mapping[int, SpeakerObservation],
    source_id_by_video_id: Mapping[int, int],
    candidate_names_by_observation: Mapping[int, Sequence[str]],
    minimum_profile_members: int,
    maximum_exemplars: int,
    minimum_same_exemplars: int,
    maximum_global_profiles: int,
    candidate_centroid: Sequence[float],
    exemplar_centroids: Mapping[int, Sequence[float]],
    confirmation_profile_ids: frozenset[int] = frozenset(),
) -> AssociationProfileRoutePlan:
    """Plan one candidate's profile route without acoustic comparisons."""
    explicit_candidate_names = tuple(
        sorted(set(candidate_names_by_observation.get(observation.id, ())))
    )
    title_hint = title_byline_selection_hint(video.title)
    routing_names = set(explicit_candidate_names)
    if title_hint:
        routing_names.add(title_hint)
    effective_candidate_profile_ids = {
        database.resolve_speaker_profile_id(profile_id)
        for profile_id in database.list_effective_profile_ids_for_observation(
            observation.id
        )
    }
    leave_one_out_applied = bool(effective_candidate_profile_ids)
    if leave_one_out_applied:
        candidate_readiness = tuple(
            leave_one_out_profile_readiness(
                profile,
                candidate=observation,
                observations_by_id=observations_by_id,
                source_id_by_video_id=source_id_by_video_id,
                normalized_names_by_observation_id=(
                    candidate_names_by_observation
                ),
                minimum_members=minimum_profile_members,
            )
            for profile in readiness
        )
        candidate_usable_profiles: list[
            tuple[ProfileAssociationReadiness, Sequence[ShadowExemplar]]
        ] = []
        for profile in candidate_readiness:
            if not profile.review_ready:
                continue
            exemplars = select_profile_exemplars(
                profile,
                eligible_exemplars,
                videos_by_id=videos_by_id,
                maximum_exemplars=maximum_exemplars,
            )
            if len(exemplars) >= minimum_same_exemplars:
                candidate_usable_profiles.append((profile, exemplars))
        readiness_funnel = _profile_readiness_funnel_payload(
            candidate_readiness,
            candidate_usable_profiles,
            eligible_exemplars=eligible_exemplars,
            minimum_same_exemplars=minimum_same_exemplars,
            leave_one_out_observation_id=observation.id,
        )
    else:
        candidate_usable_profiles = list(usable_profiles)
        readiness_funnel = _profile_readiness_funnel_payload(
            readiness,
            candidate_usable_profiles,
            eligible_exemplars=eligible_exemplars,
            minimum_same_exemplars=minimum_same_exemplars,
        )

    legacy_routed_profiles = select_routed_association_profiles(
        candidate_usable_profiles,
        candidate_source_id=video.source_id,
        candidate_normalized_names=sorted(routing_names),
        source_id_by_video_id=source_id_by_video_id,
    )
    routing = select_staged_association_profiles(
        candidate_usable_profiles,
        candidate_source_id=video.source_id,
        candidate_normalized_names=sorted(routing_names),
        source_id_by_video_id=source_id_by_video_id,
        candidate_centroid=candidate_centroid,
        exemplar_centroids=exemplar_centroids,
        maximum_global_profiles=maximum_global_profiles,
        confirmation_priority_profile_ids=confirmation_profile_ids,
    )
    payload: dict[str, Any] = {
        "route": routing.route,
        "exhaustive": routing.exhaustive,
        "priority_profile_ids": list(routing.priority_profile_ids),
        "shortlisted_profile_ids": list(routing.shortlisted_profile_ids),
        "total_routable_profiles": routing.total_routable_profiles,
        "maximum_global_profiles": maximum_global_profiles,
        "retrieval_evidence_only": True,
        "candidate_funnel": {
            **dict(routing.candidate_funnel or {}),
            **readiness_funnel,
            "retrospective_evaluation": {
                "leave_one_out_applied": leave_one_out_applied,
                "hidden_effective_profile_ids": sorted(
                    effective_candidate_profile_ids
                ),
                "membership_used_as_routing_evidence": False,
            },
            "candidate_routing_inputs": {
                "source_id": video.source_id,
                "explicit_normalized_names": list(explicit_candidate_names),
                "title_byline_normalized_name": title_hint,
                "routing_normalized_names": sorted(routing_names),
            },
            "profiles_actually_compared": sorted(
                profile.profile_id
                for profile, _exemplars in routing.profiles
            ),
        },
    }
    if routing.confirmation_priority_profile_ids:
        payload["confirmation_priority_profile_ids"] = list(
            routing.confirmation_priority_profile_ids
        )
    return AssociationProfileRoutePlan(
        routing=routing,
        routing_payload=payload,
        explicit_candidate_names=explicit_candidate_names,
        exhaustive_profile_comparison_count=len(legacy_routed_profiles),
        candidate_usable_profiles=tuple(candidate_usable_profiles),
        legacy_routed_profiles=legacy_routed_profiles,
    )
