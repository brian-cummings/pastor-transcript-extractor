from copy import deepcopy
import unittest

from pastor_transcript_extractor import automatic_proposition_binding as a
from pastor_transcript_extractor.binding_evidence import context_digest,text_digest


def fixture(text='God creates the world. Trust him.'):
    texts=dict(target_text=text,leading_context='',trailing_context='')
    units=a.source_units(texts);unit=units[0];pool=a.evidence_pool(texts,units,unit)
    q=a.field_questions(texts,unit,pool)
    d={key:'none' if 'none' in value['criteria'] else 'unresolved' for key,value in q.items()}
    d.update(voice='preacher',speaker='preacher',occurrence='actual',adoption='own_assertion',basis='own_speech',polarity='affirmed',expression='assertion',uncertainty='not_stated',voice_evidence='e0',adoption_evidence='e0',condition_kind='none',relation='none',address='none',addressee='no_address',address_voice='preacher',address_adoption='own_or_adopted')
    provenance=dict(case_id='control',source_sha256='source',target_sha256=text_digest(text),texts_sha256=context_digest(texts))
    return texts,unit,pool,d,provenance


class AutomaticBindingTests(unittest.TestCase):
    def test_outer_multi_sentence_quote_remains_one_act_and_inner_words_stay_literal(self):
        text='Can you say, "I trust him. He cares for me." We continue.'
        units=a.source_units(dict(target_text=text,leading_context='',trailing_context=''))
        outer=next(u for u in units if u['span']['text'].startswith('Can you'))
        inner=next(u for u in units if u['origin']=='embedded_quote')
        self.assertEqual('Can you say, "I trust him. He cares for me."',outer['span']['text'])
        self.assertEqual('contains_quotation',outer['speech_layer'])
        self.assertEqual('inside_quotation',inner['speech_layer'])
        self.assertEqual(outer['span'],inner['outer_frame'])
        self.assertNotIn('occurrence',inner)

    def test_discovery_keeps_relevance_separate_from_boundary_and_overlap(self):
        units=a.source_units(dict(target_text='She said, "God hears us."',leading_context='',trailing_context=''))
        decisions={u['candidate_id']:'include' for u in units}
        decisions.update({u['candidate_id']+'__boundary':'complete' for u in units})
        self.assertEqual(units,a.included_units(units,decisions))
        decisions[units[0]['candidate_id']+'__boundary']='mixed_or_fragment'
        self.assertNotIn(units[0],a.included_units(units,decisions))

    def test_speaker_options_require_a_speech_attribution_and_stages_are_disjoint(self):
        texts,unit,pool,_,_=fixture('And Miriam said, "God creates the world."')
        frame=a.field_questions(texts,unit,pool,stage='frame')
        self.assertIn('Miriam',frame['speaker']['criteria']);self.assertNotIn('God',frame['speaker']['criteria'])
        self.assertNotIn('And Miriam',frame['speaker']['criteria'])
        dependent=a.field_questions(texts,unit,pool,stage='interpretation')
        self.assertFalse(set(frame)&set(dependent))
        self.assertEqual(set(a.field_questions(texts,unit,pool)),set(frame)|set(dependent))
        self.assertIn('frame_selection',dependent['adoption']['instructions']['task'])

    def test_unresolved_links_remain_visible_beyond_empty_lists(self):
        texts,unit,pool,d,p=fixture();d.update(relation='unresolved',qualification='unresolved',address='unresolved')
        result=a.compose(texts,unit,pool,d,p)
        self.assertEqual([],result['qualifications'])
        for field in ('qualification','relation','address'):
            self.assertTrue(any(s.startswith(field+': unresolved;') for s in result['unknowns']))

    def test_source_only_units_preserve_outer_and_embedded_speech(self):
        texts=dict(target_text='Can you say, "God forgives me." He said, "I trust God."',leading_context='God rejects me.',trailing_context='')
        units=a.source_units(texts)
        self.assertTrue(any(u['span']['text']=='God forgives me.' for u in units))
        self.assertTrue(any(u['span']['text'].startswith('Can you say') for u in units))
        self.assertFalse(any('rejects' in u['span']['text'] for u in units))
        for u in units:self.assertEqual(texts['target_text'][u['span']['start']:u['span']['end']],u['span']['text'])

    def test_generated_binding_has_correct_authorship_and_no_accepted_projection(self):
        inputs=fixture();before=deepcopy(inputs);result=a.compose(*inputs)
        self.assertEqual(before,inputs);self.assertTrue(result['automatic_binding'])
        self.assertFalse(result['accepted_observation']);self.assertIn('not source-reviewed',result['authorship'])
        self.assertNotIn('subject_id',result);self.assertEqual(inputs[1]['span']['text'],result['proposition']['reading'])

    def test_quote_only_cannot_be_promoted_and_conflicting_answers_are_withheld(self):
        texts,unit,pool,d,provenance=fixture();d.update(adoption='adopted',basis='quotation_only')
        result=a.compose(texts,unit,pool,d,provenance)
        self.assertEqual('undetermined',result['adoption']['status']);self.assertIn('adoption_frame_insufficient',result['diagnostics'])
        d.update(adoption='own_assertion',basis='own_speech',occurrence='projected',voice='quoted_or_reported',speaker='invited_listener')
        self.assertEqual('undetermined',a.compose(texts,unit,pool,d,provenance)['adoption']['status'])

    def test_act_adoption_is_independent_of_proposition_adoption(self):
        texts,unit,pool,d,provenance=fixture('Can you trust God?')
        d.update(adoption='undetermined',basis='unresolved',expression='question',polarity='unresolved',address='invitation',addressee='direct_current_listener',address_evidence='e0')
        result=a.compose(texts,unit,pool,d,provenance)
        self.assertEqual('undetermined',result['adoption']['status'])
        self.assertEqual('own_or_adopted',result['address_acts'][0]['adoption'])
        self.assertEqual('not_stated',result['epistemic_status']['value'])

    def test_missing_uncertainty_or_relation_evidence_withholds_not_invents(self):
        texts,unit,pool,d,provenance=fixture();d.update(uncertainty='expressed_uncertainty',uncertainty_evidence='none',relation='reason_supports_claim',relation_endpoint='none')
        result=a.compose(texts,unit,pool,d,provenance)
        self.assertEqual('unresolved',result['epistemic_status']['value']);self.assertEqual([],result['development_relations'])

    def test_low_probability_is_analyst_withholding_and_vocabulary_is_checked(self):
        inventory=dict(field=a.question('Task',dict(yes='yes',no='no',unresolved='unknown')))
        raw=dict(answers={'field':dict(choice='yes',probabilities=dict(yes=.6,no=.3,unresolved=.1))})
        d,withheld=a.choices(raw,inventory);self.assertEqual('unresolved',d['field']);self.assertEqual(['field'],withheld)
        raw['answers']['field']['probabilities']['opposite']=0
        with self.assertRaises(ValueError):a.choices(raw,inventory)
