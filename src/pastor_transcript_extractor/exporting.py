from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

from pastor_transcript_extractor.config import AppPaths
from pastor_transcript_extractor.models import VideoStatus
from pastor_transcript_extractor.storage import Database


@dataclass(frozen=True, slots=True)
class ExportRunResult:
    export_path: Path
    review_path: Path


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value).strip("-").lower()
    return slug or "untitled"


def export_video(database: Database, app_paths: AppPaths, video_id: int) -> ExportRunResult:
    video = database.get_video_by_id(video_id)
    if video is None:
        raise ValueError(f"Unknown video id: {video_id}")

    pastor = database.get_pastor_by_id(video.pastor_id) if video.pastor_id is not None else None
    if pastor is None:
        raise ValueError(f"Video {video_id} is missing a linked pastor")

    review_result = database.get_latest_review_result_for_video(video.id)
    if review_result is None:
        raise ValueError(f"Video {video_id} has not been approved for export")

    approved_path = Path(review_result.approved_text_path)
    if not approved_path.exists():
        raise FileNotFoundError(f"Approved transcript is missing at {approved_path}")

    export_dir = app_paths.exports / pastor.slug
    export_dir.mkdir(parents=True, exist_ok=True)
    published_prefix = video.published_at.date().isoformat() if video.published_at is not None else "undated"
    title_slug = _slugify(video.title)
    export_path = export_dir / f"{published_prefix}-{title_slug}-{video.youtube_video_id}.md"

    approved_text = approved_path.read_text(encoding="utf-8")
    frontmatter = [
        "---",
        f"pastor: {pastor.slug}",
        f"pastor_name: {pastor.display_name}",
        f"title: {video.title}",
        f"youtube_video_id: {video.youtube_video_id}",
        f"source_url: {video.url}",
        f"reviewed_at: {review_result.reviewed_at.isoformat()}",
        f"review_result_id: {review_result.id}",
        "---",
        "",
    ]
    export_path.write_text("\n".join(frontmatter) + approved_text.rstrip() + "\n", encoding="utf-8")
    database.update_video_status(video.id, VideoStatus.EXPORTED)
    return ExportRunResult(export_path=export_path, review_path=approved_path)
