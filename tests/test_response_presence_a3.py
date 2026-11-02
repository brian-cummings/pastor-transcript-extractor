import json
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from pastor_transcript_extractor import response_presence_a3 as a3
from pastor_transcript_extractor import response_presence_diagnostic as diagnostic
from pastor_transcript_extractor import response_presence_execution as execution
from test_response_presence_diagnostic import fixture
from test_response_presence_execution import answer


class A3Tests(unittest.TestCase):
    def prepare(self, directory):
        parent = diagnostic.prepare(Path(directory), fixture(Path(directory)))
        def failed(spec):
            wire = answer(spec); raw = json.loads(wire.text)
            for value in raw['answers'].values():
                value['noul'] = .34
            return execution.requests.WireResponse(200, json.dumps(raw))
        execution.run(parent['packet'], parent['fingerprint'], transport=failed)
        prepared = a3.prepare(parent['packet'])
        return parent['packet'], prepared['packet'], prepared['fingerprint']

    def test_single_pass_exact_payload_and_parent_unchanged(self):
        with TemporaryDirectory() as directory:
            parent, path, fp = self.prepare(directory)
            original = execution.report(parent)
            historical = {p: p.read_bytes() for p in (Path(parent).parent/'execution').rglob('*') if p.is_file()}
            batch = diagnostic.report(parent)['batches'][2]
            def send(spec):
                self.assertEqual(batch['request'], execution.asdict(spec))
                self.assertEqual(batch['fingerprint'], spec.fingerprint)
                return answer(spec)
            with patch.object(a3.requests, 'typesafe_transport', side_effect=send) as mock, patch.dict('os.environ', {'TYPESAFE_API_KEY': 'test'}):
                result = a3.run(path, fp)
                self.assertEqual(result, a3.run(path, fp))
            self.assertEqual(1, mock.call_count)
            self.assertEqual('PASS', result['status'])
            self.assertEqual(result, a3.report(path))
            self.assertEqual(original, execution.report(parent))
            self.assertTrue(all(p.read_bytes() == data for p, data in historical.items()))

    def test_failed_or_lost_answer_never_retried_without_saved_assessment(self):
        for lost in (False, True):
            with self.subTest(lost=lost), TemporaryDirectory() as directory:
                _, path, fp = self.prepare(directory)
                def send(spec):
                    if lost:
                        raise RuntimeError('lost')
                    wire = answer(spec); raw = json.loads(wire.text)
                    next(iter(raw['answers'].values()))['noul'] = .89
                    return execution.requests.WireResponse(200, json.dumps(raw))
                with patch.object(a3.requests, 'typesafe_transport', side_effect=send) as mock, patch.dict('os.environ', {'TYPESAFE_API_KEY': 'test'}):
                    result = a3.run(path, fp)
                    root = Path(path).parent/'execution'
                    (root/'assessment.json').unlink(); (root/'assessment.md').unlink()
                    self.assertEqual(result, a3.run(path, fp))
                self.assertEqual(1, mock.call_count)
                self.assertEqual('STOPPED', result['status'])
                self.assertEqual('0.002752512', result['costs']['retained_attempt_reservations_usd'])

    def test_guards_before_dispatch(self):
        with TemporaryDirectory() as directory:
            _, path, fp = self.prepare(directory)
            with self.assertRaisesRegex(ValueError, 'approval required'):
                a3.run(path, 'wrong')
            self.assertEqual('CHECKED_NO_CALLS', a3.run(path, fp, check_only=True)['status'])
            with patch.object(a3.requests, 'request_reservation', return_value=Decimal('.02')):
                with self.assertRaisesRegex(ValueError, 'changed'):
                    a3.run(path, fp, check_only=True)
            copied = Path(directory)/'copy.json'; copied.write_bytes(Path(path).read_bytes())
            with self.assertRaisesRegex(ValueError, 'canonical'):
                a3.run(copied, fp, check_only=True)
            proposal = json.loads(Path(path).read_text())
            proposal['batch']['request']['body']['model'] = 'different'
            Path(path).write_text(json.dumps(proposal))
            with self.assertRaisesRegex(ValueError, 'lineage changed'):
                a3.run(path, fp, check_only=True)
            with self.assertRaisesRegex(ValueError, 'one-attempt'):
                a3.Ledger().check([{}], 'source_verification')


if __name__ == '__main__':
    unittest.main()
