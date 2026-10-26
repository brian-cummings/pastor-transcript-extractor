from copy import deepcopy
from dataclasses import asdict,replace
from decimal import Decimal
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from typer.testing import CliRunner

from pastor_transcript_extractor import source_context_trial as t
from pastor_transcript_extractor import source_context as c
from pastor_transcript_extractor import evidence_requests as r
from pastor_transcript_extractor import binding_retry as b
from pastor_transcript_extractor.pastor_evidence import SourceWindow,digest
from pastor_transcript_extractor.cli import app
from test_learning_demo_five_windows import packet as five_packet
from test_learning_demo_correction import wire_response


def fixture():
    prior,output=five_packet()
    for case in prior['cases']:
        window=SourceWindow(**case['window']);state=t.demo._source_state(window)
        spec=r.RequestSpec(**case['request']);body=deepcopy(spec.body)
        body['messages'][1]['content']=r.wire(dict(texts=state['texts'],block_mapping=state['block_mapping'],
            source_identity={k:v for k,v in case['window'].items() if k!='blocks'},target_scope='declared_blocks_only'))
        case['request']=asdict(replace(spec,body=body))
        case['seeds']={'must_not_import':'historical answer'}
    prior['published_model_metadata']={'model':'synthetic'}
    prior=json.loads(json.dumps(prior))
    result=dict(accounting=dict(cumulative_attempts=60,cumulative_local_attempts=28,
        cumulative_paid_attempts=32,cumulative_known_list_price_usage_usd='0.274732242'))
    value=t.build(prior,result,c.contract_packet());value['input_fingerprint']=digest(value)
    output['abstentions']=[]
    return prior,result,value,output


