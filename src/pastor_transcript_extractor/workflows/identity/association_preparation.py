from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field, replace
import json
import math
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from pastor_transcript_extractor.identity_exemplar_preparation import (
    ExemplarPreparationStateCache,
)
from pastor_transcript_extractor.identity_prepared_profiles import PreparedProfileCache
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
    ACTIVITY_QUALIFIED_SELECTION_CACHE_VERSION,
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
    preparation_cache_counts: Mapping[str, int] = field(default_factory=dict)


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
        "ctime_ns": stat.st_ctime_ns,
        "device": stat.st_dev,
        "inode": stat.st_ino,
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


def _prepare_association_exemplars_uncached(
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
    profile_cache: PreparedProfileCache | None = None,
) -> AssociationExemplarPreparationResult:
    """Prepare and persist the per-profile acoustic exemplar funnel."""
    eligible_exemplars: list[ShadowExemplar] = []
    span_specs_by_observation_id: dict[int, tuple[SpanSpec, ...]] = {}
    span_selections_by_observation_id: dict[int, Mapping[str, Any]] = {}
    counts: dict[str, int] = {}
    counts_by_profile: dict[int, dict[str, int]] = {}
    cache_counts = {"members_reused": 0, "members_prepared": 0}

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
            member_inputs = (
                _prepared_member_inputs(
                    database, observation, eligibility.media_artifact,
                    model_fingerprint, policy_artifact_sha256,
                )
                if profile_cache is not None and not plan_only else None
            )
            saved_member = (
                profile_cache.load("member", member_inputs)
                if member_inputs is not None else None
            )
            reused = _decode_prepared_exemplar(saved_member, profile.profile_id, observation)
            if reused is not None and (
                reused[0].audio_path != audio_path
                or reused[0].audio_sha256 != eligibility.media_artifact.content_sha256
            ):
                reused = None
            try:
                if reused is not None:
                    span_specs, span_selection = reused[0].span_specs, reused[1]
                    cache_counts["members_reused"] += 1
                else:
                    cache_counts["members_prepared"] += 1
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
            if member_inputs is not None and reused is None:
                profile_cache.save("member", member_inputs, _encode_prepared_exemplar(
                    eligible_exemplars[-1], span_selection,
                ))
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
        preparation_cache_counts=cache_counts,
    )


def _prepared_member_inputs(database, observation, media, model_fingerprint, policy_sha256):
    """Acoustic dependencies independent of a profile's name or membership.

    An exact historical member uses its own extraction, as the span provider
    does. A newer extraction is not a replacement for that immutable member.
    """
    extraction = database.get_extraction_result(observation.extraction_result_id)
    return {
        "observation": {
            key: getattr(observation, key) for key in (
                "id", "video_id", "input_fingerprint", "extraction_result_id",
                "start_seconds", "end_seconds", "role", "multiplicity_state",
                "content_sha256", "extractor_version", "artifact_path",
            )
        },
        "review_action": database.get_effective_observation_review_action(observation.id),
        "extraction": None if extraction is None else {
            "id": extraction.id, "video_id": extraction.video_id,
            "version": extraction.version,
            "json": _path_state(extraction.proposed_json_path),
        },
        "media": {
            "id": media.id, "input_fingerprint": media.input_fingerprint,
            "content_sha256": media.content_sha256,
            "artifact": _path_state(media.artifact_path),
        },
        "model_fingerprint": model_fingerprint,
        "policy_artifact_sha256": policy_sha256,
        "span_selection_version": TRANSCRIPT_GROUNDED_SPAN_SELECTION_VERSION,
        "activity_selection_version": ACTIVITY_QUALIFIED_SELECTION_CACHE_VERSION,
    }


def _encode_prepared_exemplar(exemplar, selection):
    return {
        "observation_id": exemplar.observation.id,
        "observation_fingerprint": exemplar.observation.input_fingerprint,
        "audio_path": str(exemplar.audio_path),
        "audio_sha256": exemplar.audio_sha256,
        "spans": [asdict(span) for span in exemplar.span_specs],
        "selection": selection,
    }


