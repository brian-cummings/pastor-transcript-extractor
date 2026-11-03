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


if __name__=='__main__':
    unittest.main()
