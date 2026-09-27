from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from pastor_transcript_extractor.commands.identity.metadata import (
    analyze_profile_metadata_command,
    enrich_metadata_command,
)


class IdentityMetadataCommandTests(unittest.TestCase):
    def test_enrichment_plan_does_not_build_network_tools(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            database_path = Path(tmp) / "app.db"
            database_path.touch()
            database = SimpleNamespace(
                get_video_by_id=lambda video_id: SimpleNamespace(id=video_id)
            )
            with patch(
                "pastor_transcript_extractor.commands.identity.metadata.build_paths",
                return_value=SimpleNamespace(database=database_path),
            ), patch(
                "pastor_transcript_extractor.commands.identity.metadata.Database",
                return_value=database,
            ), patch(
                "pastor_transcript_extractor.commands.identity.metadata."
                "latest_metadata_description",
                return_value=None,
            ), patch(
                "pastor_transcript_extractor.commands.identity.metadata."
                "build_tool_config"
            ) as build_tools:
                enrich_metadata_command(
                    video_id=1,
                    profile_id=None,
                    all_anonymous_profiles=False,
                    plan_only=True,
                    base_dir=Path(tmp),
                )

        build_tools.assert_not_called()

    def test_metadata_analysis_plan_does_not_construct_llm(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            database_path = Path(tmp) / "app.db"
            database_path.touch()
            with patch(
                "pastor_transcript_extractor.commands.identity.metadata.build_paths",
                return_value=SimpleNamespace(database=database_path),
            ), patch(
                "pastor_transcript_extractor.commands.identity.metadata.Database"
            ), patch(
                "pastor_transcript_extractor.commands.identity.metadata."
                "profile_metadata_candidate_profile_ids",
                return_value=(3,),
            ), patch(
                "pastor_transcript_extractor.commands.identity.metadata."
                "build_llm_config"
            ) as build_llm:
                analyze_profile_metadata_command(
                    all_profiles=False,
                    profile_id=3,
                    model=None,
                    details=False,
                    plan_only=True,
                    base_dir=Path(tmp),
                )

        build_llm.assert_not_called()


if __name__ == "__main__":
    unittest.main()
