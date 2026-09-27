from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import unittest

from pastor_transcript_extractor.media_artifacts import StageSourceAudioResult
from pastor_transcript_extractor.workflows.audio_stage import (
    AudioStageDependencies,
    AudioStageRequest,
    AudioStageScopeDependencies,
    AudioStageScopeRequest,
    resolve_audio_stage_scope,
    stage_audio_inputs,
)


class AudioStageWorkflowTests(unittest.TestCase):
    def test_resolves_selected_sources_without_contacting_unselected_sources(self) -> None:
        calls = []
        database = SimpleNamespace(
            get_source_by_id=lambda source_id: SimpleNamespace(id=source_id)
        )

        def discover(limit, all_videos, source_id, base_dir):
            calls.append(source_id)
            return SimpleNamespace(
                selected_video_ids_by_source={source_id: (source_id * 10,)}
            )

        result = resolve_audio_stage_scope(
            AudioStageScopeRequest(source_ids=(2, 4), limit=3),
            dependencies=AudioStageScopeDependencies(
                get_database=lambda base_dir: database,
                add_source=lambda *args, **kwargs: None,
                delete_source=lambda *args, **kwargs: None,
                discover=discover,
                select_existing=lambda *args, **kwargs: set(),
            ),
        )

        self.assertEqual([2, 4], calls)
        self.assertEqual(frozenset({20, 40}), result.video_ids)

    def test_empty_all_scope_returns_explained_skip(self) -> None:
        events = []
        database = SimpleNamespace(list_processing_enabled_sources=lambda: [])

        result = resolve_audio_stage_scope(
            AudioStageScopeRequest(all_sources=True),
            progress_callback=events.append,
            dependencies=AudioStageScopeDependencies(
                get_database=lambda base_dir: database,
                add_source=lambda *args, **kwargs: None,
                delete_source=lambda *args, **kwargs: None,
                discover=lambda *args, **kwargs: None,
                select_existing=lambda *args, **kwargs: set(),
            ),
        )

        self.assertEqual("No processing-enabled sources configured.", result.skip_reason)
        self.assertEqual([result.skip_reason], events)

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
