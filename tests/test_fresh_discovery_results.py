"""Focused matcher/denominator checks; no corpus or provider work."""
import unittest
from pastor_transcript_extractor import fresh_discovery_results as r


class MatcherTests(unittest.TestCase):
    def test_small_source_denominators_are_diagnostic(self):
        for n in range(5):
            self.assertEqual('DIAGNOSTIC_ONLY',r.source_gate(0,n))
        self.assertEqual('FAIL',r.source_gate(3,5))
        self.assertEqual('PASS',r.source_gate(4,5))
        self.assertEqual('PASS',r.source_gate(8,10))

    def test_only_full_roles_not_overlap_are_discovery_matches(self):
        ref=dict(capability='G3',roles=dict(utterance=dict(start=10,end=30)),equivalent_role_occurrences=dict(utterance=[dict(start=10,end=30)]))
        e=dict(candidate=dict(capability='G3',endpoints=dict(utterance=dict(start=9,end=29))))
        self.assertFalse(r.geometric_match(ref,e))
        e['candidate']['endpoints']['utterance']['end']=30
        self.assertTrue(r.geometric_match(ref,e))

    def test_G1_condition_cannot_be_borrowed_from_leading_context(self):
        ref=dict(capability='G1',roles=dict(claim=dict(start=20,end=30)),equivalent_role_occurrences=dict(claim=[dict(start=20,end=30)]),required_target_framing=[dict(start=10,end=30)])
        e=dict(candidate=dict(capability='G1',claim=dict(start=20,end=30),target=dict(start=20,end=30)))
        self.assertFalse(r.geometric_match(ref,e))
        e['candidate']['target']['start']=10
        self.assertTrue(r.geometric_match(ref,e))

    def test_G2_direction_cannot_be_reversed(self):
        ref=dict(capability='G2',roles=dict(left=dict(start=0,end=5),right=dict(start=10,end=15)),equivalent_role_occurrences=dict(left=[dict(start=0,end=5)],right=[dict(start=10,end=15)]))
        e=dict(candidate=dict(capability='G2',endpoints=dict(left=dict(start=10,end=15),right=dict(start=0,end=5))))
        self.assertFalse(r.geometric_match(ref,e))

    def test_manual_context_rescue_does_not_count_as_automatic_coverage(self):
        ref=dict(required_source_evidence_spans=[dict(start=0,end=5)])
        e=dict(candidate=dict(capability='G3'),automatic_envelope=dict(status='prepared_not_attested',start=10,end=30))
        self.assertFalse(r.coverage(ref,e))

    def test_distinct_exact_alias_is_not_a_new_opportunity(self):
        ref=dict(capability='G3',roles=dict(utterance=dict(start=10,end=20)),equivalent_role_occurrences=dict(utterance=[dict(start=10,end=20),dict(start=30,end=40)]))
        e=dict(candidate=dict(capability='G3',endpoints=dict(utterance=dict(start=30,end=40))))
        self.assertTrue(r.geometric_match(ref,e))
