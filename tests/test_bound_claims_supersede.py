from decimal import Decimal
from pathlib import Path
import tempfile
import unittest

from pastor_transcript_extractor.bound_claims import supersede
from pastor_transcript_extractor.bound_claims.common import read_json, write_json
from pastor_transcript_extractor.bound_claims.ledger import PilotLedger


class SupersedeTests(unittest.TestCase):
    def pilot(self, directory):
        pilot = Path(directory)
        write_json(pilot / 'plan.json', dict(content_fingerprint='ab' * 32, implementation=dict(commit='old')))
        (pilot / 'extract' / 'pro').mkdir(parents=True)
        (pilot / 'extract' / 'pro' / 'extraction.json').write_text('{}')
        ledger = PilotLedger(pilot / 'ledger.json', ceiling_usd=Decimal('5.00'), ceiling_attempts=600)
        ledger.reserve('leaf/0', 'leaf', Decimal('0.01'))
        ledger.reserve('extract_pro/v1b1', 'extract_pro', Decimal('0.04'))
        ledger.resolve('extract_pro/v1b1', actual_usd=Decimal('0.01'), input_tokens=1, output_tokens=2)
        return pilot, ledger

    def test_moves_plan_and_outputs_and_keeps_spend_counted(self):
        with tempfile.TemporaryDirectory() as directory:
            pilot, ledger = self.pilot(directory)
            before = ledger.committed_usd()
            result = supersede.run(pilot, 'reasoning off')
            ledger = PilotLedger(pilot / 'ledger.json')
            self.assertFalse((pilot / 'plan.json').exists() or (pilot / 'extract').exists())
            destination = Path(result['destination'])
            self.assertTrue((destination / 'plan.json').exists() and (destination / 'extract' / 'pro' / 'extraction.json').exists())
            note = read_json(destination / 'SUPERSEDED.json')
            self.assertEqual(['extract_pro/v1b1'], note['ledger_entries'])
            self.assertEqual(dict(usd='10.00', attempts=1000), note['ceiling'])
            self.assertEqual(dict(usd='5.00', attempts=600), note['previous_ceiling'])
            self.assertEqual(before, ledger.committed_usd())
            self.assertEqual(2, ledger.attempt_count())
            self.assertIsNone(ledger.entry_status('extract_pro/v1b1'))
            self.assertEqual(1, ledger.entry_count('leaf/'))

    def test_refuses_twice_without_a_plan_with_labels_or_without_a_reason(self):
        with tempfile.TemporaryDirectory() as directory:
            pilot, _ = self.pilot(directory)
            with self.assertRaises(ValueError):
                supersede.run(pilot, ' ')
            (pilot / 'decisions.jsonl').write_text('')
            with self.assertRaises(ValueError):
                supersede.run(pilot, 'x')
            (pilot / 'decisions.jsonl').unlink()
            supersede.run(pilot, 'x')
            with self.assertRaises(ValueError):
                supersede.run(pilot, 'x')


if __name__ == '__main__':
    unittest.main()