class SourceContextTrialTests(unittest.TestCase):
    def test_schema_transport_is_lossless_except_exact_duplicate(self):
        _,_,value,_=fixture();body=deepcopy(value['cases'][0]['request']['body'])
        original=deepcopy(body)
        body['messages'][0]['content']+='\nOutput schema: '+r.wire(c.schema())
        self.assertEqual(c.without_duplicate_schema(body),original)
        self.assertEqual(c.without_duplicate_schema(original),original)
        self.assertEqual(body['response_format'],original['response_format'])
        self.assertTrue(body['messages'][0]['content'].endswith(r.wire(c.schema())))
        body['messages'][0]['content']+=' other instructions'
        self.assertEqual(c.without_duplicate_schema(body),body)
        body['response_format']['json_schema']['schema']={}
        with self.assertRaises(ValueError): c.without_duplicate_schema(body)

    def test_halted_paid_revision_is_reported_and_continuation_bills_only_remaining_calls(self):
        _,_,value,valid=fixture();old_case=deepcopy(value['cases'][0])
        old_case['request']['body']['messages'][0]['content']+='\nOutput schema: '+r.wire(c.schema())
        bad=deepcopy(valid);bad['claims'][0]['qualifications']=[dict(node_id='missing-q',
            applies_to=bad['claims'][0]['proposition']['node_id'],reading='Synthetic qualification')]
        sent=[]
        def flash(spec): sent.append(spec);return wire_response(spec,json.dumps(valid if len(sent)==1 else bad))
        def uncertain(spec):
            return dict(model='jev-1.13.0',complete=True,usage=dict(input_tokens=100,output_tokens=100),
                output={k:dict(type='noul',noul=.5) for k in spec.body['questions']})
        with TemporaryDirectory() as directory:
            old_root=Path(directory)/'old'
            with patch.object(b,'retry_request',side_effect=ValueError('synthetic fit stop')):
                stopped=b.run_case(value,old_case,old_root,flash,uncertain)
            self.assertEqual(stopped['halt'],'synthetic fit stop')
            self.assertIsNotNone(stopped['revision']);self.assertTrue(stopped['revision']['mechanical']['errors'])
            self.assertEqual(stopped['binding_stage_attempts']['review'],1)
            self.assertEqual(stopped['revision']['halt'],'synthetic fit stop')
            seed=dict(initial=t.five.load_seed(old_root/'initial',stopped['initial']),
                before=t.five.load_seed(old_root/'before'),review=t.five.load_seed(old_root/'revision/review'))
            for name in ('initial','review'): seed[name]['body_compatibility']=c.SCHEMA_TRANSPORT_VERSION
            seed['review']['raw_response_ref']='revision/review/receipts/'+r.RequestSpec(**seed['review']['receipt']['request']).fingerprint+'.json'
            new_case=deepcopy(value['cases'][0]);new_case['seeds']=seed
            old_hashes={str(p):t.demo.file_hash(p) for p in old_root.rglob('*.json')}
            calls=[];verifier=[]
            def resumed_flash(spec): calls.append(spec);return wire_response(spec,json.dumps(valid))
            def resumed_typesafe(spec):
                verifier.append(spec)
                return dict(model='jev-1.13.0',complete=True,usage=dict(input_tokens=100,output_tokens=100),
                    output={k:dict(type='noul',noul=.99) for k in spec.body['questions']})
            new_root=Path(directory)/'new'
            resumed=b.run_case(value,new_case,new_root,resumed_flash,resumed_typesafe)
            self.assertIsNone(resumed['halt']);self.assertEqual(len(calls),1);self.assertEqual(len(verifier),1)
            self.assertEqual(resumed['initial']['observations'],stopped['initial']['observations'])
            self.assertEqual(resumed['before']['findings'],stopped['before']['findings'])
            self.assertEqual(sorted(resumed['before']['feedback'],key=r.wire),sorted(stopped['before']['feedback'],key=r.wire))
            self.assertEqual(sum(len(r.ReceiptStore(new_root/stage).attempts()) for stage in ('initial','before','revision/review','revision/after')),2)
            self.assertEqual({str(p):t.demo.file_hash(p) for p in old_root.rglob('*.json')},old_hashes)
            self.assertNotIn('Output schema:',calls[0].body['messages'][0]['content'])

    def test_sources_geometry_order_model_preserved_without_old_outputs_or_seeds(self):
        prior,_,value,_=fixture()
        for old,new in zip(prior['cases'],value['cases'],strict=True):
            self.assertEqual(old['window'],new['window']);self.assertEqual(old['case_id'],new['case_id'])
            self.assertEqual(old['request']['body']['messages'][1],new['request']['body']['messages'][1])
            self.assertEqual(new['request']['body']['model'],t.hosted.FLASH_MODEL)
            self.assertEqual(new['request']['body']['reasoning_effort'],'none')
            self.assertEqual(new['request']['body']['max_tokens'],65536)
            self.assertNotIn('seeds',new)
            c.validate_request(r.RequestSpec(**new['request']))
        self.assertEqual(value['budget']['maximum_paid_attempts'],30)
        self.assertEqual(value['budget']['cumulative_maximum_paid_attempts'],62)
        self.assertEqual(Decimal(value['budget']['reserved_usd']),Decimal('1.010565120'))
        self.assertLess(Decimal(value['budget']['reserved_usd'])+Decimal(value['history']['prior_known_list_price_usage_usd']),2)

    def test_changed_source_or_cumulative_budget_excess_stops(self):
        for kind in ('source','attempts','dollars'):
            prior,result,_,_=fixture()
            if kind=='source': prior['cases'][0]['window']['blocks'][0]['target_text']='changed'
            if kind=='attempts': result['accounting']['cumulative_paid_attempts']=37
            if kind=='dollars': result['accounting']['cumulative_known_list_price_usage_usd']='1.1'
            with self.subTest(kind=kind),self.assertRaises(ValueError): t.build(prior,result,c.contract_packet())

    def test_all_five_bounded_loops_and_context_reporting_with_stubs(self):
        _,_,value,valid=fixture();calls=[];verifications=[]
        bad=deepcopy(valid);bad['claims'][0]['qualifications']=[dict(node_id='missing',
            applies_to=bad['claims'][0]['proposition']['node_id'],reading='Synthetic qualification')]
        def flash(spec):
            calls.append(spec);return wire_response(spec,json.dumps(bad if len(calls)%2 else valid))
        def typesafe(spec):
            verifications.append(spec)
            return dict(model='jev-1.13.0',complete=True,usage=dict(input_tokens=100,output_tokens=100),
                output={key:dict(type='noul',noul=.5 if key.endswith(':context_sufficiency') else .99) for key in spec.body['questions']})
        with TemporaryDirectory() as directory:
            root=Path(directory)/'execution';result=t.five.run_recipe(value,root,flash,typesafe)
            self.assertEqual(len(calls),20);self.assertEqual(len(verifications),10)
            self.assertEqual(result['accounting']['attempts'],30)
            self.assertEqual(result['accounting']['cumulative_paid_attempts'],62)
            self.assertEqual(result['accounting']['cumulative_attempts'],90)
            self.assertEqual(result['status'],'INCONCLUSIVE')
            self.assertTrue(all(x['context_eligibility']['final']['eligible_observation_ids']==[] for x in result['cases']))
            review=json.loads((root/'source-review-packet.json').read_text())
            self.assertTrue(all('context_eligibility' in case for case in review['cases']))
            self.assertEqual(t.five.run_recipe(value,root,lambda _:self.fail('no replay sends'),typesafe),result)

    def test_freeze_authorization_and_budget_checks_precede_execution(self):
        _,_,value,_=fixture()
        with TemporaryDirectory() as directory:
            root=Path(directory);value['history']['prior_input']=str(root/'prior/input.json')
            value['input_fingerprint']=digest({k:v for k,v in value.items() if k!='input_fingerprint'})
            path=t.directory(root,value['input_fingerprint'])/'input.json';path.parent.mkdir(parents=True)
            path.write_text(json.dumps(value))
            with patch.object(t,'prepare',return_value=(value,path.parent)),patch.object(t.hosted,'transport',side_effect=AssertionError('no inference')):
                checked=t.run(path,root,check_only=True)
                self.assertEqual(checked['paid_calls'],0)
                self.assertFalse((path.parent/'execution').exists())
                with self.assertRaisesRegex(ValueError,'exact fingerprint'): t.run(path,root)
                for cap in ('0.1','NaN','2'):
                    with self.assertRaisesRegex(ValueError,'Reserve'): t.run(path,root,max_usd=cap,check_only=True)
            with patch.object(t,'prepare',return_value=({**value,'schema_version':'changed'},path.parent)):
                with self.assertRaisesRegex(ValueError,'changed after freeze'): t.run(path,root,check_only=True)

    def test_cli_adapters_and_execute_command(self):
        _,_,value,_=fixture();runner=CliRunner()
        with patch.object(t,'prepare',return_value=(value,Path('/tmp/frozen'))):
            result=runner.invoke(app,['analysis','learning-demo','model-fit','source-context-prepare','--from-input','/tmp/prior','--json'])
            self.assertEqual(result.exit_code,0,result.output)
            out=json.loads(result.output);self.assertEqual(out['paid_calls'],0)
            self.assertIn('source-context-run',out['execute_command'])
            self.assertIn('--max-usd 1.02',out['execute_command'])
        with patch.object(t,'run',return_value=dict(status='PREPARED_NO_EXECUTION')) as run:
            result=runner.invoke(app,['analysis','learning-demo','model-fit','source-context-run','--input','/tmp/frozen/input.json','--check-only','--json'])
            self.assertEqual(result.exit_code,0,result.output);self.assertTrue(run.call_args.kwargs['check_only'])
