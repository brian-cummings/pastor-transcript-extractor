import unittest

from pastor_transcript_extractor.bound_claims import report, review
from pastor_transcript_extractor.bound_claims.common import canonical, read_json, write_json

try:
    from tests.bound_claims_support import PilotBuilder
except ImportError:
    from bound_claims_support import PilotBuilder


class ReportTests(PilotBuilder, unittest.TestCase):
    """Report metrics and acceptance rules over real extraction, verification and decision artifacts."""

    def rows(self):
        return {row['criterion']: row for row in report.compute(self.root)['acceptance']}

    def test_all_criteria_pass(self):
        # Pro makes six claims, all accepted; Flash adds two rejected ones (.75) -> margin .25.
        self.build(range(6), range(8), accept={f'v1b{i}' for i in range(6)})
        self.section()
        result = report.compute(self.root)
        self.assertEqual({1: 'PASS', 2: 'PASS', 3: 'PASS', 4: 'PASS', 5: 'PASS'}, {r['criterion']: r['status'] for r in result['acceptance']})
        self.assertEqual(('PASS', []), (result['status'], result['failing_components']))
        self.assertEqual((1.0, 0.75), (result['producers']['pro']['precision'], result['producers']['flash']['precision']))

    def test_producer_precision_rule_needs_floor_and_margin_over_flash(self):
        # Pro 7 of 8 accepted (.875); Flash makes the same 8 claims, 7 accepted too -> no margin
        self.build(range(8), range(8), accept={f'v1b{i}' for i in range(8)} - {'v1b5'})
        row = self.rows()[1]
        self.assertEqual(('FAIL', 'producer or contract'), (row['status'], row['failing_component']))
        self.assertEqual(0.875, row['observed']['pro'])

    def test_precision_margin_met_when_flash_adds_rejected_claims(self):
        self.build(range(8), range(8), accept={f'v1b{i}' for i in range(4)} | {f'v1b{i}' for i in range(8, 10)})
        # claims are shared by both producers so they carry identical labels; pro and flash both .5 -> FAIL
        self.assertEqual('FAIL', self.rows()[1]['status'])

    def test_precision_floor_failure_and_anchor_failures_count_against_producers(self):
        self.build(range(8), range(8), accept={'v1b0', 'v1b1', 'v1b2'})
        result = report.compute(self.root)
        pro = result['producers']['pro']
        self.assertEqual((8, 3, 5), (pro['claims_produced'], pro['accepted'], pro['rejected']))
        self.assertEqual({'proposition': 5, 'anchor_failure': 0}, pro['rejected_by_category'])
        self.assertEqual(0.375, pro['precision'])

    def test_verifier_that_does_not_separate_fails_criterion_two(self):
        self.build(range(8), range(8), accept={'v1b0', 'v1b1', 'v1b2', 'v1b3'}, jev_by_label=(0.7, 0.7))
        row = self.rows()[2]
        self.assertEqual(('FAIL', 'verifier design'), (row['status'], row['failing_component']))

    def test_verifier_that_separates_only_by_discarding_most_accepted_claims_fails(self):
        # accepted claims all score .62: the .60 threshold retains them but cannot reach precision .90 because
        # rejected claims score .65; higher thresholds drop every accepted claim.
        self.build(range(8), range(8), accept={'v1b0', 'v1b1', 'v1b2', 'v1b3'}, jev_by_label=(0.62, 0.65))
        self.assertEqual('FAIL', self.rows()[2]['status'])

    def test_controls_allow_at_most_one_accepted_claim(self):
        self.build(range(8), range(8), control_claims=(8,), accept=None)
        self.assertEqual('PASS', self.rows()[5]['status'])
        self.setUp()
        self.build(range(8), range(8), control_claims=(8, 9), accept=None)
        row = self.rows()[5]
        self.assertEqual(('FAIL', 'producer over-generation', 2), (row['status'], row['failing_component'], row['observed']['accepted']))

    def test_public_life_needs_an_accepted_pro_public_life_claim(self):
        self.build(range(8), range(8), public_at=0, accept={'v1b1', 'v1b2'})
        self.assertEqual(('FAIL', 'producer on C08'), (self.rows()[4]['status'], self.rows()[4]['failing_component']))
        self.setUp()
        self.build(range(8), range(8), public_at=0, accept={'v1b0'})
        self.assertEqual('PASS', self.rows()[4]['status'])

    def test_delivered_findings_need_two_sermons_and_a_rendered_section(self):
        self.build(range(8), range(8))
        self.assertEqual('PENDING_RENDER', self.rows()[3]['status'])
        self.section(videos=(1, 1))
        self.assertEqual(('FAIL', 'assembly'), (self.rows()[3]['status'], self.rows()[3]['failing_component']))
        self.section(videos=(1, 2))
        self.assertEqual('PASS', self.rows()[3]['status'])

    def test_unlabeled_claims_make_the_table_incomplete(self):
        self.build(range(8), range(8))
        decisions = (self.root / review.DECISIONS)
        lines = decisions.read_text().splitlines()
        decisions.write_text('\n'.join(lines[:-2]) + '\n')
        result = report.compute(self.root)
        self.assertEqual('INCOMPLETE', result['status'])
        self.assertEqual('PENDING_REVIEW', {r['criterion']: r for r in result['acceptance']}[1]['status'])

    def test_threshold_tables_report_precision_and_retained_fraction(self):
        self.build(range(8), range(8), accept={'v1b0', 'v1b1', 'v1b2', 'v1b3'}, jev_by_label=(0.97, 0.85))
        supported = report.compute(self.root)['jev_thresholds']['pro']['supported']
        by_threshold = {t['threshold']: t for t in supported['thresholds']}
        self.assertEqual((8, 4, 0.5, 1.0), (by_threshold[0.8]['passed'], by_threshold[0.8]['accepted_passed'], by_threshold[0.8]['precision'], by_threshold[0.8]['retained_accepted_fraction']))
        self.assertEqual((4, 1.0), (by_threshold[0.9]['passed'], by_threshold[0.9]['precision']))
        self.assertEqual(0.9, supported['first_threshold_reaching_precision_90'])

    def test_agreement_between_producers(self):
        self.build([0, 1, 2], [1, 2, 3])
        agree = report.compute(self.root)['agreement']
        self.assertEqual((2, 1, 1), (agree['matched'], agree['pro_only'], agree['flash_only']))

    def test_billing_finding_identifies_the_billed_unit(self):
        # tokens follow request size when state is billed once ...
        self.build(range(8), range(8), tokens=lambda body: (len(canonical(body['state'])) + len(canonical(body['questions']))) // 4)
        self.assertEqual('per_request', report.compute(self.root)['costs']['jev_billing_finding']['model'])
        self.setUp()
        # ... and follow questions x state when billed per question
        self.build(range(8), range(8), tokens=lambda body: (len(canonical(body['state'])) * len(body['questions']) + len(canonical(body['questions']))) // 4)
        self.assertEqual('per_question', report.compute(self.root)['costs']['jev_billing_finding']['model'])

    def test_strong_block_recall_proxy_and_controls_metrics(self):
        self.build([0, 1, 2, 3], [0], control_claims=(8,))
        pro = report.compute(self.root)['producers']['pro']
        self.assertEqual((8, 0.5, 0.5), (pro['strong_signal_blocks'], pro['claims_per_strong_block'], pro['zero_claim_rate_on_strong_blocks']))
        self.assertEqual((2, 1), (pro['control_blocks'], pro['control_claims']))

    def test_run_writes_sealed_json_and_markdown(self):
        self.build(range(8), range(8))
        summary = report.run(self.root)
        saved = read_json(self.root / 'REPORT.json')
        from pastor_transcript_extractor.collector_retrieval_json_v1_1 import seal
        self.assertEqual(saved, seal(saved))
        text = (self.root / 'REPORT.md').read_text()
        for fragment in ('# Bound-claim pilot report', '## Acceptance', 'Producer precision', '## Jev thresholds against labels', '## Costs'):
            self.assertIn(fragment, text)
        self.assertEqual(set(range(1, 6)), set(summary['acceptance']))

    def test_stopped_or_missing_producer_is_refused(self):
        self.build(range(8), range(8))
        (self.root / 'extract' / 'flash' / 'extraction.json').unlink()
        with self.assertRaises(Exception):
            report.compute(self.root)


if __name__ == '__main__':
    unittest.main()
