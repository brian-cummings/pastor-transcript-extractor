import json
from pathlib import Path
import unittest
from unittest import mock

from typer.testing import CliRunner

from pastor_transcript_extractor.cli import app
from pastor_transcript_extractor.bound_claims.common import file_sha256, write_json
from pastor_transcript_extractor.bound_claims import slice as slicing

try:
    from tests.bound_claims_support import PilotBuilder
    from tests.test_bound_claims_selection import write_sermon
except ImportError:
    from bound_claims_support import PilotBuilder
    from test_bound_claims_selection import write_sermon

COMMANDS = ('slice-propose', 'leaf-run', 'strata', 'extract', 'verify', 'review-queue', 'review', 'report', 'render')


class CliTests(PilotBuilder, unittest.TestCase):
    def invoke(self, *arguments):
        return CliRunner().invoke(app, ['analysis', 'bound-claims', *arguments])

    def test_group_lists_every_subcommand_and_each_has_help(self):
        listing = self.invoke('--help')
        self.assertEqual(0, listing.exit_code, listing.output)
        for command in COMMANDS:
            self.assertIn(command, listing.output)
            result = self.invoke(command, '--help')
            self.assertEqual(0, result.exit_code, f'{command}: {result.output}')

    def test_leaf_run_check_only_opens_no_client_and_prints_the_census(self):
        source = write_sermon(Path(self.directory.name), 'a', [(0.8, 0.0), (0.5, 0.0)])
        slice_path = self.root / 'slice.json'
        write_json(slice_path, dict(version=slicing.VERSION, sermons=[dict(
            profile_id=1, video_id=7, youtube_video_id='y', title='T', url='https://youtu.be/7', source_path=str(source),
            source_sha256=file_sha256(source), cache_dir=str(source.parent / 'inference-cache'), model='jev-1.13.0', block_count=2)]))
        with mock.patch('pastor_transcript_extractor.recording_verifier_typesafe.TypeSafeSdkAdapter',
                        side_effect=AssertionError('opened a client')):
            result = self.invoke('leaf-run', '--slice', str(slice_path), '--approve-slice', file_sha256(slice_path), '--check-only')
        self.assertEqual(0, result.exit_code, result.output)
        plan = json.loads(result.output)
        self.assertEqual(({'T': 2, 'S': 2, 'P': 2, 'H': 2}, 2), ({k: v for k, v in plan['cache_misses'].items() if k in 'TSPH'}, plan['blocks']))
        self.assertFalse((self.root / 'ledger.json').exists())

    def test_wrong_slice_approval_is_a_usage_error(self):
        slice_path = self.root / 'slice.json'
        write_json(slice_path, dict(version=slicing.VERSION, sermons=[]))
        result = self.invoke('leaf-run', '--slice', str(slice_path), '--approve-slice', '0' * 64, '--check-only')
        self.assertEqual(2, result.exit_code)
        self.assertIn('approved SHA-256', result.output)

    def test_extract_and_verify_check_only_send_nothing(self):
        self.build(range(3), range(3))
        for producer in ('pro', 'flash'):
            with mock.patch('pastor_transcript_extractor.deepinfra_requests.transport', side_effect=AssertionError('sent')):
                result = self.invoke('extract', '--strata', str(self.root / 'strata.json'), '--producer', producer, '--check-only')
            self.assertEqual(0, result.exit_code, result.output)
            self.assertEqual(0, json.loads(result.output)['requests_to_send'])
        with mock.patch('pastor_transcript_extractor.evidence_requests.typesafe_transport', side_effect=AssertionError('sent')):
            result = self.invoke('verify', '--extraction', str(self.root / 'extract/pro/extraction.json'),
                                 '--extraction', str(self.root / 'extract/flash/extraction.json'), '--check-only')
        self.assertEqual(0, result.exit_code, result.output)
        self.assertEqual(0, json.loads(result.output)['requests_to_send'])

    def test_unknown_producer_is_a_usage_error(self):
        self.build(range(1), range(1))
        result = self.invoke('extract', '--strata', str(self.root / 'strata.json'), '--producer', 'gpt', '--check-only')
        self.assertEqual(2, result.exit_code)

    def test_review_report_and_render_run_end_to_end(self):
        self.build(range(6), range(8), accept={f'v1b{i}' for i in range(6)})
        queue = self.invoke('review-queue', '--pilot', str(self.root), '--output', str(self.root / 'queue-copy.json'))
        self.assertEqual(0, queue.exit_code, queue.output)
        replay = self.invoke('review', '--pilot', str(self.root), '--decisions', str(self.root / 'labels.json'))
        self.assertEqual(0, json.loads(replay.output)['remaining'])
        rendered = self.invoke('render', '--pilot', str(self.root))
        self.assertEqual(0, rendered.exit_code, rendered.output)
        reported = self.invoke('report', '--pilot', str(self.root))
        self.assertEqual('PASS', json.loads(reported.output)['status'], reported.output)

    def test_slice_propose_refuses_a_repository_output(self):
        repository = Path(__file__).resolve().parents[1]
        result = self.invoke('slice-propose', '--base-dir', self.directory.name, '--output', str(repository / 'slice.json'))
        self.assertEqual(2, result.exit_code)
        self.assertFalse((repository / 'slice.json').exists())


if __name__ == '__main__':
    unittest.main()
