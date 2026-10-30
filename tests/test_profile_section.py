from copy import deepcopy
from dataclasses import asdict, replace
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from pastor_transcript_extractor import response_growth_binding as producer
from pastor_transcript_extractor import profile_section as section
from pastor_transcript_extractor import evidence_requests as requests
from pastor_transcript_extractor import profile_analysis_support as core
from test_source_context import fixture


def reading():
    window, _, value = fixture()
    for c in value['claims']:
        c['response_growth'] = dict(requested_response='Not established in this target.',
            growth='not_stated',evidence=[],facets=['salvation'],
            reader_statement=c['proposition']['reading'])
    spec=producer.request(window)
    checked=producer.inspect(value,window,spec,'receipt.json')
    return window,spec,value,checked


class SectionTests(unittest.TestCase):
    def test_versioned_source_contract_preserves_existing_binding_semantics(self):
        window,spec,value,checked=reading()
        self.assertEqual([],checked['errors'])
        self.assertEqual(2,len(checked['observations']))
        self.assertEqual(spec.body['model'],producer.hosted.FLASH_MODEL)
        self.assertNotIn('expected',spec.body['messages'][1]['content'])
        self.assertEqual(2,producer.schema()['properties']['claims']['maxItems'])
        saved=deepcopy(value);producer.inspect(value,window,spec,'receipt.json')
        self.assertEqual(saved,value)
        self.assertTrue(all(o['production_admission']=='not_admitted' for o in checked['observations']))

    def test_extension_literal_failure_cannot_leave_partial_accepted_inventory(self):
        window,spec,value,_=reading()
        value['claims'][0]['response_growth'].update(growth='gradual_growth',evidence=[dict(source_field='target_text',text='invented')])
        result=producer.inspect(value,window,spec,'receipt.json')
        self.assertTrue(result['errors']);self.assertEqual([],result['observations'])

    def test_full_field_eligibility_and_uncertainty_remain_independent(self):
        window,_,_,checked=reading()
        spec=producer.verification(window,checked['observations'])
        self.assertEqual('jev-1.13.0',spec.body['model'])
        answer=dict(output={k:dict(type='noul',noul=.99) for k in spec.body['questions']})
        rows=producer.qualify(checked,answer,spec)
        self.assertTrue(all(o['section_eligibility']['eligible'] for o in rows))
        key=rows[0]['id']+':conditions';answer['output'][key]['noul']=.5
        rows=producer.qualify(checked,answer,spec)
        self.assertFalse(rows[0]['section_eligibility']['eligible'])
        self.assertTrue(rows[1]['section_eligibility']['eligible'])
        self.assertEqual(checked['observations'][0]['binding'],rows[0]['binding'])

    def test_main_question_original_false_acceptance_requires_priority_warrant(self):
        original='The main question for further listening is how these reassuring invitations and warnings fit together in his fuller understanding of salvation and discipleship.'
        for force in ('local_observation','comparative_priority'):
            with self.assertRaisesRegex(ValueError,'warrant'):
                section.check_strength(dict(wording=original,assertion_force=force))
        section.check_strength(dict(wording='An invitation appears in this selected passage.',assertion_force='local_observation'))

    def test_assembly_uses_machine_presentations_and_preserves_withheld_inputs(self):
        window,_,_,checked=reading();spec=producer.verification(window,checked['observations'])
        rows=producer.qualify(checked,dict(output={k:dict(type='noul',noul=.99) for k in spec.body['questions']}),spec)
        rows[0]['section_eligibility']['eligible']=False
        packet=dict(profile=dict(id=99),inventory_fingerprint='inventory',source_identity=[],tasks=[],coverage={})
        result=section.assemble_record(packet,[dict(observations=rows)])
        self.assertEqual(len(result['claims']),1)
        self.assertEqual(result['claims'][0]['wording'],rows[1]['response_growth']['reader_statement'])
        self.assertEqual(result['machine_observations'],rows)
        packet['profile']['id']=888
        other=section.assemble_record(packet,[dict(observations=rows)])
        self.assertEqual(result['claims'],other['claims'])
        self.assertEqual(result['hypotheses'],[])

    def test_shared_plan_machine_seam_and_named_failure(self):
        claim=dict(id='machine',wording='An example',machine_observation_ids=['missing'],scope={},upstream_claim_ids=[])
        record=dict(profile=dict(id=99),inventory_fingerprint='inventory',observations=[],source_identity=[],reader=dict(claims=[claim]),machine_observations=[])
        plan=core.build_plan(record)
        self.assertIsNone(plan['items'][0]['case'])
        self.assertTrue(plan['items'][0]['gap'])

    def test_complete_sequence_reservation_includes_correction_and_verification(self):
        _,spec,_,_=reading()
        one=2*requests.request_reservation(spec)+requests.reservation('source_verification')
        self.assertLessEqual(one,section.Decimal('.50'))
        self.assertLessEqual(6*one+section.Decimal('1.25'),section.Decimal('3'))

    def test_flash_streaming_reuses_detector_and_preserves_source_semantics(self):
        from test_deepinfra_streaming import Harness,loop,normal
        window,old,value,_=reading()
        streamed=producer.hosted.streaming_request(old)
        self.assertEqual(old.body,streamed.body)
        self.assertEqual(old.body['model'],streamed.body['model'])
        self.assertEqual(2,streamed.preflight()['stream_recovery']['maximum_attempts'])
        with TemporaryDirectory() as folder:
            store=requests.ReceiptStore(Path(folder))
            h=Harness(streamed,[loop(streamed),normal(streamed,json.dumps(value))])
            response=requests.execute(streamed,producer.hosted.OneRequestLedger(str(requests.request_reservation(streamed)),streamed.version),store,h.managed())
            self.assertEqual(2,len(h.requests))
            self.assertEqual(old.body,{k:v for k,v in h.requests[0].items() if k!='stream'}|{'stream':False})
            checked=producer.inspect(response['output'],window,streamed,'stream-receipt')
            self.assertEqual([],checked['errors'])
            correction=requests.corrective_request(streamed,'{}',[dict(path='$',code='schema',message='Missing fields')],producer.reading_diagnostics.CORRECTION)
            correction.preflight()
            self.assertEqual(streamed.body['messages'],correction.body['messages'][:2])
            usage=section.x.supervised.check.demo.usage_account(store)
            self.assertEqual(2,usage['paid_attempts']);self.assertEqual(1,usage['reserved_cancelled_usage_attempts'])
        one=2*requests.request_reservation(streamed)+requests.reservation('source_verification')
        self.assertLess(one,section.Decimal('.50'))
        self.assertLess(6*one+section.Decimal('1.25')+section.Decimal('.0890834'),section.Decimal(3))

    def test_local_enum_transport_does_not_relax_local_semantic_acceptance(self):
        window,old,value,_=reading();original=deepcopy(value)
        revised=producer.local_enum_transport(producer.hosted.streaming_request(old))
        self.assertEqual(old.body['messages'][1],revised.body['messages'][1])
        self.assertTrue(revised.body['messages'][0]['content'].startswith(old.body['messages'][0]['content']))
        self.assertEqual(old.body['model'],revised.body['model'])
        self.assertNotIn('"enum"',json.dumps(revised.body['response_format']))
        self.assertEqual(producer.evidence.digest(producer.schema()),revised.source_identity['local_schema_digest'])
        checked=producer.inspect(value,window,revised,'local-enum-receipt')
        self.assertEqual([],checked['errors']);self.assertEqual(original,value)
        value['claims'][0]['adoption']['status']='invented_choice'
        invalid=producer.inspect(value,window,revised,'local-enum-receipt')
        self.assertTrue(invalid['errors']);self.assertEqual([],invalid['observations'])
        with self.assertRaisesRegex(ValueError,'already selected'):producer.local_enum_transport(revised)

    def test_source_feedback_headroom_preserves_entire_prefix_and_single_correction(self):
        _,old,_,_=reading();spec=producer.local_enum_transport(producer.hosted.streaming_request(old))
        spec=replace(spec,body=deepcopy(spec.body))
        room=49152-spec.preflight()['request_upper_bound']-1000
        spec.body['messages'][1]['content']+='x'*max(0,room);spec.preflight()
        output=' '*2500+'{}';errors=[dict(path='$',code='schema',message='Missing required fields')]
        with self.assertRaisesRegex(ValueError,'input exceeds reservation'):
            section.source_correction(spec,output,errors)
        revised=section.source_correction(spec,output,errors,headroom=True)
        self.assertEqual(65536,revised.runtime_identity['input_cap'])
        self.assertEqual(spec.body['messages'],revised.body['messages'][:2])
        self.assertEqual(output,revised.body['messages'][2]['content'])
        self.assertEqual(spec.body['model'],revised.body['model'])
        self.assertEqual(spec.body['response_format'],revised.body['response_format'])
        revised.preflight()
        with self.assertRaises(ValueError):section.source_correction(revised,'{}',errors,headroom=True)

    def test_stubbed_source_through_shared_support_and_final_handoff(self):
        from test_learning_demo_correction import wire_response
        from test_profile_analysis_support_execution import wire
        window,spec,value,_=reading()
        with TemporaryDirectory() as folder:
            root=Path(folder);calls=[]
            source_path=root/'proposed.json';source_path.write_text('{"classification": {}}')
            window=replace(window,source_sha256=section.file_hash(source_path))
            spec=producer.request(window)
            blocks=[dict(b,text=b['target_text']) for b in window.blocks]
            packet=dict(input_fingerprint='frozen',profile=dict(id=window.profile_id,effective_member_video_ids=[window.video_id],membership_fingerprint='membership'),
                inventory_fingerprint='inventory',coverage={},unknowns=section.UNKNOWN,source_identity=[dict(video_id=window.video_id,url='https://example.org/watch?v=source',source_path=str(source_path),source_sha256=window.source_sha256,gate=dict(eligible=True))],acceptance_authorization=None,
                tasks=[dict(id=window.id,window=asdict(window),request=asdict(spec),reserved_usd='.11')],
                budget=dict(spend_root=str(root/'requests'),cumulative_ceiling_usd='1',starting_conservative_usd='0',support_reservation_usd='1.25'))
            def send(request):
                calls.append(request)
                if request.phase=='source_verification':
                    return dict(output={k:dict(type='noul',noul=.99) for k in request.body['questions']},usage=dict(input_tokens=100,output_tokens=0),model='jev-1.13.0',complete=True)
                return wire_response(request,json.dumps(value))
            with patch.object(section,'load',return_value=(packet,root)),patch.object(section.sermon_topics,'resolve_topic_analysis_artifact',return_value=dict(blocks=blocks)),patch.object(section.sermon_topics,'resolve_topic_block_context',side_effect=lambda b:dict(target_text=b['target_text'])):
                result=section.run_source(root/'plan.json',window.id,'frozen',transport=send)
                self.assertEqual(2,result['eligible'])
                section.run_source(root/'plan.json',window.id,'frozen',transport=lambda s:self.fail('no replay'))
                self.assertEqual(len(calls),2)
                prepared=section.prepare_support(root/'plan.json')
                self.assertEqual(2,prepared['claims'])
                section.run_support(root/'plan.json','1','frozen',transport=lambda s:wire(s))
                delivered=section.render(root/'plan.json')
                self.assertEqual(2,delivered['model_supported'])
                document=json.loads(Path(delivered['document_input']).read_text())
                self.assertEqual('not_admitted',document['production_admission'])
                self.assertTrue(document['section_trace'])
                # An extension cannot be hand-edited after its producer/verification
                # receipts are saved, even with the same original observation ID.
                record=core.read_record(root/'assembled-profile.json')
                record['machine_observations'][0]['response_growth']['reader_statement']='Manual replacement'
                broken=core.build_plan(record)
                self.assertTrue(any(i['gap'] for i in broken['items']))

    def test_unknown_usage_failure_handoff_preserves_reservation_and_has_no_claims(self):
        window,spec,_,_=reading()
        with TemporaryDirectory() as folder:
            root=Path(folder)
            p=dict(base_dir=str(root),profile=dict(id=window.profile_id,effective_member_video_ids=[window.video_id]),
                inventory_fingerprint='inventory',coverage={},source_identity=[],unknowns=section.UNKNOWN,
                tasks=[dict(id=window.id,window=asdict(window),request=asdict(spec))],code_identity={},
                budget=dict(spend_root=str(root/'requests'),cumulative_ceiling_usd='1',starting_conservative_usd=str(section.x.supervised.BASELINE_SPEND)))
            p['input_fingerprint']=section.digest(p)
            path=root/'plan.json';path.write_text(json.dumps(p))
            target=section.x._store(p,spec)
            # Same durable state as a transport exception: reservation exists,
            # but no complete response/usage receipt may be manufactured.
            target.write_immutable('attempts/'+spec.fingerprint+'.json',dict(request_fingerprint=spec.fingerprint,
                phase=spec.phase,reserved_usd=str(requests.request_reservation(spec)),namespace=spec.namespace,provider='DeepInfra'))
            with patch.object(section,'inventory',return_value=dict(content_fingerprint='inventory')),patch.object(section,'windows',return_value=[window]):
                result=section.failure_handoff(path)
                replay=section.failure_handoff(path)
            self.assertEqual(result,replay)
            self.assertEqual('FAILED_BOUNDED_DELIVERY',result['status'])
            self.assertEqual(1,result['costs']['unknown_usage_attempts'])
            self.assertEqual(requests.request_reservation(spec),section.Decimal(result['costs']['new_conservative_usd']))
            self.assertIsNone(result['costs']['actual_invoice_usd'])
            doc=json.loads(Path(result['document_input']).read_text())
            self.assertEqual([],doc['ready_claim_ids']);self.assertEqual([],doc['entries'])
            self.assertTrue(doc['known_gaps']);self.assertTrue(result['paid_execution_stopped'])
            self.assertFalse((target.root/'receipts'/f'{spec.fingerprint}.json').exists())
            # An explicitly authorized recovery preserves the original payload,
            # lost attempt and allowance; it cannot mint a second recovery.
            p['budget']['maximum_sequence_reservation_usd']='.2'
            p['input_fingerprint']=section.digest({k:v for k,v in p.items() if k!='input_fingerprint'})
            path.write_text(json.dumps(p))
            with patch.object(section,'inventory',return_value=dict(content_fingerprint='inventory')),patch.object(section,'windows',return_value=[window]):
                recovery=section.prepare_recovery(path)
                changed=json.loads(Path(recovery['plan']).read_text())
                self.assertEqual(p['tasks'][0]['request']['body'],changed['tasks'][0]['request']['body'])
                self.assertEqual(p['budget'],changed['budget'])
                self.assertTrue((target.root/'attempts'/f'{spec.fingerprint}.json').exists())
                with self.assertRaisesRegex(ValueError,'Only one recovery'):
                    section.prepare_recovery(recovery['plan'])


if __name__=='__main__':unittest.main()
