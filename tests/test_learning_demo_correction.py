from copy import deepcopy
from dataclasses import asdict,replace
from decimal import Decimal
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from typer.testing import CliRunner

from pastor_transcript_extractor import learning_demo_correction as c
from pastor_transcript_extractor import deepinfra_requests as p
from pastor_transcript_extractor import evidence_requests as r
from pastor_transcript_extractor import reading_diagnostics as d
from pastor_transcript_extractor.cli import app
from pastor_transcript_extractor.pastor_evidence import digest
from test_deepinfra_fit import specimen
from test_learning_demo import FakeProvider


def packet():
    value,old=specimen()
    spec=replace(old,body={**old.body,'model':p.FLASH_MODEL,'reasoning_effort':'none','max_tokens':65536},
        namespace=p.CORRECTION_NAMESPACE,version=r.DEEPINFRA_CORRECTION_VERSION,runtime_identity=p.CORRECTION_POLICY)
    value.update(request=asdict(spec),correction=dict(template=d.CORRECTION),
        history=dict(prior_attempts=31,prior_local_attempts=28,prior_paid_attempts=3,
            prior_source_attempts=27,prior_synthetic_attempts=4,prior_known_list_price_usage_usd='0.2279878'))
    value['input_fingerprint']=digest(value)
    return value,spec


def wire_response(spec,content,finish='stop',reasoning=0):
    return r.WireResponse(200,json.dumps(dict(model=p.FLASH_MODEL,
        choices=[dict(finish_reason=finish,message=dict(content=content))],
        usage=dict(prompt_tokens=100,completion_tokens=200,completion_tokens_details=dict(reasoning_tokens=reasoning)))))


