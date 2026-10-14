from __future__ import annotations

from copy import deepcopy
from decimal import Decimal
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from typer.testing import CliRunner
from pastor_transcript_extractor.cli import app
from pastor_transcript_extractor import evidence_supply_revision as supply


def source(text):
    return dict(video_id=999,text=text,main_span={'start':0,'end':len(text)})


def small_run():
    candidates,_=supply.discover(source('Salvation is our topic today. Romans says love your neighbor. This means we care for other people. If you are grieving, call a friend.'))
    candidates=candidates[:2]
    requests=supply.request_inputs(candidates)
    packet=dict(content_fingerprint='test-approved-exact-packet',request_manifest=[dict(request_key=r['request_key'],state_fingerprint=supply.fp(r['state']),questions_fingerprint=supply.fp(r['questions'])) for r in requests],
                budget=dict(maximum_attempts=len(requests),maximum_input_tokens=len(requests)*supply.CONTEXT_TOKENS,maximum_list_price_usd=str(len(requests)*supply.CONTEXT_TOKENS*supply.PRICE)),
                candidate_manifest=[{k:v for k,v in c.items() if k not in ('target','leading_context','trailing_context','phrase_pools','local_claim')}|{'target_start':c['target']['start'],'target_end':c['target']['end']} for c in candidates],funnel=[])
    return packet,requests


class FakeProvider:
    instances=0
    attempts=0
    malformed=False

    def __init__(self):
        type(self).instances+=1

    def assess(self,request):
        type(self).attempts+=1
        if type(self).malformed:return {'status_code':200,'body':'not-json'}
        answers={}
        for key,q in request['questions'].items():
            chosen=next(iter(q['criteria']))
            answers[key]=dict(type='choice',choice=chosen,confidence=1.0,probabilities={option:float(option==chosen) for option in q['criteria']})
        return dict(status_code=200,request_id='mock-only',body=json.dumps(dict(model=supply.MODEL,answers=answers,usage={'input_tokens':500,'output_tokens':100})))

    def close(self):
        pass


