from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from typer.testing import CliRunner

from pastor_transcript_extractor import evidence_supply_review as supply
from pastor_transcript_extractor.cli import app


class EvidenceSupplyReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.packet = supply.build_packet()

    def rehash(self, packet):
        packet['content_fingerprint'] = supply.fingerprint({k: v for k, v in packet.items() if k != 'content_fingerprint'})
        return packet

    def test_preparation_never_constructs_provider_and_is_reproducible(self):
        with patch('pastor_transcript_extractor.sermon_g1_feasibility_review.Provider', side_effect=AssertionError('provider')), patch('pastor_transcript_extractor.sermon_g2_feasibility_review.Provider', side_effect=AssertionError('provider')), patch('pastor_transcript_extractor.sermon_g3_feasibility_review.Provider', side_effect=AssertionError('provider')):
            self.assertEqual(self.packet, supply.build_packet())
        self.assertEqual(0, self.packet['provider_requests'])
        self.assertFalse(self.packet['execution_preflight']['ready'])
        self.assertEqual(20, len(self.packet['field_readiness']))

    def test_references_never_feed_discovery(self):
        source = deepcopy(self.packet['sources'][0])
        before = supply.discover(source)
        source['expected'] = {'all_candidates': 'positive', 'invented_ramp_policy': True}
        self.assertEqual(before, supply.discover(source))

    def test_spatial_hit_never_becomes_semantic_match_or_usable_item(self):
        rows = self.packet['funnel']
        self.assertTrue(any(r['spatial_candidate_ids'] for r in rows))
        self.assertTrue(any(r['supply_state'] == 'not_supplied' and r['reference_state'] == 'positive' for r in rows))
        self.assertTrue(all(r['discovered_semantic_match'] is None and r['usable_evidence'] is None for r in rows))

    def test_source_attribution_corruption_rejected_after_rehash(self):
        bad = deepcopy(self.packet)
        bad['sources'][0]['profile_id'] = 99999
        with self.assertRaisesRegex(ValueError, 'wrong_source_or_speaker'):
            supply.validate_packet(self.rehash(bad))

    def test_reference_expectation_mutation_rejected_after_rehash(self):
        bad = deepcopy(self.packet)
        bad['references']['rows'][0]['reference_state'] = 'negative_control'
        with self.assertRaisesRegex(ValueError, 'reference decisions changed'):
            supply.validate_packet(self.rehash(bad))

    def test_context_cannot_be_promoted_to_target(self):
        bad = deepcopy(self.packet)
        bad['candidates'][0]['target']['role'] = 'leading_context'
        with self.assertRaisesRegex(ValueError, 'context_promoted_to_target'):
            supply.validate_packet(self.rehash(bad))

    def test_adapter_preserves_each_original_answer_and_reuse_origin(self):
        for adapted in self.packet['source_adapters']:
            original = adapted['original_record']
            self.assertFalse(adapted['pastor_credit'])
            supply.validate_transport(adapted, original)
            mutated = deepcopy(adapted)
            key = next(iter(mutated['original_record']['raw_answers']))
            mutated['original_record']['raw_answers'][key]['choice'] = 'invented'
            with self.assertRaisesRegex(ValueError, 'provenance_loss'):
                supply.validate_transport(mutated, original)

    def test_incompatible_measurement_cannot_receive_natural_credit(self):
        adapted = deepcopy(self.packet['source_adapters'][0])
        adapted['compatibility'] = 'compatible'
        with self.assertRaisesRegex(ValueError, 'incompatible_measurement_credited'):
            supply.validate_transport(adapted, adapted['original_record'])

    def test_missing_provenance_or_projection_rejected(self):
        cap, path, pointer, original = next(supply._frozen_examples())
        bad = deepcopy(original); bad.pop('answer_provenance')
        with self.assertRaisesRegex(ValueError, 'provenance_loss'):
            supply.adapt_frozen(cap, bad, path, pointer)
        adapted = deepcopy(self.packet['source_adapters'][0]); adapted['population_rate'] = 0.5
        with self.assertRaisesRegex(ValueError, 'Held output'):
            supply.validate_transport(adapted, original)

    def test_categories_do_not_average_critical_failures_with_omissions(self):
        common = {'supplied': True, 'reference_state': 'positive', 'observation': 'wrong', 'expected': ['correct']}
        self.assertEqual('critical_integrity_failure', supply.classify_failure(**common, integrity='fabricated_proposition_relation_or_opposite'))
        self.assertEqual('measurement_error', supply.classify_failure(**common))
        self.assertEqual('supply_discovery_miss', supply.classify_failure(supplied=False, reference_state='positive'))
        self.assertEqual('conservative_measurement_omission', supply.classify_failure(supplied=True, reference_state='positive', observation='unclear'))
        self.assertEqual('correctly_withheld', supply.classify_failure(supplied=True, reference_state='ambiguous', observation='unclear'))

    def test_cost_does_not_invent_usable_counts_or_fill_missing_usage(self):
        usage = {'attempts': 3, 'input_tokens': 10000, 'output_tokens': 1000}
        self.assertIsNone(supply.sample_cost(usage, None)['usd_per_usable_item'])
        self.assertIsNone(supply.sample_cost(usage, 0)['usd_per_usable_item'])
        self.assertAlmostEqual(0.00021, supply.sample_cost(usage, 2)['usd_per_usable_item'])
        self.assertIsNone(supply.sample_cost(usage, 2)['corpus_extrapolation'])
        with self.assertRaises(ValueError):
            supply.sample_cost({'attempts': 1, 'input_tokens': None, 'output_tokens': 0}, 1)

    def test_preparation_never_overwrites_changed_frozen_packet(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            supply.write_packet(self.packet, output)
            bad = deepcopy(self.packet); bad['status'] = 'different'
            (output / 'input-v1.json').write_text(json.dumps(bad))
            with self.assertRaisesRegex(ValueError, 'Frozen V1 packet differs'):
                supply.write_packet(self.packet, output)

    def test_cli_defaults_to_check_and_paid_preflight_stops_locally(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            supply.write_packet(self.packet, output)
            runner = CliRunner()
            args = ['analysis', 'evidence-supply-review', '--output-dir', str(output)]
            before = (output / 'input-v1.json').read_bytes()
            result = runner.invoke(app, args)
            self.assertEqual(0, result.exit_code, result.output)
            self.assertEqual(before, (output / 'input-v1.json').read_bytes())
            result = runner.invoke(app, args + ['--paid-run-preflight'])
            self.assertNotEqual(0, result.exit_code)
            self.assertIn('blocked before provider construction', result.output)
            result = runner.invoke(app, args + ['--prepare-only', '--check-only'])
            self.assertNotEqual(0, result.exit_code)


if __name__ == '__main__':
    unittest.main()
