from copy import deepcopy
from dataclasses import asdict
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from pastor_transcript_extractor import profile_a3_delivery as pilot
from pastor_transcript_extractor import response_presence_diagnostic as diagnostic
from pastor_transcript_extractor import response_growth_binding as producer
from pastor_transcript_extractor.pastor_evidence import digest
from test_response_presence_diagnostic import fixture


class A3CompositionTests(unittest.TestCase):
    def setup_case(self, root, correctness=.91):
        prepared = diagnostic.prepare(root, fixture(root))
        parent = json.loads(Path(prepared['packet']).read_text())
        batch = parent['batches'][2]
        refs = batch['evidence']
        result_ref = next(r for r in refs if '/dimensions/' in r['path'] and r['path'].endswith('result.json'))
        result_path = Path(result_ref['path']); result = json.loads(result_path.read_text())
        receipt_path = Path(result['receipt']['path']); receipt = json.loads(receipt_path.read_text())
        original = pilot.support.requests.RequestSpec(**receipt['request'])
        receipt_path = root/'receipts'/(original.fingerprint+'.json')
        receipt['token_account'] = original.preflight()
        receipt['response']['output'][pilot.OID+':requested_response']['noul'] = correctness
        receipt['response_digest'] = digest(receipt['response'])
        receipt_path.write_text(json.dumps(receipt))
        result['receipt'] = diagnostic.reference(receipt_path)
        result_path.write_text(json.dumps(result)); result_ref.update(diagnostic.reference(result_path))
        outcome = dict(status='PASS',rows=[dict(observation_id=pilot.OID,passed=True,presence_probability=.96)],
            receipts=[dict(path='separate-presence-receipt',sha256='retained')])
        return dict(batch=batch), outcome, original

    def test_separate_conjunction_preserves_text_history_and_contracts(self):
        with TemporaryDirectory() as directory:
            root = Path(directory); proposal, outcome, original = self.setup_case(root)
            before = deepcopy(proposal)
            with patch.object(pilot.a3,'locate',return_value=(proposal,None)), \
                 patch.object(pilot.a3,'report',return_value=outcome), \
                 patch.object(pilot,'CORRECTNESS_REQUEST',original.fingerprint), \
                 patch.object(pilot,'PRESENCE_REQUEST',proposal['batch']['fingerprint']):
                value = pilot.composition(root/'audit.json')
            row = value['row']
            self.assertTrue(row['eligible'])
            self.assertEqual(original.body['state']['items'][0]['response_growth']['requested_response'],row['value'])
            self.assertEqual(.89,row['historical_presence']['probability'])
            self.assertEqual(.91,row['checks']['requested_response']['probability'])
            self.assertEqual(.96,row['checks']['requested_response_present']['probability'])
            self.assertEqual(producer.DIMENSION_VERIFICATION_VERSION,row['constituents']['correctness']['contract'])
            self.assertEqual(producer.PRESENCE_CONTRACT,row['constituents']['presence']['contract'])
            self.assertNotIn('verification_request',row)  # no synthetic combined provider receipt
            self.assertEqual(before,proposal)

    def test_low_correctness_changed_payload_or_unapproved_case_cannot_release(self):
        with TemporaryDirectory() as directory:
            root=Path(directory); proposal,outcome,original=self.setup_case(root,correctness=.89)
            with patch.object(pilot.a3,'locate',return_value=(proposal,None)), \
                 patch.object(pilot.a3,'report',return_value=outcome), \
                 patch.object(pilot,'CORRECTNESS_REQUEST',original.fingerprint), \
                 patch.object(pilot,'PRESENCE_REQUEST',proposal['batch']['fingerprint']):
                with self.assertRaisesRegex(ValueError,'each meet'):
                    pilot.composition(root/'audit.json')
                proposal['batch']['request']['body']['state']['items'][0]['response_growth']['requested_response']+=' changed'
                with self.assertRaisesRegex(ValueError,'differs'):
                    pilot.composition(root/'audit.json')
            with self.assertRaisesRegex(ValueError,'Explicit approval'):
                pilot.deliver(root/'audit.json','A1')

    def test_dimension_claim_copies_machine_value_and_retains_limits(self):
        row=dict(field='requested_response',value='Unchanged machine response with its qualifications.',authority=pilot.AUTHORITY)
        observation=dict(id=pilot.OID,source_refs=[dict(video_id=4589)])
        claim=pilot.section.dimension_claim(observation,row)
        self.assertEqual('The response requested or described at this selected point is: '+row['value'],claim['wording'])
        self.assertEqual('local_observation',claim['assertion_force'])
        self.assertEqual([pilot.OID],claim['machine_observation_ids'])
        self.assertIn(pilot.AUTHORITY,claim['limits'])


