from copy import deepcopy
from dataclasses import asdict
from decimal import Decimal
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from typer.testing import CliRunner

from pastor_transcript_extractor import learning_demo_uncertainty as u
from pastor_transcript_extractor import learning_demo_field_check as fields
from pastor_transcript_extractor import learning_demo_correction as correction
from pastor_transcript_extractor import evidence_requests as r
from pastor_transcript_extractor.pastor_evidence import SourceWindow,digest
from pastor_transcript_extractor.cli import app
from test_learning_demo_feedback import packet as baseline,Stub
from test_learning_demo_correction import wire_response


def packet():
    prior,output=baseline();window=SourceWindow(**prior['window'])
    spec,candidates=fields.verification(window,prior['observations']);stub=Stub(output,before=.5)
    response=stub.typesafe(spec);judgment=u.feedback.judgments(response,spec,candidates)
    scores=u.review_scores(spec,judgment)
    request=correction.corrective_request(dict(request=prior['request'],correction=dict(template=u.TEMPLATE)),prior['original_output'],scores)
    value=dict(request=asdict(request),window=prior['window'],schema=prior['schema'],scores=scores,
        original_output=prior['original_output'],original_observations=prior['observations'],
        limitation='Synthetic diagnostic only',history=dict(prior_attempts=34,prior_local_attempts=28,
            prior_paid_attempts=6,prior_known_list_price_usage_usd='0.231240538'),
        budget=dict(reserved_usd='0.051904512',max_usd='0.06'))
    value['input_fingerprint']=digest(value)
    return value,output


