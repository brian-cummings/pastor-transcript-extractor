from copy import deepcopy
from dataclasses import asdict
from decimal import Decimal
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from typer.testing import CliRunner
from pastor_transcript_extractor import reference_field_validation as v
from pastor_transcript_extractor.cli import app


def packet():
    source='I assert the gate is open. The guide said the gate is closed. I endorse his words. The recording cuts off.'
    cases=[]
    for text,expected in [('I assert the gate is open.',dict(adoption='own_assertion',adoption_basis=True,qualifications=True)),('The guide said the gate is closed.',dict(adoption='adopted',adoption_basis=False,qualifications=False)),('The recording cuts off.',dict(adoption=None,adoption_basis=None,qualifications=True))]:
        span=v.evidence.locate_literal_spans(dict(source_field='target_text',text=text),dict(target_text=source))
        cases.append(dict(span=span,reference_id='r'+str(len(cases)),expected=expected,reference=dict(proposition=dict(reading='HIDDEN EVALUATOR PARAPHRASE'),rationale='HIDDEN SOURCE REFERENCE')))
    spec,index=v.request(cases,source)
    return dict(input_fingerprint='synthetic',cases=cases,request=asdict(spec),audit_index=index,budget=dict(prior_recorded_usd=str(v.integration.BASELINE_SPEND),reserved_usd='.002752512'),reference_authority='synthetic controls; not pastor references')


def response(value,mode='correct'):
    answers={}
    for n,case in enumerate(value['cases']):
        for field,expected in case['expected'].items():
            key=f'q{n}_{field}'
            if field=='adoption':
                options=v.check.choices.CRITERIA['adoption'];choice=expected or 'undetermined'
                if mode=='wrong':choice=next(k for k in options if k!=choice)
                answers[key]=dict(type='choice',choice=choice,confidence=.5 if mode=='uncertain' else .99,probabilities={k:.97 if k==choice else .03/(len(options)-1) for k in options})
            else:
                p=.99 if expected else .01
                if mode=='wrong':p=1-p
                answers[key]=dict(type='noul',noul=.5 if mode=='uncertain' else p)
    return dict(model='jev-1.13.0',complete=True,usage=dict(input_tokens=100,output_tokens=100),output=answers)


class ReferenceFieldTests(unittest.TestCase):
    def test_reference_answers_and_authored_readings_never_enter_wire_state(self):
        value=packet();spec=v.requests.RequestSpec(**value['request']);spec.preflight()
        text=v.requests.wire(spec.body)
        for token in ('HIDDEN','reference_id','expected','rationale','reference_authority'):
            self.assertNotIn(token,text)
        for item,case in zip(spec.body['state']['items'],value['cases']):
            self.assertEqual(item['proposition']['reading'],case['span']['text'])
            self.assertEqual(item['proposed'],dict(adoption_basis='own_speech',qualifications=[]))

    def test_correct_wrong_unknown_and_reference_unknown_denominators(self):
        for mode in ('correct','wrong','uncertain'):
            value=packet();records,summary=v.evaluate(value,response(value,mode))
            self.assertEqual(len(records),9)
            self.assertEqual(summary['adoption']['reference_adjudicable'],2)
            self.assertEqual(summary['adoption_basis']['reference_adjudicable'],2)
            self.assertEqual(summary['qualifications']['reference_adjudicable'],3)
            if mode=='correct': self.assertEqual(summary['qualifications']['correct'],3)
            if mode=='wrong':
                self.assertEqual(summary['adoption']['wrong'],2)
                self.assertEqual(summary['qualifications']['false_accept'],1)
                self.assertEqual(summary['qualifications']['false_reject'],2)
            if mode=='uncertain':
                self.assertEqual(summary['adoption']['withheld'],2)
                self.assertEqual(summary['qualifications']['supported_but_withheld'],2)

    def test_one_call_no_replay_no_admission_lost_response_and_malformed_probabilities(self):
        for mode in ('correct','timeout','malformed'):
            value=packet();sent=[]
            def transport(spec):
                sent.append(spec)
                if mode=='timeout':raise OSError('lost response')
                out=response(value)
                if mode=='malformed':out['output']['q0_qualifications']['noul']=True
                return out
            with self.subTest(mode=mode),TemporaryDirectory() as folder:
                result=v.run_recipe(value,Path(folder),transport)
                self.assertEqual(len(sent),1);self.assertEqual(result,v.run_recipe(value,Path(folder),lambda s:self.fail('no replay call')))
                self.assertEqual(result['status'],'INCONCLUSIVE' if mode=='correct' else 'FAIL(component)')
                self.assertFalse(result['production_admission']);self.assertFalse((Path(folder)/'observations.json').exists())
                if mode=='timeout': self.assertEqual(result['accounting']['cumulative_budget_charge_usd'],str(v.integration.BASELINE_SPEND+Decimal('.002752512')))

    def test_frozen_cli_and_budget_authorization(self):
        with patch.object(v,'run',return_value=dict(status='PREPARED_NO_EXECUTION')) as run:
            out=CliRunner().invoke(app,['analysis','learning-demo','model-fit','reference-fields-run','--input','/tmp/input.json','--check-only','--json'])
            self.assertEqual(out.exit_code,0,out.output);self.assertTrue(run.call_args.kwargs['check_only'])
        with TemporaryDirectory() as folder:
            value=packet();value['input_fingerprint']=v.digest({k:x for k,x in value.items() if k!='input_fingerprint'})
            path=v.directory(Path(folder),value['input_fingerprint'])/'input.json';path.parent.mkdir(parents=True);path.write_text(json.dumps(value))
            with patch.object(v,'prepare',return_value=(value,path.parent)):
                self.assertEqual(v.run(path,Path(folder),check_only=True)['paid_calls'],0)
                self.assertFalse((path.parent/'execution').exists())
                with self.assertRaises(ValueError):v.run(path,Path(folder))
                for amount in ('.001','.004','NaN'):
                    with self.assertRaises(ValueError):v.run(path,Path(folder),max_usd=amount,check_only=True)
            changed=deepcopy(value);changed['version']='foreign'
            with patch.object(v,'prepare',return_value=(changed,path.parent)),self.assertRaises(ValueError):v.run(path,Path(folder),check_only=True)


