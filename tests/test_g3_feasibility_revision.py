from copy import deepcopy
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from pastor_transcript_extractor import sermon_g3_feasibility_revision as v2


class G3RevisionTests(unittest.TestCase):
    def test_exact_subset_states_reuse_and_new_questions_only(self):
        original, result, rows = v2.load_baseline()
        packet = v2.prepare(); v2.validate_packet(packet)
        self.assertEqual(12, len(packet['cases']))
        self.assertEqual(24, packet['budget']['new_question_count'])
        self.assertEqual(132, packet['budget']['v1_answers_reused'])
        self.assertEqual({'circumstance_relevance', 'recipient_circumstance_binding'}, set(v2.questions()))
        for c in packet['cases']:
            p = c['candidates'][0]
            old = next(c0 for c0 in original['cases'] if c0['case_id'] == c['case_id'])
            oldp = next(p0 for p0 in old['candidates'] if p0['candidate_id'] == p['candidate_id'])
            self.assertEqual(v2.v1.state_for(old, oldp), v2.v1.state_for(c, p))
            self.assertEqual({f: rows[p['candidate_id']]['raw_answers'][f] for f in v2.REUSED_FIELDS}, p['reused_answers'])
            self.assertNotIn('binding', p['reused_answers'])
            state = v2.v1.state_for(c, p)
            self.assertNotIn('expected', str(state.keys()))
            self.assertEqual({'circumstance', 'utterance'}, set(state['candidate']))
        altered = deepcopy(packet); altered['cases'][0]['leading_context'] += ' changed'
        with self.assertRaises(ValueError):
            v2.validate_packet(altered)

    def test_relevance_alone_cannot_promote_prayer_report_or_wrong_person(self):
        d = {a: 'observed' for a in v2.v1.ACTS}
        d.update(circumstance_relevance='relevant_in_target', recipient_circumstance_binding='bound_in_target', addressee='direct_current_listener', adoption='own_or_adopted', boundary='local_sufficient')
        self.assertEqual(list(v2.v1.ACTS), v2.provisional(d))
        for change in [dict(recipient_circumstance_binding='not_bound', addressee='God'), dict(addressee='reported_person', adoption='not_adopted_report'), dict(circumstance_relevance='not_relevant'), dict(recipient_circumstance_binding='unclear')]:
            self.assertEqual([], v2.provisional({**d, **change}))
        self.assertEqual(list(v2.v1.ACTS), v2.provisional({**d, 'circumstance_relevance': 'relevant_context_resolved', 'recipient_circumstance_binding': 'bound_context_resolved'}))

    def test_mock_provider_asks_only_two_questions_and_reuses_cache(self):
        class Fake:
            def assess(self, state, inventory):
                if set(inventory) != set(v2.questions()):
                    raise AssertionError('Only new questions may be requested')
                return {'answers': {k: {'choice': 'unclear', 'probabilities': {o: float(o == 'unclear') for o in q['criteria']}} for k, q in inventory.items()}, 'resolved_model': v2.v1.MODEL}
        with tempfile.TemporaryDirectory() as folder:
            first = v2.evaluate(v2.prepare(), provider_factory=Fake, cache_dir=Path(folder))
            self.assertEqual({'provider_requests': 12, 'cache_hits': 0, 'v1_answers_reused': 132}, first['execution'])
            second = v2.evaluate(v2.prepare(), provider_factory=lambda: self.fail('No client on cache hit'), cache_dir=Path(folder))
            self.assertEqual(12, second['execution']['cache_hits'])
            self.assertEqual(0, second['execution']['provider_requests'])
            self.assertEqual(first['rows'][0]['reuse_provenance'], second['rows'][0]['reuse_provenance'])
        class Wrong(Fake):
            def assess(self, state, inventory):
                return {**super().assess(state, inventory), 'resolved_model': 'wrong'}
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ValueError):
                v2.evaluate(v2.prepare(), provider_factory=Wrong, cache_dir=Path(folder))
            self.assertEqual([], list(Path(folder).glob('*.json')))

    def test_baseline_provenance_failure_stops_revision(self):
        with patch.object(v2.v1, 'validate_packet', side_effect=ValueError('changed baseline')):
            with self.assertRaises(ValueError):
                v2.prepare()
