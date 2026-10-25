"""Bounded local model-fit tests use synthetic source text and stub transports only."""
from copy import deepcopy
from dataclasses import asdict,replace
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from pastor_transcript_extractor import learning_demo_model_fit as fit
from pastor_transcript_extractor.evidence_requests import RequestSpec,ReceiptStore,WireResponse
from pastor_transcript_extractor.learning_demo_contracts import generation_request
from test_learning_demo import synthetic_packet,FakeProvider


def packet():
    original=synthetic_packet()
    runtime=dict(model='qwen3.5:9b',base_url='http://127.0.0.1:11434',num_ctx=131072,
                 input_cap=122880,thinking_supported=True,thinking=False)
    cases=[original['windows'][index]['id'] for index in (0,4,8,12,16,20)]
    original['windows']=[row for row in original['windows'] if row['id'] in cases]
    original['source_requests']=[row for row in original['source_requests'] if row['case_id'] in cases]
    for row in original['source_requests']:
        old=RequestSpec(**row['request'])
        request=replace(generation_request('source_reading',json.loads(old.body['messages'][1]['content']),
            old.source_identity,runtime_identity=runtime),namespace=fit.NAMESPACE)
        row.update(request=asdict(request),fingerprint=request.fingerprint,token_account=request.preflight())
    original.update(generation_runtime=runtime,contracts=dict(schemas=fit.contract.SCHEMAS),
        baseline={cases[0]:dict(status='SAVED_BASELINE_DO_NOT_SEND',literal_bound_claims=0)})
    return original


