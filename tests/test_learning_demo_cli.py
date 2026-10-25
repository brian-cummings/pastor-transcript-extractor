import unittest
from unittest.mock import patch
from typer.testing import CliRunner
from pastor_transcript_extractor.cli import app


class LearningCliTests(unittest.TestCase):
    def test_help_and_read_only_adapter(self):
        runner=CliRunner()
        self.assertEqual(runner.invoke(app,['analysis','learning-demo','--help']).exit_code,0)
        with patch('pastor_transcript_extractor.learning_demo.run',return_value=dict(status='PREPARED_NO_EXECUTION',provider_calls=0)) as run:
            result=runner.invoke(app,['analysis','learning-demo','run','--input','/tmp/fixture-input.json','--check-only','--json'])
            self.assertEqual(result.exit_code,0,result.output)
            self.assertTrue(run.call_args.kwargs['check_only'])
            self.assertFalse(run.call_args.kwargs['experimental'])
            self.assertIn('"provider_calls": 0',result.output)
