from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from pastor_transcript_extractor.config import ToolConfig, build_paths, ensure_directories
from pastor_transcript_extractor.models import SourceType, TranscriptSourceKind
from pastor_transcript_extractor.storage import Database
from pastor_transcript_extractor.workflows.caption_acquisition import (
    CaptionAcquisitionRequest,
    acquire_captions,
)


class CaptionAcquisitionWorkflowTests(unittest.TestCase):
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
        self.pastor_id = pastor.id
        self.tools = ToolConfig(
            whisper_cpp_bin=Path("/tmp/whisper-cli"),
            whisper_model_path=Path("/tmp/model.bin"),
            ffmpeg_bin="ffmpeg",
            yt_dlp_bin="yt-dlp",
            yt_dlp_js_runtimes=None,
        )

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def add_video(self, youtube_video_id: str, *, duration_seconds: float):
        return self.database.add_video(
            source_id=self.source.id,
            pastor_id=self.pastor_id,
            youtube_video_id=youtube_video_id,
            title=f"Sermon {youtube_video_id}",
            url=f"https://www.youtube.com/watch?v={youtube_video_id}",
            duration_seconds=duration_seconds,
        )

    def test_returns_structured_counts_and_reports_bypassed_videos(self) -> None:
        short_video = self.add_video("shortvideo1", duration_seconds=300)
        eligible_video = self.add_video("longvideo01", duration_seconds=1800)
        fetched_video_ids: list[int] = []
        events: list[str] = []

        def fetch_captions(database, paths, tools, video_id):
            del database, paths, tools
            fetched_video_ids.append(video_id)
            return SimpleNamespace(raw_text_path=Path("captions.txt"))

        result = acquire_captions(
            self.database,
            self.paths,
            self.tools,
            CaptionAcquisitionRequest(source_id=self.source.id),
            progress_callback=events.append,
            fetch_captions=fetch_captions,
        )

        self.assertEqual([eligible_video.id], fetched_video_ids)
        self.assertEqual(2, result.selected_count)
        self.assertEqual(1, result.processed_count)
        self.assertEqual(1, result.skipped_count)
        self.assertEqual(1, result.below_minimum_count)
        self.assertTrue(any("below the configured" in event for event in events))
        self.assertFalse(
            any(f"video #{short_video.id}:" in event for event in events)
        )

    def test_retries_unexpected_failure_after_first_pass(self) -> None:
        video = self.add_video("retryvideo1", duration_seconds=1800)
        attempts = 0
        events: list[str] = []

        def fetch_captions(database, paths, tools, video_id):
            nonlocal attempts
            del database, paths, tools
            self.assertEqual(video.id, video_id)
            attempts += 1
            if attempts == 1:
                raise RuntimeError("temporary")
            return SimpleNamespace(raw_text_path=Path("captions.txt"))

        result = acquire_captions(
            self.database,
            self.paths,
            self.tools,
            CaptionAcquisitionRequest(video_ids=frozenset({video.id})),
            progress_callback=events.append,
            fetch_captions=fetch_captions,
        )

        self.assertEqual(2, attempts)
        self.assertEqual(1, result.processed_count)
        self.assertEqual(0, result.failed_count)
        self.assertTrue(any("Retrying captions" in event for event in events))

    def test_skips_video_with_existing_local_transcript(self) -> None:
        existing = self.add_video("existingasr1", duration_seconds=1800)
        missing = self.add_video("missingtext1", duration_seconds=1800)
        self.database.add_transcript_artifact(
            video_id=existing.id,
            source_kind=TranscriptSourceKind.LOCAL_ASR,
            audio_path="audio.wav",
            raw_json_path="transcript.json",
            raw_text_path="transcript.txt",
        )
        fetched_video_ids: list[int] = []

        result = acquire_captions(
            self.database,
            self.paths,
            self.tools,
            CaptionAcquisitionRequest(video_ids=frozenset({existing.id, missing.id})),
            fetch_captions=lambda _database, _paths, _tools, video_id: (
                fetched_video_ids.append(video_id)
                or SimpleNamespace(raw_text_path=Path("captions.txt"))
            ),
        )

        self.assertEqual([missing.id], fetched_video_ids)
        self.assertEqual(1, result.skipped_count)


if __name__ == "__main__":
    unittest.main()