class ModelFitTests(unittest.TestCase):
    def test_selection_covers_all_six_recordings_both_profiles_and_two_frozen_controls(self):
        windows=[dict(id=f'P{profile}-R{video}-{slot}',profile_id=profile,video_id=video)
                 for profile,videos in fit.demo.SCOPE.items() for video in videos for slot in fit.SLOTS]
        cases=fit.select_cases(dict(windows=windows))
        self.assertEqual(cases,[
            'P318-R3973-theology','P130-R1037-theology',
            'P318-R281-application','P130-R350-application',
            'P318-R4589-independent_control','P130-R4430-independent_control'])
        self.assertEqual(sum('independent_control' in case for case in cases),2)

    def test_six_local_calls_no_verifier_no_baseline_input_no_admission(self):
        value=packet();provider=FakeProvider();messages=[]
        with TemporaryDirectory() as directory:
            store=ReceiptStore(Path(directory))
            result=fit.run_recipe(value,store,provider,messages.append)
            self.assertEqual(len(provider.calls),6)
            self.assertEqual({r.phase for r in provider.calls},{'source_reading'})
            self.assertEqual({r.body['model'] for r in provider.calls},{'qwen3.5:9b'})
            self.assertTrue(all('SAVED_BASELINE_DO_NOT_SEND' not in json.dumps(r.body) for r in provider.calls))
            self.assertEqual(result['accounting']['paid_attempts'],0)
            self.assertEqual(result['accounting']['cumulative_attempts'],21)
            self.assertEqual(result['contract_fit'],'PASS')
            self.assertEqual(result['status'],'INCONCLUSIVE')
            self.assertEqual(result['diagnostics']['literal_bound_claims'],12)
            self.assertTrue(all(not r['field_judgments'] and r['production_admission']=='not_admitted'
                                for r in result['observations']))
            self.assertEqual(result['baseline_comparison'][1]['baseline']['status'],'UNATTEMPTED')
            self.assertTrue(any('Source window 6/6' in message for message in messages))
            self.assertEqual(fit.run_recipe(value,store,provider),result)
            self.assertEqual(len(provider.calls),6)

    def test_length_stop_preserves_wire_usage_and_never_retries(self):
        value=packet();calls=[]
        def send(spec):
            calls.append(spec)
            return WireResponse(200,json.dumps(dict(model=spec.body['model'],done=True,done_reason='length',
                prompt_eval_count=42,eval_count=8192,message=dict(content='{unfinished'))))
        with TemporaryDirectory() as directory:
            store=ReceiptStore(Path(directory));result=fit.run_recipe(value,store,send)
            self.assertEqual(result['status'],'FAIL(component)');self.assertIn('length',result['halt'])
            self.assertEqual(len(calls),1);self.assertEqual(result['accounting']['cumulative_attempts'],16)
            self.assertEqual(result['accounting']['known_output_tokens'],8192)
            self.assertTrue(list((store.root/'wire-responses').glob('*.json')))
            self.assertEqual(fit.run_recipe(value,store,send),result);self.assertEqual(len(calls),1)

    def test_literal_failures_are_reported_without_manual_repairs(self):
        value=packet();provider=FakeProvider()
        def send(spec):
            response=provider(spec)
            response['output']['claims'][0]['proposition']['span']['text']='Not present'
            return response
        with TemporaryDirectory() as directory:
            result=fit.run_recipe(value,ReceiptStore(Path(directory)),send)
            self.assertEqual(len(provider.calls),6)
            self.assertEqual(result['contract_fit'],'FAIL(component)')
            self.assertEqual(len(result['failures']),6)
            self.assertEqual(result['diagnostics']['literal_bound_claims'],6)
            self.assertEqual(result['accounting']['runtime_repairs'],0)

    def test_empty_readings_are_inconclusive_and_other_phases_are_rejected(self):
        value=packet()
        def empty(spec):return dict(model=spec.body['model'],complete=True,
            usage=dict(input_tokens=10,output_tokens=10),output=dict(status='none',claims=[]))
        with TemporaryDirectory() as directory:
            result=fit.run_recipe(value,ReceiptStore(Path(directory)),empty)
            self.assertEqual(result['contract_fit'],'INCONCLUSIVE')
        value['source_requests'][0]['request']['phase']='source_verification'
        with TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError,'only its six'):
                fit.run_recipe(value,ReceiptStore(Path(directory)),lambda spec:self.fail('must not send'))

    def test_preflight_does_not_claim_execution_or_require_credentials(self):
        with TemporaryDirectory() as directory,patch.object(fit,'verify',return_value=dict(
            input_fingerprint='synthetic',budget=dict(maximum_attempts=6))),patch.object(fit,'ollama_transport') as send:
            result=fit.run(Path(directory)/'input.json',check_only=True)
            self.assertEqual(result['status'],'PREPARED_NO_EXECUTION');send.assert_not_called()
            self.assertFalse((Path(directory)/'execution').exists())
            with self.assertRaisesRegex(ValueError,'exact fingerprint'):
                fit.run(Path(directory)/'input.json',approve_input='wrong',experimental=True)

    def test_other_history_or_changed_literal_contract_cannot_start_trial(self):
        with TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError,'preserved corrected'):
                fit.history(Path(directory)/'other.json',Path(directory))
        with patch.object(fit,'history',return_value=(dict(contracts={}),{})):
            with self.assertRaisesRegex(ValueError,'unchanged corrected'):
                fit.prepare('/tmp/synthetic.json')

    def test_changed_frozen_recipe_and_reused_trial_claim_are_rejected(self):
        from pastor_transcript_extractor.pastor_evidence import digest
        with TemporaryDirectory() as directory:
            root=Path(directory).resolve();prior=root/'prior/input.json'
            value=dict(schema_version=fit.VERSION,code_identity={},history=dict(prior_input=str(prior)),
                       generation_runtime=dict(model='qwen3.5:9b'))
            value['input_fingerprint']=digest(value)
            out=root/value['input_fingerprint'];out.mkdir();path=out/'input.json';path.write_text(json.dumps(value))
            with patch.object(fit,'directory',lambda base,key:root/key),patch.object(fit,'code_identity',return_value={}),\
                patch.object(fit,'prepare',return_value=(value,out)):
                self.assertEqual(fit.verify(path,root),value)
                marker=prior.parent/'execution/model-fit-authorization.json';marker.parent.mkdir(parents=True)
                marker.write_text(json.dumps(dict(input_fingerprint='another-input')))
                with self.assertRaisesRegex(ValueError,'already assigned'):fit.verify(path,root)
            changed=deepcopy(value);changed['changed_recipe']=True
            with patch.object(fit,'directory',lambda base,key:root/key),patch.object(fit,'code_identity',return_value={}),\
                patch.object(fit,'prepare',return_value=(changed,out)):
                with self.assertRaisesRegex(ValueError,'requests, model or limits'):fit.verify(path,root)


class ModelFitCliTests(unittest.TestCase):
    def test_help_preflight_and_summary_adapter(self):
        from typer.testing import CliRunner
        from pastor_transcript_extractor.cli import app
        runner=CliRunner()
        self.assertEqual(runner.invoke(app,['analysis','learning-demo','model-fit','--help']).exit_code,0)
        with patch.object(fit,'run',return_value=dict(status='PREPARED_NO_EXECUTION')) as run:
            result=runner.invoke(app,['analysis','learning-demo','model-fit','run','--input','/tmp/synthetic.json','--check-only','--json'])
            self.assertEqual(result.exit_code,0,result.output)
            self.assertTrue(run.call_args.kwargs['check_only'])
            self.assertEqual(run.call_args.kwargs['max_usd'],'0')
        with patch.object(fit,'prepare',return_value=(dict(input_fingerprint='synthetic',selection={},budget={}),Path('/tmp/synthetic'))) as prepare:
            result=runner.invoke(app,['analysis','learning-demo','model-fit','prepare','--from-input','/tmp/prior.json','--json'])
            self.assertEqual(result.exit_code,0,result.output)
            self.assertEqual(prepare.call_args.kwargs['model'],'qwen3.5:9b')
