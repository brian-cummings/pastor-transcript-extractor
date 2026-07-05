from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pastor_transcript_extractor.config import AppPaths, build_pastor_paths
from pastor_transcript_extractor.models import Video, VideoStatus
from pastor_transcript_extractor.storage import Database


@dataclass(frozen=True, slots=True)
class PastorReviewMarkdownResult:
    export_path: Path
    manifest_path: Path
    video_count: int
    skipped_count: int


def _sort_videos_for_review(videos: list[Video]) -> list[Video]:
    def sort_key(video: Video) -> tuple[int, datetime, int]:
        published = video.published_at or datetime.min.replace(tzinfo=timezone.utc)
        return (1 if video.published_at is not None else 0, published, video.id)

    return sorted(videos, key=sort_key, reverse=True)


def _build_pastor_review_markdown(
    pastor_slug: str,
    pastor_name: str,
    generated_at: str,
    sections: list[str],
) -> str:
    lines = [
        "---",
        f"pastor: {pastor_slug}",
        f"pastor_name: {pastor_name}",
        f"generated_at: {generated_at}",
        f"video_count: {len(sections)}",
        "---",
        "",
        f"# {pastor_name} Review",
        "",
        "Regenerate this file after excluding videos or adding newly processed source material.",
        "",
    ]
    if not sections:
        lines.extend(["No extracted videos are available for this pastor.", ""])
        return "\n".join(lines)

    lines.extend(sections)
    if lines[-1] != "":
        lines.append("")
    return "\n".join(lines)


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return loaded if isinstance(loaded, dict) else None


def export_pastor_review_markdown(database: Database, app_paths: AppPaths, pastor_slug: str) -> PastorReviewMarkdownResult:
    pastor = database.get_pastor_by_slug(pastor_slug)
    if pastor is None:
        raise ValueError(f"Unknown pastor slug: {pastor_slug}")

    pastor_paths = build_pastor_paths(app_paths, pastor.slug)
    pastor_paths.exports.mkdir(parents=True, exist_ok=True)

    candidate_videos = [
        video
        for video in database.list_videos()
        if video.pastor_id == pastor.id and database.get_latest_extraction_result_for_video(video.id) is not None
    ]
    videos = _sort_videos_for_review(candidate_videos)

    sections: list[str] = []
    skipped_count = 0
    manifest_videos: list[dict[str, object]] = []
    for video in videos:
        extraction_result = database.get_latest_extraction_result_for_video(video.id)
        if extraction_result is None:
            skipped_count += 1
            continue
        proposed_path = Path(extraction_result.proposed_text_path)
        proposed_json_path = Path(extraction_result.proposed_json_path) if extraction_result.proposed_json_path else None
        if not proposed_path.exists():
            skipped_count += 1
            continue

        proposed_text = proposed_path.read_text(encoding="utf-8").rstrip()
        proposed_json = _load_json(proposed_json_path) if proposed_json_path is not None else None
        transcript_source = None
        if proposed_json is not None and isinstance(proposed_json.get("transcript_source"), str):
            transcript_source = str(proposed_json["transcript_source"])
        published_text = video.published_at.date().isoformat() if video.published_at is not None else "undated"
        sections.extend(
            [
                f"## {published_text} - {video.title}",
                "",
                f"- Video ID: {video.youtube_video_id}",
                f"- Source: {video.url}",
                f"- Transcript Source: {transcript_source or 'unknown'}",
                f"- Status: {video.status.value}",
                f"- Proposed Markdown: {proposed_path}",
                "",
                proposed_text,
                "",
                "---",
                "",
            ]
        )
        manifest_videos.append(
            {
                "video_id": video.id,
                "youtube_video_id": video.youtube_video_id,
                "title": video.title,
                "published_at": video.published_at.isoformat() if video.published_at is not None else None,
                "status": video.status.value,
                "source_url": video.url,
                "transcript_source": transcript_source,
                "proposed_text_path": str(proposed_path),
            }
        )
        database.update_video_status(video.id, VideoStatus.EXPORTED)

    generated_at = datetime.now(timezone.utc).isoformat()
    export_path = pastor_paths.exports / "review.md"
    manifest_path = pastor_paths.exports / "review.json"
    export_path.write_text(
        _build_pastor_review_markdown(
            pastor_slug=pastor.slug,
            pastor_name=pastor.display_name,
            generated_at=generated_at,
            sections=sections,
        ),
        encoding="utf-8",
    )
    manifest_path.write_text(
        json.dumps(
            {
                "pastor_slug": pastor.slug,
                "pastor_name": pastor.display_name,
                "generated_at": generated_at,
                "video_count": len(manifest_videos),
                "skipped_count": skipped_count,
                "videos": manifest_videos,
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return PastorReviewMarkdownResult(
        export_path=export_path,
        manifest_path=manifest_path,
        video_count=len(manifest_videos),
        skipped_count=skipped_count,
    )
