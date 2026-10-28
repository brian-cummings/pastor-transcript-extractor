from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import json
import unittest
from pastor_transcript_extractor import final_profile_support as f


def fixture(folder):
    folder=Path(folder);source_path=folder/'source.json'
    block=dict(block_id=1,text='The preacher explains the text. It does not say the son was created.',start_seconds=60,end_seconds=120,segment_indexes=[1,2])
    measurement=dict(block_id=1,probabilities=dict(exegetical_exposition=.95),resolved_model_id='jev-1.13.0',within_selected_candidate=True)
    raw=dict(classification=dict(blocks=[block],search=dict(semantic_analysis=dict(blocks=[measurement],question_version='q1'))))
    source_path.write_text(json.dumps(raw));sha=f.shared.check.demo.file_hash(source_path)
    observation=dict(id='e1',video_id=3,block_id=1,source_path=str(source_path),source_sha256=sha,full_target_text=block['text'],layer='treatment',field='exegetical_exposition',value=.95,state='measured',meaning='Explains biblical wording.',question_version='q1',model='jev-1.13.0',**{k:block[k] for k in ('start_seconds','end_seconds','segment_indexes')})
    point=dict(point_id=f.POINT,kind='style',explanation='The preacher explains the wording.',evidence_ids=['e1'],status='pending_review')
    record=dict(profile=dict(id=2,effective_member_video_ids=[3],membership_fingerprint='membership'),inventory_fingerprint='inventory',reader=dict(explanatory_descriptions=dict(points=[point])),observations=[observation],source_identity=[dict(video_id=3,source_sha256=sha,gate=dict(eligible=True))])
    profile=folder/'profile.json';profile.write_text(json.dumps(dict(description=record)))
    return profile,source_path,record


def metadata(model):
    return dict(model=model,context=262144,capabilities=['structured-output'],input_cents_per_token='.00002',output_cents_per_token='.00025')


def response(spec,judgment='supported',evidence=None):
    answer=dict(judgment=judgment,evidence=[dict(evidence_id='e1',start_unit='u0000',end_unit='u0001')] if evidence is None else evidence,qualifications=[],reason='The linked passage supports the local wording.')
    return dict(model=spec.body['model'],complete=True,usage=dict(input_tokens=100,output_tokens=100),output=json.dumps(answer))


class FinalProfileSupportTests(unittest.TestCase):
    def test_reuses_exact_profile_statement_source_geometry_and_observation(self):
        with TemporaryDirectory() as folder:
            profile,source,record=fixture(folder);case=f.load_case(profile)
            self.assertEqual(case['state']['candidate']['statement'],record['reader']['explanatory_descriptions']['points'][0]['explanation'])
            self.assertEqual(case['state']['evidence'][0]['observation']['value'],.95)
            self.assertNotIn('source_reviews',f.shared.requests.wire(case['state']))
            self.assertNotIn('expected',f.shared.requests.wire(case['state']))
            self.assertEqual(case,json.loads(json.dumps(case)))
            raw=json.loads(source.read_text());raw['classification']['blocks'][0]['text']='changed';source.write_text(json.dumps(raw))
            with self.assertRaisesRegex(ValueError,'Source'):f.load_case(profile)

    def packet(self,folder):
        profile,_,_=fixture(folder)
        with patch.object(f.hosted,'public_model_metadata',side_effect=metadata):
            return f.prepare(Path(folder),profile_path=profile,check_only=True)

    def test_mechanical_binding_distinct_from_semantic_support_and_unknown(self):
        with TemporaryDirectory() as folder:
            packet,_=self.packet(folder);spec=f.shared.requests.RequestSpec(**packet['request'])
            for judgment in ('supported','contradicted','unresolved'):
                result=f.assess(packet,response(spec,judgment))
                self.assertEqual(result['answer']['judgment'],judgment)
                self.assertEqual(result['mechanical_contract'],'PASS')
                self.assertIn('INCONCLUSIVE',result['semantic_outcome'])
                self.assertFalse(result['production_admission'])
                self.assertEqual(result['bound_evidence'][0]['span']['text'],packet['case']['state']['evidence'][0]['source']['units'][0]['text']+packet['case']['state']['evidence'][0]['source']['units'][1]['text'])
            self.assertEqual(f.assess(packet,response(spec,'unresolved',[]))['summary']['withheld'],1)
            with self.assertRaisesRegex(ValueError,'requires source'):f.assess(packet,response(spec,evidence=[]))
            with self.assertRaisesRegex(ValueError,'Foreign'):f.assess(packet,response(spec,evidence=[dict(evidence_id='foreign',start_unit='u0000',end_unit='u0000')]))
            with self.assertRaisesRegex(ValueError,'Unknown source'):f.assess(packet,response(spec,evidence=[dict(evidence_id='e1',start_unit='missing',end_unit='u0000')]))

    def test_stubbed_paid_executor_one_call_cache_budget_and_invalid_citation(self):
        with TemporaryDirectory() as folder:
            packet,out=self.packet(folder);sent=[]
            def transport(spec):sent.append(spec);return response(spec)
            result=f.shared.qwen_recipe(packet,out/'execution',transport,assessor=f.assess)
            self.assertEqual(len(sent),1);self.assertEqual(result['status'],'INCONCLUSIVE')
            self.assertEqual(result['accounting']['paid_attempts'],1)
            replay=f.shared.qwen_recipe(packet,out/'execution',lambda s:self.fail('no new call'),assessor=f.assess)
            self.assertEqual(replay,result)
            with f.shared.integration.cumulative_history(packet,out.parent/'other/execution') as history:self.assertEqual(len(history),1)
            self.assertEqual(packet['token_account']['output_cap'],2048)
            self.assertEqual(packet['budget']['reserved_usd'],'0.0083968')
        with TemporaryDirectory() as folder:
            packet,out=self.packet(folder)
            result=f.shared.qwen_recipe(packet,out/'execution',lambda spec:response(spec,evidence=[]),assessor=f.assess)
            self.assertEqual(result['status'],'FAIL(component)')
            self.assertEqual(result['accounting']['paid_attempts'],1)

    def test_frozen_approval_and_no_generation_during_prepare(self):
        with TemporaryDirectory() as folder:
            packet,out=self.packet(folder);out.mkdir(parents=True);path=out/'input.json';path.write_text(json.dumps(packet))
            with patch.object(f,'prepare',return_value=(packet,out)),patch.object(f.hosted,'transport',side_effect=AssertionError('no call')):
                self.assertEqual(f.run(path,Path(folder),check_only=True)['paid_calls'],0)
                with self.assertRaises(ValueError):f.run(path,Path(folder))
                with self.assertRaises(ValueError):f.run(path,Path(folder),check_only=True,max_usd='.001')
                with self.assertRaisesRegex(ValueError,'Invalid support-test'):f.run(path,Path(folder),check_only=True,max_usd='invalid')
                changed=deepcopy(packet);changed['policy']['retries']=1
                with patch.object(f,'prepare',return_value=(changed,out)),self.assertRaisesRegex(ValueError,'Frozen'):f.run(path,Path(folder),check_only=True)

    def test_cli_tie_in(self):
        from typer.testing import CliRunner
        from pastor_transcript_extractor.cli import app
        with patch.object(f,'run',return_value=dict(status='PREPARED_NO_EXECUTION')) as run:
            result=CliRunner().invoke(app,['analysis','learning-demo','profile-support-run','--input','/tmp/frozen.json','--check-only','--json'])
            self.assertEqual(result.exit_code,0,result.output);self.assertTrue(run.call_args.kwargs['check_only'])