class EvidenceSupplyRevisionTests(unittest.TestCase):
    def setUp(self):
        FakeProvider.instances=FakeProvider.attempts=0;FakeProvider.malformed=False

    def test_late_source_is_retained_and_g1_fits_frozen_limits(self):
        text=' '.join(f'Romans chapter {i} says love your neighbor. This means care for others.' for i in range(18))+' While Mary was a sinner, pardoned, and she knew it, she was grateful.'
        candidates,diagnostic=supply.discover(source(text))
        self.assertEqual(0,diagnostic['global_truncation'])
        self.assertFalse(diagnostic['unrepresentable'])
        g1=[c for c in candidates if c['capability']=='G1']
        self.assertTrue(any('pardoned' in c['claim']['text'] for c in g1))
        self.assertTrue(any('pardoned' in s['text'] for c in g1 for s in c['phrase_pools']['objects'].values()))
        self.assertGreater(len([c for c in candidates if c['capability']=='G2']),8)
        self.assertTrue(any(c.get('right',{}).get('end')==len(text) for c in candidates if c['capability']=='G2'))

    def test_caption_line_break_does_not_split_sentence(self):
        nodes=supply.sentences(source('The field\ncontains the treasure. Right? This means the\nword of God.'))
        self.assertEqual(2,len(nodes))
        self.assertIn('field\ncontains',nodes[0]['text'])
        self.assertIn('means the\nword',nodes[1]['text'])

    def test_question_binding_is_reversible_without_semantic_changes(self):
        from pastor_transcript_extractor.sermon_g3_feasibility_revision import questions
        for q in questions().values():
            bound=supply.bind_address_question(q,2)
            original=json.dumps(bound).replace('candidates[2].','candidate.')
            self.assertEqual(q,json.loads(original))

    def test_requests_have_only_frozen_g2_fields_and_scoped_g3_candidates(self):
        from pastor_transcript_extractor.sermon_g2_feasibility_revision import questions
        candidates,_=supply.discover(source('Romans says love your neighbor. This means care for others. When you are grieving, call a friend. If you are afraid, ask for help.'))
        requests=supply.request_inputs(candidates)
        for r in requests:
            self.assertEqual(r['request_key'],supply.fp({k:v for k,v in r.items() if k!='request_key'}))
            if r['capability']=='G2':
                self.assertLessEqual(len(r['candidate_ids']),8)
                for key,q in r['questions'].items():
                    pos=int(key.split('_')[0][1:]);self.assertEqual(questions(pos)[key],q)
                    self.assertIn(key.split('_',1)[1],{'explains_text','adoption','boundary','left_voice','right_voice'})
            if r['capability']=='G3':
                self.assertLessEqual(len(r['candidate_ids']),3)
                self.assertEqual(len(r['state']['candidates']),len(r['candidate_ids']))

    def test_spatial_overlap_cannot_match_wrong_directed_endpoints(self):
        text='Romans says weep. This means sharing grief.'
        a=supply.span(text,0,16);b=supply.span(text,17,len(text))
        check=dict(kind='directed_edge',left=a,right=b)
        self.assertTrue(supply.matching(check,dict(left=a,right=b)))
        self.assertFalse(supply.matching(check,dict(left=b,right=a)))
        self.assertFalse(supply.matching(check,dict(target=supply.span(text,0,len(text)))))

    def test_approval_and_budget_fail_before_provider_construction(self):
        p,requests=small_run()
        with tempfile.TemporaryDirectory() as directory,patch.object(supply,'validate_packet'):
            with self.assertRaisesRegex(ValueError,'exact --approve-paid-packet'):
                supply.execute(p,requests,approval_key='wrong',output_dir=directory,provider_factory=FakeProvider)
            p['budget']['maximum_list_price_usd']='0'
            with self.assertRaisesRegex(ValueError,'Spending ceiling'):
                supply.execute(p,requests,approval_key=p['content_fingerprint'],output_dir=directory,provider_factory=FakeProvider)
        self.assertEqual(0,FakeProvider.instances)

    def test_request_mutation_fails_before_provider_construction(self):
        p,requests=small_run();requests[0]['state']['target_text']='changed'
        with tempfile.TemporaryDirectory() as directory,patch.object(supply,'validate_packet'):
            with self.assertRaisesRegex(ValueError,'Changed request'):
                supply.execute(p,requests,approval_key=p['content_fingerprint'],output_dir=directory,provider_factory=FakeProvider)
        self.assertEqual(0,FakeProvider.instances)

    def test_saved_receipts_replay_without_provider_and_recover_valid_receipt(self):
        p,requests=small_run()
        with tempfile.TemporaryDirectory() as directory,patch.object(supply,'validate_packet'):
            report=supply.execute(p,requests,approval_key=p['content_fingerprint'],output_dir=directory,provider_factory=FakeProvider)
            self.assertEqual(len(requests),FakeProvider.attempts)
            self.assertTrue(all(o['pastor_credit'] is False and o['quality_score'] is None for o in report['observations']))
            # Simulate interruption after receipt persistence but before ledger update.
            path=Path(directory)/'request-ledger.json';ledger=json.loads(path.read_text());ledger['attempts'][0]['status']='attempted'
            supply.dump(path,supply._seal({k:v for k,v in ledger.items() if k!='fingerprint'}))
            supply.execute(p,requests,approval_key=p['content_fingerprint'],output_dir=directory,provider_factory=lambda: self.fail('Provider constructed on replay'))
            self.assertEqual('validated_saved_raw_receipt_no_new_attempt',json.loads(path.read_text())['attempts'][0]['recovery'])

    def test_malformed_raw_receipt_is_preserved_and_cannot_retry(self):
        p,requests=small_run();FakeProvider.malformed=True
        with tempfile.TemporaryDirectory() as directory,patch.object(supply,'validate_packet'):
            with self.assertRaises(ValueError):
                supply.execute(p,requests,approval_key=p['content_fingerprint'],output_dir=directory,provider_factory=FakeProvider)
            receipt=Path(directory)/'receipts'/f"{requests[0]['request_key']}.json"
            self.assertEqual('not-json',json.loads(receipt.read_text())['response']['body'])
            ledger=json.loads((Path(directory)/'request-ledger.json').read_text())
            self.assertEqual(supply.CONTEXT_TOKENS,ledger['attempts'][0]['reserved_input_tokens'])
            with self.assertRaises(ValueError):
                supply.execute(p,requests,approval_key=p['content_fingerprint'],output_dir=directory,provider_factory=lambda: self.fail('Automatic retry'))
        self.assertEqual(1,FakeProvider.attempts)

    def test_alias_error_cannot_be_hidden_by_matching_alias(self):
        p={'candidate_manifest':[], 'funnel':[dict(check_id='C1',reference_id='R1',capability='G2',opportunity='negative_control',matching_candidate_ids=['a','b'],expected={'explains_text':['not_linked']})], 'content_fingerprint':'test'}
        def a(choice):return dict(choice=choice,probabilities={choice:1.0},confidence=1.0)
        rows=[dict(request_key='r1',capability='G2',candidate_ids=['a'],raw_answers={'p0_explains_text':a('not_linked')},usage={'input_tokens':1,'output_tokens':1}),dict(request_key='r2',capability='G2',candidate_ids=['b'],raw_answers={'p0_explains_text':a('linked')},usage={'input_tokens':1,'output_tokens':1})]
        r=supply.interpret(p,rows)
        self.assertEqual('critical_integrity_failure',r['reference_checks'][0]['status'])
        self.assertIsNone(r['cost_per_usable_item'])

    def test_cli_cannot_execute_without_separate_exact_approval(self):
        result=CliRunner().invoke(app,['analysis','evidence-supply-review','--revision','v2','--execute'])
        self.assertNotEqual(0,result.exit_code)
        self.assertIn('separately approve',result.output)
        result=CliRunner().invoke(app,['analysis','evidence-supply-review','--revision','v2','--check-only','--approve-paid-packet','x'])
        self.assertNotEqual(0,result.exit_code)
        self.assertIn('requires --execute',result.output)


if __name__=='__main__':unittest.main()
