from copy import deepcopy
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from typer.testing import CliRunner
from pastor_transcript_extractor import connected_binding_development as d
from pastor_transcript_extractor import profile_proposition_review
from test_profile_proposition_review import fixture as reference_fixture
from test_connected_proposition_binding import fixture as extraction_fixture


def fixture():
    reviewed=profile_proposition_review.build(*reference_fixture())
    content,source,_=extraction_fixture()
    for i,(c,identity) in enumerate(zip(reviewed['cases'],[(4589,47),(3973,75),(281,123)])):
        c['video_id'],c['block_id']=identity
        c['texts']=deepcopy(source['texts']);c['texts']['target_text']='Opening '+str(i)+'. '+source['texts']['target_text']
    with patch.object(d.reference,'load',return_value=reviewed):return d.panel()


class FakeProvider:
    calls=0
    def digest(self):return 'a'*64
    def generate(self,body):
        type(self).calls+=1
        content,_,_=extraction_fixture()
        return json.dumps(dict(model=body['model'],done=True,done_reason='stop',message=dict(content=json.dumps(content)),prompt_eval_count=100,eval_count=200))


class ConnectedRunnerTests(unittest.TestCase):
    def test_whole_passage_requests_have_no_reviewed_answers_or_candidate_menu(self):
        spec,_=fixture()
        for source in spec['sources']:
            payload=d.body(source,spec);state=json.loads(payload['messages'][1]['content'])
            self.assertEqual(source['texts'],state)
            for forbidden in ('g1_record','reference_id','field_review','source_candidates','expected_readings','reviewed_subject_mapping'):
                self.assertNotIn(forbidden,json.dumps(payload))
            self.assertEqual(8192,payload['options']['num_predict']);self.assertEqual(16384,payload['options']['num_ctx'])
        with patch.object(d,'panel',return_value=(spec,{})),patch.object(Path,'write_text',side_effect=AssertionError('No writes')),patch.object(d,'Provider',side_effect=AssertionError('No backend')):
            result=d.prepare();self.assertEqual(0,result['provider_requests']);self.assertEqual(0,result['metadata_reads']);self.assertEqual(3,result['max_generation_requests'])

    def test_three_requests_pin_model_preserve_raw_and_resume_without_backend(self):
        spec,ref=fixture()
        with TemporaryDirectory() as root,patch.object(d,'panel',return_value=(spec,ref)),patch.object(d,'directory',return_value=Path(root)):
            first,folder,_=d.execute(provider_factory=FakeProvider)
            self.assertEqual(3,first['unique_request_count']);self.assertEqual(dict(input_tokens=300,output_tokens=600),first['usage'])
            self.assertEqual('a'*64,first['backend_pin']['model_digest'])
            initial=d.review.read(folder/'invocation-v1.json');self.assertEqual(3,initial['provider_requests']);self.assertEqual(7,initial['metadata_reads'])
            self.assertTrue(all(g['binding']['automatic_binding'] for c in first['cases'] for g in c['generated']))
            with patch.object(d,'urlopen',side_effect=AssertionError('No network')):
                again,_,_=d.execute(provider_factory=lambda:self.fail('No provider'))
                cached,_,_=d.cached()
            self.assertEqual(first,again);self.assertEqual(first,cached)
            self.assertEqual(initial,d.review.read(folder/'invocation-v1.json'))
            resume=d.review.read(folder/'resume-invocation-v1.json');self.assertEqual(0,resume['provider_requests']);self.assertEqual(3,resume['cache_hits'])
            records=[d.review.read(p) for p in (Path(root)/'cache').glob('*.json')]
            self.assertEqual(3,len(records));self.assertTrue(all('message' in x['raw_envelope'] for x in records))
            self.assertFalse(first['accepted_observations']);self.assertFalse(first['profile_projection'])

    def test_timeout_is_logged_and_never_silently_retried(self):
        class Fails(FakeProvider):
            def generate(self,body):raise TimeoutError('Synthetic timeout')
        spec,ref=fixture()
        with TemporaryDirectory() as root,patch.object(d,'panel',return_value=(spec,ref)),patch.object(d,'directory',return_value=Path(root)):
            with self.assertRaises(TimeoutError):d.execute(provider_factory=Fails)
            with self.assertRaisesRegex(ValueError,'no automatic retry'):d.execute(provider_factory=lambda:self.fail('No repeat'))
            self.assertEqual(1,len(d.review.read(next((Path(root)/'runs').glob('*/request-ledger-v1.json')))['attempts']))

    def test_digest_drift_preserves_raw_but_blocks_reuse_and_repeat(self):
        class Drifts(FakeProvider):
            reads=0
            def digest(self):
                self.reads+=1;return ('a' if self.reads<3 else 'b')*64
        spec,ref=fixture()
        with TemporaryDirectory() as root,patch.object(d,'panel',return_value=(spec,ref)),patch.object(d,'directory',return_value=Path(root)):
            with self.assertRaisesRegex(ValueError,'during extraction'):d.execute(provider_factory=Drifts)
            cached=d.review.read(next((Path(root)/'cache').glob('*.json')));self.assertTrue(cached['raw_envelope']);self.assertEqual('raw_saved_unverified',cached['status'])
            with self.assertRaisesRegex(ValueError,'no automatic repeat'):d.execute(provider_factory=lambda:self.fail('No repeat'))

    def test_truncated_wrong_model_and_invalid_json_are_visible_rejections_not_repairs(self):
        spec,ref=fixture()
        for mutation in ('length','model','json','schema'):
            class Bad(FakeProvider):
                def generate(self,body):
                    envelope=json.loads(super().generate(body))
                    if mutation=='length':envelope['done_reason']='length'
                    if mutation=='model':envelope['model']='another-model'
                    if mutation=='json':envelope['message']['content']='{incomplete'
                    if mutation=='schema':envelope['message']['content']='{"frames": []}'
                    return json.dumps(envelope)
            with self.subTest(mutation=mutation),TemporaryDirectory() as root,patch.object(d,'panel',return_value=(spec,ref)),patch.object(d,'directory',return_value=Path(root)):
                result,_,_=d.execute(provider_factory=Bad)
                self.assertTrue(all(c['compile_error'] for c in result['cases']))
                self.assertEqual(3,result['unique_request_count']);self.assertEqual(3,len(list((Path(root)/'cache').glob('*.json'))))
                report,path=d.report();self.assertEqual(3,len(report['passage_rejections']));self.assertIn('Passage rejected:',path.read_text())

    def test_resealed_generated_tampering_is_detected_by_raw_replay(self):
        spec,ref=fixture()
        with TemporaryDirectory() as root,patch.object(d,'panel',return_value=(spec,ref)),patch.object(d,'directory',return_value=Path(root)):
            result,folder,_=d.execute(provider_factory=FakeProvider)
            result['cases'][0]['generated'][0]['binding']['proposition']['reading']='An invented paraphrase.'
            d.review.save(folder/'generated-v1.json',result)
            with self.assertRaisesRegex(ValueError,'raw response'):d.cached()

    def test_cli_prepare_and_check_only_are_network_and_write_free(self):
        from pastor_transcript_extractor.cli import app
        spec,ref=fixture()
        with TemporaryDirectory() as root,patch.object(d,'panel',return_value=(spec,ref)),patch.object(d,'directory',return_value=Path(root)):
            d.execute(provider_factory=FakeProvider)
            with patch.object(d,'urlopen',side_effect=AssertionError('No network')),patch.object(Path,'write_text',side_effect=AssertionError('No writes')):
                for option in ('--prepare','--check-only'):
                    result=CliRunner().invoke(app,['analysis','profile-connected-binding',option,'--json']);self.assertEqual(0,result.exit_code,result.output)
                    self.assertEqual(0,json.loads(result.output)['provider_requests'])
            result=CliRunner().invoke(app,['analysis','profile-connected-binding','--prepare','--run']);self.assertEqual(2,result.exit_code)

    def test_transport_preserves_complete_envelope_and_uses_bounded_options(self):
        raw=b'{"model":"synthetic","done":true,"message":{"content":"{}"},"eval_count":7}'
        with patch.object(d,'urlopen',return_value=io.BytesIO(raw)) as call:
            provider=d.Provider();body=dict(model=provider.config.model,options=dict(num_predict=8192,num_ctx=16384),stream=False)
            self.assertEqual(raw.decode(),provider.generate(body))
            request=call.call_args.args[0];self.assertTrue(request.full_url.endswith('/api/chat'));self.assertEqual(body,json.loads(request.data))
            self.assertEqual(180,call.call_args.kwargs['timeout'])

    def test_remote_disabled_and_foreign_source_configuration_are_rejected(self):
        for key,value in (('PTE_LLM_BASE_URL','https://example.com'),('PTE_LLM_ENABLED','0'),('PTE_LLM_MODEL','some-model:cloud')):
            with patch.dict('os.environ',{key:value}):
                with self.assertRaises(ValueError):d.configuration()
        spec,ref=fixture();ref['cases'][0]['video_id']=999
        with patch.object(d.reference,'load',return_value=ref):
            with self.assertRaisesRegex(ValueError,'same three'):d.panel()

    def test_report_has_literal_sources_rejections_raw_links_and_no_semantic_verdict(self):
        spec,ref=fixture()
        with TemporaryDirectory() as root,patch.object(d,'panel',return_value=(spec,ref)),patch.object(d,'directory',return_value=Path(root)):
            d.execute(provider_factory=FakeProvider);report,path=d.report();html=path.read_text()
            self.assertEqual('GENERATED_AWAITING_CODEX_SEMANTIC_COMPARISON',report['status']);self.assertEqual(3,report['structurally_valid_candidates'])
            self.assertIn('Awaiting semantic comparison',html);self.assertIn('Original request and raw response',html)
            self.assertIn('Connected speech frames',html);self.assertIn('The maker shaped the land',path.with_name('review-v1.md').read_text())
