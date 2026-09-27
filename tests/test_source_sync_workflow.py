from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from pastor_transcript_extractor.config import build_paths, ensure_directories
from pastor_transcript_extractor.models import SourceType
from pastor_transcript_extractor.storage import Database
from pastor_transcript_extractor.workflows.source_sync import (
    SourceSyncDependencies,
    SourceSyncDiskReserveError,
    SourceSyncRequest,
    sync_imported_sources_workflow,
)


class SourceSyncWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.paths = build_paths(Path(self.tempdir.name))
        ensure_directories(self.paths)
        self.database = Database(self.paths.database)
        self.database.initialize()
        pastor = self.database.add_pastor("sample-church", "Sample Church")
        self.source = self.database.add_source(
            "https://www.youtube.com/@samplechurch",
            SourceType.CHANNEL,
            pastor_id=pastor.id,
        )
        self.video = self.database.add_video(
            source_id=self.source.id,
            pastor_id=pastor.id,
            youtube_video_id="syncvideo01",
            title="Sync sermon",
            url="https://www.youtube.com/watch?v=syncvideo01",
            duration_seconds=1800,
        )

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_returns_structured_counts_and_preserves_stage_order(self) -> None:
        calls: list[str] = []
        events: list[str] = []

        def discover(**kwargs):
            calls.append("discover")
            return SimpleNamespace(
                selected_video_ids_by_source={
                    kwargs["source_id"]: (self.video.id,)
                }
            )

        def captions(**kwargs):
            self.assertEqual({self.video.id}, kwargs["video_ids"])
            calls.append("captions")

        def transcribe(**kwargs):
            self.assertEqual({self.video.id}, kwargs["video_ids"])
            calls.append("transcribe")

        def extract(*args, **kwargs):
            self.assertEqual({self.video.id}, kwargs["video_ids"])
            calls.append("extract")
            return SimpleNamespace(processed=1, skipped=2, failed=3)

        def register(*args, **kwargs):
            self.assertEqual(self.video.id, kwargs["video_id"])
            calls.append("register")
            return SimpleNamespace(artifacts_registered=2, missing_paths=1)

        result = sync_imported_sources_workflow(
            self.database,
            self.paths,
            SourceSyncRequest(extract_new=True),
            progress_callback=events.append,
            dependencies=SourceSyncDependencies(
                list_imported_sources=lambda database, provider: [self.source.id],
                discover=discover,
                fetch_captions=captions,
                transcribe=transcribe,
                extract=extract,
                register_media=register,
                disk_usage=lambda path: SimpleNamespace(
                    total=10_000_000_000,
                    used=1_000_000_000,
                    free=9_000_000_000,
                ),
            ),
        )

        self.assertEqual(
            ["discover", "captions", "transcribe", "extract", "register"],
            calls,
        )
        self.assertEqual(1, result.source_count)
        self.assertEqual(1, result.selected_video_count)
        self.assertEqual(1, result.extracted_count)
        self.assertEqual(2, result.extraction_skipped_count)
        self.assertEqual(3, result.extraction_failed_count)
        self.assertEqual(2, result.registered_artifact_count)
        self.assertEqual(1, result.missing_path_count)
        self.assertTrue(any("Synchronized 1 imported source" in event for event in events))

    def test_raises_domain_error_before_discovery_when_disk_reserve_is_low(self) -> None:
        events: list[str] = []
        discovery_calls = 0

        def discover(**kwargs):
            nonlocal discovery_calls
            discovery_calls += 1

        dependencies = SourceSyncDependencies(
            list_imported_sources=lambda database, provider: [self.source.id],
            discover=discover,
            disk_usage=lambda path: SimpleNamespace(total=100, used=81, free=19),
            archive_lock_held=lambda path: False,
        )

        with self.assertRaises(SourceSyncDiskReserveError):
            sync_imported_sources_workflow(
                self.database,
                self.paths,
                SourceSyncRequest(),
                progress_callback=events.append,
                dependencies=dependencies,
            )

        self.assertEqual(0, discovery_calls)
        self.assertTrue(any("at least 20.0%" in event for event in events))


if __name__ == "__main__":
    unittest.main()
