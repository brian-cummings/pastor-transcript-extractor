"""Proposal specification tests only; no implementation of evidence admission."""
from copy import deepcopy
import unittest
from unittest.mock import patch

from typer.testing import CliRunner

from pastor_transcript_extractor import evidence_supply_boundary_repair_proposal as proposal
from pastor_transcript_extractor.cli import app


class RepairProposalTests(unittest.TestCase):
    def setUp(self):
        self.spec = proposal.load_sealed(proposal.HERE / 'invariant-spec-v4.json')

    def test_all_assertions_and_source_exhibits_verify_without_execution(self):
        with patch.object(proposal.audit.panel, 'execute', side_effect=AssertionError('provider execution')):
            review = proposal.verify()
        self.assertEqual(55, review['specification_assertions'])
        self.assertEqual(21, review['context_exhibits'])
        self.assertEqual(6, review['forward_checks'])
        self.assertEqual(37, review['manifest']['semantic_revalidation']['maximum_new_requests'])

    def test_all_seven_mechanisms_have_non_model_denial_witnesses(self):
        cases = [e for e in self.spec['examples'] if e['test_id'].startswith('critical-')]
        self.assertEqual(7, len(cases))
        for case in cases:
            with self.subTest(case=case['test_id']):
                self.assertEqual('quarantine', case['expected_admission'])
                self.assertTrue(any(v is False for v in case['conditions'].values()))
                self.assertIn('maximal', case['adversarial_model'])

    def test_missing_one_prerequisite_cannot_claim_eligibility(self):
        witness = next(e for e in self.spec['examples'] if '-missing-' in e['test_id'])
        witness['expected_admission'] = 'eligible_for_reviewed_local_namespace_only'
        with self.assertRaisesRegex(ValueError, 'contradicts'):
            proposal.check_specification(self.spec)

    def test_unknown_and_truthy_strings_do_not_count_as_true(self):
        for value in (None, 'true', 'unknown', 1):
            spec = deepcopy(self.spec)
            witness = deepcopy(next(e for e in spec['examples'] if e['test_id'] == 'G2_bible_edge-supported-positive'))
            witness['test_id'] = 'unknown-support'
            witness['conditions']['reviewed_biblical_anchor'] = value
            witness['expected_admission'] = 'quarantine'
            spec['examples'].append(witness)
            self.assertEqual(56, proposal.check_specification(spec))

    def test_cannot_remove_prerequisite_from_an_example(self):
        del self.spec['examples'][0]['conditions']['review_witness_bound']
        with self.assertRaisesRegex(ValueError, 'prerequisite'):
            proposal.check_specification(self.spec)

    def test_all_deny_is_not_accepted(self):
        for row in self.spec['examples']:
            if row['route'] == 'G2_bible_edge':
                row['conditions']['review_witness_bound'] = False
                row['expected_admission'] = 'quarantine'
        with self.assertRaisesRegex(ValueError, 'all-deny'):
            proposal.check_specification(self.spec)

    def test_reported_local_is_separate_from_current_preacher(self):
        current = set(self.spec['routes']['G3_current_preacher_act'])
        local = set(self.spec['routes']['G3_local_act'])
        self.assertTrue(local < current)
        self.assertTrue({'reviewed_present_preacher', 'reviewed_current_human_recipient', 'raw_current_human_recipient', 'raw_own_or_adopted'} <= current - local)

    def test_cli_has_no_execution_option(self):
        result = CliRunner().invoke(app, ['analysis', 'evidence-supply-boundary-repair-proposal', '--execute'])
        self.assertNotEqual(0, result.exit_code)
        result = CliRunner().invoke(app, ['analysis', 'evidence-supply-boundary-repair-proposal'])
        self.assertEqual(0, result.exit_code, result.output)
        self.assertIn('55 design assertions', ' '.join(result.output.split()))

    def test_human_fail_is_bound_to_unchanged_audit(self):
        report = proposal.load_sealed(proposal.audit.AUDIT)
        decision = proposal.audit.accepted_decision(report)
        self.assertEqual('FAIL', decision['status'])
        self.assertFalse(decision['repair_implementation_authorized'])
        report['content_fingerprint'] = 'wrong'
        with self.assertRaisesRegex(ValueError, 'human decision'):
            proposal.audit.accepted_decision(report)
