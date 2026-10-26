from copy import deepcopy
from dataclasses import asdict
from decimal import Decimal
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from typer.testing import CliRunner

from pastor_transcript_extractor import learning_demo_feedback as f
from pastor_transcript_extractor import reading_diagnostics as d
from pastor_transcript_extractor import evidence_requests as r
from pastor_transcript_extractor import deepinfra_requests as hosted
from pastor_transcript_extractor.pastor_evidence import SourceWindow,digest
from pastor_transcript_extractor.cli import app
from test_learning_demo_correction import packet as original_packet,wire_response
from test_learning_demo import FakeProvider


def packet():
    value,spec=original_packet();output=FakeProvider()(spec)['output']
    for i,claim in enumerate(output['claims']): claim['binding_id']='b'+str(i+1)
    window=SourceWindow(**value['window'])
    checked=d.inspect(output,value['schema'],window,model=hosted.FLASH_MODEL,prompt_digest=digest(spec.body['messages']),raw_response_ref='saved')
    assert not checked['errors']
    before,candidates=f.verification(window,checked['observations'],candidates=True)
    value.update(original_output=json.dumps(output),observations=checked['observations'],before_request=asdict(before),
        candidate_map=candidates,budget=f.budget(),correction=dict(template=f.TEMPLATE),
        history=dict(prior_attempts=32,prior_local_attempts=28,prior_paid_attempts=4,
            prior_known_list_price_usage_usd='0.2298886'))
    value['input_fingerprint']=digest(value)
    return value,output


class Stub:
    def __init__(self,output,*,before=.01,after=.99):
        self.output=output;self.before=before;self.after=after;self.calls=[]
    def typesafe(self,spec):
        self.calls.append(spec);later='original_items' in spec.body['state']
        answers={}
        for key in spec.body['questions']:
            p=.99
            if not key.startswith('passage-'):
                identity,field=key.rsplit(':',1)
                item=next(i for i in spec.body['state']['items'] if i['id']==identity)
                if later:p=self.after
                elif item['binding']['binding_id']=='b2' and field in ('qualifications','polarity'):p=self.before
            answers[key]=dict(type='noul',noul=p)
        return dict(model='jev-1.13.0',complete=True,output=answers,usage=dict(input_tokens=100,output_tokens=100))
    def flash(self,spec):
        self.calls.append(spec);return wire_response(spec,json.dumps(self.output))


