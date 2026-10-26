from copy import deepcopy
from dataclasses import asdict, replace
from decimal import Decimal
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from pastor_transcript_extractor import deepinfra_requests as provider
from pastor_transcript_extractor import evidence_requests as requests
from pastor_transcript_extractor import learning_demo_deepinfra_fit as hosted
from pastor_transcript_extractor import learning_demo_thinking_check as thinking
from pastor_transcript_extractor import learning_demo as demo
from pastor_transcript_extractor.pastor_evidence import digest
from test_learning_demo_model_fit import packet
from test_learning_demo import FakeProvider


def specimen():
    original=packet();old=requests.RequestSpec(**original['source_requests'][0]['request'])
    body=dict(model=provider.MODEL,messages=old.body['messages'],temperature=0,top_p=1,n=1,
        stream=False,reasoning_effort='medium',max_tokens=provider.OUTPUT_CAP,
        response_format=dict(type='json_schema',json_schema=dict(name='qualified_source_reading',strict=True,schema=thinking.schema())))
    spec=requests.RequestSpec('source_reading',body,old.source_identity,namespace=provider.NAMESPACE,
        version=requests.DEEPINFRA_VERSION,runtime_identity=deepcopy(provider.POLICY))
    value=dict(request=asdict(spec),window=original['windows'][0],schema=thinking.schema(),limitation='synthetic only',
        history=dict(prior_attempts=28,prior_source_attempts=24))
    value['input_fingerprint']=digest(value)
    return value,spec


def response(spec,content='{"status":"none","claims":[]}',**changes):
    raw=dict(model=provider.MODEL,choices=[dict(finish_reason='stop',message=dict(content=content,reasoning_content='synthetic reasoning'))],
        usage=dict(prompt_tokens=100,completion_tokens=200))
    return requests.WireResponse(200,json.dumps({**raw,**changes}))


