from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import unittest

from pastor_transcript_extractor.workflows.run import (
    RunMode,
    RunWorkflowDependencies,
    RunWorkflowRequest,
    run_workflow,
)


class RunWorkflowTests(unittest.TestCase):
    def _dependencies(self, calls):
        def record(name, result=None):
            def operation(*args, **kwargs):
                calls.append((name, args, kwargs))
                return result

            return operation

        return RunWorkflowDependencies(
            get_database=record("database", SimpleNamespace()),
            build_paths=record("paths", SimpleNamespace(logs=Path("logs"))),
            build_tools=record("tools", SimpleNamespace()),
            verify_manifest=record("verify", {11}),
            audio_scope=SimpleNamespace(),
            audio_stage=SimpleNamespace(),
            resume_pipeline=SimpleNamespace(),
            online_pipeline=SimpleNamespace(),
            resolve_audio_scope=record(
                "scope",
                SimpleNamespace(
                    database=SimpleNamespace(),
                    video_ids=frozenset({11}),
                    skip_reason=None,
                ),
            ),
            stage_audio=record("stage", SimpleNamespace()),
            resume=record("resume", SimpleNamespace()),
            online=record("online", SimpleNamespace()),
        )

    def test_online_mode_deduplicates_source_ids_before_dispatch(self) -> None:
        calls = []
        result = run_workflow(
            RunWorkflowRequest(source_ids=(2, 4, 2)),
            dependencies=self._dependencies(calls),
        )

        self.assertEqual(RunMode.ONLINE, result.mode)
        self.assertEqual(["online"], [call[0] for call in calls])
        self.assertEqual((2, 4), calls[0][1][0].source_ids)

    def test_audio_mode_resolves_scope_before_staging(self) -> None:
        calls = []
        result = run_workflow(
            RunWorkflowRequest(all_sources=True, stage_audio_only=True),
            dependencies=self._dependencies(calls),
        )

        self.assertEqual(RunMode.STAGE_AUDIO, result.mode)
        self.assertEqual(
            ["scope", "paths", "tools", "stage"],
            [call[0] for call in calls],
        )
        self.assertEqual(frozenset({11}), calls[-1][1][3].video_ids)

    def test_resume_mode_verifies_manifest_before_offline_pipeline(self) -> None:
        calls = []
        events = []
        result = run_workflow(
            RunWorkflowRequest(resume_stage=Path("stage.json")),
            event_callback=events.append,
            dependencies=self._dependencies(calls),
        )

        self.assertEqual(RunMode.RESUME, result.mode)
        self.assertEqual(
            ["database", "paths", "verify", "resume"],
            [call[0] for call in calls],
        )
        self.assertEqual(frozenset({11}), calls[-1][1][2].video_ids)
        self.assertIn("verifying every checksum", events[0])

    def test_invalid_mode_stops_before_dependencies_are_called(self) -> None:
        calls = []
        with self.assertRaisesRegex(ValueError, "either --stage-audio-only"):
            run_workflow(
                RunWorkflowRequest(
                    stage_audio_only=True,
                    resume_stage=Path("stage.json"),
                ),
                dependencies=self._dependencies(calls),
            )

        self.assertEqual([], calls)


if __name__ == "__main__":
    unittest.main()
