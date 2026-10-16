"""Authority guards for a read-only design packet, not repair behavior tests."""
import copy
import unittest
from unittest.mock import patch
from typer.testing import CliRunner
from pastor_transcript_extractor.cli import app
from pastor_transcript_extractor import collector_retrieval_design as design


class RetrievalDesignTests(unittest.TestCase):
    def test_cannot_grant_execution_or_expand_frozen_bounds(self):
        plan = design.sealed(design.HERE / 'proposal-v1.json')
        decision = design.sealed(design.HERE / 'decision-v1.json')
        design.validate(plan, decision)
        for key in ('provider_calls', 'local_encoder_execution', 'source_selection', 'repair_implementation'):
            changed = copy.deepcopy(plan)
            changed['authorization'][key] = True
            with self.assertRaises(ValueError):
                design.validate(changed, decision)
        changed = copy.deepcopy(plan)
        changed['budget']['source_candidate_ceiling'] += 1
        with self.assertRaises(ValueError):
            design.validate(changed, decision)

    def test_cli_reads_proposal_and_has_no_execution_option(self):
        runner = CliRunner()
        with patch.object(design, 'verify', return_value=({}, {'content_fingerprint': 'test'})) as check:
            result = runner.invoke(app, ['analysis', 'collector-retrieval-design', '--check-only'])
        self.assertEqual(result.exit_code, 0, result.output)
        check.assert_called_once_with()
        self.assertIn('PROPOSAL_ONLY', result.output)
        self.assertIn('provider_requests=0', result.output)
        result = runner.invoke(app, ['analysis', 'collector-retrieval-design', '--run-development'])
        self.assertNotEqual(result.exit_code, 0)
