from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from pastor_transcript_extractor.workflows.identity import run as identity_run
from pastor_transcript_extractor.workflows.identity.run import (
    IdentityWorkflowRequest,
    synchronize_reviewed_evidence_stage,
    validate_identity_workflow_request,
)


class IdentityRunWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.request = IdentityWorkflowRequest(
            youtube_video_id=None,
            all_extractions=True,
            plan_only=False,
            skip_discovery=False,
            apply_automatic=False,
            apply_confirmations=False,
            apply_promotions=False,
            apply_machine_canary=False,
            machine_assignment_policy_path=None,
            review_prewarm_limit=24,
            base_dir=None,
            jobs=2,
        )

    def test_automatic_apply_enables_each_guarded_mutation(self) -> None:
        policy = validate_identity_workflow_request(
            replace(self.request, apply_automatic=True)
        )

        self.assertTrue(policy.apply_confirmations)
        self.assertTrue(policy.apply_promotions)
        self.assertTrue(policy.apply_machine_assignments)

    def test_plan_only_rejects_every_mutation_flag(self) -> None:
        for field in (
            "apply_automatic",
            "apply_confirmations",
            "apply_promotions",
            "apply_machine_canary",
        ):
            with self.subTest(field=field), self.assertRaisesRegex(
                ValueError, "registry mutation"
            ):
                validate_identity_workflow_request(
                    replace(self.request, plan_only=True, **{field: True})
                )

    def test_single_video_rejects_corpus_only_mutations(self) -> None:
        single_video = replace(
            self.request,
            youtube_video_id="video-1",
            all_extractions=False,
        )
        with self.assertRaisesRegex(ValueError, "promotion requires --all"):
            validate_identity_workflow_request(
                replace(single_video, apply_promotions=True)
            )
        with self.assertRaisesRegex(ValueError, "canary activation requires --all"):
            validate_identity_workflow_request(
                replace(single_video, apply_machine_canary=True)
            )

    def test_scope_and_resource_limits_are_validated(self) -> None:
        invalid = (
            (replace(self.request, youtube_video_id="video-1"), "exactly one"),
            (replace(self.request, review_prewarm_limit=-1), "cannot be negative"),
            (replace(self.request, jobs=0), "at least one"),
        )
        for request, message in invalid:
            with self.subTest(message=message), self.assertRaisesRegex(
                ValueError, message
            ):
                validate_identity_workflow_request(request)

    def test_reviewed_evidence_plan_does_not_open_writable_database(self) -> None:
        evidence = object()
        with patch.object(
            identity_run, "load_reviewed_speaker_evidence", return_value=evidence
        ), patch.object(identity_run, "Database") as database_factory, patch.object(
            identity_run, "sync_reviewed_speaker_evidence"
        ) as sync:
            result = synchronize_reviewed_evidence_stage(
                Path("app.db"), plan_only=True
            )

        self.assertIs(evidence, result.evidence)
        self.assertIsNone(result.sync)
        database_factory.assert_not_called()
        sync.assert_not_called()

    def test_reviewed_evidence_execute_initializes_before_sync(self) -> None:
        events: list[str] = []
        evidence = object()
        database = SimpleNamespace(initialize=lambda: events.append("initialize"))
        sync_result = object()
        sync = Mock(
            side_effect=lambda _database, _evidence: (
                events.append("sync"),
                sync_result,
            )[1]
        )
        with patch.object(
            identity_run, "load_reviewed_speaker_evidence", return_value=evidence
        ), patch.object(identity_run, "Database", return_value=database), patch.object(
            identity_run, "sync_reviewed_speaker_evidence", sync
        ):
            result = synchronize_reviewed_evidence_stage(
                Path("app.db"), plan_only=False
            )

        self.assertEqual(["initialize", "sync"], events)
        self.assertIs(sync_result, result.sync)

    def test_reviewed_evidence_errors_keep_stage_context(self) -> None:
        with patch.object(
            identity_run,
            "load_reviewed_speaker_evidence",
            side_effect=OSError("unreadable"),
        ):
            with self.assertRaisesRegex(
                ValueError, "reviewed-evidence sync failed: unreadable"
            ):
                synchronize_reviewed_evidence_stage(
                    Path("app.db"), plan_only=False
                )


if __name__ == "__main__":
    unittest.main()
