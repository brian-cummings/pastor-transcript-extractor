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


if __name__=='__main__':unittest.main()
