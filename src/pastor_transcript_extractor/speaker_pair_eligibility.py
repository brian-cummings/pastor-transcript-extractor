from __future__ import annotations

from dataclasses import dataclass
import json
import math
from pathlib import Path

from pastor_transcript_extractor.disposition import ACCEPTED_SERMON
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


def assess_automatic_speaker_observation(
    database: Database,
    video_id: int,
    *,
    verification_cache: MediaVerificationCache | None = None,
    verify_media: bool = True,
) -> AutomaticSpeakerObservationEligibility:
    """Admit only an observation derived from the current accepted sermon window.

    ``verify_media=False`` is metadata-only and must be used only for inventory
    or status reporting. Automatic selection and media consumption retain the
    default byte-verifying behavior.
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
    if status != ACCEPTED_SERMON:
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
