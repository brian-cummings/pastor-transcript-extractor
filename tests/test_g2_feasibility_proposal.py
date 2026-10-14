"""Inexpensive synthetic/mocked harness checks; never provider or dataset validation."""
from pathlib import Path
import runpy
import tempfile
import unittest
from unittest.mock import patch

MODULE = runpy.run_path(str(Path(__file__).resolve().parents[1] / "docs/review-proposals/g2-feasibility-v1/experiment.py"))
G = MODULE['evaluate'].__globals__


class FakeProvider:
    def __init__(self):
        self.calls = 0

    def assess(self, state, inventory):
        self.calls += 1
        answers = {}
        for key, question in inventory.items():
            chosen = 'reported' if key.endswith('_adoption') else 'local_sufficient' if key.endswith('_boundary') else 'not_linked'
            answers[key] = {'choice':chosen, 'probabilities':{k:float(k==chosen) for k in question['criteria']}, 'confidence':1.0}
        return {'answers':answers, 'resolved_model':MODULE['MODEL'], 'usage':{}}


def synthetic_packet():
    pairs,_=MODULE['candidates']('One assertion. Another assertion. A third assertion.')
    return {'model':MODULE['MODEL'], 'question_digest':MODULE['fp'](MODULE['questions']()),
            'content_fingerprint':'synthetic-unit-input', 'budget':{'provider_request_ceiling':10},
            'cases':[{'case_id':'unit-only','origin':'authored','target_text':'One assertion. Another assertion. A third assertion.',
                      'leading_context':'','trailing_context':'','review_targets':[],'case_check':None,'pairs':pairs}]}


class G2FeasibilityProposalTests(unittest.TestCase):
    def test_candidate_offsets_and_quote_boundary(self):
        text="A text says, 'Weep.' This explains that text."
        pairs,info=MODULE['candidates'](text)
        self.assertGreater(len(pairs),0)
        self.assertEqual(info['omitted_pairs'],0)
        for pair in pairs:
            for field in ('left','right'):
                span=pair[field]
                self.assertEqual(span['text'],text[span['start']:span['end']])
        self.assertTrue(any(p['left']['text'].endswith("Weep.'") for p in pairs))

    def test_no_gold_or_old_probabilities_in_provider_state(self):
        c=synthetic_packet()['cases'][0]
        c.update(review_targets=[{'expected':'linked'}],old_probability=.99,pastor_name='not sent')
        state=MODULE['state_for'](c,c['pairs'])
        self.assertEqual(set(state),{'target_text','leading_context','trailing_context','pairs'})

    def test_bad_choice_inventory_and_probability_rejected(self):
        inventory=MODULE['questions']()
        raw=FakeProvider().assess({},inventory)['answers']
        raw.pop(next(iter(raw)))
        with self.assertRaisesRegex(ValueError,'Incomplete'):
            MODULE['validate_answers'](raw,inventory)
        raw=FakeProvider().assess({},inventory)['answers']
        raw['p0_explains_text']['probabilities']['linked']=float('nan')
        with self.assertRaisesRegex(ValueError,'Malformed'):
            MODULE['validate_answers'](raw,inventory)

    def test_uncertain_choice_does_not_create_link(self):
        answer={'choice':'linked','probabilities':{'linked':.79,'unclear':.21}}
        self.assertEqual(MODULE['decision'](answer),'unclear')

    def test_independent_pair_cache_survives_regrouping_no_client_on_hits(self):
        provider=FakeProvider()
        with tempfile.TemporaryDirectory() as directory, patch.dict(G,validate_packet=lambda p:None):
            cache=Path(directory)
            first=MODULE['evaluate'](synthetic_packet(),provider_factory=lambda:provider,cache_dir=cache)
            self.assertGreater(first['execution']['provider_requests'],0)
            with patch.dict(G,BATCH_PAIRS=1):
                def forbidden():
                    raise AssertionError('No provider construction on all-cache replay')
                second=MODULE['evaluate'](synthetic_packet(),provider_factory=forbidden,cache_dir=cache)
            self.assertEqual(second['execution']['provider_requests'],0)
            self.assertEqual(first['cases'],second['cases'])
            self.assertGreater(second['execution']['cache_hits'],0)

    def test_wrong_resolved_model_not_cached(self):
        class WrongModel(FakeProvider):
            def assess(self,state,inventory):
                result=super().assess(state,inventory);result['resolved_model']='other';return result
        with tempfile.TemporaryDirectory() as directory, patch.dict(G,validate_packet=lambda p:None):
            with self.assertRaisesRegex(ValueError,'pinned model'):
                MODULE['evaluate'](synthetic_packet(),provider_factory=WrongModel,cache_dir=Path(directory))
            self.assertEqual(list(Path(directory).iterdir()),[])

    def test_false_edge_cannot_hide_behind_correct_matching_candidate(self):
        c={'case_id':'unit','origin':'authored','case_check':None,'review_targets':[{'facet':'explains_text','expected':'not_linked','allowed_adoption':None,'matching_pair_ids':['one','two']}]}
        rows=[{'pair':{'pair_id':k},'decisions':{**{f:'not_linked' for f in MODULE['FACETS']},'explains_text':v,'adoption':'own_or_adopted','boundary':'local_sufficient'}} for k,v in [('one','not_linked'),('two','linked')]]
        result=MODULE['diagnose']({'cases':[c]},[{'case_id':'unit','rows':rows}])
        self.assertEqual(result['checks'][0]['status'],'false_semantic_edge')


if __name__=='__main__': unittest.main()
