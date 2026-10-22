"""Small end-to-end receipts for the integrated read-only profile workflow."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from typer.testing import CliRunner

from pastor_transcript_extractor import profile_description as description
from pastor_transcript_extractor.cli import app
from test_profile_description import fixture


class ProfileWorkflowTests(unittest.TestCase):
    def test_generation_and_check_only_report_same_integrated_scope(self):
        record = description.build(*fixture(routed=True))
        command = ['analysis', 'structure-readiness', '--segment-view', '--description', '--json']
        with TemporaryDirectory() as base, patch.object(description, 'load', return_value=record), patch.object(
                description, 'build_paths', return_value=SimpleNamespace(evaluation=Path(base))):
            generated = CliRunner().invoke(app, command)
            self.assertEqual(0, generated.exit_code, generated.output)
            result = json.loads(generated.output)
            output = Path(result['path'])
            before = {path.name: path.read_bytes() for path in output.parent.iterdir()}
            with patch.object(description, 'prepare', side_effect=AssertionError('check-only cannot write')):
                checked = CliRunner().invoke(app, command+['--check-only'])
            self.assertEqual(0, checked.exit_code, checked.output)
            check = json.loads(checked.output)
            self.assertIsNone(check.pop('path'))
            result.pop('path')
            self.assertEqual(result, check)
            self.assertEqual('pastor-profile-description-v7', result['profile_version'])
            self.assertEqual([9], result['recording_ids'])
            self.assertGreater(result['supporting_examples']['selected'], 0)
            self.assertFalse(result['new_measurements'])
            self.assertFalse(result['quote_execution'])
            self.assertEqual(before, {path.name: path.read_bytes() for path in output.parent.iterdir()})
            self.assertIn('next-capability-v2.md', before)
            self.assertIn('description-v7.json', before)
            self.assertIn('review-v7.json', before)
            self.assertFalse(any('v4' in name for name in before))
            manifest = json.loads(before['description-v7.json'])
            self.assertEqual('pastor-profile-description-v7', manifest['version'])
            self.assertEqual('pastor-profile-reader-v7', manifest['description']['reader']['version'])
            self.assertTrue(any(path.endswith('profile_explanatory_descriptions.py') for path in manifest['implementation_files']))
            self.assertIn('How the recordings compare', before['profile-v7.md'].decode())
            self.assertNotIn('No bound-position pilot has been executed', before['index.html'].decode())


if __name__ == '__main__':
    unittest.main()
