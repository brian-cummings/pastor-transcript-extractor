from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import json
import unittest
import httpx
from pastor_transcript_extractor import deepinfra_streaming as streaming
from pastor_transcript_extractor import deepinfra_requests as provider
from pastor_transcript_extractor import evidence_requests as requests
from pastor_transcript_extractor import learning_demo as accounting
from pastor_transcript_extractor import profile_analysis_support_execution as support
from test_profile_analysis_support import plan


def spec(threshold=256):
    with patch.dict('os.environ',PTE_DEEPINFRA_WHITESPACE_THRESHOLD=str(threshold)):
        return support.make_request(plan()['items'][0]['case'])


def chunk(s,text=None,*,finish=None,usage=None,model=True):
    data=dict(choices=[dict(index=0,delta={} if text is None else dict(content=text),finish_reason=finish)])
    if model:data['model']=s.body['model']
    if usage is not None:data['usage']=usage
    return ('data: '+json.dumps(data)+'\n\n').encode()


class Body(httpx.SyncByteStream):
    def __init__(self,chunks):self.chunks=chunks;self.closed=False;self.read=0
    def __iter__(self):
        for c in self.chunks:self.read+=1;yield c
    def close(self):self.closed=True


class Harness:
    def __init__(self,s,bodies):self.spec=s;self.bodies=bodies;self.requests=[];self.streams=[];self.clients=[]
    def handler(self,request):
        if self.streams:assert self.streams[-1].closed, 'Previous stream still open at retry'
        body=json.loads(request.content);self.requests.append(body)
        assert body=={**self.spec.body,'stream':True}
        stream=Body(self.bodies[len(self.requests)-1]);self.streams.append(stream)
        return httpx.Response(200,stream=stream)
    def client(self):
        client=httpx.Client(transport=httpx.MockTransport(self.handler));self.clients.append(client);return client
    def run(self,**kwargs):
        return streaming.transport(self.spec,key='sensitive-test-key',timeout=20,threshold=self.spec.runtime_identity['stream_recovery']['whitespace_threshold'],client_factory=self.client,**kwargs)
    def managed(self):
        def transport(s,**kwargs):return self.run(**kwargs)
        transport.supports_stream_callbacks=True
        return transport


def normal(s,content='{"value":true}'):
    return [b': keepalive\n\n',chunk(s,content),chunk(s,finish='stop',usage=dict(prompt_tokens=100,completion_tokens=10,estimated_cost='.00001')),b'data: [DONE]\n\n']


def loop(s):
    return [chunk(s,'{"value":'),chunk(s,' '*100),chunk(s,' '*100),chunk(s,' '*100),chunk(s,'SHOULD_NOT_BE_READ')]


class DetectorTests(unittest.TestCase):
    def test_threshold_exactly_allowed_then_exceeded_across_chunks(self):
        d=streaming.JSONWhitespaceDetector();d.feed('{');d.feed(' '*128);d.feed('\n'*128)
        self.assertEqual(d.consecutive,256)
        with self.assertRaises(streaming.WhitespaceLoop):d.feed('\t')

    def test_strings_escaped_quotes_and_backslashes_across_chunks(self):
        value=json.dumps(dict(value='a"'+(' '*1000)+'\\"'+(' '*1000)))
        d=streaming.JSONWhitespaceDetector()
        for c in value:d.feed(c)
        self.assertFalse(d.in_string);self.assertEqual(d.consecutive,0)

    def test_nonwhitespace_resets_and_empty_deltas_do_not(self):
        d=streaming.JSONWhitespaceDetector(3);d.feed('  ');d.feed('');d.feed('x  ');self.assertEqual(d.consecutive,2)
        with self.assertRaises(streaming.WhitespaceLoop):d.feed('  ')
        for value in (0,-1,True,2.5):
            with self.assertRaises(ValueError):streaming.JSONWhitespaceDetector(value)


