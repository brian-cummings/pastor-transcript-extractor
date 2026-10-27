from copy import deepcopy
from dataclasses import asdict
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from typer.testing import CliRunner
from pastor_transcript_extractor import role_decisions_check as r
from pastor_transcript_extractor.cli import app
from test_passage_voice_context import specimen, output


def fixture():
    packet=specimen();checked=r.context.inspect(output(),packet)
    packet['candidate_index']=[dict(item_id='i0',case_id='generic',binding_id='c1')]
    text=''.join(u['text'] for u in packet['state']['sources']['w0']['units'])
    old_spec,index=r.choices.make_request([dict(case_id='generic',source=text,reading=dict(claims=[dict(binding_id='c1',proposition=dict(reading='The gate is open.',span=dict(source_field='target_text',text='The gate is open.')),voice=dict(kind='quoted_or_reported',occurrence='actual'),adoption=dict(status='adopted'))]))])
    answers={}
    for key,audit in index.items():
        field=audit['field'];options=r.choices.CRITERIA[field];value=(audit['expected'] or audit['previous'])[field]
        answers[key]=dict(type='choice',choice=value,probabilities={k:.97 if k==value else .03/(len(options)-1) for k in options},confidence=.95 if field=='occurrence' else .5)
    response=dict(model='jev-1.13.0',complete=True,usage=dict(input_tokens=100,output_tokens=100),output=answers)
    baseline=r.choices.decisions(response,old_spec,index)
    spec,index,reused=r.make_request(packet,checked,baseline,old_spec)
    return dict(input_fingerprint='synthetic',request=asdict(spec),audit_index=index,reused_decisions=reused,history=packet['history'],coverage=dict(source_profiles=[])),packet,checked,baseline,old_spec


class RoleDecisionsTests(unittest.TestCase):
    def test_compatible_choices_reused_others_get_literal_roles_no_old_answers(self):
        value,packet,checked,baseline,old=fixture();spec=r.requests.RequestSpec(**value['request'])
        self.assertEqual(len(spec.body['questions']),2);self.assertEqual(len(value['reused_decisions']),1)
        self.assertEqual(value['reused_decisions'][0]['decision']['field'],'occurrence')
        self.assertEqual(spec.body['state']['items'][0]['proposition']['binding_evidence'],checked['evidence'][0]['package']['binding_evidence'])
        for key in ('previous','expected','rationale','probability_correct','confidence'):
            self.assertNotIn('"'+key+'":',r.requests.wire(spec.body))
        for kind in ('reading','source','duplicate','missing'):
            changed=deepcopy(packet);rows=deepcopy(baseline)
            if kind=='reading': changed['state']['items'][0]['candidate_reading']='Different claim'
            if kind=='source': changed['state']['sources']['w0']['units'][0]['text']='Different source'
            if kind=='duplicate': rows.append(deepcopy(next(x for x in rows if x['origin']=='saved_claim')))
            if kind=='missing': rows=[x for x in rows if x['field']!='voice']
            with self.subTest(kind=kind),self.assertRaises(ValueError): r.make_request(changed,checked,rows,old)

    def test_one_request_unknowns_invalid_answers_timeout_and_replay(self):
        for mode in ('resolved','uncertain','invalid','timeout'):
            value,*_=fixture();sent=[]
            def transport(spec):
                sent.append(spec)
                if mode=='timeout': raise OSError('stub timeout')
                answers={}
                for key,audit in value['audit_index'].items():
                    options=r.choices.CRITERIA[audit['field']];choice=next(iter(options))
                    answers[key]=dict(type='choice',choice=choice,probabilities={k:.97 if k==choice else .03/(len(options)-1) for k in options},confidence=.4 if mode=='uncertain' else .95)
                if mode=='invalid': next(iter(answers.values()))['probabilities']={}
                return dict(model='jev-1.13.0',complete=True,usage=dict(input_tokens=100,output_tokens=100),output=answers)
            with self.subTest(mode=mode),TemporaryDirectory() as folder:
                result=r.run_recipe(value,Path(folder),transport)
                self.assertEqual(len(sent),1);self.assertFalse(result['production_admission'])
                self.assertEqual(result['status'],'FAIL(component)' if mode in ('invalid','timeout') else 'INCONCLUSIVE')
                self.assertEqual(result['accounting']['paid_attempts'],1)
                self.assertEqual(result['accounting']['cumulative_paid_attempts'],72)
                if mode=='uncertain': self.assertEqual(result['still_unresolved'],2)
                self.assertEqual(result,r.run_recipe(value,Path(folder),lambda s:self.fail('replayed call')))

    def test_frozen_cli_budget_authorization_and_no_writes_check(self):
        with patch.object(r,'run',return_value=dict(status='PREPARED_NO_EXECUTION')) as run:
            out=CliRunner().invoke(app,['analysis','learning-demo','model-fit','role-decisions-run','--input','/tmp/input.json','--check-only','--json'])
            self.assertEqual(out.exit_code,0,out.output);self.assertTrue(run.call_args.kwargs['check_only'])
        with TemporaryDirectory() as folder:
            packet,*_=fixture();packet['budget']=dict(reserved_usd='.002752512')
            packet['input_fingerprint']=r.digest({k:v for k,v in packet.items() if k!='input_fingerprint'})
            path=r.directory(Path(folder),packet['input_fingerprint'])/'input.json';path.parent.mkdir(parents=True);path.write_text(json.dumps(packet))
            with patch.object(r,'prepare',return_value=(packet,path.parent)):
                self.assertEqual(r.run(path,Path(folder),check_only=True)['paid_calls'],0)
                self.assertFalse((path.parent/'execution').exists())
                with self.assertRaises(ValueError): r.run(path,Path(folder))
                for cap in ('.001','.004','.10','NaN'):
                    with self.assertRaises(ValueError): r.run(path,Path(folder),max_usd=cap,check_only=True)
            changed=deepcopy(packet);changed['version']='foreign'
            with patch.object(r,'prepare',return_value=(changed,path.parent)),self.assertRaises(ValueError): r.run(path,Path(folder),check_only=True)
