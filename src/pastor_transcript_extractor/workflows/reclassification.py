from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

from pastor_transcript_extractor.disposition import REVIEW_REQUIRED
from pastor_transcript_extractor.fixture_validation import validate_fixture_directory
from pastor_transcript_extractor.models import Video
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
