"""Bounded editorial synthesis never becomes measurement or semantic admission."""
from copy import deepcopy
import io
import json
from pathlib import Path
import re
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from typer.testing import CliRunner

from pastor_transcript_extractor import profile_description
from pastor_transcript_extractor import profile_synthesis as synthesis
from pastor_transcript_extractor.collector_retrieval_json_v1_1 import seal
from test_profile_description import fixture


def record():
    inv,sources = fixture(routed=True)
    inv = deepcopy(inv)
    sermon = inv['sermons'][0]
    inv['selected_profile']['id'] = 318
    inv['sermons'] = [dict(deepcopy(sermon),video_id=vid) for vid in (3973,281,4589)]
    return profile_description.build(seal(inv),{vid:deepcopy(sources[9]) for vid in (3973,281,4589)})


def panel():
    with patch.object(synthesis.description,'load',return_value=record()):return synthesis.panel()


class FakeProvider:
    def digest(self):return 'a'*64
    def generate(self,body):
        packet = json.loads(body['messages'][1]['content'])
        draft = dict(sections=[dict(key='portrait',sentences=[dict(
            text='These selected recordings discuss God’s character and action.',
            source_ids=[packet['sources'][0]['source_id']])])])
        return json.dumps(dict(model=body['model'],done=True,done_reason='stop',
            message=dict(content=json.dumps(draft)),prompt_eval_count=500,eval_count=100,total_duration=1200000))


