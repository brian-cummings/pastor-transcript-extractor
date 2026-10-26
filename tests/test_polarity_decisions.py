from copy import deepcopy
from dataclasses import asdict,replace
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from typer.testing import CliRunner

from pastor_transcript_extractor import polarity_decisions as p
from pastor_transcript_extractor import polarity_producer as adapter
from pastor_transcript_extractor.pastor_evidence import EvidencePolicy,ObservationEnvelope
from pastor_transcript_extractor.cli import app
from test_source_context import fixture,inspect


def inputs():
    window,_,valid=fixture();checked=inspect(valid,window)
    return window,checked['observations']


def response(spec,choice='affirmed',confidence=.99):
    return dict(model='jev-1.13.0',complete=True,usage=dict(input_tokens=100,output_tokens=100),
        output={key:dict(type='choice',choice=choice,probabilities={k:.97 if k==choice else .01 for k in p.CRITERIA},confidence=confidence)
            for key in spec.body['questions']})


class PolarityProducerTests(unittest.TestCase):
    def test_direct_producer_has_separate_provenance_and_never_inherits_admission(self):
        window,parents=inputs();original=deepcopy(parents);spec,index=p.request([window],parents)
        key=next(iter(index));parent=next(row for row in parents if row['id']==index[key]);answer=response(spec)
        result=p.derive(parent,window,spec,answer,key,receipt_ref='saved-receipt.json')
        self.assertEqual(parents,original);self.assertNotEqual(result['id'],parent['id'])
        ObservationEnvelope(result)
        self.assertEqual(result['field_judgments'],{});self.assertEqual(result['production_admission'],'not_admitted')
        self.assertEqual(EvidencePolicy().permits(result),(False,'missing_required_checks'))
        decision=result['producer']['polarity_decision']
        self.assertEqual(decision['parent_observation_id'],parent['id']);self.assertEqual(decision['decision_model'],'jev-1.13.0')
        self.assertEqual(decision['raw_response_ref'],'saved-receipt.json')
        self.assertEqual(result['raw_response_ref'],parent['raw_response_ref'])
        for field in parent['binding']:
            if field!='polarity': self.assertEqual(result['binding'][field],parent['binding'][field])

    def test_unsettled_is_not_insufficient_or_low_model_confidence(self):
        window,parents=inputs();spec,index=p.request([window],parents);key=next(iter(index));parent=next(x for x in parents if x['id']==index[key])
        for choice,confidence,expected in (('unsettled',.99,'unsettled'),('insufficient_evidence',.99,'unresolved'),('affirmed',.5,'unresolved')):
            value=p.derive(parent,window,spec,response(spec,choice,confidence),key,receipt_ref='receipt')
            self.assertEqual(value['binding']['polarity']['value'],expected)
            self.assertEqual(bool(value['binding']['polarity']['evidence']),expected!='unresolved')

    def test_request_blinding_order_invariance_and_source_mapping_guards(self):
        window,parents=inputs();spec,index=p.request([window],parents)
        self.assertEqual(p.request([window],list(reversed(parents))),(spec,index))
        for item in spec.body['state']['items']:
            self.assertEqual(set(item),{'source_id','proposition'});self.assertEqual(set(item['proposition']),{'span','reading'})
        key=next(iter(index));parent=next(x for x in parents if x['id']==index[key])
        wrong=replace(window,id='foreign')
        with self.assertRaises(ValueError): p.derive(parent,wrong,spec,response(spec),key,receipt_ref='receipt')
        with self.assertRaises(ValueError): p.request([wrong],parents)
        with self.assertRaises(ValueError): p.request([window],[])
        with self.assertRaises(ValueError): p.request([window],[parents[0],parents[0]])
        bad=replace(spec,body=deepcopy(spec.body));bad.body['questions'][key]['instructions']='Different question '+p.INSTRUCTION
        with self.assertRaises(ValueError): p.derive(parent,window,bad,response(bad),key,receipt_ref='receipt')

    def test_saved_receipt_replays_through_shared_producer_without_new_calls(self):
        window,parents=inputs();sent=[]
        def transport(spec): sent.append(spec);return response(spec)
        with TemporaryDirectory() as directory:
            store=p.requests.ReceiptStore(Path(directory));ledger=p.requests.BudgetLedger(max_attempts=1,max_usd='0.003')
            first=p.produce([window],parents,store,transport,ledger)
            second=p.produce([window],parents,store,lambda s:self.fail('exact receipt must be reused'),ledger)
            self.assertEqual(first,second);self.assertEqual(len(sent),1)
            self.assertTrue((store.root/'polarity-observations.json').exists())
            self.assertTrue(all(not EvidencePolicy().permits(row)[0] for row in first['observations']))

    def test_question_mapping_survives_serialized_order_after_q9(self):
        window,parents=inputs();base=parents[0];many=[]
        for i in range(12):
            row=deepcopy(base);row['binding']['binding_id']='synthetic-'+str(i)
            from pastor_transcript_extractor.pastor_evidence import observation_identity
            row['id']=observation_identity(row);many.append(row)
        spec,index=p.request([window],many)
        spec=p.requests.RequestSpec(**json.loads(p.requests.wire(asdict(spec))))
        parent=next(x for x in many if x['id']==index['q10'])
        self.assertEqual(p.derive(parent,window,spec,response(spec),'q10',receipt_ref='receipt')['binding']['polarity']['value'],'affirmed')

    def test_cli_tie_in_is_offline_and_exposes_decision_roadmap(self):
        self.assertTrue(any(row['stage']=='Canonical alignment and hierarchy' for row in adapter.DECISIONS))
        with patch.object(adapter,'materialize',return_value=dict(status='MATERIALIZED_EXPERIMENTAL_PENDING_VERIFICATION',paid_calls=0)) as materialize:
            result=CliRunner().invoke(app,['analysis','learning-demo','model-fit','polarity-producer-materialize','--base-dir','/tmp/pte-base','--json'])
            self.assertEqual(result.exit_code,0,result.output);materialize.assert_called_once()
