"""Proposal-only safeguards; never run discovery or the closed panel."""
from copy import deepcopy
import json
import unittest
from unittest.mock import patch
from typer.testing import CliRunner
from pastor_transcript_extractor import fresh_discovery_readiness as review
from pastor_transcript_extractor.cli import app


class FreshProposalTests(unittest.TestCase):
    def setUp(self):
        self.plan = json.loads(review.PLAN.read_text())
        self.manifest = json.loads(review.MANIFEST.read_text())

    def test_sources_are_fresh_and_scope_is_prospective(self):
        review.validate(self.plan, self.manifest)
        self.assertEqual([1565,1450,1618], [r['video_id'] for r in self.manifest['sources'][:3]])
        self.assertFalse(self.plan['authorization']['evaluation_execution'])
        self.assertFalse(self.plan['authorization']['provider_calls'])

    def test_development_video_or_channel_cannot_return_as_fresh(self):
        for key, value in [('video_id', 1200), ('source_id', 44)]:
            m = deepcopy(self.manifest); m['sources'][0][key] = value
            with self.assertRaisesRegex(ValueError, 'distinct fresh'): review.validate(self.plan, m)

    def test_reserve_cannot_be_silently_added_to_denominator(self):
        m = deepcopy(self.manifest); m['sources'][-1]['role'] = 'primary'
        with self.assertRaisesRegex(ValueError, 'distinct fresh'): review.validate(self.plan, m)

    def test_reference_informed_retrieval_order_is_not_preparation(self):
        self.plan['freeze_order'][1] = 'Inspect gold first then select candidate endpoints'
        with self.assertRaisesRegex(ValueError, 'separation'): review.validate(self.plan, self.manifest)

    def test_proposal_is_not_provider_or_execution_authorization(self):
        for key in ('evaluation_execution', 'provider_calls', 'automatic_attestation', 'discovery_tuning'):
            p = deepcopy(self.plan); p['authorization'][key] = True
            with self.assertRaisesRegex(ValueError, 'authority'): review.validate(p, self.manifest)

    def test_resealed_larger_request_budget_is_not_the_proposal(self):
        self.plan['bounds']['semantic_requests_max'] = 241
        with self.assertRaisesRegex(ValueError, 'bounded'): review.validate(self.plan, self.manifest)

    def test_cli_cannot_execute_or_replay_and_has_no_write_mode(self):
        from pastor_transcript_extractor import g3_atomic_admission_replay as closed
        with patch.object(review, 'verify', return_value=(self.plan,self.manifest)), \
             patch.object(closed, 'run', side_effect=AssertionError('closed panel')):
            result = CliRunner().invoke(app,['analysis','fresh-discovery-readiness','--check-only'])
        self.assertEqual(0, result.exit_code, result.output)
        self.assertIn('no discovery evaluation executed', ' '.join(result.output.split()))
        for flag in ('--execute','--execute-paid','--prepare-only'):
            result = CliRunner().invoke(app,['analysis','fresh-discovery-readiness',flag])
            self.assertNotEqual(0,result.exit_code)
