from copy import deepcopy
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest
from pastor_transcript_extractor import profile_analysis_support_execution as x
from pastor_transcript_extractor import profile_support_correction as correction
from pastor_transcript_extractor import learning_demo_correction as legacy
from test_profile_analysis_support_execution import packet,wire


def enabled(folder):
    p,out=packet(folder)
    for task in p['tasks']:task['correction']=correction.policy(x.requests.RequestSpec(**task['request']))
    p['budget']['reserved_usd']=str(2*Decimal(p['budget']['reserved_usd']))
    p['budget']['maximum_paid_attempts']=8
    p['input_fingerprint']=x.digest({k:v for k,v in p.items() if k!='input_fingerprint'})
    return p,out


class ProfileCorrectionTests(unittest.TestCase):
    def test_missing_fields_reported_and_correction_uses_original_prefix(self):
        with TemporaryDirectory() as folder:
            p,out=enabled(folder);sent=[]
            def send(spec):
                sent.append(spec)
                if len(sent)==1:return wire(spec,'{"judgment":"supported"}')
                return wire(spec)
            report=x.recipe(p,out,send)
            self.assertEqual(len(sent),3);self.assertEqual(report['accounting']['contract_corrections'],1)
            self.assertEqual(report['accounting']['new_paid_attempts'],3)
            self.assertEqual(report['coverage']['by_status'],dict(supported=2))
            initial,fixed=sent[:2]
            self.assertEqual(fixed.body['messages'][:2],initial.body['messages'])
            self.assertEqual(fixed.body['messages'][2],dict(role='assistant',content='{"judgment":"supported"}'))
            feedback=fixed.body['messages'][3]['content']
            for field in ('$.evidence','$.reason','$.qualifications'):self.assertIn(field,feedback)
            self.assertEqual(fixed.body['response_format'],initial.body['response_format'])
            self.assertEqual(fixed.source_identity['correction_of'],initial.fingerprint)
            self.assertEqual(len(report['results'][0]['rounds']),2)
            self.assertEqual(report['results'][0]['rounds'][0]['status'],'component_failure')
            self.assertEqual(x.recipe(p,out,lambda s:self.fail('no replay')),report)
            replay=deepcopy(p);replay['input_fingerprint']='other-document-run'
            cached=x.recipe(replay,Path(folder)/'other',lambda s:self.fail('reuse initial and correction'))
            self.assertEqual(cached['accounting']['new_paid_attempts'],0)
            self.assertEqual(cached['accounting']['cache_reused_claims'],2)

    def test_retry_exhaustion_and_binding_diagnostics_never_relax_validation(self):
        with TemporaryDirectory() as folder:
            p,out=enabled(folder);sent=[]
            def send(spec):
                sent.append(spec);a=json.loads(json.loads(wire(spec).text)['choices'][0]['message']['content']);a['evidence']=['invented'];return wire(spec,json.dumps(a))
            report=x.recipe(p,out,send)
            self.assertEqual(len(sent),4);self.assertEqual(report['accounting']['contract_corrections'],2)
            self.assertEqual(report['coverage']['by_status'],dict(component_failure=2))
            self.assertTrue(all(len(r['rounds'])==2 for r in report['results']))
            self.assertIn('$.evidence[0]',sent[1].body['messages'][-1]['content'])
            self.assertEqual(json.loads((out/'document-input.json').read_text())['ready_claim_ids'],[])

    def test_valid_unresolved_and_required_qualification_are_not_repaired(self):
        with TemporaryDirectory() as folder:
            p,out=enabled(folder);sent=[]
            def send(spec):
                sent.append(spec);return wire(spec,json.dumps(dict(judgment='unresolved',evidence=[],qualifications=[],reason='Insufficient supplied context.')))
            report=x.recipe(p,out,send);self.assertEqual(len(sent),2);self.assertEqual(report['accounting']['contract_corrections'],0)
            self.assertEqual(report['coverage']['by_status'],dict(unresolved=2))
        with TemporaryDirectory() as folder:
            p,out=enabled(folder);sent=[]
            def send(spec):
                sent.append(spec);a=json.loads(json.loads(wire(spec).text)['choices'][0]['message']['content']);a['qualifications']=[dict(reading='Missing restriction.',evidence=a['evidence'],status='missing_required',preservation_evidence=[])];return wire(spec,json.dumps(a))
            report=x.recipe(p,out,send);self.assertEqual(len(sent),2);self.assertEqual(report['accounting']['contract_corrections'],0)
            self.assertEqual(report['coverage']['by_status'],dict(requires_qualification=2))

    def test_unknown_usage_during_correction_stops_batch_without_third_send(self):
        with TemporaryDirectory() as folder:
            p,out=enabled(folder);sent=[]
            def send(spec):
                sent.append(spec)
                if len(sent)==1:return wire(spec,'{}')
                raise OSError('lost correction response')
            report=x.recipe(p,out,send)
            self.assertEqual(len(sent),2);self.assertEqual(report['execution_status'],'HALTED')
            self.assertEqual(report['coverage']['by_status'],dict(component_failure=1,not_run=1))
            self.assertGreaterEqual(Decimal(report['accounting']['new_conservative_charge_usd']),x.requests.request_reservation(sent[1]))
            with self.assertRaisesRegex(ValueError,'uncertain spend'):
                other=deepcopy(p);other['input_fingerprint']='new';x.recipe(other,Path(folder)/'other',lambda s:self.fail('no repeat'))

    def test_no_feedback_for_incomplete_transport_and_overflow_stops_without_truncation(self):
        with TemporaryDirectory() as folder:
            p,out=enabled(folder);sent=[]
            def send(spec):
                sent.append(spec);raw=json.loads(wire(spec).text);raw['choices'][0]['finish_reason']='length';return x.requests.WireResponse(200,json.dumps(raw))
            report=x.recipe(p,out,send);self.assertEqual(len(sent),2);self.assertEqual(report['accounting']['contract_corrections'],0)
        with TemporaryDirectory() as folder:
            p,out=enabled(folder);sent=[]
            def send(spec):sent.append(spec);return wire(spec,'x'*20000)
            report=x.recipe(p,out,send)
            self.assertEqual(len(sent),2);self.assertTrue(all('no truncation' in r['correction_blocked'] for r in report['results']))

    def test_shared_experimental_request_builder_is_preserved_and_no_second_correction(self):
        with TemporaryDirectory() as folder:
            p,out=enabled(folder);task=p['tasks'][0];spec=x.requests.RequestSpec(**task['request']);errors=[dict(path='$',code='json',message='Bad JSON')]
            shared=correction.request(spec,'bad',errors,task['correction'])
            historical=legacy.corrective_request(dict(request=task['request'],correction=dict(template=task['correction']['template'])),'bad',errors)
            self.assertEqual(shared,historical)
            with self.assertRaisesRegex(ValueError,'Only one'):correction.request(shared,'bad',errors,correction.policy(shared))
            self.assertEqual(spec.body['messages'],shared.body['messages'][:2])

    def test_whitespace_recovery_and_contract_correction_share_reserved_limits(self):
        from test_deepinfra_streaming import Harness,loop,normal
        with TemporaryDirectory() as folder:
            p,out=enabled(folder);harnesses=[]
            def send(spec,**kwargs):
                content='{}' if not harnesses else json.loads(wire(spec).text)['choices'][0]['message']['content']
                bodies=([loop(spec)] if len(harnesses)<2 else [])+[normal(spec,content)]
                h=Harness(spec,bodies);harnesses.append(h);return h.run(**kwargs)
            send.supports_stream_callbacks=True
            report=x.recipe(p,out,send)
            self.assertEqual(report['execution_status'],'COMPLETE')
            self.assertEqual(report['accounting']['contract_corrections'],1)
            self.assertEqual(report['accounting']['new_paid_attempts'],5)
            self.assertEqual(sum(len(h.requests) for h in harnesses),5)
            self.assertLessEqual(Decimal(report['accounting']['new_conservative_charge_usd']),Decimal(p['budget']['reserved_usd']))
            self.assertEqual(report['coverage']['by_status'],dict(supported=2))

    def test_frozen_whole_batch_reserves_correction_before_sending(self):
        from contextlib import contextmanager
        from unittest.mock import patch
        @contextmanager
        def nearly_full(packet,root):yield [({},Decimal('.60'))]
        with TemporaryDirectory() as folder:
            p,out=enabled(folder)
            with patch.object(x.supervised,'cumulative_history',nearly_full),self.assertRaisesRegex(ValueError,'reservations'):
                x.recipe(p,out,lambda s:self.fail('must reserve corrections before any send'))
