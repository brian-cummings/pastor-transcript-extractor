from copy import deepcopy
import hashlib
import unittest

from pastor_transcript_extractor import profile_capability_review as c
from pastor_transcript_extractor import profile_description as d
from test_profile_description import fixture


def prepared(record):
    o = next(o for o in record['observations'] if o['field'] == 'assurance_security')
    return dict(evidence_id=o['id'], source_sha256=o['source_sha256'],
        target_sha256=hashlib.sha256(o['full_target_text'].encode()).hexdigest(),
        title='A review contrast', review_question='Is an in-scope assertion present?', caution='Do not infer adoption.',
        proposed_position=None, position_status='withheld_pending_separate_source_review')


class CapabilityReviewTests(unittest.TestCase):
    def test_packet_is_prepared_evidence_not_a_position_finding(self):
        record = d.build(*fixture(routed=True)); before = deepcopy(record)
        packet = c.build(record, {'cases': [prepared(record)]})
        self.assertEqual(before, record)
        self.assertEqual('READY_FOR_BOUNDED_DECISION', packet['status'])
        self.assertEqual([], packet['published_position_claims'])
        for field in ('pilot_execution','automatic_adoption','new_measurements','collection','quote_execution'):
            self.assertFalse(packet[field])
        self.assertEqual(0, packet['provider_requests'])
        self.assertIn('No G1 V3', packet['limits'])
        self.assertIn('existing G1', packet['reuse'])

    def test_below_threshold_stays_below_threshold_not_denial(self):
        record = d.build(*fixture(routed=True))
        packet = c.build(record, {'cases': [prepared(record)]})
        case = packet['cases'][0]
        self.assertEqual('measured_below_threshold', case['current_state'])
        self.assertIsNone(case['proposed_position'])
        self.assertEqual('not_established', case['opportunity_status'])
        self.assertFalse(case['historical_exact_target_match'])
        self.assertEqual([], packet['published_position_claims'])

    def test_changed_source_is_excluded_without_substitution(self):
        record = d.build(*fixture(routed=True))
        for field in ('source_sha256','target_sha256','evidence_id'):
            case = prepared(record); case[field] = 'changed'
            packet = c.build(record, {'cases':[case]})
            self.assertEqual('PREPARED_CASES_INCOMPLETE', packet['status'])
            self.assertEqual([], packet['cases'])
            self.assertEqual(1, len(packet['excluded_cases']))

    def test_published_interpretation_cannot_be_smuggled_into_case(self):
        record = d.build(*fixture(routed=True)); case = prepared(record)
        case['proposed_position'] = 'The preacher affirms permanent security.'
        with self.assertRaises(ValueError): c.build(record, {'cases':[case]})

    def test_source_links_and_full_text_are_preserved_in_packet(self):
        record = d.build(*fixture(routed=True)); case = prepared(record)
        packet = c.build(record, {'cases':[case]})
        self.assertEqual(case['source_sha256'], packet['cases'][0]['source_sha256'])
        self.assertIn('index.html#passage-9-1', c.markdown(packet))
        self.assertIn('never become denial', packet['acceptance_checks'][2])
        self.assertIn('pte analysis structure-readiness --segment-view --description --json', c.markdown(packet))

    def test_current_reference_packet_respects_closed_historical_gate(self):
        inputs = c.load_inputs()
        self.assertEqual(3, len(inputs['cases']))
        self.assertEqual(5, len(inputs['references']))
        self.assertTrue(all(row['sha256'] for row in inputs['references']))
        self.assertTrue(inputs['historical_target_hashes'])