class PairedWordingTests(unittest.TestCase):
    def fixture(self):
        spec,index=v.paired_request(v.pair_controls())
        trial=dict(name='controls',request=asdict(spec),audit_index=index)
        return dict(input_fingerprint='paired-synthetic',rounds=[trial,dict(deepcopy(trial),name='transfer')],budget=dict(spend_root='unused'))

    def answers(self,spec,mode='correct'):
        output={}
        for key in spec.body['questions']:
            n=key.split('_',1)[0]
            # Expected values belong only to the audit, never provider state.
            item=int(n[1:]);field='adoption_basis' if 'adoption_basis' in key else 'qualifications'
            expected=v.pair_controls()[item]['expected'][field]
            p=.99 if expected else .01
            if mode=='wrong':p=1-p
            if mode=='uncertain':p=.5
            output[key]=dict(type='noul',noul=p)
        return dict(model='jev-1.13.0',complete=True,usage=dict(input_tokens=100,output_tokens=10),output=output)

    def test_same_targets_both_arms_no_expected_labels_and_balanced_controls(self):
        packet=self.fixture();spec=v.requests.RequestSpec(**packet['rounds'][0]['request'])
        self.assertNotIn('expected',v.requests.wire(spec.body));self.assertEqual(len(spec.body['questions']),32)
        for n,item in enumerate(spec.body['state']['items']):
            for field in ('adoption_basis','qualifications'):
                for arm in ('current','narrow'):
                    question=spec.body['questions'][f'q{n}_{field}_{arm}']
                    self.assertIn(f'items[{n}].proposition',question['instructions'])
                    self.assertIn(f'sources.w{n}',question['instructions'])
        for field in ('adoption_basis','qualifications'):
            self.assertEqual({c['expected'][field] for c in v.pair_controls()},{False,True})

    def test_confident_wrong_scores_worse_and_unknown_not_counted_correct(self):
        trial=self.fixture()['rounds'][0];spec=v.requests.RequestSpec(**trial['request'])
        for mode in ('correct','wrong','uncertain'):
            result=v.paired_assess(trial,self.answers(spec,mode))
            for arm in result['summary'].values():
                self.assertEqual(arm['adjudicable'],16)
                self.assertEqual(arm['correct'],16 if mode=='correct' else 0)
                self.assertEqual(arm['wrong'],16 if mode=='wrong' else 0)
                self.assertEqual(arm['withheld'],16 if mode=='uncertain' else 0)

    def test_two_frozen_calls_no_retry_no_replay_and_unknown_spend_stops(self):
        for lost in (False,True):
            packet=self.fixture();sent=[]
            # Distinct provenance avoids an identical-request cache hit in this fixture.
            packet['rounds'][1]['request']['source_identity']['round']='transfer'
            def transport(spec):
                sent.append(spec)
                if lost: raise OSError('response lost')
                return self.answers(spec)
            with TemporaryDirectory() as folder:
                packet['budget']['spend_root']=folder
                result=v.pair_recipe(packet,Path(folder)/'run',transport)
                self.assertEqual(len(sent),1 if lost else 2)
                self.assertFalse(result['production_admission'])
                self.assertEqual(result['status'],'FAIL(component)' if lost else 'INCONCLUSIVE')
                self.assertEqual(result,v.pair_recipe(packet,Path(folder)/'run',lambda s:self.fail('replay')))
                if lost:self.assertEqual(result['accounting']['cumulative_budget_charge_usd'],str(v.integration.BASELINE_SPEND+Decimal('.002752512')))

    def test_cumulative_cap_blocks_transport_and_cli_tie_in(self):
        from contextlib import contextmanager
        @contextmanager
        def near_cap(packet,root):yield [(None,Decimal('.635'))]
        with TemporaryDirectory() as folder,patch.object(v.integration,'cumulative_history',near_cap):
            result=v.pair_recipe(self.fixture(),Path(folder),lambda s:self.fail('budget must block'))
            self.assertEqual(result['accounting']['attempts'],0)
            self.assertIn('below $1',result['halt'])
        with patch.object(v,'pair_run',return_value=dict(status='PREPARED_NO_EXECUTION')) as run:
            result=CliRunner().invoke(app,['analysis','learning-demo','model-fit','question-pair-run','--input','/tmp/input.json','--check-only','--json'])
            self.assertEqual(result.exit_code,0,result.output);self.assertTrue(run.call_args.kwargs['check_only'])


