from copy import deepcopy
from dataclasses import asdict
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from pastor_transcript_extractor import reader_claim_admission as admission
from pastor_transcript_extractor import response_growth_binding as producer
from test_profile_section import reading


class ReaderClaimAdmissionTests(unittest.TestCase):
    def case(self):
        window, _, _, checked = reading()
        original = producer.dimension_verification(window, checked['observations'])
        oid = original.body['state']['items'][0]['id']
        return original, oid

    def batch(self, correctness=.91, evaluation=False):
        original, oid = self.case()
        spec = producer.action_grounding_request(original,[oid],
            evaluation_candidates={oid:'Authored control only'} if evaluation else None)
        batch = dict(id='one',request=asdict(spec),fingerprint=spec.fingerprint,
            preflight=spec.preflight(),reserved_usd=str(admission.support.requests.request_reservation(spec)),
            maximum_attempts=1,evaluation_only=evaluation,
            historical_row=dict(checks=dict(requested_response=dict(probability=correctness,resolved=correctness>=.90))),
            expected=dict(observation_id=oid, action=True,eligible=correctness>=.90))
        return spec,batch

    def receipt(self,spec,action=.96,correctness=.1):
        answers={k:dict(type='noul',noul=action if k.endswith(':source_grounded_action') else correctness)
                 for k in spec.body['questions']}
        return dict(request=asdict(spec),halt=None,
            response=dict(output=answers))

    def test_original_unchanged_and_no_correctness_repurchase(self):
        original,oid=self.case();before=deepcopy(original)
        spec=producer.action_grounding_request(original,[oid])
        self.assertEqual(original,before)
        self.assertEqual(original.body['state'],spec.body['state'])
        self.assertEqual(original.body['model'],spec.body['model'])
        self.assertEqual([oid+':source_grounded_action'],list(spec.body['questions']))
        self.assertNotEqual(original.fingerprint,spec.fingerprint)
        with self.assertRaisesRegex(ValueError,'IDs required'):
            producer.action_grounding_request(original,['other'])

    def test_conjunction_preserves_uncertainty_and_threshold(self):
        for correctness,action,eligible in [(.90,.90,True),(.89,.99,False),(.99,.89,False)]:
            with self.subTest(correctness=correctness,action=action):
                spec,batch=self.batch(correctness)
                result=admission.assess(batch,self.receipt(spec,action))
                self.assertEqual(eligible,result['eligible'])
                self.assertEqual(correctness,result['checks']['requested_response']['probability'])

    def test_edited_control_needs_fresh_correctness_and_stays_evaluation_only(self):
        spec,batch=self.batch(evaluation=True)
        result=admission.assess(batch,self.receipt(spec,correctness=.1))
        self.assertFalse(result['eligible']);self.assertTrue(result['evaluation_only'])
        self.assertEqual(2,len(spec.body['questions']))

    def test_reserve_is_durable_cumulative_and_preserves_final_allowance(self):
        with TemporaryDirectory() as directory:
            root=Path(directory);packet=dict(objective={'sha256':'fixed'})
            ledger=dict(objective=packet['objective'],entries=[],stopped=None)
            admission.save(root/'ledger.json',ledger)
            for n in range(4):
                admission.reserve(root,packet,dict(id=str(n),fingerprint=str(n),reserved_usd='.50',maximum_attempts=6))
            with self.assertRaisesRegex(ValueError,'reserve exhausted'):
                admission.reserve(root,packet,dict(id='next',fingerprint='next',reserved_usd='.01',maximum_attempts=1))
            admission.reserve(root,packet,dict(id='final',fingerprint='final',reserved_usd='.50',maximum_attempts=6),final=True)
            with self.assertRaisesRegex(ValueError,'already reserved'):
                admission.reserve(root,packet,dict(id='final',fingerprint='final',reserved_usd='.01',maximum_attempts=1),final=True)
            self.assertEqual(5,len(json.loads((root/'ledger.json').read_text())['entries']))

    def test_stop_blocks_paid_execution_and_offline_missing_result_cannot_dispatch(self):
        with TemporaryDirectory() as directory:
            root=Path(directory);packet=dict(objective={})
            admission.save(root/'ledger.json',dict(objective={},entries=[],stopped={'reason':'failed'}))
            with self.assertRaisesRegex(ValueError,'ledger stopped'):
                admission.reserve(root,packet,dict(id='next',reserved_usd='.01',maximum_attempts=1))
            with patch.object(admission.support.requests,'execute',side_effect=AssertionError('Offline')):
                with self.assertRaises(FileNotFoundError):admission.saved_result(root,dict(id='absent'))

    def test_transport_failure_is_one_durable_attempt_and_no_semantic_retry(self):
        for broken in (True,False):
            with self.subTest(broken=broken),TemporaryDirectory() as directory:
                root=Path(directory);path=root/'plan.json';spec,batch=self.batch()
                batch['historical_input']=dict(path='unused');batch['historical_result']=dict(path='unused')
                packet=dict(batches=[batch],objective={})
                admission.save(root/'ledger.json',dict(objective={},entries=[],stopped=None))
                sent=[]
                def transport(request):
                    sent.append(request)
                    if broken:raise OSError('lost response')
                    return admission.support.requests.WireResponse(200,json.dumps(dict(model=spec.body['model'],
                        usage=dict(input_tokens=100,output_tokens=1),
                        answers={k:dict(type='noul',noul=.2) for k in spec.body['questions']})))
                with patch.object(admission,'load',return_value=packet),patch.object(admission.diagnostic,'checked_json'):
                    result=admission.run(path,'one',transport=transport)
                    self.assertEqual('STOPPED',result['status'])
                    self.assertEqual(result,admission.run(path,'one',transport=transport))
                self.assertEqual(1,len(sent))
                self.assertEqual(1,result['usage']['paid_attempts'])
                self.assertIsNotNone(json.loads((root/'ledger.json').read_text())['stopped'])


if __name__=='__main__':unittest.main()
