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
