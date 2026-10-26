from copy import deepcopy
from dataclasses import replace
import unittest

from pastor_transcript_extractor import binding_feedback as f
from test_source_context import fixture


class BindingFeedbackTests(unittest.TestCase):
    def test_all_literal_matches_locations_and_contexts_without_selection_or_mutation(self):
        window,_,reading=fixture();quote='Repeat.'
        window=replace(window,blocks=({**window.blocks[0],'target_text':'Repeat. Middle. Repeat.'},))
        reading=deepcopy(reading);reading['claims'][0]['scope']['evidence']=[dict(source_field='target_text',text=quote)]
        errors=[dict(path='$.claims[0].scope.evidence[0]',code='literal',message='ambiguous')]
        original=deepcopy((reading,errors));result=f.enrich(errors,reading,window)
        facts=result[0]['mechanical_details'];text=window.target()[0]['target_text']
        self.assertEqual(facts['occurrence_count'],2);self.assertTrue(facts['exhaustive']);self.assertIsNone(facts['selected_match'])
        self.assertEqual([m['start'] for m in facts['matches']],[0,16])
        for match in facts['matches']:
            self.assertEqual(text[match['start']:match['end']],quote)
            self.assertEqual(text[match['context_start']:match['context_end']],match['context'])
            self.assertEqual(match['blocks'][0]['block_id'],window.blocks[0]['block_id'])
        self.assertEqual((reading,errors),original)

    def test_overlapping_missing_and_added_occurrences_are_exhaustive(self):
        window,_,reading=fixture()
        error=dict(path='$.claims[0].scope.evidence[0]',code='literal',message='literal failure')
        reading['claims'][0]['scope']['evidence']=[dict(source_field='target_text',text='aa')]
        for text,count in [('x',0),('aaa',2),('aaaa',3)]:
            changed=replace(window,blocks=({**window.blocks[0],'target_text':text},))
            facts=f.enrich([error],reading,changed)[0]['mechanical_details']
            self.assertEqual(len(facts['matches']),count);self.assertEqual(facts['occurrence_count'],count)

    def test_cross_block_unicode_offsets_and_literal_context_never_normalize(self):
        window,_,reading=fixture()
        blocks=({**window.blocks[0],'target_text':'αé'}, {**window.blocks[0],'block_id':999,'target_text':'βx'})
        changed=replace(window,blocks=blocks)
        reading['claims'][0]['scope']['evidence']=[dict(source_field='target_text',text='é\nβ')]
        error=dict(path='$.claims[0].scope.evidence[0]',code='literal',message='synthetic location probe')
        facts=f.enrich([error],reading,changed)[0]['mechanical_details'];match=facts['matches'][0]
        self.assertEqual((match['start'],match['end']),(1,4));self.assertEqual(len(match['blocks']),2)
        self.assertEqual(match['context'],'αé\nβx')

    def test_missing_reference_reports_exact_id_all_roles_and_pairing_without_choosing(self):
        window,_,reading=fixture();claim=reading['claims'][0];prop=claim['proposition']['node_id']
        claim['qualifications']=[dict(node_id='absent',applies_to='wrong-proposition',reading='Synthetic qualifier')]
        error=dict(path='$.claims[0].qualifications[0]',code='reference',message='undefined node')
        facts=f.enrich([error],reading,window)[0]['mechanical_details']
        self.assertEqual(facts['referenced_node_id'],'absent');self.assertFalse(facts['referenced_node_is_defined'])
        self.assertEqual(facts['required_role'],'qualification');self.assertEqual(facts['required_applies_to'],prop)
        self.assertFalse(facts['applies_to_matches']);self.assertIsNone(facts['selected_node_id'])
        self.assertEqual(facts['available_nodes'],[dict(node_id=n['node_id'],role=n['role']) for n in claim['evidence_nodes']])

    def test_unsupported_errors_and_paths_are_retained_verbatim(self):
        window,_,reading=fixture()
        errors=[dict(path='$.unknown',code='reference',message='missing'),
                dict(path='$.__class__()',code='literal',message='unrecognized'),
                dict(path='$.status',code='status',message='inconsistent')]
        self.assertEqual(f.enrich(errors,reading,window),errors)
