from copy import deepcopy
from pathlib import Path
import unittest
from unittest.mock import patch
from typer.testing import CliRunner
from pastor_transcript_extractor import typesafe_window_bridge as b
from pastor_transcript_extractor import minute_evidence_context as c
from pastor_transcript_extractor.collector_retrieval_json_v1_1 import seal
from tests.test_minute_evidence_implementation import fixture


def answers(request,choices=None,default='unknown'):
    result={}
    for key,q in request['questions'].items():
        chosen=(choices or {}).get(key,default)
        result[key]=dict(choice=chosen,probabilities={option:float(option==chosen) for option in q['criteria']})
    return result


def mapped_fixture(main_start=0):
    source,proof,blocks,anchor,context=fixture()
    source=seal({**source,'video_id':1,'main_span':dict(start=main_start,end=len(source['text']))})
    proof=seal({**proof,'source_fingerprint':source['content_fingerprint']})
    anchor=c.map_anchor(source,blocks[1],{0,1,2},proof);context=c.plan_context(source,anchor)
    return source,proof,anchor,context


def nominee():
    source,proof,anchor,context=mapped_fixture();request=b.prepare_selection(context,anchor,['G3'])
    s=anchor['center_ranges'][0]
    raw=answers(request,dict(G3_utterance_start='p'+str(s['start']),G3_utterance_end='p'+str(s['end'])))
    records,deferred=b.decode_points(request,raw,context,anchor,proof)
    return source,records[0],request,raw


