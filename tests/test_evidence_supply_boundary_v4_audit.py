"""Focused audit coverage/tamper tests; semantic judgments are authored.

The small vectors reconstructed here exercise coverage validation. The CLI's live
verification separately validates the real sealed receipts and admission replay.
"""
from copy import deepcopy
import json
from types import SimpleNamespace
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from typer.testing import CliRunner

from pastor_transcript_extractor import evidence_supply_boundary_v4_audit as audit
from pastor_transcript_extractor.cli import app


class V4AuditTests(unittest.TestCase):
    def setUp(self):
        self.report=json.loads(audit.AUDIT.read_text())
        self.packet=json.loads(audit.panel.INPUT.read_text())
        self.review=json.loads(audit.REVIEW.read_text())
        self.measurements={}
        for row in self.report['records']:
            phases={}
            for field in row['fields']:
                phase=phases.setdefault(field['phase'],dict(phase=field['phase'],raw_answers={},decisions={}))
                phase['raw_answers'][field['question_key']]=dict(choice=field['raw_choice'],probabilities=deepcopy(field['probabilities']),confidence=field['confidence'])
                phase['decisions'][field['field']]=field['decision']
            self.measurements[row['case_id']]=SimpleNamespace(fingerprint=row['measurement_fingerprint'],document=dict(
                case_id=row['case_id'],binding=deepcopy(row['binding']),decisions={f['field']:f['decision'] for f in row['fields']},phases=list(phases.values())))

    def check(self):
        audit.validate_coverage(self.report,self.packet,self.review,self.measurements)

    def record(self,case_id):
        return next(r for r in self.report['records'] if r['case_id']==case_id)

    def test_complete_case_field_and_difference_inventory(self):
        self.check()
        self.assertEqual(224,self.report['audited_fields'])
        self.assertEqual(20,self.report['historical_difference_count'])
        self.assertEqual(2,self.report['forward_difference_count'])
        self.assertEqual(6,self.report['forward_checks'])
        self.assertEqual(18,self.report['cases_without_forward_checks'])

    def test_unscored_voice_cannot_be_omitted(self):
        row=self.record('B4-R073');row['fields']=[f for f in row['fields'] if f['field']!='voice']
        with self.assertRaisesRegex(ValueError,'all-field'):self.check()

    def test_unscored_withholding_remains_visible(self):
        row=self.record('B4-R018');row['unscored_findings']=[]
        with self.assertRaisesRegex(ValueError,'Unscored'):self.check()

    def test_confidence_cannot_replace_selected_probability(self):
        row=self.record('B4-R077-complete-promise')
        field=next(f for f in row['fields'] if f['field']=='boundary');field['selected_probability']=field['confidence']
        with self.assertRaisesRegex(ValueError,'gating changed'):self.check()

    def test_forward_differences_cannot_be_erased(self):
        self.record('B4-R077-complete-promise')['comparisons'][0]['differences']=[]
        with self.assertRaisesRegex(ValueError,'comparison changed'):self.check()

    def test_source_excerpt_and_witness_must_remain_bound(self):
        self.record('B4-R018')['source_excerpt']['text']+=' invented'
        with self.assertRaisesRegex(ValueError,'excerpt changed'):self.check()

    def test_unknown_voice_scope_cannot_be_silently_filled(self):
        self.record('B4-R023')['witness_facts']['left_voice']='preacher'
        with self.assertRaisesRegex(ValueError,'binding changed'):self.check()

    def test_anti_vacuity_hold_and_delegated_authority_are_explicit(self):
        self.assertEqual('FAIL',self.report['raw_semantic_recommendation'])
        self.assertEqual('HOLD',self.report['containment_recommendation'])
        summary=self.report['admission_summary']
        self.assertEqual(2,summary['admitted']);self.assertEqual(0,summary['unsupported_admitted'])
        self.assertEqual(['G3_current_preacher_act','G3_reported_local_act'],summary['missing_positive_families'])
        g3=[r for r in self.report['records'] if r['capability']=='G3']
        self.assertEqual(13,len(g3))
        self.assertTrue(all(next(f['decision'] for f in r['fields'] if f['field']=='boundary')=='unclear' for r in g3))
        acceptance=json.loads(audit.ACCEPTANCE.read_text())
        self.assertEqual('delegated_post_receipt_audit_replay_only',acceptance['acceptance_mode'])
        self.assertIsNone(acceptance['final_raw_semantic_decision']);self.assertIsNone(acceptance['final_containment_decision'])

    def test_cli_has_no_execution_or_write_mode(self):
        with patch.object(audit,'verify',return_value=self.report), patch.object(audit.execution,'execute',side_effect=AssertionError('No provider execution')):
            result=CliRunner().invoke(app,['analysis','evidence-supply-boundary-v4-audit'])
        self.assertEqual(0,result.exit_code,result.output)
        self.assertIn('containment HOLD',' '.join(result.output.split()))
        self.assertIn('provider_requests=0',' '.join(result.output.split()))
        self.assertIn('Brian accepted both decisions', ' '.join(result.output.split()))
        result=CliRunner().invoke(app,['analysis','evidence-supply-boundary-v4-audit','--execute'])
        self.assertNotEqual(0,result.exit_code)

    def test_human_decision_preserves_hold_and_historical_audit(self):
        decision = audit.accepted_decision(self.report)
        self.assertEqual('FAIL', decision['raw_semantic_status'])
        self.assertEqual('HOLD', decision['containment_status'])
        self.assertFalse(decision['repair_implementation_authorized'])
        self.assertIsNone(self.report['final_containment_decision'])

    def test_resealed_retroactive_pass_is_rejected(self):
        decision = deepcopy(audit.accepted_decision(self.report))
        decision['containment_status'] = 'PASS'
        decision.pop('content_fingerprint')
        decision['content_fingerprint'] = audit.panel.old.frozen.fp(decision)
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'acceptance-decision-v4.json').write_text(json.dumps(decision))
            with patch.object(audit, 'AUDIT', root / audit.AUDIT.name):
                with patch.object(audit.panel.old.frozen.v1, 'file_hash', return_value=decision['audit_file_sha256']):
                    with self.assertRaisesRegex(ValueError, 'human decision'):
                        audit.accepted_decision(self.report)