def _decode_prepared_exemplar(payload, profile_id, observation):
    if not isinstance(payload, dict) or (
        payload.get("observation_id") != observation.id
        or payload.get("observation_fingerprint") != observation.input_fingerprint
        or not isinstance(payload.get("audio_path"), str)
        or not payload["audio_path"]
        or not isinstance(payload.get("audio_sha256"), str)
        or not payload["audio_sha256"]
        or not isinstance(payload.get("spans"), list)
        or not payload["spans"]
        or not (payload.get("selection") is None or isinstance(payload["selection"], dict))
    ):
        return None
    try:
        spans = tuple(SpanSpec(**span) for span in payload["spans"])
        if any(
            isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value)
            for span in spans for value in (span.start_seconds, span.end_seconds)
        ) or any(span.end_seconds <= span.start_seconds for span in spans):
            return None
    except (TypeError, ValueError):
        return None
    return ShadowExemplar(
        profile_id, observation, Path(payload["audio_path"]),
        payload["audio_sha256"], spans,
    ), payload.get("selection")


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
    prepare_spans: Callable,
    profile_progress: Callable | None = None,
    profile_cache: PreparedProfileCache | None = None,
) -> AssociationExemplarPreparationResult:
    """Reuse prepared profile units after fresh metadata and media admission.

    Partial profiles still reuse compatible individual successes. Failures keep
    the existing retry and repair policy; a profile snapshot cannot hide them.
    """
    arguments = dict(
        verification_cache=verification_cache, span_cache=span_cache,
        state_cache=state_cache, videos_by_id=videos_by_id, plan_only=plan_only,
        model_fingerprint=model_fingerprint, policy_artifact_sha256=policy_artifact_sha256,
        maximum_exemplars=maximum_exemplars, minimum_same_exemplars=minimum_same_exemplars,
        prepare_spans=prepare_spans, profile_cache=profile_cache,
    )
    if profile_cache is None or plan_only:
        result = _prepare_association_exemplars_uncached(
            database, readiness, profile_progress=profile_progress, **arguments,
        )
        if profile_cache is not None:
            profiles = [p for p in readiness if p.review_ready]
            result = replace(result, preparation_cache_counts={
                "profiles_not_checked_plan_only": len(profiles),
                "profile_snapshots_present": sum(profile_cache.has_profile(p.profile_id) for p in profiles),
            })
        return result

    exemplars, usable, specs, selections, counts, by_profile = [], [], {}, {}, {}, {}
    cache_counts = {"profiles_reused": 0, "profiles_rebuilt": 0,
                    "members_reused": 0, "members_prepared": 0}
    profiles = [p for p in readiness if p.review_ready]
    for index, profile in enumerate(profiles, start=1):
        if profile_progress is not None:
            profile_progress(index, len(profiles), profile)
        inputs, observations = _prepared_profile_inputs(
            database, profile, videos_by_id, verification_cache, state_cache,
            model_fingerprint, policy_artifact_sha256,
            maximum_exemplars, minimum_same_exemplars,
        )
        saved = (profile_cache.load("profile", inputs, profile_id=profile.profile_id)
                 if inputs is not None else None)
        result = _replay_prepared_profile(
            saved, database, profile, observations, verification_cache,
            span_cache, videos_by_id, maximum_exemplars, minimum_same_exemplars,
        )
        if result is not None:
            cache_counts["profiles_reused"] += 1
        else:
            cache_counts["profiles_rebuilt"] += 1
            result = _prepare_association_exemplars_uncached(database, (profile,), **arguments)
            # Whole-profile reuse is limited to fully successful preparation;
            # blocked or transient members must retain the normal failure path.
            if inputs is not None and observations and len(result.eligible_exemplars) == len(observations):
                inputs["preparation_states"] = _preparation_states(state_cache, profile, observations)
                profile_cache.save("profile", inputs, {
                    "exemplars": [_encode_prepared_exemplar(
                        e, result.span_selections_by_observation_id.get(e.observation.id),
                    ) for e in result.eligible_exemplars],
                    "selected_observation_ids": [
                        e.observation.id for _p, selected in result.usable_profiles for e in selected
                    ],
                }, profile_id=profile.profile_id)
        exemplars.extend(result.eligible_exemplars)
        usable.extend(result.usable_profiles)
        specs.update(result.span_specs_by_observation_id)
        selections.update(result.span_selections_by_observation_id)
        by_profile.update(result.counts_by_profile)
        for key, value in result.counts.items():
            counts[key] = counts.get(key, 0) + value
        for key, value in result.preparation_cache_counts.items():
            cache_counts[key] = cache_counts.get(key, 0) + value
    return AssociationExemplarPreparationResult(
        tuple(exemplars), tuple(usable), specs, selections, counts, by_profile, cache_counts,
    )


