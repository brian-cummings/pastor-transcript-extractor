"""Prospective synthetic invariants only; no dataset or real encoder execution."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from pastor_transcript_extractor import collector_role_lattice_v1_1 as lattice
from pastor_transcript_extractor import collector_retrieval_v1_1 as collector
from pastor_transcript_extractor import collector_retrieval_json_v1_1 as seals
from pastor_transcript_extractor import collector_retrieval_workflow_v1_1 as workflow
from pastor_transcript_extractor import collector_retrieval_workflow as historical


def source(text): return dict(video_id=999,text=text,main_span=dict(start=0,end=len(text)))


class Encoder:
    tokens=0
    def encode(self,text):
        self.tokens+=len(text.split())
        return [1.,float('lamp' in text.lower()),.5]


class RoleTests(unittest.TestCase):
    def test_G2_independent_of_all_G3_retention_and_quota_displacements(self):
        s=source('Open a book; sing a verse; bring a notebook; remember a title. A lamp was lit. Remain ready. Read a passage.')
        a=collector.discover(s,Encoder())
        with patch.object(lattice,'g3_roles',return_value=([],[],[])):
            b=collector.discover(s,Encoder())
        for key in ('descriptors','G2_primary','retrieval_trace','composition_trace','resource_counts'):
            self.assertEqual(a[key],b[key])
        self.assertEqual([c for c in a['candidates'] if c['capability']=='G2'],[c for c in b['candidates'] if c['capability']=='G2'])
        self.assertGreater(a['lattice_diagnostics']['G3_budget_displaced'],0)

    def test_qualification_cannot_become_an_unqualified_core(self):
        texts=('You cannot rely on anybody but God.',
               'If the door is closed, do not enter.',
               'Do not enter, unless the guide calls.',
               'If the door is closed. Do not enter.',
               'You may leave; but you must return before dark.',
               'Read the passage; if you have not read it, memorize the words.',
               'You should decide: “I will remain faithful.”',
               'We should resolve as she did. I will remain faithful.',
               'I told him, I will remain faithful.',
               'You must not; trust strangers.')
        for text in texts:
            with self.subTest(text=text):
                g=lattice.build(source(text))
                targets=[c['span']['text'] for c in g['G3_hypotheses']]
                self.assertTrue(targets or g['deferred'])
                self.assertTrue(all(t==text for t in targets),targets)

    def test_unresolved_completion_and_referent_defer_instead_of_claim(self):
        for text in ('Because the road is closed.', 'He will protect you.', 'Tell her that:', '“Come inside.'):
            g=lattice.build(source(text))
            self.assertEqual([],g['G3_hypotheses'])
            self.assertTrue(any(d['capability']=='G3' for d in g['deferred']))
        # G2 text hypotheses are independent of an act-oriented referent veto.
        g=lattice.build(source('He spoke quietly. Another subject follows.'))
        self.assertIsNotNone(g['G2_primary'][0])

    def test_quota_applies_after_dependency_closure_and_retains_reviewable_trace(self):
        g=lattice.build(source('Open a book; sing a verse; bring a notebook; remember a title.'))
        self.assertEqual(2,len(g['G3_hypotheses']))
        self.assertEqual(2,len(g['G3_displacements']))
        self.assertTrue(all(d['structural_dependency_status']=='completed_no_detected_open_dependency' for d in g['G3_displacements']))
        self.assertTrue(all(d['semantic_act_status']=='unmeasured_requires_source_review' for d in g['G3_displacements']))

    def test_oversized_dependency_defers_without_partial_G3_targets(self):
        text='If the path is blocked, '+('you must remain where you are, '*250)+'wait.'
        g=lattice.build(source(text))
        self.assertFalse(g['G3_hypotheses'])
        self.assertTrue(any(d['reason']=='dependency_exceeds_frame_bound' for d in g['deferred']))

    def test_coordinate_exactness_unicode_no_substrate_changes(self):
        s=source('“Open a book”; sing a verse. '+('alpha '*220))
        g=lattice.build(s)
        self.assertEqual(collector.substrate.source_sentences(s),g['nodes'])
        for d in g['descriptors']+g['G3_hypotheses']:
            p=d['span'];self.assertEqual(s['text'][p['start']:p['end']],p['text'])
        self.assertLessEqual(len(g['descriptors']),3*len(g['nodes']))
        self.assertIsNone(g['diagnostics']['adoption'])


class TraceTests(unittest.TestCase):
    def test_every_mate_retains_rank_score_displacement_and_composition(self):
        s=source('A lamp was lit. Another topic arose. Remain ready. Read a page. Open a book. Sing a verse.')
        r=collector.discover(s,Encoder())
        self.assertTrue(r['retrieval_trace'])
        displaced=0
        for query in r['retrieval_trace']:
            self.assertEqual(len(r['descriptors']),len(query['rows']))
            for j,score,rank,code in query['rows']:
                self.assertEqual(j,r['descriptors'][j]['descriptor_id'])
                reason=query['decision_codes'][code]
                if rank is not None:
                    self.assertIsNotNone(score)
                if reason=='top_K_displaced': displaced+=1
        self.assertGreater(displaced,0)
        for c in r['composition_trace']:
            self.assertTrue(c['seed_descriptor_ids'])
            self.assertIsNotNone(c['mate_descriptor_id'])
            for direction in ('forward','reverse'):
                self.assertIn(c[direction]['status'],('emitted','duplicate_geometry_no_refill','representation_rejected','envelope_rejected'))
        self.assertEqual(r,collector.discover(s,Encoder()))

    def test_rejections_and_no_encoder_fallback_are_recorded(self):
        class Empty(Encoder):
            def encode(self,text): return None
        s=source('Open a book. Read a page. Sing a verse. Remain ready.')
        r=collector.discover(s,Empty())
        self.assertEqual([],r['retrieval_trace'])
        self.assertTrue(any(d['reason']=='concept_query_unavailable_no_lexical_fallback' for d in r['search_diagnostics']))
        with patch.object(collector.geometry,'represent',return_value=dict(status='deferred',reason='synthetic_rejection')):
            r=collector.discover(s,Encoder())
        self.assertTrue(r['composition_trace'])
        self.assertTrue(any(c['forward']['status']=='representation_rejected' for c in r['composition_trace']))
        self.assertTrue(all(c['forward']['status'] in ('representation_rejected','duplicate_geometry_no_refill') for c in r['composition_trace']))

    def test_budget_similarity_and_admission_authority_unchanged(self):
        self.assertEqual({k:v for k,v in historical.collector.POLICY.items() if k!='version'},
                         {k:v for k,v in collector.POLICY.items() if k!='version'})
        for a,b in (([1.,2.],[2.,1.]),([1.,0.],[0.,1.])):
            self.assertEqual(historical.collector.cosine(a,b),collector.cosine(a,b))
        r=collector.discover(source('Open a book. Read a page. Sing a verse.'),Encoder())
        self.assertLessEqual(len(r['candidates']),10*len(r['nodes']))
        self.assertTrue(all(c['semantic_truth'] is None and c['pastor_credit'] is False for c in r['candidates']))


class SealAndWorkflowTests(unittest.TestCase):
    def test_numeric_keys_roundtrip_and_collision_rejection(self):
        value=seals.seal(dict(per_unit_saturation={2:1,10:2},unicode='“α”'))
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'sealed.json'
            workflow.save_checkpoint(path,value,dict(inventory_bytes_max=10000,runtime_output_bytes_max=10000))
            reread=workflow.design.sealed(path)
            self.assertEqual(value,reread)
            self.assertEqual(value,seals.seal(json.loads(path.read_text())))
            workflow.save_checkpoint(path,value,dict(inventory_bytes_max=10000,runtime_output_bytes_max=10000))
        for obj in ({2:1,'2':2},{'n':float('nan')},{'n':float('inf')},{True:'x'},{'n':object()}):
            with self.assertRaises(ValueError):seals.seal(obj)

    def test_new_authority_cannot_reuse_V1_decision_or_approval_flag(self):
        with tempfile.TemporaryDirectory() as d,patch.object(workflow,'EXECUTION',Path(d)/'missing.json'):
            with self.assertRaisesRegex(ValueError,'absent'):
                workflow.require_execution(dict(content_fingerprint='new'),'new','development_execution_authorized')
        decision=workflow.design.sealed(historical.EXECUTION)
        with patch.object(workflow,'EXECUTION',historical.EXECUTION),patch.object(workflow.design,'sealed',return_value=decision):
            with self.assertRaisesRegex(ValueError,'mismatches'):
                workflow.require_execution(dict(content_fingerprint='new',artifact_lock_fingerprint='same'),'new','development_execution_authorized')

    def test_prospective_authority_must_bind_exact_resources_and_one_attempt(self):
        packet=dict(content_fingerprint='new',artifact_lock_fingerprint='locked',development_video_ids=[999],resources={'ceiling':1})
        decision=dict(status='AUTHORIZED',decision_owner='Brian',input_fingerprint='new',artifact_lock_fingerprint='locked',
            provider_calls_authorized=False,source_selection_authorized=False,collection_projection_authorized=False,
            semantic_admission_threshold_changes_authorized=False,automatic_provenance_authorized=False,
            model_comparison_training_authorized=False,reference_specific_tuning_authorized=False,
            local_encoder_execution_authorized=True,development_execution_authorized=True,
            attempts=1,development_video_ids=[999],resources={'ceiling':1})
        with patch.object(workflow,'EXECUTION',historical.EXECUTION),patch.object(workflow.design,'sealed',return_value=decision):
            self.assertEqual(decision,workflow.require_execution(packet,'new','development_execution_authorized'))
            decision['attempts']=2
            with self.assertRaisesRegex(ValueError,'mismatches'):
                workflow.require_execution(packet,'new','development_execution_authorized')

    def test_real_workflow_roundtrip_resume_seals_before_reference_matching(self):
        from pastor_transcript_extractor import collector_recall_repair_v4_1 as matching
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);s=seals.seal(source('Open a book; sing a verse; bring a notebook; remember a title. Remain ready.'))
            refs=seals.seal(dict(rows=[],controls=[]));ref=root/'refs.json';ref.write_text(json.dumps(refs))
            p=dict(content_fingerprint='synthetic',development_video_ids=[999],source_files={},reference_path=str(ref),reference_sha256=workflow.design.file_hash(ref),
                resources=dict(wall_time_seconds_max=30,inventory_bytes_max=1000000,runtime_output_bytes_max=10000000))
            original=matching.match_rows
            def checked(*args):
                workflow.design.sealed(root/'synthetic/natural-inventory-v1.1.json')
                return original(*args)
            bindings=(patch.object(workflow,'verify',return_value=p),patch.object(workflow,'require_execution',return_value={'model_loading_authorized':True,'content_fingerprint':'synthetic-authority'}),patch.object(workflow,'preflight',return_value=[]),patch.object(workflow,'sources',return_value={999:s}),patch.object(workflow,'directory',return_value=root),patch.object(workflow.encoder,'LocalEncoder',return_value=Encoder()),patch.object(matching,'match_rows',side_effect=checked))
            from contextlib import ExitStack
            with ExitStack() as stack:
                for binding in bindings: stack.enter_context(binding)
                a=workflow.run_development(approve_input='synthetic')
                self.assertEqual(a,workflow.run_development(approve_input='synthetic'))
                # A source-only restart must reuse its JSON seal without loading.
                (root/'synthetic/results-v1.1.json').unlink()
                with patch.object(workflow.encoder,'LocalEncoder',side_effect=AssertionError('Must reuse sealed checkpoint')):
                    b=workflow.run_development(approve_input='synthetic')
                self.assertEqual(a['historical_exact_target_diagnostics'],b['historical_exact_target_diagnostics'])
            self.assertIsNone(a['admitted_items']);self.assertEqual(0,a['provider_requests'])

    def test_CLI_execution_is_held_before_loading(self):
        from typer.testing import CliRunner
        from pastor_transcript_extractor.cli import app
        with tempfile.TemporaryDirectory() as d,patch.object(workflow,'verify',return_value={'content_fingerprint':'held'}),patch.object(workflow,'EXECUTION',Path(d)/'missing.json'),patch.object(workflow.encoder,'LocalEncoder',side_effect=AssertionError('No model loading')):
            r=CliRunner().invoke(app,['analysis','collector-retrieval-repair','--run-development','--approve-input','held'])
            self.assertNotEqual(0,r.exit_code);self.assertIn('authorization is absent',r.output)
