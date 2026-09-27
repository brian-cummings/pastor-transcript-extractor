from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch

import typer

from pastor_transcript_extractor.commands.identity import coordination
from pastor_transcript_extractor.identity_automation import (
    IdentityAssociationWorkItem,
    IdentityAssociationWorkPlan,
)


def _work_item(
    *,
    state: str = "dispatch_ready",
    reason_code: str = "ready",
    next_operation: str = "association_dispatch",
) -> IdentityAssociationWorkItem:
    return IdentityAssociationWorkItem(
        video_id=7,
        youtube_video_id="video-7",
        observation_id=11,
        observation_fingerprint="fingerprint-11",
        state=state,
        stage="association",
        reason_code=reason_code,
        next_operation=next_operation,
        retryable=True,
    )


class IdentityCoordinationCommandTests(unittest.TestCase):
    def test_coordinate_requires_exactly_one_scope(self) -> None:
        with patch.object(coordination, "build_paths") as build_paths:
            with self.assertRaises(typer.BadParameter):
                coordination.coordinate_identity_command(
                    youtube_video_id=None,
                    all_extractions=False,
                    execute_shadow=False,
                    discovery_report=None,
                    discovery_root=Path("discovery"),
                    model_path=Path("model.onnx"),
                    model_sha256="checksum",
                    policy_path=Path("policy.json"),
                    evaluation_root=Path("evaluation"),
                    cache_dir=Path("cache"),
                    association_root=Path("associations"),
                    output_root=None,
                    base_dir=None,
                )

        build_paths.assert_not_called()

    def test_coordinate_rejects_corpus_shadow_execution(self) -> None:
        with patch.object(coordination, "build_paths") as build_paths:
            with self.assertRaises(typer.BadParameter):
                coordination.coordinate_identity_command(
                    youtube_video_id=None,
                    all_extractions=True,
                    execute_shadow=True,
                    discovery_report=None,
                    discovery_root=Path("discovery"),
                    model_path=Path("model.onnx"),
                    model_sha256="checksum",
                    policy_path=Path("policy.json"),
                    evaluation_root=Path("evaluation"),
                    cache_dir=Path("cache"),
                    association_root=Path("associations"),
                    output_root=None,
                    base_dir=None,
                )

        build_paths.assert_not_called()

    def test_dispatch_dry_run_does_not_invoke_associator(self) -> None:
        plan = IdentityAssociationWorkPlan(items=(_work_item(),), attempt_volume=0)
        associator = Mock()
        coordination.configure_shadow_associator(associator)

        with patch.object(
            coordination, "build_paths", return_value=SimpleNamespace(database=Path("db"))
        ), patch.object(coordination, "Database"), patch.object(
            coordination, "build_identity_association_work_plan", return_value=plan
        ):
            coordination.dispatch_associations_command(
                limit=25,
                dry_run=True,
                jobs=2,
                retry_failed_only=False,
                association_root=Path("associations"),
                base_dir=None,
            )

        associator.assert_not_called()

    def test_dispatch_records_one_failure_without_aborting_batch(self) -> None:
        items = (
            _work_item(),
            IdentityAssociationWorkItem(
                video_id=8,
                youtube_video_id="video-8",
                observation_id=12,
                observation_fingerprint="fingerprint-12",
                state="dispatch_ready",
                stage="association",
                reason_code="ready",
                next_operation="association_dispatch",
                retryable=True,
            ),
        )
        plan = IdentityAssociationWorkPlan(items=items, attempt_volume=0)
        associator = Mock(side_effect=[RuntimeError("broken"), None])
        coordination.configure_shadow_associator(associator)

        with patch.object(
            coordination, "build_paths", return_value=SimpleNamespace(database=Path("db"))
        ), patch.object(coordination, "Database"), patch.object(
            coordination, "build_identity_association_work_plan", return_value=plan
        ), patch.object(coordination, "write_identity_work_event") as write_event:
            coordination.dispatch_associations_command(
                limit=25,
                dry_run=False,
                jobs=2,
                retry_failed_only=False,
                association_root=Path("associations"),
                base_dir=None,
            )

        self.assertEqual(associator.call_count, 2)
        write_event.assert_called_once()
        self.assertEqual(write_event.call_args.kwargs["outcome"], "technical_failure")

    def test_superseded_review_no_candidate_does_not_start_review(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            database_path = Path(tmp) / "app.db"
            database_path.touch()
            with patch.object(
                coordination,
                "build_paths",
                return_value=SimpleNamespace(database=database_path),
            ), patch.object(coordination, "Database"), patch.object(
                coordination, "select_superseded_profile_member_review", return_value=None
            ), patch.object(coordination, "review_speaker_pair") as review:
                coordination.review_next_superseded_profile_member_command(
                    reviewer=None,
                    prepare_only=True,
                    open_packet=False,
                    evaluation_root=Path("evaluation/speaker-pairs"),
                    cache_dir=Path("evaluation/speaker-pairs/cache"),
                    base_dir=Path(tmp),
                )

        review.assert_not_called()


if __name__ == "__main__":
    unittest.main()
