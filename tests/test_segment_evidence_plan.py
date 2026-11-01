import json
import unittest
from copy import deepcopy
from unittest.mock import patch
from typer.testing import CliRunner
from pastor_transcript_extractor import segment_evidence_plan as p


class SegmentPlanTests(unittest.TestCase):
    def test_current_status_and_boundaries_are_read_only(self):
        plan,path=p.verify()
        self.assertEqual('partial',plan['product_goal']['automatic_analysis_acceptance'])
        self.assertFalse(plan['product_goal']['broad_dimensional_benchmark_validated'])
        self.assertEqual('optional_Ollama_illustrative_quote',plan['pipeline_order'][-1])
        self.assertEqual('PASTOR_PROFILE_PRODUCT_PLAN.md',path.name)
        self.assertFalse(plan['provider_execution'])
        self.assertNotIn('documentation_cleanup',plan)
        self.assertNotIn('previous_registry',plan)
        self.assertNotIn('archive_manifest_path',plan)

    def test_reuse_policy_does_not_allow_late_reinference(self):
        plan,_=p.verify()
        for field,value in (
                ('full_pack_miss_proves_constituent_absence',True),
                ('end_stage_general_extractor',True),
                ('quote_supplies_analytical_authority',True),
                ('semantic_owner','final_profile_summarizer'),
                ('failed_experiment_automatically_starts_variant',True)):
            changed=deepcopy(plan);changed['reuse_policy'][field]=value
            with self.subTest(field=field),patch.object(p.trace,'read',return_value=changed):
                with self.assertRaisesRegex(ValueError,'Reuse-first'):
                    p.verify()

    def test_current_evidence_cannot_become_benchmark_or_full_product_acceptance(self):
        plan,_=p.verify()
        for group,field,value in (
                ('product_goal','broad_dimensional_benchmark_validated',True),
                ('product_goal','unknown_is_not_zero',False),
                ('automatic_section_delivery','eligible_complete_bindings',12),
                ('automatic_section_delivery','remaining_credit_is_new_experiment_authorization',True)):
            changed=deepcopy(plan);changed[group][field]=value
            with self.subTest(field=field),patch.object(p.trace,'read',return_value=changed):
                with self.assertRaisesRegex(ValueError,'Product acceptance'):
                    p.verify()

    def test_active_document_changes_are_detected(self):
        plan,_=p.verify()
        changed=deepcopy(plan)
        changed['active_document_hashes']['docs/PASTOR_PROFILE_PRODUCT_PLAN.md']='changed'
        with patch.object(p.trace,'read',return_value=changed):
            with self.assertRaisesRegex(ValueError,'Current documentation'):
                p.verify()

    def test_obsolete_selection_stays_blocked_without_archive_or_status_dependencies(self):
        from pastor_transcript_extractor import typesafe_selection_execution as e
        with patch.object(p,'verify',side_effect=AssertionError('No documentation dependency')):
            with self.assertRaisesRegex(ValueError,'retired'):
                e.execute(p.OLD_SELECTION_INPUT,transport=lambda *a:self.fail('No inference'))

    def test_cli_reports_current_goal_without_archive_dependencies(self):
        from pastor_transcript_extractor.cli import app
        result=CliRunner().invoke(app,['analysis','structure-readiness','--segment-plan','--json'])
        self.assertEqual(0,result.exit_code,result.output)
        report=json.loads(result.output)
        self.assertEqual('AUTOMATIC_ANALYSIS_PARTIAL_DIMENSIONAL_BENCHMARK_GOAL_NOT_ACHIEVED',report['status'])
        self.assertEqual(0,report['provider_requests'])
        self.assertTrue(report['implementation_path'].endswith('PASTOR_PROFILE_IMPLEMENTATION_PLAN.md'))
        result=CliRunner().invoke(app,['analysis','structure-readiness','--segment-plan','--run-selection'])
        self.assertEqual(2,result.exit_code)
