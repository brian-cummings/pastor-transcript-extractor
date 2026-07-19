from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from unittest.mock import patch

from typer.testing import CliRunner

from pastor_transcript_extractor.church_database_import import (
    canonical_youtube_source_key,
    import_church_sources,
    imported_source_ids,
    normalize_youtube_channel_url,
)
from pastor_transcript_extractor.cli import app
from pastor_transcript_extractor.models import SourceType, VideoStatus
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
                updated_at TEXT,
                youtube_channel_canonical_url TEXT,
                youtube_channel_id TEXT,
                youtube_channel_key TEXT,
                youtube_channel_resolver_version TEXT,
                youtube_channel_resolved_at TEXT,
                youtube_channel_resolution_error TEXT
            );
            INSERT INTO churches VALUES (
                1, 'Existing Church', 'https://directory.test/church/1',
                'https://www.youtube.com/@existing/featured', 'Existing Pastor',
                'found', '2026-07-19T00:00:00Z',
                'https://www.youtube.com/channel/UCaaaaaaaaaaaaaaaaaaaaaa',
                'UCaaaaaaaaaaaaaaaaaaaaaa',
                'youtube:channel:UCaaaaaaaaaaaaaaaaaaaaaa',
                'test-resolver-v1', '2026-07-19T00:00:00Z', NULL
            );
            INSERT INTO churches VALUES (
                2, 'New Church', 'https://directory.test/church/2/',
                'https://youtube.com/channel/UCbbbbbbbbbbbbbbbbbbbbbb/streams?view=1',
                'New Pastor', 'found', '2026-07-19T00:00:00Z',
                'https://www.youtube.com/channel/UCbbbbbbbbbbbbbbbbbbbbbb',
                'UCbbbbbbbbbbbbbbbbbbbbbb',
                'youtube:channel:UCbbbbbbbbbbbbbbbbbbbbbb',
                'test-resolver-v1', '2026-07-19T00:00:00Z', NULL
            );
            INSERT INTO churches VALUES (
                3, 'Incomplete Church', 'https://directory.test/church/3',
                NULL, 'No Channel', 'found', '2026-07-19T00:00:00Z',
                NULL, NULL, NULL, NULL, NULL, 'not resolved'
            );
            """
        )
        connection.commit()
        connection.close()
        return path

    def _app_database(
        self,
        root: Path,
        *,
        existing_url: str = "https://www.youtube.com/@existing",
    ) -> Database:
        database = Database(root / "app.db")
        database.initialize()
        pastor = database.add_pastor("existing", "Existing Pastor")
        database.add_source(
            existing_url,
            SourceType.CHANNEL,
            pastor.id,
        )
        return database

    def test_resolved_identity_reuses_existing_channel_id_url(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            church_path = self._church_database(root)
            database = self._app_database(
                root,
                existing_url=(
                    "https://www.youtube.com/channel/UCaaaaaaaaaaaaaaaaaaaaaa"
                ),
            )

            result = import_church_sources(database, church_path, dry_run=True)

            self.assertEqual({"created": 1, "reused": 1}, result.counts)
            self.assertEqual(1, len(database.list_sources()))

    def test_normalizes_channel_variants_without_losing_channel_id_case(self) -> None:
        normalized = normalize_youtube_channel_url(
            "https://youtube.com/channel/UCbbbbbbbbbbbbbbbbbbbbbb/streams?view=1"
        )

        self.assertEqual(
            "https://www.youtube.com/channel/UCbbbbbbbbbbbbbbbbbbbbbb", normalized
        )
        self.assertEqual(
            canonical_youtube_source_key(normalized),
            canonical_youtube_source_key(
                "https://www.youtube.com/channel/UCbbbbbbbbbbbbbbbbbbbbbb/featured"
            ),
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
            with database.connect() as connection:
                existing_identity = connection.execute(
                    "SELECT source_identity_key FROM sources WHERE url = ?",
                    ("https://www.youtube.com/@existing",),
                ).fetchone()["source_identity_key"]
            self.assertEqual(
                "youtube:channel:UCaaaaaaaaaaaaaaaaaaaaaa", existing_identity
            )

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


class ImportedSourceSyncTests(unittest.TestCase):
    def _database(self, root: Path, *, configure_archive: bool) -> tuple[Database, int]:
        database = Database(root / "app.db")
        database.initialize()
        pastor = database.add_pastor("sample", "Sample Pastor")
        source = database.add_source(
            "https://www.youtube.com/@sample",
            SourceType.CHANNEL,
            pastor.id,
        )
        database.add_video(
            source_id=source.id,
            pastor_id=pastor.id,
            youtube_video_id="syncvideo01",
            title="Sync Video",
            url="https://www.youtube.com/watch?v=syncvideo01",
            channel_name="Sample Church",
            published_at="2026-07-19T00:00:00Z",
            duration_seconds=3600,
        )
        if configure_archive:
            archive_root = root / "archive"
            archive_root.mkdir()
            database.configure_media_archive_destination(str(archive_root))
        return database, source.id

    def test_sync_registers_and_archives_each_source_after_extraction(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            database, source_id = self._database(root, configure_archive=True)
            pastor = database.get_pastor_by_slug("sample")
            self.assertIsNotNone(pastor)
            outside = database.add_video(
                source_id=source_id,
                pastor_id=pastor.id,
                youtube_video_id="outside0001",
                title="Outside Current Window",
                url="https://www.youtube.com/watch?v=outside0001",
                channel_name="Sample Church",
                published_at="2025-01-01T00:00:00Z",
                duration_seconds=3600,
                status=VideoStatus.TRANSCRIBING_LOCAL,
            )
            database.add_extraction_result(
                video_id=outside.id,
                version=1,
                proposed_text_path=str(root / "outside.md"),
                proposed_json_path=str(root / "outside.json"),
            )
            events: list[str] = []

            def extraction(*args, **kwargs):
                self.assertEqual({1}, kwargs["video_ids"])
                events.append("extract")
                return SimpleNamespace(processed=1, skipped=0, failed=0)

            def registration(*args, **kwargs):
                events.append("register")
                return SimpleNamespace(
                    artifacts_registered=2,
                    attempts_registered=1,
                    missing_paths=0,
                )

            def archival(*args, **kwargs):
                events.append("archive")
                self.assertEqual({1}, kwargs["video_ids"])
                self.assertTrue(kwargs["wait_for_lock"])
                return SimpleNamespace(
                    counts={
                        "archived": 0,
                        "already_archived": 0,
                        "destination_unavailable": 0,
                        "failed": 0,
                        "would_archive": 0,
                    },
                    items=(),
                )

            def discovery(**kwargs):
                events.append("discover")
                return SimpleNamespace(
                    selected_video_ids_by_source={source_id: (1,)}
                )

            def captions(**kwargs):
                self.assertEqual({1}, kwargs["video_ids"])
                events.append("captions")

            def transcribe(**kwargs):
                self.assertEqual({1}, kwargs["video_ids"])
                events.append("transcribe")

            with (
                patch(
                    "pastor_transcript_extractor.cli.imported_source_ids",
                    return_value=[source_id],
                ),
                patch(
                    "pastor_transcript_extractor.cli.discover_sources_service",
                    side_effect=discovery,
                ),
                patch(
                    "pastor_transcript_extractor.cli.fetch_captions_service",
                    side_effect=captions,
                ),
                patch(
                    "pastor_transcript_extractor.cli.transcribe_videos_service",
                    side_effect=transcribe,
                ),
                patch("pastor_transcript_extractor.cli.extract_batch", side_effect=extraction),
                patch(
                    "pastor_transcript_extractor.cli.backfill_existing_media_artifacts",
                    side_effect=registration,
                ),
                patch(
                    "pastor_transcript_extractor.cli.archive_source_media",
                    side_effect=archival,
                ),
            ):
                result = CliRunner().invoke(
                    app,
                    [
                        "sync-imported-sources",
                        "--extract",
                        "--archive-sources",
                        "--base-dir",
                        str(root),
                    ],
                )

            self.assertEqual(0, result.exit_code, result.output)
            self.assertEqual(
                ["discover", "captions", "transcribe", "extract", "register", "archive"],
                events,
            )
            self.assertEqual(
                VideoStatus.EXTRACTED,
                database.get_video_by_id(outside.id).status,
            )

    def test_sync_archive_mode_requires_a_configured_destination(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, source_id = self._database(root, configure_archive=False)
            with (
                patch(
                    "pastor_transcript_extractor.cli.imported_source_ids",
                    return_value=[source_id],
                ),
                patch(
                    "pastor_transcript_extractor.cli.discover_sources_service"
                ) as discover,
            ):
                result = CliRunner().invoke(
                    app,
                    [
                        "sync-imported-sources",
                        "--extract",
                        "--archive-sources",
                        "--base-dir",
                        str(root),
                    ],
                )

            self.assertNotEqual(0, result.exit_code)
            self.assertIn("No media archive destination is configured", result.output)
            discover.assert_not_called()

    def test_sync_stops_before_download_when_free_space_is_below_twenty_percent(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, source_id = self._database(root, configure_archive=True)
            with (
                patch(
                    "pastor_transcript_extractor.cli.imported_source_ids",
                    return_value=[source_id],
                ),
                patch(
                    "pastor_transcript_extractor.cli.shutil.disk_usage",
                    return_value=SimpleNamespace(total=100, used=81, free=19),
                ),
                patch(
                    "pastor_transcript_extractor.cli.discover_sources_service"
                ) as discover,
            ):
                result = CliRunner().invoke(
                    app,
                    [
                        "sync-imported-sources",
                        "--extract",
                        "--archive-sources",
                        "--base-dir",
                        str(root),
                    ],
                )

            self.assertEqual(1, result.exit_code)
            self.assertIn("at least 20.0%", result.output)
            discover.assert_not_called()

    def test_sync_overlaps_archival_with_the_next_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            database, first_source_id = self._database(root, configure_archive=True)
            second_pastor = database.add_pastor("second", "Second Pastor")
            second_source = database.add_source(
                "https://www.youtube.com/@second",
                SourceType.CHANNEL,
                second_pastor.id,
            )
            database.add_video(
                source_id=second_source.id,
                pastor_id=second_pastor.id,
                youtube_video_id="syncvideo02",
                title="Second Sync Video",
                url="https://www.youtube.com/watch?v=syncvideo02",
                channel_name="Second Church",
                published_at="2026-07-19T00:00:00Z",
                duration_seconds=3600,
            )
            archive_started = Event()
            second_discovery_started = Event()
            events: list[str] = []
            archive_calls = 0

            def discover(*, source_id, **kwargs):
                events.append(f"discover:{source_id}")
                if source_id == second_source.id:
                    self.assertTrue(archive_started.wait(timeout=2))
                    second_discovery_started.set()
                selected = database.list_videos_by_source_id(source_id)[0].id
                return SimpleNamespace(
                    selected_video_ids_by_source={source_id: (selected,)}
                )

            def archival(*args, **kwargs):
                nonlocal archive_calls
                archive_calls += 1
                current = archive_calls
                events.append(f"archive-start:{current}")
                if current == 1:
                    archive_started.set()
                    self.assertTrue(second_discovery_started.wait(timeout=2))
                events.append(f"archive-done:{current}")
                return SimpleNamespace(
                    counts={
                        "archived": 0,
                        "already_archived": 0,
                        "destination_unavailable": 0,
                        "failed": 0,
                        "would_archive": 0,
                    },
                    items=(),
                )

            no_registration = SimpleNamespace(
                artifacts_registered=0,
                attempts_registered=0,
                missing_paths=0,
            )
            no_extraction = SimpleNamespace(processed=0, skipped=1, failed=0)
            with (
                patch(
                    "pastor_transcript_extractor.cli.imported_source_ids",
                    return_value=[first_source_id, second_source.id],
                ),
                patch(
                    "pastor_transcript_extractor.cli.discover_sources_service",
                    side_effect=discover,
                ),
                patch("pastor_transcript_extractor.cli.fetch_captions_service"),
                patch("pastor_transcript_extractor.cli.transcribe_videos_service"),
                patch(
                    "pastor_transcript_extractor.cli.extract_batch",
                    return_value=no_extraction,
                ),
                patch(
                    "pastor_transcript_extractor.cli.backfill_existing_media_artifacts",
                    return_value=no_registration,
                ),
                patch(
                    "pastor_transcript_extractor.cli.archive_source_media",
                    side_effect=archival,
                ),
            ):
                result = CliRunner().invoke(
                    app,
                    [
                        "sync-imported-sources",
                        "--extract",
                        "--archive-sources",
                        "--base-dir",
                        str(root),
                    ],
                )

            self.assertEqual(0, result.exit_code, result.output)
            self.assertLess(
                events.index(f"discover:{second_source.id}"),
                events.index("archive-done:1"),
            )

    def test_sync_reserves_duration_projected_bytes_before_audio_download(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, source_id = self._database(root, configure_archive=False)
            constrained_disk = SimpleNamespace(
                total=1_000_000_000,
                used=700_000_000,
                free=300_000_000,
            )
            with (
                patch(
                    "pastor_transcript_extractor.cli.imported_source_ids",
                    return_value=[source_id],
                ),
                patch(
                    "pastor_transcript_extractor.cli.shutil.disk_usage",
                    return_value=constrained_disk,
                ),
                patch(
                    "pastor_transcript_extractor.cli.discover_sources_service",
                    return_value=SimpleNamespace(
                        selected_video_ids_by_source={source_id: (1,)}
                    ),
                ),
                patch("pastor_transcript_extractor.cli.fetch_captions_service"),
                patch(
                    "pastor_transcript_extractor.cli.transcribe_videos_service"
                ) as transcribe,
            ):
                result = CliRunner().invoke(
                    app,
                    [
                        "sync-imported-sources",
                        "--all-audio",
                        "--base-dir",
                        str(root),
                    ],
                )

            self.assertEqual(1, result.exit_code)
            self.assertIn("projected local free space", result.output)
            transcribe.assert_not_called()

    def test_sync_waits_for_pending_archive_to_restore_projected_reserve(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            database, first_source_id = self._database(root, configure_archive=True)
            second_pastor = database.add_pastor("reserve", "Reserve Pastor")
            second_source = database.add_source(
                "https://www.youtube.com/@reserve",
                SourceType.CHANNEL,
                second_pastor.id,
            )
            database.add_video(
                source_id=second_source.id,
                pastor_id=second_pastor.id,
                youtube_video_id="reservevid1",
                title="Reserve Video",
                url="https://www.youtube.com/watch?v=reservevid1",
                channel_name="Reserve Church",
                published_at="2026-07-19T00:00:00Z",
                duration_seconds=3600,
            )
            release_archive = Event()
            disk_calls = 0
            archive_calls = 0

            def disk_usage(path):
                nonlocal disk_calls
                disk_calls += 1
                free = 2_500_000_000 if disk_calls in {3, 4} else 5_000_000_000
                if disk_calls == 4:
                    release_archive.set()
                return SimpleNamespace(
                    total=10_000_000_000,
                    used=10_000_000_000 - free,
                    free=free,
                )

            def archival(*args, **kwargs):
                nonlocal archive_calls
                archive_calls += 1
                if archive_calls == 1:
                    self.assertTrue(release_archive.wait(timeout=2))
                return SimpleNamespace(
                    counts={
                        "archived": 1,
                        "already_archived": 0,
                        "destination_unavailable": 0,
                        "failed": 0,
                        "would_archive": 0,
                    },
                    items=(),
                )

            no_registration = SimpleNamespace(
                artifacts_registered=0,
                attempts_registered=0,
                missing_paths=0,
            )
            no_extraction = SimpleNamespace(processed=0, skipped=1, failed=0)
            with (
                patch(
                    "pastor_transcript_extractor.cli.imported_source_ids",
                    return_value=[first_source_id, second_source.id],
                ),
                patch(
                    "pastor_transcript_extractor.cli.shutil.disk_usage",
                    side_effect=disk_usage,
                ),
                patch(
                    "pastor_transcript_extractor.cli.discover_sources_service",
                    side_effect=lambda **kwargs: SimpleNamespace(
                        selected_video_ids_by_source={
                            kwargs["source_id"]: tuple(
                                video.id
                                for video in database.list_videos_by_source_id(
                                    kwargs["source_id"]
                                )
                            )
                        }
                    ),
                ),
                patch("pastor_transcript_extractor.cli.fetch_captions_service"),
                patch("pastor_transcript_extractor.cli.transcribe_videos_service"),
                patch(
                    "pastor_transcript_extractor.cli.extract_batch",
                    return_value=no_extraction,
                ),
                patch(
                    "pastor_transcript_extractor.cli.backfill_existing_media_artifacts",
                    return_value=no_registration,
                ),
                patch(
                    "pastor_transcript_extractor.cli.archive_source_media",
                    side_effect=archival,
                ),
            ):
                result = CliRunner().invoke(
                    app,
                    [
                        "sync-imported-sources",
                        "--all-audio",
                        "--extract",
                        "--archive-sources",
                        "--base-dir",
                        str(root),
                    ],
                )

            self.assertEqual(0, result.exit_code, result.output)
            self.assertIn("Waiting for archival before source", result.output)


if __name__ == "__main__":
    unittest.main()
