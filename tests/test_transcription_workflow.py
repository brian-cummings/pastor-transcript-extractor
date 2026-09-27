from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from pastor_transcript_extractor.config import ToolConfig, build_paths, ensure_directories
from pastor_transcript_extractor.models import SourceType
from pastor_transcript_extractor.storage import Database
from pastor_transcript_extractor.transcription import PreparedTranscriptInput
from pastor_transcript_extractor.workflows.transcription import (
    TranscriptionRequest,
    transcribe_videos,
)
from pastor_transcript_extractor.workflows.transcription_events import (
    TranscriptionBatchFinished,
    TranscriptionProgressed,
    TranscriptionRetrying,
)


class TranscriptionWorkflowTests(unittest.TestCase):
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
        self.pastor = pastor
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
            pastor_id=self.pastor.id,
            youtube_video_id=youtube_video_id,
            title=f"Sermon {youtube_video_id}",
            url=f"https://www.youtube.com/watch?v={youtube_video_id}",
            duration_seconds=duration_seconds,
        )

    def prepared(self, video_id: int) -> PreparedTranscriptInput:
        video = self.database.get_video_by_id(video_id)
        return PreparedTranscriptInput(
            video_id=video.id,
            youtube_video_id=video.youtube_video_id,
            pastor_id=self.pastor.id,
            pastor_slug=self.pastor.slug,
            source_url=video.url,
            transcript_root=self.paths.root,
            metadata_path=self.paths.root / f"{video.id}.json",
            normalized_audio_path=self.paths.root / f"{video.id}.wav",
            whisper_output_base=self.paths.root / f"{video.id}-whisper",
        )

    def test_returns_structured_counts_and_emits_progress_events(self) -> None:
        self.add_video("shortvideo1", duration_seconds=300)
        eligible = self.add_video("longvideo01", duration_seconds=1800)
        events = []
        prepared_video_ids: list[int] = []

        def prepare(database, paths, tools, video_id, stage_callback, allow_network):
            del database, paths, tools, allow_network
            prepared_video_ids.append(video_id)
            stage_callback("normalizing")
            return self.prepared(video_id)

        def complete(database, tools, prepared, progress_callback, stage_callback):
            del database, tools, prepared
            stage_callback("transcribing")
            progress_callback(42)
            stage_callback("done")

        result = transcribe_videos(
            self.database,
            self.paths,
            self.tools,
            TranscriptionRequest(jobs=1, prep_jobs=1),
            event_callback=events.append,
            prepare=prepare,
            complete=complete,
        )

        self.assertEqual([eligible.id], prepared_video_ids)
        self.assertEqual(2, result.selected_count)
        self.assertEqual(1, result.processed_count)
        self.assertEqual(1, result.skipped_count)
        self.assertEqual(1, result.below_minimum_count)
        self.assertTrue(any(isinstance(event, TranscriptionProgressed) for event in events))

    def test_retries_failed_preparation_once_and_returns_final_failure_state(self) -> None:
        video = self.add_video("retryvideo1", duration_seconds=1800)
        attempts = 0
        events = []

        def prepare(database, paths, tools, video_id, stage_callback, allow_network):
            nonlocal attempts
            del database, paths, tools, stage_callback, allow_network
            attempts += 1
            if attempts == 1:
                raise RuntimeError("temporary")
            return self.prepared(video_id)

        def complete(database, tools, prepared, progress_callback, stage_callback):
            del database, tools, prepared, progress_callback, stage_callback

        result = transcribe_videos(
            self.database,
            self.paths,
            self.tools,
            TranscriptionRequest(
                jobs=1,
                prep_jobs=1,
                video_ids=frozenset({video.id}),
            ),
            event_callback=events.append,
            prepare=prepare,
            complete=complete,
        )

        self.assertEqual(2, attempts)
        self.assertEqual(1, result.processed_count)
        self.assertEqual(0, result.failed_count)
        self.assertEqual(frozenset(), result.failed_video_ids)
        self.assertEqual(2, sum(isinstance(event, TranscriptionBatchFinished) for event in events))
        self.assertTrue(any(isinstance(event, TranscriptionRetrying) for event in events))


if __name__ == "__main__":
    unittest.main()
