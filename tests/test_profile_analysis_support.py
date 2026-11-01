from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import hashlib
import json
import unittest
from pastor_transcript_extractor import profile_analysis_support as s


def fixture():
    texts=dict(target_text='The speaker explains the passage. It does not mean the son was created.',leading_context='This is a reported example.',trailing_context='The discussion continues.')
    block=dict(block_id=1,text=texts['target_text'],context=texts,start_seconds=60,end_seconds=120,segment_indexes=[1,2])
    measurement=dict(block_id=1,probabilities=dict(exegetical_exposition=.95),resolved_model_id='jev-test')
    raw=dict(classification=dict(search=dict(topic_analysis=dict(blocks=[block]),semantic_analysis=dict(blocks=[measurement],question_version='q1'))))
    content=json.dumps(raw).encode();sha=hashlib.sha256(content).hexdigest()
    obs=dict(id='e1',video_id=9,block_id=1,source_path='/fixture/source.json',source_sha256=sha,full_target_text=texts['target_text'],layer='treatment',field='exegetical_exposition',value=.95,state='measured',meaning='Explains a biblical text.',question_version='q1',model='jev-test',start_seconds=60,end_seconds=120,segment_indexes=[1,2])
    claims=[dict(id='local',wording='The speaker explains the passage.',evidence_ids=['e1'],observation_input_ids=['e1'],scope=dict(meaning='local')),dict(id='summary',wording='This sample includes biblical explanation.',evidence_ids=['e1'],upstream_claim_ids=['local'],scope=dict(meaning='selected sample'))]
    record=dict(profile=dict(id=777,effective_member_video_ids=[9],membership_fingerprint='membership'),inventory_fingerprint='inventory',reader=dict(claims=claims),observations=[obs],source_identity=[dict(video_id=9,source_path='/fixture/source.json',source_sha256=sha,gate=dict(eligible=True))],gaps=[dict(id='coverage',withheld='Ministry-wide stability',cause='Small sample',remedy='Retain unknown')])
    return record,content


def plan(record=None,content=None):
    default,blob=fixture();record=record or default;content=blob if content is None else content
    with patch.object(s,'resolve_topic_analysis_artifact',side_effect=lambda c:c['search']['topic_analysis']),patch.object(s,'resolve_topic_block_context',side_effect=lambda b:b['context']):
        return s.build_plan(record,loader=lambda p:content)


def answer(judgment='supported',field='target_text'):
    return dict(judgment=judgment,evidence=[dict(passage_id='v9b1',field=field,start_unit='u0000',end_unit='u0000')],qualifications=[],reason='The source supports this statement within the declared scope.')


def results(p):
    return [dict(claim_id=i['claim_id'],status='complete',judgment=s.validate_answer(i['case'],answer()),receipt='immutable-receipt.json') for i in p['items']]


