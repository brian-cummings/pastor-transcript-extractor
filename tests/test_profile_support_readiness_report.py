from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest
from pastor_transcript_extractor import profile_support_readiness_report as r
from typer.testing import CliRunner
from pastor_transcript_extractor.cli import app


class ReadinessReportTests(unittest.TestCase):
    def test_altered_reference_cannot_be_used_to_claim_a_pass(self):
        with TemporaryDirectory() as folder:
            root=Path(folder);(root/'human-review').mkdir()
            (root/'regression-inputs.json').write_text('[]');(root/'regression-references.json').write_text('[]')
            work=dict(regression_input_sha256=r.readiness.file_hash(root/'regression-inputs.json'),reference_sha256='original-frozen-reference-digest')
            human=dict(review={});human['packet_fingerprint']=r.x.digest(human)
            for name,value in [('work-plan.json',work),('allowance.json',{}),('regression-report.json',{}),('human-review/packet.json',human)]:
                (root/name).write_text(json.dumps(value))
            with self.assertRaisesRegex(ValueError,'Original frozen'):r.prepare(root)

    def test_saved_report_can_be_read_without_replaying_provider_execution(self):
        with TemporaryDirectory() as folder:
            root=Path(folder);saved=dict(decision='HOLDOUT_BLOCKED',accuracy_established=False)
            saved['report_fingerprint']=r.x.digest(saved)
            (root/'readiness-report.json').write_text(json.dumps(saved));(root/'readiness-report.md').write_text('Pending independent validation.')
            result=CliRunner().invoke(app,['analysis','profile-support','readiness-report','--root',str(root),'--json'])
            self.assertEqual(result.exit_code,0,result.output)
            self.assertEqual(json.loads(result.output),saved)
            saved['accuracy_established']=True;(root/'readiness-report.json').write_text(json.dumps(saved))
            result=CliRunner().invoke(app,['analysis','profile-support','readiness-report','--root',str(root),'--json'])
            self.assertNotEqual(result.exit_code,0);self.assertIn('Readiness report changed',result.output)
