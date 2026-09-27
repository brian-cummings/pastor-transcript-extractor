from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from pastor_transcript_extractor.commands.identity.profiles import (
    export_profile_command,
    sync_reviewed_speaker_evidence_command,
)


class IdentityProfileCommandTests(unittest.TestCase):
    def test_reviewed_evidence_dry_run_does_not_open_database(self) -> None:
        evidence = SimpleNamespace(
            review_event_count=2,
            qualifications={},
            same_components=lambda: (),
            pair_relations={},
            qualification_conflicts=(),
            pair_conflicts=(),
        )
        with patch(
            "pastor_transcript_extractor.commands.identity.profiles."
            "load_reviewed_speaker_evidence",
            return_value=evidence,
        ), patch(
            "pastor_transcript_extractor.commands.identity.profiles.get_database"
        ) as get_database:
            sync_reviewed_speaker_evidence_command(
                evaluation_root=Path("evaluation/speaker-pairs"),
                dry_run=True,
                base_dir=None,
            )

        get_database.assert_not_called()

    def test_export_profile_renders_canonical_redirect(self) -> None:
        result = SimpleNamespace(
            requested_profile_id=7,
            profile_id=3,
            export_path=Path("profile.md"),
            manifest_path=Path("profile.json"),
            video_count=4,
            skipped_count=1,
        )
        with patch(
            "pastor_transcript_extractor.commands.identity.profiles.get_database",
            return_value=SimpleNamespace(),
        ), patch(
            "pastor_transcript_extractor.commands.identity.profiles.build_paths",
            return_value=SimpleNamespace(),
        ), patch(
            "pastor_transcript_extractor.commands.identity.profiles."
            "export_profile_transcript_collection",
            return_value=result,
        ), patch(
            "pastor_transcript_extractor.commands.identity.profiles.console.print"
        ) as output:
            export_profile_command(profile_id=7, base_dir=None)

        rendered = "\n".join(str(call.args[0]) for call in output.call_args_list)
        self.assertIn("canonical profile #3", rendered)
        self.assertIn("Included 4 sermon(s); skipped 1", rendered)


if __name__ == "__main__":
    unittest.main()