class CorrectionTests(unittest.TestCase):
    def test_budget_reserves_both_and_rejects_third_or_foreign_policy(self):
        value,spec=packet();ledger=p.CorrectionLedger()
        self.assertEqual(2*p.reserved_usd(spec.version),Decimal('.098304'))
        ledger.check([],'source_reading')
        for cap in ('0.09','0.101','NaN','0','-1','bad'):
            with self.subTest(cap=cap),self.assertRaises(ValueError): p.CorrectionLedger(cap).check([],'source_reading')
        with self.assertRaises(ValueError):ledger.check([{},{}],'source_reading')
        with self.assertRaises(ValueError):ledger.check([{}],'source_reading')
        with self.assertRaises(ValueError):p.CorrectionLedger(request_version=r.DEEPINFRA_DIRECT_VERSION).check([],'source_reading')

    def test_success_needs_no_retry_and_result_cache_never_resends(self):
        value,spec=packet();output=FakeProvider()(spec)['output'];calls=[]
        def send(s): calls.append(s);return wire_response(s,json.dumps(output))
        with TemporaryDirectory() as directory:
            store=r.ReceiptStore(Path(directory)/'execution')
            result=c.run_recipe(value,store,send)
            self.assertEqual(result['contract_fit'],'PASS');self.assertEqual(result['status'],'INCONCLUSIVE')
            self.assertEqual(result['literal_bound_claims'],2);self.assertFalse(result['production_admission'])
            self.assertEqual(result['accounting']['paid_attempts'],1)
            self.assertEqual(c.run_recipe(value,store,send),result);self.assertEqual(len(calls),1)

    def test_correction_keeps_prefix_all_failures_and_both_outputs(self):
        value,spec=packet();valid=FakeProvider()(spec)['output'];invalid=deepcopy(valid)
        invalid['claims'][0]['adoption']['basis']='discourse_use'
        invalid['claims'][0]['epistemic_status']['evidence']=[]
        calls=[]
        def send(s):
            calls.append(s);return wire_response(s,json.dumps(invalid if len(calls)==1 else valid))
        with TemporaryDirectory() as directory:
            store=r.ReceiptStore(Path(directory)/'execution');result=c.run_recipe(value,store,send)
            self.assertEqual(result['contract_fit'],'PASS');self.assertEqual(len(calls),2)
            self.assertEqual(calls[1].body['messages'][:2],calls[0].body['messages'])
            self.assertEqual(json.loads(calls[1].body['messages'][2]['content']),invalid)
            feedback=calls[1].body['messages'][3]['content']
            self.assertIn('$.claims[0].adoption',feedback);self.assertIn('epistemic_status.evidence',feedback)
            self.assertEqual(result['accounting']['reserved_usd'],'0.098304')
            self.assertEqual(result['accounting']['cumulative_attempts'],33)
            self.assertEqual(len(list((store.root/'receipts').glob('*.json'))),2)
            self.assertTrue((store.root/'validation/attempt-1.json').exists())

    def test_json_or_schema_failure_can_correct_once_but_never_third(self):
        for invalid in ('not json','{}'):
            with self.subTest(invalid=invalid),TemporaryDirectory() as directory:
                value,_=packet();calls=[]
                def send(s): calls.append(s);return wire_response(s,invalid)
                result=c.run_recipe(value,r.ReceiptStore(Path(directory)/'execution'),send)
                self.assertEqual(len(calls),2);self.assertEqual(result['contract_fit'],'FAIL(component)')
                self.assertEqual(result['literal_bound_claims'],0)

    def test_length_reasoning_network_and_uncertain_spend_do_not_retry(self):
        for kind in ('length','reasoning','network'):
            with self.subTest(kind=kind),TemporaryDirectory() as directory:
                value,_=packet();calls=[]
                def send(s):
                    calls.append(s)
                    if kind=='network': raise OSError('timed out')
                    return wire_response(s,'{}',finish='length' if kind=='length' else 'stop',reasoning=int(kind=='reasoning'))
                store=r.ReceiptStore(Path(directory)/'execution');result=c.run_recipe(value,store,send)
                self.assertEqual(len(calls),1);self.assertEqual(result['contract_fit'],'FAIL(component)')
                self.assertIsNotNone(result['halt'])
                if kind=='network':self.assertEqual(result['accounting']['unknown_usage_attempts'],1)

    def test_crash_after_first_response_uses_exact_cache_before_correction(self):
        value,spec=packet();calls=[]
        with TemporaryDirectory() as directory:
            store=r.ReceiptStore(Path(directory)/'execution')
            r.execute(spec,p.CorrectionLedger(),store,lambda s:wire_response(s,'{}'))
            def send(s):calls.append(s);return wire_response(s,'{"status":"none","claims":[]}')
            result=c.run_recipe(value,store,send)
            self.assertEqual(len(calls),1);self.assertEqual(len(calls[0].body['messages']),4)
            self.assertEqual(result['accounting']['paid_attempts'],2)
            self.assertEqual(result['contract_fit'],'INCONCLUSIVE')

    def test_feedback_overflow_stops_without_truncation(self):
        value,_=packet();calls=[]
        with TemporaryDirectory() as directory:
            def send(s):calls.append(s);return wire_response(s,'x'*60000)
            result=c.run_recipe(value,r.ReceiptStore(Path(directory)/'execution'),send)
            self.assertEqual(len(calls),1);self.assertIn('no truncation',result['halt'])

    def test_old_request_policies_cannot_use_four_messages(self):
        value,spec=packet();correction=c.corrective_request(value,'{}',[dict(path='$',code='missing',message='missing fields')])
        correction.preflight()
        old=replace(correction,namespace=p.DIRECT_NAMESPACE,version=r.DEEPINFRA_DIRECT_VERSION,runtime_identity=p.DIRECT_POLICY)
        with self.assertRaises(ValueError):old.preflight()

    def test_cli_tie_in_is_explicit_and_read_only_by_default(self):
        runner=CliRunner();value,spec=packet();value['budget']={}
        with patch.object(c,'prepare',return_value=(value,Path('/tmp/synthetic'))) as prepare:
            result=runner.invoke(app,['analysis','learning-demo','model-fit','corrective-prepare','--from-input','/tmp/prior.json','--json'])
            self.assertEqual(result.exit_code,0,result.output);self.assertIn('"paid_calls": 0',result.stdout)
        with patch.object(c,'run',return_value=dict(status='PREPARED_NO_EXECUTION')) as run:
            result=runner.invoke(app,['analysis','learning-demo','model-fit','corrective-run','--input','/tmp/input.json','--check-only','--json'])
            self.assertEqual(result.exit_code,0,result.output);self.assertTrue(run.call_args.kwargs['check_only'])
            self.assertFalse(run.call_args.kwargs['experimental']);self.assertEqual(run.call_args.kwargs['max_usd'],'0.10')

    def test_preparation_freezes_history_and_changes_block_execution(self):
        from pastor_transcript_extractor import learning_demo as demo
        metadata=dict(model=p.FLASH_MODEL,native_output_schema_maximum=1000000,context=1048576,
            capabilities=['can-disable-reasoning','structured-output'],input_cents_per_token='0.00002',
            output_cents_per_token='0.00006',deployment_version='synthetic')
        with TemporaryDirectory() as base:
            base=Path(base)
            prior,_=packet();prior.pop('input_fingerprint');prior.update(code_identity=demo.code_identity(),source_requests=[])
            prior['history']['preserved_files']={};fingerprint=digest(prior);prior['input_fingerprint']=fingerprint
            old_dir=c.direct.directory(base,fingerprint);old_store=r.ReceiptStore(old_dir/'execution')
            old_store.write_immutable('attempts/synthetic.json',{})
            old_store.write_immutable('results.json',dict(input_fingerprint=fingerprint,halt=None,literal_bound_claims=0,
                failures=[{},{}],accounting=dict(paid_attempts=1,unknown_usage_attempts=0,cumulative_attempts=31,
                cumulative_known_list_price_usage_usd='0.2279878')))
            (old_dir/'input.json').write_text(json.dumps(prior))
            with patch.object(c,'PRIOR',fingerprint),patch.object(p,'public_model_metadata',return_value=metadata),\
                 patch('pastor_transcript_extractor.learning_demo_model_fit.verify_sources'),patch.object(p,'transport') as send:
                frozen,out=c.prepare(old_dir/'input.json',base)
                self.assertEqual(frozen['budget']['reserved_usd'],'0.098304')
                self.assertEqual(c.run(out/'input.json',base,check_only=True)['paid_calls'],0)
                with self.assertRaisesRegex(ValueError,'--experimental'):
                    c.run(out/'input.json',base)
                metadata['deployment_version']='changed'
                with self.assertRaisesRegex(ValueError,'changed after freeze'):
                    c.run(out/'input.json',base,check_only=True)
                send.assert_not_called()
