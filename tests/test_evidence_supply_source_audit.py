from copy import deepcopy
from decimal import Decimal
import unittest
from unittest.mock import patch

from typer.testing import CliRunner

from pastor_transcript_extractor import evidence_supply_source_audit as audit
from pastor_transcript_extractor.cli import app


def fixture():
    text = 'Love one another. This means care.'
    left = dict(start=0, end=17, text=text[:17])
    right = dict(start=18, end=len(text), text=text[18:])
    check = dict(check_id='R001-edge', left=left, right=right,
                 expected={'explains_text': ['linked']}, opportunity='positive')
    reference = dict(video_id=1, checks=[check])
    candidate = dict(candidate_id='candidate-1', target=dict(start=0, end=len(text), text=text), left=left, right=right)
    decisions = dict(explains_text='linked')
    evaluation = dict(candidate_id='candidate-1', decisions=decisions)
    observation = dict(candidate_id='candidate-1', raw_answers={'explains_text': {'choice': 'linked'}},
                       payload={'decision': 'linked'}, request_key='request-1', pastor_credit=False)
    alias = dict(candidate=candidate, evaluation=evaluation, raw_answers=observation['raw_answers'],
                 payload=observation['payload'], request_key=observation['request_key'])
    item_id = audit.frozen.fp(dict(capability='G2', video_id=1, spans=dict(left=left, right=right)))
    item = dict(item_id=item_id, candidate_id='candidate-1', check_ids=['R001-edge'],
                accepted_positive_facts={'explains_text': 'linked'}, retained_decisions=decisions,
                spans=dict(left=left, right=right), capability='G2', video_id=1,
                category='partial_local', pastor_credit=False)
    row = dict(check_id='R001-edge', video_id=1, frozen_check=check, frozen_status='matches_frozen_fields',
               frozen_opportunity='positive', aliases=[alias], usable_item_ids=[item_id])
    usage = dict(attempts=1, input_tokens=100, output_tokens=20)
    cost = str(Decimal(100) * audit.frozen.PRICE)
    report = dict(input_fingerprint='packet', records=[row], frozen_counts={'matches_frozen_fields': 1},
                  audited_focal_checks=1, requested_nonmatching_checks=0,
                  provider_requests_during_audit=0, usable_evidence=dict(items=[item],
                  audited_focal_subset_unique_items=1, by_capability={'G2': 1}, by_category={'partial_local': 1},
                  full_run_list_price_usd=cost, full_run_cost_per_audited_subset_item_usd=cost,
                  whole_run_unique_items=None, whole_run_unit_cost_usd=None))
    report['content_fingerprint'] = audit.frozen.fp(report)
    packet = dict(content_fingerprint='packet', model='jev-1.13.0', request_manifest=[dict(request_key='request-1')])
    result = dict(input_fingerprint='packet', reference_checks=[dict(check_id='R001-edge', status='matches_frozen_fields', evaluations=[evaluation])],
                  observations=[observation], check_counts={'matches_frozen_fields': 1},
                  raw_rows=[dict(request_key='request-1', usage=dict(input_tokens=100, output_tokens=20))], usage=usage,
                  actual_list_price_usd=cost)
    sources = {1: dict(text=text, main_span=dict(start=0, end=len(text)))}
    ledger = dict(input_fingerprint='packet', attempts=[dict(request_key='request-1', status='validated',
                  usage=dict(input_tokens=100, output_tokens=20), resolved_model='jev-1.13.0')])
    return report, packet, result, dict(rows=[reference]), sources, ledger


class SourceAuditTests(unittest.TestCase):
    def setUp(self):
        self.values = fixture()

    def verify(self):
        report = self.values[0]
        report['content_fingerprint'] = audit.frozen.fp({k: v for k, v in report.items() if k != 'content_fingerprint'})
        audit.validate_review(*self.values)

    def test_scoped_evidence_and_accounting_pass(self):
        self.verify()

    def test_frozen_expectation_cannot_be_rewritten(self):
        self.values[0]['records'][0]['frozen_check'] = deepcopy(self.values[0]['records'][0]['frozen_check'])
        self.values[0]['records'][0]['frozen_check']['expected'] = {'explains_text': ['unclear']}
        with self.assertRaisesRegex(ValueError, 'Frozen check'):
            self.verify()

    def test_missing_focal_case_is_rejected(self):
        self.values[0]['records'] = []
        with self.assertRaisesRegex(ValueError, 'focal audit check'):
            self.verify()

    def test_withheld_fact_cannot_be_filled_by_auditor(self):
        self.values[0]['usable_evidence']['items'][0]['accepted_positive_facts']['adoption'] = 'own_or_adopted'
        with self.assertRaisesRegex(ValueError, 'filled a withheld'):
            self.verify()

    def test_duplicate_item_cannot_inflate_denominator(self):
        economics = self.values[0]['usable_evidence']
        economics['items'].append(deepcopy(economics['items'][0]))
        economics['audited_focal_subset_unique_items'] = 2
        with self.assertRaisesRegex(ValueError, 'duplicated'):
            self.verify()

    def test_whole_run_economics_cannot_be_inferred_from_subset(self):
        self.values[0]['usable_evidence']['whole_run_unique_items'] = 1
        with self.assertRaisesRegex(ValueError, 'scope'):
            self.verify()

    def test_ledger_usage_drift_is_rejected(self):
        self.values[-1]['attempts'][0]['usage']['input_tokens'] = 200
        with self.assertRaisesRegex(ValueError, 'Ledger differs'):
            self.verify()

    def test_cli_verifies_without_executing_provider(self):
        report = dict(audited_focal_checks=114, requested_nonmatching_checks=70,
                      usable_evidence={'audited_focal_subset_unique_items': 34})
        with patch.object(audit, 'load_review', return_value=report), patch.object(audit.frozen, 'execute', side_effect=AssertionError('No execution allowed')):
            result = CliRunner().invoke(app, ['analysis', 'evidence-supply-source-audit'])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn('FAIL', result.output)
        self.assertIn('not a readiness PASS', result.output)


if __name__ == '__main__':
    unittest.main()
