"""Focused synthetic guards for fresh V3 preparation, no real-source discovery."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from typer.testing import CliRunner
from pastor_transcript_extractor import fresh_discovery_confirmation_v3 as c
from pastor_transcript_extractor.cli import app


def manifest():
    return dict(content_fingerprint='m',sources=[dict(video_id=i,source_id=i+10,role='primary' if i<4 else 'technical_reserve_only') for i in range(1,5)])


def validation():
    return dict(manifest_fingerprint='m',all_three_usable=True,active_video_ids=[1,2,3],technical_exclusions=[])


class FreshV3PreparationTests(unittest.TestCase):
    def test_only_technical_reserve_substitution_allowed(self):
        m=manifest();v=validation();self.assertEqual([1,2,3],c.validate_selection(m,v))
        v['active_video_ids']=[1,2,4];v['technical_exclusions']=[dict(video_id=3,reason='non_sermon')]
        self.assertEqual([1,2,4],c.validate_selection(m,v))
        v['technical_exclusions'][0]['reason']='low_G2_recall'
        with self.assertRaises(ValueError):c.validate_selection(m,v)

    def test_two_technical_exclusions_preserve_three_active_sources(self):
        m=manifest();m['sources'].append(dict(video_id=5,source_id=15,role='technical_reserve_only'))
        v=validation();v['active_video_ids']=[1,4,5]
        v['technical_exclusions']=[dict(video_id=i,reason='non_sermon') for i in (2,3)]
        self.assertEqual([1,4,5],c.validate_selection(m,v))
        v['technical_exclusions'][0]['reason']='few_opportunities'
        with self.assertRaises(ValueError):c.validate_selection(m,v)

    def test_punctuation_quality_cannot_replace_source(self):
        v=validation();v['active_video_ids']=[1,2,4];v['technical_exclusions']=[dict(video_id=3,reason='sparse_punctuation')]
        with self.assertRaises(ValueError):c.validate_selection(manifest(),v)
        v=validation();v['technical_exclusions']=[dict(video_id=4,reason='duplicate')]
        with self.assertRaises(ValueError):c.validate_selection(manifest(),v)

    def test_all_prior_primary_reserve_and_development_channels_excluded(self):
        previous=dict(excluded_source_ids=[10,20],excluded_video_ids=[100],sources=[dict(source_id=30,video_id=300),dict(source_id=40,video_id=400)])
        with patch.object(c.prep.gate,'sealed',return_value=previous):
            es,ev=c.exposure_sets()
        self.assertEqual({10,20,30,40},es);self.assertEqual({100,300,400},ev)

    def test_reference_existence_blocks_regeneration(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);docs=root/'docs';docs.mkdir()
            with patch.object(c,'REFERENCES',docs/'references-v3.json'),patch.object(c,'HERE',docs):
                c.freeze_guard(root)
                (docs/'census-999-v3.json').write_text('{}')
                with self.assertRaises(ValueError):c.freeze_guard(root)

    def test_unit_preflight_is_bounded_without_collector_execution(self):
        text='unpunctuated words '*150
        source=dict(video_id=999999,text=text,main_span=dict(start=0,end=len(text)),units=[])
        with patch.object(c.collector,'discover',side_effect=AssertionError('No discovery')):
            rows=c.size_preflight([source])
        self.assertLessEqual(rows[0]['unit_max_chars'],400)
        self.assertLess(rows[0]['G2_G3_upper_bound'],12000)

    def test_existing_selection_reused_without_selecting_new_sources(self):
        m=manifest()
        with patch.object(c,'authority'),patch.object(Path,'exists',return_value=True),patch.object(c,'verify',return_value=(m,{})), \
                patch.object(c.previous.repair,'select_confirmation_rows',side_effect=AssertionError('No reselection')):
            self.assertEqual(m,c.select_sources())

    def test_v3_cli_does_not_delegate_to_old_collector(self):
        with patch.object(c,'verify',return_value=(manifest(),{})):
            with patch.object(c,'validated_sources',side_effect=FileNotFoundError('not validated')):
                result=CliRunner().invoke(app,['analysis','fresh-discovery-readiness','--revision','v3','--check-only'])
        self.assertEqual(0,result.exit_code,result.output)


if __name__=='__main__':unittest.main()
