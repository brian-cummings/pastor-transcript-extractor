from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from pastor_transcript_extractor.models import Video
from pastor_transcript_extractor.speaker_pair_diagnostics import SpanSpec
from pastor_transcript_extractor.speaker_pair_eligibility import (
    AutomaticSpeakerObservationEligibility,
)
from pastor_transcript_extractor.speaker_shadow_association import ShadowExemplar


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
