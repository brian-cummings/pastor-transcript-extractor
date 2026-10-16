"""Proposal binding/consistency only; these are not tests of an A1 guard."""
from copy import deepcopy
import json
import unittest
from unittest.mock import patch

from typer.testing import CliRunner

from pastor_transcript_extractor import g3_atomic_admission_review as review
from pastor_transcript_extractor.cli import app


class AtomicAdmissionProposalTests(unittest.TestCase):
    def setUp(self):
        self.proposal = json.loads(review.PROPOSAL.read_text())
        self.report = json.loads(review.audit.AUDIT.read_text())

    def check(self):
        review.validate_design(self.proposal, self.report)

    def row(self, case_id):
        return next(r for r in self.proposal['records'] if r['case_id'] == case_id)

    def test_design_has_two_scoped_controls_without_new_admissions(self):
        self.check()
        eligible = [r for r in self.proposal['records'] if r['claim_sufficiency_exhibit']]
        self.assertEqual({'B4-R018', 'B4-R053'}, {r['case_id'] for r in eligible})
        for row in eligible:
            self.assertEqual('quarantined', row['original_admission']['status'])
            self.assertEqual('unclear', row['original_boundary']['decision'])
            self.assertEqual('PROPOSED_NOT_ADMISSION_AUTHORITY', row['claim_sufficiency_exhibit']['status'])

    def test_raw_recipient_unknown_cannot_be_review_filled(self):
        row = self.row('B4-R077-complete-promise')
        self.assertIn('unsupported_addressee', row['unchanged_blockers'])
        row['proposed_disposition'] = 'eligible_only_after_separate_policy_and_claim_review_acceptance'
        with self.assertRaisesRegex(ValueError, 'expansion'): self.check()

    def test_unsafe_reported_voice_blocker_cannot_be_removed(self):
        self.row('B4-R073')['unchanged_blockers'].remove('unsupported_voice')
        with self.assertRaisesRegex(ValueError, 'blocker lost'): self.check()

    def test_proposed_witness_cannot_claim_accepted_authority(self):
        self.row('B4-R018')['claim_sufficiency_exhibit']['status'] = 'ACCEPTED'
        with self.assertRaisesRegex(ValueError, 'exhibit'): self.check()

    def test_atomic_witness_cannot_supply_circumstance_claim(self):
        self.row('B4-R053')['claim_sufficiency_exhibit']['circumstance_claim'] = 'bound'
        with self.assertRaisesRegex(ValueError, 'exhibit'): self.check()

    def test_original_quarantine_must_remain_original(self):
        self.row('B4-R018')['original_admission']['status'] = 'admitted_local_only'
        with self.assertRaisesRegex(ValueError, 'quarantines'): self.check()

    def test_exact_target_cannot_borrow_neighbor(self):
        self.row('B4-R018')['claim_sufficiency_exhibit']['exact_utterance']['text'] += ' read the Bible'
        with self.assertRaisesRegex(ValueError, 'exhibit'): self.check()

    def test_frozen_semantics_and_threshold_cannot_change(self):
        for field, value in [('selected_probability_threshold', .60), ('shared_boundary_question', {})]:
            with self.subTest(field=field):
                proposal = deepcopy(self.proposal)
                proposal[field] = value
                with self.assertRaisesRegex(ValueError, 'frozen semantics'):
                    review.validate_design(proposal, self.report)

    def test_pin_inventory_cannot_omit_real_guard(self):
        self.proposal['pins'].pop('src/pastor_transcript_extractor/evidence_boundary_admission.py')
        with self.assertRaisesRegex(ValueError, 'Missing pinned'): self.check()

    def test_no_retroactive_pass_or_future_execution_authority(self):
        self.proposal['accepted_v4_decisions']['containment'] = 'PASS'
        with self.assertRaisesRegex(ValueError, 'binding'): self.check()

    def test_cli_is_read_only_and_explicitly_prospective(self):
        with patch('pastor_transcript_extractor.g3_atomic_admission_decision.accepted_decision', return_value=None), patch.object(review, 'verify', return_value=self.proposal), patch.object(
                review.audit.execution, 'execute', side_effect=AssertionError('provider path forbidden')):
            result = CliRunner().invoke(app, ['analysis', 'g3-atomic-admission-review'])
        self.assertEqual(0, result.exit_code, result.output)
        output = ' '.join(result.output.split())
        self.assertIn('prospective controls only', output)
        self.assertIn('Historical proposal only', output)
        self.assertIn('provider_requests=0', output)
        for flag in ('--execute', '--accept-review', '--prepare-only'):
            result = CliRunner().invoke(app, ['analysis', 'g3-atomic-admission-review', flag])
            self.assertNotEqual(0, result.exit_code)
