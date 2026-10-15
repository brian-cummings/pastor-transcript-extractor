import base64
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from typer.testing import CliRunner
from pastor_transcript_extractor.cli import app
from pastor_transcript_extractor import evidence_supply_boundary_validation as panel


class FakeProvider:
    instances=0
    calls=0
    failure=None

    def __init__(self):type(self).instances+=1

    def assess(self,request):
        type(self).calls+=1
        if self.failure=='lost':raise OSError('Synthetic lost reply')
        if self.failure=='utf8':return dict(status_code=200,body_base64=base64.b64encode(b'\xff').decode())
        answers={}
        for k,q in request['questions'].items():
            choice=next(iter(q['criteria']))
            answers[k]=dict(type='choice',choice=choice,probabilities={option:float(option==choice) for option in q['criteria']},confidence=1.0)
        value=dict(model=panel.frozen.MODEL,answers=answers,usage={'input_tokens':10,'output_tokens':3})
        return dict(status_code=200,body_base64=base64.b64encode(json.dumps(value).encode()).decode())

    def close(self):pass


class BoundaryPanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.packet=panel.build_packet()

    def setUp(self):
        FakeProvider.instances=FakeProvider.calls=0;FakeProvider.failure=None
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name)

    def run_fake(self,packet=None):
        p=packet or self.packet
        return panel.execute(p,p['content_fingerprint'],base_dir=self.base,provider_factory=FakeProvider,progress=lambda *args,**kwargs:None)

    def test_fixed_panel_does_not_invoke_discovery_or_G1(self):
        with patch.object(panel.design,'discover',side_effect=AssertionError('No ranker iteration')):
            p=panel.build_packet()
        self.assertEqual(len(p['cases']),21)
        self.assertEqual(len(p['requests']),33)
        self.assertEqual({r['capability'] for r in p['requests']},{'G2','G3'})
        self.assertEqual(p['budget']['maximum_list_price_usd'],'0.088704')

    def test_changed_state_is_rejected_before_client_creation(self):
        p=deepcopy(self.packet);p['requests'][0]['state']['target_text']='Changed evidence'
        p['content_fingerprint']=panel.frozen.fp({k:v for k,v in p.items() if k!='content_fingerprint'})
        with self.assertRaisesRegex(ValueError,'request identity'):
            self.run_fake(p)
        self.assertEqual(FakeProvider.instances,0)

    def test_wrong_approval_has_no_runtime_or_client_side_effects(self):
        with self.assertRaisesRegex(ValueError,'exact --approve-paid-packet'):
            panel.execute(self.packet,'wrong',base_dir=self.base,provider_factory=FakeProvider)
        self.assertEqual(list(self.base.iterdir()),[])
        self.assertEqual(FakeProvider.instances,0)

    def test_success_reuses_all_receipts_with_no_new_client(self):
        first=self.run_fake();self.assertEqual(FakeProvider.calls,33)
        second=self.run_fake();self.assertEqual(FakeProvider.calls,33)
        self.assertEqual(FakeProvider.instances,1)
        self.assertEqual(first,second)
        self.assertEqual(first['status'],'pending_Codex_source_audit_and_Brian_decision')
        self.assertIsNone(first['discovery_readiness'])
        self.assertTrue((panel.output_directory(self.base)/'results-v3.md').exists())

    def test_invalid_raw_bytes_retained_without_retry(self):
        FakeProvider.failure='utf8'
        with self.assertRaises(UnicodeDecodeError):self.run_fake()
        directory=panel.output_directory(self.base)
        receipts=list((directory/'receipts').glob('*.json'))
        self.assertEqual(len(receipts),1)
        self.assertEqual(json.loads(receipts[0].read_text())['response']['body_base64'],'/w==')
        with self.assertRaises(UnicodeDecodeError):self.run_fake()
        self.assertEqual(FakeProvider.calls,1)
        self.assertEqual(FakeProvider.instances,1)

    def test_lost_reply_keeps_charge_and_blocks_replacement(self):
        FakeProvider.failure='lost'
        with self.assertRaises(OSError):self.run_fake()
        ledger=json.loads((panel.output_directory(self.base)/'request-ledger.json').read_text())
        self.assertEqual(len(ledger['attempts']),1)
        self.assertEqual(ledger['attempts'][0]['reserved_input_tokens'],64000)
        with self.assertRaisesRegex(ValueError,'recovery decision'):self.run_fake()
        self.assertEqual(FakeProvider.calls,1)

    def test_crash_after_saved_valid_receipt_recovers_locally(self):
        self.run_fake();path=panel.output_directory(self.base)/'request-ledger.json'
        ledger=json.loads(path.read_text());ledger.pop('fingerprint');ledger['attempts'][-1]['status']='attempted'
        panel.frozen.dump(path,panel.seal(ledger))
        self.run_fake()
        self.assertEqual(FakeProvider.calls,33)
        self.assertEqual(json.loads(path.read_text())['attempts'][-1]['status'],'validated')

    def test_narration_error_remains_failure_even_when_quarantined(self):
        result=self.run_fake();row=next(r for r in result['observations'] if r['case_id']=='B3-R078')
        self.assertIn('narration_or_neighbor_promoted_to_addressed_act',row['automatic_critical_flags'])
        self.assertEqual(row['guarded_local_payload']['positive_facts'],{})
        self.assertEqual(row['decisions']['reassurance'],'observed')

    def test_confidence_cannot_promote_below_threshold_probability(self):
        result=self.run_fake();rows=result['raw_rows']
        rows[0]['raw_answers']['p0_explains_text']=dict(type='choice',choice='linked',confidence=.99,
                         probabilities={'linked':.79,'not_linked':.21,'incomplete':0.0,'unclear':0.0})
        interpreted=panel.interpret(self.packet,rows)
        self.assertEqual(interpreted['observations'][0]['decisions']['explains_text'],'unclear')

    def test_reservation_drift_blocks_replay_before_new_client(self):
        self.run_fake();path=panel.output_directory(self.base)/'request-ledger.json'
        ledger=json.loads(path.read_text());ledger.pop('fingerprint');ledger['attempts'][0]['reserved_usd']='0'
        panel.frozen.dump(path,panel.seal(ledger))
        with self.assertRaisesRegex(ValueError,'reservation/authorization drift'):self.run_fake()
        self.assertEqual(FakeProvider.instances,1)
        self.assertEqual(FakeProvider.calls,33)

    def test_repository_runtime_root_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'outside the repository'):
            panel.output_directory(panel.frozen.ROOT)

    def test_concurrent_execution_is_locked_without_stale_lock(self):
        directory=panel.output_directory(self.base)
        with panel.execution_lock(directory):
            with self.assertRaisesRegex(ValueError,'already running'):
                with panel.execution_lock(directory):pass
        with panel.execution_lock(directory):pass

    def test_cli_execute_needs_explicit_fingerprint(self):
        with patch.object(panel,'execute',side_effect=AssertionError('No execution')):
            r=CliRunner().invoke(app,['analysis','evidence-supply-boundary-validation','--execute'])
        self.assertNotEqual(r.exit_code,0)
        self.assertIn('--approve-paid-packet',r.output)


if __name__=='__main__':unittest.main()