class FeedbackTests(unittest.TestCase):
    def test_bounded_full_loop_reports_detection_and_replays_without_calls(self):
        value,output=packet();stub=Stub(output)
        with TemporaryDirectory() as directory:
            root=Path(directory)/'execution';result=f.run_recipe(value,root,stub.typesafe,stub.flash)
            self.assertEqual(result['status'],'PASS');self.assertEqual(len(stub.calls),3)
            self.assertTrue(result['known_error_audit']['both_confidently_detected'])
            self.assertFalse(result['production_admission']);self.assertIn('review',result['semantic_outcome'])
            self.assertEqual(result['accounting']['cumulative_attempts'],35)
            self.assertEqual(Decimal(result['accounting']['reserved_usd']),Decimal('.054657024'))
            self.assertEqual(f.run_recipe(value,root,stub.typesafe,stub.flash),result)
            self.assertEqual(len(stub.calls),3)

    def test_feedback_has_field_binding_and_selected_source_refs_without_gold(self):
        value,output=packet();stub=Stub(output)
        with TemporaryDirectory() as directory:
            result=f.run_recipe(value,Path(directory)/'execution',stub.typesafe,stub.flash)
            feedback=result['before']['feedback']
            self.assertEqual({r['field'] for r in feedback},{'qualifications','polarity'})
            self.assertTrue(all(r['binding_id']=='b2' and r['source_refs'] for r in feedback))
            flash=stub.calls[1]
            self.assertEqual(flash.body['messages'][:2],value['request']['body']['messages'])
            self.assertEqual(flash.body['messages'][2]['content'],value['original_output'])
            state=stub.calls[0].body['state']
            self.assertNotIn('known_error_audit',state);self.assertNotIn('expected',json.dumps(state))
            self.assertIn('repair_scope',' '.join(stub.calls[2].body['questions']))

    def test_false_pass_or_only_uncertainty_does_not_generate_correction(self):
        for probability,status in ((.99,'FAIL(component)'),(.5,'INCONCLUSIVE')):
            with self.subTest(probability=probability),TemporaryDirectory() as directory:
                value,output=packet();stub=Stub(output,before=probability)
                result=f.run_recipe(value,Path(directory)/'execution',stub.typesafe,stub.flash)
                self.assertEqual(result['status'],status);self.assertEqual(len(stub.calls),1)

    def test_failed_or_uncertain_recheck_never_launches_second_correction(self):
        for probability,status in ((.01,'FAIL(component)'),(.5,'INCONCLUSIVE')):
            with self.subTest(probability=probability),TemporaryDirectory() as directory:
                value,output=packet();stub=Stub(output,after=probability)
                result=f.run_recipe(value,Path(directory)/'execution',stub.typesafe,stub.flash)
                self.assertEqual(result['status'],status);self.assertEqual(len(stub.calls),3)

    def test_mechanical_failure_or_dropped_claim_stops_before_recheck(self):
        for kind in ('schema','binding','dropped'):
            with self.subTest(kind=kind),TemporaryDirectory() as directory:
                value,output=packet()
                if kind=='schema': output={}
                elif kind=='binding': output['claims'][0]['adoption']['basis']='discourse_use'
                else: output['claims']=output['claims'][:1]
                stub=Stub(output);result=f.run_recipe(value,Path(directory)/'execution',stub.typesafe,stub.flash)
                self.assertEqual(result['status'],'FAIL(component)');self.assertEqual(len(stub.calls),2)
                self.assertIsNone(result['after'])

    def test_transport_error_stops_and_no_retry_on_second_invocation(self):
        value,_=packet();calls=[]
        def send(spec): calls.append(spec);raise OSError('timed out')
        with TemporaryDirectory() as directory:
            root=Path(directory)/'execution';result=f.run_recipe(value,root,send,lambda spec:self.fail('no correction'))
            self.assertEqual(result['status'],'FAIL(component)');self.assertEqual(result['accounting']['unknown_usage_attempts'],1)
            f.run_recipe(value,root,send,lambda spec:self.fail('no correction'))
            self.assertEqual(len(calls),1)

    def test_missing_or_malformed_verifier_answers_do_not_trigger_correction(self):
        value,output=packet();stub=Stub(output)
        for kind in ('missing','invalid'):
            with self.subTest(kind=kind),TemporaryDirectory() as directory:
                def send(spec):
                    response=stub.typesafe(spec)
                    if kind=='missing':response['output'].pop(next(iter(response['output'])))
                    else:response['output'][next(iter(response['output']))]['noul']=float('nan')
                    return response
                result=f.run_recipe(value,Path(directory)/'execution',send,lambda spec:self.fail('no correction'))
                self.assertEqual(result['status'],'FAIL(component)')

    def test_later_transport_failures_stop_without_extra_calls(self):
        for stage in ('flash','after'):
            with self.subTest(stage=stage),TemporaryDirectory() as directory:
                value,output=packet();stub=Stub(output)
                def typesafe(spec):
                    if stage=='after' and 'original_items' in spec.body['state']:
                        stub.calls.append(spec);raise OSError('timed out')
                    return stub.typesafe(spec)
                def flash(spec):
                    if stage=='flash':stub.calls.append(spec);raise OSError('timed out')
                    return stub.flash(spec)
                result=f.run_recipe(value,Path(directory)/'execution',typesafe,flash)
                self.assertEqual(result['status'],'FAIL(component)')
                self.assertEqual(len(stub.calls),2 if stage=='flash' else 3)
                self.assertEqual(result['accounting']['unknown_usage_attempts'],1)

    def test_passage_probability_is_not_a_generated_explanation(self):
        value,output=packet();spec=r.RequestSpec(**value['before_request']);stub=Stub(output)
        response=stub.typesafe(spec)
        for key in value['candidate_map']:response['output'][key]['noul']=.5
        judgment=f.judgments(response,spec,value['candidate_map'])
        self.assertTrue(all(not record['source_refs'] for record in judgment['feedback']))
        self.assertTrue(all('complete original source' in record['source_fallback'] for record in judgment['feedback']))

    def test_crash_after_original_verification_reuses_receipt(self):
        value,output=packet();stub=Stub(output)
        with TemporaryDirectory() as directory:
            root=Path(directory)/'execution'
            r.execute(r.RequestSpec(**value['before_request']),r.BudgetLedger(max_attempts=1),r.ReceiptStore(root/'before'),stub.typesafe)
            result=f.run_recipe(value,root,stub.typesafe,stub.flash)
            self.assertEqual(result['status'],'PASS');self.assertEqual(len(stub.calls),3)

    def test_cli_read_only_and_explicit_paid_adapter(self):
        runner=CliRunner();value,_=packet()
        with patch.object(f,'prepare',return_value=(value,Path('/tmp/frozen'))):
            result=runner.invoke(app,['analysis','learning-demo','model-fit','feedback-prepare','--from-input','/tmp/prior.json','--json'])
            self.assertEqual(result.exit_code,0,result.output);self.assertIn('"paid_calls": 0',result.stdout)
        with patch.object(f,'run',return_value=dict(status='PREPARED_NO_EXECUTION')) as run:
            result=runner.invoke(app,['analysis','learning-demo','model-fit','feedback-run','--input','/tmp/frozen/input.json','--check-only','--json'])
            self.assertEqual(result.exit_code,0,result.output);self.assertTrue(run.call_args.kwargs['check_only'])
            self.assertFalse(run.call_args.kwargs['experimental'])

    def test_frozen_preparation_and_authorization_guards_before_any_send(self):
        from pastor_transcript_extractor import learning_demo as demo
        value,output=packet();spec=r.RequestSpec(**value['request'])
        metadata=dict(deployment_version='synthetic',model=hosted.FLASH_MODEL)
        with TemporaryDirectory() as directory:
            base=Path(directory);prior=deepcopy(value);prior.pop('input_fingerprint')
            prior.update(code_identity=demo.code_identity(),published_model_metadata=metadata,source_requests=[])
            prior['history']['preserved_files']={};fingerprint=digest(prior);prior['input_fingerprint']=fingerprint
            old=f.correction.directory(base,fingerprint);store=r.ReceiptStore(old/'execution')
            response=r.execute(spec,hosted.OneRequestLedger('0.10',spec.version),store,lambda s:wire_response(s,json.dumps(output)))
            checked=d.inspect(response['output'],value['schema'],SourceWindow(**value['window']),model=hosted.FLASH_MODEL,
                prompt_digest=digest(spec.body['messages']),raw_response_ref='receipts/'+spec.fingerprint+'.json')
            store.write_immutable('results.json',dict(input_fingerprint=fingerprint,contract_fit='PASS',halt=None,
                literal_bound_claims=2,reading=checked['reading'],observations=checked['observations'],
                accounting=dict(unknown_usage_attempts=0,cumulative_attempts=32,cumulative_known_list_price_usage_usd='0.2298886')))
            (old/'input.json').write_text(json.dumps(prior))
            with patch.object(f,'PRIOR',fingerprint),patch.object(hosted,'public_model_metadata',return_value=metadata),\
                 patch('pastor_transcript_extractor.learning_demo_model_fit.verify_sources'),\
                 patch.object(hosted,'transport') as flash,patch.object(r,'typesafe_transport') as typesafe:
                frozen,out=f.prepare(old/'input.json',base)
                self.assertEqual(f.run(out/'input.json',base,check_only=True)['paid_calls'],0)
                for cap in ('0.05','0.11','NaN','bad'):
                    with self.subTest(cap=cap),self.assertRaises(ValueError):f.run(out/'input.json',base,max_usd=cap)
                with self.assertRaisesRegex(ValueError,'--experimental'):f.run(out/'input.json',base)
                with patch.dict('os.environ',{},clear=True),self.assertRaisesRegex(ValueError,'Both TYPESAFE_API_KEY'):
                    f.run(out/'input.json',base,experimental=True,approve_input=frozen['input_fingerprint'],confirm_prices=True)
                metadata['deployment_version']='changed'
                with self.assertRaisesRegex(ValueError,'changed'):f.run(out/'input.json',base,check_only=True)
                flash.assert_not_called();typesafe.assert_not_called()
