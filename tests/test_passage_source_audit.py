from copy import deepcopy
from dataclasses import asdict
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from typer.testing import CliRunner
from pastor_transcript_extractor import passage_source_audit as a
from pastor_transcript_extractor.cli import app
from test_source_passages import packet,selected


def specimen(folder):
    value=packet();before=selected(value['state']);value['before']=before
    value['before_scores']=[dict(item_id=i['item_id'],field=f,probability_correct=.5,outcome='INCONCLUSIVE') for i in value['state']['items'] for f in a.c.CRITERIA]
    verify=a.c.verification(value['state'],before);store=a.requests.ReceiptStore(Path(folder)/'seed')
    a.requests.execute(verify,a.requests.BudgetLedger(max_attempts=1,max_usd='.003'),store,judgment)
    ref=store.root/'receipts'/f'{verify.fingerprint}.json';value['verifier_seed']=dict(path=str(ref),receipt=json.loads(ref.read_text()))
    value['request']=asdict(a.audit_request(value));value['history']['prior_accounting'].update(cumulative_attempts=97,cumulative_paid_attempts=69)
    return value


def judgment(spec):
    return dict(model='jev-1.13.0',complete=True,usage=dict(input_tokens=100,output_tokens=100),output={key:dict(type='noul',noul=.7) for key in spec.body['questions']})


def output(value,action='retain'):
    return dict(audits=[dict(item_id=row['item_id'],finding='no_demonstrated_defect' if action=='retain' else 'unresolved',
        evidence_units=[row['proposition_range']['start_unit']],explanation='The selected source supports retaining the fixed candidate; no defect is demonstrated.' if action=='retain' else 'Consequential meaning remains unresolved in this synthetic source.',action=action,
        proposition_range=deepcopy(row['proposition_range']) if action=='retain' else dict(start_unit='',end_unit=''),adoption_ranges=[]) for row in value['before']['selections']])


