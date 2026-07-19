from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from pastor_transcript_extractor.church_database_import import (
    canonical_youtube_source_key,
    import_church_sources,
    imported_source_ids,
    normalize_youtube_channel_url,
)
from pastor_transcript_extractor.models import SourceType
from pastor_transcript_extractor.storage import Database


class ChurchDatabaseImportTests(unittest.TestCase):
    def _church_database(self, root: Path) -> Path:
        path = root / "churches.db"
        connection = sqlite3.connect(path)
        connection.executescript(
            """
            CREATE TABLE churches (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                source_url TEXT NOT NULL,
                youtube_channel TEXT,
                pastor_name TEXT,
                status TEXT NOT NULL,
                updated_at TEXT
            );
            INSERT INTO churches VALUES (
                1, 'Existing Church', 'https://directory.test/church/1',
                'https://www.youtube.com/@existing/featured', 'Existing Pastor',
                'found', '2026-07-19T00:00:00Z'
            );
            INSERT INTO churches VALUES (
                2, 'New Church', 'https://directory.test/church/2/',
                'https://youtube.com/channel/UCAbCdEf/streams?view=1', 'New Pastor',
                'found', '2026-07-19T00:00:00Z'
            );
            INSERT INTO churches VALUES (
                3, 'Incomplete Church', 'https://directory.test/church/3',
                NULL, 'No Channel', 'found', '2026-07-19T00:00:00Z'
            );
            """
        )
        connection.commit()
        connection.close()
        return path

    def _app_database(self, root: Path) -> Database:
        database = Database(root / "app.db")
        database.initialize()
        pastor = database.add_pastor("existing", "Existing Pastor")
        database.add_source(
            "https://www.youtube.com/@existing",
            SourceType.CHANNEL,
            pastor.id,
        )
        return database

    def test_normalizes_channel_variants_without_losing_channel_id_case(self) -> None:
        normalized = normalize_youtube_channel_url(
            "https://youtube.com/channel/UCAbCdEf/streams?view=1"
        )

        self.assertEqual("https://www.youtube.com/channel/UCAbCdEf", normalized)
        self.assertEqual(
            canonical_youtube_source_key(normalized),
            canonical_youtube_source_key("https://www.youtube.com/channel/UCAbCdEf/featured"),
        )

    def test_dry_run_reports_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            church_path = self._church_database(root)
            database = self._app_database(root)

            result = import_church_sources(database, church_path, dry_run=True)

            self.assertEqual({"created": 1, "reused": 1}, result.counts)
            self.assertEqual([], imported_source_ids(database))
            self.assertEqual(1, len(database.list_sources()))

    def test_apply_is_idempotent_and_tracks_existing_sources(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            church_path = self._church_database(root)
            database = self._app_database(root)

            first = import_church_sources(database, church_path, dry_run=False)
            replay = import_church_sources(database, church_path, dry_run=False)

            self.assertEqual({"created": 1, "reused": 1}, first.counts)
            self.assertEqual({"unchanged": 2}, replay.counts)
            self.assertEqual(2, len(imported_source_ids(database)))
            self.assertEqual(2, len(database.list_sources()))

            manual_pastor = database.add_pastor("manual", "Manual Pastor")
            database.add_source(
                "https://www.youtube.com/@manual",
                SourceType.CHANNEL,
                manual_pastor.id,
            )
            self.assertEqual(2, len(imported_source_ids(database)))
            self.assertEqual(3, len(database.list_sources()))

    def test_changed_external_assignment_becomes_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            church_path = self._church_database(root)
            database = self._app_database(root)
            import_church_sources(database, church_path, dry_run=False)
            connection = sqlite3.connect(church_path)
            connection.execute(
                "UPDATE churches SET pastor_name = 'Replacement Pastor' WHERE id = 2"
            )
            connection.commit()
            connection.close()

            result = import_church_sources(database, church_path, dry_run=False)

            self.assertEqual({"conflict": 1, "unchanged": 1}, result.counts)
            imported = database.get_pastor_by_slug("churchdb-2")
            self.assertIsNotNone(imported)
            self.assertEqual("New Pastor", imported.display_name)


if __name__ == "__main__":
    unittest.main()
