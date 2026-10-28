from copy import deepcopy
import json
from pathlib import Path
import unittest
from pastor_transcript_extractor import qualifier_holdout as h
from pastor_transcript_extractor import deepinfra_requests as provider


def fixture():
    base,_=h.existing.source_first_trial(atomic=True)
    body,trial=h.trial_body(base.body)
    spec=h.existing.requests.RequestSpec(base.phase,body,base.source_identity,namespace=base.namespace,version=base.version,runtime_identity=base.runtime_identity)
    output={}
    for key,item in trial['state'].items():
        units=item['source']['units'];output[key]={}
        for role,expected in trial['audit_index'][key]['expected_roles'].items():
            output[key][role]=None if expected is None else [dict(start_unit=units[0]['id'],end_unit=units[-1]['id'])] if expected else []
    response=dict(model=body['model'],complete=True,usage=dict(input_tokens=100,output_tokens=100),output=json.dumps(output))
    return spec,trial,response


class QualifierHoldoutTests(unittest.TestCase):
    def test_new_sources_no_provider_reference_leak_and_frozen_question(self):
        original,_=h.existing.source_first_trial(atomic=True);spec,trial,_=fixture()
        self.assertEqual(spec.body['messages'][0],original.body['messages'][0])
        payload=json.loads(spec.body['messages'][1]['content'])
        self.assertEqual(payload,trial['state'])
        for token in ('expected_roles','markers','family'):
            self.assertNotIn(token,h.existing.requests.wire(payload))
        previous={x['proposition']['reading'] for x in json.loads(original.body['messages'][1]['content']).values()}
        self.assertTrue(previous.isdisjoint({x['proposition']['reading'] for x in payload.values()}))
        self.assertEqual(len(payload),12)
        self.assertEqual(trial,json.loads(json.dumps(trial)))

    def test_denominators_expected_abstention_and_false_decisions(self):
        spec,trial,response=fixture();result=h.assess(spec,trial,response);s=result['summary']
        self.assertEqual((s['roles'],s['roles_correct'],s['cases_correct']),(24,24,12))
        self.assertEqual({k:v['total'] for k,v in s['by_reference'].items()},dict(positive=7,negative=15,unrecoverable=2))
        self.assertEqual(s['roles_abstained'],2);self.assertEqual(s['missed_required_abstention'],0)
        values=json.loads(response['output'])
        missing=next(k for k,x in trial['audit_index'].items() if x['expected_roles']['concession'] is True)
        negative=next(k for k,x in trial['audit_index'].items() if x['expected_roles']['concession'] is False)
        unknown=next(k for k,x in trial['audit_index'].items() if x['expected_roles']['concession'] is None)
        values[missing]['concession']=[]
        values[negative]['concession']=[dict(start_unit='u0000',end_unit='u0000')]
        values[unknown]=dict(concession=[],expressed_uncertainty=[])
        response['output']=json.dumps(values);s=h.assess(spec,trial,response)['summary']
        self.assertEqual(s['false_positive'],1);self.assertEqual(s['false_negative'],1);self.assertEqual(s['missed_required_abstention'],2)

    def test_unexpected_unknowns_not_claimed_as_success_and_no_mutation(self):
        spec,trial,response=fixture();old=deepcopy(trial);values=json.loads(response['output'])
        key=next(k for k,x in trial['audit_index'].items() if x['expected_roles']['expressed_uncertainty'] is True)
        values[key]['expressed_uncertainty']=None;response['output']=json.dumps(values)
        result=h.assess(spec,trial,response)
        self.assertEqual(result['summary']['roles_withheld'],1)
        self.assertEqual(result['summary']['roles_abstained'],3)
        self.assertFalse(result['production_admission']);self.assertEqual(trial,old)


