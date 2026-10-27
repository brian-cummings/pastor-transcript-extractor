from copy import deepcopy
from dataclasses import asdict
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from pastor_transcript_extractor import pastor_evidence as e
from pastor_transcript_extractor import pastor_fingerprint as f
from pastor_transcript_extractor.source_passages import bind_evidence_roles
from test_source_passages import window_with


def provenance(label='test'):
    return dict(model='synthetic',prompt_digest=label+'prompt',raw_response_ref=label+'receipt',request_fingerprint=label+'request',response_digest=label+'response',question_id=label+'question')


def specimen(mode='known'):
    window=window_with('The guide said this. The gate is open. I endorse that message.')
    package=bind_evidence_roles(window,dict(start_unit='u0001',end_unit='u0001'),voice_context_ranges=[dict(start_unit='u0000',end_unit='u0000')],adoption_ranges=[dict(start_unit='u0002',end_unit='u0002')])
    decisions={}
    for field,choice in dict(voice='quoted_or_reported',occurrence='actual',adoption='adopted').items():
        decisions[field]=dict(type='choice',choice=choice,probabilities={k:.97 if k==choice else .03/(len(e.ROLE_OPTIONS[field])-1) for k in e.ROLE_OPTIONS[field]},confidence=.95 if mode=='known' else .5,**provenance(field))
    return window,dict(reading='The gate is open.',span=package['proposition']['span']),package['binding_evidence'],decisions


def observation(mode='known'):
    w,p,roles,d=specimen(mode)
    return w,e.compile_partial_observation(w,p,roles,d,evidence_provenance=provenance())


class PartialObservationTests(unittest.TestCase):
    def test_exact_roles_preserved_missing_fields_never_fabricated(self):
        w,p,roles,decisions=specimen();before=deepcopy((p,roles,decisions))
        out=e.compile_partial_observation(w,p,roles,decisions,evidence_provenance=provenance())
        self.assertEqual((p,roles,decisions),before)
        self.assertIsNone(out['binding']);self.assertEqual(out['partial_binding']['evidence'],roles)
        self.assertEqual(out['partial_binding']['values'],dict(voice='quoted_or_reported',occurrence='actual',adoption='adopted'))
        self.assertTrue(all(out['partial_binding']['masks'].values()))
        self.assertIsNone(out['partial_binding']['speaker']);self.assertIsNone(out['partial_binding']['adoption_basis'])
        self.assertFalse(any(x['resolved'] for x in out['field_judgments'].values()))
        self.assertEqual(out['production_admission'],'not_admitted')
        self.assertEqual(out['source_refs'][0]['video_id'],w.video_id)
        for field in decisions: self.assertEqual(out['field_decisions'][field]['raw_response_ref'],field+'receipt')

    def test_uncertainty_high_confidence_unknown_and_invalid_distribution(self):
        w,p,roles,decisions=specimen('uncertain')
        out=e.compile_partial_observation(w,p,roles,decisions,evidence_provenance=provenance())
        self.assertTrue(all(v is None for v in out['partial_binding']['values'].values()))
        self.assertFalse(any(out['partial_binding']['masks'].values()))
        self.assertEqual(out['field_decisions']['voice']['choice'],'quoted_or_reported')
        for field,choice in dict(voice='unresolved',occurrence='unresolved',adoption='undetermined').items():
            decisions[field].update(choice=choice,confidence=.99,probabilities={k:1 if k==choice else 0 for k in e.ROLE_OPTIONS[field]})
        self.assertFalse(any(e.role_values(decisions)[1].values()))
        for kind in ('mass','nan','boolean','missing_option','missing_provenance','extra_field','argmax'):
            bad=deepcopy(decisions)
            if kind=='mass': bad['voice']['probabilities']['unresolved']=.2
            if kind=='nan': bad['voice']['confidence']=float('nan')
            if kind=='boolean': bad['voice']['probabilities']['unresolved']=True
            if kind=='missing_option': del bad['voice']['probabilities']['preacher']
            if kind=='missing_provenance': del bad['voice']['raw_response_ref']
            if kind=='extra_field': bad['polarity']=deepcopy(bad['voice'])
            if kind=='argmax': bad['voice']['choice']='preacher'
            with self.subTest(kind=kind),self.assertRaises(ValueError): e.role_values(bad)

    def test_identity_literal_and_role_mutations_rejected(self):
        w,out=observation()
        for kind in ('model','receipt','mask','value','span','admission','binding'):
            bad=deepcopy(out)
            if kind=='model': bad['field_decisions']['voice']['model']='foreign'
            if kind=='receipt': bad['producer']['role_evidence']['raw_response_ref']='foreign'
            if kind=='mask': bad['partial_binding']['masks']['voice']=False
            if kind=='value': bad['partial_binding']['values']['voice']='preacher'
            if kind=='span': bad['partial_binding']['evidence']['voice']['evidence'][0]['text']='foreign'
            if kind=='admission': bad['production_admission']='admitted'
            if kind=='binding': bad['binding']={}
            with self.subTest(kind=kind),self.assertRaises(ValueError): e.ObservationEnvelope(bad)
        w,p,roles,d=specimen()
        roles['voice']['evidence'][0]['text']='invented'
        with self.assertRaises(ValueError): e.compile_partial_observation(w,p,roles,d,evidence_provenance=provenance())
        w,p,roles,d=specimen();roles['adoption']['status']='adopted'
        with self.assertRaises(ValueError): e.compile_partial_observation(w,p,roles,d,evidence_provenance=provenance())

    def test_policy_and_fingerprint_consumer_roundtrip_keep_partial_excluded(self):
        w,row=observation()
        # Even an unrelated alignment or fabricated complete-check set cannot promote a partial record.
        row['field_judgments']={key:dict(resolved=True,probability=1) for key in e.REQUIRED_CHECKS}
        row['alignment']=dict(meaning='must never be consumed')
        for policy in (e.EvidencePolicy(),e.EvidencePolicy(require_production_admission=True)):
            self.assertFalse(policy.permits(row)[0])
        accepted,excluded=e.EvidenceView((row,)).partition()
        self.assertFalse(accepted);self.assertEqual(excluded[0]['reason'],'partial_observation')
        with TemporaryDirectory() as folder:
            store=e.EvidenceArtifactStore(Path(folder));ref=store.write_immutable('observations.json',[row]);loaded=store.read_exact('observations.json',ref['sha256'])
            sample=e.SampleSpec(w.profile_id,(w.video_id,),'synthetic')
            fp=f.build_fingerprint(sample,e.EvidenceView(tuple(loaded)))
            self.assertFalse(fp['claim_frames']);self.assertFalse(fp['evidence_relations'])
            self.assertEqual(fp['evidence_observations'],loaded)
            self.assertEqual(fp['missingness']['unaligned'][0]['reason'],'partial_observation')
            self.assertFalse(any(fp['features'].values()))
            self.assertEqual(fp,f.build_fingerprint(sample,e.EvidenceView(tuple(loaded+loaded))))
