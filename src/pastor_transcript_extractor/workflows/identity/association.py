from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from pastor_transcript_extractor.identity_leverage import (
    profile_neighborhood_video_ids,
)
from pastor_transcript_extractor.media_artifacts import MediaVerificationCache
from pastor_transcript_extractor.models import SpeakerObservation, Video
from pastor_transcript_extractor.pipeline_diagnostics import (
    load_identity_association_attempts,
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
