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

    def test_verifier_price_flag_and_reduced_default_budget(self):
        runner=CliRunner()
        with patch('pastor_transcript_extractor.learning_demo.run',return_value=dict(status='PREPARED_NO_EXECUTION')) as run:
            result=runner.invoke(app,['analysis','learning-demo','run','--input','/tmp/fixture-input.json',
                '--experimental','--approve-input','fixture','--confirm-verifier-price','--json'])
            self.assertEqual(result.exit_code,0,result.output)
            self.assertTrue(run.call_args.kwargs['confirm_proposal_prices'])
            self.assertEqual(run.call_args.kwargs['max_usd'],'0.10')

    def test_execution_routes_to_ollama_without_openai_key(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory
        import os
        from pastor_transcript_extractor import learning_demo as demo
        from pastor_transcript_extractor.learning_demo_contracts import generation_request,verification_request
        from unittest.mock import patch
        with TemporaryDirectory() as directory:
            packet=dict(input_fingerprint='fixture')
            def stub_pipeline(packet,store,transport,**kwargs):
                transport(generation_request('source_reading',{},{}))
                transport(verification_request('source_verification',{},[dict(id='a')],{},source=True))
                return dict(status='INCONCLUSIVE')
            with patch.dict(os.environ,{'TYPESAFE_API_KEY':'test-only'},clear=True),\
                patch.object(demo,'verify_input',return_value=(packet,None)),\
                patch.object(demo,'execute_pipeline',side_effect=stub_pipeline),\
                patch.object(demo,'ollama_transport',return_value={}) as local,\
                patch.object(demo,'typesafe_transport',return_value={}) as verifier:
                result=demo.run(Path(directory)/'input.json',approve_input='fixture',experimental=True,
                    max_usd='.10',confirm_proposal_prices=True)
                self.assertEqual(result['status'],'INCONCLUSIVE')
                self.assertEqual(local.call_count,1);self.assertEqual(verifier.call_count,1)
                self.assertNotIn('OPENAI_API_KEY',os.environ)
