from copy import deepcopy
from dataclasses import asdict,replace
from decimal import Decimal
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from typer.testing import CliRunner

from pastor_transcript_extractor import attachment_trial as t
from pastor_transcript_extractor.cli import app
from test_source_context_trial import fixture
from test_learning_demo_correction import wire_response


def source():
    _,_,base,valid=fixture();case=base['cases'][0];windows=[];producers=[]
    for slot_index,slot in enumerate(t.fit.SLOTS):
        for profile,videos in t.demo.SCOPE.items():
            window=deepcopy(case['window']);window.update(id=f'P{profile}-R{videos[slot_index]}-{slot}',
                profile_id=profile,video_id=videos[slot_index],stratum='independent_control' if slot_index==2 else 'detector_selected')
            state=t.demo._source_state(t.SourceWindow(**window));old=t.requests.RequestSpec(**case['request'])
            body=deepcopy(old.body);body['messages'][1]['content']=t.requests.wire(dict(texts=state['texts'],
                block_mapping=state['block_mapping'],source_identity={k:v for k,v in window.items() if k!='blocks'},target_scope='declared_blocks_only'))
            windows.append(window);producers.append(dict(case_id=window['id'],request=asdict(replace(old,body=body,source_identity=dict(window=window['id'])))))
    return dict(windows=windows,source_requests=producers,selection=dict(cases=[w['id'] for w in windows])),valid


def packet():
    value,valid=source();account=dict(cumulative_attempts=75,cumulative_local_attempts=28,cumulative_paid_attempts=47,
        cumulative_known_list_price_usage_usd='0.332992212')
    value=t.build(value,account,t.context.contract_packet());value['input_fingerprint']=t.digest(value)
    return value,valid


