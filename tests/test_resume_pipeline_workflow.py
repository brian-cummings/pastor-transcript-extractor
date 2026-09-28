from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import unittest

from pastor_transcript_extractor.application import ExtractionBatchResult
from pastor_transcript_extractor.workflows.resume_pipeline import (
    ResumePipelineDependencies,
    ResumePipelineRequest,
    resume_staged_pipeline,
)


class ResumePipelineWorkflowTests(unittest.TestCase):
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
