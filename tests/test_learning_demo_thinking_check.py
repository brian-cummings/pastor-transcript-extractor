from copy import deepcopy
from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from pastor_transcript_extractor import evidence_requests as requests
from pastor_transcript_extractor import learning_demo_thinking_check as thinking
from pastor_transcript_extractor.learning_demo_contracts import generation_request
from pastor_transcript_extractor.pastor_evidence import digest
from test_learning_demo_model_fit import packet
from test_learning_demo import FakeProvider


def specimen():
    original=packet()
    old=requests.RequestSpec(**original['source_requests'][0]['request'])
    runtime={**old.runtime_identity,'thinking':True,'server_version':'0.40.11',
             'local_request_policy':deepcopy(requests.THINKING_CHECK_POLICY)}
    body=deepcopy(old.body)
    body.update(think=True,format=thinking.schema())
    body['options']['num_predict']=4096
    body['options']['num_ctx']=requests.ollama_context_for(body)
    spec=replace(old,body=body,runtime_identity=runtime,namespace=thinking.VERSION,version=requests.THINKING_CHECK_VERSION)
    value=dict(request=asdict(spec),window=original['windows'][0],schema=thinking.schema(),limitation='synthetic fixture')
    value['input_fingerprint']=digest(value)
    return value,spec


class ThinkingCheckTests(unittest.TestCase):
    def test_timeout_scales_with_budget_and_legacy_policy_stays_disabled(self):
        _,spec=specimen()
        small=spec.preflight()
        body=deepcopy(spec.body);body['messages'][1]['content']+='x'*12000
        body['options']['num_ctx']=requests.ollama_context_for(body)
        larger=replace(spec,body=body).preflight()
        self.assertGreater(larger['execution_policy']['timeout_seconds'],small['execution_policy']['timeout_seconds'])
        self.assertLessEqual(larger['execution_policy']['timeout_seconds'],1800)
        self.assertEqual(small['output_cap'],4096)
        old=generation_request('source_reading',{}, {})
        self.assertEqual(requests.local_execution_settings(old),dict(thinking=False,output_cap=8192,timeout_seconds=600))
        for changed in (replace(spec,namespace='learning-demo-v3'),replace(spec,version=old.version),
                        replace(spec,runtime_identity={**spec.runtime_identity,'thinking':False})):
            with self.assertRaises(ValueError):changed.preflight()

    def test_native_transport_receives_dynamic_timeout_and_thinking(self):
        _,spec=specimen()
        with TemporaryDirectory() as directory:
            manifest=Path(directory)/'manifest';manifest.write_text('synthetic installed identity')
            spec=replace(spec,runtime_identity={**spec.runtime_identity,'manifest_path':str(manifest),
                'manifest_sha256':hashlib.sha256(manifest.read_bytes()).hexdigest()})
            with patch('httpx.Client') as factory:
                client=factory.return_value.__enter__.return_value
                client.post.return_value.status_code=200;client.post.return_value.text='{}'
                requests.ollama_transport(spec)
                self.assertEqual(factory.call_args.kwargs['timeout'],spec.preflight()['execution_policy']['timeout_seconds'])
                self.assertTrue(client.post.call_args.kwargs['json']['think'])
                self.assertFalse(factory.call_args.kwargs['trust_env'])

    def test_thinking_is_preserved_separately_and_never_evidence(self):
        value,spec=specimen();provider=FakeProvider();calls=[]
        def send(request):
            calls.append(request);response=provider(request)
            return requests.WireResponse(200,json.dumps(dict(model=request.body['model'],done=True,done_reason='stop',
                prompt_eval_count=100,eval_count=100,message=dict(content=json.dumps(response['output']),
                    thinking='SYNTHETIC_REASONING_NEVER_SOURCE_EVIDENCE'))))
        with TemporaryDirectory() as directory:
            store=requests.ReceiptStore(Path(directory)/'execution')
            result=thinking.run_recipe(value,store,send)
            self.assertTrue(result['thinking_emitted'])
            self.assertEqual(result['contract_fit'],'PASS')
            self.assertEqual(result['status'],'INCONCLUSIVE')
            self.assertEqual(result['accounting']['cumulative_attempts'],28)
            self.assertEqual(result['accounting']['paid_attempts'],0)
            self.assertEqual(result['literal_bound_claims'],2)
            self.assertNotIn('SYNTHETIC_REASONING',json.dumps(result['observations']))
            self.assertIn('SYNTHETIC_REASONING',next((store.root/'wire-responses').glob('*.json')).read_text())
            self.assertEqual(thinking.run_recipe(value,store,send),result)
            self.assertEqual(len(calls),1)

    def test_token_overflow_incomplete_and_lost_responses_stop_without_retry(self):
        for kind in ('overflow','length','timeout'):
            value,spec=specimen();calls=[]
            def send(request):
                calls.append(request)
                if kind=='timeout':raise TimeoutError('synthetic timeout')
                return requests.WireResponse(200,json.dumps(dict(model=request.body['model'],done=True,
                    done_reason='length' if kind=='length' else 'stop',prompt_eval_count=10,
                    eval_count=4096 if kind=='length' else 4097,message=dict(content='{}',thinking='trace'))))
            with self.subTest(kind=kind),TemporaryDirectory() as directory:
                store=requests.ReceiptStore(Path(directory)/'execution')
                result=thinking.run_recipe(value,store,send)
                self.assertEqual(result['status'],'FAIL(component)')
                self.assertTrue(result['halt'])
                self.assertEqual(thinking.run_recipe(value,store,send),result)
                self.assertEqual(len(calls),1)

    def test_two_claim_schema_and_existing_literal_compiler_stay_strict(self):
        value,spec=specimen();provider=FakeProvider()
        def send(request):
            response=provider(request)
            response['output']['claims'][0]['proposition']['node_id']='undefined-node'
            return {**response,'output':json.dumps(response['output'])}
        with TemporaryDirectory() as directory:
            result=thinking.run_recipe(value,requests.ReceiptStore(Path(directory)/'execution'),send)
            self.assertEqual(result['contract_fit'],'FAIL(component)')
            self.assertEqual(result['literal_bound_claims'],1)
            self.assertIn('missing evidence node',result['failures'][0]['reason'])
        from pastor_transcript_extractor import learning_demo_contracts as contract
        self.assertEqual(thinking.schema()['properties']['claims']['maxItems'],2)
        self.assertEqual(contract.READ_SCHEMA['properties']['claims']['maxItems'],12)

    def test_cli_preflight_has_no_execution_and_run_requires_exact_input(self):
        from typer.testing import CliRunner
        from pastor_transcript_extractor.cli import app
        value,spec=specimen();value.update(budget={},token_account=spec.preflight())
        with patch.object(thinking,'verify',return_value=(value,Path('/tmp/unused-thinking-marker'))),\
             patch.object(requests,'ollama_transport') as send:
            output=CliRunner().invoke(app,['analysis','learning-demo','model-fit','thinking-run',
                '--input','/tmp/synthetic.json','--check-only','--json'])
            self.assertEqual(output.exit_code,0,output.output);send.assert_not_called()
            with self.assertRaisesRegex(ValueError,'exact thinking input'):
                thinking.run('/tmp/synthetic.json',experimental=True,approve_input='wrong')
