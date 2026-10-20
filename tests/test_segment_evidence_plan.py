import unittest
from unittest.mock import patch
from typer.testing import CliRunner
from pastor_transcript_extractor import segment_evidence_plan as p


class SegmentPlanTests(unittest.TestCase):
    def test_plan_is_read_only_and_quotes_are_last(self):
        plan,_=p.verify()
        self.assertEqual('IMPLEMENTED_PENDING_HUMAN_ACCEPTANCE',plan['status'])
        self.assertEqual('gap_code_map_delivered_remedies_conditional',plan['milestone_status']['4'])
        self.assertEqual('pending',plan['verification']['human_acceptance'])
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
