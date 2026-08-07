from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from pastor_transcript_extractor.cli import (
    _held_out_speaker_fixture_fingerprints,
    run_identity_workflow_service,
)


class IdentityRunTests(unittest.TestCase):
    def test_held_out_fixture_observations_are_reserved_from_machine_use(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            fixture_dir = Path(tempdir)
            (fixture_dir / "held-out.json").write_text(
                """{
                  "evaluation_partition": "held_out",
                  "observations": {
                    "a": {"input_fingerprint": "fingerprint-a"},
                    "b": {"input_fingerprint": "fingerprint-b"}
                  }
                }""",
                encoding="utf-8",
            )
            (fixture_dir / "development.json").write_text(
                """{
                  "evaluation_partition": "development",
                  "observations": {
                    "a": {"input_fingerprint": "fingerprint-c"},
                    "b": {"input_fingerprint": "fingerprint-d"}
                  }
                }""",
                encoding="utf-8",
            )

            reserved = _held_out_speaker_fixture_fingerprints(fixture_dir)

        self.assertEqual(
            frozenset(("fingerprint-a", "fingerprint-b")),
            reserved,
        )

    def test_all_run_chains_backfill_association_confirmation_and_discovery(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            database_path = Path(tempdir) / "app.db"
            database_path.touch()
            paths = SimpleNamespace(database=database_path)
            with (
                patch(
                    "pastor_transcript_extractor.cli.build_paths",
                    return_value=paths,
                ),
                patch("pastor_transcript_extractor.cli.Database"),
                patch(
                    "pastor_transcript_extractor.cli.load_reviewed_speaker_evidence"
                ) as load_evidence,
                patch(
                    "pastor_transcript_extractor.cli.sync_reviewed_speaker_evidence"
                ) as sync_evidence,
                patch(
                    "pastor_transcript_extractor.cli._print_reviewed_evidence_summary"
                ),
                patch(
                    "pastor_transcript_extractor.cli.identity_backfill"
                ) as backfill,
                patch(
                    "pastor_transcript_extractor.cli.shadow_associate_speakers_command"
                ) as associate,
                patch(
                    "pastor_transcript_extractor.cli.plan_machine_assignments",
                    return_value=SimpleNamespace(
                        candidates=(),
                        skipped_counts={},
                        tripped_policy_fingerprints=frozenset(),
                    ),
                ) as plan_machine,
                patch(
                    "pastor_transcript_extractor.cli.apply_machine_assignment_plan",
                    return_value=SimpleNamespace(
                        evidence_recorded=0,
                        evidence_reused=0,
                        assignments_activated=0,
                        activation_blocked=0,
                    ),
                ),
                patch(
                    "pastor_transcript_extractor.cli.confirm_discovered_profiles_command"
                ) as confirm,
                patch(
                    "pastor_transcript_extractor.cli.shadow_discover_profiles_command"
                ) as discover,
                patch(
                    "pastor_transcript_extractor.cli.promote_discovered_profiles_command"
                ) as promote,
                patch(
                    "pastor_transcript_extractor.cli.coordinate_identity_command"
                ) as coordinate,
                patch.object(Path, "glob", return_value=[]),
            ):
                current_report = Path(tempdir) / "current-association.json"
                associate.return_value = (current_report,)
                run_identity_workflow_service(
                    youtube_video_id=None,
                    all_extractions=True,
                    plan_only=False,
                    skip_discovery=False,
                    apply_automatic=False,
                    apply_confirmations=False,
                    apply_promotions=False,
                    base_dir=Path(tempdir),
                )

        backfill.assert_called_once_with(
            video_id=None,
            base_dir=Path(tempdir),
        )
        load_evidence.assert_called_once()
        sync_evidence.assert_called_once()
        self.assertFalse(associate.call_args.kwargs["plan_only"])
        self.assertTrue(associate.call_args.kwargs["all_eligible"])
        self.assertEqual(
            (current_report,),
            plan_machine.call_args.args[1],
        )
        self.assertFalse(confirm.call_args.kwargs["apply"])
        self.assertFalse(discover.call_args.kwargs["plan_only"])
        promote.assert_not_called()
        self.assertTrue(coordinate.call_args.kwargs["all_extractions"])

    def test_plan_only_rejects_registry_mutation_flags(self) -> None:
        with self.assertRaisesRegex(ValueError, "plan-only"):
            run_identity_workflow_service(
                youtube_video_id=None,
                all_extractions=True,
                plan_only=True,
                skip_discovery=False,
                apply_automatic=False,
                apply_confirmations=True,
                apply_promotions=False,
                base_dir=None,
            )

    def test_apply_automatic_enables_confirmations_and_promotions(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            database_path = Path(tempdir) / "app.db"
            database_path.touch()
            discovery_path = Path(tempdir) / "discovery.json"
            discovery_path.touch()
            paths = SimpleNamespace(database=database_path)
            with (
                patch(
                    "pastor_transcript_extractor.cli.build_paths",
                    return_value=paths,
                ),
                patch("pastor_transcript_extractor.cli.Database"),
                patch(
                    "pastor_transcript_extractor.cli.load_reviewed_speaker_evidence"
                ),
                patch(
                    "pastor_transcript_extractor.cli.sync_reviewed_speaker_evidence"
                ),
                patch(
                    "pastor_transcript_extractor.cli._print_reviewed_evidence_summary"
                ),
                patch("pastor_transcript_extractor.cli.identity_backfill"),
                patch(
                    "pastor_transcript_extractor.cli.shadow_associate_speakers_command"
                ),
                patch(
                    "pastor_transcript_extractor.cli.confirm_discovered_profiles_command"
                ) as confirm,
                patch(
                    "pastor_transcript_extractor.cli.shadow_discover_profiles_command"
                ),
                patch(
                    "pastor_transcript_extractor.cli.promote_discovered_profiles_command"
                ) as promote,
                patch(
                    "pastor_transcript_extractor.cli.coordinate_identity_command"
                ),
                patch.object(Path, "glob", return_value=[discovery_path]),
            ):
                run_identity_workflow_service(
                    youtube_video_id=None,
                    all_extractions=True,
                    plan_only=False,
                    skip_discovery=False,
                    apply_automatic=True,
                    apply_confirmations=False,
                    apply_promotions=False,
                    base_dir=Path(tempdir),
                )

        self.assertTrue(confirm.call_args.kwargs["apply"])
        self.assertTrue(promote.call_args.kwargs["apply"])

    def test_requires_exactly_one_scope(self) -> None:
        with self.assertRaisesRegex(ValueError, "exactly one"):
            run_identity_workflow_service(
                youtube_video_id=None,
                all_extractions=False,
                plan_only=True,
                skip_discovery=False,
                apply_automatic=False,
                apply_confirmations=False,
                apply_promotions=False,
                base_dir=None,
            )


if __name__ == "__main__":
    unittest.main()