class UncertaintyTests(unittest.TestCase):
    def test_one_review_then_unchanged_verification_and_no_automatic_accuracy_claim(self):
        value,output=packet();stub=Stub(output)
        with TemporaryDirectory() as directory:
            result=u.run_recipe(value,Path(directory)/'execution',stub.flash,stub.typesafe)
            self.assertEqual(len(stub.calls),2);self.assertEqual(result['status'],'INCONCLUSIVE')
            self.assertEqual(result['accounting']['reserved_usd'],'0.051904512')
            self.assertEqual(result['accounting']['cumulative_attempts'],36)
            self.assertEqual(result['accounting']['cumulative_paid_attempts'],8)
            self.assertFalse(result['production_admission'])
            self.assertTrue(all(not d['changed_fields'] for d in result['changed_fields']))
            expected,_=fields.verification(SourceWindow(**value['window']),result['mechanical']['observations'])
            self.assertEqual(asdict(stub.calls[1]),asdict(expected))
            self.assertEqual(u.run_recipe(value,Path(directory)/'execution',stub.flash,stub.typesafe),result)
            self.assertEqual(len(stub.calls),2)

    def test_uncertainty_is_not_a_diagnosis_and_input_includes_only_machine_feedback(self):
        value,_=packet();spec=r.RequestSpec(**value['request'])
        content=spec.body['messages'][3]['content'];self.assertTrue(content.startswith(u.TEMPLATE))
        scores=json.loads(content[len(u.TEMPLATE):]);self.assertEqual(scores,value['scores'])
        self.assertTrue(any(s['review_requested'] for s in scores));self.assertTrue(any(not s['review_requested'] for s in scores))
        self.assertEqual(len(scores),4)
        self.assertTrue(all(set(s)=={'binding_id','field','probability_correct','review_requested','criterion'} for s in scores))
        self.assertEqual(spec.body['messages'][2]['content'],value['original_output'])
        self.assertIn('not evidence that a field is wrong',u.TEMPLATE)
        self.assertNotIn('known_error',content)

    def test_report_changes_even_to_previously_confident_content(self):
        value,output=packet();output['claims'][0]['polarity']['rationale']='A changed synthetic rationale.'
        stub=Stub(output)
        with TemporaryDirectory() as directory:
            result=u.run_recipe(value,Path(directory)/'execution',stub.flash,stub.typesafe)
            self.assertEqual(result['changed_fields'][0]['changed_fields'],['polarity'])
            self.assertIn('preservation of correct content',result['semantic_outcome'])

    def test_bad_or_missing_claims_stop_without_verifier_or_second_review(self):
        for kind in ('schema','binding','identity'):
            with self.subTest(kind=kind),TemporaryDirectory() as directory:
                value,output=packet()
                if kind=='schema':output={}
                elif kind=='binding':output['claims'][0]['adoption']['basis']='discourse_use'
                else:output['claims']=output['claims'][:1]
                stub=Stub(output)
                result=u.run_recipe(value,Path(directory)/'execution',stub.flash,stub.typesafe)
                self.assertEqual(result['status'],'FAIL(component)');self.assertEqual(len(stub.calls),1)

    def test_transport_length_or_later_error_never_retries(self):
        for kind in ('network','length','after'):
            with self.subTest(kind=kind),TemporaryDirectory() as directory:
                value,output=packet();stub=Stub(output);calls=[]
                def flash(spec):
                    calls.append(spec)
                    if kind=='network':raise OSError('timed out')
                    return wire_response(spec,json.dumps(output),finish='length' if kind=='length' else 'stop')
                def typesafe(spec):calls.append(spec);raise OSError('timed out')
                root=Path(directory)/'execution';result=u.run_recipe(value,root,flash,typesafe)
                self.assertEqual(result['status'],'FAIL(component)');self.assertEqual(len(calls),2 if kind=='after' else 1)
                u.run_recipe(value,root,flash,typesafe);self.assertEqual(len(calls),2 if kind=='after' else 1)

    def test_crash_recovery_reuses_completed_flash_receipt(self):
        value,output=packet();stub=Stub(output)
        with TemporaryDirectory() as directory:
            root=Path(directory)/'execution';spec=r.RequestSpec(**value['request'])
            r.execute(spec,u.hosted.OneRequestLedger('0.06',spec.version),r.ReceiptStore(root/'review'),stub.flash)
            result=u.run_recipe(value,root,stub.flash,stub.typesafe)
            self.assertEqual(len(stub.calls),2);self.assertEqual(result['accounting']['attempts'],2)

    def test_scores_policy_is_not_binding_name_specific(self):
        prior,output=baseline();observations=deepcopy(prior['observations']);observations.reverse()
        for i,o in enumerate(observations):o['id']='new-'+str(i);o['binding']['binding_id']='other-'+str(i)
        spec,candidates=fields.verification(SourceWindow(**prior['window']),observations)
        response=dict(output={k:dict(type='noul',noul=.5) for k in spec.body['questions']})
        judgment=u.feedback.judgments(response,spec,candidates);scores=u.review_scores(spec,judgment)
        self.assertEqual({s['binding_id'] for s in scores},{'other-0','other-1'})
        self.assertTrue(all(s['review_requested'] for s in scores));self.assertEqual(len(scores),4)

    def test_budget_freeze_and_credential_guards(self):
        value,_=packet()
        with TemporaryDirectory() as directory:
            base=Path(directory);value.pop('input_fingerprint');value['history']['prior_input']=str(base/'prior/input.json')
            value['input_fingerprint']=digest(value);value=json.loads(json.dumps(value))
            out=u.directory(base,value['input_fingerprint']);out.mkdir(parents=True)
            path=out/'input.json';path.write_text(json.dumps(value))
            with patch.object(u,'prepare',return_value=(value,out)),patch.object(u.hosted,'transport') as send:
                self.assertEqual(u.run(path,base,check_only=True)['paid_calls'],0)
                for cap in ('0.05','0.061','NaN','bad'):
                    with self.subTest(cap=cap),self.assertRaises(ValueError):u.run(path,base,max_usd=cap)
                with self.assertRaisesRegex(ValueError,'--experimental'):u.run(path,base)
                with patch.dict('os.environ',{},clear=True),self.assertRaisesRegex(ValueError,'Both TYPESAFE_API_KEY'):
                    u.run(path,base,experimental=True,approve_input=value['input_fingerprint'],confirm_prices=True)
                self.assertFalse((out/'execution').exists());send.assert_not_called()
            changed=deepcopy(value);changed['limitation']='changed'
            with patch.object(u,'prepare',return_value=(changed,out)),self.assertRaisesRegex(ValueError,'changed after freeze'):
                u.run(path,base,check_only=True)

    def test_cli_has_explicit_preparation_and_check_only(self):
        runner=CliRunner();value,_=packet()
        with patch.object(u,'prepare',return_value=(value,Path('/tmp/frozen'))):
            result=runner.invoke(app,['analysis','learning-demo','model-fit','uncertainty-prepare','--from-input','/tmp/prior.json','--json'])
            self.assertEqual(result.exit_code,0,result.output);self.assertIn('"paid_calls": 0',result.stdout)
        with patch.object(u,'run',return_value=dict(status='PREPARED_NO_EXECUTION')) as run:
            result=runner.invoke(app,['analysis','learning-demo','model-fit','uncertainty-run','--input','/tmp/input.json','--check-only','--json'])
            self.assertEqual(result.exit_code,0,result.output);self.assertTrue(run.call_args.kwargs['check_only'])
            self.assertFalse(run.call_args.kwargs['experimental'])
