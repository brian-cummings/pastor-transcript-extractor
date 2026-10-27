from copy import deepcopy
from dataclasses import asdict
from decimal import Decimal
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from typer.testing import CliRunner
from pastor_transcript_extractor import qualified_observations as q
from pastor_transcript_extractor.cli import app
from test_role_observations import inputs
from test_evidence_constituents import field


def packet():
    data=inputs();context=data['context_packet'];context['candidate_index']=[dict(item_id='i0',case_id='generic',binding_id='c1')]
    parent=q.roles.integrate(data)[0];roles=parent['partial_binding']['evidence'];span=parent['partial_binding']['proposition']['span']
    binding=dict(proposition=dict(reading='The gate is open.',span=span),voice=dict(speaker='guide',evidence=roles['voice']['evidence']),adoption=dict(basis='discourse_use',evidence=roles['adoption']['evidence']),scope=dict(reading='The local gate',evidence=[span]),expression=dict(value='assertion',evidence=[span]),epistemic_status=dict(value='not_stated',evidence=[span]))
    original=dict(generic=dict(c1=binding));spec=q.missing_request(context,original)
    value=dict(input_fingerprint='synthetic',parents=[parent],reused_fields=dict(i0=dict(polarity=field('affirmed'),conditions=field([]),qualifications=field([],.6))),windows=context['windows'],items=context['state']['items'],candidate_index=context['candidate_index'],original_proposals=original,request=asdict(spec),history=dict(prior_accounting=dict(cumulative_attempts=102,cumulative_local_attempts=28,cumulative_paid_attempts=74,cumulative_known_list_price_usage_usd=str(q.BASELINE_SPEND))),budget=dict(prior_recorded_usd=str(q.BASELINE_SPEND),reserved_usd='.002752512'))
    return json.loads(json.dumps(value))


def response(spec,mode='pass'):
    answers={key:dict(type='noul',noul=.95 if mode=='pass' else .5) for key in spec.body['questions']}
    return dict(model='jev-1.13.0',complete=True,usage=dict(input_tokens=100,output_tokens=100),output=answers)


