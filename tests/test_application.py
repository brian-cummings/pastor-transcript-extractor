from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from threading import Barrier, Lock
from types import SimpleNamespace
from unittest.mock import patch

from pastor_transcript_extractor.application import extract_batch
from pastor_transcript_extractor.config import build_paths
from pastor_transcript_extractor.models import VideoStatus


class ExtractionParallelismTests(unittest.TestCase):
    def test_extract_batch_bypasses_video_above_maximum(self) -> None:
        video = SimpleNamespace(
            id=1,
            pastor_id=None,
            title="Seven-hour stream",
            status=VideoStatus.TRANSCRIBED_LOCAL,
            duration_seconds=7 * 60 * 60,
            published_at=None,
        )
        database = SimpleNamespace(list_videos=lambda: [video])
        events: list[str] = []

        with tempfile.TemporaryDirectory() as tmp, patch(
            "pastor_transcript_extractor.application.extract_video",
        ) as extract:
            result = extract_batch(
                database,
                build_paths(Path(tmp)),
                classifier="rules",
                event_callback=events.append,
            )

        self.assertEqual(0, result.processed)
        self.assertEqual(1, result.skipped)
        self.assertTrue(any("above" in event and "10800" in event for event in events))
        extract.assert_not_called()

    def test_extract_batch_includes_targetless_video(self) -> None:
        video = SimpleNamespace(
            id=1,
            pastor_id=None,
            title="Publisher Video",
            status=VideoStatus.TRANSCRIBED_LOCAL,
            duration_seconds=None,
            published_at=None,
        )
        database = SimpleNamespace(
            list_videos=lambda: [video],
            get_latest_transcript_artifact_for_video=lambda _: SimpleNamespace(),
            get_latest_extraction_result_for_video=lambda _: None,
            update_video_status=lambda *args: None,
        )

        with tempfile.TemporaryDirectory() as tmp, patch(
            "pastor_transcript_extractor.application.extract_video",
        ) as extract:
            result = extract_batch(
                database,
                build_paths(Path(tmp)),
                classifier="rules",
            )

        self.assertEqual(1, result.processed)
        self.assertEqual(0, result.skipped)
        extract.assert_called_once()

    def test_extract_batch_runs_independent_videos_with_requested_workers(self) -> None:
        videos = [
            SimpleNamespace(
                id=1,
                pastor_id=1,
                title="First",
                status=VideoStatus.DISCOVERED,
                duration_seconds=None,
                published_at=None,
            ),
            SimpleNamespace(
                id=2,
                pastor_id=1,
                title="Second",
                status=VideoStatus.DISCOVERED,
                duration_seconds=None,
                published_at=None,
            ),
        ]
        database = SimpleNamespace(
            list_videos=lambda: videos,
            get_latest_transcript_artifact_for_video=lambda _: SimpleNamespace(),
            get_latest_extraction_result_for_video=lambda _: None,
            update_video_status=lambda *args: None,
        )
        barrier = Barrier(2)
        lock = Lock()
        active = 0
        maximum_active = 0

        def extract(*args, **kwargs):
            nonlocal active, maximum_active
            with lock:
                active += 1
                maximum_active = max(maximum_active, active)
            barrier.wait(timeout=2)
            with lock:
                active -= 1

        with tempfile.TemporaryDirectory() as tmp, patch(
            "pastor_transcript_extractor.application.extract_video",
            side_effect=extract,
        ):
            result = extract_batch(
                database,
                build_paths(Path(tmp)),
                classifier="rules",
                workers=2,
            )

        self.assertEqual(2, result.processed)
        self.assertEqual(0, result.failed)
        self.assertEqual(2, maximum_active)

    def test_extract_batch_progress_identifies_the_video(self) -> None:
        video = SimpleNamespace(
            id=1620,
            pastor_id=1,
            title="Sermon",
            status=VideoStatus.DISCOVERED,
            duration_seconds=None,
            published_at=None,
        )
        database = SimpleNamespace(
            list_videos=lambda: [video],
            get_latest_transcript_artifact_for_video=lambda _: SimpleNamespace(),
            get_latest_extraction_result_for_video=lambda _: None,
            update_video_status=lambda *args: None,
        )
        progress_events = []

        def extract(*args, **kwargs):
            kwargs["progress"]("coarse", 4, 23)

        with tempfile.TemporaryDirectory() as tmp, patch(
            "pastor_transcript_extractor.application.extract_video",
            side_effect=extract,
        ):
            result = extract_batch(
                database,
                build_paths(Path(tmp)),
                classifier="rules",
                progress_callback=lambda stage, current, total: progress_events.append(
                    (stage, current, total)
                ),
            )

        self.assertEqual(1, result.processed)
        self.assertEqual([("video #1620 coarse", 4, 23)], progress_events)

    def test_extract_batch_retries_failure_after_first_pass(self) -> None:
        videos = [
            SimpleNamespace(
                id=1,
                pastor_id=1,
                title="Transient failure",
                status=VideoStatus.DISCOVERED,
                duration_seconds=None,
                published_at=None,
            ),
            SimpleNamespace(
                id=2,
                pastor_id=1,
                title="Independent success",
                status=VideoStatus.DISCOVERED,
                duration_seconds=None,
                published_at=None,
            ),
        ]
        database = SimpleNamespace(
            list_videos=lambda: videos,
            get_latest_transcript_artifact_for_video=lambda _: SimpleNamespace(),
            get_latest_extraction_result_for_video=lambda _: None,
            update_video_status=lambda *args: None,
        )
        attempts: list[int] = []

        def extract(_database, _paths, video_id, **_kwargs):
            attempts.append(video_id)
            if video_id == 1 and attempts.count(1) == 1:
                raise RuntimeError("temporary")

        events: list[str] = []
        with tempfile.TemporaryDirectory() as tmp, patch(
            "pastor_transcript_extractor.application.extract_video",
            side_effect=extract,
        ):
            result = extract_batch(
                database,
                build_paths(Path(tmp)),
                classifier="rules",
                workers=1,
                event_callback=events.append,
            )

        self.assertEqual([1, 2, 1], attempts)
        self.assertEqual(2, result.processed)
        self.assertEqual(0, result.failed)
        self.assertEqual((), result.failed_video_ids)
        self.assertTrue(any("Retrying 1 extraction" in event for event in events))

    def test_extract_batch_rejects_nonpositive_worker_count(self) -> None:
        with self.assertRaisesRegex(ValueError, "at least 1"):
            extract_batch(
                SimpleNamespace(),
                build_paths(Path("/tmp/unused")),
                workers=0,
            )


if __name__ == "__main__":
    unittest.main()