class WindowBridgeTests(unittest.TestCase):
    def test_direct_short_window_needs_no_second_pass(self):
        _,_,anchor,context=mapped_fixture();request=b.prepare_selection(context,anchor,['G3','G2'])
        self.assertEqual('direct_points',request['phase']);self.assertEqual(6,len(request['questions']))
        self.assertTrue(all(q['type']=='choice' for q in request['questions'].values()))
        with self.assertRaisesRegex(ValueError,'no refinement'):b.refine(request,{})
        self.assertNotIn('case_id',request['state']);self.assertNotIn('expected',request['state'])

    def test_every_character_boundary_is_addressable_with_255_option_limit(self):
        source,proof,blocks,anchor,context=fixture(['x'*6000]);request=b.prepare_selection(context,anchor,['G3'])
        self.assertEqual('boundary_pages',request['phase']);points=set()
        for page in request['state']['boundary_pages']:points.update(range(page['first'],page['last']+1))
        self.assertEqual(set(range(context['start'],context['end']+1)),points)
        self.assertEqual(24,len(request['state']['boundary_pages']))
        raw=answers(request,{k:'b23' for k in request['questions']});refined,deferred=b.refine(request,raw)
        self.assertEqual([],deferred);self.assertTrue(all(len(q['criteria'])<=255 for q in refined['questions'].values()))
        self.assertEqual(request['state'],refined['state'])

    def test_withholding_short_circuits_without_presence_question_or_retry(self):
        source,proof,blocks,anchor,context=fixture(['x'*1000]);request=b.prepare_selection(context,anchor,['G3','G2'])
        result,deferred=b.refine(request,answers(request,default='needs_context'))
        self.assertIsNone(result);self.assertEqual(['G2','G3'],deferred)

    def test_point_decode_produces_only_literal_untrusted_nominee(self):
        source,record,request,raw=nominee()
        self.assertFalse(record['usable_evidence']);self.assertEqual('If you ask, come in.',record['roles']['utterance']['text'])
        self.assertEqual([],record['raw_hypotheses']['provenance_hypotheses'])

    def test_bad_order_and_context_only_points_defer_without_repair(self):
        source,proof,anchor,context=mapped_fixture();request=b.prepare_selection(context,anchor,['G3'])
        for start,end in ((10,1),(0,3)):
            raw=answers(request,dict(G3_utterance_start=f'p{start}',G3_utterance_end=f'p{end}'))
            records,deferred=b.decode_points(request,raw,context,anchor,proof)
            self.assertEqual([],records);self.assertIn('G3',deferred)

    def test_corrupt_probabilities_and_foreign_context_rejected(self):
        source,proof,anchor,context=mapped_fixture();request=b.prepare_selection(context,anchor,['G3']);raw=answers(request)
        raw['G3_utterance_start']['probabilities']['unknown']=.5
        with self.assertRaises(ValueError):b.decode_points(request,raw,context,anchor,proof)
        changed=seal({**context,'source_fingerprint':'foreign'})
        with self.assertRaises(ValueError):b.prepare_selection(changed,anchor,['G3'])

    def test_exact_cache_reuse_avoids_call_and_partial_reuse_only_requests_missing(self):
        _,_,request,raw=nominee();cache={}
        for key in request['questions']:
            leaf=b.cached_leaf(request,key,raw[key],dict(receipt='synthetic'))
            cache[leaf['leaf_key']]=leaf
        result=b.dispatch_plan(request,cache);self.assertEqual(0,result['requests_needed']);self.assertEqual({},result['missing_questions'])
        cache.pop(next(iter(cache)));result=b.dispatch_plan(request,cache)
        self.assertEqual(1,result['requests_needed']);self.assertEqual(1,len(result['missing_questions']))

    def test_cache_does_not_alias_changed_model_state_question_phase_or_scope(self):
        _,_,request,raw=nominee();key=next(iter(request['questions']));old=b.leaf_key(request,key)
        for field,value in (('model','different'),('phase','different'),('version','different')):
            changed=seal({**request,field:value});self.assertNotEqual(old,b.leaf_key(changed,key))
        for field in ('state','scope','questions'):
            changed=deepcopy(request)
            if field=='questions':changed[field][key]['instructions']['task']='different'
            else:changed[field]['changed']='different'
            self.assertNotEqual(old,b.leaf_key(seal(changed),key))

    def test_corrupt_cache_leaf_does_not_trigger_automatic_refill(self):
        _,_,request,raw=nominee();key=next(iter(request['questions']));leaf=b.cached_leaf(request,key,raw[key],dict(receipt='synthetic'))
        leaf['model']='different'
        with self.assertRaisesRegex(ValueError,'corrupt'):b.dispatch_plan(request,{b.leaf_key(request,key):leaf})

    def test_existing_G3_measurement_questions_reused_and_binding_phase_unrequested(self):
        source,record,request,raw=nominee();result=b.measurement_intents(record,source)
        self.assertEqual('PROSPECTIVE_MEASUREMENT_ONLY',result['status']);self.assertEqual(1,len(result['requests']))
        actual=result['requests'][0]
        from pastor_transcript_extractor import sermon_g3_feasibility_review as g3
        self.assertEqual({k:v for k,v in g3.questions().items() if k!='binding'},actual['questions'])
        self.assertEqual('unmeasured',result['relation_fields']);self.assertFalse(result['consumer_adapter_authorized'])
        self.assertFalse(actual['execution_authorized']);self.assertIsNone(actual['admission_authority'])

    def test_out_of_measurement_scope_context_is_blocked_without_silent_clipping(self):
        source,proof,anchor,context=mapped_fixture(main_start=16);request=b.prepare_selection(context,anchor,['G3']);s=anchor['center_ranges'][0]
        raw=answers(request,dict(G3_utterance_start=f"p{s['start']}",G3_utterance_end=f"p{s['end']}"))
        records,_=b.decode_points(request,raw,context,anchor,proof);result=b.measurement_intents(records[0],source)
        self.assertEqual('BLOCKED_MATERIALIZATION_SCOPE',result['status']);self.assertEqual([],result['requests'])

    def test_cli_is_provider_free_and_conflicting_modes_rejected(self):
        from pastor_transcript_extractor.cli import app
        from pastor_transcript_extractor import typesafe_window_review as r
        result=dict(status='provider_free',content_fingerprint='synthetic',usage_bounds={})
        with patch.object(r,'prepare',return_value=(result,Path('/tmp/synthetic'))):
            response=CliRunner().invoke(app,['analysis','structure-readiness','--typesafe-windows'])
            self.assertEqual(0,response.exit_code,response.output);self.assertIn('provider_requests=0',response.output)
        response=CliRunner().invoke(app,['analysis','structure-readiness','--typesafe-windows','--prepare-handoff'])
        self.assertEqual(2,response.exit_code)
