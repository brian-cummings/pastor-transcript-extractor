import unittest
from unittest.mock import patch
from typer.testing import CliRunner
from pastor_transcript_extractor import segment_evidence_plan as p


class SegmentPlanTests(unittest.TestCase):
    def test_plan_is_read_only_and_quotes_are_last(self):
        plan,_=p.verify()
        self.assertEqual('V8_DELIVERED_IMPLEMENTATION_GOAL_COMPLETE_PORTABILITY_PROPOSED',plan['status'])
        self.assertEqual('gap_code_map_delivered_remedies_conditional',plan['milestone_status']['4'])
        self.assertFalse(plan['source_review_pilot']['automatic_binding'])
        self.assertTrue(plan['historical_capability_decision']['pilot_execution'])
        self.assertEqual('pastor-profile-description-v8',plan['current_delivery'])
        self.assertEqual(['R1','R3','R4'],plan['profile_reuse_increment']['main_path'])
        self.assertTrue(plan['verification']['feature_increment_executed'])
        self.assertEqual(10,plan['bounded_delivery']['reviewed_local_proposals'])
        self.assertEqual(0,plan['bounded_delivery']['raw_leaf_answers_reused'])
        self.assertEqual('Brian',plan['connected_binding_development']['executor'])
        self.assertEqual(3,plan['connected_binding_development']['max_generation_requests'])
        self.assertEqual(3,plan['connected_binding_development']['live_provider_requests'])
        self.assertEqual(7,plan['connected_binding_development']['metadata_reads'])
        self.assertEqual(0,plan['connected_binding_development']['review_provider_requests'])
        self.assertEqual(0,plan['connected_binding_development']['review_metadata_reads'])
        self.assertEqual(14,plan['connected_binding_development']['raw_propositions'])
        self.assertEqual(29,plan['connected_binding_development']['raw_frames'])
        self.assertEqual(0,plan['connected_binding_development']['compiled_bindings'])
        self.assertTrue(plan['connected_binding_development']['semantic_comparison_complete'])
        self.assertEqual('Brian',plan['binding_revision']['executor'])
        self.assertEqual(39,plan['binding_revision']['live_provider_requests'])
        self.assertEqual(0,plan['binding_revision']['review_provider_requests'])
        self.assertTrue(plan['binding_revision']['semantic_comparison_complete'])
        self.assertEqual(0,plan['binding_revision']['development_content']['fully_faithful'])
        self.assertFalse(plan['binding_revision']['proposed_architecture_executed'])
        self.assertEqual(.8,plan['binding_revision']['min_probability'])
        self.assertTrue(plan['binding_separation']['new_implementation_verified'])
        self.assertTrue(plan['binding_separation']['original_G1_records_unchanged'])
        self.assertEqual(10,plan['binding_separation']['source_readings'])
        self.assertTrue(plan['binding_development']['live_results_available'])
        self.assertTrue(plan['binding_development']['semantic_comparison_complete'])
        self.assertEqual(15,plan['binding_development']['live_provider_requests'])
        self.assertEqual(0,plan['binding_development']['development_content']['fully_faithful'])
        self.assertEqual('assurance_of_salvation',plan['source_review_pilot']['test_domain'])
        self.assertEqual('pastor-profile-description-v2',plan['presentation_revision']['version'])
        self.assertEqual('unchanged_from_V1',plan['presentation_revision']['raw_observations_and_underlying_claims'])
        self.assertEqual('optional_Ollama_illustrative_quote',plan['pipeline_order'][-1])
        self.assertFalse(plan['provider_execution']);self.assertFalse(plan['exact_span_extraction_required_upstream'])
        self.assertEqual(['preceding_segment','center_segment','following_segment'],plan['quote_context'])

    def test_rejects_reinference_and_misplaced_semantics(self):
        from copy import deepcopy
        plan,_=p.verify()
        for field,value in (
                ('full_pack_miss_proves_constituent_absence',True),
                ('end_stage_general_extractor',True),
                ('quote_supplies_analytical_authority',True),
                ('semantic_owner','final_profile_summarizer'),
                ('standalone_inventory_gate',True),
                ('failed_experiment_automatically_starts_variant',True),
                ('unknowns_block_supported_delivery',True)):
            with self.subTest(field=field):
                changed=deepcopy(plan)
                changed['profile_reuse_increment'][field]=value
                with patch.object(p.trace,'read',return_value=changed):
                    with self.assertRaisesRegex(ValueError,'Reuse-first'):
                        p.verify()

    def test_description_revision_keeps_evidence_and_execution_boundaries(self):
        from copy import deepcopy
        plan,_=p.verify()
        self.assertEqual(['D1','D2','D3','D4'],plan['description_increment']['sequence'])
        self.assertEqual('BOUNDED_RUN_VERIFIED_WORDING_REVIEW_PENDING',plan['description_increment']['status'])
        self.assertEqual('V8_pending_concrete_portrait_review',plan['verification']['human_acceptance'])
        for field,value in (('provider_execution',True),
                ('promote_reviewed_proposals_to_production',True),
                ('example_is_measurement_ground_truth',True),
                ('technical_delivery_is_reader_acceptance',True),
                ('preserve_meaning_changing_qualifications',False),
                ('listener_directive_run_is_next',True)):
            with self.subTest(field=field):
                changed=deepcopy(plan)
                changed['description_increment'][field]=value
                with patch.object(p.trace,'read',return_value=changed):
                    with self.assertRaisesRegex(ValueError,'description planning'):
                        p.verify()

    def test_editorial_synthesis_cannot_release_semantic_or_comparison_holds(self):
        from copy import deepcopy
        plan,_=p.verify()
        self.assertEqual(1,plan['editorial_synthesis']['max_generation_requests'])
        for field,value in (('max_generation_requests',2),('semantic_acceptance',True),
                ('benchmark_comparison_available',True),('confidence_calibrated',True),
                ('citations_prove_entailment',True),('no_raw_transcripts',False),
                ('automatic_retries',True),('default_description_command_provider_free',False),
                ('required_portrait_in_generation_schema',False),('prior_run_preserved',False)):
            with self.subTest(field=field):
                changed=deepcopy(plan);changed['editorial_synthesis'][field]=value
                with patch.object(p.trace,'read',return_value=changed):
                    with self.assertRaisesRegex(ValueError,'editorial synthesis'):
                        p.verify()

    def test_direct_editorial_revision_cannot_change_measurements_or_weaken_reuse_checks(self):
        from copy import deepcopy
        plan,_=p.verify()
        for field,value in (('provider_requests',1),('reader_acceptance',True),
                ('full_point_digest_required',False),('original_evidence_unchanged',False)):
            changed=deepcopy(plan);changed['direct_editorial_revision'][field]=value
            with self.subTest(field=field),patch.object(p.trace,'read',return_value=changed):
                with self.assertRaisesRegex(ValueError,'Direct editorial'):
                    p.verify()

    def test_portrait_does_not_turn_interpretation_into_measurement_or_stability(self):
        from copy import deepcopy
        plan,_=p.verify()
        for field,value in (('semantic_admission',True),('ministry_stability',True),
                ('source_frame_reinterpretation',True),('assurance_selection_bias_visible',False),
                ('requires_warrant_limits_and_alternative',False)):
            changed=deepcopy(plan);changed['portrait_increment'][field]=value
            with self.subTest(field=field),patch.object(p.trace,'read',return_value=changed):
                with self.assertRaisesRegex(ValueError,'portrait interpretation'):
                    p.verify()

    def test_portability_is_one_proposed_cached_case_not_implicit_execution_or_validation(self):
        from copy import deepcopy
        plan,_=p.verify()
        self.assertEqual('complete',plan['implementation_goal']['status'])
        self.assertEqual(5,len(plan['documentation_cleanup']['archives']))
        for field,value in (('execution_authorized',True),('implemented',True),('provider_requests',1),
                ('max_additional_profiles',2),('cached_evidence_only',False),
                ('manual_interpretation_disclosure',False),('profile_318_wording_transplant',True)):
            changed=deepcopy(plan);changed['portability_proposal'][field]=value
            with self.subTest(field=field),patch.object(p.trace,'read',return_value=changed):
                with self.assertRaisesRegex(ValueError,'portability scope'):
                    p.verify()

    def test_cleanup_snapshots_and_active_document_hashes_are_checked(self):
        from copy import deepcopy
        plan,_=p.verify()
        for field in ('archive','active'):
            changed=deepcopy(plan)
            if field=='archive':changed['documentation_cleanup']['archives'][0]['original_sha256']='changed'
            else:changed['documentation_cleanup']['active_docs']['docs/PASTOR_PROFILE_DESCRIPTION.md']='changed'
            original=p.trace.read
            def read(path,sealed=False):
                return changed if path.name=='plan-v30.json' else original(path,sealed)
            with self.subTest(field=field),patch.object(p.trace,'read',side_effect=read):
                with self.assertRaisesRegex(ValueError,'documentation'):
                    p.verify()

    def test_closed_run_rejected_before_provider_or_frozen_input(self):
        from pastor_transcript_extractor import typesafe_selection_execution as e
        with patch.object(e.spec,'verify',side_effect=AssertionError('No old workflow')):
            with self.assertRaisesRegex(ValueError,'retired'):
                e.execute(p.OLD_SELECTION_INPUT,transport=lambda *a:self.fail('No inference'))

    def test_cli_plan_and_conflicting_mode(self):
        from pastor_transcript_extractor.cli import app
        result=CliRunner().invoke(app,['analysis','structure-readiness','--segment-plan','--json'])
        self.assertEqual(0,result.exit_code,result.output)
        result=CliRunner().invoke(app,['analysis','structure-readiness','--segment-plan','--run-selection'])
        self.assertEqual(2,result.exit_code)
