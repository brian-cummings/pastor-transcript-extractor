from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from typer.testing import CliRunner

from pastor_transcript_extractor.cli import app
from pastor_transcript_extractor.models import (
    SourceType,
    TranscriptSourceKind,
    VideoStatus,
)
from pastor_transcript_extractor.storage import Database


class SourceProcessingEnablementTests(unittest.TestCase):
    def test_disable_and_enable_commands_control_bulk_processing_state(self) -> None:
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmp:
            base_dir = Path(tmp)
            database = Database(base_dir / "app.db")
            database.initialize()
            source = database.add_source(
                "https://www.youtube.com/@sample",
                SourceType.CHANNEL,
                None,
            )

            disabled = runner.invoke(
                app,
                [
                    "source",
                    "disable",
                    str(source.id),
                    "--base-dir",
                    str(base_dir),
                ],
            )

            self.assertEqual(0, disabled.exit_code, msg=disabled.output)
            self.assertFalse(database.get_source_by_id(source.id).processing_enabled)
            self.assertEqual([], database.list_processing_enabled_sources())

            listed = runner.invoke(
                app,
                ["source", "list", "--base-dir", str(base_dir)],
            )
            self.assertEqual(0, listed.exit_code, msg=listed.output)
            self.assertIn("disabled", listed.output)
            self.assertIn("Recordings", listed.output)
            self.assertIn("0", listed.output)

            enabled = runner.invoke(
                app,
                [
                    "source",
                    "enable",
                    str(source.id),
                    "--base-dir",
                    str(base_dir),
                ],
            )

            self.assertEqual(0, enabled.exit_code, msg=enabled.output)
            self.assertTrue(database.get_source_by_id(source.id).processing_enabled)
            self.assertEqual([source.id], [item.id for item in database.list_processing_enabled_sources()])

    def test_source_list_excludes_queued_recordings_unless_requested(self) -> None:
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmp:
            base_dir = Path(tmp)
            database = Database(base_dir / "app.db")
            database.initialize()
            source = database.add_source(
                "https://www.youtube.com/@sample",
                SourceType.CHANNEL,
                None,
            )
            downloaded_video = database.add_video(
                source.id,
                None,
                "downloaded-video",
                "Downloaded recording",
                "https://www.youtube.com/watch?v=downloaded-video",
                status=VideoStatus.DISCOVERED,
            )
            database.add_transcript_artifact(
                downloaded_video.id,
                TranscriptSourceKind.CAPTIONS,
                audio_path=None,
            )
            database.add_video(
                source.id,
                None,
                "queued-video",
                "Queued recording",
                "https://www.youtube.com/watch?v=queued-video",
                status=VideoStatus.DISCOVERED,
            )
            self.assertEqual(
                {source.id: 1}, database.count_recordings_by_source()
            )
            self.assertEqual(
                {source.id: 2},
                database.count_recordings_by_source(include_queued=True),
            )

            result = runner.invoke(
                app,
                ["source", "list", "--base-dir", str(base_dir)],
            )

            self.assertEqual(0, result.exit_code, msg=result.output)
            self.assertIn("Recordings", result.output)
            self.assertIn("1", result.output)

            including_queued = runner.invoke(
                app,
                ["source", "list", "--include-queued", "--base-dir", str(base_dir)],
            )

            self.assertEqual(0, including_queued.exit_code, msg=including_queued.output)
            self.assertIn("2", including_queued.output)

    def test_new_column_defaults_existing_sources_to_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            database_path = Path(tmp) / "app.db"
            database = Database(database_path)
            database.initialize()
            source = database.add_source(
                "https://www.youtube.com/@existing",
                SourceType.CHANNEL,
                None,
            )
            with database.connect() as connection:
                connection.execute(
                    "ALTER TABLE sources RENAME COLUMN processing_enabled TO legacy_enabled"
                )

            database.initialize()

            reloaded = database.get_source_by_id(source.id)
            self.assertIsNotNone(reloaded)
            self.assertTrue(reloaded.processing_enabled)


if __name__ == "__main__":
    unittest.main()
