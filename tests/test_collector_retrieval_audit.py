"""Read-only legacy-output verification; no encoder, model or real-source run."""
from pathlib import Path
import tempfile
import json
import unittest
from pastor_transcript_extractor import collector_retrieval_audit as audit


class LegacySealTests(unittest.TestCase):
    def test_original_integer_key_preimage_reproduces_without_rewriting(self):
        original=audit.workflow.prep.seal(dict(collection=dict(lattice_diagnostics=dict(per_unit_saturation={2:1,10:3})),other='unchanged'))
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'source.json';path.write_text(json.dumps(original))
            before=path.read_bytes()
            with self.assertRaises(ValueError):audit.workflow.design.sealed(path)
            checked=audit.original_output_seal(path)
            self.assertEqual(original['content_fingerprint'],checked['content_fingerprint'])
            self.assertEqual(before,path.read_bytes())
            changed=json.loads(before);changed['other']='corrupted';path.write_text(json.dumps(changed))
            with self.assertRaises(ValueError):audit.original_output_seal(path)

    def test_unknown_shape_or_noncanonical_numeric_key_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'output.json'
            for value in ({'content_fingerprint':'invalid'}, {'collection':{'lattice_diagnostics':{'per_unit_saturation':{'02':1}}}}):
                path.write_text(json.dumps(value))
                with self.assertRaises(ValueError):audit.original_output_seal(path)


class TargetBindingTests(unittest.TestCase):
    def fixture(self):
        span=dict(start=0,end=5,text='Trust')
        roles=dict(utterance=span,circumstance=None)
        entry=dict(candidate=dict(candidate_id='natural',endpoints=roles),automatic_envelope=dict(start=0,end=5))
        natural=dict(inventories=[dict(video_id=999,entries=[entry],G3_displacements=[])])
        result=dict(historical_exact_target_diagnostics=[dict(reference_id='r',role_containment_hits=['natural'],required_evidence_coverage_hits=['natural'])])
        refs=dict(rows=[dict(reference_id='r')],controls=[])
        review=dict(historical_case_reviews=[dict(reference_id='r',candidate_id='natural',source_compatible_supply=True,target_status='source_supported_compatible',target_roles=roles,envelope_span=dict(start=0,end=5))],P1_annotations=[dict(candidate_ids=['natural'],historical_score_change=False,exact_target_roles=roles,envelope_span=dict(start=0,end=5),annotation_is_new_gold=False,no_manual_narrowing=True)],G3_quota_displacement_reviews=[],controls=[])
        return review,result,natural,refs

    def test_P1_quality_annotation_cannot_replace_the_natural_target(self):
        values=self.fixture();audit.validate_cases(*values)
        values[0]['P1_annotations'][0]['exact_target_roles']={}
        with self.assertRaises(ValueError):audit.validate_cases(*values)

    def test_missing_required_evidence_cannot_become_compatible_supply(self):
        values=self.fixture();values[1]['historical_exact_target_diagnostics'][0]['required_evidence_coverage_hits']=[]
        with self.assertRaises(ValueError):audit.validate_cases(*values)
