import unittest
from unittest import mock

from pastor_transcript_extractor.bound_claims import pipeline


class PipelineTests(unittest.TestCase):
    def patched(self, extract_results=None, verify_result=None):
        calls = []
        extract_results = extract_results or {}

        def record(name, value):
            def inner(*args, **kwargs):
                calls.append(name if name != 'extract' else 'extract_' + args[1])
                return value(args) if callable(value) else value
            return inner
        return calls, [
            mock.patch.object(pipeline.leaf_pass, 'run', record('leaf', dict(packs='TSPH'))),
            mock.patch.object(pipeline.strata, 'run', record('strata', dict(block_count=100))),
            mock.patch.object(pipeline.extract, 'run', record('extract', lambda a: extract_results.get(a[1], dict(stopped=None)))),
            mock.patch.object(pipeline.verify, 'run', record('verify', verify_result or dict(stopped=None))),
        ]

    def run_with(self, **options):
        calls, patches = self.patched(**options)
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            return calls, pipeline.run(directory, 'sha')

    def test_runs_every_paid_step_in_order_with_the_default_packs(self):
        calls, result = self.run_with()
        self.assertEqual(['leaf', 'strata', 'extract_pro', 'extract_flash', 'verify'], calls)
        self.assertEqual('COMPLETE', result['status'])

    def test_a_pro_stop_halts_before_flash_and_verification(self):
        calls, result = self.run_with(extract_results={'pro': dict(stopped='stop rule: x')})
        self.assertEqual(['leaf', 'strata', 'extract_pro'], calls)
        self.assertEqual(('STOPPED', 'extract_pro'), (result['status'], result['stopped_at']))

    def test_a_verification_stop_is_reported(self):
        _, result = self.run_with(verify_result=dict(stopped='stop rule: y'))
        self.assertEqual(('STOPPED', 'verify'), (result['status'], result['stopped_at']))

    def test_check_only_stops_after_the_leaf_census(self):
        calls, patches = self.patched()
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            result = pipeline.run(directory, 'sha', check_only=True)
        self.assertEqual(['leaf'], calls)
        self.assertEqual('CHECK_ONLY', result['status'])


if __name__ == '__main__':
    unittest.main()
