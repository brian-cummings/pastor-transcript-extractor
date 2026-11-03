from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from pastor_transcript_extractor import reviewed_b1_delivery as b1
from test_profile_analysis_support import plan
from test_profile_analysis_support_execution import wire


class B1DeliveryTests(unittest.TestCase):
    def setup_case(self,directory):
        base=Path(directory);path=base/'proposal.json';path.write_text('{}')
        key=b1.OID+':requested_response_present'
        spec=b1.support.requests.RequestSpec('source_verification',dict(model='jev-1.13.0',
            questions={key:b1.producer.presence_question(1)},state=dict(items=[None,dict(id=b1.OID)])),
            {},namespace='response-growth-reviewed-case-presence-v1',version='response-growth-reviewed-case-presence-v1')
        data=dict(spec=spec,p=dict(base_dir=str(base)),root=base/'evaluation'/b1.VERSION/'case')
        return path,data

    def presence(self,spec,probability):
        return b1.support.requests.WireResponse(200,json.dumps(dict(model='jev-1.13.0',
            usage=dict(input_tokens=100,output_tokens=0),
            answers={key:dict(type='noul',noul=probability) for key in spec.body['questions']})))

    def test_low_presence_and_lost_response_stop_without_support_or_retry(self):
        for lost in (False,True):
            with self.subTest(lost=lost),TemporaryDirectory() as directory:
                path,data=self.setup_case(directory);sent=[]
                def send(spec):
                    sent.append(spec)
                    if lost:raise OSError('lost')
                    return self.presence(spec,.89)
                with patch.object(b1,'load',return_value=data),patch.object(b1,'PRESENCE',data['spec'].fingerprint), \
                     patch.object(b1,'assemble',side_effect=AssertionError('No composition after failed gate')):
                    result=b1.run(path,b1.PROPOSAL,b1.OID,presence_transport=send,
                        support_transport=lambda s:self.fail('No support call'))
                    self.assertEqual(result,b1.run(path,b1.PROPOSAL,b1.OID,presence_transport=send))
                self.assertEqual(1,len(sent));self.assertEqual('STOPPED_PRESENCE',result['status'])
                self.assertEqual(1,result['paid_attempts']);self.assertNotIn('support',result['accounting'])

    def test_presence_pass_then_whole_statement_support_without_correction(self):
        for valid in (True,False):
            with self.subTest(valid=valid),TemporaryDirectory() as directory:
                path,data=self.setup_case(directory);p=deepcopy(plan());item=p['items'][0]
                item['claim_id']='section-dimension-requested_response-'+b1.OID
                item['case']['state']['candidate']['id']=item['claim_id']
                prior=deepcopy(item);prior['claim_id']='section-dimension-requested_response-'+b1.a3.OID
                prior['case']['state']['candidate']['id']=prior['claim_id']
                existing=b1.support.make_request(prior['case'],whole_statement=True)
                store=b1.support.requests.ReceiptStore(Path(directory)/'evaluation/qualified-observations'/existing.fingerprint/'execution')
                b1.support.requests.execute(existing,b1.support.provider.OneRequestLedger('.03',existing.version),store,wire)
                p['items']=[prior,item];sent=[];rendered=[]
                def first(spec):sent.append('presence');return self.presence(spec,.96)
                def second(spec):sent.append('support');return wire(spec,output=None if valid else '{}')
                with patch.object(b1,'load',return_value=data),patch.object(b1,'PRESENCE',data['spec'].fingerprint), \
                     patch.object(b1,'assemble',return_value=({},p)), \
                     patch.object(b1.section,'write_document',side_effect=lambda p,r,rec,doc:rendered.append(doc)), \
                     patch.object(b1.support.correction,'request',side_effect=AssertionError('No correction')):
                    result=b1.run(path,b1.PROPOSAL,b1.OID,presence_transport=first,support_transport=second)
                self.assertEqual(['presence','support'],sent)
                self.assertEqual('DELIVERED_TWO_REVIEWED_CASES' if valid else 'STOPPED_SUPPORT',result['status'])
                self.assertEqual(valid,item['claim_id'] in rendered[0]['ready_claim_ids'])
                self.assertEqual(2,result['paid_attempts']);self.assertEqual(0,result['corrections'])
                self.assertLessEqual(float(result['retained_reservations_usd']),.04)

    def test_wrong_approval_never_reads_or_dispatches(self):
        with patch.object(b1,'load',side_effect=AssertionError('No read')):
            for key,oid in [('wrong',b1.OID),(b1.PROPOSAL,'A1')]:
                with self.assertRaisesRegex(ValueError,'approval required'):b1.run('unused',key,oid)
        with self.assertRaisesRegex(ValueError,'zero retries'):b1.PresenceLedger().check([{}],'source_verification')

    def test_changed_packet_cannot_reuse_approved_key(self):
        with TemporaryDirectory() as directory:
            path=Path(directory)/'proposal.json'
            path.write_text(json.dumps(dict(fingerprint=b1.PROPOSAL,candidate='changed')))
            with self.assertRaisesRegex(ValueError,'Exact approved B1'):
                b1.load(path)


if __name__=='__main__':unittest.main()
