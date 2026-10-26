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

    def test_expanded_policy_reserves_full_cost_and_requires_matching_ledger(self):
        _,old=specimen()
        spec=replace(old,body={**old.body,'max_tokens':65536},namespace=provider.EXPANDED_NAMESPACE,
            version=requests.DEEPINFRA_EXPANDED_VERSION,runtime_identity=deepcopy(provider.EXPANDED_POLICY))
        self.assertEqual(provider.reserved_usd(spec.version),Decimal('.2342912'))
        self.assertLess(provider.reserved_usd(spec.version),Decimal('.25'))
        self.assertGreater(spec.preflight()['timeout_seconds'],old.preflight()['timeout_seconds'])
        self.assertLessEqual(spec.preflight()['timeout_seconds'],7200)
        self.assertEqual({k:v for k,v in spec.body.items() if k!='max_tokens'},
                         {k:v for k,v in old.body.items() if k!='max_tokens'})
        with TemporaryDirectory() as directory:
            store=requests.ReceiptStore(Path(directory))
            with self.assertRaisesRegex(ValueError,'explicit paid'):
                requests.execute(spec,provider.OneRequestLedger(),store,lambda s:self.fail('no call'))
            self.assertFalse(store.attempts())
            got=requests.execute(spec,provider.OneRequestLedger('.25',spec.version),store,
                lambda s:response(s,usage=dict(prompt_tokens=100,completion_tokens=20000)))
            self.assertEqual(got['usage']['output_tokens'],20000)
            self.assertEqual(Decimal(store.attempts()[0]['reserved_usd']),Decimal('.2342912'))
        provider.validate(got,spec)
        with self.assertRaisesRegex(ValueError,'outside reservation'):provider.validate(got,old)

    def test_expanded_complete_result_preserves_prior_paid_accounting(self):
        value,old=specimen()
        spec=replace(old,body={**old.body,'max_tokens':65536},namespace=provider.EXPANDED_NAMESPACE,
            version=requests.DEEPINFRA_EXPANDED_VERSION,runtime_identity=deepcopy(provider.EXPANDED_POLICY))
        value.update(request=asdict(spec),history=dict(prior_attempts=29,prior_local_attempts=28,prior_paid_attempts=1,
            prior_source_attempts=25,prior_known_list_price_usage_usd='0.0490698'))
        value['input_fingerprint']=digest(value)
        fake=FakeProvider()
        with TemporaryDirectory() as directory:
            store=requests.ReceiptStore(Path(directory)/'execution')
            result=thinking.run_recipe(value,store,lambda s:response(s,json.dumps(fake(s)['output']),
                usage=dict(prompt_tokens=100,completion_tokens=20000)),ledger=provider.OneRequestLedger('.25',spec.version))
            self.assertEqual(result['contract_fit'],'PASS')
            self.assertEqual(result['accounting']['cumulative_attempts'],30)
            self.assertEqual(result['accounting']['cumulative_paid_attempts'],2)
            self.assertEqual(result['accounting']['cumulative_local_attempts'],28)
            self.assertEqual(Decimal(result['accounting']['cumulative_known_list_price_usage_usd']),Decimal('.1011998'))

    def test_public_model_metadata_is_read_only_and_projects_cap_and_prices(self):
        raw=dict(model_name=provider.MODEL,version='deployment-snapshot',max_tokens=1048576,
            in_schema=dict(properties=dict(max_new_tokens=dict(maximum=1000000))),
            pricing=dict(cents_per_input_token=.00013,cents_per_output_token=.00026))
        with patch('httpx.Client') as factory:
            client=factory.return_value.__enter__.return_value
            client.get.return_value.json.return_value=raw
            metadata=provider.public_model_metadata()
            self.assertEqual(metadata['native_output_schema_maximum'],1000000)
            self.assertEqual(metadata['deployment_version'],'deployment-snapshot')
            client.post.assert_not_called()
            self.assertNotIn('headers',client.get.call_args.kwargs)
            self.assertFalse(factory.call_args.kwargs['trust_env'])

    def test_selected_flash_direct_policy_exact_model_and_five_cent_budget(self):
        _,old=specimen()
        spec=replace(old,body={**old.body,'model':provider.FLASH_MODEL,'reasoning_effort':'none','max_tokens':65536},
            namespace=provider.DIRECT_NAMESPACE,version=requests.DEEPINFRA_DIRECT_VERSION,
            runtime_identity=deepcopy(provider.DIRECT_POLICY))
        self.assertEqual(requests.request_model(spec),'deepseek-ai/DeepSeek-V4.1-Flash-1017')
        self.assertEqual(spec.preflight()['execution_policy']['reasoning_effort'],'none')
        self.assertEqual(provider.reserved_usd(spec.version),Decimal('.049152'))
        for ceiling in ('.06','.04'):
            with self.assertRaises(ValueError):provider.OneRequestLedger(ceiling,spec.version).check([],'source_reading')
        provider.OneRequestLedger('.05',spec.version).check([],'source_reading')
        for body in ({**spec.body,'reasoning_effort':'medium'},{**spec.body,'model':provider.MODEL}):
            with self.assertRaises(ValueError):replace(spec,body=body).preflight()
        with self.assertRaisesRegex(ValueError,'model differs'):
            requests.decode_response(spec,response(spec))

    def test_direct_flash_rejects_unexpected_reasoning_and_never_retries(self):
        _,old=specimen()
        spec=replace(old,body={**old.body,'model':provider.FLASH_MODEL,'reasoning_effort':'none','max_tokens':65536},
            namespace=provider.DIRECT_NAMESPACE,version=requests.DEEPINFRA_DIRECT_VERSION,runtime_identity=deepcopy(provider.DIRECT_POLICY))
        for trace,tokens in [('unexpected',0),('',25)]:
            calls=[]
            def send(s):
                calls.append(s)
                return response(s,model=provider.FLASH_MODEL,
                    choices=[dict(finish_reason='stop',message=dict(content='{}',reasoning_content=trace))],
                    usage=dict(prompt_tokens=100,completion_tokens=200,completion_tokens_details=dict(reasoning_tokens=tokens)))
            with self.subTest(trace=trace,tokens=tokens),TemporaryDirectory() as directory:
                store=requests.ReceiptStore(Path(directory))
                ledger=provider.OneRequestLedger('.05',spec.version)
                with self.assertRaisesRegex(ValueError,'despite frozen disabled'):
                    requests.execute(spec,ledger,store,send)
                with self.assertRaisesRegex(ValueError,'halted'):requests.execute(spec,ledger,store,send)
                self.assertEqual(len(calls),1)

    def test_direct_flash_complete_pipeline_uses_frozen_prices_and_separate_provider_estimate(self):
        value,old=specimen()
        spec=replace(old,body={**old.body,'model':provider.FLASH_MODEL,'reasoning_effort':'none','max_tokens':65536},
            namespace=provider.DIRECT_NAMESPACE,version=requests.DEEPINFRA_DIRECT_VERSION,runtime_identity=deepcopy(provider.DIRECT_POLICY))
        value.update(request=asdict(spec),history=dict(prior_attempts=30,prior_local_attempts=28,prior_paid_attempts=2,
            prior_source_attempts=26,prior_known_list_price_usage_usd='.2259348'))
        value['input_fingerprint']=digest(value)
        fake=FakeProvider()
        def send(s):
            return response(s,model=provider.FLASH_MODEL,
                choices=[dict(finish_reason='stop',message=dict(content=json.dumps(fake(s)['output']),reasoning_content=None))],
                usage=dict(prompt_tokens=100,completion_tokens=200,completion_tokens_details=dict(reasoning_tokens=0),estimated_cost=.0000686))
        with TemporaryDirectory() as directory:
            store=requests.ReceiptStore(Path(directory)/'execution')
            result=thinking.run_recipe(value,store,send,ledger=provider.OneRequestLedger('.05',spec.version))
            self.assertEqual(result['contract_fit'],'PASS');self.assertEqual(result['status'],'INCONCLUSIVE')
            self.assertFalse(result['thinking_emitted'])
            self.assertEqual(result['literal_bound_claims'],2)
            self.assertEqual(result['accounting']['cumulative_attempts'],31)
            self.assertEqual(result['accounting']['cumulative_local_attempts'],28)
            self.assertEqual(result['accounting']['cumulative_paid_attempts'],3)
            self.assertEqual(Decimal(result['accounting']['known_list_price_usage_usd']),Decimal('.00014'))
            self.assertEqual(Decimal(result['accounting']['known_provider_estimated_usage_usd']),Decimal('.0000686'))
            self.assertTrue(all(o['model']==provider.FLASH_MODEL for o in result['observations']))

    def test_direct_cli_routes_explicit_flag_and_displays_selected_model(self):
        from typer.testing import CliRunner
        from pastor_transcript_extractor.cli import app
        value=dict(input_fingerprint='fixture',request=dict(body=dict(model=provider.FLASH_MODEL,reasoning_effort='none')),
            budget={},credentials={})
        with patch.object(hosted,'prepare',return_value=(value,Path('/tmp/fixture'))) as prepare:
            result=CliRunner().invoke(app,['analysis','learning-demo','model-fit','deepinfra-prepare',
                '--from-input','/tmp/prior.json','--no-reasoning','--json'])
            self.assertEqual(result.exit_code,0,result.output)
            self.assertIn(provider.FLASH_MODEL,result.output)
            self.assertTrue(prepare.call_args.kwargs['no_reasoning'])
        with self.assertRaisesRegex(ValueError,'not both'):
            hosted.prepare('/tmp/prior.json',no_reasoning=True,expanded_output=True)
