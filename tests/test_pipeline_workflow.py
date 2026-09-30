from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import threading
import unittest

from pastor_transcript_extractor.application import ExtractionBatchResult
from pastor_transcript_extractor.models import VideoStatus
from pastor_transcript_extractor.workflows.caption_acquisition import (
    CaptionAcquisitionBlockedError,
)
from pastor_transcript_extractor.workflows.pipeline import (
    PipelineDependencies,
    PipelineRequest,
    PipelineScope,
    PostContentIdentityRequest,
    run_pipeline,
    run_post_content_identity,
    validate_pipeline_request,
)


class PipelineWorkflowTests(unittest.TestCase):
    def test_post_content_identity_uses_guarded_automatic_policy(self) -> None:
        calls = []
        events = []

        run_post_content_identity(
            PostContentIdentityRequest(base_dir=Path("data"), jobs=3),
            event_callback=events.append,
            identity_runner=lambda **kwargs: calls.append(kwargs),
        )

        self.assertEqual(1, len(calls))
        self.assertTrue(calls[0]["all_extractions"])
        self.assertTrue(calls[0]["apply_automatic"])
        self.assertFalse(calls[0]["plan_only"])
        self.assertEqual(3, calls[0]["jobs"])
        self.assertIn("Run identity stage", events[0])

    def _dependencies(self, database, calls):
        def record(name, result=None):
            def operation(*args, **kwargs):
                calls.append((name, args, kwargs))
                return result

            return operation

        return PipelineDependencies(
            get_database=lambda base_dir: database,
            build_paths=lambda base_dir, remember: SimpleNamespace(root=base_dir),
            add_source=record("add"),
            delete_source=record("delete"),
            discover=record(
                "discover",
                SimpleNamespace(selected_video_ids_by_source={1: (11,)}),
            ),
            fetch_captions=record("captions"),
            transcribe=record("transcribe"),
            extract=record("extract", ExtractionBatchResult(1, 0, 0)),
            ensure_media=record("media"),
            run_identity=record("identity"),
            prepare_reviews=record(
                "review",
                SimpleNamespace(pastors=(), prepared=0, failed=0),
            ),
        )

    def test_all_scope_runs_named_stages_in_order_and_scopes_review(self) -> None:
        calls = []
        video = SimpleNamespace(id=11, pastor_id=7)
        pastor = SimpleNamespace(id=7, slug="sample-church")
        database = SimpleNamespace(
            list_processing_enabled_sources=lambda: [SimpleNamespace(id=1)],
            list_sources=lambda: [SimpleNamespace(id=1), SimpleNamespace(id=2)],
            get_video_by_id=lambda video_id: video,
            get_pastor_by_id=lambda pastor_id: pastor,
        )
        events = []

        result = run_pipeline(
            PipelineRequest(
                all_sources=True,
                run_identity=True,
                recording_verifier_backend="typesafe",
                recording_verifier_model="jev-1.13.0",
            ),
            event_callback=events.append,
            dependencies=self._dependencies(database, calls),
        )

        self.assertEqual(PipelineScope.ALL, result.scope)
        self.assertEqual(frozenset({11}), result.video_ids)
        self.assertEqual(1, result.review_batch_count)
        self.assertEqual(
            ["discover", "captions", "transcribe", "extract", "media", "identity", "review"],
            [name for name, _args, _kwargs in calls],
        )
        review_call = calls[-1]
        self.assertEqual({11}, review_call[2]["video_ids"])
        extract_call = next(call for call in calls if call[0] == "extract")
        transcribe_call = next(call for call in calls if call[0] == "transcribe")
        self.assertTrue(transcribe_call[2]["missing_only"])
        self.assertEqual("typesafe", extract_call[2]["recording_verifier_backend"])
        self.assertEqual("jev-1.13.0", extract_call[2]["recording_verifier_model"])
        self.assertIn("skipping 1 disabled source", events[0])

    def test_failed_scope_preserves_missing_only_policy_without_discovery(self) -> None:
        calls = []
        failed = SimpleNamespace(id=21, pastor_id=None, status=VideoStatus.FAILED)
        database = SimpleNamespace(list_videos=lambda: [failed])

        result = run_pipeline(
            PipelineRequest(failed_only=True, skip_review=True, jobs=4),
            dependencies=self._dependencies(database, calls),
        )

        self.assertEqual(frozenset({21}), result.video_ids)
        self.assertNotIn("discover", [name for name, _args, _kwargs in calls])
        transcribe = next(call for call in calls if call[0] == "transcribe")
        extract = next(call for call in calls if call[0] == "extract")
        self.assertTrue(transcribe[2]["missing_only"])
        self.assertTrue(extract[2]["missing_only"])
        self.assertEqual(4, extract[2]["workers"])

    def test_no_transcribe_missing_explicitly_allows_retranscription(self) -> None:
        calls = []
        video = SimpleNamespace(id=11, pastor_id=None)
        database = SimpleNamespace(
            list_processing_enabled_sources=lambda: [SimpleNamespace(id=1)],
            list_sources=lambda: [SimpleNamespace(id=1)],
            get_video_by_id=lambda _video_id: video,
        )

        run_pipeline(
            PipelineRequest(
                all_sources=True,
                transcribe_missing=False,
                skip_review=True,
            ),
            dependencies=self._dependencies(database, calls),
        )

        transcribe = next(call for call in calls if call[0] == "transcribe")
        self.assertFalse(transcribe[2]["missing_only"])
        self.assertFalse(transcribe[2]["captions_missing_only"])

    def test_primary_run_retries_captions_while_confirmed_misses_transcribe(
        self,
    ) -> None:
        calls = []
        fetch_scopes: list[set[int]] = []
        transcribed_video_ids: list[set[int]] = []
        sleeps: list[float] = []
        transcription_started = threading.Event()
        database = SimpleNamespace(
            list_processing_enabled_sources=lambda: [SimpleNamespace(id=1)],
            list_sources=lambda: [SimpleNamespace(id=1)],
            get_video_by_id=lambda video_id: SimpleNamespace(
                id=video_id,
                pastor_id=None,
            ),
            get_latest_transcript_artifact_for_video=lambda _video_id: None,
        )

        def fetch_captions(**kwargs):
            scope = set(kwargs["video_ids"])
            fetch_scopes.append(scope)
            if len(fetch_scopes) == 1:
                kwargs["outcome_callback"](11, "unavailable")
                raise CaptionAcquisitionBlockedError("repeatedly rate limited")
            kwargs["outcome_callback"](12, "processed")

        def transcribe(**kwargs):
            transcribed_video_ids.append(kwargs["video_ids"])
            transcription_started.set()

        def sleeper(seconds):
            self.assertTrue(transcription_started.wait(timeout=1))
            sleeps.append(seconds)

        dependencies = replace(
            self._dependencies(database, calls),
            discover=lambda *args, **kwargs: SimpleNamespace(
                selected_video_ids_by_source={1: (11, 12)}
            ),
            fetch_captions=fetch_captions,
            transcribe=transcribe,
            caption_retry_sleeper=sleeper,
        )

        run_pipeline(
            PipelineRequest(all_sources=True, skip_review=True, jobs=2),
            dependencies=dependencies,
        )

        self.assertEqual([{11, 12}, {12}], fetch_scopes)
        self.assertEqual([{11}], transcribed_video_ids)
        self.assertEqual([300.0], sleeps)

    def test_url_scope_replaces_before_add_and_passes_source_id(self) -> None:
        calls = []
        source = SimpleNamespace(id=3)
        lookups = iter([SimpleNamespace(id=2), source])
        database = SimpleNamespace(get_source_by_url=lambda url: next(lookups))
        dependencies = self._dependencies(database, calls)
        dependencies = PipelineDependencies(
            **{
                field: getattr(dependencies, field)
                for field in dependencies.__dataclass_fields__
                if field != "discover"
            },
            discover=lambda *args, **kwargs: (
                calls.append(("discover", args, kwargs))
                or SimpleNamespace(selected_video_ids_by_source={3: (31,)})
            ),
        )

        result = run_pipeline(
            PipelineRequest(
                url="https://www.youtube.com/@samplechurch",
                pastor="sample-church",
                replace_existing=True,
                skip_review=True,
                base_dir=Path("data"),
            ),
            dependencies=dependencies,
        )

        self.assertEqual(PipelineScope.URL, result.scope)
        self.assertEqual(["delete", "add"], [calls[0][0], calls[1][0]])
        for name in ("discover", "captions", "transcribe", "extract"):
            call = next(item for item in calls if item[0] == name)
            self.assertEqual(3, call[2]["source_id"])

    def test_validation_rejects_ambiguous_scope_before_database_access(self) -> None:
        with self.assertRaisesRegex(ValueError, "either --all or --source-id"):
            validate_pipeline_request(
                PipelineRequest(all_sources=True, source_ids=(1,))
            )


if __name__ == "__main__":
    unittest.main()
