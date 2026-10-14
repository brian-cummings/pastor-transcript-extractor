from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from typer.testing import CliRunner
from pastor_transcript_extractor.cli import app
from pastor_transcript_extractor.sermon_leaf_packs import SOURCE_MATERIAL
from pastor_transcript_extractor.sermon_source_material_review import (
    DEFAULT_SOURCE_REVIEW_OUTPUT, SOURCE_COMPLETED_FINGERPRINT,
    build_source_completion, write_source_completion,
)


class SourceCompletionTests(unittest.TestCase):
    def test_completion_preserves_frozen_answers_boundaries_and_overlap(self):
        before = DEFAULT_SOURCE_REVIEW_OUTPUT.read_bytes()
        report = build_source_completion()
        self.assertEqual(before, DEFAULT_SOURCE_REVIEW_OUTPUT.read_bytes())
        self.assertEqual('PASS', report['stage_gate'])
        self.assertEqual(SOURCE_COMPLETED_FINGERPRINT, report['source_review_fingerprint'])
        self.assertEqual(SOURCE_MATERIAL.digest(), report['question_pack_digest'])
        self.assertEqual(23, report['authored_probe_matches'])
        observations = {c['block_id']: c for c in report['natural_observations']}
        self.assertEqual(.63, observations[36]['probabilities']['historical_example'])
        self.assertEqual(.70, observations[57]['probabilities']['personal_testimony'])
        self.assertIn('not verified lived testimony', observations[37]['interpretation'])
        self.assertEqual('accepted_eligibility_only', report['routing']['decision'])
        self.assertFalse(report['broader_collection_activated'])
        self.assertEqual(.70, report['review_display_threshold'])
        self.assertEqual(0, report['provider_requests'])

    def test_tampered_evidence_or_changed_questions_cannot_receive_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            source = json.loads(DEFAULT_SOURCE_REVIEW_OUTPUT.read_text())
            source['cases'][0]['leaf_answer']['probabilities']['quotation'] = .123
            path = Path(directory)/'changed.json'
            path.write_text(json.dumps(source))
            with self.assertRaisesRegex(ValueError, 'fingerprint-valid'):
                build_source_completion(path)
        with patch('pastor_transcript_extractor.sermon_source_material_review.SOURCE_MATERIAL',
                   replace(SOURCE_MATERIAL, boundary='Changed semantics')):
            with self.assertRaisesRegex(ValueError, 'unchanged questions'):
                build_source_completion()

    def test_provider_free_cli_reuse_and_output_pair_repair(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)/'decision.json'
            module = 'pastor_transcript_extractor.commands.analysis.content'
            with patch(module+'.Database', side_effect=AssertionError('No database')), \
                 patch(module+'.TypeSafeSdkAdapter', side_effect=AssertionError('No provider')):
                for action in ('Wrote', 'Reused'):
                    result = CliRunner().invoke(app, ['analysis', 'source-material-stage-gate', '--output', str(output)])
                    self.assertEqual(0, result.exit_code, result.output + str(result.exception))
                    self.assertIn(action, result.output)
                    self.assertIn('provider_requests=0', result.output)
            output.with_suffix('.md').write_text('damaged')
            self.assertFalse(write_source_completion(output, build_source_completion())[2])
            self.assertTrue(write_source_completion(output, build_source_completion())[2])
