from copy import deepcopy
import unittest
from pastor_transcript_extractor import pastor_evidence as e
from pastor_transcript_extractor.pastor_fingerprint import build_fingerprint
from test_partial_observations import observation, provenance


def field(value,probability=.95):
    return dict(proposal=value,answer=dict(type='noul',noul=probability),evidence=[],
        proposal_provenance=provenance('producer'),judgment_provenance=provenance('verifier'))


class ConstituentTests(unittest.TestCase):
    def test_known_empty_differs_from_unknown_and_other_fields_not_inferred(self):
        w,parent=observation('uncertain');fields=dict(conditions=field([]),scope=field('This local point',.5),speaker=field('guide',.5))
        row=e.extend_partial_observation(w,parent,fields)
        self.assertEqual(row['partial_binding']['semantic_values'],dict(conditions=[],scope=None,speaker=None))
        self.assertEqual(row['partial_binding']['semantic_masks'],dict(conditions=True,scope=False,speaker=False))
        self.assertFalse(any(row['partial_binding']['masks'].values()));self.assertIsNone(row['binding'])
        self.assertIn('scope',row['partial_binding']['unassessed']);self.assertNotIn('conditions',row['partial_binding']['unassessed'])
        self.assertFalse(any(x['resolved'] for x in row['field_judgments'].values()))
        self.assertFalse(e.EvidencePolicy().permits(row)[0]);self.assertEqual(row['derivation']['parent_observation_id'],parent['id'])

    def test_polarity_preserves_internal_negation_unknown_vs_unsettled(self):
        w,parent=observation()
        for label in ('affirmed','unsettled','insufficient_evidence'):
            entry=field(label);entry['answer']=dict(type='choice',choice=label,confidence=.99,probabilities={k:.97 if k==label else .01 for k in ('affirmed','denied','unsettled','insufficient_evidence')})
            row=e.extend_partial_observation(w,parent,dict(polarity=entry))
            self.assertEqual(row['partial_binding']['semantic_values']['polarity'],None if label=='insufficient_evidence' else label)
            self.assertEqual(row['partial_binding']['proposition'],parent['partial_binding']['proposition'])

    def test_identity_shape_source_provenance_and_literal_guards(self):
        w,parent=observation();before=deepcopy(parent);row=e.extend_partial_observation(w,parent,dict(speaker=field('guide')))
        self.assertEqual(parent,before)
        for kind in ('value','mask','answer','parent','receipt'):
            bad=deepcopy(row)
            if kind=='value': bad['partial_binding']['semantic_values']['speaker']='other'
            if kind=='mask': bad['partial_binding']['semantic_masks']['speaker']=False
            if kind=='answer': bad['constituent_fields']['speaker']['answer']['noul']=.5
            if kind=='parent': bad['derivation']['parent_observation_id']='foreign'
            if kind=='receipt': bad['constituent_fields']['speaker']['judgment_provenance']['raw_response_ref']='foreign'
            with self.subTest(kind=kind),self.assertRaises(ValueError): e.ObservationEnvelope(bad)
        for kind in ('nan','bool','provenance','field','proposition','literal','condition'):
            fields=dict(speaker=field('guide'))
            if kind=='nan': fields['speaker']['answer']['noul']=float('nan')
            if kind=='bool': fields['speaker']['answer']['noul']=True
            if kind=='provenance': del fields['speaker']['judgment_provenance']['question_id']
            if kind=='field': fields['alignment']=field('path')
            if kind=='proposition': fields['proposition']=field('Changed qualified point')
            if kind=='literal': fields['speaker']['evidence']=[dict(source_field='target_text',start=0,end=3,text='bad')]
            if kind=='condition': fields['conditions']=field([dict(kind='concession',rationale='not a condition',span={})])
            with self.subTest(kind=kind),self.assertRaises(ValueError): e.extend_partial_observation(w,parent,fields)

    def test_same_consumer_keeps_partial_without_claims_and_complete_behavior_unchanged(self):
        from test_pastor_fingerprint import observation as complete
        # Generic fixtures only; no actual pastor fingerprints/comparisons.
        w,parent=observation();row=e.extend_partial_observation(w,parent,dict(conditions=field([])))
        fp=build_fingerprint(e.SampleSpec(w.profile_id,(w.video_id,),'synthetic'),e.EvidenceView((row,)))
        self.assertFalse(fp['claim_frames']);self.assertFalse(fp['evidence_relations'])
        self.assertEqual(fp['evidence_observations'],[row]);self.assertEqual(fp['missingness']['excluded'][0]['reason'],'partial_observation')
        full=complete();accepted,excluded=e.EvidenceView((full,)).partition()
        self.assertEqual(accepted,[full]);self.assertFalse(excluded)
