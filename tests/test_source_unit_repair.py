"""Synthetic infrastructure/integration checks, not the retired sermon slate."""
import json
import unittest
import tempfile
from pathlib import Path
from copy import deepcopy
from unittest.mock import patch
from typer.testing import CliRunner
from pastor_transcript_extractor import evidence_supply_source_unit_repair as c
from pastor_transcript_extractor import evidence_supply_collector_v4_1 as old
from pastor_transcript_extractor import source_unit_repair as runner
from pastor_transcript_extractor import fresh_discovery_preparation as prep
from pastor_transcript_extractor.cli import app


def source(text,offset=0):
    return dict(video_id=991234,text=text,main_span=dict(start=offset,end=len(text)),units=[])


def geometry(result):
    return {(x['capability'],json.dumps(x.get('endpoints',dict(claim=x.get('claim'),target=x.get('target'))),sort_keys=True))
        for x in result['candidates']+result['G1_candidates']}


class UnitRepairTests(unittest.TestCase):
    def test_unpunctuated_unicode_whitespace_preserves_all_canonical_characters(self):
        s=source('PREFIX '+('λόγος\twe remember\n the road  ' * 90),7);before=deepcopy(s)
        nodes=c.source_sentences(s)
        self.assertGreater(len(nodes),1)
        covered=set()
        for n in nodes:
            self.assertEqual(s['text'][n['start']:n['end']],n['text']);self.assertLessEqual(len(n['text']),400)
            covered.update(range(n['start'],n['end']))
        self.assertTrue(all(i in covered for i in range(7,len(s['text'])) if not s['text'][i].isspace()))
        self.assertEqual(before,s)

    def test_caption_breaks_are_preferred_but_not_required(self):
        s=source('word '*600);s['units']=[dict(end=250),dict(end=501),dict(end=750)]
        self.assertEqual(249,c.source_sentences(s)[0]['end'])
        self.assertGreater(len(c.source_sentences(source(s['text']))),1)

    def test_no_space_oversize_token_is_bounded_and_lossless(self):
        s=source('界'*1301);nodes=c.source_sentences(s)
        self.assertEqual(s['text'],''.join(n['text'] for n in nodes));self.assertEqual(4,len(nodes))

    def test_ordinary_punctuation_candidate_geometries_and_envelopes_unchanged(self):
        s=source('Dr. Vale reads the letter. That means every household may enter. Come inside. The invitation remains. Stay with us.')
        a=old.discover(s);b=c.discover(s)
        self.assertEqual(old.source_sentences(s),c.source_sentences(s));self.assertEqual(geometry(a),geometry(b))
        for x in b['candidates']:self.assertEqual(prep.automatic_envelope(s,x),c.automatic_envelope(s,x))

    def test_target_crossing_a_mechanical_seam_is_naturally_supplied(self):
        text='ordinary word '*35+'Miriam said please stay beside the travelers until morning '+ 'ordinary word '*80
        s=source(text);result=c.discover(s)
        phrase='Miriam said please stay beside the travelers until morning'
        self.assertTrue(any(phrase in x['endpoints']['utterance']['text'] for x in result['candidates'] if x['capability']=='G3'))
        self.assertLessEqual(len(result['candidates']),10*len(result['nodes']))
        for x in result['candidates']:
            self.assertFalse(x['pastor_credit']);self.assertIsNone(x['semantic_truth'])
            self.assertFalse(x['automatic_provenance_attestation'])
            self.assertLessEqual(len(x['relation_frame']['text']),6000)

    def test_mixed_punctuation_and_sparse_regions_keep_small_sentences(self):
        s=source('A full sentence. '+ 'unpunctuated text '*90+' End. A closing sentence.')
        nodes=c.source_sentences(s)
        self.assertEqual('A full sentence.',nodes[0]['text']);self.assertEqual('A closing sentence.',nodes[-1]['text'])
        self.assertTrue(all(len(n['text'])<=1000 for n in nodes))

    def test_repaired_targets_use_actual_phase_isolated_request_factory(self):
        s=source('The narrator remembers the journey '+ 'ordinary word '*110)
        result=c.discover(s);x=next(x for x in result['candidates'] if x['capability']=='G3')
        envelope=c.automatic_envelope(s,x);shapes=prep.shapes(s,x,envelope)
        self.assertEqual(2,len(shapes))
        self.assertEqual(x['act_target']['text'],shapes[0]['state']['target_text'])
        from pastor_transcript_extractor.sermon_g3_feasibility_review import ACTS
        self.assertFalse(set(ACTS)&set(shapes[1]['questions']))
        runner.validate_natural(dict(entries=[dict(candidate=x,automatic_envelope=envelope)]))

    def test_source_ceiling_fails_explicitly_without_truncation(self):
        s=source('unpunctuated words '*100)
        with self.assertRaisesRegex(ValueError,'ceiling exceeded'):
            c.discover(s,{**c.POLICY,'source_candidate_ceiling':1})

    def test_all_frozen_miss_classes_preserved_without_semantic_credit(self):
        cats=['confirmed_source_unit_segmentation_failure','confirmed_directed_pair_materialization_failure','frozen_composite_target_miss_with_reference_granularity_question']
        misses=[dict(reference_id=str(i),video_id=i,source_review_classification=cat,source_roles={}) for i,cat in enumerate(cats)]
        rows=[dict(reference_id=str(i),role_containment_hits=['natural'] if i==0 else [],required_evidence_coverage_hits=[]) for i in range(3)]
        groups=runner.cohort_report(dict(misses=misses),rows)
        self.assertEqual(set(cats),set(groups));self.assertEqual(0,groups[cats[0]]['natural_required_evidence_hits'])

    def test_envelope_preserves_required_frame_without_attesting_provenance(self):
        s=source('ordinary text '*140)
        result=c.discover(s)
        for candidate in result['candidates']:
            env=c.automatic_envelope(s,candidate);frame=candidate['relation_frame']
            self.assertEqual('prepared_not_attested',env['status'])
            self.assertLessEqual(env['start'],frame['start']);self.assertGreaterEqual(env['end'],frame['end'])
            self.assertEqual(s['text'][env['start']:env['end']],env['text'])
            self.assertIsNone(env['source_voice']);self.assertIsNone(env['atomic_sufficiency'])
        self.assertEqual(result,json.loads(json.dumps(result)))

    def test_no_space_split_is_disclosed_and_reference_input_is_not_accepted(self):
        result=c.discover(source('z'*1301))
        self.assertEqual([400,800,1200],result['unit_diagnostics']['hard_token_split_coordinates'])
        self.assertFalse(result['unit_diagnostics']['units_are_semantic_boundaries'])
        with self.assertRaises(TypeError):c.discover(source('A thought.'),references=[])

    def test_synthetic_runner_seals_before_matching_and_reuses_sealed_result(self):
        s=source('ordinary word '*110);vid=s['video_id']
        role=dict(start=0,end=8,text=s['text'][:8])
        ref=dict(reference_id='synthetic',video_id=vid,capability='G3',source_namespace='current_preacher',
            classification='definite_compatible_opportunity',roles=dict(utterance=role),
            equivalent_role_occurrences=dict(utterance=[role]),required_source_evidence_spans=[role])
        packet=dict(content_fingerprint='synthetic-input',development_video_ids=[vid])
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);refs=root/'references.json';before=root/'before.json'
            refs.write_text(json.dumps(prep.seal(dict(rows=[ref],controls=[]))))
            before.write_text(json.dumps(prep.seal(dict(records=[dict(reference_id='synthetic',role_containment_hits=[],required_evidence_coverage_hits=[])],
                workload={str(vid):dict(counts={})}))))
            review=dict(artifacts=dict(results=dict(path=str(before))),misses=[dict(reference_id='synthetic',video_id=vid,
                source_review_classification='confirmed_source_unit_segmentation_failure',source_roles=ref['roles'])])
            old_inventory=dict(source_files={},inventories=[dict(video_id=vid,entries=[])])
            sealed=prep.gate.sealed
            def read(path):
                if Path(path)==refs:self.assertTrue((root/'synthetic-input/natural-inventory-v1.json').exists())
                return sealed(path)
            with patch.object(runner,'verify',return_value=(packet,review)), patch.object(runner,'source_inputs',return_value=(old_inventory,{vid:s})), \
                    patch.object(runner,'directory',return_value=root), patch.object(runner.baseline,'REFERENCES',refs), patch.object(prep.gate,'sealed',side_effect=read):
                result=runner.run_development(approve_input='synthetic-input')
                self.assertEqual(0,result['provider_requests']);self.assertIsNone(result['admitted_items'])
                self.assertEqual(1,result['cohorts']['confirmed_source_unit_segmentation_failure']['natural_complete_role_hits'])
                self.assertEqual(result,runner.run_development(approve_input='synthetic-input'))

    def test_cli_requires_exact_fingerprint_and_never_implies_provider_authority(self):
        result=CliRunner().invoke(app,['analysis','source-unit-repair','--run-development'])
        self.assertNotEqual(0,result.exit_code)
        with patch.object(runner,'verify',return_value=({'content_fingerprint':'abc'},{})):
            with self.assertRaisesRegex(ValueError,'exact prepared'):
                runner.run_development(approve_input='wrong')


if __name__=='__main__':unittest.main()
