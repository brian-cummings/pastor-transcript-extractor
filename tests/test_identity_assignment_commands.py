from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

import typer

from pastor_transcript_extractor.commands.identity import assignments
from pastor_transcript_extractor.commands.identity.common import (
    held_out_speaker_fixture_fingerprints,
)


class IdentityAssignmentCommandTests(unittest.TestCase):
    def test_held_out_fingerprints_ignore_development_fixtures(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture_dir = Path(tmp)
            (fixture_dir / "held-out.json").write_text(
                json.dumps(
                    {
                        "evaluation_partition": "held_out",
                        "observations": {
                            "a": {"input_fingerprint": "held-a"},
                            "b": {"input_fingerprint": "held-b"},
                        },
                    }
                ),
                encoding="utf-8",
            )
            (fixture_dir / "development.json").write_text(
                json.dumps(
                    {
                        "evaluation_partition": "development",
                        "observations": {
                            "a": {"input_fingerprint": "development-a"}
                        },
                    }
                ),
                encoding="utf-8",
            )

            fingerprints = held_out_speaker_fixture_fingerprints(fixture_dir)

        self.assertEqual(frozenset({"held-a", "held-b"}), fingerprints)

    def test_reconcile_dry_run_never_mutates_assignment_state(self) -> None:
        database = SimpleNamespace(list_speaker_machine_evidence=lambda: [])
        plan = SimpleNamespace(candidates=(), skipped_counts={})
        with patch.object(
            assignments,
            "build_paths",
            return_value=SimpleNamespace(database=Path("app.db")),
        ), patch.object(assignments, "Database", return_value=database), patch.object(
            assignments, "latest_association_reports", return_value=[]
        ), patch.object(
            assignments, "load_reviewed_speaker_evidence", return_value=object()
        ), patch.object(
            assignments, "assess_profile_association_readiness", return_value=[]
        ), patch.object(
            assignments, "load_machine_assignment_policy", return_value=object()
        ), patch.object(
            assignments, "plan_machine_assignments", return_value=plan
        ), patch.object(
            assignments, "reconcile_machine_assignments"
        ) as reconcile, patch.object(
            assignments, "apply_machine_assignment_plan"
        ) as apply_plan:
            assignments.reconcile_current_proposals_command(
                dry_run=True,
                activate_canary=False,
                machine_assignment_policy=Path("policy.json"),
                association_root=Path("associations"),
                base_dir=None,
            )

        reconcile.assert_not_called()
        apply_plan.assert_not_called()

    def test_rollback_plan_does_not_open_writable_database(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            database_path = Path(tmp) / "app.db"
            database_path.touch()
            readonly = SimpleNamespace()
            with patch.object(
                assignments,
                "build_paths",
                return_value=SimpleNamespace(database=database_path),
            ), patch.object(
                assignments, "Database", return_value=readonly
            ) as database_factory, patch.object(
                assignments,
                "active_machine_assignment_evidence",
                return_value=[{"policy_fingerprint": "policy-a"}],
            ), patch.object(
                assignments, "rollback_machine_assignments"
            ) as rollback:
                assignments.rollback_machine_assignments_command(
                    policy_fingerprint="policy-a",
                    apply=False,
                    base_dir=Path(tmp),
                )

        database_factory.assert_called_once_with(database_path, readonly=True)
        rollback.assert_not_called()

    def test_status_rejects_unknown_state_before_opening_database(self) -> None:
        with patch.object(assignments, "build_paths") as build_paths:
            with self.assertRaises(typer.BadParameter):
                assignments.machine_assignment_status_command(
                    details=False,
                    profile_id=None,
                    state="unknown",
                    base_dir=None,
                )

        build_paths.assert_not_called()


if __name__ == "__main__":
    unittest.main()
