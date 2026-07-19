from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from pastor_transcript_extractor.models import (
    ExcludedVideo,
    ExtractionResult,
    IdentityAction,
    IdentityAssessment,
    IdentityEvidence,
    IdentityState,
    MediaAcquisitionAttempt,
    MediaArtifact,
    MetadataArtifact,
    Pastor,
    SpeakerNameClaim,
    SpeakerObservation,
    SpeakerProfile,
    ReviewResult,
    Source,
    SourceType,
    TranscriptSegment,
    TranscriptArtifact,
    TranscriptSourceKind,
    TranscriptSegmentLabel,
    Video,
    VideoStatus,
    parse_datetime,
    utc_now,
)


SCHEMA = """
CREATE TABLE IF NOT EXISTS pastors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slug TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    added_at TEXT NOT NULL,
    notes TEXT NULL
);

CREATE TABLE IF NOT EXISTS sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pastor_id INTEGER NOT NULL,
    url TEXT NOT NULL UNIQUE,
    source_type TEXT NOT NULL,
    added_at TEXT NOT NULL,
    notes TEXT NULL,
    FOREIGN KEY(pastor_id) REFERENCES pastors(id)
);

CREATE TABLE IF NOT EXISTS source_import_refs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id INTEGER NOT NULL,
    pastor_id INTEGER NOT NULL,
    provider TEXT NOT NULL,
    external_entity_key TEXT NOT NULL,
    external_record_id TEXT NULL,
    imported_fingerprint TEXT NOT NULL,
    import_payload_json TEXT NOT NULL,
    external_updated_at TEXT NULL,
    imported_at TEXT NOT NULL,
    FOREIGN KEY(source_id) REFERENCES sources(id),
    FOREIGN KEY(pastor_id) REFERENCES pastors(id),
    UNIQUE(provider, external_entity_key)
);

CREATE TABLE IF NOT EXISTS videos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id INTEGER NOT NULL,
    pastor_id INTEGER NOT NULL,
    youtube_video_id TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    url TEXT NOT NULL,
    channel_name TEXT NULL,
    published_at TEXT NULL,
    duration_seconds INTEGER NULL,
    status TEXT NOT NULL,
    failure_reason TEXT NULL,
    FOREIGN KEY(source_id) REFERENCES sources(id),
    FOREIGN KEY(pastor_id) REFERENCES pastors(id)
);

CREATE TABLE IF NOT EXISTS transcript_artifacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id INTEGER NOT NULL,
    source_kind TEXT NOT NULL,
    raw_json_path TEXT NULL,
    raw_text_path TEXT NULL,
    audio_path TEXT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(video_id) REFERENCES videos(id)
);

CREATE TABLE IF NOT EXISTS media_artifacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id INTEGER NOT NULL,
    parent_media_artifact_id INTEGER NULL,
    artifact_kind TEXT NOT NULL CHECK(artifact_kind IN ('source_audio', 'normalized_audio')),
    provenance_kind TEXT NOT NULL CHECK(provenance_kind IN ('original_download', 'derived', 'reconstructed_existing')),
    artifact_path TEXT NOT NULL,
    manifest_path TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    byte_size INTEGER NOT NULL,
    duration_seconds REAL NULL,
    format_name TEXT NULL,
    sample_rate_hz INTEGER NULL,
    channel_count INTEGER NULL,
    acquisition_tool TEXT NOT NULL,
    acquisition_tool_version TEXT NOT NULL,
    input_fingerprint TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    FOREIGN KEY(video_id) REFERENCES videos(id),
    FOREIGN KEY(parent_media_artifact_id) REFERENCES media_artifacts(id)
);

CREATE TABLE IF NOT EXISTS media_acquisition_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id INTEGER NOT NULL,
    target_kind TEXT NOT NULL,
    outcome TEXT NOT NULL CHECK(outcome IN ('verified', 'unavailable', 'failed')),
    reason_code TEXT NOT NULL,
    detail TEXT NULL,
    media_artifact_id INTEGER NULL,
    service_version TEXT NOT NULL,
    input_fingerprint TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    FOREIGN KEY(video_id) REFERENCES videos(id),
    FOREIGN KEY(media_artifact_id) REFERENCES media_artifacts(id)
);

CREATE TABLE IF NOT EXISTS transcript_segments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id INTEGER NOT NULL,
    artifact_id INTEGER NOT NULL,
    start_seconds REAL NULL,
    end_seconds REAL NULL,
    text TEXT NOT NULL,
    speaker_hint TEXT NULL,
    label TEXT NOT NULL,
    confidence REAL NULL,
    FOREIGN KEY(video_id) REFERENCES videos(id),
    FOREIGN KEY(artifact_id) REFERENCES transcript_artifacts(id)
);

CREATE TABLE IF NOT EXISTS extraction_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id INTEGER NOT NULL,
    version INTEGER NOT NULL,
    proposed_text_path TEXT NOT NULL,
    proposed_json_path TEXT NULL,
    notes TEXT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(video_id) REFERENCES videos(id)
);

CREATE TABLE IF NOT EXISTS review_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id INTEGER NOT NULL,
    extraction_result_id INTEGER NOT NULL,
    approved_text_path TEXT NOT NULL,
    reviewed_at TEXT NOT NULL,
    review_notes TEXT NULL,
    FOREIGN KEY(video_id) REFERENCES videos(id),
    FOREIGN KEY(extraction_result_id) REFERENCES extraction_results(id)
);

CREATE TABLE IF NOT EXISTS excluded_videos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pastor_id INTEGER NULL,
    source_id INTEGER NULL,
    youtube_video_id TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    url TEXT NOT NULL,
    excluded_at TEXT NOT NULL,
    notes TEXT NULL
);

CREATE TABLE IF NOT EXISTS metadata_artifacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id INTEGER NOT NULL,
    schema_version INTEGER NOT NULL,
    source_kind TEXT NOT NULL,
    artifact_path TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    extractor_version TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(video_id) REFERENCES videos(id),
    UNIQUE(video_id, content_sha256, extractor_version)
);

CREATE TABLE IF NOT EXISTS identity_evidence (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id INTEGER NOT NULL,
    target_pastor_id INTEGER NOT NULL,
    evidence_type TEXT NOT NULL,
    source_family TEXT NOT NULL,
    polarity TEXT NOT NULL,
    strength TEXT NOT NULL,
    scope TEXT NOT NULL,
    artifact_path TEXT NOT NULL,
    extractor_version TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(video_id) REFERENCES videos(id),
    FOREIGN KEY(target_pastor_id) REFERENCES pastors(id)
);

CREATE TABLE IF NOT EXISTS identity_assessments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id INTEGER NOT NULL,
    target_pastor_id INTEGER NOT NULL,
    extraction_result_id INTEGER NOT NULL,
    state TEXT NOT NULL,
    recommended_action TEXT NOT NULL,
    shadow_mode INTEGER NOT NULL,
    policy_version TEXT NOT NULL,
    evidence_ledger_path TEXT NOT NULL,
    assessment_path TEXT NOT NULL,
    input_fingerprint TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    FOREIGN KEY(video_id) REFERENCES videos(id),
    FOREIGN KEY(target_pastor_id) REFERENCES pastors(id),
    FOREIGN KEY(extraction_result_id) REFERENCES extraction_results(id)
);

CREATE TABLE IF NOT EXISTS speaker_profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    stable_key TEXT NOT NULL UNIQUE,
    display_label TEXT NULL,
    lifecycle_state TEXT NOT NULL,
    created_reason TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pastor_speaker_bindings (
    pastor_id INTEGER PRIMARY KEY,
    profile_id INTEGER NOT NULL UNIQUE,
    binding_kind TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(pastor_id) REFERENCES pastors(id),
    FOREIGN KEY(profile_id) REFERENCES speaker_profiles(id)
);

CREATE TABLE IF NOT EXISTS speaker_observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id INTEGER NOT NULL,
    extraction_result_id INTEGER NOT NULL,
    role TEXT NOT NULL,
    multiplicity_state TEXT NOT NULL,
    start_seconds REAL NOT NULL,
    end_seconds REAL NOT NULL,
    artifact_path TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    extractor_version TEXT NOT NULL,
    input_fingerprint TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    FOREIGN KEY(video_id) REFERENCES videos(id),
    FOREIGN KEY(extraction_result_id) REFERENCES extraction_results(id)
);

CREATE TABLE IF NOT EXISTS speaker_name_claims (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id INTEGER NOT NULL,
    observation_id INTEGER NULL,
    display_name TEXT NOT NULL,
    normalized_name TEXT NOT NULL,
    claim_kind TEXT NOT NULL,
    channel TEXT NOT NULL,
    explicit_speaker_attribution INTEGER NOT NULL,
    correlation_group_id TEXT NOT NULL,
    provenance_json TEXT NOT NULL,
    artifact_path TEXT NOT NULL,
    claim_fingerprint TEXT NOT NULL UNIQUE,
    extractor_version TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(video_id) REFERENCES videos(id),
    FOREIGN KEY(observation_id) REFERENCES speaker_observations(id)
);

CREATE TABLE IF NOT EXISTS profile_observation_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id INTEGER NOT NULL,
    observation_id INTEGER NOT NULL,
    action TEXT NOT NULL CHECK(action IN ('attach', 'detach')),
    reviewer TEXT NOT NULL,
    reason TEXT NOT NULL,
    event_fingerprint TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    FOREIGN KEY(profile_id) REFERENCES speaker_profiles(id),
    FOREIGN KEY(observation_id) REFERENCES speaker_observations(id)
);

CREATE TABLE IF NOT EXISTS profile_name_claim_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id INTEGER NULL,
    claim_id INTEGER NOT NULL,
    action TEXT NOT NULL CHECK(action IN ('attach', 'reject')),
    reviewer TEXT NOT NULL,
    reason TEXT NOT NULL,
    event_fingerprint TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    FOREIGN KEY(profile_id) REFERENCES speaker_profiles(id),
    FOREIGN KEY(claim_id) REFERENCES speaker_name_claims(id),
    CHECK((action = 'attach' AND profile_id IS NOT NULL) OR action = 'reject')
);

CREATE TABLE IF NOT EXISTS speaker_profile_redirect_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    from_profile_id INTEGER NOT NULL,
    to_profile_id INTEGER NULL,
    action TEXT NOT NULL CHECK(action IN ('redirect', 'clear')),
    reviewer TEXT NOT NULL,
    reason TEXT NOT NULL,
    event_fingerprint TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    FOREIGN KEY(from_profile_id) REFERENCES speaker_profiles(id),
    FOREIGN KEY(to_profile_id) REFERENCES speaker_profiles(id),
    CHECK((action = 'redirect' AND to_profile_id IS NOT NULL) OR action = 'clear')
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_identity_evidence_artifact
ON identity_evidence(video_id, target_pastor_id, evidence_type, artifact_path);

CREATE INDEX IF NOT EXISTS idx_speaker_claims_video
ON speaker_name_claims(video_id, observation_id);

CREATE INDEX IF NOT EXISTS idx_media_artifacts_video_kind
ON media_artifacts(video_id, artifact_kind, id);

CREATE INDEX IF NOT EXISTS idx_media_attempts_video
ON media_acquisition_attempts(video_id, id);

CREATE INDEX IF NOT EXISTS idx_profile_observation_events_pair
ON profile_observation_events(profile_id, observation_id, id);

CREATE INDEX IF NOT EXISTS idx_profile_redirect_events_source
ON speaker_profile_redirect_events(from_profile_id, id);

CREATE INDEX IF NOT EXISTS idx_source_import_refs_provider
ON source_import_refs(provider, source_id);
"""


