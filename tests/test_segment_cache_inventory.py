from copy import deepcopy
from pathlib import Path
import unittest
from unittest.mock import patch
from typer.testing import CliRunner
from pastor_transcript_extractor import segment_cache_inventory as m


def fixture():
    topic=dict(block_id=1,start_seconds=0,end_seconds=60,segment_indexes=[0],resolved_model_id=m.DEFAULT_TYPESAFE_MODEL,
        projection_eligibility={'eligible':True},context={'target_text':'A whole minute.'},
        scores={k:dict(score=0,probabilities={str(i):float(i==0) for i in range(5)}) for k in m.TOPIC_SPECS})
    analysis=dict(question_pack_version=m.TOPIC_PACK_VERSION,question_pack_digest=m.topic_pack_digest(),requested_model_id=m.DEFAULT_TYPESAFE_MODEL,blocks=[topic])
    sem=dict(question_version=m.SEMANTIC_ANALYSIS_QUESTION_VERSION,dimensions=list(m.SEMANTIC_DIMENSIONS),blocks=[
        {**{k:topic[k] for k in ('block_id','start_seconds','end_seconds','segment_indexes','resolved_model_id')},'probabilities':{k:0.2 for k in m.SEMANTIC_DIMENSIONS}}])
    s=m.salvation
    sal=dict(question_pack_version=s.SALVATION_RELATIONSHIPS_PACK_VERSION,question_pack_digest=s.salvation_relationship_pack_digest(),requested_model_id=m.DEFAULT_TYPESAFE_MODEL,
        observation_policy_version=s.SALVATION_RELATIONSHIP_OBSERVATION_POLICY_VERSION,observation_thresholds=s.SALVATION_RELATIONSHIP_OBSERVATION_THRESHOLDS,
        measurement_statuses=s.SALVATION_RELATIONSHIP_MEASUREMENT_STATUSES,route_policy_version=s.SALVATION_ROUTE_POLICY_VERSION,
        route_threshold=s.SALVATION_ROUTE_THRESHOLD,final_projection_reconciled=True,missing_current_routed_block_ids=[],blocks=[])
    return {'search':{'semantic_analysis':sem,'salvation_relationship_analysis':sal}},analysis


class CacheInventoryTests(unittest.TestCase):
    def test_no_salvation_route_is_unmeasured_not_negative(self):
        cl,a=fixture();x=m.compatible_layers(cl,a,[1])
        self.assertEqual([],x['salvation']);self.assertIsNone(x['salvation_reason'])
        self.assertEqual(1,len(x['treatment']));self.assertIn('listener_directives',x['absent_production_layers'])

    def test_changed_question_or_model_is_not_reused(self):
        cl,a=fixture();a['question_pack_digest']='changed'
        with self.assertRaises(ValueError):m.compatible_layers(cl,a,[1])
        cl,a=fixture();a['blocks'][0]['resolved_model_id']='another-model'
        with self.assertRaises(ValueError):m.compatible_layers(cl,a,[1])

    def test_same_block_id_with_changed_timing_does_not_reuse_treatment(self):
        cl,a=fixture();cl['search']['semantic_analysis']['blocks'][0]['end_seconds']=61
        x=m.compatible_layers(cl,a,[1]);self.assertEqual([],x['treatment']);self.assertIsNotNone(x['treatment_reason'])

    def test_missing_current_salvation_measurement_remains_a_gap(self):
        cl,a=fixture();a['blocks'][0]['scores']['salvation_gospel']['probabilities']={str(i):float(i==3) for i in range(5)}
        x=m.compatible_layers(cl,a,[1]);self.assertEqual([],x['salvation']);self.assertEqual('current_route_and_measured_inventory_differ',x['salvation_reason'])

    def test_unresolved_leaves_never_become_positive_observations(self):
        probs={k:float(k in m.salvation.UNRESOLVED_SALVATION_RELATIONSHIP_OBSERVATIONS) for k in m.salvation.SALVATION_RELATIONSHIPS}
        self.assertEqual((),m.salvation.collected_salvation_relationships(probs))

    def test_profile_selection_uses_coverage_not_answers(self):
        rows=[dict(status='compatible',profile_id=2,eligible_blocks=5,positive_answers=100),dict(status='compatible',profile_id=1,eligible_blocks=6,positive_answers=0)]
        self.assertEqual(1,m.select_profile(rows))

    def test_cli_read_only_check_cannot_prepare_or_run_model(self):
        from pastor_transcript_extractor.cli import app
        value=dict(status='inventory',content_fingerprint='test',selected_profile={'id':1},coverage={})
        with patch.object(m,'build',return_value=value),patch.object(m,'prepare',side_effect=AssertionError('No writes')):
            x=CliRunner().invoke(app,['analysis','structure-readiness','--segment-inventory','--check-only','--json'])
            self.assertEqual(0,x.exit_code,x.output)
        x=CliRunner().invoke(app,['analysis','structure-readiness','--segment-inventory','--run-selection'])
        self.assertEqual(2,x.exit_code)
