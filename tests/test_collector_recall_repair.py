"""Synthetic comparison, selection and CLI tests; no source dataset execution."""
import unittest
from unittest.mock import patch
from typer.testing import CliRunner
from pastor_transcript_extractor import collector_recall_repair as r
from pastor_transcript_extractor.cli import app


def row(rid,hits):
    return dict(reference_id=rid,video_id=1565,route='G3_current',classification='definite_compatible_opportunity',role_containment_hits=hits,required_evidence_coverage_hits=hits)


class DevelopmentReviewTests(unittest.TestCase):
    def test_recovery_and_regression_are_both_visible(self):
        before=[row('a',['old']),row('b',[])];after=[row('a',[]),row('b',['new'])]
        result=r.compare_rows(before,after)['G3_current']
        self.assertEqual(['b'],result['recovered_reference_ids'])
        self.assertEqual(['a'],result['regressed_reference_ids'])
        self.assertEqual(.5,result['development_recall_upper_bound'])

    def test_unresolved_opportunity_does_not_enter_denominator(self):
        uncertain=row('uncertain',['hit']);uncertain['classification']='unresolved_provenance'
        result=r.compare_rows([row('a',[])],[row('a',[]),uncertain])['G3_current']
        self.assertEqual(1,result['opportunities'])

    def test_unmatched_and_control_contacts_are_not_semantic_false_positives(self):
        c=dict(candidate=dict(video_id=1565,capability='G3',candidate_id='new',endpoints=dict(utterance=dict(start=0,end=25,text='He waved to the traveler.'),circumstance=None)))
        control=dict(control_id='narration',classification='act_narration_control',span=dict(start=0,end=25))
        burden=r.burden([c],[],set(),[control])
        self.assertEqual(1,burden['new_reference_unmatched_candidate_count'])
        self.assertEqual(['new'],burden['control_contacts'][0]['candidate_ids'])
        self.assertIsNone(burden['semantically_false_positive_candidates'])

    def test_selection_is_metadata_only_stable_and_excludes_all_exposed_channels(self):
        rows=[dict(video_id=i,source_id=i,youtube_video_id=f'video-{i}',title='Sermon',duration_seconds=2000) for i in range(1,12)]
        metadata=lambda _:dict(final_disposition=dict(status='accepted_sermon'),guest_speaker_suspected=False)
        selected=r.select_confirmation_rows(rows,metadata,{1,2,3},{4})
        self.assertEqual(selected,r.select_confirmation_rows(list(reversed(rows)),metadata,{1,2,3},{4}))
        self.assertEqual(4,len(selected))
        self.assertFalse({1,2,3}&{x['source_id'] for x in selected})
        self.assertNotIn(4,{x['video_id'] for x in selected})
        self.assertEqual(['primary']*3+['technical_reserve_only'],[x['role'] for x in selected])

    def test_bad_metadata_is_technical_exclusion_not_opportunity_selection(self):
        rows=[dict(video_id=i,source_id=i,youtube_video_id=f'video-{i}',title='Bible Answers Live' if i==1 else 'Message') for i in range(1,9)]
        def meta(x):return dict(final_disposition=dict(status='accepted_sermon'),guest_speaker_suspected=x['video_id']==2)
        selected=r.select_confirmation_rows(rows,meta,set(),set())
        self.assertFalse({1,2}&{x['video_id'] for x in selected})

    def test_cli_defaults_to_read_only_and_requires_bound_input(self):
        with patch.object(r,'verify',return_value=(dict(content_fingerprint='sealed'),{})), \
             patch.object(r,'run_development',side_effect=AssertionError('no dataset')):
            result=CliRunner().invoke(app,['analysis','collector-recall-repair','--check-only'])
        self.assertEqual(0,result.exit_code,result.output)
        for options in (['--run-development'],['--approve-input','wrong'],['--prepare-confirmation'],['--execute-paid']):
            result=CliRunner().invoke(app,['analysis','collector-recall-repair',*options])
            self.assertNotEqual(0,result.exit_code)
