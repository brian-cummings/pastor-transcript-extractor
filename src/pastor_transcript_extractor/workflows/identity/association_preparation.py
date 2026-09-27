from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from pastor_transcript_extractor.identity_exemplar_preparation import (
    ExemplarPreparationStateCache,
)
from pastor_transcript_extractor.media_artifacts import MediaVerificationCache
from pastor_transcript_extractor.models import SpeakerObservation, Video
from pastor_transcript_extractor.speaker_pair_diagnostics import (
    AudioSpanCache,
    EmbeddingCache,
    SpanSpec,
)
from pastor_transcript_extractor.speaker_pair_eligibility import (
    AutomaticSpeakerObservationEligibility,
    assess_automatic_speaker_observation,
)
from pastor_transcript_extractor.speaker_shadow_association import (
    ProfileAssociationReadiness,
    ShadowExemplar,
    ShadowPolicySpec,
    select_profile_exemplars,
)
from pastor_transcript_extractor.speaker_profile_discovery import (
    ActivityQualifiedSelectionCache,
    TRANSCRIPT_GROUNDED_SPAN_SELECTION_VERSION,
    select_transcript_grounded_span_candidates,
)
from pastor_transcript_extractor.storage import Database


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
class AssociationCentroidCandidateInput:
    video: Video
    eligibility: AutomaticSpeakerObservationEligibility


@dataclass(frozen=True, slots=True)
class AssociationCandidateCentroidOutcome:
    candidate: AssociationCentroidCandidateInput
    observation_id: int | None
    video_id: int | None
    centroid: tuple[float, ...] | None
    failure: str | None


@dataclass(frozen=True, slots=True)
class AssociationCentroidPreparationResult:
    exemplar_centroids: Mapping[int, tuple[float, ...]]
    candidate_outcomes: tuple[AssociationCandidateCentroidOutcome, ...]


@dataclass(frozen=True, slots=True)
class AssociationExemplarPreparationResult:
    eligible_exemplars: tuple[ShadowExemplar, ...]
    usable_profiles: tuple[
        tuple[ProfileAssociationReadiness, Sequence[ShadowExemplar]], ...
    ]
    span_specs_by_observation_id: Mapping[int, tuple[SpanSpec, ...]]
    span_selections_by_observation_id: Mapping[int, Mapping[str, Any]]
    counts: Mapping[str, int]
    counts_by_profile: Mapping[int, Mapping[str, int]]


class TranscriptGroundedSpanProvider:
    """Load transcript candidates and optionally qualify coherent speech spans."""

    def __init__(
        self,
        database: Database,
        *,
        plan_only: bool,
        span_cache: AudioSpanCache,
        activity_selection_cache: ActivityQualifiedSelectionCache,
        embedding_cache: EmbeddingCache | None,
        backend: Any | None,
        policy_spec: ShadowPolicySpec,
    ) -> None:
        self._database = database
        self._plan_only = plan_only
        self._span_cache = span_cache
        self._activity_selection_cache = activity_selection_cache
        self._embedding_cache = embedding_cache
        self._backend = backend
        self._policy_spec = policy_spec

    def __call__(
        self,
        video_id: int,
        observation: SpeakerObservation,
        audio_path: Path,
        source_audio_sha256: str,
        *,
        acoustic_backend: Any | None = None,
    ) -> tuple[tuple[SpanSpec, ...], Mapping[str, Any] | None]:
        del video_id
        extraction = self._database.get_extraction_result(
            observation.extraction_result_id
        )
        if extraction is None or not extraction.proposed_json_path:
            return (), None
        try:
            payload = json.loads(
                Path(extraction.proposed_json_path).read_text(encoding="utf-8")
            )
        except (OSError, UnicodeError, json.JSONDecodeError):
            return (), None
        if not isinstance(payload, dict):
            return (), None
        candidates = select_transcript_grounded_span_candidates(
            payload, observation
        )
        if not candidates or self._plan_only:
            return candidates, None
        if self._backend is None or self._embedding_cache is None:
            raise RuntimeError("Acoustic span qualification is not initialized.")
        selected_backend = acoustic_backend or self._backend
        qualified = self._activity_selection_cache.get_or_prepare(
            observation=observation,
            source_audio_sha256=source_audio_sha256,
            audio_path=audio_path,
            span_cache=self._span_cache,
            candidate_specs=candidates,
            embedding_cache=self._embedding_cache,
            backend=selected_backend,
            policy=self._policy_spec.policy,
        )
        selection = {
            **qualified.selection,
            "coherent_sermon_speaker_spans": [
                {
                    "start_seconds": spec.start_seconds,
                    "end_seconds": spec.end_seconds,
                    "speaker_key": (
                        "sermon_speaker_candidate:"
                        f"{observation.input_fingerprint}"
                    ),
                    "relationship": "coherent_sermon_speaker",
                }
                for spec in qualified.span_specs
            ],
        }
        return qualified.span_specs, selection


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


