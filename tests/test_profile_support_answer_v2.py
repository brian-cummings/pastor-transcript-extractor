from copy import deepcopy
import unittest
from pastor_transcript_extractor import profile_analysis_support as core
from pastor_transcript_extractor import profile_analysis_support_execution as execution
from test_profile_analysis_support import plan,results


def response(case,*,status=None,field='scope',text='local'):
    catalog=core.citation_catalog(case);cid=next(k for k,v in catalog.items() if v['field']=='target_text')
    qualities=[] if status is None else [dict(reading='This statement remains local.',evidence=[cid],status=status,preservation_evidence=[dict(field=field,text=text)] if status=='already_preserved' else [])]
    return dict(judgment='supported',evidence=[cid],qualifications=qualities,reason='The cited source supports this bounded statement.')


class AnswerV2Tests(unittest.TestCase):
    def test_ids_resolve_one_passage_field_unit_and_reordering_is_stable(self):
        case=plan()['items'][0]['case'];other=deepcopy(case['sources']['v9b1']);case['sources']['other']=other
        ids=core.citation_catalog(case)
        self.assertEqual(len({tuple(v.values()) for v in ids.values()}),len(ids))
        source=core.citation_state(case);seen=[u['citation_id'] for p in source['passages'] for us in p['fields'].values() for u in us]
        self.assertTrue(set(seen)<=set(ids));self.assertEqual(len(seen),len(set(seen)))
        changed=deepcopy(case);changed['sources']=dict(reversed(list(changed['sources'].items())))
        self.assertEqual(core.citation_catalog(changed),ids)
        answer=response(case);bound=core.validate_answer_v2(case,answer)
        self.assertEqual(bound['contract_version'],core.ANSWER_V2)
        self.assertEqual(bound['bound_evidence'][0]['selection'],ids[answer['evidence'][0]])
        answer['evidence']=['v9b1.target_text.u9999']
        with self.assertRaisesRegex(ValueError,'Unknown source citation'):core.validate_answer_v2(case,answer)

    def test_no_citation_omission_duplicates_or_invented_preservation(self):
        case=plan()['items'][0]['case'];answer=response(case)
        answer['evidence']=[]
        with self.assertRaisesRegex(ValueError,'requires source'):core.validate_answer_v2(case,answer)
        answer['judgment']='unresolved';self.assertEqual(core.validate_answer_v2(case,answer)['answer']['judgment'],'unresolved')
        for field,text in [('scope','A made up restriction'),('wrong','local')]:
            with self.assertRaisesRegex(ValueError,'literal supplied'):core.validate_answer_v2(case,response(case,status='already_preserved',field=field,text=text))
        answer=response(case,status='already_preserved');answer['qualifications'][0]['preservation_evidence']=[]
        with self.assertRaisesRegex(ValueError,'requires literal'):core.validate_answer_v2(case,answer)
        answer=response(case);answer['evidence']*=2
        with self.assertRaisesRegex(ValueError,'Duplicate'):core.validate_answer_v2(case,answer)
        answer=response(case,status='missing_required');answer['qualifications'][0]['evidence']=[]
        with self.assertRaisesRegex(ValueError,'requires evidence'):core.validate_answer_v2(case,answer)

    def test_preserved_missing_and_unknown_have_distinct_handoff_states(self):
        p=plan();case=p['items'][0]['case']
        expected={'already_preserved':'supported','missing_required':'requires_qualification','unresolved':'qualification_unresolved'}
        for status,outcome in expected.items():
            rows=results(p);rows[0]['judgment']=core.validate_answer_v2(case,response(case,status=status));doc=core.document_input(p,rows)
            self.assertEqual(doc['entries'][0]['support_status'],outcome)
            self.assertEqual(bool(doc['ready_claim_ids']),status=='already_preserved')
            if status!='already_preserved':self.assertEqual(doc['entries'][1]['support_status'],'dependency_unresolved')
        legacy=results(p);legacy[0]['judgment']['qualifications']=[dict(reading='local',status='already_preserved')]
        self.assertEqual(core.document_input(p,legacy)['entries'][0]['support_status'],'requires_qualification')

    def test_literal_preservation_in_statement_scope_and_existing_caveats(self):
        case=plan()['items'][0]['case'];case['state']['candidate']['declared_caveats']=dict(limits='Selected evidence only.')
        for field,text in [('statement','The speaker explains'),('scope','local'),('declared_caveats','Selected evidence only.')]:
            bound=core.validate_answer_v2(case,response(case,status='already_preserved',field=field,text=text))
            self.assertEqual(bound['qualifications'][0]['preservation_evidence'][0]['text'],text)
            self.assertTrue(bound['qualifications'][0]['preservation_evidence'][0]['occurrences'])

    def test_schema_and_request_use_catalog_not_passage_unit_cross_product(self):
        case=plan()['items'][0]['case'];schema=execution.schema(case);props=schema['properties']
        self.assertEqual(props['evidence']['items']['type'],'string')
        self.assertEqual(set(props['evidence']['items']['enum']),set(core.citation_catalog(case)))
        self.assertEqual(props['qualifications']['items']['properties']['evidence']['minItems'],1)
        self.assertNotIn('anyOf',schema)
        self.assertEqual(set(schema['required']),{'judgment','evidence','qualifications','reason'})
        spec=execution.make_request(case);self.assertEqual(spec.source_identity['answer_contract'],core.ANSWER_V2)
        self.assertEqual(spec.body['reasoning_effort'],'none')
        self.assertIn('already_preserved',spec.body['messages'][0]['content'])
