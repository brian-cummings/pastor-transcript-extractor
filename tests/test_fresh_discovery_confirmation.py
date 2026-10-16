"""Synthetic Fresh V2 orchestration guards; no real source discovery/census."""
import unittest
from pathlib import Path
from unittest.mock import patch
from tempfile import TemporaryDirectory
from typer.testing import CliRunner
from pastor_transcript_extractor import fresh_discovery_confirmation as f
from pastor_transcript_extractor.cli import app


class ConfirmationTests(unittest.TestCase):
    def test_preview_does_not_call_discovery_or_read_references(self):
        source=f.prep.seal(dict(video_id=90,text='A synthetic sermon.',main_span=dict(start=0,end=19)))
        with TemporaryDirectory() as directory,patch.object(f,'verify',return_value=(dict(sources=[dict(video_id=90,role='primary')]),{})), \
             patch.object(f,'snapshot',return_value=source),patch.object(f,'directory',return_value=Path(directory)), \
             patch.object(f.repair.collector,'discover',side_effect=AssertionError('no discovery')):
            self.assertEqual([90],f.preview())
            self.assertTrue((Path(directory)/'sources/90.json').is_file())

    def test_existing_census_blocks_refreezing(self):
        with TemporaryDirectory() as directory,patch.object(f,'verify',return_value=({},{})), \
             patch.object(f,'directory',return_value=Path(directory)),patch.object(f,'REFERENCES',Path(directory)/'refs.json'), \
             patch.object(f,'validated_sources',side_effect=AssertionError('no new sources')):
            f.REFERENCES.write_text('{}')
            with self.assertRaisesRegex(ValueError,'Never regenerate'):f.freeze()

    def test_cli_v2_is_provider_free_and_requires_explicit_reserve_preview(self):
        with patch.object(f,'verify',return_value=(dict(content_fingerprint='manifest'),{})), \
             patch.object(f,'freeze',side_effect=AssertionError('no discovery')):
            result=CliRunner().invoke(app,['analysis','fresh-discovery-readiness','--revision','v2','--check-only'])
        self.assertEqual(0,result.exit_code,result.output)
        for options in (['--include-reserve'],['--execute'],['--execute-paid']):
            result=CliRunner().invoke(app,['analysis','fresh-discovery-readiness','--revision','v2',*options])
            self.assertNotEqual(0,result.exit_code)