def prepare_association_centroids(
    exemplars: Sequence[ShadowExemplar],
    candidates: Sequence[AssociationCentroidCandidateInput],
    *,
    jobs: int,
    build_exemplar_centroid: Callable[
        [ShadowExemplar], Sequence[float]
    ],
    build_candidate_centroid: Callable[
        [AssociationCentroidCandidateInput], Sequence[float]
    ],
    candidate_progress: Callable[[int, int], None] | None = None,
) -> AssociationCentroidPreparationResult:
    """Build stable retrieval centroids while isolating candidate failures."""

    def ordered_map(function, items, *, thread_name_prefix):
        if jobs == 1 or len(items) < 2:
            return tuple(map(function, items))
        with ThreadPoolExecutor(
            max_workers=min(jobs, len(items)),
            thread_name_prefix=thread_name_prefix,
        ) as executor:
            return tuple(executor.map(function, items))

    unique_exemplars = tuple(
        {
            exemplar.observation.id: exemplar
            for exemplar in exemplars
        }.values()
    )

    def prepare_exemplar(exemplar: ShadowExemplar):
        return (
            exemplar.observation.id,
            tuple(build_exemplar_centroid(exemplar)),
        )

    exemplar_centroids = dict(
        ordered_map(
            prepare_exemplar,
            unique_exemplars,
            thread_name_prefix="identity-exemplar-centroid",
        )
    )

    def prepare_candidate(
        indexed_candidate: tuple[int, AssociationCentroidCandidateInput],
    ) -> tuple[int, AssociationCandidateCentroidOutcome]:
        index, candidate = indexed_candidate
        observation = candidate.eligibility.observation
        if (
            observation is None
            or candidate.eligibility.media_artifact is None
        ):
            return index, AssociationCandidateCentroidOutcome(
                candidate, None, None, None, None
            )
        try:
            centroid = tuple(build_candidate_centroid(candidate))
        except Exception as error:
            return index, AssociationCandidateCentroidOutcome(
                candidate,
                observation.id,
                observation.video_id,
                None,
                f"{type(error).__name__}:{error}",
            )
        return index, AssociationCandidateCentroidOutcome(
            candidate,
            observation.id,
            observation.video_id,
            centroid,
            None,
        )

    indexed_candidates = tuple(enumerate(candidates, start=1))
    prepared_candidates = ordered_map(
        prepare_candidate,
        indexed_candidates,
        thread_name_prefix="identity-candidate-centroid",
    )
    outcomes: list[AssociationCandidateCentroidOutcome] = []
    for index, outcome in prepared_candidates:
        if candidate_progress is not None:
            candidate_progress(index, len(candidates))
        outcomes.append(outcome)
    return AssociationCentroidPreparationResult(
        exemplar_centroids=exemplar_centroids,
        candidate_outcomes=tuple(outcomes),
    )


def _path_state(path_value: str | None) -> dict[str, Any]:
    if not path_value:
        return {"path": path_value, "exists": False}
    path = Path(path_value).expanduser().resolve()
    try:
        stat = path.stat()
    except OSError:
        return {"path": str(path), "exists": False}
    return {
        "path": str(path),
        "exists": True,
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
    }


