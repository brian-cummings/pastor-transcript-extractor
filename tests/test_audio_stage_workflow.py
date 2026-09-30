from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from pastor_transcript_extractor.audio_staging import (
    load_audio_stage_downloaded_video_ids,
    write_audio_stage_manifest,
)
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
            ),
            get_latest_transcript_artifact_for_video=lambda _video_id: None,
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

    def test_bypasses_acquired_transcripts_and_fetches_captions_only_for_downloads(
        self,
    ) -> None:
        staged_video_ids: list[int] = []
        manifest_video_ids: list[int] = []
        caption_video_ids: list[set[int]] = []
        events: list[str] = []
        database = SimpleNamespace(
            get_latest_transcript_artifact_for_video=lambda video_id: (
                SimpleNamespace() if video_id == 10 else None
            )
        )

        def stage_video(*args, **kwargs):
            video_id = kwargs["video_id"]
            staged_video_ids.append(video_id)
            return StageSourceAudioResult(
                video_id,
                f"video-{video_id}",
                "verified",
                "source_audio_staged" if video_id == 11 else "verified_existing_source",
                SimpleNamespace(),
                None,
                video_id == 11,
            )

        def write_manifest(_logs, results):
            manifest_video_ids.extend(result.video_id for result in results)
            return Path("stage.json")

        result = stage_audio_inputs(
            database,
            SimpleNamespace(logs=Path("logs"), root=Path("data")),
            SimpleNamespace(),
            AudioStageRequest(
                video_ids=frozenset({10, 11, 12}),
                download_jobs=1,
                resume_jobs=2,
            ),
            progress_callback=events.append,
            dependencies=AudioStageDependencies(
                stage_video=stage_video,
                write_manifest=write_manifest,
                fetch_captions=lambda **kwargs: caption_video_ids.append(
                    kwargs["video_ids"]
                ),
            ),
        )

        self.assertCountEqual([11, 12], staged_video_ids)
        self.assertCountEqual([11, 12], manifest_video_ids)
        self.assertEqual([{11}], caption_video_ids)
        self.assertEqual(frozenset({11, 12}), result.verified_video_ids)
        self.assertTrue(any("Bypassing 1" in event for event in events))

    def test_manifest_preserves_downloaded_caption_scope(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest = write_audio_stage_manifest(
                Path(directory),
                [
                    StageSourceAudioResult(
                        11, "video-11", "verified", "source_audio_staged",
                        SimpleNamespace(
                            id=1,
                            artifact_path="11.wav",
                            content_sha256="one",
                            byte_size=1,
                            duration_seconds=1.0,
                        ),
                        None,
                        True,
                    ),
                    StageSourceAudioResult(
                        12, "video-12", "verified", "verified_existing_source",
                        SimpleNamespace(
                            id=2,
                            artifact_path="12.wav",
                            content_sha256="two",
                            byte_size=2,
                            duration_seconds=2.0,
                        ),
                        None,
                        False,
                    ),
                ],
            )

            self.assertEqual({11}, load_audio_stage_downloaded_video_ids(manifest))


if __name__ == "__main__":
    unittest.main()