class Database:
    def __init__(self, database_path: Path, *, readonly: bool = False) -> None:
        self.database_path = database_path
        self.readonly = readonly

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        if self.readonly:
            uri = f"{self.database_path.expanduser().resolve().as_uri()}?mode=ro"
            connection = sqlite3.connect(uri, timeout=30.0, uri=True)
        else:
            connection = sqlite3.connect(self.database_path, timeout=30.0)
        connection.row_factory = sqlite3.Row
        try:
            if self.readonly:
                connection.execute("PRAGMA query_only = ON")
            else:
                connection.execute("PRAGMA journal_mode = WAL")
                connection.execute("PRAGMA synchronous = NORMAL")
            connection.execute("PRAGMA busy_timeout = 30000")
            yield connection
            if not self.readonly:
                connection.commit()
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript(SCHEMA)
            self._ensure_pastor_columns(connection)

    def _ensure_pastor_columns(self, connection: sqlite3.Connection) -> None:
        source_columns = {str(row["name"]) for row in connection.execute("PRAGMA table_info(sources)").fetchall()}
        if "pastor_id" not in source_columns:
            connection.execute("ALTER TABLE sources ADD COLUMN pastor_id INTEGER NULL")

        video_columns = {str(row["name"]) for row in connection.execute("PRAGMA table_info(videos)").fetchall()}
        if "pastor_id" not in video_columns:
            connection.execute("ALTER TABLE videos ADD COLUMN pastor_id INTEGER NULL")

    def _source_from_row(self, row: sqlite3.Row) -> Source:
        return Source(
            id=int(row["id"]),
            pastor_id=row["pastor_id"],
            url=str(row["url"]),
            source_type=SourceType(str(row["source_type"])),
            added_at=parse_datetime(str(row["added_at"])) or utc_now(),
            notes=row["notes"],
        )

    def _pastor_from_row(self, row: sqlite3.Row) -> Pastor:
        return Pastor(
            id=int(row["id"]),
            slug=str(row["slug"]),
            display_name=str(row["display_name"]),
            added_at=parse_datetime(str(row["added_at"])) or utc_now(),
            notes=row["notes"],
        )

    def _video_from_row(self, row: sqlite3.Row) -> Video:
        return Video(
            id=int(row["id"]),
            source_id=int(row["source_id"]),
            pastor_id=row["pastor_id"],
            youtube_video_id=str(row["youtube_video_id"]),
            title=str(row["title"]),
            url=str(row["url"]),
            channel_name=row["channel_name"],
            published_at=parse_datetime(row["published_at"]),
            duration_seconds=row["duration_seconds"],
            status=VideoStatus(str(row["status"])),
            failure_reason=row["failure_reason"],
        )

    def _transcript_artifact_from_row(self, row: sqlite3.Row) -> TranscriptArtifact:
        return TranscriptArtifact(
            id=int(row["id"]),
            video_id=int(row["video_id"]),
            source_kind=TranscriptSourceKind(str(row["source_kind"])),
            raw_json_path=row["raw_json_path"],
            raw_text_path=row["raw_text_path"],
            audio_path=row["audio_path"],
            created_at=parse_datetime(str(row["created_at"])) or utc_now(),
        )

    def _media_artifact_from_row(self, row: sqlite3.Row) -> MediaArtifact:
        return MediaArtifact(
            id=int(row["id"]),
            video_id=int(row["video_id"]),
            parent_media_artifact_id=(
                int(row["parent_media_artifact_id"])
                if row["parent_media_artifact_id"] is not None
                else None
            ),
            artifact_kind=str(row["artifact_kind"]),
            provenance_kind=str(row["provenance_kind"]),
            artifact_path=str(row["artifact_path"]),
            manifest_path=str(row["manifest_path"]),
            content_sha256=str(row["content_sha256"]),
            byte_size=int(row["byte_size"]),
            duration_seconds=(
                float(row["duration_seconds"]) if row["duration_seconds"] is not None else None
            ),
            format_name=row["format_name"],
            sample_rate_hz=(
                int(row["sample_rate_hz"]) if row["sample_rate_hz"] is not None else None
            ),
            channel_count=(
                int(row["channel_count"]) if row["channel_count"] is not None else None
            ),
            acquisition_tool=str(row["acquisition_tool"]),
            acquisition_tool_version=str(row["acquisition_tool_version"]),
            input_fingerprint=str(row["input_fingerprint"]),
            created_at=parse_datetime(str(row["created_at"])) or utc_now(),
        )

    def _media_acquisition_attempt_from_row(
        self, row: sqlite3.Row
    ) -> MediaAcquisitionAttempt:
        return MediaAcquisitionAttempt(
            id=int(row["id"]),
            video_id=int(row["video_id"]),
            target_kind=str(row["target_kind"]),
            outcome=str(row["outcome"]),
            reason_code=str(row["reason_code"]),
            detail=row["detail"],
            media_artifact_id=(
                int(row["media_artifact_id"])
                if row["media_artifact_id"] is not None
                else None
            ),
            service_version=str(row["service_version"]),
            input_fingerprint=str(row["input_fingerprint"]),
            created_at=parse_datetime(str(row["created_at"])) or utc_now(),
        )

    def _transcript_segment_from_row(self, row: sqlite3.Row) -> TranscriptSegment:
        return TranscriptSegment(
            id=int(row["id"]),
            video_id=int(row["video_id"]),
            artifact_id=int(row["artifact_id"]),
            start_seconds=row["start_seconds"],
            end_seconds=row["end_seconds"],
            text=str(row["text"]),
            speaker_hint=row["speaker_hint"],
            label=TranscriptSegmentLabel(str(row["label"])),
            confidence=row["confidence"],
        )

    def _extraction_result_from_row(self, row: sqlite3.Row) -> ExtractionResult:
        return ExtractionResult(
            id=int(row["id"]),
            video_id=int(row["video_id"]),
            version=int(row["version"]),
            proposed_text_path=str(row["proposed_text_path"]),
            proposed_json_path=row["proposed_json_path"],
            notes=row["notes"],
            created_at=parse_datetime(str(row["created_at"])) or utc_now(),
        )

    def _review_result_from_row(self, row: sqlite3.Row) -> ReviewResult:
        return ReviewResult(
            id=int(row["id"]),
            video_id=int(row["video_id"]),
            extraction_result_id=int(row["extraction_result_id"]),
            approved_text_path=str(row["approved_text_path"]),
            reviewed_at=parse_datetime(str(row["reviewed_at"])) or utc_now(),
            review_notes=row["review_notes"],
        )

    def _excluded_video_from_row(self, row: sqlite3.Row) -> ExcludedVideo:
        return ExcludedVideo(
            id=int(row["id"]),
            pastor_id=row["pastor_id"],
            source_id=row["source_id"],
            youtube_video_id=str(row["youtube_video_id"]),
            title=str(row["title"]),
            url=str(row["url"]),
            excluded_at=parse_datetime(str(row["excluded_at"])) or utc_now(),
            notes=row["notes"],
        )

    def _metadata_artifact_from_row(self, row: sqlite3.Row) -> MetadataArtifact:
        return MetadataArtifact(
            id=int(row["id"]),
            video_id=int(row["video_id"]),
            schema_version=int(row["schema_version"]),
            source_kind=str(row["source_kind"]),
            artifact_path=str(row["artifact_path"]),
            content_sha256=str(row["content_sha256"]),
            extractor_version=str(row["extractor_version"]),
            created_at=parse_datetime(str(row["created_at"])) or utc_now(),
        )

    def _identity_evidence_from_row(self, row: sqlite3.Row) -> IdentityEvidence:
        return IdentityEvidence(
            id=int(row["id"]),
            video_id=int(row["video_id"]),
            target_pastor_id=int(row["target_pastor_id"]),
            evidence_type=str(row["evidence_type"]),
            source_family=str(row["source_family"]),
            polarity=str(row["polarity"]),
            strength=str(row["strength"]),
            scope=str(row["scope"]),
            artifact_path=str(row["artifact_path"]),
            extractor_version=str(row["extractor_version"]),
            created_at=parse_datetime(str(row["created_at"])) or utc_now(),
        )

    def _identity_assessment_from_row(self, row: sqlite3.Row) -> IdentityAssessment:
        return IdentityAssessment(
            id=int(row["id"]),
            video_id=int(row["video_id"]),
            target_pastor_id=int(row["target_pastor_id"]),
            extraction_result_id=int(row["extraction_result_id"]),
            state=IdentityState(str(row["state"])),
            recommended_action=IdentityAction(str(row["recommended_action"])),
            shadow_mode=bool(row["shadow_mode"]),
            policy_version=str(row["policy_version"]),
            evidence_ledger_path=str(row["evidence_ledger_path"]),
            assessment_path=str(row["assessment_path"]),
            input_fingerprint=str(row["input_fingerprint"]),
            created_at=parse_datetime(str(row["created_at"])) or utc_now(),
        )

    def _speaker_profile_from_row(self, row: sqlite3.Row) -> SpeakerProfile:
        return SpeakerProfile(
            id=int(row["id"]),
            stable_key=str(row["stable_key"]),
            display_label=row["display_label"],
            lifecycle_state=str(row["lifecycle_state"]),
            created_reason=str(row["created_reason"]),
            created_at=parse_datetime(str(row["created_at"])) or utc_now(),
        )

    def _speaker_observation_from_row(self, row: sqlite3.Row) -> SpeakerObservation:
        return SpeakerObservation(
            id=int(row["id"]),
            video_id=int(row["video_id"]),
            extraction_result_id=int(row["extraction_result_id"]),
            role=str(row["role"]),
            multiplicity_state=str(row["multiplicity_state"]),
            start_seconds=float(row["start_seconds"]),
            end_seconds=float(row["end_seconds"]),
            artifact_path=str(row["artifact_path"]),
            content_sha256=str(row["content_sha256"]),
            extractor_version=str(row["extractor_version"]),
            input_fingerprint=str(row["input_fingerprint"]),
            created_at=parse_datetime(str(row["created_at"])) or utc_now(),
        )

    def _speaker_name_claim_from_row(self, row: sqlite3.Row) -> SpeakerNameClaim:
        return SpeakerNameClaim(
            id=int(row["id"]),
            video_id=int(row["video_id"]),
            observation_id=int(row["observation_id"]) if row["observation_id"] is not None else None,
            display_name=str(row["display_name"]),
            normalized_name=str(row["normalized_name"]),
            claim_kind=str(row["claim_kind"]),
            channel=str(row["channel"]),
            explicit_speaker_attribution=bool(row["explicit_speaker_attribution"]),
            correlation_group_id=str(row["correlation_group_id"]),
            provenance_json=str(row["provenance_json"]),
            artifact_path=str(row["artifact_path"]),
            claim_fingerprint=str(row["claim_fingerprint"]),
            extractor_version=str(row["extractor_version"]),
            created_at=parse_datetime(str(row["created_at"])) or utc_now(),
        )

    def add_pastor(self, slug: str, display_name: str, notes: str | None = None) -> Pastor:
        added_at = utc_now().isoformat()
        with self.connect() as connection:
            try:
                cursor = connection.execute(
                    "INSERT INTO pastors (slug, display_name, added_at, notes) VALUES (?, ?, ?, ?)",
                    (slug, display_name, added_at, notes),
                )
            except sqlite3.IntegrityError:
                row = connection.execute(
                    "SELECT id, slug, display_name, added_at, notes FROM pastors WHERE slug = ?",
                    (slug,),
                ).fetchone()
                if row is None:
                    raise
                return self._pastor_from_row(row)
            pastor_id = int(cursor.lastrowid)
        return Pastor(
            id=pastor_id,
            slug=slug,
            display_name=display_name,
            added_at=parse_datetime(added_at) or utc_now(),
            notes=notes,
        )

    def get_pastor_by_slug(self, slug: str) -> Pastor | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT id, slug, display_name, added_at, notes FROM pastors WHERE slug = ?",
                (slug,),
            ).fetchone()
        if row is None:
            return None
        return self._pastor_from_row(row)

    def get_pastor_by_id(self, pastor_id: int) -> Pastor | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT id, slug, display_name, added_at, notes FROM pastors WHERE id = ?",
                (pastor_id,),
            ).fetchone()
        if row is None:
            return None
        return self._pastor_from_row(row)

    def list_pastors(self) -> list[Pastor]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT id, slug, display_name, added_at, notes FROM pastors ORDER BY id"
            ).fetchall()
        return [self._pastor_from_row(row) for row in rows]

    def add_source(
        self,
        url: str,
        source_type: SourceType,
        pastor_id: int,
        notes: str | None = None,
    ) -> Source:
        added_at = utc_now().isoformat()
        with self.connect() as connection:
            try:
                cursor = connection.execute(
                    "INSERT INTO sources (pastor_id, url, source_type, added_at, notes) VALUES (?, ?, ?, ?, ?)",
                    (pastor_id, url, source_type.value, added_at, notes),
                )
            except sqlite3.IntegrityError:
                row = connection.execute(
                    "SELECT id, pastor_id, url, source_type, added_at, notes FROM sources WHERE url = ?",
                    (url,),
                ).fetchone()
                if row is None:
                    raise
                return self._source_from_row(row)
            source_id = int(cursor.lastrowid)
        return Source(
            id=source_id,
            pastor_id=pastor_id,
            url=url,
            source_type=source_type,
            added_at=parse_datetime(added_at) or utc_now(),
            notes=notes,
        )

    def list_sources(self) -> list[Source]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT id, pastor_id, url, source_type, added_at, notes FROM sources ORDER BY id"
            ).fetchall()
        return [self._source_from_row(row) for row in rows]

    def get_source_by_id(self, source_id: int) -> Source | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT id, pastor_id, url, source_type, added_at, notes FROM sources WHERE id = ?",
                (source_id,),
            ).fetchone()
        if row is None:
            return None
        return self._source_from_row(row)

    def get_source_by_url(self, url: str) -> Source | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT id, pastor_id, url, source_type, added_at, notes FROM sources WHERE url = ?",
                (url,),
            ).fetchone()
        if row is None:
            return None
        return self._source_from_row(row)

    def add_video(
        self,
        source_id: int,
        pastor_id: int,
        youtube_video_id: str,
        title: str,
        url: str,
        channel_name: str | None = None,
        published_at: str | None = None,
        duration_seconds: int | None = None,
        status: VideoStatus = VideoStatus.DISCOVERED,
        failure_reason: str | None = None,
    ) -> Video:
        with self.connect() as connection:
            try:
                cursor = connection.execute(
                    """
                    INSERT INTO videos (
                        source_id, pastor_id, youtube_video_id, title, url, channel_name,
                        published_at, duration_seconds, status, failure_reason
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        source_id,
                        pastor_id,
                        youtube_video_id,
                        title,
                        url,
                        channel_name,
                        published_at,
                        duration_seconds,
                        status.value,
                        failure_reason,
                    ),
                )
            except sqlite3.IntegrityError:
                row = connection.execute(
                    """
                    SELECT id, source_id, pastor_id, youtube_video_id, title, url, channel_name,
                           published_at, duration_seconds, status, failure_reason
                    FROM videos
                    WHERE youtube_video_id = ?
                    """,
                    (youtube_video_id,),
                ).fetchone()
                if row is None:
                    raise
                return self._video_from_row(row)

            video_id = int(cursor.lastrowid)
        return Video(
            id=video_id,
            source_id=source_id,
            pastor_id=pastor_id,
            youtube_video_id=youtube_video_id,
            title=title,
            url=url,
            channel_name=channel_name,
            published_at=parse_datetime(published_at),
            duration_seconds=duration_seconds,
            status=status,
            failure_reason=failure_reason,
        )

    def update_video_status(self, video_id: int, status: VideoStatus, failure_reason: str | None = None) -> None:
        with self.connect() as connection:
            connection.execute(
                "UPDATE videos SET status = ?, failure_reason = ? WHERE id = ?",
                (status.value, failure_reason, video_id),
            )

    def update_video_status_if_current(
        self,
        video_id: int,
        current_status: VideoStatus,
        new_status: VideoStatus,
        failure_reason: str | None = None,
    ) -> bool:
        with self.connect() as connection:
            cursor = connection.execute(
                "UPDATE videos SET status = ?, failure_reason = ? WHERE id = ? AND status = ?",
                (new_status.value, failure_reason, video_id, current_status.value),
            )
        return cursor.rowcount > 0

    def list_videos(self) -> list[Video]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT id, source_id, pastor_id, youtube_video_id, title, url, channel_name,
                       published_at, duration_seconds, status, failure_reason
                FROM videos
                ORDER BY id
                """
            ).fetchall()
        return [self._video_from_row(row) for row in rows]

    def get_video_by_youtube_id(self, youtube_video_id: str) -> Video | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT id, source_id, pastor_id, youtube_video_id, title, url, channel_name,
                       published_at, duration_seconds, status, failure_reason
                FROM videos
                WHERE youtube_video_id = ?
                """,
                (youtube_video_id,),
            ).fetchone()
        if row is None:
            return None
        return self._video_from_row(row)

    def get_video_by_id(self, video_id: int) -> Video | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT id, source_id, pastor_id, youtube_video_id, title, url, channel_name,
                       published_at, duration_seconds, status, failure_reason
                FROM videos
                WHERE id = ?
                """,
                (video_id,),
            ).fetchone()
        if row is None:
            return None
        return self._video_from_row(row)

    def list_videos_by_source_id(self, source_id: int) -> list[Video]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT id, source_id, pastor_id, youtube_video_id, title, url, channel_name,
                       published_at, duration_seconds, status, failure_reason
                FROM videos
                WHERE source_id = ?
                ORDER BY id
                """,
                (source_id,),
            ).fetchall()
        return [self._video_from_row(row) for row in rows]

    def add_transcript_artifact(
        self,
        video_id: int,
        source_kind: TranscriptSourceKind,
        audio_path: str | None,
        raw_json_path: str | None = None,
        raw_text_path: str | None = None,
    ) -> TranscriptArtifact:
        created_at = utc_now().isoformat()
        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO transcript_artifacts (
                    video_id, source_kind, raw_json_path, raw_text_path, audio_path, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (video_id, source_kind.value, raw_json_path, raw_text_path, audio_path, created_at),
            )
        return TranscriptArtifact(
            id=int(cursor.lastrowid),
            video_id=video_id,
            source_kind=source_kind,
            raw_json_path=raw_json_path,
            raw_text_path=raw_text_path,
            audio_path=audio_path,
            created_at=parse_datetime(created_at) or utc_now(),
        )

    def add_media_artifact(
        self,
        *,
        video_id: int,
        parent_media_artifact_id: int | None,
        artifact_kind: str,
        provenance_kind: str,
        artifact_path: str,
        manifest_path: str,
        content_sha256: str,
        byte_size: int,
        duration_seconds: float | None,
        format_name: str | None,
        sample_rate_hz: int | None,
        channel_count: int | None,
        acquisition_tool: str,
        acquisition_tool_version: str,
        input_fingerprint: str,
    ) -> MediaArtifact:
        created_at = utc_now().isoformat()
        values = (
            video_id,
            parent_media_artifact_id,
            artifact_kind,
            provenance_kind,
            artifact_path,
            manifest_path,
            content_sha256,
            byte_size,
            duration_seconds,
            format_name,
            sample_rate_hz,
            channel_count,
            acquisition_tool,
            acquisition_tool_version,
            input_fingerprint,
            created_at,
        )
        with self.connect() as connection:
            try:
                cursor = connection.execute(
                    """
                    INSERT INTO media_artifacts (
                        video_id, parent_media_artifact_id, artifact_kind, provenance_kind,
                        artifact_path, manifest_path, content_sha256, byte_size,
                        duration_seconds, format_name, sample_rate_hz, channel_count,
                        acquisition_tool, acquisition_tool_version, input_fingerprint, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    values,
                )
            except sqlite3.IntegrityError:
                row = connection.execute(
                    "SELECT * FROM media_artifacts WHERE input_fingerprint = ?",
                    (input_fingerprint,),
                ).fetchone()
                if row is None:
                    raise
                return self._media_artifact_from_row(row)
        return MediaArtifact(
            id=int(cursor.lastrowid),
            video_id=video_id,
            parent_media_artifact_id=parent_media_artifact_id,
            artifact_kind=artifact_kind,
            provenance_kind=provenance_kind,
            artifact_path=artifact_path,
            manifest_path=manifest_path,
            content_sha256=content_sha256,
            byte_size=byte_size,
            duration_seconds=duration_seconds,
            format_name=format_name,
            sample_rate_hz=sample_rate_hz,
            channel_count=channel_count,
            acquisition_tool=acquisition_tool,
            acquisition_tool_version=acquisition_tool_version,
            input_fingerprint=input_fingerprint,
            created_at=parse_datetime(created_at) or utc_now(),
        )

    def list_media_artifacts_for_video(self, video_id: int) -> list[MediaArtifact]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM media_artifacts WHERE video_id = ? ORDER BY id",
                (video_id,),
            ).fetchall()
        return [self._media_artifact_from_row(row) for row in rows]

    def get_latest_media_artifact(
        self, video_id: int, artifact_kind: str
    ) -> MediaArtifact | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM media_artifacts
                WHERE video_id = ? AND artifact_kind = ?
                ORDER BY id DESC LIMIT 1
                """,
                (video_id, artifact_kind),
            ).fetchone()
        return self._media_artifact_from_row(row) if row is not None else None

    def add_media_acquisition_attempt(
        self,
        *,
        video_id: int,
        target_kind: str,
        outcome: str,
        reason_code: str,
        detail: str | None,
        media_artifact_id: int | None,
        service_version: str,
        input_fingerprint: str,
    ) -> MediaAcquisitionAttempt:
        created_at = utc_now().isoformat()
        values = (
            video_id,
            target_kind,
            outcome,
            reason_code,
            detail,
            media_artifact_id,
            service_version,
            input_fingerprint,
            created_at,
        )
        with self.connect() as connection:
            try:
                cursor = connection.execute(
                    """
                    INSERT INTO media_acquisition_attempts (
                        video_id, target_kind, outcome, reason_code, detail,
                        media_artifact_id, service_version, input_fingerprint, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    values,
                )
            except sqlite3.IntegrityError:
                row = connection.execute(
                    "SELECT * FROM media_acquisition_attempts WHERE input_fingerprint = ?",
                    (input_fingerprint,),
                ).fetchone()
                if row is None:
                    raise
                return self._media_acquisition_attempt_from_row(row)
        return MediaAcquisitionAttempt(
            id=int(cursor.lastrowid),
            video_id=video_id,
            target_kind=target_kind,
            outcome=outcome,
            reason_code=reason_code,
            detail=detail,
            media_artifact_id=media_artifact_id,
            service_version=service_version,
            input_fingerprint=input_fingerprint,
            created_at=parse_datetime(created_at) or utc_now(),
        )

    def list_media_acquisition_attempts(
        self, video_id: int | None = None
    ) -> list[MediaAcquisitionAttempt]:
        with self.connect() as connection:
            if video_id is None:
                rows = connection.execute(
                    "SELECT * FROM media_acquisition_attempts ORDER BY id"
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM media_acquisition_attempts WHERE video_id = ? ORDER BY id",
                    (video_id,),
                ).fetchall()
        return [self._media_acquisition_attempt_from_row(row) for row in rows]

    def get_latest_media_acquisition_attempt(
        self, video_id: int
    ) -> MediaAcquisitionAttempt | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM media_acquisition_attempts
                WHERE video_id = ? ORDER BY id DESC LIMIT 1
                """,
                (video_id,),
            ).fetchone()
        return self._media_acquisition_attempt_from_row(row) if row is not None else None

    def delete_transcript_segments_for_video(self, video_id: int) -> None:
        with self.connect() as connection:
            connection.execute("DELETE FROM transcript_segments WHERE video_id = ?", (video_id,))

    def delete_review_results_for_video(self, video_id: int) -> None:
        with self.connect() as connection:
            connection.execute("DELETE FROM review_results WHERE video_id = ?", (video_id,))

    def delete_extraction_results_for_video(self, video_id: int) -> None:
        with self.connect() as connection:
            connection.execute("DELETE FROM identity_assessments WHERE video_id = ?", (video_id,))
            self._delete_speaker_records_for_video(connection, video_id)
            connection.execute("DELETE FROM extraction_results WHERE video_id = ?", (video_id,))

    def delete_transcript_artifacts_for_video(self, video_id: int) -> None:
        with self.connect() as connection:
            connection.execute("DELETE FROM transcript_artifacts WHERE video_id = ?", (video_id,))

    def delete_identity_records_for_video(self, video_id: int) -> None:
        with self.connect() as connection:
            connection.execute("DELETE FROM identity_assessments WHERE video_id = ?", (video_id,))
            connection.execute("DELETE FROM identity_evidence WHERE video_id = ?", (video_id,))
            connection.execute("DELETE FROM metadata_artifacts WHERE video_id = ?", (video_id,))
            self._delete_speaker_records_for_video(connection, video_id)

    def _delete_speaker_records_for_video(
        self, connection: sqlite3.Connection, video_id: int
    ) -> None:
        connection.execute(
            """
            DELETE FROM profile_name_claim_events
            WHERE claim_id IN (SELECT id FROM speaker_name_claims WHERE video_id = ?)
            """,
            (video_id,),
        )
        connection.execute(
            """
            DELETE FROM profile_observation_events
            WHERE observation_id IN (SELECT id FROM speaker_observations WHERE video_id = ?)
            """,
            (video_id,),
        )
        connection.execute("DELETE FROM speaker_name_claims WHERE video_id = ?", (video_id,))
        connection.execute("DELETE FROM speaker_observations WHERE video_id = ?", (video_id,))

    def delete_video(self, video_id: int) -> None:
        self.delete_identity_records_for_video(video_id)
        self.delete_review_results_for_video(video_id)
        self.delete_extraction_results_for_video(video_id)
        self.delete_transcript_segments_for_video(video_id)
        self.delete_transcript_artifacts_for_video(video_id)
        with self.connect() as connection:
            connection.execute("DELETE FROM media_acquisition_attempts WHERE video_id = ?", (video_id,))
            connection.execute("DELETE FROM media_artifacts WHERE video_id = ?", (video_id,))
            connection.execute("DELETE FROM videos WHERE id = ?", (video_id,))

    def delete_source(self, source_id: int) -> None:
        with self.connect() as connection:
            connection.execute("DELETE FROM sources WHERE id = ?", (source_id,))

    def add_excluded_video(
        self,
        youtube_video_id: str,
        title: str,
        url: str,
        pastor_id: int | None = None,
        source_id: int | None = None,
        notes: str | None = None,
    ) -> ExcludedVideo:
        excluded_at = utc_now().isoformat()
        with self.connect() as connection:
            try:
                cursor = connection.execute(
                    """
                    INSERT INTO excluded_videos (
                        pastor_id, source_id, youtube_video_id, title, url, excluded_at, notes
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (pastor_id, source_id, youtube_video_id, title, url, excluded_at, notes),
                )
            except sqlite3.IntegrityError:
                connection.execute(
                    """
                    UPDATE excluded_videos
                    SET pastor_id = ?, source_id = ?, title = ?, url = ?, excluded_at = ?, notes = ?
                    WHERE youtube_video_id = ?
                    """,
                    (pastor_id, source_id, title, url, excluded_at, notes, youtube_video_id),
                )
                row = connection.execute(
                    """
                    SELECT id, pastor_id, source_id, youtube_video_id, title, url, excluded_at, notes
                    FROM excluded_videos
                    WHERE youtube_video_id = ?
                    """,
                    (youtube_video_id,),
                ).fetchone()
                if row is None:
                    raise
                return self._excluded_video_from_row(row)
        return ExcludedVideo(
            id=int(cursor.lastrowid),
            pastor_id=pastor_id,
            source_id=source_id,
            youtube_video_id=youtube_video_id,
            title=title,
            url=url,
            excluded_at=parse_datetime(excluded_at) or utc_now(),
            notes=notes,
        )

    def list_excluded_videos(self) -> list[ExcludedVideo]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT id, pastor_id, source_id, youtube_video_id, title, url, excluded_at, notes
                FROM excluded_videos
                ORDER BY excluded_at DESC, id DESC
                """
            ).fetchall()
        return [self._excluded_video_from_row(row) for row in rows]

    def get_excluded_video_by_youtube_id(self, youtube_video_id: str) -> ExcludedVideo | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT id, pastor_id, source_id, youtube_video_id, title, url, excluded_at, notes
                FROM excluded_videos
                WHERE youtube_video_id = ?
                """,
                (youtube_video_id,),
            ).fetchone()
        if row is None:
            return None
        return self._excluded_video_from_row(row)

    def delete_excluded_video(self, youtube_video_id: str) -> None:
        with self.connect() as connection:
            connection.execute("DELETE FROM excluded_videos WHERE youtube_video_id = ?", (youtube_video_id,))

    def add_transcript_segment(
        self,
        video_id: int,
        artifact_id: int,
        start_seconds: float | None,
        end_seconds: float | None,
        text: str,
        label: TranscriptSegmentLabel,
        speaker_hint: str | None = None,
        confidence: float | None = None,
    ) -> TranscriptSegment:
        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO transcript_segments (
                    video_id, artifact_id, start_seconds, end_seconds, text, speaker_hint, label, confidence
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (video_id, artifact_id, start_seconds, end_seconds, text, speaker_hint, label.value, confidence),
            )
        return TranscriptSegment(
            id=int(cursor.lastrowid),
            video_id=video_id,
            artifact_id=artifact_id,
            start_seconds=start_seconds,
            end_seconds=end_seconds,
            text=text,
            speaker_hint=speaker_hint,
            label=label,
            confidence=confidence,
        )

    def list_transcript_segments(self, video_id: int) -> list[TranscriptSegment]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT id, video_id, artifact_id, start_seconds, end_seconds, text, speaker_hint, label, confidence
                FROM transcript_segments
                WHERE video_id = ?
                ORDER BY id
                """,
                (video_id,),
            ).fetchall()
        return [self._transcript_segment_from_row(row) for row in rows]

    def list_transcript_artifacts(self) -> list[TranscriptArtifact]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT id, video_id, source_kind, raw_json_path, raw_text_path, audio_path, created_at
                FROM transcript_artifacts
                ORDER BY id
                """
            ).fetchall()
        return [self._transcript_artifact_from_row(row) for row in rows]

    def list_transcript_artifacts_for_video(self, video_id: int) -> list[TranscriptArtifact]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT id, video_id, source_kind, raw_json_path, raw_text_path, audio_path, created_at
                FROM transcript_artifacts
                WHERE video_id = ?
                ORDER BY id
                """,
                (video_id,),
            ).fetchall()
        return [self._transcript_artifact_from_row(row) for row in rows]

    def get_latest_transcript_artifact_for_video(self, video_id: int) -> TranscriptArtifact | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT id, video_id, source_kind, raw_json_path, raw_text_path, audio_path, created_at
                FROM transcript_artifacts
                WHERE video_id = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (video_id,),
            ).fetchone()
        if row is None:
            return None
        return self._transcript_artifact_from_row(row)

    def get_latest_audio_transcript_artifact_for_video(
        self, video_id: int
    ) -> TranscriptArtifact | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT id, video_id, source_kind, raw_json_path, raw_text_path, audio_path, created_at
                FROM transcript_artifacts
                WHERE video_id = ? AND audio_path IS NOT NULL AND audio_path != ''
                ORDER BY id DESC
                LIMIT 1
                """,
                (video_id,),
            ).fetchone()
        if row is None:
            return None
        return self._transcript_artifact_from_row(row)

    def add_extraction_result(
        self,
        video_id: int,
        version: int,
        proposed_text_path: str,
        proposed_json_path: str | None = None,
        notes: str | None = None,
    ) -> ExtractionResult:
        created_at = utc_now().isoformat()
        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO extraction_results (
                    video_id, version, proposed_text_path, proposed_json_path, notes, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (video_id, version, proposed_text_path, proposed_json_path, notes, created_at),
            )
        return ExtractionResult(
            id=int(cursor.lastrowid),
            video_id=video_id,
            version=version,
            proposed_text_path=proposed_text_path,
            proposed_json_path=proposed_json_path,
            notes=notes,
            created_at=parse_datetime(created_at) or utc_now(),
        )

    def list_extraction_results(self) -> list[ExtractionResult]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT id, video_id, version, proposed_text_path, proposed_json_path, notes, created_at
                FROM extraction_results
                ORDER BY id
                """
            ).fetchall()
        return [self._extraction_result_from_row(row) for row in rows]

    def get_latest_extraction_result_for_video(self, video_id: int) -> ExtractionResult | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT id, video_id, version, proposed_text_path, proposed_json_path, notes, created_at
                FROM extraction_results
                WHERE video_id = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (video_id,),
            ).fetchone()
        if row is None:
            return None
        return self._extraction_result_from_row(row)

    def add_review_result(
        self,
        video_id: int,
        extraction_result_id: int,
        approved_text_path: str,
        review_notes: str | None = None,
    ) -> ReviewResult:
        reviewed_at = utc_now().isoformat()
        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO review_results (
                    video_id, extraction_result_id, approved_text_path, reviewed_at, review_notes
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (video_id, extraction_result_id, approved_text_path, reviewed_at, review_notes),
            )
        return ReviewResult(
            id=int(cursor.lastrowid),
            video_id=video_id,
            extraction_result_id=extraction_result_id,
            approved_text_path=approved_text_path,
            reviewed_at=parse_datetime(reviewed_at) or utc_now(),
            review_notes=review_notes,
        )

    def list_review_results(self) -> list[ReviewResult]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT id, video_id, extraction_result_id, approved_text_path, reviewed_at, review_notes
                FROM review_results
                ORDER BY id
                """
            ).fetchall()
        return [self._review_result_from_row(row) for row in rows]

    def get_latest_review_result_for_video(self, video_id: int) -> ReviewResult | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT id, video_id, extraction_result_id, approved_text_path, reviewed_at, review_notes
                FROM review_results
                WHERE video_id = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (video_id,),
            ).fetchone()
        if row is None:
            return None
        return self._review_result_from_row(row)

    def add_metadata_artifact(
        self,
        *,
        video_id: int,
        schema_version: int,
        source_kind: str,
        artifact_path: str,
        content_sha256: str,
        extractor_version: str,
    ) -> MetadataArtifact:
        created_at = utc_now().isoformat()
        with self.connect() as connection:
            try:
                cursor = connection.execute(
                    """
                    INSERT INTO metadata_artifacts (
                        video_id, schema_version, source_kind, artifact_path, content_sha256,
                        extractor_version, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        video_id,
                        schema_version,
                        source_kind,
                        artifact_path,
                        content_sha256,
                        extractor_version,
                        created_at,
                    ),
                )
            except sqlite3.IntegrityError:
                row = connection.execute(
                    """
                    SELECT id, video_id, schema_version, source_kind, artifact_path, content_sha256,
                           extractor_version, created_at
                    FROM metadata_artifacts
                    WHERE video_id = ? AND content_sha256 = ? AND extractor_version = ?
                    """,
                    (video_id, content_sha256, extractor_version),
                ).fetchone()
                if row is None:
                    raise
                return self._metadata_artifact_from_row(row)
        return MetadataArtifact(
            id=int(cursor.lastrowid),
            video_id=video_id,
            schema_version=schema_version,
            source_kind=source_kind,
            artifact_path=artifact_path,
            content_sha256=content_sha256,
            extractor_version=extractor_version,
            created_at=parse_datetime(created_at) or utc_now(),
        )

    def get_latest_metadata_artifact_for_video(self, video_id: int) -> MetadataArtifact | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT id, video_id, schema_version, source_kind, artifact_path, content_sha256,
                       extractor_version, created_at
                FROM metadata_artifacts
                WHERE video_id = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (video_id,),
            ).fetchone()
        return self._metadata_artifact_from_row(row) if row is not None else None

    def add_identity_evidence(
        self,
        *,
        video_id: int,
        target_pastor_id: int,
        evidence_type: str,
        source_family: str,
        polarity: str,
        strength: str,
        scope: str,
        artifact_path: str,
        extractor_version: str,
    ) -> IdentityEvidence:
        created_at = utc_now().isoformat()
        with self.connect() as connection:
            try:
                cursor = connection.execute(
                    """
                    INSERT INTO identity_evidence (
                        video_id, target_pastor_id, evidence_type, source_family, polarity,
                        strength, scope, artifact_path, extractor_version, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        video_id,
                        target_pastor_id,
                        evidence_type,
                        source_family,
                        polarity,
                        strength,
                        scope,
                        artifact_path,
                        extractor_version,
                        created_at,
                    ),
                )
            except sqlite3.IntegrityError:
                row = connection.execute(
                    """
                    SELECT id, video_id, target_pastor_id, evidence_type, source_family, polarity,
                           strength, scope, artifact_path, extractor_version, created_at
                    FROM identity_evidence
                    WHERE video_id = ? AND target_pastor_id = ? AND evidence_type = ?
                      AND artifact_path = ?
                    """,
                    (video_id, target_pastor_id, evidence_type, artifact_path),
                ).fetchone()
                if row is None:
                    raise
                return self._identity_evidence_from_row(row)
        return IdentityEvidence(
            id=int(cursor.lastrowid),
            video_id=video_id,
            target_pastor_id=target_pastor_id,
            evidence_type=evidence_type,
            source_family=source_family,
            polarity=polarity,
            strength=strength,
            scope=scope,
            artifact_path=artifact_path,
            extractor_version=extractor_version,
            created_at=parse_datetime(created_at) or utc_now(),
        )

    def list_identity_evidence_for_video(self, video_id: int) -> list[IdentityEvidence]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT id, video_id, target_pastor_id, evidence_type, source_family, polarity,
                       strength, scope, artifact_path, extractor_version, created_at
                FROM identity_evidence
                WHERE video_id = ?
                ORDER BY id
                """,
                (video_id,),
            ).fetchall()
        return [self._identity_evidence_from_row(row) for row in rows]

    def get_identity_assessment_by_fingerprint(self, input_fingerprint: str) -> IdentityAssessment | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT id, video_id, target_pastor_id, extraction_result_id, state,
                       recommended_action, shadow_mode, policy_version, evidence_ledger_path,
                       assessment_path, input_fingerprint, created_at
                FROM identity_assessments
                WHERE input_fingerprint = ?
                """,
                (input_fingerprint,),
            ).fetchone()
        return self._identity_assessment_from_row(row) if row is not None else None

    def add_identity_assessment(
        self,
        *,
        video_id: int,
        target_pastor_id: int,
        extraction_result_id: int,
        state: IdentityState,
        recommended_action: IdentityAction,
        shadow_mode: bool,
        policy_version: str,
        evidence_ledger_path: str,
        assessment_path: str,
        input_fingerprint: str,
    ) -> IdentityAssessment:
        existing = self.get_identity_assessment_by_fingerprint(input_fingerprint)
        if existing is not None:
            return existing
        created_at = utc_now().isoformat()
        with self.connect() as connection:
            try:
                cursor = connection.execute(
                    """
                    INSERT INTO identity_assessments (
                        video_id, target_pastor_id, extraction_result_id, state, recommended_action,
                        shadow_mode, policy_version, evidence_ledger_path, assessment_path,
                        input_fingerprint, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        video_id,
                        target_pastor_id,
                        extraction_result_id,
                        state.value,
                        recommended_action.value,
                        1 if shadow_mode else 0,
                        policy_version,
                        evidence_ledger_path,
                        assessment_path,
                        input_fingerprint,
                        created_at,
                    ),
                )
            except sqlite3.IntegrityError:
                row = connection.execute(
                    """
                    SELECT id, video_id, target_pastor_id, extraction_result_id, state,
                           recommended_action, shadow_mode, policy_version, evidence_ledger_path,
                           assessment_path, input_fingerprint, created_at
                    FROM identity_assessments
                    WHERE input_fingerprint = ?
                    """,
                    (input_fingerprint,),
                ).fetchone()
                if row is None:
                    raise
                return self._identity_assessment_from_row(row)
        return IdentityAssessment(
            id=int(cursor.lastrowid),
            video_id=video_id,
            target_pastor_id=target_pastor_id,
            extraction_result_id=extraction_result_id,
            state=state,
            recommended_action=recommended_action,
            shadow_mode=shadow_mode,
            policy_version=policy_version,
            evidence_ledger_path=evidence_ledger_path,
            assessment_path=assessment_path,
            input_fingerprint=input_fingerprint,
            created_at=parse_datetime(created_at) or utc_now(),
        )

    def get_latest_identity_assessment_for_video(self, video_id: int) -> IdentityAssessment | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT id, video_id, target_pastor_id, extraction_result_id, state,
                       recommended_action, shadow_mode, policy_version, evidence_ledger_path,
                       assessment_path, input_fingerprint, created_at
                FROM identity_assessments
                WHERE video_id = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (video_id,),
            ).fetchone()
        return self._identity_assessment_from_row(row) if row is not None else None

    def ensure_speaker_profile(
        self,
        *,
        stable_key: str,
        display_label: str | None,
        lifecycle_state: str,
        created_reason: str,
    ) -> SpeakerProfile:
        created_at = utc_now().isoformat()
        with self.connect() as connection:
            try:
                cursor = connection.execute(
                    """
                    INSERT INTO speaker_profiles (
                        stable_key, display_label, lifecycle_state, created_reason, created_at
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (stable_key, display_label, lifecycle_state, created_reason, created_at),
                )
            except sqlite3.IntegrityError:
                row = connection.execute(
                    """
                    SELECT id, stable_key, display_label, lifecycle_state, created_reason, created_at
                    FROM speaker_profiles WHERE stable_key = ?
                    """,
                    (stable_key,),
                ).fetchone()
                if row is None:
                    raise
                return self._speaker_profile_from_row(row)
        return SpeakerProfile(
            id=int(cursor.lastrowid),
            stable_key=stable_key,
            display_label=display_label,
            lifecycle_state=lifecycle_state,
            created_reason=created_reason,
            created_at=parse_datetime(created_at) or utc_now(),
        )

    def get_speaker_profile(self, profile_id: int) -> SpeakerProfile | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT id, stable_key, display_label, lifecycle_state, created_reason, created_at
                FROM speaker_profiles WHERE id = ?
                """,
                (profile_id,),
            ).fetchone()
        return self._speaker_profile_from_row(row) if row is not None else None

    def ensure_pastor_speaker_binding(self, pastor_id: int, profile_id: int) -> int:
        created_at = utc_now().isoformat()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO pastor_speaker_bindings (
                    pastor_id, profile_id, binding_kind, created_at
                ) VALUES (?, ?, 'configured_requested_identity', ?)
                """,
                (pastor_id, profile_id, created_at),
            )
            row = connection.execute(
                "SELECT profile_id FROM pastor_speaker_bindings WHERE pastor_id = ?",
                (pastor_id,),
            ).fetchone()
        if row is None:
            raise RuntimeError("Pastor speaker binding was not persisted")
        return int(row["profile_id"])

    def add_speaker_observation(
        self,
        *,
        video_id: int,
        extraction_result_id: int,
        role: str,
        multiplicity_state: str,
        start_seconds: float,
        end_seconds: float,
        artifact_path: str,
        content_sha256: str,
        extractor_version: str,
        input_fingerprint: str,
    ) -> SpeakerObservation:
        created_at = utc_now().isoformat()
        with self.connect() as connection:
            try:
                cursor = connection.execute(
                    """
                    INSERT INTO speaker_observations (
                        video_id, extraction_result_id, role, multiplicity_state,
                        start_seconds, end_seconds, artifact_path, content_sha256,
                        extractor_version, input_fingerprint, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        video_id,
                        extraction_result_id,
                        role,
                        multiplicity_state,
                        start_seconds,
                        end_seconds,
                        artifact_path,
                        content_sha256,
                        extractor_version,
                        input_fingerprint,
                        created_at,
                    ),
                )
            except sqlite3.IntegrityError:
                row = connection.execute(
                    """
                    SELECT id, video_id, extraction_result_id, role, multiplicity_state,
                           start_seconds, end_seconds, artifact_path, content_sha256,
                           extractor_version, input_fingerprint, created_at
                    FROM speaker_observations WHERE input_fingerprint = ?
                    """,
                    (input_fingerprint,),
                ).fetchone()
                if row is None:
                    raise
                return self._speaker_observation_from_row(row)
        return SpeakerObservation(
            id=int(cursor.lastrowid),
            video_id=video_id,
            extraction_result_id=extraction_result_id,
            role=role,
            multiplicity_state=multiplicity_state,
            start_seconds=start_seconds,
            end_seconds=end_seconds,
            artifact_path=artifact_path,
            content_sha256=content_sha256,
            extractor_version=extractor_version,
            input_fingerprint=input_fingerprint,
            created_at=parse_datetime(created_at) or utc_now(),
        )

    def get_speaker_observation_by_fingerprint(
        self, input_fingerprint: str
    ) -> SpeakerObservation | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT id, video_id, extraction_result_id, role, multiplicity_state,
                       start_seconds, end_seconds, artifact_path, content_sha256,
                       extractor_version, input_fingerprint, created_at
                FROM speaker_observations WHERE input_fingerprint = ?
                """,
                (input_fingerprint,),
            ).fetchone()
        return self._speaker_observation_from_row(row) if row is not None else None

    def get_speaker_observation(self, observation_id: int) -> SpeakerObservation | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT id, video_id, extraction_result_id, role, multiplicity_state,
                       start_seconds, end_seconds, artifact_path, content_sha256,
                       extractor_version, input_fingerprint, created_at
                FROM speaker_observations WHERE id = ?
                """,
                (observation_id,),
            ).fetchone()
        return self._speaker_observation_from_row(row) if row is not None else None

    def get_latest_speaker_observation_for_video(
        self, video_id: int
    ) -> SpeakerObservation | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT id, video_id, extraction_result_id, role, multiplicity_state,
                       start_seconds, end_seconds, artifact_path, content_sha256,
                       extractor_version, input_fingerprint, created_at
                FROM speaker_observations WHERE video_id = ? ORDER BY id DESC LIMIT 1
                """,
                (video_id,),
            ).fetchone()
        return self._speaker_observation_from_row(row) if row is not None else None

    def add_speaker_name_claim(
        self,
        *,
        video_id: int,
        observation_id: int | None,
        display_name: str,
        normalized_name: str,
        claim_kind: str,
        channel: str,
        explicit_speaker_attribution: bool,
        correlation_group_id: str,
        provenance_json: str,
        artifact_path: str,
        claim_fingerprint: str,
        extractor_version: str,
    ) -> SpeakerNameClaim:
        created_at = utc_now().isoformat()
        with self.connect() as connection:
            try:
                cursor = connection.execute(
                    """
                    INSERT INTO speaker_name_claims (
                        video_id, observation_id, display_name, normalized_name, claim_kind,
                        channel, explicit_speaker_attribution, correlation_group_id,
                        provenance_json, artifact_path, claim_fingerprint, extractor_version,
                        created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        video_id,
                        observation_id,
                        display_name,
                        normalized_name,
                        claim_kind,
                        channel,
                        1 if explicit_speaker_attribution else 0,
                        correlation_group_id,
                        provenance_json,
                        artifact_path,
                        claim_fingerprint,
                        extractor_version,
                        created_at,
                    ),
                )
            except sqlite3.IntegrityError:
                row = connection.execute(
                    """
                    SELECT id, video_id, observation_id, display_name, normalized_name,
                           claim_kind, channel, explicit_speaker_attribution,
                           correlation_group_id, provenance_json, artifact_path,
                           claim_fingerprint, extractor_version, created_at
                    FROM speaker_name_claims WHERE claim_fingerprint = ?
                    """,
                    (claim_fingerprint,),
                ).fetchone()
                if row is None:
                    raise
                return self._speaker_name_claim_from_row(row)
        return SpeakerNameClaim(
            id=int(cursor.lastrowid),
            video_id=video_id,
            observation_id=observation_id,
            display_name=display_name,
            normalized_name=normalized_name,
            claim_kind=claim_kind,
            channel=channel,
            explicit_speaker_attribution=explicit_speaker_attribution,
            correlation_group_id=correlation_group_id,
            provenance_json=provenance_json,
            artifact_path=artifact_path,
            claim_fingerprint=claim_fingerprint,
            extractor_version=extractor_version,
            created_at=parse_datetime(created_at) or utc_now(),
        )

    def list_speaker_name_claims_for_video(self, video_id: int) -> list[SpeakerNameClaim]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT id, video_id, observation_id, display_name, normalized_name,
                       claim_kind, channel, explicit_speaker_attribution,
                       correlation_group_id, provenance_json, artifact_path,
                       claim_fingerprint, extractor_version, created_at
                FROM speaker_name_claims WHERE video_id = ? ORDER BY id
                """,
                (video_id,),
            ).fetchall()
        return [self._speaker_name_claim_from_row(row) for row in rows]

    def get_speaker_name_claim(self, claim_id: int) -> SpeakerNameClaim | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT id, video_id, observation_id, display_name, normalized_name,
                       claim_kind, channel, explicit_speaker_attribution,
                       correlation_group_id, provenance_json, artifact_path,
                       claim_fingerprint, extractor_version, created_at
                FROM speaker_name_claims WHERE id = ?
                """,
                (claim_id,),
            ).fetchone()
        return self._speaker_name_claim_from_row(row) if row is not None else None

    def add_profile_observation_event(
        self,
        *,
        profile_id: int,
        observation_id: int,
        action: str,
        reviewer: str,
        reason: str,
        event_fingerprint: str,
    ) -> int:
        return self._add_registry_event(
            table="profile_observation_events",
            columns=("profile_id", "observation_id", "action", "reviewer", "reason"),
            values=(profile_id, observation_id, action, reviewer, reason),
            event_fingerprint=event_fingerprint,
        )

    def add_profile_name_claim_event(
        self,
        *,
        profile_id: int | None,
        claim_id: int,
        action: str,
        reviewer: str,
        reason: str,
        event_fingerprint: str,
    ) -> int:
        return self._add_registry_event(
            table="profile_name_claim_events",
            columns=("profile_id", "claim_id", "action", "reviewer", "reason"),
            values=(profile_id, claim_id, action, reviewer, reason),
            event_fingerprint=event_fingerprint,
        )

    def add_profile_redirect_event(
        self,
        *,
        from_profile_id: int,
        to_profile_id: int | None,
        action: str,
        reviewer: str,
        reason: str,
        event_fingerprint: str,
    ) -> int:
        return self._add_registry_event(
            table="speaker_profile_redirect_events",
            columns=("from_profile_id", "to_profile_id", "action", "reviewer", "reason"),
            values=(from_profile_id, to_profile_id, action, reviewer, reason),
            event_fingerprint=event_fingerprint,
        )

    def _add_registry_event(
        self,
        *,
        table: str,
        columns: tuple[str, ...],
        values: tuple[object, ...],
        event_fingerprint: str,
    ) -> int:
        allowed_tables = {
            "profile_observation_events",
            "profile_name_claim_events",
            "speaker_profile_redirect_events",
        }
        if table not in allowed_tables:
            raise ValueError(f"Unsupported registry event table: {table}")
        created_at = utc_now().isoformat()
        column_sql = ", ".join((*columns, "event_fingerprint", "created_at"))
        placeholders = ", ".join("?" for _ in range(len(columns) + 2))
        with self.connect() as connection:
            try:
                cursor = connection.execute(
                    f"INSERT INTO {table} ({column_sql}) VALUES ({placeholders})",
                    (*values, event_fingerprint, created_at),
                )
            except sqlite3.IntegrityError:
                row = connection.execute(
                    f"SELECT id FROM {table} WHERE event_fingerprint = ?",
                    (event_fingerprint,),
                ).fetchone()
                if row is None:
                    raise
                return int(row["id"])
        return int(cursor.lastrowid)

    def get_effective_profile_redirect(self, from_profile_id: int) -> int | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT action, to_profile_id
                FROM speaker_profile_redirect_events
                WHERE from_profile_id = ? ORDER BY id DESC LIMIT 1
                """,
                (from_profile_id,),
            ).fetchone()
        if row is None or str(row["action"]) == "clear":
            return None
        return int(row["to_profile_id"])

    def is_observation_attached(self, profile_id: int, observation_id: int) -> bool:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT action FROM profile_observation_events
                WHERE profile_id = ? AND observation_id = ? ORDER BY id DESC LIMIT 1
                """,
                (profile_id, observation_id),
            ).fetchone()
        return row is not None and str(row["action"]) == "attach"

    def counts_by_table(self) -> dict[str, int]:
        with self.connect() as connection:
            source_count = connection.execute("SELECT COUNT(*) FROM sources").fetchone()[0]
            source_import_ref_count = connection.execute(
                "SELECT COUNT(*) FROM source_import_refs"
            ).fetchone()[0]
            pastor_count = connection.execute("SELECT COUNT(*) FROM pastors").fetchone()[0]
            video_count = connection.execute("SELECT COUNT(*) FROM videos").fetchone()[0]
            transcript_count = connection.execute("SELECT COUNT(*) FROM transcript_artifacts").fetchone()[0]
            segment_count = connection.execute("SELECT COUNT(*) FROM transcript_segments").fetchone()[0]
            extraction_count = connection.execute("SELECT COUNT(*) FROM extraction_results").fetchone()[0]
            review_count = connection.execute("SELECT COUNT(*) FROM review_results").fetchone()[0]
            excluded_count = connection.execute("SELECT COUNT(*) FROM excluded_videos").fetchone()[0]
            metadata_count = connection.execute("SELECT COUNT(*) FROM metadata_artifacts").fetchone()[0]
            identity_evidence_count = connection.execute("SELECT COUNT(*) FROM identity_evidence").fetchone()[0]
            identity_assessment_count = connection.execute("SELECT COUNT(*) FROM identity_assessments").fetchone()[0]
            speaker_profile_count = connection.execute("SELECT COUNT(*) FROM speaker_profiles").fetchone()[0]
            speaker_observation_count = connection.execute("SELECT COUNT(*) FROM speaker_observations").fetchone()[0]
            speaker_name_claim_count = connection.execute("SELECT COUNT(*) FROM speaker_name_claims").fetchone()[0]
            media_artifact_count = connection.execute("SELECT COUNT(*) FROM media_artifacts").fetchone()[0]
            media_attempt_count = connection.execute("SELECT COUNT(*) FROM media_acquisition_attempts").fetchone()[0]
        return {
            "sources": int(source_count),
            "source_import_refs": int(source_import_ref_count),
            "pastors": int(pastor_count),
            "videos": int(video_count),
            "transcript_artifacts": int(transcript_count),
            "transcript_segments": int(segment_count),
            "extraction_results": int(extraction_count),
            "review_results": int(review_count),
            "excluded_videos": int(excluded_count),
            "metadata_artifacts": int(metadata_count),
            "identity_evidence": int(identity_evidence_count),
            "identity_assessments": int(identity_assessment_count),
            "speaker_profiles": int(speaker_profile_count),
            "speaker_observations": int(speaker_observation_count),
            "speaker_name_claims": int(speaker_name_claim_count),
            "media_artifacts": int(media_artifact_count),
            "media_acquisition_attempts": int(media_attempt_count),
        }
