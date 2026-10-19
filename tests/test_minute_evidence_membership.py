from copy import deepcopy
from pathlib import Path
import unittest
from unittest.mock import patch
from typer.testing import CliRunner
from pastor_transcript_extractor import minute_evidence_membership as m
from pastor_transcript_extractor.collector_retrieval_json_v1_1 import seal


def fixture():
    text='Intro\nOpening\nExposition\nConclusion\nHost thanks'
    texts=text.splitlines();units=[];cursor=0
    for i,t in enumerate(texts):
        units.append(dict(unit_id=str(i),start=cursor,end=cursor+len(t),text=t,source_segment_indexes=[i],start_seconds=i*60,end_seconds=i*60+30));cursor+=len(t)+1
    window=dict(start=units[1]['start']+2,end=units[3]['end'],rationale='Exclude partial opening and host; retain restored conclusion')
    review=seal(dict(rows=[dict(video_id=951,main_span=window,technically_usable_sermon=True)]))
    source=seal(dict(video_id=951,text=text,units=units,main_span=window,source_validation_fingerprint=review['content_fingerprint']))
    extracted=dict(classification=dict(retained_segment_indexes=[0,1,2]))
    binding=dict(source_fingerprint=source['content_fingerprint'],extraction_content_fingerprint=seal(extracted)['content_fingerprint'],reviewed_main_span=window)
    authority=seal(dict(status='PROVIDER_FREE_FIXTURE_RECONCILIATION_AUTHORIZED',membership_scope='retired_fixture_preparation_only',review_validation_fingerprint=review['content_fingerprint'],source_bindings={'951':binding},production_authorization=False,provider_execution=False,measurement_admission=False,classifications_mutated=False,source_files_mutated=False,additional_sources=False))
    return source,extracted,review,authority


class MembershipTests(unittest.TestCase):
    def test_default_never_inherits_review_without_explicit_authority(self):
        s,e,r,a=fixture();result=m.effective_membership(s,e,review=r)
        self.assertEqual([0,1,2],result['effective_indexes']);self.assertIsNone(result['authority_fingerprint'])

    def test_reviewed_membership_replaces_rather_than_unions_saved_membership(self):
        s,e,r,a=fixture();result=m.effective_membership(s,e,review=r,authority=a)
        self.assertEqual([2,3],result['effective_indexes']);self.assertEqual([3],result['added_indexes']);self.assertEqual([0,1],result['removed_indexes'])
        self.assertEqual(['1'],result['boundary_units_deferred']);self.assertFalse(result['production_authorization']);self.assertFalse(result['pastor_identity_established'])

    def test_old_source_review_and_extraction_are_immutable(self):
        s,e,r,a=fixture();before=deepcopy((s,e,r,a));m.effective_membership(s,e,review=r,authority=a)
        self.assertEqual(before,(s,e,r,a))

    def test_changed_extraction_or_unknown_source_fails_closed(self):
        s,e,r,a=fixture();e['classification']['retained_segment_indexes']=[0,1,2,3]
        with self.assertRaisesRegex(ValueError,'binding'):m.effective_membership(s,e,review=r,authority=a)
        s,e,r,a=fixture();s=seal({**s,'video_id':520})
        with self.assertRaisesRegex(ValueError,'binding'):m.effective_membership(s,e,review=r,authority=a)

    def test_stale_source_review_and_unreviewed_bounds_cannot_apply(self):
        s,e,r,a=fixture();changed=deepcopy(r);changed['rows'][0]['main_span']['end']-=1;changed=seal(changed)
        with self.assertRaisesRegex(ValueError,'binding'):m.effective_membership(s,e,review=changed,authority=a)
        s,e,r,a=fixture();s=seal({**s,'main_span':dict(start=0,end=len(s['text']))})
        with self.assertRaises(ValueError):m.effective_membership(s,e,review=r,authority=a)

    def test_production_or_provider_scope_is_rejected(self):
        for key in ('production_authorization','provider_execution','measurement_admission','classifications_mutated','source_files_mutated','additional_sources'):
            s,e,r,a=fixture();a=seal({**a,key:True})
            with self.assertRaisesRegex(ValueError,'scope'):m.effective_membership(s,e,review=r,authority=a)

    def test_bad_source_and_nonusable_review_fail_closed(self):
        s,e,r,a=fixture();s['text']+='x'
        with self.assertRaisesRegex(ValueError,'seal'):m.effective_membership(s,e,review=r,authority=a)
        s,e,r,a=fixture();r['rows'][0]['technically_usable_sermon']=False;r=seal(r);s=seal({**s,'source_validation_fingerprint':r['content_fingerprint']});a['review_validation_fingerprint']=r['content_fingerprint'];a['source_bindings']['951']['source_fingerprint']=s['content_fingerprint'];a=seal(a)
        with self.assertRaisesRegex(ValueError,'usable'):m.effective_membership(s,e,review=r,authority=a)

    def test_same_indexes_different_authority_still_changes_membership_identity(self):
        s,e,r,a=fixture();one=m.effective_membership(s,e,review=r,authority=a)
        another=seal({**a,'decision_note':'separate accepted authority identity'})
        two=m.effective_membership(s,e,review=r,authority=another)
        self.assertEqual(one['effective_indexes'],two['effective_indexes']);self.assertNotEqual(one['content_fingerprint'],two['content_fingerprint'])

    def test_cli_uses_reviewed_mode_only_when_explicit(self):
        from pastor_transcript_extractor.cli import app
        result=dict(status='RECONCILED_FIXTURES_NO_INFERENCE_AUTHORIZED',content_fingerprint='synthetic',counts={})
        with patch.object(m,'prepare',return_value=(result,Path('/tmp/synthetic'))) as prep:
            r=CliRunner().invoke(app,['analysis','structure-readiness','--prepare-handoff','--reviewed-membership'])
            self.assertEqual(0,r.exit_code,r.output);prep.assert_called_once()
        r=CliRunner().invoke(app,['analysis','structure-readiness','--reviewed-membership'])
        self.assertEqual(2,r.exit_code)
