from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from pastor_transcript_extractor.evidence_requests import (
    BudgetLedger, PHASES, ReceiptStore, RequestSpec, execute, reservation,
)
from pastor_transcript_extractor.learning_demo_contracts import generation_request, verification_request, judgments


class Encoding:
    def encode(self,text,**kwargs): return text.encode()


class RequestTests(unittest.TestCase):
    def setUp(self):
        self.request=generation_request('source_reading',{'target_text':'synthetic'}, {'target':'hash'})

    def response(self,spec):
        return dict(model=spec.body['model'],usage=dict(input_tokens=10,output_tokens=10),
                    complete=True,output={'status':'none','claims':[]})

    def test_cache_no_retry_and_namespace_identity(self):
        with TemporaryDirectory() as directory:
            store=ReceiptStore(Path(directory)); calls=[]
            def send(spec): calls.append(spec); return self.response(spec)
            one=execute(self.request,BudgetLedger(),store,send,encoding=Encoding())
            self.assertEqual(one,execute(self.request,BudgetLedger(),store,send,encoding=Encoding()))
            self.assertEqual(len(calls),1)
            self.assertNotEqual(self.request.fingerprint,replace(self.request,namespace='other').fingerprint)

    def test_lost_attempt_stops_even_different_request(self):
        with TemporaryDirectory() as directory:
            store=ReceiptStore(Path(directory)); calls=[]
            def lost(spec): calls.append(1); raise TimeoutError('lost')
            with self.assertRaises(TimeoutError): execute(self.request,BudgetLedger(),store,lost,encoding=Encoding())
            for request in [self.request,replace(self.request,source_identity={'new':'source'})]:
                with self.assertRaisesRegex(ValueError,'lacks receipt'):
                    execute(request,BudgetLedger(),store,lost,encoding=Encoding())
            self.assertEqual(len(calls),1)

    def test_budget_phase_total_and_subceilings(self):
        attempts=[dict(phase=phase,reserved_usd=str(reservation(phase))) for phase in PHASES
                  for _ in range(PHASES[phase][2])]
        from decimal import Decimal
        self.assertEqual(sum(Decimal(r['reserved_usd']) for r in attempts),Decimal('1.657552896'))
        with self.assertRaises(ValueError): BudgetLedger().check(attempts,'source_reading')
        with self.assertRaises(ValueError): BudgetLedger(max_usd='.01').check([],'source_reading')
        with self.assertRaises(ValueError): BudgetLedger(source_max_usd='.01').check([],'source_reading')
        with self.assertRaises(ValueError): BudgetLedger(max_attempts=67).check([],'source_reading')

    def test_overflow_and_model_fallback_rejected_before_send(self):
        request=generation_request('source_reading',{'text':'x'*50000},{})
        with self.assertRaisesRegex(ValueError,'fit failure'): request.preflight(Encoding())
        bad=replace(self.request,body={**self.request.body,'model':'other'})
        with self.assertRaisesRegex(ValueError,'Pinned model'): bad.preflight(Encoding())
        verify=verification_request('source_verification',{'text':'x'*33000},[{'id':'a'}],{},source=True)
        with self.assertRaisesRegex(ValueError,'per-question'): verify.preflight()

    def test_incomplete_receipt_halts_without_fallback(self):
        with TemporaryDirectory() as directory:
            store=ReceiptStore(Path(directory)); count=[]
            def send(spec):
                count.append(1); return {**self.response(spec),'complete':False}
            for _ in range(2):
                with self.assertRaises(ValueError): execute(self.request,BudgetLedger(),store,send,encoding=Encoding())
            self.assertEqual(len(count),1)

    def test_field_checks_strict_and_no_probability_product(self):
        request=verification_request('source_verification',{},[{'id':'a'}],{},source=True)
        response=dict(output={k:dict(type='noul',noul=.9) for k in request.body['questions']})
        self.assertTrue(all(v['resolved'] for v in judgments(response,request)['a'].values()))
        del response['output']['a:voice']
        with self.assertRaises(ValueError): judgments(response,request)
