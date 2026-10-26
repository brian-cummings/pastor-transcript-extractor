from copy import deepcopy
from dataclasses import asdict,replace
from decimal import Decimal
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from typer.testing import CliRunner
from pastor_transcript_extractor.cli import app
from pastor_transcript_extractor import source_enum_check as c
from test_learning_demo_correction import wire_response


def answer():
    quote=dict(source_field='target_text',text=c.SOURCE)
    return dict(claims=[dict(address_acts=[dict(addressee=dict(kind='direct_current_listener',evidence=[quote]),
        adoption='own_or_adopted')],adoption=dict(status='own_assertion',basis='own_speech',
            evidence=[quote],rationale='The synthetic speaker directly gives this instruction in their own voice.'))])


def packet():
    value=dict(request=asdict(c.request()),history=dict(prior_attempts=66,prior_local_attempts=28,
        prior_paid_attempts=38,prior_known_list_price_usage_usd='0.322717632'))
    value['input_fingerprint']=c.digest(value)
    return value


class EnumCheckTests(unittest.TestCase):
    def test_guide_is_derived_and_preserves_distinct_shapes_and_enum_meanings(self):
        spec=c.request();guide='\n'.join(c.field_guide(c.schema()))
        self.assertIn('$.claims[].address_acts[].adoption: string',guide)
        self.assertIn('$.claims[].adoption: object',guide)
        self.assertIn('own_or_adopted',guide);self.assertIn('own_assertion',guide)
        original=c.source_context.schema()['properties']['claims']['items']['properties']
        reduced=c.schema()['properties']['claims']['items']['properties']
        self.assertEqual(reduced['adoption'],original['adoption'])
        self.assertEqual(reduced['address_acts']['items']['properties']['adoption'],original['address_acts']['items']['properties']['adoption'])
        self.assertEqual(c.requests.request_provider(spec),'DeepInfra')
        self.assertLessEqual(spec.preflight()['request_upper_bound'],8192)
        self.assertEqual(c.hosted.reserved_usd(spec.version),Decimal('0.0022528'))
        self.assertNotIn('prompt_cache_key',spec.body);self.assertNotIn('prompt_cache_options',spec.body)

    def test_schema_and_synthetic_meaning_checks_fail_closed_without_repair(self):
        self.assertEqual(c.assess(json.dumps(answer()))['status'],'PASS')
        for kind in ('object','enum','inventory','meaning','literal','json'):
            value=answer()
            if kind=='object': value['claims'][0]['address_acts'][0]['adoption']=deepcopy(value['claims'][0]['adoption'])
            if kind=='enum': value['claims'][0]['address_acts'][0]['adoption']='own_assertion'
            if kind=='inventory': value['claims']=[]
            if kind=='meaning': value['claims'][0]['address_acts'][0]['adoption']='unresolved'
            if kind=='literal': value['claims'][0]['adoption']['evidence'][0]['text']='missing'
            with self.subTest(kind=kind):
                self.assertEqual(c.assess('broken' if kind=='json' else json.dumps(value))['status'],'FAIL(component)')

    def test_stubbed_single_call_and_cache_replay_accounting(self):
        value=packet();calls=[]
        def send(spec): calls.append(spec);return wire_response(spec,json.dumps(answer()))
        with TemporaryDirectory() as directory:
            result=c.run_recipe(value,Path(directory)/'execution',send)
            self.assertEqual(result['status'],'PASS');self.assertEqual(len(calls),1)
            self.assertEqual(result['accounting']['paid_attempts'],1)
            self.assertEqual(result['accounting']['cumulative_paid_attempts'],39)
            self.assertFalse(result['production_admission'])
            self.assertEqual(c.run_recipe(value,Path(directory)/'execution',send),result);self.assertEqual(len(calls),1)

    def test_length_and_network_halts_never_retry(self):
        for kind in ('length','network'):
            with self.subTest(kind=kind),TemporaryDirectory() as directory:
                calls=[]
                def send(spec):
                    calls.append(spec)
                    if kind=='network': raise OSError('synthetic timeout')
                    return wire_response(spec,'{"claims":\r\n'*5,finish='length')
                result=c.run_recipe(packet(),Path(directory)/'execution',send)
                self.assertEqual(len(calls),1);self.assertEqual(result['status'],'FAIL(component)')
                self.assertIsNotNone(result['halt']);self.assertIsNone(result['assessment'])

    def test_model_reasoning_limit_and_budget_guards(self):
        spec=c.request()
        with self.assertRaises(ValueError): c.hosted.OneRequestLedger('0.001',spec.version).check([],'source_reading')
        with self.assertRaises(ValueError): c.hosted.OneRequestLedger('0.004',spec.version).check([],'source_reading')
        body=deepcopy(spec.body);body['max_tokens']=65536
        with self.assertRaises(ValueError): replace(spec,body=body).preflight()
        with TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError,'reasoning'):
                c.requests.execute(spec,c.hosted.OneRequestLedger('0.003',spec.version),c.requests.ReceiptStore(Path(directory)),
                    lambda s:wire_response(s,json.dumps(answer()),reasoning=1))

    def test_cli_prepare_and_read_only_adapter(self):
        runner=CliRunner();value=packet();value['budget']=dict(maximum_attempts=1,max_usd='0.003')
        with patch.object(c,'prepare',return_value=(value,Path('/tmp/frozen'))):
            result=runner.invoke(app,['analysis','learning-demo','model-fit','deepinfra-enum-prepare','--from-input','/tmp/prior','--json'])
            self.assertEqual(result.exit_code,0,result.output);self.assertIn('deepinfra-enum-run',result.output)
        with patch.object(c,'run',return_value=dict(status='PREPARED_NO_EXECUTION')) as run:
            result=runner.invoke(app,['analysis','learning-demo','model-fit','deepinfra-enum-run','--input','/tmp/frozen/input.json','--check-only','--json'])
            self.assertEqual(result.exit_code,0,result.output);self.assertTrue(run.call_args.kwargs['check_only'])

    def test_frozen_identity_approval_and_dollar_guards_precede_inference(self):
        with TemporaryDirectory() as directory:
            root=Path(directory);value=packet()
            value['history']['prior_input']=str(root/'prior/input.json')
            value['budget']=dict(reserved_usd='0.0022528',max_usd='0.003')
            value['input_fingerprint']=c.digest({k:v for k,v in value.items() if k!='input_fingerprint'})
            path=c.directory(root,value['input_fingerprint'])/'input.json';path.parent.mkdir(parents=True)
            path.write_text(json.dumps(value))
            with patch.object(c,'prepare',return_value=(value,path.parent)),patch.object(c.hosted,'transport',side_effect=AssertionError('no inference')):
                self.assertEqual(c.run(path,root,check_only=True)['paid_calls'],0)
                self.assertFalse((path.parent/'execution').exists())
                with self.assertRaisesRegex(ValueError,'exact fingerprint'): c.run(path,root)
                for cap in ('0.001','0.004','NaN'):
                    with self.assertRaises(ValueError): c.run(path,root,max_usd=cap,check_only=True)
            with patch.object(c,'prepare',return_value=({**value,'schema':'changed'},path.parent)):
                with self.assertRaisesRegex(ValueError,'changed'): c.run(path,root,check_only=True)
