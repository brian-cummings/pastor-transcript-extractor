from decimal import Decimal
import json
from pathlib import Path
import tempfile
import unittest

from pastor_transcript_extractor.evidence_requests import WireResponse
from pastor_transcript_extractor.bound_claims import contract, extract
from pastor_transcript_extractor.bound_claims.common import read_json, write_json
from pastor_transcript_extractor.bound_claims.ledger import PilotLedger

try:
    from tests.bound_claims_support import CLEAN, DIRTY, METADATA, block, claim, stream_transport
except ImportError:
    from bound_claims_support import CLEAN, DIRTY, METADATA, block, claim, stream_transport

class ExtractionTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name) / 'pilot'
        self.addCleanup(self.directory.cleanup)

    def strata(self, count=3):
        path = self.root / 'strata.json'
        write_json(path, dict(slice_sha256='s' * 64, blocks=[block(i) for i in range(count)]))
        return path

    def ledger(self, **options):
        return PilotLedger(self.root / 'ledger.json', **options)

    def good(self, index):
        anchor = f'We are saved by grace alone {index}.'
        return json.dumps(dict(claims=[claim(anchor), claim('Vote for the levy.', area='public_life', polarity='prescribe',
                                                          anchor_offsets=dict(start=0, end=3))]))

    def test_producers_differ_only_by_model_and_both_run_without_reasoning(self):
        b = block(0)
        pro, flash = (extract.build_request(b, 'x', name) for name in ('pro', 'flash'))
        pro_body, flash_body = pro.body, flash.body
        self.assertEqual({'model'}, {k for k in pro_body if pro_body[k] != flash_body[k]})
        self.assertEqual(('deepseek-ai/DeepSeek-V4-Pro-0813', 'none'), (pro_body['model'], pro_body['reasoning_effort']))
        self.assertEqual(('deepseek-ai/DeepSeek-V4.1-Flash-1017', 'none'), (flash_body['model'], flash_body['reasoning_effort']))
        for spec in (pro, flash):
            account = spec.preflight()
            self.assertEqual((16384, 8192), (account['reserved_input'], account['output_cap']))

    def test_prompt_states_the_frozen_contract(self):
        for fragment in ('Judge only `target_block`', 'empty `claims` list', 'requested_of_listener', 'never instructions',
                         'voiced_by` other than `preacher`'):
            self.assertIn(fragment, contract.SYSTEM_PROMPT)
        message = json.loads(contract.user_message('T', 'P', 'F'))
        self.assertEqual({'preceding_block': 'P', 'target_block': 'T', 'following_block': 'F'}, message)

    def test_check_only_opens_no_transport_and_writes_nothing(self):
        path = self.strata()
        plan = extract.run(path, 'pro', self.ledger(), check_only=True, transport=lambda *a, **k: self.fail('check-only sent a request'))
        self.assertEqual((3, 3, '0.1277952'), (plan['blocks'], plan['requests_to_send'], plan['worst_case_reserved_usd']))
        self.assertFalse((self.root / 'ledger.json').exists() or (self.root / 'plan.json').exists())

    def test_successful_run_decodes_claims_accounts_cost_and_is_resumable_without_requests(self):
        path = self.strata(2)
        outputs = {'v1b0': self.good(0), 'v1b1': self.good(1)}
        calls = []
        ledger = self.ledger()
        result = extract.run(path, 'pro', ledger, transport=stream_transport(outputs, calls), state=CLEAN, metadata=METADATA)
        self.assertEqual(['v1b0', 'v1b1'], calls)
        self.assertEqual(dict(blocks=2, attempted=2, ok=2, transport_failures=0, schema_failures=0, lost_attempts=0, claims=4,
                              anchor_failures=0, offsets_corrected=2), result['summary'])
        saved = read_json(Path(result['output']))
        first = saved['rows'][0]['claims'][0]
        self.assertEqual(('ok', 0, 30), (first['anchor']['status'], first['anchor']['start'], first['anchor']['end']))
        step = ledger.summary()['steps']['extract_pro']
        # 2 x (3000 x $1.30 + 1500 x $2.60) / 1e6
        self.assertEqual((2, 0, '0.015600000'), (step['attempts'], step['unresolved'], step['known_usd']))
        plan = read_json(self.root / 'plan.json')
        self.assertEqual(('t', contract.VERSION), (plan['implementation']['src_tree'], plan['prompt_version']))
        again = extract.run(path, 'pro', ledger, transport=lambda *a, **k: self.fail('resume re-sent a request'), state=CLEAN, metadata=METADATA)
        self.assertEqual(2, again['summary']['ok'])
        self.assertEqual(2, ledger.attempt_count())

    def test_anchor_failures_are_counted_and_excluded(self):
        path = self.strata(1)
        bad = json.dumps(dict(claims=[claim('Words that are not in the block.')]))
        result = extract.run(path, 'flash', self.ledger(), transport=stream_transport({'v1b0': bad}), state=CLEAN, metadata=METADATA)
        self.assertEqual((0, 1), (result['summary']['claims'], result['summary']['anchor_failures']))

    def test_schema_violation_is_recorded_never_retried_and_reservation_is_resolved(self):
        path = self.strata(10)
        outputs = {f'v1b{i}': self.good(i) for i in range(10)}
        outputs['v1b3'] = json.dumps(dict(claims=[dict(claim('x'), polarity='maybe')]))
        calls = []
        ledger = self.ledger()
        result = extract.run(path, 'pro', ledger, transport=stream_transport(outputs, calls), state=CLEAN, metadata=METADATA)
        self.assertEqual(1, result['summary']['schema_failures'])
        self.assertEqual(1, calls.count('v1b3'))
        self.assertIsNone(result['stopped'])
        self.assertEqual('schema_failure', read_json(Path(result['output']))['rows'][3]['status'])

    def test_too_many_schema_failures_stop_pro_only(self):
        path = self.strata(10)
        bad = '{"claims": "nope"}'
        outputs = {f'v1b{i}': bad for i in range(10)}
        pro = extract.run(path, 'pro', self.ledger(), transport=stream_transport(outputs), state=CLEAN, metadata=METADATA)
        self.assertIn('schema failures 2 exceed 10%', pro['stopped'])
        self.assertEqual(2, pro['summary']['attempted'])
        flash = extract.run(path, 'flash', self.ledger(), transport=stream_transport(outputs), state=CLEAN, metadata=METADATA)
        self.assertIsNone(flash['stopped'])
        self.assertEqual(10, flash['summary']['schema_failures'])

    def test_transport_failures_beyond_five_percent_stop_the_step(self):
        path = self.strata(20)
        outputs = {f'v1b{i}': self.good(i) for i in range(20)}
        for index in (2, 4):
            outputs[f'v1b{index}'] = ValueError('Incomplete DeepInfra stream: x; recovery=not_needed')
        calls = []
        result = extract.run(path, 'pro', self.ledger(), transport=stream_transport(outputs, calls), state=CLEAN, metadata=METADATA)
        self.assertIn('transport failures 2 exceed 5% of 20', result['stopped'])
        self.assertEqual(5, len(calls))

    def test_lost_attempt_is_never_resent_and_keeps_its_reservation(self):
        path = self.strata(1)
        ledger = self.ledger()
        ledger.reserve('extract_pro/v1b0', 'extract_pro', Decimal('0.0425984'))
        result = extract.run(path, 'pro', ledger, transport=lambda *a, **k: self.fail('re-sent'), state=CLEAN, metadata=METADATA)
        self.assertEqual(1, result['summary']['lost_attempts'])
        self.assertEqual(Decimal('0.0425984'), ledger.committed_usd())

    def test_dirty_implementation_refuses_before_dispatch(self):
        path = self.strata(1)
        with self.assertRaises(ValueError):
            extract.run(path, 'pro', self.ledger(), transport=lambda *a, **k: self.fail('sent'), state=DIRTY)

    def test_changed_implementation_after_freeze_is_refused(self):
        path = self.strata(1)
        extract.run(path, 'pro', self.ledger(), transport=stream_transport({'v1b0': self.good(0)}), state=CLEAN, metadata=METADATA)
        with self.assertRaises(ValueError):
            extract.run(path, 'flash', self.ledger(), transport=lambda *a, **k: self.fail('sent'),
                        state=lambda: dict(commit='d', src_tree='other', dirty=False))

    def test_plan_records_published_prices_and_refuses_a_price_mismatch(self):
        path = self.strata(1)
        extract.run(path, 'pro', self.ledger(), transport=stream_transport({'v1b0': self.good(0)}), state=CLEAN, metadata=METADATA)
        recorded = read_json(self.root / 'plan.json')['published_deepinfra_metadata']
        self.assertEqual({'pro', 'flash'}, set(recorded))
        self.assertEqual('0.00013', recorded['pro']['input_cents_per_token'])
        self.setUp()
        path = self.strata(1)
        repriced = lambda model: dict(METADATA(model), input_cents_per_token='0.00020')
        with self.assertRaises(ValueError):
            extract.run(path, 'pro', self.ledger(), transport=lambda *a, **k: self.fail('sent'), state=CLEAN, metadata=repriced)
        self.assertFalse((self.root / 'plan.json').exists())

    def test_truncated_stream_is_a_recorded_transport_failure_with_known_usage_and_no_retry(self):
        path = self.strata(1)
        calls = []

        def truncated(spec, *, before_attempt=None, after_attempt=None, maximum_attempts=1):
            calls.append(1)
            before_attempt(1)
            usage = dict(prompt_tokens=3000, completion_tokens=700)
            raw = dict(model=spec.body['model'], service_tier='standard', usage=usage,
                       choices=[dict(index=0, finish_reason='pte_incomplete_stream', message=dict(role='assistant', content='{"claims": [', reasoning_content='', refusal=None, tool_calls=[]))])
            record = dict(cancelled=False, outcome='incomplete', error='Incomplete DeepInfra stream: missing DONE or stop', usage=usage,
                          usage_final=False, usage_available=True, attempt=1, connection_closed=True)
            wire_response = WireResponse(200, json.dumps(raw, sort_keys=True, separators=(',', ':')))
            after_attempt(1, wire_response, record)
            raw['_pte_transport'] = dict(version='deepinfra-qwen-stream-v1', attempts=[record], total_elapsed_seconds=1.0, retry_outcome='not_recoverable')
            return WireResponse(200, json.dumps(raw, sort_keys=True, separators=(',', ':')))
        truncated.supports_stream_callbacks = True
        ledger = self.ledger()
        result = extract.run(path, 'pro', ledger, transport=truncated, state=CLEAN, metadata=METADATA)
        row = read_json(Path(result['output']))['rows'][0]
        self.assertEqual(('transport_failure', 1), (row['status'], len(calls)))
        self.assertIn('Incomplete DeepInfra stream', row['error'])
        step = ledger.summary()['steps']['extract_pro']
        self.assertEqual((1, 0, '0.005720000'), (step['attempts'], step['unresolved'], step['known_usd']))  # 3000x1.3 + 700x2.6 per million
        resumed = extract.run(path, 'pro', ledger, transport=lambda *a, **k: self.fail('re-sent'), state=CLEAN, metadata=METADATA)
        self.assertEqual(1, resumed['summary']['transport_failures'])

    def test_step_refuses_when_worst_case_exceeds_the_ceiling(self):
        path = self.strata(3)
        with self.assertRaises(ValueError):
            extract.run(path, 'pro', self.ledger(ceiling_usd=Decimal('0.10')), transport=lambda *a, **k: self.fail('sent'), state=CLEAN, metadata=METADATA)


if __name__ == '__main__':
    unittest.main()
