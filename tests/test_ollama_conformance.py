import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from typer.testing import CliRunner
from pastor_transcript_extractor import ollama_conformance as check
from pastor_transcript_extractor.cli import app
from pastor_transcript_extractor.evidence_requests import WireResponse


class ConformanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.runtime = dict(model='qwen3.5:9b', base_url='http://127.0.0.1:11434',
            manifest_sha256='synthetic', num_ctx=131072, input_cap=122880,
            thinking_supported=True, thinking=False)
        self.identity = patch.object(check.requests, 'ollama_runtime_identity', return_value=self.runtime)
        self.version = patch.object(check, 'server_version', return_value='0.31.1')
        self.identity.start(); self.version.start()
        self.addCleanup(self.identity.stop); self.addCleanup(self.version.stop)
        self.prepared = check.prepare(self.base)
        self.input = Path(self.prepared['input'])

    def response(self, spec, content=None, **changes):
        raw = dict(model=spec.body['model'], done=True, done_reason='stop',
                   prompt_eval_count=100, eval_count=30,
                   message=dict(content=content or json.dumps(dict(result='SCHEMA_ENFORCED', detail=dict(marker='SYNTHETIC_ONLY')))))
        return WireResponse(200,json.dumps({**raw, **changes}))

    def test_prepare_never_generates_and_only_synthetic_bodies(self):
        self.assertEqual(self.prepared['generation_calls'],0)
        packet = json.loads(self.input.read_text())
        self.assertEqual(len(packet['requests']),2)
        for raw in packet['requests']:
            self.assertEqual(raw['body']['format'],check.SCHEMA)
            self.assertFalse(raw['body']['think'])
            self.assertEqual(raw['namespace'],check.VERSION)
            self.assertEqual(raw['body']['options']['num_predict'],8192)
        self.assertNotIn('target_text',self.input.read_text())

    def test_wire_receipts_pass_and_completed_run_never_repeats(self):
        calls=[]
        def send(spec):
            calls.append(spec)
            return self.response(spec)
        result=check.run(self.input,self.base,transport=send)
        self.assertEqual(result['status'],'PASS')
        self.assertEqual(result['attempts'],2)
        self.assertEqual(len(list(self.input.parent.glob('execution/wire-responses/*.json'))),2)
        self.assertEqual(check.run(self.input,self.base,transport=send),result)
        self.assertEqual(len(calls),2)
        self.assertTrue((self.input.parent/'report.md').exists())

    def test_ignored_schema_conflicting_probe_fails(self):
        def send(spec):
            return self.response(spec, 'RUNTIME_UNCONSTRAINED' if spec.source_identity['synthetic_case']=='conflicting' else None)
        result=check.run(self.input,self.base,transport=send)
        self.assertEqual(result['status'],'FAIL(component)')
        self.assertEqual([r['status'] for r in result['checks']],['PASS','FAIL(component)'])

    def test_duplicate_missing_extra_nested_and_enum_rejected(self):
        bad=['{"result":"SCHEMA_ENFORCED","result":"SCHEMA_ENFORCED"}',
             '{"result":"SCHEMA_ENFORCED"}',
             '{"result":"SCHEMA_ENFORCED","detail":{"marker":"WRONG"}}',
             '{"result":"SCHEMA_ENFORCED","detail":{"marker":"SYNTHETIC_ONLY","extra":true}}']
        for value in bad:
            with self.subTest(value=value),self.assertRaises(ValueError):
                check.validate_shape(check.strict_json(value),check.SCHEMA)

    def test_lost_response_consumes_slot_and_stops_without_retry(self):
        calls=[]
        def send(spec):
            calls.append(spec)
            raise OSError('synthetic lost response')
        result=check.run(self.input,self.base,transport=send)
        self.assertEqual(result['status'],'INCONCLUSIVE')
        self.assertEqual(result['attempts'],1)
        self.assertEqual(check.run(self.input,self.base,transport=send),result)
        self.assertEqual(len(calls),1)

    def test_incomplete_response_halts(self):
        result=check.run(self.input,self.base,transport=lambda spec:self.response(spec,done_reason='length'))
        self.assertEqual(result['status'],'INCONCLUSIVE')
        self.assertEqual(result['attempts'],1)
        self.assertEqual(len(list(self.input.parent.glob('execution/receipts/*.json'))),1)

    def test_unexpected_thinking_halts_without_admitting_content(self):
        result=check.run(self.input,self.base,transport=lambda spec:self.response(spec,
            message=dict(content='{}',thinking='unexpected')))
        self.assertEqual(result['status'],'INCONCLUSIVE')
        self.assertEqual(result['checks'],[])
        self.assertEqual(result['attempts'],1)

    def test_interrupted_uncertain_attempt_cannot_be_reissued(self):
        frozen=json.loads(self.input.read_text())
        spec=check.requests.RequestSpec(**frozen['requests'][0])
        store=check.requests.ReceiptStore(self.input.parent/'execution')
        store.write_immutable('attempts/'+spec.fingerprint+'.json',dict(
            request_fingerprint=spec.fingerprint,phase=spec.phase,reserved_usd='0',namespace=check.VERSION))
        calls=[]
        result=check.run(self.input,self.base,transport=lambda spec:calls.append(spec))
        self.assertEqual(result['status'],'INCONCLUSIVE')
        self.assertIn('lacks receipt',result['halt'])
        self.assertEqual(calls,[])

    def test_runtime_change_blocks_before_generation(self):
        calls=[]
        with patch.object(check,'server_version',return_value='changed'):
            with self.assertRaisesRegex(ValueError,'changed after freeze'):
                check.run(self.input,self.base,transport=lambda spec:calls.append(spec))
        self.assertEqual(calls,[])

    def test_tampered_input_and_wrong_base_rejected(self):
        with self.assertRaisesRegex(ValueError,'configured application base'):
            check.run(self.input,self.base/'different')
        raw=json.loads(self.input.read_text());raw['budget']['max_attempts']=3
        self.input.write_text(json.dumps(raw))
        with self.assertRaisesRegex(ValueError,'input changed'):
            check.run(self.input,self.base)

    def test_cli_prepare_default_and_explicit_execution(self):
        runner=CliRunner()
        with patch.object(check,'prepare',return_value=self.prepared) as prepare:
            result=runner.invoke(app,['analysis','learning-demo','runtime-check','--json'])
            self.assertEqual(result.exit_code,0,result.output)
            prepare.assert_called_once()
        with patch.object(check,'run',return_value=dict(status='PASS')) as run:
            result=runner.invoke(app,['analysis','learning-demo','runtime-check','--execute','--input',str(self.input),'--json'])
            self.assertEqual(result.exit_code,0,result.output)
            run.assert_called_once()
        result=runner.invoke(app,['analysis','learning-demo','runtime-check','--execute'])
        self.assertNotEqual(result.exit_code,0)


if __name__=='__main__':
    unittest.main()
