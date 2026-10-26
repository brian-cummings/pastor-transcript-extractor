from copy import deepcopy
from dataclasses import asdict
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from typer.testing import CliRunner
from pastor_transcript_extractor import condition_model_check as c
from pastor_transcript_extractor.cli import app
from test_learning_demo_correction import wire_response


def answer():
    values=[]
    for i,case in enumerate(c.controls.cases()[:5]):
        row=case['reading']['claims'][0];nodes={n['node_id']:n for n in row['evidence_nodes']}
        values.append(dict(case_id='s'+str(i+1),conditions=deepcopy(row['conditions']),
            qualifications=[dict(span=nodes[q['node_id']]['span'],reading=q['reading']) for q in row['qualifications']],
            conditional_consequences=[dict(proposition=nodes[r['to_node']]['span'],
                conditions=[dict(kind='condition',span=q,rationale='Synthetic condition on consequence.') for q in r['stated_qualifications']],
                rationale='Synthetic consequence.') for r in row['development_relations']]))
    return dict(cases=values)


def packet():
    return dict(input_fingerprint='synthetic-test',request=asdict(c.reader_request()),
        history=dict(prior_accounting=dict(cumulative_attempts=73,cumulative_local_attempts=28,
            cumulative_paid_attempts=45,cumulative_known_list_price_usage_usd='0.332433348')))


class ConditionModelTests(unittest.TestCase):
    def test_request_has_only_sources_and_propositions_without_reference_answers(self):
        spec=c.reader_request();state=json.loads(spec.body['messages'][1]['content'])
        self.assertEqual(state,dict(synthetic=True,cases=c.inputs()))
        self.assertEqual(len(state['cases']),5)
        self.assertEqual(spec.body['reasoning_effort'],'none');self.assertEqual(spec.body['max_tokens'],8192)
        self.assertLessEqual(spec.preflight()['request_upper_bound'],49152)
        self.assertEqual(c.inspect(answer())['errors'],[])
        self.assertTrue(all(r['outcome']=='PASS' for r in c.assess(answer())))

    def test_fixed_reference_checks_detect_wrong_attachment_and_separate_concession(self):
        value=answer();value['cases'][0]['conditions']=[]
        value['cases'][2]['conditions']=[dict(kind='condition',span=value['cases'][2]['qualifications'][0]['span'],rationale='Wrong type')]
        value['cases'][4]['conditions']=deepcopy(value['cases'][4]['conditional_consequences'][0]['conditions'])
        self.assertEqual(c.inspect(value)['errors'],[])
        checked=c.assess(value)
        self.assertEqual([r['case_id'] for r in checked if r['outcome']!='PASS'],['s1','s3','s5'])

    def test_negative_controls_have_no_labels_in_model_state_even_when_duplicate(self):
        value=answer();value['cases'][0]['conditions']=[]
        spec,index=c.verification(value)
        self.assertEqual(len(spec.body['state']['items']),7);self.assertEqual(len(index),7)
        self.assertEqual(sum(v['origin']=='generated' for v in index.values()),5)
        self.assertEqual(sum(v['origin']=='negative_control' for v in index.values()),2)
        for item in spec.body['state']['items']:
            self.assertEqual(set(item),{'case_id','source','main_proposition','proposed'})
        self.assertNotIn('expected_correct',c.requests.wire(spec.body))
        # Truly identical proposals are still independent audit entries.
        value['cases'][0].update(qualifications=[],conditional_consequences=[])
        self.assertEqual(len(c.verification(value)[1]),7)

    def test_two_calls_report_pass_uncertainty_failure_and_replay_without_retry(self):
        value=answer();_,index=c.verification(value)
        for kind in ('pass','uncertain','missed_error'):
            calls=[]
            def flash(spec): calls.append('flash');return wire_response(spec,json.dumps(value))
            def verifier(spec):
                calls.append('verifier');out={}
                for key,label in index.items():
                    probability=.02 if label['origin']=='negative_control' else .98
                    if kind=='uncertain': probability=.5
                    if kind=='missed_error' and label['origin']=='negative_control': probability=.98
                    out[key]=dict(type='noul',noul=probability)
                return dict(model='jev-1.13.0',complete=True,usage=dict(input_tokens=100,output_tokens=100),output=out)
            with self.subTest(kind=kind),TemporaryDirectory() as directory:
                root=Path(directory);result=c.run_recipe(packet(),root,flash,verifier)
                self.assertEqual(calls,['flash','verifier']);self.assertFalse(result['production_admission'])
                self.assertEqual(result['status'],{'pass':'PASS','uncertain':'INCONCLUSIVE','missed_error':'FAIL(component)'}[kind])
                self.assertEqual(result['accounting']['cumulative_paid_attempts'],47)
                self.assertEqual(result['accounting']['reserved_usd'],'0.017498112')
                self.assertEqual(c.run_recipe(packet(),root,lambda s:self.fail('replay'),verifier),result)

    def test_mechanical_failures_halt_without_verifier_or_retry(self):
        for kind in ('schema','literal','inventory','length','timeout'):
            value=answer();calls=[]
            if kind=='schema': del value['cases'][0]['qualifications']
            if kind=='literal': value['cases'][0]['conditions'][0]['span']['text']='invented'
            if kind=='inventory': value['cases'].pop()
            def flash(spec):
                calls.append(spec)
                if kind=='timeout': raise OSError('synthetic timeout')
                return wire_response(spec,json.dumps(value),finish='length' if kind=='length' else 'stop')
            with self.subTest(kind=kind),TemporaryDirectory() as directory:
                result=c.run_recipe(packet(),Path(directory),flash,lambda s:self.fail('no verifier'))
                self.assertEqual(len(calls),1);self.assertEqual(result['status'],'FAIL(component)')

    def test_cli_tie_in_and_read_only_budget_authorization_guards(self):
        runner=CliRunner()
        with patch.object(c,'run',return_value=dict(status='PREPARED_NO_EXECUTION')) as run:
            result=runner.invoke(app,['analysis','learning-demo','model-fit','condition-model-run','--input','/tmp/input.json','--check-only','--json'])
            self.assertEqual(result.exit_code,0,result.output);self.assertTrue(run.call_args.kwargs['check_only'])
        with TemporaryDirectory() as directory:
            value=packet();value['budget']=dict(reserved_usd='0.017498112')
            value['input_fingerprint']=c.digest({k:v for k,v in value.items() if k!='input_fingerprint'})
            path=c.directory(Path(directory),value['input_fingerprint'])/'input.json';path.parent.mkdir(parents=True);path.write_text(json.dumps(value))
            with patch.object(c,'prepare',return_value=(value,path.parent)):
                self.assertEqual(c.run(path,Path(directory),check_only=True)['paid_calls'],0)
                self.assertFalse((path.parent/'execution').exists())
                with self.assertRaises(ValueError): c.run(path,Path(directory))
                for cap in ('0.01','0.03','NaN'):
                    with self.assertRaises(ValueError): c.run(path,Path(directory),max_usd=cap,check_only=True)
