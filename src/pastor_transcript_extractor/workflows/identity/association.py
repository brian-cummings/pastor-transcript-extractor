from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from pastor_transcript_extractor.identity_leverage import (
    profile_neighborhood_video_ids,
)
from pastor_transcript_extractor.identity_attribution import (
    title_byline_selection_hint,
)
from pastor_transcript_extractor.media_artifacts import (
    MediaVerificationCache,
    media_artifact_availability,
)
from pastor_transcript_extractor.models import (
    ExtractionResult,
    MediaArchiveEntry,
    SpeakerObservation,
    Video,
)
from pastor_transcript_extractor.pipeline_diagnostics import (
    load_identity_association_attempts,
)
from pastor_transcript_extractor.speaker_shadow_association import (
    DISCOVERY_PROFILE_REASON,
    ProfileAssociationReadiness,
    ShadowExemplar,
    StagedAssociationRouting,
    leave_one_out_profile_readiness,
    plan_pending_discovery_confirmation_routes,
    select_profile_exemplars,
    select_routed_association_profiles,
    select_staged_association_profiles,
)
from pastor_transcript_extractor.storage import Database
from pastor_transcript_extractor.speaker_pair_eligibility import (
    AutomaticSpeakerObservationEligibility,
    assess_automatic_speaker_observation,
)
from pastor_transcript_extractor.workflows.identity.association_preparation import (
    AssociationCandidateCentroidOutcome,
    AssociationCentroidCandidateInput,
    AssociationCentroidPreparationResult,
    AssociationSpanExclusion,
    AssociationSpanInput,
    AssociationSpanPreparationResult,
    PreparedAssociationCandidate,
    prepare_association_candidate_spans,
    prepare_association_centroids,
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
class AssociationCorpusInventory:
    videos_by_id: Mapping[int, Video]
    observations_by_id: Mapping[int, SpeakerObservation]
    observations_by_video_id: Mapping[int, tuple[SpeakerObservation, ...]]
    current_observation_by_video_id: Mapping[int, SpeakerObservation]
    latest_extraction_by_video_id: Mapping[int, ExtractionResult]
    archive_entries_by_artifact_id: Mapping[int, MediaArchiveEntry]
    profiled_observation_ids: frozenset[int]
    review_actions_by_observation_id: Mapping[int, str]
    source_id_by_video_id: Mapping[int, int]
    candidate_names_by_observation: Mapping[int, frozenset[str]]


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
class AssociationCandidateScanResult:
    span_inputs: tuple[AssociationSpanInput, ...]
    exclusion_counts: Mapping[str, int]


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


@dataclass(frozen=True, slots=True)
class PendingConfirmationRoutePlan:
    profiles: tuple[
        tuple[ProfileAssociationReadiness, Sequence[ShadowExemplar]], ...
    ]
    routes: Mapping[int, tuple[int, ...]]
    pending_profile_ids: frozenset[int]
    routed_profile_ids: frozenset[int]

    @property
    def route_count(self) -> int:
        return sum(len(profile_ids) for profile_ids in self.routes.values())


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


def load_association_corpus_inventory(
    database: Database,
) -> AssociationCorpusInventory:
    """Load stable lookup maps and explicit routing-name evidence."""
    videos_by_id = {video.id: video for video in database.list_videos()}
    observations_by_id = {
        observation.id: observation
        for observation in database.list_speaker_observations()
    }
    current_observation_by_video_id: dict[int, SpeakerObservation] = {}
    observations_by_video_id: dict[int, list[SpeakerObservation]] = {}
    for observation in observations_by_id.values():
        observations_by_video_id.setdefault(observation.video_id, []).append(
            observation
        )
        current = current_observation_by_video_id.get(observation.video_id)
        if current is None or observation.id > current.id:
            current_observation_by_video_id[observation.video_id] = observation
    latest_extraction_by_video_id: dict[int, ExtractionResult] = {}
    for extraction in database.list_extraction_results():
        current = latest_extraction_by_video_id.get(extraction.video_id)
        if current is None or extraction.id > current.id:
            latest_extraction_by_video_id[extraction.video_id] = extraction
    profiled_observation_ids = frozenset(
        observation_id
        for _event_id, _profile_id, observation_id, action, _reviewer, _reason
        in database.list_effective_profile_observation_events()
        if action == "attach"
    )
    names: dict[int, set[str]] = {}
    for claim in database.list_speaker_name_claims():
        if (
            claim.observation_id is not None
            and claim.explicit_speaker_attribution
            and claim.normalized_name.strip()
        ):
            names.setdefault(claim.observation_id, set()).add(
                claim.normalized_name.strip()
            )
    return AssociationCorpusInventory(
        videos_by_id=videos_by_id,
        observations_by_id=observations_by_id,
        observations_by_video_id={
            video_id: tuple(sorted(values, key=lambda item: item.id))
            for video_id, values in observations_by_video_id.items()
        },
        current_observation_by_video_id=current_observation_by_video_id,
        latest_extraction_by_video_id=latest_extraction_by_video_id,
        archive_entries_by_artifact_id={
            entry.media_artifact_id: entry
            for entry in database.list_media_archive_entries()
        },
        profiled_observation_ids=profiled_observation_ids,
        review_actions_by_observation_id=(
            database.list_effective_observation_review_actions()
        ),
        source_id_by_video_id={
            video_id: video.source_id
            for video_id, video in videos_by_id.items()
        },
        candidate_names_by_observation={
            observation_id: frozenset(values)
            for observation_id, values in names.items()
        },
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
    inventory: AssociationCorpusInventory | None = None,
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
        latest_extractions_by_video_id=(
            inventory.latest_extraction_by_video_id
            if inventory is not None
            else None
        ),
        observations_by_video_id=(
            inventory.observations_by_video_id
            if inventory is not None
            else None
        ),
        review_actions_by_observation_id=(
            inventory.review_actions_by_observation_id
            if inventory is not None
            else None
        ),
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
        and (
            observation.id in inventory.profiled_observation_ids
            if inventory is not None
            else bool(
                database.list_effective_profile_ids_for_observation(
                    observation.id
                )
            )
        )
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
    review_action = (
        inventory.review_actions_by_observation_id.get(observation.id)
        if inventory is not None
        else database.get_effective_observation_review_action(observation.id)
    )
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

    availability = (
        media_artifact_availability(
            database,
            eligibility.media_artifact,
            verification_cache=verification_cache,
            archive_entries_by_artifact_id=(
                inventory.archive_entries_by_artifact_id
                if inventory is not None
                else None
            ),
        )
        if eligibility.media_artifact is not None
        else None
    )
    if availability is not None and availability.verified:
        verified = eligibility
    else:
        # Preserve fallback selection and archived-media reason semantics for
        # uncommon missing, corrupt, or offline metadata-selected artifacts.
        verified = assess_automatic_speaker_observation(
            database,
            video.id,
            verification_cache=verification_cache,
            verify_media=True,
            latest_extractions_by_video_id=(
                inventory.latest_extraction_by_video_id
                if inventory is not None
                else None
            ),
            observations_by_video_id=(
                inventory.observations_by_video_id
                if inventory is not None
                else None
            ),
            review_actions_by_observation_id=(
                inventory.review_actions_by_observation_id
                if inventory is not None
                else None
            ),
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


def scan_association_candidates(
    database: Database,
    videos: Sequence[Video],
    *,
    unattempted_only: bool,
    attempted_observation_fingerprints: frozenset[str],
    include_profiled: bool,
    verification_cache: MediaVerificationCache,
    remember_verified_source: Callable[[Path, str], None],
    exclusion_callback: Callable[[AssociationCandidateAssessment], None],
    inventory: AssociationCorpusInventory | None = None,
    progress_callback: Callable[[int, int, int, int], None] | None = None,
) -> AssociationCandidateScanResult:
    """Assess candidates in stable order and queue verified span inputs."""
    span_inputs: list[AssociationSpanInput] = []
    exclusion_counts: dict[str, int] = {}
    for index, video in enumerate(videos, start=1):
        if progress_callback is not None and (
            index == 1 or index == len(videos) or index % 25 == 0
        ):
            progress_callback(
                index,
                len(videos),
                len(span_inputs),
                sum(exclusion_counts.values()),
            )
        assessment = assess_association_candidate(
            database,
            video,
            unattempted_only=unattempted_only,
            attempted_observation_fingerprints=(
                attempted_observation_fingerprints
            ),
            include_profiled=include_profiled,
            verification_cache=verification_cache,
            inventory=inventory,
        )
        if not assessment.admitted:
            reason = assessment.exclusion_reason
            if reason is None:
                raise RuntimeError("Excluded association candidate has no reason.")
            exclusion_counts[reason] = exclusion_counts.get(reason, 0) + 1
            exclusion_callback(assessment)
            continue
        eligibility = assessment.eligibility
        audio_path = assessment.audio_path
        if (
            eligibility is None
            or eligibility.observation is None
            or eligibility.media_artifact is None
            or audio_path is None
        ):
            raise RuntimeError("Admitted association candidate is incomplete.")
        remember_verified_source(
            audio_path, eligibility.media_artifact.content_sha256
        )
        span_inputs.append(AssociationSpanInput(video, eligibility, audio_path))
    return AssociationCandidateScanResult(
        span_inputs=tuple(span_inputs),
        exclusion_counts=exclusion_counts,
    )


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


def plan_pending_confirmation_routing(
    database: Database,
    usable_profiles: Sequence[
        tuple[ProfileAssociationReadiness, Sequence[ShadowExemplar]]
    ],
    *,
    candidate_centroids: Mapping[int, Sequence[float]],
    candidate_video_ids: Mapping[int, int],
    exemplar_centroids: Mapping[int, Sequence[float]],
    candidates_per_profile: int = 2,
) -> PendingConfirmationRoutePlan:
    """Route candidates only to persisted discovery profiles awaiting proof."""
    profiles = tuple(
        (profile, exemplars)
        for profile, exemplars in usable_profiles
        if (
            "discovery_candidate_unconfirmed" in profile.automatic_blockers
            and (
                registry_profile := database.get_speaker_profile(
                    profile.profile_id
                )
            )
            is not None
            and registry_profile.created_reason == DISCOVERY_PROFILE_REASON
            and database.get_speaker_profile_discovery_promotion(
                profile.profile_id
            )
            is not None
        )
    )
    routes = plan_pending_discovery_confirmation_routes(
        profiles,
        candidate_centroids=candidate_centroids,
        candidate_video_ids=candidate_video_ids,
        exemplar_centroids=exemplar_centroids,
        candidates_per_profile=candidates_per_profile,
    )
    pending_profile_ids = frozenset(
        profile.profile_id for profile, _exemplars in profiles
    )
    routed_profile_ids = frozenset(
        profile_id
        for profile_ids in routes.values()
        for profile_id in profile_ids
    )
    return PendingConfirmationRoutePlan(
        profiles=profiles,
        routes=routes,
        pending_profile_ids=pending_profile_ids,
        routed_profile_ids=routed_profile_ids,
    )
