import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from typer.testing import CliRunner
from pastor_transcript_extractor import evidence_pipeline_trace as t
from pastor_transcript_extractor.sermon_classification import TranscriptBlock


class TraceTests(unittest.TestCase):
    def test_presence_is_whitespace_only_not_fuzzy(self):
        spans=[dict(text='do not\ngo')]
        self.assertTrue(t.span_presence(spans,'do not go')['all_present'])
        self.assertFalse(t.span_presence(spans,'do not go')['literal_all_present'])
        self.assertFalse(t.span_presence(spans,'do go')['all_present'])
        self.assertFalse(t.span_presence(spans,'DO NOT GO')['all_present'])

    def test_canonical_identity_and_conservative_timestamps(self):
        source=dict(text='come now',units=[dict(unit_id='u',start=0,end=8,source_segment_indexes=[3,4],start_seconds=10,end_seconds=14)])
        loc=t.source_location(source,dict(start=5,end=8,text='now'))
        self.assertEqual([3,4],loc['source_segment_indexes']);self.assertEqual(10,loc['conservative_start_seconds'])
        with self.assertRaisesRegex(ValueError,'canonical'):t.source_location(source,dict(start=5,end=8,text='Now'))

    def test_block_identity_keeps_ordinal_and_oversize_visible(self):
        b=TranscriptBlock(0,[0],0,120,'x'*4000)
        self.assertNotEqual(t.block_row(b,0),t.block_row(b,10))
        self.assertTrue(t.block_row(b)['exceeds_60_second_target'])
        self.assertTrue(t.block_row(b)['exceeds_3200_character_target'])

    def test_seal_and_dependency_verification(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'report.json';p.write_text(json.dumps(t.seal(dict(n=1))))
            self.assertEqual(1,t.read(p,True)['n'])
            p.write_text(json.dumps(dict(n=2,content_fingerprint='bad')))
            with self.assertRaisesRegex(ValueError,'seal'):t.read(p,True)

    def test_immutable_report_under_configured_base(self):
        with tempfile.TemporaryDirectory() as d:
            report=t.seal(dict(version='synthetic'))
            path=t.save_report(report,Path(d));self.assertTrue(path.is_relative_to(Path(d).resolve()))
            self.assertEqual(path,t.save_report(report,Path(d)))
            with self.assertRaisesRegex(ValueError,'preserve'):t.save_report(t.seal(dict(version='changed')),Path(d))

    def test_cli_check_only_never_builds_or_infers(self):
        from pastor_transcript_extractor.cli import app
        with patch.object(t,'verify',return_value=(dict(status='diagnostic',content_fingerprint='synthetic'),Path('/tmp/synthetic'))),patch.object(t,'build',side_effect=AssertionError('No rebuild')):
            r=CliRunner().invoke(app,['analysis','structure-readiness','--evidence-trace','--check-only'])
            self.assertEqual(0,r.exit_code,r.output);self.assertIn('provider_requests=0',r.output)
        r=CliRunner().invoke(app,['analysis','structure-readiness','--check-only'])
        self.assertEqual(2,r.exit_code)
