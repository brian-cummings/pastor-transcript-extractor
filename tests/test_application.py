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
    def test_extract_batch_runs_independent_videos_with_requested_workers(self) -> None:
        videos = [
            SimpleNamespace(id=1, pastor_id=1, title="First", status=VideoStatus.DISCOVERED),
            SimpleNamespace(id=2, pastor_id=1, title="Second", status=VideoStatus.DISCOVERED),
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

    def test_extract_batch_rejects_nonpositive_worker_count(self) -> None:
        with self.assertRaisesRegex(ValueError, "at least 1"):
            extract_batch(
                SimpleNamespace(),
                build_paths(Path("/tmp/unused")),
                workers=0,
            )


if __name__ == "__main__":
    unittest.main()