class PassageAuditTests(unittest.TestCase):
    def test_retain_is_valid_without_forcing_correction_and_citations_bind(self):
        with TemporaryDirectory() as folder:
            value=specimen(folder);spec=a.requests.RequestSpec(**value['request']);spec.preflight()
            self.assertNotIn('expected_correction',spec.body['messages'][1]['content'])
            good=a.inspect(output(value),value);self.assertFalse(good['errors']);self.assertEqual(good['selections'],value['before'])
            reordered=a.inspect(dict(audits=list(reversed(output(value)['audits']))),value)
            self.assertEqual(reordered['selections'],value['before']);self.assertTrue(a.verification(value,reordered)[1])
            for row in good['resolved']: self.assertTrue(row['citations'][0]['span']['text'])
            for kind in ('uncited','unknown_id','duplicate','retained_change','invented_field','inconsistent_action'):
                bad=output(value);row=bad['audits'][0]
                if kind=='uncited': row['evidence_units']=[]
                if kind=='unknown_id': row['evidence_units']=['foreign']
                if kind=='duplicate': bad['audits'].append(deepcopy(row))
                if kind=='retained_change': row['proposition_range']['end_unit']=row['proposition_range']['start_unit']
                if kind=='invented_field': row['expected_correction']='leaked'
                if kind=='inconsistent_action': row['action']='replace'
                with self.subTest(kind=kind): self.assertTrue(a.inspect(bad,value)['errors'])

    def test_expansion_preserves_existing_text_and_replacement_or_abstention_remain_distinct(self):
        with TemporaryDirectory() as folder:
            value=specimen(folder);bad=output(value);row=bad['audits'][0];row.update(finding='missing_continuation',action='expand')
            row['proposition_range']['end_unit']=row['proposition_range']['start_unit']
            self.assertTrue(a.inspect(bad,value)['errors'])
            short=deepcopy(value);short['before']['selections'][0]['proposition_range']['end_unit']='u0000'
            expanded=output(short);expanded['audits'][0].update(finding='missing_continuation',action='expand',proposition_range=deepcopy(value['before']['selections'][0]['proposition_range']))
            self.assertFalse(a.inspect(expanded,short)['errors'])
            self.assertFalse(a.inspect(output(value,'abstain'),value)['errors'])

    def test_identical_original_assessments_reused_and_new_diagnoses_always_checked(self):
        with TemporaryDirectory() as folder:
            value=specimen(folder);checked=a.inspect(output(value),value);verify,reused=a.verification(value,checked)
            self.assertTrue(reused);self.assertEqual(len(verify.body['questions']),4)
            self.assertTrue(all(k.split(':')[1] in a.DIAGNOSIS_CHECKS for k in verify.body['questions']))
            changed=output(value);changed['audits'][0].update(finding='candidate_mismatch',action='replace')
            changed['audits'][0]['proposition_range']['end_unit']=changed['audits'][0]['proposition_range']['start_unit']
            verify,reused=a.verification(value,a.inspect(changed,value));self.assertFalse(reused)
            self.assertEqual(len(verify.body['questions']),10)

    def test_bounded_retry_and_replay_no_semantic_loop(self):
        for mode in ('retain','abstain','retry','failed_twice','timeout'):
            with self.subTest(mode=mode),TemporaryDirectory() as folder:
                value=specimen(folder);calls=[]
                def flash(spec):
                    calls.append('flash')
                    if mode=='timeout': raise OSError('synthetic timeout')
                    out=output(value,'abstain' if mode=='abstain' else 'retain')
                    if mode=='failed_twice' or (mode=='retry' and calls.count('flash')==1): out['audits'][0]['evidence_units']=['foreign']
                    return dict(model=a.hosted.FLASH_MODEL,complete=True,usage=dict(input_tokens=100,output_tokens=100),output=json.dumps(out))
                def verify(spec): calls.append('typesafe');return judgment(spec)
                root=Path(folder)/'run';result=a.run_recipe(value,root,flash,verify)
                self.assertLessEqual(len(calls),3);self.assertFalse(result['production_admission'])
                self.assertEqual(result['status'],'FAIL(component)' if mode in ('failed_twice','timeout') else 'INCONCLUSIVE')
                self.assertEqual(a.run_recipe(value,root,lambda s:self.fail('replay'),lambda s:self.fail('replay')),result)
                if mode=='retry': self.assertEqual(calls,['flash','flash','typesafe'])
                if mode=='failed_twice': self.assertEqual(calls,['flash','flash'])
                if mode=='retain':
                    self.assertTrue(result['original_verifier_reused']);self.assertEqual(len(result['diagnosis_scores']),4);self.assertEqual(len(result['passage_scores']),6)

    def test_cli_approval_budget_and_frozen_change_guards(self):
        with patch.object(a,'run',return_value=dict(status='PREPARED_NO_EXECUTION')) as run:
            out=CliRunner().invoke(app,['analysis','learning-demo','model-fit','passage-audit-run','--input','/tmp/input.json','--check-only','--json'])
            self.assertEqual(out.exit_code,0,out.output);self.assertTrue(run.call_args.kwargs['check_only'])
        with TemporaryDirectory() as folder:
            value=json.loads(json.dumps(specimen(folder)));value['budget']=dict(reserved_usd='.032243712')
            value['input_fingerprint']=a.digest({k:v for k,v in value.items() if k!='input_fingerprint'})
            path=a.directory(Path(folder),value['input_fingerprint'])/'input.json';path.parent.mkdir(parents=True);path.write_text(json.dumps(value))
            with patch.object(a,'prepare',return_value=(value,path.parent)):
                self.assertEqual(a.run(path,Path(folder),check_only=True)['paid_calls'],0);self.assertFalse((path.parent/'execution').exists())
                with self.assertRaises(ValueError): a.run(path,Path(folder))
                for cap in ('NaN','.01','.05'):
                    with self.assertRaises(ValueError): a.run(path,Path(folder),max_usd=cap,check_only=True)
            changed=deepcopy(value);changed['version']='foreign'
            with patch.object(a,'prepare',return_value=(changed,path.parent)),self.assertRaises(ValueError): a.run(path,Path(folder),check_only=True)
