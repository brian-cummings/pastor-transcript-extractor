from copy import deepcopy
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from pastor_transcript_extractor import profile_section_measurements as m
from pastor_transcript_extractor import profile_section as section
from pastor_transcript_extractor.collector_retrieval_json_v1_1 import seal
from test_profile_description import fixture


def data():
    inv,sources=fixture(routed=True)
    return m.build(inv,sources,[dict(video_id=9,blocks=[dict(block_id=1)])])


class MeasurementSectionTests(unittest.TestCase):
    def test_literal_draft_is_recomputed_from_frozen_inputs_without_provider_or_authored_readings(self):
        with TemporaryDirectory() as folder:
            root=Path(folder);packet=data();path=root/'inputs.json';path.write_text(json.dumps(packet))
            p=dict(input_fingerprint='frozen',materialized_composition=m.LITERAL_VERSION,
                materialized_inputs=dict(path=str(path),sha256=section.file_hash(path)),
                budget=dict(spend_root=str(root/'requests'),cumulative_ceiling_usd='1'))
            with patch.object(section,'load',return_value=(p,root)):
                prepared=section.prepare_analysis(root/'plan.json');self.assertEqual('0',prepared['reserved_usd'])
                result=section.run_analysis(root/'plan.json','frozen',transport=lambda s:self.fail('No draft inference'))
                self.assertEqual(m.literal_reading(packet),result['reading']);self.assertEqual([],result['rounds'])
                edited=deepcopy(result);edited['reading']['clauses'][0]['text']='An authored replacement'
                (root/'analysis/results.json').write_text(json.dumps(edited))
                with self.assertRaisesRegex(ValueError,'output changed'):section.read_analysis(p,root)

    def test_literal_composition_preserves_every_alternative_and_only_selected_positive_findings(self):
        packet=data();reading=m.literal_reading(packet)
        self.assertEqual([],m.inspect(reading,packet,literal=True)[1])
        positive=[o for o in packet['observations'] if o['state']=='observed']
        self.assertEqual(1,len(positive));self.assertEqual(1,len(reading['clauses']))
        self.assertEqual('The selected passages discuss '+packet['contracts'][positive[0]['field']]['description']+'.',reading['clauses'][0]['text'])
        # Metamorphic input: a different admitted relationship, not an expected pastor answer.
        changed=deepcopy(packet)
        for o in changed['observations']:o['state']='observed' if o['field']=='judgment_final_destiny' else 'measured_below_threshold'
        next_reading=m.literal_reading(changed)
        self.assertEqual('The selected passages discuss '+changed['contracts']['judgment_final_destiny']['description']+'.',next_reading['clauses'][0]['text'])
        self.assertIn(' or ',next_reading['clauses'][0]['text'])
        for o in changed['observations']:o['state']='observed'
        grouped=m.literal_reading(changed)
        self.assertEqual([],m.inspect(grouped,changed,literal=True)[1])
        self.assertTrue(grouped['hypotheses'])
        self.assertTrue(all(h['warrant'] and h['alternatives'] and h['defeaters'] for h in grouped['hypotheses']))
        scaled=deepcopy(changed)
        scaled['observations']=[dict(o,id=o['id']+'-'+str(i)) for i in range(14) for o in changed['observations']]
        complete=m.literal_reading(scaled)
        self.assertEqual([],m.inspect(complete,scaled,literal=True)[1])
        self.assertEqual(len(scaled['observations']),sum(len(h['premise_ids']) for h in complete['hypotheses']))

    def test_structured_draft_through_ordinary_support_and_final_document_without_new_bindings(self):
        from test_profile_analysis_support_execution import wire
        with TemporaryDirectory() as folder:
            root=Path(folder);inv,sources=fixture(routed=True,text='God supplies salvation as an unearned gift.')
            source=root/'source.json';source.write_text(json.dumps(sources[9]))
            inv['sermons'][0].update(source_path=str(source),source_sha256=section.file_hash(source))
            inv['selected_profile']['effective_member_video_ids']=[9];inv=seal(inv)
            packet=m.build(inv,sources,[dict(video_id=9,blocks=[dict(block_id=1)])])
            inputs=root/'measurements.json';inputs.write_text(json.dumps(packet))
            p=dict(input_fingerprint='frozen',profile=inv['selected_profile'],inventory_fingerprint=inv['content_fingerprint'],
                coverage=inv['coverage'],unknowns=section.UNKNOWN,source_identity=[dict(video_id=9,url='https://youtu.be/example',
                    source_path=str(source),source_sha256=section.file_hash(source),gate=dict(eligible=True))],
                materialized_inputs=dict(path=str(inputs),sha256=section.file_hash(inputs)),acceptance_authorization=None,
                tasks=[dict(id='v9b1',window=dict(video_id=9,blocks=[dict(block_id=1)]))],
                budget=dict(spend_root=str(root/'requests'),support_reservation_usd='1.25',cumulative_ceiling_usd='1',starting_conservative_usd=str(section.x.supervised.BASELINE_SPEND)))
            result=root/'sources/v9b1';result.mkdir(parents=True)
            (result/'result.json').write_text(json.dumps(dict(observations=[],eligible=0,verification_receipt=None)))
            eid=next(o['id'] for o in packet['observations'] if o['state']=='observed')
            value=dict(hypotheses=[],clauses=[dict(id='grace',text='The selected passage records salvation as an unearned gift.',entry_ids=[eid],scope_video_ids=[9],role='observation',assertion_force='local_observation')],unknowns=['Adoption is not measured.'])
            with patch.object(section,'load',return_value=(p,root)):
                prepared=section.prepare_analysis(root/'plan.json')
                self.assertLess(section.Decimal(prepared['reserved_usd']),section.Decimal('.50'))
                draft=section.run_analysis(root/'plan.json','frozen',transport=lambda s:wire(s,json.dumps(value)))
                self.assertEqual(value,draft['reading'])
                section.run_analysis(root/'plan.json','frozen',transport=lambda s:self.fail('draft cache must be reused'))
                support=section.prepare_support(root/'plan.json')
                self.assertEqual(1,support['claims']);self.assertEqual(0,support['eligible_bindings'])
                def support_wire(spec):
                    raw=wire(spec);outer=json.loads(raw.text);answer=json.loads(outer['choices'][0]['message']['content'])
                    answer['assertion_force']=dict(complete=True,assertions=[dict(excerpt=value['clauses'][0]['text'],force='local_observation',
                        measurement_entitlement='within_meaning',reason='Restates the supplied admitted relationship.')])
                    outer['choices'][0]['message']['content']=json.dumps(answer)
                    return type(raw)(200,json.dumps(outer))
                section.run_support(root/'plan.json','1','frozen',transport=support_wire)
                delivery=section.render(root/'plan.json')
                self.assertEqual(1,delivery['model_supported']);self.assertEqual(9,delivery['reused_materialized_observations'])
                doc=json.loads(Path(delivery['document_input']).read_text())
                entry=doc['entries'][0];self.assertEqual(value['clauses'][0]['text'],entry['statement'])
                self.assertEqual('admitted_local_relationship',doc['section_trace'][entry['claim_id']]['evidence_kind'])
                self.assertIn('which reported views the preacher adopts',Path(delivery['draft']).read_text())
                edited=json.loads((root/'analysis/results.json').read_text());edited['reading']['clauses'][0]['text']='Manual prose'
                (root/'analysis/results.json').write_text(json.dumps(edited))
                with self.assertRaisesRegex(ValueError,'output changed'):section.read_analysis(p,root)

    def test_reuses_admitted_meanings_without_authored_readings_or_raw_text_in_drafting(self):
        with patch('pastor_transcript_extractor.profile_evidence_supply.attach',side_effect=AssertionError('authored inputs forbidden')):
            packet=data()
        self.assertEqual(9,len(packet['observations']))
        self.assertEqual(1,sum(o['state']=='observed' for o in packet['observations']))
        self.assertEqual(3,len(packet['unresolved_leaves']))
        spec=m.request(packet)
        self.assertEqual('Qwen/Qwen3.8-27B',spec.body['model'])
        self.assertEqual('none',spec.body['reasoning_effort'])
        self.assertNotIn('full_target_text',json.dumps(m.state(packet)))
        self.assertNotIn('A quoted view is discussed',spec.body['messages'][1]['content'])
        self.assertFalse(packet['authored_presentation_inputs'])

    def test_draft_references_and_scope_are_checked_without_semantic_repair(self):
        packet=data();eid=packet['observations'][0]['id']
        value=dict(hypotheses=[],clauses=[dict(id='local',text='A local measured relationship is recorded.',
            entry_ids=[eid],scope_video_ids=[9],role='observation',assertion_force='local_observation')],unknowns=['Adoption is unknown.'])
        original=deepcopy(value);parsed,errors=m.inspect(value,packet)
        self.assertEqual([],errors);claims=m.claims(parsed,packet)
        self.assertEqual(value,original);self.assertEqual(value['clauses'][0]['text'],claims[0]['wording'])
        self.assertEqual([eid],claims[0]['evidence_ids'])
        self.assertNotIn('machine_observation_ids',claims[0])
        bad=deepcopy(value);bad['clauses'][0]['scope_video_ids']=[77]
        self.assertTrue(m.inspect(bad,packet)[1])
        bad=deepcopy(value);bad['clauses'][0]['entry_ids']=['invented']
        self.assertTrue(m.inspect(bad,packet)[1])
        bad=deepcopy(value);bad['clauses'][0]['role']='inference'
        self.assertTrue(m.inspect(bad,packet)[1])

    def test_uncertainty_is_valid_and_never_forces_a_clause(self):
        packet=data();value=dict(hypotheses=[],clauses=[],unknowns=['Insufficient qualified distinctions.'])
        parsed,errors=m.inspect(value,packet)
        self.assertEqual([],errors);self.assertEqual([],m.claims(parsed,packet))
        inv,sources=fixture(routed=True)
        self.assertEqual([],m.build(inv,sources,[dict(video_id=9,blocks=[dict(block_id=999)])])['observations'])


if __name__=='__main__':unittest.main()
