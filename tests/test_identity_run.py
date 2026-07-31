from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from pastor_transcript_extractor.cli import run_identity_workflow_service


class IdentityRunTests(unittest.TestCase):
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
                    "pastor_transcript_extractor.cli.identity_backfill"
                ) as backfill,
                patch(
                    "pastor_transcript_extractor.cli.shadow_associate_speakers_command"
                ) as associate,
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
                run_identity_workflow_service(
                    youtube_video_id=None,
                    all_extractions=True,
                    plan_only=False,
                    skip_discovery=False,
                    apply_confirmations=False,
                    apply_promotions=False,
                    base_dir=Path(tempdir),
                )

        backfill.assert_called_once_with(
            video_id=None,
            base_dir=Path(tempdir),
        )
        self.assertFalse(associate.call_args.kwargs["plan_only"])
        self.assertTrue(associate.call_args.kwargs["all_eligible"])
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
                apply_confirmations=True,
                apply_promotions=False,
                base_dir=None,
            )

    def test_requires_exactly_one_scope(self) -> None:
        with self.assertRaisesRegex(ValueError, "exactly one"):
            run_identity_workflow_service(
                youtube_video_id=None,
                all_extractions=False,
                plan_only=True,
                skip_discovery=False,
                apply_confirmations=False,
                apply_promotions=False,
                base_dir=None,
            )


if __name__ == "__main__":
    unittest.main()
