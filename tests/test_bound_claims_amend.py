from decimal import Decimal
from pathlib import Path
import tempfile
import unittest

from pastor_transcript_extractor.bound_claims import amend
from pastor_transcript_extractor.bound_claims.common import file_sha256, read_json, write_json
from pastor_transcript_extractor.bound_claims.extract import freeze_plan
from pastor_transcript_extractor.bound_claims.ledger import PilotLedger

try:
    from tests.bound_claims_support import CLEAN, DIRTY, METADATA
except ImportError:
    from bound_claims_support import CLEAN, DIRTY, METADATA

NEWER = lambda: dict(commit='d', src_tree='u', dirty=False)


class AmendTests(unittest.TestCase):
    def pilot(self, directory):
        pilot = Path(directory)
        write_json(pilot / 'strata.json', dict(slice_sha256='s' * 64, blocks=[]))
        ledger = PilotLedger(pilot / 'ledger.json', ceiling_usd=Decimal('10.00'), ceiling_attempts=1000)
        ledger.reserve('extract_pro/v1b1', 'extract_pro', Decimal('0.04'))
        ledger.resolve('extract_pro/v1b1', actual_usd=Decimal('0.01'), input_tokens=1, output_tokens=2)
        freeze_plan(pilot, 's' * 64, file_sha256(pilot / 'strata.json'), ledger, CLEAN, METADATA)
        (pilot / 'extract' / 'pro').mkdir(parents=True)
        (pilot / 'extract' / 'pro' / 'extraction.json').write_text('{}')
        return pilot

    def test_refreezes_at_the_new_commit_keeping_output_entries_and_spend(self):
        with tempfile.TemporaryDirectory() as directory:
            pilot = self.pilot(directory)
            old = read_json(pilot / 'plan.json')
            result = amend.run(pilot, 'attempts ceiling', state=NEWER, metadata=METADATA)
            plan = read_json(pilot / 'plan.json')
            self.assertEqual('u', plan['implementation']['src_tree'])
            self.assertEqual((old['content_fingerprint'], False), (plan['amendment']['amends_plan'], plan['amendment']['requests_changed']))
            self.assertEqual(dict(usd='10.00', attempts=1000), plan['amendment']['previous_ledger_ceiling'])
            self.assertEqual(dict(usd='10.00', attempts=1200), plan['ceiling'])
            self.assertEqual(old, read_json(Path(result['destination']) / 'plan.json'))
            self.assertTrue((pilot / 'extract' / 'pro' / 'extraction.json').exists())
            ledger = PilotLedger(pilot / 'ledger.json')
            self.assertEqual((Decimal('0.010000000'), 1, 1200), (ledger.committed_usd(), ledger.attempt_count(), ledger.ceiling_attempts))
            freeze_plan(pilot, 's' * 64, file_sha256(pilot / 'strata.json'), ledger, NEWER, METADATA)

    def test_refuses_dirty_unchanged_repeated_or_reasonless_amendments(self):
        with tempfile.TemporaryDirectory() as directory:
            pilot = self.pilot(directory)
            with self.assertRaises(ValueError):
                amend.run(pilot, ' ', state=NEWER, metadata=METADATA)
            with self.assertRaises(ValueError):
                amend.run(pilot, 'x', state=DIRTY, metadata=METADATA)
            with self.assertRaises(ValueError):
                amend.run(pilot, 'x', state=CLEAN, metadata=METADATA)
            amend.run(pilot, 'x', state=NEWER, metadata=METADATA)
            with self.assertRaises(ValueError):
                amend.run(pilot, 'x', state=NEWER, metadata=METADATA)


if __name__ == '__main__':
    unittest.main()
