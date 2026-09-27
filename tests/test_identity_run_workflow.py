from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch

from pastor_transcript_extractor.workflows.identity import run as identity_run
from pastor_transcript_extractor.workflows.identity.run import (
    AssociationCacheDecision,
    AssociationExecutionRequest,
    IdentityWorkflowRequest,
    decide_association_cache,
    execute_association_stage,
    index_current_association_results,
    reconcile_current_assignment_results_stage,
    reconcile_machine_assignments_stage,
    repair_association_stage,
    select_pending_exemplar_repairs,
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

    def _association_request(self) -> AssociationExecutionRequest:
        return AssociationExecutionRequest(
            youtube_video_id=None,
            all_extractions=True,
            plan_only=False,
            jobs=3,
            model_sha256="model-sha",
            policy_path=Path("policy.json"),
            evaluation_root=Path("evaluation"),
            cache_dir=Path("cache"),
            output_root=Path("output"),
            base_dir=Path("app-data"),
        )

    def test_association_execution_reuses_cache_without_invocation(self) -> None:
        associator = Mock()
        reports = (Path("cached.json"),)
        result = execute_association_stage(
            self._association_request(),
            AssociationCacheDecision(
                cached_reports=reports,
                refresh_mode="cached",
                checkpoint_needs_refresh=False,
            ),
            associator=associator,
        )

        self.assertEqual(reports, result)
        associator.assert_not_called()

    def test_association_execution_forwards_incremental_decision(self) -> None:
        associator = Mock(return_value=[Path("new.json")])
        result = execute_association_stage(
            self._association_request(),
            AssociationCacheDecision(
                cached_reports=None,
                refresh_mode="incremental",
                checkpoint_needs_refresh=True,
            ),
            associator=associator,
        )

        self.assertEqual((Path("new.json"),), result)
        self.assertTrue(associator.call_args.kwargs["unattempted_only"])
        self.assertEqual(3, associator.call_args.kwargs["jobs"])
        self.assertFalse(associator.call_args.kwargs["plan_only"])
        self.assertEqual(
            Path("policy.json"), associator.call_args.kwargs["policy_path"]
        )

    def test_exemplar_repair_selection_is_scoped_to_video(self) -> None:
        states = (
            SimpleNamespace(video_id=7),
            SimpleNamespace(video_id=8),
        )
        cache = SimpleNamespace(pending_automatic_repairs=lambda: states)

        selected = select_pending_exemplar_repairs(
            cache,
            database_video_id=8,
            plan_only=False,
        )

        self.assertEqual((states[1],), selected)

    def test_plan_only_does_not_read_pending_exemplar_repairs(self) -> None:
        cache = SimpleNamespace(
            pending_automatic_repairs=Mock(
                side_effect=AssertionError("must not read repair state")
            )
        )

        selected = select_pending_exemplar_repairs(
            cache,
            database_video_id=None,
            plan_only=True,
        )

        self.assertEqual((), selected)
        cache.pending_automatic_repairs.assert_not_called()

    def test_empty_repair_stage_preserves_reports_and_checkpoint(self) -> None:
        repairer = Mock()
        reports = (Path("current.json"),)

        result = repair_association_stage(
            pending_repairs=(),
            current_reports=reports,
            youtube_video_id=None,
            all_extractions=True,
            paths=SimpleNamespace(),
            base_dir=None,
            state_cache=SimpleNamespace(),
            jobs=2,
            repairer=repairer,
        )

        self.assertEqual(reports, result.reports)
        self.assertFalse(result.checkpoint_needs_refresh)
        self.assertFalse(result.repair_attempted)
        repairer.assert_not_called()

    def test_repair_stage_replaces_reports_and_invalidates_checkpoint(self) -> None:
        pending = (SimpleNamespace(video_id=7),)
        repairer = Mock(return_value=[Path("repaired.json")])

        result = repair_association_stage(
            pending_repairs=pending,
            current_reports=(Path("old.json"),),
            youtube_video_id="video-7",
            all_extractions=False,
            paths=SimpleNamespace(),
            base_dir=Path("app-data"),
            state_cache=SimpleNamespace(),
            jobs=3,
            repairer=repairer,
        )

        self.assertEqual((Path("repaired.json"),), result.reports)
        self.assertTrue(result.checkpoint_needs_refresh)
        self.assertTrue(result.repair_attempted)
        self.assertEqual(
            pending, repairer.call_args.kwargs["pending_exemplar_repairs"]
        )

    def test_automatic_apply_enables_each_guarded_mutation(self) -> None:
        policy = validate_identity_workflow_request(
            replace(self.request, apply_automatic=True)
        )

        self.assertTrue(policy.apply_confirmations)
        self.assertTrue(policy.apply_promotions)
        self.assertTrue(policy.apply_machine_assignments)

    def test_association_cache_reuses_reports_without_refresh(self) -> None:
        reports = (Path("report.json"),)
        decision = decide_association_cache(
            cached_reports=reports,
            previous_input_state=None,
            current_input_state=None,
            all_extractions=True,
        )

        self.assertEqual(reports, decision.cached_reports)
        self.assertEqual("cached", decision.refresh_mode)
        self.assertFalse(decision.checkpoint_needs_refresh)
        self.assertFalse(decision.incremental)

    def test_missing_prior_state_rewrites_reused_checkpoint(self) -> None:
        decision = decide_association_cache(
            cached_reports=(Path("report.json"),),
            previous_input_state=None,
            current_input_state={"observations": {}},
            all_extractions=True,
        )

        self.assertTrue(decision.checkpoint_needs_refresh)

    def test_corpus_cache_miss_delegates_refresh_mode(self) -> None:
        previous = {"previous": True}
        current = {"current": True}
        with patch.object(
            identity_run,
            "association_refresh_mode",
            return_value="incremental",
        ) as refresh_mode:
            decision = decide_association_cache(
                cached_reports=None,
                previous_input_state=previous,
                current_input_state=current,
                all_extractions=True,
            )

        self.assertTrue(decision.incremental)
        self.assertTrue(decision.checkpoint_needs_refresh)
        refresh_mode.assert_called_once_with(previous, current)

    def test_single_video_cache_miss_forces_full_refresh(self) -> None:
        with patch.object(identity_run, "association_refresh_mode") as refresh_mode:
            decision = decide_association_cache(
                cached_reports=None,
                previous_input_state=None,
                current_input_state=None,
                all_extractions=False,
            )

        self.assertEqual("full", decision.refresh_mode)
        refresh_mode.assert_not_called()

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

    def test_assignment_reconciliation_plan_does_not_open_database(self) -> None:
        with patch.object(identity_run, "Database") as database_factory, patch.object(
            identity_run, "reconcile_machine_assignments"
        ) as reconcile:
            result = reconcile_machine_assignments_stage(
                Path("app.db"),
                verification_cache=object(),
                plan_only=True,
            )

        self.assertIsNone(result)
        database_factory.assert_not_called()
        reconcile.assert_not_called()

    def test_assignment_reconciliation_uses_writable_database(self) -> None:
        database = object()
        expected = object()
        cache = object()
        with patch.object(
            identity_run, "Database", return_value=database
        ) as database_factory, patch.object(
            identity_run, "reconcile_machine_assignments", return_value=expected
        ) as reconcile:
            result = reconcile_machine_assignments_stage(
                Path("app.db"),
                verification_cache=cache,
                plan_only=False,
            )

        self.assertIs(expected, result)
        database_factory.assert_called_once_with(Path("app.db"))
        reconcile.assert_called_once_with(database, verification_cache=cache)

    def test_association_result_index_skips_malformed_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            valid = root / "valid.json"
            valid.write_text(
                '{"candidate":{"observation_id":7},"result_sha256":"sha-7"}',
                encoding="utf-8",
            )
            malformed = root / "malformed.json"
            malformed.write_text("{", encoding="utf-8")
            missing = root / "missing.json"

            result = index_current_association_results(
                (malformed, missing, valid)
            )

        self.assertEqual({7: "sha-7"}, result)

    def test_association_result_index_uses_last_current_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = root / "first.json"
            second = root / "second.json"
            first.write_text(
                '{"candidate":{"observation_id":7},"result_sha256":"old"}',
                encoding="utf-8",
            )
            second.write_text(
                '{"candidate":{"observation_id":7},"result_sha256":"current"}',
                encoding="utf-8",
            )

            result = index_current_association_results((first, second))

        self.assertEqual({7: "current"}, result)

    def test_current_result_reconciliation_forwards_exact_index(self) -> None:
        database = object()
        expected = object()
        cache = object()
        result_index = {7: "sha-7"}
        with patch.object(
            identity_run, "Database", return_value=database
        ), patch.object(
            identity_run, "reconcile_machine_assignments", return_value=expected
        ) as reconcile:
            result = reconcile_current_assignment_results_stage(
                Path("app.db"),
                verification_cache=cache,
                result_sha256_by_observation=result_index,
                plan_only=False,
            )

        self.assertIs(expected, result)
        reconcile.assert_called_once_with(
            database,
            verification_cache=cache,
            current_association_result_sha256_by_observation=result_index,
        )

    def test_current_result_reconciliation_plan_is_non_mutating(self) -> None:
        with patch.object(identity_run, "Database") as database_factory, patch.object(
            identity_run, "reconcile_machine_assignments"
        ) as reconcile:
            result = reconcile_current_assignment_results_stage(
                Path("app.db"),
                verification_cache=object(),
                result_sha256_by_observation={7: "sha-7"},
                plan_only=True,
            )

        self.assertIsNone(result)
        database_factory.assert_not_called()
        reconcile.assert_not_called()


if __name__ == "__main__":
    unittest.main()
