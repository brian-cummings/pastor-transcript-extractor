import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from typer.testing import CliRunner
from pastor_transcript_extractor.cli import app
from pastor_transcript_extractor import sermon_g1_feasibility_stage_gate as gate


class G1ClosedGateTests(unittest.TestCase):
    def test_human_pass_record_is_verified_without_provider(self):
        with patch('pastor_transcript_extractor.sermon_g1_feasibility_review.Provider', side_effect=AssertionError('provider')):
            result = CliRunner().invoke(app, ['analysis', 'g1-feasibility-review', '--stage-gate'])
        self.assertEqual(0, result.exit_code, result.output)
        self.assertIn('CLOSED by Brian; provider_requests=0', result.output)
        self.assertIn('198/209', result.output)
        decision = json.loads(gate.GATE.read_text())
        self.assertEqual(11, len(decision['accepted_residual_checks']))
        self.assertFalse(decision['expectations_rewritten'])

    def test_closed_gate_blocks_all_provider_modes_before_dispatch(self):
        for flags in ([], ['--revision', 'v2'], ['--revision', 'v2', '--replace-lost-response']):
            with self.subTest(flags=flags), patch('pastor_transcript_extractor.sermon_g1_feasibility_revision.run') as run:
                result = CliRunner().invoke(app, ['analysis', 'g1-feasibility-review', *flags])
                self.assertNotEqual(0, result.exit_code)
                self.assertIn('closed PASS', result.output)
                run.assert_not_called()

    def test_tampered_decision_is_rejected_and_remains_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'decision.json'
            decision = json.loads(gate.GATE.read_text()); decision['status'] = 'reopened'
            path.write_text(json.dumps(decision))
            with patch.object(gate, 'GATE', path):
                self.assertTrue(gate.is_closed())
                with self.assertRaisesRegex(ValueError, 'Invalid G1 stage-gate'):
                    gate.show()
