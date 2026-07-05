from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pastor_transcript_extractor.config import AppPaths, build_video_artifact_paths
from pastor_transcript_extractor.models import ExtractionResult, TranscriptArtifact, TranscriptSegment, TranscriptSegmentLabel, TranscriptSourceKind, VideoStatus
from pastor_transcript_extractor.sermon_detection import GuestSpeakerFlags, SermonWindowResult, detect_guest_speaker_flags, detect_sermon_window
from pastor_transcript_extractor.segmentation import SegmentDraft, segment_transcript
from pastor_transcript_extractor.storage import Database


@dataclass(frozen=True, slots=True)
class ExtractionRunResult:
    extraction_result: ExtractionResult
    segments_path: Path
    proposed_text_path: Path
    proposed_json_path: Path
    segment_count: int


def _load_json(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.exists():
        return None
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return loaded if isinstance(loaded, dict) else None


def _read_text(path: Path | None) -> str:
    if path is None or not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def _load_window_override(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    payload = _load_json(path)
    if payload is None:
        return None, None if not path.exists() else "invalid override ignored: could not parse JSON object"
    start_seconds = payload.get("start_seconds")
    end_seconds = payload.get("end_seconds")
    if not isinstance(start_seconds, (int, float)) or not isinstance(end_seconds, (int, float)):
        return None, "invalid override ignored: start_seconds and end_seconds must be numbers"
    start = float(start_seconds)
    end = float(end_seconds)
    if end <= start:
        return None, "invalid override ignored: end_seconds must be greater than start_seconds"
    notes = payload.get("notes")
    updated_at = payload.get("updated_at")
    updated_by = payload.get("updated_by")
    if notes is not None and not isinstance(notes, str):
        return None, "invalid override ignored: notes must be a string when provided"
    if updated_at is not None and not isinstance(updated_at, str):
        return None, "invalid override ignored: updated_at must be a string when provided"
    if updated_by is not None and not isinstance(updated_by, str):
        return None, "invalid override ignored: updated_by must be a string when provided"
    return {
        "start_seconds": start,
        "end_seconds": end,
        "notes": notes,
        "updated_at": updated_at,
        "updated_by": updated_by,
    }, None


def _segment_to_storage(
    database: Database,
    video_id: int,
    artifact: TranscriptArtifact,
    draft: SegmentDraft,
) -> TranscriptSegment:
    return database.add_transcript_segment(
        video_id=video_id,
        artifact_id=artifact.id,
        start_seconds=draft.start_seconds,
        end_seconds=draft.end_seconds,
        text=draft.text,
        label=draft.label,
        speaker_hint=draft.speaker_hint,
        confidence=draft.confidence,
    )


def _format_timestamp(seconds: float | None) -> str:
    if seconds is None:
        return "--:--"
    total_seconds = max(0, int(seconds))
    minutes, remaining_seconds = divmod(total_seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:d}:{minutes:02d}:{remaining_seconds:02d}"
    return f"{minutes:02d}:{remaining_seconds:02d}"


def _transcript_duration(drafts: list[SegmentDraft]) -> float | None:
    timed_ends = [draft.end_seconds for draft in drafts if draft.end_seconds is not None]
    return max(timed_ends) if timed_ends else None


def _effective_sermon_window(
    detected_window: SermonWindowResult,
    override: dict[str, Any] | None,
    override_error: str | None,
) -> dict[str, Any]:
    reasons = list(detected_window.reasons)
    source = "detected"
    start_seconds = detected_window.start_seconds
    end_seconds = detected_window.end_seconds
    if override_error:
        reasons.append(override_error)
    if override is not None:
        source = "override"
        start_seconds = float(override["start_seconds"])
        end_seconds = float(override["end_seconds"])
        reasons = ["manual review override applied"]
        if override.get("notes"):
            reasons.append(str(override["notes"]))
    return {
        "start_seconds": start_seconds,
        "end_seconds": end_seconds,
        "confidence": detected_window.confidence,
        "reasons": reasons,
        "method": detected_window.method,
        "source": source,
        "included_segment_indexes": detected_window.included_segment_indexes,
        "excluded_segment_indexes": detected_window.excluded_segment_indexes,
    }


def _build_proposed_markdown(
    title: str,
    url: str,
    pastor_slug: str,
    transcript_source: TranscriptSourceKind,
    sermon_window: dict[str, Any],
    guest_flags: GuestSpeakerFlags,
    drafts: list[SegmentDraft],
) -> str:
    body = "\n\n".join(draft.text for draft in drafts)
    if not body.strip():
        body = "(no transcript text available)"

    duration = _transcript_duration(drafts)
    window_start = _format_timestamp(sermon_window.get("start_seconds"))
    window_end = _format_timestamp(sermon_window.get("end_seconds"))
    window_reasons = "; ".join(sermon_window.get("reasons", [])) or "none"
    lines = [
        f"# {title}",
        "",
        f"- Pastor: {pastor_slug}",
        f"- Source: {url}",
        f"- Transcript Source: {transcript_source.value}",
        f"- Duration: {_format_timestamp(duration)}" if duration is not None else "- Duration: unknown",
        f"- Likely Sermon Window: {window_start} - {window_end}",
        f"- Window Confidence: {sermon_window.get('confidence', 0.0):.2f}",
        f"- Window Source: {sermon_window.get('source', 'detected')}",
        f"- Window Reasons: {window_reasons}",
        f"- Guest Speaker Suspected: {'yes' if guest_flags.suspected else 'no'}",
        (
            f"- Guest Speaker Reasons: {'; '.join(guest_flags.reasons)}"
            if guest_flags.reasons
            else "- Guest Speaker Reasons: none"
        ),
        "",
        "## Proposed Transcript",
        "",
        body,
        "",
        "## Segment Notes",
        "",
    ]
    for draft in drafts:
        lines.append(
            f"- [{_format_timestamp(draft.start_seconds)} - {_format_timestamp(draft.end_seconds)}] "
            f"{draft.label.value}: {draft.text}"
        )
    lines.append("")
    return "\n".join(lines)


def extract_video(database: Database, app_paths: AppPaths, video_id: int) -> ExtractionRunResult:
    video = database.get_video_by_id(video_id)
    if video is None:
        raise ValueError(f"Unknown video id: {video_id}")

    pastor = database.get_pastor_by_id(video.pastor_id) if video.pastor_id is not None else None
    if pastor is None:
        raise ValueError(f"Video {video_id} is missing a linked pastor")

    transcript_artifacts = database.list_transcript_artifacts_for_video(video.id)
    if not transcript_artifacts:
        raise ValueError(f"Video {video_id} has no transcript artifact to extract from")
    transcript_artifact = next(
        (artifact for artifact in reversed(transcript_artifacts) if artifact.source_kind == TranscriptSourceKind.CAPTIONS),
        transcript_artifacts[-1],
    )

    video_paths = build_video_artifact_paths(app_paths, pastor.slug, video.youtube_video_id)
    video_paths.extracted.mkdir(parents=True, exist_ok=True)
    database.delete_transcript_segments_for_video(video.id)

    raw_json = _load_json(Path(transcript_artifact.raw_json_path) if transcript_artifact.raw_json_path else None)
    raw_text = _read_text(Path(transcript_artifact.raw_text_path) if transcript_artifact.raw_text_path else None)
    if not raw_text and raw_json is not None and isinstance(raw_json.get("text"), str):
        raw_text = str(raw_json["text"])

    drafts = segment_transcript(raw_text, raw_json)
    persisted_segments = [_segment_to_storage(database, video.id, transcript_artifact, draft) for draft in drafts]
    detected_window = detect_sermon_window(drafts)
    override_path = video_paths.review / "window_override.json"
    override, override_error = _load_window_override(override_path)
    sermon_window = _effective_sermon_window(detected_window, override, override_error)
    guest_flags = detect_guest_speaker_flags(
        video_title=video.title,
        drafts=drafts,
        pastor_name=pastor.display_name,
        sermon_window=detected_window,
    )

    proposed_text = _build_proposed_markdown(
        video.title,
        video.url,
        pastor.slug,
        transcript_artifact.source_kind,
        sermon_window,
        guest_flags,
        drafts,
    )
    proposed_text_path = video_paths.extracted / "proposed.md"
    proposed_json_path = video_paths.extracted / "proposed.json"
    segments_path = video_paths.extracted / "segments.json"

    proposed_text_path.write_text(proposed_text, encoding="utf-8")
    proposed_json = {
        "video_id": video.id,
        "youtube_video_id": video.youtube_video_id,
        "pastor_slug": pastor.slug,
        "source_url": video.url,
        "transcript_source": transcript_artifact.source_kind.value,
        "sermon_window": sermon_window,
        "guest_speaker_suspected": guest_flags.suspected,
        "guest_name_candidates": guest_flags.name_candidates,
        "guest_signal_reasons": guest_flags.reasons,
        "segment_count": len(persisted_segments),
        "segments": [
            {
                "start_seconds": segment.start_seconds,
                "end_seconds": segment.end_seconds,
                "text": segment.text,
                "speaker_hint": segment.speaker_hint,
                "label": segment.label.value,
                "confidence": segment.confidence,
            }
            for segment in persisted_segments
        ],
    }
    proposed_json_path.write_text(json.dumps(proposed_json, indent=2, sort_keys=True), encoding="utf-8")
    segments_path.write_text(json.dumps(proposed_json["segments"], indent=2, sort_keys=True), encoding="utf-8")

    extraction_result = database.add_extraction_result(
        video_id=video.id,
        version=1,
        proposed_text_path=str(proposed_text_path),
        proposed_json_path=str(proposed_json_path),
    )
    database.update_video_status(video.id, VideoStatus.EXTRACTED)
    return ExtractionRunResult(
        extraction_result=extraction_result,
        segments_path=segments_path,
        proposed_text_path=proposed_text_path,
        proposed_json_path=proposed_json_path,
        segment_count=len(persisted_segments),
    )
