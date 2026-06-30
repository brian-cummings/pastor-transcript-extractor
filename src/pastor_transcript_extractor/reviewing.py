from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from pastor_transcript_extractor.config import AppPaths, build_video_artifact_paths
from pastor_transcript_extractor.models import VideoStatus
from pastor_transcript_extractor.storage import Database


@dataclass(frozen=True, slots=True)
class ReviewRunResult:
    approved_text_path: Path | None
    review_json_path: Path | None


def _format_segment_line(segment: object) -> str:
    label = getattr(segment, "label").value
    start_seconds = getattr(segment, "start_seconds")
    end_seconds = getattr(segment, "end_seconds")
    text = getattr(segment, "text")
    return f"[{start_seconds!s} - {end_seconds!s}] {label}: {text}"


def review_video(
    database: Database,
    app_paths: AppPaths,
    video_id: int,
    approve: bool = False,
    review_notes: str | None = None,
    edit: bool = False,
) -> ReviewRunResult:
    video = database.get_video_by_id(video_id)
    if video is None:
        raise ValueError(f"Unknown video id: {video_id}")

    pastor = database.get_pastor_by_id(video.pastor_id) if video.pastor_id is not None else None
    if pastor is None:
        raise ValueError(f"Video {video_id} is missing a linked pastor")

    extraction_result = database.get_latest_extraction_result_for_video(video.id)
    if extraction_result is None:
        raise ValueError(f"Video {video_id} has no extraction result to review")

    review_result = database.get_latest_review_result_for_video(video.id)
    if not approve:
        if review_result is not None:
            approved_path = Path(review_result.approved_text_path)
            return ReviewRunResult(approved_text_path=approved_path, review_json_path=approved_path.with_suffix(".json"))
        return ReviewRunResult(approved_text_path=None, review_json_path=None)

    segments = database.list_transcript_segments(video.id)
    video_paths = build_video_artifact_paths(app_paths, pastor.slug, video.youtube_video_id)
    video_paths.review.mkdir(parents=True, exist_ok=True)

    approved_text_path = video_paths.review / "approved.md"
    proposed_path = Path(extraction_result.proposed_text_path)
    if not proposed_path.exists():
        raise FileNotFoundError(f"Missing proposed transcript at {proposed_path}")
    shutil.copyfile(proposed_path, approved_text_path)

    if edit:
        editor = shutil.which("code") or shutil.which("nano") or shutil.which("vim")
        if editor is None:
            raise RuntimeError("No editor found on PATH")
        subprocess.run([editor, str(approved_text_path)], check=True)

    review_json_path = approved_text_path.with_suffix(".json")
    review_json = {
        "video_id": video.id,
        "youtube_video_id": video.youtube_video_id,
        "pastor_slug": pastor.slug,
        "extraction_result_id": extraction_result.id,
        "approved_text_path": str(approved_text_path),
        "segment_count": len(segments),
        "review_notes": review_notes,
    }
    review_json_path.write_text(json.dumps(review_json, indent=2, sort_keys=True), encoding="utf-8")

    database.add_review_result(
        video_id=video.id,
        extraction_result_id=extraction_result.id,
        approved_text_path=str(approved_text_path),
        review_notes=review_notes,
    )
    database.update_video_status(video.id, VideoStatus.APPROVED)
    return ReviewRunResult(approved_text_path=approved_text_path, review_json_path=review_json_path)
