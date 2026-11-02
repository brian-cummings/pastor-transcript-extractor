import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from pastor_transcript_extractor import response_presence_diagnostic as diagnostic
from pastor_transcript_extractor import response_presence_execution as execution
from test_response_presence_diagnostic import fixture


def answer(spec):
    return execution.requests.WireResponse(200, json.dumps(dict(model='jev-1.13.0',
        usage=dict(input_tokens=100, output_tokens=0),
        answers={k: dict(type='noul', noul=.1 if k.startswith(diagnostic.BACKGROUND) else .95)
                 for k in spec.body['questions']})))


class PresenceExecutionTests(unittest.TestCase):
    def prepare(self, root):
        prepared = diagnostic.prepare(root, fixture(root))
        return prepared['packet'], prepared['fingerprint']

    def test_all_pass_three_calls_wire_reconstruction_and_idempotent_reporting(self):
        with TemporaryDirectory() as directory:
            path, fingerprint = self.prepare(Path(directory))
            with patch.object(execution.requests, 'typesafe_transport', side_effect=answer) as send:
                result = execution.run(path, fingerprint, transport=send)
            self.assertEqual(3, send.call_count)
            self.assertEqual('PASS', result['status'])
            self.assertEqual(5, len(result['rows']))
            self.assertEqual('0.0000126', result['costs']['usage_based_usd'])
            self.assertEqual(result, execution.report(path))
            with patch.dict('os.environ', {'TYPESAFE_API_KEY': 'test'}), \
                 patch.object(execution.requests, 'typesafe_transport', side_effect=AssertionError('No retries')):
                self.assertEqual(result, execution.run(path, fingerprint))

    def test_failed_expectation_stops_after_first_request_and_stays_stopped(self):
        with TemporaryDirectory() as directory:
            path, fingerprint = self.prepare(Path(directory))
            def failed(spec):
                wire = answer(spec); body = json.loads(wire.text)
                body['answers'][diagnostic.TARGETS['A1']+':requested_response_present']['noul'] = .89
                return execution.requests.WireResponse(200, json.dumps(body))
            with patch.dict('os.environ', {'TYPESAFE_API_KEY': 'test'}), \
                 patch.object(execution.requests, 'typesafe_transport', side_effect=failed) as send:
                result = execution.run(path, fingerprint)
                self.assertEqual(result, execution.run(path, fingerprint))
            self.assertEqual(1, send.call_count)
            self.assertEqual('STOPPED', result['status'])
            self.assertEqual('Presence acceptance failed; stop without another variant', result['failure'])
            self.assertEqual(.89, next(r['presence_probability'] for r in result['rows'] if r['label'] == 'A1'))
            self.assertEqual(2, len(result['not_run']))

    def test_lost_response_cannot_retry_or_advance_even_without_assessment(self):
        with TemporaryDirectory() as directory:
            path, fingerprint = self.prepare(Path(directory))
            with patch.object(execution.requests, 'typesafe_transport', side_effect=RuntimeError('lost')) as send:
                # Injected transport avoids credentials and still uses the real executor.
                result = execution.run(path, fingerprint, transport=send)
                root = Path(path).parent/'execution'
                (root/'assessment.json').unlink(); (root/'assessment.md').unlink()
                again = execution.run(path, fingerprint, transport=send)
            self.assertEqual(1, send.call_count)
            self.assertEqual('STOPPED', result['status'])
            self.assertEqual(result, again)
            self.assertEqual('0.002752512', result['costs']['retained_attempt_reservations_usd'])

    def test_bad_approval_check_only_and_missing_credentials_make_no_calls(self):
        with TemporaryDirectory() as directory:
            path, fingerprint = self.prepare(Path(directory))
            with patch.object(execution.requests, 'typesafe_transport', side_effect=AssertionError('No calls')):
                with self.assertRaisesRegex(ValueError, 'approval required'):
                    execution.run(path, 'wrong')
                self.assertEqual('CHECKED_NO_CALLS', execution.run(path, fingerprint, check_only=True)['status'])
                with patch.dict('os.environ', {}, clear=True):
                    with self.assertRaisesRegex(ValueError, 'credential absent'):
                        execution.run(path, fingerprint)
            self.assertFalse((Path(path).parent/'execution').exists())

    def test_missing_answer_stops_without_next_request(self):
        with TemporaryDirectory() as directory:
            path, fingerprint = self.prepare(Path(directory))
            def missing(spec):
                return dict(model='jev-1.13.0', complete=True,
                    usage=dict(input_tokens=100, output_tokens=0), output={})
            with patch.object(execution.requests, 'typesafe_transport', side_effect=missing) as send:
                result = execution.run(path, fingerprint, transport=send)
            self.assertEqual(1, send.call_count)
            self.assertEqual('STOPPED', result['status'])
            self.assertIn('Invalid presence answer', result['failure'])


if __name__ == '__main__':
    unittest.main()
