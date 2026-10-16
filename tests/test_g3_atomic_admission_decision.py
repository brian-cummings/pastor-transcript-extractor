"""Final decision checks never re-execute the closed semantic/policy panel."""
from copy import deepcopy
import unittest
from unittest.mock import patch
from typer.testing import CliRunner
from pastor_transcript_extractor import g3_atomic_admission_decision as decision
from pastor_transcript_extractor import g3_atomic_admission_replay as replay
from pastor_transcript_extractor.cli import app


class ClosedDecisionTests(unittest.TestCase):
    def test_accepted_scope_and_v4_decisions_are_separate(self):
        d = decision.accepted_decision()
        self.assertEqual('PASS', d['status'])
        self.assertTrue(d['closed'])
        self.assertEqual(dict(raw_semantic='FAIL', containment='HOLD'), d['v4_decisions'])
        self.assertFalse(d['discovery_execution_authorized'])

    def test_resealed_scope_or_verdict_changes_rejected(self):
        original = decision.a1.v4.sealed
        value = deepcopy(decision.accepted_decision())
        for key, changed in [('status', 'HOLD'), ('scope', 'general_production'), ('further_panel_replay_authorized', True)]:
            bad = {**value, key: changed}
            with patch.object(decision.a1.v4, 'sealed', side_effect=lambda p: bad if p == decision.DECISION else original(p)):
                with self.assertRaisesRegex(ValueError, 'decision binding'): decision.accepted_decision()

    def test_all_A1_cli_modes_respect_closure_without_any_panel_work(self):
        with patch.object(replay, 'context', side_effect=AssertionError('closed panel')), \
             patch.object(replay, 'execute', side_effect=AssertionError('closed panel')), \
             patch.object(replay, 'verify_audit', side_effect=AssertionError('closed panel')):
            for mode in ([], ['--check-only'], ['--verify-audit']):
                r = CliRunner().invoke(app, ['analysis', 'g3-atomic-admission-replay', *mode])
                self.assertEqual(0, r.exit_code, r.output)
                self.assertIn('no replay performed', ' '.join(r.output.split()))
            r = CliRunner().invoke(app, ['analysis', 'g3-atomic-admission-replay', '--execute', '--approve-packet', 'old'])
            self.assertNotEqual(0, r.exit_code)
            self.assertIn('closed', r.output)
