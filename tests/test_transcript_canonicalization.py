from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from pastor_transcript_extractor.config import build_paths, ensure_directories
from pastor_transcript_extractor.models import SourceType, TranscriptSourceKind, VideoStatus
from pastor_transcript_extractor.storage import Database
from pastor_transcript_extractor.transcript_canonicalization import (
    CANONICAL_TRANSCRIPT_VERSION,
    materialize_canonical_transcript,
)


class TranscriptCanonicalizationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.paths = build_paths(Path(self.tempdir.name))
        ensure_directories(self.paths)
        self.database = Database(self.paths.database)
        self.database.initialize()
        pastor = self.database.add_pastor("sample", "Sample Pastor")
        source = self.database.add_source(
            "https://www.youtube.com/@sample",
            SourceType.CHANNEL,
            pastor_id=pastor.id,
        )
        self.video = self.database.add_video(
            source_id=source.id,
            pastor_id=pastor.id,
            youtube_video_id="canonical123",
            title="Worship Service",
            url="https://www.youtube.com/watch?v=canonical123",
            status=VideoStatus.TRANSCRIBED_LOCAL,
        )

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _source_artifact(self, segments: list[dict[str, object]]):
        raw = self.paths.root / "raw"
        raw.mkdir(parents=True, exist_ok=True)
        json_path = raw / "whisper.json"
        text_path = raw / "whisper.txt"
        json_path.write_text(json.dumps({"transcription": segments}), encoding="utf-8")
        text_path.write_text(
            "\n".join(str(item["text"]) for item in segments),
            encoding="utf-8",
        )
        return self.database.add_transcript_artifact(
            video_id=self.video.id,
            source_kind=TranscriptSourceKind.LOCAL_ASR,
            audio_path=None,
            raw_json_path=str(json_path),
            raw_text_path=str(text_path),
        )

    def test_full_transcript_is_deduplicated_before_any_block_split(self) -> None:
        source = self._source_artifact(
            [
                {
                    "offsets": {"from": 0, "to": 30000},
                    "text": "Father in heaven",
                },
                {
                    "offsets": {"from": 30000, "to": 60000},
                    "text": "Father in heaven thank you",
                },
                {
                    "offsets": {"from": 60000, "to": 90000},
                    "text": "thank you for grace",
                },
            ]
        )

        canonical = materialize_canonical_transcript(self.database, source)
        payload = json.loads(Path(canonical.raw_json_path).read_text(encoding="utf-8"))

        self.assertEqual("canonical", canonical.artifact_kind)
        self.assertEqual(CANONICAL_TRANSCRIPT_VERSION, canonical.transformation_version)
        self.assertEqual("Father in heaven thank you for grace", payload["text"])
        self.assertEqual([0, 1, 2], payload["segments"][0]["source_segment_indexes"])
        self.assertGreater(payload["normalization"]["deduplication_ratio"], 0.0)

    def test_canonicalization_is_idempotent_and_supersedes_source(self) -> None:
        source = self._source_artifact(
            [
                {
                    "offsets": {"from": 0, "to": 30000},
                    "text": "A complete sermon sentence.",
                }
            ]
        )

        first = materialize_canonical_transcript(self.database, source)
        second = materialize_canonical_transcript(self.database, source)
        artifacts = self.database.list_transcript_artifacts_for_video(self.video.id)

        self.assertEqual(first.id, second.id)
        self.assertEqual(2, len(artifacts))
        self.assertEqual(first.id, artifacts[0].superseded_by_artifact_id)
        self.assertEqual(
            first.id,
            self.database.get_latest_transcript_artifact_for_video(self.video.id).id,
        )

    def test_materializing_canonical_transcript_does_not_change_video_status(self) -> None:
        source = self._source_artifact(
            [
                {
                    "offsets": {"from": 0, "to": 30000},
                    "text": "A complete sermon sentence.",
                }
            ]
        )
        self.database.update_video_status(self.video.id, VideoStatus.EXTRACTED)

        materialize_canonical_transcript(self.database, source)

        self.assertEqual(
            VideoStatus.EXTRACTED,
            self.database.get_video_by_id(self.video.id).status,
        )


class TranscriptCanonicalizationMigrationTests(unittest.TestCase):
    def test_initialize_upgrades_legacy_transcript_artifact_table(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            database_path = Path(tmp) / "app.db"
            with sqlite3.connect(database_path) as connection:
                connection.execute(
                    """
                    CREATE TABLE transcript_artifacts (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        video_id INTEGER NOT NULL,
                        source_kind TEXT NOT NULL,
                        raw_json_path TEXT NULL,
                        raw_text_path TEXT NULL,
                        audio_path TEXT NULL,
                        created_at TEXT NOT NULL
                    )
                    """
                )

            Database(database_path).initialize()

            with sqlite3.connect(database_path) as connection:
                columns = {
                    str(row[1])
                    for row in connection.execute(
                        "PRAGMA table_info(transcript_artifacts)"
                    ).fetchall()
                }
            self.assertIn("artifact_kind", columns)
            self.assertIn("parent_transcript_artifact_id", columns)
            self.assertIn("superseded_by_artifact_id", columns)