class FieldIsolationTests(unittest.TestCase):
    def test_only_other_field_values_and_unused_questions_change(self):
        original=PairedWordingTests().fixture()['rounds'][0]
        isolated=v.isolate_qualifications(original)
        before=original['request']['body'];after=isolated['request']['body']
        self.assertEqual(after['model'],before['model'])
        self.assertEqual(after['state']['sources'],before['state']['sources'])
        self.assertEqual(len(after['questions']),8)
        for a,b in zip(after['state']['items'],before['state']['items'],strict=True):
            self.assertEqual(a['proposition'],b['proposition'])
            self.assertEqual(a['source_id'],b['source_id'])
            self.assertEqual(a['proposed'],dict(qualifications=b['proposed']['qualifications']))
        for key,question in after['questions'].items():
            self.assertEqual(question,before['questions'][key])
            self.assertEqual(isolated['audit_index'][key],original['audit_index'][key])
        self.assertNotIn('expected',v.requests.wire(after))
        self.assertNotIn('own_speech',v.requests.wire(after))
        self.assertEqual(original,PairedWordingTests().fixture()['rounds'][0])

    def test_one_call_policy_and_cli_selects_exact_isolation_round(self):
        fixture=PairedWordingTests();packet=fixture.fixture()
        packet['rounds']=[v.isolate_qualifications(packet['rounds'][0])]
        packet['baseline']=dict(rows=[]);packet['limitation']='Synthetic field isolation'
        packet['budget'].update(maximum_paid_attempts=1,max_usd='.003')
        with TemporaryDirectory() as folder:
            packet['budget']['spend_root']=folder;calls=[]
            def transport(spec):calls.append(spec);return fixture.answers(spec)
            result=v.pair_recipe(packet,Path(folder)/'run',transport)
            self.assertEqual(len(calls),1)
            self.assertEqual(result['accounting']['attempts'],1)
            self.assertEqual(result['baseline'],packet['baseline'])
            self.assertEqual(result['limitation'],packet['limitation'])
            self.assertFalse(result['production_admission'])
        with patch.object(v,'pair_run',return_value=dict(status='PREPARED_NO_EXECUTION')) as run:
            out=CliRunner().invoke(app,['analysis','learning-demo','model-fit','question-pair-run','--input','/tmp/input.json','--isolate-round','neutral_controls','--max-usd','.003','--check-only','--json'])
            self.assertEqual(out.exit_code,0,out.output)
            self.assertEqual(run.call_args.kwargs['isolate_round'],'neutral_controls')


