"""Bound preflight and revisioned CLI; never run diagnostic datasets."""
from unittest.mock import patch
from typer.testing import CliRunner
import test_collector_recall_repair as original
from pastor_transcript_extractor import collector_recall_repair_v4_1 as repaired
from pastor_transcript_extractor.cli import app


class RevisedHarnessTests(original.DevelopmentReviewTests):
    def setUp(self):
        self.patch=patch.object(original,'r',repaired);self.patch.start();self.addCleanup(self.patch.stop)

    def test_cli_defaults_to_read_only_and_requires_bound_input(self):
        with patch.object(repaired,'verify',return_value=(dict(content_fingerprint='sealed'),{})), \
             patch.object(repaired,'size_preflight',return_value=[]), \
             patch.object(repaired,'run_development',side_effect=AssertionError('no dataset')):
            result=CliRunner().invoke(app,['analysis','collector-recall-repair','--revision','v4.1','--check-only'])
        self.assertEqual(0,result.exit_code,result.output)
        for options in (['--run-development'],['--approve-input','wrong'],['--prepare-confirmation'],['--execute-paid']):
            result=CliRunner().invoke(app,['analysis','collector-recall-repair','--revision','v4.1',*options])
            self.assertNotEqual(0,result.exit_code)

    def test_structural_size_proof_catches_overflow_before_materialization(self):
        rows=[dict(video_id=90,source_chars=50000,sentence_nodes=1201,G2_G3_upper_bound=12010)]
        with self.assertRaisesRegex(ValueError,'Source 90 size preflight'):repaired.validate_size_proofs(rows)
        self.assertIsNone(repaired.validate_size_proofs([dict(video_id=90,source_chars=50000,sentence_nodes=1099,G2_G3_upper_bound=10990)]))

    def test_aggregate_preflight_is_not_just_per_source(self):
        with self.assertRaisesRegex(ValueError,'Aggregate size preflight'):
            repaired.validate_size_proofs([dict(video_id=i,source_chars=50000,sentence_nodes=800,G2_G3_upper_bound=8000) for i in range(3)])

    def test_old_execution_is_retired_with_actionable_error(self):
        with patch.object(original.r,'run_development',side_effect=AssertionError('no execution')):
            result=CliRunner().invoke(app,['analysis','collector-recall-repair','--revision','v4','--run-development','--approve-input','old'])
        self.assertNotEqual(0,result.exit_code)
        self.assertIn('v4.1',result.output)
