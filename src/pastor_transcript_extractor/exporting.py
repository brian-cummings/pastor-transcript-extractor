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


def _format_window(window: dict[str, Any] | None) -> str:
    if not isinstance(window, dict):
        return "unknown"
    start_seconds = window.get("start_seconds")
    end_seconds = window.get("end_seconds")
    if not isinstance(start_seconds, (int, float)) or not isinstance(end_seconds, (int, float)):
        return "unknown"

    def format_timestamp(seconds: float) -> str:
        total_seconds = max(0, int(seconds))
        minutes, remaining_seconds = divmod(total_seconds, 60)
        hours, minutes = divmod(minutes, 60)
        if hours:
            return f"{hours:d}:{minutes:02d}:{remaining_seconds:02d}"
        return f"{minutes:02d}:{remaining_seconds:02d}"

    return f"{format_timestamp(float(start_seconds))} - {format_timestamp(float(end_seconds))}"


def _segment_is_within_window(segment: dict[str, Any], sermon_window: dict[str, Any]) -> bool:
    start_seconds = sermon_window.get("start_seconds")
    end_seconds = sermon_window.get("end_seconds")
    segment_start = segment.get("start_seconds")
    segment_end = segment.get("end_seconds")
    if not isinstance(start_seconds, (int, float)) or not isinstance(end_seconds, (int, float)):
        return False
    if not isinstance(segment_start, (int, float)) or not isinstance(segment_end, (int, float)):
        return False
    return float(segment_end) > float(start_seconds) and float(segment_start) < float(end_seconds)


def _window_segments(segments: list[dict[str, Any]], sermon_window: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(sermon_window, dict):
        return []
    in_window = [segment for segment in segments if isinstance(segment, dict) and _segment_is_within_window(segment, sermon_window)]
    if in_window:
        return in_window
    included_indexes_raw = sermon_window.get("included_segment_indexes")
    if not isinstance(included_indexes_raw, list):
        return []
    included_indexes = {index for index in included_indexes_raw if isinstance(index, int)}
    return [
        segment
        for index, segment in enumerate(segments)
        if index in included_indexes and isinstance(segment, dict)
    ]


def _build_review_transcript_excerpt(
    proposed_json: dict[str, Any] | None,
    fallback_text: str,
) -> str:
    if proposed_json is None:
        return fallback_text
    segments = proposed_json.get("segments")
    sermon_window = proposed_json.get("sermon_window")
    if not isinstance(segments, list) or not isinstance(sermon_window, dict):
        return fallback_text

    excerpt_parts = [
        str(segment.get("text")).strip()
        for segment in _window_segments([segment for segment in segments if isinstance(segment, dict)], sermon_window)
        if isinstance(segment.get("text"), str) and str(segment.get("text")).strip()
    ]

    if excerpt_parts:
        return "\n\n".join(excerpt_parts)
    return fallback_text


def _build_review_sections_for_videos(
    database: Database,
    videos: list[Video],
) -> tuple[list[str], int, list[dict[str, object]]]:
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
        review_excerpt = _build_review_transcript_excerpt(proposed_json, proposed_text)
        transcript_source = None
        sermon_window = None
        guest_speaker_suspected = False
        guest_name_candidates: list[str] = []
        guest_signal_reasons: list[str] = []
        if proposed_json is not None and isinstance(proposed_json.get("transcript_source"), str):
            transcript_source = str(proposed_json["transcript_source"])
        if proposed_json is not None and isinstance(proposed_json.get("sermon_window"), dict):
            sermon_window = dict(proposed_json["sermon_window"])
        if proposed_json is not None and isinstance(proposed_json.get("guest_speaker_suspected"), bool):
            guest_speaker_suspected = bool(proposed_json["guest_speaker_suspected"])
        if proposed_json is not None and isinstance(proposed_json.get("guest_name_candidates"), list):
            guest_name_candidates = [str(candidate) for candidate in proposed_json["guest_name_candidates"]]
        if proposed_json is not None and isinstance(proposed_json.get("guest_signal_reasons"), list):
            guest_signal_reasons = [str(reason) for reason in proposed_json["guest_signal_reasons"]]
        published_text = video.published_at.date().isoformat() if video.published_at is not None else "undated"
        section_lines = [
            f"## {published_text} - {video.title}",
            "",
        ]
        section_lines.extend(
            [
                f"- Video ID: {video.youtube_video_id}",
                f"- Source: {video.url}",
                f"- Transcript Source: {transcript_source or 'unknown'}",
                f"- Likely Sermon Window: {_format_window(sermon_window)}",
                (
                    f"- Sermon Window Source: {sermon_window.get('source', 'detected')}"
                    if isinstance(sermon_window, dict)
                    else "- Sermon Window Source: unknown"
                ),
                (
                    f"- Suspicious Boundary: {'yes' if sermon_window.get('suspicious_boundary') else 'no'}"
                    if isinstance(sermon_window, dict)
                    else "- Suspicious Boundary: unknown"
                ),
                (
                    f"- Suspicious Boundary Reasons: {'; '.join(sermon_window.get('suspicious_boundary_reasons', []))}"
                    if isinstance(sermon_window, dict) and sermon_window.get("suspicious_boundary_reasons")
                    else "- Suspicious Boundary Reasons: none"
                ),
                f"- Guest Speaker Suspected: {'yes' if guest_speaker_suspected else 'no'}",
                (
                    f"- Guest Signal Reasons: {'; '.join(guest_signal_reasons)}"
                    if guest_signal_reasons
                    else "- Guest Signal Reasons: none"
                ),
                f"- Status: {video.status.value}",
                f"- Proposed Markdown: {proposed_path}",
                "",
                "## Sermon Review Excerpt",
                "",
                review_excerpt.rstrip(),
                "",
                "---",
                "",
            ]
        )
        sections.extend(section_lines)
        manifest_videos.append(
            {
                "video_id": video.id,
                "youtube_video_id": video.youtube_video_id,
                "title": video.title,
                "published_at": video.published_at.isoformat() if video.published_at is not None else None,
                "status": video.status.value,
                "source_url": video.url,
                "transcript_source": transcript_source,
                "sermon_window": sermon_window,
                "guest_speaker_suspected": guest_speaker_suspected,
                "guest_name_candidates": guest_name_candidates,
                "guest_signal_reasons": guest_signal_reasons,
                "proposed_text_path": str(proposed_path),
            }
        )
        database.update_video_status(video.id, VideoStatus.EXPORTED)

    return sections, skipped_count, manifest_videos


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
    sections, skipped_count, manifest_videos = _build_review_sections_for_videos(
        database,
        videos,
    )

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