class QwenInstantTests(unittest.TestCase):
    def fixture(self):
        from pastor_transcript_extractor import deepinfra_requests as hosted
        trial=v.isolate_qualifications(PairedWordingTests().fixture()['rounds'][0]);spec=v.qwen_request(trial)
        packet=dict(input_fingerprint='synthetic-qwen',request=asdict(spec),native_trial=trial,baseline={},policy=dict(reasoning_effort='none'),limitation='synthetic',budget=dict(max_usd='.02',spend_root='unused'))
        return packet,spec,hosted

    def wire(self,spec,trial,*,reasoning=False):
        output={}
        for key,meta in trial['audit_index'].items():
            item=trial['request']['body']['state']['items'][meta['item']];source=trial['request']['body']['state']['sources'][item['source_id']]
            output[key]=dict(verdict=meta['expected'],rationale='Synthetic source supports this test verdict.',source_quote=source)
        return v.requests.WireResponse(200,json.dumps(dict(model=spec.body['model'],choices=[dict(finish_reason='stop',message=dict(content=json.dumps(output),reasoning_content='forbidden trace' if reasoning else ''))],usage=dict(prompt_tokens=100,completion_tokens=200))))

    def test_exact_questions_and_targets_retained_no_expected_or_probabilities_in_prompt(self):
        packet,spec,hosted=self.fixture();payload=json.loads(spec.body['messages'][1]['content'])
        native=packet['native_trial']['request']['body']
        self.assertEqual(payload,dict(state=native['state'],questions=native['questions']))
        self.assertEqual(spec.body['reasoning_effort'],'none');self.assertEqual(v.requests.request_provider(spec),'DeepInfra')
        self.assertEqual(v.requests.request_model(spec),'Qwen/Qwen3.8-27B')
        self.assertEqual(spec.preflight()['reserved_usd'],'0.0135168')
        self.assertNotIn('expected',spec.body['messages'][1]['content'])
        self.assertNotIn('probabilities',spec.body['messages'][1]['content'])
        self.assertEqual(hosted.POLICY['model'],'deepseek-ai/DeepSeek-V4-Pro-0813')

    def test_thinking_or_model_substitution_rejected_and_usage_preserved(self):
        from dataclasses import replace
        packet,spec,hosted=self.fixture()
        for changed in (replace(spec,body=dict(spec.body,reasoning_effort='low')),replace(spec,body=dict(spec.body,model=hosted.FLASH_MODEL))):
            with self.assertRaises(ValueError):changed.preflight()
        with TemporaryDirectory() as folder:
            store=v.requests.ReceiptStore(Path(folder))
            with self.assertRaisesRegex(ValueError,'emitted reasoning'):
                v.requests.execute(spec,hosted.OneRequestLedger('.02',spec.version),store,lambda s:self.wire(s,packet['native_trial'],reasoning=True))
            self.assertEqual(v.check.demo.usage_account(store)['known_output_tokens'],200)

    def test_one_call_replay_mixed_provider_ledger_and_literal_quote_validation(self):
        packet,spec,hosted=self.fixture()
        with TemporaryDirectory() as folder:
            packet['budget']['spend_root']=folder;calls=[]
            def send(s):calls.append(s);return self.wire(s,packet['native_trial'])
            root=Path(folder)/'qwen/execution';result=v.qwen_recipe(packet,root,send)
            self.assertEqual(result['assessment']['summary']['correct'],8)
            self.assertEqual(len(calls),1);self.assertFalse(result['production_admission'])
            self.assertEqual(v.qwen_recipe(packet,root,lambda s:self.fail('replay')),result)
            with v.integration.cumulative_history(packet,Path(folder)/'other/execution') as history:
                self.assertEqual(len(history),1);self.assertEqual(history[0][1],Decimal('.00052'))
            response=json.loads((root/'receipts'/f'{spec.fingerprint}.json').read_text())['response']
            output=json.loads(response['output']);output[next(iter(output))]['source_quote']='fabricated quotation'
            response['output']=json.dumps(output)
            with self.assertRaisesRegex(ValueError,'not literal'):v.qwen_assess(packet,response)
            output[next(iter(output))]['verdict']=.99;response['output']=json.dumps(output)
            with self.assertRaisesRegex(ValueError,'contract differs'):v.qwen_assess(packet,response)

    def test_unknown_spend_and_qwen_cli_routing(self):
        packet,spec,hosted=self.fixture()
        with TemporaryDirectory() as folder:
            packet['budget']['spend_root']=folder
            def lost(s):raise OSError('lost response')
            result=v.qwen_recipe(packet,Path(folder)/'qwen/execution',lost)
            self.assertEqual(result['accounting']['cumulative_budget_charge_usd'],str(v.integration.BASELINE_SPEND+Decimal('.0135168')))
            self.assertEqual(result['status'],'FAIL(component)')
        with patch.object(v,'qwen_run',return_value=dict(status='PREPARED_NO_EXECUTION')) as run:
            out=CliRunner().invoke(app,['analysis','learning-demo','model-fit','question-pair-run','--input','/tmp/input.json','--qwen-instant','--max-usd','.02','--check-only','--json'])
            self.assertEqual(out.exit_code,0,out.output);self.assertTrue(run.call_args.kwargs['check_only'])
