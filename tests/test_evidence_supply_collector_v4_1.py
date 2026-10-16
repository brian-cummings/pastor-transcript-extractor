"""Ceiling repair regressions; reuse frozen synthetic classes on the new module."""
from unittest.mock import patch
import json
import test_evidence_supply_collector_v4 as original
from pastor_transcript_extractor import evidence_supply_collector_v4_1 as repaired


class CeilingRepairTests(original.RecallMechanicsTests):
    def setUp(self):
        self.patch=patch.object(original,'c',repaired);self.patch.start();self.addCleanup(self.patch.stop)

    def test_dense_dialogue_stays_inside_ten_per_sentence_without_clipping(self):
        text=' '.join(f'Observation {i}. This means another possibility.' for i in range(40))
        source=original.source(text)
        policy={**repaired.POLICY,'source_candidate_ceiling':800}
        result=repaired.discover(source,policy)
        self.assertEqual(80,len(result['nodes']))
        self.assertEqual(800,result['budget_proof']['linear_candidate_bound'])
        self.assertLessEqual(len(result['candidates']),800)
        self.assertEqual(80,len([c for c in result['candidates'] if c['capability']=='G3' and c['selection']=='source_only_complete_sentence']))
        self.assertTrue(any(d['reason']=='asymmetric_boundary_variants_not_materialized' for d in result['search_diagnostics']))
        self.assertEqual(result,json.loads(json.dumps(result)))

    def test_maximal_local_pairs_contain_all_omitted_asymmetric_roles(self):
        source=original.source('A distinct opening. A second sentence. A third sentence. A closing remark.')
        nodes=repaired.source_sentences(source);result=repaired.discover(source)
        for i in range(len(nodes)-1):
            for left_width in range(1,min(2,i+1)+1):
                for right_width in range(1,min(2,len(nodes)-i-1)+1):
                    a=repaired.joined(source,nodes,i-left_width+1,i)['text']
                    b=repaired.joined(source,nodes,i+1,i+right_width)['text']
                    self.assertTrue(original.supplied(result,'G2',left=a,right=b))
                    self.assertTrue(original.supplied(result,'G2',left=b,right=a))

    def test_old_version_and_hard_ceilings_are_preserved(self):
        from pastor_transcript_extractor import evidence_supply_collector_v4 as old
        self.assertEqual(12,old.POLICY['G2_per_sentence_bound'])
        self.assertEqual(8,repaired.POLICY['G2_per_sentence_bound'])
        for key in ('source_candidate_ceiling','total_candidate_ceiling','G1_source_ceiling','max_frame_chars'):
            self.assertEqual(old.POLICY[key],repaired.POLICY[key])
