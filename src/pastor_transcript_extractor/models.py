from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from typing import Optional


class SourceType(StrEnum):
    VIDEO = "video"
    PLAYLIST = "playlist"
    CHANNEL = "channel"


class VideoStatus(StrEnum):
    QUEUED = "queued"
    DISCOVERED = "discovered"
    TRANSCRIPT_FETCHED = "transcript_fetched"
    TRANSCRIBING_LOCAL = "transcribing_local"
    TRANSCRIBED_LOCAL = "transcribed_local"
    EXTRACTED = "extracted"
    NEEDS_REVIEW = "needs_review"
    APPROVED = "approved"
    EXPORTED = "exported"
    FAILED = "failed"


class TranscriptSourceKind(StrEnum):
    CAPTIONS = "captions"
    LOCAL_ASR = "local_asr"


class TranscriptSegmentLabel(StrEnum):
    UNKNOWN = "unknown"
    SERMON = "sermon"
    MUSIC = "music"
    ANNOUNCEMENTS = "announcements"
    PRAYER = "prayer"
    READING = "reading"
    OTHER = "other"


@dataclass(slots=True)
class Source:
    id: int
    pastor_id: Optional[int]
    url: str
    source_type: SourceType
    added_at: datetime
    notes: Optional[str] = None


@dataclass(slots=True)
class Video:
    id: int
    source_id: int
    pastor_id: Optional[int]
    youtube_video_id: str
    title: str
    url: str
    channel_name: Optional[str]
    published_at: Optional[datetime]
    duration_seconds: Optional[int]
    status: VideoStatus
    failure_reason: Optional[str] = None


@dataclass(slots=True)
class Pastor:
    id: int
    slug: str
    display_name: str
    added_at: datetime
    notes: Optional[str] = None


@dataclass(slots=True)
class TranscriptArtifact:
    id: int
    video_id: int
    source_kind: TranscriptSourceKind
    raw_json_path: Optional[str]
    raw_text_path: Optional[str]
    audio_path: Optional[str]
    created_at: datetime


@dataclass(slots=True)
class TranscriptSegment:
    id: Optional[int]
    video_id: int
    artifact_id: int
    start_seconds: Optional[float]
    end_seconds: Optional[float]
    text: str
    speaker_hint: Optional[str]
    label: TranscriptSegmentLabel
    confidence: Optional[float]


@dataclass(slots=True)
class ExtractionResult:
    id: int
    video_id: int
    version: int
    proposed_text_path: str
    proposed_json_path: Optional[str]
    notes: Optional[str]
    created_at: datetime


@dataclass(slots=True)
class ReviewResult:
    id: int
    video_id: int
    extraction_result_id: int
    approved_text_path: str
    reviewed_at: datetime
    review_notes: Optional[str] = None


@dataclass(slots=True)
class ExcludedVideo:
    id: int
    pastor_id: Optional[int]
    source_id: Optional[int]
    youtube_video_id: str
    title: str
    url: str
    excluded_at: datetime
    notes: Optional[str] = None


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    return datetime.fromisoformat(text)
