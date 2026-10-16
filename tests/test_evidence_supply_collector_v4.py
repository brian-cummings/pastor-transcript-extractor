"""Synthetic failure-class regressions, never the diagnostic sermon benchmark."""
import unittest
from copy import deepcopy
from pastor_transcript_extractor import evidence_supply_collector_v4 as c
from pastor_transcript_extractor import fresh_discovery_preparation as prep


def source(text,video_id=900010):
    return dict(video_id=video_id,text=text,main_span=dict(start=0,end=len(text)))


def supplied(collection,cap,**roles):
    def inside(actual,phrase):return actual is not None and phrase in actual['text']
    return [x for x in collection['candidates'] if x['capability']==cap and all(inside(x['endpoints'][k],v) for k,v in roles.items())]


class RecallMechanicsTests(unittest.TestCase):
    def test_unseen_imperatives_questions_and_reported_utterances_need_no_address_keyword(self):
        for utterance in ('Lift the curtain.','Remain awake.','How many baskets remain?','Travel onward.','Stand firm.'):
            result=c.discover(source('Miriam told the travelers: '+utterance+' The narrator watched.'))
            self.assertTrue(supplied(result,'G3',utterance=utterance),utterance)
            self.assertTrue(all(x['source_hypothesis_only'] for x in result['candidates']))

    def test_nonbiblical_and_narration_are_hypotheses_never_positive_evidence(self):
        s=source('A gardening manual says growth takes time. That means patience. She comforted the visitor.')
        result=c.discover(s)
        self.assertTrue(supplied(result,'G3',utterance='She comforted the visitor.'))
        self.assertTrue(supplied(result,'G2',left='A gardening manual says growth takes time.',right='That means patience.'))
        for x in result['candidates']:
            self.assertFalse(x['pastor_credit']);self.assertIsNone(x['semantic_truth'])
            self.assertFalse(x['automatic_provenance_attestation'])

    def test_biblical_language_does_not_need_a_book_number_or_known_spelling(self):
        result=c.discover(source('The letter of Fylimon calls the servant a sibling. That signifies shared dignity.'))
        self.assertTrue(supplied(result,'G2',left='The letter of Fylimon calls the servant a sibling.',right='That signifies shared dignity.'))

    def test_same_sentence_prefix_and_suffix_preserve_complete_predicates(self):
        text='The passage names them heirs, which meant the inheritance belonged to the whole household.'
        result=c.discover(source(text))
        hits=supplied(result,'G2',left='The passage names them heirs,',right='which meant the inheritance belonged to the whole household.')
        self.assertTrue(hits)
        self.assertLessEqual(hits[0]['endpoints']['left']['end'],hits[0]['endpoints']['right']['start'])

    def test_two_sentence_quote_and_two_sentence_gloss_remain_complete(self):
        text='Where is the treasure? In earthen vessels. This is the point. Frail people bear the gift.'
        result=c.discover(source(text))
        self.assertTrue(supplied(result,'G2',left='Where is the treasure? In earthen vessels.',right='This is the point. Frail people bear the gift.'))

    def test_nonlocal_gloss_is_not_discarded_for_a_four_sentence_horizon(self):
        text='The passage calls him a shepherd. First observation. Second observation. Third observation. Fourth observation. Fifth observation. This means faithful care.'
        result=c.discover(source(text))
        self.assertTrue(supplied(result,'G2',left='The passage calls him a shepherd.',right='This means faithful care.'))

    def test_abbreviation_does_not_clip_a_complete_target(self):
        text='We depend on status, possessions, etc. for our importance. Remain watchful.'
        nodes=c.source_sentences(source(text))
        self.assertEqual('We depend on status, possessions, etc. for our importance.',nodes[0]['text'])
        self.assertTrue(supplied(c.discover(source(text)),'G3',utterance=nodes[0]['text']))

    def test_conditional_question_answer_continuation_preserved_as_hypothesis(self):
        text='If the path is ignored, danger follows. And the danger is what? A steep ravine. It is hazardous.'
        result=c.discover(source(text))
        hits=supplied(result,'G3',utterance=text)
        self.assertTrue(hits)
        self.assertIn('requires_target_review',hits[0]['selection'])
        # A singleton remains separately available; no successful sibling lends acts.
        self.assertTrue(any(x['endpoints']['utterance']['text']=='If the path is ignored, danger follows.' for x in supplied(result,'G3',utterance='If the path is ignored, danger follows.')))

    def test_reporting_switch_stops_continuation(self):
        s=source('Will the traveler come? She replied that the bridge was closed. It was late.')
        nodes=c.source_sentences(s)
        self.assertIsNone(c.continuation(s,nodes,0))

    def test_G1_qualified_framing_uses_unchanged_pools(self):
        text='If trust is abandoned, the record is lost. Eternal life is not mechanically retained. As long as we abide, the promise stands.'
        s=source(text);result=c.discover(s)
        claim=next(x for x in result['G1_candidates'] if x['claim']['text']=='Eternal life is not mechanically retained.')
        self.assertEqual(text,claim['target']['text'])
        from pastor_transcript_extractor import sermon_g1_feasibility_review as g1
        _,pools=g1.candidates(dict(case_id='test',target_text=text,leading_context='',trailing_context=''))
        self.assertEqual(pools,claim['phrase_pools'])

    def test_source_only_determinism_and_unchanged_hard_limits(self):
        s=source('Lift the curtain. The letter promises life. This means renewed hope. How many lamps remain?')
        untouched=deepcopy(s);a=c.discover(s);b=c.discover(s)
        self.assertEqual(a,b);self.assertEqual(untouched,s)
        self.assertEqual(len({x['candidate_id'] for x in a['candidates']}),len(a['candidates']))
        self.assertLessEqual(len(a['candidates']),14*len(a['nodes']))
        small={**c.POLICY,'source_candidate_ceiling':1}
        with self.assertRaisesRegex(ValueError,'ceiling exceeded'):c.discover(s,small)

    def test_new_candidates_materialize_with_closed_phase_questions(self):
        s=source('The letter calls the promise an anchor. That means stability. Remain steady.')
        result=c.discover(s)
        for cap in ('G2','G3'):
            item=next(x for x in result['candidates'] if x['capability']==cap)
            envelope=prep.automatic_envelope(s,item)
            requests=prep.shapes(s,item,envelope)
            self.assertEqual(1 if cap=='G2' else 2,len(requests))
            if cap=='G3':
                self.assertEqual(item['endpoints']['utterance']['text'],requests[0]['state']['target_text'])
                from pastor_transcript_extractor.sermon_g3_feasibility_review import ACTS
                self.assertFalse(set(ACTS)&set(requests[1]['questions']))