class StreamingTransportTests(unittest.TestCase):
    def test_normal_response_is_assembled_into_existing_interface(self):
        s=spec();h=Harness(s,[normal(s)]);raw=h.run()
        response=requests.decode_response(s,raw);requests.validate_response(s,response)
        self.assertEqual(json.loads(response['output']),dict(value=True))
        self.assertEqual(response['usage'],dict(input_tokens=100,output_tokens=10))
        self.assertTrue(h.streams[0].closed);self.assertTrue(h.clients[0].is_closed)
        self.assertFalse(s.body['stream']);self.assertTrue(h.requests[0]['stream'])
        self.assertEqual(response['raw']['_pte_transport']['retry_outcome'],'not_needed')

    def test_legitimate_string_whitespace_and_pretty_json_are_not_cancelled(self):
        s=spec();value=json.dumps(dict(value='quoted "'+' '*1200+'\\'))
        h=Harness(s,[[chunk(s,value[:8]),chunk(s,value[8:17]),chunk(s,value[17:]),chunk(s,finish='stop',usage=dict(prompt_tokens=100,completion_tokens=100)),b'data: [DONE]\n\n']])
        response=requests.decode_response(s,h.run(maximum_attempts=2))
        self.assertEqual(json.loads(response['output']),json.loads(value));self.assertEqual(len(h.requests),1)

    def test_loop_is_cancelled_immediately_and_retry_is_identical(self):
        s=spec();h=Harness(s,[loop(s),normal(s)])
        raw=h.run(maximum_attempts=2);response=requests.decode_response(s,raw)
        self.assertEqual(h.streams[0].read,4);self.assertTrue(all(b.closed for b in h.streams))
        self.assertTrue(all(c.is_closed for c in h.clients));self.assertEqual(h.requests[0],h.requests[1])
        self.assertEqual(h.requests[0]['temperature'],0)
        meta=response['raw']['_pte_transport'];self.assertEqual(meta['retry_outcome'],'recovered')
        self.assertTrue(meta['attempts'][0]['cancelled']);self.assertFalse(meta['attempts'][0]['usage_available'])
        self.assertIsNotNone(meta['attempts'][1]['first_content_seconds'])

    def test_retry_exhaustion_never_becomes_complete(self):
        s=spec();h=Harness(s,[loop(s),loop(s)])
        raw=h.run(maximum_attempts=2);self.assertEqual(len(h.requests),2)
        self.assertEqual(json.loads(raw.text)['_pte_transport']['retry_outcome'],'exhausted')
        with self.assertRaisesRegex(ValueError,'Incomplete'):requests.decode_response(s,raw)

    def test_incomplete_finish_missing_done_missing_usage_and_wrong_model_rejected(self):
        s=spec()
        cases=[normal(s)[:-1],[chunk(s,'{}'),chunk(s,finish='length',usage=dict(prompt_tokens=100,completion_tokens=2048)),b'data: [DONE]\n\n'],[chunk(s,'{}'),chunk(s,finish='stop'),b'data: [DONE]\n\n'],[b'data: {"model":"wrong","choices":[]}\n\n']]
        for body in cases:
            h=Harness(s,[body]);raw=h.run(maximum_attempts=2)
            with self.assertRaises((ValueError,KeyError)):
                response=requests.decode_response(s,raw);requests.validate_response(s,response)
            self.assertEqual(len(h.requests),1);self.assertTrue(h.streams[0].closed)

    def test_heartbeats_do_not_extend_the_original_deadline(self):
        s=spec();clock=[0];streams=[]
        class Heartbeats(Body):
            def __iter__(self):
                yield b': keepalive\n\n'
                clock[0]=11
                yield b': keepalive\n\n'
                self.fail_if_read_further=True
        def handler(request):
            b=Heartbeats([]);streams.append(b);return httpx.Response(200,stream=b)
        raw=streaming.transport(s,key='test',timeout=10,maximum_attempts=2,clock=lambda:clock[0],client_factory=lambda:httpx.Client(transport=httpx.MockTransport(handler)))
        self.assertTrue(streams[0].closed);self.assertEqual(len(streams),1)
        self.assertIn('deadline exceeded',raw.text)

    def test_read_error_and_http_error_close_without_retry(self):
        s=spec()
        class Broken(Body):
            def __iter__(self):yield chunk(s,'{');raise httpx.ReadError('socket closed')
        streams=[]
        def handler(request):
            b=Broken([]);streams.append(b);return httpx.Response(200,stream=b)
        raw=streaming.transport(s,key='test',timeout=10,maximum_attempts=2,client_factory=lambda:httpx.Client(transport=httpx.MockTransport(handler)))
        self.assertTrue(streams[0].closed);self.assertEqual(len(streams),1)
        self.assertIn('ReadError',raw.text)
        responses=[]
        def fail(request):
            r=httpx.Response(503,stream=Body([]));responses.append(r);return r
        raw=streaming.transport(s,key='test',timeout=10,maximum_attempts=2,client_factory=lambda:httpx.Client(transport=httpx.MockTransport(fail)))
        self.assertEqual(raw.status_code,503);self.assertTrue(responses[0].is_closed)

    def test_deadline_exhaustion_does_not_start_recovery(self):
        s=spec();h=Harness(s,[loop(s)])
        clock=[0]
        def after(*args):clock[0]=21
        raw=streaming.transport(s,key='test',timeout=20,maximum_attempts=2,after_attempt=after,client_factory=h.client,clock=lambda:clock[0])
        self.assertEqual(len(h.requests),1)
        self.assertEqual(json.loads(raw.text)['_pte_transport']['retry_outcome'],'blocked_by_budget_or_deadline')


