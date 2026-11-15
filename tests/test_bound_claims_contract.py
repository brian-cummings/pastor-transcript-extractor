from copy import deepcopy
from decimal import Decimal
import tempfile
from pathlib import Path
import unittest

from pastor_transcript_extractor.bound_claims import contract
from pastor_transcript_extractor.bound_claims.common import ensure_outside_repository
from pastor_transcript_extractor.bound_claims.ledger import CeilingExceeded, PilotLedger, list_price_usd

TARGET = 'We are saved by grace alone. Some say works matter, but I reject that. Vote for the school levy.'


def claim(**changes):
    value = dict(area='salvation', object='salvation by grace', proposition='People are saved by grace alone.',
                 polarity='affirm', voiced_by='preacher', preacher_adoption='adopts', speech_role='asserted',
                 conditions=[], qualifications=[], reasons=[], anchor_text='We are saved by grace alone.',
                 anchor_offsets=dict(start=0, end=28))
    value.update(changes)
    return value


class AnchorTests(unittest.TestCase):
    def test_verbatim_hit_at_reported_offsets(self):
        result = contract.check_anchor(claim(), TARGET)
        self.assertEqual(('ok', 0, 28, False), (result['status'], result['start'], result['end'], result['offsets_corrected']))

    def test_wrong_offsets_are_located_once_by_code_without_editing_text(self):
        result = contract.check_anchor(claim(anchor_offsets=dict(start=5, end=9)), TARGET)
        self.assertEqual(('ok', 0, True), (result['status'], result['start'], result['offsets_corrected']))

    def test_miss_is_an_anchor_failure(self):
        result = contract.check_anchor(claim(anchor_text='We are saved by works.'), TARGET)
        self.assertEqual(('anchor_failure', 'not_in_source'), (result['status'], result['reason']))

    def test_context_only_anchor_fails(self):
        result = contract.check_anchor(claim(anchor_text='Grace abounds.', anchor_offsets=dict(start=0, end=13)), TARGET,
                                       preceding='Earlier. Grace abounds.', following='')
        self.assertEqual(('anchor_failure', 'context_only'), (result['status'], result['reason']))

    def test_ambiguous_repeat_with_wrong_offsets_fails(self):
        result = contract.check_anchor(claim(anchor_text='grace', anchor_offsets=dict(start=1, end=6)), 'grace and grace')
        self.assertEqual(('anchor_failure', 'ambiguous_in_target'), (result['status'], result['reason']))

    def test_whitespace_only_anchor_fails(self):
        self.assertEqual('anchor_failure', contract.check_anchor(claim(anchor_text='  ', anchor_offsets=dict(start=0, end=2)), TARGET)['status'])


class SchemaTests(unittest.TestCase):
    def test_empty_and_valid_outputs_pass(self):
        self.assertEqual([], contract.validate_claims({'claims': []}))
        self.assertEqual(claim(), contract.validate_claims({'claims': [claim()]})[0])

    def test_extra_missing_and_bad_enum_fields_are_rejected(self):
        for bad in (dict(claim(), extra=1), {k: v for k, v in claim().items() if k != 'reasons'}, claim(polarity='maybe'),
                    claim(conditions='none'), claim(anchor_offsets=dict(start='0', end=3)), claim(anchor_offsets=dict(start=0))):
            with self.assertRaises(ValueError):
                contract.validate_claims({'claims': [bad]})
        for bad in ([], {'claims': 'x'}, {'claims': [], 'x': 1}):
            with self.assertRaises(ValueError):
                contract.validate_claims(bad)

    def test_too_many_claims_are_rejected(self):
        with self.assertRaises(ValueError):
            contract.validate_claims({'claims': [claim()] * (contract.MAXIMUM_CLAIMS_PER_BLOCK + 1)})

    def test_fingerprint_ignores_offsets_but_not_meaning(self):
        base = contract.claim_fingerprint(1, 2, claim())
        self.assertEqual(base, contract.claim_fingerprint(1, 2, claim(anchor_offsets=dict(start=3, end=9))))
        self.assertNotEqual(base, contract.claim_fingerprint(1, 2, claim(polarity='reject')))
        self.assertNotEqual(base, contract.claim_fingerprint(1, 3, claim()))

    def test_schema_requires_exactly_the_documented_fields(self):
        self.assertEqual(set(contract.FIELDS), set(contract.CLAIM_SCHEMA['properties']))
        self.assertEqual(set(contract.FIELDS), set(contract.CLAIM_SCHEMA['required']))


class LedgerTests(unittest.TestCase):
    def test_refuses_step_whose_worst_case_exceeds_remaining_ceiling(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = PilotLedger(Path(directory) / 'ledger.json', ceiling_usd=Decimal('1.00'), ceiling_attempts=3)
            ledger.require_step('extract_pro', Decimal('1.00'), 3)
            with self.assertRaises(CeilingExceeded):
                ledger.require_step('extract_pro', Decimal('1.01'), 1)
            with self.assertRaises(CeilingExceeded):
                ledger.require_step('extract_pro', Decimal('0.10'), 4)
            ledger.reserve('a', 'verify', Decimal('0.60'))
            with self.assertRaises(CeilingExceeded):
                ledger.require_step('verify', Decimal('0.50'), 1)
            with self.assertRaises(CeilingExceeded):
                ledger.reserve('b', 'verify', Decimal('0.50'))

    def test_known_usage_releases_the_reservation_and_missing_usage_keeps_it(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = PilotLedger(Path(directory) / 'ledger.json', ceiling_usd=Decimal('1.00'), ceiling_attempts=5)
            ledger.reserve('a', 'leaf', Decimal('0.40'))
            ledger.reserve('b', 'leaf', Decimal('0.40'))
            ledger.resolve('a', actual_usd=Decimal('0.01'), input_tokens=100, output_tokens=0)
            ledger.resolve('b', actual_usd=None)
            self.assertEqual(Decimal('0.41'), ledger.committed_usd())
            summary = ledger.summary()['steps']['leaf']
            self.assertEqual((2, 1, '0.40'), (summary['attempts'], summary['unresolved'], summary['reserved_unresolved_usd']))

    def test_attempt_is_never_reserved_twice_and_usage_cannot_exceed_reservation(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = PilotLedger(Path(directory) / 'ledger.json')
            ledger.reserve('a', 'verify', Decimal('0.01'))
            with self.assertRaises(ValueError):
                ledger.reserve('a', 'verify', Decimal('0.01'))
            with self.assertRaises(ValueError):
                ledger.resolve('a', actual_usd=Decimal('0.02'))

    def test_ceiling_cannot_be_changed_on_an_existing_ledger(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'ledger.json'
            PilotLedger(path).reserve('a', 'verify', Decimal('0.01'))
            with self.assertRaises(ValueError):
                PilotLedger(path, ceiling_usd=Decimal('9.00')).remaining()

    def test_list_price(self):
        self.assertEqual(Decimal('0.042'), list_price_usd(1_000_000, 123, '0.042', '0'))


class PathTests(unittest.TestCase):
    def test_repository_paths_are_refused(self):
        with self.assertRaises(ValueError):
            ensure_outside_repository(Path(__file__).parent / 'x')
        with tempfile.TemporaryDirectory() as directory:
            self.assertTrue(ensure_outside_repository(Path(directory) / 'x'))


if __name__ == '__main__':
    unittest.main()
