from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from pastor_transcript_extractor.config import AppPaths
from pastor_transcript_extractor.workflows.identity import finalization
from pastor_transcript_extractor.workflows.identity.finalization import (
    ActionableReviewAudioPreparation,
    CoordinationStageRequest,
    run_coordination_stage,
    run_archive_dispatch_stage,
    run_review_prewarm_stage,
)


class IdentityFinalizationWorkflowTests(unittest.TestCase):
    def test_coordination_is_always_shadow_only_with_pinned_inputs(self) -> None:
        coordinator = Mock(return_value="report")
        request = CoordinationStageRequest(
            youtube_video_id="video-1",
            all_extractions=False,
            discovery_report=Path("discovery.json"),
            discovery_root=Path("discovery"),
            model_sha256="model-sha",
            base_dir=Path("app-data"),
        )

        result = run_coordination_stage(request, coordinator=coordinator)

        self.assertEqual("report", result)
        options = coordinator.call_args.kwargs
        self.assertFalse(options["execute_shadow"])
        self.assertEqual("video-1", options["youtube_video_id"])
        self.assertEqual(Path("discovery.json"), options["discovery_report"])
        self.assertEqual("model-sha", options["model_sha256"])
        self.assertIsNone(options["output_root"])

    def test_prewarm_plan_only_does_not_open_database(self) -> None:
        prewarmer = Mock()
        with patch.object(finalization, "Database") as database_factory:
            result = run_review_prewarm_stage(
                Path("app.db"),
                SimpleNamespace(),
                plan_only=True,
                all_extractions=True,
                limit=24,
                discovery_report=None,
                association_reports=(),
                automatic_profile_ready_ids=frozenset(),
                prewarmer=prewarmer,
            )

        self.assertEqual("plan_only", result.status)
        database_factory.assert_not_called()
        prewarmer.assert_not_called()

    def test_prewarm_executes_with_exact_scope(self) -> None:
        database = object()
        preparation = ActionableReviewAudioPreparation(4, 2, 1, 1, 0)
        prewarmer = Mock(return_value=preparation)
        paths = SimpleNamespace()
        with patch.object(finalization, "Database", return_value=database):
            result = run_review_prewarm_stage(
                Path("app.db"),
                paths,
                plan_only=False,
                all_extractions=True,
                limit=4,
                discovery_report=Path("discovery.json"),
                association_reports=(Path("association.json"),),
                automatic_profile_ready_ids=frozenset({3}),
                prewarmer=prewarmer,
            )

        self.assertEqual("executed", result.status)
        self.assertIs(preparation, result.preparation)
        options = prewarmer.call_args.kwargs
        self.assertEqual(4, options["limit"])
        self.assertEqual(frozenset({3}), options["automatic_profile_ready_ids"])

    def test_prewarm_expected_failure_is_nonfatal(self) -> None:
        with patch.object(finalization, "Database", return_value=object()):
            result = run_review_prewarm_stage(
                Path("app.db"),
                SimpleNamespace(),
                plan_only=False,
                all_extractions=True,
                limit=4,
                discovery_report=None,
                association_reports=(),
                automatic_profile_ready_ids=frozenset(),
                prewarmer=Mock(side_effect=OSError("missing media")),
            )

        self.assertEqual("failed", result.status)
        self.assertEqual("OSError: missing media", result.error)

    def test_archive_plan_only_does_not_open_database(self) -> None:
        archiver = Mock()
        with patch.object(finalization, "Database") as database_factory:
            result = run_archive_dispatch_stage(
                SimpleNamespace(),
                plan_only=True,
                database_video_id=7,
                all_extractions=False,
                archiver=archiver,
            )

        self.assertEqual("plan_only", result.status)
        database_factory.assert_not_called()
        archiver.assert_not_called()

    def test_archive_dispatch_preserves_single_video_scope(self) -> None:
        root = Path("app-data")
        paths = AppPaths(
            root=root,
            database=root / "app.db",
            artifacts=root / "artifacts",
            logs=root / "logs",
            exports=root / "exports",
            pastors=root / "pastors",
        )
        database = object()
        archiver = Mock()
        with patch.object(finalization, "Database", return_value=database):
            result = run_archive_dispatch_stage(
                paths,
                plan_only=False,
                database_video_id=7,
                all_extractions=False,
                archiver=archiver,
            )

        self.assertEqual("executed", result.status)
        archiver.assert_called_once_with(
            database,
            paths,
            video_ids={7},
            all_eligible=False,
        )


if __name__ == "__main__":
    unittest.main()