def _exemplar_preparation_evidence(
    database: Database,
    *,
    profile_id: int,
    observation: SpeakerObservation,
    assessed_observation: SpeakerObservation | None,
    media_artifact: Any | None,
    model_fingerprint: str | None,
    policy_artifact_sha256: str,
) -> dict[str, Any]:
    extraction = database.get_latest_extraction_result_for_video(
        observation.video_id
    )
    return {
        "profile_id": profile_id,
        "observation_id": observation.id,
        "observation_fingerprint": observation.input_fingerprint,
        "observation_extraction_result_id": observation.extraction_result_id,
        "assessed_observation": (
            {
                "id": assessed_observation.id,
                "input_fingerprint": assessed_observation.input_fingerprint,
                "extraction_result_id": assessed_observation.extraction_result_id,
            }
            if assessed_observation is not None
            else None
        ),
        "profile_member_is_current_automatic_observation": (
            assessed_observation is not None
            and assessed_observation.id == observation.id
        ),
        "effective_review_action": (
            database.get_effective_observation_review_action(observation.id)
        ),
        "latest_extraction": (
            {
                "id": extraction.id,
                "version": extraction.version,
                "json": _path_state(extraction.proposed_json_path),
            }
            if extraction is not None
            else None
        ),
        "media": (
            {
                "id": media_artifact.id,
                "input_fingerprint": media_artifact.input_fingerprint,
                "content_sha256": media_artifact.content_sha256,
                "artifact": _path_state(media_artifact.artifact_path),
            }
            if media_artifact is not None
            else None
        ),
        "span_selection_version": TRANSCRIPT_GROUNDED_SPAN_SELECTION_VERSION,
        "model_fingerprint": model_fingerprint,
        "policy_artifact_sha256": policy_artifact_sha256,
    }


def _exemplar_preparation_initial_blocker(
    *,
    profile_observation_id: int,
    assessment_eligible: bool,
    assessed_observation_id: int | None,
    assessment_reason_code: str,
) -> tuple[str, str]:
    if (
        assessment_eligible
        and assessed_observation_id is not None
        and assessed_observation_id != profile_observation_id
    ):
        return "observation_consistency", "assessed_observation_mismatch"
    stage = (
        "extraction_lookup"
        if assessment_reason_code.startswith("extraction_")
        else "media_registration"
        if "media" in assessment_reason_code or "audio" in assessment_reason_code
        else "observation_consistency"
    )
    return stage, assessment_reason_code


