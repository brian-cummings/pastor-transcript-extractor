from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Callable

from pastor_transcript_extractor.disposition import REVIEW_REQUIRED
from pastor_transcript_extractor.fixture_validation import validate_fixture_directory
from pastor_transcript_extractor.models import Video
from pastor_transcript_extractor.sermon_policy import (
    maximum_sermon_duration_seconds,
    minimum_sermon_duration_seconds,
    video_is_sermon_eligible,
)
from pastor_transcript_extractor.storage import Database


@dataclass(frozen=True, slots=True)
class ReclassificationSelectionRequest:
    video_id: int | None = None
    source_id: int | None = None
    review_required: bool = False
    all_videos: bool = False
    fixture_dir: Path | None = None


@dataclass(frozen=True, slots=True)
class ReclassificationSelection:
    videos: tuple[Video, ...]
    messages: tuple[str, ...] = ()
    empty_is_success: bool = False


@dataclass(frozen=True, slots=True)
class ReclassificationEligibility:
    videos: tuple[Video, ...]
    skipped: int
    messages: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ReclassificationOutcome:
    video: Video
    result: Any | None = None
    error: Exception | None = None


@dataclass(frozen=True, slots=True)
class ReclassificationExecution:
    outcomes: tuple[ReclassificationOutcome, ...]


