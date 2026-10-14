from copy import deepcopy
import tempfile
from pathlib import Path
import unittest

from pastor_transcript_extractor import sermon_g3_feasibility_review as g3


class G3ProposalTests(unittest.TestCase):
    def test_grounding_inventory_and_state_exclude_expectations(self):
        packet = g3.prepare()
        g3.validate_packet(packet)
        self.assertEqual(21, len(packet['cases']))
        self.assertEqual(27, packet['budget']['provider_request_ceiling'])
        self.assertEqual(324, packet['budget']['question_count'])
        for c in packet['cases']:
            for p in c['candidates']:
                state = g3.state_for(c, p)
                self.assertEqual({'target_text', 'leading_context', 'trailing_context', 'candidate'}, set(state))
                self.assertEqual({'circumstance', 'utterance'}, set(state['candidate']))
        changed = deepcopy(packet)
        changed['cases'][0]['candidates'][0]['utterance']['start'] += 1
        with self.assertRaises(ValueError):
            g3.validate_packet(changed)

    def test_framing_gates_do_not_promote_report_prayer_or_proximity(self):
        decisions = {a: 'observed' for a in g3.ACTS}
        decisions.update(binding='bound_in_target', addressee='direct_current_listener', adoption='own_or_adopted', boundary='local_sufficient')
        self.assertEqual(list(g3.ACTS), g3.provisional(decisions))
        for key, value in [('binding', 'not_bound'), ('addressee', 'God'), ('addressee', 'reported_person'), ('adoption', 'not_adopted_report'), ('adoption', 'explicitly_rejected'), ('boundary', 'continuation_required')]:
            with self.subTest(field=key, value=value):
                self.assertEqual([], g3.provisional({**decisions, key: value}))
        self.assertEqual('unclear', g3.decision({'choice': 'observed', 'probabilities': {'observed': .79}}))

    def test_exact_state_cache_and_wrong_model_never_cached(self):
        class Fake:
            calls = 0
            def assess(self, state, inventory):
                Fake.calls += 1
                answers = {}
                for field, q in inventory.items():
                    option = 'not_observed' if field in g3.ACTS else next(iter(q['criteria']))
                    answers[field] = {'choice': option, 'probabilities': {k: float(k == option) for k in q['criteria']}}
                return {'answers': answers, 'resolved_model': g3.MODEL}
        packet = g3.prepare()
        with tempfile.TemporaryDirectory() as folder:
            cache = Path(folder)
            first = g3.evaluate(packet, provider_factory=Fake, cache_dir=cache)
            self.assertEqual(27, first['execution']['provider_requests'])
            second = g3.evaluate(packet, provider_factory=lambda: self.fail('all cache hits should not create provider'), cache_dir=cache)
            self.assertEqual({'provider_requests': 0, 'cache_hits': 27}, second['execution'])
            self.assertEqual(27, Fake.calls)
        class WrongModel(Fake):
            def assess(self, state, inventory):
                return {**super().assess(state, inventory), 'resolved_model': 'wrong'}
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ValueError):
                g3.evaluate(packet, provider_factory=WrongModel, cache_dir=Path(folder))
            self.assertEqual([], list(Path(folder).glob('*.json')))

    def test_all_positive_acts_remain_visible_beyond_expected_labels(self):
        # Diagnostic rendering exposes every facet even when no gold label was authored.
        packet = g3.prepare()
        c = packet['cases'][0]; candidate = c['candidates'][0]
        text = g3.render_results({'status': 'pending', 'input_fingerprint': 'mock', 'execution': {}, 'rows': [{
            'case_id': c['case_id'], 'candidate_id': candidate['candidate_id'],
            'candidate': {}, 'review_reason': 'mock', 'decisions': {'warning': 'observed'},
            'provisional_current_listener_acts': ['warning'], 'checks': []
        }]}, packet)
        self.assertIn('"warning": "observed"', text)