class QualifiedObservationTests(unittest.TestCase):
    def test_request_only_existing_proposed_values_no_feedback_or_expected_labels(self):
        value=packet();spec=q.requests.RequestSpec(**value['request'])
        self.assertEqual(len(spec.body['questions']),6)
        state=spec.body['state'];self.assertEqual(state['items'][0]['proposed']['speaker'],'guide')
        self.assertNotIn('polarity',state['items'][0]['proposed']);self.assertNotIn('conditions',state['items'][0]['proposed'])
        for name in ('probabilities','confidence','noul','rationale','expected','previous','reference'):
            self.assertNotIn('"'+name+'":',q.requests.wire(state))
        spec.preflight()

    def test_materialization_keeps_reuse_unknowns_and_exact_evidence(self):
        value=packet();before=deepcopy(value);spec=q.requests.RequestSpec(**value['request'])
        rows=q.materialize(value,response(spec),'/synthetic/new-receipt')
        self.assertEqual(value,before);row=rows[0]
        self.assertEqual(row['partial_binding']['semantic_values']['conditions'],[])
        self.assertIsNone(row['partial_binding']['semantic_values']['qualifications'])
        self.assertEqual(row['partial_binding']['semantic_values']['speaker'],'guide')
        self.assertEqual(row['partial_binding']['semantic_values']['polarity'],'affirmed')
        self.assertEqual(row['partial_binding']['evidence'],value['parents'][0]['partial_binding']['evidence'])
        self.assertFalse(any(x['resolved'] for x in row['field_judgments'].values()))
        self.assertFalse(q.evidence.EvidencePolicy().permits(row)[0])
        uncertain=q.materialize(value,response(spec,'uncertain'),'/synthetic/new-receipt')[0]
        self.assertIsNone(uncertain['partial_binding']['semantic_values']['speaker'])
        self.assertTrue(uncertain['partial_binding']['semantic_masks']['conditions'])
        fallback=q.materialize(value,None,'no-receipt')[0]
        self.assertNotIn('speaker',fallback['constituent_fields']);self.assertIsNone(fallback['partial_binding']['speaker'])
        bad=deepcopy(value);bad['parents'][0]['partial_binding']['proposition']['reading']='changed'
        with self.assertRaises(ValueError): q.materialize(bad,None,'no-receipt')

    def test_malformed_response_one_call_lost_response_and_durable_replay(self):
        for mode in ('pass','uncertain','malformed','timeout'):
            value=packet();sent=[]
            def transport(spec):
                sent.append(spec)
                if mode=='timeout': raise OSError('lost response')
                out=response(spec,'uncertain' if mode=='uncertain' else 'pass')
                if mode=='malformed': next(iter(out['output'].values()))['noul']=True
                return out
            with self.subTest(mode=mode),TemporaryDirectory() as folder:
                result=q.run_recipe(value,Path(folder),transport)
                self.assertEqual(len(sent),1);self.assertEqual(result,q.run_recipe(value,Path(folder),lambda s:self.fail('no retry')))
                self.assertEqual(result['status'],'FAIL(component)' if mode in ('malformed','timeout') else 'INCONCLUSIVE')
                self.assertEqual(result['eligible_complete_observations'],0);self.assertEqual(result['accounting']['cumulative_paid_attempts'],75)
                self.assertEqual(result['known_constituent_fields']['conditions'],1)
                if mode=='timeout':
                    self.assertEqual(result['accounting']['cumulative_budget_charge_usd'],str(q.BASELINE_SPEND+Decimal('.002752512')))
                    self.assertTrue(list((Path(folder)/'attempts').glob('*.json')))
                self.assertFalse(result['production_admission'])

    def test_strict_cumulative_budget_nan_and_unknown_usage_reservations(self):
        reserve=q.requests.reservation('source_verification')
        q.SliceBudget(str(q.BASELINE_SPEND)).check([], 'source_verification')
        for amount in ('NaN',str(Decimal(1)-reserve),'1',str(q.BASELINE_SPEND-Decimal('.01'))):
            with self.subTest(amount=amount),self.assertRaises(ValueError): q.SliceBudget(amount).check([], 'source_verification')
        with self.assertRaises(ValueError): q.SliceBudget(str(q.BASELINE_SPEND)).check([dict(phase='source_verification',reserved_usd=str(reserve))],'source_verification')

    def test_cross_input_unknown_charge_and_exact_cache_reuse(self):
        with TemporaryDirectory() as folder:
            base=Path(folder);value=packet();value['budget']['spend_root']=str(base)
            def lost(spec): raise OSError('lost response')
            first=q.run_recipe(value,base/'first'/'execution',lost)
            self.assertEqual(first['accounting']['unknown_usage_attempts'],1)
            second=q.run_recipe(value,base/'second'/'execution',lambda spec:response(spec))
            self.assertEqual(second['accounting']['cumulative_paid_attempts'],76)
            known=Decimal(second['accounting']['known_list_price_usage_usd'])
            self.assertEqual(Decimal(second['accounting']['cumulative_budget_charge_usd']),q.BASELINE_SPEND+Decimal('.002752512')+known)
            third=q.run_recipe(value,base/'third'/'execution',lambda spec:self.fail('exact receipt should be reused'))
            self.assertEqual(third['accounting']['paid_attempts'],0)
            self.assertEqual(third['accounting']['cumulative_paid_attempts'],76)
            self.assertEqual(third['accounting']['cumulative_budget_charge_usd'],second['accounting']['cumulative_budget_charge_usd'])
            self.assertTrue((base/'third/execution/cache-reuse.json').exists())
            receipt=next((base/'second/execution/receipts').glob('*.json'))
            damaged=json.loads(receipt.read_text());damaged['response_digest']='corrupted';receipt.write_text(json.dumps(damaged))
            blocked=q.run_recipe(value,base/'fourth'/'execution',lambda spec:self.fail('corrupt spend receipt must stop send'))
            self.assertEqual(blocked['status'],'FAIL(component)');self.assertEqual(blocked['accounting']['paid_attempts'],0)
            self.assertIsNone(blocked['accounting']['remaining_usd'])

    def test_frozen_cli_source_and_budget_guards(self):
        with patch.object(q,'run',return_value=dict(status='PREPARED_NO_EXECUTION')) as run:
            out=CliRunner().invoke(app,['analysis','learning-demo','model-fit','qualified-observations-run','--input','/tmp/input.json','--check-only','--json'])
            self.assertEqual(out.exit_code,0,out.output);self.assertTrue(run.call_args.kwargs['check_only'])
        with TemporaryDirectory() as folder:
            value=packet();value['input_fingerprint']=q.digest({k:v for k,v in value.items() if k!='input_fingerprint'})
            path=q.directory(Path(folder),value['input_fingerprint'])/'input.json';path.parent.mkdir(parents=True);path.write_text(json.dumps(value))
            with patch.object(q,'prepare',return_value=(value,path.parent)):
                self.assertEqual(q.run(path,Path(folder),check_only=True)['paid_calls'],0)
                self.assertFalse((path.parent/'execution').exists())
                with self.assertRaises(ValueError): q.run(path,Path(folder))
                for cap in ('.001','.004','NaN'):
                    with self.assertRaises(ValueError): q.run(path,Path(folder),max_usd=cap,check_only=True)
            changed=deepcopy(value);changed['version']='foreign'
            with patch.object(q,'prepare',return_value=(changed,path.parent)),self.assertRaises(ValueError): q.run(path,Path(folder),check_only=True)
