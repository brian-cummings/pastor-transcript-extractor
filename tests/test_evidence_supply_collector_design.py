from copy import deepcopy
import unittest
from unittest.mock import patch

from typer.testing import CliRunner
from pastor_transcript_extractor.cli import app
from pastor_transcript_extractor import evidence_supply_collector_design as design
from pastor_transcript_extractor import sermon_g3_feasibility_review as g3
from pastor_transcript_extractor import sermon_g3_feasibility_revision as g3v2


def source(text):
    return dict(video_id=999,text=text,main_span=dict(start=0,end=len(text)))


def span(s, text):
    start=s['text'].index(text)
    return dict(start=start,end=start+len(text),text=text)


class CollectorDesignTests(unittest.TestCase):
    def test_same_sentence_distinct_roles_are_representable(self):
        s=source('Luke 15 says prodigal means wasteful living.')
        r=design.represent(s,'G2',dict(left=span(s,'prodigal'),right=span(s,'means wasteful living')))
        self.assertEqual(r['status'],'represented')
        self.assertEqual(len(design.v2.sentences(s)),1)

    def test_overlapping_G2_roles_are_deferred_not_fabricated(self):
        s=source('The gospel means good news.')
        r=design.represent(s,'G2',dict(left=span(s,'gospel means'),right=span(s,'means good news')))
        self.assertEqual(r['reason'],'overlapping_G2_endpoint_roles')

    def test_G2_has_no_four_sentence_representation_ceiling(self):
        s=source('John 3 says God loves. '+('An intervening sentence supplies context. '*8)+'This means God cares.')
        r=design.represent(s,'G2',dict(left=span(s,'God loves'),right=span(s,'This means God cares')))
        self.assertEqual(r['status'],'represented')
        self.assertEqual(r['relation_frame']['text'],s['text'][r['relation_frame']['start']:r['relation_frame']['end']])

    def test_long_G3_pair_keeps_exact_utterance_as_act_target(self):
        s=source('A convicted felon arrived. '+('An intervening narrative sentence. '*36)+'Promise me that you will help others.')
        r=design.represent(s,'G3',dict(circumstance=span(s,'convicted felon'),utterance=span(s,'Promise me that you will help others.')))
        self.assertEqual(r['status'],'represented')
        self.assertEqual(r['act_target']['text'],'Promise me that you will help others.')
        self.assertIn('convicted felon',r['binding_target']['text'])

    def test_named_nonbiblical_attribution_survives_beyond_250_chars(self):
        s=source('In Desire of Ages we read. '+('The surrounding source material remains intact. '*8)+'Seven times she heard. This means repeated help.')
        r=design.represent(s,'G2',dict(left=span(s,'Seven times she heard'),right=span(s,'This means repeated help')))
        self.assertEqual(r['admission'],'quarantine_nonbiblical_source_signal')
        self.assertIn('Desire of Ages',r['relation_frame']['text'])
        self.assertIsNone(r['attribution']['source_voice'])

    def test_common_names_and_job_are_not_biblical_citations(self):
        s=source('Mark helped John apply for a job. He explained the work.')
        self.assertIsNone(design.attribution_before(s,len(s['text'])))

    def test_narration_positive_is_retained_as_error_and_not_exported(self):
        s=source('You are forgiven. And I encouraged him and we prayed together.')
        r=design.represent(s,'G3',dict(circumstance=None,utterance=span(s,'And I encouraged him and we prayed together.')))
        merged=design.combine_address_phases(r,dict(utterance=r['endpoints']['utterance'],target=r['act_target'],decisions={'reassurance':'observed'}),dict(utterance=r['endpoints']['utterance'],target=r['binding_target'],decisions={'recipient_circumstance_binding':'not_bound'}))
        self.assertEqual(merged['positive_facts'],{})
        self.assertTrue(merged['integrity_finding'])
        self.assertEqual(merged['raw_act_decisions']['reassurance'],'observed')

    def test_binding_phase_cannot_supply_act(self):
        s=source('If you grieve, call a friend.')
        r=design.represent(s,'G3',dict(circumstance=span(s,'you grieve'),utterance=span(s,'call a friend.')))
        with self.assertRaisesRegex(ValueError,'cannot introduce'):
            design.combine_address_phases(r,dict(utterance=r['endpoints']['utterance'],target=r['act_target'],decisions={'invitation':'unclear'}),dict(utterance=r['endpoints']['utterance'],target=r['binding_target'],decisions={'invitation':'observed'}))

    def test_G3_request_phases_keep_canonical_questions_and_source_coordinates(self):
        s=source('If you grieve, call a friend.')
        r=design.represent(s,'G3',dict(circumstance=span(s,'you grieve'),utterance=span(s,'call a friend.')))
        a,b=design.request_shapes(r)
        self.assertEqual(a['questions'],{k:v for k,v in g3.questions().items() if k!='binding'})
        self.assertEqual(b['questions'],g3v2.questions())
        self.assertEqual(a['state']['target_text'],'call a friend.')
        self.assertIsNone(a['state']['candidate']['circumstance'])
        for role in b['state']['candidate'].values():
            self.assertEqual(b['state']['target_text'][role['start']:role['end']],role['text'])

    def test_excessive_attribution_frame_is_deferred(self):
        s=source('John 3 says God loves. '+('Context sentence. '*30)+'This means God cares.')
        policy=dict(design.POLICY,max_frame_chars=50)
        r=design.represent(s,'G2',dict(left=span(s,'God loves'),right=span(s,'This means God cares')),policy)
        self.assertEqual(r['reason'],'attribution_or_relation_exceeds_frame_bound')

    def test_discovery_growth_is_bounded_and_labels_cannot_affect_it(self):
        s=source(('John 3 says love. This means care for you. If you grieve, call a friend. '*8))
        a=design.discover(s)
        b=design.discover(dict(s,frozen_reference_ids=['invented'],expected={'explains_text':'linked'}))
        self.assertEqual(a,b)
        self.assertLessEqual(len(a['candidates']),a['budget_proof']['linear_candidate_bound'])
        with self.assertRaisesRegex(ValueError,'bound exceeded'):
            design.discover(s,dict(design.POLICY,source_candidate_ceiling=1))

    def test_unexpanded_clause_fanout_is_explicit(self):
        s=source('John 3 says one, two, three, four, five, six, seven, eight, nine, ten, eleven, twelve.')
        nodes,deferred=design.source_nodes(s,dict(design.POLICY,max_clause_children=2))
        self.assertEqual(len(nodes),1)
        self.assertEqual(deferred[0]['reason'],'clause_fanout_requires_review')

    def test_cli_has_no_paid_execution_path(self):
        packet=dict(candidate_count=20,bound=30)
        with patch.object(design,'build_packet',return_value=packet),patch.object(design,'write_packet'),patch.object(design.v2,'execute',side_effect=AssertionError('No provider run')):
            result=CliRunner().invoke(app,['analysis','evidence-supply-collector-design','--prepare-only'])
        self.assertEqual(result.exit_code,0,result.output)
        self.assertIn('provider_requests=0',result.output)
        refused=CliRunner().invoke(app,['analysis','evidence-supply-collector-design','--execute'])
        self.assertNotEqual(refused.exit_code,0)

    def test_accepted_V2_gate_blocks_old_paid_command(self):
        with patch.object(design.v2,'execute',side_effect=AssertionError('Closed gate must stop execution')):
            result=CliRunner().invoke(app,['analysis','evidence-supply-review','--revision','v2','--execute','--approve-paid-packet','old-packet'])
        self.assertNotEqual(result.exit_code,0)
        self.assertIn('closed FAIL',result.output)


if __name__=='__main__':
    unittest.main()
