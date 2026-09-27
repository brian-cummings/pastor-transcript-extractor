from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import unittest

from pastor_transcript_extractor.media_artifacts import StageSourceAudioResult
from pastor_transcript_extractor.workflows.audio_stage import (
    AudioStageDependencies,
    AudioStageRequest,
    stage_audio_inputs,
)


class AudioStageWorkflowTests(unittest.TestCase):
    def test_retries_worker_failure_and_returns_verified_manifest_scope(self) -> None:
        attempts = 0
        caption_video_ids: list[set[int]] = []
        events: list[str] = []
        database = SimpleNamespace(
            get_video_by_id=lambda video_id: SimpleNamespace(
                id=video_id,
                youtube_video_id=f"video-{video_id}",
            )
        )
        paths = SimpleNamespace(logs=Path("logs"), root=Path("data"))

        def stage_video(*args, **kwargs):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise RuntimeError("temporary")
            return StageSourceAudioResult(
                kwargs["video_id"],
                f"video-{kwargs['video_id']}",
                "verified",
                "source_audio_staged",
                SimpleNamespace(),
                None,
                True,
            )

        def fetch_captions(**kwargs):
            caption_video_ids.append(kwargs["video_ids"])

        result = stage_audio_inputs(
            database,
            paths,
            SimpleNamespace(),
            AudioStageRequest(
                video_ids=frozenset({11}),
                download_jobs=1,
                resume_jobs=2,
            ),
            progress_callback=events.append,
            dependencies=AudioStageDependencies(
                stage_video=stage_video,
                write_manifest=lambda logs, results: Path("stage.json"),
                fetch_captions=fetch_captions,
            ),
        )

        self.assertEqual(2, attempts)
        self.assertEqual(Path("stage.json"), result.manifest_path)
        self.assertEqual(frozenset({11}), result.verified_video_ids)
        self.assertEqual(0, result.failed_count)
        self.assertEqual([{11}], caption_video_ids)
        self.assertTrue(any("Retrying 1" in event for event in events))


if __name__ == "__main__":
    unittest.main()