class StreamingExecutorTests(unittest.TestCase):
    def test_recovery_journal_accounting_and_cache_only_final_complete_response(self):
        s=spec();h=Harness(s,[loop(s),normal(s)])
        with TemporaryDirectory() as folder:
            store=requests.ReceiptStore(Path(folder));ledger=provider.OneRequestLedger(str(provider.reserved_usd(s.version)),s.version)
            result=requests.execute(s,ledger,store,h.managed())
            self.assertTrue(result['complete']);self.assertEqual(len(h.requests),2)
            count=accounting.usage_account(store)
            self.assertEqual(count['paid_attempts'],2);self.assertEqual(count['attempts'],2)
            self.assertEqual(count['unknown_usage_attempts'],1);self.assertEqual(count['known_input_tokens'],100)
            self.assertEqual(Decimal(count['reserved_usd']),2*provider.reserved_usd(s.version.removesuffix('-stream-v1')))
            first=json.loads((Path(folder)/'stream-attempts'/s.fingerprint/'1/telemetry.json').read_text())
            self.assertTrue(first['cancelled']);self.assertTrue(first['connection_closed'])
            self.assertFalse((Path(folder)/'stream-attempts'/s.fingerprint/'1/receipts').exists())
            cached=requests.execute(s,ledger,store,lambda _:self.fail('no more calls'));self.assertEqual(cached,result)
            self.assertNotIn('sensitive-test-key',''.join(p.read_text() for p in Path(folder).rglob('*.json')))

    def test_exhausted_streams_are_failed_receipts_never_success_cache(self):
        s=spec();h=Harness(s,[loop(s),loop(s)])
        with TemporaryDirectory() as folder:
            store=requests.ReceiptStore(Path(folder));ledger=provider.OneRequestLedger('.04',s.version)
            with self.assertRaises(ValueError):requests.execute(s,ledger,store,h.managed())
            receipt=json.loads((store.root/'receipts'/f'{s.fingerprint}.json').read_text())
            self.assertTrue(receipt['halt']);self.assertIsNone(receipt['response'])
            self.assertEqual(accounting.usage_account(store)['unknown_usage_attempts'],2)
            with self.assertRaises(ValueError):requests.execute(s,ledger,store,lambda _:self.fail('no retry'))

    def test_budget_checked_before_any_connection_and_legacy_reservation_unchanged(self):
        s=spec();h=Harness(s,[normal(s)])
        with TemporaryDirectory() as folder:
            with self.assertRaisesRegex(ValueError,'reservation exceeds'):requests.execute(s,provider.OneRequestLedger('.01',s.version),requests.ReceiptStore(Path(folder)),h.managed())
            self.assertEqual(h.requests,[])
        base=s.version.removesuffix('-stream-v1')
        self.assertEqual(provider.reserved_usd(base),Decimal('.0083968'))
        self.assertEqual(provider.preflight(s)['stream_recovery']['maximum_attempts'],2)
        big=replace(s,version=requests.DEEPINFRA_ANALYSIS_SUPPORT_VERSIONS[-1],namespace=requests.DEEPINFRA_ANALYSIS_SUPPORT_VERSIONS[-1],runtime_identity=provider.ANALYSIS_SUPPORT_POLICIES[requests.DEEPINFRA_ANALYSIS_SUPPORT_VERSIONS[-1]])
        protected=provider.streaming_request(big)
        self.assertEqual(protected.preflight()['stream_recovery']['maximum_attempts'],1)
        self.assertLessEqual(provider.reserved_usd(protected.version),Decimal('.04'))

    def test_interrupted_recovery_keeps_both_reservations_and_never_resends(self):
        s=spec();h=Harness(s,[loop(s)]);client=h.client
        def interrupted():
            if h.requests:raise KeyboardInterrupt()
            return client()
        h.client=interrupted
        with TemporaryDirectory() as folder:
            store=requests.ReceiptStore(Path(folder));ledger=provider.OneRequestLedger('.04',s.version)
            with self.assertRaises(KeyboardInterrupt):requests.execute(s,ledger,store,h.managed())
            count=accounting.usage_account(store)
            self.assertEqual(count['paid_attempts'],2);self.assertEqual(count['unknown_usage_attempts'],2)
            with self.assertRaisesRegex(ValueError,'lacks receipt'):requests.execute(s,ledger,store,lambda _:self.fail('no third request'))

    def test_incomplete_stream_is_not_successfully_cached(self):
        s=spec();h=Harness(s,[normal(s)[:-1]])
        with TemporaryDirectory() as folder:
            store=requests.ReceiptStore(Path(folder));ledger=provider.OneRequestLedger('.04',s.version)
            with self.assertRaises(ValueError):requests.execute(s,ledger,store,h.managed())
            receipt=json.loads((store.root/'receipts'/f'{s.fingerprint}.json').read_text())
            self.assertIsNone(receipt['response']);self.assertTrue(receipt['halt'])
            self.assertEqual(len(h.requests),1)

    def test_tampered_cancelled_usage_is_detected(self):
        s=spec();h=Harness(s,[loop(s),normal(s)])
        with TemporaryDirectory() as folder:
            store=requests.ReceiptStore(Path(folder))
            requests.execute(s,provider.OneRequestLedger('.04',s.version),store,h.managed())
            path=store.root/'stream-attempts'/s.fingerprint/'1/wire.json'
            raw=json.loads(path.read_text());raw['text']='{}';path.write_text(json.dumps(raw))
            with self.assertRaisesRegex(ValueError,'Corrupt streaming'):accounting.usage_account(store)

    def test_config_is_frozen_and_read_only_cli_makes_no_provider_calls(self):
        from typer.testing import CliRunner
        from pastor_transcript_extractor.cli import app
        s=spec(17);self.assertEqual(s.preflight()['stream_recovery']['whitespace_threshold'],17)
        with patch.dict('os.environ',PTE_DEEPINFRA_WHITESPACE_THRESHOLD='bad'):
            self.assertEqual(s.preflight()['stream_recovery']['whitespace_threshold'],17)
        with patch.dict('os.environ',PTE_DEEPINFRA_WHITESPACE_THRESHOLD='17'),patch.object(provider,'transport',side_effect=AssertionError('no paid call')):
            result=CliRunner().invoke(app,['analysis','profile-support','transport-info','--json'])
            self.assertEqual(result.exit_code,0,result.output)
            self.assertEqual(json.loads(result.output)['whitespace_threshold'],17)
            self.assertEqual(json.loads(result.output)['generation_calls'],0)
