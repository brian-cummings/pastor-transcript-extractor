"""Focused tamper/coverage checks for the authored review verifier; no inference."""
from copy import deepcopy
import json
import unittest
from unittest.mock import patch

from typer.testing import CliRunner

from pastor_transcript_extractor import evidence_supply_boundary_audit as audit
from pastor_transcript_extractor.cli import app


class BoundaryAuditTests(unittest.TestCase):
    def setUp(self):
        full = json.loads(audit.AUDIT.read_text())
        packet = json.loads(audit.panel.INPUT.read_text())
        # The single narration case exercises the raw-error versus export-veto distinction.
        record = deepcopy(next(r for r in full['records'] if r['case_id'] == 'B3-R078'))
        self.report = dict(records=[record], audited_cases=1, audited_fields=len(record['fields']),
                           prepared_differences=1,
                           difference_class_counts={'safely_quarantined_integrity_finding': 1},
                           confirmed_critical_raw_cases=['B3-R078'], usage=full['usage'],
                           actual_list_price_usd=full['actual_list_price_usd'])
        self.packet = dict(cases=[record['frozen_case']], requests=[q for q in packet['requests'] if q['case_id'] == 'B3-R078'])
        phases = []
        for request in self.packet['requests']:
            fields = [f for f in record['fields'] if f['phase'] == request['phase']]
            phases.append(dict(phase=request['phase'], decisions={f['field']: f['decision'] for f in fields},
                               raw_answers={f['field']: dict(choice=f['raw_choice'], confidence=f['confidence'], probabilities=f['probabilities']) for f in fields}))
        self.result = dict(observations=[dict(case_id=record['case_id'], phases=phases,
                          decisions={f['field']: f['decision'] for f in record['fields']},
                          prepared_field_differences=[{k: d[k] for k in ('field', 'expected', 'actual')} for d in record['prepared_differences']],
                          automatic_critical_flags=[f['flag'] for f in record['automatic_flags']],
                          guarded_local_payload=deepcopy(record['guarded_local_payload']))],
                          usage=full['usage'], actual_list_price_usd=full['actual_list_price_usd'])

    def check(self):
        audit.validate_coverage(self.report, self.packet, self.result)

    def test_raw_error_and_empty_export_remain_distinct(self):
        self.check()
        row = self.report['records'][0]
        self.assertTrue(row['confirmed_critical_raw_error'])
        self.assertEqual({}, row['guarded_local_payload']['positive_facts'])
        self.assertEqual('observed', self.result['observations'][0]['decisions']['reassurance'])

    def test_unscored_field_cannot_be_omitted(self):
        self.report['records'][0]['fields'] = [f for f in self.report['records'][0]['fields'] if f['field'] != 'boundary']
        with self.assertRaisesRegex(ValueError, 'Incomplete field'):
            self.check()

    def test_guard_cannot_be_replaced_by_audit(self):
        self.report['records'][0]['guarded_local_payload']['positive_facts'] = {'reassurance': 'observed'}
        with self.assertRaisesRegex(ValueError, 'actual guard'):
            self.check()

    def test_flag_cannot_be_dropped(self):
        self.report['records'][0]['automatic_flags'] = []
        with self.assertRaisesRegex(ValueError, 'flag omitted'):
            self.check()

    def test_confidence_cannot_replace_selected_probability(self):
        self.report['records'][0]['fields'][0]['selected_probability'] = -1
        with self.assertRaisesRegex(ValueError, 'conflated'):
            self.check()

    def test_source_excerpt_cannot_change(self):
        self.report['records'][0]['source_excerpt']['text'] += 'invented'
        with self.assertRaisesRegex(ValueError, 'Source excerpt'):
            self.check()

    def test_cli_has_no_execution_path(self):
        with patch.object(audit, 'verify', return_value=self.report), patch.object(audit, 'accepted_decision', return_value=None), patch.object(audit.panel, 'execute', side_effect=AssertionError('provider execution')):
            result = CliRunner().invoke(app, ['analysis', 'evidence-supply-boundary-audit'])
        self.assertEqual(0, result.exit_code, result.output)
        self.assertIn('provider_requests=0', result.output)
        self.assertIn('Brian decision pending', ' '.join(result.output.split()))
