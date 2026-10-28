from copy import deepcopy
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import json
import unittest
from pastor_transcript_extractor import profile_analysis_support_execution as x
from test_profile_analysis_support import plan, answer


def packet(folder):
    p=plan();tasks=[]
    for i in p['items']:
        spec=x.make_request(i['case']);tasks.append(dict(claim_id=i['claim_id'],request=asdict(spec),token_account=spec.preflight()))
    result=dict(plan=p,tasks=tasks,budget=dict(max_usd='.55',reserved_usd=str(sum(x.requests.request_reservation(x.requests.RequestSpec(**t['request'])) for t in tasks)),maximum_paid_attempts=len(tasks),spend_root=str(Path(folder)/'requests')),profile_input=dict(path='/fixture/profile.json'))
    result['input_fingerprint']=x.digest(result)
    return result,Path(folder)/'run'


def wire(spec,output=None,*,thinking=''):
    return x.requests.WireResponse(200,json.dumps(dict(model=spec.body['model'],choices=[dict(finish_reason='stop',message=dict(content=json.dumps(answer()) if output is None else output,reasoning_content=thinking))],usage=dict(prompt_tokens=100,completion_tokens=100))))


class ProfileSupportExecutionTests(unittest.TestCase):
    def test_finite_tiers_no_context_truncation_and_instant_enforcement(self):
        c=plan()['items'][0]['case'];small=x.make_request(c)
        self.assertEqual(small.body['reasoning_effort'],'none')
        self.assertEqual(small.preflight()['output_cap'],2048)
        self.assertEqual(small.runtime_identity['input_cap'],16384)
        big=deepcopy(c);big['state']['extra']='x'*24000
        larger=x.make_request(big);self.assertGreater(larger.runtime_identity['input_cap'],small.runtime_identity['input_cap'])
        self.assertEqual(json.loads(larger.body['messages'][1]['content'])['extra'],big['state']['extra'])
        big['state']['extra']='x'*140000
        with self.assertRaisesRegex(ValueError,'no truncation'):x.make_request(big)
        with self.assertRaisesRegex(ValueError,'emitted reasoning'):x.requests.decode_response(small,wire(small,thinking='forbidden'))

    def test_complete_pipeline_document_handoff_cache_reuse_and_no_double_spend(self):
        with TemporaryDirectory() as folder:
            p,out=packet(folder);sent=[]
            def send(spec):sent.append(spec.fingerprint);return wire(spec)
            report=x.recipe(p,out,send)
            self.assertEqual(len(sent),2);self.assertEqual(report['execution_status'],'COMPLETE')
            self.assertEqual(report['coverage']['by_status'],dict(supported=2))
            self.assertEqual(report['accounting']['new_paid_attempts'],2)
            doc=json.loads((out/'document-input.json').read_text());self.assertEqual(doc['ready_claim_ids'],['local','summary'])
            self.assertEqual(x.recipe(p,out,lambda s:self.fail('no replay')),report)
            # A presentation-only run identity change reuses the same constituent requests.
            other=deepcopy(p);other['input_fingerprint']='new-document-run'
            replay=x.recipe(other,Path(folder)/'other-run',lambda s:self.fail('no request'))
            self.assertEqual(replay['accounting']['new_paid_attempts'],0)
            self.assertEqual(replay['accounting']['cache_reused_claims'],2)
            self.assertEqual(replay['accounting']['cumulative_conservative_charge_usd'],report['accounting']['cumulative_conservative_charge_usd'])
            self.assertIn('Statements available',(out/'analysis-support.md').read_text())

    def test_partial_process_recovery_reuses_previous_receipt_and_progress(self):
        with TemporaryDirectory() as folder:
            p,out=packet(folder);sent=[]
            def interrupted(spec):
                sent.append(spec)
                if len(sent)==2:raise KeyboardInterrupt()
                return wire(spec)
            with self.assertRaises(KeyboardInterrupt):x.recipe(p,out,interrupted)
            # Unreceipted second attempt is a hard stop, not a reason to resend it.
            with self.assertRaisesRegex(ValueError,'uncertain spend'):x.recipe(p,out,lambda s:self.fail('no retry'))
            second=sent[1];target=x._store(p,second)
            # Recover only the original response into its exact existing reservation.
            raw=wire(second);response=x.requests.decode_response(second,raw)
            target.write_immutable('wire-responses/'+second.fingerprint+'.json',asdict(raw))
            target.write_immutable('receipts/'+second.fingerprint+'.json',dict(request=asdict(second),token_account=second.preflight(),response=response,response_digest=x.digest(response),wire_response_digest=x.digest(asdict(raw)),halt=None))
            report=x.recipe(p,out,lambda s:self.fail('no duplicate call'))
            self.assertEqual(report['accounting']['cache_reused_claims'],2)
            self.assertEqual(report['execution_status'],'COMPLETE')

    def test_component_failure_retained_without_retry_and_dependencies_withheld(self):
        with TemporaryDirectory() as folder:
            p,out=packet(folder);sent=[]
            def send(spec):sent.append(spec);return wire(spec,output='{}') if len(sent)==1 else wire(spec)
            report=x.recipe(p,out,send)
            self.assertEqual(len(sent),2);self.assertEqual(report['status'],'FAIL(component)')
            self.assertEqual(report['coverage']['by_status'],dict(component_failure=1,dependency_unresolved=1))
            self.assertEqual(report['accounting']['new_paid_attempts'],2)

    def test_lost_response_halts_remaining_calls_and_preserves_reservation(self):
        with TemporaryDirectory() as folder:
            p,out=packet(folder);sent=[]
            def send(spec):sent.append(spec);raise OSError('connection lost')
            report=x.recipe(p,out,send)
            self.assertEqual(len(sent),1);self.assertEqual(report['execution_status'],'HALTED')
            self.assertEqual(report['coverage']['by_status'],dict(component_failure=1,not_run=1))
            self.assertEqual(Decimal(report['accounting']['new_conservative_charge_usd']),x.requests.request_reservation(sent[0]))

    def test_reserve_whole_batch_before_spending_and_tampered_cache_rejected(self):
        from contextlib import contextmanager
        @contextmanager
        def full(packet,root):yield [({},Decimal('.63'))]
        with TemporaryDirectory() as folder:
            p,out=packet(folder)
            with patch.object(x.supervised,'cumulative_history',full),self.assertRaisesRegex(ValueError,'full-profile reservations'):
                x.recipe(p,out,lambda s:self.fail('no sends'))
        with TemporaryDirectory() as folder:
            p,out=packet(folder);x.recipe(p,out,lambda spec:wire(spec))
            task=p['tasks'][0];spec=x.requests.RequestSpec(**task['request']);target=x._store(p,spec)
            path=target.root/'receipts'/f'{spec.fingerprint}.json';receipt=json.loads(path.read_text());receipt['response']['output']='tampered';path.write_text(json.dumps(receipt))
            with self.assertRaisesRegex(ValueError,'corrupt'):x.recipe(p,Path(folder)/'new',lambda s:self.fail('no send'))

    def test_all_unavailable_evidence_remains_visible_without_calls(self):
        with TemporaryDirectory() as folder:
            p,out=packet(folder);p['tasks']=[];p['budget']['reserved_usd']='0'
            for item in p['plan']['items']:item['gap']=dict(missing_information='Missing existing source');item['case']=None
            report=x.recipe(p,out,lambda s:self.fail('no model calls'))
            self.assertEqual(report['coverage']['by_status'],dict(unresolved=2))
            self.assertEqual(report['accounting']['new_paid_attempts'],0)
            self.assertEqual(report['status'],'INCONCLUSIVE')

    def test_exact_authorization_budget_and_cli(self):
        from typer.testing import CliRunner
        from pastor_transcript_extractor.cli import app
        with TemporaryDirectory() as folder:
            p,out=packet(folder);out.mkdir();path=out/'input.json';path.write_text(json.dumps(p))
            with patch.object(x,'prepare',return_value=(p,out)):
                self.assertEqual(x.run(path,Path(folder),check_only=True)['requests'],2)
                with self.assertRaises(ValueError):x.run(path,Path(folder))
                with self.assertRaises(ValueError):x.run(path,Path(folder),check_only=True,max_usd='.001')
                with self.assertRaises(ValueError):x.run(path,Path(folder),check_only=True,max_usd='bad')
        with patch.object(x,'run',return_value=dict(status='CHECKED_NO_EXECUTION')) as run:
            result=CliRunner().invoke(app,['analysis','profile-support','run','--input','/tmp/input.json','--check-only','--json'])
            self.assertEqual(result.exit_code,0,result.output);self.assertTrue(run.call_args.kwargs['check_only'])