def prepare_association_exemplars(
    database: Database,
    readiness: Sequence[ProfileAssociationReadiness],
    *,
    verification_cache: MediaVerificationCache,
    span_cache: AudioSpanCache,
    state_cache: ExemplarPreparationStateCache,
    videos_by_id: Mapping[int, Video],
    plan_only: bool,
    model_fingerprint: str | None,
    policy_artifact_sha256: str,
    maximum_exemplars: int,
    minimum_same_exemplars: int,
    prepare_spans: Callable[
        [int, SpeakerObservation, Path, str],
        tuple[tuple[SpanSpec, ...], Mapping[str, Any] | None],
    ],
    profile_progress: Callable[
        [int, int, ProfileAssociationReadiness], None
    ] | None = None,
) -> AssociationExemplarPreparationResult:
    """Prepare and persist the per-profile acoustic exemplar funnel."""
    eligible_exemplars: list[ShadowExemplar] = []
    span_specs_by_observation_id: dict[int, tuple[SpanSpec, ...]] = {}
    span_selections_by_observation_id: dict[int, Mapping[str, Any]] = {}
    counts: dict[str, int] = {}
    counts_by_profile: dict[int, dict[str, int]] = {}

    def count(profile_id: int, key: str) -> None:
        counts[key] = counts.get(key, 0) + 1
        profile_counts = counts_by_profile.setdefault(profile_id, {})
        profile_counts[key] = profile_counts.get(key, 0) + 1

    def record(
        *,
        profile_id: int,
        observation: SpeakerObservation,
        evidence: Mapping[str, Any],
        stage: str,
        outcome: str,
        reason_code: str,
    ) -> None:
        count(
            profile_id,
            "eligible" if outcome == "eligible" else f"{stage}:{reason_code}",
        )
        if plan_only:
            return
        video = videos_by_id.get(observation.video_id)
        if video is None:
            return
        state_cache.record(
            profile_id=profile_id,
            observation_id=observation.id,
            observation_fingerprint=observation.input_fingerprint,
            video_id=observation.video_id,
            youtube_video_id=video.youtube_video_id,
            evidence=evidence,
            stage=stage,
            outcome=outcome,
            reason_code=reason_code,
        )

    review_ready_profiles = tuple(
        profile for profile in readiness if profile.review_ready
    )
    for profile_index, profile in enumerate(review_ready_profiles, start=1):
        if profile_progress is not None:
            profile_progress(profile_index, len(review_ready_profiles), profile)
        observation_ids = (
            profile.certified_exemplar_observation_ids
            if profile.automatic_profile_ready
            and profile.certified_exemplar_observation_ids
            else profile.member_observation_ids
        )
        for observation_id in observation_ids:
            observation = database.get_speaker_observation(observation_id)
            if observation is None:
                continue
            eligibility = assess_automatic_speaker_observation(
                database,
                observation.video_id,
                observation_id=observation.id,
                verification_cache=verification_cache,
                verify_media=False,
            )
            evidence = _exemplar_preparation_evidence(
                database,
                profile_id=profile.profile_id,
                observation=observation,
                assessed_observation=eligibility.observation,
                media_artifact=eligibility.media_artifact,
                model_fingerprint=model_fingerprint,
                policy_artifact_sha256=policy_artifact_sha256,
            )
            evidence_fingerprint = state_cache.evidence_fingerprint(evidence)
            unchanged = (
                state_cache.unchanged_deterministic_failure(
                    profile_id=profile.profile_id,
                    observation_fingerprint=observation.input_fingerprint,
                    evidence_fingerprint=evidence_fingerprint,
                )
                if not plan_only
                else None
            )
            if unchanged is not None:
                count(
                    profile.profile_id,
                    f"cached:{unchanged.stage}:{unchanged.reason_code}",
                )
                continue
            if (
                not eligibility.eligible
                or eligibility.observation is None
                or eligibility.media_artifact is None
                or eligibility.observation.id != observation.id
            ):
                stage, reason_code = _exemplar_preparation_initial_blocker(
                    profile_observation_id=observation.id,
                    assessment_eligible=eligibility.eligible,
                    assessed_observation_id=(
                        eligibility.observation.id
                        if eligibility.observation is not None
                        else None
                    ),
                    assessment_reason_code=eligibility.reason_code,
                )
                record(
                    profile_id=profile.profile_id,
                    observation=observation,
                    evidence=evidence,
                    stage=stage,
                    outcome="blocked",
                    reason_code=reason_code,
                )
                continue
            eligibility = assess_automatic_speaker_observation(
                database,
                observation.video_id,
                observation_id=observation.id,
                verification_cache=verification_cache,
                verify_media=True,
            )
            if (
                not eligibility.eligible
                or eligibility.observation is None
                or eligibility.media_artifact is None
                or eligibility.observation.id != observation.id
            ):
                record(
                    profile_id=profile.profile_id,
                    observation=observation,
                    evidence=evidence,
                    stage="media_verification",
                    outcome="blocked",
                    reason_code=eligibility.reason_code,
                )
                continue
            audio_path = Path(eligibility.media_artifact.artifact_path)
            span_cache.remember_verified_source(
                audio_path, eligibility.media_artifact.content_sha256
            )
            try:
                span_specs, span_selection = prepare_spans(
                    observation.video_id,
                    observation,
                    audio_path,
                    eligibility.media_artifact.content_sha256,
                )
            except (OSError, RuntimeError, ValueError) as error:
                record(
                    profile_id=profile.profile_id,
                    observation=observation,
                    evidence=evidence,
                    stage="activity_span_selection",
                    outcome="blocked",
                    reason_code=(
                        str(error) or "activity_qualified_spans_unavailable"
                    ),
                )
                continue
            if not span_specs:
                record(
                    profile_id=profile.profile_id,
                    observation=observation,
                    evidence=evidence,
                    stage="transcript_span_selection",
                    outcome="blocked",
                    reason_code="speech_grounded_spans_unavailable",
                )
                continue
            if span_selection is not None:
                span_selections_by_observation_id[observation.id] = span_selection
            span_specs_by_observation_id[observation.id] = span_specs
            eligible_exemplars.append(
                ShadowExemplar(
                    profile_id=profile.profile_id,
                    observation=observation,
                    audio_path=audio_path,
                    audio_sha256=eligibility.media_artifact.content_sha256,
                    span_specs=span_specs,
                )
            )
            record(
                profile_id=profile.profile_id,
                observation=observation,
                evidence=evidence,
                stage="complete",
                outcome="eligible",
                reason_code="eligible_exemplar",
            )

    usable_profiles = []
    for profile in readiness:
        if not profile.review_ready:
            continue
        exemplars = select_profile_exemplars(
            profile,
            eligible_exemplars,
            videos_by_id=videos_by_id,
            maximum_exemplars=maximum_exemplars,
        )
        if len(exemplars) >= minimum_same_exemplars:
            usable_profiles.append((profile, exemplars))
    return AssociationExemplarPreparationResult(
        eligible_exemplars=tuple(eligible_exemplars),
        usable_profiles=tuple(usable_profiles),
        span_specs_by_observation_id=span_specs_by_observation_id,
        span_selections_by_observation_id=span_selections_by_observation_id,
        counts=counts,
        counts_by_profile=counts_by_profile,
    )