def _prepared_profile_inputs(database, profile, videos_by_id, verification_cache, state_cache,
                             model_fingerprint, policy_sha256, maximum, minimum):
    member_ids = (profile.certified_exemplar_observation_ids
                  if profile.automatic_profile_ready and profile.certified_exemplar_observation_ids
                  else profile.member_observation_ids)
    observations, members, state_evidence = {}, [], []
    for observation_id in member_ids:
        observation = database.get_speaker_observation(observation_id)
        if observation is None:
            return None, {}
        eligibility = assess_automatic_speaker_observation(
            database, observation.video_id, observation_id=observation_id,
            verification_cache=verification_cache, verify_media=False,
        )
        if (not eligibility.eligible or eligibility.observation is None
                or eligibility.observation.id != observation_id or eligibility.media_artifact is None):
            return None, {}
        observations[observation_id] = observation
        members.append(_prepared_member_inputs(
            database, observation, eligibility.media_artifact, model_fingerprint, policy_sha256,
        ))
        state_evidence.append(_exemplar_preparation_evidence(
            database, profile_id=profile.profile_id, observation=observation,
            assessed_observation=eligibility.observation, media_artifact=eligibility.media_artifact,
            model_fingerprint=model_fingerprint, policy_artifact_sha256=policy_sha256,
        ))
    return {
        "readiness": asdict(profile), "members": members,
        "state_evidence": state_evidence,
        "preparation_states": _preparation_states(state_cache, profile, observations),
        "source_ids": [getattr(videos_by_id.get(o.video_id), "source_id", -1)
                       for o in observations.values()],
        "maximum_exemplars": maximum, "minimum_same_exemplars": minimum,
    }, observations


def _preparation_states(state_cache, profile, observations):
    # A previous success must not conceal a later blocked/repair state. Rebuild
    # the profile (retaining member acoustics) so the normal ledger is restored.
    return [
        asdict(state) if (state := state_cache.latest_for_observation(
            profile_id=profile.profile_id, observation_fingerprint=o.input_fingerprint,
        )) is not None else None
        for o in observations.values()
    ]


def _replay_prepared_profile(saved, database, profile, observations, verification_cache,
                             span_cache, videos_by_id, maximum, minimum):
    if not isinstance(saved, dict) or not isinstance(saved.get("exemplars"), list):
        return None
    if (len(saved["exemplars"]) != len(observations)
            or [e.get("observation_id") for e in saved["exemplars"] if isinstance(e, dict)] != list(observations)):
        return None
    exemplars, selections = [], {}
    for raw, observation in zip(saved["exemplars"], observations.values(), strict=True):
        decoded = _decode_prepared_exemplar(raw, profile.profile_id, observation)
        if decoded is None:
            return None
        exemplar, selection = decoded
        eligibility = assess_automatic_speaker_observation(
            database, observation.video_id, observation_id=observation.id,
            verification_cache=verification_cache, verify_media=True,
        )
        if (not eligibility.eligible or eligibility.observation is None
                or eligibility.observation.id != observation.id or eligibility.media_artifact is None
                or Path(eligibility.media_artifact.artifact_path) != exemplar.audio_path
                or eligibility.media_artifact.content_sha256 != exemplar.audio_sha256):
            return None
        span_cache.remember_verified_source(exemplar.audio_path, exemplar.audio_sha256)
        exemplars.append(exemplar)
        if selection is not None:
            selections[observation.id] = selection
    selected = select_profile_exemplars(profile, exemplars, videos_by_id=videos_by_id,
                                       maximum_exemplars=maximum)
    usable = ((profile, selected),) if len(selected) >= minimum else ()
    selected_ids = [e.observation.id for _p, values in usable for e in values]
    if selected_ids != saved.get("selected_observation_ids"):
        return None
    return AssociationExemplarPreparationResult(
        tuple(exemplars), usable, {e.observation.id: e.span_specs for e in exemplars},
        selections, {"eligible": len(exemplars)}, {profile.profile_id: {"eligible": len(exemplars)}},
        {"members_reused": len(exemplars), "members_prepared": 0},
    )
