from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Callable

from pastor_transcript_extractor import (
    artifact_namespace,
    extraction,
    identity,
    speaker_pair_eligibility,
)
from pastor_transcript_extractor.config import AppPaths
from pastor_transcript_extractor.fixture_correction import (
    FixtureWindowCorrection,
    persist_fixture_window_override,
)
from pastor_transcript_extractor.models import Video
from pastor_transcript_extractor.storage import Database


@dataclass(frozen=True, slots=True)
class FixtureCorrectionResult:
    video_id: int
    fixture_path: Path
    start_seconds: float
    end_seconds: float
    disposition_status: str
    observation_fingerprint: str
    previous_fingerprint: str | None
    fingerprint_state: str
    automatic_pair_eligibility: str


def propagate_fixture_correction(
    database: Database,
    paths: AppPaths,
    *,
    video: Video,
    correction: FixtureWindowCorrection,
    previous_observation: Any | None,
    normalized_audio: Any | None,
    llm_client: Any,
    prompt_version: str,
    context_size: int,
    recording_verifier: Any,
    inference_cache_root: Path | None,
    recording_verifier_cache_root: Path | None,
    event_callback: Callable[[str], None] | None = None,
) -> FixtureCorrectionResult:
    """Persist, propagate, and verify one approved fixture correction."""
    video_paths = artifact_namespace.resolve_video_artifact_paths(
        database,
        paths,
        video,
    )
    persist_fixture_window_override(
        correction,
        video_paths.review / "window_override.json",
    )
    if event_callback is not None:
        event_callback(
            f"Applied fixture {correction.fixture_path} as window override "
            f"{correction.start_seconds:.3f}-{correction.end_seconds:.3f}s."
        )

    result = extraction.reclassify_video(
        database,
        paths,
        video.id,
        llm_client=llm_client,
        prompt_version=prompt_version,
        force=True,
        progress=(
            None
            if event_callback is None
            else lambda stage, current, total: event_callback(
                f"  video #{video.id} {stage} block {current}/{total}"
            )
        ),
        model_digest=llm_client.model_digest(),
        context_size=context_size,
        inference_cache_dir=(
            inference_cache_root / video.youtube_video_id
            if inference_cache_root is not None
            else None
        ),
        recording_verifier=recording_verifier,
        recording_verifier_cache_dir=recording_verifier_cache_root,
    )
    proposed = json.loads(result.proposed_json_path.read_text(encoding="utf-8"))
    window = proposed.get("sermon_window")
    if not isinstance(window, dict):
        raise ValueError("reclassification did not persist a sermon window")
    persisted_start = window.get("start_seconds")
    persisted_end = window.get("end_seconds")
    if (
        window.get("source") != "override"
        or not isinstance(persisted_start, (int, float))
        or isinstance(persisted_start, bool)
        or not isinstance(persisted_end, (int, float))
        or isinstance(persisted_end, bool)
        or abs(float(persisted_start) - correction.start_seconds) > 1e-6
        or abs(float(persisted_end) - correction.end_seconds) > 1e-6
    ):
        raise ValueError(
            "reclassification did not preserve the fixture-derived override"
        )

    current_extraction = database.get_latest_extraction_result_for_video(video.id)
    if current_extraction is None:
        raise ValueError("latest extraction disappeared after reclassification")
    pastor = (
        database.get_pastor_by_id(video.pastor_id)
        if video.pastor_id is not None
        else None
    )
    speaker_record = identity.record_neutral_speaker_evidence(
        database,
        paths,
        video=video,
        pastor=pastor,
        extraction_result=current_extraction,
        normalized_audio_artifact=normalized_audio,
    )
    observation = speaker_record.neutral_evidence.observation
    if observation is None:
        raise ValueError("corrected extraction did not produce a speaker observation")
    if (
        observation.extraction_result_id != current_extraction.id
        or abs(observation.start_seconds - correction.start_seconds) > 1e-6
        or abs(observation.end_seconds - correction.end_seconds) > 1e-6
    ):
        raise ValueError(
            "speaker observation does not match the corrected extraction window"
        )

    previous_fingerprint = (
        previous_observation.input_fingerprint
        if previous_observation is not None
        else None
    )
    fingerprint_state = (
        "reused"
        if previous_fingerprint == observation.input_fingerprint
        else "regenerated"
    )
    eligibility = speaker_pair_eligibility.assess_automatic_speaker_observation(
        database,
        video.id,
    )
    disposition = proposed.get("final_disposition")
    disposition_status = (
        disposition.get("status") if isinstance(disposition, dict) else "unknown"
    )
    return FixtureCorrectionResult(
        video_id=video.id,
        fixture_path=correction.fixture_path,
        start_seconds=correction.start_seconds,
        end_seconds=correction.end_seconds,
        disposition_status=str(disposition_status),
        observation_fingerprint=observation.input_fingerprint,
        previous_fingerprint=previous_fingerprint,
        fingerprint_state=fingerprint_state,
        automatic_pair_eligibility=eligibility.reason_code,
    )
