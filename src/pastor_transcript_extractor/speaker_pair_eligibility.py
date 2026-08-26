from __future__ import annotations

from dataclasses import dataclass
import json
import math
from pathlib import Path
from typing import Callable, Sequence

from pastor_transcript_extractor.disposition import ACCEPTED_SERMON, REVIEW_REQUIRED
from pastor_transcript_extractor.media_artifacts import (
    ArchivedMediaUnavailableError,
    MediaVerificationCache,
    get_registered_normalized_media_artifact,
    get_verified_normalized_media_artifact,
)
from pastor_transcript_extractor.models import MediaArtifact, SpeakerObservation
from pastor_transcript_extractor.speaker_pair_diagnostics import (
    SpanSpec,
    select_diagnostic_spans,
)
from pastor_transcript_extractor.speaker_pair_selector import (
    PairCandidateObservation,
    PairSelection,
)
from pastor_transcript_extractor.storage import Database


@dataclass(frozen=True, slots=True)
class AutomaticSpeakerObservationEligibility:
    """Conservative eligibility result for automatic speaker-pair nomination."""

    reason_code: str
    observation: SpeakerObservation | None = None
    media_artifact: MediaArtifact | None = None
    diagnostic_spans: tuple[SpanSpec, ...] = ()

    @property
    def eligible(self) -> bool:
        return self.reason_code == "eligible"


@dataclass(frozen=True, slots=True)
class VerifiedAutomaticPairSelection:
    """A deterministic nomination whose two media artifacts were verified."""

    selection: PairSelection
    selection_attempts: int
    rejection_counts: dict[str, int]


def select_verified_automatic_speaker_pair(
    database: Database,
    observations: Sequence[PairCandidateObservation],
    *,
    select_pair: Callable[[Sequence[PairCandidateObservation]], PairSelection],
    verification_cache: MediaVerificationCache | None = None,
) -> VerifiedAutomaticPairSelection:
    """Select from metadata, then byte-verify only nominated observations.

    A failed or stale nomination is removed and selection is replayed over the
    remaining observations. Filtering preserves candidate order, so the result
    is deterministic while uncertainty remains fail-closed.
    """
    remaining = list(observations)
    rejection_counts: dict[str, int] = {}
    attempts = 0
    while True:
        try:
            selection = select_pair(remaining)
        except ValueError as error:
            if not rejection_counts:
                raise
            details = ", ".join(
                f"{reason}={count}"
                for reason, count in sorted(rejection_counts.items())
            )
            raise ValueError(
                f"{error}; selected-pair verification exclusions: {details}"
            ) from error

        attempts += 1
        failed_fingerprints: set[str] = set()
        for candidate in (
            selection.observation_a,
            selection.observation_b,
        ):
            video = database.get_video_by_youtube_id(candidate.video_id)
            if video is None:
                reason = "selected_video_unavailable"
            else:
                eligibility = assess_automatic_speaker_observation(
                    database,
                    video.id,
                    verification_cache=verification_cache,
                    verify_media=True,
                )
                if not eligibility.eligible:
                    reason = eligibility.reason_code
                elif (
                    eligibility.observation is None
                    or eligibility.observation.input_fingerprint
                    != candidate.input_fingerprint
                ):
                    reason = "selected_observation_changed"
                else:
                    continue
            failed_fingerprints.add(candidate.input_fingerprint)
            rejection_counts[reason] = rejection_counts.get(reason, 0) + 1

        if not failed_fingerprints:
            return VerifiedAutomaticPairSelection(
                selection=selection,
                selection_attempts=attempts,
                rejection_counts=rejection_counts,
            )

        next_remaining = [
            candidate
            for candidate in remaining
            if candidate.input_fingerprint not in failed_fingerprints
        ]
        if len(next_remaining) == len(remaining):
            raise RuntimeError(
                "selected-pair verification did not remove a failed candidate"
            )
        remaining = next_remaining


def assess_automatic_speaker_observation(
    database: Database,
    video_id: int,
    *,
    verification_cache: MediaVerificationCache | None = None,
    verify_media: bool = True,
    allow_review_required: bool = False,
) -> AutomaticSpeakerObservationEligibility:
    """Admit only an observation derived from the current accepted sermon window.

    ``verify_media=False`` is metadata-only. It may be used for inventory,
    status reporting, or candidate ranking only when the selected observation
    is subsequently reassessed with the default byte-verifying behavior before
    any media is consumed.
    """
    extraction = database.get_latest_extraction_result_for_video(video_id)
    if extraction is None or not extraction.proposed_json_path:
        return AutomaticSpeakerObservationEligibility("extraction_unavailable")

    try:
        payload = json.loads(
            Path(extraction.proposed_json_path).expanduser().read_text(encoding="utf-8")
        )
    except (OSError, UnicodeError, json.JSONDecodeError):
        return AutomaticSpeakerObservationEligibility("extraction_artifact_unreadable")
    if not isinstance(payload, dict):
        return AutomaticSpeakerObservationEligibility("extraction_artifact_malformed")

    disposition = payload.get("final_disposition")
    if not isinstance(disposition, dict):
        return AutomaticSpeakerObservationEligibility("disposition_missing_or_malformed")
    status = disposition.get("status")
    if not isinstance(status, str):
        return AutomaticSpeakerObservationEligibility("disposition_missing_or_malformed")
    if status != ACCEPTED_SERMON and not (
        allow_review_required and status == REVIEW_REQUIRED
    ):
        return AutomaticSpeakerObservationEligibility("disposition_not_accepted")

    window = _valid_window(payload.get("sermon_window"))
    if window is None:
        return AutomaticSpeakerObservationEligibility("sermon_window_invalid")

    observation = database.get_speaker_observation_for_extraction_window(
        video_id,
        extraction.id,
        start_seconds=window[0],
        end_seconds=window[1],
    )
    if observation is None:
        latest_observation = database.get_latest_speaker_observation_for_video(
            video_id
        )
        if latest_observation is None:
            return AutomaticSpeakerObservationEligibility(
                "observation_unavailable"
            )
        if (
            latest_observation.video_id != video_id
            or latest_observation.extraction_result_id != extraction.id
        ):
            return AutomaticSpeakerObservationEligibility(
                "observation_not_current_extraction"
            )
        return AutomaticSpeakerObservationEligibility(
            "observation_window_mismatch"
        )

    diagnostic_spans = select_diagnostic_spans(observation)
    if not diagnostic_spans:
        return AutomaticSpeakerObservationEligibility("diagnostic_spans_unavailable")

    if verify_media:
        try:
            media = get_verified_normalized_media_artifact(
                database,
                video_id,
                verification_cache=verification_cache,
            )
        except ArchivedMediaUnavailableError:
            return AutomaticSpeakerObservationEligibility(
                "archived_media_unavailable",
                observation=observation,
            )
        except OSError:
            media = None
    else:
        media = get_registered_normalized_media_artifact(database, video_id)
    if media is None:
        return AutomaticSpeakerObservationEligibility(
            (
                "verified_normalized_media_unavailable"
                if verify_media
                else "registered_normalized_media_unavailable"
            )
        )
    return AutomaticSpeakerObservationEligibility(
        "eligible",
        observation=observation,
        media_artifact=media,
        diagnostic_spans=diagnostic_spans,
    )


def _valid_window(value: object) -> tuple[float, float] | None:
    if not isinstance(value, dict):
        return None
    start = _finite_number(value.get("start_seconds"))
    end = _finite_number(value.get("end_seconds"))
    if start is None or end is None or end <= start:
        return None
    return start, end


def _finite_number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None