class TwoModelHoldoutTests(unittest.TestCase):
    def packet(self,folder,pair='qwen'):
        from unittest.mock import patch
        from decimal import Decimal
        spec,trial,_=fixture();body=deepcopy(spec.body);body.pop('model')
        selected=dict(input_fingerprint='frozen-synthetic-cases',body_without_model=body,trial=trial)
        def metadata(model):
            policy=next(p for p in provider.HOLDOUT_POLICIES.values() if p['model']==model)
            return dict(model=model,context=262144,capabilities=['structured-output','can-disable-reasoning'],input_cents_per_token=str(Decimal(policy['input_usd_per_million'])/10000),output_cents_per_token=str(Decimal(policy['output_usd_per_million'])/10000))
        with patch.object(h,'selection',return_value=(selected,Path(folder))),patch.object(provider,'public_model_metadata',side_effect=metadata):
            packet,out=h.prepare(Path(folder),pair=pair,check_only=True)
        return packet,out

    def wire(self,spec,trial,*,thinking=False):
        output={}
        for key,item in trial['state'].items():
            units=item['source']['units'];output[key]={role:None if expected is None else [dict(start_unit=units[0]['id'],end_unit=units[-1]['id'])] if expected else [] for role,expected in trial['audit_index'][key]['expected_roles'].items()}
        return h.existing.requests.WireResponse(200,json.dumps(dict(model=spec.body['model'],choices=[dict(finish_reason='stop',message=dict(content=json.dumps(output),reasoning_content='forbidden' if thinking else ''))],usage=dict(prompt_tokens=100,completion_tokens=100))))

    def test_same_frozen_body_except_model_and_no_legacy_policy_change(self):
        from tempfile import TemporaryDirectory
        from decimal import Decimal
        for pair,reserve in [('qwen','0.0438272'),('flash','0.0258048')]:
            with TemporaryDirectory() as folder:
                packet,_=self.packet(folder,pair)
                bodies=[{k:v for k,v in r['request']['body'].items() if k!='model'} for r in packet['runs']]
                self.assertEqual(bodies[0],bodies[1]);self.assertEqual(packet['budget']['reserved_usd'],reserve)
                self.assertTrue(all(r['request']['body']['reasoning_effort']=='none' for r in packet['runs']))
                for run in packet['runs']:
                    spec=h.existing.requests.RequestSpec(**run['request'])
                    self.assertEqual(h.existing.requests.request_provider(spec),'DeepInfra')
                    self.assertEqual(spec.preflight()['output_cap'],4096)
                self.assertEqual(provider.DIRECT_POLICY['output_cap'],65536)
                self.assertEqual(provider.QWEN_VERIFY_POLICY['input_cap'],16384)

    def test_two_exact_calls_replay_and_mixed_provider_history(self):
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as folder:
            packet,out=self.packet(folder);sent=[]
            def transport(spec):sent.append(spec);return self.wire(spec,packet['selection']['trial'])
            result=h.run_recipe(packet,out,transport)
            self.assertEqual(len(sent),2);self.assertEqual(result['bounded_control_fit'],'PASS')
            self.assertFalse(result['production_admission'])
            self.assertTrue(all(r['result']['assessment']['summary']['roles_correct']==24 for r in result['runs']))
            self.assertEqual(h.run_recipe(packet,out,lambda s:self.fail('no replay')),result)
            with h.existing.integration.cumulative_history(packet,out.parent/'other/execution') as history:
                self.assertEqual(len(history),2)

    def test_flash_reuses_exact_qwen_receipt_without_duplicate_spend(self):
        from tempfile import TemporaryDirectory
        from unittest.mock import patch
        from decimal import Decimal
        with TemporaryDirectory() as folder:
            first,parent=self.packet(folder)
            h.existing.Store(parent).write_immutable('input.json',first)
            original=h.run_recipe(first,parent,lambda spec:self.wire(spec,first['selection']['trial']))
            with patch.object(h,'SAVED_QWEN_COMPARISON',first['input_fingerprint']):
                packet,out=self.packet(folder,'flash')
            self.assertEqual(packet['budget']['maximum_paid_attempts'],1)
            self.assertEqual(packet['budget']['reserved_usd'],'0.0090112')
            sent=[]
            def transport(spec):sent.append(spec);return self.wire(spec,packet['selection']['trial'])
            result=h.run_recipe(packet,out,transport)
            self.assertEqual([s.body['model'] for s in sent],['deepseek-ai/DeepSeek-V4.1-Flash-1017'])
            self.assertTrue(result['runs'][0]['cache_reuse'])
            self.assertEqual(result['runs'][0]['results'],original['runs'][1]['results'])
            self.assertIsNone(result['runs'][0]['elapsed_seconds'])
            self.assertEqual(result['runs'][0]['original_elapsed_seconds'],original['runs'][1]['elapsed_seconds'])
            with h.existing.integration.cumulative_history(packet,out.parent/'other/execution') as history:
                self.assertEqual(len(history),3)
                expected=h.existing.integration.BASELINE_SPEND+sum((v for _,v in history),Decimal(0))
            self.assertEqual(Decimal(result['runs'][1]['result']['accounting']['cumulative_budget_charge_usd']),expected)
            reused=packet['runs'][0]['reuse']
            receipt=next(p for p in reused['preserved_files'] if '/receipts/' in p)
            saved=Path(receipt).read_text();Path(receipt).write_text(saved+' ')
            with self.assertRaisesRegex(ValueError,'changed after freeze'):h.validate_reuse(reused)
            Path(receipt).write_text(saved)
            prior_path=Path(result['runs'][0]['results']).parent.parent/'input.json'
            prior=json.loads(prior_path.read_text());prior['native_trial']['audit_index']['q0']['family']='tampered'
            prior_path.write_text(json.dumps(prior))
            with patch.object(h,'SAVED_QWEN_COMPARISON',first['input_fingerprint']),self.assertRaisesRegex(ValueError,'provenance'):
                self.packet(folder,'flash')

    def test_thinking_failure_preserves_cost_and_other_frozen_model_still_runs(self):
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as folder:
            packet,out=self.packet(folder);sent=[]
            def transport(spec):sent.append(spec);return self.wire(spec,packet['selection']['trial'],thinking=len(sent)==1)
            result=h.run_recipe(packet,out,transport)
            self.assertEqual(len(sent),2);self.assertEqual(result['bounded_control_fit'],'FAIL(component)')
            self.assertIn('emitted reasoning',result['runs'][0]['result']['halt'])
            self.assertEqual(result['runs'][0]['result']['accounting']['known_output_tokens'],100)
            self.assertEqual(result['runs'][1]['result']['assessment']['summary']['roles_correct'],24)

    def test_reserve_both_before_send_and_unknown_spend_charged(self):
        from tempfile import TemporaryDirectory
        from contextlib import contextmanager
        from decimal import Decimal
        from unittest.mock import patch
        @contextmanager
        def almost_full(packet,root):yield [({},Decimal('.62'))]
        with TemporaryDirectory() as folder:
            packet,out=self.packet(folder)
            with patch.object(h.existing.integration,'cumulative_history',almost_full),self.assertRaisesRegex(ValueError,'Both requests'):
                h.run_recipe(packet,out,lambda s:self.fail('must reserve both'))
        with TemporaryDirectory() as folder:
            packet,out=self.packet(folder);sent=[]
            def transport(spec):
                sent.append(spec)
                if len(sent)==1:raise OSError('response lost')
                return self.wire(spec,packet['selection']['trial'])
            result=h.run_recipe(packet,out,transport)
            self.assertEqual(len(sent),2)
            self.assertEqual(result['runs'][0]['result']['accounting']['unknown_usage_attempts'],1)
            expected=h.existing.integration.BASELINE_SPEND+Decimal(packet['runs'][0]['token_account']['reserved_usd'])+Decimal('.00027')
            self.assertEqual(Decimal(result['runs'][-1]['result']['accounting']['cumulative_budget_charge_usd']),expected)

    def test_cli_exact_input_approval_and_budget(self):
        from tempfile import TemporaryDirectory
        from unittest.mock import patch
        from typer.testing import CliRunner
        from pastor_transcript_extractor.cli import app
        with patch.object(h,'run',return_value=dict(status='PREPARED_NO_EXECUTION')) as run:
            result=CliRunner().invoke(app,['analysis','learning-demo','model-fit','qualifier-validation-run','--input','/tmp/frozen.json','--check-only','--json'])
            self.assertEqual(result.exit_code,0,result.output);self.assertTrue(run.call_args.kwargs['check_only'])
        with TemporaryDirectory() as folder:
            packet,out=self.packet(folder);out.mkdir(parents=True);path=out/'input.json';path.write_text(json.dumps(packet))
            with patch.object(h,'prepare',return_value=(packet,out)):
                self.assertEqual(h.run(path,Path(folder),check_only=True)['paid_calls'],0)
                with self.assertRaises(ValueError):h.run(path,Path(folder))
                with self.assertRaises(ValueError):h.run(path,Path(folder),max_usd='.01',check_only=True)
