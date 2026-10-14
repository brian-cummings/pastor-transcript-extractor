"""Frozen artifact and synthetic mocked refinement checks; no provider validation."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from pastor_transcript_extractor import sermon_g2_feasibility_revision as v2
from pastor_transcript_extractor import sermon_g2_feasibility_review as v1


class FakeProvider:
    def assess(self,state,inventory):
        answers={}
        for key,q in inventory.items():
            selected='preacher' if key.endswith('_voice') else 'own_or_adopted' if key.endswith('_adoption') else 'local_sufficient' if key.endswith('_boundary') else 'not_linked'
            answers[key]={'choice':selected,'probabilities':{k:float(k==selected) for k in q['criteria']},'confidence':1.0}
        return {'answers':answers,'resolved_model':v1.MODEL,'usage':{}}


class G2RevisionTests(unittest.TestCase):
    def test_every_mismatch_and_positive_cell_is_adjudicated(self):
        report=v2.audit()
        self.assertEqual(len(report['mismatches']),10)
        self.assertEqual(len(report['positive_cell_review']),15)
        self.assertEqual({m['bucket'] for m in report['mismatches']},{'A','B','C'})

    def test_all_frozen_sources_and_pairs_retained_and_required_targets_covered(self):
        base,_,_=v2.load_baseline();revision=v2.prepare()
        cases={c['case_id']:c for c in revision['cases']}
        for original in base['cases']:
            updated=cases[original['case_id']]
            for field in ('target_text','leading_context','trailing_context','candidate_focus'):
                self.assertEqual(original[field],updated[field])
            self.assertEqual(updated['pairs'][:len(original['pairs'])],original['pairs'])
        self.assertEqual(len(revision['cases']),21)
        self.assertTrue(all(t['matching_pair_ids'] for c in revision['cases'] for t in c['review_targets']))

    def test_only_semantically_identical_state_and_questions_reused(self):
        base,_,rows=v2.load_baseline();c=base['cases'][0];pair=c['pairs'][0]
        self.assertEqual(set(v2.reusable(c,pair,rows)),{'explains_text','addresses_response_obstacle','boundary'})
        changed=deepcopy(c);changed['leading_context']='Changed reference context'
        self.assertEqual(v2.reusable(changed,pair,rows),{})

    def test_serialization_epsilon_preserves_probability_and_threshold(self):
        q={'p0_explains_text':v2.questions()['p0_explains_text']}
        a={'p0_explains_text':{'choice':'not_linked','probabilities':{'linked':0.,'not_linked':.94,'unclear':.05,'incomplete':0.}}}
        v2.validate_answers(a,q)
        self.assertAlmostEqual(sum(a['p0_explains_text']['probabilities'].values()),.99)
        a['p0_explains_text']['probabilities']['not_linked']=.93
        with self.assertRaisesRegex(ValueError,'Malformed'):
            v2.validate_answers(a,q)
        self.assertEqual(v1.THRESHOLD,.80)

    def test_refinement_cache_hits_do_not_construct_provider(self):
        pairs,_=v1.candidates('An assertion. A different assertion.')
        c={'case_id':'synthetic','origin':'authored','target_text':'An assertion. A different assertion.','leading_context':'','trailing_context':'','pairs':pairs,'review_targets':[],'case_check':None}
        packet={'cases':[c],'model':v1.MODEL,'question_digest':v1.fp(v2.questions()),'content_fingerprint':'synthetic-only','budget':{'maximum_uncached_requests':4}}
        with tempfile.TemporaryDirectory() as directory, patch.object(v2,'validate_packet'), patch.object(v2,'load_baseline',return_value=(None,None,{})):
            first=v2.evaluate(packet,provider_factory=FakeProvider,cache_dir=Path(directory))
            def forbidden():raise AssertionError('No client on all-hit cache replay')
            second=v2.evaluate(packet,provider_factory=forbidden,cache_dir=Path(directory))
            self.assertGreater(first['execution']['provider_requests'],0)
            self.assertEqual(second['execution']['provider_requests'],0)
            self.assertGreater(second['execution']['V2_cache_hits'],0)
            for a,b in zip(first['cases'][0]['rows'],second['cases'][0]['rows']):
                self.assertEqual(a['raw_answers'],b['raw_answers'])
                self.assertEqual(a['decisions'],b['decisions'])


if __name__=='__main__':unittest.main()
