"""Scope checks for a read-only authored audit, no sermon evaluation."""
from copy import deepcopy
import unittest
from unittest.mock import patch
from typer.testing import CliRunner
from pastor_transcript_extractor import source_unit_repair_audit as a
from pastor_transcript_extractor.cli import app


def review():
    return dict(recovered_cases=[dict(reference_id=str(i),usable_atomic_evidence_certified=False) for i in range(47)],
        remaining_segmentation_cases=[dict(reference_id=str(i)) for i in range(47,54)],
        persistent_G2_cases=[{}]*4,preserved_G3_questions=[{}]*4,provider_requests=0,implementation_changed=False,confirmation_selected=False)


class SourceUnitAuditTests(unittest.TestCase):
    def test_review_preserves_all_frozen_cases_and_no_semantic_credit(self):
        a.validate_summary(review())
        for key,value in [('provider_requests',1),('confirmation_selected',True),('implementation_changed',True)]:
            r=review();r[key]=value
            with self.assertRaises(ValueError):a.validate_summary(r)
        r=review();r['recovered_cases'][0]['usable_atomic_evidence_certified']=True
        with self.assertRaises(ValueError):a.validate_summary(r)

    def test_duplicate_or_missing_reference_rejected(self):
        r=review();r['remaining_segmentation_cases'][0]['reference_id']='0'
        with self.assertRaises(ValueError):a.validate_summary(r)
        r=review();r['remaining_segmentation_cases'].pop()
        with self.assertRaises(ValueError):a.validate_summary(r)

    def test_cli_review_never_invokes_development_replay(self):
        with patch.object(a,'verify_review',return_value=dict(content_fingerprint='audit',recommendation='DEVELOPMENT_FREEZE_ONLY')) as verify, \
                patch.object(a.repair,'run_development',side_effect=AssertionError('No replay')):
            result=CliRunner().invoke(app,['analysis','source-unit-repair','--verify-review'])
            self.assertEqual(0,result.exit_code,result.output);verify.assert_called_once()
            result=CliRunner().invoke(app,['analysis','source-unit-repair','--verify-review','--run-development','--approve-input','x'])
            self.assertNotEqual(0,result.exit_code)


if __name__=='__main__':unittest.main()
