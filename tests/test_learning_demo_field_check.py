from copy import deepcopy
from dataclasses import asdict
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from typer.testing import CliRunner

from pastor_transcript_extractor import learning_demo_field_check as f
from pastor_transcript_extractor import evidence_requests as r
from pastor_transcript_extractor.pastor_evidence import SourceWindow,digest
from pastor_transcript_extractor.cli import app
from test_learning_demo_feedback import packet as baseline,Stub


def packet():
    prior,output=baseline();spec,candidates=f.verification(SourceWindow(**prior['window']),prior['observations'])
    value=dict(request=asdict(spec),candidate_map=candidates,history=dict(prior_attempts=33,
        prior_local_attempts=28,prior_paid_attempts=5,prior_known_list_price_usage_usd='0.230670556'),
        previous_findings={o['id']:{field:dict(probability=.5) for field in f.FIELDS} for o in prior['observations']},
        policy=dict(limitation='Synthetic diagnostic only'),budget=dict(maximum_attempts=1,max_usd='0.003'))
    value['input_fingerprint']=digest(value)
    return value,output


class FieldCheckTests(unittest.TestCase):
    def test_literal_passages_are_complete_and_exact_including_unicode(self):
        prior,_=baseline();window=SourceWindow(**prior['window'])
        block=deepcopy(window.blocks[0]);block['target_text']='An assertion — with a qualification.\nAnother statement.'
        window=SourceWindow(**{**asdict(window),'blocks':[block]})
        spec,_=f.verification(window,prior['observations'])
        state=spec.body['state'];text=state['source']['texts']['target_text']
        self.assertEqual(text,block['target_text'])
        for passage in state['source_passages']:
            self.assertEqual(passage['text'],text[passage['start']:passage['end']])
        for question in spec.body['questions'].values():
            self.assertNotIn('start/end range',json.dumps(question))

    def test_same_fields_for_all_claims_no_labels_or_prior_probabilities(self):
        value,_=packet();body=value['request']['body'];items=body['state']['items']
        self.assertEqual(len(body['questions']),len(items)*2*(1+len(body['state']['source_passages'])))
        for item in items:
            self.assertTrue(all(item['id']+':'+field in body['questions'] for field in f.FIELDS))
        self.assertNotIn('previous_findings',body['state']);self.assertNotIn('known_error',json.dumps(body))
        self.assertNotIn('expected_answers',json.dumps(body))

    def test_question_policy_is_invariant_to_names_and_order(self):
        prior,_=baseline();window=SourceWindow(**prior['window'])
        observations=deepcopy(prior['observations']);observations.reverse()
        for i,o in enumerate(observations):
            o['id']='unrelated-'+str(i);o['binding']['binding_id']='different-'+str(i)
        spec,_=f.verification(window,observations)
        for i,o in enumerate(observations):
            for field in f.FIELDS:
                q=spec.body['questions'][o['id']+':'+field]
                self.assertEqual(q['instructions']['binding_id'],o['binding']['binding_id'])
                self.assertIn(f'items[{i}].binding',q['instructions']['instruction'])
                self.assertEqual(q['instructions']['criterion'],f.contract.CHECK_MEANINGS[field])

    def test_candidate_values_are_copied_without_repair_or_label_specific_prompt(self):
        prior,_=baseline();observations=deepcopy(prior['observations']);original=deepcopy(observations)
        spec,_=f.verification(SourceWindow(**prior['window']),observations)
        self.assertEqual(observations,original)
        altered=deepcopy(observations);altered[0]['binding']['polarity']['value']='denied'
        changed,_=f.verification(SourceWindow(**prior['window']),altered)
        key=observations[0]['id']+':polarity'
        self.assertEqual(spec.body['questions'][key]['criteria'],changed.body['questions'][key]['criteria'])
        a=deepcopy(spec.body['questions'][key]['instructions']);b=deepcopy(changed.body['questions'][key]['instructions'])
        a.pop('returned_value');b.pop('returned_value');self.assertEqual(a,b)
        self.assertEqual(changed.body['questions'][key]['instructions']['returned_value']['value'],'denied')

    def test_probability_report_keeps_uncertainty_and_never_claims_accuracy(self):
        value,output=packet();stub=Stub(output)
        with TemporaryDirectory() as directory:
            store=r.ReceiptStore(Path(directory)/'execution');result=f.run_recipe(value,store,stub.typesafe)
            self.assertEqual(result['execution_status'],'COMPLETE');self.assertEqual(result['status'],'INCONCLUSIVE')
            self.assertFalse(result['production_admission']);self.assertEqual(len(result['field_comparisons']),4)
            self.assertEqual(result['accounting']['attempts'],1)
            self.assertEqual(result['accounting']['cumulative_attempts'],34)
            self.assertEqual(f.run_recipe(value,store,stub.typesafe),result);self.assertEqual(len(stub.calls),1)

    def test_boundaries_are_fixed_not_selected_from_results(self):
        value,output=packet();stub=Stub(output)
        def send(spec):
            response=stub.typesafe(spec)
            for i,key in enumerate(k for k in response['output'] if not k.startswith('passage-')):
                response['output'][key]['noul']=(.1,.9,.5,.99)[i]
            return response
        with TemporaryDirectory() as directory:
            result=f.run_recipe(value,r.ReceiptStore(Path(directory)/'execution'),send)
            self.assertEqual([row['outcome'] for row in result['field_comparisons']],['FAIL','PASS','INCONCLUSIVE','PASS'])

    def test_timeout_and_missing_answer_stop_without_retry(self):
        for kind in ('timeout','missing'):
            with self.subTest(kind=kind),TemporaryDirectory() as directory:
                value,output=packet();stub=Stub(output);calls=[]
                def send(spec):
                    calls.append(spec)
                    if kind=='timeout':raise OSError('timed out')
                    result=stub.typesafe(spec);result['output'].pop(next(iter(result['output'])))
                    return result
                store=r.ReceiptStore(Path(directory)/'execution');result=f.run_recipe(value,store,send)
                self.assertEqual(result['status'],'FAIL(component)')
                f.run_recipe(value,store,send);self.assertEqual(len(calls),1)

    def test_cli_tie_in_has_no_provider_calls_during_preparation(self):
        runner=CliRunner();value,_=packet()
        with patch.object(f,'prepare',return_value=(value,Path('/tmp/frozen'))):
            result=runner.invoke(app,['analysis','learning-demo','model-fit','field-check-prepare','--from-input','/tmp/prior.json','--json'])
            self.assertEqual(result.exit_code,0,result.output);self.assertIn('"provider_calls": 0',result.stdout)
        with patch.object(f,'run',return_value=dict(status='PREPARED_NO_EXECUTION')) as run:
            result=runner.invoke(app,['analysis','learning-demo','model-fit','field-check-run','--input','/tmp/input.json','--check-only','--json'])
            self.assertEqual(result.exit_code,0,result.output);self.assertTrue(run.call_args.kwargs['check_only'])
            self.assertFalse(run.call_args.kwargs['experimental']);self.assertEqual(run.call_args.kwargs['max_usd'],'0.003')

    def test_run_freeze_budget_and_credentials_gate_every_send(self):
        with TemporaryDirectory() as directory:
            base=Path(directory);value,_=packet();value.pop('input_fingerprint')
            value['budget']['reserved_usd']='0.002752512'
            value['history']['prior_input']=str(base/'prior/input.json')
            value['input_fingerprint']=digest(value);out=f.directory(base,value['input_fingerprint'])
            out.mkdir(parents=True);path=out/'input.json';path.write_text(json.dumps(value))
            with patch.object(f,'prepare',return_value=(value,out)),patch.object(r,'typesafe_transport') as send:
                self.assertEqual(f.run(path,base,check_only=True)['paid_calls'],0)
                for cap in ('0.002','0.004','NaN','bad'):
                    with self.subTest(cap=cap),self.assertRaises(ValueError):f.run(path,base,max_usd=cap)
                with self.assertRaisesRegex(ValueError,'--experimental'):f.run(path,base)
                with patch.dict('os.environ',{},clear=True),self.assertRaisesRegex(ValueError,'TYPESAFE_API_KEY'):
                    f.run(path,base,experimental=True,approve_input=value['input_fingerprint'],confirm_prices=True)
                self.assertFalse((out/'execution').exists());send.assert_not_called()
            changed=deepcopy(value);changed['policy']['limitation']='changed'
            with patch.object(f,'prepare',return_value=(changed,out)),self.assertRaisesRegex(ValueError,'changed after freeze'):
                f.run(path,base,check_only=True)