class AttachmentTrialTests(unittest.TestCase):
    def test_selection_source_geometry_model_and_budget_are_frozen(self):
        original,valid=source();value,_=packet()
        self.assertEqual(value['selection']['cases'],['P130-R1037-theology','P318-R281-application','P318-R4589-independent_control'])
        self.assertEqual(value['budget']['maximum_paid_attempts'],18)
        self.assertEqual(value['budget']['cumulative_maximum_paid_attempts'],65)
        self.assertEqual(Decimal(value['budget']['reserved_usd']),Decimal('.193462272'))
        self.assertEqual(value['selection']['profile_counts'],{'130':1,'318':2})
        for case in value['cases']:
            old=next(r for r in original['source_requests'] if r['case_id']==case['case_id'])
            spec=t.requests.RequestSpec(**case['request'])
            self.assertEqual(spec.body['messages'][1],old['request']['body']['messages'][1])
            self.assertEqual(spec.body['model'],'deepseek-ai/DeepSeek-V4.1-Flash-1017')
            self.assertEqual(spec.body['max_tokens'],8192);self.assertEqual(spec.body['reasoning_effort'],'none')
            self.assertIn(t.context.ATTACHMENT_RULE,spec.body['messages'][0]['content'])
            spec.preflight()
        for paid,cost in ((49,'0.3'),(47,'1.9')):
            with self.assertRaises(ValueError): t.build(original,dict(cumulative_paid_attempts=paid,
                cumulative_known_list_price_usage_usd=cost),t.context.contract_packet())

    def test_worst_case_binding_and_semantic_loop_is_eighteen_calls(self):
        value,valid=packet();bad=deepcopy(valid);bad['claims'][0]['qualifications']=[dict(node_id='missing',
            applies_to=bad['claims'][0]['proposition']['node_id'],reading='Synthetic qualification')]
        flashes=[];verifiers=[]
        def flash(spec):
            flashes.append(spec);return wire_response(spec,json.dumps(bad if len(flashes)%2 else valid))
        def verifier(spec):
            verifiers.append(spec)
            return dict(model='jev-1.13.0',complete=True,usage=dict(input_tokens=100,output_tokens=100),
                output={k:dict(type='noul',noul=.5 if len(verifiers)%2 else .99) for k in spec.body['questions']})
        with TemporaryDirectory() as directory:
            root=Path(directory);result=t.five.run_recipe(value,root,flash,verifier)
            self.assertEqual(len(flashes),12);self.assertEqual(len(verifiers),6)
            self.assertEqual(result['accounting']['paid_attempts'],18)
            self.assertEqual(result['accounting']['cumulative_paid_attempts'],65)
            self.assertEqual(Decimal(result['accounting']['reserved_usd']),Decimal('.193462272'))
            self.assertEqual(result['processed_windows'],3);self.assertFalse(result['production_admission'])
            self.assertTrue(all(sum(k.endswith(':conditions') for k in s.body['questions'])==2 for s in verifiers))
            self.assertIn('mechanical_details',flashes[1].body['messages'][-1]['content'])
            self.assertEqual(t.five.run_recipe(value,root,lambda s:self.fail('no replay'),verifier),result)

    def test_transport_halt_stops_batch_and_component_failure_continues(self):
        for transport in (False,True):
            value,valid=packet();bad=deepcopy(valid);bad['claims'][0]['proposition']['span']['text']='absent'
            calls=[]
            def flash(spec):
                calls.append(spec)
                if transport: raise OSError('synthetic timeout')
                return wire_response(spec,json.dumps(bad if len(calls)<=2 else valid))
            def verifier(spec):
                return dict(model='jev-1.13.0',complete=True,usage=dict(input_tokens=100,output_tokens=100),
                    output={k:dict(type='noul',noul=.99) for k in spec.body['questions']})
            with self.subTest(transport=transport),TemporaryDirectory() as directory:
                result=t.five.run_recipe(value,Path(directory),flash,verifier)
                self.assertEqual(result['status'],'FAIL(component)')
                self.assertEqual(result['processed_windows'],1 if transport else 3)
                self.assertEqual(result['accounting']['unknown_usage_attempts'],1 if transport else 0)

    def test_guided_retry_is_explicit_and_reserves_both_attempts(self):
        value,_=packet();spec=t.requests.RequestSpec(**value['cases'][0]['request'])
        with self.assertRaises(ValueError):
            t.binding_retry.read(spec,t.SourceWindow(**value['cases'][0]['window']),value['schema'],
                t.requests.ReceiptStore(Path('/tmp/unused-guided-test')),lambda s:self.fail('no send'))
        ledger=t.hosted.GuidedBindingLedger();ledger.check([],'source_reading')
        with self.assertRaises(ValueError): t.hosted.GuidedBindingLedger('0.02').check([],'source_reading')
        with self.assertRaises(ValueError): ledger.check([{},{}],'source_reading')
        with self.assertRaises(ValueError): ledger.check([dict(namespace='foreign',provider='DeepInfra',reserved_usd='0')],'source_reading')

    def test_cli_and_read_only_freeze_guards(self):
        value,_=packet();runner=CliRunner()
        with patch.object(t,'run',return_value=dict(status='PREPARED_NO_EXECUTION',model=t.hosted.FLASH_MODEL)) as run:
            result=runner.invoke(app,['analysis','learning-demo','model-fit','attachment-run','--input','/tmp/input.json','--check-only','--json'])
            self.assertEqual(result.exit_code,0,result.output);self.assertTrue(run.call_args.kwargs['check_only'])
        with TemporaryDirectory() as directory:
            base=Path(directory);path=t.directory(base,value['input_fingerprint'])/'input.json'
            path.parent.mkdir(parents=True);path.write_text(json.dumps(value))
            with patch.object(t,'prepare',return_value=(value,path.parent)):
                self.assertEqual(t.run(path,base,check_only=True)['paid_calls'],0)
                with self.assertRaises(ValueError): t.run(path,base)
                for ceiling in ('0.02','0.21','NaN'):
                    with self.assertRaises(ValueError): t.run(path,base,max_usd=ceiling,check_only=True)
