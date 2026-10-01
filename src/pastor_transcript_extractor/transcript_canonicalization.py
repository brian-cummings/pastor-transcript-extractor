from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from pastor_transcript_extractor.caption_normalization import (
    NORMALIZER_VERSION,
    normalize_caption_fragments,
)
from pastor_transcript_extractor.models import TranscriptArtifact
from pastor_transcript_extractor.segmentation import SegmentDraft, segment_transcript
from pastor_transcript_extractor.storage import Database


CANONICAL_TRANSCRIPT_VERSION = f"canonical-transcript-v1+{NORMALIZER_VERSION}"


def _read_json(path: str | None) -> dict[str, Any] | None:
    if not path:
        return None
    candidate = Path(path)
    if not candidate.exists():
        return None
    try:
        payload = json.loads(candidate.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _read_text(path: str | None) -> str:
    if not path:
        return ""
    candidate = Path(path)
    if not candidate.exists():
        return ""
    return candidate.read_text(encoding="utf-8")


def _source_hash(raw_json: dict[str, Any] | None, raw_text: str) -> str:
    digest = hashlib.sha256()
    digest.update(
        json.dumps(raw_json, sort_keys=True, separators=(",", ":"), default=str).encode(
            "utf-8"
        )
        if raw_json is not None
        else b"null"
    )
    digest.update(b"\0")
    digest.update(raw_text.encode("utf-8"))
    return digest.hexdigest()


def _canonical_segments(
    drafts: list[SegmentDraft],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    normalized = normalize_caption_fragments(
        (index, draft.text) for index, draft in enumerate(drafts)
    )
    segments: list[dict[str, Any]] = []
    for unit in normalized.units:
        sources = [drafts[index] for index in unit.source_segment_indexes]
        starts = [item.start_seconds for item in sources if item.start_seconds is not None]
        ends = [item.end_seconds for item in sources if item.end_seconds is not None]
        segments.append(
            {
                "start": min(starts) if starts else None,
                "end": max(ends) if ends else None,
                "text": unit.text,
                "source_segment_indexes": list(unit.source_segment_indexes),
            }
        )
    return segments, dict(normalized.diagnostics)


def materialize_canonical_transcript(
    database: Database,
    source: TranscriptArtifact,
) -> TranscriptArtifact:
    """Persist the canonical transcript that supersedes one source artifact."""
    if source.artifact_kind == "canonical":
        return source
    raw_json = _read_json(source.raw_json_path)
    raw_text = _read_text(source.raw_text_path)
    if not raw_text and raw_json is not None and isinstance(raw_json.get("text"), str):
        raw_text = str(raw_json["text"])
    drafts = segment_transcript(raw_text, raw_json)
    input_hash = _source_hash(raw_json, raw_text)
    existing = database.get_canonical_transcript_artifact(
        source.id,
        CANONICAL_TRANSCRIPT_VERSION,
        input_hash,
    )
    if existing is not None:
        return existing

    segments, diagnostics = _canonical_segments(drafts)
    canonical_text = "\n".join(str(item["text"]) for item in segments)
    payload: dict[str, Any] = {
        "schema_version": 1,
        "transformation_version": CANONICAL_TRANSCRIPT_VERSION,
        "parent_transcript_artifact_id": source.id,
        "source_kind": source.source_kind.value,
        "input_content_sha256": input_hash,
        "normalization": diagnostics,
        "text": canonical_text,
        "segments": segments,
    }
    encoded = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")
    content_hash = hashlib.sha256(encoded).hexdigest()
    source_artifact_path = source.raw_json_path or source.raw_text_path
    if not source_artifact_path:
        raise ValueError(
            f"Transcript artifact {source.id} has no JSON or text path"
        )
    source_path = Path(source_artifact_path)
    canonical_dir = source_path.parent / "canonical"
    canonical_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{CANONICAL_TRANSCRIPT_VERSION}-{content_hash[:16]}"
    json_path = canonical_dir / f"{stem}.json"
    text_path = canonical_dir / f"{stem}.txt"
    if not json_path.exists():
        json_path.write_bytes(encoded)
    if not text_path.exists():
        text_path.write_text(canonical_text, encoding="utf-8")

    return database.add_transcript_artifact(
        video_id=source.video_id,
        source_kind=source.source_kind,
        audio_path=source.audio_path,
        raw_json_path=str(json_path),
        raw_text_path=str(text_path),
        parent_transcript_artifact_id=source.id,
        artifact_kind="canonical",
        transformation_version=CANONICAL_TRANSCRIPT_VERSION,
        input_content_sha256=input_hash,
        content_sha256=content_hash,
    )


def ensure_canonical_transcript_for_video(
    database: Database,
    video_id: int,
) -> TranscriptArtifact:
    source = database.get_preferred_source_transcript_artifact_for_video(video_id)
    if source is None:
        effective = database.get_latest_transcript_artifact_for_video(video_id)
        if effective is not None and effective.artifact_kind == "canonical":
            return effective
        raise ValueError(f"Video {video_id} has no source transcript artifact")
    return materialize_canonical_transcript(database, source)
