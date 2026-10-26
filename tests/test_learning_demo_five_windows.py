from copy import deepcopy
from dataclasses import asdict,replace
from decimal import Decimal
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from typer.testing import CliRunner

from pastor_transcript_extractor import learning_demo_five_windows as f
from pastor_transcript_extractor import evidence_requests as r
from pastor_transcript_extractor.pastor_evidence import digest,SourceWindow
from pastor_transcript_extractor.cli import app
from test_learning_demo_feedback import packet as baseline,Stub
from test_learning_demo_uncertainty import packet as review_packet
from test_learning_demo_correction import wire_response


def packet():
    base,output=baseline();cases=[]
    for i in range(5):
        window=deepcopy(base['window']);window['id']=f'synthetic-case-{i}'
        window['stratum']='independent_control' if i>=3 else 'detector_selected'
        spec=r.RequestSpec(**base['request']);body=deepcopy(spec.body)
        body['messages'][1]['content']=r.wire(f.demo._source_state(SourceWindow(**window)))
        spec=replace(spec,body=body,source_identity=dict(case=i))
        cases.append(dict(case_id=window['id'],window=window,request=asdict(spec)))
    value=dict(cases=cases,schema=base['schema'],limitation='Synthetic only',
        history=dict(prior_attempts=35,prior_local_attempts=28,prior_paid_attempts=7,prior_known_list_price_usage_usd='0.233560938'),
        budget=dict(reserved_usd='0.519045120',max_usd='0.52'),selection=dict(windows=5))
    value['input_fingerprint']=digest(value)
    return value,output


