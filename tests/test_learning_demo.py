"""Synthetic model boundary fixtures; no real pastor fingerprints or warrants."""
from dataclasses import asdict
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from pastor_transcript_extractor import learning_demo as demo
from pastor_transcript_extractor import learning_demo_contracts as c
from pastor_transcript_extractor.pastor_evidence import SourceWindow, SampleSpec, digest
from pastor_transcript_extractor.evidence_requests import ReceiptStore
from test_theological_binding import fixture


class SyntheticEncoding:
    """Fixed stub tokenizer only for transport-free orchestration fixtures."""
    def encode(self,text,**kwargs): return [0]*(len(text)//4)


def synthetic_packet():
    windows=[];requests=[];sources=[];samples=[]
    for p in range(2):
        videos=tuple(10000+p*3+i for i in range(3))
        samples.append(asdict(SampleSpec(900+p,videos,'synthetic-membership')))
        for vid in videos:
            sources.append(dict(video_id=vid))
            for slot in range(4):
                window=SourceWindow(f'synthetic-{vid}-{slot}',900+p,vid,'synthetic-source',slot,
                    (dict(block_id=slot,start_seconds=slot*60,end_seconds=(slot+1)*60,
                        segment_indexes=[slot],target_text='God creates the world. People respond with trust.'),),
                    'independent_control' if slot==3 else 'detector_selected')
                texts,mapping=window.target()
                request=c.generation_request('source_reading',dict(texts=texts,block_mapping=mapping),{'window':window.id})
                windows.append(asdict(window));requests.append(dict(case_id=window.id,request=asdict(request)))
    return dict(input_fingerprint='synthetic-only',windows=windows,samples=samples,
                source_refs=sources,source_requests=requests,measurements=[])


class FakeProvider:
    def __init__(self): self.calls=[]
    def __call__(self,request):
        self.calls.append(request)
        phase=request.phase
        if request.body['model']=='jev-1.13.0':
            output={key:dict(type='noul',noul=.95) for key in request.body['questions']}
        else:
            state=json.loads(request.body['messages'][1]['content'])
            if phase=='source_reading':
                text=state['texts']['target_text'];rows=[]
                for i,phrase in enumerate(['God creates the world.','People respond with trust.']):
                    _,row,_=fixture(text)
                    start=text.index(phrase)
                    span=dict(source_field='target_text',start=start,end=start+len(phrase),text=phrase)
                    row['binding_id']=str(i);row['proposition'].update(span=span,reading=phrase)
                    row['evidence_nodes'][0]['span']=span
                    rows.append(row)
                output=dict(status='proposed',claims=rows)
            elif phase=='alignment_and_interpretation':
                assignments=[]
                for item in state['items']:
                    meaning=dict(proposition=item['binding']['proposition']['reading'],referents=[],modality='assertion',
                        quantifiers=[],conditions=[],exceptions=[],temporal_scope='unspecified',scope='local')
                    assignments.append(dict(observation_id=item['id'],meaning=meaning,
                        paths=['theology/creation'],resolved=True,evidence=[item['id']]))
                vid=state['sources'][0]['video_id']
                hypothesis=dict(id=f'hyp-{vid}',conclusion='The source connects creation and response.',
                    premise_ids=[state['items'][0]['id'],state['items'][1]['id']],inference_type='synthetic_warrant_fixture',
                    scope_video_ids=[vid],alternatives=['Statements may be adjacent only.'],counterevidence_ids=[],
                    defeaters=['No actual source link.'])
                output=dict(assignments=assignments,hypotheses=[hypothesis],relation_assessments=[])
            else:
                key=next(iter(state['entries']))
                output=dict(clauses=[dict(id='synthetic-clause',text='Synthetic supported clause.',entry_ids=[key],
                    scope_video_ids=state['entries'][key]['scope_video_ids'],role='observation')])
        return dict(model=request.body['model'],usage=dict(input_tokens=100,output_tokens=100),complete=True,output=output)


class IntegrationTests(unittest.TestCase):
    def test_full_automatic_recipe_66_attempts_and_six_omission_views(self):
        packet=synthetic_packet();provider=FakeProvider()
        with TemporaryDirectory() as directory:
            store=ReceiptStore(Path(directory))
            result=demo.execute_pipeline(packet,store,provider,encoding=SyntheticEncoding())
            self.assertEqual(len(provider.calls),66)
            self.assertEqual(result['accounting']['attempts'],66)
            self.assertLess(float(result['accounting']['reserved_usd']),2)
            self.assertEqual(result['accounting']['runtime_repairs'],0)
            self.assertEqual(len(result['omission_views']),6)
            self.assertEqual(len(result['fingerprints']),2)
            self.assertEqual(result['comparisons']['theology']['position_metrics']['agreement'],1)
            self.assertEqual(result['status'],'INCONCLUSIVE')
            self.assertEqual(len(result['hypotheses']['accepted']),6)
            for view in result['omission_views']:
                omitted=view['omitted_video_id']
                for fp in view['fingerprints']:
                    self.assertNotIn(omitted,fp['sample_spec']['video_ids'])
                for hypothesis in view['hypotheses']['accepted']:
                    self.assertNotIn(omitted,hypothesis['scope_video_ids'])
                for narrative in view['narratives']:
                    for clause in narrative['final']['clauses']:
                        self.assertNotIn(omitted,clause['scope_video_ids'])
            again=demo.execute_pipeline(packet,store,provider,encoding=SyntheticEncoding())
            self.assertEqual(result,again)
            self.assertEqual(len(provider.calls),66)

    def test_no_oracle_or_manual_runtime_input(self):
        packet=synthetic_packet()
        packet['oracle']='DO NOT SEND TO MODEL'
        provider=FakeProvider()
        with TemporaryDirectory() as directory:
            demo.execute_pipeline(packet,ReceiptStore(Path(directory)),provider,encoding=SyntheticEncoding())
        self.assertNotIn('DO NOT SEND TO MODEL',json.dumps([r.body for r in provider.calls]))

    def test_controls_ignore_scores_and_order(self):
        ids=[1,2,3,4,5]
        self.assertEqual(demo.independent_control(42,ids),demo.independent_control(42,ids[::-1]))

    def test_strict_schema_overflow_and_foreign_fields(self):
        with self.assertRaises(ValueError): c.validate_shape({'status':'none','claims':[],'manual_fix':True},c.READ_SCHEMA)
        with self.assertRaises(ValueError): c.validate_shape({'clauses':[{}]*13},c.NARRATIVE_SCHEMA)