def has_reusable_extraction_segments(extraction: object) -> bool:
    """Return whether a persisted extraction contains usable timed text."""
    proposed_path = getattr(extraction, "proposed_json_path", None)
    if not isinstance(proposed_path, str) or not proposed_path.strip():
        return False
    try:
        payload = json.loads(Path(proposed_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(payload, dict):
        return False
    segments = payload.get("segments")
    if (
        not isinstance(segments, list)
        or not segments
        or any(
            not isinstance(segment, dict)
            or not isinstance(segment.get("text"), str)
            for segment in segments
        )
    ):
        return False
    return any(
        isinstance(segment.get("start_seconds"), (int, float))
        and not isinstance(segment.get("start_seconds"), bool)
        and isinstance(segment.get("end_seconds"), (int, float))
        and not isinstance(segment.get("end_seconds"), bool)
        and float(segment["end_seconds"]) > float(segment["start_seconds"])
        for segment in segments
    )


def select_reclassification_videos(
    database: Database,
    request: ReclassificationSelectionRequest,
) -> ReclassificationSelection:
    """Resolve exactly one CLI selector without rendering or running inference."""
    validate_reclassification_selection_request(request)

    messages: list[str] = []
    empty_is_success = False
    if request.video_id is not None:
        video = database.get_video_by_id(request.video_id)
        videos = [video] if video is not None else []
    elif request.source_id is not None:
        videos = list(database.list_videos_by_source_id(request.source_id))
    elif request.review_required:
        videos = []
        invalid_disposition_artifacts = 0
        for video in database.list_videos():
            extraction = database.get_latest_extraction_result_for_video(video.id)
            proposed_path = (
                getattr(extraction, "proposed_json_path", None)
                if extraction is not None
                else None
            )
            if not isinstance(proposed_path, str) or not proposed_path.strip():
                continue
            try:
                payload = json.loads(Path(proposed_path).read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                invalid_disposition_artifacts += 1
                continue
            disposition = (
                payload.get("final_disposition")
                if isinstance(payload, dict)
                else None
            )
            if (
                isinstance(disposition, dict)
                and disposition.get("status") == REVIEW_REQUIRED
            ):
                videos.append(video)
        videos.sort(key=lambda video: video.id)
        messages.append(
            f"Discovered {len(videos)} video(s) with a review_required "
            "final disposition."
        )
        if invalid_disposition_artifacts:
            messages.append(
                f"Skipped {invalid_disposition_artifacts} invalid proposed "
                "artifact(s) while selecting review-required videos."
            )
        if not videos:
            messages.append("No review-required videos remain to reclassify.")
            empty_is_success = True
    elif request.all_videos:
        videos = list(database.list_videos())
        messages.append(f"Discovered {len(videos)} video(s) in the corpus.")
    else:
        assert request.fixture_dir is not None
        fixture_root = request.fixture_dir.expanduser().resolve()
        fixtures = validate_fixture_directory(fixture_root)
        resolved = [
            (fixture, database.get_video_by_youtube_id(fixture.video_id))
            for fixture in fixtures
        ]
        missing_fixture_ids = [
            fixture.video_id for fixture, video in resolved if video is None
        ]
        if missing_fixture_ids:
            raise ValueError(
                "Fixture videos are missing from the database: "
                + ", ".join(missing_fixture_ids)
            )
        videos = [video for _, video in resolved if video is not None]
        messages.append(
            f"Discovered {len(videos)} fixture video(s) in {fixture_root}."
        )

    if not videos and not empty_is_success:
        raise ValueError("No matching videos found.")
    return ReclassificationSelection(
        videos=tuple(videos),
        messages=tuple(messages),
        empty_is_success=empty_is_success,
    )


def validate_reclassification_selection_request(
    request: ReclassificationSelectionRequest,
) -> None:
    """Validate mutually exclusive selectors before database initialization."""
    selector_count = sum(
        (
            request.video_id is not None,
            request.source_id is not None,
            request.fixture_dir is not None,
            request.review_required,
            request.all_videos,
        )
    )
    if selector_count != 1:
        raise ValueError(
            "Pass exactly one of --video-id, --source-id, --fixture-dir, "
            "--review-required, or --all."
        )


def select_eligible_reclassification_videos(
    database: Database,
    videos: tuple[Video, ...],
    *,
    fixture_selection: bool,
    report_skips: bool,
) -> ReclassificationEligibility:
    """Apply production eligibility and reusable-artifact gates."""
    eligible: list[Video] = []
    messages: list[str] = []
    skipped = 0
    minimum_duration = minimum_sermon_duration_seconds()
    maximum_duration = maximum_sermon_duration_seconds()
    for video in videos:
        # Frozen fixtures are explicit validation targets and intentionally
        # bypass production discovery eligibility policy.
        if not fixture_selection and not video_is_sermon_eligible(
            video.duration_seconds,
            video.published_at,
            minimum_seconds=minimum_duration,
            maximum_seconds=maximum_duration,
        ):
            skipped += 1
            if report_skips:
                messages.append(
                    f"Skipping video #{video.id}: video is outside the configured "
                    "sermon-video duration range or is a future event."
                )
            continue
        extraction = database.get_latest_extraction_result_for_video(video.id)
        if extraction is None:
            skipped += 1
            if report_skips:
                messages.append(
                    f"Skipping video #{video.id}: no reusable extraction segments."
                )
            continue
        if report_skips and not has_reusable_extraction_segments(extraction):
            skipped += 1
            messages.append(
                f"Skipping video #{video.id}: no reusable extraction segments."
            )
            continue
        eligible.append(video)
    return ReclassificationEligibility(
        videos=tuple(eligible),
        skipped=skipped,
        messages=tuple(messages),
    )


def execute_reclassification(
    videos: tuple[Video, ...],
    *,
    jobs: int,
    reclassify: Callable[[Video], Any],
) -> ReclassificationExecution:
    """Run independent classifications while isolating per-video failures."""
    if jobs < 1:
        raise ValueError("jobs must be at least 1")
    outcomes: list[ReclassificationOutcome] = []
    max_workers = min(jobs, len(videos)) if videos else 1
    if max_workers == 1:
        for video in videos:
            try:
                result = reclassify(video)
            except Exception as error:
                outcomes.append(ReclassificationOutcome(video=video, error=error))
            else:
                outcomes.append(ReclassificationOutcome(video=video, result=result))
    else:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_video = {
                executor.submit(reclassify, video): video for video in videos
            }
            for future in as_completed(future_to_video):
                video = future_to_video[future]
                try:
                    result = future.result()
                except Exception as error:
                    outcomes.append(
                        ReclassificationOutcome(video=video, error=error)
                    )
                else:
                    outcomes.append(
                        ReclassificationOutcome(video=video, result=result)
                    )
    return ReclassificationExecution(outcomes=tuple(outcomes))
