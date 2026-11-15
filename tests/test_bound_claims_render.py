import json
import unittest

from pastor_transcript_extractor.bound_claims import render, report
from pastor_transcript_extractor.bound_claims.common import read_json
from pastor_transcript_extractor.collector_retrieval_json_v1_1 import seal

try:
    from tests.bound_claims_support import PilotBuilder
except ImportError:
    from bound_claims_support import PilotBuilder


class RenderTests(PilotBuilder, unittest.TestCase):
    def test_section_groups_accepted_pro_claims_with_links_and_empty_areas(self):
        self.build(range(6), range(8), public_at=2, accept={'v1b0', 'v1b2', 'v1b5'})
        summary = render.run(self.root)
        self.assertEqual((1, 3, 2), (summary['profile_id'], summary['accepted_claims'], summary['sermons_with_findings']))
        section = read_json(self.root / 'SECTION_1.json')
        self.assertEqual(section, seal(section))
        self.assertEqual({'salvation': 2, 'assurance': 0, 'other_doctrine': 0, 'public_life': 1, 'pastoral_address': 0},
                         {g['area']: g['accepted_claims'] for g in section['groups']})
        text = (self.root / 'SECTION_1.md').read_text()
        self.assertIn('# Bound claims: Pastor Sample', text)
        self.assertEqual(3, text.count('No accepted claims in this sample.'))  # assurance, other doctrine, pastoral address
        self.assertIn('## Public life', text)
        self.assertIn('prescribe · voiced by preacher · preacher adopts · role: asserted', text)
        self.assertIn('[Second Sermon](https://youtu.be/2)', text)
        # source link carries the block's watch URL and timestamp; the only quotation is the anchor text
        self.assertIn('“We are saved by grace alone 5.” — [T, 1:40](https://youtu.be/1?t=0)', text)
        self.assertNotIn('Vote for the levy', text)

    def test_rejected_and_flash_only_claims_never_appear(self):
        self.build([0, 1], range(8), accept={'v1b0'})
        section = read_json(self.root / 'SECTION_1.json') if render.run(self.root) else None
        self.assertEqual(['v1b0'], [f['coordinate'] for f in section['findings']])

    def test_no_frequency_or_interpretive_language(self):
        self.build(range(6), range(8), accept={f'v1b{i}' for i in range(6)})
        render.run(self.root)
        text = (self.root / 'SECTION_1.md').read_text().lower()
        for word in ('often', 'dominant', 'typically', 'usually', 'tendency', 'frequently', 'most of'):
            self.assertNotIn(word, text)
        self.assertIn('does not show how common, central or representative', text)

    def test_profile_with_most_accepted_claims_is_chosen_and_requires_accepted_claims(self):
        self.assertEqual(7, render.choose_profile({9: [1, 2, 3], 7: [1, 2, 3], 3: [1]}))
        with self.assertRaises(ValueError):
            render.choose_profile({})
        self.build(range(2), range(2), accept=set())
        with self.assertRaises(ValueError):
            render.run(self.root)

    def test_rendered_section_satisfies_report_criterion_three(self):
        self.build(range(6), range(8), accept={f'v1b{i}' for i in range(6)})
        self.assertEqual('PENDING_RENDER', {r['criterion']: r for r in report.compute(self.root)['acceptance']}[3]['status'])
        render.run(self.root)
        rows = {r['criterion']: r for r in report.compute(self.root)['acceptance']}
        self.assertEqual(('PASS', [1]), (rows[3]['status'], rows[3]['observed']['qualifying_profiles'] and [int(p) for p in rows[3]['observed']['qualifying_profiles']]))

    def test_section_records_contract_gap_and_non_admission(self):
        self.build(range(3), range(3))
        render.run(self.root)
        section = read_json(self.root / 'SECTION_1.json')
        self.assertEqual('not_admitted', section['production_admission'])
        self.assertIn('no bridge was forced', section['contract_gap'])
        self.assertEqual(section['ready_claim_ids'], [f['claim_id'] for f in section['findings']])


if __name__ == '__main__':
    unittest.main()
