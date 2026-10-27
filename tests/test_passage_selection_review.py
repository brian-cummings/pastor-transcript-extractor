from copy import deepcopy
from dataclasses import asdict
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from typer.testing import CliRunner
from pastor_transcript_extractor import passage_selection_review as r
from pastor_transcript_extractor.cli import app
from test_source_passages import packet,selected


def specimen():
    value=packet();before=selected(value['state']);spec=r.requests.RequestSpec(**value['request'])
    verify=r.selection.verification(value['state'],before)
    scores=[dict(item_id=i['item_id'],field=f,probability_correct=.5) for i in value['state']['items'] for f in r.selection.CRITERIA]
    revised=r.review_request(spec,json.dumps(before),scores,[dict(item_id=i['item_id'],evidence=i['evidence']) for i in verify.body['state']['items']])
    value.update(request=asdict(revised),before=before,before_scores=scores,limitation='Synthetic unit test')
    return value


class PassageReviewTests(unittest.TestCase):
    def test_unchanged_verifier_request_reuses_receipt_but_changed_selection_rechecks(self):
        for changed in (False,True):
            value=specimen();spec=r.selection.verification(value['state'],value['before'])
            def judgment(spec):
                return dict(model='jev-1.13.0',complete=True,usage=dict(input_tokens=100,output_tokens=100),output={key:dict(type='noul',noul=.5) for key in spec.body['questions']})
            with self.subTest(changed=changed),TemporaryDirectory() as folder:
                baseline=r.requests.ReceiptStore(Path(folder)/'baseline')
                r.requests.execute(spec,r.requests.BudgetLedger(max_attempts=1,max_usd='.003'),baseline,judgment)
                ref=baseline.root/'receipts'/f'{spec.fingerprint}.json'
                value['verifier_seed']=dict(path=str(ref),receipt=json.loads(ref.read_text()))
                calls=[]
                def flash(spec):
                    calls.append('flash');out=deepcopy(value['before'])
                    if changed: out['selections'][0]['proposition_range']['end_unit']=out['selections'][0]['proposition_range']['start_unit']
                    return dict(model=r.hosted.FLASH_MODEL,complete=True,usage=dict(input_tokens=100,output_tokens=100),output=json.dumps(out))
                def verifier(spec): calls.append('typesafe');return judgment(spec)
                result=r.run_recipe(value,Path(folder)/'review',flash,verifier)
                self.assertEqual(result['verifier_reused'],not changed)
                self.assertEqual(calls,['flash','typesafe'] if changed else ['flash'])
                self.assertEqual(result['accounting']['paid_attempts'],2 if changed else 1)

    def test_request_reuses_source_and_feedback_without_expected_corrections(self):
        value=specimen();spec=r.requests.RequestSpec(**value['request']);spec.preflight()
        self.assertEqual([m['role'] for m in spec.body['messages']],['system','user','assistant','user'])
        self.assertEqual(json.loads(spec.body['messages'][1]['content']),value['state'])
        self.assertEqual(json.loads(spec.body['messages'][2]['content']),value['before'])
        self.assertIn('Low confidence is not proof of error',spec.body['messages'][3]['content'])
        self.assertNotIn('expected_correction',spec.body['messages'][3]['content'])

    def test_single_semantic_review_recheck_reuse_and_preservation_comparison(self):
        for mode in ('same','abstain','mechanical_retry'):
            value=specimen();calls=[]
            def flash(spec):
                calls.append('flash');out=selected(value['state'],'no_adequate_passage' if mode=='abstain' else 'selected')
                if mode=='mechanical_retry' and calls.count('flash')==1: out['selections'][0]['proposition_range']['start_unit']='invalid'
                return dict(model=r.hosted.FLASH_MODEL,complete=True,usage=dict(input_tokens=100,output_tokens=100),output=json.dumps(out))
            def verifier(spec):
                calls.append('typesafe')
                return dict(model='jev-1.13.0',complete=True,usage=dict(input_tokens=100,output_tokens=100),output={k:dict(type='noul',noul=.7) for k in spec.body['questions']})
            with self.subTest(mode=mode),TemporaryDirectory() as folder:
                result=r.run_recipe(value,Path(folder),flash,verifier)
                self.assertFalse(result['production_admission']);self.assertLessEqual(len(calls),3)
                self.assertEqual(result['status'],'INCONCLUSIVE')
                self.assertEqual(r.run_recipe(value,Path(folder),lambda s:self.fail('no repeated calls'),lambda s:self.fail('no repeated calls')),result)
                self.assertEqual(len(result['range_changes']),2)
                self.assertTrue(all(x['changed']==(mode=='abstain') for x in result['range_changes']))
                if mode!='abstain': self.assertTrue(all(x['previous_probability_correct']==.5 for x in result['field_comparisons']))
                else: self.assertEqual(calls,['flash'])

    def test_approval_budget_cli_and_frozen_change_guards(self):
        with patch.object(r,'run',return_value=dict(status='PREPARED_NO_EXECUTION')) as run:
            out=CliRunner().invoke(app,['analysis','learning-demo','model-fit','passage-review-run','--input','/tmp/input.json','--check-only','--json'])
            self.assertEqual(out.exit_code,0,out.output);self.assertTrue(run.call_args.kwargs['check_only'])
        with TemporaryDirectory() as folder:
            value=json.loads(json.dumps(specimen()));value['budget']=dict(reserved_usd='.032243712')
            value['input_fingerprint']=r.digest({k:v for k,v in value.items() if k!='input_fingerprint'})
            path=r.directory(Path(folder),value['input_fingerprint'])/'input.json';path.parent.mkdir(parents=True);path.write_text(json.dumps(value))
            with patch.object(r,'prepare',return_value=(value,path.parent)):
                self.assertEqual(r.run(path,Path(folder),check_only=True)['paid_calls'],0)
                self.assertFalse((path.parent/'execution').exists())
                with self.assertRaises(ValueError): r.run(path,Path(folder))
                for cap in ('NaN','.01','.05'):
                    with self.assertRaises(ValueError): r.run(path,Path(folder),max_usd=cap,check_only=True)
            changed=deepcopy(value);changed['version']='different'
            with patch.object(r,'prepare',return_value=(changed,path.parent)),self.assertRaises(ValueError): r.run(path,Path(folder),check_only=True)
