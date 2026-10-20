import unittest
from pathlib import Path
from unittest.mock import patch
from typer.testing import CliRunner
from pastor_transcript_extractor import unit_span_readiness as r
from pastor_transcript_extractor.collector_retrieval_json_v1_1 import seal


def fixture(text,units,lo=0,hi=None):
    hi=len(text) if hi is None else hi
    source=seal(dict(text=text,units=[dict(unit_id=str(i),start=a,end=b,text=text[a:b]) for i,(a,b) in enumerate(units)]))
    context=seal(dict(source_fingerprint=source['content_fingerprint'],start=lo,end=hi,text=text[lo:hi]))
    return source,context


class UnitSpanTests(unittest.TestCase):
    def test_distinct_focal_roles_in_one_unit_cannot_be_nonoverlapping(self):
        s,c=fixture('quote gloss',[(0,11)])
        x=r.check_roles(s,c,'G2',dict(left=dict(start=0,end=5,text='quote'),right=dict(start=6,end=11,text='gloss')))
        self.assertTrue(x['directed_roles_overlap']);self.assertFalse(x['all_roles_exact'])

    def test_separate_exact_units_represent_roles_without_enumerating_pairs(self):
        s,c=fixture('quote\ngloss',[(0,5),(6,11)])
        x=r.check_roles(s,c,'G2',dict(left=dict(start=0,end=5,text='quote'),right=dict(start=6,end=11,text='gloss')))
        self.assertFalse(x['directed_roles_overlap']);self.assertTrue(x['all_roles_exact'])

    def test_edge_units_are_not_clipped_or_expanded_outside_context(self):
        s,c=fixture('first unit\nsecond',[(0,10),(11,17)],lo=3)
        x=r.inventory(s,c);self.assertEqual(['0'],x['excluded_partial_unit_ids'])
        self.assertEqual('whole_cover_requires_outside_context',r.cover(s,c,dict(start=6,end=10,text='unit'))['status'])

    def test_cover_preserves_canonical_newlines(self):
        s,c=fixture('one\ntwo',[(0,3),(4,7)])
        x=r.cover(s,c,dict(start=1,end=6,text='ne\ntw'))
        self.assertEqual('one\ntwo',x['text']);self.assertEqual(2,x['extra_characters'])

    def test_foreign_reference_and_source_fail(self):
        s,c=fixture('source',[(0,6)])
        with self.assertRaises(ValueError):r.cover(s,c,dict(start=0,end=3,text='bad'))
        with self.assertRaises(ValueError):r.inventory(s,seal({**c,'source_fingerprint':'foreign'}))

    def test_cli_offline_check_and_mode_conflicts(self):
        from pastor_transcript_extractor.cli import app
        result=seal(dict(status='STOP',counts={}))
        with patch.object(r,'prepare',return_value=(result,Path('/tmp/synthetic'))):
            x=CliRunner().invoke(app,['analysis','structure-readiness','--unit-span-check','--json'])
            self.assertEqual(0,x.exit_code,x.output)
        x=CliRunner().invoke(app,['analysis','structure-readiness','--unit-span-check','--run-selection'])
        self.assertEqual(2,x.exit_code)
