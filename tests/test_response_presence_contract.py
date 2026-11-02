"""Authored examples specify semantics; stub probabilities test mechanics only."""
from copy import deepcopy
import unittest

from pastor_transcript_extractor import response_growth_binding as producer
from test_profile_section import reading


class PresenceContractTests(unittest.TestCase):
    def test_opt_in_changes_only_presence_question_and_identity(self):
        window, _, _, checked = reading()
        old = producer.dimension_verification(window, checked['observations'])
        new = producer.dimension_verification(window, checked['observations'], presence_contract=True)
        self.assertEqual(old, producer.dimension_verification(window, checked['observations']))
        self.assertNotEqual(old.fingerprint, new.fingerprint)
        self.assertEqual(old.body['state'], new.body['state'])
        self.assertEqual(old.body['model'], new.body['model'])
        for key, question in new.body['questions'].items():
            if key.endswith(':requested_response_present'):
                self.assertNotEqual(old.body['questions'][key], question)
                self.assertIn('not whether the source supports it', question['instructions'])
                self.assertIn('regardless', question['criteria']['true'])
                self.assertNotIn('unsupported', question['criteria']['false'])
            else:
                self.assertEqual(old.body['questions'][key], question)

    def test_authored_semantic_cases_and_two_gate_boundary(self):
        window, _, _, checked = reading()
        # These expected labels are specifications, never model validation.
        cases = [
            ('The preacher requests that listeners donate a car.', .89, .99, False),
            ('The preacher invites repentance; listener uptake is unknown.', .90, .90, True),
            ('God loves them. No human response is established for this point.', .99, .10, False),
            ('The preacher requests prayer.', .99, .89, False),
        ]
        for candidate, correctness, presence, eligible in cases:
            with self.subTest(candidate=candidate):
                observations = deepcopy(checked['observations'])
                observations[0]['response_growth']['requested_response'] = candidate
                spec = producer.dimension_verification(window, observations, presence_contract=True)
                oid = observations[0]['id']
                answers = {k: dict(type='noul', noul=.99) for k in spec.body['questions']}
                answers[oid+':requested_response']['noul'] = correctness
                answers[oid+':requested_response_present']['noul'] = presence
                row = next(r for r in producer.dimension_findings(observations, dict(output=answers), spec)
                           if r['observation_id'] == oid and r['field'] == 'requested_response')
                self.assertEqual(eligible, row['eligible'])
                self.assertEqual(candidate, row['value'])
                instruction = spec.body['questions'][oid+':requested_response_present']['instructions']
                self.assertIn('Do not borrow a response from another item', instruction)
                self.assertIn('uptake is unknown does not erase', instruction)

    def test_presence_only_cannot_be_used_as_dimension_receipt(self):
        window, _, _, checked = reading()
        old = producer.dimension_verification(window, checked['observations'])
        diagnostic = producer.presence_diagnostic_request(old)
        self.assertEqual(old.body['state'], diagnostic.body['state'])
        self.assertTrue(all(k.endswith(':requested_response_present') for k in diagnostic.body['questions']))
        with self.assertRaisesRegex(ValueError, 'cannot grant dimension eligibility'):
            producer.dimension_findings(checked['observations'], {}, diagnostic)
        self.assertIsNone(producer.dimension_verification(window, [], presence_contract=True))


if __name__ == '__main__':
    unittest.main()
