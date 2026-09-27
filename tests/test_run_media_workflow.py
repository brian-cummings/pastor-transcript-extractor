from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from pastor_transcript_extractor.config import build_paths, ensure_directories
from pastor_transcript_extractor.models import SourceType
from pastor_transcript_extractor.storage import Database
from pastor_transcript_extractor.workflows.run_media import (
    RunMediaDependencies,
    RunMediaRequest,
    ensure_and_archive_run_media,
)


class RunMediaWorkflowTests(unittest.TestCase):
    def test_returns_structured_audio_counts_without_archive_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = build_paths(Path(tmp))
            ensure_directories(paths)
            database = Database(paths.database)
            database.initialize()
            pastor = database.add_pastor("sample-church", "Sample Church")
            source = database.add_source(
                "https://www.youtube.com/@samplechurch",
                SourceType.CHANNEL,
                pastor_id=pastor.id,
            )
            video = database.add_video(
                source_id=source.id,
                pastor_id=pastor.id,
                youtube_video_id="mediavideo1",
                title="Media sermon",
                url="https://www.youtube.com/watch?v=mediavideo1",
            )
            calls: list[int] = []
            events: list[tuple[str, str | None]] = []

            def ensure_audio(*args, **kwargs):
                calls.append(kwargs["video_id"])
                return SimpleNamespace(
                    outcome="verified",
                    downloaded=True,
                    reason_code="downloaded_and_normalized",
                )

            result = ensure_and_archive_run_media(
                database,
                paths,
                RunMediaRequest(video_ids=frozenset({video.id})),
                progress_callback=lambda message, style: events.append(
                    (message, style)
                ),
                dependencies=RunMediaDependencies(
                    has_isolated_sermon=lambda database, video_id: (
                        True,
                        "isolated_sermon",
                    ),
                    get_verified_media=lambda database, video_id: None,
                    build_tools=lambda: SimpleNamespace(),
                    ensure_audio=ensure_audio,
                ),
            )

            self.assertEqual([video.id], calls)
            self.assertEqual(1, result.eligible_count)
            self.assertEqual(1, result.verified_count)
            self.assertEqual(1, result.downloaded_count)
            self.assertFalse(result.archive_configured)
            self.assertTrue(
                any("archive skipped" in message for message, _ in events)
            )


if __name__ == "__main__":
    unittest.main()
