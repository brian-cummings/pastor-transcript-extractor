from copy import deepcopy
from pathlib import Path
import json
import unittest
from unittest.mock import patch
from typer.testing import CliRunner
from pastor_transcript_extractor import minute_evidence_context as c
from pastor_transcript_extractor import minute_evidence_nomination as n
from pastor_transcript_extractor.collector_retrieval_json_v1_1 import seal
from pastor_transcript_extractor.caption_normalization import normalize_caption_fragments
from pastor_transcript_extractor.sermon_classification import build_transcript_blocks
from pastor_transcript_extractor.segmentation import SegmentDraft
import hashlib


def fixture(texts=None):
    texts=texts or ['Earlier report.','If you ask, come in.','Later context.']
    segments=[dict(start_seconds=i*60,end_seconds=i*60+30,text=text,speaker_hint=None,label='sermon',confidence=None) for i,text in enumerate(texts)]
    norm=normalize_caption_fragments(enumerate(texts));units=[];cursor=0
    for i,u in enumerate(norm.units):
        a=cursor;b=a+len(u.text);indexes=list(u.source_segment_indexes)
        units.append(dict(unit_id=str(i),start=a,end=b,text=u.text,source_segment_indexes=indexes,
            start_seconds=min(segments[k]['start_seconds'] for k in indexes),end_seconds=max(segments[k]['end_seconds'] for k in indexes)));cursor=b+1
    source=seal(dict(text=norm.text,units=units,main_span=dict(start=0,end=len(norm.text)),normalization_diagnostics=norm.diagnostics,
                     normalized_text_sha256=hashlib.sha256(norm.text.encode()).hexdigest()))
    proof=c.validate_source(source,segments)
    drafts=[SegmentDraft(s['start_seconds'],s['end_seconds'],s['text'],None,'sermon',None) for s in segments]
    blocks=build_transcript_blocks(drafts,target_seconds=60,max_chars=3200,normalize_rolling_captions=True)
    block=blocks[min(1,len(blocks)-1)];anchor=c.map_anchor(source,block,set(range(len(segments))),proof);context=c.plan_context(source,anchor)
    return source,proof,blocks,anchor,context


def span(source,text,start=0):
    a=source['text'].index(text,start);return dict(start=a,end=a+len(text),text=text)


def output(binding,roles,dependencies=None,hypotheses=None):
    return dict(request_fingerprint=binding['content_fingerprint'],status='proposed',nominations=[dict(roles=roles,dependencies=dependencies or [],provenance_hypotheses=hypotheses or [],sufficiency='unknown')])


class MappingTests(unittest.TestCase):
    def test_exact_mapping_and_canonical_roundtrip(self):
        source,proof,blocks,anchor,context=fixture()
        self.assertEqual('mapped',anchor['status']);self.assertEqual(blocks[1].text,anchor['center_ranges'][0]['text'])
        self.assertEqual(source['text'][context['start']:context['end']],context['text']);self.assertFalse(context['complete_context_established'])

    def test_repeated_text_uses_unit_identity_not_first_match(self):
        source,proof,blocks,anchor,context=fixture(['These repeated words are longer than eight distinct source tokens here.','Other message.','These repeated words are longer than eight distinct source tokens here.'])
        last=c.map_anchor(source,blocks[-1],{0,1,2},proof)
        self.assertEqual(source['text'].rindex('These repeated words are longer than eight distinct source tokens here.'),last['center_ranges'][0]['start'])

    def test_partial_retained_membership_and_normalization_mismatch_defer(self):
        source,proof,blocks,anchor,context=fixture()
        self.assertEqual('deferred',c.map_anchor(source,blocks[1],{0,2},proof)['status'])
        from dataclasses import replace
        wrong=replace(blocks[1],text=blocks[1].text.upper())
        self.assertEqual('block_text_not_exact_canonical_slice',c.map_anchor(source,wrong,{0,1,2},proof)['reason'])
        changed=deepcopy(source);changed['text']+='!'
        with self.assertRaises(ValueError):c.validate_source(changed,[])

    def test_oversized_anchor_and_context_budget_no_anchor_truncation(self):
        source,proof,blocks,anchor,context=fixture(['X'*6100])
        self.assertEqual('complete_anchor_exceeds_6000',context['reason'])
        source,proof,blocks,anchor,context=fixture(['A '*1800,'Center message.','B '*1800])
        self.assertLessEqual(len(context['text']),6000);self.assertTrue(context['budget_clipped'])
        self.assertTrue(context['start']<=anchor['center_ranges'][0]['start']<anchor['center_ranges'][0]['end']<=context['end'])

    def test_timestamp_and_partial_unit_lineage_cannot_gain_mapping(self):
        source,proof,blocks,anchor,context=fixture()
        from dataclasses import replace
        self.assertEqual('block_timestamp_lineage_differs',c.map_anchor(source,replace(blocks[1],start_seconds=61),{0,1,2},proof)['reason'])
        with self.assertRaisesRegex(ValueError,'Foreign'):c.map_anchor(source,blocks[1],{0,1,2},seal(dict(source_fingerprint='foreign')))


