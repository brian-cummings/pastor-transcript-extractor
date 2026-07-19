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


class IdentityState(StrEnum):
    TARGET_CONFIRMED = "target_confirmed"
    TARGET_PLAUSIBLE = "target_plausible"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    CONFLICTING_EVIDENCE = "conflicting_evidence"
    NON_TARGET_CONFIRMED = "non_target_confirmed"
    MIXED_OR_COMPOUND = "mixed_or_compound"
    PROFILE_UNAVAILABLE = "profile_unavailable"
    ANALYSIS_FAILED = "analysis_failed"


class IdentityAction(StrEnum):
    ACCEPT = "accept"
    REVIEW = "review"
    REJECT_NON_TARGET = "reject_non_target"
    REJECT_COMPOUND = "reject_compound"
    RETRY = "retry"


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
class MediaArtifact:
    id: int
    video_id: int
    parent_media_artifact_id: Optional[int]
    artifact_kind: str
    provenance_kind: str
    artifact_path: str
    manifest_path: str
    content_sha256: str
    byte_size: int
    duration_seconds: Optional[float]
    format_name: Optional[str]
    sample_rate_hz: Optional[int]
    channel_count: Optional[int]
    acquisition_tool: str
    acquisition_tool_version: str
    input_fingerprint: str
    created_at: datetime


@dataclass(slots=True)
class MediaAcquisitionAttempt:
    id: int
    video_id: int
    target_kind: str
    outcome: str
    reason_code: str
    detail: Optional[str]
    media_artifact_id: Optional[int]
    service_version: str
    input_fingerprint: str
    created_at: datetime


@dataclass(slots=True)
class MediaArchiveDestination:
    id: int
    archive_root: str
    active: bool
    created_at: datetime
    updated_at: datetime


@dataclass(slots=True)
class MediaArchiveEntry:
    id: int
    media_artifact_id: int
    destination_id: int
    source_path: str
    archive_path: str
    content_sha256: str
    byte_size: int
    status: str
    archived_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime


@dataclass(slots=True)
class MediaArchiveAttempt:
    id: int
    archive_entry_id: int
    outcome: str
    detail: Optional[str]
    attempted_at: datetime


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


@dataclass(slots=True)
class MetadataArtifact:
    id: int
    video_id: int
    schema_version: int
    source_kind: str
    artifact_path: str
    content_sha256: str
    extractor_version: str
    created_at: datetime


@dataclass(slots=True)
class IdentityEvidence:
    id: int
    video_id: int
    target_pastor_id: int
    evidence_type: str
    source_family: str
    polarity: str
    strength: str
    scope: str
    artifact_path: str
    extractor_version: str
    created_at: datetime


@dataclass(slots=True)
class IdentityAssessment:
    id: int
    video_id: int
    target_pastor_id: int
    extraction_result_id: int
    state: IdentityState
    recommended_action: IdentityAction
    shadow_mode: bool
    policy_version: str
    evidence_ledger_path: str
    assessment_path: str
    input_fingerprint: str
    created_at: datetime


@dataclass(slots=True)
class SpeakerProfile:
    id: int
    stable_key: str
    display_label: Optional[str]
    lifecycle_state: str
    created_reason: str
    created_at: datetime


@dataclass(slots=True)
class SpeakerObservation:
    id: int
    video_id: int
    extraction_result_id: int
    role: str
    multiplicity_state: str
    start_seconds: float
    end_seconds: float
    artifact_path: str
    content_sha256: str
    extractor_version: str
    input_fingerprint: str
    created_at: datetime


@dataclass(slots=True)
class SpeakerNameClaim:
    id: int
    video_id: int
    observation_id: Optional[int]
    display_name: str
    normalized_name: str
    claim_kind: str
    channel: str
    explicit_speaker_attribution: bool
    correlation_group_id: str
    provenance_json: str
    artifact_path: str
    claim_fingerprint: str
    extractor_version: str
    created_at: datetime


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    return datetime.fromisoformat(text)
