from pathlib import Path
from unittest.mock import patch
import unittest
from typer.testing import CliRunner
from pastor_transcript_extractor import evidence_probe_retirement as retired


class RetirementTests(unittest.TestCase):
    def test_record_supersedes_without_rewriting_original_authorization(self):
        decision=retired.closure()
        self.assertEqual('SUPERSEDED_UNEXECUTED',decision['status'])
        self.assertFalse(decision['execution_allowed']);self.assertIsNone(decision['semantic_verdict'])

    def test_frozen_git_paths_reject_traversal(self):
        for path in ('../secret','/tmp/absolute'):
            with self.assertRaisesRegex(ValueError,'path'):retired.archived_bytes(path)

    def test_cli_retired_prepare_and_run_never_reach_provider(self):
        from pastor_transcript_extractor.cli import app
        from pastor_transcript_extractor import context_extraction_probe as old
        with patch.object(old,'run',side_effect=AssertionError('No old execution')),patch.object(old,'prepare',side_effect=AssertionError('No rematerialization')):
            for flags in (['--prepare'],['--run','--approve-input',retired.INPUT_FINGERPRINT]):
                result=CliRunner().invoke(app,['analysis','collector-retrieval-design','--context-extraction-probe',*flags])
                self.assertEqual(2,result.exit_code,result.output);self.assertIn('RETIRED',result.output)

    def test_old_python_runner_fails_frozen_pins_before_credentials(self):
        from pastor_transcript_extractor import context_extraction_probe as old
        with patch.object(old,'transport',side_effect=AssertionError('No transport')):
            with self.assertRaisesRegex(ValueError,'pin changed'):old.run(approve_input=retired.INPUT_FINGERPRINT)

    def test_cli_readonly_archive_mode(self):
        from pastor_transcript_extractor.cli import app
        with patch.object(retired,'verify',return_value=dict(status='SUPERSEDED_UNEXECUTED',input_fingerprint=retired.INPUT_FINGERPRINT)):
            result=CliRunner().invoke(app,['analysis','collector-retrieval-design','--context-extraction-probe','--check-only'])
            self.assertEqual(0,result.exit_code,result.output);self.assertIn('read-only',result.output)
