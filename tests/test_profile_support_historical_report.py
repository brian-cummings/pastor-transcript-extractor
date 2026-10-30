from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import json
import unittest
from typer.testing import CliRunner
from pastor_transcript_extractor.cli import app
from pastor_transcript_extractor.pastor_evidence import digest


class HistoricalReportTests(unittest.TestCase):
    def test_old_report_remains_readable_after_implementation_changes(self):
        with TemporaryDirectory() as folder:
            root=Path(folder);plan=dict(code_identity={'old':'historical-hash'});plan['input_fingerprint']=digest(plan);(root/'plan.json').write_text(json.dumps(plan));report=dict(plan_fingerprint=plan['input_fingerprint'],decision='NOT_READY');(root/'acceptance-report.json').write_text(json.dumps(report))
            with patch('pastor_transcript_extractor.profile_support_acceptance.load',side_effect=AssertionError('Do not execute old code')):
                result=CliRunner().invoke(app,['analysis','profile-support','acceptance-report','--plan',str(root/'plan.json'),'--json'])
            self.assertEqual(result.exit_code,0,result.output);self.assertEqual(json.loads(result.output),report)
            plan['code_identity']['old']='tampered';(root/'plan.json').write_text(json.dumps(plan))
            result=CliRunner().invoke(app,['analysis','profile-support','acceptance-report','--plan',str(root/'plan.json'),'--json'])
            self.assertNotEqual(result.exit_code,0);self.assertIn('digest differs',result.output)