class NominationTests(unittest.TestCase):
    def setUp(self):
        self.source,self.proof,self.blocks,self.anchor,self.context=fixture()
        self.binding=n.identity(self.proof,self.anchor,self.context,'G3')
        self.roles=dict(left=None,right=None,utterance=span(self.source,'If you ask, come in.'))

    def test_supported_geometry_remains_untrusted_and_mapping_strips_hypotheses(self):
        hypotheses=[dict(dimension='voice',value='reported',support=span(self.source,'Earlier report.'))]
        records=n.validate_output(output(self.binding,self.roles,hypotheses=hypotheses),self.binding,self.anchor,self.context)
        self.assertFalse(records[0]['usable_evidence']);mapped=n.measurement_mapping(records[0])
        self.assertIsNone(mapped['measurement_authority']);self.assertFalse(mapped['extractor_hypotheses_forwarded']);self.assertNotIn('voice',mapped)
        self.assertEqual(self.roles,mapped['roles'])

    def test_context_only_target_is_rejected(self):
        roles=dict(left=None,right=None,utterance=span(self.source,'Earlier report.'))
        with self.assertRaisesRegex(ValueError,'Context-only'):n.validate_output(output(self.binding,roles),self.binding,self.anchor,self.context)

    def test_declared_required_condition_cannot_be_outside_target(self):
        roles=dict(left=None,right=None,utterance=span(self.source,'come in.'))
        with self.assertRaisesRegex(ValueError,'required content'):n.validate_output(output(self.binding,roles,[span(self.source,'If you ask')]),self.binding,self.anchor,self.context)
        # Undeclared omitted qualifiers cannot be detected by literal code.
        records=n.validate_output(output(self.binding,roles),self.binding,self.anchor,self.context)
        self.assertFalse(records[0]['usable_evidence'])

    def test_strict_coordinates_roles_fields_foreign_source_and_ceiling(self):
        for changes in (dict(start=True),dict(end=99999),dict(text='paraphrase')):
            roles=deepcopy(self.roles);roles['utterance'].update(changes)
            with self.assertRaises(ValueError):n.validate_output(output(self.binding,roles),self.binding,self.anchor,self.context)
        value=output(self.binding,self.roles);value['nominations']*=5
        with self.assertRaisesRegex(ValueError,'four'):n.validate_output(value,self.binding,self.anchor,self.context)
        value=output(self.binding,self.roles);value['positive_facts']=[]
        with self.assertRaisesRegex(ValueError,'fields'):n.validate_output(value,self.binding,self.anchor,self.context)
        value=output(self.binding,self.roles);value['request_fingerprint']='foreign'
        with self.assertRaisesRegex(ValueError,'Foreign'):n.validate_output(value,self.binding,self.anchor,self.context)

    def test_directed_G2_cross_block_pair_and_overlap(self):
        binding=n.identity(self.proof,self.anchor,self.context,'G2')
        roles=dict(left=span(self.source,'Earlier report.'),right=span(self.source,'If you ask, come in.'),utterance=None)
        records=n.validate_output(output(binding,roles),binding,self.anchor,self.context)
        self.assertEqual(roles,records[0]['roles'])
        roles['right']=roles['left']
        with self.assertRaisesRegex(ValueError,'Overlapping'):n.validate_output(output(binding,roles),binding,self.anchor,self.context)

    def test_dedup_preserves_reported_current_conflict_and_order_independent_owner(self):
        records=[]
        for voice in ('reported','current_preacher'):
            records+=n.validate_output(output(self.binding,self.roles,hypotheses=[dict(dimension='voice',value=voice,support=self.roles['utterance'])]),self.binding,self.anchor,self.context)
        group=n.deduplicate(records+records)[0]
        self.assertEqual(2,len(group['origins']));self.assertTrue(group['provenance_conflict']);self.assertFalse(group['usable_evidence'])
        self.assertEqual([group],n.deduplicate(list(reversed(records))))

    def test_identity_changes_for_model_question_context_routing_and_source(self):
        baseline=self.binding['content_fingerprint']
        for kwargs in (dict(provider_lock=dict(model='different',digest='different')),dict(question_version='different'),dict(routing_identity='different')):
            self.assertNotEqual(baseline,n.identity(self.proof,self.anchor,self.context,'G3',**kwargs)['content_fingerprint'])
        changed=seal({**self.context,'has_later_source':not self.context['has_later_source']})
        self.assertNotEqual(baseline,n.identity(self.proof,self.anchor,changed,'G3')['content_fingerprint'])
        self.assertFalse(self.binding['cache_reuse_authorized']);self.assertFalse(self.binding['provider_request_prepared'])

    def test_unknown_provenance_must_remain_unknown_without_support(self):
        for voice in ('reported','preacher'):
            with self.assertRaisesRegex(ValueError,'Unsupported'):n.validate_output(output(self.binding,self.roles,hypotheses=[dict(dimension='voice',value=voice,support=None)]),self.binding,self.anchor,self.context)
        self.assertEqual(1,len(n.validate_output(output(self.binding,self.roles,hypotheses=[dict(dimension='voice',value='unknown',support=None)]),self.binding,self.anchor,self.context)))


class CliTests(unittest.TestCase):
    def test_preparation_and_check_do_not_add_execution_modes(self):
        from pastor_transcript_extractor.cli import app
        from pastor_transcript_extractor import minute_evidence_preparation as p
        result=dict(status='PREPARED_NO_INFERENCE_AUTHORIZED',content_fingerprint='synthetic',counts={})
        with patch.object(p,'prepare',return_value=(result,Path('/tmp/synthetic'))):
            r=CliRunner().invoke(app,['analysis','structure-readiness','--prepare-handoff'])
            self.assertEqual(0,r.exit_code,r.output);self.assertIn('provider_requests=0',r.output)
        r=CliRunner().invoke(app,['analysis','structure-readiness','--prepare-handoff','--check-handoff'])
        self.assertEqual(2,r.exit_code)
