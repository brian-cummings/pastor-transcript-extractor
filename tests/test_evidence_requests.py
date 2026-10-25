from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from pastor_transcript_extractor.evidence_requests import (
    BudgetLedger, PHASES, ReceiptStore, RequestSpec, execute, reservation,
)
from pastor_transcript_extractor.learning_demo_contracts import generation_request, verification_request, judgments


class Encoding:
    def encode(self,text,**kwargs): return text.encode()


class RequestTests(unittest.TestCase):
    def setUp(self):
        self.request=generation_request('source_reading',{'target_text':'synthetic'}, {'target':'hash'})

    def response(self,spec):
        return dict(model=spec.body['model'],usage=dict(input_tokens=10,output_tokens=10),
                    complete=True,output={'status':'none','claims':[]})

    def test_cache_no_retry_and_namespace_identity(self):
        with TemporaryDirectory() as directory:
            store=ReceiptStore(Path(directory)); calls=[]
            def send(spec): calls.append(spec); return self.response(spec)
            one=execute(self.request,BudgetLedger(),store,send,encoding=Encoding())
            self.assertEqual(one,execute(self.request,BudgetLedger(),store,send,encoding=Encoding()))
            self.assertEqual(len(calls),1)
            self.assertNotEqual(self.request.fingerprint,replace(self.request,namespace='other').fingerprint)

    def test_lost_attempt_stops_even_different_request(self):
        with TemporaryDirectory() as directory:
            store=ReceiptStore(Path(directory)); calls=[]
            def lost(spec): calls.append(1); raise TimeoutError('lost')
            with self.assertRaises(TimeoutError): execute(self.request,BudgetLedger(),store,lost,encoding=Encoding())
            for request in [self.request,replace(self.request,source_identity={'new':'source'})]:
                with self.assertRaisesRegex(ValueError,'lacks receipt'):
                    execute(request,BudgetLedger(),store,lost,encoding=Encoding())
            self.assertEqual(len(calls),1)

    def test_budget_phase_total_and_subceilings(self):
        attempts=[dict(phase=phase,reserved_usd=str(reservation(phase))) for phase in PHASES
                  for _ in range(PHASES[phase][2])]
        from decimal import Decimal
        self.assertEqual(sum(Decimal(r['reserved_usd']) for r in attempts),Decimal('0.090832896'))
        with self.assertRaises(ValueError): BudgetLedger().check(attempts,'source_reading')
        with self.assertRaises(ValueError): BudgetLedger(max_usd='.001').check([],'source_verification')
        with self.assertRaises(ValueError): BudgetLedger(source_max_usd='.001').check([],'source_verification')
        with self.assertRaises(ValueError): BudgetLedger(max_attempts=67).check([],'source_reading')

    def test_overflow_and_model_fallback_rejected_before_send(self):
        request=generation_request('source_reading',{'text':'x'*200000},{})
        with self.assertRaisesRegex(ValueError,'fit failure'): request.preflight(Encoding())
        bad=replace(self.request,body={**self.request.body,'model':'other'})
        with self.assertRaisesRegex(ValueError,'Pinned model'): bad.preflight(Encoding())
        verify=verification_request('source_verification',{'text':'x'*33000},[{'id':'a'}],{},source=True)
        with self.assertRaisesRegex(ValueError,'per-question'): verify.preflight()

    def test_incomplete_receipt_halts_without_fallback(self):
        with TemporaryDirectory() as directory:
            store=ReceiptStore(Path(directory)); count=[]
            def send(spec):
                count.append(1); return {**self.response(spec),'complete':False}
            for _ in range(2):
                with self.assertRaises(ValueError): execute(self.request,BudgetLedger(),store,send,encoding=Encoding())
            self.assertEqual(len(count),1)

    def test_field_checks_strict_and_no_probability_product(self):
        request=verification_request('source_verification',{},[{'id':'a'}],{},source=True)
        response=dict(output={k:dict(type='noul',noul=.9) for k in request.body['questions']})
        self.assertTrue(all(v['resolved'] for v in judgments(response,request)['a'].values()))
        del response['output']['a:voice']
        with self.assertRaises(ValueError): judgments(response,request)

    def test_native_ollama_transport_local_only_and_no_cloud_fallback(self):
        import hashlib,json
        from unittest.mock import patch
        from pastor_transcript_extractor.evidence_requests import ollama_transport,local_ollama_url,validate_response,decode_response
        with TemporaryDirectory() as directory:
            manifest=Path(directory)/'manifest';manifest.write_text('installed-model-identity')
            request=replace(self.request,runtime_identity=dict(model='gemma3:4b',base_url='http://127.0.0.1:11434',
                manifest_path=str(manifest),manifest_sha256=hashlib.sha256(manifest.read_bytes()).hexdigest()))
            raw=dict(model='gemma3:4b',done=True,done_reason='stop',prompt_eval_count=200,eval_count=30,
                     message=dict(content='{"status":"none","claims":[]}'))
            with patch('httpx.Client') as factory:
                client=factory.return_value.__enter__.return_value
                client.post.return_value.status_code=200;client.post.return_value.text=json.dumps(raw)
                response=decode_response(request,ollama_transport(request))
                self.assertTrue(response['complete']);validate_response(request,response)
                args=client.post.call_args
                self.assertEqual(args.args[0],'http://127.0.0.1:11434/api/chat')
                self.assertNotIn('headers',args.kwargs)
                self.assertEqual(args.kwargs['json']['model'],'gemma3:4b')
                self.assertFalse(factory.call_args.kwargs['trust_env'])
                self.assertFalse(factory.call_args.kwargs['follow_redirects'])
                raw['done_reason']='length';client.post.return_value.text=json.dumps(raw)
                with self.assertRaisesRegex(ValueError,'Incomplete'):decode_response(request,ollama_transport(request))
            manifest.write_text('changed-model-identity')
            with patch('httpx.Client') as factory:
                with self.assertRaisesRegex(ValueError,'tag changed'):ollama_transport(request)
                factory.assert_not_called()
        for url in ('https://ollama.com','http://api.openai.com','http://localhost:11434/proxy','http://key@localhost:11434'):
            with self.assertRaisesRegex(ValueError,'local loopback'):local_ollama_url(url)

    def test_wire_failures_preserved_and_never_retried(self):
        import json
        from pastor_transcript_extractor.evidence_requests import WireResponse
        valid=dict(model='gemma3:4b',done=True,done_reason='stop',prompt_eval_count=20,
                   eval_count=10,message=dict(content='{}'))
        cases=[(200,json.dumps(dict(done=True,done_reason=reason)),'Incomplete')
               for reason in ('load','length','cancel',None)]
        cases += [(200,json.dumps({k:v for k,v in valid.items() if k!=field}),field)
                  for field in ('prompt_eval_count','eval_count')]
        cases += [(200,'',''),(200,'{invalid',''),(200,'[]','object'),(503,'unavailable','HTTP 503')]
        for status,body,reason in cases:
            with self.subTest(status=status,body=body),TemporaryDirectory() as directory:
                store=ReceiptStore(Path(directory));calls=[]
                def send(spec): calls.append(spec);return WireResponse(status,body)
                with self.assertRaisesRegex(ValueError,reason):execute(self.request,BudgetLedger(),store,send)
                key=self.request.fingerprint
                saved=json.loads((store.root/'wire-responses'/f'{key}.json').read_text())
                self.assertEqual(saved,dict(status_code=status,text=body))
                receipt=json.loads((store.root/'receipts'/f'{key}.json').read_text())
                self.assertTrue(receipt['halt']);self.assertTrue(receipt['wire_response_digest'])
                with self.assertRaisesRegex(ValueError,'Prior receipt halted'):
                    execute(self.request,BudgetLedger(),store,send)
                self.assertEqual(len(calls),1)
                from pastor_transcript_extractor.learning_demo import usage_account
                self.assertEqual(usage_account(store)['unknown_usage_attempts'],1)

    def test_paid_wire_usage_remains_required(self):
        import json
        from pastor_transcript_extractor.evidence_requests import WireResponse
        request=verification_request('source_verification',{},[{'id':'a'}],{},source=True)
        with TemporaryDirectory() as directory:
            store=ReceiptStore(Path(directory))
            with self.assertRaises(ValueError):
                execute(request,BudgetLedger(),store,lambda spec:WireResponse(200,json.dumps(
                    dict(model=spec.body['model'],answers={}))))
            self.assertEqual(len(store.attempts()),1)
            self.assertTrue(list((store.root/'receipts').glob('*.json')))

    def test_installed_ollama_identity_requires_exact_blob_hash_and_model(self):
        import hashlib,json,os
        from unittest.mock import patch
        from pastor_transcript_extractor.evidence_requests import ollama_runtime_identity
        with TemporaryDirectory() as directory:
            root=Path(directory);(root/'blobs').mkdir()
            data=b'fixture weights, not an actual model';sha=hashlib.sha256(data).hexdigest()
            blob=root/'blobs'/('sha256-'+sha);blob.write_bytes(data)
            manifest=root/'manifests/registry.ollama.ai/library/gemma3/4b'
            manifest.parent.mkdir(parents=True)
            manifest.write_text(json.dumps(dict(config=dict(mediaType='fixture',digest='sha256:'+sha,size=len(data)),layers=[])))
            env=dict(OLLAMA_MODELS=str(root),PTE_LLM_MODEL='gemma3:4b',PTE_LLM_BASE_URL='http://127.0.0.1:11434')
            with patch.dict(os.environ,env):
                identity=ollama_runtime_identity()
                self.assertEqual(identity['model'],'gemma3:4b')
                self.assertEqual(identity['blobs'][0]['sha256'],sha)
                blob.write_bytes(b'x'*len(data))
                with self.assertRaisesRegex(ValueError,'blob differs'):ollama_runtime_identity()
                with patch.dict(os.environ,dict(PTE_LLM_MODEL='gemma3:12b')):
                    with self.assertRaisesRegex(ValueError,'no substitution'):ollama_runtime_identity()

    def test_local_preflight_ignores_openai_tokenizer_and_rejects_context_drift(self):
        from pastor_transcript_extractor.evidence_requests import ollama_context_for
        account=self.request.preflight()
        self.assertFalse(account['exact_token_count_known'])
        self.assertEqual(account['num_ctx'],ollama_context_for(self.request.body))
        self.assertGreaterEqual(account['num_ctx'],account['reserved_input']+account['output_cap'])
        for field,value in [('num_ctx',4096),('num_predict',1),('temperature',1)]:
            body={**self.request.body,'options':{**self.request.body['options'],field:value}}
            with self.assertRaisesRegex(ValueError,'limits differ'):replace(self.request,body=body).preflight()
        self.assertEqual(reservation('source_reading'),0)
        self.assertEqual(reservation('alignment_and_interpretation'),0)
        self.assertEqual(reservation('narratives_and_pair_report'),0)


class IncompleteUsageTests(unittest.TestCase):
    def test_length_stop_usage_is_measured_without_accepting_response(self):
        import json
        from pastor_transcript_extractor.evidence_requests import WireResponse
        from pastor_transcript_extractor.learning_demo import usage_account
        request=generation_request('source_reading',{'target_text':'synthetic'},{})
        raw=dict(model='gemma3:4b',done=True,done_reason='length',prompt_eval_count=42,eval_count=8192,
                 message=dict(content='{unfinished'))
        with TemporaryDirectory() as directory:
            store=ReceiptStore(Path(directory))
            with self.assertRaisesRegex(ValueError,'Incomplete'):
                execute(request,BudgetLedger(),store,lambda spec:WireResponse(200,json.dumps(raw)))
            result=usage_account(store)
            self.assertEqual(result['known_input_tokens'],42)
            self.assertEqual(result['known_output_tokens'],8192)
            self.assertEqual(result['unknown_usage_attempts'],0)
            self.assertEqual(result['paid_attempts'],0)
            with self.assertRaisesRegex(ValueError,'Prior receipt halted'):
                execute(request,BudgetLedger(),store,lambda spec:self.fail('must not retry'))