class ProfileSynthesisTests(unittest.TestCase):
    def test_packet_reuses_interpretations_not_transcripts_probabilities_or_identity_guess(self):
        from test_profile_description_revision import supplied_record
        from pastor_transcript_extractor.profile_presentation import build_reader
        r = supplied_record('projected');r['reader'] = build_reader(r);r = seal(r)
        before = deepcopy(r)
        packet = synthesis.evidence_packet(r)
        self.assertEqual(before,r)
        self.assertIsNone(packet['confirmed_name'])
        self.assertEqual('unavailable',packet['comparison_status'])
        local = next(row for row in packet['sources'] if row['basis']=='source_reviewed_local_proposal')
        self.assertEqual('projected',local['voice']['occurrence'])
        self.assertEqual('undetermined',local['preacher_use']['status'])
        self.assertIn('An invited response does not establish an actual listener response.',local['unknowns'])
        for field in ('full_target_text','probabilities','g1_record','segment_indexes','threshold'):
            self.assertNotIn('"'+field+'"',json.dumps(packet))

    def test_prepare_is_network_and_write_free_with_fixed_budget_and_scope(self):
        spec,r = panel()
        with patch.object(synthesis,'panel',return_value=(spec,r)),patch.object(synthesis,'Provider',side_effect=AssertionError('No provider')),patch.object(Path,'write_text',side_effect=AssertionError('No write')):
            result = synthesis.prepare()
        self.assertEqual(1,result['max_generation_requests'])
        self.assertEqual(0,result['metadata_reads'])
        self.assertEqual(0,result['provider_requests'])
        body = synthesis.request_body(spec)
        model_input = json.loads(body['messages'][1]['content'])
        self.assertNotIn('source_claim_map',model_input)
        self.assertEqual(list(spec['packet']['source_claim_map']),
            spec['schema']['$defs']['Sentence']['properties']['source_ids']['items']['enum'])
        self.assertEqual(32768,body['options']['num_ctx'])
        self.assertEqual(3072,body['options']['num_predict'])
        oversized = deepcopy(spec);oversized['instructions'] += 'x'*40000
        with self.assertRaisesRegex(ValueError,'context budget'):synthesis.request_body(oversized)
        foreign = record();foreign['profile']['id']=319
        with patch.object(synthesis.description,'load',return_value=seal(foreign)):
            with self.assertRaisesRegex(ValueError,'profile 318'):synthesis.panel()

    def test_single_request_raw_receipt_immutable_report_and_cached_replay_without_network(self):
        spec,r = panel()
        with TemporaryDirectory() as root,patch.object(synthesis,'panel',return_value=(spec,r)),patch.object(synthesis,'directory',return_value=Path(root)):
            first,path,invocation = synthesis.report(run_model=True,provider_factory=FakeProvider)
            self.assertEqual(1,invocation['provider_requests'])
            self.assertEqual(2,invocation['metadata_reads'])
            self.assertEqual('DRAFT_AWAITING_SEMANTIC_AND_WORDING_REVIEW',first['status'])
            self.assertFalse(first['semantic_acceptance']);self.assertFalse(first['comparison_available'])
            self.assertFalse(first['confidence_calibrated']);self.assertFalse(first['new_measurements'])
            self.assertEqual(500,first['generated']['usage']['input_tokens'])
            self.assertTrue((path.parent/'raw-response-v1.json').exists())
            saved = {p.name:p.read_bytes() for p in path.parent.iterdir()}
            with patch.object(synthesis,'Provider',side_effect=AssertionError('No provider')),patch.object(synthesis,'urlopen',side_effect=AssertionError('No network')):
                again,_,current = synthesis.report(run_model=True)
                synthesis.cached()
            self.assertEqual(first,again);self.assertEqual(0,current['provider_requests'])
            self.assertEqual(1,current['cache_hits'])
            self.assertEqual(saved,{p.name:p.read_bytes() for p in path.parent.iterdir()})
            page = path.read_text()
            ids = re.findall(r' id="([^"]+)"',page)
            self.assertEqual(len(ids),len(set(ids)))
            self.assertLessEqual(set(re.findall(r'href="#([^"]+)"',page)),set(ids))
            self.assertLess(page.index('Pastor-level synthesis'),page.index('Existing evidence-backed descriptions'))
            self.assertIn(synthesis.COMPARISON,page)
            self.assertIn('no calibrated confidence percentage',page.lower())
            self.assertEqual('a'*64,first['generated']['request']['model_digest'])

    def test_failures_and_digest_drift_preserve_receipts_without_automatic_retry(self):
        spec,r = panel()
        class Timeout(FakeProvider):
            def generate(self,body):raise TimeoutError('Synthetic timeout')
        class Drift(FakeProvider):
            def __init__(self):self.reads=0
            def digest(self):self.reads+=1;return ('a' if self.reads==1 else 'b')*64
        for factory in (Timeout,Drift):
            with self.subTest(factory=factory),TemporaryDirectory() as root,patch.object(synthesis,'panel',return_value=(spec,r)),patch.object(synthesis,'directory',return_value=Path(root)):
                with self.assertRaises((TimeoutError,ValueError)):synthesis.execute(provider_factory=factory)
                with self.assertRaisesRegex(ValueError,'already attempted'):
                    synthesis.execute(provider_factory=lambda:self.fail('No retry'))
                folder = Path(root)/'runs'/spec['content_fingerprint']
                self.assertEqual('failed_or_ambiguous',synthesis.read(folder/'request-ledger-v1.json')['status'])
                if factory is Drift:self.assertEqual('raw_saved_unverified',synthesis.read(folder/'raw-response-v1.json')['status'])

    def test_invalid_output_is_withheld_not_repaired_or_semantically_accepted(self):
        spec,r = panel();body = synthesis.request_body(spec)
        original = json.loads(FakeProvider().generate(body))
        mutations = {
            'length':lambda e:e.update(done_reason='length'),
            'output_budget':lambda e:e.update(eval_count=synthesis.MAX_OUTPUT_TOKENS+1),
            'model':lambda e:e.update(model='other'),
            'invalid_json':lambda e:e['message'].update(content='{'),
            'unknown_citation':lambda e:e['message'].update(content=json.dumps(dict(sections=[dict(key='portrait',sentences=[dict(text='Unsupported text',source_ids=['missing'])])]))),
            'confidence_score':lambda e:e['message'].update(content=json.dumps(dict(sections=[dict(key='portrait',sentences=[dict(text='Confidence is 95%.',source_ids=[spec['packet']['sources'][0]['source_id']])])]))),
            'extra_comparison':lambda e:e['message'].update(content=json.dumps(dict(sections=[],nearest_preacher='Invented'))),
        }
        for name,mutate in mutations.items():
            envelope=deepcopy(original);mutate(envelope)
            compiled=synthesis.compile_response(dict(raw_envelope=json.dumps(envelope),status='verified',digest_after='digest'),spec,'digest')
            with self.subTest(name=name):
                self.assertEqual('REJECTED_SYNTHESIS_OUTPUT',compiled['status'])
                self.assertIsNone(compiled['draft']);self.assertFalse(compiled['semantic_acceptance'])
        # Even a cited but false statement cannot be declared faithful by structure.
        unsupported=deepcopy(original);draft=json.loads(unsupported['message']['content'])
        draft['sections'][0]['sentences'][0]['text']='The preacher secretly rejects the gospel.'
        unsupported['message']['content']=json.dumps(draft)
        compiled=synthesis.compile_response(dict(raw_envelope=json.dumps(unsupported),status='verified',digest_after='digest'),spec,'digest')
        self.assertFalse(compiled['semantic_acceptance'])

    def test_raw_replay_detects_resealed_generated_tampering(self):
        spec,r = panel()
        with TemporaryDirectory() as root,patch.object(synthesis,'panel',return_value=(spec,r)),patch.object(synthesis,'directory',return_value=Path(root)):
            result,folder,_,_=synthesis.execute(provider_factory=FakeProvider)
            result['draft']['sections'][0]['sentences'][0]['text']='Changed after generation.'
            synthesis.save(folder/'generated-v1.json',result)
            with self.assertRaisesRegex(ValueError,'raw response'):synthesis.cached()

    def test_cli_prepare_check_only_and_conflicting_flags(self):
        from pastor_transcript_extractor.cli import app
        spec,r = panel()
        with TemporaryDirectory() as root,patch.object(synthesis,'panel',return_value=(spec,r)),patch.object(synthesis,'directory',return_value=Path(root)):
            with patch.object(synthesis,'Provider',FakeProvider):
                ran=CliRunner().invoke(app,['analysis','profile-synthesis','--run','--json'])
            self.assertEqual(0,ran.exit_code,ran.output)
            with patch.object(synthesis,'Provider',side_effect=AssertionError('No backend')),patch.object(Path,'write_text',side_effect=AssertionError('No writes')):
                for flag in ('--prepare','--check-only'):
                    result=CliRunner().invoke(app,['analysis','profile-synthesis',flag,'--json'])
                    self.assertEqual(0,result.exit_code,result.output)
                    self.assertEqual(0,json.loads(result.output)['provider_requests'])
            result=CliRunner().invoke(app,['analysis','profile-synthesis','--prepare','--run'])
            self.assertEqual(2,result.exit_code)

    def test_loopback_only_and_transport_preserves_raw_envelope(self):
        for key,value in (('PTE_LLM_BASE_URL','https://example.com'),('PTE_LLM_ENABLED','0'),('PTE_LLM_MODEL','example:cloud')):
            with patch.dict('os.environ',{key:value}):
                with self.assertRaises(ValueError):synthesis.configuration()
        raw=b'{"model":"synthetic","message":{"content":"{}"}}'
        with patch.object(synthesis,'urlopen',return_value=io.BytesIO(raw)) as call:
            provider=synthesis.Provider();body=dict(model=provider.config.model,stream=False)
            self.assertEqual(raw.decode(),provider.generate(body))
            self.assertTrue(call.call_args.args[0].full_url.endswith('/api/chat'))
            self.assertEqual(body,json.loads(call.call_args.args[0].data))