class DeepInfraTests(unittest.TestCase):
    def test_paid_reservation_and_opt_in_cannot_expand_existing_budget(self):
        _,spec=specimen()
        self.assertEqual(provider.reserved_usd(),Decimal('0.1277952'))
        self.assertEqual(spec.preflight()['reserved_usd'],'0.1277952')
        for value in ('0','.10','.26','NaN','Infinity','invalid'):
            with self.subTest(value=value),self.assertRaises(ValueError):provider.OneRequestLedger(value).check([],'source_reading')
        with self.assertRaisesRegex(ValueError,'One DeepInfra'):provider.OneRequestLedger().check([{}],'source_reading')
        with TemporaryDirectory() as directory:
            store=requests.ReceiptStore(Path(directory))
            with self.assertRaisesRegex(ValueError,'explicit paid'):
                requests.execute(spec,requests.BudgetLedger(),store,lambda s:self.fail('no send'))
            self.assertEqual(store.attempts(),[])

    def test_transport_fixed_tls_no_redirect_proxy_retry_or_key_in_body(self):
        _,spec=specimen()
        with patch.dict(os.environ,{'DEEPINFRA_API_KEY':'synthetic-secret'}),patch('httpx.Client') as factory,\
             patch('httpx.HTTPTransport') as http_transport:
            client=factory.return_value.__enter__.return_value
            client.post.return_value.status_code=200;client.post.return_value.text=response(spec).text
            requests.decode_response(spec,provider.transport(spec))
            self.assertEqual(client.post.call_args.args[0],provider.ENDPOINT)
            self.assertEqual(client.post.call_args.kwargs['headers']['Authorization'],'Bearer synthetic-secret')
            self.assertNotIn('synthetic-secret',json.dumps(client.post.call_args.kwargs['json']))
            self.assertFalse(factory.call_args.kwargs['follow_redirects'])
            self.assertFalse(factory.call_args.kwargs['trust_env'])
            self.assertEqual(http_transport.call_args.kwargs['retries'],0)
            self.assertEqual(factory.call_args.kwargs['timeout'],spec.preflight()['timeout_seconds'])
        for changed in (replace(spec,namespace='learning-demo-v3'),replace(spec,runtime_identity={**provider.POLICY,'endpoint':'https://other.test'}),
                        replace(spec,body={**spec.body,'service_tier':'priority'}),replace(spec,body={**spec.body,'model':'other'})):
            with self.assertRaises(ValueError):changed.preflight()

    def test_immutable_wire_cache_paid_accounting_and_no_secret_artifacts(self):
        _,spec=specimen();calls=[]
        def send(s):calls.append(s);return response(s)
        with TemporaryDirectory() as directory:
            store=requests.ReceiptStore(Path(directory))
            first=requests.execute(spec,provider.OneRequestLedger(),store,send)
            self.assertEqual(requests.execute(spec,provider.OneRequestLedger(),store,send),first)
            self.assertEqual(len(calls),1)
            account=demo.usage_account(store)
            self.assertEqual(account['paid_attempts'],1);self.assertEqual(account['local_attempts'],0)
            self.assertEqual(account['openai_calls'],0)
            self.assertEqual(Decimal(account['reserved_usd']),provider.reserved_usd())
            self.assertEqual(Decimal(account['known_list_price_usage_usd']),Decimal('.00065'))
            self.assertEqual(account['unknown_usage_attempts'],0)
            other=replace(spec,source_identity={'other':'case'})
            with self.assertRaisesRegex(ValueError,'One DeepInfra'):
                requests.execute(other,provider.OneRequestLedger(),store,send)
            self.assertEqual(len(calls),1)
            self.assertNotIn('Authorization',''.join(p.read_text() for p in store.root.rglob('*.json')))

    def test_length_response_preserves_billed_usage_and_halts(self):
        _,spec=specimen();calls=[]
        def send(s):
            calls.append(s)
            return response(s,choices=[dict(finish_reason='length',message=dict(content='',reasoning_content='partial reasoning'))],
                            usage=dict(prompt_tokens=100,completion_tokens=provider.OUTPUT_CAP))
        with TemporaryDirectory() as directory:
            store=requests.ReceiptStore(Path(directory))
            with self.assertRaisesRegex(ValueError,'Incomplete DeepInfra'):requests.execute(spec,provider.OneRequestLedger(),store,send)
            self.assertEqual(demo.usage_account(store)['known_output_tokens'],provider.OUTPUT_CAP)
            with self.assertRaisesRegex(ValueError,'halted'):requests.execute(spec,provider.OneRequestLedger(),store,send)
            self.assertEqual(len(calls),1)

    def test_timeout_and_http_errors_never_retry_or_release_reservations(self):
        for error in ('timeout','http'):
            _,spec=specimen();calls=[]
            def send(s):
                calls.append(s)
                if error=='timeout':raise TimeoutError('synthetic timeout')
                return requests.WireResponse(401,'{"error":"unauthorized"}')
            with self.subTest(error=error),TemporaryDirectory() as directory:
                store=requests.ReceiptStore(Path(directory))
                with self.assertRaises((ValueError,TimeoutError)):requests.execute(spec,provider.OneRequestLedger(),store,send)
                with self.assertRaises(ValueError):requests.execute(spec,provider.OneRequestLedger(),store,send)
                self.assertEqual(len(calls),1)
                account=demo.usage_account(store)
                self.assertEqual(account['paid_attempts'],1)
                self.assertEqual(account['unknown_usage_attempts'],1)
                self.assertEqual(Decimal(account['reserved_usd']),provider.reserved_usd())

    def test_wrong_model_usage_refusal_tier_and_schema_rejected(self):
        _,spec=specimen()
        for override in (dict(model='other'),dict(service_tier='priority'),
                         dict(choices=[dict(finish_reason='stop',message=dict(content='{}',refusal='no'))]),
                         dict(usage=dict(prompt_tokens=100,completion_tokens=provider.OUTPUT_CAP+1))):
            with self.subTest(override=override),self.assertRaises(ValueError):
                requests.validate_response(spec,requests.decode_response(spec,response(spec,**override)))
        value,spec=specimen()
        with TemporaryDirectory() as directory:
            result=thinking.run_recipe(value,requests.ReceiptStore(Path(directory)/'execution'),
                lambda s:response(s,'{}'),ledger=provider.OneRequestLedger())
            self.assertEqual(result['contract_fit'],'FAIL(component)')

    def test_full_one_window_stub_uses_same_compiler_and_no_reasoning_evidence(self):
        value,spec=specimen();fake=FakeProvider()
        def send(s):return response(s,json.dumps(fake(s)['output']))
        with TemporaryDirectory() as directory:
            store=requests.ReceiptStore(Path(directory)/'execution')
            result=thinking.run_recipe(value,store,send,ledger=provider.OneRequestLedger())
            self.assertEqual(result['contract_fit'],'PASS');self.assertEqual(result['status'],'INCONCLUSIVE')
            self.assertEqual(result['literal_bound_claims'],2)
            self.assertEqual(result['accounting']['cumulative_attempts'],29)
            self.assertEqual(result['accounting']['cumulative_local_attempts'],28)
            self.assertEqual(result['accounting']['cumulative_paid_attempts'],1)
            self.assertTrue(result['thinking_emitted'])
            self.assertNotIn('synthetic reasoning',json.dumps(result['observations']))
            self.assertTrue(all(o['production_admission']=='not_admitted' for o in result['observations']))

    def test_no_credentials_preflight_and_missing_key_does_not_consume_attempt(self):
        value,spec=specimen();value.update(budget={},token_account=spec.preflight())
        with TemporaryDirectory() as directory,patch.object(hosted,'verify',return_value=(value,Path(directory)/'prior/marker.json')),\
             patch.dict(os.environ,{'DEEPINFRA_API_KEY':''}),patch.object(provider,'transport') as send:
            path=Path(directory)/'input.json'
            result=hosted.run(path,check_only=True)
            self.assertFalse(result['credential_configured']);self.assertEqual(result['provider_calls'],0)
            with self.assertRaisesRegex(ValueError,'no attempts started'):
                hosted.run(path,experimental=True,approve_input=value['input_fingerprint'],confirm_prices=True)
            self.assertFalse((path.parent/'execution').exists());send.assert_not_called()

    def test_cli_routes_preflight_and_requires_execution_flags(self):
        from typer.testing import CliRunner
        from pastor_transcript_extractor.cli import app
        runner=CliRunner()
        with patch.object(hosted,'run',return_value=dict(status='PREPARED_NO_EXECUTION',provider_calls=0)) as run:
            result=runner.invoke(app,['analysis','learning-demo','model-fit','deepinfra-run','--input','/tmp/synthetic.json','--check-only','--json'])
            self.assertEqual(result.exit_code,0,result.output)
            self.assertTrue(run.call_args.kwargs['check_only']);self.assertFalse(run.call_args.kwargs['confirm_prices'])

    def test_frozen_recipe_and_one_input_marker_are_enforced(self):
        with TemporaryDirectory() as directory:
            base=Path(directory)
            value=dict(schema_version=hosted.VERSION,history=dict(prior_input=str(base/'prior/input.json')))
            value['input_fingerprint']=digest(value)
            out=hosted.directory(base,value['input_fingerprint']);out.mkdir(parents=True)
            path=out/'input.json';path.write_text(json.dumps(value))
            with patch.object(hosted,'prepare',return_value=(value,out)):
                self.assertEqual(hosted.verify(path,base)[0],value)
                marker=base/'prior/execution/deepinfra-fit-authorization.json';marker.parent.mkdir(parents=True)
                marker.write_text(json.dumps(dict(input_fingerprint='other')))
                with self.assertRaisesRegex(ValueError,'already assigned'):hosted.verify(path,base)
            with patch.object(hosted,'prepare',return_value=({**value,'changed_prices':True},out)):
                with self.assertRaisesRegex(ValueError,'changed after freeze'):hosted.verify(path,base)
            value['modified']=True;path.write_text(json.dumps(value))
            with self.assertRaisesRegex(ValueError,'identity or location'):hosted.verify(path,base)

    def test_paid_run_flags_and_ceiling_are_checked_before_transport(self):
        value,spec=specimen()
        with TemporaryDirectory() as directory,patch.object(hosted,'verify',return_value=(value,Path(directory)/'marker.json')),\
             patch.object(provider,'transport') as send:
            for flags in ({},{'experimental':True,'approve_input':'wrong','confirm_prices':True},
                          {'experimental':True,'approve_input':value['input_fingerprint']},
                          {'experimental':True,'approve_input':value['input_fingerprint'],'confirm_prices':True,'max_usd':'1'}):
                with self.subTest(flags=flags),self.assertRaises(ValueError):hosted.run(Path(directory)/'input.json',**flags)
            send.assert_not_called()
            self.assertFalse((Path(directory)/'marker.json').exists())
