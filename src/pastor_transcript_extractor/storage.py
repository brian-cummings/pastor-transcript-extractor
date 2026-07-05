from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from pastor_transcript_extractor.models import (
    ExcludedVideo,
    ExtractionResult,
    Pastor,
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
"""


class Database:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_path, timeout=30.0)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("PRAGMA synchronous = NORMAL")
            connection.execute("PRAGMA busy_timeout = 30000")
            yield connection
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

    def delete_transcript_segments_for_video(self, video_id: int) -> None:
        with self.connect() as connection:
            connection.execute("DELETE FROM transcript_segments WHERE video_id = ?", (video_id,))

    def delete_review_results_for_video(self, video_id: int) -> None:
        with self.connect() as connection:
            connection.execute("DELETE FROM review_results WHERE video_id = ?", (video_id,))

    def delete_extraction_results_for_video(self, video_id: int) -> None:
        with self.connect() as connection:
            connection.execute("DELETE FROM extraction_results WHERE video_id = ?", (video_id,))

    def delete_transcript_artifacts_for_video(self, video_id: int) -> None:
        with self.connect() as connection:
            connection.execute("DELETE FROM transcript_artifacts WHERE video_id = ?", (video_id,))

    def delete_video(self, video_id: int) -> None:
        self.delete_review_results_for_video(video_id)
        self.delete_extraction_results_for_video(video_id)
        self.delete_transcript_segments_for_video(video_id)
        self.delete_transcript_artifacts_for_video(video_id)
        with self.connect() as connection:
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

    def counts_by_table(self) -> dict[str, int]:
        with self.connect() as connection:
            source_count = connection.execute("SELECT COUNT(*) FROM sources").fetchone()[0]
            pastor_count = connection.execute("SELECT COUNT(*) FROM pastors").fetchone()[0]
            video_count = connection.execute("SELECT COUNT(*) FROM videos").fetchone()[0]
            transcript_count = connection.execute("SELECT COUNT(*) FROM transcript_artifacts").fetchone()[0]
            segment_count = connection.execute("SELECT COUNT(*) FROM transcript_segments").fetchone()[0]
            extraction_count = connection.execute("SELECT COUNT(*) FROM extraction_results").fetchone()[0]
            review_count = connection.execute("SELECT COUNT(*) FROM review_results").fetchone()[0]
            excluded_count = connection.execute("SELECT COUNT(*) FROM excluded_videos").fetchone()[0]
        return {
            "sources": int(source_count),
            "pastors": int(pastor_count),
            "videos": int(video_count),
            "transcript_artifacts": int(transcript_count),
            "transcript_segments": int(segment_count),
            "extraction_results": int(extraction_count),
            "review_results": int(review_count),
            "excluded_videos": int(excluded_count),
        }
