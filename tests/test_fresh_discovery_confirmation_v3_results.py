"""Synthetic source-only matching and review guards; no real-source evaluation."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from pastor_transcript_extractor import fresh_discovery_confirmation_v3_results as r


class FreshV3ResultsTests(unittest.TestCase):
    def test_matching_cannot_turn_geometry_into_readiness_pass(self):
        s=dict(start=0,end=11,text='Stay alert.')
        source=dict(video_id=999,text=s['text'],main_span=dict(start=0,end=11))
        candidate=dict(candidate_id='natural',video_id=999,capability='G3',endpoints=dict(utterance=s,circumstance=None),relation_frame=s)
        entry=dict(candidate=candidate,automatic_envelope=dict(status='prepared_not_attested',**s))
        inventory=r.prep.seal(dict(source_files={},inventories=[dict(video_id=999,entries=[entry],deferrals=[],search_diagnostics=[],budget_proof=dict(sentence_count=1))],queue=[]))
        ref=dict(reference_id='frozen',video_id=999,capability='G3',source_namespace='current_preacher',classification='definite_compatible_opportunity',roles=dict(utterance=s),equivalent_role_occurrences=dict(utterance=[s]),required_source_evidence_spans=[s])
        refs=r.prep.seal(dict(rows=[ref],controls=[]))
        auth=dict(criteria=dict(per_source_minimum=5,per_source_recall=.8,aggregate_recall=.8,aggregate_sufficient_envelope_recall=.8,aggregate_floors=dict(G1_assurance=5,G2_explanation=10,G3_current=1,G3_reported=3)))
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'natural-inventory-v3.json').write_text(json.dumps(inventory));(root/'gold.json').write_text(json.dumps(refs))
            with patch.object(r,'inputs',return_value=({},auth,inventory,refs,{999:source})),patch.object(r.config,'directory',return_value=root),patch.object(r.config,'REFERENCES',root/'gold.json'),patch.object(r,'REVIEW',root/'review-not-yet-authored.json'),patch.object(r.config.collector,'discover',side_effect=AssertionError('No replay')):
                result=r.prepare()
        self.assertEqual('HOLD_PENDING_SOURCE_REVIEW',result['verdict'])
        self.assertEqual(1,result['statistics']['G3_current']['complete_role_upper_bound_hits'])
        self.assertEqual('PENDING_AUTHORED_SOURCE_REVIEW',result['target_envelope_review'])
        self.assertFalse(result['provider_execution_authorized']);self.assertIsNone(result['admitted_items'])

class SourceReviewBindingTests(unittest.TestCase):
    def fixture(self):
        s=dict(start=0,end=5,text='Trust')
        candidate=dict(candidate_id='n',capability='G3',endpoints=dict(utterance=s,circumstance=None))
        inventory=dict(inventories=[dict(entries=[dict(candidate=candidate,automatic_envelope=dict(start=0,end=5))])],queue=[])
        matches=dict(records=[dict(reference_id='ref',role_containment_hits=['n'],required_evidence_coverage_hits=['n'])])
        review=dict(case_reviews=[dict(reference_id='ref',route='G3_current',candidate_id='n',exact_target_roles=candidate['endpoints'],automatic_envelope_span=dict(start=0,end=5),compatible_supply_evidenced=True,target_status='source_supported_compatible_target',envelope_status='sufficient_source_provenance_context')],queue_reviews=[],reviewed_compatible_supply=dict(G3_current=dict(frozen_opportunities=1,reviewed_compatible_hits=1)))
        return review,matches,inventory,dict(rows=[dict(reference_id='ref')])

    def test_review_cannot_replace_a_natural_target_with_manual_narrowing(self):
        values=self.fixture();r.validate_source_reviews(*values)
        values[0]['case_reviews'][0]['exact_target_roles']={}
        with self.assertRaises(ValueError):r.validate_source_reviews(*values)

    def test_review_cannot_promote_missing_context_or_unknown_target(self):
        for key,value in [('envelope_status','missing_required_evidence'),('target_status','unresolved_target_scope')]:
            values=self.fixture();values[0]['case_reviews'][0][key]=value
            with self.assertRaises(ValueError):r.validate_source_reviews(*values)
        values=self.fixture();values[0]['reviewed_compatible_supply']['G3_current']['reviewed_compatible_hits']=2
        with self.assertRaises(ValueError):r.validate_source_reviews(*values)


if __name__=='__main__':unittest.main()
