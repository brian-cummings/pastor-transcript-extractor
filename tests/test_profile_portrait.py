"""Portrait warrants compose reviewed points without promoting their authority."""
from copy import deepcopy
import hashlib
import json
import unittest
from pastor_transcript_extractor import profile_portrait as p


def fixture():
    points=[];claims=[]
    for index,vid in [('a',1),('b',2)]:
        points.append(dict(point_id=index,claim_id=index,kind='reviewed_binding',video_ids=[vid],
            frame=dict(voice=dict(occurrence='projected'),adoption=dict(status='adopted'),unknowns=['Actual response unknown.']),
            explanation='An offered statement, not actual hearer uptake.',reviewed_binding_ids=['binding-'+index]))
        claims.append(dict(id=index,evidence_ids=['e-'+index],observation_input_ids=['e-'+index],
            counterevidence_ids=['counter-'+index],recording_support={str(vid):['e-'+index]}))
    reader=dict(explanatory_descriptions=dict(points=points),claims=claims,
        assessment=[[('Original narrow account','a')]],assessment_scope='Original scope.')
    sources={x['point_id']:hashlib.sha256(json.dumps({k:v for k,v in x.items() if k!='claim_id'},sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest() for x in points}
    packet=dict(scope_note='Preliminary; selected passages.',sources=sources,entries=[dict(id='portrait',facet='posture',kind='preliminary_impression',
        text='Confidence is offered to listeners in these passages.',support_point_ids=['a','b'],rationale='Both reviewed invitations offer confidence.',
        limits='Actual response is unknown.',alternative='The reviewed selection may emphasize invitations.',review_status='authored_interpretation_pending_reader_review')],paragraphs=[['portrait']])
    return reader,packet


class PortraitTests(unittest.TestCase):
    def test_interpretation_keeps_trace_counterevidence_and_provisional_authority(self):
        reader,packet=fixture();before=deepcopy(reader)
        result=p.apply(reader,packet)
        self.assertEqual(before['explanatory_descriptions'],result['explanatory_descriptions'])
        self.assertEqual(before['claims'],result['claims'][:2])
        claim=result['claims'][-1]
        self.assertEqual(['a','b'],claim['upstream_claim_ids'])
        self.assertEqual(['counter-a','counter-b'],claim['counterevidence_ids'])
        self.assertEqual(['binding-a','binding-b'],claim['reviewed_binding_ids'])
        self.assertEqual([1,2],claim['scope']['video_ids'])
        self.assertIn('selection',claim['reason'])
        self.assertFalse(result['portrait']['semantic_admission'])
        self.assertFalse(result['portrait']['reader_acceptance'])
        self.assertEqual('preliminary_impression',claim['interpretation_kind'])

    def test_changed_frame_or_missing_support_withholds_impression_and_preserves_narrow_account(self):
        for change in ('frame','missing','counter_source'):
            reader,packet=fixture()
            if change=='frame':reader['explanatory_descriptions']['points'][0]['frame']['unknowns'].append('New qualification')
            elif change=='missing':reader['explanatory_descriptions']['points'].pop()
            else:packet['sources']['a']='stale'
            result=p.apply(reader,packet)
            self.assertEqual([],result['portrait']['entries'])
            self.assertTrue(result['portrait']['withheld'])
            self.assertEqual([[('Original narrow account','a')]],result['assessment'])
            self.assertEqual(2,len(result['claims']))

    def test_unsupported_concern_without_warrant_limit_or_alternative_cannot_appear(self):
        for key in ('support_point_ids','rationale','limits','alternative'):
            reader,packet=fixture();packet['entries'][0][key]=[] if key=='support_point_ids' else ''
            result=p.apply(reader,packet)
            self.assertEqual([],result['portrait']['entries'])

    def test_partial_support_narrows_portrait_without_inventing_missing_dimension(self):
        reader,packet=fixture()
        second=deepcopy(packet['entries'][0]);second.update(id='missing-center',support_point_ids=['absent'])
        packet['entries'].append(second);packet['paragraphs'][0].append('missing-center')
        result=p.apply(reader,packet)
        self.assertEqual(1,len(result['portrait']['entries']))
        self.assertIn('withheld',result['assessment_scope'])
        self.assertEqual([('Confidence is offered to listeners in these passages.','portrait')],result['assessment'][0])

    def test_portrait_reuses_existing_examples_instead_of_creating_new_measurement_selection(self):
        from pastor_transcript_extractor import profile_description, profile_supporting_blocks
        from test_profile_description import fixture as evidence_fixture
        record=profile_description.build(*evidence_fixture())
        before=profile_supporting_blocks.build(record)
        changed=deepcopy(record)
        changed['reader']['claims'].append(dict(id='portrait-provisional',
            analytical_basis='reviewed_cross_point_interpretation',evidence_ids=[record['observations'][0]['id']]))
        self.assertEqual(before,profile_supporting_blocks.build(changed))
