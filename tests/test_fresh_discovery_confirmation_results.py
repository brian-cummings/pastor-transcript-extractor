"""Synthetic route/format-loss tests, no Fresh V2 source evaluation."""
import unittest
from pastor_transcript_extractor import fresh_discovery_confirmation_results as r

CRITERIA=dict(aggregate_floors=dict(G1_assurance=5,G2_explanation=10,G3_current=5,G3_reported=3),aggregate_recall=.8,aggregate_sufficient_envelope_recall=.8,per_source_recall=.8,per_source_minimum=5)

def row(i,vid,hit,enough=True):
 return dict(reference_id=str(i),video_id=vid,route='G2_explanation',classification='definite_compatible_opportunity',role_containment_hits=['hit'] if hit else [],required_evidence_coverage_hits=['hit'] if hit and enough else [])

class ConfirmationResultTests(unittest.TestCase):
 def test_small_cells_diagnostic_aggregate_still_applies(self):
  rows=[row(i,i//4,True) for i in range(12)]
  s=r.route_statistics(rows,[0,1,2],CRITERIA)['G2_explanation']
  self.assertEqual('PENDING_TARGET_ENVELOPE_AUDIT',s['decision'])
  self.assertTrue(all(x['gate']=='DIAGNOSTIC_ONLY' for x in s['per_source'].values()))
 def test_populated_source_can_fail_even_if_aggregate_passes(self):
  rows=[row(i,0,i<3) for i in range(5)]+[row(5+i,1,True) for i in range(15)]
  self.assertEqual('FAIL',r.route_statistics(rows,[0,1],CRITERIA)['G2_explanation']['decision'])
 def test_required_source_coverage_is_not_conflated_with_role_hits(self):
  rows=[row(i,0,True,i<7) for i in range(10)]
  s=r.route_statistics(rows,[0],CRITERIA)['G2_explanation']
  self.assertEqual(10,s['complete_role_upper_bound_hits']);self.assertEqual(7,s['required_evidence_upper_bound_hits']);self.assertEqual('FAIL',s['decision'])
 def test_absent_G1_is_hold(self):
  self.assertEqual('HOLD',r.route_statistics([],[],CRITERIA)['G1_assurance']['decision'])
 def test_long_unit_failure_is_not_unavailable_source_or_model_error(self):
  text='Read this book '+('unpunctuated words '*400)+' and respond'
  source=dict(video_id=9000,text=text,main_span=dict(start=0,end=len(text)))
  span=dict(start=0,end=14,text=text[:14]);ref=dict(capability='G3',roles=dict(utterance=span))
  diagnostic=r.miss_diagnostic(ref,[],source,[dict(start=0,end=len(text),text=text)],[],[])
  self.assertEqual('oversize_punctuation_unit_prevents_bounded_role_materialization',diagnostic['cause'])
  self.assertEqual('represented',diagnostic['authored_geometry_status'])
  self.assertEqual(0,diagnostic['manual_rescue_discovery_credit'])
