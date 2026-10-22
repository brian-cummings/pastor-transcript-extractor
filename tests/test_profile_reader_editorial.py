"""Editorial wording must remain pinned to the whole reviewed source point."""
from copy import deepcopy
import hashlib
import json
import unittest
from pastor_transcript_extractor import profile_presentation as p


def point(identity, kind='reviewed_binding', vid=1):
    return dict(point_id=identity,claim_id=identity,kind=kind,video_ids=[vid],
        explanation='The preacher invites confidence; actual listener status is unresolved.',
        evidence_ids=['evidence-'+identity],frame=dict(voice=dict(occurrence='projected'),
        adoption=dict(status='undetermined'),conditions=[],qualifications=[],unknowns=['Actual status unknown.']))


def entry(value):
    original={k:v for k,v in value.items() if k!='claim_id'}
    return dict(point_id=value['point_id'],expected_point_sha256=hashlib.sha256(
        json.dumps(original,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest(),
        text='The invitation offers confidence; it does not establish a listener’s actual status.')


def reader(points):
    return dict(explanatory_descriptions=dict(points=points),titles={1:'First sermon',2:'Second sermon'},
        assessment=[[('Fuller fallback wording','original')]],at_a_glance=[])


class ReaderEditorialTests(unittest.TestCase):
    def test_exact_review_is_reworded_with_same_claim_link_and_recording_scope(self):
        points=[point('one'),point('two',vid=2)]
        original=deepcopy(points)
        result=p._apply_reviewed_editorial(reader(points),[entry(x) for x in points])
        self.assertEqual(original,points)
        self.assertEqual(['one','two'],result['editorial_review']['applied_point_ids'])
        self.assertFalse(result['editorial_review']['semantic_admission'])
        self.assertIn('First sermon',result['assessment'][0][0][0])
        self.assertNotIn('Second sermon',result['assessment'][0][0][0])
        self.assertEqual('one',result['assessment'][0][0][1])
        self.assertIn('proposals',result['assessment_scope'])

    def test_changed_frame_evidence_or_explanation_cannot_receive_authored_wording(self):
        original=point('one');approved=entry(original)
        for field in ('frame','evidence_ids','explanation','video_ids'):
            changed=deepcopy(original)
            changed[field]={'changed':True} if field=='frame' else ['changed'] if field in ('evidence_ids','video_ids') else 'Different proposition'
            result=p._apply_reviewed_editorial(reader([changed]),[approved])
            self.assertEqual([],result['editorial_review']['applied_point_ids'])
            self.assertTrue(result['editorial_review']['withheld'])
            self.assertEqual([[('Fuller fallback wording','original')]],result['assessment'])

    def test_one_stale_point_does_not_hide_other_reviewed_content_or_repair_stale_prose(self):
        first=point('one');second=point('two')
        entries=[entry(first),entry(second)]
        first['frame']['unknowns'].append('New unknown')
        result=p._apply_reviewed_editorial(reader([first,second]),entries)
        self.assertEqual(['two'],result['editorial_review']['applied_point_ids'])
        text=' '.join(text for paragraph in result['assessment'] for text,key in paragraph)
        self.assertIn('These words are offered for someone to say',text)
        self.assertIn('The invitation offers confidence',text)
