"""Replay decision and CLI tests. Real typed paths are in test_g3_atomic_admission.

No providers or external runtime fixtures are needed for these unit tests.
"""
from copy import deepcopy
import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from typer.testing import CliRunner

from pastor_transcript_extractor import g3_atomic_admission_replay as replay
from pastor_transcript_extractor.cli import app


class ReplayTests(unittest.TestCase):
    def setUp(self):
        self.packet = json.loads(replay.INPUT.read_text())
        self.historical = json.loads(replay.audit.AUDIT.read_text())
        self.items = deepcopy(self.packet['expected_admissions'])
        for item in self.items.values():
            item.update(pastor_projection=None, quality_score=None)
        self.boundary = Mock()
        self.boundary.policy_authority.policy_json = json.dumps(dict(content_fingerprint='test-policy'))
        self.boundary.policy_authority.authorization_sha256 = 'test-authority'
        self.boundary.base.packet = dict(cases=[r['frozen_case'] for r in self.historical['records']])
        records = {r['case_id']: r for r in self.historical['records']}
        self.boundary.base.measure.side_effect = lambda key, _: SimpleNamespace(
            fingerprint=records[key]['measurement_fingerprint'], key=key)
        def admit(m):
            item = self.items.get(m.key)
            return SimpleNamespace(item=SimpleNamespace(document_json=json.dumps(item)) if item else None,
                                   reasons=() if item else ('test-blocked',))
        self.boundary.admit.side_effect = admit
        self.boundary.export.side_effect = lambda item: item.document_json
        self.boundary.consume_local.side_effect = lambda wires: dict(items=[json.loads(w) for w in wires])
        self.receipts = {k: None for r in self.historical['records'] for k in r['frozen_case']['request_keys']}

    def run_panel(self, approval=None):
        with patch.object(replay, 'context', return_value=(self.packet, self.historical, self.boundary, self.receipts)):
            return replay.run(approval or self.packet['content_fingerprint'])

    def test_both_namespaces_and_unchanged_G2_allow_only_provisional_pass(self):
        result = self.run_panel()
        self.assertEqual('PASS', result['provisional_containment_recommendation'])
        self.assertEqual('PENDING', result['independent_source_audit'])
        self.assertIsNone(result['final_brian_decision'])
        self.assertEqual(4, result['admitted']); self.assertEqual(20, result['quarantined'])
        self.assertEqual(4, self.boundary.deserialize.call_count)

    def test_missing_either_control_is_hold(self):
        for key in ('B4-R018', 'B4-R053'):
            with self.subTest(key=key):
                item = self.items.pop(key)
                result = self.run_panel()
                self.assertEqual('HOLD', result['provisional_containment_recommendation'])
                self.items[key] = item

    def test_wrong_or_extra_fact_is_fail(self):
        self.items['B4-R018']['positive_facts']['reassurance'] = 'observed'
        result = self.run_panel()
        self.assertEqual('FAIL', result['provisional_containment_recommendation'])
        self.assertIn('B4-R018', result['unsupported_or_unresolved_admissions'])

    def test_critical_case_admission_is_fail_even_if_expected_tampered(self):
        item = deepcopy(self.items['B4-R018'])
        self.items['B4-R078'] = item
        self.packet['expected_admissions']['B4-R078'] = {k:v for k,v in item.items() if k not in ('pastor_projection','quality_score')}
        self.assertEqual('FAIL', self.run_panel()['provisional_containment_recommendation'])

    def test_circumstance_or_projection_claim_fails(self):
        for field in ('circumstance_claim', 'pastor_projection', 'quality_score'):
            old = self.items['B4-R053'][field]
            self.items['B4-R053'][field] = 'invented'
            self.assertEqual('FAIL', self.run_panel()['provisional_containment_recommendation'])
            self.items['B4-R053'][field] = old

    def test_unsupported_admission_overrides_missing_control_hold(self):
        self.items.pop('B4-R053')
        self.items['B4-R018']['namespace'] = 'G3_reported_local_act'
        self.assertEqual('FAIL', self.run_panel()['provisional_containment_recommendation'])

    def test_wrong_fingerprint_never_calls_A1_admission(self):
        with self.assertRaisesRegex(ValueError, 'fingerprint'): self.run_panel('wrong')
        self.boundary.admit.assert_not_called()

    def test_raw_identity_change_is_rejected(self):
        self.boundary.base.measure.side_effect = lambda *_: SimpleNamespace(fingerprint='changed')
        with self.assertRaisesRegex(ValueError, 'raw measurement'): self.run_panel()

    def test_cli_default_is_no_write_check_and_no_provider_mode_exists(self):
        with patch.object(replay, 'context', return_value=(self.packet, None, None, None)), \
             patch.object(replay, 'execute', side_effect=AssertionError('Execution forbidden in check mode')):
            result = CliRunner().invoke(app, ['analysis', 'g3-atomic-admission-replay'])
        self.assertEqual(0, result.exit_code, result.output)
        self.assertIn('provider_requests=0', ' '.join(result.output.split()))
        for args in (['--execute'], ['--execute', '--check-only'], ['--approve-packet', 'x'], ['--execute-paid']):
            result = CliRunner().invoke(app, ['analysis', 'g3-atomic-admission-replay', *args])
            self.assertNotEqual(0, result.exit_code)
