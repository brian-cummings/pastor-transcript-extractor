import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pastor_transcript_extractor import typesafe_selection_resume as r
from pastor_transcript_extractor import typesafe_selection_execution as e
from pastor_transcript_extractor import typesafe_window_bridge as b
from pastor_transcript_extractor import typesafe_selection_packet as p
from pastor_transcript_extractor.collector_retrieval_json_v1_1 import seal
from tests.test_typesafe_window_bridge import mapped_fixture,answers


class ResumeTests(unittest.TestCase):
    def fixture(self,out,maximum=2):
        _,proof,anchor,context=mapped_fixture()
        first=b.prepare_selection(context,anchor,['G3'])
        second=seal({**first,'metadata':{**first['metadata'],'synthetic_ordinal':2}})
        rows=[dict(request=x,first_dispatch=b.dispatch_plan(x,{}),diagnostic_slots=['test']) for x in (first,second)]
        packet=seal(dict(requests=rows,endpoint='https://example.invalid',structural_deferrals=[],bounds=dict(
            provider_requests_max=maximum,run_seconds_max=1800,request_timeout_seconds=45,reserved_total_input_tokens=2*p.TOKENS_PER_REQUEST)))
        selected=dict(sources={'1':dict(proof=proof)},contexts={context['content_fingerprint']:context},cases=[
            dict(context_fingerprint=context['content_fingerprint'],anchor=anchor,preparation_binding=dict(source_proof=proof['content_fingerprint']))])
        choices={'G3_utterance_start':f"p{anchor['center_ranges'][0]['start']}",'G3_utterance_end':f"p{anchor['center_ranges'][0]['end']}"}
        raw=dict(model=p.MODEL,usage=dict(input_tokens=10,output_tokens=2),answers={k:dict(type='choice',**v) for k,v in answers(first,choices).items()})
        response=dict(status=200,body_utf8=json.dumps(raw))
        e.write_once(out/'01-reservation.json',dict(input_fingerprint=packet['content_fingerprint'],request_fingerprint=first['content_fingerprint'],wire=p.wire(first),reserved_input_tokens=p.TOKENS_PER_REQUEST))
        e.write_once(out/'01-response.json',dict(request_fingerprint=first['content_fingerprint'],raw=response))
        cache={}
        for key,answer in raw['answers'].items():
            leaf=b.cached_leaf(first,key,answer,dict(input_fingerprint=packet['content_fingerprint'],receipt='01-response.json'));cache[leaf['leaf_key']]=leaf
        e.write_once(out/'01-leaves.json',dict(leaves=cache))
        return packet,selected,response

    def test_reuses_paid_prefix_and_only_sends_unsent_tail(self):
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp);packet,selected,response=self.fixture(out)
            old={x.name:x.read_bytes() for x in out.iterdir()};sends=[]
            def transport(*args):sends.append(args);return response
            result,_=r.continue_rows(packet,selected,out,1,transport=transport,clock=lambda:0)
            self.assertEqual(1,len(sends));self.assertEqual(2,result['provider_requests'])
            self.assertEqual(1,result['replayed_provider_responses']);self.assertEqual(1,result['new_provider_requests'])
            self.assertEqual(2,sum(len(x['nominations']) for x in result['rows']))
            for name,data in old.items():self.assertEqual(data,(out/name).read_bytes())

    def test_mismatched_old_wire_never_calls_transport(self):
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp);packet,selected,_=self.fixture(out)
            path=out/'01-reservation.json';value=json.loads(path.read_text());value['wire']['model']='wrong';path.write_text(json.dumps(seal(value)))
            with self.assertRaisesRegex(ValueError,'never resubmit'):
                r.continue_rows(packet,selected,out,1,transport=lambda *a:self.fail('No paid retry'),clock=lambda:0)

    def test_original_total_ceiling_still_applies(self):
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp);packet,selected,_=self.fixture(out,maximum=1)
            with self.assertRaisesRegex(ValueError,'ceiling'):
                r.continue_rows(packet,selected,out,1,transport=lambda *a:self.fail('Over budget'),clock=lambda:0)

    def test_missing_or_foreign_proof_fails_before_decode(self):
        _,proof,anchor,_=mapped_fixture()
        row=dict(anchor=anchor,preparation_binding=dict(source_proof=proof['content_fingerprint']))
        self.assertEqual(proof,e.resolve_source_proof(dict(sources={'1':dict(proof=proof)}),row))
        with self.assertRaises(ValueError):e.resolve_source_proof(dict(sources={}),row)
