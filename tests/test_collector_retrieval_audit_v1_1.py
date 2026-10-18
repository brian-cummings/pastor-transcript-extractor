"""Source audit integrity tests; never encoder or dataset execution."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from pastor_transcript_extractor import collector_retrieval_audit_v1_1 as audit


def fixture():
    p=dict(start=0,end=5,text='Read.')
    candidate=dict(candidate_id='natural',endpoints=dict(utterance=p,circumstance=None))
    env=dict(start=0,end=10)
    natural=dict(inventories=[dict(video_id=999,entries=[dict(candidate=candidate,automatic_envelope=env)],G3_displacements=[])])
    result=dict(historical_exact_target_diagnostics=[dict(reference_id='frozen',route='G3_current',role_containment_hits=['natural'],required_evidence_coverage_hits=['natural'])])
    refs=dict(rows=[dict(reference_id='frozen')],controls=[])
    review=dict(historical_case_reviews=[dict(reference_id='frozen',candidate_id='natural',target_roles=candidate['endpoints'],envelope_span=env,source_supported_P1_input=True)],
        P1_annotations=[dict(candidate_id='natural',exact_target_roles=deepcopy(candidate['endpoints']),envelope_span=deepcopy(env),annotation_is_new_gold=False,historical_score_change=False,pastor_credit=False)],
        G3_quota_displacement_reviews=[],controls=[],G2_miss_reviews=[])
    return review,result,natural,refs


class AuditTests(unittest.TestCase):
    def test_manual_target_narrowing_is_rejected(self):
        review,result,natural,refs=fixture();audit.validate(review,result,natural,refs)
        changed=deepcopy(review);changed['historical_case_reviews'][0]['target_roles']['utterance']['end']=4
        with self.assertRaisesRegex(ValueError,'narrowed'):audit.validate(changed,result,natural,refs)
        changed=deepcopy(review);changed['P1_annotations'][0]['exact_target_roles']['utterance']['end']=4
        with self.assertRaisesRegex(ValueError,'changed a supplied'):audit.validate(changed,result,natural,refs)

    def test_missing_context_and_missing_frozen_checks_cannot_be_promoted(self):
        review,result,natural,refs=fixture();result['historical_exact_target_diagnostics'][0]['required_evidence_coverage_hits']=[]
        with self.assertRaisesRegex(ValueError,'Missing source context'):audit.validate(review,result,natural,refs)
        review['historical_case_reviews']=[]
        with self.assertRaisesRegex(ValueError,'every frozen check'):audit.validate(review,result,natural,refs)

    def test_missing_quota_and_audit_cannot_grant_pastor_credit(self):
        review,result,natural,refs=fixture();natural['inventories'][0]['G3_displacements']=[dict(parent=0,source_span=dict(start=0,end=5))]
        with self.assertRaisesRegex(ValueError,'quota review'):audit.validate(review,result,natural,refs)
        natural['inventories'][0]['G3_displacements']=[]
        review['P1_annotations'][0]['pastor_credit']=True
        with self.assertRaisesRegex(ValueError,'grant measurement'):audit.validate(review,result,natural,refs)

    def test_cli_extension_delegates_frozen_execution_unchanged(self):
        from typer.testing import CliRunner
        from pastor_transcript_extractor.cli import app
        from pastor_transcript_extractor.commands.analysis import content
        with patch.object(content,'analysis_collector_retrieval_repair') as original:
            r=CliRunner().invoke(app,['analysis','collector-retrieval-repair','--run-development','--approve-input','exact'])
            self.assertEqual(0,r.exit_code,r.output)
            original.assert_called_once_with(False,False,True,'exact',None)

    def test_cli_audit_path_never_loads_encoder(self):
        from typer.testing import CliRunner
        from pastor_transcript_extractor.cli import app
        with patch.object(audit,'verify',return_value=dict(recommendation='STOP',content_fingerprint='sealed')) as check,patch.object(audit.workflow.encoder,'LocalEncoder',side_effect=AssertionError('No encoder')):
            r=CliRunner().invoke(app,['analysis','collector-retrieval-repair','--verify-audit'])
            self.assertEqual(0,r.exit_code,r.output);check.assert_called_once_with(None)
            r=CliRunner().invoke(app,['analysis','collector-retrieval-repair','--verify-audit','--run-development'])
            self.assertNotEqual(0,r.exit_code)
