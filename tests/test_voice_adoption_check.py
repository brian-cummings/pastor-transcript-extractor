from copy import deepcopy
from dataclasses import asdict
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from typer.testing import CliRunner
from pastor_transcript_extractor import voice_adoption_check as c
from pastor_transcript_extractor.cli import app
from test_attachment_trial import packet as attachment_packet


def packet():
    base,valid=attachment_packet()
    cases=[dict(case_id=row['case_id'],source=c.demo._source_state(c.SourceWindow(**row['window']))['texts']['target_text'],reading=deepcopy(valid)) for row in base['cases']]
    spec,index=c.make_request(cases)
    return dict(input_fingerprint='synthetic',request=asdict(spec),audit_index=index,
        history=dict(prior_accounting=dict(cumulative_attempts=90,cumulative_local_attempts=28,cumulative_paid_attempts=62,cumulative_known_list_price_usage_usd='.354077160')))


def response(spec,index,mode='pass'):
    answers={}
    for key,audit in index.items():
        options=c.CRITERIA[audit['field']];choice=audit['expected'][audit['field']] if audit['expected'] else next(iter(options))
        if mode=='wrong' and audit['expected']: choice=next(k for k in options if k!=choice)
        answers[key]=dict(type='choice',choice=choice,probabilities={k:.97 if k==choice else .03/(len(options)-1) for k in options},confidence=.5 if mode=='uncertain' else .99)
    return dict(model='jev-1.13.0',complete=True,usage=dict(input_tokens=100,output_tokens=100),output=answers)


class VoiceAdoptionTests(unittest.TestCase):
    def test_request_retains_source_and_strips_old_judgments(self):
        value=packet();spec=c.requests.RequestSpec(**value['request'])
        self.assertEqual(len(spec.body['questions']),36);self.assertEqual(len(spec.body['state']['items']),12)
        for item in spec.body['state']['items']:
            self.assertEqual(set(item),{'source_id','proposition'})
            self.assertEqual(set(item['proposition']),{'reading','span'})
            self.assertIn(item['proposition']['span']['text'],spec.body['state']['sources'][item['source_id']])
        for key in ('previous','expected','rationale','probability_correct','polarity','origin'):
            self.assertNotIn('"'+key+'":',c.requests.wire(spec.body))
        for field,options in c.CRITERIA.items():
            actual={a['expected'][field] for a in value['audit_index'].values() if a['expected'] and a['field']==field}
            self.assertEqual(actual,set(options))
        spec.preflight()

    def test_validation_and_item_mapping(self):
        value=packet();spec=c.requests.RequestSpec(**value['request']);good=response(spec,value['audit_index'])
        self.assertEqual(len(c.decisions(good,spec,value['audit_index'])),36)
        for kind in ('missing','sum','option','confidence','model','bool','object'):
            bad=deepcopy(good);key=next(iter(bad['output']));answer=bad['output'][key]
            if kind=='missing': bad['output'].pop(key)
            if kind=='sum': answer['probabilities'][answer['choice']]=.2
            if kind=='option': answer['choice']='invented'
            if kind=='confidence': answer['confidence']=float('nan')
            if kind=='model': bad['model']='other-model'
            if kind=='bool': answer['probabilities'][answer['choice']]=True
            if kind=='object': bad['output'][key]='malformed'
            with self.subTest(kind=kind),self.assertRaises(ValueError): c.decisions(bad,spec,value['audit_index'])
        bad=deepcopy(value['audit_index']);key=next(iter(bad));bad[key]['item_index']=11-bad[key]['item_index']
        with self.assertRaises(ValueError): c.decisions(good,spec,bad)

    def test_one_request_replay_controls_unknowns_and_accounting(self):
        for mode in ('pass','wrong','uncertain','timeout'):
            value=packet();sent=[]
            def transport(spec):
                sent.append(spec)
                if mode=='timeout': raise OSError('synthetic timeout')
                return response(spec,value['audit_index'],mode)
            with self.subTest(mode=mode),TemporaryDirectory() as directory:
                root=Path(directory);result=c.run_recipe(value,root,transport)
                self.assertEqual(len(sent),1);self.assertFalse(result['production_admission'])
                self.assertEqual(result['control_fit'],{'pass':'PASS','wrong':'FAIL(component)','uncertain':'INCONCLUSIVE','timeout':'FAIL(component)'}[mode])
                self.assertEqual(result['accounting']['cumulative_paid_attempts'],63)
                self.assertEqual(c.run_recipe(value,root,lambda s:self.fail('no replay call')),result)
                if mode=='pass': self.assertEqual(result['status'],'INCONCLUSIVE')
                if mode=='uncertain': self.assertTrue(all(r['effective_value'] in ('unresolved','undetermined') for r in result['decisions']))

    def test_cli_and_frozen_budget_authorization_guards(self):
        with patch.object(c,'run',return_value=dict(status='PREPARED_NO_EXECUTION')) as run:
            result=CliRunner().invoke(app,['analysis','learning-demo','model-fit','voice-adoption-run','--input','/tmp/input.json','--check-only','--json'])
            self.assertEqual(result.exit_code,0,result.output);self.assertTrue(run.call_args.kwargs['check_only'])
        with TemporaryDirectory() as directory:
            value=packet();value['budget']=dict(reserved_usd='.002752512')
            value['input_fingerprint']=c.digest({k:v for k,v in value.items() if k!='input_fingerprint'})
            path=c.directory(Path(directory),value['input_fingerprint'])/'input.json';path.parent.mkdir(parents=True);path.write_text(json.dumps(value))
            with patch.object(c,'prepare',return_value=(value,path.parent)):
                self.assertEqual(c.run(path,Path(directory),check_only=True)['paid_calls'],0)
                self.assertFalse((path.parent/'execution').exists())
                with self.assertRaises(ValueError): c.run(path,Path(directory))
                for cap in ('0.001','0.004','NaN'):
                    with self.assertRaises(ValueError): c.run(path,Path(directory),max_usd=cap,check_only=True)
                changed=deepcopy(value);changed['version']='changed'
                with patch.object(c,'prepare',return_value=(changed,path.parent)),self.assertRaises(ValueError): c.run(path,Path(directory),check_only=True)
