from copy import deepcopy
from dataclasses import asdict
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from typer.testing import CliRunner
from pastor_transcript_extractor import polarity_choice_check as c
from pastor_transcript_extractor.cli import app
from test_attachment_trial import packet as attachment_packet


def packet():
    base,valid=attachment_packet();cases=[]
    for case in base['cases']:
        cases.append(dict(case_id=case['case_id'],source=c.demo._source_state(c.SourceWindow(**case['window']))['texts']['target_text'],reading=deepcopy(valid)))
    spec,index=c.make_request(cases)
    return dict(input_fingerprint='synthetic',request=asdict(spec),audit_index=index,
        history=dict(prior_accounting=dict(cumulative_attempts=89,cumulative_local_attempts=28,cumulative_paid_attempts=61,
            cumulative_known_list_price_usage_usd='0.353800674')))


def response(spec,index,*,uncertain=False,wrong=False):
    answers={}
    for key,audit in index.items():
        choice=audit['expected'] or 'affirmed'
        if wrong and audit['origin']=='synthetic_control': choice='denied' if choice!='denied' else 'affirmed'
        probabilities={label:(.97 if label==choice else .01) for label in c.CRITERIA}
        answers[key]=dict(type='choice',choice=choice,probabilities=probabilities,confidence=.5 if uncertain else .99)
    return dict(model='jev-1.13.0',complete=True,usage=dict(input_tokens=100,output_tokens=100),output=answers)


class PolarityChoiceTests(unittest.TestCase):
    def test_automatic_questions_hide_prior_decisions_and_keep_full_source(self):
        value=packet();spec=c.requests.RequestSpec(**value['request'])
        self.assertEqual(len(spec.body['questions']),10)
        for item in spec.body['state']['items']:
            self.assertEqual(set(item),{'source_id','proposition'})
            self.assertEqual(set(item['proposition']),{'span','reading'})
            self.assertIn(item['proposition']['span']['text'],spec.body['state']['sources'][item['source_id']])
        for key in ('previous_polarity','expected','rationale','probability_correct','origin'):
            self.assertNotIn('"'+key+'"',c.requests.wire(spec.body))
        self.assertEqual({a['expected'] for a in value['audit_index'].values() if a['origin']=='synthetic_control'},set(c.CRITERIA))
        spec.preflight()

    def test_choice_validation_rejects_invalid_distributions_inventory_and_confidence(self):
        value=packet();spec=c.requests.RequestSpec(**value['request']);good=response(spec,value['audit_index'])
        for kind in ('missing','type','sum','selected','confidence','bool'):
            result=deepcopy(good);key=next(iter(result['output']));answer=result['output'][key]
            if kind=='missing': result['output'].pop(key)
            if kind=='type': answer['type']='noul'
            if kind=='sum': answer['probabilities'][answer['choice']]=.5
            if kind=='selected': answer['choice']=next(k for k in c.CRITERIA if k!=answer['choice'])
            if kind=='confidence': answer['confidence']=float('nan')
            if kind=='bool': answer['confidence']=True
            with self.subTest(kind=kind),self.assertRaises(ValueError): c.decisions(result,spec,value['audit_index'])
        rounded=deepcopy(good)
        for answer in rounded['output'].values(): answer['probabilities'][answer['choice']]=.96
        self.assertEqual(len(c.decisions(rounded,spec,value['audit_index'])),10)

    def test_one_call_controls_and_disagreement_never_repair_or_admit(self):
        for kind in ('pass','uncertain','wrong','timeout'):
            value=packet();sent=[]
            def transport(spec):
                sent.append(spec)
                if kind=='timeout': raise OSError('synthetic timeout')
                return response(spec,value['audit_index'],uncertain=kind=='uncertain',wrong=kind=='wrong')
            with self.subTest(kind=kind),TemporaryDirectory() as directory:
                root=Path(directory);result=c.run_recipe(value,root,transport)
                self.assertEqual(len(sent),1);self.assertFalse(result['production_admission'])
                self.assertEqual(result['control_fit'],{'pass':'PASS','uncertain':'INCONCLUSIVE','wrong':'FAIL(component)','timeout':'FAIL(component)'}[kind])
                self.assertEqual(result['accounting']['cumulative_paid_attempts'],62)
                self.assertEqual(c.run_recipe(value,root,lambda s:self.fail('no replay')),result)
                if kind!='timeout': self.assertEqual(len(result['decisions']),10)

    def test_cli_and_read_only_authorization_budget_guards(self):
        runner=CliRunner()
        with patch.object(c,'run',return_value=dict(status='PREPARED_NO_EXECUTION')) as run:
            result=runner.invoke(app,['analysis','learning-demo','model-fit','polarity-choice-run','--input','/tmp/input.json','--check-only','--json'])
            self.assertEqual(result.exit_code,0,result.output);self.assertTrue(run.call_args.kwargs['check_only'])
        with TemporaryDirectory() as directory:
            base=Path(directory);value=packet();value['budget']=dict(reserved_usd='0.002752512')
            value['input_fingerprint']=c.digest({k:v for k,v in value.items() if k!='input_fingerprint'})
            path=c.directory(base,value['input_fingerprint'])/'input.json';path.parent.mkdir(parents=True);path.write_text(json.dumps(value))
            with patch.object(c,'prepare',return_value=(value,path.parent)):
                self.assertEqual(c.run(path,base,check_only=True)['paid_calls'],0)
                self.assertFalse((path.parent/'execution').exists())
                with self.assertRaises(ValueError): c.run(path,base)
                for ceiling in ('0.001','0.004','NaN'):
                    with self.assertRaises(ValueError): c.run(path,base,max_usd=ceiling,check_only=True)
