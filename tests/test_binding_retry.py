from copy import deepcopy
from dataclasses import asdict,replace
from decimal import Decimal
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from pastor_transcript_extractor import binding_retry as b
from pastor_transcript_extractor import evidence_requests as r
from pastor_transcript_extractor import deepinfra_requests as h
from pastor_transcript_extractor import learning_demo_five_windows as five
from pastor_transcript_extractor.pastor_evidence import SourceWindow
from test_learning_demo_feedback import packet,Stub
from test_learning_demo_correction import wire_response


def specimen():
    value,valid=packet();old=r.RequestSpec(**value['request'])
    spec=replace(old,version=r.DEEPINFRA_BINDING_VERSION,namespace=h.BINDING_NAMESPACE,runtime_identity=h.BINDING_POLICY)
    bad=deepcopy(valid)
    bad['claims'][0]['qualifications']=[dict(node_id='missing-q',applies_to=bad['claims'][0]['proposition']['node_id'],reading='Synthetic qualification')]
    return value,spec,valid,bad


class BindingRetryTests(unittest.TestCase):
    def test_missing_node_causes_one_model_retry_with_precise_errors(self):
        value,spec,valid,bad=specimen();calls=[];original=deepcopy(bad)
        def send(s):calls.append(s);return wire_response(s,json.dumps(bad if len(calls)==1 else valid))
        with TemporaryDirectory() as directory:
            store=r.ReceiptStore(Path(directory));result=b.read(spec,SourceWindow(**value['window']),value['schema'],store,send)
            self.assertEqual(len(calls),2);self.assertEqual(result['retries'],1);self.assertEqual(result['validation']['errors'],[])
            self.assertEqual(calls[1].body['messages'][:2],calls[0].body['messages'])
            self.assertEqual(json.loads(calls[1].body['messages'][2]['content']),bad)
            self.assertIn('$.claims[0].qualifications[0]',calls[1].body['messages'][3]['content'])
            self.assertEqual(bad,original);self.assertEqual(len(store.attempts()),2)
            self.assertTrue((store.root/'binding-validation/attempt-1.json').exists())
            b.read(spec,SourceWindow(**value['window']),value['schema'],store,send)
            self.assertEqual(len(calls),2)

    def test_success_needs_no_retry_and_exhaustion_stops(self):
        for kind in ('valid','exhausted'):
            with self.subTest(kind=kind),TemporaryDirectory() as directory:
                value,spec,valid,bad=specimen();calls=[]
                def send(s):calls.append(s);return wire_response(s,json.dumps(valid if kind=='valid' else bad))
                result=b.read(spec,SourceWindow(**value['window']),value['schema'],r.ReceiptStore(Path(directory)),send)
                self.assertEqual(len(calls),1 if kind=='valid' else 2)
                self.assertEqual(bool(result['validation']['errors']),kind=='exhausted')

    def test_json_schema_and_status_failures_do_not_retry(self):
        for output in ('not JSON','{}','{"status":"proposed","claims":[]}'):
            with self.subTest(output=output),TemporaryDirectory() as directory:
                value,spec,_,_=specimen();calls=[]
                def send(s):calls.append(s);return wire_response(s,output)
                result=b.read(spec,SourceWindow(**value['window']),value['schema'],r.ReceiptStore(Path(directory)),send)
                self.assertEqual(len(calls),1);self.assertTrue(result['validation']['errors'])

    def test_transport_length_reasoning_errors_do_not_retry(self):
        for kind in ('network','length','reasoning'):
            with self.subTest(kind=kind),TemporaryDirectory() as directory:
                value,spec,valid,_=specimen();calls=[]
                def send(s):
                    calls.append(s)
                    if kind=='network':raise OSError('timed out')
                    return wire_response(s,json.dumps(valid),finish='length' if kind=='length' else 'stop',reasoning=int(kind=='reasoning'))
                with self.assertRaises((ValueError,OSError)):
                    b.read(spec,SourceWindow(**value['window']),value['schema'],r.ReceiptStore(Path(directory)),send)
                self.assertEqual(len(calls),1)

    def test_binding_retry_cannot_drop_claims_to_pass(self):
        value,spec,valid,bad=specimen();valid['claims']=valid['claims'][1:];calls=[]
        def send(s):calls.append(s);return wire_response(s,json.dumps(bad if len(calls)==1 else valid))
        with TemporaryDirectory() as directory:
            result=b.read(spec,SourceWindow(**value['window']),value['schema'],r.ReceiptStore(Path(directory)),send)
            self.assertTrue(any(e['code']=='identity' for e in result['validation']['errors']))
            self.assertEqual(result['validation']['observations'],[])

    def test_review_retry_preserves_task_and_latest_answer_without_superseded_answer(self):
        value,spec,valid,bad=specimen()
        spec=replace(spec,body={**spec.body,'messages':spec.body['messages']+[
            dict(role='assistant',content=json.dumps(valid)),dict(role='user',content='Synthetic review request')]})
        calls=[]
        def send(s):calls.append(s);return wire_response(s,json.dumps(bad if len(calls)==1 else valid))
        with TemporaryDirectory() as directory:
            b.read(spec,SourceWindow(**value['window']),value['schema'],r.ReceiptStore(Path(directory)),send)
            self.assertEqual(len(calls[1].body['messages']),4)
            self.assertEqual(json.loads(calls[1].body['messages'][2]['content']),bad)
            self.assertIn('Synthetic review request',calls[1].body['messages'][3]['content'])
            old=replace(spec,version=r.DEEPINFRA_CORRECTION_VERSION,namespace=h.CORRECTION_NAMESPACE,runtime_identity=h.CORRECTION_POLICY)
            with self.assertRaisesRegex(ValueError,'newly frozen'):
                b.read(old,SourceWindow(**value['window']),value['schema'],r.ReceiptStore(Path(directory)/'old'),send)
            with self.assertRaises(ValueError):h.BindingRetryLedger().check([{},{}],'source_reading')
            with self.assertRaises(ValueError):h.BindingRetryLedger('0.09').check([],'source_reading')

    def test_full_application_loop_retries_both_stages_then_checks_typesafe(self):
        value,spec,valid,bad=specimen();calls=[];ts=[]
        def flash(s):calls.append(s);return wire_response(s,json.dumps(bad if len(calls)%2 else valid))
        def typesafe(s):
            ts.append(s)
            return dict(model='jev-1.13.0',complete=True,usage=dict(input_tokens=100,output_tokens=100),
                output={k:dict(type='noul',noul=.5 if len(ts)==1 else .99) for k in s.body['questions']})
        packet_value=dict(input_fingerprint='synthetic',schema=value['schema'],policy=dict(binding_retries=1),
            history=dict(prior_attempts=0,prior_local_attempts=0,prior_paid_attempts=0,prior_known_list_price_usage_usd='0'),
            limitation='synthetic only',cases=[dict(case_id=value['window']['id'],window=value['window'],request=asdict(spec))])
        with TemporaryDirectory() as directory:
            result=five.run_recipe(packet_value,Path(directory)/'execution',flash,typesafe)
            self.assertEqual(len(calls),4);self.assertEqual(len(ts),2)
            self.assertEqual(result['cases'][0]['binding_retries'],2)
            self.assertEqual(result['accounting']['attempts'],6)
            self.assertEqual(Decimal(result['accounting']['reserved_usd']),Decimal('.202113024'))
            self.assertEqual(result['status'],'INCONCLUSIVE');self.assertFalse(result['production_admission'])
            self.assertEqual(len(calls[2].body['messages']),4)  # semantic review starts with clean source prefix

    def test_exhausted_initial_binding_retry_skips_typesafe_explicitly(self):
        value,spec,valid,bad=specimen();messages=[]
        with TemporaryDirectory() as directory:
            result=b.run_case(dict(input_fingerprint='synthetic',schema=value['schema']),
                dict(case_id='synthetic',window=value['window'],request=asdict(spec)),Path(directory),
                lambda s:wire_response(s,json.dumps(bad)),lambda s:self.fail('no semantic check'),progress=messages.append)
            self.assertEqual(result['status'],'FAIL(component)');self.assertEqual(result['initial_binding_retries'],1)
            self.assertTrue(any('skipped' in message for message in messages))

    def test_all_five_can_retry_both_stages_within_frozen_new_budget(self):
        value,spec,valid,bad=specimen();calls=[];ts=[]
        def flash(s):calls.append(s);return wire_response(s,json.dumps(bad if len(calls)%2 else valid))
        def typesafe(s):
            ts.append(s)
            return dict(model='jev-1.13.0',complete=True,usage=dict(input_tokens=100,output_tokens=100),
                output={k:dict(type='noul',noul=.5 if len(ts)%2 else .99) for k in s.body['questions']})
        cases=[]
        for i in range(5):
            window={**deepcopy(value['window']),'id':'synthetic-'+str(i)}
            cases.append(dict(case_id=window['id'],window=window,request=asdict(replace(spec,source_identity=dict(case=i)))))
        packet_value=dict(input_fingerprint='synthetic-five',cases=cases,schema=value['schema'],policy=dict(binding_retries=1),
            history=dict(prior_attempts=35,prior_local_attempts=28,prior_paid_attempts=7,prior_known_list_price_usage_usd='0'),limitation='synthetic only')
        with TemporaryDirectory() as directory:
            result=five.run_recipe(packet_value,Path(directory)/'execution',flash,typesafe)
            self.assertEqual(len(calls),20);self.assertEqual(len(ts),10)
            self.assertEqual(result['accounting']['attempts'],30)
            self.assertEqual(result['accounting']['cumulative_attempts'],65)
            self.assertEqual(Decimal(result['accounting']['reserved_usd']),Decimal('1.010565120'))

    def test_retry_fit_failure_stops_without_extra_send_or_truncation(self):
        value,spec,valid,bad=specimen();calls=[]
        def send(s):calls.append(s);return wire_response(s,json.dumps(bad))
        with TemporaryDirectory() as directory,patch.object(b,'TEMPLATE','x'*60000):
            with self.assertRaisesRegex(ValueError,'no truncation'):
                b.read(spec,SourceWindow(**value['window']),value['schema'],r.ReceiptStore(Path(directory)),send)
            self.assertEqual(len(calls),1)

    def test_saved_binding_failure_reuses_original_and_bills_only_its_retry(self):
        value,spec,valid,bad=specimen();calls=[]
        old=replace(spec,version=r.DEEPINFRA_CORRECTION_VERSION,namespace=h.CORRECTION_NAMESPACE,runtime_identity=h.CORRECTION_POLICY)
        with TemporaryDirectory() as directory:
            root=Path(directory);old_store=r.ReceiptStore(root/'old')
            response=r.execute(old,h.OneRequestLedger('0.10',old.version),old_store,lambda s:wire_response(s,json.dumps(bad)))
            checked=b.diagnostics.inspect(response['output'],value['schema'],SourceWindow(**value['window']),model=h.FLASH_MODEL,
                prompt_digest=b.digest(old.body['messages']),raw_response_ref='initial/receipts/'+old.fingerprint+'.json')
            seed=five.load_seed(old_store.root,checked);new_store=r.ReceiptStore(root/'new')
            def send(s):calls.append(s);return wire_response(s,json.dumps(valid))
            result=b.read(spec,SourceWindow(**value['window']),value['schema'],new_store,send,seed=seed)
            self.assertEqual(len(calls),1);self.assertEqual(result['retries'],1)
            self.assertTrue(result['attempts'][0]['reused']);self.assertEqual(len(new_store.attempts()),1)

    def test_compatible_completed_cases_replay_all_stages_without_new_billing(self):
        from test_learning_demo_five_windows import packet as five_packet
        value,valid=five_packet();stub=Stub(valid,before=.5)
        with TemporaryDirectory() as directory:
            root=Path(directory);old_root=root/'old';five.run_recipe(value,old_root,stub.flash,stub.typesafe)
            new=deepcopy(value);new['input_fingerprint']='new-synthetic';new['policy']=dict(binding_retries=1)
            for case in new['cases']:
                old_case=old_root/case['case_id'];saved=json.loads((old_case/'results.json').read_text())
                old_spec=r.RequestSpec(**case['request'])
                case['request']=asdict(replace(old_spec,version=r.DEEPINFRA_BINDING_VERSION,namespace=h.BINDING_NAMESPACE,runtime_identity=h.BINDING_POLICY))
                case['seeds']=dict(initial=five.load_seed(old_case/'initial',saved['initial']),
                    before=five.load_seed(old_case/'before'),review=five.load_seed(old_case/'revision/review',saved['revision']['mechanical']),
                    after=five.load_seed(old_case/'revision/after'))
            result=five.run_recipe(new,root/'new',lambda s:self.fail('no new Flash'),lambda s:self.fail('no new verifier'))
            self.assertEqual(result['accounting']['attempts'],0)
            self.assertEqual(result['completed_windows'],5);self.assertEqual(result['status'],'INCONCLUSIVE')

    def test_imported_receipts_must_match_pinned_model_and_usage_contract(self):
        value,spec,valid,bad=specimen()
        with TemporaryDirectory() as directory:
            root=Path(directory);store=r.ReceiptStore(root/'old')
            r.execute(spec,h.BindingRetryLedger(),store,lambda s:wire_response(s,json.dumps(valid)))
            seed=five.load_seed(store.root)
            seed['receipt']['response']['model']='wrong-model'
            seed['receipt']['response_digest']=b.digest(seed['receipt']['response'])
            with self.assertRaisesRegex(ValueError,'substituted'):
                b.import_receipt(r.ReceiptStore(root/'new'),seed)
