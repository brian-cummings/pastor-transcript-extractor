import unittest
from unittest.mock import patch
from typer.testing import CliRunner
from pastor_transcript_extractor import segment_evidence_plan as p


class SegmentPlanTests(unittest.TestCase):
    def test_plan_is_read_only_and_quotes_are_last(self):
        plan,_=p.verify()
        self.assertEqual('AUTOMATIC_BINDING_V2_PREPARED_NOT_EXECUTED',plan['status'])
        self.assertEqual('gap_code_map_delivered_remedies_conditional',plan['milestone_status']['4'])
        self.assertFalse(plan['source_review_pilot']['automatic_binding'])
        self.assertTrue(plan['next_capability_decision']['pilot_execution'])
        self.assertEqual('automatic-generic-proposition-binding-dev-v2',plan['current_delivery'])
        self.assertEqual('Brian',plan['binding_revision']['executor'])
        self.assertEqual(0,plan['binding_revision']['live_provider_requests'])
        self.assertFalse(plan['binding_revision']['semantic_comparison_complete'])
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
