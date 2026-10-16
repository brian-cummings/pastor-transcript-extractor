"""Synthetic roles/ranks only. No real encoder or retired-source evaluation."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from pastor_transcript_extractor import collector_role_lattice as lattice
from pastor_transcript_extractor import collector_retrieval as collector
from pastor_transcript_extractor import collector_retrieval_encoder as adapter
from pastor_transcript_extractor import collector_retrieval_workflow as workflow
from pastor_transcript_extractor import evidence_boundary_admission as boundary


def source(text):
    return dict(video_id=999,text=text,main_span=dict(start=0,end=len(text)))


class FakeEncoder:
    tokens=0
    def encode(self,text):
        self.tokens+=len(text.split())
        return [1., float('lamp' in text.lower()), .5]


class LatticeTests(unittest.TestCase):
    def test_coordinates_unicode_and_unpunctuated_source_roundtrip(self):
        for text in ('“Be calm”; you may enter. Remain alert.', 'alpha '*400):
            s=source(text);g=lattice.build(s)
            self.assertLessEqual(len(g['descriptors']),3*len(g['nodes']))
            for item in g['descriptors']:
                p=item['span'];self.assertEqual(text[p['start']:p['end']],p['text'])
            self.assertIsNone(g['diagnostics']['source_voice'])

    def test_condition_qualifier_and_required_content_cannot_be_stripped(self):
        for text in ('If you are afraid. Remember I am with you.',
                     'God will forgive you. But if you turn to him.',
                     'Tell him this: I want to change.'):
            g=lattice.build(source(text)); targets=[c['span']['text'] for c in g['G3_hypotheses']]
            self.assertEqual([text],targets)

    def test_independent_commands_repeat_and_exact_saturation(self):
        g=lattice.build(source('Open your book; sing the verse; bring a notebook; remember the title.'))
        self.assertEqual(2,len(g['G3_hypotheses']))
        self.assertEqual(2,g['diagnostics']['G3_budget_displaced'])
        self.assertEqual(4,g['diagnostics']['G3_structural_hypotheses'])
        self.assertTrue(all(d['reason']=='G3_two_per_unit_saturation' for d in g['G3_displacements']))
        g=lattice.build(source('Take a seat. Take a seat.'))
        self.assertEqual(2,len(g['G3_hypotheses']))
        self.assertNotEqual(g['G3_hypotheses'][0]['span']['start'],g['G3_hypotheses'][1]['span']['start'])

    def test_prayer_report_and_nested_speech_do_not_get_source_authority(self):
        for text in ('Please stand. Lord, give us courage.', 'Mara said: Do not give up. I now ask you to join us.',
                     'We should resolve as she did: I will remain faithful.', 'I comforted him and we left.'):
            graph=lattice.build(source(text))
            self.assertFalse(graph['diagnostics']['identities_are_semantic'])
            self.assertIsNone(graph['diagnostics']['adoption'])
        g=lattice.build(source('If you are afraid. Mara said: you must leave.'))
        self.assertTrue(g['deferred'])


class SelectorTests(unittest.TestCase):
    def test_same_unit_partition_and_reverse_pairs_do_not_assert_bible_truth(self):
        result=collector.discover(source('The lamp gives light; it guides our path.'),FakeEncoder())
        pairs=[c for c in result['candidates'] if c['selection']=='G2_within_unit_partition']
        self.assertEqual(2,len(pairs))
        self.assertEqual(pairs[0]['endpoints']['left'],pairs[1]['endpoints']['right'])
        self.assertTrue(all(c['semantic_truth'] is None and c['pastor_credit'] is False for c in result['candidates']))

    def test_concept_lane_can_nominate_non_gloss_pair_with_injected_rank(self):
        s=source('The lamp was dark. A separate matter arose. Nothing changed. They refused to yield.')
        class Concept(FakeEncoder):
            def encode(self,text):
                return [1.,0.] if ('lamp' in text or 'yield' in text) else [0.,1.]
        r=collector.discover(s,Concept())
        pairs=[c for c in r['candidates'] if c['selection']=='G2_source_wide_concept']
        self.assertTrue(any('lamp' in c['endpoints']['left']['text'] and 'yield' in c['endpoints']['right']['text'] for c in pairs))
        # Topic similarity and reversed pairs remain unmeasured hypotheses.
        self.assertTrue(all(c['semantic_truth'] is None for c in pairs))

    def test_complete_directed_role_crosses_unit_without_dropping_condition(self):
        s=source('If people turn away. They lose the path. The speaker explains the consequence. A separate reminder follows.')
        r=collector.discover(s,FakeEncoder())
        full='If people turn away. They lose the path.'
        pairs=[c for c in r['candidates'] if c['capability']=='G2']
        self.assertTrue(any(c['endpoints']['left']['text']==full and 'explains' in c['endpoints']['right']['text'] for c in pairs))
        self.assertFalse(any(p['text']=='They lose the path.' for c in pairs for p in c['endpoints'].values()))

    def test_no_fallback_for_unencodable_descriptors_and_stable_ties(self):
        class Empty(FakeEncoder):
            def encode(self,text):return None
        s=source('Stay here. Open it. Sing now. Be ready.')
        a=collector.discover(s,FakeEncoder());b=collector.discover(s,FakeEncoder())
        self.assertEqual(a,b)
        r=collector.discover(s,Empty())
        self.assertFalse(any(c['selection']=='G2_source_wide_concept' for c in r['candidates']))
        self.assertTrue(any('ranking_descriptor' in d['reason'] for d in r['deferred']))

    def test_frame_bound_density_and_dependency_budget_are_accounted(self):
        s=source('Open it; bring it; sing now; remain ready. '+('Unrelated material. '*330)+'Remember me.')
        r=collector.discover(s,FakeEncoder());n=len(r['nodes'])
        self.assertLessEqual(len(r['candidates']),10*n)
        self.assertGreater(r['budget_proof']['G3_budget_displaced'],0)
        self.assertTrue(all(len(c['relation_frame']['text'])<=6000 and len(c['automatic_envelope']['text'])<=6000 for c in r['candidates']))
        self.assertTrue(any(d.get('frame_excluded',0) for d in r['search_diagnostics']))

    def test_no_narration_or_candidate_can_enter_real_consumer_without_authority(self):
        from pastor_transcript_extractor import evidence_supply_boundary_v4 as panel
        guard=boundary.Boundary(json.loads(panel.INPUT.read_text()))
        r=collector.discover(source('I comforted him and we left. Please stand.'),FakeEncoder())
        for c in r['candidates']:
            c=deepcopy(c);c.update(positive_facts={'reassurance':'observed'},pastor_credit=True)
            with self.assertRaises((ValueError,KeyError,TypeError)):
                guard.deserialize(json.dumps(c))


class EncoderAndAuthorityTests(unittest.TestCase):
    def test_unauthorized_load_fails_before_import_or_file_access(self):
        with patch.object(adapter,'verify_files',side_effect=AssertionError('No model file access')):
            with self.assertRaisesRegex(ValueError,'not authorized'):adapter.LocalEncoder('/missing')

    def test_token_no_truncation_and_masked_pooling(self):
        self.assertTrue(adapter.validate_tokens(list(range(256))))
        self.assertFalse(adapter.validate_tokens(list(range(257))))
        pooled=adapter.pool([[3.,0.],[0.,4.],[999.,999.]],[1,1,0])
        self.assertAlmostEqual(.6,pooled[0]);self.assertAlmostEqual(.8,pooled[1])
        with self.assertRaises(ValueError):adapter.pool([[float('nan')]], [1])

    def test_exact_files_git_blob_and_weight_sha_are_enforced(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'a';path.write_bytes(b'data')
            item=dict(path='a',size=4,git_blob_sha1=hashlib.sha1(b'blob 4\0data').hexdigest())
            adapter.verify_files(d,dict(files=[item]))
            adapter.verify_files(d,dict(files=[dict(path='a',size=4,sha256=hashlib.sha256(b'data').hexdigest())]))
            path.write_bytes(b'fake')
            with self.assertRaises(ValueError):adapter.verify_files(d,dict(files=[item]))

    def test_absent_separate_authorization_blocks_both_execution_routes(self):
        p=dict(content_fingerprint='prepared')
        with tempfile.TemporaryDirectory() as d,patch.object(workflow,'EXECUTION',Path(d)/'absent.json'):
            for operation in ('model_acquisition_authorized','development_execution_authorized'):
                with self.assertRaisesRegex(ValueError,'absent'):
                    workflow.require_execution(p,'prepared',operation)


class WorkflowTests(unittest.TestCase):
    def test_atomic_seal_is_immutable_and_recovers_without_partial_reuse(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);p=root/'sealed.json';v=workflow.prep.seal({'stage':'complete'})
            budgets=dict(inventory_bytes_max=10000,runtime_output_bytes_max=10000)
            (root/'sealed.json.crashed.partial').write_text('incomplete')
            workflow.save_checkpoint(p,v,budgets);workflow.save_checkpoint(p,v,budgets)
            self.assertEqual(v,workflow.design.sealed(p))
            with self.assertRaises(ValueError):workflow.save_checkpoint(p,workflow.prep.seal({'stage':'changed'}),budgets)
            with self.assertRaises(ValueError):workflow.save_checkpoint(root/'other.json',v,dict(inventory_bytes_max=1,runtime_output_bytes_max=10000))

    def test_synthetic_real_workflow_seals_before_matching_and_reuses_result(self):
        from pastor_transcript_extractor import collector_recall_repair_v4_1 as matching
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);s=workflow.prep.seal(source('Please stand. Remain ready.'))
            span=dict(start=0,end=13,text='Please stand.')
            refs=workflow.prep.seal(dict(rows=[dict(reference_id='synthetic',video_id=999,capability='G3',
                classification='definite_compatible_opportunity',source_namespace='current_preacher',
                roles=dict(utterance=span),equivalent_role_occurrences=dict(utterance=[span]),required_source_evidence_spans=[])],controls=[]))
            ref=root/'refs.json';ref.write_text(json.dumps(refs))
            packet=dict(content_fingerprint='synthetic',artifact_lock_fingerprint='model',development_video_ids=[999],
                source_files={},reference_path=str(ref),reference_sha256=workflow.design.file_hash(ref),
                resources=dict(wall_time_seconds_max=30,inventory_bytes_max=1000000,runtime_output_bytes_max=10000000))
            original=matching.match_rows
            def checked(*args):
                self.assertTrue((root/'synthetic/natural-inventory-v1.json').exists())
                return original(*args)
            with patch.object(workflow,'verify',return_value=packet),patch.object(workflow,'require_execution',return_value={'model_loading_authorized':True,'content_fingerprint':'synthetic-authority'}),patch.object(workflow,'preflight',return_value=[]),patch.object(workflow,'sources',return_value={999:s}),patch.object(workflow,'directory',return_value=root),patch.object(adapter,'LocalEncoder',return_value=FakeEncoder()) as loader,patch.object(matching,'match_rows',side_effect=checked):
                result=workflow.run_development(approve_input='synthetic')
                again=workflow.run_development(approve_input='synthetic')
            self.assertEqual(result,again);self.assertEqual(1,loader.call_count)
            self.assertEqual('DEVELOPMENT_DIAGNOSTIC_ONLY',result['verdict'])
            self.assertEqual(0,result['provider_requests']);self.assertIsNone(result['admitted_items'])
            self.assertIn('999',result['G3_budget_displacement'])


class CliGateTests(unittest.TestCase):
    def test_execution_and_acquisition_cli_cannot_load_or_generate_under_current_hold(self):
        from typer.testing import CliRunner
        from pastor_transcript_extractor.cli import app
        with tempfile.TemporaryDirectory() as d,patch.object(workflow,'verify',return_value={'content_fingerprint':'held'}),patch.object(workflow,'EXECUTION',Path(d)/'absent.json'),patch.object(collector,'discover',side_effect=AssertionError('No candidates')),patch.object(adapter,'LocalEncoder',side_effect=AssertionError('No model')):
            for flag in ('--run-development','--acquire-model'):
                result=CliRunner().invoke(app,['analysis','collector-retrieval',flag,'--approve-input','held'])
                self.assertNotEqual(0,result.exit_code)
                self.assertIn('authorization is absent',result.output)