class ProfileAnalysisSupportTests(unittest.TestCase):
    def test_multiblock_field_inventory_cannot_append_target_blocks_or_invent_context(self):
        window=s.evidence.SourceWindow('multi',777,9,'source',1,tuple(
            dict(block_id=i,target_text=text,start_seconds=i*60,end_seconds=(i+1)*60,segment_indexes=[i])
            for i,text in ((1,'First complete sentence.'),(2,'Second complete sentence.'))),'test')
        texts,_=window.target();fields=s._inventory(window,texts)
        self.assertEqual([],fields['leading_context']);self.assertEqual([],fields['trailing_context'])
        self.assertEqual(texts['target_text'],''.join(u['text'] for u in fields['target_text']))
        for unit in fields['target_text']:
            self.assertLessEqual(unit['end'],len(texts['target_text']))
            self.assertEqual(unit['text'],texts['target_text'][unit['start']:unit['end']])
        self.assertEqual('Second complete sentence.',fields['target_text'][-1]['text'])
        source=dict(window=dict(video_id=9,anchor_block_id=1,source_sha256='source'),
            fields=fields,texts=texts,context_sha256=s.context_digest(texts))
        last=fields['target_text'][-1]['id']
        bound=s.validate_answer(dict(sources={'multi':source}),dict(judgment='supported',
            evidence=[dict(passage_id='multi',field='target_text',start_unit=last,end_unit=last)],
            qualifications=[],reason='The last real source unit must bind.'))
        self.assertEqual('Second complete sentence.',bound['bound_evidence'][0]['span']['text'])

    def test_all_claims_independent_of_profile_and_roundtrip(self):
        p=plan();self.assertEqual(len(p['items']),2);self.assertEqual(p['profile']['id'],777)
        self.assertTrue(all(i['case'] for i in p['items']))
        self.assertEqual(p,json.loads(json.dumps(p)))
        self.assertEqual(p['items'][0]['case']['state']['measurement_ledger']['rows'][0][4],.95)
        self.assertNotIn('expected',json.dumps(p))
        record,blob=fixture();old=deepcopy(record);plan(record,blob);self.assertEqual(record,old)

    def test_stale_source_model_geometry_and_missing_inputs_become_named_gaps(self):
        record,blob=fixture()
        for key,value in [('model','wrong'),('value',.1),('full_target_text','wrong'),('source_sha256','wrong')]:
            changed=deepcopy(record);changed['observations'][0][key]=value;p=plan(changed,blob)
            self.assertTrue(all(i['case'] is None and i['gap']['missing_information'] for i in p['items']))
        changed=deepcopy(record);changed['reader']['claims'][0]['observation_input_ids']=['missing']
        p=plan(changed,blob);self.assertIsNotNone(p['items'][0]['gap']);self.assertIsNotNone(p['items'][1]['case'])
        self.assertTrue(all(i['case'] is None for i in plan(record,blob+b' ')['items']))

    def test_counterevidence_and_every_denominator_input_retained(self):
        record,blob=fixture();o=deepcopy(record['observations'][0]);o['id']='e2';record['observations'].append(o)
        record['reader']['claims'][0].update(observation_input_ids=['e1','e2'],counterevidence_ids=['e2'])
        c=plan(record,blob)['items'][0]['case'];self.assertEqual(len(c['state']['measurement_ledger']['rows']),2)
        self.assertEqual(len(c['state']['passages']),1)
        self.assertEqual(c['state']['passages'][0]['counter_input_ids'],[1])
        self.assertEqual(c['input_ids'],{'0':'e1','1':'e2'})

    def test_citations_in_named_context_do_not_claim_target_timestamps(self):
        c=plan()['items'][0]['case'];a=s.validate_answer(c,answer(field='leading_context'))
        self.assertEqual(a['bound_evidence'][0]['span']['source_field'],'leading_context')
        self.assertNotIn('start_seconds',a['bound_evidence'][0]['source_identity'])
        self.assertEqual(a['bound_evidence'][0]['span']['text'],'This is a reported example.')
        bad=answer();bad['evidence'][0]['start_unit']='missing'
        with self.assertRaises(KeyError):s.validate_answer(c,bad)
        bad=answer();bad['evidence']=[]
        with self.assertRaises(ValueError):s.validate_answer(c,bad)
        bad['judgment']='unresolved';self.assertEqual(s.validate_answer(c,bad)['answer']['judgment'],'unresolved')

    def test_document_handoff_withholds_qualification_dependencies_and_cycles(self):
        p=plan();rows=results(p);doc=s.document_input(p,rows)
        self.assertEqual(doc['ready_claim_ids'],['local','summary']);self.assertEqual(doc['known_gaps'],p['known_gaps'])
        a=answer();a['qualifications']=[dict(reading='Only this reported example.',evidence=a['evidence'])]
        rows[0]['judgment']=s.validate_answer(p['items'][0]['case'],a);doc=s.document_input(p,rows)
        self.assertEqual(doc['ready_claim_ids'],[])
        self.assertEqual(doc['coverage']['by_status'],dict(dependency_unresolved=1,requires_qualification=1))
        rows[0]['judgment']=s.validate_answer(p['items'][0]['case'],answer('contradicted'));doc=s.document_input(p,rows)
        self.assertEqual(doc['entries'][0]['support_status'],'contradicted');self.assertIn('Unresolved',s.render_handoff(doc))
        p['items'][0]['case']['dependencies']=['summary'];self.assertEqual(s.document_input(p,results(p))['ready_claim_ids'],[])
        with self.assertRaises(ValueError):s.document_input(p,rows[:1])
        with self.assertRaisesRegex(ValueError,'not production admitted'):s.document_input(p,rows,production=True)

    def test_reader_limits_and_alternatives_survive_into_final_handoff(self):
        record,blob=fixture();record['reader']['portrait']=dict(entries=[dict(id='summary',limits='Only this selected sample.',alternative='Selection may overrepresent this example.')])
        p=plan(record,blob);doc=s.document_input(p,results(p))
        self.assertEqual(p['items'][1]['case']['state']['candidate']['declared_caveats']['limits'],'Only this selected sample.')
        self.assertEqual(doc['entries'][1]['declared_caveats']['alternative'],'Selection may overrepresent this example.')
        self.assertIn('Only this selected sample.',s.render_handoff(doc))
        self.assertIn('Scope:',s.render_handoff(doc))

    def test_valid_unresolved_judgment_never_appears_ready(self):
        p=plan();rows=results(p);rows[0]['judgment']=s.validate_answer(p['items'][0]['case'],answer('unresolved'))
        self.assertEqual(s.document_input(p,rows)['coverage']['by_status'],dict(dependency_unresolved=1,unresolved=1))
