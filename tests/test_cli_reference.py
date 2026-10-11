from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from typer.main import get_command
from typer.testing import CliRunner

from pastor_transcript_extractor.cli import app
from pastor_transcript_extractor.commands.cli_docs import render_cli_reference


class CliReferenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = CliRunner()

    def test_includes_nested_commands_and_representative_pte_commands(self) -> None:
        document = render_cli_reference(get_command(app))

        self.assertIn("## `pte analysis`", document)
        self.assertIn("### `pte analysis structure-run`", document)
        self.assertIn("## `pte identity`", document)
        self.assertIn("### `pte identity run`", document)
        self.assertIn("### `pte media archive-sources`", document)

    def test_includes_command_arguments_options_and_status(self) -> None:
        document = render_cli_reference(get_command(app))

        self.assertIn("## `pte add`", document)
        self.assertIn("| `URL` | YouTube video, playlist, or channel URL.  [required] | yes | — |", document)
        self.assertIn("| `--pastor TEXT` | Pastor slug to associate with this source.  [required] | yes | — |", document)
        self.assertIn("| `--base-dir PATH` | Override app data directory. | no | — |", document)

    def test_uses_descriptions_from_cli_definitions(self) -> None:
        document = render_cli_reference(get_command(app))

        self.assertIn("Manage reviewed profile reference panels.", document)
        self.assertIn("Create an idempotent named reference panel.", document)

    def test_output_is_deterministic(self) -> None:
        command = get_command(app)

        self.assertEqual(
            render_cli_reference(command),
            render_cli_reference(command),
        )

    def test_docs_command_writes_the_rendered_reference(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "reference.md"
            result = self.runner.invoke(app, ["docs", "cli", "--output", str(output)])

            self.assertEqual(0, result.exit_code, msg=result.output)
            self.assertEqual(render_cli_reference(get_command(app)), output.read_text())


if __name__ == "__main__":
    unittest.main()
