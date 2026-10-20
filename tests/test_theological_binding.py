from copy import deepcopy
import unittest

from pastor_transcript_extractor import theological_binding as b
from pastor_transcript_extractor.binding_evidence import context_digest, text_digest
from pastor_transcript_extractor.assurance_binding_adapter import interpret


def fixture(text='God creates the world.'):
    texts = dict(target_text=text, leading_context='', trailing_context='')
    span = dict(source_field='target_text', start=0, end=len(text), text=text)
    finding = lambda **kw: dict(evidence=[deepcopy(span)], rationale='Direct source-reviewed statement.', **kw)
    row = dict(binding_id='reading', title='A theological statement',
        proposition=dict(node_id='claim', span=span, reading=text),
        voice=finding(kind='preacher', speaker='preacher', occurrence='actual'),
        adoption=finding(status='own_assertion', basis='own_speech'),
        polarity=finding(value='affirmed'), expression=finding(value='assertion'),
        epistemic_status=finding(value='not_stated'), conditions=[],
        scope=dict(reading='Local statement only.', evidence=[span]),
        evidence_nodes=[dict(node_id='claim', span=span, role='teaching_statement', voice='preacher', adoption='own_assertion', reference_status='No external attribution verified')],
        qualifications=[], development_relations=[], address_acts=[],
        unknowns=['No ministry-wide conclusion established.'])
    provenance=dict(case_id='control', source_sha256='source', target_sha256=text_digest(text), texts_sha256=context_digest(texts))
    return texts, row, provenance


class GenericBindingTests(unittest.TestCase):
    def test_theology_needs_no_subject_predicate_and_inputs_are_immutable(self):
        inputs=fixture(); before=deepcopy(inputs)
        result=b.bind(*inputs)
        self.assertEqual(before,inputs)
        self.assertEqual('God creates the world.',result['proposition']['reading'])
        self.assertNotIn('subject_id',result); self.assertNotIn('relation',result)
        self.assertFalse(result['automatic_binding'])

    def test_foreign_stale_or_context_only_semantics_fail_closed(self):
        for field in ('source','span','frame','claim'):
            texts,row,provenance=fixture()
            if field=='source': texts['target_text']+='Changed'
            elif field=='span': row['proposition']['span']['text']='Fabricated'
            else:
                texts['leading_context']=texts['target_text'];provenance['texts_sha256']=context_digest(texts)
                if field=='claim': row['proposition']['span']['source_field']='leading_context'
                else: row['adoption']['evidence'][0]['source_field']='leading_context'
            with self.assertRaises(ValueError): b.bind(texts,row,provenance)

    def test_quote_alone_is_not_adopted_but_affirmative_use_can_be(self):
        texts,row,provenance=fixture('Paul said: God creates. That teaches us to trust God.')
        quote=dict(source_field='target_text',start=11,end=23,text='God creates.')
        row['proposition']['span']=quote;row['evidence_nodes'][0]['span']=quote
        row['voice'].update(kind='quoted_or_reported',speaker='Paul')
        row['adoption'].update(status='adopted',basis='quotation_only')
        with self.assertRaisesRegex(ValueError,'Quotation alone'):b.bind(texts,row,provenance)
        row['adoption']['basis']='discourse_use';row['adoption']['evidence']=[quote]
        with self.assertRaisesRegex(ValueError,'beyond quotation'):b.bind(texts,row,provenance)
        row['adoption']['evidence']=[dict(source_field='target_text',start=24,end=len(texts['target_text']),text=texts['target_text'][24:])]
        self.assertEqual('adopted',b.bind(texts,row,provenance)['adoption']['status'])

    def test_projected_assertion_and_actual_question_are_independent(self):
        texts,row,provenance=fixture('Can you say God forgives me?')
        row['voice'].update(kind='quoted_or_reported',speaker='invited listener',occurrence='projected')
        row['adoption'].update(status='undetermined',basis='unresolved')
        result=b.bind(texts,row,provenance)
        self.assertEqual('assertion',result['expression']['value'])
        self.assertEqual('projected',result['voice']['occurrence'])
        row['adoption'].update(status='own_assertion',basis='own_speech')
        with self.assertRaisesRegex(ValueError,'actual preacher'):b.bind(texts,row,provenance)
        texts,row,provenance=fixture('Can you trust God?');row['expression']['value']='question';row['polarity']['value']='unresolved';row['adoption'].update(status='undetermined',basis='unresolved')
        self.assertEqual('not_stated',b.bind(texts,row,provenance)['epistemic_status']['value'])

    def test_conditions_exceptions_and_uncertainty_need_their_own_evidence(self):
        texts,row,provenance=fixture('Perhaps we remain, if we trust, unless we turn away.')
        row['conditions']=[dict(kind='condition',span=row['proposition']['span'],rationale='Authored conditional control.'),dict(kind='exception',span=row['proposition']['span'],rationale='Authored exception control.')]
        row['epistemic_status']['value']='expressed_uncertainty'
        self.assertEqual(2,len(b.bind(texts,row,provenance)['conditions']))
        row['epistemic_status']['evidence']=[]
        with self.assertRaisesRegex(ValueError,'exact evidence'):b.bind(texts,row,provenance)
        row['epistemic_status']['evidence']=[row['proposition']['span']];row['conditions'][0]['kind']='concession'
        with self.assertRaisesRegex(ValueError,'cannot be widened'):b.bind(texts,row,provenance)

    def test_rejection_never_synthesizes_opposite_or_changes_literal_polarity(self):
        texts,row,provenance=fixture('Some say God abandons everyone. I reject that.')
        row['voice'].update(kind='quoted_or_reported',speaker='some');row['adoption'].update(status='rejected',basis='explicit_rejection')
        result=b.bind(texts,row,provenance)
        self.assertEqual('affirmed',result['polarity']['value'])
        self.assertEqual('rejected',result['adoption']['status'])
        self.assertNotIn('opposite',result)

    def test_assurance_positive_control_still_composes_atop_binding(self):
        from test_profile_binding_pilot import row as legacy_row, TEXT
        texts,row,provenance=fixture(TEXT)
        generic=b.bind(texts,row,provenance)
        result=interpret(generic,texts,legacy_row())
        self.assertEqual('matched',result['mapping_status'])
        self.assertTrue(result['g1_record']['provisional_adopted_local_assertion'])
        self.assertEqual('acceptance_knowable_now',result['g1_record']['relation'])
        changed=legacy_row();changed['unit']['candidate_id']='other'
        with self.assertRaisesRegex(ValueError,'exact bound proposition'):interpret(generic,texts,changed)

    def test_development_relations_require_grounded_endpoints_and_relation_evidence(self):
        texts,row,provenance=fixture()
        relation=dict(relation_id='r',kind='reason_supports_claim',from_node='missing',to_node='claim',status='supported_observation',rationale='Authored reason.',evidence=[])
        row['development_relations']=[relation]
        with self.assertRaisesRegex(ValueError,'endpoints'):b.bind(texts,row,provenance)
        relation['from_node']='claim'
        with self.assertRaisesRegex(ValueError,'Co-occurrence'):b.bind(texts,row,provenance)