class ApprovedSupportTests(unittest.TestCase):
    def prepared(self, directory):
        from test_deepinfra_streaming import spec
        request=spec()
        root=Path(directory)/'evaluation'/pilot.VERSION/'case'
        root.mkdir(parents=True)
        task=dict(fingerprint=request.fingerprint,request=asdict(request),token_account=request.preflight())
        (root/'support-plan.json').write_text(json.dumps(dict(tasks=[task])))
        return root,request

    def test_one_assessment_replay_and_no_schema_correction(self):
        from test_profile_analysis_support_execution import wire
        with TemporaryDirectory() as directory:
            root,request=self.prepared(directory)
            with patch.object(pilot,'SUPPORT_REQUEST',request.fingerprint), \
                 patch.object(pilot.support.correction,'request',side_effect=AssertionError('No correction')):
                sent=[]
                def send(spec):sent.append(spec);return wire(spec,output='{}')
                result=pilot.approved_assessment(root,request,transport=send)
                self.assertEqual(result,pilot.approved_assessment(root,request,transport=send))
            self.assertEqual(1,len(sent))
            self.assertEqual(1,result['usage']['paid_attempts'])
            self.assertFalse(result['unresolved_usage'])

    def test_lost_response_consumes_reservation_without_retry(self):
        with TemporaryDirectory() as directory:
            root,request=self.prepared(directory)
            with patch.object(pilot,'SUPPORT_REQUEST',request.fingerprint):
                sent=[]
                def lost(spec):sent.append(spec);raise OSError('Lost response')
                result=pilot.approved_assessment(root,request,transport=lost)
                self.assertEqual(result,pilot.approved_assessment(root,request,transport=lost))
            self.assertEqual(1,len(sent));self.assertTrue(result['unresolved_usage'])
            self.assertEqual(str(pilot.support.requests.request_reservation(request)),result['usage']['reserved_usd'])

    def test_shared_stream_recovery_is_bounded_to_two_physical_attempts(self):
        from test_deepinfra_streaming import Harness,loop,normal
        with TemporaryDirectory() as directory:
            root,request=self.prepared(directory)
            h=Harness(request,[loop(request),normal(request)])
            with patch.object(pilot,'SUPPORT_REQUEST',request.fingerprint):
                result=pilot.approved_assessment(root,request,transport=h.managed())
            self.assertEqual(2,len(h.requests));self.assertEqual(2,result['usage']['paid_attempts'])
            self.assertFalse(result['unresolved_usage'])
            self.assertLessEqual(float(result['usage']['reserved_usd']),.03)

    def test_changed_fingerprint_and_frozen_payload_rejected_before_dispatch(self):
        with TemporaryDirectory() as directory:
            root,request=self.prepared(directory)
            with self.assertRaisesRegex(ValueError,'fingerprint'):
                pilot.approved_assessment(root,request,transport=lambda s:self.fail('No call'))
            frozen=json.loads((root/'support-plan.json').read_text())
            frozen['tasks'][0]['request']['body']['temperature']=1
            (root/'support-plan.json').write_text(json.dumps(frozen))
            with patch.object(pilot,'SUPPORT_REQUEST',request.fingerprint),self.assertRaisesRegex(ValueError,'changed'):
                pilot.approved_assessment(root,request,transport=lambda s:self.fail('No call'))


if __name__=='__main__':
    unittest.main()
