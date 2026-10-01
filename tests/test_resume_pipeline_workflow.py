from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import threading
import unittest

from pastor_transcript_extractor.application import ExtractionBatchResult
from pastor_transcript_extractor.workflows.caption_acquisition import (
    CaptionAcquisitionBlockedError,
)
from pastor_transcript_extractor.workflows.resume_pipeline import (
    ResumePipelineDependencies,
    ResumePipelineRequest,
    resume_staged_pipeline,
)


class ResumePipelineWorkflowTests(unittest.TestCase):
    def test_caption_scope_is_limited_to_stage_downloads(self) -> None:
        caption_video_ids: list[set[int]] = []
        database = SimpleNamespace(
            get_video_by_id=lambda _video_id: None,
            get_pastor_by_id=lambda _pastor_id: None,
            get_latest_transcript_artifact_for_video=lambda _video_id: None,
        )

        resume_staged_pipeline(
            database,
            SimpleNamespace(),
            ResumePipelineRequest(
                video_ids=frozenset({11, 12}),
                manifest_path=Path("stage.json"),
                acquire_captions=True,
                captions_only=True,
                skip_review=True,
            ),
            dependencies=ResumePipelineDependencies(
                fetch_captions=lambda **kwargs: caption_video_ids.append(
                    kwargs["video_ids"]
                ),
                extract=lambda *args, **kwargs: ExtractionBatchResult(0, 2, 0),
                caption_scope=lambda _path: {11},
            ),
        )

        self.assertEqual([{11}], caption_video_ids)

    def test_rate_limited_captions_retry_while_confirmed_misses_transcribe(
        self,
    ) -> None:
        fetch_scopes: list[set[int]] = []
        transcribed_video_ids: list[set[int]] = []
        sleeps: list[float] = []
        transcription_started = threading.Event()
        release_transcription = threading.Event()
        database = SimpleNamespace(
            get_video_by_id=lambda _video_id: None,
            get_pastor_by_id=lambda _pastor_id: None,
            get_latest_transcript_artifact_for_video=lambda _video_id: None,
        )

        def fetch_captions(**kwargs):
            scope = set(kwargs["video_ids"])
            fetch_scopes.append(scope)
            if len(fetch_scopes) == 1:
                kwargs["outcome_callback"](11, "unavailable")
                self.assertTrue(transcription_started.wait(timeout=1))
                kwargs["outcome_callback"](12, "unavailable")
                raise CaptionAcquisitionBlockedError("repeatedly rate limited")
            release_transcription.set()
            kwargs["outcome_callback"](13, "processed")
            kwargs["outcome_callback"](14, "processed")

        def transcribe(**kwargs):
            transcribed_video_ids.append(kwargs["video_ids"])
            transcription_started.set()
            self.assertTrue(release_transcription.wait(timeout=1))

        def sleeper(seconds):
            self.assertTrue(transcription_started.wait(timeout=1))
            sleeps.append(seconds)

        result = resume_staged_pipeline(
            database,
            SimpleNamespace(),
            ResumePipelineRequest(
                video_ids=frozenset({11, 12, 13, 14}),
                manifest_path=Path("stage.json"),
                acquire_captions=True,
                skip_review=True,
                jobs=2,
            ),
            dependencies=ResumePipelineDependencies(
                fetch_captions=fetch_captions,
                transcribe=transcribe,
                extract=lambda *args, **kwargs: ExtractionBatchResult(0, 2, 0),
                caption_scope=lambda _path: {11, 12, 13, 14},
                caption_retry_sleeper=sleeper,
            ),
        )

        self.assertEqual([{11, 12, 13, 14}, {13, 14}], fetch_scopes)
        self.assertCountEqual([{11}, {12}], transcribed_video_ids)
        self.assertEqual(900.0, sum(sleeps))
        self.assertTrue(all(seconds <= 30.0 for seconds in sleeps))
        self.assertFalse(result.captions_blocked)

    def test_runs_offline_stages_in_order_and_returns_structured_result(self) -> None:
        calls: list[str] = []
        video = SimpleNamespace(id=11, pastor_id=7)
        pastor = SimpleNamespace(id=7, slug="sample-church")
        database = SimpleNamespace(
            get_video_by_id=lambda video_id: video,
            get_pastor_by_id=lambda pastor_id: pastor,
        )
        review_batch = SimpleNamespace(pastors=(), prepared=0, failed=0)

        def transcribe(**kwargs):
            self.assertFalse(kwargs["allow_network"])
            self.assertTrue(kwargs["missing_only"])
            calls.append("transcribe")

        def extract(*args, **kwargs):
            self.assertEqual("typesafe", kwargs["recording_verifier_backend"])
            self.assertEqual("jev-1.13.0", kwargs["recording_verifier_model"])
            calls.append("extract")
            return ExtractionBatchResult(1, 0, 0)

        result = resume_staged_pipeline(
            database,
            SimpleNamespace(),
            ResumePipelineRequest(
                video_ids=frozenset({11}),
                manifest_path=Path("stage.json"),
                run_identity=True,
                recording_verifier_backend="typesafe",
                recording_verifier_model="jev-1.13.0",
            ),
            dependencies=ResumePipelineDependencies(
                transcribe=transcribe,
                extract=extract,
                ensure_media=lambda *args, **kwargs: calls.append("media"),
                run_identity=lambda *args, **kwargs: calls.append("identity"),
                prepare_reviews=lambda *args, **kwargs: (
                    calls.append("review") or review_batch
                ),
            ),
        )

        self.assertEqual(
            ["transcribe", "extract", "media", "identity", "review"],
            calls,
        )
        self.assertEqual(1, result.video_count)
        self.assertEqual(1, result.extraction.processed)
        self.assertEqual(1, result.review_batch_count)


if __name__ == "__main__":
    unittest.main()
