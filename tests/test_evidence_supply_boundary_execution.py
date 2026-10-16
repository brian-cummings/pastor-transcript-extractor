"""Focused bounded-executor tests with injected replies; no provider calls."""
import base64
from copy import deepcopy
from decimal import Decimal
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from typer.testing import CliRunner

from pastor_transcript_extractor import evidence_supply_boundary_execution as run
from pastor_transcript_extractor.cli import app

REAL_AUTHORIZATION = run.AUTHORIZATION


def make_test_authorization(base, path):
    """Explicit synthetic trust root for a temporary test execution directory."""
    value = json.loads(REAL_AUTHORIZATION.read_text())
    value['runtime_directory'] = str(run.panel.output_directory(base))
    value['content_fingerprint'] = run.panel.old.frozen.fp({k:v for k,v in value.items() if k!='content_fingerprint'})
    path.write_text(json.dumps(value))
    return value


class FakeProvider:
    calls = 0
    instances = 0
    mode = None
    on_assess = None

    def __init__(self):
        type(self).instances += 1

    def assess(self, request):
        type(self).calls += 1
        if type(self).on_assess:
            type(self).on_assess(request)
        if self.mode == 'lost':
            raise OSError('Injected lost reply')
        if self.mode == 'utf8':
            return dict(status_code=200, body_base64='/w==')
        if self.mode == 'http':
            return dict(status_code=429, body_base64=base64.b64encode(b'quota').decode())
        answers = {}
        for key, question in request['questions'].items():
            choice = next(iter(question['criteria']))
            answers[key] = dict(type='choice', choice=choice, confidence=1.,
                                probabilities={option: float(option == choice) for option in question['criteria']})
        raw = dict(model='wrong' if self.mode == 'model' else request['model'], answers=answers,
                   usage=dict(input_tokens=64001 if self.mode == 'tokens' else 10, output_tokens=3))
        return dict(status_code=200, body_base64=base64.b64encode(json.dumps(raw).encode()).decode())

    def close(self):
        pass


class ExecutionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.packet = json.loads(run.panel.INPUT.read_text())
        cls.fixture = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.fixture.cleanup)
        cls.fixture_base = Path(cls.fixture.name) / 'data'
        cls.fixture_base.mkdir()
        auth_path = Path(cls.fixture.name) / 'test-authorization.json'
        make_test_authorization(cls.fixture_base, auth_path)
        FakeProvider.calls = FakeProvider.instances = 0
        FakeProvider.mode = FakeProvider.on_assess = None
        cls.messages = []
        with patch.object(run.panel.old.frozen, 'live_check'), patch.object(run, 'AUTHORIZATION', auth_path):
            cls.result = run.execute(cls.packet, run.FROZEN_FINGERPRINT, base_dir=cls.fixture_base,
                                     provider_factory=FakeProvider, progress=lambda text, **kwargs: cls.messages.append(text))
        cls.fixture_calls = FakeProvider.calls

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name) / 'data'
        self.base.mkdir()
        auth_path = Path(self.temp.name) / 'test-authorization.json'
        self.decision = make_test_authorization(self.base, auth_path)
        authority_patch = patch.object(run, 'AUTHORIZATION', auth_path)
        authority_patch.start()
        self.addCleanup(authority_patch.stop)
        self.directory = run.panel.output_directory(self.base)
        FakeProvider.calls = FakeProvider.instances = 0
        FakeProvider.mode = FakeProvider.on_assess = None
        self.live = patch.object(run.panel.old.frozen, 'live_check')
        self.live.start()
        self.addCleanup(self.live.stop)

    def execute(self, packet=None, approval=run.FROZEN_FINGERPRINT, factory=FakeProvider):
        return run.execute(packet or self.packet, approval, base_dir=self.base, provider_factory=factory,
                           progress=lambda *args, **kwargs: None)

    def seed(self):
        shutil.copytree(run.panel.output_directory(self.fixture_base), self.directory)
        self.rewrite_ledger(lambda l:l.update(authorization_fingerprint=self.decision['content_fingerprint']))

    def rewrite_ledger(self, change):
        path = self.directory / 'request-ledger.json'
        ledger = json.loads(path.read_text()); ledger.pop('fingerprint')
        change(ledger)
        run.atomic_json(path, run.seal(ledger))

    def test_success_is_bounded_and_does_not_accept_oracle_or_gate(self):
        self.assertEqual(37, self.fixture_calls)
        self.assertEqual(dict(attempts=37, input_tokens=370, output_tokens=111), self.result['usage'])
        self.assertEqual(Decimal('0.00001554'), Decimal(self.result['actual_list_price_usd']))
        self.assertEqual([], self.result['local_evidence']['items'])
        self.assertIsNone(self.result['usable_evidence_items'])
        self.assertEqual('pending_full_source_audit', self.result['raw_semantic_verdict'])
        self.assertEqual(74, len(self.messages))
        self.assertIn('[1/37]', self.messages[0])
        self.assertIn('[37/37] validated', self.messages[-1])

    def test_replay_uses_receipts_without_client_or_new_charge(self):
        self.seed()
        result = self.execute(factory=lambda: self.fail('No client for cached replies'))
        self.assertEqual(self.result['observations'], result['observations'])
        self.assertEqual(self.result['usage'], result['usage'])
        self.assertEqual(0, FakeProvider.calls)
        self.assertEqual(37, len(json.loads((self.directory/'request-ledger.json').read_text())['attempts']))

    def test_reservation_is_durable_before_assess(self):
        seen=[]
        def inspect(request):
            ledger=json.loads((self.directory/'request-ledger.json').read_text())
            seen.append((request,ledger))
            raise OSError('Stop after observing reservation')
        FakeProvider.on_assess=inspect
        with self.assertRaisesRegex(ValueError,'Charged request failed'):self.execute()
        self.assertEqual(1,len(seen))
        request,ledger=seen[0];run.panel.old.frozen._verify_seal(ledger)
        last=ledger['attempts'][-1]
        self.assertEqual(request['request_key'],last['request_key'])
        self.assertEqual(64000,last['reserved_input_tokens'])
        self.assertEqual('attempted',last['status'])
        self.assertEqual(1,FakeProvider.calls)

    def test_lost_reply_stops_and_cannot_be_retried(self):
        FakeProvider.mode='lost'
        with self.assertRaisesRegex(ValueError,'recovery decision'):self.execute()
        ledger=json.loads((self.directory/'request-ledger.json').read_text())
        self.assertEqual(1,len(ledger['attempts']))
        self.assertEqual('failed',ledger['attempts'][0]['status'])
        self.assertEqual(Decimal('.002688'),Decimal(ledger['attempts'][0]['reserved_usd']))
        FakeProvider.mode=None
        with self.assertRaisesRegex(ValueError,'recovery decision'):self.execute()
        self.assertEqual(1,FakeProvider.calls)
        self.assertEqual(1,FakeProvider.instances)

    def test_invalid_replies_saved_before_parse_and_no_replacement(self):
        for mode in ('utf8','http','model','tokens'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as base:
                auth_path=Path(base)/'control.json'; data=Path(base)/'data';data.mkdir()
                make_test_authorization(data,auth_path)
                FakeProvider.mode=mode; calls=FakeProvider.calls
                with patch.object(run,'AUTHORIZATION',auth_path):
                    with self.assertRaisesRegex(ValueError,'Charged request failed'):
                        run.execute(self.packet,run.FROZEN_FINGERPRINT,base_dir=data,provider_factory=FakeProvider,progress=lambda *a,**k:None)
                    directory=run.panel.output_directory(data); values=list((directory/'receipts').glob('*.json'))
                    self.assertEqual(1,len(values))
                    saved=json.loads(values[0].read_text());self.assertIn('body_base64',saved['response'])
                    with self.assertRaisesRegex(ValueError,'recovery decision'):
                        run.execute(self.packet,run.FROZEN_FINGERPRINT,base_dir=data,provider_factory=FakeProvider,progress=lambda *a,**k:None)
                self.assertEqual(calls+1,FakeProvider.calls)

    def test_crash_after_valid_receipt_recovers_without_call(self):
        self.seed()
        self.rewrite_ledger(lambda l:l['attempts'][-1].update(status='attempted',usage=None,receipt_fingerprint=None))
        result=self.execute(factory=lambda:self.fail('Local receipt recovery only'))
        self.assertEqual(37,result['usage']['attempts'])
        self.assertEqual('validated',json.loads((self.directory/'request-ledger.json').read_text())['attempts'][-1]['status'])

    def test_missing_or_corrupt_or_orphan_receipt_blocks_client(self):
        self.seed();path=next((self.directory/'receipts').glob('*.json'));original=path.read_text()
        path.unlink()
        with self.assertRaisesRegex(ValueError,'recovery decision'):self.execute()
        path.write_text(original+'broken')
        with self.assertRaises(ValueError):self.execute()
        path.write_text(original)
        (self.directory/'results-v4.json').unlink()
        (self.directory/'results-v4.md').unlink()
        self.rewrite_ledger(lambda l:l.update(attempts=[]))
        with self.assertRaisesRegex(ValueError,'Orphan'):self.execute()
        self.assertEqual(0,FakeProvider.instances)

    def test_duplicate_or_overbudget_or_reservation_drift_blocks_client(self):
        self.seed();original=(self.directory/'request-ledger.json').read_text()
        for change in (lambda l:l['attempts'].append(deepcopy(l['attempts'][0])),
                       lambda l:l['attempts'][0].update(reserved_usd='1'),
                       lambda l:l['attempts'][0].update(reserved_input_tokens=64001)):
            with self.subTest(change=change):
                (self.directory/'request-ledger.json').write_text(original);self.rewrite_ledger(change)
                with self.assertRaises(ValueError):self.execute()
        self.assertEqual(0,FakeProvider.instances)

    def test_ledger_accounting_must_match_saved_receipt(self):
        self.seed();self.rewrite_ledger(lambda l:l['attempts'][0]['usage'].update(input_tokens=9))
        with self.assertRaisesRegex(ValueError,'accounting differs'):self.execute()
        self.assertEqual(0,FakeProvider.instances)

    def test_foreign_V3_receipt_and_symlink_cannot_replay(self):
        self.seed();foreign=self.directory/'receipts'/'v3-old.json';foreign.write_text('{}')
        with self.assertRaisesRegex(ValueError,'Foreign'):self.execute()
        foreign.unlink()
        receipt=next((self.directory/'receipts').glob('*.json'));receipt.unlink();receipt.symlink_to(self.base/'elsewhere')
        with self.assertRaisesRegex(ValueError,'escapes'):self.execute()
        self.assertEqual(0,FakeProvider.instances)

    def test_wrong_fingerprint_state_or_authorization_cannot_create_client(self):
        with self.assertRaisesRegex(ValueError,'exact --approve'):self.execute(approval='wrong')
        packet=deepcopy(self.packet);packet['requests'][0]['state']['target_text']='mutated'
        packet['content_fingerprint']=run.panel.old.frozen.fp({k:v for k,v in packet.items() if k!='content_fingerprint'})
        with self.assertRaises(ValueError):self.execute(packet=packet)
        path=self.base/'unauthorized.json';decision=json.loads(run.AUTHORIZATION.read_text());decision['source_oracle_accepted']=True
        decision['content_fingerprint']=run.panel.old.frozen.fp({k:v for k,v in decision.items() if k!='content_fingerprint'});path.write_text(json.dumps(decision))
        with patch.object(run,'AUTHORIZATION',path):
            with self.assertRaisesRegex(ValueError,'authorization'):self.execute()
        self.assertEqual(0,FakeProvider.instances)
        self.assertFalse(self.directory.exists())

    def test_lock_excludes_second_execution_and_releases(self):
        with run.execution_lock(self.directory):
            with self.assertRaisesRegex(ValueError,'already running'):self.execute()
        with run.execution_lock(self.directory):pass
        self.assertEqual(0,FakeProvider.instances)

    def test_readonly_preflight_makes_no_runtime_files(self):
        with patch.object(run.panel.old.frozen,'HTTPProvider',side_effect=AssertionError('No API')):
            _,ledger,reused=run.preflight(self.packet,self.base)
        self.assertEqual([],ledger['attempts']);self.assertEqual({},reused)
        self.assertEqual([],list(self.base.iterdir()))

    def test_closed_gate_blocks_execution(self):
        self.directory.mkdir(parents=True);(self.directory/'acceptance-decision.json').write_text('{}')
        with self.assertRaisesRegex(ValueError,'already closed'):self.execute()
        self.assertEqual(0,FakeProvider.instances)

    def test_different_runtime_root_cannot_reset_authorized_budget(self):
        other=self.base/'different-root'
        with self.assertRaisesRegex(ValueError,'authorization'):
            run.execute(self.packet,run.FROZEN_FINGERPRINT,base_dir=other,provider_factory=FakeProvider)
        self.assertFalse(other.exists())
        self.assertEqual(0,FakeProvider.instances)

    def test_completed_results_with_missing_ledger_require_recovery(self):
        self.seed();(self.directory/'request-ledger.json').unlink()
        shutil.rmtree(self.directory/'receipts')
        with self.assertRaisesRegex(ValueError,'recovery decision'):self.execute()
        self.assertEqual(0,FakeProvider.instances)

    def test_cli_requires_exact_key_and_passes_it_to_runner(self):
        for args in (['--execute'],['--execute','--approve-paid-packet','wrong'],['--approve-paid-packet',run.FROZEN_FINGERPRINT]):
            with patch.object(run,'execute',side_effect=AssertionError('No execution')):
                result=CliRunner().invoke(app,['analysis','evidence-supply-boundary-revalidation',*args])
                self.assertNotEqual(0,result.exit_code)
        with patch.object(run,'execute',return_value=self.result) as execute:
            result=CliRunner().invoke(app,['analysis','evidence-supply-boundary-revalidation','--execute','--approve-paid-packet',run.FROZEN_FINGERPRINT,'--base-dir',str(self.base)])
        self.assertEqual(0,result.exit_code,result.output)
        execute.assert_called_once_with(self.packet,run.FROZEN_FINGERPRINT,base_dir=self.base)
        self.assertIn('source audit',' '.join(result.output.split()))
