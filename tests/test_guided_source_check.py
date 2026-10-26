from copy import deepcopy
from dataclasses import asdict,replace
from decimal import Decimal
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from typer.testing import CliRunner

from pastor_transcript_extractor import guided_source_check as g
from pastor_transcript_extractor.cli import app
from test_source_context_trial import fixture
from test_learning_demo_correction import wire_response


def packet():
    _,_,value,output=fixture();case=value['cases'][0]
    spec=g.source_request(case)
    value=dict(request=asdict(spec),window=case['window'],history=dict(prior_attempts=67,prior_paid_attempts=39,
        prior_local_attempts=28,prior_known_list_price_usage_usd='0.322889032'))
    value['input_fingerprint']=g.digest(value)
    return value,output


class GuidedSourceTests(unittest.TestCase):
    def test_one_saved_answer_binding_replacement_preserves_source_and_checks_coverage(self):
        from pastor_transcript_extractor import binding_retry
        value,valid=packet();old=g.requests.RequestSpec(**value['request'])
        bad=deepcopy(valid);bad['claims'][0]['proposition']['span']['text']='missing'
        response=dict(output=json.dumps(bad))
        corrected=binding_retry.retry_request(old,response,[dict(path='$.claims[0].proposition.span',code='literal',message='missing')],contextual=True)
        self.assertEqual(corrected.body['messages'][:2],old.body['messages'])
        self.assertEqual(json.loads(corrected.body['messages'][2]['content']),bad)
        self.assertEqual(corrected.body['response_format'],old.body['response_format'])
        corrected.preflight()
        value['request']=asdict(corrected)
        value['policy']=dict(binding_correction=True,binding_ids=g.context.inventory(valid))
        for drop in (False,True):
            output=deepcopy(valid)
            if drop: output['claims'].pop()
            calls=[];verifier=[]
            def flash(spec): calls.append(spec);return wire_response(spec,json.dumps(output))
            def typesafe(spec):
                verifier.append(spec)
                return dict(model='jev-1.13.0',complete=True,usage=dict(input_tokens=100,output_tokens=100),
                    output={k:dict(type='noul',noul=.5) for k in spec.body['questions']})
            with self.subTest(drop=drop),TemporaryDirectory() as directory:
                result=g.run_recipe(value,Path(directory)/'execution',flash,typesafe)
                self.assertEqual(len(calls),1);self.assertEqual(len(verifier),0 if drop else 1)
                self.assertEqual(result['status'],'FAIL(component)' if drop else 'INCONCLUSIVE')

    def test_unchanged_full_schema_source_and_mechanically_derived_guide(self):
        _,_,old,_=fixture();case=old['cases'][0];spec=g.source_request(case)
        self.assertEqual(spec.body['messages'][1],case['request']['body']['messages'][1])
        self.assertEqual(spec.body['response_format']['json_schema']['schema'],g.context.schema())
        self.assertIn('$.claims[].address_acts[].adoption: string',spec.body['messages'][0]['content'])
        self.assertIn('$.claims[].adoption: object',spec.body['messages'][0]['content'])
        self.assertNotIn('Output schema:',spec.body['messages'][0]['content'])
        self.assertEqual(spec.body['max_tokens'],8192);self.assertEqual(spec.body['reasoning_effort'],'none')
        self.assertLessEqual(spec.preflight()['request_upper_bound'],49152)
        total=g.hosted.reserved_usd(spec.version)+g.requests.reservation('source_verification')
        self.assertEqual(total,Decimal('0.017498112'))

    def test_shared_binding_and_conditional_typesafe_with_no_automatic_correction(self):
        value,valid=packet();calls=[];verifiers=[]
        def flash(spec): calls.append(spec);return wire_response(spec,json.dumps(valid))
        def typesafe(spec):
            verifiers.append(spec)
            return dict(model='jev-1.13.0',complete=True,usage=dict(input_tokens=100,output_tokens=100),
                output={k:dict(type='noul',noul=.5) for k in spec.body['questions']})
        with TemporaryDirectory() as directory:
            root=Path(directory)/'execution';result=g.run_recipe(value,root,flash,typesafe)
            self.assertEqual(len(calls),1);self.assertEqual(len(verifiers),1)
            self.assertEqual(result['contract_fit'],'PASS');self.assertEqual(result['status'],'INCONCLUSIVE')
            self.assertEqual(result['accounting']['paid_attempts'],2)
            self.assertEqual(result['accounting']['cumulative_paid_attempts'],41)
            self.assertEqual(result['context_eligibility']['eligible_observation_ids'],[])
            self.assertEqual(result['accounting']['runtime_repairs'],0)
            self.assertEqual(g.run_recipe(value,root,lambda s:self.fail('no replay call'),typesafe),result)

    def test_invalid_or_unbound_output_and_length_never_call_verifier_or_retry(self):
        for kind in ('json','binding','length'):
            value,valid=packet();calls=[]
            if kind=='binding': valid['claims'][0]['proposition']['span']['text']='missing'
            def send(spec):
                calls.append(spec)
                return wire_response(spec,'not JSON' if kind=='json' else json.dumps(valid),finish='length' if kind=='length' else 'stop')
            with self.subTest(kind=kind),TemporaryDirectory() as directory:
                result=g.run_recipe(value,Path(directory)/'execution',send,lambda s:self.fail('no verifier'))
                self.assertEqual(len(calls),1);self.assertEqual(result['status'],'FAIL(component)')

    def test_read_only_cli_and_frozen_authorization_budget_guards(self):
        value,_=packet();runner=CliRunner()
        with patch.object(g,'run',return_value=dict(status='PREPARED_NO_EXECUTION')) as run:
            result=runner.invoke(app,['analysis','learning-demo','model-fit','guided-source-run','--input','/tmp/input.json','--check-only','--json'])
            self.assertEqual(result.exit_code,0,result.output);self.assertTrue(run.call_args.kwargs['check_only'])
        with TemporaryDirectory() as directory:
            root=Path(directory);value['history']['prior_input']=str(root/'prior/input.json')
            value['budget']=dict(reserved_usd='0.017498112',max_usd='0.02')
            value['input_fingerprint']=g.digest({k:v for k,v in value.items() if k!='input_fingerprint'})
            path=g.directory(root,value['input_fingerprint'])/'input.json';path.parent.mkdir(parents=True);path.write_text(json.dumps(value))
            with patch.object(g,'prepare',return_value=(value,path.parent)):
                self.assertEqual(g.run(path,root,check_only=True)['paid_calls'],0)
                self.assertFalse((path.parent/'execution').exists())
                with self.assertRaises(ValueError): g.run(path,root)
                for cap in ('0.01','0.03','NaN'):
                    with self.assertRaises(ValueError): g.run(path,root,max_usd=cap,check_only=True)