class FiveWindowTests(unittest.TestCase):
    def test_full_frozen_typesafe_loop_all_five_and_total_budget(self):
        value,output=packet();stub=Stub(output,before=.5)
        with TemporaryDirectory() as directory:
            root=Path(directory)/'execution';result=f.run_recipe(value,root,stub.flash,stub.typesafe)
            self.assertEqual(len(stub.calls),20);self.assertEqual(result['completed_windows'],5)
            self.assertEqual(result['accounting']['attempts'],20)
            self.assertEqual(Decimal(result['accounting']['reserved_usd']),Decimal('.51904512'))
            self.assertEqual(result['accounting']['cumulative_attempts'],55)
            self.assertEqual(result['accounting']['cumulative_paid_attempts'],27)
            self.assertTrue(all(c['review_attempted'] for c in result['cases']))
            self.assertEqual(result['status'],'INCONCLUSIVE');self.assertFalse(result['production_admission'])
            self.assertIsNone(result['accuracy_counts']['errors_corrected'])
            self.assertTrue((root/'source-review-packet.json').exists())
            self.assertEqual(f.run_recipe(value,root,stub.flash,stub.typesafe),result);self.assertEqual(len(stub.calls),20)

    def test_initial_pass_has_no_review_and_no_added_questions(self):
        value,output=packet();stub=Stub(output,before=.99)
        with TemporaryDirectory() as directory:
            result=f.run_recipe(value,Path(directory)/'execution',stub.flash,stub.typesafe)
            self.assertEqual(len(stub.calls),10);self.assertFalse(any(c['review_attempted'] for c in result['cases']))
            for spec in stub.calls[1::2]:
                self.assertEqual(len(spec.body['questions']),8)  # two claims, two fields, one synthetic block

    def test_complete_initial_binding_failure_continues_fixed_cases_without_repair(self):
        value,output=packet();stub=Stub(output,before=.99);calls=[]
        bad=deepcopy(output);bad['claims'][0]['adoption']['basis']='discourse_use'
        def flash(spec):
            calls.append(spec);return wire_response(spec,json.dumps(bad if len(calls)==1 else output))
        with TemporaryDirectory() as directory:
            result=f.run_recipe(value,Path(directory)/'execution',flash,stub.typesafe)
            self.assertEqual(len(calls),5);self.assertEqual(len(stub.calls),4)
            self.assertEqual(result['completed_windows'],5);self.assertEqual(result['status'],'FAIL(component)')
            self.assertTrue(result['cases'][0]['initial_errors']);self.assertFalse(result['cases'][0]['review_attempted'])

    def test_failed_review_does_not_get_another_review_or_recheck(self):
        value,output=packet();stub=Stub(output,before=.5);calls=[]
        bad=deepcopy(output);bad['claims'][0]['adoption']['basis']='discourse_use'
        def flash(spec):
            calls.append(spec);return wire_response(spec,json.dumps(bad if len(spec.body['messages'])==4 else output))
        with TemporaryDirectory() as directory:
            result=f.run_recipe(value,Path(directory)/'execution',flash,stub.typesafe)
            self.assertEqual(len(calls),10);self.assertEqual(len(stub.calls),5)
            self.assertEqual(result['accounting']['attempts'],15)
            self.assertTrue(all(c['review_errors'] for c in result['cases']))

    def test_transport_stop_blocks_remaining_windows_and_preserves_uncertain_spend(self):
        value,_=packet();calls=[]
        def send(spec):calls.append(spec);raise OSError('timed out')
        with TemporaryDirectory() as directory:
            root=Path(directory)/'execution';result=f.run_recipe(value,root,send,send)
            self.assertEqual(len(calls),1);self.assertEqual(result['processed_windows'],1)
            self.assertEqual(result['completed_windows'],0);self.assertEqual(result['accounting']['unknown_usage_attempts'],1)
            f.run_recipe(value,root,send,send);self.assertEqual(len(calls),1)

    def test_empty_output_abstains_without_verification_or_review(self):
        value,_=packet();calls=[]
        def send(spec):calls.append(spec);return wire_response(spec,'{"status":"none","claims":[]}')
        with TemporaryDirectory() as directory:
            result=f.run_recipe(value,Path(directory)/'execution',send,lambda spec:self.fail('no verifier'))
            self.assertEqual(len(calls),5);self.assertEqual(result['status'],'INCONCLUSIVE')

    def test_review_prefix_uses_exact_initial_output_and_no_expected_corrections(self):
        value,output=packet();stub=Stub(output,before=.5)
        with TemporaryDirectory() as directory:
            f.run_recipe(value,Path(directory)/'execution',stub.flash,stub.typesafe)
            first,_,review,_=stub.calls[:4]
            self.assertEqual(review.body['messages'][:2],first.body['messages'])
            self.assertEqual(json.loads(review.body['messages'][2]['content']),output)
            self.assertIn(f.review.TEMPLATE,review.body['messages'][3]['content'])
            self.assertNotIn('known_error',review.body['messages'][3]['content'])

    def test_crash_after_initial_response_replays_receipt_without_new_call(self):
        value,output=packet();stub=Stub(output,before=.99)
        with TemporaryDirectory() as directory:
            root=Path(directory)/'execution';case=value['cases'][0];spec=r.RequestSpec(**case['request'])
            r.execute(spec,f.hosted.OneRequestLedger('0.06',spec.version),r.ReceiptStore(root/case['case_id']/'initial'),stub.flash)
            result=f.run_recipe(value,root,stub.flash,stub.typesafe)
            self.assertEqual(len(stub.calls),10);self.assertEqual(result['accounting']['attempts'],10)

    def test_budget_credentials_and_freeze_before_calls(self):
        value,_=packet()
        with TemporaryDirectory() as directory:
            base=Path(directory);value.pop('input_fingerprint');value['history']['prior_input']=str(base/'prior/input.json')
            value['input_fingerprint']=digest(value);value=json.loads(json.dumps(value));out=f.directory(base,value['input_fingerprint']);out.mkdir(parents=True)
            path=out/'input.json';path.write_text(json.dumps(value))
            with patch.object(f,'prepare',return_value=(value,out)),patch.object(f.hosted,'transport') as send:
                self.assertEqual(f.run(path,base,check_only=True)['paid_calls'],0)
                for cap in ('0.5','0.53','NaN','bad'):
                    with self.subTest(cap=cap),self.assertRaises(ValueError):f.run(path,base,max_usd=cap)
                with self.assertRaisesRegex(ValueError,'--experimental'):f.run(path,base)
                with patch.dict('os.environ',{},clear=True),self.assertRaisesRegex(ValueError,'Both TYPESAFE_API_KEY'):
                    f.run(path,base,experimental=True,approve_input=value['input_fingerprint'],confirm_prices=True)
                self.assertFalse((out/'execution').exists());send.assert_not_called()
            changed=deepcopy(value);changed['limitation']='changed'
            with patch.object(f,'prepare',return_value=(changed,out)),self.assertRaisesRegex(ValueError,'changed after freeze'):
                f.run(path,base,check_only=True)

    def test_cli_has_explicit_full_loop_preparation_and_check_only(self):
        runner=CliRunner();value,_=packet()
        with patch.object(f,'prepare',return_value=(value,Path('/tmp/frozen'))):
            result=runner.invoke(app,['analysis','learning-demo','model-fit','remaining-five-prepare','--from-input','/tmp/prior.json','--json'])
            self.assertEqual(result.exit_code,0,result.output);self.assertIn('"paid_calls": 0',result.stdout)
        with patch.object(f,'run',return_value=dict(status='PREPARED_NO_EXECUTION')) as run:
            result=runner.invoke(app,['analysis','learning-demo','model-fit','remaining-five-run','--input','/tmp/input.json','--check-only','--json'])
            self.assertEqual(result.exit_code,0,result.output);self.assertTrue(run.call_args.kwargs['check_only'])
            self.assertFalse(run.call_args.kwargs['experimental'])

    def test_preparation_preserves_selection_prompt_and_checks_constituents(self):
        prior,output=review_packet();bad=deepcopy(output);bad['claims'][0]['adoption']['basis']='discourse_use'
        with TemporaryDirectory() as directory:
            base=Path(directory);source_cases=[];source_requests=[];windows=[]
            for index in range(6):
                window=deepcopy(prior['window']);window['id']='frozen-'+str(index)
                windows.append(window);source_cases.append(window['id'])
                state=f.demo._source_state(SourceWindow(**window))
                state=dict(texts=state['texts'],block_mapping=state['block_mapping'],
                    source_identity={k:v for k,v in window.items() if k!='blocks'},target_scope='declared_blocks_only')
                source_requests.append(dict(case_id=window['id'],request=asdict(replace(r.RequestSpec(**prior['request']),
                    body={**prior['request']['body'],'messages':[
                        prior['request']['body']['messages'][0],dict(role='user',content=r.wire(state))]},source_identity=dict(index=index)))))
            ancestor=dict(windows=windows,source_requests=source_requests,selection=dict(cases=source_cases))
            six_fp=digest(ancestor);ancestor['input_fingerprint']=six_fp
            six_path=f.fit.directory(base,six_fp)/'input.json';six_path.parent.mkdir(parents=True);six_path.write_text(json.dumps(ancestor))
            prior.pop('input_fingerprint');prior['history']['prior_input']=str(six_path)
            prior['history']['preserved_files']={str(six_path):f.demo.file_hash(six_path)}
            prior['published_model_metadata']={};fp=digest(prior);prior['input_fingerprint']=fp
            old=f.review.directory(base,fp);store=r.ReceiptStore(old/'execution/review');spec=r.RequestSpec(**prior['request'])
            response=r.execute(spec,f.hosted.OneRequestLedger('0.06',spec.version),store,lambda s:wire_response(s,json.dumps(bad)))
            checked=f.diagnostics.inspect(response['output'],prior['schema'],SourceWindow(**prior['window']),model=f.hosted.FLASH_MODEL,
                prompt_digest=digest(spec.body['messages']),raw_response_ref='review/receipts/'+spec.fingerprint+'.json')
            r.ReceiptStore(old/'execution').write_immutable('results.json',dict(input_fingerprint=fp,status='FAIL(component)',halt=None,
                mechanical=checked,after=None,accounting=dict(attempts=1,unknown_usage_attempts=0,cumulative_attempts=35,
                    cumulative_known_list_price_usage_usd='0.233560938')))
            (old/'input.json').write_text(json.dumps(prior));prior=json.loads(json.dumps(prior))
            with patch.object(f,'PRIOR',fp),patch.object(f,'SIX',six_fp),patch.object(f,'DEVELOPMENT',source_cases[0]),\
                 patch.object(f.review,'prepare',return_value=(prior,old)),patch.object(f.fit,'verify_sources'),\
                 patch.object(f.fit,'select_cases',return_value=source_cases),patch.object(f.hosted,'transport') as send:
                frozen,out=f.prepare(old/'input.json',base,binding_retries=False)
                self.assertEqual([c['case_id'] for c in frozen['cases']],source_cases[1:])
                self.assertEqual(Decimal(frozen['budget']['reserved_usd']),Decimal('.51904512'))
                self.assertTrue(all(c['request']['body']['messages'][0]==prior['request']['body']['messages'][0] for c in frozen['cases']))
                self.assertEqual(f.run(out/'input.json',base,check_only=True)['paid_calls'],0)
                send.assert_not_called()
                cached=base/'receipts/compatible.json';cached.parent.mkdir()
                producer=deepcopy(frozen['cases'][0]['request'])
                producer['runtime_identity']['maximum_usd']='0.05'
                cached.write_text(json.dumps(dict(request=producer,halt=None)))
                self.assertEqual(f.compatible_receipts(r.RequestSpec(**frozen['cases'][0]['request']),[cached]),[str(cached)])
                self.assertEqual(f.compatible_receipts(r.RequestSpec(**frozen['cases'][1]['request']),[cached]),[])
                prior['history']['preserved_files'][str(cached)]=f.demo.file_hash(cached)
                (old/'input.json').write_text(json.dumps(prior))
                with self.assertRaisesRegex(ValueError,'Prior input changed'):
                    f.prepare(old/'input.json',base,binding_retries=False)
