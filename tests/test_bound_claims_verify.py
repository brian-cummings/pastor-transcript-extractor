import json
from pathlib import Path
import tempfile
import unittest

from pastor_transcript_extractor.evidence_requests import WireResponse
from pastor_transcript_extractor.bound_claims import contract, extract, verify
from pastor_transcript_extractor.bound_claims.common import read_json, write_json
from pastor_transcript_extractor.bound_claims.ledger import PilotLedger

try:
    from tests.bound_claims_support import CLEAN, DIRTY, METADATA, block, claim, stream_transport
except ImportError:
    from bound_claims_support import CLEAN, DIRTY, METADATA, block, claim, stream_transport


def jev(probability=0.9, tokens=2000, fail=None):
    def send(spec):
        send.calls.append(spec.source_identity['fingerprint'])
        if fail and spec.source_identity['coordinate'] in fail:
            return WireResponse(500, '{}')
        answers = {key: dict(type='noul', noul=probability) for key in spec.body['questions']}
        return WireResponse(200, json.dumps(dict(model='jev-1.13.0', usage=dict(input_tokens=tokens, output_tokens=0), answers=answers)))
    send.calls = []
    return send


class VerificationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name) / 'pilot'
        self.addCleanup(self.directory.cleanup)
        self.ledger = PilotLedger(self.root / 'ledger.json')

    def produce(self, outputs, producers=('pro', 'flash')):
        path = self.root / 'strata.json'
        write_json(path, dict(slice_sha256='s' * 64, blocks=[block(i) for i in range(len(outputs))]))
        paths = []
        for producer in producers:
            result = extract.run(path, producer, self.ledger, transport=stream_transport({f'v1b{i}': o for i, o in enumerate(outputs)}), state=CLEAN, metadata=METADATA)
            paths.append(Path(result['output']))
        return paths

    def anchor_output(self, index, **changes):
        return json.dumps(dict(claims=[claim(f'We are saved by grace alone {index}.', **changes)]))

    def test_request_shape_has_labeled_window_and_conditional_action_question(self):
        item = dict(fingerprint='f', coordinate='v1b0', claim=claim('We are saved by grace alone 0.'), anchor=dict(start=0, end=30),
                    text='We are saved by grace alone 0. Vote.', preceding_text='P', following_text='F')
        spec = verify.build_request(item)
        self.assertEqual(['complete', 'polarity_correct', 'supported', 'voice_correct'], sorted(spec.body['questions']))
        self.assertEqual({'preceding_block': 'P', 'target_block': item['text'], 'following_block': 'F'}, spec.body['state']['window'])
        self.assertEqual(set(contract.FIELDS), set(spec.body['state']['claim']))
        self.assertEqual('jev-1.13.0', spec.body['model'])
        for question in spec.body['questions'].values():
            self.assertEqual('noul', question['type'])
            self.assertIn('`window.target_block`', question['instructions'])
            self.assertEqual({'true', 'false'}, set(question['criteria']))
        for role in contract.SPEECH_ROLES:
            asked = 'action_grounded' in verify.questions(claim('x', speech_role=role))
            self.assertEqual(role in ('requested_of_listener', 'performed'), asked)
        self.assertEqual(5, len(verify.questions(claim('x', speech_role='requested_of_listener'))))

    def test_identical_claims_from_both_producers_are_verified_once(self):
        paths = self.produce([self.anchor_output(0), self.anchor_output(1)])
        items = verify.collect_claims(paths)
        self.assertEqual(2, len(items))
        self.assertTrue(all(sorted(item['producers']) == ['flash', 'pro'] for item in items))

    def test_run_records_probabilities_costs_and_resumes_without_requests(self):
        paths = self.produce([self.anchor_output(0), self.anchor_output(1, speech_role='requested_of_listener')])
        send = jev(0.8)
        result = verify.run(paths, self.ledger, transport=send, state=CLEAN, metadata=METADATA)
        self.assertEqual(dict(claims=2, attempted=2, ok=2, failed=0, lost_attempts=0), result['summary'])
        rows = read_json(Path(result['output']))['rows']
        self.assertEqual([4, 5], sorted(len(row['answers']) for row in rows))
        self.assertTrue(all(value == 0.8 for row in rows for value in row['answers'].values()))
        step = self.ledger.summary()['steps']['verify']
        self.assertEqual((2, 0, '0.000168000'), (step['attempts'], step['unresolved'], step['known_usd']))
        again = verify.run(paths, self.ledger, transport=lambda spec: self.fail('resume re-sent'), state=CLEAN, metadata=METADATA)
        self.assertEqual(2, again['summary']['ok'])

    def test_check_only_sends_nothing_and_writes_no_ledger_entry(self):
        paths = self.produce([self.anchor_output(0)])
        before = self.ledger.attempt_count()
        plan = verify.run(paths, self.ledger, check_only=True, transport=lambda spec: self.fail('sent'))
        self.assertEqual((1, 1, '0.002752512'), (plan['claims'], plan['requests_to_send'], plan['worst_case_reserved_usd']))
        self.assertEqual(before, self.ledger.attempt_count())

    def test_http_failure_keeps_the_reservation_and_is_never_retried(self):
        paths = self.produce([self.anchor_output(i) for i in range(2)])
        send = jev(fail={'v1b1'})
        result = verify.run(paths, self.ledger, transport=send, state=CLEAN, metadata=METADATA)
        self.assertEqual(1, result['summary']['failed'])
        self.assertEqual(1, send.calls.count(next(f for f in send.calls if f)) if send.calls else 1)
        entries = self.ledger.summary()['steps']['verify']
        self.assertEqual(1, entries['unresolved'])
        self.assertIn('stop rule', result['stopped'])  # 1 failure > 5% of 2 claims

    def test_invalid_probability_is_rejected(self):
        paths = self.produce([self.anchor_output(0)])
        result = verify.run(paths, self.ledger, transport=jev(1.5), state=CLEAN, metadata=METADATA)
        self.assertEqual(1, result['summary']['failed'])

    def test_dirty_implementation_refuses_before_dispatch(self):
        paths = self.produce([self.anchor_output(0)])
        with self.assertRaises(ValueError):
            verify.run(paths, self.ledger, transport=lambda spec: self.fail('sent'), state=DIRTY)

    def test_extraction_from_another_strata_file_is_refused(self):
        paths = self.produce([self.anchor_output(0)])
        write_json(self.root / 'strata.json', dict(slice_sha256='s' * 64, blocks=[block(0), block(1)]))
        with self.assertRaises(ValueError):
            verify.collect_claims(paths)


if __name__ == '__main__':
    unittest.main()
